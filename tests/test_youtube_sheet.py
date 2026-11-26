"""youtube_sheet.py: a song's auto sheet from a YouTube video, now, stage by stage.

yt-dlp is ``FakeYtDlp`` (helpers/fake_ytdlp.py), LRCLIB a fake behind ``_common.transport_for``, ntfy
another, auto-chords' models a fake recognizer and fake beats, demucs-rs and Whisper test_transcribe_job.py's
fakes (``Ears``), and chordpro ``fake_chordpro``: nothing reaches the network, and no model runs.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import wave
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from conftest import add_song, subprocess_pythonpath
from helpers.fake_ytdlp import FakeYtDlp, entry
from helpers.azlyrics_site import FakeAzLyrics
from helpers.locks import waiting_for
from helpers.megalobiz_site import FakeMegalobiz
from helpers.megalobiz_site import record as megalobiz_record
from helpers.rendered import fake_chordpro

from caracole import youtube_fetch as yf
from caracole.autochords import ChordSegment, separate
from caracole.autochords.transcript import NOTE, SILENT, heard_nothing, transcript_of, why_not_offered
from caracole.commands import _common
from caracole.db import kv_get
from caracole.config import AutochordsConfig
from caracole.get import Progress
from caracole.health import get_state, is_cooling
from caracole.library import keep_file, song_dir
from caracole.overrides import load_overrides
from caracole.songs import find_song, get_song, update_song
from caracole.versions import upsert_version
from caracole.youtube_sheet import STAGES, SheetRequest, make_sheet

VIKINGOS = "lzN7Thn3FV4"
PASTED = f"https://www.youtube.com/watch?v={VIKINGOS}&pp=ygUQdmlraW5nb3MgdmVnYW5vcw%3D%3D"
NOW = datetime(2026, 10, 29, 20, 0, tzinfo=UTC)
NTFY = "https://ntfy.example/caracole-test"
SYNCED = "[00:00.50]Somos vikingos de prueba\n[00:05.20]comemos lechuga de prueba\n"


def wav(path: Path, seconds: float) -> Path:
    """Silence of a length mutagen reads: the fakes never listen."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * seconds))
    return path


class Heard(Progress):
    """What the run reports, as caracole serve would read it."""

    def __init__(self):
        self.events: list[tuple] = []

    def stage(self, name, state, detail=""):
        self.events.append(("stage", name, state, detail))

    def readable(self, files, seconds):
        self.events.append(("files", dict(files)))

    def song(self, song_id, display):
        self.events.append(("song", song_id, display))

    def ends(self) -> dict[str, tuple[str, str]]:
        return {e[1]: (e[2], e[3]) for e in self.events if e[0] == "stage" and e[2] != "running"}


class Recognizer:
    def __init__(self, *, fail=False):
        self.calls: list[Path] = []
        self.fail = fail

    def recognize(self, path):
        self.calls.append(Path(path))
        if self.fail:
            raise RuntimeError("Error opening the file: Format not recognised.")
        return [ChordSegment(0.0, 5.0, "D"), ChordSegment(5.0, 10.0, "A")]


def beats(path):
    return [i * 0.5 for i in range(41)], [i * 2.0 for i in range(11)]


class Lrclib:
    """LRCLIB's /api/get and /api/search: ``records`` by track name; every request kept."""

    def __init__(self, *records):
        self.records = list(records)
        self.requests: list[tuple[str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.removeprefix("/api/")
        params = dict(request.url.params)
        self.requests.append((endpoint, params))
        if endpoint.startswith("get/"):  # a record by its id
            found = [r for r in self.records if str(r["id"]) == endpoint.removeprefix("get/")]
            return httpx.Response(200, json=found[0]) if found else httpx.Response(404, json={"name": "TrackNotFound"})
        found = [r for r in self.records if r["trackName"] == params["track_name"]
                 and ("duration" not in params or abs(r["duration"] - int(params["duration"])) <= 2)]
        if endpoint == "get":
            return httpx.Response(200, json=found[0]) if found else httpx.Response(404, json={"name": "TrackNotFound"})
        return httpx.Response(200, json=found)


def record(duration: float, synced: str | None = SYNCED) -> dict:
    return {"id": 77, "name": "Vikingos veganos", "trackName": "Vikingos veganos", "artistName": "Nick Cani",
            "albumName": "Pruebas", "duration": duration, "instrumental": False,
            "plainLyrics": "Somos vikingos de prueba\ncomemos lechuga de prueba", "syncedLyrics": synced}


class Ntfy:
    def __init__(self):
        self.posts: list[httpx.Request] = []

    def handler(self, request):
        self.posts.append(request)
        return httpx.Response(200, json={"id": "x"})


@pytest.fixture
def megalobiz():
    return FakeMegalobiz()  # with no record: Megalobiz has nothing for the song


@pytest.fixture
def azlyrics():
    return FakeAzLyrics({})  # with no page: it has no artist


@pytest.fixture
def sites(monkeypatch, megalobiz, azlyrics):
    lrclib, ntfy = Lrclib(record(200.0)), Ntfy()

    def transport(provider):
        handlers = {"lrclib": lrclib.handler, "ntfy": ntfy.handler, "megalobiz": lambda r: megalobiz.handler(r),
                    "azlyrics": lambda r: azlyrics.handler(r)}
        if provider not in handlers:
            pytest.fail(f"a client for {provider} was made")
        return httpx.MockTransport(handlers[provider])

    monkeypatch.setattr(_common, "transport_for", transport)
    monkeypatch.setattr(_common, "sleep", lambda s: None)
    return lrclib, ntfy


@pytest.fixture
def fake(tmp_path):
    return FakeYtDlp(tmp_path / "bin")


@pytest.fixture
def setup(cfg, fake, tmp_path, monkeypatch):
    """The config: the fake yt-dlp, no pause between its runs, model files (unread), an ntfy topic; auto-chords and
    Whisper taken to be there, with their files, and demucs-rs not: a sheet hears no words here unless its test says
    so (``hears=True``), its vocals skipped "not transcribed here: demucs-rs is missing" where no site has its lyrics
    ("not transcribed: its lyrics are found" where one has)."""
    from caracole.config import NtfyConfig

    find_spec = importlib.util.find_spec
    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    monkeypatch.setattr(importlib.util, "find_spec",
                        lambda name, *args: object() if name == "whisper" else find_spec(name, *args))
    files = {"btc_weights": tmp_path / "btc.pt", "beat_checkpoint": tmp_path / "final0.ckpt",
             "whisper_model": tmp_path / "large-v3.pt", "separator_model": tmp_path / "htdemucs.safetensors"}
    for path in files.values():
        path.write_bytes(b"model")
    youtube = replace(cfg.provider("youtube"), delay=(0.0, 0.0))
    return replace(cfg, ytdlp_bin=fake.bin, demucs_bin=str(tmp_path / "no-demucs-here"),
                   autochords=AutochordsConfig(**files), providers={**cfg.providers, "youtube": youtube},
                   ntfy=NtfyConfig(url=NTFY))


class Ears:
    """demucs-rs and Whisper, test_transcribe_job.py's fakes, each noting in ``log`` that it ran, and the loudness they
    are read by: the vocal stem's ``stem`` (sung from 25 s to the mix's minute; a test may silence it), the mix's loud
    throughout."""

    def __init__(self, monkeypatch):
        from test_transcribe_job import MIX, STEM, Separator, Transcriber

        self.log: list[str] = []
        self.separator, self.transcriber = Separator(log=self.log), Transcriber(log=self.log)
        self.stem = list(STEM)
        monkeypatch.setattr(separate, "frame_db",
                            lambda path, **kw: list(self.stem if Path(path).name == "vocals.wav" else MIX))


@pytest.fixture
def ears(monkeypatch):
    return Ears(monkeypatch)


def vikingos(fake, tmp_path, seconds=200.0, **spec):
    audio = wav(tmp_path / "audio" / "vikingos.wav", seconds)
    fake.video(VIKINGOS, "Vikingos veganos", "HyperFanes", seconds, ext="wav", copy=str(audio), **spec)


def make(cfg, url=PASTED, *, artist="Nick Cani", title="Vikingos veganos", recognizer=None, ears=None, hears=None,
         progress=None):
    heard = progress or Heard()
    result = make_sheet(cfg, SheetRequest(artist, title, url), heard, runner=fake_chordpro,
                        recognizer=recognizer or Recognizer(), beats_fn=beats, now=NOW,
                        separator=ears.separator if ears else None, transcriber=ears.transcriber if ears else None,
                        hears=hears)
    return result, heard


def auto_sheet(cfg, conn, song) -> str:
    return (song_dir(cfg.library_dir, get_song(conn, song.id)) / "sheet (auto).txt").read_text(encoding="utf-8")


# --- the whole way ------------------------------------------------------------------------------------


def test_a_song_new_to_the_library_gets_its_sheet_from_the_video(setup, conn, fake, sites, tmp_path):
    lrclib, ntfy = sites
    vikingos(fake, tmp_path)
    result, heard = make(setup)
    assert result.ok, result
    assert [e[1] for e in heard.events if e[0] == "stage" and e[2] != "running"] == [name for name, _ in STAGES]
    ends = heard.ends()
    assert ends["song"] == ("done", f"added to wanted.txt, line 16; noted under [youtube]: https://www.youtube.com/watch?v={VIKINGOS}")
    assert ends["audio"] == ("done", f"downloaded Vikingos veganos (HyperFanes), https://www.youtube.com/watch?v={VIKINGOS}")
    assert ends["lyrics"] == ("done", "found, timed")
    assert ends["vocals"] == ("skipped", "not transcribed: its lyrics are found")  # whatever this caracole can do
    assert ends["words"] == ("skipped", "no vocals")
    assert ends["chords"] == ("done", "chords over the lyrics")
    assert ends["pdf"] == ("done", "made")
    # A song comes from a wanted.txt line, and the video goes under [youtube], as caracole youtube --url writes it.
    assert "Nick Cani - Vikingos veganos" in setup.wanted_file.read_text(encoding="utf-8")
    song = find_song(conn, result_key(conn))
    assert load_overrides(setup.overrides_file).youtube == {song.key: VIKINGOS}
    # yt-dlp was given the video's plain address alone: no search, no playlist.
    [argv] = fake.argvs()
    assert argv[-2:] == ["--", f"https://www.youtube.com/watch?v={VIKINGOS}"] and "--retries" in argv
    # LRCLIB was asked with the audio's length, the song's line giving none: its timed lyrics fit the audio.
    assert lrclib.requests[0] == ("get", {"artist_name": "Nick Cani", "track_name": "Vikingos veganos",
                                          "duration": "200"})
    text = auto_sheet(setup, conn, song)
    lines = text.splitlines()
    assert lines[:3] == ["auto-generated, unverified", "Nick Cani - Vikingos veganos",
                         "Audio from YouTube: Vikingos veganos (HyperFanes)"]
    i = lines.index("Somos vikingos de prueba")
    assert lines[i - 1].startswith("[ch]D[/ch]")  # chords over the words, as a UG sheet has them
    folder = song_dir(setup.library_dir, song)
    assert (folder / "sheet (auto).html").is_file() and (folder / "sheet (auto).pdf").is_file()
    # Its viewer draws the video from its data, a link, in place of that line (test_viewer_credit.py).
    page = (folder / "sheet (auto).html").read_text(encoding="utf-8")
    video = json.loads(page.split('<script type="application/json" id="song">', 1)[1].split("</script>", 1)[0])["video"]
    assert (video["title"], video["href"], video["channel"]) == (
        "Vikingos veganos", f"https://www.youtube.com/watch?v={VIKINGOS}", "HyperFanes")
    files = [e[1] for e in heard.events if e[0] == "files"]
    assert files[-1]["viewer"] == "Nick Cani/Vikingos veganos/sheet (auto).html"
    assert ("song", song.id, "Nick Cani - Vikingos veganos") in heard.events
    assert get_song(conn, song.id).status == "found"
    assert ntfy.posts == []
    index = (setup.library_dir / "index.html").read_text(encoding="utf-8")
    assert "Vikingos veganos" in index


def result_key(conn) -> str:
    from caracole.normalize import identity_key

    return identity_key("Nick Cani", "Vikingos veganos")


def test_without_lyrics_on_lrclib_the_sheet_is_the_chords_alone(setup, conn, fake, sites, tmp_path):
    lrclib, _ = sites
    lrclib.records.clear()
    vikingos(fake, tmp_path)
    result, heard = make(setup)
    assert result.ok
    assert heard.ends()["lyrics"] == ("done", "LRCLIB has none; nor has Megalobiz; nor has AZLyrics")
    assert heard.ends()["vocals"] == ("skipped", "not transcribed here: demucs-rs is missing")
    assert heard.ends()["chords"] == ("done", "chords only, no lyrics")
    text = auto_sheet(setup, conn, find_song(conn, result_key(conn)))
    assert "[Chords]" in text and "[Lyrics]" not in text


def test_without_lyrics_on_lrclib_megalobizs_timed_ones_put_the_chords_over_the_words(setup, conn, fake, sites,
                                                                                     megalobiz, tmp_path):
    lrclib, _ = sites
    lrclib.records.clear()
    megalobiz.records.append(megalobiz_record(lrc_id=8, title="Vikingos veganos", artist="Nick Cani", duration=200.0))
    vikingos(fake, tmp_path)
    result, heard = make(setup)
    assert result.ok
    assert heard.ends()["lyrics"] == ("done", "LRCLIB has none; found on Megalobiz, timed")
    assert heard.ends()["chords"] == ("done", "chords over the lyrics")
    assert megalobiz.requests[0][1]["duration"] == "200"  # asked with the audio's length, as LRCLIB is


def test_lrclib_failing_leaves_the_chords_alone_and_says_what_comes_of_the_lyrics(setup, conn, fake, sites, tmp_path,
                                                                                monkeypatch):
    # LRCLIB overloaded, as it was on the owner's example: the sheet is made all the same, and the lyrics wait.
    lrclib, _ = sites
    monkeypatch.setattr(lrclib, "handler", lambda request: httpx.Response(503, text="Service Unavailable"))
    vikingos(fake, tmp_path)
    result, heard = make(setup)
    assert result.ok
    assert heard.ends()["lyrics"] == ("failed", "no lyrics yet (LRCLIB unavailable); tried again tonight")
    assert heard.ends()["chords"] == ("done", "chords only, no lyrics")
    assert get_song(conn, find_song(conn, result_key(conn)).id).lyrics_status == "pending"  # never a miss


def test_timed_lyrics_of_another_cut_give_a_chart_then_the_lyrics(setup, conn, fake, sites, tmp_path):
    lrclib, _ = sites
    lrclib.records[:] = [record(150.0)]  # LRCLIB knows the record; the video has a long intro
    vikingos(fake, tmp_path)
    result, heard = make(setup)
    assert result.ok
    assert heard.ends()["chords"] == ("done", "chords, then the lyrics")
    text = auto_sheet(setup, conn, find_song(conn, result_key(conn)))
    assert "[Chords]" in text and "[Lyrics]" in text


def test_lyrics_the_song_had_are_kept(setup, conn, fake, sites, tmp_path):
    lrclib, _ = sites
    song = add_song(conn, "Nick Cani", "Vikingos veganos", duration_ms=None)
    from caracole.lyrics import Lyrics

    update_song(conn, song.id, lyrics_status="found", lyrics_json=Lyrics.from_record(record(200.0)).to_json())
    vikingos(fake, tmp_path)
    result, heard = make(setup)
    assert result.ok and heard.ends()["lyrics"] == ("done", "already there") and lrclib.requests == []
    assert heard.ends()["song"][1].startswith("in the book")


# --- refused: asked nothing -----------------------------------------------------------------------------


def keep_human_sheet(conn, cfg, song):
    vid = upsert_version(conn, provider="ug", tab_id="85053", song_id=song.id, slot="sheet", kind="chords",
                         rating=4.5, votes=100, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/x",
                         raw={}, now="2026-10-18T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt", data=b"[ch]G[/ch]\nHi", rank=1)


@pytest.mark.parametrize("case,said", [
    ("human", "already has a sheet"),
    ("ignored", "is ignored (overrides.toml)"),
    ("purchase", "has bought audio in Music/"),
])
def test_a_song_youtube_isnt_for_is_refused_and_youtube_is_asked_nothing(setup, conn, fake, sites, tmp_path,
                                                                          case, said):
    song = add_song(conn, "Nick Cani", "Vikingos veganos")
    if case == "human":
        keep_human_sheet(conn, setup, song)
    elif case == "ignored":
        setup.overrides_file.parent.mkdir(parents=True, exist_ok=True)
        setup.overrides_file.write_text('[ignore]\nsongs = ["Nick Cani - Vikingos veganos"]\n', encoding="utf-8")
    else:
        bought = wav(setup.music_dir / "Nick Cani - Vikingos veganos.wav", 3.0)
        update_song(conn, song.id, audio_path=str(bought), audio_mtime=bought.stat().st_mtime)
    vikingos(fake, tmp_path)
    result, heard = make(setup)
    assert not result.ok and result.refused and said in result.refused
    assert heard.ends()["song"][0] == "failed" and said in heard.ends()["song"][1]
    assert all(heard.ends()[name][0] == "skipped" for name, _ in STAGES[1:])
    assert fake.argvs() == [] and sites[0].requests == []
    assert VIKINGOS not in (setup.overrides_file.read_text(encoding="utf-8")
                            if setup.overrides_file.exists() else "")


def test_a_song_turned_down_for_youtube_needs_a_video_given(setup, conn, fake, sites, tmp_path):
    add_song(conn, "Nick Cani", "Vikingos veganos")
    setup.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    setup.overrides_file.write_text('[youtube]\n"Nick Cani - Vikingos veganos" = "none"\n', encoding="utf-8")
    fake.search("Nick Cani Vikingos veganos", entry(VIKINGOS, "Vikingos veganos", "Nick Cani"))
    result, _ = make(setup, url=None)
    assert result.refused and '[youtube] says "none"' in result.refused and fake.argvs() == []
    vikingos(fake, tmp_path)
    result, _ = make(setup)  # a video given: it takes the place of "none"
    assert result.ok


# --- waits and failures ------------------------------------------------------------------------------------


def test_a_block_cools_youtube_down_sends_one_alert_and_makes_nothing(setup, conn, fake, sites, tmp_path):
    _, ntfy = sites
    vikingos(fake, tmp_path, stderr="ERROR: [youtube] lzN7Thn3FV4: Sign in to confirm you're not a bot", exit=1)
    result, heard = make(setup)
    assert result.ok  # a wait, never a failure
    state, detail = heard.ends()["audio"]
    assert state == "skipped" and detail.startswith("YouTube turned us back; waiting until ")
    assert heard.ends()["chords"] == ("skipped", "no audio")
    assert heard.ends()["pdf"][0] == "skipped"
    assert is_cooling(conn, "youtube", NOW) and get_state(conn, "youtube").strikes == 1
    assert len(ntfy.posts) == 1 and ntfy.posts[0].headers["title"] == "caracole: YouTube blocked"
    assert len(fake.argvs()) == 1  # nothing retried


def test_while_youtube_cools_down_it_asks_nothing(setup, conn, fake, sites, tmp_path):
    from caracole.health import record_block

    record_block(conn, "youtube", NOW, "blocked")
    vikingos(fake, tmp_path)
    result, heard = make(setup)
    assert result.ok and fake.argvs() == []
    assert heard.ends()["audio"][0] == "skipped" and "waiting out YouTube" in heard.ends()["audio"][1]


def test_a_video_youtube_wont_give_fails_for_good(setup, conn, fake, sites, tmp_path):
    vikingos(fake, tmp_path, stderr="ERROR: [youtube] lzN7Thn3FV4: Private video. Sign in if you've been granted "
                                    "access to this video", exit=1)
    result, heard = make(setup)
    assert not result.ok and result.failed == "can't download this video; try another"
    assert heard.ends()["audio"][0] == "failed" and heard.ends()["chords"][0] == "skipped"


def test_a_network_error_is_a_wait(setup, conn, fake, sites, tmp_path):
    vikingos(fake, tmp_path, stderr="ERROR: [Errno -3] Temporary failure in name resolution", exit=1)
    result, heard = make(setup)
    assert result.ok and heard.ends()["audio"][0] == "failed"
    assert heard.ends()["audio"][1] == "download failed; try again later"


def test_audio_auto_chords_cant_read_fails(setup, conn, fake, sites, tmp_path):
    vikingos(fake, tmp_path)
    result, heard = make(setup, recognizer=Recognizer(fail=True))
    assert not result.ok and result.failed == "auto-chords can't read the audio"
    assert heard.ends()["chords"][0] == "failed" and heard.ends()["pdf"][0] == "skipped"


def test_a_song_removed_as_the_models_let_a_lookup_go_first_ends_the_sheet_as_a_refusal(setup, conn, fake, sites,
                                                                                            tmp_path, monkeypatch):
    # Before its models the sheet hands the lock to a waiting lookup; meanwhile another caracole took the song out.
    # The sheet ends there, a refusal its song stage says (the command's "No sheet made: …"), never a bug, and the
    # models run on nothing: no auto sheet is written.
    vikingos(fake, tmp_path)
    monkeypatch.setattr(_common, "_handoffs", _common.handoffs())  # put back as it was after the test

    def hand_over(cfg_, conn_=None) -> bool:
        _common._handoffs += 1  # the lookup had the lock, and another caracole removed the song
        conn_.execute("DELETE FROM songs")
        return True

    monkeypatch.setattr(_common, "hand_over", hand_over)
    recognizer = Recognizer()
    result, heard = make(setup, recognizer=recognizer)

    assert result.bug is None and result.failed is None
    assert result.refused == ("Nick Cani - Vikingos veganos left the book while its sheet was made (removed, or "
                              "merged into a song of the same name)")
    ends = heard.ends()
    assert ends["song"] == ("failed", result.refused)
    assert [ends[name][0] for name in ("audio", "lyrics")] == ["done", "done"]
    assert [ends[name][0] for name in ("chords", "pdf", "pages")] == ["skipped"] * 3
    assert recognizer.calls == []
    assert not (setup.library_dir / "Nick Cani" / "Vikingos veganos" / "sheet (auto).txt").exists()


@pytest.mark.parametrize("earlier", [False, True], ids=["no auto sheet before", "an auto sheet before"])
def test_a_human_sheet_kept_as_the_models_let_a_lookup_go_first_ends_the_sheet_as_a_refusal(setup, conn, fake, sites,
                                                                                         tmp_path, monkeypatch,
                                                                                         earlier):
    # Meanwhile a terminal's `caracole get` kept UG's chords: auto-chords would skip the song, which is no failure of
    # the sheet's ("made no sheet") nor, over an earlier auto sheet, a Ready. The sheet ends there, a refusal.
    vikingos(fake, tmp_path)
    if earlier:
        assert make(setup)[0].ok
    monkeypatch.setattr(_common, "_handoffs", _common.handoffs())  # put back as it was after the test

    def hand_over(cfg_, conn_=None) -> bool:
        _common._handoffs += 1
        keep_human_sheet(conn_, cfg_, find_song(conn_, result_key(conn_)))
        return True

    monkeypatch.setattr(_common, "hand_over", hand_over)
    recognizer = Recognizer()
    result, heard = make(setup, recognizer=recognizer)
    assert result.bug is None and result.failed is None
    assert result.refused == "Nick Cani - Vikingos veganos already has a sheet"
    ends = heard.ends()
    assert ends["song"] == ("failed", result.refused)
    assert [ends[name][0] for name in ("chords", "pdf", "pages")] == ["skipped"] * 3
    assert recognizer.calls == []


def test_the_audio_it_has_is_not_asked_for_again(setup, conn, fake, sites, tmp_path):
    vikingos(fake, tmp_path)
    assert make(setup)[0].ok
    recognizer = Recognizer()
    result, heard = make(setup, recognizer=recognizer)
    assert result.ok and len(fake.argvs()) == 1 and recognizer.calls == []
    assert heard.ends()["audio"] == ("done", f"has the audio of https://www.youtube.com/watch?v={VIKINGOS} already")
    assert heard.ends()["chords"] == ("done", "up to date: chords over the lyrics")


def test_another_video_replaces_the_audio_and_the_sheet(setup, conn, fake, sites, tmp_path):
    vikingos(fake, tmp_path)
    assert make(setup)[0].ok
    other = "oNOFfl3Hx3s"
    fake.video(other, "Vikingos veganos (en directo)", "Nick Cani", 200.0, ext="wav",
               copy=str(tmp_path / "audio" / "vikingos.wav"))
    result, heard = make(setup, url=f"https://youtu.be/{other}")
    assert result.ok and heard.ends()["chords"][0] == "done"
    text = auto_sheet(setup, conn, find_song(conn, result_key(conn)))
    assert "Audio from YouTube: Vikingos veganos (en directo) (Nick Cani)" in text
    assert [p.name for p in (setup.cache_dir / "youtube").iterdir()] == [f"1-{other}.wav"]


@pytest.mark.parametrize("url,asks", [
    (PASTED, ["downloading the video's audio"]),
    (None, ["looking for a video on YouTube", "downloading the video's audio"]),
], ids=["pasted", "searched"])
def test_the_audio_and_the_chords_say_what_they_do_as_they_run(setup, conn, fake, sites, tmp_path, url, asks):
    # The song's line moves through the minutes of the models: what the audio stage asks YouTube for (a video
    # searched for, then its audio once one is found), then auto-chords' steps, each said once.
    vikingos(fake, tmp_path)
    fake.search("Nick Cani Vikingos veganos", entry(VIKINGOS, "Vikingos veganos", "Nick Cani"))
    result, heard = make(setup, url=url)
    assert result.ok, result
    running = [(e[1], e[3]) for e in heard.events if e[0] == "stage" and e[2] == "running" and e[3]]
    assert running == [
        *(("audio", said) for said in asks),
        ("chords", "setting up the models"), ("chords", "hearing the chords"), ("chords", "finding the beats"),
        ("chords", "writing the sheet"),
    ]


def test_every_event_is_plain_data(setup, conn, fake, sites, tmp_path):
    # What caracole serve reads: every event a plain JSON object.
    vikingos(fake, tmp_path)
    _, heard = make(setup)
    assert json.loads(json.dumps(heard.events))


def test_without_lyrics_on_lrclib_or_megalobiz_azlyrics_plain_ones_go_on_the_sheet(setup, conn, fake, sites, azlyrics,
                                                                                  tmp_path):
    from helpers.azlyrics_site import SONG, artist_page, lyrics_page

    lrclib, _ = sites
    lrclib.records.clear()
    azlyrics.pages.update({
        "/n/nickcani.html": artist_page().replace("Pomme Lyrics", "Nick Cani Lyrics").replace(
            "mononoke</a>", "Vikingos veganos</a>"),
        SONG: lyrics_page(),
    })
    vikingos(fake, tmp_path)
    result, heard = make(setup)
    assert result.ok
    assert heard.ends()["lyrics"] == ("done", "LRCLIB has none; nor has Megalobiz; found on AZLyrics")
    assert result.requests["azlyrics"] == 2
    song = find_song(conn, result_key(conn))
    assert song.lyrics_status == "found"
    assert "Des mots inventés" in auto_sheet(setup, conn, song)


def test_a_sheet_from_youtube_asks_its_lyrics_under_the_lyrics_name(setup, conn, fake, sites, megalobiz, tmp_path):
    # [lyrics]' `as`: the sites are asked under it, with the audio's length and no album.
    from caracole.overrides import set_lyrics_name

    lrclib, _ = sites
    set_lyrics_name(setup.overrides_file, "Nick Cani - Vikingos veganos (Video Oficial)", "Nick Cani - Vikingos veganos")
    vikingos(fake, tmp_path)
    result, heard = make(setup, title="Vikingos veganos (Video Oficial)")
    assert result.ok, result
    assert lrclib.requests == [("get", {"artist_name": "Nick Cani", "track_name": "Vikingos veganos",
                                        "duration": "200"})]
    assert heard.ends()["lyrics"] == ("done", "found, timed under “Nick Cani - Vikingos veganos”")
    assert megalobiz.requests == []  # timed lyrics already


def test_a_sheet_from_youtube_asks_a_picked_record_of_its_site_alone(setup, conn, fake, sites, megalobiz, azlyrics,
                                                                    tmp_path):
    from caracole.overrides import set_lyrics_record

    lrclib, _ = sites
    set_lyrics_record(setup.overrides_file, "Nick Cani - Vikingos veganos", "lrclib:77")
    vikingos(fake, tmp_path)
    result, heard = make(setup)
    assert result.ok, result
    assert lrclib.requests == [("get/77", {})]
    assert heard.ends()["lyrics"] == ("done", "the record you picked: lrclib 77")
    assert megalobiz.requests == [] and azlyrics.requests == []


# --- the words heard from the audio, where no site has them ------------------------------------------------------


def nowhere(sites):
    """No lyrics site has the song: LRCLIB's record gone (Megalobiz and AZLyrics have none already)."""
    sites[0].records.clear()


def the_song(conn):
    return get_song(conn, find_song(conn, result_key(conn)).id)


def auto_raw(conn, song) -> dict:
    from caracole.songs import AUTO_SHEET
    from caracole.versions import get_version

    [version_id] = conn.execute("SELECT version_id FROM files WHERE song_id = ? AND name = ?",
                                (song.id, AUTO_SHEET)).fetchone()
    return get_version(conn, version_id).raw


def test_a_video_no_site_has_lyrics_for_gets_its_words_heard_before_its_chords(setup, conn, fake, sites, ears,
                                                                                tmp_path):
    # The owner's rule: the lyrics sites are asked first, and only once every one missed are the words heard from the
    # audio; the chords are then made once, over them.
    from test_transcribe_job import SAID

    nowhere(sites)
    vikingos(fake, tmp_path)
    recognizer = Recognizer()
    result, heard = make(setup, recognizer=recognizer, ears=ears, hears=True)
    assert result.ok, result
    names = ["song", "audio", "lyrics", "vocals", "words", "chords", "pdf", "pages"]
    assert [name for name, _ in STAGES] == names
    assert [e[1] for e in heard.events if e[0] == "stage" and e[2] != "running"] == names
    ends = heard.ends()
    assert ends["lyrics"] == ("done", "LRCLIB has none; nor has Megalobiz; nor has AZLyrics")
    assert ends["vocals"] == ("done", "sung from 24.8 s, 1 stretch")
    assert ends["words"] == ("done", SAID)
    assert ends["chords"] == ("done", "chords over the transcribed lyrics")
    assert ends["pdf"] == ("done", "made")
    song = the_song(conn)
    # The separator and Whisper heard the video's audio, then the chords were made of it once.
    assert ears.log == ["separator", "transcriber"]
    [(separated, _)] = ears.separator.calls
    assert separated == Path(song.audio_path) and recognizer.calls == [Path(song.audio_path)]
    raw = auto_raw(conn, song)
    assert raw["lyrics_source"] == "transcript" and raw["transcript_made_at"] == transcript_of(conn, song).made_at
    lines = auto_sheet(setup, conn, song).splitlines()
    assert NOTE in lines and "Somos vikingos de prueba" in lines
    assert (song.lyrics_status, song.lyrics_json) == ("missing", None)  # a transcript is no site's lyrics
    assert not list(setup.cache_dir.glob("transcribe-*"))  # the stem went with the job


def test_a_picked_record_gone_is_every_site_asked_and_the_words_are_heard(setup, conn, fake, sites, megalobiz,
                                                                         azlyrics, ears, tmp_path):
    # The record you picked is final: its own site alone is asked, and once it is gone there no other will be, so the
    # sites were asked and missed and the words are heard from the audio, the owner's rule kept.
    from caracole.overrides import set_lyrics_record

    lrclib, _ = sites
    set_lyrics_record(setup.overrides_file, "Nick Cani - Vikingos veganos", "megalobiz:8")
    vikingos(fake, tmp_path)
    result, heard = make(setup, ears=ears, hears=True)
    assert result.ok, result
    ends = heard.ends()
    assert ends["lyrics"] == ("done", "the record you picked is gone: megalobiz 8")
    assert lrclib.requests == [] and [e for e, _ in megalobiz.requests] == ["lrc"] and azlyrics.requests == []
    assert ends["vocals"][0] == "done", ends["vocals"]
    assert ears.log == ["separator", "transcriber"]
    assert ends["chords"] == ("done", "chords over the transcribed lyrics")


@pytest.mark.parametrize("found,said,chords", [
    (record(200.0), "its lyrics are found", "chords over the lyrics"),
    ({**record(200.0), "instrumental": True, "plainLyrics": None, "syncedLyrics": None}, "its lyrics are instrumental",
     "chords only, no lyrics"),
], ids=["lyrics", "an instrumental"])
def test_a_sites_lyrics_skip_the_vocals_and_the_words(setup, conn, fake, sites, ears, tmp_path, found, said, chords):
    sites[0].records[:] = [found]
    vikingos(fake, tmp_path)
    result, heard = make(setup, ears=ears, hears=True)
    assert result.ok, result
    ends = heard.ends()
    assert ends["vocals"] == ("skipped", f"not transcribed: {said}")
    assert ends["words"] == ("skipped", "no vocals")
    assert ends["chords"] == ("done", chords)
    assert ears.log == []


@pytest.mark.parametrize("lyrics,transcribe,said", [
    ("found", True, "not transcribed: its lyrics are found"),
    ("found", False, "not transcribed: its lyrics are found"),
    ("instrumental", True, "not transcribed: its lyrics are instrumental"),
    ("none", True, "not transcribed here: demucs-rs is missing"),
    ("none", False, "not transcribed: turned off ([autochords] transcribe = false)"),
    ("unavailable", True, "not transcribed here: demucs-rs is missing"),
], ids=["lyrics", "lyrics, turned off", "an instrumental", "none", "none, turned off", "LRCLIB unavailable"])
def test_a_sites_lyrics_are_said_first_whatever_this_caracole_can_do(setup, conn, fake, sites, monkeypatch, tmp_path,
                                                                     lyrics, transcribe, said):
    # On a caracole that can't transcribe (no demucs-rs here), a sheet whose lyrics a site found says so, which is no
    # fault; only a song no site has words or a verdict for says the setting, or why this caracole can't.
    lrclib, _ = sites
    if lyrics == "instrumental":
        lrclib.records[:] = [{**record(200.0), "instrumental": True, "plainLyrics": None, "syncedLyrics": None}]
    elif lyrics == "none":
        lrclib.records.clear()
    elif lyrics == "unavailable":
        monkeypatch.setattr(lrclib, "handler", lambda request: httpx.Response(503, text="Service Unavailable"))
    vikingos(fake, tmp_path)
    result, heard = make(replace(setup, autochords=replace(setup.autochords, transcribe=transcribe)))
    assert result.ok, result
    assert heard.ends()["vocals"] == ("skipped", said)
    assert heard.ends()["words"] == ("skipped", "no vocals")


@pytest.mark.parametrize("stem,words,why,ran", [
    ([-80.0] * 1200, None, "sung 0.0 s", ["separator"]),  # no singing found: Whisper isn't run
    (None, 6, "5 words in 0:35 sung", ["separator", "transcriber"]),  # a shouted line: too few words to be lyrics
], ids=["no singing found", "five words"])
def test_nothing_sung_makes_a_chords_only_sheet_that_says_so_and_exits_0(setup, conn, fake, sites, ears, tmp_path,
                                                                         stem, words, why, ran):
    from test_transcribe_job import WORDS

    nowhere(sites)
    if stem is not None:
        ears.stem = stem
    if words is not None:
        ears.transcriber.words = WORDS[:words]
    vikingos(fake, tmp_path)
    result, heard = make(setup, ears=ears, hears=True)
    assert result.ok and result.failed is None, result  # the command exits 0
    ends = heard.ends()
    assert ends["vocals"][0] == "done"
    assert ends["words"] == ("done", f"nothing sung was heard ({why})")
    assert ends["chords"] == ("done", "chords only: nothing sung was heard")
    assert ends["pdf"] == ("done", "made")
    assert ears.log == ran
    song = the_song(conn)
    assert heard_nothing(conn, song) and transcript_of(conn, song) is None
    assert auto_raw(conn, song)["heard_nothing"] is True
    assert SILENT in auto_sheet(setup, conn, song).splitlines()


@pytest.mark.parametrize("fails,stage,said,ran", [
    ("separator", "vocals", "the separator can't run here (No possible adapter)", ["separator"]),
    ("whisper", "words", "the GPU failed: OutOfMemoryError: CUDA out of memory", ["separator", "transcriber"]),
    ("audio", "words", "Whisper can't read the audio", ["separator", "transcriber"]),
], ids=["the separator", "the GPU", "audio Whisper can't load"])
def test_a_transcription_that_fails_here_still_makes_the_chords_and_exits_0(setup, conn, fake, sites, ears, tmp_path,
                                                                            fails, stage, said, ran):
    # The setup's failure, not the song's: its stage says so, the sheet is made chords-only all the same, and the song
    # stays offered a transcription, for Transcribe the lyrics to try again. So does audio Whisper can't load (it reads
    # through the ffmpeg program): auto-chords reads it with its own reader, the one the vocals read it with, and files
    # nothing against it when it can.
    from caracole.autochords import transcribe as tx

    nowhere(sites)
    if fails == "separator":
        ears.separator.fail = "No possible adapter"
    elif fails == "whisper":
        ears.transcriber.fail = tx.SetupFailed(said)
    else:
        ears.transcriber.fail = RuntimeError("Failed to load audio: [mov,mp4] moov atom not found")
    vikingos(fake, tmp_path)
    recognizer = Recognizer()
    result, heard = make(setup, recognizer=recognizer, ears=ears, hears=True)
    assert result.ok and result.failed is None and result.bug is None, result  # the command exits 0
    ends = heard.ends()
    assert ends[stage] == ("failed", said)
    if stage == "vocals":
        assert ends["words"] == ("skipped", "no vocals")
    assert ends["chords"] == ("done", "chords only, no lyrics")
    assert ends["pdf"] == ("done", "made")
    assert ears.log == ran
    song = the_song(conn)
    assert recognizer.calls == [Path(song.audio_path)]
    assert transcript_of(conn, song) is None and not heard_nothing(conn, song)
    assert kv_get(conn, f"autochords:failed:{song.id}") is None
    # Offered again after the setup's failure; audio Whisper can't load is noted for its own audio, and offered no
    # more until it changes (a transcription would fail on it the same way).
    expected = "Whisper can't read its audio" if fails == "audio" else None
    assert why_not_offered(conn, setup, song, load_overrides(setup.overrides_file)) == expected


@pytest.mark.parametrize("before,ran", [("vocals", []), ("words", ["separator"])])
def test_lyrics_a_lookup_found_as_it_went_first_skip_the_hearing_and_the_chords_go_over_them(
        setup, conn, fake, sites, ears, tmp_path, monkeypatch, before, ran):
    # Before the vocals and the words a waiting lookup goes first: one that found the song's lyrics meanwhile (a
    # terminal's `caracole get`) leaves nothing to hear, and the sheet goes on, over those lyrics, never a refusal.
    from caracole.lyrics import Lyrics

    nowhere(sites)
    vikingos(fake, tmp_path)
    heard = Heard()
    monkeypatch.setattr(_common, "_handoffs", _common.handoffs())  # put back as it was after the test

    def hand_over(cfg_, conn_=None) -> bool:
        if heard.events[-1][1:3] != (before, "running"):  # no lookup waits: a pause's look finds none
            return False
        _common._handoffs += 1
        song = find_song(conn_, result_key(conn_))
        update_song(conn_, song.id, lyrics_status="found", lyrics_json=Lyrics.from_record(record(200.0)).to_json())
        return True

    monkeypatch.setattr(_common, "hand_over", hand_over)
    result, _ = make(setup, ears=ears, hears=True, progress=heard)
    assert result.ok and result.refused is None, result
    ends = heard.ends()
    assert ends[before] == ("skipped", "not transcribed: its lyrics are found")
    assert ends["words"][0] == "skipped"
    assert ends["chords"] == ("done", "chords over the lyrics")
    assert ears.log == ran
    assert transcript_of(conn, the_song(conn)) is None


@pytest.mark.parametrize("transcribe", [True, False], ids=["on", "off"])
def test_transcribe_off_in_the_config_skips_them(setup, conn, fake, sites, ears, tmp_path, monkeypatch, transcribe):
    # Where the words can be heard here, [autochords] transcribe decides: off, the sheet is made as before, chords
    # only, and the song is offered Transcribe the lyrics on its card.
    from test_transcribe_job import SAID

    monkeypatch.setattr(yf, "transcribe_problem", lambda cfg: None)  # Whisper, its models and demucs-rs here
    nowhere(sites)
    vikingos(fake, tmp_path)
    result, heard = make(replace(setup, autochords=replace(setup.autochords, transcribe=transcribe)), ears=ears)
    assert result.ok, result
    ends = heard.ends()
    if transcribe:
        assert ends["words"] == ("done", SAID)
        assert ends["chords"] == ("done", "chords over the transcribed lyrics")
        return
    assert ends["vocals"] == ("skipped", "not transcribed: turned off ([autochords] transcribe = false)")
    assert ends["words"] == ("skipped", "no vocals")
    assert ends["chords"] == ("done", "chords only, no lyrics")
    assert ears.log == []
    assert why_not_offered(conn, setup, the_song(conn), load_overrides(setup.overrides_file)) is None


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
@pytest.mark.parametrize("sung,order", [
    (True, ["lookup", "separator", "lookup", "transcriber", "lookup", "recognizer"]),
    (False, ["lookup", "separator", "lookup", "lookup", "recognizer"]),
], ids=["sung", "no singing found"])
def test_the_lock_goes_to_a_waiting_lookup_before_vocals_words_and_chords(setup, conn, fake, sites, ears, tmp_path,
                                                                          sung, order):
    # The separator, Whisper and auto-chords take minutes each: a lookup asked meanwhile goes before each of them, and
    # before the words where no singing was found too, as nothing sung is noted only after it.
    nowhere(sites)
    vikingos(fake, tmp_path)
    if not sung:
        ears.stem = [-80.0] * 1200
    config = tmp_path / "caracole.toml"
    config.write_text(f'state_dir = "{setup.state_dir}"\ncache_dir = "{setup.cache_dir}"\n'
                      f'library_dir = "{setup.library_dir}"\n', encoding="utf-8")
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
                assert waiting_for(setup.state_dir / _common.LOCK_NAME, lambda: lookup.poll() is None)

    class Noted:
        """Where each model notes that it runs: the log the lookups write too."""

        def append(self, what):
            with open(log, "a", encoding="utf-8") as out:
                out.write(what + "\n")

    class Recognized(Recognizer):
        def recognize(self, path):
            Noted().append("recognizer")
            return super().recognize(path)

    ears.separator.log = ears.transcriber.log = Noted()
    handed = _common.handoffs()
    try:
        result, heard = make(setup, recognizer=Recognized(), ears=ears, hears=True, progress=Asked())
        assert [lookup.wait(30) for lookup in lookups] == [0, 0, 0]
    finally:
        for lookup in lookups:
            lookup.kill()
    assert result.ok, result
    assert heard.ends()["words"][0] == "done"
    assert log.read_text(encoding="utf-8").splitlines() == order
    assert _common.handoffs() == handed + 3


def test_the_ready_line_says_the_lyrics_are_transcribed():
    from caracole.youtube_sheet import HOLDS, holds

    assert HOLDS["transcript"] == "chords over the transcribed lyrics"
    assert holds({"lyrics": "synced", "lyrics_source": "transcript"}) == "chords over the transcribed lyrics"
    assert holds({"lyrics": "synced"}) == "chords over the lyrics"
    assert HOLDS["silent"] == "chords only: nothing sung was heard"
    assert holds({"lyrics": "none", "heard_nothing": True}) == "chords only: nothing sung was heard"
    # The owner's mark is said as theirs, never as nothing heard (Whisper heard words, and the owner overruled them).
    assert HOLDS["said"] == "chords only: you said it isn't sung"
    assert holds({"lyrics": "none", "heard_nothing": True, "not_sung_by": "you"}) == (
        "chords only: you said it isn't sung")
    assert holds({"lyrics": "none"}) == "chords only, no lyrics"
    assert holds({}) == "chords"
