#!/usr/bin/env python3
"""Pre-publish scan: fail if any private/family data is present in the tree.

This is the final gate before making the repository public (see
STROHSACK_PROJECT_PLAN.md, Milestone 3.6). It scans the git-tracked working
tree for the sensitive family terms and structural keys that must live only in
the private, gitignored personality overlay. It exits non-zero (CI-friendly) if
anything is found.

Usage:
    python scripts/check_no_private_data.py

Scans only files git would track (respects .gitignore), so the private overlay
``personality.private.json`` is not scanned. This script excludes itself.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Two tiers of patterns (all case-insensitive):
#
# HARD_FORBIDDEN — the actual secret. These name real relatives or encode
# relationship-specific behavior that embeds those names. They must NOT appear
# in ANY tracked file (code, docs, tests, configs). If one of these shows up,
# something leaked.
HARD_FORBIDDEN = [
    r"\bbig[ _]bear\b",
    r"\bbig[ _]pig\b",
    r"\blittle[ _]ones\b",
    r"runs_to_big_bear",
    r"initiates_big_pig",
    r"protects_little_ones",
    r"big_brother_duties",
]

# CONFIG_ONLY_FORBIDDEN — generic *structural* keys. They are fine to mention in
# code, tests, and docs (the loader and its tests legitimately reference them),
# but real data lives in profile JSON, so they must never appear in a tracked
# personality config file. Enforced only against src/config/*.json.
CONFIG_ONLY_FORBIDDEN = [
    r"relationship_dynamics",
    r"family_teasing_targets",
    r"family_teasing_skill",
    r"family_dynamic_teasing",
    r"\"(family_conversation|big_bear_bonding|big_pig_teasing|little_ones_interaction|family_gathering)\"",
]

CONFIG_GLOB = "src/config/"

# This script itself defines the patterns above, so it is excluded from scanning.
SCRIPT_REL = "scripts/check_no_private_data.py"


def tracked_text_files() -> list[Path]:
    """Return git-tracked files (respects .gitignore via `git ls-files`)."""
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    files = []
    for rel in out.stdout.splitlines():
        rel = rel.strip()
        if not rel or rel == SCRIPT_REL:
            continue
        files.append(REPO_ROOT / rel)
    return files


def scan() -> list[tuple[str, int, str, str]]:
    """Return a list of (relpath, lineno, pattern, line) hits."""
    hard = [(p, re.compile(p, re.IGNORECASE)) for p in HARD_FORBIDDEN]
    config_only = [(p, re.compile(p, re.IGNORECASE)) for p in CONFIG_ONLY_FORBIDDEN]
    hits: list[tuple[str, int, str, str]] = []
    for path in tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable — skip
        rel = path.relative_to(REPO_ROOT).as_posix()
        # Structural keys are only forbidden inside personality config files.
        is_config = rel.startswith(CONFIG_GLOB)
        active = hard + config_only if is_config else hard
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern, regex in active:
                if regex.search(line):
                    hits.append((rel, lineno, pattern, line.strip()))
    return hits


def main() -> int:
    hits = scan()
    if not hits:
        print("OK: no private/family data found in the tracked working tree.")
        return 0

    print("FAIL: private/family data found in the tracked working tree:\n")
    for rel, lineno, pattern, line in hits:
        print(f"  {rel}:{lineno}  [{pattern}]  {line}")
    print(
        f"\n{len(hits)} match(es). Move this data to the gitignored "
        "personality.private.json before publishing."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
