"""caracole.viewer.theory: chord names, keys, modes and the alternatives the sheet viewer offers."""

from __future__ import annotations

import pytest

from caracole.viewer.theory import (
    FLATS,
    QUALITIES,
    SCALES,
    SHARPS,
    Chord,
    Key,
    alternatives,
    capo_hints,
    estimate_key,
    key_name,
    map_chord,
    parse_chord,
    parse_key,
    sounding,
    spelling,
)


def chords(*names: str) -> list[Chord]:
    return [parse_chord(n) for n in names]


def named(chord: Chord, key: Key | None = None) -> str:
    names = spelling(key)
    bass = "" if chord.bass is None else "/" + names[chord.bass]
    return names[chord.root] + chord.suffix + bass

# --- reading chord names --------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "root", "quality", "bass"),
    [
        ("G", 7, "", None),
        ("Am", 9, "m", None),
        ("Am7", 9, "m7", None),
        ("F#m7b5", 6, "m7b5", None),
        ("Bbmaj7", 10, "maj7", None),
        ("Db", 1, "", None),
        ("E7sus4", 4, "7sus4", None),
        ("G/B", 7, "", 11),
        ("Am7/G", 9, "m7", 7),
        ("Dsus2/F#", 2, "sus2", 6),
        ("C♯m", 1, "m", None),
        ("B♭", 10, "", None),
    ],
)
def test_a_chord_name_gives_its_root_quality_and_bass(text, root, quality, bass):
    chord = parse_chord(text)
    assert (chord.root, chord.quality, chord.bass) == (root, quality, bass)


@pytest.mark.parametrize(
    ("text", "quality"),
    [
        ("CM7", "maj7"),
        ("CΔ7", "maj7"),
        ("CΔ", "maj7"),
        ("C7M", "maj7"),
        ("Cma7", "maj7"),
        ("Cmin", "m"),
        ("Cmi7", "m7"),
        ("C-7", "m7"),
        ("C-", "m"),
        ("C°", "dim"),
        ("Co7", "dim7"),
        ("Cø", "m7b5"),
        ("Cø7", "m7b5"),
        ("Cm7(b5)", "m7b5"),
        ("C+", "aug"),
        ("C(add9)", "add9"),
        ("Cadd2", "add9"),
        ("Cm(add9)", "madd9"),
        ("Cm(maj7)", "mmaj7"),
        ("CmM7", "mmaj7"),
        ("Csus", "sus4"),
        ("C4", "sus4"),
        ("C2", "sus2"),
        ("C6/9", "69"),
        ("C69", "69"),
        ("C7(#9)", "7#9"),
        ("C7-9", "7b9"),
        ("C7+5", "aug7"),
        ("C7#5", "aug7"),
        ("CM", ""),
        ("Cmaj", ""),
    ],
)
def test_spellings_of_a_quality_read_alike(text, quality):
    assert parse_chord(text).quality == quality


def test_six_nine_is_not_a_slash_chord():
    assert parse_chord("C6/9").bass is None


def test_the_suffix_is_kept_as_written_for_display():
    assert parse_chord("CM7").shown == "M7"
    assert parse_chord("Am7/G").shown == "m7"


@pytest.mark.parametrize("quality", sorted(QUALITIES))
def test_a_made_up_chords_name_reads_back_as_the_same_chord(quality):
    # G with a flat fifth written "Gb5" reads as a G-flat power chord: the name must say G.
    for names in (SHARPS, FLATS):
        for root in range(12):
            name = names[root] + Chord(root, quality).suffix
            back = parse_chord(name)
            assert back is not None and (back.root, back.quality) == (root, quality), name


def test_a_flat_five_is_written_in_brackets():
    assert named(Chord(7, "b5")) == "G(b5)"
    assert named(Chord(7, "7b5")) == "G7b5"


@pytest.mark.parametrize(
    ("text", "intervals"),
    [
        ("C", {0, 4, 7}),
        ("Cm", {0, 3, 7}),
        ("C7", {0, 4, 7, 10}),
        ("C7#9", {0, 3, 4, 7, 10}),
        ("Cmaj7#11", {0, 4, 6, 7, 11}),
        ("Cm11", {0, 2, 3, 5, 7, 10}),
        ("C13", {0, 2, 4, 7, 9, 10}),
        ("C5", {0, 7}),
        ("Cadd11", {0, 4, 5, 7}),
        ("Cm9b5", {0, 2, 3, 6, 10}),
    ],
)
def test_a_chord_knows_its_intervals(text, intervals):
    assert parse_chord(text).intervals == frozenset(intervals)


def test_a_quality_outside_the_table_keeps_its_name_and_intervals():
    chord = parse_chord("Cmaj7#11")
    assert chord.quality == "maj7#11"
    assert chord.pitch_classes == frozenset({0, 4, 6, 7, 11})


def test_the_bass_counts_among_the_pitch_classes():
    assert parse_chord("Am7/G").pitch_classes == frozenset({9, 0, 4, 7})
    assert parse_chord("D/F#").pitch_classes == frozenset({2, 6, 9})


@pytest.mark.parametrize("text", ["", "N.C.", "x2", "H", "Hm", "(x4)", "Cfoo", "C/H", "%", "|", "C7zz"])
def test_what_is_no_chord_is_none(text):
    assert parse_chord(text) is None


def test_chords_compare_by_sound_and_spelling():
    assert parse_chord("CM7") == Chord(0, "maj7", shown="M7")
    assert parse_chord("CM7") != parse_chord("Cmaj7")  # shown differently
    assert parse_chord("CM7").pitch_classes == parse_chord("Cmaj7").pitch_classes


@pytest.mark.parametrize(
    ("text", "intervals"),
    [
        ("C7#13", {0, 4, 7, 10}),  # a sharp thirteenth sounds as the flat seventh
        ("C7(#13)", {0, 4, 7, 10}),
        ("E7+13", {0, 4, 7, 10}),  # "+13" is "#13"
        ("Am7b11", {0, 3, 4, 7, 10}),  # a flat eleventh sounds as the major third
        ("Bb7-11", {0, 4, 7, 10}),
    ],
)
def test_odd_alterations_on_real_sheets_are_read_as_they_sound(text, intervals):
    assert parse_chord(text).intervals == frozenset(intervals)
    assert parse_chord(text, strict=False).intervals == frozenset(intervals)


@pytest.mark.parametrize(
    "alteration",
    ["b5", "#5", "b9", "#9", "b11", "#11", "b13", "#13", "add2", "add4", "add6", "add9", "add11",
     "add13", "no3", "no5"],
)
def test_every_alteration_a_suffix_may_hold_is_read(alteration):
    for base in ("C", "Cm", "C7", "Cm7", "Cmaj7", "Csus4"):
        assert parse_chord(base + alteration, strict=False) is not None, base + alteration


def test_a_lenient_read_keeps_the_root_of_a_suffix_it_doesnt_know():
    chord = parse_chord("Cfoo/E", strict=False)
    assert (chord.root, chord.bass, chord.shown, chord.intervals) == (0, 4, "foo", frozenset({0, 4, 7}))
    assert parse_chord("Bbmfoo", strict=False).intervals == frozenset({0, 3, 7})
    assert parse_chord("Am7", strict=False) == parse_chord("Am7")
    assert parse_chord("N.C.", strict=False) is None
    assert parse_chord("C/H", strict=False) is None


# --- spelling notes in a key ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "names"),
    [
        (Key(0, "ionian"), "C Db D Eb E F F# G Ab A Bb B"),
        (Key(7, "ionian"), "C C# D Eb E F F# G Ab A Bb B"),
        (Key(5, "ionian"), "C Db D Eb E F Gb G Ab A Bb B"),
        (Key(4, "ionian"), "C C# D D# E F F# G G# A A# B"),
        (Key(1, "ionian"), "C Db D Eb E F Gb G Ab A Bb B"),
        (Key(6, "ionian"), "C C# D D# E F F# G G# A A# B"),
        (Key(9, "aeolian"), "C C# D Eb E F F# G G# A Bb B"),
        (Key(2, "aeolian"), "C C# D Eb E F F# G Ab A Bb B"),
        (Key(2, "dorian"), "C C# D Eb E F F# G Ab A Bb B"),
        (Key(3, "aeolian"), "C C# D D# E F F# G G# A A# B"),
        (None, "C C# D Eb E F F# G Ab A Bb B"),
    ],
)
def test_notes_are_spelled_as_the_key_writes_them(key, names):
    assert spelling(key) == names.split()


@pytest.mark.parametrize(
    ("key", "name"),
    [
        (Key(0, "ionian"), "C"),
        (Key(9, "aeolian"), "Am"),
        (Key(3, "aeolian"), "D#m"),
        (Key(10, "aeolian"), "Bbm"),
        (Key(1, "ionian"), "Db"),
        (Key(6, "ionian"), "F#"),
        (Key(1, "aeolian"), "C#m"),
        (Key(2, "dorian"), "D dorian"),
        (Key(4, "phrygian"), "E phrygian"),
        (Key(10, "mixolydian"), "Bb mixolydian"),
    ],
)
def test_a_key_is_named_like_a_chord_sheet_names_it(key, name):
    assert key_name(key) == name


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("C", Key(0, "ionian")),
        ("Am", Key(9, "aeolian")),
        ("F#m", Key(6, "aeolian")),
        ("Bb", Key(10, "ionian")),
        ("Ebm", Key(3, "aeolian")),
        ("C♯m", Key(1, "aeolian")),
        ("C minor", Key(0, "aeolian")),
        ("c Minor", Key(0, "aeolian")),
        ("Cmin", Key(0, "aeolian")),
        ("C min", Key(0, "aeolian")),
        ("Gb major", Key(6, "ionian")),
        ("Cmaj", Key(0, "ionian")),
        ("A dorian", Key(9, "dorian")),
        ("D Mixolydian", Key(2, "mixolydian")),
        ("E phrygian", Key(4, "phrygian")),
        ("F lydian", Key(5, "lydian")),
        ("B locrian", Key(11, "locrian")),
        ("C ionian", Key(0, "ionian")),
        ("A aeolian", Key(9, "aeolian")),
        (" G ", Key(7, "ionian")),
    ],
)
def test_a_key_is_read_from_how_tabs_and_tags_write_it(text, key):
    assert parse_key(text) == key


@pytest.mark.parametrize(
    "text", ["", "soda stereo|de musica ligera", "Cm7", "H", "Am/C", "key", "C dorian minor", "X", None, 5]
)
def test_what_is_no_key_is_none(text):
    assert parse_key(text) is None


# --- guessing the key from the chords ------------------------------------------------------------

LONG_MINOR = (
    "Am F C G Am F C G Am F C G Am F C G/B E7 Dm7 Em7 Fmaj7 Gsus4 G C G Am F C G C G Am Am7/G "
    "Fadd9 Dm E F G Em Am Bb F/A Dm E7sus4 E7 Am F C G Am"
)


@pytest.mark.parametrize(
    ("progression", "key"),
    [
        ("G D Em C", Key(7, "ionian")),
        ("Am F C G", Key(9, "aeolian")),
        ("C G Am F", Key(0, "ionian")),
        ("Em C G D", Key(4, "aeolian")),
        ("E A B7 E", Key(4, "ionian")),
        ("Am Dm E7 Am", Key(9, "aeolian")),
        ("Dm Bb F C", Key(2, "aeolian")),
        ("F C Dm Bb", Key(5, "ionian")),
        ("Bm G D A", Key(11, "aeolian")),
        ("D A/C# Bm G", Key(2, "ionian")),
        (LONG_MINOR, Key(9, "aeolian")),
        # a tab that starts on the tonic and ends on an outro chord: the start counts as much
        ("G D Em C G D Em C C G/B Am F C G D C", Key(7, "ionian")),
    ],
)
def test_the_key_is_guessed_from_the_chords(progression, key):
    assert estimate_key(chords(*progression.split())) == key


def test_no_chords_no_key():
    assert estimate_key([]) is None


# --- changing mode ----------------------------------------------------------------------------

C_MINOR, C_MAJOR = Key(0, "aeolian"), Key(0, "ionian")


@pytest.mark.parametrize(
    ("chord", "key", "mode", "becomes"),
    [
        ("Cm", C_MINOR, "ionian", "C"),
        ("Ab", C_MINOR, "ionian", "Am"),
        ("Bb", C_MINOR, "ionian", "Bdim"),
        ("Eb", C_MINOR, "ionian", "Em"),
        ("Fm7", C_MINOR, "ionian", "Fmaj7"),
        ("Bb7", C_MINOR, "ionian", "Bm7b5"),
        ("Cm/Eb", C_MINOR, "ionian", "C/E"),
        ("G", C_MINOR, "ionian", "G"),  # the raised seventh stays where it is
        ("C", C_MAJOR, "aeolian", "Cm"),
        ("Am", C_MAJOR, "aeolian", "Ab"),
        ("Dm", C_MAJOR, "aeolian", "Ddim"),
        ("G7", C_MAJOR, "aeolian", "Gm7"),
        ("G", C_MAJOR, "mixolydian", "Gm"),
        ("Bdim", C_MAJOR, "mixolydian", "Bb"),
        ("F", Key(9, "aeolian"), "dorian", "F#dim"),
        ("E7", Key(9, "aeolian"), "dorian", "E7"),
        ("E7", Key(9, "aeolian"), "phrygian", "E7b5"),
        ("G", C_MINOR, "phrygian", "G(b5)"),  # never "Gb5", a G-flat power chord
        ("Cmaj7#11", C_MAJOR, "dorian", "Cm7"),  # no such chord: the mode's own seventh chord
    ],
)
def test_a_mode_change_moves_each_note_to_the_same_degree_of_the_new_mode(chord, key, mode, becomes):
    target = Key(key.tonic, mode)
    assert named(map_chord(parse_chord(chord), key, mode), target) == becomes


def test_a_chord_the_mode_change_leaves_alone_keeps_its_spelling():
    chord = parse_chord("GM7")
    assert map_chord(chord, C_MAJOR, "lydian") == chord
    assert map_chord(chord, C_MAJOR, "ionian") == chord


# --- alternatives in the key ---------------------------------------------------------------------


def scale_of(key: Key) -> set[int]:
    return {(key.tonic + i) % 12 for i in SCALES[key.mode]}


@pytest.mark.parametrize(
    ("chord", "key"),
    [("C", C_MAJOR), ("G7", C_MAJOR), ("Am", C_MAJOR), ("E7", Key(9, "aeolian")), ("Bb", C_MAJOR),
     ("F#m7b5", Key(7, "ionian")), ("D/F#", Key(7, "ionian")), ("Cfoo", C_MAJOR)],
)
def test_alternatives_stay_in_the_key_and_share_notes_with_the_chord(chord, key):
    original = parse_chord(chord, strict=False)
    alts = alternatives(original, key)
    assert 3 <= len(alts) <= 8
    allowed = scale_of(key) | original.pitch_classes
    for alt in alts:
        assert alt.pitch_classes <= allowed, named(alt, key)
        assert len(alt.pitch_classes & original.pitch_classes) >= 2, named(alt, key)
        assert alt.pitch_classes != original.pitch_classes or alt.bass != original.bass
        assert alt.shown is None
    assert len({sound(a) for a in alts}) == len(alts)  # none sound alike


def sound(chord: Chord) -> tuple:
    """What a chord sounds like: its notes and its lowest one. G#dim7 and Ddim7 sound alike."""
    if chord.quality in ("dim7", "aug"):  # symmetric: any of its notes may be called the root
        return (chord.pitch_classes, None)
    return (chord.pitch_classes, chord.bass if chord.bass is not None else chord.root)


def test_the_tonic_chord_gets_its_colours_then_its_relatives():
    names = [named(a, C_MAJOR) for a in alternatives(parse_chord("C"), C_MAJOR)]
    assert names[0] == "Cmaj7"
    assert {"Cmaj7", "Cadd9", "Csus2", "C6", "Am", "Em"} <= set(names)
    assert not {"C7", "Cm"} & set(names)
    assert names.index("Am") < names.index("Em")  # a third below first: I's usual stand-in is vi


def test_a_dominant_in_minor_keeps_its_leading_note():
    names = {named(a, Key(9, "aeolian")) for a in alternatives(parse_chord("E7"), Key(9, "aeolian"))}
    assert {"E7sus4", "Em7", "G#dim7"} <= names


def test_a_chord_gets_an_inversion_and_a_slash_chord_its_root_position():
    assert "C/E" in [named(a) for a in alternatives(parse_chord("C"), C_MAJOR)]
    assert "D" in [named(a) for a in alternatives(parse_chord("D/F#"), Key(7, "ionian"))]


# --- capo hints -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "hints"),
    [
        (Key(10, "ionian"), [(1, "A"), (3, "G")]),
        (Key(3, "ionian"), [(1, "D"), (3, "C")]),
        (Key(1, "ionian"), [(1, "C"), (4, "A")]),
        (Key(6, "aeolian"), [(2, "Em"), (4, "Dm")]),
        (Key(11, "aeolian"), [(2, "Am")]),
        (Key(0, "ionian"), []),
        (Key(9, "aeolian"), []),
        (Key(2, "dorian"), []),  # C major's notes: open chords already
        (Key(3, "dorian"), [(1, "D dorian")]),
    ],
)
def test_a_capo_hint_offers_open_chord_shapes_for_an_awkward_key(key, hints):
    assert [(capo, key_name(shapes)) for capo, shapes in capo_hints(key)] == hints


@pytest.mark.parametrize(
    ("shapes", "capo", "hints"),
    [
        # G shapes with capo 2 (A), transposed down two: F shapes, sounding G
        (Key(5, "ionian"), 2, [(0, "G"), (3, "E")]),
        # down one: Gb shapes, sounding Ab
        (Key(6, "ionian"), 2, [(1, "G"), (4, "E")]),
        # up three: Bb shapes, sounding C
        (Key(10, "ionian"), 2, [(0, "C"), (3, "A")]),
        (Key(7, "ionian"), 2, []),  # G shapes: open already
        (Key(10, "ionian"), 0, [(1, "A"), (3, "G")]),  # no capo on the sheet: as before
    ],
)
def test_a_capo_hint_may_lower_or_take_off_the_sheets_capo(shapes, capo, hints):
    # The frets are where the capo goes (0: none), from the key the song sounds in.
    assert [(fret, key_name(k)) for fret, k in capo_hints(shapes, capo=capo)] == hints


@pytest.mark.parametrize(
    ("shapes", "capo", "sounds"),
    [
        (Key(4, "aeolian"), 2, "F#m"),  # Em shapes with capo 2, as Wonderwall is played
        (Key(7, "ionian"), 0, "G"),  # no capo: the shapes' key
        (Key(9, "ionian"), 3, "C"),
        (Key(2, "dorian"), 11, "C# dorian"),
    ],
)
def test_a_capo_raises_the_key_the_song_sounds_in(shapes, capo, sounds):
    assert key_name(sounding(shapes, capo)) == sounds
