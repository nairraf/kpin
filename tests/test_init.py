import json

from tests.helpers import run_cli


def test_init_creates_vault_in_config_vault_dir(isolated_env, mock_vault, monkeypatch):
    monkeypatch.setenv("KPIN_CONFIG", "")
    vault_dir = mock_vault["home"] / "myvaults"
    key_dir = mock_vault["home"] / "mykeys"
    r = run_cli(["config", "vault_dir", str(vault_dir)])
    assert r["rc"] == 0
    r = run_cli(["config", "key_dir", str(key_dir)])
    assert r["rc"] == 0

    proj = mock_vault["home"] / "proj"
    proj.mkdir()
    r2 = run_cli(["init", "--project", "p1"], cwd=str(proj))
    assert r2["rc"] == 0
    assert (vault_dir / "p1.kdbx").exists()
    assert (key_dir / "p1.key").exists()
    assert (key_dir / "p1.key").stat().st_mode & 0o777 == 0o600
    assert not (vault_dir / "p1.key").exists()

    reg = json.loads((mock_vault["config_dir"] / "projects.json").read_text())
    assert "p1" in reg
    assert reg["p1"]["db"] == "~/myvaults/p1.kdbx"
    assert reg["p1"]["keyfile"] == "~/mykeys/p1.key"

    local = proj / ".kpin"
    assert local.exists()
    assert json.loads(local.read_text())["db"] == "~/myvaults/p1.kdbx"
    assert json.loads(local.read_text())["keyfile"] == "~/mykeys/p1.key"


def test_init_defaults_store_tilde_paths(isolated_env, mock_vault, monkeypatch):
    monkeypatch.setenv("KPIN_CONFIG", "")
    proj = mock_vault["home"] / "proj_default"
    proj.mkdir()
    r = run_cli(["init", "--project", "p_def"], cwd=str(proj))
    assert r["rc"] == 0
    assert (mock_vault["home"] / ".kpin" / "p_def.kdbx").exists()
    assert (mock_vault["home"] / ".keys" / "p_def.key").exists()

    local = proj / ".kpin"
    data = json.loads(local.read_text())
    assert data["db"] == "~/.kpin/p_def.kdbx"
    assert data["keyfile"] == "~/.keys/p_def.key"


def test_init_refuses_existing_vault(isolated_env, mock_vault, monkeypatch):
    monkeypatch.setenv("KPIN_CONFIG", "")
    from pykeepass import create_database

    existing_dir = mock_vault["home"] / ".kpin"
    existing_dir.mkdir()
    (existing_dir / "existing.key").write_bytes(b"x" * 64)
    create_database(
        str(existing_dir / "existing.kdbx"),
        keyfile=str(existing_dir / "existing.key"),
    )
    proj = mock_vault["home"] / "proj"
    proj.mkdir()
    r = run_cli(["init", "--project", "existing"], cwd=str(proj))
    assert r["rc"] == 1
    assert "already exists" in r["err"]


def test_init_warns_and_aborts_on_registered_name(
    isolated_env, write_registry, mock_vault
):
    write_registry()
    proj = mock_vault["home"] / "proj"
    proj.mkdir()
    r = run_cli(["init", "--project", "mock"], cwd=str(proj), input="n\n")
    assert r["rc"] == 1
    assert "already registered" in r["err"]
    assert "Aborted" in r["err"]
    assert not (proj / ".kpin").exists()


def test_init_reuses_existing_vault_on_confirm(
    isolated_env, write_registry, mock_vault
):
    write_registry()
    proj = mock_vault["home"] / "proj"
    proj.mkdir()
    r = run_cli(["init", "--project", "mock"], cwd=str(proj), input="y\n")
    assert r["rc"] == 0
    assert "Linked to existing vault" in r["out"]
    local = proj / ".kpin"
    assert local.exists()
    assert json.loads(local.read_text())["db"] == str(mock_vault["db"])
