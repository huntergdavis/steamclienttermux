#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

base="${STEAM_ARM64_BASE:-$HOME/steam-arm64}"
interval="${MONITOR_INTERVAL_SECONDS:-5}"
duration="${MONITOR_DURATION_SECONDS:-7200}"
stamp="$(date +%Y%m%d-%H%M%S)"
output="${MONITOR_OUTPUT:-$base/logs/termux-game-monitor-$stamp.log}"

if [[ ! "$interval" =~ ^[0-9]+$ ]] || (( interval < 1 || interval > 60 )); then
    printf 'MONITOR_INTERVAL_SECONDS must be an integer from 1 to 60\n' >&2
    exit 2
fi
if [[ ! "$duration" =~ ^[0-9]+$ ]] || (( duration < 1 || duration > 21600 )); then
    printf 'MONITOR_DURATION_SECONDS must be an integer from 1 to 21600\n' >&2
    exit 2
fi

mkdir -p "$(dirname "$output")"
umask 077
uid="$(id -u)"
deadline="$(( $(date +%s) + duration ))"

printf 'monitor_start=%s uid=%s interval_seconds=%s duration_seconds=%s\n' \
    "$(date --iso-8601=seconds)" "$uid" "$interval" "$duration" >"$output"

while (( $(date +%s) < deadline )); do
    {
        printf '\nsample=%s uptime=' "$(date --iso-8601=seconds)"
        cat /proc/uptime
        printf 'load='
        cat /proc/loadavg
        awk '
            /^(MemTotal|MemFree|MemAvailable|Cached|SwapCached|AnonPages|Mapped|Shmem|Slab|PageTables|SwapTotal|SwapFree):/ {
                printf "%s=%s%s ", substr($1, 1, length($1)-1), $2, $3
            }
            END { print "" }
        ' /proc/meminfo

        ps -u "$uid" -o pid=,ppid=,rss=,stat=,comm= 2>/dev/null |
            awk '
                { count += 1; rss += $3 }
                END { printf "uid_processes=%d uid_rss_kb=%d\n", count, rss }
            '

        for name in termux-x11 kwin_x11 plasmashell steam GTAIV.exe \
                RockstarService wineserver proot; do
            pids="$(pgrep -x "$name" 2>/dev/null | paste -sd, - || true)"
            printf 'watch_%s=%s\n' "$name" "${pids:-absent}"
        done
    } >>"$output"
    sleep "$interval"
done

printf '\nmonitor_end=%s\n' "$(date --iso-8601=seconds)" >>"$output"
printf '%s\n' "$output"
