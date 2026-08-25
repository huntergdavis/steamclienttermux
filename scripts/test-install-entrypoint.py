#!/usr/bin/env python3

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    source = (ROOT / "install.sh").read_text(encoding="utf-8")
    release = (ROOT / "scripts/build-release-archive.py").read_text(encoding="utf-8")
    assert source.startswith("#!/data/data/com.termux/files/usr/bin/bash\n")
    assert 'installer=$repo_root/scripts/bootstrap-termux-stack.sh' in source
    assert '[[ $# -eq 0 ]]' in source
    assert 'exec "$installer"' in source
    assert '"install.sh"' in release
    print("simple install entrypoint contract: PASS")


if __name__ == "__main__":
    main()
