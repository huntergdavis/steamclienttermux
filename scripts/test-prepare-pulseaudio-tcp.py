#!/usr/bin/env python3

import json
import os
from pathlib import Path
import subprocess
import tempfile


MOCK_PROGRAM = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

state_path = Path(os.environ["PULSE_TEST_STATE"])
state = json.loads(state_path.read_text())
program = Path(sys.argv[0]).name
args = sys.argv[1:]
state.setdefault("calls", []).append(
    {
        "program": program,
        "args": args,
        "runtime": os.environ.get("PULSE_RUNTIME_PATH"),
    }
)


def save():
    state_path.write_text(json.dumps(state))


if program == "pulseaudio":
    if args == ["--start", "--exit-idle-time=-1"] and state.get("start_ok", True):
        state["local_up"] = True
        save()
        raise SystemExit(0)
    save()
    raise SystemExit(1)

server_arg = next((arg for arg in args if arg.startswith("--server=")), None)
server = server_arg.partition("=")[2] if server_arg else ""
command = [arg for arg in args if arg != server_arg]

if command == ["info"]:
    if server == "tcp:127.0.0.1:4713":
        state["tcp_probes"] = state.get("tcp_probes", 0) + 1
        succeeds_after = state.get("tcp_succeeds_after")
        success = state.get("tcp_up", False) or (
            succeeds_after is not None and state["tcp_probes"] >= succeeds_after
        )
    else:
        success = state.get("local_up", False)
    save()
    raise SystemExit(0 if success else 1)

if command == ["list", "short", "modules"]:
    if not state.get("list_ok", True):
        save()
        raise SystemExit(1)
    for module in state.get("modules", []):
        print("\t".join(module))
    save()
    raise SystemExit(0)

if len(command) >= 2 and command[:2] == ["load-module", "module-native-protocol-tcp"]:
    if not state.get("load_ok", True):
        save()
        raise SystemExit(1)
    state.setdefault("modules", []).append(
        ["42", "module-native-protocol-tcp", " ".join(command[2:]), "n/a"]
    )
    state["load_count"] = state.get("load_count", 0) + 1
    if state.get("load_enables_tcp", True):
        state["tcp_up"] = True
    save()
    print("42")
    raise SystemExit(0)

save()
raise SystemExit(2)
'''


def write_state(path, **updates):
    state = {
        "local_up": False,
        "tcp_up": False,
        "modules": [],
        "start_ok": True,
        "list_ok": True,
        "load_ok": True,
        "load_enables_tcp": True,
    }
    state.update(updates)
    path.write_text(json.dumps(state))


def read_state(path):
    return json.loads(path.read_text())


def invoke(helper, base, mock_bin, state_path):
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{mock_bin}:{env['PATH']}",
            "PULSE_TEST_STATE": str(state_path),
        }
    )
    return subprocess.run(
        [os.environ.get("BASH", "bash"), str(helper), str(base)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def calls_for(state, program, command=None):
    calls = [call for call in state["calls"] if call["program"] == program]
    if command is not None:
        calls = [call for call in calls if command in call["args"]]
    return calls


def run_tests():
    repo = Path(__file__).resolve().parent.parent
    helper = repo / "bin" / "prepare-pulseaudio-tcp.sh"

    with tempfile.TemporaryDirectory(prefix="pulse-preflight-test.") as temp:
        tempdir = Path(temp)
        mock_bin = tempdir / "bin"
        mock_bin.mkdir()
        mock = mock_bin / "pulse-test-mock"
        mock.write_text(MOCK_PROGRAM)
        mock.chmod(0o700)
        (mock_bin / "pactl").symlink_to(mock.name)
        (mock_bin / "pulseaudio").symlink_to(mock.name)
        state_path = tempdir / "state.json"

        # A healthy canonical endpoint must be a side-effect-free fast path.
        write_state(state_path, tcp_up=True)
        base = tempdir / "healthy"
        result = invoke(helper, base, mock_bin, state_path)
        assert result.returncode == 0, result.stderr
        state = read_state(state_path)
        assert len(state["calls"]) == 1
        assert state["calls"][0]["args"] == [
            "--server=tcp:127.0.0.1:4713",
            "info",
        ]
        assert not base.exists()

        # A cold start uses the fixed runtime, creates one exact TCP module,
        # and a second invocation does not start or load anything again.
        write_state(state_path)
        base = tempdir / "bootstrap"
        first = invoke(helper, base, mock_bin, state_path)
        second = invoke(helper, base, mock_bin, state_path)
        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr
        state = read_state(state_path)
        starts = calls_for(state, "pulseaudio")
        loads = calls_for(state, "pactl", "load-module")
        assert len(starts) == 1
        assert starts[0]["runtime"] == str(base / "run" / "pulse")
        assert len(loads) == 1
        assert loads[0]["args"] == [
            f"--server=unix:{base}/run/pulse/native",
            "load-module",
            "module-native-protocol-tcp",
            "listen=127.0.0.1",
            "port=4713",
            "auth-ip-acl=127.0.0.1",
            "auth-anonymous=1",
        ]
        assert state["load_count"] == 1

        # If the exact module is already present, a transient failed probe
        # must not create a duplicate before the mandatory re-probe.
        exact_module = [
            "17",
            "module-native-protocol-tcp",
            "auth-anonymous=1 port=4713 listen=127.0.0.1",
            "n/a",
        ]
        write_state(
            state_path,
            local_up=True,
            modules=[exact_module],
            tcp_succeeds_after=2,
        )
        base = tempdir / "existing"
        result = invoke(helper, base, mock_bin, state_path)
        assert result.returncode == 0, result.stderr
        state = read_state(state_path)
        assert not calls_for(state, "pulseaudio")
        assert not calls_for(state, "pactl", "load-module")
        assert state["tcp_probes"] == 2

        # A differently bound module does not satisfy the loopback endpoint.
        wrong_module = [
            "9",
            "module-native-protocol-tcp",
            "listen=0.0.0.0 port=4713",
            "n/a",
        ]
        write_state(state_path, local_up=True, modules=[wrong_module])
        base = tempdir / "wrong-binding"
        result = invoke(helper, base, mock_bin, state_path)
        assert result.returncode == 0, result.stderr
        state = read_state(state_path)
        assert len(calls_for(state, "pactl", "load-module")) == 1

        # Loading a module is not success unless the canonical TCP endpoint
        # can actually be reached afterward.
        write_state(state_path, local_up=True, load_enables_tcp=False)
        base = tempdir / "failed-reprobe"
        result = invoke(helper, base, mock_bin, state_path)
        assert result.returncode != 0
        assert "canonical TCP server is unreachable after preflight" in result.stderr

    print("PulseAudio TCP preflight tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_tests())
