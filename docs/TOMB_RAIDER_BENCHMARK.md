# Tomb Raider (2013) benchmark comparison

## First measured run

The first complete built-in benchmark ran on the Samsung Galaxy Tab S8+
(SM-X808U, Snapdragon 8 Gen 1/SM8450, Adreno 730, 7.12 GiB usable RAM) through
this repository's official Proton 11 ARM64, bundled FEX, DXVK, private Turnip,
and Termux:X11 path.

| Setting | Measured value |
|---|---|
| Game setting | 1280x720, Low |
| Motion blur/post-process/screen effects/tessellation/shadows/SSAO | Off |
| V-Sync | Double Buffer (`VSyncMode=1`) |
| `TombRaider.exe` affinity | CPUs 4-7 |
| Termux:X11 server affinity | CPUs 0-3 |
| Minimum | **5.8 FPS** |
| Maximum | **18.0 FPS** |
| Average | **13.6 FPS** |

The user read the three values directly from the result dialog. The automated
capture hit a black exclusive-fullscreen buffer, and the game returned to its
main menu before the foreground retry, so the repository does not claim a
result screenshot that it does not have. The retained
[`tombraider-start-benchmark-2026-08-14.png`](evidence/tombraider-start-benchmark-2026-08-14.png)
shows the real Windows game at its built-in `Start Benchmark` control.

This was the first benchmark pass after first launch, not a warmed three-pass
sample. At the completed result, 1,900,812 KiB remained available and
5,158,284 KiB of swap remained free. It was not an OOM result.

## What the percentage difference means

The closest built-in benchmark recording found during this research used
GameFusion 2.0.3, Proton 9 ARM64, and a Snapdragon 8+ Gen 1 Redmi K60. Its
side-by-side result reported 43.1/88.9/63.0 FPS with Turnip and
58.9/101.4/83.6 FPS with the Android system driver. The recording does not
show a trustworthy matching resolution/preset, and 8+ Gen 1 is not the same
SoC, so this is an upper comparison rather than an apples-to-apples result:
[primary recording at the result frame](https://www.youtube.com/watch?v=TtTjQr9tKOk&t=80s).

Using the Turnip result:

| Metric | This project | Published comparison | Comparison / ours | Ours is lower by | Comparison is faster by |
|---|---:|---:|---:|---:|---:|
| Minimum | 5.8 | 43.1 | 7.43x | 86.5% | 643.1% |
| Maximum | 18.0 | 88.9 | 4.94x | 79.8% | 393.9% |
| Average | 13.6 | 63.0 | 4.63x | 78.4% | 363.2% |

The last two columns have different denominators. “Ours is 78.4% lower” means
`(63.0 - 13.6) / 63.0`; “the comparison is 363.2% faster” means
`(63.0 - 13.6) / 13.6`. The least ambiguous statement is **4.63 times the
measured average throughput**.

Qualcomm describes 8+ Gen 1 as 10% faster in CPU performance and GPU clocks
than 8 Gen 1, with substantially better efficiency. That matters for sustained
performance, but it cannot by itself explain a 4.63x gap:
[Qualcomm 8+ Gen 1 product brief](https://www.qualcomm.com/content/dam/qcomm-martech/dm-assets/documents/Snapdragon-8-plus-Gen-1-Product-Brief.pdf).

## Same-chip evidence

No Tomb Raider submission for Adreno 730 was present in the current
[GameNative compatibility database](https://gamenative.app/compatibility/),
and no same-chip GameHub built-in benchmark was found. That absence is why the
8+ Gen 1 result above is not presented as an exact comparison.

A primary recording does exist for an unrooted Motorola Edge Plus (2022) with
the exact Snapdragon 8 Gen 1, Adreno 730, and 8 GB memory class. It used
Winlator Bionic, Proton 9 ARM64EC, FEXCore 2508, DXVK 2.4.1, and Turnip 26.0 R1.
The visible game settings were 1280x720 Low, V-Sync off, fullscreen/exclusive
fullscreen on, and motion blur and screen effects off. Sampled gameplay frames
showed the on-screen counter between 35.9 and 62.7 FPS:
[primary same-chip recording](https://www.youtube.com/watch?v=LN5PWI8DcR4&t=73s).

That is instantaneous gameplay, not the built-in benchmark, so comparing it
directly with 13.6 FPS average would overstate precision. As a broad bound, our
average is 62.1% below 35.9 FPS and 78.3% below 62.7 FPS. The important result
is not a precise percentage; it is that the same silicon has demonstrated far
more performance through a closely related Proton/FEX/DXVK/Turnip stack.

A GameHub recording on the nearby Snapdragon 8+ Gen 1/Adreno 730 reports
45-72 FPS at 720p, again as gameplay rather than the built-in benchmark:
[primary GameHub recording](https://www.youtube.com/watch?v=Zwq3uJz1-Po).

## Why this run is probably leaving performance on the table

The saved prefix registry proves that the game requested 1280x720 and disabled
the expensive Low-profile effects, but it also proves `VSyncMode=1` (Double
Buffer). The same-chip recording used V-Sync off. Double-buffered V-Sync is the
first setting to remove because missed refresh deadlines can quantize output to
lower refresh divisors.

The game requested 1280x720 while the only observed X display remained
2800x1586. That native surface has 4.8186 times as many pixels as 720p. As a
hypothesis—not a measured scaling law—`13.6 * 4.8186 = 65.5 FPS`, strikingly
close to the 63.0 FPS comparison. A fullscreen X window does not prove the
DXVK swapchain rendered at native resolution, so the next run must log the
actual swapchain extent instead of assuming either resolution.

The official Termux:X11 project now documents this exact Samsung OneUI cpuset
problem and offers an integrated Termux build so the X11 process is spawned by
the visible foreground app. That is a cleaner long-term answer than retaining
a tiny Termux pop-up over the game:
[Termux:X11 Samsung cpuset documentation](https://github.com/termux/termux-x11#termux-with-termuxx11-embedded).

The installed official Proton payload contains FEX release 2605, newer than the
FEXCore 2508 same-chip recording, and the private Turnip is Mesa 26.2-devel.
Changing translators or drivers is therefore lower priority than verifying the
presentation path and removing V-Sync.

## Next controlled passes

Change one variable at a time and use one warm-up plus three recorded passes:

1. Keep the present stack, 1280x720 Low, and the 4-7/0-3 CPU split; set V-Sync
   **Off**. This isolates the confirmed settings mismatch.
2. Set Termux:X11 to exact 1280x720 before launch. Record `xrandr` and enable a
   bounded DXVK info log to prove the swapchain extent. Do not infer it from
   window geometry.
3. Back up Termux and evaluate the official integrated Termux:X11 build for the
   Samsung foreground-cpuset fix. Do not replace the live app without a
   recovery plan.
4. Compare CPUs 4-7 against a deliberate all-core control while retaining X11
   on 0-3. The current affinity is informed, but it is not yet benchmarked for
   this game.
5. Only after those passes, measure a launch-only session with KDE/Plasma and
   nonessential Steam CEF processes absent. Preserve Steam authentication and
   verify that closing the client does not terminate the game before using that
   route for a recorded pass.

The required `deja "Snapdragon 8 Gen 1 Adreno 730 Tomb Raider GameHub
GameNative benchmark FPS"` and focused benchmark/affinity searches returned no
indexed prior-session match. The comparisons above come from primary recordings,
Qualcomm's product brief, GameNative's live compatibility service, and this
run's measured registry/process state.
