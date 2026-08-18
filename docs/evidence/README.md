# Visual evidence

These screenshots capture milestones and failures from the original tablet.

- `steam-visible-now.png`: conventional ARM64 Steam client visibly running.
- `flicker-1.png`: CEF GPU-compositing flicker/partial-surface failure.
- `superflight-fullscreen.png`: Superflight running fullscreen through official
  Proton 11 ARM64, FEX, DXVK, and Turnip after the performance profile and
  CPU-affinity change.
- `gtaiv-selector-2026-08-13.png`: the focused fullscreen GTA IV / Episodes
  from Liberty City selector rendered by the real `GTAIV.exe` after saved
  Rockstar authentication, online presence, and cloud sync completed.
- `gtaiv-main-menu-2026-08-13.png`: the focused fullscreen GTA IV main menu,
  with `Start` selected and the Social Club panel connected, proving that the
  real game passed the earlier GTA IV/EFLC selector boundary.
- `gtaiv-loading-art-industrial-2026-08-13.png` through
  `gtaiv-loading-art-highway-2026-08-13.png`: five distinct native-resolution
  frames from the animated GTA IV loading-art sequence after choosing `Start`.
  They prove the game advanced beyond its main menu and began loading a game,
  but do not by themselves prove a playable scene completed loading.
- `gtaiv-new-game-2026-08-14.png`: the first-mission title **The Cousins
  Bellic** after the saved Rockstar session, selector, main menu, GTA IV sign-in
  prompt, and rotating loader all completed. This proves a new game started;
  it does not yet prove interactive control after the opening transition.
- `tombraider-main-menu-2026-08-14.png`: the real Windows Tomb Raider launcher
  after the App ID was explicitly mapped to official Proton 11 ARM64.
- `tombraider-start-benchmark-2026-08-14.png`: the real Tomb Raider game at its
  built-in `Start Benchmark` control. The first result was 5.8/18.0/13.6 FPS,
  read directly by the user; no result screenshot is claimed because the
  exclusive-fullscreen capture was black and the foreground retry reached the
  main menu.
- `tombraider-exact720-vsync-off-warmup-2026-08-14.png`: the first captured
  result after switching the live Termux:X11 root to exact 1280x720 and setting
  `VSyncMode=0`: 8.9/16.2/13.6 FPS. It is the warm-up, not a measured pass.
- `tombraider-exact720-vsync-off-run1-2026-08-14.png` through
  `tombraider-exact720-vsync-off-run3-2026-08-14.png`: the three clean result
  dialogs for the combined exact-X/V-Sync-off profile: 9.6/16.9/13.8,
  5.6/16.3/13.5, and 8.8/16.7/13.8 FPS. No sampler or screenshot ran during
  these timed scenes.
- `tombraider-affinity-1-7-menu-2026-08-15.png`: the 1280x720 game menu
  captured immediately after the user-read 23/41/31 FPS scheduling pass. The
  game had already dismissed its result dialog, so this is post-pass state
  evidence and is deliberately not labeled as a result screenshot.
- `tombraider-affinity-1-7-run3-2026-08-15.png`: the captured third result for
  the CPUs 1-7/RakNet CPU 1/Steam-helper CPU 0 profile, visibly reporting
  21.0 FPS minimum, 39.8 maximum, and 31.1 average.
- `tombraider-fex-safe-run1-2026-08-15.png`: the first clean result for the FEX
  `safe` profile under the same scheduling state, visibly reporting 17.7 FPS
  minimum, 30.8 maximum, and 25.7 average.
- `tombraider-fex-safe-window-switch-excluded-2026-08-15.png`: the captured
  5.9/30.1/23.7 FPS safe-profile pass during which the user briefly switched
  to another Android window. It is preserved but excluded from the clean mean.
- `tombraider-fex-safe-run2-2026-08-15.png`: the uninterrupted replacement
  Safe Clean 2 result, visibly reporting 19.2 FPS minimum, 31.1 maximum, and
  25.8 average.
- `tombraider-fex-safe-run3-2026-08-15.png`: the final Safe Clean 3 result,
  visibly repeating 19.2 FPS minimum, 31.1 maximum, and 25.8 average.
- `tombraider-shareduid-fullscreen-run1-2026-08-15.png`: the first usable
  no-overlay Safe-profile result with official shared-UID Termux:X11, visibly
  reporting 17.4 FPS minimum, 36.3 maximum, and 28.5 average. Both the game and
  X server remained `/top-app`; no profiler or screenshot ran during the timed
  scene.
- `tombraider-shareduid-1080p-run1-2026-08-15.png`: the first controlled
  1920x1080 resolution A/B under the same full-screen shared-UID Safe profile,
  visibly reporting 9.3 FPS minimum, 34.0 maximum, and 27.8 average. The X root
  and game window were both exactly 1920x1080; no tool ran during the timed
  scene.
- `tombraider-shareduid-native-2800x1752-run1-2026-08-15.png`: the first
  panel-native optimization baseline, visibly reporting 15.8 FPS minimum,
  29.8 maximum, and 23.2 average. XRandR, the game window, registry, and
  captured frame were all exactly 2800x1752; no tool ran during the timed
  scene.
- `tombraider-shareduid-native-2800x1752-run2-2026-08-15.png`: the second
  unchanged panel-native Low pass, visibly reporting 4.7 FPS minimum, 27.9
  maximum, and 21.7 average. The complete affinity profile verified afterward.
- `tombraider-shareduid-native-2800x1752-run3-2026-08-15.png`: the third
  unchanged panel-native Low pass, visibly reporting 13.6 FPS minimum, 28.7
  maximum, and 21.7 average. Together, the three native passes establish an
  11.37/28.8/22.2 FPS mean.
- `tombraider-native-hardened-run1-2026-08-16.png`: the first panel-native Low
  pass launched from the hardened foreground-only script, visibly reporting
  19.0 FPS minimum, 36.0 maximum, and 25.7 average. Before the benchmark, its
  finite guard verified `/top-app`, game/Wine CPUs 1-7, RakNet CPU 1, and nine
  Steam helpers on CPU 0, then exited so it was absent from the timed scene.
- `tombraider-direct-no-proot-terms-2026-08-17.png`: the real 2800x1752 game
  window rendered by the direct patched-glibc Proton path after the final
  Tomb Raider process left PRoot. It shows the Square Enix Terms of Service
  prompt and proves that DirectX 11 initialization reached interactive UI; it
  does not claim that the user accepted those terms.
- `tombraider-direct-cpu-topology-20260818.json`: the PE32 CPU-helper addresses,
  Windows API/CPUID control-probe results, Android affinity-race evidence, and
  first valid command-line benchmark from the direct no-PRoot game path.
- `tombraider-direct-live-profile-20260818.json`: one explicitly excluded
  10-second mid-scene `/proc` profile of the patched direct Safe path. It
  records process/thread CPU deltas, masks, memory, clocks, GPU busy, and
  thermal state without command lines or account data. Its FPS result is not
  part of any controlled aggregate.
- `tombraider-gaminghub-added-performance-unconfirmed-2026-08-15.png`: a
  panel-native Low pass after both shared-UID apps were added to Gaming Hub but
  before the separate Performance selector was confirmed, reporting
  5.2/28.5/19.9 FPS. It is excluded from the confirmed Performance sample.
- `tombraider-gamebooster-performance-run1-2026-08-15.png`: the first
  panel-native Low pass after the user explicitly selected Game Booster's
  Performance policy, visibly reporting 13.7/29.0/20.2 FPS. Affinity and both
  `/top-app` placements verified before and after the timed scene.
- `burnout-after-install-confirm.png`: Burnout installation confirmation.
- `steam-relaunched-installed.png`: client relaunched with completed installs.
- `2026-08-08-live-debugging-compat-timeout.png`: live debugging session with
  Burnout visibly in `Launching` state. Steam had accepted the launch request,
  but its compatibility-cache rebuild was serially registering historical Proton
  versions and had not yet resolved Steam Linux Runtime 4.0.
- `gtaiv-rockstar-email-verified-2026-08-12.png`: privacy-safe Rockstar splash
  captured immediately after the email-verification milestone. It records the
  session context but, by itself, is not evidence of authenticated launcher or
  game state; those later states are supported by the exact launcher log and
  X11 process/window observations in `docs/TECHNICAL_LOG.md` and the selector
  screenshot above.
