from app.text.normalizer import normalize, number_to_kanji


def test_number_to_kanji():
    assert number_to_kanji(0) == "零"
    assert number_to_kanji(5) == "五"
    assert number_to_kanji(10) == "十"
    assert number_to_kanji(11) == "十一"
    assert number_to_kanji(1234) == "千二百三十四"
    assert number_to_kanji(10000) == "一万"
    assert number_to_kanji(2026) == "二千二十六"


def test_counter_readings():
    assert "さんにん" in normalize("3人が来た")
    assert "いっぽん" in normalize("1本ください")
    assert "よにん" in normalize("4人で行く")


def test_dates():
    assert "二千二十六年十月十四日" in normalize("2026/10/14")


def test_times():
    out = normalize("18:44に終わる")
    assert "十八時四十四分" in out


def test_symbols_and_units():
    assert "パーセント" in normalize("50%オフ")
    assert "ド" not in normalize("25℃")


def test_urls_and_emails_skipped():
    assert "http" not in normalize("見て https://example.com これ")
    assert "@" not in normalize("連絡 a@b.com して")


def test_english_to_katakana():
    assert "ハロー" in normalize("hello と言った")
    assert "シーピーユー" in normalize("cpu が速い")


def test_nfkc_width():
    # full-width digits normalized
    assert "三" in normalize("３人") or "さんにん" in normalize("３人")
