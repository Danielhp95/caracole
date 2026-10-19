"""Auto-chords over the database: which songs get ``sheet (auto).txt``, and how.

Most tests use a fake recognizer and fake beats, so they run anywhere. The one
marked ``autochords`` runs the real models on synthetic audio; it needs torch,
librosa and beat_this, and the model files (see tests/test_autochords_models.py).
"""

from __future__ import annotations

import json
import logging
import os
import wave
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tabarr.autochords import ChordSegment
from tabarr.autochords.run import AUTO_SHEET, AutoStats, autochords_pending
from tabarr.cli import build_app
from tabarr.config import AutochordsConfig
from tabarr.library import keep_file, kept_files, song_dir
from tabarr.lyrics import Lyrics
from tabarr.overrides import Overrides
from tabarr.songs import get_song, update_song
from tabarr.versions import get_version, upsert_version

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


# --- what gets generated -------------------------------------------------------------------


def test_auto_sheet_kept_with_its_version_and_the_song_becomes_found(conn, cfg, tmp_path):
    s = with_audio(
        conn,
        tmp_path,
        add_song(conn, "Nobody", "River Road"),
        lyrics_status="found",
        lyrics_json=lyrics_json(plain="Walking down\nSinging on"),
    )
    stats = run(conn, cfg)
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
    assert v.raw == {"audio": s.audio_path, "model": "btc_large_voca", "lyrics": "plain"}

    song = get_song(conn, s.id)
    assert song.status == "found"
    assert song.autochords_mtime == song.audio_mtime

    info = json.loads((song_dir(cfg.library_dir, song) / "info.json").read_text(encoding="utf-8"))
    assert info["status"] == "found"
    assert [(f["name"], f["provider"], f["kind"]) for f in info["files"]] == [
        (AUTO_SHEET, "auto", "auto")
    ]


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
    import tabarr.autochords.run as ac_run

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
    with caplog.at_level(logging.ERROR, logger="tabarr.autochords.run"):
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
    assert any("TABARR_BTC_WEIGHTS" in e for e in stats.errors)
    assert any("TABARR_BEAT_CHECKPOINT" in e for e in stats.errors)


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
    with caplog.at_level(logging.ERROR, logger="tabarr.autochords.run"):
        stats = run(conn, cfg, FakeRecognizer(fail_on=("bad.wav",)))
    assert (stats.generated, stats.failed) == (1, 1)
    assert len(stats.errors) == 1 and stats.errors[0].startswith("A - Broken Download: ")
    assert "Format not recognised" in caplog.text
    song = get_song(conn, bad.id)
    assert (song.status, song.autochords_mtime, kept_files(conn, bad.id)) == ("wanted", None, [])
    assert get_song(conn, good.id).status == "found"
    # Still pending: the next run tries again.
    rec = FakeRecognizer()
    run(conn, cfg, rec)
    assert rec.calls == [Path(bad.audio_path)]


def test_nothing_pending_loads_no_model(conn, cfg, tmp_path):
    cfg = replace(cfg, autochords=AutochordsConfig(btc_weights=tmp_path / "nope.pt"))
    s = with_audio(conn, tmp_path, add_song(conn, "A", "T"))
    keep_human_sheet(conn, cfg, s)
    stats = autochords_pending(conn, cfg)
    assert (stats.generated, stats.skipped, stats.failed, stats.errors) == (0, 1, 0, [])


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
    p = tmp_path / "tabarr.toml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def invoke(config: Path):
    return CliRunner().invoke(build_app(), ["--config", str(config), "autochords"])


@pytest.fixture
def models_importable(monkeypatch):
    import tabarr.commands.autochords as cmd

    monkeypatch.setattr(cmd, "find_spec", lambda name: object())


def test_command_without_the_models_says_which_package_has_them(tmp_path, monkeypatch):
    import tabarr.commands.autochords as cmd

    monkeypatch.setattr(cmd, "find_spec", lambda name: None if name == "torch" else object())
    result = invoke(write_config(tmp_path))
    assert result.exit_code == 1
    assert (
        "this tabarr was built without auto-chords; use the flake's packages.autochords"
        in result.output
    )
    assert "torch" in result.output


def test_command_scans_music_then_generates(tmp_path, monkeypatch, models_importable):
    import tabarr.autochords.run as ac_run

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
    from tabarr import db

    conn = db.connect(tmp_path / "state" / "tabarr.sqlite")
    add_song(conn, "宋冬野", "斑马斑马", duration_ms=None)
    # Dropped into Music/ after the night's run: only the command's own scan links it.
    make_wav(tmp_path / "music" / "宋冬野 - 斑马斑马.wav", 3.0)

    result = invoke(config)
    assert result.exit_code == 0, result.output
    assert "Music: 1 file, 1 linked" in result.output
    assert "auto-chords: 1 generated, 0 skipped, 0 failed" in result.output
    assert (tmp_path / "lib" / "宋冬野" / "斑马斑马" / AUTO_SHEET).is_file()


def test_command_fails_when_a_song_failed(tmp_path, models_importable):
    from tabarr import db

    conn = db.connect(tmp_path / "state" / "tabarr.sqlite")
    add_song(conn, "Nobody", "River Road", duration_ms=None)
    make_wav(tmp_path / "music" / "Nobody - River Road.wav", 3.0)
    result = invoke(write_config(tmp_path, btc_weights=tmp_path / "missing.pt"))
    assert result.exit_code == 1, result.output
    assert "auto-chords: 0 generated, 0 skipped, 1 failed" in result.output


def test_command_with_nothing_to_do(tmp_path, models_importable):
    result = invoke(write_config(tmp_path))
    assert result.exit_code == 0, result.output
    assert "auto-chords: 0 generated, 0 skipped, 0 failed" in result.output


# --- the real models ---------------------------------------------------------------------------


@pytest.mark.autochords
def test_real_models_put_chords_over_synced_lyrics(conn, cfg, tmp_path):
    from test_autochords_models import BEAT_CHECKPOINT, BTC_WEIGHTS, HAVE_LIBS, _drums, _triads

    if not HAVE_LIBS or BTC_WEIGHTS is None or BEAT_CHECKPOINT is None:
        pytest.skip("needs torch, librosa, beat_this and both model files")
    import soundfile as sf

    # C major for 5 s, then G major, over a 120 BPM drum pattern.
    chords, sr = sf.read(_triads(tmp_path / "triads.wav"))
    drums, _ = sf.read(_drums(tmp_path / "drums.wav", seconds=10.0))
    mix = chords + 0.5 * drums[: len(chords)]
    audio = tmp_path / "music" / "Nobody - River Road.wav"
    audio.parent.mkdir()
    sf.write(audio, 0.9 * mix / abs(mix).max(), sr)

    s = add_song(conn, "Nobody", "River Road", duration_ms=10000)
    update_song(
        conn,
        s.id,
        audio_path=str(audio),
        audio_mtime=os.stat(audio).st_mtime,
        lyrics_status="found",
        lyrics_json=lyrics_json(synced=SYNCED.replace("05.20", "05.10"), duration=10.0),
    )
    cfg = replace(
        cfg, autochords=AutochordsConfig(btc_weights=BTC_WEIGHTS, beat_checkpoint=BEAT_CHECKPOINT)
    )
    stats = autochords_pending(conn, cfg)
    assert (stats.generated, stats.failed, stats.errors) == (1, 0, [])
    lines = auto_sheet(cfg, conn, s).splitlines()
    assert lines[:2] == ["auto-generated, unverified", "Nobody - River Road"]
    i = lines.index("Walking down the river road")
    j = lines.index("Singing to the morning light")
    assert lines[i - 1].startswith("[ch]C[/ch]") and lines[j - 1].startswith("[ch]G[/ch]")
    assert get_song(conn, s.id).status == "found"
