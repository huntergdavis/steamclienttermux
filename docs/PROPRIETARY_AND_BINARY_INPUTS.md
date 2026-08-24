# External binary inputs

This repository cannot redistribute Valve client binaries, games, Proton, or
the Mesa binary bundle.

## Valve Steam ARM64 client

The working stable payload is build ID `1785799196`. We do not redistribute it.
The bootstrap lock fetches the seed directly from Valve's public HTTPS
client-update service and fails closed if any locked byte changes:

```text
manifest: https://client-update.steamstatic.com/steam_client_linuxarm64
size:     12,579 bytes
sha256:   a2ad912ef6f150d373504a80c79f95210f8ed4ddbc42071593d0a120eb96ca91

seed:     https://client-update.steamstatic.com/bins_linuxarm64_linuxarm64.zip.4f25204460fd1f27acce2f687019e2518ed8d8bf
size:     109,534,844 bytes
sha256:   3f282edba1e24ab01c4d532a43bf3000946df8199c16f16c279635f16c6edc06
```

The seed contains the native AArch64 glibc executable below. After verified
extraction, run it through this project's native glibc loader and let Valve's
own updater retrieve the rest of Steam. Account login and Steam Guard happen
only in Valve's client; this bootstrap never handles credentials.

```text
~/steam-arm64/client/steamrtarm64/steam
```

The live client-update channel is not a documented historical-release API. If
Valve changes stable, the pinned bootstrap intentionally stops until a new
build is independently validated and a new signed project lock is published.
Valve's Subscriber Agreement still applies; seek explicit legal review before
distributing any Valve binary. Direct end-user retrieval is not permission to
mirror or rebundle it.

## Mesa Turnip

The working private bundle identified itself as Mesa `26.2.0-devel`, git
`9452d1daec`, with Vulkan ICD API `1.4.335`. Expected layout:

```text
~/steam-arm64/mesa-kgsl/usr/lib/aarch64-linux-gnu/libvulkan_freedreno.so
~/steam-arm64/mesa-kgsl/usr/lib/aarch64-linux-gnu/dri/
~/steam-arm64/mesa-kgsl/icd.d/freedreno-private.json
```

Steam-managed Proton, runtimes, redistributables, and games belong in the Steam
library and must never be committed.
