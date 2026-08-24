#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail
umask 077

base=${STEAM_ARM64_BASE:-$HOME/steam-arm64}
dispatcher=${TOMB_RAIDER_DIRECT_DISPATCHER:-$base/compat-bin/pressure-vessel-direct-dispatch.py}
default_python=/data/data/com.termux/files/usr/bin/python3
python=${TOMB_RAIDER_DIRECT_PYTHON:-$default_python}
launcher=${TOMB_RAIDER_DIRECT_LAUNCHER:-$HOME/start-steam-native.sh}
prepare=${TOMB_RAIDER_DIRECT_PREPARE:-$base/compat-bin/prepare-proton-direct-wine.py}
affinity=${TOMB_RAIDER_DIRECT_AFFINITY:-$base/compat-bin/set-tombraider-affinity.py}
topology_checker=${TOMB_RAIDER_DIRECT_TOPOLOGY_CHECKER:-$base/compat-bin/configure-tombraider-cpu-topology.py}
dxvk_overlay=${TOMB_RAIDER_DIRECT_DXVK_OVERLAY:-$base/compat-bin/manage-tombraider-dxvk-overlay.py}
mode=${TOMB_RAIDER_DIRECT_MODE:-tombraider}
diagnostics=${TOMB_RAIDER_DIRECT_DIAGNOSTICS:-0}
command_stream=${TOMB_RAIDER_BVB_COMMAND_STREAM:-strict}
mapped_memory=${TOMB_RAIDER_BVB_MAPPED_MEMORY:-strict}
descriptor_journal=${TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL:-strict}
first_rejection_diagnostic=${TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC-0}
raknet_recv_sleep_us=${TOMB_RAIDER_RAKNET_RECV_SLEEP_US:-0}
# Generation 5 is an exact FEX-2605, binary-hash-keyed cache validated again
# by the dispatcher before it reaches the final game process. Keep the
# recording/max-buffer mode as an explicit reverse control.
fex_code_cache=${TOMB_RAIDER_FEX_CODE_CACHE:-compiled}
fex_smc_checks=${TOMB_RAIDER_FEX_SMC_CHECKS:-mtrack}
dxvk_relaxed_graphics_barriers=${TOMB_RAIDER_DXVK_RELAXED_GRAPHICS_BARRIERS:-off}
dxvk_compiler_threads=${TOMB_RAIDER_DXVK_COMPILER_THREADS:-0}
# The hash-pinned x32 2.4.1 payload is both the fastest validated renderer and
# the fastest measured AppID-to-window path. Keep bundled/1.10.3 as explicit
# reverse controls rather than silently falling back if validation fails.
dxvk_variant=${TOMB_RAIDER_DXVK_VARIANT:-dxvk-2.4.1-x32}
benchmark_preset=${TOMB_RAIDER_BENCHMARK_PRESET:-registry}
child_preload=${TOMB_RAIDER_DIRECT_CHILD_PRELOAD:-full}
vulkan_trace=${TOMB_RAIDER_VULKAN_TRACE:-0}
vulkan_trace_preload=${TOMB_RAIDER_VULKAN_TRACE_PRELOAD:-$HOME/bionic-vulkan-bridge/out/glibc/libbvb-vulkan-resolve-trace.so}
raknet_nice=${TOMB_RAIDER_RAKNET_NICE:-}
game_cpus=${TOMB_RAIDER_GAME_CPUS:-1-7}
socket=$base/run/native-runtime-dispatch/dispatch.sock
state=$base/run/tombraider-direct-dispatch.state
start_gate=${STEAM_ARM64_DIRECT_START_GATE:-}
start_gate_ack_timeout=${STEAM_ARM64_DIRECT_START_GATE_ACK_TIMEOUT:-300}
start_gate_waiting=
start_gate_launcher_ready=

fail() {
    printf 'start-tombraider-direct-dispatch: %s\n' "$*" >&2
    exit 1
}

[[ $mode == proton-entry-smoke || $mode == proton-cmd-smoke ||
    $mode == proton-arm64-cmd-smoke || $mode == fex-offline-compile ||
    $mode == tombraider ||
    $mode == tombraider-benchmark || $mode == tombraider-diagnostic ]] ||
    fail "unsupported direct-dispatch mode: $mode"
[[ $diagnostics == 0 || $diagnostics == 1 ]] ||
    fail 'TOMB_RAIDER_DIRECT_DIAGNOSTICS must be 0 or 1'
[[ $command_stream == strict || $command_stream == shared ]] ||
    fail 'TOMB_RAIDER_BVB_COMMAND_STREAM must be strict or shared'
[[ $mapped_memory == strict || $mapped_memory == shared ||
    $mapped_memory == direct ]] ||
    fail 'TOMB_RAIDER_BVB_MAPPED_MEMORY must be strict, shared, or direct'
[[ $descriptor_journal == strict || $descriptor_journal == shared ]] ||
    fail 'TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL must be strict or shared'
[[ $first_rejection_diagnostic == 0 || $first_rejection_diagnostic == 1 ]] ||
    fail 'TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC must be 0 or 1'
[[ $raknet_recv_sleep_us == 0 || $raknet_recv_sleep_us == 1000 ]] ||
    fail 'TOMB_RAIDER_RAKNET_RECV_SLEEP_US must be 0 or 1000'
[[ $fex_code_cache == off || $fex_code_cache == on ||
    $fex_code_cache == compiled ]] ||
    fail 'TOMB_RAIDER_FEX_CODE_CACHE must be off, on, or compiled'
[[ $fex_smc_checks == mtrack || $fex_smc_checks == none ]] ||
    fail 'TOMB_RAIDER_FEX_SMC_CHECKS must be mtrack or none'
[[ $dxvk_relaxed_graphics_barriers == off ||
    $dxvk_relaxed_graphics_barriers == on ]] ||
    fail 'TOMB_RAIDER_DXVK_RELAXED_GRAPHICS_BARRIERS must be off or on'
[[ $dxvk_compiler_threads =~ ^(0|[1-9]|1[0-6])$ ]] ||
    fail 'TOMB_RAIDER_DXVK_COMPILER_THREADS must be 0 through 16'
[[ $dxvk_variant == bundled || $dxvk_variant == dxvk-1.10.3-x32 ||
    $dxvk_variant == dxvk-2.4.1-x32 ]] ||
    fail 'TOMB_RAIDER_DXVK_VARIANT must be bundled, dxvk-1.10.3-x32, or dxvk-2.4.1-x32'
[[ $benchmark_preset == registry ||
    $benchmark_preset =~ ^(720p|1080p)-(high|ultra|ultimate|ultra-no-tessellation|ultra-no-tessellation-ssao1|ultra-no-tessellation-ssao1-dof1|ultra-no-tessellation-ssao1-dof1-lod3|ultra-no-tessellation-ssao1-dof1-shadow1|ultra-no-tessellation-ssao1-dof1-shadow0)$ ]] ||
    fail 'TOMB_RAIDER_BENCHMARK_PRESET must be registry or a supported resolution-quality pair'
if [[ $mode != tombraider-benchmark && $benchmark_preset != registry ]]; then
    fail 'a Tomb Raider benchmark preset is valid only in tombraider-benchmark mode'
fi
if [[ $command_stream == shared && ${STEAM_ARM64_BVB_VULKAN:-0} != 1 ]]; then
    fail 'shared BVB command stream requires STEAM_ARM64_BVB_VULKAN=1'
fi
if [[ $mapped_memory != strict && ${STEAM_ARM64_BVB_VULKAN:-0} != 1 ]]; then
    fail "$mapped_memory BVB mapped memory requires STEAM_ARM64_BVB_VULKAN=1"
fi
if [[ $descriptor_journal == shared && ${STEAM_ARM64_BVB_VULKAN:-0} != 1 ]]; then
    fail 'shared BVB descriptor journal requires STEAM_ARM64_BVB_VULKAN=1'
fi
if [[ $first_rejection_diagnostic == 1 && ${STEAM_ARM64_BVB_VULKAN:-0} != 1 ]]; then
    fail 'BVB first-rejection diagnostic requires STEAM_ARM64_BVB_VULKAN=1'
fi
# Preserve only the validated local value. The actual ICD switch is injected by
# the dispatcher into the final Wine/DXVK environment, never into Steam/CEF.
unset BVB_COMMAND_STREAM STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM \
    TOMB_RAIDER_BVB_COMMAND_STREAM BVB_MAPPED_MEMORY \
    STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY TOMB_RAIDER_BVB_MAPPED_MEMORY \
    BVB_DESCRIPTOR_JOURNAL STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL \
    TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL \
    BVB_FIRST_REJECTION_DIAGNOSTIC \
    STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC \
    TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC \
    TGCOMPAT_RAKNET_RECV_SLEEP_US \
    STEAM_ARM64_DIRECT_RAKNET_RECV_SLEEP_US \
    TOMB_RAIDER_RAKNET_RECV_SLEEP_US \
    FEX_ENABLECODECACHINGWIP FEX_APP_CACHE_LOCATION \
    STEAM_ARM64_DIRECT_FEX_CODE_CACHE TOMB_RAIDER_FEX_CODE_CACHE \
    FEX_SMC_CHECKS STEAM_ARM64_DIRECT_FEX_SMC_CHECKS \
    TOMB_RAIDER_FEX_SMC_CHECKS \
    DXVK_CONFIG DXVK_CONFIG_FILE \
    WINEDLLPATH STEAM_ARM64_DIRECT_DXVK_VARIANT \
    STEAM_ARM64_BWRAP_DXVK_VARIANT \
    TOMB_RAIDER_DXVK_VARIANT \
    STEAM_ARM64_DIRECT_TOMBRAIDER_BENCHMARK_PRESET \
    TOMB_RAIDER_BENCHMARK_PRESET \
    STEAMCLIENTTERMUX_DXVK_COMPILER_THREADS \
    STEAM_ARM64_DIRECT_DXVK_COMPILER_THREADS \
    STEAM_ARM64_BWRAP_DXVK_COMPILER_THREADS \
    TOMB_RAIDER_DXVK_COMPILER_THREADS \
    STEAM_ARM64_DIRECT_DXVK_RELAXED_GRAPHICS_BARRIERS \
    TOMB_RAIDER_DXVK_RELAXED_GRAPHICS_BARRIERS
[[ $vulkan_trace == 0 || $vulkan_trace == 1 ]] ||
    fail 'TOMB_RAIDER_VULKAN_TRACE must be 0 or 1'
[[ $child_preload == full || $child_preload == lean ||
    $child_preload == lean-tmp-only || $child_preload == lean-debug-wait ]] ||
    fail 'TOMB_RAIDER_DIRECT_CHILD_PRELOAD must be full, lean, lean-tmp-only, or lean-debug-wait'
if [[ $raknet_recv_sleep_us == 1000 && $child_preload != lean &&
      $child_preload != lean-debug-wait ]]; then
    fail 'RakNet receive backoff requires a lean final-process preload'
fi
if [[ -n $raknet_nice ]]; then
    [[ $raknet_nice =~ ^[0-9]+$ ]] && (( raknet_nice <= 19 )) ||
        fail 'TOMB_RAIDER_RAKNET_NICE must be an integer from 0 through 19'
fi
[[ $game_cpus == 1-7 || $game_cpus == 2-7 ]] ||
    fail 'TOMB_RAIDER_GAME_CPUS must be 1-7 or 2-7'
[[ -d $base/run && ! -L $base/run && -d $base/logs && ! -L $base/logs ]] ||
    fail "Steam run or log directory is unavailable below $base"
if [[ -n $start_gate ]]; then
    if ! [[ $start_gate_ack_timeout =~ ^[0-9]+$ ]] ||
            (( start_gate_ack_timeout < 1 || start_gate_ack_timeout > 600 )); then
        fail 'STEAM_ARM64_DIRECT_START_GATE_ACK_TIMEOUT must be 1 through 600'
    fi
    gate_directory=$base/run/bvb
    [[ -d $gate_directory && ! -L $gate_directory ]] ||
        fail "BVB launch-gate directory is unavailable: $gate_directory"
    [[ ${start_gate%/*} == "$gate_directory" &&
       ${start_gate##*/} =~ ^tombraider-start-[0-9]{8}T[0-9]{6}Z-[0-9]+\.gate$ ]] ||
        fail "direct start gate is outside the controlled path: $start_gate"
    start_gate_waiting=$start_gate.waiting
    start_gate_launcher_ready=$start_gate.launcher-ready
    [[ ! -e $start_gate && ! -L $start_gate &&
       ! -e $start_gate_launcher_ready && ! -L $start_gate_launcher_ready ]] ||
        fail 'direct start gate or launcher-ready marker already exists'
fi
[[ -x $python && (! -L $python || $python == "$default_python") ]] ||
    fail "Termux Python is unavailable: $python"
[[ -f $dispatcher && ! -L $dispatcher ]] ||
    fail "direct dispatcher is unavailable: $dispatcher"
if [[ $vulkan_trace == 1 ]]; then
    [[ $child_preload == lean || $child_preload == lean-tmp-only ||
        $child_preload == lean-debug-wait ]] ||
        fail 'Vulkan tracing requires a lean final-process preload profile'
    [[ -f $vulkan_trace_preload && ! -L $vulkan_trace_preload ]] ||
        fail "Vulkan trace preload is unavailable: $vulkan_trace_preload"
fi
[[ -x $launcher && ! -L $launcher ]] ||
    fail "native Steam launcher is unavailable: $launcher"
[[ -x $prepare && ! -L $prepare ]] ||
    fail "Proton direct Wine preparation tool is unavailable: $prepare"
if [[ $mode == tombraider || $mode == tombraider-benchmark ||
    $mode == tombraider-diagnostic ]]; then
    [[ -f $affinity && ! -L $affinity ]] ||
        fail "Tomb Raider affinity guard is unavailable: $affinity"
    [[ -f $topology_checker && ! -L $topology_checker ]] ||
        fail "Tomb Raider CPU-topology checker is unavailable: $topology_checker"
    topology_status=$("$python" "$topology_checker" --check) ||
        fail 'Tomb Raider CPU-topology fix check failed'
    [[ $topology_status =~ ^Tomb\ Raider\ CPU\ topology\ fix:\ enabled\;\ SHA-256\ [0-9a-f]{64}$ ]] ||
        fail "Tomb Raider CPU-topology fix is not enabled: $topology_status"
fi
# DXVK is game-local. Compiler/smoke modes never load it and must not mutate
# the game directory merely because the game default selects an overlay.
if [[ $dxvk_variant != bundled && $mode == tombraider* ]]; then
    [[ -x $dxvk_overlay && ! -L $dxvk_overlay ]] ||
        fail "transactional DXVK overlay tool is unavailable: $dxvk_overlay"
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
timing_log=$base/logs/tombraider-direct-launch-timing-$stamp-$$.log
(set -o noclobber; : >"$timing_log") 2>/dev/null ||
    fail "could not create direct-launch timing log: $timing_log"
chmod 600 "$timing_log"

launch_phase() {
    local event=$1 detail=${2:-none} clock_value whole fraction
    [[ $event =~ ^[a-z][a-z0-9_]*$ &&
       $detail =~ ^[A-Za-z0-9_.:/=-]+$ ]] ||
        fail "invalid direct-launch phase: $event $detail"
    clock_value=${EPOCHREALTIME:-}
    [[ $clock_value =~ ^[0-9]+([.][0-9]+)?$ ]] ||
        fail 'Bash realtime clock is unavailable'
    whole=${clock_value%%.*}
    if [[ $clock_value == *.* ]]; then
        fraction=${clock_value#*.}00
        fraction=${fraction:0:2}
    else
        fraction=00
    fi
    printf 'steam-arm64-launch-phase version=1 route=direct event=%s clock=realtime timestamp_cs=%s detail=%s\n' \
        "$event" "$((10#$whole * 100 + 10#$fraction))" "$detail" \
        >>"$timing_log"
}

launch_phase wrapper_start "mode=$mode"
launch_phase prepare_start
"$python" "$prepare" prepare --base "$base"
launch_phase prepare_complete

vulkan_trace_file=
benchmark_ini=
benchmark_ini_windows=
if [[ $benchmark_preset != registry ]]; then
    benchmark_ini=$base/run/tombraider-benchmark-$benchmark_preset.ini
    [[ ! -e $benchmark_ini && ! -L $benchmark_ini ]] ||
        fail "controlled Tomb Raider benchmark INI already exists: $benchmark_ini"
    case $benchmark_preset in
        720p-*)
            benchmark_width=1280
            benchmark_height=720
            ;;
        1080p-*)
            benchmark_width=1920
            benchmark_height=1080
            ;;
    esac
    case $benchmark_preset in
        *-high) benchmark_quality_level=2 ;;
        *-ultra) benchmark_quality_level=3 ;;
        *-ultra-no-tessellation) benchmark_quality_level=3 ;;
        *-ultra-no-tessellation-ssao1) benchmark_quality_level=3 ;;
        *-ultra-no-tessellation-ssao1-dof1) benchmark_quality_level=3 ;;
        *-ultra-no-tessellation-ssao1-dof1-lod3) benchmark_quality_level=3 ;;
        *-ultra-no-tessellation-ssao1-dof1-shadow1) benchmark_quality_level=3 ;;
        *-ultra-no-tessellation-ssao1-dof1-shadow0) benchmark_quality_level=3 ;;
        *-ultimate) benchmark_quality_level=4 ;;
    esac
    benchmark_extra_lines=()
    if [[ $benchmark_preset == *-ultra-no-tessellation ||
        $benchmark_preset == *-ultra-no-tessellation-ssao1 ||
        $benchmark_preset == *-ultra-no-tessellation-ssao1-dof1 ||
        $benchmark_preset == *-ultra-no-tessellation-ssao1-dof1-lod3 ||
        $benchmark_preset == *-ultra-no-tessellation-ssao1-dof1-shadow1 ||
        $benchmark_preset == *-ultra-no-tessellation-ssao1-dof1-shadow0 ]]; then
        benchmark_extra_lines+=('EnableTessellation = 0')
    fi
    if [[ $benchmark_preset == *-ultra-no-tessellation-ssao1 ||
        $benchmark_preset == *-ultra-no-tessellation-ssao1-dof1 ||
        $benchmark_preset == *-ultra-no-tessellation-ssao1-dof1-lod3 ||
        $benchmark_preset == *-ultra-no-tessellation-ssao1-dof1-shadow1 ||
        $benchmark_preset == *-ultra-no-tessellation-ssao1-dof1-shadow0 ]]; then
        benchmark_extra_lines+=('SSAOMode = 1')
    fi
    if [[ $benchmark_preset == *-ultra-no-tessellation-ssao1-dof1 ||
        $benchmark_preset == *-ultra-no-tessellation-ssao1-dof1-lod3 ||
        $benchmark_preset == *-ultra-no-tessellation-ssao1-dof1-shadow1 ||
        $benchmark_preset == *-ultra-no-tessellation-ssao1-dof1-shadow0 ]]; then
        benchmark_extra_lines+=('DOFQuality = 1')
    fi
    if [[ $benchmark_preset == *-ultra-no-tessellation-ssao1-dof1-lod3 ]]; then
        benchmark_extra_lines+=('LODScale = 3')
    fi
    if [[ $benchmark_preset == *-ultra-no-tessellation-ssao1-dof1-shadow1 ]]; then
        benchmark_extra_lines+=('ShadowResolution = 1')
    fi
    if [[ $benchmark_preset == *-ultra-no-tessellation-ssao1-dof1-shadow0 ]]; then
        benchmark_extra_lines+=('ShadowResolution = 0')
    fi
    benchmark_ini_lines=( \
        "QualityLevel = $benchmark_quality_level" \
        'Fullscreen = 1' \
        'ExclusiveFullscreen = 1' \
        'VSyncMode = 0' \
        "FullscreenWidth = $benchmark_width" \
        "FullscreenHeight = $benchmark_height" \
        'FullscreenRefreshRate = 60' \
        'EnableMotionBlur = 0' \
        "${benchmark_extra_lines[@]}")
    (set -o noclobber; printf '%s\n' \
        "${benchmark_ini_lines[@]}" >"$benchmark_ini") 2>/dev/null ||
        fail "could not create controlled Tomb Raider benchmark INI: $benchmark_ini"
    chmod 600 "$benchmark_ini"
    benchmark_ini_windows=Z:${benchmark_ini//\//\\}
fi
if [[ $vulkan_trace == 1 ]]; then
    vulkan_trace_file=$base/logs/tombraider-vulkan-resolve-$stamp-$$.tsv
    (set -o noclobber; : >"$vulkan_trace_file") 2>/dev/null ||
        fail "could not create private Vulkan trace output: $vulkan_trace_file"
fi
server_log=$base/logs/tombraider-direct-$mode-$child_preload-$stamp.log
launcher_log=$base/logs/tombraider-direct-launcher-$mode-$child_preload-$stamp.log
server_pid=
affinity_pid=
affinity_log=
dxvk_overlay_active=0
cleanup() {
    if [[ -n ${affinity_pid:-} ]] && kill -0 "$affinity_pid" 2>/dev/null; then
        kill -TERM "$affinity_pid" 2>/dev/null || true
        wait "$affinity_pid" 2>/dev/null || true
    fi
    if [[ -n ${server_pid:-} ]] && kill -0 "$server_pid" 2>/dev/null; then
        kill -TERM "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
    if (( dxvk_overlay_active )); then
        "$python" "$dxvk_overlay" restore --base "$base" ||
            printf 'start-tombraider-direct-dispatch: DXVK overlay recovery failed; retained state requires explicit recovery\n' >&2
        dxvk_overlay_active=0
    fi
    if [[ -n ${benchmark_ini:-} && -f $benchmark_ini && ! -L $benchmark_ini ]]; then
        rm -f -- "$benchmark_ini"
    fi
}
trap cleanup EXIT HUP INT TERM

if [[ $dxvk_variant != bundled && $mode == tombraider* ]]; then
    launch_phase dxvk_overlay_start "variant=$dxvk_variant"
    "$python" "$dxvk_overlay" activate --base "$base" \
        --variant "$dxvk_variant"
    dxvk_overlay_active=1
    launch_phase dxvk_overlay_complete "variant=$dxvk_variant"
fi

dispatcher_environment=(
    "STEAM_ARM64_DIRECT_DIAGNOSTICS=$diagnostics"
    "STEAM_ARM64_DIRECT_CHILD_PRELOAD=$child_preload"
    "STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM=$command_stream"
    "STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY=$mapped_memory"
    "STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL=$descriptor_journal"
    "STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC=$first_rejection_diagnostic"
    "STEAM_ARM64_DIRECT_RAKNET_RECV_SLEEP_US=$raknet_recv_sleep_us"
    "STEAM_ARM64_DIRECT_FEX_CODE_CACHE=$fex_code_cache"
    "STEAM_ARM64_DIRECT_FEX_SMC_CHECKS=$fex_smc_checks"
    "STEAM_ARM64_DIRECT_DXVK_RELAXED_GRAPHICS_BARRIERS=$dxvk_relaxed_graphics_barriers"
    "STEAM_ARM64_DIRECT_DXVK_COMPILER_THREADS=$dxvk_compiler_threads"
    "STEAM_ARM64_DIRECT_DXVK_VARIANT=$dxvk_variant"
    "STEAM_ARM64_DIRECT_TOMBRAIDER_BENCHMARK_PRESET=$benchmark_preset"
)
if [[ $vulkan_trace == 1 ]]; then
    dispatcher_environment+=(
        "STEAM_ARM64_VULKAN_TRACE_PRELOAD=$vulkan_trace_preload"
        "STEAM_ARM64_VULKAN_TRACE_FILE=$vulkan_trace_file"
    )
fi
launch_phase service_start
env -u BVB_COMMAND_STREAM -u TOMB_RAIDER_BVB_COMMAND_STREAM \
    -u BVB_MAPPED_MEMORY -u TOMB_RAIDER_BVB_MAPPED_MEMORY \
    -u BVB_DESCRIPTOR_JOURNAL -u TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL \
    -u BVB_FIRST_REJECTION_DIAGNOSTIC \
    -u TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC \
    -u TGCOMPAT_RAKNET_RECV_SLEEP_US \
    -u STEAM_ARM64_DIRECT_RAKNET_RECV_SLEEP_US \
    -u TOMB_RAIDER_RAKNET_RECV_SLEEP_US \
    -u FEX_ENABLECODECACHINGWIP -u FEX_APP_CACHE_LOCATION \
    -u TOMB_RAIDER_FEX_CODE_CACHE \
    -u FEX_SMC_CHECKS -u TOMB_RAIDER_FEX_SMC_CHECKS \
    -u DXVK_CONFIG -u DXVK_CONFIG_FILE -u WINEDLLPATH \
    -u STEAMCLIENTTERMUX_DXVK_COMPILER_THREADS \
    -u STEAM_ARM64_BWRAP_DXVK_COMPILER_THREADS \
    -u TOMB_RAIDER_DXVK_COMPILER_THREADS \
    -u STEAM_ARM64_BWRAP_DXVK_VARIANT \
    -u TOMB_RAIDER_DXVK_VARIANT \
    -u TOMB_RAIDER_BENCHMARK_PRESET \
    -u TOMB_RAIDER_DXVK_RELAXED_GRAPHICS_BARRIERS \
    "${dispatcher_environment[@]}" \
    "$python" "$dispatcher" serve --base "$base" --mode "$mode" \
    >"$server_log" 2>&1 &
server_pid=$!
for _ in $(seq 1 100); do
    [[ -S $socket ]] && break
    kill -0 "$server_pid" 2>/dev/null || break
    sleep 0.1
done
[[ -S $socket && -n $server_pid ]] || {
    sed -n '1,80p' "$server_log" >&2 || true
    fail 'direct dispatcher did not create its socket'
}
launch_phase service_ready "pid=$server_pid"

if [[ $mode == tombraider || $mode == tombraider-benchmark ||
    $mode == tombraider-diagnostic ]]; then
    affinity_log=$base/logs/tombraider-direct-affinity-$stamp.log
    affinity_arguments=(--watch --raknet-cpu1 --steam-base "$base" --game-cpus "$game_cpus")
    if [[ -n $raknet_nice ]]; then
        affinity_arguments+=(--raknet-nice "$raknet_nice")
    fi
    "$python" "$affinity" "${affinity_arguments[@]}" \
        --wait-for-cpu-log \
        --poll-seconds 0.25 \
        --lock-file "$base/runtime/tomb-raider-affinity.lock" \
        >"$affinity_log" 2>&1 &
    affinity_pid=$!
fi

printf 'pid=%s\nmode=%s\nchild_preload=%s\nraknet_recv_sleep_us=%s\nfex_code_cache=%s\nfex_smc_checks=%s\ndxvk_relaxed_graphics_barriers=%s\ndxvk_compiler_threads=%s\ndxvk_variant=%s\ngame_cpus=%s\nvulkan_trace_file=%s\ntiming_log=%s\nserver_pid=%s\nserver_log=%s\nlauncher_log=%s\naffinity_log=%s\nstatus=launching\n' \
    "$$" "$mode" "$child_preload" "$raknet_recv_sleep_us" "$fex_code_cache" "$fex_smc_checks" "$dxvk_relaxed_graphics_barriers" "$dxvk_compiler_threads" "$dxvk_variant" "$game_cpus" "$vulkan_trace_file" \
    "$timing_log" "$server_pid" "$server_log" "$launcher_log" "$affinity_log" >"$state"

set +e
game_arguments=(-nolauncher)
skip_outer_affinity_guard=0
if [[ $mode == tombraider-benchmark ]]; then
    if [[ $benchmark_preset == registry ]]; then
        game_arguments+=(-benchmark)
    else
        game_arguments+=(-benchmarkini "$benchmark_ini_windows")
    fi
elif [[ $mode == fex-offline-compile ]]; then
    skip_outer_affinity_guard=1
fi
launch_phase steam_request_start "appid=203160"
env -u BVB_COMMAND_STREAM -u STEAM_ARM64_DIRECT_BVB_COMMAND_STREAM \
    -u TOMB_RAIDER_BVB_COMMAND_STREAM \
    -u BVB_MAPPED_MEMORY -u STEAM_ARM64_DIRECT_BVB_MAPPED_MEMORY \
    -u TOMB_RAIDER_BVB_MAPPED_MEMORY \
    -u BVB_DESCRIPTOR_JOURNAL \
    -u STEAM_ARM64_DIRECT_BVB_DESCRIPTOR_JOURNAL \
    -u TOMB_RAIDER_BVB_DESCRIPTOR_JOURNAL \
    -u BVB_FIRST_REJECTION_DIAGNOSTIC \
    -u STEAM_ARM64_DIRECT_BVB_FIRST_REJECTION_DIAGNOSTIC \
    -u TOMB_RAIDER_BVB_FIRST_REJECTION_DIAGNOSTIC \
    -u TGCOMPAT_RAKNET_RECV_SLEEP_US \
    -u STEAM_ARM64_DIRECT_RAKNET_RECV_SLEEP_US \
    -u TOMB_RAIDER_RAKNET_RECV_SLEEP_US \
    -u FEX_ENABLECODECACHINGWIP -u FEX_APP_CACHE_LOCATION \
    -u STEAM_ARM64_DIRECT_FEX_CODE_CACHE \
    -u TOMB_RAIDER_FEX_CODE_CACHE \
    -u FEX_SMC_CHECKS -u STEAM_ARM64_DIRECT_FEX_SMC_CHECKS \
    -u TOMB_RAIDER_FEX_SMC_CHECKS \
    -u DXVK_CONFIG -u DXVK_CONFIG_FILE -u WINEDLLPATH \
    -u STEAMCLIENTTERMUX_DXVK_COMPILER_THREADS \
    -u STEAM_ARM64_DIRECT_DXVK_COMPILER_THREADS \
    -u STEAM_ARM64_BWRAP_DXVK_COMPILER_THREADS \
    -u TOMB_RAIDER_DXVK_COMPILER_THREADS \
    -u STEAM_ARM64_DIRECT_DXVK_VARIANT \
    -u STEAM_ARM64_BWRAP_DXVK_VARIANT \
    -u TOMB_RAIDER_DXVK_VARIANT \
    -u STEAM_ARM64_DIRECT_TOMBRAIDER_BENCHMARK_PRESET \
    -u TOMB_RAIDER_BENCHMARK_PRESET \
    -u STEAM_ARM64_DIRECT_DXVK_RELAXED_GRAPHICS_BARRIERS \
    -u TOMB_RAIDER_DXVK_RELAXED_GRAPHICS_BARRIERS \
    STEAM_ARM64_BWRAP_DIRECT=1 \
    STEAM_ARM64_SKIP_GAME_AFFINITY_GUARD=$skip_outer_affinity_guard \
    STEAM_BACKGROUND=1 \
    STEAM_PROCESS_TIMEOUT=${STEAM_PROCESS_TIMEOUT:-180} \
    STEAM_WINDOW_TIMEOUT=${STEAM_WINDOW_TIMEOUT:-300} \
    STEAM_APP_TIMEOUT=${STEAM_APP_TIMEOUT:-300} \
    "$launcher" --appid 203160 -- "${game_arguments[@]}" >"$launcher_log" 2>&1
launcher_status=$?
launch_phase steam_request_complete "status=$launcher_status"
if (( launcher_status == 0 )) && [[ -n $start_gate ]]; then
    for _ in $(seq 1 $((start_gate_ack_timeout * 20))); do
        [[ -L $start_gate_waiting || -f $start_gate_waiting ]] && break
        kill -0 "$server_pid" 2>/dev/null || break
        sleep 0.05
    done
    if [[ -f $start_gate_waiting && ! -L $start_gate_waiting ]] &&
       (set -o noclobber; : >"$start_gate_launcher_ready") 2>/dev/null; then
        launch_phase start_gate_ready
    else
        printf 'start-tombraider-direct-dispatch: direct dispatch did not reach the launch gate within %ss after Steam acknowledgement\n' \
            "$start_gate_ack_timeout" \
            >>"$launcher_log"
        launcher_status=1
    fi
fi
if (( launcher_status != 0 )) && kill -0 "$server_pid" 2>/dev/null; then
    kill -TERM "$server_pid" 2>/dev/null || true
fi
wait "$server_pid"
server_status=$?
launch_phase service_complete "status=$server_status"
set -e
server_pid=
if [[ -n ${affinity_pid:-} ]] && kill -0 "$affinity_pid" 2>/dev/null; then
    kill -TERM "$affinity_pid" 2>/dev/null || true
    wait "$affinity_pid" 2>/dev/null || true
fi
affinity_pid=

printf 'pid=%s\nmode=%s\nchild_preload=%s\nraknet_recv_sleep_us=%s\nfex_code_cache=%s\nfex_smc_checks=%s\ndxvk_relaxed_graphics_barriers=%s\ndxvk_compiler_threads=%s\ndxvk_variant=%s\ngame_cpus=%s\nvulkan_trace_file=%s\ntiming_log=%s\nserver_log=%s\nlauncher_log=%s\naffinity_log=%s\nstatus=complete\nlauncher_status=%s\nserver_status=%s\n' \
    "$$" "$mode" "$child_preload" "$raknet_recv_sleep_us" "$fex_code_cache" "$fex_smc_checks" "$dxvk_relaxed_graphics_barriers" "$dxvk_compiler_threads" "$dxvk_variant" "$game_cpus" "$vulkan_trace_file" \
    "$timing_log" "$server_log" "$launcher_log" "$affinity_log" "$launcher_status" \
    "$server_status" >"$state"
printf 'Tomb Raider direct dispatch completed: mode=%s child_preload=%s launcher=%s server=%s trace=%s server_log=%s launcher_log=%s\n' \
    "$mode" "$child_preload" "$launcher_status" "$server_status" \
    "$vulkan_trace_file" "$server_log" "$launcher_log"
if (( launcher_status != 0 )); then
    exit "$launcher_status"
fi
exit "$server_status"
