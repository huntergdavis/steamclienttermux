# Steam ARM64 on Termux/X11

Run Valve's native ARM64 Steam client and Windows games on an **unrooted
Samsung Galaxy Tab S8+** with Termux, Termux:X11, Mesa Turnip, Proton ARM64,
FEX, and DXVK.

![GTA IV at its main menu](docs/evidence/gtaiv-main-menu-2026-08-13.png)

This is a measured research stack, not yet a one-click Android app. It does not
contain Valve binaries, games, credentials, or account state.

## Current status

| Goal | Best verified result | Next gate |
| --- | --- | --- |
| Tomb Raider performance | 1080p tuned Ultra: **30.7 FPS average** | Replicate and generalize the profile |
| Steam startup | Warm visible UI: **27.329s -> 2.254s** | Measure Library/Store interaction latency |
| Easy distribution | Manifest-locked Valve ARM64 bootstrap works | Deterministic installer archive and rollback test |

| Component | Verified |
| --- | --- |
| Steam | Login, Store/Library rendering, downloads, preserved login state |
| Graphics | Hardware Vulkan through private Mesa Turnip |
| Windows games | Proton ARM64 + FEX + DXVK |
| Audio/input | PulseAudio and Termux:X11 mouse, touch, and keyboard |
| Native path | Steam and CEF outside PRoot; allow-listed games use the direct dispatcher |

## Best measurements

| Workload | Configuration | Min / max / average | Evidence |
| --- | --- | ---: | --- |
| Tomb Raider (2013) | 1920x1080 tuned Ultra, exclusive fullscreen | 17.3 / 39.8 / **30.7 FPS** | [JSON](docs/benchmark-series/tombraider-direct-glibc-dxvk-241-x32-1080p-ultra-no-tessellation-ssao1-dof1-shadow0-fullscreen-60hz-40c-20260824.json) |
| Tomb Raider (2013) | 1280x720 Normal, exclusive fullscreen | 35.8 / 74.4 / **59.1 FPS** | [JSON](docs/benchmark-series/tombraider-direct-glibc-dxvk-241-x32-720p-normal-fullscreen-60hz-20260823.json) |
| Steam warm visible UI | Existing authenticated native session | **2.254 seconds** | [Timing log](docs/STEAM_TIMINGS.md) |

The tuned-Ultra profile keeps Ultra textures/filtering, LOD4, reflections, and
high-precision rendering. Tessellation, TressFX hair, and motion blur are off;
SSAO and depth of field use mode 1; shadows stay enabled at resolution 0.

## Quick start

Install official Termux and a matching shared-UID Termux:X11 build first. Then
prepare this checkout:

```sh
scripts/inventory.sh
scripts/build-proot.sh
scripts/prepare-arm64-runtime-shadow.sh
scripts/install-project-files.sh
scripts/verify-gpu.sh
```

Start the minimal Steam session from visible Termux:

```sh
~/start-steam.sh
```

Launch or stop a game session:

```sh
~/start-steam.sh --appid 203160 -- -nolauncher
~/start-tombraider-native.sh
~/stop-steam-native.sh
```

The launcher fails closed on stale X11 state, duplicate processes, background
scheduling, unverified windows, or mismatched artifacts.

## Reproducible packaging

The project fetches the ARM64 Steam seed directly from Valve and verifies the
pinned manifest, archive, members, symlinks, and executable before promotion:

```sh
python3 scripts/bootstrap-steam-arm64-client.py install \
  --cache "$HOME/steam-arm64/download-cache" \
  --destination "$HOME/steam-arm64/client-seed"
```

The intended first release is a signed/checksummed Termux bootstrap archive
containing only our open-source code and locks. See [productization
research](docs/PRODUCTIZATION_RESEARCH.md) and [packaging](docs/PACKAGING.md).

## Documentation

| Need | Document |
| --- | --- |
| Steam performance timeline | [Steam timings](docs/STEAM_TIMINGS.md) |
| Product/release design | [Productization research](docs/PRODUCTIZATION_RESEARCH.md) |
| Complete Tomb Raider results | [Benchmark report](docs/TOMB_RAIDER_BENCHMARK.md) |
| Architecture boundaries | [Architecture](docs/ARCHITECTURE.md) |
| Binary provenance | [External inputs](docs/PROPRIETARY_AND_BINARY_INPUTS.md) |
| Chronological investigation | [Technical log](docs/TECHNICAL_LOG.md) |
| Machine-readable runs | [`docs/benchmark-series/`](docs/benchmark-series/) |

The separate
[`bionic-vulkan-bridge`](https://github.com/huntergdavis/bionic-vulkan-bridge)
remains an experimental graphics-bridge project. It has not established a game
performance gain and is not the current production route.

## Validate

```sh
scripts/check-project.sh
```

Every promoted timing or benchmark must retain its configuration, artifact
identity, thermal/display conditions, and any exclusion reason.
