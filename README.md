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
- The ARM64 Pressure Vessel path now passes an end-to-end `/bin/true` smoke
  test with a clean, repository-built PRoot. The fixes normalize `.l2s`
  directory-entry metadata, force Pressure Vessel's copy fallback only inside
  its private mutable-runtime prefix, preserve real symlink behavior, and
  emulate Bubblewrap's bind/pivot sequence through its final root switch.
- A prepared runtime shadow keeps the official App ID and platform payload but
  supplies the hash-identical real-file ARM64 Pressure Vessel bundled in
  conventional Runtime 4. A narrow outer PRoot bind exposes the shadow at the
  App-ID path Steam computes, without changing the installed ARM64 depot or its
  appmanifest, and gives mutable runtime copies their own private `var`
  directory.
- Burnout has not yet been proven on screen. The next confirmed boundary is
  Proton/FEX startup, followed by the EA App, DXVK, and Turnip game path.

This is a precise, continuable engineering record, not yet a one-command finished
installer.

## Repository map

- `bin/steam-arm` — isolated launcher used on the tablet.
- `bin/patch-steam-network-ui.sh` — version-specific Steam UI API guard.
- `bin/lsof` — narrowly scoped Android `/proc/net` compatibility shim.
- `config/steam-arm64-compatibilitytools.vdf.in` — local registrations for the
  official ARM64 Proton and runtime payloads.
- `patches/proot-steam-android.patch` — exact custom PRoot changes.
- `patches/proot-link2symlink-*.patch`, `patches/proot-pivot-*.patch`, and
  `patches/proot-runtime-bind-exact-detranslate.patch` — focused Pressure
  Vessel/Bubblewrap compatibility fixes.
- `scripts/build-proot.sh` — reproducibly rebuilds patched PRoot.
- `scripts/prepare-arm64-runtime-shadow.sh` — non-destructively prepares the
  official ARM64 runtime for PRoot's mutable-runtime copy path.
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
