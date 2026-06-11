"""Small shared helpers for routers."""

from __future__ import annotations


def provisional_name(prompt: str, max_words: int = 6) -> str:
    """A temporary display name for a doc/task while it's being generated, derived
    from the prompt. Replaced by the AI-chosen name on completion."""
    words = prompt.strip().split()
    name = " ".join(words[:max_words]) if words else "Untitled"
    return (name[:60] + "…") if len(name) > 60 else name or "Untitled"
