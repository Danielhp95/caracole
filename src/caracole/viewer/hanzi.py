"""A sheet's Chinese in Simplified characters and in Traditional ones, for the viewer's Chinese characters (page.py's
data ``hanzi``): Simplified at first, Traditional once chosen, whichever the sheet is written in.

Each text is converted whole, word by word, by OpenCC: its dictionaries of phrases come before its characters'.
Simplified into Traditional is one to many (发 is 發 in 发现 and 髮 in 头发; 后 is 後 in 后来 and stays in 皇后; 干 is
乾 in 干净, 幹 in 干活 and stays in 干涉), and Traditional into Simplified is, here and there, too (著 is 着 in 睡著,
where Taiwan writes it so, and stays in 著名; 乾 is 干 in 乾淨 and stays in 乾坤): normalize.py's table, a character
for a character, is for comparing names, never for showing them.

A sheet is written in Traditional characters when more of its characters are Traditional's alone (OpenCC writes each,
on its own, otherwise in Simplified) than Simplified's alone. Its Simplified is OpenCC's from Taiwan's standard
(``tw2s``), which reads the OpenCC standard's and Hong Kong's variants too (爲, 裏); a Simplified sheet's is OpenCC's
from Traditional (``t2s``), which leaves Simplified as written and changes a stray Traditional character. A Simplified
sheet's Traditional is Taiwan's standard (``s2tw``: 為, 裡, 著); a Traditional sheet's is as written, as converting
into Traditional changes some Traditional texts (是只會 is 是隻會, 鄰里 鄰裡). A text the same in either script, or
with no Chinese, has none.

A conversion keeps a text's length, a character for a character, as each of OpenCC's phrases is as long as what it
becomes: the viewer cuts it where the page cut the text (into its columns, under its chords), and each reading of the
data's ``pinyin`` stays with its character. A conversion that came out longer or shorter (never seen) is made again a
character at a time, and a character whose conversion isn't one character stays as written. OpenCC's rare
characters a font may lack (its ``TSCharactersExt``) are left out.

OpenCC is imported by the function that converts, never by importing this module: the page of a sheet with no
Chinese, and every command, start without it.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache

from caracole.normalize import has_han


def scripts(texts: list[str]) -> dict[str, dict[str, str]]:
    """For a sheet's ``texts`` (each as its page writes it: a line's words whole, a section's label, a tab), each
    text with Chinese in Simplified characters (``simplified``) and in Traditional ones (``traditional``), where
    that isn't the text as written, each as long as its text."""
    chinese = [text for text in dict.fromkeys(texts) if has_han(text)]
    traditional = _written_in_traditional(chinese)
    shown: dict[str, dict[str, str]] = {"simplified": {}, "traditional": {}}
    for script, config in (("simplified", "tw2s" if traditional else "t2s"),
                           ("traditional", None if traditional else "s2tw")):
        if config is None:
            continue
        for text in chinese:
            if (converted := _converted(config, text)) != text:
                shown[script][text] = converted
    return shown


def _written_in_traditional(texts: list[str]) -> bool:
    """Whether more of ``texts``' characters are Traditional's alone than Simplified's alone, each read on its own."""
    characters = [c for text in texts for c in text if has_han(c)]
    alone = {c: (_converted("t2s", c) != c, _converted("s2tw", c) != c) for c in set(characters)}
    return sum(alone[c][0] for c in characters) > sum(alone[c][1] for c in characters)


def _converted(config: str, text: str) -> str:
    """``text`` as OpenCC's ``config`` converts it, as long as it is."""
    convert = _converter(config)
    whole = convert(text)
    if len(whole) == len(text):
        return whole
    return "".join(one if len(one := convert(c)) == 1 else c for c in text)


@cache
def _converter(config: str) -> Callable[[str], str]:
    from opencc import OpenCC

    return OpenCC(config, include_tofu_risk_dictionaries=False).convert
