import os
import wave
from pathlib import Path

from mutagen.id3 import TALB, TIT2, TPE1
from mutagen.wave import WAVE

from caracole.lyrics import Lyrics
from caracole.music import AUDIO_EXTENSIONS, read_audio, scan_music
from caracole.songs import get_song, update_song

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
    make_wav(tmp_path / "music" / "b.wav", artist="Soda Stereo", title="Sobredosis de TV")
    scan_music(conn, tmp_path / "music")
    p.unlink()
    scan_music(conn, tmp_path / "music")
    assert get_song(conn, s.id).audio_path is None


def test_missing_music_dir_is_fine(conn, tmp_path):
    stats = scan_music(conn, tmp_path / "nope")
    assert (stats.seen, stats.matched) == (0, 0)


def test_extensions():
    assert {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav"} <= set(AUDIO_EXTENSIONS)


# --- a disk that isn't there tonight --------------------------------------------------------


def linked_purchase(conn, music: Path):
    s = add_song(conn, "Soda Stereo", "Persiana Americana", duration_ms=None)
    make_wav(music / "Soda Stereo" / "Soda Stereo - Persiana Americana.wav")
    scan_music(conn, music)
    path = get_song(conn, s.id).audio_path
    assert path
    return s, path


def test_a_missing_music_folder_unlinks_nothing(conn, tmp_path):
    music = tmp_path / "music"
    s, path = linked_purchase(conn, music)
    music.rename(tmp_path / "music-unmounted")
    assert scan_music(conn, music).seen == 0
    assert get_song(conn, s.id).audio_path == path


def test_an_empty_music_folder_unlinks_nothing(conn, tmp_path):
    # An unmounted disk leaves its mount point behind: an empty folder.
    music = tmp_path / "music"
    s, path = linked_purchase(conn, music)
    (music / "Soda Stereo").rename(tmp_path / "elsewhere")
    assert scan_music(conn, music).seen == 0
    assert get_song(conn, s.id).audio_path == path


# --- which file is the song's -----------------------------------------------------------------

BRICK = "Another Brick in the Wall, Pt. 2"


def test_the_exact_track_wins_over_an_album_sibling(conn, tmp_path):
    # A wanted.txt line gives no duration, and the files are named, not tagged. Pt. 1 sorts
    # first, and its title is 97% alike.
    s = add_song(conn, "Pink Floyd", BRICK, duration_ms=None)
    album = tmp_path / "music" / "Pink Floyd" / "The Wall"
    for part in (1, 2, 3):
        make_wav(album / f"Pink Floyd - Another Brick in the Wall, Pt. {part}.wav")
    stats = scan_music(conn, tmp_path / "music")
    assert Path(get_song(conn, s.id).audio_path).name == f"Pink Floyd - {BRICK}.wav"
    assert stats.matched == 1 and len(stats.unmatched) == 2


def test_the_exact_track_replaces_a_sibling_linked_before_it_arrived(conn, tmp_path):
    s = add_song(conn, "Pink Floyd", BRICK, duration_ms=None)
    music = tmp_path / "music"
    make_wav(music / "Pink Floyd - Another Brick in the Wall, Pt. 1.wav")
    scan_music(conn, music)  # nothing tells it from Pt. 2: no tags, no duration
    make_wav(music / f"Pink Floyd - {BRICK}.wav")
    scan_music(conn, music)
    assert Path(get_song(conn, s.id).audio_path).name == f"Pink Floyd - {BRICK}.wav"


def with_lrclib_duration(conn, song, seconds: float):
    record = {"id": 1, "trackName": song.title, "artistName": song.artist, "duration": seconds,
              "plainLyrics": "words to sing", "syncedLyrics": None}
    lyrics = Lyrics.from_record(record).to_json()
    update_song(conn, song.id, lyrics_status="found", lyrics_json=lyrics)


def test_lrclib_duration_guards_a_fuzzy_match_when_the_song_has_none(conn, tmp_path):
    s = add_song(conn, "Pink Floyd", BRICK, duration_ms=None)
    with_lrclib_duration(conn, s, 239.0)
    make_wav(tmp_path / "music" / "Pink Floyd - Another Brick in the Wall, Pt. 1.wav", 2.0)
    stats = scan_music(conn, tmp_path / "music")
    assert stats.matched == 0 and get_song(conn, s.id).audio_path is None


def test_lrclib_duration_does_not_overrule_the_exact_track(conn, tmp_path):
    # The file is the song by name; LRCLIB may have timed another edit of it.
    s = add_song(conn, "Radiohead", "Creep", duration_ms=None)
    with_lrclib_duration(conn, s, 238.0)
    make_wav(tmp_path / "music" / "Radiohead - Creep.wav", 2.0)
    scan_music(conn, tmp_path / "music")
    assert get_song(conn, s.id).audio_path is not None


def test_a_fuzzy_title_needs_a_clear_lead_over_the_next_title(conn, tmp_path):
    # Tagged "(Part 1)" and "(Part 2)": neither is "Pt. 2" by identity, and both come close.
    s = add_song(conn, "Pink Floyd", BRICK, duration_ms=None)
    music = tmp_path / "music"
    make_wav(music / "1.wav", artist="Pink Floyd", title="Another Brick in the Wall (Part 1)")
    make_wav(music / "2.wav", artist="Pink Floyd", title="Another Brick in the Wall (Part 2)")
    stats = scan_music(conn, music)
    assert get_song(conn, s.id).audio_path is None
    assert stats.matched == 0 and len(stats.unmatched) == 2


def test_a_file_as_close_to_two_songs_links_to_neither(conn, tmp_path):
    one = add_song(conn, "Pink Floyd", "Another Brick in the Wall, Pt. 1", duration_ms=None)
    two = add_song(conn, "Pink Floyd", BRICK, duration_ms=None)
    title = "Another Brick in the Wall (Part 2)"
    make_wav(tmp_path / "music" / "x.wav", artist="Pink Floyd", title=title)
    scan_music(conn, tmp_path / "music")
    assert get_song(conn, one.id).audio_path is None and get_song(conn, two.id).audio_path is None


def test_a_second_copy_of_the_track_leaves_the_link_alone(conn, tmp_path):
    s = add_song(conn, "Radiohead", "Creep", duration_ms=None)
    music = tmp_path / "music"
    first = make_wav(music / "b" / "Radiohead - Creep.wav")
    scan_music(conn, music)
    make_wav(music / "a" / "Radiohead - Creep.wav")  # sorts first
    stats = scan_music(conn, music)
    assert get_song(conn, s.id).audio_path == str(first)
    assert stats.matched == 2


def test_traditional_tags_link_to_the_simplified_song(conn, tmp_path):
    # 斑馬斑馬 and 斑马斑马 are the same title, compared as pinyin.
    s = add_song(conn, "宋冬野", "斑马斑马", duration_ms=None)
    make_wav(tmp_path / "music" / "banma.wav", artist="宋冬野", title="斑馬斑馬")
    scan_music(conn, tmp_path / "music")
    assert get_song(conn, s.id).audio_path.endswith("banma.wav")
