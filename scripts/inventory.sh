#!/data/data/com.termux/files/usr/bin/bash
set -u

section() { printf '\n## %s\n' "$1"; }

section Android
for prop in ro.product.model ro.product.device ro.build.version.release ro.build.version.sdk ro.build.version.security_patch ro.hardware ro.soc.model; do
    printf '%s=' "$prop"
    getprop "$prop"
done

section Kernel
whoami
uname -a
getconf PAGESIZE 2>/dev/null || true

section Termux
termux-info 2>&1 || true
dpkg --print-architecture 2>/dev/null || true

section Resources
lscpu 2>/dev/null || true
free -h 2>/dev/null || true
df -h

section Containers
command -v proot || true
command -v proot-distro || true
proot-distro list 2>/dev/null || true
ps -A -o pid,ppid,args | grep -E 'termux-x11|virgl|proot|steam' || true

section Devices
ls -la /dev/kgsl* /dev/dri 2>&1 || true
ls -la /proc/sys/fs/binfmt_misc 2>&1 || true

section GPU_packages
pkg list-installed 2>/dev/null | grep -Ei 'mesa|vulkan|turnip|virgl|zink|x11' || true

section Translation_layers
for candidate in FEXInterpreter FEXBash box64 box86 wine steam; do
    command -v "$candidate" || true
done

section Root
command -v su || true
su -c id 2>&1 || true

