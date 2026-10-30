"""Lyrics that come after an auto sheet was made go on it at the next render: no model, no audio."""

from __future__ import annotations

from datetime import UTC, datetime

from conftest import add_song
from helpers.rendered import fake_chordpro

from caracole.autochords import ChordSegment, build_sheet
from caracole.autochords.merge import with_plain_lyrics
from caracole.autochords.run import _keep, _skip_reason
from caracole.autochords.sheet_lyrics import lyrics_onto_sheets, sheets_wanting_lyrics
from caracole.library import keep_file, kept_files, song_dir
from caracole.lyrics import Lyrics
from caracole.overrides import Overrides
from caracole.render import render_all
from caracole.songs import AUTO_SHEET, HUMAN_SHEET, get_song, update_song
from caracole.versions import get_version, upsert_version

STAMP = "2026-10-30T13:42:00Z"
NOW = datetime(2026, 10, 30, 14, 23, tzinfo=UTC)
SEGMENTS = [ChordSegment(0.0, 4.0, "C"), ChordSegment(4.0, 8.0, "G")]
BEATS = [float(n) for n in range(9)]
WORDS = "Une ligne inventée\n\nUne autre ligne"


def chords_only(conn, cfg, *, artist="pomme", title="mononoke", used="none", plain=None):
    """A song with the auto sheet auto-chords made of it, as run.py keeps one: over no lyrics by default."""
    song = add_song(conn, artist, title)
    update_song(conn, song.id, audio_path="/gone/audio.m4a", audio_mtime=1.0)
    song = get_song(conn, song.id)
    text = build_sheet(SEGMENTS, title=title, artist=artist, plain=plain, beats=BEATS,
                       source="Audio from YouTube: a clip (a channel)")
    _keep(conn, cfg, song, text, used, "C", STAMP)
    return get_song(conn, song.id)


def found(conn, song, *, plain=WORDS, synced=None):
    update_song(conn, song.id, lyrics_status="found", lyrics_json=Lyrics(
        plain=plain, synced=synced, instrumental=False, duration=None, lrclib_id=None, provider="azlyrics",
        url="https://www.azlyrics.com/lyrics/pomme/mononoke.html").to_json())
    return get_song(conn, song.id)


def sheet(cfg, song):
    return (song_dir(cfg.library_dir, song) / AUTO_SHEET).read_text(encoding="utf-8")


def raw(conn, song):
    auto = next(f for f in kept_files(conn, song.id) if f.name == AUTO_SHEET)
    return get_version(conn, auto.version_id).raw


def test_the_lyrics_go_on_a_sheet_as_auto_chords_would_have_put_them():
    credit = "Audio from YouTube: a clip (a channel)"
    chart = build_sheet(SEGMENTS, title="mononoke", artist="pomme", beats=BEATS, source=credit)
    assert "[Chords]" in chart
    assert with_plain_lyrics(chart, WORDS) == build_sheet(SEGMENTS, title="mononoke", artist="pomme", beats=BEATS,
                                                          source=credit, plain=WORDS)


def test_a_sheet_of_no_chords_takes_them_the_same_way():
    assert with_plain_lyrics(build_sheet([], title="t", artist="a"), WORDS) == build_sheet(
        [], title="t", artist="a", plain=WORDS)


def test_a_sheet_made_with_no_lyrics_takes_them_with_no_model_and_no_audio(conn, cfg):
    song = found(conn, chords_only(conn, cfg))
    assert [s.id for s in lyrics_onto_sheets(conn, cfg)] == [song.id]
    text = sheet(cfg, song)
    assert "[Chords]" in text and text.endswith("[Lyrics]\nUne ligne inventée\n\nUne autre ligne\n")
    assert "Audio from YouTube: a clip (a channel)" in text
    assert raw(conn, song)["lyrics"] == "plain"


def test_what_else_the_version_says_stays(conn, cfg):
    song = found(conn, chords_only(conn, cfg))
    before = raw(conn, song)
    lyrics_onto_sheets(conn, cfg)
    assert raw(conn, song) == {**before, "lyrics": "plain"}


def test_the_sheet_takes_them_once(conn, cfg):
    song = found(conn, chords_only(conn, cfg))
    lyrics_onto_sheets(conn, cfg)
    text = sheet(cfg, song)
    assert lyrics_onto_sheets(conn, cfg) == []
    assert sheet(cfg, song) == text


def test_auto_chords_has_nothing_left_to_do_for_plain_lyrics(conn, cfg, tmp_path):
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"x")
    song = found(conn, chords_only(conn, cfg))
    update_song(conn, song.id, audio_path=str(audio), autochords_mtime=1.0)
    assert _skip_reason(conn, get_song(conn, song.id), Overrides()) is None  # due, by the models, until now
    lyrics_onto_sheets(conn, cfg)
    assert _skip_reason(conn, get_song(conn, song.id), Overrides()) == "up to date"


def test_timed_lyrics_go_on_at_once_then_stay_due_for_the_models(conn, cfg, tmp_path):
    # Plain words now; the chords over them take the models, which the nightly unit still runs.
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"x")
    song = found(conn, chords_only(conn, cfg), plain="Une ligne", synced="[00:01.00]Une ligne")
    update_song(conn, song.id, audio_path=str(audio), autochords_mtime=1.0)
    lyrics_onto_sheets(conn, cfg)
    assert sheet(cfg, song).endswith("[Lyrics]\nUne ligne\n")
    assert _skip_reason(conn, get_song(conn, song.id), Overrides()) is None


def test_a_song_with_no_lyrics_or_an_instrumental_is_left_alone(conn, cfg):
    none = chords_only(conn, cfg)
    music = chords_only(conn, cfg, title="Chapelle")
    update_song(conn, music.id, lyrics_status="instrumental", lyrics_json=Lyrics(
        plain="", synced=None, instrumental=True, duration=None, lrclib_id=1).to_json())
    assert sheets_wanting_lyrics(conn, Overrides()) == []
    assert "[Lyrics]" not in sheet(cfg, none)


def test_a_sheet_made_over_lyrics_is_left_alone(conn, cfg):
    song = found(conn, chords_only(conn, cfg, used="plain", plain="Autre chose"))
    assert lyrics_onto_sheets(conn, cfg) == []
    assert sheet(cfg, song).count("[Lyrics]") == 1


def test_a_song_with_a_human_sheet_is_left_alone(conn, cfg):
    song = found(conn, chords_only(conn, cfg))
    version = upsert_version(conn, provider="ug", tab_id="1", song_id=song.id, slot="sheet", kind="chords", rating=5,
                             votes=1, version=1, label=None, url="https://x", raw={}, now=STAMP)
    keep_file(conn, cfg.library_dir, song=song, version_id=version, name=HUMAN_SHEET, data=b"[Verse]\n", rank=1)
    assert sheets_wanting_lyrics(conn, Overrides()) == []


def test_an_ignored_song_is_left_alone(conn, cfg):
    song = found(conn, chords_only(conn, cfg))
    overrides = Overrides(ignore=frozenset({song.key}))
    assert sheets_wanting_lyrics(conn, overrides) == []
    update_song(conn, song.id, status="ignored")
    assert sheets_wanting_lyrics(conn, Overrides()) == []


def test_only_the_songs_asked_for(conn, cfg):
    song = found(conn, chords_only(conn, cfg))
    other = found(conn, chords_only(conn, cfg, title="Grandiose"))
    assert [s.id for s in lyrics_onto_sheets(conn, cfg, only={other.id})] == [other.id]
    assert "[Lyrics]" not in sheet(cfg, song)


def test_lyrics_stored_that_cant_be_read_stop_no_render(conn, cfg):
    song = found(conn, chords_only(conn, cfg))
    update_song(conn, song.id, lyrics_json="not json")
    other = found(conn, chords_only(conn, cfg, title="Grandiose"))
    assert [s.id for s in sheets_wanting_lyrics(conn, Overrides())] == [other.id]


def test_a_sheet_gone_from_the_folder_is_left_for_the_models(conn, cfg):
    song = found(conn, chords_only(conn, cfg))
    (song_dir(cfg.library_dir, song) / AUTO_SHEET).unlink()
    assert lyrics_onto_sheets(conn, cfg) == []
    assert raw(conn, song)["lyrics"] == "none"


def test_a_file_that_cant_be_kept_stops_nothing_else(conn, cfg, monkeypatch):
    song = found(conn, chords_only(conn, cfg))
    other = found(conn, chords_only(conn, cfg, title="Grandiose"))
    from caracole.autochords import sheet_lyrics

    real = sheet_lyrics.keep_file

    def full_disk(conn, library_dir, *, song, **kept):
        if song.title == "Grandiose":
            raise OSError("no space left on device")
        return real(conn, library_dir, song=song, **kept)

    monkeypatch.setattr(sheet_lyrics, "keep_file", full_disk)
    assert [s.id for s in lyrics_onto_sheets(conn, cfg)] == [song.id]
    assert raw(conn, other)["lyrics"] == "none"


def test_the_render_puts_them_on_the_page_and_says_so(conn, cfg):
    song = chords_only(conn, cfg)
    render_all(conn, cfg, Overrides(), runner=fake_chordpro, now=NOW)
    page = song_dir(cfg.library_dir, song) / "sheet (auto).html"
    assert "Une ligne inventée" not in page.read_text(encoding="utf-8")
    found(conn, song)
    stats = render_all(conn, cfg, Overrides(), runner=fake_chordpro, now=NOW)
    assert stats.given == 1 and stats.rendered == 1
    assert "Une ligne inventée" in page.read_text(encoding="utf-8")
    assert render_all(conn, cfg, Overrides(), runner=fake_chordpro, now=NOW).given == 0


def test_a_render_of_one_song_gives_that_song_alone_its_lyrics(conn, cfg):
    song = found(conn, chords_only(conn, cfg))
    other = found(conn, chords_only(conn, cfg, title="Grandiose"))
    render_all(conn, cfg, Overrides(), runner=fake_chordpro, now=NOW, song_ids={other.id})
    assert "[Lyrics]" in sheet(cfg, other) and "[Lyrics]" not in sheet(cfg, song)
