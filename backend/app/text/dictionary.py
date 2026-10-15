"""User dictionary application (spec §8 step 3).

Applies DictionaryEntry rows to analyzed Utterances. Entries are matched by
surface form against accent-phrase mora surface text; matched phrases get
their kana reading and accent nucleus replaced.
"""

import logging

from sqlmodel import Session, select

from app.core.db import get_engine
from app.engines.base import Utterance
from app.models.tables import DictionaryEntry

log = logging.getLogger("text.dictionary")


def load_entries() -> list[dict]:
    with Session(get_engine()) as session:
        rows = session.exec(
            select(DictionaryEntry).order_by(DictionaryEntry.priority.desc())
        ).all()
    return [
        {"surface": r.surface, "reading": r.reading,
         "accent_type": r.accent_type, "priority": r.priority}
        for r in rows
    ]


def apply_user_dictionary(utterances: list[Utterance]) -> list[Utterance]:
    """Override readings/accents where a dictionary surface matches.

    For M1 this is a post-analysis pass over mora kana; the mecab userdic
    integration lands in M3 for entries that change word segmentation.
    """
    with Session(get_engine()) as session:
        entries = session.exec(
            select(DictionaryEntry).order_by(DictionaryEntry.priority.desc())
        ).all()
    if not entries:
        return utterances

    for utt in utterances:
        for entry in entries:
            if entry.surface not in utt.text:
                continue
            _apply_entry(utt, entry.surface, entry.reading, entry.accent_type)
    return utterances


def _word_runs(moras: list) -> list[tuple[str, list]]:
    """Group a phrase's moras into (surface, [moras]) runs — moras of one word
    share its surface text."""
    runs: list[tuple[str, list]] = []
    for m in moras:
        if runs and runs[-1][0] == m.text:
            runs[-1][1].append(m)
        else:
            runs.append((m.text, [m]))
    return runs


def _apply_entry(utt: Utterance, surface: str, reading: str,
                 accent_type: int | None) -> None:
    """Override readings where the entry surface matches.

    Matches either word runs inside an accent phrase ("便利" inside
    "便利だ物です") or a run of consecutive phrases whose combined surface
    equals the entry surface; the replaced span gets the forced reading and
    (if given) accent nucleus.
    """
    from app.engines.base import AccentPhrase
    from app.text.analyzer import _pron_to_moras

    for phrase in utt.accent_phrases:
        runs = _word_runs(phrase.moras)
        i = 0
        while i < len(runs):
            for j in range(len(runs), i, -1):
                if "".join(t for t, _ in runs[i:j]) != surface:
                    continue
                new_moras = _pron_to_moras(reading, surface)
                phrase.moras = (
                    [m for _, ms in runs[:i] for m in ms]
                    + new_moras
                    + [m for _, ms in runs[j:] for m in ms]
                )
                if accent_type is not None:
                    phrase.accent = min(accent_type, len(phrase.moras))
                break
            i += 1

    # cross-phrase spans: merge consecutive phrases whose combined surface
    # equals the entry surface
    phrases = utt.accent_phrases
    i = 0
    while i < len(phrases):
        for j in range(len(phrases), i + 1, -1):
            span = phrases[i:j]
            if "".join(t for p in span for t, _ in _word_runs(p.moras)) != surface:
                continue
            new_moras = _pron_to_moras(reading, surface)
            phrases[i:j] = [AccentPhrase(
                moras=new_moras,
                accent=min(accent_type, len(new_moras))
                if accent_type is not None else (0 if not new_moras else 1),
                pause_after_ms=span[-1].pause_after_ms,
                is_interrogative=span[-1].is_interrogative)]
            break
        i += 1


def _phrase_surface(span) -> str:
    return "".join(t for p in span for t, _ in _word_runs(p.moras))
