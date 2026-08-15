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

## CPU-affinity/RakNet diagnostic pass

On 2026-08-15, the first live scheduling pass reported the following values,
read directly by the user from Tomb Raider's result dialog:

| Pass | Minimum | Maximum | Average |
|---|---:|---:|---:|
| Scheduling pass 1 | **23** | **41** | **31** |
| Scheduling pass 2 | **11** | **28** | **24** |
| Scheduling pass 3 | **21.0** | **39.8** | **31.1** |
| **Three-pass mean** | **18.3** | **36.3** | **28.7** |
| **Three-pass median** | **21.0** | **39.8** | **31.0** |

The game remained at exact 1280x720, Low, and V-Sync off. A post-pass audit
found 56 game threads: 55 allowed on CPUs 1-7 and the continuously runnable
`Raknet-RecvFrom` thread allowed only on CPU 1. Nine Steam web-helper processes
were confined to CPU 0, while Termux:X11 retained the CPUs 0-3 mask used by the
earlier passes. This was a combined scheduling change, so the result does not
yet separate the benefit of the wider game mask, RakNet isolation, and Steam
helper isolation.

The per-game FEX JSON still contained an empty `Config` object, and the active
global Proton configuration still used `ProfileStats=1`, `MaxInst=500`, TSO
and half-barrier TSO on, and multiblock on. No `safe` or `fast` launcher-profile
variables were present in the game environment. This result therefore belongs
to the bundled Proton FEX profile, not to the later translator tuning.

Relative to the three-pass 8.0/16.63/13.7 clean mean, the first diagnostic pass
improved minimum by 187.5%, maximum by 146.5%, and average by 126.3%; average
throughput was **2.26x** as high. The non-matching Snapdragon 8+ Gen 1 Turnip
comparison's 63 FPS average is now 2.03x this pass rather than 4.60x the clean
baseline, but it remains an upper comparison with unverified settings and a
different SoC.

Using all three tuned passes, mean average throughput is **28.7 FPS**, 2.09x
the clean baseline or a 109.5% increase. The tuned median average is 31.0 FPS.
The non-matching 63 FPS comparison is 2.20x the tuned mean; this project is
54.4% lower by that comparison's denominator. No pass is discarded.

The first pass had already returned to its main menu before capture. The retained
[`post-pass menu frame`](evidence/tombraider-affinity-1-7-menu-2026-08-15.png)
is evidence of the live 1280x720 game state, not a result screenshot. At the
post-pass audit, 2,063,264 KiB RAM and 4,575,800 KiB swap remained available;
the game itself used about 264-275 MiB resident and 363 MiB swapped. CPU policy
maxima were still only 1.325 GHz on CPUs 4-6 and 1.613 GHz on CPU 7, versus
2.496 and 2.995 GHz hardware maxima. KGSL exposed the full 818 MHz GPU maximum,
reported thermal power level zero, and was about 16.6% busy in the menu sample.
The third dialog was captured successfully and visibly reports 21.0/39.8/31.1
FPS in
[`tombraider-affinity-1-7-run3-2026-08-15.png`](evidence/tombraider-affinity-1-7-run3-2026-08-15.png).

The first value was one diagnostic result, so two repetitions ran in the
identical live state with no profiler or screenshot in either timed scene. The
first repetition reported 11/28/24 FPS and the second 21/39.8/31.1 FPS. The
middle pass is retained rather than discarded. The complete three-pass set is
the scheduling baseline for one-variable FEX `safe` and then `fast`
comparisons.

The post-second-pass masks, CPU policy limits, X11 affinity, and Steam-helper
affinity were unchanged. A two-second menu profile exposed a remaining source
of scheduler variance: the outer PRoot tracer used 63.5% CPU with a CPUs 0-7
mask, wineserver used 31% with a CPUs 1-7 mask, and both ended the sample on
CPU 4 alongside game work. This is a plausible contention mechanism, not yet
proven causality; the first pass did not capture their processor placement.

## FEX `safe` profile

The `safe` session was launched with `MaxInst=5000`, full JIT caches, and FEX
sampling disabled while retaining TSO and half-barrier TSO. Every setting was
verified in the real game environment. Proton's generated per-game JSON
contained `TSOEnabled=1` and `Multiblock=1`, agreeing with the environment.

| Pass | Minimum | Maximum | Average |
|---|---:|---:|---:|
| Warm-up | 18.0 | 30.9 | 25.5 |
| Clean 1 | **17.7** | **30.8** | **25.7** |
| Window switch, excluded | 5.9 | 30.1 | 23.7 |
| Clean 2 | **19.2** | **31.1** | **25.8** |
| Clean 3 | **19.2** | **31.1** | **25.8** |
| **Three-clean mean** | **18.7** | **31.0** | **25.77** |

The warm-up values were read directly by the user; its exclusive-window
capture was black and the root capture reached the menu after the dialog had
closed. Clean 1 is preserved as
[`tombraider-fex-safe-run1-2026-08-15.png`](evidence/tombraider-fex-safe-run1-2026-08-15.png).
No screenshot or profiler ran in either timed scene.

Before and after Clean 1, all 56 threads verified on CPUs 1-7 except
`Raknet-RecvFrom` on CPU 1, all Steam web helpers used CPU 0, and Termux:X11
used CPUs 0-3. CPU policy maxima were 1.325 GHz for CPUs 4-6 and 1.613 GHz for
CPU 7, exactly matching the scheduling-baseline ceiling. Available RAM after
the pass was 2,275,692 KiB and free swap was 5,052,556 KiB.

Clean 1 is 10.5% below the bundled-FEX scheduling mean of 28.7 FPS and 17.1%
below its 31.0 FPS median. At that checkpoint, one clean pass was not enough to
accept or reject the profile, so two more unchanged passes remained.

The uninterrupted replacement Clean 2 reported 19.2/31.1/25.8 FPS and is
preserved as
[`tombraider-fex-safe-run2-2026-08-15.png`](evidence/tombraider-fex-safe-run2-2026-08-15.png).
Clean 3 repeated the same exact 19.2/31.1/25.8 FPS dialog and is preserved as
[`tombraider-fex-safe-run3-2026-08-15.png`](evidence/tombraider-fex-safe-run3-2026-08-15.png).
The three clean averages are tightly grouped at 25.7, 25.8, and 25.8 FPS,
with a 25.77 FPS mean. That is 10.2% below the bundled-FEX scheduling mean.

The attempted second clean pass included a user-reported switch to another
Android window and returned 5.9/30.1/23.7 FPS. It is retained as
[`window-switch contamination evidence`](evidence/tombraider-fex-safe-window-switch-excluded-2026-08-15.png)
but excluded under the existing no-interaction clean-run rule. After returning,
Termux, the native X11 server, and the game all reported `/top-app`, all 56 game
thread masks verified, and CPU policy ceilings still matched the baseline.
That post-run state cannot prove the cgroup remained `top-app` during the
window switch. It also does not measure the steady-state case where
Termux:X11 alone is full-screen; that usable configuration is a separate A/B
condition.

The clean restart also exposed two launch details. Steam ignored repeated
`steam://rungameid/203160` actions while rebuilding and even after completing
its compatibility registry, whereas `-applaunch 203160` immediately created
the tracked ARM64 Runtime/Proton session. During renderer startup, three late
threads reset themselves to CPUs 0-7; the guarded helper caught them, and a
second application at the stable 56-thread state remained verified.

## Full-screen Termux:X11 usability A/B

The Safe baseline kept the Termux activity floating in front of Termux:X11 so
Android continued treating the Termux UID as foreground. That is useful for a
scheduler baseline but not acceptable gameplay. The no-overlay A/B produced
two sharply different results:

| Full-screen condition | Minimum | Maximum | Average |
|---|---:|---:|---:|
| Standalone Termux:X11 APK | **3.0** | **7.0** | **5.4** |
| Official shared-UID APK, run 1 | **17.4** | **36.3** | **28.5** |

The standalone result was read directly by the user and has no result capture.
It used the same exact 1280x720 Low, V-Sync-off, FEX `safe` profile and hid the
floating Termux activity before the timed scene. The post-run process state
showed `TombRaider.exe` allowed only on CPUs 1-3, in `/cpuset/moderate` and
`cpu:/background`. Its 5.4 FPS average is not a game or translation baseline;
it is the Android foreground-ownership failure this A/B was designed to find.

The replacement is the upstream universal `sharedUid` nightly APK documented
under [Avoiding slowdowns](https://github.com/termux/termux-x11#avoiding-slowdowns).
The installed APK is 14,576,870 bytes with SHA-256
`e3e2633287af90586cc994745855c9514fa6f9a94eff54abad6faf3cdefb0375` and
version code 15. Termux, Termux:X11, and Termux:API all report Android UID
10469. The matching Termux companion is `termux-x11-nightly 1.03.01-6`.

The first install inherited a stale server/activity Binder and showed only a
black, laggy surface. Logcat measured 1,733 matching connection messages in
three seconds, including repeated `DeadObjectException` failures. Stopping the
single X server was insufficient because the old activity had already queued
many connection callbacks. Temporarily disabling and re-enabling only
`LorieBroadcastReceiver` recycled the shared UID on this Samsung build, so the
supervised SSH service stopped and Termux had to be opened once after each
component-state change. No package data was cleared. With a fresh process, the
working sequence launched the Android activity first and exactly one X server
second. It produced one `ACTION_START`, one X-socket extraction, zero
connection errors, and a live 1280x720 root. A mapped `xmessage` window then
proved both Android presentation and pointer input before Steam started.

The measured shared-UID run used no KDE and left Termux:X11 as the only visible
Android activity. Steam ran with the FEX `safe` profile, its web helpers were
placed on CPU 0, X11 used CPUs 0-3, and the game was verified on CPUs 1-7 with
`Raknet-RecvFrom` on CPU 1 immediately before the user tapped **Start
Benchmark**. No SSH check, profiler, or screenshot ran during the timed scene.
The captured dialog visibly reports 17.4/36.3/28.5 FPS:
[`tombraider-shareduid-fullscreen-run1-2026-08-15.png`](evidence/tombraider-shareduid-fullscreen-run1-2026-08-15.png).

The shared-UID average is 5.28x the standalone result, a 427.8% increase; its
minimum is 5.80x and maximum 5.19x as high. It is also 10.6% above the 25.77
FPS floating-Termux Safe clean mean and only 0.7% below the 28.7 FPS bundled-
FEX scheduling mean. This single result proves that a usable full-screen
configuration need not pay the catastrophic standalone-APK penalty, but it
does not yet establish a new mean. The post-run audit found one late-created
`dxvk-cache` thread on CPUs 0-7 while the other game masks retained the tuned
profile, so repetitions must record that thread explicitly.

At the result dialog, 1,978,564 KiB RAM and 4,806,580 KiB swap remained
available. The game and X server both reported `/top-app`; this was not an OOM.

## Samsung Game Booster candidate

The measured tablet is an SM-X808U on Android 16 / One UI 8. Its installed
Samsung stack includes Gaming Hub, Game Booster, Game Optimizing Service, and
the SM8450 Samsung game-driver package. The Windows renderer and the visible
Termux:X11 activity now share Termux's Android UID. Game Booster still might
not classify that UID as a game automatically.

Samsung documents manually adding apps through **Gaming Hub → My games → More
→ Add games**. The controlled candidate is to add both Termux and Termux:X11,
then select **Gaming Hub → More → Game Booster → Game optimisation →
Performance**. Per-game resolution must remain at 100% and Frame Booster off,
because this project already controls the 1280x720 surface and the built-in
benchmark must not include synthetic frames. Samsung also documents Pause USB
PD charging for the Tab S8 series; when a suitable charger is connected, it
can avoid adding battery-charging heat during a run.

Performance mode is not enabled during the FEX `safe` set. It will be a
separate A/B profile because Samsung warns that it can increase heat and power
use, and because recognition of this split Termux/Termux:X11 workload remains
to be proven:
[Samsung Game Booster guide](https://www.samsung.com/us/support/answer/ANS10002536/),
[manual app-add guide](https://www.samsung.com/ca/support/apps-services/how-to-add-and-remove-apps-in-the-gaming-hub-app/),
and [current Game Booster layout](https://www.samsung.com/latin/support/apps-services/updates-to-game-booster-settings-and-features-on-the-samsung-galaxy-devices/).

The official shared-UID Termux:X11 build is now installed and has eliminated
the split foreground-ownership failure in one measured pass: Termux:X11 alone
kept the complete workload in `/top-app`. Game Booster remains a separate
future A/B and was not enabled for the 28.5 FPS result.

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
following the online-services update independently describe the first core
staying at 100%. The comparison visibly uses v1.01.748.0; our installed PE is
dated September 2022 and reaches the disabled online-service path, but its
exact semantic version has not been extracted. A live, reversible isolation
placed the game on CPUs 1-7 and that thread alone on CPU 1, preventing it from
occupying the 2.995 GHz prime core. That state subsequently produced the
23/41/31 FPS pass recorded above, together with the Steam-helper isolation.

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

1. Benchmark `STEAM_ARM64_FEX_PROFILE=safe`, then `fast`, changing no graphics,
   affinity, or presentation variable between them.
2. Separate the scheduling changes only after replication: first remove RakNet
   isolation, then restore Steam helper scheduling, one variable per set.
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
