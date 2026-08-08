#!/usr/bin/env python3
"""kpin - inject secrets from a KeePassXC vault into dev commands.

Resolves a per-project vault (via a local `.kpin` file or a global registry),
then reads/decrypts secrets and injects them into a child process without
printing values to stdout.

Requires: Python 3.9+, pykeepass, keepassxc-cli (optional, for init).

Config resolution order:
  1. --config <path>
  2. $KPIN_CONFIG
  3. `.kpin` file found by walking up from CWD
  4. ~/.config/kpin/projects.json keyed by project name
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path

from . import __version__

LOCAL_FILE = ".kpin"

DEFAULT_SETTINGS = {
    "vault_dir": "~/.kpin",
    "key_dir": "~/.keys",
    "clean_env_extra": "",
}

SETTING_KEYS = tuple(DEFAULT_SETTINGS) + ("clean_env_extra",)

# `run --clean-env` allowlist. Core vars every child needs; toolchain vars
# are kept if set so Android/Flutter/Java builds work out of the box.
CLEAN_ENV_CORE = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TERM")
CLEAN_ENV_TOOLCHAIN = (
    "ANDROID_HOME",
    "ANDROID_SDK_ROOT",
    "ANDROID_USER_HOME",
    "ANDROID_NDK_HOME",
    "NDK_HOME",
    "JAVA_HOME",
    "JAVA_TOOL_OPTIONS",
    "GRADLE_HOME",
    "GRADLE_USER_HOME",
    "PUB_CACHE",
    "CHROME_EXECUTABLE",
)


class KpinError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    db: Path
    keyfile: Path
    entry: str
    clean_env_extra: tuple[str, ...] = ()


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "kpin"


def registry_file() -> Path:
    return config_dir() / "projects.json"


def config_file() -> Path:
    return config_dir() / "config.json"


def _registry() -> dict:
    path = registry_file()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise KpinError(f"Invalid registry JSON: {path}")
    return {}


def _save_registry(data: dict) -> None:
    path = registry_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _settings() -> dict:
    path = config_file()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise KpinError(f"Invalid settings JSON: {path}")
        if not isinstance(data, dict):
            raise KpinError(f"Settings must be a JSON object: {path}")
        return data
    return {}


def _save_settings(data: dict) -> None:
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _setting(key: str) -> str:
    return str(_settings().get(key, DEFAULT_SETTINGS.get(key, "")))


def _confirm(prompt: str) -> bool:
    try:
        answer = input(prompt)
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def _find_local_file() -> Path | None:
    cur = Path.cwd()
    for parent in [cur, *cur.parents]:
        candidate = parent / LOCAL_FILE
        if candidate.is_file():
            return candidate
    return None


def resolve_config(project: str | None, config_path: str | None) -> ProjectConfig:
    if config_path:
        p = Path(config_path).expanduser()
        if not p.is_file():
            raise KpinError(f"Config file not found: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        name = data.get("name", "local")
        return _build(name, data)

    if os.environ.get("KPIN_CONFIG"):
        return resolve_config(None, os.environ["KPIN_CONFIG"])

    local = _find_local_file()
    if local:
        data = json.loads(local.read_text(encoding="utf-8"))
        return _build(data.get("name", local.parent.name), data)

    reg = _registry()
    if project:
        if project in reg:
            return _build(project, reg[project])
        raise KpinError(f"Project '{project}' not in registry {registry_file()}")

    raise KpinError(
        "No vault configured. Run 'kpin init' in this directory or provide --project."
    )


def _build(name: str, data: dict) -> ProjectConfig:
    db = Path(data.get("db", "")).expanduser()
    keyfile = Path(data.get("keyfile", "")).expanduser()
    entry = data.get("entry", "default")
    extra = _parse_extra(data.get("clean_env_extra"))
    return ProjectConfig(
        name=name, db=db, keyfile=keyfile, entry=entry, clean_env_extra=extra
    )


def _parse_extra(value) -> tuple[str, ...]:
    """Normalize a clean_env_extra value (list or comma-separated string)."""
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(v.strip() for v in value.split(",") if v.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(v).strip() for v in value if str(v).strip())
    raise KpinError("clean_env_extra must be a list or comma-separated string")


def _require(config: ProjectConfig) -> None:
    if not config.db.is_file():
        raise KpinError(f"Database not found: {config.db}")
    if not config.keyfile.is_file():
        raise KpinError(f"Keyfile not found: {config.keyfile}")


def _import_pykeepass() -> "module":
    try:
        from pykeepass import PyKeePass
    except ImportError:
        raise KpinError(
            "pykeepass is required. Install: pip install pykeepass"
        ) from None
    return PyKeePass


def _open(config: ProjectConfig):
    PyKeePass = _import_pykeepass()
    return PyKeePass(str(config.db), keyfile=str(config.keyfile))


def _entry(kp, config: ProjectConfig, entry_name: str | None = None):
    title = entry_name or config.entry
    entry = kp.find_entries(title=title, first=True)
    if entry is None:
        raise KpinError(f"Entry '{title}' not found in {config.db}")
    return entry


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_init(args) -> int:
    name = args.project or Path.cwd().name
    vault_dir = Path(_setting("vault_dir")).expanduser()
    key_dir = Path(_setting("key_dir")).expanduser()
    data = {
        "name": name,
        "db": str(vault_dir / f"{name}.kdbx"),
        "keyfile": str(key_dir / f"{name}.key"),
        "entry": "default",
    }
    db, keyfile = Path(data["db"]), Path(data["keyfile"])
    if db.exists() or keyfile.exists():
        print(f"Vault already exists for '{name}' at {db}", file=sys.stderr)
        return 1

    reg = _registry()
    if name in reg:
        existing = reg[name]
        print(
            f"Project '{name}' is already registered at {existing.get('db')}",
            file=sys.stderr,
        )
        if not _confirm(
            f"Reuse that vault for this directory instead of creating a new one? [y/N] "
        ):
            print(
                "Aborted. Use 'kpin init --project <unique-name>' to create a separate vault.",
                file=sys.stderr,
            )
            return 1
        local = Path.cwd() / LOCAL_FILE
        if not local.exists():
            local.write_text(json.dumps(existing, indent=2))
            print(f"Created {local}")
        print(f"Linked to existing vault: {existing.get('db')}")
        return 0

    db.parent.mkdir(parents=True, exist_ok=True)
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    keyfile.write_bytes(os.urandom(64))
    keyfile.chmod(0o600)

    from pykeepass import create_database

    kp = create_database(str(db), keyfile=str(keyfile))
    kp.database_name = name
    kp.add_entry(kp.root_group, data["entry"], username="kpin", password="placeholder")
    kp.save()

    reg[name] = data
    _save_registry(reg)

    local = Path.cwd() / LOCAL_FILE
    if not local.exists():
        local.write_text(json.dumps(data, indent=2))
        print(f"Created {local}")

    print(f"Created vault: {db}")
    print(f"Keyfile: {keyfile} (keep secret, never sync)")
    print(f"Entry: '{data['entry']}'")
    return 0


def _value_from_stdin(args) -> str | None:
    if getattr(args, "stdin", False):
        return sys.stdin.read().rstrip("\n")
    return getattr(args, "value", None)


def cmd_set(args) -> int:
    config = resolve_config(args.project, args.config)
    _require(config)
    kp = _open(config)
    entry = _entry(kp, config, args.entry)

    if args.kind == "password":
        value = _value_from_stdin(args)
        if value is None:
            print("Missing value (use --stdin or a value argument)", file=sys.stderr)
            return 1
        entry.password = value
        kp.save()
        print(f"Set password on '{entry.title}'")
        return 0

    if args.kind == "attribute":
        value = _value_from_stdin(args)
        if value is None:
            print("Missing value (use --stdin or a value argument)", file=sys.stderr)
            return 1
        entry.set_custom_property(args.key, value)
        kp.save()
        print(f"Set {args.key} on '{entry.title}'")
        return 0

    if args.kind == "attachment":
        path = Path(args.file).expanduser()
        if not path.is_file():
            raise KpinError(f"File not found: {path}")
        binary_id = kp.add_binary(path.read_bytes())
        entry.add_attachment(binary_id, path.name)
        kp.save()
        print(f"Attached {path.name} to '{entry.title}'")
        return 0

    print(f"Unknown set kind: {args.kind}", file=sys.stderr)
    return 1


def _get_attribute(config: ProjectConfig, key: str, entry_name: str | None) -> str:
    kp = _open(config)
    entry = _entry(kp, config, entry_name)
    value = entry.get_custom_property(key)
    if value is None:
        raise KpinError(f"Attribute '{key}' not found on entry '{entry.title}'")
    return value


def _attachment(config: ProjectConfig, name: str, entry_name: str | None):
    kp = _open(config)
    entry = _entry(kp, config, entry_name)
    for attachment in entry.attachments:
        if attachment.filename == name:
            return attachment
    raise KpinError(
        f"Attachment '{name}' not found on entry '{entry.title}'"
        f" (have: {', '.join(a.filename for a in entry.attachments) or 'none'})"
    )


def _output_path(output: str, filename: str) -> Path:
    out = Path(output).expanduser()
    if (
        out.is_dir()
        or str(out).endswith(os.sep)
        or (out.suffix == "" and not out.exists())
    ):
        out = out / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def cmd_get(args) -> int:
    config = resolve_config(args.project, args.config)
    _require(config)

    if args.kind == "password":
        kp = _open(config)
        entry = _entry(kp, config, args.entry)
        print(entry.password)
        return 0

    if args.kind == "attribute":
        print(_get_attribute(config, args.key, args.entry))
        return 0

    if args.kind == "attachment":
        attachment = _attachment(config, args.name, args.entry)
        data = attachment.binary
        if not args.output:
            if sys.stdout.isatty():
                raise KpinError(
                    "Refusing to write binary attachment to a terminal. "
                    "Use --output DIR|PATH or pipe to a file."
                )
            sys.stdout.buffer.write(data)
            return 0
        out = _output_path(args.output, attachment.filename)
        out.write_bytes(data)
        out.chmod(0o600)
        print(out)
        return 0

    print(f"Unknown get kind: {args.kind}", file=sys.stderr)
    return 1


def cmd_env(args) -> int:
    config = resolve_config(args.project, args.config)
    _require(config)
    kp = _open(config)
    entry = _entry(kp, config, args.entry)
    for prop in entry.custom_properties:
        value = entry.get_custom_property(prop)
        print(f"{prop}={value or ''}")
    return 0


def _clean_env(config: ProjectConfig) -> dict[str, str]:
    """Minimal child env for `run --clean-env`.

    Copies a fixed allowlist (core + toolchain vars) plus any user-configured
    extras (global `clean_env_extra` setting + per-project `clean_env_extra`),
    and drops everything else so nothing from the parent leaks into the child.
    """
    env: dict[str, str] = {}
    global_extra = _parse_extra(_settings().get("clean_env_extra"))
    env_extra = _parse_extra(os.environ.get("KPIN_CLEAN_ENV_EXTRA"))
    keys = (
        CLEAN_ENV_CORE
        + CLEAN_ENV_TOOLCHAIN
        + global_extra
        + config.clean_env_extra
        + env_extra
    )
    for key in keys:
        if key in os.environ:
            env[key] = os.environ[key]
    if "PATH" not in env:
        env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    return env


def _parse_attach(spec: str) -> tuple[str, str]:
    """Parse an --attach NAME:VAR spec.

    Returns (name, var). Raises KpinError with a clear message on bad input.
    """
    if ":" not in spec:
        raise KpinError(
            f"Invalid --attach '{spec}': expected NAME:VAR "
            "(attachment filename, colon, env var name)"
        )
    name, _, rest = spec.partition(":")
    if ":" in rest:
        raise KpinError(f"Invalid --attach '{spec}': too many ':' (expected NAME:VAR)")
    if not name:
        raise KpinError(f"Invalid --attach '{spec}': missing attachment name")
    if not rest:
        raise KpinError(f"Invalid --attach '{spec}': missing env var name")
    if not re.match(r"[A-Za-z_][A-Za-z0-9_]*$", rest):
        raise KpinError(
            f"Invalid --attach '{spec}': '{rest}' is not a valid env var name"
        )
    return name, rest


def _materialize(attachment) -> str:
    """Write an attachment to a 0600 temp file, returning its path."""
    with tempfile.NamedTemporaryFile(delete=False, prefix="kpin-") as fh:
        fh.write(attachment.binary)
        return fh.name


def cmd_run(args) -> int:
    config = resolve_config(args.project, args.config)
    _require(config)
    kp = _open(config)
    entry = _entry(kp, config, args.entry)
    command = _strip_sep(args.cmd)
    if not command:
        print("Missing command to run", file=sys.stderr)
        return 1

    if args.attach and args.output:
        print(
            "--output is not compatible with --attach "
            "(a single --output can't address multiple files); use --keep to persist temp files",
            file=sys.stderr,
        )
        return 1

    attaches = [_parse_attach(spec) for spec in args.attach or []]
    vars_seen: set[str] = set()
    if args.name:
        vars_seen.add("KPIN_FILE")
    for name, var in attaches:
        if var in vars_seen:
            raise KpinError(
                f"Duplicate env var '{var}' in --attach (would silently overwrite)"
            )
        vars_seen.add(var)

    env = _clean_env(config) if args.clean_env else dict(os.environ)
    for prop in entry.custom_properties:
        value = entry.get_custom_property(prop)
        env[prop] = value or ""
    if args.password:
        env["KPIN_PASSWORD"] = entry.password or ""

    temp_paths: list[str] = []
    try:
        if args.name:
            attachment = _attachment(config, args.name, args.entry)
            if args.output:
                out = _output_path(args.output, attachment.filename)
                out.write_bytes(attachment.binary)
                out.chmod(0o600)
                path = str(out)
            else:
                path = _materialize(attachment)
                temp_paths.append(path)
            env["KPIN_FILE"] = path
        for name, var in attaches:
            attachment = _attachment(config, name, args.entry)
            path = _materialize(attachment)
            temp_paths.append(path)
            env[var] = path

        return subprocess.call(command, env=env)
    finally:
        if not args.keep:
            for path in temp_paths:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass


def _strip_sep(command: list[str]) -> list[str]:
    if command and command[0] == "--":
        return command[1:]
    return command


def cmd_validate(args) -> int:
    config = resolve_config(args.project, args.config)
    _require(config)
    kp = _open(config)
    entry = _entry(kp, config, args.entry)
    names = args.keys or [p for p in entry.custom_properties]
    missing = [k for k in names if not entry.get_custom_property(k)]
    for k in names:
        ok = k not in missing
        print(f"{k}: {'present' if ok else 'missing'}")
    return 1 if missing else 0


def _is_git_repo(directory: Path) -> bool:
    r = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(directory),
        capture_output=True,
        text=True,
    )
    return r.returncode == 0 and r.stdout.strip() == "true"


def _git_ls_files(directory: Path) -> set[str]:
    r = subprocess.run(
        ["git", "ls-files"],
        cwd=str(directory),
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return set()
    return {line.strip() for line in r.stdout.splitlines()}


def _git_ignored(directory: Path, path: Path) -> bool:
    r = subprocess.run(
        ["git", "check-ignore", str(path)],
        cwd=str(directory),
        capture_output=True,
        text=True,
    )
    return r.returncode == 0


def cmd_scan(args) -> int:
    if args.scan_kind == "history":
        return cmd_scan_history(args)
    return cmd_scan_audit(args)


def cmd_scan_audit(args) -> int:
    config = resolve_config(args.project, args.config)
    results: list[tuple[str, str]] = []
    fail = 0

    if not config.db.is_file():
        results.append(("FAIL", f"vault database missing: {config.db}"))
        fail = 1
    else:
        results.append(("OK", f"vault database present: {config.db}"))

    if not config.keyfile.is_file():
        results.append(("FAIL", f"keyfile missing: {config.keyfile}"))
        fail = 1
    else:
        results.append(("OK", f"keyfile present: {config.keyfile}"))
        if os.name != "nt":
            mode = config.keyfile.stat().st_mode & 0o777
            if mode & 0o077:
                results.append(("WARN", f"keyfile perms {mode:03o} — should be 600"))
            else:
                results.append(("OK", f"keyfile perms {mode:03o} (600)"))

    local = _find_local_file()
    git_root = Path.cwd()
    if not _is_git_repo(git_root):
        if not args.silent:
            results.append(("SKIP", "not a git repo — skipping git checks"))
    else:
        tracked = _git_ls_files(git_root)
        if local and str(local.relative_to(git_root)) in tracked:
            results.append(("FAIL", f".kpin is tracked in git: {local}"))
            fail = 1
        elif local and _git_ignored(git_root, local):
            results.append(("OK", ".kpin is gitignored"))
        elif local:
            results.append(("WARN", ".kpin is neither tracked nor gitignored"))

        leaks = [f for f in tracked if f.endswith((".kdbx", ".key", ".keyx"))]
        if leaks:
            for f in leaks:
                results.append(("FAIL", f"vault/keyfile tracked in git: {f}"))
            fail = 1
        else:
            results.append(("OK", "no vault/keyfile files tracked"))

        env_tracked = [f for f in tracked if f == ".env" or f.startswith(".env.")]
        if env_tracked:
            for f in env_tracked:
                results.append(("FAIL", f".env-style file tracked in git: {f}"))
            fail = 1
        else:
            results.append(("OK", "no .env-style files tracked"))

    for status, message in results:
        print(f"{status}: {message}")
    return fail


def _history_files(shell: str | None) -> list[tuple[str, Path, str]]:
    home = Path.home()
    candidates = {
        "bash": [("bash", home / ".bash_history", "plain")],
        "zsh": [("zsh", home / ".zsh_history", "zsh_extended")],
        "fish": [("fish", home / ".local/share/fish/fish_history", "fish_yaml")],
    }
    if shell:
        return candidates[shell]
    return [entry for entries in candidates.values() for entry in entries]


def _read_history(path: Path, fmt: str) -> list[str]:
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    if fmt == "zsh_extended":
        result = []
        for line in lines:
            if ";" in line:
                line = line.split(";", 1)[1]
            result.append(line)
        return result
    if fmt == "fish_yaml":
        result = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- cmd:"):
                result.append(stripped[len("- cmd:") :].strip().strip("'").strip('"'))
        return result
    return lines


def _redact_kpin_history(lines: list[str]) -> tuple[int, list[str]]:
    import re

    hits = 0
    reports = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("kpin"):
            continue
        if "--stdin" in stripped:
            continue
        m = re.match(r"kpin\s+set\s+(attribute|password)\s+(\S+)\s+(.+)", stripped)
        if not m:
            m = re.match(r"kpin\s+set\s+(attribute|password)\s+(\S+)=(.+)", stripped)
        if m:
            hits += 1
            kind, key, _value = m.groups()
            reports.append(f"kpin set {kind} {key} ***")
    return hits, reports


def cmd_scan_history(args) -> int:
    fail = 0
    for shell, path, fmt in _history_files(args.shell):
        lines = _read_history(path, fmt)
        if not lines:
            print(f"OK: no history entries in {path}")
            continue
        hits, reports = _redact_kpin_history(lines)
        if hits:
            fail = 1
            for report in reports:
                print(f"WARN {path}: {report}")
        else:
            print(f"OK: no leaked kpin secrets in {path}")
    return fail


def cmd_list(args) -> int:
    config = resolve_config(args.project, args.config)
    _require(config)
    kp = _open(config)

    if args.kind == "entries":
        for entry in kp.entries:
            print(entry.title)
        return 0

    entry = _entry(kp, config, args.entry)

    if args.kind == "attributes":
        for prop in entry.custom_properties:
            print(prop)
        return 0

    if args.kind == "attachments":
        for attachment in entry.attachments:
            print(attachment.filename)
        return 0

    print(f"Unknown list kind: {args.kind}", file=sys.stderr)
    return 1


def cmd_entry(args) -> int:
    config = resolve_config(args.project, args.config)
    _require(config)
    kp = _open(config)

    if args.kind == "add":
        title = args.title
        if kp.find_entries(title=title, first=True) is not None:
            print(f"Entry '{title}' already exists", file=sys.stderr)
            return 1
        kp.add_entry(kp.root_group, title, username="", password="")
        kp.save()
        print(f"Created entry '{title}'")
        return 0

    print(f"Unknown entry kind: {args.kind}", file=sys.stderr)
    return 1


def _local_config_path() -> Path:
    local = _find_local_file()
    if local is None:
        raise KpinError(
            "No .kpin found in this directory tree. Run 'kpin init' here or use --config PATH."
        )
    return local


def _read_local_config(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise KpinError(f"Invalid .kpin JSON: {path}")
    if not isinstance(data, dict):
        raise KpinError(f".kpin must be a JSON object: {path}")
    return data


def _write_local_config(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def cmd_config(args) -> int:
    local = args.local or bool(args.config)
    if local:
        path = Path(args.config).expanduser() if args.config else _local_config_path()
        if args.config and not path.is_file():
            raise KpinError(f"Config file not found: {path}")
        data = _read_local_config(path)
        if args.unset:
            if args.unset in data:
                del data[args.unset]
                _write_local_config(path, data)
                print(f"Unset {args.unset}")
            else:
                print(f"Setting '{args.unset}' is not set", file=sys.stderr)
                return 1
            return 0
        if args.show or (args.key == "show" and args.value is None):
            value = data.get("clean_env_extra", "")
            print(f"clean_env_extra={','.join(_parse_extra(value))}")
            return 0
        if not args.key:
            return cmd_config(
                Namespace(
                    show=True,
                    unset=None,
                    key=None,
                    value=None,
                    local=args.local,
                    config=args.config,
                )
            )
        if args.key != "clean_env_extra":
            print(
                f"Setting '{args.key}' is global-only; only clean_env_extra is project-scoped",
                file=sys.stderr,
            )
            return 1
        if args.value:
            data["clean_env_extra"] = _parse_extra(args.value)
            _write_local_config(path, data)
            print(f"{args.key}={args.value}")
            return 0
        print(",".join(_parse_extra(data.get("clean_env_extra"))))
        return 0

    if args.unset:
        data = _settings()
        if args.unset in data:
            del data[args.unset]
            _save_settings(data)
            print(f"Unset {args.unset}")
        else:
            print(f"Setting '{args.unset}' is not set", file=sys.stderr)
            return 1
        return 0
    if args.show or (args.key == "show" and args.value is None):
        data = dict(DEFAULT_SETTINGS)
        data.update(_settings())
        for key in SETTING_KEYS:
            value = data[key]
            if key == "clean_env_extra":
                value = ",".join(_parse_extra(value))
            print(f"{key}={value}")
        return 0
    if not args.key:
        return cmd_config(
            Namespace(
                show=True,
                unset=None,
                key=None,
                value=None,
                local=False,
                config=None,
            )
        )
    if args.key not in SETTING_KEYS:
        print(
            f"Unknown setting '{args.key}'. Known: {', '.join(SETTING_KEYS)}",
            file=sys.stderr,
        )
        return 1
    if args.value:
        data = _settings()
        if args.key == "clean_env_extra":
            data[args.key] = _parse_extra(args.value)
        else:
            data[args.key] = args.value
        _save_settings(data)
        print(f"{args.key}={args.value}")
        return 0
    if args.key == "clean_env_extra":
        print(",".join(_parse_extra(_settings().get("clean_env_extra"))))
        return 0
    print(_setting(args.key))
    return 0


def cmd_status(args) -> int:
    config = resolve_config(args.project, args.config)
    _require(config)
    print(f"project: {config.name}")
    print(f"db:      {config.db}")
    print(f"keyfile: {config.keyfile}")
    print(f"entry:   {config.entry}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kpin", description=__doc__)
    parser.add_argument("--version", action="version", version=f"kpin {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p):
        p.add_argument("--project", help="project name (registry lookup)")
        p.add_argument("--config", help="path to a .kpin config file")

    p = sub.add_parser("init", help="create a new project vault")
    add_common(p)

    p = sub.add_parser("config", help="get/set/show settings (git-config style)")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.add_argument("--unset", metavar="KEY", help="remove a setting")
    p.add_argument("--show", action="store_true", help="show all settings")
    p.add_argument(
        "--local",
        action="store_true",
        help="target the project's .kpin (walked up from CWD) instead of global settings",
    )
    p.add_argument(
        "--config",
        metavar="PATH",
        help="target a specific .kpin file (project-scoped settings)",
    )

    p = sub.add_parser("status", help="show active vault")
    add_common(p)

    p = sub.add_parser("entry", help="manage vault entries")
    entry_kind = p.add_subparsers(dest="kind", required=True)

    ep = entry_kind.add_parser("add", help="create a new entry")
    add_common(ep)
    ep.add_argument("title", help="entry title")

    p = sub.add_parser("list", help="list entries, attributes, or attachments")
    list_kind = p.add_subparsers(dest="kind", required=True)

    lp = list_kind.add_parser("entries", help="list entry titles")
    add_common(lp)

    lp = list_kind.add_parser("attributes", help="list attribute names (no values)")
    add_common(lp)
    lp.add_argument("--entry", help="entry title (default: configured entry)")

    lp = list_kind.add_parser("attachments", help="list attachment filenames")
    add_common(lp)
    lp.add_argument("--entry", help="entry title (default: configured entry)")

    p = sub.add_parser("set", help="set a password, attribute, or attachment")
    set_kind = p.add_subparsers(dest="kind", required=True)

    sp = set_kind.add_parser("password", help="set the entry's password field")
    add_common(sp)
    sp.add_argument("value", nargs="?", help="new password")
    sp.add_argument("--entry", help="entry title (default: configured entry)")
    sp.add_argument("--stdin", action="store_true", help="read value from stdin")

    sp = set_kind.add_parser("attribute", help="set an attribute (custom property)")
    add_common(sp)
    sp.add_argument("key", help="attribute key")
    sp.add_argument("value", nargs="?", help="attribute value")
    sp.add_argument("--entry", help="entry title (default: configured entry)")
    sp.add_argument("--stdin", action="store_true", help="read value from stdin")

    sp = set_kind.add_parser("attachment", help="attach a binary file to the entry")
    add_common(sp)
    sp.add_argument("file", help="path to the file to attach")
    sp.add_argument("--entry", help="entry title (default: configured entry)")

    p = sub.add_parser("get", help="reveal a password, attribute, or attachment")
    get_kind = p.add_subparsers(dest="kind", required=True)

    sp = get_kind.add_parser("password", help="print the entry's password field")
    add_common(sp)
    sp.add_argument("--entry", help="entry title (default: configured entry)")

    sp = get_kind.add_parser("attribute", help="print an attribute value")
    add_common(sp)
    sp.add_argument("key", help="attribute key")
    sp.add_argument("--entry", help="entry title (default: configured entry)")

    sp = get_kind.add_parser("attachment", help="extract an attachment")
    add_common(sp)
    sp.add_argument("--entry", help="entry title (default: configured entry)")
    sp.add_argument(
        "--name",
        required=True,
        help="attachment filename (see 'kpin list attachments')",
    )
    sp.add_argument(
        "--output",
        help="write attachment here (dir keeps stored name, or exact path)",
    )

    p = sub.add_parser("env", help="print all attributes as KEY=value")
    add_common(p)
    p.add_argument("--entry", help="entry title (default: configured entry)")

    p = sub.add_parser("run", help="run a command with secrets injected")
    add_common(p)
    p.add_argument("--entry", help="entry title (default: configured entry)")
    p.add_argument(
        "--name",
        help="also materialize this attachment as $KPIN_FILE (exact stored filename)",
    )
    p.add_argument(
        "--attach",
        action="append",
        metavar="NAME:VAR",
        help="materialize attachment NAME and expose its path as $VAR (repeatable)",
    )
    p.add_argument(
        "--output",
        help="write the materialized attachment here (dir keeps stored name, or exact path)",
    )
    p.add_argument("--keep", action="store_true", help="keep the materialized file")
    p.add_argument(
        "--clean-env",
        action="store_true",
        help="start the child from a minimal env (PATH/HOME/locale/TMPDIR/TERM + injected secrets) instead of inheriting the parent",
    )
    p.add_argument(
        "--password",
        action="store_true",
        help="also inject the entry password as $KPIN_PASSWORD (opt-in; leaks it into the child env)",
    )
    p.add_argument("cmd", nargs=argparse.REMAINDER)

    p = sub.add_parser("validate", help="check required secrets are present")
    add_common(p)
    p.add_argument("--entry", help="entry title (default: configured entry)")
    p.add_argument("keys", nargs="*")

    p = sub.add_parser(
        "scan",
        help="audit the vault setup and shell history for secret sprawl",
    )
    scan_sub = p.add_subparsers(dest="scan_kind")
    audit = scan_sub.add_parser(
        "audit", help="check vault/keyfile/.kpin/git hygiene (default)"
    )
    audit.add_argument("--silent", action="store_true", help="suppress SKIP lines")
    audit.add_argument("--project", help="project name (registry lookup)")
    audit.add_argument("--config", help="path to a .kpin config file")
    hist = scan_sub.add_parser("history", help="check shell history for leaked values")
    hist.add_argument(
        "--shell", choices=["bash", "zsh", "fish"], help="restrict to one shell"
    )
    hist.add_argument("--project", help="project name (registry lookup)")
    hist.add_argument("--config", help="path to a .kpin config file")

    return parser


def dispatch(args) -> int:
    handlers = {
        "init": cmd_init,
        "config": cmd_config,
        "status": cmd_status,
        "entry": cmd_entry,
        "list": cmd_list,
        "set": cmd_set,
        "get": cmd_get,
        "env": cmd_env,
        "run": cmd_run,
        "validate": cmd_validate,
        "scan": cmd_scan,
    }
    return handlers[args.command](args)


def main() -> None:
    args = build_parser().parse_args()
    try:
        rc = dispatch(args)
    except KpinError as exc:
        print(f"kpin: {exc}", file=sys.stderr)
        rc = 1
    sys.exit(rc)


if __name__ == "__main__":
    main()
