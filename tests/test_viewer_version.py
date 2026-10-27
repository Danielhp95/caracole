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
# A chord legend after the song's first section, as to_chordpro writes "[ch]Am[/ch] x02210": each fingering a mark.
LEGEND_LATER = ("{title: T}\n{artist: A}\n{key: Am}\n{comment: Verse}\n[Am]Una canció[C]n de [G]prueba\n\n"
                "{comment: Chords}\n[Am] [*x02210]\n[C] [*x32010]\n\n{comment: Chorus}\n[F]Otra [C]vez\n")


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


def test_a_chord_legends_lines_stay_as_written_in_any_version():
    # A legend's line gives the tab's shapes by the names the tab gives them: moved, "[Bm] [*x02210]" would name
    # Am's shape Bm. It stays as written, as the viewer shows it, wherever the song is played.
    legend = ["[Am] [*x02210]", "[C] [*x32010]"]
    swapped_am = Version(t=2, alt={"aeolian": {0: (9, "m7", None)}})
    for v in (Version(t=2), Version(mode="ionian"), Version(capo=3), swapped_am):
        out = applied(LEGEND_LATER, v).splitlines()
        assert out[out.index("{comment: Chords}") + 1:][:2] == legend, v
    assert "[Bm]Una canció[D]n de [A]prueba" in applied(LEGEND_LATER, Version(t=2))  # the song moves
    assert "[Em7] [*(022033)]" in applied(LEGEND, Version(t=3), "Em").splitlines()  # a legend in the notes too


def test_a_minor_major_seventh_keeps_its_seventh_however_it_is_spelled():
    # Am(maj7) in A major is Amaj7: spelled "AmMaj7" it is the same chord, never a plain Am that loses it
    for spelled in ("Am(maj7)", "AmMaj7", "AminMaj7"):
        cho = f"{{title: T}}\n{{artist: A}}\n{{key: Am}}\n[Am]la [{spelled}]le [Am7]li [D]lo\n"
        assert played(applied(cho, Version(mode="ionian"))) == ["A", "Amaj7", "Amaj7", "D"], spelled


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


def test_where_a_songbook_plays_a_version_says_nothing_of_a_capo_it_plays_without():
    # a songbook's set list: "G Dorian", never "G Dorian, capo 0"; an export's name keeps it (version_label)
    assert version.played_label(Version(mode="dorian", capo=0), Key(7, "ionian"), 0) == "G Dorian"
    assert version.played_label(Version(t=-1, mode="ionian"), Key(1, "ionian"), None) == "C Major"
    assert version.played_label(Version(capo=0), Key(4, "aeolian"), 2) == "F# Minor"  # the sheet's capo taken off
    assert version.played_label(Version(t=2, capo=0), None, 3) == "Transposed +2"
    assert version.played_label(Version(), None, None) == "As written"
    # a capo it plays with is said, as an export's name says it
    assert version.played_label(Version(), Key(7, "ionian"), 2) == "G Major, capo 2"
    assert version.played_label(Version(t=3, capo=3), Key(7, "ionian"), 2) == "A Major, capo 3"
    assert version.played_label(Version(), None, 3) == "As written, capo 3"
    assert version.played_label(Version(t=-4, capo=1), None, None) == "Transposed -4, capo 1"
    for v, key, capo in ((Version(mode="dorian", capo=0), Key(7, "ionian"), 0), (Version(t=2), Key(0, "ionian"), 3),
                         (Version(t=2, capo=0), None, 3), (Version(), None, 3)):
        label = version_label(v, key, capo)
        assert version.played_label(v, key, capo) == label.removesuffix(", capo 0"), label


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
            Version(t=3, mode="phrygian", capo=0),
            # on an instrument: the piano's chords named as they sound, the capo folded in; the ukulele's capo kept
            Version(t=3, inst="piano"), Version(mode="dorian", capo=3, inst="piano"),
            Version(t=-3, capo=0, inst="ukulele"))


@in_chromium
@pytest.mark.parametrize(("cho", "key"),
                         [(LEGEND, "Em"), (LEGEND, None), (UG, None), (ODD, None), (LEGEND_LATER, None)],
                         ids=["legend-em", "legend", "ug", "odd", "legend-later"])
def test_python_and_the_viewer_name_every_chord_alike(cho, key, tmp_path):
    capo = parse_sheet(cho).capo or 0
    for v in (*VERSIONS, swapped(cho, key)):
        address, names = shown(cho, key, version_query(v), tmp_path)
        assert names == played(applied(cho, v, key)), v
        # the viewer keeps the version in its address as Python writes it (a capo on the sheet's own fret is none)
        kept = dataclasses.replace(v, capo=None if v.capo == capo else v.capo)
        assert address == "#" + version_query(kept), v


# --- a version kept by its key ([version], "Make this my version") ------------------------------------

IN_A_MINOR = "{title: T}\n{artist: A}\n{key: Am}\n[Am]una [F]can[C]ción [G]más\n"
IN_D_MINOR_CAPO_3 = "{title: T}\n{artist: A}\n{key: Dm}\n{capo: 3}\n[Dm]otra [Bb]le[F]tra [C]más\n"  # a 4th up
IN_C_MAJOR = IN_A_MINOR.replace("{key: Am}", "{key: C}")  # its chords, as a tabber who reads them in C names them
NO_KEY = "{title: T}\n{artist: A}\n[N.C.]la [Hm]lo\n"  # no chord caracole can read: no key


def kept_on(entry: str, cho: str) -> Version:
    """Where the ``[version]`` entry plays the sheet ``cho``, its key and capo as its viewer reads them."""
    return version.in_key(version.key_version(entry), cho, key=viewer_key(cho), capo_sheet=parse_sheet(cho).capo)


def entry_of(v: Version, cho: str) -> str | None:
    """The ``[version]`` entry Make this my version writes for ``v`` on the sheet ``cho``."""
    return version.version_entry(v, cho, key=viewer_key(cho), capo_sheet=parse_sheet(cho).capo)


def sheet_of(chords: list[str]) -> str:
    """A sheet of these chords, naming no key: its viewer estimates one from them."""
    return "{title: T}\n{artist: A}\n" + " ".join(f"[{c}]la" for c in chords) + "\n"


def test_my_version_is_kept_as_the_key_it_plays_in_its_mode_and_its_capo():
    g_dorian = Version(t=-2, mode="dorian")
    # The key as the sheet's chords read it (G minor, from an A minor sheet), the mode chosen, the capo: never a t
    assert entry_of(g_dorian, IN_A_MINOR) == "key=Gm&mode=dorian&capo=0"
    assert version.key_version("key=Gm&mode=dorian&capo=0") == version.KeyVersion(Key(7, "aeolian"), "dorian", 0)
    # On its own sheet it is the version it was made of; on a sheet a fourth up, with a capo, it is the same key
    assert kept_on("key=Gm&mode=dorian&capo=0", IN_A_MINOR) == Version(t=-2, mode="dorian", capo=0)
    moved = kept_on("key=Gm&mode=dorian&capo=0", IN_D_MINOR_CAPO_3)
    assert moved == Version(t=2, mode="dorian", capo=0)
    assert played(applied(IN_D_MINOR_CAPO_3, moved)) == ["Gm", "Edim", "Bb", "F"]
    assert played(applied(IN_A_MINOR, g_dorian)) == ["Gm", "Edim", "Bb", "F"]
    assert version_label(moved, viewer_key(IN_D_MINOR_CAPO_3), 3) == "G Dorian, capo 0"
    # The sheet's own mode is no mode chosen, even named: the version plays in whichever its sheet is in
    assert entry_of(Version(t=-2), IN_A_MINOR) == "key=Gm&capo=0"
    assert entry_of(Version(t=-2, mode="aeolian"), IN_A_MINOR) == "key=Gm&capo=0"
    assert kept_on("key=Gm&capo=0", IN_A_MINOR) == Version(t=-2, capo=0)
    assert entry_of(Version(t=1, capo=2), IN_D_MINOR_CAPO_3) == "key=Em&capo=2"  # F# minor sounds
    assert entry_of(Version(), IN_D_MINOR_CAPO_3) == "key=Dm&capo=3"
    assert entry_of(Version(t=2), IN_C_MAJOR) == "key=D&capo=0"
    assert entry_of(Version(mode="aeolian"), IN_C_MAJOR) == "key=C&mode=aeolian&capo=0"


def test_a_sheet_whose_key_reads_as_the_relative_one_plays_my_versions_chords():
    # Two tabs of one song, its notes alike: one reads its chords in C major, the other in A minor. The version is
    # the key its chords are in, so the other plays the chords it played, as a t= did
    one, two = sheet_of(["C", "G", "Am", "F", "C"]), sheet_of(["Am", "F", "C", "G", "Am"])
    assert (viewer_key(one), viewer_key(two)) == (Key(0, "ionian"), Key(9, "aeolian"))
    entry = entry_of(Version(t=2), one)
    assert entry == "key=D&capo=0"
    assert kept_on(entry, two) == Version(t=2, capo=0)
    assert played(applied(two, kept_on(entry, two))) == ["Bm", "G", "D", "A", "Bm"]
    # A tab naming its key: B minor, from an A minor sheet, on one that names C major for the same chords
    entry = entry_of(Version(t=2), IN_A_MINOR)
    assert entry == "key=Bm&capo=0"
    assert played(applied(IN_C_MAJOR, kept_on(entry, IN_C_MAJOR))) == ["Bm", "G", "D", "A"]
    # A mode chosen plays its chords there too: G dorian's, which the viewer names by the sheet's tonic
    placed = kept_on(entry_of(Version(t=-2, mode="dorian"), IN_A_MINOR), IN_C_MAJOR)
    assert played(applied(IN_C_MAJOR, placed)) == ["Gm", "Edim", "Bb", "F"]
    assert version_label(placed, viewer_key(IN_C_MAJOR), None) == "Bb Lydian, capo 0"  # G dorian's notes
    # and a major sheet played minor, on a sheet that reads its chords in A minor
    entry = entry_of(Version(mode="aeolian"), IN_C_MAJOR)
    assert played(applied(IN_C_MAJOR, Version(mode="aeolian"))) == ["Ab", "Fm", "Cm", "Gm"]
    assert played(applied(IN_A_MINOR, kept_on(entry, IN_A_MINOR))) == ["Ab", "Fm", "Cm", "Gm"]


def test_a_sheet_tagged_in_the_parallel_key_plays_my_versions_chords():
    # A tab of the A minor song that names its key A (as a key read from audio can): its chords are A minor's, so
    # it is read from its own tonic, as a t= did, never as A major's notes (F# minor's, a fourth off)
    tagged_a = IN_A_MINOR.replace("{key: Am}", "{key: A}")
    assert viewer_key(tagged_a) == Key(9, "ionian")
    for entry, chords in (("key=Bm&capo=0", ["Bm", "G", "D", "A"]), ("key=Gm&capo=0", ["Gm", "Eb", "Bb", "F"]),
                          ("key=Am&capo=0", ["Am", "F", "C", "G"])):
        assert played(applied(tagged_a, kept_on(entry, tagged_a))) == chords, entry
    assert kept_on("key=Bm&capo=0", tagged_a) == Version(t=2, capo=0)
    # a mode chosen moves it as the t= with that mode did
    assert kept_on("key=Gm&mode=dorian&capo=0", tagged_a) == Version(t=-2, mode="dorian", capo=0)
    # and a C major song's tab tagged C minor
    tagged_cm = IN_C_MAJOR.replace("{key: C}", "{key: Cm}")
    assert played(applied(tagged_cm, kept_on(entry_of(Version(t=2), IN_C_MAJOR), tagged_cm))) == ["Bm", "G", "D", "A"]
    # A sheet whose chords are its key's is read in that key's notes, whatever mode the version's key is in
    assert played(applied(IN_C_MAJOR, kept_on("key=Bm&capo=0", IN_C_MAJOR))) == ["Bm", "G", "D", "A"]


def as_kept(v: Version) -> Version:
    """``v`` as its entry keeps it, with no capo of its own: the capo where the entry puts it (the sheet's, 0 here),
    and the swaps of the mode it plays in alone."""
    return dataclasses.replace(v, capo=0, alt={v.mode: v.alt[v.mode]})


def gm_define(cho: str) -> str:
    return next(d for d in directives(cho, "define") if d.startswith("Gm "))


def test_my_versions_swaps_and_shapes_are_kept_for_the_chords_they_were_chosen_for():
    fmaj7 = next(a for a in alternatives(parse_chord("G"), Key(9, "dorian")) if a.suffix == "maj7")
    mine = Version(t=-2, mode="dorian", at={0: 2}, alt={"dorian": {3: (fmaj7.root, fmaj7.suffix, fmaj7.bass)},
                                                         "lydian": {1: (5, "maj7", None)}})
    assert played(applied(IN_A_MINOR, mine)) == ["Gm", "Edim", "Bb", "Fmaj7"]
    # each by the chord as the version names it: Fmaj7 for its F; Gm's third shape by its frets from the nut;
    # only its own mode's swaps
    entry = entry_of(mine, IN_A_MINOR)
    assert entry == "key=Gm&mode=dorian&capo=0&alt=F.Fmaj7&at=Gm.x-x-5-7-8-6"
    assert kept_on(entry, IN_A_MINOR) == as_kept(mine)
    # A sheet in another key plays them on the chords it names so there, wherever they are
    moved = kept_on(entry, IN_D_MINOR_CAPO_3)
    out = applied(IN_D_MINOR_CAPO_3, moved)
    assert played(out) == ["Gm", "Edim", "Bb", "Fmaj7"]
    assert gm_define(out) == gm_define(applied(IN_A_MINOR, mine)) == "Gm base-fret 5 frets x x 1 3 4 2 fingers 0 0 1 3 4 2"
    assert moved.at == {0: 2}
    # A sheet without those chords takes none of them; frets that are no shape of its chord are none either
    other = "{title: T}\n{artist: A}\n{key: Am}\n[Am]la [Dm]lo [E7]li\n"
    assert kept_on(entry, other).alt == {} and kept_on(entry, other).at == {0: 2}
    assert kept_on("key=Gm&mode=dorian&capo=0&at=Gm.1-1-1-1-1-1,Bb.6-8-8-7-6-6", IN_A_MINOR).at == {2: 2}
    assert played(applied(other, kept_on(entry, other))) == ["Gm", "C", "D7"]


def test_a_shape_kept_is_the_one_its_frets_name_wherever_a_new_sheet_lists_it():
    # Gm's third shape on a sheet that gives none: a sheet in its place gives Gm shapes of its own, which its
    # viewer lists first. The shape kept is the same fingering, found where it is now, never the third of that list
    mine = Version(t=-2, at={0: 2})
    entry = entry_of(mine, IN_A_MINOR)
    assert entry == "key=Gm&capo=0&at=Gm.x-x-5-7-8-6"
    its_own = ("{title: T}\n{artist: A}\n{key: Gm}\n"
               "{define: Gm base-fret 10 frets x 1 3 3 2 1 fingers 0 1 3 4 2 1}\n"
               "{define: Gm base-fret 1 frets x x 0 3 3 3 fingers 0 0 0 1 1 1}\n"
               "[Gm]otra [Eb]le[Bb]tra [F]más\n")
    moved = kept_on(entry, its_own)
    assert moved.at != {0: 2} and gm_define(applied(its_own, moved)) == gm_define(applied(IN_A_MINOR, mine))
    # Frets no shape of the new sheet's Gm has are none
    assert kept_on("key=Gm&capo=0&at=Gm.x-x-x-3-3-3", its_own).at == {}


def test_a_sheet_with_no_key_plays_my_version_as_written():
    assert kept_on("key=Gm&mode=dorian&capo=0", NO_KEY) == Version()
    # and on one, there's no key to keep: none (render.py writes the version as an address naming its t)
    assert entry_of(Version(t=2, capo=1), NO_KEY) is None
    assert entry_of(Version(), NO_KEY) is None


def test_an_entry_without_a_key_is_a_move_and_one_that_cant_be_read_says_why():
    assert version.key_version("t=2&mode=dorian&capo=0") is None and version.key_version("") is None
    assert version.key_version("#key=F#m&mode=dorian&capo=2") == version.KeyVersion(Key(6, "aeolian"), "dorian", 2)
    assert version.key_version("key=Bb") == version.KeyVersion(Key(10, "ionian"))  # its capo the sheet's
    assert version.key_version("key=A dorian&capo=0") == version.KeyVersion(Key(9, "dorian"), None, 0)
    for bad, why in (("key=H", "key must be a key"), ("key=g", "key must be a key"), ("key=", "key must be a key"),
                     ("key=Gmin", "key must be a key"), ("key=G dorien", "key must be a key"),
                     ("key=G&mode=dorien", "mode must be one of"),
                     ("key=G&capo=12", "capo must be a fret"), ("key=G&capo=two", "capo must be a fret"),
                     ("key=G&t=2", "not both")):
        with pytest.raises(ValueError, match=why):
            version.key_version(bad)
    # what it can't read of its swaps and shapes is dropped, as the viewer drops it from its address
    kept = version.key_version("key=G&alt=F.Fmaj7,F,Hm.Gm,F.x,a.b.c"
                               "&at=Gm.x-x-5-7-8-6,3.1,Hm.x-0-2-2-1-0,Gm.2,Gm.x-x-x-x-x-x,Gm.1-2-3,Bb")
    assert (kept.alt, kept.at) == ((("F", "Fmaj7"),), (("Gm", (None, None, 5, 7, 8, 6)),))


def test_an_entry_round_trips_with_any_chords_name():
    kept = version.KeyVersion(Key(6, "aeolian"), "dorian", 0, alt=(("C#7", "C#7(b9)"),),
                              at=(("F#m", (None, 4, 4, 6, 7, 5)), ("C6.9", (None, 3, 2, 2, 3, 3)),
                                  ("A,B", (5, 7, 7, 6, 5, 5)), ("D&=%", (None, None, 0, 2, 3, 2))))
    query = kept.query()
    assert query == ("key=F#m&mode=dorian&capo=0&alt=C#7.C#7(b9)&at=F#m.x-4-4-6-7-5,C6%2E9.x-3-2-2-3-3,"
                     "A%2CB.5-7-7-6-5-5,D%26%3D%25.x-x-0-2-3-2")
    assert version.key_version(query) == kept
    # a key in a mode a tab names, as it names it
    assert version.KeyVersion(Key(10, "dorian")).query() == "key=Bb dorian"
    assert version.key_version("key=Bb dorian") == version.KeyVersion(Key(10, "dorian"))


# --- on another instrument ---------------------------------------------------------------------------

def test_a_version_names_its_instrument_in_its_address_as_the_viewer_does():
    v = Version(t=2, capo=0, at={1: 1}, inst="ukulele")
    assert version_query(v) == "t=2&capo=0&at=1.1&inst=ukulele"  # last, as the viewer's save() keeps it
    assert version_from_query(version_query(v)) == v and hash(version_from_query(version_query(v))) == hash(v)
    assert version_from_query("inst=piano") == Version(inst="piano")
    # the harmonica and the winds, which a PDF prints before the viewer draws them
    assert {version_from_query(f"inst={i}").inst for i in ("harmonica", "flute", "recorder")} == {
        "harmonica", "flute", "recorder"}
    # the guitar is none, and so is an instrument caracole hasn't got
    assert version_from_query("inst=guitar") == Version() and version_from_query("inst=banjo") == Version()
    assert Version(inst="piano") != Version()
    assert version.instrument_ids()[0] == "guitar" and "piano" in version.instrument_ids()


def test_an_instrument_with_no_capo_is_named_by_the_key_it_sounds_in():
    g_capo_2 = Key(7, "ionian")
    assert version_label(Version(inst="piano"), g_capo_2, 2) == "A Major, piano"
    # a capo moves the shapes, never the sound (F shapes, capo 4, sound A): the harmonica plays A all the same
    assert version_label(Version(capo=4), g_capo_2, 2) == "F Major, capo 4"
    assert version_label(Version(capo=4, inst="harmonica"), g_capo_2, 2) == "A Major, harmonica"
    assert version_label(Version(inst="ukulele"), g_capo_2, 2) == "G Major, capo 2, ukulele"
    assert version_label(Version(inst="ukulele-low-g"), g_capo_2, 2) == "G Major, capo 2, low-G ukulele"
    assert version.played_label(Version(capo=0, inst="baritone"), g_capo_2, 2) == "A Major, baritone ukulele"
    assert version.played_label(Version(inst="flute"), g_capo_2, 2) == "A Major, flute"
    # a sheet with no key: how far it sounds from the shapes as written
    assert version_label(Version(inst="piano"), None, 3) == "Transposed +3, piano"
    assert version_label(Version(t=-3, capo=0, inst="recorder"), None, 3) == "As written, recorder"
    # its key line: the key it sounds in, no capo; the guitar keeps its own
    assert version.played_key(Version(inst="piano"), g_capo_2, 2) == (Key(9, "ionian"), 0)
    assert version.played_key(Version(inst="ukulele"), g_capo_2, 2) == (g_capo_2, 2)


def test_a_ukuleles_version_defines_its_four_strings_shapes():
    from caracole.viewer.instruments import BARITONE, UKULELE, chord_shapes

    for inst, at in ((UKULELE, {}), (BARITONE, {}), (UKULELE, {0: 1})):
        out = applied(UG, Version(at=at, inst=inst.id))
        assert played(out) == played(applied(UG, Version())), inst  # the same chords: a ukulele takes the capo
        defines = directives(out, "define")
        assert len(defines) == len(set(played(out)))
        for name in set(played(out)):
            shapes = chord_shapes(inst, parse_chord(name), 0, shapes_of(parse_sheet(UG)))
            n = at.get(parse_sheet(UG).chords.index(name), 0) if name in parse_sheet(UG).chords else 0
            assert define_of(name, shapes[n]) in defines, (inst, name)
            assert len(define_of(name, shapes[n]).split("frets ")[1].split(" fingers")[0].split()) == 4
    assert directives(applied(UG, Version(inst="ukulele")), "capo") == ["2"]


def test_a_pianos_version_names_the_chords_as_they_sound_and_defines_their_keys():
    from caracole.viewer.instruments import PIANO, chord_shapes

    out = applied(UG, Version(inst="piano"))  # G shapes, capo 2: the piano plays A
    assert played(out)[:4] == ["A", "E", "F#m", "D"] and "G/B" not in played(out) and "A/C#" in played(out)
    assert directives(out, "key") == ["A"] and directives(out, "capo") == []
    defines = directives(out, "define")
    assert len(defines) == len(set(played(out)))
    first = chord_shapes(PIANO, parse_chord("A/C#"), 0)[0]  # [bass, *right hand], MIDI notes
    assert f"A/C# keys {' '.join(str(n - (first[0] - 4)) for n in first)}" in defines  # C# 4 above A
    assert "A keys 0 12 16 19" in defines  # A2, then A3 C#4 E4
    # a chosen inversion is its define
    a = parse_sheet(UG).chords.index("G")
    assert "A keys 0 16 19 24" in directives(applied(UG, Version(at={a: 1}, inst="piano")), "define")
    assert version.define_keys([48, 60, 64, 67], 0) == [0, 12, 16, 19]
    assert version.define_keys([52, 60, 64, 67], 0) == [4, 12, 16, 19]  # C/E: E lowest, four above C


def test_the_harmonica_and_the_winds_define_no_shapes():
    for inst in ("harmonica", "flute", "recorder"):
        out = applied(UG, Version(inst=inst))
        assert directives(out, "define") == [] and directives(out, "capo") == [], inst
        assert played(out)[:4] == ["A", "E", "F#m", "D"], inst


def test_a_setting_plays_the_song_on_its_instrument():
    shapes, capo = viewer_key(UG), 2  # G shapes, capo 2: sounds A
    own = Version(t=1, at={0: 1})
    on = version.in_setting
    # the instrument alone: the own version on it, its shapes chosen gone (they were the guitar's)
    assert on(own, version.Setting(instrument="ukulele"), shapes, capo) == Version(t=1, inst="ukulele")
    # on an instrument with no capo the key is the key it sounds in: placed with no capo
    piano = on(own, version.Setting(key="C", instrument="piano"), shapes, capo)
    assert piano.capo == 0 and version.played_key(piano, shapes, capo) == (Key(0, "ionian"), 0)
    # a setting on the guitar takes the song off its own version's instrument
    assert on(Version(inst="piano"), version.Setting(instrument="guitar"), shapes, capo) == Version()
    assert on(Version(inst="piano"), version.Setting(key="G"), shapes, capo).inst == "piano"
    assert on(Version(inst="piano"), version.Setting(key="G"), None, None) == Version(inst="piano")
    assert version.setting_problem(instrument="banjo").startswith("instrument must be one of guitar, ukulele")
    assert version.setting_problem(instrument="harmonica") is None


def test_my_version_keeps_its_instrument_and_the_capo_the_guitar_plays_at():
    from caracole.viewer.instruments import UKULELE, chord_shapes
    from caracole.viewer.voicings import frets_from_nut

    assert entry_of(Version(t=-2, inst="piano"), IN_A_MINOR) == "key=Gm&capo=0&inst=piano"
    assert entry_of(Version(inst="piano"), IN_D_MINOR_CAPO_3) == "key=Dm&capo=3&inst=piano"  # the guitar's capo
    assert kept_on("key=Dm&capo=3&inst=piano", IN_D_MINOR_CAPO_3) == Version(capo=3, inst="piano")
    assert version.key_version("key=Dm&capo=3&inst=piano").label() == "D Minor, piano"
    assert version.key_version("key=Dm&capo=3&inst=ukulele").label() == "D Minor, capo 3, ukulele"
    # a ukulele's chosen shape is kept by its four strings' frets, and found again on a sheet in another key
    am = parse_sheet(IN_A_MINOR).chords.index("Am")
    second = chord_shapes(UKULELE, parse_chord("Gm"), 0)[1]
    entry = entry_of(Version(t=-2, at={am: 1}, inst="ukulele"), IN_A_MINOR)
    assert entry == f"key=Gm&capo=0&at=Gm.{'-'.join(map(str, frets_from_nut(second)))}&inst=ukulele"
    assert kept_on(entry, IN_D_MINOR_CAPO_3) == Version(t=2, capo=0, at={0: 1}, inst="ukulele")
    assert kept_on(entry, NO_KEY) == Version(inst="ukulele")
    # a shape of six strings is none on a ukulele, and none is kept on the piano
    assert version.key_version("key=G&at=G.3-2-0-0-0-3&inst=ukulele").at == ()
    assert version.key_version("key=G&at=G.0-2-3-2&inst=piano").at == ()
    with pytest.raises(ValueError, match="instrument must be one of"):
        version.key_version("key=G&inst=banjo")
