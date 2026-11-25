"""audio_store.py: the audio files you give caracole for a song, kept in caracole's own folder, ``state_dir/audio/``."""

from __future__ import annotations

import hashlib
import io
import os
import stat
import struct
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import add_song, subprocess_pythonpath
from helpers.audio_files import FORMATS as MADE
from helpers.audio_files import audio, mp4, ogg_speex, write

from caracole import audio_store
from caracole.audio_store import (
    AUDIO_MAX,
    EXPIRES,
    FORMATS,
    HEAD,
    MAX_SECONDS,
    NO_ROOM,
    NOT_AUDIO,
    ROOM,
    TOO_BIG,
    TOO_LONG,
    AudioError,
    drop,
    keep,
    stage,
    staged,
    sweep,
    tidy,
    uploaded,
)
from caracole.songs import get_song, update_song


@pytest.fixture(autouse=True)
def room(monkeypatch):
    """Room on the disk for every file kept (``ROOM`` is a GiB); test_too_little_room_is_refused says less."""
    monkeypatch.setattr(audio_store, "disk_usage", lambda path: SimpleNamespace(total=10**15, used=0, free=10**15))


def store(cfg) -> Path:
    return cfg.state_dir / "audio"


def names(cfg) -> list[str]:
    """What the store holds, by name: none when there is no store."""
    return sorted(p.name for p in store(cfg).iterdir()) if store(cfg).exists() else []


def mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def refused(status: int, call, *args, **kwargs) -> AudioError:
    with pytest.raises(AudioError) as e:
        call(*args, **kwargs)
    assert e.value.status == status, e.value
    return e.value


def ftyp(major: bytes, *compatible: bytes) -> bytes:
    body = major + b"\x00\x00\x00\x00" + b"".join(compatible)
    return struct.pack(">I", 8 + len(body)) + b"ftyp" + body


# --- what a file is ---------------------------------------------------------------------------------------------


def test_the_limits_and_the_formats():
    assert AUDIO_MAX == 128 * 1024 * 1024 and MAX_SECONDS == 30 * 60
    assert FORMATS == {"MP3": ".mp3", "M4A": ".m4a", "FLAC": ".flac", "WAV": ".wav", "Ogg": ".ogg", "AIFF": ".aiff"}
    assert set(MADE) == set(FORMATS)


@pytest.mark.parametrize("fmt", MADE)
def test_sniff_knows_each_format_by_its_bytes(fmt, tmp_path):
    assert audio_store.sniff(audio(fmt)[:HEAD]) == fmt
    tagged = write(tmp_path / f"tagged{FORMATS[fmt]}", fmt, artist="Radiohead", title="Creep")  # an MP3's ID3 tag comes first
    assert audio_store.sniff(tagged.read_bytes()[:HEAD]) == fmt


@pytest.mark.parametrize("head, fmt", [
    (b"ID3\x04\x00\x00\x00\x00\x00\x00", "MP3"),
    (b"\xff\xfb\x90\xc0", "MP3"),  # MPEG-1 Layer III
    (b"\xff\xf3\x48\xc4", "MP3"),  # MPEG-2 Layer III
    (b"\xff\xe3\x18\xc4", "MP3"),  # MPEG-2.5 Layer III
    (b"\xff\xfd\x90\xc0", "MP3"),  # MPEG-1 Layer II
    (ftyp(b"M4A ", b"M4A ", b"isom"), "M4A"),
    (ftyp(b"mp42", b"isom"), "M4A"),
    (ftyp(b"isom", b"iso2"), "M4A"),
    (ftyp(b"M4B "), "M4A"),
    (ftyp(b"dash", b"iso6", b"mp41"), "M4A"),  # YouTube's audio as yt-dlp takes it, before FFmpeg's fix-up
    (ftyp(b"M4A ", b"M4A ", b"isom", b"iso2"), "M4A"),  # FFmpeg's .m4a
    (ftyp(b"isom", b"iso2", b"mp41"), "M4A"),  # FFmpeg's .mp4
    (ftyp(b"iso5", b"iso6", b"mp41"), "M4A"),  # FFmpeg's for DASH
    (ftyp(b"mp41"), "M4A"),
    (ftyp(b"iso2"), "M4A"),
    (ftyp(b"M4V ", b"M4A ", b"mp42", b"isom"), "M4A"),  # one of its compatible brands: its audio track decides
    (b"fLaC\x00\x00\x00\x22", "FLAC"),
    (b"RIFF\x24\x00\x00\x00WAVEfmt ", "WAV"),
    (b"OggS\x00\x02", "Ogg"),
    (b"FORM\x00\x00\x00\x00AIFF", "AIFF"),
    (b"FORM\x00\x00\x00\x00AIFC", "AIFF"),
    (b"", None),
    (b"not really audio", None),
    (b"\xff\xf1\x50\x80", None),  # ADTS AAC, layer 0: no MP3
    (b"\xff\xfb\xf0\xc0", None),  # a bitrate no MPEG frame has
    (b"\xff\xfb\x9c\xc0", None),  # a sample rate no MPEG frame has
    (b"\xff\xeb\x90\xc0", None),  # MPEG version 1 is reserved
    (ftyp(b"qt  ", b"qt  "), None),  # QuickTime
    (ftyp(b"heic", b"mif1"), None),  # a picture
    (ftyp(b"avif", b"mif1", b"miaf"), None),
    (ftyp(b"M4V ", b"M4V "), None),  # iTunes' video
    (ftyp(b"3gp4", b"3gp4"), None),
    (ftyp(b"crx ", b"isom")[:12], None),  # brands cut off where the bytes end
    (b"RIFF\x24\x00\x00\x00AVI LIST", None),
    (b"FORM\x00\x00\x00\x008SVX", None),
    (b"\x89PNG\r\n\x1a\n", None),
    (b"%PDF-1.7", None),
])
def test_sniff_reads_the_bytes_alone(head, fmt):
    assert audio_store.sniff(head) == fmt


@pytest.mark.parametrize("fmt", MADE)
def test_each_format_is_read_with_its_length_and_tags(fmt, cfg, tmp_path):
    data = write(tmp_path / f"song{FORMATS[fmt]}", fmt, 2.0, artist="Radiohead", title="Creep",
                 album="Pablo Honey").read_bytes()
    up = stage(cfg, data, "song", named=())
    assert (up.format, up.path.suffix) == (fmt, FORMATS[fmt]) and abs(up.duration - 2.0) < 0.05
    assert up.tags == {"artist": "Radiohead", "title": "Creep", "album": "Pablo Honey"}


@pytest.mark.parametrize("major, compatible", [(b"dash", (b"iso6", b"mp41")), (b"isom", (b"iso2", b"mp41")),
                                               (b"iso5", (b"iso6", b"mp41")), (b"mp42", (b"isom", b"mp42"))])
def test_an_mp4_of_any_audio_brand_is_an_m4a(cfg, major, compatible):
    up = stage(cfg, mp4(1.5, major=major, compatible=compatible), "yt.webm", named=())
    assert (up.format, up.path.suffix, up.duration) == ("M4A", ".m4a", 1.5)


def test_an_mp4_with_no_audio_track_is_refused(cfg):
    # mutagen reads a video alone as long as the movie (its mvhd): the audio track it lacks is what refuses it.
    from mutagen.mp4 import MP4

    video = mp4(3.0, major=b"isom", compatible=(b"isom", b"iso2", b"avc1", b"mp41"), video=True)
    assert audio_store.sniff(video[:HEAD]) == "M4A" and MP4(io.BytesIO(video)).info.length == 3.0
    said = refused(415, stage, cfg, video, "clip.mp4", named=())
    assert str(said) == NOT_AUDIO and names(cfg) == []


def test_whatever_a_hostile_file_makes_the_tag_reader_raise_is_a_refusal(conn, cfg, tmp_path, monkeypatch):
    # mutagen 1.48's OggSpeex divides by its header's rate, unguarded: a rate of 0 raised ZeroDivisionError.
    said = refused(415, stage, cfg, ogg_speex(rate=0), "speex.ogg", named=())
    assert str(said) == NOT_AUDIO and names(cfg) == []
    from mutagen.wave import WAVE

    def raising(error):
        def load(self, *args, **kwargs):
            raise error
        return load

    for error in (ArithmeticError("anything"), AttributeError("a reader's bug"), MemoryError(), OSError("bytes")):
        monkeypatch.setattr(WAVE, "load", raising(error))
        refused(415, stage, cfg, audio("WAV"), "song.wav", named=())  # bytes in memory: whatever it is, theirs
    assert names(cfg) == []
    song = add_song(conn, "Radiohead", "Creep")
    with pytest.raises(OSError, match="the disk's"):  # reading a file of the disk: the disk's, no refusal
        monkeypatch.setattr(WAVE, "load", raising(OSError("the disk's")))
        keep(cfg, conn, song, write(tmp_path / "song.wav", "WAV"), move=False)
    with pytest.raises(KeyboardInterrupt):
        monkeypatch.setattr(WAVE, "load", raising(KeyboardInterrupt()))
        stage(cfg, audio("WAV"), "song.wav", named=())
    monkeypatch.undo()
    monkeypatch.setattr(audio_store, "disk_usage", lambda path: SimpleNamespace(total=10**15, used=0, free=10**15))
    up = stage(cfg, ogg_speex(rate=8000), "speex.ogg", named=())  # the same file at a rate is read
    assert (up.format, up.duration) == ("Ogg", 2.0)


def test_a_file_named_mp3_that_isnt_one_is_refused(conn, cfg, tmp_path):
    said = refused(415, stage, cfg, b"not really audio, whatever its name says" * 10, "song.mp3", named=())
    assert str(said) == NOT_AUDIO == "Not an audio file caracole reads (MP3, M4A, FLAC, WAV, Ogg or AIFF)."
    refused(415, stage, cfg, b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"junk" * 100, "song.mp3", named=())  # no frame
    refused(415, stage, cfg, audio("WAV", 0), "silence.wav", named=())  # mutagen reads no length
    assert names(cfg) == []
    # A WAV named song.mp3 is a WAV, kept as one: the extension is caracole's, from the bytes.
    wav = stage(cfg, audio("WAV"), "song.mp3", named=())
    assert (wav.format, wav.path.suffix, wav.name) == ("WAV", ".wav", "song.mp3")
    song = add_song(conn, "Radiohead", "Creep")
    fake = tmp_path / "creep.mp3"
    fake.write_bytes(b"not really audio" * 10)
    refused(415, keep, cfg, conn, song, fake, move=False)
    refused(415, keep, cfg, conn, song, tmp_path, move=False)  # a folder
    assert get_song(conn, song.id).audio_path is None
    assert names(cfg) == sorted([wav.path.name, f".upload-{wav.id}.json"])


def test_a_file_past_the_limits_is_refused(conn, cfg, tmp_path, monkeypatch):
    said = refused(422, stage, cfg, audio("FLAC", MAX_SECONDS + 1), "long.flac", named=())
    assert str(said) == TOO_LONG == "That file is longer than 30 minutes."
    assert stage(cfg, audio("FLAC", MAX_SECONDS), "long.flac", named=()).duration == MAX_SECONDS
    song = add_song(conn, "Radiohead", "Creep")
    refused(422, keep, cfg, conn, song, write(tmp_path / "long.flac", "FLAC", MAX_SECONDS + 1), move=False)
    data = audio("MP3")
    monkeypatch.setattr(audio_store, "AUDIO_MAX", len(data) - 1)
    said = refused(413, stage, cfg, data, "song.mp3", named=())
    assert str(said) == TOO_BIG == ("That file is too big: an audio file is 128 MiB at most; `caracole audio FILE` "
                                    "takes any.")
    # The command takes any size: a file of its own is no upload.
    assert keep(cfg, conn, song, write(tmp_path / "big.mp3", "MP3"), move=False).exists()
    refused(400, stage, cfg, b"", "song.mp3", named=())
    refused(400, stage, cfg, data[:10], "\x00\x1f/", named=())  # no name left


# --- a staged upload ----------------------------------------------------------------------------------------------


def test_an_upload_is_staged_privately_and_one_unconfirmed_at_a_time(cfg, tmp_path):
    data = write(tmp_path / "creep.mp3", "MP3", artist="Radiohead", title="Creep", album="Pablo Honey").read_bytes()
    first = stage(cfg, data, "../../Music/01 Creep.mp3", named=())
    assert mode(store(cfg)) == 0o700
    assert audio_store.ID.fullmatch(first.id) and first.path == store(cfg) / f".upload-{first.id}.mp3"
    assert mode(first.path) == 0o600 and mode(store(cfg) / f".upload-{first.id}.json") == 0o600
    assert first.path.read_bytes() == data
    assert first.name == "01 Creep.mp3"  # its last part, a name to show: never a path
    assert (first.size, first.sha256, first.format) == (len(data), hashlib.sha256(data).hexdigest(), "MP3")
    assert abs(first.duration - 1.0) < 0.05
    assert first.tags == {"artist": "Radiohead", "title": "Creep", "album": "Pablo Honey"}
    assert staged(cfg, first.id) == first
    # Control characters out, and 255 characters at most; a job names the first, which stays.
    odd = stage(cfg, audio("WAV"), "C:\\Users\\me\\a\x00b\x1f\n" + "x" * 300 + ".wav", named={first.id})
    assert odd.name == ("ab" + "x" * 300)[:255] and odd.tags == {"artist": None, "title": None, "album": None}
    assert staged(cfg, first.id) == first and staged(cfg, odd.id) == odd
    # A new one lets go of every earlier one no job names.
    third = stage(cfg, audio("FLAC"), "c.flac", named={odd.id})
    refused(404, staged, cfg, first.id)
    assert staged(cfg, odd.id) == odd and staged(cfg, third.id) == third
    assert names(cfg) == sorted([odd.path.name, f".upload-{odd.id}.json", third.path.name,
                                 f".upload-{third.id}.json"])


def test_a_staged_id_names_one_regular_file_in_the_store_never_a_path_or_a_link(conn, cfg, tmp_path):
    for bad in ("../../caracole.sqlite", "0123456789ABCDEF", "0123456789abcde", "0123456789abcdef0",
                "0123456789abcdef/../x", "0123456789abcdef\n", "０１２３４５６７８９ａｂｃｄｅｆ", 42, None):
        refused(400, staged, cfg, bad)
        refused(400, drop, cfg, bad)
    refused(404, staged, cfg, "0123456789abcdef")
    secret = tmp_path / "secret"
    secret.write_bytes(audio("MP3"))
    up = stage(cfg, audio("MP3"), "a.mp3", named=())
    up.path.unlink()
    up.path.symlink_to(secret)  # a link planted in its place is never followed
    refused(404, staged, cfg, up.id)
    song = add_song(conn, "Radiohead", "Creep")
    refused(404, keep, cfg, conn, song, up.path, move=True)
    refused(404, keep, cfg, conn, song, secret, move=True)  # a move takes a staged upload alone
    assert secret.read_bytes() == audio("MP3") and get_song(conn, song.id).audio_path is None
    drop(cfg, up.id)  # the link goes, never what it points at
    assert not os.path.lexists(up.path) and secret.exists()
    # Two audio files under one id: neither is the upload.
    two = stage(cfg, audio("MP3"), "b.mp3", named=())
    (store(cfg) / f".upload-{two.id}.wav").write_bytes(audio("WAV"))
    refused(404, staged, cfg, two.id)


def test_a_link_in_place_of_the_store_is_refused(cfg, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o755)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    store(cfg).symlink_to(elsewhere)
    refused(500, stage, cfg, audio("MP3"), "a.mp3", named=())
    assert list(elsewhere.iterdir()) == [] and mode(elsewhere) == 0o755


def test_a_staged_upload_is_dropped_now_or_swept_after_an_hour_unless_a_job_names_it(cfg):
    import time

    one = stage(cfg, audio("MP3"), "a.mp3", named=())
    two = stage(cfg, audio("WAV"), "b.wav", named={one.id})
    (store(cfg) / ".upload-0123456789abcdef.ogg").write_bytes(b"what a stopped upload left")
    (store(cfg) / "notes.txt").write_text("not caracole's")
    assert sweep(cfg, set()) == []  # nothing an hour old
    later = time.time() + EXPIRES + 1
    assert sorted(sweep(cfg, {two.id}, now=later)) == sorted([one.id, "0123456789abcdef"])
    refused(404, staged, cfg, one.id)
    assert staged(cfg, two.id) == two and (store(cfg) / "notes.txt").exists()
    drop(cfg, two.id)
    refused(404, staged, cfg, two.id)
    refused(404, drop, cfg, two.id)
    assert names(cfg) == ["notes.txt"]


# --- a song's own audio --------------------------------------------------------------------------------------------


def test_keep_names_it_by_song_and_digest_and_links_it(conn, cfg, tmp_path):
    song = add_song(conn, "Radiohead", "Creep")
    given = write(tmp_path / "home" / "creep.flac", "FLAC", 2.0)
    kept = keep(cfg, conn, song, given, move=False)
    digest = hashlib.sha256(given.read_bytes()).hexdigest()
    assert kept == store(cfg) / f"{song.id}-{digest[:16]}.flac"
    assert kept.read_bytes() == given.read_bytes() and given.exists()  # a file of yours is copied
    assert mode(kept) == 0o600 and mode(store(cfg)) == 0o700
    after = get_song(conn, song.id)
    assert (after.audio_path, after.audio_mtime) == (str(kept), kept.stat().st_mtime)
    assert uploaded(cfg, after) == kept
    # The same file again is the song's audio already: nothing changes.
    assert keep(cfg, conn, song, given, move=False) == kept
    assert get_song(conn, song.id).audio_mtime == after.audio_mtime
    # A staged upload is moved, and its record goes with it.
    other = add_song(conn, "Oasis", "Wonderwall")
    up = stage(cfg, audio("Ogg", 1.5), "wonderwall.opus", named=())
    moved = keep(cfg, conn, other, up.path, move=True)
    assert moved == store(cfg) / f"{other.id}-{up.sha256[:16]}.ogg" and mode(moved) == 0o600
    refused(404, staged, cfg, up.id)
    assert names(cfg) == sorted([kept.name, moved.name])  # nothing left over
    assert uploaded(cfg, get_song(conn, other.id)) == moved


def test_a_songs_audio_is_an_upload_only_when_it_is_a_kept_file_of_the_store(conn, cfg, tmp_path):
    song = add_song(conn, "Radiohead", "Creep")
    kept = keep(cfg, conn, song, write(tmp_path / "creep.mp3", "MP3"), move=False)
    assert uploaded(cfg, get_song(conn, song.id)) == kept
    for path in (cfg.music_dir / "Creep.mp3", cfg.cache_dir / "youtube" / f"{song.id}-XFkzRNyygfk.m4a",
                 store(cfg) / "sub" / kept.name, store(cfg) / "notes.mp3"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")
        update_song(conn, song.id, audio_path=str(path))
        assert uploaded(cfg, get_song(conn, song.id)) is None, path
    link = store(cfg) / f"{song.id}-{'0' * 16}.mp3"
    link.symlink_to(kept)
    update_song(conn, song.id, audio_path=str(link))
    assert uploaded(cfg, get_song(conn, song.id)) is None
    update_song(conn, song.id, audio_path=None)
    assert uploaded(cfg, get_song(conn, song.id)) is None


def test_an_upload_spelled_through_another_path_to_the_store_is_still_the_songs_upload(conn, cfg, tmp_path):
    # A process may spell state_dir otherwise (a link to it, ".."): the folder is the same, its files the song's.
    from caracole.music import scan_music
    from caracole.removal import plan_removal

    song = add_song(conn, "Radiohead", "Creep", duration_ms=None)
    given = write(tmp_path / "creep.mp3", "MP3")
    kept = keep(cfg, conn, song, given, move=False)
    alias = tmp_path / "alias"
    alias.symlink_to(cfg.state_dir)
    write(cfg.music_dir / "Radiohead - Creep.wav", "WAV", artist="Radiohead", title="Creep")
    for spelled in (alias / "audio" / kept.name, store(cfg) / ".." / "audio" / kept.name):
        update_song(conn, song.id, audio_path=str(spelled))
        assert uploaded(cfg, get_song(conn, song.id)) == kept
        assert plan_removal(conn, cfg, get_song(conn, song.id)).uploaded_audio == str(kept)
        assert tidy(conn, cfg) == 0 and kept.exists()
        scan_music(conn, cfg.music_dir, uploads=store(cfg))
        assert get_song(conn, song.id).audio_path == str(spelled)  # no purchase took its place
        assert keep(cfg, conn, song, given, move=False) == kept and kept.exists()  # the same file, never deleted
        assert get_song(conn, song.id).audio_path == str(kept)


def test_a_new_upload_replaces_the_songs_old_one(conn, cfg, tmp_path):
    song = add_song(conn, "Radiohead", "Creep")
    other = add_song(conn, "Oasis", "Wonderwall")
    first = keep(cfg, conn, song, write(tmp_path / "a.mp3", "MP3"), move=False)
    theirs = keep(cfg, conn, other, write(tmp_path / "b.mp3", "MP3", 2.0), move=False)
    up = stage(cfg, audio("WAV", 2.0), "creep.wav", named=())
    second = keep(cfg, conn, song, up.path, move=True)
    assert not first.exists() and second.exists() and theirs.exists()
    assert get_song(conn, song.id).audio_path == str(second)
    assert get_song(conn, other.id).audio_path == str(theirs)


def test_keep_takes_a_purchases_place_and_leaves_its_file_in_music(conn, cfg, tmp_path):
    # The owner's decision of 2026-11-25: a file you give a song is its audio, whatever it had.
    song = add_song(conn, "Radiohead", "Creep")
    bought = write(cfg.music_dir / "Radiohead - Creep.wav", "WAV", 2.0, artist="Radiohead", title="Creep")
    update_song(conn, song.id, audio_path=str(bought), audio_mtime=bought.stat().st_mtime)
    before = bought.read_bytes()
    kept = keep(cfg, conn, song, write(tmp_path / "mine.flac", "FLAC", 2.0), move=False)
    assert get_song(conn, song.id).audio_path == str(kept)
    assert bought.read_bytes() == before and sorted(cfg.music_dir.iterdir()) == [bought]
    # YouTube's audio too: the song's audio is the file now (youtube_fetch.tidy lets go of YouTube's).
    youtube = cfg.cache_dir / "youtube" / f"{song.id}-XFkzRNyygfk.m4a"
    youtube.parent.mkdir(parents=True)
    youtube.write_bytes(audio("M4A"))
    update_song(conn, song.id, audio_path=str(youtube))
    again = keep(cfg, conn, song, write(tmp_path / "mine.ogg", "Ogg"), move=False)
    assert get_song(conn, song.id).audio_path == str(again) and youtube.exists()


def test_too_little_room_is_refused(conn, cfg, tmp_path, monkeypatch):
    data = audio("MP3")
    free = {"bytes": 2 * len(data) + ROOM - 1}
    monkeypatch.setattr(audio_store, "disk_usage", lambda path: SimpleNamespace(total=10**12, used=0,
                                                                                 free=free["bytes"]))
    said = refused(507, stage, cfg, data, "song.mp3", named=())
    assert str(said) == NO_ROOM == "No room to keep it here."
    song = add_song(conn, "Radiohead", "Creep")
    refused(507, keep, cfg, conn, song, write(tmp_path / "song.mp3", "MP3"), move=False)
    assert names(cfg) == [] and get_song(conn, song.id).audio_path is None
    free["bytes"] += 1
    up = stage(cfg, data, "song.mp3", named=())
    free["bytes"] = 0  # a move takes no room
    assert keep(cfg, conn, song, up.path, move=True).exists()


def test_tidy_deletes_files_no_song_names(conn, cfg, tmp_path):
    song = add_song(conn, "Radiohead", "Creep")
    kept = keep(cfg, conn, song, write(tmp_path / "creep.mp3", "MP3"), move=False)
    orphan = store(cfg) / f"999-{'a' * 16}.mp3"  # a song merged into another, say
    orphan.write_bytes(b"audio")
    leftover = store(cfg) / ".keep-0123456789abcdef.part"  # what a copy cut short left
    leftover.write_bytes(b"half")
    up = stage(cfg, audio("WAV"), "b.wav", named=())  # serve's, until a job takes it or sweep
    mine = store(cfg) / "notes.txt"
    mine.write_text("not caracole's")
    assert tidy(conn, cfg) == 2
    assert kept.exists() and staged(cfg, up.id) == up and mine.exists()
    assert not orphan.exists() and not leftover.exists()
    conn.execute("DELETE FROM songs WHERE id = ?", (song.id,))
    assert tidy(conn, cfg) == 1 and not kept.exists()
    assert tidy(conn, cfg) == 0


def test_tidy_with_no_store_does_nothing(conn, cfg):
    assert tidy(conn, cfg) == 0 and not store(cfg).exists()


@pytest.mark.slow
def test_the_store_imports_no_tag_reader():
    # The pages and the server import it: mutagen is imported only to read a file.
    code = ("import sys; import caracole.audio_store, caracole.removal, caracole.pipeline, caracole.music; "
            "print(sorted(m for m in sys.modules if m.startswith('mutagen')))")
    src = Path(__file__).resolve().parents[1] / "src"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": subprocess_pythonpath(src)})
    assert out.stdout.strip() == "[]"
