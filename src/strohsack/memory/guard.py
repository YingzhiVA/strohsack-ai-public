"""
Deterministic never-store guard for durable facts (Milestone 2.5-lite).

The never-store policy (docs/architecture/safety.md) is enforced in two tiers:
the model is the first filter (the ``remember()`` tool description carries the
policy), and this module is the deterministic backstop for the subset a pattern
can actually recognize — credentials and card/account/identity numbers
(safety.md categories 4-5). The judgment categories (secrets, third parties,
health, routine, distress) cannot be pattern-matched and stay model-tier,
covered by eval probes instead.

The guard runs in the write path, before a fact is persisted. It is
deliberately narrow: a false positive blocks a charming fact, so every pattern
requires a value-shaped string, not just a scary keyword — "always forgets her
password" must pass; "her password is hunter2" must not.
"""

from __future__ import annotations

import re

# Credential keyword followed (closely, within the same clause) by an
# assignment: "password is hunter2", "PIN: 1234", "the wifi code = ...".
_CREDENTIAL_RE = re.compile(
    r"\b(?:password|passcode|passwort|pin|otp|api key|secret key|"
    r"(?:verification|security|access|login|unlock|wifi) code)\b"
    r"[^.,;!?]{0,20}?(?:\bis\b|[:=])\s*\S",
    re.IGNORECASE,
)

# IBAN-shaped: country code + 2 check digits + 10 or more alphanumerics,
# spaces allowed between groups ("CH93 0076 2011 6238 5295 7").
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Za-z0-9]){10,}\b")

# Key/token-shaped: one long unbroken run of identifier characters that
# contains at least one digit (API keys, tokens, serials). The digit
# requirement keeps long ordinary words — German compounds — legal.
_TOKEN_RE = re.compile(r"(?=[A-Za-z_\-]*\d)[A-Za-z0-9_\-]{24,}")

# Card/account/phone/ID-shaped: 10 or more digits once grouping spaces and
# dashes are removed. The threshold keeps dates (8 digits) and years legal
# while catching card numbers (13-19 digits), phone numbers, and
# AHV/passport-length identifiers.
_DIGIT_RUN_RE = re.compile(r"\d(?:[ \-]?\d){9,}")


def never_store_reason(note: str) -> str | None:
    """Why ``note`` must never be persisted as a durable fact, or ``None``.

    Backstop for safety.md categories 4-5 only (credentials and money,
    government/identity numbers) — the categories with recognizable shapes.
    A ``None`` result does NOT mean the note is safe to store, only that no
    hard pattern matched; the judgment categories are the model's job.

    Args:
        note: The fact text the model asked to save.

    Returns:
        A short human-readable reason suitable for the tool result (so the
        model can voice the refusal in character), or ``None`` to allow.
    """
    if _CREDENTIAL_RE.search(note):
        return "it looks like a password or access code"
    if _TOKEN_RE.search(note):
        return "it looks like a key or access token"
    if _IBAN_RE.search(note) or _DIGIT_RUN_RE.search(note):
        return "it looks like a card, account, phone, or ID number"
    return None
