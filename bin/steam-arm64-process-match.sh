#!/data/data/com.termux/files/usr/bin/bash

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
