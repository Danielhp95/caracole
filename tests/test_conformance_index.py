"""The index merge, for the phone: what ``index_transfer.merge`` takes of a ``caracole index export`` file into a
database, what ``index_transfer.newest`` says of a database's indexes, and how ``stamps.parse`` reads a time, written
for the Kotlin port's core.index (IndexTransfer, Stamps) to agree with.

**Runtime data**: tests/conformance/data/caracole/schema/fresh_kv.json, ``{"kv": {key: value}}``, the kv records a
freshly migrated caracole database holds once each site's index has made its keys current on its empty tables
(``index_transfer._current_keys`` of every site, as a merge runs it after taking a site): the keys records
(``ug:artist_tabs:keys``, ``lacuerda:index:keys``, ``harptabs:index:keys``, ``harptabs:artists:keys``,
``gametabs:games:keys``), by key. ``IndexTransfer.seedFresh`` puts them in a new phone database, so that its first
merge of an export this caracole made finds the keys records the export holds and re-keys nothing.

**Fixtures** (``vectors/index/fixtures/<name>.jsonl``, helpers.corpus's format), each built with caracole's own
writers (test_index_transfer.py's: the indexes' own stores, at the times below), every stamp caracole writes as now
made ``BUILT``:

- ``full-export``: every site's index on the computer, as ``index_transfer.export`` writes it, a raw fixture (its
  ``CREATE`` lines, then its rows, its ``kv`` and ``caracole_export`` tables among them; ``source`` made a fixed
  path). Some pages and sitemaps read ``EARLY``, some ``LATE``; a record of odd times and numbers
  (``gtptabs:sitemaps``' ``sitemap-tabs-9.xml``: a time that isn't one, ``1.50``, an escaped ``é``); and one row of
  each re-keyed table whose keys no reading of its names gives (``STALE``), which a merge that re-keys nothing keeps.
- ``partial-export``: its gtptabs.com and MuseScore alone. ``rekey-export``: ``full-export`` made by an older
  normalizer: its ``keys`` (META) and its kv keys records ``"1"``, ``harptabs:index:keys`` absent (a merge goes by
  the kv records). ``schema-export``, ``format-export``: META's ``schema`` ``"14"``, ``format`` ``"2"``;
  ``columns-export``: ``gtptabs_index`` with a column more; ``nometa-export``: no ``caracole_export`` table.
- ``fresh-before``: a new phone database, ``fresh_kv.json`` seeded; ``unseeded-before``: the same without it (its
  first merge re-keys every index whole); ``phone-before``: a phone's indexes, some pages read later than the
  computer's, some earlier, some the computer never read, a time written with an offset (``gtptabs:sitemaps``' second
  sitemap, ``LATE`` at +02:00), a record that isn't an object, and its songs (matched, pinned, in review, ignored),
  which new tabs of theirs mark to fetch again.
- ``<case>-after``: the phone after a merge (``dump_fixture``, ``phone:schema`` among its kv, as the replay makes the
  phone's tables).
- ``stamps``, ``overflow``: phones for ``newest`` alone: odd times in every place it reads one; a time a UTC
  conversion takes out of range (``OverflowError``).

**Vectors**:

- ``merge.jsonl``: ``{fn: "caracole.index_transfer.merge", fixture: {export, before, after}, kw: {now, sites},
  out | err}``. The export replayed into a file of its own (``Fixtures.loadRaw``), the phone into a new database
  (``Fixtures.load``), then merged at ``now`` (a stamp; a song marked to fetch again takes it as its
  ``updated_at``); ``after`` is the phone's dump then (for a refusal, ``before``: nothing written). ``out``:
  ``{changed, backup, sites: [{site, taken: [[noun, count]…], records: […], rows: {table: [before, after]}}…]}``,
  Python's ``Merged``, ``backup`` whether it backed the database up first (the Kotlin merge's callback, called once,
  before the first change, or never). ``err``: ``"TransferError"``, nothing written.
- ``newest.jsonl``: ``{fn: "caracole.index_transfer.newest", fixture, out | err}``, over each phone fixture replayed.
- ``sites.jsonl``: ``{fn: "caracole.index_transfer.SITES", args: [name], out: {name, title, tables, kv}}``, each site
  in caracole's order.
- ``stamps.jsonl``: ``{fn: "caracole.stamps.parse", args: [value], out | err}``: ``out`` the time in UTC as
  ``datetime.isoformat`` writes it (``"2026-10-18T03:30:00+00:00"``, microseconds when there are any), or null;
  ``err`` ``"OverflowError"`` (a UTC conversion out of range) or ``"TypeError"`` (a value that is neither a string nor
  false, which merge's records may hold). ``datetime.fromisoformat``'s C reading, its edges and a seeded sample
  around them.
"""

from __future__ import annotations

import json
import random
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from caracole import (
    db,
    gametabs_fetch,
    gtptabs_fetch,
    harptabs_fetch,
    index_transfer,
    lacuerda_index,
    musescore_fetch,
    site_index,
    stamps,
)
from helpers.corpus import DATA, VECTORS, check, dump_fixture, jsonl, read_fixture, replay_fixture

MADE_BY = "tests/test_conformance_index.py"
FRESH_KV = DATA / "schema" / "fresh_kv.json"
INDEX = VECTORS / "index"
FIXTURES = INDEX / "fixtures"

EARLY = datetime(2026, 10, 19, 3, 30, tzinfo=UTC)
MID = datetime(2026, 10, 23, 3, 30, tzinfo=UTC)
LATE = datetime(2026, 10, 28, 3, 30, tzinfo=UTC)
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
BUILT = "2026-11-01T00:00:00Z"  # every stamp caracole writes as now, while the fixtures are built
SOURCE = "/var/lib/caracole/state/caracole.sqlite"  # the export's META source, the computer's database
STALE = "stale-key"
SONG_DONGYE = "https://www.ultimate-guitar.com/artist/634073"
SODA = "https://www.ultimate-guitar.com/artist/soda-stereo_1186"
GTP = "https://gtptabs.com/tabs/"


def _stamp(at: datetime) -> str:
    return stamps.stamp(at)


# --- the worlds ------------------------------------------------------------------------------------------------------


def computer(conn: sqlite3.Connection) -> None:
    """The computer's indexes, the export's source: every site's, some pages read early, some late."""
    import test_index_transfer as tt
    from caracole.lacuerda import LCSong, SearchAnswer, SearchSong

    tt.ug_sitemap(conn, "1", ["radiohead/creep-chords-4169", "radiohead/creep-acoustic-chords-4170",
                              "oasis/wonderwall-chords-27596"], LATE)
    tt.ug_sitemap(conn, "2", ["blur/song-2-chords-1001"], EARLY)
    tt.ug_sitemap(conn, "3", ["muse/uprising-chords-555"], LATE)
    tt.ug_listed(conn, ["1", "2", "3"], LATE)
    tt.artist_tab(conn, SONG_DONGYE, 2001, "斑马 斑马", LATE)
    tt.artist_tab(conn, SONG_DONGYE, 2002, "安和桥", EARLY)
    tt.artist_tab(conn, SODA, 3001, "De Música Ligera", LATE)
    tt.listing(conn, "tabs/e/index0.html", [("estopa", "Estopa"), ("enanitos_verdes", "Enanitos Verdes")], LATE)
    tt.listing(conn, "tabs/s/index0.html", [("soda_stereo", "Soda Stereo")], EARLY)
    db.kv_set(conn, lacuerda_index.COMPLETE_KEY, _stamp(LATE))
    tt.artist_songs(conn, "estopa", "Estopa", ["Como Camarón", "Vino Tinto"])
    tt.artist_songs(conn, "soda_stereo", "Soda Stereo", ["De Música Ligera"])
    lacuerda_index.store_search(conn, SearchAnswer(songs=(
        SearchSong("bunbury", "Enrique Bunbury", LCSong("lady_blue", "Lady Blue", "RA", (1,))),
        SearchSong("bunbury", "Enrique Bunbury", LCSong("maldito_duende", "Maldito Duende", "R", (1,))))))
    tt.sitemap(conn, gtptabs_fetch.SITE, "sitemap-tabs-1.xml", [f"{GTP}2/blur.html", f"{GTP}2/blur/song-2-2.html"],
               LATE)
    tt.sitemap(conn, gtptabs_fetch.SITE, "sitemap-tabs-2.xml", [f"{GTP}18/radiohead.html",
                                                                f"{GTP}18/radiohead/creep.html"], EARLY)
    db.kv_set(conn, gtptabs_fetch.SITE.complete_key, _stamp(EARLY))
    tt.sitemap(conn, musescore_fetch.SITE, "song-1", ["https://musescore.com/song/wonderwall-1524"], LATE)
    tt.sitemap(conn, harptabs_fetch.SITE, site_index.ONE, ["https://www.harptabs.com/artist/1178/billy-joel",
                                                           "https://www.harptabs.com/tab/25/piano-man",
                                                           "https://www.harptabs.com/tab/26/can-t-help-falling"], LATE)
    db.kv_set(conn, harptabs_fetch.KEYS_KEY, harptabs_fetch.ROW_KEYS)
    tt.harp_page(conn, "artist/1178/billy-joel", ["Piano Man", "Honesty"], LATE)
    tt.harp_page(conn, "artist/50/the-beatles", ["Yesterday"], EARLY)
    db.kv_set(conn, harptabs_fetch.SITE.complete_key, _stamp(LATE))
    tt.sitemap(conn, gametabs_fetch.SITE, "sitemap-games.xml", ["https://gametabs.net/tabs/actraiser",
                                                                "https://gametabs.net/tabs/actraiser/fillmore"], LATE)
    tt.game_page(conn, "tabs/actraiser", ["Fillmore", "Bloodpool"], LATE)
    tt.game_page(conn, "tabs/hollow-knight", ["Greenpath"], EARLY)
    db.kv_set(conn, gametabs_fetch.SITE.complete_key, _stamp(LATE))
    # A record a merge reads as Python's json.loads reads it, and writes back as json.dumps writes it.
    records = json.loads(db.kv_get(conn, gtptabs_fetch.SITE.sitemaps_key))
    text = json.dumps(records, ensure_ascii=False)[:-1]
    text += ', "sitemap-tabs-9.xml": {"checked_at": "not a time", "rows": 1.50, "etag": "\\u00e9", "keys": 2}}'
    db.kv_set(conn, gtptabs_fetch.SITE.sitemaps_key, text)
    games = json.loads(db.kv_get(conn, gametabs_fetch.SITE.sitemaps_key))
    db.kv_set_json(conn, gametabs_fetch.SITE.sitemaps_key, {**games, "junk": 5})
    # What a re-key makes again: one row of each such table keyed as no reading of its names keys it.
    conn.execute("UPDATE ug_artist_tabs SET artist_forms = ? WHERE tab_id = 3001", (STALE,))
    conn.execute("UPDATE lacuerda_index SET artist_key = ? WHERE path = 'enanitos_verdes/'", (STALE,))
    conn.execute("UPDATE harptabs_index SET key = ? WHERE path = 'tab/26/can-t-help-falling'", (STALE,))
    conn.execute("UPDATE harptabs_artist_tabs SET song_key = ? WHERE title = 'Honesty'", (STALE,))
    conn.execute("UPDATE gametabs_game_tabs SET title_key = ? WHERE title = 'Bloodpool'", (STALE,))


def phone(conn: sqlite3.Connection) -> None:
    """The phone's indexes, merged into, and its songs."""
    import test_index_transfer as tt
    from caracole.lacuerda import LCSong, SearchAnswer, SearchSong
    from conftest import add_song

    from caracole.songs import update_song

    for key, value in json.loads(fresh_kv_text())["kv"].items():
        db.kv_set(conn, key, value)
    # Ultimate Guitar: sitemap 1 read before the computer's read (taken), 2 after (kept), 4 the phone's own.
    tt.ug_sitemap(conn, "1", ["radiohead/creep-chords-4169", "radiohead/creep-live-chords-4171"], MID)
    tt.ug_sitemap(conn, "2", ["blur/song-2-chords-1001", "blur/parklife-chords-1002"], MID)
    tt.ug_sitemap(conn, "4", ["radiohead/karma-police-chords-9001"], MID)
    conn.execute("UPDATE ug_index SET path = 'radiohead/creep-old-chords-4169', song_key = 'creep-old' "
                 "WHERE tab_id = 4169")
    tt.ug_listed(conn, ["1", "2", "4"], MID)
    tt.artist_tab(conn, SONG_DONGYE, 2001, "斑马 斑马", MID)
    tt.artist_tab(conn, SONG_DONGYE, 2002, "安和桥 (live)", LATE)
    tt.artist_tab(conn, "https://www.ultimate-guitar.com/artist/12", 4001, "春天里", MID)
    # LaCuerda: e read before (taken), s after (kept), b the phone's own; Estopa's page its own (theirs not taken).
    tt.listing(conn, "tabs/e/index0.html", [("estopa", "Estopa")], MID)
    tt.listing(conn, "tabs/s/index0.html", [("soda_stereo", "Soda Stereo"), ("sabina", "Joaquín Sabina")], LATE)
    tt.listing(conn, "tabs/b/index0.html", [("bunbury", "Enrique Bunbury")], MID)
    db.kv_set(conn, lacuerda_index.COMPLETE_KEY, _stamp(MID))
    tt.artist_songs(conn, "estopa", "Estopa", ["Como Camarón"])
    lacuerda_index.store_search(conn, SearchAnswer(songs=(
        SearchSong("bunbury", "Enrique Bunbury", LCSong("lady_blue", "Lady Blue", "RA", (1,))),)))
    # gtptabs.com: 1 read before (taken), 2 after, its time written at +02:00 (kept); read whole later than theirs.
    tt.sitemap(conn, gtptabs_fetch.SITE, "sitemap-tabs-1.xml", [f"{GTP}2/blur.html"], MID)
    tt.sitemap(conn, gtptabs_fetch.SITE, "sitemap-tabs-2.xml", [f"{GTP}18/radiohead.html"], LATE)
    records = json.loads(db.kv_get(conn, gtptabs_fetch.SITE.sitemaps_key))
    records["sitemap-tabs-2.xml"]["checked_at"] = "2026-10-28T05:30:00+02:00"
    db.kv_set_json(conn, gtptabs_fetch.SITE.sitemaps_key, records)
    db.kv_set(conn, gtptabs_fetch.SITE.complete_key, _stamp(MID))
    # harptabs.com: its sitemap read before (taken), Billy Joel's page before (taken), the Beatles' after (kept).
    tt.sitemap(conn, harptabs_fetch.SITE, site_index.ONE, ["https://www.harptabs.com/artist/1178/billy-joel"], MID)
    records = json.loads(db.kv_get(conn, harptabs_fetch.SITE.sitemaps_key))
    db.kv_set_json(conn, harptabs_fetch.SITE.sitemaps_key, {"old": "x", **records})
    tt.harp_page(conn, "artist/1178/billy-joel", ["Piano Man"], MID)
    tt.harp_page(conn, "artist/50/the-beatles", ["Yesterday", "Let It Be"], LATE)
    tt.harp_page(conn, "artist/7/bob-dylan", ["Blowin' in the Wind"], MID)
    # gametabs.net: its sitemap before (taken), Actraiser's page before (taken), Hollow Knight's after (kept).
    tt.sitemap(conn, gametabs_fetch.SITE, "sitemap-games.xml", ["https://gametabs.net/tabs/actraiser"], MID)
    tt.game_page(conn, "tabs/actraiser", ["Fillmore"], MID)
    tt.game_page(conn, "tabs/hollow-knight", ["Greenpath", "Dirtmouth"], LATE)
    db.kv_set(conn, gametabs_fetch.SITE.complete_key, _stamp(LATE))
    # Songs: new tabs of theirs mark the matched and the pinned to fetch again, never one in review or ignored.
    for artist, title, decision, keys, ignored in (
            ("Oasis", "Wonderwall", "accept", ("oasis", "wonderwall"), False),
            ("Radiohead", "Creep", "pinned", ("radiohead", "creep"), False),
            ("Blur", "Song 2", "accept", ("blur", "song-2"), False),
            ("Muse", "Uprising", "accept", ("muse", "uprising"), True),
            ("Oasis", "Champagne Supernova", "review", ("oasis", "wonderwall"), False)):
        song = add_song(conn, artist, title)
        update_song(conn, song.id, match_decision=decision, match_artist_key=keys[0], match_song_key=keys[1],
                    ug_dirty=False, **({"status": "ignored"} if ignored else {}))


def newest_stamps(conn: sqlite3.Connection) -> None:
    """Odd times in each place newest reads one."""
    from caracole.ug import index as ug

    db.kv_set_json(conn, ug.SITEMAPS_KEY, {
        "a": {"indexed_at": "2026-10-20T05:00:00+02:00"}, "b": {"indexed_at": 5}, "c": "x",
        "d": {"indexed_at": "garbage"}, "e": {"indexed_at": "2026-10-20T03:00:00.999999Z"}, "f": {}})
    conn.execute(
        "INSERT INTO ug_artist_tabs (page, tab_id, type, artist, title, url, artist_key, song_key, artist_forms, "
        "title_forms, forms, read_at) VALUES ('p', 1, 'chords', 'A', 'B', 'u', 'a', 'b', 'a', 'b', 'a b', "
        "'2026-10-19')")
    db.kv_set(conn, ug.REFRESHED_KEY, "2026-10-19T23:00:00-05:00")
    db.kv_set_json(conn, lacuerda_index.PAGES_KEY, {"tabs/a/index0.html": {"checked_at": "2026-W43-2"}})
    db.kv_set(conn, lacuerda_index.COMPLETE_KEY, "")
    db.kv_set(conn, gtptabs_fetch.SITE.complete_key, "2026-10-18 23:00:00-05:00")
    db.kv_set_json(conn, gtptabs_fetch.SITE.sitemaps_key, {"x": {"checked_at": "20261017T120000,5+0130"}})
    db.kv_set_json(conn, musescore_fetch.SITE.sitemaps_key, {"x": {"checked_at": None}})
    conn.execute("INSERT INTO harptabs_artists (path, page_id, key, name, tabs, read_at) "
                 "VALUES ('artist/1/a', 1, 'a', 'A', 0, 'garbage')")
    conn.execute("INSERT INTO gametabs_games (path, game, name, tabs, read_at) "
                 "VALUES ('tabs/a', 'a', 'A', 0, '2026-10-22T24:00:00')")
    db.kv_set(conn, gametabs_fetch.SITE.complete_key, "2026-10-22T23:59:59.999999")


def newest_overflow(conn: sqlite3.Connection) -> None:
    """A time whose UTC is before the first day: datetime's OverflowError, newest's too."""
    db.kv_set(conn, gtptabs_fetch.SITE.complete_key, "0001-01-01T00:00:00+01:00")


# --- the exports -----------------------------------------------------------------------------------------------------


def _patch_rekey(c: sqlite3.Connection) -> None:
    c.execute(f"UPDATE {index_transfer.META} SET value = '1' WHERE key = 'keys'")
    c.execute("UPDATE kv SET value = '1' WHERE key IN ('ug:artist_tabs:keys', 'lacuerda:index:keys', "
              "'harptabs:artists:keys', 'gametabs:games:keys')")
    c.execute("DELETE FROM kv WHERE key = 'harptabs:index:keys'")


EXPORTS: dict[str, tuple[tuple[str, ...] | None, Any]] = {
    "full": (None, None),
    "partial": (("gtptabs", "musescore"), None),
    "rekey": (None, _patch_rekey),
    "schema": (None, lambda c: c.execute(f"UPDATE {index_transfer.META} SET value = '14' WHERE key = 'schema'")),
    "format": (None, lambda c: c.execute(f"UPDATE {index_transfer.META} SET value = '2' WHERE key = 'format'")),
    "columns": (None, lambda c: c.execute("ALTER TABLE gtptabs_index ADD COLUMN extra TEXT")),
    "nometa": (None, lambda c: c.execute(f"DROP TABLE {index_transfer.META}")),
}

PHONES: dict[str, Any] = {
    "fresh": lambda conn: [db.kv_set(conn, k, v) for k, v in json.loads(fresh_kv_text())["kv"].items()],
    "unseeded": lambda conn: None,
    "phone": phone,
    "stamps": newest_stamps,
    "overflow": newest_overflow,
}

# Each merge: its name (its after's), the export, the phone before (a fixture), the sites asked for.
MERGES: list[tuple[str, str, str, list[str] | None]] = [
    ("fresh", "full", "fresh-before", None),
    ("unseeded", "full", "unseeded-before", None),
    ("phone", "full", "phone-before", None),
    ("again", "full", "phone-after", None),
    ("phone-sites", "full", "phone-before", ["musescore", "gtptabs"]),
    ("rekey", "rekey", "phone-before", None),
    ("fresh-rekey", "rekey", "fresh-before", None),
    ("partial", "partial", "phone-before", None),
    ("partial-gtptabs", "partial", "phone-before", ["gtptabs"]),
    ("schema", "schema", "phone-before", None),
    ("format", "format", "phone-before", None),
    ("columns", "columns", "phone-before", None),
    ("nometa", "nometa", "phone-before", None),
    ("not-held", "partial", "phone-before", ["ug"]),
    ("unknown", "partial", "phone-before", ["spotify"]),
]

NEWEST = ["fresh-before", "unseeded-before", "phone-before", "phone-after", "fresh-after", "unseeded-after",
          "rekey-after", "partial-after", "phone-sites-after", "stamps-before", "overflow-before"]


# --- making them -----------------------------------------------------------------------------------------------------


def fresh_kv_text() -> str:
    """fresh_kv.json: what each site's ensure_current_keys sets in a new database."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp, closing(db.connect(Path(tmp) / "caracole.sqlite")) as conn:
        before = dict(conn.execute("SELECT key, value FROM kv").fetchall())
        for name in index_transfer.SITES:
            index_transfer._current_keys(conn, name)
        after = dict(conn.execute("SELECT key, value FROM kv").fetchall())
    made = {key: after[key] for key in sorted(after) if before.get(key) != after[key]}
    return json.dumps({"kv": made}, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def _fresh(path: Path) -> sqlite3.Connection:
    from conftest import migrated_database

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(migrated_database())
    return db.connect(path)


def _settled(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (BUILT, BUILT))


def _fixture(records: list[dict[str, Any]], name: str) -> str:
    return jsonl(records, corpus=f"index/fixtures/{name}", made_by=MADE_BY)


def _report(merged: index_transfer.Merged) -> dict[str, Any]:
    return {"changed": merged.changed, "backup": merged.backup is not None,
            "sites": [{"site": s.site, "taken": [list(t) for t in s.taken], "records": list(s.records),
                       "rows": {t: list(r) for t, r in s.rows.items()}} for s in merged.sites]}


class Corpus:
    """Every file of the corpus, made in ``workdir`` once."""

    def __init__(self, workdir: Path, monkeypatch: pytest.MonkeyPatch):
        self.workdir = workdir
        self.monkeypatch = monkeypatch
        self.texts: dict[str, str] = {}
        self.merges: list[dict[str, Any]] = []
        self._made = False

    def _clock(self, stamp: str) -> None:
        from caracole import songs

        self.monkeypatch.setattr(songs, "utc_now_iso", lambda: stamp)

    def make(self) -> None:
        if self._made:
            return
        self._made = True
        self._clock(BUILT)
        with closing(_fresh(self.workdir / "computer" / "caracole.sqlite")) as conn:
            computer(conn)
            for name, (sites, patch) in EXPORTS.items():
                path = self.workdir / "exports" / f"{name}.sqlite"
                path.parent.mkdir(parents=True, exist_ok=True)
                index_transfer.export(conn, path, sites, now=NOW)
                with closing(sqlite3.connect(path, isolation_level=None)) as out:
                    out.execute(f"UPDATE {index_transfer.META} SET value = ? WHERE key = 'source'", (SOURCE,))
                    if patch is not None:
                        patch(out)
                    out.execute("VACUUM")
                    self.texts[f"{name}-export"] = _fixture(dump_fixture(out, raw=True), f"{name}-export")
        for name, build in PHONES.items():
            with closing(_fresh(self.workdir / "phones" / name / "caracole.sqlite")) as conn:
                build(conn)
                _settled(conn)
                self.texts[f"{name}-before"] = _fixture(dump_fixture(conn), f"{name}-before")
        for name, export, before, sites in MERGES:
            self._merge(name, export, before, sites)

    def replayed_export(self, name: str, where: Path) -> Path:
        path = where / "export.sqlite"
        with closing(sqlite3.connect(path, isolation_level=None)) as out:
            replay_fixture(out, read_fixture(self.texts[f"{name}-export"]))
        return path

    def replayed(self, fixture: str, where: Path) -> sqlite3.Connection:
        conn = _fresh(where / "state" / "caracole.sqlite")
        replay_fixture(conn, read_fixture(self.texts[fixture]))
        return conn

    def _merge(self, name: str, export: str, before: str, sites: list[str] | None) -> None:
        where = self.workdir / "merges" / name
        where.mkdir(parents=True)
        path = self.replayed_export(export, where)
        record: dict[str, Any] = {"fn": "caracole.index_transfer.merge", "kw": {"now": _stamp(NOW), "sites": sites}}
        with closing(self.replayed(before, where)) as conn:
            self._clock(_stamp(NOW))
            replayed = dump_fixture(conn)
            try:
                merged = index_transfer.merge(conn, path, sites, state_dir=where / "state", now=NOW)
            except index_transfer.TransferError:
                record["err"] = "TransferError"
                after = before
                assert dump_fixture(conn) == replayed  # nothing written
                assert not (where / "state" / "backups").exists() or not list((where / "state" / "backups").iterdir())
            else:
                record["out"] = _report(merged)
                after = f"{name}-after"
                self.texts[after] = _fixture(dump_fixture(conn), after)
            finally:
                self._clock(BUILT)
        record["fixture"] = {"export": f"{export}-export", "before": before, "after": after}
        self.merges.append(record)

    def newest(self) -> list[dict[str, Any]]:
        out = []
        for fixture in NEWEST:
            where = self.workdir / "newest" / fixture
            where.mkdir(parents=True)
            record: dict[str, Any] = {"fn": "caracole.index_transfer.newest", "fixture": fixture}
            with closing(self.replayed(fixture, where)) as conn:
                try:
                    record["out"] = index_transfer.newest(conn)
                except OverflowError:
                    record["err"] = "OverflowError"
            out.append(record)
        return out


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Corpus:
    with pytest.MonkeyPatch.context() as monkeypatch:
        made = Corpus(tmp_path_factory.mktemp("index-corpus"), monkeypatch)
        made.make()
        yield made


# --- stamps.parse ------------------------------------------------------------------------------------------------

STAMPS = [
    "2026-10-18T03:30:00Z", "2026-10-18T03:30:00", "2026-10-18", "20261018", "2026-W42-7", "2026W427", "2026-W42",
    "2026W42", "2026-W53-1", "2020-W53-7", "2026-W00-1", "2026-W01-0", "2026-W01-8", "0001-W01-1", "9999-W52-5",
    "9999-W52-6", "2026-10-18 03:30", "2026-10-18T03", "2026-10-18T0330", "2026-10-18T033000", "20261018T033000Z",
    "2026-10-18T03:30:00.5", "2026-10-18T03:30:00,5", "2026-10-18T03:30:00.123456789123", "2026-10-18T033000,5",
    "2026-10-18T03:30:00+02:00", "2026-10-18T03:30:00-05:30", "2026-10-18T03:30:00+0530", "2026-10-18T03:30:00+05",
    "2026-10-18T03:30:00-00:00", "2026-10-18T03:30:00+23:59:59.999999", "2026-10-18T03:30:00-23:59:59.999999",
    "2026-10-18T03:30:00+24:00", "2026-10-18T03:30:00+05:60", "2026-10-18T03:30:00+05:30:60",
    "2026-10-18T03:30:00+00:00:00.000001", "2026-10-18T03:30:00+0", "2026-10-18T03:30:00+053",
    "2026-10-18T24:00:00", "2026-10-18T24:00", "2026-10-18T24", "2026-12-31T24:00", "2026-02-28T24:00Z",
    "2024-02-29T24:00:00-00:00", "2026-02-29T24:00", "2026-10-00T24:00", "2026-00-00T24:00:00", "2026-13-01T24:00",
    "9999-12-31T24:00", "2026-10-18T24:00:01", "2026-10-18T24:00:00.0000001", "2026-10-18T25:00",
    "2026-10-18T03:60", "2026-10-18T03:30:60", "2026-10-18T", "2026-10-18T03:30:00.", "2026-10-18T03:30:00.Z",
    "2026-10-18T03:30:00+", "2026-10-18T03:30:00-", "2026-10-18T03:30:00ZZ", "2026-10-18T03:30:00Z+05",
    "2026-10-18T03:30:00Z ", "2026-10-18T03:30:00 ", "2026-10-18T3:30", "2026-10-18T0330:00", "2026-10-18T03:3000",
    "2026-10-18T03:30:00.12a", "2026-10-18T03,5", "2026-10-18T03:30,5", "2026-10-18T03:30:00x+05:00",
    "2026-10-18T03:30:00xZ", "2026-10-18T03:30:00x", "2026-10-18T03x+05", "2026-10-18T03:30:001Z",
    "2026-10-18T03:30:00ab+05:00", "2026-10-18 03:30:00.123456T+05:30", "20261018T03300005-0130",
    "2026-10-18é03:30", "2026-10-18€03:30", "2026-10-18𝄞03:30", "20261018é0330", "2026W42é03", "2026-W42-7é03",
    "2026-10-18T03:30:00é+05:00", "2026-10-18T03:30:00.5é+05:00", "2026-10-18 03:30:00.123456٣+0530",
    "2026-10-18é", "２０２６-10-18", "2026-10-1٨", "2026-291", "2026-1018", "2026101", "2261018", "0000-01-01",
    "0001-01-01T00:00:00", "0001-01-01T00:00:00+01:00", "0001-01-01T00:59:59.999999-00:00:00.000001",
    "9999-12-31T23:59:59.999999", "9999-12-31T23:59:59-01:00", "9999-12-31T23:59:59+01:00", "", "x", "2026",
    "2026-10", "2026-1-1", " 2026-10-18", "+2026-10-18", "2026_10_18", "2026-10-18\x00", "2026-10-18T03:30\x00Z",
]
NOT_STRINGS: list[Any] = [None, 0, 0.0, -0.0, False, [], {}, 5, 1.5, True, [1], {"a": 1}]
FUZZ_SEEDS = ["2026-10-18T03:30:00Z", "2026-W42-7T03:30:00.123+01:00", "20261018T0330", "2026W427 0330,1234567-0100",
              "2026-12-31T24:00:00", "2026W53", "2026-10-18 03:30:00.123456+05:30", "20261018T033000.5-0130"]
FUZZ_ALPHABET = "0123456789" * 3 + "-:T Z+.,W é ٣１_x\x00"


def _fuzzed(n: int) -> list[str]:
    """Mutations of times, seeded: the edges of the reading, a sample around them."""
    rng = random.Random(20261103)
    out: list[str] = []
    while len(out) < n:
        s = list(rng.choice(FUZZ_SEEDS))
        for _ in range(rng.randint(1, 3)):
            i, op = rng.randint(0, len(s)), rng.randint(0, 2)
            if op == 0 and s:
                s.pop(min(i, len(s) - 1))
            elif op == 1:
                s.insert(i, rng.choice(FUZZ_ALPHABET))
            elif s:
                s[min(i, len(s) - 1)] = rng.choice(FUZZ_ALPHABET)
        text = "".join(s)
        if text not in out:
            out.append(text)
    return out


def _parsed(value: Any) -> dict[str, Any]:
    record: dict[str, Any] = {"fn": "caracole.stamps.parse", "args": [value]}
    try:
        when = stamps.parse(value)
    except (OverflowError, TypeError) as e:
        record["err"] = type(e).__name__
    else:
        record["out"] = None if when is None else when.isoformat()
    return record


def stamps_text() -> str:
    values = [*STAMPS, *[f for f in _fuzzed(1500) if f not in STAMPS], *NOT_STRINGS]
    return jsonl([_parsed(v) for v in values], corpus="index/stamps", made_by=MADE_BY)


# --- the tests ---------------------------------------------------------------------------------------------------


def test_fresh_kv_json_is_what_a_new_database_holds_once_each_index_made_its_keys_current():
    text = fresh_kv_text()
    check(FRESH_KV, text)
    assert set(json.loads(text)["kv"]) == {"ug:artist_tabs:keys", "lacuerda:index:keys", "harptabs:index:keys",
                                           "harptabs:artists:keys", "gametabs:games:keys"}


@pytest.mark.parametrize("name", [*(f"{e}-export" for e in EXPORTS), *(f"{p}-before" for p in PHONES),
                                  *(f"{m[0]}-after" for m in MERGES if m[0] not in
                                    ("schema", "format", "columns", "nometa", "not-held", "unknown"))])
def test_a_fixture_is_its_database_dumped(corpus, name):
    check(FIXTURES / f"{name}.jsonl", corpus.texts[name])


def test_merge_jsonl_is_what_index_transfer_merge_takes(corpus):
    check(INDEX / "merge.jsonl", jsonl(corpus.merges, corpus="index/merge", made_by=MADE_BY))


def test_newest_jsonl_is_what_index_transfer_newest_says(corpus):
    check(INDEX / "newest.jsonl", jsonl(corpus.newest(), corpus="index/newest", made_by=MADE_BY))


def test_stamps_jsonl_is_how_stamps_parse_reads_a_time():
    check(INDEX / "stamps.jsonl", stamps_text())


def test_sites_jsonl_is_index_transfers_sites():
    records = [{"fn": "caracole.index_transfer.SITES", "args": [name], "out": site}
               for name, site in index_transfer.SITES.items()]
    check(INDEX / "sites.jsonl", jsonl(records, corpus="index/sites", made_by=MADE_BY))


def test_a_fresh_phone_seeded_merges_an_export_and_re_keys_nothing(corpus):
    # The done_when the Kotlin side checks too: the keys records as fresh_kv.json made them, every stale row as the
    # export holds it; the unseeded phone re-keys them all.
    def rows(fixture: str) -> list[dict[str, Any]]:
        return read_fixture(corpus.texts[fixture])

    seeded = json.loads(fresh_kv_text())["kv"]
    after = {r["kv"]: r["value"] for r in rows("fresh-after") if "kv" in r}
    assert all(after[k] == v for k, v in seeded.items())
    stale = [r for r in rows("fresh-after") if "row" in r and STALE in r["row"].values()]
    assert {r["table"] for r in stale} == {"ug_artist_tabs", "lacuerda_index", "harptabs_index",
                                           "harptabs_artist_tabs", "gametabs_game_tabs"}
    assert not [r for r in rows("unseeded-after") if "row" in r and STALE in r["row"].values()]
    assert not [r for r in rows("rekey-after") if "row" in r and STALE in r["row"].values()]


def test_the_phone_merge_takes_what_was_read_later_and_marks_the_songs_new_tabs_are_for(corpus):
    merged = next(m for m in corpus.merges if m["fixture"]["after"] == "phone-after")["out"]
    taken = {s["site"]: dict(map(tuple, s["taken"])) for s in merged["sites"]}
    assert taken["ug"] == {"sitemap": 2, "tab of its artist pages": 2}
    assert taken["lacuerda"] == {"listing page": 1, "artist page": 1, "row of its search's answers": 1}
    assert taken["gtptabs"] == {"sitemap": 2} and taken["musescore"] == {"sitemap": 1}
    assert taken["harptabs"] == {"sitemap": 1, "artist page": 1} and taken["gametabs"] == {"sitemap": 1,
                                                                                            "game page": 1}
    songs = {r["row"]["title"]: r["row"] for r in read_fixture(corpus.texts["phone-after"]) if r.get("table") == "songs"}
    assert {t for t, s in songs.items() if s["ug_dirty"]} == {"Wonderwall", "Creep"}
    assert songs["Creep"]["updated_at"] == _stamp(NOW) and songs["Song 2"]["updated_at"] == BUILT
    again = next(m for m in corpus.merges if m["fixture"]["before"] == "phone-after")["out"]
    assert not again["changed"] and not again["backup"]


def test_each_refusal_changes_nothing(corpus):
    refused = {m["fixture"]["export"] + str(m["kw"]["sites"]) for m in corpus.merges if "err" in m}
    assert refused == {"schema-exportNone", "format-exportNone", "columns-exportNone", "nometa-exportNone",
                       "partial-export['ug']", "partial-export['spotify']"}
