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


RECORDS = [("lrclib", "9"), ("megalobiz", "24519"), ("azlyrics", "pomme/mononoke")]


@pytest.mark.parametrize("site,record_id", RECORDS)
def test_a_record_written_by_hand_on_a_song_missing_under_its_own_name_is_never_offered(conn, cfg, tmp_path, site,
                                                                                        record_id):
    # The state a hand edit reaches: a song missing under its own name (every site asked), then a record written into
    # [lyrics]: not read yet (it waits the 30 days of the song's miss), and refused all the same, `anyway` or not, in
    # words true of a record read or not, whatever any site's checked: record says (every one is set here). The
    # owner's rule: the lyrics databases before Whisper, and with a record picked only that record is asked.
    from caracole.overrides import LyricsPick, LyricsRecord, override_key

    song = youtube_song(conn, tmp_path)
    picked = Overrides(lyrics={override_key(song.display): LyricsPick(None, LyricsRecord(site, record_id))})
    none = tr.PICKED_NONE.format(record=f"{site} {record_id}")
    assert none == f"the record you picked ({site} {record_id}) has given no lyrics: pick another, or clear the pick"
    for anyway in (False, True):
        assert tr.why_not_offered(conn, cfg, song, picked, anyway=anyway) == none
    nothing_offered = {"songs": [], "nothing": [], "unsung": [], "transcribed": []}
    assert tr.offers(conn, cfg, picked) == nothing_offered  # the served card's member offers it nothing
    tr.note_heard_nothing(conn, song, "2026-11-20T00:00:00Z", why="sung 6.2 s", by="caracole")
    assert tr.offers(conn, cfg, picked) == nothing_offered  # nor Transcribe anyway
    conn.execute("DELETE FROM kv WHERE key = ?", (f"{tr.HEARD_NOTHING}{song.id}",))
    update_song(conn, song.id, lyrics_status="pending", lyrics_at=None)
    pending = get_song(conn, song.id)
    unread = tr.PICKED_UNREAD.format(record=f"{site} {record_id}")
    for anyway in (False, True):
        assert tr.why_not_offered(conn, cfg, pending, picked, anyway=anyway) == unread
    update_song(conn, song.id, lyrics_status="found")
    assert tr.why_not_offered(conn, cfg, get_song(conn, song.id), picked) == "its lyrics are found"


def test_a_cleared_pick_on_a_song_whose_own_name_missed_first_is_offered(conn, cfg, tmp_path):
    # The song's own-name misses came first (every site asked under its name), then a record, then the pick cleared:
    # offered, as any song every site missed. Not covered here: a record's own miss, then the pick cleared, whose stamps
    # read as own-name misses until the command that clears a pick resets them (a later task's).
    from caracole.overrides import LyricsPick, LyricsRecord, override_key

    song = youtube_song(conn, tmp_path)
    key = override_key(song.display)
    assert tr.why_not_offered(conn, cfg, song, Overrides(lyrics={key: LyricsPick(None, LyricsRecord("lrclib", "9"))}))
    assert tr.why_not_offered(conn, cfg, song, Overrides()) is None  # the pick cleared
    named = Overrides(lyrics={key: LyricsPick(("A", "T2"), None)})
    assert tr.why_not_offered(conn, cfg, song, named) is None  # a name alone: as before


def _record_gone(conn, tmp_path, site: str, record_id: str, picks):
    """The song's site asked for the record you picked and answered it gone, its pass run as the nightly run's."""
    from datetime import UTC, datetime

    from helpers.azlyrics_site import FakeAzLyrics
    from helpers.megalobiz_site import FakeMegalobiz
    from test_lyrics_pending import FakeLrclib

    from caracole.azlyrics_fetch import azlyrics_lyrics
    from caracole.lyrics import fetch_pending_lyrics
    from caracole.megalobiz_fetch import megalobiz_lyrics

    now, cache, library = datetime(2026, 11, 20, tzinfo=UTC), tmp_path / "cache", tmp_path / "library"
    if site == "lrclib":
        fake = FakeLrclib()
        stats = fetch_pending_lyrics(conn, fake.client(cache), library, now, picks=picks)
        asked = [endpoint for endpoint, _ in fake.requests]
    elif site == "megalobiz":
        fake = FakeMegalobiz()
        stats = megalobiz_lyrics(conn, fake.client(cache, now=now), library, now, picks=picks)
        asked = [endpoint for endpoint, _ in fake.requests]
    else:
        fake = FakeAzLyrics({})
        stats = azlyrics_lyrics(conn, fake.client(cache, now=now), library, now, lyrics=picks)
        asked = fake.requests
    assert stats.missing == 1 and len(asked) == 1, asked
    return asked


@pytest.mark.parametrize("site,record_id", RECORDS)
def test_a_record_its_site_answered_gone_is_never_offered(conn, cfg, tmp_path, site, record_id):
    # The record asked for and answered gone by its site's own pass: the song missing, never heard, `anyway` or not.
    from caracole.overrides import LyricsPick, LyricsRecord, override_key

    song = youtube_song(conn, tmp_path, lyrics_status="pending", lyrics_at=None)
    for key in ("megalobiz:checked:", "azlyrics:checked:"):  # no site has asked about it yet
        conn.execute("DELETE FROM kv WHERE key = ?", (f"{key}{song.id}",))
    picked = Overrides(lyrics={override_key(song.display): LyricsPick(None, LyricsRecord(site, record_id))})
    _record_gone(conn, tmp_path, site, record_id, picked.lyrics)
    song = get_song(conn, song.id)
    assert song.lyrics_status == "missing"
    for anyway in (False, True):
        assert tr.why_not_offered(conn, cfg, song, picked, anyway=anyway) == tr.PICKED_NONE.format(
            record=f"{site} {record_id}")


def test_a_kept_transcript_is_still_offered_not_sung_once_a_record_is_picked(conn, cfg, tmp_path):
    # Not sung, chords only, runs no Whisper and drops a transcript: a record picked since doesn't refuse it, while a
    # transcription stays refused.
    from caracole.overrides import LyricsPick, LyricsRecord, override_key

    song = youtube_song(conn, tmp_path)
    tr.keep_transcript(conn, song, made(song))
    picked = Overrides(lyrics={override_key(song.display): LyricsPick(None, LyricsRecord("megalobiz", "24519"))})
    assert tr.why_not_unsung(conn, cfg, song, picked) is None
    assert tr.offers(conn, cfg, picked)["transcribed"] == [song.id]
    assert tr.why_not_offered(conn, cfg, song, picked, anyway=True) == tr.PICKED_NONE.format(record="megalobiz 24519")


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


def test_whisper_cant_read_drops_nothing_sung_and_the_card_offers_nothing_over_that_file(conn, cfg, tmp_path):
    # caracole noted nothing sung on too little singing (Whisper never ran); the owner asked anyway; Whisper can't load
    # the file. Its verdict of nothing sung goes: the card offers no Transcribe anyway that can only fail again.
    song = youtube_song(conn, tmp_path)
    tr.note_heard_nothing(conn, song, "2026-11-25T00:00:00Z", why="sung 6.2 s", by="caracole")
    assert tr.offers(conn, cfg, Overrides())["nothing"] == [song.id]
    tr.note_whisper_cant_read(conn, song, "2026-11-25T01:00:00Z", "RuntimeError: Failed to load audio")
    assert not tr.heard_nothing(conn, song)
    assert tr.offers(conn, cfg, Overrides()) == {"songs": [], "nothing": [], "unsung": [], "transcribed": []}
    assert tr.why_not_offered(conn, cfg, song, Overrides()) == tr.WHISPER_UNREADABLE_WHY


@pytest.mark.parametrize("came", ["transcript", "nothing sung", "whisper can't read"])
def test_a_hearing_that_comes_to_something_drops_the_failed_hearings_note(conn, cfg, tmp_path, came):
    from datetime import UTC, datetime

    song = youtube_song(conn, tmp_path)
    now = datetime(2026, 11, 25, 3, 0, tzinfo=UTC)
    tr.note_hearing_failed(conn, song, "2026-11-25T03:00:00Z", "the separator can't run here (x)")
    assert tr.hearing_failed(conn, song, now) == "the separator can't run here (x)"
    assert tr.why_not_offered(conn, cfg, song, Overrides()) is None  # by hand, offered as ever
    if came == "transcript":
        tr.keep_transcript(conn, song, made(song))
    elif came == "nothing sung":
        tr.note_heard_nothing(conn, song, "2026-11-25T04:00:00Z", why="sung 6.2 s", by="caracole")
    else:
        tr.note_whisper_cant_read(conn, song, "2026-11-25T04:00:00Z", "RuntimeError: Failed to load audio")
    assert kv_get(conn, f"{tr.HEARING_FAILED}{song.id}") is None and tr.hearing_failed(conn, song, now) is None


def test_a_removal_takes_the_failed_hearings_note_with_the_song(conn, cfg, tmp_path):
    from caracole.songs import _PER_SONG_KV, delete_song_kv

    song = youtube_song(conn, tmp_path)
    tr.note_hearing_failed(conn, song, "2026-11-25T03:00:00Z", "the GPU failed: CUDA out of memory")
    assert tr.HEARING_FAILED in _PER_SONG_KV
    delete_song_kv(conn, song.id)
    assert kv_get(conn, f"{tr.HEARING_FAILED}{song.id}") is None


@pytest.mark.parametrize("words_win", [True, False])
def test_a_song_whose_auto_sheet_another_caracole_made_is_offered_its_words_as_any(conn, cfg, tmp_path, monkeypatch,
                                                                                    words_win):
    # Decision 5 decides what words heard here do to that sheet (run.py), never whether the card offers them: with
    # words winning the nightly pass hears them too; without, Transcribe the lyrics by hand is the one way.
    assert tr.WORDS_WIN is True  # the design's recommendation, in force until the owner says otherwise
    monkeypatch.setattr(tr, "WORDS_WIN", words_win)
    song = youtube_song(conn, tmp_path)
    version = upsert_version(conn, provider="auto", tab_id="42", song_id=song.id, slot="sheet", kind="auto", rating=0,
                             votes=0, version=1, label=None, url="file:///data/phone/x.mp3",
                             raw={"lyrics": "none", "heard": {"contract": 1}, "made_on": "phone",
                                  "made_by": "0f1e2d3c4b5a6978"}, now="2026-11-20T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=version, name="sheet (auto).txt", data=b"[C]", rank=1)
    assert tr.why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) is None
    assert song.id in tr.offers(conn, cfg, Overrides())["songs"]
