# Scripts

Utility scripts for development, evaluation, and publishing.

| Script | What it does |
| --- | --- |
| `hello_strohsack.py` | Smoke test — generates one Strohsack reply via the Claude API. |
| `run_personality_eval.py` | Runs the LLM-as-judge personality eval (probes + rubric) and writes a report. |
| `check_no_private_data.py` | Pre-publish scan gate. Greps the git-tracked tree for private/family data. Exits non-zero on any hit. |
| `publish_public_snapshot.py` | Publishes a scrubbed snapshot of this private repo to the public repo. |

## Publishing to the public repo

This (`strohsack-ai`) is the **private, full-history working repo**. The public
repo [`strohsack-ai-public`](https://github.com/YingzhiVA/strohsack-ai-public)
receives a **fresh, squashed snapshot** of the scrubbed tree — no private
history and no private files (e.g. `personality.private.json`) ever cross over.
See `STROHSACK_PROJECT_PLAN.md` → *Pre-Public Hardening* for the rationale.

To publish (typically when a milestone lands on `main`):

```bash
# 1. Preview: build + scan the snapshot, but don't push.
python scripts/publish_public_snapshot.py --dry-run

# 2. Publish origin/main (asks for confirmation before force-pushing).
python scripts/publish_public_snapshot.py
```

What it guarantees:

- Publishes from **`origin/main`** by default (the reviewed state), not your
  working tree — use `--ref` to publish a different commit.
- Exports **tracked files only** (`git archive`), so gitignored private files
  are structurally excluded; an extra check also fails on any `*.private.*` file.
- Runs `check_no_private_data.py` as a **hard gate** against the staged export
  and aborts (non-zero) if anything is found — it never pushes a tree it
  couldn't verify.
- Force-pushes a single squashed commit authored with the GitHub noreply email.

The push step asks you to type `publish` to confirm; pass `--yes` to skip that
(e.g. for automation), and `--dry-run` to stop before pushing entirely.
