#!/usr/bin/env python3

import importlib.util
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/configure-steam-app-proton.py"


def load_module():
    spec = importlib.util.spec_from_file_location("configure_steam_app_proton", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONFIG = b'''"InstallConfigStore"\r
{\r
\t"Software"\r
\t{\r
\t\t"Valve"\r
\t\t{\r
\t\t\t"Steam"\r
\t\t\t{\r
\t\t\t\t"Other"\t\t"kept"\r
\t\t\t\t"CompatToolMapping"\r
\t\t\t\t{\r
\t\t\t\t\t"12210"\r
\t\t\t\t\t{\r
\t\t\t\t\t\t"name"\t\t"old-tool"\r
\t\t\t\t\t\t"config"\t\t"x"\r
\t\t\t\t\t\t"priority"\t\t"100"\r
\t\t\t\t\t}\r
\t\t\t\t}\r
\t\t\t}\r
\t\t}\r
\t}\r
}\r
'''


def main():
    module = load_module()
    rendered = module.render_mapping(
        CONFIG, "275850", "proton_11_arm64_official", 250
    )
    assert b'"Other"\t\t"kept"\r\n' in rendered
    assert rendered.count(b'"275850"') == 1
    assert b'"name"\t\t"proton_11_arm64_official"' in rendered
    assert module.render_mapping(
        rendered, "275850", "proton_11_arm64_official", 250
    ) == rendered
    replaced = module.render_mapping(
        CONFIG, "12210", "proton_11_arm64_official", 250
    )
    assert b'"old-tool"' not in replaced
    assert replaced.count(b'"12210"') == 1
    duplicate = CONFIG.replace(
        b'\t\t\t\t\t}\r\n\t\t\t\t}\r\n',
        b'\t\t\t\t\t}\r\n'
        b'\t\t\t\t\t"12210"\r\n'
        b'\t\t\t\t\t{\r\n'
        b'\t\t\t\t\t}\r\n'
        b'\t\t\t\t}\r\n',
        1,
    )
    assert duplicate != CONFIG
    try:
        module.render_mapping(duplicate, "275850", "proton_11_arm64_official", 250)
    except module.MappingError as error:
        assert "duplicate VDF object" in str(error)
    else:
        raise AssertionError("duplicate AppID was accepted")

    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        base = temporary / "steam-arm64"
        config = base / "client/config/config.vdf"
        config.parent.mkdir(parents=True)
        config.write_bytes(CONFIG)
        original, metadata = module.load_config(config)
        wanted = module.render_mapping(
            original, "275850", "proton_11_arm64_official", 250
        )
        backup = module.install_config(config, original, metadata, wanted, base)
        assert backup.read_bytes() == CONFIG
        assert config.read_bytes() == wanted
        proc = temporary / "proc"
        (proc / "42").mkdir(parents=True)
        (proc / "42/comm").write_text("steam\n")
        assert module.active_processes(proc) == [(42, "steam")]
        target = temporary / "target"
        target.write_bytes(CONFIG)
        link = temporary / "link"
        link.symlink_to(target)
        try:
            module.load_config(link)
        except module.MappingError as error:
            assert "regular non-symlink" in str(error)
        else:
            raise AssertionError("symlink config was accepted")
    print("generic Steam ARM64 Proton mapping tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
