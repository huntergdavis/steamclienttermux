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
