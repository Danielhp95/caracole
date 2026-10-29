"""Ultimate Guitar sheet markup to ChordPro.

UG sheets, LaCuerda sheets (once ``lacuerda.py`` has turned ``<A>X</A>`` into
``[ch]X[/ch]``) and auto-chords sheets all use one markup:

- chords are ``[ch]X[/ch]`` on chord lines placed above lyric lines;
- ``[tab]…[/tab]`` wraps chord-and-lyric pairs, and real tablature;
- section headers are lines such as ``[Verse 1]`` or ``[Chorus]``.

A chord's position is its display column in the chord line once the tags are
removed, as UG shows the sheet in a monospace font. East Asian wide characters
(Chinese, for one) take two columns there, so they count as two here too
(``display_columns``), and auto-chords writes its chord lines in those columns.
"""

from __future__ import annotations

import re
import unicodedata

from caracole.viewer.theory import parse_chord

_CHORD = re.compile(r"\[ch\](.*?)\[/ch\]")
_TAB_MARK = re.compile(r"\[/?tab\]")
_SECTION = re.compile(r"\s*\[(?!/?(?:ch|tab)\])([^\[\]]+)\]\s*(.*?)\s*")
# Repeat marks ("x2", "(x4)", "2x", LaCuerda's "(4)") and no-chord marks keep
# their place on a chord line, as ChordPro annotations.
_MARK = re.compile(
    r"[(\[]\s*(?:[xX×]\s*\d+|\d+\s*[xX×]?)\s*[)\]]"
    r"|(?<!\w)(?:[xX×]\d+|\d+[xX×])(?!\w)"
    r"|(?<!\w)(?i:n\.?c\.?)(?!\w)"
)
# What else a chord line may hold: bar lines, dashes, slashes, beat dots, repeat signs.
_CHORD_LINE_REST = re.compile(r"[\s|/\\.,:;()*~–—-]*")
_STAFF = re.compile(r"\s*(?:[A-Ga-g][#b]?\s*[|:]|\|)[\s\d|:()\[\]<>/\\^~*.=+'hpbrstxvPMHBRSTXV-]*")
_SOLFEGE = re.compile(r"(?i)(do|re|mi|fa|sol|la|si)(?!dd|ug|lt)")
_SOLFEGE_LETTER = {"do": "C", "re": "D", "mi": "E", "fa": "F", "sol": "G", "la": "A", "si": "B"}

# The spaces between a line's first chords and its first word: the lyric's own indent, which
# only pushes the words away from their chord. Spaces before another chord stay.
_LEAD_GAP = re.compile(r"^((?:\[[^\[\]]*\])+) +(?=[^\[\s])")

TAB_STOP = 8


def normalize_chord(name: str) -> str:
    """Letter names for a solfège chord: "Do#m7" → "C#m7", "Sib" → "Bb", "Mi/Sol#" → "E/G#".

    Letter chords pass through unchanged ("Fadd9" stays: ``Fa`` followed by
    ``dd``, ``ug`` or ``lt`` is F add/aug/alt, not solfège).
    """
    root, sep, bass = name.partition("/")
    return _letter_root(root) + sep + (_letter_root(bass) if sep else "")


def _letter_root(part: str) -> str:
    m = _SOLFEGE.match(part)
    if not m:
        return _capital(part)
    return _SOLFEGE_LETTER[m.group(1).lower()] + part[m.end() :]


def _capital(part: str) -> str:
    """A chord typed in lower case ("am", "em7", "dm", "f#") with its letter capitalised; a word that is no
    chord once capitalised ("be", "dim", "capo", "x2") stays as it was written."""
    if not part or part[0] not in "abcdefg":  # (an empty part, "A/"'s bass, is in every string)
        return part
    named = part[0].upper() + part[1:]
    return named if parse_chord(named) is not None else part


_WORD = re.compile(r"[^\s|]+")


def tag_forgotten(line: str) -> str:
    """A chord line with the chords nobody tagged tagged: ``[ch]Dm[/ch]   Dm/F   [ch]E[/ch]``.

    Tabbers forget a tag now and then, and a line with one word that is no tag is no chord line: its chords
    would read as lyrics (a real sheet lost 22 of its 85 chords so). A line that already holds a tag is mended
    when every other word on it, but its bars, dashes and repeat marks, is a chord (a letter's name, as
    ``theory.parse_chord`` reads it: "La" and "Be" are no chords here) and there are no more of them than tagged
    chords; any other line, a lyric with a chord in it, stays as it is. Columns do not move.
    """
    tagged = len(_CHORD.findall(line))
    if not tagged:
        return line

    def blank(m: re.Match[str]) -> str:
        return " " * len(m.group())

    bare = _MARK.sub(blank, _CHORD.sub(blank, _TAB_MARK.sub(blank, line)))
    forgotten = []
    for m in _WORD.finditer(bare):
        if _CHORD_LINE_REST.fullmatch(m.group()):
            continue
        if parse_chord(m.group()) is None:
            return line
        forgotten.append(m)
    if not forgotten or len(forgotten) > tagged:
        return line
    for m in reversed(forgotten):
        line = f"{line[: m.start()]}[ch]{m.group()}[/ch]{line[m.end() :]}"
    return line


def is_chord_line(line: str) -> bool:
    """Whether a line holds chords and nothing else but bars, dashes, slashes and repeat marks."""
    line = tag_forgotten(_TAB_MARK.sub("", line))
    if not _CHORD.search(line):
        return False
    rest = _MARK.sub(" ", _CHORD.sub(" ", line))
    return _CHORD_LINE_REST.fullmatch(rest) is not None


def merge_chord_line(chords: str, lyrics: str) -> str:
    """One ChordPro line: each chord of the chord line placed at its column in the lyric line.

    A chord beyond the end of the lyric is padded out with spaces. The spaces directly after the
    line's leading chords are dropped; later chords stay on the same letters.
    """
    text = _escape_inline(_TAB_MARK.sub("", lyrics).expandtabs(TAB_STOP).rstrip())
    out: list[str] = []
    i = col = 0
    for at, token in _chord_items(chords):
        while i < len(text) and col + _width(text[i]) <= at:
            col += _width(text[i])
            out.append(text[i])
            i += 1
        if i == len(text) and col < at:
            out.append(" " * (at - col))
            col = at
        out.append(token)
    out.append(text[i:])
    return _finish(_LEAD_GAP.sub(r"\1", "".join(out)))


def to_chordpro(
    content: str,
    *,
    title: str,
    artist: str,
    key: str | None = None,
    capo: int | str | None = None,
    auto: bool = False,
) -> str:
    """Convert UG sheet markup into a ChordPro document.

    - A chord line followed by a lyric line becomes one line, each chord at its
      column; a chord line with no lyric line under it becomes a chord-only line.
    - ``[Verse 1]`` becomes ``{comment: Verse 1}``.
    - A ``[tab]`` block holding staff lines, or a run of staff lines outside one,
      becomes ``{start_of_tab}`` … ``{end_of_tab}``, kept verbatim.
    - Solfège chords get letter names; repeat marks become annotations (``[*x2]``).
    - Text ChordPro would misread is escaped (see ``_escape_inline``).

    The header carries the title, the artist, the key and capo when given, and an
    "auto-generated, unverified" comment for auto-chords sheets.
    """
    head = [f"{{title: {directive_text(title)}}}", f"{{artist: {directive_text(artist)}}}"]
    key_text = (key or "").strip()
    capo_text = "" if capo is None else str(capo).strip()
    if key_text:
        head.append(f"{{key: {directive_text(normalize_chord(key_text))}}}")
    if capo_text not in ("", "0"):
        head.append(f"{{capo: {directive_text(capo_text)}}}")
    if auto:
        head.append("{comment: auto-generated, unverified}")
    return "\n".join(head + _body(content)) + "\n"


def _body(content: str) -> list[str]:
    entries = _entries(content.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    out: list[str] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        nxt = entries[i + 1] if i + 1 < len(entries) else None
        i += 1
        if isinstance(entry, list):
            out += ["{start_of_tab}", *(_tab_line(ln) for ln in entry), "{end_of_tab}"]
        elif is_chord_line(entry):
            if isinstance(nxt, str) and _is_lyric(nxt):
                out.append(merge_chord_line(entry, nxt))
                i += 1
            else:
                out.append(_chord_only(entry))
        elif section := _section(entry):
            label, rest = section
            if is_chord_line(rest):
                out += [f"{{comment: {directive_text(label)}}}", _chord_only(rest)]
            else:
                out.append(f"{{comment: {directive_text(f'{label} {rest}'.rstrip())}}}")
        else:
            out.append(_text_line(entry))
    return _trim_blank(out)


def _entries(lines: list[str]) -> list[str | list[str]]:
    """Lines to convert one by one (str), and tab environments to keep verbatim (list)."""
    entries: list[str | list[str]] = []
    bare: list[str] | None = None  # staff lines outside a [tab] block, gathered as one block
    for in_block, run in _runs(lines):
        if in_block and any(_is_staff(ln) for ln in run):
            entries.append(_trim_blank(run))
            bare = None
            continue
        for line in run:
            if _is_staff(line):
                if bare is None:
                    bare = []
                    entries.append(bare)
                bare.append(line)
            else:
                bare = None
                entries.append(line)
    return entries


def _runs(lines: list[str]) -> list[tuple[bool, list[str]]]:
    """Split the sheet into runs inside and outside ``[tab]`` blocks, markers removed."""
    runs: list[tuple[bool, list[str]]] = []
    run: list[str] = []
    in_block = False
    for raw in lines:
        if "[tab]" in raw and not in_block:
            if run:
                runs.append((False, run))
            run, in_block = [], True
        line = _TAB_MARK.sub("", raw)
        if line.strip() or line == raw:  # a line holding only markers is no blank line
            run.append(line)
        if "[/tab]" in raw and in_block:
            runs.append((True, run))
            run, in_block = [], False
    if run:
        runs.append((in_block, run))
    return runs


def _is_staff(line: str) -> bool:
    return _STAFF.fullmatch(line) is not None and line.count("-") >= 3


def _is_lyric(line: str) -> bool:
    return bool(line.strip()) and not _CHORD.search(line) and not _section(line)


def _section(line: str) -> tuple[str, str] | None:
    """A section header's label, and the chords or repeat mark after it on its line."""
    m = _SECTION.fullmatch(line)
    if not m:
        return None
    label, rest = m.groups()
    if rest and not (is_chord_line(rest) or _MARK.fullmatch(rest)):
        return None  # "[x2] and again" is a lyric with a note, not a header
    return label, rest


def _chord_only(line: str) -> str:
    return " ".join(token for _, token in _chord_items(line))


def _chord_items(line: str) -> list[tuple[int, str]]:
    """The chords and marks of a chord line, as (display column, ChordPro token), in order."""
    line = tag_forgotten(_TAB_MARK.sub("", line))
    plain = ""
    spans: list[tuple[int, int, str]] = []
    pos = 0
    for m in _CHORD.finditer(line):
        plain += line[pos : m.start()]
        # ChordPro draws chord names with markup too, and its <img> opens a local file.
        name = _escape_inline(normalize_chord(m.group(1).strip().replace("[", "").replace("]", "")))
        spans.append((len(plain), len(plain) + len(m.group(1)), f"[{name}]" if name else ""))
        plain += m.group(1)
        pos = m.end()
    plain += line[pos:]
    for m in _MARK.finditer(plain):
        if not any(s <= m.start() < e for s, e, _ in spans):
            spans.append((m.start(), m.end(), f"[*{m.group().strip()}]"))
    columns = display_columns(plain)
    return [(columns[s], token) for s, _, token in sorted(spans) if token]


def display_columns(text: str) -> list[int]:
    """The display column at which each character of ``text`` starts, then the one where it ends, as a monospace
    font shows it: a wide East Asian character (Chinese, kana, Hangul, full-width punctuation) two columns, a
    combining mark none, a tab up to the next stop. ``merge_chord_line`` reads a chord line's columns so, and a
    lyric line's characters by the same widths; autochords/merge.py writes its chord lines in these columns."""
    cols, col = [], 0
    for ch in text:
        cols.append(col)
        col = (col // TAB_STOP + 1) * TAB_STOP if ch == "\t" else col + _width(ch)
    cols.append(col)
    return cols


def _width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def _text_line(line: str) -> str:
    """A lyric or note line; chord names in running text stay as plain text."""
    line = _CHORD.sub(lambda m: normalize_chord(m.group(1).strip()), line)
    return _finish(_escape_inline(line.expandtabs(TAB_STOP)))


def _tab_line(line: str) -> str:
    """A tablature line, verbatim but for chord tags and what ChordPro would misread."""
    line = _CHORD.sub(lambda m: m.group(1), line).rstrip()
    if _DIRECTIVE_LIKE.fullmatch(line):
        line = line.translate(_BRACKETS)
    return _finish(line)


# What ChordPro 6.050.7 misreads in text, checked against the binary: any [..] is
# a chord (no escape exists), {..} on its own line is a directive, %{..} is a
# metadata substitution, <..> is Pango-style markup (and &lt; is not decoded),
# a line starting with # is a comment, a trailing backslash joins the next line,
# and a backslash followed by u and four hex digits is decoded as a character.
_BRACKETS = str.maketrans("[]{}", "()()")
_MARKUP_START = re.compile(r"<(?=.*>)")
_DECODED_BACKSLASH = re.compile(r"\\(?=u[0-9a-fA-F]{4}|$)")
_ESCAPED_BACKSLASH = "\\" + "u005c"  # ChordPro's own escape for one backslash
_DIRECTIVE_LIKE = re.compile(r"\s*\{.*\}\s*")


def _escape_inline(text: str) -> str:
    """Swap characters that would read as a chord, a directive, a substitution or markup."""
    return _MARKUP_START.sub("\u2039", text.translate(_BRACKETS))


def _escape_backslashes(line: str) -> str:
    return _DECODED_BACKSLASH.sub(lambda _: _ESCAPED_BACKSLASH, line)


def directive_text(text: str) -> str:
    """Text for a directive's value (``{title: …}``), on one line, as ``to_chordpro`` writes it: nothing
    in it reads as a chord, a directive, a substitution or markup."""
    return _escape_backslashes(_escape_inline(" ".join(text.split())))


def _finish(line: str) -> str:
    """The last touches on an output line: no trailing space, no comment-like start."""
    line = _escape_backslashes(line.rstrip())
    return " " + line if line.startswith("#") else line


def _trim_blank(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]
