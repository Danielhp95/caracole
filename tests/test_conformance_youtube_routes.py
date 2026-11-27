"""A sheet from a YouTube video on the phone: caracole serve's web/youtube_routes.py, written for android/server's
``YouTubeRoutes`` (and ``POST /request`` with ``youtube``, LibraryRoutes') to agree with (the phone-YouTube plan's
Y2.5; ``WebReplay.youtubeRoutes``).

**vectors/web/youtube_routes.jsonl**, after its header:

- ``{"fn": "fixture", "scene", "records", "thumbs"}``: a scene, a library in a fresh database dumped whole with its
  library folder's files (``helpers.corpus.dump_fixture``; overrides.toml as the phone's ``phone_overrides`` rows,
  never as a file), and the thumbnails kept in caracole's cache (``thumbs``: ``{name: base64}``), which the replay
  loads; every record after it names the scene it asks over. ``library``: Nick Cani's song with no sheet, Calla
  Lake's with a human sheet, an ignored one, one with audio of its own, one whose audio is a video's (its
  ``youtube:`` record), one with a video pasted under ``[youtube]``; a video read this month with its thumbnail, a
  video YouTube wouldn't give, a thumbnail kept that is no JPEG. ``cooling``: YouTube cooling down after a block.
  ``spent``: the hour's 10 searches and reads of YouTube spent (``events``). ``failed``: a video's read failed within
  the hour.
- ``{"fn": "POST /youtube" | "POST /request" | "POST /youtube/video", "scene", "case", "form": [[name, value], ...],
  "json", "problem", "full", "twice", "out"}``: the form posted to a fresh queue that runs nothing (``full``: one that
  holds no job; ``twice``: the same form posted once before, its job waiting, so the answer is that job's), asking for
  JSON (``json``) or not, with ``problem`` the reason this caracole makes no sheet from a video
  (``youtube_fetch.route_reason``'s, null for none: the phone's is its own, Phone.youtubeProblem, so the record names
  it), every gate read at ``NOW``. ``out`` a refusal, ``{status, title, message}``, or ``{status, location, body,
  order, job: {title, key, steps: [[label, [args]]], display, note}, wanted, song}``: its body less the job's ``view``
  (``order``, its members' paths in the order the answer wrote them, the vector's keys being sorted);
  ``wanted``, caracole serve wrote wanted.txt (``library_routes.wanted_line``), whose line its ``note`` names: the
  phone writes none (the job adds the song), so its note is ""; and ``song``, that line's song (``{artist, title,
  album, duration_ms}``), the one the phone's job adds (its spec's song), null where none was written.
- ``{"fn": "GET /api/youtube/video", "scene", "case", "query": {name: value}, "problem", "out": {status, body, order}}``:
  ``pasted_video``'s answer (``order`` as above), or a refusal.
- ``{"fn": "GET /youtube/thumb/", "scene", "case", "name", "out": {status, headers, sha256}}``: ``thumbnail``'s
  answer (its body's SHA-256), or its 404's ``body``.

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_youtube_routes.py``.
"""

from __future__ import annotations

import base64
import hashlib
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

import pytest
from helpers.corpus import VECTORS, check, jsonl
from test_conformance_ug_link import World

from caracole import db, youtube_search

MADE_BY = "tests/test_conformance_youtube_routes.py"
VECTOR = VECTORS / "web" / "youtube_routes.jsonl"
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=UTC)
STAMP = "2026-11-27T12:00:00Z"
READ = "lzN7Thn3FV4"  # read this month, its thumbnail kept
WONT = "PrivateVid1"  # YouTube wouldn't give it
FRESH = "FreshVideo1"  # never read
DOWNLOADED = "Downloaded1"  # the audio of Tube Band's song
PASTED = "PastedVideo"  # under [youtube] for Paste Band's song
SHEETED = "RiverRoad01"  # read this month, its title Calla Lake's song, which has a human sheet
NOT_JPEG = "NotAJpeg001"  # a thumbnail kept that isn't a JPEG
JPEG = (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xc0\x00\x0b\x08\x01\x68\x01\xe0\x01\x01\x11\x00\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x12\x34\xff\xd9")
WATCH = "https://www.youtube.com/watch?v={}"


def _gate_at() -> Iterator[None]:
    """youtube_search.video_gate read at ``NOW``, wherever a route reads it."""
    real = youtube_search.video_gate
    return mock.patch.object(youtube_search, "video_gate", lambda cfg, conn, vid, now: real(cfg, conn, vid, NOW))


@contextmanager
def _asking(problem: str | None) -> Iterator[None]:
    """The routes as caracole serve answers them, its reason for no sheet from a video ``problem``, at ``NOW``."""
    from caracole import youtube_fetch

    with _gate_at(), mock.patch.object(youtube_fetch, "route_reason", lambda cfg: problem), \
            mock.patch.object(youtube_fetch, "route_problem", lambda cfg: problem):
        yield


def _read(vid: str, title: str, channel: str, *, thumb: bool, days: int = 3) -> tuple[str, str]:
    from datetime import timedelta

    from caracole import stamps
    return (youtube_search.KV_PREFIX + youtube_search.video_key(vid),
            json.dumps({"at": stamps.stamp(NOW - timedelta(days=days)),
                        "video": {"id": vid, "title": title, "channel": channel, "duration": 222.0,
                                  "url": WATCH.format(vid)}, "thumb": thumb}, ensure_ascii=False))


def _fixture(w: World, scene: str) -> dict[str, Any]:
    made = w.fixture(scene)
    made.pop("cache", None)
    root = w.cfg.cache_dir / youtube_search.THUMBS
    made["thumbs"] = {p.name: base64.b64encode(p.read_bytes()).decode("ascii")
                      for p in sorted(root.iterdir())} if root.is_dir() else {}
    return made


def library(tmp: Path, scene: str = "library") -> tuple[World, dict[str, Any]]:
    from caracole.library import keep_file
    from caracole.songs import update_song
    from caracole.versions import upsert_version
    from caracole.youtube import Video
    from caracole.youtube_fetch import Record, _save

    w = World(tmp, scene)
    songs = {}
    for artist, title in (("Nick Cani", "Vikingos veganos"), ("Calla Lake", "River Road"),
                          ("Ignored Band", "Ignored Song"), ("Own Audio", "Purchase"), ("Tube Band", "Downloaded"),
                          ("Paste Band", "Pasted")):
        songs[title] = w.song(artist, title)
    river = songs["River Road"]
    version = upsert_version(w.conn, provider="ug", tab_id="101", song_id=river.id, slot="sheet", kind="chords",
                             rating=4.7, votes=90, version=1, label=None, url="https://tabs.ultimate-guitar.com/tab/101",
                             raw={}, now=STAMP)
    keep_file(w.conn, w.cfg.library_dir, song=river, version_id=version, name="sheet.txt", data=b"[ch]C[/ch]\n", rank=1)
    update_song(w.conn, songs["Purchase"].id, audio_path="/music/Own Audio/Purchase.m4a", audio_mtime=1.0)
    tube = f"/cache/youtube/{songs['Downloaded'].id}-{DOWNLOADED}.m4a"  # a path compared, never opened
    update_song(w.conn, songs["Downloaded"].id, audio_path=str(tube), audio_mtime=1.0)
    _save(w.conn, songs["Downloaded"].id, Record(video=Video(DOWNLOADED, "Tube Band - Downloaded", "Tube Band", 200.0),
                                                 source="search", audio=str(tube), downloaded_at=STAMP))
    w.overrides('[ignore]\nsongs = ["Ignored Band - Ignored Song"]\n\n'
                f'[youtube]\n"Paste Band - Pasted" = "{WATCH.format(PASTED)}"\n')
    for key, value in (_read(READ, "Nick Cani - Vikingos veganos (Videoclip)", "Nick Cani", thumb=True),
                       _read(NOT_JPEG, "Somebody - Something", "Somebody", thumb=True),
                       _read(SHEETED, "Calla Lake - River Road (Live)", "Calla Lake", thumb=False),
                       (youtube_search.KV_PREFIX + youtube_search.video_key(WONT),
                        json.dumps({"at": "2026-11-26T10:00:00Z", "video": None,
                                    "unavailable": f"[youtube] {WONT}: Private video"}))):
        db.kv_set(w.conn, key, value)
    thumbs = w.cfg.cache_dir / youtube_search.THUMBS
    thumbs.mkdir(parents=True)
    (thumbs / f"{READ}.jpg").write_bytes(JPEG)
    (thumbs / f"{NOT_JPEG}.jpg").write_bytes(b"<html>no</html>")
    return w, {t: s.id for t, s in songs.items()}


def _refusal(e) -> dict[str, Any]:
    return {"status": e.status, "title": e.title, "message": e.message}


def posted(w: World, scene: str, fn: str, case: str, form: list[tuple[str, str]], *, wants: bool = True,
           problem: str | None = None, full: bool = False, twice: bool = False) -> dict[str, Any]:
    from caracole.web import library_routes, youtube_routes
    from caracole.web.jobs import JobQueue
    from caracole.web.pages import Refused

    app = w.app()
    if full:
        def runner(args, emit):  # nothing runs: the queue is never started
            raise AssertionError(f"a route ran {args}")

        app.queue = JobQueue(runner, limit=0)
    route = {"POST /youtube": lambda f: youtube_routes.sheet_from_youtube(app, f),
             "POST /request": lambda f: library_routes.request(app, f),
             "POST /youtube/video": lambda f: youtube_routes.read_pasted_video(app, f, json=wants)}[fn]
    wanted = w.cfg.wanted_file
    before = wanted.read_text("utf-8") if wanted.exists() else ""
    record = {"fn": fn, "scene": scene, "case": case, "form": [list(f) for f in form], "json": wants,
              "problem": problem, "full": full, "twice": twice}
    try:
        with _asking(problem):
            if twice:  # asked once already: its job waits
                route({"csrf": "x", **dict(form)})
            response = route({"csrf": "x", **dict(form)})
    except Refused as e:
        _restore(wanted, before)
        return {**record, "out": _refusal(e)}
    [job] = app.queue.snapshot()
    location = next((v for k, v in response.headers if k == "Location"), None)
    body = json.loads(response.body) if response.body else None
    if isinstance(body, dict):
        body.pop("view", None)
    after = wanted.read_text("utf-8") if wanted.exists() else ""
    wrote = after != before
    song = None
    if wrote:
        from caracole.wanted import parse_wanted

        [line] = [ln for ln in parse_wanted(after)[0] if ln.line_no > len(parse_wanted(before)[0])]
        song = {"artist": line.artist, "title": line.title, "album": line.album, "duration_ms": line.duration_ms}
    _restore(wanted, before)
    return {**record, "out": {"status": response.status, "location": location, "body": body, "order": _order(body),
                              "job": {"title": job.title, "key": job.song_key,
                                      "steps": [[s.label, list(s.args)] for s in job.steps],
                                      "display": job.display, "note": job.note},
                              "wanted": wrote, "song": song}}


def _order(value: Any, at: str = "") -> list[str]:
    """Every object's members in the order the answer writes them, by their path (``.song.id``, ``[0].name``): the
    vector's own keys are sorted, so the order is recorded apart."""
    out: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            out.append(f"{at}.{k}")
            out += _order(v, f"{at}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out += _order(v, f"{at}[{i}]")
    return out


def _restore(wanted: Path, before: str) -> None:
    if before:
        wanted.write_text(before, encoding="utf-8")
    elif wanted.exists():
        wanted.unlink()


def asked(w: World, scene: str, case: str, query: dict[str, str], *, problem: str | None = None) -> dict[str, Any]:
    from caracole.web.pages import Refused
    from caracole.web.youtube_routes import pasted_video

    record = {"fn": "GET /api/youtube/video", "scene": scene, "case": case, "query": query, "problem": problem}
    try:
        with _asking(problem):
            response = pasted_video(w.app(), {k: [v] for k, v in query.items()})
    except Refused as e:
        return {**record, "out": _refusal(e)}
    body = json.loads(response.body)
    return {**record, "out": {"status": response.status, "body": body, "order": _order(body)}}


def thumb(w: World, scene: str, case: str, name: str) -> dict[str, Any]:
    from caracole.web.youtube_routes import thumbnail

    response = thumbnail(w.app(), name)
    out: dict[str, Any] = {"status": response.status, "headers": [list(h) for h in response.headers]}
    if response.status == 200:
        out["sha256"] = hashlib.sha256(response.body).hexdigest()
    else:
        out["body"] = json.loads(response.body)
    return {"fn": "GET /youtube/thumb/", "scene": scene, "case": case, "name": name, "out": out}


NOT_HERE = "auto-chords isn't installed"


def records(tmp: Path) -> list[dict[str, Any]]:
    w, ids = library(tmp)
    out: list[dict[str, Any]] = [_fixture(w, "library")]
    nick, river, ignored = ids["Vikingos veganos"], ids["River Road"], ids["Ignored Song"]
    own, tube, pasted = ids["Purchase"], ids["Downloaded"], ids["Pasted"]
    url = WATCH.format(FRESH)
    yt = "POST /youtube"
    for case, form, kw in (
        ("a song of the library, its card's video", [("youtube", url), ("song", str(nick)),
                                                     ("identity", "nick-cani/vikingos-veganos")], {}),
        ("the same, not asking for JSON", [("youtube", url), ("song", str(nick))], {"wants": False}),
        ("a video's every link: youtu.be with tracking", [("youtube", f"https://youtu.be/{FRESH}?si=abc"),
                                                          ("song", str(nick))], {}),
        ("a song whose audio is a video's", [("youtube", url), ("song", str(tube))], {}),
        ("a song with a video pasted under [youtube], given another", [("youtube", url), ("song", str(pasted))], {}),
        ("a song by name the library hasn't", [("youtube", url), ("artist", "Nueva Banda"), ("title", "Canción")], {}),
        ("a song by name the library has", [("youtube", url), ("artist", "nick cani"), ("title", "Vikingos Veganos")],
         {}),
        ("a song with a human sheet", [("youtube", url), ("song", str(river))], {}),
        ("a song by name with a human sheet", [("youtube", url), ("artist", "Calla Lake"), ("title", "River Road")], {}),
        ("an ignored song", [("youtube", url), ("song", str(ignored))], {}),
        ("a song with audio of its own", [("youtube", url), ("song", str(own))], {}),
        ("another song now has its id", [("youtube", url), ("song", str(nick)), ("identity", "someone/else")], {}),
        ("no such song", [("youtube", url), ("song", "999")], {}),
        ("not a song's id", [("youtube", url), ("song", "x")], {}),
        ("not a video's link", [("youtube", "https://vimeo.com/1"), ("song", str(nick))], {}),
        ("a link too long", [("youtube", url + "&x=" + "x" * 600), ("song", str(nick))], {}),
        ("no video", [("youtube", ""), ("song", str(nick))], {}),
        ("no sheet from a video here", [("youtube", url), ("song", str(nick))], {"problem": NOT_HERE}),
        ("a song by name with no title", [("youtube", url), ("artist", "Nueva Banda")], {}),
        ("the queue full", [("youtube", url), ("song", str(nick))], {"full": True}),
        ("asked again while its job waits", [("youtube", url), ("song", str(nick))], {"twice": True}),
    ):
        out.append(posted(w, "library", yt, case, form, **kw))
    for case, form, kw in (
        ("the request form's video", [("youtube", url), ("artist", "Nueva Banda"), ("title", "Canción"),
                                      ("album", "Un Disco"), ("duration", "3:45"), ("fetch", "1")], {}),
        ("one text and a video", [("youtube", url), ("q", "Nick Cani - Vikingos veganos")], {}),
        ("its video where none can be made", [("youtube", url), ("artist", "Nueva Banda"), ("title", "Canción")],
         {"problem": NOT_HERE}),
        ("its video not a video's", [("youtube", "nick cani"), ("artist", "Nueva Banda"), ("title", "Canción")], {}),
    ):
        out.append(posted(w, "library", "POST /request", case, form, **kw))
    for case, query, kw in (
        ("a video never read", {"url": WATCH.format(FRESH) + "&pp=x"}, {}),
        ("a video read, its thumbnail kept, the song guessed from its title", {"id": READ}, {}),
        ("a video YouTube won't give", {"url": f"https://youtu.be/{WONT}"}, {}),
        ("the audio of a song of the library", {"id": DOWNLOADED}, {}),
        ("the video pasted for a song of the library", {"id": PASTED}, {}),
        ("a video read, the song it names has a human sheet", {"id": SHEETED}, {}),
        ("no sheet from a video here", {"id": FRESH}, {"problem": NOT_HERE}),
        ("YouTube off", {"id": READ}, {"problem": "YouTube is off"}),
        ("not a video's link", {"url": "https://www.youtube.com/@nickcani"}, {}),
        ("not a video's id", {"id": "short"}, {}),
        ("nothing", {}, {}),
    ):
        out.append(asked(w, "library", case, query, **kw))
    for case, form, kw in (
        ("a video never read", [("url", WATCH.format(FRESH))], {}),
        ("the same, not asking for JSON", [("id", FRESH)], {"wants": False}),
        ("read already this month", [("id", READ)], {}),
        ("read as none this month", [("url", f"https://youtu.be/{WONT}")], {}),
        ("no sheet from a video here", [("id", FRESH)], {"problem": NOT_HERE}),
        ("not a video's link", [("url", "nick cani")], {}),
        ("the queue full", [("id", FRESH)], {"full": True}),
    ):
        out.append(posted(w, "library", "POST /youtube/video", case, form, **kw))
    for case, name in (("a thumbnail kept", f"{READ}.jpg"), ("one kept that isn't a JPEG", f"{NOT_JPEG}.jpg"),
                       ("none kept", f"{FRESH}.jpg"), ("no .jpg", READ), ("not an id", "../x.jpg")):
        out.append(thumb(w, "library", case, name))
    w.close()

    for scene, setup in (("cooling", "cooling"), ("spent", "spent"), ("failed", "failed")):
        w, _ = library(tmp, scene)
        if setup == "cooling":
            from datetime import timedelta

            from caracole.health import record_block
            record_block(w.conn, "youtube", NOW - timedelta(hours=1), "blocked")
        elif setup == "spent":
            w.conn.executemany("INSERT INTO events (run, at, provider, url, status, decision) VALUES (?, ?, 'youtube', ?, "
                               "NULL, 'ok')", [(f"youtube-search:2026-11-27T11:{n:02d}:00Z", f"2026-11-27T11:{n:02d}:00Z",
                                                WATCH.format(READ)) for n in range(10)])
        else:
            youtube_search.record_failure(w.conn, youtube_search.video_key(FRESH), NOW, "yt-dlp: boom")
        out.append(_fixture(w, scene))
        out.append(asked(w, scene, "a video never read", {"id": FRESH}))
        out.append(posted(w, scene, "POST /youtube/video", "a video never read", [("id", FRESH)]))
        if scene == "cooling":  # a sheet from a video is queued all the same: its job waits YouTube out
            out.append(posted(w, scene, yt, "a song of the library", [("youtube", WATCH.format(FRESH)),
                                                                       ("song", str(nick))]))
        w.close()
    return out


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> list[dict[str, Any]]:
    return records(tmp_path_factory.mktemp("youtube-routes"))


def test_youtube_routes_jsonl(made):
    check(VECTOR, jsonl(made, corpus="web/youtube_routes", made_by=MADE_BY))


def test_the_vector_is_the_same_on_another_run(made, tmp_path):
    assert jsonl(records(tmp_path), corpus="web/youtube_routes", made_by=MADE_BY) == jsonl(
        made, corpus="web/youtube_routes", made_by=MADE_BY)


def test_the_routes_come_to_what_they_say(made):
    by = {(r["fn"], r["scene"], r["case"]): r["out"] for r in made if "case" in r}
    first = by[("POST /youtube", "library", "a song of the library, its card's video")]
    assert first["status"] == 303 and first["job"]["key"] == "youtube:nick-cani/vikingos-veganos"
    assert first["job"]["steps"][0][1][:3] == ["youtube", "--sheet", "--progress"]
    assert by[("POST /youtube", "library", "a song by name the library hasn't")]["wanted"] is True
    form = by[("POST /request", "library", "the request form's video")]
    assert form["song"] == {"artist": "Nueva Banda", "title": "Canción", "album": "Un Disco", "duration_ms": 225000}
    assert by[("POST /youtube", "library", "asked again while its job waits")]["status"] == 303
    sheeted = by[("GET /api/youtube/video", "library", "a video read, the song it names has a human sheet")]
    assert sheeted["body"]["song"]["has_sheet"] is True
    for case in ("a song with a human sheet", "an ignored song", "a song with audio of its own",
                 "no sheet from a video here"):
        assert by[("POST /youtube", "library", case)]["status"] == 409, case
    assert by[("POST /youtube", "library", "a song whose audio is a video's")]["status"] == 303
    assert by[("POST /youtube", "library", "not a video's link")]["status"] == 400
    read = by[("GET /api/youtube/video", "library", "a video read, its thumbnail kept, the song guessed from its title")]
    assert read["body"]["state"] == "found" and read["body"]["video"]["thumb"] == f"/youtube/thumb/{READ}.jpg"
    assert read["body"]["song"]["id"] is not None
    assert by[("GET /api/youtube/video", "library", "the audio of a song of the library")]["body"]["song"]
    assert by[("GET /api/youtube/video", "library", "the video pasted for a song of the library")]["body"]["song"]
    assert by[("POST /youtube/video", "library", "a video never read")]["status"] == 202
    assert by[("POST /youtube/video", "cooling", "a video never read")]["status"] == 429
    assert by[("POST /youtube/video", "spent", "a video never read")]["status"] == 429
    assert by[("POST /youtube/video", "failed", "a video never read")]["status"] == 429
    assert by[("GET /youtube/thumb/", "library", "a thumbnail kept")]["sha256"] == hashlib.sha256(JPEG).hexdigest()
    assert by[("GET /youtube/thumb/", "library", "one kept that isn't a JPEG")]["status"] == 404
