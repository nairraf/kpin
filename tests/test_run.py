import os
import sys
import tempfile
from pathlib import Path

from tests.helpers import run_cli


def _probe(config_path, outfile):
    return run_cli(
        [
            "run",
            "--config",
            config_path,
            "--",
            sys.executable,
            "-c",
            f"import os; open({outfile!r},'w').write("
            "os.environ.get('MOCK_SECRET','__NONE__') + '|' + "
            "os.environ.get('MOCK_TOKEN','__NONE__') + '|' + "
            "('1' if os.environ.get('MOCK_EMPTY') == '' else '0'))",
        ]
    )


def test_run_injects_env_and_prints_nothing_about_secrets(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    outfile = str(mock_vault["home"] / "probe.out")
    r = _probe(cfg, outfile)
    assert r["rc"] == 0
    assert open(outfile).read() == "MOCK_VAL|tok-12345|1"
    assert "MOCK_VAL" not in r["err"]
    assert "MOCK_TOKEN" not in r["err"]


def test_run_strips_double_dash(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    outfile = str(mock_vault["home"] / "probe2.out")
    r = _probe(cfg, outfile)
    assert r["rc"] == 0


def test_run_with_attachment_temp_cleans_up(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    outfile = str(mock_vault["home"] / "mat.out")
    r = run_cli(
        [
            "run",
            "--config",
            cfg,
            "--name",
            mock_vault["att_name"],
            "--",
            sys.executable,
            "-c",
            f"import os; p=os.environ['KPIN_FILE']; "
            f"open({outfile!r},'wb').write(open(p,'rb').read()); "
            f"open({outfile!r}+'.ex', 'w').write('1' if os.path.exists(p) else '0')",
        ]
    )
    assert r["rc"] == 0
    assert open(outfile, "rb").read() == mock_vault["att_bytes"]
    assert open(outfile + ".ex").read() == "1"
    assert not list(Path(tempfile.gettempdir()).glob("kpin-*"))


def test_run_with_attachment_output_dir_keeps_file(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    out_dir = mock_vault["home"] / "out"
    r = run_cli(
        [
            "run",
            "--config",
            cfg,
            "--name",
            mock_vault["att_name"],
            "--output",
            str(out_dir),
            "--keep",
            "--",
            sys.executable,
            "-c",
            "pass",
        ]
    )
    assert r["rc"] == 0
    written = out_dir / mock_vault["att_name"]
    assert written.read_bytes() == mock_vault["att_bytes"]


def test_run_propagates_child_exit_code(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(
        ["run", "--config", cfg, "--", sys.executable, "-c", "import sys; sys.exit(7)"]
    )
    assert r["rc"] == 7
