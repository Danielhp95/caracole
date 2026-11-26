"""mpeg_frames.py: an MP3's length counted from its frames, for one whose first frame names no length.

The files are tests/fixtures/audio/'s, which its make.sh wrote once with FFmpeg: short-guess.mp3, a VBR MP3 with no
length header whose loud first frame makes every reader that doesn't count its frames guess it far too short;
long-guess.mp3, its mirror (a quiet first frame, the guess far too long); cbr.mp3, xing.mp3 and tone.m4a, files
every reader agrees on.
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

import mutagen.mp3
import pytest

from caracole import audio_store
from caracole.mpeg_frames import _frame, count, counted_length
from caracole.music import read_audio

AUDIO = Path(__file__).parent / "fixtures" / "audio"
FRAME_S = 1152 / 44100
# The frames of each file, as FFmpeg decodes them (frames x 1152 samples is the length its decode gives).
SHORT_FRAMES, LONG_FRAMES, CBR_FRAMES = 386, 80, 78


def test_a_vbr_mp3_with_no_length_header_is_as_long_as_its_frames_where_mutagen_guesses_far_off():
    found = count(AUDIO / "short-guess.mp3")

    assert found.frames == SHORT_FRAMES
    assert found.seconds == pytest.approx(SHORT_FRAMES * 1152 / 44100)
    guessed = mutagen.mp3.MP3(AUDIO / "short-guess.mp3").info.length
    assert guessed < found.seconds / 5  # 1.7 s of 10.1
    assert found.guessed == pytest.approx(guessed, abs=1e-6)  # the guess every reader took


def test_a_quiet_first_frame_makes_the_guess_too_long_and_the_frames_say_how_long():
    found = count(AUDIO / "long-guess.mp3")

    assert found.frames == LONG_FRAMES
    assert found.seconds == pytest.approx(LONG_FRAMES * FRAME_S)
    guessed = mutagen.mp3.MP3(AUDIO / "long-guess.mp3").info.length
    assert guessed > found.seconds * 5  # 11.5 s of 2.1
    assert found.guessed == pytest.approx(guessed, abs=1e-6)


def test_a_cbr_mp3_with_no_header_is_counted_as_long_as_it_is_guessed():
    found = count(AUDIO / "cbr.mp3")

    assert found.frames == CBR_FRAMES
    assert found.seconds == pytest.approx(mutagen.mp3.MP3(AUDIO / "cbr.mp3").info.length, abs=FRAME_S)
    assert found.guessed == pytest.approx(found.seconds, abs=FRAME_S)


@pytest.mark.parametrize("name", ["xing.mp3", "tone.m4a"])
def test_a_file_whose_first_frame_names_its_length_or_that_is_no_mp3_is_not_counted(name):
    assert count(AUDIO / name) is None
    assert counted_length(AUDIO / name) is None


def test_a_wav_and_an_empty_file_are_not_counted(tmp_path):
    from helpers.audio_files import audio

    (tmp_path / "x.wav").write_bytes(audio("WAV", 1.0))
    (tmp_path / "empty.mp3").write_bytes(b"")

    assert count(tmp_path / "x.wav") is None
    assert count(tmp_path / "empty.mp3") is None


def _id3v2(body: bytes) -> bytes:
    size = len(body)
    synchsafe = bytes([(size >> 21) & 0x7F, (size >> 14) & 0x7F, (size >> 7) & 0x7F, size & 0x7F])
    return b"ID3\x04\x00\x00" + synchsafe + body


def _ape_footer(items: bytes) -> bytes:
    footer = b"APETAGEX" + struct.pack("<IIII", 2000, len(items) + 32, 0, 0) + b"\x00" * 8
    return items + footer


def test_tags_at_either_end_and_junk_between_frames_are_passed_over(tmp_path):
    data = (AUDIO / "short-guess.mp3").read_bytes()
    at = 0
    for _ in range(10):  # the tenth frame's end
        at += _frame(data, at).size
    # Junk between two frames, with a sync word in it that no frame follows.
    junk = b"\x00junk\xff\xfb\x90" + b"\x55" * 40
    messy = (_id3v2(b"\x00" * 300) + _id3v2(b"\x00" * 50) + data[:at] + junk + data[at:]
             + _ape_footer(b"\x00" * 64) + b"TAG" + b"\x00" * 125)
    (tmp_path / "messy.mp3").write_bytes(messy)

    found = count(tmp_path / "messy.mp3")

    assert found.frames == SHORT_FRAMES


def test_a_file_open_in_memory_is_counted_as_one_on_disk():
    data = (AUDIO / "short-guess.mp3").read_bytes()

    assert count(io.BytesIO(data)) == count(AUDIO / "short-guess.mp3")


def test_read_audio_gives_the_counted_length_of_an_mp3_with_no_length_header():
    assert read_audio(AUDIO / "short-guess.mp3").duration_s == pytest.approx(SHORT_FRAMES * FRAME_S)
    assert read_audio(AUDIO / "long-guess.mp3").duration_s == pytest.approx(LONG_FRAMES * FRAME_S)
    # The others as mutagen reads them.
    assert read_audio(AUDIO / "xing.mp3").duration_s == pytest.approx(mutagen.mp3.MP3(AUDIO / "xing.mp3").info.length)


def test_examine_gives_the_counted_length_and_judges_the_thirty_minutes_by_it(tmp_path, monkeypatch):
    assert audio_store.examine(AUDIO / "short-guess.mp3").duration == pytest.approx(SHORT_FRAMES * FRAME_S)
    assert audio_store.examine(AUDIO / "long-guess.mp3").duration == pytest.approx(LONG_FRAMES * FRAME_S)

    # The limit is the counted length's: the guess of long-guess.mp3 (11.5 s) passes 5 s, its 2.1 s don't.
    monkeypatch.setattr(audio_store, "MAX_SECONDS", 5)
    assert audio_store.examine(AUDIO / "long-guess.mp3").duration == pytest.approx(LONG_FRAMES * FRAME_S)
    with pytest.raises(audio_store.AudioError) as refused:
        audio_store.examine(AUDIO / "short-guess.mp3")
    assert refused.value.status == 422


def test_bytes_made_to_crash_a_reader_never_make_the_count_raise():
    import random

    data = (AUDIO / "short-guess.mp3").read_bytes()
    rng = random.Random(7)
    cases = [data[:n] for n in (1, 3, 4, 10, 627, 700, len(data) - 1)]
    cases += [_id3v2(b"\x00" * 10)[:-10] + b"\x7f\x7f\x7f\x7f", b"ID3\x04\x00\x10\x7f\x7f\x7f\x7f",
              data[:2000] + b"APETAGEX" + b"\xff" * 24, b"\xff" * 5000, b"\x00" * 5000]
    for _ in range(200):
        mutated = bytearray(data[:4000])
        for _ in range(rng.randint(1, 40)):
            mutated[rng.randrange(len(mutated))] = rng.randrange(256)
        cases.append(bytes(mutated))
    for case in cases:
        found = count(io.BytesIO(case))
        assert found is None or (found.seconds >= 0 and found.frames >= 0)
