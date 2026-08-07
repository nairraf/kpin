import json

from tests.helpers import run_cli


def test_init_creates_vault_in_config_vault_dir(isolated_env, mock_vault, monkeypatch):
    monkeypatch.setenv("KPIN_CONFIG", "")
    vault_dir = mock_vault["home"] / "myvaults"
    r = run_cli(["config", "vault_dir", str(vault_dir)])
    assert r["rc"] == 0

    proj = mock_vault["home"] / "proj"
    proj.mkdir()
    r2 = run_cli(["init", "--project", "p1"], cwd=str(proj))
    assert r2["rc"] == 0
    assert (vault_dir / "p1.kdbx").exists()
    assert (vault_dir / "p1.key").exists()
    assert (vault_dir / "p1.key").stat().st_mode & 0o777 == 0o600

    reg = json.loads((mock_vault["config_dir"] / "projects.json").read_text())
    assert "p1" in reg
    assert reg["p1"]["db"] == str(vault_dir / "p1.kdbx")

    local = proj / ".kpin"
    assert local.exists()
    assert json.loads(local.read_text())["db"] == str(vault_dir / "p1.kdbx")


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
