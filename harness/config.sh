# Harness configuration (P0-HARNESS). Sourced by every harness script via harness/lib/common.sh.
# Values here are measured/decided by P0-HARNESS; see harness/README.md and harness/NOTES.md for evidence.

# Number of concurrent lanes (TESTING §Lanes default 3). Measured on DXVK after the GPU reset (NOTES.md N11): 4
# instances at once (the whole 2x2 slot grid) ran clean at ~198 fps each, GPU <= 65 % busy, no recovery action.
LANES=${LANES:-4}
# Lane count when the renderer resolves to wined3d-sw (Mesa llvmpipe, CPU-bound): 2 instances already drop from
# 68.7 to 41 fps each (NOTES.md N11). lane.sh acquire without --lane uses min(LANES, LANES_SW) then.
LANES_SW=${LANES_SW:-2}
# Highest lane number lane.sh will ever hand out with an explicit --lane (slots beyond 4 overlap harmlessly).
LANES_MAX=${LANES_MAX:-8}

# Prefix layout (CONVENTIONS §1, BUILD_PLAN §3). The play prefix is a CLONE SOURCE ONLY.
FL_ROOT=/home/user/freelancer
PLAY_PREFIX=$FL_ROOT/prefix
BASE_PREFIX_A=$FL_ROOT/prefix-dev-base-A
BASE_PREFIX_B=$FL_ROOT/prefix-dev-base-B
LANE_PREFIX_STEM=$FL_ROOT/prefix-lane-
HDE_REL="drive_c/Games/Freelancer HD Edition"
SPEW_REL="drive_c/users/steamuser/AppData/Local/Freelancer/FLSpew.txt"

# Window slots: 2x2 grid of 1280x720 on the 3744x2106 X screen (R4 §0.5).
LANE_W=1280
LANE_H=720

# Per-lane sidecar port (CONVENTIONS §7). Lane N -> 29170+N; the play install uses 29170.
FLCOPILOT_PORT_BASE=29170

# Lane runtime environment (REQ-P0-HARNESS-11, R4 §B6/§B7).
RUN_WINEDEBUG="fixme-all,+seh,+loaddll"
RUN_DXVK_LOG_LEVEL=${RUN_DXVK_LOG_LEVEL:-warn}
# Frame cap: DXVK v3.1.1 (Proton 11) has no DXVK_FRAME_RATE env var any more (the string is absent from its d3d9.dll);
# the config key d3d9.maxFrameRate caps presents at 60 (NOTES.md N17). presentInterval 0 = no vsync on the 29.97 Hz panel.
RUN_DXVK_CONFIG=${RUN_DXVK_CONFIG:-"d3d9.presentInterval = 0; d3d9.maxFrameRate = 60"}
RUN_DXVK_HUD=${RUN_DXVK_HUD:-}   # e.g. fps,frametimes for frame-pacing experiments (NOTES.md N17)

# Lock lease: a lane's lock-holder process exits by itself after this many seconds (leaked locks expire).
LOCK_TTL_S=${LOCK_TTL_S:-14400}

# Window identification method chosen by the REQ-8 evaluation: pid | desktop | serial.
WINDOW_METHOD=${WINDOW_METHOD:-pid}

# Display: lanes run on X :0 only. gamescope nested/headless was evaluated (worked with ENABLE_GAMESCOPE_WSI=0:
# menu + gamescopectl screenshots, NOTES.md N3) but its Xwayland caused GPU Xid 51/154 at 05:28Z; gamescope is banned
# on this host (D103). REQ-9 verdict: headless lanes via gamescope NOT VIABLE.
HEADLESS_USABLE=0
# x11 = game window directly on :0; vdesk = per-lane Wine virtual desktop (explorer /desktop=lane<N>,1280x720).
# FLUF (Track A) forces the game resolution to the desktop size, so A uses vdesk (NOTES.md N2).
DISPLAY_MODE_A=${DISPLAY_MODE_A:-vdesk}
DISPLAY_MODE_B=${DISPLAY_MODE_B:-x11}

# Renderer (D103): auto | dxvk | wined3d | wined3d-sw. auto = dxvk if a Vulkan device can be created, else
# RENDERER_FALLBACK. wined3d = Wine's builtin d3d8/d3d9 on the host OpenGL; wined3d-sw = the same on Mesa llvmpipe
# (no GPU at all). With the GPU degraded (NOTES.md N8/N10) hardware GL fails too, so the fallback is wined3d-sw.
# Lane environment only (WINEDLLOVERRIDES, GLVND vendor). Every run records renderer= in run.json and verdict.json;
# spew allow-lists are keyed per track and renderer (baseline/spew_allow_<A|B>_<renderer>.txt).
RENDERER_DEFAULT=auto   # $FLMOD_RENDERER or run.sh --renderer override
RENDERER_FALLBACK=wined3d-sw
RENDERER_WINED3D_OVERRIDES="d3d8=b;d3d9=b"

# Hang detection: no growth of FLSpew/devbridge log for this long while commands are pending => HANG.
HANG_S=${HANG_S:-60}
# Upper bound for the hang minidump (winedbg suspends the game; aborted early if X stops answering, NOTES.md N6).
HANG_DUMP_S=${HANG_DUMP_S:-30}

# Crash-offsets table (TESTING §CrashTriage).
CRASH_OFFSETS_JSON=/home/user/freelancer/refs/StarportKnowledgeBase/static/payloads/crash-offsets.json
CRASH_OFFSETS_JSON_ALT=/home/user/freelancer/refs/starport-kb-payload/crash-offsets.json
