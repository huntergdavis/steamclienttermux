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
| Native host | Steam and CEF run outside PRoot; validated games can use the narrow direct dispatcher |

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
fast. The direct game dispatcher also removes the remaining hot PRoot boundary
for its exact allow-listed commands. See the
[launch artifacts](docs/launch-timings/) and [performance analysis](docs/PERFORMANCE.md).

The experimental
[`bionic-vulkan-bridge`](https://github.com/huntergdavis/bionic-vulkan-bridge)
explores a direct glibc-to-Android system-Vulkan path and has proved
cross-process Adreno rendering and image sharing. It does not yet render Tomb
Raider or establish a game FPS gain; its current status and evidence live in
the bridge repository.

## Tomb Raider benchmark snapshot

### Validated resolution and quality matrix

The first DXVK optimization at the new comparison target is complete. Tomb Raider
rendered internally at 1280x720 Normal in exclusive fullscreen while
Termux:X11 occupied the full 2800x1752 tablet panel at 59.97 Hz. V-Sync and
motion blur were off. Two independent game-authored passes with official x32
DXVK 2.4.1 both averaged 59.1 FPS.

| DXVK | FEX profile | Game resolution/profile | X11 surface | Min/max/average FPS | Evidence |
| --- | --- | --- | --- | ---: | --- |
| official 2.4.1 x32 | `safe`, offline-compiled cache generation 5 | 1280x720 Normal, exclusive fullscreen | Borderless 2800x1752 at 59.97 Hz | 35.8 / 74.4 / **59.1**; repeat 15.7 / 72.5 / **59.1** | [JSON](docs/benchmark-series/tombraider-direct-glibc-dxvk-241-x32-720p-normal-fullscreen-60hz-20260823.json) |
| official 2.4.1 x32 | `safe`, offline-compiled cache generation 5 | 1280x720 High (`QualityLevel=2`), exclusive fullscreen | Borderless 2800x1752 at 59.97 Hz | 31.4 / 59.4 / **47.5** | [JSON](docs/benchmark-series/tombraider-direct-glibc-dxvk-241-x32-720p-high-fullscreen-60hz-40c-20260824.json) |
| official 2.4.1 x32 | `safe`, offline-compiled cache generation 5 | 1280x720 Ultra (`QualityLevel=3`), exclusive fullscreen | Borderless 2800x1752 at 59.97 Hz | 16.3 / 22.0 / **19.4** | [JSON](docs/benchmark-series/tombraider-direct-glibc-dxvk-241-x32-720p-ultra-fullscreen-60hz-40c-20260824.json) |
| official 2.4.1 x32 | `safe`, offline-compiled cache generation 5 | 1280x720 Ultimate (`QualityLevel=4`), exclusive fullscreen | Borderless 2800x1752 at 59.97 Hz | 10.8 / 18.2 / **14.2** | [JSON](docs/benchmark-series/tombraider-direct-glibc-dxvk-241-x32-720p-ultimate-fullscreen-60hz-40c-20260824.json) |
| official 2.4.1 x32 | `safe`, offline-compiled cache generation 5 | 1920x1080 Normal, exclusive fullscreen | Borderless 2800x1752 at 59.97 Hz | 29.2 / 65.5 / **44.8** | [JSON](docs/benchmark-series/tombraider-direct-glibc-dxvk-241-x32-1080p-normal-fullscreen-60hz-40c-20260824.json) |
| official 2.4.1 x32 | `safe`, offline-compiled cache generation 5 | 1920x1080 High (`QualityLevel=2`), exclusive fullscreen | Borderless 2800x1752 at 59.97 Hz | 17.2 / 37.3 / **28.7** | [JSON](docs/benchmark-series/tombraider-direct-glibc-dxvk-241-x32-1080p-high-fullscreen-60hz-40c-20260824.json) |
| official 2.4.1 x32 | `safe`, offline-compiled cache generation 5 | 1920x1080 Ultra (`QualityLevel=3`), exclusive fullscreen | Borderless 2800x1752 at 59.97 Hz | 7.2 / 12.8 / **10.0** | [JSON](docs/benchmark-series/tombraider-direct-glibc-dxvk-241-x32-1080p-ultra-fullscreen-60hz-40c-20260824.json) |
| official 2.4.1 x32, 4 compiler workers (rejected) | `safe`, offline-compiled cache generation 5 | 1920x1080 Normal, exclusive fullscreen | Borderless 2800x1752 at 59.97 Hz | 27.7 / 63.1 / **44.3** | [JSON](docs/benchmark-series/tombraider-direct-glibc-dxvk-241-compiler4-1080p-normal-fullscreen-60hz-40c-20260824.json) |
| official 1.10.3 x32 | `safe`, offline-compiled cache generation 5 | 1280x720 Normal, exclusive fullscreen | Borderless 2800x1752 at 59.97 Hz | 27.9 / 70.3 / **55.6** | [JSON](docs/benchmark-series/tombraider-direct-glibc-dxvk-1103-x32-720p-normal-fullscreen-60hz-40c-20260824.json) |
| Proton 11 bundled DXVK | `safe`, offline-compiled cache generation 5 | 1280x720 Normal, exclusive fullscreen | Borderless 2800x1752 at 59.97 Hz | 33.7 / 61.6 / **52.0** | [JSON](docs/benchmark-series/tombraider-direct-glibc-safe-offline-compiled-720p-normal-fullscreen-60hz-40c-first-20260823.json) |

The earlier 34.1 and 29.7 FPS 720p attempts are excluded because the Android
controller left Termux:X11 in a 520x320 floating window. The coherent 2.4.1
swap improves the validated 52.0 FPS control by 7.1 FPS, or 13.7%. Its two
minimum-FPS readings differ substantially, so 59.1 is the promoted throughput
result rather than a frame-pacing claim. Official 1.10.3 x32 was also valid at
55.6 FPS: 6.9% faster than bundled, but 5.9% slower than 2.4.1.

The first controlled 1080p Normal pass averaged 44.8 FPS and held a 29.2 FPS
minimum. Rendering 2.25x as many pixels reduced average throughput by only
24.2% versus 720p, confirming that pixel fill alone does not dominate this
stack. It is one thermally valid sample, so it is a baseline rather than a
replicated promotion.

The first exact 720p High pass averaged 47.5 FPS and held a 31.4 FPS minimum.
High costs 11.6 FPS / 19.6% versus 720p Normal; its game-authored settings
raise texture filtering, shadow resolution, reflections, LOD, and enable the
high-precision render target while leaving TressFX and tessellation off.

Ultra averaged 19.4 FPS, losing 28.1 FPS / 59.2% versus High. Its aggregate
preset simultaneously enables tessellation and raises texture quality,
anisotropic filtering, SSAO, depth of field, and LOD. This is the first clear
quality-setting cliff; the matrix must separate those changes before assigning
the cost to one feature.

Ultimate averaged 14.2 FPS, 5.2 FPS / 26.8% below Ultra. The game-authored
settings differ from Ultra only by enabling TressFX hair, making hair the
isolated cause of this second quality step under the controlled benchmark.

At 1080p, High averaged 28.7 FPS, 16.1 FPS / 35.9% below 1080p Normal.
The same High profile therefore crosses below the 30 FPS target when pixel
count rises from 720p to 1080p.

1080p Ultra averaged 10.0 FPS, 18.7 FPS / 65.2% below 1080p High. Because the
same transition costs 59.2% at 720p, the Ultra bundle grows more expensive
with pixel count and is substantially GPU/shader/bandwidth sensitive.

Forcing four DXVK compiler workers reduced the 1080p result to 44.3 FPS,
1.1% below DXVK's automatic seven-worker choice, with lower minimum and maximum
FPS as well. Automatic selection remains the 1080p default.

### Historical panel-native Low target

These are the committed controlled native-glibc series for the previous
2800x1752 Low target: motion blur off, V-Sync off, one warm-up, and three
recorded runs. “Mean” is the mean of the three game-authored results, shown as
minimum/maximum/average FPS.

| FEX profile | Resolution | X11 refresh | Recorded average FPS | Mean min/max/avg | Start condition | Raw data |
| --- | ---: | ---: | --- | ---: | --- | --- |
| `safe` (FEX 128 MiB JIT buffer/code maps) | 2800×1752 | 59.97 Hz | 35.3 / 34.6 / 32.1 | 20.667 / 46.433 / **34.000** | Fixed 40 °C ceiling; promoted | [JSON](docs/benchmark-series/tombraider-direct-glibc-safe-fex-max-buffer-60hz-40c-20260823.json) |
| `safe` (immediate FEX reverse control) | 2800×1752 | 59.97 Hz | 33.3 / 33.8 / 31.9 | 21.500 / 46.800 / **33.000** | Fixed 40 °C ceiling | [JSON](docs/benchmark-series/tombraider-direct-glibc-safe-fex-max-buffer-reverse-control-60hz-40c-20260823.json) |
| `safe` | 2800×1752 | 119.92 Hz | 24.8 / 22.7 / 22.7 | 15.767 / 32.567 / **23.400** | 37.0–40.7 °C observed | [JSON](docs/benchmark-series/tombraider-native-glibc-safe-119hz-20260817.json) |
| `safe` | 2800×1752 | 59.97 Hz | 25.3 / 24.9 / 25.3 | 16.200 / 34.500 / **25.167** | 37.0 °C observed | [JSON](docs/benchmark-series/tombraider-native-glibc-safe-60hz-20260817.json) |
| `safe` (direct game) | 2800×1752 | 59.97 Hz | 31.1 / 30.3 / 30.3 | 18.900 / 47.733 / **30.567** | Fixed 40 °C ceiling; all starts 37.0 °C | [JSON](docs/benchmark-series/tombraider-direct-glibc-safe-60hz-40c-20260818.json) |
| `safe` (direct game, topology fix) | 2800×1752 | 59.97 Hz | 30.6 / 30.2 / 30.4 | 21.000 / 46.133 / **30.400** | Fixed 40 °C ceiling; starts 37.0–37.9 °C | [JSON](docs/benchmark-series/tombraider-direct-glibc-safe-topology-fix-60hz-40c-20260818.json) |
| `safe` (direct game, RakNet backoff) | 2800×1752 | 59.97 Hz | 32.9 / 31.3 / 30.7 | 20.300 / 46.767 / **31.633** | Fixed 40 °C ceiling; all starts 37.0 °C; promoted | [JSON](docs/benchmark-series/tombraider-direct-glibc-safe-raknet-backoff-60hz-40c-20260822.json) |
| `safe` (post-RakNet CEF controls) | 2800×1752 | 59.97 Hz | 32.0 / 33.0 / 33.0 | 20.100 / 46.667 / **32.667** | Alternating 40 °C gate; current default control | [JSON](docs/evidence/tombraider-direct-cef-hold-revisit-20260823.json) |
| `safe` (post-RakNet CEF hold) | 2800×1752 | 59.97 Hz | 33.3 / 32.5 / 32.8 | 20.167 / 45.533 / **32.867** | Alternating 40 °C gate; +0.61%; rejected | [JSON](docs/evidence/tombraider-direct-cef-hold-revisit-20260823.json) |
| `proton` (direct game, topology fix) | 2800×1752 | 59.97 Hz | 32.1 / 31.2 / 30.6 | 20.400 / 45.567 / **31.300** | Fixed 40 °C ceiling; starts 37.0–37.2 °C; candidate | [JSON](docs/benchmark-series/tombraider-direct-glibc-proton-topology-fix-60hz-40c-20260818.json) |
| `safe` (immediate reverse control) | 2800×1752 | 59.97 Hz | 30.9 / 31.2 / 30.6 | 19.233 / 47.367 / **30.900** | Fixed 40 °C ceiling; all starts 37.0 °C | [JSON](docs/benchmark-series/tombraider-direct-glibc-safe-topology-fix-reverse-control-60hz-40c-20260818.json) |
| `safe` (RakNet pair controls) | 2800×1752 | 59.97 Hz | 30.9 / 31.2 / 30.7 | 20.967 / 45.433 / **30.933** | Fixed 40 °C ceiling; paired control | [JSON](docs/benchmark-series/tombraider-direct-glibc-safe-topology-fix-raknet-exclusive-alternating-60hz-40c-20260818.json) |
| `safe` (RakNet-exclusive CPU1) | 2800×1752 | 59.97 Hz | 29.6 / 30.5 / 30.7 | 15.667 / 46.300 / **30.267** | Fixed 40 °C ceiling; paired/rejected | [JSON](docs/benchmark-series/tombraider-direct-glibc-safe-topology-fix-raknet-exclusive-alternating-60hz-40c-20260818.json) |
| `safe` (direct game, topology fix, CEF hold) | 2800×1752 | 59.97 Hz | 31.5 / 31.3 / 30.9 | 20.367 / 46.567 / **31.233** | Fixed 40 °C ceiling; all starts 37.0 °C; experimental | [JSON](docs/benchmark-series/tombraider-direct-glibc-safe-topology-fix-cef-hold-60hz-40c-20260818.json) |
| `fast` (direct game, topology fix) | 2800×1752 | 59.97 Hz | 30.2 / 30.3 / 30.9 | 21.367 / 46.167 / **30.467** | Fixed 40 °C ceiling; all starts 37.0 °C | [JSON](docs/benchmark-series/tombraider-direct-glibc-fast-topology-fix-60hz-40c-20260818.json) |
| bundled Proton | 2800×1752 | 59.97 Hz | 23.2 / 23.1 / 22.6 | 14.200 / 31.233 / **22.967** | 45.1–47.9 °C; unmatched | [JSON](docs/benchmark-series/tombraider-native-glibc-proton-60hz-unmatched-20260817.json) |
| bundled Proton | 2800×1752 | 59.97 Hz | 22.8 / 22.7 / 25.2 | 12.500 / 32.967 / **23.567** | Fixed 40 °C ceiling; starts 37.0–37.6 °C | [JSON](docs/benchmark-series/tombraider-native-glibc-proton-60hz-40c-20260817.json) |
| `fast` | 2800×1752 | 59.97 Hz | 25.5 / 23.0 / 22.9 | 16.367 / 32.300 / **23.800** | Fixed 40 °C ceiling; all starts 37.0 °C | [JSON](docs/benchmark-series/tombraider-native-glibc-fast-60hz-40c-20260817.json) |

The current best direct game path is 35.1% faster than the matched 59.97 Hz
profile with the Runtime/Proton PRoot boundary. In the patched-topology comparison, `fast`
scores 30.467 FPS and `safe` 30.400 FPS, only 0.22% apart, so `safe` remains
the production profile. The opt-in native CEF hold raises the matched average
to 31.233 FPS, a small 2.74% candidate gain, while reducing minimum-FPS mean
3.01%. A follow-up three-pair replication reduces the average delta to only
+0.55% (30.600 held versus 30.433 control), with per-pair changes of +0.7,
-0.1, and -0.1 FPS. CEF hold therefore remains experimental rather than the
default; see the [paired composite](docs/benchmark-series/tombraider-direct-glibc-safe-topology-fix-cef-hold-paired-composite-60hz-40c-20260818.json).
Reserving CPU1 exclusively for RakNet is rejected: three alternating pairs
reduced average mean 2.15% (30.933 to 30.267 FPS) and minimum mean 25.28%,
while raising maximum mean only 1.91%. The paired average changes were -1.3,
-0.7, and 0.0 FPS, so production remains game CPUs1-7 with RakNet on CPU1.
The targeted 1 ms empty-receive backoff instead reduces the exact
`Raknet-RecvFrom` thread from 98.2% to 3.0% CPU and records a 31.633 FPS mean,
2.37% above the retained complete reverse control. A new same-session control
accepted 30.4/28.9 FPS before its third affinity validation failed, so its
directional +6.69% comparison is not treated as a complete series. The CPU
efficiency and correctness result is strong enough to make backoff the lean
Tomb Raider default; set `TOMB_RAIDER_RAKNET_RECV_SLEEP_US=0` for an explicit
control.
The later post-RakNet CEF revisit measured three current-default controls at
32.667 FPS and three held passes at 32.867 FPS. Its +0.61% change and paired
deltas of +1.3/-0.5/-0.2 FPS are noise-sized, so CEF hold remains off.
The final-game FEX WIP cache switch measured 34.000 FPS against an immediate
33.000 FPS reverse control, a +3.03% mean gain with positive paired changes of
+2.0/+0.8/+0.2 FPS. Upstream source shows that the switch starts FEX with one
128 MiB JIT buffer instead of an initial 16 MiB buffer. This Proton payload
lacks `FEXOfflineCompiler`, so no reusable compiled cache was loaded: the
accepted claim is maximal-buffer/code-map mode, not persistent-cache reuse.
The mode is now Tomb Raider's default; use
`TOMB_RAIDER_FEX_CODE_CACHE=off` for an exact control.
The first topology-fixed direct `proton` series averages 31.300 FPS. Against
the immediate reverse-order Safe control at 30.900 FPS, that is only +1.29%;
the per-position average changes are +1.2, 0.0, and 0.0 FPS. Proton raises
minimum mean 6.07% but lowers maximum mean 3.80%. This does not prove a
repeatable profile gain, so Safe remains the production default.
The direct dispatcher leaves Steam's generated outer request waiting for
lifecycle compatibility but executes the hot Proton/FEX/game tree outside the
PRoot tracer. The unmatched Proton row is retained for audit, not used to
select a profile.

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
