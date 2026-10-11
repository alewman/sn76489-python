#!/usr/bin/env python
"""Fetch the referee's source and the pinned reference files.

    python scripts/fetch_references.py            # fetch what is missing
    python scripts/fetch_references.py --verify   # only check what is there

Into ``reference/`` (ignored). Nuked-PSG is GPL-2.0: read and run as a referee here,
never copied into this repository. The two SMS Power files are the wiki's noise bit
patterns, checked by SHA-256 (the same pins as sms-python's
``scripts/pinned_files.json``).
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "reference" / "src"

#: The pin, the same as megadrive-python's scripts/pinned_repos.json.
REPOS = [
    {
        "path": "Nuked-PSG",
        "url": "https://github.com/nukeykt/Nuked-PSG",
        "rev": "d15a168c676f4669e23660be9225b34ad7c1764e",
        "why": "The PSG inside the YM7101 VDP, transcribed from its die: the judge. GPL-2.0.",
    },
]

#: Maxim's wiki's noise bit patterns: illustrations, not recordings (docs/claims.md).
FILES = [
    {
        "path": "reference/smspower-attach/SN76489WhiteNoise.zip",
        "url": "https://www.smspower.org/uploads/Development/SN76489WhiteNoise.zip",
        "sha256": "dfb670d472471f7e3d20969cc07574af6ca4f2af7517391e786ea3022dd9177d",
    },
    {
        "path": "reference/smspower-attach/SegaVDPWhiteNoise.zip",
        "url": "https://www.smspower.org/uploads/Development/SegaVDPWhiteNoise.zip",
        "sha256": "e49b1a3c26cb51a76c009adb3e713bc375f5e5f9c569104fd5eb99a3c705e576",
    },
]


#: SMS Power answers Python's default user agent with 403 Forbidden.
USER_AGENT = "Mozilla/5.0 (sn76489-python reference fetch)"


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def fetch_files(verify: bool) -> int:
    bad = 0
    for entry in FILES:
        path = ROOT / entry["path"]
        if sha256(path) == entry["sha256"]:
            print(f"{entry['path']}: ok")
            continue
        if verify:
            print(f"{entry['path']}: missing or wrong SHA-256")
            bad += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(entry["url"], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            print(f"{entry['path']}: fetched file has the wrong SHA-256; not saved")
            bad += 1
            continue
        path.write_bytes(data)
        print(f"{entry['path']}: fetched")
    return bad


def head(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return result.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--verify", action="store_true", help="check, do not fetch")
    args = parser.parse_args(argv)
    bad = 0
    for entry in REPOS:
        path = SRC / entry["path"]
        if head(path) == entry["rev"]:
            print(f"{entry['path']}: at {entry['rev'][:7]}")
            continue
        if args.verify:
            print(f"{entry['path']}: missing or not at {entry['rev'][:7]}")
            bad += 1
            continue
        path.mkdir(parents=True, exist_ok=True)
        git = ["git", "-C", str(path)]
        if not (path / ".git").exists():
            subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run(
            [*git, "fetch", "-q", "--depth", "1", entry["url"], entry["rev"]], check=True
        )
        subprocess.run([*git, "checkout", "-q", "--detach", "FETCH_HEAD"], check=True)
        if head(path) != entry["rev"]:
            print(f"{entry['path']}: fetched the wrong revision")
            bad += 1
            continue
        print(f"{entry['path']}: fetched {entry['rev'][:7]}")
    bad += fetch_files(args.verify)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
