"""autochords/hearing.py: a song's words heard from its audio, the separator and Whisper built once a Hearing,
nothing sung by words.py's rule and noted with why, and the work folders a killed job left swept.

The fakes are test_transcribe_job.py's: demucs-rs a ``Separator`` that writes a WAV, Whisper a ``Transcriber`` that
hears fixed words, the loudness of the stem and the mix fixed frames (``separate.frame_db`` faked): no model runs.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from test_transcribe_job import MIX, STEM, WORDS, Built, Separator, Transcriber, default_models, offered

from caracole.autochords import separate
from caracole.autochords import transcribe as tx
from caracole.autochords.hearing import OWNER, WORK_PREFIX, Hearing, HearingFailed, Kept, Nothing, sweep
from caracole.autochords.transcript import HEARD_NOTHING, TRANSCRIPT, heard_nothing, transcript_of, why_not_offered
from caracole.db import kv_get, kv_get_json
from caracole.overrides import Overrides
from caracole.songs import get_song

STAMP = "2026-11-20T21:00:00Z"
SILENT = [-80.0] * 1200  # a stem with no voice in it
VOCALISE = [-80.0] * 500 + [-12.0] * 120 + [-80.0] * 580  # six seconds of a voice, from 25 s: 24.8 to 31.2 padded


@pytest.fixture(autouse=True)
def stem(monkeypatch):
    """The stem's frames, which a test may change, and the mix's for any other file."""
    frames = list(STEM)

    def frame_db(path, **kwargs):
        return list(frames if Path(path).name == "vocals.wav" else MIX)

    monkeypatch.setattr(separate, "frame_db", frame_db)
    return frames


def hear(cfg, conn, song, *, separator=None, transcriber=None, anyway=False, **words):
    """The song heard, vocals then words, by a Hearing of the fakes: the words' answer and what it said it did."""
    said: list[str] = []
    hearing = Hearing(cfg, separator=separator or Separator(), transcriber=transcriber or Transcriber())
    try:
        vocals = hearing.vocals(song, on_doing=said.append)
        return hearing.words(conn, song, vocals, STAMP, on_doing=said.append, anyway=anyway, **words), said
    finally:
        hearing.close()


def noted(conn, song) -> dict | None:
    return kv_get_json(conn, f"{HEARD_NOTHING}{song.id}")


def test_a_song_sung_keeps_its_words_as_its_transcript(conn, cfg, monkeypatch):
    monkeypatch.delenv("CARACOLE_TORCH_CUDA", raising=False)  # on the CPU: the separator's pace there
    song = offered(conn, cfg)
    transcriber = Transcriber()
    heard, said = hear(cfg, conn, song, transcriber=transcriber)
    assert isinstance(heard, Kept) and (heard.words, heard.lines, heard.dropped) == (16, 4, 1)
    assert heard.said == "16 words in 4 lines (es), 1 dropped"
    assert heard.transcript == transcript_of(conn, get_song(conn, song.id))
    assert heard.transcript.made_at == STAMP and heard.transcript.language == "es"
    [(_, _, first)] = transcriber.calls
    assert first == 24.8  # the language heard on the singing's first seconds
    assert said == ["~5 min", "0:00 of 1:00"]  # what the separator, then Whisper, were at
    assert noted(conn, song) is None


@pytest.mark.parametrize("words,why", [
    (WORDS[:6], "5 words in 0:35 sung"),  # under 8 words
    (WORDS[:11], "10 words in 0:35 sung"),  # 8 or more, but 17 a minute, under 20
], ids=["five words", "ten words"])
def test_too_few_words_are_nothing_sung_and_noted_with_why(conn, cfg, words, why):
    song = offered(conn, cfg)
    transcriber = Transcriber(words)
    heard, _ = hear(cfg, conn, song, transcriber=transcriber)
    assert heard == Nothing(why)
    assert len(transcriber.calls) == 1  # Whisper heard them: too few to be lyrics
    assert kv_get(conn, f"{TRANSCRIPT}{song.id}") is None
    assert noted(conn, song) == {"audio": song.audio_path, "audio_mtime": song.audio_mtime, "at": STAMP, "why": why,
                                 "by": "caracole"}
    assert heard_nothing(conn, song) and why_not_offered(conn, cfg, song, Overrides()) == "nothing sung was heard"


@pytest.mark.parametrize("frames,sung,why", [
    (VOCALISE, "sung from 24.8 s, 1 stretch", "sung 6.4 s"),
    (SILENT, "no singing found", "sung 0.0 s"),
], ids=["six seconds sung", "no singing found"])
def test_a_short_sung_time_runs_no_whisper(conn, cfg, tmp_path, monkeypatch, stem, frames, sung, why):
    # Under ten seconds sung, the guard would keep too few words to be lyrics: Whisper isn't even built (a minute or
    # two to load on a CPU), and nothing sung is noted.
    stem[:] = frames
    built = Built(monkeypatch)
    setup = default_models(cfg, tmp_path)
    song = offered(conn, setup)
    hearing = Hearing(setup)
    try:
        vocals = hearing.vocals(song, on_doing=lambda said: None)
        assert vocals.said == sung
        assert hearing.words(conn, song, vocals, STAMP, on_doing=lambda said: None) == Nothing(why)
    finally:
        hearing.close()
    assert [entry[0] for entry in built.log] == ["demucs built", "demucs"]
    assert noted(conn, song)["why"] == why and kv_get(conn, f"{TRANSCRIPT}{song.id}") is None


@pytest.mark.parametrize("frames,words,first,kept", [
    (STEM, WORDS[:6], 24.8, 5),  # too few words, kept anyway
    (VOCALISE, WORDS, 24.8, 8),  # six seconds sung: Whisper runs, its words kept within the spans
    (SILENT, WORDS, 0.0, 17),  # no span: every word, the whole song one span, the intro's too
], ids=["five words", "six seconds sung", "no singing found"])
def test_anyway_skips_both_rules(conn, cfg, stem, frames, words, first, kept):
    # The owner's "it is sung": Whisper runs whatever the spans, and what it heard there is kept.
    stem[:] = frames
    song = offered(conn, cfg)
    transcriber = Transcriber(words)
    heard, _ = hear(cfg, conn, song, transcriber=transcriber, anyway=True)
    assert isinstance(heard, Kept) and heard.words == kept
    [(_, _, sung_from)] = transcriber.calls
    assert sung_from == first
    assert transcript_of(conn, get_song(conn, song.id)) == heard.transcript and noted(conn, song) is None


def test_anyway_with_no_word_heard_is_still_nothing_sung(conn, cfg):
    song = offered(conn, cfg)
    assert hear(cfg, conn, song, transcriber=Transcriber([]), anyway=True)[0] == Nothing("0 words in 0:35 sung")
    assert noted(conn, song)["why"] == "0 words in 0:35 sung"


@pytest.mark.parametrize("separator,transcriber,kind,words", [
    (Separator(fail="No possible adapter"), Transcriber(), "setup",
     "the separator can't run here (No possible adapter)"),
    (Separator(), Transcriber(fail=tx.SetupFailed("the GPU failed: CUDA out of memory")), "setup",
     "the GPU failed: CUDA out of memory"),
    (Separator(), Transcriber(fail=RuntimeError("Failed to load audio: [mov,mp4] moov atom not found")), "audio",
     "can't read the audio"),
], ids=["the separator", "the GPU", "the audio"])
def test_a_failure_says_whose_it_is_and_only_the_audios_is_filed(conn, cfg, separator, transcriber, kind, words):
    song = offered(conn, cfg)
    with pytest.raises(HearingFailed) as failed:
        hear(cfg, conn, song, separator=separator, transcriber=transcriber)
    assert (failed.value.kind, failed.value.words, str(failed.value)) == (kind, words, words)
    assert (kv_get(conn, f"autochords:failed:{song.id}") is not None) == (kind == "audio")
    assert noted(conn, song) is None and kv_get(conn, f"{TRANSCRIPT}{song.id}") is None


def test_audio_whisper_cant_read_is_filed_only_where_the_caller_says(conn, cfg):
    # Whisper reads the mix through the ffmpeg program, auto-chords through its own reader, which the vocals read it
    # with already: a job that makes the chords all the same files nothing, and auto-chords gives its own verdict.
    song = offered(conn, cfg)
    with pytest.raises(HearingFailed) as failed:
        hear(cfg, conn, song, transcriber=Transcriber(fail=RuntimeError("Failed to load audio: moov atom not found")),
             file_unreadable=False)
    assert (failed.value.kind, failed.value.words) == ("audio", "Whisper can't read the audio")
    assert kv_get(conn, f"autochords:failed:{song.id}") is None
    assert why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) is None


def test_hearing_builds_each_model_once_a_run(conn, cfg, tmp_path, monkeypatch):
    # The nightly run hears a few songs in a row: demucs-rs and Whisper (a minute or two to load on a CPU, and its test
    # tone) are built for the first, and kept for the rest; one song's stem at a time under the work folder.
    built = Built(monkeypatch)
    setup = default_models(cfg, tmp_path)
    songs = [offered(conn, setup), offered(conn, setup, artist="Otro", title="Canción")]
    hearing = Hearing(setup)
    stems = []
    try:
        for song in songs:
            vocals = hearing.vocals(song, on_doing=lambda said: None)
            stems.append(vocals.stem)
            assert isinstance(hearing.words(conn, song, vocals, STAMP, on_doing=lambda said: None), Kept)
        assert not stems[0].exists() and stems[1].is_file()
    finally:
        hearing.close()
    first, second = (Path(song.audio_path).name for song in songs)
    assert [entry[0] for entry in built.log if entry[0].endswith(" built")] == ["demucs built", "whisper built"]
    assert [entry for entry in built.log if entry[0] in ("demucs", "whisper")] == [
        ("demucs", first), ("whisper", "test-tone.wav"), ("whisper", first), ("demucs", second), ("whisper", second)]
    assert all(transcript_of(conn, get_song(conn, song.id)) is not None for song in songs)
    assert not list(setup.cache_dir.glob(f"{WORK_PREFIX}*"))  # the work folder goes once the Hearing is closed


def test_sweep_still_spares_a_live_jobs_folder(conn, cfg):
    # A transcription that lets the lookups have caracole's lock before its words keeps its stem under the cache: a
    # job asked for meanwhile sweeps the folders killed jobs left (their owner's lock went with their process; an
    # older caracole's has no owner file), never a live one's.
    song = offered(conn, cfg)
    killed, older, unread = (cfg.cache_dir / f"{WORK_PREFIX}{name}" for name in ("k1ll3d", "0ld", "odd"))
    (killed / "1" / "stems").mkdir(parents=True)
    (killed / OWNER).write_bytes(b"")
    (older / "song" / "stems").mkdir(parents=True)
    (unread / OWNER).mkdir(parents=True)  # an owner file that can't be opened: kept
    elsewhere = cfg.cache_dir / "youtube"
    (cfg.cache_dir / f"{WORK_PREFIX}link").symlink_to(elsewhere, target_is_directory=True)
    hearing = Hearing(cfg, separator=Separator(), transcriber=Transcriber())
    try:
        vocals = hearing.vocals(song, on_doing=lambda said: None)
        sweep(cfg.cache_dir)
        assert vocals.stem.is_file()
        assert not killed.exists() and not older.exists() and unread.is_dir()
        assert Path(song.audio_path).is_file()  # a link is never followed
        assert isinstance(hearing.words(conn, song, vocals, STAMP, on_doing=lambda said: None), Kept)
    finally:
        hearing.close()
    assert not vocals.stem.parents[2].exists()  # the work folder itself, gone once the Hearing is closed
    sweep(cfg.cache_dir / "nowhere")  # a cache not made yet: nothing to sweep


def test_words_refuse_vocals_that_are_no_longer_the_songs_current_stem(conn, cfg):
    # A pass over the library separates one song's vocals at a time, the next song's taking the last one's place:
    # vocals heard before another song was separated, of another song, or of audio replaced since are a caller's bug,
    # refused in words of its own before Whisper runs, never blamed on the separator.
    first, second = offered(conn, cfg), offered(conn, cfg, artist="Otro", title="Canción")
    transcriber = Transcriber()
    hearing = Hearing(cfg, separator=Separator(), transcriber=transcriber)
    try:
        earlier = hearing.vocals(first, on_doing=lambda said: None)
        now = hearing.vocals(second, on_doing=lambda said: None)
        with pytest.raises(ValueError, match=r"^the vocals of Nick Cani - Vikingos veganos are no longer its "
                                             r"current stem: separate them again$"):
            hearing.words(conn, first, earlier, STAMP, on_doing=lambda said: None)
        with pytest.raises(ValueError, match=r"^the vocals given aren't Nick Cani - Vikingos veganos's"):
            hearing.words(conn, first, now, STAMP, on_doing=lambda said: None)
        moved = replace(second, audio_mtime=(second.audio_mtime or 0) + 5)
        with pytest.raises(ValueError, match=r"^the vocals of Otro - Canción were separated from other audio"):
            hearing.words(conn, moved, now, STAMP, on_doing=lambda said: None)
        assert transcriber.calls == []
        assert isinstance(hearing.words(conn, second, now, STAMP, on_doing=lambda said: None), Kept)
    finally:
        hearing.close()
