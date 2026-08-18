# Architecture and isolation boundaries

## The key compatibility boundary

This project is primarily a **Linux ABI/behavior repair**, not a CPU-emulation
trick. Steam is already an ARM64 executable. Debian supplies its glibc userspace,
but PRoot must make that userspace observe kernel behavior close enough to normal
Linux. The decisive changes were robust-list syscall emulation and more complete
SysV semaphore semantics, especially waking blocked `semop` callers when another
process changes a semaphore.

The graphics issue is separate: Turnip can accelerate Vulkan on Adreno 730, but
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

## Experimental Bionic/system-Vulkan path

The production game path above is unchanged. A separate
[`bionic-vulkan-bridge`](https://github.com/huntergdavis/bionic-vulkan-bridge)
project now tests a second graphics boundary without discarding the working
Steam/Proton/FEX stack:

```text
glibc game-side client
  -> versioned, owner-authenticated Unix socket
  -> Bionic bridge service
  -> /system/lib64/libvulkan.so
  -> /vendor/lib64/hw/vulkan.adreno.so
```

On the Tab S8+, a Termux-built Bionic probe enumerated the Adreno 730 directly;
an independently glibc-linked AArch64 client then negotiated protocol v1 and
received the same capability fields through the service. Neither leg uses
PRoot. The service now also creates a logical device, command pool, queue, and
host-visible buffer, executes `vkCmdFillBuffer`, synchronizes, maps, and verifies
the result. Both a direct Bionic control and the glibc-triggered service path
verified 1,024 words with zero mismatches. This proves native Vulkan object and
command execution across the process/ABI control boundary.

The current Termux:X11 Binder interface exports X and log descriptors, not its
Android `Surface`; its in-process renderer already owns that `SurfaceView` as an
EGL producer. An X connection is not an `ANativeWindow`, and the tablet lacks
`VK_EXT_headless_surface`. The next isolated gate therefore uses a controlled
Android native window before adding a dedicated visible `SurfaceView` host.
E006 passed that first gate with an independently owned 64x64
`AImageReader`/`ANativeWindow`: the system loader created its Vulkan surface and
reported stable queue, capability, format, and present-mode data across four
runs. E007 then created its six-image FIFO swapchain, acquired and cleared an
image, synchronized and presented it, acquired the consumer `AImage`, and
verified all 4,096 opaque-magenta RGBA pixels. The full offscreen
producer/BufferQueue/consumer loop now passes. The dedicated visible host,
glibc bridge exposure, game-facing dispatch, DXVK integration, and any FPS
improvement remain unproven. E008 then packaged a standalone Bionic
`NativeActivity` whose dedicated Android window visibly displayed the same
opaque-magenta Vulkan frame. The bottom navigation bar remained visible. The
visible host therefore works, while explicit bridge lifecycle handoff,
shared-UID integration, game dispatch, and performance remain future gates.

Termux remains the Bionic control plane, while glibc remains necessary for the
commercial Linux game stack. The experiment therefore narrows one boundary
instead of proposing an unmeasured replacement for the full Linux stack.

The `lsof` shim only answers Steam's loopback-WebSocket ownership query, which
Android's restricted `/proc/net` cannot answer, and delegates all other calls.
