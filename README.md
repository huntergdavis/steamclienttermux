# Steam ARM64 on Termux/X11

Run Valve's native ARM64 Linux Steam client and Windows games on an
**unrooted Samsung Galaxy Tab S8+** using Termux, Termux:X11, Mesa Turnip,
official Proton 11 ARM64, FEX, and DXVK.

![GTA IV at its main menu on the Tab S8+](docs/evidence/gtaiv-main-menu-2026-08-13.png)

This is an experimental, measured compatibility stack—not a turnkey Android
app. The working tablet is an SM-X808U with a Snapdragon 8 Gen 1, Adreno 730,
7.12 GiB usable RAM, and Android 16. It requires no root, bootloader unlock,
custom kernel, chroot, or system-wide library replacement.

## What works

| Component | Verified state |
| --- | --- |
| Steam | Authenticates, renders, downloads, and retains login state |
| Graphics | Hardware Vulkan through private Mesa Turnip |
| Windows games | Official Proton 11 ARM64 + FEX + DXVK |
| Audio/input | PulseAudio and Termux:X11 pointer/keyboard support |
| Storage | Game payloads on microSD; lock-sensitive Steam metadata on internal F2FS |
| Native host | Steam and CEF run outside PRoot; the game boundary still enters PRoot |

Verified game milestones:

| Game | Current result | Details |
| --- | --- | --- |
| Tomb Raider (2013) | Panel-native game and built-in benchmark run repeatedly | [Benchmark log](docs/TOMB_RAIDER_BENCHMARK.md) |
| Grand Theft Auto IV | Saved Rockstar authentication, selector, main menu, loading sequence, and first mission | [Technical log](docs/TECHNICAL_LOG.md#2026-08-17-native-steam-reaches-authenticated-gta-iv) |
| Superflight | Fullscreen rendering with working audio | [Technical log](docs/TECHNICAL_LOG.md#2026-08-09-superflight-proves-dxvkturnip-and-working-pulse-audio) |
| Kingsway | Runs from the split microSD library | [Technical log](docs/TECHNICAL_LOG.md#2026-08-10-kingsway-survives-restart-and-runs-from-the-microsd) |
| Burnout Paradise Remastered | Experimental; EA and renderer issues remain | [Technical log](docs/TECHNICAL_LOG.md#2026-08-08-first-complete-burnout-launch-trace) |

The native-glibc host reduced Tomb Raider's comparable Runtime-request-to-window
interval from **407.236 seconds to 58.256 seconds**: 85.7% shorter, or 6.99x as
fast. FPS gains are much smaller because Proton/FEX and the remaining game-side
PRoot boundary still dominate runtime work. See the
[launch artifacts](docs/launch-timings/) and [performance analysis](docs/PERFORMANCE.md).

## Tomb Raider benchmark snapshot

These are the committed controlled native-glibc series for the current target:
2800x1752, Low, motion blur off, V-Sync off, one warm-up, and three recorded
runs. “Mean” is the mean of the three game-authored results, shown as
minimum/maximum/average FPS.

| FEX profile | X11 refresh | Recorded average FPS | Mean min/max/avg | Start condition | Raw data |
| --- | ---: | --- | ---: | --- | --- |
| `safe` | 119.92 Hz | 24.8 / 22.7 / 22.7 | 15.767 / 32.567 / **23.400** | 37.0–40.7 °C observed | [JSON](docs/benchmark-series/tombraider-native-glibc-safe-119hz-20260817.json) |
| `safe` | 59.97 Hz | 25.3 / 24.9 / 25.3 | 16.200 / 34.500 / **25.167** | 37.0 °C observed | [JSON](docs/benchmark-series/tombraider-native-glibc-safe-60hz-20260817.json) |
| bundled Proton | 59.97 Hz | 23.2 / 23.1 / 22.6 | 14.200 / 31.233 / **22.967** | 45.1–47.9 °C; unmatched | [JSON](docs/benchmark-series/tombraider-native-glibc-proton-60hz-unmatched-20260817.json) |
| bundled Proton | 59.97 Hz | 22.8 / 22.7 / 25.2 | 12.500 / 32.967 / **23.567** | Fixed 40 °C ceiling; starts 37.0–37.6 °C | [JSON](docs/benchmark-series/tombraider-native-glibc-proton-60hz-40c-20260817.json) |
| `fast` | 59.97 Hz | 25.5 / 23.0 / 22.9 | 16.367 / 32.300 / **23.800** | Fixed 40 °C ceiling; all starts 37.0 °C | [JSON](docs/benchmark-series/tombraider-native-glibc-fast-60hz-40c-20260817.json) |

The 59.97 Hz `safe` series is the current leader at **25.167 average FPS**. It
is 7.6% faster than the same profile at 119.92 Hz and 6.8% faster than bundled
Proton under the matched comparison. The unmatched Proton row is retained for
audit, not used to select a profile. The matched `fast` profile averaged 23.800
FPS: 5.4% below `safe` and only 1.0% above bundled Proton, so `safe` remains the
production profile.

Read the [full Tomb Raider report](docs/TOMB_RAIDER_BENCHMARK.md) for every
historical pass, exclusions, thermal state, affinity evidence, and methodology.
The [optimization plan](docs/TOMB_RAIDER_OPTIMIZATION_PLAN.md) ranks the next
experiments.

## Quick start

The proprietary Steam, Proton, Runtime, and Mesa payloads are intentionally not
in this repository. Obtain and verify them first as described in
[External binary inputs](docs/PROPRIETARY_AND_BINARY_INPUTS.md).

Prepare the project:

```sh
scripts/inventory.sh
scripts/build-proot.sh
scripts/prepare-arm64-runtime-shadow.sh
scripts/install-project-files.sh
scripts/verify-gpu.sh
```

Start Steam from a **visibly foreground Termux terminal**, not an SSH shell:

```sh
~/start-steam.sh
```

The launcher brings up the shared-UID Termux:X11 activity, one X server,
PulseAudio, input devices, and Steam without KDE. It fails closed on stale X11
Binder state, duplicate servers, background scheduling, or an unverified Steam
window.

Launch a game directly:

```sh
~/start-steam.sh --appid 203160 -- -nolauncher
~/start-tombraider.sh
~/start-tombraider-native.sh
```

`start-steam.sh` is the established all-PRoot route. The `-native` wrapper runs
Steam and CEF through the separate
[`termux-glibc-compat`](https://github.com/huntergdavis/termux-glibc-compat)
host, then crosses into the existing PRoot environment at the game boundary.
It preserves the same Steam library and authenticated state.

After exiting the game, stop the minimal session cleanly:

```sh
~/stop-steam.sh
~/stop-steam-native.sh
```

Both stop scripts protect a running game and avoid force-stopping the shared
Termux UID. Use their explicit `--force` option only when intentional.

## Benchmark Tomb Raider

For the current panel-native, 60 Hz tests, set Samsung Motion smoothness to
**Standard** and verify that XRandR reports approximately 59.97 Hz. Keep
Termux:X11 visible so the shared UID remains in Android's `/top-app` group.

Run a controlled series:

```sh
~/run-tombraider-native-benchmark --profile safe
~/test-tomb-raider-proton-40c-ceiling.sh
~/test-tomb-raider-fast-40c-ceiling.sh
```

Each series performs one warm-up and three recorded runs. Before every pass it
waits for full CPU/GPU policy, thermal level zero, stable temperature samples,
and the configured ceiling. It records the game's result file, display mode,
thermals, memory, clocks, affinity, and cooldown duration in JSON.

Do not profile, take screenshots, or switch Android windows during a timed
scene. Capture evidence after the result appears.

## Practical notes

- Use the official shared-UID Termux:X11 build. The standalone UID can be
  demoted to Android's background groups when Termux is hidden.
- Keep Steam metadata, compatdata, downloads, and active staging on internal
  storage. Put only large game payloads on portable storage.
- `cleanup-steam-temp` is dry-run by default; `--apply` removes only validated,
  old, closed Steam shared-memory files.
- A changed FEX profile applies only to a fresh Steam process.
- This repository never contains Steam credentials, Rockstar credentials,
  2FA tokens, proprietary client binaries, or game files.

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — compatibility and isolation boundaries
- [Performance](docs/PERFORMANCE.md) — measured PRoot bottlenecks and prototypes
- [Tomb Raider benchmark](docs/TOMB_RAIDER_BENCHMARK.md) — complete game results
- [Tomb Raider optimization plan](docs/TOMB_RAIDER_OPTIMIZATION_PLAN.md) — next tests
- [Technical log](docs/TECHNICAL_LOG.md) — chronological debugging evidence
- [Visual evidence](docs/evidence/README.md) — screenshots removed from this page
- [External binary inputs](docs/PROPRIETARY_AND_BINARY_INPUTS.md) — required artifacts

Important implementation paths:

- [`bin/steam-arm`](bin/steam-arm) — production launcher
- [`scripts/`](scripts/) — setup, validation, launch, and tuning tools
- [`patches/`](patches/) — reproducible PRoot patch series
- [`config/steam-arm64-compatibilitytools.vdf.in`](config/steam-arm64-compatibilitytools.vdf.in)
  — official ARM64 Proton/runtime registration
- [`docs/benchmark-series/`](docs/benchmark-series/) — machine-readable results

## Validate

```sh
scripts/check-project.sh
```

The check runs the retained test suite, parses shell entry points, and rejects
whitespace errors. Before reporting a new performance result, also commit its
raw JSON artifact and document any excluded or thermally unmatched run.
