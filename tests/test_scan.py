import json
import os
import subprocess
import stat

from tests.helpers import run_cli


def _write_cfg(isolated_env, mock_vault, name="scan"):
    cfg = mock_vault["home"] / f"{name}.json"
    cfg.write_text(
        json.dumps(
            {
                "name": "mock",
                "db": str(mock_vault["db"]),
                "keyfile": str(mock_vault["keyfile"]),
                "entry": mock_vault["entry"],
            }
        )
    )
    return cfg


def _git(project, *args):
    subprocess.run(["git", "-C", str(project), *args], check=True)


def _init_git(project):
    _git(project, "init", "-q")


def test_scan_audit_healthy(isolated_env, mock_vault):
    cfg = _write_cfg(isolated_env, mock_vault)
    r = run_cli(["scan", "audit", "--config", str(cfg), "--silent"])
    assert r["rc"] == 0
    assert "OK" in r["out"]
    assert "FAIL" not in r["out"]


def test_scan_audit_missing_db(isolated_env, mock_vault):
    cfg = _write_cfg(isolated_env, mock_vault)
    mock_vault["db"].unlink()
    r = run_cli(["scan", "audit", "--config", str(cfg), "--silent"])
    assert r["rc"] == 1
    assert "vault database missing" in r["out"]


def test_scan_audit_missing_keyfile(isolated_env, mock_vault):
    cfg = _write_cfg(isolated_env, mock_vault)
    mock_vault["keyfile"].unlink()
    r = run_cli(["scan", "audit", "--config", str(cfg), "--silent"])
    assert r["rc"] == 1
    assert "keyfile missing" in r["out"]


def test_scan_audit_bad_keyfile_perms(isolated_env, mock_vault):
    cfg = _write_cfg(isolated_env, mock_vault)
    mock_vault["keyfile"].chmod(0o644)
    r = run_cli(["scan", "audit", "--config", str(cfg), "--silent"])
    assert r["rc"] == 0
    assert "keyfile perms" in r["out"]
    assert "WARN" in r["out"]


def test_scan_audit_not_git_repo(isolated_env, mock_vault):
    cfg = _write_cfg(isolated_env, mock_vault)
    r = run_cli(["scan", "audit", "--config", str(cfg)])
    assert r["rc"] == 0
    assert "SKIP: not a git repo" in r["out"]


def test_scan_audit_silent_hides_skip(isolated_env, mock_vault):
    cfg = _write_cfg(isolated_env, mock_vault)
    r = run_cli(["scan", "audit", "--config", str(cfg), "--silent"])
    assert r["rc"] == 0
    assert "SKIP" not in r["out"]


def test_scan_audit_kpin_tracked(isolated_env, mock_vault, monkeypatch):
    project = mock_vault["home"] / "proj"
    project.mkdir()
    (project / ".kpin").write_text(
        json.dumps(
            {
                "name": "mock",
                "db": str(mock_vault["db"]),
                "keyfile": str(mock_vault["keyfile"]),
                "entry": mock_vault["entry"],
            }
        )
    )
    _init_git(project)
    _git(project, "add", ".kpin")
    monkeypatch.chdir(project)
    r = run_cli(["scan", "audit", "--silent"])
    assert r["rc"] == 1
    assert ".kpin is tracked" in r["out"]


def test_scan_audit_kpin_gitignored(isolated_env, mock_vault, monkeypatch):
    project = mock_vault["home"] / "proj"
    project.mkdir()
    (project / ".kpin").write_text(
        json.dumps(
            {
                "name": "mock",
                "db": str(mock_vault["db"]),
                "keyfile": str(mock_vault["keyfile"]),
                "entry": mock_vault["entry"],
            }
        )
    )
    (project / ".gitignore").write_text(".kpin\n")
    _init_git(project)
    _git(project, "add", ".gitignore")
    monkeypatch.chdir(project)
    r = run_cli(["scan", "audit", "--silent"])
    assert r["rc"] == 0
    assert ".kpin is gitignored" in r["out"]


def test_scan_audit_env_and_vault_tracked(isolated_env, mock_vault, monkeypatch):
    project = mock_vault["home"] / "proj"
    project.mkdir()
    (project / ".kpin").write_text(
        json.dumps(
            {
                "name": "mock",
                "db": str(mock_vault["db"]),
                "keyfile": str(mock_vault["keyfile"]),
                "entry": mock_vault["entry"],
            }
        )
    )
    (project / ".env").write_text("SECRET=x\n")
    (project / "vault.kdbx").write_bytes(b"fake")
    (project / ".key").write_bytes(b"fake")
    _init_git(project)
    _git(project, "add", ".kpin", ".env", "vault.kdbx", ".key")
    monkeypatch.chdir(project)
    r = run_cli(["scan", "audit", "--silent"])
    assert r["rc"] == 1
    assert ".env-style file tracked" in r["out"]
    assert "vault/keyfile tracked" in r["out"]


def test_scan_history_redacts_values(isolated_env, monkeypatch):
    home = isolated_env["home"]
    hist = home / ".bash_history"
    hist.write_text(
        "ls -la\n"
        "kpin set attribute API_KEY abcd1234\n"
        "kpin set password p@ssw0rd\n"
        "kpin run -- ./deploy.sh\n"
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    r = run_cli(["scan", "history", "--shell", "bash"])
    assert r["rc"] == 1
    assert "WARN" in r["out"]
    assert "abcd1234" not in r["out"]
    assert "p@ssw0rd" not in r["out"]
    assert "kpin set attribute API_KEY ***" in r["out"]


def test_scan_history_stdin_not_flagged(isolated_env, monkeypatch):
    home = isolated_env["home"]
    hist = home / ".bash_history"
    hist.write_text(
        "printf 'x' | kpin set attribute API_KEY --stdin\nkpin run -- ./deploy.sh\n"
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    r = run_cli(["scan", "history", "--shell", "bash"])
    assert r["rc"] == 0
    assert "no leaked kpin secrets" in r["out"]


def test_scan_history_zsh_extended(isolated_env, monkeypatch):
    home = isolated_env["home"]
    hist = home / ".zsh_history"
    hist.write_text(
        ": 1234567890:0;kpin set attribute ZSH_KEY zshsecret\n: 1234567891:0;ls\n"
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    r = run_cli(["scan", "history", "--shell", "zsh"])
    assert r["rc"] == 1
    assert "zshsecret" not in r["out"]
    assert "kpin set attribute ZSH_KEY ***" in r["out"]


def test_scan_history_fish(isolated_env, monkeypatch):
    home = isolated_env["home"]
    hist = home / ".local/share/fish/fish_history"
    hist.parent.mkdir(parents=True)
    hist.write_text("- cmd: kpin set attribute FISH_KEY fishsecret\n")
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    r = run_cli(["scan", "history", "--shell", "fish"])
    assert r["rc"] == 1
    assert "fishsecret" not in r["out"]
    assert "kpin set attribute FISH_KEY ***" in r["out"]


def test_scan_history_missing_file_not_fatal(isolated_env, monkeypatch):
    home = isolated_env["home"]
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    r = run_cli(["scan", "history", "--shell", "bash"])
    assert r["rc"] == 0
    assert "OK" in r["out"]
