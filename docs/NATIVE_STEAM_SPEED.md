# Native Steam speed plan

Steam and `steamwebhelper` are native ARM64/glibc processes; PRoot and FEX do
not participate until a Windows-game handoff. The first optimization therefore
targets repeated forwarding into an already-running, remembered-login Steam
session rather than the game translation stack.

## Measured warm-forward baseline

Across 304 retained `start-steam-forward-*` logs, setup before the second Steam
process received its request took a median 3.0 seconds and a 10-second p90.
Steam's forwarder then acknowledged in a median 0.932 seconds. Median total time
was 3.372 seconds. The log filenames have whole-second setup resolution and the
population includes busy/game states, so these measurements define the A/B
baseline rather than a claimed speedup.

The first tablet fast-path proof completed the authenticated dispatcher in 350
ms. Its strict control remained inside the legacy PRoot launcher beyond 60
seconds and was deliberately censored, so that pair proves the architectural
cliff but is not a completed strict timing distribution. A second wrapper gate
runs fast forwarding synchronously: only an exact `session_valid`,
`fast_launch`, and successful `complete` sequence may bypass the older mutable
login-log heuristic. Window presentation and AppID acknowledgement waits remain
unchanged.

The first wrapper trace measured 28.337 seconds despite a roughly 0.5-second
forward: reused-X11 discovery/foregrounding cost about 6.1 seconds, Binder
health 2.7, Steam discovery 1.7, and two full affinity passes about 8 seconds
each. The warm path now treats already-correct thread masks as a no-op, avoids
the second Android Activity handoff for a reused X11 server, and omits the
duplicate post-forward affinity pass when no AppID was requested. Cold X11,
game-launch, window-surfacing, and incorrect-mask paths retain their checks and
repinning behavior.

Even checking every existing thread mask cost 7.7 seconds across Steam and 11
CEF processes on the tablet. A private affinity stamp now binds the complete
helper set to each exact PID/start-time identity, `/top-app` cgroup, and target
mask. An unchanged set skips thread-by-thread `/proc` reads; any restarted,
added, removed, re-cgrouped, or stale process forces the complete validation
and repin before atomically replacing the stamp.

`STEAM_ARM64_CEF_AFFINITY=auto` is the default UI policy. A visible Steam
Library/Store request gives CEF CPUs 0-3 for responsiveness. A warm AppID launch
now also uses CPUs 0-3 while Steam processes its launch UI, then automatically
compacts CEF to CPU 0 after the AppID acknowledgement so the game retains the
measured CPU layout. Explicit `responsive`, `compact`, and `launch-boost` modes
remain available for A/B work. The selected CEF mask is part of the affinity
stamp, so switching modes forces an exact repin and subsequent launches of the
same mode become cache hits.

The first direct AppID phase trace isolated a roughly 29.5-second delay inside
Steam after the authenticated dispatcher completed in 0.410 seconds. It
coincided with 10.371- and 11.438-second SteamUI stalls and repeated SDL
HIDAPI/udev discovery messages. SDL documents `SDL_JOYSTICK_HIDAPI=0` as the
global HIDAPI-driver off switch, but that requires a cold Steam environment and
changes controller behavior. The warm launch-boost is therefore tested first;
the HIDAPI control remains a separate cold-start A/B rather than an inferred
fix.

For a later cold-session A/B, `STEAM_ARM64_HIDAPI=disabled` starts Steam with
SDL's documented `SDL_JOYSTICK_HIDAPI=0`. The default is unchanged. The wrapper
refuses to pretend the selector affected an already-running process, and both
the ordinary and direct game boundaries strip the Steam-only control so it
cannot disable SDL controller handling inside Proton or a game. This is a
diagnostic control, not a promoted speed setting; disabling it trades away
Steam's HIDAPI controller path. Upstream semantics:
<https://wiki.libsdl.org/SDL2/SDL_HINT_JOYSTICK_HIDAPI>.

The code reuses the exact loader-process model and remembered-profile rules
established in indexed sessions `019ff310-e8ac-7212-9f2f-5ba9005b97bd` and
`019fe348-1247-7530-bc25-8a573aaf4252`. A focused deja query for an existing
authenticated fast-forward implementation returned no match.

## Strict/fast A/B

`STEAM_ARM64_FORWARD_BOOTSTRAP` accepts `strict` or `fast`. The public Steam
wrapper now defaults warm requests to `fast`; the lower-level dispatcher keeps
its defensive `strict` default when invoked directly:

```sh
STEAM_ARM64_FORWARD_BOOTSTRAP=strict ~/start-steam-native.sh --appid 203160 -- -nolauncher
STEAM_ARM64_FORWARD_BOOTSTRAP=fast   ~/start-steam-native.sh --appid 203160 -- -nolauncher
```

The selector affects only requests forwarded to an existing native Steam
process. A cold start always uses the complete launcher. Fast mode requires
exactly one explicit-loader Steam candidate and validates its stable start
ticks, real/effective/saved/filesystem UID, loader executable, native HOME,
display, Steam base/client root, glibc library path, runtime directory, and
Vulkan profile. It then reuses that process's initial environment while
removing dispatcher/test controls. Any stale, ambiguous, malformed, or
profile-mismatched candidate delegates to the existing strict launcher.

The dispatcher never rewrites, clears, or relocates Steam cookies,
`loginusers.vdf`, `ssfn` files, userdata, or CEF storage. The existing outer
launcher retains its read-only remembered-login readiness check.

Each forward log contains append-friendly monotonic records:

```text
steam-arm64-forward-phase version=2 mode=fast event=fast_inspect clock=monotonic timestamp_cs=... detail=none
```

Linux monotonic uptime is preferred. Android 16 may expose `/proc/uptime` but
deny the Termux UID permission to read it; that case uses Bash's
zero-subprocess `EPOCHREALTIME` and records `clock=realtime` rather than failing
the request or pretending the fallback is monotonic.

Strict mode records `request`, `strict_launch`, and `complete`. An eligible fast
run records `request`, `fast_inspect`, `session_valid`, `fast_launch`, and
`complete`; a rejection records `fast_fallback` before `strict_launch`. Compare
request-to-complete and the existing Steam/AppID acknowledgement separately.

The first tablet sequence reduced the authenticated warm wrapper from 27.329
seconds to 17.208 seconds after eliminating redundant foreground/affinity work,
then to 12.678 seconds on an exact affinity-stamp hit. The dispatcher itself
remained approximately 0.33--0.35 seconds. This is a single-device engineering
sequence, not yet a timing distribution or a UI-latency claim. It does not
change the separately measured Tomb Raider FPS result.

The focused deja query
`Steam CEF responsive affinity UI CPU0 cache warm launch optimization` returned
no indexed implementation, so the responsive/compact split is new work built on
the exact authenticated fast-forward and affinity-stamp boundaries above.

The following warm-path slice replaces three Bash-wide `/proc` scans with
native `pgrep` candidate narrowing for X11, Steam, and CEF, followed by the same
exact command-line/process matcher as before. On the target, each native scan
took roughly 0.08 seconds; false-positive candidates are expected and rejected
by the authoritative matcher. X11 additionally decodes its NUL-delimited argv
in Bash, accepting both the Android setproctitle-style combined first argument
and conventional split argv while removing one `tr` subprocess per process.
Cold launcher discovery keeps the exhaustive fallback. The focused deja query
`cache X11 Steam steamwebhelper PID discovery affinity stamp start ticks proc
scan` returned no indexed implementation.

A timestamped tablet trace then showed a separate warm-UI cost: after finding a
valid visible 2800x1586 Steam window, each stability iteration still scanned
every hidden 64x24 CEF utility window. Four redundant fallback scans cost about
8.6 seconds. The existing-process path also inherited the cold-start five-second
window-stability delay. Warm authenticated Steam now accepts the first valid
visible full-size window and invokes hidden-window recovery only when no valid
visible window exists. Cold startup retains the complete stability gate. The
focused deja query `warm existing Steam window five second stability hidden CEF
window scan xdotool` returned no indexed implementation.

The reused-X11 path also spent about 2.4 seconds asking Android to start an
Activity that was already topmost, followed by the two-second Binder failure
observation required after a real handoff. The launcher can directly read the
exact X11 PID's `cpuset` and `cpu` cgroups. It now skips both operations only
when both are already `/top-app`; a backgrounded, cold, or restarted X11 keeps
the original Activity handoff, top-app wait, and Binder log gate. The focused
deja query `Termux X11 already top-app skip am start binder health warm Steam
launcher` returned no indexed implementation.

The intermediate top-app tablet run completed in 4.887 seconds with return code
0, the exact Steam/X11/PulseAudio identities unchanged, all 11 CEF helpers on
CPUs 0-3, and a populated 2800x1752 screenshot.

The sub-five-second trace had no remaining blocking sleep. Most residual time
was cumulative process creation: each of 11 CEF helpers triggered separate
`sed|head` cgroup readers and a separate `sed` affinity reader. The warm path
now parses each `/proc/PID/cgroup` and `/proc/PID/status` file once with Bash
builtins, preserving the exact top-app and CPU-mask assertions without those
external processes. The focused deja query `Bash builtin parse proc pid cgroup
status affinity eliminate sed head Steam helpers warm launcher` returned no
indexed implementation.

The accepted built-in-parser run completed in 2.254 seconds with return code 0
and the same protected process identities and populated screenshot hash. This
is a 91.8% reduction from the initial 27.329-second warm wrapper measurement.
Exact artifacts, all intermediate measurements, identities, and no-claim
boundaries are recorded in `evidence/native-steam-warm-ui-20260823.json`.

## Later, separate A/Bs

1. Reclaim safe non-profile disk space; the audited tablet filesystem was 98%
   full. Do not start by clearing authentication, HTML, or Library caches.
2. Measure Library click-to-paint and scrolling after game affinity has restored
   CEF beyond CPU 0; distinguish responsiveness from merely hiding the UI.
3. Remove the observed one-second missing-portal D-Bus timeout with a correct
   portal/nonportal configuration.
4. Test CEF GPU flags one at a time with stale/black-surface detection; prior
   GPU-composited Termux:X11 surfaces were unreliable.
5. Cache immutable cold dependency/Runtime validation by content identity, then
   separately A/B a candidate-specific glibc loader cache.

FEX tuning remains a game-process optimization, not a Steam/Library startup
optimization.

For Tomb Raider, the ordinary direct launcher defaults to the verified,
binary-hash-keyed FEX-2605 generation-5 compiled cache. The dispatcher checks
its manifest, embedded FEX identity, cache format, and files before exposing
it only to the final game process. `TOMB_RAIDER_FEX_CODE_CACHE=on` remains the
recording/max-buffer reverse control; `off` disables both modes. Other games
must build and validate their own binary-specific cache before adopting this
pattern.
