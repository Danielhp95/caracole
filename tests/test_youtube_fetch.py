"""youtube_fetch.py: which songs get their audio from YouTube, and what a pass keeps.

yt-dlp is ``FakeYtDlp`` (helpers/fake_ytdlp.py): no test reaches YouTube. Auto-chords is
taken to be there (``autochords_missing`` answers none), with model files in tmp_path.
"""

from __future__ import annotations

import dataclasses
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import add_song
from helpers.fake_ytdlp import FakeYtDlp, entry

import caracole.youtube_fetch as yf
from caracole.config import AutochordsConfig, ProviderPolicy
from caracole.db import kv_get_json, kv_set_json
from caracole.http import ProviderBlocked
from caracole.library import keep_file
from caracole.overrides import Overrides
from caracole.songs import get_song, update_song
from caracole.versions import upsert_version
from caracole.youtube import Video, YtDlp, watch_url

NOW = datetime(2026, 10, 19, 3, 50, tzinfo=UTC)
TOPIC = "XFkzRNyygfk"
LYRICS = "pyGxJ0y0dbE"
OTHER = "oNOFfl3Hx3s"


@pytest.fixture
def fake(tmp_path):
    return FakeYtDlp(tmp_path / "bin")


@pytest.fixture
def ycfg(cfg, tmp_path, fake, monkeypatch):
    """The config of a caracole with auto-chords, its model files and yt-dlp (the fake)."""
    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    models = tmp_path / "models"
    models.mkdir()
    (models / "btc.pt").write_bytes(b"w")
    (models / "beat.ckpt").write_bytes(b"c")
    return dataclasses.replace(cfg, ytdlp_bin=fake.bin, autochords=AutochordsConfig(models / "btc.pt",
                                                                                     models / "beat.ckpt"))


def to_buy(conn, artist="Radiohead", title="Creep", *, duration_ms=239000, **kw):
    """A song on the to-do page's buy list: UG has no sheet of it, and nothing else is to come."""
    song = add_song(conn, artist, title, duration_ms=duration_ms, **kw)
    update_song(conn, song.id, match_decision="not_found")
    return get_song(conn, song.id)


def creep_results(fake):
    fake.search("Radiohead Creep",
                entry(LYRICS, "Radiohead - Creep (Lyrics)", "lyricsfan", 239),
                entry(TOPIC, "Creep", "Radiohead - Topic", 238),
                entry(OTHER, "Creep (Live)", "Radiohead", 260))
    fake.video(TOPIC, "Creep", "Radiohead - Topic", 238, data="the topic upload")
    fake.video(LYRICS, "Radiohead - Creep (Lyrics)", "lyricsfan", 239, data="a lyric video")
    fake.video(OTHER, "Creep (Live)", "Radiohead", 260, data="a live cut")


def runner(cfg, *, budget=6):
    return YtDlp(cfg.ytdlp_bin, ProviderPolicy(budget, (0.0, 0.0)), cfg.cache_dir, sleep=lambda s: None)


def run(conn, cfg, overrides=None, *, budget=6, now=NOW, songs=None):
    with runner(cfg, budget=budget) as yt:
        return yf.youtube_pass(conn, yt, cfg, now, overrides=overrides or Overrides(), songs=songs)


# --- the route ---------------------------------------------------------------------------------


def test_the_route_needs_auto_chords_its_models_and_yt_dlp(ycfg, cfg, tmp_path, monkeypatch):
    assert yf.route_problem(ycfg) is None
    off = dataclasses.replace(ycfg, providers={**ycfg.providers, "youtube": ProviderPolicy(6, (15.0, 30.0), False)})
    assert yf.route_problem(off) == "turned off ([providers.youtube] enabled = false)"
    no_models = dataclasses.replace(ycfg, autochords=AutochordsConfig(None, tmp_path / "models" / "beat.ckpt"))
    assert yf.route_problem(no_models) == "auto-chords has no BTC weights configured"
    gone = dataclasses.replace(ycfg, autochords=AutochordsConfig(tmp_path / "nope.pt", tmp_path / "models/beat.ckpt"))
    assert yf.route_problem(gone) == f"auto-chords' BTC weights aren't there ({tmp_path / 'nope.pt'})"
    no_ytdlp = dataclasses.replace(ycfg, ytdlp_bin=str(tmp_path / "no-yt-dlp"))
    assert yf.route_problem(no_ytdlp) == f"yt-dlp isn't there ({tmp_path / 'no-yt-dlp'})"
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch", "librosa"])
    assert yf.route_problem(ycfg) == ("this caracole was built without auto-chords (missing: torch, librosa), "
                                      "so it has nothing to make of the audio")


def test_in_the_tests_a_config_read_from_the_environment_finds_no_real_yt_dlp(tmp_path, monkeypatch):
    # conftest's guard: in `nix develop .#autochords` torch imports, the model paths are set and
    # yt-dlp is on PATH, and a command must still never run it.
    from caracole.config import load_config

    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    for name in ("btc.pt", "beat.ckpt"):
        (tmp_path / name).write_bytes(b"m")
    FakeYtDlp(tmp_path / "on-path")  # a yt-dlp on PATH, as the dev shell has
    monkeypatch.setenv("PATH", f"{tmp_path / 'on-path'}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CARACOLE_BTC_WEIGHTS", str(tmp_path / "btc.pt"))
    monkeypatch.setenv("CARACOLE_BEAT_CHECKPOINT", str(tmp_path / "beat.ckpt"))
    assert yf.route_problem(load_config(None)).startswith("yt-dlp isn't there")


def test_without_auto_chords_the_packages_are_looked_for_and_never_imported():
    import sys

    missing = yf.autochords_missing()
    assert all(name not in sys.modules for name in missing)


def test_while_youtube_cools_down_its_songs_wait_blocked(conn, ycfg):
    from caracole.health import record_block

    song = to_buy(conn)
    record_block(conn, "youtube", NOW, "youtube: Sign in to confirm you're not a bot")
    state = yf.song_state(conn, ycfg, song, Overrides(), NOW)
    assert state.state == yf.BLOCKED and state.detail == "until 2026-10-20 05:50 UTC"
    assert yf.song_state(conn, ycfg, song, Overrides(), NOW + timedelta(days=2)).state == yf.QUEUED


# --- a pass -------------------------------------------------------------------------------------


def test_a_song_on_the_buy_list_gets_its_topic_audio_kept_outside_the_library(conn, ycfg, fake):
    song = to_buy(conn, duration_ms=239000)
    creep_results(fake)
    stats = run(conn, ycfg)
    assert (stats.tried, stats.downloaded, stats.missing, stats.errors) == (1, 1, 0, 0)
    after = get_song(conn, song.id)
    audio = Path(after.audio_path)
    assert audio == ycfg.cache_dir / "youtube" / f"{song.id}-{TOPIC}.m4a"
    assert audio.read_text() == "the topic upload" and after.audio_mtime == audio.stat().st_mtime
    assert not list(ycfg.library_dir.rglob("*.m4a"))  # the synced library holds no audio
    assert [p.name for p in (ycfg.cache_dir / "youtube").iterdir()] == [audio.name]  # no download folder left
    assert yf.youtube_audio(conn, after) == Video(TOPIC, "Creep", "Radiohead - Topic", 238.0)
    record = kv_get_json(conn, f"youtube:{song.id}")
    assert record["video"]["url"] == watch_url(TOPIC) and record["source"] == "search"
    assert [a[-1] for a in fake.argvs()] == ["ytsearch8:Radiohead Creep", watch_url(TOPIC)]


def test_the_video_must_fit_lrclibs_duration_when_the_song_has_none(conn, ycfg, fake):
    song = to_buy(conn, duration_ms=None)
    update_song(conn, song.id, lyrics_status="found", lyrics_json=json.dumps(
        {"id": 1, "plainLyrics": "When you were here before", "syncedLyrics": None, "duration": 262.0,
         "instrumental": False}))
    creep_results(fake)
    run(conn, ycfg)
    assert get_song(conn, song.id).audio_path.endswith(f"-{OTHER}.m4a")  # the only one 260 s long


def test_songs_caracole_may_still_find_a_sheet_for_or_has_audio_for_are_left_alone(conn, ycfg, fake):
    waiting = add_song(conn, "Oasis", "Wonderwall")
    update_song(conn, waiting.id, match_decision="accept")  # its UG fetch is still to come
    bought = to_buy(conn, "Blur", "Beetlebum")
    update_song(conn, bought.id, audio_path="/music/Blur - Beetlebum.flac")
    found = to_buy(conn, "Pulp", "Common People")
    update_song(conn, found.id, status="found")
    ignored = to_buy(conn, "Suede", "Animal Nitrate")
    unmatched = add_song(conn, "Elastica", "Connection")
    o = Overrides(ignore=frozenset({ignored.key}))
    assert yf.songs_for_youtube(conn, ycfg, o, NOW) == []
    assert run(conn, ycfg, o).tried == 0 and fake.argvs() == []
    assert unmatched.match_decision is None


def test_a_song_youtube_has_nothing_for_is_a_miss_asked_about_again_after_30_days(conn, ycfg, fake):
    song = to_buy(conn)
    fake.search("Radiohead Creep", entry(OTHER, "Creep", "Stone Temple Pilots - Topic"))
    assert run(conn, ycfg).missing == 1
    assert get_song(conn, song.id).audio_path is None
    assert kv_get_json(conn, f"youtube:{song.id}")["missing_at"] == "2026-10-19T03:50:00Z"
    assert yf.songs_for_youtube(conn, ycfg, Overrides(), NOW + timedelta(days=29)) == []
    assert [s.id for s in yf.songs_for_youtube(conn, ycfg, Overrides(), NOW + timedelta(days=31))] == [song.id]


def test_a_pasted_video_is_downloaded_without_a_search(conn, ycfg, fake):
    song = to_buy(conn)
    fake.video(OTHER, "Radiohead - Creep (Live at Glastonbury)", "someone", 300, data="the live one")
    o = Overrides(youtube={song.key: OTHER})
    stats = run(conn, ycfg, o)
    assert stats.downloaded == 1 and [a[-1] for a in fake.argvs()] == [watch_url(OTHER)]
    assert Path(get_song(conn, song.id).audio_path).read_text() == "the live one"
    record = kv_get_json(conn, f"youtube:{song.id}")
    assert record["source"] == "pasted" and record["video"]["title"] == "Radiohead - Creep (Live at Glastonbury)"


def test_a_pasted_video_also_serves_a_song_its_search_found_nothing_for(conn, ycfg, fake):
    song = to_buy(conn)
    run(conn, ycfg)  # no results: a miss
    fake.video(OTHER, data="pasted")
    run(conn, ycfg, Overrides(youtube={song.key: OTHER}))
    assert Path(get_song(conn, song.id).audio_path).read_text() == "pasted"


def test_a_new_paste_replaces_the_audio_and_none_takes_it_away(conn, ycfg, fake):
    song = to_buy(conn)
    creep_results(fake)
    run(conn, ycfg)
    first = Path(get_song(conn, song.id).audio_path)
    run(conn, ycfg, Overrides(youtube={song.key: LYRICS}))
    second = Path(get_song(conn, song.id).audio_path)
    assert second.read_text() == "a lyric video" and not first.exists()
    assert yf.youtube_audio(conn, get_song(conn, song.id)).id == LYRICS
    calls = len(fake.argvs())
    run(conn, ycfg, Overrides(youtube={song.key: LYRICS}))  # the same paste: nothing to do
    assert len(fake.argvs()) == calls
    run(conn, ycfg, Overrides(youtube={song.key: None}))
    assert get_song(conn, song.id).audio_path is None and not second.exists()
    assert len(fake.argvs()) == calls  # "none" asks YouTube nothing
    assert yf.songs_for_youtube(conn, ycfg, Overrides(youtube={song.key: None}), NOW) == []


def test_a_spent_budget_keeps_the_pick_and_the_next_run_only_downloads(conn, ycfg, fake):
    first = to_buy(conn, added_at="2026-10-02T00:00:00Z")
    second = to_buy(conn, "Radiohead", "Karma Police", duration_ms=200000, added_at="2026-10-01T00:00:00Z")
    creep_results(fake)
    fake.search("Radiohead Karma Police", entry(OTHER, "Karma Police", "Radiohead - Topic", 200))
    stats = run(conn, ycfg, budget=3)  # newest first: Creep's search and download, Karma Police's search
    assert stats.budget_exhausted and stats.downloaded == 1
    assert get_song(conn, first.id).audio_path and get_song(conn, second.id).audio_path is None
    assert kv_get_json(conn, f"youtube:{second.id}")["video"]["id"] == OTHER
    fake.video(OTHER, "Karma Police", "Radiohead - Topic", data="karma")
    before = len(fake.argvs())
    run(conn, ycfg)
    assert [a[-1] for a in fake.argvs()[before:]] == [watch_url(OTHER)]
    assert Path(get_song(conn, second.id).audio_path).read_text() == "karma"


def test_an_error_is_no_miss_and_the_song_waits_for_the_next_run(conn, ycfg, fake):
    song = to_buy(conn)
    fake.search("Radiohead Creep", stderr="ERROR: Unable to download API page: HTTP Error 503: Service Unavailable",
                exit=1)
    stats = run(conn, ycfg)
    assert (stats.errors, stats.missing) == (1, 0)
    assert [(s.id, e.status) for s, e in stats.failures] == [(song.id, 503)]
    record = kv_get_json(conn, f"youtube:{song.id}")
    assert "missing_at" not in record and "503" in record["error"]
    assert [s.id for s in yf.songs_for_youtube(conn, ycfg, Overrides(), NOW)] == [song.id]


def test_a_block_stops_the_pass_and_marks_no_song(conn, ycfg, fake):
    first = to_buy(conn, added_at="2026-10-02T00:00:00Z")
    second = to_buy(conn, "Radiohead", "Karma Police", added_at="2026-10-01T00:00:00Z")
    fake.search("Radiohead Creep", stderr="ERROR: [youtube] Sign in to confirm you’re not a bot", exit=1)
    with pytest.raises(ProviderBlocked):
        run(conn, ycfg)
    assert len(fake.argvs()) == 1
    for song in (first, second):
        record = kv_get_json(conn, f"youtube:{song.id}") or {}
        assert "missing_at" not in record and get_song(conn, song.id).audio_path is None


def test_a_searched_video_that_cant_be_had_is_passed_over_for_the_next_one(conn, ycfg, fake):
    song = to_buy(conn)
    creep_results(fake)
    fake.video(TOPIC, stderr="ERROR: [youtube] XFkzRNyygfk: Video unavailable", exit=1)
    stats = run(conn, ycfg)
    assert stats.unavailable == 1 and stats.errors == 0 and get_song(conn, song.id).audio_path is None
    assert kv_get_json(conn, f"youtube:{song.id}")["skip"] == [TOPIC]
    run(conn, ycfg)
    assert get_song(conn, song.id).audio_path.endswith(f"-{LYRICS}.m4a")


def test_a_pasted_video_that_cant_be_had_waits_for_another_paste(conn, ycfg, fake):
    song = to_buy(conn)
    fake.video(OTHER, stderr="ERROR: [youtube] oNOFfl3Hx3s: Private video", exit=1)
    o = Overrides(youtube={song.key: OTHER})
    run(conn, ycfg, o)
    state = yf.song_state(conn, ycfg, get_song(conn, song.id), o, NOW)
    assert state.state == yf.UNUSABLE and "Private video" in state.detail
    assert yf.songs_for_youtube(conn, ycfg, o, NOW) == []
    fake.video(LYRICS, data="another")
    run(conn, ycfg, Overrides(youtube={song.key: LYRICS}))
    assert Path(get_song(conn, song.id).audio_path).read_text() == "another"


def test_one_song_by_hand_is_looked_up_even_when_its_search_missed_lately(conn, ycfg, fake):
    song = to_buy(conn)
    run(conn, ycfg)  # a miss
    creep_results(fake)
    stats = run(conn, ycfg, songs=[get_song(conn, song.id)])
    assert stats.downloaded == 1


def test_a_purchase_takes_the_youtube_audios_place(conn, ycfg, fake):
    from caracole.music import scan_music

    song = to_buy(conn)
    creep_results(fake)
    run(conn, ycfg)
    ycfg.music_dir.mkdir(parents=True)
    bought = ycfg.music_dir / "Radiohead - Creep.flac"
    bought.write_bytes(b"not really flac")
    scan_music(conn, ycfg.music_dir)
    after = get_song(conn, song.id)
    assert after.audio_path == str(bought) and yf.youtube_audio(conn, after) is None
    assert yf.songs_for_youtube(conn, ycfg, Overrides(), NOW) == []


# --- what the to-do page and index.html show -----------------------------------------------------


def auto_sheet(conn, cfg, song):
    v = upsert_version(conn, provider="auto", tab_id=str(song.id), song_id=song.id, slot="sheet", kind="auto",
                       rating=0, votes=0, version=1, label=None, url="x", raw={}, now="x")
    keep_file(conn, cfg.library_dir, song=song, version_id=v, name="sheet (auto).txt", data=b"x", rank=1)
    update_song(conn, song.id, status="found", autochords_mtime=get_song(conn, song.id).audio_mtime)


def test_each_song_without_a_human_sheet_has_a_state(conn, ycfg, fake):
    queued = to_buy(conn, "Radiohead", "Karma Police")
    creep = to_buy(conn)
    missing = to_buy(conn, "Radiohead", "Airbag")
    declined = to_buy(conn, "Radiohead", "Let Down")
    creep_results(fake)
    fake.search("Radiohead Karma Police", stderr="ERROR: HTTP Error 502: Bad Gateway", exit=1)
    o = Overrides(youtube={declined.key: None})
    run(conn, ycfg, o, songs=[get_song(conn, creep.id), get_song(conn, missing.id), get_song(conn, queued.id)])
    states = yf.song_states(conn, ycfg, o, NOW)
    assert {s.title: states[s.id].state for s in (queued, creep, missing, declined)} == {
        "Karma Police": yf.QUEUED, "Creep": yf.DOWNLOADED, "Airbag": yf.MISSING, "Let Down": yf.DECLINED}
    assert "502" in states[queued.id].detail  # the last try's error, tried again next run
    assert states[creep.id].video.id == TOPIC
    auto_sheet(conn, ycfg, get_song(conn, creep.id))
    assert yf.song_states(conn, ycfg, o, NOW)[creep.id].state == yf.CHORDS
    keep_file(conn, ycfg.library_dir, song=get_song(conn, creep.id), version_id=upsert_version(
        conn, provider="ug", tab_id="1", song_id=creep.id, slot="sheet", kind="chords", rating=5, votes=9,
        version=1, label=None, url="u", raw={}, now="x"), name="sheet.txt", data=b"[C]x", rank=1)
    assert creep.id not in yf.song_states(conn, ycfg, o, NOW)  # a human sheet: off the list


def test_a_record_that_isnt_one_is_no_record(conn, ycfg):
    song = to_buy(conn)
    kv_set_json(conn, f"youtube:{song.id}", ["not", "a", "record"])
    assert yf.song_state(conn, ycfg, song, Overrides(), NOW).state == yf.QUEUED
