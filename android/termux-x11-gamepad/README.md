# Termux:X11 input port

This overlay adds one-controller XInput transport and separates touch/touchpad
from captured physical-mouse input.

Base: Termux:X11 `54d159166a4d8573da54d693e461a1def3751248`.

1. Apply `termux-x11-input.patch` at the Termux:X11 root.
2. Add this directory to the `lorie` Java source set, or copy
   `GamepadBridge.java` under `com/termux/x11/input`.
3. Build the shared-UID APK normally.

The controller bridge is localhost-only. It advertises XInput only while a
real Android gamepad is connected and clears state on hot-unplug. Touch and
touchpad events never request pointer capture; physical mouse events do.
