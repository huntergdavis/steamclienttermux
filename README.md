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
| Steam startup | UI **1.662s**; AppID-to-window **53.553s** | Validate generic startup prefetch; reduce CPU-bound graphics init |
| Easy distribution | Reproducible ZIP + tablet-tested read-only doctor | Bootstrap/rollback workflow |

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
| Steam warm visible UI | Existing authenticated native session | **1.662 seconds** | [Timing log](docs/STEAM_TIMINGS.md) |
| Steam AppID to Tomb Raider | Warm direct session, FEX generation 6, DXVK 2.4.1 | **53.553 seconds** | [Timing log](docs/STEAM_TIMINGS.md) |

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
~/start-tombraider-direct-raknet-backoff
~/stop-steam-native.sh
```

The direct Tomb Raider command is the current optimized path. The plain
`start-tombraider-native.sh` route remains available as a compatibility
control.

Startup tuning uses a shared bounded prefetch engine plus reviewed per-game
manifests; it remains opt-in until its tablet A/B is conclusive.

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
containing only project source code and locks. See [productization
research](docs/PRODUCTIZATION_RESEARCH.md) and [packaging](docs/PACKAGING.md).

Check a device without changing it:

```sh
python3 scripts/steam-stack-doctor.py --mode bootstrap
```

Build the current commit's deterministic candidate archive:

```sh
python3 scripts/build-release-archive.py \
  --destination "$PWD/dist/release-candidate"
```

Public open-source release remains blocked until the project owner selects and
adds a license; the builder reports that state in `release-manifest.json`.

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
