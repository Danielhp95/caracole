"""A version of a sheet as its viewer shows it, applied in Python: the text a PDF of that version is made from.

The viewer (viewer.js) keeps where a song is played in its address: ``t``, the semitones it moved; ``mode``, one
of ``theory.MODES``; ``capo``, the fret the capo is on; ``alt``, the chords played instead of others
(``alt=<mode>.<chord>.<root>.<suffix>.<bass>,…``); and ``at``, the shape chosen for a chord
(``at=<chord>.<shape>,…``), each chord by its index in the sheet (``Sheet.chords``). ``Version`` is that,
``version_from_query`` reads it from an address as the viewer reads it, and ``version_query`` writes it as the
viewer's ``save()`` does. ``version_label`` names it: "G Dorian, capo 0".

``apply_version`` makes a ChordPro sheet that version, as its viewer shows it, by the viewer's own rules, in
Python: each chord named as viewer.js names it (``shift``, ``names``, ``nameOf``, from ``theory.spelling``,
``theory.map_chord`` and a swap among ``theory.alternatives``), and given the shape it shows for it as a
``{define}`` (``shapesOf``: the sheet's own shapes for that very chord, ``page.shapes_of``, else chords-db's), so a
PDF of the text has the chords and the shapes the viewer showed (test_viewer_version.py compares the two in
Chromium).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qsl, quote, unquote

from caracole.autochords.merge import AUTO_MARKER
from caracole.viewer.page import shapes_of
from caracole.viewer.sheet import COMMENTS, Sheet, directive, parse_sheet
from caracole.viewer.theory import MODES, SCALES, Chord, Key, alternatives, map_chord, parse_chord, spelling
from caracole.viewer.voicings import Position, load_voicings, parse_define, voicing_keys

Swap = tuple[int, str, int | None]  # a chord played instead: its root, suffix and bass, before any move

# The modes as the viewer's settings name them (viewer.js MODES).
MODE_NAMES = {"ionian": "Major", "dorian": "Dorian", "phrygian": "Phrygian", "lydian": "Lydian",
              "mixolydian": "Mixolydian", "aeolian": "Minor", "locrian": "Locrian"}


@dataclass(frozen=True)
class Version:
    """Where a song is played, as the viewer keeps it (its ``state``): ``t`` semitones from the sheet as
    written; ``mode``, None for the sheet's; ``capo``, None for the sheet's; ``at``, a chord's chosen shape
    (by its index in the sheet, the shape's in the list the viewer shows, 0 its first); ``alt``, by mode, a
    chord played instead of one (by its index), as long as the viewer offers it in that mode.

    ``at`` and ``alt`` are kept as read-only copies, so a version is a value, hashed by what it holds."""

    t: int = 0
    mode: str | None = None
    capo: int | None = None
    at: Mapping[int, int] = field(default_factory=dict)
    alt: Mapping[str, Mapping[int, Swap]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "at", MappingProxyType(dict(self.at)))
        object.__setattr__(self, "alt", MappingProxyType({
            mode: MappingProxyType({i: tuple(swap) for i, swap in swaps.items()}) for mode, swaps in self.alt.items()
        }))

    def __hash__(self) -> int:
        return hash((self.t, self.mode, self.capo, frozenset(self.at.items()),
                     frozenset((mode, frozenset(swaps.items())) for mode, swaps in self.alt.items())))


# --- the address ---------------------------------------------------------------------------------

_DIGITS = re.compile(r"[0-9]*")
# A chord's index as the viewer names one (its data-c): "03" is none.
_INDEX = re.compile(r"0|[1-9][0-9]*")
# A number as JavaScript's Number() reads one written in decimals; anything else is NaN.
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_BAD_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")
# What application/x-www-form-urlencoded (URLSearchParams) writes as it is.
_FORM_SAFE = frozenset(b"*-._0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def version_from_query(query: str) -> Version:
    """The version an address holds (``t=2&mode=dorian&capo=0&alt=…&at=…``, or the fragment with its "#"), read
    as the viewer reads its own: the rest of it (``fs``, ``speed``, ``chord``, …) left out, ``t`` rounded
    to within 11 semitones, a capo below the nut, a mode or a part of ``alt`` or ``at`` it can't read dropped.

    The viewer leaves ``t`` out of its address where the song's ``[transpose]`` puts it: without one, it is 0."""
    if query[:1] in ("#", "?"):
        query = query[1:]
    params: dict[str, str] = {}
    for name, value in parse_qsl(query, keep_blank_values=True):
        params.setdefault(name, value)  # the first, as URLSearchParams.get gives it
    t = 0
    if "t" in params:
        t = _round(max(-11.0, min(11.0, _number(params["t"]) or 0.0)))
    capo = None
    if params.get("capo", "") != "" and (fret := _number(params["capo"])) is not None and fret >= 0:
        capo = _round(min(fret, 99.0))  # a number, not infinity: apply_version keeps it to the viewer's frets
    mode = params.get("mode")
    return Version(t=t, mode=mode if mode in MODES else None, capo=capo,
                   at=_positions(params.get("at", "")), alt=_swaps(params.get("alt", "")))


def _number(text: str) -> float | None:
    """``text`` as JavaScript's Number() reads it (blank is 0), or None where that is NaN."""
    text = text.strip()
    if not text:
        return 0.0
    return float(text) if _NUMBER.fullmatch(text) else None


def _round(number: float) -> int:
    """Math.round: half up."""
    return math.floor(number + 0.5)


def _swaps(text: str) -> dict[str, dict[int, Swap]]:
    out: dict[str, dict[int, Swap]] = {}
    for part in text.split(","):
        mode, i, root, suffix, bass = (part.split(".") + [""] * 5)[:5]
        if mode not in MODES or not _INDEX.fullmatch(i) or not root or not _DIGITS.fullmatch(root) \
                or not _DIGITS.fullmatch(bass):
            continue
        if _BAD_ESCAPE.search(suffix):
            continue  # decodeURIComponent throws
        try:
            written = unquote(suffix, errors="strict")
        except UnicodeDecodeError:
            continue
        out.setdefault(mode, {})[int(i)] = (int(root), written, int(bass) if bass else None)
    return out


def _positions(text: str) -> dict[int, int]:
    out: dict[int, int] = {}
    for part in text.split(","):
        i, n = (part.split(".") + ["", ""])[:2]
        if _INDEX.fullmatch(i) and n and _DIGITS.fullmatch(n) and int(n) > 0:
            out[int(i)] = int(n)
    return out


def version_query(v: Version) -> str:
    """The version as the viewer's ``save()`` writes it in its address, in its order (``t``, ``mode``,
    ``capo``, ``alt``, ``at``), each left out where it says nothing; "" for the sheet as written."""
    params: list[tuple[str, str]] = []
    if v.t:
        params.append(("t", str(v.t)))
    if v.mode is not None:
        params.append(("mode", v.mode))
    if v.capo is not None:
        params.append(("capo", str(v.capo)))
    swaps = ",".join(f"{mode}.{i}.{root}.{_component(suffix)}.{'' if bass is None else bass}"
                     for mode, chosen in v.alt.items() for i, (root, suffix, bass) in sorted(chosen.items()))
    if swaps:
        params.append(("alt", swaps))
    if v.at:
        params.append(("at", ",".join(f"{i}.{n}" for i, n in sorted(v.at.items()))))
    return "&".join(f"{_form(name)}={_form(value)}" for name, value in params)


def _component(text: str) -> str:
    """encodeURIComponent, then "." as "%2E", as the viewer writes a swap's suffix."""
    return quote(text, safe="!~*'()").replace(".", "%2E")


def _form(text: str) -> str:
    """``text`` as URLSearchParams writes it."""
    return "".join("+" if byte == 0x20 else chr(byte) if byte in _FORM_SAFE else f"%{byte:02X}"
                   for byte in text.encode("utf-8"))


# --- where the song is played ------------------------------------------------------------------


@dataclass(frozen=True)
class _Played:
    """A version as the viewer plays it: the mode the chords are in (None without a key), whether that is the
    sheet's, how many semitones their names move (``shift()``: the transposition less the capo's move), and
    the fret the capo is on."""

    mode: str | None
    as_written: bool
    shift: int
    capo: int


def _played(v: Version, key: Key | None, capo_sheet: int | None) -> _Played:
    sheet_capo = capo_sheet or 0
    # The capo goes on any fret up to the 11th, or the sheet's (viewer.js CAPO_MAX).
    capo = sheet_capo if v.capo is None else max(0, min(max(11, sheet_capo), v.capo))
    mode = None if key is None else v.mode if v.mode in MODES else key.mode
    return _Played(mode, key is None or mode == key.mode, v.t - (capo - sheet_capo), capo)


def played_key(v: Version, key: Key | None, capo_sheet: int | None) -> tuple[Key | None, int]:
    """The key of the shapes the version plays (None for a sheet with no key) and its capo, for a PDF's
    key line (``page.key_line_text``); ``key`` and ``capo_sheet`` as for ``apply_version``."""
    played = _played(v, key, capo_sheet)
    if key is None or played.mode is None:
        return None, played.capo
    return Key((key.tonic + played.shift) % 12, played.mode), played.capo


def version_label(v: Version, key: Key | None, capo_sheet: int | None) -> str:
    """The version in words: the key of the shapes it plays, in the viewer's names of the modes, and its capo
    ("G Dorian, capo 0", "E Minor, capo 2"). A sheet with no key says how far it moved ("Transposed +2, capo 0",
    "As written, capo 3"). ``key`` is the key of the sheet's shapes, ``capo_sheet`` its capo, as for
    ``apply_version``."""
    played = _played(v, key, capo_sheet)
    if key is None or played.mode is None:
        return f"{f'Transposed {v.t:+d}' if v.t else 'As written'}, capo {played.capo}"
    shapes = Key((key.tonic + played.shift) % 12, played.mode)
    return f"{spelling(shapes)[shapes.tonic]} {MODE_NAMES[shapes.mode]}, capo {played.capo}"


# --- the sheet in that version -----------------------------------------------------------------

# ChordPro's escape for a backslash, as sheet.py undoes it and chordpro.py writes it.
_ESCAPED_BACKSLASH = "\\" + "u005c"
_TOKEN = re.compile(r"\[([^\]]*)\]")  # sheet.py's: a chord, or a mark ("[*x2]")
_HEADER = frozenset({"title", "t", "subtitle", "st", "artist"})  # to_chordpro's, besides the key and capo
_NAMEABLE = re.compile(r"[^\s{}\[\]]+")  # a chord name a {define} can carry


def apply_version(cho: str, v: Version, *, key: Key | None, capo_sheet: int | None) -> str:
    """The ChordPro sheet ``cho`` in the version ``v``, as its viewer shows it.

    ``key`` is the key of the sheet's shapes as its viewer names it (``page.viewer_key``, with the song's key)
    and ``capo_sheet`` the sheet's capo (``parse_sheet(cho).capo``). Each chord is named as the viewer names it,
    moved, in the mode, played instead; a chord ``theory.parse_chord`` can't read ("N.C.") stays as written,
    as do marks, tabs and the rest of the text. The header names the version's key (of its shapes, as chordpro
    reads a key: "Em" for E dorian) and its capo, and after it comes a ``{define}`` of each chord's chosen shape,
    once a name, in place of the sheet's own ``{define}``s that the viewer reads. No ``{transpose}`` is left:
    the chords are where the version plays them.
    """
    sheet = parse_sheet(cho)
    played = _played(v, key, capo_sheet)
    chords = _chords(sheet.chords, v, key, played)
    names = _names(sheet.chords, chords, key, played)
    index = {name: i for i, name in enumerate(sheet.chords)}

    def rename(token: re.Match[str]) -> str:
        text = token.group(1)
        if text.startswith("*"):
            return token.group(0)  # a mark
        name = text.replace(_ESCAPED_BACKSLASH, "\\").strip()
        i = index.get(name)
        if i is None or names[i] == name:
            return token.group(0)
        return "[" + names[i].replace("\\", _ESCAPED_BACKSLASH) + "]"

    out: list[str] = []
    tab = False
    for line in cho.splitlines():
        found = directive(line)
        if tab:
            tab = not (found is not None and found[0] in ("end_of_tab", "eot"))
        elif found is not None:
            what, value = found
            tab = what in ("start_of_tab", "sot")
            if what in ("capo", "transpose") or (what == "define" and parse_define(value) is not None):
                continue  # the version's, below
            if what == "key" and (key is not None or played.shift):
                continue  # a key that names the chords no more
        elif not line.startswith("#"):
            line = _TOKEN.sub(rename, line)
        out.append(line)

    head = 0
    while head < len(out) and _in_header(out[head]):
        head += 1
    stated = []
    if key is not None and played.mode is not None:
        stated.append(f"{{key: {_key_text(Key((key.tonic + played.shift) % 12, played.mode))}}}")
    if played.capo:
        stated.append(f"{{capo: {played.capo}}}")
    notice = next((n for n in range(head) if _notice(out[n])), head)  # to_chordpro's order: the key, the capo, it
    out[notice:notice] = stated
    head += len(stated)
    out[head:head] = _defines(sheet, chords, names, played.shift, v.at)
    return "\n".join(out) + "\n"


def _in_header(line: str) -> bool:
    found = directive(line)
    return (found is not None and found[0] in _HEADER) or _notice(line)


def _notice(line: str) -> bool:
    """Whether ``line`` is an auto sheet's notice (``to_chordpro(auto=True)``)."""
    found = directive(line)
    return found is not None and found[0] in COMMENTS and found[1] == AUTO_MARKER


def _key_text(key: Key) -> str:
    """A key as chordpro reads a ``{key}``: its tonic, and "m" for a mode with a minor third. chordpro 6.050
    reads no mode ("E dorian" is an unknown chord to it), and stops at one beside a capo."""
    return spelling(key)[key.tonic] + ("m" if 3 in SCALES[key.mode] else "")


def _chords(sheet_chords: list[str], v: Version, key: Key | None,
            played: _Played) -> list[tuple[Chord | None, bool]]:
    """Each chord of the sheet as the version plays it (viewer.js ``current``: the chord in the mode, or one
    the viewer offers instead there), and whether it is the chord as the sheet writes it; None for a chord
    caracole can't read."""
    swaps = v.alt.get(played.mode, {}) if key is not None and played.mode is not None else {}
    out: list[tuple[Chord | None, bool]] = []
    for i, name in enumerate(sheet_chords):
        chord = parse_chord(name, strict=False)
        if chord is None or key is None or played.mode is None:
            out.append((chord, True))
            continue
        mapped = map_chord(chord, key, played.mode)
        swap = swaps.get(i)
        instead = None if swap is None else next(
            (a for a in alternatives(mapped, Key(key.tonic, played.mode)) if (a.root, a.suffix, a.bass) == swap), None)
        if instead is not None:
            out.append((instead, False))
        else:
            out.append((chord, True) if played.as_written else (mapped, False))
    return out


def _names(sheet_chords: list[str], chords: list[tuple[Chord | None, bool]], key: Key | None,
           played: _Played) -> list[str]:
    """Each chord of the sheet as the version names it (viewer.js ``label``): as written when it is the chord as
    written, unmoved, or one caracole can't read; else its notes as the mode and the key moved there spell
    them (``nameOf``), its suffix as written."""
    spelled = spelling(None if key is None else Key((key.tonic + played.shift) % 12, played.mode))
    out = []
    for name, (chord, as_written) in zip(sheet_chords, chords, strict=True):
        if chord is None or (as_written and played.shift == 0):
            out.append(name)
        else:
            bass = "" if chord.bass is None else "/" + spelled[(chord.bass + played.shift) % 12]
            out.append(spelled[(chord.root + played.shift) % 12] + chord.suffix + bass)
    return out


def _defines(sheet: Sheet, chords: list[tuple[Chord | None, bool]], names: list[str], shift: int,
             at: Mapping[int, int]) -> list[str]:
    """A ``{define}`` of the shape played for each chord (``at``, else its first), once a name (its first
    place's, as the viewer's rail of necks draws it), for a chord the viewer has a shape for."""
    given = shapes_of(sheet)
    data = load_voicings()
    out, seen = [], set()
    for i, (chord, _) in enumerate(chords):
        name = names[i]
        if chord is None or name in seen or not _NAMEABLE.fullmatch(name):
            continue
        seen.add(name)
        shapes = _shapes(chord, shift, given, data)
        if not shapes:
            continue
        n = at.get(i, 0)
        frets, fingers, base, _ = shapes[n if 0 < n < len(shapes) else 0]
        out.append(f"{{define: {name} base-fret {base} frets {' '.join(frets)} fingers {' '.join(fingers)}}}")
    return out


def _shapes(chord: Chord, shift: int, given: dict[str, dict[str, Any]],
            data: dict[str, list[list[Position]]]) -> list[Position]:
    """The shapes the viewer shows for ``chord`` moved ``shift`` semitones (viewer.js ``shapesOf``): those the
    sheet gives that very chord first, else chords-db's for its slash chord, else for its quality."""
    root = (chord.root + shift) % 12
    shown = f"{root},{chord.suffix},{'' if chord.bass is None else (chord.bass + shift) % 12}"
    if shown in given:
        return given[shown]["list"]
    fingering, _, slash = voicing_keys(chord)
    if slash is not None and slash in data and data[slash][root]:
        return data[slash][root]
    return data[fingering][root] if fingering in data else []
