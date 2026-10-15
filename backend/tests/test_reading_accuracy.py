"""M3 acceptance: >=97% mora-level reading accuracy on curated corpus
(spec §12). Compares pyopenjtalk readings (devoicing markers stripped)
against expected katakana."""

from pathlib import Path

import pytest

from app.text.analyzer import analyze_sentence

CORPUS = Path(__file__).parent / "data" / "reading_corpus.txt"


def _corpus() -> list[tuple[str, str]]:
    rows = []
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        surface, expected = line.split("\t")
        rows.append((surface, expected))
    return rows


@pytest.mark.parametrize("surface,expected", _corpus())
def test_reading(surface: str, expected: str):
    utt = analyze_sentence(surface)
    got = "".join(m.kana for p in utt.accent_phrases for m in p.moras)
    assert got == expected, f"{surface}: got {got}, want {expected}"


def test_accuracy_threshold():
    results = []
    failures = []
    for surface, expected in _corpus():
        utt = analyze_sentence(surface)
        got = "".join(m.kana for p in utt.accent_phrases for m in p.moras)
        ok = got == expected
        results.append(ok)
        if not ok:
            failures.append((surface, got, expected))
    acc = sum(results) / len(results)
    for s, g, e in failures:
        print(f"  MISS {s}: got {g}, want {e}")
    assert acc >= 0.97, f"reading accuracy {acc:.1%} < 97%"
