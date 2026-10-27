"""The harp a harmonica tab (harptab.py) is played on, for its page (harptab_page.py): the one that plays along with
the record, from the song's chord sheet, else the one the tab's words name, else the key harptabs.com's page names,
else harp.py's for the song's key, else a C harp. On top of harptab.py, harp.py, theory.py and sheet.py.

A tab's holes are the same on any harp and sound in its key, and a tabber's word for the harp is often missing or
wrong: harptabs.com's Key chip is the harp's key on some tabs and the song's on others (Juke: the chip E, the tab's
words "I use an A harp"; Wonderwall: the chip Bb, played with the record on an A harp). The chord sheet says which:

**With the record** (``record_fit``). Each sung row of the tab is matched to the sheet's line its words read most
like (``difflib``, at least ``LINE_MATCH`` alike), word by word; each hole blown on a word matched is set against the
chord the sheet plays there, as it sounds (the capo added). Of the 12 harps, the one that puts the most of those
notes on a tone of their chord plays with the record, once ``MIN_NOTES`` notes are counted (Hotel California: a D
harp, 63 % of its notes, an A harp 52 %; Wonderwall: an A harp, 72 %; Free Bird: a G harp, 74 %).

**The choice** (``choose``), each with where it came from (``Choice.why``): "record", "tab" (the tab's words,
``harptab.named_key``), "page" (harptabs.com's Key chip), "song" (harp.py's first harp for the song's key and chords:
``harp.choices``) or "usual" (a C harp, the key a tab is written for when it says none). ``tonic`` is the key the song
sounds in (the sheet's, ``page.viewer_key``, the capo added), which names each harp's position.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, replace

from caracole.viewer import harp
from caracole.viewer.harptab import Tab
from caracole.viewer.sheet import Lyrics, parse_sheet
from caracole.viewer.theory import Chord, Key, parse_chord, sounding

MIN_NOTES = 20  # the sung notes on a chord of the sheet the fit needs before it names a harp
LINE_MATCH = 0.6  # how alike a tab's row and a sheet's line read, word by word, to be the same line
WHY = ("record", "tab", "page", "song", "usual")
_PITCH = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
          "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


@dataclass(frozen=True)
class Fit:
    """A harp's fit with the record: its key (a pitch class), the share of the sung notes on a chord tone, of how
    many."""

    harp: int
    share: float
    notes: int


@dataclass(frozen=True)
class Choice:
    """The harp a tab's page starts on, ``harp`` (a pitch class), and why (one of ``WHY``); the fit with the record,
    best first (``fits``, none without a sheet that matches); the harp the tab's words name and the key its page
    names (pitch classes, or None); and the tonic the song sounds in, or None."""

    harp: int
    why: str
    fits: tuple[Fit, ...] = ()
    named: int | None = None
    page: int | None = None
    tonic: int | None = None

    @property
    def tabs_harp(self) -> int | None:
        """The harp the tab is played on, as far as caracole can tell: the one that plays with the record, else the
        one its words name; None where the page's harp is a guess (harptabs.com's key, the song's key, a C harp).
        The overlay marks it "the tab's", and a chord sheet's starts on it (page.py ``harpTabs``)."""
        return self.harp if self.why in ("record", "tab") else None


def pitch(name: str | None) -> int | None:
    """A key's name, as a tab or harptabs.com writes it ("A", "Bb", "F#"), as a pitch class; None for none."""
    return _PITCH.get((name or "").strip().replace("♭", "b").replace("♯", "#"))


def words(text: str) -> list[str]:
    """``text``'s words as the fit compares them: lower case, a hyphen inside a word gone ("des-ert" is "desert"),
    what is in brackets left out ("(background)")."""
    text = re.sub(r"(?<=\w)-+(?=\w)", "", text.lower().replace("’", "'"))
    return re.findall(r"[^\W_]+(?:'[^\W_]+)*", re.sub(r"\([^)]*\)", " ", text))


def _sheet_lines(cho: str) -> list[list[tuple[str, frozenset[int] | None]]]:
    """Each sung line of a ChordPro sheet: its words, each with the pitch classes of the chord sounding there (the
    capo added; None before the first chord, or for one caracole can't read)."""
    sheet = parse_sheet(cho)
    capo = sheet.capo or 0
    out = []
    for section in sheet.sections:
        sounding_now: frozenset[int] | None = None
        for line in section.lines:
            if not isinstance(line, Lyrics):
                continue
            found = []
            for chord, text in line.parts:
                if isinstance(chord, int):
                    read = parse_chord(sheet.chords[chord], strict=False)
                    sounding_now = None if read is None else frozenset((p + capo) % 12 for p in read.pitch_classes)
                found += [(w, sounding_now) for w in words(text)]
            if found:
                out.append(found)
    return out


def _first_note(group) -> int | None:
    hole = group.holes[0]
    return None if hole.button else harp.hole_note(0, hole.hole, hole.breath, hole.bend, hole.over)


def record_fit(tab: Tab, cho: str) -> list[Fit]:
    """How well each of the 12 harps plays the tab with the record the chord sheet ``cho`` (as caracole writes
    one) charts, best first: the module's docstring. None counted (a sheet with no line like the tab's), none."""
    lines = _sheet_lines(cho)
    if not lines:
        return []
    pairs: list[tuple[int, frozenset[int]]] = []  # each note on a C harp, and the chord sounding there
    for row in tab.rows():
        if row.lyric is None:
            continue
        sung: list[tuple[str, list[int]]] = []
        for groups, text in row.parts:
            notes = [n for g in groups if (n := _first_note(g)) is not None]
            said = words(text)
            if not said:
                if sung:
                    sung[-1][1].extend(notes)
                continue
            sung += [(w, notes if k == 0 else []) for k, w in enumerate(said)]
        mine = [w for w, _ in sung]
        if not mine:
            continue
        best, ratio = None, 0.0
        for line in lines:
            alike = difflib.SequenceMatcher(None, mine, [w for w, _ in line], autojunk=False).ratio()
            if alike > ratio:
                best, ratio = line, alike
        if best is None or ratio < LINE_MATCH:
            continue
        matcher = difflib.SequenceMatcher(None, mine, [w for w, _ in best], autojunk=False)
        for block in matcher.get_matching_blocks():
            for k in range(block.size):
                chord = best[block.b + k][1]
                if chord:
                    pairs += [(n, chord) for n in sung[block.a + k][1]]
    if not pairs:
        return []
    fits = [Fit(t, sum((n + t) % 12 in chord for n, chord in pairs) / len(pairs), len(pairs)) for t in range(12)]
    return sorted(fits, key=lambda f: (-f.share, f.harp))


def _song_key(cho: str, key: str | None, key_source: str | None) -> tuple[Key | None, list[Chord]]:
    """The key the song sounds in (the sheet's, as its viewer names it, the capo added), and its chords as they
    sound; None and none for a sheet with no key."""
    from caracole.viewer.page import viewer_key  # page.py imports this module's page

    shapes = viewer_key(cho, key, key_source)
    if shapes is None:
        return None, []
    sheet = parse_sheet(cho)
    capo = sheet.capo or 0
    chords = []
    for name in sheet.chords:
        chord = parse_chord(name, strict=False)
        if chord is not None:
            chords.append(replace(chord, root=(chord.root + capo) % 12,
                                  bass=None if chord.bass is None else (chord.bass + capo) % 12))
    return sounding(shapes, capo), chords


def choose(tab: Tab, *, cho: str | None = None, key: str | None = None, key_source: str | None = None,
           page_key: str | None = None) -> Choice:
    """The harp the tab's page starts on (the module's docstring): ``cho`` is the song's chord sheet (its ChordPro
    as caracole writes it), ``key`` and ``key_source`` its key as keys.py found it, ``page_key`` the key
    harptabs.com's page names."""
    named, page = pitch(tab.key), pitch(page_key)
    song, chords = _song_key(cho, key, key_source) if cho else (None, [])
    tonic = None if song is None else song.tonic
    fits = tuple(record_fit(tab, cho)) if cho and tab.readable else ()
    if fits and fits[0].notes >= MIN_NOTES:
        return Choice(fits[0].harp, "record", fits, named, page, tonic)
    if named is not None:
        return Choice(named, "tab", fits, named, page, tonic)
    if page is not None:
        return Choice(page, "page", fits, named, page, tonic)
    if song is not None and (found := harp.choices(song, chords)):
        return Choice(found[0].harp, "song", fits, named, page, tonic)
    return Choice(0, "usual", fits, named, page, tonic)
