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


def _apply_entry(utt: Utterance, surface: str, reading: str,
                 accent_type: int | None) -> None:
    """Replace kana reading of any accent phrase whose surface matches."""
    from app.text.analyzer import _pron_to_moras

    for phrase in utt.accent_phrases:
        phrase_surface = "".join({m.text for m in phrase.moras})
        if surface != phrase_surface and surface not in phrase_surface:
            continue
        new_moras = _pron_to_moras(reading, surface)
        phrase.moras = new_moras
        if accent_type is not None:
            phrase.accent = min(accent_type, len(new_moras))
