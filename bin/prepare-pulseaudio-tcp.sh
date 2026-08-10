#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

base="${1:-$HOME/steam-arm64}"
pulse_server="tcp:127.0.0.1:4713"
pulse_runtime="$base/run/pulse"
local_server="unix:$pulse_runtime/native"

fail() {
    printf 'Unable to prepare PulseAudio for Steam: %s\n' "$1" >&2
    exit 1
}

command -v pactl >/dev/null 2>&1 || fail 'pactl is unavailable'

# A healthy canonical TCP server is sufficient regardless of which Termux
# runtime directory owns it. This fast path also makes forwarded steam://
# launches side-effect free instead of loading another TCP module each time.
if pactl --server="$pulse_server" info >/dev/null 2>&1; then
    exit 0
fi

# Use one project-private runtime if the TCP endpoint must be bootstrapped.
# This avoids creating a different Pulse daemon whenever KDE and an SSH shell
# supply different XDG_RUNTIME_DIR values.
if [[ -L "$pulse_runtime" ]]; then
    fail "refusing symlinked runtime directory: $pulse_runtime"
fi
mkdir -p "$pulse_runtime"
[[ -d "$pulse_runtime" ]] || fail "runtime path is not a directory: $pulse_runtime"
chmod 700 "$pulse_runtime"

if ! pactl --server="$local_server" info >/dev/null 2>&1; then
    command -v pulseaudio >/dev/null 2>&1 || fail 'pulseaudio is unavailable'
    PULSE_RUNTIME_PATH="$pulse_runtime" \
        pulseaudio --start --exit-idle-time=-1 >/dev/null 2>&1 ||
        fail "failed to start the canonical local server: $local_server"
fi
if ! pactl --server="$local_server" info >/dev/null 2>&1; then
    fail "canonical local server is unreachable after startup: $local_server"
fi

if ! module_list="$(pactl --server="$local_server" list short modules)"; then
    fail "unable to inspect modules on the canonical local server: $local_server"
fi

has_loopback_tcp=0
while IFS=$'\t' read -r _ module_name module_args _; do
    [[ "$module_name" == "module-native-protocol-tcp" ]] || continue

    has_listen=0
    has_port=0
    read -r -a arguments <<<"$module_args"
    for argument in "${arguments[@]}"; do
        case "$argument" in
            listen=127.0.0.1) has_listen=1 ;;
            port=4713) has_port=1 ;;
        esac
    done
    if ((has_listen && has_port)); then
        has_loopback_tcp=1
        break
    fi
done <<<"$module_list"

if ((!has_loopback_tcp)); then
    if ! module_id="$(pactl --server="$local_server" load-module \
            module-native-protocol-tcp listen=127.0.0.1 port=4713 \
            auth-ip-acl=127.0.0.1 auth-anonymous=1)"; then
        fail 'failed to load the loopback PulseAudio TCP module'
    fi
    [[ "$module_id" =~ ^[0-9]+$ ]] ||
        fail "PulseAudio returned an invalid module ID: $module_id"
fi

if ! pactl --server="$pulse_server" info >/dev/null 2>&1; then
    fail "canonical TCP server is unreachable after preflight: $pulse_server"
fi
