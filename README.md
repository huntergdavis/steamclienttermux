# Steam ARM64 on Termux/X11

Run Valve's conventional native ARM64 Linux Steam client on an **unrooted**
Samsung Galaxy Tab S9+ using Termux, Debian PRoot, Termux:X11/KDE, Mesa Turnip,
official Proton 11 ARM64, and its bundled FEX/DXVK stack.

![GTA IV main menu running through Proton ARM64, FEX, DXVK, and Turnip](docs/evidence/gtaiv-main-menu-2026-08-13.png)

![Superflight fullscreen through Proton ARM64, FEX, DXVK, and Turnip](docs/evidence/superflight-fullscreen.png)

## Current status

- Native ARM64 Steam launches, authenticates, renders its UI, and downloads
  games.
- Turnip provides Vulkan acceleration on the Snapdragon/Adreno GPU.
- Official Proton 11 ARM64 and Steam Linux Runtime 4 ARM64 are registered and
  launch through the correct ARM64 paths.
- Superflight runs fullscreen through FEX, Wine, DXVK, and Turnip with working
  PulseAudio output.
- An optional microSD library keeps Windows game depots external while Proton,
  runtimes, active downloads, and per-game compatdata remain on internal F2FS.
  Kingsway runs fullscreen with audio through this split route.
- GTA IV is installed on the microSD, completes Rockstar authentication and
  online presence, launches the real `GTAIV.exe`, passes the GTA IV/EFLC
  selector, and renders the GTA IV main menu through official ARM Proton/FEX
  and Turnip. Saved authentication survived a full X/KDE/Steam recovery and no
  additional 2FA was required. Gameplay beyond the main menu is not yet
  verified.
- Burnout remains experimental; its detailed EA, FEX, and DXVK investigation is
  kept in [`docs/TECHNICAL_LOG.md`](docs/TECHNICAL_LOG.md), not duplicated here.

![Kingsway running from the microSD through Proton ARM64 and FEX](docs/evidence/kingsway-running.png)

## What changed

### Recompiled PRoot

Stock PRoot was not sufficient for Steam and Pressure Vessel. The repository
rebuild applies narrowly scoped fixes for:

- glibc robust-list calls blocked by Android seccomp;
- System V semaphore operations and waiter wakeups used by Steam;
- Pressure Vessel's `.l2s` metadata, bind mounts, pivot sequence, and shared
  `/tmp` behavior;
- the private `/proc/net` route view required by Wine's Windows networking APIs.

The source is pinned and rebuilt by:

```sh
scripts/build-proot.sh
```

The build is stamped with the source commit, ordered patch-set hash, source-diff
hash, and binary hash. The exact patches live under [`patches/`](patches/).

### Hardened the Steam launcher

[`bin/steam-arm`](bin/steam-arm) now prepares a completely user-local runtime:

- private Debian/glibc, D-Bus, Mesa/Turnip, and Steam paths;
- ARM64 compatibility-tool registration and traditional Steam SDK symlinks;
- stable software-rendered CEF while games retain Vulkan acceleration;
- Android loopback/network compatibility shims;
- canonical PulseAudio TCP setup;
- bounded session logs, `/dev/null` guards for runaway CEF logs, and a 1 GiB
  free-space floor.

It does not replace global library paths or modify the existing KDE/Mesa setup.

### Tuned Superflight

[`scripts/configure-superflight-performance.py`](scripts/configure-superflight-performance.py)
applies a backup-first, atomic Unity profile: fullscreen 1280x720, quality zero,
and antialiasing, motion blur, post-processing, and shadows disabled.

The game initially pinned all 72 observed Unity/DXVK threads to CPUs 0-3. On
this tablet those are the lower-capacity cores. The guarded
[`scripts/set-superflight-affinity.py`](scripts/set-superflight-affinity.py)
validates the game/App ID and the measured CPU topology before moving all game
threads to CPUs 4-7. In the same menu scene, observed game CPU use fell from
about 157% to 97%, and play felt noticeably smoother. This affinity is
process-local and must currently be applied after each launch.

### Reached the GTA IV main menu

GTA IV now passes the Rockstar boundary that previously ended at CEF Code 17.
The working checkpoint combines four narrowly scoped pieces:

- the Pressure Vessel route wrapper validates a private internal copy of GTA
  IV's executable files, overlays it at the normal game path, and keeps the
  large game-data directories on the microSD;
- the initial `PlayGTAIV.exe` payload is changed to a service-first batch that
  starts `Rockstar Service` before handing control back to the signed game
  launcher;
- Wine's service startup timeout is raised to 60 seconds; and
- only `SocialClubHelper.exe` receives Wine's builtin D3D11/DXGI renderer,
  leaving the game itself on its accelerated D3D9/Vulkan route.

The validated online runs logged `Auth -> MainWindow`, `Presence Event - Signed
In`, and `Presence Event :: Went Online`. Rockstar then launched the genuine
`GTAIV.exe`; X11 reported a focused fullscreen `GTAIV` window and the rendered
frame first showed the GTA IV/EFLC selector. A fresh run reproduced the launch
without another 2FA prompt and then passed the selector into the real GTA IV
main menu. The exact 2800x1586 composed frame shows `Start` selected, the GTA IV
title art, and the connected Social Club panel. Gameplay beyond this menu is
not yet claimed.

The internal executable view and the service-first batch are still an
experimental, machine-specific setup. The wrapper validates their exact file
set and ownership instead of silently creating them. With the prefix stopped,
the two registry changes are reproduced by:

```sh
system_reg="$HOME/steam-arm64/removable-library-compatdata/12210/pfx/system.reg"
scripts/configure-gtaiv-service-timeout.py \
  --registry "$system_reg" --backups-dir "$HOME/steam-arm64/backups" \
  --expected-sha "$(sha256sum "$system_reg" | awk '{print $1}')"
scripts/configure-gtaiv-socialclub-wined3d.py \
  --base "$HOME/steam-arm64" --enable
```

Both tools refuse unsafe registry shapes, preserve byte-verified backups, use
atomic replacement, and refuse changes while Wine/Proton/container processes
are active.

## Reproduce

Read [`docs/PROPRIETARY_AND_BINARY_INPUTS.md`](docs/PROPRIETARY_AND_BINARY_INPUTS.md)
for the required external Steam, Proton, runtime, and Mesa payloads. They are
not stored in this repository.

```sh
scripts/inventory.sh
scripts/build-proot.sh
scripts/prepare-arm64-runtime-shadow.sh
scripts/install-project-files.sh
scripts/verify-gpu.sh
~/bin/steam-arm
```

In Steam, explicitly force Superflight (App ID 732430) to use Proton 11.0
(ARM64), and set this launch option for audio:

```text
PULSE_SERVER=tcp:127.0.0.1:4713 %command%
```

With Steam and Wine stopped, apply the graphics profile:

```sh
scripts/configure-superflight-performance.py --base "$HOME/steam-arm64"
scripts/configure-superflight-performance.py --base "$HOME/steam-arm64" --check
```

After Superflight starts, apply and verify the confirmed live affinity:

```sh
scripts/set-superflight-affinity.py
scripts/set-superflight-affinity.py --check
```

With Steam fully stopped, prepare and register the removable Windows-game
library before the next Steam start:

```sh
bin/steam-arm64-removable-library.py --base "$HOME/steam-arm64" prepare
bin/steam-arm64-removable-library.py --base "$HOME/steam-arm64" register
scripts/install-project-files.sh
```

`register` makes a byte-verified backup before atomically adding the library to
Steam's `libraryfolders.vdf`, and refuses to run while Steam or Wine is active.
Use this library only for Windows game depots. The launcher keeps Steam's
`steamapps` control metadata internal, binds only `steamapps/common` to the card,
and uses dedicated internal compatdata and active-download directories. Android's
portable-storage FUSE does not implement the file locks Steam needs for manifests
or patch state. The launcher fails early if the card is absent or the layout is
unsafe.

Large depots can make Steam's cross-filesystem commit path spend seconds per
file under PRoot. With Steam stopped, copy one numeric `downloading/<appid>`
tree to `<microSD-library>/staging/<appid>`, generate matching relative-path
SHA-256 manifests for both trees, then enable the verified nested bind:

```sh
bin/steam-arm64-removable-library.py --base "$HOME/steam-arm64" \
  enable-staging-bind 12210 --source-manifest source.sha256 \
  --target-manifest target.sha256
```

Patch-state files remain internal and lock-safe; only the verified numeric
payload tree is overlaid, making the final commit a same-filesystem rename.
If Steam's own commit still stalls on per-file PRoot metadata, stop Steam and
run the manifest-gated native merge:

```sh
bin/steam-arm64-removable-library.py --base "$HOME/steam-arm64" \
  commit-staging 12210 --install-dir "Grand Theft Auto IV" \
  --manifest source.sha256
```

The internal staging tree stays hidden as a temporary recovery copy. Keep it
only until Steam has restarted and retained `StateFlags 4` and
the target build. If the native merge bypassed Steam's final metadata write,
run the offline `finalize-staging` action with one `--depot-manifest` argument
for each current cached depot manifest; it validates their embedded IDs and
sizes before backing up and atomically completing the appmanifest. The exact
GTA IV example is in [`docs/TECHNICAL_LOG.md`](docs/TECHNICAL_LOG.md). After a
verified restart, the redundant internal numeric App-ID tree can be removed
with Steam stopped and its empty mountpoint recreated.

GTA IV's signed depot metadata currently spells its installscript path with a
Windows separator that native Linux Steam cannot enumerate on Android's
portable-storage filesystem. With no Wine, Proton, or game container running,
apply the signed script's two registry entries using the hash- and
mapping-guarded helper:

```sh
scripts/configure-gtaiv-registry.py --base "$HOME/steam-arm64" \
  --installscript "/storage/7376-B000/Android/data/com.termux/files/steam-arm64-library/steamapps/common/Grand Theft Auto IV/GTAIV/installscript.vdf"
```

The helper verifies the exact signed VDF, `S:` mapping, and existing registry
state; it makes a byte-verified backup before an atomic `system.reg` update.

`WINE_CPU_TOPOLOGY=4:4,5,6,7` is a candidate for making the affinity persistent,
but it is intentionally not presented as confirmed until a clean launch proves
the same per-thread masks and performance.

## Validate the repository

```sh
for test_file in scripts/test-*.py; do
    PYTHONDONTWRITEBYTECODE=1 python3 "$test_file" || exit
done
```

The retained tests cover the launcher log guard, PulseAudio preparation,
Pressure Vessel route injection, Superflight settings and affinity, removable
storage, and GTA IV's signed registry, service timeout, and scoped Social Club
WineD3D state.

## Key paths

- [`bin/steam-arm`](bin/steam-arm) — production launcher.
- [`patches/`](patches/) — reproducible PRoot patch series.
- [`config/steam-arm64-compatibilitytools.vdf.in`](config/steam-arm64-compatibilitytools.vdf.in)
  — official ARM64 Proton/runtime registration.
- [`scripts/`](scripts/) — builds, installation, probes, and game tuning.
- [`docs/TECHNICAL_LOG.md`](docs/TECHNICAL_LOG.md) — full chronological evidence
  and unresolved diagnostics.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — component boundaries.

## Observed platform

- Samsung Galaxy Tab S9+, Snapdragon 8 Gen 2 / Adreno 740
- Debian 13 under Termux PRoot
- ARM64 Steam build `1785799196`
- Mesa Turnip `26.2.0-devel (git-9452d1daec)`
- PRoot base commit `a89b3732ec6ae1db674510f0843b2f3db54d0a2f`

No root, bootloader unlock, custom kernel, flash, chroot, or global Mesa/library
replacement is required.
