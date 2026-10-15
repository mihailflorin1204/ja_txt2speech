"""Sentence splitting (spec §8 step 2).

Split on 。！？!?… and newlines; sentences longer than 120 chars are split
further on 、 and clause boundaries.
"""

import re

BOUNDARY_CHARS = "。！？!?…"
MAX_SENTENCE_CHARS = 120

_BOUNDARY_RE = re.compile(rf"[{re.escape(BOUNDARY_CHARS)}\n]+")
_COMMA_SPLIT_RE = re.compile(r"、+")


def split_sentences(text: str, keep_punct: bool = True) -> list[str]:
    """Split text into sentences, keeping trailing punctuation on each."""
    out: list[str] = []
    for chunk in _BOUNDARY_RE.split(text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if len(chunk) <= MAX_SENTENCE_CHARS:
            out.append(chunk)
        else:
            out.extend(_split_long(chunk))
    if keep_punct:
        out = _reattach_punct(text, out)
    return [s for s in out if s]


def _split_long(chunk: str) -> list[str]:
    """Split an overlong sentence on commas / clause boundaries."""
    parts = [p for p in _COMMA_SPLIT_RE.split(chunk) if p]
    if len(parts) == 1:
        # no commas: hard split
        return [chunk[i:i + MAX_SENTENCE_CHARS]
                for i in range(0, len(chunk), MAX_SENTENCE_CHARS)]
    merged: list[str] = []
    buf = ""
    for part in parts:
        if buf and len(buf) + len(part) + 1 > MAX_SENTENCE_CHARS:
            merged.append(buf)
            buf = part
        else:
            buf = f"{buf}、{part}" if buf else part
    if buf:
        merged.append(buf)
    final: list[str] = []
    for m in merged:
        if len(m) > MAX_SENTENCE_CHARS:
            final.extend(m[i:i + MAX_SENTENCE_CHARS]
                         for i in range(0, len(m), MAX_SENTENCE_CHARS))
        else:
            final.append(m)
    return final


def _reattach_punct(original: str, sentences: list[str]) -> list[str]:
    """Restore the boundary punctuation that followed each sentence."""
    pos = 0
    result = []
    for sent in sentences:
        idx = original.find(sent[:20] if len(sent) > 20 else sent, pos)
        if idx < 0:
            result.append(sent)
            continue
        pos = idx + len(sent)
        tail = ""
        while pos < len(original) and original[pos] in BOUNDARY_CHARS:
            tail += original[pos]
            pos += 1
        result.append(sent + tail)
    return result
