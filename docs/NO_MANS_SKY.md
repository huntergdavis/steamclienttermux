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

Before the first launch, stop Steam and select the verified native ARM64 Proton
tool with the generic AppID mapper:

```sh
~/bin/configure-steam-app-proton 275850
```

The command backs up `config.vdf`, updates only this AppID, and is idempotent.

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
