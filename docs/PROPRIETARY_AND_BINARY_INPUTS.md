# External binary inputs

This repository cannot redistribute Valve client binaries, games, Proton, or
the Mesa binary bundle.

## Valve Steam ARM64 client

The working payload was observed as build ID `1785799196`; its staging filename
was `steam_client_publicbeta_linuxarm64`. Record the original URL, checksum, and
license when acquisition is reconstructed. Expected executable:

```text
~/steam-arm64/client/steamrtarm64/steam
```

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

