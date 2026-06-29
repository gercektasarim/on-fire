#!/usr/bin/env python3
"""
on-fire / clear_all — Privacy wipe (DANGEROUS, IRREVERSIBLE).

Invoked via --clear-all. It:
  * Deletes browser HISTORY (Chrome, Brave, Edge, Chromium, Vivaldi, Opera,
    Firefox, Safari).
  * Deletes COOKIE / SESSION data -> effectively logs you out of web accounts.
  * Deletes the browser's INTERNAL password store (Chromium 'Login Data',
    Firefox logins.json + key4.db).

It deliberately DOES NOT:
  * Touch the macOS Keychain. Safari/iCloud passwords live there, along with
    wifi, certificates, and app secrets, so deleting it would be far too broad
    and destructive. To remove those, use the Passwords / Keychain Access app.
  * Delete the whole profile -> bookmarks, extensions, and settings are kept.
    It targets only the history/cookie/password data files.
  * Sign out of native apps (Slack, Mail, etc.); the scope here is the web.

WARNING: deleting passwords + logging out can lock you out of your own accounts
if those passwords are not stored elsewhere. Make sure you have a real password
manager first.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

HOME = Path.home()


def _os() -> str:
    s = platform.system().lower()
    if s.startswith("win"):
        return "windows"
    if s == "darwin":
        return "macos"
    return "linux"


# --------------------------------------------------------------------------- #
# Target definitions
# --------------------------------------------------------------------------- #
# Chromium-family base dirs (per OS). Each base may hold multiple profiles
# (Default, Profile 1, ...).
def _chromium_bases(os_name: str) -> dict[str, Path]:
    if os_name == "macos":
        a = HOME / "Library" / "Application Support"
        return {
            "Chrome": a / "Google" / "Chrome",
            "Brave": a / "BraveSoftware" / "Brave-Browser",
            "Edge": a / "Microsoft Edge",
            "Chromium": a / "Chromium",
            "Vivaldi": a / "Vivaldi",
            "Opera": a / "com.operasoftware.Opera",
        }
    if os_name == "windows":
        la = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local"))
        ro = Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))
        return {
            "Chrome": la / "Google" / "Chrome" / "User Data",
            "Brave": la / "BraveSoftware" / "Brave-Browser" / "User Data",
            "Edge": la / "Microsoft" / "Edge" / "User Data",
            "Chromium": la / "Chromium" / "User Data",
            "Vivaldi": la / "Vivaldi" / "User Data",
            "Opera": ro / "Opera Software" / "Opera Stable",
        }
    # linux
    c = HOME / ".config"
    return {
        "Chrome": c / "google-chrome",
        "Brave": c / "BraveSoftware" / "Brave-Browser",
        "Edge": c / "microsoft-edge",
        "Chromium": c / "chromium",
        "Vivaldi": c / "vivaldi",
        "Opera": c / "opera",
    }


# Data to delete inside a Chromium profile. Searched within the profile root.
CHROMIUM_TARGETS = [
    # history
    "History", "History-journal", "Archived History",
    # passwords
    "Login Data", "Login Data-journal", "Login Data For Account",
    "Login Data For Account-journal",
    # cookies/session -> log out
    "Cookies", "Cookies-journal",
    "Network/Cookies", "Network/Cookies-journal",
    "Local Storage", "Session Storage", "IndexedDB", "Service Worker",
    "Sessions", "Current Session", "Current Tabs", "Last Session", "Last Tabs",
]


def _firefox_profiles(os_name: str) -> list[Path]:
    if os_name == "macos":
        base = HOME / "Library" / "Application Support" / "Firefox" / "Profiles"
    elif os_name == "windows":
        base = Path(os.environ.get("APPDATA", HOME)) / "Mozilla" / "Firefox" / "Profiles"
    else:
        base = HOME / ".mozilla" / "firefox"
    if not base.exists():
        return []
    return [p for p in base.iterdir() if p.is_dir()]


FIREFOX_TARGETS = [
    "places.sqlite",            # history + bookmarks (handled specially to keep bookmarks)
    "cookies.sqlite",           # cookies -> log out
    "logins.json", "key4.db",   # passwords
    "sessionstore.jsonlz4",     # session
    "sessionstore-backups",
    "webappsstore.sqlite",
    "storage",                  # DOM storage (log out)
]
# Note: places.sqlite holds both history and bookmarks. To keep bookmarks we do
# not delete places.sqlite outright; instead we clear the history tables only
# (special handling below).


# Browser application names (for quitting)
APP_NAMES = ["Google Chrome", "Brave Browser", "Microsoft Edge", "Chromium",
             "Vivaldi", "Opera", "firefox", "Safari"]
PROC_NAMES = ["Google Chrome", "Brave Browser", "Microsoft Edge", "chromium",
              "Vivaldi", "Opera", "firefox", "Safari"]


def quit_browsers(os_name: str, dry_run: bool, log) -> None:
    log("Quitting browsers (so their files aren't locked)...")
    if dry_run:
        log("  (dry-run) not quit")
        return
    if os_name == "macos":
        for app in APP_NAMES:
            subprocess.run(["osascript", "-e", f'tell application "{app}" to quit'],
                           capture_output=True)
        time.sleep(2)
        for proc in PROC_NAMES:
            subprocess.run(["pkill", "-x", proc], capture_output=True)
    elif os_name == "windows":
        for exe in ["chrome.exe", "brave.exe", "msedge.exe", "firefox.exe", "opera.exe", "vivaldi.exe"]:
            subprocess.run(["taskkill", "/IM", exe, "/F"], capture_output=True)
    else:
        for proc in ["chrome", "brave", "microsoft-edge", "firefox", "opera", "vivaldi", "chromium"]:
            subprocess.run(["pkill", "-f", proc], capture_output=True)
    time.sleep(1)


# --------------------------------------------------------------------------- #
# Deletion helpers
# --------------------------------------------------------------------------- #
def _rm(path: Path, dry_run: bool, log, counter: dict) -> None:
    if not path.exists():
        return
    if dry_run:
        log(f"  [would delete] {path}")
        counter["would"] += 1
        return
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
            for suf in ("-wal", "-shm"):
                sib = path.with_name(path.name + suf)
                if sib.exists():
                    sib.unlink(missing_ok=True)
        counter["deleted"] += 1
        log(f"  deleted: {path}")
    except Exception as e:  # noqa: BLE001
        counter["errors"] += 1
        log(f"  ERROR could not delete: {path} ({e})")


def _chromium_profiles(base: Path) -> list[Path]:
    if not base.exists():
        return []
    profs = []
    for name in os.listdir(base):
        p = base / name
        if p.is_dir() and (name == "Default" or name.startswith("Profile")):
            profs.append(p)
    return profs


def clear_chromium(os_name: str, dry_run: bool, log, counter: dict) -> None:
    for browser, base in _chromium_bases(os_name).items():
        profs = _chromium_profiles(base)
        if not profs:
            continue
        log(f"{browser}: {len(profs)} profile(s)")
        for prof in profs:
            for rel in CHROMIUM_TARGETS:
                _rm(prof / rel, dry_run, log, counter)


def clear_firefox(os_name: str, dry_run: bool, log, counter: dict) -> None:
    profs = _firefox_profiles(os_name)
    if not profs:
        return
    log(f"Firefox: {len(profs)} profile(s)")
    for prof in profs:
        for rel in FIREFOX_TARGETS:
            if rel == "places.sqlite":
                _clear_firefox_history_keep_bookmarks(prof / rel, dry_run, log, counter)
            else:
                _rm(prof / rel, dry_run, log, counter)


def _clear_firefox_history_keep_bookmarks(places: Path, dry_run: bool, log, counter: dict) -> None:
    """Delete only browsing history while preserving bookmarks."""
    if not places.exists():
        return
    if dry_run:
        log(f"  [would clear history, keep bookmarks] {places}")
        counter["would"] += 1
        return
    try:
        import sqlite3
        con = sqlite3.connect(str(places))
        cur = con.cursor()
        cur.execute("DELETE FROM moz_historyvisits;")
        # Delete non-bookmarked places (bookmarks are linked via moz_bookmarks)
        cur.execute("""DELETE FROM moz_places WHERE id NOT IN
                       (SELECT fk FROM moz_bookmarks WHERE fk IS NOT NULL);""")
        con.commit()
        con.close()
        counter["deleted"] += 1
        log(f"  history cleared (bookmarks kept): {places}")
    except Exception as e:  # noqa: BLE001
        counter["errors"] += 1
        log(f"  ERROR (firefox history): {e} -> deleting the file outright")
        _rm(places, dry_run, log, counter)


def clear_safari(dry_run: bool, log, counter: dict) -> None:
    if _os() != "macos":
        return
    log("Safari (history + cookies; passwords are in the Keychain, untouched)")
    targets = [
        HOME / "Library" / "Safari" / "History.db",
        HOME / "Library" / "Safari" / "History.db-wal",
        HOME / "Library" / "Safari" / "History.db-shm",
        HOME / "Library" / "Cookies" / "Cookies.binarycookies",
        HOME / "Library" / "Containers" / "com.apple.Safari" / "Data" / "Library" / "Cookies",
        HOME / "Library" / "Containers" / "com.apple.Safari" / "Data" / "Library" / "Safari" / "History.db",
        HOME / "Library" / "HTTPStorages",  # WebKit storage -> log out
    ]
    for t in targets:
        _rm(t, dry_run, log, counter)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def run_clear(log, dry_run: bool = False, force: bool = False) -> dict:
    """Run the wipe. log: a print-like function. Returns a summary."""
    os_name = _os()
    counter = {"deleted": 0, "would": 0, "errors": 0}

    log("─" * 50)
    log("⚠️  --clear-all: PRIVACY WIPE (IRREVERSIBLE)")
    log("    Will delete: browser history + cookies/sessions (logout) + in-browser passwords")
    log("    Will keep: bookmarks, extensions, settings; the macOS Keychain is untouched")

    if not dry_run and not force:
        try:
            ans = input("\n  Type CLEAR in uppercase to proceed (anything else cancels): ").strip()
        except EOFError:
            ans = ""
        if ans != "CLEAR":
            log("  Not confirmed -> wipe CANCELLED.")
            return {"aborted": True, **counter}

    quit_browsers(os_name, dry_run, log)
    clear_chromium(os_name, dry_run, log, counter)
    clear_firefox(os_name, dry_run, log, counter)
    clear_safari(dry_run, log, counter)

    log("─" * 50)
    if dry_run:
        log(f"DRY-RUN: {counter['would']} item(s) would be deleted (nothing was deleted).")
    else:
        log(f"Wipe complete: {counter['deleted']} item(s) deleted, {counter['errors']} error(s).")
    log("Note: you have been logged out of web accounts. If your passwords are not"
        " stored elsewhere, you may need a recovery flow to get back into your accounts.")
    return {"aborted": False, **counter}
