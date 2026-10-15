"""Reading + accent analysis via pyopenjtalk (spec §8 steps 4-5).

Produces engine-neutral Utterance objects: accent phrases with moras,
katakana readings, and accent nucleus positions.
"""

import logging

import pyopenjtalk

from app.engines.base import AccentPhrase, Mora, Utterance
from app.text.normalizer import normalize
from app.text.splitter import split_sentences

log = logging.getLogger("text.analyzer")

# Built-in corrections for notorious irregular readings OpenJTalk misses
# (spec FR-4.5: common mis-reading corrections applied before presenting data).
KNOWN_READINGS: dict[str, str] = {
    "明後日": "アサッテ",
    "一昨日": "オトトイ",
    "昨日": "キノー",
    "今日": "キョー",
    "明日": "アシタ",
    "大人": "オトナ",
    "二人": "フタリ",
    "一人": "ヒトリ",
    "一人暮らし": "ヒトリグラシ",
    "二十歳": "ハタチ",
    "八百屋": "ヤオヤ",
    "上手い": "ウマイ",
    "上手": "ジョーズ",
    "下手": "ヘタ",
    "眼鏡": "メガネ",
    "海老": "エビ",
    "床屋": "トコヤ",
    "凸凹": "デコボコ",
    "為替": "カワセ",
}

# phoneme -> katakana vowel/mora table for reading display
_VOWEL_KANA = {
    "a": "ア", "i": "イ", "u": "ウ", "e": "エ", "o": "オ",
    "N": "ン", "cl": "ッ", "pau": "", "sil": "",
}


def _njd_to_accent_phrases(njd_features: list[dict]) -> list[AccentPhrase]:
    """Group NJD word nodes into accent phrases.

    OpenJTalk NJD marks each word with `acc` (accent nucleus mora index within
    the accent phrase it heads) and `chain_flag` (1 = attach to previous
    accent phrase). Phrase accent nucleus = mora offset of the accented word
    plus its acc value.
    """
    phrases: list[list[dict]] = []
    for node in njd_features:
        if not phrases or node.get("chain_flag", 0) == 0:
            phrases.append([node])
        else:
            phrases[-1].append(node)

    out: list[AccentPhrase] = []
    for group in phrases:
        moras: list[Mora] = []
        nucleus = 0  # 0 => flat (heiban)
        for node in group:
            node_mora_start = len(moras)
            surface = node.get("orig") or node.get("surface") or ""
            pron = KNOWN_READINGS.get(surface) or node.get("pron", "") or surface
            moras.extend(_pron_to_moras(pron, surface or pron))
            acc = node.get("acc", 0) or 0
            if acc > 0:
                nucleus = node_mora_start + acc
        if moras:
            out.append(AccentPhrase(
                moras=moras,
                accent=min(nucleus, len(moras)),
                is_interrogative=False,
            ))
    return out


def _pron_to_moras(pron: str, surface: str) -> list[Mora]:
    """Convert a katakana pronunciation string to Mora objects.

    Small kana (ャュョァィゥェォッ) attach to the previous kana to form one mora.
    """
    small = "ャュョァィゥェォヮ"
    skip = "'’"  # devoicing markers in pyopenjtalk pron fields
    moras: list[Mora] = []
    i = 0
    while i < len(pron):
        ch = pron[i]
        if ch in skip:
            i += 1
            continue
        kana = ch
        if i + 1 < len(pron) and pron[i + 1] in small:
            kana += pron[i + 1]
            i += 1
        i += 1
        moras.append(Mora(
            text=surface,
            kana=kana,
            consonant=None,
            vowel=_guess_vowel(kana),
        ))
    return moras


def _guess_vowel(kana: str) -> str:
    last = kana[-1]
    table = {
        "ア": "a", "イ": "i", "ウ": "u", "エ": "e", "オ": "o",
        "カ": "a", "キ": "i", "ク": "u", "ケ": "e", "コ": "o",
        "サ": "a", "シ": "i", "ス": "u", "セ": "e", "ソ": "o",
        "タ": "a", "チ": "i", "ツ": "u", "テ": "e", "ト": "o",
        "ナ": "a", "ニ": "i", "ヌ": "u", "ネ": "e", "ノ": "o",
        "ハ": "a", "ヒ": "i", "フ": "u", "ヘ": "e", "ホ": "o",
        "マ": "a", "ミ": "i", "ム": "u", "メ": "e", "モ": "o",
        "ヤ": "a", "ユ": "u", "ヨ": "o",
        "ラ": "a", "リ": "i", "ル": "u", "レ": "e", "ロ": "o",
        "ワ": "a", "ヲ": "o", "ン": "N",
        "ガ": "a", "ギ": "i", "グ": "u", "ゲ": "e", "ゴ": "o",
        "ザ": "a", "ジ": "i", "ズ": "u", "ゼ": "e", "ゾ": "o",
        "ダ": "a", "ヂ": "i", "ヅ": "u", "デ": "e", "ド": "o",
        "バ": "a", "ビ": "i", "ブ": "u", "ベ": "e", "ボ": "o",
        "パ": "a", "ピ": "i", "プ": "u", "ペ": "e", "ポ": "o",
        "ッ": "cl",
    }
    vowel = table.get(last, "")
    if kana.endswith("ャ"):
        vowel = "a"
    elif kana.endswith("ュ"):
        vowel = "u"
    elif kana.endswith("ョ"):
        vowel = "o"
    return vowel


def analyze_sentence(sentence: str) -> Utterance:
    """Analyze one normalized sentence into an Utterance."""
    try:
        njd = pyopenjtalk.run_frontend(sentence)
    except Exception as e:  # noqa: BLE001
        log.warning("pyopenjtalk frontend failed for %r: %s", sentence, e)
        return Utterance(text=sentence)
    phrases = _njd_to_accent_phrases(njd)
    if sentence.rstrip().endswith(("？", "?")) and phrases:
        phrases[-1].is_interrogative = True
    return Utterance(text=sentence, accent_phrases=phrases)


def analyze_text(text: str) -> list[Utterance]:
    """Full pipeline: normalize -> split -> analyze each sentence."""
    normalized = normalize(text)
    sentences = split_sentences(normalized)
    return [analyze_sentence(s) for s in sentences]
