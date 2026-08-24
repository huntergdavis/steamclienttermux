# Steam timing log

Human-readable results live here; exact identities and raw evidence remain in
[`docs/evidence/`](evidence/). Lower is better.

## Warm visible Steam UI

Same authenticated native ARM64 Steam/X11 session on the Galaxy Tab S8+.

| Stage | Commit | Seconds | Change from initial | Status |
| --- | --- | ---: | ---: | --- |
| Initial warm wrapper | before `542141a` | 27.329 | baseline | Retained |
| Remove redundant foreground/affinity work | `542141a` | 17.208 | -37.0% | Superseded |
| Identity-bound affinity cache hit | `a50e861` | 12.678 | -53.6% | Superseded |
| Native process discovery + warm window gate | `d2e1bde` | 9.889 | -63.8% | Superseded |
| Exact X11 top-app fast path | `506080c` | 4.887 | -82.1% | Superseded |
| Built-in `/proc` validation | `73a9b02` | **2.254** | **-91.8%** | Current |

The authenticated dispatcher itself measured about 0.33-0.35 seconds. The
2.254-second run returned 0, preserved exact Steam/X11/PulseAudio identities,
kept 11 CEF helpers on CPUs 0-3, and reproduced the populated 2800x1752 frame
hash. This is an engineering sequence from one live session, not a randomized
latency distribution. See
[`native-steam-warm-ui-20260823.json`](evidence/native-steam-warm-ui-20260823.json).

## Steam-to-game launch architecture

| Route | Runtime request to window | Change |
| --- | ---: | ---: |
| Comparable PRoot route | 407.236s | baseline |
| Native-glibc host | 58.256s | -85.7%; 6.99x faster |

The direct dispatcher removes the remaining hot PRoot boundary only for exact
allow-listed commands. See [`launch-timings/`](launch-timings/) for artifacts.

The warm Tomb Raider wrapper now detects one exact native Steam process with
the shared process-identity matcher and skips its redundant no-AppID readiness
pass. The AppID request still performs the authoritative session, login, X11,
audio, and affinity checks. Cold or ambiguous sessions retain the full prime.
The expected saving is one warm-wrapper pass; no launch-time claim will be
added until the structured timer measures it on the tablet.

## Excluded measurements

| Date | Route | Observation | Why excluded |
| --- | --- | --- | --- |
| 2026-08-24 | Ordinary Steam/PRoot game route | Duplicate readiness pass removed; strict forwards took 12.38s and 11.12s | Both accepted containers exited before the game process; [evidence](evidence/steam-warm-appid-single-pass-excluded-20260824.txt) |

Those strict controls motivated promoting the already-proven authenticated
fast forward as the wrapper default. It previously measured about 0.33--0.35
seconds at the dispatcher boundary. Cold starts remain complete launches, and
failed authentication retains the strict fallback; a new end-to-end AppID
timing is still required before claiming the control-to-game delta.

## Logging rule

Append only promoted or diagnostically useful measurements. Record the commit,
route, start state, elapsed time, result status, and evidence link. Keep rejected
or thermally invalid data in machine-readable evidence with an exclusion reason.
