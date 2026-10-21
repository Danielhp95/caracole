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
  capo the notes name for a sheet with no capo of its own, and a tuning they name ("half step
  down", "Drop D") or give after a "Tuning:" label (``sheet.split_preamble``), so a song in another
  tuning never prints as if in standard tuning, and one in standard tuning never as if in another;
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
  A sheet with no key has no numerals.

Each PDF's record (render.py) keeps the SHA-256 of this text, so a PDF is made again whenever it
would print otherwise (a key heard anew, a newer viewer's theory or shapes), and ``PDF_TEXT_VERSION``:
bump it to make every PDF again even so.
"""

from __future__ import annotations

import re
from typing import Any

from caracole.autochords.merge import AUTO_MARKER
from caracole.chordpro import directive_text
from caracole.progressions import key_words
from caracole.viewer import harmony
from caracole.viewer.page import key_line_text, shapes_of
from caracole.viewer.sheet import COMMENTS, Preamble, directive, parse_sheet, split_preamble
from caracole.viewer.theory import Chord, Key, parse_chord
from caracole.viewer.voicings import Position, load_voicings, parse_define, shape_key, voicing_keys

PDF_TEXT_VERSION = 1

# The directives of a sheet's header, as to_chordpro writes them (with an auto sheet's notice).
_HEADER = frozenset({"title", "t", "subtitle", "st", "artist", "key", "capo"})

# What a PDF names its chords by, as a version's ``nm`` says it: the chords alone (the default), the chords and
# their numerals, or the numerals alone.
NAMES = ("chords", "both", "numerals")
_CHORD = re.compile(r"\[([^\]*][^\]]*)\]")  # a chord on a line of the song; [*…] is an annotation
_NAMEABLE = re.compile(r"[^\s{}\[\]\"~]+")  # a chord name a {define} can carry, and display


def pdf_text(cho: str, *, key: Key | None, capo: int | None, columns: int = 2, names: str = "chords") -> str:
    """The text of the PDF of the .cho ``cho`` (see the module's docstring). ``key`` is the key of
    its shapes and ``capo`` its capo, None for none, as the viewer reads them (``page.viewer_key``);
    ``columns`` the song's columns, one for none; ``names``, one of ``NAMES``."""
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
    if subtitle := _subtitle(lines[:head], key, capo, pre, numbered):
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
    return "\n".join(out) + "\n"


def _in_header(line: str) -> bool:
    found = directive(line)
    return found is not None and (found[0] in _HEADER or (found[0] in COMMENTS and found[1] == AUTO_MARKER))


def _subtitle(header: list[str], key: Key | None, capo: int | None, pre: Preamble,
              numbered: Key | None = None) -> str:
    """The line under the title: the artist, the key line, the key the numerals are read in, the notes'
    capo and their tuning."""
    artist = next((found[1] for line in header if (found := directive(line)) and found[0] == "artist"), "")
    read = f"numerals in {key_words(numbered)}" if numbered is not None else ""
    parts = (artist, key_line_text(key, capo), read, "" if capo else pre.capo_note, pre.tuning)
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
