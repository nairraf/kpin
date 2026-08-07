from kpin import cli
from tests.helpers import run_cli


def test_config_dir_is_xdg(isolated_env, mock_vault):
    assert cli.config_dir() == mock_vault["config_dir"]
    assert cli.registry_file() == mock_vault["registry_file"]


def test_config_show_defaults(isolated_env):
    r = run_cli(["config", "show"])
    assert r["rc"] == 0
    assert "vault_dir=~/.kpin" in r["out"]


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
