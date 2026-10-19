"""The ChordPro file caracole writes (``chordpro.to_chordpro``), read back for the viewer.

Only what that file holds is read: the ``title``, ``artist``, ``key`` and ``capo``
directives, ``comment`` (a section's name), tab and chorus environments, and lines
with ``[Chord]`` and ``[*mark]`` in them. Other directives and ``#`` comment lines are
skipped. The escapes ChordPro needed (a backslash written ``\\u005c``) are undone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from caracole.autochords.merge import AUTO_MARKER


@dataclass(frozen=True)
class Lyrics:
    """A sung line: (chord, text) parts. The chord is an index into ``Sheet.chords``, a repeat
    mark ("x2") as text, or None for the words before the first chord."""

    parts: list[tuple[int | str | None, str]]


@dataclass(frozen=True)
class ChordRow:
    """A line of chords alone: chord indexes, and repeat marks ("x2") as text."""

    items: list[int | str]


@dataclass(frozen=True)
class Text:
    text: str


@dataclass(frozen=True)
class Tab:
    lines: list[str]


@dataclass(frozen=True)
class Blank:
    """The space between two stanzas of a section."""


Line = Lyrics | ChordRow | Text | Tab | Blank


@dataclass
class Section:
    label: str | None
    chorus: bool = False
    lines: list[Line] = field(default_factory=list)


@dataclass
class Sheet:
    title: str = ""
    artist: str = ""
    key: str | None = None
    capo: int | None = None
    auto: bool = False
    chords: list[str] = field(default_factory=list)  # as written, each once, in order of appearance
    sections: list[Section] = field(default_factory=list)


_DIRECTIVE = re.compile(r"\s*\{\s*([A-Za-z_]+)\s*(?::\s*(.*?))?\s*\}\s*")
_TOKEN = re.compile(r"\[([^\]]*)\]")
_CHORUS = re.compile(r"(?i)chorus|coro|estribillo|refr[aeá]i?n|副歌")
_ESCAPED_BACKSLASH = "\\" + "u005c"
_COMMENTS = {"comment", "c", "comment_italic", "ci", "comment_box", "cb", "highlight"}


def parse_sheet(text: str) -> Sheet:
    """The sheet a ChordPro text holds."""
    sheet = Sheet()
    index: dict[str, int] = {}
    section = Section(None)
    sheet.sections.append(section)
    tab: list[str] | None = None

    def chord(name: str) -> int:
        if name not in index:
            index[name] = len(sheet.chords)
            sheet.chords.append(name)
        return index[name]

    def start(label: str | None, chorus: bool = False) -> None:
        nonlocal section
        section = Section(label, chorus or bool(label and _CHORUS.search(label)))
        sheet.sections.append(section)

    for raw in text.splitlines():
        line = raw.replace(_ESCAPED_BACKSLASH, "\\")
        if tab is not None:
            if (d := _DIRECTIVE.fullmatch(line)) and d.group(1).lower() in ("end_of_tab", "eot"):
                section.lines.append(Tab(tab))
                tab = None
            else:
                tab.append(line)
            continue
        if d := _DIRECTIVE.fullmatch(line):
            name, value = d.group(1).lower(), (d.group(2) or "").strip()
            if name in ("title", "t"):
                sheet.title = value
            elif name == "artist":
                sheet.artist = value
            elif name == "key":
                sheet.key = value or None
            elif name == "capo":
                sheet.capo = int(value) if value.isdigit() and int(value) > 0 else None
            elif name in _COMMENTS:
                if value == AUTO_MARKER:
                    sheet.auto = True
                else:
                    start(value)
            elif name in ("start_of_tab", "sot"):
                tab = []
            elif name in ("start_of_chorus", "soc"):
                start(value or None, chorus=True)
            elif name in ("end_of_chorus", "eoc"):
                start(None)
            continue
        if line.startswith("#"):
            continue
        section.lines.append(_line(line, chord))
    if tab is not None:
        section.lines.append(Tab(tab))
    for s in sheet.sections:
        while s.lines and isinstance(s.lines[0], Blank):
            s.lines.pop(0)
        while s.lines and isinstance(s.lines[-1], Blank):
            s.lines.pop()
    sheet.sections = [s for s in sheet.sections if s.lines or s.label]
    return sheet


def _line(line: str, chord) -> Line:
    if not line.strip():
        return Blank()
    pieces = _TOKEN.split(line)  # text, token, text, token, ..., text
    if len(pieces) == 1:
        return Text(line.rstrip())
    parts: list[tuple[int | str | None, str]] = []
    if pieces[0]:
        parts.append((None, pieces[0]))
    for token, after in zip(pieces[1::2], pieces[2::2], strict=True):
        mark = token.startswith("*")
        parts.append((token[1:].strip() if mark else chord(token.strip()), after))
    if all(not text.strip() for _, text in parts):
        return ChordRow([item for item, _ in parts if item is not None])
    return Lyrics(parts)
