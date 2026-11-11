"""The library page's lookups on the phone: what android/server's ``LookupRoutes`` and ``/api/search`` (lane
lookup-routes) answer, written for ``LookupRoutesReplay`` to agree with.

**The library** (``build_library``): LaCuerda's listing of the search corpus's ``lacuerda`` fixture, harptabs.com's
artists of its ``sites`` fixture, and songs of the cases' own: a song in review that needs it first, others a
``[match]``, its artist's page or a ``[reject]`` settle, an ignored one, one matched to an Ultimate Guitar song, and
two with Ultimate Guitar's chords versions, one with versions left to keep and one with none; overrides.toml as the
phone holds it (``phone_overrides``, ``test_conformance_overrides.rows_of``). Dumped whole into the vector's first
record (``helpers.corpus.dump_fixture``), which the replay loads into a fresh database.

**vectors/web/lookup_routes.jsonl**: a header, then:

- ``{"fn": "fixture", "records": [...]}``: the library, as above;
- a record a request, ``{"fn": "POST <path>", "case", "form": [[name, value], ...], "json", "full", "rows", "now",
  "out"}``: the form posted to caracole serve's route (``search_routes.lookup``, ``lacuerda_read``, ``lacuerda_search``,
  ``harptabs_read``, ``library_routes.request`` and ``fetch``, ``versions_routes.versions_post``), asking for JSON
  (``json``) or not, to a fresh queue that runs nothing (``full``: one that holds no job, so it is full), over the
  library with ``rows`` (fixture records: each kv record the case holds otherwise than the library, and every
  ``events`` row, which the library has none of: LaCuerda's searches asked and failed, a cooldown, the hour's lookups),
  LaCuerda's gate read at ``now``. ``out`` is a refusal, ``{status, title, message}``, or what was queued, ``{status,
  location, body, job: {title, key, steps: [[label, [args]]], fetching, note, display}, wanted}``: the answer's
  status, its ``Location`` (POST /lookup's that asks for no JSON is the phone's: the request's line in the Requests
  tab, ``status.details_href``, as the phone has no /lookup page), its JSON body less the job's ``view``
  (``{job, url}``), and the job. ``wanted``: the song is new to the library, so caracole serve wrote wanted.txt
  (``library_routes.wanted_line``), whose line its ``note`` names and its queue-full refusal tells of; the phone
  writes no wanted.txt, so its note is "" then, and its queue-full words its own ("nothing was added").

**vectors/web/api_search_gate.jsonl**: a header, then ``{"fn": "caracole.web.search_routes._found_for", "fixture",
"rows", "case", "q", "now", "out": {lacuerda_search, lacuerda_unlisted}}``: over a fixture of the search corpus
(``vectors/search/fixtures/<fixture>.jsonl``) replayed with the fixture records ``rows`` after it (kv records of
LaCuerda's searches asked and failed, a cooldown, ``events`` of the hour's lookups), what /api/search says of
LaCuerda's own search (``_lacuerda_search_gate``: auto, button, failed with why, asked, spent, or none) and of a
LaCuerda page to read (``_lacuerda_unlisted``), its gate read at ``now``, with LaCuerda's search on
(``WebApp(searches_lacuerda=True)``).

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_lookup_routes.py``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from helpers.corpus import VECTORS, check, dump_fixture, jsonl, read_fixture, replay_fixture

from caracole import db
from caracole.web.pages import Refused

MADE_BY = "tests/test_conformance_lookup_routes.py"
ROUTES = VECTORS / "web" / "lookup_routes.jsonl"
GATE = VECTORS / "web" / "api_search_gate.jsonl"
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
STAMP = "2026-11-03T10:00:00Z"
SLUGGED = "https://tabs.ultimate-guitar.com/tab/los-prisioneros/tren-al-sur-chords-{}"


# --- the library ---------------------------------------------------------------------------------------------------


def _search_fixture(name: str) -> list[dict[str, Any]]:
    return read_fixture((VECTORS / "search" / "fixtures" / f"{name}.jsonl").read_text("utf-8"))


SONGS = (  # artist, title, (match_decision, step of each candidate, the candidates' keys), review
    ("Estopa", "Tu Calorro", None),
    ("Radiohead", "Creep", ("review", ["fuzzy_title", "word_title"], ["radiohead/creep", "radiohead/creep-acoustic"])),
    ("Radiohead", "Karma Police", ("review", ["fuzzy_title"], ["radiohead/karma-police"])),
    ("Soda Stereo", "Persiana Americana", ("not_found", [], [])),
    ("Café Tacvba", "Eres", None),
    ("Héroes del Silencio", "Entre Dos Tierras", ("review", ["title_only", "catch_all"],
                                                  ["misc-unsigned/entre-dos-tierras", "heroes/entre-dos-tierras"])),
    ("Radiohead", "No Surprises", ("review", ["fuzzy_title", "fuzzy_artist"],
                                   ["radiohead/no-surprises", "radio-head/no-surprises"])),
    ("Radiohead", "Lucky", ("review", ["fuzzy_title", "fuzzy_artist"], ["radiohead/lucky", "radio-head/lucky"])),
    ("Radiohead", "Paranoid Android", ("accept", ["alias"], ["radiohead-uk/paranoid-android"])),
    ("Los Prisioneros", "Tren al Sur", None),
    ("Los Prisioneros", "El Baile de los que Sobran", None),
)

OVERRIDES = """\
[match]
"Radiohead - Karma Police" = "radiohead/karma-police"

[reject]
"Radiohead - No Surprises" = ["radiohead/no-surprises", "radio-head/no-surprises"]
"Radiohead - Lucky" = ["radiohead/lucky"]

[ignore]
songs = ["Café Tacvba - Eres"]

[block]
tab_ids = [1004]
"""


def _chords(conn, song, tab: int, number: int, rating: float, votes: int) -> int:
    from caracole.versions import upsert_version

    return upsert_version(conn, provider="ug", tab_id=str(tab), song_id=song.id, slot="sheet", kind="chords",
                          rating=rating, votes=votes, version=number, label=None, url=SLUGGED.format(tab),
                          raw={"id": tab}, now=STAMP)


def build_library(conn, cfg) -> dict[str, Any]:
    """The cases' library in ``conn`` (a fresh database), its overrides.toml written to ``cfg``'s and held as the
    phone's rows too; the songs by their title."""
    from conftest import add_song
    from test_conformance_overrides import rows_of

    from caracole.library import keep_file
    from caracole.songs import get_song

    replay_fixture(conn, _search_fixture("lacuerda"))
    harp = [r for r in _search_fixture("sites")
            if r.get("table", "").startswith("harptabs_") or r.get("kv") == "harptabs:artists:keys"]
    replay_fixture(conn, harp)
    songs = {}
    for n, (artist, title, match) in enumerate(SONGS):
        song = add_song(conn, artist, title, added_at=f"2026-10-02T00:{n:02d}:00Z")
        if match is not None:
            decision, steps, keys = match
            candidates = [{"artist_key": k.split("/")[0], "song_key": k.split("/")[1], "artist": artist,
                           "title": title, "score": 88.0, "step": step} for k, step in zip(keys, steps, strict=True)]
            accepted = decision == "accept"
            conn.execute("UPDATE songs SET match_decision = ?, match_step = ?, match_score = ?, match_artist_key = ?,"
                         " match_song_key = ?, match_candidates = ?, matched_at = ?, review = ?, status = ? "
                         "WHERE id = ?",
                         (decision, steps[0] if steps else None, 100.0 if accepted else None,
                          keys[0].split("/")[0] if accepted else None, keys[0].split("/")[1] if accepted else None,
                          json.dumps(candidates), STAMP, int(decision == "review"), "wanted", song.id))
        songs[title] = get_song(conn, song.id)
    # Tren al Sur: its sheet (Ver 1) and three more chords versions, one under [block]: two left to keep. El Baile:
    # its sheet alone.
    tren = songs["Tren al Sur"]
    sheet = _chords(conn, tren, 1001, 1, 4.8, 900)
    for tab, number in ((1002, 2), (1003, 3), (1004, 4)):
        _chords(conn, tren, tab, number, 4.5, 100 - number)
    keep_file(conn, cfg.library_dir, song=tren, version_id=sheet, name="sheet.txt", data=b"[G]Tren\n", rank=1)
    baile = songs["El Baile de los que Sobran"]
    keep_file(conn, cfg.library_dir, song=baile, version_id=_chords(conn, baile, 2001, 1, 4.9, 500),
              name="sheet.txt", data=b"[Am]Baile\n", rank=1)
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (STAMP, STAMP))
    conn.execute("UPDATE files SET created_at = ?", (STAMP,))
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(OVERRIDES, encoding="utf-8")
    # replay_fixture made the phone's tables already
    for row in rows_of(cfg.overrides_file):
        conn.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)",
                     (row["tbl"], row["key"], row["written"], row["value"]))
    return {title: get_song(conn, s.id) for title, s in songs.items()}


@contextmanager
def _library(tmp: Path) -> Iterator[tuple[Any, Any, dict[str, Any]]]:
    """A config over ``tmp`` and its database with the cases' library: (cfg, conn, songs by title)."""
    from caracole.config import load_config

    cfg = load_config(None, env={"HOME": str(tmp / "home"), "STATE_DIRECTORY": str(tmp / "state"),
                                 "CACHE_DIRECTORY": str(tmp / "cache")})
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    with closing(db.connect(cfg.db_path)) as conn:
        songs = build_library(conn, cfg)
        yield cfg, conn, songs


def _app(cfg, *, full: bool = False):
    from caracole.web.app import WebApp
    from caracole.web.jobs import JobQueue

    def runner(args, emit):  # nothing runs: the queue is never started
        raise AssertionError(f"a route ran {args}")

    queue = JobQueue(runner, limit=0 if full else 20)
    return WebApp(cfg, queue, allowed=frozenset({"localhost"}), csrf="tok", searches_lacuerda=True,
                  searches_youtube=False)


@contextmanager
def _gate_at(now: datetime) -> Iterator[None]:
    """LaCuerda's gate read at ``now``, wherever a route or a search reads it."""
    from caracole import lacuerda_search

    real = lacuerda_search.gate
    with mock.patch.object(lacuerda_search, "gate", lambda cfg, conn, q, *, strong, now=None: real(
            cfg, conn, q, strong=strong, now=at)):
        at = now
        yield


# --- the requests --------------------------------------------------------------------------------------------------


def _route(path: str):
    from caracole.web import library_routes, search_routes, versions_routes

    return {
        "/lookup": lambda app, form, wants: search_routes.lookup(app, form, wants_json=wants),
        "/request": lambda app, form, wants: library_routes.request(app, form),
        "/fetch": lambda app, form, wants: library_routes.fetch(app, form),
        "/lacuerda/artist": lambda app, form, wants: search_routes.lacuerda_read(app, form, wants_json=wants),
        "/lacuerda/search": lambda app, form, wants: search_routes.lacuerda_search(app, form, wants_json=wants),
        "/harptabs/artist": lambda app, form, wants: search_routes.harptabs_read(app, form, wants_json=wants),
        "/versions/keep-more": lambda app, form, wants: versions_routes.versions_post(app, "keep-more", form),
    }[path]


def _asked(cfg, path: str, case: str, form: list[tuple[str, str]], *, wants: bool = True, full: bool = False,
           now: datetime = NOW, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One request's record: the route over a fresh queue, its answer and what it queued; ``rows``, the kv records and
    events the case holds beyond the library's (``_beyond``)."""
    rows = rows or []
    from caracole.web.status import details_href

    app = _app(cfg, full=full)
    asked = dict(form)
    wanted_before = cfg.wanted_file.read_text("utf-8") if cfg.wanted_file.exists() else ""
    try:
        with _gate_at(now):
            response = _route(path)(app, asked, wants)
    except Refused as e:
        out = {"status": e.status, "title": e.title, "message": e.message}
        if full:
            out["wanted"] = _wrote_wanted(cfg, wanted_before)
        _restore_wanted(cfg, wanted_before)
        return _record(path, case, form, wants, full, rows, now, out)
    jobs = app.queue.snapshot()
    assert len(jobs) == 1, (path, case, jobs)
    job = jobs[0]
    location = next((v for k, v in response.headers if k == "Location"), None)
    if path == "/lookup" and not wants:  # the phone's: no /lookup page, the request's line in the Requests tab
        assert location == f"/lookup?job={job.id}"
        location = f"/{details_href(job.id)}"
    body = json.loads(response.body) if response.body else None
    if isinstance(body, dict):
        body.pop("view", None)
    out = {"status": response.status, "location": location, "body": body,
           "job": {"title": job.title, "key": job.song_key, "steps": [[s.label, list(s.args)] for s in job.steps],
                   "fetching": job.fetching, "note": job.note, "display": job.display},
           "wanted": _wrote_wanted(cfg, wanted_before)}
    _restore_wanted(cfg, wanted_before)
    return _record(path, case, form, wants, full, rows, now, out)


def _wrote_wanted(cfg, before: str) -> bool:
    return (cfg.wanted_file.read_text("utf-8") if cfg.wanted_file.exists() else "") != before or \
        (before == "" and cfg.wanted_file.exists())


def _restore_wanted(cfg, before: str) -> None:
    """Every request asks over the same library: wanted.txt as it was."""
    if before:
        cfg.wanted_file.write_text(before, encoding="utf-8")
    elif cfg.wanted_file.exists():
        cfg.wanted_file.unlink()


def _record(path, case, form, wants, full, rows, now, out) -> dict[str, Any]:
    return {"fn": f"POST {path}", "case": case, "form": [list(f) for f in form], "json": wants, "full": full,
            "rows": rows, "now": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "out": out}


def _beyond(conn, base: dict[str, str]) -> list[dict[str, Any]]:
    """What the database holds beyond the library ``base`` (its kv records): each kv record that differs from it, by
    key, then every ``events`` row, as fixture records. No case takes a record of the library's away."""
    assert set(base) <= {k for (k,) in conn.execute("SELECT key FROM kv")}
    kv = [{"kv": k, "value": v} for k, v in conn.execute("SELECT key, value FROM kv ORDER BY key") if base.get(k) != v]
    cursor = conn.execute("SELECT * FROM events ORDER BY rowid")
    names = [d[0] for d in cursor.description]
    return kv + [{"table": "events", "row": dict(zip(names, tuple(row)))} for row in cursor.fetchall()]


TAB = "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"
LACUERDA = "https://acordes.lacuerda.net/estopa/tu_calorro"
HARPTABS = "https://www.harptabs.com/tab/12345/creep"
GAMETABS = "https://gametabs.net/tabs/actraiser/fillmore"


def lookups(cfg, songs) -> list[dict[str, Any]]:
    creep, karma, tren, baile = (songs[t] for t in ("Creep", "Karma Police", "Tren al Sur", "El Baile de los que Sobran"))
    persiana, eres, heroes = songs["Persiana Americana"], songs["Eres"], songs["Entre Dos Tierras"]
    surprises, lucky, calorro = songs["No Surprises"], songs["Lucky"], songs["Tu Calorro"]
    long = "x" * 301
    out = []
    a = out.append
    # POST /lookup: Get it on a search's line
    for wants in (True, False):
        a(_asked(cfg, "/lookup", "your song by its id", [("song", str(calorro.id))], wants=wants))
        a(_asked(cfg, "/lookup", "a new song by its names", [("artist", "Fito Páez"), ("title", "Mariposa Tecknicolor"),
                                                            ("album", "Circo Beat"), ("duration", "4:38")], wants=wants))
    a(_asked(cfg, "/lookup", "your song by its names, spelled otherwise", [("artist", "estopa"), ("title", "tu calorro")]))
    a(_asked(cfg, "/lookup", "your song by its id, the form's names aside",
             [("song", f" {creep.id} "), ("artist", "Other"), ("title", "Thing")]))
    a(_asked(cfg, "/lookup", "an id that is no number", [("song", "abc")]))
    a(_asked(cfg, "/lookup", "an id no song has", [("song", "9999")]))
    a(_asked(cfg, "/lookup", "one text naming a new song", [("q", "Gustavo Cerati - Crimen")]))
    a(_asked(cfg, "/lookup", "one text naming your song", [("q", "Estopa - Tu Calorro")]))
    a(_asked(cfg, "/lookup", "one text naming no artist", [("q", "zzqx")]))
    a(_asked(cfg, "/lookup", "one text too long", [("q", "a " * 300)]))
    a(_asked(cfg, "/lookup", "an Ultimate Guitar song picked, matched to your song",
             [("ug", "radiohead-uk/paranoid-android"), ("artist", "Radiohead UK"), ("title", "Paranoid Android")]))
    a(_asked(cfg, "/lookup", "an Ultimate Guitar song picked, another artist's song of your title",
             [("ug", "sodastereo/tu-calorro"), ("artist", "Sodastereo"), ("title", "Tu Calorro (Live)")]))
    a(_asked(cfg, "/lookup", "an Ultimate Guitar song picked, new",
             [("ug", "radiohead/street-spirit"), ("artist", "Radiohead"), ("title", "Street Spirit")]))
    a(_asked(cfg, "/lookup", "a pick that is no Ultimate Guitar song", [("ug", "radiohead"), ("artist", "Radiohead"),
                                                                         ("title", "Creep")]))
    a(_asked(cfg, "/lookup", "a pick with two slashes", [("ug", "a/b/c"), ("artist", "A"), ("title", "B")]))
    a(_asked(cfg, "/lookup", "an Ultimate Guitar tab picked", [("tab", TAB), ("artist", "Radiohead"), ("title", "Creep")]))
    a(_asked(cfg, "/lookup", "a tab that is no Ultimate Guitar tab", [("tab", "https://example.com/tab/1"),
                                                                       ("artist", "Radiohead"), ("title", "Creep")]))
    a(_asked(cfg, "/lookup", "a LaCuerda song picked", [("lacuerda", LACUERDA), ("artist", "Estopa"),
                                                         ("title", "Tu calorro")]))
    a(_asked(cfg, "/lookup", "a LaCuerda pick that isn't one", [("lacuerda", "https://acordes.lacuerda.net/tabs/e/"),
                                                                 ("artist", "Estopa"), ("title", "Tu calorro")]))
    a(_asked(cfg, "/lookup", "a harptabs.com tab picked", [("harptabs", HARPTABS), ("artist", "Radiohead"),
                                                           ("title", "Creep")]))
    a(_asked(cfg, "/lookup", "a harptabs.com pick that isn't one", [("harptabs", "https://www.harptabs.com/x"),
                                                                    ("artist", "Radiohead"), ("title", "Creep")]))
    a(_asked(cfg, "/lookup", "a gametabs.net tab picked", [("gametabs", GAMETABS), ("artist", "Actraiser"),
                                                           ("title", "Fillmore")]))
    a(_asked(cfg, "/lookup", "a gametabs.net pick that isn't one", [("gametabs", "https://gametabs.net/x"),
                                                                    ("artist", "Actraiser"), ("title", "Fillmore")]))
    for name, limit in (("ug", 300), ("tab", 600), ("lacuerda", 600), ("harptabs", 600), ("gametabs", 600)):
        a(_asked(cfg, "/lookup", f"a {name} too long", [(name, "y" * (limit + 1)), ("artist", "A"), ("title", "B")]))
    a(_asked(cfg, "/lookup", "an artist too long", [("artist", "x" * 201), ("title", "B")]))
    a(_asked(cfg, "/lookup", "a title too long", [("artist", "A"), ("title", long)]))
    a(_asked(cfg, "/lookup", "an album too long", [("artist", "A"), ("title", "B"), ("album", long)]))
    a(_asked(cfg, "/lookup", "no title", [("artist", "A")]))
    a(_asked(cfg, "/lookup", "a length that isn't one", [("artist", "A"), ("title", "B"), ("duration", "abc")]))
    a(_asked(cfg, "/lookup", "a length out of range", [("artist", "A"), ("title", "B"), ("duration", "4:75")]))
    a(_asked(cfg, "/lookup", "an artist wanted.txt can't hold", [("artist", "AC - DC"), ("title", "Thunder")]))
    a(_asked(cfg, "/lookup", "a full queue, your song", [("song", str(calorro.id))], full=True))
    a(_asked(cfg, "/lookup", "a full queue, a new song", [("artist", "Fito Páez"), ("title", "Mariposa Tecknicolor")],
             full=True))
    # POST /request: the request form; with fetch, looked up now
    a(_asked(cfg, "/request", "Add", [("artist", "Fito Páez"), ("title", "Mariposa Tecknicolor"), ("album", "Circo Beat")]))
    a(_asked(cfg, "/request", "Fetch now", [("artist", "Fito Páez"), ("title", "Mariposa Tecknicolor"),
                                            ("duration", "278"), ("fetch", "1")]))
    a(_asked(cfg, "/request", "Fetch now, your song", [("artist", "Estopa"), ("title", "Tu Calorro"), ("fetch", "on")]))
    a(_asked(cfg, "/request", "Fetch now with a LaCuerda pick", [("artist", "Estopa"), ("title", "Tu calorro"),
                                                                 ("lacuerda", LACUERDA), ("fetch", "yes")]))
    a(_asked(cfg, "/request", "Add with a LaCuerda pick", [("artist", "Estopa"), ("title", "Fuego"),
                                                           ("lacuerda", "https://acordes.lacuerda.net/estopa/fuego")]))
    a(_asked(cfg, "/request", "a LaCuerda pick that isn't one", [("artist", "Estopa"), ("title", "Fuego"),
                                                                 ("lacuerda", "https://example.com/estopa/fuego")]))
    a(_asked(cfg, "/request", "an Ultimate Guitar pick too long, which a request never reads",
             [("artist", "Estopa"), ("title", "Fuego"), ("ug", "y" * 301), ("fetch", "1")]))
    a(_asked(cfg, "/request", "one text, fetched now", [("q", "Gustavo Cerati - Crimen"), ("fetch", "1")]))
    a(_asked(cfg, "/request", "fetch that isn't one", [("artist", "Estopa"), ("title", "Fuego"), ("fetch", "true")]))
    a(_asked(cfg, "/request", "a full queue, fetched now", [("artist", "Estopa"), ("title", "Fuego"), ("fetch", "1")],
             full=True))
    # POST /fetch: Fetch now on a song's card
    for wants in (True, False):
        a(_asked(cfg, "/fetch", "a song of the library", [("song", str(calorro.id))], wants=wants))
    a(_asked(cfg, "/fetch", "a song that needs review first", [("song", str(creep.id))]))
    a(_asked(cfg, "/fetch", "a review a [match] settles", [("song", str(karma.id))]))
    a(_asked(cfg, "/fetch", "a song not found: its artist's page settles it", [("song", str(persiana.id))]))
    a(_asked(cfg, "/fetch", "a review whose candidates never accept: its artist's page settles it",
             [("song", str(heroes.id))]))
    a(_asked(cfg, "/fetch", "a review every candidate of which is rejected", [("song", str(surprises.id))]))
    a(_asked(cfg, "/fetch", "a review a candidate of which is rejected", [("song", str(lucky.id))]))
    a(_asked(cfg, "/fetch", "an ignored song", [("song", str(eres.id))]))
    a(_asked(cfg, "/fetch", "an id that is no number", [("song", "x1")]))
    a(_asked(cfg, "/fetch", "no id", []))
    a(_asked(cfg, "/fetch", "an id no song has", [("song", "9999")]))
    a(_asked(cfg, "/fetch", "a full queue", [("song", str(calorro.id))], full=True))
    # POST /lacuerda/artist: an artist's Songs
    for wants in (True, False):
        a(_asked(cfg, "/lacuerda/artist", "an artist the index lists", [("slug", "estopa")], wants=wants))
    a(_asked(cfg, "/lacuerda/artist", "a slug the index hasn't", [("slug", "nadie_nunca")]))
    a(_asked(cfg, "/lacuerda/artist", "a slug that isn't one", [("slug", "Estopa!")]))
    a(_asked(cfg, "/lacuerda/artist", "a name, under a letter not read", [("name", "  Fito   Páez ")]))
    a(_asked(cfg, "/lacuerda/artist", "a name that makes no address", [("name", "¡¡¡")]))
    a(_asked(cfg, "/lacuerda/artist", "a name too long", [("name", "x" * 201)]))
    a(_asked(cfg, "/lacuerda/artist", "a slug and a name", [("slug", "estopa"), ("name", "Estopa")]))
    a(_asked(cfg, "/lacuerda/artist", "neither", []))
    # POST /harptabs/artist
    for wants in (True, False):
        a(_asked(cfg, "/harptabs/artist", "an artist the sitemap lists", [("path", "artist/50/the-beatles")],
                 wants=wants))
    a(_asked(cfg, "/harptabs/artist", "a path the sitemap hasn't", [("path", "artist/51/the-rolling-stones")]))
    a(_asked(cfg, "/harptabs/artist", "a path that isn't one", [("path", "/artist/50/the-beatles")]))
    # POST /versions/keep-more: Fetch them on a song's card
    for wants in (True, False):
        a(_asked(cfg, "/versions/keep-more", "versions left to keep", [("song", str(tren.id))], wants=wants))
    a(_asked(cfg, "/versions/keep-more", "nothing left to keep", [("song", str(baile.id))]))
    a(_asked(cfg, "/versions/keep-more", "a song with no version", [("song", str(calorro.id))]))
    a(_asked(cfg, "/versions/keep-more", "an ignored song", [("song", str(eres.id))]))
    a(_asked(cfg, "/versions/keep-more", "an id that is no number", [("song", "zz")]))
    a(_asked(cfg, "/versions/keep-more", "an id no song has", [("song", "9999")]))
    # by a viewer's path (caracole serve's versions page): the phone writes no viewer of its own, so none names a sheet
    a(_asked(cfg, "/versions/keep-more", "no song and no sheet", []))
    a(_asked(cfg, "/versions/keep-more", "a song of spaces, no sheet", [("song", "  ")]))
    a(_asked(cfg, "/versions/keep-more", "a sheet no viewer was written for",
             [("sheet", "Los Prisioneros/Tren al Sur/sheet.html")]))
    a(_asked(cfg, "/versions/keep-more", "a sheet that is no viewer's path", [("sheet", "../sheet.html")]))
    return out


def lacuerda_searches(cfg, conn) -> list[dict[str, Any]]:
    """POST /lacuerda/search in each state of its gate, over the library with the gate's records of each case."""
    from caracole.commands._common import LOOKUP_RUN
    from caracole.health import record_block
    from caracole.db import kv_set_json
    from caracole.lacuerda_search import FAILED_KEY, KV_PREFIX, RUN, SEARCHES_PER_HOUR, query_key

    out = []
    a = out.append
    at = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    base = dict(conn.execute("SELECT key, value FROM kv").fetchall())

    def reset() -> None:
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM kv")
        conn.executemany("INSERT INTO kv (key, value) VALUES (?, ?)", base.items())

    def events(n: int, run: str) -> None:
        conn.executemany("INSERT INTO events (run, at, provider, url, status, decision, message) VALUES "
                         "(?, ?, 'lacuerda', 'https://acordes.lacuerda.net/busca.php', 200, 'ok', NULL)",
                         [(run, at)] * n)

    def ask(case: str, form: list[tuple[str, str]], **options: Any) -> None:
        a(_asked(cfg, "/lacuerda/search", case, form, rows=_beyond(conn, base), **options))

    assert conn.execute("SELECT 1 FROM events").fetchone() is None, "the library has no events"
    q = "corazones rotos"
    for wants in (True, False):
        ask("auto: sent by the page", [("q", q)], wants=wants)
    ask("by hand", [("q", q), ("by_hand", "1")])
    ask("no query", [("q", "   ")])
    ask("a query too long", [("q", "palabra " * 30)])
    ask("no word of four letters", [("q", "mi sol la")])
    ask("LaCuerda's index has the artist, whose page caracole read", [("q", "soda stereo")])
    ask("your library has the song", [("q", "tu calorro")])
    kv_set_json(conn, KV_PREFIX + query_key(q), {"at": "2026-10-20T00:00:00Z", "songs": 3, "artists": 0, "stated": 3})
    ask("asked within 30 days", [("q", q)])
    kv_set_json(conn, KV_PREFIX + query_key(q), {"at": "2026-09-20T00:00:00Z", "songs": 3, "artists": 0, "stated": 3})
    ask("asked more than 30 days ago", [("q", q)])
    reset()
    record_block(conn, "lacuerda", NOW - timedelta(hours=1), "HTTP 429")
    ask("spent: LaCuerda cools down", [("q", q), ("by_hand", "1")])
    reset()
    events(cfg.provider("lacuerda").lookup_per_hour, LOOKUP_RUN + "get:1")
    ask("spent: the hour's lookups to LaCuerda", [("q", q)])
    reset()
    kv_set_json(conn, FAILED_KEY, {query_key(q): {"at": "2026-11-03T11:40:00Z", "error": "HTTP 500"}})
    ask("failed within the hour, by itself", [("q", q)])
    ask("failed within the hour, by hand", [("q", q), ("by_hand", "1")])
    reset()
    kv_set_json(conn, FAILED_KEY, {f"otra-{n}": {"at": f"2026-11-03T11:{20 + n}:00Z", "error": f"HTTP 50{n}"}
                                   for n in range(3)})
    ask("three others failed within the hour", [("q", q)])
    reset()
    events(SEARCHES_PER_HOUR, LOOKUP_RUN + RUN + "x")
    ask("button: the page's share of the hour spent", [("q", q)])
    ask("button, by hand", [("q", q), ("by_hand", "1")])
    reset()
    ask("a full queue", [("q", q)], full=True)
    return out


# --- /api/search's gate --------------------------------------------------------------------------------------------


GATE_CASES = (  # fixture, case, rows, queries
    ("lacuerda", "nothing asked", [], ("corazones rotos", "fito paez", "estopa", "soda stereo", "mi sol la",
                                       "bomba estereo", "como camaron", "estopa como camaron", "tu calorro",
                                       "enanitos verdes", "los enanitos verdes", "bunbury", "ecos", "ab")),
    ("lacuerda", "asked within 30 days", [{"kv": "lacuerda:search:corazones-rotos",
                                           "value": '{"at": "2026-10-20T00:00:00Z", "songs": 3}'}],
     ("corazones rotos", "rotos corazones")),
    ("lacuerda", "its own search failed", [{"kv": "lacuerda:search-failed",
                                            "value": '{"corazones-rotos": {"at": "2026-11-03T11:40:00Z", '
                                                     '"error": "HTTP 500"}}'}],
     ("corazones rotos", "fito paez")),
    ("lacuerda", "three failed", [{"kv": "lacuerda:search-failed",
                                   "value": json.dumps({f"otra-{n}": {"at": f"2026-11-03T11:{20 + n}:00Z",
                                                                       "error": f"HTTP 50{n}"} for n in range(3)})}],
     ("corazones rotos",)),
    ("lacuerda", "the page's share spent", [
        {"table": "events", "row": {"run": f"lookup:lacuerda-search:{n}", "at": "2026-11-03T11:30:00Z",
                                    "provider": "lacuerda", "url": "https://acordes.lacuerda.net/busca.php",
                                    "status": 200, "decision": "ok", "message": None}} for n in range(20)],
     ("corazones rotos",)),
    ("lacuerda", "cooling down", [{"kv": "provider:lacuerda",
                                   "value": '{"strikes": 1, "cooldown_until": "2026-11-04T13:00:00Z"}'}],
     ("corazones rotos",)),
    ("lacuerda", "the listing read whole", [{"kv": "lacuerda:index:complete_at", "value": "2026-10-21T00:00:00Z"}],
     ("fito paez", "bomba estereo")),
    ("common", "nothing asked", [], ("fito paez", "calamaro", "heroes del silencio entre dos tierras",
                                     "mana rayando el sol", "joaquin sabina", "creep")),
    ("empty", "nothing asked", [], ("fito paez", "corazones rotos")),
)


def gate_records(tmp: Path) -> list[dict[str, Any]]:
    from caracole.web.search_routes import _found_for

    out = []
    for fixture, case, rows, queries in GATE_CASES:
        where = tmp / f"gate-{len(out)}"
        from caracole.config import load_config

        cfg = load_config(None, env={"HOME": str(where / "home"), "STATE_DIRECTORY": str(where / "state"),
                                     "CACHE_DIRECTORY": str(where / "cache")})
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        app = _app(cfg)
        with closing(db.connect(cfg.db_path)) as conn:
            replay_fixture(conn, _search_fixture(fixture))
            replay_fixture(conn, rows)
            for q in queries:
                with _gate_at(NOW):
                    found = _found_for(app, conn, q)
                out.append({"fn": "caracole.web.search_routes._found_for", "fixture": fixture, "case": case,
                            "rows": rows, "q": q, "now": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "out": {"lacuerda_search": found["lacuerda_search"],
                                    "lacuerda_unlisted": found["lacuerda_unlisted"]}})
    return out


# --- the vectors ---------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> dict[str, list[dict[str, Any]]]:
    tmp = tmp_path_factory.mktemp("lookup_routes")
    with _library(tmp / "library") as (cfg, conn, songs):
        fixture = dump_fixture(conn)
        routes = [{"fn": "fixture", "records": fixture}, *lookups(cfg, songs), *lacuerda_searches(cfg, conn)]
    return {"routes": routes, "gate": gate_records(tmp)}


def test_the_routes_vectors_are_caracole_serves_answers(made):
    check(ROUTES, jsonl(made["routes"], corpus="web/lookup_routes", made_by=MADE_BY))


def test_the_gate_vectors_are_caracole_serves_answers(made):
    check(GATE, jsonl(made["gate"], corpus="web/api_search_gate", made_by=MADE_BY))


def test_every_route_answers_a_job_and_a_refusal(made):
    by = {}
    for r in made["routes"][1:]:
        by.setdefault(r["fn"], set()).add("job" in r["out"])
    assert set(by) == {"POST /lookup", "POST /request", "POST /fetch", "POST /lacuerda/artist",
                       "POST /lacuerda/search", "POST /harptabs/artist", "POST /versions/keep-more"}
    assert all(seen == {True, False} for seen in by.values()), by


def test_the_cases_meet_what_they_name(made):
    out = {(r["fn"], r["case"], r["json"]): r["out"] for r in made["routes"][1:]}
    assert out[("POST /fetch", "a song that needs review first", True)]["status"] == 409
    assert out[("POST /fetch", "a review a candidate of which is rejected", True)]["status"] == 409
    for case in ("a review a [match] settles", "a song not found: its artist's page settles it",
                 "a review whose candidates never accept: its artist's page settles it",
                 "a review every candidate of which is rejected"):
        assert "job" in out[("POST /fetch", case, True)], case
    assert out[("POST /lookup", "your song by its id", True)]["wanted"] is False
    assert out[("POST /lookup", "a new song by its names", True)]["wanted"] is True
    assert out[("POST /lookup", "a new song by its names", False)]["location"] == "/#tab=requests&job=1"
    assert out[("POST /lookup", "an Ultimate Guitar song picked, matched to your song", True)]["wanted"] is False
    assert out[("POST /versions/keep-more", "versions left to keep", True)]["status"] == 303
    assert out[("POST /versions/keep-more", "nothing left to keep", True)]["status"] == 409
    for case in ("no song and no sheet", "a song of spaces, no sheet", "a sheet no viewer was written for",
                 "a sheet that is no viewer's path"):
        assert out[("POST /versions/keep-more", case, True)] == {
            "status": 404, "title": "Not found", "message": "No such sheet in the book."}, case
    states = {r["case"]: r["out"] for r in made["routes"][1:] if r["fn"] == "POST /lacuerda/search"}
    assert states["auto: sent by the page"]["job"]["steps"][0][1][-1] == "--auto"
    assert states["by hand"]["job"]["steps"][0][1][-1] == "--progress"
    for case, status in (("asked within 30 days", 409), ("spent: LaCuerda cools down", 429),
                         ("spent: the hour's lookups to LaCuerda", 429), ("failed within the hour, by itself", 429),
                         ("button: the page's share of the hour spent", 429)):
        assert states[case]["status"] == status, case
    for case in ("failed within the hour, by hand", "button, by hand", "asked more than 30 days ago"):
        assert "job" in states[case], case
    gates = {(r["case"], r["q"]): r["out"] for r in made["gate"]}
    said = {g["lacuerda_search"]["state"] for g in gates.values() if g["lacuerda_search"]}
    assert said == {"auto", "asked", "failed", "button", "spent"}, said
    assert any(g["lacuerda_search"] is None for g in gates.values())
    assert any(g["lacuerda_unlisted"] for g in gates.values())
    assert any(g["lacuerda_unlisted"] is None for g in gates.values())


def test_the_vectors_are_the_same_on_another_run(made, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("again")
    with _library(tmp / "library") as (cfg, conn, songs):
        assert [{"fn": "fixture", "records": dump_fixture(conn)}, *lookups(cfg, songs),
                *lacuerda_searches(cfg, conn)] == made["routes"]
    assert gate_records(tmp) == made["gate"]
