#!/usr/bin/env python3
"""Publish a scrubbed public snapshot of this (private) repo.

This automates the Milestone 3.6 publishing model: the private repo
(``strohsack-ai``) is the full-history working repo; the public repo
(``strohsack-ai-public``) receives a *fresh, squashed snapshot* of the scrubbed
tree on each release. No private history and no private files ever cross over.

What it does, in order:
  1. Resolves the source commit (default: ``origin/main`` — the reviewed,
     canonical state, never your dirty working tree).
  2. Exports that commit's **tracked files only** via ``git archive`` into a
     temporary directory. Because git archive emits only tracked files, the
     gitignored private overlay (``personality.private.json``) and other
     gitignored paths (``my-learnings/`` etc.) are structurally excluded.
  3. ``git init``s the export and stages everything, so the pre-publish scan
     runs against a real index (avoids the false-clean-on-zero-files trap).
  4. Runs ``scripts/check_no_private_data.py`` as a hard gate. Aborts on any hit.
  5. Makes a single commit and **force-pushes** it to the public repo's default
     branch — but only after an explicit confirmation (unless ``--yes``).

Usage:
    python scripts/publish_public_snapshot.py            # publish origin/main
    python scripts/publish_public_snapshot.py --ref HEAD # publish a specific ref
    python scripts/publish_public_snapshot.py --dry-run  # build + scan, no push
    python scripts/publish_public_snapshot.py --yes      # skip confirmation

Requires: git, and push access to the public remote.
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The public destination. Single source of truth — change here if it ever moves.
PUBLIC_REMOTE_URL = "https://github.com/YingzhiVA/strohsack-ai-public.git"
PUBLIC_BRANCH = "main"

DEFAULT_REF = "origin/main"
COMMIT_AUTHOR_NAME = "YingzhiVA"
# noreply form — keeps the real email out of public commit metadata and avoids
# GitHub's push-time email-privacy rejection.
COMMIT_AUTHOR_EMAIL = "218220824+YingzhiVA@users.noreply.github.com"

SCAN_SCRIPT_REL = "scripts/check_no_private_data.py"


def run(cmd: list[str], cwd: Path, *, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command, raising on failure. Echoes the command for transparency."""
    print(f"  $ {' '.join(cmd)}  (in {cwd})")
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=capture,
    )


def resolve_commit(ref: str) -> str:
    """Resolve ``ref`` to a full commit sha in the source repo."""
    out = run(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], REPO_ROOT, capture=True)
    return out.stdout.strip()


def export_tree(commit: str, dest: Path) -> int:
    """Export tracked files of ``commit`` into ``dest`` via git archive.

    Returns the number of files extracted. Raises if zero (a sign something is
    wrong — we never want to publish an empty tree).
    """
    print(f"Exporting tracked tree of {commit[:10]} ...")
    archive = subprocess.run(
        ["git", "archive", "--format=tar", commit],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tf:
        tf.extractall(dest, filter="data")
    files = [p for p in dest.rglob("*") if p.is_file()]
    if not files:
        raise SystemExit("ABORT: git archive produced no files — nothing to publish.")
    print(f"  extracted {len(files)} files")
    return len(files)


def assert_no_private_files(dest: Path) -> None:
    """Belt-and-suspenders: explicitly fail if any *.private.* file slipped in.

    git archive already excludes gitignored files, but this guards against a
    private file that was mistakenly committed (and thus tracked) upstream.
    """
    leaked = [p for p in dest.rglob("*") if ".private." in str(p.relative_to(dest))]
    if leaked:
        names = ", ".join(str(p.relative_to(dest)) for p in leaked)
        raise SystemExit(f"ABORT: private file(s) present in export: {names}")


def init_and_stage(dest: Path) -> int:
    """git init the export and stage all files. Returns tracked file count.

    Staging matters: the scan uses `git ls-files`, so it must run against a real
    repo+index, or it scans nothing and falsely passes.
    """
    run(["git", "init", "-q"], dest)
    run(["git", "add", "-A"], dest)
    out = run(["git", "ls-files"], dest, capture=True)
    tracked = [line for line in out.stdout.splitlines() if line.strip()]
    if not tracked:
        raise SystemExit("ABORT: nothing staged in the export — scan would be meaningless.")
    print(f"  staged {len(tracked)} tracked files")
    return len(tracked)


def run_scan_gate(dest: Path) -> None:
    """Run the pre-publish scan inside the export. Aborts publish on any hit."""
    scan = dest / SCAN_SCRIPT_REL
    if not scan.exists():
        raise SystemExit(
            f"ABORT: {SCAN_SCRIPT_REL} not found in the export — cannot verify the tree is clean."
        )
    print("Running pre-publish scan gate ...")
    result = subprocess.run(
        [sys.executable, str(scan)],
        cwd=dest,
        env={**_env_with_src(dest)},
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit("ABORT: pre-publish scan FAILED. Private data present — not publishing.")
    print("  scan clean.")


def _env_with_src(dest: Path) -> dict:
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(dest / "src")
    # Strip git plumbing env vars that could redirect git commands to the
    # original private repo instead of the temp export. If GIT_DIR is set in
    # the caller's environment, git ls-files inside the scan would enumerate
    # the private repo's index — all read_text calls would fail silently via
    # the OSError handler, the scan would return zero hits, and private data
    # could be published without detection.
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY"):
        env.pop(var, None)
    return env


def commit_and_push(dest: Path, commit: str, *, dry_run: bool, assume_yes: bool) -> None:
    message = (
        "Public release: Strohsack AI\n\n"
        f"Scrubbed public snapshot of the private repo at {commit[:10]}.\n"
        "Generic bear only; relationship/family behavior is a private at-home\n"
        "overlay and is intentionally not part of this repository.\n\n"
        "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
    )
    run(["git", "branch", "-M", PUBLIC_BRANCH], dest)
    run(
        [
            "git",
            "-c", f"user.name={COMMIT_AUTHOR_NAME}",
            "-c", f"user.email={COMMIT_AUTHOR_EMAIL}",
            "commit", "-q", "-m", message,
        ],
        dest,
    )

    if dry_run:
        print("\nDRY RUN: built and scanned a clean snapshot. Not pushing.")
        print(f"  (would force-push to {PUBLIC_REMOTE_URL} {PUBLIC_BRANCH})")
        return

    print(f"\nAbout to FORCE-PUSH a fresh snapshot to:\n  {PUBLIC_REMOTE_URL} ({PUBLIC_BRANCH})")
    print("This replaces the public repo's history with one squashed commit.")
    if not assume_yes:
        reply = input("Type 'publish' to confirm: ").strip()
        if reply != "publish":
            raise SystemExit("Aborted by user.")

    run(["git", "remote", "add", "public", PUBLIC_REMOTE_URL], dest)
    run(["git", "push", "--force", "public", f"{PUBLIC_BRANCH}:{PUBLIC_BRANCH}"], dest)
    print(f"\nPublished. https://github.com/YingzhiVA/strohsack-ai-public/tree/{PUBLIC_BRANCH}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref",
        default=DEFAULT_REF,
        help=f"Source ref to publish (default: {DEFAULT_REF}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and scan the snapshot but do not push.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation before force-pushing.",
    )
    args = parser.parse_args()

    # Always fetch so origin/main is current before we publish from it.
    if args.ref.startswith("origin/"):
        run(["git", "fetch", "origin", "-q"], REPO_ROOT)

    commit = resolve_commit(args.ref)
    print(f"Source: {args.ref} -> {commit}")

    tmp = Path(tempfile.mkdtemp(prefix="strohsack-public-"))
    try:
        export_tree(commit, tmp)
        assert_no_private_files(tmp)
        init_and_stage(tmp)
        run_scan_gate(tmp)
        commit_and_push(tmp, commit, dry_run=args.dry_run, assume_yes=args.yes)
    finally:
        _rmtree(tmp)
    return 0


def _rmtree(path: Path) -> None:
    """Remove a directory tree, handling Windows read-only files (git objects)."""
    def _on_error(func, fpath, exc_info):
        # Git writes objects as read-only; clear the bit and retry.
        try:
            os.chmod(fpath, stat.S_IWRITE)
            func(fpath)
        except OSError as exc:
            print(f"WARNING: could not remove temp dir {path}: {exc}", file=sys.stderr)
            print("  Remove it manually to avoid leaving export data on disk.", file=sys.stderr)

    shutil.rmtree(path, onerror=_on_error)


if __name__ == "__main__":
    sys.exit(main())
