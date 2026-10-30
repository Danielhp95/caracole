"""The site indexes into a file of their own, and such a file into the database: ``caracole index export`` and
``caracole index merge``.

Each index costs days of polite requests to build, and lives in one database; a caracole run with other folders (a
shell's, on its home defaults, beside the service: service.py) builds into another. So an index moves between two
databases as a file: ``export`` copies a site's tables, with the kv records it keeps its progress in (``SITES``),
into a new SQLite file, in one read transaction (a consistent copy, which takes no lock); and ``merge`` takes into
the database what the file read more recently, under the lock the command holds.

**A merge** checks first that the file is an export (its ``META`` table) of this schema version, and that every
table it merges has the database's columns, else it changes nothing (``TransferError``). Then it decides, per site,
what the file read more recently, the database's records and the file's compared:

- a sitemap (UG's ``ug:sitemaps``, site_index.py's ``<provider>:sitemaps``) or a listing page of LaCuerda's
  (``lacuerda:index:pages``) the file read or checked later, or one the database never read, replaces its rows and
  its record, as reading it again would: UG's rows upserted as a refresh stores them (a row the database has keeps
  its sitemap and first sighting), and the songs its new tabs are for marked to fetch again; the others' rows
  deleted and inserted;
- a page the file read later by its ``read_at`` (harptabs.com's artist pages, gametabs.net's game pages), or one
  the database never read, replaces its tabs and its row; UG's artist pages' tabs, a row at a time, where the file's
  read is later, then filed again (ug/artist_tabs.py ``refile``);
- with no time to tell (an artist page of LaCuerda's; the songs its search answered), only a page or a song the
  database lacks is taken: the database's stays;
- a progress record moves on, never back: ``complete_at`` and UG's refresh to the later time; UG's index built once
  the file's was; the listing of UG's sitemaps the later refresh's.

So a merge never loses a page or a sitemap: what the file lacks, or read earlier, stays as it was. Each site is one
savepoint. When anything changes, the database is backed up first (backup.py, ``-before-merge``), and refused
without room for that copy; when nothing does, neither is anything written, so a second merge of the same file
changes nothing. Afterwards each index's keys are made current (``ensure_current_keys``), and made again whole where
the file's were made by another caracole's normalizer (its keys record differs). ``Merged`` says what each site
took, and its tables' rows before and after.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from caracole import __version__, backup, db, normalize, stamps

FORMAT = 1  # the export's own layout: META, kv, and each site's tables as the database has them
META = "caracole_export"
THEIRS = "theirs"  # the export, attached to the database's connection
_TAKEN = "temp._merge_taken"


class TransferError(Exception):
    """An export or a merge refused, nothing written: its words say why."""


@dataclass(frozen=True)
class Site:
    """A site's index: its name (``--site``), its name for people, its tables, and the kv records of its progress."""

    name: str
    title: str
    tables: tuple[str, ...]
    kv: tuple[str, ...]


def _sites() -> dict[str, Site]:
    from caracole import (
        gametabs_fetch,
        gametabs_index,
        gtptabs_fetch,
        harptabs_fetch,
        harptabs_index,
        lacuerda_index,
        musescore_fetch,
    )
    from caracole.ug import artist_tabs
    from caracole.ug import index as ug

    def sitemaps(site: Any) -> tuple[str, str]:
        return site.sitemaps_key, site.complete_key

    return {s.name: s for s in (
        Site("ug", "Ultimate Guitar", ("ug_index", "ug_artist_tabs"),
             (ug.SITEMAPS_KEY, ug.LISTED_KEY, ug.BUILT_KEY, ug.REFRESHED_KEY, artist_tabs.KEYS_KEY)),
        Site("lacuerda", "LaCuerda", ("lacuerda_index",),
             (lacuerda_index.PAGES_KEY, lacuerda_index.COMPLETE_KEY, lacuerda_index.KEYS_KEY)),
        Site("gtptabs", "gtptabs.com", ("gtptabs_index",), sitemaps(gtptabs_fetch.SITE)),
        Site("musescore", "MuseScore", ("musescore_index",), sitemaps(musescore_fetch.SITE)),
        Site("harptabs", "harptabs.com", ("harptabs_index", "harptabs_artists", "harptabs_artist_tabs"),
             (*sitemaps(harptabs_fetch.SITE), harptabs_fetch.KEYS_KEY, harptabs_index.KEYS_KEY)),
        Site("gametabs", "gametabs.net", ("gametabs_index", "gametabs_games", "gametabs_game_tabs"),
             (*sitemaps(gametabs_fetch.SITE), gametabs_index.KEYS_KEY)),
    )}


SITES: dict[str, Site] = _sites()


_PLURALS = {"tab of its artist pages": "tabs of its artist pages",
            "row of its search's answers": "rows of its search's answers"}


def counted(n: int, noun: str) -> str:
    """"1 game page", "2 game pages", "3 tabs of its artist pages"."""
    return f"{n:,} {noun if n == 1 else _PLURALS.get(noun, noun + 's')}"


@dataclass(frozen=True)
class Exported:
    path: Path
    sites: tuple[str, ...]
    rows: dict[str, int]
    size: int


@dataclass
class SiteMerge:
    """What a merge took of a site: ``taken``, (noun, count) for each kind of page; ``records``, its progress
    records moved on; ``rows``, each table's rows (before, after)."""

    site: str
    taken: list[tuple[str, int]] = field(default_factory=list)
    records: list[str] = field(default_factory=list)
    rows: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.taken or self.records)


@dataclass
class Merged:
    sites: list[SiteMerge]
    backup: Path | None

    @property
    def changed(self) -> bool:
        return any(s.changed for s in self.sites)


def chosen(names: Iterable[str] | None, among: Sequence[str] | None = None) -> tuple[str, ...]:
    """The sites ``names`` names, in caracole's order (every one of ``among``, else of ``SITES``, with none)."""
    known = tuple(among) if among is not None else tuple(SITES)
    if not names:
        return known
    wanted = list(dict.fromkeys(names))
    unknown = [n for n in wanted if n not in SITES]
    if unknown:
        raise TransferError(f"no site {unknown[0]!r}: the indexes are {', '.join(SITES)}")
    return tuple(n for n in SITES if n in wanted)


# --- export --------------------------------------------------------------------------------------------------------


def export(conn: sqlite3.Connection, path: Path, sites: Iterable[str] | None = None, *, now: datetime) -> Exported:
    """The indexes of ``sites`` (every one with none) into a new file at ``path``, in one read transaction; a file
    there already, or the database itself, is refused. Written under a name of its own, then renamed."""
    names = chosen(sites)
    if _same_file(path, _db_path(conn)):
        raise TransferError(f"{path} is the database itself: name a new file")
    if os.path.lexists(path):
        raise TransferError(f"{path} already exists: name a new file, or remove that one first")
    if not path.parent.is_dir():
        raise TransferError(f"{path.parent} is no folder: name a file in one")
    part = path.with_name(f"{path.name}.{secrets.token_hex(6)}.part")
    tables = [t for n in names for t in SITES[n].tables]
    keys = [k for n in names for k in SITES[n].kv]
    try:
        _write_export(conn, part, names, tables, keys, now)
        os.replace(part, path)
    except (OSError, sqlite3.Error) as e:
        raise TransferError(f"can't write {path}: {e}") from e
    finally:
        part.unlink(missing_ok=True)
    counts = {table: _count(path, table) for table in tables}
    return Exported(path, names, counts, path.stat().st_size)


def _write_export(conn: sqlite3.Connection, part: Path, names: Sequence[str], tables: Sequence[str],
                  keys: Sequence[str], now: datetime) -> None:
    """The export's tables, as the database has them, made in a file of their own, then filled from the
    database in one transaction: one snapshot of it for every table, a consistent copy."""
    out = sqlite3.connect(part)
    try:
        for table in tables:
            (sql,) = conn.execute("SELECT sql FROM main.sqlite_master WHERE type = 'table' AND name = ?",
                                  (table,)).fetchone()
            out.execute(sql)
        out.execute("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        out.execute(f"CREATE TABLE {META} (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        out.executemany(f"INSERT INTO {META} (key, value) VALUES (?, ?)", [
            ("format", str(FORMAT)), ("schema", str(db.SCHEMA_VERSION)), ("keys", str(normalize.KEY_VERSION)),
            ("caracole", __version__), ("exported_at", stamps.stamp(now)), ("sites", json.dumps(list(names))),
            ("source", str(_db_path(conn) or "")),
        ])
        out.commit()
    finally:
        out.close()
    conn.execute("ATTACH DATABASE ? AS exported", (str(part),))
    try:
        conn.execute("BEGIN")
        try:
            for table in tables:
                cols = ", ".join(_columns(conn, "main", table))
                conn.execute(f"INSERT INTO exported.{table} ({cols}) SELECT {cols} FROM main.{table}")
            marks = ", ".join("?" for _ in keys)
            conn.execute(f"INSERT INTO exported.kv (key, value) SELECT key, value FROM main.kv WHERE key IN "
                         f"({marks})", list(keys))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.execute("DETACH DATABASE exported")


def _count(path: Path, table: str) -> int:
    file = sqlite3.connect(_read_only(path), uri=True)
    try:
        return file.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        file.close()


def _read_only(path: Path) -> str:
    """A file's URI, opened read-only: whatever its name holds (a ``?``, a ``#``), percent-encoded."""
    return f"{path.resolve().as_uri()}?mode=ro"


# --- merge ---------------------------------------------------------------------------------------------------------


def merge(conn: sqlite3.Connection, path: Path, sites: Iterable[str] | None = None, *, state_dir: Path,
          now: datetime) -> Merged:
    """Take into the database what the export at ``path`` read more recently, site by site (``sites``: every one
    the file holds, with none), after a copy of it in ``state_dir``'s backups; see the module docstring.
    ``TransferError`` when it is refused, nothing written; backup.py's ``BackupError`` when the copy fails."""
    meta = _meta(path)
    names = _merged_sites(path, meta, sites)
    if _same_file(path, _db_path(conn)):
        raise TransferError(f"{path} is the database itself")
    with _attached(conn, path):
        _check_columns(conn, path, names)
        plans = [_plan(conn, name) for name in names]
    if not any(p.changes for p in plans):
        return Merged([SiteMerge(p.site) for p in plans], None)
    copy = backup.make(conn, state_dir, now, label=backup.MERGE)
    if isinstance(copy, backup.Skipped):
        raise TransferError(f"{copy.reason}, and a merge backs the database up first")
    done: list[SiteMerge] = []
    with _attached(conn, path):
        for plan in plans:
            done.append(_apply(conn, plan))
    return Merged(done, copy.backup.path)


def _meta(path: Path) -> dict[str, str]:
    if not path.exists():
        raise TransferError(f"{path}: no such file")
    try:
        file = sqlite3.connect(_read_only(path), uri=True)
        try:
            meta = dict(file.execute(f"SELECT key, value FROM {META}").fetchall())
        finally:
            file.close()
    except sqlite3.Error as e:
        raise TransferError(f"{path} is no index export of caracole's ({e}): `caracole index export` makes one") from e
    if meta.get("format") != str(FORMAT):
        raise TransferError(f"{path} is an index export of another layout ({meta.get('format')!r}, this caracole's "
                            f"is {FORMAT}): export it again with this caracole")
    if meta.get("schema") != str(db.SCHEMA_VERSION):
        raise TransferError(f"{path} was exported at schema version {meta.get('schema')}, and this caracole's "
                            f"database is at {db.SCHEMA_VERSION}: merge it with a caracole of the same version "
                            "(export it again with this one, or bring both to the same caracole); nothing changed")
    return meta


def _merged_sites(path: Path, meta: dict[str, str], sites: Iterable[str] | None) -> tuple[str, ...]:
    try:
        held = [s for s in json.loads(meta.get("sites", "[]")) if s in SITES]
    except ValueError:
        held = []
    names = chosen(sites, chosen(held) if held else ())
    for name in names:
        if name not in held:
            raise TransferError(f"{path} holds no {name} index; it holds {', '.join(held) or 'none'}")
    return names


@contextmanager
def _attached(conn: sqlite3.Connection, path: Path) -> Iterator[None]:
    conn.execute(f"ATTACH DATABASE ? AS {THEIRS}", (str(path),))
    try:
        yield
    finally:
        conn.execute(f"DETACH DATABASE {THEIRS}")


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def _check_columns(conn: sqlite3.Connection, path: Path, names: Sequence[str]) -> None:
    for name in names:
        for table in SITES[name].tables:
            mine, theirs = _columns(conn, "main", table), _columns(conn, THEIRS, table)
            if mine != theirs:
                raise TransferError(f"{path}'s {table} has the columns ({', '.join(theirs) or 'none'}), and the "
                                    f"database's ({', '.join(mine)}): nothing changed")


def _db_path(conn: sqlite3.Connection) -> Path | None:
    for row in conn.execute("PRAGMA database_list"):
        if row[1] == "main" and row[2]:
            return Path(row[2])
    return None


def _same_file(a: Path, b: Path | None) -> bool:
    if b is None:
        return False
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


# --- deciding ------------------------------------------------------------------------------------------------------


def _newer(theirs: str | None, mine: str | None) -> bool:
    """Whether a time the file recorded is later than the database's; a time missing is earlier than any."""
    t, m = stamps.parse(theirs), stamps.parse(mine)
    return t is not None and (m is None or t > m)


def _kv(conn: sqlite3.Connection, schema: str, key: str) -> str | None:
    row = conn.execute(f"SELECT value FROM {schema}.kv WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _records(conn: sqlite3.Connection, schema: str, key: str) -> dict[str, Any]:
    value = _kv(conn, schema, key)
    try:
        records = json.loads(value) if value else {}
    except ValueError:
        return {}
    return records if isinstance(records, dict) else {}


def _newer_records(conn: sqlite3.Connection, key: str, stamp: str) -> list[str]:
    """The sitemaps (pages) of a record of them the file read later than the database, or the database never read."""
    mine, theirs = _records(conn, "main", key), _records(conn, THEIRS, key)

    def seen(entry: Any) -> str | None:
        return entry.get(stamp) if isinstance(entry, dict) else None

    return [name for name, entry in theirs.items()
            if isinstance(entry, dict) and (name not in mine or _newer(seen(entry), seen(mine[name])))]


@dataclass
class _Plan:
    """What a merge takes of a site: each action (a noun, how many, and what does it), and the kv records set (a
    value) or let go (None)."""

    site: str
    actions: list[tuple[str, int, Callable[[sqlite3.Connection], None]]] = field(default_factory=list)
    kv: dict[str, str | None] = field(default_factory=dict)
    records: list[str] = field(default_factory=list)  # the progress records the kv moves on, in words
    keys: list[str] = field(default_factory=list)  # the keys records to let go: made again whole

    @property
    def changes(self) -> bool:
        return bool(self.actions or self.kv)

    def take(self, noun: str, n: int, action: Callable[[sqlite3.Connection], None]) -> None:
        if n:
            self.actions.append((noun, n, action))


def _plan(conn: sqlite3.Connection, name: str) -> _Plan:
    plan = _Plan(name)
    {"ug": _plan_ug, "lacuerda": _plan_lacuerda, "gtptabs": _plan_sitemaps, "musescore": _plan_sitemaps,
     "harptabs": _plan_harptabs, "gametabs": _plan_gametabs}[name](conn, plan)
    return plan


def _later(conn: sqlite3.Connection, plan: _Plan, key: str, what: str) -> None:
    """A time that moves on, never back: the file's, when later."""
    theirs = _kv(conn, THEIRS, key)
    if _newer(theirs, _kv(conn, "main", key)):
        plan.kv[key] = theirs
        plan.records.append(what)


def _keys_again(conn: sqlite3.Connection, plan: _Plan, key: str) -> None:
    """Rows of the file's keyed by another normalizer than the database's: the keys made again whole after."""
    if plan.actions and _kv(conn, THEIRS, key) != _kv(conn, "main", key):
        plan.kv[key] = None


def _taken(conn: sqlite3.Connection, names: Iterable[str]) -> None:
    conn.execute(f"CREATE TEMP TABLE IF NOT EXISTS {_TAKEN.split('.')[1]} (name TEXT PRIMARY KEY)")
    conn.execute(f"DELETE FROM {_TAKEN}")
    conn.executemany(f"INSERT OR IGNORE INTO {_TAKEN} (name) VALUES (?)", [(n,) for n in names])


def _replace(conn: sqlite3.Connection, table: str, column: str) -> None:
    """The database's rows of the pages taken (``_TAKEN``, by ``column``) in place of the file's."""
    cols = ", ".join(_columns(conn, "main", table))
    conn.execute(f"DELETE FROM main.{table} WHERE {column} IN (SELECT name FROM {_TAKEN})")
    conn.execute(f"INSERT OR REPLACE INTO main.{table} ({cols}) SELECT {cols} FROM {THEIRS}.{table} "
                 f"WHERE {column} IN (SELECT name FROM {_TAKEN})")


def _take_records(conn: sqlite3.Connection, key: str, names: Sequence[str]) -> None:
    """The file's records of the sitemaps (pages) taken, in place of the database's."""
    mine, theirs = _records(conn, "main", key), _records(conn, THEIRS, key)
    db.kv_set_json(conn, key, {**mine, **{n: theirs[n] for n in names}})


def _sitemaps(conn: sqlite3.Connection, plan: _Plan, site: Any, noun: str = "sitemap") -> None:
    """A site_index.py site's sitemaps the file read later, and its ``complete_at``."""
    names = _newer_records(conn, site.sitemaps_key, "checked_at")

    def take(c: sqlite3.Connection) -> None:
        _taken(c, names)
        _replace(c, site.table, "sitemap")
        _take_records(c, site.sitemaps_key, names)

    plan.take(noun, len(names), take)
    _later(conn, plan, site.complete_key, f"{noun}s read whole")


def _plan_sitemaps(conn: sqlite3.Connection, plan: _Plan) -> None:
    from caracole import gtptabs_fetch, musescore_fetch

    _sitemaps(conn, plan, {"gtptabs": gtptabs_fetch.SITE, "musescore": musescore_fetch.SITE}[plan.site])


def _pages_read_later(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[0] for r in conn.execute(
        f"SELECT t.path FROM {THEIRS}.{table} t LEFT JOIN main.{table} m ON m.path = t.path "
        "WHERE m.path IS NULL OR t.read_at > m.read_at ORDER BY t.path")]


def _pages(conn: sqlite3.Connection, plan: _Plan, noun: str, pages: str, tabs: str, column: str) -> None:
    """The pages (``pages``: path, read_at) the file read later, with their tabs (``tabs``, by ``column``)."""
    names = _pages_read_later(conn, pages)

    def take(c: sqlite3.Connection) -> None:
        _taken(c, names)
        _replace(c, tabs, column)
        _replace(c, pages, "path")

    plan.take(noun, len(names), take)


def _plan_harptabs(conn: sqlite3.Connection, plan: _Plan) -> None:
    from caracole import harptabs_fetch, harptabs_index

    _sitemaps(conn, plan, harptabs_fetch.SITE)
    _keys_again(conn, plan, harptabs_fetch.KEYS_KEY)
    sitemap_actions = len(plan.actions)
    _pages(conn, plan, "artist page", "harptabs_artists", "harptabs_artist_tabs", "artist")
    if len(plan.actions) > sitemap_actions:
        _keys_again(conn, plan, harptabs_index.KEYS_KEY)


def _plan_gametabs(conn: sqlite3.Connection, plan: _Plan) -> None:
    from caracole import gametabs_fetch, gametabs_index

    _sitemaps(conn, plan, gametabs_fetch.SITE)
    sitemap_actions = len(plan.actions)
    _pages(conn, plan, "game page", "gametabs_games", "gametabs_game_tabs", "page")
    if len(plan.actions) > sitemap_actions:
        _keys_again(conn, plan, gametabs_index.KEYS_KEY)


def _plan_lacuerda(conn: sqlite3.Connection, plan: _Plan) -> None:
    from caracole import lacuerda_index as li

    listings = _newer_records(conn, li.PAGES_KEY, "checked_at")

    def take_listings(c: sqlite3.Connection) -> None:
        _taken(c, listings)
        _replace(c, "lacuerda_index", "page")
        _take_records(c, li.PAGES_KEY, listings)

    plan.take("listing page", len(listings), take_listings)
    # An artist page's rows have no time of their own: the file's are taken where the database has none.
    artists = [r[0] for r in conn.execute(
        f"SELECT DISTINCT t.page FROM {THEIRS}.lacuerda_index t WHERE t.page LIKE '%/' AND t.page NOT LIKE 'tabs/%' "
        "AND NOT EXISTS (SELECT 1 FROM main.lacuerda_index m WHERE m.page = t.page) ORDER BY t.page")]

    def take_artists(c: sqlite3.Connection) -> None:
        _taken(c, artists)
        _replace(c, "lacuerda_index", "page")

    plan.take("artist page", len(artists), take_artists)
    search = f"FROM {THEIRS}.lacuerda_index t WHERE t.page = ? AND NOT EXISTS " \
             "(SELECT 1 FROM main.lacuerda_index m WHERE m.path = t.path)"
    found = conn.execute(f"SELECT COUNT(*) {search}", (li.SEARCH_PAGE,)).fetchone()[0]

    def take_search(c: sqlite3.Connection) -> None:
        cols = ", ".join(f"t.{col}" for col in _columns(c, "main", "lacuerda_index"))
        c.execute(f"INSERT OR IGNORE INTO main.lacuerda_index SELECT {cols} {search}", (li.SEARCH_PAGE,))

    plan.take("row of its search's answers", found, take_search)
    _keys_again(conn, plan, li.KEYS_KEY)
    _later(conn, plan, li.COMPLETE_KEY, "listings read whole")


def _plan_ug(conn: sqlite3.Connection, plan: _Plan) -> None:
    from caracole.ug import artist_tabs
    from caracole.ug import index as ug

    names = _newer_records(conn, ug.SITEMAPS_KEY, "indexed_at")

    def take_sitemaps(c: sqlite3.Connection) -> None:
        _taken(c, names)
        new = [r[0] for r in c.execute(
            f"SELECT t.tab_id FROM {THEIRS}.ug_index t WHERE t.sitemap IN (SELECT name FROM {_TAKEN}) "
            "AND NOT EXISTS (SELECT 1 FROM main.ug_index m WHERE m.tab_id = t.tab_id) ORDER BY t.tab_id")]
        # As a refresh stores a sitemap (ug/index.py upsert_rows): a row the database has keeps where and when it
        # was first seen, and takes the file's keys and path.
        c.execute(
            "INSERT INTO main.ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
            f"SELECT tab_id, artist_key, song_key, type, sitemap, first_seen, path FROM {THEIRS}.ug_index "
            f"WHERE sitemap IN (SELECT name FROM {_TAKEN}) "
            "ON CONFLICT (tab_id) DO UPDATE SET artist_key = excluded.artist_key, song_key = excluded.song_key, "
            "type = excluded.type, path = excluded.path "
            "WHERE ug_index.artist_key != excluded.artist_key OR ug_index.song_key != excluded.song_key "
            "OR ug_index.type != excluded.type OR ug_index.path != excluded.path")
        _take_records(c, ug.SITEMAPS_KEY, names)
        ug.mark_dirty_for_new(c, new)

    plan.take("sitemap", len(names), take_sitemaps)
    newer = (f"FROM {THEIRS}.ug_artist_tabs t LEFT JOIN main.ug_artist_tabs m ON m.page = t.page AND "
             "m.tab_id = t.tab_id WHERE m.page IS NULL OR t.read_at > m.read_at")
    tabs = conn.execute(f"SELECT COUNT(*) {newer}").fetchone()[0]

    def take_tabs(c: sqlite3.Connection) -> None:
        pages = [r[0] for r in c.execute(f"SELECT DISTINCT t.page {newer}")]
        cols = _columns(c, "main", "ug_artist_tabs")
        c.execute(f"INSERT INTO main.ug_artist_tabs ({', '.join(cols)}) SELECT {', '.join(cols)} FROM "
                  f"{THEIRS}.ug_artist_tabs WHERE true ON CONFLICT (page, tab_id) DO UPDATE SET "
                  + ", ".join(f"{col} = excluded.{col}" for col in cols[2:])
                  + " WHERE excluded.read_at > ug_artist_tabs.read_at")
        artist_tabs.refile(c, pages)

    plan.take("tab of its artist pages", tabs, take_tabs)
    if tabs:
        _keys_again(conn, plan, artist_tabs.KEYS_KEY)
    # The index's state: refreshed at the later time, built once either was, and listed as the later read saw it.
    mine_seen = max(filter(None, map(stamps.parse, (_kv(conn, "main", ug.REFRESHED_KEY),
                                                    _kv(conn, "main", ug.BUILT_KEY)))), default=None)
    theirs_seen = max(filter(None, map(stamps.parse, (_kv(conn, THEIRS, ug.REFRESHED_KEY),
                                                      _kv(conn, THEIRS, ug.BUILT_KEY)))), default=None)
    listed = _kv(conn, THEIRS, ug.LISTED_KEY)
    if listed is not None and theirs_seen is not None and (mine_seen is None or theirs_seen > mine_seen) \
            and listed != _kv(conn, "main", ug.LISTED_KEY):
        plan.kv[ug.LISTED_KEY] = listed
        plan.records.append("the sitemaps UG lists")
    _later(conn, plan, ug.REFRESHED_KEY, "its last refresh")
    built = _kv(conn, THEIRS, ug.BUILT_KEY)
    if built is not None and _kv(conn, "main", ug.BUILT_KEY) is None:
        plan.kv[ug.BUILT_KEY] = built
        plan.records.append("the index built whole")


# --- applying ------------------------------------------------------------------------------------------------------


def _counts(conn: sqlite3.Connection, site: Site) -> dict[str, int]:
    return {t: conn.execute(f"SELECT COUNT(*) FROM main.{t}").fetchone()[0] for t in site.tables}


def _apply(conn: sqlite3.Connection, plan: _Plan) -> SiteMerge:
    site = SITES[plan.site]
    before = _counts(conn, site)
    with db.savepoint(conn, "index_merge"):
        for _, _, action in plan.actions:
            action(conn)
        for key, value in plan.kv.items():
            if value is None:
                db.kv_delete(conn, key)
            else:
                db.kv_set(conn, key, value)
        _current_keys(conn, plan.site)
        conn.execute(f"DROP TABLE IF EXISTS {_TAKEN}")
    after = _counts(conn, site)
    return SiteMerge(plan.site, [(noun, n) for noun, n, _ in plan.actions], plan.records,
                     {t: (before[t], after[t]) for t in site.tables})


def _current_keys(conn: sqlite3.Connection, name: str) -> None:
    """Each index's keys made current, as its next read would make them (and whole, its keys record let go)."""
    if name == "ug":
        from caracole.ug import artist_tabs

        artist_tabs.ensure_current_keys(conn)
    elif name == "lacuerda":
        from caracole import lacuerda_index

        lacuerda_index.ensure_current_keys(conn)
    elif name == "harptabs":
        from caracole import harptabs_fetch, harptabs_index

        harptabs_fetch.ensure_current_keys(conn)
        harptabs_index.ensure_current_keys(conn)
    elif name == "gametabs":
        from caracole import gametabs_index

        gametabs_index.ensure_current_keys(conn)
