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
  down"), so a song in another tuning never prints as if in standard tuning;
- its section names in capitals;
- ``{columns: N}`` after its header.

Each PDF's record (render.py) keeps the SHA-256 of this text, so a PDF is made again whenever it
would print otherwise (a key heard anew, a newer viewer's theory or shapes), and ``PDF_TEXT_VERSION``:
bump it to make every PDF again even so.
"""

from __future__ import annotations

from typing import Any

from caracole.autochords.merge import AUTO_MARKER
from caracole.chordpro import directive_text
from caracole.viewer.page import key_line_text, shapes_of
from caracole.viewer.sheet import COMMENTS, Preamble, directive, parse_sheet, split_preamble
from caracole.viewer.theory import Key, parse_chord
from caracole.viewer.voicings import parse_define, shape_key

PDF_TEXT_VERSION = 1

# The directives of a sheet's header, as to_chordpro writes them (with an auto sheet's notice).
_HEADER = frozenset({"title", "t", "subtitle", "st", "artist", "key", "capo"})


def pdf_text(cho: str, *, key: Key | None, capo: int | None, columns: int = 2) -> str:
    """The text of the PDF of the .cho ``cho`` (see the module's docstring). ``key`` is the key of
    its shapes and ``capo`` its capo, None for none, as the viewer reads them (``page.viewer_key``);
    ``columns`` the song's columns, one for none."""
    lines = cho.splitlines()
    pre = split_preamble(lines)
    head = 0
    while head < len(lines) and _in_header(lines[head]):
        head += 1
    body = _song(lines[max(head, pre.end):])
    out = lines[:head]
    if subtitle := _subtitle(lines[:head], key, capo, pre):
        out.append(f"{{subtitle: {directive_text(subtitle)}}}")
    # A directive among the notes stays (a {define} the viewer can't read, say)
    out += [line for line in lines[head:pre.end] if (found := directive(line)) and not _read_define(found)]
    out += _defines(shapes_of(parse_sheet(cho)), parse_sheet("\n".join(body)).chords)
    if columns > 1:
        out.append(f"{{columns: {columns}}}")
    out += body
    return "\n".join(out) + "\n"


def _in_header(line: str) -> bool:
    found = directive(line)
    return found is not None and (found[0] in _HEADER or (found[0] in COMMENTS and found[1] == AUTO_MARKER))


def _subtitle(header: list[str], key: Key | None, capo: int | None, pre: Preamble) -> str:
    """The line under the title: the artist, the key line, the notes' capo and their tuning."""
    artist = next((found[1] for line in header if (found := directive(line)) and found[0] == "artist"), "")
    parts = (artist, key_line_text(key, capo), "" if capo else pre.capo_note, pre.tuning)
    return " · ".join(part for part in parts if part)


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
