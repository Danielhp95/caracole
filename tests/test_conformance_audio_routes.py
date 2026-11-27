"""A sheet from an audio file, the library page's routes (web/audio_routes.py), for the phone's ``AudioRoutes`` (the
chords-on-the-phone design's §8.2, the plan's E24) to answer as caracole serve answers them.

**vectors/web/audio_routes.jsonl**, a header, then:

- ``{"fn": "fixture", "records", "store"}``: the scenes' library, dumped whole (``helpers.corpus.dump_fixture``, its
  folder's files), each path under the state folder written ``{state}``; ``store``, the files of ``state_dir/audio/``
  by name, base64: the song whose audio is a file you gave. Its songs: Calla Lake - River Road (no audio), Old Pines -
  Cedar Hill (a human sheet), Grey Owls - Quiet Hours (ignored), Bought Band - Store Song (a purchase linked), Tube
  Band - Video Song (YouTube's audio, its kv ``youtube:`` record), Given Band - Own Song (a file you gave).
- ``{"fn": "scene", "scene", "can", "steps", "staged", "jobs"}``: a scene, a fresh copy of that library and caracole
  serve over it (its queue never started), each step a request the page's script makes, in order, to
  ``WebApp.handle``:
  - ``ask``: ``{method, target, kind, body, headers}``: ``kind`` ``bytes`` (``body`` base64; or ``{"length": n}``, a
    body of n bytes past the route's limit, which the phone is never sent: its ``Content-Length`` alone), ``json``
    (``body`` the document) or ``form`` (``body`` ``[[name, value], …]``, the token first); ``headers``, any the
    script sends otherwise (null: left out), else the script's own (the form token in its header, its content type,
    JSON wanted);
  - ``audio``: for an upload, what the store's reader made of its bytes (``audio_store._examine``'s ``{format,
    duration, tags}``), which the phone's examiner answers; null: the reader refused the file; absent: never read;
  - ``status`` and ``out``, the answer as JSON (a refusal's ``{error}``, and ``reload``), each staged upload's id
    written ``<upload N>`` in the order they were staged, a job queued's view cut to its ``id``.
  ``can``: whether this caracole makes sheets from audio files (``audio_routes.audio_reason``); where it doesn't, its
  reason is ``<reason>``, which the phone's replay gives as its own. ``staged``: the uploads staged after the last
  step; ``jobs``: the queue's jobs after it, ``{title, key, steps: [[label, [args]]], display, note, wanted}``,
  ``wanted`` that caracole serve wrote wanted.txt for it (its ``note`` names the line; the phone writes none).
- ``{"fn": "limits", "out": {"<METHOD> <path>": [body, limit]}}``: each route's declared kind and limit.
- ``{"fn": "caracole.library_page.audio_member", "out"}``: ``server.audio`` where this caracole makes sheets from
  audio files (its ``limit`` and ``too_big``), as the phone's page gives it then.
- ``{"fn": "caracole.audio_store.examine", "file" | "bytes", "out"}``: what the store reads of a file (its format,
  length and tags), over the committed fixtures (``file``, under tests/fixtures/) and tiny files of every format
  tagged by mutagen (``bytes``, base64, helpers/audio_files.py), for the phone's examiner.

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_audio_routes.py``.
"""

from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import urlencode

import pytest
from helpers.audio_files import audio
from helpers.audio_files import write as write_audio
from helpers.corpus import VECTORS, check, dump_fixture, jsonl

MADE_BY = "tests/test_conformance_audio_routes.py"
VECTOR = VECTORS / "web" / "audio_routes.jsonl"
FIXTURES = Path(__file__).parent / "fixtures"
HOST = "localhost:8737"
CSRF = "tok"
ADDED = "2026-11-20T10:00:00Z"
REASON = "<reason>"
JSON = "application/json"
BYTES = "application/octet-stream"
VIDEO_AUDIO = "/nowhere/youtube/abc123def45.m4a"
PURCHASE = "/music/Bought Band/Store Song.mp3"
SHORT = {"MP3": 0.1, "WAV": 0.05, "AIFF": 0.05}  # seconds of the files made: a few KB each

SONGS = (("Calla Lake", "River Road"), ("Old Pines", "Cedar Hill"), ("Grey Owls", "Quiet Hours"),
         ("Bought Band", "Store Song"), ("Tube Band", "Video Song"), ("Given Band", "Own Song"))

EXAMINED = ("autochords/decode.mp3", "autochords/decode-headerless.mp3", "autochords/decode-lame.mp3",
            "autochords/decode.m4a", "autochords/decode-11k.m4a", "autochords/decode.flac",
            "autochords/decode-24.flac", "autochords/decode.ogg", "autochords/decode-opus.ogg",
            "autochords/decode.wav", "autochords/decode.aiff", "audio/cbr.mp3", "audio/cbr-22k.mp3",
            "audio/long-guess.mp3", "audio/short-guess.mp3", "audio/xing.mp3", "audio/tone.m4a")


class Library:
    """The scenes' library, in a folder of its own: its config, its database, its songs by title."""

    def __init__(self, root: Path):
        from caracole import db
        from caracole.config import load_config

        self.root = root
        root.mkdir(parents=True)
        (root / "library").mkdir()
        (root / "caracole.toml").write_text(
            f'library_dir = "{root / "library"}"\nstate_dir = "{root / "state"}"\ncache_dir = "{root / "cache"}"\n',
            encoding="utf-8")
        self.cfg = load_config(root / "caracole.toml", env={"HOME": str(root / "home")})
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self.conn = db.connect(self.cfg.db_path)

    def build(self) -> dict[str, Any]:
        from conftest import add_song
        from helpers.audio_files import given
        from helpers.corpus import phone_schema

        from caracole.library import keep_file
        from caracole.songs import get_song, update_song
        from caracole.versions import upsert_version
        from caracole.youtube import Video
        from caracole.youtube_fetch import Record, _save

        phone_schema(self.conn)
        songs = {}
        for artist, title in SONGS:
            songs[title] = add_song(self.conn, artist, title, added_at=ADDED)
        cedar = songs["Cedar Hill"]
        version = upsert_version(self.conn, provider="ug", tab_id="5001", song_id=cedar.id, slot="sheet",
                                 kind="chords", rating=4.5, votes=10, version=1, label=None,
                                 url="https://tabs.ultimate-guitar.com/tab/old-pines/cedar-hill-chords-5001",
                                 raw={"id": 5001}, now=ADDED)
        keep_file(self.conn, self.cfg.library_dir, song=cedar, version_id=version, name="sheet.txt",
                  data=b"[ch]G[/ch]Cedar Hill\n", rank=1)
        self.conn.execute("UPDATE songs SET status = 'ignored' WHERE id = ?", (songs["Quiet Hours"].id,))
        update_song(self.conn, songs["Store Song"].id, audio_path=PURCHASE, audio_mtime=1764000000.0)
        video = songs["Video Song"]
        update_song(self.conn, video.id, audio_path=VIDEO_AUDIO, audio_mtime=1764000000.0)
        _save(self.conn, video.id, Record(video=Video("abc123def45", "Tube Band - Video Song", "Tube Band", 200.0),
                                          source="search", audio=VIDEO_AUDIO, downloaded_at=ADDED))
        own = songs["Own Song"]
        given(self.conn, self.cfg.state_dir, own, "MP3")
        self.conn.execute("UPDATE songs SET audio_mtime = 1764000000.0 WHERE id = ?", (own.id,))
        self.conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (ADDED, ADDED))
        self.conn.execute("UPDATE files SET created_at = ?", (ADDED,))
        self.conn.commit()
        self.songs = {t: get_song(self.conn, s.id) for t, s in songs.items()}
        state = str(self.cfg.state_dir)
        records = [json.loads(json.dumps(r).replace(json.dumps(state)[1:-1], "{state}"))
                   for r in dump_fixture(self.conn, self.cfg.library_dir)]
        store = self.cfg.state_dir / "audio"
        return {"fn": "fixture", "records": records,
                "store": {p.name: base64.b64encode(p.read_bytes()).decode("ascii") for p in sorted(store.iterdir())}}

    def copy(self, to: Path) -> Library:
        """A fresh copy of this library, for one scene: its folders and database, its paths its own."""
        self.conn.commit()
        shutil.copytree(self.root, to)
        other = Library.__new__(Library)
        from caracole import db
        from caracole.config import load_config

        other.root = to
        (to / "caracole.toml").write_text(
            f'library_dir = "{to / "library"}"\nstate_dir = "{to / "state"}"\ncache_dir = "{to / "cache"}"\n',
            encoding="utf-8")
        other.cfg = load_config(to / "caracole.toml", env={"HOME": str(to / "home")})
        other.conn = db.connect(other.cfg.db_path)
        old, new = str(self.cfg.state_dir), str(other.cfg.state_dir)
        other.conn.execute("UPDATE songs SET audio_path = replace(audio_path, ?, ?)", (old, new))
        other.conn.commit()
        other.songs = self.songs
        return other


class Scene:
    """One scene: caracole serve over a copy of the library, its queue never started, the requests in order."""

    def __init__(self, library: Library, name: str, *, can: bool = True):
        from caracole.web.app import WebApp
        from caracole.web.jobs import JobQueue

        self.lib = library
        self.name = name
        self.can = can

        def runner(args, emit):  # nothing runs: the queue is never started
            raise AssertionError(f"a route ran {args}")

        self.app = WebApp(library.cfg, JobQueue(runner, limit=20), allowed=frozenset({"localhost"}), csrf=CSRF,
                          searches_lacuerda=False, searches_youtube=False)
        self.steps: list[dict[str, Any]] = []
        self.ids: dict[str, str] = {}
        self.wanted: set[int] = set()

    def song(self, title: str):
        return self.lib.songs[title]

    def mask(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {k: self.mask(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.mask(v) for v in value]
        if isinstance(value, str):
            for real, masked in self.ids.items():
                value = value.replace(real, masked)
        return value

    def target(self, path: str, **query: Any) -> str:
        """``path`` with ``query``, each value a masked id given back as its real one."""
        real = {masked: id_ for id_, masked in self.ids.items()}
        shown = {k: real.get(str(v), str(v)) for k, v in query.items()}
        return f"{path}?{urlencode(shown)}" if shown else path

    def _ask(self, method: str, target: str, kind: str, body: bytes, headers: dict[str, str | None]) -> tuple[int, Any]:
        from caracole.web import audio_routes
        from caracole.web.app import Request, WebApp

        sent = {"host": HOST, "accept": JSON, "sec-fetch-site": "same-origin", "origin": f"http://{HOST}"}
        if kind == "form":
            sent["content-type"] = "application/x-www-form-urlencoded"
        else:
            sent |= {"content-type": BYTES if kind == "bytes" else JSON, "x-caracole-form-token": CSRF}
        for name, value in headers.items():
            if value is None:
                sent.pop(name, None)
            else:
                sent[name] = value
        reason = None if self.can else REASON
        with mock.patch.object(audio_routes, "audio_reason", lambda cfg: reason):
            answer = WebApp.finish(self.app.handle(Request(method, target, sent, body)))
        return answer.status, json.loads(answer.body)

    def upload(self, data: bytes, name: str | None, *, audio: Any = "read", headers: dict[str, str | None] | None = None,
               oversized: int | None = None, **query: Any) -> dict[str, Any]:
        """POST /audio/upload of ``data`` sent under ``name`` (None: no name in the query), with ``query`` (a card's
        ``song`` and ``identity``); ``audio`` what the store's reader reads of it, ``"read"`` mutagen's own."""
        from caracole import audio_store

        read: list[Any] = []
        real = audio_store._examine

        def examined(f):
            f.seek(0)
            if audio_store.sniff(f.read(audio_store.HEAD)) is None:  # no format: the reader is never asked
                raise audio_store.AudioError(audio_store.NOT_AUDIO, 415)
            f.seek(0)
            try:
                found = real(f)
            except audio_store.AudioError as e:
                read.append(None if e.status == 415 else "refused")
                raise
            if audio != "read":
                found = audio_store.Audio(audio["format"], audio["duration"], audio["tags"])
                if found.duration > audio_store.MAX_SECONDS:
                    read.append({"format": found.format, "duration": found.duration, "tags": found.tags})
                    raise audio_store.AudioError(audio_store.TOO_LONG, 422)
            read.append({"format": found.format, "duration": found.duration, "tags": found.tags})
            return found

        asked = ({"name": name} if name is not None else {}) | query
        body = bytes(oversized) if oversized is not None else data
        before = set(audio_store._staged_ids(self.lib.cfg.state_dir / "audio"))
        with mock.patch.object(audio_store, "_examine", examined):
            status, out = self._ask("POST", self.target("/audio/upload", **asked), "bytes", body, headers or {})
        if status == 200:
            self.ids[out["upload"]] = f"<upload {len(self.ids) + 1}>"
        assert set(audio_store._staged_ids(self.lib.cfg.state_dir / "audio")) <= before | set(self.ids)
        ask = {"method": "POST", "target": self.mask(self.target("/audio/upload", **asked)), "kind": "bytes",
               "body": {"length": len(body)} if oversized is not None else base64.b64encode(data).decode("ascii"),
               "headers": headers or {}}
        step = {"ask": ask, "status": status, "out": self.mask(out)}
        if read and read[0] != "refused":
            step["audio"] = read[0]
        self.steps.append(step)
        return out

    def form(self, path: str, fields: list[tuple[str, str]], *, headers: dict[str, str | None] | None = None,
             token: str | None = CSRF) -> dict[str, Any]:
        real = {masked: id_ for id_, masked in self.ids.items()}
        sent = ([("csrf", token)] if token is not None else []) + [(k, real.get(v, v)) for k, v in fields]
        wanted = self.lib.cfg.wanted_file
        before = wanted.read_text("utf-8") if wanted.exists() else None
        status, out = self._ask("POST", path, "form", urlencode(sent).encode(), headers or {})
        after = wanted.read_text("utf-8") if wanted.exists() else None
        if isinstance(out, dict) and isinstance(out.get("job"), dict):
            out = {"job": {"id": out["job"]["id"]}}
            if after != before:
                self.wanted.add(out["job"]["id"])
        step = {"ask": {"method": "POST", "target": path, "kind": "form",
                        "body": [[k, self.mask(v)] for k, v in sent], "headers": headers or {}},
                "status": status, "out": self.mask(out)}
        self.steps.append(step)
        return out

    def drop(self, doc: Any, *, headers: dict[str, str | None] | None = None) -> dict[str, Any]:
        real = {masked: id_ for id_, masked in self.ids.items()}
        sent = {k: real.get(v, v) if isinstance(v, str) else v for k, v in doc.items()} if isinstance(doc, dict) else doc
        status, out = self._ask("POST", "/audio/drop", "json", json.dumps(sent).encode(), headers or {})
        self.steps.append({"ask": {"method": "POST", "target": "/audio/drop", "kind": "json", "body": doc,
                                   "headers": headers or {}}, "status": status, "out": self.mask(out)})
        return out

    def record(self) -> dict[str, Any]:
        from caracole import audio_store

        staged = sorted(self.ids.get(i, i) for i in audio_store._staged_ids(self.lib.cfg.state_dir / "audio"))
        jobs = [{"title": j.title, "key": j.song_key, "steps": [[s.label, list(s.args)] for s in j.steps],
                 "display": j.display, "note": j.note, "wanted": j.id in self.wanted}
                for j in self.app.queue.snapshot()]
        return {"fn": "scene", "scene": self.name, "can": self.can, "steps": self.steps, "staged": staged,
                "jobs": self.mask(jobs)}


def tagged(fmt: str, folder: Path, **tags: str) -> bytes:
    from caracole.audio_store import FORMATS

    return write_audio(folder / f"tagged{FORMATS[fmt]}", fmt, SHORT.get(fmt, 1.0), **tags).read_bytes()


def scenes(library: Library, tmp: Path) -> list[dict[str, Any]]:
    out = []
    n = iter(range(1000))

    def scene(name: str, **kw: Any) -> Scene:
        return Scene(library.copy(tmp / f"scene-{next(n)}"), name, **kw)

    files = tmp / "files"
    files.mkdir()
    river, cedar, quiet = (library.songs[t] for t in ("River Road", "Cedar Hill", "Quiet Hours"))
    store, video, own = (library.songs[t] for t in ("Store Song", "Video Song", "Own Song"))

    s = scene("the bar's +: a tagged file of a song of the library, then files named by their names alone")
    s.upload(tagged("MP3", files, artist="Calla Lake", title="River Road (Official Video)", album="Shores"),
             "river road.mp3")
    s.upload(audio("WAV", 0.05), "03 - Nobody Knows - First Light.wav")
    s.upload(audio("Ogg", 1.0), "humming.ogg")
    s.upload(audio("FLAC", 1.0), "Calla Lake - River Road.flac")
    s.upload(audio("AIFF", 0.05), "C:\\Users\\me\\Music\\07. Old Pines - Cedar Hill.aiff")
    s.upload(tagged("M4A", files, artist="Grey Owls", title="Quiet Hours"), "song.m4a")
    s.upload(tagged("FLAC", files, title="Only A Title"), "Given Band - Own Song.flac")
    out.append(s.record())

    s = scene("a card's file: each song's audio as the dialog says what the file replaces")
    for song in (river, cedar, store, video, own):
        s.upload(audio("FLAC", 1.0), "take.flac", song=song.id, identity=song.key)
    s.upload(audio("FLAC", 1.0), "take.flac", song=quiet.id)  # an ignored song's card: the route's dialog says nothing
    out.append(s.record())

    s = scene("a card that names no song, another's, or none at all")
    s.upload(audio("FLAC", 1.0), "take.flac", song=999)
    s.upload(audio("FLAC", 1.0), "take.flac", song=river.id, identity="someone/else")
    s.upload(audio("FLAC", 1.0), "take.flac", song="nine")
    s.upload(audio("FLAC", 1.0), "take.flac", song="99999999999999999999999")
    out.append(s.record())

    s = scene("the files the store refuses, and requests the server refuses before the route")
    s.upload(audio("FLAC", 1.0), "")
    s.upload(audio("FLAC", 1.0), None)
    s.upload(audio("FLAC", 1.0), "/\x00\x01")
    s.upload(b"", "empty.mp3")
    s.upload(b"just some text, no audio at all\n" * 3, "notes.mp3")
    s.upload(audio("FLAC", 1.0), "long.flac", audio={"format": "FLAC", "duration": 1801.5,
                                                   "tags": {"artist": None, "title": None, "album": None}})
    from helpers.audio_files import mp4

    s.upload(mp4(1.0, video=True), "clip.m4a")
    s.upload(b"", "huge.mp3", oversized=128 * 1024 * 1024 + 1)
    s.upload(audio("FLAC", 1.0), "token.flac", headers={"x-caracole-form-token": None})
    s.upload(audio("FLAC", 1.0), "type.flac", headers={"content-type": "audio/mpeg"})
    s.upload(audio("FLAC", 1.0), "other.flac", headers={"origin": "http://elsewhere.example", "sec-fetch-site": "cross-site"})
    out.append(s.record())

    s = scene("a caracole that makes no sheets from audio files", can=False)
    s.upload(audio("FLAC", 1.0), "take.flac")
    s.form("/audio", [("upload", "0123456789abcdef"), ("artist", "Calla Lake"), ("title", "River Road")])
    s.drop({"upload": "0123456789abcdef"})
    out.append(s.record())

    s = scene("Make sheet from a card: queued, asked again with another file, and that file let go")
    s.upload(audio("FLAC", 1.0), "first.flac", song=river.id, identity=river.key)
    s.form("/audio", [("upload", "<upload 1>"), ("song", str(river.id)), ("identity", river.key)])
    s.upload(audio("WAV", 0.05), "second.wav", song=river.id, identity=river.key)
    s.form("/audio", [("upload", "<upload 2>"), ("song", str(river.id)), ("identity", river.key)])
    s.drop({"upload": "<upload 1>"})
    s.drop({"upload": "<upload 2>"})
    s.upload(audio("Ogg", 1.0), "third.ogg")  # the job's file stays: no new upload lets it go
    out.append(s.record())

    s = scene("Make sheet by name: a new song, a song of the library, with its file's album and length")
    s.upload(tagged("MP3", files, album="Lowlands"), "Nobody Knows - First Light.mp3")
    s.form("/audio", [("upload", "<upload 1>"), ("artist", "Nobody  Knows"), ("title", " First Light ")])
    s.upload(audio("WAV", 0.05), "Calla Lake - River Road.wav")
    s.form("/audio", [("upload", "<upload 2>"), ("artist", "calla lake"), ("title", "river road")])
    s.upload(audio("FLAC", 1.0), "Bought Band - Store Song.flac")
    s.form("/audio", [("upload", "<upload 3>"), ("artist", "Bought Band"), ("title", "Store Song"),
                      ("album", "Their Own"), ("duration", "3:05")])
    out.append(s.record())

    s = scene("Make sheet refused: a sheet, ignored, no such song, another's id, no names, no upload")
    s.upload(audio("FLAC", 1.0), "take.flac")
    for fields in ([("upload", "<upload 1>"), ("song", str(cedar.id))],
                   [("upload", "<upload 1>"), ("song", str(quiet.id))],
                   [("upload", "<upload 1>"), ("artist", "Old Pines"), ("title", "Cedar Hill")],
                   [("upload", "<upload 1>"), ("artist", "grey owls"), ("title", "quiet hours")],
                   [("upload", "<upload 1>"), ("song", "999")],
                   [("upload", "<upload 1>"), ("song", str(river.id)), ("identity", "someone/else")],
                   [("upload", "<upload 1>"), ("song", "nine")],
                   [("upload", "<upload 1>"), ("artist", "Calla Lake")],
                   [("upload", "<upload 1>"), ("artist", "Someone - Else"), ("title", "Song")],
                   [("upload", "<upload 1>"), ("artist", "A"), ("title", "B"), ("duration", "4:75")],
                   [("upload", "nope"), ("song", str(river.id))],
                   [("upload", "0123456789abcdef"), ("song", str(river.id))],
                   [("song", str(river.id))]):
        s.form("/audio", fields)
    s.form("/audio", [("upload", "<upload 1>"), ("song", str(river.id))], token="stale")
    s.form("/audio", [("upload", "<upload 1>"), ("song", str(river.id))], token=None)
    out.append(s.record())

    s = scene("Cancel: a staged file dropped, then gone; what names none")
    s.upload(audio("FLAC", 1.0), "take.flac")
    s.drop({"upload": "<upload 1>"})
    s.drop({"upload": "<upload 1>"})
    for doc in ({}, {"upload": 5}, {"upload": "nope"}, ["<upload 1>"]):
        s.drop(doc)
    s.drop({"upload": "0123456789abcdef"}, headers={"x-caracole-form-token": None})
    out.append(s.record())

    s = scene("a new upload lets go of the one before, unless a job names it")
    s.upload(audio("FLAC", 1.0), "one.flac")
    s.upload(audio("Ogg", 2.0), "two.ogg")
    s.form("/audio", [("upload", "<upload 1>"), ("song", str(river.id))])
    s.form("/audio", [("upload", "<upload 2>"), ("song", str(store.id))])
    s.upload(audio("FLAC", 1.0), "three.flac")
    s.form("/audio", [("upload", "<upload 2>"), ("song", str(video.id))])
    out.append(s.record())
    return out


def limits() -> dict[str, Any]:
    from caracole.web import audio_routes

    return {"fn": "limits", "out": {f"{r.method} {r.path}": [r.body, r.limit] for r in audio_routes.ROUTES}}


def member(cfg) -> dict[str, Any]:
    from caracole import library_page

    with mock.patch("caracole.youtube_fetch.autochords_problem", lambda cfg: None):
        return {"fn": "caracole.library_page.audio_member", "out": library_page.audio_member(cfg)}


def examined(tmp: Path) -> list[dict[str, Any]]:
    from dataclasses import asdict

    from caracole import audio_store
    from caracole.audio_store import FORMATS

    out = []
    for name in EXAMINED:
        found = audio_store.examine(FIXTURES / name)
        out.append({"fn": "caracole.audio_store.examine", "file": name, "out": asdict(found)})
    folder = tmp / "examined"
    folder.mkdir()
    for fmt in FORMATS:
        data = tagged(fmt, folder, artist="Calla Lake", title="River Road", album="Shores")
        path = folder / f"tagged{FORMATS[fmt]}"
        out.append({"fn": "caracole.audio_store.examine", "bytes": base64.b64encode(data).decode("ascii"),
                    "out": asdict(audio_store.examine(path))})
    return out


def records(tmp: Path) -> list[dict[str, Any]]:
    library = Library(tmp / "library-base")
    fixture = library.build()
    return [fixture, *scenes(library, tmp), limits(), member(library.cfg), *examined(tmp)]


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> list[dict[str, Any]]:
    return records(tmp_path_factory.mktemp("audio-routes"))


def test_the_audio_routes_vectors_are_caracole_serves_answers(made):
    check(VECTOR, jsonl(made, corpus="web/audio_routes", made_by=MADE_BY))


def test_every_route_answers_and_refuses(made):
    steps = [step for r in made if r["fn"] == "scene" for step in r["steps"]]
    for path in ("/audio/upload", "/audio", "/audio/drop"):
        statuses = {step["status"] for step in steps if step["ask"]["target"].split("?")[0] == path}
        assert 200 in statuses and len(statuses) >= 4, (path, statuses)
    assert {413, 415, 422, 403, 400, 404, 409} <= {step["status"] for step in steps}
    jobs = [job for r in made if r["fn"] == "scene" for job in r["jobs"]]
    assert any(j["wanted"] for j in jobs) and any(not j["wanted"] for j in jobs)
    assert any(step.get("audio") is None and "audio" in step for step in steps)  # a file the reader refused


def test_the_vectors_are_the_same_on_another_run(made, tmp_path_factory):
    assert records(tmp_path_factory.mktemp("audio-routes-again")) == made
