"""index_transfer.py: the site indexes into a file of their own (``caracole index export``), and such a file into
the database (``caracole index merge``): what each read more recently, page by page or sitemap by sitemap, never a
page or a sitemap lost, the database backed up first, and nothing the second time.

Each test fills two databases, "home" (the file's source) and "live" (``conn``: the one merged into), through the
indexes' own writers, so that their rows and progress records are the ones a read leaves.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import add_song, migrated_database
from typer.testing import CliRunner

from caracole import (
    backup,
    db,
    gametabs_fetch,
    gametabs_index,
    gtptabs_fetch,
    harptabs_fetch,
    harptabs_index,
    lacuerda_index,
    musescore_fetch,
    normalize,
    site_index,
)
from caracole import index_transfer as transfer
from caracole.gametabs import GamePage
from caracole.gametabs import ListedTab as GameListed
from caracole.harptabs import ArtistPage
from caracole.harptabs import ListedTab as HarpListed
from caracole.lacuerda import LCArtist, LCSong, Listing, SearchAnswer, SearchSong
from caracole.ug import artist_tabs
from caracole.ug import index as ug_index
from caracole.ug.sitemap import classify_tab_url

EARLY = datetime(2026, 10, 19, 3, 30, tzinfo=UTC)
LATE = datetime(2026, 10, 28, 3, 30, tzinfo=UTC)
NOW = datetime(2026, 10, 29, 18, 0, tzinfo=UTC)
TAB = "https://tabs.ultimate-guitar.com/tab/"
SITES = ("ug", "lacuerda", "gtptabs", "musescore", "harptabs", "gametabs")


def database(tmp_path: Path, name: str) -> sqlite3.Connection:
    path = tmp_path / name / "caracole.sqlite"
    path.parent.mkdir(parents=True)
    path.write_bytes(migrated_database())
    return db.connect(path)


@pytest.fixture
def home(tmp_path):
    c = database(tmp_path, "home")
    yield c
    c.close()


# --- what a read leaves, through the indexes' own writers --------------------------------------------------------


def ug_sitemap(conn, name: str, slugs: list[str], at: datetime) -> None:
    rows = [classify_tab_url(TAB + slug) for slug in slugs]
    ug_index._store(conn, name, rows, ug_index.TabCounts(len(rows), len(rows)), {"etag": f'"{name}-{at:%d}"',
                                                                              "last_modified": None}, at)


def ug_listed(conn, names: list[str], at: datetime, *, built: bool = True) -> None:
    db.kv_set_json(conn, ug_index.LISTED_KEY, names)
    db.kv_set(conn, ug_index.REFRESHED_KEY, at.strftime("%Y-%m-%dT%H:%M:%SZ"))
    if built:
        ug_index.mark_built(conn, at)


def artist_tab(conn, page: str, tab_id: int, title: str, read_at: datetime) -> None:
    """A tab of an artist page, as ``artist_tabs.store`` keeps one (its keys and forms its own ``_names``')."""
    artist_key, song_key, _, artist_forms, title_forms, forms = artist_tabs._names("Song Dongye", title)
    artist_tabs.ensure_current_keys(conn)
    conn.execute(
        "INSERT INTO ug_artist_tabs (page, tab_id, type, artist, title, label, rating, votes, url, artist_key, "
        "song_key, artist_forms, title_forms, forms, read_at) VALUES (?, ?, 'chords', 'Song Dongye', ?, NULL, 4.5, "
        "10, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (page, tab_id) DO UPDATE SET title = excluded.title, song_key = "
        "excluded.song_key, title_forms = excluded.title_forms, forms = excluded.forms, read_at = excluded.read_at",
        (page, tab_id, title, f"{TAB}{tab_id}", artist_key, song_key, artist_forms, title_forms, forms,
         read_at.strftime("%Y-%m-%dT%H:%M:%SZ")))
    artist_tabs.refile(conn, [page])  # filed as a read files them


def sitemap(conn, site: site_index.Site, name: str, locs: list[str], at: datetime) -> None:
    rows = [site.row(loc) for loc in locs]
    site_index._store(conn, site, name, rows, {"etag": f'"{name}-{at:%d}"', "last_modified": None}, at)


def game_page(conn, path: str, titles: list[str], at: datetime) -> None:
    listed = tuple(GameListed(f"{path.split('?')[0]}/{normalize.slug_key(t)}", t, composers=("Yuzo Koshiro",))
                   for t in titles)
    gametabs_index.store_game_page(conn, path, GamePage(path.split("/")[1].title(), len(titles), listed), at)


def harp_page(conn, path: str, titles: list[str], at: datetime) -> None:
    listed = tuple(HarpListed(100 + n, f"tab/{100 + n}/{normalize.slug_key(t)}", t) for n, t in enumerate(titles))
    harptabs_index.store_artist_page(conn, path, ArtistPage(path.split("/")[2].title(), len(titles), listed), at)


def listing(conn, page: str, artists: list[tuple[str, str]], at: datetime) -> None:
    found = Listing(tuple(LCArtist(slug, name, 3) for slug, name in artists), (page.split("/")[2],), len(artists))
    lacuerda_index._store(conn, page, found, {"etag": f'"{page}-{at:%d}"', "last_modified": None}, at)


def artist_songs(conn, slug: str, name: str, titles: list[str]) -> None:
    lacuerda_index.store_songs(conn, slug, name, [LCSong(normalize.slug_key(t).replace("-", "_"), t, "RA", (1, 2))
                                                  for t in titles])


def rows(conn, table: str, *, schema: str = "main") -> list[tuple]:
    return sorted(tuple(r) for r in conn.execute(f"SELECT * FROM {schema}.{table}"))


def kv(conn, key: str):
    return db.kv_get(conn, key)


def export(conn, tmp_path, sites=None, name="indexes.sqlite") -> Path:
    path = tmp_path / name
    transfer.export(conn, path, sites, now=NOW)
    return path


def merge(conn, path, sites=None, state=None):
    return transfer.merge(conn, path, sites, state_dir=state, now=NOW)


def full(conn) -> None:
    """Every site's index as a few reads left it."""
    ug_sitemap(conn, "1", ["radiohead/creep-chords-4169", "oasis/wonderwall-chords-27596"], EARLY)
    ug_sitemap(conn, "last", ["blur/song-2-chords-1001"], EARLY)
    ug_listed(conn, ["1", "last"], EARLY)
    artist_tab(conn, "https://www.ultimate-guitar.com/artist/634073", 2001, "斑马 斑马", EARLY)
    listing(conn, "tabs/e/index0.html", [("estopa", "Estopa"), ("enanitos_verdes", "Enanitos Verdes")], EARLY)
    db.kv_set(conn, lacuerda_index.COMPLETE_KEY, "2026-10-19T03:30:00Z")
    artist_songs(conn, "estopa", "Estopa", ["Como Camarón", "Vino Tinto"])
    lacuerda_index.store_search(conn, SearchAnswer(songs=(SearchSong("bunbury", "Enrique Bunbury", LCSong(
        "lady_blue", "Lady Blue", "RA", (1,))),)))
    sitemap(conn, gtptabs_fetch.SITE, "sitemap-tabs-1.xml", ["https://gtptabs.com/tabs/2/blur.html",
                                                             "https://gtptabs.com/tabs/2/blur/song-2-2.html"], EARLY)
    db.kv_set(conn, gtptabs_fetch.SITE.complete_key, "2026-10-19T03:30:00Z")
    sitemap(conn, musescore_fetch.SITE, "song-1", ["https://musescore.com/song/wonderwall-1524"], EARLY)
    sitemap(conn, harptabs_fetch.SITE, site_index.ONE, ["https://www.harptabs.com/artist/1178/billy-joel",
                                                         "https://www.harptabs.com/tab/25/piano-man"], EARLY)
    db.kv_set(conn, harptabs_fetch.KEYS_KEY, harptabs_fetch.ROW_KEYS)
    harp_page(conn, "artist/1178/billy-joel", ["Piano Man", "Honesty"], EARLY)
    sitemap(conn, gametabs_fetch.SITE, "sitemap-games.xml", ["https://gametabs.net/tabs/actraiser",
                                                             "https://gametabs.net/tabs/actraiser/fillmore"], EARLY)
    game_page(conn, "tabs/actraiser", ["Fillmore", "Bloodpool"], EARLY)


# --- export ------------------------------------------------------------------------------------------------------


def test_an_export_holds_each_sites_tables_and_progress_records_and_nothing_else(home, tmp_path):
    full(home)
    add_song(home)
    db.kv_set(home, "run:last", "{}")
    db.kv_set(home, "lacuerda:search:camaron-como", "{}")

    exported = transfer.export(home, tmp_path / "indexes.sqlite", now=NOW)

    assert exported.sites == SITES
    out = sqlite3.connect(tmp_path / "indexes.sqlite")
    try:
        meta = dict(out.execute(f"SELECT key, value FROM {transfer.META}"))
        tables = {r[0] for r in out.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        keys = {r[0] for r in out.execute("SELECT key FROM kv")}
        out.execute("ATTACH ? AS home", (str(tmp_path / "home" / "caracole.sqlite"),))
        same = {t: rows(out, t) == rows(out, t, schema="home") for t in tables - {"kv", transfer.META}}
    finally:
        out.close()
    assert meta["format"] == str(transfer.FORMAT) and meta["schema"] == str(db.SCHEMA_VERSION)
    assert json.loads(meta["sites"]) == list(SITES) and meta["exported_at"] == "2026-10-29T18:00:00Z"
    assert tables == {transfer.META, "kv", "ug_index", "ug_artist_tabs", "lacuerda_index", "gtptabs_index",
                      "musescore_index", "harptabs_index", "harptabs_artists", "harptabs_artist_tabs",
                      "gametabs_index", "gametabs_games", "gametabs_game_tabs"}
    assert all(same.values()), same
    assert keys == {"ug:sitemaps", "ug:index:listed", "ug:index:built_at", "ug:index:refreshed_at",
                    "ug:artist_tabs:keys", "lacuerda:index:pages", "lacuerda:index:complete_at",
                    "lacuerda:index:keys", "gtptabs:sitemaps", "gtptabs:index:complete_at", "musescore:sitemaps",
                    "harptabs:sitemaps", "harptabs:index:keys", "harptabs:artists:keys", "gametabs:sitemaps",
                    "gametabs:games:keys"}
    assert exported.rows["ug_index"] == 3 and exported.rows["harptabs_artist_tabs"] == 2


def test_an_export_of_some_sites(home, tmp_path):
    full(home)
    exported = transfer.export(home, tmp_path / "indexes.sqlite", ["gametabs", "harptabs"], now=NOW)
    assert exported.sites == ("harptabs", "gametabs")  # in caracole's order
    out = sqlite3.connect(tmp_path / "indexes.sqlite")
    try:
        tables = {r[0] for r in out.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        keys = {r[0] for r in out.execute("SELECT key FROM kv")}
    finally:
        out.close()
    assert tables == {transfer.META, "kv", "harptabs_index", "harptabs_artists", "harptabs_artist_tabs",
                      "gametabs_index", "gametabs_games", "gametabs_game_tabs"}
    assert all(k.startswith(("harptabs:", "gametabs:")) for k in keys)


def test_an_export_never_writes_over_a_file(home, tmp_path):
    there = tmp_path / "indexes.sqlite"
    there.write_bytes(b"mine")
    with pytest.raises(transfer.TransferError, match="already exists"):
        transfer.export(home, there, now=NOW)
    assert there.read_bytes() == b"mine"
    with pytest.raises(transfer.TransferError, match="is the database"):
        transfer.export(home, tmp_path / "home" / "caracole.sqlite", now=NOW)
    assert not list(tmp_path.glob("*.part"))


def test_an_unknown_site_is_refused(home, tmp_path):
    with pytest.raises(transfer.TransferError, match="no site 'spotify'.*ug, lacuerda"):
        transfer.export(home, tmp_path / "x.sqlite", ["spotify"], now=NOW)


# --- merge: round trips --------------------------------------------------------------------------------------------

TABLES = {
    "ug": ("ug_index", "ug_artist_tabs"),
    "lacuerda": ("lacuerda_index",),
    "gtptabs": ("gtptabs_index",),
    "musescore": ("musescore_index",),
    "harptabs": ("harptabs_index", "harptabs_artists", "harptabs_artist_tabs"),
    "gametabs": ("gametabs_index", "gametabs_games", "gametabs_game_tabs"),
}


@pytest.mark.parametrize("site", SITES)
def test_an_empty_database_takes_a_sites_whole_index_and_a_second_merge_changes_nothing(home, conn, tmp_path, site):
    full(home)
    path = export(home, tmp_path, [site])

    merged = merge(conn, path, state=tmp_path / "state")

    [done] = merged.sites
    assert done.site == site and done.changed
    for table in TABLES[site]:
        assert rows(conn, table) == rows(home, table), table
    for key in transfer.SITES[site].kv:
        assert kv(conn, key) == kv(home, key), key
    assert merged.backup is not None and merged.backup.name.endswith("-before-merge.sqlite")
    before = {t: rows(conn, t) for t in TABLES[site]}

    again = merge(conn, path, state=tmp_path / "state")

    assert not again.changed and again.backup is None
    assert {t: rows(conn, t) for t in TABLES[site]} == before
    assert len(backup.backups(tmp_path / "state")) == 1


def test_every_site_at_once(home, conn, tmp_path):
    full(home)
    merged = merge(conn, export(home, tmp_path), state=tmp_path / "state")
    assert [s.site for s in merged.sites] == list(SITES) and merged.changed
    for tables in TABLES.values():
        for table in tables:
            assert rows(conn, table) == rows(home, table), table


# --- merge: what was read more recently wins ---------------------------------------------------------------------


def test_gametabs_takes_each_game_page_read_more_recently_and_keeps_the_rest(home, conn, tmp_path):
    game_page(home, "tabs/actraiser", ["Fillmore", "Bloodpool", "Kasandora"], LATE)  # read again since
    game_page(conn, "tabs/actraiser", ["Fillmore"], EARLY)
    game_page(home, "tabs/ys", ["Feena"], EARLY)  # read earlier than the database's
    game_page(conn, "tabs/ys", ["Feena", "First Step Towards Wars"], LATE)
    game_page(conn, "tabs/hollow-knight", ["Resting Grounds"], EARLY)  # the database's alone
    game_page(home, "tabs/celeste", ["Resurrections"], EARLY)  # the file's alone

    merged = merge(conn, export(home, tmp_path, ["gametabs"]), state=tmp_path / "state")

    titles = {page: sorted(r[0] for r in conn.execute("SELECT title FROM gametabs_game_tabs WHERE page = ?", (page,)))
              for page in ("tabs/actraiser", "tabs/ys", "tabs/hollow-knight", "tabs/celeste")}
    assert titles == {"tabs/actraiser": ["Bloodpool", "Fillmore", "Kasandora"],
                      "tabs/ys": ["Feena", "First Step Towards Wars"],
                      "tabs/hollow-knight": ["Resting Grounds"], "tabs/celeste": ["Resurrections"]}
    read = dict(conn.execute("SELECT path, read_at FROM gametabs_games"))
    assert read == {"tabs/actraiser": "2026-10-28T03:30:00Z", "tabs/ys": "2026-10-28T03:30:00Z",
                    "tabs/hollow-knight": "2026-10-19T03:30:00Z", "tabs/celeste": "2026-10-19T03:30:00Z"}
    [done] = merged.sites
    assert ("game page", 2) in done.taken
    assert done.rows["gametabs_game_tabs"] == (4, 7)


def test_a_page_gone_since_is_gone_from_the_database_too(home, conn, tmp_path):
    game_page(conn, "tabs/actraiser", ["Fillmore"], EARLY)
    gametabs_index.store_gone(home, "tabs/actraiser", LATE)  # answered 404 when read again

    merge(conn, export(home, tmp_path, ["gametabs"]), state=tmp_path / "state")

    assert [tuple(r) for r in conn.execute("SELECT name FROM gametabs_games")] == [("",)]
    assert rows(conn, "gametabs_game_tabs") == []


def test_harptabs_takes_each_artist_page_read_more_recently(home, conn, tmp_path):
    harp_page(home, "artist/1178/billy-joel", ["Piano Man", "Honesty", "Vienna"], LATE)
    harp_page(conn, "artist/1178/billy-joel", ["Piano Man"], EARLY)
    harp_page(conn, "artist/9/bob-dylan", ["Blowin' in the Wind"], LATE)
    harp_page(home, "artist/9/bob-dylan", [], EARLY)

    merge(conn, export(home, tmp_path, ["harptabs"]), state=tmp_path / "state")

    titles = dict(conn.execute("SELECT artist, group_concat(title, '|') FROM (SELECT * FROM harptabs_artist_tabs "
                               "ORDER BY place) GROUP BY artist"))
    assert titles == {"artist/1178/billy-joel": "Piano Man|Honesty|Vienna", "artist/9/bob-dylan": "Blowin' in the Wind"}


def test_a_sitemap_read_more_recently_replaces_its_rows_and_the_others_stay(home, conn, tmp_path):
    site = gtptabs_fetch.SITE
    sitemap(home, site, "sitemap-tabs-1.xml", ["https://gtptabs.com/tabs/2/blur.html",
                                               "https://gtptabs.com/tabs/2/blur/beetlebum.html"], LATE)
    sitemap(conn, site, "sitemap-tabs-1.xml", ["https://gtptabs.com/tabs/2/blur.html"], EARLY)
    sitemap(home, site, "sitemap-tabs-2.xml", ["https://gtptabs.com/tabs/3/oasis.html"], EARLY)
    sitemap(conn, site, "sitemap-tabs-2.xml", ["https://gtptabs.com/tabs/3/oasis.html",
                                               "https://gtptabs.com/tabs/3/oasis/wonderwall.html"], LATE)
    sitemap(conn, site, "sitemap-tabs-3.xml", ["https://gtptabs.com/tabs/4/pulp.html"], EARLY)
    db.kv_set(conn, site.complete_key, "2026-10-19T03:30:00Z")
    db.kv_set(home, site.complete_key, "2026-10-28T03:30:00Z")

    merged = merge(conn, export(home, tmp_path, ["gtptabs"]), state=tmp_path / "state")

    paths = {r[0] for r in conn.execute("SELECT path FROM gtptabs_index")}
    assert paths == {"tabs/2/blur.html", "tabs/2/blur/beetlebum.html", "tabs/3/oasis.html",
                     "tabs/3/oasis/wonderwall.html", "tabs/4/pulp.html"}
    records = site_index.sitemaps(conn, site)
    assert records["sitemap-tabs-1.xml"]["etag"] == '"sitemap-tabs-1.xml-28"'
    assert records["sitemap-tabs-2.xml"]["etag"] == '"sitemap-tabs-2.xml-28"'
    assert set(records) == {"sitemap-tabs-1.xml", "sitemap-tabs-2.xml", "sitemap-tabs-3.xml"}
    assert kv(conn, site.complete_key) == "2026-10-28T03:30:00Z"
    assert ("sitemap", 1) in merged.sites[0].taken


def test_ug_takes_each_sitemap_indexed_more_recently_and_marks_the_songs_its_new_tabs_are_for(home, conn, tmp_path):
    from caracole.songs import get_song, update_song

    ug_sitemap(conn, "1", ["radiohead/creep-chords-4169"], EARLY)
    ug_sitemap(conn, "last", ["blur/song-2-chords-1001"], LATE)
    ug_listed(conn, ["1", "last"], EARLY, built=False)
    ug_sitemap(home, "1", ["radiohead/creep-chords-4169", "radiohead/creep-chords-5000"], LATE)
    ug_sitemap(home, "last", ["blur/song-2-chords-1001", "blur/beetlebum-chords-1002"], EARLY)
    ug_sitemap(home, "2", ["oasis/wonderwall-chords-27596"], LATE)
    ug_listed(home, ["1", "2", "last"], LATE)
    song = add_song(conn, "Radiohead", "Creep")
    update_song(conn, song.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep",
                ug_dirty=False)

    merged = merge(conn, export(home, tmp_path, ["ug"]), state=tmp_path / "state")

    assert {r[0] for r in conn.execute("SELECT tab_id FROM ug_index")} == {4169, 5000, 1001, 27596}  # not 1002
    assert get_song(conn, song.id).ug_dirty  # a new tab of its song: fetched again
    records = ug_index._indexed(conn)
    assert records["1"]["indexed_at"] == records["2"]["indexed_at"] == "2026-10-28T03:30:00Z"
    assert records["last"]["indexed_at"] == "2026-10-28T03:30:00Z"  # the database's own
    assert kv(conn, ug_index.BUILT_KEY) == "2026-10-28T03:30:00Z"
    assert db.kv_get_json(conn, ug_index.LISTED_KEY) == ["1", "2", "last"]
    assert ug_index.index_state(conn) == "complete"
    assert ("sitemap", 2) in merged.sites[0].taken
    # Its search tables follow the rows, by their triggers.
    assert conn.execute("SELECT 1 FROM ug_artists WHERE artist_key = 'oasis'").fetchone() is not None


def test_a_tab_the_file_names_anew_in_words_the_database_knows_is_merged(home, conn, tmp_path):
    ug_sitemap(conn, "1", ["blur/hello-world-chords-1", "blur/moon-chords-2"], EARLY)
    ug_listed(conn, ["1"], EARLY)
    ug_sitemap(home, "1", ["blur/hello-moon-chords-1", "blur/moon-chords-2"], LATE)
    ug_listed(home, ["1"], LATE)

    merge(conn, export(home, tmp_path, ["ug"]), state=tmp_path / "state")

    assert [r[2] for r in rows(conn, "ug_index")] == ["hello-moon", "moon"]


def test_ug_artist_pages_tabs_are_taken_where_read_more_recently(home, conn, tmp_path):
    page = "https://www.ultimate-guitar.com/artist/634073"
    artist_tab(conn, page, 2001, "Banma", EARLY)
    artist_tab(home, page, 2001, "斑马 斑马", LATE)
    artist_tab(conn, page, 2002, "Ai Ni", LATE)
    artist_tab(home, page, 2002, "old name", EARLY)
    artist_tab(home, page, 2003, "Moscow", EARLY)

    merge(conn, export(home, tmp_path, ["ug"]), state=tmp_path / "state")

    assert dict(conn.execute("SELECT tab_id, title FROM ug_artist_tabs")) == {2001: "斑马 斑马", 2002: "Ai Ni",
                                                                             2003: "Moscow"}


def test_lacuerda_takes_listing_pages_read_more_recently_and_the_artist_pages_it_lacks(home, conn, tmp_path):
    listing(home, "tabs/e/index0.html", [("estopa", "Estopa"), ("el_canto_del_loco", "El Canto del Loco")], LATE)
    listing(conn, "tabs/e/index0.html", [("estopa", "Estopa")], EARLY)
    listing(home, "tabs/m/index0.html", [("mana", "Maná")], EARLY)
    listing(conn, "tabs/m/index0.html", [("mana", "Maná"), ("mecano", "Mecano")], LATE)
    artist_songs(home, "estopa", "Estopa", ["Como Camarón", "Vino Tinto"])
    artist_songs(conn, "mana", "Maná", ["Rayando el Sol"])
    artist_songs(home, "mana", "Maná", ["Oye Mi Amor"])  # no time to tell which is newer: the database's stays
    lacuerda_index.store_search(home, SearchAnswer(songs=(SearchSong("bunbury", "Enrique Bunbury", LCSong(
        "lady_blue", "Lady Blue", "RA", (1,))),)))

    merge(conn, export(home, tmp_path, ["lacuerda"]), state=tmp_path / "state")

    by_page: dict[str, set[str]] = {}
    for path, page in conn.execute("SELECT path, page FROM lacuerda_index"):
        by_page.setdefault(page, set()).add(path)
    assert by_page == {
        "tabs/e/index0.html": {"estopa/", "el_canto_del_loco/"},
        "tabs/m/index0.html": {"mana/", "mecano/"},
        "estopa/": {"estopa/como_camaron", "estopa/vino_tinto"},
        "mana/": {"mana/rayando_el_sol"},
        lacuerda_index.SEARCH_PAGE: {"bunbury/lady_blue", "bunbury/"},
    }


# --- keys ----------------------------------------------------------------------------------------------------------


def test_rows_keyed_by_another_caracole_are_keyed_again(home, conn, tmp_path):
    game_page(home, "tabs/actraiser", ["Fillmore"], LATE)
    home.execute("UPDATE gametabs_game_tabs SET title_key = 'keyed-the-old-way'")
    db.kv_set(home, gametabs_index.KEYS_KEY, "0")

    merge(conn, export(home, tmp_path, ["gametabs"]), state=tmp_path / "state")

    assert [tuple(r) for r in conn.execute("SELECT title_key FROM gametabs_game_tabs")] == [("fillmore",)]
    assert kv(conn, gametabs_index.KEYS_KEY) == str(normalize.KEY_VERSION)


# --- what is refused -------------------------------------------------------------------------------------------------


def snapshot(conn) -> list:
    return [rows(conn, t) for tables in TABLES.values() for t in tables] + [rows(conn, "kv")]


def test_a_file_of_another_schema_is_refused_and_nothing_changes(home, conn, tmp_path):
    full(home)
    path = export(home, tmp_path)
    out = sqlite3.connect(path)
    out.execute(f"UPDATE {transfer.META} SET value = ? WHERE key = 'schema'", (str(db.SCHEMA_VERSION + 1),))
    out.commit()
    out.close()
    before = snapshot(conn)

    with pytest.raises(transfer.TransferError, match=f"schema version {db.SCHEMA_VERSION + 1}"):
        merge(conn, path, state=tmp_path / "state")

    assert snapshot(conn) == before
    assert backup.backups(tmp_path / "state") == []


def test_a_table_whose_columns_differ_is_refused_and_nothing_changes(home, conn, tmp_path):
    full(home)
    path = export(home, tmp_path)
    out = sqlite3.connect(path)
    out.execute("ALTER TABLE gametabs_games ADD COLUMN platform TEXT")
    out.commit()
    out.close()
    before = snapshot(conn)

    with pytest.raises(transfer.TransferError, match="gametabs_games.*platform"):
        merge(conn, path, state=tmp_path / "state")

    assert snapshot(conn) == before
    assert backup.backups(tmp_path / "state") == []


def test_a_file_that_is_no_export_is_refused(conn, tmp_path):
    other = tmp_path / "other.sqlite"
    sqlite3.connect(other).close()
    with pytest.raises(transfer.TransferError, match="no index export"):
        merge(conn, other, state=tmp_path / "state")
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"not a database, not at all" * 100)
    with pytest.raises(transfer.TransferError, match="no index export"):
        merge(conn, junk, state=tmp_path / "state")
    with pytest.raises(transfer.TransferError, match="no such file"):
        merge(conn, tmp_path / "missing.sqlite", state=tmp_path / "state")


def test_a_site_the_file_lacks_is_refused(home, conn, tmp_path):
    path = export(home, tmp_path, ["gametabs"])
    with pytest.raises(transfer.TransferError, match="holds no harptabs index.*gametabs"):
        merge(conn, path, ["harptabs"], state=tmp_path / "state")


def test_merging_some_sites_of_a_file(home, conn, tmp_path):
    full(home)
    merged = merge(conn, export(home, tmp_path), ["harptabs"], state=tmp_path / "state")
    assert [s.site for s in merged.sites] == ["harptabs"]
    assert rows(conn, "harptabs_artists") == rows(home, "harptabs_artists")
    assert rows(conn, "gametabs_games") == []


def test_no_room_for_the_backup_no_merge(home, conn, tmp_path, monkeypatch):
    from types import SimpleNamespace

    full(home)
    path = export(home, tmp_path)
    monkeypatch.setattr(backup, "disk_usage", lambda p: SimpleNamespace(total=1, used=1, free=1))
    before = snapshot(conn)

    with pytest.raises(transfer.TransferError, match="no room"):
        merge(conn, path, state=tmp_path / "state")

    assert snapshot(conn) == before


# --- the commands --------------------------------------------------------------------------------------------------


def invoke(tmp_path, *args):
    from caracole.cli import build_app

    config = tmp_path / "caracole.toml"
    config.write_text(f'data_dir = "{tmp_path / "data"}"\n', encoding="utf-8")
    return CliRunner().invoke(build_app(), ["--config", str(config), "index", *args])


def test_the_commands_export_and_merge_and_say_what_changed(tmp_path, monkeypatch):
    monkeypatch.delenv("CARACOLE_CONFIG", raising=False)
    state = tmp_path / "data" / "state"
    state.mkdir(parents=True)
    source = db.connect(state / "caracole.sqlite")
    try:
        game_page(source, "tabs/actraiser", ["Fillmore", "Bloodpool"], LATE)
    finally:
        source.close()
    path = tmp_path / "out" / "indexes.sqlite"
    path.parent.mkdir()

    exported = invoke(tmp_path, "export", str(path), "--site", "gametabs")

    assert exported.exit_code == 0, exported.output
    assert exported.stdout.splitlines()[0].startswith(f"Exported gametabs.net's index to {path} (")
    assert "gametabs_game_tabs 2" in exported.stdout
    os.remove(state / "caracole.sqlite")
    for extra in ("-wal", "-shm"):
        (state / f"caracole.sqlite{extra}").unlink(missing_ok=True)

    merged = invoke(tmp_path, "merge", str(path))

    assert merged.exit_code == 0, merged.output
    lines = merged.stdout.splitlines()
    assert lines[0].startswith(f"Backed up the database to {state / 'backups'}/caracole-")
    assert lines[1] == f"Merged {path} into {state / 'caracole.sqlite'}:"
    assert lines[2] == ("  gametabs.net: 1 game page; gametabs_index 0 rows (unchanged), gametabs_games 0 → 1, "
                        "gametabs_game_tabs 0 → 2.")

    again = invoke(tmp_path, "merge", str(path))

    assert again.exit_code == 0, again.output
    assert again.stdout == (f"Nothing to merge: {state / 'caracole.sqlite'} holds everything {path} does, "
                            "read as recently.\n")


def test_the_merge_command_refuses_a_mismatch_with_status_2(tmp_path, monkeypatch):
    monkeypatch.delenv("CARACOLE_CONFIG", raising=False)
    other = tmp_path / "other.sqlite"
    sqlite3.connect(other).close()
    result = invoke(tmp_path, "merge", str(other))
    assert result.exit_code == 2
    assert "no index export" in result.stderr


def test_an_export_into_no_folder_is_refused(home, tmp_path):
    with pytest.raises(transfer.TransferError, match="is no folder"):
        transfer.export(home, tmp_path / "nowhere" / "indexes.sqlite", now=NOW)
