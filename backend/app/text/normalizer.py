"""Text normalization for Japanese TTS (spec §8 step 1).

- Unicode NFKC width normalization
- Numbers with counters (3人 → さんにん, 1本 → いっぽん)
- Dates and times
- Symbols and units (%, ℃, km, ¥, ~)
- URLs / emails (skipped by default)
- English words -> katakana (dictionary lookup, letter-by-letter fallback)
"""

import re
import unicodedata

import jaconv

# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

_DIGITS = "〇一二三四五六七八九"
_UNITS1 = ["", "十", "百", "千"]
_UNITS4 = ["", "万", "億", "兆", "京"]


def _four_digits_to_kanji(n: int) -> str:
    """0-9999 -> kanji reading (e.g. 1234 -> 千二百三十四)."""
    if n == 0:
        return ""
    out = ""
    for i in range(3, -1, -1):
        d = n // (10**i) % 10
        if d == 0:
            continue
        if d == 1 and i > 0:
            out += _UNITS1[i]
        else:
            out += _DIGITS[d] + _UNITS1[i]
    return out


def number_to_kanji(n: int) -> str:
    """Integer -> kanji numeral reading."""
    if n == 0:
        return "零"
    parts = []
    unit_idx = 0
    while n > 0:
        chunk = n % 10000
        if chunk:
            parts.append(_four_digits_to_kanji(chunk) + _UNITS4[unit_idx])
        n //= 10000
        unit_idx += 1
    return "".join(reversed(parts))


# Simplified counter table: surface -> per-number readings 1..10
COUNTERS: dict[str, list[str]] = {
    "人": ["ひとり", "ふたり", "さんにん", "よにん", "ごにん", "ろくにん",
           "ななにん", "はちにん", "きゅうにん", "じゅうにん"],
    "本": ["いっぽん", "にほん", "さんぼん", "よんほん", "ごほん", "ろっぽん",
           "ななほん", "はちほん", "きゅうほん", "じゅっぽん"],
    "冊": ["いっさつ", "にさつ", "さんさつ", "よんさつ", "ごさつ", "ろくさつ",
           "ななさつ", "はっさつ", "きゅうさつ", "じゅっさつ"],
    "枚": ["いちまい", "にまい", "さんまい", "よんまい", "ごまい", "ろくまい",
           "ななまい", "はちまい", "きゅうまい", "じゅうまい"],
    "匹": ["いっぴき", "にひき", "さんびき", "よんひき", "ごひき", "ろっぴき",
           "ななひき", "はちひき", "きゅうひき", "じゅっぴき"],
    "台": ["いちだい", "にだい", "さんだい", "よんだい", "ごだい", "ろくだい",
           "ななだい", "はちだい", "きゅうだい", "じゅうだい"],
    "個": ["いっこ", "にこ", "さんこ", "よんこ", "ごこ", "ろっこ",
           "ななこ", "はっこ", "きゅうこ", "じゅっこ"],
    "回": ["いっかい", "にかい", "さんかい", "よんかい", "ごかい", "ろっかい",
           "ななかい", "はちかい", "きゅうかい", "じゅっかい"],
    "歳": ["いっさい", "にさい", "さんさい", "よんさい", "ごさい", "ろくさい",
           "ななさい", "はっさい", "きゅうさい", "じゅっさい"],
    "分": ["いっぷん", "にふん", "さんぷん", "よんぷん", "ごふん", "ろっぷん",
           "ななふん", "はちふん", "きゅうふん", "じゅっぷん"],
    "時": ["いちじ", "にじ", "さんじ", "よじ", "ごじ", "ろくじ",
           "しちじ", "はちじ", "くじ", "じゅうじ"],
    "日": ["ついたち", "ふつか", "みっか", "よっか", "いつか", "むいか",
           "なのか", "ようか", "ここのか", "とおか"],
}

_NUM_COUNTER_RE = re.compile(
    r"(\d{1,3}(?:,\d{3})+|\d+)\s*(" + "|".join(COUNTERS) + ")"
)


def _num_counter_sub(m: re.Match) -> str:
    num = int(m.group(1).replace(",", ""))
    counter = m.group(2)
    readings = COUNTERS[counter]
    if 1 <= num <= 10:
        return readings[num - 1]
    return number_to_kanji(num) + counter


def _plain_number_sub(m: re.Match) -> str:
    return number_to_kanji(int(m.group(0).replace(",", "")))


# ---------------------------------------------------------------------------
# Dates / times
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"(\d{4})[/\-年](\d{1,2})[/\-月](\d{1,2})日?")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?")


def _date_sub(m: re.Match) -> str:
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{number_to_kanji(y)}年{number_to_kanji(mo)}月{number_to_kanji(d)}日"


def _time_sub(m: re.Match) -> str:
    h, mi = int(m.group(1)), int(m.group(2))
    out = f"{number_to_kanji(h)}時{number_to_kanji(mi)}分"
    if m.group(3):
        out += f"{number_to_kanji(int(m.group(3)))}秒"
    return out


# ---------------------------------------------------------------------------
# Symbols / units / URLs / email / English
# ---------------------------------------------------------------------------

_SYMBOL_MAP = {
    "%": "パーセント",
    "℃": "度",
    "℉": "度",
    "¥": "円",
    "〜": "から",
    "～": "から",
    "&": "アンド",
    "＆": "アンド",
    "@": "アット",
    "＃": "シャープ",
    "#": "シャープ",
    "＋": "プラス",
    "－": "マイナス",
    "±": "プラスマイナス",
    "×": "かける",
    "÷": "わる",
    "＝": "イコール",
    "=": "イコール",
}

_UNIT_MAP = {
    "km": "キロメートル", "kg": "キログラム", "cm": "センチメートル",
    "mm": "ミリメートル", "ml": "ミリリットル", "GB": "ギガバイト",
    "MB": "メガバイト", "TB": "テラバイト", "Hz": "ヘルツ",
    "円": "えん",
}

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_ENGLISH_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")

# Minimal English -> katakana table (alkana-style); extended over time.
ENGLISH_KANA: dict[str, str] = {
    "the": "ザ", "a": "ア", "an": "アン", "and": "アンド", "or": "オア",
    "hello": "ハロー", "world": "ワールド", "music": "ミュージック",
    "video": "ビデオ", "game": "ゲーム", "play": "プレイ", "stop": "ストップ",
    "start": "スタート", "ok": "オーケー", "no": "ノー", "yes": "イエス",
    "i": "アイ", "you": "ユー", "we": "ウィー", "ai": "エーアイ",
    "api": "エーピーアイ", "url": "ユーアールエル", "cpu": "シーピーユー",
    "gpu": "ジーピーユー", "tts": "ティーティーエス", "mp3": "エムピースリー",
    "wav": "ウェーブ", "text": "テキスト", "speech": "スピーチ",
    "voice": "ボイス", "open": "オープン", "source": "ソース",
}

_LETTER_KANA = {
    "a": "エー", "b": "ビー", "c": "シー", "d": "ディー", "e": "イー",
    "f": "エフ", "g": "ジー", "h": "エイチ", "i": "アイ", "j": "ジェー",
    "k": "ケー", "l": "エル", "m": "エム", "n": "エヌ", "o": "オー",
    "p": "ピー", "q": "キュー", "r": "アール", "s": "エス", "t": "ティー",
    "u": "ユー", "v": "ブイ", "w": "ダブリュー", "x": "エックス",
    "y": "ワイ", "z": "ゼット",
}


def _english_sub(m: re.Match) -> str:
    word = m.group(0)
    kana = ENGLISH_KANA.get(word.lower())
    if kana:
        return kana
    if len(word) <= 3 or word.isupper():
        return "".join(_LETTER_KANA.get(c.lower(), c) for c in word)
    return jaconv.alphabet2kana(word)


def normalize(text: str, read_urls: bool = False) -> str:
    """Normalize raw input text for the TTS pipeline."""
    t = unicodedata.normalize("NFKC", text)

    # URLs and emails (skip unless configured to read)
    t = _URL_RE.sub(" URL " if read_urls else " ", t)
    t = _EMAIL_RE.sub(" メールアドレス " if read_urls else " ", t)

    # Dates before plain numbers (contains digits)
    t = _DATE_RE.sub(_date_sub, t)
    t = _TIME_RE.sub(_time_sub, t)

    # Numbers with counters, then plain numbers
    t = _NUM_COUNTER_RE.sub(_num_counter_sub, t)
    t = re.sub(r"\d{1,3}(?:,\d{3})+|\d+", _plain_number_sub, t)

    # Symbols and units
    for sym, rep in _SYMBOL_MAP.items():
        t = t.replace(sym, rep)
    for unit, rep in sorted(_UNIT_MAP.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"(?<=[\d一二三四五六七八九十百千万億兆]){re.escape(unit)}\b", rep, t)
        t = re.sub(rf"(?<=[ぁ-んァ-ヶ]){re.escape(unit)}\b", rep, t) if unit != "円" else t

    # English words -> katakana
    t = _ENGLISH_RE.sub(_english_sub, t)

    # Collapse whitespace
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()
