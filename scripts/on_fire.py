#!/usr/bin/env python3
"""
on-fire — Emergency "panic button" backup script.

What it does:
  1) Detects the host OS and the standard user file folders.
  2) COPIES the configured folders (default: Desktop + Documents) to Drive
     (never moves them). Uses rclone first, otherwise the Drive desktop sync folder.
  3) Finds ALL git projects under the configured root dirs and commits + pushes
     each one to a separate "on-fire/<timestamp>" branch.
  4) Logs everything to a file; if one step fails it keeps going with the rest.

Design principle: FAST AND SAFE IN A PANIC.
  - Copy (not move) -> no local loss even if a transfer is interrupted.
  - Separate branch -> main/master history stays clean; if a secret is committed
    by accident, that branch can be deleted without touching the main branch.
  - Respects .gitignore (git's default) -> ignored secrets are not committed.

No dependencies beyond the stdlib. Uses rclone/rsync/robocopy if present,
otherwise falls back to pure Python (shutil) copying.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# Default configuration. Can be overridden via config.json.
# --------------------------------------------------------------------------- #
DEFAULT_CONFIG = {
    # Folders to copy to Drive (~ expands to the home directory)
    "backup_dirs": ["~/Desktop", "~/Documents"],
    # Root dirs to scan for git projects
    "project_roots": ["~/projects", "~/code", "~/dev", "~/src", "~/repos", "~/Documents"],
    # Empty = auto-select the first configured rclone remote
    "rclone_remote": "",
    # Empty = auto-detect the Drive desktop folder based on OS
    "drive_folder": "",
    # Parent folder on Drive where backups are collected
    "drive_subdir": "on-fire-backup",
    "branch_prefix": "on-fire",
    "commit_message": "on-fire: emergency backup snapshot",
    # Folders to skip when copying (prevents bloat)
    "exclude_dirs": ["node_modules", ".cache", "venv", ".venv", "__pycache__",
                     ".git", "dist", "build", ".next", "target", ".gradle"],
    # File patterns that trigger a WARNING if they get staged for commit
    "warn_secret_patterns": [".env", ".env.*", "*.pem", "*.key", "id_rsa",
                             "*credential*", "*secret*", "*.pfx", "*.p12"],
    # If True, a repo with a detected secret is not committed (safety over panic speed)
    "block_on_secrets": False,
    # Max depth for the git scan (from each root dir)
    "scan_max_depth": 4,
}

LOG_LINES: list[str] = []


def log(msg: str) -> None:
    stamp = dt.datetime.now().strftime("%H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    LOG_LINES.append(line)


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
def load_config(path: Path | None) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    candidates = []
    if path:
        candidates.append(path)
    candidates += [
        Path.home() / ".config" / "on-fire" / "config.json",
        Path(__file__).resolve().parent.parent / "config.json",
    ]
    for c in candidates:
        try:
            if c and c.is_file():
                user = json.loads(c.read_text(encoding="utf-8"))
                cfg.update(user)
                log(f"Loaded configuration: {c}")
                break
        except Exception as e:  # noqa: BLE001
            log(f"WARNING: could not read configuration ({c}): {e}")
    return cfg


def expand(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p)))


# --------------------------------------------------------------------------- #
# OS and folder detection
# --------------------------------------------------------------------------- #
def detect_os() -> str:
    s = platform.system().lower()
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "macos"
    return "linux"


def which(name: str) -> str | None:
    return shutil.which(name)


def find_drive_folder(os_name: str, override: str) -> Path | None:
    """Find the Google Drive for Desktop sync folder."""
    if override:
        p = expand(override)
        return p if p.exists() else None

    home = Path.home()
    candidates: list[Path] = []
    if os_name == "macos":
        candidates += [home / "Google Drive" / "My Drive", home / "Google Drive"]
        cs = home / "Library" / "CloudStorage"
        if cs.exists():
            for d in cs.glob("GoogleDrive-*"):
                candidates += [d / "My Drive", d]
    elif os_name == "windows":
        candidates += [home / "Google Drive" / "My Drive", home / "Google Drive",
                       home / "My Drive"]
        # Drive for Desktop virtual drive (like G:) — try common letters
        for letter in "GHIJKL":
            candidates.append(Path(f"{letter}:/My Drive"))
            candidates.append(Path(f"{letter}:/"))
    else:  # linux
        candidates += [home / "Google Drive" / "My Drive", home / "GoogleDrive",
                       home / "gdrive"]

    for c in candidates:
        try:
            if c.exists():
                return c
        except OSError:
            continue
    return None


def find_rclone_remote(preferred: str) -> str | None:
    if not which("rclone"):
        return None
    try:
        out = subprocess.run(["rclone", "listremotes"], capture_output=True,
                             text=True, timeout=20)
        remotes = [r.strip() for r in out.stdout.splitlines() if r.strip()]
    except Exception:  # noqa: BLE001
        return None
    if not remotes:
        return None
    if preferred:
        want = preferred.rstrip(":") + ":"
        if want in remotes:
            return want
        log(f"WARNING: remote '{preferred}' not found; using the first remote.")
    return remotes[0]  # in "name:" format


# --------------------------------------------------------------------------- #
# File copying
# --------------------------------------------------------------------------- #
def copy_tree_python(src: Path, dst: Path, exclude: list[str]) -> int:
    """Pure-Python fallback copy when rclone/rsync is unavailable. Returns file count."""
    count = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in exclude]
        rel = Path(root).relative_to(src)
        target_root = dst / rel
        target_root.mkdir(parents=True, exist_ok=True)
        for f in files:
            try:
                shutil.copy2(Path(root) / f, target_root / f)
                count += 1
            except Exception as e:  # noqa: BLE001
                log(f"  could not copy: {Path(root) / f} ({e})")
    return count


def copy_dir_to_drive(src: Path, dest_root: str, is_rclone: bool, cfg: dict,
                      host: str, dry_run: bool) -> bool:
    """Copy a single folder to the Drive target. dest_root can be an rclone
    remote ('name:') or a local folder path."""
    label = src.name or "root"
    sub = f"{cfg['drive_subdir']}/{host}/{label}"
    exclude = cfg["exclude_dirs"]

    if is_rclone:
        dest = f"{dest_root}{sub}" if dest_root.endswith(":") else f"{dest_root}/{sub}"
        cmd = ["rclone", "copy", str(src), dest, "--create-empty-src-dirs", "-P"]
        for x in exclude:
            cmd += ["--exclude", f"{x}/**"]
        if dry_run:
            cmd.append("--dry-run")
        log(f"  rclone copy -> {dest}")
        try:
            subprocess.run(cmd, check=True, timeout=60 * 60)
            return True
        except Exception as e:  # noqa: BLE001
            log(f"  ERROR (rclone): {e}")
            return False

    # Local folder target (Drive desktop sync)
    dest_path = Path(dest_root) / sub
    log(f"  copy -> {dest_path}")
    if dry_run:
        log("  (dry-run, not copied)")
        return True

    os_name = detect_os()
    try:
        if os_name in ("macos", "linux") and which("rsync"):
            cmd = ["rsync", "-a"]
            for x in exclude:
                cmd += ["--exclude", x]
            cmd += [str(src) + "/", str(dest_path) + "/"]
            dest_path.mkdir(parents=True, exist_ok=True)
            subprocess.run(cmd, check=True, timeout=60 * 60)
            return True
        if os_name == "windows" and which("robocopy"):
            cmd = ["robocopy", str(src), str(dest_path), "/E", "/NFL", "/NDL", "/NJH"]
            if exclude:
                cmd += ["/XD"] + exclude
            # robocopy treats exit codes 0-7 as "success"
            r = subprocess.run(cmd, timeout=60 * 60)
            return r.returncode < 8
        # Pure-Python fallback
        n = copy_tree_python(src, dest_path, exclude)
        log(f"  copied {n} files (python)")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"  ERROR (copy): {e}")
        return False


# --------------------------------------------------------------------------- #
# Git operations
# --------------------------------------------------------------------------- #
def find_git_repos(roots: list[str], max_depth: int, exclude: list[str]) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for r in roots:
        base = expand(r)
        if not base.exists():
            continue
        base_depth = len(base.parts)
        for root, dirs, _files in os.walk(base):
            cur = Path(root)
            depth = len(cur.parts) - base_depth
            if depth > max_depth:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in exclude]
            if (cur / ".git").exists():
                rp = cur.resolve()
                if rp not in seen:
                    seen.add(rp)
                    found.append(rp)
                dirs[:] = []  # repo found, don't descend into subdirs
    return found


def git(repo: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=timeout)


def staged_files(repo: Path) -> list[str]:
    r = git(repo, "diff", "--cached", "--name-only")
    return [f for f in r.stdout.splitlines() if f.strip()]


def detect_secrets(files: list[str], patterns: list[str]) -> list[str]:
    hits = []
    for f in files:
        name = Path(f).name
        for pat in patterns:
            if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(f, pat):
                hits.append(f)
                break
    return hits


def save_repo(repo: Path, cfg: dict, branch: str, dry_run: bool) -> dict:
    res = {"repo": str(repo), "status": "", "branch": branch, "pushed": False}
    log(f"GIT: {repo}")

    # Is there anything worth doing?
    st = git(repo, "status", "--porcelain")
    if not st.stdout.strip():
        res["status"] = "clean (no changes)"
        log("  no changes, skipped")
        return res

    if dry_run:
        res["status"] = "dry-run (not committed)"
        log("  (dry-run) commit/push skipped")
        return res

    # Stage everything
    git(repo, "add", "-A")
    files = staged_files(repo)

    secrets = detect_secrets(files, cfg["warn_secret_patterns"])
    if secrets:
        log(f"  ⚠️  POSSIBLE SECRET ({len(secrets)}): {', '.join(secrets[:5])}"
            + (" ..." if len(secrets) > 5 else ""))
        if cfg.get("block_on_secrets"):
            git(repo, "reset")  # unstage
            res["status"] = "SKIPPED (secret detected, block_on_secrets=True)"
            log("  block_on_secrets=True -> this repo was not committed")
            return res

    # Create a separate snapshot branch (staged changes carry over)
    cb = git(repo, "checkout", "-b", branch)
    if cb.returncode != 0:
        res["status"] = f"could not create branch: {cb.stderr.strip()}"
        log(f"  ERROR: {cb.stderr.strip()}")
        return res

    msg = f"{cfg['commit_message']} ({dt.datetime.now().isoformat(timespec='seconds')})"
    cm = git(repo, "commit", "-m", msg)
    if cm.returncode != 0:
        res["status"] = f"commit error: {cm.stderr.strip() or cm.stdout.strip()}"
        log(f"  ERROR: {res['status']}")
        return res
    log(f"  committed -> {branch} ({len(files)} files)")

    # Push (if no remote or no network: the local commit still stands)
    has_remote = git(repo, "remote").stdout.strip()
    if not has_remote:
        res["status"] = "committed (no remote, push skipped)"
        log("  no remote configured, push skipped (local commit is safe)")
        return res

    ps = git(repo, "push", "-u", "origin", branch, timeout=180)
    if ps.returncode == 0:
        res["pushed"] = True
        res["status"] = "commit + push OK"
        log("  push OK")
    else:
        res["status"] = f"commit OK, PUSH ERROR: {ps.stderr.strip()[:200]}"
        log(f"  PUSH ERROR: {ps.stderr.strip()[:200]}")
    return res


# --------------------------------------------------------------------------- #
# Main flow
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="on-fire emergency backup")
    ap.add_argument("--config", type=Path, default=None, help="path to config.json")
    ap.add_argument("--dry-run", "--test", "--simulate", dest="dry_run",
                    action="store_true",
                    help="change nothing, only show what would happen (safe to test)")
    ap.add_argument("--no-git", action="store_true", help="skip the git step")
    ap.add_argument("--no-drive", action="store_true", help="skip the Drive copy step")
    ap.add_argument("--clear-all", action="store_true",
                    help="DANGEROUS: after backup, delete browser history+cookies+passwords and log out")
    ap.add_argument("--no-backup", action="store_true",
                    help="with --clear-all: skip backup, only wipe (NOT RECOMMENDED)")
    ap.add_argument("--force", action="store_true",
                    help="skip the typed confirmation for --clear-all (for a real panic)")
    args = ap.parse_args()

    start = dt.datetime.now()
    os_name = detect_os()
    host = socket.gethostname()
    ts = start.strftime("%Y%m%d-%H%M%S")

    log("🔥 on-fire started" + (" [DRY-RUN]" if args.dry_run else ""))
    log(f"OS: {os_name} | host: {host}")

    cfg = load_config(args.config)
    branch = f"{cfg['branch_prefix']}/{ts}"

    summary = {"drive": [], "git": []}

    # --no-backup: means a wipe-only run, skip the backup steps
    do_drive = not args.no_drive and not args.no_backup
    do_git = not args.no_git and not args.no_backup
    if args.no_backup:
        log("⚠️  --no-backup: proceeding straight to wipe without a backup (not recommended)")

    # --- Drive copy ---
    if do_drive:
        remote = find_rclone_remote(cfg["rclone_remote"])
        if remote:
            dest_root, is_rclone = remote, True
            log(f"Drive method: rclone ({remote})")
        else:
            folder = find_drive_folder(os_name, cfg["drive_folder"])
            if folder:
                dest_root, is_rclone = str(folder), False
                log(f"Drive method: desktop sync folder ({folder})")
            else:
                dest_root = None
                log("⚠️  No Drive target found (no rclone remote, no desktop folder)."
                    " Drive step skipped.")
                summary["drive"].append({"dir": "(no Drive target found)", "ok": False})
        if dest_root:
            for d in cfg["backup_dirs"]:
                src = expand(d)
                if not src.exists():
                    log(f"  missing, skipped: {src}")
                    continue
                ok = copy_dir_to_drive(src, dest_root, is_rclone, cfg, host, args.dry_run)
                summary["drive"].append({"dir": str(src), "ok": ok})
    else:
        log("Drive step skipped via --no-drive")

    # --- Git ---
    if do_git:
        repos = find_git_repos(cfg["project_roots"], cfg["scan_max_depth"], cfg["exclude_dirs"])
        log(f"Found {len(repos)} git projects")
        for repo in repos:
            try:
                summary["git"].append(save_repo(repo, cfg, branch, args.dry_run))
            except Exception as e:  # noqa: BLE001
                log(f"  ERROR ({repo}): {e}")
                summary["git"].append({"repo": str(repo), "status": f"error: {e}", "pushed": False})
    else:
        log("Git step skipped via --no-git")

    # --- Summary ---
    dur = (dt.datetime.now() - start).total_seconds()
    pushed = sum(1 for g in summary["git"] if g.get("pushed"))
    drive_ok = sum(1 for d in summary["drive"] if d.get("ok"))
    log("─" * 50)
    log(f"DONE ({dur:.1f}s) | Drive folders: {drive_ok}/{len(summary['drive'])} OK"
        f" | Repos pushed: {pushed}/{len(summary['git'])}")
    fails = [g for g in summary["git"] if "ERROR" in g.get("status", "") or "error" in g.get("status", "")]
    if fails:
        log(f"⚠️  {len(fails)} repo(s) had issues — check the log file.")

    # --- Wipe (--clear-all) ---
    if args.clear_all:
        drive_fail = any(not d.get("ok") for d in summary["drive"])
        backup_clean = (not fails) and (not drive_fail)
        if not args.no_backup and not backup_clean and not args.force:
            log("⛔ Backup had problems -> wipe NOT performed for safety."
                " (To wipe anyway add --force; but fix the backup first.)")
        else:
            if not args.no_backup and not args.dry_run and backup_clean:
                log("✓ Backup verified clean, proceeding to wipe.")
            try:
                from clear_all import run_clear
                run_clear(log, dry_run=args.dry_run, force=args.force)
            except Exception as e:  # noqa: BLE001
                log(f"ERROR (wipe module): {e}")

    # --- Log file ---
    log_dir = Path.home() / "on-fire-logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"on-fire-{ts}.log"
        log_file.write_text("\n".join(LOG_LINES), encoding="utf-8")
        print(f"\nLog: {log_file}")
    except Exception as e:  # noqa: BLE001
        print(f"Could not write log: {e}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
