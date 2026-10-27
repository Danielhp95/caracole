"""caracole.viewer.harpfit: the harp a harmonica tab's page starts on, with the record first (the song's chord sheet),
then the tab's words, harptabs.com's key, the song's key, a C harp; each with where it came from."""

from __future__ import annotations

from caracole.viewer import harp
from caracole.viewer.harpfit import MIN_NOTES, Fit, choose, pitch, record_fit, words
from caracole.viewer.harptab import parse

LINES = ("made up words for row one", "made up words for row two", "made up words for row three",
         "made up words for row four", "made up words for row five")


def sung(lyric: str, holes: tuple[str, ...]) -> str:
    """A row of ``holes``, one over each word of ``lyric``, then the lyric."""
    starts = [i for i, ch in enumerate(lyric) if ch != " " and (i == 0 or lyric[i - 1] == " ")]
    line = [" "] * (len(lyric) + 4)
    for at, hole in zip(starts, holes):
        line[at:at + len(hole)] = hole
    return "".join(line).rstrip() + "\n" + lyric + "\n"


def a_tab(rows: int = 4, *, before: str = "") -> str:
    """A tab of ``rows`` sung rows, each blowing C E G C E G on a C harp (holes 4 5 6 7 8 9)."""
    return before + "\n".join(sung(LINES[n], ("4", "5", "6", "7", "8", "9")) for n in range(rows))


def a_sheet(chord: str = "D", *, key: str = "D", capo: int = 0, lines: tuple[str, ...] = LINES) -> str:
    """A ChordPro sheet, as caracole writes one, playing ``chord`` under each line."""
    return ("{title: Synthetic}\n{artist: Placeholder Band}\n" + f"{{key: {key}}}\n"
            + (f"{{capo: {capo}}}\n" if capo else "") + "".join(f"[{chord}]{line}\n" for line in lines))


def test_the_harp_that_puts_the_tabs_notes_on_the_records_chords():
    # C E G on a C harp under a D chord: on a D harp the same holes blow D F# A, the chord itself.
    fits = record_fit(parse(a_tab()), a_sheet("D"))
    assert fits[0] == Fit(2, 1.0, 24)
    assert len(fits) == 12 and fits[1].share < 1.0
    chosen = choose(parse(a_tab()), cho=a_sheet("D"), page_key="C")
    assert (chosen.harp, chosen.why, chosen.page) == (2, "record", 0)


def test_the_chord_as_it_sounds_with_the_capo():
    # C shapes with the capo on 2 sound D: a D harp still
    assert record_fit(parse(a_tab()), a_sheet("C", key="C", capo=2))[0] == Fit(2, 1.0, 24)


def test_a_line_matched_word_by_word_though_it_reads_a_little_differently():
    sheet = a_sheet("D", lines=tuple(line.replace("made up", "made-up") for line in LINES))
    assert record_fit(parse(a_tab()), sheet)[0].harp == 2


def test_too_few_notes_counted_and_the_tabs_words_name_the_harp():
    small = parse(a_tab(3, before="We play it, so I use an A harp\n\n"))
    assert 3 * 6 < MIN_NOTES
    chosen = choose(small, cho=a_sheet("D"), page_key="C")
    assert (chosen.harp, chosen.why, chosen.named) == (9, "tab", 9)
    assert chosen.fits[0] == Fit(2, 1.0, 18)  # counted, too few to say


def test_then_harptabs_coms_key_then_the_songs_key_then_a_c_harp():
    elsewhere = a_sheet("G", key="G", lines=("other words than the tab", "and more of them here"))
    assert choose(parse(a_tab()), cho=elsewhere, page_key="Bb").why == "page"
    assert choose(parse(a_tab()), cho=elsewhere, page_key="Bb").harp == 10
    by_key = choose(parse(a_tab()), cho=elsewhere)
    assert (by_key.harp, by_key.why, by_key.tonic) == (7, "song", 7)  # G major: a G harp, the 1st position
    alone = choose(parse(a_tab()))
    assert (alone.harp, alone.why, alone.tonic, alone.fits) == (0, "usual", None, ())


def test_the_key_the_song_sounds_in_names_the_position():
    chosen = choose(parse(a_tab()), cho=a_sheet("D", key="Bm"))
    assert chosen.tonic == 11
    assert harp.position_text(chosen.tonic, chosen.harp) == "4th position, aeolian"
    with_capo = choose(parse(a_tab()), cho=a_sheet("C", key="Am", capo=2))  # Am shapes, capo 2: B minor
    assert with_capo.tonic == 11


def test_a_sheets_key_named_by_its_letter_alone_over_minor_chords_is_minor_for_the_harp_too():
    # UG's Hotel California: {key: A}, capo 2, Am E7 G D F C Dm E. The song sounds B minor: an A harp in the 3rd
    # position, a D harp in the 4th, never a B harp in the 1st.
    lines = ("other words than the tab", "and more of them here", "a third line of them", "and a fourth")
    pairs = (("Am", "E7"), ("G", "D"), ("F", "C"), ("Dm", "E"))
    cho = "{title: Hotel}\n{artist: Placeholder Band}\n{key: A}\n{capo: 2}\n" + "".join(
        f"[{a}]{line} [{b}]and on\n" for (a, b), line in zip(pairs, lines))
    for key, source in ((None, None), ("A minor", "tab")):  # the sheet's own, and as keys.py now reads UG's "A"
        chosen = choose(parse(a_tab()), cho=cho, key=key, key_source=source)
        assert (chosen.harp, chosen.why, chosen.tonic) == (9, "song", 11), key
        assert harp.position_text(chosen.tonic, chosen.harp) == "3rd position, dorian"


def test_the_songs_own_key_wins_over_the_sheets():
    chosen = choose(parse(a_tab()), cho=a_sheet("D", key="D"), key="Bm", key_source="chords")
    assert chosen.tonic == 11


def test_a_tab_shown_as_written_has_no_fit():
    chosen = choose(parse("(3)tue (3)te (3)te\n"), cho=a_sheet("D"), page_key="E")
    assert (chosen.why, chosen.fits) == ("page", ())


def test_words_as_the_fit_compares_them():
    assert words("On a dark des-ert high-way, (background)") == ["on", "a", "dark", "desert", "highway"]
    assert words("I'm sure you’ve") == ["i'm", "sure", "you've"]


def test_a_keys_name_as_a_pitch_class():
    assert [pitch(k) for k in ("C", "Bb", "A#", "F#", "E♭", " G ")] == [0, 10, 10, 6, 3, 7]
    assert pitch(None) is None and pitch("H") is None and pitch("") is None
