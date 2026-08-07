# kpin

Inject secrets from a KeePassXC vault into dev commands — without printing them to stdout.

`kpin` gives you a KeePassXC-backed vault per project, and injects secrets into a child process environment (or materializes a binary attachment to a file) so values never land in shell history, logs, or an agent's context.

## Why

- **Env-var-only tools (kprun, op run) can't do attachments or files.** `kpin run` injects env vars and can also materialize a named binary attachment (e.g. Android keystore, certificate) to a temp file or a directory of your choice. This covers the cases the others miss.
- **One database = one trust boundary.** Each project has its own vault + keyfile, so project A cannot read project B. No per-entry permissions needed.
- **Cross-platform.** Pure-Python stdlib + `pykeepass` + `keepassxc-cli` (optional). Works on Linux, macOS, Windows.

## Install

```bash
git clone https://github.com/YOU/kpin.git ~/development/kpin
ln -s ~/development/kpin/bin/kpin ~/.local/bin/kpin
python3 -m pip install --user pykeepass
kpin --version
```

Requires a KeePassXC-compatible KDBX vault. Install KeePassXC (optional, for `kpin init` and GUI editing):
- Linux: `sudo apt install keepassxc` / `dnf install keepassxc`
- macOS: `brew install --cask keepassxc`
- Windows: download from https://keepassxc.org

## Quick start

```bash
cd my-project
kpin init                  # creates vault + keyfile + local .kpin pointer
kpin entry add "API Keys"  # create a named entry (default entry is 'default')
kpin set attribute API_KEY --stdin           # or: kpin set attribute API_KEY 'value'
kpin run -- node app.js    # injects attributes into the child env only

# Reveal secrets deliberately (human/pipe only — never agent automation)
kpin get attribute API_KEY                  # default entry
kpin get password --entry "API Keys"        # a specific entry's password
kpin get attribute openai_token --entry "AI Providers"

# Binary attachment (e.g. Android keystore, certificate)
kpin set attachment debug.keystore
kpin get attachment                 # list attachment names
kpin get attachment --name debug.keystore --output ./certs   # extract, keep name
kpin run --name debug.keystore -- gradlew assembleDebug      # temp file, $KPIN_FILE, auto-cleanup
```

## Commands

Every secret access is explicit about **type**, **entry**, and (for attachments) **which file + where it lands**. `--entry NAME` selects an entry by title; omitted → the configured entry (usually `default`).

| Command | Description |
|---|---|
| `kpin init [--project NAME]` | Create a project vault (keyfile-only) + local `.kpin` |
| `kpin config [KEY [VALUE]]` / `--unset` / `show` | Manage global settings (`vault_dir`, `key_dir`) |
| `kpin status` | Show the active vault |
| `kpin entry add TITLE` / `kpin entry list` | Create or list entries |
| `kpin set password [VALUE\|--stdin] [--entry NAME]` | Set an entry's password field |
| `kpin set attribute KEY [VALUE\|--stdin] [--entry NAME]` | Set an attribute (custom property) |
| `kpin set attachment FILE [--entry NAME]` | Attach a binary file (stored under its filename) |
| `kpin get password [--entry NAME]` | Reveal an entry's password |
| `kpin get attribute KEY [--entry NAME]` | Reveal an attribute value |
| `kpin get attachment [--entry NAME] [--name FILE] [--output DIR\|PATH]` | List attachment names, or extract one to a dir (keeps stored name) or exact path |
| `kpin env [--entry NAME]` | Print all attributes as `KEY=value` |
| `kpin run [--entry NAME] [--name FILE] [--output DIR\|PATH] [--keep] [--] CMD...` | Inject attributes into CMD's env; `--name` also materializes that attachment as `$KPIN_FILE` (auto-deleted unless `--keep`) |
| `kpin validate [KEY...]` | Check required attributes are present |

## Config resolution

`kpin` finds your vault in this order:

1. `--config <path>` flag
2. `$KPIN_CONFIG` env var
3. `.kpin` file found by walking up from the current directory
4. `~/.config/kpin/projects.json` keyed by project name (`--project NAME`)

The `.kpin` file is a machine-local pointer (paths only, no secrets) and should be gitignored:

```json
{
  "name": "my-project",
  "db": "~/.kpin/my-project.kdbx",
  "keyfile": "~/.keys/my-project.key",
  "entry": "default"
}
```

Use `--project NAME` from anywhere (falls back to the registry).

## Global settings

`kpin config` manages settings in `~/.config/kpin/config.json` (git-config style):

```bash
kpin config vault_dir ~/.kpin   # where vaults (.kdbx) live
kpin config key_dir ~/.keys     # where keyfiles (.key) live — keep separate from vaults
kpin config show                # show all settings
kpin config --unset key_dir     # remove a setting (falls back to default)
```

Vaults and keyfiles are kept in separate directories by default so a synced vault directory never carries the keyfiles that unlock it.

## Security notes

- Keyfile-only vaults: the keyfile **is** the secret. Never sync `~/.keys/*.key` to the cloud.
- `kpin get`/`kpin env` print values to stdout — intended for humans or explicit piping, not agents.
- `kpin run` prints nothing about the secrets; the child inherits them in env only.
- `kpin run --name FILE` cleans up the temp file after the child exits (unless `--keep`).

## License

MIT
