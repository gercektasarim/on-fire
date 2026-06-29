---
name: on-fire
description: >-
  Emergency "panic button" backup. With a single command it copies all your
  important files to Google Drive (rclone or the Drive desktop sync folder,
  auto-detected per OS) and commits + pushes every git project to a separate
  snapshot branch, so you can safely leave your environment in a hurry. Safe by
  design: copy (never move), commits land on an isolated on-fire/<timestamp>
  branch, .gitignore is respected, and everything is logged. Use when the user
  wants an emergency backup or fast exit. Triggers include: /on-fire, "fire",
  "yangin", "acil yedek", "her seyi yedekle ve cik", "panik butonu",
  "save everything and go", "back up and leave", "secure my environment".
license: MIT
compatibility: >-
  Requires Python 3.8+ and git. Optional but recommended: rclone, or Google
  Drive for Desktop. Works on Windows, macOS, and Linux. Compatible with Claude
  Code, Cowork, and any agent that supports the SKILL.md standard.
metadata:
  author: gercektasarim
  version: "1.1.1"
  tags:
    - backup
    - git
    - emergency
    - google-drive
    - automation
    - devops
---

# on-fire — Emergency backup

Goal: in a panic, **one command** secures the environment and the user leaves.
All the logic lives in `scripts/on_fire.py` — do not improvise; run the script
and summarize the result.

## What it does

1. Detects the OS (Windows/macOS/Linux) and the standard user folders.
2. **Copies** the configured folders (default: Desktop + Documents) to Drive
   (never moves them). rclone first, otherwise the Drive desktop sync folder.
3. Finds **all git projects** under the configured root dirs and commits + pushes
   each to an `on-fire/<timestamp>` branch. Respects `.gitignore`.
4. Logs everything under `~/on-fire-logs/`; if one step fails it keeps going.

## How to run it

The script is in this skill's `scripts/` subfolder. Call it from wherever the
skill is installed; two common paths:

```bash
# skills.sh / manual install (skill under ~/.claude/skills/on-fire/)
python3 ~/.claude/skills/on-fire/scripts/on_fire.py

# Installed as a plugin
python3 "${CLAUDE_PLUGIN_ROOT}/skills/on-fire/scripts/on_fire.py"
```

If unsure, locate `scripts/on_fire.py` next to this SKILL.md and run that.

Useful flags:
- `--dry-run` (aliases: `--test`, `--simulate`): change nothing, just show what
  would happen — recommended for the first try.
- `--no-drive` / `--no-git`: run only one step.
- `--config <path>`: alternative config file.
- `--clear-all`: **DANGEROUS.** After the backup, deletes browser history +
  cookies/sessions (web logout) + in-browser passwords. Bookmarks/extensions are
  kept, the macOS Keychain is untouched. Asks for typed confirmation.
- `--force`: skip the typed confirmation for `--clear-all` (for a real panic).
- `--no-backup`: with `--clear-all`, wipe without backing up first (not recommended).

## Behavior rules (important)

- This is an **emergency** command. Don't ask for lengthy confirmation before
  running; at most say one line ("running it") and start the script. If the user
  explicitly says "dry-run first", add `--dry-run`.
- When the script finishes, report **only the summary**: how many folders were
  copied to Drive, how many repos were pushed (to which branch), any errors or
  warnings, and where the log file is.
- If the script is about to commit a secret (`.env`, `*.key`, etc.) it prints a
  WARNING but, by default, still commits to the separate branch (the branch can
  be deleted, main is unaffected). Mention this in the report.
- If no Drive target is found (no rclone remote + no desktop folder) the script
  skips that step and warns; tell the user to set `rclone_remote` or
  `drive_folder` in `config.json`.
- `--clear-all` performs an IRREVERSIBLE deletion. NEVER add it on your own; run
  it only when the user explicitly asks. Before running, warn the user in one
  sentence: once passwords are deleted and they're logged out, they may not be
  able to get back into their accounts if the passwords aren't stored elsewhere.
  If the backup succeeded the script proceeds to wipe; if the backup failed it
  will not wipe without `--force`.

## Configuration

Settings are looked up in this order: `--config` path →
`~/.config/on-fire/config.json` → `config.json` in the skill directory. See
`config.example.json` for an example. Key fields: `backup_dirs`,
`project_roots`, `rclone_remote`, `drive_folder`, `block_on_secrets`.
