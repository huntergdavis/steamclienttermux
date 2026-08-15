# Steam ARM64 on Termux/X11

Run Valve's conventional native ARM64 Linux Steam client on an **unrooted**
Samsung Galaxy Tab S8+ (SM-X808U) using Termux, Debian PRoot, Termux:X11/KDE,
Mesa Turnip, official Proton 11 ARM64, and its bundled FEX/DXVK stack.

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
  selector and main menu, completes the animated loading-art sequence, and
  starts the first mission, **The Cousins Bellic**, through official ARM
  Proton/FEX and Turnip. Saved authentication survived full X/KDE/Steam
  recovery and repeated launches without another 2FA prompt. Interactive
  control after the opening mission transition is not yet verified.
- Tomb Raider (2013) is installed on the microSD as the Windows depot set and
  launches the real `TombRaider.exe` through Steam Linux Runtime 4 ARM64,
  official Proton 11 ARM64, FEX, DXVK, and Turnip. Its launcher and first-run
  renderer both work. Its first built-in 1280x720 Low benchmark completed at
  5.8 minimum, 18.0 maximum, and 13.6 average FPS. The saved profile still had
  double-buffered V-Sync enabled, so this is a first-run baseline rather than a
  performance ceiling. See the
  [comparison and next-pass protocol](docs/TOMB_RAIDER_BENCHMARK.md).
- Burnout remains experimental; its detailed EA, FEX, and DXVK investigation is
  kept in [`docs/TECHNICAL_LOG.md`](docs/TECHNICAL_LOG.md), not duplicated here.

### Current benchmark target: Tomb Raider (2013)

Tomb Raider replaces the earlier planned Sleeping Dogs control for the first
measurement. It avoids GTA IV's separate Rockstar launcher, has named graphics
quality profiles and an integrated benchmark, and has now crossed the real
Windows executable boundary on this exact Tab S8+. The first completed pass
used its Low profile at fullscreen 1280x720, with game/X11 affinity split across
CPUs 4-7/0-3. The next controlled pass disables the still-active V-Sync before
changing resolution, translation, or driver components.

The measurement protocol is one warm-up and three recorded passes per profile.
Alongside the benchmark result, record peak memory, time to the main menu,
launch success rate, and any Android whole-UID eviction.

![Kingsway running from the microSD through Proton ARM64 and FEX](docs/evidence/kingsway-running.png)

![Tomb Raider Windows launcher running through Proton ARM64 and FEX](docs/evidence/tombraider-main-menu-2026-08-14.png)

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

### Reached GTA IV's first mission

GTA IV now passes the Rockstar boundary that previously ended at CEF Code 17.
The working checkpoint combines four narrowly scoped pieces:

- the Pressure Vessel route wrapper validates a private internal copy of GTA
  IV's executable files, overlays it at the normal game path, and keeps the
  large game-data directories on the microSD;
- the initial `PlayGTAIV.exe` payload is changed to a service-first batch that
  attempts to start `Rockstar Service` before handing control back to the
  signed game launcher; a nonzero service-control result is logged but does not
  suppress `PlayGTAIV.exe`;
- Wine's service startup timeout is raised to 60 seconds; and
- only `SocialClubHelper.exe` receives Wine's builtin D3D11/DXGI renderer,
  leaving the game itself on its accelerated D3D9/Vulkan route.

The validated online runs logged `Auth -> MainWindow`, `Presence Event - Signed
In`, and `Presence Event :: Went Online`. Rockstar then launched the genuine
`GTAIV.exe`; X11 reported a focused fullscreen `GTAIV` window and the rendered
frame first showed the GTA IV/EFLC selector. A fresh run reproduced the launch
without another 2FA prompt and then passed the selector into the real GTA IV
main menu. The exact 2800x1586 composed frame shows `Start` selected, the GTA IV
title art, and the connected Social Club panel. A later lean launch passed the
same selector and menu, accepted GTA IV's own saved-session sign-in prompt,
cycled through the loading art, and rendered the first-mission title **The
Cousins Bellic**. The retained mission-title frame is the first proof that a
new game started; interactive control after the opening transition remains the
next boundary.

The repository retains a purpose-built Windows ARM64 selector helper in
[`diagnostics/win-arm64-gtaiv-selector-play.c`](diagnostics/win-arm64-gtaiv-selector-play.c).
It accepts only an exact visible `GTAIV` top-level window, rejects client areas
smaller than 640x480, derives the GTA IV-side Play target from the current
fullscreen dimensions, and injects one Win32 left click. This avoids Wine's
unreliable cross-process `ClientToScreen` and `GetWindowRect` paths. It remains
a diagnostic rather than a guaranteed launch step: in one repeat run the
separately attached PE returned status 5 without moving the cursor or changing
the frame. After revalidating the exact focused X11 window, one XTest Return
press crossed the highlighted selector into the main menu and a second started
the loading sequence. The following frame and GTA process transition—not a
helper exit status—remain the live success criteria. Build the mouse helper with
[`scripts/build-win-arm64-gtaiv-selector-play.sh`](scripts/build-win-arm64-gtaiv-selector-play.sh).

Do not terminate Rockstar's CEF processes after GTA starts. A measured test
freed about 1.6 GiB of available RAM and 2.8 GiB of swap, but the launcher then
reported `Browser unavailable`, forced its own shutdown after 14 seconds, and
cleanly stopped GTA. The browser subprocesses are therefore part of the live
launcher/game contract, not disposable UI once the title process exists.

#### Keep the Android session alive and scheduled

On the tested Samsung Android build, the foreground app changes scheduling for
the whole Termux UID. With Termux:X11 visible, Steam, PRoot, Wine, and Rockstar
were placed in `cpu:/background` and `/cpuset/moderate`, with only CPUs 0-3.
Bringing `com.termux/.app.TermuxActivity` forward moved those same live
processes to `top-app` on CPUs 0-7; returning to
`com.termux.x11/.MainActivity` immediately restored the four-core restriction.

This can be a correctness issue, not just a performance issue. One Rockstar
start completed its network downloads but spent 61-152 seconds in background
service transactions and reached Code 17 almost exactly five minutes after the
launcher began. KDE, Steam, Wine, and Rockstar were all still alive, so that
event was a launcher deadline rather than an Android process kill.

A follow-up run started entirely in `/cpuset/moderate`: Rockstar service
transactions climbed from 37 seconds to about 180 seconds and saved-login
initialization never reached `Went Online`. Giving the launcher all available
moderate cores and closing Steam's UI recovered roughly 1 GiB. Physically
foregrounding Termux later drained most queued transactions from about 214 to
36 seconds, but one already-stalled transaction remained blocked for more than
1,200 seconds and the launch still did not reach `Went Online`. Start the
launch while Termux is the visible Android activity; late foregrounding is not
a dependable recovery for an already-backlogged run.

Before a long session, run `termux-wake-lock`. It prevents CPU sleep, but it
does **not** move the UID out of the background cpuset. The installed
`~/start-kde` likewise has no hidden `taskset` or Android timeout override:
`pulseaudio --exit-idle-time=-1` only keeps audio alive, while its final
`exec startplasma-x11` keeps Plasma attached to the launching terminal. For a
diagnostic launch, Termux can be brought forward during Rockstar's nonvisual
initialization and Termux:X11 restored after the log reports `Social Club UI
has started` and `Client is ready to attempt a launch`. The current tablet
environment accepted these exact activity switches from an SSH shell without
restarting X, Wine, or the game:

```sh
am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER \
  -n com.termux/.app.TermuxActivity
am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER \
  -n com.termux.x11/.MainActivity
```

Always verify `Cpus_allowed_list` after switching: an earlier environment
returned a package/permission mismatch, in which case physically tapping the
two activities remains the fallback.

This foreground sequence is a measured diagnostic workaround, not yet a
claimed fix for the separate whole-Termux process-tree loss described in the
technical log.

The successful first-mission launch also started Steam with shader cache
management disabled and the supported `-noshaders` client flag. That removed
the repeatedly growing 96-percent Vulkan preprocessing gate without changing
the App 12210 Proton/runtime route:

```sh
STEAM_ENABLE_SHADER_CACHE_MANAGEMENT=0 \
  ~/bin/steam-arm -no-browser -console -noshaders
```

#### Keep SSH supervised

With `termux-services` and OpenSSH installed, enable the runit service once:

```sh
sv-enable sshd
```

The repository installs a bounded startup helper at
`~/bin/ensure-sshd-supervised`. Keep this idempotent fallback in interactive
`~/.bashrc`, so opening Termux restores the service supervisor if needed and
waits for runit before asking it to bring SSH up:

```sh
if [[ $- == *i* ]] && [[ -n ${PREFIX:-} ]]; then
    "$HOME/bin/ensure-sshd-supervised" ||
        printf 'warning: supervised sshd did not start\n' >&2
fi
```

The helper validates the service installation, starts `runsvdir` without an
extra backgrounding race, waits at most ten seconds for the exact supervisor,
then requires `sv status` to report `run:`. The stock Termux profile also starts
`service-daemon`; concurrent calls are safe and the helper verifies the result.

A live test sent `TERM` to the supervised `sshd`; runit replaced it
immediately and a fresh port-8022 connection succeeded. This handles an SSH
daemon crash. It cannot restart Termux after Android force-stops the entire app
or evicts its UID under memory pressure, nor after a reboot; that requires an
external launcher such as Termux:Boot. A GTA IV loading run exhausted zram to
less than 100 KiB free and then made port 8022 refuse connections despite the
supervisor, demonstrating this whole-app boundary.

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

The tablet's native 2800x1586 desktop also made GTA IV create a roughly
2800x1550 render window. The repository therefore installs a minimal,
plain-text 1280x720 fullscreen profile as the validated executable view's
`commandline.txt`:

```text
-width 1280
-height 720
```

Width and height are present in this exact installed GTA IV executable's own
command-line help strings. Omitting `-windowed` keeps the game's default
fullscreen presentation while limiting its internal render size to 1280x720;
Wine's separate virtual desktop should remain disabled for this profile. The
profile leaves the opaque binary `SETTINGS.CFG` and the Rockstar login/profile
tree untouched. `scripts/install-project-files.sh` backs up an existing view
file before installing the repo-owned version; run it only with the GTA IV
Wine/Proton stack stopped so the next launch receives the new profile.

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
payload tree is overlaid, making the final commit a same-filesystem rename. The
per-App-ID overlay must target Steam's visible
`removable-library/steamapps/downloading/<appid>` path. Targeting the internal
backing directory does not transitively cover that earlier PRoot bind.

Do not use this overlay to extend an incomplete download directly on Android
portable storage. Steam's file allocator can return `ENOSYS`/disk-write failure
on that FUSE path even though ordinary writes work. Complete active staging on
internal F2FS, stop Steam, make and hash-verify the card copy, then enable the
overlay only for commit—or use the offline native commit below. If an
incomplete test enabled the overlay, disable it without touching either copy:

```sh
bin/steam-arm64-removable-library.py --base "$HOME/steam-arm64" \
  disable-staging-bind 203160
```

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

- Samsung Galaxy Tab S8+ (SM-X808U / `gts8p`), Snapdragon 8 Gen 1 (SM8450) /
  Adreno 730, with 7.12 GiB usable RAM and Android 16
- Debian 13 under Termux PRoot
- ARM64 Steam build `1785799196`
- Mesa Turnip `26.2.0-devel (git-9452d1daec)`
- PRoot base commit `a89b3732ec6ae1db674510f0843b2f3db54d0a2f`

No root, bootloader unlock, custom kernel, flash, chroot, or global Mesa/library
replacement is required.
