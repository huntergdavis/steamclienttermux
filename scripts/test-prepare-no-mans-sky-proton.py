#!/usr/bin/env python3
"""Host contract for the contained No Man's Sky Proton tool."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import sys
import tempfile


SCRIPT = Path(__file__).with_name("prepare-no-mans-sky-proton.py")
ROOT = SCRIPT.parent.parent
SPEC = importlib.util.spec_from_file_location("nms_proton", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

bundled_openvr = ROOT / "assets/nms-openvr-stub/openvr_api.dll.b64"
decoded_openvr = __import__("base64").b64decode(bundled_openvr.read_bytes())
assert len(decoded_openvr) == module.OPENVR_SIZE
assert hashlib.sha256(decoded_openvr).hexdigest() == module.OPENVR_SHA256
installer = (ROOT / "scripts/install-project-files.sh").read_text()
assert 'assets/nms-openvr-stub/openvr_api.dll.b64' in installer
assert 'compat-bin/nms-openvr-stub/openvr_api.dll' in installer
for xinput_name, (xinput_size, xinput_sha256) in module.XINPUT_DLLS.items():
    bundled_xinput = ROOT / "assets/nms-xinput" / xinput_name
    assert bundled_xinput.stat().st_size == xinput_size
    assert hashlib.sha256(bundled_xinput.read_bytes()).hexdigest() == xinput_sha256
    assert f'assets/nms-xinput/{xinput_name}' in installer
    assert f'compat-bin/nms-xinput/{xinput_name}' in installer


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


with tempfile.TemporaryDirectory(prefix="nms-proton-tool.") as temporary:
    root = Path(temporary)
    source = root / "source"
    tools = root / "tools"
    dll = source / module.DLL_RELATIVE
    dll.parent.mkdir(parents=True)
    tools.mkdir(mode=0o700)
    source.chmod(0o700)
    before = b"ABCDEFGH"
    after = b"12345678"
    payload = b"prefix-" + before + b"-suffix"
    patched = b"prefix-" + after + b"-suffix"
    spec = module.PatchSpec(
        source_sha256=digest(payload),
        patched_sha256=digest(patched),
        offset=7,
        before=before,
        after=after,
    )
    dll.write_bytes(payload)
    dll.chmod(0o600)
    original_loader_chain_sha256 = module.LOADER_CHAIN_SHA256
    loader_payloads = {
        relative: f"reviewed Wine loader {relative}".encode()
        for relative in original_loader_chain_sha256
    }
    module.LOADER_CHAIN_SHA256 = {
        relative: digest(payload) for relative, payload in loader_payloads.items()
    }
    for relative, loader_payload in loader_payloads.items():
        loader = source / relative
        loader.parent.mkdir(parents=True, exist_ok=True)
        loader.write_bytes(loader_payload)
        loader.chmod(0o700)
    proton = source / "proton"
    proton.write_text("#!/bin/sh\nexit 0\n")
    proton.chmod(0o700)
    shared = source / "shared.bin"
    shared.write_bytes(b"shared payload")
    shared.chmod(0o600)
    (source / "version").write_bytes(module.SOURCE_VERSION)
    (source / "version").chmod(0o600)

    nt_before = b"NT00"
    nt_after = b"NT01"
    nt_next_before = b"RQ00"
    nt_next_after = b"RQ01"
    nt_pointer_before = b"PT00"
    nt_pointer_after = b"PT01"
    nt_payload = (
        b"ntoskrnl-prefix-" + nt_before + b"-middle-" + nt_next_before
        + b"-pointer-" + nt_pointer_before + b"-suffix"
    )
    first_patched_nt_payload = (
        b"ntoskrnl-prefix-" + nt_after + b"-middle-" + nt_next_before
        + b"-pointer-" + nt_pointer_before + b"-suffix"
    )
    second_patched_nt_payload = (
        b"ntoskrnl-prefix-" + nt_after + b"-middle-" + nt_next_after
        + b"-pointer-" + nt_pointer_before + b"-suffix"
    )
    patched_nt_payload = (
        b"ntoskrnl-prefix-" + nt_after + b"-middle-" + nt_next_after
        + b"-pointer-" + nt_pointer_after + b"-suffix"
    )
    ntoskrnl = source / module.NTOSKRNL_RELATIVE
    ntoskrnl.parent.mkdir(parents=True, exist_ok=True)
    ntoskrnl.write_bytes(nt_payload)
    ntoskrnl.chmod(0o600)
    original_nt_patch = module.NMS_NTOSKRNL_DEVICE_MANAGER_PATCH
    original_nt_next_patch = module.NMS_NTOSKRNL_GET_REQUEST_PATCH
    original_nt_pointer_patch = module.NMS_NTOSKRNL_OBJECT_POINTER_PATCH
    module.NMS_NTOSKRNL_DEVICE_MANAGER_PATCH = module.PatchSpec(
        source_sha256=digest(nt_payload),
        patched_sha256=digest(first_patched_nt_payload),
        offset=len(b"ntoskrnl-prefix-"),
        before=nt_before,
        after=nt_after,
    )
    module.NMS_NTOSKRNL_GET_REQUEST_PATCH = module.PatchSpec(
        source_sha256=digest(first_patched_nt_payload),
        patched_sha256=digest(second_patched_nt_payload),
        offset=len(b"ntoskrnl-prefix-") + len(nt_after) + len(b"-middle-"),
        before=nt_next_before,
        after=nt_next_after,
    )
    module.NMS_NTOSKRNL_OBJECT_POINTER_PATCH = module.PatchSpec(
        source_sha256=digest(second_patched_nt_payload),
        patched_sha256=digest(patched_nt_payload),
        offset=(
            len(b"ntoskrnl-prefix-") + len(nt_after) + len(b"-middle-")
            + len(nt_next_after) + len(b"-pointer-")
        ),
        before=nt_pointer_before,
        after=nt_pointer_after,
    )

    destination, changed = module.prepare_tool(source, tools, spec)
    assert changed
    assert dll.read_bytes() == payload
    contained = destination / module.DLL_RELATIVE
    assert contained.read_bytes() == patched
    assert contained.stat().st_ino != dll.stat().st_ino
    assert (destination / "proton").stat().st_ino != proton.stat().st_ino
    contained_ntoskrnl = destination / module.NTOSKRNL_RELATIVE
    assert contained_ntoskrnl.read_bytes() == patched_nt_payload
    assert contained_ntoskrnl.stat().st_ino != ntoskrnl.stat().st_ino
    for relative, loader_payload in loader_payloads.items():
        loader = source / relative
        contained_loader = destination / relative
        assert contained_loader.read_bytes() == loader_payload
        assert contained_loader.stat().st_ino != loader.stat().st_ino
        assert not contained_loader.is_symlink()
    assert (destination / "shared.bin").is_symlink()
    assert (destination / "shared.bin").resolve() == shared
    marker = module.validate_tool(destination, spec)
    assert marker == module.expected_marker(spec)
    assert stat.S_IMODE((destination / "compatibilitytool.vdf").stat().st_mode) == 0o600

    repeated, changed = module.prepare_tool(source, tools, spec)
    assert repeated == destination and not changed

    # Reconstruct the exact schema-3 layout and prove the upgrade is bounded.
    contained_ntoskrnl.unlink()
    contained_ntoskrnl.symlink_to(ntoskrnl)
    marker_path = destination / module.MARKER_NAME
    marker_path.write_text(json.dumps(module.legacy_marker(spec), sort_keys=True) + "\n")
    marker_path.chmod(0o600)
    upgraded, changed = module.prepare_tool(source, tools, spec)
    assert upgraded == destination and changed
    assert not contained_ntoskrnl.is_symlink()
    assert contained_ntoskrnl.read_bytes() == patched_nt_payload
    assert not (tools / f".{module.TOOL_DIRECTORY}.schema3-backup").exists()

    candidates = root / "candidates"
    candidates.mkdir(mode=0o700)
    openvr_source = root / module.OPENVR_SOURCE_RELATIVE
    openvr_source.parent.mkdir(parents=True, exist_ok=True)
    openvr_payload = b"reviewed OpenVR compatibility payload"
    openvr_source.write_bytes(openvr_payload)
    openvr_source.chmod(0o600)
    original_openvr_size = module.OPENVR_SIZE
    original_openvr_sha256 = module.OPENVR_SHA256
    module.OPENVR_SIZE = len(openvr_payload)
    module.OPENVR_SHA256 = digest(openvr_payload)
    candidate, changed = module.prepare_openvr_candidate(root, candidates)
    assert changed
    candidate_dll = module.validate_openvr_candidate(candidate)
    assert candidate_dll.name == "openvr_api.dll"
    assert candidate_dll.read_bytes() == openvr_payload
    assert candidate_dll.stat().st_ino != openvr_source.stat().st_ino
    repeated_candidate, changed = module.prepare_openvr_candidate(root, candidates)
    assert repeated_candidate == candidate and not changed

    game_openvr = root / module.GAME_OPENVR_RELATIVE
    game_openvr.parent.mkdir(parents=True, exist_ok=True)
    original_game_payload = b"reviewed original game OpenVR payload"
    game_openvr.write_bytes(original_game_payload)
    game_openvr.chmod(0o600)
    original_game_size = module.GAME_OPENVR_ORIGINAL_SIZE
    original_game_sha256 = module.GAME_OPENVR_ORIGINAL_SHA256
    module.GAME_OPENVR_ORIGINAL_SIZE = len(original_game_payload)
    module.GAME_OPENVR_ORIGINAL_SHA256 = digest(original_game_payload)
    installed_game_openvr, changed = module.prepare_game_openvr(root, candidate)
    assert changed and installed_game_openvr == game_openvr
    assert game_openvr.read_bytes() == openvr_payload
    game_backup = game_openvr.with_name(module.GAME_OPENVR_BACKUP_NAME)
    assert game_backup.read_bytes() == original_game_payload
    repeated_game_openvr, changed = module.prepare_game_openvr(root, candidate)
    assert repeated_game_openvr == game_openvr and not changed
    module.GAME_OPENVR_ORIGINAL_SIZE = original_game_size
    module.GAME_OPENVR_ORIGINAL_SHA256 = original_game_sha256

    original_xinput_dlls = module.XINPUT_DLLS
    xinput_payloads = {
        "xinput1_4.dll": b"reviewed xinput 1.4 payload",
        "xinput9_1_0.dll": b"reviewed xinput 9.1 payload",
    }
    module.XINPUT_DLLS = {
        name: (len(payload), digest(payload))
        for name, payload in xinput_payloads.items()
    }
    xinput_source = root / module.XINPUT_SOURCE_RELATIVE
    xinput_source.mkdir(parents=True, mode=0o700)
    for name, payload in xinput_payloads.items():
        source_library = xinput_source / name
        source_library.write_bytes(payload)
        source_library.chmod(0o600)
    installed_xinput, changed = module.prepare_game_xinput(root)
    assert changed
    assert [path.name for path in installed_xinput] == list(xinput_payloads)
    for path in installed_xinput:
        assert path.read_bytes() == xinput_payloads[path.name]
    repeated_xinput, changed = module.prepare_game_xinput(root)
    assert repeated_xinput == installed_xinput and not changed
    installed_xinput[0].write_bytes(b"foreign replacement")
    try:
        module.prepare_game_xinput(root)
    except module.ToolError as error:
        assert "refusing to replace" in str(error)
    else:
        raise AssertionError("foreign NMS XInput DLL was overwritten")
    module.XINPUT_DLLS = original_xinput_dlls

    candidate_dll.write_bytes(b"corrupt")
    try:
        module.validate_openvr_candidate(candidate)
    except module.ToolError as error:
        assert "unexpected" in str(error)
    else:
        raise AssertionError("corrupt OpenVR compatibility DLL was accepted")
    module.OPENVR_SIZE = original_openvr_size
    module.OPENVR_SHA256 = original_openvr_sha256

    loader_root_relative = Path("files/lib/wine/aarch64-unix/ntdll.so")
    loader_root = source / loader_root_relative
    contained_loader_root = destination / loader_root_relative
    contained_loader_root.unlink()
    contained_loader_root.symlink_to(loader_root)
    try:
        module.validate_tool(destination, spec)
    except module.ToolError as error:
        assert "Wine loader" in str(error)
    else:
        raise AssertionError("symlinked Wine loader root was accepted")
    contained_loader_root.unlink()
    contained_loader_root.write_bytes(loader_payloads[loader_root_relative])
    contained_loader_root.chmod(0o700)

    contained.write_bytes(b"corrupt")
    try:
        module.validate_tool(destination, spec)
    except module.ToolError as error:
        assert "hash is unexpected" in str(error)
    else:
        raise AssertionError("corrupt contained DLL was accepted")

    module.LOADER_CHAIN_SHA256 = original_loader_chain_sha256
    module.NMS_NTOSKRNL_DEVICE_MANAGER_PATCH = original_nt_patch
    module.NMS_NTOSKRNL_GET_REQUEST_PATCH = original_nt_next_patch
    module.NMS_NTOSKRNL_OBJECT_POINTER_PATCH = original_nt_pointer_patch

print("contained No Man's Sky Proton tool tests: PASS")
