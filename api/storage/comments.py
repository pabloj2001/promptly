"""Parse/serialize the trailing ``promptly:comments`` block in ``.md`` files.

Highlight comments are appended to the end of a doc inside an HTML comment so they
never render in markdown and travel with the file (01 §3):

    ...body...

    <!-- promptly:comments
    { "comments": [ ... ] }
    -->

There is at most one such block, always last. ``anchor.start/end`` are character
offsets into the body (the text *before* the block); ``quote`` is the fallback
used to re-anchor after the body is edited.
"""

from __future__ import annotations

import json
import re

from ..models import Comment

_SENTINEL = "promptly:comments"
# Matches the trailing block: <!-- promptly:comments\n{json}\n-->
_BLOCK_RE = re.compile(
    r"\n*<!--\s*" + re.escape(_SENTINEL) + r"\s*\n(?P<json>.*?)\n-->\s*$",
    re.DOTALL,
)


def parse_document(text: str) -> tuple[str, list[Comment]]:
    """Split a raw ``.md`` into (body, comments)."""
    m = _BLOCK_RE.search(text)
    if not m:
        return text, []
    body = text[: m.start()]
    try:
        payload = json.loads(m.group("json"))
        comments = [Comment.model_validate(c) for c in payload.get("comments", [])]
    except (json.JSONDecodeError, ValueError):
        # Malformed block: keep the body, drop the comments rather than crash.
        comments = []
    return body, comments


def serialize_document(body: str, comments: list[Comment]) -> str:
    """Recombine body + comments into a raw ``.md``. Drops the block entirely
    when there are no comments so clean docs stay clean."""
    body = body.rstrip("\n")
    if not comments:
        return body + "\n"
    payload = {
        "comments": [c.model_dump(by_alias=True, exclude_none=True) for c in comments]
    }
    block = (
        "<!-- " + _SENTINEL + "\n"
        + json.dumps(payload, indent=2, ensure_ascii=False)
        + "\n-->\n"
    )
    return body + "\n\n" + block


def reanchor(body: str, comments: list[Comment]) -> list[Comment]:
    """After a body edit, fix each comment's offsets against the new body.

    If the text at ``[start:end]`` still equals ``quote`` it is left alone.
    Otherwise we search for ``quote``; on a hit we update the offsets, on a miss
    we mark the comment ``orphaned`` (offsets left as-is).
    """
    out: list[Comment] = []
    for c in comments:
        quote = c.anchor.quote
        if quote and body[c.anchor.start : c.anchor.end] == quote:
            c.orphaned = False
        elif quote and (idx := body.find(quote)) != -1:
            c.anchor.start = idx
            c.anchor.end = idx + len(quote)
            c.orphaned = False
        else:
            c.orphaned = True
        out.append(c)
    return out
