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
