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
| Steam startup | UI **1.662s**; cold AppID **21.80s**; cold game **49.513s** | Connect AppID acceptance to the direct game route |
| Easy distribution | Locked ZIP bootstrap through minimal Debian | Package product launchers and first-run setup |

| Component | Verified |
| --- | --- |
| Steam | Login, Store/Library rendering, downloads, preserved login state |
| Graphics | Hardware Vulkan through private Mesa Turnip |
| Windows games | Proton ARM64 + FEX + DXVK |
| Audio/input | PulseAudio and Termux:X11 mouse, touch, and keyboard |
| Native path | Steam and CEF outside PRoot; allow-listed games use the direct dispatcher |
| Launch polish | Tomb Raider's pre-class Wine surface stays mapped off-screen until first paint |

## Best measurements

| Workload | Configuration | Min / max / average | Evidence |
| --- | --- | ---: | --- |
| Tomb Raider (2013) | 1920x1080 tuned Ultra, exclusive fullscreen | 17.3 / 39.8 / **30.7 FPS** | [JSON](docs/benchmark-series/tombraider-direct-glibc-dxvk-241-x32-1080p-ultra-no-tessellation-ssao1-dof1-shadow0-fullscreen-60hz-40c-20260824.json) |
| Tomb Raider (2013) | 1280x720 Normal, exclusive fullscreen | 35.8 / 74.4 / **59.1 FPS** | [JSON](docs/benchmark-series/tombraider-direct-glibc-dxvk-241-x32-720p-normal-fullscreen-60hz-20260823.json) |
| Steam warm visible UI | Existing authenticated native session | **1.662 seconds** | [Timing log](docs/STEAM_TIMINGS.md) |
| Cold Steam to AppID acceptance | Deterministic X11, controller-safe default | **21.80 seconds** | [Timing log](docs/STEAM_TIMINGS.md) |
| Cold Steam to Tomb Raider window | No Steam or X11 process; native ARM64 route | **49.513 seconds** | [Timing log](docs/STEAM_TIMINGS.md) |
| Steam AppID to Tomb Raider | Warm direct session, FEX generation 6, DXVK 2.4.1 | **53.553 seconds** | [Timing log](docs/STEAM_TIMINGS.md) |

The tuned-Ultra profile keeps Ultra textures/filtering, LOD4, reflections, and
high-precision rendering. Tessellation, TressFX hair, and motion blur are off;
SSAO and depth of field use mode 1; shadows stay enabled at resolution 0.

## Install

Install official Termux and the matching Termux:X11 build from the same
trusted source. Unpack a release inside Termux, enter its directory, and run:

```sh
./install.sh
```

The installer verifies every locked download before use. It fetches Valve's
ARM64 client seed directly from Valve and never bundles Steam, games, login
state, or credentials. It is restartable and keeps user libraries intact.

This release preview prepares the complete locked runtime. Installing the
small product-launcher set and proving the whole flow on a clean device are the
remaining one-command gates; do not describe it as finished or one-click yet.

## Use an installed stack

Start Steam from visible Termux:

```sh
~/start-steam.sh
```

Launch or stop a game session:

```sh
~/start-steam-game 203160
~/start-steam-game 203160 --mode benchmark
~/stop-steam-native.sh
```

The AppID command launches any installed game through Steam's generic route;
it does not require another game's tuning helpers. A reviewed manifest entry
can replace that route with measured optimizations.
`~/start-tombraider.sh` is the Tomb Raider shortcut.

Startup prefetch is generic and manifest-driven, but remains off for Tomb Raider
because its tablet timing did not improve the 53.553-second best.

The launcher fails closed on stale X11 state, duplicate processes, background
scheduling, unverified windows, or mismatched artifacts.

## Installer status

The default base is Termux private storage. An SD card is optional and used
only for large game files; Proton prefixes and the runtime stay internal.

| Automated | Still in progress |
| --- | --- |
| 36 Termux packages; Valve seed; Turnip | product launchers and first-run setup |
| Native tgcompat; patched glibc; PRoot; Debian | fresh-device end-to-end proof |
| Idempotent, private staged promotion | full rollback and fresh-device proof |

The release ZIP contains project source plus the audited open-source glibc
package—never Valve binaries, games, credentials, or account data. Long-term,
the same engine becomes a signed Termux-repository `.deb`. See
[packaging](docs/PACKAGING.md).

Run the read-only prerequisite check separately when needed:

```sh
python3 scripts/steam-stack-doctor.py --mode bootstrap
```

Build the current commit's deterministic candidate archive:

```sh
python3 scripts/build-release-archive.py \
  --glibc-package /path/to/glibc_2.44_signalfix_aarch64.deb \
  --destination "$PWD/dist/release-candidate"
```

Public open-source release remains blocked until the project owner selects and
adds a license; the builder reports that state in `release-manifest.json`.

## Documentation

| Need | Document |
| --- | --- |
| Steam performance timeline | [Steam timings](docs/STEAM_TIMINGS.md) |
| Product/release design | [Productization research](docs/PRODUCTIZATION_RESEARCH.md) |
| No Man's Sky profile | [1080p configuration and save safety](docs/NO_MANS_SKY.md) |
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
