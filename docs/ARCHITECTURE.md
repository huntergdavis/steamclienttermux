# Architecture and isolation boundaries

## The key compatibility boundary

This project is primarily a **Linux ABI/behavior repair**, not a CPU-emulation
trick. Steam is already an ARM64 executable. Debian supplies its glibc userspace,
but PRoot must make that userspace observe kernel behavior close enough to normal
Linux. The decisive changes were robust-list syscall emulation and more complete
SysV semaphore semantics, especially waking blocked `semop` callers when another
process changes a semaphore.

The graphics issue is separate: Turnip can accelerate Vulkan on Adreno 740, but
Steam's Chromium compositor did not interact correctly with Termux:X11. The
working configuration deliberately splits those paths—software-rendered CEF for
the Steam interface, private Turnip Vulkan for games.

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
