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

## Cold Steam-to-game launch

One clean tablet pass started with neither Steam nor Termux:X11 alive and ended
at the first Tomb Raider window:

| Boundary | Seconds from wrapper start |
| --- | ---: |
| X11 ready | 9.38 |
| Steam process ready | 14.51 |
| Remembered login ready | 22.97 |
| AppID accepted | 40.08 |
| **First game window** | **49.513** |

The previous validated cold result was 79.256 seconds. The current pass is
29.743 seconds faster (-37.5%). It is one engineering pass, not a latency
distribution. The external game timer independently measured 22.213 seconds
from the runtime request to the first window. Exact evidence and hashes are in
[`steam-cold-appid-acceptance-20260824.json`](evidence/steam-cold-appid-acceptance-20260824.json).

### Deterministic X11 and matched HIDAPI control

The cold launcher now starts one authoritative CLI X server, waits for its
short-lived launcher PID to settle, and only then attaches the Android
Activity. This removes the build-dependent race where the Activity and manual
fallback could both claim `:0`.

| Cold boundary | Earlier default | Current default | Change |
| --- | ---: | ---: | ---: |
| X11 ready | 9.38s | **4.44s** | -4.94s / -52.7% |
| Wrapper to AppID accepted | 40.08s | **21.80s** | -18.28s / -45.6% |

The AppID result is one pass and includes variable proprietary Steam work, so
only the X11 boundary is attributed to the launcher change. A matched adjacent
control found no HIDAPI speed gain:

| Mode | Controller to AppID | Wrapper to AppID | Login to AppID |
| --- | ---: | ---: | ---: |
| Default | **30.798s** | **21.80s** | **5.02s** |
| HIDAPI disabled | 30.865s | 21.85s | 6.25s |

Disabling SDL HIDAPI was 0.067 seconds slower end to end and changes controller
behavior, so the controller-safe default remains. Both screenshots were
byte-identical black X11 surfaces: these runs prove AppID acceptance and X11
health, not a rendered game window. Exact hashes and exclusions are in
[`steam-cold-appid-x11-hidapi-20260824.json`](evidence/steam-cold-appid-x11-hidapi-20260824.json).

The boundary-matched [x86 PC and handheld comparison](research/STEAM_X86_HANDHELD_TIMINGS.md)
finds the warm UI PC-class and the full cold launch inside normal handheld
territory. It recommends stopping broad speed redesigns after one ten-run tail
check, then prioritizing packaging and generic game support.

## Steam AppID acceptance profile

The warm acceptance boundary is native ARM64, not an emulation bottleneck:

| Observation | Result |
| --- | ---: |
| Observed Steam payloads | 9 AArch64 / 0 x86-64 |
| FEX mappings in Steam tree | 0 |
| Second-client acceptance wall time | 13.049s |
| Steam + helper CPU in that interval | 3.04 CPU-s |
| Physical reads in that interval | 320 KiB |
| Steam `RunInstallScript` warning | 8.851s |

The authenticated forwarder previously started a second copy of the native
Steam executable so its singleton logic could write to `steam.pipe`. Tracing
that exact process recovered Steam's bounded shell-quoted argv record. Writing
the same record directly reduced an adjacent acceptance pass from 13.049 to
8.971 seconds (-31.3%) while retaining an authenticated session, exact FIFO
owner/mode/inode checks, one atomic write, and the old client route when no FIFO
reader exists. The integrated route then reached the real Proton/DXVK game and
rendered Tomb Raider's Profile screen.

The remaining result varies: two integrated request-to-AppID passes were 10.77
and 19.61 seconds. Both still logged long `RunInstallScript` work, and the slower
pass also spent about ten seconds in Steam Cloud synchronization. The FIFO path
removes redundant process startup; it does not bypass Steam's license, cloud,
install-script, or game-action state machine. The next A/B is a cold-session
HIDAPI-disabled control because the stall is accompanied by repeated udev
device discovery. No controller-safe default will change without that evidence.

## Steam-to-game launch architecture

| Route | Runtime request to window | Change |
| --- | ---: | ---: |
| Comparable PRoot route | 407.236s | baseline |
| Native-glibc host | 58.256s | -85.7%; 6.99x faster |

| Warm forwarding boundary | Seconds | Status |
| --- | ---: | --- |
| Strict controls | 11.12--12.38 | Superseded |
| Authenticated second-client dispatcher | 0.340 | Superseded |
| Authenticated direct FIFO write | **0.10** | Current; bounded atomic packet |
| Complete warm background wrapper | **1.833** | Current; [evidence](evidence/steam-warm-fast-forward-default-20260824.json) |

| Warm AppID acknowledgement | Control | Incremental follower | Change |
| --- | ---: | ---: | ---: |
| Wrapper start to accepted AppID | 20.34s | **20.05s** | **-0.29s** |
| Forward complete to accepted AppID | 15.51s | **15.35s** | **-0.16s** |

The incremental follower replaces repeated one-second `stat|tail|grep` scans
with one 100 ms stream reader. A full-screen 2800x1752 Tomb Raider Terms frame
passed visual inspection. This is one adjacent pair; the remaining 15.35
seconds are Steam processing, not waiter overhead. See the [tablet
evidence](evidence/steam-appid-incremental-wait-tablet-20260824.json).

The direct dispatcher removes the remaining hot PRoot boundary only for exact
allow-listed commands. See [`launch-timings/`](launch-timings/) for artifacts.

| Repeated Proton preparation | Seconds | Change |
| --- | ---: | ---: |
| Full ELF + target/backup SHA validation | 1.291 | baseline |
| Identity-bound receipt, median of 3 | **0.443** | **-65.7%** |

The receipt saves 0.848 seconds from every unchanged direct game launch. Any
target, backup, or loader identity change falls back to the full validation;
the fast path is not a replacement for first-run verification. See [the tablet
evidence](evidence/proton-preparation-identity-cache-tablet-20260824.json).

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
| Transient CEF launch boost | 65.193 | -20.2% |
| Launch boost + compiled FEX cache | 64.200 | -21.5% |
| **Compiled cache + DXVK 2.4.1 x32** | **55.339** | **-32.3%** |
| **Refreshed FEX generation 6 + DXVK 2.4.1** | **53.553** | **-34.5%** |
| FEX generation 7 + DXVK 2.4.1 | 55.303 | -32.3%; valid, not promoted |
| Generation 7 + forced 7 DXVK workers | 58.670 | -28.2%; valid, rejected |
| Restored generation 6 confirmation | 59.381 | -27.4%; visual pass, no new record |
| Copied DXVK cache + explicit path | 58.634 | -28.3%; no promotion |

Session-to-runtime fell from 30 to 12 seconds while runtime-to-window remained
roughly flat (51.742 vs 53.193 seconds). A 2800x1752 tablet screenshot confirmed
Tomb Raider's rendered terms UI; the game was then terminated without restarting
Steam or X11. This is one controlled engineering A/B, not a latency distribution.
See [the result](evidence/steam-direct-appid-window-launch-boost-20260824.json).

The next same-session A/B changed only the direct game launcher's default FEX
cache mode from `on` to `compiled`:

| Launch boundary | Launch boost | Compiled cache |
| --- | ---: | ---: |
| Session to runtime request | 12.000 | 12.000 |
| Runtime request to Proton | 11.367 | 9.313 |
| Runtime request to game process | 19.762 | 18.775 |
| Game process to stable window | 33.431 | 33.425 |
| **Session to stable window** | **65.193** | **64.200** |

The compiled cache saved 0.993 seconds overall (-1.5% from the preceding
control), while leaving the largest 33.4-second game initialization boundary
unchanged. The 2800x1752 screenshot is a full-screen Tomb Raider loading frame;
Steam and X11 kept the same process identities. See the [compiled-cache
result](evidence/steam-direct-appid-window-compiled-fex-20260824.json).

After correcting the repeat-launch cache gate, the same warm-session test
changed only the renderer from bundled DXVK to the already hash-pinned official
x32 DXVK 2.4.1 payload:

| Launch boundary | Bundled DXVK | DXVK 2.4.1 |
| --- | ---: | ---: |
| Session to runtime request | 12.000 | 11.000 |
| Runtime request to game process | 18.775 | 17.434 |
| Game process to stable window | 33.425 | 26.905 |
| **Session to stable window** | **64.200** | **55.339** |

The candidate saved 8.861 seconds (-13.8%) from the preceding control and
26.403 seconds (-32.3%) from the original 81.742-second path. A 2800x1752
screenshot proves the full-screen Tomb Raider loading UI. The overlay restored,
four learned FEX maps remained available for refresh, and Steam/X11 identities
were unchanged. This is one engineering A/B, not a latency distribution.

The first no-override confirmation of the promoted defaults completed in
57.320 seconds and again produced a full-screen loading frame. Its external
timer first observed the DXVK cache marker at 46.220 seconds after the runtime
request and the visible window at 46.320 seconds. Because DXVK buffers its log,
these markers identify the end—not the internal shape—of the remaining delay.

After compiling ten retained runtime maps into verified FEX cache generation
6, the same warm AppID path completed in **53.553 seconds**, a new best. That
is 1.786 seconds / 3.2% faster than the 55.339-second generation-5 best and
28.189 seconds / 34.5% faster than the original path. The target appeared at
16.858 seconds after the runtime request, Wine Vulkan at 28.560, D3D11 at
29.379, and the game window at 42.553. A screenshot confirms the real
full-screen game startup; Steam and X11 identities were unchanged. This is one
engineering pass, not a latency distribution.

## Excluded measurements

| Date | Route | Observation | Why excluded |
| --- | --- | --- | --- |
| 2026-08-24 | Ordinary Steam/PRoot game route | Duplicate readiness pass removed; strict forwards took 12.38s and 11.12s | Both accepted containers exited before the game process; [evidence](evidence/steam-warm-appid-single-pass-excluded-20260824.txt) |
| 2026-08-24 | Direct AppID + DXVK 2.4.1 | Service exited 125 before Wine | Expected FEX runtime deltas exposed a repeat-launch validation defect; no timing result |
| 2026-08-24 | Integrated startup prefetch, two attempts | Steam outer process exited before dispatcher handoff | No game/window timing; prefetch itself completed in 0.255s |
| 2026-08-24 | Manual 48.4-MB prefetch + normal path | 55.357s to game Terms window | Slower than 53.553s best; prefetch remains off |
| 2026-08-24 | `lean-tmp-only` final preload | No game PID/window; service exit 225 | Required compatibility shims remain enabled; [evidence](evidence/tombraider-lean-tmp-only-rejected-20260824.json) |
| 2026-08-24 | First-paint guard v3 | 0.024s candidate-to-class; 2.137s candidate-to-reveal | UI polish only; same two-second hold, no launch-speed claim |

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

For startup diagnosis, `time-steam-game-launch.py --dxvk-log-root DIR` can also
timestamp first state-cache, swapchain, and compiler markers from only the new
DXVK log directory created by that run. This is an external polling sidecar,
not game instrumentation, and remains outside the render/frame path.
The same timer externally observes Wine Vulkan, DXGI, D3D11, and Turnip module
maps for only the verified game PID, avoiding buffered-log ordering when
partitioning startup.

The first module-timed tablet run split the 26.783-second process-to-window
interval almost evenly: 12.769 seconds before Wine Vulkan/Turnip mapped, then
14.014 seconds from those graphics modules to the visible window. The complete
AppID-to-window result was 57.828 seconds. CPU/I/O counters are the next gate;
the split alone does not prove storage or translation is responsible.
The next timer revision samples cumulative CPU and I/O counters for the same
verified PID at those boundaries so a hot-file mirror is attempted only if the
tablet shows meaningful reads rather than CPU work or waits.

The attribution run completed in 58.564 seconds and confirmed two different
targets:

| Startup segment | Wall | Game CPU | Physical reads | Conclusion |
| --- | ---: | ---: | ---: | --- |
| Target -> Wine Vulkan | 12.755s | 4.12s | 49.4 MiB | overlap bounded hot-file reads with handoff |
| D3D11 -> DXVK cache marker | 13.885s | 13.45s | 1.4 MiB | CPU-bound translation/graphics setup |

The screenshot was a genuine full-screen 2800x1752 Tomb Raider loading frame.
These are cumulative `/proc` deltas from one run, not benchmark FPS or a
latency distribution. Exact counters are in
[the process-metrics evidence](evidence/steam-appid-process-metrics-host-20260824.json).

Generation 7 compiled six later learning maps and passed full cache validation,
but its correctly routed AppID run reached the same full-screen loading frame in
55.303 seconds—1.750 seconds slower than generation 6's best. Generation 6
therefore remains the published performance record. Two earlier attempts are
excluded because they invoked the ordinary Steam wrapper rather than the direct
dispatcher and never created a game process; that UX ambiguity motivated the
manifest-backed `start-steam-game APPID` entry point.

The new public command then passed end to end on the tablet: `start-steam-game
203160` resolved the reviewed profile, entered the authenticated direct
dispatcher, and reached the real full-screen Terms UI in 58.688 seconds. This
is a repeatability/packaging acceptance result, not a performance promotion;
53.553 seconds remains the launch record. See [the AppID launcher
evidence](evidence/generic-appid-launcher-tablet-20260824.json).

Forcing seven DXVK compiler workers was also ineffective for startup. The game
log proves the exact seven-worker setting, but the full-screen game frame took
58.670 seconds from AppID session start—slower than both generation-7 automatic
selection and the 53.553-second record. Automatic selection remains the default.
See [the compiler-worker evidence](evidence/tombraider-appid-dxvk-compiler7-20260824.json).

Generation 6 was then restored from its authenticated external archive using a
same-filesystem swap and the new idempotent cache audit. The public
`start-steam-game 203160` path reached a stable window in 59.381 seconds; an
initial black capture was rejected, while a later screenshot proved the real
full-screen Terms UI. This validates the restored cache but is slower than its
53.553-second best, which remains the published record. See [the restore
evidence](evidence/tombraider-fex-cache-generation6-restored-20260824.json).

The internal DXVK cache experiment reached the same full-screen Terms UI in
**58.634 seconds**, only 0.747 seconds faster than the adjacent 59.381-second
confirmation and 5.081 seconds slower than the record. More importantly, the
source compatdata cache was already on Termux's private internal filesystem;
the experiment copied it to another directory on the same device. The DXVK log
continued to report its Windows-visible AppData path, so this run does not
prove a distinct physical-cache fast path. External/default placement remains
selected. See [the bounded result](evidence/tombraider-dxvk-state-cache-internal-20260824.json).
