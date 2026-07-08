"""
Configuration loading for Strohsack AI.

Centralizes all the bits the rest of the app needs to start a conversation:
environment settings (API key, model, token budget) and the system prompt
text that gives Strohsack his personality. Everything else plugs into the
``Config`` object returned by :func:`load_config`.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# The prompt file is a sibling of this package: src/strohsack/personality/
# Using a package-relative path (rather than climbing to the repo root) means
# the path stays correct regardless of where the package is installed.
DEFAULT_PROMPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "personality"
    / "strohsack_system_prompt_v0.1.txt"
)

# Personality profiles live in src/config/. The public profile is the generic,
# self-contained bear and is the default everywhere. The private profile is a
# gitignored family overlay loaded only at home — see STROHSACK_PROJECT_PLAN.md
# (Pre-Public Hardening). Resolve src/config relative to this file so the paths
# survive an editable install.
CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"
PUBLIC_PERSONALITY_PATH = CONFIG_DIR / "personality.json"
PRIVATE_PERSONALITY_PATH = CONFIG_DIR / "personality.private.json"


class ConfigError(Exception):
    """Raised when configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    """Resolved application settings.

    Attributes:
        api_key: Anthropic API key.
        model: Claude model identifier.
        max_tokens: Maximum tokens for a single response.
        system_prompt: The full Strohsack personality prompt.
    """

    api_key: str
    model: str
    max_tokens: int
    system_prompt: str


def load_system_prompt(prompt_path: Path | None = None) -> str:
    """Read the Strohsack system prompt from disk.

    Args:
        prompt_path: Override path to the prompt file. Defaults to the
            bundled v0.1 prompt.

    Raises:
        ConfigError: If the prompt file does not exist or is empty.
    """
    path = prompt_path or DEFAULT_PROMPT_PATH
    if not path.exists():
        raise ConfigError(f"System prompt not found at: {path}")

    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ConfigError(f"System prompt file is empty: {path}")
    return text


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge ``overlay`` onto a copy of ``base``.

    Nested dicts are merged key-by-key; any non-dict value in ``overlay``
    replaces the corresponding value in ``base``. Used to layer the private
    family overlay over the public personality profile.
    """
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def load_personality_profile(
    profile_path: Path | None = None,
    *,
    include_private: bool | None = None,
) -> dict:
    """Load the Strohsack personality profile.

    Selection order:
      1. ``profile_path`` argument, if given (loaded as-is, no merging).
      2. ``STROHSACK_PERSONALITY`` env var, if set, pointing at a profile to
         load as-is.
      3. The public ``personality.json`` (always the base), optionally with the
         private ``personality.private.json`` overlay deep-merged on top.

    Whether the private overlay is applied (case 3) is decided by
    ``include_private``: when ``None`` (the default) the overlay is merged only
    if the file is present on disk, so the public build — which never ships that
    file — runs the generic bear automatically. Pass ``True``/``False`` to force
    it.

    Args:
        profile_path: Explicit profile to load, bypassing public/private logic.
        include_private: Force-enable/disable the private overlay. ``None``
            auto-detects from the file's presence.

    Raises:
        ConfigError: If a resolved profile file is missing or not valid JSON.
    """
    explicit = profile_path or _env_profile_path()
    if explicit is not None:
        return _read_json_profile(explicit)

    base = _read_json_profile(PUBLIC_PERSONALITY_PATH)

    if include_private is None:
        include_private = PRIVATE_PERSONALITY_PATH.exists()
    if include_private:
        overlay = _read_json_profile(PRIVATE_PERSONALITY_PATH)
        return _deep_merge(base, overlay)
    return base


def _env_profile_path() -> Path | None:
    raw = os.getenv("STROHSACK_PERSONALITY", "").strip()
    return Path(raw) if raw else None


def _read_json_profile(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Personality profile not found at: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Personality profile is not valid JSON ({path}): {exc}") from exc


def load_config(
    *,
    require_api_key: bool = True,
    prompt_path: Path | None = None,
    use_dotenv: bool = True,
) -> Config:
    """Load environment settings and the system prompt into a ``Config``.

    Reads ``.env`` (if present) and the process environment. The system
    prompt is always loaded from disk so personality edits don't require
    touching code.

    Args:
        require_api_key: When True (the default), raise if the API key is
            missing. Set False for tests that exercise prompt assembly
            without contacting the API.
        prompt_path: Override path to the system prompt file.
        use_dotenv: When True (the default), load a ``.env`` file. Tests
            set this False so a real ``.env`` doesn't bleed into the
            controlled environment they set up.

    Raises:
        ConfigError: If a required setting is missing or malformed.
    """
    if use_dotenv:
        load_dotenv()

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if require_api_key and not api_key:
        raise ConfigError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and "
            "add your Anthropic API key."
        )

    model = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6").strip()

    raw_max_tokens = os.getenv("MAX_TOKENS", "1000").strip()
    try:
        max_tokens = int(raw_max_tokens)
    except ValueError as exc:
        raise ConfigError(f"MAX_TOKENS must be an integer, got: {raw_max_tokens!r}") from exc
    if max_tokens <= 0:
        raise ConfigError(f"MAX_TOKENS must be positive, got: {max_tokens}")

    system_prompt = load_system_prompt(prompt_path)

    return Config(
        api_key=api_key,
        model=model,
        max_tokens=max_tokens,
        system_prompt=system_prompt,
    )
