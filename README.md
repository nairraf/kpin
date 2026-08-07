# kpin

Inject secrets from a KeePassXC vault into dev commands — without printing them to stdout.

`kpin` gives you a KeePassXC-backed vault per project, and injects secrets into a child process environment (or materializes a binary attachment to a temp file) so values never land in shell history, logs, or an agent's context.

## Why

- **Env-var-only tools (kprun, op run) can't do attachments or temp files.** `kpin run` injects env vars, and `kpin materialize` exports a binary attachment (e.g. Android keystore, Firebase config) to a temp file that is deleted afterward. This covers the cases the others miss.
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
kpin init                # creates ~/.kpin/<project>.kdbx + keyfile + local .kpin
kpin set API_KEY --stdin # or: kpin set API_KEY 'value'
kpin run -- node app.js  # injects API_KEY into the child env only

# Binary attachment (e.g. Android keystore)
kpin attach debug.keystore
kpin materialize -- gradlew assembleDebug   # writes temp file, sets $KPIN_FILE, runs, deletes
```

## Commands

| Command | Description |
|---|---|
| `kpin init [--project NAME]` | Create a project vault (keyfile-only) + local `.kpin` |
| `kpin status` | Show the active vault |
| `kpin set KEY [VALUE]` / `--stdin` | Set a secret on the entry |
| `kpin attach FILE` | Attach a binary file to the entry |
| `kpin get KEY` | Print a secret (reveals it — use deliberately) |
| `kpin env` | Print all secrets as `KEY=value` |
| `kpin run [--] CMD...` | Run a command with secrets injected as env vars |
| `kpin materialize [--] [CMD...]` | Write the attachment to a temp file, export it as `$KPIN_FILE`, run CMD, delete it |
| `kpin validate [KEY...]` | Check required secrets are present |

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
  "keyfile": "~/.kpin/my-project.key",
  "entry": "default"
}
```

Use `--project NAME` from anywhere (falls back to the registry).

## Security notes

- Keyfile-only vaults: the keyfile **is** the secret. Never sync `~/.kpin/*.key` to the cloud.
- `kpin get`/`kpin env` print values to stdout — intended for humans or explicit piping, not agents.
- `kpin run` prints nothing about the secrets; the child inherits them in env only.
- `kpin materialize` cleans up the temp file in a `finally` block.

## License

MIT
