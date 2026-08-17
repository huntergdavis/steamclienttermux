#!/usr/bin/env python3

from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "steam-arm-native"


def main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "linux_pulse_lib=$linux_lib/pulseaudio" in source
    assert "! -L $linux_pulse_lib" in source
    assert "library_path=" in source
    library_path = next(
        line for line in source.splitlines() if line.startswith("library_path=")
    )
    assert "$linux_lib:$linux_pulse_lib:$linux_usr_lib" in library_path
    assert 'check_dependencies "$client/steamui.so" \'Steam UI\'' in source
    print("native Steam library-path tests: PASS")


if __name__ == "__main__":
    main()
