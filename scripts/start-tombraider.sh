#!/data/data/com.termux/files/usr/bin/bash

set -euo pipefail

game_start=${STEAM_GAME_START_SCRIPT:-$HOME/start-steam-game}
stock_start=${STEAM_START_SCRIPT:-$HOME/start-steam.sh}

case ${1:-} in
    '')
        [[ -x $game_start ]] || {
            printf 'start-tombraider: optimized game launcher is unavailable: %s\n' \
                "$game_start" >&2
            exit 1
        }
        exec "$game_start" 203160
        ;;
    -benchmark)
        (($# == 1)) || {
            printf '%s\n' 'start-tombraider: -benchmark takes no additional arguments' >&2
            exit 1
        }
        [[ -x $game_start ]] || {
            printf 'start-tombraider: optimized game launcher is unavailable: %s\n' \
                "$game_start" >&2
            exit 1
        }
        exec "$game_start" 203160 --mode benchmark
        ;;
    --stock)
        shift
        [[ -x $stock_start ]] || {
            printf 'start-tombraider: stock Steam launcher is unavailable: %s\n' \
                "$stock_start" >&2
            exit 1
        }
        export STEAM_BACKGROUND=1
        exec "$stock_start" --appid 203160 -- -nolauncher "$@"
        ;;
    *)
        printf '%s\n' 'usage: start-tombraider.sh [-benchmark | --stock [GAME_ARG...]]' >&2
        exit 2
        ;;
esac
