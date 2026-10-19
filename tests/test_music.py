import os
import wave
from pathlib import Path

from mutagen.id3 import TALB, TIT2, TPE1
from mutagen.wave import WAVE

from tabarr.music import AUDIO_EXTENSIONS, read_audio, scan_music
from tabarr.songs import get_song

from conftest import add_song


def make_wav(path: Path, seconds: float = 1.0, *, artist=None, title=None, album=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * seconds))
    if artist or title or album:
        f = WAVE(path)
        f.add_tags()
        if artist:
            f.tags.add(TPE1(encoding=3, text=artist))
        if title:
            f.tags.add(TIT2(encoding=3, text=title))
        if album:
            f.tags.add(TALB(encoding=3, text=album))
        f.save()
    return path


def test_read_audio_tags_and_duration(tmp_path):
    p = make_wav(tmp_path / "x.wav", 2.0, artist="Radiohead", title="Creep", album="Pablo Honey")
    af = read_audio(p)
    assert (af.artist, af.title, af.album) == ("Radiohead", "Creep", "Pablo Honey")
    assert abs(af.duration_s - 2.0) < 0.01
    assert af.mtime == os.stat(p).st_mtime


def test_read_audio_filename_fallback(tmp_path):
    af = read_audio(make_wav(tmp_path / "Soda Stereo - De Música Ligera.wav"))
    assert (af.artist, af.title) == ("Soda Stereo", "De Música Ligera")
    af = read_audio(make_wav(tmp_path / "Soda Stereo" / "Canción Animal" / "03 - De Música Ligera.wav"))
    assert (af.artist, af.title) == ("Soda Stereo", "De Música Ligera")


def test_read_audio_unreadable_file(tmp_path):
    p = tmp_path / "Radiohead - Creep.mp3"
    p.write_bytes(b"not really audio")
    af = read_audio(p)
    assert (af.artist, af.title, af.duration_s) == ("Radiohead", "Creep", None)


def test_tags_matched(conn, tmp_path):
    s = add_song(conn, "Radiohead", "Creep", duration_ms=2000)
    make_wav(tmp_path / "music" / "a.wav", 2.0, artist="Radiohead", title="Creep (Remastered)")
    stats = scan_music(conn, tmp_path / "music")
    assert (stats.seen, stats.matched, stats.unmatched) == (1, 1, [])
    song = get_song(conn, s.id)
    assert song.audio_path == str(tmp_path / "music" / "a.wav") and song.audio_mtime


def test_cjk_tags_matched(conn, tmp_path):
    s = add_song(conn, "宋冬野", "斑马，斑马", duration_ms=1000)
    make_wav(tmp_path / "music" / "banma.wav", 1.0, artist="宋冬野", title="斑马斑马")
    scan_music(conn, tmp_path / "music")
    assert get_song(conn, s.id).audio_path.endswith("banma.wav")


def test_fuzzy_match(conn, tmp_path):
    s = add_song(conn, "Enanitos Verdes", "Lamento Boliviano", duration_ms=None)
    make_wav(tmp_path / "music" / "x.wav", artist="Los Enanitos Verdes", title="Lamento Boliviano")
    scan_music(conn, tmp_path / "music")
    assert get_song(conn, s.id).audio_path is not None


def test_duration_mismatch_rejected(conn, tmp_path):
    s = add_song(conn, "Radiohead", "Creep", duration_ms=238000)
    make_wav(tmp_path / "music" / "a.wav", 2.0, artist="Radiohead", title="Creep")
    stats = scan_music(conn, tmp_path / "music")
    assert stats.matched == 0 and len(stats.unmatched) == 1
    assert get_song(conn, s.id).audio_path is None


def test_missing_file_clears_audio_path(conn, tmp_path):
    s = add_song(conn, "Radiohead", "Creep", duration_ms=None)
    p = make_wav(tmp_path / "music" / "a.wav", artist="Radiohead", title="Creep")
    scan_music(conn, tmp_path / "music")
    p.unlink()
    scan_music(conn, tmp_path / "music")
    assert get_song(conn, s.id).audio_path is None


def test_missing_music_dir_is_fine(conn, tmp_path):
    stats = scan_music(conn, tmp_path / "nope")
    assert (stats.seen, stats.matched) == (0, 0)


def test_extensions():
    assert {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav"} <= set(AUDIO_EXTENSIONS)
