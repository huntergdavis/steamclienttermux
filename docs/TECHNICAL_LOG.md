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
inside this PRoot/app-sandbox arrangement. See `flicker-1.png` and
`cef-software-fixed-20260807-162701.log`. The stable-UI screenshot was removed
because it exposed private account information.

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
The official ARM64 Proton and runtime are registered and Burnout has an explicit
mapping. Its first correctly mapped launch reached ARM64 Pressure Vessel, whose
metadata scan exposed a PRoot `link2symlink` inconsistency and crashed before
Proton, Wine, FEX, the EA App, or Burnout started. Next: validate the isolated
PRoot correction, then continue through FEX, DXVK, Turnip, audio, and controller
initialization without speculative workarounds.

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

## 2026-08-08: ARM SDK layout and the correct Proton artifacts

Once compatibility registration completed, the first real launch failed before
Proton with `/root/steam-arm/.steam/sdkarm64/steam-launch-wrapper: not found`.
The ARM client stores that wrapper in `linuxarm64`, while its game-launch command
uses Steam's traditional `$HOME/.steam` SDK names. The isolated launcher now
creates narrow symlinks for `sdkarm64`, `bin64`, `bin32`, and `steamrtarm64`.
It intentionally keeps `.steam` as a real directory because Steam stores live
account and IPC state there.

That exposed the next architecture mismatch: Burnout was automatically mapped
to conventional x86-64 Proton Experimental (App ID 1493710) and x86-64 Steam
Linux Runtime 4.0 (App ID 4183110). The x86-64 `pressure-vessel-wrap` cannot be
executed directly on this AArch64 userspace and exited 127. The required native
tools are separate Steam applications:

- Proton 11.0 (ARM64), App ID 4628740;
- Steam Linux Runtime 4.0 - Arm64, App ID 4185400.

Proton 11.0 (ARM64) downloaded completely (3,596,743,348 installed bytes). The
ARM64 runtime download was started next. Burnout must then be explicitly mapped
to Proton 11.0 (ARM64); installing it alone does not replace Steam's automatic
Proton Experimental mapping.

## 2026-08-08: register the separately distributed ARM64 tools

The installed ARM64 applications were absent from the compatibility-tool list
in the cached SteamPlay 2.0 Manifests application (App ID 891390). Their own
`toolmanifest.vdf` files were valid, but installing the applications did not add
them to Burnout's compatibility dropdown.

The launcher now renders
`config/steam-arm64-compatibilitytools.vdf.in` into Steam's canonical local-tool
directory:

```text
~/steam-arm64/client/compatibilitytools.d/steam-arm64-official/compatibilitytool.vdf
```

This declares the untouched installed payloads with explicit local keys:

- `proton_11_arm64_official`: Proton App ID 4628740, depot 4628741;
- `steamlinuxruntime_4_arm64_official`: runtime App ID 4185400, depot 4185401.

The Proton declaration and its installed `toolmanifest.vdf` both preserve the
runtime dependency on App ID 4185400. The first attempt placed the declaration
at `/root/steam-arm/.steam/compatibilitytools.d`. A full registry pass completed
at 16:11:23 without either ARM tool, and access times proved Steam never opened
that directory. This installation has no conventional `~/.steam/root` symlink;
placing the descriptor directly under the actual client root fixed discovery
without replacing the live `.steam` state directory.

On the corrected start, `compat_log.txt` recorded at 16:37:00:

```text
Processing local tool list at .../client/compatibilitytools.d/steam-arm64-official/compatibilitytool.vdf...
Registering tool proton_11_arm64_official, AppID 4628740
Registering tool steamlinuxruntime_4_arm64_official, AppID 4185400
Loaded manifest for tool proton_11_arm64_official.
Loaded manifest for tool steamlinuxruntime_4_arm64_official.
```

The launcher also makes `-noverifyfiles` a fixed client argument. It does not
disable the normal client-version manifest check. It skips bootstrap file-size
verification because this project deliberately patches one minified Steam UI
chunk. A bare start without the flag detected the 57-byte intentional size
difference and spent about eleven minutes extracting and reinstalling the same
client build. After the stock file was restored, all three exact UI signatures
were verified, the guard was reapplied, and the next start logged `Verification
skipped` with exactly one `-noverifyfiles` argument.

## 2026-08-08: registry completion and explicit Burnout mapping

The corrected compatibility registry pass completed at 00:13:45 UTC on
2026-08-09 (17:13:45 local time on 2026-08-08) and posted the two queued ARM64
tool-registration callbacks. Steam resolved these exact command prefixes:

```text
Command prefix for tool 4185400 "Steam Linux Runtime 4.0 - Arm64" set to: "'/data/data/com.termux/files/home/steam-arm64/client/steamapps/common/SteamLinuxRuntime_4-arm64'/_v2-entry-point --verb=run -- "
Command prefix for tool 4628740 "Proton 11.0 (ARM64)" set to: "'/data/data/com.termux/files/home/steam-arm64/client/steamapps/common/SteamLinuxRuntime_4-arm64'/_v2-entry-point --verb=run -- '/data/data/com.termux/files/home/steam-arm64/client/steamapps/common/Proton 11.0 (ARM64)'/proton run "
```

This confirms that the ARM Proton tool depends on
`SteamLinuxRuntime_4-arm64`; neither prefix uses conventional Proton
Experimental or the x86-64 `SteamLinuxRuntime_4` directory.

The UI remained on its loading spinner after registry completion, and opening
the Burnout Properties URI did not render a usable dialog. Steam was shut down
before the fallback edit. The live configuration files were preserved under:

```text
~/steam-arm64/backups/20260808-172147-post-shutdown-before-burnout-arm-mapping
```

With Steam offline, `~/steam-arm64/client/config/config.vdf` received this
standard explicit entry under
`InstallConfigStore/Software/Valve/Steam/CompatToolMapping`:

```text
"1238080"
{
	"name"      "proton_11_arm64_official"
	"config"    ""
	"priority"  "250"
}
```

The next startup log accepted the edit at 00:34:35 UTC, recording Burnout App
ID 1238080 mapped to `proton_11_arm64_official` at priority 250. This proves the
explicit selection was loaded. The two queued compatibility cache passes then
completed at 00:48:03 UTC. Steam explicitly skipped its automatic priority-100
`proton-experimental` mapping because the priority-250 ARM64 mapping already
existed.

Screenshot capture also needs a bounded runtime in this environment:

```sh
timeout 40s proot-distro login debian --shared-tmp -- /bin/bash -lc \
  'DISPLAY=:0 import -window root /data/data/com.termux/files/home/steam-arm64/current-screen.png'
```

An unbounded capture left an orphaned `import`/PRoot process. That process
blocked the Steam updater handoff until it was identified and terminated. The
timeout prevents a future capture from silently holding the startup sequence
open.

## 2026-08-08: first official ARM64 Proton launch and Pressure Vessel crash

Burnout was launched through `steam://rungameid/1238080` at 17:50:57 local
time. Both the install-script evaluator and the game-process log selected
`proton_11_arm64_official`. The actual game command began with:

```text
SteamLinuxRuntime_4-arm64/_v2-entry-point --verb=waitforexitandrun --
Proton 11.0 (ARM64)/proton waitforexitandrun
link2ea://launchgame/1238080?platform=steam&theme=bprm
```

There was no reference to conventional Proton Experimental or the x86-64
`SteamLinuxRuntime_4` directory. This confirms the registry and explicit
mapping work. It does not yet prove Proton itself runs: the ARM64
`pressure-vessel-wrap` process received `SIGSEGV` before Proton, FEX, Wine, the
EA App, or Burnout appeared in the process tree. Steam recovered to the Burnout
library page with its green Play button.

Both the evaluator and game crashes had the same symbolized signature in the
runtime's bundled GLib 2.66.8:

```text
instruction offset 0x41390: g_str_hash+0
link-register offset 0x3fce4: g_hash_table_lookup_extended
fault address: 0x0
```

The matching Pressure Vessel 0.20260714.0 source explains the null key. During
runtime cleanup, `pv_runtime_remove_overridden_libraries()` trusts a directory
entry reported as `DT_LNK`, ignores failure from its following `readlinkat`, and
passes the resulting null target to a string-keyed hash lookup.

The underlying inconsistency is in PRoot's `link2symlink` extension. A direct
syscall probe on an emulated hard link showed:

```text
getdents64 d_type: DT_LNK
guest lstat type: regular file
guest readlink: EINVAL
```

The host file is a symlink into PRoot's `.l2s` storage, but PRoot deliberately
presents it to the guest as a regular hard link for `stat` and `readlink`.
`link2symlink` does not currently filter `getdents` or `getdents64`, so the raw
host `DT_LNK` leaks through. Pressure Vessel therefore takes its symlink path
and receives the contradictory regular-file behavior. Replacing GLib cannot
fix this null input. The preferred fix is to make the extension report
`DT_UNKNOWN` only for `.l2s`-backed directory entries, letting the caller query
the already-correct guest `fstatat` result. Any modified PRoot must be built and
validated separately before replacing the production launcher binary.

Compatibility scanning was also strongly affected by Android scheduling. With
Termux:X11 in the foreground, the Termux UID was restricted to the moderate
cpuset on CPUs 0-3 and registry intervals took 52-54 seconds. Bringing the
Termux activity to the foreground moved the same live Steam processes to the
top-app cpuset on CPUs 0-7; the same intervals fell to 7-8 seconds, about a
6.9x improvement. This is a useful non-destructive optimization for future
nonvisual registry work; Termux:X11 must be foregrounded again for visual
inspection.

## 2026-08-08: complete ARM64 Runtime 4 container passes under PRoot

Before implementing the Pressure Vessel fixes, two local history searches were
run as required by the workspace instructions:

```text
deja "PRoot bubblewrap Can't bind mount bindfile newroot etc passwd Unable to find in mount table"
deja "PRoot Bubblewrap fchdir to oldroot No such file or directory after pivot_root"
```

Neither query matched an indexed prior agent session, so no previous-session
solution was reused. The implementation below was derived from the live traces,
the pinned PRoot source, and Bubblewrap's matching pivot sequence in the
[Steam Runtime Tools source](https://gitlab.steamos.cloud/steamrt/steam-runtime-tools/-/blob/v0.20260714.0/subprojects/bubblewrap/bubblewrap.c#L3039).

The first fix makes the `link2symlink` extension post-process `getdents` and
`getdents64`. A raw `DT_LNK` is changed to `DT_UNKNOWN` only when the host entry
is confirmed to point into PRoot's private `.l2s` storage. A focused regression
probe then produced the internally consistent results:

```text
source:   d_type=DT_UNKNOWN, lstat=regular, readlink=EINVAL
hardlink: d_type=DT_UNKNOWN, lstat=regular, readlink=EINVAL
symlink:  d_type=DT_LNK,     lstat=symlink, readlink=target=source
```

Pressure Vessel next encountered pseudo-hardlinks as physical bind sources
below its emulated `/oldroot`. Final host-path canonicalization now resolves a
confirmed `.l2s` backing path.

Two separate Bubblewrap translation failures remained. Exact host bindings
whose source is also inside the guest root were being discarded by PRoot's
reverse binding lookup, yielding:

```text
Can't bind mount /bindfile... on /newroot/etc/passwd: Unable to find the mount point in the mount table
```

The existing safety guard is retained for descendants, but an exact binding is
now allowed to win. Finally, Bubblewrap's second `pivot_root(".", ".")` keeps an
fd for the detached root, calls `fchdir()` on it, detaches `.`, and changes to
the new `/`. PRoot now gives that detached root a transient per-vpid binding
and drops bindings belonging to the stale namespace snapshot so they cannot
win fd detranslation over the alias. The focused fd probe prints
`pivot-root-fd: PASS`.

The first full-container smoke test exposed a validation mistake. Its narrow
hard-link guard compared the configured guest `var/tmp-` prefix with a syscall
argument that PRoot had already canonicalized to a host path. The command
exited zero, but a later host-side audit showed all 136 regular Pressure Vessel
files had been converted back into `.l2s` pseudo-links. The wrapper then failed
to load `libjson-glib-1.0.so.0`. Guest-side `find -type f` had hidden the
conversion because `link2symlink` intentionally presents those backing links
as regular files. This invalidated the first smoke-test conclusion and binary:

```text
00cdd490de055ca71bbb8ec75eacc22d29f708d9221eff8bf2cf4cc9178d36ae
```

The corrected guard translates the opt-in guest prefix with PRoot's own
`translate_path()` before comparing it with the canonicalized destination.
The `/proc/self/fd` special case still runs first, the prefix must be absolute
and end in `/tmp-`, and no behavior changes when the environment variable is
absent. Pressure Vessel now receives `EXDEV` and uses its normal copy fallback.

All production patches were applied to a clean checkout of Termux PRoot commit
`a89b3732ec6ae1db674510f0843b2f3db54d0a2f` and built with
`PROOT_WITH_LIBANDROID_SHMEM=1`. The corrected binary has SHA-256:

```text
5ec617e9177076d40bf1fd878387a419ff4fa6f7be32b1a0448a3e6fc38db8d5
```

The build script now stamps the commit, ordered patch-set hash, and complete
source-diff hash. A second build verified the stamp instead of applying any
patch twice. The patch-set and diff hashes were respectively:

```text
693ad81804c9c1376ff4dc9c1fa78aad1e3fe8205b48b2ee8476760c91c46179
3e233db7b62e2494909a92fe2d902e623c58178a53285f97f29ce24836de7a02
```

A fresh isolated shadow was prepared at
`~/steam-arm64/runtime/SteamLinuxRuntime_4-arm64-v2`. It preserves the
installed official ARM64 runtime and its prior `var` state, while replacing
the active Pressure Vessel tree with the hash-identical real-file ARM64 copy
shipped in the installed conventional Runtime 4 depot. Its
`pressure-vessel-wrap` SHA-256 is:

```text
f53f2e6574926d1e5bebac4ca43e19138d10941826bc397520508dcfa6648182
```

Using the corrected PRoot build and this exact shadow path, the complete
official ARM64 Runtime 4 entry point passed:

```text
_v2-entry-point --verb=run -- /bin/true
exit status: 0
host Pressure Vessel: 136 regular files, 0 .l2s links
host mutable runtime: 5,372 regular files, 0 .l2s links
```

Steam does not honor the local Runtime 4 `install_path` when Proton's
`require_tool_appid=4185400` is resolved. After the compatibility pass completed
at 02:16:17 UTC, the command prefix still used
`client/steamapps/common/SteamLinuxRuntime_4-arm64`. The installed
`appmanifest_4185400.acf`, library metadata, and ARM `steamclient.so` strings
confirm that this path is computed through `GetAppInstallDir()`.

The non-destructive solution is an outer PRoot bind from the prepared shadow
onto that exact guest depot directory. The appmanifest and both official depot
trees remain unchanged on the host. A second complete smoke test used the bind
and Steam's exact computed path; it also exited zero with 136 real Pressure
Vessel files, 5,372 real mutable-runtime files, and zero `.l2s` links on the
host.

This is the first valid end-to-end confirmation that Pressure Vessel builds and
enters its full mutable ARM64 container under both the direct and actual Steam
path spellings. It proves the runtime boundary, not Burnout, Proton, FEX, Wine,
DXVK, or the EA App.

Steam was shut down gracefully before deployment. The old launcher, manifest
template, PRoot binary, generated compatibility manifest, and `config.vdf` are
preserved at:

```text
~/steam-arm64/backups/20260808-191150-before-pressure-vessel-runtime-fixes
```

That deployment was subsequently shown to contain the invalid first guard and
shadow, so it is retained as diagnostic history rather than accepted as the
final fix.

The corrected runtime checkpoint was committed and pushed as `dfa15f6`. A
full-resolution 2800x1586 screenshot showed the authenticated Steam Store UI
rendering normally before deployment. Steam then exited cleanly six seconds
after a forwarded `-shutdown` request. The live launcher, compatibility-tool
template, generated manifest, `config.vdf`, old PRoot hash, and invalid runtime
shadow were preserved without deletion at:

```text
~/steam-arm64/backups/20260808-194157-before-runtime-v2-overlay
```

The tested v2 shadow was atomically promoted to
`~/steam-arm64/runtime/SteamLinuxRuntime_4-arm64`, and the clean stamped build
was installed at `~/steam-arm64/src/proot-production/src/proot`. The deployed
hashes are:

```text
launcher:        548d79bfae0e5d6a87288c84ba4a13285719139d004980d212b667e8f0a706e1
patched PRoot:   5ec617e9177076d40bf1fd878387a419ff4fa6f7be32b1a0448a3e6fc38db8d5
PV wrapper:      f53f2e6574926d1e5bebac4ca43e19138d10941826bc397520508dcfa6648182
```

Steam restarted at 02:42:22 UTC with main PID 22724 and PRoot parent PID
22711. The parent command line contains the exact bind:

```text
runtime/SteamLinuxRuntime_4-arm64:
client/steamapps/common/SteamLinuxRuntime_4-arm64
```

Its environment contains the guest-visible copy-fallback prefix
`client/steamapps/common/SteamLinuxRuntime_4-arm64/var/tmp-`. Turnip sysinfo
still completed successfully after restart. The new registry pass registered
both ARM tools and retained Burnout's priority-250 mapping.

## 2026-08-08: spaced compatibility-tool paths in synthetic mountinfo

The post-restart registry pass completed at 02:52:46 UTC. In the same second,
Steam posted registration callbacks for App IDs 4185400 and 4628740 and set
these fresh command prefixes:

```text
SteamLinuxRuntime_4-arm64/_v2-entry-point --verb=run --
SteamLinuxRuntime_4-arm64/_v2-entry-point --verb=run -- Proton 11.0 (ARM64)/proton run
```

The priority-100 automatic `proton-experimental` mapping was skipped because
Burnout retained the explicit priority-250 `proton_11_arm64_official` mapping.
A full-resolution 2800x1586 screenshot at
`~/steam-arm64/prelaunch-runtime-v2.png` showed the Steam Store UI rendering
normally before launch.

The launch request began at 02:55:27 UTC. Both its install-script evaluator and
the subsequent real `link2ea://launchgame/1238080?platform=steam&theme=bprm`
action selected official Proton 11 ARM64 and the ARM64 Runtime 4. Each completed
the slow mutable-runtime copy and then failed before Proton, FEX, Wine, the EA
App, or Burnout started:

```text
bwrap: Can't bind mount /oldroot/.../Proton 11.0 (ARM64)
on /newroot/.../Proton 11.0 (ARM64):
Unable to find "/newroot/.../Proton 11.0 (ARM64)" in mount table
```

The error appears at lines 18583 and 37085 of
`~/steam-arm64/logs/steam-20260808-194221.log`. The preserved post-launch
screenshot `~/steam-arm64/post-first-arm64-launch.png` shows a healthy Steam
Store/KDE desktop but no game or EA window. Both host-side integrity audits
still reported zero `.l2s` links.

Before diagnosis, these required history searches returned no indexed match:

```text
deja "bwrap Unable to find newroot Proton ARM64 mount table PRoot same-dir pivot bind mount"
deja "PROot bwrap Can't bind mount Unable to find in mount table emulate_pivot_root Proton ARM64 Pressure Vessel"
```

No prior-session solution was reused. The live trace, pinned PRoot source, and
Bubblewrap parser behavior isolated the fault to PRoot's synthetic mountinfo.
`append_runtime_binding_lines()` wrote mountpoint and source fields with raw
`%s`. Mountinfo requires spaces, tabs, newlines, and backslashes to be encoded
as `\040`, `\011`, `\012`, and `\134`. Bubblewrap splits on whitespace before
decoding those octal escapes, so the raw compatibility-tool path was parsed
only through `Proton` and could never equal the full destination.

The focused Bubblewrap reproducer produced this matrix with the deployed PRoot:

```text
bind /bin:                                  exit 0
bind Proton 11.0 (ARM64):                   exit 1
```

`proot-mountinfo-escape-paths.patch` now emits the required octal escapes for
both fields. `probe-proot-mountinfo-escape.sh` verifies a bind containing both
spaces and a literal backslash. `probe-proot-bwrap-spaced-bind.sh` exercises the
bundled ARM64 `srt-bwrap` parser with both the no-space control and the actual
official Proton directory. Against the isolated v3 build, both Bubblewrap cases
exited zero and the mountinfo probe printed `mountinfo-escape: PASS`.

The v3 build remains pinned to PRoot commit
`a89b3732ec6ae1db674510f0843b2f3db54d0a2f`. Its provenance is:

```text
patch-set SHA-256: ef0d425bc118d54ad701e01123c09ab0da71c6001ab33bdebe24a68082367fda
source-diff SHA-256: 8244798771f0c30d27ca09d28a3ff49227e0ca4bfe53daaac8780aa3c6bc44a9
binary SHA-256: c9ae8f9611b1009568ac18a8d83695440306e25e0f0b4223d09bf821ca2d6a53
```

Finally, the complete official ARM64 Runtime 4 smoke test using the exact Steam
path overlay exited zero after 177 seconds. Host audits found 136 real Pressure
Vessel files, 5,372 real mutable-runtime files, and zero `.l2s` links. The log
`~/steam-arm64/logs/proot-v3-full-runtime-smoke-20260808-2010.log` contains no
unexpected error. This validates the fix before production deployment; it does
not yet prove Proton, FEX, Wine, EA App, or Burnout execution.

The confirmed fix was committed and pushed as `822880d`. Steam then shut down
gracefully ten seconds after its own `-shutdown` forwarder completed. The prior
complete production PRoot tree and unchanged launcher are preserved at:

```text
~/steam-arm64/backups/20260808-201650-before-mountinfo-v3
```

The v3 source tree was atomically promoted to
`~/steam-arm64/src/proot-production`; its commit, patch-set hash, source-diff
hash, and binary hash all matched the isolated build. Steam restarted on PRoot
PID 32757 and main PID 320. `/proc/32757/exe` has the expected
`c9ae8f9611b1009568ac18a8d83695440306e25e0f0b4223d09bf821ca2d6a53`
hash, and its command line and environment retain the exact ARM64 runtime
overlay and guarded `var/tmp-` prefix.

The new session log is `~/steam-arm64/logs/steam-20260808-201738.log`. Turnip
sysinfo still succeeds after restart and reports `Turnip Adreno (TM) 730`.
`~/steam-arm64/post-mountinfo-v3-restart.png` is a full-resolution 2800x1586
screenshot of the healthy Steam "Loading user data..." window. Steam registered
both ARM tools and the priority-250 Burnout mapping, then started compatibility
cache job 15488033736693968634 at 03:18:13 UTC. The queued second pass completed
at 03:47:16 UTC with callbacks for App ID 4185400 as
`steamlinuxruntime_4_arm64_official`, App ID 4628740 as
`proton_11_arm64_official`, and Burnout App ID 1238080. The log explicitly
skipped Burnout's lower-priority automatic `proton_experimental` mapping.

At 20:50:31 PDT, a single `steam://rungameid/1238080` launch was forwarded to
the existing Steam process. Session `bb257b8e4cd92f1` selected the official
`SteamLinuxRuntime_4-arm64` and `Proton 11.0 (ARM64)` paths for both its install
evaluator and main `link2ea://launchgame/1238080` command. Both invocations
passed the old spaced-path mount-table failure, confirming the production
mountinfo fix against Steam's real launch path.

The next exact blocker is independent of the Proton path. Both invocations
ended at:

```text
bwrap: Can't get type of source /tmp/.X11-unix/X0: No such file or directory
```

The X0 socket exists natively in Termux and is visible from an ordinary
`proot-distro login debian --shared-tmp` shell, but the bundled ARM64
`srt-bwrap` cannot resolve it while setting up the container. The main launch
exited at 03:56:04 UTC before a Proton child, FEX, Wine, the EA App, or Burnout
started. Pressure Vessel and its mutable runtime still contain zero `.l2s`
links, and 27 GB remained free. The failed 370 MB temporary root
`var/tmp-EJJ2T3` was retained for inspection. A full-resolution post-failure
screenshot at `~/steam-arm64/post-x0-bind-failure.png` shows the authenticated
Steam Store healthy with no game or EA window.

## 2026-08-08: retain shared `/tmp` below Bubblewrap's staging mount

The X0 failure was not specific to sockets. These required history searches
returned no indexed match, so no previous-session solution was reused:

```text
deja "srt-bwrap PRoot Unix socket ro-bind X0 no such file Termux X11"
deja "PRoot srt-bwrap X0 unix socket lstat ENOENT pivot_root path translation bind source"
```

With production PRoot, bundled `srt-bwrap --ro-bind / /` could bind `/tmp`
itself, but every tested descendant of the shared Termux `/tmp` failed with
`ENOENT`: a regular file, a child directory, the existing X0 socket, and a
fresh AF_UNIX socket. The same regular file, directory, and exact live X0 inode
all succeeded when the outer PRoot exposed them below `/mnt`. This ruled out
file type, socket permissions, and the host source path.

`PROOT_VERBOSE=9` showed the exact lifecycle. The outer namespace initially
translated `/tmp` through `$PREFIX/tmp`. Bubblewrap then mounted a private
tmpfs at guest `/tmp` for its staging root. PRoot's equal-guest insertion
discarded the covered `$PREFIX/tmp:/tmp` binding. After the first
`pivot_root`, Bubblewrap resolved its pre-opened source below
`/oldroot/tmp/.X11-unix/X0`, but PRoot could only see the staging tmpfs and
returned `ENOENT`.

`proot-runtime-mount-stack.patch` gives emulated runtime mounts ordered stack
semantics. The newest equal guest binding is active, `umount` reveals the
covered entry, namespace copies preserve active-to-covered order, and
`pivot_root` excludes the active new-root layer while re-exposing its covered
underlay below `oldroot`. Root lookup now selects the active binding, and
synthetic mountinfo emits only the active entry for duplicate guest paths.

`probe-proot-bwrap-shared-tmp-bind.sh` creates a validated Termux-tmp fixture
and checks both its regular file and containing directory through the bundled
ARM64 `srt-bwrap`. The identical harness fails against production v3 with the
original `No such file or directory`, and exits zero against isolated v4b.
The v4b build also passes the mountinfo escape probe, both no-space and real
`Proton 11.0 (ARM64)` binds, and `pivot-root-fd.py`.

The isolated v4b build remains pinned to PRoot commit
`a89b3732ec6ae1db674510f0843b2f3db54d0a2f`. Its provenance is:

```text
artifact root:        ~/steam-arm64/src/mountstack-v4b-20260808-212006
source tree:          ~/steam-arm64/src/mountstack-v4b-20260808-212006/worktree
patch input SHA-256:  263d3db02e03ab90163d5080b26a806c4851af8c554ef33c81b57b2911a64ca9
probe SHA-256:        8d5e7ac5881c03585dbe69a18385c0dbe3f7a9c2fbeacc11564372338116a52a
patch-set SHA-256:    fa72be34b4317763eb6c7f0eeb048a475eb6be5a1ef33d1bc9d57cb174f71258
source-diff SHA-256:  ceac3039e9321553b2faee363b71b26d54e3620b7c1a8e54f8e557bd3efb525a
binary SHA-256:       981c304c7cf156ea7f7068fc2d3ed781aef1d2514c5d128b0ce0b57d52ad47ca
```

A complete isolated official `SteamLinuxRuntime_4-arm64` smoke using
`_v2-entry-point --verb=run -- /bin/true` then exited zero. Its private
`var/tmp-56SZT3` contains 5,371 regular files; Pressure Vessel, all isolated
`var`, and the new temporary root contain zero `.l2s` links. The log contains
only the expected guarded `EXDEV` copy warnings and no unexpected missing-path,
permission, segmentation, fatal, or `E:` errors. The production binary remains
v3 hash `c9ae8f9611b1009568ac18a8d83695440306e25e0f0b4223d09bf821ca2d6a53`
until a guarded deployment, Steam remained alive, and 26 GB remained free.

The guarded production deployment then shut Steam down through its own
forwarder and observed a natural exit. The shutdown transcript is
`~/steam-arm64/logs/shutdown-before-mountstack-v4-20260808-213614.log`. The
complete v3 tree was preserved by atomic rename at:

```text
~/steam-arm64/backups/20260808-2136-before-mountstack-v4/proot-production-v3
```

The validated v4b tree was promoted to
`~/steam-arm64/src/proot-production`, retaining the isolated candidate
artifact. The promoted patch-set, source-diff, and binary hashes exactly match
the provenance above. Steam restarted through
`~/steam-arm64/logs/restart-mountstack-v4-20260808-213713.log`; its new session
log is `~/steam-arm64/logs/steam-20260808-213715.log`. Live process inspection
found Steam PID 17522 under outer PRoot PID 17515, and `/proc/17515/exe` has
the expected v4b binary SHA-256
`981c304c7cf156ea7f7068fc2d3ed781aef1d2514c5d128b0ce0b57d52ad47ca`.
The runtime shadow bind and guarded `PROOT_L2S_EXDEV_PREFIX` also remained
exactly as configured.

The post-restart screenshot
`~/steam-arm64/post-mountstack-v4-restart.png` (SHA-256
`2b3c7e8962c2a2ac4291c7a3063893c582d948f4a1acce68a3618837c1e61020`)
shows KDE responsive and Steam at `Loading user data...`, with no crash dialog
or game window. Before the new cache rebuild began, `compat_log.txt` again
loaded App IDs 4628740 and 4185400 as `proton_11_arm64_official` and
`steamlinuxruntime_4_arm64_official`, and mapped Burnout App ID 1238080 to the
ARM Proton at priority 250. The new cache job then began its known slow scan;
Burnout was deliberately not launched while registration remained incomplete.

## 2026-08-08/09: official Proton/FEX/Wine reaches the EA App

Compatibility cache job `1851510475679486629` completed at 05:06:28 UTC. In
the same second Steam posted callbacks for App ID 4185400 as
`steamlinuxruntime_4_arm64_official`, App ID 4628740 as
`proton_11_arm64_official`, and Burnout App ID 1238080. Steam again skipped the
priority-100 automatic Experimental mapping because the priority-250 ARM
mapping already existed. `~/steam-arm64/prelaunch-mountstack-v4.png` (SHA-256
`4aebe248d100d7737ff6eba464120bde9286511086ba401d32194b0902ef3332`)
shows the authenticated Steam Store before the single launch request.

The install-script evaluator started at 05:08:11 UTC and selected the official
ARM tool. Production PRoot v4b passed the previous X0 bind boundary and ran the
bundled `srt-bwrap`, `pv-adverb`, official Proton Python entry point, native
ARM64 Wine, and ARM64 wineserver. Proton upgraded the prefix to `11.0-100` and
generated `proton-fex-config.json`. Process maps and signal telemetry identified
both `libarm64ecfex.dll`/`libwow64fex.dll` and `[anon:FEXMemJIT]`, confirming
the official bundled FEX path.

The EA installer displayed its first-run `LET'S GO` UI. The exact visible child
window was validated as `EA app installer`, 480x480, before its button was
clicked. These screenshots preserve the milestone:

```text
~/steam-arm64/wine-prefix-init-v4.png
  bed33e8043245846f10867291bbd951f1538ed13599e63d6aac0e11334b78aa3
~/steam-arm64/ea-installer-window-v4.png
  af0f34146d6bccf6b1dc3617a96d26080e6e5fe81f9598eff7053c595e4499a9
~/steam-arm64/ea-after-lets-go-v4.png
  83be20fe233cb396e307047d8e49b548b6cc579bf72bc21187fd4d7656362e5c
```

EA unpacked roughly 556 MB and invoked `EABackgroundService.exe -start`, but
the MSI transaction rolled back. The authoritative terminal artifact is:

```text
~/steam-arm64/client/steamapps/compatdata/1238080/pfx/drive_c/users/steamuser/AppData/Local/Temp/Setup_20260809053742_Failed.txt
SHA-256 2258a43b898517f750fad153876b68d8e31b2bda4c0f7c288f21f78e7bcdc814

Error 0x800700e8: Failed to pump messages from parent process.
Error 0x800700e8: Failed to run per-machine mode.
```

`0x800700e8` is Win32 `ERROR_NO_DATA`. The original clean-room/UI parent had
exited about twenty minutes earlier, leaving the elevated Burn child without
its IPC peer. The MSI log did not preserve the service return code, so this
does not prove that EA's supported `EAX_DISABLE_SYMLINKS` option is relevant.
No EA override was applied. The source `installScript.vdf` remains signed and
unchanged.

DirectX proceeded slowly through 154 CAB files after EA rolled back. Every
observed helper returned zero, and `windows/Logs/DirectX.log` ended at 05:48:50
UTC with:

```text
Installation ended with value 0 = Installation succeeded
```

The prefix registry now contains Steam's DirectX June 2010 completion marker,
so a normal retry should not repeat that prerequisite.

Steam naturally advanced into the main command at 05:52:10 UTC:

```text
SteamLinuxRuntime_4-arm64/_v2-entry-point --verb=waitforexitandrun --
Proton 11.0 (ARM64)/proton waitforexitandrun
link2ea://launchgame/1238080?platform=steam&theme=bprm
```

That attempt re-entered the cached EA bundle, but it was invalidated by the
screenshot workflow rather than an EA payload failure. An earlier
`import -window 0x4800091` remained alive after its transient target vanished.
ImageMagick's X11 import path grabs the server until image retrieval returns;
Termux:X11 frame telemetry stopped while that helper was stuck and resumed in
the exact second it was terminated. See the upstream
[`XImportImage` implementation](https://www.imagemagick.org/api/MagickCore/xwindow_8c-source.html).

EA started while the server was grabbed and logged:

```text
Error 0x800703e6: Failed to create window.
CreateDialogParam failed: File not found.
```

Its UI thread then exited, package detection completed, and both remaining EA
processes slept indefinitely in `pipe_read`. The cached and clean-room
installer executables were byte-identical, no new crash/failure artifact was
created, and no EA window appeared after X11 recovered. Therefore this run is
not evidence for changing `EAX_LAUNCH_CLIENT`, `IGNORE_INSTALLED`, symlink
mode, or Proton settings.

The recovered full desktop screenshot
`~/steam-arm64/main-link2ea-stuck-ea.png` has SHA-256
`4a3a26b00bda9aa24436106778a40df462022b6ed7bc904b15cd1da6f237837d`.
The Steam-only confirmation screenshot
`~/steam-arm64/steam-after-stop-click.png` has SHA-256
`cc0f43276a478965024f2f3a91593a0ea8bb63a4d0698bfaaeaa2252f2f6ee5d`.
After the exact visible Stop/Confirm controls were used, Steam removed App
1238080 from the running list at 06:07:28 UTC; the outer tracked PID exited
zero and every Runtime/Proton/Wine/EA child disappeared.

Future X11 evidence capture must use a hard timeout and a stable target, for
example:

```sh
timeout 12 env DISPLAY=:0 import -window <stable-window-id> output.png
```

After a timeout, verify that no `import` or capture-side `xdotool` process
survived before allowing a new GUI process to start. Do not capture a transient
window by ID while it may be closing.

The signed Steam install script, prefix registries, active EA logs, and failure
artifact were preserved before retry work under:

```text
~/steam-arm64/backups/20260808-2300-ea-before-retry
```

Before diagnosing the EA window failure and manifest-rescan behavior, focused
`deja` queries returned no indexed matches. No prior-session solution was
reused.

## 2026-08-08: avoid registry rebuilds for unchanged ARM manifests

Forwarded `steam://` commands also enter `bin/steam-arm`. The launcher formerly
rendered the ARM compatibility manifest to a temporary file and unconditionally
replaced the destination. A navigation request at 23:05:19 PDT changed the
manifest mtime without changing its content; Steam began compatibility cache
job `17304496708137475581` shortly afterward.

The launcher now streams the generated manifest into `cmp` first. Identical
content creates no temporary directory entry and does not touch the destination;
only a real content change uses a unique same-directory `mktemp` followed by an
atomic replacement. A two-pass focused test retained the same inode and mtime,
first-run and changed-content tests passed, and 128 concurrent publishers
completed with exact content and no leftover temp files. `bash -n` passed, and
ShellCheck passed after excluding the existing intentional SC2016 warning for
the single-quoted inner PRoot script. This avoids both metadata-only
compatibility scans and fixed-temp races between concurrent URI forwarders.

The new cache job was allowed to continue; Burnout will not be launched again
until it completes and reconfirms the priority-250 ARM mapping. The next test is
one clean, otherwise unmodified Steam launch with no screenshot helper active
during EA startup. A direct quiet bundle/MSI workaround remains a later option
only if the clean run reproduces the parent-IPC failure.

The reviewed launcher was deployed without executing it. Its live SHA-256 is
`c8af1a27e6e9ed716a77bdd04021ee0fc23edad9334d06e036f63851e0bd2b26`.
The prior launcher (SHA-256
`548d79bfae0e5d6a87288c84ba4a13285719139d004980d212b667e8f0a706e1`)
is preserved at:

```text
~/steam-arm64/backups/20260808-2300-ea-before-retry/steam-arm.before-manifest-idempotence
```

Cache job `17304496708137475581` then completed naturally at 06:19:17 UTC and
again retained Burnout's priority-250 `proton_11_arm64_official` mapping over
the priority-100 automatic Experimental entry. This incremental pass did not
post new ARM callbacks; the retained callbacks remain those from 05:06:28 UTC,
and live `config.vdf` plus the latest command prefixes still select the exact
ARM64 runtime and Proton paths.

A live navigation-only forwarder test at 23:20:40 PDT then exercised the
deployed launcher without starting a game. Before and after the command, the
manifest retained inode 717612, mtime `2026-08-08 23:05:19.512701718 -0700`,
size 853, and SHA-256
`051c887425acd289c225d02f6225014d63b29dc7c66f9b705bc27f3627dfcffe`.
No new cache job appeared during the observation interval. This confirms the
fix against a real existing-client URI forward, not only the focused harness.

## 2026-08-09: fail closed on contaminated ARM64 runtime shadows

The prepared ARM64 runtime must never contain PRoot `.l2s` pseudo-hardlink
symlinks. They encode paths from the temporary copy namespace and can silently
turn a reusable shadow into a host-specific, mutable tree. The preparation
script now routes donor, staged-tree, and existing-shadow checks through one
`require_no_l2s_links` guard. It rejects both a matching link and any failed
`find` traversal; an existing marker and matching wrapper hash are no longer
trusted until the whole Pressure Vessel tree passes that check.

Focused fixtures passed for a clean first preparation, idempotent reuse, donor
contamination, existing-shadow contamination, staged contamination, and an
unreadable scan root. `bash -n`, ShellCheck, and `git diff --check` also pass.
This hardening complements the earlier 136-link recovery; it does not alter the
live Steam depot or select the experimental PRoot build.

## 2026-08-09: direct Link2EA proves EA authentication and prerequisites

The installed EA service was preserved and configured with
`ServicesPipeTimeout=60000`. An isolated official-Proton session then started
the service and Link2EA directly. The authoritative transcript is:

```text
~/steam-arm64/logs/ea-service-timeout-and-link2ea-20260809-0140.log
terminal marker: LINK2EA_RC=0
```

EA's own logs show that Link2EA obtained an external-login authorization code
and access token, fetched the persona, confirmed the linked Steam/EA account,
queued App ID 1238080, and waited for the game launch request. EA Desktop and
EALocalHost also started. EABackgroundService subsequently installed all four
bundled Visual C++ prerequisites (11 x86/x64 and 12 x86/x64) successfully.
The request was dequeued only after EA Desktop became ready, while those
prerequisites were still running. This proves service startup, authentication,
account linking, and prerequisite completion. It does not prove that
`BurnoutPR.exe` started or rendered.

## 2026-08-09: Steam's Link2EA path crashes in official ARM DXVK d3d11

The clean canonical Steam launch selected
`proton_11_arm64_official`, App ID 4628740, and its required
`SteamLinuxRuntime_4-arm64`, App ID 4185400. The real command used the expected
URI:

```text
link2ea://launchgame/1238080?platform=steam&theme=bprm
```

Official Proton Python, native ARM64 wineserver, Wine's Steam stub, and FEX all
started. Link2EA then terminated before creating an EA log or window. PRoot's
terminal signal record was stable across repeated launches:

```text
signal=11 code=2 fault=0x6ff9340000 ip=0x6ff9340000
map=6ff9340000-6ff9341000 ...
    compatdata/1238080/pfx/drive_c/windows/system32/d3d11.dll
```

The faulting prefix file is 7,569,408 bytes with SHA-256
`27a79be7a0db74af3283a600b041c2ced087e4529678e6b1351488718608c676`.
It exactly matches official Proton 11 ARM64's
`files/lib/wine/dxvk/aarch64-windows/d3d11.dll`; Proton recopied it during the
launch. The companion prefix `dxgi.dll` likewise matches the official ARM DXVK
payload (`2c8df44028c1e5b707532cc4317827d9ceb306e6178eda52d2cbce89ee2b9cfe`).
This is not evidence of a stale or third-party DLL.

## 2026-08-09: overlay UI and overlay injection are separate controls

Burnout's Properties dialog was opened only after validating its exact X11
window. Before changing it, `localconfig.vdf` was preserved at:

```text
~/steam-arm64/backups/20260809-0213-before-overlay-test/localconfig.vdf
SHA-256 422f06c26050e5bedef41c4d8c1031b2169f766cbb2afd790bf8362f7411894f
```

The checkbox persisted the authoritative key
`UserLocalConfigStore/apps/1238080/OverlayAppEnable="0"`. The next process had
`SteamNoOverlayUI=1`, but its Pressure Vessel command and `LD_PRELOAD` still
contained the 64-bit, 32-bit, and ARM64 `gameoverlayrenderer.so` paths. Link2EA
reproduced the same `d3d11.dll` fault. Therefore the checkbox disables overlay
UI but is not an injection-removal control.

The installed ARM64 Pressure Vessel 0.20260714.0 supports the narrower
`PRESSURE_VESSEL_REMOVE_GAME_OVERLAY=1` switch. Valve's implementation maps it
to `--remove-game-overlay` and filters only preload paths ending in
`/gameoverlayrenderer.so`:

- <https://gitlab.steamos.cloud/steamrt/steam-runtime-tools/-/blob/v0.20260714.0/pressure-vessel/wrap-context.c#L868>
- <https://gitlab.steamos.cloud/steamrt/steam-runtime-tools/-/blob/v0.20260714.0/pressure-vessel/wrap-preload.c#L422>
- <https://gitlab.steamos.cloud/steamrt/steam-runtime-tools/-/blob/v0.20260714.0/pressure-vessel/wrap.1.md#L305>

Steam's Properties UI persisted the exact launch option under
`UserLocalConfigStore/Software/Valve/Steam/apps/1238080/LaunchOptions`:

```text
PRESSURE_VESSEL_REMOVE_GAME_OVERLAY=1 %command%
```

The pre-change backup is
`~/steam-arm64/backups/20260809-0310-before-remove-overlay-launch-option/localconfig.vdf`
with SHA-256
`fe87b3966a8e9087451515334debdc1777b38b2176ab7791260daec445062bf0`.
After the UI write, the live file hash was
`f6ece0176845e8d373100b1220166703c7a5b07e155e0c1f80985e7498ac4580`.

The real launch began at 03:20:23 PDT. Its shell command began with the exact
removal variable and used official ARM Runtime 4 plus Proton 11. The incoming
Pressure Vessel wrapper still received Steam's three preload arguments, but
the downstream `pv-adverb`, Proton Python, Wine Steam stub, and ARM wineserver
had no `--ld-preloads` argument and no `LD_PRELOAD` environment entry. This is
positive process-level proof that the supported filter worked. Nevertheless,
Link2EA PID 1770 reproduced the identical terminal `d3d11.dll` fault, no EA log
changed, no EA/Burnout window appeared, and Steam removed App ID 1238080 from
the running list at 03:24:07. Overlay injection is conclusively not the cause.

Visual evidence from the two overlay tests is preserved as follows:

```text
steam-burnout-properties-dialog.png              3a0e7d92f74b9e4e8fe0ef76086b240f898242fffdb08dde7dd9b37b2d9525b4
steam-burnout-overlay-off.png                    c40c0b394e78f375407bca25aecad35457c985d8874ee7c2e679258b4d7eda62
steam-burnout-overlay-off-launch.png             187340a81b6cff6d811a2a2bb113d918f95800cb089e5c2e99eb3f429de8a0f3
properties-before-remove-overlay-launch-option.png 78b88a02e95664ed6d85f1c70194b210a2c9f8403b78ce5c8f2c53bb4d6ff8d1
properties-remove-overlay-launch-option-set-2.png 9c3bf5c4c3b9f3156f1898053d44ac3720244c868f5db83765c363cc70f29001
canonical-remove-overlay-launching.png           187340a81b6cff6d811a2a2bb113d918f95800cb089e5c2e99eb3f429de8a0f3
canonical-remove-overlay-failed.png              07a0c5322963b5673f267813dbfae8379757adba80fc50fe769fadd125f4fd2f
```

The last image still showed a stale `STOP` button after all tracked processes
had exited; process and gameprocess-log evidence, not that transient UI label,
establishes the failure state.

Focused `deja` searches for the EA service timeout, Link2EA, overlay injection,
Pressure Vessel filtering, Proton verb behavior, and the exact `d3d11.dll`
base-address fault returned no reusable prior-session solution. Nothing from
cross-session recall was reused for these changes.

## 2026-08-09: direct Link2EA helper is diagnostic, not a Steam substitute

`scripts/run-ea-link2ea-direct.sh` reproduces the narrow direct path through
the prepared ARM Runtime 4 shadow and official Proton 11 `runinprefix`. It
checks every required file, fails closed on an unreadable or contaminated
runtime-shadow scan, and refuses to start while any wineserver is active.

Without Steam API context, Link2EA reached EA's logger but deliberately
fast-failed in its bundled `ucrtbase.dll` with `INT 0x29`. Setting
`STEAM_STUB_COUNT=0` did not change that result. The isolated stub-zero
transcript is:

```text
~/steam-arm64/logs/ea-link2ea-direct-stub0-20260809-032726.log
SHA-256 060c28d8fc9614daf4b1119eddc2c5ffd291f7b9ed3b254f0495131019ea9a97
```

Its EA crash artifact has SHA-256
`b75a352ccb8654fa7bd4d245000706cf22c0d2c2c21ed5df9ec1e3ec11591445`.
The exact crashed child was validated before an ordinary SIGTERM was sent;
the isolated subtree then exited without Wine or EA residue. This does not
invalidate the earlier direct session that authenticated and installed the
prerequisites: it shows that a reusable diagnostic invocation cannot replace
Steam's live API/stub context.

## 2026-08-09: ARM64EC import dispatch explains the DXVK image-base target

The official ARM DXVK `d3d11.dll` is COFF ARM64EC with preferred image base
`0x180000000`. Across five launches, its loaded base, faulting PC, return
address, and stack pointer were stable. Relative to loaded base
`0x6ff9340000`, LR `0x6ff94e9f98` is RVA `0x1a9f98`, exactly the instruction
after:

```text
RVA 0x1a9f94: bl 0x1803a9b04 <#memmove>
RVA 0x1a9f98: strb wzr, [x25, x21]
```

The ARM64EC `#memmove` thunk loads its target through the import/auxiliary
slot and explicitly supplies image RVA zero in `x10` before calling
`__icall_helper_arm64ec`. Microsoft's ARM64EC ABI defines `x10` as the exit
thunk for an indirect call. Valve Wine's checker substitutes that exit thunk
when the target is not classified as ARM64EC. Relocating RVA zero produces
the observed `0x6ff9340000` target exactly, whose header mapping is not
executable.

The bundled UCRT is ARM64X and contains both neutral ARM64 `memmove` and an EC
route, so the strong inference is a bad import target or Wine ARM64EC bitmap
classification at this boundary. The live IAT value was not captured;
therefore the exact loader mechanism is not yet proven. A conclusive debugger
capture would read D3D11 base plus `0x3c4430` immediately before the call and
compare it with the loaded UCRT routes.

Primary references:

- <https://learn.microsoft.com/en-us/windows/arm/arm64ec-abi>
- <https://github.com/ValveSoftware/wine/blob/proton_11.0/dlls/ntdll/signal_arm64ec.c>
- <https://github.com/ValveSoftware/wine/blob/proton_11.0/dlls/ntdll/unix/virtual.c>

## 2026-08-09: WineD3D bypasses the DXVK crash and reaches EA Desktop

Before the diagnostic, `localconfig.vdf` and all four tracked system32/syswow64
D3D DLLs were preserved under:

```text
~/steam-arm64/backups/20260809-0335-before-wined3d-diagnostic/
localconfig.vdf SHA-256 cf59b3d861020efdd388aed392a087b783e2ac194f126b991b711aa0122b3b5f
```

Steam's Properties UI persisted this exact launch option twice with stable
configuration hash
`8764267b1d5a98dcd80250e965142fd57e59146ed061930f682e49a0ea5dfa25`:

```text
PROTON_USE_WINED3D=1 PRESSURE_VESSEL_REMOVE_GAME_OVERLAY=1 %command%
```

The compatibility evaluator selected `proton_11_arm64_official`; the real
launch began at 10:46:58 UTC with both variables, official ARM Runtime 4, and
official Proton 11 ARM64. Downstream `pv-adverb`, Proton, Wine, and wineserver
again had no overlay preload. Proton replaced the prefix files as follows:

```text
d3d11.dll 34c5ea361c18cfaba22bf94b2c2c41fc4b269b0e655890913e40440d8087f1bf
dxgi.dll  6fd18f3672146bc0df65c26231082e4ad1517abe5d9894f71540cd597576fff4
```

Those hashes exactly match Proton's
`files/lib/wine/aarch64-windows/{d3d11,dxgi}.dll` built-ins. The original
prefix hashes exactly matched
`files/lib/wine/dxvk/aarch64-windows/{d3d11,dxgi}.dll`. This proves that the
test changed only Proton's supported D3D provider selection.

The DXVK image-base crash did not recur. Instead, the canonical Steam launch
created Link2EA, EABackgroundService, EADesktop, EALocalHostSvc, and CEF GPU,
storage, and network subprocesses. EA's non-verbose logs confirm:

- external Steam login, access-token acquisition, persona lookup, and account
  link succeeded;
- the catalog query for Steam App ID 1238080 returned HTTP 200 and one offer;
- the pending and authenticated Link2EA actions were pushed and later popped;
- EA Desktop reached `App ready`, LocalHost connected, and authentication
  telemetry became true.

No authentication codes, cookies, tokens, persona identifiers, or PLR payloads
are copied into this repository.

The next boundary is EA networking. At startup, EABackgroundService reported
`server_timeout`; EA Desktop set network state 4, told LoginHandler
`isOnline=false`, and entered `offlineAwaitingAuth`. Its
`DirtySDKConnectDetectionJob` later timed out without DirtySDK reaching an
online/offline/connecting state. This is not loss of tablet connectivity:
from the same Debian runtime, DNS and TLS completed and unauthenticated HTTP
requests reached all four observed hosts. `desktop-config.juno.ea.com` returned
200, while Statsig, RATT, and SAL returned application-level 403/404 responses.
EA's own earlier SAL and RATT requests also returned 200.

The running EA processes produced no mapped or hidden EA application window;
the only extra X11 objects were tiny unmapped DXGI device windows. KDE's visible
tray likewise contained no EA item. By 04:02 PDT, EADesktop, BGS, and LocalHost
were still alive and using CPU, but the non-verbose FSM log had not advanced
past LocalHost connection and `BurnoutPR.exe` had not started.

Visual evidence:

```text
wined3d-properties-before.png      d8e35c5c8be84d8cefb81d9896e833b5a66a3b8a9ba72f2c73270145886e01b0
wined3d-properties-set.png         095a14b475c3b5d0204dd300b2476d55ae1d763ab36bf3eb1837569f62868f9b
pre-wined3d-launch.png             ec6af22e196007cd0264752484c852a8178688acea9ffa13f5f62913cf9d2af3
wined3d-real-launch.png            41b4a59b757f5e46e1ffbc24e2264a4d7b4782c03633bd5d2dbe72477868be17
wined3d-link2ea-milestone.png      2acfaf9dc6584dee36a25346acb28e2e9f152b440181c0ed6a903c46de8924c8
wined3d-ea-ready.png               cf747dee0c20a7815460c5026e92428b725c6d1e997eb2a7594f8a2ac7928e92
wined3d-tray-open.png              c1a262de952bab5076da61188bbf1e5199cd28d5868ac1c568650bba9a0ecc25
wined3d-final-stalled.png          c87836fadae21efa7940a74ca2bb8a0f3edcf04643a4edfc40f177302ebd5b5e
wined3d-stop-dialog.png            afe479966f9dbb3d7dccfd02ef7466cef9ed1b5a03aae4846502c7d186adff53
wined3d-after-confirm-stop.png     27518469c8db77249365bee306a54966d5091e02971213ae481f5e5fca740f95
restore-properties-before.png     70479b92937f971c83339f58cb54f126407143bbdc4262cbfe08f3fa0df2d9ed
restore-properties-after.png      9267852f193e3726fbd377a76710355bf9d9bcef01d3588628b998cb8706b7aa
final-idle.png                     14a74e1cc693ee1f2d3adf82a43f40b60b0f1ab2840b95822911a7c42b6ada0b
```

After more than 15 minutes without another EA FSM transition or a
`BurnoutPR.exe` process, Steam's visible **STOP** button was used. The
confirmation dialog was captured and **Confirm** was clicked. At 11:08:59
UTC, `gameprocess_log.txt` removed every tracked PID and then removed App ID
1238080 from the running list; outer PID 8953 recorded exit code 143. No EA
Desktop, EA Background Service, EA LocalHost, CEF, Burnout, or wineserver
process remained. Steam itself stayed healthy under production PRoot without
a restart, and the final screenshot visibly returned to **PLAY**.

The diagnostic launch option was then restored through Steam Properties to:

```text
PRESSURE_VESSEL_REMOVE_GAME_OVERLAY=1 %command%
```

`localconfig.vdf` held that exact value with the same SHA-256
`093f4376e8a101c17a0f1069784380a5c89596da8f880a109fbba43e90ac790e`
in two reads eight seconds apart. `OverlayAppEnable` remained `0`. The prefix
still contains the Wine built-ins selected by this diagnostic; they were not
manually overwritten from the backup. A later ordinary Proton setup pass,
without `PROTON_USE_WINED3D`, is responsible for restoring the normal DXVK
links/files. Repeating that known-crashing path was not useful before the
ARM64EC defect is fixed.

Burnout did not start in this checkpoint. The confirmed forward blocker is
EA Desktop's internal connectivity state after successful Steam
authentication, account linking, catalog lookup, and external-action queue
handoff.

WineD3D is a diagnostic isolator, not the desired renderer. The final path
must still return to official ARM DXVK plus Turnip after the ARM64EC dispatch
defect is fixed. A focused `deja` query for the EA offline/external-action
state returned no reusable session, so no cross-session workaround was used.

## 2026-08-09: Android route visibility makes Wine report offline

A focused `deja` query for Android `/proc/net/route`, Wine IP Helper, and NLM
returned no reusable session. The next diagnosis therefore used a new,
credential-free Windows ARM64 probe in a scratch Proton prefix, not EA's live
prefix or verbose authenticated logs.

Static inspection first narrowed EADesktop's imports. It imports synchronous
`GetBestRoute2`, `GetUnicastIpAddressTable`, `FreeMibTable`, and
`GetAdaptersAddresses` from IP Helper, plus `CoCreateInstance`, and contains a
`NetworkListManager` system-connectivity checker. It does not statically import
or contain the names of the newer connectivity-hint notification APIs.

The probe is a freestanding COFF-ARM64 console executable built on the tablet
with Termux Clang, `llvm-dlltool`, and `lld-link`. It imports only Kernel32 and
Ole32; IP Helper, WinINet, and their optional entry points are resolved at
runtime. The canonical executable is:

```text
~/steam-arm64/diagnostics/network-api-probe/build/win-network-status-probe.exe
SHA-256 796e883f0398176e78073cbdc4d7c3f9f8a65544a1b0887821ef37c32c3dd101
scratch prefix version 11.0-100
```

Without a route workaround, official Proton 11 ARM64 returned:

```text
GetAdaptersAddresses flags 0       -> 50, zero adapters
GetAdaptersAddresses NLM flags 8e  -> 50, zero adapters
GetUnicastIpAddressTable           -> 0, five addresses
InternetGetConnectedState          -> false, flags 0
NLM create/query HRESULTs          -> S_OK
NLM connected / Internet           -> false / false
NLM connectivity                   -> 0x00000000
NotifyIpInterfaceChange(TRUE)      -> success, null handle, zero callbacks
NotifyUnicastIpAddressChange(TRUE) -> success, null handle, one callback
```

The complete numeric transcript is
`~/steam-arm64/diagnostics/network-api-probe/network-probe-no-route.log`,
SHA-256
`5b66195dc2e21e5cdbfdae9198e5c351cb86d3987847a7dceedc773ca8f31ccb`.
The narrow `+iphlpapi,+nsi,+netprofm` trace is
`network-probe-api-trace.log`, SHA-256
`98661bee5dbcd55727e56367c92663aee6cef794897f7a9889a759355e0b2c7f`.

The trace and Valve's Proton 11 Wine source establish the exact failure chain:

1. Android denies the Termux UID access to `/proc/net/route`; a Debian PRoot
   read also returns `Permission denied`. Netlink route dumps are denied too.
2. Wine's `ipv4_forward_enumerate_all()` returns `STATUS_NOT_SUPPORTED` when
   it cannot open that file.
3. `gateway_and_prefix_addresses_alloc()` propagates the error, so
   `GetAdaptersAddresses()` aborts with Windows error 50 even when gateways
   were not requested.
4. Proton's `netprofm` calls `GetAdaptersAddresses()` with flags `0x8e`. With
   no returned adapters, Network List Manager has no connected network and
   reports connectivity zero.

Relevant Proton 11 source:

- <https://github.com/ValveSoftware/wine/blob/proton_11.0/dlls/nsiproxy.sys/ip.c>
- <https://github.com/ValveSoftware/wine/blob/proton_11.0/dlls/iphlpapi/iphlpapi_main.c>
- <https://github.com/ValveSoftware/wine/blob/proton_11.0/dlls/netprofm/list.c>
- <https://github.com/ValveSoftware/wine/blob/proton_11.0/include/netlistmgr.idl>

The real tablet route was measured without root: `ifconfig` identified
`wlan0` at `192.168.0.215/24`, and a one-hop TTL probe received the expected
time-exceeded response from `192.168.0.1`. A standard two-row Linux route file
was generated from those values. Its SHA-256 is
`4b3a3e8bed570a9f39e2bca75b86e1023e3ecded31f4efe046469b63be53c648`.
Individual file binds at `/proc/net/route`, `/proc/self/net/route`, and
`/proc/thread-self/net/route` did not override Android's protected proc entry
through PRoot. Binding a private directory at `/proc/net` did.

With that one directory bind, the same binary and scratch prefix returned:

```text
GetAdaptersAddresses flags 0 / 8e -> 0 / 0, three adapters each
GetUnicastIpAddressTable          -> 0, five addresses
InternetGetConnectedState         -> true, flags 0x12
NLM connected / Internet          -> true / true
NLM connectivity                  -> 0x00000060 (IPv4 local + Internet)
```

The positive-control transcript is
`~/steam-arm64/diagnostics/network-api-probe/network-probe-with-route.log`,
SHA-256
`e4ce6c95207eea40e56a2a53a44edb6f83ede4bef799bec0384def10725ca28e`.
Linux DNS and HTTPS also continued working through the synthetic directory;
an `example.com` request returned HTTP 200.

`bin/prepare-proc-net-shadow.sh` now derives the Wi-Fi IPv4 address, interface,
netmask, and one-hop gateway, validates every component and subnet
relationship, and atomically writes only `route` plus an empty `ipv6_route`.
`bin/steam-arm` fails closed if the helper or files are absent and binds that
private directory at `/proc/net`. Fully explicit environment overrides remain
available for networks where the TTL probe is blocked. The tablet's automatic
discovery path produced the exact positive-control hash; local fixtures also
passed byte comparison plus off-subnet, unexpected-entry, and symlink
rejection.

This fixes the proven static Wine connectivity view. It does not fix Wine's
separate `NotifyIpInterfaceChange` stub, which still returns success without
the required initial callback. Microsoft documents that `InitialNotification`
must invoke the callback immediately:
<https://learn.microsoft.com/en-us/windows/win32/api/netioapi/nf-netioapi-notifyipinterfacechange>.
EADesktop does not statically import that function, so it is a remaining Wine
gap, not yet the demonstrated EA cause. A canonical Steam/EA retest after a
necessary launcher restart is the next boundary.

## 2026-08-09: route visibility preserved through Pressure Vessel

The launcher's outer PRoot bind made the route shadow visible before Proton,
but the official runtime then invoked Bubblewrap with `--proc /proc`. That
mount covered the outer `/proc/net` directory. Re-injecting the directory after
`--proc` exposed a second PRoot defect: emulated runtime mounts canonicalized
the final `/proc/net` symlink to `/proc/<bubblewrap-pid>/net`. The sandbox child
has a different PID and therefore did not see the new binding.

`patches/proot-runtime-directory-bind-target.patch` changes only this mount
case. `guest_canonicalize()` now takes an explicit final-component policy;
`emulate_mount()` uses `lstat()` on the translated source and does not
dereference the target's final component when the source is a directory.
Pivot and unmount handling retain their previous dereferencing behavior. This
matches PRoot's startup-bind semantics without preserving arbitrary covered
mounts across a pivot.

`diagnostics/pressure-vessel-route-bwrap.c` handles the other half of the
boundary. It reads Pressure Vessel's NUL-delimited `--args` file, locates the
end of the final `--proc /proc` pair, and inserts:

```text
--ro-bind-fd <validated-directory-fd> /proc/net
```

The wrapper opens the shadow with `O_NOFOLLOW | O_DIRECTORY`, requires a
private current-user-owned directory, accepts exactly regular `route` and
`ipv6_route` files with safe modes and bounded sizes, keeps the directory FD
across `exec`, and closes the superseded argument-stream FD. Ordinary feature
checks and invocations without `--args` pass through unchanged. Tests cover
both `--args FD` and `--args=FD` spellings, insertion before the payload
terminator, unsafe modes, unexpected entries, and ordinary argv passthrough.

The real lifecycle regression used the isolated candidate PRoot and the exact
installed ARM64 `srt-bwrap`. The sandbox payload could no longer access the
source FD but still read the expected route marker from `/proc/net`, proving
that the directory bind survives descriptor closure and the child PID change.
The candidate and an independent reproduction build were byte-identical:

```text
PRoot SHA-256 0378e0631dbf7a8bd0061b54fc167bb881c70a76109f567b682f7262a063166c
```

The first complete Runtime/Proton probe used a new empty compatibility prefix
and returned Windows error 2 with zero adapters. That was not a route-binding
failure: the prefix was still running `wineboot --init` and lacked `version`,
`config_info`, and `tracked_files`. Proton Wine opens `\\.\Nsi` before its
adapter and unicast enumeration; the uninitialized device state made every NSI
table unavailable.

A second isolated run copied an already initialized, credential-free Proton 11
ARM64 probe prefix, verified those three seed files, and used the candidate
PRoot plus hardened FD wrapper through official Steam Linux Runtime 4 ARM64 and
official Proton 11 ARM64. It completed before its 600-second guard with:

```text
/proc/net/route SHA-256             4b3a3e8bed570a9f39e2bca75b86e1023e3ecded31f4efe046469b63be53c648
GetAdaptersAddresses flags 0 / 8e   0 / 0, three adapters each
GetUnicastIpAddressTable            0, five rows
InternetGetConnectedState           true, flags 0x00000012
NLM Internet / Connected            true / true
NLM connectivity                    0x00000060
probe exit                           0
```

The stable transcript is:

```text
~/steam-arm64/diagnostics/network-api-probe/nested-runtime-candidate-seeded-20260809-073001/nested-runtime-network-probe.log
SHA-256 8418407443327be9894a1c5549886e4a86e5064a956894531997b43ceda28862
```

All guarded probe processes exited, and exact checks for the fake App ID,
scratch root, probe executable, and candidate PRoot found no residue. A focused
`deja` search returned no matching prior implementation, so no recalled fix was
reused.

The build now records `proot_sha256` only after a successful compile. Existing
build reuse, project-file installation, and launcher startup all fail closed if
the executable does not match that stamp. Legacy production stamps without the
hash are intentionally rejected, requiring a fresh verified build instead of
an in-place source mutation.

Nothing in this checkpoint has yet replaced the live production PRoot or
restarted Steam. The next boundary is a backed-up, controlled deployment,
graceful Steam restart, and canonical WineD3D EA retest. The live Burnout
launch options intentionally still contain `PROTON_USE_WINED3D=1` and
`PRESSURE_VESSEL_REMOVE_GAME_OVERLAY=1`; they must not be treated as the final
renderer configuration. Burnout has not started, and the separate official
DXVK ARM64EC dispatch fault remains open.

## 2026-08-09: route-preservation fix deployed to production

The validated implementation was committed as `1ebd14f`. Its test harness
then received a native Termux fallback: `a12d9f4` retains the owning argument
file object and uses `TemporaryFile` when `os.memfd_create` is unavailable.
Commit `a1d8f61` makes the C wrapper honor Termux's `TMPDIR` when it creates its
replacement argument stream. A focused `deja` query for the Termux
`TMPDIR`/Bubblewrap wrapper case returned no indexed match, so no prior-session
implementation was reused.

Steam was stopped through its own shutdown path before production files were
changed. The old outer PRoot PID 28801 and Steam PID 28808 both exited. The
pre-deployment state and the two guarded installer passes are preserved at:

```text
/data/data/com.termux/files/home/steam-arm64/backups/20260809-before-pressure-vessel-route-deploy.zCJzqG
/data/data/com.termux/files/home/steam-arm64/backups/repo-install-20260809-074455
/data/data/com.termux/files/home/steam-arm64/backups/repo-install-20260809-075057
```

The previous production source tree was retained, not deleted, at:

```text
/data/data/com.termux/files/home/steam-arm64/src/proot-production-old-ba3282b-20260809
```

The freshly built and stamped tree was promoted to
`~/steam-arm64/src/proot-production`. The live executable and installed route
wrapper match the validated artifacts exactly:

```text
production PRoot SHA-256  0378e0631dbf7a8bd0061b54fc167bb881c70a76109f567b682f7262a063166c
route wrapper SHA-256     6ba0a5f0ed955439efb220ea64d267b96cc3f6a1e7ee390f17be175990c39f7a
```

Steam restarted successfully under outer PRoot PID 13620 and Steam PID 13625.
Live environment inspection recorded the complete route-injection chain:

```text
PRESSURE_VESSEL_BWRAP=/data/data/com.termux/files/home/steam-arm64/compat-bin/steam-arm64-bwrap-route
STEAM_ARM64_REAL_BWRAP=/data/data/com.termux/files/home/steam-arm64/runtime/SteamLinuxRuntime_4-arm64/pressure-vessel/libexec/steam-runtime-tools-0/srt-bwrap
STEAM_ARM64_PROC_NET=/data/data/com.termux/files/home/steam-arm64/config/proc-net
```

At 14:46:33, the new session registered
`steamlinuxruntime_4_arm64_official` and `proton_11_arm64_official` and retained
Burnout App ID 1238080's explicit priority-250 mapping to
`proton_11_arm64_official`. The live outcomes after the compatibility scan are
recorded in the following checkpoint.

## 2026-08-09: live EA route breakthrough and Burnout pre-render stall

Steam's second cache-off pass completed at 15:15:49:

```text
Recording non-user mapping for 1238080 at priority 100 to tool proton-experimental
Skip mapping AppID 1238080 to tool "proton-experimental" with priority 100:
  mapping to tool "proton_11_arm64_official" with priority 250 already exists.
CCacheOffSteamPlayStateJob 9249030437168336014 complete
```

The next real launch used the intended artifacts throughout:

```text
SteamLinuxRuntime_4-arm64/_v2-entry-point --verb=waitforexitandrun
Proton 11.0 (ARM64)/proton waitforexitandrun
link2ea://launchgame/1238080?platform=steam&theme=bprm
```

It did not reference conventional Proton Experimental or the x86-64 Runtime 4.
The still-active launch options were intentionally diagnostic:

```text
PROTON_USE_WINED3D=1 PRESSURE_VESSEL_REMOVE_GAME_OVERLAY=1 %command%
```

The production route fix cleared the previous EA offline state. EA logged HTTP
successes, entered its online application state, authenticated through Steam,
linked the account, found the Burnout offer, accepted the external launch
action, connected its local service, and reported Link2EA launch success.
Strings naming `offlineAwaitingAuth` were state-machine definitions; the live
transition count was zero. The visible EA frontend nevertheless showed a
network-load error after its SPA load stalled. CEF subsequently logged frame
connection timeouts, a network-service crash/restart, renderer termination as
`PROCESS_CRASHED`, aborted page loads, and repeated GPU-process failures. At the
same time, the background service remained network-online, maintained websocket
traffic, and received later HTTP 200 replies. No certificate, SSL, or TLS error
was logged. The best-supported classification is a CEF renderer/GPU and IPC
starvation failure, not failure of the preserved network route.

`BurnoutPR.exe --reactivate` then appeared for the first time. Process mappings
proved Proton's bundled ARM64 WoW64/FEX path through
`aarch64-windows/libwow64fex.dll`. EA reported the game running and
`FirstPartyLoaderReady`, but X11 never acquired a managed Burnout gameplay
window. The sampled Burnout processes remained in activation/protected startup:
`Core/Activation.dll` and the EA activation/IGO logs were open, while no movie
asset or game `d3d9`, `d3d11`, or WineD3D renderer module was mapped. This does
not support a `-skipvideos` change yet.

The later FEX-hosted Burnout process produced 59,989 repeated signal-7/SIGBUS
records in `[anon:FEXMemJIT]` in the Steam session log and consumed enough CPU
to make Steam and touch input unresponsive. These records are handled guest
fault traffic, not 59,989 process crashes: both Burnout processes and affected
EA/CEF components continued running after many such records. Steam subsequently
asserted that its main loop had stalled for more than 15 seconds and exited on:

```text
src/common/pipes.cpp (900) : fatal stalled cross-thread pipe.
```

The gameprocess log did not receive a normal tracked-process removal for this
final attempt. The game container supervisor was sent standard `SIGTERM`; all
Burnout, EA, Wine, Steam, and outer-PRoot processes were subsequently absent,
but the logs do not identify the exact initiator of the whole-session exit. No
`SIGKILL` was used, and no game, prefix, credential, Mesa, or Steam data was
deleted. A full-resolution post-teardown screenshot had SHA-256
`00010e0eef41c19f56e5dd0194fa68ad2ab1b2d3bb53c6a1dcad9486dc2dba91`
and showed the intact KDE desktop with no Steam, EA, or Burnout surface.

This checkpoint proves the official ARM64 runtime/Proton/FEX launch path and
the live EA network route. It does **not** prove rendered gameplay or the final
DXVK/Turnip path. A focused `deja` query for this exact EA CEF/FEX failure found
no independent prior-session match, so no recalled implementation was reused.

## 2026-08-09: PRoot crash tracing made opt-in

The signal flood exposed an incorrect launcher assumption. `bin/steam-arm`
previously forced `PROOT_CRASH_LOG=1` with this comment:

```text
This is diagnostic only and has no effect unless a translated process fails.
```

That is false for FEX. Valve's pinned Proton 11 ARM64 FEX source names its JIT
mapping `FEXMemJIT` and installs a handler that attempts to emulate unaligned
atomic accesses on SIGBUS. Valve's pinned ARM64 Wine maps native SIGBUS to the
normal Windows `EXCEPTION_DATATYPE_MISALIGNMENT` exception path. The observed
processes continued running after hundreds or tens of thousands of these
events, matching handled guest-fault traffic rather than fatal exits.

Primary sources for the exact pinned code are:

- FEX JIT mapping name: <https://github.com/FEX-Emu/FEX/blob/a04b0241c2fe3911729842205cd8643981108aad/FEXCore/Source/Interface/Core/CPUBackend.cpp#L351-L368>
- FEX WoW64 SIGBUS recovery: <https://github.com/FEX-Emu/FEX/blob/a04b0241c2fe3911729842205cd8643981108aad/Source/Windows/WOW64/Module.cpp#L919-L935>
- FEX handled/unhandled atomic path: <https://github.com/FEX-Emu/FEX/blob/a04b0241c2fe3911729842205cd8643981108aad/FEXCore/Source/Utils/ArchHelpers/Arm64.cpp#L1900-L1925>
- Valve Wine ARM64 SIGBUS handler: <https://github.com/ValveSoftware/wine/blob/81d78e4f3ea8ce868d775021fdc9f90122dc1a6b/dlls/ntdll/unix/signal_arm64.c#L1168-L1178>

The PRoot diagnostic path is particularly expensive: for every selected signal
stop it fetches registers, reads the process command line, opens the process
maps, and scans for the instruction-pointer mapping before writing three log
records. The prior launcher also offered no effective off switch because PRoot
tests only whether `PROOT_CRASH_LOG` exists; even a value of `0` enabled it.

The production launcher no longer defines the variable by default. Explicit
`PROOT_CRASH_LOG=1 ~/bin/steam-arm` still enables the unchanged PRoot tracer for
a bounded diagnostic. The specialized direct Link2EA diagnostic script retains
its explicit setting. A focused `deja` query found no independent prior-session
implementation for this logger/default issue, so no recalled fix was reused.

The next safe discriminator is one bounded launch with Valve's supported
`PROTON_LOG=1` and a new private `PROTON_LOG_DIR`, with external file-size,
free-space, PID-progress, and timeout guards. Do not change FEX TSO or kernel
settings based only on the handled signal count.

## 2026-08-09: EA license succeeds; Burnout exposes the FEX CPUID blocker

Steam was restarted once after the crash-tracing correction and was then left
running. The fresh compatibility job `7250488763318918964` completed at
16:49:55. It posted callbacks for App IDs 4185400, 4628740, and 1238080 and
again rejected the lower-priority automatic Proton Experimental mapping. The
next launch used only `SteamLinuxRuntime_4-arm64`, Proton 11.0 (ARM64), and the
expected Link2EA target. The installed Proton appmanifest recorded build ID
`23303086` and a complete 3,596,743,348-byte depot.

The launch ran without `PROOT_CRASH_LOG`. No crash-dump flood occurred, log
files remained below 25 MiB, Steam stayed responsive, and Burnout eventually
settled sleeping instead of pegging the tablet. This confirms that making the
tracer opt-in removed the earlier instrumentation-amplified CPU stall without
changing the game result.

EA's visible CEF window displayed:

```text
Couldn't connect to servers
We ran into a problem, but a quick restart should fix it.
```

Its background state independently remained online and authenticated. The EA
logs recorded Steam external authentication, content readiness, Link2EA launch
success, and `isGameRunning:true`. `BurnoutPR.exe` requested its license at
17:10:37.280, and EA returned `RequestLicenseResponse` at 17:10:37.520. The
cached activation signature was valid. Therefore the visible EA error is a CEF
renderer/network-service failure, not a failure of the preserved network route,
Steam-to-EA authentication, or game licensing. The exact EA screenshot had
SHA-256
`b7f2ab444e23298325c813990171852232b849259f5741bcd840cedd1f2b4529`.

Burnout then created a 315x102 X11 dialog titled `CPU Error` with the exact text:

```text
This machine does not support the SSE2 Command Set which is required to run this game.
The game will now terminate
```

The exact dialog screenshot had SHA-256
`711a3b07ce6721512ac5acaf5de580b956d29ce4127356d12d655586b2dc18ed`.
The running process mapped Proton's bundled `libwow64fex.dll` and
`[anon:FEXMemJIT]`, making this a guest CPU-compatibility check reached through
the intended official ARM64 Proton/FEX path. There was no gameplay window.

Cleanup used the dialog's own exit path. Immediately before interaction, X11
reported exactly one visible window titled `CPU Error`, owned by Burnout PID
15946, class `steam_app_1238080`, with the observed 315x102 geometry. Its
centered **OK** button was clicked using window-relative coordinates. Steam then
logged removal of every App ID 1238080 tracked process at 17:34:12, recorded the
outer launcher's exit code as zero, and removed the game from its running list.
No process signal was used. Steam PID 31776 remained alive. The post-dismiss
screenshot had SHA-256
`96c940836b64bc158b8e83ac7da714ec67b7ce64a1a29ad2cc3e216bbfb5d6ea`
and showed the intact Steam/KDE desktop with only EA's CEF network-error window
remaining.

Upstream source and issue history identify the exact cause:

- Proton commit `0745bfbc4cf4365e8cf048b003990c59def29948` pins FEX commit
  `a04b0241c2fe3911729842205cd8643981108aad`.
- That FEX revision already advertises real SSE2 in CPUID leaf 1 EDX bit 26 and
  through Wine's Win32 processor-feature path.
- Burnout and Burnout Remastered incorrectly use CPUID leaf 1 EDX bit 2,
  Debugging Extensions, as their SSE2 gate.
- FEX issue [#5805](https://github.com/FEX-Emu/FEX/issues/5805) reproduces the
  same dialog. Merged fix
  [`9365e624`](https://github.com/FEX-Emu/FEX/commit/9365e6240b3b87466753cd989d257e5c93092578)
  adds the legacy DE/PSE/1-GiB-page bits expected by these games; pull request
  [#5807](https://github.com/FEX-Emu/FEX/pull/5807) carries the rationale.
- Proton's generated per-game FEX configuration only controls TSO,
  multiblocking, and logging; it has no supported CPUID feature-mask field.

Consequently there is no launch-option, TSO, kernel, or host-CPU-mask remedy.
The production-safe next step is an official Proton 11 ARM64 build whose bundled
FEX contains `9365e624` or later. The installed App ID 4628740 payload was not
modified. A private copied compatibility tool could prove the fix sooner, but
would be explicitly non-official and must never overwrite Steam's managed
depot.

The source-only `diagnostics/cpuid-probe` records the relevant raw CPUID and
Win32 checks for future validation. A standalone Proton attempt reached the
ARM64EC FEX loader but aborted in Proton's injected `steamclient` initialization
before the probe entry point, so no result from that attempt is treated as
evidence. A focused `deja` query found no independent prior-session workaround;
no recalled implementation was reused.

This checkpoint still uses `PROTON_USE_WINED3D=1` for isolation. It proves the
EA route, authentication, license response, and exact FEX CPUID blocker. It does
**not** prove gameplay, DXVK, or Turnip rendering, and it does not resolve the
separate official DXVK ARM64EC dispatch fault.

## 2026-08-09: Superflight proves DXVK/Turnip and working Pulse audio

Superflight's installed manifest identifies App ID 732430. Steam first mapped
it to conventional Proton Experimental, reproducing the known x86-64 Runtime 4
loader failure before Proton. The mapping was then replaced with this explicit
entry at priority 250:

```text
732430 -> proton_11_arm64_official
```

The corrected launch used only the intended paths:

```text
SteamLinuxRuntime_4-arm64/_v2-entry-point --verb=waitforexitandrun
Proton 11.0 (ARM64)/proton waitforexitandrun
SuperFlight/superflight.exe
```

The tracked session ran from 01:40:01 through 01:46:25 UTC on 2026-08-10.
Unity's `output_log.txt` proves a real graphics device rather than a registry or
process-only milestone:

```text
Initialize engine version: 2017.2.0f3
Direct3D: Version: Direct3D 11.0 [level 11.1]
Renderer: Turnip Adreno (TM) 730
VRAM: 5469 MB
```

The game rendered through official Proton 11 ARM64's DXVK and the private
Turnip stack. Superflight is therefore the first conventional Windows game in
this project confirmed on the DXVK/Turnip path. This result is independent of
Burnout's ARM64EC `d3d11.dll` and FEX CPUID blockers.

Audio did not work. Inspection while the game was live established the complete
failure chain:

- `PULSE_SERVER` was absent from the game environment;
- no Superflight PulseAudio client or sink input appeared;
- the prefix recorded only `Software\\Wine\\Drivers\\winealsa.drv` and no
  MMDevice render or capture endpoint;
- Wine's ALSA fallback reported `cannot find card '0'` and
  `Unknown PCM default` twice.

The ARM64 `winepulse.drv` and `winepulse.so` payloads are installed. The audio
server is also healthy: read-only `pactl info` checks against
`tcp:127.0.0.1:4713` succeeded from native Termux and Debian PRoot and reported
the Termux `OpenSL_ES_sink`. The missing game environment variable, not absent
Wine drivers, a dead Pulse server, or an Android ALSA device, is the confirmed
cause of this run's silence.

Before changing Steam's per-game configuration, the 295,280-byte live file was
copied and byte-verified at:

```text
~/steam-arm64/backups/localconfig.vdf.before-superflight-pulse-edit-20260809-1924
```

With Steam offline, the only staged full-file difference in
`~/steam-arm64/client/userdata/10546184/config/localconfig.vdf` was initially a
new App ID 732430 `LaunchOptions` block containing:

```text
PULSE_SERVER=tcp:127.0.0.1:4713 %command%
```

The staged file's SHA-256 before Steam normalization was
`6ab1317f49d1733ea1a4eb6aeb5ea0c23c20f4f0f41099c907389a7cffd807ca`.
That block was placed under the one-tab top-level `apps` section, not Steam's
four-tab `Software/Valve/Steam/apps` hierarchy. Steam retained but ignored it.
The resulting discriminator launch at 02:59 still started without the explicit
prefix, and its wrapper children inherited only the launcher's older
`PULSE_SERVER=127.0.0.1` value. This disproved the assumed VDF placement before
any audio success was claimed.

Steam restarted cleanly in
`~/steam-arm64/logs/steam-20260809-192748.log`. Both official ARM64 tools
registered at 02:27:55 UTC on 2026-08-10. The first historical-tool pass ran
from 02:28:23 through 02:48:07, mappings were processed, and the second pass
began at 02:49:03. The queued Superflight discriminator delayed but did not
break that worker. The job completed at 03:07:58, released the ARM tool and
App ID 732430 callbacks, and did not restart.

Once the full Steam UI rendered, Superflight's normal Properties page showed
an empty Launch Options field. Entering the same string through that supported
UI wrote it inside the real six-tab App ID 732430 block under
`Software/Valve/Steam/apps`. The inert top-level duplicate remains for removal
at a future clean shutdown; it is not consulted for launch options.

The next launch started session `6b66ff24a201c73b` at 03:16:14. Steam's tracked
command begins with the exact assignment:

```text
PULSE_SERVER=tcp:127.0.0.1:4713 steam-launch-wrapper ...
```

Every child after the assignment shell inherited the full URI. Live Unity PID
32705 had the same `PULSE_SERVER`, mapped `winepulse.so`, `winepulse.drv`, and
`libpulse`, and exposed the visible `SUPERFLIGHT` window. Pulse client 148
(`wine-preloader`) owned sink input 23 at stereo 48 kHz, while Termux's
`OpenSL_ES_sink` was `RUNNING` at stereo 44.1 kHz. Repeated samples preserved
that chain, and neither the Steam session log nor Unity's `output_log.txt`
contained an audio failure. This proves the game is producing an end-to-end
Wine-to-Pulse-to-Android OpenSL audio stream.

The live main-menu screenshot was captured and inspected at local path
`/tmp/superflight-pulse-live.png`, SHA-256
`e274a8762b4180591f19ed75b9a9abb229d0730dfb592654c59223b57e253d95`.

Repository checkpoint `69d18a6` independently replaces the launcher's repeated
Pulse module loads with a tested, idempotent preflight and exports the canonical
`tcp:127.0.0.1:4713` URI. It is pushed but has not been deployed to the tablet;
the current Steam session still uses the prior deployed launcher. The confirmed
audio stream comes from the per-game option and validates the canonical endpoint,
not the new launcher helper in production. That repository checkpoint remains
prepared for a controlled future deployment.

The required `deja "Superflight Termux Proton ARM64 PulseAudio ALSA
PULSE_SERVER"` query returned no matches. No cross-session solution or wording
was reused for this checkpoint.

## 2026-08-10: keyboard-resize incident and bounded session logging

An apparent Termux:X11 freeze after the Superflight audio run was not CPU or
storage exhaustion. Android's on-screen keyboard had resized X display `:0`
from the previously observed 2800x1586 desktop to 2800x876. `xdpyinfo`,
`xrandr`, and `xdotool` still completed, the eight CPUs were reported as 800%
idle, and the filesystem retained 25 GiB free. SSH cannot dismiss the Android
IME without the platform's input-injection permission, so the safe recovery is
the tablet's keyboard-hide/down control; restarting X11 is unnecessary.

The audit did find residue from the separate 03:16 Superflight session. Its
Pressure Vessel path spent roughly two hours in PRoot metadata work and emitted
12,320 `Invalid cross-device link` hard-link warnings plus 18,481
`pressure-vessel-wrap` lines before `pv-adverb: wait: Function not implemented`
and `Real-time signal 1`. The game and native Steam were already gone. Nine
sleeping App ID 732430 Wine/route processes were revalidated through their
environments and stopped with `SIGTERM`; no force signal was used and X11/KDE
were left running.

Five uncited outer wrapper logs were byte-verified as a short prefix followed by
an already preserved canonical session log. Removing only those redundant
copies recovered 115,801,781 bytes and reduced `~/steam-arm64/logs` from about
761 MiB to 651 MiB. Two documented 164 MiB wrapper/canonical files were retained,
as were every game, compatdata, credential, and normal Steam log. The known CEF
paths remained exact `/dev/null` symlinks, no deleted file was held open, and a
12-second sample showed no ongoing scoped log growth.

Repository prevention now replaces the launcher's unbounded `tee` with
`steam-arm64-session-guard.py`. The guard creates collision-safe mode-600 log
files, caps the canonical log at 64 MiB and mirrored stdout at 1 MiB, writes a
visible marker inside each cap, and continues reading all remaining child output.
With Bash `pipefail`, Steam's exit status remains the pipeline status even if
stdout closes. Preflight requires a 1 GiB free-space floor plus the session-log
budget. It treats only an exact `/dev/null` symlink as a valid CEF guard; an
incorrect path fails unchanged while Steam is running, and only missing or
closed regular files can be replaced while stopped. `PROOT_CRASH_LOG` accepts
only unset/`0`/`1`, actively removes disabled values from the outer environment,
and the direct EA diagnostic route no longer enables it unconditionally.

Syntax checks, ShellCheck, Python compilation, the PulseAudio and Pressure
Vessel regression suites, and the new guard tests all pass. The new tests prove
free-space rejection before CEF mutation, all accepted/refused CEF states,
continued drain with capped or closed stdout, child status 23 propagation, and
24 concurrent unique session-log creations. The required `deja "Termux X11
Steam CPU pegged disk full giant logs steamwebhelper cleanup prevention"` query
returned no matches, so no prior-session implementation was reused.

## 2026-08-10: Superflight low-resolution fullscreen performance profile

After the first audio-confirmed run, the apparent UI freeze was cleared by a
user-controlled KDE stop/start. X display `:0` returned to 2800x1586 at 120 Hz,
the machine was idle, and 25 GiB remained free. Superflight's saved Unity
PlayerPrefs explained its avoidable rendering cost: the keyboard-resized run
had left a 2800x876 target together with 4x antialiasing, motion blur,
post-processing, 4000-unit shadows, and enabled shadow quality. Unity's global
quality index was already zero.

With Steam and Wine stopped, the original `user.reg` was byte-verified and
preserved at:

```text
~/steam-arm64/backups/20260810-before-superflight-performance.fd0S7o/user.reg
```

An atomic replacement changed exactly eight Superflight DWORDs: windowed
1280x720, zero antialiasing, motion blur, post-processing, shadow distance, and
shadow quality. No other prefix registry value changed. The user then completed
a run and reported that it played much better and that audio worked well. This
is direct play feedback, not an instrumented FPS claim.

The live window was an exact 1280x720 at X=760/Y=446. Its post-run screenshot,
`~/steam-arm64/superflight-performance-window.png`, has SHA-256
`f6ab8b4b669b4d60ed0f035213be994f7fa9ce72ff2fe8313a76b4774ab65331`.
At the visible crash-result menu, Unity's standard Alt+Enter toggle expanded the
window to 2800x1586 while preserving the saved 1280x720 internal resolution and
all disabled effects. The full-screen screenshot has SHA-256
`bda0aaf106f94e6b331044a5150d6d497c51dd8ab1f06408409e13b6958e7acb`;
it shows correct aspect scaling without cropping.

Live process and file evidence preserves the intended stack. Unity reports
Direct3D 11.0 level 11.1 and `Turnip Adreno (TM) 730` with 5469 MiB VRAM. The
prefix `d3d11.dll` and `dxgi.dll` hashes exactly match the official Proton 11
ARM64 files under `files/lib/wine/dxvk/aarch64-windows`. The game maps
`libarm64ecfex.dll`, Wine Vulkan, private `libvulkan_freedreno.so`, Wine Pulse,
and the Turnip shader cache. Pulse's `OpenSL_ES_sink` was `RUNNING`, unmuted at
100%, with sink input 2 owned by `superflight.exe` PID 15964 at stereo 48 kHz.
The bounded Steam session log was only 5,541,850 bytes during this check.

The required `deja "Superflight small window fullscreen FSR Proton ARM64
Termux X11"` query returned no matches. No recalled implementation was reused;
the fullscreen choice was validated against the installed Proton payload and
the live window rather than assuming an unsupported FSR variable.

The full-screen window advertises `_NET_WM_BYPASS_COMPOSITOR=1`; KWin consumed
zero CPU in repeated samples, so disabling the compositor cannot explain or
improve the remaining frame rate. KGSL reported roughly 18--36% GPU busy at the
minimum 220 MHz GPU frequency, while `superflight.exe` consumed about 157% CPU
and the outer PRoot about 48%. This identifies a CPU/translation limit rather
than a Turnip fill-rate limit.

Every hot Superflight thread, including the main thread, Unity workers,
`UnityGfxDeviceW`, and DXVK submit/queue threads, had affinity `0-3`. Those are
the Snapdragon's four 1.785 GHz efficiency CPUs, each reported with scheduler
capacity 261. The game-local mask was not imposed by Android's foreground
cpuset, PRoot, Steam, Wine server, or Proton's generated FEX configuration:
parents allowed CPUs 0-7 and `proton-fex-config.json` had an empty `Config`.

A reversible live A/B applied `taskset -apc 4-7` only to Superflight PID 15964.
All 72 existing threads were verified at mask `4-7`; future threads inherit the
same mask. CPUs 4-6 have capacity 805 and a 2.496 GHz maximum, while CPU 7 has
capacity 1024 and a 2.995 GHz maximum. In the same menu scene, game CPU fell
from about 157% to 97%, big cores reached 1.65--1.88 GHz, and GPU busy rose from
about 32% to 36%. The user then completed another live feel test and reported
that it was faster. The original `0-3` mask remains the immediate rollback.

The installed Proton 11 ARM64 Wine `ntdll.so` contains support for
`WINE_CPU_TOPOLOGY`. Valve's documented syntax uses `count:host-cpu-list`, so
`WINE_CPU_TOPOLOGY=4:4,5,6,7` is the production candidate for persisting this
mapping in Superflight's launch options. It has not yet been claimed as a
confirmed fix: the current improvement comes from the live `taskset` A/B, and
the environment form still requires a clean next-launch validation.

### Reproducibility automation and validation

`scripts/configure-superflight-performance.py` turns the confirmed Unity
PlayerPrefs values into a fail-closed, idempotent operation. It accepts only one
exact Superflight registry section (including Wine's optional numeric section
timestamp) and exactly one DWORD for each of the nine settings: fullscreen,
1280x720, Unity quality zero, and disabled antialiasing, motion blur,
post-processing, shadow distance, and shadow quality. It refuses symlinks,
non-regular files, unexpected hard links, missing or duplicate values, and any
write while Steam, Wine, or the game is active. A change creates a unique
mode-700 backup directory, byte-verifies the copied `user.reg`, writes and
`fsync`s a same-directory mode-preserving temporary file, atomically replaces
the original, and `fsync`s its directory. An already-current profile creates no
backup. Read-only `--check` is safe during a game.

`scripts/set-superflight-affinity.py` makes the live A/B repeatable without a
PID guess. It requires exactly one `superflight.exe`, mandatory
`STEAM_COMPAT_APP_ID=732430`, no conflicting optional Steam IDs, the exact App
ID compatdata suffix, CPU IDs 0-7, and a measured higher-capacity CPU 4-7
cluster. It applies `taskset -apc 4-7` and then rejects any readable thread that
did not acquire that mask. Its read-only `--check` mode reports drift.

Both uncommitted tools were streamed over SSH and executed read-only against the
still-running tablet session. The settings check reported current registry
SHA-256 `78379083f691d00b5f9a45a8129fa2ed40294cc8b6426784fdad17e3c105155d`.
The affinity check independently resolved PID 15964 and reported all 72 threads
at `4-7`. At the same checkpoint, the filesystem retained 25 GiB free,
`~/steam-arm64/logs` used 656 MiB, and client logs used 13 MiB.

A final bounded X capture completed in 6.8 seconds at 09:01 local time. The
2800x1586 PNG has SHA-256
`497a6571e948b9992dcddb5b09414cbb81c3931d08f55f04195bcb780a5c2ada`.
Visual inspection shows Superflight's live 3D crash/menu scene covering the
desktop without a window border, keyboard resize, dialog, or rendering
corruption. This is final visual confirmation of the fullscreen state; it is
not by itself an FPS measurement.

The repository-wide validation matrix for this checkpoint is:

- Python compilation passed for all eight Python entry points and tests;
- Bash syntax parsing passed for all 16 shell entry points;
- ShellCheck's warning/error gate passed all 16 shell files; its unrestricted
  mode reported only seven existing informational SC2009/SC2016 notes;
- all five retained Python suites passed: settings, affinity, PulseAudio,
  Pressure Vessel route wrapper, and bounded session logging;
- `git diff --check` passed;
- `diagnostics/pressure-vessel-route-bwrap.c`, `probes/fd-holder.c`, and
  `probes/robust-list.c` all compiled with
  `-std=c11 -O2 -Wall -Wextra -Werror` into inspected temporary ELF files;
- the unchanged Windows ARM64 network probe was not rebuilt on this workstation
  because its declared Clang/LLVM cross-toolchain is absent. Its earlier tablet
  candidate and independent reproduction build remain byte-identical as logged
  in the 2026-08-09 route-probe section; no new claim is based on a skipped
  build.

The strict native compilation found one latent `-Wformat-truncation` failure in
`probes/fd-holder.c`. The probe now calls `readlinkat()` relative to its already
open `/proc/<pid>/fd` directory instead of concatenating the directory and
entry name into a fixed `PATH_MAX` buffer. This removes the truncation path and
the corrected probe passes the strict compile gate. The required
`deja "steamclienttermux fd-holder.c format-truncation PATH_MAX compile Werror"`
query returned no matches, so no prior-session implementation was reused.

The required `deja "Superflight fullscreen frame rate DXVK Turnip FEX KWin
compositor Termux X11"` query returned no matches. No prior-session affinity
implementation was reused.

## 2026-08-10: removable Windows-game library

The tablet's removable card is visible to native Termux at
`~/storage/external-1`, resolving to the app-specific directory
`/storage/7376-B000/Android/data/com.termux/files`. It has 606 GiB free. Android
mounts the underlying 924 GiB exFAT card through FUSE with `noexec` and
`symlink=0`; the live Steam PRoot initially had no bind exposing it. Steam knew
only the internal client root in `steamapps/libraryfolders.vdf`.

A disposable live probe used the production patched PRoot with an external
library bind followed by a nested internal compatdata bind. The library and
`steamapps/common` reported FUSE, while `steamapps/compatdata` reported F2FS.
External symlink creation failed as expected, executing a copied native ELF
returned 126, and a symlink inside the overlaid compatdata succeeded. Host-side
markers proved bulk data reached the card and prefix data reached internal
storage. All uniquely named probe directories were removed afterward.

The opt-in `steam-arm64-removable-library.py` helper now prepares and validates:

```text
external depot: /storage/7376-B000/Android/data/com.termux/files/steam-arm64-library
guest path:     ~/steam-arm64/removable-library
control root:   ~/steam-arm64/removable-library-steamapps
compatdata:     ~/steam-arm64/removable-library-compatdata
download state: ~/steam-arm64/removable-library-downloads
configuration:  ~/steam-arm64/config/removable-library.json
```

It accepts only Termux's exact `/storage/UUID/Android/data/com.termux/files`
boundary, mode-protects and atomically writes its configuration, backs up a
changed configuration, requires empty mountpoints so data cannot be hidden,
requires at least 1 GiB free, and fails if the card disappears. The launcher
binds the external root first, covers `steamapps` with internal control metadata,
binds only `common` back to the card, then overlays unique internal compatdata
and active downloads. Linux executables, Proton, runtimes, prefixes, and native
games remain internal; this route is limited to Windows depot payloads.

The helper's offline `register` action adds the stable guest path to
`client/steamapps/libraryfolders.vdf`. It refuses the edit while Steam or Wine
is active, rejects non-regular and multiply linked VDFs, preserves the source
newline style and mode, makes a byte-verified timestamped backup, detects a
concurrent source change, installs with an atomic rename, and is idempotent.

The initial tablet layout was prepared while the old Steam launcher remained
running. After a graceful shutdown, the offline registration added guest entry
1 with label `microSD Windows games`; its timestamped backup has the exact
pre-edit SHA. Steam retained the entry on restart, measured 991,757,860,864
bytes, and logged two library folders.

Kingsway is the first planned end-to-end validation target: App ID 588950,
Windows-only depot 588951, approximately 45.67 MiB downloaded and 57.53 MiB on
disk. The required `deja "Kingsway Steam Proton Termux ARM64 FEX microSD"`
query returned no matches, so no prior-session implementation was reused.

The first install correctly selected the removable library and fetched depot
588951's manifest, but stopped before downloading payload bytes. Native Termux
reproduced the exact blocker: `flock` succeeds on internal F2FS and returns
`ENOSYS` on the card's Android FUSE mount. Steam consequently reported `Failed
to write patch state file (Disk write failure)` for
`steamapps/downloading/state_588950_588951.patch`. The mount design therefore
keeps the active `steamapps/downloading` tree on internal F2FS as a second
nested bind, alongside compatdata, while the installed Windows payload and
appmanifest remain external.

The required `deja "Steam removable library flock errno 38 FUSE Android state
patch disk write failure"` query returned no matches, so no prior-session fix
was reused.

The failed zero-byte staging skeleton was preserved at
`steamapps/downloading.pre-internal-f2fs-20260810-1013`, copied to the new
internal staging root, and verified by relative tree and file SHA before the
new empty external mountpoint was exposed. With the nested bind active, Steam
wrote a valid patch-state file, downloaded 47,883,776 bytes, staged 60,322,784
bytes internally, and committed across the bind into the card. The final
external manifest reports `StateFlags 4`, BuildID 7833329, and 60,322,784 bytes
on disk; the internal staging tree drained to zero files. `content_log.txt`
records `Fully Installed` and scheduler result `No Error` for App ID 588950.

On the next startup Steam logged `Loaded 0 apps` for the external library and
reset Kingsway to update-required even though all payload files remained on the
card. Selecting the same SD library completed a second verification/install
without error. This isolates the remaining FUSE limitation to Steam's lockable
control metadata, including `appmanifest_588950.acf`, rather than game payloads.
The final layout therefore keeps the whole small `steamapps` control root on
internal F2FS and rebinds only `steamapps/common` to the card.

The required `deja "Steam external library appmanifest loaded 0 apps FUSE flock
internal metadata common bind"` query returned no matches, so no prior-session
implementation was reused.

## 2026-08-10: Kingsway survives restart and runs from the microSD

Steam was stopped for one backup-first migration of the removable library's
small control plane. All external `steamapps` entries except the untouched
`common/Kingsway` payload were moved into the recoverable same-card directory:

```text
/storage/7376-B000/Android/data/com.termux/files/steam-arm64-library/steamapps-control.pre-internal-f2fs-20260810-1044
```

The live launcher then exposed the removable library in this order:

```text
external library root -> ~/steam-arm64/removable-library
internal control root -> removable-library/steamapps
external common       -> removable-library/steamapps/common
internal compatdata   -> removable-library/steamapps/compatdata
internal downloads    -> removable-library/steamapps/downloading
```

After the required restart, Steam logged `Loaded 1 apps` for the removable
library. `appmanifest_588950.acf` remained fully installed with `StateFlags 4`,
BuildID 7833329, and 60,322,784 bytes, and `libraryfolders.vdf` retained App ID
588950. This proves that internal F2FS control metadata fixes the restart-time
reset without moving the game payload off the microSD.

Kingsway was mapped at priority 250 to the confirmed internal tool key
`proton_11_arm64_official`. The pre-edit Steam configuration is preserved at:

```text
~/steam-arm64/backups/kingsway-compat-20260810-1032/config.vdf
```

The next launch selected only the intended route:

```text
~/steam-arm64/removable-library/steamapps/common/Kingsway/Kingsway.exe
SteamLinuxRuntime_4-arm64/_v2-entry-point --verb=waitforexitandrun
Proton 11.0 (ARM64)/proton waitforexitandrun
```

Pressure Vessel performed its known guarded `EXDEV` copy fallback while
assembling the 5,371-file temporary runtime. This matched the earlier isolated
Runtime 4 smoke recorded in this log, so that proven diagnosis was reused and
no speculative runtime change was applied. It then entered the patched route
wrapper, upgraded the new internal prefix to Proton `11.0-100`, and started
`S:\\common\\Kingsway\\Kingsway.exe` as PID 30467.

The running game environment provided `FEX_APP_CONFIG` from bundled official
Proton, selected the Turnip `freedreno-private.json` Vulkan ICD, and pointed
`PULSE_SERVER` at the project's TCP endpoint. PulseAudio reported an active
stereo 44.1 kHz sink input. X11 reported a fullscreen 2800x1586 window titled
`Kingsway`, class `steam_app_588950`, owned by PID 30467.

The exact game window was captured without the desktop or Steam UI. Visual
inspection confirms the rendered Kingsway `New Adventurer` screen and no Steam
account or friends-list names:

![Kingsway running fullscreen from the microSD](evidence/kingsway-running.png)

The captured PNG SHA-256 is:

```text
ea65967482f8bb995ef83f715f46b194a881676311fc038650a2c4dde61663d3
```

## 2026-08-10: forwarded Steam URLs tolerate empty mount shadows

After Kingsway exited, forwarding `steam://install/12210` through the launcher
was safely refused because PRoot had left empty covered directory skeletons at
`removable-library-steamapps/common/Kingsway` and
`removable-library-steamapps/compatdata/588950`. Both trees contained zero
files, while the real 65 MiB Kingsway payload remained intact on the microSD.

The required `deja "removable internal common mount point must be empty
forwarded steam URI Steam running"` query returned no matches, so no
prior-session fix was reused.

The helper now allows recursively real-directory-only skeletons in the three
nested mountpoints that are covered at launch. It continues to reject files,
symlinks, devices, and every other non-directory entry at any depth; the
top-level internal library mountpoint remains strictly empty. Tests reproduce
the live empty Kingsway, compatdata, and download shadows and verify nested-file
and symlink refusals.

The live candidate SHA-256 was
`08df3e3031b7ef9c9abda1796ffe88c95e089bd2cd195322ed26c6e137426f2f`.
The previous deployed helper is preserved byte-for-byte at:

```text
~/steam-arm64/backups/removable-skeleton-helper-20260810-1103/steam-arm64-removable-library.py
```

With Steam still running, the promoted helper passed its live layout check and
the next launcher invocation forwarded `steam://install/12210`. Steam logged
both `ExecCommandLine` and `ExecuteSteamURL` for App ID 12210 without a restart.

## 2026-08-10: GTA IV split staging and native microSD commit

Grand Theft Auto IV: The Complete Edition (App ID 12210, target BuildID
14009960) downloaded 21,023,910,704 bytes and staged 23,929,147,221 bytes.
Steam's normal commit then attempted 5,933 updated files across the internal
F2FS-to-microSD boundary. After about seven minutes it had committed only about
34 MiB and 98 files. This was the same per-file PRoot metadata cost observed on
Kingsway, scaled to a much larger tree; the content was not corrupt.

The required recall queries for cross-filesystem commit behavior, numeric
download binds, StateFlags recovery, identical overlap handling, appmanifest
finalization, and ContentManifest metadata returned no matching prior session.
No prior-session implementation was reused. The earlier documented forwarded
`-shutdown` procedure was reused: when Steam was idle it again produced a
natural exit, while a forward issued during the wedged commit remained queued
until the worker released Steam's main loop.

Steam was stopped before staging migration. The remaining internal tree had
5,604 regular files, 242 directories, no links or special files, and
23,894,672,552 bytes by `du -sb`. It was copied natively, without Unix
owner/mode/xattr preservation, to:

```text
/storage/7376-B000/Android/data/com.termux/files/steam-arm64-library/staging/12210
```

Independent full SHA-256 inventories of the internal source and external copy
matched byte-for-byte. Each contained 5,604 records and the manifest file hash
was:

```text
62fdb31c21a4ccde9a157ee59480b20828ac8d5fabeae885169ac808b96f358f
```

The evidence is retained at
`~/steam-arm64/diagnostics/gtaiv-staging-verify-20260810-1221/`. A production
PRoot probe proved that the external staging tree and external `common` target
both report device 1048616; a 1 MiB rename between the two completed in 0.446
seconds including PRoot startup. The launcher therefore adds the whole internal
downloads bind first and a narrower external `staging/12210` bind over only the
numeric guest download tree.

Configuration version 2 records each nested staging App ID with its verified
file count, byte count, and manifest SHA. `enable-staging-bind` requires Steam
and Wine to be stopped, identical source/target SHA manifest files, matching
tree statistics, safe real-directory mountpoints, and the expected internal and
external devices. Launcher startup validates only these fixed device and path
boundaries; it deliberately does not rescan thousands of mutable staged files.

The exact offline registration was:

```sh
bin/steam-arm64-removable-library.py --base "$HOME/steam-arm64" \
  enable-staging-bind 12210 \
  --source-manifest source.sha256 --target-manifest target.sha256
```

Steam resumed after a backup-first `StateFlags 1538` to `1026` correction,
redownloaded about 26 MiB, restored the one actually missing staged file, and
again reached the complete 23,929,147,221-byte stage. Its same-device view was
correct but the PRoot commit still spent its time on metadata calls and made no
useful progress.

The offline `commit-staging` action validates the registered manifest digest,
exact source inventory and byte total, source/target device equality, real
directories, zero Steam/Wine processes, and the installed target before making
same-filesystem `os.replace()` calls. Steam had already copied 61 paths without
removing their staged sources. The helper now accepts such overlaps only when
both files independently match the registered manifest digest; any mismatch is
a hard pre-mutation failure. A regression test covers both identical reuse and
mismatched refusal.

```sh
bin/steam-arm64-removable-library.py --base "$HOME/steam-arm64" \
  commit-staging 12210 --install-dir "Grand Theft Auto IV" \
  --manifest source.sha256
```

The live result was 5,543 same-device moves, 61 digest-verified reuses, and an
empty external staging tree. The final target contained exactly 5,702 regular
files and 23,929,147,221 bytes. The deployed helper SHA at that checkpoint was
`6b269ee74257422d8b702e055670057bd66a9617ec31f9e9a81015e62255c26e`;
its predecessor is preserved at
`~/steam-arm64/backups/staging-identical-overlap-20260810-1327/`.

The interrupted Steam commit also left `InstalledDepots` empty. Steam initially
accepted the corrected build/size as fully installed, then changed state 4 to
state 6 after appinfo added five depots. It logged 21,023,910,704 bytes to
download but zero bytes to stage, proving a control-metadata inconsistency
rather than absent installed content.

The five cached Steam ContentManifest files use the standard payload marker
`0x71f617d0` and metadata marker `0x1f4812be`. Their embedded protobuf fields
matched each filename's depot ID and manifest GID. Field 5 supplied these
original sizes:

```text
12218    5435507331887440070       6,554,576
12211    8070600747380932868  16,332,847,585
12213    7959739752369022030      37,487,453
12212    5029883714475696364   7,312,739,354
1899671  1378788310039702778     239,518,253
                                      -----------
                                   23,929,147,221
```

That exact sum equals both the completed stage and installed-target byte total.
The new offline `finalize-staging` action codifies the live repair: it requires
empty external staging, verifies every cached filename against its embedded
depot/GID, requires the signed depot sizes to equal the installed tree, checks
the app/build/counter state, creates a timestamped appmanifest backup, preserves
LF or CRLF style, and atomically writes normal installed state and the depot
block. For this build the reproducible command is:

```sh
bin/steam-arm64-removable-library.py --base "$HOME/steam-arm64" \
  finalize-staging 12210 --install-dir "Grand Theft Auto IV" \
  --depot-manifest "$HOME/steam-arm64/client/depotcache/12218_5435507331887440070.manifest" \
  --depot-manifest "$HOME/steam-arm64/client/depotcache/12211_8070600747380932868.manifest" \
  --depot-manifest "$HOME/steam-arm64/client/depotcache/12213_7959739752369022030.manifest" \
  --depot-manifest "$HOME/steam-arm64/client/depotcache/12212_5029883714475696364.manifest" \
  --depot-manifest "$HOME/steam-arm64/client/depotcache/1899671_1378788310039702778.manifest"
```

The live pre-finalization manifests are preserved at
`~/steam-arm64/backups/gtaiv-finalize-20260810-1347/` and
`~/steam-arm64/backups/gtaiv-depots-20260810-1359/`. After another Steam start,
App ID 12210 remained state 4 with BuildID 14009960, size 23,929,147,221,
`StagingSize 0`, all completed counters, schedule zero, and no new update event.

Only after that restart proof was the redundant internal
`removable-library-downloads/12210` tree deleted. The deletion revalidated the
exact resolved path, 5,543 files, 242 directories, zero non-file/non-directory
entries, 23,894,509,024 logical bytes, state 4, full installed size, empty
external staging, and zero Steam/Wine processes in the same foreground shell.
The empty mountpoint was recreated mode 0700. Internal free space increased by
23,954,800,640 allocated bytes, from 3,322,888 KiB to 26,716,248 KiB.

In the final Steam session, App 4628740 registered as
`proton_11_arm64_official`, App 4185400 registered as
`steamlinuxruntime_4_arm64_official`, and App 12210 mapped to the ARM Proton key
at priority 250 while remaining state 4. The first `steam://rungameid/12210`
forward was issued only after those lines appeared. The known slow historical
tool scan then completed with `CCacheOffSteamPlayStateJob ... complete` and
posted the ARM tool callbacks. The queued launch immediately entered official
`Proton 11.0 (ARM64)` and Runtime 4 ARM64 to run
`legacycompat/iscriptevaluator.exe` for App 12210.

The evaluator created the expected ARM Proton/Wine tree (`wineserver`,
`services.exe`, `rpcss.exe`, `iscriptevaluator.exe`, and SteamService) and is
currently running Steamworks Shared's DirectX June 2010 `DXSETUP.exe /silent`.
That leaf has accumulated hundreds of megabytes of read/write I/O and steadily
increasing traced context switches, so it is slow but not stuck. GTA IV and
Rockstar Launcher have not started yet; this section therefore claims the
correct ARM prerequisite route, not game execution.

## 2026-08-10: GTA IV first launch and signed registry workaround

After DirectX setup completed, the next launch produced the required tracked
command without any x86 fallback:

```text
SteamLinuxRuntime_4-arm64/_v2-entry-point --verb=waitforexitandrun
Proton 11.0 (ARM64)/proton waitforexitandrun
Grand Theft Auto IV/GTAIV/PlayGTAIV.exe
```

The live tree progressed through `srt-bwrap`, `pv-adverb`, official ARM Proton,
`wineserver`, and `PlayGTAIV.exe`. Runtime 4 performed the same guarded `EXDEV`
hard-link-to-copy fallback already proven by Kingsway. `PlayGTAIV.exe` then
started the bundled 112,072,312-byte x86-64
`Rockstar-Games-Launcher.exe /s /t` through FEX/Wine.

The exact Rockstar installer window was captured instead of the desktop. It
showed only the Rockstar logo and progress bar, with no Steam account or friend
data. Tablet and local copies matched SHA-256:

```text
83acd34a4652f0b21182cb21614ce92f45b910cb012f48f68080972c6c41a789
```

Four minutes later a second capture was byte-identical. The installer remained
at four sleeping threads with flat context-switch counters, no TCP connection,
no created Launcher executable, and no crash log. Its 653-byte
`installer_log.txt` ended at `Load Init Page`. A standard SIGTERM to only the
validated `srt-bwrap` game-container supervisor removed all ten GTA, Proton,
and Rockstar processes in five seconds; main Steam remained running and no
SIGKILL was used.

The same launch exposed a separate deterministic error in
`installscript_log.txt`: Steam tried to load the signed file at a Linux pathname
ending in the literal filename `GTAIV\installscript.vdf`. The real 566-byte
depot file is `GTAIV/installscript.vdf`, SHA-256:

```text
58de41add79ba9753b4a73b00a1ad7e7e1e14770c959beb4c8b78155607ed498
```

The failed evaluator left the GTA IV registry keys absent. Android's exFAT/FUSE
mount refused creation of a literal backslash filename with `EPERM`; the
byte-verified temporary copy was removed and the signed original remained
unchanged. The required
`deja "PRoot file bind nonexistent target backslash path"` search returned no
matching prior session, so no prior implementation was reused.

An isolated read-only Debian PRoot probe bound the real slash-path source onto
the nonexistent literal-backslash guest target. An exact `stat`/open of that
guest path returned the real 566-byte file with the same SHA. However,
`readdir()` on the parent did not contain the alias: it returned only `GTAIV`,
`Redistributables`, and `installscript_sdk.vdf`. PRoot can redirect an exact
lookup but does not synthesize a nonexistent bind target into directory
enumeration.

Steam shut down naturally before deployment. The previous launcher/helper are
preserved at:

```text
~/steam-arm64/backups/gtaiv-installscript-bind-20260810-1423
```

The experimental deployed launcher SHA was
`5b9f2d4345e47193b475fec1c0f0504a79f75a5bce091d8c2e3ab338b13ee2a1`;
the deployed finalizer-capable removable helper SHA is
`0f5a50963d2b2ab8e0fa82837c08ec970d4e680f81e3ec980062d88ca6c5ff42`.
On restart the launcher printed the exact GTA IV path bind, Steam again
registered both official ARM tools, and App 12210 retained its priority-250 ARM
mapping. After compatibility registration completed, the 21:26:33 retry still
logged the identical installscript load failure and created neither registry
key. The production PRoot argument contained exactly one backslash and the bind
followed its parent mounts, confirming directory enumeration—not quoting or
ordering—as the failure. The ineffective launcher bind is therefore removed
from the repository.

The signed VDF contains no prerequisite executable. Its complete effect is:

```text
HKLM\SOFTWARE\Rockstar Games\Grand Theft Auto IV
  InstallFolder = S:\common\Grand Theft Auto IV\GTAIV
HKLM\SOFTWARE\Rockstar Games\Grand Theft Auto IV\1.00.0000
```

The `S:` dosdevice was verified as a symlink to the removable library's
internal `steamapps` control path, which exposes the external `common` bind in
the game container. A required
`deja "Proton reg.exe HKLM registry PRoot FEX Termux"` search found no prior
session to reuse. Instead,
`scripts/configure-gtaiv-registry.py` reuses the already tested backup, staged
write, `fsync`, atomic replace, and post-write verification pattern from the
Superflight registry helper. It additionally refuses a changed signed-VDF
hash, wrong `S:` mapping, symlink/multi-link registry, duplicate/partial/wrong
keys, or any live Wine, Proton, FEX, Runtime, GTA, or Rockstar process.

While Steam's one-time GTA shader replay was active but no prefix writer or
game container existed, the helper applied the two entries. Evidence:

```text
signed VDF SHA-256: 58de41add79ba9753b4a73b00a1ad7e7e1e14770c959beb4c8b78155607ed498
backup: ~/steam-arm64/backups/gtaiv-registry-20260810-144159-aupo4ih6/system.reg
backup SHA-256: c96836b6257de18e592b0c4d2c34aa66d19233a242c0b787f6151ddb5831f9e3
installed SHA-256: 5acf092fc006e661ba41698168ea118db8c8538845a8ae21c0714fcc0b934afc
deployed helper SHA-256: 74705507e1dbc58982197889ea47530411ee9fa0e6f9f2f54c8437c2b54583a6
```

An immediate idempotent `--check` and literal inspection confirmed both exact
sections. This proves the signed installscript state is present; it does not
yet prove that Rockstar Launcher gets past `Load Init Page` or that GTA IV
renders.

## 2026-08-11: GTA IV Rockstar CEF Code 17 matrix

GTA IV now reproducibly reaches its current Rockstar stack through the normal
Steam URI and the official ARM tools. The tracked command uses
`SteamLinuxRuntime_4-arm64`, `Proton 11.0 (ARM64)`, and `PlayGTAIV.exe`; it does
not fall back to an x86 Runtime or Proton Experimental. The installed launcher
is 1.0.108.2970, Social Club is 2.4.0.216, and its CEF is 143.0.0.0.

Rockstar Service connectivity is not the first failure. Launcher logs show
successful HTTP work and `GetDefaultApps`, then Social Club connects its CEF
browser but receives no page-load callback for either the online page or its
packed offline `default.html`. Each path receives a 60-second window before
Category 3, Code 17, `SC_INIT_ERR_WEBSITE_FAILED_LOAD`. The browser already
uses `--no-sandbox`; the renderer uses `--no-sandbox`; and the GPU process uses
`--disable-gpu-sandbox`, so repeating sandbox switches is not justified.

The following controlled tests all preserved the same official Steam/Proton
route and were rolled back after failure:

| Test | Confirmed effect | Functional result |
| --- | --- | --- |
| CEF `hardware_acceleration_mode.enabled=false` | Correct active `Local State` changed and restored | Code 17 |
| SocialClub-only WineD3D overrides | `d3d11`/`dxgi` builtins were present in live mappings | Code 17 |
| Strict bundled-FEX TSO JSON | Reduced `titles.dat` queued-write latency from about 176 seconds to 8–12 seconds | Code 17 |
| `PROTON_NO_FSYNC=1` | `WINEFSYNC` absent from the live Wine environment | Regression: browser helper did not start |
| Disable Rockstar Vulkan overlay layer | Layer absent from GPU mappings; Turnip remained | Longer helper lifetime, then a white window and no GTA |
| `%command% -scDisableGpu` | Rockstar translated it to `--disable-gpu` plus `--disable-gpu-compositing`; steady GPU count became zero | Exact Code 17 at 120 seconds |
| Wine virtual desktop, 1920x1080 | CEF visibly painted the Rockstar connection screen inside `Wine Desktop` | Internal Code 17, window disappeared, no GTA |

The virtual-desktop route came from the primary Proton launcher report
<https://github.com/ValveSoftware/Proton/issues/5882>, which reports that Wine
virtual desktop fixes similar Chromium launcher hangs. Termux:X11 reports one
`builtin` monitor at 2800x1586, not the issue's multi-monitor topology. On this
tablet virtual desktop fixed presentation only: the launcher rendered
"Connecting to Rockstar Games Services" and ran beyond the normal external
error-dialog deadline, but its open log still contained Code 17, three timeout
markers, no ready marker, and no `GTAIV.exe`.

The privacy-safe 1920x1080 diagnostic capture contains no Steam account,
friends list, or Rockstar username. Tablet and local copies matched SHA-256:

```text
5288160e45bce8c213cf365c35c697cee74205662ea39a21978867b1c62364a2
```

The failed final blank capture was deleted from both machines. The safe image
is retained outside Git until there is a successful game milestone.

The new `scripts/configure-gtaiv-virtual-desktop.py` tool exists to reproduce
or remove this diagnostic without hand-editing `user.reg`:

```sh
scripts/configure-gtaiv-virtual-desktop.py --enable --size 1920x1080
scripts/configure-gtaiv-virtual-desktop.py --check --size 1920x1080
scripts/configure-gtaiv-virtual-desktop.py --disable --size 1920x1080
```

It refuses symlink/multi-link registries, duplicate or unexpected values, and
any live Wine/Proton/FEX/Runtime/Rockstar process. Changes use a byte-verified
backup, same-directory staged write, `fsync`, atomic replace, and post-write
verification. Disable removes only the exact values it owns and preserves any
later Wine state. Enable and post-test backups are:

```text
~/steam-arm64/backups/gtaiv-virtual-desktop-20260811-020450-qt8eb6jo
~/steam-arm64/backups/gtaiv-virtual-desktop-20260811-021801-7gilqep7
```

The required `deja` searches for the CEF/FEX white-window symptom and Wine
virtual-desktop route returned no matching prior session. The helper reuses the
repository's tested GTA registry atomic-write/process-guard pattern; the
display workaround itself is attributed to the Proton issue above.

The dominant cold-launch delay is separate from Code 17. After shader replay
is skipped, `pressure-vessel-wrap` spends roughly three to five minutes in
`aarch64-linux-gnu-capsule-capture-libs` through production PRoot before Wine
starts. The tracer consumes CPU and its traced child normally sits in
`ptrace_stop`; this is slow forward progress, not a deadlock. Optimizing or
caching that capture is the next startup-performance target.

After every failed test, only App 12210 processes were enumerated from their
exact Steam environment and stopped with normal SIGTERM; SIGKILL was never
used and native Steam survived. The restored baseline has empty GTA launch
options, default fsync, hardware acceleration enabled, the Rockstar Vulkan
layer enabled, and Wine virtual desktop disabled. GTA IV is not yet running.

Three follow-up diagnostics narrowed the remaining failure further.

First, a bounded Proton trace used an isolated directory and the exact launch
environment `PROTON_LOG=1` with
`WINEDEBUG=+timestamp,+pid,+tid,err+all,warn+all`. A two-second watcher enforced
a 64 MiB ceiling; the log stopped at 19,824,105 bytes, SHA-256:

```text
408e14cc7bdcb942ef73b36b6919cb4c7c9b0955ca186cdd206dfe6acce7a473
```

This instrumentation changed the failure and is not suitable for Code 17
analysis. It emitted 61,227 `seh:virtual_unwind` and 45,921
`virtual:virtual_setup_exception` warnings, then Rockstar `Launcher.exe`
(Windows PID `0138`) hit an explicit `virtual_setup_exception` stack overflow.
The UI showed the distinct 311x82 message "Unable to launch game, please try
reinstalling the game" before any `SocialClubHelper.exe` existed. Dismissing
that validated dialog caused App 12210 to exit naturally. The diagnostic
screenshot was deleted from both machines; the trace remains outside Git.

Second, the 1920x1080 Wine virtual desktop and Rockstar's supported
`-scDisableGpu` option were tested together. The final Steam command carried
the option, and `CrBrowserMain` received both `--disable-gpu` and
`--disable-gpu-compositing` inside the live Wine desktop. GPU subprocesses still
restarted, and the combination ended at the same 940x318 Code 17 dialog with
three timeout markers and no `GTAIV.exe`. The interaction therefore provides
no workaround. Both values were removed and idempotently verified; the
post-test prefix backup is:

```text
~/steam-arm64/backups/gtaiv-virtual-desktop-20260811-025015-rxjdcokn
```

Third, an unmodified baseline launch inspected only CEF argument names and
kernel descriptor categories. Browser main grew to 129 pipes and five sockets.
Renderer received a numeric `--mojo-platform-channel-handle` and a
`--field-trial-handle`, then grew to 69 pipes and three sockets. Browser and
renderer shared six pipe/socket/anonymous kernel objects. GPU, network, and
storage subprocesses also received Mojo and field-trial handles. The numeric
Mojo value was not a Linux FD, which is expected for a Windows handle mediated
by Wine and is not itself an error.

That baseline remained alive for a 701-second watcher with browser, renderer,
GPU, and utility processes present. Rockstar's open log nevertheless recorded
Code 17, three timeouts, zero ready markers, and no `GTAIV.exe`; its visible
window had already disappeared. Basic subprocess creation, Mojo argument
delivery, and all browser-to-renderer kernel-object sharing are therefore not
missing. The remaining blocker is above channel construction: CEF renderer
execution or browser event/page-completion delivery under the ARM64
Wine/FEX/PRoot stack.

Existing FEX single-step and `MaxInstPerBlock` 32/256 diagnostics were also
audited before proposing another translator knob. They failed before CEF and
did not advance the Rockstar service log, so they are not evidence for the
current callback failure. `socialclub.dll` contains `scDebugLogging`, but it is
in a generic protobuf/XML literal area with no adjacent debug-port, level, or
file controls; it was not guessed as a launch switch.

After these diagnostics the clean baseline was restored again: no App 12210
process, empty launch options, Wine virtual desktop disabled, and native Steam
alive. Internal free space remained 23 GiB.

## 2026-08-11: credential-free Chromium/FEX callback boundary

The remaining Rockstar Code 17 failure was separated from account state with
two credential-free Windows diagnostics. Required `deja` searches for a CEF
143/FEX reproducer, delayed callback queues, and a Wine `wkscli` shim returned
no matching prior session. The implementation instead reused two already
proven repository patterns: the freestanding Termux LLVM PE build used by
`win-network-status-probe.c`, and the removable-library topology that binds an
external SD directory onto an ordinary internal Termux path before Wine sees
it.

First, `diagnostics/win-x64-message-loop-probe.c` exercises the Windows
primitives used by Chromium's message pump without loading CEF. It creates a
worker-signaled kernel event, delivers and removes a posted thread message,
and queues an APC to an alertable `MsgWaitForMultipleObjectsEx` call. The
freestanding executable imports only the explicit Kernel32/User32 symbols in
`diagnostics/win-x64-kernel32.def` and
`diagnostics/win-x64-user32.def`. It is reproducibly built on the tablet with:

```sh
scripts/build-win-x64-message-loop-probe.sh /path/to/output
```

Termux Clang 21.1.8 and LLD produced a 4,608-byte AMD64 PE with zero timestamp,
SHA-256:

```text
3c875b361634cbff85ea063163cfeed63756f3ab39caf5d425a150a28821521c
```

It ran through official Proton `11.0-1-beta5-unstripped` using the supported
`runinprefix` verb and a new scratch compatdata directory. The exact transcript
has SHA-256
`a9e3e8953e3750b1da7e412d7d3f2cd802500b30cfb10b2c37e5235580363223`
and ended:

```text
EVENT_WAIT_RC=0x00000000
EVENT_SET_RC=1
MESSAGE_WAIT_RC=0x00000000
MESSAGE_POST_RC=1
MESSAGE_FOUND=1
APC_WAIT_RC=0x000000c0
APC_QUEUE_RC=1
APC_CALLBACKS=1
EVENT_PASS=1
MESSAGE_PASS=1
APC_PASS=1
PASS=1
```

This rules out a broad failure of kernel-event wakeups, posted-message
delivery, APC dispatch, or alertable message waits in AMD64 PE code translated
by the bundled FEX. The probe exited zero and left no scratch Wine/FEX process.

Second, the official Google Chrome for Testing manifest resolved milestone 143
to `143.0.7499.192`. Its public Windows x64 headless-shell archive came from:

<https://storage.googleapis.com/chrome-for-testing-public/143.0.7499.192/win64/chrome-headless-shell-win64.zip>

The 111,718,755-byte ZIP has SHA-256
`5c6a6b71acc58f51d17c243e8e09e392753f95ea01bc7ec9a715eb3e1fd9e6fb`.
Its 187,059,200-byte `chrome-headless-shell.exe` is AMD64 and has SHA-256
`e05c08952f663b375a797b71812c609d223cab2e50bef3a7ff91669ca62810e9`.
The archive and extracted 387 MiB payload remain outside Git on the removable
card under `steam-arm64-diagnostics/chrome143-renderer-20260811-0730`.
Google documents Chrome for Testing's version/download API and headless-shell
artifacts at <https://github.com/GoogleChromeLabs/chrome-for-testing>.

`diagnostics/chromium-renderer-probe.html` is the offline input. Its final PASS
marker requires JavaScript arithmetic, Promise delivery, a WebAssembly export
returning 42, a `data:` fetch, and a timer callback before updating the DOM.
The file's tablet and repository copies match SHA-256
`3a9327a88e4614bc7b226eff5ed7c9710b98bacc051c7c59be0d4f05def82804`.

The first loader trace exposed a separate Proton gap before Chromium started:
the PE imports only `NetGetJoinInformation` from `wkscli.dll`, but Proton 11
ARM64 ships no such module. Wine mapped the Chrome PE and then stopped with
`c0000135`. The bounded `-all,+loaddll,+module,+seh` trace was 627,189 bytes,
SHA-256
`dee5549a69667e4b1277558d194d64f1893a43e061f4d0e40fb00cd0ee2ed219`.
It did not reach a browser process and left no residue.

`diagnostics/win-x64-wkscli-shim.c` provides only that one app-local diagnostic
symbol. It returns system error 50 (`ERROR_NOT_SUPPORTED`) after setting the
name buffer to null and join status to unknown. This follows the documented
API contract without inventing domain membership or allocating a buffer:
<https://learn.microsoft.com/en-us/windows/win32/api/lmjoin/nf-lmjoin-netgetjoininformation>.
The shim is built with:

```sh
scripts/build-win-x64-wkscli-shim.sh /path/to/output
```

The resulting 2,048-byte AMD64 DLL has no imports, exactly one export, and
SHA-256
`ad701bde2cff9aca038797c784e19af98303db416c45545dccde5f15d506ad15`.
Only that binary was placed beside the public Chrome diagnostic on SD; it was
not installed into Proton, GTA, or either Wine prefix and is not tracked in
Git.

After the shim, Chrome passed PE import initialization and created browser
main. Matching the live environment required two additional controls:

- `PD_PROOT_BIN` selected the production patched PRoot, SHA-256
  `0378e0631dbf7a8bd0061b54fc167bb881c70a76109f567b682f7262a063166c`,
  instead of stock Termux PRoot, SHA-256
  `6ffdff4117c571d07aa7e6f940001f050c97adb920660c984b72d4a537b4f60a`.
- The existing 173-byte route shadow, SHA-256
  `4b3a3e8bed570a9f39e2bca75b86e1023e3ecded31f4efe046469b63be53c648`,
  was bound at `/proc/net`. A guest-side hash check proved the bind before
  Chrome started.

The matched multiprocess run used a fresh profile, no sandbox, disabled GPU
and background networking, a two-second virtual-time budget, and a 180-second
normal-TERM ceiling. Browser main appeared, and a GPU subprocess appeared
about 92 seconds later. No renderer process was sampled, the PASS image was
never created, and the run timed out with no residual scratch process. The
route shadow removed repeated DNS-configuration warnings. The only remaining
Chrome log entry was:

```text
WSALookupServiceBegin failed with: 8
```

Chromium 143 handles that call failure by logging it and immediately returning
`CONNECTION_UNKNOWN`; it does not block in the notifier function:
<https://chromium.googlesource.com/chromium/src/+/refs/tags/143.0.7499.192/net/base/network_change_notifier_win.cc#188>.
A fresh `--single-process` control under the same production PRoot and route
shadow also retained only browser main for 180 seconds and produced no image.
It therefore did not demonstrate page, Blink, V8, or WebAssembly execution.

This clean reproducer narrows the remaining issue without proving an exact
Rockstar cause. Basic Windows callback/message primitives work, while a
same-generation Chromium browser does not reach useful page execution under
the matched Proton ARM64/FEX/PRoot environment. Rockstar's CEF can create and
retain a renderer but never reports page completion, so the common boundary is
now Chromium browser/renderer startup and event delivery above generic Wine
wait primitives—not Steam authentication, Rockstar HTTP reachability, DXVK,
or Turnip. Native Steam remained alive throughout; GTA App 12210 was never
launched or modified in this checkpoint, and internal free space remained
23 GiB.

## 2026-08-11: combined production/metadata-fastpath PRoot candidate

A required `deja` query for the exact message-loop/Proton/PRoot launch recipe
returned no matching prior session. This work reused the repository's stamped
PRoot builder, isolated diagnostics directories, explicit `PD_PROOT_BIN`
selection, four production regression probes, and official Proton
`runinprefix` pattern. No live source tree was hand-merged.

`scripts/build-proot.sh` now accepts the opt-in build-time switch
`PROOT_ENABLE_NODEREF_FASTPATH=1`. It appends
`proot-noderef-fastpath.patch` after the ten production patches and therefore
includes it in the ordered patch-list, patch-set, diff, and executable hashes.
The default remains the production patch set; any value other than `0` or `1`
fails before creating a target tree.

The isolated tablet build is:

```text
source       ~/steam-arm64/src/proot-production-fastpath-candidate
commit       a89b3732ec6ae1db674510f0843b2f3db54d0a2f
patch set    e30b8179fe50fca210e59e5379b63d8c0596bec58dc371b041b372d9c2e25898
binary diff  5aeaf544250f8d57ffd84254b187009cf289303ac815e8abbbcd1ce544cae953
binary       4d38e8a989df054ea119cf9b0981ff74cd41af03e62453c24081f485c275032a
```

The combined source has 12 modified files, 665 insertions, and 33 deletions.
It was rebuilt from clean objects against its stamp and reproduced the same
binary hash. The production executable remained
`0378e0631dbf7a8bd0061b54fc167bb881c70a76109f567b682f7262a063166c`;
`bin/steam-arm` continued to select that production path.

The candidate then passed the current spaced-path, shared-`/tmp`,
post-`--proc` `/proc/net`, and mountinfo-escaping probes. Their combined
transcript has SHA-256
`bf836f4f080640197d25b841d341ced1d4e15a09a0455242cf92ed0d80faa909`.
The existing AMD64 message-loop PE, SHA-256
`3c875b361634cbff85ea063163cfeed63756f3ab39caf5d425a150a28821521c`,
ran through official Proton 11 ARM64 and bundled FEX with the candidate. It
exited zero, left no Wine/FEX process, and reproduced the exact prior all-PASS
transcript SHA-256
`a9e3e8953e3750b1da7e412d7d3f2cd802500b30cfb10b2c37e5235580363223`.

The credential-free public Chrome control was attempted with the trusted SD
bind supplied through `proot-distro --env`. Candidate v6 and a production-only
v7 control both created fresh profiles, exited with code 3 after 41
seconds, produced no image, emitted only the normal wineserver synchronization
line, and left no process. Because the production control behaved identically,
this is not a candidate regression. The literal earlier v4 command was not
preserved, so these reconstructed runs also do not supersede v4's 180-second
browser/GPU timeout or measure a candidate renderer improvement.

`scripts/benchmark-proot-filesystem.sh` now accepts `PROOT_BUILD_DIR` and
`PROOT_BENCHMARK_TARGET`. It also passes `PROOT_NODEREF_FAST_PATH` via
`proot-distro --env`. A first alternating benchmark accidentally supplied that
variable only to the outer Termux shell. Inspection of the actual candidate
PRoot process showed an empty value, invalidating that transcript as a speed
measurement. A second process-environment probe with `--env` exposed the exact
trusted Proton Experimental path and passed.

The corrected three-pair benchmark counted 5,601 files in every case. Median
long-path time fell from 1.733 to 1.589 seconds (8.3%); median explicit-bind
time fell from 1.742 to 1.527 seconds (12.3%). The corrected transcript SHA-256
is `582f407dc655a3a483de1bb1a5ffe970c97f74cc550d915dfedfb10b7c3e0d09`.
These measurements are materially faster but smaller than the first prototype
delta, and do not justify claiming a Chromium or GTA fix.

The closing health check found no GTA, Rockstar, Chrome-control, Wine, or FEX
process. Internal storage had 23 GiB free, the SD card had 576 GiB free, and
the two guarded CEF logs were zero bytes. The 18-hour Steam session did have
two leaf CEF children consuming roughly 1.7 CPU cores through PRoot. After
their names, parents, tracer, arguments, and lack of descendants were
revalidated, normal TERM removed only those two leaves. Steam immediately
respawned replacements which remained CPU-heavy, proving that blind child
reaping is not a remedy. Main Steam stayed alive; no stronger signal or Steam
restart was performed in this checkpoint.

## 2026-08-13: Rockstar authenticated and GTA IV selector rendered

This checkpoint crossed the prior Code 17/authentication boundary without
restarting native Steam, X11, KDE, or Termux. The required `deja` searches did
not return an indexed match. The launch procedure reused the exact
`steam://rungameid/12210` URI and descendant-affinity method from Codex session
`019fe348-1247-7530-bc25-8a573aaf4252`, plus the scoped Social Club WineD3D and
saved-login preservation patterns from session
`019ff310-e8ac-7212-9f2f-5ba9005b97bd`.

The working route had four relevant controls. The Pressure Vessel wrapper
validated and overlaid a private internal GTA IV executable view while binding
the large data directories from the original microSD install. Its final
`PlayGTAIV.exe` payload became `cmd.exe /d /c C:\\gtaiv-service-first.cmd`,
which started `Rockstar Service` before the signed launcher. Wine's
`ServicesPipeTimeout` was 60 seconds. Finally, only
`SocialClubHelper.exe` used builtin `d3d11` and `dxgi`; the actual game retained
the accelerated D3D9/Vulkan path. No Rockstar account/profile tree was deleted
or cleared, and the known-good authenticated data remained backed up outside
Git.

The online CEF renderer completed its page state and launcher startup. The
decisive launcher records were:

```text
UiWindowController::SetContext: Auth -> MainWindow
Presence Event - Signed In
Presence Event :: Went Online
Attempting Steam launch.
Begin game launch: gta4
Launching game...
Path: S:\\common\\Grand Theft Auto IV\\GTAIV\\GTAIV.exe
```

The real `GTAIV.exe` appeared as a distinct process. `/proc/<pid>/maps` proved
that `GTAIV.exe`, `binkw32.dll`, and `steam_api.dll` came from the validated
internal executable view; Wine's `d3d9.dll`, `winevulkan`, Turnip's
`libvulkan_freedreno.so`, and App 12210's shader caches were also mapped. This
run did not capture an `MTLX.dll` mapping, so none is claimed.

The game initially had no window after Rockstar's 60-second warning. A
read-only CPU sample showed the outer PRoot tracer using about 82% of one core
and `RockstarService` about 124%, both eligible for the same performance cores.
A reversible process-local split placed PRoot on CPU 7, Rockstar Service on CPU
6, and wineserver/GTA IV on CPUs 4-5. GTA IV then advanced from 28 to 54
threads, roughly 1,350 to 1,874 mappings, and about 30 MiB to 448 MiB resident
memory before creating a focused fullscreen X11 window titled `GTAIV`.

An exact-window capture showed a fully rendered GTA IV / Episodes from Liberty
City selector rather than a black surface. GTA IV's Play control was visibly
highlighted and Enter was sent only after validating the focused window and its
owning process. Later, more complete timing evidence invalidated the initial
interpretation that the input had been accepted: the game remained on the
selector and Social Club recorded `[00600157] Shutting down...`, the exact
roughly 600-second idle boundary, followed by a clean launcher exit. The thread
and mapping growth after the attempted input was therefore continuing selector
startup, not proof of a selection. The proven milestone is authenticated online
launcher plus rendered game selector—not an accepted selection or in-game
scene.

The generic Rockstar splash captured immediately after email verification is
retained as privacy-safe context under
`docs/evidence/gtaiv-rockstar-email-verified-2026-08-12.png`. It contains no
account identifier and is not treated as proof of the later authenticated or
game states.

### Repeat confirmation and retained selector evidence

A fresh launch later on 2026-08-13 preserved the existing Rockstar login and
again reached `Auth -> MainWindow`, signed-in presence, online presence, cloud
sync completion, and the genuine `GTAIV.exe` without another 2FA prompt. This
time `/proc/<pid>/maps` also captured executable mappings for `MTLX.dll` from
the validated internal executable view. The process grew from 3 to 25 and then
54 threads, opened the game audio archives and App 12210 shader/pipeline caches,
and created a focused fullscreen 2800x1586 X11 window.

Capturing the direct game child returned a black surface because the composed
fullscreen frame lives at the root/KWin surface. A root capture produced a
fully rendered selector and was byte-identical to the previous selector
milestone. The privacy-safe image is retained as
`docs/evidence/gtaiv-selector-2026-08-13.png` and is the lead README screenshot.
Synthetic XTest input and events injected directly through the live Lorie X11
devices were visible to XInput diagnostics but did not reach the selector's
game input path. The process later reached the same exact 600-second idle
shutdown rather than exiting in response to the attempted Play input. The
remaining boundary is therefore selector input delivery, downstream of the
repeatably working Rockstar login, online presence, cloud sync, executable
routing, and initial D3D9/Vulkan setup.

A bounded Windows ARM64 diagnostic now addresses that boundary without relying
on XTest. `diagnostics/win-arm64-gtaiv-selector-input.c` enumerates only visible
top-level windows, requires the exact title `GTAIV`, focuses that window, and
places one Return press/release pair into Wine's Win32 input queue with
`SendInput`. It exits with status 2 if the exact window is absent and status 3
if Wine does not accept both input records. The reproducible freestanding build
is `scripts/build-win-arm64-gtaiv-selector-input.sh`; the generated PE imports
only `ExitProcess` and the six declared User32 calls. Live selector validation
is still required before this helper can be called a fix.

### Main-menu milestone after full desktop recovery

Later on 2026-08-13, the whole Termux:X11/KDE/Steam display stack had to be
recreated after an unrelated process loss. The authenticated Rockstar prefix
and its backup were left untouched. Native ARM64 Steam reused its saved login,
Rockstar again reached `Auth -> MainWindow`, signed-in and online presence, and
cloud sync without another 2FA challenge, and the genuine `GTAIV.exe` launched
again.

The one-shot game affinity had reset during startup, so a bounded maintainer
validated the exact GTA IV, wineserver, Rockstar Service, and outer PRoot
processes before keeping their previously measured process-local CPU split.
With GTA IV on CPUs 4-5, it advanced from 25 to 57 threads and rendered the
legal screen, GTA IV logo, selector, and finally the actual GTA IV main menu.
No account/profile files were deleted or reset.

The retained 2800x1586 composed frame visibly shows the GTA IV title art,
`Start` selected, and the connected Social Club panel. Its SHA-256 is
`0eec82f4317efd0943410ed93a67560018b8cc92a26c638100f24271f40486f2` and it is
stored as `docs/evidence/gtaiv-main-menu-2026-08-13.png`. At capture time the
real `GTAIV.exe` was still alive with 57 threads and CPU affinity 4-5. This is
proof that the run passed the earlier selector boundary and reached the game
menu; it is not yet evidence of a loaded gameplay scene.

This recovery continued to reuse the exact `steam://rungameid/12210` launch and
descendant-affinity method from Codex session
`019fe348-1247-7530-bc25-8a573aaf4252`, plus the scoped Social Club WineD3D and
saved-login preservation patterns from session
`019ff310-e8ac-7212-9f2f-5ba9005b97bd`. The required new `deja` query,
`Termux X11 KDE launch-only Steam ARM tablet full process kill GTA IV saved
login`, returned no additional indexed match.

### Game-loading sequence and whole-Termux process loss

Choosing `Start` advanced GTA IV beyond its main menu into the rotating game
loading-art sequence. Twenty-one complete 2800x1586 composed frames were
captured locally; five visually distinct, privacy-safe originals are retained
under `docs/evidence/gtaiv-loading-art-*-2026-08-13.png`. Sound was present but
stuttered during this run. Audio and performance tuning are deliberately
deferred until a playable scene is repeatable.

At 11:47:46 PDT, Termux:X11 still logged 3.2 frames per second and the real
`GTAIV.exe` remained alive with 57 threads and affinity 4-5. Shortly afterward,
the SSH listener refused a connection. Android then created a fresh
`com.termux` process at 11:48:21 and the SSH service was listening again by
11:48:26. The former X, KDE, Steam, GTA IV, Wine, and Rockstar processes were
all absent; the X0 filesystem socket remained but had no server behind it.
There was no orderly GTA/Rockstar shutdown record.

This evidence identifies a whole Termux native-process-tree loss rather than a
normal game exit. It does not yet identify the trigger. No retained `lmkd`,
kernel OOM, or `am_kill` line was visible to the Termux user, and the observed
3.9 GiB `MemAvailable` value was measured only after the former process tree
had already been reclaimed. Repeated ImageMagick root captures overlap the
failure window but are correlation, not proof of causation. The required
`deja "Termux X11 ImageMagick import root screenshot repeated capture kills X
server GTA IV"` query returned no indexed match.

`scripts/monitor-termux-game-session.sh` is a bounded, read-only sampler for the
next run. Every five seconds it records memory and swap availability, total
Termux-UID RSS/process count, load, and the presence of the critical X, KDE,
Steam, GTA IV, Rockstar, Wine, and PRoot processes. Its log is written with
mode 0600 outside Git. This should distinguish memory/swap exhaustion from a
display-only or ordinary game-process failure without polling X or touching
saved authentication.

### Android foreground scheduling and Rockstar's deadline

The next recovery used a launch-only X/KDE path to preserve the authenticated
Rockstar prefix. The live `startplasma-x11` process was orphaned under PID 1
rather than remaining the foreground job of a Termux terminal. Inspection of
the installed `~/start-kde` established that it contains no `taskset`, wake
lock, Android importance adjustment, or general process timeout override. Its
`pulseaudio --exit-idle-time=-1` setting prevents only PulseAudio's idle exit;
its final `exec startplasma-x11` keeps Plasma attached to the terminal that ran
the script.

The launch-only session exposed a separate, exactly reproducible Android
scheduling effect. While Termux:X11 was the foreground Android activity, the
Termux application PID and all inspected native children reported:

```text
cpuset: /moderate
cpu: /background
Cpus_allowed_list: 0-3
```

The tablet has CPUs 0-7 online. A one-variable live A/B brought the existing
Termux activity forward without restarting any native process:

```sh
am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER \
  -n com.termux/.app.TermuxActivity
```

The same Steam PRoot immediately changed to `/cpuset/top-app`, `cpu:/top-app`,
and `Cpus_allowed_list: 0-7`. Bringing the existing X11 activity forward with
the corresponding `com.termux.x11/.MainActivity` component immediately moved
it back to `/moderate`, `cpu:/background`, and CPUs 0-3. A separately acquired
`termux-wake-lock` returned success and created Termux's ongoing service
notification, but correctly did not change the cpuset: a wake lock prevents
CPU sleep and is not a scheduling-class control.

This launch then distinguished a timeout from a kill. Steam completed the GTA
IV install evaluator, the optional Vulkan shader dialog was skipped, Pressure
Vessel built its runtime view, Wine started, and both `RockstarService.exe` and
`Launcher.exe` appeared. Rockstar downloads returned HTTP 200. Confined to
CPUs 0-3, however, launcher background-service transactions grew from 61 to
152 seconds. At 20:13:29 UTC, almost exactly five minutes after Launcher began,
it reported `SC_INIT_ERR_WEBSITE_FAILED_LOAD` (Code 17) and the visible error
said that both online and offline content had timed out. At that point X, KDE,
Steam, PRoot, Wine, PlayGTAIV, Rockstar Service, and Launcher were all alive,
and the sampler still recorded about 1.99 GiB `MemAvailable`. This failure was
therefore Rockstar's UI deadline, not Android killing the process tree.

The result does not prove that background scheduling caused the earlier
whole-Termux loss. It does prove that foreground scheduling can determine
whether Rockstar completes before its own deadline, so future launches should
acquire the wake lock and keep the Termux activity foregrounded during the
nonvisual launcher initialization. Termux:X11 should be restored only after
`launcher.log` reports `Social Club UI has started` and `Client is ready to
attempt a launch`. The monitor now also records the effective CPU list,
cpuset/cpu cgroups, Termux application PID, and its readable OOM adjustment so
the next process-tree loss can be correlated with Android scheduling state.

This investigation reused the foreground-component command and prior
`background/moderate` versus `top-app` measurements from Codex session
`019fe348-1247-7530-bc25-8a573aaf4252`. The required `deja "start-kde"` and
`deja "Termux foreground cpuset"` searches found that session; no timeout-pin
implementation was reused because the installed script has no such mechanism.

### Fullscreen 720p launch, selector click, and CEF lifetime

A later clean run preserved both Steam and Rockstar authentication and used the
plain `-width 1280` / `-height 720` profile with Wine virtual desktop disabled.
The game still exposed a display-sized X11 window because fullscreen scaling is
handled by the presentation path; the internal render profile was not reverted
to the native 2800-pixel desktop size. After Termux:X11 returned to the Android
foreground, GTA grew from 25 to 38 threads and produced its first non-black
frame.

The new `win-arm64-gtaiv-selector-play.exe` requires the exact visible `GTAIV`
window and a fullscreen display of at least 640x480, calculates the retained
left Play target as 28 percent across and 79 percent down the current screen,
and sends one Win32 mouse click. Earlier rectangle-based revisions were not
reliable: Wine could reject both `ClientToScreen` and `GetWindowRect`, and the
separately attached ARM64 PE could finish with an access violation after its
input side effect. The implementation therefore avoids cross-process rectangle
queries, and validation uses the following frame and process transition rather
than the Wine loader's teardown status. GTA rendered its legal screen and title
logo with 43-52 threads after the input path was exercised. Privacy-safe
captures are retained as
`docs/evidence/gtaiv-fullscreen-legal-2026-08-13.png` and
`docs/evidence/gtaiv-fullscreen-logo-2026-08-13.png`.

The same run established an important negative result for memory tuning. At
peak pressure, GTA was alive with 57 threads while four Rockstar CEF processes
held about 2.2 GiB of swap. Sending normal `TERM` only to those four exact,
App-12210-validated CEF processes raised `MemAvailable` from roughly 0.9 to
2.5 GiB and free swap from 0.33 to 3.16 GiB. The launcher immediately began
reporting `Browser unavailable`, forced shutdown 14 seconds later, and then
reported GTA's exit code zero as a clean shutdown. Rockstar CEF must therefore
remain alive for this launch path; unloading it is not a safe memory fix.

This run reused the saved-login preservation and service/launcher CPU split
from Codex sessions `019ff310-e8ac-7212-9f2f-5ba9005b97bd` and
`019fe348-1247-7530-bc25-8a573aaf4252`. The required `deja "RockstarService
CPU6"` query returned no newly indexed match, so the retained session evidence
and new live measurements above were used directly.

### Supervised SSH recovery

The installed runit tree was already active, but `$PREFIX/var/service/sshd/down`
kept SSH outside supervision. `sv-enable sshd` removed that marker, and an
interactive `~/.bashrc` guard now starts `service-daemon` only when the exact
`runsvdir $PREFIX/var/service` process is absent, then calls `sv up` for the
SSH service. Killing the supervised listener with `TERM` caused an immediate
runit replacement and a new port-8022 connection succeeded. This protects an
ongoing diagnostic session from an `sshd` daemon exit; without Termux:Boot it
does not resurrect the whole Termux app after an Android force-stop or reboot.

### Foreground launch timing and the Rockstar transaction backlog

Action 8 kept Termux in Android's `top-app` group and preserved the saved
Rockstar login. `RockstarService`, the launcher, and GTA all started; GTA
reached the logo and selector while the service remained alive. Delaying the
selector input during diagnostics nevertheless let launcher service work queue
for 64-128 seconds. By the time the GTA IV Play choice was accepted, Social
Club initialization failed and the launcher later classified GTA's exit as a
clean shutdown. This separates the visible selector success from the online
service deadline.

Action 9 supplied the selector input helper in advance but began while the
Termux UID was already in `/cpuset/moderate`. Saved-login initialization never
reached `Went Online`: Rockstar transactions rose from 36.7 seconds to roughly
180 seconds even though the service, Wine server, launcher, and CEF processes
all remained alive. Expanding launcher/CEF affinity from CPUs 1-2 to every
available moderate CPU (0-2) and closing the Steam UI recovered about 1 GiB of
`MemAvailable`. Physically foregrounding Termux later drained most accumulated
transactions from about 214 to 36 seconds, but one transaction remained blocked
for more than 1,223 seconds and saved-login initialization still did not reach
`Went Online`. The launch should begin while Termux is visible; foregrounding
after a backlog forms can help but is not a dependable recovery mechanism.

At the measurement point, nine Steam webhelpers held only about 85 MiB resident
while four Rockstar CEF processes held about 765 MiB. This confirms two separate
facts: Steam UI can be hidden after dispatch for useful headroom, but Rockstar
CEF must not be terminated because it is part of the live launcher contract.

### Action 10: repeat main-menu transition, loading I/O, and whole-app eviction

Action 10 began with Termux physically in Android's `/top-app` group and kept
the saved Rockstar prefix unchanged. The launcher completed `Auth ->
MainWindow`, `Went Online`, cloud synchronization, and game dispatch without
another 2FA prompt. `GTAIV.exe` PID 23488 appeared five seconds after the
launcher requested the game, built a 57-thread process, and exposed the exact
fullscreen X11 window `GTAIV`, class `steam_app_12210`, at 2800x1586. Captures
showed the legal screen, title logo, and GTA IV/EFLC selector while
`RockstarService.exe` remained alive.

A fixed-coordinate Windows ARM64 PE was tested only after external validation
of the exact title, PID, class, and geometry. Wine returned status 5, the X11
cursor remained at the top-left corner, and the selector frame did not change,
so that helper was rejected and is not retained. The focused selector already
had GTA IV's Play choice highlighted. One XTest Return press/release sent with
`xdotool` changed the next captured frame to the real GTA IV main menu; a second
validated Return on the highlighted `Start` item entered the animated loading
art. This repeat run therefore confirms that XTest keyboard input can reach
this game state even though earlier synthetic mouse and key attempts were not
accepted. Exact window validation and following-frame evidence remain required.

The loader remained active at 57 threads and increased process read I/O from
about 877 MiB to 1.39 GiB while cycling through distinct loading frames. Memory
pressure, not a fixed launcher timeout, then became the limiting failure.
Required Rockstar CEF could not be removed. Terminating only exact
`steamwebhelper` processes temporarily raised free swap from 38 MiB to roughly
530 MiB, but native Steam respawned nine helpers, recreated its UI, stole X11
focus, and minimized GTA. Mapping and activating the exact GTA window restored
the still-running loader each time. Closing Steam's UI through
`WM_DELETE_WINDOW` did not prevent that respawn. A reversible `SIGSTOP` attempt
on Steam core did not take effect through PRoot's ptrace supervision, so Steam
core was never killed.

Immediately before the final loss, `/proc/meminfo` reported only 96 KiB of free
swap while GTA and Rockstar Service were alive and GTA's I/O was still
advancing. Twenty seconds later port 8022 refused connections twice; runit's
verified sshd supervision did not recover it. This is consistent with Android
evicting the whole Termux UID under exhausted memory, beyond the reach of an
in-app service supervisor. It is not evidence of the prior hypothesized
`start-kde` timeout. The next run should reduce the persistent Steam UI memory
contract before dispatch rather than repeatedly killing helpers after GTA has
started.

This run reused the authenticated-launch and CPU-affinity findings from Codex
sessions `019ff310-e8ac-7212-9f2f-5ba9005b97bd` and
`019fe348-1247-7530-bc25-8a573aaf4252`. The exact Nintendo Switch session
`a1837cd4-ab7b-411b-a83f-6e900a7ed053` was recalled to check the remembered
Steam-unload command; its recorded mechanism was direct `steam.pipe` launch,
not unloading Steam. The required `deja` queries for the selector and
`SIGSTOP` experiment returned no additional indexed matches.

### Action 14: lean launch, saved authentication, and first-mission start

The next launch retained Termux:X11, KWin, and PulseAudio but stopped Plasma
shell and its unrelated background services. Steam reused its saved login and
was started with `STEAM_ENABLE_SHADER_CACHE_MANAGEMENT=0` and `-noshaders`.
The prior Vulkan preprocessing dialog and its repeatedly growing 96-percent
queue did not return. Native Steam still registered the official ARM64 Proton
11 and Steam Linux Runtime 4 tools, then dispatched App 12210 through the same
validated executable view and Pressure Vessel route.

Termux:X11 initially left the Termux UID in `/cpuset/moderate`, CPUs 0-3.
Rockstar's first service transactions reached 31-64 seconds even though its
HTTP requests returned 200. Bringing `com.termux/.app.TermuxActivity` forward
through `am start` moved the live UID to `/cpuset/top-app`, CPUs 0-7, without
restarting X, Wine, or Steam. A live process-local split kept Steam UI on CPUs
0-3, launcher/Wine on 4-5, Rockstar Service on 6, and the outer PRoot tracer on
7. Rockstar then logged `Social Club UI has started`, `Client is ready to
attempt a launch`, completed cloud synchronization, and launched the real
`GTAIV.exe`. Cached authentication completed without another password or 2FA
challenge.

The game exposed the normal 2800x1586 fullscreen X11 surface. The installed
executable-view `commandline.txt` was simultaneously verified as the exact
24-byte repository file containing `-width 1280` and `-height 720`; the large
surface was therefore fullscreen scaling, not a return to native internal
rendering. Alternating short nonvisual `top-app` bursts with X11 checks moved
GTA from 27 to 40 and then 59 threads. Exact active-window validation followed
by untargeted native XTest Return events crossed the highlighted selector into
the main menu and selected `Start`. GTA's own legacy prompt then reported that
it was not currently signed in and offered `Enter` for Yes. One validated
Return accepted that choice, after which the rotating loading art began.

Memory remained the limiting resource. At the first danger point only about
150 MiB of swap was free. One exact Steam `steamwebhelper` zygote held roughly
406 MiB, mostly swap; normal `TERM` left only a zombie and raised free swap to
about 736 MiB without terminating Steam core or any Rockstar process. GTA
continued from roughly 756 MiB to 1.47 GiB of process read I/O while its
loading frames changed. Rockstar CEF remained alive throughout because the
earlier controlled test proved that removing it terminates the game.

At 09:36 PDT the composed frame changed from loading art to the first-mission
title **The Cousins Bellic**. The privacy-safe 2800x1586 frame is retained as
`docs/evidence/gtaiv-new-game-2026-08-14.png`, SHA-256
`21c8f78fdee83ee3765be5fd8ac21324ac39cbc4b778c5aecd94c0b15e4c4762`.
This is proof that a new game started, beyond the previous main-menu/loading
milestones; it is not yet proof of interactive control after the opening
transition.

A second capture attempt overlapped the next whole-Termux loss. The final
successful sampler record immediately beforehand still showed about 532 MiB
`MemAvailable`, 674 MiB free swap, active GTA CPU, and advancing reads. X11,
GTA, and SSH then all disappeared and runit could not restore SSH. This does
not support a conventional kernel OOM at the final sample, but it is consistent
with Android evicting the background Termux UID under sustained memory
pressure before Linux exhausts RAM and zram. The capture overlap remains a
correlation, not a proven cause; future high-pressure transitions should avoid
captures and keep Termux foregrounded until loading completes.

This action reused the saved-login, foreground-component, and affinity
findings from Codex sessions `019ff310-e8ac-7212-9f2f-5ba9005b97bd` and
`019fe348-1247-7530-bc25-8a573aaf4252`. The required `deja` searches for the
new combined eviction signature returned no additional indexed match.

### Bounded SSH cold-start supervision

After the Action 14 whole-UID loss, opening Termux created the Android app,
interactive `bash -l`, `runsvdir`, the `sshd` service supervisor, and the
supervised listener within roughly one second. The listener's parent was the
exact `runsv sshd` process and the service log recorded both IPv4 and IPv6 port
8022 listeners. This shows the existing profile path did run; a manually typed
standalone `sshd` command was redundant on that recovery.

The fallback still contained a race: both Termux's stock profile and `.bashrc`
backgrounded `service-daemon`, while `.bashrc` immediately called `sv up` and
silently ignored a failure before `runsvdir` was ready. The repository now
installs `~/bin/ensure-sshd-supervised`. It validates the exact service tree,
starts `service-daemon` without another backgrounding layer when needed, waits
at most ten seconds for the exact `runsvdir` argument pair, calls bounded
`sv up`, and requires the final status to begin with `run:`. The tablet's
`.bashrc` calls this helper and retains a mode-preserving backup of the prior
guard.

A live verification sent normal `TERM` only to the exact `sshd` child of the
validated `runsv sshd` supervisor. Runit replaced listener PID 4034 with PID
5567 in under one second; a new port-8022 connection and a second helper call
both succeeded. This verifies daemon-crash recovery and removes the startup
race. It still cannot resurrect an Android-evicted Termux app until an external
event opens Termux.
