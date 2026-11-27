"""autochords/transcript.py: a record of a song's audio follows that audio by its content (the owner's "yes" of
2026-11-27): a file moved, renamed or touched keeps its transcript and its verdicts; other bytes drop them, as ever.
No model runs here."""

from __future__ import annotations

import hashlib
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import add_song

from caracole.autochords import transcript as tr
from caracole.db import kv_get_json, kv_set, kv_set_json
from caracole.overrides import Overrides
from caracole.songs import get_song, update_song

AT = "2026-11-20T00:00:00Z"
NOW = datetime(2026, 11, 21, tzinfo=UTC)
BYTES = b"the purchase's own bytes" * 40


@pytest.fixture(autouse=True)
def hashed(monkeypatch):
    """Every whole read of a file to hash it, by its path; no hash remembered from another test."""
    reads: list[str] = []
    real = tr._read_sha256

    def counting(path):
        reads.append(Path(path).name)
        return real(path)

    tr._HASHED.clear()
    monkeypatch.setattr(tr, "_read_sha256", counting)
    yield reads
    tr._HASHED.clear()


def bought(conn, tmp_path, data=BYTES, name="A - T.mp3", **fields):
    """A song whose audio is a purchase in Music/, its lyrics missing and every site asked about it."""
    song = add_song(conn, "A", "T")
    audio = tmp_path / "Music" / name
    audio.parent.mkdir(parents=True, exist_ok=True)
    audio.write_bytes(data)
    fields = {"lyrics_status": "missing", "lyrics_at": "2026-11-01T00:00:00Z", **fields}
    update_song(conn, song.id, audio_path=str(audio), audio_mtime=os.stat(audio).st_mtime, **fields)
    for site in ("megalobiz", "azlyrics"):
        kv_set(conn, f"{site}:checked:{song.id}", AT)
    return get_song(conn, song.id)


def made(song, **kw):
    fields = dict(lrc="[00:01.00]hello\n", audio=song.audio_path, audio_mtime=song.audio_mtime, model=tr.MODEL,
                  language="en", device="cuda", words_dropped=0, made_at=AT)
    return tr.Transcript(**{**fields, **kw})


def relinked(conn, song, path: Path):
    """The song's audio linked again at ``path``, as music.scan_music links a moved purchase."""
    update_song(conn, song.id, audio_path=str(path), audio_mtime=os.stat(path).st_mtime)
    return get_song(conn, song.id)


def every_record(conn, song):
    """The four records kept of the song's audio, as their readers answer them."""
    return (tr.transcript_of(conn, song) is not None, tr.heard_nothing(conn, song), tr.said_not_sung(conn, song),
            tr.whisper_cant_read(conn, song), tr.hearing_failed(conn, song, NOW))


def noted(conn, song):
    """The song's audio heard (a transcript), said not sung, refused by Whisper and failed to be heard: one of each
    record, all of its audio as it is now (each writer drops another, so they are written as they are kept)."""
    tr.keep_transcript(conn, song, made(song))
    nothing = {"audio": song.audio_path, "audio_mtime": song.audio_mtime, "at": AT, "why": "you said so", "by": "you"}
    kv_set_json(conn, f"{tr.HEARD_NOTHING}{song.id}", {**nothing, **tr.audio_key(song.audio_path, song.audio_mtime)})
    kv_set_json(conn, f"{tr.WHISPER_CANT_READ}{song.id}", {
        "audio": song.audio_path, "audio_mtime": song.audio_mtime, "at": AT, "error": "no decoder",
        **tr.audio_key(song.audio_path, song.audio_mtime)})
    tr.note_hearing_failed(conn, song, AT, "the GPU")


KEPT_ALL = (True, True, True, "no decoder", "the GPU")
NONE = (False, False, False, None, None)


def test_a_record_kept_names_its_audios_content(conn, tmp_path):
    song = bought(conn, tmp_path)
    tr.keep_transcript(conn, song, made(song))
    kept = kv_get_json(conn, f"{tr.TRANSCRIPT}{song.id}")
    assert kept[tr.AUDIO_SIZE] == len(BYTES)
    assert kept[tr.AUDIO_SHA256] == hashlib.sha256(BYTES).hexdigest()
    assert tr.Transcript.from_json(kept) == made(song)  # the members a Transcript holds, as ever


@pytest.mark.parametrize("where", ["renamed", "moved", "touched"])
def test_a_purchase_renamed_moved_or_touched_keeps_every_record(conn, cfg, tmp_path, where):
    song = bought(conn, tmp_path)
    noted(conn, song)
    why = tr.why_not_offered(conn, cfg, song, Overrides())
    old = Path(song.audio_path)
    new = {"renamed": old.with_name("01 - T.mp3"), "moved": tmp_path / "Music" / "Album" / "T.mp3",
           "touched": old}[where]
    new.parent.mkdir(parents=True, exist_ok=True)
    os.rename(old, new)
    if where == "touched":
        os.utime(new, (song.audio_mtime + 100, song.audio_mtime + 100))
    after = relinked(conn, song, new)
    assert (after.audio_path, after.audio_mtime) != (song.audio_path, song.audio_mtime)
    assert every_record(conn, after) == KEPT_ALL
    assert tr.why_not_offered(conn, cfg, after, Overrides()) == why


def test_other_bytes_under_the_same_path_or_another_drop_every_record(conn, cfg, tmp_path, hashed):
    song = bought(conn, tmp_path)
    noted(conn, song)
    old = Path(song.audio_path)
    hashed.clear()
    old.write_bytes(b"another take" * 10)  # other bytes, of another size: no hash needed
    other = relinked(conn, song, old)
    assert every_record(conn, other) == NONE
    assert hashed == []
    same_size = bytes(reversed(BYTES))
    old.write_bytes(same_size)  # other bytes of the same size: hashed, once
    os.utime(old, (song.audio_mtime + 7, song.audio_mtime + 7))
    other = relinked(conn, song, old)
    assert every_record(conn, other) == NONE
    assert hashed == [old.name]
    elsewhere = tmp_path / "Music" / "Other.mp3"
    elsewhere.write_bytes(b"another song" * 7)
    assert every_record(conn, relinked(conn, song, elsewhere)) == NONE
    assert tr.why_not_offered(conn, cfg, relinked(conn, song, elsewhere), Overrides()) is None


def given(tmp_path, song_id: int, data: bytes) -> Path:
    """A file given the song, as audio_store.keep names it in state_dir/audio/."""
    path = tmp_path / "state" / "audio" / f"{song_id}-{hashlib.sha256(data).hexdigest()[:16]}.mp3"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_a_given_file_is_known_by_its_name_and_another_upload_is_other_audio(conn, tmp_path, hashed):
    song = bought(conn, tmp_path)
    first = given(tmp_path, song.id, BYTES)
    song = relinked(conn, song, first)
    noted(conn, song)
    hashed.clear()
    second = given(tmp_path, song.id, b"another upload" * 9)
    first.unlink()
    assert every_record(conn, relinked(conn, song, second)) == NONE
    second.unlink()
    again = given(tmp_path, song.id, BYTES)  # the same file given again: the same name, a new mtime
    os.utime(again, (song.audio_mtime + 50, song.audio_mtime + 50))
    assert every_record(conn, relinked(conn, song, again)) == KEPT_ALL
    assert hashed == []  # a given file's key is its name's: nothing read


def test_a_purchase_heard_then_given_as_an_upload_keeps_its_records_by_the_uploads_name(conn, tmp_path, hashed):
    song = bought(conn, tmp_path)
    noted(conn, song)
    hashed.clear()
    upload = given(tmp_path, song.id, BYTES)
    Path(song.audio_path).unlink()
    assert every_record(conn, relinked(conn, song, upload)) == KEPT_ALL
    assert hashed == []


def test_an_old_record_with_no_key_holds_while_its_path_and_mtime_do_and_is_keyed_by_a_pass(conn, tmp_path, hashed):
    song = bought(conn, tmp_path)
    old = {**made(song).as_json()}
    kv_set_json(conn, f"{tr.TRANSCRIPT}{song.id}", old)
    assert tr.transcript_of(conn, song) is not None
    assert kv_get_json(conn, f"{tr.TRANSCRIPT}{song.id}") == old  # a read writes nothing
    assert hashed == []
    assert tr.follow_audio(conn, song) == 1  # a pass that may write keys it, lazily
    assert kv_get_json(conn, f"{tr.TRANSCRIPT}{song.id}") == {**old, **tr.audio_key(song.audio_path, song.audio_mtime)}
    assert tr.follow_audio(conn, song) == 0
    # Unkeyed, once its path and mtime differ, nothing proves the bytes: other audio, as before.
    kv_set_json(conn, f"{tr.TRANSCRIPT}{song.id}", old)
    moved = Path(song.audio_path).with_name("moved.mp3")
    os.rename(song.audio_path, moved)
    after = relinked(conn, song, moved)
    assert tr.transcript_of(conn, after) is None
    assert tr.follow_audio(conn, after) == 0
    assert kv_get_json(conn, f"{tr.TRANSCRIPT}{song.id}") == old


def test_a_pass_re_points_the_records_of_a_moved_file_and_reads_answer_alike_meanwhile(conn, tmp_path, hashed):
    song = bought(conn, tmp_path)
    noted(conn, song)
    before = {p: kv_get_json(conn, f"{p}{song.id}") for p in tr.RECORDS}
    moved = tmp_path / "Music" / "Album" / "T.mp3"
    moved.parent.mkdir()
    shutil.move(song.audio_path, moved)
    after = relinked(conn, song, moved)
    hashed.clear()
    assert every_record(conn, after) == KEPT_ALL  # answered by content, nothing written
    assert every_record(conn, after) == KEPT_ALL
    assert hashed == [moved.name]  # one read for every answer of the same file
    assert {p: kv_get_json(conn, f"{p}{song.id}") for p in tr.RECORDS} == before
    assert tr.follow_audio(conn, after) == 4
    for prefix in tr.RECORDS:
        record = kv_get_json(conn, f"{prefix}{song.id}")
        assert (record["audio"], record["audio_mtime"]) == (after.audio_path, after.audio_mtime)
        assert {k: v for k, v in record.items() if k not in ("audio", "audio_mtime")} == {
            k: v for k, v in before[prefix].items() if k not in ("audio", "audio_mtime")}
    assert tr.follow_audio(conn, after) == 0


def test_the_cards_offers_are_the_same_after_a_move(conn, cfg, tmp_path):
    heard = bought(conn, tmp_path, name="heard.mp3")
    tr.keep_transcript(conn, heard, made(heard))
    offers = tr.offers(conn, cfg, Overrides())
    assert offers["transcribed"] == [heard.id]
    moved = Path(heard.audio_path).with_name("moved.mp3")
    os.rename(heard.audio_path, moved)
    relinked(conn, heard, moved)
    kv = conn.execute("SELECT key, value FROM kv ORDER BY key").fetchall()
    assert tr.offers(conn, cfg, Overrides()) == offers
    assert conn.execute("SELECT key, value FROM kv ORDER BY key").fetchall() == kv  # a page build writes nothing


# The review of 2026-11-27: a record is keyed only with the bytes it names (its path and mtime as the file stands).


def test_an_old_record_is_never_keyed_with_bytes_that_replaced_its_own(conn, tmp_path):
    song = bought(conn, tmp_path)  # the row: its path, mtime and first bytes
    old = made(song).as_json()  # an old unkeyed transcript of those bytes
    kv_set_json(conn, f"{tr.TRANSCRIPT}{song.id}", old)
    path = Path(song.audio_path)
    path.write_bytes(b"other bytes entirely" * 5)  # replaced in place before any scan
    os.utime(path, (song.audio_mtime + 50, song.audio_mtime + 50))
    assert tr.follow_audio(conn, song) == 0  # a pass with the row as it was: its mtime isn't the file's, no key
    assert kv_get_json(conn, f"{tr.TRANSCRIPT}{song.id}") == old
    after = relinked(conn, song, path)  # the next scan links the new mtime
    assert tr.transcript_of(conn, after) is None


def test_a_record_kept_after_its_file_changed_is_keyed_with_nothing(conn, tmp_path):
    song = bought(conn, tmp_path)
    heard = made(song)  # heard of the first bytes, at the row's mtime
    path = Path(song.audio_path)
    path.write_bytes(b"other bytes entirely" * 5)  # changed while Whisper ran
    os.utime(path, (song.audio_mtime + 50, song.audio_mtime + 50))
    tr.keep_transcript(conn, song, heard)
    tr.note_hearing_failed(conn, song, AT, "the GPU")
    for prefix in (tr.TRANSCRIPT, tr.HEARING_FAILED):
        assert tr.AUDIO_SHA256 not in kv_get_json(conn, f"{prefix}{song.id}"), prefix
    after = relinked(conn, song, path)
    assert tr.transcript_of(conn, after) is None
    assert tr.hearing_failed(conn, after, NOW) is None
