import sys
from pathlib import Path

from tests.helpers import run_cli


def test_set_get_attribute_roundtrip(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["set", "attribute", "MOCK_SET_1", "V1", "--config", cfg])
    assert r["rc"] == 0
    assert "MOCK_SET_1" in r["out"]
    r2 = run_cli(["get", "attribute", "MOCK_SET_1", "--config", cfg])
    assert r2["rc"] == 0
    assert r2["out"].strip() == "V1"


def test_get_missing_attribute(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["get", "attribute", "NOPE", "--config", cfg])
    assert r["rc"] == 1
    assert "NOPE" in r["err"]


def test_set_attribute_stdin(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(
        ["set", "attribute", "MOCK_STDIN", "--stdin", "--config", cfg],
        input="from-stdin\n",
    )
    assert r["rc"] == 0
    r2 = run_cli(["get", "attribute", "MOCK_STDIN", "--config", cfg])
    assert r2["out"].strip() == "from-stdin"


def test_get_password_default_entry(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["get", "password", "--config", cfg])
    assert r["rc"] == 0
    assert r["out"].strip() == "placeholder"


def test_set_password(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["set", "password", "s3cret", "--config", cfg])
    assert r["rc"] == 0
    r2 = run_cli(["get", "password", "--config", cfg])
    assert r2["out"].strip() == "s3cret"


def test_env_lists_attributes(isolated_env, mock_vault):
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


def test_get_attachment_to_output_dir_keeps_name(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    out_dir = mock_vault["home"] / "certs"
    r = run_cli(
        [
            "get",
            "attachment",
            "--name",
            mock_vault["att_name"],
            "--output",
            str(out_dir),
            "--config",
            cfg,
        ]
    )
    assert r["rc"] == 0
    written = out_dir / mock_vault["att_name"]
    assert written.read_bytes() == mock_vault["att_bytes"]
    assert r["out"].strip() == str(written)


def test_get_attachment_listing(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["get", "attachment", "--config", cfg])
    assert r["rc"] == 0
    assert mock_vault["att_name"] in r["out"].split()


def test_get_attachment_missing_name(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["get", "attachment", "--name", "nope.pem", "--config", cfg])
    assert r["rc"] == 1
    assert "nope.pem" in r["err"]


def test_entry_add_and_list(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["entry", "add", "API_KEY", "--config", cfg])
    assert r["rc"] == 0
    assert "API_KEY" in r["out"]
    r2 = run_cli(["entry", "add", "AI Providers", "--config", cfg])
    assert r2["rc"] == 0
    r3 = run_cli(["entry", "list", "--config", cfg])
    assert r3["rc"] == 0
    titles = r3["out"].splitlines()
    assert mock_vault["entry"] in titles
    assert "API_KEY" in titles
    assert "AI Providers" in titles


def test_entry_add_duplicate_rejected(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["entry", "add", mock_vault["entry"], "--config", cfg])
    assert r["rc"] == 1
    assert "already exists" in r["err"]


def test_list_entries(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["list", "entries", "--config", cfg])
    assert r["rc"] == 0
    titles = r["out"].splitlines()
    assert mock_vault["entry"] in titles
    assert mock_vault["other"] in titles


def test_list_attributes_default_entry(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["list", "attributes", "--config", cfg])
    assert r["rc"] == 0
    names = r["out"].splitlines()
    assert "MOCK_SECRET" in names
    assert "MOCK_TOKEN" in names
    assert "MOCK_EMPTY" in names
    assert "MOCK_OTHER" not in names
    assert "MOCK_VAL" not in r["out"]


def test_list_attributes_named_entry(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["list", "attributes", "--entry", mock_vault["other"], "--config", cfg])
    assert r["rc"] == 0
    names = r["out"].splitlines()
    assert "MOCK_OTHER" in names
    assert "MOCK_SECRET" not in names


def test_list_attachments_default_entry(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(["list", "attachments", "--config", cfg])
    assert r["rc"] == 0
    assert mock_vault["att_name"] in r["out"].split()


def test_list_attachments_named_entry(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(
        ["list", "attachments", "--entry", mock_vault["other"], "--config", cfg]
    )
    assert r["rc"] == 0
    assert r["out"].strip() == ""


def test_get_attribute_from_named_entry(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(
        [
            "get",
            "attribute",
            "MOCK_OTHER",
            "--entry",
            mock_vault["other"],
            "--config",
            cfg,
        ]
    )
    assert r["rc"] == 0
    assert r["out"].strip() == "OTHER_VAL"


def test_get_password_from_named_entry(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    run_cli(
        ["set", "password", "named-pw", "--entry", mock_vault["other"], "--config", cfg]
    )
    r = run_cli(["get", "password", "--entry", mock_vault["other"], "--config", cfg])
    assert r["rc"] == 0
    assert r["out"].strip() == "named-pw"


def test_set_attribute_on_named_entry(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(
        [
            "set",
            "attribute",
            "NEW_ATTR",
            "v",
            "--entry",
            mock_vault["other"],
            "--config",
            cfg,
        ]
    )
    assert r["rc"] == 0
    r2 = run_cli(
        [
            "get",
            "attribute",
            "NEW_ATTR",
            "--entry",
            mock_vault["other"],
            "--config",
            cfg,
        ]
    )
    assert r2["out"].strip() == "v"


def test_get_attachment_to_exact_path(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    exact = str(mock_vault["home"] / "renamed.json")
    r = run_cli(
        [
            "get",
            "attachment",
            "--name",
            mock_vault["att_name"],
            "--output",
            exact,
            "--config",
            cfg,
        ]
    )
    assert r["rc"] == 0
    assert Path(exact).read_bytes() == mock_vault["att_bytes"]


def test_set_attachment_to_specific_entry(isolated_env, mock_vault):
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

    r = run_cli(["set", "attachment", str(f), "--config", other_cfg])
    assert r["rc"] == 0
    assert "data.txt" in r["out"]

    outfile = str(mock_vault["home"] / "att.out")
    r2 = run_cli(
        [
            "run",
            "--config",
            other_cfg,
            "--name",
            "data.txt",
            "--",
            sys.executable,
            "-c",
            f"import os; open({outfile!r},'wb').write(open(os.environ['KPIN_FILE'],'rb').read())",
        ]
    )
    assert r2["rc"] == 0
    assert open(outfile, "rb").read() == payload
