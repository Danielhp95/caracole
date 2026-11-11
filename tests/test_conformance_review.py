"""An uncertain match reviewed on the phone: what android/server's ``ReviewRoutes`` and ``ReviewRunner`` (lane
review) answer, written for ``ReviewReplay`` to agree with.

**The library** (``build_library``): an offline Ultimate Guitar index of a few artists (``INDEX``), complete
(``ug:index:built_at``), UG's catch-alls among them, and songs of the cases' own (``SONGS``): in review with
candidates of every step (one the index no longer has, one whose names need escaping, one with more candidates than
a review lists, some that name no UG song), in review with none, not found with and without search hits, matched,
ignored, and an artist with other songs (one under a second artist's name) that an ``[alias]`` matches; its
overrides.toml (``OVERRIDES``) as the phone holds it too (``phone_overrides``,
``test_conformance_overrides.rows_of``). Dumped whole into the vector's first record (``helpers.corpus.dump_fixture``),
which the replay loads into a fresh database for each case that writes.

**vectors/web/review.jsonl**: a header, then:

- ``{"fn": "fixture", "records": [...]}``: the library, as above;
- ``{"fn": "caracole.review.SHOWN" | "SEARCH" | "SEARCHED", "out"}`` and ``{"fn": "caracole.match.NO_ALIAS_STEPS",
  "out"}``: review.py's constants;
- ``{"fn": "caracole.review.candidates_of", "song": KEY, "out": [candidate]}``: each song's, by its key;
- ``{"fn": "caracole.review.step_words", "cand", "out"}``: why the matcher thought of a candidate, for every step;
- ``{"fn": "caracole.review.writes_alias", "song": KEY, "cand", "out"}``;
- ``{"fn": "caracole.review.search_candidates", "song": KEY, "rejected": [[artist, song]], "out": [candidate]}``:
  a song's search hits, less those rejected;
- ``{"fn": "caracole.library_page.review_choices", "song": KEY, "cands": null | [candidate], "out": [choice]}``:
  the picker's choices, of the song's own candidates or of ``cands`` (a song not found's search hits);
- ``{"fn": "GET /review", "case", "target", "out"}``: the picker's page (``review_routes.picker``, its song read
  from ``target``'s query as the route reads it), the form token ``CSRF`` and the library named ``NAME`` with the
  phone's badge (``library_name.LibraryName(NAME, "Phone")``): a refusal, ``{status, title, message}``, or ``{status,
  html}``, the page with its style (``pages.PAGE_STYLE``, the message page's, which ``message.json`` holds whole)
  left out, ``<style></style>``;
- ``{"fn": "POST /review", "case", "form": [[name, value], ...], "busy", "full", "out"}``: the form posted to
  ``review_routes.review`` over the library, to a fresh queue that runs nothing (``busy``: a request of the song's
  waits in it already; ``full``: one that holds no job), the answer a refusal or ``{status, location, job: {title,
  key, steps: [[label, [args]]], fetching, display}, phone_steps}``. ``phone_steps`` are the phone's commands for the
  job: the same ``caracole review``, and, for a pick with Fetch it now, the lookup Fetch now queues
  (``library_routes.fetch``'s ``lookup_steps`` of the song) in place of caracole serve's ``caracole fetch --song`` and
  ``caracole render --song``: the phone has neither, and its lookup matches the song, fetches it and makes its pages;
- ``{"fn": "caracole review", "case", "args", "out": {code, error, lines, overrides, songs}}``: the command as the
  queue spells it, ``caracole review --song=… --pick=…`` (or ``--none``, ``--seen=…``), run on a fresh copy of the
  library: its exit status, its last word when it fails (``commands._common.fail``'s message, which the phone's
  queue says as ``error: …``), its lines but the one naming the pages it wrote (``Wrote …``: the phone writes no
  _todo.md or index.html), and then every row of overrides.toml as the phone holds it (``rows_of``) and every song's
  match as stored that differs from the library's (``SONG_COLUMNS``, by id: the song and, with an ``[alias]``, its
  artist's songs matched again; every other song is as the fixture has it);
- ``{"fn": "POST /review, run", "case", "form", "out": {line, overrides, songs}}``: the job ``POST /review`` queues,
  run to its end on a fresh copy of the library, ``caracole review`` in-process, then the job's line as the phone's
  says it (``status.job_line`` with ``todo=None``, its song's facts ``jobs_routes.song_of``'s), and the rows as above;
- ``{"fn": "POST /review, fetching", "case", "form", "out": {running: [{command, line}], line}}``: a pick with Fetch
  it now as the phone queues it (its ``phone_steps``), on a fresh copy of the library: the job's line as each of its
  two commands starts (while ``caracole review`` runs, the lookup's first stage's: ``status.py`` reads a job with a
  lookup by its stages), ``caracole review`` run in-process and the lookup ended at once with nothing said, then the
  job's line once it is over.

Stamps: the library's writers take ``STAMP``; what the command writes takes the clock's time (``matched_at``,
``updated_at``), which no record holds.

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_review.py``.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from helpers.corpus import VECTORS, check, dump_fixture, jsonl

from caracole import db

MADE_BY = "tests/test_conformance_review.py"
REVIEW = VECTORS / "web" / "review.jsonl"
STAMP = "2026-11-03T10:00:00Z"
NAME = "Songs & Co"  # the library's name, as a sync gave it to the phone
BADGE = "Phone"
CSRF = "tok"
SONG_COLUMNS = ("key", "status", "review", "match_decision", "match_step", "match_score", "match_artist_key",
                "match_song_key", "match_candidates", "ug_dirty")

INDEX = (  # tab id, artist key, song key, type
    (101, "radiohead", "creep", "chords"), (102, "radiohead", "creep", "chords"), (103, "radiohead", "creep", "tabs"),
    (104, "radiohead", "creep-acoustic", "tabs"), (105, "radiohead", "karma-police", "chords"),
    (106, "radiohead", "high-and-dry", "chords"), (107, "radiohead", "lucky", "chords"),
    (108, "radio-head", "lucky", "chords"),
    (201, "soda-stereo", "persiana-americana", "chords"), (202, "soda-stereo", "persiana", "chords"),
    (203, "soda-stereo", "de-musica-ligera", "chords"), (204, "soda-stereo", "te-para-tres", "chords"),
    (205, "soda-stereo", "de-musica-ligera", "tabs"),
    (301, "jeff-buckley", "hallelujah", "chords"),
    (401, "misc-musicals", "epic-the-musical-not-sorry-for-loving-you", "chords"),
    (402, "misc-unsigned-bands", "heroes-del-silencio-entre-dos-tierras", "chords"),
    (501, "coldplay", "yellow", "chords"), (502, "coldplay", "the-scientist", "chords"),
    (601, "oasis", "wonderwall", "chords"),
    (701, "bob-marley", "is-this-love", "chords"),
    (801, "cafe-tacvba", "eres", "chords"),
    (901, "the-beatles", "yesterday-1", "chords"), (902, "the-beatles", "yesterday-2", "chords"),
    (110, "radiohead", "paranoid-android", "chords"), (111, "radio-head", "paranoid-android", "chords"),
)


def _cands(*rows: tuple[str, str | None, float | None]) -> list[dict[str, Any]]:
    """Stored candidates, as match_all stores them: each ref, its step and score."""
    out = []
    for ref, step, score in rows:
        artist, _, song = ref.partition("/")
        cand: dict[str, Any] = {"artist_key": artist, "song_key": song, "score": score}
        if step is not None:
            cand["step"] = step
        out.append(cand)
    return out


BEATLES = [  # more than a review lists, some naming no UG song, a step unknown, none, a score none
    *_cands(("the-beatles/yesterday-1", "fuzzy_title", 89.0), ("the-beatles/yesterday-2", "word_title", 88.5)),
    {"artist_key": "", "song_key": "yesterday-x", "score": 88.0, "step": "fuzzy_title"},
    {"artist_key": "the-beatles", "score": 87.0, "step": "fuzzy_title"},
    *_cands(("the-beatles/yesterday-3", "mystery", 86.5), ("the-beatles/yesterday-4", None, 86.0),
            ("the-beatles/yesterday-5", "fuzzy_title", None), ("the-beatles/yesterday-6", "fuzzy_title", 84.5),
            ("the-beatles/yesterday-7", "fuzzy_title", 84.0), ("the-beatles/yesterday-8", "fuzzy_title", 83.5),
            ("the-beatles/yesterday-9", "fuzzy_title", 83.0), ("the-beatles/yesterday-10", "fuzzy_title", 82.5)),
]

SONGS = (  # artist, title, artists (None: the artist alone), decision, candidates
    ("Radiohead", "Creep", None, "review",
     _cands(("radiohead/creep", "fuzzy_title", 88.0), ("radiohead/creep-acoustic", "word_title", 80.0))),
    ("Soda", "Persiana Americana", None, "review",
     _cands(("soda-stereo/persiana-americana", "fuzzy_artist", 82.0), ("soda-stereo/persiana", "fuzzy_artist", 76.0))),
    ("Soda", "De Musica Ligera", None, "not_found", []),
    ("Gustavo Cerati", "Te Para Tres", ["Gustavo Cerati", "Soda"], "not_found", []),
    ("Someone", "Hallelujah", None, "review", _cands(("jeff-buckley/hallelujah", "title_only", 100.0))),
    ("epic", "I'm not sorry for loving you", None, "review",
     _cands(("misc-musicals/epic-the-musical-not-sorry-for-loving-you", "catch_all", 94.1))),
    ("Coldplya", "Yellow", None, "review", _cands(("coldplay/yellow", "typo_artist", 100.0))),
    ("Radio Head", "Crep", None, "not_found", []),
    ("Queen", "Bohemian Rhapsody", None, "review", []),
    ("Oasis", "Wonderwall", None, "accept", _cands(("oasis/wonderwall", "exact", 100.0))),
    ("Café Tacvba", "Eres", None, "review", _cands(("cafe-tacvba/eres", "fuzzy_title", 85.0))),
    ("Héroes del Silencio", "Entre Dos Tierras", None, "review",
     _cands(("misc-unsigned-bands/heroes-del-silencio-entre-dos-tierras", "catch_all", 90.0),
            ("heroes/entre-dos-tierras", "title_only", 86.5))),
    ("<b>Evil</b>", 'Song "<script>alert(1)</script>"', None, "review", _cands(("evil/song", "fuzzy_title", 80.0))),
    ("Zyxwv", "Qqqq Jjjj", None, "not_found", []),
    ("Bob Marley & The Wailers", "Is This Love", None, "review",
     _cands(("bob-marley/is-this-love", "fuzzy_title", 88.0))),
    ("Radiohead", "Lucky", None, "review",
     _cands(("radiohead/lucky", "fuzzy_title", 86.0), ("radio-head/lucky", "fuzzy_artist", 80.0))),
    ("The Beatles", "Yesterday", None, "review", BEATLES),
    # matched before radio-head's tab was in the index: rejected, the rematch leaves it in review with that one
    ("Radiohead", "Paranoid", None, "review", _cands(("radiohead/paranoid-android", "word_title", 85.3))),
)

OVERRIDES = """\
[alias]
# UG files them under two names
"Bob Marley & The Wailers" = ["bob-marley", "bob-marley-the-wailers"]

[reject]
"Radio Head - Crep" = ["radiohead/creep-acoustic"]
"Radiohead - Lucky" = ["radiohead/lucky"]

[ignore]
songs = ["Café Tacvba - Eres"]
"""


# --- the library ---------------------------------------------------------------------------------------------------


def _config(where: Path) -> Path:
    where.mkdir(parents=True, exist_ok=True)
    path = where / "caracole.toml"
    path.write_text(f'library_dir = "{where / "lib"}"\nmusic_dir = "{where / "music"}"\n'
                    f'state_dir = "{where / "state"}"\ncache_dir = "{where / "cache"}"\n', encoding="utf-8")
    return path


def build_library(conn: sqlite3.Connection, cfg) -> dict[str, Any]:
    """The cases' library in ``conn`` (a fresh database), its overrides.toml written to ``cfg``'s and held as the
    phone's rows too; the songs by their title."""
    from conftest import add_song
    from helpers.corpus import phone_schema
    from test_conformance_overrides import rows_of

    from caracole.songs import get_song

    conn.executemany("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) VALUES "
                     "(?, ?, ?, ?, '1', ?, ?)",
                     [(tab, artist, song, kind, STAMP, f"{artist}/{song}-{kind}-{tab}")
                      for tab, artist, song, kind in INDEX])
    conn.execute("INSERT INTO kv (key, value) VALUES ('ug:index:built_at', ?)", (STAMP,))
    songs = {}
    for n, (artist, title, artists, decision, cands) in enumerate(SONGS):
        song = add_song(conn, artist, title, artists=artists, added_at=f"2026-10-02T00:{n:02d}:00Z")
        accepted = decision == "accept"
        first = cands[0] if cands else {}
        conn.execute("UPDATE songs SET match_decision = ?, match_step = ?, match_score = ?, match_artist_key = ?, "
                     "match_song_key = ?, match_candidates = ?, matched_at = ?, review = ?, status = ? WHERE id = ?",
                     (decision, first.get("step") if accepted else None, 100.0 if accepted else None,
                      first.get("artist_key") if accepted else None, first.get("song_key") if accepted else None,
                      json.dumps(cands), STAMP, int(decision == "review"), "wanted", song.id))
        songs[title] = song.id
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (STAMP, STAMP))
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(OVERRIDES, encoding="utf-8")
    phone_schema(conn)
    for row in rows_of(cfg.overrides_file):
        conn.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)",
                     (row["tbl"], row["key"], row["written"], row["value"]))
    return {title: get_song(conn, sid) for title, sid in songs.items()}


@contextmanager
def _library(where: Path) -> Iterator[tuple[Path, Any, sqlite3.Connection, dict[str, Any]]]:
    """A config file over ``where`` and its database with the cases' library: (its path, cfg, conn, songs by
    title)."""
    from caracole.config import load_config

    path = _config(where)
    cfg = load_config(path, env={"HOME": str(where / "home")})
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    with closing(db.connect(cfg.db_path)) as conn:
        songs = build_library(conn, cfg)
        yield path, cfg, conn, songs


def _app(cfg, *, full: bool = False, runner=None):
    from caracole.library_name import LibraryName
    from caracole.web.app import WebApp
    from caracole.web.jobs import JobQueue

    def nowhere(args, emit):  # nothing runs: the queue is never started
        raise AssertionError(f"a route ran {args}")

    queue = JobQueue(runner or nowhere, limit=0 if full else 20)
    app = WebApp(cfg, queue, allowed=frozenset({"localhost"}), csrf=CSRF, searches_lacuerda=False,
                 searches_youtube=False)
    app.library_name = LibraryName(NAME, BADGE)
    return app


def _matches(conn: sqlite3.Connection, before: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Every song's match as stored, by id; with ``before`` (the library's), those that differ from it alone."""
    cursor = conn.execute(f"SELECT id, {', '.join(SONG_COLUMNS)} FROM songs ORDER BY id")
    names = [d[0] for d in cursor.description]
    rows = [dict(zip(names, row)) for row in cursor.fetchall()]
    return [r for r in rows if before is None or r not in before]


def _overrides(cfg) -> list[dict[str, str]]:
    from test_conformance_overrides import rows_of

    return rows_of(cfg.overrides_file)


# --- review.py's rules ---------------------------------------------------------------------------------------------


def rules(cfg, conn: sqlite3.Connection, songs: dict[str, Any]) -> list[dict[str, Any]]:
    from caracole import match, review
    from caracole.library_page import review_choices
    from caracole.overrides import load_overrides

    out: list[dict[str, Any]] = [{"fn": f"caracole.review.{name}", "out": getattr(review, name)}
                                 for name in ("SHOWN", "SEARCH", "SEARCHED")]
    out.append({"fn": "caracole.match.NO_ALIAS_STEPS", "out": list(match.NO_ALIAS_STEPS)})
    for song in songs.values():
        out.append({"fn": "caracole.review.candidates_of", "song": song.key, "out": review.candidates_of(song)})
    steps = [review.SEARCH, *review._STEP_WORDS, "catch_all", "mystery", None]
    for step in dict.fromkeys(steps):
        out.append({"fn": "caracole.review.step_words", "cand": {"artist_key": "a", "song_key": "b", "step": step},
                    "out": review.step_words({"artist_key": "a", "song_key": "b", "step": step})})
    for catch_all in sorted(match.PERFORMER_CATCH_ALLS | {"misc-musicals"}):
        cand = {"artist_key": catch_all, "song_key": "s", "step": "catch_all"}
        out.append({"fn": "caracole.review.step_words", "cand": cand, "out": review.step_words(cand)})
    out.append({"fn": "caracole.review.step_words", "cand": {"artist_key": "a", "song_key": "b"},
                "out": review.step_words({"artist_key": "a", "song_key": "b"})})
    aliases = [  # song, candidate
        ("Persiana Americana", {"artist_key": "soda-stereo", "song_key": "persiana", "step": "fuzzy_artist"}),
        ("Creep", {"artist_key": "radiohead", "song_key": "creep", "step": "fuzzy_title"}),
        ("Hallelujah", {"artist_key": "jeff-buckley", "song_key": "hallelujah", "step": "title_only"}),
        ("I'm not sorry for loving you", {"artist_key": "misc-musicals", "song_key": "x", "step": "catch_all"}),
        ("Crep", {"artist_key": "radiohead", "song_key": "creep", "step": review.SEARCH}),
        ("Yellow", {"artist_key": "coldplay", "song_key": "yellow", "step": "typo_artist"}),
        ("Is This Love", {"artist_key": "bob-marley", "song_key": "is-this-love", "step": "fuzzy_title"}),
        ("Is This Love", {"artist_key": "bob-marley-the-wailers", "song_key": "is-this-love", "step": "alias"}),
        ("Yesterday", {"artist_key": "beatles", "song_key": "yesterday"}),
        ("Entre Dos Tierras", {"artist_key": "heroes-del-silencio", "song_key": "x", "step": None}),
    ]
    for title, cand in aliases:
        out.append({"fn": "caracole.review.writes_alias", "song": songs[title].key, "cand": cand,
                    "out": review.writes_alias(songs[title], cand)})
    overrides = load_overrides(cfg.overrides_file)
    for song in songs.values():
        rejected = sorted(overrides.reject.get(song.key, frozenset()))
        for given in ({*rejected}, set()) if rejected else (set(),):
            out.append({"fn": "caracole.review.search_candidates", "song": song.key,
                        "rejected": sorted([list(r) for r in given]),
                        "out": review.search_candidates(conn, song, rejected=given)})
    for song in songs.values():
        out.append({"fn": "caracole.library_page.review_choices", "song": song.key, "cands": None,
                    "out": review_choices(conn, song)})
    crep = songs["Crep"]
    hits = review.search_candidates(conn, crep, rejected=overrides.reject.get(crep.key, frozenset()))
    assert hits, "Crep has search hits"
    out.append({"fn": "caracole.library_page.review_choices", "song": crep.key, "cands": hits,
                "out": review_choices(conn, crep, hits)})
    return out


# --- the routes ----------------------------------------------------------------------------------------------------


def picks(cfg, songs: dict[str, Any]) -> list[dict[str, Any]]:
    """GET /review: each song's picker, and every refusal."""
    from caracole.web import pages, review_routes
    from caracole.web.app import Request
    from caracole.web.pages import Refused

    route = next(r for r in review_routes.ROUTES if r.method == "GET")
    app = _app(cfg)
    out = []

    def page(case: str, target: str) -> None:
        try:
            response = route.answer(app, Request("GET", target, {}))
        except Refused as e:
            said: dict[str, Any] = {"status": e.status, "title": e.title, "message": e.message}
        else:
            html = response.body.decode("utf-8")
            assert html.count(pages.PAGE_STYLE) == 1
            assert dict(response.headers)["Content-Security-Policy"] == pages.PAGE_CSP
            said = {"status": response.status, "html": html.replace(pages.PAGE_STYLE, "")}
        out.append({"fn": "GET /review", "case": case, "target": target, "out": said})

    for title, song in songs.items():
        page(f"the picker of {title}", f"/review?song={song.id}")
    creep = songs["Creep"]
    page("no song", "/review")
    page("an empty song", "/review?song=")
    page("a song that is no number", "/review?song=x")
    page("an id no song has", "/review?song=999")
    page("an id past SQLite's", "/review?song=99999999999999999999")
    page("an id with spaces", f"/review?song=%20{creep.id}%20")
    page("an id given twice", f"/review?song={creep.id}&song=999")
    return out


def _posted(cfg, conn, case: str, form: list[tuple[str, str]], *, busy: bool = False,
            full: bool = False) -> dict[str, Any]:
    from caracole.songs import find_song
    from caracole.web import review_routes
    from caracole.web.jobs import lookup_steps, review_steps
    from caracole.web.pages import Refused

    app = _app(cfg, full=full)
    asked = dict(form)
    if busy:
        song = conn.execute("SELECT key, artist, title FROM songs WHERE id = ?", (int(asked["song"]),)).fetchone()
        app.queue.submit(f"Add {song[1]} - {song[2]}", song[0], [("Adding to the library",
                                                                 ("add", "--", song[1], song[2]))])
    try:
        response = review_routes.review(app, asked)
    except Refused as e:
        said: dict[str, Any] = {"status": e.status, "title": e.title, "message": e.message}
    else:
        jobs = [j for j in app.queue.snapshot() if j.title.startswith(("Pick ", "None of these"))]
        assert len(jobs) == 1, (case, jobs)
        job = jobs[0]
        steps = [[s.label, list(s.args)] for s in job.steps]
        song = find_song(conn, job.song_key)
        review = [[label, list(args)] for label, args in
                  review_steps(song.display, pick=asked["pick"].strip() if asked["pick"].strip() != "none" else None,
                               seen=[] if asked["pick"].strip() != "none" else asked["shown"].split())]
        phone = review + ([[label, list(args)] for label, args in lookup_steps(song.artist, song.title)]
                          if job.fetching else [])
        assert steps[:1] == review, (steps, review)
        said = {"status": response.status, "location": dict(response.headers).get("Location"),
                "job": {"title": job.title, "key": job.song_key, "steps": steps, "fetching": job.fetching,
                        "display": job.display},
                "phone_steps": phone}
    return {"fn": "POST /review", "case": case, "form": [list(f) for f in form], "busy": busy, "full": full,
            "out": said}


def answers(cfg, conn, songs: dict[str, Any]) -> list[dict[str, Any]]:
    """POST /review: every answer and every refusal, before anything runs."""
    from caracole.overrides import load_overrides
    from caracole.review import search_candidates

    creep, persiana, crep = songs["Creep"], songs["Persiana Americana"], songs["Crep"]
    shown = "radiohead/creep radiohead/creep-acoustic"
    hits = " ".join(f"{c['artist_key']}/{c['song_key']}"
                    for c in search_candidates(conn, crep, rejected=load_overrides(cfg.overrides_file).reject[crep.key]))
    out = []
    a = out.append
    s = str
    a(_posted(cfg, conn, "a pick, fetched now", [("song", s(creep.id)), ("pick", "radiohead/creep"), ("shown", shown),
                                                 ("fetch", "1")]))
    a(_posted(cfg, conn, "a pick, fetch on", [("song", s(creep.id)), ("pick", "radiohead/creep-acoustic"),
                                              ("shown", shown), ("fetch", "on")]))
    a(_posted(cfg, conn, "a pick, fetch yes, spaced", [("song", f" {creep.id} "), ("pick", "  radiohead/creep "),
                                                       ("shown", f"  {shown.replace(' ', '   ')} "), ("fetch", "yes")]))
    a(_posted(cfg, conn, "a pick, fetch that isn't one", [("song", s(creep.id)), ("pick", "radiohead/creep"),
                                                          ("shown", shown), ("fetch", "true")]))
    a(_posted(cfg, conn, "a pick, not fetched", [("song", s(creep.id)), ("pick", "radiohead/creep"), ("shown", shown)]))
    a(_posted(cfg, conn, "a pick of another artist's, fetched now",
              [("song", s(persiana.id)), ("pick", "soda-stereo/persiana-americana"),
               ("shown", "soda-stereo/persiana-americana soda-stereo/persiana"), ("fetch", "1")]))
    a(_posted(cfg, conn, "none of these, fetch asked", [("song", s(creep.id)), ("pick", "none"), ("shown", shown),
                                                        ("fetch", "1")]))
    a(_posted(cfg, conn, "none of these", [("song", s(creep.id)), ("pick", " none "), ("shown", shown)]))
    a(_posted(cfg, conn, "a search hit, fetched now", [("song", s(crep.id)), ("pick", hits.split()[0]),
                                                       ("shown", hits), ("fetch", "1")]))
    a(_posted(cfg, conn, "a search hit, not fetched", [("song", s(crep.id)), ("pick", hits.split()[-1]),
                                                       ("shown", hits)]))
    a(_posted(cfg, conn, "nine of more candidates", [("song", s(songs["Yesterday"].id)),
                                                     ("pick", "the-beatles/yesterday-10"),
                                                     ("shown", " ".join(c["ref"] for c in _choices(conn, songs, "Yesterday")))]))
    # refusals
    a(_posted(cfg, conn, "no song", [("pick", "radiohead/creep"), ("shown", shown)]))
    a(_posted(cfg, conn, "a song that is no number", [("song", "x"), ("pick", "radiohead/creep"), ("shown", shown)]))
    a(_posted(cfg, conn, "an id no song has", [("song", "999"), ("pick", "radiohead/creep"), ("shown", shown)]))
    a(_posted(cfg, conn, "an id past SQLite's", [("song", "99999999999999999999"), ("pick", "radiohead/creep"),
                                                 ("shown", shown)]))
    a(_posted(cfg, conn, "no pick", [("song", s(creep.id)), ("pick", ""), ("shown", shown)]))
    a(_posted(cfg, conn, "a pick of spaces", [("song", s(creep.id)), ("pick", "   "), ("shown", shown)]))
    a(_posted(cfg, conn, "no candidate's", [("song", s(creep.id)), ("pick", "radiohead/high-and-dry"),
                                            ("shown", shown)]))
    a(_posted(cfg, conn, "the candidates changed", [("song", s(creep.id)), ("pick", "radiohead/creep"),
                                                    ("shown", "radiohead/creep")]))
    a(_posted(cfg, conn, "the candidates in another order", [("song", s(creep.id)), ("pick", "radiohead/creep"),
                                                             ("shown", "radiohead/creep-acoustic radiohead/creep")]))
    a(_posted(cfg, conn, "none shown", [("song", s(creep.id)), ("pick", "none"), ("shown", "")]))
    a(_posted(cfg, conn, "none of a search's hits", [("song", s(crep.id)), ("pick", "none"), ("shown", hits)]))
    a(_posted(cfg, conn, "a search with nothing to show", [("song", s(songs["Qqqq Jjjj"].id)), ("pick", "none"),
                                                           ("shown", "")]))
    a(_posted(cfg, conn, "a song that needs no review", [("song", s(songs["Wonderwall"].id)),
                                                         ("pick", "oasis/wonderwall"), ("shown", "oasis/wonderwall")]))
    a(_posted(cfg, conn, "a review with no candidates", [("song", s(songs["Bohemian Rhapsody"].id)), ("pick", "none"),
                                                         ("shown", "")]))
    a(_posted(cfg, conn, "an ignored song", [("song", s(songs["Eres"].id)), ("pick", "cafe-tacvba/eres"),
                                             ("shown", "cafe-tacvba/eres")]))
    a(_posted(cfg, conn, "a request of the song's waits", [("song", s(creep.id)), ("pick", "radiohead/creep"),
                                                           ("shown", shown), ("fetch", "1")], busy=True))
    a(_posted(cfg, conn, "a full queue", [("song", s(creep.id)), ("pick", "radiohead/creep"), ("shown", shown)],
              full=True))
    return out


def _choices(conn, songs, title: str) -> list[dict[str, Any]]:
    from caracole.library_page import review_choices

    return review_choices(conn, songs[title])


# --- the command, and the job ----------------------------------------------------------------------------------------


def _cli(path: Path, args: list[str]) -> dict[str, Any]:
    """``caracole --config PATH`` with ``args`` (after ``review``), in-process: its status, its last word when it
    fails, its lines but the one that names the pages it wrote."""
    from typer.testing import CliRunner

    from caracole.cli import build_app
    from caracole.commands import library

    said: list[str] = []
    real = library.fail

    def fail(message: str, code: int = 1):
        said.append(message)
        real(message, code)

    with mock.patch.object(library, "fail", fail):
        result = CliRunner().invoke(build_app(), ["--config", str(path), *args])
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        raise result.exception
    lines = [line for line in result.stdout.splitlines() if not line.startswith("Wrote ")]
    assert result.exit_code == 0 or said, (args, result.output)
    return {"code": result.exit_code, "error": said[-1] if result.exit_code else None, "lines": lines}


RUNS = (  # case, args after `caracole review`
    ("a pick of the artist's own", ["--song=Radiohead - Creep", "--pick=radiohead/creep"]),
    ("a pick by its number", ["--song=Radiohead - Creep", "--pick=2"]),
    ("a pick by its number, spaced", ["--song=Radiohead - Creep", "--pick= 1 "]),
    ("a pick of another artist's: its [alias], the artist's songs matched again",
     ["--song=Soda - Persiana Americana", "--pick=soda-stereo/persiana-americana"]),
    ("a title-only pick: no [alias]", ["--song=Someone - Hallelujah", "--pick=1"]),
    ("a catch-all's pick: no [alias]", ["--song=epic - I'm not sorry for loving you", "--pick=1"]),
    ("a performer catch-all's pick: no [alias]", ["--song=Héroes del Silencio - Entre Dos Tierras", "--pick=1"]),
    ("a misspelt artist's pick: its [alias]", ["--song=Coldplya - Yellow", "--pick=coldplay/yellow"]),
    ("an [alias] there already", ["--song=Bob Marley & The Wailers - Is This Love", "--pick=1"]),
    ("a pick the index no longer has", ['--song=<b>Evil</b> - Song "<script>alert(1)</script>"',
                                        "--pick=evil/song"]),
    ("the ninth of more", ["--song=The Beatles - Yesterday", "--pick=9"]),
    ("none of these, those seen", ["--song=Radiohead - Creep", "--none", "--seen=radiohead/creep"]),
    ("none of these, every candidate", ["--song=Radiohead - Creep", "--none"]),
    ("none of these, beside a [reject]", ["--song=Radiohead - Lucky", "--none", "--seen=radiohead/lucky",
                                          "--seen=radio-head/lucky"]),
    ("none of these, seen ones no longer listed", ["--song=Radiohead - Creep", "--none",
                                                   "--seen=radiohead/high-and-dry"]),
    ("none of these, another left in review", ["--song=Radiohead - Paranoid", "--none"]),
    ("a search hit picked", ["--song=Radio Head - Crep", "--pick=radiohead/creep"]),
    ("a search hit by its number", ["--song=Radio Head - Crep", "--pick=1"]),
    ("a search hit [reject] leaves out", ["--song=Radio Head - Crep", "--pick=radiohead/creep-acoustic"]),
    # refusals
    ("none of these for a song not found", ["--song=Radio Head - Crep", "--none"]),
    ("none of these with no candidates", ["--song=Queen - Bohemian Rhapsody", "--none"]),
    ("a pick with no candidates", ["--song=Queen - Bohemian Rhapsody", "--pick=1"]),
    ("a song that needs no review", ["--song=Oasis - Wonderwall", "--pick=1"]),
    ("an ignored song", ["--song=Café Tacvba - Eres", "--pick=1"]),
    ("a song not found with no hit", ["--song=Zyxwv - Qqqq Jjjj", "--pick=1"]),
    ("no candidate of that number", ["--song=Radiohead - Creep", "--pick=3"]),
    ("no candidate of that number, nought", ["--song=Radiohead - Creep", "--pick=0"]),
    ("past the ninth", ["--song=The Beatles - Yesterday", "--pick=10"]),
    ("no candidate of that name", ["--song=Radiohead - Creep", "--pick=radiohead/high-and-dry"]),
    ("a name that isn't Artist - Title", ["--song=no dash", "--pick=1"]),
    ("a song not in the library", ["--song=Radiohead - Paranoid Android", "--pick=1"]),
    ("a song spelled otherwise", ["--song=radiohead - creep", "--pick=1"]),
    ("--pick with no song", ["--pick=1"]),
    ("--none with no song", ["--none"]),
    ("--pick and --none", ["--song=Radiohead - Creep", "--pick=1", "--none"]),
    ("--seen without --none", ["--song=Radiohead - Creep", "--pick=1", "--seen=radiohead/creep"]),
    ("--seen that isn't a UG song", ["--song=Radiohead - Creep", "--none", "--seen=radiohead"]),
    ("--seen with two slashes", ["--song=Radiohead - Creep", "--none", "--seen=a/b/c"]),
    ("--seen with nothing after its slash", ["--song=Radiohead - Creep", "--none", "--seen=radiohead/ "]),
)


def runs(where: Path) -> list[dict[str, Any]]:
    out = []
    for n, (case, args) in enumerate(RUNS):
        with _library(where / f"run-{n}") as (path, cfg, conn, _songs):
            before = _matches(conn)
            said = _cli(path, ["review", *args])
            said |= {"overrides": _overrides(cfg), "songs": _matches(conn, before)}
        out.append({"fn": "caracole review", "case": case, "args": ["review", *args], "out": said})
    return out


def _run_job(path: Path):
    """A queue runner that runs each command in-process, as caracole serve's child process would: its lines, then
    its last word as the queue reads it."""

    def runner(args, emit):
        said = _cli(path, list(args))
        for line in said["lines"]:
            emit(line)
        if said["code"]:
            emit(f"error: {said['error']}")
        return said["code"]

    return runner


JOBS = (  # case, song's title, pick, shown (None: its candidates)
    ("a pick", "Creep", "radiohead/creep", None),
    ("a pick of another artist's", "Persiana Americana", "soda-stereo/persiana-americana", None),
    ("a pick of a title alone", "Hallelujah", "jeff-buckley/hallelujah", None),
    ("none of these", "Creep", "none", None),
    ("none of these, one left", "Lucky", "none", None),
    ("a search hit", "Crep", "radiohead/creep", None),
    ("none of these, another left", "Paranoid", "none", None),
)


def jobs(where: Path) -> list[dict[str, Any]]:
    from caracole.overrides import load_overrides
    from caracole.review import search_candidates
    from caracole.web import jobs_routes, review_routes
    from caracole.web.status import job_line

    out = []
    for n, (case, title, pick, shown) in enumerate(JOBS):
        with _library(where / f"job-{n}") as (path, cfg, conn, songs):
            song = songs[title]
            if shown is None:
                cands = (_choices(conn, songs, title) if song.review else
                         [{"ref": f"{c['artist_key']}/{c['song_key']}"} for c in
                          search_candidates(conn, song, rejected=load_overrides(cfg.overrides_file).reject.get(
                              song.key, frozenset()))])
                shown = " ".join(c["ref"] for c in cands)
            form = [("song", str(song.id)), ("pick", pick), ("shown", shown)]
            before = _matches(conn)
            app = _app(cfg, runner=_run_job(path))
            review_routes.review(app, dict(form))
            app.queue.run_pending()
            [job] = app.queue.snapshot()
            assert job.state == "done", (case, [(s.state, s.output) for s in job.steps])
            _, facts = jobs_routes.song_of(app, conn, load_overrides(cfg.overrides_file), job)
            line = job_line(job, facts, todo=None)
            said = {"line": line.as_json(), "overrides": _overrides(cfg), "songs": _matches(conn, before)}
        out.append({"fn": "POST /review, run", "case": case, "form": [list(f) for f in form], "out": said})
    return out


FETCHING = (  # case, song's title, pick
    ("a pick, fetched now", "Creep", "radiohead/creep"),
    ("a pick of another artist's, fetched now", "Persiana Americana", "soda-stereo/persiana-americana"),
    ("a search hit, fetched now", "Crep", "radiohead/creep"),
)


def fetching(where: Path) -> list[dict[str, Any]]:
    """A pick with Fetch it now, as the phone queues it: its ``phone_steps`` (``caracole review``, then the lookup Fetch
    now queues) under the title and key ``POST /review`` gives it, run by a queue whose runner says the job's line as
    each command starts (``status.job_line``, ``todo=None``: while ``caracole review`` runs, the lookup's stages wait,
    so its first one's), runs ``caracole review`` in-process and ends the lookup at once, having said nothing (no site
    is asked); then the job's line once it is over."""
    from caracole.overrides import load_overrides
    from caracole.review import search_candidates
    from caracole.web import jobs_routes
    from caracole.web.jobs import lookup_steps, review_steps
    from caracole.web.status import job_line

    out = []
    for n, (case, title, pick) in enumerate(FETCHING):
        with _library(where / f"fetching-{n}") as (path, cfg, conn, songs):
            song = songs[title]
            cands = (_choices(conn, songs, title) if song.review else
                     [{"ref": f"{c['artist_key']}/{c['song_key']}"} for c in
                      search_candidates(conn, song, rejected=load_overrides(cfg.overrides_file).reject.get(
                          song.key, frozenset()))])
            form = [("song", str(song.id)), ("pick", pick), ("shown", " ".join(c["ref"] for c in cands)),
                    ("fetch", "1")]
            running: list[dict[str, Any]] = []
            app = None

            def line_now() -> dict[str, Any]:
                [job] = app.queue.snapshot()
                _, facts = jobs_routes.song_of(app, conn, load_overrides(cfg.overrides_file), job)
                return job_line(job, facts, todo=None).as_json()

            def runner(args, emit):
                running.append({"command": args[0], "line": line_now()})
                if args[0] == "get":
                    return 0
                said = _cli(path, list(args))
                for line in said["lines"]:
                    emit(line)
                return said["code"]

            app = _app(cfg, runner=runner)
            steps = [*review_steps(song.display, pick=pick), *lookup_steps(song.artist, song.title)]
            app.submit(f"Pick {pick} for {song.display}, and fetch it", song.key, steps, fetching=True, join=False,
                       display=song.display)
            app.queue.run_pending()
            [job] = app.queue.snapshot()
            assert job.state == "done", (case, [(s.state, s.output) for s in job.steps])
            said = {"running": running, "line": line_now()}
        out.append({"fn": "POST /review, fetching", "case": case, "form": [list(f) for f in form], "out": said})
    return out


# --- the vectors ---------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> list[dict[str, Any]]:
    tmp = tmp_path_factory.mktemp("review")
    return _made(tmp)


def _made(tmp: Path) -> list[dict[str, Any]]:
    with _library(tmp / "library") as (_path, cfg, conn, songs):
        records = [{"fn": "fixture", "records": dump_fixture(conn)}, *rules(cfg, conn, songs), *picks(cfg, songs),
                   *answers(cfg, conn, songs)]
    return [*records, *runs(tmp), *jobs(tmp), *fetching(tmp)]


def test_the_vectors_are_caracole_serves_answers(made):
    check(REVIEW, jsonl(made, corpus="web/review", made_by=MADE_BY))


def _by(made, fn: str) -> dict[str, dict[str, Any]]:
    return {r["case"]: r["out"] for r in made if r["fn"] == fn}


def test_the_cases_meet_what_they_name(made):
    pages = _by(made, "GET /review")
    assert pages["the picker of Creep"]["status"] == 200
    assert "<style></style>" in pages["the picker of Creep"]["html"]
    assert "Songs &amp; Co" in pages["the picker of Creep"]["html"]
    assert pages["the picker of Crep"]["status"] == 200 and "caracole search" in pages["the picker of Crep"]["html"]
    for case, status in (("the picker of Wonderwall", 409), ("the picker of Bohemian Rhapsody", 409),
                         ("the picker of Eres", 409), ("the picker of Qqqq Jjjj", 409), ("no song", 400),
                         ("an empty song", 400), ("a song that is no number", 400), ("an id no song has", 404),
                         ("an id past SQLite's", 404)):
        assert pages[case]["status"] == status, case
    assert pages["an id with spaces"]["status"] == 200
    assert "&lt;b&gt;Evil&lt;/b&gt;" in pages['the picker of Song "<script>alert(1)</script>"']["html"]
    posts = _by(made, "POST /review")
    fetched = posts["a pick, fetched now"]
    assert [s[1][0] for s in fetched["job"]["steps"]] == ["review", "fetch", "render"]
    assert [s[1][0] for s in fetched["phone_steps"]] == ["review", "get"]
    assert posts["a pick, not fetched"]["phone_steps"] == posts["a pick, not fetched"]["job"]["steps"]
    assert not posts["none of these, fetch asked"]["job"]["fetching"]
    for case, status in (("no song", 400), ("no pick", 400), ("no candidate's", 400), ("the candidates changed", 409),
                         ("none shown", 409), ("none of a search's hits", 400), ("a song that needs no review", 409),
                         ("an ignored song", 409), ("a request of the song's waits", 409), ("a full queue", 503),
                         ("a search with nothing to show", 409), ("a review with no candidates", 409)):
        assert posts[case]["status"] == status, case
    commands = _by(made, "caracole review")
    alias = commands["a pick of another artist's: its [alias], the artist's songs matched again"]
    assert alias["code"] == 0 and any(r["tbl"] == "alias" and r["key"] == "soda" for r in alias["overrides"])
    decided = {s["key"]: s["match_decision"] for s in alias["songs"]}
    assert decided["soda/de-musica-ligera"] == "accept" and decided["gustavo-cerati/te-para-3"] == "accept"
    assert not any(r["tbl"] == "alias" for r in commands["a title-only pick: no [alias]"]["overrides"]
                   if r["key"] == "someone")
    for case in ("none of these for a song not found", "a song that needs no review", "an ignored song",
                 "no candidate of that number", "a song not in the library", "none of these with no candidates"):
        assert commands[case]["code"] == 1, case
    for case in ("a name that isn't Artist - Title", "--pick with no song", "--pick and --none",
                 "--seen without --none", "--seen that isn't a UG song"):
        assert commands[case]["code"] == 2, case
    lines = _by(made, "POST /review, run")
    assert lines["a pick"]["line"]["text"] == "Added · fetched tonight"
    assert lines["none of these, another left"]["line"]["tone"] == "review"
    for case, said in _by(made, "POST /review, fetching").items():
        assert [r["command"] for r in said["running"]] == ["review", "get"], case
        assert all(r["line"]["tone"] == "running" for r in said["running"]), case
    assert all(r["out"]["lines"] for r in made if r["fn"] == "caracole review" and r["out"]["code"] == 0)


@pytest.mark.slow
def test_the_vectors_are_the_same_on_another_run(made, tmp_path):
    assert _made(tmp_path) == made
