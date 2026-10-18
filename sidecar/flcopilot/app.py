"""Assemble a runnable sidecar: config + profile + registry + features + server."""
from __future__ import annotations

from dataclasses import dataclass

from .pipeline import VoicePipeline
from .profiles import Profile, build_profile
from .registry import HandlerRegistry
from .server import SidecarServer


@dataclass
class App:
    server: SidecarServer
    profile: Profile
    registry: HandlerRegistry
    pipeline: VoicePipeline


def build_app(cfg, profile_name: str, mic_file=None, null_wav_dir=None, env=None) -> App:
    profile = build_profile(profile_name, cfg, mic_file=mic_file, null_wav_dir=null_wav_dir, env=env)
    registry = HandlerRegistry()
    pipeline = VoicePipeline(profile)
    pipeline.install(registry)
    # Later waves register their features here (memory, grammar, brain, ...).
    server = SidecarServer.from_config(cfg, registry=registry, features=profile.features,
                                       profile_name=profile.name)
    return App(server=server, profile=profile, registry=registry, pipeline=pipeline)
