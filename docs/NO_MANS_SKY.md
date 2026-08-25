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
| Screenshots | Live-news UI `96fe91ee...1d29`; 1080p settings `bd2e6e74...0d86` |
| Current boundary | Schema 3 reached the live UI and 1080p graphics menu, remained alive for more than four minutes, and wrote no new dump |

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
This disproves scheduler starvation as the sole failure. Schema 3 then mapped
the complete contained Wine loader chain and advanced beyond both crashes to
the live-news UI and graphics menu. The retained menu proves exclusive
1920x1080, V-sync off, a 30 FPS cap, and Turnip on Adreno 730. FPS remains
unmeasured; a visible menu is not a gameplay benchmark.

The removable library root now remains on internal F2FS while only bulk game
content is mounted from SD. This removed Steam's `libraryfolder.vdf` flock
failure without moving NMS off the card. Cold launch still spent about 60
seconds rebuilding Steam's compatibility registry, so this is a correctness
fix rather than a claimed startup-speed win.

## FPS overlay and logs

Install the maintained AArch64 layer once, then start the measured path:

```sh
pkg install mangohud-glibc
~/start-no-mans-sky-fps
```

The 259 MB package remains optional so normal Steam installs stay lean. The FPS
launcher validates the native Vulkan layer and manifest, shows an FPS-only
overlay, and writes frame times to a private session log below
`~/steam-arm64/logs/no-mans-sky-fps-*`. Its explicit minimal configuration
disables hardware and battery probes that Android blocks. It rejects
caller-supplied layer paths and unexpected configuration. On clean exit it
writes a validated `summary.json` beside the raw CSV, excluding the first 60
seconds by default. Use one warm-up followed by three identical 60-second
surface/traversal/flight passes; compare average, sampled percentiles,
frame-time percentiles, hitches, and temperature. Temporarily test
the 60 FPS cap to expose headroom, then restore 30 FPS for pacing validation.

No Man's Sky has no established built-in benchmark. This follows the common
real-gameplay frame-time method documented by
[GamersNexus](https://gamersnexus.net/guides/2561-no-mans-sky-frametime-performance-review-poor-performance)
and uses [MangoHud's](https://github.com/flightlessmango/MangoHud) maintained
logging path rather than Android's compositor FPS counter.

Summarize a deliberately selected gameplay interval with:

```sh
python3 scripts/summarize-mangohud-csv.py METRICS.csv \
  --start-seconds 60 --duration-seconds 180
```

The JSON labels periodic FPS percentiles as samples, not conventional
frame-level 1% lows. Record the scene, route, settings, temperature, and exact
CSV hash alongside it before comparing runs.

## Preliminary headroom

| Interval | Configuration | Sampled result | Status |
| --- | --- | --- | --- |
| 60.0–296.5 s | 1080p, FSR 2 Quality, High textures/animation, Medium remaining detail, 60 cap | 58.35 mean; 56.89 median FPS | Unclassified scene; not charted |

This first retained CSV is encouraging but lacks a recorded on-planet route
and temperature. Its exact hash and bounded statistics are retained in
[the preliminary record](benchmark-series/no-mans-sky-1080p-fsr2-quality-unclassified-20260825.json).
