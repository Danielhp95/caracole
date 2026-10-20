"""Auto-chords over the database: which songs get ``sheet (auto).txt``, and how.

Most tests use a fake recognizer and fake beats, so they run anywhere. The one
marked ``autochords`` runs the real models on synthetic audio; it needs torch,
librosa and beat_this, and the model files (see tests/test_autochords_models.py).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import wave
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from helpers.locks import waiting_for
from typer.testing import CliRunner

from caracole.autochords import ChordSegment
from caracole.autochords.run import AUTO_SHEET, AutoStats, autochords_pending
from caracole.cli import build_app
from caracole.config import AutochordsConfig
from caracole.db import kv_get, kv_get_json
from caracole.library import keep_file, kept_files, song_dir
from caracole.lyrics import Lyrics
from caracole.overrides import Overrides
from caracole.songs import get_song, update_song
from caracole.versions import get_version, upsert_version

from conftest import add_song

BEATS = [i * 0.5 for i in range(41)]  # 120 BPM for 20 s
DOWNBEATS = BEATS[::4]


def make_wav(path: Path, seconds: float = 10.0) -> Path:
    """Silence: the fakes never listen, but read_audio needs a real duration."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * seconds))
    return path


def lyrics_json(*, plain=None, synced=None, duration=10.0, instrumental=False) -> str:
    record = {
        "id": 7,
        "trackName": "T",
        "artistName": "A",
        "duration": duration,
        "instrumental": instrumental,
        "plainLyrics": plain,
        "syncedLyrics": synced,
    }
    return Lyrics.from_record(record).to_json()


def with_audio(conn, tmp_path, song, *, seconds=10.0, name=None, **fields):
    """Link a WAV to the song as scan_music would, plus any other song fields."""
    path = make_wav(tmp_path / "music" / (name or f"{song.id}.wav"), seconds)
    update_song(conn, song.id, audio_path=str(path), audio_mtime=os.stat(path).st_mtime, **fields)
    return get_song(conn, song.id)


def keep_human_sheet(conn, cfg, song):
    vid = upsert_version(
        conn,
        provider="ug",
        tab_id="85053",
        song_id=song.id,
        slot="sheet",
        kind="chords",
        rating=4.5,
        votes=100,
        version=1,
        label=None,
        url="https://tabs.ultimate-guitar.com/tab/x-85053",
        raw={},
        now="2026-10-18T00:00:00Z",
    )
    keep_file(
        conn,
        cfg.library_dir,
        song=song,
        version_id=vid,
        name="sheet.txt",
        data=b"[ch]G[/ch]\nHi",
        rank=1,
    )


class FakeRecognizer:
    def __init__(self, *, fail_on: tuple[str, ...] = ()):
        self.calls: list[Path] = []
        self.fail_on = fail_on

    def recognize(self, path):
        self.calls.append(Path(path))
        if Path(path).name in self.fail_on:
            raise RuntimeError(f"Error opening {str(path)!r}: Format not recognised.")
        return [ChordSegment(0.0, 5.0, "C"), ChordSegment(5.0, 10.0, "G")]


class FakeBeats:
    def __init__(self):
        self.calls: list[Path] = []

    def __call__(self, path):
        self.calls.append(Path(path))
        return BEATS, DOWNBEATS


def run(conn, cfg, recognizer=None, beats=None, **kw) -> AutoStats:
    return autochords_pending(
        conn, cfg, recognizer=recognizer or FakeRecognizer(), beats_fn=beats or FakeBeats(), **kw
    )


def auto_sheet(cfg, conn, song) -> str:
    return (song_dir(cfg.library_dir, get_song(conn, song.id)) / AUTO_SHEET).read_text(
        encoding="utf-8"
    )


STATUS = "autochords:status"


def failed_key(song) -> str:
    return f"autochords:failed:{song.id}"


def failures(stats: AutoStats) -> list[tuple[str, str, str]]:
    """The purchases a run couldn't read, as (song, error, audio)."""
    return [(f.song, f.error, f.audio) for f in stats.failures]


def unreadable(path) -> str:
    """The error FakeRecognizer raises for a file it fails on, as the to-do page shows it."""
    return f"RuntimeError: Error opening {Path(path).name!r}: Format not recognised."


def model_files(tmp_path: Path) -> dict[str, Path]:
    """Model files that exist, for fakes of the default models: nothing reads them."""
    files = {"btc_weights": tmp_path / "btc.pt", "beat_checkpoint": tmp_path / "final0.ckpt"}
    for path in files.values():
        path.write_bytes(b"model")
    return files


def with_model_files(cfg, tmp_path):
    return replace(cfg, autochords=AutochordsConfig(**model_files(tmp_path)))


def fake_default_models(monkeypatch, *, fail_on: tuple[str, ...] = ()) -> None:
    """Fakes for BTCRecognizer and detect_beats, which the default models are built from."""
    import caracole.autochords.run as ac_run

    class Recognizer(FakeRecognizer):
        def __init__(self, weights, *, device="cpu"):
            super().__init__(fail_on=fail_on)

    monkeypatch.setattr(ac_run, "BTCRecognizer", Recognizer)
    monkeypatch.setattr(
        ac_run, "detect_beats", lambda path, checkpoint, device="cpu": (BEATS, DOWNBEATS)
    )


# --- what gets generated -------------------------------------------------------------------


def test_auto_sheet_kept_with_its_version_and_the_song_becomes_found(conn, cfg, tmp_path):
    s = with_audio(
        conn,
        tmp_path,
        add_song(conn, "Nobody", "River Road"),
        lyrics_status="found",
        lyrics_json=lyrics_json(plain="Walking down\nSinging on"),
    )
    stats = run(conn, cfg, now=datetime(2026, 10, 18, 4, 5, tzinfo=UTC))
    assert (stats.generated, stats.skipped, stats.failed, stats.errors) == (1, 0, 0, [])

    text = auto_sheet(cfg, conn, s)
    assert text.startswith("auto-generated, unverified\nNobody - River Road\n")
    assert "[ch]C[/ch]" in text and "[ch]G[/ch]" in text and "Walking down" in text

    [kept] = kept_files(conn, s.id)
    assert (kept.name, kept.kept_rank, kept.path) == (
        AUTO_SHEET,
        1,
        f"Nobody/River Road/{AUTO_SHEET}",
    )
    v = get_version(conn, kept.version_id)
    assert (v.provider, v.tab_id, v.song_id, v.slot, v.kind) == (
        "auto",
        str(s.id),
        s.id,
        "sheet",
        "auto",
    )
    assert (v.rating, v.votes, v.version, v.label) == (0, 0, 1, None)
    assert v.url == "file://" + s.audio_path
    assert v.raw == {"audio": s.audio_path, "model": "btc_large_voca", "lyrics": "plain", "key": "G"}
    assert v.fetched_at == "2026-10-18T04:05:00Z"

    song = get_song(conn, s.id)
    assert song.status == "found"
    assert song.autochords_mtime == song.audio_mtime

    info = json.loads((song_dir(cfg.library_dir, song) / "info.json").read_text(encoding="utf-8"))
    assert info["status"] == "found"
    assert [(f["name"], f["provider"], f["kind"]) for f in info["files"]] == [
        (AUTO_SHEET, "auto", "auto")
    ]


def test_an_auto_sheet_from_youtube_audio_says_which_video_it_came_from(conn, cfg, tmp_path):
    # youtube_fetch.py links the audio as a purchase is linked, and records the video it came from.
    from caracole.db import kv_set_json
    from caracole.render import _auto_sheet

    s = with_audio(conn, tmp_path, add_song(conn, "Radiohead", "Creep"), name="youtube/1-XFkzRNyygfk.m4a",
                   lyrics_status="found", lyrics_json=lyrics_json(plain="When you were here before"))
    video = {"id": "XFkzRNyygfk", "title": "Creep", "channel": "Radiohead - Topic", "duration": 238.0,
             "url": "https://www.youtube.com/watch?v=XFkzRNyygfk"}
    kv_set_json(conn, f"youtube:{s.id}", {"video": video, "source": "search", "audio": s.audio_path})
    run(conn, cfg)
    text = auto_sheet(cfg, conn, s)
    assert text.startswith("auto-generated, unverified\nRadiohead - Creep\n"
                           "Audio from YouTube: Creep (Radiohead - Topic), https://www.youtube.com/watch?v=XFkzRNyygfk\n\n")
    [kept] = kept_files(conn, s.id)
    v = get_version(conn, kept.version_id)
    assert v.url == video["url"]  # info.json then names the video, not a file of caracole's
    assert v.raw["youtube"] == video and v.raw["audio"] == s.audio_path
    info = json.loads((song_dir(cfg.library_dir, s) / "info.json").read_text(encoding="utf-8"))
    assert info["files"][0]["url"] == video["url"]
    # The PDF, made from the sheet without its two header lines, says it as its first line.
    assert _auto_sheet(cfg.library_dir, kept).markup.startswith("Audio from YouTube: Creep (Radiohead - Topic)")


def test_a_purchase_that_took_the_youtube_audios_place_is_a_purchase_again(conn, cfg, tmp_path):
    from caracole.db import kv_set_json

    s = with_audio(conn, tmp_path, add_song(conn, "Radiohead", "Creep"), name="Radiohead - Creep.wav")
    kv_set_json(conn, f"youtube:{s.id}", {"video": {"id": "XFkzRNyygfk", "title": "Creep"}, "source": "search",
                                          "audio": str(tmp_path / "cache" / "youtube" / "1-XFkzRNyygfk.m4a")})
    run(conn, cfg)
    assert "YouTube" not in auto_sheet(cfg, conn, s)
    [kept] = kept_files(conn, s.id)
    assert get_version(conn, kept.version_id).url == "file://" + s.audio_path


class Heard(FakeRecognizer):
    """A recognizer that hears the given chords, as (start, end, label)."""

    def __init__(self, *segments: tuple[float, float, str]):
        super().__init__()
        self.segments = [ChordSegment(*s) for s in segments]

    def recognize(self, path):
        super().recognize(path)
        return self.segments


def test_the_auto_sheet_keeps_the_key_of_the_chords_the_model_heard(conn, cfg, tmp_path):
    # Am rings for most of the song, F, C and G pass by: A minor, weighed by time.
    heard = Heard((0.0, 0.5, "N"), (0.5, 4.0, "Am"), (4.0, 5.0, "F"), (5.0, 6.0, "C"),
                  (6.0, 7.0, "G"), (7.0, 10.0, "Am"))
    s = with_audio(conn, tmp_path, add_song(conn, "Nobody", "River Road"))
    run(conn, cfg, heard)
    [kept] = kept_files(conn, s.id)
    assert get_version(conn, kept.version_id).raw["key"] == "A minor"
    info = json.loads((song_dir(cfg.library_dir, s) / "info.json").read_text(encoding="utf-8"))
    assert (info["key"], info["key_source"]) == ("A minor", "audio")


def test_an_auto_sheet_of_no_chords_keeps_no_key(conn, cfg, tmp_path):
    s = with_audio(conn, tmp_path, add_song(conn, "Nobody", "River Road"))
    run(conn, cfg, Heard((0.0, 10.0, "N")))
    [kept] = kept_files(conn, s.id)
    assert "key" not in get_version(conn, kept.version_id).raw
    info = json.loads((song_dir(cfg.library_dir, s) / "info.json").read_text(encoding="utf-8"))
    assert (info["key"], info["key_source"]) == (None, None)


def test_pending_selects_only_songs_without_human_sheet(conn, cfg, tmp_path):
    new = with_audio(conn, tmp_path, add_song(conn, "A", "New Purchase"))
    human = with_audio(conn, tmp_path, add_song(conn, "A", "Has A Human Sheet"))
    keep_human_sheet(conn, cfg, human)
    ignored = with_audio(conn, tmp_path, add_song(conn, "A", "Ignored By Status"), status="ignored")
    in_overrides = with_audio(conn, tmp_path, add_song(conn, "A", "Ignored In Overrides"))
    gone = with_audio(conn, tmp_path, add_song(conn, "A", "Audio Deleted"))
    Path(gone.audio_path).unlink()
    add_song(conn, "A", "No Audio")

    rec = FakeRecognizer()
    stats = run(conn, cfg, rec, overrides=Overrides(ignore=frozenset({in_overrides.key})))
    assert rec.calls == [Path(new.audio_path)]
    assert (stats.generated, stats.skipped, stats.failed) == (1, 4, 0)
    assert get_song(conn, human.id).autochords_mtime is None
    assert get_song(conn, ignored.id).status == "ignored"


def test_up_to_date_songs_are_left_alone(conn, cfg, tmp_path):
    s = with_audio(conn, tmp_path, add_song(conn, "A", "T"))
    run(conn, cfg)
    rec = FakeRecognizer()
    stats = run(conn, cfg, rec)
    assert rec.calls == []
    assert (stats.generated, stats.skipped, stats.failed) == (0, 1, 0)
    assert get_song(conn, s.id).status == "found"


def test_changed_audio_is_generated_again(conn, cfg, tmp_path):
    s = with_audio(conn, tmp_path, add_song(conn, "A", "T"))
    run(conn, cfg)
    # A better copy synced in later: Syncthing keeps the sender's mtime, which may even be older.
    update_song(conn, s.id, audio_mtime=get_song(conn, s.id).audio_mtime - 3600)
    rec = FakeRecognizer()
    assert run(conn, cfg, rec).generated == 1
    assert rec.calls == [Path(s.audio_path)]
    song = get_song(conn, s.id)
    assert song.autochords_mtime == song.audio_mtime
    assert [f.name for f in kept_files(conn, s.id)] == [AUTO_SHEET]


def test_a_human_sheet_stops_regeneration(conn, cfg, tmp_path):
    s = with_audio(conn, tmp_path, add_song(conn, "A", "T"))
    run(conn, cfg)
    keep_human_sheet(conn, cfg, s)
    update_song(conn, s.id, audio_mtime=get_song(conn, s.id).audio_mtime + 60)
    rec = FakeRecognizer()
    assert run(conn, cfg, rec).skipped == 1
    assert rec.calls == []


# --- lyrics ----------------------------------------------------------------------------------

SYNCED = "[00:00.50]Walking down the river road\n[00:05.20]Singing to the morning light\n"


def test_synced_lyrics_used_when_their_duration_matches_the_audio(conn, cfg, tmp_path):
    s = with_audio(
        conn,
        tmp_path,
        add_song(conn, "Nobody", "River Road"),
        seconds=10.0,
        lyrics_status="found",
        lyrics_json=lyrics_json(synced=SYNCED, duration=11.5),
    )
    run(conn, cfg)
    lines = auto_sheet(cfg, conn, s).splitlines()
    assert "[Lyrics]" not in lines
    i = lines.index("Walking down the river road")
    j = lines.index("Singing to the morning light")
    assert lines[i - 1].startswith("[ch]C[/ch]") and lines[j - 1].startswith("[ch]G[/ch]")
    assert get_version(conn, kept_files(conn, s.id)[0].version_id).raw["lyrics"] == "synced"


def test_plain_lyrics_used_when_the_synced_duration_does_not_match(conn, cfg, tmp_path):
    # LRCLIB's record is another cut of the song: its timings would put chords on the wrong lines.
    s = with_audio(
        conn,
        tmp_path,
        add_song(conn, "Nobody", "River Road"),
        seconds=10.0,
        lyrics_status="found",
        lyrics_json=lyrics_json(synced=SYNCED, duration=12.5),
    )
    run(conn, cfg)
    lines = auto_sheet(cfg, conn, s).splitlines()
    assert lines[3] == "[Chords]"
    assert lines[lines.index("[Lyrics]") + 1 :] == [
        "Walking down the river road",
        "Singing to the morning light",
    ]
    assert get_version(conn, kept_files(conn, s.id)[0].version_id).raw["lyrics"] == "plain"


def test_plain_only_chinese_lyrics(conn, cfg, tmp_path):
    plain = "範例歌詞 第一行\n範例歌詞 第二行"
    s = with_audio(
        conn,
        tmp_path,
        add_song(conn, "宋冬野", "斑马斑马", duration_ms=253000),
        lyrics_status="found",
        lyrics_json=lyrics_json(plain=plain, duration=253.1),
    )
    assert run(conn, cfg).generated == 1
    song = get_song(conn, s.id)
    path = song_dir(cfg.library_dir, song) / AUTO_SHEET
    assert path == cfg.library_dir / "宋冬野" / "斑马斑马" / AUTO_SHEET
    text = path.read_text(encoding="utf-8")
    assert "宋冬野 - 斑马斑马" in text and text.endswith(
        "[Lyrics]\n範例歌詞 第一行\n範例歌詞 第二行\n"
    )
    assert song.status == "found"


def test_instrumental_gets_a_chord_chart_only(conn, cfg, tmp_path):
    s = with_audio(
        conn,
        tmp_path,
        add_song(conn, "A", "Interlude"),
        lyrics_status="instrumental",
        lyrics_json=lyrics_json(instrumental=True),
    )
    run(conn, cfg)
    text = auto_sheet(cfg, conn, s)
    assert "[Chords]" in text and "[Lyrics]" not in text


def test_sheet_made_before_the_lyrics_arrived_is_made_again_once(conn, cfg, tmp_path):
    s = with_audio(conn, tmp_path, add_song(conn, "A", "T"))  # lyrics still pending
    run(conn, cfg)
    assert "[Lyrics]" not in auto_sheet(cfg, conn, s)

    update_song(
        conn, s.id, lyrics_status="found", lyrics_json=lyrics_json(plain="Finally the words")
    )
    rec = FakeRecognizer()
    assert run(conn, cfg, rec).generated == 1
    assert "Finally the words" in auto_sheet(cfg, conn, s)

    rec = FakeRecognizer()
    assert (run(conn, cfg, rec).skipped, rec.calls) == (1, [])


def test_missing_lyrics_are_not_waited_for(conn, cfg, tmp_path):
    s = with_audio(conn, tmp_path, add_song(conn, "A", "T"), lyrics_status="missing")
    assert run(conn, cfg).generated == 1
    rec = FakeRecognizer()
    assert (run(conn, cfg, rec).skipped, rec.calls) == (1, [])
    assert get_song(conn, s.id).status == "found"


def test_build_sheet_gets_the_song_beats_and_lyrics(conn, cfg, tmp_path, monkeypatch):
    import caracole.autochords.run as ac_run

    seen = {}

    def spy(segments, **kwargs):
        seen.update(kwargs, segments=list(segments))
        return "auto-generated, unverified\nA - T\n"

    monkeypatch.setattr(ac_run, "build_sheet", spy)
    with_audio(
        conn,
        tmp_path,
        add_song(conn, "Nobody", "River Road - Remastered 2011"),
        lyrics_status="found",
        lyrics_json=lyrics_json(synced=SYNCED, duration=10.0),
    )
    run(conn, cfg)
    assert seen["segments"] == [ChordSegment(0.0, 5.0, "C"), ChordSegment(5.0, 10.0, "G")]
    assert (seen["title"], seen["artist"]) == ("River Road - Remastered 2011", "Nobody")
    assert seen["synced"] == SYNCED
    assert seen["plain"] == "Walking down the river road\nSinging to the morning light"
    assert (seen["beats"], seen["downbeats"]) == (BEATS, DOWNBEATS)


# --- the models ------------------------------------------------------------------------------


def test_default_models_are_built_once_from_the_config(conn, cfg, tmp_path, monkeypatch):
    import caracole.autochords.run as ac_run

    built, tracked = [], []

    class Recognizer(FakeRecognizer):
        def __init__(self, weights, *, device="cpu"):
            super().__init__()
            built.append((Path(weights), device))

    def detect_beats(path, checkpoint, *, device="cpu"):
        tracked.append((Path(path), Path(checkpoint), device))
        return BEATS, DOWNBEATS

    monkeypatch.setattr(ac_run, "BTCRecognizer", Recognizer)
    monkeypatch.setattr(ac_run, "detect_beats", detect_beats)
    weights, checkpoint = tmp_path / "btc.pt", tmp_path / "final0.ckpt"
    weights.write_bytes(b"weights")
    checkpoint.write_bytes(b"checkpoint")
    cfg = replace(
        cfg,
        autochords=AutochordsConfig(
            btc_weights=weights, beat_checkpoint=checkpoint, device="cuda:1"
        ),
    )
    songs = [with_audio(conn, tmp_path, add_song(conn, "A", title)) for title in ("One", "Two")]

    assert autochords_pending(conn, cfg).generated == 2
    assert built == [(weights, "cuda:1")]
    # A test tone first (test_default_models_first_read_a_test_tone), then each song.
    tone, *rest = tracked
    assert tone[1:] == (checkpoint, "cuda:1")
    assert sorted(rest) == sorted((Path(s.audio_path), checkpoint, "cuda:1") for s in songs)


def test_default_models_first_read_a_test_tone(conn, cfg, tmp_path, monkeypatch):
    import caracole.autochords.run as ac_run

    heard = []

    def hear(model, path):
        with wave.open(str(path)) as w:
            heard.append((model, Path(path), w.getnframes() / w.getframerate()))

    class Recognizer(FakeRecognizer):
        def __init__(self, weights, *, device="cpu"):
            super().__init__()

        def recognize(self, path):
            hear("BTC", path)
            return super().recognize(path)

    def detect_beats(path, checkpoint, *, device="cpu"):
        hear("beat_this", path)
        return BEATS, DOWNBEATS

    monkeypatch.setattr(ac_run, "BTCRecognizer", Recognizer)
    monkeypatch.setattr(ac_run, "detect_beats", detect_beats)
    s = with_audio(conn, tmp_path, add_song(conn, "A", "T"), seconds=10.0)
    assert autochords_pending(conn, with_model_files(cfg, tmp_path)).generated == 1
    tone = heard[0][1]
    assert sorted(heard[:2]) == [("BTC", tone, 2.0), ("beat_this", tone, 2.0)]
    assert heard[2:] == [("BTC", Path(s.audio_path), 10.0), ("beat_this", Path(s.audio_path), 10.0)]
    assert not tone.exists()


def test_models_that_cannot_read_a_test_tone_are_a_setup_problem(conn, cfg, tmp_path, monkeypatch):
    # As under a sandbox that stops them (MemoryDenyWriteExecute, docs/deploy.md): every
    # file would fail, so none is blamed, and the purchase is made once the setup is fixed.
    import caracole.autochords.run as ac_run

    class Recognizer(FakeRecognizer):
        def __init__(self, weights, *, device="cpu"):
            super().__init__()

        def recognize(self, path):
            super().recognize(path)
            raise RuntimeError(f"could not create a primitive for {str(path)!r}")

    monkeypatch.setattr(ac_run, "BTCRecognizer", Recognizer)
    monkeypatch.setattr(
        ac_run, "detect_beats", lambda path, checkpoint, device="cpu": (BEATS, DOWNBEATS)
    )
    s = with_audio(conn, tmp_path, add_song(conn, "A", "T"))
    stats = autochords_pending(conn, with_model_files(cfg, tmp_path))
    assert (stats.generated, stats.failed, stats.failures) == (0, 1, [])
    assert stats.errors == [
        "BTC fails on a test tone: RuntimeError: could not create a primitive for 'test-tone.wav'"
    ]
    assert kv_get(conn, failed_key(s)) is None and kv_get_json(conn, STATUS)["failed"] == []

    rec = FakeRecognizer()
    assert run(conn, cfg, rec).generated == 1 and rec.calls == [Path(s.audio_path)]


# --- failures --------------------------------------------------------------------------------


def test_missing_weights_fail_every_pending_song_and_are_reported_once(conn, cfg, tmp_path, caplog):
    cfg = replace(
        cfg,
        autochords=AutochordsConfig(
            btc_weights=tmp_path / "nope.pt", beat_checkpoint=make_wav(tmp_path / "beats.ckpt", 0.1)
        ),
    )
    a = with_audio(conn, tmp_path, add_song(conn, "A", "One"))
    b = with_audio(conn, tmp_path, add_song(conn, "A", "Two"))
    keep_human_sheet(conn, cfg, with_audio(conn, tmp_path, add_song(conn, "A", "Three")))
    beats = FakeBeats()
    with caplog.at_level(logging.ERROR, logger="caracole.autochords.run"):
        stats = autochords_pending(conn, cfg, beats_fn=beats)
    assert (stats.generated, stats.skipped, stats.failed) == (0, 1, 2)
    assert len(stats.errors) == 1 and "BTC weights not found" in stats.errors[0]
    assert [r.getMessage().count("BTC weights not found") for r in caplog.records] == [1]
    assert beats.calls == []
    for s in (a, b):
        song = get_song(conn, s.id)
        assert (song.status, song.autochords_mtime) == ("wanted", None)
        assert kept_files(conn, s.id) == []


def test_unconfigured_models_say_how_to_configure_them(conn, cfg, tmp_path):
    with_audio(conn, tmp_path, add_song(conn, "A", "One"))
    stats = autochords_pending(conn, cfg)  # the cfg fixture has no [autochords] paths
    assert stats.failed == 1
    assert any("CARACOLE_BTC_WEIGHTS" in e for e in stats.errors)
    assert any("CARACOLE_BEAT_CHECKPOINT" in e for e in stats.errors)


def test_missing_beat_checkpoint_is_reported_once(conn, cfg, tmp_path):
    cfg = replace(cfg, autochords=AutochordsConfig(beat_checkpoint=tmp_path / "final0.ckpt"))
    for title in ("One", "Two"):
        with_audio(conn, tmp_path, add_song(conn, "A", title))
    rec = FakeRecognizer()
    stats = autochords_pending(conn, cfg, recognizer=rec)
    assert (stats.failed, rec.calls) == (2, [])
    assert stats.errors == [f"beat_this checkpoint not found: {tmp_path / 'final0.ckpt'}"]


def test_a_file_that_will_not_decode_fails_alone(conn, cfg, tmp_path, caplog):
    bad = with_audio(conn, tmp_path, add_song(conn, "A", "Broken Download"), name="bad.wav")
    good = with_audio(conn, tmp_path, add_song(conn, "A", "Fine"), name="good.wav")
    with caplog.at_level(logging.INFO, logger="caracole.autochords.run"):
        stats = run(conn, cfg, FakeRecognizer(fail_on=("bad.wav",)))
    assert (stats.generated, stats.failed, stats.errors) == (1, 1, [])
    assert failures(stats) == [("A - Broken Download", unreadable(bad.audio_path), bad.audio_path)]
    # Named in the journal, as a warning: the purchase's problem, not caracole's.
    named = [r.levelname for r in caplog.records if "Format not recognised" in r.getMessage()]
    assert named == ["WARNING"]
    song = get_song(conn, bad.id)
    assert (song.status, song.autochords_mtime, kept_files(conn, bad.id)) == ("wanted", None, [])
    assert get_song(conn, good.id).status == "found"


@pytest.mark.parametrize("change", ["downloaded again", "converted"])
def test_a_file_that_failed_is_tried_again_only_once_it_changes(conn, cfg, tmp_path, change):
    bad = with_audio(conn, tmp_path, add_song(conn, "A", "Broken Download"), name="bad.wav")
    run(conn, cfg, FakeRecognizer(fail_on=("bad.wav",)))

    # The same file on the nights after: not decoded again, and still listed.
    for _ in range(2):
        rec = FakeRecognizer(fail_on=("bad.wav",))
        stats = run(conn, cfg, rec)
        assert rec.calls == []
        assert (stats.generated, stats.skipped, stats.failed, stats.errors) == (0, 0, 1, [])
        assert failures(stats) == [
            ("A - Broken Download", unreadable(bad.audio_path), bad.audio_path)
        ]

    # What scan_music records when the file changes.
    if change == "downloaded again":  # under the same name, so only its mtime changes
        update_song(conn, bad.id, audio_mtime=get_song(conn, bad.id).audio_mtime + 60)
    else:  # converted to another file, and the original removed
        Path(bad.audio_path).unlink()
        flac = make_wav(tmp_path / "music" / "bad.flac")
        update_song(conn, bad.id, audio_path=str(flac), audio_mtime=os.stat(flac).st_mtime)
    rec = FakeRecognizer()
    stats = run(conn, cfg, rec)
    song = get_song(conn, bad.id)
    assert rec.calls == [Path(song.audio_path)]
    assert (stats.generated, stats.failed, failures(stats)) == (1, 0, [])
    assert song.status == "found" and kv_get(conn, failed_key(bad)) is None


def test_a_replacement_that_fails_too_is_listed_with_its_own_error(conn, cfg, tmp_path):
    bad = with_audio(conn, tmp_path, add_song(conn, "A", "Broken Download"), name="bad.wav")
    run(conn, cfg, FakeRecognizer(fail_on=("bad.wav",)))
    m4a = make_wav(tmp_path / "music" / "bad.m4a")
    update_song(conn, bad.id, audio_path=str(m4a), audio_mtime=os.stat(m4a).st_mtime)
    rec = FakeRecognizer(fail_on=("bad.m4a",))
    stats = run(conn, cfg, rec)
    assert rec.calls == [m4a]
    assert failures(stats) == [("A - Broken Download", unreadable(m4a), str(m4a))]
    rec = FakeRecognizer(fail_on=("bad.m4a",))
    assert (run(conn, cfg, rec).failed, rec.calls) == (1, [])


def test_each_run_records_its_outcome_for_the_to_do_page(conn, cfg, tmp_path):
    bad = with_audio(conn, tmp_path, add_song(conn, "宋冬野", "斑马斑马"), name="斑马斑马.m4a")
    with_audio(conn, tmp_path, add_song(conn, "A", "Fine"), name="fine.wav")
    keep_human_sheet(conn, cfg, with_audio(conn, tmp_path, add_song(conn, "A", "Charted")))
    add_song(conn, "A", "Not Bought")
    night = datetime(2026, 10, 18, 4, 12, tzinfo=UTC)
    run(conn, cfg, FakeRecognizer(fail_on=("斑马斑马.m4a",)), now=night)
    failed = [
        {"song": "宋冬野 - 斑马斑马", "error": unreadable(bad.audio_path), "audio": bad.audio_path}
    ]
    assert kv_get_json(conn, STATUS) == {
        "at": "2026-10-18T04:12:00Z",
        "generated": 1,
        "skipped": 1,
        "failed": failed,
    }
    # The next night: one sheet up to date, one human sheet, the same unreadable file.
    run(conn, cfg, now=night.replace(day=19))
    assert kv_get_json(conn, STATUS) == {
        "at": "2026-10-19T04:12:00Z",
        "generated": 0,
        "skipped": 2,
        "failed": failed,
    }


@pytest.mark.parametrize(
    ("error", "listed"),
    [
        (
            lambda path: RuntimeError("Could not open input\nffmpeg version 8.0\n…"),
            "RuntimeError: Could not open input",
        ),
        (lambda path: EOFError(), "EOFError"),
        (lambda path: ValueError("x" * 500), "ValueError: " + "x" * 287 + "…"),
        # The page shows where the file is, so the message only names it (torchcodec's, in full).
        (
            lambda path: RuntimeError(
                f"Failed to create AudioDecoder for {path}: SingleStreamDecoder, /build/source/src/"
                f"torchcodec/_core/SingleStreamDecoder.cpp:41, Could not open input file: {path} "
                "Invalid data found when processing input"
            ),
            (
                "RuntimeError: Failed to create AudioDecoder for 斑马斑马.mp3: SingleStreamDecoder, "
                "/build/source/src/torchcodec/_core/SingleStreamDecoder.cpp:41, Could not open "
                "input file: 斑马斑马.mp3 Invalid data found when processing input"
            ),
        ),
    ],
)
def test_the_listed_error_is_one_short_line(conn, cfg, tmp_path, error, listed):
    class Failing(FakeRecognizer):
        def recognize(self, path):
            raise error(path)

    folder = tmp_path / "Music" / "宋冬野" / "安和桥北"  # a long path, repeated in the message
    with_audio(conn, folder, add_song(conn, "A", "T"), name="斑马斑马.mp3")
    [(_, message, _)] = failures(run(conn, cfg, Failing()))
    assert message == listed


def test_a_failure_is_listed_only_while_the_song_still_needs_an_auto_sheet(conn, cfg, tmp_path):
    charted = with_audio(conn, tmp_path, add_song(conn, "A", "Charted Since"), name="a.wav")
    ignored = with_audio(conn, tmp_path, add_song(conn, "A", "Ignored Since"), name="b.wav")
    removed = with_audio(conn, tmp_path, add_song(conn, "A", "Removed Since"), name="c.wav")
    assert run(conn, cfg, FakeRecognizer(fail_on=("a.wav", "b.wav", "c.wav"))).failed == 3

    keep_human_sheet(conn, cfg, charted)
    update_song(conn, ignored.id, status="ignored")
    Path(removed.audio_path).unlink()
    update_song(conn, removed.id, audio_path=None, audio_mtime=None)  # as scan_music does
    stats = run(conn, cfg)
    assert (stats.skipped, stats.failed, stats.failures) == (2, 0, [])
    assert kv_get_json(conn, STATUS)["failed"] == []
    assert kv_get(conn, failed_key(removed)) is None  # the file is gone, and its failure with it

    # Wanted again, with the same file: still not worth decoding again.
    update_song(conn, ignored.id, status="wanted")
    rec = FakeRecognizer()
    stats = run(conn, cfg, rec)
    assert rec.calls == []
    assert failures(stats) == [
        ("A - Ignored Since", unreadable(ignored.audio_path), ignored.audio_path)
    ]


def test_missing_models_blame_no_purchase(conn, cfg, tmp_path):
    bad = with_audio(conn, tmp_path, add_song(conn, "A", "Broken Download"), name="bad.wav")
    run(conn, cfg, FakeRecognizer(fail_on=("bad.wav",)))
    new = with_audio(conn, tmp_path, add_song(conn, "A", "New Purchase"), name="new.wav")

    broken = replace(cfg, autochords=AutochordsConfig(btc_weights=tmp_path / "nope.pt"))
    stats = autochords_pending(conn, broken, beats_fn=FakeBeats())
    assert (stats.generated, stats.failed) == (0, 2)
    assert len(stats.errors) == 1 and "BTC weights not found" in stats.errors[0]
    # The file that failed on its own stays listed; the new one only waits for the models.
    assert failures(stats) == [("A - Broken Download", unreadable(bad.audio_path), bad.audio_path)]
    assert [f["song"] for f in kv_get_json(conn, STATUS)["failed"]] == ["A - Broken Download"]
    assert kv_get(conn, failed_key(new)) is None

    rec = FakeRecognizer(fail_on=("bad.wav",))
    assert run(conn, cfg, rec).generated == 1
    assert rec.calls == [Path(new.audio_path)]


def test_a_sheet_that_cannot_be_kept_is_not_blamed_on_the_purchase(
    conn, cfg, tmp_path, monkeypatch
):
    import caracole.autochords.run as ac_run

    s = with_audio(conn, tmp_path, add_song(conn, "A", "T"))

    def disk_full(*args, **kwargs):
        raise OSError(28, "No space left on device")

    with monkeypatch.context() as m:
        m.setattr(ac_run, "keep_file", disk_full)
        stats = run(conn, cfg)
    assert (stats.generated, stats.failed, stats.failures) == (0, 1, [])
    assert stats.errors == ["A - T: OSError: [Errno 28] No space left on device"]
    assert kv_get_json(conn, STATUS)["failed"] == [] and kv_get(conn, failed_key(s)) is None
    # With space again, the same file is tried again.
    rec = FakeRecognizer()
    assert run(conn, cfg, rec).generated == 1 and rec.calls == [Path(s.audio_path)]


def test_nothing_pending_loads_no_model(conn, cfg, tmp_path):
    cfg = replace(cfg, autochords=AutochordsConfig(btc_weights=tmp_path / "nope.pt"))
    s = with_audio(conn, tmp_path, add_song(conn, "A", "T"))
    keep_human_sheet(conn, cfg, s)
    stats = autochords_pending(conn, cfg)
    assert (stats.generated, stats.skipped, stats.failed, stats.errors) == (0, 1, 0, [])


# --- a lookup goes between two songs -------------------------------------------------------------

LOOKUP = r"""
import sys
from pathlib import Path
from caracole.commands import _common
from caracole.config import load_config

cfg = load_config(Path(sys.argv[1]))
with _common.exclusive(cfg, "get Nobody - Lantern Shore", interactive=True):
    with open(sys.argv[2], "a", encoding="utf-8") as log:
        log.write("lookup\n")
"""


@pytest.mark.slow
def test_a_lookup_waiting_for_the_lock_takes_it_between_two_songs(conn, cfg, tmp_path):
    # A song's auto sheet takes minutes, and the unit runs for hours: a lookup never waits for all of it.
    import time

    from caracole.commands import _common

    from conftest import subprocess_pythonpath

    with_audio(conn, tmp_path, add_song(conn, "Nobody", "River Road", added_at="2026-10-02T00:00:00Z"),
               name="first.wav")
    with_audio(conn, tmp_path, add_song(conn, "Nobody", "Lantern Shore", added_at="2026-10-01T00:00:00Z"),
               name="second.wav")
    config = tmp_path / "caracole.toml"
    config.write_text(f'state_dir = "{cfg.state_dir}"\ncache_dir = "{cfg.cache_dir}"\n'
                      f'library_dir = "{cfg.library_dir}"\n', encoding="utf-8")
    log = tmp_path / "order.log"
    env = {**os.environ, "PYTHONPATH": subprocess_pythonpath(Path(__file__).parents[1] / "src")}
    lookups: list[subprocess.Popen] = []

    class Busy(FakeRecognizer):
        def recognize(self, path):
            with open(log, "a", encoding="utf-8") as out:
                out.write(Path(path).name + "\n")
            if not lookups:  # while the first song is worked on, a lookup asks for the lock
                lookups.append(subprocess.Popen([sys.executable, "-c", LOOKUP, str(config), str(log)], env=env))
                deadline = time.time() + 20
                while not _common.lookups_waiting(cfg) and time.time() < deadline:
                    time.sleep(0.05)
            return super().recognize(path)

    try:
        with _common.exclusive(cfg, "autochords"):
            stats = run(conn, cfg, recognizer=Busy(), between=lambda: _common.hand_over(cfg, conn))
        assert lookups[0].wait(30) == 0
    finally:
        for p in lookups:
            p.kill()
    assert stats.generated == 2
    assert log.read_text(encoding="utf-8").splitlines() == ["first.wav", "lookup", "second.wav"]


def test_after_a_handoff_the_songs_and_overrides_are_read_again(conn, cfg, tmp_path):
    with_audio(conn, tmp_path, add_song(conn, "Nobody", "River Road", added_at="2026-10-02T00:00:00Z"),
               name="first.wav")
    with_audio(conn, tmp_path, add_song(conn, "Nobody", "Lantern Shore", added_at="2026-10-01T00:00:00Z"),
               name="second.wav")
    calls = []

    def between() -> bool:  # a lookup had the lock, and you ignored the second song meanwhile
        calls.append(1)
        cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
        cfg.overrides_file.write_text('[ignore]\nsongs = ["Nobody - Lantern Shore"]\n', encoding="utf-8")
        return True

    recognizer = FakeRecognizer()
    stats = run(conn, cfg, recognizer=recognizer, overrides=Overrides(), between=between)
    assert calls == [1]  # between the two songs
    assert [p.name for p in recognizer.calls] == ["first.wav"] and stats.skipped == 1


def test_the_command_hands_the_lock_over_between_songs(tmp_path, monkeypatch, models_importable):
    import caracole.autochords.run as ac_run
    from caracole.commands import _common

    handed = []
    monkeypatch.setattr(_common, "hand_over", lambda cfg, conn=None: handed.append(conn is not None) or False)

    def pending(conn, cfg, **kwargs):
        kwargs["between"]()
        return AutoStats()

    monkeypatch.setattr(ac_run, "autochords_pending", pending)
    result = invoke(write_config(tmp_path))
    assert result.exit_code == 0, result.output
    assert handed == [True]


def test_summary():
    assert (
        AutoStats(generated=2, skipped=5, failed=1).summary() == "2 generated, 5 skipped, 1 failed"
    )


# --- the command ------------------------------------------------------------------------------


def write_config(tmp_path: Path, **autochords: Path) -> Path:
    lines = [
        f'{k} = "{tmp_path / v}"'
        for k, v in (
            ("library_dir", "lib"),
            ("music_dir", "music"),
            ("state_dir", "state"),
            ("cache_dir", "cache"),
        )
    ]
    if autochords:
        lines.append("[autochords]")
        lines += [f'{k} = "{v}"' for k, v in autochords.items()]
    p = tmp_path / "caracole.toml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def invoke(config: Path):
    return CliRunner().invoke(build_app(), ["--config", str(config), "autochords"])


@pytest.fixture
def models_importable(monkeypatch):
    import caracole.commands.autochords as cmd

    monkeypatch.setattr(cmd, "find_spec", lambda name: object())
    # Only the model files a test configures: `nix develop .#autochords` sets both variables, and
    # its real beat_this would read the test tone (seconds, and torch in the test process).
    monkeypatch.delenv("CARACOLE_BTC_WEIGHTS", raising=False)
    monkeypatch.delenv("CARACOLE_BEAT_CHECKPOINT", raising=False)


def test_command_without_the_models_says_which_package_has_them(tmp_path, monkeypatch):
    import caracole.commands.autochords as cmd

    monkeypatch.setattr(cmd, "find_spec", lambda name: None if name == "torch" else object())
    result = invoke(write_config(tmp_path))
    assert result.exit_code == 1
    assert (
        "this caracole was built without auto-chords; use the flake's packages.autochords"
        in result.output
    )
    assert "torch" in result.output


def test_command_scans_music_then_generates(tmp_path, monkeypatch, models_importable):
    import caracole.autochords.run as ac_run

    class Recognizer(FakeRecognizer):
        def __init__(self, weights, *, device="cpu"):
            super().__init__()
            assert (Path(weights), device) == (tmp_path / "btc.pt", "cpu")

    monkeypatch.setattr(ac_run, "BTCRecognizer", Recognizer)
    monkeypatch.setattr(
        ac_run, "detect_beats", lambda path, checkpoint, device="cpu": (BEATS, DOWNBEATS)
    )
    (tmp_path / "btc.pt").write_bytes(b"weights")
    (tmp_path / "final0.ckpt").write_bytes(b"checkpoint")
    config = write_config(
        tmp_path, btc_weights=tmp_path / "btc.pt", beat_checkpoint=tmp_path / "final0.ckpt"
    )
    from caracole import db

    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    add_song(conn, "宋冬野", "斑马斑马", duration_ms=None)
    # Dropped into Music/ after the night's run: only the command's own scan links it.
    make_wav(tmp_path / "music" / "宋冬野 - 斑马斑马.wav", 3.0)

    result = invoke(config)
    assert result.exit_code == 0, result.output
    assert "Music: 1 file, 1 linked" in result.output
    assert "auto-chords: 1 generated, 0 skipped, 0 failed" in result.output
    assert (tmp_path / "lib" / "宋冬野" / "斑马斑马" / AUTO_SHEET).is_file()


def bought(tmp_path: Path):
    """The database, with a song whose purchase was dropped into Music/ after the night's run."""
    from caracole import db

    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    add_song(conn, "Nobody", "River Road", duration_ms=None)
    make_wav(tmp_path / "music" / "Nobody - River Road.wav", 3.0)
    return conn


def test_command_exits_0_when_a_purchase_cannot_be_read(tmp_path, monkeypatch, models_importable):
    # A file that will never decode is listed on the to-do page, not an alert every night.
    fake_default_models(monkeypatch, fail_on=("Nobody - River Road.wav",))
    conn = bought(tmp_path)
    config = write_config(tmp_path, **model_files(tmp_path))
    for _ in range(2):
        result = invoke(config)
        assert result.exit_code == 0, result.output
        assert "auto-chords: 0 generated, 0 skipped, 1 failed" in result.output
        failed = kv_get_json(conn, STATUS, {}).get("failed")
        assert [f["song"] for f in failed or []] == ["Nobody - River Road"]


def test_command_exits_1_when_the_weights_are_missing(tmp_path, models_importable):
    conn = bought(tmp_path)
    result = invoke(write_config(tmp_path, btc_weights=tmp_path / "missing.pt"))
    assert result.exit_code == 1, result.output
    assert "auto-chords: 0 generated, 0 skipped, 1 failed" in result.output
    assert kv_get_json(conn, STATUS, {}).get("failed") == []  # no purchase is blamed


def test_command_exits_1_when_the_beat_checkpoint_is_missing(
    tmp_path, monkeypatch, models_importable
):
    fake_default_models(monkeypatch)
    files = model_files(tmp_path)
    files["beat_checkpoint"].unlink()
    conn = bought(tmp_path)
    result = invoke(write_config(tmp_path, **files))
    assert result.exit_code == 1, result.output
    assert "auto-chords: 0 generated, 0 skipped, 1 failed" in result.output
    assert kv_get_json(conn, STATUS, {}).get("failed") == []


def test_command_exits_1_when_the_models_fail_on_a_test_tone(
    tmp_path, monkeypatch, models_importable
):
    import caracole.autochords.run as ac_run

    def broken(path, checkpoint, device="cpu"):
        raise RuntimeError("could not create a primitive")

    fake_default_models(monkeypatch)
    monkeypatch.setattr(ac_run, "detect_beats", broken)
    conn = bought(tmp_path)
    result = invoke(write_config(tmp_path, **model_files(tmp_path)))
    assert result.exit_code == 1, result.output
    assert kv_get_json(conn, STATUS, {}).get("failed") == []


def test_command_rewrites_the_todo_page_and_the_index(tmp_path, monkeypatch, models_importable):
    # caracole-autochords runs after the nightly run has written both pages: they must not
    # wait a night to show its sheets.
    fake_default_models(monkeypatch)
    bought(tmp_path)
    result = invoke(write_config(tmp_path, **model_files(tmp_path)))
    assert result.exit_code == 0, result.output
    todo = (tmp_path / "lib" / "_todo.md").read_text(encoding="utf-8")
    assert "1 song: 1 found, 0 wanted" in todo
    assert "Auto sheet text" in (tmp_path / "lib" / "index.html").read_text(encoding="utf-8")


def test_command_lists_a_purchase_it_cant_read_on_the_todo_page_at_once(
    tmp_path, monkeypatch, models_importable
):
    fake_default_models(monkeypatch, fail_on=("Nobody - River Road.wav",))
    bought(tmp_path)
    result = invoke(write_config(tmp_path, **model_files(tmp_path)))
    assert result.exit_code == 0, result.output
    todo = (tmp_path / "lib" / "_todo.md").read_text(encoding="utf-8")
    assert "## Auto-chords couldn't read these purchases" in todo and "Nobody - River Road" in todo


def test_command_waits_for_another_caracole(tmp_path, monkeypatch, models_importable):
    import fcntl
    import threading

    fake_default_models(monkeypatch)
    bought(tmp_path)
    config = write_config(tmp_path, **model_files(tmp_path))
    lock = tmp_path / "state" / "caracole.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)  # the nightly run, say, still writing the library
    results = []
    thread = threading.Thread(target=lambda: results.append(invoke(config)))
    try:
        thread.start()
        assert waiting_for(lock, thread.is_alive) and not (tmp_path / "lib" / "_todo.md").exists()
    finally:
        os.close(fd)
    thread.join(10)
    assert results and results[0].exit_code == 0, results and results[0].output
    assert "auto-chords: 1 generated" in results[0].output


def test_command_with_nothing_to_do(tmp_path, models_importable):
    from caracole import db

    result = invoke(write_config(tmp_path))
    assert result.exit_code == 0, result.output
    assert "auto-chords: 0 generated, 0 skipped, 0 failed" in result.output
    status = kv_get_json(db.connect(tmp_path / "state" / "caracole.sqlite"), STATUS, {})
    assert (status.get("generated"), status.get("skipped"), status.get("failed")) == (0, 0, [])


MODEL_PACKAGES = {"torch", "torchaudio", "librosa", "beat_this", "numpy", "soundfile"}


def model_packages_after(code: str, tmp_path: Path, *args: str) -> list[str]:
    """Run ``code`` in a fresh interpreter: its output lines, then the model packages imported."""
    src = Path(__file__).resolve().parents[1] / "src"
    # Keep the inherited PYTHONPATH: inside a Nix build, the dependencies are on it.
    pythonpath = os.pathsep.join(p for p in (str(src), os.environ.get("PYTHONPATH")) if p)
    env = {"HOME": str(tmp_path), "PATH": os.environ.get("PATH", ""), "PYTHONPATH": pythonpath}
    probe = f"\nprint(sorted({{m.split('.')[0] for m in sys.modules}} & {MODEL_PACKAGES!r}))\n"
    result = subprocess.run(
        [sys.executable, "-c", "import sys\n" + code + probe, *args],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout.strip().splitlines()


@pytest.mark.slow
def test_registering_the_command_imports_no_model_packages(tmp_path):
    # Every command module is imported on every start, and the default package has no torch.
    code = (
        "import typer\nfrom caracole.commands import autochords\nautochords.register(typer.Typer())"
    )
    assert model_packages_after(code, tmp_path) == ["[]"]


@pytest.mark.slow
def test_a_night_with_nothing_due_imports_no_model_packages(conn, cfg, tmp_path):
    keep_human_sheet(conn, cfg, with_audio(conn, tmp_path, add_song(conn, "A", "Charted")))
    # The cfg fixture's directories, and model files that would fail if anything loaded them.
    code = (
        "from pathlib import Path\n"
        "from caracole import db\n"
        "from caracole.autochords.run import autochords_pending\n"
        "from caracole.config import load_config\n"
        "tmp = Path(sys.argv[1])\n"
        "env = {'HOME': str(tmp / 'home'), 'STATE_DIRECTORY': str(tmp / 'state')}\n"
        "env['CARACOLE_BTC_WEIGHTS'] = str(tmp / 'btc.pt')\n"
        "env['CARACOLE_BEAT_CHECKPOINT'] = str(tmp / 'final0.ckpt')\n"
        "cfg = load_config(None, env=env)\n"
        "print(autochords_pending(db.connect(cfg.db_path), cfg).summary())"
    )
    assert model_packages_after(code, tmp_path, str(tmp_path)) == [
        "0 generated, 1 skipped, 0 failed",
        "[]",
    ]


# --- the real models ---------------------------------------------------------------------------


@pytest.fixture
def real_models(cfg):
    """The cfg with the real model files; skips without them or their packages."""
    from test_autochords_models import BEAT_CHECKPOINT, BTC_WEIGHTS, libs_load

    if BTC_WEIGHTS is None or BEAT_CHECKPOINT is None or not libs_load():
        pytest.skip("needs torch, librosa, beat_this and both model files")
    return replace(
        cfg, autochords=AutochordsConfig(btc_weights=BTC_WEIGHTS, beat_checkpoint=BEAT_CHECKPOINT)
    )


def synthetic_song(tmp_path: Path):
    """C major for 5 s, then G major, over a 120 BPM drum pattern: (samples, sample rate)."""
    import soundfile as sf
    from test_autochords_models import _drums, _triads

    chords, sr = sf.read(_triads(tmp_path / "triads.wav"))
    drums, _ = sf.read(_drums(tmp_path / "drums.wav", seconds=10.0))
    mix = chords + 0.5 * drums[: len(chords)]
    return 0.9 * mix / abs(mix).max(), sr


def assert_chords_over_synced_lyrics(conn, cfg, audio: Path) -> None:
    """The real models on ``synthetic_song`` audio: C over the first timed line, then G."""
    s = add_song(conn, "Nobody", "River Road", duration_ms=10000)
    update_song(
        conn,
        s.id,
        audio_path=str(audio),
        audio_mtime=os.stat(audio).st_mtime,
        lyrics_status="found",
        lyrics_json=lyrics_json(synced=SYNCED.replace("05.20", "05.10"), duration=10.0),
    )
    stats = autochords_pending(conn, cfg)
    assert (stats.generated, stats.failed, stats.errors) == (1, 0, [])
    lines = auto_sheet(cfg, conn, s).splitlines()
    assert lines[:2] == ["auto-generated, unverified", "Nobody - River Road"]
    i = lines.index("Walking down the river road")
    j = lines.index("Singing to the morning light")
    assert lines[i - 1].startswith("[ch]C[/ch]") and lines[j - 1].startswith("[ch]G[/ch]")
    # The synced lyrics were used, so the file's own duration was read and fits LRCLIB's.
    [kept] = kept_files(conn, s.id)
    assert get_version(conn, kept.version_id).raw["lyrics"] == "synced"
    assert get_song(conn, s.id).status == "found"


@pytest.mark.autochords
def test_real_models_put_chords_over_synced_lyrics(conn, real_models, tmp_path):
    import soundfile as sf

    samples, sr = synthetic_song(tmp_path)
    audio = tmp_path / "music" / "Nobody - River Road.wav"
    audio.parent.mkdir()
    sf.write(audio, samples, sr)
    assert_chords_over_synced_lyrics(conn, real_models, audio)


@pytest.mark.autochords
def test_real_models_read_an_itunes_m4a(conn, real_models, tmp_path):
    # iTunes Store purchases are AAC in .m4a, which libsndfile can't read: both models
    # fall back to torchaudio (FFmpeg), and mutagen reads the file's duration.
    torch = pytest.importorskip("torch")
    encoders = pytest.importorskip("torchcodec.encoders")

    samples, sr = synthetic_song(tmp_path)
    audio = tmp_path / "music" / "Nobody - River Road.m4a"
    audio.parent.mkdir()
    mono = torch.tensor(samples[None, :], dtype=torch.float32)
    encoders.AudioEncoder(mono, sample_rate=sr).to_file(str(audio))
    assert_chords_over_synced_lyrics(conn, real_models, audio)
