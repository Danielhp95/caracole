"""The pure half of auto-chords: snapping, LRC parsing and sheet layout."""

from tabarr.autochords.merge import ChordSegment, build_sheet, parse_lrc, snap_to_beats

# 120 BPM: a beat every 0.5 s, so a 4/4 bar lasts 2 s.
BEATS = [i * 0.5 for i in range(121)]


def seg(start: float, end: float, label: str) -> ChordSegment:
    return ChordSegment(start, end, label)


def test_snap_moves_changes_to_nearest_beat():
    segs = [seg(0.1, 2.1, "C"), seg(2.1, 3.9, "G"), seg(3.9, 6.2, "Am")]
    assert snap_to_beats(segs, BEATS) == [
        seg(0.0, 2.0, "C"),
        seg(2.0, 4.0, "G"),
        seg(4.0, 6.0, "Am"),
    ]


def test_snap_drops_no_chord_and_blips_then_merges_repeats():
    segs = [
        seg(0.0, 0.9, "N"),
        seg(0.9, 3.0, "C"),
        seg(3.0, 3.2, "F"),  # shorter than a beat: both ends land on 3.0
        seg(3.2, 5.0, "C"),
        seg(5.0, 7.0, "N"),
        seg(7.0, 9.0, "G"),
    ]
    assert snap_to_beats(segs, BEATS) == [seg(1.0, 5.0, "C"), seg(7.0, 9.0, "G")]


def test_snap_keeps_a_chord_that_returns_after_a_long_no_chord():
    segs = [seg(0.0, 2.0, "C"), seg(2.0, 4.0, "N"), seg(4.0, 6.0, "C")]
    assert snap_to_beats(segs, BEATS) == [seg(0.0, 2.0, "C"), seg(4.0, 6.0, "C")]


def test_snap_fills_gaps_in_the_detected_beats():
    beats = [0.0, 0.5, 1.0, 1.5, 2.0, 6.0, 6.5, 7.0]  # nothing detected from 2 s to 6 s
    segs = [seg(0.0, 3.9, "C"), seg(3.9, 7.0, "G")]
    assert snap_to_beats(segs, beats) == [seg(0.0, 4.0, "C"), seg(4.0, 7.0, "G")]


def test_snap_extends_the_grid_past_the_last_beat():
    beats = [0.0, 0.5, 1.0, 1.5, 2.0]
    segs = [seg(0.0, 2.9, "C"), seg(2.9, 4.1, "G")]
    assert snap_to_beats(segs, beats) == [seg(0.0, 3.0, "C"), seg(3.0, 4.0, "G")]


def test_snap_tolerates_a_beat_detected_twice():
    beats = [0.0, 0.5, 0.56, 1.0, 1.5, 2.0]
    segs = [seg(0.0, 1.0, "C"), seg(1.0, 2.0, "G")]
    assert snap_to_beats(segs, beats) == [seg(0.0, 1.0, "C"), seg(1.0, 2.0, "G")]


def test_snap_without_beats_only_cleans():
    segs = [seg(0.0, 1.3, "N"), seg(1.3, 2.7, "C"), seg(2.7, 4.1, "C"), seg(4.1, 5.0, "G")]
    assert snap_to_beats(segs, []) == [seg(1.3, 4.1, "C"), seg(4.1, 5.0, "G")]


def test_parse_lrc():
    text = (
        "\ufeff[ar:Nobody]\n"
        "[ti:River Road]\n"
        "[length: 03:12]\n"
        "[offset:+500]\n"
        "[00:12.50]First line\n"
        "[00:10][01:02.250]Repeated line\n"
        "[00:15.00]\n"
        "[00:16.00] <00:16.20>Word <00:16.80>sync\n"
        "a line with no stamp\n"
    )
    assert parse_lrc(text) == [
        (9.5, "Repeated line"),
        (12.0, "First line"),
        (14.5, ""),
        (15.5, "Word sync"),
        (61.75, "Repeated line"),
    ]


def test_parse_lrc_negative_offset_and_colon_fractions():
    assert parse_lrc("[offset:-250]\n[00:01:50]One\n[1:05]Two\n") == [(1.75, "One"), (65.25, "Two")]


def test_build_sheet_places_chords_over_lyric_lines():
    synced = (
        "[00:08.00]Walking down the river road\n"
        "[00:12.00]Singing to the morning light\n"
        "[00:16.00]Nothing left to say\n"
    )
    segs = [
        seg(8.0, 10.0, "G"),
        seg(10.0, 12.0, "D"),
        seg(12.0, 16.0, "Em"),
        seg(16.0, 18.0, "C"),
        seg(18.0, 20.0, "G"),
    ]
    sheet = build_sheet(segs, title="River Road", artist="Nobody", synced=synced, beats=BEATS)
    # D starts halfway through the first line's 4 s: column 27 // 2 = 13.
    assert sheet == (
        "auto-generated, unverified\n"
        "Nobody - River Road\n"
        "\n"
        "[ch]G[/ch]            [ch]D[/ch]\n"
        "Walking down the river road\n"
        "[ch]Em[/ch]\n"
        "Singing to the morning light\n"
        "[ch]C[/ch]        [ch]G[/ch]\n"
        "Nothing left to say\n"
    )


def test_chords_on_a_short_line_never_touch():
    synced = "[00:08.00]Oh\n[00:12.00]Singing to the morning light\n"
    segs = [seg(8.0, 9.0, "G"), seg(9.0, 10.0, "D"), seg(10.0, 12.0, "Em")]
    sheet = build_sheet(segs, title="T", artist="A", synced=synced, beats=BEATS)
    assert sheet.splitlines()[3:5] == ["[ch]G[/ch] [ch]D[/ch] [ch]Em[/ch]", "Oh"]


def test_columns_count_characters_in_cjk_lines():
    # The ChordPro converter inserts a chord before the character at its column,
    # so a column is a character index, not a display width.
    synced = "[00:08.00]第一行歌词在这里\n[00:12.00]第二行歌词在这里\n"
    segs = [seg(8.0, 10.0, "G"), seg(10.0, 16.0, "D")]
    sheet = build_sheet(segs, title="斑马斑马", artist="宋冬野", synced=synced, beats=BEATS)
    assert sheet.splitlines()[3:5] == ["[ch]G[/ch]   [ch]D[/ch]", "第一行歌词在这里"]


def test_lrc_without_lyric_lines_falls_back_to_plain():
    sheet = build_sheet(
        [seg(0.0, 2.0, "G")],
        title="T",
        artist="A",
        synced="[ti:T]\n[00:05.00]\n",
        plain="La la\n",
        beats=BEATS,
    )
    assert sheet.splitlines()[3:] == ["[Chords]", "| [ch]G[/ch] |", "", "[Lyrics]", "La la"]


def test_no_chords_still_gives_the_lyrics():
    synced = "[00:08.00]Walking down the river road\n"
    assert build_sheet([], title="T", artist="A", synced=synced, beats=BEATS).splitlines()[3:] == [
        "Walking down the river road"
    ]
    assert build_sheet([seg(0.0, 9.0, "N")], title="T", artist="A", plain="La la\n").splitlines()[
        3:
    ] == [
        "[Lyrics]",
        "La la",
    ]


def test_change_just_before_a_line_starts_that_line():
    # The singer comes in 0.2 s after the downbeat where the chord changes.
    synced = "[00:08.20]Walking down the river road\n[00:12.20]Singing to the morning light\n"
    segs = [seg(8.0, 12.0, "G"), seg(12.0, 16.0, "Em")]
    sheet = build_sheet(segs, title="River Road", artist="Nobody", synced=synced, beats=BEATS)
    assert sheet.splitlines()[3:] == [
        "[ch]G[/ch]",
        "Walking down the river road",
        "[ch]Em[/ch]",
        "Singing to the morning light",
    ]


def test_instrumental_gap_gets_chord_line():
    # Lines last 4 s; after the fourth, 8 s (4 bars) of guitar before the voice returns.
    synced = (
        "[00:04.00]Line one of the verse\n"
        "[00:08.00]Line two of the verse\n"
        "[00:12.00]Line three of the verse\n"
        "[00:16.00]Line four of the verse\n"
        "[00:28.00]Back to singing again\n"
        "[00:32.00]And the very last line\n"
    )
    segs = [
        seg(4.0, 8.0, "G"),
        seg(8.0, 12.0, "D"),
        seg(12.0, 16.0, "Em"),
        seg(16.0, 20.0, "C"),
        seg(20.0, 22.0, "G"),
        seg(22.0, 24.0, "D"),
        seg(24.0, 26.0, "Em"),
        seg(26.0, 28.0, "C"),
        seg(28.0, 32.0, "G"),
        seg(32.0, 36.0, "D"),
    ]
    sheet = build_sheet(segs, title="Gap Song", artist="Nobody", synced=synced, beats=BEATS)
    assert sheet.splitlines()[3:] == [
        "[ch]G[/ch]",
        "Line one of the verse",
        "[ch]D[/ch]",
        "Line two of the verse",
        "[ch]Em[/ch]",
        "Line three of the verse",
        "[ch]C[/ch]",
        "Line four of the verse",
        "",
        "[Instrumental]",
        "| [ch]G[/ch] | [ch]D[/ch] | [ch]Em[/ch] | [ch]C[/ch] |",
        "",
        "[ch]G[/ch]",
        "Back to singing again",
        "[ch]D[/ch]",
        "And the very last line",
    ]


def test_first_line_shows_the_chord_already_sounding():
    # G starts under a bar before the voice: too short for an intro line of its own.
    synced = "[00:08.00]Walking down the river road\n[00:12.00]Singing to the morning light\n"
    segs = [seg(7.0, 10.0, "G"), seg(10.0, 16.0, "D")]
    sheet = build_sheet(segs, title="River Road", artist="Nobody", synced=synced, beats=BEATS)
    assert sheet.splitlines()[3:] == [
        "[ch]G[/ch]            [ch]D[/ch]",
        "Walking down the river road",
        "Singing to the morning light",
    ]


def test_line_after_a_break_shows_the_chord_already_sounding():
    synced = (
        "[00:04.00]Line one of the verse\n"
        "[00:08.00]Line two of the verse\n"
        "[00:12.00]Line three of the verse\n"
        "[00:16.00]Line four of the verse\n"
        "[00:28.00]Back to singing again\n"
        "[00:32.00]And the very last line\n"
    )
    segs = [
        seg(4.0, 8.0, "G"),
        seg(8.0, 12.0, "D"),
        seg(12.0, 16.0, "Em"),
        seg(16.0, 20.0, "C"),
        seg(20.0, 24.0, "G"),
        seg(24.0, 30.0, "D"),  # still ringing when the voice comes back at 28 s
        seg(30.0, 36.0, "G"),
    ]
    sheet = build_sheet(segs, title="Gap Song", artist="Nobody", synced=synced, beats=BEATS)
    lines = sheet.splitlines()
    assert lines[lines.index("[Instrumental]") :] == [
        "[Instrumental]",
        "| [ch]G[/ch] | [ch]G[/ch] | [ch]D[/ch] | [ch]D[/ch] |",
        "",
        "[ch]D[/ch]         [ch]G[/ch]",
        "Back to singing again",
        "And the very last line",
    ]


def test_empty_lrc_line_breaks_the_stanza():
    synced = "[00:04.00]Line one\n[00:08.00]Line two\n[00:11.00]\n[00:12.00]Line three\n[00:16.00]Line four\n"
    segs = [seg(4.0, 8.0, "G"), seg(8.0, 12.0, "D"), seg(12.0, 16.0, "Em"), seg(16.0, 20.0, "C")]
    sheet = build_sheet(segs, title="T", artist="A", synced=synced, beats=BEATS)
    assert sheet.splitlines()[3:] == [
        "[ch]G[/ch]",
        "Line one",
        "[ch]D[/ch]",
        "Line two",
        "",
        "[ch]Em[/ch]",
        "Line three",
        "[ch]C[/ch]",
        "Line four",
    ]


def test_empty_lrc_line_starts_the_instrumental():
    # The LRC marks the end of "Line two" at 10 s, before the usual 4 s are up.
    synced = "[00:04.00]Line one\n[00:08.00]Line two\n[00:10.00]\n[00:20.00]Line three\n[00:24.00]Line four\n"
    segs = [
        seg(4.0, 8.0, "G"),
        seg(8.0, 10.0, "D"),
        seg(10.0, 14.0, "Em"),
        seg(14.0, 20.0, "C"),
        seg(20.0, 24.0, "G"),
        seg(24.0, 28.0, "D"),
    ]
    sheet = build_sheet(segs, title="T", artist="A", synced=synced, beats=BEATS)
    lines = sheet.splitlines()
    assert lines[lines.index("Line two") - 1 :][:6] == [
        "[ch]D[/ch]",
        "Line two",
        "",
        "[Instrumental]",
        "| [ch]Em[/ch] | [ch]Em[/ch] | [ch]C[/ch] | [ch]C[/ch] |",
        "| [ch]C[/ch] |",
    ]


def test_intro_and_outro_get_chord_lines():
    synced = "[00:08.00]Walking down the river road\n[00:12.00]Singing to the morning light\n"
    segs = [
        seg(0.0, 4.0, "Am"),
        seg(4.0, 8.0, "F"),
        seg(8.0, 12.0, "G"),
        seg(12.0, 16.0, "C"),
        seg(16.0, 20.0, "Am"),
        seg(20.0, 24.0, "F"),
    ]
    sheet = build_sheet(segs, title="River Road", artist="Nobody", synced=synced, beats=BEATS)
    assert sheet.splitlines()[3:] == [
        "[Intro]",
        "| [ch]Am[/ch] | [ch]Am[/ch] | [ch]F[/ch] | [ch]F[/ch] |",
        "",
        "[ch]G[/ch]",
        "Walking down the river road",
        "[ch]C[/ch]",
        "Singing to the morning light",
        "",
        "[Outro]",
        "| [ch]Am[/ch] | [ch]Am[/ch] | [ch]F[/ch] | [ch]F[/ch] |",
    ]


def test_plain_lyrics_get_chord_chart_then_lyrics():
    # 斑马斑马 by 宋冬野 has only plain lyrics on LRCLIB. These lines are made up.
    plain = "第一行歌词在这里\n第二行歌词在这里\n\n第三行歌词在这里\n"
    progression = ["G", "D", "Em", "C", "Am", "F", "C", "G"]
    segs = [seg(2.0 * k, 2.0 * (k + 1), name) for k, name in enumerate(progression)]
    sheet = build_sheet(
        segs,
        title="斑马斑马",
        artist="宋冬野",
        plain=plain,
        beats=BEATS[:33],
        downbeats=[2.0 * k for k in range(9)],
    )
    assert sheet == (
        "auto-generated, unverified\n"
        "宋冬野 - 斑马斑马\n"
        "\n"
        "[Chords]\n"
        "| [ch]G[/ch] | [ch]D[/ch] | [ch]Em[/ch] | [ch]C[/ch] |\n"
        "| [ch]Am[/ch] | [ch]F[/ch] | [ch]C[/ch] | [ch]G[/ch] |\n"
        "\n"
        "[Lyrics]\n"
        "第一行歌词在这里\n"
        "第二行歌词在这里\n"
        "\n"
        "第三行歌词在这里\n"
    )


def test_repeated_chart_lines_are_collapsed():
    progression = ["G", "D", "Em", "C"] * 3 + ["Am", "F", "C", "G"]
    segs = [seg(2.0 * k, 2.0 * (k + 1), name) for k, name in enumerate(progression)]
    sheet = build_sheet(segs, title="Loop", artist="Nobody", beats=BEATS[:65])
    assert sheet.splitlines()[3:] == [
        "[Chords]",
        "| [ch]G[/ch] | [ch]D[/ch] | [ch]Em[/ch] | [ch]C[/ch] | x3",
        "| [ch]Am[/ch] | [ch]F[/ch] | [ch]C[/ch] | [ch]G[/ch] |",
    ]


def test_bars_without_downbeats_start_where_chords_change():
    # The song starts 1 s in, on the third beat of the grid.
    segs = [
        seg(0.0, 1.0, "N"),
        seg(1.0, 3.0, "G"),
        seg(3.0, 5.0, "D"),
        seg(5.0, 7.0, "Em"),
        seg(7.0, 9.0, "C"),
    ]
    sheet = build_sheet(segs, title="T", artist="A", beats=BEATS[:21])
    assert sheet.splitlines()[4] == "| [ch]G[/ch] | [ch]D[/ch] | [ch]Em[/ch] | [ch]C[/ch] |"


def test_chart_bars_follow_downbeats():
    # A waltz: three beats to the bar, so a bar lasts 1.5 s.
    segs = [seg(0.0, 1.5, "G"), seg(1.5, 3.0, "C"), seg(3.0, 4.5, "D"), seg(4.5, 6.0, "G")]
    sheet = build_sheet(
        segs, title="Waltz", artist="Nobody", beats=BEATS[:13], downbeats=[0.0, 1.5, 3.0, 4.5]
    )
    assert sheet.splitlines()[3:] == [
        "[Chords]",
        "| [ch]G[/ch] | [ch]C[/ch] | [ch]D[/ch] | [ch]G[/ch] |",
    ]


def test_a_missed_downbeat_is_filled_in():
    segs = [seg(0.0, 1.5, "G"), seg(1.5, 3.0, "C"), seg(3.0, 4.5, "D"), seg(4.5, 6.0, "G")]
    sheet = build_sheet(
        segs, title="Waltz", artist="Nobody", beats=BEATS[:13], downbeats=[0.0, 1.5, 4.5, 6.0]
    )
    assert sheet.splitlines()[4] == "| [ch]G[/ch] | [ch]C[/ch] | [ch]D[/ch] | [ch]G[/ch] |"


def test_bar_with_two_chords_shows_both():
    segs = [seg(0.0, 1.0, "G"), seg(1.0, 2.0, "D"), seg(2.0, 4.0, "Em")]
    sheet = build_sheet(segs, title="T", artist="A", beats=BEATS[:9])
    assert sheet.splitlines()[4] == "| [ch]G[/ch] [ch]D[/ch] | [ch]Em[/ch] |"


def test_bar_with_nothing_sounding_shows_no_chord():
    segs = [seg(0.0, 2.0, "G"), seg(2.0, 4.0, "N"), seg(4.0, 6.0, "D")]
    sheet = build_sheet(segs, title="T", artist="A", beats=BEATS[:13])
    assert sheet.splitlines()[4] == "| [ch]G[/ch] | [ch]N.C.[/ch] | [ch]D[/ch] |"


def test_a_spurious_downbeat_is_ignored():
    # A waltz with an extra downbeat detected one beat after the one at 4.5 s.
    progression = ["G", "C", "D", "G", "C", "G", "D", "G"]
    segs = [seg(1.5 * k, 1.5 * (k + 1), name) for k, name in enumerate(progression)]
    downbeats = sorted([1.5 * k for k in range(9)] + [5.0])
    sheet = build_sheet(segs, title="Waltz", artist="Nobody", beats=BEATS[:25], downbeats=downbeats)
    assert sheet.splitlines()[4:6] == [
        "| [ch]G[/ch] | [ch]C[/ch] | [ch]D[/ch] | [ch]G[/ch] |",
        "| [ch]C[/ch] | [ch]G[/ch] | [ch]D[/ch] | [ch]G[/ch] |",
    ]


def test_no_lyrics_gives_the_chart_only():
    segs = [seg(0.0, 2.0, "G"), seg(2.0, 4.0, "D")]
    sheet = build_sheet(segs, title="River Road", artist="Nobody", beats=BEATS[:9])
    assert sheet == (
        "auto-generated, unverified\nNobody - River Road\n\n[Chords]\n| [ch]G[/ch] | [ch]D[/ch] |\n"
    )
