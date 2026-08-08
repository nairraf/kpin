# kpin

Inject secrets from a KeePassXC vault into dev commands — without printing them to stdout.

`kpin` gives you a KeePassXC-backed vault per project, and injects secrets into a child process environment (or materializes a binary attachment to a file) so values never land in shell history, logs, or an agent's context.

## The problem

Every project ends up reinventing secret management. Keys end up in `.env` files that get committed by accident, in shell history, in notes apps, or pasted into chat. When a teammate joins or a machine is rebuilt, there's no single source of truth — just a scramble to reconstruct what's set where.

The tools that exist take two shapes, and both miss the mark for day-to-day dev work:

- **Env-var-only injectors** (kprun, `op run`) inject variables but can't handle *files* — Android keystores, certificates, Firebase configs. You still have to keep those somewhere.
- **Git/file-centric tools** (SOPS, age) encrypt files in the repo but don't inject anything at runtime. Values land in plaintext the moment a process reads them.

`kpin` is built around the cases that actually come up in dev:

- secrets **and** binary files, from one place
- injected into a single child process, never printed
- per-project isolation that is structural, not a convention

## The mental model

Three ideas make kpin easy to use without thinking.

**One vault per project, the keyfile is the key.** Each project gets its own KDBX database *and* its own keyfile. Project A literally cannot open project B's vault — there is no "isolation by convention" to trust or misconfigure. The keyfile never leaves your machine and is never synced.

**The default entry + attributes is the everyday case.** You store secrets as attributes on the vault's **default** entry. The attribute *name* becomes the environment variable name, so `API_KEY` stored as an attribute shows up as `$API_KEY` in your process. No entry names, no flags — you just set and run.

**Named entries are for environments and configs.** When the same project needs different secret sets — production vs. staging vs. test, or separate credentials for separate services — create one entry per environment and pick it at runtime with `--entry NAME`. Same code, same commands, different secrets. Attachments (files) work the same way per entry.

## Install

```bash
git clone https://github.com/nairraf/kpin.git ~/development/kpin
cd ~/development/kpin
uv tool install --editable .   # puts `kpin` on PATH
kpin --version
```

Requires a KeePassXC-compatible KDBX vault. KeePassXC is optional (needed for `kpin init` and GUI editing):
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
kpin list attributes             # list attribute names (no values)
```

## Environments with named entries

When the same project needs different secret sets, create one entry per environment and switch at runtime. The example below uses prod/qa, but the pattern covers any split — staging, test configs, separate service credentials.

```bash
kpin entry add prod
kpin entry add qa

# set the same attribute on each environment
kpin set attribute API_KEY --stdin --entry prod
kpin set attribute API_KEY --stdin --entry qa
kpin set attribute DB_URL --stdin --entry prod
kpin set attribute DB_URL --stdin --entry qa

# pick the environment at runtime — same code, different secrets
kpin run --entry prod -- ./deploy.sh
kpin run --entry qa   -- ./deploy.sh
```

Omit `--entry` and commands target the **default** entry. Everything works per entry — attributes, passwords, and attachments:

```bash
kpin entry add "AI Providers"
kpin set attribute openai_token --stdin --entry "AI Providers"
kpin get attribute openai_token --entry "AI Providers"

kpin entry add "API Keys"
kpin set password --stdin --entry "API Keys"   # set the password field
kpin get password --entry "API Keys"
kpin get password                            # no --entry = default entry
```

## Files & attachments (certificates, keystores, configs)

Some secrets aren't strings — they're files that have to exist on disk. Attachments are referenced by their exact stored filename:

```bash
kpin set attachment server.pem --entry "AI Providers"
kpin list attachments --entry "AI Providers"         # list attachment names
kpin get attachment --name server.pem --output ./certs   # extract, keeps the name
kpin run --name server.pem --entry "AI Providers" -- ./start.sh   # temp file as $KPIN_FILE, auto-cleanup
```

`kpin run --name FILE` materializes the attachment to a temp file, sets `$KPIN_FILE` in the child env, and deletes the file when the child exits (unless `--keep`). Extracted files are written owner-only (`0600`).

## Commands

Every secret access is explicit about **type**, **entry**, and (for attachments) **which file + where it lands**. `--entry NAME` selects an entry by title; omitted → the default entry.

| Command | Description |
|---|---|
| `kpin init [--project NAME]` | Create a project vault (keyfile-only) + local `.kpin` |
| `kpin config [KEY [VALUE]]` / `--unset` / `show` / `--local` | Manage settings: global (`vault_dir`, `key_dir`, `clean_env_extra`) or per-project (`--local clean_env_extra`) |
| `kpin status` | Show the active vault |
| `kpin entry add TITLE` | Create a new entry |
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
| `kpin run [--clean-env] [--entry NAME] [--name FILE] [--output DIR\|PATH] [--keep] [--password] [--] CMD...` | Inject attributes into CMD's env; `--name` also materializes that attachment as `$KPIN_FILE` (auto-deleted unless `--keep`); `--password` also injects the entry password as `$KPIN_PASSWORD`; `--clean-env` starts the child from a minimal env instead of inheriting |
| `kpin validate [KEY...] [--entry NAME]` | Check required attributes are present |

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

## Settings

`kpin config` manages settings (git-config style). Most settings are **global** in `~/.config/kpin/config.json`; `clean_env_extra` can also be **per-project** in the local `.kpin`.

```bash
kpin config vault_dir ~/.kpin   # where vaults (.kdbx) live (global)
kpin config key_dir ~/.keys     # where keyfiles (.key) live — keep separate from vaults (global)
kpin config show                # show all global settings
kpin config --unset key_dir     # remove a setting (falls back to default)
```

Vaults and keyfiles are kept in separate directories by default so a synced vault directory never carries the keyfiles that unlock it.

## Clean environments (`run --clean-env`)

By default `kpin run` inherits your shell's environment and layers the vault secrets on top. If the parent environment is dirty — a stale `kpin env` export, a leaked secret, a leftover variable — the child sees it, which silently defeats kpin's isolation promise.

`kpin run --clean-env` starts the child from a **minimal, predictable environment** instead:

- **Always kept:** `PATH`, `HOME`, locale (`LANG`/`LC_ALL`/`LC_CTYPE`), `TMPDIR`, `TERM`.
- **Toolchain vars kept if set:** `ANDROID_HOME`, `ANDROID_SDK_ROOT`, `ANDROID_USER_HOME`, `ANDROID_NDK_HOME`, `NDK_HOME`, `JAVA_HOME`, `JAVA_TOOL_OPTIONS`, `GRADLE_HOME`, `GRADLE_USER_HOME`, `PUB_CACHE`, `CHROME_EXECUTABLE` — so Android/Flutter/Java builds work out of the box.
- **Vault secrets** (and `$KPIN_PASSWORD`/`$KPIN_FILE` when requested) are always injected.
- **Everything else from the parent is dropped.**

### Extending the allowlist

If a build needs a variable that isn't in the list, add it at the scope that fits:

```bash
# global — applies to every project (good if you mostly do one kind of dev)
kpin config clean_env_extra "MY_TOOL_VAR,OTHER_VAR"

# per-project — applies only to this project's .kpin (good for multi-language work)
kpin config --local clean_env_extra "MY_TOOL_VAR,OTHER_VAR"

# per-invocation — one-off, no file changes
KPIN_CLEAN_ENV_EXTRA=MY_TOOL_VAR kpin run --clean-env -- ./build.sh
```

The effective allowlist is the union of the built-in list, the global setting, the project's `.kpin`, and the `KPIN_CLEAN_ENV_EXTRA` env var. `--local` targets the `.kpin` walked up from your current directory (run `kpin init` there first); `kpin config --config PATH clean_env_extra ...` targets a specific `.kpin` when you're not in the directory. `vault_dir` and `key_dir` are global-only — they're machine settings, not project settings.

## Security notes

- Keyfile-only vaults: the keyfile **is** the secret. Never sync `~/.keys/*.key` to the cloud.
- `kpin get`/`kpin env` print values to stdout — intended for humans or explicit piping, not agents.
- `kpin run` prints nothing about the secrets; the child inherits them in env only.
- `kpin run --name FILE` cleans up the temp file after the child exits (unless `--keep`).
- Extracted attachments (`--output`) are written with `0600` permissions (owner-only).
- `kpin get attachment` without `--output` refuses to write binary to an interactive terminal — pipe it or use `--output`.
- `kpin run --password` injects the entry password as `$KPIN_PASSWORD` — opt-in only; it exposes the password to the child process, so use it knowingly.
- `kpin run --clean-env` drops the parent environment (except the documented allowlist) so a dirty shell can't leak secrets into the child. Every variable you add to `clean_env_extra` is a potential leak surface — keep the list tight.

## License

MIT
