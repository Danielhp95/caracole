"""transcribe_job.py: a YouTube song's lyrics transcribed from its audio, then its auto sheet made again over them.

demucs-rs is a fake ``Separator`` that writes a WAV, Whisper a fake ``Transcriber`` that hears fixed words, the
loudness of the stem and the mix fixed frames (``separate.frame_db`` faked, but in the one test marked
``autochords``, which reads an AAC .m4a for real), auto-chords' models test_youtube_sheet.py's fakes and chordpro
``fake_chordpro``: no model runs and nothing reaches the network.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import add_song, subprocess_pythonpath
from helpers.aac import RATE as AAC_RATE
from helpers.aac import aac_m4a, needs_aac
from helpers.aac import samples as aac_samples
from helpers.locks import waiting_for
from helpers.rendered import fake_chordpro
from test_youtube_sheet import Heard, Recognizer, beats, keep_human_sheet, wav

from caracole.autochords import separate
from caracole.autochords import transcribe as tx
from caracole.autochords.separate import SeparatorFailed
from caracole.autochords.transcript import (
    HEARD_NOTHING,
    NOTE,
    TRANSCRIPT,
    Transcript,
    heard_nothing,
    transcript_of,
    why_not_offered,
)
from caracole.autochords.words import Word
from caracole.commands import _common
from caracole.db import kv_get, kv_get_json, kv_set
from caracole.library import song_dir
from caracole.lyrics import Lyrics
from caracole.overrides import Overrides
from caracole.songs import get_song, update_song
from caracole.transcribe_job import STAGES, TranscribeRequest, _Transcription, make_transcript
from caracole.youtube import Video
from caracole.youtube_fetch import Record, _save

NOW = datetime(2026, 11, 20, 21, 0, tzinfo=UTC)
VIDEO = "XFkzRNyygfk"
# 50 ms frames: the stem silent through the intro's 25 s, then sung to the minute's end; the mix loud throughout.
STEM = [-80.0] * 500 + [-12.0] * 700
MIX = [-10.0] * 1200
REAL_FRAME_DB = separate.frame_db  # the autouse ``loudness`` fakes it; a test of the real reader puts it back
INTRO = Word(0.0, 0.4, "Suscríbete", False, True)  # Whisper's own, over the intro nobody sings
# Sung as a song is (words.py's rule): 16 words in the 35.4 s sung, 27 a minute.
WORDS = [
    INTRO,
    Word(25.5, 26.0, "Somos", True, True),
    Word(26.1, 26.6, "vikingos", True),
    Word(26.7, 27.0, "de", True),
    Word(27.1, 27.6, "prueba", True),
    Word(30.0, 30.5, "comemos", True, True),
    Word(30.6, 31.0, "lechuga", True),
    Word(31.1, 31.3, "y", True),
    Word(31.4, 32.0, "tomate", True),
    Word(34.5, 35.0, "nunca", True, True),
    Word(35.1, 35.5, "carne", True),
    Word(35.6, 35.8, "de", True),
    Word(35.9, 36.4, "vaca", True),
    Word(38.0, 38.4, "somos", True, True),
    Word(38.5, 39.0, "vikingos", True),
    Word(39.1, 39.6, "veganos", True),
    Word(39.7, 40.0, "hoy", True),
]
LRC = ("[00:25.50] <00:25.50>Somos <00:26.10>vikingos <00:26.70>de <00:27.10>prueba\n"
       "[00:27.60]\n"
       "[00:30.00] <00:30.00>comemos <00:30.60>lechuga <00:31.10>y <00:31.40>tomate\n"
       "[00:32.00]\n"
       "[00:34.50] <00:34.50>nunca <00:35.10>carne <00:35.60>de <00:35.90>vaca\n"
       "[00:38.00] <00:38.00>somos <00:38.50>vikingos <00:39.10>veganos <00:39.70>hoy\n")
SAID = "16 words in 4 lines (es), 1 dropped"  # the words stage's end, for WORDS


class Separator:
    """demucs-rs: a vocal stem written under the work folder it is given; the audio never listened to."""

    def __init__(self, *, fail: str | None = None, log: list | None = None):
        self.calls: list[tuple[Path, Path]] = []
        self.fail, self.log = fail, log

    def vocals(self, audio, workdir, *, on_tick=None):
        self.calls.append((Path(audio), Path(workdir)))
        if self.log is not None:
            self.log.append("separator")
        if self.fail is not None:
            raise SeparatorFailed(self.fail)
        return wav(Path(workdir) / "stems" / "vocals.wav", 1.0)


class Transcriber:
    """Whisper: fixed words in a fixed language, or ``fail`` raised."""

    device = "cpu"

    def __init__(self, words=WORDS, *, language="es", fail: Exception | None = None, log: list | None = None):
        self.words, self.language, self.fail, self.log = list(words), language, fail, log
        self.calls: list[tuple[Path, Path, float]] = []

    def hear(self, mix, stem, first_sung_s, *, on_progress=None):
        self.calls.append((Path(mix), Path(stem), first_sung_s))
        if self.log is not None:
            self.log.append("transcriber")
        if self.fail is not None:
            raise self.fail
        return tx.Heard(self.language, list(self.words))


@pytest.fixture(autouse=True)
def loudness(monkeypatch):
    """librosa's frame loudness, faked: the stem's frames for a vocal stem, the mix's for any other file."""
    read: list[Path] = []

    def frame_db(path, **kwargs):
        read.append(Path(path))
        return list(STEM if Path(path).name == "vocals.wav" else MIX)

    monkeypatch.setattr(separate, "frame_db", frame_db)
    return read


@pytest.fixture(autouse=True)
def no_sites(monkeypatch):
    def transport(provider):
        pytest.fail(f"a client for {provider} was made")

    monkeypatch.setattr(_common, "transport_for", transport)


def offered(conn, cfg, artist="Nick Cani", title="Vikingos veganos", seconds=60.0, audio=None):
    """A song whose audio came from YouTube, its lyrics missing and every lyrics site asked: one offered a
    transcription. Its audio is ``seconds`` of silence in a WAV, or what ``audio`` writes given the file's path in the
    cache's youtube folder (its suffix ``.wav``) and returns."""
    song = add_song(conn, artist, title, duration_ms=None)
    path = cfg.cache_dir / "youtube" / f"{song.id}-{VIDEO}.wav"
    audio = wav(path, seconds) if audio is None else audio(path)
    update_song(conn, song.id, audio_path=str(audio), audio_mtime=audio.stat().st_mtime, lyrics_status="missing",
                lyrics_at="2026-11-01T00:00:00Z")
    _save(conn, song.id, Record(video=Video(VIDEO, title, "HyperFanes", seconds), source="pasted", audio=str(audio)))
    for site in ("megalobiz", "azlyrics"):
        kv_set(conn, f"{site}:checked:{song.id}", "2026-11-01T00:00:00Z")
    song = get_song(conn, song.id)
    assert why_not_offered(conn, cfg, song, Overrides()) is None
    return song


def make(cfg, *, separator=None, transcriber=None, recognizer=None, progress=None, artist="Nick Cani",
         title="Vikingos veganos", force=False, none=False):
    heard = progress or Heard()
    result = make_transcript(cfg, TranscribeRequest(artist, title, force=force, none=none), heard,
                             separator=separator or Separator(), transcriber=transcriber or Transcriber(),
                             recognizer=recognizer or Recognizer(), beats_fn=beats, runner=fake_chordpro, now=NOW)
    return result, heard


def auto_sheet(cfg, conn, song) -> Path:
    return song_dir(cfg.library_dir, song) / "sheet (auto).txt"


def kept(conn, song) -> Transcript | None:
    return Transcript.from_json(kv_get_json(conn, f"{TRANSCRIPT}{song.id}"))


def nothing_recorded(conn, song) -> bool:
    """No transcript, no "heard nothing", no audio auto-chords can't read: nothing against the song."""
    return all(kv_get(conn, f"{prefix}{song.id}") is None
               for prefix in (TRANSCRIPT, HEARD_NOTHING, "autochords:failed:"))


# --- the whole way ------------------------------------------------------------------------------------------------


def test_an_offered_song_gets_its_transcript_and_its_sheet_over_it(conn, cfg):
    song = offered(conn, cfg)
    separator, transcriber, recognizer = Separator(), Transcriber(), Recognizer()
    result, heard = make(cfg, separator=separator, transcriber=transcriber, recognizer=recognizer)
    assert result.ok, result
    assert [e[1] for e in heard.events if e[0] == "stage" and e[2] != "running"] == [name for name, _ in STAGES]
    ends = heard.ends()
    assert ends["song"] == ("done", "in the book")
    assert ends["vocals"] == ("done", "sung from 24.8 s, 1 stretch")
    assert ends["words"] == ("done", SAID)
    assert ends["chords"] == ("done", "chords over the transcribed lyrics")
    assert ends["pdf"] == ("done", "made")
    assert ends["pages"] == ("done", "_todo.md and index.html rewritten")
    assert ("song", song.id, "Nick Cani - Vikingos veganos") in heard.events
    # The separator heard the song's audio; Whisper the mix, the stem beside it, the singing's first second.
    audio = Path(song.audio_path)
    [(separated, work)] = separator.calls
    [(mix, stem, first)] = transcriber.calls
    assert separated == mix == audio and first == 24.8
    assert stem == work / "stems" / "vocals.wav" and work.is_relative_to(cfg.cache_dir)
    assert not work.exists()  # the work folder goes with the job
    # The transcript is kept apart from the song's lyrics, which stay missing.
    assert kept(conn, song) == Transcript(lrc=LRC, audio=song.audio_path, audio_mtime=song.audio_mtime,
                                          model="whisper-large-v3", language="es", device="cpu", words_dropped=1,
                                          made_at="2026-11-20T21:00:00Z")
    after = get_song(conn, song.id)
    assert (after.lyrics_status, after.lyrics_json) == ("missing", None)
    assert why_not_offered(conn, cfg, after, Overrides()) == "already transcribed"
    # Then the sheet, over the transcribed words, saying so.
    text = auto_sheet(cfg, conn, song).read_text(encoding="utf-8")
    assert NOTE in text.splitlines() and "Somos vikingos de prueba" in text.splitlines()
    assert recognizer.calls == [audio]
    files = [e[1] for e in heard.events if e[0] == "files"]
    assert files[-1]["viewer"] == "Nick Cani/Vikingos veganos/sheet (auto).html"
    assert not cfg.wanted_file.exists()  # the song was in the book: nothing added


class Ticking(Separator):
    """demucs-rs on the CPU, telling how long it has run at each tick: more than once a minute, past its estimate."""

    def vocals(self, audio, workdir, *, on_tick=None):
        for ran in (5.0, 61.0, 65.0, 130.0, 290.0, 300.0):
            on_tick(ran)
        return super().vocals(audio, workdir)


class Hearing(Transcriber):
    """Whisper, telling how far it has heard the minute of mix, a 30 s window at a time."""

    def hear(self, mix, stem, first_sung_s, *, on_progress=None):
        for done in (30.0, 60.0):
            on_progress(done, 60.0)
        return super().hear(mix, stem, first_sung_s)


@pytest.mark.parametrize("gpu,about", [(False, "~5 min"), (True, "~1 min")], ids=["cpu", "gpu"])
def test_each_long_stage_says_how_far_it_is_as_it_runs(conn, cfg, monkeypatch, gpu, about):
    # The separator and Whisper take minutes, up to half an hour on a CPU: the song's line moves as they go (the
    # vocals' minutes against about how long demucs-rs takes for the song's minute here, Whisper's place in the mix,
    # auto-chords' steps), each change said once, and each stage's end as before.
    from caracole import youtube_fetch

    monkeypatch.setattr(youtube_fetch, "transcribes_on_the_gpu", lambda cfg: gpu)
    offered(conn, cfg)
    result, heard = make(cfg, separator=Ticking(), transcriber=Hearing())
    assert result.ok, result
    running = [(e[1], e[3]) for e in heard.events if e[0] == "stage" and e[2] == "running"]
    vocals = [about] + (["1 of ~5 min", "2 of ~5 min", "4 of ~5 min", "5 min so far"] if not gpu else [
        "1 min so far", "2 min so far", "4 min so far", "5 min so far"])
    assert running == [
        ("song", ""),
        ("vocals", ""), *(("vocals", said) for said in vocals),
        ("words", ""), ("words", "0:00 of 1:00"), ("words", "0:30 of 1:00"), ("words", "1:00 of 1:00"),
        ("chords", ""), ("chords", "setting up the models"), ("chords", "hearing the chords"),
        ("chords", "finding the beats"), ("chords", "writing the sheet"),
        ("pdf", ""), ("pages", ""),
    ]
    assert heard.ends()["vocals"] == ("done", "sung from 24.8 s, 1 stretch")
    assert heard.ends()["words"] == ("done", SAID)


def test_words_outside_the_singing_are_dropped(conn, cfg):
    song = offered(conn, cfg)
    result, heard = make(cfg)
    assert result.ok
    transcript = kept(conn, song)
    assert transcript.words_dropped == 1 and "Suscríbete" not in transcript.lrc
    assert "Suscríbete" not in auto_sheet(cfg, conn, song).read_text(encoding="utf-8")
    assert heard.ends()["words"][1].endswith(", 1 dropped")


@pytest.mark.parametrize("words,why", [
    ([], "0 words in 0:35 sung"),
    ([INTRO], "0 words in 0:35 sung"),
    (WORDS[:6], "5 words in 0:35 sung"),  # a shouted line over a song's worth of singing: under 8 words
    (WORDS[:11], "10 words in 0:35 sung"),  # 17 a minute, under 20: a pad's invented words
], ids=["nothing heard", "only the intro", "five words", "ten words"])
def test_no_singing_heard_records_it_and_fails_without_a_sheet(conn, cfg, words, why):
    song = offered(conn, cfg)
    recognizer = Recognizer()
    result, heard = make(cfg, transcriber=Transcriber(words), recognizer=recognizer)
    assert not result.ok and result.failed == "no singing heard" and result.bug is None
    ends = heard.ends()
    assert ends["words"] == ("failed", "no singing heard")
    assert [ends[name][0] for name in ("chords", "pdf", "pages")] == ["skipped", "skipped", "done"]
    assert recognizer.calls == [] and not auto_sheet(cfg, conn, song).exists()
    assert kept(conn, song) is None
    # Not offered again until the song's audio changes, and noted with why.
    assert heard_nothing(conn, song)
    assert why_not_offered(conn, cfg, song, Overrides()) == "nothing sung was heard"
    noted = kv_get_json(conn, f"{HEARD_NOTHING}{song.id}")
    assert (noted["why"], noted["by"]) == (why, "caracole")



@pytest.mark.parametrize("short", [1, 4])
def test_a_stem_a_few_frames_shorter_than_the_mix_is_read_as_far_as_both_go(conn, cfg, monkeypatch, short):
    # demucs-rs writes the stem at its own rate: resampled, it may have a frame or so fewer than the mix.
    offered(conn, cfg)
    monkeypatch.setattr(separate, "frame_db",
                        lambda path, **kw: list(STEM[:-short] if Path(path).name == "vocals.wav" else MIX))
    result, heard = make(cfg)
    assert result.ok, result
    assert heard.ends()["vocals"] == ("done", "sung from 24.8 s, 1 stretch")


@pytest.mark.parametrize("short,said", [(5, "0.25"), (200, "10")])
def test_a_stem_shorter_than_the_song_is_the_separators_failure(conn, cfg, monkeypatch, short, said):
    # Read only as far as both go, its singing past its end would be lost without a word.
    song = offered(conn, cfg)
    monkeypatch.setattr(separate, "frame_db",
                        lambda path, **kw: list(STEM[:-short] if Path(path).name == "vocals.wav" else MIX))
    transcriber = Transcriber()
    result, heard = make(cfg, transcriber=transcriber)
    failed = f"the separator can't run here (its vocals are {said} s shorter than the song)"
    assert not result.ok and result.bug is None and result.failed == failed
    assert heard.ends()["vocals"] == ("failed", failed)
    assert transcriber.calls == []
    assert nothing_recorded(conn, song)
    assert why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) is None


def test_a_killed_jobs_work_folders_are_swept_when_the_next_job_starts(conn, cfg):
    # A job killed in its stages leaves its stem (tens of MB) under the cache, and its folder no live job holds (its
    # lock on the folder's owner file went with its process; an older caracole's folder has none).
    offered(conn, cfg)
    stale = [cfg.cache_dir / name for name in ("transcribe-k1ll3d0", "transcribe-0ld")]
    for folder in stale:
        (folder / "song" / "stems").mkdir(parents=True)
        (folder / "song" / "stems" / "vocals.wav").write_bytes(b"RIFF")
    (stale[0] / ".owner").write_bytes(b"")
    other = cfg.cache_dir / "youtube"
    result, _ = make(cfg)
    assert result.ok, result
    assert not any(folder.exists() for folder in stale)
    assert other.is_dir() and list(other.iterdir())  # the rest of the cache stays
    assert not list(cfg.cache_dir.glob("transcribe-*"))  # and the job's own went with it


class StemFirst(Transcriber):
    """Whisper as WhisperTranscriber.hear runs it: the stem read first, for the language, and a stem that is gone
    failing as openai-whisper's load_audio fails (ffmpeg 9.0.1's words)."""

    def hear(self, mix, stem, first_sung_s, **kwargs):
        if not Path(stem).is_file():
            raise RuntimeError("Failed to load audio: Error opening input files: No such file or directory")
        return super().hear(mix, stem, first_sung_s, **kwargs)


def test_a_second_transcription_in_the_first_ones_hand_over_leaves_its_stem_alone(conn, cfg, monkeypatch):
    # Before the words, the job hands caracole's lock to the lookups and waits for it with a ticket outside the lane;
    # another caracole asked for now (a terminal's `caracole transcribe` of another song) may take the lock first once
    # the lane is empty. Its sweep leaves a live job's folder alone: the first job's stem gone, Whisper would fail on
    # it, and the song's good audio would be filed as audio that can't be read.
    first = offered(conn, cfg)
    offered(conn, cfg, artist="Otro", title="Canción")
    monkeypatch.setattr(_common, "_handoffs", _common.handoffs())  # put back as it was after the test
    heard = Heard()
    second = []

    def hand_over(cfg_, conn_=None) -> bool:
        if heard.events[-1][1:3] != ("words", "running") or second:  # the second job's own hand-overs: none
            return False
        second.append(None)
        second[0] = make_transcript(cfg_, TranscribeRequest("Otro", "Canción"), Heard(), separator=Separator(),
                                    transcriber=StemFirst(), recognizer=Recognizer(), beats_fn=beats,
                                    runner=fake_chordpro, now=NOW)
        _common._handoffs += 1
        return True

    monkeypatch.setattr(_common, "hand_over", hand_over)
    result, _ = make(cfg, transcriber=StemFirst(), progress=heard)
    assert second and second[0].ok, second
    assert result.ok, result
    assert heard.ends()["words"] == ("done", SAID)
    assert kv_get(conn, f"autochords:failed:{first.id}") is None
    assert why_not_offered(conn, cfg, get_song(conn, first.id), Overrides()) == "already transcribed"
    assert not list(cfg.cache_dir.glob("transcribe-*"))  # both went with their jobs


def test_a_song_with_an_auto_sheet_over_no_lyrics_gets_it_made_again_over_its_transcript(conn, cfg):
    # The example's own way: `caracole youtube --sheet` made a chart with no words, and then its lyrics are
    # transcribed.
    from caracole.autochords.run import autochords_pending

    song = offered(conn, cfg)
    autochords_pending(conn, cfg, recognizer=Recognizer(), beats_fn=beats, only={song.id})
    before = auto_sheet(cfg, conn, song).read_text(encoding="utf-8")
    assert NOTE not in before.splitlines() and "Somos vikingos de prueba" not in before
    recognizer = Recognizer()
    result, heard = make(cfg, recognizer=recognizer)
    assert result.ok, result
    assert heard.ends()["chords"] == ("done", "chords over the transcribed lyrics")
    assert recognizer.calls == [Path(song.audio_path)]
    lines = auto_sheet(cfg, conn, song).read_text(encoding="utf-8").splitlines()
    assert NOTE in lines and "Somos vikingos de prueba" in lines


@pytest.mark.parametrize("chart_before", [False, True], ids=["no sheet before", "a chart before"])
def test_try_again_after_the_chords_failed_makes_the_sheet_over_the_transcript_kept(conn, cfg, monkeypatch,
                                                                                    chart_before):
    # The words keep the transcript before the chords run: when auto-chords can't keep the sheet (a full disk), or the
    # server stops mid-way, Try again runs the same `caracole transcribe`, which goes straight to the chords over the
    # transcript kept, neither model run again; never "already transcribed", the sheet over it left to the night.
    from caracole.autochords import run as ac_run
    from caracole.autochords.run import autochords_pending

    song = offered(conn, cfg)
    if chart_before:
        autochords_pending(conn, cfg, recognizer=Recognizer(), beats_fn=beats, only={song.id})
    keep_sheet = ac_run._keep

    def full_disk(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(ac_run, "_keep", full_disk)
    first, _ = make(cfg)
    assert first.failed and first.failed.startswith("auto-chords can't run here"), first
    assert transcript_of(conn, get_song(conn, song.id)) is not None
    monkeypatch.setattr(ac_run, "_keep", keep_sheet)  # room again
    separator, transcriber, recognizer = Separator(), Transcriber(), Recognizer()
    again, heard = make(cfg, separator=separator, transcriber=transcriber, recognizer=recognizer)
    assert again.ok, again
    ends = heard.ends()
    assert ends["song"] == ("done", "in the book; transcribed already, its sheet to make")
    assert ends["vocals"] == ("skipped", "transcribed already")
    assert ends["words"] == ("done", "the transcript kept")
    assert ends["chords"] == ("done", "chords over the transcribed lyrics")
    assert separator.calls == transcriber.calls == [] and recognizer.calls == [Path(song.audio_path)]
    lines = auto_sheet(cfg, conn, song).read_text(encoding="utf-8").splitlines()
    assert NOTE in lines and "Somos vikingos de prueba" in lines
    # Once the sheet is over it, a transcription of it is asked for no more.
    third, _ = make(cfg)
    assert third.refused == "Nick Cani - Vikingos veganos isn't offered a transcription: already transcribed"


def test_a_songs_auto_sheet_record_that_cant_be_read_is_a_refusal_never_a_traceback(conn, cfg):
    # Whether a transcribed song's sheet is still to make reads its auto sheet's record (run.py _skip_reason): a
    # record another device wrote that won't read stops the job as a refusal, in its words, as auto-chords counts
    # such a song an error and goes on.
    from caracole.autochords.run import autochords_pending
    from caracole.autochords.transcript import keep_transcript

    song = offered(conn, cfg)
    autochords_pending(conn, cfg, recognizer=Recognizer(), beats_fn=beats, only={song.id})
    keep_transcript(conn, song, Transcript(lrc=LRC, audio=song.audio_path, audio_mtime=song.audio_mtime,
                                           model="whisper-large-v3", language="es", device="cpu", words_dropped=1,
                                           made_at="2026-11-19T21:00:00Z"))
    conn.execute("UPDATE versions SET raw = '{not json' WHERE song_id = ?", (song.id,))
    separator, transcriber, recognizer = Separator(), Transcriber(), Recognizer()
    result, heard = make(cfg, separator=separator, transcriber=transcriber, recognizer=recognizer)
    assert result.bug is None and result.failed is None
    assert result.refused is not None and result.refused.startswith(
        "Nick Cani - Vikingos veganos: its auto sheet's record can't be read (JSONDecodeError: "), result.refused
    assert heard.ends()["song"] == ("failed", result.refused)
    assert separator.calls == transcriber.calls == recognizer.calls == []


@pytest.mark.parametrize("stem,vocals,why", [
    ([-80.0] * 1200, "no singing found", "sung 0.0 s"),
    ([-80.0] * 500 + [-12.0] * 120 + [-80.0] * 580, "sung from 24.8 s, 1 stretch", "sung 6.4 s"),  # a vocalise
], ids=["no singing found", "six seconds sung"])
def test_with_no_singing_found_whisper_never_runs_and_nothing_sung_is_noted(conn, cfg, monkeypatch, stem, vocals,
                                                                            why):
    # The guard would drop every word Whisper heard, or keep too few to be lyrics: it isn't run (up to half an hour
    # on a CPU).
    song = offered(conn, cfg)
    monkeypatch.setattr(separate, "frame_db",
                        lambda path, **kw: list(stem) if Path(path).name == "vocals.wav" else list(MIX))
    transcriber, recognizer = Transcriber(), Recognizer()
    result, heard = make(cfg, transcriber=transcriber, recognizer=recognizer)
    assert not result.ok and result.failed == "no singing heard" and result.bug is None
    ends = heard.ends()
    assert ends["vocals"] == ("done", vocals)
    assert ends["words"] == ("failed", "no singing heard")
    assert transcriber.calls == [] and recognizer.calls == []
    assert heard_nothing(conn, song) and kept(conn, song) is None
    assert kv_get_json(conn, f"{HEARD_NOTHING}{song.id}")["why"] == why


class Lenient(_Transcription):
    """A job whose words not coming fail no more than their own stage, as a sheet from a YouTube video's is; the
    transcription's chords, which need a transcript, left out."""

    WORDS_FAIL_THE_JOB = False

    def chords(self):
        return "skipped", "not this job's"


@pytest.mark.parametrize("transcriber,words", [
    (Transcriber(fail=tx.SetupFailed("the GPU failed: CUDA out of memory")),
     ("failed", "the GPU failed: CUDA out of memory")),
    (Transcriber(WORDS[:6]), ("done", "nothing sung was heard (5 words in 0:35 sung)")),
], ids=["the setup failed", "nothing sung"])
def test_a_job_whose_words_dont_fail_it_ends_their_stage_alone(conn, cfg, transcriber, words):
    song = offered(conn, cfg)
    heard = Heard()
    result = Lenient(cfg, TranscribeRequest("Nick Cani", "Vikingos veganos"), heard, separator=Separator(),
                     transcriber=transcriber, recognizer=Recognizer(), beats_fn=beats, runner=fake_chordpro, now=NOW,
                     clock=time.monotonic).run()
    assert result.ok and result.failed is None, result
    assert heard.ends()["words"] == words
    assert kept(conn, song) is None
    assert not list(cfg.cache_dir.glob("transcribe-*"))  # the work folder goes with the job all the same

# --- refused: nothing runs ----------------------------------------------------------------------------------------


def with_lyrics(conn, cfg, song):
    lyrics = Lyrics(plain="Somos vikingos", synced=None, instrumental=False, duration=None, lrclib_id=None)
    update_song(conn, song.id, lyrics_status="found", lyrics_json=lyrics.to_json())


def ignored(conn, cfg, song):
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(f'[ignore]\nsongs = ["{song.display}"]\n', encoding="utf-8")


@pytest.mark.parametrize("change,said", [
    (with_lyrics, "Nick Cani - Vikingos veganos isn't offered a transcription: its lyrics are found"),
    (ignored, "Nick Cani - Vikingos veganos isn't offered a transcription: ignored"),
    (lambda conn, cfg, song: conn.execute("DELETE FROM songs"), "Nick Cani - Vikingos veganos isn't in the book"),
], ids=["lyrics found", "ignored", "not in the book"])
def test_a_song_not_offered_is_refused_with_its_reason_and_nothing_runs(conn, cfg, change, said):
    song = offered(conn, cfg)
    change(conn, cfg, song)
    separator, transcriber, recognizer = Separator(), Transcriber(), Recognizer()
    result, heard = make(cfg, separator=separator, transcriber=transcriber, recognizer=recognizer)
    assert not result.ok and result.refused == said
    assert heard.ends()["song"] == ("failed", said)
    assert all(heard.ends()[name][0] == "skipped" for name, _ in STAGES[1:])
    assert separator.calls == transcriber.calls == recognizer.calls == []
    assert kept(conn, song) is None and kv_get(conn, f"{HEARD_NOTHING}{song.id}") is None
    assert not cfg.wanted_file.exists()  # a song not in the book is never added to wanted.txt


# --- the setup's failures and the audio's ---------------------------------------------------------------------------


def test_a_separator_that_cant_run_fails_the_job_and_records_nothing(conn, cfg):
    song = offered(conn, cfg)
    transcriber = Transcriber()
    result, heard = make(cfg, separator=Separator(fail="No possible adapter"), transcriber=transcriber)
    assert not result.ok and result.bug is None
    assert result.failed == "the separator can't run here (No possible adapter)"
    ends = heard.ends()
    assert ends["vocals"] == ("failed", result.failed)
    assert [ends[name][0] for name in ("words", "chords", "pdf", "pages")] == ["skipped"] * 3 + ["done"]
    assert transcriber.calls == []
    assert nothing_recorded(conn, song)
    assert why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) is None  # still offered


@pytest.mark.parametrize("said", [
    "the GPU failed: OutOfMemoryError: CUDA out of memory. Tried to allocate 20.00 MiB",
    "the GPU failed: RuntimeError: CUDA error: device-side assert triggered",
])
def test_a_gpu_failure_fails_the_job_records_nothing_and_the_song_stays_offered(conn, cfg, said):
    song = offered(conn, cfg)
    recognizer = Recognizer()
    result, heard = make(cfg, transcriber=Transcriber(fail=tx.SetupFailed(said)), recognizer=recognizer)
    assert not result.ok and result.bug is None and result.failed == said  # SetupFailed's own words, as they are
    ends = heard.ends()
    assert ends["words"] == ("failed", said)
    assert [ends[name][0] for name in ("chords", "pdf", "pages")] == ["skipped", "skipped", "done"]
    assert recognizer.calls == []
    assert nothing_recorded(conn, song)  # never filed as audio that can't be read
    assert why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) is None


def test_audio_whisper_cant_read_is_noted_as_whispers_and_the_job_says_what_to_do(conn, cfg):
    # Whisper reads the mix through the ffmpeg program: its refusal is no verdict on the file auto-chords reads. Noted
    # as Whisper's alone, as the nightly pass and a sheet from a video note it; never filed as audio auto-chords can't
    # read. The job fails in words that say what to do, and --force tries it again (an ffmpeg or Whisper upgrade).
    from caracole.autochords.transcript import WHISPER_CANT_READ

    song = offered(conn, cfg)
    fail = RuntimeError("Failed to load audio: [mov,mp4] moov atom not found")
    result, heard = make(cfg, transcriber=Transcriber(fail=fail))
    said = ("Whisper can't read the audio: a new file, or another video under [youtube], gets its words heard; after "
            "an ffmpeg or Whisper upgrade, caracole transcribe --force tries it again")
    assert not result.ok and result.bug is None and result.failed == said
    assert heard.ends()["words"] == ("failed", said)
    assert kv_get(conn, f"autochords:failed:{song.id}") is None
    record = kv_get_json(conn, f"{WHISPER_CANT_READ}{song.id}")
    assert (record["audio"], record["audio_mtime"]) == (song.audio_path, song.audio_mtime)
    assert record["error"] == "RuntimeError: Failed to load audio: [mov,mp4] moov atom not found"
    song = get_song(conn, song.id)
    assert why_not_offered(conn, cfg, song, Overrides()) == "Whisper can't read its audio"
    assert kept(conn, song) is None and not heard_nothing(conn, song)
    refused, _ = make(cfg)
    assert refused.refused == ("Nick Cani - Vikingos veganos isn't offered a transcription: Whisper can't read its "
                               "audio (a new file, or another video under [youtube], gets its words heard; after an "
                               "ffmpeg or Whisper upgrade, caracole transcribe --force tries it again)")
    again, _ = make(cfg, force=True)  # after an upgrade: heard now, and the note goes with its transcript
    assert again.ok, again
    assert kept(conn, song) is not None and kv_get(conn, f"{WHISPER_CANT_READ}{song.id}") is None


@pytest.mark.parametrize("fail", [IndexError("list index out of range"),
                                  RuntimeError("expected scalar type Half but found Float")], ids=["index", "runtime"])
def test_anything_else_whisper_raises_is_a_bug_that_files_nothing(conn, cfg, fail):
    # Only Whisper failing to load the audio is the audio's; a failure deep in Whisper, or in caracole, parks nothing.
    song = offered(conn, cfg)
    recognizer = Recognizer()
    result, heard = make(cfg, transcriber=Transcriber(fail=fail), recognizer=recognizer)
    assert not result.ok and result.failed is None
    assert result.bug == f"words: {type(fail).__name__}: {fail}"
    ends = heard.ends()
    assert ends["words"] == ("failed", f"a bug in caracole: {type(fail).__name__}: {fail}")
    assert [ends[name][0] for name in ("chords", "pdf", "pages")] == ["skipped", "skipped", "done"]
    assert recognizer.calls == []
    assert nothing_recorded(conn, song)
    assert why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) is None


@pytest.mark.parametrize("error", [
    RuntimeError("Error opening '1-XFkzRNyygfk.m4a': Format not recognised."),
    FileNotFoundError("audio file not found: 1-XFkzRNyygfk.m4a"),
    ValueError("buffer is too small"),
], ids=["undecodable", "missing", "other"])
def test_a_mix_the_loudness_reader_cant_read_files_nothing_and_the_song_stays_offered(conn, cfg, monkeypatch, error):
    # The reader's failure, of any kind, is no proof the audio is bad: only Whisper's own "Failed to load audio" is
    # filed. The job ends there, in the reader's words, before the separator runs.
    song = offered(conn, cfg)

    def frame_db(path, **kwargs):
        raise error

    monkeypatch.setattr(separate, "frame_db", frame_db)
    separator, transcriber = Separator(), Transcriber()
    result, heard = make(cfg, separator=separator, transcriber=transcriber)
    said = f"can't measure the audio here ({type(error).__name__}: {error})"
    assert not result.ok and result.bug is None and result.failed == said
    assert heard.ends()["vocals"] == ("failed", said)
    assert [heard.ends()[name][0] for name in ("words", "chords", "pdf", "pages")] == ["skipped"] * 3 + ["done"]
    assert separator.calls == transcriber.calls == []
    assert nothing_recorded(conn, song)
    assert why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) is None


def test_a_stem_that_cant_be_read_is_the_separators_failure_and_files_nothing(conn, cfg, monkeypatch):
    song = offered(conn, cfg)

    def frame_db(path, **kwargs):
        if Path(path).name == "vocals.wav":
            raise RuntimeError("Error opening 'vocals.wav': File contains data in an unknown format.")
        return list(MIX)

    monkeypatch.setattr(separate, "frame_db", frame_db)
    transcriber = Transcriber()
    result, heard = make(cfg, transcriber=transcriber)
    said = ("the separator can't run here (its vocals can't be read: RuntimeError: Error opening 'vocals.wav': File "
            "contains data in an unknown format.)")
    assert not result.ok and result.bug is None and result.failed == said
    assert heard.ends()["vocals"] == ("failed", said)
    assert transcriber.calls == []
    assert nothing_recorded(conn, song)
    assert why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) is None


@pytest.mark.autochords
@needs_aac
def test_a_song_whose_audio_is_the_aac_m4a_youtube_gives_is_transcribed(conn, cfg, monkeypatch):
    # The loudness read for real (separate.frame_db) on the AAC .m4a caracole keeps YouTube's audio as, and on the
    # stem demucs-rs writes (a WAV); demucs-rs, Whisper and auto-chords' models are the fakes.
    import soundfile

    monkeypatch.setattr(separate, "frame_db", REAL_FRAME_DB)
    song_of = [(1.0, 0.0), (11.0, 0.3)]  # a second's silence, then eleven of singing: enough to be sung
    song = offered(conn, cfg, seconds=12.0, audio=lambda path: aac_m4a(path.with_suffix(".m4a"), song_of))
    assert Path(song.audio_path).suffix == ".m4a"

    class Stem(Separator):
        def vocals(self, audio, workdir, **kwargs):
            self.calls.append((Path(audio), Path(workdir)))
            out = Path(workdir) / "stems" / "vocals.wav"
            out.parent.mkdir(parents=True)
            soundfile.write(out, aac_samples(song_of), AAC_RATE)
            return out

    words = [Word(0.0, 0.2, "Suscríbete", False, True),
             *(replace(w, start=w.start - 24.0, end=w.end - 24.0) for w in WORDS[1:9])]  # two lines, from 1.5 s
    transcriber = Transcriber(words)
    result, heard = make(cfg, separator=Stem(), transcriber=transcriber)
    assert result.ok, result
    ends = heard.ends()
    state, detail = ends["vocals"]
    assert state == "done" and detail.endswith(" s, 1 stretch"), detail
    assert 0.6 <= float(detail.removeprefix("sung from ").partition(" s")[0]) <= 1.0  # the singing from 1 s
    assert ends["words"] == ("done", "8 words in 2 lines (es), 1 dropped")
    assert ends["chords"] == ("done", "chords over the transcribed lyrics")
    assert kv_get(conn, f"autochords:failed:{song.id}") is None
    assert "Somos vikingos" in auto_sheet(cfg, conn, song).read_text(encoding="utf-8")


# --- the default models -----------------------------------------------------------------------------------------


class Built:
    """Which default model was built when, and what each was given, in order."""

    def __init__(self, monkeypatch, *, separator_fails: str | None = None, whisper_fails: Exception | None = None,
                 load_fails: Exception | None = None):
        self.log: list[tuple] = []
        built = self

        class Demucs(Separator):
            def __init__(self, binary, model, cache_dir, timeout=0.0):
                super().__init__()
                built.log.append(("demucs built", binary, model, cache_dir))

            def vocals(self, audio, workdir, **kwargs):
                built.log.append(("demucs", Path(audio).name))
                if separator_fails:
                    raise SeparatorFailed(separator_fails)
                return super().vocals(audio, workdir, **kwargs)

        class Whisper(Transcriber):
            def __init__(self, model_path, *, device, cache_dir):
                super().__init__()
                built.log.append(("whisper built", model_path, device, cache_dir))
                if load_fails is not None:
                    raise load_fails

            def hear(self, mix, stem, first_sung_s, **kwargs):
                built.log.append(("whisper", Path(mix).name))
                if whisper_fails is not None and Path(mix).name == "test-tone.wav":
                    raise whisper_fails
                return super().hear(mix, stem, first_sung_s, **kwargs)

        monkeypatch.setattr(separate, "DemucsSeparator", Demucs)
        monkeypatch.setattr(tx, "WhisperTranscriber", Whisper)
        monkeypatch.setattr(tx, "resolve_device", lambda setting: built.log.append(("device", setting)) or "cuda")


class Says(Heard):
    """The progress, which notes each stage as it starts, and what it says it does while it runs, in the same log as
    the models."""

    def __init__(self, log: list):
        super().__init__()
        self.log = log

    def stage(self, name, state, detail=""):
        super().stage(name, state, detail)
        if state == "running":
            self.log.append(("doing", name, detail) if detail else ("stage", name))


def default_models(cfg, tmp_path):
    from dataclasses import replace

    from caracole.config import AutochordsConfig

    files = {"whisper_model": tmp_path / "large-v3.pt", "separator_model": tmp_path / "htdemucs.safetensors"}
    return replace(cfg, demucs_bin="demucs-cpu", autochords=AutochordsConfig(**files, transcribe_device="auto"))


def make_with_defaults(cfg, built):
    heard = Says(built.log)
    result = make_transcript(cfg, TranscribeRequest("Nick Cani", "Vikingos veganos"), heard,
                             recognizer=Recognizer(), beats_fn=beats, runner=fake_chordpro, now=NOW)
    return result, heard


def test_the_default_models_are_built_at_their_first_stage_and_whisper_must_hear_a_tone_first(conn, cfg, tmp_path,
                                                                                             monkeypatch):
    # demucs-rs hears no tone: failing on the song is the setup's as failing on a tone would be, and each of its runs
    # costs about 30 s (measured: the results file of docs/superpowers/plans/).
    monkeypatch.delenv("CARACOLE_TORCH_CUDA", raising=False)  # on the CPU: the separator's pace there
    built = Built(monkeypatch)
    setup = default_models(cfg, tmp_path)
    song = offered(conn, setup)
    result, _ = make_with_defaults(setup, built)
    assert result.ok, result
    audio = Path(song.audio_path).name
    assert built.log == [
        ("stage", "song"),
        ("stage", "vocals"),
        ("demucs built", "demucs-cpu", tmp_path / "htdemucs.safetensors", setup.cache_dir),
        ("doing", "vocals", "~5 min"),
        ("demucs", audio),
        ("stage", "words"),
        ("doing", "words", "loading Whisper"),
        ("device", "auto"),
        ("whisper built", tmp_path / "large-v3.pt", "cuda", setup.cache_dir),
        ("whisper", "test-tone.wav"),
        ("doing", "words", "0:00 of 1:00"),
        ("whisper", audio),
        ("stage", "chords"),
        ("doing", "chords", "setting up the models"),
        ("doing", "chords", "hearing the chords"),
        ("doing", "chords", "finding the beats"),
        ("doing", "chords", "writing the sheet"),
        ("stage", "pdf"),
        ("stage", "pages"),
    ]


@pytest.mark.parametrize("fails,stage,said", [
    ({"separator_fails": "No possible adapter"}, "vocals", "the separator can't run here (No possible adapter)"),
    ({"load_fails": tx.SetupFailed("the GPU failed: OutOfMemoryError: CUDA out of memory")}, "words",
     "the GPU failed: OutOfMemoryError: CUDA out of memory"),
    ({"load_fails": tx.SetupFailed("Whisper's model won't load: RuntimeError: PytorchStreamReader failed")}, "words",
     "Whisper's model won't load: RuntimeError: PytorchStreamReader failed"),
    ({"whisper_fails": tx.SetupFailed("the GPU failed: RuntimeError: CUDA error: no kernel image")}, "words",
     "the GPU failed: RuntimeError: CUDA error: no kernel image"),
    ({"whisper_fails": RuntimeError("ffmpeg was not found")}, "words",
     "Whisper fails on a test tone: RuntimeError: ffmpeg was not found"),
], ids=["separator on the song", "GPU at load", "model at load", "GPU on the tone", "Whisper on the tone"])
def test_a_default_model_that_fails_on_the_tone_or_at_load_is_the_setups(conn, cfg, tmp_path, monkeypatch, fails,
                                                                         stage, said):
    built = Built(monkeypatch, **fails)
    setup = default_models(cfg, tmp_path)
    song = offered(conn, setup)
    result, heard = make_with_defaults(setup, built)
    assert not result.ok and result.bug is None and result.failed == said
    assert heard.ends()[stage] == ("failed", said)
    audio = Path(song.audio_path).name
    assert ("demucs", "test-tone.wav") not in built.log  # the separator is tried on the song alone
    assert ("whisper", audio) not in built.log  # a broken Whisper never heard the song
    assert nothing_recorded(conn, song)
    assert why_not_offered(conn, setup, get_song(conn, song.id), Overrides()) is None


# --- the lock ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("before,change,said", [
    ("words", with_lyrics, "Nick Cani - Vikingos veganos isn't offered a transcription: its lyrics are found"),
    ("chords", lambda conn, cfg, song: conn.execute("DELETE FROM songs"),
     "Nick Cani - Vikingos veganos left the book while its lyrics were transcribed (removed, or merged into a song "
     "of the same name)"),
    ("chords", keep_human_sheet, "Nick Cani - Vikingos veganos needs no sheet over its transcript now: has a human "
                                 "sheet"),
    ("chords", ignored, "Nick Cani - Vikingos veganos needs no sheet over its transcript now: ignored"),
], ids=["lyrics found before the words", "removed before the chords", "a human sheet before the chords",
        "ignored before the chords"])
@pytest.mark.parametrize("earlier", [False, True], ids=["no auto sheet before", "an auto sheet before"])
def test_a_song_a_lookup_changed_while_it_had_the_lock_ends_the_job_as_a_refusal(conn, cfg, monkeypatch, before,
                                                                                 change, said, earlier):
    # Before each long stage the job lets a waiting lookup have the lock; meanwhile the song may have found lyrics
    # (no longer offered), kept a human sheet (a terminal's `caracole get` found UG's chords), been ignored, or left
    # the book. The job ends there, a refusal, before the next model runs: never auto-chords' skip said as its own
    # failure ("made no sheet"), nor an earlier auto sheet said as Ready.
    from caracole.autochords.run import autochords_pending

    song = offered(conn, cfg)
    if earlier:  # a chart auto-chords made before, with no words
        autochords_pending(conn, cfg, recognizer=Recognizer(), beats_fn=beats, only={song.id})
    heard = Heard()
    monkeypatch.setattr(_common, "_handoffs", _common.handoffs())  # put back as it was after the test

    def hand_over(cfg_, conn_=None) -> bool:
        _common._handoffs += 1
        if heard.events[-1][1:3] == (before, "running"):
            change(conn_, cfg_, song)
        return True

    monkeypatch.setattr(_common, "hand_over", hand_over)
    made_before = auto_sheet(cfg, conn, song).exists()
    transcriber, recognizer = Transcriber(), Recognizer()
    result, _ = make(cfg, transcriber=transcriber, recognizer=recognizer, progress=heard)
    assert result.bug is None and result.failed is None and result.refused == said
    ends = heard.ends()
    assert ends["song"] == ("failed", said)
    assert all(ends[name][0] == "skipped" for name in ("chords", "pdf", "pages"))
    assert recognizer.calls == []
    assert (transcriber.calls == []) == (before == "words")
    assert auto_sheet(cfg, conn, song).exists() == made_before
    # Refused at the chords, its transcript is kept, and the job says so (the command's "Transcript kept; ...").
    assert result.transcript_kept == ("needs no sheet" in said)
    if result.transcript_kept:
        assert transcript_of(conn, get_song(conn, song.id)) is not None



def other_audio(conn, cfg, song):
    """Another video's audio for the song, as a `caracole youtube --sheet --url` that took the lock after the lookups
    would leave it."""
    other = "oNOFfl3Hx3s"
    audio = wav(cfg.cache_dir / "youtube" / f"{song.id}-{other}.wav", 60.0)
    update_song(conn, song.id, audio_path=str(audio), audio_mtime=audio.stat().st_mtime)
    _save(conn, song.id, Record(video=Video(other, song.title, "Nick Cani", 60.0), source="pasted", audio=str(audio)))


@pytest.mark.parametrize("before", ["words", "chords"])
def test_audio_replaced_while_the_job_let_others_have_the_lock_ends_it_as_a_refusal(conn, cfg, monkeypatch, before):
    # The stem and the sung spans are the old audio's: no transcript, nor a sheet over one, is made of them for the
    # new audio, which is offered a transcription of its own.
    song = offered(conn, cfg)
    heard = Heard()
    monkeypatch.setattr(_common, "_handoffs", _common.handoffs())  # put back as it was after the test

    def hand_over(cfg_, conn_=None) -> bool:
        _common._handoffs += 1
        if heard.events[-1] == ("stage", before, "running", ""):
            other_audio(conn_, cfg_, song)
        return True

    monkeypatch.setattr(_common, "hand_over", hand_over)
    transcriber, recognizer = Transcriber(), Recognizer()
    result, _ = make(cfg, transcriber=transcriber, recognizer=recognizer, progress=heard)
    said = "Nick Cani - Vikingos veganos: its audio changed while its lyrics were transcribed"
    assert result.bug is None and result.failed is None and result.refused == said
    ends = heard.ends()
    assert ends["song"] == ("failed", said)
    assert all(ends[name][0] == "skipped" for name in ("chords", "pdf", "pages"))
    assert recognizer.calls == [] and not auto_sheet(cfg, conn, song).exists()
    assert (transcriber.calls == []) == (before == "words")
    now = get_song(conn, song.id)
    assert transcript_of(conn, now) is None and not heard_nothing(conn, now)
    assert kv_get(conn, f"autochords:failed:{song.id}") is None
    assert why_not_offered(conn, cfg, now, Overrides()) is None


LOOKUP = r"""
import sys
from pathlib import Path
from caracole.commands import _common
from caracole.config import load_config

cfg = load_config(Path(sys.argv[1]))
with _common.exclusive(cfg, "get Nick Cani - Vikingos veganos", lane=True):
    with open(sys.argv[2], "a", encoding="utf-8") as log:
        log.write("lookup\n")
"""


@pytest.mark.slow
def test_the_lock_goes_to_a_waiting_lookup_before_each_long_stage(conn, cfg, tmp_path):
    # The separator, Whisper and auto-chords take minutes each: a lookup asked meanwhile goes before each of them.
    offered(conn, cfg)
    config = tmp_path / "caracole.toml"
    config.write_text(f'state_dir = "{cfg.state_dir}"\ncache_dir = "{cfg.cache_dir}"\n'
                      f'library_dir = "{cfg.library_dir}"\n', encoding="utf-8")
    log = tmp_path / "order.log"
    env = {**os.environ, "PYTHONPATH": subprocess_pythonpath(Path(__file__).parents[1] / "src")}
    lookups: list[subprocess.Popen] = []

    class Asked(Heard):
        def stage(self, name, state, detail=""):
            super().stage(name, state, detail)
            if state == "running" and not detail and name in ("vocals", "words", "chords"):  # as each starts, a
                # lookup asks for the lock
                lookup = subprocess.Popen([sys.executable, "-c", LOOKUP, str(config), str(log)], env=env)
                lookups.append(lookup)
                assert waiting_for(cfg.state_dir / _common.LOCK_NAME, lambda: lookup.poll() is None)

    class Noted:
        """Where each model notes that it runs: the log the lookups write too."""

        def append(self, what):
            with open(log, "a", encoding="utf-8") as out:
                out.write(what + "\n")

    class Recognized(Recognizer):
        def recognize(self, path):
            Noted().append("recognizer")
            return super().recognize(path)

    handed = _common.handoffs()
    try:
        result, _ = make(cfg, separator=Separator(log=Noted()), transcriber=Transcriber(log=Noted()),
                         recognizer=Recognized(), progress=Asked())
        assert [lookup.wait(30) for lookup in lookups] == [0, 0, 0]
    finally:
        for lookup in lookups:
            lookup.kill()
    assert result.ok, result
    order = log.read_text(encoding="utf-8").splitlines()
    assert order == ["lookup", "separator", "lookup", "transcriber", "lookup", "recognizer"]
    assert _common.handoffs() == handed + 3


# --- the owner's word over caracole's: --force and --none -----------------------------------------------------------


def test_force_hears_a_song_heard_to_have_nothing_and_keeps_its_words(conn, cfg):
    # Five words over a song's worth of singing: nothing sung, by caracole's rule. The owner says it is sung: Whisper's
    # words are kept all the same, within the singing, and the sheet is made over them.
    song = offered(conn, cfg)
    first, _ = make(cfg, transcriber=Transcriber(WORDS[:6]))
    assert first.failed == "no singing heard" and heard_nothing(conn, song)
    assert why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) == "nothing sung was heard"
    recognizer = Recognizer()
    result, heard = make(cfg, transcriber=Transcriber(WORDS[:6]), recognizer=recognizer, force=True)
    assert result.ok, result
    ends = heard.ends()
    assert ends["words"] == ("done", "5 words in 2 lines (es), 1 dropped")
    assert ends["chords"] == ("done", "chords over the transcribed lyrics")
    transcript = kept(conn, song)
    assert transcript is not None and transcript.lrc.startswith("[00:25.50] <00:25.50>Somos")
    assert not heard_nothing(conn, get_song(conn, song.id)) and recognizer.calls
    assert NOTE in auto_sheet(cfg, conn, song).read_text(encoding="utf-8")


def test_force_hears_the_whole_song_where_no_singing_was_found(conn, cfg, monkeypatch):
    # The separator found no singing at all: Whisper isn't run by caracole's rule; asked anyway, it hears the whole
    # song, its words kept, the intro's too, as one span.
    monkeypatch.setattr(separate, "frame_db", lambda path, **kwargs: [-80.0] * 1200 if Path(path).name == "vocals.wav"
                        else list(MIX))
    song = offered(conn, cfg)
    transcriber = Transcriber()
    result, heard = make(cfg, transcriber=transcriber, force=True)
    assert result.ok, result
    assert heard.ends()["vocals"] == ("done", "no singing found") and transcriber.calls
    assert heard.ends()["words"] == ("done", "17 words in 5 lines (es), 0 dropped")
    assert kept(conn, song) is not None


def test_none_drops_the_transcript_and_makes_the_chords_alone(conn, cfg):
    # Whisper's words over a pad passed the rules: the owner says it isn't sung. Its transcript goes, the song noted
    # not sung by their word, and its sheet is made again of its chords alone; neither model runs.
    from caracole.autochords.transcript import NOT_SUNG, SAID_NOT_SUNG, SILENT

    song = offered(conn, cfg)
    assert make(cfg)[0].ok and kept(conn, song) is not None
    separator, transcriber, recognizer = Separator(), Transcriber(), Recognizer()
    result, heard = make(cfg, separator=separator, transcriber=transcriber, recognizer=recognizer, none=True)
    assert result.ok, result
    ends = heard.ends()
    assert ends["song"] == ("done", "in the book")
    assert ends["vocals"] == ("skipped", "you said nothing is sung")
    assert ends["words"] == ("done", "transcript dropped")
    assert ends["chords"] == ("done", "chords only: you said it isn't sung")  # the owner's word, not what was heard
    assert ends["pdf"] == ("done", "made")
    assert separator.calls == transcriber.calls == [] and recognizer.calls
    assert kept(conn, song) is None and not result.transcript_kept
    noted = kv_get_json(conn, f"{HEARD_NOTHING}{song.id}")
    assert (noted["why"], noted["by"]) == ("you said so", "you")
    song = get_song(conn, song.id)
    sheet = auto_sheet(cfg, conn, song).read_text(encoding="utf-8")
    assert NOTE not in sheet and NOT_SUNG in sheet and SILENT not in sheet and "Somos" not in sheet
    assert why_not_offered(conn, cfg, song, Overrides()) == SAID_NOT_SUNG
    assert why_not_offered(conn, cfg, song, Overrides(), anyway=True) is None  # until the owner says it is
    # Their word is about that audio: a new file is a new start, offered a transcription again.
    other = Path(song.audio_path).with_name("other.wav")
    wav(other, 60.0)
    update_song(conn, song.id, audio_path=str(other), audio_mtime=other.stat().st_mtime)
    assert why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) is None


def test_none_is_refused_for_a_song_with_no_transcript_and_changes_nothing(conn, cfg):
    song = offered(conn, cfg)
    separator, transcriber, recognizer = Separator(), Transcriber(), Recognizer()
    result, heard = make(cfg, separator=separator, transcriber=transcriber, recognizer=recognizer, none=True)
    assert result.refused == "Nick Cani - Vikingos veganos can't be said not sung: it has no transcript"
    assert heard.ends()["song"] == ("failed", result.refused)
    assert separator.calls == transcriber.calls == recognizer.calls == []
    assert kv_get(conn, f"{HEARD_NOTHING}{song.id}") is None
    assert why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) is None


def test_transcribe_anyway_over_audio_whisper_cant_read_leaves_no_offer_over_that_file(conn, cfg, monkeypatch):
    # Too little singing: caracole noted nothing sung, Whisper never run. Transcribe anyway: Whisper can't load the
    # file. Its verdict of nothing sung goes with it, so the card offers no Transcribe anyway that can only fail
    # again; asked again, the refusal says what to do.
    from caracole.autochords.transcript import offers

    monkeypatch.setattr(separate, "frame_db", lambda path, **kwargs: [-80.0] * 1200 if Path(path).name == "vocals.wav"
                        else list(MIX))
    song = offered(conn, cfg)
    assert make(cfg)[0].failed == "no singing heard" and offers(conn, cfg, Overrides())["nothing"] == [song.id]
    fail = RuntimeError("Failed to load audio: [mov,mp4] moov atom not found")
    result, _ = make(cfg, transcriber=Transcriber(fail=fail), force=True)
    assert result.failed.startswith("Whisper can't read the audio: a new file")
    song = get_song(conn, song.id)
    assert not heard_nothing(conn, song)
    assert offers(conn, cfg, Overrides()) == {"songs": [], "nothing": [], "unsung": [], "transcribed": []}
    refused, _ = make(cfg)
    assert refused.refused.endswith("Whisper can't read its audio (a new file, or another video under [youtube], gets "
                                    "its words heard; after an ffmpeg or Whisper upgrade, caracole transcribe --force "
                                    "tries it again)")
