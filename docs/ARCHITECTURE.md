# Architecture and isolation boundaries

```text
Android / Samsung kernel
  -> Termux app sandbox
    -> Termux:X11 + existing KDE session
    -> proot-distro Debian ARM64
      -> native ARM64 Steam client
        -> CEF software rendering for Steam UI
        -> private ARM64 Mesa Turnip ICD for Vulkan
        -> Proton / future x86 execution layer for Windows games
```

The client is native ARM64, avoiding translation of Steam's large Chromium UI.
Debian supplies the conventional glibc filesystem Valve expects. A patched
Termux PRoot supplies missing System V IPC behavior.

The launcher confines gaming variables to a child process. `LD_LIBRARY_PATH`,
`VK_DRIVER_FILES`, and `LIBGL_DRIVERS_PATH` select the private Mesa bundle;
`MESA_LOADER_DRIVER_OVERRIDE=kgsl` selects Qualcomm KGSL; and `TU_DEBUG=noconform`
permits this non-conformant Android configuration. None are exported globally.

A private D-Bus session prevents updater pipe inheritance from delaying launch.
PulseAudio is bridged over loopback. Steam CEF uses software rendering because
GPU compositing created stale/partial Termux:X11 surfaces; games retain Turnip.

The `lsof` shim only answers Steam's loopback-WebSocket ownership query, which
Android's restricted `/proc/net` cannot answer, and delegates all other calls.

