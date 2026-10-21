"""The ChordPro file caracole writes (``chordpro.to_chordpro``), read back for the viewer.

Only what that file holds is read: the ``title``, ``artist``, ``key`` and ``capo``
directives, ``comment`` (a section's name), tab and chorus environments, and lines
with ``[Chord]`` and ``[*mark]`` in them; and the fingerings a sheet of yours may give
its chords (``define`` and ``chord``, kept as written for ``voicings.parse_define``).
Other directives and ``#`` comment lines are skipped. The escapes ChordPro needed (a
backslash written ``\\u005c``) are undone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from caracole.autochords.merge import AUTO_MARKER
from caracole.viewer.theory import Chord
from caracole.viewer.voicings import Position, chord_legend


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
    defines: list[str] = field(default_factory=list)  # each {define} and {chord}, as written after its colon


_DIRECTIVE = re.compile(r"\s*\{\s*([A-Za-z_]+)\s*(?::\s*(.*?))?\s*\}\s*")
_TOKEN = re.compile(r"\[([^\]]*)\]")
_FRET = re.compile(r"[0-9]+")  # ASCII digits: str.isdigit takes "²", which int() refuses
_CHORUS = re.compile(r"(?i)chorus|coro|estribillo|refr[aeá]i?n|副歌")
_ESCAPED_BACKSLASH = "\\" + "u005c"
COMMENTS = {"comment", "c", "comment_italic", "ci", "comment_box", "cb", "highlight"}  # a section's name


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
                sheet.capo = int(value) if _FRET.fullmatch(value) and int(value) > 0 else None
            elif name in COMMENTS:
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
            elif name in ("define", "chord") and value:
                sheet.defines.append(value)
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


def directive(line: str) -> tuple[str, str] | None:
    """A directive line as ``parse_sheet`` reads it: its name in lower case and its value, its
    escapes undone (``("comment", "Verse 1")`` for "{comment: Verse 1}"); None for any other line."""
    d = _DIRECTIVE.fullmatch(line.replace(_ESCAPED_BACKSLASH, "\\"))
    return None if d is None else (d.group(1).lower(), (d.group(2) or "").strip())


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


# --- the preamble --------------------------------------------------------------------------------


def written(line: Line, names: list[str]) -> str:
    """A line as the sheet writes it, its chords and marks among its words: "Cadd9 (x32033)"."""
    if isinstance(line, Text):
        return line.text
    if isinstance(line, ChordRow):
        return " ".join(names[i] if isinstance(i, int) else i for i in line.items)
    if isinstance(line, Lyrics):
        return "".join((names[c] if isinstance(c, int) else c or "") + text for c, text in line.parts)
    return ""


def _played(line: Line, names: list[str]) -> bool:
    return not isinstance(line, (Text, Blank)) and not chord_legend(written(line, names))


def preamble_section(sheet: Sheet) -> Section | None:
    """What a tab says before its first section (its tabber's notes, a link, a chord legend), or None:
    an unlabelled first section, before another, up to its first tab (UG's first label is often inside
    it: "[Intro]"), with nothing played in it. Its lines are text and chords given with their
    fingerings (``voicings.chord_legend``); chords alone there are the song's intro and words sung
    there its first verse, and none of it is folded away. The viewer's rule, and the PDF's."""
    first = sheet.sections[0] if len(sheet.sections) > 1 else None
    if first is None or first.label or first.chorus:
        return None
    lines: list[Line] = []
    for line in first.lines:
        if isinstance(line, Tab):
            break
        if _played(line, sheet.chords):
            return None
        lines.append(line)
    while lines and isinstance(lines[-1], Blank):
        lines.pop()
    return Section(None, lines=lines) if lines else None


# A tuning a note names: "half step down", "Eb standard", or "drop" and a note ("Drop D", "drop C#"),
# never a word ("drop by", "drop down"); "drop a" only before "tuning", a sign or the note's end, as
# a tabber also asks to "drop a comment".
_TUNING_NAME = re.compile(
    r"(?i:\bhalf[- ]step down\b)|(?i:\b[a-g]b standard\b)"
    r"|(?i:\bdrop)[ -](?:[B-Gb-g][#b♯♭]?(?![\w'’-])|[Aa][#b♯♭]?(?=\s+(?i:tuning)\b|\s*(?:[^\w\s'’-]|$)))"
)
# Else the tuning a "Tuning:" label gives, up to a comma or a semicolon ("Tuning: DADGAD")
_TUNING_LABEL = re.compile(r"(?i)\btuning\s*[:=]\s*(?P<value>[^,;|]+)")
_CAPO = re.compile(r"(?i)\bcapo\b\D{0,6}(\d+)")


@dataclass(frozen=True)
class Preamble:
    notes: tuple[str, ...]  # the text lines folded away (not tab, not legend)
    legend: tuple[tuple[Chord, Position], ...]  # from voicings.chord_legend
    tabs: tuple[tuple[int, int], ...]  # (start, end) line spans of tab blocks inside it: always (): the rule ends the preamble at the first tab, so none is inside it
    tuning: str | None  # e.g. "Eb standard", "half step down", "Drop D"
    capo_note: str | None  # e.g. "Capo 2"
    end: int  # index of the first body line


def split_preamble(lines: list[str]) -> Preamble:
    """The preamble of a ChordPro text's lines by the viewer's rule (``preamble_section``): what
    it holds, and ``end``, the index of the first line after it (``0`` when there is none)."""
    sheet = parse_sheet("\n".join(lines))
    section = preamble_section(sheet)
    if section is None:
        return Preamble((), (), (), None, None, 0)
    notes: list[str] = []
    legend: list[tuple[Chord, Position]] = []
    for line in section.lines:
        text = written(line, sheet.chords)
        found = chord_legend(text)
        if found:
            legend += found
        elif isinstance(line, Text):
            notes.append(text.strip())
    tuning = capo = None
    for note in notes:
        if tuning is None:
            tuning = _tuning(note)
        if capo is None and (m := _CAPO.search(note)):
            capo = f"Capo {int(m.group(1))}"
    return Preamble(tuple(notes), tuple(legend), (), tuning, capo, _end_of(lines, len(section.lines)))


def _tuning(note: str) -> str | None:
    """The tuning a note names (``_TUNING_NAME``), else the one after its "Tuning:" label, or None:
    a note that only talks about the tuning names none, and standard tuning goes unsaid."""
    if named := _TUNING_NAME.search(note):
        return named.group(0)
    label = _TUNING_LABEL.search(note)
    if label is None:
        return None
    value = label.group("value").strip().rstrip(".").strip()
    if value.endswith(")") and value.count(")") > value.count("("):  # "(Tuning: DADGAD)"
        value = value[:-1].strip()
    letters = re.sub(r"[^a-z]", "", value.lower()).replace("tuning", "")
    return value if value and letters not in _STANDARD else None


_STANDARD = frozenset({"standard", "estandard", "eadgbe", "standardeadgbe", "estandardeadgbe"})


def _end_of(lines: list[str], count: int) -> int:
    """The index after the ``count``-th content line of the text (a line the parser keeps in a
    section: not a directive, a ``#`` comment, or inside a tab), and the blank lines after it."""
    seen, tab = 0, False
    for i, raw in enumerate(lines):
        line = raw.replace(_ESCAPED_BACKSLASH, "\\")
        if tab:
            tab = not ((d := _DIRECTIVE.fullmatch(line)) and d.group(1).lower() in ("end_of_tab", "eot"))
        elif (d := _DIRECTIVE.fullmatch(line)):
            tab = d.group(1).lower() in ("start_of_tab", "sot")
        elif not line.startswith("#") and (seen or line.strip()):  # parse_sheet drops a section's leading blanks
            seen += 1
        if seen == count and not tab:
            end = i + 1
            while end < len(lines) and not lines[end].strip():
                end += 1
            return end
    return len(lines)
