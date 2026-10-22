"""A version of a sheet as its viewer shows it, applied in Python: the text a PDF of that version is made from.

The viewer (viewer.js) keeps where a song is played in its address: ``t``, the semitones it moved; ``mode``, one
of ``theory.MODES``; ``capo``, the fret the capo is on; ``alt``, the chords played instead of others
(``alt=<mode>.<chord>.<root>.<suffix>.<bass>,…``); and ``at``, the shape chosen for a chord
(``at=<chord>.<shape>,…``), each chord by its index in the sheet (``Sheet.chords``). ``Version`` is that,
``version_from_query`` reads it from an address as the viewer reads it, and ``version_query`` writes it as the
viewer's ``save()`` does. ``version_label`` names it: "G Dorian, capo 0".

A ``Setting`` is where a song is played by the key of the shapes played, its mode and its capo, rather than by a
move from its sheet: a songbook's setting for a song. ``in_setting`` makes it a version of a sheet, whatever key
and capo the sheet has. ``KeyVersion`` is the song's own version as Make this my version keeps it in
overrides.toml's ``[version]`` (``key=Gm&mode=dorian&capo=0&alt=F.Fmaj7&at=Gm.x-x-5-7-8-6``): the key its chords
are in, as the sheet reads them, a mode chosen beside it, its capo, and the chords played instead and the shapes
chosen, each by its chord's name there. ``version_entry`` writes one from a version of a sheet, ``key_version``
reads one, and ``in_key`` plays it on any sheet, the song's or another in its place, by the setting's rule.

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
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qsl, quote, unquote

from caracole.autochords.merge import AUTO_MARKER
from caracole.viewer.page import shapes_of
from caracole.viewer.sheet import COMMENTS, Sheet, directive, is_legend_line, parse_sheet
from caracole.viewer.theory import (
    MODES,
    SCALES,
    Chord,
    Key,
    alternatives,
    key_name,
    map_chord,
    note_pc,
    parse_chord,
    parse_key,
    scale,
    spelling,
)
from caracole.viewer.voicings import TUNING, Position, frets_from_nut, load_voicings, parse_define, voicing_keys

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


# --- where a setting plays it: by the key of its shapes ------------------------------------------

CAPO_MAX = 11  # the highest fret a setting's capo names (viewer.js CAPO_MAX)
_TONIC = re.compile(r"[A-G][#b]?")


@dataclass(frozen=True)
class Setting:
    """Where a song is played by the key of the shapes played rather than by a move from its sheet, each part
    None where it says nothing: ``key``, the tonic of those shapes, as written ("G", "F#", "Bb"); ``mode``, one of
    ``theory.MODES``; ``capo``, a fret up to ``CAPO_MAX``. A songbook's setting for a song (songbook.py).
    ``in_setting`` makes it a version of a sheet; the song's own version kept by its key (``KeyVersion``) is placed
    by the same rule."""

    key: str | None = None
    mode: str | None = None
    capo: int | None = None

    def __bool__(self) -> bool:
        return self.key is not None or self.mode is not None or self.capo is not None


def setting_problem(key: Any = None, mode: Any = None, capo: Any = None) -> str | None:
    """Why these parts make no ``Setting``, in words, or None when they make one."""
    if key is not None and not (isinstance(key, str) and _TONIC.fullmatch(key)):
        return f'key must be a tonic such as "G", "F#" or "Bb", got {key!r}'
    if mode is not None and mode not in MODES:
        return f"mode must be one of {', '.join(MODES)}, got {mode!r}"
    if capo is not None and (isinstance(capo, bool) or not isinstance(capo, int) or not 0 <= capo <= CAPO_MAX):
        return f"capo must be a fret from 0 to {CAPO_MAX}, got {capo!r}"
    return None


def places(setting: Setting | None) -> bool:
    """Whether the setting names a key or a mode, which only a sheet with a key can take."""
    return setting is not None and (setting.key is not None or setting.mode is not None)


def in_setting(own: Version, setting: Setting | None, shapes: Key | None, capo_sheet: int | None) -> Version:
    """The version a setting plays a song in: the key of the shapes played (as ``version_label`` names a version,
    "G Dorian, capo 0"), the mode and the capo, and for what it leaves out the song's own version's (``own``).
    ``shapes`` and ``capo_sheet`` are the sheet's, as its viewer reads them (``page.viewer_key``, its ``{capo}``):
    the key is the setting's, whatever key and capo the sheet has.

    With the capo where the sheet has it, ``t`` is the setting's tonic less the sheet's shapes' (to within six
    semitones), and another capo moves the shapes, as on a guitar. A setting with a key or a mode is the sheet
    as written (``Version()``) for a sheet with no key (no chord caracole can read): nothing places it there.
    Shapes chosen in the song's own version (``at``) are for the chords that plays, so they go when the setting
    plays others; its chords played instead (``alt``) are kept by mode, as the viewer keeps them."""
    if not setting:
        return own
    if places(setting) and shapes is None:
        return Version()
    tonic = None if setting.key is None else note_pc(setting.key[0], setting.key[1:])
    return _placed(own, tonic, setting.mode, setting.capo, shapes, capo_sheet)


def _placed(own: Version, tonic: int | None, mode: str | None, capo: int | None, shapes: Key | None,
            capo_sheet: int | None) -> Version:
    """The setting's rule (``in_setting``), for the tonic of the shapes played (a pitch class), a mode and a capo,
    each None for the own version's: ``KeyVersion``s are placed by it too (``in_key``)."""
    mode = own.mode if mode is None else mode
    capo = own.capo if capo is None else capo
    t = own.t
    if tonic is not None:
        unmoved, _ = played_key(Version(mode=mode, capo=capo), shapes, capo_sheet)  # its shapes at t = 0
        t = (tonic - unmoved.tonic + 5) % 12 - 5
    if (t, mode, capo) == (own.t, own.mode, own.capo):
        return own
    return replace(own, t=t, mode=mode, capo=capo, at={})


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
    as do a chord legend's lines (``sheet.is_legend``: "Am x02210" names the shape beside it), marks, tabs and the
    rest of the text. The header names the version's key (of its shapes, as chordpro reads a key: "Em" for E
    dorian) and its capo, and after it comes a ``{define}`` of each chord's chosen shape, once a name, in place of
    the sheet's own ``{define}``s that the viewer reads. No ``{transpose}`` is left: the chords are where the
    version plays them.
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
        elif not line.startswith("#") and not is_legend_line(line):  # a legend names the shapes it gives as written
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


# --- a version kept by its key ([version], "Make this my version") ----------------------------------------

# What a chord's name in a kept version escapes: what would split it, and space.
_ESCAPED = re.compile(r"[%&=,.\s]")
# A key as a sheet names it (theory.key_name): "G", "F#m", "Bb dorian".
_KEY_NAME = re.compile(r"[A-G][#b]?(?:m| (?:" + "|".join(MODES) + "))?")
Frets = tuple[int | None, ...]  # a shape: each string's fret from the nut, low E first, None where it isn't played


@dataclass(frozen=True)
class KeyVersion:
    """A song's own version kept by the key it plays in, as Make this my version writes overrides.toml's
    ``[version]`` (``key=Gm&mode=dorian&capo=0&alt=F.Fmaj7&at=Gm.x-x-5-7-8-6``), so that a sheet in another key or
    capo in its sheet's place plays there too: ``key``, the key of the shapes played, in the mode the sheet's
    chords were read in (G minor for an A minor sheet played two down), whose notes another sheet's chords are read
    in, whatever key it names for them (C major's are A minor's); ``mode``, a mode chosen to play it in (dorian),
    None for that key's own; ``capo``, None for the sheet's; the chords played instead (``alt``: each chord as the
    version names it, then the chord played in its place); and the shapes chosen (``at``: each chord as the version
    names it, then that shape's frets). ``in_key`` plays it on a sheet; ``query`` writes it, and ``key_version``
    reads it back."""

    key: Key
    mode: str | None = None
    capo: int | None = None
    alt: tuple[tuple[str, str], ...] = ()
    at: tuple[tuple[str, Frets], ...] = ()

    def query(self) -> str:
        """The entry as caracole writes it: ``key`` (as a sheet names one: "Gm", "F#", "A dorian"), ``mode``,
        ``capo``, ``alt`` and ``at`` (a shape's frets from the nut, low E first, "x" for a string not played:
        "x-x-5-7-8-6"), each left out where it says nothing. In a chord's name, "%", "&", "=", ",", "." and space are
        escaped ("C6%2E9"), the rest of it written as it is ("F#m", "C#7(b9)"), so that the entry reads well in
        overrides.toml."""
        params = [("key", key_name(self.key)), ("mode", self.mode),
                  ("capo", None if self.capo is None else str(self.capo)),
                  ("alt", ",".join(f"{_escape(a)}.{_escape(b)}" for a, b in self.alt)),
                  ("at", ",".join(f"{_escape(name)}.{_frets_text(frets)}" for name, frets in self.at))]
        return "&".join(f"{name}={value}" for name, value in params if value)

    def label(self) -> str:
        """The version in words, as ``version_label`` names it on the sheet it was made on ("G Dorian, capo 0";
        "G Dorian" with the sheet's capo)."""
        played = Key(self.key.tonic, self.mode or self.key.mode)
        words = f"{spelling(played)[played.tonic]} {MODE_NAMES[played.mode]}"
        return words if self.capo is None else f"{words}, capo {self.capo}"


def _escape(name: str) -> str:
    return _ESCAPED.sub(lambda m: "".join(f"%{byte:02X}" for byte in m.group(0).encode("utf-8")), name)


def _frets_text(frets: Frets) -> str:
    return "-".join("x" if fret is None else str(fret) for fret in frets)


def _frets(text: str) -> Frets | None:
    """A shape's frets as an entry writes them ("x-x-5-7-8-6"), or None for text that is none: a fret a string,
    from the nut, and at least one string played."""
    parts = text.split("-")
    if len(parts) != len(TUNING) or not all(p == "x" or (p.isascii() and p.isdigit() and len(p) <= 2) for p in parts):
        return None
    frets = tuple(None if p == "x" else int(p) for p in parts)
    return None if all(fret is None for fret in frets) else frets


def _text(value: str) -> str:
    """A part of an entry, its escapes undone; as written where one doesn't decode."""
    try:
        return unquote(value, errors="strict")
    except UnicodeDecodeError:
        return value


def _chord_name(text: str) -> str | None:
    """A chord's name in a kept version's ``alt`` or ``at``, its escapes undone; None for one whose escapes don't
    decode or that names no chord ``theory.parse_chord`` can read ("Hm", "3")."""
    if _BAD_ESCAPE.search(text):
        return None
    try:
        name = unquote(text, errors="strict").strip()
    except UnicodeDecodeError:
        return None
    return name if parse_chord(name, strict=False) is not None else None


def key_version(text: str) -> KeyVersion | None:
    """The version a ``[version]`` entry keeps by its key (``KeyVersion``), or None for one that names no ``key``:
    a move from the sheet (``t=2&mode=dorian``), as the viewer's address writes it and caracole wrote
    ``[version]`` before it kept a key (``version_from_query`` reads that). A "#" or a "?" before it is dropped,
    and of a name given twice the first counts, as in an address.

    Raises ValueError, saying why, for a key that is none as a sheet names one ("G", "F#m", "Bb dorian"), a mode or
    a capo that can't be one (``setting_problem``: a blank mode or capo is none), or a key beside a ``t``. A swap
    or a shape it can't read is dropped, as the viewer drops one from its address."""
    if text[:1] in ("#", "?"):
        text = text[1:]
    params: dict[str, str] = {}
    for part in text.split("&"):
        if part:
            name, _, value = part.partition("=")
            params.setdefault(name, value)
    if "key" not in params:
        return None
    if "t" in params:
        raise ValueError("a key or a t, not both: key=G is the key the song plays in, t=2 a move from its sheet")
    named = _text(params["key"])
    key = parse_key(named) if _KEY_NAME.fullmatch(named) else None
    if key is None:
        raise ValueError(f'key must be a key as a sheet names it, such as "G", "F#m" or "Bb dorian", got {named!r}')
    mode = _text(params.get("mode", "")) or None
    capo_text = _text(params.get("capo", ""))
    capo: Any = int(capo_text) if capo_text.isascii() and capo_text.isdigit() else capo_text or None
    if (problem := setting_problem(None, mode, capo)) is not None:
        raise ValueError(problem)
    swaps: dict[str, str] = {}
    for part in params.get("alt", "").split(","):
        names = [_chord_name(piece) for piece in part.split(".")]
        if len(names) == 2 and names[0] and names[1]:
            swaps.setdefault(names[0], names[1])
    shapes: dict[str, Frets] = {}
    for part in params.get("at", "").split(","):
        pieces = part.split(".")
        if len(pieces) == 2 and (name := _chord_name(pieces[0])) and (frets := _frets(pieces[1])) is not None:
            shapes.setdefault(name, frets)
    return KeyVersion(key, mode, capo, tuple(swaps.items()), tuple(shapes.items()))


def _sound(chord: Chord, shift: int = 0) -> tuple[int, frozenset[int], int | None]:
    """A chord as it sounds, moved ``shift`` semitones: its root, its intervals and its bass, however it is spelled."""
    return ((chord.root + shift) % 12, chord.intervals, None if chord.bass is None else (chord.bass + shift) % 12)


def _sounds(names: Iterable[str]) -> list[tuple[int, frozenset[int], int | None]]:
    return [_sound(parse_chord(name, strict=False)) for name in names]  # key_version read each


def _relative(key: Key, mode: str) -> int:
    """The degree (0 its tonic) ``key``'s tonic is in the key of its notes in ``mode``: 2 for C major in A minor,
    5 for A minor in C major. Each mode is the others' notes from another degree, so there is one."""
    return next(degree for degree, interval in enumerate(SCALES[mode])
                if scale(Key((key.tonic - interval) % 12, mode)) == scale(key))


def _fitting(key: Key, names: Iterable[str]) -> int:
    """How many of the chords named (a sheet's, as written) have every note, their bass too, in ``key``."""
    notes = scale(key)
    count = 0
    for name in names:
        chord = parse_chord(name, strict=False)
        if chord is not None and {(chord.root + i) % 12 for i in chord.intervals} <= notes \
                and (chord.bass is None or chord.bass in notes):
            count += 1
    return count


def _from_degree(mode: str, degree: int) -> str:
    """The mode ``mode``'s notes make from its ``degree``: lydian from dorian's third (G dorian's notes from Bb)."""
    steps = SCALES[mode]
    intervals = tuple((steps[(n + degree) % 7] - steps[degree]) % 12 for n in range(7))
    return next(m for m in MODES if SCALES[m] == intervals)


def in_key(kept: KeyVersion, cho: str, *, key: Key | None, capo_sheet: int | None) -> Version:
    """Where the version kept by its key plays the ChordPro sheet ``cho`` (``key`` and ``capo_sheet`` as for
    ``apply_version``), by the setting's rule (``in_setting``: its key the key of the shapes played, its capo
    whatever capo the sheet has), with each chord its ``alt`` names played instead, where the viewer offers that
    chord for it there, and each chord its ``at`` names given the shape of those frets, where its viewer lists one.
    A swap or a shape for a chord the version doesn't play on this sheet is none, wherever the chord is on the
    sheet it was made on. A sheet with no key plays it as written (``Version()``), as it does a songbook's setting.

    The sheet's chords are read in the notes of its key, in the kept key's mode: a sheet in C major whose version
    is kept in B minor (from A minor, two up) is read in A minor, its notes, and plays two up too, its chords those
    the version played. A mode chosen moves the same degrees of that reading; the viewer names that mode by the
    sheet's own tonic (G dorian's chords, on that sheet, are its Bb lydian's: the same notes from another degree),
    and a note outside the key moves with its tonic, a semitone off where the two readings' tonics part.

    A sheet whose chords are more of them in its tonic's key in the kept key's mode than in the key it names (an A
    minor sheet that names A, as a key read from audio can) is read from its own tonic instead, the kept key's
    tonic, and plays there as a move from it (``t``, with the mode chosen), as a ``t=`` entry did."""
    if key is None:
        return Version()
    sheet = parse_sheet(cho)
    parallel = Key(key.tonic, kept.key.mode)
    if parallel != key and _fitting(parallel, sheet.chords) > _fitting(key, sheet.chords):
        chosen = None if kept.mode == key.mode else kept.mode
        placed = _placed(Version(), kept.key.tonic, chosen, kept.capo, key, capo_sheet)
    else:
        degree = _relative(key, kept.key.mode)  # where the sheet's tonic is in the kept key's reading of its notes
        mode = kept.mode or kept.key.mode
        played_mode = _from_degree(mode, degree)
        tonic = (kept.key.tonic + SCALES[mode][degree]) % 12  # of the shapes, on the sheet's own tonic
        placed = _placed(Version(), tonic, None if played_mode == key.mode else played_mode, kept.capo, key,
                         capo_sheet)
    played = _played(placed, key, capo_sheet)
    instead = dict(zip(_sounds(a for a, _ in kept.alt), _sounds(b for _, b in kept.alt), strict=True))
    swaps: dict[int, Swap] = {}
    for i, (chord, _) in enumerate(_chords(sheet.chords, placed, key, played)):
        wanted = None if chord is None else instead.get(_sound(chord, played.shift))
        if wanted is None:
            continue
        written = parse_chord(sheet.chords[i], strict=False)
        offered = alternatives(map_chord(written, key, played.mode), Key(key.tonic, played.mode))
        found = next((a for a in offered if _sound(a, played.shift) == wanted), None)
        if found is not None:
            swaps[i] = (found.root, found.suffix, found.bass)
    version = replace(placed, alt={played.mode: swaps}) if swaps else placed
    chosen = dict(zip(_sounds(name for name, _ in kept.at), (frets for _, frets in kept.at), strict=True))
    given, data = shapes_of(sheet), load_voicings()
    positions = {}
    for i, (chord, _) in enumerate(_chords(sheet.chords, version, key, played)):
        frets = None if chord is None else chosen.get(_sound(chord, played.shift))
        if frets is None:
            continue
        listed = _shapes(chord, played.shift, given, data)
        n = next((n for n, shape in enumerate(listed) if frets_from_nut(shape) == frets), None)
        if n:  # the first is the one played anyway
            positions[i] = n
    return replace(version, at=positions) if positions else version


def version_entry(v: Version, cho: str, *, key: Key | None, capo_sheet: int | None) -> str | None:
    """The ``[version]`` entry Make this my version writes for the version ``v`` of the ChordPro sheet ``cho``
    (``key`` and ``capo_sheet`` as for ``apply_version``): ``v`` kept by its key (``KeyVersion.query``), the key of
    the shapes it plays in the mode the sheet's chords are read in ("Gm"), the mode it plays them in where that is
    another, chosen ("dorian"), and its capo (none past ``CAPO_MAX``: the sheet's), then the chords it plays instead
    and the shapes it chose, each chord by its name there, in its mode alone: what its PDF shows. So "G Dorian,
    capo 0" on an A minor sheet is ``key=Gm&mode=dorian&capo=0``, and "B Minor, capo 0" there ``key=Bm&capo=0``.

    None for a sheet with no key: there's none to keep (render.py writes the version as an address, a move from the
    sheet)."""
    played = _played(v, key, capo_sheet)
    if key is None or played.mode is None:
        return None
    shapes = Key((key.tonic + played.shift) % 12, key.mode)
    capo = played.capo if played.capo <= CAPO_MAX else None
    sheet = parse_sheet(cho)
    plain = _chords(sheet.chords, replace(v, alt={}), key, played)
    chords = _chords(sheet.chords, v, key, played)
    before, names = _names(sheet.chords, plain, key, played), _names(sheet.chords, chords, key, played)
    swaps: dict[str, str] = {}
    for i, ((was, _), (now, _)) in enumerate(zip(plain, chords, strict=True)):
        if now is not None and now != was:
            swaps.setdefault(before[i], names[i])
    given, data = shapes_of(sheet), load_voicings()
    shown: dict[str, Frets] = {}
    seen: set[str] = set()
    for i, (chord, _) in enumerate(chords):  # a shape a name, its first place's, as _defines draws it
        if chord is None or names[i] in seen:
            continue
        seen.add(names[i])
        n = v.at.get(i, 0)
        listed = _shapes(chord, played.shift, given, data)
        if 0 < n < len(listed):
            shown[names[i]] = frets_from_nut(listed[n])
    kept = KeyVersion(shapes, None if played.as_written else played.mode, capo, tuple(swaps.items()),
                      tuple(shown.items()))
    return kept.query()
