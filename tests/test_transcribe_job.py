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
from caracole.transcribe_job import STAGES, TranscribeRequest, make_transcript
from caracole.youtube import Video
from caracole.youtube_fetch import Record, _save

NOW = datetime(2026, 11, 20, 21, 0, tzinfo=UTC)
VIDEO = "XFkzRNyygfk"
# 50 ms frames: the stem silent through the intro's 25 s, then sung to the minute's end; the mix loud throughout.
STEM = [-80.0] * 500 + [-12.0] * 700
MIX = [-10.0] * 1200
REAL_FRAME_DB = separate.frame_db  # the autouse ``loudness`` fakes it; a test of the real reader puts it back
INTRO = Word(0.0, 0.4, "Suscríbete", False, True)  # Whisper's own, over the intro nobody sings
WORDS = [
    INTRO,
    Word(25.5, 26.0, "Somos", True, True),
    Word(26.1, 26.6, "vikingos", True),
    Word(26.7, 27.0, "de", True),
    Word(27.1, 27.6, "prueba", True),
    Word(30.0, 30.5, "comemos", True, True),
    Word(30.6, 31.0, "lechuga", True),
]
LRC = ("[00:25.50] <00:25.50>Somos <00:26.10>vikingos <00:26.70>de <00:27.10>prueba\n"
       "[00:27.60]\n"
       "[00:30.00] <00:30.00>comemos <00:30.60>lechuga\n")


class Separator:
    """demucs-rs: a vocal stem written under the work folder it is given; the audio never listened to."""

    def __init__(self, *, fail: str | None = None, log: list | None = None):
        self.calls: list[tuple[Path, Path]] = []
        self.fail, self.log = fail, log

    def vocals(self, audio, workdir):
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

    def hear(self, mix, stem, first_sung_s):
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
         title="Vikingos veganos"):
    heard = progress or Heard()
    result = make_transcript(cfg, TranscribeRequest(artist, title), heard,
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
    assert ends["words"] == ("done", "6 words in 2 lines (es), 1 dropped")
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


def test_words_outside_the_singing_are_dropped(conn, cfg):
    song = offered(conn, cfg)
    result, heard = make(cfg)
    assert result.ok
    transcript = kept(conn, song)
    assert transcript.words_dropped == 1 and "Suscríbete" not in transcript.lrc
    assert "Suscríbete" not in auto_sheet(cfg, conn, song).read_text(encoding="utf-8")
    assert heard.ends()["words"][1].endswith(", 1 dropped")


@pytest.mark.parametrize("words", [[], [INTRO]], ids=["nothing heard", "only the intro"])
def test_no_singing_heard_records_it_and_fails_without_a_sheet(conn, cfg, words):
    song = offered(conn, cfg)
    recognizer = Recognizer()
    result, heard = make(cfg, transcriber=Transcriber(words), recognizer=recognizer)
    assert not result.ok and result.failed == "no singing heard" and result.bug is None
    ends = heard.ends()
    assert ends["words"] == ("failed", "no singing heard")
    assert [ends[name][0] for name in ("chords", "pdf", "pages")] == ["skipped", "skipped", "done"]
    assert recognizer.calls == [] and not auto_sheet(cfg, conn, song).exists()
    assert kept(conn, song) is None
    # Not offered again until the song's audio changes.
    assert heard_nothing(conn, song)
    assert why_not_offered(conn, cfg, song, Overrides()) == "nothing sung was heard"



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
    assert heard.ends()["words"] == ("done", "6 words in 2 lines (es), 1 dropped")
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


def test_with_no_singing_found_whisper_never_runs_and_nothing_sung_is_noted(conn, cfg, monkeypatch):
    # The guard would drop every word Whisper heard: it isn't run (up to half an hour on a CPU).
    song = offered(conn, cfg)
    monkeypatch.setattr(separate, "frame_db",
                        lambda path, **kw: [-80.0] * 1200 if Path(path).name == "vocals.wav" else list(MIX))
    transcriber, recognizer = Transcriber(), Recognizer()
    result, heard = make(cfg, transcriber=transcriber, recognizer=recognizer)
    assert not result.ok and result.failed == "no singing heard" and result.bug is None
    ends = heard.ends()
    assert ends["vocals"] == ("done", "no singing found")
    assert ends["words"] == ("failed", "no singing heard")
    assert transcriber.calls == [] and recognizer.calls == []
    assert heard_nothing(conn, song) and kept(conn, song) is None

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


def filed_unreadable(conn, cfg, song) -> bool:
    """Whether the song's audio is filed as auto-chords files a file it can't read, and so offered no transcription
    until it changes."""
    record = kv_get_json(conn, f"autochords:failed:{song.id}")
    return (record["audio"], record["audio_mtime"]) == (song.audio_path, song.audio_mtime) and (
        why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) == "its audio can't be read")


def test_audio_whisper_cant_read_is_filed_as_auto_chords_files_it(conn, cfg):
    song = offered(conn, cfg)
    fail = RuntimeError("Failed to load audio: [mov,mp4] moov atom not found")
    result, heard = make(cfg, transcriber=Transcriber(fail=fail))
    assert not result.ok and result.bug is None and result.failed == "can't read the audio"
    assert heard.ends()["words"] == ("failed", "can't read the audio")
    assert filed_unreadable(conn, cfg, song)
    assert kv_get_json(conn, f"autochords:failed:{song.id}")["error"] == (
        "RuntimeError: Failed to load audio: [mov,mp4] moov atom not found")
    assert kept(conn, song) is None and not heard_nothing(conn, song)


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
    song_of = [(1.0, 0.0), (3.0, 0.3)]  # a second's silence, then three of singing
    song = offered(conn, cfg, seconds=4.0, audio=lambda path: aac_m4a(path.with_suffix(".m4a"), song_of))
    assert Path(song.audio_path).suffix == ".m4a"

    class Stem(Separator):
        def vocals(self, audio, workdir):
            self.calls.append((Path(audio), Path(workdir)))
            out = Path(workdir) / "stems" / "vocals.wav"
            out.parent.mkdir(parents=True)
            soundfile.write(out, aac_samples(song_of), AAC_RATE)
            return out

    words = [Word(0.0, 0.2, "Suscríbete", False, True), Word(1.5, 2.0, "Somos", True, True),
             Word(2.1, 2.8, "vikingos", True)]
    transcriber = Transcriber(words)
    result, heard = make(cfg, separator=Stem(), transcriber=transcriber)
    assert result.ok, result
    ends = heard.ends()
    state, detail = ends["vocals"]
    assert state == "done" and detail.endswith(" s, 1 stretch"), detail
    assert 0.6 <= float(detail.removeprefix("sung from ").partition(" s")[0]) <= 1.0  # the singing from 1 s
    assert ends["words"] == ("done", "2 words in 1 line (es), 1 dropped")
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

            def vocals(self, audio, workdir):
                built.log.append(("demucs", Path(audio).name))
                if separator_fails:
                    raise SeparatorFailed(separator_fails)
                return super().vocals(audio, workdir)

        class Whisper(Transcriber):
            def __init__(self, model_path, *, device, cache_dir):
                super().__init__()
                built.log.append(("whisper built", model_path, device, cache_dir))
                if load_fails is not None:
                    raise load_fails

            def hear(self, mix, stem, first_sung_s):
                built.log.append(("whisper", Path(mix).name))
                if whisper_fails is not None and Path(mix).name == "test-tone.wav":
                    raise whisper_fails
                return super().hear(mix, stem, first_sung_s)

        monkeypatch.setattr(separate, "DemucsSeparator", Demucs)
        monkeypatch.setattr(tx, "WhisperTranscriber", Whisper)
        monkeypatch.setattr(tx, "resolve_device", lambda setting: built.log.append(("device", setting)) or "cuda")


class Says(Heard):
    """The progress, which notes each stage as it starts in the same log as the models."""

    def __init__(self, log: list):
        super().__init__()
        self.log = log

    def stage(self, name, state, detail=""):
        super().stage(name, state, detail)
        if state == "running":
            self.log.append(("stage", name))


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
        ("demucs", audio),
        ("stage", "words"),
        ("device", "auto"),
        ("whisper built", tmp_path / "large-v3.pt", "cuda", setup.cache_dir),
        ("whisper", "test-tone.wav"),
        ("whisper", audio),
        ("stage", "chords"),
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
    ("chords", keep_human_sheet, "Nick Cani - Vikingos veganos isn't offered a transcription: has a human sheet"),
    ("chords", ignored, "Nick Cani - Vikingos veganos isn't offered a transcription: ignored"),
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
            if state == "running" and name in ("vocals", "words", "chords"):  # a lookup asks for the lock now
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
