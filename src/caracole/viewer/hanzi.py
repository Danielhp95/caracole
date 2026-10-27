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
with no Chinese, has none. A song's title and its artist's name are each judged alone (``names``), as a title from
wanted.txt may be written in the other script than its sheet. Only Chinese characters change: whatever else a text
holds (a chord, a letter, punctuation) stays as written.

A conversion keeps a text's length, a character for a character, as each of OpenCC's phrases is as long as what it
becomes: the viewer cuts it where the page cut the text (into its columns, under its chords), and each reading of the
data's ``pinyin`` stays with its character. A conversion that came out longer or shorter (never seen) is made again a
character at a time, and a character whose conversion isn't one character stays as written. OpenCC's rare
characters a font may lack (its ``TSCharactersExt``) are left out.

OpenCC is imported by the function that converts, never by importing this module: the page of a sheet with no
Chinese, and every command, start without it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import cache

from caracole.normalize import has_han


def names(texts: list[str]) -> dict[str, dict[str, str]]:
    """``scripts`` of each of ``texts`` alone: a song's title and its artist's name, each written in the script most
    of its own characters are, which may be the other one than its sheet's (a title from wanted.txt)."""
    shown: dict[str, dict[str, str]] = {"simplified": {}, "traditional": {}}
    for text in dict.fromkeys(texts):
        for script, table in scripts([text]).items():
            shown[script].update(table)
    return shown


def scripts(texts: list[str]) -> dict[str, dict[str, str]]:
    """For a sheet's ``texts`` (each as its page writes it: a line's words whole, a section's label, a tab), each
    text with Chinese in Simplified characters (``simplified``) and in Traditional ones (``traditional``), where
    that isn't the text as written, each as long as its text."""
    chinese = [text for text in dict.fromkeys(texts) if has_han(text)]
    traditional = written_in_traditional(chinese)
    shown: dict[str, dict[str, str]] = {"simplified": {}, "traditional": {}}
    for script in shown:
        if (convert := converter(script, traditional=traditional)) is None:
            continue
        for text in chinese:
            if (converted := convert(text)) != text:
                shown[script][text] = converted
    return shown


def converter(script: str, *, traditional: bool) -> Callable[[str], str] | None:
    """What writes a sheet's texts in ``script`` ("simplified", "traditional"), the sheet written in Traditional
    characters or not (``traditional``: ``written_in_traditional``); None where they show as written."""
    config = ("tw2s" if traditional else "t2s") if script == "simplified" else None if traditional else "s2tw"
    return None if config is None else lambda text: _converted(config, text)


# A ChordPro directive ("{title: 斑馬斑馬}"), and a chord or an annotation among a line's words ("[Am]", "[*x02210]")
_DIRECTIVE = re.compile(r"(\s*\{\s*)([A-Za-z_]+)(.*)", re.S)
_TOKEN = re.compile(r"\[[^\]]*\]")
# The directives that name the song, each judged alone, as its page judges its names (``names``)
_NAMED = frozenset({"title", "t", "subtitle", "st", "artist"})


def chordpro(text: str, script: str, *, traditional: bool) -> str:
    """A ChordPro text (a PDF's, render.py's) in ``script``'s characters, as the sheet's page shows it there: its
    sheet written in Traditional characters or not (``traditional``). Each line's words whole, its chords and
    annotations left where they are (a line's columns, on the page); each directive's text; and the title, the
    subtitle and the artist each judged alone (``names``). A line for a line, each as long as it was."""
    words = converter(script, traditional=traditional)
    out = []
    for line in text.splitlines(keepends=True):
        if (found := _DIRECTIVE.fullmatch(line)) is not None and line.lstrip().startswith("{"):
            convert = (lambda value: _named(value, script)) if found.group(2).lower() in _NAMED else words
            out.append(found.group(1) + found.group(2) + (convert(found.group(3)) if convert else found.group(3)))
        else:
            out.append(_between_tokens(line, words) if words else line)
    return "".join(out)


def _named(text: str, script: str) -> str:
    """A name (a title, an artist's) in ``script``, judged alone (``names``)."""
    return scripts([text])[script].get(text, text)


def _between_tokens(line: str, convert: Callable[[str], str]) -> str:
    """``line``'s words converted whole, its chords and annotations (``[...]``) where they were."""
    pieces = _TOKEN.split(line)
    tokens = _TOKEN.findall(line)
    shown = convert("".join(pieces))
    out, at = [], 0
    for n, piece in enumerate(pieces):
        out.append(shown[at:at + len(piece)])
        at += len(piece)
        if n < len(tokens):
            out.append(tokens[n])
    return "".join(out)


def written_in_traditional(texts: list[str]) -> bool:
    """Whether more of ``texts``' characters are Traditional's alone than Simplified's alone, each read on its own,
    each text counted once."""
    characters = [c for text in dict.fromkeys(texts) for c in text if has_han(c)]
    alone = {c: (_converted("t2s", c) != c, _converted("s2tw", c) != c) for c in set(characters)}
    return sum(alone[c][0] for c in characters) > sum(alone[c][1] for c in characters)


def _converted(config: str, text: str) -> str:
    """``text`` as OpenCC's ``config`` converts it, as long as it is, its Chinese characters alone: whatever else
    it holds (letters, a chord, punctuation) stays as written."""
    convert = _converter(config)
    whole = convert(text)
    if len(whole) != len(text):
        whole = "".join(one if len(one := convert(c)) == 1 else c for c in text)
    return "".join(after if has_han(before) else before for before, after in zip(text, whole))


@cache
def _converter(config: str) -> Callable[[str], str]:
    from opencc import OpenCC

    return OpenCC(config, include_tofu_risk_dictionaries=False).convert
