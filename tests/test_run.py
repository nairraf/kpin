import json
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


def _probe_env(cfg, outfile, checks, clean=False):
    expr = ", ".join(checks)
    args = ["run", "--config", cfg]
    if clean:
        args.append("--clean-env")
    args += [
        "--",
        sys.executable,
        "-c",
        f"import os; open({outfile!r},'w').write('|'.join([{expr}]))",
    ]
    return run_cli(args)


def _env_check(name, expected):
    return f"'1' if os.environ.get({name!r}) == {expected!r} else '0'"


def _env_absent(name):
    return f"'1' if os.environ.get({name!r}) is None else '0'"


def _env_present(name):
    return f"'1' if os.environ.get({name!r}) else '0'"


def test_run_clean_env_drops_parent_vars(isolated_env, mock_vault, monkeypatch):
    monkeypatch.setenv("PARENT_LEAK", "leaky")
    cfg = str(mock_vault["home"] / "cfg.json")
    outfile = str(mock_vault["home"] / "clean1.out")
    r = _probe_env(
        cfg,
        outfile,
        [
            _env_absent("PARENT_LEAK"),
            _env_check("MOCK_SECRET", "MOCK_VAL"),
            _env_present("PATH"),
            _env_present("HOME"),
        ],
        clean=True,
    )
    assert r["rc"] == 0
    assert open(outfile).read() == "1|1|1|1"


def test_run_clean_env_injects_secrets(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    outfile = str(mock_vault["home"] / "clean2.out")
    r = _probe_env(
        cfg,
        outfile,
        [
            _env_check("MOCK_SECRET", "MOCK_VAL"),
            _env_check("MOCK_TOKEN", "tok-12345"),
            _env_check("MOCK_EMPTY", ""),
        ],
        clean=True,
    )
    assert r["rc"] == 0
    assert open(outfile).read() == "1|1|1"


def test_run_clean_env_keeps_path_and_home(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    outfile = str(mock_vault["home"] / "clean3.out")
    r = _probe_env(
        cfg,
        outfile,
        [_env_present("PATH"), _env_present("HOME")],
        clean=True,
    )
    assert r["rc"] == 0
    assert open(outfile).read() == "1|1"


def test_run_default_inherits_parent_vars(isolated_env, mock_vault, monkeypatch):
    monkeypatch.setenv("PARENT_LEAK", "leaky")
    cfg = str(mock_vault["home"] / "cfg.json")
    outfile = str(mock_vault["home"] / "inherit.out")
    r = _probe_env(
        cfg,
        outfile,
        [_env_check("PARENT_LEAK", "leaky")],
    )
    assert r["rc"] == 0
    assert open(outfile).read() == "1"


def test_run_clean_env_composes_with_password_and_name(
    isolated_env, mock_vault, monkeypatch
):
    monkeypatch.setenv("PARENT_LEAK", "leaky")
    cfg = str(mock_vault["home"] / "cfg.json")
    outfile = str(mock_vault["home"] / "compose.out")
    r = run_cli(
        [
            "run",
            "--config",
            cfg,
            "--clean-env",
            "--password",
            "--name",
            mock_vault["att_name"],
            "--",
            sys.executable,
            "-c",
            f"import os; open({outfile!r},'w').write('|'.join(["
            + _env_absent("PARENT_LEAK")
            + ","
            + _env_check("KPIN_PASSWORD", "placeholder")
            + ","
            + _env_present("KPIN_FILE")
            + ","
            + _env_check("MOCK_SECRET", "MOCK_VAL")
            + "]))",
        ]
    )
    assert r["rc"] == 0
    assert open(outfile).read() == "1|1|1|1"


def test_run_clean_env_keeps_toolchain_vars(isolated_env, mock_vault, monkeypatch):
    monkeypatch.setenv("ANDROID_HOME", "/opt/android-sdk")
    monkeypatch.setenv("JAVA_HOME", "/usr/lib/jvm/java-17")
    monkeypatch.setenv("GRADLE_USER_HOME", "/tmp/gradle-home")
    cfg = str(mock_vault["home"] / "cfg.json")
    outfile = str(mock_vault["home"] / "toolchain.out")
    r = _probe_env(
        cfg,
        outfile,
        [
            _env_check("ANDROID_HOME", "/opt/android-sdk"),
            _env_check("JAVA_HOME", "/usr/lib/jvm/java-17"),
            _env_check("GRADLE_USER_HOME", "/tmp/gradle-home"),
        ],
        clean=True,
    )
    assert r["rc"] == 0
    assert open(outfile).read() == "1|1|1"


def test_run_clean_env_global_extra(isolated_env, mock_vault, monkeypatch):
    monkeypatch.setenv("MY_GLOBAL_VAR", "gval")
    run_cli(["config", "clean_env_extra", "MY_GLOBAL_VAR"])
    cfg = str(mock_vault["home"] / "cfg.json")
    outfile = str(mock_vault["home"] / "gextra.out")
    r = _probe_env(
        cfg,
        outfile,
        [_env_check("MY_GLOBAL_VAR", "gval")],
        clean=True,
    )
    assert r["rc"] == 0
    assert open(outfile).read() == "1"


def test_run_clean_env_project_extra(isolated_env, mock_vault, monkeypatch):
    monkeypatch.setenv("MY_PROJECT_VAR", "pval")
    cfg = str(mock_vault["home"] / "cfg.json")
    data = json.loads(open(cfg).read())
    data["clean_env_extra"] = ["MY_PROJECT_VAR"]
    open(cfg, "w").write(json.dumps(data))
    outfile = str(mock_vault["home"] / "pextra.out")
    r = _probe_env(
        cfg,
        outfile,
        [_env_check("MY_PROJECT_VAR", "pval")],
        clean=True,
    )
    assert r["rc"] == 0
    assert open(outfile).read() == "1"


def test_run_clean_env_global_and_project_extra_union(
    isolated_env, mock_vault, monkeypatch
):
    monkeypatch.setenv("GLOBAL_ONLY", "g")
    monkeypatch.setenv("PROJECT_ONLY", "p")
    monkeypatch.setenv("BOTH", "b")
    run_cli(["config", "clean_env_extra", "GLOBAL_ONLY,BOTH"])
    cfg = str(mock_vault["home"] / "cfg.json")
    data = json.loads(open(cfg).read())
    data["clean_env_extra"] = ["PROJECT_ONLY", "BOTH"]
    open(cfg, "w").write(json.dumps(data))
    outfile = str(mock_vault["home"] / "union.out")
    r = _probe_env(
        cfg,
        outfile,
        [
            _env_check("GLOBAL_ONLY", "g"),
            _env_check("PROJECT_ONLY", "p"),
            _env_check("BOTH", "b"),
        ],
        clean=True,
    )
    assert r["rc"] == 0
    assert open(outfile).read() == "1|1|1"


def test_run_clean_env_env_override(isolated_env, mock_vault, monkeypatch):
    monkeypatch.setenv("MY_ENV_VAR", "eval")
    monkeypatch.setenv("KPIN_CLEAN_ENV_EXTRA", "MY_ENV_VAR")
    cfg = str(mock_vault["home"] / "cfg.json")
    outfile = str(mock_vault["home"] / "envoverride.out")
    r = _probe_env(
        cfg,
        outfile,
        [_env_check("MY_ENV_VAR", "eval")],
        clean=True,
    )
    assert r["rc"] == 0
    assert open(outfile).read() == "1"


def test_run_clean_env_all_sources_union(isolated_env, mock_vault, monkeypatch):
    monkeypatch.setenv("GLOBAL_VAR", "g")
    monkeypatch.setenv("PROJECT_VAR", "p")
    monkeypatch.setenv("ENV_VAR", "e")
    monkeypatch.setenv("KPIN_CLEAN_ENV_EXTRA", "ENV_VAR")
    run_cli(["config", "clean_env_extra", "GLOBAL_VAR"])
    cfg = str(mock_vault["home"] / "cfg.json")
    data = json.loads(open(cfg).read())
    data["clean_env_extra"] = ["PROJECT_VAR"]
    open(cfg, "w").write(json.dumps(data))
    outfile = str(mock_vault["home"] / "allsources.out")
    r = _probe_env(
        cfg,
        outfile,
        [
            _env_check("GLOBAL_VAR", "g"),
            _env_check("PROJECT_VAR", "p"),
            _env_check("ENV_VAR", "e"),
        ],
        clean=True,
    )
    assert r["rc"] == 0
    assert open(outfile).read() == "1|1|1"


def test_run_attach_multi_materializes_and_cleans_up(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    outfile = str(mock_vault["home"] / "attach.out")
    r = run_cli(
        [
            "run",
            "--config",
            cfg,
            "--attach",
            f"{mock_vault['att_name']}:KPIN_JSON",
            "--attach",
            f"{mock_vault['att_name2']}:KPIN_PEM",
            "--",
            sys.executable,
            "-c",
            f"import os; "
            f"open({outfile!r}+'.j','wb').write(open(os.environ['KPIN_JSON'],'rb').read()); "
            f"open({outfile!r}+'.p','wb').write(open(os.environ['KPIN_PEM'],'rb').read()); "
            f"open({outfile!r}+'.ex','w').write('1' if os.path.exists(os.environ['KPIN_JSON']) else '0')",
        ]
    )
    assert r["rc"] == 0
    assert open(outfile + ".j", "rb").read() == mock_vault["att_bytes"]
    assert open(outfile + ".p", "rb").read() == mock_vault["att_bytes2"]
    assert open(outfile + ".ex").read() == "1"
    assert not list(Path(tempfile.gettempdir()).glob("kpin-*"))


def test_run_attach_with_name_both_set(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    outfile = str(mock_vault["home"] / "attach_name.out")
    r = run_cli(
        [
            "run",
            "--config",
            cfg,
            "--name",
            mock_vault["att_name"],
            "--attach",
            f"{mock_vault['att_name2']}:KPIN_PEM",
            "--",
            sys.executable,
            "-c",
            f"import os; open({outfile!r},'w').write('|'.join(["
            f"'1' if os.environ.get('KPIN_FILE') else '0',"
            f"'1' if os.environ.get('KPIN_PEM') else '0']))",
        ]
    )
    assert r["rc"] == 0
    assert open(outfile).read() == "1|1"
    assert not list(Path(tempfile.gettempdir()).glob("kpin-*"))


def test_run_attach_keep_persists_temp_files(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    outfile = str(mock_vault["home"] / "attach_keep.out")
    r = run_cli(
        [
            "run",
            "--config",
            cfg,
            "--attach",
            f"{mock_vault['att_name']}:KPIN_JSON",
            "--keep",
            "--",
            sys.executable,
            "-c",
            f"import os; open({outfile!r},'w').write(os.environ['KPIN_JSON'])",
        ]
    )
    assert r["rc"] == 0
    kept = open(outfile).read().strip()
    assert kept.startswith("/tmp/kpin-")
    assert Path(kept).exists()
    assert Path(kept).read_bytes() == mock_vault["att_bytes"]
    os.unlink(kept)


def test_run_attach_invalid_specs(isolated_env, mock_vault, monkeypatch):
    cfg = str(mock_vault["home"] / "cfg.json")
    bad_specs = [
        "no-colon",
        "a:b:c",
        ":VAR",
        "name:",
        "name:1BAD",
    ]
    for spec in bad_specs:
        r = run_cli(["run", "--config", cfg, "--attach", spec, "--", "echo", "hi"])
        assert r["rc"] == 1, spec
        assert "--attach" in r["err"], spec


def test_run_attach_duplicate_var_rejected(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(
        [
            "run",
            "--config",
            cfg,
            "--attach",
            f"{mock_vault['att_name']}:KPIN_X",
            "--attach",
            f"{mock_vault['att_name2']}:KPIN_X",
            "--",
            "echo",
            "hi",
        ]
    )
    assert r["rc"] == 1
    assert "Duplicate env var" in r["err"]


def test_run_attach_with_output_rejected(isolated_env, mock_vault):
    cfg = str(mock_vault["home"] / "cfg.json")
    r = run_cli(
        [
            "run",
            "--config",
            cfg,
            "--attach",
            f"{mock_vault['att_name']}:KPIN_JSON",
            "--output",
            str(mock_vault["home"] / "out"),
            "--",
            "echo",
            "hi",
        ]
    )
    assert r["rc"] == 1
    assert "--output" in r["err"]


def test_run_attach_composes_with_clean_env(isolated_env, mock_vault, monkeypatch):
    monkeypatch.setenv("PARENT_LEAK", "leaky")
    cfg = str(mock_vault["home"] / "cfg.json")
    outfile = str(mock_vault["home"] / "attach_clean.out")
    r = run_cli(
        [
            "run",
            "--config",
            cfg,
            "--clean-env",
            "--attach",
            f"{mock_vault['att_name']}:KPIN_JSON",
            "--",
            sys.executable,
            "-c",
            f"import os; open({outfile!r},'w').write('|'.join(["
            f"'1' if os.environ.get('PARENT_LEAK') is None else '0',"
            f"'1' if os.environ.get('KPIN_JSON') else '0',"
            f"'1' if os.environ.get('MOCK_SECRET') == 'MOCK_VAL' else '0']))",
        ]
    )
    assert r["rc"] == 0
    assert open(outfile).read() == "1|1|1"
