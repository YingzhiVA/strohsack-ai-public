"""
End-to-end personality evaluation runner.

Loads the probe set, drives each probe through a responder (Strohsack), judges
each reply against the rubric, and aggregates the results into an
:class:`EvalReport`. Depends only on the ``Responder`` and ``Judge`` protocols,
so it runs fully offline in tests with stubs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..conversation.manager import Responder
from .judge import Judge, Verdict
from .rubric import TRAIT_KEYS

DEFAULT_PROBES_PATH = Path(__file__).resolve().parent / "probes.yaml"


@dataclass(frozen=True)
class Probe:
    """A single evaluation prompt."""

    id: str
    category: str
    prompt: str
    targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProbeResult:
    """The reply and verdict for one probe.

    On a failed probe (the responder or judge raised), ``reply`` holds
    whatever was obtained (often ""), ``verdict`` is None, and ``error``
    holds the failure message. Failed probes are excluded from score
    averages but reported separately.
    """

    probe: Probe
    reply: str
    verdict: Verdict | None
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.verdict is None


@dataclass
class EvalReport:
    """Aggregated results across all probes.

    Rates and averages are computed over the SCORED probes only; failed
    probes (responder/judge raised) are counted in ``failures`` but excluded
    from the score statistics so a transient error doesn't masquerade as a
    bad score.

    Attributes:
        results: Per-probe results, in probe order (includes failures).
        in_character_rate: Fraction of SCORED replies that met the threshold.
        trait_averages: Mean score per trait across SCORED probes.
        overall_average: Mean overall score across SCORED probes.
        failures: Number of probes that errored out.
    """

    results: list[ProbeResult] = field(default_factory=list)
    in_character_rate: float = 0.0
    trait_averages: dict[str, float] = field(default_factory=dict)
    overall_average: float = 0.0
    failures: int = 0

    def worst(self, n: int = 5) -> list[ProbeResult]:
        """The ``n`` most-concerning SCORED results, worst first.

        Critical failures sort ahead of everything else (even a high mean can't
        excuse breaking a hard rule), then by ascending overall score.
        """
        scored = [r for r in self.results if not r.failed]
        return sorted(
            scored, key=lambda r: (not r.verdict.critical_failure, r.verdict.overall)
        )[:n]


def load_probes(path: Path | None = None) -> list[Probe]:
    """Load and validate the probe set from YAML.

    Raises:
        ValueError: If the file has no probes or a probe is missing fields.
    """
    probes_path = path or DEFAULT_PROBES_PATH
    data = yaml.safe_load(probes_path.read_text(encoding="utf-8"))
    raw_probes = (data or {}).get("probes")
    if not raw_probes:
        raise ValueError(f"No probes found in {probes_path}")

    probes: list[Probe] = []
    for entry in raw_probes:
        try:
            probes.append(
                Probe(
                    id=entry["id"],
                    category=entry["category"],
                    prompt=entry["prompt"],
                    targets=tuple(entry.get("targets", ())),
                )
            )
        except KeyError as exc:
            raise ValueError(f"Probe missing required field {exc}: {entry!r}") from exc
    return probes


def run_eval(
    responder: Responder,
    judge: Judge,
    probes: list[Probe] | None = None,
) -> EvalReport:
    """Run every probe through the responder and judge, then aggregate.

    Each probe is sent as a fresh single-turn conversation (no carryover
    between probes), so results are independent.

    Args:
        responder: Produces Strohsack's reply to a message history.
        judge: Scores each (probe, reply) pair.
        probes: Probe set; loaded from the default file when omitted.
    """
    probe_list = probes if probes is not None else load_probes()

    results: list[ProbeResult] = []
    for probe in probe_list:
        # Isolate each probe: a single transient failure (network, rate limit,
        # unparseable judge output) records an error and continues rather than
        # aborting the whole run and discarding the probes already paid for.
        reply = ""
        try:
            reply = responder.respond([{"role": "user", "content": probe.prompt}])
            verdict = judge.score(probe.prompt, reply, probe.targets)
        except Exception as exc:  # noqa: BLE001 - eval must survive any probe failure
            results.append(
                ProbeResult(probe=probe, reply=reply, verdict=None, error=str(exc))
            )
            continue
        results.append(ProbeResult(probe=probe, reply=reply, verdict=verdict))

    return _aggregate(results)


def _aggregate(results: list[ProbeResult]) -> EvalReport:
    failures = sum(1 for r in results if r.failed)
    scored = [r for r in results if not r.failed]

    if not scored:
        return EvalReport(results=results, failures=failures)

    n = len(scored)
    in_character = sum(1 for r in scored if r.verdict.in_character)
    overall_avg = sum(r.verdict.overall for r in scored) / n

    trait_averages = {
        key: sum(r.verdict.scores.get(key, 0.0) for r in scored) / n for key in TRAIT_KEYS
    }

    return EvalReport(
        results=results,
        in_character_rate=in_character / n,
        trait_averages=trait_averages,
        overall_average=overall_avg,
        failures=failures,
    )


def format_report(report: EvalReport, *, worst_n: int = 5) -> str:
    """Render an :class:`EvalReport` as a human-readable markdown summary."""
    scored = len(report.results) - report.failures
    lines = ["# Strohsack Personality Eval", ""]
    lines.append(f"- **Probes:** {len(report.results)} ({scored} scored, {report.failures} failed)")
    lines.append(f"- **In-character rate:** {report.in_character_rate:.0%}")
    lines.append(f"- **Overall average:** {report.overall_average:.2f}")
    lines.append("")
    lines.append("## Trait averages")
    for key in TRAIT_KEYS:
        avg = report.trait_averages.get(key, 0.0)
        lines.append(f"- {key}: {avg:.2f}")
    lines.append("")
    lines.append(f"## Worst {worst_n} responses")
    for result in report.worst(worst_n):
        lines.append("")
        flag = " ⛔ CRITICAL FAIL" if result.verdict.critical_failure else ""
        lines.append(f"### `{result.probe.id}` ({result.verdict.overall:.2f}){flag}")
        lines.append(f"- **Probe:** {result.probe.prompt}")
        lines.append(f"- **Reply:** {result.reply}")
        if result.verdict.reasoning:
            lines.append(f"- **Judge:** {result.verdict.reasoning}")

    if report.failures:
        lines.append("")
        lines.append("## Failed probes")
        for result in report.results:
            if result.failed:
                lines.append(f"- `{result.probe.id}`: {result.error}")
    return "\n".join(lines)
