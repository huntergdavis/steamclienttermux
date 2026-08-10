#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

mode="${1:---outer}"

if [[ "$mode" == "--inside-proot" ]]; then
    base="$2"
    client="$base/client"
    runtime="$client/steamapps/common/SteamLinuxRuntime_4-arm64/_v2-entry-point"
    proton="$client/steamapps/common/Proton 11.0 (ARM64)/proton"
    install="$client/steamapps/common/BurnoutPR"

    mkdir -p /tmp/steam-runtime
    export PATH="$base/compat-bin:$PATH"
    cd "$install"
    exec "$runtime" --verb=run -- \
        "$proton" runinprefix \
        'C:\Program Files\Electronic Arts\EA Desktop\EA Desktop\Link2EA.exe' \
        'link2ea://launchgame/1238080?platform=steam&theme=bprm'
fi

if [[ "$mode" != "--outer" ]]; then
    printf 'Unknown mode: %s\n' "$mode" >&2
    exit 2
fi

base="${2:-$HOME/steam-arm64}"
client="$base/client"
shadow="$base/runtime/SteamLinuxRuntime_4-arm64"
depot="$client/steamapps/common/SteamLinuxRuntime_4-arm64"
compat="$client/steamapps/compatdata/1238080"
hosts="$base/config/hosts-ipv4"
custom_proot_dir="$base/src/proot-production/src"
script_path="$base/compat-bin/steam-arm64-ea-link2ea-direct"
session_guard="$base/compat-bin/steam-arm64-session-guard.py"

required_files=(
    "$client/steamapps/common/Proton 11.0 (ARM64)/proton"
    "$compat/pfx/drive_c/Program Files/Electronic Arts/EA Desktop/EA Desktop/Link2EA.exe"
    "$shadow/pressure-vessel/bin/pressure-vessel-wrap"
    "$hosts"
    "$script_path"
    "$session_guard"
)
for required_file in "${required_files[@]}"; do
    if [[ ! -f "$required_file" ]]; then
        printf 'Required direct-launch file is missing: %s\n' "$required_file" >&2
        exit 1
    fi
done
if [[ ! -x "$custom_proot_dir/proot" ]]; then
    printf 'Required patched PRoot is missing: %s\n' "$custom_proot_dir/proot" >&2
    exit 1
fi
command -v python3 >/dev/null || { echo 'python3 is required' >&2; exit 1; }
crash_log_mode="$(
    python3 "$session_guard" crash-mode "${PROOT_CRASH_LOG-}"
)"
if [[ "$crash_log_mode" == enabled ]]; then
    export PROOT_CRASH_LOG=1
else
    unset PROOT_CRASH_LOG
fi
if pgrep -x wineserver >/dev/null; then
    printf 'Refusing direct launch while a Wine prefix session is active\n' >&2
    exit 1
fi

if ! unsafe_link="$(
    find "$shadow/pressure-vessel" -type l -lname '*/.l2s/*' -print -quit
)"; then
    printf 'Unable to inspect prepared ARM64 runtime for .l2s links: %s\n' \
        "$shadow" >&2
    exit 1
fi
if [[ -n "$unsafe_link" ]]; then
    printf 'Prepared ARM64 runtime contains unsafe .l2s links: %s\n' "$shadow" >&2
    exit 1
fi

pd_args=(login debian --shared-tmp)
pd_args+=(--bind "$hosts:/etc/hosts")
pd_args+=(--bind "$shadow:$depot")
pd_args+=(--env "PROOT_L2S_EXDEV_PREFIX=$depot/var/tmp-")
if [[ "$crash_log_mode" == enabled ]]; then
    pd_args+=(--env PROOT_CRASH_LOG=1)
fi
pd_args+=(--env "DISPLAY=${DISPLAY:-:0}")
pd_args+=(--env XDG_RUNTIME_DIR=/tmp/steam-runtime)
pd_args+=(--env PULSE_SERVER=127.0.0.1)
pd_args+=(--env "LD_LIBRARY_PATH=$base/mesa-kgsl/usr/lib/aarch64-linux-gnu")
pd_args+=(--env "VK_DRIVER_FILES=$base/mesa-kgsl/icd.d/freedreno-private.json")
pd_args+=(--env "LIBGL_DRIVERS_PATH=$base/mesa-kgsl/usr/lib/aarch64-linux-gnu/dri")
pd_args+=(--env MESA_LOADER_DRIVER_OVERRIDE=kgsl)
pd_args+=(--env TU_DEBUG=noconform)
pd_args+=(--env MESA_VK_WSI_PRESENT_MODE=mailbox)
pd_args+=(--env "STEAM_COMPAT_CLIENT_INSTALL_PATH=$client")
pd_args+=(--env "STEAM_COMPAT_DATA_PATH=$compat")
pd_args+=(--env STEAM_COMPAT_APP_ID=1238080)
pd_args+=(--env SteamAppId=1238080)
pd_args+=(--env SteamGameId=1238080)
# Link2EA initializes steam_api64.dll directly in this diagnostic path. Keep
# the zero-depth stub state explicit: this reproduces the isolated fast-fail
# and is not sufficient Steam API context for a production launch.
pd_args+=(--env STEAM_STUB_COUNT=0)
pd_args+=(--env "STEAM_COMPAT_INSTALL_PATH=$client/steamapps/common/BurnoutPR")
pd_args+=(--env PROTON_LOG=0)

export PATH="$custom_proot_dir:$PATH"
export PROOT_L2S_EXDEV_PREFIX="$depot/var/tmp-"
exec proot-distro "${pd_args[@]}" -- \
    /bin/bash "$script_path" --inside-proot "$base"
