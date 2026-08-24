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
| Built-in `/proc` validation | `73a9b02` | 2.254 | -91.8% | Superseded |
| Phase-instrumented confirmation | `e0f34b5` | 2.220 | -91.9% | Superseded |
| Collapsed X11 window transactions | `c66ae18` | **1.662** | **-93.9%** | Current |

The authenticated dispatcher itself measured about 0.33-0.35 seconds. The
current launcher batches window search/geometry and map/raise/focus into one
X11 client each. A plain warm UI request also skips the redundant second
affinity pass because it launched no process after the first authenticated
pass.

| Warm phase | Before | Current |
| --- | ---: | ---: |
| X11 readiness | 0.58 | 0.61 |
| Audio readiness | 0.17 | 0.14 |
| Steam discovery | 0.15 | 0.13 |
| Affinity validation | 0.35 | 0.38 |
| Visible-window validation | **0.86** | **0.27** |
| **Internal total** | **2.11** | **1.53** |
| **External wrapper total** | **2.220** | **1.662** |

This is an engineering sequence from one live session, not a randomized
latency distribution. See the [original optimization
sequence](evidence/native-steam-warm-ui-20260823.json) and the [phase-timed
confirmation](evidence/native-steam-warm-ui-phases-20260824.json).
The [collapsed-window A/B](evidence/native-steam-warm-ui-window-collapse-20260824.json)
includes both candidate passes and the screenshot proof.

## Steam-to-game launch architecture

| Route | Runtime request to window | Change |
| --- | ---: | ---: |
| Comparable PRoot route | 407.236s | baseline |
| Native-glibc host | 58.256s | -85.7%; 6.99x faster |

| Warm forwarding boundary | Seconds | Status |
| --- | ---: | --- |
| Strict controls | 11.12--12.38 | Superseded |
| Authenticated fast dispatcher | 0.340 | Current |
| Complete warm background wrapper | **1.833** | Current; [evidence](evidence/steam-warm-fast-forward-default-20260824.json) |

The direct dispatcher removes the remaining hot PRoot boundary only for exact
allow-listed commands. See [`launch-timings/`](launch-timings/) for artifacts.

### Direct Tomb Raider launch phases

One warm, authenticated direct-glibc launch on the same tablet:

| Boundary | Seconds |
| --- | ---: |
| Session to runtime request | 30.000 |
| Runtime request to Pressure Vessel | 1.627 |
| Runtime request to Proton | 10.438 |
| Runtime request to Wine | 12.605 |
| Runtime request to game process | 18.681 |
| Runtime request to first visible window | 51.742 |
| **Session to first visible window** | **81.742** |

The authenticated handoff itself took 0.410 seconds. Roughly 29.5 seconds then
elapsed inside Steam before the request returned, coinciding with 10.371- and
11.438-second SteamUI stalls plus repeated HIDAPI/udev discovery messages. That
makes Steam UI/input work—not the dispatcher—the next measured launch target.
See [the compact evidence](evidence/steam-direct-appid-window-20260824.json).

The next same-session A/B temporarily gave Steam's CEF helpers CPUs 0-3 during
the AppID handoff and restored them to CPU 0 after acknowledgement:

| AppID-to-window mode | Seconds | Change |
| --- | ---: | ---: |
| Compact CEF throughout | 81.742 | baseline |
| **Transient CEF launch boost** | **65.193** | **-20.2%** |

Session-to-runtime fell from 30 to 12 seconds while runtime-to-window remained
roughly flat (51.742 vs 53.193 seconds). A 2800x1752 tablet screenshot confirmed
Tomb Raider's rendered terms UI; the game was then terminated without restarting
Steam or X11. This is one controlled engineering A/B, not a latency distribution.
See [the result](evidence/steam-direct-appid-window-launch-boost-20260824.json).

## Excluded measurements

| Date | Route | Observation | Why excluded |
| --- | --- | --- | --- |
| 2026-08-24 | Ordinary Steam/PRoot game route | Duplicate readiness pass removed; strict forwards took 12.38s and 11.12s | Both accepted containers exited before the game process; [evidence](evidence/steam-warm-appid-single-pass-excluded-20260824.txt) |

Those strict controls motivated promoting authenticated fast forwarding as the
wrapper default. The first promoted tablet check measured 0.340 seconds in the
dispatcher and 1.833 seconds for the complete warm background wrapper. Cold
starts remain complete launches, and failed authentication retains the strict
fallback; a new end-to-end AppID timing is still required before claiming the
control-to-game delta.

## Logging rule

Append only promoted or diagnostically useful measurements. Record the commit,
route, start state, elapsed time, result status, and evidence link. Keep rejected
or thermally invalid data in machine-readable evidence with an exclusion reason.

Direct game launches now write one compact phase record at preparation, service,
Steam/AppID, optional external-gate, and completion boundaries. These records
use Bash's built-in clock and never enter the per-frame path. They are the source
for the next AppID-to-window optimization rather than a new performance claim.

Every full Steam wrapper invocation also writes `start-steam-phases-*.log` with
zero-subprocess timestamps for X11, audio, process discovery, affinity,
forwarding, login, AppID, and visible-window boundaries. This is lifecycle-only
instrumentation; it does not sample Steam or enter any game/rendering path.
