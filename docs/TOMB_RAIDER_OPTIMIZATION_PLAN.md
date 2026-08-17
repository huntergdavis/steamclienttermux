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
all-PRoot-host mean. The Steam/CEF host is no longer under PRoot; one explicit
outer PRoot remains at the Runtime/Proton game boundary.

Samsung Standard 60 Hz is also established. With XRandR verified at 59.97 Hz,
the otherwise identical `safe` series averaged 25.167 FPS: 7.6% above the
119.92 Hz control. Retain Standard 60 Hz for subsequent profiles. It improved
throughput but did not prevent every pass from ending at GPU thermal level six.

## Primary path: remove avoidable launch work, then remove PRoot

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
5. Continue `termux-glibc-compat` at the remaining game boundary. The versioned
   glibc, same-UID semaphore broker, authentication, native Steam, and CEF host
   are complete. Replace the explicit outer Runtime/Proton PRoot with a
   preconstructed/bindless layout; Android's denied user and mount namespaces
   mean additional libc shims alone cannot make Bubblewrap own that boundary.
6. Run bounded `proton` and `fast` FEX A/B passes at verified 59.97 Hz.
   `proton` previously averaged 11.4% above `safe` at 720p. `fast`
   follows the same-chip TSO-off direction but remains opt-in because FEX warns
   it can break multithreaded software. Use a fixed 40 C start ceiling for the
   warm-up and every recorded pass; the first native-resolution Proton series
   started at 45.1-47.9 C versus the `safe` control's 37.0 C and is therefore
   observational rather than the accepted profile A/B. These are useful
   interim measurements, not substitutes for removing the 60-65%-CPU PRoot
   tracer.

The one warm-up plus three-pass rule applies to each profile. Compare the
three-pass mean and median, not an isolated maximum or minimum.

## Second-wave tests

| Candidate | Why it is credible | Order / risk |
|---|---|---|
| Steam launch-only session | Steam/CEF consumed roughly one CPU core in the live profile. | Implemented as the silent direct AppID path. Compare launch time and memory before considering any explicit CEF suspension; do not kill or `SIGSTOP` helpers during a timed pass because Steam respawns them and traced stopped tasks did not behave normally. |
| PRoot/wineserver placement | PRoot plus wineserver consumed close to one core and could contend with game threads. | Profile their actual running CPUs, then A/B one guarded mask at a time. Pinning the tracer to a slower core may also increase syscall latency. |
| Internal-storage A/B | The game is on Android FUSE over the removable exFAT/sdfat card. This may affect loading and minimum-FPS stalls. | Low priority for mean FPS. The 15.3 GB game would leave only about 3.7 GB of the currently free 19 GB internal space, so do not move it until space is freed. |
| No-PRoot native glibc host | PRoot uses `ptrace` to intercept and rewrite guest syscalls; the live tracer alone used 60-65% CPU and the first timed PRoot game launch needed about 6m47s from runtime request to window. | Primary engineering path. Extend Termux glibc with the measured SysV semaphore behavior, launch native ARM64 Steam first, then isolate the later Pressure Vessel boundary. |
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
