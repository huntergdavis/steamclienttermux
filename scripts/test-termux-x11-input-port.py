#!/usr/bin/env python3

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / "android/termux-x11-gamepad"


def main() -> None:
    bridge = (PORT / "GamepadBridge.java").read_text(encoding="utf-8")
    patch = (PORT / "termux-x11-input.patch").read_text(encoding="utf-8")
    readme = (PORT / "README.md").read_text(encoding="utf-8")

    for token in (
        "InputManager.InputDeviceListener",
        "registerInputDeviceListener",
        "unregisterInputDeviceListener",
        "scanControllers()",
        "sendRelease()",
        "!device.isVirtual()",
        'InetAddress.getByName("127.0.0.1")',
    ):
        assert token in bridge

    assert "new GamepadBridge(this)" in patch
    assert "mGamepadBridge.close()" in patch
    assert "e.getHistorySize()" in patch
    assert "getHistoricalAxisValue(MotionEvent.AXIS_RELATIVE_X" in patch
    assert "ACTION_HOVER_MOVE" in patch
    assert "Touch and touchpads must never trigger capture" in patch
    assert "+        if (event.getAction() == MotionEvent.ACTION_UP)" not in patch
    assert "54d159166a4d8573da54d693e461a1def3751248" in readme

    print("Termux:X11 controller and dual-pointer port tests: PASS")


if __name__ == "__main__":
    main()
