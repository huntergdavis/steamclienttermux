# Steam ARM64 on Termux/X11

Reproducibility project for running Valve's conventional native ARM64 Steam
client on an unrooted Samsung Galaxy Tab S9+ (Snapdragon 8 Gen 2 / Adreno 740),
inside Debian under Termux PRoot and displayed by Termux:X11/KDE.

This repository records the working client bring-up completed on 2026-08-07
and the disk-exhaustion fix added on 2026-08-08. It contains our launch code,
compatibility shims, diagnostic programs, exact PRoot source patch, inventory,
selected logs, and visual evidence. It deliberately does **not** contain Valve
client binaries, games, Proton payloads, credentials, or Mesa binaries.

## Current status

- Native Linux ARM64 Steam client launches and authenticates.
- Steam's HTML interface renders under Termux:X11 using CEF software rendering.
- The native ARM64 client uses a private Mesa Turnip Vulkan stack for games.
- Burnout Paradise Remastered, Proton Experimental, and Steam Linux Runtime 4.0
  downloaded completely.
- Windows game execution is not yet demonstrated end-to-end. The remaining work
  is the x86/x86-64 guest execution layer and Proton launch integration.

This is a precise, continuable engineering record, not yet a one-command finished
installer.

## Repository map

- `bin/steam-arm` — isolated launcher used on the tablet.
- `bin/patch-steam-network-ui.sh` — version-specific Steam UI API guard.
- `bin/lsof` — narrowly scoped Android `/proc/net` compatibility shim.
- `patches/proot-steam-android.patch` — exact custom PRoot changes.
- `scripts/build-proot.sh` — reproducibly rebuilds patched PRoot.
- `scripts/install-project-files.sh` — installs only this project's files.
- `scripts/inventory.sh` and `scripts/verify-gpu.sh` — diagnostics.
- `docs/TECHNICAL_LOG.md` — chronological fault/fix record.
- `docs/ARCHITECTURE.md` — component and library-boundary explanation.
- `docs/inventory/`, `docs/logs/`, and `docs/evidence/` — captured evidence.
- `probes/` — focused C diagnostics used during PRoot IPC investigation.

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
6. Run `scripts/install-project-files.sh`.
7. Run `scripts/verify-gpu.sh`, then launch `~/bin/steam-arm` from KDE.

Read the technical log first. Several fixes are Android-sandbox and Steam-build
specific.

## Safety

The scripts do not root, unlock, flash, repartition, replace KDE, or globally
change library paths. Installation is confined to `~/steam-arm64`, `~/bin`, and
the user's desktop-entry directory. Existing destination files are backed up.

