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
SPEC = importlib.util.spec_from_file_location("nms_proton", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


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

    destination, changed = module.prepare_tool(source, tools, spec)
    assert changed
    assert dll.read_bytes() == payload
    contained = destination / module.DLL_RELATIVE
    assert contained.read_bytes() == patched
    assert contained.stat().st_ino != dll.stat().st_ino
    assert (destination / "proton").stat().st_ino != proton.stat().st_ino
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

print("contained No Man's Sky Proton tool tests: PASS")
