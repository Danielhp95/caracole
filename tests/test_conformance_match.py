"""The matcher, for the phone: what match.py decides for a song over an index and overrides, and what ``match_all``
writes, for the Kotlin lane matcher (core.match's ``Matcher``, ``IndexView`` and the lookup's match stage) to agree
with. A song's match is in its sync unit's digest (its ``match_*`` columns, its candidates, ``review``), so the
phone's must be the computer's to the byte.

**Harvested** from tests/test_match.py: each of its tests run here over a database of its own, its calls to
``match_song``, ``match_all`` and the index view (``IndexView``) recorded as they happen, with the database each
call met, so the Kotlin side replays every case test_match.py holds, over the same small index, and a new case there
is a new record here.

**Seeded**: a library of songs named as streaming services name them (exact, misspelt, with a word more or less, a
remaster's suffix, an article, another script, a show's song, a cover, nothing UG has) over an index of about a
thousand tabs of real-looking and generated artists, UG's catch-alls among them; matched once, given versions, then
the index changed under it, so that a match changes, is kept or is marked stale (``fixtures/seeded.jsonl``). Its
records match it whole, as the nightly run does, with the index complete, partial and empty, with overrides and a
policy of its own, and one song at a time, as a lookup does.

**Vectors** (``vectors/match/``), a header, then a record a line:

- ``ladder.jsonl``: ``{fn: "caracole.match.match_song", case, fixture, song, overrides, policy, out}``: ``fixture``
  the database's records then (helpers.corpus's ``dump_fixture``, inline), ``song`` the song's id in it,
  ``overrides`` the fields match.py reads (``alias``, ``match``, ``pin``, ``ignore``, ``reject``, ``lacuerda``: a
  set sorted, a pair an array, a pick its fields), ``policy`` ``MatchPolicy``'s fields, ``out`` the ``MatchResult``'s
  fields (its candidates' too). Each is the same over a fresh ``IndexView`` as over the test's (asserted).
- ``view.jsonl``: ``{fn: "caracole.match.IndexView", case, fixture, calls: [{method, args, out}]}``: one view's
  calls in order, a method's answer as JSON (an ``IndexTitle`` its fields, a tuple an array, a dict an object).
- ``match_all.jsonl`` and ``seeded.jsonl``: ``{fn: "caracole.match.match_all", case, fixture, before, overrides,
  policy, kw, now, out}``: ``fixture`` inline, or a fixture's name (``match/fixtures/seeded.jsonl``); ``before`` what
  is done to it first (``drop_kv``: kv keys deleted, ``clear_index``: every ``ug_index`` row deleted); ``kw``
  ``{dry_run, songs, song_ids}``, the songs by id (``songs`` the songs given, as they are in the database; null for
  none); ``now`` the clock's time while it runs (``songs.utc_now_iso``: ``matched_at`` and ``updated_at``); ``out``
  ``{changes: [{song, old, new}], rows: {songs, versions}}``: each change's song id, its decision before and its
  match now, and every row the call wrote (new, or other than before), whole, as ``dump_fixture`` reads them, by id.
- ``stage.jsonl``: ``{fn: "caracole.get._Lookup.match", case, fixture, song, overrides, policy, now, out}``: the
  lookup's match stage, its words (``out``), after ``artist_tabs.backfill`` from an empty cache.

Stamps: every time the tests' own writers take is ``BASE``; ``match_all`` runs at ``MATCHED``.

The answers are the same on every run (``test_the_vectors_are_the_same_on_another_run``). Regenerate with
``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import random
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from helpers.corpus import VECTORS, check, dump_fixture, jsonl, plain, read_fixture, replay_fixture

MADE_BY = "tests/test_conformance_match.py"
MATCH = VECTORS / "match"
SEEDED_FIXTURE = MATCH / "fixtures" / "seeded.jsonl"
SEEDED_NAME = "match/fixtures/seeded.jsonl"
BASE = "2026-11-03T12:00:00Z"
MATCHED = "2026-11-04T09:30:00Z"
SEED = 20261104
HARVESTED = "test_match"
OVERRIDE_FIELDS = ("alias", "match", "pin", "ignore", "reject", "lacuerda")
TABLES = ("songs", "versions")


# --- the clock and a database -----------------------------------------------------------------------------------


class Clock:
    """``songs.utc_now_iso``, and match.py's name for it: ``now``, which a call sets for its run."""

    def __init__(self):
        self.now = BASE

    def __call__(self) -> str:
        return self.now


@contextmanager
def patched(target: Any, name: str, value: Any) -> Iterator[None]:
    old = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, old)


@contextmanager
def clocked(clock: Clock) -> Iterator[None]:
    from caracole import match, songs

    with patched(songs, "utc_now_iso", clock), patched(match, "utc_now_iso", clock):
        yield


@contextmanager
def database(where: Path) -> Iterator[sqlite3.Connection]:
    from caracole import db
    from conftest import migrated_database

    where.mkdir(parents=True, exist_ok=True)
    path = where / "caracole.sqlite"
    path.write_bytes(migrated_database())
    conn = db.connect(path)
    try:
        yield conn
    finally:
        conn.close()


def rows(conn: sqlite3.Connection, table: str) -> dict[int, dict[str, Any]]:
    return {r["row"]["id"]: r["row"] for r in dump_fixture(conn) if r.get("table") == table}


# --- what a record carries --------------------------------------------------------------------------------------


def overrides_json(o: Any) -> dict[str, Any]:
    """The fields of ``o`` match.py reads, each as a corpus writes it, only those that hold an entry."""
    out: dict[str, Any] = {}
    if o.alias:
        out["alias"] = {k: list(v) for k, v in o.alias.items()}
    if o.match:
        out["match"] = {k: list(v) for k, v in o.match.items()}
    if o.pin:
        out["pin"] = {k: list(v) for k, v in o.pin.items()}
    if o.ignore:
        out["ignore"] = sorted(o.ignore)
    if o.reject:
        out["reject"] = {k: sorted(list(p) for p in v) for k, v in o.reject.items()}
    if o.lacuerda:
        out["lacuerda"] = {k: dataclasses.asdict(v) for k, v in o.lacuerda.items()}
    return out


def policy_json(p: Any) -> dict[str, Any]:
    return dataclasses.asdict(p)


def change_json(change: Any) -> dict[str, Any]:
    return {"song": change.song.id, "old": change.old, "new": plain(change.new)}


def written(before: dict[str, dict[int, dict[str, Any]]], conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """Every row of ``TABLES`` the call wrote: new, or other than before, by id (match_all deletes none)."""
    out = {}
    for table in TABLES:
        after = rows(conn, table)
        assert set(before[table]) <= set(after), f"match_all deleted {table} rows"
        out[table] = [row for i, row in sorted(after.items()) if before[table].get(i) != row]
    return out


# --- the harvest ------------------------------------------------------------------------------------------------


class Harvest:
    """test_match.py's calls, recorded as they happen."""

    def __init__(self, clock: Clock):
        self.clock = clock
        self.case = ""
        self.n = 0
        self.ladder: list[dict[str, Any]] = []
        self.views: list[dict[str, Any]] = []
        self.matched: list[dict[str, Any]] = []

    def name(self) -> str:
        self.n += 1
        return f"{self.case}#{self.n}"

    def fresh(self, conn: sqlite3.Connection, song: Any) -> None:
        from caracole.songs import get_song

        assert get_song(conn, song.id) == song, f"{self.case}: a song as it is in the database, not as it was"

    def match_song(self, real):
        harvest = self

        def recording(song, index, overrides, policy):
            from caracole.match import IndexView

            result = real(song, index, overrides, policy)
            conn = index.conn
            harvest.fresh(conn, song)
            assert real(song, IndexView(conn), overrides, policy) == result, harvest.case
            harvest.ladder.append({"fn": "caracole.match.match_song", "case": harvest.name(),
                                   "fixture": dump_fixture(conn), "song": song.id,
                                   "overrides": overrides_json(overrides), "policy": policy_json(policy),
                                   "out": plain(result)})
            return result

        return recording

    def match_all(self, real):
        harvest = self

        def recording(conn, overrides, policy, *, dry_run=False, song_ids=None, songs=None):
            fixture = dump_fixture(conn)
            if songs is not None:
                songs = list(songs)
                for s in songs:
                    harvest.fresh(conn, s)
            before = {t: rows(conn, t) for t in TABLES}
            old = harvest.clock.now
            harvest.clock.now = MATCHED
            try:
                changes = real(conn, overrides, policy, dry_run=dry_run, song_ids=song_ids, songs=songs)
            finally:
                harvest.clock.now = old
            harvest.matched.append({
                "fn": "caracole.match.match_all", "case": harvest.name(), "fixture": fixture, "before": {},
                "overrides": overrides_json(overrides), "policy": policy_json(policy),
                "kw": {"dry_run": dry_run, "songs": None if songs is None else [s.id for s in songs],
                       "song_ids": None if song_ids is None else sorted(song_ids)},
                "now": MATCHED, "out": {"changes": [change_json(c) for c in changes], "rows": written(before, conn)},
            })
            return changes

        return recording

    def view_class(self, real):
        harvest = self

        class RecordingView(real):
            """An IndexView whose calls from test_match.py itself are recorded, in order."""

            def __init__(self, conn):
                super().__init__(conn)
                self._record = None

            def __getattribute__(self, attr):
                value = super().__getattribute__(attr)
                if attr.startswith("_") or not callable(value) or sys._getframe(1).f_globals.get("__name__") != HARVESTED:
                    return value

                def called(*args):
                    out = value(*args)
                    if self._record is None:
                        self._record = {"fn": "caracole.match.IndexView", "case": harvest.name(),
                                        "fixture": dump_fixture(self.conn), "calls": []}
                        harvest.views.append(self._record)
                    else:
                        assert dump_fixture(self.conn) == self._record["fixture"], harvest.case
                    self._record["calls"].append({"method": attr, "args": [list(a) if isinstance(a, list) else a
                                                                           for a in args], "out": plain(out)})
                    return out

                return called

        return RecordingView


def parameters(fn) -> list[tuple[str, dict[str, Any]]]:
    """Each run of a test function: its id and its parameters (pytest.mark.parametrize's, or none)."""
    marks = [m for m in getattr(fn, "pytestmark", []) if m.name == "parametrize"]
    if not marks:
        return [("", {})]
    assert len(marks) == 1, fn.__name__
    names, values = marks[0].args[0], marks[0].args[1]
    names = [n.strip() for n in names.split(",")] if isinstance(names, str) else list(names)
    return [(f"[{i}]", dict(zip(names, v if len(names) > 1 else [v], strict=True))) for i, v in enumerate(values)]


def harvest(workdir: Path) -> Harvest:
    import test_match as T

    clock = Clock()
    h = Harvest(clock)
    tests = [(name, fn) for name, fn in vars(T).items() if name.startswith("test_") and inspect.isfunction(fn)]
    with clocked(clock), patched(T, "match_song", h.match_song(T.match_song)), \
            patched(T, "match_all", h.match_all(T.match_all)), patched(T, "IndexView", h.view_class(T.IndexView)):
        for name, fn in tests:
            assert list(inspect.signature(fn).parameters)[0] == "conn", name
            for suffix, params in parameters(fn):
                h.case, h.n = name + suffix, 0
                clock.now = BASE
                with database(workdir / f"{name}{suffix}") as conn:
                    fn(conn, **params)
    return h


# --- the seeded library -----------------------------------------------------------------------------------------

# Artists as UG files them (its key) and as a streaming service names them, each with titles of their own.
KNOWN = (
    ("Oasis", "oasis", ("Wonderwall", "Champagne Supernova", "Don't Look Back in Anger", "Live Forever",
                        "Supersonic", "Stand By Me", "Half the World Away", "Wonderwalls")),
    ("Radiohead", "radiohead", ("Creep", "Karma Police", "No Surprises", "Fake Plastic Trees", "Lucky",
                                "High and Dry", "Paranoid Android")),
    ("The Beatles", "beatles", ("Let It Be", "Yesterday", "Yesterdays", "Hey Jude", "Come Together", "Something",
                                "Here Comes the Sun", "Blackbird")),
    ("AC/DC", "acdc", ("Highway to Hell", "Back in Black", "Thunderstruck", "You Shook Me All Night Long")),
    ("Enanitos Verdes", "los-enanitos-verdes", ("Lamento Boliviano", "La Muralla Verde", "Luz de Dia")),
    ("Los Prisioneros", "prisioneros", ("Tren al Sur", "El Baile de los que Sobran", "Estrechez de Corazon")),
    ("Soda Stereo", "soda-stereo", ("Persiana Americana", "De Musica Ligera", "En la Ciudad de la Furia",
                                    "Te Hare Sentir Bien")),
    ("Coldplay", "coldplay", ("Yellow", "Fix You", "The Scientist", "Clocks", "Viva la Vida")),
    ("Metallica", "metallica", ("One", "Nothing Else Matters", "Enter Sandman", "Creeping Death", "Live")),
    ("Tool", "tool", ("Schism", "Lateralus", "Sober", "Forty Six and 2")),
    ("Red Hot Chili Peppers", "red-hot-chili-peppers", ("Californication", "Scar Tissue", "Otherside")),
    ("Red Hot Chili Peppers", "red-hot-chilli-peppers", ("Under the Bridge", "Snow Hey Oh")),
    ("Los Lobos", "los-lobos", ("Cancion del Mariachi Morena de Mi Corazon", "La Bamba", "Will the Wolf Survive")),
    ("Katy Perry", "katy-perry", ("E.T.", "Roar", "Firework")),
    ("Leonard Cohen", "leonard-cohen", ("Hallelujah", "Suzanne", "So Long Marianne")),
    ("Jeff Buckley", "jeff-buckley", ("Hallelujah", "Grace", "Last Goodbye")),
    ("Ana Gabriel", "ana-gabriel", ("Rayando el Sol", "Simplemente Amigos")),
    ("Pablo Alboran", "pablo-alboran", ("Rayando el Sol", "Solamente Tu", "Saturno")),
    ("Joaquin Sabina", "joaquin-sabina", ("Y Nos Dieron las Diez", "Calle Melancolia")),
    ("宋冬野", "song-dongye", ("斑马，斑马", "安和桥", "董小姐")),
    ("李志", "li-zhi", ("斑马，斑马", "关于郑州的记忆", "天空之城")),
    ("赵雷", "zhao-lei", ("成都", "南方姑娘", "画")),
    ("DAOKO", "daoko", ("打上花火 (Uchiage Hanabi)", "Ienai")),
    ("Kino (Кино)", "kino", ("Gruppa Krovi / Группа крови", "Kukushka")),
    ("Idina Menzel", "idina-menzel", ("Defying Gravity",)),
    ("James Bay", "james-bay", ("Let It Go", "Hold Back the River")),
    ("Demi Lovato", "demi-lovato", ("Let It Go", "Skyscraper")),
)
# UG's catch-alls and the titles they file: a show's name or a performer's before the song's.
CATCH_ALLS = (
    ("misc-musicals", ("epic-the-musical-not-sorry-for-loving-you", "epic-the-musical-get-in-the-water",
                       "epic-the-musical-open-arms", "hamilton-my-shot", "hamilton-wait-for-it",
                       "les-miserables-on-my-own")),
    ("misc-cartoons", ("frozen-let-it-go", "steven-universe-here-comes-a-thought", "moana-how-far-ill-go")),
    ("misc-soundtrack", ("titanic-my-heart-will-go-on", "shot-in-the-dark")),
    ("misc-television", ("friends-ill-be-there-for-you", "oasis-wonderwal")),
    ("misc-computer-games", ("hollow-knight-main-theme", "undertale-megalovania")),
    ("misc-originals", ("ray-porter-red-sarah", "robert-muecke-kiss-you")),
    ("misc-unsigned-bands", ("suzie-clark-aint-gonna-kiss-you",)),
    ("misc-mashups", ("radiohead-creep-mitski-my-love-mine-all-mine",)),
    ("misc-praise-songs", ("how-great-is-our-god", "amazing-grace")),
    ("misc-christmas", ("silent-night",)),
)
SYLLABLES = ("ka", "lo", "mi", "ra", "su", "te", "vo", "na", "di", "pe", "ro", "ba", "ne", "ti", "go", "za", "lu")
VARIANTS = ("", "", "", "", "-acoustic", "-live", "-intro", "-solo")
TYPES = ("chords", "chords", "chords", "tabs", "ukulele")


def generated_name(rng: random.Random, words: int) -> str:
    return " ".join("".join(rng.choice(SYLLABLES) for _ in range(rng.randint(1, 3))) for _ in range(words))


def seeded_index(rng: random.Random) -> list[tuple[int, str, str, str]]:
    """(tab id, artist key, song key, type) rows: the known artists', the catch-alls', generated artists' (some an
    edit from a known one, some of the known titles: covers)."""
    from caracole.normalize import romanize, slug_key

    rows = []
    tab = 100

    def add(artist_key: str, song_key: str, tabs: int) -> None:
        nonlocal tab
        for _ in range(tabs):
            tab += 1
            rows.append((tab, artist_key, song_key + rng.choice(VARIANTS), rng.choice(TYPES)))

    for _, key, titles in KNOWN:
        for title in titles:
            song = slug_key(romanize(title.split(" (")[0])) if "，" in title or title[0] > "　" else slug_key(title)
            if title.startswith("打上花火"):
                song = "uchiage-hanabi"
            if title.startswith("Gruppa"):
                song = "gruppa-krovi"
            if title == "E.T.":
                song = "et"  # E.T. keys as e-t; UG wrote the slug as et
            if key == "song-dongye" and rng.random() < 0.5:
                song = song.replace("ban-ma-ban-ma", "banma-banma")
            add(key, song, rng.randint(1, 4))
    for key, titles in CATCH_ALLS:
        for title in titles:
            add(key, title, rng.randint(1, 3))
    known_titles = [slug_key(t) for _, _, titles in KNOWN for t in titles if t.isascii()]
    generated = sorted({slug_key(generated_name(rng, rng.randint(1, 3))) for _ in range(160)})
    for artist in generated:
        for _ in range(rng.randint(1, 6)):
            title = rng.choice(known_titles) if rng.random() < 0.15 else slug_key(generated_name(rng, rng.randint(1, 4)))
            add(artist, title, rng.randint(1, 3))
    # Neighbours an edit away: a known artist's name misspelt as UG files a duplicate, and short names a letter off.
    for artist in ("coldplya", "oaiss", "metalica", "colo", "lolo", "polo", "radiohaed"):
        add(artist, slug_key(generated_name(rng, 2)), rng.randint(1, 2))
    return rows


def misspelt(rng: random.Random, text: str) -> str:
    """``text`` with one of its letters swapped with the next, dropped or doubled."""
    letters = [i for i, c in enumerate(text[:-1]) if c.isalpha() and text[i + 1].isalpha()]
    if not letters:
        return text + text[-1]
    i = rng.choice(letters)
    kind = rng.randrange(3)
    if kind == 0:
        return text[:i] + text[i + 1] + text[i] + text[i + 2:]
    if kind == 1:
        return text[:i] + text[i + 1:]
    return text[:i] + text[i] + text[i:]


SUFFIXES = (" - Remastered 2011", " (Live)", " (Acoustic)", " - Radio Edit", " (feat. Someone Else)")


def seeded_songs(rng: random.Random) -> list[tuple[str, str, list[str] | None]]:
    """(artist, title, artists or None) as a streaming service names songs, each made from the index's songs."""
    songs: list[tuple[str, str, list[str] | None]] = []
    for name, _, titles in KNOWN:
        for title in titles:
            pick = rng.random()
            if pick < 0.3:
                songs.append((name, title, None))
            elif pick < 0.45:
                songs.append((name, title + rng.choice(SUFFIXES), None))
            elif pick < 0.55 and title.isascii():
                songs.append((name, misspelt(rng, title), None))
            elif pick < 0.62 and name.isascii():
                songs.append((misspelt(rng, name), title, None))
            elif pick < 0.68:
                songs.append(("Someone Else Entirely", title, None))
            elif pick < 0.74 and len(title.split()) > 2:
                songs.append((name, " ".join(title.split()[:-1]), None))
            elif pick < 0.8:
                songs.append((name, title + " and More", None))
    songs += [
        ("Epic", "Get in the Water", None), ("Jorge Rivera-Herrans", "Not Sorry for Loving You", None),
        ("Jorge Rivera-Herrans", "Open Arms", None), ("Hamilton", "My Shot", None), ("Frozen", "Let It Go", None),
        ("Idina Menzel", "Let It Go", None), ("Ray Porter", "Red Sarah", None), ("Kiss", "You", None),
        ("Mitski", "My Love Mine All Mine", None), ("Chris Tomlin", "Great Is Our God", None),
        ("Traditional", "Silent Night", None), ("Coldplya", "Yelow", None), ("Tolo", "Schism", None),
        ("Oaiss", "Wonderwall", None), ("Metalicca", "One", None), ("Santana", "Smooth", ["Santana", "Rob Thomas"]),
        ("Oasis", "Wonderwal", ["Oasis", "Liam Gallagher"]), ("Song Dongye (宋冬野)", "斑马斑马", None),
        ("宋冬野", "安和桥北", None), ("宋冬野", "斑马 斑马 Banma Banma Zebra Zebra", None),
        ("Maná", "Rayando el Sol", None), ("Nobody", "Nothing Like It", None), ("Oasis", "!!!", None),
        ("Undertale", "Megalovania", None), ("Hollow Knight", "Main Theme", None),
        ("Steven Universe", "Here Comes a Thought", None), ("Moana", "How Far I'll Go", None),
    ]
    for _ in range(12):
        songs.append((generated_name(rng, 2).title(), generated_name(rng, 3).title(), None))
    return songs


def build_seeded(conn: sqlite3.Connection, clock: Clock) -> dict[str, int]:
    """The seeded library: songs matched once, given versions, then the index changed under them. Returns the ids
    of the songs the records name."""
    from caracole.config import MatchPolicy
    from caracole.match import match_all
    from caracole.overrides import Overrides
    from caracole.songs import get_song, list_songs, update_song, upsert_song
    from caracole.ug.index import mark_built
    from caracole.versions import set_picks, upsert_version

    rng = random.Random(SEED)
    rows = seeded_index(rng)
    conn.executemany(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (?, ?, ?, ?, '1', '2026-10-18T03:30:00Z', ?)",
        [(t, a, s, k, f"{a}/{s}-{k}-{t}") for t, a, s, k in rows])
    mark_built(conn, datetime(2026, 10, 18, 3, 30, tzinfo=UTC))
    for n, (artist, title, artists) in enumerate(seeded_songs(rng)):
        upsert_song(conn, artists=artists or [artist], title=title, album=None, duration_ms=200000 + n, isrc=None,
                    source="wanted", source_id=f"{artist}/{title}", added_at=f"2026-10-{1 + n // 24:02d}T"
                                                                            f"{n % 24:02d}:00:00Z")
    match_all(conn, Overrides(), MatchPolicy())
    # Songs added since, never matched: a partial index leaves them so, missing or not.
    for n, (artist, title) in enumerate((("Soda Stereo", "Signos"), ("Eagles", "Hotel California"),
                                         ("Nobody", "Nothing Like It"), ("Rob Thomas", "Smooth"))):
        upsert_song(conn, artists=[artist], title=title, album=None, duration_ms=None, isrc=None, source="wanted",
                    source_id=f"{artist}/{title}", added_at=f"2026-10-30T0{n}:00:00Z")
    songs = list_songs(conn)
    accepted = [s for s in songs if s.match_decision == "accept"]
    for s in accepted:
        ids = [upsert_version(conn, provider="ug", tab_id=str(9000 + s.id * 10 + k), song_id=s.id, slot=slot,
                              kind=kind, rating=4.0 + k / 10, votes=10 + k, version=1, label=None,
                              url=f"https://tabs.ultimate-guitar.com/tab/{9000 + s.id * 10 + k}", raw={"k": k},
                              now=BASE)
               for k, (slot, kind) in enumerate((("sheet", "chords"), ("guitar", "tabs")))]
        set_picks(conn, s.id, ("chords",), ids[:1])
        if s.id % 3 == 0:
            lacuerda = upsert_version(conn, provider="lacuerda", tab_id=f"x/{s.key}", song_id=s.id, slot="sheet",
                                      kind="acordes", rating=4.2, votes=3, version=1, label=None,
                                      url=f"https://acordes.lacuerda.net/x/{s.id}", raw={}, now=BASE)
            set_picks(conn, s.id, ("acordes",), [lacuerda])
        update_song(conn, s.id, ug_dirty=False)
    # The index changes under the library: titles gone, rivals and covers come, a miss now found.
    gone = [s for s in accepted if s.id % 5 == 0]
    for s in gone:
        conn.execute("DELETE FROM ug_index WHERE artist_key = ? AND (song_key = ? OR song_key LIKE ?)",
                     (s.match_artist_key, s.match_song_key, s.match_song_key + "-%"))
    tab = 50000
    for s in [s for s in accepted if s.id % 7 == 0]:
        tab += 1
        conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
                     "VALUES (?, ?, ?, 'chords', '1', 'x', ?)",
                     (tab, s.match_artist_key, s.match_song_key + "s", f"rival/{tab}"))
    for artist, title in (("nobody", "nothing-like-it"), ("rob-thomas", "smooth"), ("liam-gallagher", "wonderwall")):
        tab += 1
        conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
                     "VALUES (?, ?, ?, 'chords', '1', 'x', ?)", (tab, artist, title, f"{artist}/{title}"))
    # A6: matches the fetch made on an artist page, one of them on a page you then rejected; an ignore taken out.
    misses = [s for s in songs if s.match_decision == "not_found"]
    for s in misses[:2]:
        update_song(conn, s.id, match_decision="accept", match_step="artist_page", match_score=100.0,
                    match_artist_key="page-artist", match_song_key=f"page-song-{s.id}", ug_dirty=False,
                    match_candidates=[{"artist_key": "page-artist", "song_key": f"page-song-{s.id}", "score": 100.0,
                                       "step": "artist_page"}])
    update_song(conn, songs[-1].id, status="ignored", match_decision="ignored", match_step="override")
    named = {"artist_page": misses[0].id, "rejected_page": misses[1].id, "ignored": songs[-1].id,
             "accepted": accepted[0].id, "gone": gone[0].id,
             "review": [s.id for s in songs if s.match_decision == "review"][0], "miss": misses[2].id}
    for s in (get_song(conn, i) for i in named.values()):
        assert s is not None
    return named


def seeded_overrides(conn: sqlite3.Connection, named: dict[str, int]):
    from caracole.overrides import LaCuerdaPick, Overrides
    from caracole.songs import get_song, list_songs

    songs = list_songs(conn)
    key = {n: get_song(conn, i).key for n, i in named.items()}
    review = get_song(conn, named["review"])
    shown = frozenset((c["artist_key"], c["song_key"]) for c in review.match_candidates)
    page = get_song(conn, named["rejected_page"])
    titled = [s for s in songs if s.match_decision == "review" and s.match_step == "title_only"]
    return Overrides(
        alias={"oasis": ("oasis",), "soda": ("soda-stereo",), "enanitos-verdes": ("los-enanitos-verdes",)},
        match={key["accepted"]: ("radiohead", "creep"), key["miss"]: ("tool", "schism")},
        pin={key["gone"]: (101, 999999), key["miss"]: (102,)},
        ignore=frozenset({key["artist_page"]}),
        reject={review.key: shown, page.key: frozenset({(page.match_artist_key, page.match_song_key)})},
        lacuerda={s.key: LaCuerdaPick("x", "y") for s in titled[:3]},
    )


def seeded_records(workdir: Path) -> tuple[str, list[dict[str, Any]]]:
    from caracole.config import MatchPolicy
    from caracole.match import match_all
    from caracole.overrides import Overrides
    from caracole.songs import get_song, list_songs

    clock = Clock()
    with clocked(clock):
        with database(workdir / "seeded") as conn:
            named = build_seeded(conn, clock)
            fixture = dump_fixture(conn)
        text = jsonl(fixture, corpus="match/fixtures/seeded", made_by=MADE_BY)
        runs: list[tuple[str, dict[str, Any], Any, Any, dict[str, Any]]] = []
        with database(workdir / "over") as conn:
            replay_fixture(conn, read_fixture(text))
            overrides = seeded_overrides(conn, named)
            songs = list_songs(conn)
        default, own = MatchPolicy(), MatchPolicy(accept=88, margin=4, review=70, artist_gate=85)
        runs += [
            ("every song, the index complete", {}, Overrides(), default, {}),
            ("every song, the index partial: no miss saved, what was found kept", {"drop_kv": ["ug:index:built_at"]},
             Overrides(), default, {}),
            ("every song, the index empty, your overrides still apply", {"clear_index": True}, overrides, default, {}),
            ("every song, with overrides and a policy of its own", {}, overrides, own, {}),
            ("every song, a dry run", {}, overrides, default, {"dry_run": True}),
            ("some songs by id", {}, Overrides(), default, {"song_ids": sorted(named.values())[:4]}),
        ]
        runs += [(f"a lookup of {name}", {}, overrides, default, {"songs": [i]}) for name, i in named.items()]
        runs += [(f"a lookup of song {s.id}", {}, Overrides(), default, {"songs": [s.id]}) for s in songs[::9]]
        records = []
        for n, (case, before, o, policy, kw) in enumerate(runs):
            with database(workdir / f"run{n}") as conn:
                replay_fixture(conn, read_fixture(text))
                for k in before.get("drop_kv", []):
                    conn.execute("DELETE FROM kv WHERE key = ?", (k,))
                if before.get("clear_index"):
                    conn.execute("DELETE FROM ug_index")
                given = [get_song(conn, i) for i in kw["songs"]] if "songs" in kw else None
                rows_before = {t: rows(conn, t) for t in TABLES}
                clock.now = MATCHED
                changes = match_all(conn, o, policy, dry_run=kw.get("dry_run", False),
                                    song_ids=set(kw["song_ids"]) if "song_ids" in kw else None, songs=given)
                clock.now = BASE
                records.append({
                    "fn": "caracole.match.match_all", "case": case, "fixture": SEEDED_NAME, "before": before,
                    "overrides": overrides_json(o), "policy": policy_json(policy),
                    "kw": {"dry_run": kw.get("dry_run", False), "songs": kw.get("songs"),
                           "song_ids": kw.get("song_ids")},
                    "now": MATCHED,
                    "out": {"changes": [change_json(c) for c in changes], "rows": written(rows_before, conn)},
                })
    return text, records


# --- the lookup's match stage -----------------------------------------------------------------------------------


STAGE_INDEX = ((1, "oasis", "wonderwall", "chords"), (2, "oasis", "wonderwalls", "chords"),
               (3, "radiohead", "creep", "chords"), (4, "leonard-cohen", "hallelujah", "chords"))


def stage_records(workdir: Path) -> list[dict[str, Any]]:
    from caracole import get
    from caracole.config import MatchPolicy
    from caracole.overrides import Overrides
    from caracole.songs import get_song, upsert_song
    from caracole.ug.index import mark_built

    clock = Clock()
    cases = [
        ("accepted", "Radiohead", "Creep", {}, "complete"),
        ("a review", "Oasis", "Wonderwal", {}, "complete"),
        ("not found", "Nobody", "Nothing", {}, "complete"),
        ("found on the title alone", "Someone", "Hallelujah", {}, "complete"),
        ("ignored", "Radiohead", "Creep", {"ignore": True}, "complete"),
        ("pinned to a tab of the index", "Radiohead", "Creep", {"pin": (3,)}, "complete"),
        ("pinned to a tab the index lacks", "Radiohead", "Creep", {"pin": (77,)}, "complete"),
        ("your match", "Nobody", "Nothing", {"match": ("oasis", "wonderwall")}, "complete"),
        ("the index partial", "Radiohead", "Creep", {}, "partial"),
        ("the index partial, a miss", "Nobody", "Nothing", {}, "partial"),
        ("the index empty", "Radiohead", "Creep", {}, "empty"),
        ("the index empty, your pin", "Radiohead", "Creep", {"pin": (3,)}, "empty"),
        ("the index empty, your match", "Radiohead", "Creep", {"match": ("radiohead", "creep")}, "empty"),
    ]
    records = []
    with clocked(clock):
        for n, (case, artist, title, entries, state) in enumerate(cases):
            with database(workdir / f"stage{n}") as conn:
                if state != "empty":
                    conn.executemany(
                        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
                        "VALUES (?, ?, ?, ?, '1', 'x', ?)", [(t, a, s, k, f"{a}/{s}-{k}-{t}") for t, a, s, k in STAGE_INDEX])
                if state == "complete":
                    mark_built(conn, datetime(2026, 10, 18, 3, 30, tzinfo=UTC))
                song_id, _ = upsert_song(conn, artists=[artist], title=title, album=None, duration_ms=None,
                                         isrc=None, source="wanted", source_id=f"{artist}/{title}",
                                         added_at="2026-10-01T00:00:00Z")
                song = get_song(conn, song_id)
                o = Overrides(ignore=frozenset({song.key}) if entries.get("ignore") else frozenset(),
                              pin={song.key: entries["pin"]} if "pin" in entries else {},
                              match={song.key: entries["match"]} if "match" in entries else {})
                fixture = dump_fixture(conn)
                lookup = get._Lookup.__new__(get._Lookup)
                lookup.conn, lookup.overrides, lookup.song = conn, o, song
                lookup.cfg = SimpleNamespace(cache_dir=workdir / f"stage{n}" / "cache", match=MatchPolicy())
                clock.now = MATCHED
                said = lookup.match()
                clock.now = BASE
                records.append({"fn": "caracole.get._Lookup.match", "case": case, "fixture": fixture,
                                "song": song.id, "overrides": overrides_json(o), "policy": policy_json(MatchPolicy()),
                                "now": MATCHED, "out": said})
    return records


# --- the files --------------------------------------------------------------------------------------------------


def every_file(workdir: Path) -> dict[Path, str]:
    h = harvest(workdir / "harvest")
    text, seeded = seeded_records(workdir / "seeded")
    return {
        MATCH / "ladder.jsonl": jsonl(h.ladder, corpus="match/ladder", made_by=MADE_BY),
        MATCH / "view.jsonl": jsonl(h.views, corpus="match/view", made_by=MADE_BY),
        MATCH / "match_all.jsonl": jsonl(h.matched, corpus="match/match_all", made_by=MADE_BY),
        SEEDED_FIXTURE: text,
        MATCH / "seeded.jsonl": jsonl(seeded, corpus="match/seeded", made_by=MADE_BY),
        MATCH / "stage.jsonl": jsonl(stage_records(workdir / "stage"), corpus="match/stage", made_by=MADE_BY),
    }


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    return every_file(tmp_path_factory.mktemp("match"))


NAMES = ("ladder", "view", "match_all", "fixtures/seeded", "seeded", "stage")


@pytest.mark.parametrize("name", NAMES)
def test_the_vector_is_what_the_matcher_does(made, name):
    path = MATCH / f"{name}.jsonl"
    check(path, made[path])


def _records(made, name):
    return read_fixture(made[MATCH / f"{name}.jsonl"])


def test_every_step_and_decision_is_in_the_vectors(made):
    from caracole.match import DECISIONS, STEPS

    results = [r["out"] for r in _records(made, "ladder")]
    results += [c["new"] for r in _records(made, "match_all") + _records(made, "seeded") for c in r["out"]["changes"]]
    assert {r["decision"] for r in results} == set(DECISIONS)
    assert {r["step"] for r in results} >= {*STEPS, "artist_page"}
    assert {c["step"] for r in results for c in r["candidates"]} >= {"word_title", "typo_artist", "catch_all",
                                                                     "title_only", "fuzzy_artist", "alias"}


def test_the_seeded_runs_change_keep_and_mark_stale(made):
    seeded = _records(made, "seeded")
    whole = seeded[0]["out"]
    assert any(r["ug_dirty"] == 1 for r in whole["rows"]["songs"])
    assert any(v["gone"] == 2 for v in whole["rows"]["versions"])  # marked stale
    assert not seeded[4]["out"]["rows"]["songs"]  # the dry run writes nothing
    # An incomplete index saves no miss: a song never matched stays unmatched, and shows as a miss.
    partial = seeded[1]["out"]
    never = {c["song"] for c in partial["changes"] if c["old"] is None and c["new"]["decision"] == "not_found"}
    assert never and not never & {r["id"] for r in partial["rows"]["songs"]}
    assert len(partial["rows"]["songs"]) < len(whole["rows"]["songs"])
    assert len({c["new"]["decision"] for r in seeded[6:] for c in r["out"]["changes"]}) >= 4


def test_the_harvest_holds_every_test_of_test_match(made):
    import test_match as T

    tests = {name for name in vars(T) if name.startswith("test_")}
    seen = {r["case"].split("#")[0].split("[")[0] for name in ("ladder", "view", "match_all")
            for r in _records(made, name)}
    # Each test that matches anything is in the vectors (a test of the index's own writer alone may not be).
    assert len(seen) >= len(tests) - 3, sorted(tests - seen)
    assert {r["out"] for r in _records(made, "stage")} >= {"matched to radiohead/creep", "ignored in overrides.toml"}


def test_the_vectors_are_the_same_on_another_run(made, tmp_path):
    assert every_file(tmp_path) == made
