"""audio_sheet.py: a song's auto sheet from an audio file you give it, now, stage by stage.

The file is one of helpers/audio_files.py's (silence of a length mutagen reads); LRCLIB, Megalobiz, AZLyrics and ntfy
fakes behind ``_common.transport_for``; auto-chords' models test_youtube_sheet.py's fake recognizer and beats, demucs-rs
and Whisper its ``Ears``, and chordpro ``fake_chordpro``: nothing reaches the network, and no model runs.
"""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from conftest import add_song
from helpers.audio_files import audio, write
from helpers.azlyrics_site import FakeAzLyrics
from helpers.megalobiz_site import FakeMegalobiz
from helpers.rendered import fake_chordpro
from test_youtube_sheet import Ears, Heard, Lrclib, Ntfy, Recognizer, beats, keep_human_sheet, record, wav

from caracole import audio_store
from caracole import youtube_fetch as yf
from caracole.audio_sheet import STAGES, AudioRequest, make_audio_sheet, names_of
from caracole.autochords.transcript import transcript_of
from caracole.commands import _common
from caracole.config import AutochordsConfig
from caracole.library import song_dir
from caracole.lyrics import Lyrics
from caracole.overrides import Overrides
from caracole.songs import find_song, get_song, update_song
from caracole.youtube import Video
from caracole.youtube_fetch import Record, _save, load_record, youtube_audio

NOW = datetime(2026, 11, 25, 20, 0, tzinfo=UTC)
VIDEO = "lzN7Thn3FV4"
NICK = ("Nick Cani", "Vikingos veganos")


@pytest.fixture(autouse=True)
def room(monkeypatch):
    """Room on the disk for every file kept (audio_store's ``ROOM`` is a GiB)."""
    monkeypatch.setattr(audio_store, "disk_usage", lambda path: SimpleNamespace(total=10**15, used=0, free=10**15))


@pytest.fixture
def sites(monkeypatch):
    """LRCLIB with the song's timed lyrics (200 s), Megalobiz and AZLyrics with none, ntfy: every request kept."""
    lrclib, ntfy, megalobiz, azlyrics = Lrclib(record(200.0)), Ntfy(), FakeMegalobiz(), FakeAzLyrics({})

    def transport(provider):
        handlers = {"lrclib": lrclib.handler, "ntfy": ntfy.handler, "megalobiz": megalobiz.handler,
                    "azlyrics": azlyrics.handler}
        if provider not in handlers:
            pytest.fail(f"a client for {provider} was made")
        return httpx.MockTransport(handlers[provider])

    monkeypatch.setattr(_common, "transport_for", transport)
    monkeypatch.setattr(_common, "sleep", lambda s: None)
    return lrclib


@pytest.fixture
def setup(cfg, tmp_path, monkeypatch):
    """The config: model files (unread), auto-chords and Whisper taken to be there, and demucs-rs not, so a sheet hears
    no words unless its test says so (``hears=True``), as test_youtube_sheet.py's ``setup``; no yt-dlp at all."""
    find_spec = importlib.util.find_spec
    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *args: object() if name == "whisper" else find_spec(name, *args))
    files = {"btc_weights": tmp_path / "btc.pt", "beat_checkpoint": tmp_path / "final0.ckpt",
             "whisper_model": tmp_path / "large-v3.pt", "separator_model": tmp_path / "htdemucs.safetensors"}
    for path in files.values():
        path.write_bytes(b"model")
    return replace(cfg, ytdlp_bin=str(tmp_path / "no-yt-dlp-here"), demucs_bin=str(tmp_path / "no-demucs-here"),
                   autochords=AutochordsConfig(**files))


@pytest.fixture
def ears(monkeypatch):
    return Ears(monkeypatch)


def a_file(tmp_path, seconds=200.0, name="vikingos.wav", **tags) -> Path:
    return write(tmp_path / "mine" / name, "WAV", seconds, **tags)


def make(cfg, request, *, recognizer=None, ears=None, hears=None, progress=None):
    heard = progress or Heard()
    result = make_audio_sheet(cfg, request, heard, runner=fake_chordpro, recognizer=recognizer or Recognizer(),
                              beats_fn=beats, separator=ears.separator if ears else None,
                              transcriber=ears.transcriber if ears else None, hears=hears, now=NOW)
    return result, heard


def the_song(conn):
    from caracole.normalize import identity_key

    return find_song(conn, identity_key(*NICK))


def auto_sheet(cfg, conn) -> str:
    return (song_dir(cfg.library_dir, the_song(conn)) / "sheet (auto).txt").read_text(encoding="utf-8")


def kept_files(cfg) -> list[str]:
    folder = cfg.state_dir / "audio"
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


# --- the whole way ---------------------------------------------------------------------------------------------


def test_a_new_song_gets_its_sheet_from_the_file_stage_by_stage(setup, conn, sites, tmp_path):
    lrclib = sites
    given = a_file(tmp_path)
    recognizer = Recognizer()
    result, heard = make(setup, AudioRequest(*NICK, file=given, album="Pruebas", duration=200.0),
                         recognizer=recognizer)
    assert result.ok, result
    assert [name for name, _ in STAGES] == ["song", "audio", "lyrics", "vocals", "words", "chords", "pdf", "pages"]
    assert dict(STAGES)["audio"] == "Your audio file"
    assert [e[1] for e in heard.events if e[0] == "stage" and e[2] != "running"] == [name for name, _ in STAGES]
    ends = heard.ends()
    assert ends["song"] == ("done", "added to wanted.txt, line 16")
    assert ends["audio"] == ("done", "kept as its audio: WAV, 3:20")
    assert ends["lyrics"] == ("done", "found, timed")
    assert ends["vocals"] == ("skipped", "not transcribed: its lyrics are found")
    assert ends["words"] == ("skipped", "no vocals")
    assert ends["chords"] == ("done", "chords over the lyrics")
    assert ends["pdf"] == ("done", "made")
    # The song's line holds the file's album and length, so LRCLIB is asked with the file's length.
    assert "Nick Cani - Vikingos veganos | Pruebas | 3:20" in setup.wanted_file.read_text(encoding="utf-8")
    assert lrclib.requests[0] == ("get", {"artist_name": "Nick Cani", "track_name": "Vikingos veganos",
                                          "album_name": "Pruebas", "duration": "200"})
    # The file is copied into caracole's own folder, the song's audio now, and the chords are made of that copy.
    song = the_song(conn)
    kept = audio_store.uploaded(setup, song)
    assert kept is not None and kept.read_bytes() == given.read_bytes() and given.exists()
    assert recognizer.calls == [kept]
    lines = auto_sheet(setup, conn).splitlines()
    assert lines[:2] == ["auto-generated, unverified", "Nick Cani - Vikingos veganos"]
    assert not any(line.startswith("Audio from YouTube") for line in lines)
    assert lines[lines.index("Somos vikingos de prueba") - 1].startswith("[ch]D[/ch]")
    folder = song_dir(setup.library_dir, song)
    assert (folder / "sheet (auto).html").is_file() and (folder / "sheet (auto).pdf").is_file()
    assert ("song", song.id, "Nick Cani - Vikingos veganos") in heard.events
    assert (setup.library_dir / "index.html").is_file()


def test_an_upload_is_moved_into_place(setup, conn, sites, tmp_path):
    up = audio_store.stage(setup, audio("MP3", 200.0), "Vikingos.mp3", named=())
    result, heard = make(setup, AudioRequest(*NICK, upload=up.id))
    assert result.ok, result
    assert heard.ends()["audio"] == ("done", "kept as its audio: MP3, 3:20")
    kept = audio_store.uploaded(setup, the_song(conn))
    assert kept is not None and kept.name == f"{the_song(conn).id}-{up.sha256[:16]}.mp3"
    assert set(kept_files(setup)) == {kept.name, f".upload-{up.id}.kept"}  # moved: its marker alone stays
    with pytest.raises(audio_store.AudioError):
        audio_store.staged(setup, up.id)


def test_youtube_audio_is_replaced_and_its_file_let_go(setup, conn, sites, tmp_path):
    song = add_song(conn, *NICK, duration_ms=200000)
    youtubes = wav(setup.cache_dir / "youtube" / f"{song.id}-{VIDEO}.wav", 200.0)
    _save(conn, song.id, Record(video=Video(VIDEO, "Vikingos veganos", "HyperFanes", 200.0), source="pasted",
                                audio=str(youtubes)))
    update_song(conn, song.id, audio_path=str(youtubes), audio_mtime=youtubes.stat().st_mtime)
    assert youtube_audio(conn, get_song(conn, song.id)) is not None
    recognizer = Recognizer()
    result, heard = make(setup, AudioRequest(*NICK, file=a_file(tmp_path)), recognizer=recognizer)
    assert result.ok, result
    assert heard.ends()["song"] == ("done", "in the book")
    assert heard.ends()["audio"] == ("done", "kept as its audio: WAV, 3:20; it replaces YouTube's audio as the "
                                             "song's source")
    song = get_song(conn, song.id)
    kept = audio_store.uploaded(setup, song)
    assert kept is not None and recognizer.calls == [kept]
    assert youtube_audio(conn, song) is None  # YouTube's file is no longer the song's own
    assert not any(line.startswith("Audio from YouTube") for line in auto_sheet(setup, conn).splitlines())
    # The next youtube tidy (the nightly step's, or caracole youtube's) lets go of YouTube's file.
    assert youtubes.exists()
    yf.tidy(conn, setup, Overrides())
    assert not youtubes.exists() and load_record(conn, song.id).audio is None
    assert get_song(conn, song.id).audio_path == str(kept)


def test_a_file_takes_a_purchases_place(setup, conn, sites, tmp_path):
    # The owner's decision of 2026-11-25: an upload always wins, a song with a purchase linked is no refusal. The file
    # given is the song's audio from now on; the purchase's file in Music/ is never touched.
    song = add_song(conn, *NICK, duration_ms=200000)
    bought = wav(setup.music_dir / "Nick Cani - Vikingos veganos.wav", 200.0)
    before = bought.read_bytes()
    update_song(conn, song.id, audio_path=str(bought), audio_mtime=bought.stat().st_mtime)
    recognizer = Recognizer()
    result, heard = make(setup, AudioRequest(*NICK, file=a_file(tmp_path, 201.0)), recognizer=recognizer)
    assert result.ok, result
    assert heard.ends()["audio"] == ("done", "kept as its audio: WAV, 3:21; it replaces the bought audio (its file "
                                             "in Music/ stays) as the song's source")
    kept = audio_store.uploaded(setup, get_song(conn, song.id))
    assert kept is not None and recognizer.calls == [kept]
    assert bought.read_bytes() == before


def test_a_file_given_again_replaces_the_one_given_before(setup, conn, sites, tmp_path):
    assert make(setup, AudioRequest(*NICK, file=a_file(tmp_path)))[0].ok
    first = audio_store.uploaded(setup, the_song(conn))
    result, heard = make(setup, AudioRequest(*NICK, file=a_file(tmp_path, 199.0, "other.wav")))
    assert result.ok, result
    assert heard.ends()["audio"] == ("done", "kept as its audio: WAV, 3:19; it replaces the file given before as "
                                             "the song's source")
    assert heard.ends()["chords"] == ("done", "chords over the lyrics")  # made again, of the new file
    now = audio_store.uploaded(setup, the_song(conn))
    assert now != first and kept_files(setup) == [now.name]


def test_the_same_file_again_is_up_to_date(setup, conn, sites, tmp_path):
    given = a_file(tmp_path)
    assert make(setup, AudioRequest(*NICK, file=given))[0].ok
    kept = audio_store.uploaded(setup, the_song(conn))
    recognizer = Recognizer()
    result, heard = make(setup, AudioRequest(*NICK, file=given), recognizer=recognizer)
    assert result.ok, result
    assert heard.ends()["audio"] == ("done", "has this file's audio already")
    assert heard.ends()["lyrics"] == ("done", "already there")
    assert heard.ends()["chords"] == ("done", "up to date: chords over the lyrics")
    assert recognizer.calls == [] and kept_files(setup) == [kept.name]


# --- refused: nothing kept, nothing asked ------------------------------------------------------------------


@pytest.mark.parametrize("case,said", [
    ("human", "Nick Cani - Vikingos veganos already has a sheet"),
    ("ignored", "Nick Cani - Vikingos veganos is ignored (overrides.toml)"),
])
def test_a_song_ignored_or_with_a_human_sheet_is_refused(setup, conn, sites, tmp_path, case, said):
    song = add_song(conn, *NICK)
    if case == "human":
        keep_human_sheet(conn, setup, song)
    else:
        setup.overrides_file.parent.mkdir(parents=True, exist_ok=True)
        setup.overrides_file.write_text('[ignore]\nsongs = ["Nick Cani - Vikingos veganos"]\n', encoding="utf-8")
    recognizer = Recognizer()
    result, heard = make(setup, AudioRequest(*NICK, file=a_file(tmp_path)), recognizer=recognizer)
    assert not result.ok and result.refused == said
    assert heard.ends()["song"] == ("failed", said)
    assert all(heard.ends()[name][0] == "skipped" for name, _ in STAGES[1:])
    assert kept_files(setup) == [] and get_song(conn, song.id).audio_path is None
    assert sites.requests == [] and recognizer.calls == []


def test_a_human_sheet_kept_as_the_models_let_a_lookup_go_first_ends_the_sheet_as_a_refusal(setup, conn, sites,
                                                                                         tmp_path, monkeypatch):
    # Before the chords a waiting lookup goes first; one that kept UG's chords meanwhile ends the sheet there, a
    # refusal, and the models run on nothing.
    monkeypatch.setattr(_common, "_handoffs", _common.handoffs())  # put back as it was after the test

    def hand_over(cfg_, conn_=None) -> bool:
        _common._handoffs += 1
        keep_human_sheet(conn_, cfg_, the_song(conn_))
        return True

    monkeypatch.setattr(_common, "hand_over", hand_over)
    recognizer = Recognizer()
    result, heard = make(setup, AudioRequest(*NICK, file=a_file(tmp_path)), recognizer=recognizer)
    assert result.bug is None and result.failed is None
    assert result.refused == "Nick Cani - Vikingos veganos already has a sheet"
    assert [heard.ends()[name][0] for name in ("chords", "pdf", "pages")] == ["skipped"] * 3
    assert recognizer.calls == []


# --- what fails ------------------------------------------------------------------------------------------


def test_a_file_caracole_doesnt_read_fails_and_nothing_is_kept(setup, conn, sites, tmp_path):
    fake = tmp_path / "mine" / "vikingos.mp3"
    fake.parent.mkdir(parents=True)
    fake.write_bytes(b"not really audio, whatever its name says" * 10)
    recognizer = Recognizer()
    result, heard = make(setup, AudioRequest(*NICK, file=fake), recognizer=recognizer)
    said = "not an audio file caracole reads (MP3, M4A, FLAC, WAV, Ogg or AIFF)"  # as a stage says it
    assert not result.ok and result.failed == said
    assert heard.ends()["audio"] == ("failed", said)
    assert heard.ends()["chords"] == ("skipped", "no audio") and heard.ends()["pdf"][0] == "skipped"
    assert kept_files(setup) == [] and the_song(conn).audio_path is None and recognizer.calls == []


def test_an_upload_gone_fails(setup, conn, sites):
    result, heard = make(setup, AudioRequest(*NICK, upload="0123456789abcdef"))
    assert not result.ok and result.failed == ("that upload is gone: it was left over an hour, or another file was "
                                               "chosen since. Choose it again")
    assert heard.ends()["audio"] == ("failed", result.failed)


def test_audio_auto_chords_cant_read_fails(setup, conn, sites, tmp_path):
    result, heard = make(setup, AudioRequest(*NICK, file=a_file(tmp_path)), recognizer=Recognizer(fail=True))
    assert not result.ok and result.failed == "auto-chords can't read the audio"
    assert heard.ends()["chords"][0] == "failed" and heard.ends()["pdf"][0] == "skipped"


def test_a_sites_wait_is_no_failure(setup, conn, sites, tmp_path, monkeypatch):
    monkeypatch.setattr(sites, "handler", lambda request: httpx.Response(503, text="Service Unavailable"))
    result, heard = make(setup, AudioRequest(*NICK, file=a_file(tmp_path)))
    assert result.ok, result
    assert heard.ends()["lyrics"] == ("failed", "no lyrics yet (LRCLIB unavailable); tried again tonight")
    assert heard.ends()["chords"] == ("done", "chords only, no lyrics")


# --- the words heard from the file, where no site has them ------------------------------------------------


def test_words_are_heard_before_the_chords(setup, conn, sites, ears, tmp_path):
    # The owner's rule: the lyrics sites are asked first, and only once every one missed are the words heard from the
    # file; the chords are then made once, over them.
    from test_transcribe_job import SAID

    sites.records.clear()
    recognizer = Recognizer()
    result, heard = make(setup, AudioRequest(*NICK, file=a_file(tmp_path)), recognizer=recognizer, ears=ears,
                         hears=True)
    assert result.ok, result
    ends = heard.ends()
    assert ends["lyrics"] == ("done", "LRCLIB has none; nor has Megalobiz; nor has AZLyrics")
    assert ends["vocals"] == ("done", "sung from 24.8 s, 1 stretch")
    assert ends["words"] == ("done", SAID)
    assert ends["chords"] == ("done", "chords over the transcribed lyrics")
    song = the_song(conn)
    kept = audio_store.uploaded(setup, song)
    assert ears.log == ["separator", "transcriber"]
    assert [separated for separated, _ in ears.separator.calls] == [kept] and recognizer.calls == [kept]
    assert transcript_of(conn, song) is not None and song.lyrics_status == "missing"


def test_a_waiting_lookup_goes_first_before_the_vocals_the_words_and_the_chords(setup, conn, sites, ears, tmp_path,
                                                                                monkeypatch):
    sites.records.clear()
    heard = Heard()
    went: list[str] = []  # the stage running each time the job looked for a waiting lookup

    def hand_over(cfg_, conn_=None) -> bool:
        name, state = heard.events[-1][1:3]
        went.append(name if state == "running" else "")
        return False  # none waits

    monkeypatch.setattr(_common, "hand_over", hand_over)
    result, _ = make(setup, AudioRequest(*NICK, file=a_file(tmp_path)), ears=ears, hears=True, progress=heard)
    assert result.ok, result
    assert [name for name in went if name in ("vocals", "words", "chords")] == ["vocals", "words", "chords"]


def test_a_transcriber_whose_setup_fails_ends_the_words_alone_and_the_chords_are_made(setup, conn, sites, ears,
                                                                                      tmp_path):
    # The setup's failure (the GPU's), never the song's: the words stage says it, and the sheet is made chords-only.
    from caracole.autochords import transcribe as tx

    sites.records.clear()
    said = "the GPU failed: OutOfMemoryError: CUDA out of memory"
    ears.transcriber.fail = tx.SetupFailed(said)
    result, heard = make(setup, AudioRequest(*NICK, file=a_file(tmp_path)), ears=ears, hears=True)
    assert result.ok and result.failed is None and result.bug is None, result
    ends = heard.ends()
    assert ends["vocals"][0] == "done" and ends["words"] == ("failed", said)
    assert ends["chords"] == ("done", "chords only, no lyrics") and ends["pdf"] == ("done", "made")
    assert ears.log == ["separator", "transcriber"]
    assert transcript_of(conn, the_song(conn)) is None


def test_lyrics_a_site_answers_with_as_the_job_runs_leave_nothing_to_hear(setup, conn, sites, ears, tmp_path):
    # The song had no lyrics as the job started; LRCLIB answers its lyrics stage: no voice separated, Whisper never
    # run, the chords over those lyrics.
    result, heard = make(setup, AudioRequest(*NICK, file=a_file(tmp_path)), ears=ears, hears=True)
    assert result.ok, result
    ends = heard.ends()
    assert ends["lyrics"] == ("done", "found, timed")
    assert ends["vocals"] == ("skipped", "not transcribed: its lyrics are found")
    assert ends["chords"] == ("done", "chords over the lyrics")
    assert ears.log == [] and ears.separator.calls == []
    assert [r[0] for r in sites.requests][:1] == ["get"]


def test_a_sheet_from_a_file_asks_its_lyrics_under_the_lyrics_name(setup, conn, sites, tmp_path):
    # [lyrics]' `as`, which the YouTube sheet's lyrics stage hands the passes: the sites are asked under it.
    from caracole.overrides import set_lyrics_name

    set_lyrics_name(setup.overrides_file, "Nick Cani - Vikingos veganos", "Nick Cani - Vikingos")
    result, heard = make(setup, AudioRequest(*NICK, file=a_file(tmp_path)))
    assert result.ok, result
    assert sites.requests[0] == ("get", {"artist_name": "Nick Cani", "track_name": "Vikingos", "duration": "200"})
    assert heard.ends()["lyrics"][1].startswith("under “Nick Cani - Vikingos”: ")


def test_a_picked_record_gone_makes_a_chords_only_sheet_from_a_file_its_words_never_heard(setup, conn, sites, ears,
                                                                                         tmp_path):
    from caracole.autochords.transcript import PICKED_NONE
    from caracole.overrides import set_lyrics_record

    set_lyrics_record(setup.overrides_file, "Nick Cani - Vikingos veganos", "megalobiz:8")
    result, heard = make(setup, AudioRequest(*NICK, file=a_file(tmp_path)), ears=ears, hears=True)
    assert result.ok, result
    ends = heard.ends()
    assert ends["lyrics"] == ("done", "the record you picked is gone: megalobiz 8")
    assert sites.requests == []  # LRCLIB never asked: the record is Megalobiz's
    assert ends["vocals"] == ("skipped", "not transcribed: " + PICKED_NONE.format(record="megalobiz 8"))
    assert ears.log == []
    assert ends["chords"] == ("done", "chords only, no lyrics")


def test_lyrics_a_site_has_skip_the_hearing(setup, conn, sites, ears, tmp_path):
    song = add_song(conn, *NICK, duration_ms=200000)
    update_song(conn, song.id, lyrics_status="found", lyrics_json=Lyrics.from_record(record(200.0)).to_json())
    result, heard = make(setup, AudioRequest(*NICK, file=a_file(tmp_path)), ears=ears, hears=True)
    assert result.ok, result
    assert heard.ends()["vocals"] == ("skipped", "not transcribed: its lyrics are found")
    assert ears.log == [] and sites.requests == []


# --- its names -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name,tags,named", [
    ("x.mp3", {"artist": "Nick Cani", "title": "Vikingos veganos (Official Audio)", "album": None},
     ("Nick Cani", "Vikingos veganos")),  # both tags: the title cleaned as a video's is
    ("03 - Nick Cani - Vikingos veganos.flac", {"artist": None, "title": "Vikingos", "album": "Pruebas"},
     ("Nick Cani", "Vikingos veganos")),  # one tag alone: the file's name, less its track number
    ("07 Vikingos veganos.wav", {"artist": None, "title": None, "album": None}, (None, "Vikingos veganos")),
], ids=["tags", "its name", "a title alone"])
def test_a_files_names_come_from_its_tags_then_its_name(conn, name, tags, named):
    assert names_of(conn, name, tags) == named


# --- Try again after the Audio stage ------------------------------------------------------------------------------


@pytest.mark.parametrize("stopped", ["failed", "interrupted"])
def test_the_same_job_again_after_its_audio_stage_makes_the_sheet_from_the_file_kept(setup, conn, sites, tmp_path,
                                                                                     monkeypatch, stopped):
    # The Audio stage moved the upload into place, so its id is gone; asked again (Try again, the same steps), the
    # song's audio is a file given: the job goes on with it, the Audio stage saying so, and makes the sheet.
    from caracole.youtube_sheet import _Sheet

    up = audio_store.stage(setup, audio("MP3", 200.0), "Vikingos.mp3", named=())
    real = _Sheet._autochords_sheet

    def stops(self):
        if stopped == "interrupted":
            raise KeyboardInterrupt  # serve stopped: the request Interrupted
        raise RuntimeError("CUDA error: an illegal memory access was encountered")

    monkeypatch.setattr(_Sheet, "_autochords_sheet", stops)
    if stopped == "interrupted":
        with pytest.raises(KeyboardInterrupt):
            make(setup, AudioRequest(*NICK, upload=up.id))
    else:
        first, _ = make(setup, AudioRequest(*NICK, upload=up.id))
        assert not first.ok
    kept = audio_store.uploaded(setup, the_song(conn))
    assert kept is not None and kept.name in kept_files(setup)
    monkeypatch.setattr(_Sheet, "_autochords_sheet", real)
    recognizer = Recognizer()
    result, heard = make(setup, AudioRequest(*NICK, upload=up.id), recognizer=recognizer)
    assert result.ok, result
    assert heard.ends()["audio"] == ("done", "has this file's audio already")
    assert kept.name in [p.name for p in recognizer.calls] and auto_sheet(setup, conn)  # made from the file kept
    assert set(kept_files(setup)) == {kept.name, f".upload-{up.id}.kept"}  # nothing staged: the file and its marker


def test_an_upload_gone_is_still_refused_for_a_song_whose_audio_is_no_file_given(setup, conn, sites, tmp_path):
    song = add_song(conn, *NICK)
    update_song(conn, song.id, audio_path=str(a_file(tmp_path)), audio_mtime=1.0)  # a purchase
    result, heard = make(setup, AudioRequest(*NICK, upload="0123456789abcdef"))
    assert not result.ok and result.failed.startswith("that upload is gone")


def sheet_of(setup, conn) -> str:
    return auto_sheet(setup, conn)


@pytest.mark.parametrize("lost", ["another upload", "the hour's sweep"])
def test_a_new_upload_lost_before_its_audio_stage_is_refused_and_the_older_file_stays(setup, conn, sites, monkeypatch,
                                                                                    lost):
    # A song with a file given; a new file uploaded for it, its job interrupted before its Audio stage, the staged file
    # let go (another upload, or the hour's sweep): Try again is refused as gone, the song's audio and sheet as they
    # were. Never "has this file's audio already" for a file that was never kept.
    from caracole.audio_sheet import _AudioSheet

    first = audio_store.stage(setup, audio("MP3", 200.0), "first.mp3", named=())
    assert make(setup, AudioRequest(*NICK, upload=first.id))[0].ok
    song = the_song(conn)
    before, sheet = song.audio_path, sheet_of(setup, conn)
    second = audio_store.stage(setup, audio("WAV", 200.0), "second.wav", named=())
    real = _AudioSheet.find_song

    def interrupted(self):
        raise KeyboardInterrupt  # serve restarted while the job ran its song stage: Interrupted, before Audio

    monkeypatch.setattr(_AudioSheet, "find_song", interrupted)
    with pytest.raises(KeyboardInterrupt):
        make(setup, AudioRequest(*NICK, upload=second.id))
    monkeypatch.setattr(_AudioSheet, "find_song", real)
    if lost == "another upload":
        audio_store.stage(setup, audio("MP3", 3.0), "another.mp3", named=())  # every staged upload no job names goes
    else:
        audio_store.sweep(setup, (), now=second.at + audio_store.EXPIRES + 1)
    with pytest.raises(audio_store.AudioError):
        audio_store.staged(setup, second.id)
    result, heard = make(setup, AudioRequest(*NICK, upload=second.id))
    assert not result.ok and result.failed.startswith("that upload is gone")
    assert the_song(conn).audio_path == before and sheet_of(setup, conn) == sheet


def test_try_again_of_an_older_job_once_a_later_file_is_kept_is_refused(setup, conn, sites):
    first = audio_store.stage(setup, audio("MP3", 200.0), "first.mp3", named=())
    assert make(setup, AudioRequest(*NICK, upload=first.id))[0].ok
    second = audio_store.stage(setup, audio("WAV", 200.0), "second.wav", named=())
    assert make(setup, AudioRequest(*NICK, upload=second.id))[0].ok
    later = the_song(conn).audio_path
    result, _ = make(setup, AudioRequest(*NICK, upload=first.id))
    assert not result.ok and result.failed.startswith("that upload is gone")
    assert the_song(conn).audio_path == later


@pytest.mark.parametrize("cut", ["before the move", "after the move, before the row"])
def test_a_keep_cut_off_anywhere_is_finished_by_the_same_job_again(setup, conn, sites, monkeypatch, cut):
    up = audio_store.stage(setup, audio("MP3", 200.0), "Vikingos.mp3", named=())
    target = (audio_store.os, "rename") if cut == "before the move" else (audio_store, "update_song")
    real = getattr(*target)

    def killed(*args, **kwargs):
        if cut == "before the move" and not str(args[0]).endswith(".mp3"):
            return real(*args, **kwargs)  # the marker's own rename goes through: cut after it, before the data's
        raise KeyboardInterrupt

    monkeypatch.setattr(*target, killed)
    with pytest.raises(KeyboardInterrupt):
        make(setup, AudioRequest(*NICK, upload=up.id))
    monkeypatch.setattr(*target, real)
    assert audio_store.uploaded(setup, the_song(conn)) is None
    assert any(n == f".upload-{up.id}.kept" for n in kept_files(setup))  # its marker, written before the move
    result, heard = make(setup, AudioRequest(*NICK, upload=up.id))
    assert result.ok, result
    assert heard.ends()["audio"] == ("done", "kept as its audio: MP3, 3:20")
    kept = audio_store.uploaded(setup, the_song(conn))
    assert kept is not None and kept.name == f"{the_song(conn).id}-{up.sha256[:16]}.mp3"
    assert [n for n in kept_files(setup) if not n.endswith(".kept")] == [kept.name]  # nothing else staged or lost


@pytest.mark.parametrize("between", ["a sweep", "another upload"])
def test_a_keep_stopped_before_the_move_survives_a_sweep_or_another_upload_and_is_finished(setup, conn, sites,
                                                                                            monkeypatch, between):
    up = audio_store.stage(setup, audio("MP3", 200.0), "Vikingos.mp3", named=())
    real = audio_store.os.rename

    def rename(src, dst, *args, **kwargs):
        if str(src).endswith(".mp3"):
            raise KeyboardInterrupt  # cut off after the marker, before the data's move
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(audio_store.os, "rename", rename)
    with pytest.raises(KeyboardInterrupt):
        make(setup, AudioRequest(*NICK, upload=up.id))
    monkeypatch.setattr(audio_store.os, "rename", real)
    if between == "a sweep":
        audio_store.sweep(setup, (), now=up.at + audio_store.EXPIRES + 1)
    else:
        audio_store.stage(setup, audio("WAV", 3.0), "other.wav", named=())
    result, heard = make(setup, AudioRequest(*NICK, upload=up.id))
    assert result.ok, result
    assert heard.ends()["audio"] == ("done", "kept as its audio: MP3, 3:20")
    assert audio_store.uploaded(setup, the_song(conn)).name == f"{the_song(conn).id}-{up.sha256[:16]}.mp3"


# --- histories (no new behaviour) ------------------------------------------------------------------------------


def test_the_same_bytes_uploaded_twice_keep_one_file_and_try_again_of_either_is_up_to_date(setup, conn, sites):
    x = audio_store.stage(setup, audio("MP3", 200.0), "x.mp3", named=())
    assert make(setup, AudioRequest(*NICK, upload=x.id))[0].ok
    kept = audio_store.uploaded(setup, the_song(conn))
    y = audio_store.stage(setup, audio("MP3", 200.0), "y.mp3", named=())
    assert make(setup, AudioRequest(*NICK, upload=y.id))[0].ok
    assert kept.exists() and audio_store.uploaded(setup, the_song(conn)) == kept
    for job in (x, y):
        result, heard = make(setup, AudioRequest(*NICK, upload=job.id))
        assert result.ok and heard.ends()["audio"] == ("done", "has this file's audio already")


def test_try_again_after_the_song_was_merged_goes_on_with_the_file_its_row_names(setup, conn, sites):
    # The upload kept for a song that a re-keying then merges into an older spelling of it: the merged song has the
    # file, and Try again of the old job finds it by its name.
    from test_songs import older_song

    from caracole.db import kv_set
    from caracole.normalize import KEY_VERSION
    from caracole.songs import KEY_VERSION_KV, ensure_current_keys

    artist, title = "Enanitos Verdes", "Lamento Boliviano"
    older = older_song(conn, "Los Enanitos Verdes", title, "los-enanitos-verdes/lamento-boliviano",
                       source="wanted", source_id="los-enanitos-verdes/lamento-boliviano")
    kv_set(conn, KEY_VERSION_KV, str(KEY_VERSION))  # not re-keyed yet: the upload's song is a record of its own
    up = audio_store.stage(setup, audio("MP3", 200.0), "lamento.mp3", named=())
    assert make(setup, AudioRequest(artist, title, upload=up.id))[0].ok
    from caracole.normalize import identity_key

    mine = find_song(conn, identity_key(artist, title))
    assert mine.id != older
    kept = audio_store.uploaded(setup, mine)
    conn.execute("DELETE FROM kv WHERE key = ?", (KEY_VERSION_KV,))
    ensure_current_keys(conn)
    merged = get_song(conn, older)
    assert merged.audio_path == str(kept)
    result, heard = make(setup, AudioRequest(artist, title, upload=up.id))
    assert result.ok and heard.ends()["audio"] == ("done", "has this file's audio already")
    assert get_song(conn, older).audio_path == str(kept)


def test_try_again_after_the_song_was_removed_and_asked_for_again_is_refused(setup, conn, sites):
    from caracole.removal import plan_removal, remove_song

    up = audio_store.stage(setup, audio("MP3", 200.0), "Vikingos.mp3", named=())
    assert make(setup, AudioRequest(*NICK, upload=up.id))[0].ok
    remove_song(conn, setup, plan_removal(conn, setup, the_song(conn)))
    result, heard = make(setup, AudioRequest(*NICK, upload=up.id))
    assert not result.ok and result.failed.startswith("that upload is gone")
    again = the_song(conn)
    assert again is None or again.audio_path is None
