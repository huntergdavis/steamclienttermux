#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

usage() {
    printf 'usage: %s --steam-pid PID --steam-start-ticks TICKS --appid APPID --log PATH --offset BYTES --timeout SECONDS\n' "${0##*/}" >&2
    exit 2
}

steam_pid=
steam_start_ticks=
appid=
log_path=
offset=
timeout=
while (($#)); do
    case "$1" in
        --steam-pid) steam_pid=${2:-}; shift 2 ;;
        --steam-start-ticks) steam_start_ticks=${2:-}; shift 2 ;;
        --appid) appid=${2:-}; shift 2 ;;
        --log) log_path=${2:-}; shift 2 ;;
        --offset) offset=${2:-}; shift 2 ;;
        --timeout) timeout=${2:-}; shift 2 ;;
        *) usage ;;
    esac
done

[[ $steam_pid =~ ^[1-9][0-9]*$ &&
   $steam_start_ticks =~ ^[1-9][0-9]*$ &&
   $appid =~ ^[1-9][0-9]*$ &&
   $offset =~ ^[0-9]+$ &&
   $timeout =~ ^[1-9][0-9]*$ &&
   $log_path == /* && -f $log_path && ! -L $log_path ]] || usage
command -v tail >/dev/null 2>&1 || exit 2

steam_pid_is_current() {
    local stat_line stat_tail
    local -a fields=()
    [[ -r /proc/$steam_pid/stat ]] || return 1
    IFS= read -r stat_line < "/proc/$steam_pid/stat" || return 1
    [[ $stat_line == *') '* ]] || return 1
    stat_tail=${stat_line##*) }
    read -r -a fields <<<"$stat_tail"
    # fields[0] is Linux stat field 3, so fields[19] is starttime/field 22.
    [[ ${fields[19]:-} == "$steam_start_ticks" ]]
}

clock_centiseconds() {
    local value whole fraction
    value=${EPOCHREALTIME:-}
    [[ $value =~ ^[0-9]+([.][0-9]+)?$ ]] || return 1
    whole=${value%%.*}
    if [[ $value == *.* ]]; then
        fraction=${value#*.}00
        fraction=${fraction:0:2}
    else
        fraction=00
    fi
    CLOCK_CENTISECONDS=$((10#$whole * 100 + 10#$fraction))
}

steam_pid_is_current || exit 1
clock_centiseconds || exit 2
deadline=$((CLOCK_CENTISECONDS + timeout * 100))

# One incremental follower replaces repeated whole-file stat/tail/grep scans.
# --pid bounds its lifetime to this waiter; 100 ms is only control-plane work.
exec {log_fd}< <(
    tail --pid="$$" --sleep-interval=0.1 --follow=name --retry \
        -c "+$((offset + 1))" -- "$log_path"
)

while steam_pid_is_current; do
    if IFS= read -r -t 0.2 -u "$log_fd" line; then
        case "$line" in
            *"AppID $appid adding PID"*) exit 0 ;;
        esac
    fi
    clock_centiseconds || exit 2
    ((CLOCK_CENTISECONDS < deadline)) || exit 1
done
exit 1
