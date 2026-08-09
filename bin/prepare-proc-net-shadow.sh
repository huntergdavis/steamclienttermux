#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

base="${1:-$HOME/steam-arm64}"
proc_net="$base/config/proc-net"
route_probe="${STEAM_ARM_ROUTE_PROBE:-1.1.1.1}"

fail() {
    printf 'Unable to prepare synthetic /proc/net: %s\n' "$1" >&2
    exit 1
}

validate_ipv4() {
    local address="$1"
    local octets octet

    [[ "$address" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || return 1
    IFS=. read -r -a octets <<<"$address"
    [[ "${#octets[@]}" -eq 4 ]] || return 1
    for octet in "${octets[@]}"; do
        [[ "$octet" =~ ^[0-9]+$ ]] || return 1
        ((10#$octet <= 255)) || return 1
    done
}

ipv4_to_route_hex() {
    local address="$1"
    local a b c d

    IFS=. read -r a b c d <<<"$address"
    printf '%02X%02X%02X%02X' \
        "$((10#$d))" "$((10#$c))" "$((10#$b))" "$((10#$a))"
}

network_address() {
    local address="$1" mask="$2"
    local a b c d ma mb mc md

    IFS=. read -r a b c d <<<"$address"
    IFS=. read -r ma mb mc md <<<"$mask"
    printf '%d.%d.%d.%d' \
        "$((10#$a & 10#$ma))" "$((10#$b & 10#$mb))" \
        "$((10#$c & 10#$mc))" "$((10#$d & 10#$md))"
}

ipv4="${STEAM_ARM_IPV4:-}"
if [[ -z "$ipv4" ]]; then
    command -v termux-wifi-connectioninfo >/dev/null 2>&1 ||
        fail 'termux-wifi-connectioninfo is unavailable; set STEAM_ARM_IPV4'
    wifi_info="$(termux-wifi-connectioninfo)" ||
        fail 'termux-wifi-connectioninfo failed'
    ipv4="$(sed -n \
        's/^[[:space:]]*"ip":[[:space:]]*"\([^"]*\)".*/\1/p' \
        <<<"$wifi_info" | head -n 1)"
fi
validate_ipv4 "$ipv4" || fail "invalid IPv4 address: $ipv4"

interface="${STEAM_ARM_INTERFACE:-}"
netmask="${STEAM_ARM_NETMASK:-}"
if [[ -z "$interface" || -z "$netmask" ]]; then
    command -v ifconfig >/dev/null 2>&1 || fail 'ifconfig is unavailable'
    ifconfig_match="$(ifconfig 2>/dev/null | awk -v wanted_ip="$ipv4" '
        /^[^[:space:]]/ {
            iface = $1
            sub(/:$/, "", iface)
        }
        $1 == "inet" && $2 == wanted_ip {
            print iface, $4
            exit
        }
    ')"
    if [[ -z "$interface" ]]; then
        interface="${ifconfig_match%% *}"
    fi
    if [[ -z "$netmask" ]]; then
        netmask="${ifconfig_match#* }"
        [[ "$netmask" != "$ifconfig_match" ]] || netmask=""
    fi
fi
[[ "$interface" =~ ^[A-Za-z0-9_.-]+$ ]] ||
    fail "invalid or unresolved interface: $interface"
validate_ipv4 "$netmask" || fail "invalid or unresolved netmask: $netmask"

gateway="${STEAM_ARM_GATEWAY:-}"
if [[ -z "$gateway" ]]; then
    command -v ping >/dev/null 2>&1 ||
        fail 'ping is unavailable; set STEAM_ARM_GATEWAY'
    ping_result="$(ping -n -c 1 -t 1 -W 3 "$route_probe" 2>&1 || true)"
    gateway="$(sed -n \
        's/^From \([0-9][0-9.]*\):.*[Tt]ime to live exceeded.*/\1/p' \
        <<<"$ping_result" | head -n 1)"
fi
validate_ipv4 "$gateway" || fail "invalid or unresolved gateway: $gateway"

network="$(network_address "$ipv4" "$netmask")"
gateway_network="$(network_address "$gateway" "$netmask")"
[[ "$network" == "$gateway_network" ]] ||
    fail "gateway $gateway is outside $ipv4/$netmask"

destination_hex="$(ipv4_to_route_hex "$network")"
gateway_hex="$(ipv4_to_route_hex "$gateway")"
mask_hex="$(ipv4_to_route_hex "$netmask")"

if [[ -L "$proc_net" ]]; then
    fail "refusing symlinked destination: $proc_net"
fi
mkdir -p "$proc_net"
[[ -d "$proc_net" ]] || fail "destination is not a directory: $proc_net"
chmod 700 "$proc_net"

if ! unexpected_entry="$(find "$proc_net" -mindepth 1 -maxdepth 1 \
        ! -name route ! -name ipv6_route -print -quit)"; then
    fail "unable to inspect destination: $proc_net"
fi
if [[ -n "$unexpected_entry" ]]; then
    fail "unexpected entry in destination: $unexpected_entry"
fi
for existing_entry in "$proc_net/route" "$proc_net/ipv6_route"; do
    if [[ -L "$existing_entry" ]] ||
            [[ -e "$existing_entry" && ! -f "$existing_entry" ]]; then
        fail "refusing non-regular destination entry: $existing_entry"
    fi
done

route_tmp="$(mktemp "$proc_net/.route.XXXXXX")"
ipv6_tmp="$(mktemp "$proc_net/.ipv6_route.XXXXXX")"
cleanup() {
    if [[ -n "${route_tmp:-}" && -f "$route_tmp" ]]; then
        unlink -- "$route_tmp"
    fi
    if [[ -n "${ipv6_tmp:-}" && -f "$ipv6_tmp" ]]; then
        unlink -- "$ipv6_tmp"
    fi
}
trap cleanup EXIT

printf 'Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n' \
    >"$route_tmp"
printf '%s\t00000000\t%s\t0003\t0\t0\t0\t00000000\t0\t0\t0\n' \
    "$interface" "$gateway_hex" >>"$route_tmp"
printf '%s\t%s\t00000000\t0001\t0\t0\t0\t%s\t0\t0\t0\n' \
    "$interface" "$destination_hex" "$mask_hex" >>"$route_tmp"

chmod 600 "$route_tmp" "$ipv6_tmp"
mv -f -- "$route_tmp" "$proc_net/route"
route_tmp=""
mv -f -- "$ipv6_tmp" "$proc_net/ipv6_route"
ipv6_tmp=""

printf 'Prepared synthetic /proc/net for %s via %s on %s\n' \
    "$network" "$gateway" "$interface"
