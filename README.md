# 🔥 on-fire

[![skills.sh](https://skills.sh/b/gercektasarim/on-fire)](https://skills.sh/gercektasarim/on-fire)

Emergency backup — a "panic button". With a single command it:

- **Copies** your files (Desktop, Documents…) to Google Drive (never moves them)
- **Commits + pushes** every git project to a separate `on-fire/<timestamp>` branch
- Logs everything under `~/on-fire-logs/`

Goal: in a panic, type `/on-fire` (or just say "make an emergency backup") and
leave your environment safely.

## Installation

### skills.sh / agent skill (recommended)

```bash
# Install into a project
npx skills add gercektasarim/on-fire

# Install globally (available in all projects)
npx skills add gercektasarim/on-fire -g
```

This places the skill in your agent's skills directory (in Claude Code,
`~/.claude/skills/on-fire/`). The skill then auto-triggers on phrases like
"fire / emergency backup".

### Slash command (Claude Code, optional)

skills.sh distributes the skill; if you also want the `/on-fire` slash command:

```bash
mkdir -p ~/.claude/commands
cp commands/on-fire.md ~/.claude/commands/on-fire.md
```

or via the plugin marketplace:

```bash
/plugin marketplace add gercektasarim/on-fire
```

## Configuration

```bash
mkdir -p ~/.config/on-fire
cp config.example.json ~/.config/on-fire/config.json
# edit: backup_dirs, project_roots, rclone_remote / drive_folder, block_on_secrets
```

## Drive connection

Either of these is enough:

1. **rclone** (recommended, ideal for headless/Linux):
   ```bash
   rclone config        # create a Google Drive remote
   rclone listremotes
   ```
2. **Google Drive for Desktop**: if installed, the skill auto-detects the sync
   folder based on your OS.

## Usage

```
/on-fire              # full backup (if the slash command is installed)
/on-fire --dry-run    # change nothing, just show what would happen (do this first)
/on-fire --test       # alias for --dry-run
/on-fire --no-drive   # git only
/on-fire --no-git     # Drive only
```

It also works in natural language: "back up everything and leave", "make an
emergency backup".

### Testing without deleting anything

`--dry-run` (aliases `--test`, `--simulate`) is completely safe: it detects
targets and prints exactly what *would* happen without copying, committing,
pushing, or deleting anything. Always run it once before a real run — especially
before `--clear-all`.

## ⚠️ `--clear-all` (privacy wipe — irreversible)

Runs **after** the backup and deletes: browser history, cookie/session data
(logs you out of web accounts), and in-browser password stores
(Chrome/Brave/Edge/Firefox). **Kept:** bookmarks, extensions, settings.
**Untouched:** the macOS Keychain (Safari/iCloud passwords, wifi, certificates) —
to remove those, use the Passwords / Keychain Access app.

```
/on-fire --clear-all                       # back up, then wipe (asks for typed confirmation)
/on-fire --clear-all --test                # simulate the wipe, delete nothing
/on-fire --clear-all --force               # skip confirmation (real panic)
/on-fire --clear-all --no-backup --force   # wipe only, no backup (not recommended)
```

> 🛑 Once passwords are deleted and you're logged out everywhere, you may not be
> able to get back into your own accounts unless those passwords live elsewhere
> (a real password manager). Run `--dry-run` first to see what would be deleted.
> If the backup fails, the script will not wipe without `--force`.

## Security notes

- **Copy, not move** — no local data loss even if a transfer is interrupted.
- **Separate branch** — your `main`/`master` history stays clean; if a secret is
  committed by accident, that branch can be deleted.
- **Respects .gitignore** + warns if files like `.env`/`*.key` get staged.
- This skill **runs code** on your machine (git push, file copy, deletion). Don't
  install it without reviewing the source; run `--dry-run` before any real run.

## License

MIT — see `LICENSE`.
