# Proton 10 ARM64EC on Termux:X11

This is an interoperability result, not a packaged GameNative fork.

| Gate | Result |
| --- | --- |
| Proton 10 WCP integrity | Pass |
| Private Turnip on Adreno 730 | Pass |
| ARM64EC Windows command | Pass |
| Real Windows pixels in Termux:X11 | Pass |
| Steam-authenticated NMS | Not yet |
| Controller and gameplay | Not yet |

## Reusable finding

GameNative normally owns its X server and sets `TMPDIR` inside its imagefs.
Termux:X11 instead publishes its Unix socket below Termux's temporary
directory. Keeping the GameNative value produces a black Windows process;
using `$PREFIX/tmp` renders Winemine correctly. `DISPLAY=:0` alone is not
enough.

The prefix also needs GameNative's missing-only DLL overlay from Proton's
`aarch64-windows` and `i386-windows` directories, followed by `wineboot -u`.
Neither operation modifies the installed Steam or Proton 11 paths.

## NMS boundary

The Proton WCP deliberately contains no Steam bridge. GameNative downloads a
Proton-matched `lsteamclient` pair and a Bionic `libsteamclient.so`, then runs
`libsteambootstrap.so` before Wine. That helper is proprietary and its source
is withheld in GameNative's own notice. It must not be bundled into this
project without separate permission.

The next experiment must keep the working X11/Vulkan candidate unchanged and
change only Steam authentication. A synthetic frame does not establish NMS
gameplay, controller support, or FPS.

Sources: [GameNative manifest](https://github.com/utkarshdalal/GameNative/blob/master/manifest.json),
[Bionic launcher](https://github.com/utkarshdalal/GameNative/blob/master/app/src/main/java/com/winlator/xenvironment/components/BionicProgramLauncherComponent.java),
[Steam assets](https://github.com/utkarshdalal/GameNative/blob/master/app/src/main/java/app/gamenative/utils/launchdependencies/BionicSteamAssetsDependency.kt),
and [third-party notices](https://github.com/utkarshdalal/GameNative/blob/master/THIRD_PARTY_NOTICES).
