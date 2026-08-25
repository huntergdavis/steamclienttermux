# No Man's Sky tablet profile

No Man's Sky is AppID `275850`. The PC renderer is Vulkan, the game supports a
correctly paced 30 FPS mode, and the Steam build supports Steam Cloud plus
Hello Games cross-save.

## First profile

| Setting | Value |
| --- | --- |
| Output | 1920x1080 exclusive fullscreen |
| Frame target | 30 FPS |
| Upscaling | FSR 2 Quality |
| Texture and animation | High |
| Shadows, effects, reflections, volumetrics | Standard |
| Terrain, planet, water, and base detail | Standard |
| Ambient occlusion | GTAO Low |
| Motion blur, HDR, V-sync | Off |
| Thread allocation | Engine automatic (`0` / `0`) |

Before the first launch, stop Steam and create the contained Proton tool:

```sh
~/setup-no-mans-sky
```

The command creates a small private overlay of the reviewed Proton 11 ARM64
tree, copies Wine's five-file loader chain and Steam Input DLL, applies the
exact reviewed patch, and maps only AppID 275850 to the new tool. It backs up `config.vdf`, is
idempotent, and never changes stock Proton. Android SELinux denies hard links
and reflinks here, so other payload files are read-only symlinks to the
hash-checked stock build instead of a second 1.9 GB copy. The schema-3 content
ID is `45a9ed5f`, so either older experimental overlay is rejected.

The profile keeps a timestamped original and atomically replaces only a valid
generated `TKGRAPHICSSETTINGS.MXML`:

```sh
~/bin/configure-no-mans-sky
```

Use `--dry-run` before changing a new game build. If Quality cannot hold 30 FPS
during planetary traversal, test `--fsr balanced`; do not lower settings based
on menus or the loading starfield.

## Save safety

Launch through Steam, exit the game normally, and wait for Steam to report
Cloud status **Up to date**. Keep rolling local snapshots of the Proton prefix
before testing new Proton builds. Hello Games cross-save is an additional
recovery path, not a replacement for local backups.

## Evidence boundary

Public GameNative results on Adreno 730 range from severe stutter to a short
54 FPS report, while Adreno 740 commonly reports 50–59 FPS at 720p. Those are
configuration leads, not a tablet claim. Promote this profile only after a
sustained on-planet run records resolution, settings, temperature, minimum,
maximum, average FPS, and cloud completion.

Research sources: [Hello Games Vulkan update](https://www.nomanssky.com/beyond-update/),
[Steam Cloud and cross-save](https://store.steampowered.com/app/275850/No_Mans_Sky/),
[Steam Deck 30 FPS profile](https://steamdeckhq.com/game-reviews/no-mans-sky/),
and [current settings-file example](https://steamcommunity.com/app/275850/discussions/0/601912361526325530/).

## Large SD-card download

Keep active download staging on internal storage and select `microSD Windows
games` as the destination. Steam then commits the completed payload to SD. The
tablet's portable-storage FUSE supports ordinary writes but not `fallocate`, so
direct active staging on SD fails with `CGenericAsyncFileIOThread` errno 38.

The generic `enable-empty-staging-bind` command now probes this requirement
before changing configuration and fails closed on this tablet. This reuses the
previously verified Tomb Raider workflow: internal F2FS staging followed by an
offline hash-verified or normal Steam commit to SD.

## First launch result

| Gate | Result |
| --- | --- |
| Install | Build `24039799`, 28.36 GB downloaded, committed successfully to SD |
| One-command route | Logged-in Steam AppID handoff; no duplicate client; bounded missing-dispatch failure |
| ARM64 mapping | Runtime 4 ARM64 + Proton 11 ARM64 selected and validated exactly |
| Removable storage | Game stays on SD; compatdata stays internal; namespace-safe binds pass |
| Direct runtime | 12 authenticated FDs; native Runtime 4, FEX, DXVK, Turnip, and Steam SDK client mapped |
| `NMS.exe` | Loaded Turnip and created a real 2800x1752 X11 game surface |
| Steam Input A/B | Returning success from the failing `ISteamInput006::Init` wrapper bypassed the pre-window crash |
| Containment | `/proc` mapped reviewed PE inode `719319` plus the contained Wine loader root; stock Proton stayed unchanged |
| Screenshots | Hello Games `9cfd72e9...92a9`; animated Atlas loader `e2197233...d2e7` |
| Current boundary | The `0x15B2C` Steam Input crash is gone; startup advanced for more than two minutes, then wrote `0xCB684-HANG` and exited |

Run the reviewed path from visible Termux:

```sh
~/start-no-mans-sky-direct
```

The regular Steam UI still uses its ARM64 PRoot wrapper; the game does not.
The direct router validates the exact AppID, executable, Proton tool, SD game
tree, internal prefix, native Steam HOME, and Runtime 4 payload before launch.
It rejects an unexpected command rather than applying NMS settings to another
game.

The exact Steam Input failure has no indexed prior implementation. The release
path now contains the exact eight-byte patch in a separately named Proton tool.
Wine resolves its executable root before builtins. The wrapper, Wine loader,
preloader, wineserver, and `ntdll.so` are therefore private hash-checked copies;
symlinking any of that chain can silently anchor lookup back in stock Proton.
[Community report](https://steamcommunity.com/app/275850/discussions/0/595139710753458551/),
[Proton source](https://github.com/ValveSoftware/Proton/blob/proton_11.0/lsteamclient/steam_input_manual.c),
[Wine loader source](https://github.com/wine-mirror/wine/blob/master/tools/wine/wine.c).

The first visible-frame test was deliberately not benchmarked. Its X11 server
was in Android's `/moderate` + `/background` cgroups and allowed only CPUs 2-3;
NMS took 207 seconds from process creation to the retained screenshot and its
watchdog wrote a 161,886-byte hang dump (SHA-256 `61f06e26...11b6`). A second
run launched from visibly foreground Termux, proved X11 in `/top-app`, and
reached a full 2800x1752 Hello Games surface. It then produced a different
`0x15B2C` access violation and 81,138-byte dump (SHA-256 `2a37769a...d9ae`).
This disproves scheduler starvation as the sole failure. The contained loader
root now removes that crash; the next boundary is the later loading hang. Apply
the 1080p profile only after a foreground run reaches a stable window and exits
cleanly.

The removable library root now remains on internal F2FS while only bulk game
content is mounted from SD. This removed Steam's `libraryfolder.vdf` flock
failure without moving NMS off the card. Cold launch still spent about 60
seconds rebuilding Steam's compatibility registry, so this is a correctness
fix rather than a claimed startup-speed win.
