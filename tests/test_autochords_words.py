"""Sung spans, the guard, the lines and the LRC of a transcript (pure Python)."""

from caracole.autochords import merge
from caracole.autochords.words import Span, Word, guard, lines_of, sung_spans, to_lrc
from caracole.chordpro import display_columns


def test_frames_where_the_stem_is_near_the_mix_are_sung():
    mix = [-10.0] * 100
    stem = [-13.0 if 20 <= i < 60 else -40.0 for i in range(100)]
    assert sung_spans(stem, mix) == [Span(0.8, 3.2)]


def test_a_soft_line_11_db_under_the_mix_is_still_sung():
    # Measured (Task 14): the example's softest sung word needs the stem counted from 9 dB under the mix; the
    # threshold keeps 3 dB more, and the instrumentals kept a made-up word only from 26 dB.
    mix = [-10.0] * 100
    stem = [-21.0 if 20 <= i < 60 else -60.0 for i in range(100)]
    assert sung_spans(stem, mix) == [Span(0.8, 3.2)]


def test_bleed_without_a_voice_is_not_sung():
    mix = [-10.0] * 100
    assert sung_spans([-25.0] * 100, mix) == []


def test_frames_below_the_mix_floor_are_not_sung():
    mix = [-10.0] * 40 + [-70.0] * 40
    stem = [-12.0] * 40 + [-70.0] * 40
    assert sung_spans(stem, mix) == [Span(0.0, 2.2)]


def test_short_gaps_join_and_short_runs_drop():
    mix = [-10.0] * 200
    stem = [-60.0] * 200
    for i in list(range(10, 30)) + list(range(35, 55)):  # a 0.25 s gap joins
        stem[i] = -12.0
    for i in range(100, 105):  # 0.25 s: too short
        stem[i] = -12.0
    for i in list(range(150, 160)) + list(range(170, 180)):  # a 1.0 s gap does not join
        stem[i] = -12.0
    assert sung_spans(stem, mix) == [Span(0.3, 2.95), Span(7.3, 8.2), Span(8.3, 9.2)]


def test_words_outside_every_span_are_dropped_and_words_touching_one_kept():
    far = Word(0.0, 0.5, "作", False)
    near = Word(24.8, 25.2, "没", False)
    kept, dropped = guard([far, near], [Span(25.0, 30.0)])
    assert kept == [near]
    assert dropped == [far]


def test_a_word_within_the_slack_of_a_span_is_kept():
    kept, dropped = guard([Word(24.5, 24.8, "x", True)], [Span(25.0, 30.0)])
    assert (kept, dropped) == ([Word(24.5, 24.8, "x", True)], [])
    kept, dropped = guard([Word(24.4, 24.6, "x", True)], [Span(25.0, 30.0)])
    assert (kept, dropped) == ([], [Word(24.4, 24.6, "x", True)])


def test_with_no_spans_every_word_is_dropped():
    word = Word(1.0, 2.0, "a", False)
    assert guard([word], []) == ([], [word])


def test_a_line_breaks_at_a_breath_not_at_a_held_note():
    words = [
        Word(24.0, 24.4, "Hola", False),
        Word(24.5, 24.9, "El", True),
        Word(25.34, 25.6, "día", True),  # 0.44 s of silence: no break
        Word(26.2, 26.5, "nuestro", True),  # 0.6 s of silence: break
    ]
    assert [[w.text for w in line] for line in lines_of(words)] == [
        ["Hola", "El", "día"],
        ["nuestro"],
    ]


def test_a_short_line_does_not_break_at_a_breath():
    words = [Word(1.0, 1.2, "Hi", False), Word(2.0, 2.2, "you", True)]
    assert len(lines_of(words)) == 1


def _chain(*texts, segment_start_at=None, step=0.1):
    """Words back to back, each a space after the one before, except the first."""
    return [
        Word(i * step, i * step + 0.05, text, i > 0, segment_start=(i == segment_start_at))
        for i, text in enumerate(texts)
    ]


def test_a_segment_start_breaks_a_line_only_once_it_is_twelve_wide():
    narrow = _chain("abcde", "fghi", "next", segment_start_at=2)  # "abcde fghi" is 10 wide
    assert len(lines_of(narrow)) == 1
    wide = _chain("abcdef", "ghijkl", "next", segment_start_at=2)  # "abcdef ghijkl" is 13 wide
    assert [[w.text for w in line] for line in lines_of(wide)] == [["abcdef", "ghijkl"], ["next"]]


def test_punctuation_breaks_a_line_only_once_it_is_eighteen_wide():
    short = _chain("abcdefgh,", "ijkl", "next")  # 9 wide when the comma ends it
    assert len(lines_of(_chain("abcdefgh,", "next"))) == 1
    assert len(lines_of(short)) == 1
    long = _chain("abcdefghi", "jklmnopq,", "next")  # 19 wide
    assert [[w.text for w in line] for line in lines_of(long)] == [
        ["abcdefghi", "jklmnopq,"],
        ["next"],
    ]


def test_chinese_lines_count_two_columns_a_character_and_join_with_no_space():
    chars = "我" * 27
    words = [Word(i * 0.1, i * 0.1 + 0.05, c, False) for i, c in enumerate(chars)]
    lines = lines_of(words)
    assert [len(line) for line in lines] == [26, 1]
    lrc = to_lrc(lines)
    assert " " not in lrc.splitlines()[0].replace("] ", "", 1)


def test_lrc_marks_a_break_before_two_seconds_of_silence():
    lines = [
        [Word(1.0, 1.4, "Hi", False), Word(1.5, 2.0, "there", True)],
        [Word(5.0, 5.5, "Again", False)],
    ]
    assert (
        to_lrc(lines)
        == "[00:01.00] <00:01.00>Hi <00:01.50>there\n[00:02.00]\n[00:05.00] <00:05.00>Again\n"
    )


def test_no_break_line_before_less_than_two_seconds_of_silence():
    lines = [[Word(1.0, 2.0, "Hi", False)], [Word(3.9, 4.5, "Again", False)]]
    assert "\n[00:02.00]\n" not in to_lrc(lines)


def test_the_lrc_reads_back_through_merge():
    lines = [
        [Word(1.0, 1.4, "Hi", False), Word(1.5, 2.0, "there", True)],
        [Word(5.0, 5.5, "Aga", False), Word(5.5, 5.8, "in", False)],
    ]
    read = merge.parse_lrc_words(to_lrc(lines))
    assert [(line.time, line.text) for line in read] == [
        (1.0, "Hi there"),
        (2.0, ""),
        (5.0, "Again"),
    ]
    assert read[0].words == ((1.0, 0), (1.5, 3))
    assert read[2].words == ((5.0, 0), (5.5, 3))


def test_a_line_never_passes_fifty_two_columns():
    texts = ["abcdefghij"] * 12 + ["x" * 60, "tail"]
    words = [Word(i * 0.1, i * 0.1 + 0.05, t, i > 0) for i, t in enumerate(texts)]
    lines = lines_of(words)
    for line in lines:
        assert len(line) == 1 or display_columns(" ".join(w.text for w in line))[-1] <= 52
    assert [len(line) for line in lines] == [4, 4, 4, 1, 1]


def test_under_ten_seconds_sung_is_nothing_sung():
    from caracole.autochords.words import MIN_SUNG_S, sung_time, too_little_sung

    assert MIN_SUNG_S == 10.0
    assert sung_time([Span(0.0, 2.5), Span(10.0, 13.7)]) == 6.2
    assert too_little_sung([Span(0.0, 2.5), Span(10.0, 13.7)]) == "sung 6.2 s"
    assert too_little_sung([]) == "sung 0.0 s"
    assert too_little_sung([Span(0.0, 10.0)]) is None


def test_few_words_or_few_a_minute_is_nothing_sung():
    from caracole.autochords.words import MIN_WORDS, MIN_WORDS_A_MINUTE, too_few_words

    assert (MIN_WORDS, MIN_WORDS_A_MINUTE) == (8, 20.0)

    def words(n):
        return [Word(float(i), i + 0.5, "la", True) for i in range(n)]

    assert too_few_words(words(12), [Span(0.0, 100.0)]) == "12 words in 1:40 sung"  # 7 a minute
    assert too_few_words(words(7), [Span(0.0, 30.0)]) == "7 words in 0:30 sung"  # under 8
    assert too_few_words(words(5), [Span(0.0, 70.0)]) == "5 words in 1:10 sung"
    assert too_few_words(words(1), [Span(0.0, 30.0)]) == "1 word in 0:30 sung"
    assert too_few_words(words(43), [Span(0.0, 18.7)]) is None


def test_the_measured_songs_are_sung():
    from caracole.autochords.words import too_few_words, too_little_sung

    # (words kept, seconds sung): docs/superpowers/plans/2026-11-20-transcribed-lyrics-results.md
    for kept, sung in [(242, 116.2), (269, 206.7), (43, 18.7), (220, 150.0)]:
        spans = [Span(0.0, sung)]
        words = [Word(0.0, 0.1, "la", True)] * kept
        assert too_little_sung(spans) is None
        assert too_few_words(words, spans) is None
