import json
from pathlib import Path

from tests.helpers import run_cli


def test_status_with_config_flag(isolated_env, mock_vault):
    cfg = {
        "name": "mock",
        "db": str(mock_vault["db"]),
        "keyfile": str(mock_vault["keyfile"]),
        "entry": mock_vault["entry"],
    }
    cfg_file = mock_vault["home"] / "cfg.json"
    cfg_file.write_text(json.dumps(cfg))
    r = run_cli(["status", "--config", str(cfg_file)])
    assert r["rc"] == 0
    assert "project: mock" in r["out"]
    assert str(mock_vault["db"]) in r["out"]


def test_status_via_registry(isolated_env, write_registry):
    write_registry()
    r = run_cli(["status", "--project", "mock"])
    assert r["rc"] == 0
    assert "project: mock" in r["out"]


def test_status_registry_project_missing(isolated_env):
    r = run_cli(["status", "--project", "ghost"])
    assert r["rc"] == 1
    assert "ghost" in r["err"]


def test_status_no_config_error(isolated_env):
    r = run_cli(["status"])
    assert r["rc"] == 1
    assert "No vault configured" in r["err"]


def test_kpin_config_flag_takes_priority_over_registry(
    isolated_env, write_registry, mock_vault
):
    cfg = {
        "name": "flagged",
        "db": str(mock_vault["db"]),
        "keyfile": str(mock_vault["keyfile"]),
        "entry": mock_vault["other"],
    }
    cfg_file = mock_vault["home"] / "flagged.json"
    cfg_file.write_text(json.dumps(cfg))
    r = run_cli(["status", "--project", "mock", "--config", str(cfg_file)])
    assert r["rc"] == 0
    assert "project: flagged" in r["out"]


def test_kpin_config_env_var_takes_priority_over_registry(
    isolated_env, write_registry, mock_vault, monkeypatch
):
    cfg = {
        "name": "envd",
        "db": str(mock_vault["db"]),
        "keyfile": str(mock_vault["keyfile"]),
        "entry": mock_vault["other"],
    }
    cfg_file = mock_vault["home"] / "envd.json"
    cfg_file.write_text(json.dumps(cfg))
    monkeypatch.setenv("KPIN_CONFIG", str(cfg_file))
    r = run_cli(["status", "--project", "mock"])
    assert r["rc"] == 0
    assert "project: envd" in r["out"]


def test_local_vault_file_discovery(isolated_env, write_registry, mock_vault):
    project_dir = mock_vault["home"] / "proj"
    project_dir.mkdir()
    (project_dir / ".kpin").write_text(
        json.dumps(
            {
                "name": "local",
                "db": str(mock_vault["db"]),
                "keyfile": str(mock_vault["keyfile"]),
                "entry": mock_vault["entry"],
            }
        )
    )
    r = run_cli(["status"], cwd=str(project_dir))
    assert r["rc"] == 0
    assert "project: local" in r["out"]


def test_portable_tilde_path_resolution(isolated_env, mock_vault):
    project_dir = mock_vault["home"] / "proj_tilde"
    project_dir.mkdir()
    (project_dir / ".kpin").write_text(
        json.dumps(
            {
                "name": "tilde_proj",
                "db": "~/vault/test.kdbx",
                "keyfile": "~/vault/test.key",
                "entry": "default",
            }
        )
    )
    r = run_cli(["status"], cwd=str(project_dir))
    assert r["rc"] == 0
    assert "project: tilde_proj" in r["out"]
    assert str(mock_vault["db"]) in r["out"]


def test_cross_platform_legacy_linux_path_fallback(isolated_env, mock_vault):
    project_dir = mock_vault["home"] / "proj_legacy_linux"
    project_dir.mkdir()
    (project_dir / ".kpin").write_text(
        json.dumps(
            {
                "name": "legacy_linux",
                "db": "/home/ian/vault/test.kdbx",
                "keyfile": "/home/ian/vault/test.key",
                "entry": "default",
            }
        )
    )
    r = run_cli(["status"], cwd=str(project_dir))
    assert r["rc"] == 0
    assert "project: legacy_linux" in r["out"]
    assert str(mock_vault["db"]) in r["out"]


def test_cross_platform_legacy_macos_path_fallback(isolated_env, mock_vault):
    project_dir = mock_vault["home"] / "proj_legacy_macos"
    project_dir.mkdir()
    (project_dir / ".kpin").write_text(
        json.dumps(
            {
                "name": "legacy_macos",
                "db": "/Users/ian/vault/test.kdbx",
                "keyfile": "/Users/ian/vault/test.key",
                "entry": "default",
            }
        )
    )
    r = run_cli(["status"], cwd=str(project_dir))
    assert r["rc"] == 0
    assert "project: legacy_macos" in r["out"]
    assert str(mock_vault["db"]) in r["out"]
