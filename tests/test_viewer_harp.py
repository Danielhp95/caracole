"""caracole.viewer.harp: the 10-hole Richter harp, its positions, the chords it plays and the harps to pick
for a song, with the tables a viewer's data carries."""

from __future__ import annotations

import dataclasses

import pytest

from caracole.viewer import harp
from caracole.viewer.harmony_tables import SHIFTS, shifted
from caracole.viewer.harp import (
    BLOW,
    DRAW,
    HARP_KEYS,
    POSITIONS,
    HarpChoice,
    Playing,
    choices,
    harp_for,
    header_line,
    layout,
    ordinal,
    play,
    position_mode,
    position_of,
)
from caracole.viewer.theory import FLATS, MODES, SHARPS, Chord, Key, map_chord, parse_chord, spelling

C_HARP = 0
NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note(midi: int) -> str:
    return f"{NAMES[midi % 12]}{midi // 12 - 1}"


def ch(name: str):
    return parse_chord(name)


def chords(text: str):
    return [parse_chord(n) for n in text.split()]


# --- the Richter layout --------------------------------------------------------------------------


def test_a_c_harp_blows_its_triad_and_draws_the_rest_of_its_scale():
    c = layout(C_HARP)
    assert [note(n) for n in c.blow] == "C4 E4 G4 C5 E5 G5 C6 E6 G6 C7".split()
    assert [note(n) for n in c.draw] == "D4 G4 B4 D5 F5 A5 B5 D6 F6 A6".split()
    assert (BLOW, DRAW) == ((0, 4, 7, 12, 16, 19, 24, 28, 31, 36), (2, 7, 11, 14, 17, 21, 23, 26, 29, 33))


@pytest.mark.parametrize("harp_key", range(12))
def test_every_harp_key_is_the_c_harps_layout_moved_from_g3_up_to_f_sharp4(harp_key):
    one = layout(harp_key)
    low = 55 + (harp_key - 7) % 12  # the G harp is the lowest, hole 1 blowing G3; the F# harp the highest
    assert one.harp == harp_key and one.name == HARP_KEYS[harp_key]
    assert one.blow == tuple(low + n for n in BLOW) and one.draw == tuple(low + n for n in DRAW)
    assert 55 <= one.blow[0] <= 66


def test_harps_are_named_as_they_are_sold():
    assert HARP_KEYS == ("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
    assert note(layout(7).blow[0]) == "G3" and note(layout(6).blow[0]) == "F#4" and note(layout(0).blow[0]) == "C4"


def test_the_higher_reed_of_a_hole_bends_down_a_semitone_at_a_time_to_the_lower_one():
    c = layout(C_HARP)
    assert [len(b) for b in c.bends] == [1, 2, 3, 1, 0, 1, 0, 1, 1, 2]
    assert [note(n) for n in c.bends[2]] == ["A#4", "A4", "G#4"]  # draw 3: B bends to Bb, A, Ab
    assert [note(n) for n in c.bends[9]] == ["B6", "A#6"]  # blow 10: C bends to B, Bb
    assert c.bend_breath == ("draw",) * 6 + ("blow",) * 4


# --- positions ------------------------------------------------------------------------------------


def test_positions_are_numbered_round_the_circle_of_fifths_as_wikipedia_numbers_them():
    on_c = {p: (FLATS[(C_HARP + 7 * (p - 1)) % 12], position_mode(p)) for p in POSITIONS}
    assert on_c == {
        1: ("C", "ionian"), 2: ("G", "mixolydian"), 3: ("D", "dorian"), 4: ("A", "aeolian"),
        5: ("E", "phrygian"), 6: ("B", "locrian"), 7: ("Gb", None), 8: ("Db", None), 9: ("Ab", None),
        10: ("Eb", None), 11: ("Bb", None), 12: ("F", "lydian"),
    }
    assert [ordinal(p) for p in (1, 2, 3, 4, 5, 11, 12)] == ["1st", "2nd", "3rd", "4th", "5th", "11th", "12th"]


@pytest.mark.parametrize(("song", "position", "harp_key"), [
    ("G", 1, "G"),
    ("G", 2, "C"),  # cross harp: a fourth above the song
    ("A", 2, "D"),
    ("E", 2, "A"),
    ("F", 2, "Bb"),  # a blues in F takes a Bb harp
    ("D", 3, "C"),  # slant harp: a whole tone below the song
    ("A", 4, "C"),
    ("E", 5, "C"),
    ("F", 12, "C"),
    ("F#", 2, "B"),
    ("C#", 2, "F#"),
])
def test_the_harp_for_a_song_in_a_position(song, position, harp_key):
    tonic = SHARPS.index(song) if song in SHARPS else FLATS.index(song)
    assert HARP_KEYS[harp_for(tonic, position)] == harp_key
    assert position_of(tonic, harp_for(tonic, position)) == position


def test_each_harp_plays_a_song_in_exactly_one_position():
    for tonic in range(12):
        assert sorted(position_of(tonic, h) for h in range(12)) == list(POSITIONS)
        assert all(harp_for(tonic, position_of(tonic, h)) == h for h in range(12))


# --- the chords a harp plays ----------------------------------------------------------------------


@pytest.mark.parametrize(("chord", "text"), [
    ("C", "blow 1–3"),
    ("G", "draw 2–4"),  # Yerxa: holes 1–4, cleanest on 2–4
    ("G7", "draw 2–5"),
    ("G9", "draw 2–6"),
    ("Dm", "draw 4–6"),
    ("Dm6", "draw 4–7"),
    ("Bdim", "draw 3–5"),
    ("Bm7b5", "draw 3–6"),
    ("G/D", "draw 1–3"),  # the bass lowest where a run of holes starts on it
    ("C/E", "blow 2–4"),
    ("G/B", "draw 2–4"),  # no run starts on B: the chord from its root
])
def test_a_c_harp_plays_these_chords_whole_on_one_breath(chord, text):
    found = play(ch(chord), C_HARP)
    assert (found.kind, found.text(spelling(None))) == ("yes", text)


@pytest.mark.parametrize("chord", ["Am", "F", "Em", "E", "Gm", "Fmaj7", "Bb", "A7", "Gsus4", "Caug"])
def test_a_c_harp_has_no_such_chord(chord):
    found = play(ch(chord), C_HARP)
    assert (found.kind, found.breath, found.holes, found.played) == ("no", None, None, None)
    assert found.text(spelling(None)) == "not on this harp"


@pytest.mark.parametrize(("chord", "text"), [
    ("Cmaj7", "blow 1–3 (as C)"),
    ("C6", "blow 1–3 (as C)"),
    ("Cadd9", "blow 1–3 (as C)"),
    ("Dm7", "draw 4–6 (as Dm)"),
    ("Dm9", "draw 4–6 (as Dm)"),
    ("Bdim7", "draw 3–5 (as Bdim)"),
    ("C/D", "blow 1–3 (as C)"),  # a bass that is no note of the chord is left out
])
def test_a_chord_the_harp_lacks_whole_is_played_as_its_triad(chord, text):
    found = play(ch(chord), C_HARP)
    assert (found.kind, found.text(spelling(None))) == ("part", text)


@pytest.mark.parametrize("chord", ["D", "D7", "D9", "D6"])
def test_a_major_chord_the_harp_has_only_in_minor_is_a_minor_substitute(chord):
    found = play(ch(chord), C_HARP)
    assert (found.kind, found.text(spelling(None))) == ("minor", "draw 4–6 (as Dm, minor substitute)")
    assert found.played == Chord(2, "m")  # a chord caracole names: its quality as it writes it


def test_a_minor_chord_never_takes_the_major_one():
    assert play(ch("Gm"), C_HARP).kind == "no"  # G B D over a G minor chord clashes


def test_what_a_chord_plays_depends_only_on_where_it_is_from_the_harps_key():
    for harp_key in range(12):
        for name in ("C", "G7", "Dm", "D", "Cmaj7", "Am", "G/D", "C5", "Bm7b5", "Bdim7"):
            chord = ch(name)
            on_c = play(chord, C_HARP)
            assert play(shifted(chord, harp_key), harp_key) == dataclasses.replace(
                on_c, played=shifted(on_c.played, harp_key)), (harp_key, name)


def test_each_position_offers_the_chords_the_research_derived():
    # 1st offers I, V7 and ii, but no clean IV or vi; 2nd I7, IV and a minor v; 3rd i, IV and bVII.
    def kinds(song: str, names: str, position: int):
        tonic = SHARPS.index(song)
        return [play(ch(n), harp_for(tonic, position)).kind for n in names.split()]

    assert kinds("C", "C G7 Dm F Am", 1) == ["yes", "yes", "yes", "no", "no"]
    assert kinds("G", "G7 C D", 2) == ["yes", "yes", "minor"]
    assert kinds("D", "Dm G C", 3) == ["yes", "yes", "yes"]


# --- the harps for a song -------------------------------------------------------------------------


def names_of(found: list[HarpChoice]) -> list[tuple[str, int]]:
    return [(HARP_KEYS[c.harp], c.position) for c in found]


@pytest.mark.parametrize(("key", "progression", "harps"), [
    # A song in a major key: the 1st position, then the 2nd, whatever its chords (the owner's rule).
    (Key(7, "ionian"), "G C D", [("G", 1), ("C", 2)]),
    (Key(7, "ionian"), "G D Em C", [("G", 1), ("C", 2)]),
    (Key(7, "ionian"), "G7 C7 D7", [("G", 1), ("C", 2)]),
    (Key(0, "ionian"), "C G Am F", [("C", 1), ("F", 2)]),
    (Key(7, "ionian"), "G", [("G", 1), ("C", 2)]),
    # Any other mode by the chords each plays: Mixolydian's own position, the 2nd, plays its tonic too.
    (Key(7, "mixolydian"), "G", [("C", 2), ("G", 1)]),
    (Key(7, "mixolydian"), "G F C", [("C", 2), ("G", 1)]),
    # A minor song: 3rd, 4th and 5th; the 3rd plays the i chord (draw 4–6), so it leads.
    (Key(9, "aeolian"), "Am F C G", [("G", 3), ("F", 5), ("C", 4)]),
    (Key(9, "aeolian"), "Am Dm Em", [("G", 3), ("C", 4), ("F", 5)]),
    (Key(2, "dorian"), "Dm G", [("C", 3), ("F", 4), ("Bb", 5)]),
    (Key(4, "phrygian"), "Em F", [("D", 3), ("C", 5), ("G", 4)]),  # the i chord first, then its own
    # Lydian and Locrian take their own positions too, the 12th and the 6th, ranked as the others are.
    (Key(5, "lydian"), "F G", [("F", 1), ("Bb", 2), ("C", 12)]),
    (Key(11, "locrian"), "Bdim C", [("C", 6), ("G", 5), ("D", 4)]),  # ties by the nearest scale
])
def test_the_harps_for_a_song_by_its_mode_then_the_chords_they_play(key, progression, harps):
    assert names_of(choices(key, chords(progression))) == harps


def test_a_choice_says_what_it_plays():
    straight, cross = choices(Key(7, "ionian"), chords("G C D G"))
    assert (cross.position, cross.mode, cross.chords, cross.plays, cross.substitutes) == (2, "mixolydian", 3, 2, 1)
    assert (straight.position, straight.mode, straight.plays, straight.substitutes) == (1, "ionian", 2, 0)
    assert cross.fit == 3.5 and straight.fit == 3  # the tonic chord counts twice, a substitute half


@pytest.fixture
def fresh_choices():
    harp._choices.cache_clear()
    yield
    harp._choices.cache_clear()


def test_the_ranking_is_one_rule_in_one_place(monkeypatch, fresh_choices):
    assert names_of(choices(Key(0, "aeolian"), chords("Cm"))) == [("Bb", 3), ("Eb", 4), ("Ab", 5)]
    harp._choices.cache_clear()
    monkeypatch.setattr(harp, "ranking", lambda key, order, choice: (-choice.position,))
    assert names_of(choices(Key(0, "aeolian"), chords("Cm"))) == [("Ab", 5), ("Eb", 4), ("Bb", 3)]
    assert names_of(choices(Key(7, "ionian"), chords("G C D"))) == [("C", 2), ("G", 1)]


def test_unreadable_chords_and_repeats_count_once_or_not_at_all():
    assert choices(Key(7, "ionian"), [ch("G"), None, ch("C"), ch("C"), ch("CM7"), ch("Cmaj7")])[0].chords == 3


def test_the_harps_follow_the_transposition():
    progression = chords("G C D Em")
    first = choices(Key(7, "ionian"), progression)
    for s in SHIFTS:
        moved = choices(Key((7 + s) % 12, "ionian"), [shifted(c, s) for c in progression])
        assert [(c.position, (c.harp - s) % 12, c.fit) for c in moved] == [(c.position, c.harp, c.fit) for c in first]


# --- the header line ------------------------------------------------------------------------------


@pytest.mark.parametrize(("key", "progression", "line"), [
    (Key(7, "ionian"), "G C D", "Harmonica: G harp (1st position) · C harp (2nd)"),
    (Key(7, "mixolydian"), "G F C", "Harmonica: C harp (2nd position) · G harp (1st)"),
    (Key(9, "aeolian"), "Am F C G", "Harmonica: G harp (3rd position, dorian) · F harp (5th, phrygian) · "
                                    "C harp (4th, aeolian)"),
    (Key(1, "ionian"), "Db Gb Ab", "Harmonica: Db harp (1st position) · F# harp (2nd)"),
    (Key(5, "lydian"), "F G", "Harmonica: F harp (1st position) · Bb harp (2nd) · C harp (12th, lydian)"),
])
def test_the_header_line_names_each_harp_and_its_position(key, progression, line):
    assert header_line(key, chords(progression)) == line


# --- the tables a viewer's data carries -----------------------------------------------------------


IN_G = chords("G C D Em G/B D7 Cmaj7")


def mapped_of(key: Key, played) -> dict:
    return {mode: [map_chord(c, key, mode) for c in played] for mode in MODES}


def test_the_tables_hold_the_harps_for_every_mode_and_what_each_chord_plays_on_each():
    key = Key(7, "ionian")
    mapped = mapped_of(key, IN_G)
    alts = {mode: [[ch("Am")] for _ in IN_G] for mode in MODES}
    data = harp.tables(key, mapped, alts)
    assert data["harpKeys"] == list(HARP_KEYS)
    for mode in MODES:
        ranked = choices(Key(7, mode), mapped[mode])
        assert [h[:2] for h in data["harps"][mode]] == [[c.position, (c.harp - 7) % 12] for c in ranked]
        for i, chord in enumerate(mapped[mode]):
            form = data["harpForms"][data["harpChords"][mode][i]]
            assert len(form) == 12
            for offset in range(12):
                assert form[offset] == harp.entry(play(chord, (7 + offset) % 12))
        assert data["harpAlts"][mode] == [[_form(data, ch("Am"), 7)] for _ in IN_G]
    assert len(data["harpForms"]) == len({tuple(map(repr, f)) for f in data["harpForms"]})  # each form once


def _form(data: dict, chord, tonic: int) -> int:
    want = [harp.entry(play(chord, (tonic + o) % 12)) for o in range(12)]
    return data["harpForms"].index(want)


def test_an_entry_is_null_or_the_kind_the_breath_the_holes_and_the_chord_played():
    assert harp.entry(play(ch("G7"), C_HARP)) == ["yes", "draw", 2, 5]
    assert harp.entry(play(ch("Cmaj7"), C_HARP)) == ["part", "blow", 1, 3, ""]
    assert harp.entry(play(ch("D7"), C_HARP)) == ["minor", "draw", 4, 6, "m"]
    assert harp.entry(play(ch("Am"), C_HARP)) is None


def test_the_page_builds_the_header_line_and_the_chords_holes_on_every_transposition():
    """What the page does with the tables (a harp's name by its offset from the key shown, a played chord's name
    from the chord's root and the entry's suffix) gives harp.py's answers in every key."""
    key = Key(7, "ionian")
    mapped = mapped_of(key, IN_G)
    data = harp.tables(key, mapped)
    for mode in ("ionian", "aeolian", "mixolydian"):
        for s in SHIFTS:
            shown = Key((7 + s) % 12, mode)
            moved = [shifted(c, s) for c in mapped[mode]]
            line = "Harmonica: " + " · ".join(
                f"{data['harpKeys'][(7 + s + offset) % 12]} harp ({label})" for _, offset, label in data["harps"][mode])
            assert line == header_line(shown, moved)
            names = spelling(shown)
            for i, chord in enumerate(moved):
                for offset in range(12):
                    want = play(chord, (shown.tonic + offset) % 12)
                    got = data["harpForms"][data["harpChords"][mode][i]][offset]
                    assert harp.entry_text(got, names[chord.root]) == want.text(names)


def test_no_key_no_harps():
    assert harp.tables(None, {}) == {}


def test_each_harps_notes_for_the_sound_of_its_holes():
    assert harp.layouts() == [[list(layout(h).blow), list(layout(h).draw)] for h in range(12)]
    assert harp.layouts()[0] == [[60, 64, 67, 72, 76, 79, 84, 88, 91, 96], [62, 67, 71, 74, 77, 81, 83, 86, 89, 93]]


def test_answers_are_frozen_and_a_list_handed_out_is_a_copy():
    with pytest.raises(dataclasses.FrozenInstanceError):
        play(ch("C"), C_HARP).kind = "no"
    with pytest.raises(dataclasses.FrozenInstanceError):
        layout(C_HARP).harp = 2
    first = choices(Key(7, "ionian"), chords("G C D"))
    first.clear()
    assert choices(Key(7, "ionian"), chords("G C D"))
    assert isinstance(play(ch("C"), C_HARP), Playing)
