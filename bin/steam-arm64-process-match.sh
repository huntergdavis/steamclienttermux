#!/data/data/com.termux/files/usr/bin/bash

# Authenticated-session functions intentionally publish these globals to a
# caller that sources this file.
# shellcheck disable=SC2034

# Shared exact-process matcher for ordinary Steam executables and native
# launches whose real argv[0] is the content-addressed glibc loader.
steam_arm64_process_matches() {
    local pid=$1 target=$2 proc_root=${STEAM_ARM64_PROC_ROOT:-/proc}
    local index saw_target=0
    local -a arguments=()

    [[ $pid =~ ^[1-9][0-9]*$ && $target == /* &&
            -r $proc_root/$pid/cmdline ]] || return 1
    mapfile -d '' -t arguments < "$proc_root/$pid/cmdline" || return 1
    ((${#arguments[@]} > 0)) || return 1
    [[ ${arguments[0]} == "$target" ]] && return 0
    [[ ${arguments[0]} == "$HOME/.local/share/tgcompat/glibc/"*/lib/ld-linux-aarch64.so.1 ]] ||
        return 1
    for ((index = 0; index < ${#arguments[@]}; index++)); do
        [[ ${arguments[index]} == "$target" ]] && saw_target=1
        if [[ ${arguments[index]} == --argv0 &&
                ${arguments[index + 1]:-} == "$target" ]]; then
            ((index++))
        fi
    done
    ((saw_target == 1)) || return 1
    for ((index = 0; index + 1 < ${#arguments[@]}; index++)); do
        if [[ ${arguments[index]} == --argv0 &&
                ${arguments[index + 1]} == "$target" ]]; then
            return 0
        fi
    done
    return 1
}

# Read field 22 from /proc/PID/stat without treating spaces or ')' inside the
# parenthesized comm field as separators. Callers use this to reject PID reuse
# between discovery and an authenticated warm handoff.
steam_arm64_process_start_ticks() {
    local pid=$1 proc_root=${STEAM_ARM64_PROC_ROOT:-/proc}
    local stat_line stat_tail
    local -a stat_fields=()

    [[ $pid =~ ^[1-9][0-9]*$ && -r $proc_root/$pid/stat ]] || return 1
    IFS= read -r stat_line < "$proc_root/$pid/stat" || return 1
    [[ $stat_line == "$pid ("* && $stat_line == *') '* ]] || return 1
    stat_tail=${stat_line##*) }
    read -r -a stat_fields <<<"$stat_tail"
    ((${#stat_fields[@]} >= 20)) || return 1
    [[ ${stat_fields[19]} =~ ^[1-9][0-9]*$ ]] || return 1
    printf '%s\n' "${stat_fields[19]}"
}

# Match only the explicit content-addressed-loader form emitted by
# steam-arm-native. This deliberately does not accept the broader direct form
# used by stop/diagnostic tooling.
steam_arm64_native_loader_process_matches() {
    local pid=$1 target=$2 loader=$3 library_path=$4
    local proc_root=${STEAM_ARM64_PROC_ROOT:-/proc}
    local index saw_argv0=0 saw_target=0 saw_library_path=0
    local -a arguments=()

    [[ $pid =~ ^[1-9][0-9]*$ && $target == /* && $loader == /* &&
            -r $proc_root/$pid/cmdline ]] || return 1
    mapfile -d '' -t arguments < "$proc_root/$pid/cmdline" || return 1
    ((${#arguments[@]} >= 7)) || return 1
    [[ ${arguments[0]} == "$loader" ]] || return 1
    for ((index = 1; index < ${#arguments[@]}; index++)); do
        case ${arguments[index]} in
            --argv0)
                [[ ${arguments[index + 1]:-} == "$target" ]] || return 1
                saw_argv0=$((saw_argv0 + 1))
                index=$((index + 1))
                ;;
            --library-path)
                [[ ${arguments[index + 1]:-} == "$library_path" ]] || return 1
                saw_library_path=$((saw_library_path + 1))
                index=$((index + 1))
                ;;
            "$target")
                saw_target=$((saw_target + 1))
                ;;
        esac
    done
    ((saw_argv0 == 1 && saw_library_path == 1 && saw_target >= 1))
}

# Authenticate one loader-backed Steam process and retain its immutable
# initial environment in STEAM_ARM64_MATCHED_ENVIRONMENT. Every required
# KEY=VALUE pair is exact. The optional expected start tick rejects a stale PID
# selected by an earlier caller.
steam_arm64_authenticated_session() {
    local pid=$1 target=$2 loader=$3 library_path=$4 expected_uid=$5
    local expected_start_ticks=$6
    shift 6
    local proc_root=${STEAM_ARM64_PROC_ROOT:-/proc}
    local actual_uid exe_path start_before start_after entry key value
    local real_uid effective_uid saved_uid filesystem_uid extra
    local -A environment_by_key=() required_by_key=()
    local -a environment=()

    STEAM_ARM64_SESSION_REASON=identity
    STEAM_ARM64_MATCHED_PID=
    STEAM_ARM64_MATCHED_START_TICKS=
    STEAM_ARM64_MATCHED_ENVIRONMENT=()

    steam_arm64_native_loader_process_matches \
        "$pid" "$target" "$loader" "$library_path" || return 1
    start_before=$(steam_arm64_process_start_ticks "$pid") || return 1
    if [[ -n $expected_start_ticks && $start_before != "$expected_start_ticks" ]]; then
        STEAM_ARM64_SESSION_REASON=stale
        return 1
    fi

    actual_uid=$(stat -c %u -- "$proc_root/$pid" 2>/dev/null) || return 1
    [[ $actual_uid == "$expected_uid" ]] || {
        STEAM_ARM64_SESSION_REASON=uid
        return 1
    }
    if ! read -r real_uid effective_uid saved_uid filesystem_uid extra < <(
            sed -n 's/^Uid:[[:space:]]*//p' "$proc_root/$pid/status" 2>/dev/null
        ); then
        return 1
    fi
    [[ -z ${extra:-} && $real_uid == "$expected_uid" &&
            $effective_uid == "$expected_uid" && $saved_uid == "$expected_uid" &&
            $filesystem_uid == "$expected_uid" ]] || {
        STEAM_ARM64_SESSION_REASON=uid
        return 1
    }

    exe_path=$(realpath -e "$proc_root/$pid/exe" 2>/dev/null) || return 1
    [[ $exe_path == "$loader" ]] || {
        STEAM_ARM64_SESSION_REASON=loader
        return 1
    }
    mapfile -d '' -t environment < "$proc_root/$pid/environ" || return 1
    ((${#environment[@]} > 0)) || return 1
    for entry in "${environment[@]}"; do
        [[ $entry == *=* ]] || return 1
        key=${entry%%=*}
        value=${entry#*=}
        [[ $key =~ ^[A-Za-z_][A-Za-z0-9_]*$ &&
                ! -v 'environment_by_key[$key]' ]] || return 1
        environment_by_key[$key]=$value
    done
    for entry in "$@"; do
        [[ $entry == *=* ]] || return 1
        key=${entry%%=*}
        value=${entry#*=}
        [[ $key =~ ^[A-Za-z_][A-Za-z0-9_]*$ &&
                ! -v 'required_by_key[$key]' ]] || return 1
        required_by_key[$key]=$value
    done
    for key in "${!required_by_key[@]}"; do
        if [[ ! -v 'environment_by_key[$key]' ||
                ${environment_by_key[$key]} != "${required_by_key[$key]}" ]]; then
            STEAM_ARM64_SESSION_REASON=profile
            return 1
        fi
    done

    start_after=$(steam_arm64_process_start_ticks "$pid") || {
        STEAM_ARM64_SESSION_REASON=stale
        return 1
    }
    [[ $start_after == "$start_before" ]] || {
        STEAM_ARM64_SESSION_REASON=stale
        return 1
    }
    STEAM_ARM64_MATCHED_PID=$pid
    STEAM_ARM64_MATCHED_START_TICKS=$start_after
    STEAM_ARM64_MATCHED_ENVIRONMENT=("${environment[@]}")
    STEAM_ARM64_SESSION_REASON=eligible
}

# A compact, append-friendly phase record based on Linux monotonic uptime.
# Centisecond resolution is sufficient for the existing whole-second launch
# evidence while avoiding a Python process on every phase transition.
steam_arm64_forward_phase() {
    local mode=$1 event=$2 detail=${3:-none} uptime whole fraction
    local uptime_file=${STEAM_ARM64_UPTIME_FILE:-/proc/uptime}

    [[ $mode == strict || $mode == fast ]] || return 1
    [[ $event =~ ^[a-z][a-z0-9_]*$ && $detail =~ ^[A-Za-z0-9_.:/=-]+$ ]] ||
        return 1
    read -r uptime _ < "$uptime_file" || return 1
    [[ $uptime =~ ^[0-9]+([.][0-9]+)?$ ]] || return 1
    whole=${uptime%%.*}
    if [[ $uptime == *.* ]]; then
        fraction=${uptime#*.}00
        fraction=${fraction:0:2}
    else
        fraction=00
    fi
    printf 'steam-arm64-forward-phase version=1 mode=%s event=%s monotonic_cs=%s detail=%s\n' \
        "$mode" "$event" "$((10#$whole * 100 + 10#$fraction))" "$detail"
}
