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

The code reuses the exact loader-process model and remembered-profile rules
established in indexed sessions `019ff310-e8ac-7212-9f2f-5ba9005b97bd` and
`019fe348-1247-7530-bc25-8a573aaf4252`. A focused deja query for an existing
authenticated fast-forward implementation returned no match.

## Strict/fast A/B

`STEAM_ARM64_FORWARD_BOOTSTRAP` accepts `strict` or `fast` and defaults to
`strict`:

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

No tablet timing has been collected for this candidate yet, so it carries no
launch-time, UI-latency, or FPS claim.

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
