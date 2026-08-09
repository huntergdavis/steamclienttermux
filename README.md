# Steam ARM64 on Termux/X11

Reproducibility project for running Valve's conventional native ARM64 Steam
client on an unrooted Samsung Galaxy Tab S9+ (Snapdragon 8 Gen 2 / Adreno 740),
inside Debian under Termux PRoot and displayed by Termux:X11/KDE.

## TL;DR: what was actually required

The surprising result is that **the native ARM64 Steam client itself was not the
main problem**. Valve's ARM64 client runs on the tablet's CPU, and Turnip can
drive the Adreno 740. The critical blocker was the Linux process environment
Steam expects versus the one an unrooted Android app receives through PRoot.

Steam depends on Linux System V IPC and thread-runtime behavior during startup.
Stock Termux PRoot did not emulate enough of that behavior for Steam:

- Android's app seccomp policy blocks the normal `set_robust_list` path used by
  glibc threading, so PRoot needed per-tracee emulation of `set_robust_list` and
  `get_robust_list`.
- PRoot's SysV semaphore emulation lacked behavior Steam relies upon, including
  `SETALL`, `GETPID`, `GETNCNT`, and `GETZCNT`.
- Updating semaphore values did not wake blocked `semop` waiters as Linux does,
  leaving Steam processes deadlocked during startup.
- Existing diagnostics did not reveal which translated child crashed, so the
  patched PRoot gained opt-in signal/register/memory-map crash reporting and
  detailed SysV IPC tracing.

That custom PRoot patch was the foundational fix. It is preserved exactly in
[`patches/proot-steam-android.patch`](patches/proot-steam-android.patch).

Once Steam could survive process startup, four secondary Android/Termux
compatibility problems remained:

1. Steam's auto-created D-Bus daemon inherited an updater pipe and delayed
   startup by about five minutes. Starting a private session bus first fixed it.
2. CEF GPU compositing produced stale/flickering Termux:X11 surfaces with broken
   hit testing. The Steam HTML UI had to use software rendering, while games
   retained Turnip Vulkan acceleration.
3. Android hides TCP ownership data in `/proc/net`. Steam's loopback WebSocket
   verification therefore needed a narrowly scoped `lsof` compatibility shim,
   plus IPv4-only localhost resolution for the Steam container.
4. This ARM64 Steam UI build called absent network bridge methods. Three guarded
   feature checks in one minified UI chunk allowed the library/store UI to load.

Finally, Steam's file preallocation was disastrously slow through ptrace PRoot,
so `-chromeosnopreallocate` was needed for practical downloads. Runaway CEF
debug streams also required a launcher-level log guard after they consumed about
25 GiB. The launcher also uses `-noverifyfiles`: Steam still checks for client
updates, but it does not replace the intentional, version-specific UI guard on
every start.

In short:

```text
Native ARM64 Steam + Debian/glibc
  + patched PRoot robust-list and SysV IPC semantics
  + private D-Bus session
  + CEF software UI / Turnip game rendering split
  + Android loopback ownership shim and UI feature guards
  = conventional Steam client running and downloading on unrooted Android
```

No root, custom kernel, chroot, or replacement Linux desktop was required to
reach the working Steam client and completed game downloads.

This repository records the working client bring-up completed on 2026-08-07
and the disk-exhaustion fix added on 2026-08-08. It contains our launch code,
compatibility shims, diagnostic programs, exact PRoot source patch, inventory,
selected logs, and visual evidence. It deliberately does **not** contain Valve
client binaries, games, Proton payloads, credentials, or Mesa binaries.

## Current status

- Native Linux ARM64 Steam client launches and authenticates.
- Steam's HTML interface renders under Termux:X11 using CEF software rendering.
- The native ARM64 client uses a private Mesa Turnip Vulkan stack for games.
- Burnout Paradise Remastered and Proton 11.0 (ARM64) downloaded completely.
- Steam Linux Runtime 4.0 - Arm64 is the required companion runtime; the
  conventional x86-64 Runtime 4 cannot execute directly in this environment.
- The launcher registers both official ARM64 payloads as local compatibility
  tools under the Steam client root. Steam has confirmed internal keys
  `proton_11_arm64_official` and `steamlinuxruntime_4_arm64_official` for App
  IDs 4628740 and 4185400 respectively.
- A complete registry pass posted both ARM64 registration callbacks. Steam
  resolved Proton 11 through `SteamLinuxRuntime_4-arm64`, not the conventional
  x86-64 Runtime 4.
- Burnout now has an explicit `CompatToolMapping` to
  `proton_11_arm64_official` at priority 250. A subsequent start accepted that
  mapping; it outranks the automatic Proton Experimental mapping at priority
  100.
- Burnout's first explicitly mapped launch used the official ARM64 runtime and
  Proton commands, including the expected `link2ea://` target.
- The production mount-stack PRoot fix clears the former shared-`/tmp` X0
  blocker on Steam's real launch path. Official Proton 11 ARM64 reached its
  Python entry point, created/upgraded the prefix, and started native ARM64
  Wine plus the bundled FEX bridge. This is confirmed process and log evidence,
  not an inference from tool registration.
- Burnout's DirectX June 2010 prerequisite completed successfully. The EA App
  is installed, its background service is registered with a 60-second startup
  allowance, and an isolated direct Link2EA session authenticated the linked
  Steam/EA account, started EA Desktop and LocalHost, and completed all four
  Visual C++ prerequisites. This proves the EA setup path, not game rendering.
- Steam's normal DXVK command crashes Link2EA before its logger or UI starts.
  The terminal fault is a jump to `0x6ff9340000`, the base of the official
  Proton 11 ARM64 DXVK `windows/system32/d3d11.dll` copied into the prefix.
  The return address is immediately after the DLL's ARM64EC `#memmove` import
  call. The imported-call thunk supplies image RVA zero as its exit thunk, so
  Wine's ARM64EC dispatch can reproduce the exact image-base target when the
  imported function is classified as non-EC. A live IAT read is still needed
  to prove the precise loader/classification defect.
- Turning off Burnout's per-game overlay checkbox set `SteamNoOverlayUI=1` but
  did not remove Steam's three `gameoverlayrenderer.so` preloads and did not
  change the fault. A second launch with the installed Pressure Vessel's
  supported `PRESSURE_VESSEL_REMOVE_GAME_OVERLAY=1` switch did remove every
  downstream overlay preload; Link2EA nevertheless reproduced the identical
  `d3d11.dll` fault. Overlay injection is therefore not the cause.
- A backed-up canonical `PROTON_USE_WINED3D=1` isolation launch replaced both
  prefix DLLs with Proton's hash-identical ARM64 Wine built-ins and eliminated
  the DXVK image-base crash. That launch started Link2EA, authenticated the
  linked account, started EA Background Service, EA Desktop, LocalHost, and CEF,
  and handed the App ID 1238080 request to EA Desktop. EA then stalled in
  `offlineAwaitingAuth`: its DirtySDK connectivity detector timed out even
  though Linux-side DNS/TLS requests to the same EA endpoints succeeded. No EA
  window or `BurnoutPR.exe` has appeared. WineD3D is diagnostic isolation, not
  the final Turnip/DXVK solution. The test was stopped through Steam, all EA and
  Wine processes exited, and Steam itself remained healthy. The current live
  launch options deliberately retain `PROTON_USE_WINED3D=1` plus
  `PRESSURE_VESSEL_REMOVE_GAME_OVERLAY=1` for the controlled network retest.
- A credential-free native ARM64 Windows probe isolated the EA offline state
  to Android's protected `/proc/net/route`. Proton Wine maps that read failure
  to `GetAdaptersAddresses` error 50, so Network List Manager reports
  disconnected even though unicast addresses and HTTPS work. With a measured,
  read-only route shadow bound at `/proc/net`, the same probe changes from zero
  adapters/NLM disconnected to three adapters/NLM IPv4 Internet. The launcher
  prepares that shadow from validated tablet network data.
- Pressure Vessel's `--proc /proc` covers the launcher's outer `/proc/net`
  bind. A narrow wrapper now validates and opens the private shadow, inserts an
  `srt-bwrap --ro-bind-fd` immediately after the final proc mount, and passes
  all other arguments through. A matching PRoot correction preserves the
  literal target of directory mounts instead of resolving `/proc/net` to a
  Bubblewrap-process-specific `/proc/<pid>/net` path.
- An isolated end-to-end probe using the corrected PRoot, hardened wrapper,
  official Steam Linux Runtime 4 ARM64, official Proton 11 ARM64, and an
  initialized credential-free prefix returned three adapters, five unicast
  rows, WinINet connected flags `0x12`, and NLM IPv4 local/Internet
  connectivity `0x60`. This proves the network fix across the actual container
  boundary.
- The validated route-preservation checkpoint (`1ebd14f`), including its
  native-Termux test fallbacks (`a12d9f4` and `a1d8f61`), is now deployed. The
  live production PRoot has SHA-256
  `0378e0631dbf7a8bd0061b54fc167bb881c70a76109f567b682f7262a063166c`;
  the route-wrapper SHA-256 is
  `6ba0a5f0ed955439efb220ea64d267b96cc3f6a1e7ee390f17be175990c39f7a`.
  Steam restarted under outer PRoot PID 13620 and Steam PID 13625 with the
  exact wrapper, real ARM64 `srt-bwrap`, and private `/proc/net` shadow in its
  live environment.
- At 14:46:33 Steam registered both official ARM64 tools and retained Burnout's
  priority-250 `proton_11_arm64_official` mapping. The second cache-off pass
  completed at 15:15:49, after rejecting the automatic priority-100
  `proton-experimental` mapping. A live launch then used only
  `SteamLinuxRuntime_4-arm64` and `Proton 11.0 (ARM64)`.
- The deployed route fix cleared the former EA offline blocker. EA reached its
  online state, authenticated through Steam, linked the account, connected its
  local service, and reported a successful Link2EA launch. Burnout's executable
  started through Proton's bundled FEX/WoW64 path for the first time. This was
  a diagnostic WineD3D run, not the final DXVK/Turnip configuration.
- A clean retest with PRoot crash tracing disabled again completed EA's Steam
  authentication and license exchange. EA's CEF surface displayed **Couldn't
  connect to servers** while the background service remained online and
  authenticated, so the visible network error is a frontend CEF failure rather
  than a return of the `/proc/net/route` blocker.
- Burnout then opened an exact `CPU Error` dialog claiming that SSE2 was
  missing. FEX does expose SSE2; Burnout incorrectly tests CPUID leaf 1 EDX bit
  2 (Debugging Extensions). Proton 11 ARM64 pins FEX commit
  `a04b0241c2fe3911729842205cd8643981108aad`, which predates FEX's merged
  compatibility fix `9365e6240b3b87466753cd989d257e5c93092578`. FEX issue
  [#5805](https://github.com/FEX-Emu/FEX/issues/5805) and merged pull request
  [#5807](https://github.com/FEX-Emu/FEX/pull/5807) cover this exact Burnout
  error. Proton's generated FEX configuration cannot add that CPUID bit, so
  there is no launch-option workaround. The production-safe resolution is an
  official Proton 11 ARM64 update containing that FEX fix; the Steam-managed
  Proton payload has not been modified in place.
- This milestone is not gameplay success. The current controlled run still uses
  WineD3D, no managed Burnout gameplay window exists, and no DXVK/Turnip frame
  has been captured.
- `PROOT_CRASH_LOG` is now opt-in. Proton 11's bundled FEX deliberately handles
  SIGBUS for unaligned guest atomics in JIT code, so the previous production
  default turned a normal hot path into 59,989 register/procfs diagnostic
  dumps. Use `PROOT_CRASH_LOG=1 ~/bin/steam-arm` only for bounded debugging.
- Every X11 evidence capture now uses a stable, validated window and a short
  timeout. A previous unbounded ImageMagick helper demonstrated that a stale X
  server grab can invalidate an EA launch attempt.
- The ARM64 Pressure Vessel path now passes an end-to-end `/bin/true` smoke
  test with a clean, repository-built PRoot. The fixes normalize `.l2s`
  directory-entry metadata, force Pressure Vessel's copy fallback only inside
  its private mutable-runtime prefix, preserve real symlink behavior, and
  emulate Bubblewrap's bind/pivot sequence through its final root switch. The
  latest isolated build also preserves covered runtime mounts, allowing
  Bubblewrap to reach the shared Termux `/tmp` below its staging tmpfs.
- A prepared runtime shadow keeps the official App ID and platform payload but
  supplies the hash-identical real-file ARM64 Pressure Vessel bundled in
  conventional Runtime 4. A narrow outer PRoot bind exposes the shadow at the
  App-ID path Steam computes, without changing the installed ARM64 depot or its
  appmanifest, and gives mutable runtime copies their own private `var`
  directory. Preparation now fails closed if donor, staged, or existing shadow
  scans fail or contain any `.l2s` pseudo-hardlink symlink.
- Burnout gameplay has not yet been proven on screen. Proton/FEX/Wine, DirectX,
  EA installation, account authentication, license response, and game-process
  startup are confirmed. The WineD3D isolation path now stops at the exact FEX
  CPUID compatibility bug above. After an official FEX-bearing Proton update,
  the separate DXVK ARM64EC dispatch fault remains to be solved before the
  final Turnip path can be claimed.

This is a precise, continuable engineering record, not yet a one-command finished
installer.

## Repository map

- `bin/steam-arm` — isolated launcher used on the tablet.
- `bin/patch-steam-network-ui.sh` — version-specific Steam UI API guard.
- `bin/prepare-proc-net-shadow.sh` — validates the active Termux network and
  prepares the minimal route snapshot required by Wine's IP Helper APIs.
- `diagnostics/pressure-vessel-route-bwrap.c` — validates the route snapshot
  and re-injects it by inherited directory FD after Pressure Vessel mounts its
  private procfs.
- `diagnostics/cpuid-probe/` — source-only Windows AMD64 probe for raw CPUID
  and Win32 SSE/SSE2 feature reporting under FEX.
- `bin/lsof` — narrowly scoped Android `/proc/net` compatibility shim.
- `config/steam-arm64-compatibilitytools.vdf.in` — local registrations for the
  official ARM64 Proton and runtime payloads.
- `patches/proot-steam-android.patch` — exact custom PRoot changes.
- `patches/proot-link2symlink-*.patch`, `patches/proot-pivot-*.patch`, and
  `patches/proot-runtime-*.patch` — focused Pressure Vessel/Bubblewrap
  compatibility fixes.
- `scripts/build-proot.sh` — reproducibly rebuilds patched PRoot.
- `scripts/probe-proot-bwrap-proc-net-bind.sh` — proves the real PRoot and
  `srt-bwrap --ro-bind-fd` lifecycle across a sandbox child process.
- `scripts/probe-proot-bwrap-*.sh` — bundled ARM64 Bubblewrap regression
  probes for spaced paths and shared-`/tmp` mount underlays.
- `scripts/prepare-arm64-runtime-shadow.sh` — non-destructively prepares the
  official ARM64 runtime for PRoot's mutable-runtime copy path.
- `scripts/run-ea-link2ea-direct.sh` — guarded diagnostic that runs the
  installed Link2EA URI through official ARM Runtime 4 and Proton; it refuses
  to collide with an active wineserver and is not a replacement game launcher.
- `scripts/build-win-network-status-probe.sh` and
  `diagnostics/win-network-status-probe.c` — build the credential-free ARM64
  Windows probe used to compare Wine IP Helper/NLM behavior with and without
  the Android route shadow.
- `scripts/install-project-files.sh` — installs only this project's files.
- `scripts/inventory.sh` and `scripts/verify-gpu.sh` — diagnostics.
- `docs/TECHNICAL_LOG.md` — chronological fault/fix record.
- `docs/ARCHITECTURE.md` — component and library-boundary explanation.
- `docs/inventory/`, `docs/logs/`, and `docs/evidence/` — captured evidence.
- `probes/` — focused C and Python diagnostics used during PRoot investigation.

## Observed working versions

- Debian 13 (`trixie`) PRoot container
- ARM64 Steam build ID `1785799196`
- Mesa `26.2.0-devel (git-9452d1daec)` Turnip build
- Vulkan ICD API version `1.4.335`
- Termux PRoot base commit `a89b3732ec6ae1db674510f0843b2f3db54d0a2f`

## Reproduction outline

1. Establish a working accelerated Termux:X11/KDE session first.
2. Install Debian with `proot-distro` and verify X11 and PulseAudio access.
3. Run `scripts/inventory.sh` and archive its output before making changes.
4. Build patched PRoot with `scripts/build-proot.sh`.
5. Place compatible ARM64 Steam and private Turnip payloads in the paths listed
   in `docs/PROPRIETARY_AND_BINARY_INPUTS.md`.
6. Run `scripts/prepare-arm64-runtime-shadow.sh` after both official Runtime 4
   depots are installed.
7. Run `scripts/install-project-files.sh`.
8. Run `scripts/verify-gpu.sh`, then launch `~/bin/steam-arm` from KDE.

Read the technical log first. Several fixes are Android-sandbox and Steam-build
specific.

## Safety

The scripts do not root, unlock, flash, repartition, replace KDE, or globally
change library paths. Installation is confined to `~/steam-arm64`, `~/bin`, and
the user's desktop-entry directory. Existing destination files are backed up.
