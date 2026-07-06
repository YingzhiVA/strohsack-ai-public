"""User-facing interfaces for Strohsack AI (CLI, web, and later voice).

Greeting and farewell text live here so every interface shows the same
in-character lines rather than each defining its own. Each is a small pool
of variants; call :func:`greeting` / :func:`farewell` to get a random one so
Strohsack doesn't say the exact same thing every session.
"""

from __future__ import annotations

import random

# A handful of openers, all in Strohsack's voice: sleepy, honey-fixated, warm.
GREETINGS = (
    "Oh! Hello there, human! Strohsack was just having the most wonderful "
    "dream about a honey waterfall... What's on your mind?",
    "Mmmf... oh, a visitor! Strohsack was *this* close to the honey in his "
    "dream. Ah well. What can a sleepy bear do for you?",
    "Hello hello! You caught Strohsack mid-stretch. *yawns hugely* Now then, "
    "what brings you to my cozy little corner?",
    "Ooh, company! Strohsack loves company almost as much as honey. Almost. "
    "Sit, sit — what's on your mind?",
    "*one eye opens* ...a human! Strohsack was dreaming he'd learned to bake. "
    "Imagine that. Anyway — hello! What shall we talk about?",
    "Well well, look who waddled in. Hello, friend! Strohsack is awake. "
    "Mostly. What would you like to know?",
    "Hello there! Strohsack just woke from a nap and his head is full of "
    "honey and half-remembered dreams. Lovely. How can I help?",
)

# Farewells, same voice: drowsy, fond, off to a nap.
FAREWELLS = (
    "Off for a nap... bye bye, human! *waddles away*",
    "Mmm, nap time. Come back soon, won't you? *yawns and shuffles off*",
    "Bye bye! Strohsack will dream of our little chat. And honey. Mostly honey.",
    "Farewell, friend! Strohsack's pillow is calling. *flops down with a sigh*",
    "Take care, human! Strohsack is off to find a snack and a soft spot to "
    "snooze. *waddles away*",
    "Goodbye for now! Strohsack had a lovely time. *sleepy wave*",
    "Time for Strohsack to curl up. Sweet dreams to you too — bye bye!",
)


def greeting() -> str:
    """Return a random in-character greeting from :data:`GREETINGS`."""
    return random.choice(GREETINGS)


def farewell() -> str:
    """Return a random in-character farewell from :data:`FAREWELLS`."""
    return random.choice(FAREWELLS)


__all__ = ["GREETINGS", "FAREWELLS", "greeting", "farewell"]
