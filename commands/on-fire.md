---
description: 🔥 Emergency backup — copy files to Drive + commit & push all projects
argument-hint: "[--dry-run] [--no-drive] [--no-git] [--clear-all] [--force]"
allowed-tools: Bash
---

EMERGENCY BACKUP. This command is a "fire button": the goal is to quickly secure
the environment so the user can leave. Don't ask for lengthy confirmation — give
at most one line of info and run the script below IMMEDIATELY.

Try these script locations in order (use the first that exists):
1. `${CLAUDE_PLUGIN_ROOT}/skills/on-fire/scripts/on_fire.py`
2. `~/.claude/skills/on-fire/scripts/on_fire.py`

Run:

```bash
python3 <found_path> $ARGUMENTS
```

After the script finishes, report ONLY the summary:
- How many folders were copied to Drive
- How many repos were committed + pushed (to which branch)
- Any secret warnings or errors
- The path to the log file

If `$ARGUMENTS` contains `--dry-run` (or `--test` / `--simulate`), remind the user
that nothing will be changed.

If `$ARGUMENTS` contains `--clear-all`: this is an IRREVERSIBLE deletion
(browser history + cookies/logout + in-browser passwords). Before running, warn
the user in one sentence: if their passwords aren't stored elsewhere, they may
not be able to get back into their accounts. The script already asks for typed
confirmation (unless `--force`) and will not wipe if the backup failed.
