#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
base="$HOME/steam-arm64"
stamp="$(date +%Y%m%d-%H%M%S)"
backup="$base/backups/repo-install-$stamp"
proot_patch_stamp="$base/src/proot-production/.steamclienttermux-patchset"
proot_binary="$base/src/proot-production/src/proot"
required_proot_patch="proot-runtime-directory-bind-target.patch"
raknet_recv_shim=${TGCOMPAT_RAKNET_RECV_SHIM:-$base/tgcompat/current/build/libtgcompat-raknet-recv.so}

command -v sha256sum >/dev/null || { echo 'sha256sum is required' >&2; exit 1; }
if [[ ! -f $raknet_recv_shim || -L $raknet_recv_shim ]] ||
        ! grep -aFq 'Raknet-RecvFrom' "$raknet_recv_shim" ||
        ! grep -aFq 'TGCOMPAT_RAKNET_RECV_SLEEP_US' "$raknet_recv_shim"; then
    printf 'Refusing install: RakNet receive backoff shim is unavailable or invalid: %s\n' \
        "$raknet_recv_shim" >&2
    exit 1
fi

if [[ ! -f "$proot_patch_stamp" ]] ||
        ! sed -n 's/^patches=//p' "$proot_patch_stamp" |
        tr ' ' '\n' | grep -Fxq "$required_proot_patch"; then
    printf 'Refusing install: production PRoot lacks %s\n' \
        "$required_proot_patch" >&2
    printf 'Build and deploy the repository PRoot patch set first.\n' >&2
    exit 1
fi
if [[ ! -x "$proot_binary" ]]; then
    printf 'Refusing install: production PRoot is not executable: %s\n' \
        "$proot_binary" >&2
    exit 1
fi
stamped_proot="$(sed -n 's/^proot_sha256=//p' "$proot_patch_stamp")"
if [[ ! "$stamped_proot" =~ ^[0-9a-f]{64}$ ]] ||
        [[ "$(sha256sum "$proot_binary" | awk '{print $1}')" != "$stamped_proot" ]]; then
    printf 'Refusing install: production PRoot does not match its build stamp: %s\n' \
        "$proot_binary" >&2
    exit 1
fi

install_one() {
    local source="$1" destination="$2" mode="$3"
    mkdir -p "$(dirname "$destination")" "$backup"
    if [[ -e "$destination" || -L "$destination" ]]; then
        cp -a -- "$destination" "$backup/$(basename "$destination")"
    fi
    install -m "$mode" "$source" "$destination"
}

wrapper_stage="$(mktemp "${TMPDIR:-$PREFIX/tmp}/steam-arm64-bwrap-route.XXXXXX")"
native_entry_stage="$(mktemp "${TMPDIR:-$PREFIX/tmp}/steam-arm64-native-entry.XXXXXX")"
tmp_shim_stage="$(mktemp "${TMPDIR:-$PREFIX/tmp}/steam-arm64-native-tmp.XXXXXX")"
debug_wait_shim_stage="$(mktemp "${TMPDIR:-$PREFIX/tmp}/steam-arm64-debug-wait.XXXXXX")"
native_lsof_stage="$(mktemp "${TMPDIR:-$PREFIX/tmp}/steam-arm64-native-lsof.XXXXXX")"
cleanup_wrapper_stage() {
    if [[ -n "$wrapper_stage" ]] && [[ -f "$wrapper_stage" ]] &&
            [[ ! -L "$wrapper_stage" ]]; then
        unlink -- "$wrapper_stage"
    fi
    if [[ -n "$native_entry_stage" ]] && [[ -f "$native_entry_stage" ]] &&
            [[ ! -L "$native_entry_stage" ]]; then
        unlink -- "$native_entry_stage"
    fi
    if [[ -n "$tmp_shim_stage" ]] && [[ -f "$tmp_shim_stage" ]] &&
            [[ ! -L "$tmp_shim_stage" ]]; then
        unlink -- "$tmp_shim_stage"
    fi
    if [[ -n "$debug_wait_shim_stage" ]] && [[ -f "$debug_wait_shim_stage" ]] &&
            [[ ! -L "$debug_wait_shim_stage" ]]; then
        unlink -- "$debug_wait_shim_stage"
    fi
    if [[ -n "$native_lsof_stage" ]] && [[ -f "$native_lsof_stage" ]] &&
            [[ ! -L "$native_lsof_stage" ]]; then
        unlink -- "$native_lsof_stage"
    fi
}
trap cleanup_wrapper_stage EXIT
"${CC:-cc}" -std=c11 -O2 -Wall -Wextra -Werror \
    "$repo_root/diagnostics/pressure-vessel-route-bwrap.c" \
    -o "$wrapper_stage"
env -u LD_PRELOAD -u LD_LIBRARY_PATH -u GLIBC_LD_LIBRARY_PATH \
    grun -s gcc -std=c11 -O3 -DNDEBUG -flto -fno-plt \
    -fno-semantic-interposition -ffunction-sections -fdata-sections \
    -Wall -Wextra -Werror -Wpedantic -Wformat=2 -Wshadow \
    "$repo_root/diagnostics/native-bwrap-entry.c" \
    -Wl,-O2,--as-needed,--gc-sections,-z,relro,-z,now \
    -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
    -o "$native_entry_stage"
env -u LD_PRELOAD -u LD_LIBRARY_PATH -u GLIBC_LD_LIBRARY_PATH \
    grun -s gcc -std=c11 -O3 -DNDEBUG -flto -fPIC -shared -fno-plt \
    -fno-semantic-interposition -ffunction-sections -fdata-sections \
    -Wall -Wextra -Werror -Wpedantic -Wformat=2 -Wshadow \
    "$repo_root/diagnostics/native-tmp-shim.c" \
    -Wl,-O2,--as-needed,--gc-sections,-z,relro,-z,now -ldl \
    -o "$tmp_shim_stage"
env -u LD_PRELOAD -u LD_LIBRARY_PATH -u GLIBC_LD_LIBRARY_PATH \
    grun -s gcc -std=c11 -O3 -DNDEBUG -flto -fPIC -shared -fno-plt \
    -fno-semantic-interposition -ffunction-sections -fdata-sections \
    -Wall -Wextra -Werror -Wpedantic -Wformat=2 -Wshadow \
    "$repo_root/diagnostics/native-tombraider-debug-wait.c" \
    -Wl,-O2,--as-needed,--gc-sections,-z,relro,-z,now \
    -o "$debug_wait_shim_stage"
env -u LD_PRELOAD -u LD_LIBRARY_PATH -u GLIBC_LD_LIBRARY_PATH \
    grun -s gcc -std=c11 -O3 -DNDEBUG -flto -fno-plt \
    -ffunction-sections -fdata-sections \
    -Wall -Wextra -Werror -Wpedantic -Wformat=2 -Wshadow \
    "$repo_root/diagnostics/native-lsof.c" \
    -Wl,-O2,--as-needed,--gc-sections,-z,relro,-z,now \
    -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
    -o "$native_lsof_stage"

install_one "$repo_root/bin/steam-arm" "$HOME/bin/steam-arm" 700
install_one "$repo_root/bin/steam-arm-native" "$HOME/bin/steam-arm-native" 700
install_one "$repo_root/bin/steam-arm64-native-bwrap" \
    "$base/compat-bin/steam-arm64-native-bwrap" 700
install_one "$repo_root/scripts/capture-pressure-vessel-plan.py" \
    "$base/compat-bin/capture-pressure-vessel-plan.py" 700
install_one "$repo_root/scripts/pressure-vessel-direct-dispatch.py" \
    "$base/compat-bin/pressure-vessel-direct-dispatch.py" 700
install_one "$repo_root/scripts/prepare-proton-direct-wine.py" \
    "$base/compat-bin/prepare-proton-direct-wine.py" 700
install_one "$repo_root/scripts/guard-wine-startup-window.sh" \
    "$base/compat-bin/guard-wine-startup-window.sh" 700
install_one "$repo_root/scripts/wait-steam-app-launch.sh" \
    "$base/compat-bin/wait-steam-app-launch.sh" 700
install_one "$native_entry_stage" \
    "$base/compat-bin/steam-arm64-native-bwrap-entry" 700
install_one "$native_entry_stage" \
    "$base/runtime/SteamLinuxRuntime_4-arm64-native/_v2-entry-point" 700
install_one "$repo_root/config/steam-arm64-runtime-toolmanifest.vdf" \
    "$base/runtime/SteamLinuxRuntime_4-arm64-native/toolmanifest.vdf" 600
install_one "$tmp_shim_stage" \
    "$base/compat-bin/steam-arm64-native-tmp.so" 700
install_one "$debug_wait_shim_stage" \
    "$base/compat-bin/steam-arm64-debug-wait.so" 700
install_one "$raknet_recv_shim" \
    "$base/compat-bin/libtgcompat-raknet-recv.so" 700
install_one "$native_lsof_stage" \
    "$base/compat-bin/steam-arm64-native-lsof" 700
install_one "$repo_root/scripts/start-steam.sh" "$HOME/start-steam.sh" 700
install_one "$repo_root/scripts/start-steam-native.sh" \
    "$HOME/start-steam-native.sh" 700
install_one "$repo_root/scripts/trace-steam-native.sh" \
    "$HOME/trace-steam-native.sh" 700
install_one "$repo_root/scripts/capture-native-steam-backtrace.sh" \
    "$HOME/capture-native-steam-backtrace.sh" 700
install_one "$repo_root/scripts/start-tombraider.sh" \
    "$HOME/start-tombraider.sh" 700
install_one "$repo_root/scripts/start-steam-game.py" \
    "$HOME/start-steam-game" 700
install_one "$repo_root/config/game-launch-profiles.json" \
    "$base/config/game-launch-profiles.json" 600
install_one "$repo_root/scripts/start-tombraider-native.sh" \
    "$HOME/start-tombraider-native.sh" 700
install_one "$repo_root/scripts/capture-tombraider-pressure-vessel-plan.sh" \
    "$HOME/capture-tombraider-pressure-vessel-plan" 700
install_one "$repo_root/scripts/start-tombraider-direct-dispatch.sh" \
    "$HOME/start-tombraider-direct-dispatch" 700
install_one "$repo_root/scripts/start-no-mans-sky-direct.sh" \
    "$HOME/start-no-mans-sky-direct" 700
install_one "$repo_root/scripts/start-no-mans-sky-fps.sh" \
    "$HOME/start-no-mans-sky-fps" 700
install_one "$repo_root/scripts/setup-no-mans-sky.sh" \
    "$HOME/setup-no-mans-sky" 700
install_one "$repo_root/scripts/prepare-no-mans-sky-proton.py" \
    "$base/compat-bin/prepare-no-mans-sky-proton.py" 700
install_one "$repo_root/scripts/start-tombraider-direct-lean.sh" \
    "$HOME/start-tombraider-direct-lean" 700
install_one "$repo_root/scripts/start-tombraider-direct-benchmark.sh" \
    "$HOME/start-tombraider-direct-benchmark" 700
install_one "$repo_root/scripts/start-tombraider-direct-raknet-backoff.sh" \
    "$HOME/start-tombraider-direct-raknet-backoff" 700
install_one "$repo_root/scripts/start-tombraider-direct-raknet-backoff-benchmark.sh" \
    "$HOME/start-tombraider-direct-raknet-backoff-benchmark" 700
install_one "$repo_root/scripts/start-tombraider-direct-tmp-only.sh" \
    "$HOME/start-tombraider-direct-tmp-only" 700
install_one "$repo_root/scripts/start-tombraider-direct-debug-wait.sh" \
    "$HOME/start-tombraider-direct-debug-wait" 700
install_one "$repo_root/scripts/start-tombraider-direct-diagnostic.sh" \
    "$HOME/start-tombraider-direct-diagnostic" 700
install_one "$repo_root/scripts/start-tombraider-vulkan-trace.sh" \
    "$HOME/start-tombraider-vulkan-trace" 700
install_one "$repo_root/scripts/start-tombraider-bvb-probe.sh" \
    "$HOME/start-tombraider-bvb-probe" 700
install_one "$repo_root/scripts/run-tombraider-bvb-foreground.py" \
    "$base/compat-bin/run-tombraider-bvb-foreground.py" 700
install_one "$repo_root/scripts/start-tombraider-bvb-foreground.sh" \
    "$HOME/start-tombraider-bvb-foreground" 700
install_one "$repo_root/scripts/run-tombraider-native-benchmark.py" \
    "$base/compat-bin/run-tombraider-native-benchmark.py" 600
install_one "$repo_root/scripts/hold-tombraider-steam-cef.py" \
    "$base/compat-bin/hold-tombraider-steam-cef.py" 700
install_one "$repo_root/scripts/isolate-tombraider-steam-service.py" \
    "$base/compat-bin/isolate-tombraider-steam-service.py" 700
install_one "$repo_root/scripts/isolate-tombraider-x11.py" \
    "$base/compat-bin/isolate-tombraider-x11.py" 700
install_one "$repo_root/scripts/run-tombraider-native-benchmark.sh" \
    "$HOME/run-tombraider-native-benchmark" 700
install_one "$repo_root/scripts/test-tomb-raider-proton-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-proton-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-fast-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-fast-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-safe-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-safe-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-fast-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-fast-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-proton-full-topology-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-proton-full-topology-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-safe-full-topology-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-safe-full-topology-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-fast-full-topology-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-fast-full-topology-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-safe-full-topology-raknet-nice19-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-safe-full-topology-raknet-nice19-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-raknet-backoff-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-raknet-backoff-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-fex-code-cache-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-fex-code-cache-40c-ceiling.sh" 700
install_one "$repo_root/scripts/prepare-tombraider-fex-offline-cache.py" \
    "$base/compat-bin/prepare-tombraider-fex-offline-cache.py" 700
install_one "$repo_root/scripts/start-tombraider-fex-offline-compile.sh" \
    "$HOME/start-tombraider-fex-offline-compile.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-fex-offline-compiled-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-fex-offline-compiled-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-fex-offline-compiled-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-fex-offline-compiled-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-fex-offline-compiled-720p-normal-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-fex-offline-compiled-720p-normal-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-1103-x32-720p-normal-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-1103-x32-720p-normal-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-720p-normal-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-720p-normal-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-1080p-normal-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-1080p-normal-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-720p-high-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-720p-high-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-1080p-high-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-1080p-high-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-720p-ultra-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-720p-ultra-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-1080p-ultra-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-1080p-ultra-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-720p-ultra-no-tessellation-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-720p-ultra-no-tessellation-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-1080p-ultra-no-tessellation-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-1080p-ultra-no-tessellation-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-720p-ultra-no-tessellation-ssao1-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-720p-ultra-no-tessellation-ssao1-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-1080p-ultra-no-tessellation-ssao1-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-1080p-ultra-no-tessellation-ssao1-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-720p-ultra-no-tessellation-ssao1-dof1-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-720p-ultra-no-tessellation-ssao1-dof1-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-1080p-ultra-no-tessellation-ssao1-dof1-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-1080p-ultra-no-tessellation-ssao1-dof1-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-720p-ultra-no-tessellation-ssao1-dof1-lod3-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-720p-ultra-no-tessellation-ssao1-dof1-lod3-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-1080p-ultra-no-tessellation-ssao1-dof1-lod3-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-1080p-ultra-no-tessellation-ssao1-dof1-lod3-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-720p-ultimate-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-720p-ultimate-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-x32-1080p-ultimate-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-x32-1080p-ultimate-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-compiler4-1080p-normal-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-compiler4-1080p-normal-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-241-compiler4-720p-normal-single-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-241-compiler4-720p-normal-single-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-fex-max-buffer-profile-excluded-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-fex-max-buffer-profile-excluded-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-relaxed-graphics-excluded-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-relaxed-graphics-excluded-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-dxvk-relaxed-graphics-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-dxvk-relaxed-graphics-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-fex-smc-none-excluded-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-fex-smc-none-excluded-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-fex-smc-none-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-fex-smc-none-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-steam-service-cpu0-abba-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-steam-service-cpu0-abba-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-steam-service-cpu0-excluded-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-steam-service-cpu0-excluded-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-safe-full-topology-cef-hold-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-safe-full-topology-cef-hold-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-safe-full-topology-cef-hold-alternating-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-safe-full-topology-cef-hold-alternating-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-safe-full-topology-cef-hold-pair-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-safe-full-topology-cef-hold-pair-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-safe-full-topology-x11-isolation-alternating-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-safe-full-topology-x11-isolation-alternating-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-safe-full-topology-x11-cpu01-pair-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-safe-full-topology-x11-cpu01-pair-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-safe-full-topology-x11-cpu01-alternating-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-safe-full-topology-x11-cpu01-alternating-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-safe-full-topology-raknet-exclusive-pair-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-safe-full-topology-raknet-exclusive-pair-40c-ceiling.sh" 700
install_one "$repo_root/scripts/test-tomb-raider-direct-safe-full-topology-raknet-exclusive-alternating-40c-ceiling.sh" \
    "$HOME/test-tomb-raider-direct-safe-full-topology-raknet-exclusive-alternating-40c-ceiling.sh" 700
install_one "$repo_root/scripts/start-gtaiv-native.sh" \
    "$HOME/start-gtaiv-native.sh" 700
install_one "$repo_root/scripts/stop-steam.sh" "$HOME/stop-steam.sh" 700
install_one "$repo_root/scripts/stop-steam-native.sh" \
    "$HOME/stop-steam-native.sh" 700
install_one "$repo_root/scripts/check-native-steam-stack.sh" \
    "$HOME/bin/check-native-steam-stack" 700
install_one "$repo_root/bin/ensure-sshd-supervised.sh" \
    "$HOME/bin/ensure-sshd-supervised" 700
install_one "$repo_root/bin/patch-steam-network-ui.sh" "$base/patch-steam-network-ui.sh" 700
install_one "$repo_root/bin/patch-steamwebhelper-native.sh" \
    "$base/patch-steamwebhelper-native.sh" 700
install_one "$repo_root/bin/prepare-proc-net-shadow.sh" "$base/prepare-proc-net-shadow.sh" 700
install_one "$repo_root/bin/prepare-pulseaudio-tcp.sh" "$base/prepare-pulseaudio-tcp.sh" 700
install_one "$repo_root/bin/prepare-runtime-direct-run.sh" \
    "$base/prepare-runtime-direct-run.sh" 700
install_one "$repo_root/bin/lsof" "$base/compat-bin/lsof" 700
install_one "$repo_root/bin/steam-arm64-process-match.sh" \
    "$base/compat-bin/steam-arm64-process-match.sh" 600
install_one "$repo_root/bin/steam-arm64-forward-dispatch" \
    "$base/compat-bin/steam-arm64-forward-dispatch" 700
install_one "$repo_root/scripts/steam-pipe-forward.py" \
    "$base/compat-bin/steam-pipe-forward.py" 700
install_one "$repo_root/bin/steam-arm64-session-guard.py" \
    "$base/compat-bin/steam-arm64-session-guard.py" 700
install_one "$repo_root/bin/steam-arm64-removable-library.py" \
    "$base/compat-bin/steam-arm64-removable-library.py" 700
install_one "$repo_root/scripts/configure-steam-app-proton.py" \
    "$HOME/bin/configure-steam-app-proton" 700
install_one "$repo_root/scripts/configure-no-mans-sky.py" \
    "$HOME/bin/configure-no-mans-sky" 700
install_one "$repo_root/scripts/prepare-runtime-direct-root.py" \
    "$base/compat-bin/prepare-runtime-direct-root.py" 700
install_one "$repo_root/scripts/configure-gtaiv-registry.py" \
    "$base/compat-bin/configure-gtaiv-registry.py" 700
install_one "$repo_root/scripts/configure-gtaiv-virtual-desktop.py" \
    "$base/compat-bin/configure-gtaiv-virtual-desktop.py" 700
install_one "$repo_root/scripts/configure-gtaiv-socialclub-wined3d.py" \
    "$base/compat-bin/configure-gtaiv-socialclub-wined3d.py" 700
install_one "$repo_root/scripts/configure-gtaiv-service-timeout.py" \
    "$base/compat-bin/configure-gtaiv-service-timeout.py" 700
install_one "$repo_root/scripts/configure-tombraider-performance.py" \
    "$base/compat-bin/configure-tombraider-performance.py" 700
install_one "$repo_root/scripts/manage-tombraider-dxvk-overlay.py" \
    "$base/compat-bin/manage-tombraider-dxvk-overlay.py" 700
install_one "$repo_root/scripts/prepare-dxvk-state-cache.py" \
    "$base/compat-bin/prepare-dxvk-state-cache.py" 700
install_one "$repo_root/scripts/configure-tombraider-cpu-topology.py" \
    "$base/compat-bin/configure-tombraider-cpu-topology.py" 700
install_one "$repo_root/scripts/configure-termux-x11-resolution.sh" \
    "$base/compat-bin/configure-termux-x11-resolution" 700
install_one "$repo_root/scripts/profile-live-game.py" \
    "$base/compat-bin/profile-live-game.py" 700
install_one "$repo_root/scripts/time-steam-game-launch.py" \
    "$base/compat-bin/time-steam-game-launch.py" 700
install_one "$repo_root/scripts/profile-steam-appid-acceptance.py" \
    "$base/compat-bin/profile-steam-appid-acceptance.py" 700
install_one "$repo_root/scripts/prefetch-game-files.py" \
    "$base/compat-bin/prefetch-game-files.py" 700
install_one "$repo_root/scripts/set-tombraider-affinity.py" \
    "$base/compat-bin/set-tombraider-affinity.py" 700
install_one "$repo_root/scripts/set-gtaiv-affinity.py" \
    "$base/compat-bin/set-gtaiv-affinity.py" 700
install_one "$repo_root/scripts/monitor-termux-game-session.sh" \
    "$base/compat-bin/monitor-termux-game-session.sh" 700
install_one "$repo_root/scripts/cleanup-steam-temp.py" \
    "$HOME/bin/cleanup-steam-temp" 700
install_one "$wrapper_stage" "$base/compat-bin/steam-arm64-bwrap-route" 700
unlink -- "$wrapper_stage"
wrapper_stage=""
unlink -- "$native_entry_stage"
native_entry_stage=""
unlink -- "$tmp_shim_stage"
tmp_shim_stage=""
unlink -- "$native_lsof_stage"
native_lsof_stage=""
trap - EXIT

install_one "$repo_root/config/hosts-ipv4" "$base/config/hosts-ipv4" 600
install_one "$repo_root/config/tombraider-startup-prefetch.json" \
    "$base/config/tombraider-startup-prefetch.json" 600
install_one "$repo_root/config/gtaiv-commandline-720p.txt" \
    "$base/gtaiv-exec-view-12210/commandline.txt" 600
gtaiv_prefix="$base/removable-library-compatdata/12210/pfx"
if [[ -d "$gtaiv_prefix/drive_c" ]]; then
    install_one "$repo_root/config/gtaiv-service-first.cmd" \
        "$gtaiv_prefix/drive_c/gtaiv-service-first.cmd" 600
fi
install_one "$repo_root/config/steam-arm64-compatibilitytools.vdf.in" "$base/config/steam-arm64-compatibilitytools.vdf.in" 600
install_one "$repo_root/desktop/steam-arm.desktop" "$HOME/.local/share/applications/steam-arm.desktop" 600

mkdir -p "$base/mesa-kgsl/icd.d"
sed "s|@HOME@|$HOME|g" "$repo_root/config/freedreno-private.json.in" > "$base/mesa-kgsl/icd.d/freedreno-private.json.tmp"
mv "$base/mesa-kgsl/icd.d/freedreno-private.json.tmp" "$base/mesa-kgsl/icd.d/freedreno-private.json"

python3 "$base/compat-bin/prepare-runtime-direct-root.py" --base "$base"
"$base/prepare-runtime-direct-run.sh" "$base"

printf 'Installed project files. Backups: %s\n' "$backup"
