# Visual evidence

These screenshots capture milestones and failures from the original tablet.

- `steam-visible-now.png`: conventional ARM64 Steam client visibly running.
- `flicker-1.png`: CEF GPU-compositing flicker/partial-surface failure.
- `software-stable-3.png`: stable client UI after disabling CEF GPU compositing.
- `burnout-after-install-confirm.png`: Burnout installation confirmation.
- `steam-relaunched-installed.png`: client relaunched with completed installs.
- `2026-08-08-live-debugging-compat-timeout.png`: live debugging session with
  Burnout visibly in `Launching` state. Steam had accepted the launch request,
  but its compatibility-cache rebuild was serially registering historical Proton
  versions and had not yet resolved Steam Linux Runtime 4.0.

