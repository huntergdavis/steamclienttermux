# Tomb Raider (2013) benchmark comparison

## First measured run

The first complete built-in benchmark ran on the Samsung Galaxy Tab S8+
(SM-X808U, Snapdragon 8 Gen 1/SM8450, Adreno 730, 7.12 GiB usable RAM) through
this repository's official Proton 11 ARM64, bundled FEX, DXVK, private Turnip,
and Termux:X11 path.

| Setting | Measured value |
|---|---|
| Game setting | 1280x720, Low |
| Motion blur/post-process/screen effects/tessellation/shadows/SSAO | Off |
| V-Sync | Double Buffer (`VSyncMode=1`) |
| `TombRaider.exe` affinity | CPUs 4-7 |
| Termux:X11 server affinity | CPUs 0-3 |
| Minimum | **5.8 FPS** |
| Maximum | **18.0 FPS** |
| Average | **13.6 FPS** |

The user read the three values directly from the result dialog. The automated
capture hit a black exclusive-fullscreen buffer, and the game returned to its
main menu before the foreground retry, so the repository does not claim a
result screenshot that it does not have. The retained
[`tombraider-start-benchmark-2026-08-14.png`](evidence/tombraider-start-benchmark-2026-08-14.png)
shows the real Windows game at its built-in `Start Benchmark` control.

This was the first benchmark pass after first launch, not a warmed three-pass
sample. At the completed result, 1,900,812 KiB remained available and
5,158,284 KiB of swap remained free. It was not an OOM result.

## Exact-X/V-Sync-off follow-up

The controlled follow-up used the same game payload, Low profile, and CPU
split, but changed two presentation variables together:

- `VSyncMode=0`, applied by the guarded backup-first profile tool; and
- Termux:X11 `displayResolutionMode=exact` at 1280x720, verified by `xrandr`
  as both the live root and `builtin` output.

The AppID window was also exactly 1280x720. Before each clean pass, all 56
observed game threads were verified on CPUs 4-7 and the 12-thread X server was
verified on CPUs 0-3. No sampler or screenshot ran during the clean timed
scenes.

| Pass | Minimum | Maximum | Average |
|---|---:|---:|---:|
| Warm-up | 8.9 | 16.2 | 13.6 |
| Clean 1 | 9.6 | 16.9 | 13.8 |
| Clean 2 | 5.6 | 16.3 | 13.5 |
| Clean 3 | 8.8 | 16.7 | 13.8 |
| **Clean mean** | **8.0** | **16.63** | **13.7** |
| **Clean median** | **8.8** | **16.7** | **13.8** |

The four result dialogs are preserved as
[`warm-up`](evidence/tombraider-exact720-vsync-off-warmup-2026-08-14.png),
[`clean 1`](evidence/tombraider-exact720-vsync-off-run1-2026-08-14.png),
[`clean 2`](evidence/tombraider-exact720-vsync-off-run2-2026-08-14.png), and
[`clean 3`](evidence/tombraider-exact720-vsync-off-run3-2026-08-14.png).
One activation-check pass had a screenshot about five seconds into the timed
scene and reported 3.6/16.5/12.9 FPS; it is deliberately excluded.

Relative to the first 5.8/18.0/13.6 pass, the clean mean minimum increased
37.9%, maximum decreased 7.6%, and average increased only 0.7%. Minimum FPS is
clearly variable across runs. At the three clean result captures, the lowest
observed memory state was 2,292,744 KiB available RAM and 5,089,696 KiB free
swap, so none was an OOM result.

The launcher passed `DXVK_LOG_LEVEL=info` and an accessible per-session
`DXVK_LOG_PATH`; both variables were present in the game environment. This
Proton payload emitted no DXVK file. Process maps and Tomb Raider's own log
still confirmed the prefix D3D11/DXGI path, Wine Vulkan, private Turnip, and
the `Turnip Adreno (TM) 730` DX11 adapter. The repository therefore records
the exact X root and window but does not claim an internally logged swapchain
extent.

## What the percentage difference means

The closest built-in benchmark recording found during this research used
GameFusion 2.0.3, Proton 9 ARM64, and a Snapdragon 8+ Gen 1 Redmi K60. Its
side-by-side result reported 43.1/88.9/63.0 FPS with Turnip and
58.9/101.4/83.6 FPS with the Android system driver. The recording does not
show a trustworthy matching resolution/preset, and 8+ Gen 1 is not the same
SoC, so this is an upper comparison rather than an apples-to-apples result:
[primary recording at the result frame](https://www.youtube.com/watch?v=TtTjQr9tKOk&t=80s).

Using the Turnip result:

| Metric | This project | Published comparison | Comparison / ours | Ours is lower by | Comparison is faster by |
|---|---:|---:|---:|---:|---:|
| Minimum | 5.8 | 43.1 | 7.43x | 86.5% | 643.1% |
| Maximum | 18.0 | 88.9 | 4.94x | 79.8% | 393.9% |
| Average | 13.6 | 63.0 | 4.63x | 78.4% | 363.2% |

The last two columns have different denominators. “Ours is 78.4% lower” means
`(63.0 - 13.6) / 63.0`; “the comparison is 363.2% faster” means
`(63.0 - 13.6) / 13.6`. The least ambiguous statement is **4.63 times the
measured average throughput**.

Using the cleaner follow-up mean of 13.7 FPS barely changes that comparison:
63.0 is 4.60 times as high, this project is 78.3% lower, or the comparison is
359.9% faster. The external recording remains non-apples-to-apples.

Qualcomm describes 8+ Gen 1 as 10% faster in CPU performance and GPU clocks
than 8 Gen 1, with substantially better efficiency. That matters for sustained
performance, but it cannot by itself explain a 4.63x gap:
[Qualcomm 8+ Gen 1 product brief](https://www.qualcomm.com/content/dam/qcomm-martech/dm-assets/documents/Snapdragon-8-plus-Gen-1-Product-Brief.pdf).

## Same-chip evidence

No Tomb Raider submission for Adreno 730 was present in the current
[GameNative compatibility database](https://gamenative.app/compatibility/),
and no same-chip GameHub built-in benchmark was found. That absence is why the
8+ Gen 1 result above is not presented as an exact comparison.

A primary recording does exist for an unrooted Motorola Edge Plus (2022) with
the exact Snapdragon 8 Gen 1, Adreno 730, and 8 GB memory class. It used
Winlator Bionic, Proton 9 ARM64EC, FEXCore 2508, DXVK 2.4.1, and Turnip 26.0 R1.
The visible game settings were 1280x720 Low, V-Sync off, fullscreen/exclusive
fullscreen on, and motion blur and screen effects off. Sampled gameplay frames
showed the on-screen counter between 35.9 and 62.7 FPS:
[primary same-chip recording](https://www.youtube.com/watch?v=LN5PWI8DcR4&t=73s).

Frame-by-frame inspection of the recording's setup section adds important
details. It uses current game build **v1.01.748.0**, CPUs **1-7** with CPU 0
excluded, FEX TSO mode `Fastest`, x87 mode `Fast`, multiblock enabled,
`Aggressive (Stop services on startup)`, and DXVK 2.4.1 ARM64EC GPLAsync with
async/cache enabled. The matching Ludashi preset table maps its performance
mode to TSO and half-barrier TSO off, reduced x87 precision on, and multiblock
on; its exposed defaults use `MaxInst=5000` and full JIT caches:
[Ludashi source-analysis table](https://github.com/The412Banner/Ludashi-plus/blob/3.0/LUDASHI_3.0_MASTER_REPORT.md#t-box64--fexcore-named-presets).

That is instantaneous gameplay, not the built-in benchmark, so comparing it
directly with the 13.7 FPS clean mean would overstate precision. The important
result is not a precise percentage; it is that the same silicon has
demonstrated far more performance through a closely related
Proton/FEX/DXVK/Turnip stack.

A GameHub recording on the nearby Snapdragon 8+ Gen 1/Adreno 730 reports
45-72 FPS at 720p, again as gameplay rather than the built-in benchmark:
[primary GameHub recording](https://www.youtube.com/watch?v=Zwq3uJz1-Po).

## What the follow-up rules out

The earlier X root was 2800x1586, 4.8186 times as many pixels as 1280x720.
Multiplying 13.6 by that ratio produced a tempting 65.5 FPS estimate near the
external 63.0 result. The exact-X follow-up averaged 13.7 FPS, so that scaling
hypothesis is disproven: the larger live X surface was not multiplying the
game's rendering work in proportion to its pixel count.

Because V-Sync and the X root changed together, this pass cannot separate
their individual effects. It does establish that their combined effect on
average throughput is negligible. The next work should target CPU scheduling,
translation overhead, and the container/driver path rather than expecting a
large resolution-only gain.

The official Termux:X11 project now documents this exact Samsung OneUI cpuset
problem and offers an integrated Termux build so the X11 process is spawned by
the visible foreground app. That is a cleaner long-term answer than retaining
a tiny Termux pop-up over the game:
[Termux:X11 Samsung cpuset documentation](https://github.com/termux/termux-x11#termux-with-termuxx11-embedded).

The installed official Proton payload contains FEX release 2605, newer than the
FEXCore 2508 same-chip recording, and the private Turnip is Mesa 26.2-devel.
That makes controlled CPU and translation comparisons higher priority than
another presentation-only change.

## Live bottleneck profile

A bounded three-second `/proc` profile at the real game menu found the game at
215-233% CPU, PRoot at 60-65%, wineserver at 31-33%, and Steam/CEF at roughly
another full core. GPU busy was only 12-16%. The tablet was also thermally
limited: CPUs 4-6 were capped at 1.325 GHz versus a 2.496 GHz hardware maximum,
CPU 7 at 1.613 versus 2.995 GHz, and the GPU at 492 versus 818 MHz. The new
profiler records both policy and hardware limits so a throttled pass can be
rejected before interpreting FPS.

One `Raknet-RecvFrom` thread remained runnable in every sample and consumed
98-100% of one core without sleeping or being observed in a syscall. Reports
from the v1.01.748.0 online-services update independently describe the first
core staying at 100%; the comparison uses that same game build, so the payload
version alone is not the full gap. A live, reversible isolation placed the
game on CPUs 1-7 and that thread alone on CPU 1, preventing it from occupying
the 2.995 GHz prime core. This state has not yet produced a built-in benchmark
and is not reported as an FPS improvement.

Proton's bundled FEX `Config.json` explicitly uses `MaxInst=500`, TSO and half-
barrier TSO on, and `ProfileStats=1`; unset upstream defaults disable the JIT
L2 cache and dynamically shrink L1. The comparison ecosystem exposes
`MaxInst=5000`, full caches, and a TSO-off performance mode. The production
launcher therefore provides `STEAM_ARM64_FEX_PROFILE=safe` for the block/cache/
sampler changes with TSO retained, and `fast` for the comparison-matched TSO-
off state. FEX upstream explicitly warns that disabling TSO is likely to break
multithreaded applications, so the two profiles must be tested separately:
[official FEX configuration definitions](https://github.com/FEX-Emu/FEX/blob/main/FEXCore/Source/Interface/Config/Config.json.in).

## Next controlled passes

Continue to use one warm-up plus three recorded passes per profile:

1. Reject thermally capped starts, then benchmark the recording-matched CPUs
   1-7 state against the existing 4-7 baseline. Keep the RakNet isolation as a
   separately identified sub-variant.
2. Benchmark `STEAM_ARM64_FEX_PROFILE=safe`, then `fast`, changing no graphics,
   affinity, or presentation variable between them.
3. Measure a launch-only session with KDE/Plasma and nonessential Steam CEF
   processes absent. `SIGSTOP` is not a solution under PRoot: it leaves traced
   helpers accumulating CPU time even though `kill` succeeds.
4. Back up Termux and evaluate the official integrated Termux:X11 build for the
   Samsung foreground-cpuset fix. Do not replace the live app without a
   recovery plan.
5. Then compare a controlled translator or driver change. Do not infer a
   benefit merely from version numbers.

The required `deja "Snapdragon 8 Gen 1 Adreno 730 Tomb Raider GameHub
GameNative benchmark FPS"` and focused benchmark/affinity searches returned no
indexed prior-session match. The comparisons above come from primary recordings,
Qualcomm's product brief, GameNative's live compatibility service, and this
run's measured registry/process state.
