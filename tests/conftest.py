import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kpin import cli  # noqa: E402
from pykeepass import create_database  # noqa: E402

from tests.helpers import run_cli  # noqa: E402


@pytest.fixture
def mock_vault(tmp_path):
    """A session-local mock vault with two entries, properties, and an attachment.

    Returns:
        dict with "home", "vault_dir", "config_dir", "config_file", "registry_file",
        "local_file", "entry", "other", "props", "att_name", "att_bytes".
    """
    home = tmp_path / "home"
    home.mkdir()
    vault_dir = home / "vault"
    vault_dir.mkdir()
    config_dir = home / ".config" / "kpin"
    config_file = config_dir / "config.json"
    registry_file = config_dir / "projects.json"
    entry = "default"
    other = "other"
    props = {
        "MOCK_SECRET": "MOCK_VAL",
        "MOCK_TOKEN": "tok-12345",
        "MOCK_EMPTY": "",
    }
    att_name = "mock.json"
    att_bytes = b'{"client": "mock"}'

    (vault_dir / "test.key").write_bytes(os.urandom(64))
    (vault_dir / "test.key").chmod(0o600)
    kp = create_database(
        str(vault_dir / "test.kdbx"), keyfile=str(vault_dir / "test.key")
    )
    e1 = kp.add_entry(kp.root_group, entry, username="kpin", password="placeholder")
    e2 = kp.add_entry(kp.root_group, other, username="kpin", password="placeholder")
    for key, value in props.items():
        e1.set_custom_property(key, value)
    e2.set_custom_property("MOCK_OTHER", "OTHER_VAL")
    bin_id = kp.add_binary(att_bytes)
    e1.add_attachment(bin_id, att_name)
    kp.save()

    return {
        "home": home,
        "vault_dir": vault_dir,
        "config_dir": config_dir,
        "config_file": config_file,
        "registry_file": registry_file,
        "entry": entry,
        "other": other,
        "props": props,
        "att_name": att_name,
        "att_bytes": att_bytes,
        "db": vault_dir / "test.kdbx",
        "keyfile": vault_dir / "test.key",
    }


@pytest.fixture
def isolated_env(mock_vault, monkeypatch):
    """Isolates config dir + HOME so no real kpin state is touched.

    Also sets KPIN_CONFIG to a nonexistent path so env-var resolution (which is
    checked before the local file) can never leak to a real config.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(mock_vault["config_dir"].parent))
    monkeypatch.setenv("HOME", str(mock_vault["home"]))
    monkeypatch.setenv("KPIN_CONFIG", "")

    cfg_file = mock_vault["home"] / "cfg.json"
    cfg_file.write_text(
        json.dumps(
            {
                "name": "mock",
                "db": str(mock_vault["db"]),
                "keyfile": str(mock_vault["keyfile"]),
                "entry": mock_vault["entry"],
            }
        )
    )
    mock_vault["cfg_file"] = cfg_file
    return mock_vault


@pytest.fixture
def registry_entry(mock_vault):
    return {
        "name": "mock",
        "db": str(mock_vault["db"]),
        "keyfile": str(mock_vault["keyfile"]),
        "entry": mock_vault["entry"],
    }


@pytest.fixture
def write_registry(isolated_env, registry_entry, monkeypatch):
    def _write(data=None):
        data = data or registry_entry
        cli._save_registry({data["name"]: data})
        return data

    return _write
