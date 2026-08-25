# GameNative input reuse

Reviewed GameNative commit
`1ad70ae54dcac1b9ae50d0b42c816e95f40cf22f`.

| Pattern | Reused here | Boundary |
| --- | --- | --- |
| Android input-device listener | Gamepad hot-plug and unplug state | One XInput controller for now |
| Physical gamepad key/axis routing | Buttons, hats, sticks, triggers | Rumble is not yet proven |
| Touchpad versus captured pointer | Touch never captures; mouse uses relative input | Termux:X11 remains the X server |
| Batched relative-axis history | All captured mouse deltas are accumulated | Live external trackpad still needs user proof |
| Background UDP sender | Android input callbacks never perform network I/O | Ordered localhost state stream |
| Per-game container defaults | App-local XInput DLL and NMS-only Wine override | No global Wine override |

GameNative is GPL-3.0 and remains valuable upstream prior art. This port uses
the same architecture, not its container/runtime: our native ARM64 Steam,
glibc, FEX, DXVK, and Turnip path remains unchanged.

Sources:

- [GameNative](https://github.com/utkarshdalal/GameNative)
- [PhysicalControllerHandler](https://github.com/utkarshdalal/GameNative/blob/1ad70ae54dcac1b9ae50d0b42c816e95f40cf22f/app/src/main/java/app/gamenative/ui/screen/xserver/PhysicalControllerHandler.kt)
- [TouchpadView captured-pointer path](https://github.com/utkarshdalal/GameNative/blob/1ad70ae54dcac1b9ae50d0b42c816e95f40cf22f/app/src/main/java/com/winlator/widget/TouchpadView.java)
- [Controller hot-plug lifecycle](https://github.com/utkarshdalal/GameNative/blob/1ad70ae54dcac1b9ae50d0b42c816e95f40cf22f/app/src/main/java/app/gamenative/MainActivity.kt)

GameNative's roadmap and open discussions still list Steam Input and relative
mouse reliability as active work. These patterns reduce our gap; they are not
evidence that every controller or game is solved.

The first live 8BitDo event exposed Android's
`NetworkOnMainThreadException`: motion callbacks execute on the Activity UI
thread. The final bridge preserves event order with one background sender.
Version 19 then produced handshake code 8 and state code 9 without an error,
while NMS mapped the matching app-local XInput DLL.
