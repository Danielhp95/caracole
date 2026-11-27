"""Lyrics that come after an auto sheet was made go on it at the next render: no model, no audio."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from conftest import add_song
from helpers.rendered import fake_chordpro

from caracole.autochords import ChordSegment, build_sheet
from caracole.autochords.merge import with_plain_lyrics
from caracole.autochords.run import _keep, _skip_reason
from caracole.autochords.sheet_lyrics import lyrics_onto_sheets, relay_onto_sheets, sheets_wanting_lyrics
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
    assert raw(conn, song) == {**before, "lyrics": "plain", "lyrics_key": raw(conn, song)["lyrics_key"]}


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


def test_the_words_key_holds_through_their_spacing_and_is_another_for_other_words():
    from caracole.autochords.sheet_lyrics import lyrics_key

    key = lyrics_key("Une ligne\n\nUne autre")
    assert len(key) == 16
    assert lyrics_key("\n  Une ligne \r\n\n\n\tUne autre\n\n") == key
    assert {lyrics_key("Une ligne\nUne autre"), lyrics_key("une ligne\n\nUne autre"),
            lyrics_key("Une ligne,\n\nUne autre")}.isdisjoint({key})


def test_lyrics_put_on_a_chart_keep_their_key(conn, cfg, tmp_path):
    # Then other words make the sheet due for the models, as for a sheet they made over lyrics.
    from caracole.autochords.sheet import song_lyrics_key as _lyrics_key

    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"x")
    song = found(conn, chords_only(conn, cfg))
    update_song(conn, song.id, audio_path=str(audio), autochords_mtime=1.0)
    lyrics_onto_sheets(conn, cfg)
    song = get_song(conn, song.id)
    assert raw(conn, song)["lyrics_key"] == _lyrics_key(song) and _lyrics_key(song) is not None
    assert _skip_reason(conn, song, Overrides()) == "up to date"
    song = found(conn, song, plain="Des mots tout autres")
    assert _skip_reason(conn, song, Overrides()) is None


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


# --- a sheet that keeps what was heard: re-laid over other words, no model (E13) ------------------------------------

def _heard_sheet(conn, cfg, tmp_path, kind, *, title="River Road"):
    """A song with the auto sheet the models make of it as the words of ``kind`` (test_autochords_sheet.py's CASES)
    stand, keeping what was heard (``heard``) and who made it."""
    from test_autochords_run import with_audio
    from test_autochords_sheet import CASES, Recognizer, _bulk

    seconds, fields, segments, beats, before = CASES[kind]
    song = with_audio(conn, tmp_path, add_song(conn, "Nobody", title), seconds=seconds, **fields)
    if before is not None:
        before(conn, song)
    _bulk(conn, cfg, get_song(conn, song.id), Recognizer(segments), beats)
    return get_song(conn, song.id)


def _words(conn, song, kind):
    """The song's words become those of ``kind``: its lyrics columns, and what its kv notes of its audio."""
    from test_autochords_sheet import CASES

    fields, before = CASES[kind][1], CASES[kind][4]
    update_song(conn, song.id, **{"lyrics_status": "missing", "lyrics_json": None, **fields})
    if before is not None:
        before(conn, get_song(conn, song.id))
    return get_song(conn, song.id)


def _dropped(conn, song):
    from caracole.autochords.transcript import drop_transcript

    drop_transcript(conn, song, "2026-11-26T09:00:00Z")
    return get_song(conn, song.id)


class Refusing:
    """A recognizer, and beats, that fail the test if a model is asked to hear anything."""

    name = "refusing"

    def recognize(self, path):
        raise AssertionError(f"a model was asked to hear {path}")

    def __call__(self, path):
        raise AssertionError(f"a model was asked for the beats of {path}")


def test_lyrics_that_come_later_re_lay_the_sheet_with_no_model(conn, cfg, tmp_path):
    from caracole.autochords.run import RELAID, autochords_pending

    song = _heard_sheet(conn, cfg, tmp_path, "no lyrics")
    assert "[Lyrics]" not in sheet(cfg, song)
    song = _words(conn, song, "synced")
    assert _skip_reason(conn, song, Overrides()) == RELAID  # never the models' for its words
    stats = render_all(conn, cfg, Overrides(), runner=fake_chordpro, now=NOW)
    assert stats.given == 1 and stats.rendered >= 1
    text = sheet(cfg, song)
    assert "[ch]" in text and "Walking down the river road" in text and "[Lyrics]" not in text  # each chord on its word
    assert raw(conn, song)["lyrics"] == "synced"
    assert _skip_reason(conn, get_song(conn, song.id), Overrides()) == "up to date"
    assert render_all(conn, cfg, Overrides(), runner=fake_chordpro, now=NOW).given == 0  # once
    stats = autochords_pending(conn, cfg, recognizer=Refusing(), beats_fn=Refusing(), now=NOW)
    assert (stats.generated, stats.relaid, stats.skipped, stats.failed, stats.errors) == (0, 0, 1, 0, [])
    # Other words before any render: the nightly pass lays it out again itself, still with no model.
    _words(conn, song, "word timed")
    stats = autochords_pending(conn, cfg, recognizer=Refusing(), beats_fn=Refusing(), now=NOW)
    assert (stats.generated, stats.relaid, stats.failed, stats.errors) == (0, 1, 0, [])
    assert "Walking" in sheet(cfg, song) and raw(conn, song)["lyrics"] == "synced"
    assert "Singing" in (song_dir(cfg.library_dir, song) / "sheet (auto).html").read_text(
        encoding="utf-8")


# (the words the sheet was made over, the words now, whether the words alone make it due): every change of words
# between test_autochords_sheet.py's kinds, over the same audio, chords and beats.
CHANGES = [
    ("no lyrics", "plain", True),
    ("no lyrics", "synced", True),
    ("no lyrics", "word timed", True),
    ("plain", "synced", True),
    ("synced", "word timed", True),
    ("plain", "chinese", True),
    ("transcript", "plain", True),
    ("transcript", "synced", True),
    ("transcript", "instrumental", True),
    ("transcript", _dropped, True),
    ("no lyrics", "transcript", True),
    ("no lyrics", "nothing sung", True),
    ("no lyrics", "said not sung", True),
    ("plain", "instrumental", True),
    ("synced", "no lyrics", True),  # a pick taken back: the chords alone again
    ("synced", "plain", False),  # the same words, untimed: up to date, as before
]


def _name(change):
    return f"{change[0]}->{getattr(change[1], '__name__', change[1]).strip('_')}"


@pytest.mark.parametrize("before,after,due", CHANGES, ids=[_name(c) for c in CHANGES])
def test_a_re_lay_is_the_sheet_the_models_would_have_made(conn, cfg, tmp_path, before, after, due):
    from caracole.autochords.sheet import raw_of, relay
    from caracole.autochords.sheet_lyrics import noted_of, relay_reason
    from test_autochords_sheet import CASES, Recognizer, _bulk

    song = _heard_sheet(conn, cfg, tmp_path, before)
    laid = raw(conn, song)
    song = after(conn, song) if callable(after) else _words(conn, song, after)
    assert (relay_reason(conn, song, laid) is not None) == due
    made = relay(song, laid, noted_of(conn, song, laid))
    relaid = json.dumps(raw_of(song, made), ensure_ascii=False)
    # What the models make of the same audio over the same words, heard afresh.
    update_song(conn, song.id, autochords_mtime=None)
    _, _, segments, beats, _ = CASES[before]
    _bulk(conn, cfg, get_song(conn, song.id), Recognizer(segments), beats)
    assert made.text == sheet(cfg, song)
    assert relaid == json.dumps(raw(conn, song), ensure_ascii=False)  # every member, in its place: the same bytes


def test_a_re_lay_over_the_shift_lrclibs_timing_needs_is_the_models_sheet_too(conn, cfg, tmp_path):
    from caracole.autochords.sheet import raw_of, relay
    from test_autochords_sheet import CASES, Recognizer, _bulk

    seconds, fields, segments, beats, _ = CASES["shifted"]
    from test_autochords_run import with_audio

    song = with_audio(conn, tmp_path, add_song(conn, "Nobody", "River Road"), seconds=seconds)
    _bulk(conn, cfg, song, Recognizer(segments), beats)
    laid = raw(conn, song)
    update_song(conn, song.id, **fields)
    song = get_song(conn, song.id)
    made = relay(song, laid)
    assert made.shift is not None
    relaid = raw_of(song, made)
    update_song(conn, song.id, autochords_mtime=None)
    _bulk(conn, cfg, get_song(conn, song.id), Recognizer(segments), beats)
    assert (made.text, relaid) == (sheet(cfg, song), raw(conn, song))


def test_a_re_lay_of_a_sheet_from_youtube_keeps_its_video_and_its_line(conn, cfg, tmp_path):
    from caracole.autochords.sheet import raw_of, relay
    from test_autochords_sheet import CASES, VIDEO, Recognizer, _bulk, _youtube
    from test_autochords_run import with_audio

    seconds, fields, segments, beats, _ = CASES["youtube, shifted"]
    song = with_audio(conn, tmp_path, add_song(conn, "Nobody", "River Road"), seconds=seconds)
    _youtube(conn, song)
    _bulk(conn, cfg, song, Recognizer(segments), beats)
    laid = raw(conn, song)
    assert laid["youtube"]["id"] == VIDEO["id"]
    update_song(conn, song.id, **fields)
    song = get_song(conn, song.id)
    made = relay(song, laid)
    relaid = raw_of(song, made)
    update_song(conn, song.id, autochords_mtime=None)
    _bulk(conn, cfg, get_song(conn, song.id), Recognizer(segments), beats)
    assert "Audio from YouTube: Longships (Nobody)" in made.text
    assert (made.text, relaid) == (sheet(cfg, song), raw(conn, song))


def test_a_re_lay_of_wider_lines_counts_display_columns(conn, cfg, tmp_path):
    from caracole.autochords.sheet import raw_of, relay
    from caracole.versions import set_raw

    song = _heard_sheet(conn, cfg, tmp_path, "chinese")
    made_now = sheet(cfg, song), raw(conn, song)
    old = {k: v for k, v in raw(conn, song).items() if k != "columns"}  # as an older layout kept it
    auto = next(f for f in kept_files(conn, song.id) if f.name == AUTO_SHEET)
    set_raw(conn, auto.version_id, old)
    assert relay_onto_sheets(conn, cfg) and (sheet(cfg, song), raw(conn, song)) == made_now
    assert raw_of(song, relay(song, old))["columns"] == "display"


def test_a_re_lay_keeps_who_made_it_and_from_what(conn, cfg, tmp_path):
    song = _heard_sheet(conn, cfg, tmp_path, "no lyrics")
    auto = next(f for f in kept_files(conn, song.id) if f.name == AUTO_SHEET)
    version = get_version(conn, auto.version_id)
    # As another caracole (the phone) made it, from its own file: a re-lay here never makes this side its maker.
    theirs = {**version.raw, "audio": "/data/user/0/phone/files/audio/7-0123456789abcdef.mp3", "made_on": "phone",
              "made_by": "0f1e2d3c4b5a6978",
              "models": {"chords": "btc_large_voca@aa", "beats": "beat_this final0 fp16@bb"},
              "runtime": "onnxruntime 1.32.0", "audio_name": "river road.mp3", "audio_sha16": "0123456789abcdef"}
    from caracole.versions import set_raw

    set_raw(conn, version.id, theirs)
    conn.execute("UPDATE versions SET tab_id = '42', url = 'file:///data/user/0/phone/x.mp3' WHERE id = ?",
                 (version.id,))
    _words(conn, song, "plain")
    assert [s.id for s in relay_onto_sheets(conn, cfg)] == [song.id]
    now = get_version(conn, version.id)
    kept = ("audio", "made_on", "made_by", "models", "runtime", "audio_name", "audio_sha16")
    assert {m: now.raw[m] for m in kept} == {m: theirs[m] for m in kept}
    assert (now.tab_id, now.url, now.fetched_at) == ("42", "file:///data/user/0/phone/x.mp3", version.fetched_at)
    assert now.raw["lyrics"] == "plain" and now.raw["heard"] == theirs["heard"]
    assert "Walking down the river road" in sheet(cfg, song)


def test_two_caracoles_re_lay_the_same_sheet_over_the_same_words_alike(conn, cfg, tmp_path, monkeypatch):
    # The design's "one unit": a re-lay is a pure function of what was heard, the song's words and the kept members.
    import time

    from caracole import db
    from caracole.config import load_config
    from caracole.db import kv_set
    from caracole.versions import upsert_version as upsert

    from conftest import migrated_database

    song = _heard_sheet(conn, cfg, tmp_path, "no lyrics")
    auto = next(f for f in kept_files(conn, song.id) if f.name == AUTO_SHEET)
    laid, chart = get_version(conn, auto.version_id).raw, sheet(cfg, song)

    def side(name, sync_id, clock):
        folder = tmp_path / name
        (folder / "state").mkdir(parents=True)
        (folder / "state" / "caracole.sqlite").write_bytes(migrated_database())
        there = db.connect(folder / "state" / "caracole.sqlite")
        here = load_config(None, env={"HOME": str(folder / "home"), "STATE_DIRECTORY": str(folder / "state"),
                                      "CACHE_DIRECTORY": str(folder / "cache")})
        kv_set(there, "sync:id", sync_id)
        for _ in range(int(clock) % 3):  # another song id here
            add_song(there, "Someone", f"Else {_}")
        other = add_song(there, "Nobody", "River Road")
        update_song(there, other.id, audio_path=None, audio_mtime=None)  # the sheet is all this side has of it
        other = get_song(there, other.id)
        version = upsert(there, provider="auto", tab_id="17", song_id=other.id, slot="sheet", kind="auto", rating=0,
                         votes=0, version=1, label=None, url="file:///elsewhere.wav", raw=laid,
                         now=f"2026-11-2{name[-1]}T00:00:00Z")
        keep_file(there, here.library_dir, song=other, version_id=version, name=AUTO_SHEET,
                  data=chart.encode("utf-8"), rank=1)
        _words(there, other, "word timed")
        monkeypatch.setattr(time, "time", lambda: clock)
        relay_onto_sheets(there, here)
        done = (sheet(here, other), there.execute("SELECT raw FROM versions WHERE id = ?", (version,)).fetchone()[0])
        there.close()
        return done

    one = side("side1", "aaaaaaaaaaaaaaaa", 1_800_000_000.0)
    two = side("side2", "bbbbbbbbbbbbbbbb", 1_900_000_001.0)
    assert one == two
    assert '"made_by"' in one[1] and "Walking" in one[0]


@pytest.mark.slow
def test_a_render_s_re_lay_loads_no_model_and_no_audio_reader(tmp_path):
    # render.py runs in a caracole without auto-chords: its first step lays sheets out again with what it imports.
    import os
    import subprocess
    import sys
    from pathlib import Path

    from conftest import subprocess_pythonpath

    code = ("import sys\nfrom caracole import db\nfrom caracole.config import load_config\n"
            "import caracole.render, caracole.lyrics, caracole.autochords.transcript\n"
            "from caracole.autochords.sheet_lyrics import relay_onto_sheets\n"
            f"cfg = load_config(None, env={{'HOME': {str(tmp_path / 'home')!r}, 'STATE_DIRECTORY': "
            f"{str(tmp_path / 'state')!r}, 'CACHE_DIRECTORY': {str(tmp_path / 'cache')!r}}})\n"
            "cfg.db_path.parent.mkdir(parents=True, exist_ok=True)\n"
            "relay_onto_sheets(db.connect(cfg.db_path), cfg)\n"
            "heavy = {'mutagen', 'torch', 'librosa', 'numpy', 'beat_this', 'soundfile', 'whisper', 'httpx',\n"
            "         'caracole.autochords.btc', 'caracole.autochords.beats', 'caracole.autochords.audio',\n"
            "         'caracole.autochords.run'}\n"
            "print(sorted(heavy & set(sys.modules)))\n")
    env = {**os.environ, "PYTHONPATH": subprocess_pythonpath(Path(__file__).parents[1] / "src")}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)
    assert out.stdout.strip() == "[]"


def test_a_heard_record_that_cant_be_read_is_neither_re_laid_nor_made_due_and_said_once(conn, cfg, tmp_path, caplog):
    import logging

    from caracole.autochords import sheet_lyrics
    from caracole.versions import set_raw

    song = _heard_sheet(conn, cfg, tmp_path, "no lyrics")
    auto = next(f for f in kept_files(conn, song.id) if f.name == AUTO_SHEET)
    newer = {**raw(conn, song), "heard": {**raw(conn, song)["heard"], "contract": 2}}  # a newer caracole's
    set_raw(conn, auto.version_id, newer)
    chart = sheet(cfg, song)
    assert render_all(conn, cfg, Overrides(), runner=fake_chordpro, now=NOW).given == 0  # nothing due: not a word
    assert "can't be read" not in caplog.text
    song = _words(conn, song, "plain")
    sheet_lyrics._TOLD.clear()
    with caplog.at_level(logging.WARNING, logger="caracole.autochords.sheet_lyrics"):
        for _ in range(3):
            assert render_all(conn, cfg, Overrides(), runner=fake_chordpro, now=NOW).given == 0
    said = [r for r in caplog.records if "what was heard can't be read" in r.getMessage()]
    assert len(said) == 1 and "contract 2" in said[0].getMessage() and song.display in said[0].getMessage()
    assert _skip_reason(conn, get_song(conn, song.id), Overrides()) == "up to date"  # nor the models'
    assert (sheet(cfg, song), raw(conn, song)) == (chart, newer)


# --- which audio a sheet was heard from (fix round 1) ---------------------------------------------------------------

def test_new_audio_and_new_words_re_lay_nothing_the_models_hear_the_new_audio(conn, cfg, tmp_path):
    from caracole.autochords.run import autochords_pending
    from test_autochords_run import make_wav
    from test_autochords_sheet import Recognizer

    song = _heard_sheet(conn, cfg, tmp_path, "no lyrics")
    chart, laid = sheet(cfg, song), raw(conn, song)
    other = make_wav(tmp_path / "music" / "other.wav", 10.0)
    update_song(conn, song.id, audio_path=str(other), audio_mtime=os.stat(other).st_mtime + 7.0)
    song = _words(conn, song, "synced")
    assert render_all(conn, cfg, Overrides(), runner=fake_chordpro, now=NOW).given == 0
    assert (sheet(cfg, song), raw(conn, song)) == (chart, laid)
    assert _skip_reason(conn, get_song(conn, song.id), Overrides()) is None  # the models' turn: other audio
    recognizer = Recognizer([(0.0, 5.0, "D"), (5.0, 10.0, "A")])
    stats = autochords_pending(conn, cfg, recognizer=recognizer, beats_fn=lambda p: (BEATS, BEATS[::4]), now=NOW)
    assert (stats.generated, stats.relaid) == (1, 0)
    assert raw(conn, song)["audio"] == str(other) and "Walking" in sheet(cfg, song)


def test_a_sheet_taken_with_no_audio_here_is_re_laid_when_its_lyrics_arrive(conn, cfg, tmp_path):
    # A sheet another caracole made, on a side that holds no file of the song: the sheet is all it has of it.
    song = _heard_sheet(conn, cfg, tmp_path, "no lyrics")
    update_song(conn, song.id, audio_path=None, audio_mtime=None, autochords_mtime=None)
    song = _words(conn, song, "synced")
    assert [s.id for s in relay_onto_sheets(conn, cfg)] == [song.id]
    assert "Walking" in sheet(cfg, song) and raw(conn, song)["lyrics"] == "synced"


def test_a_file_moved_with_its_mtime_kept_then_transcribed_gets_its_words(conn, cfg, tmp_path):
    # Syncthing or a hand moves the file; relinked under its new path with the same mtime, it is the same audio.
    from test_autochords_sheet import _transcript

    song = _heard_sheet(conn, cfg, tmp_path, "no lyrics")
    moved = Path(song.audio_path).with_name("moved.wav")
    Path(song.audio_path).rename(moved)
    update_song(conn, song.id, audio_path=str(moved))
    song = get_song(conn, song.id)
    assert song.autochords_mtime == song.audio_mtime
    _transcript(conn, song)  # transcribed from its new path
    assert [s.id for s in relay_onto_sheets(conn, cfg)] == [song.id]
    assert raw(conn, song)["lyrics_source"] == "transcript" and "la la la" in sheet(cfg, song)
    assert raw(conn, song)["audio"] != str(moved)  # who heard it and from what stays as it was


def test_a_sheet_over_a_transcript_whose_file_moved_goes_back_to_its_chords_as_before(conn, cfg, tmp_path):
    # Its transcript names the old path, so it is no transcript of the song's audio now (transcript.py
    # ``transcript_of``): as before what was heard was kept (then by the models), the sheet goes back to its chords,
    # and its transcription isn't "already" done any more.
    from caracole.autochords.transcript import ALREADY_TRANSCRIBED, transcript_of, why_not_offered

    song = _heard_sheet(conn, cfg, tmp_path, "transcript")
    moved = Path(song.audio_path).with_name("moved.wav")
    Path(song.audio_path).rename(moved)
    update_song(conn, song.id, audio_path=str(moved))
    song = get_song(conn, song.id)
    assert transcript_of(conn, song) is None
    assert [s.id for s in relay_onto_sheets(conn, cfg)] == [song.id]
    assert raw(conn, song)["lyrics"] == "none" and "la la la" not in sheet(cfg, song)
    assert why_not_offered(conn, cfg, get_song(conn, song.id), Overrides()) != ALREADY_TRANSCRIBED


def test_a_bug_laying_a_sheet_out_is_one_of_the_nightly_runs_errors(conn, cfg, tmp_path, monkeypatch):
    from caracole.autochords import sheet_lyrics
    from caracole.autochords.run import autochords_pending

    song = _heard_sheet(conn, cfg, tmp_path, "no lyrics")
    _words(conn, song, "plain")

    def broken(*args, **kwargs):
        raise KeyError("a bug")

    monkeypatch.setattr(sheet_lyrics, "relay", broken)
    stats = autochords_pending(conn, cfg, recognizer=Refusing(), beats_fn=Refusing(), now=NOW)
    assert (stats.relaid, stats.failed) == (0, 1) and stats.errors == ["Nobody - River Road: KeyError: 'a bug'"]


def test_info_json_that_cant_be_written_after_a_re_lay_leaves_it_re_laid(conn, cfg, tmp_path, monkeypatch, caplog):
    from caracole.autochords import sheet_lyrics

    song = _heard_sheet(conn, cfg, tmp_path, "no lyrics")
    _words(conn, song, "plain")

    def full(*args, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(sheet_lyrics, "write_info", full)
    assert [s.id for s in relay_onto_sheets(conn, cfg)] == [song.id]
    assert raw(conn, song)["lyrics"] == "plain"
    assert "its info.json couldn't be written: no space left on device" in caplog.text


def test_a_render_of_one_song_reads_only_its_record(conn, cfg, tmp_path):
    from caracole.autochords.sheet_lyrics import _relay_candidates

    one = _heard_sheet(conn, cfg, tmp_path, "no lyrics")
    two = _heard_sheet(conn, cfg, tmp_path, "no lyrics", title="Hill Song")
    asked = []
    conn.set_trace_callback(asked.append)
    assert _relay_candidates(conn, {two.id}) == [two.id]
    conn.set_trace_callback(None)
    assert _relay_candidates(conn, None) == [one.id, two.id] and _relay_candidates(conn, set()) == []
    assert any("f.song_id IN (" in q and str(two.id) in q for q in asked)


def test_a_bug_writing_info_json_after_a_re_lay_stops_no_other_song(conn, cfg, tmp_path, monkeypatch, caplog):
    # info.json raising anything but OSError (a bug) is logged with its traceback, one of the errors, and the other
    # songs are re-laid all the same: the sheet itself was re-laid.
    from caracole.autochords import sheet_lyrics

    one = _heard_sheet(conn, cfg, tmp_path, "no lyrics")
    two = _heard_sheet(conn, cfg, tmp_path, "no lyrics", title="Hill Song")
    one, two = _words(conn, one, "plain"), _words(conn, two, "plain")
    written = sheet_lyrics.write_info

    def broken(conn, library_dir, song):
        if song.id == one.id:
            raise KeyError("a bug")
        return written(conn, library_dir, song)

    monkeypatch.setattr(sheet_lyrics, "write_info", broken)
    errors: list[str] = []
    assert [s.id for s in relay_onto_sheets(conn, cfg, errors=errors)] == [one.id, two.id]
    assert raw(conn, one)["lyrics"] == "plain" and raw(conn, two)["lyrics"] == "plain"
    assert errors == ["Nobody - River Road: info.json: KeyError: 'a bug'"]
    assert "Traceback" in caplog.text and "KeyError: 'a bug'" in caplog.text
