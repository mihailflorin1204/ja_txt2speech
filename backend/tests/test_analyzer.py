import pytest

pyopenjtalk = pytest.importorskip("pyopenjtalk")

from app.text.analyzer import analyze_sentence, analyze_text  # noqa: E402


def test_analyze_basic():
    utt = analyze_sentence("今日はいい天気ですね。")
    assert utt.text == "今日はいい天気ですね。"
    assert len(utt.accent_phrases) >= 1
    all_kana = "".join(m.kana for p in utt.accent_phrases for m in p.moras)
    assert "キョ" in all_kana or "キョウ" in all_kana


def test_accent_nucleus_in_range():
    utt = analyze_sentence("辛いものが好きです。")
    for p in utt.accent_phrases:
        assert 0 <= p.accent <= len(p.moras)


def test_analyze_text_multiple():
    utts = analyze_text("こんにちは。元気ですか？")
    assert len(utts) == 2


def test_interrogative_flag():
    utt = analyze_sentence("元気ですか？")
    assert utt.accent_phrases[-1].is_interrogative is True
