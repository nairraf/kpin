import sys
from pathlib import Path

from tests.helpers import run_cli


def test_set_get_roundtrip(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["set", "MOCK_SET_1", "V1", "--config", cfg])
    assert r["rc"] == 0
    assert "MOCK_SET_1" in r["out"]
    r2 = run_cli(["get", "MOCK_SET_1", "--config", cfg])
    assert r2["rc"] == 0
    assert r2["out"].strip() == "V1"


def test_get_missing_secret(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["get", "NOPE", "--config", cfg])
    assert r["rc"] == 1
    assert "NOPE" in r["err"]


def test_set_stdin(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["set", "MOCK_STDIN", "--stdin", "--config", cfg], input="from-stdin\n")
    assert r["rc"] == 0
    r2 = run_cli(["get", "MOCK_STDIN", "--config", cfg])
    assert r2["out"].strip() == "from-stdin"


def test_env_lists_properties(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["env", "--config", cfg])
    assert r["rc"] == 0
    assert "MOCK_SECRET=MOCK_VAL" in r["out"]
    assert "MOCK_TOKEN=tok-12345" in r["out"]
    assert "MOCK_EMPTY=" in r["out"]


def test_validate_all_present(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["validate", "--config", cfg])
    assert r["rc"] == 1
    assert "MOCK_SECRET: present" in r["out"]
    assert "MOCK_EMPTY: missing" in r["out"]


def test_validate_specific_missing(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["validate", "MOCK_SECRET", "MOCK_GONE", "--config", cfg])
    assert r["rc"] == 1
    assert "MOCK_GONE: missing" in r["out"]


def test_attach_roundtrip(isolated_env, mock_vault):
    payload = b"ATTACH-CONTENT"
    f = mock_vault["home"] / "data.txt"
    f.write_bytes(payload)

    other_cfg = str(mock_vault["home"] / "other.json")
    (mock_vault["home"] / "other.json").write_text(
        "{\n"
        f'  "name": "mock",\n'
        f'  "db": "{mock_vault["db"]}",\n'
        f'  "keyfile": "{mock_vault["keyfile"]}",\n'
        f'  "entry": "{mock_vault["other"]}"\n'
        "}"
    )

    r = run_cli(["attach", str(f), "--config", other_cfg])
    assert r["rc"] == 0
    assert "data.txt" in r["out"]

    outfile = str(mock_vault["home"] / "att.out")
    r2 = run_cli(
        [
            "materialize",
            "--config",
            other_cfg,
            "--",
            sys.executable,
            "-c",
            f"import os; open({outfile!r},'wb').write(open(os.environ['KPIN_FILE'],'rb').read())",
        ]
    )
    assert r2["rc"] == 0
    assert open(outfile, "rb").read() == payload
