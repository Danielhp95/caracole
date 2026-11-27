"""autochords/sheet.py: the sheet half of auto-chords, laid out from what the models heard, with no model and no audio.

run.py hears a song's audio (``_hear``: BTC's chords, beat_this's beats, the length ``music.read_audio`` reads) into a
``sheet.Heard``; ``sheet.make_sheet`` lays the sheet out from that alone, and ``sheet.raw_of`` is its version's record.
The pinned digests are what the code made before the two halves were parted (E11): every case below, through the
bulk pass and a staged job's chords stage, keeps those bytes (the sheet, info.json, the version's row and raw, kv).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_autochords_run import BAND, RELEASE_LRC, TALK, TALKED_BEATS, lyrics_json, with_audio

from caracole.autochords import ChordSegment
from caracole.autochords.run import _from_youtube, autochords_pending
from caracole.autochords.sheet import Heard, heard_of, make_sheet, raw_of
from caracole.autochords.transcript import (
    Transcript,
    keep_transcript,
    note_heard_nothing,
    said_not_sung,
    transcript_of,
)
from caracole.autochords.transcript import heard_nothing as heard_nothing_of
from caracole.db import kv_set_json
from caracole.library import kept_files, song_dir
from caracole.music import read_audio
from caracole.peer_sync import own_id
from caracole.songs import get_song
from caracole.versions import get_version
from caracole.youtube_fetch import youtube_audio

from conftest import add_song, subprocess_pythonpath

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
STAMP = "2026-11-26T12:00:00Z"
BEATS = [i * 0.5 for i in range(41)]
FOUR = [(2.0 * k, 2.0 * (k + 1), ("C", "G", "Am", "F")[k % 4]) for k in range(5)]
SYNCED = "[00:00.50]Walking down the river road\n[00:05.20]Singing to the morning light\n"
WORDS = "[00:00.00]<00:00.00>Walking <00:00.60>down <00:01.20>the <00:03.00>river <00:03.60>road\n"
PLAIN = "Walking down the river road\nSinging to the morning light"
CHINESE = "[00:00.50]我们一起走在河边的路上\n[00:05.20]唱着早晨的歌\n"
VIDEO = {"id": "lzN7Thn3FV4", "title": "Longships", "channel": "Nobody", "duration": 46.0,
         "url": "https://www.youtube.com/watch?v=lzN7Thn3FV4"}


class Recognizer:
    def __init__(self, segments):
        self.segments = [ChordSegment(*s) for s in segments]

    def recognize(self, path):
        return list(self.segments)


def _transcript(conn, song):
    keep_transcript(conn, song, Transcript(lrc="[00:01.00]la la la\n[00:06.00]la la lo\n", audio=song.audio_path,
                                           audio_mtime=song.audio_mtime, model="whisper-large-v3", language="en",
                                           device="cpu", words_dropped=0, made_at="2026-11-25T10:00:00Z"))


def _silent(by):
    return lambda conn, song: note_heard_nothing(conn, song, "2026-11-25T10:00:00Z", why="sung 2.0 s", by=by)


def _youtube(conn, song):
    kv_set_json(conn, f"youtube:{song.id}", {"video": VIDEO, "source": "pasted", "audio": song.audio_path})


# name: (seconds of audio, song fields, chords heard, beats, what else the song has before its sheet is made)
CASES = {
    "no lyrics": (10.0, {"lyrics_status": "missing"}, FOUR, BEATS, None),
    "plain": (10.0, {"lyrics_status": "found", "lyrics_json": lyrics_json(plain=PLAIN)}, FOUR, BEATS, None),
    "synced": (10.0, {"lyrics_status": "found", "lyrics_json": lyrics_json(synced=SYNCED, duration=11.5)}, FOUR,
               BEATS, None),
    "word timed": (10.0, {"lyrics_status": "found", "lyrics_json": lyrics_json(synced=WORDS, duration=10.0)}, FOUR,
                   BEATS, None),
    "shifted": (TALK + 34.0, {"lyrics_status": "found", "lyrics_json": lyrics_json(synced=RELEASE_LRC, duration=34.0)},
                [(0.0, TALK, "N"), *BAND], TALKED_BEATS, None),
    "no clear shift": (TALK + 34.0, {"lyrics_status": "found",
                                     "lyrics_json": lyrics_json(synced=RELEASE_LRC, duration=34.0)},
                       [(2.0 * k, 2.0 * (k + 1), ("C", "G", "Am", "F")[k % 4]) for k in range(23)],
                       [0.5 * k for k in range(93)], None),
    "chinese": (10.0, {"lyrics_status": "found", "lyrics_json": lyrics_json(synced=CHINESE, duration=10.0)}, FOUR,
                BEATS, None),
    "instrumental": (10.0, {"lyrics_status": "instrumental", "lyrics_json": lyrics_json(instrumental=True)}, FOUR,
                     BEATS, None),
    "transcript": (10.0, {"lyrics_status": "missing"}, FOUR, BEATS, _transcript),
    "nothing sung": (10.0, {"lyrics_status": "missing"}, FOUR, BEATS, _silent("caracole")),
    "said not sung": (10.0, {"lyrics_status": "missing"}, FOUR, BEATS, _silent("you")),
    "youtube, shifted": (TALK + 34.0, {"lyrics_status": "found",
                                       "lyrics_json": lyrics_json(synced=RELEASE_LRC, duration=34.0)},
                         [(0.0, TALK, "N"), *BAND], TALKED_BEATS, _youtube),
}

# What each case made before the sheet half left run.py (E11), by the code of 74f6c3c8.
PINNED = {
    "no lyrics": "08df4723d065fc8a",
    "plain": "1c1c8765f3683d08",
    "synced": "af5b055801f6d4ec",
    "word timed": "c6088775211409a8",
    "shifted": "fc97538b3520d0d2",
    "no clear shift": "dab9d122f0e03609",
    "chinese": "ee2218c98cb2be5a",
    "instrumental": "1f8c8056d123de42",
    "transcript": "f5c05df959194788",
    "nothing sung": "db6612f8259a5138",
    "said not sung": "a2bd0f0e47fcfb00",
    "youtube, shifted": "5423c781521e2c7c",
}


def _bulk(conn, cfg, song, recognizer, beats):
    autochords_pending(conn, cfg, recognizer=recognizer, beats_fn=lambda path: (beats, beats[::4]), now=NOW)


def _staged(conn, cfg, song, recognizer, beats):
    from caracole.overrides import Overrides
    from caracole.staged import StagedResult, StagedRun

    job = StagedRun(cfg, SimpleNamespace(stage=lambda *a: None, readable=lambda *a: None), StagedResult(),
                    recognizer=recognizer, beats_fn=lambda path: (beats, beats[::4]), now=NOW, clock=lambda: 0.0)
    job.conn, job.overrides, job.song = conn, Overrides(), song
    job.result.states["chords"] = "running"
    state, _ = job._autochords_sheet()
    assert state == "done"


# What a sheet's raw keeps since E12 of what was heard and who made it from what: ``_made`` takes them out, so that
# the rest is pinned as it was before (PINNED), and each test says what they hold.
NEW_MEMBERS = ("heard", "made_on", "made_by", "models", "runtime", "audio_name", "audio_sha16")


def _made(conn, cfg, tmp_path, song, new: dict | None = None) -> str:
    """Everything the sheet's making left, as one text: the sheet, info.json, its version and the kv, with the test's
    own folder and the audio's mtime written as names; the raw's ``NEW_MEMBERS`` taken out of it, into ``new``."""
    song = get_song(conn, song.id)
    [kept] = kept_files(conn, song.id)
    version = get_version(conn, kept.version_id)
    taken = {member: version.raw.pop(member) for member in NEW_MEMBERS if member in version.raw}
    if new is not None:
        new.update(taken)
    folder = song_dir(cfg.library_dir, song)
    made = {
        "sheet": (folder / kept.name).read_text(encoding="utf-8"),
        "info": (folder / "info.json").read_text(encoding="utf-8"),
        "version": [version.provider, version.tab_id, version.slot, version.kind, version.url, version.raw],
        "song": [song.status, song.autochords_mtime == song.audio_mtime],
        "kv": [list(row) for row in conn.execute("SELECT key, value FROM kv WHERE key != 'sync:id' ORDER BY key")],
    }
    text = json.dumps(made, ensure_ascii=False, sort_keys=True)
    return text.replace(str(tmp_path), "<tmp>").replace(json.dumps(song.audio_mtime), "<mtime>")


@pytest.mark.parametrize("how", [_bulk, _staged], ids=["bulk", "staged"])
@pytest.mark.parametrize("case", list(CASES))
def test_the_sheet_half_makes_the_bytes_it_made_before_it_moved(conn, cfg, tmp_path, case, how):
    seconds, fields, segments, beats, before = CASES[case]
    song = with_audio(conn, tmp_path, add_song(conn, "Nobody", "River Road"), seconds=seconds, **fields)
    if before is not None:
        before(conn, song)
        song = get_song(conn, song.id)
    how(conn, cfg, song, Recognizer(segments), beats)
    new: dict = {}
    made = _made(conn, cfg, tmp_path, song, new)
    assert hashlib.sha256(made.encode("utf-8")).hexdigest()[:16] == PINNED.get(case), made
    # What E12 added, and nothing else: what was heard, and who made it from what (these fakes name no model).
    audio = Path(song.audio_path)
    assert new == {
        "heard": {"contract": 1, "duration": read_audio(audio).duration_s, "chords": [list(s) for s in segments],
                  "beats": beats, "downbeats": beats[::4]},
        "made_on": "computer",
        "made_by": own_id(conn),
        **({} if case.startswith("youtube") else {"audio_name": audio.name}),
        "audio_sha16": hashlib.sha256(audio.read_bytes()).hexdigest()[:16],
    }


# A file that names no length (``read_audio``'s ``duration_s`` None): its timed lyrics can't be fitted to it, so the
# plain ones, and the raw's lyrics members as the code wrote them before the halves were parted (74f6c3c8).
NO_LENGTH = "716401d00ab757d7"


@pytest.mark.parametrize("how", [_bulk, _staged], ids=["bulk", "staged"])
def test_audio_that_names_no_length_gets_its_plain_lyrics_as_before(conn, cfg, tmp_path, how, monkeypatch):
    import caracole.autochords.run as ac_run

    monkeypatch.setattr(ac_run, "read_audio", lambda path: SimpleNamespace(duration_s=None))
    song = with_audio(conn, tmp_path, add_song(conn, "Nobody", "River Road"), seconds=10.0, lyrics_status="found",
                      lyrics_json=lyrics_json(synced=SYNCED, duration=10.0))
    how(conn, cfg, song, Recognizer(FOUR), BEATS)
    [kept] = kept_files(conn, song.id)
    raw = get_version(conn, kept.version_id).raw
    assert (raw["lyrics"], "lyrics_shift" in raw, "synced_lyrics" in raw, "lyrics_key" in raw) == (
        "plain", False, True, True)
    new: dict = {}
    made = _made(conn, cfg, tmp_path, song, new)
    assert hashlib.sha256(made.encode("utf-8")).hexdigest()[:16] == NO_LENGTH, made
    assert new["heard"]["duration"] is None


def test_heard_is_what_make_sheet_took(conn, cfg, tmp_path, monkeypatch):
    import caracole.autochords.run as ac_run

    took = []

    def making(song, heard, **kw):
        took.append(heard)
        return make_sheet(song, heard, **kw)

    monkeypatch.setattr(ac_run, "make_sheet", making)
    seconds, fields, segments, beats, _ = CASES["shifted"]
    song = with_audio(conn, tmp_path, add_song(conn, "Nobody", "River Road"), seconds=seconds, **fields)
    _bulk(conn, cfg, song, Recognizer(segments), beats)
    [kept] = kept_files(conn, song.id)
    [heard] = took
    assert heard_of(get_version(conn, kept.version_id).raw) == Heard(
        list(heard.segments), list(heard.beats), list(heard.downbeats), heard.duration)
    assert heard.duration == read_audio(Path(song.audio_path)).duration_s


@pytest.mark.parametrize("case", list(CASES))
def test_a_sheet_laid_out_again_from_what_its_raw_kept_is_the_same_bytes(conn, cfg, tmp_path, case):
    # What E13 relies on: ``heard_of`` the raw gives back what was heard, and make_sheet the very sheet, no model.
    seconds, fields, segments, beats, before = CASES[case]
    song = with_audio(conn, tmp_path, add_song(conn, "Nobody", "River Road"), seconds=seconds, **fields)
    if before is not None:
        before(conn, song)
        song = get_song(conn, song.id)
    _bulk(conn, cfg, song, Recognizer(segments), beats)
    song = get_song(conn, song.id)
    [kept] = kept_files(conn, song.id)
    raw = get_version(conn, kept.version_id).raw
    transcript = transcript_of(conn, song)
    silent = transcript is None and heard_nothing_of(conn, song)
    made = make_sheet(song, heard_of(raw), source=_from_youtube(youtube_audio(conn, song)), transcript=transcript,
                      silent=silent, said=silent and said_not_sung(conn, song))
    assert made.text == (song_dir(cfg.library_dir, song) / kept.name).read_text(encoding="utf-8")
    assert raw_of(song, made)["heard"] == raw["heard"]


def test_a_raw_that_kept_no_heard_or_another_contract_gives_none():
    assert heard_of({"model": "btc_large_voca"}) is None
    assert heard_of({"heard": {"contract": 2, "duration": 1.0, "chords": [], "beats": [], "downbeats": []}}) is None


GOOD = {"contract": 1, "duration": 10.0, "chords": [[0.0, 5.0, "C"], [5, 10.0, "G"]], "beats": [0.5, 1], "downbeats": []}


@pytest.mark.parametrize("member, value", [
    ("beats", "12"),  # a string is no list of numbers, though it iterates
    ("beats", [0.5, True]),  # a bool is no number
    ("beats", [0.5, "1.0"]),
    ("downbeats", None),
    ("duration", True),
    ("duration", "10.0"),
    ("chords", [[0.0, 5.0]]),
    ("chords", [[0.0, 5.0, "C", "x"]]),
    ("chords", [["0.0", 5.0, "C"]]),
    ("chords", [[0.0, False, "C"]]),
    ("chords", [[0.0, 5.0, 7]]),
    ("chords", "C"),
    ("contract", None),
])
def test_a_heard_record_of_any_other_shape_is_unreadable(member, value):
    from caracole.autochords.sheet import read_heard

    record = {**GOOD, member: value}
    with pytest.raises(ValueError, match="what was heard"):
        read_heard(record)
    assert heard_of({"heard": record}) is None
    record = {k: v for k, v in GOOD.items() if k != member}
    with pytest.raises(ValueError):
        read_heard(record)


def test_a_heard_record_reads_its_numbers_as_floats():
    from caracole.autochords.sheet import read_heard

    heard = read_heard(GOOD)
    assert heard == Heard([ChordSegment(0.0, 5.0, "C"), ChordSegment(5.0, 10.0, "G")], [0.5, 1.0], [], 10.0)
    assert all(type(x) is float for x in [*heard.beats, *(s.start for s in heard.segments)])
    assert read_heard({**GOOD, "duration": None}).duration is None


def _ten_minutes() -> Heard:
    """A dense hearing of a ten-minute song, as real recordings run up to: 40 segments and 75 beats a minute. BTC's
    400 segments at its frames (10/108 s, three decimals) under long chord names; beat_this's 750 beats at 50 frames a
    second with a frame's jitter and some twin peaks merged by their mean, every fourth a downbeat."""
    import random

    rng = random.Random(12)
    names = ["C#m7b5", "Abmaj7", "F#mMaj7", "Bbsus4", "Ebdim7", "G7", "N"]
    frames = 6480  # ten minutes of BTC's frames
    cuts = sorted(rng.sample(range(1, frames), 399))
    edges = [0, *cuts, frames]
    segments = [ChordSegment(round(a * 10 / 108, 3), round(b * 10 / 108, 3), rng.choice(names))
                for a, b in zip(edges, edges[1:])]
    beats = []
    for k in range(750):  # 75 a minute, as a dense recording's
        frame = 40 * k + rng.choice((-1, 0, 0, 1))
        beats.append((frame + 0.5) / 50 if rng.random() < 0.1 else frame / 50)
    return Heard(segments, beats, beats[::4], 600.0195918367347)


def test_a_ten_minute_songs_raw_stays_under_32_kb(conn, tmp_path):
    from caracole.autochords.sheet import Maker

    song = with_audio(conn, tmp_path, add_song(conn, "Nobody", "River Road"), seconds=1.0, lyrics_status="found",
                      lyrics_json=lyrics_json(synced=SYNCED, duration=600.0))
    heard = _ten_minutes()
    assert (len(heard.segments), len(heard.beats)) == (400, 750)
    made = make_sheet(song, heard)
    maker = Maker("computer", "0123456789abcdef0123456789abcdef", {
        "chords": "btc_large_voca@1673d23f8f9a55ae", "beats": "beat_this final0@8c328b45f59d8dd3"}, "torch 2.13.0",
        "Nobody - River Road (Remastered 2011).flac", "0123456789abcdef")
    raw = raw_of(song, made, maker=maker)
    stored = json.dumps(raw, ensure_ascii=False).encode("utf-8")  # as versions.upsert_version writes it
    assert len(stored) < 32 * 1024, len(stored)
    assert heard_of(json.loads(stored)) == heard


def test_the_sheet_half_reads_no_audio_file():
    # sheet.py lays a sheet out from what was heard alone: no audio reader (music.py, mutagen) and no model.
    code = ("import sys\nimport caracole.autochords.sheet\nimport caracole.autochords.sheet_lyrics\n"
            "heavy = {'caracole.music', 'mutagen', 'torch', 'librosa', 'numpy', 'beat_this', 'soundfile', 'whisper',\n"
            "         'rapidfuzz', 'httpx', 'caracole.autochords.btc', 'caracole.autochords.beats',\n"
            "         'caracole.autochords.audio', 'caracole.autochords.run'}\n"
            "print(sorted(heavy & set(sys.modules)))\n")
    env = {**os.environ, "PYTHONPATH": subprocess_pythonpath(Path(__file__).parents[1] / "src")}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)
    assert out.stdout.strip() == "[]"
