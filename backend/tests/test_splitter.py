from app.text.splitter import split_sentences


def test_basic_split():
    out = split_sentences("こんにちは。元気ですか？はい！")
    assert out == ["こんにちは。", "元気ですか？", "はい！"]


def test_newline_split():
    out = split_sentences("一行目\n二行目")
    assert out == ["一行目", "二行目"]


def test_long_sentence_split_on_comma():
    long = "あ" * 100 + "、" + "い" * 100 + "。"
    out = split_sentences(long)
    assert len(out) >= 2
    assert all(len(s) <= 130 for s in out)


def test_no_comma_hard_split():
    long = "あ" * 300
    out = split_sentences(long)
    assert len(out) >= 2
    assert all(len(s) <= 120 for s in out)


def test_ellipsis_boundary():
    out = split_sentences("それは…本当？")
    assert len(out) == 2
