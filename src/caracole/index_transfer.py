"""The site indexes into a file of their own, and such a file into the database: ``caracole index export`` and
``caracole index merge``.

Each index costs days of polite requests to build, and lives in one database; a caracole run with other folders (a
shell's, on its home defaults, beside the service: service.py) builds into another. So an index moves between two
databases as a file: ``export`` copies a site's tables, with the kv records it keeps its progress in (``SITES``),
into a new SQLite file, in one read transaction (a consistent copy, which takes no lock); and ``merge`` takes into
the database what the file read more recently, under the lock the command holds.

**An export of pages** (``export(pages=)``) is what the phone sends the computer at a sync (``POST /peer/index``):
the pages its lookups read, which core.index.Reads noted, never a time window (UG's artist pages' stamp moves with
the computer's nightly refresh, and LaCuerda's pages hold no time). Each site's tables are made as a whole export
makes them, but filled only with the rows of the pages named, by the column that names a page (``PAGES``: UG's
artist pages' tabs, LaCuerda's artist pages and its search's rows, ``busca.php``, harptabs.com's artist pages and
their tabs, gametabs.net's game pages and theirs), and its kv only with the records of how those rows are keyed,
which a merge compares to make keys again: never a sitemap's or a listing page's record, nor how far an index has
got, whose rows such a file never holds (a record of it the other side lacks would be taken with no row). A site
whose index has no page a lookup reads (gtptabs.com's, MuseScore's: sitemaps alone) is refused. ``check_pages`` holds
a file posted to caracole serve to that shape before its merge is queued, so that nothing but pages comes of it.

**A partial export** (``export(have=)``) is what a sync gives the phone of this side's indexes (``POST
/peer/index/newer``): the asker says what it holds (``read_have``: its record of each sitemap, and the time of the last
export of this side's it merged), and the file holds of each site only the sitemaps whose record differs from its,
each whole, the rows read a row or a page at a time since (``_bound``), and the progress records whole, as a whole
export would; its META's ``partial`` says what it was cut by, and a merge never reads a sitemap it left out as gone.
Rows a merge brings into this side meanwhile carry another caracole's times, so a merge notes when it took them and
how early their times go (kv ``ARRIVED_KEY``), which the bound goes back to.

**A merge** checks first that the file is an export (its ``META`` table, and tables alone: no view, trigger, index of
its own or virtual table), read with no function its schema names trusted, of this schema version, and that every
table it merges has the database's columns, else it changes nothing (``TransferError``; ``OtherVersion`` for another
layout, schema or columns). Then it decides, per site,
what the file read more recently, the database's records and the file's compared:

- a sitemap (UG's ``ug:sitemaps``, site_index.py's ``<provider>:sitemaps``) or a listing page of LaCuerda's
  (``lacuerda:index:pages``) the file read or checked later, or one the database never read, replaces its rows and
  its record, as reading it again would: UG's rows upserted as a refresh stores them (a row the database has keeps
  its sitemap and first sighting), and the songs its new tabs are for marked to fetch again; the others' rows
  deleted and inserted, but for a sitemap the file merely checked again and found unchanged (its record alike but
  its ``checked_at``: ``_unchanged``), whose record alone moves on, no row of it written;
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

**Its progress** (``merge(progress=, backing_up=)``, the phone's core.index alike): before it plans, before the
backup, before each site and each of its actions, and after each chunk of UG's sitemap rows, which go in a statement
for each ``UG_CHUNK`` (50,000) of them, by ``tab_id`` range, in the order one statement takes them and in the same
savepoint: every row, trigger-made row and record comes out as one statement leaves it (FTS5 lays its segments out
by its own flushes, which no reading of it sees). ``MergeWords`` puts it into words.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from caracole import __version__, backup, db, normalize, stamps

FORMAT = 1  # the export's own layout: META, kv, and each site's tables as the database has them
META = "caracole_export"
THEIRS = "theirs"  # the export, attached to the database's connection
_TAKEN = "temp._merge_taken"
UG_CHUNK = 50_000  # UG's sitemap rows a statement of a merge takes, a step of its progress: the phone's alike
PLANNING = "planning"  # merge(progress=)'s action before it plans
UG_TABS = "tab"  # its action as UG's sitemap rows go in, a chunk at a time
PARTIAL = "partial"  # META's key of a partial export (export(have=)): what it was cut by, by site
SINCE_MARGIN = timedelta(hours=1)  # a read stamped before an export's snapshot and stored after it, at most
ARRIVED_KEY = "index:arrived"  # this side's own: when a merge took rows read a row or a page at a time, by site
ARRIVALS_KEPT = 32  # the arrivals kept a site, the oldest two made one past it
# The sitemaps (listing pages) a have names at most, every site's together: the most a body within POST
# /peer/index/newer's limit (web/peer_routes.py HAVE_MAX, 1 MiB) can name at 6 bytes the smallest ('"":{},'), so this
# count never refuses what that limit lets through (its 413 the one size refusal, after which the phone asks for the
# whole). Real ones are far smaller: a UG record is about 160 bytes a sitemap, tens of them; a have of every site is
# tens to a few hundred KB today.
HAVE_SITEMAPS = -(-1024 * 1024 // 6)  # rounded up

# merge(progress=): (site, action, done, total), see ``merge``.
Progress = Callable[[str, str, int, int], None]


class TransferError(Exception):
    """An export or a merge refused, nothing written: its words say why."""


class NoBackup(TransferError):
    """A merge refused for want of room for the backup it makes first: the file itself may merge later."""


class OtherVersion(TransferError):
    """An export of another layout, schema or columns than this caracole's: it merges once both sides are of one
    version, never before."""


def refusal_words(e: Exception, path: Path, name: str) -> str:
    """``e``'s words with the file at ``path`` called ``name`` ("The index export": a refusal's words begin with the
    file) where they say its path, a copy caracole keeps in a folder of its own (its cache, a staging folder), which
    tells the owner nothing: the words a merge refused in, wherever they reach the Journal or the Sync sheet."""
    return str(e).replace(str(path), name)


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
    from caracole.ug import artist_tabs, directory
    from caracole.ug import index as ug

    def sitemaps(site: Any) -> tuple[str, str]:
        return site.sitemaps_key, site.complete_key

    return {s.name: s for s in (
        Site("ug", "Ultimate Guitar", ("ug_index", "ug_artist_tabs", "ug_directory"),
             (ug.SITEMAPS_KEY, ug.LISTED_KEY, ug.BUILT_KEY, ug.REFRESHED_KEY, artist_tabs.KEYS_KEY,
              directory.LETTERS_KEY, directory.KEYS_KEY)),
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


@dataclass(frozen=True)
class Pages:
    """What of a site's index a lookup reads a page at a time (``export(pages=)``): each table holding a page's
    rows, with the column that names the page, and the kv records of how those rows are keyed."""

    tables: tuple[tuple[str, str], ...]
    kv: tuple[str, ...]


def _pages() -> dict[str, Pages]:
    from caracole import gametabs_index, harptabs_index, lacuerda_index
    from caracole.ug import artist_tabs

    return {
        "ug": Pages((("ug_artist_tabs", "page"),), (artist_tabs.KEYS_KEY,)),
        "lacuerda": Pages((("lacuerda_index", "page"),), (lacuerda_index.KEYS_KEY,)),
        "harptabs": Pages((("harptabs_artists", "path"), ("harptabs_artist_tabs", "artist")),
                          (harptabs_index.KEYS_KEY,)),
        "gametabs": Pages((("gametabs_games", "path"), ("gametabs_game_tabs", "page")), (gametabs_index.KEYS_KEY,)),
    }


PAGES: dict[str, Pages] = _pages()


@dataclass(frozen=True)
class Sitemapped:
    """A site's table of rows filed by sitemap (or LaCuerda's by listing page): its records' kv key, the table, the
    column that names a row's sitemap, and the fields of a record that say two records hold the same rows
    (``_unchanged``'s)."""

    key: str
    table: str
    column: str
    same: tuple[str, ...]


_SAME_SITEMAP = ("etag", "last_modified", "rows", "keys")  # a site_index.py record beside its checked_at
# UG's record has no ``keys``, and moves its ``indexed_at`` only when the sitemap is parsed again (a 304 leaves it):
# so a record alike, ``indexed_at`` too, is the same read of the same rows.
_SAME_UG = ("etag", "last_modified", "rows", "indexed_at")
# A LaCuerda listing page's record beside its checked_at: what identifies its content (lacuerda_index._read; a 304
# moves its checked_at alone), and a page found gone.
_SAME_LISTING = ("etag", "last_modified", "rows", "pages", "total", "gone")


def _sitemapped() -> dict[str, Sitemapped]:
    from caracole import gametabs_fetch, gtptabs_fetch, harptabs_fetch, lacuerda_index, musescore_fetch
    from caracole.ug import index as ug

    def site_index(site: Any) -> Sitemapped:
        return Sitemapped(site.sitemaps_key, site.table, "sitemap", _SAME_SITEMAP)

    return {"ug": Sitemapped(ug.SITEMAPS_KEY, "ug_index", "sitemap", _SAME_UG),
            "lacuerda": Sitemapped(lacuerda_index.PAGES_KEY, "lacuerda_index", "page", _SAME_LISTING),
            "gtptabs": site_index(gtptabs_fetch.SITE), "musescore": site_index(musescore_fetch.SITE),
            "harptabs": site_index(harptabs_fetch.SITE), "gametabs": site_index(gametabs_fetch.SITE)}


SITEMAPPED: dict[str, Sitemapped] = _sitemapped()

# The tables read a row or a page at a time, whose rows a partial export cuts by a time: by site, each table's
# condition on a row read or seen at or after the bound (``:b``), and the time columns a merge into this side reads
# them by (``ARRIVED_KEY``). Times are compared as text, here and in ``_note_arrival``'s MIN(), as the merge compares
# them (``t.read_at > m.read_at``): caracole writes every stamp in UTC with a "Z" (``stamps.stamp``), so text order is
# time order; a time that isn't text is always sent. A stamp written with another offset (the index corpus holds one at
# +02:00 on purpose) compares by its digits as written: one ahead of UTC reads later than it is (sent once more), one
# behind reads earlier (passed over by up to its offset), as a merge would take or keep it the same way.
_TIMED: dict[str, dict[str, str]] = {
    "ug": {"ug_artist_tabs": "typeof(read_at) != 'text' OR read_at >= :b",
           "ug_directory": "typeof(seen_at) != 'text' OR seen_at >= :b OR typeof(read_at) != 'text' "
                           "OR read_at >= :b"},
    "harptabs": {"harptabs_artists": "typeof(read_at) != 'text' OR read_at >= :b",
                 "harptabs_artist_tabs": "artist IN (SELECT path FROM main.harptabs_artists WHERE "
                                         "typeof(read_at) != 'text' OR read_at >= :b)"},
    "gametabs": {"gametabs_games": "typeof(read_at) != 'text' OR read_at >= :b",
                 "gametabs_game_tabs": "page IN (SELECT path FROM main.gametabs_games WHERE "
                                       "typeof(read_at) != 'text' OR read_at >= :b)"},
}
_TIMES: dict[str, tuple[tuple[str, str], ...]] = {
    "ug": (("ug_artist_tabs", "read_at"), ("ug_directory", "seen_at"), ("ug_directory", "read_at")),
    "harptabs": (("harptabs_artists", "read_at"),),
    "gametabs": (("gametabs_games", "read_at"),),
}
# A merge's actions that take rows of those tables, by site.
_TIMED_NOUNS: dict[str, frozenset[str]] = {
    "ug": frozenset({"tab of its artist pages", "artist page read of its directory", "artist of its directory"}),
    "harptabs": frozenset({"artist page"}),
    "gametabs": frozenset({"game page"}),
}


@dataclass(frozen=True)
class Have:
    """What the asker of a partial export holds of a site (``export(have=)``): its record of each sitemap (listing
    page) it holds, by name, as it keeps it but its ``checked_at``; and ``since``, the time of this side's export it
    last merged (its META ``exported_at``), None when it never merged one of this side's."""

    sitemaps: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    since: str | None = None


_SCALARS = (str, int, float, bool, type(None))


def _plain(value: Any, depth: int = 3) -> bool:
    """A value of a sitemap's record as caracole writes one: a scalar, or a list or an object of them, nested
    ``depth`` deep at most (UG's ``tabs``, its counts by type)."""
    if isinstance(value, _SCALARS):
        return True
    if depth == 0:
        return False
    items = value.values() if isinstance(value, dict) else value if isinstance(value, list) else None
    return items is not None and all(_plain(v, depth - 1) for v in items)


def read_have(doc: Any) -> tuple[tuple[str, ...], dict[str, Have]]:
    """``POST /peer/index/newer``'s document, ``{"sites": [site, …], "have": {site: {"sitemaps": {name: record},
    "since": time or null}}}``, read as data from another device: the sites asked (each one of ``SITES``, in caracole's
    order) and what the asker holds of each. ``TransferError`` in words for anything else: no site, a site caracole
    has no index of, a ``have`` of a site not asked, more than ``HAVE_SITEMAPS`` sitemaps, a record that isn't an
    object of plain values (``_plain``), a ``since`` that is no time."""
    if not isinstance(doc, dict):
        raise TransferError("the request is no object: it names the sites asked and what this side holds of them")
    asked = doc.get("sites")
    if not isinstance(asked, list) or not asked or not all(isinstance(s, str) for s in asked):
        raise TransferError("the request names no site: \"sites\" is a list of the sites asked")
    sites = chosen(asked)
    held = doc.get("have", {})
    if not isinstance(held, dict):
        raise TransferError("\"have\" is no object: what this side holds, by site")
    stray = [s for s in held if s not in sites]
    if stray:
        raise TransferError(f"\"have\" names {str(stray[0])[:100]!r}, a site not asked")
    have: dict[str, Have] = {}
    count = 0
    for name, entry in held.items():
        if not isinstance(entry, dict):
            raise TransferError(f"what this side holds of {name} is no object")
        sitemaps = entry.get("sitemaps", {})
        if not isinstance(sitemaps, dict):
            raise TransferError(f"{name}'s \"sitemaps\" is no object: each record by its sitemap's name")
        count += len(sitemaps)
        if count > HAVE_SITEMAPS:
            raise TransferError(f"the request names more than {HAVE_SITEMAPS:,} sitemaps")
        for key, record in sitemaps.items():
            if len(key) > 1024 or not isinstance(record, dict) or not _plain(record):
                raise TransferError(f"{name}'s record of {key[:100]!r} is no object of plain values")
        since = entry.get("since")
        if since is not None:
            try:
                readable = isinstance(since, str) and stamps.parse(since) is not None
            except OverflowError:
                readable = False
            if not readable:
                raise TransferError(f"{name}'s \"since\" is no time: {str(since)[:100]!r}")
        have[name] = Have(sitemaps, since)
    return sites, have


_PLURALS = {"tab of its artist pages": "tabs of its artist pages",
            "row of its search's answers": "rows of its search's answers",
            "artist of its directory": "artists of its directory",
            "artist page read of its directory": "artist pages read of its directory"}


def counted(n: int, noun: str) -> str:
    """"1 game page", "2 game pages", "3 tabs of its artist pages"."""
    return f"{n:,} {noun if n == 1 else _PLURALS.get(noun, noun + 's')}"


class MergeWords:
    """A merge's progress (``merge(progress=)``, ``backing_up``) in words, a line each, as commands/index.py's and
    commands/peer.py's merges say it: "Comparing with this database's indexes", "Backing up the database first",
    "Ultimate Guitar" (a site), "Ultimate Guitar · 41 sitemaps" (an action), "Ultimate Guitar · 41 sitemaps ·
    600,000 of 1,367,059 tabs" (UG's sitemap rows, a chunk at a time).

    A sync's merge of the other side's indexes, or of a file's, passes ``held``, the sites this database held rows of
    before it (``held()``), and ``there``, where the rows were read ("on the other side", "in the file"): of those
    sites, each action says what is newer there and UG's rows the rows checked, "Ultimate Guitar · 3 sitemaps newer on
    the other side · 50,000 of 117,701 tabs checked" (the phone's MergeProgress.Updating alike, "on the computer",
    "in the file"), never as if every row were new; a site it held none of as any merge says it."""

    COMPARING = "Comparing with this database's indexes"
    BACKING_UP = "Backing up the database first"

    def __init__(self, held: Iterable[str] = (), there: str = "") -> None:
        self._doing = ""
        self._held = frozenset(held)
        self._there = there

    def __call__(self, site: str, action: str, done: int, total: int) -> str:
        updating = site in self._held
        if action == PLANNING:
            return self.COMPARING
        if action == UG_TABS:
            return f"{self._doing} · {done:,} of {total:,} tabs" + (" checked" if updating else "")
        title = SITES[site].title if site in SITES else site
        newer = f" newer {self._there}" if updating and self._there else ""
        self._doing = f"{title} · {counted(total, action)}{newer}" if action else title
        return self._doing


@dataclass(frozen=True)
class Omit:
    """Rows an export leaves out: an SQL condition on a table's rows (``table`` ``META``: a meta key dropped)."""
    table: str
    where: str


# S2: what a public copy of the indexes leaves out. To keep a thing, remove its rule; to drop UG's artist pages, add
# ``Omit("ug_artist_tabs", "1")``.
PUBLIC_OMIT: tuple[Omit, ...] = (Omit(META, "key = 'source'"), Omit("lacuerda_index", "page = 'busca.php'"))


@dataclass(frozen=True)
class Exported:
    path: Path
    sites: tuple[str, ...]
    rows: dict[str, int]
    size: int


@dataclass
class SiteMerge:
    """What a merge took of a site: ``taken``, (noun, count) for each kind of page; ``records``, its progress
    records moved on; ``rows``, each table's rows (before, after); ``checked``, the file's rows of its first table
    (``Site.tables[0]``: UG's ``ug_index``…) in what it took: for UG and the sitemap sites the rows of the sitemaps
    taken, read whether new or not; for LaCuerda its listing pages' rows, and its artist pages' and search's rows the
    database lacked, inserted (new by construction). Counted as it takes them, by the statements' own counts (UG's the
    count its chunks are cut by), no table scanned for it."""

    site: str
    taken: list[tuple[str, int]] = field(default_factory=list)
    records: list[str] = field(default_factory=list)
    rows: dict[str, tuple[int, int]] = field(default_factory=dict)
    checked: int = 0

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


def export(conn: sqlite3.Connection, path: Path, sites: Iterable[str] | None = None, *, now: datetime,
           pages: Mapping[str, Sequence[str]] | None = None, omit: Sequence[Omit] = (),
           have: Mapping[str, Have] | None = None, copied: Callable[[str, int], None] | None = None,
           omitting: Callable[[], None] | None = None) -> Exported:
    """The indexes of ``sites`` (every one with none) into a new file at ``path``, in one read transaction; a file
    there already, or the database itself, is refused. Written under a name of its own, then renamed.

    With ``pages`` (``{site: [page, …]}``, a lookup's reads: none of ``sites`` then), those sites alone, each table
    of theirs holding only those pages' rows (``PAGES``) and the kv only their keys records; with no site at all for
    an empty one.

    With ``have`` (what the asker holds of each of ``sites``: ``Have``; a site it doesn't name, nothing), a partial
    export, the phone's take of this side's indexes (``POST /peer/index/newer``): of each site only the sitemaps (and
    LaCuerda's listing pages) whose record differs from the asker's or that it lacks (``_unchanged`` by the site's
    ``Sitemapped.same``), each with all of its rows (a merge replaces a sitemap's rows whole); LaCuerda's artist pages'
    and search's rows whole (they hold no time); the rows of the tables read a row or a page at a time (``_TIMED``)
    read or seen at or after the bound (``_bound``: ``since`` less ``SINCE_MARGIN``, and earlier for what a merge
    took here since; every row with no ``since``); and the kv records whole, as a whole export holds them. Its META's
    ``partial`` says what it was cut by: ``{site: {"since", "from" (the bound), "same" (the sitemaps left out, the
    asker's alike)}}``, which a merge reads (``_left``): a sitemap it names is never read as gone.

    ``copied(table, rows)``, after each table is copied, in the export's order, with the rows copied (before
    ``omit`` leaves any out); ``omitting()``, before the rows ``omit`` names are deleted and the file compacted. Both
    tell, and change nothing of what is written (``caracole index publish``'s progress)."""
    if omit and pages is not None:
        raise TransferError("an export of pages omits nothing")
    if have is not None and (pages is not None or omit):
        raise TransferError("a partial export is of whole sites, and omits nothing")
    if pages is not None:
        if sites is not None:
            raise TransferError("an export of pages exports their sites alone: name no site beside them")
        names = chosen(pages) if pages else ()
        lacking = [n for n in names if n not in PAGES]
        if lacking:
            raise TransferError(f"{SITES[lacking[0]].title}'s index has no pages a lookup reads, its sitemaps alone: "
                                f"pages are of {', '.join(PAGES)}")
        chosen_pages = {table: (column, list(dict.fromkeys(pages[n])))
                        for n in names for table, column in PAGES[n].tables}
    else:
        names = chosen(sites)
        chosen_pages = None
    if _same_file(path, _db_path(conn)):
        raise TransferError(f"{path} is the database itself: name a new file")
    if os.path.lexists(path):
        raise TransferError(f"{path} already exists: name a new file, or remove that one first")
    if not path.parent.is_dir():
        raise TransferError(f"{path.parent} is no folder: name a file in one")
    part = path.with_name(f"{path.name}.{secrets.token_hex(6)}.part")
    tables = [t for n in names for t in SITES[n].tables]
    keys = [k for n in names for k in (SITES[n].kv if chosen_pages is None else PAGES[n].kv)]
    try:
        _write_export(conn, part, names, tables, keys, now, chosen_pages, copied, have)
        if omit:
            if omitting is not None:
                omitting()
            _omit(part, omit)
        os.replace(part, path)
    except (OSError, sqlite3.Error) as e:
        raise TransferError(f"can't write {path}: {e}") from e
    finally:
        with suppress(OSError):  # never replace the real error: the folder may be read-only
            part.unlink(missing_ok=True)
    counts = {table: _count(path, table) for table in tables}
    return Exported(path, names, counts, path.stat().st_size)


def _omit(part: Path, omit: Sequence[Omit]) -> None:
    """Delete the rows ``omit`` names from the file ``part``, then VACUUM it; a rule for a table the file doesn't
    hold (an export of some sites) is passed over. The names come from the rules alone."""
    out = sqlite3.connect(part, isolation_level=None)
    try:
        held = {r[0] for r in out.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for rule in omit:
            if rule.table not in held:
                continue
            out.execute(f"DELETE FROM {rule.table} WHERE {rule.where}")
        out.execute("VACUUM")
    finally:
        out.close()


@dataclass(frozen=True)
class _Cut:
    """A partial export's cut: each table's condition and its parameters (a table it doesn't name, whole), and what
    META's ``partial`` says of each site."""

    where: dict[str, tuple[str, dict[str, Any]]]
    said: dict[str, dict[str, Any]]


def _cut(conn: sqlite3.Connection, names: Sequence[str], have: Mapping[str, Have], now: datetime) -> _Cut:
    """What a partial export of ``names`` holds for an asker that holds ``have`` (``export(have=)``). The records are
    this database's as the export reads them: a record read before its snapshot, a sitemap re-read meanwhile sent
    whole by its record's next comparison."""
    where: dict[str, tuple[str, dict[str, Any]]] = {}
    said: dict[str, dict[str, Any]] = {}
    for name in names:
        asked = have.get(name, Have())
        mapped = SITEMAPPED[name]
        records = _records(conn, "main", mapped.key)
        same = sorted(n for n, entry in records.items()
                      if _unchanged(entry, asked.sitemaps.get(n), mapped.same))
        sent = json.dumps([n for n in records if n not in same], ensure_ascii=False)
        held = f"{mapped.column} IN (SELECT value FROM json_each(:sent))"
        if name == "lacuerda":  # its artist pages' and search's rows hold no time: sent whole
            held = f"page NOT LIKE 'tabs/%' OR {held}"
        where[mapped.table] = (held, {"sent": sent})
        bound = _bound(conn, name, asked.since, now)
        if bound is not None:
            for table, condition in _TIMED.get(name, {}).items():
                where[table] = (condition, {"b": bound})
        said[name] = {"since": asked.since, "from": bound if name in _TIMED else None, "same": same}
    return _Cut(where, said)


def _bound(conn: sqlite3.Connection, site: str, since: str | None, now: datetime) -> str | None:
    """The earliest read or sighting a partial export sends of a site's tables read a row or a page at a time (a
    time compared as text, as a merge compares them), or None for every row: ``since`` (when the asker last merged
    an export of this side's, this side's clock) less ``SINCE_MARGIN``, for a read stamped before that export's
    snapshot and stored after it; and earlier where a merge since took rows of other times here (a phone's pages,
    another caracole's, a file's: ``ARRIVED_KEY``), to the earliest of them, so that none is missed. None with no
    ``since``: a stamp of another caracole's (a catalogue's) is never a bound for this side's rows; nor with a
    ``since`` later than ``now``, this side's clock as it exports (its clock stepped back since, or a cut of another
    clock's), nor one within ``SINCE_MARGIN`` of the first day: every row, once, META's ``partial`` saying the
    ``since`` asked and no ``from``."""
    if since is None or stamps.parse(since) > stamps.utc(now):
        return None
    try:
        floor = stamps.parse(since) - SINCE_MARGIN
    except OverflowError:  # within the margin of the first day: before every row
        return None
    bounds = [stamps.stamp(floor)]
    arrivals = _records(conn, "main", ARRIVED_KEY).get(site)
    for entry in arrivals if isinstance(arrivals, list) else []:
        at, low = (entry + [None, None])[:2] if isinstance(entry, list) else (None, None)
        when = stamps.parse(at) if isinstance(at, str) else None
        if when is not None and when <= floor:
            continue
        if not isinstance(low, str):  # an arrival that can't be read: every row
            return ""
        bounds.append(low)
    return min(bounds)


def _write_export(conn: sqlite3.Connection, part: Path, names: Sequence[str], tables: Sequence[str],
                  keys: Sequence[str], now: datetime,
                  pages: Mapping[str, tuple[str, list[str]]] | None = None,
                  copied: Callable[[str, int], None] | None = None, have: Mapping[str, Have] | None = None) -> None:
    """The export's tables, as the database has them, made in a file of their own, then filled from the
    database in one transaction: one snapshot of it for every table, a consistent copy. With ``pages`` (a table's
    column and the pages it names, by table), only those pages' rows, and no row of a table it doesn't name, each
    table's in the database's order, the kv by key. With ``have`` (a partial export's), each table its cut names
    (``_cut``, of the records read in the same snapshot as the rows) only the rows its condition takes, in the
    database's order, and META's ``partial``."""
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
        if have is not None:
            out.execute(f"INSERT INTO {META} (key, value) VALUES (?, ?)", (PARTIAL, "{}"))
        out.commit()
    finally:
        out.close()
    conn.execute("ATTACH DATABASE ? AS exported", (str(part),))
    try:
        conn.execute("BEGIN")
        try:
            cut = None if have is None else _cut(conn, names, have, now)
            if cut is not None:
                conn.execute(f"UPDATE exported.{META} SET value = ? WHERE key = ?",
                             (json.dumps(cut.said, ensure_ascii=False), PARTIAL))
            for table in tables:
                cols = ", ".join(_columns(conn, "main", table))
                n = 0
                if cut is not None and table in cut.where:
                    condition, params = cut.where[table]
                    n = conn.execute(f"INSERT INTO exported.{table} ({cols}) SELECT {cols} FROM main.{table} "
                                     f"WHERE {condition} ORDER BY rowid", params).rowcount
                elif pages is None:
                    n = conn.execute(f"INSERT INTO exported.{table} ({cols}) SELECT {cols} FROM main.{table}").rowcount
                elif table in pages:
                    column, named = pages[table]
                    n = conn.execute(f"INSERT INTO exported.{table} ({cols}) SELECT {cols} FROM main.{table} "
                                     f"WHERE {column} IN (SELECT value FROM json_each(?)) ORDER BY rowid",
                                     (json.dumps(named),)).rowcount
                if copied is not None:
                    copied(table, n)
            marks = ", ".join("?" for _ in keys)
            conn.execute(f"INSERT INTO exported.kv (key, value) SELECT key, value FROM main.kv WHERE key IN "
                         f"({marks})" + ("" if pages is None else " ORDER BY key"), list(keys))
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
          now: datetime, progress: Progress | None = None,
          backing_up: Callable[[], None] | None = None, arrivals: bool = True) -> Merged:
    """Take into the database what the export at ``path`` read more recently, site by site (``sites``: every one
    the file holds, with none), after a copy of it in ``state_dir``'s backups; see the module docstring.
    ``TransferError`` when it is refused, nothing written (``NoBackup`` when only the room for that copy is
    lacking); backup.py's ``BackupError`` when the copy fails.

    ``progress(site, action, done, total)`` tells how far it has got, and changes nothing of what is written:
    ``("", PLANNING, 0, sites)`` once the file is found an export of those sites, before it plans; then, once any
    site changes anything (a merge of nothing newer tells the plan alone), ``(site, "", i, sites)`` before every site
    of those, one that changes nothing too (the i-th, from 0, in ``SITES``' order), ``(site, noun, 0, n)`` before
    each of its actions (a ``SiteMerge.taken`` entry: "sitemap", 41), and, while UG's sitemap action takes its rows,
    ``("ug", UG_TABS, rows taken, rows)`` after each chunk of ``UG_CHUNK`` of them, the last with done == total.
    ``backing_up()``, before the backup a merge that changes a row makes first: one that moves records alone (a
    sitemap re-checked and found unchanged, a refresh's time) makes none, the backup being there to undo rows.

    A partial export's sitemaps it left out (META's ``partial``: ``_left``) are never read as gone (``_held``).
    ``arrivals``: this side notes when a merge took rows of the tables read a row or a page at a time, and the
    earliest of the file's times there (``ARRIVED_KEY``), so that a partial export it makes later sends them
    (``_bound``); the phone, which makes none, notes nothing (its core.index, the corpus's merges)."""
    tell: Progress = progress if progress is not None else _untold
    if _same_file(path, _db_path(conn)):
        raise TransferError(f"{path} is the database itself")
    meta = _meta(path)
    names = _merged_sites(path, meta, sites)
    left = _left(path, meta)
    tell("", PLANNING, 0, len(names))
    with _attached(conn, path):
        _check_columns(conn, path, names)
        plans = [_plan(conn, name, tell, left.get(name, ())) for name in names]
    if not any(p.changes for p in plans):
        return Merged([SiteMerge(p.site) for p in plans], None)
    copy = None
    if any(p.actions for p in plans):
        if backing_up is not None:
            backing_up()
        made = backup.make(conn, state_dir, now, label=backup.MERGE)
        if isinstance(made, backup.Skipped):
            raise NoBackup(f"{made.reason}, and a merge backs the database up first")
        copy = made.backup.path
    done: list[SiteMerge] = []
    with _attached(conn, path):
        for i, plan in enumerate(plans):
            tell(plan.site, "", i, len(plans))
            done.append(_apply(conn, plan, now if arrivals else None))
    return Merged(done, copy)


def _left(path: Path, meta: Mapping[str, str]) -> dict[str, list[str]]:
    """A partial export's sitemaps (listing pages) it left out, by site (META's ``partial``, each site's ``same``);
    none for a whole export. ``TransferError`` for a ``partial`` that can't be read: a file cut that way can't be
    merged as a whole one, which would read its sitemaps left out as gone."""
    if PARTIAL not in meta:
        return {}
    try:
        said = json.loads(meta[PARTIAL])
    except ValueError:
        said = None
    if not isinstance(said, dict) or not all(
            isinstance(cut, dict) and isinstance(cut.get("same"), list) and all(isinstance(n, str) for n in cut["same"])
            for cut in said.values()):
        raise TransferError(f"{path} is part of the indexes, and doesn't say which part in a form this caracole "
                            "reads: nothing changed")
    return {site: list(cut["same"]) for site, cut in said.items()}


def _untold(site: str, action: str, done: int, total: int) -> None:
    pass


def check_pages(conn: sqlite3.Connection, path: Path) -> tuple[str, ...]:
    """That the file at ``path`` is an export of pages (``export(pages=)``'s: the phone's reads, posted to caracole
    serve) this database merges, read with nothing written: an export ``_meta`` takes; every site of it one of
    ``PAGES``', with its tables alone beside kv and ``META``, each of the database's columns (generated ones too);
    no row in a table no page fills (a sitemap's: ``ug_index``, ``harptabs_index``, ``gametabs_index``); and its kv
    only how those rows are keyed, never a sitemap's or a listing page's record, nor how far an index has got, which
    a merge would take with no row of theirs. Its sites; ``TransferError`` else, ``OtherVersion`` for another layout,
    schema or columns."""
    meta = _meta(path)
    names = _merged_sites(path, meta, None)
    lacking = [n for n in names if n not in PAGES]
    if lacking:
        raise TransferError(f"{path} holds {SITES[lacking[0]].title}'s index, of which no lookup reads a page: it "
                            "is no export of pages")
    try:
        file = _untrusted(path)
        try:
            held = {r[0] for r in file.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            tables = [t for n in names for t in SITES[n].tables]
            if held != {META, "kv", *tables}:
                raise TransferError(f"{path} holds the tables {', '.join(sorted(held))}, and an export of its sites' "
                                    f"pages {', '.join(sorted({META, 'kv', *tables}))}")
            paged = {t for n in names for t, _ in PAGES[n].tables}
            for table in tables:
                mine = [(r[1], r[6]) for r in conn.execute(f"PRAGMA main.table_xinfo({table})")]
                theirs = [(r[1], r[6]) for r in file.execute(f"PRAGMA main.table_xinfo({table})")]
                if mine != theirs:
                    raise OtherVersion(f"{path}'s {table} has the columns ({', '.join(c for c, _ in theirs)}), and "
                                       f"the database's ({', '.join(c for c, _ in mine)}): nothing changed")
                if table not in paged and file.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None:
                    raise TransferError(f"{path}'s {table} holds rows, and an export of pages none: a sitemap's rows "
                                        "come of the computer's own reads")
            keys = {k for n in names for k in PAGES[n].kv}
            other = [r[0] for r in file.execute("SELECT key FROM kv ORDER BY key") if r[0] not in keys]
        finally:
            file.close()
    except sqlite3.Error as e:
        raise TransferError(f"{path} can't be read as an export of pages ({e})") from e
    if other:
        raise TransferError(f"{path}'s kv holds {other[0]!r}, and an export of pages only how its rows are keyed: "
                            "a sitemap's or a listing's record, or how far an index has got, comes of the computer's "
                            "own reads")
    return names


def _untrusted(path: Path) -> sqlite3.Connection:
    """The file at ``path``, opened read-only as a file of anyone's: no function its schema names runs
    (``trusted_schema`` off)."""
    file = sqlite3.connect(_read_only(path), uri=True)
    file.execute("PRAGMA trusted_schema = OFF")
    return file


def _meta(path: Path) -> dict[str, str]:
    """The export's META, once the file is one: of tables alone, as ``export`` makes it (no view, trigger, index of
    its own or virtual table, whose reading could run what its maker wrote), of this layout and schema. Its schema
    is read first, and META only once it is a table: a view in its place (an endless query, say) is never read."""
    if not path.exists():
        raise TransferError(f"{path}: no such file")
    try:
        file = _untrusted(path)
        try:
            odd = file.execute(
                "SELECT type, name FROM sqlite_master WHERE NOT (type = 'table' AND sql LIKE 'CREATE TABLE %') "
                "AND NOT (type = 'index' AND sql IS NULL) ORDER BY rowid").fetchone()
            if odd is not None:
                raise TransferError(f"{path} holds the {odd[0]} {odd[1]}, and an index export of caracole's holds "
                                    "tables alone: `caracole index export` makes one")
            meta = dict(file.execute(f"SELECT key, value FROM {META}").fetchall())
        finally:
            file.close()
    except sqlite3.Error as e:
        raise TransferError(f"{path} is no index export of caracole's ({e}): `caracole index export` makes one") from e
    if meta.get("format") != str(FORMAT):
        raise OtherVersion(f"{path} is an index export of another layout ({meta.get('format')!r}, this caracole's "
                           f"is {FORMAT}): export it again with this caracole")
    if meta.get("schema") != str(db.SCHEMA_VERSION):
        raise OtherVersion(f"{path} was exported at schema version {meta.get('schema')}, and this caracole's "
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
    """The export attached as ``THEIRS``, the connection trusting no schema's functions meanwhile (``_untrusted``):
    the file may be anyone's (a phone's, posted to caracole serve)."""
    (trusted,) = conn.execute("PRAGMA trusted_schema").fetchone()
    conn.execute("PRAGMA trusted_schema = OFF")
    try:
        conn.execute(f"ATTACH DATABASE ? AS {THEIRS}", (str(path),))
        try:
            yield
        finally:
            conn.execute(f"DETACH DATABASE {THEIRS}")
    finally:
        conn.execute(f"PRAGMA trusted_schema = {'ON' if trusted else 'OFF'}")


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA {schema}.table_info({table})")]


def _check_columns(conn: sqlite3.Connection, path: Path, names: Sequence[str]) -> None:
    for name in names:
        for table in ("kv", *SITES[name].tables):  # its records of how far each index has got too
            mine, theirs = _columns(conn, "main", table), _columns(conn, THEIRS, table)
            if mine != theirs:
                raise OtherVersion(f"{path}'s {table} has the columns ({', '.join(theirs) or 'none'}), and the "
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
    value) or let go (None); ``tell``, the merge's progress, which an action that goes in chunks tells each of."""

    site: str
    tell: Progress = _untold
    actions: list[tuple[str, int, Callable[[sqlite3.Connection], None]]] = field(default_factory=list)
    kv: dict[str, str | None] = field(default_factory=dict)
    records: list[str] = field(default_factory=list)  # the progress records the kv moves on, in words
    keys: list[str] = field(default_factory=list)  # the keys records to let go: made again whole
    checked: int = 0  # the file's rows of its first table its actions took (SiteMerge.checked)
    left: frozenset[str] = frozenset()  # a partial export's sitemaps (listing pages) it left out (META's partial)

    @property
    def changes(self) -> bool:
        return bool(self.actions or self.kv)

    def take(self, noun: str, n: int, action: Callable[[sqlite3.Connection], None]) -> None:
        if n:
            self.actions.append((noun, n, action))


def _plan(conn: sqlite3.Connection, name: str, tell: Progress = _untold, left: Iterable[str] = ()) -> _Plan:
    plan = _Plan(name, tell, left=frozenset(left))
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


def _replace(conn: sqlite3.Connection, table: str, column: str) -> int:
    """The database's rows of the pages taken (``_TAKEN``, by ``column``) in place of the file's; how many of the
    file's it took (its insert's own count)."""
    cols = ", ".join(_columns(conn, "main", table))
    conn.execute(f"DELETE FROM main.{table} WHERE {column} IN (SELECT name FROM {_TAKEN})")
    return conn.execute(f"INSERT OR REPLACE INTO main.{table} ({cols}) SELECT {cols} FROM {THEIRS}.{table} "
                        f"WHERE {column} IN (SELECT name FROM {_TAKEN})").rowcount


def _take_records(conn: sqlite3.Connection, key: str, names: Sequence[str]) -> None:
    """The file's records of the sitemaps (pages) taken, in place of the database's."""
    mine, theirs = _records(conn, "main", key), _records(conn, THEIRS, key)
    db.kv_set_json(conn, key, {**mine, **{n: theirs[n] for n in names}})


_LACKED = object()  # a field a record lacks, which no value json.loads gives equals


def _unchanged(theirs: Any, mine: Any, same: Sequence[str] = _SAME_SITEMAP) -> bool:
    """Whether the file's record of a sitemap says its rows are the database's: each of ``same`` alike (a field one
    record lacks and the other holds differs; ``_SAME_SITEMAP`` by default, a site_index.py record's beside its
    ``checked_at``), with a validator to tell by. A re-check that found it unchanged (a 304) moves its ``checked_at``
    alone; with no etag and no date, a re-read of as many rows may hold others. The one rule both a merge and a
    partial export tell a sitemap that differs by (``Sitemapped.same``)."""
    return isinstance(theirs, dict) and isinstance(mine, dict) \
        and all(theirs.get(k, _LACKED) == mine.get(k, _LACKED) for k in same) \
        and (theirs.get("etag") is not None or theirs.get("last_modified") is not None)


def _held(plan: _Plan, theirs: Mapping[str, Any], mine: Mapping[str, Any], read: Sequence[str],
          same: Sequence[str] = _SAME_SITEMAP) -> list[str]:
    """Of the sitemaps (listing pages) ``read`` more recently by the file, those it holds: a partial export's
    sitemap it left out (``_Plan.left``) only where the database's record says it holds those rows already
    (``_unchanged``), its record then moved on alone; else neither its rows nor its record is taken, never read as
    gone."""
    return [n for n in read if n not in plan.left or _unchanged(theirs[n], mine.get(n), same)]


def _sitemaps(conn: sqlite3.Connection, plan: _Plan, site: Any, noun: str = "sitemap") -> None:
    """A site_index.py site's sitemaps the file read later, and its ``complete_at``: one whose rows differ taken
    (``_unchanged``), one the file merely checked again only its record moved on, no row of it written."""
    mine, theirs = _records(conn, "main", site.sitemaps_key), _records(conn, THEIRS, site.sitemaps_key)
    read = _held(plan, theirs, mine, _newer_records(conn, site.sitemaps_key, "checked_at"))
    names = [n for n in read if not _unchanged(theirs[n], mine.get(n))]

    def take(c: sqlite3.Connection) -> None:
        _taken(c, names)
        plan.checked += _replace(c, site.table, "sitemap")

    plan.take(noun, len(names), take)
    if read:
        plan.kv[site.sitemaps_key] = json.dumps({**mine, **{n: theirs[n] for n in read}}, ensure_ascii=False)
    if len(names) < len(read):
        plan.records.append(f"{noun}s found unchanged")
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

    mine, theirs = _records(conn, "main", li.PAGES_KEY), _records(conn, THEIRS, li.PAGES_KEY)
    listings = _held(plan, theirs, mine, _newer_records(conn, li.PAGES_KEY, "checked_at"), _SAME_LISTING)
    # A page the file merely checked again and found unchanged (a 304: its checked_at alone moved) moves its record
    # alone, as a sitemap does: none of its rows written.
    changed = [n for n in listings if not _unchanged(theirs[n], mine.get(n), _SAME_LISTING)]

    def take_listings(c: sqlite3.Connection) -> None:
        _taken(c, changed)
        plan.checked += _replace(c, "lacuerda_index", "page")

    plan.take("listing page", len(changed), take_listings)
    if listings:
        plan.kv[li.PAGES_KEY] = json.dumps({**mine, **{n: theirs[n] for n in listings}}, ensure_ascii=False)
    if len(changed) < len(listings):
        plan.records.append("listing pages found unchanged")
    # An artist page's rows have no time of their own: the file's are taken where the database has none.
    artists = [r[0] for r in conn.execute(
        f"SELECT DISTINCT t.page FROM {THEIRS}.lacuerda_index t WHERE t.page LIKE '%/' AND t.page NOT LIKE 'tabs/%' "
        "AND NOT EXISTS (SELECT 1 FROM main.lacuerda_index m WHERE m.page = t.page) ORDER BY t.page")]

    def take_artists(c: sqlite3.Connection) -> None:
        _taken(c, artists)
        plan.checked += _replace(c, "lacuerda_index", "page")

    plan.take("artist page", len(artists), take_artists)
    search = f"FROM {THEIRS}.lacuerda_index t WHERE t.page = ? AND NOT EXISTS " \
             "(SELECT 1 FROM main.lacuerda_index m WHERE m.path = t.path)"
    found = conn.execute(f"SELECT COUNT(*) {search}", (li.SEARCH_PAGE,)).fetchone()[0]

    def take_search(c: sqlite3.Connection) -> None:
        cols = ", ".join(f"t.{col}" for col in _columns(c, "main", "lacuerda_index"))
        plan.checked += c.execute(f"INSERT OR IGNORE INTO main.lacuerda_index SELECT {cols} {search}",
                                  (li.SEARCH_PAGE,)).rowcount

    plan.take("row of its search's answers", found, take_search)
    _keys_again(conn, plan, li.KEYS_KEY)
    _later(conn, plan, li.COMPLETE_KEY, "listings read whole")


def _plan_ug(conn: sqlite3.Connection, plan: _Plan) -> None:
    from caracole.ug import artist_tabs
    from caracole.ug import index as ug

    names = [n for n in _newer_records(conn, ug.SITEMAPS_KEY, "indexed_at") if n not in plan.left]

    def take_sitemaps(c: sqlite3.Connection) -> None:
        _taken(c, names)
        new = [r[0] for r in c.execute(
            f"SELECT t.tab_id FROM {THEIRS}.ug_index t WHERE t.sitemap IN (SELECT name FROM {_TAKEN}) "
            "AND NOT EXISTS (SELECT 1 FROM main.ug_index m WHERE m.tab_id = t.tab_id) ORDER BY t.tab_id")]
        plan.checked += _take_ug_rows(c, plan.tell)
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
    _plan_directory(conn, plan)
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


def _take_ug_rows(c: sqlite3.Connection, tell: Progress) -> int:
    """The file's rows of UG's sitemaps taken (``_TAKEN``), as a refresh stores a sitemap (ug/index.py
    ``upsert_rows``): a row the database has keeps where and when it was first seen, and takes the file's keys and
    path. A statement for each ``UG_CHUNK`` of them, in ``tab_id`` order (the order one statement reads the file's
    table in, its rowid's: so the triggers' rows come out the same), each told: a chunk ends at the ``UG_CHUNK``-th
    row's ``tab_id`` after the last chunk's, the rest one chunk, its bound none (and so is a chunk that would end
    past the file's last row, which a file made by hand repeating a ``tab_id`` may hold). The rows it read: the count
    its chunks are cut by."""
    rows = f"FROM {THEIRS}.ug_index WHERE sitemap IN (SELECT name FROM {_TAKEN})"
    (total,) = c.execute(f"SELECT COUNT(*) {rows}").fetchone()
    done, after = 0, None
    while True:
        lower, low = ("", ()) if after is None else (" AND tab_id > ?", (after,))
        upto = None
        if total - done > UG_CHUNK:  # a file made by hand may repeat a tab_id: no row there, the rest one chunk
            row = c.execute(f"SELECT tab_id {rows}{lower} ORDER BY tab_id LIMIT 1 OFFSET ?",
                            (*low, UG_CHUNK - 1)).fetchone()
            upto = row[0] if row else None
        upper, up = ("", ()) if upto is None else (" AND tab_id <= ?", (upto,))
        c.execute(
            "INSERT INTO main.ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
            f"SELECT tab_id, artist_key, song_key, type, sitemap, first_seen, path {rows}{lower}{upper} "
            "ON CONFLICT (tab_id) DO UPDATE SET artist_key = excluded.artist_key, song_key = excluded.song_key, "
            "type = excluded.type, path = excluded.path "
            "WHERE ug_index.artist_key != excluded.artist_key OR ug_index.song_key != excluded.song_key "
            "OR ug_index.type != excluded.type OR ug_index.path != excluded.path", (*low, *up))
        done = total if upto is None else done + UG_CHUNK
        tell("ug", UG_TABS, done, total)
        if upto is None:
            return total
        after = upto


def _round(entry: Any) -> tuple[Any, ...]:
    """How far a listing's round of UG's artist directory has got, to compare two: its last whole read, then its
    round's start, then its next page (ug/directory.py ``LetterState``); a time missing or unreadable is earlier than
    any."""
    entry = entry if isinstance(entry, dict) else {}
    earliest = datetime.min.replace(tzinfo=UTC)

    def when(key: str) -> Any:
        value = entry.get(key)
        return (stamps.parse(value) if isinstance(value, str) else None) or earliest

    page = entry.get("next")
    return when("done"), when("started"), page if isinstance(page, int) and not isinstance(page, bool) else 0


def _plan_directory(conn: sqlite3.Connection, plan: _Plan) -> None:
    """UG's artist directory (ug/directory.py): a row the file saw later in a listing (``seen_at``), or one the
    database lacks, takes the file's listing columns; a page the file read later (``read_at``) its read columns; and a
    listing's round, the file's where it got further (``_round``), never back. A listing never removes an artist, so
    neither does a merge."""
    from caracole.ug import directory

    listed = ("name", "slug", "letter", "place", "tabs", "updated_at", "artist_key", "forms", "seen_at")
    seen = (f"FROM {THEIRS}.ug_directory t LEFT JOIN main.ug_directory m ON m.artist_id = t.artist_id "
            "WHERE m.artist_id IS NULL OR t.seen_at > m.seen_at")
    read = (f"FROM {THEIRS}.ug_directory t JOIN main.ug_directory m ON m.artist_id = t.artist_id "
            "WHERE t.read_at > m.read_at")
    seen_n = conn.execute(f"SELECT COUNT(*) {seen}").fetchone()[0]
    read_n = conn.execute(f"SELECT COUNT(*) {read}").fetchone()[0]

    def take_seen(c: sqlite3.Connection) -> None:
        cols = _columns(c, "main", "ug_directory")
        c.execute(f"INSERT INTO main.ug_directory ({', '.join(cols)}) SELECT {', '.join(cols)} FROM "
                  f"{THEIRS}.ug_directory WHERE true ON CONFLICT (artist_id) DO UPDATE SET "
                  + ", ".join(f"{col} = excluded.{col}" for col in listed)
                  + " WHERE excluded.seen_at > ug_directory.seen_at")

    def take_read(c: sqlite3.Connection) -> None:
        c.execute(f"UPDATE main.ug_directory AS m SET read_at = t.read_at, read_tabs = t.read_tabs, "
                  f"read_updated = t.read_updated FROM {THEIRS}.ug_directory AS t "
                  "WHERE t.artist_id = m.artist_id AND t.read_at > m.read_at")

    # The read columns first: a row the file saw later takes its listing columns alone.
    plan.take("artist page read of its directory", read_n, take_read)
    plan.take("artist of its directory", seen_n, take_seen)
    if seen_n:
        _keys_again(conn, plan, directory.KEYS_KEY)
    mine, theirs = _records(conn, "main", directory.LETTERS_KEY), _records(conn, THEIRS, directory.LETTERS_KEY)
    moved = sorted(letter for letter, entry in theirs.items()
                   if isinstance(entry, dict) and _round(entry) > _round(mine.get(letter)))
    if moved:
        plan.kv[directory.LETTERS_KEY] = json.dumps({k: v for k, v in sorted({**mine, **{n: theirs[n] for n in moved}}
                                                                              .items())}, ensure_ascii=False)
        plan.records.append("its directory's listings")


# --- the newest read -----------------------------------------------------------------------------------------------


def newest(conn: sqlite3.Connection) -> dict[str, str]:
    """Each site's newest read, by ``SITES``' order: the latest of the times a merge compares (its sitemaps' or
    listing pages' records, the read of each page of its that has one, and its progress records), as stored
    (``stamps.stamp``); a site with none is left out. A sync's state document says it (``peer_sync.state_document``'s
    ``indexes``), so that the other side asks only for the indexes read more recently than its own.

    What has no time of its own moves no site's stamp, as a merge compares none of it: LaCuerda's artist pages and its
    search's rows (a night that reads only those, its popular pages or a search, leaves ``lacuerda`` where it was,
    and the other side has them at the next listing page read), and UG's sitemap rows apart from their sitemap's
    record."""
    from caracole import gametabs_fetch, gtptabs_fetch, harptabs_fetch, lacuerda_index, musescore_fetch
    from caracole.ug import index as ug

    def recorded(key: str, stamp: str) -> list[Any]:
        return [entry.get(stamp) for entry in _records(conn, "main", key).values() if isinstance(entry, dict)]

    def read_at(table: str) -> list[Any]:
        return [r[0] for r in conn.execute(f"SELECT DISTINCT read_at FROM main.{table}")]

    def site_index(site: Any) -> list[Any]:
        return [*recorded(site.sitemaps_key, "checked_at"), _kv(conn, "main", site.complete_key)]

    from caracole.ug import directory

    times = {
        "ug": [*recorded(ug.SITEMAPS_KEY, "indexed_at"), *read_at("ug_artist_tabs"),
               _kv(conn, "main", ug.REFRESHED_KEY), _kv(conn, "main", ug.BUILT_KEY),
               *conn.execute("SELECT MAX(seen_at), MAX(read_at) FROM main.ug_directory").fetchone(),
               *recorded(directory.LETTERS_KEY, "done"), *recorded(directory.LETTERS_KEY, "started")],
        "lacuerda": [*recorded(lacuerda_index.PAGES_KEY, "checked_at"), _kv(conn, "main", lacuerda_index.COMPLETE_KEY)],
        "gtptabs": site_index(gtptabs_fetch.SITE),
        "musescore": site_index(musescore_fetch.SITE),
        "harptabs": [*site_index(harptabs_fetch.SITE), *read_at("harptabs_artists")],
        "gametabs": [*site_index(gametabs_fetch.SITE), *read_at("gametabs_games")],
    }
    found = {}
    for name in SITES:
        latest = max(filter(None, (stamps.parse(t) if isinstance(t, str) else None for t in times[name])),
                     default=None)
        if latest is not None:
            found[name] = stamps.stamp(latest)
    return found


def tab_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """The tabs each site's index tracks, by ``SITES``' order: the rows of its first table (UG's ``ug_index``,
    never its artist pages' tabs; LaCuerda's ``lacuerda_index``, …), which ``GET /api/sync/indexes`` answers and a
    sync's report counts before and after an index is merged."""
    return {name: conn.execute(f"SELECT COUNT(*) FROM main.{site.tables[0]}").fetchone()[0]
            for name, site in SITES.items()}


def held(conn: sqlite3.Connection, sites: Iterable[str] | None = None) -> set[str]:
    """The sites (of ``sites``, else every one) whose first table holds a row here: one row looked for each, no
    count, so a sync tells a site it updates from one it imports whole (``MergeWords``' ``held``)."""
    return {name for name in chosen(sites) if conn.execute(
        f"SELECT EXISTS (SELECT 1 FROM main.{SITES[name].tables[0]})").fetchone()[0]}


# --- applying ------------------------------------------------------------------------------------------------------


def _counts(conn: sqlite3.Connection, site: Site) -> dict[str, int]:
    return {t: conn.execute(f"SELECT COUNT(*) FROM main.{t}").fetchone()[0] for t in site.tables}


def _apply(conn: sqlite3.Connection, plan: _Plan, arrived: datetime | None = None) -> SiteMerge:
    site = SITES[plan.site]
    before = _counts(conn, site)
    with db.savepoint(conn, "index_merge"):
        for noun, n, action in plan.actions:
            plan.tell(plan.site, noun, 0, n)
            action(conn)
        for key, value in plan.kv.items():
            if value is None:
                db.kv_delete(conn, key)
            else:
                db.kv_set(conn, key, value)
        if arrived is not None and any(noun in _TIMED_NOUNS.get(plan.site, ()) for noun, _, _ in plan.actions):
            _note_arrival(conn, plan.site, arrived)
        _current_keys(conn, plan.site)
        conn.execute(f"DROP TABLE IF EXISTS {_TAKEN}")
    after = _counts(conn, site)
    return SiteMerge(plan.site, [(noun, n) for noun, n, _ in plan.actions], plan.records,
                     {t: (before[t], after[t]) for t in site.tables}, plan.checked)


def _note_arrival(conn: sqlite3.Connection, site: str, at: datetime) -> None:
    """kv ``ARRIVED_KEY``: this merge's time (``at``, the merge's own ``now``, this side's clock) and the earliest time the file holds in
    the site's tables read a row or a page at a time (text alone; "" for none, every row), appended to the site's
    list, the oldest two made one (the later time, the earlier low) past ``ARRIVALS_KEPT``: whatever a merge took,
    a partial export made after it sends (``_bound``), the rows of other caracoles' times among them."""
    lows = [conn.execute(f"SELECT MIN({column}) FROM {THEIRS}.{table} WHERE typeof({column}) = 'text' "
                         f"AND {column} != ''").fetchone()[0] for table, column in _TIMES[site]]
    low = min((v for v in lows if v is not None), default="")
    held = _records(conn, "main", ARRIVED_KEY)
    kept = held.get(site)
    entries = [e[:2] for e in kept if isinstance(e, list) and len(e) >= 2] if isinstance(kept, list) else []
    entries.append([stamps.stamp(at), low])
    while len(entries) > ARRIVALS_KEPT:
        (_, first), (at, second) = entries[0][:2], entries[1][:2]
        entries[:2] = [[at, min(first, second) if isinstance(first, str) and isinstance(second, str) else ""]]
    db.kv_set_json(conn, ARRIVED_KEY, {**held, site: entries})


def _current_keys(conn: sqlite3.Connection, name: str) -> None:
    """Each index's keys made current, as its next read would make them (and whole, its keys record let go)."""
    if name == "ug":
        from caracole.ug import artist_tabs, directory

        artist_tabs.ensure_current_keys(conn)
        directory.ensure_current_keys(conn)
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
