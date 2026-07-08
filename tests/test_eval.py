"""Offline tests for the personality eval harness (no live API).

Exercises the harness machinery — probe loading, judge-output parsing, the run
loop, and aggregation — using stubs in place of the real Strohsack client and
LLM judge. The live scored eval lives in scripts/run_personality_eval.py.
"""

from __future__ import annotations

import pytest

from strohsack.eval.judge import JudgeError, Verdict, parse_verdict
from strohsack.eval.rubric import CRITICAL_TRAIT_KEYS, TARGET_WEIGHT, TRAIT_KEYS
from strohsack.eval.runner import (
    Probe,
    format_report,
    load_probes,
    run_eval,
)


def _full_scores(value: float) -> dict[str, float]:
    return {key: value for key in TRAIT_KEYS}


# --- Probe loading ---------------------------------------------------------


def test_load_bundled_probes() -> None:
    probes = load_probes()
    assert len(probes) >= 15
    assert all(p.id and p.prompt and p.category for p in probes)
    # ids must be unique
    ids = [p.id for p in probes]
    assert len(ids) == len(set(ids))


def test_load_probes_rejects_empty(tmp_path) -> None:
    empty = tmp_path / "empty.yaml"
    empty.write_text("probes: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="No probes"):
        load_probes(empty)


def test_load_probes_rejects_missing_field(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("probes:\n  - id: x\n    category: greeting\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required field"):
        load_probes(bad)


# --- Verdict parsing -------------------------------------------------------


def test_parse_clean_json() -> None:
    raw = (
        '{"scores": {'
        + ", ".join(f'"{k}": 0.8' for k in TRAIT_KEYS)
        + '}, "reasoning": "solid"}'
    )
    verdict = parse_verdict(raw)
    assert verdict.overall == pytest.approx(0.8)
    assert verdict.reasoning == "solid"
    assert verdict.in_character is True


def test_parse_json_wrapped_in_markdown_and_prose() -> None:
    body = ", ".join(f'"{k}": 0.5' for k in TRAIT_KEYS)
    raw = f"Here is my assessment:\n```json\n{{\"scores\": {{{body}}}, \"reasoning\": \"meh\"}}\n```"
    verdict = parse_verdict(raw)
    assert verdict.overall == pytest.approx(0.5)
    assert verdict.in_character is False  # 0.5 < 0.7 threshold


def test_parse_json_with_trailing_prose_containing_braces() -> None:
    # Regression: greedy first-{-to-last-} matching used to swallow the trailing
    # brace and produce invalid JSON. The valid object must still be extracted.
    body = ", ".join(f'"{k}": 0.8' for k in TRAIT_KEYS)
    raw = f'{{"scores": {{{body}}}, "reasoning": "good"}}\n\nNote: the {{honey}} dimension was light.'
    verdict = parse_verdict(raw)
    assert verdict.overall == pytest.approx(0.8)
    assert verdict.reasoning == "good"


def test_parse_json_with_leading_prose_containing_braces() -> None:
    # A stray brace in leading prose must not derail extraction of the real object.
    body = ", ".join(f'"{k}": 0.9' for k in TRAIT_KEYS)
    raw = f'Scoring {{like this}}:\n{{"scores": {{{body}}}, "reasoning": "ok"}}'
    verdict = parse_verdict(raw)
    assert verdict.overall == pytest.approx(0.9)


def test_parse_clamps_out_of_range_scores() -> None:
    body = ", ".join(f'"{k}": 1.5' for k in TRAIT_KEYS)
    verdict = parse_verdict(f'{{"scores": {{{body}}}, "reasoning": ""}}')
    assert all(v == 1.0 for v in verdict.scores.values())


def test_parse_rejects_non_json() -> None:
    with pytest.raises(JudgeError, match="No JSON"):
        parse_verdict("the bear was great, 10/10")


def test_parse_rejects_missing_targeted_trait() -> None:
    # Drop one trait from the scores; the probe TARGETS it, so the omission is
    # the very score the probe exists for — still a hard error.
    missing = TRAIT_KEYS[-1]
    partial = ", ".join(f'"{k}": 0.9' for k in TRAIT_KEYS[:-1])
    with pytest.raises(JudgeError, match="missing score"):
        parse_verdict(f'{{"scores": {{{partial}}}, "reasoning": ""}}', targets=(missing,))


def test_parse_defaults_missing_untargeted_trait_to_one() -> None:
    # The judge occasionally drops a key it deemed irrelevant. For an
    # UNTARGETED trait that means "not exercised" (rubric convention: ~1.0),
    # so the probe is kept rather than discarded.
    partial = ", ".join(f'"{k}": 0.9' for k in TRAIT_KEYS[:-1])
    verdict = parse_verdict(f'{{"scores": {{{partial}}}, "reasoning": ""}}')
    assert verdict.scores[TRAIT_KEYS[-1]] == 1.0


def test_parse_rejects_non_numeric_score() -> None:
    body = ", ".join(
        f'"{k}": ' + ('"high"' if i == 0 else "0.9") for i, k in enumerate(TRAIT_KEYS)
    )
    with pytest.raises(JudgeError, match="not a number"):
        parse_verdict(f'{{"scores": {{{body}}}, "reasoning": ""}}')


# --- Critical-trait hard-fail gate -----------------------------------------


def _scores_with(overrides: dict[str, float], base: float = 0.95) -> dict[str, float]:
    scores = {k: base for k in TRAIT_KEYS}
    scores.update(overrides)
    return scores


def test_critical_trait_below_floor_fails_despite_high_mean() -> None:
    # never_mean is critical: a cruel reply must NOT pass even if every other
    # trait is near-perfect (which would otherwise average well above 0.7).
    critical = CRITICAL_TRAIT_KEYS[0]
    verdict = Verdict.from_scores(_scores_with({critical: 0.0}), reasoning="cruel")
    assert verdict.critical_failure is True
    assert verdict.in_character is False
    assert verdict.overall > 0.7  # the mean alone would have passed


def test_critical_trait_at_floor_passes() -> None:
    critical = CRITICAL_TRAIT_KEYS[0]
    verdict = Verdict.from_scores(_scores_with({critical: 0.5}), reasoning="ok")
    assert verdict.critical_failure is False
    assert verdict.in_character is True


def test_noncritical_trait_low_does_not_hard_fail() -> None:
    # A low non-critical trait only affects the mean, not the gate.
    noncritical = next(k for k in TRAIT_KEYS if k not in CRITICAL_TRAIT_KEYS)
    verdict = Verdict.from_scores(_scores_with({noncritical: 0.0}), reasoning="meh")
    assert verdict.critical_failure is False


# --- Targets weighting -----------------------------------------------------


def test_targets_weight_overall_toward_targeted_traits() -> None:
    # One targeted trait scores high, everything else scores low. With weighting,
    # the targeted trait pulls overall up vs. an unweighted mean.
    target = TRAIT_KEYS[0]
    scores = _scores_with({target: 1.0}, base=0.0)  # only the target is 1.0

    weighted = Verdict.from_scores(scores, reasoning="", targets=(target,))
    unweighted = Verdict.from_scores(scores, reasoning="")

    n = len(TRAIT_KEYS)
    # unweighted: one 1.0 among n zeros
    assert unweighted.overall == pytest.approx(1.0 / n)
    # weighted: target counts TARGET_WEIGHT times
    assert weighted.overall == pytest.approx(TARGET_WEIGHT / (TARGET_WEIGHT + (n - 1)))
    assert weighted.overall > unweighted.overall


def test_targets_none_is_plain_mean() -> None:
    scores = _scores_with({TRAIT_KEYS[0]: 0.2}, base=0.8)
    verdict = Verdict.from_scores(scores, reasoning="")
    assert verdict.overall == pytest.approx(sum(scores.values()) / len(scores))


def test_parse_verdict_threads_targets() -> None:
    target = TRAIT_KEYS[0]
    body = ", ".join(f'"{k}": ' + ("1.0" if k == target else "0.0") for k in TRAIT_KEYS)
    raw = f'{{"scores": {{{body}}}, "reasoning": "x"}}'
    weighted = parse_verdict(raw, targets=(target,))
    plain = parse_verdict(raw)
    assert weighted.overall > plain.overall


# --- Run loop + aggregation (stubbed responder + judge) --------------------


class StubResponder:
    """Echoes a fixed reply and records the probes it saw."""

    def __init__(self, reply: str = "Honey!") -> None:
        self.reply = reply
        self.seen: list[str] = []

    def respond(self, messages: list[dict[str, str]]) -> str:
        self.seen.append(messages[-1]["content"])
        return self.reply


class ScriptedJudge:
    """Returns verdicts from a preset list of overall scores, in order."""

    def __init__(self, overalls: list[float]) -> None:
        self._overalls = list(overalls)
        self._i = 0

    def score(self, probe: str, reply: str, targets=None) -> Verdict:
        value = self._overalls[self._i]
        self._i += 1
        return Verdict.from_scores(_full_scores(value), reasoning="stub")


def _probes(n: int) -> list[Probe]:
    return [Probe(id=f"p{i}", category="test", prompt=f"prompt {i}") for i in range(n)]


def test_run_eval_drives_every_probe() -> None:
    responder = StubResponder()
    judge = ScriptedJudge([1.0, 1.0, 1.0])
    probes = _probes(3)

    report = run_eval(responder, judge, probes)

    assert len(report.results) == 3
    assert responder.seen == ["prompt 0", "prompt 1", "prompt 2"]


def test_run_eval_passes_probe_targets_to_judge() -> None:
    class RecordingJudge:
        def __init__(self) -> None:
            self.seen_targets: list = []

        def score(self, probe: str, reply: str, targets=None) -> Verdict:
            self.seen_targets.append(targets)
            return Verdict.from_scores(_full_scores(0.9), reasoning="")

    responder = StubResponder()
    judge = RecordingJudge()
    probes = [
        Probe(id="a", category="t", prompt="p", targets=("warmth", "brevity")),
        Probe(id="b", category="t", prompt="q", targets=()),
    ]
    run_eval(responder, judge, probes)
    assert judge.seen_targets == [("warmth", "brevity"), ()]


def test_run_eval_aggregates_rates_and_averages() -> None:
    responder = StubResponder()
    # Two in-character (>=0.7), two not.
    judge = ScriptedJudge([0.9, 0.8, 0.6, 0.2])
    report = run_eval(responder, judge, _probes(4))

    assert report.in_character_rate == pytest.approx(0.5)
    assert report.overall_average == pytest.approx((0.9 + 0.8 + 0.6 + 0.2) / 4)
    # All traits got the same value as overall in this stub.
    for key in TRAIT_KEYS:
        assert report.trait_averages[key] == pytest.approx(report.overall_average)


def test_worst_returns_lowest_first() -> None:
    responder = StubResponder()
    judge = ScriptedJudge([0.9, 0.1, 0.5])
    report = run_eval(responder, judge, _probes(3))

    worst = report.worst(2)
    assert [r.verdict.overall for r in worst] == pytest.approx([0.1, 0.5])


def test_format_report_includes_key_sections() -> None:
    responder = StubResponder()
    judge = ScriptedJudge([0.9, 0.4])
    report = run_eval(responder, judge, _probes(2))

    text = format_report(report)
    assert "In-character rate" in text
    assert "Trait averages" in text
    assert "Worst" in text


# --- Per-probe error recovery ----------------------------------------------


class FlakyResponder:
    """Raises on a chosen probe index, echoes otherwise."""

    def __init__(self, fail_on: int) -> None:
        self._fail_on = fail_on
        self._i = 0

    def respond(self, messages: list[dict[str, str]]) -> str:
        i = self._i
        self._i += 1
        if i == self._fail_on:
            raise RuntimeError("simulated API failure")
        return "Honey!"


class FlakyJudge:
    """Scores a fixed overall, but raises JudgeError on a chosen probe index."""

    def __init__(self, fail_on: int, overall: float = 0.9) -> None:
        self._fail_on = fail_on
        self._overall = overall
        self._i = 0

    def score(self, probe: str, reply: str, targets=None) -> Verdict:
        i = self._i
        self._i += 1
        if i == self._fail_on:
            raise JudgeError("simulated unparseable verdict")
        return Verdict.from_scores(_full_scores(self._overall), reasoning="stub")


def test_run_eval_continues_past_responder_failure() -> None:
    responder = FlakyResponder(fail_on=1)
    judge = ScriptedJudge([0.9, 0.9])  # only the 2 surviving probes are judged
    report = run_eval(responder, judge, _probes(3))

    assert len(report.results) == 3
    assert report.failures == 1
    failed = [r for r in report.results if r.failed]
    assert len(failed) == 1
    assert failed[0].probe.id == "p1"
    assert "simulated API failure" in failed[0].error


def test_run_eval_continues_past_judge_failure() -> None:
    responder = StubResponder()
    judge = FlakyJudge(fail_on=0)
    report = run_eval(responder, judge, _probes(3))

    assert report.failures == 1
    assert report.results[0].failed
    assert not report.results[1].failed


def test_failures_excluded_from_averages() -> None:
    # Probe 1 fails; the two scored probes are both 0.8. Averages must reflect
    # only the scored probes, not dilute toward 0 for the failure.
    responder = FlakyResponder(fail_on=1)
    judge = ScriptedJudge([0.8, 0.8])
    report = run_eval(responder, judge, _probes(3))

    assert report.failures == 1
    assert report.overall_average == pytest.approx(0.8)
    assert report.in_character_rate == pytest.approx(1.0)  # both scored are in-character


def test_all_probes_failing_yields_zero_rate_not_crash() -> None:
    responder = FlakyResponder(fail_on=0)
    # Every probe fails at the responder, so the judge is never reached.
    judge = ScriptedJudge([])
    report = run_eval(responder, judge, _probes(1))

    assert report.failures == 1
    assert report.in_character_rate == 0.0
    assert report.overall_average == 0.0


def test_format_report_lists_failures() -> None:
    responder = FlakyResponder(fail_on=0)
    judge = ScriptedJudge([0.9])
    report = run_eval(responder, judge, _probes(2))

    text = format_report(report)
    assert "Failed probes" in text
    assert "1 failed" in text
