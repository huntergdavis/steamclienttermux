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
| Easy distribution | One command installs the locked runtime, launchers, and NMS game-side compatibility DLLs | Fresh-device/update/rollback proof; package Android input patch |

| Component | Verified |
| --- | --- |
| Steam | Login, Store/Library rendering, downloads, preserved login state |
| Graphics | Hardware Vulkan through private Mesa Turnip |
| Windows games | Proton ARM64 + FEX + DXVK |
| Audio/input | PulseAudio; keyboard; touch and captured physical mouse are separate live paths |
| Controllers | Android hot-plug and app-local XInput transport pass; NMS still needs visible button/axis confirmation |
| Native path | Steam and CEF outside PRoot; allow-listed games use the direct dispatcher |
| Launch polish | Tomb Raider's pre-class Wine surface stays mapped off-screen until first paint |
| No Man's Sky | FEX 2512 + Steam Input reaches the real main menu without a new dump | Enter gameplay, prove controller input, then measure FPS |

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

The doctor rejects Termux:X11 revision `9471ad9`, which has an upstream
cursor-recenter regression. Use a current matching nightly.

The installer verifies every locked download before use. It fetches Valve's
ARM64 client seed directly from Valve and never bundles Steam, games, login
state, or credentials. It atomically activates a private mutable client tree,
is restartable, and keeps existing clients and user libraries intact.

This release preview prepares the locked runtime and installs the launchers.
A clean-device install/update/rollback run is still required before calling it
one-click.

## Use an installed stack

Start Steam from visible Termux:

```sh
~/start-steam.sh
```

Launch or stop a game session:

```sh
~/start-steam-game 203160
~/start-steam-game 203160 --mode benchmark
~/setup-no-mans-sky       # once, while Steam is stopped
~/start-no-mans-sky-direct
~/start-no-mans-sky-fps   # FPS/frame-time overlay plus private CSV log
~/stop-steam-native.sh
```

Map a new Windows game to the verified ARM64 Proton while Steam is stopped:

```sh
~/bin/configure-steam-app-proton APPID
```

The AppID command launches any installed game through Steam's generic route;
it does not require another game's tuning helpers. Reviewed shortcuts use the
same Steam handoff with stricter game-specific validation.
`~/start-tombraider.sh` is the Tomb Raider shortcut.

Startup prefetch is generic and manifest-driven, but remains off for Tomb Raider
because its tablet timing did not improve the 53.553-second best.

The launcher fails closed on stale X11 state, duplicate processes, background
scheduling, unverified windows, or mismatched artifacts.

## Installer status

The default base is Termux private storage. An SD card is optional and used
only for large game files; Proton prefixes and the runtime stay internal.
On affected Android versions, public `/storage/<UUID>/Steam/steamapps/common`
is faster than `Android/data`; the removable-library helper validates and
selects that same-volume layout without moving prefixes or control data.

| Automated | Still in progress |
| --- | --- |
| 36 Termux packages; Valve seed; Turnip | first-run UI polish |
| Native tgcompat; patched glibc; PRoot; Debian; launchers | fresh-device end-to-end proof |
| Idempotent, private staged promotion; NMS OpenVR/XInput payloads | patched Termux:X11 input build is not packaged yet |

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

Project-owned code is available under the [MIT License](LICENSE). Bundled or
downloaded components retain their own licenses and distribution terms; the
release manifest keeps those boundaries explicit.

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
