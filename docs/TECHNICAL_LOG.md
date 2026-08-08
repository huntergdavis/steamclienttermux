# Technical log

Reconstructed from timestamped logs, backups, exact source diffs, screenshots,
and the final live filesystem. Times use America/Los_Angeles.

## 2026-08-07: preserve and inventory

Before changes, the KDE start/stop scripts, `.bashrc`, `kwinrc`, Termux details,
package list, and GPU environment were backed up under
`~/steam-arm64/backups/20260807-113956`. The existing accelerated desktop was
treated as immutable; all Steam libraries and variables were isolated.

## Native ARM64 client in Debian

Valve's ARM64 client was staged under `~/steam-arm64/client`. Early direct and
PRoot launches established that it required a conventional glibc userspace, so
Debian 13 was used with `~/.steam/steam` linked to the external client tree.
See `debian-native-linked-20260807-115310.log` and `bootstrap-driver-2.log`.

## Private Turnip selection

A private Mesa bundle was installed at `~/steam-arm64/mesa-kgsl`. The launcher
selects it with `VK_DRIVER_FILES`, `LD_LIBRARY_PATH`, `LIBGL_DRIVERS_PATH`,
`MESA_LOADER_DRIVER_OVERRIDE=kgsl`, and `TU_DEBUG=noconform`, without replacing
the desktop's Mesa. Observed: Mesa `26.2.0-devel (git-9452d1daec)`, ICD API
`1.4.335`.

## PRoot IPC repair

Steam exercised SysV shared memory/semaphores and robust-list calls missing or
incomplete in the Android PRoot path. PRoot at commit
`a89b3732ec6ae1db674510f0843b2f3db54d0a2f` was changed to:

- emulate `set_robust_list` and `get_robust_list` registration;
- track semaphore last-operation PIDs and implement `GETPID`;
- implement `SETALL`, `GETNCNT`, and `GETZCNT` behavior;
- wake blocked `semop` waiters after `SETVAL`/`SETALL`;
- add opt-in `PROOT_SYSVIPC_LOG` diagnostics;
- add opt-in crash reports with signal, registers, command line, and memory map.

The exact 244-line diff is `patches/proot-steam-android.patch`. Focused probes
are retained in `probes/`.

## Five-minute launch delay: D-Bus pipe inheritance

Steam's updater auto-started D-Bus. The daemon inherited the updater output pipe,
preventing EOF for about five minutes. The launcher now starts a private session
bus first, passes its address into Debian, and cleans it up on exit. Evidence:
`dbus-fix.log`.

## CEF flicker, stale surfaces, and broken clicks

CEF GPU compositing under Termux:X11 produced partial/stale surfaces, flicker,
and bad hit testing. `-cef-disable-gpu` stabilized Steam's HTML UI. This affects
the client UI only; games remain on Turnip. `-no-cef-sandbox` is also required
inside this PRoot/app-sandbox arrangement. See `flicker-1.png`,
`software-stable-3.png`, and `cef-software-fixed-20260807-162701.log`.

## Missing Steam network bridge methods

The UI called absent `SteamClient.System.Network` methods and threw before its
fallback could render. The idempotent UI patch adds exact function checks for
`RegisterForDeviceChanges`, `GetProxyInfo`, and
`RegisterForConnectivityTestChanges`. It backs up the minified chunk and refuses
unexpected match counts. It is tied to `chunk~2dcc5aaf7.js`; future Steam builds
will require locating the new chunk and expressions.

## IPv4 and Android `/proc/net`

Steam's local bridge was unreliable with IPv6-preferred localhost resolution,
so the Steam PRoot session receives a private IPv4-only hosts file. Android also
hides TCP ownership details from unprivileged apps. Steam's scoped `lsof` query
is answered by our shim; all other invocations reach real `lsof`. Evidence:
`ipv4-test-20260807-151041.log` and `lsof-shim-20260807-151218.log`.

## Download preallocation and inconsistent install state

File-by-file preallocation was pathologically slow through ptrace PRoot and held
downloads near 2%. `-chromeosnopreallocate` disables it. Incomplete manifests
were quarantined rather than destroyed, Steam recreated state, and downloads
completed. Final sizes observed on 2026-08-08:

- Burnout Paradise Remastered: `7992789904` bytes;
- Proton Experimental: `1515228739` bytes;
- Steam Linux Runtime 4.0: `672088523` bytes.

See `burnout-after-install-confirm.png`, `restart-after-install-complete.log`,
and `steam-relaunched-installed.png`.

## 2026-08-08: runaway logs filled the filesystem

`steamwebhelper.log` allocated about 8.4 GiB and `chrome_debug.log` about 16.7
GiB. Truncation while writers remained open merely created huge sparse files at
their retained offsets; output continued around 150 MB every few seconds. The
orphan helper trees were stopped, closed files cleared, and only those two debug
streams linked to `/dev/null`. The launcher reapplies this guard. Normal Steam
and launcher logs remain. Roughly 30 GB was free after deleted handles closed.

## Known incomplete work

Authentication, UI interaction, downloads, native ARM64 client execution, and
Turnip selection are demonstrated. Windows-game execution is not yet proven.
Next: integrate and validate an ARM64 Proton/FEX (or equivalent) guest layer,
then test DXVK, VKD3D, audio, controller input, and a small Windows game before
Burnout.

## 2026-08-08: first complete Burnout launch trace

Steam accepted a Burnout launch request and advanced through `UnlockingH264`,
shader-cache processing, license checkout, and `CreatingProcess`. No Proton,
Wine, FEX, EA launcher, or game process was spawned.

The immediate failure occurred in Steam's compatibility manager. Its cache-off
job was still registering every historical Proton generation at approximately
35 seconds per entry. PRoot consumed about 87% of one CPU core and accumulated
hundreds of thousands of context switches. When Proton Experimental requested
its installed Runtime 4 dependency (App ID 4183110), Steam reported the tool as
unknown because the cache rebuild had not reached it. Command-line wrapping
failed and Steam released the game session.

The Runtime 4 installation and `toolmanifest.vdf` were verified complete. This
distinguishes a slow/incomplete compatibility-cache rebuild from missing game
files or a Proton/game crash. The live state is captured in
`docs/evidence/2026-08-08-live-debugging-compat-timeout.png`.
