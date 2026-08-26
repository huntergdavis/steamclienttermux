#!/usr/bin/env python3

import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts/build-xinput-udp.sh"
SOURCE = ROOT / "native/xinput-udp/xinput_udp.c"
ANDROID = ROOT / "android/termux-x11-gamepad/GamepadBridge.java"

EXPECTED = {
    "xinput1_3.dll": "3276f5443550a25bae01a61d99932feeb51d35986568dc3b80431539a73a070c",
    "xinput1_4.dll": "3fc6d898a3f1f0e66ea3b7428409eff3e2abb10e4401aa7209e9d214524e3534",
    "xinput9_1_0.dll": "11e928f5e337680efa6baa6e2a839795a79bd752387b1e0956ea805f1a25fa43",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    c_source = SOURCE.read_text(encoding="utf-8")
    java_source = ANDROID.read_text(encoding="utf-8")
    build_source = BUILD.read_text(encoding="utf-8")

    for source in (c_source, java_source):
        assert "CLIENT_PORT = 4600" in source or "BVB_CLIENT_PORT 4600" in source
        assert "SERVER_PORT = 4602" in source or "BVB_SERVER_PORT 4602" in source
        assert "PACKET_SIZE = 64" in source or "BVB_PACKET_SIZE 64" in source
    assert 'InetAddress.getByName("127.0.0.1")' in java_source
    assert "getLoopbackAddress" not in java_source
    assert "inet.getPort() == SERVER_PORT" in java_source
    assert "inet.getAddress().isLoopbackAddress()" in java_source
    assert "InputManager.InputDeviceListener" in java_source
    assert "registerInputDeviceListener" in java_source
    assert "unregisterInputDeviceListener" in java_source
    assert "activeDeviceId" in java_source
    assert "sendRelease()" in java_source
    assert "!device.isVirtual()" in java_source
    assert "sin_addr.s_addr ==\n                        htonl(INADDR_LOOPBACK)" in c_source
    assert "IN6_IS_ADDR_LOOPBACK" in c_source
    assert "bvb_accept_packet" in c_source
    assert "BVB_CODE_RELEASE_GAMEPAD" in c_source
    assert "--no-insert-timestamp" in build_source
    assert "--image-base" in build_source

    compiler = shutil.which("x86_64-w64-mingw32-gcc")
    objdump = shutil.which("x86_64-w64-mingw32-objdump")
    if compiler and objdump:
        with tempfile.TemporaryDirectory(prefix="xinput-udp.") as directory:
            output = Path(directory)
            subprocess.run([str(BUILD), str(output)], check=True, capture_output=True)
            for name, expected in EXPECTED.items():
                library = output / name
                assert library.read_bytes()[:2] == b"MZ"
                assert sha256(library) == expected
            for library_name in ("xinput1_4.dll", "xinput9_1_0.dll"):
                exports = subprocess.run(
                    [objdump, "-p", str(output / library_name)],
                    check=True,
                    text=True,
                    capture_output=True,
                ).stdout
                for name in ("XInputGetState", "XInputSetState", "XInputEnable"):
                    assert name in exports
            assert "XInputGetAudioDeviceIds" in subprocess.run(
                [objdump, "-p", str(output / "xinput1_4.dll")],
                check=True,
                text=True,
                capture_output=True,
            ).stdout

    print("XInput UDP bridge tests: PASS")


if __name__ == "__main__":
    main()
