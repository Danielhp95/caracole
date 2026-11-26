"""autochords/transcript.py: the transcript kept for a song's YouTube audio, apart from its lyrics, and which
songs are offered one. No model runs here."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest
from conftest import add_song

from caracole.autochords import transcript as tr
from caracole.config import ProviderPolicy
from caracole.db import kv_get, kv_get_json, kv_set
from caracole.library import keep_file
from caracole.overrides import Overrides
from caracole.songs import get_song, update_song
from caracole.versions import upsert_version
from caracole.youtube import Video
from caracole.youtube_fetch import Record, _save


def youtube_song(conn, tmp_path, artist="A", title="T", **fields):
    """A song whose audio came from YouTube, its lyrics missing and every site asked about it."""
    song = add_song(conn, artist, title)
    audio = tmp_path / "youtube" / f"{song.id}-abc.m4a"
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(b"audio")
    fields = {"lyrics_status": "missing", "lyrics_at": "2026-11-01T00:00:00Z", **fields}
    update_song(conn, song.id, audio_path=str(audio), audio_mtime=os.stat(audio).st_mtime, **fields)
    _save(conn, song.id, Record(video=Video("XFkzRNyygfk", "T", "A - Topic", 200.0),
                                source="search", audio=str(audio)))
    kv_set(conn, f"megalobiz:checked:{song.id}", "2026-11-01T00:00:00Z")
    kv_set(conn, f"azlyrics:checked:{song.id}", "2026-11-01T00:00:00Z")
    return get_song(conn, song.id)


def made(song, **kw):
    fields = dict(lrc="[00:01.00]hello\n", audio=song.audio_path, audio_mtime=song.audio_mtime, model=tr.MODEL,
                  language="en", device="cuda", words_dropped=0, made_at="2026-11-20T00:00:00Z")
    return tr.Transcript(**{**fields, **kw})


def test_a_transcript_kept_is_read_back_while_the_audio_is_the_same(conn, tmp_path):
    song = youtube_song(conn, tmp_path)
    t = made(song)
    tr.keep_transcript(conn, song, t)
    assert tr.transcript_of(conn, song) == t
    assert tr.Transcript.from_json(t.as_json()) == t
    assert tr.Transcript.from_json({"lrc": 3}) is None
    assert tr.Transcript.from_json("nope") is None


def test_a_transcript_of_other_audio_is_none_and_the_offer_comes_back(conn, cfg, tmp_path):
    song = youtube_song(conn, tmp_path)
    tr.keep_transcript(conn, song, made(song))
    assert tr.why_not_offered(conn, cfg, song, Overrides()) is not None
    update_song(conn, song.id, audio_mtime=song.audio_mtime + 5)
    song = get_song(conn, song.id)
    assert tr.transcript_of(conn, song) is None
    assert tr.why_not_offered(conn, cfg, song, Overrides()) is None


def test_heard_nothing_holds_for_that_audio_alone(conn, cfg, tmp_path):
    song = youtube_song(conn, tmp_path)
    assert not tr.heard_nothing(conn, song)
    tr.note_heard_nothing(conn, song, "2026-11-20T00:00:00Z", why="sung 6.2 s", by="caracole")
    assert tr.heard_nothing(conn, song)
    assert kv_get_json(conn, f"{tr.HEARD_NOTHING}{song.id}") == {
        "audio": song.audio_path, "audio_mtime": song.audio_mtime, "at": "2026-11-20T00:00:00Z", "why": "sung 6.2 s",
        "by": "caracole"}
    assert tr.why_not_offered(conn, cfg, song, Overrides()) is not None
    update_song(conn, song.id, audio_mtime=song.audio_mtime + 5)
    other = get_song(conn, song.id)
    assert not tr.heard_nothing(conn, other)
    assert tr.why_not_offered(conn, cfg, other, Overrides()) is None
    tr.note_heard_nothing(conn, song, "2026-11-20T00:00:00Z", why="you said so", by="you")
    tr.keep_transcript(conn, song, made(song))
    assert kv_get(conn, f"{tr.HEARD_NOTHING}{song.id}") is None


def test_a_song_is_offered_once_every_site_switched_on_missed(conn, cfg, tmp_path):
    song = youtube_song(conn, tmp_path)
    assert tr.why_not_offered(conn, cfg, song, Overrides()) is None
    conn.execute("DELETE FROM kv WHERE key = ?", (f"azlyrics:checked:{song.id}",))
    assert tr.why_not_offered(conn, cfg, song, Overrides()) is not None
    off = dataclasses.replace(cfg, providers={**cfg.providers, "azlyrics": ProviderPolicy(0, (0.0, 0.0), False)})
    assert tr.why_not_offered(conn, off, song, Overrides()) is None
    update_song(conn, song.id, lyrics_at=None)
    assert tr.why_not_offered(conn, off, get_song(conn, song.id), Overrides()) is not None


def test_a_song_whose_picked_record_is_gone_is_offered_once_its_site_missed(conn, cfg, tmp_path):
    # A record you picked is final: no other site is ever asked about the song, so its own site's miss is every
    # site's, the lyrics sites asked first all the same.
    from caracole.overrides import LyricsPick, LyricsRecord, override_key

    song = youtube_song(conn, tmp_path)
    for key in ("megalobiz:checked:", "azlyrics:checked:"):
        conn.execute("DELETE FROM kv WHERE key = ?", (f"{key}{song.id}",))
    picked = {site: Overrides(lyrics={override_key(song.display): LyricsPick(None, LyricsRecord(site, "8"))})
              for site in ("lrclib", "megalobiz", "azlyrics")}
    assert tr.why_not_offered(conn, cfg, song, picked["lrclib"]) is None
    assert tr.why_not_offered(conn, cfg, song, picked["megalobiz"]) == "megalobiz hasn't been asked"
    kv_set(conn, f"megalobiz:checked:{song.id}", "2026-11-01T00:00:00Z")
    assert tr.why_not_offered(conn, cfg, song, picked["megalobiz"]) is None
    assert tr.why_not_offered(conn, cfg, song, Overrides()) == "azlyrics hasn't been asked"


def _human_sheet(conn, cfg, song):
    vid = upsert_version(conn, provider="ug", tab_id="1", song_id=song.id, slot="sheet", kind="chords", rating=4.5,
                         votes=1, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/x-1", raw={},
                         now="2026-10-18T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt", data=b"[ch]G[/ch]\nHi", rank=1)


@pytest.mark.parametrize("what", ["pending", "found", "instrumental", "human", "ignored", "overridden"])
def test_no_offer_for_pending_or_found_or_instrumental_lyrics_a_human_sheet_an_ignored_song_or_bought_audio(
        conn, cfg, tmp_path, what):
    song = youtube_song(conn, tmp_path)
    overrides = Overrides()
    if what in ("pending", "found", "instrumental"):
        update_song(conn, song.id, lyrics_status=what)
    elif what == "human":
        _human_sheet(conn, cfg, song)
    elif what == "ignored":
        update_song(conn, song.id, status="ignored")
    elif what == "overridden":
        overrides = Overrides(ignore=frozenset({song.key}))
    assert tr.why_not_offered(conn, cfg, get_song(conn, song.id), overrides)


def test_a_purchase_is_offered_a_transcription(conn, cfg, tmp_path):
    song = youtube_song(conn, tmp_path)
    conn.execute("DELETE FROM kv WHERE key = ?", (f"youtube:{song.id}",))  # audio that isn't from YouTube
    assert tr.why_not_offered(conn, cfg, song, Overrides()) is None
    assert song.id in tr.offered_song_ids(conn, cfg, Overrides())


def test_a_song_with_no_audio_isnt_offered(conn, cfg, tmp_path):
    song = add_song(conn, "A", "T")
    update_song(conn, song.id, lyrics_status="missing", lyrics_at="2026-11-01T00:00:00Z")
    kv_set(conn, f"megalobiz:checked:{song.id}", "2026-11-01T00:00:00Z")
    kv_set(conn, f"azlyrics:checked:{song.id}", "2026-11-01T00:00:00Z")
    assert tr.why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) == "it has no audio"


def test_anyway_passes_over_nothing_sung_and_nothing_else(conn, cfg, tmp_path):
    song = youtube_song(conn, tmp_path)
    tr.note_heard_nothing(conn, song, "2026-11-20T00:00:00Z", why="sung 2 s", by="caracole")
    assert tr.why_not_offered(conn, cfg, song, Overrides()) == "nothing sung was heard"
    assert tr.why_not_offered(conn, cfg, song, Overrides(), anyway=True) is None
    update_song(conn, song.id, lyrics_status="found")  # the sites come first, forced or not
    assert tr.why_not_offered(conn, cfg, get_song(conn, song.id), Overrides(), anyway=True)
    update_song(conn, song.id, lyrics_status="missing")
    tr.keep_transcript(conn, song, made(song))
    assert tr.why_not_offered(conn, cfg, song, Overrides(), anyway=True) == tr.ALREADY_TRANSCRIBED


def test_a_song_whose_audio_file_is_gone_is_not_offered(conn, cfg, tmp_path):
    song = youtube_song(conn, tmp_path)
    Path(song.audio_path).unlink()
    assert tr.why_not_offered(conn, cfg, song, Overrides())


def test_audio_that_cant_be_read_is_offered_no_more_until_it_changes(conn, cfg, tmp_path):
    # Filed as auto-chords files a file it can't read (run.py), by auto-chords or by a transcription.
    from caracole.autochords.run import _unreadable

    song = youtube_song(conn, tmp_path)
    _unreadable(conn, song, RuntimeError("Failed to load audio: moov atom not found"), "2026-11-20T00:00:00Z")
    assert tr.why_not_offered(conn, cfg, song, Overrides()) == "its audio can't be read"
    assert tr.offered_song_ids(conn, cfg, Overrides()) == []
    update_song(conn, song.id, audio_mtime=song.audio_mtime + 5)  # new audio: offered again
    assert tr.why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) is None


def test_offered_song_ids_lists_the_songs_due(conn, cfg, tmp_path):
    first = youtube_song(conn, tmp_path, "A", "One")
    second = youtube_song(conn, tmp_path, "B", "Two")
    youtube_song(conn, tmp_path, "C", "Three", lyrics_status="found")
    assert tr.offered_song_ids(conn, cfg, Overrides()) == sorted([first.id, second.id])


def test_a_song_with_lyrics_is_told_so_before_whisper_cant_read_its_audio(conn, cfg, tmp_path):
    # The lyrics sites come first: a song a site has lyrics for, or one ignored, is told that, never what Whisper made
    # of its audio; the record says why only while it is all that keeps the words from being heard.
    song = youtube_song(conn, tmp_path)
    tr.note_whisper_cant_read(conn, song, "2026-11-25T00:00:00Z", "RuntimeError: Failed to load audio")
    assert tr.why_not_offered(conn, cfg, song, Overrides()) == tr.WHISPER_UNREADABLE_WHY
    update_song(conn, song.id, lyrics_status="found")
    assert tr.why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) == "its lyrics are found"
    update_song(conn, song.id, lyrics_status="missing", status="ignored")
    assert tr.why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) == "ignored"


def test_the_owners_not_sung_holds_for_that_audio_and_a_new_file_is_heard_again(conn, cfg, tmp_path):
    song = youtube_song(conn, tmp_path)
    tr.keep_transcript(conn, song, made(song))
    assert tr.why_not_unsung(conn, cfg, song, Overrides()) is None
    tr.drop_transcript(conn, song, "2026-11-25T00:00:00Z")
    assert tr.transcript_of(conn, song) is None and tr.said_not_sung(conn, song)
    assert tr.why_not_offered(conn, cfg, song, Overrides()) == tr.SAID_NOT_SUNG
    assert tr.why_not_unsung(conn, cfg, song, Overrides()) == tr.NO_TRANSCRIPT
    assert tr.heard_nothing(conn, song)
    assert tr.offers(conn, cfg, Overrides()) == {"songs": [], "nothing": [], "unsung": [song.id], "transcribed": []}
    moved = dataclasses.replace(song, audio_mtime=(song.audio_mtime or 0) + 5)  # a new file: a new start
    assert not tr.heard_nothing(conn, moved) and not tr.said_not_sung(conn, moved)
    assert tr.why_not_offered(conn, cfg, moved, Overrides()) is None
    tr.keep_transcript(conn, song, made(song))  # Transcribe anyway heard it: their word is gone with it
    assert not tr.said_not_sung(conn, song)
    assert tr.offers(conn, cfg, Overrides()) == {"songs": [], "nothing": [], "unsung": [], "transcribed": [song.id]}
