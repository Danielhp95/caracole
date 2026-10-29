"""youtube_search.py: a YouTube video suggested for a search, its gate, its record and its thumbnail.

The command that runs it (``caracole youtube --search``) is tested in test_commands_youtube.py, with ``FakeYtDlp``
and a fake image host: nothing here reaches the network.
"""

from __future__ import annotations

import struct
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import caracole.youtube_fetch as yf
from caracole.config import AutochordsConfig
from caracole.db import kv_set_json
from caracole.health import record_block
from caracole.http import ROBOTS_DISALLOW, robots_disallows
from caracole.search import STRONG, ArtistHit, IndexFound, IndexHit, LibraryHit, SiteArtist, SiteHit
from caracole.youtube_search import (
    FAILURES_PAUSE,
    KV_PREFIX,
    MAX_BYTES,
    SEARCHES_PER_HOUR,
    THUMB_URL,
    checked_jpeg,
    gate,
    query_key,
    record_failure,
    sheet_on_screen,
    suggestion,
)

NOW = datetime(2026, 10, 29, 20, 0, tzinfo=UTC)
FIXTURES = Path(__file__).parent / "fixtures" / "youtube"
QUERY = "Nick Cani - Vikingos veganos"
VIDEO = {"id": "lzN7Thn3FV4", "title": "Somos vikingos veganos - Hyperfanes", "channel": "kintanedu",
         "duration": 222.0, "url": "https://www.youtube.com/watch?v=lzN7Thn3FV4"}


def jpeg(width: int = 480, height: int = 360, *, tail: bytes = b"\xff\xd9", frame: bool = True) -> bytes:
    """A JPEG's skeleton: its start, a JFIF header, a frame of ``width`` × ``height``, a scan, its end."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    sos = b"\xff\xda" + struct.pack(">HB", 8, 1) + b"\x01\x00\x00\x3f\x00"
    return b"\xff\xd8" + app0 + (sof0 if frame else b"") + sos + b"\x12\x34\x56" + tail


@pytest.fixture
def able(cfg, tmp_path, monkeypatch):
    """A caracole that makes a sheet from a video: auto-chords' packages taken to be there, its model files, a
    yt-dlp (never run here)."""
    monkeypatch.setattr(yf, "autochords_missing", lambda: [])
    files = {"btc_weights": tmp_path / "btc.pt", "beat_checkpoint": tmp_path / "final0.ckpt"}
    for path in files.values():
        path.write_bytes(b"model")
    ytdlp = tmp_path / "bin" / "yt-dlp"
    ytdlp.parent.mkdir()
    ytdlp.write_text("#!/bin/sh\nexit 1\n")
    ytdlp.chmod(0o755)
    return replace(cfg, ytdlp_bin=str(ytdlp), autochords=AutochordsConfig(**files))


# --- the image host's robots.txt ------------------------------------------------------------------------


def test_robots_rules_are_the_live_files_user_agent_star_group():
    lines = (FIXTURES / "ytimg-robots.txt").read_text(encoding="utf-8").splitlines()
    group = lines[lines.index("User-agent: *") + 1:]
    assert ROBOTS_DISALLOW["i.ytimg.com"] == tuple(line.split(":", 1)[1].strip() for line in group
                                                   if line.startswith("Disallow:"))
    assert robots_disallows(THUMB_URL.format(id=VIDEO["id"])) is None
    assert robots_disallows(f"https://i.ytimg.com/sb/{VIDEO['id']}/storyboard3_L0/default.jpg") == "/sb/"


# --- a thumbnail's bytes ----------------------------------------------------------------------------------


def test_a_jpeg_is_kept_as_it_is():
    image = jpeg()
    assert checked_jpeg(image) == image


@pytest.mark.parametrize("data", [
    b"",
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 40,  # a PNG
    b"<!doctype html><title>Sign in</title>",  # a page in an image's place
    jpeg()[:-2],  # cut short: no end
    jpeg(0, 360),  # no width
    jpeg(4096, 360),  # too wide for a thumbnail
    jpeg(frame=False),  # no frame before the scan
    jpeg()[:30],  # cut short in its segments
    jpeg(tail=b"\x00" * MAX_BYTES + b"\xff\xd9"),  # too big
], ids=["empty", "png", "html", "no-end", "no-width", "too-wide", "no-frame", "cut-short", "too-big"])
def test_anything_else_is_no_thumbnail(data):
    assert checked_jpeg(data) is None


# --- when a search goes --------------------------------------------------------------------------------------


def test_a_querys_key_is_its_words_in_alphabetical_order():
    assert query_key(QUERY) == query_key("vikingos veganos nick cani") == "cani-nick-veganos-vikingos"
    assert query_key(" - ") == ""


def test_a_search_goes_for_a_query_with_no_sheet_where_a_sheet_can_be_made(able, conn, cfg, monkeypatch):
    said = gate(able, conn, QUERY, on_screen=False, now=NOW)
    assert (said.state, said.key) == ("auto", "cani-nick-veganos-vikingos")
    assert gate(able, conn, QUERY, on_screen=True, now=NOW) is None  # a sheet on the screen: nothing to suggest
    assert gate(able, conn, "- -", on_screen=False, now=NOW) is None
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch"])
    assert gate(able, conn, QUERY, on_screen=False, now=NOW) is None  # no sheet from a video here
    assert gate(cfg, conn, QUERY, on_screen=False, now=NOW) is None  # nor without yt-dlp


def test_a_query_is_searched_once_in_30_days_its_answer_kept(able, conn):
    kv_set_json(conn, KV_PREFIX + query_key(QUERY), {"at": "2026-10-20T10:00:00Z", "video": VIDEO, "thumb": True})
    said = gate(able, conn, "vikingos veganos - nick cani", on_screen=False, now=NOW)
    assert said.state == "found"
    assert suggestion(said, QUERY) == {"state": "found", "query": QUERY, "key": said.key, "video": {
        **VIDEO, "thumb": "/youtube/thumb/lzN7Thn3FV4.jpg"}}
    assert gate(able, conn, QUERY, on_screen=False, now=NOW + timedelta(days=31)).state == "auto"
    kv_set_json(conn, KV_PREFIX + query_key(QUERY), {"at": "2026-10-20T10:00:00Z", "video": None})
    assert gate(able, conn, QUERY, on_screen=False, now=NOW).state == "none"


def test_none_goes_while_youtube_cools_down_or_once_the_hours_searches_are_spent(able, conn):
    for n in range(SEARCHES_PER_HOUR):
        conn.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES (?, ?, 'youtube', ?, NULL, "
                     "'ok')", (f"youtube-search:2026-10-29T19:{n:02d}:00Z", f"2026-10-29T19:{n:02d}:00Z",
                               f"ytsearch1:song {n}"))
    said = gate(able, conn, QUERY, on_screen=False, now=NOW)
    assert (said.state, said.why) == ("spent", f"this hour's {SEARCHES_PER_HOUR} searches of YouTube are spent")
    assert gate(able, conn, QUERY, on_screen=False, now=NOW + timedelta(hours=1)).state == "auto"
    record_block(conn, "youtube", NOW, "bot check")
    assert gate(able, conn, QUERY, on_screen=False, now=NOW + timedelta(hours=1)).why == (
        "YouTube is cooling down after a block")


def test_a_search_that_failed_isnt_sent_for_an_hour_nor_any_after_three_failed(able, conn):
    record_failure(conn, query_key(QUERY), NOW, "yt-dlp failed: HTTP Error 500")
    said = gate(able, conn, QUERY, on_screen=False, now=NOW + timedelta(minutes=10))
    assert said.state == "failed" and "HTTP Error 500" in said.why
    assert gate(able, conn, "Other - Song", on_screen=False, now=NOW).state == "auto"
    for n in range(FAILURES_PAUSE - 1):
        record_failure(conn, f"other-{n}", NOW, "timed out")
    assert gate(able, conn, "Other - Song", on_screen=False, now=NOW).state == "failed"
    assert gate(able, conn, QUERY, on_screen=False, now=NOW + timedelta(minutes=61)).state == "auto"


# --- what the search's answer has on the screen --------------------------------------------------------------


def test_a_sheet_on_the_screen_is_a_strong_song_or_an_artist_named_whole():
    none = IndexFound()
    assert not sheet_on_screen([], none, [], [])
    assert sheet_on_screen([LibraryHit(None, STRONG, "title")], none, [], [])
    assert not sheet_on_screen([LibraryHit(None, STRONG, "artist")], none, [], [])  # an artist of yours: no song
    ug_song = IndexHit("nick-cani", "vikingos-veganos", {"chords": 1}, STRONG, "https://tabs.ultimate-guitar.com/x")
    assert sheet_on_screen([], IndexFound(songs=(ug_song,)), [], [])
    assert not sheet_on_screen([], IndexFound(songs=(replace(ug_song, score=STRONG - 1),)), [], [])
    assert sheet_on_screen([], IndexFound(artists=(ArtistHit("estopa", "Estopa", STRONG, 60, 300),)), [], [])
    assert not sheet_on_screen([], IndexFound(artists=(ArtistHit("estopa", "Estopa", STRONG, 60, 300, part=True),)),
                               [], [])
    lc = SiteHit("lacuerda", "Vikingos veganos", "https://acordes.lacuerda.net/x", STRONG, sheet="x-2.shtml")
    assert sheet_on_screen([], none, [], [lc]) and not sheet_on_screen([], none, [], [replace(lc, sheet=None)])
    assert sheet_on_screen([], none, [SiteArtist("lacuerda", "Estopa", "estopa", "u", STRONG)], [])
