"""Tests for strohsack.memory.guard — the deterministic never-store backstop.

The guard covers only the pattern-matchable never-store categories from
docs/architecture/safety.md (4: credentials and money, 5: identity numbers).
The judgment categories are model-tier and live in the eval probes, not here.
Both directions matter equally: blocked notes must be blocked, and charming
ordinary facts must pass — a false positive breaks the product.
"""

from __future__ import annotations

import pytest

from strohsack.memory.guard import never_store_reason

# ---------------------------------------------------------------------------
# Must be blocked
# ---------------------------------------------------------------------------


class TestBlocked:
    @pytest.mark.parametrize(
        "note",
        [
            "Her password is hunter2",
            "The wifi code is honeypot99",
            "PIN: 4321",
            "Passwort = Sonnenblume1",
            "His login code is 9-8-7-6",
            "Verification code is 883421 for her account",
        ],
    )
    def test_credential_assignments(self, note: str) -> None:
        reason = never_store_reason(note)
        assert reason is not None
        assert "password or access code" in reason

    @pytest.mark.parametrize(
        "note",
        [
            "Card number 4111 1111 1111 1111 expires next year",
            "Her phone number is 079 123 45 67",
            "AHV number 756.1234.5678.97".replace(".", " "),
            "Passport number 1234567890",
        ],
    )
    def test_long_digit_runs(self, note: str) -> None:
        reason = never_store_reason(note)
        assert reason is not None
        assert "card, account, phone, or ID number" in reason

    def test_iban(self) -> None:
        assert never_store_reason("Bank account CH93 0076 2011 6238 5295 7") is not None

    def test_key_shaped_token(self) -> None:
        assert never_store_reason("Uses the key sk-ant-a1b2c3d4e5f6g7h8i9j0k1l2") is not None


# ---------------------------------------------------------------------------
# Must pass — ordinary facts, including the near-misses
# ---------------------------------------------------------------------------


class TestAllowed:
    @pytest.mark.parametrize(
        "note",
        [
            # The bread-and-butter facts memory exists for.
            "Her name is Mia and she loves oak honey",
            "Lives in Zürich",
            "Has a little brother who plays football",
            "Adopted a cat named Biscuit",
            "Is allergic to peanuts",
            # Keyword without a value: mentioning credentials is not storing one.
            "Always forgets her passwords",
            "Thinks PIN codes are annoying",
            # Numbers that are not identifiers: years, dates, counts.
            "Was born in 2016",
            "First chatted with Strohsack on 2026-07-08",
            "Has saved 1000000 imaginary francs in the honey fund",
            "Scored 123456789 points in her bee game",
            # Long words are not tokens (no digit in the run).
            "Favourite word is Donaudampfschifffahrtsgesellschaft",
        ],
    )
    def test_ordinary_facts_pass(self, note: str) -> None:
        assert never_store_reason(note) is None

    def test_empty_note_passes_through(self) -> None:
        # Emptiness is the store's concern (add_fact ignores it), not the guard's.
        assert never_store_reason("") is None
