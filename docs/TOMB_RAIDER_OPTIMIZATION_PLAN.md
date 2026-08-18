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
   The missing topology-fixed direct series is now complete at 31.300 FPS,
   2.96% above the 30.400 FPS direct Safe baseline. Minimum and maximum means
   regress 2.86% and 1.23%, and recorded averages descend 32.1/31.2/30.6.
   Treat Proton as the leading candidate, not the default, until a fresh
   reverse-order Safe control distinguishes the gain from same-session drift.

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
| RakNet-exclusive CPU1 (rejected) | The direct profile measured the single `Raknet-RecvFrom` thread at 99% on CPU1 while the game used 313% total. | Three alternating pairs changed mean min/max/avg by -25.28%/+1.91%/-2.15%. Keep production game CPUs1-7 with RakNet on CPU1. |
| Internal-storage A/B | The game is on Android FUSE over the removable exFAT/sdfat card. This may affect loading and minimum-FPS stalls. | Low priority for mean FPS. The 15.3 GB game would leave only about 3.7 GB of the currently free 19 GB internal space, so do not move it until space is freed. |
| No-PRoot native glibc host | PRoot uses `ptrace` to intercept and rewrite guest syscalls; the old tracer alone used 60-65% CPU. | Completed for the hot game tree through the guarded direct dispatcher; retain the parked outer request only for Steam lifecycle compatibility. |
| Bionic/system-Vulkan host | Current GameNative source uses a Bionic image and defaults its wrapper to `System`, while an external comparison showed a large system-driver lead. | Separate architecture project. Its Vulkan wrapper is an Android/NDK Bionic library depending on Android native-window and AdrenoTools libraries, not a drop-in glibc ICD. |

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
