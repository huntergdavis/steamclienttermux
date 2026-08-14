#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

if [[ -z ${PREFIX:-} ]]; then
    printf 'ensure-sshd-supervised: PREFIX is not set\n' >&2
    exit 2
fi

service_root="${SVDIR:-$PREFIX/var/service}"
log_root="${LOGDIR:-$PREFIX/var/log}"
sshd_service="$service_root/sshd"
runsvdir_binary="$PREFIX/bin/runsvdir"
startup_timeout="${SSHD_SUPERVISOR_START_TIMEOUT_SECONDS:-10}"

if [[ ! "$startup_timeout" =~ ^[0-9]+$ ]] ||
        (( startup_timeout < 1 || startup_timeout > 30 )); then
    printf 'ensure-sshd-supervised: invalid startup timeout: %s\n' \
        "$startup_timeout" >&2
    exit 2
fi
if [[ ! -x "$runsvdir_binary" ]] || [[ ! -d "$sshd_service" ]] ||
        [[ ! -x "$sshd_service/run" ]]; then
    printf 'ensure-sshd-supervised: incomplete termux-services setup\n' >&2
    exit 2
fi

export SVDIR="$service_root"
export LOGDIR="$log_root"

runsvdir_present() {
    local cmdline
    local -a args

    for cmdline in /proc/[0-9]*/cmdline; do
        [[ -r "$cmdline" ]] || continue
        args=()
        mapfile -d '' -t args <"$cmdline" 2>/dev/null || true
        if (( ${#args[@]} >= 2 )) &&
                [[ "${args[0]}" == "$runsvdir_binary" ]] &&
                [[ "${args[1]}" == "$service_root" ]]; then
            return 0
        fi
    done

    return 1
}

if ! runsvdir_present; then
    # start-stop-daemon detaches the process itself. Do not add another
    # backgrounding layer here: it creates a race with the first `sv up`.
    service-daemon start >/dev/null 2>&1 || true
fi

deadline=$((SECONDS + startup_timeout))
while ! runsvdir_present; do
    if (( SECONDS >= deadline )); then
        printf 'ensure-sshd-supervised: runsvdir did not start in %ss\n' \
            "$startup_timeout" >&2
        exit 1
    fi
    sleep 0.1
done

if ! sv -w "$startup_timeout" up "$sshd_service" >/dev/null 2>&1; then
    printf 'ensure-sshd-supervised: sshd did not enter the run state\n' >&2
    exit 1
fi

status="$(sv status "$sshd_service" 2>&1 || true)"
if [[ "$status" != run:* ]]; then
    printf 'ensure-sshd-supervised: unexpected sshd status: %s\n' \
        "$status" >&2
    exit 1
fi
