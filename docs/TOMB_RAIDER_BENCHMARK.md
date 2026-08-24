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

## Shared-UID 720p/1080p/panel-native resolution A/B

The first resolution pass changed only the Termux:X11 root and Tomb Raider
fullscreen resolution from 1280x720 to 1920x1080. It retained Low, motion blur
off, V-Sync off, FEX `safe`, Steam, the shared-UID full-screen activity, and
the same affinity profile. Steam was deliberately left loaded so unloading it
did not become a second variable.

| Shared-UID full-screen pass | Pixels | Minimum | Maximum | Average |
|---|---:|---:|---:|---:|
| 1280x720, run 1 | 921,600 | **17.4** | **36.3** | **28.5** |
| 1920x1080, run 1 | 2,073,600 | **9.3** | **34.0** | **27.8** |
| 2800x1752 Low, run 1 | 4,905,600 | **15.8** | **29.8** | **23.2** |
| 2800x1752 Low, run 2 | 4,905,600 | **4.7** | **27.9** | **21.7** |
| 2800x1752 Low, run 3 | 4,905,600 | **13.6** | **28.7** | **21.7** |
| 2800x1752 Low, three-run mean | 4,905,600 | **11.37** | **28.8** | **22.2** |

The 1080p pass rendered 2.25x as many pixels. Relative to the 720p pass,
average FPS fell by 0.7 FPS or 2.5%, maximum fell by 2.3 FPS or 6.3%, and
minimum fell by 8.1 FPS or 46.6%. The small average change is consistent with
a CPU, translation, or synchronization limit dominating steady-state
throughput, while the much lower minimum indicates worse transient stalls at
1080p. One pass at each resolution cannot isolate the cause or establish a
stable mean.

Before the user tapped **Start Benchmark**, XRandR and the game window both
reported 1920x1080. The game registry reported fullscreen 1920x1080 and V-Sync
off. All 55 then-live game threads verified on CPUs 1-7 except
`Raknet-RecvFrom` on CPU 1, Steam helpers used CPU 0, and X11 used CPUs 0-3.
There was 1,957,420 KiB RAM and 5,145,664 KiB swap available. No tool ran
during the timed scene.

The result dialog is preserved as
[`tombraider-shareduid-1080p-run1-2026-08-15.png`](evidence/tombraider-shareduid-1080p-run1-2026-08-15.png).
The post-run audit still showed both game and X11 in `/top-app`, with
2,086,616 KiB RAM and 4,927,732 KiB swap available, so this was not an OOM.
One late-created `dxvk-cache` thread widened itself to CPUs 0-7, the same
post-run caveat seen at 720p.

Changing the stored Termux:X11 preference did not resize the existing X
framebuffer. A clean transition required ending Steam, stopping the old X
server, recycling the stale Termux UI process without clearing package data,
then starting the Android activity before exactly one X server. The resulting
connection had one `ACTION_START`, one socket extraction, no connection errors,
and a 1920x1080 shared buffer. The supervised SSH service recovered after the
Termux process recycle, and cached Steam authentication was preserved.

### Panel-native optimization baseline

The Tab S8+ panel-native render target is now the optimization baseline. Its
three Low passes are 15.8/29.8/23.2, 4.7/27.9/21.7, and 13.6/28.7/21.7 FPS,
giving a mean of **11.37/28.8/22.2 FPS** and median of 13.6/28.7/21.7. Runs 2
and 3 repeated the same 21.7 FPS average while their minimums differed by 8.9
FPS. The mean average is 20.1% below the single 1080p pass and 22.1% below the
single shared-UID 720p pass. Those cross-resolution percentages compare
different sample counts and remain directional, not replacement resolution
means.

Immediately before the native timed scene, XRandR, the visible game window,
and Tomb Raider's registry all reported 2800x1752 fullscreen with V-Sync off.
The game affinity checker verified 59 threads on CPUs 1-7 except
`Raknet-RecvFrom` on CPU 1; nine Steam helpers used CPU 0 and X11 used CPUs
0-3. Game and X11 both reported `/top-app`. There was 1,928,504 KiB RAM and
5,003,876 KiB swap available. The user started the benchmark, and no tool ran
during the timed scene.

All three result dialogs are preserved as
[`run1`](evidence/tombraider-shareduid-native-2800x1752-run1-2026-08-15.png),
[`run2`](evidence/tombraider-shareduid-native-2800x1752-run2-2026-08-15.png),
and [`run3`](evidence/tombraider-shareduid-native-2800x1752-run3-2026-08-15.png).
After every pass, the exact 2800x1752 root/window and `/top-app` membership
remained intact. Run 1's post-audit found the familiar late `dxvk-cache`
thread on CPUs 0-7; the profile was reapplied before Run 2, and the complete
affinity profile still verified after Runs 2 and 3. None of the runs OOMed.

An immediate exploratory switch from Low Run 3 to the Normal preset, still
without Game Booster, produced a user-read **10/16/13.9 FPS**. That is 35.9%
below the adjacent Low Run 3 average and 37.4% below the three-run Low mean.
The registry showed that Normal enabled AA mode 1, depth of field,
post-processing, LOD 2, reflections, shadows, and SSAO while motion blur,
tessellation, and V-Sync remained off. The screenshot attempt occurred after
the dialog had advanced to a loading screen, so it was deleted and is not
claimed as result evidence.

Termux:X11's preset-only `exact` preference silently retained 1920x1080 when
asked for 2800x1752. The correct panel-sized render target is
`displayResolutionMode=custom` plus `displayResolutionCustom=2800x1752`.
Because the shared-UID APK runs `MainActivity` inside Termux's Android process,
changing the preference and recycling only the standalone helper did not clear
the old 1080p activity state. Stopping the exact X server and recycling that
verified UI process made Android rebuild it; runit restored SSH immediately.
The activity must then be opened before starting exactly one server. A server
started without the activity exposes only its 1280x1024 bootstrap root. The
final connection reported a 2800x1752 shared buffer (stride 2816) and XRandR
root. This distinction follows upstream's separation of the
[Android activity and background X server](https://github.com/termux/termux-x11#force-stopping-x-server-running-in-termux-background-not-an-activity).

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
because this project already controls the 2800x1752 surface and the built-in
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
the split foreground-ownership failure in measured passes: Termux:X11 alone
kept the complete workload in `/top-app`. Game Booster remains a separate A/B
and was not enabled for the 720p, 1080p, native-Low, or native-Normal results.

Adding Termux and Termux:X11 to Gaming Hub produced 5.2/28.5/19.9 FPS before
the user had confirmed the separate Performance selector. That pass is retained
as an app-added, policy-unconfirmed observation and is not included in the
Performance sample. After explicitly selecting **Game optimisation →
Performance**, the first controlled native-Low pass reported
**13.7/29.0/20.2 FPS**. This is 9.0% below the 22.2 native-Low mean and 6.9%
below the two immediately preceding 21.7 averages. Maximum remained within
0.2 FPS of the native-Low mean, while minimum remained noisy.

The confirmed result is preserved as
[`tombraider-gamebooster-performance-run1-2026-08-15.png`](evidence/tombraider-gamebooster-performance-run1-2026-08-15.png).
Immediately before it, all 60 game threads, native resolution, and both
`/top-app` placements verified; 2,047,396 KiB RAM and 4,759,816 KiB swap were
available. After it, affinity and both `/top-app` placements still verified;
2,059,916 KiB RAM and 4,788,128 KiB swap remained. It was not an OOM.

An unchanged confirmed Performance Run 2 then reported a user-read
**14.0/29.0/19.8 FPS**. The two-run Performance mean is therefore
**13.85/29.0/20.0 FPS**, 9.9% below the ordinary native-Low mean. The root
capture for Run 2 was a 734-byte all-black exclusive-fullscreen PNG. A targeted
window capture was not recovered before the game exited, so Run 2 is explicitly
user-read and no screenshot is claimed. Two agreeing averages are enough to
reject Performance as the next leading candidate; the next session returns to
Samsung Standard.

## Excluded SSH-background pass and launcher hardening

The first native-Low pass after removing Termux and Termux:X11 from Gaming Hub
reported a user-read **7.2/13.8/10.3 FPS**. Its average is 53.6% below the
valid 22.2 FPS native-Low mean, but the immediate post-run state makes it an
invalid graphics or translation comparison. `TombRaider.exe`, wineserver,
Steam, PRoot, and X11 were all in `/cpuset/moderate` and `cpu:/background`.
The game was allowed only on CPUs 0-3 and consumed 225.3% CPU while PRoot used
68.7%; Adreno was only 35% busy at its full 818 MHz policy maximum and thermal
power level zero. About 1.85 GiB RAM and 4.91 GiB swap remained available.
The X root and game settings remained native 2800x1752 Low, and the active FEX
environment remained the `safe` profile. This was neither an OOM, a thermal
GPU limit, nor a changed graphics preset.

The Android `com.termux` UI process itself was in `/top-app`, but X11 and Steam
had been created through a supervised SSH session that remained in
`/moderate` + `/background`; foregrounding the shared-UID activity did not
retroactively migrate those unrelated shell descendants. This refines the
earlier shared-UID result: the integrated APK fixes ownership only when the
native workload originates from a foreground Termux lineage. Removing the apps
from Gaming Hub was not the measured cause.

The production launcher now refuses a cold SSH/background launch before it
creates X11, PulseAudio, or Steam. A foreground launch pins X11 and Steam to
CPUs 0-3 and CEF helpers to CPU 0. Its single-instance, CPU-0 guard verifies
the exact App ID 203160 environment, requires the game and Wine auxiliaries to
remain in both `/top-app` controllers, applies CPUs 1-7, isolates
`Raknet-RecvFrom` on CPU 1, repairs late-created threads, and exits only after
the visible Tomb Raider window has retained the complete masks for thirty seconds.
It exits before any benchmark begins. PRoot is deliberately left unpinned
until its placement has a controlled A/B result.

The hardened tablet integration test invoked the cold launcher over SSH. It
exited 1 with the exact `/moderate` and `/background` diagnosis and left X11,
Steam, and PulseAudio counts at zero. The required `deja` query for an earlier
automatic launcher/affinity implementation returned no indexed match; this
guard encodes the repository's measured 31 FPS scheduling profile and the
shared-UID foreground A/B cited above.

### Hardened foreground-launch validation

The first real foreground run through the hardened launcher reported
**19.0 FPS minimum, 36.0 maximum, and 25.7 average** at the panel-native
2800x1752 Low target. This is a valid scheduling pass: before the timed scene,
the guard verified the exact App ID 203160 game with 56 threads on CPUs 1-7,
the single `Raknet-RecvFrom` thread on CPU 1, Wine auxiliaries on CPUs 1-7,
nine exact Steam helpers on CPU 0, and the complete game lineage in
`/top-app`. It then exited after thirty stable seconds, so no affinity poller
or logger ran during the benchmark.

Relative to the original three-run native-Low mean of 11.37/28.8/22.2 FPS,
this pass raised minimum by 67.1%, maximum by 25.0%, and average by 15.8%.
Relative to the excluded SSH-background pass, average throughput rose 149.5%.
One run does not establish a replacement mean, but it validates both the
foreground-lineage gate and automatic affinity path.

The result dialog is preserved as
[`tombraider-native-hardened-run1-2026-08-16.png`](evidence/tombraider-native-hardened-run1-2026-08-16.png).
The post-run audit still showed the 2800x1752 X root/window, FEX `safe`, the
game in `/top-app`, about 1.81 GiB available RAM, and about 5.01 GiB free swap;
this was not an OOM. As in earlier native passes, one late-created
`dxvk-cache` thread had widened itself to CPUs 0-7 after the guard exited. The
result remains valid, but that reset is now a concrete candidate for the next
low-overhead affinity improvement.

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

The shared-UID and native-resolution work is complete, and Samsung Performance
has not helped. The next sequence starts fully cooled with Samsung Standard and
60 Hz display refresh, then compares a fresh `safe` control, Proton's bundled
FEX configuration, and the opt-in `fast` profile. Every profile receives one
warm-up and three recorded passes. The exact order, stop rules, preflight, and
longer-term PRoot/Bionic work are in the
[research-backed optimization plan](TOMB_RAIDER_OPTIMIZATION_PLAN.md).

The required `deja "Snapdragon 8 Gen 1 Adreno 730 Tomb Raider GameHub
GameNative benchmark FPS"` and focused benchmark/affinity searches returned no
indexed prior-session match. The comparisons above come from primary recordings,
Qualcomm's product brief, GameNative's live compatibility service, and this
run's measured registry/process state.

## Preliminary native-glibc control (2026-08-17)

The native-glibc work has already produced a decisive startup result, but not
yet a controlled FPS result. Moving the authenticated Steam client and CEF host
out of PRoot reduced the comparable Runtime-request-to-visible-window interval
from 407.236 seconds to 58.256 seconds: 85.7% shorter, or 6.99 times as fast.

Two panel-native 2800x1752 Low-profile warm-up passes produced these
game-authored results:

| Warm-up | Minimum | Maximum | Average |
| --- | ---: | ---: | ---: |
| `20260817T152127Z-safe` | 15.6 | 32.9 | 23.6 |
| `20260817T154636Z-safe` | 5.3 | 32.0 | 24.2 |
| preliminary mean | 10.45 | 32.45 | **23.9** |

The 23.9 FPS point estimate is 7.7% above the earlier three-pass all-PRoot-host
mean of 22.2 FPS. It is not evidence of a 7.7% glibc FPS improvement: these are
warm-ups rather than a completed one-warm-up/three-recorded series, their
minimums are noisy, and the first pass ended in severe thermal throttling. It
also remains below the earlier single hardened 25.7 FPS pass.

The first warm-up began with full CPU/GPU policy and a maximum sampled thermal
sensor of 50.3 C. It ended at 73.9 C; the little, big, and prime CPU policy
maximums had fallen to 1.3632, 1.5552, and 1.8432 GHz, while the GPU fell from
818 to 492 MHz and thermal power level rose from zero to six. Available RAM
increased slightly and free zram remained about 5.75 GiB, ruling out OOM as the
cause of this slowdown. The runner now waits for full CPU/GPU policy, thermal
level zero, and stable near-start temperatures between recorded passes.

The second warm-up wrote the expected new game result, but the series rejected
it because exFAT/FUSE changed the identity of an older result file. The selector
now accepts exactly one previously absent timestamped result filename rather
than treating inode churn as a new result. This preserves fail-closed result
selection without rejecting a valid pass.

XRandR reported the Termux:X11 surface at 2800x1752 and 119.92 Hz while the
game-authored result reported a 60 Hz fullscreen target. That presentation-rate
mismatch is now the first controlled thermal experiment: finish the current
119.92 Hz native-glibc control, switch Samsung Motion smoothness to Standard
60 Hz and restart X11, then repeat the same profile. Only afterward should the
bundled Proton FEX profile and the correctness-risking `fast` TSO-off profile
be compared.

Native glibc removes PRoot from Steam and CEF, but the game still crosses one
explicit outer PRoot boundary before Pressure Vessel, Proton, FEX/Wine, and
`TombRaider.exe`. The earlier live menu profile attributed 60-65% of one CPU to
that tracer, 215-233% to the game, 31-33% to wineserver, and roughly another
core to Steam/CEF. Those figures predate the completed native-host route and
must be remeasured during the new control. They identify the remaining
structural glibc task: replace the game-boundary PRoot with a bindless,
preconstructed Runtime/Proton layout. More semaphore or robust-list emulation
cannot provide Android-denied user and mount namespaces.

The required `deja "Tomb Raider native glibc performance bottlenecks thermal
refresh rate remaining proot benchmark"` query returned no indexed prior
session. This section reuses the repository's existing exact game-result,
thermal-rejection, affinity, and Runtime-to-window measurement contracts and
the two preserved 2026-08-17 warm-up artifacts.

## Completed native-glibc 119.92 Hz control (2026-08-17)

Series `20260817T161307Z-safe` completed one warm-up and three automatically
cooled recorded passes. The X surface remained 2800x1752 at 119.92 Hz; the game
remained exclusive fullscreen, V-Sync off, Low/off, and used the `safe` FEX
profile. Native Steam primed in 17.699 seconds.

| Pass | Minimum | Maximum | Average | Cooldown before pass |
| --- | ---: | ---: | ---: | ---: |
| warm-up | 14.0 | 33.9 | 23.4 | 0.0 s |
| recorded 1 | 14.6 | 32.4 | 24.8 | 70.603 s |
| recorded 2 | 16.3 | 33.6 | 22.7 | 80.619 s |
| recorded 3 | 16.4 | 31.7 | 22.7 | 110.820 s |
| recorded mean | **15.767** | **32.567** | **23.400** | n/a |

The controlled 23.4 FPS average is 1.2 FPS, or 5.4%, above the earlier 22.2
FPS all-PRoot-host three-pass mean. This is a modest throughput improvement,
not the order-of-magnitude change seen in startup. The stronger established
glibc result remains launch latency: 58.256 seconds versus 407.236 seconds,
85.7% shorter or 6.99x as fast.

All three recorded passes began with every CPU policy at its hardware maximum,
the GPU policy at 818 MHz, and GPU thermal power level zero. Their starting
maximum sensor temperatures were 37.0, 37.9, and 40.7 C. Every pass ended with
the GPU capped at 492 MHz and thermal level six; maximum sensors reached 65.7,
62.2, and 79.0 C. This is not an OOM signature: after Run 3, available RAM was
3,160,796 KiB and free zram was 5,527,284 KiB. The runner's thermal gate made
the starting conditions comparable, but the timed workload itself still
drives severe policy reduction.

The unchanged 119.92 Hz series is now the native-glibc control. The next single
variable is Samsung **Motion smoothness: Standard (60 Hz)** followed by an X11
restart and verification that XRandR reports approximately 60 Hz. The same
`safe` series must then run with no other configuration change. Only after that
display/thermal A/B should the bundled Proton and `fast` FEX profiles be tested.

The complete machine-readable series, including each source result, affinity
log, clock, memory, thermal sensor, elapsed time, and aggregate, is retained as
[`tombraider-native-glibc-safe-119hz-20260817.json`](benchmark-series/tombraider-native-glibc-safe-119hz-20260817.json).

## Completed 59.97 Hz A/B (2026-08-17)

After the 119.92 Hz control completed and Steam/X11 stopped, Samsung Motion
smoothness was changed to Standard. A newly created X11 session independently
reported 2800x1752 at 59.97 Hz. No game, FEX, resolution, V-Sync, affinity,
graphics, launcher, or benchmark-series setting changed.

| Pass | Minimum | Maximum | Average | Cooldown before pass |
| --- | ---: | ---: | ---: | ---: |
| warm-up | 18.6 | 33.6 | 25.6 | 0.0 s |
| recorded 1 | 17.3 | 33.8 | 25.3 | 110.912 s |
| recorded 2 | 13.4 | 35.5 | 24.9 | 100.862 s |
| recorded 3 | 17.9 | 34.2 | 25.3 | 110.975 s |
| recorded mean | **16.200** | **34.500** | **25.167** | n/a |

| Aggregate | 119.92 Hz | 59.97 Hz | Change |
| --- | ---: | ---: | ---: |
| minimum mean | 15.767 | 16.200 | +2.7% |
| maximum mean | 32.567 | 34.500 | +5.9% |
| average mean | 23.400 | 25.167 | **+7.6%** |
| average median | 22.700 | 25.300 | **+11.5%** |

The result supports retaining Samsung Standard 60 Hz for this 60 FPS-targeted
game. It does not yet identify the mechanism. Every recorded 60 Hz pass began
at full CPU/GPU policy with a maximum sampled temperature of 37.0 C, but still
ended with the GPU capped at 492 MHz/thermal level six. End temperatures were
63.9, 75.6, and 77.6 C, and cooldowns were not shorter than the 119.92 Hz
series. The FPS gain could reflect lower X11/compositor presentation work or
less CPU/GPU contention without producing a lower final thermal state.

Memory again rules out OOM: after Run 3, available RAM was 3,166,504 KiB and
free zram was 5,629,180 KiB. The raw 59.97 Hz series is retained as
[`tombraider-native-glibc-safe-60hz-20260817.json`](benchmark-series/tombraider-native-glibc-safe-60hz-20260817.json).
The next controlled profiles are Proton's bundled FEX configuration and then
the opt-in `fast` configuration, both while retaining the winning 59.97 Hz
display state.

## Preliminary Proton profile series and fixed cross-series ceiling

The first 59.97 Hz bundled-Proton series completed at 15.9/30.0/23.2,
14.8/32.4/23.1, and 11.9/31.3/22.6 FPS. Its recorded aggregate was
14.200/31.233/22.967 FPS, 8.7% below the `safe` average. This series is retained
as observational evidence, not accepted as the profile A/B.

Inspection before publication found that Proton's recorded passes began at
45.5, 45.1, and 47.9 C, while all three `safe` passes began at 37.0 C. Both
series began each pass with full CPU/GPU policy and GPU thermal level zero, but
the 8.1-10.9 C headroom difference can bias when throttling begins. The runner's
original ceiling was derived independently from each warm-up start, so it
matched passes within a series without guaranteeing a cross-series match.

The runner now accepts `--start-temperature-ceiling-c`. A fixed ceiling applies
to the warm-up and every recorded pass and still requires full CPU/GPU policy,
GPU thermal level zero, and three stable samples. The accepted Proton repeat
and subsequent `fast` series use a 40 C ceiling. The existing `safe` control
qualifies because all recorded starts were 37.0 C.

The exact unmatched Proton artifact remains available for audit as
[`tombraider-native-glibc-proton-60hz-unmatched-20260817.json`](benchmark-series/tombraider-native-glibc-proton-60hz-unmatched-20260817.json).
The required focused `deja` query returned no indexed prior implementation;
the fixed gate extends the existing tested cooldown and fail-closed series
method.

The fixed-ceiling repeat completed successfully. Its warm-up began at 37.6 C
and reported 17.1/33.5/24.2 FPS. The recorded results were:

| Pass | Start | Minimum | Maximum | Average | Cooldown |
| --- | ---: | ---: | ---: | ---: | ---: |
| recorded 1 | 37.0 C | 5.1 | 34.7 | 22.8 | 100.885 s |
| recorded 2 | 37.0 C | 14.4 | 30.8 | 22.7 | 110.819 s |
| recorded 3 | 37.6 C | 18.0 | 33.4 | 25.2 | 110.902 s |
| mean | n/a | **12.500** | **32.967** | **23.567** | n/a |

Against `safe` at 16.200/34.500/25.167 FPS, bundled Proton is 22.8% lower in
minimum mean, 4.4% lower in maximum mean, and **6.4% lower in average mean**.
Average-FPS median is 22.8 versus `safe` at 25.3, a 9.9% deficit. The earlier
720p Proton advantage therefore does not generalize to the native-resolution
60 Hz target; `safe` remains the selected production profile.

The 5.1 FPS minimum belongs to a pass that started at 37.0 C with full policy
but ended at 83.8 C and GPU thermal level six. It did not OOM: available RAM
and free zram afterward were 2,956,196 and 5,680,448 KiB. Thermal variance still
makes isolated minimums unsuitable for profile selection, but it does not
erase the three-pass average/median result.

The accepted raw artifact is
[`tombraider-native-glibc-proton-60hz-40c-20260817.json`](benchmark-series/tombraider-native-glibc-proton-60hz-40c-20260817.json).
The subsequent `fast` series used the same verified 59.97 Hz display and fixed
40 C ceiling.

## Completed matched `fast` profile (2026-08-17)

Series `20260817T195804Z-fast` completed one warm-up and three recorded passes.
The warm-up reported 13.3/33.3/22.8 FPS. Every recorded pass began at exactly
37.0 C with full CPU/GPU policy, GPU thermal level zero, and the 818 MHz GPU
policy ceiling.

| Pass | Start | Minimum | Maximum | Average | Cooldown |
| --- | ---: | ---: | ---: | ---: | ---: |
| recorded 1 | 37.0 C | 17.6 | 33.9 | 25.5 | 100.864 s |
| recorded 2 | 37.0 C | 16.3 | 33.9 | 23.0 | 80.737 s |
| recorded 3 | 37.0 C | 15.2 | 29.1 | 22.9 | 110.947 s |
| mean | n/a | **16.367** | **32.300** | **23.800** | n/a |

Against `safe` at 16.200/34.500/25.167 FPS, `fast` improved minimum mean by
1.0% but reduced maximum mean by 6.4% and average mean by **5.4%**. `safe` is
5.7% faster when the denominator is `fast`. Average-FPS median was 23.0 versus
`safe` at 25.3, a 9.1% deficit. Against the matched bundled-Proton series,
`fast` improved average mean by only 1.0%.

The recorded passes ended at 63.3, 59.5, and 60.5 C, each with the GPU capped
at 492 MHz/thermal level six. Available RAM after Run 3 was 3,175,508 KiB and
free zram was 5,437,696 KiB, ruling out OOM. Run 2 was slower than Run 1 despite
ending cooler, so its drop is not explained by a hotter start or memory
pressure. The TSO-off `fast` profile does not justify its correctness risk and
remains opt-in; `safe` remains selected for production launches.

The complete artifact is
[`tombraider-native-glibc-fast-60hz-40c-20260817.json`](benchmark-series/tombraider-native-glibc-fast-60hz-40c-20260817.json).
The bounded FEX profile phase is complete. The next primary optimization is
removing or reducing the remaining game-boundary PRoot cost, with profiling
used only outside timed benchmark scenes.

## Completed direct-game `safe` series (2026-08-18)

The remaining hot game boundary is now bypassed by the narrowly validated
direct dispatcher. Steam still creates its normal Runtime/Proton request and
waits for lifecycle completion, but the outer PRoot process remains paused
while the patched-glibc dispatcher runs Runtime Python, Proton, Wine, FEX, and
`TombRaider.exe` directly with `TracerPid: 0`. The exact benchmark command is
allow-listed as `TombRaider.exe -nolauncher -benchmark`.

Series `20260818T072343Z-safe` reused the authenticated Safe-profile Steam
process and completed one warm-up plus three recorded passes. XRandR was
2800x1752 at 59.97 Hz. Every recorded pass began at 37.0 C with all CPU policy
limits at hardware maximum, GPU policy 818 MHz, and GPU thermal level zero.
The controller required a fresh usable CPU-topology line and the complete
post-discovery affinity ready state for every pass.

| Pass | Start | Minimum | Maximum | Average | Cooldown | Elapsed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| warm-up | 37.9 C | 15.2 | 44.6 | 31.3 | 80.619 s | 122.486 s |
| recorded 1 | 37.0 C | 21.8 | 48.1 | 31.1 | 110.939 s | 115.715 s |
| recorded 2 | 37.0 C | 12.3 | 46.7 | 30.3 | 90.829 s | 118.803 s |
| recorded 3 | 37.0 C | 22.6 | 48.4 | 30.3 | 120.935 s | 120.361 s |
| recorded mean | n/a | **18.900** | **47.733** | **30.567** | n/a | n/a |

Against the matched PRoot-bound Safe series at 16.200/34.500/25.167 FPS,
direct execution improves minimum mean by 16.7%, maximum mean by 38.4%, and
average mean by **21.5%**. Average-FPS median improves from 25.3 to 30.3, or
19.8%. The recorded averages span only 0.8 FPS despite each pass ending near
70.4-71.5 C. Recorded pass 2's 12.3 FPS minimum is retained; its 30.3 average
and the repeated 30.3 third pass prevent an isolated minimum from driving the
profile decision.

Available RAM after the recorded passes was 3,432,732, 3,095,928, and
3,121,784 KiB; free zram remained above 5,393,948 KiB. The gain is therefore
not an OOM artifact. Steam, X11, PulseAudio, and saved authentication survived
every game exit. The exact schema-v1 artifact, including per-pass clocks,
thermal sensors, memory, result paths, and affinity logs, is
[`tombraider-direct-glibc-safe-60hz-40c-20260818.json`](benchmark-series/tombraider-direct-glibc-safe-60hz-40c-20260818.json),
SHA-256 `0a12a244143202144b7cf75cf8e1c48a983b981e2a6f5d284629011748754ac8`.

This closes the former primary PRoot-removal experiment with a repeatable
throughput win. The next controlled variable is the direct per-game FEX
profile: retain the same authenticated Steam process and compare TSO-off
`fast` against this new direct `safe` baseline under the same 40 C gate.

## Guarded CPU-topology fix

The installed 32-bit game has a launch-time bug: if Windows reports different
process and system affinity masks, its CPU helper leaves all counts at one.
Android can change those masks while Wine/FEX starts, so launcher timing alone
is not reliable. This repository ships a reversible five-byte patcher, not the
copyrighted executable:

```bash
~/steam-arm64/compat-bin/configure-tombraider-cpu-topology.py --check
~/steam-arm64/compat-bin/configure-tombraider-cpu-topology.py --enable
```

It accepts only the known installed executable with SHA-256
`f36b8dd2bd74d48c14bf910ad9bd4ac9f4024433523ffc7e46d5c85c3dd618f5`,
creates a complete verified backup under `~/steam-arm64/backups/`, and refuses
to run while that exact game path is active. Restore the original bytes with:

```bash
~/steam-arm64/compat-bin/configure-tombraider-cpu-topology.py --disable
```

Steam file verification can also restore the vendor executable. The patch
changes only the helper's local enumeration mask; the post-discovery game
CPUs 1-7, RakNet CPU 1, and Steam-helper CPU 0 policy remains separate.

## Completed patched-topology direct `fast` series (2026-08-18)

Series `20260818T090408Z-fast` completed one warm-up and three recorded passes
with the guarded CPU-topology fix enabled. All four passes started at 37.0 C,
with full CPU/GPU policy, at 2800x1752 and 59.97 Hz. The helper returned usable
topology on every launch despite Android granting different startup masks; all
four affinity artifacts then reached the normal CPUs 1-7/RakNet/helper ready
state.

| Pass | Minimum | Maximum | Average |
| --- | ---: | ---: | ---: |
| warm-up | 21.6 | 47.4 | 31.8 |
| recorded 1 | 21.4 | 48.4 | 30.2 |
| recorded 2 | 21.5 | 43.9 | 30.3 |
| recorded 3 | 21.2 | 46.2 | 30.9 |
| recorded mean | **21.367** | **46.167** | **30.467** |

Against the earlier direct `safe` mean of 18.900/47.733/30.567 FPS, `fast`
improves minimum mean by 13.1%, reduces maximum mean by 3.3%, and reduces
average mean by 0.3%. Average medians are identical at 30.3 FPS. The mean
average difference is too small to justify changing the production profile;
the next control is a patched-topology `safe` repeat.

The complete schema-v1 artifact is
[`tombraider-direct-glibc-fast-topology-fix-60hz-40c-20260818.json`](benchmark-series/tombraider-direct-glibc-fast-topology-fix-60hz-40c-20260818.json),
SHA-256 `3abf061dab28b8f06242cab6aa17f05df891d3ed9c5e27c19b33aed05739d768`.

## Completed patched-topology direct `safe` series (2026-08-18)

Series `20260818T093126Z-safe` repeated the patched direct protocol with the
production FEX profile. XRandR was 2800x1752 at 59.97 Hz. Every pass began
below the fixed 40 C ceiling with full CPU/GPU policy and GPU thermal level
zero. The manifest records the required patched executable SHA-256
`4f311ecb46d6eb8f781d0c6a5e2fac6ee6a6224d19f23a79e7173b8f260807ad`.

| Pass | Start | Minimum | Maximum | Average | Elapsed |
| --- | ---: | ---: | ---: | ---: | ---: |
| warm-up | 37.0 C | 21.3 | 46.3 | 32.1 | 120.090 s |
| recorded 1 | 37.0 C | 23.2 | 44.7 | 30.6 | 120.620 s |
| recorded 2 | 37.0 C | 20.8 | 48.6 | 30.2 | 118.924 s |
| recorded 3 | 37.9 C | 19.0 | 45.1 | 30.4 | 119.960 s |
| recorded mean | n/a | **21.000** | **46.133** | **30.400** | n/a |

All four launches returned usable topology counts (`7/7/7`, `6/6/6`,
`5/5/5`, and `6/6/6`) and then verified game CPUs 1-7, RakNet CPU 1, and
Steam helpers CPU 0. This extends the patch reliability result to eight
consecutive controlled launches across the matched Fast and Safe series.

Against patched `fast`, `safe` differs by -1.72% minimum mean, -0.07% maximum
mean, and -0.22% average mean. The absolute average difference is 0.067 FPS,
while individual averages span 0.7 FPS across the two series. Disabling TSO
therefore provides no meaningful throughput gain; `safe` remains the default.

The complete schema-v1 artifact is
[`tombraider-direct-glibc-safe-topology-fix-60hz-40c-20260818.json`](benchmark-series/tombraider-direct-glibc-safe-topology-fix-60hz-40c-20260818.json),
SHA-256 `3837e5f3fc9eda9fff75964f51cc806440c187ab66bde993946a268accd9c661`.

## Incomplete RakNet nice-19 experiment (2026-08-18)

Series `20260818T095210Z-safe` changed only the RakNet receive thread from
normal priority to nice 19. The guard verified the intervention on the warm-up
and first two recorded passes. Their results were 18.4/47.0/30.8,
23.0/45.0/30.7, and 20.3/45.9/30.4 FPS, respectively. The two valid recorded
averages mean 30.55 FPS versus the 30.40 FPS baseline, too small and incomplete
to claim a gain.

The third recorded launch produced a raw 19.6/38.5/28.4 FPS result, but its
guard saw valid 6/6/6 startup topology and never observed a RakNet thread on
which it could verify nice 19. The controller therefore excluded the pass and
withheld an aggregate. This is correct experimental behavior: a score cannot
measure an intervention that was not proven active. The candidate is rejected
as unreliable and remains off in production.

The failed schema-v1 manifest is retained explicitly as incomplete:
[`tombraider-direct-glibc-safe-topology-fix-raknet-nice19-60hz-40c-incomplete-20260818.json`](benchmark-series/tombraider-direct-glibc-safe-topology-fix-raknet-nice19-60hz-40c-incomplete-20260818.json),
SHA-256 `33b62b03509cb7641933eb1085092f03888a00abdc7d2640a3bb380e92e5f91b`.
The excluded game-authored result had SHA-256
`f9a25e2ccd7263ba7c3eb2dc96e96201aa0bdedf01b6db77e686e8dcfcca4a9b`.

## Experimental native CEF-hold series (2026-08-18)

Series `20260818T105022Z-safe` changed only one timed-scene variable: after the
exact game identity appeared and stabilized for 25 seconds, a guarded helper
held eight exact native Steam CEF descendants until normal game exit. Every
pass proved that the helper set remained unchanged and stopped, then resumed
the identical start-tick-verified PIDs. Steam's intentionally reparented
crashpad handler was not signaled.

| Pass | Start | Minimum | Maximum | Average | Cooldown | Elapsed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| warm-up | 37.0 C | 22.8 | 47.1 | 32.1 | 30.293 s | 119.834 s |
| recorded 1 | 37.0 C | 23.1 | 45.3 | 31.5 | 141.210 s | 120.138 s |
| recorded 2 | 37.0 C | 16.8 | 45.5 | 31.3 | 120.996 s | 119.206 s |
| recorded 3 | 37.0 C | 21.2 | 48.9 | 30.9 | 121.025 s | 119.132 s |
| recorded mean | n/a | **20.367** | **46.567** | **31.233** | n/a | n/a |

Against the matched patched Safe baseline at 21.000/46.133/30.400 FPS, the
candidate changes minimum, maximum, and average means by -3.01%, +0.94%, and
+2.74%, respectively. Each recorded average improved by 0.5-1.1 FPS, but one
completed series is not enough to distinguish that small gain from variance;
an immediately preceding excluded untreated pass also reached 31.9 FPS. The
holder therefore remains an explicit experiment rather than the production
default. The next decision-quality test is an alternating untreated/held
replication from the same cooled session.

The complete schema-v1 artifact is
[`tombraider-direct-glibc-safe-topology-fix-cef-hold-60hz-40c-20260818.json`](benchmark-series/tombraider-direct-glibc-safe-topology-fix-cef-hold-60hz-40c-20260818.json),
SHA-256 `dcc06789340dc746cd3453d14fd39a72aede66fc77eea9ac63cb835a5b43feab`.
Steam PID 22318, X11 PID 25663, PulseAudio PID 25865, saved authentication, the
enabled topology fix, and the disabled external-command property all survived.

## Paired native CEF-hold replication (2026-08-18)

The decision-quality follow-up alternated untreated controls with guarded CEF
holds in the same authenticated, cooled session. The initial six-run series
completed two pairs, then failed closed on a third untreated pass: that pass
produced 18.8/39.7/28.5 FPS and valid 6/6/6 startup topology, but its affinity
guard never emitted the final performance-ready proof. The result is excluded.
A two-pass continuation supplied one replacement control/held pair.

| Pair | Control min/max/avg | Held min/max/avg | Held minus control average |
| --- | ---: | ---: | ---: |
| 1 | 14.4 / 42.6 / 30.2 | 22.9 / 46.3 / 30.9 | +0.7 |
| 2 | 15.2 / 47.1 / 30.5 | 21.6 / 46.8 / 30.4 | -0.1 |
| 3 | 22.0 / 46.9 / 30.6 | 15.4 / 45.4 / 30.5 | -0.1 |
| mean | **17.200 / 45.533 / 30.433** | **19.967 / 46.167 / 30.600** | **+0.167** |

All six accepted passes started at 37.0-39.6 C with CPU/GPU policy at hardware
maximum and GPU thermal level zero. Every held pass proved the same eight
helper identities active and resumed. Held-minus-control changes are +16.09%
minimum mean, +1.39% maximum mean, and only +0.55% average mean. Minimums are
not directionally consistent: held improves the first two pairs but regresses
the third. The paired evidence therefore does not reproduce the all-held
series' +2.74% average signal. CEF hold remains explicit and experimental.

The composite decision artifact is
[`tombraider-direct-glibc-safe-topology-fix-cef-hold-paired-composite-60hz-40c-20260818.json`](benchmark-series/tombraider-direct-glibc-safe-topology-fix-cef-hold-paired-composite-60hz-40c-20260818.json).
Its SHA-256 is
`c0cf0c6fe88354160ab87e11b0af8e0f2a8d54e1640b8d55433b0235ebaf4a6e`.
Its exact source manifests are retained as
[`alternating incomplete`](benchmark-series/tombraider-direct-glibc-safe-topology-fix-cef-hold-alternating-60hz-40c-incomplete-20260818.json),
SHA-256 `949b6432fb12bc40f11b1134ca9428816e016213096ea7bb2467f8fba4272897`,
and [`pair continuation`](benchmark-series/tombraider-direct-glibc-safe-topology-fix-cef-hold-pair-continuation-60hz-40c-20260818.json),
SHA-256 `9cc1ee724d493a12952ddc06e4c5cf84530394170a6ad9b46ea0881eb4e9e5a2`.
The excluded raw result SHA-256 is
`e6823ccda0bb8003945d46e994c600c1a5b8a990d2ae18c247a4b1ece7de7854`.

## Experimental X11 CPU0-1 pair (2026-08-18)

A guarded feasibility pair tested whether moving all 14 exact Termux:X11
threads from CPUs 0-3 to CPUs 0-1 reduces contention with the game on CPUs
1-7. The panel remained at 2800x1752 and 59.97 Hz with Low graphics, Safe
FEX, full startup topology, and a fixed 40 C start ceiling.

| Pass | X11 CPUs | Minimum | Maximum | Average |
| --- | ---: | ---: | ---: | ---: |
| warm-up | 0-3 | 22.9 | 45.5 | 33.0 |
| recorded control | 0-3 | 21.8 | 44.7 | 31.3 |
| recorded isolated | 0-1 | 22.3 | 48.7 | 31.4 |
| isolated minus control | n/a | +2.29% | +8.95% | **+0.32%** |

The holder proved the same 14 thread identities active, normal game exit,
and exact restoration to CPUs 0-3. Steam, X11, PulseAudio, saved
authentication, the topology patch, and the disabled external-command
property all survived. CPU0-1 is feasible, unlike rejected CPU0-only
isolation, but the single-pair average gain is too small to enable by
default. The next decision-quality series alternates three untreated and
three CPU0-1 passes in one cooled session.

The exact schema-v1 artifact is
[`tombraider-direct-glibc-safe-topology-fix-x11-cpu01-pair-60hz-40c-20260818.json`](benchmark-series/tombraider-direct-glibc-safe-topology-fix-x11-cpu01-pair-60hz-40c-20260818.json),
SHA-256 `0ca22f2ee6436eaa6a6a0492425253ca1e326153c0f7819828c589ca65281d2f`.

## Incomplete X11 CPU0-1 alternating replication (2026-08-18)

The first six-pass replication attempt completed its untreated warm-up at
17.1/46.0/31.6 FPS, then failed closed after untreated recorded pass 1. The
game wrote a complete 21.7/46.3/31.4 FPS result and the direct affinity guard
proved 6/6/6 startup topology plus the ready performance state. During
shutdown, however, PulseAudio asserted in `mainloop_io_free()` and the direct
dispatcher returned 1. The controller therefore excluded the score under its
then-current zero-exit rule; no CPU0-1 condition ran in this attempt.

The raw result, ready guard, and dispatcher log have SHA-256 values
`ccfe1db6a116c85f07ada379f5fee855a6ae07767daa17743000e46d98e3b69a`,
`156d5fa9bd8b3756d2adef15b764ff318c2bbaae45d968aa78a4789873f59be4`,
and `f3370e9dd560aa4bad0bfb25a2a1f033b50d6d680d29a0997b530827d38895be`,
respectively. The excluded manifest is
[`tombraider-direct-glibc-safe-topology-fix-x11-cpu01-alternating-60hz-40c-incomplete-20260818.json`](benchmark-series/tombraider-direct-glibc-safe-topology-fix-x11-cpu01-alternating-60hz-40c-incomplete-20260818.json),
SHA-256 `8b46da7e398081d799b6910ca3df14af010a6b1c19a4d4e3e324a27ca0e6979f`.

The controller now carries direct-launch status through CEF/X11 holder
restoration and independently validates the new benchmark result and ready
affinity log first. Status 1 is accepted only when protected dispatcher paths,
the exact Pulse assertion, final `DISPATCH_STATUS=1 TRACER_PID=0`, and zero
live Tomb Raider processes all match; every other nonzero exit remains fatal.
Each accepted anomaly records its server-log path and SHA-256 in the run.

## CPU0-1 replication rejects the candidate (2026-08-18)

A clean retry with the post-result shutdown classifier completed a
19.3/46.4/32.5 FPS warm-up and an untreated 21.8/45.4/32.3 FPS control. The
first CPU0-1 pass then wrote 21.2/41.6/28.3 FPS, a 4.0 FPS (-12.38%) average
regression. Its holder still proved all 14 X11 identities active on CPUs 0-1,
normal game exit, and exact restoration to CPUs 0-3. The game also exited
normally with dispatcher status zero.

The isolated pass is excluded rather than counted: its direct affinity guard
proved 7/7/7 startup topology but never reached the required performance-ready
state. Waiting for that ready state before isolation is not a clean repair;
accepted passes create their result only 33.8-46.0 seconds after the ready-log
write, so moving X11 then would change the timed scene mid-pass. Across valid
evidence, CPU0-1 changed average by only +0.1 FPS in the first pair and then
caused an invalid -4.0 FPS raw pass. CPU0-only already starved the game
entirely. Host X11 affinity therefore remains CPUs 0-3 in production.

The exact incomplete retry manifest is
[`tombraider-direct-glibc-safe-topology-fix-x11-cpu01-replication-60hz-40c-incomplete-20260818.json`](benchmark-series/tombraider-direct-glibc-safe-topology-fix-x11-cpu01-replication-60hz-40c-incomplete-20260818.json),
SHA-256 `3ef5314278f3699f5f6a0ee8b98ae6c7e5d9845f6c440a7478b535c83c2aa858`.
The excluded result, incomplete guard, and normal server log SHA-256 values
are `853ff507b67a7691a24d16169351e4d37a31661b1d507be74d93048625f42dac`,
`c7b6628a94f82c62a3cd12b3cb62085cf54f1fcb9dbbd38de3328e23c73f299c`,
and `9e9d9f657f7c77d335643a3517d9b410992a698af76ba29fa49b71463d0ed8dc`.

## RakNet-exclusive alternating replication (2026-08-18)

The fixed-ceiling replication alternated three untreated controls with three
passes reserving CPU1 exclusively for `Raknet-RecvFrom`. The target remained
2800x1752 at 59.97 Hz, Low, motion blur off, V-Sync off, Safe FEX, direct game
dispatch, full startup topology, and the fixed 40 C start ceiling.

| Pass | Game CPUs | RakNet-exclusive | Minimum | Maximum | Average |
| --- | ---: | ---: | ---: | ---: | ---: |
| warm-up | 1-7 | no | 22.3 | 45.2 | 31.9 |
| recorded 1 | 1-7 | no | 19.3 | 44.7 | 30.9 |
| recorded 2 | 2-7 | yes | 3.8 | 46.3 | 29.6 |
| recorded 3 | 1-7 | no | 21.9 | 45.5 | 31.2 |
| recorded 4 | 2-7 | yes | 20.4 | 46.9 | 30.5 |
| recorded 5 | 1-7 | no | 21.7 | 46.1 | 30.7 |
| recorded 6 | 2-7 | yes | 22.8 | 45.7 | 30.7 |

Control mean minimum/maximum/average was 20.967/45.433/30.933 FPS. The
condition was 15.667/46.300/30.267 FPS, changes of -25.28%, +1.91%, and
-2.15%. Paired average changes were -1.3, -0.7, and 0.0 FPS. The condition
did not repeat the first pair's minimum-FPS gain and introduced a 3.8 FPS
minimum. It is rejected; production remains game CPUs1-7 with RakNet on CPU1.

All seven launcher calls returned zero and their fresh guards proved the
requested ready topology. The controller waited for unthrottled CPU/GPU,
thermal power level zero, a sub-40 C reading, and three stable samples before
each pass. Steam PID 22318, X11 PID 25663, PulseAudio PID 25865, saved login,
the topology patch, and the disabled external-command property survived.

The exact artifact is
[`tombraider-direct-glibc-safe-topology-fix-raknet-exclusive-alternating-60hz-40c-20260818.json`](benchmark-series/tombraider-direct-glibc-safe-topology-fix-raknet-exclusive-alternating-60hz-40c-20260818.json),
SHA-256 `48d87e6763d7a8f4d2008e4dece48dec2ddfc6f5a6548c51c0caebbc47cc2895`.

## Topology-fixed direct Proton series (2026-08-18)

The earlier Proton rows still crossed the Runtime/PRoot game boundary. Series
`20260818T150228Z-proton` is the first Proton-profile measurement on the current
direct hot path. It retained 2800x1752, 59.97 Hz, Low, motion blur off, V-Sync
off, full topology fix, production affinity, and the fixed 40 C start ceiling.

| Pass | Start temperature | Minimum | Maximum | Average |
| --- | ---: | ---: | ---: | ---: |
| warm-up | 37.0 C | 26.0 | 46.4 | 33.5 |
| recorded 1 | 37.0 C | 24.6 | 45.1 | 32.1 |
| recorded 2 | 37.0 C | 14.5 | 46.8 | 31.2 |
| recorded 3 | 37.2 C | 22.1 | 44.8 | 30.6 |
| recorded mean | n/a | **20.400** | **45.567** | **31.300** |

Every start had full CPU/GPU policy and GPU thermal power level zero. All four
launches returned zero and supplied a fresh ready topology/affinity guard. The
phase-aware controller ended `complete`; the RunCommand transport reported
`err=-1` and `exit_code=0`.

Against the matched direct Safe baseline at 21.000/46.133/30.400 FPS, Proton
changes minimum/maximum/average means by -2.86%/-1.23%/+2.96%. This makes it
the leading FEX candidate, but not yet the default: the gain is small and the
recorded average declines on every pass. Run an immediate reverse-order Safe
control before assigning the delta to the profile.

The exact artifact is
[`tombraider-direct-glibc-proton-topology-fix-60hz-40c-20260818.json`](benchmark-series/tombraider-direct-glibc-proton-topology-fix-60hz-40c-20260818.json),
SHA-256 `6f64685bfbeb57c0a6732b876f5c95589c15c27ba8653af6d28d230418a47d3d`.
Steam PID 22318, X11 PID 25663, PulseAudio PID 25865, saved login, the topology
patch, and the disabled external-command property survived unchanged.

## Reverse-order Safe control closes the Proton candidate (2026-08-18)

The immediate follow-up returned to Safe without restarting the authenticated
Steam host. Series `20260818T151901Z-safe` retained the exact direct path,
topology fix, production affinity, 2800x1752/59.97 Hz display, Low settings,
and fixed 40 C start ceiling. Every pass started unthrottled at 37.0 C.

| Pass | Minimum | Maximum | Average |
| --- | ---: | ---: | ---: |
| warm-up | 19.0 | 47.4 | 32.3 |
| recorded 1 | 22.3 | 46.9 | 30.9 |
| recorded 2 | 20.6 | 45.3 | 31.2 |
| recorded 3 | 14.8 | 49.9 | 30.6 |
| recorded mean | **19.233** | **47.367** | **30.900** |

Proton's 20.400/45.567/31.300 FPS means are +6.07%/-3.80%/+1.29% relative
to this immediate Safe control. Ordered average differences are +1.2, 0.0,
and 0.0 FPS, so the average signal is confined to the first position rather
than repeating. Safe remains the production profile; Proton remains explicit.

Every launcher returned zero and supplied a fresh ready guard. The controller
ended `complete`, RunCommand returned `err=-1`/`exit_code=0`, and Steam, X11,
PulseAudio, authentication, topology patch, and disabled property survived.
The exact artifact is
[`tombraider-direct-glibc-safe-topology-fix-reverse-control-60hz-40c-20260818.json`](benchmark-series/tombraider-direct-glibc-safe-topology-fix-reverse-control-60hz-40c-20260818.json),
SHA-256 `40052514627a9eda68ef0fe93c8364d12073c7cb211b3a2abe47e65d45bf3103`.

## FEX maximal-buffer/code-map promotion (2026-08-23)

The Tomb Raider-only FEX WIP-cache switch completed a corrected candidate and
an immediate reverse control without restarting Steam or Termux:X11. Both used
the direct Safe path, full topology guard, 2800x1752 Low, 59.97 Hz, V-Sync and
motion blur off, the promoted 1 ms RakNet empty-receive backoff, one excluded
warm-up, three cooled recorded passes, and the fixed 40 C start ceiling.

| Condition | Recorded minimum FPS | Recorded maximum FPS | Recorded average FPS | Mean min/max/avg |
| --- | --- | --- | --- | --- |
| 128 MiB JIT buffer/code maps | 26.9 / 25.4 / 9.7 | 45.7 / 47.0 / 46.6 | 35.3 / 34.6 / 32.1 | **20.667 / 46.433 / 34.000** |
| immediate reverse control | 23.3 / 23.2 / 18.0 | 45.3 / 47.1 / 48.0 | 33.3 / 33.8 / 31.9 | **21.500 / 46.800 / 33.000** |

The candidate's average-FPS mean improves 1.0 FPS / 3.03%, and each
same-position delta is positive (+2.0/+0.8/+0.2 FPS). Its minimum-FPS mean
falls 0.833 FPS / 3.87%, so the result is an accepted throughput improvement
with an explicit pacing caveat—not a universal win.

Upstream FEX source explains the mechanism: the enabled path starts with a
128 MiB code buffer rather than the ordinary 16 MiB initial buffer. The
installed Proton payload writes code maps but lacks `FEXOfflineCompiler` and
produced no loadable cache file. The promoted claim is therefore maximal JIT
buffer plus code-map recording. The full raw artifacts are
[`candidate`](benchmark-series/tombraider-direct-glibc-safe-fex-max-buffer-60hz-40c-20260823.json)
and [`reverse control`](benchmark-series/tombraider-direct-glibc-safe-fex-max-buffer-reverse-control-60hz-40c-20260823.json).

## First valid 720p Normal fullscreen sample (2026-08-23)

The apples-to-apples target is now 1280x720 Normal, not the earlier
panel-native Low profile. The first valid built-in benchmark completed with
the following game-authored result:

| Pass | Minimum | Maximum | Average | Elapsed |
| --- | ---: | ---: | ---: | ---: |
| first valid sample | **33.7** | **61.6** | **52.0** | 122.618 s |

The game registry contained exact 1280x720, Normal-equivalent graphics,
exclusive fullscreen, 60 Hz, V-Sync off, and motion blur off. Termux:X11
remained a separate borderless 2800x1752 surface at 59.97 Hz so Android did
not shrink or decorate the presentation path. The foreground gate verified
requested size, task bounds, frame bounds, and content bounds as the full
panel with zero insets. The retained ready-screen screenshot SHA-256 is
`a5714549246e0a0f7b72ad9df83225aa7dc547fb74438447f832b16e17c46710`.

The run used direct native-glibc dispatch, Safe FEX, verified offline cache
generation 5, `mtrack`, game CPUs 1-7, `Raknet-RecvFrom` on CPU1, and Steam
helpers on CPU0. The Android controller remained in `/top-app` and stopped
polling before the timed scene. The fixed 40 C gate admitted the pass at 37.0
C with full CPU/GPU policy and GPU thermal power level zero. The affinity log
SHA-256 is
`8848d81a8df6779c1e326f9b6ddf6930c5ccc2d4bb3dac080a83e2df0623b213`.

The exact series is
[`tombraider-direct-glibc-safe-offline-compiled-720p-normal-fullscreen-60hz-40c-first-20260823.json`](benchmark-series/tombraider-direct-glibc-safe-offline-compiled-720p-normal-fullscreen-60hz-40c-first-20260823.json),
SHA-256 `38ebe9404a9f7bbde53442cb49e2f7d126708d7abe494519f9f83d9be641a67b`.
The raw game result SHA-256 is
`f714af27da24e56c63dffb10a988c3442d0c64eb71eef01a7249bdbb268dc35c`,
and the foreground log SHA-256 is
`8ae8b86b26e7f71722c39086cef0af459fc27a27eb476c2afc1180bdbc97be68`.
The process exited normally with `DISPATCH_STATUS=0`; the game is therefore
not expected to remain visible after the benchmark result is collected.

This is one valid sample, not a promoted multi-run mean. Two earlier nominal
720p results, 34.1 and 29.7 FPS, are excluded because their controller left
Termux:X11 as a decorated 520x320 floating window.

Launch attempts v5-v11 remain diagnostic evidence. v5-v8 used an invalid
Android `#!/bin/bash` wrapper and produced zero-byte logs; v9 reached the
wrapper but failed its `/usr/bin/env` interpreter; v10 rejected Termux's
legitimate `python3` symlink; and v11 passed the fullscreen gate but the
installed dispatcher selected stale cache
`tombraider-203160-offline-fff9bd81`, yielding no game or affinity guard. v12
used the no-clobber current dispatcher, selected verified generation-5 cache
`tombraider-203160-offline-7efb8f8e`, and produced the result above.

Required recall queries for prior 720p fullscreen automation, controller
handoff, zero-result output, and compiled-cache generation selection returned
no indexed implementation. This work reuses the repository's 2026-08-14
backup-first Tomb Raider profile controls, E135/E136 foreground-controller
rules, and verified generation-5 cache. The next gate changes only the
Tomb Raider-local DXVK version while preserving this profile and topology.

## Official DXVK 2.4.1 x32 promotion (2026-08-23)

The transactional app-local DXVK selector copies one coherent four-module x32
family beside `TombRaider.exe`, validates every byte before launch, forces
native Wine DLL selection, and moves all four files into a recoverable evidence
directory on every normal or signaled exit. Tomb Raider uses D3D11 through
DXGI; `d3d9`, `d3d10core`, `d3d11`, and `dxgi` therefore move together rather
than mixing an app-local module with Proton's bundled family.

| DXVK | Minimum FPS | Maximum FPS | Average FPS |
| --- | ---: | ---: | ---: |
| Proton 11 bundled control | 33.7 | 61.6 | **52.0** |
| official 2.4.1 x32, pass 1 | 35.8 | 74.4 | **59.1** |
| official 2.4.1 x32, pass 2 | 15.7 | 72.5 | **59.1** |

The repeated average improves 7.1 FPS / 13.7%. Both result files independently
record 1280x720, exclusive fullscreen, 60 Hz, Normal-equivalent settings,
V-Sync off, and motion blur off. DXVK logs independently report version 2.4.1
and the exclusive transition to a 1280x720 swapchain. The retained screenshot
shows a Lara Croft benchmark frame scaled inside the full panel. The second
affinity record reached ready with 50 threads on CPUs1-7, RakNet on CPU1, and
Steam helpers on CPU0. Steam, Termux:X11, and PulseAudio retained their original
PIDs and start ticks.

This is a promoted app-local throughput result, not a thermally paired series:
the first runner rejected its otherwise successful pass because a pre-existing
affinity watcher logged into an older file, and the second outer orchestrator
was interrupted while Steam delayed its acknowledgement before the detached
game completed. The exact average replicated, but the 35.8 versus 15.7 minimum
spread remains a pacing caveat. The compact raw authority is
[`tombraider-direct-glibc-dxvk-241-x32-720p-normal-fullscreen-60hz-20260823.json`](benchmark-series/tombraider-direct-glibc-dxvk-241-x32-720p-normal-fullscreen-60hz-20260823.json).

The immediate official 1.10.3 x32 A/B completed as a fully runner-accepted
sample: **27.9 minimum, 70.3 maximum, and 55.6 average FPS**. It started at the
same 37.0 C ceiling sample, used exact 1280x720 exclusive fullscreen and the
same FEX/topology controls, returned zero, and restored the overlay. This is
3.6 FPS / 6.9% faster than bundled DXVK, but 3.5 FPS / 5.9% slower than 2.4.1,
so 2.4.1 remains the promoted variant. Exact evidence is
[`tombraider-direct-glibc-dxvk-1103-x32-720p-normal-fullscreen-60hz-40c-20260824.json`](benchmark-series/tombraider-direct-glibc-dxvk-1103-x32-720p-normal-fullscreen-60hz-40c-20260824.json).
