"""caracole.viewer.version: a version of a sheet as its viewer shows it (key, capo, mode, shapes, swaps),
applied in Python to the ChordPro text a PDF is made from."""

from __future__ import annotations

import dataclasses
import json
import re
from html import unescape
from pathlib import Path

import pytest
from helpers import browser
from helpers.browser import in_chromium

from caracole.viewer import build_viewer, version
from caracole.viewer.page import HERE, shapes_of, viewer_key
from caracole.viewer.sheet import ChordRow, Lyrics, directive, parse_sheet
from caracole.viewer.theory import Key, alternatives, map_chord, parse_chord
from caracole.viewer.version import Version, apply_version, version_from_query, version_label, version_query
from caracole.viewer.voicings import Position, load_voicings

FIXTURES = Path(__file__).parent / "fixtures" / "chordpro"
UG = (FIXTURES / "ug_sheet.cho").read_text(encoding="utf-8")  # G shapes, capo 2
LEGEND = (FIXTURES / "legend_sheet.cho").read_text(encoding="utf-8")  # capo 2, a chord legend, no key
# Chords theory.parse_chord can't read: "N.C.", a German B minor, a chord in brackets; and Cadd9(no3),
# which it reads as C, D and G (a Csus2 written otherwise).
ODD = "{title: Odd}\n{artist: A}\n{key: C}\n[N.C.]la [Cadd9(no3)]lo [Hm]li [G]le [(G)]lu\n[C] [N.C.] [*x2]\n"


def applied(cho: str, v: Version, key: str | None = None) -> str:
    """``cho`` in the version ``v``, with the key and the capo its viewer reads (``key``: the song's, as
    info.json gives it)."""
    return apply_version(cho, v, key=viewer_key(cho, key), capo_sheet=parse_sheet(cho).capo)


def played(cho: str) -> list[str]:
    """Every chord a ChordPro text plays, each time it plays it, as it names it: in the order its viewer
    shows them, preamble and all."""
    sheet = parse_sheet(cho)
    out = []
    for section in sheet.sections:
        for line in section.lines:
            if isinstance(line, Lyrics):
                out += [sheet.chords[c] for c, _ in line.parts if isinstance(c, int)]
            elif isinstance(line, ChordRow):
                out += [sheet.chords[c] for c in line.items if isinstance(c, int)]
    return out


def directives(cho: str, name: str) -> list[str]:
    return [found[1] for line in cho.splitlines() if (found := directive(line)) and found[0] == name]


def define_of(name: str, position: Position) -> str:
    frets, fingers, base, _ = position
    return f"{name} base-fret {base} frets {' '.join(frets)} fingers {' '.join(fingers)}"


# --- naming the chords ---------------------------------------------------------------------------


def test_a_version_names_chords_as_the_viewer_does():
    assert viewer_key(LEGEND, "Em") == Key(4, "aeolian")  # Em shapes, the song's key
    up = applied(LEGEND, Version(t=1), "Em")  # F minor: flats
    assert "[Fm7]Made up words f[Ab]or the test" in up
    assert "[Ebsus4]and another lin[Bb7sus4]e of them" in up
    assert "[Dbadd9]Still more [Ebsus4/G]words to sing" in up
    dorian = applied(LEGEND, Version(mode="dorian"), "Em")  # E dorian: C becomes C#, its chord a C#m7b5
    assert "[C#m7b5]Still more [Dsus4/F#]words to sing" in dorian
    assert "[Em7]Made up words f[G]or the test" in dorian
    # As written, every chord is named as the sheet writes it; marks and tabs stay as they are
    assert played(applied(UG, Version())) == played(UG)
    assert "[*x2]" in applied(UG, Version(t=5)) and "e|-----0---0---|" in applied(UG, Version(t=5))


def test_a_capo_names_the_shapes_and_a_swap_plays_its_chord():
    # The chords name the shapes played: three up with the capo a fret higher (3, on a sheet with capo 2) is
    # two up, A shapes; two up with the capo off is four up, B shapes.
    assert played(applied(UG, Version(t=3, capo=3)))[:4] == ["A", "E", "F#m", "D"]
    assert played(applied(UG, Version(t=2, capo=0)))[:4] == ["B", "F#", "G#m", "E"]
    # A chord played instead of G, among those the viewer offers for it in G major, named as moved
    gmaj7 = next(a for a in alternatives(parse_chord("G"), Key(7, "ionian")) if a.suffix == "maj7")
    swap = {"ionian": {0: (gmaj7.root, gmaj7.suffix, gmaj7.bass)}}
    assert played(applied(UG, Version(alt=swap)))[:2] == ["Gmaj7", "D"]
    assert played(applied(UG, Version(t=2, alt=swap)))[:2] == ["Amaj7", "E"]
    # A swap the viewer doesn't offer, or one kept for another mode, changes nothing
    assert played(applied(UG, Version(alt={"ionian": {0: (1, "dim", None)}})))[0] == "G"
    assert played(applied(UG, Version(mode="dorian", alt=swap)))[0] == "Gm"  # G dorian's own


def test_an_unreadable_chord_stays_as_written():
    # No version renames a chord caracole can't read, gives it a shape, or fails on it: with a key or none.
    versions = (Version(), Version(t=2), Version(t=-5, capo=3), Version(mode="dorian"), Version(mode="phrygian", t=7),
                Version(t=1, at={0: 1, 2: 3, 4: 1}, alt={"ionian": {0: (0, "", None), 2: (11, "m", None)}}))
    for v in versions:
        for key in (Key(0, "ionian"), None):
            out = apply_version(ODD, v, key=key, capo_sheet=None)
            names = played(out)
            assert (names[0], names[2], names[4], names[6]) == ("N.C.", "Hm", "(G)", "N.C."), v
            assert not any(d.split()[0] in ("N.C.", "Hm", "(G)") for d in directives(out, "define")), v
    # Cadd9(no3) moves with the song as the viewer moves it, its suffix as the sheet writes it
    assert played(applied(ODD, Version()))[1] == "Cadd9(no3)"
    assert played(applied(ODD, Version(t=2)))[1] == "Dadd9(no3)"
    assert played(apply_version(ODD, Version(t=-1), key=None, capo_sheet=None))[1] == "Badd9(no3)"


def test_the_header_names_the_versions_key_and_capo_and_nothing_transposes():
    out = applied(LEGEND, Version(t=1), "Em")
    assert directives(out, "key") == ["Fm"] and directives(out, "capo") == ["2"]
    assert directives(applied(UG, Version(t=3, capo=3)), "key") == ["A"]
    assert directives(applied(UG, Version(t=3, capo=3)), "capo") == ["3"]
    assert directives(applied(UG, Version(capo=0)), "capo") == []  # no capo
    # chordpro 6.050 reads no mode in a {key}, and stops at one with a capo: a mode's key is its tonic chord
    assert directives(applied(LEGEND, Version(mode="dorian"), "Em"), "key") == ["Em"]
    assert directives(applied(UG, Version(mode="mixolydian", t=-2)), "key") == ["F"]
    assert directives(applied(UG, Version(mode="locrian")), "key") == ["Gm"]
    moved = applied("{title: T}\n{artist: A}\n{transpose: 2}\n{key: G}\n[G]la\n{transpose: 3}\n[C]lo\n", Version(t=2))
    assert "transpose" not in moved
    assert moved.splitlines()[:3] == ["{title: T}", "{artist: A}", "{key: A}"]
    assert played(moved) == ["A", "D"]
    # a sheet with no key of its own gets the one its viewer reads, in the header: estimated, or the song's
    assert applied(LEGEND, Version()).splitlines()[:4] == ["{title: Legend Song}", "{artist: The Placeholders}",
                                                         "{key: G}", "{capo: 2}"]
    assert applied(LEGEND, Version(), "Em").splitlines()[2] == "{key: Em}"
    # an auto sheet's notice stays in the header, after them
    auto = "{title: T}\n{artist: A}\n{comment: auto-generated, unverified}\n[Am]la [C]lo [Am]li\n"
    assert applied(auto, Version(t=2)).splitlines()[:4] == ["{title: T}", "{artist: A}", "{key: Bm}",
                                                          "{comment: auto-generated, unverified}"]


# --- the shapes ----------------------------------------------------------------------------------


def test_a_chosen_position_becomes_its_define():
    data = load_voicings()
    c = parse_sheet(UG).chords.index("C")
    out = applied(UG, Version(at={c: 2}))
    defines = directives(out, "define")
    assert define_of("C", data[""][0][2]) in defines  # C's third shape, chords-db's
    assert define_of("G", data[""][7][0]) in defines  # every other chord its first
    assert len(defines) == len(set(played(out)))  # one for each chord played
    # moved, the shape is the one of the chord now played
    assert define_of("D", data[""][2][1]) in directives(applied(UG, Version(t=2, at={c: 1})), "define")
    # a position the chord hasn't is its first, as in the viewer
    assert define_of("C", data[""][0][0]) in directives(applied(UG, Version(at={c: 99})), "define")
    # the sheet's own shapes come first, as the viewer shows them: Cadd9's from its chord legend
    cadd9 = parse_sheet(LEGEND).chords.index("Cadd9")
    given = shapes_of(parse_sheet(LEGEND))["0,add9,"]["list"]
    assert define_of("Cadd9", given[0]) in directives(applied(LEGEND, Version()), "define")
    assert define_of("Cadd9", given[1]) in directives(applied(LEGEND, Version(at={cadd9: 1})), "define")
    # once Cadd9 moves, the sheet's shape for it is no shape for the chord played: chords-db's
    assert define_of("Dadd9", data["add9"][2][0]) in directives(applied(LEGEND, Version(t=2)), "define")


def test_a_sheets_own_defines_give_way_to_the_versions():
    cho = ("{title: T}\n{artist: A}\n{key: G}\n{define: G base-fret 1 frets 3 2 0 0 0 3 fingers 2 1 0 0 0 3}\n"
           "{define: Q keys 0 4 7}\n[G]la [C]lo\n")
    shapes = shapes_of(parse_sheet(cho))["7,,"]["list"]
    defines = directives(applied(cho, Version(at={0: 1})), "define")
    assert [d for d in defines if d.startswith("G ")] == [define_of("G", shapes[1])]  # the chosen one, once
    assert "Q keys 0 4 7" in defines  # one the viewer can't read stays as it is
    # a slash chord's own shape comes before chords-db's for it (x20003 first)
    slash = "{title: T}\n{artist: A}\n{key: G}\n{define: G/B base-fret 1 frets x 2 0 0 3 3 fingers 0 1 0 0 3 4}\n[G/B]la\n"
    assert directives(applied(slash, Version()), "define") == ["G/B base-fret 1 frets x 2 0 0 3 3 fingers 0 1 0 0 3 4"]


# --- the address ---------------------------------------------------------------------------------


def test_the_query_round_trips():
    v = Version(t=-3, mode="dorian", capo=0, at={3: 2, 0: 1},
                alt={"dorian": {3: (1, "7#9", None), 0: (4, "m7", 11)}, "lydian": {2: (0, "6/9.x", 4)}})
    query = ("t=-3&mode=dorian&capo=0&alt=dorian.0.4.m7.11%2Cdorian.3.1.7%25239.%2Clydian.2.0.6%252F9%252Ex.4"
             "&at=0.1%2C3.2")
    assert version_query(v) == query  # as the viewer's save() writes it
    assert version_from_query(query) == v
    assert version_from_query("#" + query) == v  # an address's fragment
    assert version_query(Version()) == "" and version_from_query("") == Version()
    # read as the viewer reads its address: the rest of it left out, what it can't read dropped
    assert version_from_query("fs=20&t=2&speed=8&chord=3&panel=1") == Version(t=2)
    assert version_from_query("t=40") == Version(t=11) and version_from_query("t=-2.6") == Version(t=-3)
    assert version_from_query("t=up&mode=funky&capo=-1") == Version()
    assert version_from_query("capo=") == Version() and version_from_query("capo=2.5") == Version(capo=3)
    assert version_from_query("at=1.0,2.x,03.1,4.2,4") == Version(at={4: 2})
    # (a suffix whose escapes don't decode: "%zz", half a character)
    assert version_from_query("alt=dorian.1.2.m.,funky.1.2.m.,dorian.x.2.m.,dorian.2.2.m.y,dorian.3.2.%25zz.,"
                              "dorian.4.2.%25E0%25A4.") == Version(alt={"dorian": {1: (2, "m", None)}})
    assert version_from_query("alt=dorian.1.2") == Version(alt={"dorian": {1: (2, "", None)}})
    # a version is a value
    assert hash(version_from_query(query)) == hash(v) and len({v, version_from_query(query)}) == 1
    assert dataclasses.replace(v, t=0) == Version(mode="dorian", capo=0, at=v.at, alt=v.alt)


def test_a_version_is_named_by_the_key_of_its_shapes_and_its_capo():
    assert version_label(Version(mode="dorian", capo=0), Key(7, "ionian"), 0) == "G Dorian, capo 0"
    assert version_label(Version(), Key(7, "ionian"), 2) == "G Major, capo 2"
    assert version_label(Version(t=3, capo=3), Key(7, "ionian"), 2) == "A Major, capo 3"  # A shapes
    assert version_label(Version(t=1), Key(4, "aeolian"), 2) == "F Minor, capo 2"
    assert version_label(Version(t=-1, mode="ionian"), Key(1, "ionian"), None) == "C Major, capo 0"
    assert version_label(Version(t=2, mode="lydian"), Key(0, "ionian"), None) == "D Lydian, capo 0"
    assert version_label(Version(), None, 3) == "As written, capo 3"
    assert version_label(Version(t=2, capo=0), None, 3) == "Transposed +2, capo 0"
    assert version_label(Version(t=-4), None, None) == "Transposed -4, capo 0"
    # the modes are named as the viewer's settings name them
    script = (HERE / "viewer.js").read_text(encoding="utf-8")
    block = re.search(r"const MODES = \{(.*?)\};", script, re.S).group(1)
    assert dict(re.findall(r'(\w+): \["([^"]+)"', block)) == version.MODE_NAMES


# --- the viewer and Python agree -----------------------------------------------------------------

# Every chord's label, in turn, and the address the viewer keeps once it read it (its save()).
HARNESS = """<script>
window.addEventListener("load", () => {
  document.body.dataset.result = JSON.stringify([location.hash,
    [...document.querySelectorAll("#sheet .c")].map((c) => c.textContent)]);
});
</script>
"""


def shown(cho: str, key: str | None, query: str, tmp_path: Path) -> tuple[str, list[str]]:
    """The address of ``cho``'s viewer (``key``: the song's) opened at ``#query`` once its script ran, and each
    chord it shows, in turn, in Chromium."""
    html = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>\n', "", build_viewer(cho, key=key))
    page = tmp_path / "Artist" / "Title" / "sheet.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(html.replace("</body>", HARNESS + "</body>"), encoding="utf-8")
    dom = browser.dump_dom(page.as_uri() + "#" + query, (390, 844))
    found = re.search(r'data-result="([^"]*)"', dom)
    assert found, "the harness didn't run"
    address, names = json.loads(unescape(found.group(1)))
    return address, names


def swapped(cho: str, song_key: str | None) -> Version:
    """A version in dorian that plays a chord instead of the first one offered something else, keeps a swap for
    another mode, and plays its first readable chord's second shape."""
    key, sheet = viewer_key(cho, song_key), parse_sheet(cho)
    chords = [parse_chord(name, strict=False) for name in sheet.chords]
    readable = [i for i, c in enumerate(chords) if c is not None]
    i = next(i for i in readable if alternatives(map_chord(chords[i], key, "dorian"), Key(key.tonic, "dorian")))
    other = alternatives(map_chord(chords[i], key, "dorian"), Key(key.tonic, "dorian"))[1]
    return Version(t=-3, mode="dorian", capo=3, at={readable[0]: 1},
                   alt={"dorian": {i: (other.root, other.suffix, other.bass)}, "lydian": {0: (0, "6/9.x", 4)}})


VERSIONS = (Version(t=3), Version(t=-3, capo=0), Version(mode="dorian"), Version(t=-3, mode="mixolydian", capo=3),
            Version(t=3, mode="phrygian", capo=0))


@in_chromium
@pytest.mark.parametrize(("cho", "key"), [(LEGEND, "Em"), (LEGEND, None), (UG, None), (ODD, None)],
                         ids=["legend-em", "legend", "ug", "odd"])
def test_python_and_the_viewer_name_every_chord_alike(cho, key, tmp_path):
    capo = parse_sheet(cho).capo or 0
    for v in (*VERSIONS, swapped(cho, key)):
        address, names = shown(cho, key, version_query(v), tmp_path)
        assert names == played(applied(cho, v, key)), v
        # the viewer keeps the version in its address as Python writes it (a capo on the sheet's own fret is none)
        kept = dataclasses.replace(v, capo=None if v.capo == capo else v.capo)
        assert address == "#" + version_query(kept), v
