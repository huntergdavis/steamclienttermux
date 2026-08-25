#!/usr/bin/env python3

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "bin" / "steam-arm"


def main() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")

    # The removable root contains libraryfolder.vdf. It must stay on internal
    # F2FS because Android portable storage cannot satisfy Steam's flock(2).
    assert 'pd_args+=(--bind "$removable_source:$removable_target")' not in source
    assert "lock-bearing libraryfolder.vdf" in source

    expected = (
        'pd_args+=(--bind "$removable_steamapps:$removable_target/steamapps")',
        'pd_args+=(--bind "$removable_common:$removable_target/steamapps/common")',
        'pd_args+=(--bind "$removable_compatdata:$removable_target/steamapps/compatdata")',
        'pd_args+=(--bind "$removable_downloads:$removable_target/steamapps/downloading")',
    )
    positions = [source.index(line) for line in expected]
    assert positions == sorted(positions)

    print("removable library lock boundary contract: PASS")


if __name__ == "__main__":
    main()
