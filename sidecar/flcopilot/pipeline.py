"""Push-to-talk voice pipeline: ``ptt`` down/up -> clip -> transcript -> brain -> commands + speech.

Registered on the handler registry like any later-wave feature. In the test profile every
stage is a fake, so a ``ptt`` up deterministically yields a canned ``policy.set`` and a
``say`` (the policy round-trip script relies on this). W1-SIDECAR swaps in the real engines
and the grammar fast path; W4-BRAIN swaps in the real brain.
"""
from __future__ import annotations

import asyncio
import time

from . import logsetup
from .audio.capture import NullMic
from .profiles import Profile

log = logsetup.get("voice")


class VoicePipeline:
    def __init__(self, profile: Profile):
        self.profile = profile
        self._tasks: dict[asyncio.Task, object] = {}  # utterance task -> its session
        self._session = None  # the session that owns the mic
        self._pressed = False  # that session's key is down (ipc.md §7.2)
        self.utterances = 0
        self.cancelled = 0
        self.ignored_ptt = 0
        self.last_timing: dict = {}

    def install(self, registry) -> None:
        registry.register_handler("ptt", self.on_ptt)
        for t in ("ev.pause", "ev.menu", "ev.load"):
            registry.register_handler(t, self.on_tick_edge)
        registry.on_session_start(self.on_session_start)
        registry.on_session_end(self.on_session_end)

    # ---- session lifecycle -------------------------------------------------------------
    def on_session_start(self, session) -> None:
        self._session = session
        self._pressed = False
        try:
            self.profile.mic.reset()  # no recording state survives into a new session
            self.profile.mic.open()  # idempotent
        except Exception as exc:
            log.warning("mic open failed; voice input disabled", extra={"kv": {"err": repr(exc)[:200]}})
            self.profile.mic = NullMic()

    def on_session_end(self, session) -> None:
        # A replaced session can end after its successor started: only touch what it owns.
        for task, owner in list(self._tasks.items()):
            if owner is session:
                task.cancel()
        if session is not self._session:
            return
        self._session = None
        self._pressed = False
        try:
            self.profile.mic.cancel()  # a press held across the disconnect is cancelled (ipc.md §4.7)
            self.profile.mic.close()
        except Exception as exc:
            log.warning("mic close failed", extra={"kv": {"err": repr(exc)[:200]}})

    # ---- push-to-talk ------------------------------------------------------------------
    def _ignore(self, session, why: str) -> None:
        self.ignored_ptt += 1
        log.debug("ptt ignored", extra={"kv": {"sid": session.sid, "why": why}})

    def _cancel_press(self, session, reason: str) -> None:
        self._pressed = False
        self.profile.mic.cancel()
        self.cancelled += 1
        log.info("ptt cancelled", extra={"kv": {"sid": session.sid, "reason": reason}})

    def on_ptt(self, session, msg: dict) -> None:
        """Push-to-talk edges, tracked per session (ipc.md §7.2): only the session that owns the mic
        counts; a press while down, and a release or cancel while not down, are ignored."""
        if session is not self._session:
            self._ignore(session, "not the session that owns the mic")
            return
        if msg["down"]:
            if self._pressed:
                self._ignore(session, "down while already down")
                return
            self._pressed = True
            self.profile.mic.ptt_down()
            log.info("ptt down", extra={"kv": {"sid": session.sid}})
            return
        if not self._pressed:
            self._ignore(session, "release or cancel while not down")
            return
        if "reason" in msg:
            # Polling stopped with the key held (focus lost, pause, menu, chat): a cancel, not an order.
            self._cancel_press(session, msg["reason"])
            return
        self._pressed = False
        log.info("ptt up", extra={"kv": {"sid": session.sid}})
        task = asyncio.ensure_future(self._utterance(session, time.perf_counter()))
        self._tasks[task] = session
        task.add_done_callback(lambda t: self._tasks.pop(t, None))

    def on_tick_edge(self, session, msg: dict) -> None:
        """Backstop for a lost cancel: the tick stopping (ev.pause{on:true}), the main menu and a
        load each cancel a press that is still held (ipc.md §4.7.7). A stall edge
        (ev.pause{on:true, stall:true}) is a frame hitch, not a player action: the DLL keeps the press
        and sends its release later, so the press stays held here too (§4.7.1)."""
        if session is not self._session or not self._pressed:
            return
        if msg["t"] == "ev.pause":
            if not msg["on"]:
                return
            if msg.get("stall") is True:
                log.info("stall edge; ptt press kept", extra={"kv": {"sid": session.sid}})
                return
        self._cancel_press(session, msg["t"])

    async def _utterance(self, session, t_up: float) -> None:
        p = self.profile
        timing: dict = {}
        try:
            clip = await p.mic.ptt_up()
            timing["clip_ms"] = round((time.perf_counter() - t_up) * 1000, 1)
            if p.transcriber is None:
                log.info("no speech-to-text in this profile yet; utterance dropped")
                return
            if clip is None and not getattr(p.transcriber, "accepts_empty", False):
                log.info("no audio captured; utterance dropped", extra={"kv": {"sid": session.sid}})
                return
            result = await asyncio.to_thread(p.transcriber.transcribe, clip)
            timing["stt_ms"] = round((time.perf_counter() - t_up) * 1000, 1)
            text = (result.text or "").strip()
            log.info("utterance", extra={"kv": {"sid": session.sid, "text": text, "stt": getattr(p.transcriber, "name", "?")}})
            if not text:
                return
            if p.brain is None:
                log.info("no brain in this profile yet; utterance not acted on")
                return
            # In a thread: a real brain (W4, Claude CLI) takes seconds and must not stall pings or I/O.
            reply = await asyncio.to_thread(p.brain.respond, text, session.last_state)
            futures = []
            for cmd in reply.commands:
                futures.append(await session.send_command(cmd.t, **cmd.fields))
            timing["cmd_sent_ms"] = round((time.perf_counter() - t_up) * 1000, 1)
            if reply.say:
                futures.append(await session.send_command("say", speaker=reply.speaker, text=reply.say,
                                                          prio=1, subtitle=True))
                await asyncio.to_thread(self._speak, reply.say)
                timing["spoken_ms"] = round((time.perf_counter() - t_up) * 1000, 1)
            acks = await asyncio.gather(*futures)
            timing["acked_ms"] = round((time.perf_counter() - t_up) * 1000, 1)
            timing["acks_ok"] = sum(1 for a in acks if a and a.get("ok"))
            timing["acks"] = len(acks)
            self.utterances += 1
            self.last_timing = timing
            log.info("utterance handled", extra={"kv": {"sid": session.sid, **timing}})
        except asyncio.CancelledError:
            raise
        except ConnectionError as exc:
            log.info("session gone during utterance", extra={"kv": {"err": repr(exc)}})
        except Exception:
            log.exception("utterance failed")

    def _speak(self, text: str) -> None:
        p = self.profile
        if p.tts is None:
            log.info("no TTS in this profile yet; subtitle only")
            return
        for pcm, rate in p.tts.synthesize(text, voice=p.voice, speed=p.speed):
            p.sink.play(pcm, rate, label="say")
