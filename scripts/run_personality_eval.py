"""
Run the live Strohsack personality eval (Milestone 1B).

Drives the probe set through the real Strohsack client and scores each reply
with the real LLM judge, then prints a summary and saves a timestamped report.
This SPENDS API TOKENS — it's the opt-in counterpart to the offline harness
tests in tests/test_eval.py.

Run with:  python scripts/run_personality_eval.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# Allow running directly without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from strohsack.eval.judge import LLMJudge  # noqa: E402
from strohsack.eval.runner import format_report, run_eval  # noqa: E402
from strohsack.utils.api_client import StrohsackClient  # noqa: E402
from strohsack.utils.config_loader import ConfigError, load_config  # noqa: E402

REPORTS_DIR = Path(__file__).resolve().parents[1] / "eval_reports"


def main() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    # No fact store: the personality eval runs the plain, memory-free responder
    # path (no fact injection, no remember() tool), which is the path that
    # established the 0.96 baseline and keeps probes isolated from durable memory.
    responder = StrohsackClient(config)
    judge = LLMJudge(config)

    print("Running personality eval (this will make API calls)...\n")
    report = run_eval(responder, judge)

    rendered = format_report(report)
    print(rendered)

    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = REPORTS_DIR / f"eval-{stamp}.md"
    out_path.write_text(rendered, encoding="utf-8")
    print(f"\nReport saved to: {out_path}")

    if report.failures:
        print(f"\nWARNING: {report.failures} probe(s) failed and were excluded.", file=sys.stderr)

    # Non-zero exit if we missed the plan's >90% in-character target or any
    # probe failed, so this can gate a release if ever wired into CI.
    passed = report.in_character_rate >= 0.9 and report.failures == 0
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
