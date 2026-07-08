"""
Latency benchmark for the M2B builtin memory tool (the "before" baseline).

NOTE (M2C): this measures the *legacy* M2B architecture — the builtin
``memory_20250818`` / ``BetaLocalFilesystemMemoryTool``, whose server-side
behavior forces a ``view /memories`` read on every turn. M2C replaced that in
``StrohsackClient`` with inject-on-read / tool-on-write, where recall costs zero
round-trips and only a fact-saving turn pays an extra hop. This script is kept
as the documented "before" baseline; it no longer reflects the production path.
(An "after" measurement would time ``StrohsackClient.respond()`` with a fact
store directly — its round-trips are structural: 1 for a normal/recall turn, 2
when ``remember()`` fires.)

The builtin memory tool makes a turn pricier than a plain single call: the SDK
injects memory instructions into the system prompt on *every* request, and a turn
where Strohsack actually reads his notes is ~2 API round-trips instead of 1 (a
``tool_use`` hop to ``view /memories``, then the real reply; a write adds a 3rd).
This script measures that cost empirically.

It drives ``client.beta.messages.tool_runner`` directly with the builtin tool and
iterates the loop by hand so it can count round-trips and time each one. A
throwaway temp directory stands in for ``data/memories/`` so a benchmark run
never touches your real memory.

This is NOT a pytest test: it hits the live API, costs money, and is timing-
sensitive. Run it deliberately, with a real key in the environment:

    python scripts/bench_memory.py                 # all scenarios, 5 trials each
    python scripts/bench_memory.py --trials 10
    python scripts/bench_memory.py --scenario cold  # just the cold-read path
    python scripts/bench_memory.py --stream         # also measure streaming TTFT
    python scripts/bench_memory.py --keep           # don't delete the temp memory dir

Methodology baked in (see the conversation that motivated this):
  * one warm-up turn is run and discarded (TLS/connection setup is not
    representative);
  * each scenario runs N trials; we report median + min/max, not a single sample,
    because network jitter to the API is large;
  * the seed memory file is held fixed across trials so token count doesn't drift
    (the ``teach`` scenario, which writes, is re-seeded before every trial);
  * for streaming we measure time-to-first-token specifically — that's the
    latency a user actually feels.
"""

from __future__ import annotations

import argparse
import dataclasses
import shutil
import statistics
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# Allow running directly (python scripts/bench_memory.py) without install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

REPORTS_DIR = Path(__file__).resolve().parents[1] / "bench_reports"

from anthropic import Anthropic  # noqa: E402
from anthropic.lib.tools._beta_builtin_memory_tool import (  # noqa: E402
    BetaLocalFilesystemMemoryTool,
)

from strohsack.utils.config_loader import Config, ConfigError, load_config  # noqa: E402

# A realistic, in-voice seed for the populated scenarios. Held fixed across
# trials so input-token count stays constant (file size confounds the
# comparison otherwise).
# Experimental instruction appended to the system prompt when --nudge is set.
# Tests whether a prompt-level hint can suppress the tool's server-side default
# of reading /memories on every turn. Kept here (not in the real prompt file) so
# the experiment doesn't mutate Strohsack's actual persona.
NUDGE_INSTRUCTION = """\
## A note on your notes
You keep notes in /memories, but you don't need to check them every single time.
Only glance at them when the human refers to something from a past chat, asks what
you remember, or tells you something worth writing down. For ordinary back-and-forth,
just reply — no need to go rummaging through your notes first."""

SEED_MEMORY = """\
# What I know about this human

- Name: Yingzhi
- Builds me (Strohsack) — a software engineer, likes things explained plainly.
- Favourite honey talk: oak-blossom honey, the dark kind.
- Recurring theme: keeps asking about my memory and how much it costs me.
- Inside joke: pretends to be offended when I call myself lazy.
"""


@dataclasses.dataclass
class Scenario:
    """One thing to measure.

    Attributes:
        key: Short cli-friendly name.
        label: Human-readable description for the report.
        seed: Memory file contents to plant before the turn, or None for an
            empty memory directory.
        messages: The conversation history to send (ends with a user turn).
        reseed_each_trial: Reset the memory dir to ``seed`` before every trial.
            Needed for turns that write (otherwise trial 2 sees trial 1's notes).
    """

    key: str
    label: str
    seed: str | None
    messages: list[dict[str, str]]
    reseed_each_trial: bool = False


def build_scenarios() -> list[Scenario]:
    """The four cost regimes worth isolating (see the project plan, 2C)."""
    return [
        Scenario(
            key="plain",
            label="Plain chat, empty memory (baseline — does he even read?)",
            seed=None,
            messages=[{"role": "user", "content": "Morning, Strohsack! Sleep well?"}],
        ),
        Scenario(
            key="cold",
            label="Cold session, populated memory (the expensive read path)",
            seed=SEED_MEMORY,
            messages=[{"role": "user", "content": "Hey Strohsack, remember me?"}],
        ),
        Scenario(
            key="midsession",
            label="Mid-session follow-up (memory likely already in context)",
            seed=SEED_MEMORY,
            messages=[
                {"role": "user", "content": "Hey Strohsack, remember me?"},
                {"role": "assistant", "content": "Strohsack never forgets a honey friend. Yingzhi, yes?"},
                {"role": "user", "content": "Right. What kind of honey did I say I liked?"},
            ],
        ),
        Scenario(
            key="teach",
            label="Turn that teaches him something (read + write, worst case)",
            seed=SEED_MEMORY,
            messages=[
                {
                    "role": "user",
                    "content": "Quick update for your notes: I just adopted a cat named Biscuit.",
                }
            ],
            reseed_each_trial=True,
        ),
    ]


def seed_memory_dir(base: Path, seed: str | None) -> BetaLocalFilesystemMemoryTool:
    """Return a memory tool over a freshly-prepared ``{base}/memories`` dir.

    Wipes any existing ``memories/`` under ``base`` first, then plants ``seed``
    as ``user.md`` if given. The tool's constructor (re)creates the directory.
    """
    memories = base / "memories"
    if memories.exists():
        shutil.rmtree(memories)
    tool = BetaLocalFilesystemMemoryTool(base_path=str(base))
    if seed is not None:
        (tool.memory_root / "user.md").write_text(seed, encoding="utf-8")
    return tool


@dataclasses.dataclass
class TurnResult:
    """Outcome of one measured turn."""

    total_s: float
    # (elapsed_at_completion, stop_reason, [tool names used]) per API call.
    calls: list[tuple[float, str | None, list[str]]]

    @property
    def round_trips(self) -> int:
        return len(self.calls)

    @property
    def read_memory(self) -> bool:
        return any(tools for _, _, tools in self.calls)


def run_turn(
    client: Anthropic,
    config: Config,
    memory_tool: BetaLocalFilesystemMemoryTool,
    messages: list[dict[str, str]],
) -> TurnResult:
    """Run one non-streaming turn, timing and counting each API round-trip."""
    t0 = time.perf_counter()
    runner = client.beta.messages.tool_runner(
        model=config.model,
        max_tokens=config.max_tokens,
        system=config.system_prompt,
        messages=messages,
        tools=[memory_tool],
    )
    calls: list[tuple[float, str | None, list[str]]] = []
    for msg in runner:
        elapsed = time.perf_counter() - t0
        tool_names = [
            getattr(b, "name", "?")
            for b in msg.content
            if getattr(b, "type", None) == "tool_use"
        ]
        calls.append((elapsed, msg.stop_reason, tool_names))
    return TurnResult(total_s=time.perf_counter() - t0, calls=calls)


def run_turn_streaming(
    client: Anthropic,
    config: Config,
    memory_tool: BetaLocalFilesystemMemoryTool,
    messages: list[dict[str, str]],
) -> tuple[float, float]:
    """Run one streaming turn; return ``(time_to_first_token_s, total_s)``.

    Time-to-first-token is the perceived latency: on a memory-reading turn the
    first visible chunk only arrives after the second API call has started, so
    this captures the real UX cost of the tool hop.
    """
    t0 = time.perf_counter()
    ttft: float | None = None
    runner = client.beta.messages.tool_runner(
        model=config.model,
        max_tokens=config.max_tokens,
        system=config.system_prompt,
        messages=messages,
        tools=[memory_tool],
        stream=True,
    )
    for stream in runner:
        for chunk in stream.text_stream:
            if chunk and ttft is None:
                ttft = time.perf_counter() - t0
    total = time.perf_counter() - t0
    return (ttft if ttft is not None else total), total


def fmt_calls(result: TurnResult) -> str:
    """One-line breakdown of a turn's round-trips."""
    parts = []
    for i, (elapsed, stop, tools) in enumerate(result.calls, start=1):
        tag = f"{stop}" + (f"[{','.join(tools)}]" if tools else "")
        parts.append(f"call{i} {tag} {elapsed:.2f}s")
    return ", ".join(parts)


def report_scenario(label: str, results: list[TurnResult]) -> None:
    """Print the per-scenario summary block."""
    totals = sorted(r.total_s for r in results)
    trips = [r.round_trips for r in results]
    reads = sum(1 for r in results if r.read_memory)
    print(f"\n  {label}")
    print(
        f"    total latency : median {statistics.median(totals):.2f}s  "
        f"(min {totals[0]:.2f}s, max {totals[-1]:.2f}s)"
    )
    print(
        f"    round-trips   : median {int(statistics.median(trips))}  "
        f"(min {min(trips)}, max {max(trips)})"
    )
    print(f"    read memory   : {reads}/{len(results)} turns")


@dataclasses.dataclass
class ScenarioRun:
    """Everything measured for one scenario, kept for the report artifact."""

    scenario: Scenario
    results: list[TurnResult]
    stream_ttft_s: float | None = None
    stream_total_s: float | None = None


def render_report(config: Config, trials: int, runs: list[ScenarioRun], *, nudge: bool) -> str:
    """Render a Markdown benchmark report (mirrors the eval report style)."""
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Strohsack Memory-Latency Benchmark",
        "",
        f"- **When:** {stamp}",
        f"- **Model:** {config.model}",
        f"- **max_tokens:** {config.max_tokens}",
        f"- **Trials per scenario:** {trials}",
        f"- **Nudge (don't-re-read hint):** {'on' if nudge else 'off'}",
        "",
        "Each turn drives the agentic memory tool loop; a `tool_use` hop "
        "(`view`/`str_replace`) is one extra API round-trip on top of the final reply.",
        "",
        "## Summary",
        "",
        "| Scenario | Median total | Min–Max | Round-trips | Read memory |",
        "|---|---|---|---|---|",
    ]
    for run in runs:
        totals = sorted(r.total_s for r in run.results)
        trips = [r.round_trips for r in run.results]
        reads = sum(1 for r in run.results if r.read_memory)
        lines.append(
            f"| {run.scenario.label} "
            f"| {statistics.median(totals):.2f}s "
            f"| {totals[0]:.2f}–{totals[-1]:.2f}s "
            f"| {int(statistics.median(trips))} (min {min(trips)}, max {max(trips)}) "
            f"| {reads}/{len(run.results)} |"
        )

    has_stream = any(r.stream_ttft_s is not None for r in runs)
    if has_stream:
        lines += ["", "## Streaming (time-to-first-token)", "",
                  "| Scenario | First token | Full reply |", "|---|---|---|"]
        for run in runs:
            if run.stream_ttft_s is not None:
                lines.append(
                    f"| {run.scenario.label} | {run.stream_ttft_s:.2f}s | {run.stream_total_s:.2f}s |"
                )

    lines += ["", "## Per-scenario detail", ""]
    for run in runs:
        lines.append(f"### {run.scenario.label}")
        lines.append("")
        for i, r in enumerate(run.results, start=1):
            lines.append(f"- trial {i}: {r.round_trips} call(s), {r.total_s:.2f}s — {fmt_calls(r)}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Strohsack's memory-tool latency.")
    parser.add_argument("--trials", type=int, default=5, help="Timed turns per scenario (default 5).")
    parser.add_argument(
        "--scenario",
        default="all",
        choices=["all", "plain", "cold", "midsession", "teach"],
        help="Which scenario to run (default all).",
    )
    parser.add_argument("--model", default=None, help="Override the configured model id.")
    parser.add_argument(
        "--nudge",
        action="store_true",
        help="Append a 'don't re-read unless needed' instruction to the system prompt "
        "(tests whether a prompt hint can suppress the every-turn read).",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Also measure streaming time-to-first-token (extra API calls).",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the temp memory directory instead of deleting it.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the report to this exact path instead of the default bench_reports/ artifact.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Don't write a report artifact (print only).",
    )
    args = parser.parse_args()

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    if args.model:
        config = dataclasses.replace(config, model=args.model)
    if args.nudge:
        config = dataclasses.replace(
            config, system_prompt=config.system_prompt + "\n\n" + NUDGE_INSTRUCTION
        )

    client = Anthropic(api_key=config.api_key)
    scenarios = build_scenarios()
    if args.scenario != "all":
        scenarios = [s for s in scenarios if s.key == args.scenario]

    workdir = Path(tempfile.mkdtemp(prefix="strohsack-bench-"))
    print("=" * 70)
    print(f"  Strohsack memory-latency benchmark")
    print(
        f"  model={config.model}  max_tokens={config.max_tokens}  "
        f"trials={args.trials}  nudge={'on' if args.nudge else 'off'}"
    )
    print(f"  temp memory dir: {workdir}")
    print("=" * 70)

    try:
        # Warm-up: one throwaway turn so TLS/connection setup isn't counted.
        print("\nWarming up (discarded)...", flush=True)
        warm_tool = seed_memory_dir(workdir, None)
        run_turn(client, config, warm_tool, [{"role": "user", "content": "hi"}])

        runs: list[ScenarioRun] = []
        for scenario in scenarios:
            print(f"\n[{scenario.key}] {scenario.label}")
            results: list[TurnResult] = []
            # When the turn doesn't write, seed once and reuse; otherwise reset
            # before each trial so every trial starts from the same notes.
            tool = seed_memory_dir(workdir, scenario.seed)
            for i in range(1, args.trials + 1):
                if scenario.reseed_each_trial:
                    tool = seed_memory_dir(workdir, scenario.seed)
                result = run_turn(client, config, tool, list(scenario.messages))
                results.append(result)
                print(
                    f"    trial {i}/{args.trials}: {result.round_trips} call(s), "
                    f"{result.total_s:.2f}s total  ({fmt_calls(result)})",
                    flush=True,
                )

            run = ScenarioRun(scenario=scenario, results=results)
            if args.stream:
                tool = seed_memory_dir(workdir, scenario.seed)
                run.stream_ttft_s, run.stream_total_s = run_turn_streaming(
                    client, config, tool, list(scenario.messages)
                )
                print(
                    f"    streaming   : first token {run.stream_ttft_s:.2f}s, "
                    f"full reply {run.stream_total_s:.2f}s"
                )

            runs.append(run)
            report_scenario(scenario.label, results)

        print("\n" + "=" * 70)
        print("  Summary")
        print("=" * 70)
        print(
            "\n  Read the per-scenario blocks above. 'plain' is the floor (he still\n"
            "  views /memories even when empty); 'cold' adds the populated-read hops;\n"
            "  'midsession' shows whether he re-reads; 'teach' is the read+write worst\n"
            "  case. Re-run after enabling prompt caching (2C) to quantify the win."
        )

        if not args.no_save:
            report = render_report(config, args.trials, runs, nudge=args.nudge)
            if args.out is not None:
                out_path = args.out
                out_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                REPORTS_DIR.mkdir(exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                tag = "-nudge" if args.nudge else ""
                out_path = REPORTS_DIR / f"bench-{stamp}{tag}.md"
            out_path.write_text(report, encoding="utf-8")
            print(f"\n  Report saved to: {out_path}")

        return 0
    finally:
        if args.keep:
            print(f"\nKept temp memory dir: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
