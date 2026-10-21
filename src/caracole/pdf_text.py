"""The text a sheet's PDF is made from: its .cho (``chordpro.to_chordpro``), made for paper.

sheet.cho stays as written, the viewer's input; render.py hands chordpro this text instead, in the
private copy it renders (``render._render_into``). It is the .cho with:

- the tab's notes before its first section left out: the viewer's preamble
  (``sheet.split_preamble``), the lines it folds away; a tab block after them stays;
- the shapes its chord legend gives as ``{define}``s, so the PDF's chord diagrams are the tab's:
  for each chord the song plays, under the name it writes it by, the first shape given for it
  that plays it (``voicings.plays``), as the viewer shows it;
- ``{subtitle}`` under the title: the artist, the viewer's key line (``page.key_line_text``), a
  capo the notes name for a sheet with no capo of its own, and a tuning they name ("half step
  down"), so a song in another tuning never prints as if in standard tuning;
- its section names in capitals;
- ``{columns: N}`` after its header.

Each PDF's record (render.py) keeps ``PDF_TEXT_VERSION``: bump it when what ``pdf_text`` writes
changes (the viewer's key line and how its key is found among it), and every PDF is made again.
"""

from __future__ import annotations

from collections.abc import Iterable

from caracole.autochords.merge import AUTO_MARKER
from caracole.chordpro import directive_text
from caracole.viewer.page import key_line_text
from caracole.viewer.sheet import COMMENTS, Preamble, directive, parse_sheet, split_preamble
from caracole.viewer.theory import Chord, Key, parse_chord
from caracole.viewer.voicings import Position, plays

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
    body = lines[max(head, pre.end):]
    out = lines[:head]
    if subtitle := _subtitle(lines[:head], key, capo, pre):
        out.append(f"{{subtitle: {directive_text(subtitle)}}}")
    out += [line for line in lines[head:pre.end] if directive(line)]  # a {define} among the notes, say
    out += _defines(pre.legend, parse_sheet("\n".join(body)).chords)
    if columns > 1:
        out.append(f"{{columns: {columns}}}")
    out += map(_capitals, body)
    return "\n".join(out) + "\n"


def _in_header(line: str) -> bool:
    found = directive(line)
    return found is not None and (found[0] in _HEADER or (found[0] in COMMENTS and found[1] == AUTO_MARKER))


def _subtitle(header: list[str], key: Key | None, capo: int | None, pre: Preamble) -> str:
    """The line under the title: the artist, the key line, the notes' capo and their tuning."""
    artist = next((found[1] for line in header if (found := directive(line)) and found[0] == "artist"), "")
    parts = (artist, key_line_text(key, capo), "" if capo else pre.capo_note, pre.tuning)
    return " · ".join(part for part in parts if part)


def _defines(legend: Iterable[tuple[Chord, Position]], names: list[str]) -> list[str]:
    """A ``{define}`` for each chord the song plays (``names``, as it writes them) that the legend
    gives a shape for: the first one that plays it."""
    shapes: dict[tuple[int, str, int | None], Position] = {}
    for chord, position in legend:
        if plays(position, chord):
            shapes.setdefault(_as_shown(chord), position)
    out = []
    for name in names:
        chord = parse_chord(name, strict=False)
        if chord is not None and (position := shapes.get(_as_shown(chord))) is not None:
            frets, fingers, base, _ = position
            out.append(f"{{define: {name} base-fret {base} frets {' '.join(frets)} fingers {' '.join(fingers)}}}")
    return out


def _as_shown(chord: Chord) -> tuple[int, str, int | None]:
    """A chord as the viewer files the sheet's shapes, for that very chord alone: its root, its
    suffix as written and its bass (``voicings.sheet_shapes``)."""
    return chord.root, chord.suffix, chord.bass


def _capitals(line: str) -> str:
    """A section's name in capitals; any other line as it is."""
    found = directive(line)
    if found is None or found[0] not in COMMENTS or not found[1]:
        return line
    return f"{{{found[0]}: {directive_text(found[1].upper())}}}"
