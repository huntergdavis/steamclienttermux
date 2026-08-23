# Tomb Raider performance optimization plan

## Finding

The current limit is primarily CPU translation, container overhead, and
thermal policy. It is not a simple lack of GPU throughput:

- the live menu used 215-233% CPU in `TombRaider.exe`, 60-65% in the outer
  PRoot tracer, 31-33% in wineserver, and roughly another core in Steam/CEF;
- KGSL reported only 12-16% GPU busy in that sample;
- CPUs 4-6 were capped at 1.325 GHz instead of 2.496 GHz, CPU 7 at 1.613 GHz
  instead of 2.995 GHz, and Adreno at 492 instead of 818 MHz; and
- increasing the shared-UID target from 720p to 1080p reduced the single-pass
  average only from 28.5 to 27.8 FPS. Panel-native 2800x1752 is more expensive,
  but resolution alone does not explain the gap.

The best 720p three-pass profile remains Proton's bundled FEX configuration at
28.7 FPS average. The later FEX `safe` profile averaged 25.77 FPS under the
same scheduling and thermal ceilings. `safe` improved cache and block settings
but did not beat the bundled profile, so every FEX change must be measured
rather than assumed to help.

Samsung Game Booster Performance also failed its first controlled A/B. Its two
panel-native Low passes averaged 13.85/29.0/20.0 FPS, versus the ordinary
native-Low mean of 11.37/28.8/22.2. The Performance average is 9.9% lower.
Return Game optimisation to **Standard** for the next tests.

Native glibc Steam is now the established host. It reduced the comparable
Runtime-to-window interval from 407.236 to 58.256 seconds, or 6.99x, and the
completed 119.92 Hz `safe` series averaged 23.4 FPS versus the older 22.2 FPS
all-PRoot-host mean. The direct dispatcher now also executes the hot
Runtime/Proton/FEX/game tree outside PRoot; its matched patched `safe` baseline
averages 30.400 FPS at native resolution and 59.97 Hz.

Samsung Standard 60 Hz is also established. With XRandR verified at 59.97 Hz,
the otherwise identical `safe` series averaged 25.167 FPS: 7.6% above the
119.92 Hz control. Retain Standard 60 Hz for subsequent profiles. It improved
throughput but did not prevent every pass from ending at GPU thermal level six.

## Primary path: profile the direct hot path

Keep 2800x1752 fullscreen, Low, motion blur off, V-Sync off, the shared-UID X11
build, game CPUs 1-7, `Raknet-RecvFrom` on CPU 1, Steam helpers on CPU 0, and
X11 on CPUs 0-3. Change only the item named by each test.

1. Retain `~/start-tombraider-native.sh` as the launch path. It primes the
   remembered-login native Steam host in the background, forwards AppID 203160,
   passes `-nolauncher`, proves a stable exact window and affinity state, and
   supervises the game for the Android foreground lifetime. Its 58.256-second
   Runtime-to-window result is the fixed launch baseline.
2. Select Samsung **Standard**, set **Motion smoothness** to
   **Standard (60 Hz)**, and verify the live X refresh rate. Android documents
   that a display rate above the game's target adds power use without benefit;
   reducing that heat load may preserve CPU/GPU clocks during a long pass.
   If a PPS charger of at least 25 W is connected and the battery is at least
   20%, enable **Pause USB PD charging**. Samsung lists the Tab S8 series as
   supported and says this bypasses battery charging while the game runs.
3. Before timing, make one bounded menu profile and record CPU policy maxima,
   KGSL frequency/thermal power level, available RAM/swap, X geometry/refresh,
   cgroups, affinity, and active FEX profile. Reject or explicitly label a run
   whose CPU or GPU policy is already throttled. Do not profile, capture, or
   switch Android windows during the timed scene.
4. The cooled display A/B is complete: 23.4 FPS at 119.92 Hz versus 25.167 FPS
   at verified 59.97 Hz. Retain Samsung Standard 60 Hz as the new baseline.
5. The direct dispatcher completes the former game-boundary PRoot task. Steam's
   generated outer request remains parked for lifecycle compatibility, while
   Runtime Python, Proton, Wine, FEX, and the game run directly. Matched `safe`
   improves average mean from 25.167 to 30.400 FPS, or 20.8%.
6. The bounded `proton` and `fast` FEX A/B passes at verified 59.97 Hz are
   complete.
   `proton` previously averaged 11.4% above `safe` at 720p. `fast`
   follows the same-chip TSO-off direction but remains opt-in because FEX warns
   it can break multithreaded software. Use a fixed 40 C start ceiling for the
   warm-up and every recorded pass; the first native-resolution Proton series
   started at 45.1-47.9 C versus the `safe` control's 37.0 C and is therefore
   observational rather than the accepted profile A/B. These are useful
   interim measurements, not substitutes for removing the 60-65%-CPU PRoot
   tracer.

   The fixed-40 C Proton repeat averaged 23.567 FPS and the matched `fast`
   series averaged 23.800 FPS versus `safe` at 25.167 FPS. Proton was 6.4%
   slower than `safe`; `fast` was 5.4% slower and only 1.0% above Proton. All
   `fast` recorded passes began at 37.0 C. In the later matched patched direct
   comparison, `safe` and `fast` differ by only 0.22% average mean. Retain
   `safe`; this profile phase is complete.

   Those older `proton` results include the old Runtime/PRoot game boundary.
   The missing topology-fixed direct series completed at 31.300 FPS, 2.96%
   above the older 30.400 FPS Safe baseline. The immediate reverse-order Safe
   control then averaged 30.900 FPS. Proton's narrowed +1.29% average change
   came from per-position deltas of +1.2/0.0/0.0 FPS; its minimum mean rose
   6.07% while maximum mean fell 3.80%. Keep Safe as the default: the reverse
   control does not prove a repeatable Proton gain.

7. RakNet nice 19 is rejected. Two verified passes differed from baseline by
   only +0.15 FPS average, and a third pass could not prove that a RakNet thread
   existed to receive the priority change. The next action is one explicitly
   non-comparable live profile of the current direct path, followed by a new
   one-variable A/B aimed at the measured top CPU consumer.
8. The native CEF hold completed one warm-up and three guarded recorded passes.
   Its 31.233 FPS average mean is 2.74% above the matched 30.400 baseline, but
   minimum mean fell 3.01% and the preceding untreated excluded pass also
   reached 31.9 FPS. The follow-up alternating replication is now complete:
   held averages 30.600 FPS versus 30.433 control, only +0.55%, and the three
   pair directions are +0.7, -0.1, and -0.1 FPS. Keep it opt-in; do not adopt it
   as a performance default.
9. Single-core X11 isolation is rejected. The exact holder moved all 14 X11
   threads from CPUs 0-3 to CPU 0, but the next game never reached topology
   readiness or wrote a benchmark result. After its 300-second deadline the
   holder restored every thread identity to 0-3. Test CPUs 0-1 only as a
   bounded feasibility pass; retain CPUs 0-3 in production unless that pass
   reaches normal game exit and strict restore proof.

The one warm-up plus three-pass rule applies to each profile. Compare the
three-pass mean and median, not an isolated maximum or minimum.

The first direct-path live profile is now complete. Over 10 seconds the game
used 313.0% CPU, including 99.0% in `Raknet-RecvFrom`; X11 used 47.8%, native
wineserver 47.0%, the hottest CEF helper 28.6%, Steam core 11.7%, and
PulseAudio 9.1%. GPU busy was 68% at 791 MHz with no thermal cap. No hot PRoot
tracer remained. The first reversible native-CEF experiment completed and its
paired average gain was only 0.55%. The next measured consumer was X11.
Constraining its 14 threads to CPU 0 stalled the game before topology readiness
and is rejected. The remaining bounded host-placement candidate is CPUs 0-1,
with the same exact identity, timeout, and restore requirements.

That feasibility gate passed: eight exact descendant CEF helpers remained
stopped without respawn through normal game exit and were all resumed, while
Steam and authentication survived. The excluded pass averaged 31.9 FPS, but
an immediately preceding untouched excluded pass also averaged 31.9 FPS. The
candidate advanced to a full controlled series. Its recorded mean was 31.233
FPS versus the matched 30.400 baseline, a small 2.74% improvement, while
minimum mean regressed 3.01%. This is promising but not yet a production gain;
the required alternating replication reduced the average delta to +0.55% and
did not reproduce a consistent per-pair improvement. The candidate is closed
as a default-performance change but remains available for explicit experiments.

## Second-wave tests

| Candidate | Why it is credible | Order / risk |
|---|---|---|
| Steam launch-only session | Steam/CEF consumed roughly one CPU core in the live profile. | The silent direct AppID path is established. PRoot-traced helpers remain unsafe to stop; the native-only guard safely completed every exact hold/resume cycle. Paired average gain was only 0.55%, so retain the silent path without enabling hold by default. |
| Steam service-engine event storm | The post-backoff profile measured Steam's exact `IPC:CServiceEng` thread at 100.8% during Tomb Raider and only 0.2% after game exit. It outranks X11 and wineserver as the next external CPU consumer. | The first bounded candidate temporarily moves that exact thread from CPUs0-3 to CPU0 while Tomb Raider is alive, then restores the original mask. Run one excluded correctness/profile pass before the cooled ABBA wrapper; never stop Steam or change its priority/login state. |
| RakNet-exclusive CPU1 (rejected) | The direct profile measured the single `Raknet-RecvFrom` thread at 99% on CPU1 while the game used 313% total. | Three alternating pairs changed mean min/max/avg by -25.28%/+1.91%/-2.15%. Keep production game CPUs1-7 with RakNet on CPU1. |
| RakNet empty-receive backoff | The retained syscall trace is the exact upstream empty-receive pattern: `RakSleep(0)` becomes Wine `NtDelayExecution(0)`, then `sched_yield`, while the receive thread consumes 99% CPU. | Promoted for lean Tomb Raider launches. The exact-thread 1 ms shim reduced RakNet from 98.2% to 3.0% CPU and completed 32.9/31.3/30.7 FPS recorded passes (31.633 mean). The complete historical control shows +2.37%; a same-session control accepted 30.4/28.9 before its third pass failed affinity validation, directionally +6.69% but not a complete claim. |
| FEX maximal JIT buffer/code-map mode | Promoted. The WIP cache switch makes FEX allocate one 128 MiB code buffer instead of starting at 16 MiB. Three cooled passes averaged 34.000 FPS against a 33.000 immediate reverse control; paired changes were +2.0/+0.8/+0.2 FPS. | Keep it final-game-only and reversible. This Proton build lacks FEXOfflineCompiler, so treat recorded code maps as future compiler inputs rather than claiming a loaded persistent cache. |
| DXVK relaxed graphics UAV barriers | Rejected: two excluded readings reached 34.7 and 34.9 FPS, but the cooled recorded series averaged only 33.0 FPS versus the accepted 34.0 FPS build; minimum-FPS mean also fell 10.49%. | Keep default-off. Revisit only after a material DXVK or driver change. |
| FEX SMC checks `none` | FEX defaults to page-tracked executable-code invalidation, and upstream has measured game workloads where invalidation dominates. Tomb Raider's current Safe profile explicitly uses `mtrack`. | Add a final-game-only `mtrack`/`none` selector. Because `none` cannot detect modified executable code, require an excluded visual/exit pass before any cooled series and reject on the first crash or corruption. |
| Internal-storage A/B | The game is on Android FUSE over the removable exFAT/sdfat card. This may affect loading and minimum-FPS stalls. | Low priority for mean FPS. The 15.3 GB game would leave only about 3.7 GB of the currently free 19 GB internal space, so do not move it until space is freed. |
| No-PRoot native glibc host | PRoot uses `ptrace` to intercept and rewrite guest syscalls; the old tracer alone used 60-65% CPU. | Completed for the hot game tree through the guarded direct dispatcher; retain the parked outer request only for Steam lifecycle compatibility. |
| Bionic/private-Turnip host | E073 created the real 2800×1752 virtual swapchain and exported its three-image ring. The hardened v40 gate now pins the complete producer/service/ICD/APK chain and correctly refuses installed v39 before launch. | User updates v39→v40, then run the isolated four-frame RGBW gate and capture visual proof before deploying E077 or touching Tomb Raider. No visible frame or FPS is claimed yet. |
| BVB shared command stream | E075's host contract removes the five per-command recording socket exchanges while retaining one Submit2 control boundary. | After E076 visible-frame proof, compare `TOMB_RAIDER_BVB_COMMAND_STREAM=strict` (default) with `shared` in a cooled alternating native-resolution series. The launcher injects the effective switch only into Wine/DXVK, not Steam/CEF. |
| BVB shared mapped memory | A real same-runtime Turnip A/B reduced eligible map/flush/invalidate/unmap/submit control round trips from 11 to 5 (54.5%) with zero mapped/GPU-fill mismatches. This is transport evidence, not FPS. | After RGBW proof, deploy the already-backed-up E077 candidate and exact staged selectors; then compare `strict`/`shared` crossed with command-stream mode in cooled native-resolution Tomb Raider runs. |
| BVB descriptor allocation reuse | E130's bounded active handoff improved the complete native-resolution benchmark from 2.0 to 2.4 FPS. E131 then proved reset-epoch whole-sequence prediction wrong on the real game: only 36 of 159,843 attempts hit a lease (0.0225%), and that attempt did not complete. | E132 should batch the live request's exact pool/layout signature instead: return the requested prefix from one real native multi-set allocation and publish only the extras. Scan independent signature banks per pool; invalidate them all on reset/destroy; fall back to the exact atomic request on batch failure. |
| BVB first-rejection diagnostic | E079 can expose the bridge's first rejected real-game call without contaminating Steam/CEF or enabling persistent verbose diagnostics. | Set `TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC=1` only for a bounded BVB diagnostic run. Default `0` emits no game variable; this is a diagnosis gate, not a speed setting. |

## Experiment ledger and revisit triggers

`TECHNICAL_LOG.md` is the chronological authority and the JSON under
`benchmark-series/` and `evidence/` is the raw authority. This compact ledger
keeps rejected and near-miss work discoverable instead of treating it as
discarded.

| Experiment | Current decision | Revisit when |
|---|---|---|
| Samsung Performance mode | Rejected: controlled mean was 9.9% below Standard. | A firmware/Game Booster update changes the policy, or another fix removes the measured thermal cap. |
| 119.92 Hz display | Rejected for this 60-FPS target: 59.97 Hz improved mean by 7.6%. | Testing a game that can sustain more than 60 FPS, or proving equal thermals at 120 Hz. |
| FEX `proton` profile | Closed near-miss: reverse control narrowed the mean change to +1.29% with mixed min/max results. | FEX/Proton changes materially, or later fixes remove enough CPU pressure to rerun the exact alternating comparison. |
| FEX `fast` profile | Rejected: 5.4% below the cooled Safe control and carries upstream correctness risk. | A newer FEX documents changed TSO/block behavior and passes an excluded correctness run. |
| FEX maximal JIT buffer/code-map mode | Promoted at +3.03% average FPS (34.000 versus 33.000), with all three paired average deltas positive. Minimum-FPS mean fell 3.87%, and no compiled cache exists. | Retain the default-on selector for Tomb Raider, preserve the off control, and revisit minimum pacing after later translator work or after adding a version-matched offline compiler. |
| Native CEF hold | Closed near-miss twice: the original alternating replication was +0.55%; the post-RakNet three-pair revisit was +0.61% average with pair deltas +1.3/-0.5/-0.2 FPS and no repeatable minimum or thermal gain. | A new causal game/Wine/Steam reduction is followed by another clean profile that again makes CEF dominant; never promote from one pair. |
| X11 on CPU0 only | Rejected: the game never reached topology readiness. | X11 CPU falls substantially, game CPU headroom rises, or a different device exposes another efficiency core. |
| X11 on CPUs0-1 | Rejected: the initial pair was +0.1 FPS, while replication produced an incomplete affinity proof and a raw condition result 4.0 FPS below control. | A future X11 implementation materially reduces its workload or can change placement before, rather than during, the timed scene. |
| RakNet nice 19 | Rejected and superseded: activation was unreliable and verified passes were neutral. | Do not revisit while the exact empty-receive backoff is available. |
| Steam `IPC:CServiceEng` on CPU0 | Rejected: cooled controls averaged 34.4 FPS versus 33.2 isolated; mean minimum/maximum/average changed -12.37%/+2.11%/-3.49%. Exact restoration and Steam/X11 survival passed. | Revisit only after a causal reduction in Steam IPC work or a new profile justifies a wider mask. Do not enumerate masks blindly. The opt-in holder remains useful diagnostic machinery. |
| RakNet-exclusive CPU1 | Rejected: mean minimum/average regressed 25.28%/2.15%. | Only if a future title has a genuinely busy network worker not fixed by backoff; not for current Tomb Raider. |
| RakNet 1 ms empty-receive backoff | Promoted: receive-thread CPU fell 98.2% to 3.0%, full backoff mean was 31.633 FPS, and network/render/exit correctness held. | Retain the generic exact-thread shim for other RakNet titles; rerun the FPS control only if later scheduling changes make its cost or benefit ambiguous. |
| Internal-storage move | Deferred: likely loading/minimum-FPS benefit but insufficient safe internal free space. | At least 20 GB internal space is safely available or a smaller reproducible asset subset can isolate storage. |
| Bionic Vulkan bridge | Paused after visible Tomb Raider frames because current transport remains far below direct glibc. | Direct-glibc bottlenecks plateau, or the logged shared-memory/descriptor/submit changes close the bridge's measured frame-time gap. |

## Changes not worth leading with

- **Rewriting Python:** Python launches and records the session; it is absent
  from the game hot path. FEX, Wine/DXVK, and PRoot are native code already.
- **Blind DXVK replacement:** the active prefix `dxgi.dll` and `d3d11.dll`
  report `COFF-ARM64EC` / `IMAGE_FILE_MACHINE_ARM64EC`, and the installed DXVK
  identifies as `v2.7.1-498-ga6764047e587178`. It is not a translated x86 DXVK
  layer. Upstream leaves graphics-pipeline-library behavior on Auto and warns
  that forcing it can increase stutter or degrade performance. An older
  GPLAsync build is therefore not an evidence-backed first move.
- **Blind Turnip update:** the private driver is already Mesa 26.2-devel, newer
  by version than the 26.0 R1 same-chip recording. Version numbers alone do not
  establish a faster path.
- **More Game Booster Performance passes:** two controlled results agree on a
  roughly 20 FPS average and do not beat Standard. Thermal controls are more
  promising than repeating this policy immediately.

## Sources and provenance

The thermal/refresh recommendation follows
[Android's power-efficiency guidance](https://developer.android.com/games/optimize/power).
The charging requirements and Tab S8 support come from
[Samsung's Pause USB PD documentation](https://www.samsung.com/uk/support/mobile-devices/what-is-the-pause-usb-power-delivery-feature/).
The FEX cache, block, and TSO behavior comes from the
[upstream configuration definitions](https://github.com/FEX-Emu/FEX/blob/main/FEXCore/Source/Interface/Config/Config.json.in).
The PRoot architecture and its syscall-interception cost are documented by
[Termux PRoot-Distro](https://github.com/termux/proot-distro#the-proot-utility),
and the native alternative starts from
[Termux glibc packages](https://github.com/termux/glibc-packages).
ARM64EC's native/interoperable role is described by
[Microsoft](https://learn.microsoft.com/en-us/windows/arm/arm64ec), while the
DXVK caution comes from its
[official configuration](https://github.com/doitsujin/dxvk/blob/master/dxvk.conf).

Focused `deja` searches for the exact FEX/affinity result, Steam-helper unload,
Turnip/system-driver path, and Samsung thermal profile returned no indexed
session matches. This plan therefore reuses the repository's measured
shared-UID, affinity, clean-scene, FEX, thermal, and PRoot evidence rather than
an uncited remembered fix.

A later recall recovered Switchroot session
`a1837cd4-ab7b-411b-a83f-6e900a7ed053`: its proven command wrote a launch URL
to `steam.pipe`; it did not unload Steam. The direct background path reuses its
validated launch intent while retaining this repository's safer
`-applaunch`/AppID-log acknowledgement. Tomb Raider's installed executable was
also inspected directly and contains both `-nolauncher` and `-benchmark`.
