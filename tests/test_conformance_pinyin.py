"""pypinyin 0.55.0 for the phone: the dictionaries core.pinyin.Pinyin reads, and what pypinyin answers caracole.

caracole asks pypinyin three things, all in Style.NORMAL (normalize.py): ``lazy_pinyin(s)`` (``romanize``),
``lazy_pinyin(text, errors="ignore")`` and ``pinyin(c, style=Style.NORMAL, heteronym=True)[0]``
(``_pinyin_readings``). pypinyin reads a text so (core.py, converter.py, utils.py, seg/simpleseg.py, seg/mmseg.py):

1. simpleseg cuts the text into runs of the characters ``RE_HANS`` matches and runs of the others (hans.txt).
2. A run of others is itself (``errors="default"``) or nothing (``"ignore"``).
3. A run of Han is cut by mmseg's forward maximum matching over PHRASES_DICT (``no_non_phrases=True``): from where
   it stands, the text is read one more character at a time while what it read is a prefix of some phrase; the
   word is the longest phrase among those prefixes, or with none the first character alone. When the whole rest of
   the run is a prefix of a phrase, the word is again the longest phrase among its prefixes and the cut goes on
   after it; with none, each character of the rest is a word alone, and the run ends there.
4. A phrase reads as the first reading of each of its syllables (phrases.txt). A lone character reads as its first
   reading in PINYIN_DICT (chars.txt), else as itself (``"default"``) or nothing (``"ignore"``).
5. ``heteronym=True``, a character alone: its readings with duplicates and empty ones dropped, ``[""]`` were none
   left (``_remove_dup_and_empty``); a Han character with no reading, or any other character, is itself.

Style.NORMAL is pypinyin's own (style/others.py, ``replace_symbol_to_no_symbol``: tone marks dropped, ü written v,
'绿色' read ``lv se``), applied here, so the phone strips no tone.

The data, a main resource of the phone's ``:core`` (caracole/pinyin/ on its classpath), UTF-8, a line each:

- ``hans.txt``: ``<first> <last>``, the ranges of code points ``RE_HANS`` matches alone, inclusive, in lowercase
  hex, in order, neither overlapping nor touching (``RE_HANS`` is not normalize.py's ``_HAN``: it holds U+3007, the
  private-use E815–E864, U+FA18 and the extensions C to I).
- ``chars.txt``: ``<code point in lowercase hex> <reading>,<reading>,…``, every entry of PINYIN_DICT by code point,
  its readings in Style.NORMAL in PINYIN_DICT's order, duplicates kept.
- ``phrases.txt``: ``<phrase> <syllable> <syllable> …``, every entry of PHRASES_DICT, each syllable the Style.NORMAL
  of the phrase's first reading of that character (all ``lazy_pinyin`` reads), in UTF-16 order, which the phone's
  binary search keeps.

The vectors (``helpers.corpus.jsonl``):

- ``vectors/pinyin/lazy.jsonl``: ``pypinyin.lazy_pinyin(text, errors=…)``, ``errors`` "default" and "ignore", over
  every phrase that holds a polyphone (a character PINYIN_DICT gives more than one reading), ``PHRASES_A_TEXT`` a
  text joined by a separator, so each is a run of its own; the texts that end mmseg's cut early (``_mmseg_stops``:
  '隆重庆' reads long zhong qing, never long chong qing); ``MIXES`` seeded random mixes of phrases, their prefixes,
  polyphones, Han with no reading, supplementary-plane Han, Latin, digits, kana, Hangul, punctuation and spaces; the
  string literals of tests/test_normalize.py and tests/test_search.py that hold a character beyond ASCII; and the
  edges (empty, each of RE_HANS's ranges' ends and their neighbours, newlines).
- ``vectors/pinyin/heteronyms.jsonl``: ``heteronyms(text)`` below, each character's
  ``pinyin(c, style=Style.NORMAL, heteronym=True)[0]``, over every code point of PINYIN_DICT, ``CHARS_A_RECORD`` a
  record in order, then characters with no reading. A record is read one code point at a time, never as one call:
  its ``out`` is a list of each code point's answer, which its ``note`` says (``HETERONYMS_NOTE``), for a replay that
  goes by ``fn``.

Each vector's test also reads it back from the data alone, as the phone does (``_Data``). pypinyin is imported where
it is used: its dictionaries take a quarter of a second to load, which collecting any other test module never pays.
"""

from __future__ import annotations

import ast
import bisect
import functools
import random
from pathlib import Path

import pytest
from helpers.corpus import DATA, VECTORS, check, jsonl

MADE_BY = "tests/test_conformance_pinyin.py"
PINYIN_DATA = DATA / "pinyin"
TESTS = Path(__file__).resolve().parent
LITERALS_FROM = ("test_normalize.py", "test_search.py")

SEED = 20261103
MIXES = 3000
PHRASES_A_TEXT = 40
CHARS_A_RECORD = 100
SEPARATORS = (" ", "，", "\n", "a", "、", " · ")
LAZY = "pypinyin.lazy_pinyin"
HETERONYMS = "test_conformance_pinyin.heteronyms"
HETERONYMS_NOTE = ("out[i] is pinyin(c, style=Style.NORMAL, heteronym=True)[0] of the i-th code point c of args[0]: "
                   "Pinyin.heteronyms(c), a code point at a time")
ERRORS = ("default", "ignore")


def normal(reading: str) -> str:
    """A reading in Style.NORMAL, by pypinyin's own converter."""
    from pypinyin.style._utils import replace_symbol_to_no_symbol

    return replace_symbol_to_no_symbol(reading)


def heteronyms(text: str) -> list[list[str]]:
    """Each character's readings as normalize._pinyin_readings asks for them, a character at a time."""
    from pypinyin import Style, pinyin

    return [pinyin(c, style=Style.NORMAL, heteronym=True)[0] for c in text]


@functools.cache
def han_ranges() -> tuple[tuple[int, int], ...]:
    """The code points RE_HANS matches alone, as ranges: read from the pattern itself, every code point tried."""
    from pypinyin.constants import RE_HANS

    ranges: list[list[int]] = []
    for cp in range(0x110000):
        if RE_HANS.match(chr(cp)):
            if ranges and ranges[-1][1] == cp - 1:
                ranges[-1][1] = cp
            else:
                ranges.append([cp, cp])
    return tuple((a, b) for a, b in ranges)


def _utf16(s: str) -> bytes:
    return s.encode("utf-16-be", "surrogatepass")


# --- the data ----------------------------------------------------------------------------------------------------


def hans_txt() -> str:
    return "".join(f"{a:x} {b:x}\n" for a, b in han_ranges())


@functools.cache
def chars_txt() -> str:
    from pypinyin.constants import PINYIN_DICT

    return "".join(f"{cp:x} {','.join(normal(r) for r in PINYIN_DICT[cp].split(','))}\n" for cp in sorted(PINYIN_DICT))


@functools.cache
def phrases_txt() -> str:
    from pypinyin.constants import PHRASES_DICT

    return "".join(f"{p} {' '.join(normal(syllable[0]) for syllable in PHRASES_DICT[p])}\n"
                   for p in sorted(PHRASES_DICT, key=_utf16))


def test_hans_txt_is_the_ranges_re_hans_matches():
    check(PINYIN_DATA / "hans.txt", hans_txt())


def test_chars_txt_is_pinyin_dict_in_normal_style():
    check(PINYIN_DATA / "chars.txt", chars_txt())


def test_phrases_txt_is_phrases_dict_in_normal_style():
    check(PINYIN_DATA / "phrases.txt", phrases_txt())


def test_what_the_phone_takes_for_granted_of_the_dictionaries():
    """The data's format, and the phone's port, rest on these: a bump of pypinyin that breaks one says so here."""
    from pypinyin.constants import PHRASES_DICT, PINYIN_DICT, RE_HANS

    syllable = set("abcdefghijklmnopqrstuvwxyzê")
    for cp, readings in PINYIN_DICT.items():
        assert RE_HANS.match(chr(cp)), f"U+{cp:04X} has readings but RE_HANS doesn't match it"
        for r in readings.split(","):
            assert normal(r) and set(normal(r)) <= syllable, f"U+{cp:04X} reads {r!r}"
    for phrase, readings in PHRASES_DICT.items():
        # heteronyms() reads a character from chars.txt alone, never as a phrase of one character.
        assert len(phrase) > 1, f"{phrase!r} is a phrase of one character"
        assert RE_HANS.match(phrase), f"{phrase!r} holds a character RE_HANS doesn't match"
        assert len(readings) == len(phrase), f"{phrase!r} has {len(readings)} syllables"
        assert all(r and normal(r[0]) and set(normal(r[0])) <= syllable for r in readings), phrase
    # A Han character with no reading reads as itself, Style.NORMAL leaving it as it is.
    for a, b in han_ranges():
        for cp in range(a, b + 1):
            if cp not in PINYIN_DICT:
                assert normal(chr(cp)) == chr(cp), f"U+{cp:04X}"


# --- the vectors -------------------------------------------------------------------------------------------------


def _polyphone_phrases() -> list[str]:
    from pypinyin.constants import PHRASES_DICT, PINYIN_DICT

    poly = {cp for cp, readings in PINYIN_DICT.items() if "," in readings}
    return [p for p in sorted(PHRASES_DICT) if any(ord(c) in poly for c in p)]


def _phrase_texts() -> list[str]:
    phrases = _polyphone_phrases()
    texts = []
    for n, at in enumerate(range(0, len(phrases), PHRASES_A_TEXT)):
        texts.append(SEPARATORS[n % len(SEPARATORS)].join(phrases[at:at + PHRASES_A_TEXT]))
    return texts


def _unread_han() -> list[int]:
    from pypinyin.constants import PINYIN_DICT

    return [cp for a, b in han_ranges() for cp in range(a, b + 1) if cp not in PINYIN_DICT]


def _mixes() -> list[str]:
    from pypinyin.constants import PHRASES_DICT, PINYIN_DICT

    rng = random.Random(SEED)
    phrases = sorted(PHRASES_DICT)
    read = sorted(PINYIN_DICT)
    poly = [cp for cp in read if "," in PINYIN_DICT[cp]]
    unread = _unread_han()
    supplementary_read = [cp for cp in read if cp > 0xFFFF]
    supplementary_unread = [cp for cp in unread if cp > 0xFFFF]
    others = [" ", "  ", "，", "。", "、", "·", "-", "(", ")", "（", "）", "《", "》", "'", "!", "?", "\n", "\t", "\u3000",
              "/", "&", "ー", "…", "\r\n"]
    latin = ["Song", "dongye", "a", "ABC", "ü", "é", "ß", "Ⅻ", "ﬁ", "Ａ", "x", "Đ", "ı"]
    digits = ["0", "2011", "２０１１", "٣", "½", "①"]
    specials = ["〇", "\ufa18"] + [chr(cp) for cp in range(0xE815, 0xE865)]

    def piece() -> str:
        kind = rng.choices(
            ("phrase", "prefix", "poly", "read", "unread", "supp", "supp_unread", "special", "other", "latin",
             "digit", "kana", "hangul", "emoji"),
            weights=(6, 3, 4, 2, 1, 1, 1, 1, 3, 1, 1, 1, 1, 1))[0]
        if kind == "phrase":
            return rng.choice(phrases)
        if kind == "prefix":
            p = rng.choice(phrases)
            return p[:rng.randrange(1, len(p))]
        if kind == "poly":
            return chr(rng.choice(poly))
        if kind == "read":
            return chr(rng.choice(read))
        if kind == "unread":
            return chr(rng.choice(unread))
        if kind == "supp":
            return "".join(chr(rng.choice(supplementary_read)) for _ in range(rng.randint(1, 3)))
        if kind == "supp_unread":
            return chr(rng.choice(supplementary_unread))
        if kind == "special":
            return rng.choice(specials)
        if kind == "other":
            return rng.choice(others)
        if kind == "latin":
            return rng.choice(latin)
        if kind == "digit":
            return rng.choice(digits)
        if kind == "kana":
            return "".join(chr(rng.choice((rng.randint(0x3041, 0x3096), rng.randint(0x30A1, 0x30FA))))
                           for _ in range(rng.randint(1, 3)))
        if kind == "hangul":
            return chr(rng.randint(0xAC00, 0xD7A3))
        return rng.choice(["🎸", "😀", "\U0001F004", "\U000E0041"])

    return ["".join(piece() for _ in range(rng.randint(1, 8))) for _ in range(MIXES)]


def _mmseg_stops() -> list[str]:
    """Texts that end mmseg's cut early: each begins a phrase whole and none of its prefixes is one, so each of its
    characters is a word alone, though cut again from its second character on it would read a phrase."""
    from pypinyin import lazy_pinyin
    from pypinyin.constants import PHRASES_DICT

    found = set()
    for phrase in PHRASES_DICT:
        for k in range(2, len(phrase)):
            text = phrase[:k]
            if text in PHRASES_DICT:
                break
            if (any(text[i:j] in PHRASES_DICT for i in range(1, k - 1) for j in range(i + 2, k + 1))
                    and lazy_pinyin(text) != lazy_pinyin(text[0]) + lazy_pinyin(text[1:])):
                found.add(text)
    return sorted(found)


def _literals() -> list[str]:
    found: set[str] = set()
    for name in LITERALS_FROM:
        tree = ast.parse((TESTS / name).read_text("utf-8"))
        found |= {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
                  and isinstance(node.value, str) and not node.value.isascii()
                  and not any(0xD800 <= ord(c) <= 0xDFFF for c in node.value)}
    return sorted(found)


def _edges() -> list[str]:
    texts = ["", " ", "a", "abc", "\n", "中", "中\n", "\n中\n", "中 国", "中国人", "绿色", "中心", "朝阳", "那些", "重庆",
             "银行", "行", "长大", "宋冬野", "安和桥", "你好，我是中国人，我爱我的祖国", "〇〇七", "\ue815\ue864", "\ufa18",
             "\U00020000", "\U0002a6df", "\U00020000\U00020001", "中\U00020000国", "ü", "Ａ１"]
    for a, b in han_ranges():
        texts += [chr(a), chr(b), chr(a) + chr(b), chr(a - 1) + chr(a) + chr(b) + chr(b + 1)]
    return texts


def lazy_records() -> tuple[dict, ...]:
    from pypinyin import lazy_pinyin

    texts = _phrase_texts() + _mmseg_stops() + _mixes() + _literals() + _edges()
    return tuple({"fn": LAZY, "args": [text], "kw": {"errors": errors}, "out": lazy_pinyin(text, errors=errors)}
                 for text in texts for errors in ERRORS)


def heteronym_records() -> tuple[dict, ...]:
    from pypinyin.constants import PINYIN_DICT

    read = sorted(PINYIN_DICT)
    texts = ["".join(chr(cp) for cp in read[at:at + CHARS_A_RECORD]) for at in range(0, len(read), CHARS_A_RECORD)]
    unread = _unread_han()
    texts.append("".join(chr(cp) for cp in unread[::500]))
    texts.append("".join(chr(a) + chr(b) for a, b in han_ranges()))
    texts.append("a Z0 \n\t\x00ü·ー가😀\U000E0041（")
    return tuple({"fn": HETERONYMS, "args": [text], "kw": {}, "note": HETERONYMS_NOTE, "out": heteronyms(text)}
                 for text in texts)


# Its records are built once, pypinyin reading 45,502 phrases in both modes: about 3 s, over plan §3's budget.
@pytest.mark.slow
def test_lazy_vectors_are_pypinyins_answers_and_the_data_reads_each():
    from pypinyin import lazy_pinyin
    from pypinyin.constants import PINYIN_DICT

    lazy = lazy_records()
    check(VECTORS / "pinyin" / "lazy.jsonl", jsonl(lazy, corpus="pinyin/lazy", made_by=MADE_BY))
    # They hold what they mean to.
    texts = {r["args"][0] for r in lazy}
    phrase_texts = _phrase_texts()
    batched = [p for n, t in enumerate(phrase_texts) for p in t.split(SEPARATORS[n % len(SEPARATORS)])]
    assert batched == _polyphone_phrases() and set(phrase_texts) <= texts
    assert {"绿色", "中心", "朝阳"} <= texts and len(_mmseg_stops()) > 20 and "隆重庆" in texts
    assert any(any(ord(c) > 0xFFFF and ord(c) in PINYIN_DICT for c in t) for t in texts)
    # The two modes differ, and mmseg reads a run as more than its characters alone.
    assert any(a["out"] != b["out"] for a, b in zip(lazy[::2], lazy[1::2]))
    assert lazy_pinyin("朝阳") == ["zhao", "yang"] and lazy_pinyin("绿色") == ["lv", "se"]
    # The data alone reads each, as the phone does.
    data = _Data(hans_txt(), chars_txt(), phrases_txt())
    for record in lazy:
        text, errors = record["args"][0], record["kw"]["errors"]
        assert data.lazy(text, errors) == record["out"], (text, errors)


def test_heteronym_vectors_are_pypinyins_answers_and_the_data_reads_each():
    from pypinyin.constants import PINYIN_DICT

    records = heteronym_records()
    check(VECTORS / "pinyin" / "heteronyms.jsonl", jsonl(records, corpus="pinyin/heteronyms", made_by=MADE_BY))
    read = {cp for r in records for cp in map(ord, r["args"][0]) if cp in PINYIN_DICT}
    assert read == set(PINYIN_DICT)
    data = _Data(hans_txt(), chars_txt(), "")
    for record in records:
        assert [data.heteronyms(ord(c)) for c in record["args"][0]] == record["out"], record["args"][0]


# --- the phone's reading, from the data alone ----------------------------------------------------------------------


class _Data:
    """The three files as core.pinyin.Pinyin reads them: hans.txt's ranges, chars.txt's readings, phrases.txt's
    phrases in UTF-16 order (a binary search finds a word, and whether it begins a phrase)."""

    def __init__(self, hans: str, chars: str, phrases: str):
        self.starts, self.ends = [], []
        for line in hans.splitlines():
            a, b = line.split(" ")
            self.starts.append(int(a, 16))
            self.ends.append(int(b, 16))
        self.chars = {}
        for line in chars.splitlines():
            cp, readings = line.split(" ")
            self.chars[int(cp, 16)] = readings.split(",")
        self.phrases, self.syllables = [], []
        for line in phrases.splitlines():
            phrase, *syllables = line.split(" ")
            self.phrases.append(_utf16(phrase))
            self.syllables.append(syllables)
        assert self.phrases == sorted(self.phrases)

    def is_han(self, cp: int) -> bool:
        i = bisect.bisect_right(self.starts, cp) - 1
        return i >= 0 and cp <= self.ends[i]

    def _at(self, word: str) -> tuple[bool, int | None]:
        """Whether ``word`` begins a phrase, and the phrase's index when it is one."""
        key = _utf16(word)
        i = bisect.bisect_left(self.phrases, key)
        found = i < len(self.phrases) and self.phrases[i].startswith(key)
        return found, i if found and self.phrases[i] == key else None

    def cut(self, run: str) -> list[str]:
        words, start = [], 0
        while start < len(run):
            valid = None
            for end in range(start + 1, len(run) + 1):
                prefix, phrase = self._at(run[start:end])
                if not prefix:
                    if valid is None:
                        valid = start + 1
                    break
                if phrase is not None:
                    valid = end
            else:
                if valid is None:  # the rest begins a phrase, and none of its prefixes is one
                    return words + list(run[start:])
            words.append(run[start:valid])
            start = valid
        return words

    def lazy(self, text: str, errors: str) -> list[str]:
        out: list[str] = []
        runs: list[str] = []
        for c in text:
            if runs and self.is_han(ord(c)) == self.is_han(ord(runs[-1][-1])):
                runs[-1] += c
            else:
                runs.append(c)
        for run in runs:
            if not self.is_han(ord(run[0])):
                out += [run] if errors == "default" else []
                continue
            for word in self.cut(run):
                _, phrase = self._at(word)
                if phrase is not None:
                    out += self.syllables[phrase]
                    continue
                for c in word:
                    if ord(c) in self.chars:
                        out.append(self.chars[ord(c)][0])
                    elif errors == "default":
                        out.append(c)
        return out

    def heteronyms(self, cp: int) -> list[str]:
        if not self.is_han(cp) or cp not in self.chars:
            return [chr(cp)]
        kept = list(dict.fromkeys(r for r in self.chars[cp] if r))
        return kept or [""]
