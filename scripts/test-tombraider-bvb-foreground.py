#!/usr/bin/env python3

import importlib.util
import os
from pathlib import Path
import tempfile


TOOL = Path(__file__).with_name("run-tombraider-bvb-foreground.py")
BROKER = Path(__file__).with_name("start-tombraider-bvb-foreground.sh")
INSTALLER = Path(__file__).with_name("install-project-files.sh")


def load_tool():
    specification = importlib.util.spec_from_file_location(
        "run_tombraider_bvb_foreground", TOOL
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def main() -> None:
    module = load_tool()
    assert module.parse_cgroups(
        "5:cpuset:/top-app\n4:cpu:/top-app\n0::/uid_10469/pid_1\n"
    ) == {"cpuset": "/top-app", "cpu": "/top-app"}
    assert module.process_start_ticks("12 (child name) S " + "0 " * 18 + "12345 0\n") == 12345
    assert module.parse_bounds("40,40,520,360") == (40, 40, 520, 360)
    for invalid in ("40,40,40,360", "a,1,2,3", "1,2,3", "-20000,0,1,2"):
        try:
            module.parse_bounds(invalid)
        except module.argparse.ArgumentTypeError:
            pass
        else:
            raise AssertionError(f"invalid bounds accepted: {invalid}")

    task_dump = """
  * Recent #0: Task{3db498f #2852 type=standard A=10469:.MainActivity}
    mUserId=0 effectiveUid=u0a469 mCallingUid=u0a469
    realActivity={com.termux.x11/com.termux.x11.MainActivity}
  * Recent #1: Task{4c9dfa6 #2918 type=standard A=10323:io.github.huntergdavis.bvb.visiblehost}
    realActivity={io.github.huntergdavis.bvb.visiblehost/io.github.huntergdavis.bvb.visiblehost.VisibleHostActivity}
  Visible recent tasks (most recent first):
  * RecentTaskInfo #0:
    id=2852
    realActivity={com.termux.x11/com.termux.x11.MainActivity}
"""
    assert module.find_x11_task_id(task_dump) == 2852
    assert module.find_x11_task_id(
        task_dump.replace(
            "realActivity={com.termux.x11/com.termux.x11.MainActivity}",
            "mActivityComponent=com.termux.x11/.MainActivity",
        )
    ) == 2852
    duplicate = """
  * Recent #2: Task{3db498f #3000 type=standard A=10469:.MainActivity}
    mActivityComponent=com.termux.x11/.MainActivity
"""
    try:
        module.find_x11_task_id(
            task_dump.replace("\n  Visible recent tasks", duplicate + "\n  Visible recent tasks")
        )
    except module.ForegroundError:
        pass
    else:
        raise AssertionError("multiple X11 tasks were accepted")

    with tempfile.TemporaryDirectory(prefix="bvb-foreground-test.") as root_text:
        root = Path(root_text)
        properties = root / "termux.properties"
        original = b"# keep\n# allow-external-apps = true\nother=value\n"
        properties.write_bytes(original)
        properties.chmod(0o600)
        reload_log = root / "reload.log"
        reload_command = root / "reload"
        reload_command.write_text(
            "#!/bin/sh\nprintf 'reload\\n' >> \"$RELOAD_LOG\"\n", encoding="utf-8"
        )
        reload_command.chmod(0o700)
        old_environment = os.environ.get("RELOAD_LOG")
        os.environ["RELOAD_LOG"] = str(reload_log)
        try:
            guard = module.PropertyGuard(properties, reload_command)
            original_sha = guard.enable()
            assert properties.read_text().splitlines()[1] == "allow-external-apps = true"
            assert guard.restore() == original_sha
            assert properties.read_bytes() == original
            assert reload_log.read_text().splitlines() == ["reload", "reload"]
        finally:
            if old_environment is None:
                os.environ.pop("RELOAD_LOG", None)
            else:
                os.environ["RELOAD_LOG"] = old_environment

        proc = root / "proc"
        process = proc / "12"
        parent = proc / "34"
        process.mkdir(parents=True)
        parent.mkdir()
        (process / "cgroup").write_text("5:cpuset:/top-app\n4:cpu:/top-app\n")
        python = Path("/termux/python3")
        tool = Path("/termux/foreground.py")
        request = Path("/termux/request")
        (process / "cmdline").write_bytes(
            b"/termux/python3\0/termux/foreground.py\0--child\0/termux/request\0"
        )
        (process / "stat").write_text("12 (child) S " + "0 " * 18 + "9876 0\n")
        (parent / "cmdline").write_bytes(b"com.termux\0")
        child = {
            "pid": 12,
            "ppid": 34,
            "cpuset": "/top-app",
            "cpu": "/top-app",
        }
        assert module.validate_child(child, proc, python, tool, request) == (12, 9876)
        (process / "cgroup").write_text("5:cpuset:/background\n4:cpu:/background\n")
        try:
            module.validate_child(child, proc, python, tool, request)
        except module.ForegroundError as error:
            assert "not in Android top-app" in str(error)
        else:
            raise AssertionError("background child was accepted")

    command = module.runcommand_arguments(
        Path("/termux/am"),
        Path("/termux/python3"),
        Path("/termux/foreground.py"),
        "--child",
        Path("/termux/request"),
        Path("/termux/home"),
    )
    assert command == [
        "/termux/am",
        "startservice",
        "--user",
        "0",
        "-n",
        "com.termux/.app.RunCommandService",
        "-a",
        "com.termux.RUN_COMMAND",
        "--es",
        "com.termux.RUN_COMMAND_PATH",
        "/termux/python3",
        "--esa",
        "com.termux.RUN_COMMAND_ARGUMENTS",
        "/termux/foreground.py,--child,/termux/request",
        "--es",
        "com.termux.RUN_COMMAND_WORKDIR",
        "/termux/home",
        "--ez",
        "com.termux.RUN_COMMAND_BACKGROUND",
        "true",
    ]

    source = TOOL.read_text(encoding="utf-8")
    assert "os.kill(child_pid, signal.SIGTERM)" in source
    assert "killall" not in source and "pkill" not in source
    assert source.index("child_pid, child_start_ticks = validate_child") < source.index(
        "restored_sha = guard.restore()"
    )
    assert source.index("promote_x11(adb, serial") < source.index(
        "result = wait_for_result("
    )
    assert "Android polling stopped before the timed scene" in source
    assert '"--windowingMode",\n        "1"' in source
    installer = INSTALLER.read_text(encoding="utf-8")
    assert (
        'run-tombraider-bvb-foreground.py" \\\n'
        '    "$base/compat-bin/run-tombraider-bvb-foreground.py" 700'
        in installer
    )
    assert (
        'start-tombraider-bvb-foreground.sh" \\\n'
        '    "$HOME/start-tombraider-bvb-foreground" 700'
        in installer
    )
    assert "exec \"$python\" \"$tool\" \"$@\"" in BROKER.read_text(encoding="utf-8")
    assert 'python=$(readlink -f -- "$python")' in BROKER.read_text(encoding="utf-8")
    print("Tomb Raider BVB foreground launcher tests: PASS")


if __name__ == "__main__":
    main()
