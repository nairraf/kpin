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
}

SETTING_KEYS = tuple(DEFAULT_SETTINGS)


class KpinError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    db: Path
    keyfile: Path
    entry: str


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
    return ProjectConfig(name=name, db=db, keyfile=keyfile, entry=entry)


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


def cmd_run(args) -> int:
    config = resolve_config(args.project, args.config)
    _require(config)
    kp = _open(config)
    entry = _entry(kp, config, args.entry)
    command = _strip_sep(args.cmd)
    if not command:
        print("Missing command to run", file=sys.stderr)
        return 1

    env = dict(os.environ)
    for prop in entry.custom_properties:
        value = entry.get_custom_property(prop)
        env[prop] = value or ""
    if args.password:
        env["KPIN_PASSWORD"] = entry.password or ""

    if args.name:
        attachment = _attachment(config, args.name, args.entry)
        if args.output:
            out = _output_path(args.output, attachment.filename)
            out.write_bytes(attachment.binary)
            out.chmod(0o600)
            path = str(out)
        else:
            with tempfile.NamedTemporaryFile(delete=False, prefix="kpin-") as fh:
                fh.write(attachment.binary)
                path = fh.name
        env["KPIN_FILE"] = path
        try:
            return subprocess.call(command, env=env)
        finally:
            if not args.keep:
                os.unlink(path)

    return subprocess.call(command, env=env)


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

    title = args.title
    if kp.find_entries(title=title, first=True) is not None:
        print(f"Entry '{title}' already exists", file=sys.stderr)
        return 1
    kp.add_entry(kp.root_group, title, username="", password="")
    kp.save()
    print(f"Created entry '{title}'")
    return 0


def cmd_config(args) -> int:
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
            print(f"{key}={data[key]}")
        return 0
    if not args.key:
        return cmd_config(Namespace(show=True, unset=None, key=None, value=None))
    if args.key not in SETTING_KEYS:
        print(
            f"Unknown setting '{args.key}'. Known: {', '.join(SETTING_KEYS)}",
            file=sys.stderr,
        )
        return 1
    if args.value:
        data = _settings()
        data[args.key] = args.value
        _save_settings(data)
        print(f"{args.key}={args.value}")
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

    p = sub.add_parser("config", help="get/set/show global settings (git-config style)")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.add_argument("--unset", metavar="KEY", help="remove a setting")
    p.add_argument("--show", action="store_true", help="show all settings")

    p = sub.add_parser("status", help="show active vault")
    add_common(p)

    p = sub.add_parser("entry", help="create a new vault entry")
    add_common(p)
    p.add_argument("title", help="entry title")

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
        "--output",
        help="write the materialized attachment here (dir keeps stored name, or exact path)",
    )
    p.add_argument("--keep", action="store_true", help="keep the materialized file")
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
