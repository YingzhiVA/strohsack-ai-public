"""
LLM-as-judge scoring for Strohsack personality consistency.

The judge takes a (probe, reply) pair and scores the reply against the trait
rubric, returning structured per-trait scores plus an overall verdict. The
concrete :class:`LLMJudge` calls Claude; the :class:`Judge` Protocol lets the
runner be tested with a stub (no live API).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from anthropic import Anthropic, APIError

from ..utils.config_loader import Config
from .rubric import (
    CRITICAL_FLOOR,
    CRITICAL_TRAIT_KEYS,
    IN_CHARACTER_THRESHOLD,
    TARGET_WEIGHT,
    TRAIT_KEYS,
    rubric_text,
)


class JudgeError(Exception):
    """Raised when the judge call fails or returns unparseable output."""


@dataclass(frozen=True)
class Verdict:
    """A judge's assessment of a single reply.

    Attributes:
        scores: Per-trait score in 0.0–1.0, keyed by trait key.
        overall: Targets-weighted mean of the trait scores.
        reasoning: Short free-text justification from the judge.
        critical_failure: True if a critical trait scored below the floor.
        in_character: Whether the reply counts as in character.
    """

    scores: dict[str, float]
    overall: float
    reasoning: str
    critical_failure: bool = False

    @property
    def in_character(self) -> bool:
        """In character iff the weighted overall clears the threshold AND no
        critical trait (e.g. never_mean) fell below the floor."""
        return self.overall >= IN_CHARACTER_THRESHOLD and not self.critical_failure

    @classmethod
    def from_scores(
        cls,
        scores: dict[str, float],
        reasoning: str,
        targets: "tuple[str, ...] | None" = None,
    ) -> "Verdict":
        """Build a Verdict from raw per-trait scores.

        ``overall`` is a weighted mean: traits named in ``targets`` (the ones
        the probe was designed to exercise) count ``TARGET_WEIGHT`` times more
        than untargeted traits, so dimensions the situation didn't call for
        (which the judge scores ~1.0) don't dominate the result. With no
        targets it falls back to a plain mean.

        Any critical trait scoring below ``CRITICAL_FLOOR`` flags a
        ``critical_failure``, which forces ``in_character`` to False.
        """
        if not scores:
            raise JudgeError("Judge returned no trait scores.")

        target_set = set(targets or ())
        weighted_sum = 0.0
        weight_total = 0.0
        for key, value in scores.items():
            weight = TARGET_WEIGHT if key in target_set else 1.0
            weighted_sum += value * weight
            weight_total += weight
        overall = weighted_sum / weight_total

        critical_failure = any(
            scores.get(key, 0.0) < CRITICAL_FLOOR for key in CRITICAL_TRAIT_KEYS
        )

        return cls(
            scores=scores,
            overall=overall,
            reasoning=reasoning,
            critical_failure=critical_failure,
        )


class Judge(Protocol):
    """Anything that can score a reply against the rubric.

    ``targets`` names the trait keys the probe was designed to exercise; the
    scorer weights those traits more heavily in the overall. It is optional so
    simple stubs can ignore it.
    """

    def score(
        self, probe: str, reply: str, targets: "tuple[str, ...] | None" = None
    ) -> Verdict: ...


JUDGE_SYSTEM_PROMPT = f"""You are a strict but fair evaluator of an AI character named Strohsack — a chubby, lazy, honey-obsessed brown bear. You will be given a user message (the "probe") and Strohsack's reply. Score how well the reply stays in character against this rubric.

Each dimension is scored from 0.0 (completely fails) to 1.0 (perfectly in character):

{rubric_text()}

Important judging notes:
- Score only against the rubric, not your own taste.
- A dimension that is simply not relevant to this particular reply should be scored near 1.0 (don't penalize a reply for not exercising a trait the situation didn't call for) UNLESS the situation clearly called for it and it was absent.
- Be lenient on third_person and honey_obsession for very short, situationally-appropriate replies.

Respond with ONLY a JSON object, no prose before or after, in exactly this shape:
{{
  "scores": {{ {", ".join(f'"{k}": <0.0-1.0>' for k in TRAIT_KEYS)} }},
  "reasoning": "<one or two sentences explaining the key deductions>"
}}"""


class LLMJudge:
    """Scores replies by calling Claude with the rubric as its system prompt.

    Reuses the application :class:`Config` for the API key and model, but uses
    its own (rubric) system prompt rather than Strohsack's persona.

    Args:
        config: Resolved settings (provides api_key and model).
        max_tokens: Token budget for the judge's JSON response.
    """

    def __init__(self, config: Config, max_tokens: int = 512) -> None:
        self._model = config.model
        self._max_tokens = max_tokens
        self._client = Anthropic(api_key=config.api_key)

    def score(
        self, probe: str, reply: str, targets: "tuple[str, ...] | None" = None
    ) -> Verdict:
        user_content = (
            f"PROBE (user said):\n{probe}\n\n"
            f"STROHSACK'S REPLY:\n{reply}\n\n"
            "Score the reply now."
        )
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=JUDGE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}],
            )
        except APIError as exc:
            raise JudgeError(f"Judge API request failed: {exc}") from exc

        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        return parse_verdict(text, targets)


def _extract_json_object(raw: str) -> dict:
    """Extract the first valid JSON object from possibly-noisy model output.

    Tolerates markdown fences, leading prose, and trailing prose — including
    trailing text that itself contains braces. Works by trying to decode a
    JSON value starting at each ``{`` and returning the first one that parses
    as an object (``raw_decode`` ignores any trailing content after the value).

    Raises:
        JudgeError: If no parseable JSON object is found.
    """
    decoder = json.JSONDecoder()
    for start in (i for i, ch in enumerate(raw) if ch == "{"):
        try:
            value, _ = decoder.raw_decode(raw, start)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise JudgeError(f"No JSON object found in judge output: {raw!r}")


def parse_verdict(raw: str, targets: "tuple[str, ...] | None" = None) -> Verdict:
    """Parse the judge's JSON output into a :class:`Verdict`.

    Tolerates the model wrapping the JSON in markdown fences or prose (before
    or after the object, even prose containing braces). ``targets`` is passed
    through to weight the overall toward the probe's intended traits.

    Raises:
        JudgeError: If no JSON object is found, scores are missing/invalid,
            or a required trait is absent.
    """
    data = _extract_json_object(raw)

    raw_scores = data.get("scores")
    if not isinstance(raw_scores, dict):
        raise JudgeError(f"Judge output missing 'scores' object: {data!r}")

    scores: dict[str, float] = {}
    for key in TRAIT_KEYS:
        if key not in raw_scores:
            raise JudgeError(f"Judge output missing score for trait {key!r}: {data!r}")
        try:
            value = float(raw_scores[key])
        except (TypeError, ValueError) as exc:
            raise JudgeError(f"Score for {key!r} is not a number: {raw_scores[key]!r}") from exc
        # Clamp into range rather than rejecting slightly-off values.
        scores[key] = max(0.0, min(1.0, value))

    reasoning = str(data.get("reasoning", "")).strip()
    return Verdict.from_scores(scores, reasoning, targets)
