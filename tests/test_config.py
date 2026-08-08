import json

from kpin import cli
from tests.helpers import run_cli


def test_config_dir_is_xdg(isolated_env, mock_vault):
    assert cli.config_dir() == mock_vault["config_dir"]
    assert cli.registry_file() == mock_vault["registry_file"]


def test_config_show_defaults(isolated_env):
    r = run_cli(["config", "show"])
    assert r["rc"] == 0
    assert "vault_dir=~/.kpin" in r["out"]
    assert "key_dir=~/.keys" in r["out"]


def test_config_set(isolated_env, mock_vault):
    r = run_cli(["config", "vault_dir", "~/.kpin-test"])
    assert r["rc"] == 0
    assert "vault_dir=~/.kpin-test" in r["out"]
    assert mock_vault["config_file"].is_file()


def test_config_get_after_set(isolated_env):
    run_cli(["config", "vault_dir", "~/.kpin-test"])
    r = run_cli(["config", "vault_dir"])
    assert r["rc"] == 0
    assert r["out"].strip() == "~/.kpin-test"


def test_config_unknown_key_rejected(isolated_env):
    r = run_cli(["config", "bogus", "x"])
    assert r["rc"] == 1
    assert "bogus" in r["err"]


def test_config_unset(isolated_env):
    run_cli(["config", "vault_dir", "~/.kpin-test"])
    r = run_cli(["config", "--unset", "vault_dir"])
    assert r["rc"] == 0
    assert r["out"].strip() == "Unset vault_dir"
    r2 = run_cli(["config", "vault_dir"])
    assert r2["out"].strip() == "~/.kpin"


def test_config_show_reflects_settings(isolated_env):
    run_cli(["config", "vault_dir", "/tmp/vaults"])
    r = run_cli(["config", "show"])
    assert r["rc"] == 0
    assert "vault_dir=/tmp/vaults" in r["out"]


def test_config_bare_is_show(isolated_env):
    r = run_cli(["config"])
    assert r["rc"] == 0
    assert "vault_dir=~/.kpin" in r["out"]
    assert "key_dir=~/.keys" in r["out"]


def test_config_clean_env_extra_set_and_get(isolated_env):
    r = run_cli(["config", "clean_env_extra", "ANDROID_HOME,JAVA_HOME"])
    assert r["rc"] == 0
    r2 = run_cli(["config", "clean_env_extra"])
    assert r2["rc"] == 0
    assert r2["out"].strip() == "ANDROID_HOME,JAVA_HOME"


def test_config_clean_env_extra_show_default_empty(isolated_env):
    r = run_cli(["config", "show"])
    assert r["rc"] == 0
    assert "clean_env_extra=" in r["out"]


def test_config_clean_env_extra_unset(isolated_env):
    run_cli(["config", "clean_env_extra", "ANDROID_HOME"])
    r = run_cli(["config", "--unset", "clean_env_extra"])
    assert r["rc"] == 0
    r2 = run_cli(["config", "clean_env_extra"])
    assert r2["out"].strip() == ""


def test_config_local_set_get(isolated_env, mock_vault):
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
    r = run_cli(
        ["config", "--local", "clean_env_extra", "ANDROID_HOME"], cwd=str(project_dir)
    )
    assert r["rc"] == 0
    data = json.loads((project_dir / ".kpin").read_text())
    assert data["clean_env_extra"] == ["ANDROID_HOME"]
    r2 = run_cli(["config", "--local", "clean_env_extra"], cwd=str(project_dir))
    assert r2["out"].strip() == "ANDROID_HOME"


def test_config_local_no_kpin_errors(isolated_env):
    r = run_cli(["config", "--local", "clean_env_extra", "ANDROID_HOME"])
    assert r["rc"] == 1
    assert "No .kpin found" in r["err"]


def test_config_local_unset(isolated_env, mock_vault):
    project_dir = mock_vault["home"] / "proj"
    project_dir.mkdir()
    (project_dir / ".kpin").write_text(
        json.dumps(
            {
                "name": "local",
                "db": str(mock_vault["db"]),
                "keyfile": str(mock_vault["keyfile"]),
                "entry": mock_vault["entry"],
                "clean_env_extra": ["ANDROID_HOME"],
            }
        )
    )
    r = run_cli(
        ["config", "--local", "--unset", "clean_env_extra"], cwd=str(project_dir)
    )
    assert r["rc"] == 0
    data = json.loads((project_dir / ".kpin").read_text())
    assert "clean_env_extra" not in data


def test_config_local_show(isolated_env, mock_vault):
    project_dir = mock_vault["home"] / "proj"
    project_dir.mkdir()
    (project_dir / ".kpin").write_text(
        json.dumps(
            {
                "name": "local",
                "db": str(mock_vault["db"]),
                "keyfile": str(mock_vault["keyfile"]),
                "entry": mock_vault["entry"],
                "clean_env_extra": ["ANDROID_HOME", "JAVA_HOME"],
            }
        )
    )
    r = run_cli(["config", "--local", "show"], cwd=str(project_dir))
    assert r["rc"] == 0
    assert r["out"].strip() == "clean_env_extra=ANDROID_HOME,JAVA_HOME"


def test_config_local_rejects_global_only_keys(isolated_env, mock_vault):
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
    r = run_cli(["config", "--local", "vault_dir", "/tmp/x"], cwd=str(project_dir))
    assert r["rc"] == 1
    assert "global-only" in r["err"]


def test_config_config_flag_targets_kpin(isolated_env, mock_vault):
    project_dir = mock_vault["home"] / "proj"
    project_dir.mkdir()
    kpin_file = project_dir / ".kpin"
    kpin_file.write_text(
        json.dumps(
            {
                "name": "local",
                "db": str(mock_vault["db"]),
                "keyfile": str(mock_vault["keyfile"]),
                "entry": mock_vault["entry"],
            }
        )
    )
    r = run_cli(
        ["config", "--config", str(kpin_file), "clean_env_extra", "GRADLE_USER_HOME"]
    )
    assert r["rc"] == 0
    data = json.loads(kpin_file.read_text())
    assert data["clean_env_extra"] == ["GRADLE_USER_HOME"]
