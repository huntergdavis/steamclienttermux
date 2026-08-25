#!/usr/bin/env python3

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = REPO_ROOT / "bin" / "steam-arm"


def main():
    source = LAUNCHER.read_text()
    lines = [line.strip() for line in source.splitlines()]
    common = {
        "FEX_MAXINST=5000",
        "FEX_PROFILESTATS=0",
        "FEX_DISABLEL2CACHE=0",
        "FEX_DYNAMICL1CACHE=0",
        "FEX_X87REDUCEDPRECISION=1",
        "FEX_MULTIBLOCK=1",
        "FEX_VECTORTSOENABLED=0",
        "FEX_MEMCPYSETTSOENABLED=0",
        "FEX_SMALLTSCSCALE=1",
        "FEX_SMC_CHECKS=mtrack",
        "FEX_VOLATILEMETADATA=1",
        "FEX_MONOHACKS=1",
        "FEX_HIDEHYPERVISORBIT=0",
        "STEAM_FEX_MULTIBLOCK=1",
    }
    for assignment in common:
        assert lines.count(assignment) == 1, assignment
    for assignment in (
        "FEX_TSOENABLED=0",
        "FEX_TSOENABLED=1",
        "FEX_HALFBARRIERTSOENABLED=0",
        "FEX_HALFBARRIERTSOENABLED=1",
        "STEAM_FEX_TSOENABLED=0",
        "STEAM_FEX_TSOENABLED=1",
    ):
        assert lines.count(assignment) == 1, assignment
    assert 'safe|fast)' in source
    assert 'if [[ "$fex_profile" == fast ]]' in source
    assert 'pd_args+=(--env "$fex_assignment")' in source
    assert "must be proton, safe, or fast" in source
    assert 'runtime_direct_run="$base/config/steamlinuxruntime4-run-direct"' in source
    assert (
        'pd_args+=(--bind "$runtime_direct_run:$arm_runtime_depot/run")'
        in source
    )
    assert source.index('pd_args+=(--bind "$arm_runtime:$arm_runtime_depot")') < source.index(
        'pd_args+=(--bind "$runtime_direct_run:$arm_runtime_depot/run")'
    )
    assert (
        'python3 "$runtime_root_prep" --base "$base" '
        '--refresh-mount-anchors-only' in source
    )
    print("Steam ARM64 FEX profile tests: PASS")


if __name__ == "__main__":
    main()
