#!/data/data/com.termux/files/usr/bin/bash
set -u

base="$HOME/steam-arm64"
mesa_lib="$base/mesa-kgsl/usr/lib/aarch64-linux-gnu"
icd="$base/mesa-kgsl/icd.d/freedreno-private.json"

export LD_LIBRARY_PATH="$mesa_lib"
export VK_DRIVER_FILES="$icd"
export LIBGL_DRIVERS_PATH="$mesa_lib/dri"
export MESA_LOADER_DRIVER_OVERRIDE=kgsl
export TU_DEBUG=noconform

printf 'VK_DRIVER_FILES=%s\n' "$VK_DRIVER_FILES"
vulkaninfo --summary 2>&1 || true
glxinfo -B 2>&1 || true

if command -v vkcube >/dev/null; then
    printf '\nRun vkcube manually in the active Termux:X11 session for visual verification.\n'
fi

