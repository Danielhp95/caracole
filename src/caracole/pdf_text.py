"""The text a sheet's PDF is made from: its .cho (``chordpro.to_chordpro``), made for paper.

sheet.cho stays as written, the viewer's input; render.py hands chordpro this text instead, in the
private copy it renders (``render._render_into``). It is the .cho with:

- the tab's notes before its first section left out: the viewer's preamble
  (``sheet.split_preamble``), the lines it folds away; a tab block after them stays;
- the shapes the sheet gives its chords as ``{define}``s, so the PDF's chord diagrams are the
  viewer's: for each chord the song plays that the sheet gives a shape for (its chord legend,
  wherever it is, or a ``{define}``), the first shape its viewer shows for it (``page.shapes_of``),
  under the name the song writes it by. The sheet's own ``{define}``s that the viewer reads go:
  chordpro draws a chord's last one;
- ``{subtitle}`` under the title: the artist, the viewer's key line (``page.key_line_text``), a
  capo the notes name for a sheet with no capo of its own, where its chords are played where the
  sheet writes them (``notes_capo``: a version that moves them or the capo plays them elsewhere), and
  a tuning they name ("half step down", "Drop D") or give after a "Tuning:" label
  (``sheet.split_preamble``), so a song in another tuning never prints as if in standard tuning, and
  one in standard tuning never as if in another;
- its section names in capitals;
- ``{columns: N}`` after its header;
- with ``names`` (a version's ``nm``, the viewer's Chord names), each chord's Roman numeral in the key
  of its shapes (``viewer.harmony.numeral``, each read with the chord it goes to), by a ``{define}``
  ``"both"`` names each chord and its numeral ("D · V/V") by a ``{define}`` of the viewer's shape for
  it, which chordpro displays so (``display``) over the words and its diagram, a chord that plays two
  roles named twice (``D``, ``D~1``); ``"numerals"`` writes the numerals in the chords' place, each a
  chord defined with no shape (``{define: V/V}``), in the chords' style, and draws no diagrams
  (``{diagrams: off}``): a chart that works in any key. A chord theory.py can't
  read (N.C.) stays as written. Either says the key the numerals are read in under the title
  ("numerals in C major") and ends with a legend of the symbols the song uses (``harmony.glossary``).
  A sheet with no key has no numerals;
- in two columns, a ``{column_break}`` where the two end level, when the two columns of its first
  page hold the song (``_column_break``): chordpro fills one column, then the next, so the second
  column of a song a little longer than one held a single line now and then. Where that is comes
  from how tall chordpro prints each line in caracole's style (``layout``, ``line_heights``,
  ``column_height``, read from STYLE_FILE's sizes and spacings and pinned to the real chordpro's
  pages by test_render.py). With ``names``, the legend is part of the song it levels, each chord as
  wide as the name chordpro displays for it ("D · V/V"), and a numerals chart has no diagrams' rows.

Each PDF's record (render.py) keeps the SHA-256 of this text, so a PDF is made again whenever it
would print otherwise (a key heard anew, a newer viewer's theory or shapes), and ``PDF_TEXT_VERSION``:
bump it to make every PDF again even so.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from caracole.autochords.merge import AUTO_MARKER
from caracole.chordpro import directive_text
from caracole.progressions import key_words
from caracole.viewer import harmony
from caracole.viewer.page import key_line_text, shapes_of
from caracole.viewer.sheet import COMMENTS, Preamble, directive, parse_sheet, split_preamble
from caracole.viewer.theory import Chord, Key, parse_chord
from caracole.viewer.voicings import Position, load_voicings, parse_define, shape_key, voicing_keys

PDF_TEXT_VERSION = 2  # 2: two columns that end level

# How the PDFs look (a ChordPro config; render.py says what it holds): its page's sizes and spacings
# are what ``layout`` reads.
STYLE_FILE = Path(__file__).with_name("chordpro-style.json")

# The directives of a sheet's header, as to_chordpro writes them (with an auto sheet's notice).
_HEADER = frozenset({"title", "t", "subtitle", "st", "artist", "key", "capo"})

# What a PDF names its chords by, as a version's ``nm`` says it: the chords alone (the default), the chords and
# their numerals, or the numerals alone.
NAMES = ("chords", "both", "numerals")
_CHORD = re.compile(r"\[([^\]*][^\]]*)\]")  # a chord on a line of the song; [*…] is an annotation
_NAMEABLE = re.compile(r"[^\s{}\[\]\"~]+")  # a chord name a {define} can carry, and display


def pdf_text(cho: str, *, key: Key | None, capo: int | None, columns: int = 2, names: str = "chords",
             notes_capo: bool = True) -> str:
    """The text of the PDF of the .cho ``cho`` (see the module's docstring). ``key`` is the key of
    its shapes and ``capo`` its capo, None for none, as the viewer reads them (``page.viewer_key``);
    ``columns`` the song's columns, one for none; ``names``, one of ``NAMES``; ``notes_capo``, whether a
    capo the notes name is the one the chords are played at: not in a version of the sheet that moves
    them or the capo (``render._version_text``)."""
    if names not in NAMES:
        raise ValueError(f"names: {names!r} is none of {', '.join(NAMES)}")
    lines = cho.splitlines()
    pre = split_preamble(lines)
    head = 0
    while head < len(lines) and _in_header(lines[head]):
        head += 1
    body = _song(lines[max(head, pre.end):])
    numbered = key if names != "chords" else None
    shapes = shapes_of(parse_sheet(cho))
    if numbered is not None:
        body, shown, played = _numbered(body, numbered, names, shapes)
    out = lines[:head]
    if subtitle := _subtitle(lines[:head], key, capo, pre, numbered, notes_capo=notes_capo):
        out.append(f"{{subtitle: {directive_text(subtitle)}}}")
    # A directive among the notes stays (a {define} the viewer can't read, say)
    out += [line for line in lines[head:pre.end] if (found := directive(line)) and not _read_define(found)]
    if numbered is None:
        out += _defines(shapes, parse_sheet("\n".join(body)).chords)
    else:
        out += shown
    if numbered is not None and names == "numerals":
        out.append("{diagrams: off}")
    if columns > 1:
        out.append(f"{{columns: {columns}}}")
    out += body
    if numbered is not None:
        out += _legend(played, numbered)
    if columns == 2 and (at := _column_break(out)) is not None:
        out.insert(at, "{column_break}")
    return "\n".join(out) + "\n"


def _in_header(line: str) -> bool:
    found = directive(line)
    return found is not None and (found[0] in _HEADER or (found[0] in COMMENTS and found[1] == AUTO_MARKER))


def _subtitle(header: list[str], key: Key | None, capo: int | None, pre: Preamble,
              numbered: Key | None = None, *, notes_capo: bool = True) -> str:
    """The line under the title: the artist, the key line, the key the numerals are read in, the notes'
    capo (for a sheet with no capo, where the chords are played where it writes them: ``notes_capo``) and
    their tuning."""
    artist = next((found[1] for line in header if (found := directive(line)) and found[0] == "artist"), "")
    read = f"numerals in {key_words(numbered)}" if numbered is not None else ""
    parts = (artist, key_line_text(key, capo), read, "" if capo or not notes_capo else pre.capo_note, pre.tuning)
    return " · ".join(part for part in parts if part)


def _numbered(body: list[str], key: Key, names: str,
              shapes: dict[str, dict[str, Any]]) -> tuple[list[str], list[str], list[Chord]]:
    """The song's lines with its numerals (``names``: "both" or "numerals"), the ``{define}``s that display
    them beside the chords, in the viewer's shapes ("both"), and the chords it plays, in order, for the
    legend. Each chord is read with the chord it goes to, the next on another root (D D7 G: both D chords
    go to G). With both, a chord that plays two roles is two chords for chordpro (``D``, ``D~1``); with
    the numerals alone, each is its numeral, a chord defined with no shape (``{define: V/V}``: a
    ``display`` must start with a note's letter, and a chord chordpro doesn't know prints in the
    annotations' faint style). One theory.py can't read (N.C.) stays as written."""
    found: list[tuple[int, re.Match[str], Chord | None]] = []
    tab = False
    for n, line in enumerate(body):
        d = directive(line)
        if tab:  # a tab's lines are as written
            tab = not (d is not None and d[0] in ("end_of_tab", "eot"))
            continue
        if d is not None:
            tab = d[0] in ("start_of_tab", "sot")
            continue
        found += [(n, m, parse_chord(m.group(1).strip(), strict=False)) for m in _CHORD.finditer(line)]
    played = [c for _, _, c in found if c is not None]
    after: list[Chord | None] = []
    upcoming: Chord | None = None
    for chord in reversed(played):
        after.append(after[-1] if upcoming is not None and upcoming.root == chord.root else upcoming)
        upcoming = chord
    goes = iter(after[::-1])
    texts: dict[tuple[int, int], str] = {}
    roles: dict[str, dict[str, str]] = {}  # a chord's name -> its numeral -> what the song calls it there
    defines: list[str] = []
    for n, m, chord in found:
        name = m.group(1).strip()
        numeral = None if chord is None else harmony.numeral(chord, key, next(goes)).text
        if numeral is not None and names == "numerals":
            texts[(n, m.start())] = f"[{numeral}]"
            if f"{{define: {numeral}}}" not in defines:  # a chord of no shape, which chordpro prints as a chord
                defines.append(f"{{define: {numeral}}}")
            continue
        if numeral is None or not _NAMEABLE.fullmatch(name):
            texts[(n, m.start())] = m.group(0)  # as written
            continue
        named = roles.setdefault(name, {})
        if numeral not in named:
            named[numeral] = name if not named else f"{name}~{len(named)}"
            defines.append(_display(named[numeral], f"{name} · {numeral}", _shape(chord, shapes)))
        texts[(n, m.start())] = f"[{named[numeral]}]"
    out = list(body)
    for n in sorted({n for n, _ in texts}):
        out[n] = _CHORD.sub(lambda m, n=n: texts[(n, m.start())], body[n])
    return out, defines, played


def _shape(chord: Chord, shapes: dict[str, dict[str, Any]]) -> Position | None:
    """The shape the viewer shows first for ``chord``: the sheet's own for that very chord, else
    chords-db's for its slash chord, else for its quality (viewer.js ``shapesOf``)."""
    entry = shapes.get(shape_key(chord))
    if entry is not None and entry["list"]:
        return entry["list"][0]
    data = load_voicings()
    fingering, _, slash = voicing_keys(chord)
    for filed in (slash, fingering):
        if filed is not None and filed in data and data[filed][chord.root]:
            return data[filed][chord.root][0]
    return None


def _display(name: str, display: str, shape: Position | None) -> str:
    """A ``{define}`` of the chord ``name``, in ``shape`` when it has one, that chordpro shows as ``display``."""
    if shape is None:
        return f'{{define: {name} display "{display}"}}'
    frets, fingers, base, _ = shape
    return (f"{{define: {name} base-fret {base} frets {' '.join(frets)} fingers {' '.join(fingers)} "
            f'display "{display}"}}')


def _legend(played: list[Chord], key: Key) -> list[str]:
    """The legend after the song: each symbol its numerals use, what it means, and the song's first chord
    that shows it (``harmony.glossary``)."""
    rows = harmony.glossary(played, key)
    if not rows:
        return []
    heading = f"THE NUMERALS, IN {key_words(key).upper()}"
    return ["", f"{{comment: {directive_text(heading)}}}", *(f"{symbol}: {meaning} ({example})"
                                                             for symbol, meaning, example in rows)]


def _defines(shapes: dict[str, dict[str, Any]], names: list[str]) -> list[str]:
    """A ``{define}`` for each chord the song plays (``names``, as it writes them) that the sheet gives
    a shape for: the first one its viewer shows (``shapes``, ``page.shapes_of``), fingers and all."""
    out = []
    for name in names:
        chord = parse_chord(name, strict=False)  # as the viewer reads the song's chords
        entry = shapes.get(shape_key(chord)) if chord is not None else None
        if entry is not None and entry["mine"]:
            frets, fingers, base, _ = entry["list"][0]
            out.append(f"{{define: {name} base-fret {base} frets {' '.join(frets)} fingers {' '.join(fingers)}}}")
    return out


def _read_define(found: tuple[str, str]) -> bool:
    """Whether a directive is a ``{define}`` whose shape the viewer reads (``voicings.parse_define``)."""
    return found[0] == "define" and parse_define(found[1]) is not None


def _song(lines: list[str]) -> list[str]:
    """The song's lines for the PDF: its section names in capitals, its own ``{define}``s that the
    viewer reads left out, and a tab's lines as they are."""
    out, tab = [], False
    for line in lines:
        found = directive(line)
        if tab:
            tab = not (found is not None and found[0] in ("end_of_tab", "eot"))
        elif found is not None and found[0] in ("start_of_tab", "sot"):
            tab = True
        elif found is not None and _read_define(found):
            continue
        elif found is not None and found[0] in COMMENTS and found[1]:
            line = f"{{{found[0]}: {directive_text(found[1].upper())}}}"
        out.append(line)
    return out


# --- two columns that end level ----------------------------------------------------------------

# The share of a column each part of a song may fill, by the estimate, to be sure chordpro's column
# holds it (else the second part would start the next page): the estimate is exact for Helvetica
# (test_render.py), but a songbook with a Chinese song prints its other songs in the CJK font too,
# whose Latin letters are wider, and wrap sooner.
_FILL = 0.85
# What may move to the second column: a section, else a stanza.
_SECTION_STARTS = frozenset({*COMMENTS, "start_of_chorus", "soc"})
_FLOW = frozenset({"column_break", "colb", "new_page", "np", "new_physical_page", "npp", "columns", "col"})


def _column_break(lines: list[str]) -> int | None:
    """Where a ``{column_break}`` levels the two columns of the song ``lines`` (the PDF's text, its
    ``{columns: 2}`` in it), or None to leave chordpro's flow, which fills the first column and puts the
    rest in the second: a single line, now and then. Only a song whose first page's two columns hold
    it gets one, and only before a section (between two stanzas in a song without any heading), never
    inside one or a tab: there, the one that leaves the taller column shortest. A song one column holds
    stays in one, a longer one than two hold keeps chordpro's flow, and so does a song that sets its
    own columns or pages."""
    if sum(1 for line in lines if (found := _directive(line)) and found[0] in _FLOW) > 1:
        return None
    shape = layout()
    heights = line_heights(lines, shape)
    column, total = column_height(lines, shape), sum(heights)
    if total <= column:
        return None
    room = column * _FILL
    best: tuple[float, int] | None = None
    for at in _starts(lines):
        above = sum(heights[:at])
        # The empty lines before the section end the first column: chordpro prints nothing there.
        first = above - sum(heights[blank] for blank in _blanks_before(lines, at))
        if 0 < first <= room and total - above <= room and (best is None or max(first, total - above) < best[0]):
            best = (max(first, total - above), at)
    return None if best is None else best[1]


def _starts(lines: list[str]) -> list[int]:
    """Where a section starts in ``lines`` (``_SECTION_STARTS``), outside a tab; in a song without any,
    where a stanza does: after the empty lines between two, the longer runs of them when every line
    has one after it (the most common run, then, is inside a stanza)."""
    sections: list[int] = []
    runs: list[tuple[int, int]] = []  # (empty lines, the line after them)
    tab, empty = False, 0
    for at, line in enumerate(lines):
        found = _directive(line)
        if tab:
            tab = not (found is not None and found[0] in ("end_of_tab", "eot"))
        elif not line.strip():
            empty += 1
            continue
        else:
            if found is not None and found[0] in _SECTION_STARTS and found[1] != AUTO_MARKER:
                sections.append(at)
            if empty:
                runs.append((empty, at))
            tab = found is not None and found[0] in ("start_of_tab", "sot")
        empty = 0
    if sections or not runs:
        return sections
    common = Counter(length for length, _ in runs).most_common(1)[0][0]
    return [at for length, at in runs if length > common] or [at for _, at in runs]


def _directive(line: str) -> tuple[str, str] | None:
    """``sheet.directive``, quicker on the many lines that hold no brace."""
    return directive(line) if "{" in line else None


def _blanks_before(lines: list[str], at: int) -> range:
    """The empty lines just before line ``at``."""
    start = at
    while start > 0 and not lines[start - 1].strip():
        start -= 1
    return range(start, at)


# --- how tall chordpro prints it ----------------------------------------------------------------

# Helvetica's advance widths, in thousandths of the size, for " " to "~" (Adobe's core-font metrics):
# the lyrics' font, and the bold one the chords are in, with the "·" a chord's numeral is named after
# (WinAnsi's, "D · V/V"). ``_letter`` gives every other letter's.
_HELVETICA = dict(zip(map(chr, range(32, 127)), map(int, """
278 278 355 556 556 889 667 222 333 333 389 584 278 333 278 278 556 556 556 556 556 556 556 556 556 556 278 278
584 584 584 556 1015 667 667 722 722 667 611 778 722 278 500 667 556 833 722 778 667 778 722 667 611 722 667 944
667 667 611 278 278 278 469 556 222 556 556 500 556 556 278 556 556 222 222 500 222 833 556 556 556 556 333 500
278 556 500 722 500 500 500 334 260 334 584""".split()), strict=True)) | {"\u00b7": 278}
_HELVETICA_BOLD = dict(zip(map(chr, range(32, 127)), map(int, """
278 333 474 556 556 889 722 278 333 333 389 584 278 333 278 278 556 556 556 556 556 556 556 556 556 556 333 333
584 584 584 611 975 722 722 722 722 667 611 778 722 278 556 722 611 833 722 778 667 778 722 667 611 722 667 944
667 667 611 333 278 333 584 556 278 556 611 556 611 556 333 611 611 278 278 556 278 889 611 611 611 611 389 556
333 611 556 778 556 556 500 389 280 389 584""".split()), strict=True)) | {"\u00b7": 278}
_TOKEN = re.compile(r"\[([^\]]*)\]")
_BREAKS = re.compile(r"(.+)([-_,.:;\s])(.+)", re.DOTALL)  # where chordpro may wrap a line, its last place
_STRINGS = 6  # a guitar's, for the width of a chord diagram
_DISPLAY = re.compile(r'\bdisplay\s+"([^"]*)"')  # what a {define} has chordpro print for its chord
_BOX = frozenset({"comment_box", "cb"})
_ITALIC = frozenset({"comment_italic", "ci"})
# The size of chordpro's own fonts for the headings caracole's style leaves as they are (its
# comment_italic and comment_box).
_CHORDPRO_SIZE = 12


@dataclass(frozen=True)
class Layout:
    """What caracole's style (STYLE_FILE) makes of a page, in points, as chordpro lays it out: the paper,
    its margins, two columns and the space between them, and how tall each kind of line is (a font's
    size times its spacing). ``diagram_row`` is a row of chord diagrams above the song, ``per_row`` how
    many a row holds; ``wrap_indent`` is how far a wrapped line's next part is indented (an "x"). A
    heading is its font's size times ``heading_spacing``: a {comment}'s (``comment``), a
    {comment_italic}'s or a {comment_box}'s (``italic_size``, ``box_size``)."""

    width: float
    height: float
    left: float
    right: float
    top: float
    bottom: float
    column_space: float
    text_size: float
    chord_size: float
    annotation_size: float
    comment_size: float
    italic_size: float
    box_size: float
    heading_spacing: float
    lyrics: float
    chords: float
    comment: float
    tab: float
    empty: float
    diagram_row: float
    per_row: int

    @property
    def column_width(self) -> float:
        return (self.width - self.left - self.right - self.column_space) / 2

    @property
    def second_column(self) -> float:
        """Where the second column starts, from the page's left edge."""
        return self.left + self.column_width + self.column_space

    @property
    def wrap_indent(self) -> float:
        return _width("x", self.text_size)


@lru_cache(maxsize=1)
def layout() -> Layout:
    """The page STYLE_FILE describes (see ``Layout``)."""
    pdf = json.loads(STYLE_FILE.read_text(encoding="utf-8"))["pdf"]
    fonts, spacing, d = pdf["fonts"], pdf["spacing"], pdf["diagrams"]
    width, height = pdf["papersize"]
    inner = width - pdf["marginleft"] - pdf["marginright"]
    # chordpro's StringDiagram: the name, the nut, the grid and the space below it; a diagram's width
    # and the space after it.
    row = (fonts["diagram"]["size"] * spacing["diagramchords"] + d["nutwidth"] * d["linewidth"] * d["width"]
           + 0.4 * d["width"] + d["vcells"] * d["height"] + d["vspace"] * d["height"])
    across = (_STRINGS - 1) * d["width"] + d["hspace"] * d["width"]
    return Layout(
        width=width, height=height, left=pdf["marginleft"], right=pdf["marginright"], top=pdf["margintop"],
        bottom=pdf["marginbottom"], column_space=pdf["columnspace"], text_size=fonts["text"]["size"],
        chord_size=fonts["chord"]["size"], annotation_size=fonts["annotation"]["size"],
        comment_size=fonts["comment"]["size"],
        italic_size=fonts.get("comment_italic", {}).get("size", _CHORDPRO_SIZE),
        box_size=fonts.get("comment_box", {}).get("size", _CHORDPRO_SIZE), heading_spacing=spacing["lyrics"],
        lyrics=fonts["text"]["size"] * spacing["lyrics"], chords=fonts["chord"]["size"] * spacing["chords"],
        comment=fonts["comment"]["size"] * spacing["lyrics"], tab=fonts["tab"]["size"] * spacing["tab"],
        empty=fonts["text"]["size"] * spacing["empty"],  # an empty line's font is the text's
        diagram_row=row, per_row=int((inner + d["hspace"] * d["width"]) / across),
    )


def column_height(lines: list[str], shape: Layout) -> float:
    """How tall the columns of the first page of the song ``lines`` are: the page less its margins and
    the rows of chord diagrams above the song, none with ``{diagrams: off}`` (a numerals chart). A
    chord gets a diagram from chordpro when the text defines it or chordpro knows its shape; chordpro
    knows no chord over another bass ("C/E"), so every other chord counts (one chordpro lacks only
    makes the estimate short of room)."""
    played: dict[str, None] = {}  # the chords sung, each once, in order (as parse_sheet's)
    defined, tab, diagrams = set(), False, True
    for line in lines:
        found = _directive(line)
        if tab:
            tab = not (found is not None and found[0] in ("end_of_tab", "eot"))
        elif found is not None:
            tab = found[0] in ("start_of_tab", "sot")
            if found[0] in ("define", "chord") and found[1].split():
                defined.add(found[1].split()[0])
            elif found[0] == "diagrams":
                diagrams = found[1].strip().lower() not in ("off", "false")
        elif not line.startswith("#"):
            played.update(dict.fromkeys(name.strip() for name in _TOKEN.findall(line) if not name.startswith("*")))
    drawn = [name for name in played if name and (name in defined or "/" not in name)]
    rows = -(-len(drawn) // shape.per_row) if diagrams else 0
    return shape.height - shape.top - shape.bottom - rows * shape.diagram_row


def line_heights(lines: list[str], shape: Layout) -> list[float]:
    """How tall chordpro prints each of ``lines`` (a ChordPro text's), in caracole's style ``shape``:
    a chord row and a lyric row for a line of chords over words, either alone for a line with only one
    of them; a heading's row ({comment}, as caracole writes a section, and a chorus recalled, which
    chordpro heads "Chorus" or by its label); a tab's line, an empty line (none before the song's first
    line); nothing for any other directive. A line too wide for its column takes the rows chordpro
    wraps it onto, as its ``wrap`` does: on the lyrics' widths alone, and a chord that doesn't fit
    where its words end, by the name chordpro prints for it (a {define}'s ``display``), starts the
    next part."""
    out: list[float] = []
    tab = started = False
    displays: dict[str, str] = {}
    for line in lines:
        found = _directive(line)
        height = 0.0
        if tab:
            tab = not (found is not None and found[0] in ("end_of_tab", "eot"))
            height = shape.tab if tab else 0.0
        elif found is not None:
            tab = found[0] in ("start_of_tab", "sot")
            text = found[1] or ("Chorus" if found[0] == "chorus" else "")
            if found[0] in ("define", "chord") and (shown := _DISPLAY.search(found[1])) and found[1].split():
                displays[found[1].split()[0]] = shown.group(1)
            elif (found[0] in COMMENTS or found[0] == "chorus") and text:
                size, widths = ((shape.box_size, _HELVETICA) if found[0] in _BOX
                                else (shape.italic_size, _HELVETICA) if found[0] in _ITALIC
                                else (shape.comment_size, _HELVETICA_BOLD))
                height = size * shape.heading_spacing * _wrapped(text, size, shape, widths)
        elif line.startswith("#"):
            pass
        elif not line.strip():
            height = shape.empty if started else 0.0
        else:
            height = sum((shape.chords if chords else 0.0) + (shape.lyrics if words else 0.0)
                         for chords, words in _parts(line, shape, displays))
        started = started or (height > 0 and bool(line.strip()))
        out.append(height)
    return out


def _width(text: str, size: float, widths: dict[str, int] = _HELVETICA) -> float:
    """The width of ``text`` in Helvetica (``widths``) at ``size``, a letter the table lacks as
    ``_letter`` says."""
    try:
        return sum(map(widths.__getitem__, text)) * size / 1000
    except KeyError:
        bold = widths is _HELVETICA_BOLD
        return sum(widths[ch] if ch in widths else _letter(ch, bold) for ch in text) * size / 1000


@lru_cache(maxsize=4096)
def _letter(ch: str, bold: bool) -> int:
    """The width of a letter the Helvetica tables lack: a wide East Asian letter is a square, an
    accented one its letter's width, any other the width of a digit."""
    if unicodedata.east_asian_width(ch) in "WF":
        return 1000
    return (_HELVETICA_BOLD if bold else _HELVETICA).get(unicodedata.normalize("NFKD", ch)[:1], 556)


def _fit(text: str, room: float, size: float, widths: dict[str, int] = _HELVETICA) -> tuple[str, str]:
    """chordpro's Writer::wrap: as much of ``text`` as fits in ``room``, broken after its last break
    that lets it fit (a space there goes), and the rest."""
    rest = space = ""
    while _width(text, size, widths) > room:
        found = _BREAKS.fullmatch(text)
        if found is None:
            return text, rest
        head, mark, tail = found.groups()
        if mark.strip():
            head, mark = head + mark, ""
        text, rest, space = head, tail + space + rest, mark
    return text, rest


def _wrapped(text: str, size: float, shape: Layout, widths: dict[str, int] = _HELVETICA) -> int:
    """How many lines chordpro wraps a line of ``text`` alone onto (a heading's, say)."""
    count, room = 1, shape.column_width
    while True:
        _, text = _fit(text, room, size, widths)
        if not text:
            return count
        count, room = count + 1, shape.column_width - shape.wrap_indent


def _parts(line: str, shape: Layout, displays: dict[str, str] | None = None) -> list[tuple[bool, bool]]:
    """The parts chordpro's ``wrap`` draws a line of chords and words in, each as (whether it has a chord,
    whether it has words): the words fill the column, a chord placed where its words would start, as
    wide as the name chordpro prints for it (``displays``: a chord's, by a {define})."""
    shown = displays or {}
    pieces = _TOKEN.split(line)
    names, sung = pieces[1::2], "".join(pieces[0::2])
    widest = max((len(shown.get(name, name)) for name in names), default=0) * shape.chord_size  # no letter is wider than its size
    if _width(sung, shape.text_size) + widest <= shape.column_width:  # nothing to wrap: one part
        return [(any(name.strip() for name in names), bool(sung.strip()))]
    pairs = ([("", pieces[0])] if pieces[0] else []) + list(zip(pieces[1::2], pieces[2::2]))
    parts: list[tuple[bool, bool]] = []
    x, placed, chords, words = 0.0, 0, False, ""
    while pairs:
        chord, phrase = pairs.pop(0)
        rest = ""
        if placed and chord:
            mark = chord.startswith("*")  # a repeat mark, in the annotations' font
            size = shape.annotation_size if mark else shape.chord_size
            printed = chord[1:] if mark else shown.get(chord, chord)
            if _width(printed, size, _HELVETICA if mark else _HELVETICA_BOLD) > shape.column_width - x:
                rest = phrase
        if not rest:
            head, rest = _fit(phrase, shape.column_width - x, shape.text_size)
            width = _width(head, shape.text_size)
            if width > shape.column_width - x and placed > 1:
                rest = phrase
            else:
                placed, chords, words, chord, x = placed + 1, chords or bool(chord.strip()), words + head, "", x + width
        if rest:
            pairs.insert(0, (chord, rest))
            parts.append((chords, bool(words.strip())))
            x, placed, chords, words = shape.wrap_indent, 0, False, ""
    parts.append((chords, bool(words.strip())))
    return parts
