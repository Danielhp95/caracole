"""Each Chinese character's reading in pinyin, for the viewer's Pinyin (page.py's data ``pinyin``).

pypinyin reads each line whole, word by word from its phrase dictionary, so a character read two ways is read
as its word has it (长 is cháng in 长城, zhǎng in 成长), with its tone marks (zhǐ, not zhi3), and 不 and 一
in the tone they take before another syllable where its dictionary writes them so (不要 bú yào).

Its phrase dictionary is Simplified Chinese: read in Traditional characters, a word may go unrecognised (長城
zhǎng chéng). A line is read in Simplified characters (``normalize.simplified``, a character for a character,
so each reading stays with the character shown as the sheet writes it). Traditional writes 着 (zhe, zháo,
zhuó) as 著 too, which Simplified keeps for zhù (显著, 著名): in a sheet in Traditional characters (one that
Simplified would write otherwise), a 著 is read as 着 unless it is in a word Simplified writes with 著, which
pypinyin's phrase dictionary holds (显著, 名著, 执著) or, its reading being 著's first, leaves out
(``_ZHU_WORDS``). A sheet with kana is Japanese, whose kanji pinyin would misread: it has none.

pypinyin is imported by the function that reads, never by importing this module: the page of a sheet with
no Chinese, and every command, start without it.
"""

from __future__ import annotations

import re

from caracole.normalize import has_han, simplified

# Hiragana and katakana, full and half width; never the katakana middle dot (・), which Chinese writes too.
_KANA = re.compile("[\u3041-\u309f\u30a0-\u30fa\u30fc-\u30ff\u31f0-\u31ff\uff66-\uff9f]")

# Words Simplified writes with 著, read zhù, that pypinyin's phrase dictionary leaves out: their reading is
# 著's first, which it gives a 著 it finds in no word.
_ZHU_WORDS = frozenset({"著名", "著作", "著者", "著称", "著述", "著书", "著录", "著有"})
_LONGEST = 4  # characters in the longest word with 著 that pypinyin's phrase dictionary holds (an idiom)


def readings(lines: list[str]) -> list[list[str] | None] | None:
    """For each of a sheet's ``lines`` (each line's words whole), each character's reading, "" for one with
    none (a letter, a digit, a space, punctuation), or None for a line with no Chinese; None for a sheet whose
    lines have none at all, or have kana (Japanese)."""
    if not is_chinese(lines):
        return None
    traditional = any(simplified(line) != line for line in lines)
    return [_read(line, traditional) if has_han(line) else None for line in lines]


def is_chinese(lines: list[str]) -> bool:
    """Whether a sheet's ``lines`` are Chinese: some have Chinese characters, and none has kana (Japanese). The
    viewer's rule for its Pinyin and its Chinese characters (hanzi.py), and its PDFs' (render.py)."""
    return any(has_han(line) for line in lines) and not any(_KANA.search(line) for line in lines)


def _read(line: str, traditional: bool) -> list[str]:
    """Each character of ``line``'s reading, in context."""
    from pypinyin import Style, lazy_pinyin

    text = _as_read(line, traditional)
    found = lazy_pinyin(text, style=Style.TONE, errors=_none)
    if len(found) != len(text):  # never seen: each character on its own, then
        found = [(lazy_pinyin(c, style=Style.TONE, errors=_none) or [""])[0] for c in text]
    return [reading if has_han(c) else "" for c, reading in zip(line, found)]


def _none(chars: str) -> list[str]:
    """What pypinyin gives what it reads no pinyin in (letters, spaces, punctuation): "" a character."""
    return [""] * len(chars)


def _as_read(line: str, traditional: bool) -> str:
    """``line`` as pypinyin reads it: in Simplified characters, and, from a Traditional sheet, each 著 that is
    no word's of its own as 着."""
    text = simplified(line)
    if not traditional or "著" not in text:
        return text
    return "".join("着" if c == "著" and not _zhu(text, i) else c for i, c in enumerate(text))


def _zhu(text: str, i: int) -> bool:
    """Whether the 著 at ``i`` is in a word Simplified writes with 著 (``_ZHU_WORDS``, pypinyin's phrases)."""
    from pypinyin.constants import PHRASES_DICT

    for start in range(max(0, i - _LONGEST + 1), i + 1):
        for end in range(max(i + 1, start + 2), min(len(text), start + _LONGEST) + 1):
            if text[start:end] in _ZHU_WORDS or text[start:end] in PHRASES_DICT:
                return True
    return False
