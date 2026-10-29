"""Where LRCLIB's timed lyrics sit in audio of another length: align.py, on synthetic songs.

A song here is bars of chords at 120 BPM (a beat every 0.5 s, a bar every 2 s), and lyrics
timed against it as LRCLIB would: a line every two bars, a little after the bar starts. The
"audio" is that song with something more at one end, as the models would hear it: chord
segments, beats and downbeats.
"""

from __future__ import annotations

import pytest

from caracole.autochords.align import lyrics_offset, shifted_lrc
from caracole.autochords.merge import ChordSegment, LrcLine, parse_lrc, parse_lrc_words

BEAT = 0.5
BAR = 4 * BEAT
JITTER = (0.1, 0.25, 0.0, 0.15)  # a singer comes in a little after the bar, never quite the same

INTRO = ["Em", "C", "G", "D"]
VERSE = ["Em", "D", "C", "D"] * 2
CHORUS = ["C", "G", "D", "Em"] * 2
BRIDGE = ["Am", "C", "D", "D"] * 2
CHORUS_WORDS = ["We sail the cold north sea", "with lentils in the hold", "no meat upon our ships",
                "just carrots, brave and bold"]


def song_form() -> list[tuple[list[str], list[str]]]:
    """Sections as (chords a bar, lines sung, one every two bars)."""
    verse = iter(f"Verse line number {n}" for n in range(1, 13))
    return [
        (INTRO, []),
        (VERSE, [next(verse) for _ in range(4)]),
        (CHORUS, CHORUS_WORDS),
        (VERSE, [next(verse) for _ in range(4)]),
        (CHORUS, CHORUS_WORDS),
        (BRIDGE, [next(verse) for _ in range(4)]),
        (CHORUS, CHORUS_WORDS),
        (INTRO, []),
    ]


def build(form, *, before: float = 0.0, after: float = 0.0, lead: float = 0.0, tail: float = 2.0):
    """The lyrics (timed lines, and their length) and the audio (segments, beats, downbeats, length).

    ``lead`` seconds of the song's own silence come before its first bar, and ``tail`` after its
    last: the release LRCLIB timed. The audio adds ``before`` and ``after`` seconds of no chord
    (talk, silence) at its ends, where beat_this finds no beat.
    """
    lines: list[tuple[float, str]] = []
    segments: list[ChordSegment] = []
    bar = 0
    for chords, sung in form:
        for k, label in enumerate(chords):
            start = lead + (bar + k) * BAR
            segments.append(ChordSegment(start, start + BAR, label))
        for k, text in enumerate(sung):
            lines.append((round(lead + (bar + 2 * k) * BAR + JITTER[len(lines) % 4], 3), text))
        bar += len(chords)
    music_end = lead + bar * BAR
    lyrics_s = music_end + tail
    audio = [ChordSegment(s.start + before, s.end + before, s.label) for s in segments]
    if before:
        audio.insert(0, ChordSegment(0.0, before, "N"))
    if after:
        audio.append(ChordSegment(music_end + before, music_end + before + after, "N"))
    beats = [before + lead + k * BEAT for k in range(round(bar * BAR / BEAT) + 1)]
    return lines, lyrics_s, audio, beats, beats[::4], lyrics_s + before + after


def offset_of(form=None, **kw):
    lines, lyrics_s, segments, beats, downbeats, audio_s = build(form or song_form(), **kw)
    return lyrics_offset(lines, segments, beats, downbeats, audio_s=audio_s, lyrics_s=lyrics_s)


def test_a_spoken_intro_twelve_seconds_long_moves_the_lyrics_twelve_seconds_later():
    found = offset_of(before=12.0)
    assert found.offset == pytest.approx(12.0, abs=BEAT)


def test_a_talk_longer_than_the_grid_reaches_is_found_at_the_difference_in_lengths():
    assert offset_of(before=45.0).offset == pytest.approx(45.0, abs=BEAT)


def test_an_intro_of_silence_a_bar_and_a_half_long_is_found_by_where_the_bars_fall():
    # 3 s is no whole number of bars: unshifted, every line would start in the middle of a bar.
    assert offset_of(before=3.0).offset == pytest.approx(3.0, abs=BEAT)


def test_a_spoken_outro_keeps_the_lyrics_where_they_are():
    assert offset_of(after=12.0).offset == pytest.approx(0.0, abs=BEAT)


def test_audio_that_starts_into_the_intro_moves_the_lyrics_earlier():
    # The video starts 5 s into the release's intro, two bars and a half: LRCLIB's times are 5 s late.
    lines, lyrics_s, segments, beats, downbeats, _ = build(song_form())
    cut = [ChordSegment(max(0.0, s.start - 5.0), s.end - 5.0, s.label) for s in segments if s.end > 5.0]
    found = lyrics_offset(lines, cut, [b - 5.0 for b in beats if b >= 5.0],
                          [b - 5.0 for b in downbeats if b >= 5.0], audio_s=lyrics_s - 5.0, lyrics_s=lyrics_s)
    assert found.offset == pytest.approx(-5.0, abs=BEAT)


def test_one_loop_from_start_to_end_with_no_quiet_end_has_no_clear_winner():
    # Every bar of the audio is music, the same four chords throughout, so a longer intro and a
    # longer outro fit as well as each other, and so does every whole bar between them.
    loop = [(INTRO * 2, [f"Line number {n}" for n in range(4 * k + 1, 4 * k + 5)]) for k in range(6)]
    lines, lyrics_s, segments, *_ = build(loop, tail=0.0)
    longer = [ChordSegment(s.start + 12.0, s.end + 12.0, s.label) for s in segments]
    longer = [ChordSegment(k * BAR, (k + 1) * BAR, INTRO[(k + 2) % 4]) for k in range(6)] + longer
    beats = [k * BEAT for k in range(round((lyrics_s + 12.0) / BEAT) + 1)]
    found = lyrics_offset(lines, longer, beats, beats[::4], audio_s=lyrics_s + 12.0, lyrics_s=lyrics_s)
    assert found.offset is None
    assert "no clear" in found.why


def test_too_few_lines_to_tell_keep_no_offset():
    lines, lyrics_s, segments, beats, downbeats, audio_s = build(song_form(), before=12.0)
    found = lyrics_offset(lines[:3], segments, beats, downbeats, audio_s=audio_s, lyrics_s=lyrics_s)
    assert found.offset is None


def test_lyrics_timed_for_another_song_keep_no_offset():
    # Lines that come every 3.7 s land on this song's bars and chord changes only by chance.
    _, lyrics_s, segments, beats, downbeats, audio_s = build(song_form(), before=12.0)
    lines = [(round(7.3 + 3.7 * k, 3), f"Some other song's line {k}") for k in range(24)]
    found = lyrics_offset(lines, segments, beats, downbeats, audio_s=audio_s, lyrics_s=lyrics_s)
    assert found.offset is None


def test_no_chords_or_no_beats_keep_no_offset():
    lines, lyrics_s, segments, beats, downbeats, audio_s = build(song_form(), before=12.0)
    assert lyrics_offset(lines, [], beats, downbeats, audio_s=audio_s, lyrics_s=lyrics_s).offset is None
    assert lyrics_offset(lines, segments, [], [], audio_s=audio_s, lyrics_s=lyrics_s).offset is None


def test_shifted_lrc_moves_every_line_and_drops_those_before_the_start():
    text = "[ti:Longships]\n[00:01.00]First\n[00:04.50]Second\n[00:06.00]\n[00:10][01:02.25]Third\n"
    assert parse_lrc(shifted_lrc(text, 12.0)) == [(13.0, "First"), (16.5, "Second"), (18.0, ""),
                                                 (22.0, "Third"), (74.25, "Third")]
    assert parse_lrc(shifted_lrc(text, -2.0)) == [(2.5, "Second"), (4.0, ""), (8.0, "Third"), (60.25, "Third")]
    assert shifted_lrc(text, 12.0).splitlines()[:2] == ["[ti:Longships]", "[00:13.000]First"]


def test_shifted_lrc_moves_word_stamps_with_their_lines_and_keeps_an_offset_tag():
    # Enhanced LRC: each word's stamp moves as its line's does, so each word keeps its time.
    text = "[offset:+500]\n[00:01.00]<00:01.00>Row <00:01.40>the <00:02.10>longship <00:03.00>home <00:03.80>\n"
    shifted = parse_lrc_words(shifted_lrc(text, 12.0))
    assert shifted == [LrcLine(round(t.time + 12.0, 3), t.text, tuple((round(w + 12.0, 3), col) for w, col in t.words))
                       for t in parse_lrc_words(text)]
    assert shifted[0].time == 12.5  # the offset tag still applies, as before the shift
