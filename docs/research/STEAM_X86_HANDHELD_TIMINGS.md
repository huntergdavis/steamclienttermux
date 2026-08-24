# Steam timing context: x86 PCs and handhelds

Research date: 2026-08-24. This is a boundary-matched comparison, not a single synthetic leaderboard. Steam launch time changes with cache state, account/library size, network/cloud state, storage, game, and whether the measured endpoint is first window, main menu, or playable gameplay.

## Decision table

| Boundary | Our ARM64 tablet | External comparison | Read |
|---|---:|---:|---|
| Warm request to visible Steam UI | **1.662 s** | Windows community report: **1–2 s** after close/reopen | **PC-class; stop optimizing this boundary.** The external number is anecdotal and may retain warm caches/background state. |
| Cold wrapper to authenticated/login-ready Steam | **22.97 s** | Current desktop stopwatch test: **22.87 s** CachyOS, **32.94 s** Windows 11 | **Normal-to-good.** Our boundary additionally starts Termux:X11, but login-ready is not necessarily identical to the article's “launched” UI endpoint. |
| Cold stopped compatibility environment to usable Steam | **22.97 s** to login-ready, with Android already booted | Steam Deck: **25–27 s** SSD or **34 s** eMMC from power-on; Deck suspend to usable Library: **<3 s** | **Cold path is handheld-class.** Full device boot and suspend are different boundaries, so neither is a direct target. |
| Steam game request to AppID/process acceptance | **13.049 s** old second-client path; **8.971 s** direct FIFO adjacent pass | One current x86 Linux Steam log: about **4 s** from first logged game action to process added, including a one-step install evaluator; Linux/Proton user report: **10–15 s** to boot a game on fast NVMe | **Direct FIFO is within reported Proton territory, but about 5 s behind the clean x86 log example.** Stabilize the long tail; do not redesign the launcher again. |
| Runtime request to first Tomb Raider window | **22.213 s** in the valid cold run | Steam Deck Hollow Knight launch: **11.1–12.1 s**; Linux CS:GO: **10 s** to fullscreen and **23 s** to main menu; Deck Portal 2: **51 s** to menu | **Normal-to-good for a translated AAA game.** Game identity and endpoints differ, so this is range evidence only. |
| Cold wrapper to first Tomb Raider window | **49.513 s** | Deck cold boot (**25–34 s**) plus reported game launch/load ranges of roughly **19–51+ s** implies about **44–85+ s**, but those studies did not measure this combined boundary | **Already in the normal handheld zone.** This combined comparison is an inference, not a direct benchmark. |

## What the external measurements actually measured

| Source | Hardware / software | Boundary and result | Evidence quality |
|---|---|---|---|
| [Tom's Hardware Steam Deck SSD testing](https://www.tomshardware.com/video-games/handheld-gaming/how-to-upgrade-steam-deck-ssd) | Steam Deck, several SSDs and eMMC | Power-on boot: **25–27 s** on SSD, **34 s** on eMMC; Hollow Knight launch: **11.1–12.1 s** across SSDs | Measured review; good cold-device and lightweight-game baselines. Boot includes firmware, kernel, gamescope, and Steam, unlike our already-booted Android start. The article does not define the Hollow Knight launch endpoint precisely. |
| [GamingOnLinux Steam Deck review](https://www.gamingonlinux.com/2022/02/steam-deck-initial-review/) | Launch-era Steam Deck | Resume to usable Library: **<3 s**. Play to playable: Dead Cells **24 s**, Death Stranding **30 s**, God of War **63 s**, and several heavier games **60–194 s** on internal storage | Re-run/verified review measurements with an explicit “press play to controllable gameplay” endpoint. Intro videos were usually not skipped. |
| [TechRadar Steam Deck review](https://www.techradar.com/reviews/steam-deck) | 256 GB Steam Deck | Portal 2: launch to menu **51 s**, then **23 s** to a loaded save | Measured review, explicit endpoints; older SteamOS/client and a different game. |
| [Current Windows-vs-CachyOS stopwatch test](https://currently.att.yahoo.com/att/does-linux-really-run-faster-190117883.html) | Dual-boot desktop | Steam startup: Windows 11 **32.94 s**, CachyOS **22.87 s** after updates | Recent manual stopwatch comparison; run count, cold-cache protocol, and exact “launched” endpoint are not specified. |
| [Steam desktop discussion](https://steamcommunity.com/discussions/forum/0/532101539722970624/) | Windows PC | Closed/reopened Steam averaged **1–2 s** | Anecdote only; useful for warm-UI scale, not a cold-start benchmark. |
| [Valve steam-runtime issue #541](https://github.com/ValveSoftware/steam-runtime/issues/541) | Arch x86-64, fast NVMe | Proton 5.13+ containerized games reported at **10–15 s** to boot; native games **<=1 s** | User measurement in Valve's primary issue tracker. Endpoint and game are unspecified; useful only as launch-overhead scale. |
| [Steam SnowRunner diagnostic log](https://steamcommunity.com/app/1465360/discussions/0/800090354736087524/) | Current x86 Linux/Proton Steam | First logged game action at 21:46:55; install evaluator at 21:46:56; game process added at 21:46:59: about **4 s** | Exact Steam timestamps and state-machine phases. It is one troubleshooting run of another game, not a controlled benchmark. |
| [Valve CS:GO Linux issue #608](https://github.com/ValveSoftware/csgo-osx-linux/issues/608) | x86-64 Linux, NVMe | Play to fullscreen **10 s**, then **13 s** black screen; **23 s** total to main menu | Timed report with screen recording and explicit endpoints, but from 2016 and a native game. |

## Recommendation: stop broad speed work, bound the tail

The overall answer is **we are within normal handheld/Linux distance now, not orders of magnitude slow**. The 1.662-second warm UI is excellent. The 22.97-second cold Steam readiness matches a current desktop Linux stopwatch result almost exactly and is competitive with Steam Deck cold boot. The 49.513-second cold environment-to-Tomb-Raider-window result sits inside the broad handheld experience range.

The remaining worthwhile performance work is narrow: Steam's game-action tail. The direct FIFO removed a redundant client launch, but integrated acceptance still varies because `RunInstallScript`, cloud, license, controller, and game-action work remains inside proprietary Steam. Use these stop/continue gates over at least 10 alternating runs:

| Boundary | Stop optimizing and shift to packaging | Continue targeted profiling |
|---|---:|---:|
| Warm visible Steam UI | median **<=2 s**, p95 **<=3 s** | p95 **>5 s** |
| Cold wrapper to login-ready | median **<=25 s**, p95 **<=35 s** | median **>30 s** |
| Direct request to AppID accepted | median **<=10 s**, p95 **<=15 s** | median **>10 s** or p95 **>20 s** |
| Runtime request to first game window | median **<=25 s**, p95 **<=35 s** | median **>30 s** after acceptance is stable |
| Cold wrapper to first game window | median **<=50 s**, p95 **<=60 s** | median **>60 s** |

If those thresholds hold, prioritize installer/package reproducibility, first-run dependency checks, generic AppID-to-game discovery, per-game profiles, and recovery diagnostics. Do not trade controller support or cloud correctness for a small mean-time gain; only promote such a change if it materially improves median **and** p95 without a feature regression.

## Local evidence and recall

Our figures come from [`steam-cold-appid-acceptance-20260824.json`](../evidence/steam-cold-appid-acceptance-20260824.json), including the valid cold run and adjacent acceptance profiles. The required Deja query was run before research; it produced no reusable result before being interrupted after roughly one minute, so no past-session implementation or claim is reused here.
