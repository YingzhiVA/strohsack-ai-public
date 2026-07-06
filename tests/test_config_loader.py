"""Tests for strohsack.utils.config_loader."""

from __future__ import annotations

import json

import pytest

from strohsack.utils.config_loader import (
    Config,
    ConfigError,
    load_config,
    load_personality_profile,
    load_system_prompt,
)


def test_load_bundled_system_prompt() -> None:
    """The shipped v0.1 prompt loads and contains its defining trait."""
    prompt = load_system_prompt()
    assert "Strohsack" in prompt
    assert "honey" in prompt.lower()


def test_load_system_prompt_missing(tmp_path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_system_prompt(tmp_path / "does_not_exist.txt")


def test_load_system_prompt_empty(tmp_path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("   \n", encoding="utf-8")
    with pytest.raises(ConfigError, match="empty"):
        load_system_prompt(empty)


def test_load_config_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("CLAUDE_MODEL", "claude-test-model")
    monkeypatch.setenv("MAX_TOKENS", "512")

    config = load_config(use_dotenv=False)

    assert isinstance(config, Config)
    assert config.api_key == "test-key"
    assert config.model == "claude-test-model"
    assert config.max_tokens == 512
    assert "Strohsack" in config.system_prompt


def test_load_config_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        load_config(use_dotenv=False)


def test_load_config_can_skip_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config = load_config(require_api_key=False, use_dotenv=False)
    assert config.api_key == ""


def test_load_config_rejects_bad_max_tokens(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("MAX_TOKENS", "not-a-number")
    with pytest.raises(ConfigError, match="MAX_TOKENS"):
        load_config(use_dotenv=False)


def test_load_config_rejects_nonpositive_max_tokens(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("MAX_TOKENS", "0")
    with pytest.raises(ConfigError, match="positive"):
        load_config(use_dotenv=False)


# --- personality profile loading (public/private split) ---


def test_public_profile_is_generic(monkeypatch) -> None:
    """The shipped public profile carries no family/relationship data."""
    monkeypatch.delenv("STROHSACK_PERSONALITY", raising=False)
    profile = load_personality_profile(include_private=False)
    assert "relationship_dynamics" not in profile
    assert "family_teasing_targets" not in profile.get("humor_profile", {})
    # but it is still a complete bear
    assert profile["bonvivant_traits"]["honey_addiction"] == 100


def test_private_overlay_merges_over_public(tmp_path, monkeypatch) -> None:
    """A private overlay deep-merges onto the public base without dropping it."""
    monkeypatch.delenv("STROHSACK_PERSONALITY", raising=False)
    public = load_personality_profile(include_private=False)

    overlay = {
        "relationship_dynamics": {"someone": {"affection_level": 100}},
        "bear_traits": {"family_loyalty": 90},  # adds a key alongside public ones
    }
    overlay_path = tmp_path / "personality.private.json"
    overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
    monkeypatch.setattr(
        "strohsack.utils.config_loader.PRIVATE_PERSONALITY_PATH", overlay_path
    )

    merged = load_personality_profile(include_private=True)
    assert merged["relationship_dynamics"]["someone"]["affection_level"] == 100
    assert merged["bear_traits"]["family_loyalty"] == 90
    # public bear_traits survive the merge
    assert merged["bear_traits"]["cuddle_factor"] == public["bear_traits"]["cuddle_factor"]


def test_auto_detect_skips_overlay_when_absent(tmp_path, monkeypatch) -> None:
    """With no private file present, the default is the generic public bear."""
    monkeypatch.delenv("STROHSACK_PERSONALITY", raising=False)
    monkeypatch.setattr(
        "strohsack.utils.config_loader.PRIVATE_PERSONALITY_PATH",
        tmp_path / "absent.json",
    )
    profile = load_personality_profile()  # include_private=None -> auto-detect
    assert "relationship_dynamics" not in profile


def test_env_var_selects_explicit_profile(tmp_path, monkeypatch) -> None:
    custom = tmp_path / "custom.json"
    custom.write_text(json.dumps({"marker": "explicit"}), encoding="utf-8")
    monkeypatch.setenv("STROHSACK_PERSONALITY", str(custom))
    assert load_personality_profile() == {"marker": "explicit"}


def test_missing_profile_raises(tmp_path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_personality_profile(tmp_path / "nope.json")


def test_invalid_json_profile_raises(tmp_path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_personality_profile(bad)
