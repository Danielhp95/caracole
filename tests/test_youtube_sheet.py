"""youtube_sheet.py: a song's auto sheet from a YouTube video, now, stage by stage.

yt-dlp is ``FakeYtDlp`` (helpers/fake_ytdlp.py), LRCLIB a fake behind ``_common.transport_for``, ntfy
another, auto-chords' models a fake recognizer and fake beats, and chordpro ``fake_chordpro``: nothing
reaches the network, and no model runs.
"""

from __future__ import annotations

import json
import wave
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from conftest import add_song
from helpers.fake_ytdlp import FakeYtDlp, entry
from helpers.rendered import fake_chordpro

from caracole.autochords import ChordSegment
from caracole.commands import _common
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
def sites(monkeypatch):
    lrclib, ntfy = Lrclib(record(200.0)), Ntfy()

    def transport(provider):
        handlers = {"lrclib": lrclib.handler, "ntfy": ntfy.handler}
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
def setup(cfg, fake, tmp_path):
    """The config: the fake yt-dlp, no pause between its runs, model files (unread), an ntfy topic."""
    from caracole.config import NtfyConfig

    files = {"btc_weights": tmp_path / "btc.pt", "beat_checkpoint": tmp_path / "final0.ckpt"}
    for path in files.values():
        path.write_bytes(b"model")
    youtube = replace(cfg.provider("youtube"), delay=(0.0, 0.0))
    return replace(cfg, ytdlp_bin=fake.bin, autochords=AutochordsConfig(**files),
                   providers={**cfg.providers, "youtube": youtube}, ntfy=NtfyConfig(url=NTFY))


def vikingos(fake, tmp_path, seconds=200.0, **spec):
    audio = wav(tmp_path / "audio" / "vikingos.wav", seconds)
    fake.video(VIKINGOS, "Vikingos veganos", "HyperFanes", seconds, ext="wav", copy=str(audio), **spec)


def make(cfg, url=PASTED, *, artist="Nick Cani", title="Vikingos veganos", recognizer=None):
    heard = Heard()
    result = make_sheet(cfg, SheetRequest(artist, title, url), heard, runner=fake_chordpro,
                        recognizer=recognizer or Recognizer(), beats_fn=beats, now=NOW)
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
    assert ends["song"] == ("done", f"added to wanted.txt, line 16; recorded under [youtube]: https://www.youtube.com/watch?v={VIKINGOS}")
    assert ends["audio"] == ("done", f"downloaded Vikingos veganos (HyperFanes), https://www.youtube.com/watch?v={VIKINGOS}")
    assert ends["lyrics"] == ("done", "found, timed")
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
    assert heard.ends()["lyrics"] == ("done", "LRCLIB has none")
    assert heard.ends()["chords"] == ("done", "chords only, no lyrics")
    text = auto_sheet(setup, conn, find_song(conn, result_key(conn)))
    assert "[Chords]" in text and "[Lyrics]" not in text


def test_lrclib_failing_leaves_the_chords_alone_and_says_what_comes_of_the_lyrics(setup, conn, fake, sites, tmp_path,
                                                                                monkeypatch):
    # LRCLIB overloaded, as it was on the owner's example: the sheet is made all the same, and the lyrics wait.
    lrclib, _ = sites
    monkeypatch.setattr(lrclib, "handler", lambda request: httpx.Response(503, text="Service Unavailable"))
    vikingos(fake, tmp_path)
    result, heard = make(setup)
    assert result.ok
    assert heard.ends()["lyrics"] == ("failed", "no lyrics yet (LRCLIB unavailable); tonight's run tries again")
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
    assert heard.ends()["song"][1].startswith("in the library")


# --- refused: asked nothing -----------------------------------------------------------------------------


def keep_human_sheet(conn, cfg, song):
    vid = upsert_version(conn, provider="ug", tab_id="85053", song_id=song.id, slot="sheet", kind="chords",
                         rating=4.5, votes=100, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/x",
                         raw={}, now="2026-10-18T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt", data=b"[ch]G[/ch]\nHi", rank=1)


@pytest.mark.parametrize("case,said", [
    ("human", "already has a sheet"),
    ("ignored", "is ignored in overrides.toml"),
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
    assert state == "skipped" and detail.startswith("YouTube blocked caracole; paused until ")
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
    assert heard.ends()["audio"][0] == "skipped" and "paused after a block" in heard.ends()["audio"][1]


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


def test_the_audio_it_has_is_not_asked_for_again(setup, conn, fake, sites, tmp_path):
    vikingos(fake, tmp_path)
    assert make(setup)[0].ok
    recognizer = Recognizer()
    result, heard = make(setup, recognizer=recognizer)
    assert result.ok and len(fake.argvs()) == 1 and recognizer.calls == []
    assert heard.ends()["audio"] == ("done", f"it has the audio of https://www.youtube.com/watch?v={VIKINGOS} already")
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


def test_every_event_is_plain_data(setup, conn, fake, sites, tmp_path):
    # What caracole serve reads: every event a plain JSON object.
    vikingos(fake, tmp_path)
    _, heard = make(setup)
    assert json.loads(json.dumps(heard.events))
