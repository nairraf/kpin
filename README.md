# kpin

Inject secrets from a KeePassXC vault into dev commands — without printing them to stdout.

`kpin` gives you a KeePassXC-backed vault per project, and injects secrets into a child process environment (or materializes a binary attachment to a file) so values never land in shell history, logs, or an agent's context.

## Why

- **Env-var-only tools (kprun, op run) can't do attachments or files.** `kpin run` injects env vars and can also materialize a named binary attachment (e.g. Android keystore, certificate) to a temp file or a directory of your choice. This covers the cases the others miss.
- **One database = one trust boundary.** Each project has its own vault + keyfile, so project A cannot read project B. No per-entry permissions needed.
- **Cross-platform.** Pure-Python stdlib + `pykeepass` + `keepassxc-cli` (optional). Works on Linux, macOS, Windows.

## Install

```bash
git clone https://github.com/nairraf/kpin.git ~/development/kpin
cd ~/development/kpin
uv tool install --editable .   # puts `kpin` on PATH
kpin --version
```

Requires a KeePassXC-compatible KDBX vault. Install KeePassXC (optional, for `kpin init` and GUI editing):
- Linux: `sudo apt install keepassxc` / `dnf install keepassxc`
- macOS: `brew install --cask keepassxc`
- Windows: download from https://keepassxc.org

## Quick start — the easy way

Attributes are stored on the vault's **default entry**, so you usually don't need to think about entries at all:

```bash
cd my-project
kpin init                        # creates vault + keyfile + local .kpin pointer
kpin set attribute API_KEY --stdin   # paste your key (avoids shell history)
kpin run -- node app.js          # injects API_KEY into the child env only
```

That's it. No entry flags needed. To check what you have or reveal a value:

```bash
kpin env                         # list all attributes as KEY=value
kpin validate API_KEY DB_URL     # exit 1 if any are missing
kpin get attribute API_KEY       # reveal one value (human/pipe only)
```

## Using named entries

Every secret can also target a specific entry. Create one, then reference it with `--entry NAME`; omit `--entry` and it goes to the default entry.

```bash
kpin entry add "AI Providers"          # create an entry
kpin set attribute openai_token --stdin --entry "AI Providers"
kpin get attribute openai_token --entry "AI Providers"

kpin entry add "API Keys"
kpin set password --stdin --entry "API Keys"   # set the password field
kpin get password --entry "API Keys"
kpin get password                            # no --entry = default entry
```

## Binary attachments (certificates, keystores, configs)

Attachments are referenced by their exact stored filename:

```bash
kpin set attachment server.pem --entry "AI Providers"
kpin list attachments --entry "AI Providers"         # list attachment names
kpin get attachment --name server.pem --output ./certs   # extract, keeps the name
kpin run --name server.pem --entry "AI Providers" -- ./start.sh   # temp file as $KPIN_FILE, auto-cleanup
```

## Commands

Every secret access is explicit about **type**, **entry**, and (for attachments) **which file + where it lands**. `--entry NAME` selects an entry by title; omitted → the default entry.

| Command | Description |
|---|---|
| `kpin init [--project NAME]` | Create a project vault (keyfile-only) + local `.kpin` |
| `kpin config [KEY [VALUE]]` / `--unset` / `show` | Manage global settings (`vault_dir`, `key_dir`) |
| `kpin status` | Show the active vault |
| `kpin entry TITLE` | Create a new entry |
| `kpin list entries` | List entry titles |
| `kpin list attributes [--entry NAME]` | List attribute names (no values) |
| `kpin list attachments [--entry NAME]` | List attachment filenames |
| `kpin set password [VALUE\|--stdin] [--entry NAME]` | Set an entry's password field |
| `kpin set attribute KEY [VALUE\|--stdin] [--entry NAME]` | Set an attribute (custom property) |
| `kpin set attachment FILE [--entry NAME]` | Attach a binary file (stored under its filename) |
| `kpin get password [--entry NAME]` | Reveal an entry's password |
| `kpin get attribute KEY [--entry NAME]` | Reveal an attribute value |
| `kpin get attachment --name FILE [--output DIR\|PATH]` | Extract an attachment to a dir (keeps stored name) or exact path |
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
