import gzip
import hashlib
import time
from datetime import UTC, datetime

import httpx
import pytest

from caracole.config import ProviderPolicy
from caracole.http import PoliteClient, ProviderError
from caracole.songs import get_song, update_song
from caracole.ug.index import (
    IndexPlan,
    IndexStats,
    SitemapRead,
    TabCounts,
    build_index,
    describe_sitemaps,
    index_count,
    index_coverage,
    index_stats,
    mark_dirty_for_new,
    refresh_index,
    upsert_rows,
)
from caracole.ug.sitemap import IndexRow

from conftest import add_song

NOW = datetime(2026, 10, 18, 3, 30, tzinfo=UTC)
LATER = datetime(2026, 10, 19, 3, 30, tzinfo=UTC)
WWW = "https://www.ultimate-guitar.com/"
TAB = "https://tabs.ultimate-guitar.com/tab/"


def urlset(*paths: str) -> bytes:
    """A tab sitemap in UG's shape: one <url> per path, with an hreflang alternate."""
    urls = "".join(
        f"<url><loc>{TAB}{p}</loc><lastmod>2026-10-01</lastmod>"
        f'<xhtml:link rel="alternate" hreflang="es" href="https://es.ultimate-guitar.com/tab/{p}"/></url>'
        for p in paths
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        f'xmlns:xhtml="http://www.w3.org/1999/xhtml">{urls}</urlset>'
    ).encode()


def sitemap_index(*names: str) -> bytes:
    items = "".join(f"<sitemap><loc>{WWW}{n}</loc><lastmod>2026-10-18</lastmod></sitemap>" for n in names)
    return (
        '<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{items}</sitemapindex>"
    ).encode()


class FakeUG:
    """www.ultimate-guitar.com's sitemaps, with ETags and If-None-Match handling."""

    def __init__(self, files: dict[str, bytes]):
        self.files = dict(files)
        self.requests: list[tuple[str, str | None]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        name = request.url.path.lstrip("/")
        self.requests.append((name, request.headers.get("if-none-match")))
        body = self.files.get(name)
        if body is None:
            return httpx.Response(404, content=b"not found")
        etag = '"' + hashlib.sha256(body).hexdigest()[:16] + '"'
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304, headers={"etag": etag})
        return httpx.Response(200, content=body, headers={"etag": etag, "content-type": "text/xml"})

    def client(self, cache_dir, budget: int = 100) -> PoliteClient:
        return PoliteClient(
            "ug", ProviderPolicy(budget=budget, delay=(0, 0)), cache_dir, user_agent="test",
            transport=httpx.MockTransport(self.handler), sleep=lambda s: None,
        )

    def names(self) -> list[str]:
        return [name for name, _ in self.requests]


S1 = urlset(
    "oasis/wonderwall-chords-1001",
    "oasis/wonderwall-tabs-1002",
    "oasis/wonderwall-bass-1003",
    "1004",
    "the-rifles/the-general-chords-1005",
    "queen/the-miracle-tabs-1006",
    "oasis/wonderwall-ukulele-1007",
)
S2 = urlset("oasis/champagne-supernova-chords-2001", "radiohead/creep-chords-2002")
LAST = urlset("radiohead/creep-chords-2002", "radiohead/creep-acoustic-tabs-3001")


def site(**extra: bytes) -> FakeUG:
    files = {
        "sitemap.xml": sitemap_index(
            "sitemap_news.xml", "sitemap2.xml", "sitemap_ukulele1.xml", "sitemap1.xml", "sitemap_last.xml"
        ),
        "sitemap1.xml": S1,
        "sitemap2.xml": S2,
        "sitemap_last.xml": LAST,
        "sitemap_news.xml": urlset("x/y-chords-9"),
        "sitemap_ukulele1.xml": urlset("x/y-ukulele-8"),
    }
    files.update(extra)
    return FakeUG(files)


def rows(conn):
    return [tuple(r) for r in conn.execute(
        "SELECT tab_id, artist_key, song_key, type, sitemap, first_seen, path FROM ug_index ORDER BY tab_id"
    )]


def test_build_inserts_kept_types_only(conn, tmp_path):
    ug = site()
    stats = build_index(conn, ug.client(tmp_path / "cache"), NOW)
    assert rows(conn) == [
        (1001, "oasis", "wonderwall", "chords", "1", "2026-10-18T03:30:00Z", "oasis/wonderwall-chords-1001"),
        (1002, "oasis", "wonderwall", "tabs", "1", "2026-10-18T03:30:00Z", "oasis/wonderwall-tabs-1002"),
        (1005, "rifles", "general", "chords", "1", "2026-10-18T03:30:00Z", "the-rifles/the-general-chords-1005"),
        (1006, "queen", "miracle", "tabs", "1", "2026-10-18T03:30:00Z", "queen/the-miracle-tabs-1006"),
        (2001, "oasis", "champagne-supernova", "chords", "2", "2026-10-18T03:30:00Z",
         "oasis/champagne-supernova-chords-2001"),
        (2002, "radiohead", "creep", "chords", "2", "2026-10-18T03:30:00Z", "radiohead/creep-chords-2002"),
        (3001, "radiohead", "creep-acoustic", "tabs", "last", "2026-10-18T03:30:00Z",
         "radiohead/creep-acoustic-tabs-3001"),
    ]
    assert ug.names() == ["sitemap.xml", "sitemap1.xml", "sitemap2.xml", "sitemap_last.xml"]
    # 2002 is listed by sitemap2 and sitemap_last: one row, reported new once.
    assert stats == IndexStats(sitemaps_fetched=3, sitemaps_unchanged=0, rows=8,
                               new_tab_ids=(1001, 1002, 1005, 1006, 2001, 2002, 3001),
                               parsed=("1", "2", "last"), completed=True)
    assert index_count(conn) == 7


def test_build_again_revalidates_instead_of_using_the_cache(conn, tmp_path):
    ug = site()
    build_index(conn, ug.client(tmp_path / "cache"), NOW)
    ug.requests.clear()
    stats = build_index(conn, ug.client(tmp_path / "cache"), LATER)
    assert ug.names() == ["sitemap.xml", "sitemap1.xml", "sitemap2.xml", "sitemap_last.xml"]
    assert all(etag for _, etag in ug.requests)
    assert stats == IndexStats(sitemaps_fetched=0, sitemaps_unchanged=3, rows=0, new_tab_ids=())


def test_refresh_unchanged_sitemaps_parse_nothing(conn, tmp_path):
    ug = site()
    build_index(conn, ug.client(tmp_path / "cache"), NOW)
    ug.requests.clear()
    stats = refresh_index(conn, ug.client(tmp_path / "cache"), LATER)
    # the index, the highest-numbered sitemap and sitemap_last, each revalidated with If-None-Match
    assert ug.names() == ["sitemap.xml", "sitemap2.xml", "sitemap_last.xml"]
    assert all(etag for _, etag in ug.requests)
    assert stats == IndexStats(sitemaps_fetched=0, sitemaps_unchanged=2, rows=0, new_tab_ids=())


def test_guitar_pro_and_power_tab_files_are_counted_by_type_and_left_out(conn, tmp_path):
    # caracole uses no Guitar Pro or Power Tab file of Ultimate Guitar's, so no song matches one and nothing lists one.
    ug = site(**{"sitemap_last.xml": urlset("radiohead/creep-chords-2002", "radiohead/creep-guitar-pro-3101",
                                            "metallica/one-power-3102")})
    seen = []
    build_index(conn, ug.client(tmp_path / "cache"), NOW, progress=seen.append)
    assert 3101 not in [r[0] for r in rows(conn)] and 3102 not in [r[0] for r in rows(conn)]
    assert seen[-1].tabs == TabCounts(urls=3, indexed=1, other={"guitar-pro": 1, "power": 1})
    assert set(index_stats(conn)["types"]) == {"chords", "tabs"}


def test_refresh_returns_new_ids_and_marks_song_dirty(conn, tmp_path):
    ug = site()
    build_index(conn, ug.client(tmp_path / "cache"), NOW)
    creep = add_song(conn, "Radiohead", "Creep")
    wonderwall = add_song(conn, "Oasis", "Wonderwall")
    for s, key in ((creep, "creep"), (wonderwall, "wonderwall")):
        update_song(conn, s.id, match_decision="accept", match_artist_key=s.key.split("/")[0],
                    match_song_key=key, ug_dirty=False)
    ug.files["sitemap_last.xml"] = urlset(
        "radiohead/creep-chords-2002", "radiohead/creep-acoustic-tabs-3001", "radiohead/creep-intro-tabs-3002"
    )
    stats = refresh_index(conn, ug.client(tmp_path / "cache"), LATER)
    assert stats.new_tab_ids == (3002,)
    assert stats.sitemaps_fetched == 1 and stats.sitemaps_unchanged == 1 and stats.rows == 3
    assert rows(conn)[-1] == (3002, "radiohead", "creep-intro", "tabs", "last", "2026-10-19T03:30:00Z",
                              "radiohead/creep-intro-tabs-3002")
    # the refresh marked the song, and its stats say which, for the pipeline and `caracole index refresh` to count
    assert get_song(conn, creep.id).ug_dirty is True
    assert get_song(conn, wonderwall.id).ug_dirty is False
    assert stats.songs_marked == frozenset({creep.id})


def test_the_songs_each_sitemaps_new_tabs_mark_are_summed_up_once(conn, tmp_path):
    ug = site()
    build_index(conn, ug.client(tmp_path / "cache"), NOW)
    hotel = accepted(conn, "Eagles", "Hotel California", "eagles", "hotel-california")
    desperado = accepted(conn, "Eagles", "Desperado", "eagles", "desperado", decision="pinned")
    creep = accepted(conn, "Radiohead", "Creep", "radiohead", "creep")
    ug.files["sitemap.xml"] = sitemap_index("sitemap1.xml", "sitemap2.xml", "sitemap3.xml", "sitemap_last.xml")
    ug.files["sitemap3.xml"] = urlset("eagles/hotel-california-chords-4001", "eagles/desperado-chords-4002")
    ug.files["sitemap_last.xml"] = urlset("eagles/desperado-tabs-4003", "radiohead/creep-chords-2002")
    stats = refresh_index(conn, ug.client(tmp_path / "cache"), LATER)
    assert stats.new_tab_ids == (4001, 4002, 4003)
    # Desperado has a new tab in both sitemaps, and Creep only one it had: each song marked counts once
    assert stats.songs_marked == frozenset({hotel, desperado})
    assert [get_song(conn, i).ug_dirty for i in (hotel, desperado, creep)] == [True, True, False]


def test_refresh_picks_up_new_numbered_sitemaps(conn, tmp_path):
    ug = site()
    build_index(conn, ug.client(tmp_path / "cache"), NOW)
    ug.files["sitemap.xml"] = sitemap_index(
        "sitemap1.xml", "sitemap2.xml", "sitemap3.xml", "sitemap4.xml", "sitemap_last.xml"
    )
    ug.files["sitemap3.xml"] = urlset("eagles/hotel-california-chords-4001")
    ug.files["sitemap4.xml"] = urlset("eagles/desperado-chords-4002")
    ug.requests.clear()
    stats = refresh_index(conn, ug.client(tmp_path / "cache"), LATER)
    assert ug.names() == ["sitemap.xml", "sitemap3.xml", "sitemap4.xml", "sitemap_last.xml"]
    assert stats.new_tab_ids == (4001, 4002)
    ug.requests.clear()
    refresh_index(conn, ug.client(tmp_path / "cache"), LATER)
    assert ug.names() == ["sitemap.xml", "sitemap4.xml", "sitemap_last.xml"]


def test_build_reports_its_plan_before_it_asks_for_a_tab_sitemap(conn, tmp_path):
    ug = site()
    seen = []
    build_index(conn, ug.client(tmp_path / "cache"), NOW, progress=lambda event: seen.append((event, ug.names())))
    plan, asked = seen[0]
    assert plan == IndexPlan(listed=("1", "2", "last"), reads=("1", "2", "last"))
    assert asked == ["sitemap.xml"]
    assert plan.expected_urls == 150_000  # a sitemap holds at most 50,000 URLs, and UG fills its numbered ones


def test_build_reports_what_each_sitemap_held(conn, tmp_path):
    ug = site()
    seen = []
    build_index(conn, ug.client(tmp_path / "cache"), NOW, progress=seen.append)
    # sitemap1: 4 rows, the bare id 1004, and a bass and a ukulele tab the index doesn't keep
    assert seen[1:] == [
        SitemapRead(1, 3, "1", "sitemap1.xml", tabs=TabCounts(urls=7, indexed=4, bare=1, other={"bass": 1, "ukulele": 1}),
                    new_tab_ids=(1001, 1002, 1005, 1006)),
        SitemapRead(2, 3, "2", "sitemap2.xml", tabs=TabCounts(urls=2, indexed=2), new_tab_ids=(2001, 2002)),
        SitemapRead(3, 3, "last", "sitemap_last.xml", tabs=TabCounts(urls=2, indexed=2), new_tab_ids=(3001,)),
    ]


def test_refresh_reports_its_plan_and_each_sitemap_unchanged(conn, tmp_path):
    ug = site()
    build_index(conn, ug.client(tmp_path / "cache"), NOW)
    seen = []
    refresh_index(conn, ug.client(tmp_path / "cache"), LATER, progress=seen.append)
    assert seen == [
        IndexPlan(listed=("1", "2", "last"), reads=("2", "last"), indexed=("2", "last")),
        SitemapRead(1, 2, "2", "sitemap2.xml", unchanged=True),
        SitemapRead(2, 2, "last", "sitemap_last.xml", unchanged=True),
    ]
    assert seen[0].expected_urls == 0  # both indexed already: nothing is expected to be downloaded


def test_a_plan_counts_the_sitemaps_the_http_cache_holds(tmp_path):
    """A fresh database next to a warm HTTP cache: a 304 then serves each sitemap, and nothing is downloaded."""
    from caracole import db

    ug = site()
    build_index(db.connect(tmp_path / "a.sqlite"), ug.client(tmp_path / "cache"), NOW)
    seen = []
    build_index(db.connect(tmp_path / "b.sqlite"), ug.client(tmp_path / "cache"), LATER, progress=seen.append)
    assert seen[0] == IndexPlan(listed=("1", "2", "last"), reads=("1", "2", "last"), cached=("1", "2", "last"))
    assert [(e.from_cache, e.tabs.indexed) for e in seen[1:]] == [(True, 4), (True, 2), (True, 2)]


def test_build_from_dir_reports_each_file(conn, tmp_path):
    d = tmp_path / "sitemaps"
    d.mkdir()
    (d / "sitemap2.xml").write_bytes(S2)
    (d / "sitemap_last.xml.gz").write_bytes(gzip.compress(LAST))
    seen = []
    build_index(conn, None, NOW, from_dir=d, progress=seen.append)
    assert seen == [
        IndexPlan(listed=("2", "last"), reads=("2", "last")),
        SitemapRead(1, 2, "2", "sitemap2.xml", tabs=TabCounts(urls=2, indexed=2), new_tab_ids=(2001, 2002)),
        SitemapRead(2, 2, "last", "sitemap_last.xml.gz", tabs=TabCounts(urls=2, indexed=2), new_tab_ids=(3001,)),
    ]


def test_a_304_for_a_sitemap_this_database_never_indexed_is_parsed(tmp_path):
    """A fresh database next to a warm HTTP cache (the state was deleted, the cache kept)."""
    from caracole import db

    ug = site()
    first = db.connect(tmp_path / "a.sqlite")
    build_index(first, ug.client(tmp_path / "cache"), NOW)
    fresh = db.connect(tmp_path / "b.sqlite")
    ug.requests.clear()
    stats = build_index(fresh, ug.client(tmp_path / "cache"), LATER)
    assert all(etag for _, etag in ug.requests)  # every sitemap answered 304...
    assert index_count(fresh) == 7  # ...and was indexed from the cached copy
    assert stats.sitemaps_fetched == 3 and stats.sitemaps_unchanged == 0


def test_a_cached_body_newer_than_the_indexed_one_is_parsed(conn, tmp_path):
    """The HTTP cache moved on (a run died after the download, before indexing): a 304 isn't 'unchanged'."""
    ug = site()
    build_index(conn, ug.client(tmp_path / "cache"), NOW)
    ug.files["sitemap_last.xml"] = urlset("radiohead/creep-chords-2002", "radiohead/high-and-dry-chords-3003")
    ug.client(tmp_path / "cache").get(WWW + "sitemap_last.xml", cache=False, conditional=True)
    stats = refresh_index(conn, ug.client(tmp_path / "cache"), LATER)
    assert stats.new_tab_ids == (3003,)


def test_index_without_tab_sitemaps_is_an_error(conn, tmp_path):
    ug = FakeUG({"sitemap.xml": sitemap_index("sitemap_news.xml", "sitemap_ukulele1.xml")})
    with pytest.raises(ProviderError, match="no tab sitemaps"):
        build_index(conn, ug.client(tmp_path / "cache"), NOW)


def test_a_sitemap_that_is_not_xml_is_an_error_not_an_empty_sitemap(conn, tmp_path):
    ug = site(**{
        "sitemap.xml": sitemap_index("sitemap1.xml", "sitemap2.xml", "sitemap3.xml", "sitemap_last.xml"),
        "sitemap2.xml": b"<html><body>Something went wrong</body></html>",
        "sitemap3.xml": urlset("eagles/hotel-california-chords-4001"),
    })
    with pytest.raises(ProviderError, match="sitemap2"):
        build_index(conn, ug.client(tmp_path / "cache"), NOW)
    # sitemap1 was indexed before the failure and stays; sitemap2 isn't recorded as indexed
    assert [r[0] for r in rows(conn)] == [1001, 1002, 1005, 1006]
    ug.files["sitemap2.xml"] = S2
    ug.requests.clear()
    stats = refresh_index(conn, ug.client(tmp_path / "cache"), LATER)
    assert ug.names() == ["sitemap.xml", "sitemap2.xml", "sitemap3.xml", "sitemap_last.xml"]
    assert stats.new_tab_ids == (2001, 2002, 4001, 3001)


def test_build_from_dir_reads_numbered_and_last_files(conn, tmp_path):
    d = tmp_path / "sitemaps"
    d.mkdir()
    (d / "sitemap1.xml.gz").write_bytes(gzip.compress(S1))
    (d / "sitemap10.xml").write_bytes(urlset("eagles/hotel-california-chords-4001"))
    (d / "sitemap2.xml.gz").write_bytes(gzip.compress(S2))
    (d / "sitemap_last.xml.gz").write_bytes(gzip.compress(LAST))
    (d / "sitemap_ukulele1.xml").write_bytes(urlset("x/y-chords-9"))
    (d / "fetch.log").write_text("not a sitemap")
    stats = build_index(conn, None, NOW, from_dir=d)
    assert [r[0] for r in rows(conn)] == [1001, 1002, 1005, 1006, 2001, 2002, 3001, 4001]
    assert stats.sitemaps_fetched == 4 and stats.new_tab_ids == (1001, 1002, 1005, 1006, 2001, 2002, 4001, 3001)
    assert dict(conn.execute("SELECT tab_id, sitemap FROM ug_index WHERE tab_id IN (2002, 4001)").fetchall()) == {
        2002: "2", 4001: "10"}
    # the files count as seen: a refresh asks only for the highest-numbered sitemap and sitemap_last
    ug = FakeUG({"sitemap.xml": sitemap_index("sitemap1.xml", "sitemap2.xml", "sitemap10.xml", "sitemap_last.xml"),
                 "sitemap10.xml": urlset("eagles/hotel-california-chords-4001"), "sitemap_last.xml": LAST})
    refresh_index(conn, ug.client(tmp_path / "cache"), LATER)
    assert ug.names() == ["sitemap.xml", "sitemap10.xml", "sitemap_last.xml"]


def test_build_from_an_empty_dir_is_an_error(conn, tmp_path):
    with pytest.raises(FileNotFoundError, match="no sitemap"):
        build_index(conn, None, NOW, from_dir=tmp_path)


def row(tab_id, artist="oasis", song="wonderwall", kind="chords"):
    return IndexRow(tab_id, artist, song, kind, f"{artist}/{song}-{kind}-{tab_id}")


def test_upsert_rows_returns_new_ids_keeps_first_seen_and_dedupes(conn):
    assert upsert_rows(conn, [row(2), row(1), row(2)], "40", NOW) == [1, 2]
    moved = IndexRow(1, "oasis", "wonderwall", "chords", "the-oasis/wonderwall-chords-1")
    assert upsert_rows(conn, [moved, row(3)], "last", LATER) == [3]
    assert rows(conn) == [
        (1, "oasis", "wonderwall", "chords", "40", "2026-10-18T03:30:00Z", "the-oasis/wonderwall-chords-1"),
        (2, "oasis", "wonderwall", "chords", "40", "2026-10-18T03:30:00Z", "oasis/wonderwall-chords-2"),
        (3, "oasis", "wonderwall", "chords", "last", "2026-10-19T03:30:00Z", "oasis/wonderwall-chords-3"),
    ]


def test_upsert_rows_handles_a_full_sitemap_quickly(conn):
    batch = [row(i, f"artist-{i % 3000}", f"song-{i}") for i in range(1, 50_001)]
    started = time.perf_counter()
    assert len(upsert_rows(conn, batch, "40", NOW)) == 50_000
    assert upsert_rows(conn, batch, "last", NOW) == []
    assert time.perf_counter() - started < 10  # about 1 s; a per-row round trip would take minutes
    assert index_count(conn) == 50_000


def accepted(conn, artist, title, akey, skey, decision="accept"):
    s = add_song(conn, artist, title)
    update_song(conn, s.id, match_decision=decision, match_artist_key=akey, match_song_key=skey, ug_dirty=False)
    return s.id


def test_mark_dirty_for_new_covers_variant_slugs_of_accepted_and_pinned_songs(conn):
    upsert_rows(conn, [row(1), row(2, "radiohead", "creep"), row(3, "eagles", "hotel-california")], "1", NOW)
    wonderwall = accepted(conn, "Oasis", "Wonderwall", "oasis", "wonderwall")
    creep = accepted(conn, "Radiohead", "Creep", "radiohead", "creep", decision="pinned")
    hotel = accepted(conn, "Eagles", "Hotel California", "eagles", "hotel-california", decision="review")
    other = accepted(conn, "Oasis", "Wonderwall II", "oasis", "wonderwall-ii")
    new = upsert_rows(conn, [row(10, "oasis", "wonderwall-acoustic"), row(11, "radiohead", "creep-intro", "tabs"),
                             row(12, "eagles", "hotel-california"), row(13, "oasis", "wonderwall-iii")], "last", NOW)
    assert mark_dirty_for_new(conn, new) == {wonderwall, creep}
    assert [get_song(conn, i).ug_dirty for i in (wonderwall, creep, hotel, other)] == [True, True, False, False]
    assert mark_dirty_for_new(conn, []) == set()


def test_index_stats(conn):
    assert index_count(conn) == 0
    assert index_stats(conn)["rows"] == 0
    upsert_rows(conn, [row(1), row(2, kind="tabs"), row(3, "radiohead", "creep")], "1", NOW)
    stats = index_stats(conn)
    assert stats["rows"] == 3 and stats["artists"] == 2
    assert stats["types"] == {"chords": 2, "tabs": 1}


def test_index_stats_report_builds_and_refreshes(conn, tmp_path):
    ug = site()
    build_index(conn, ug.client(tmp_path / "cache"), NOW)
    refresh_index(conn, ug.client(tmp_path / "cache"), LATER)
    stats = index_stats(conn)
    assert stats["built_at"] == "2026-10-18T03:30:00Z"
    assert stats["refreshed_at"] == "2026-10-19T03:30:00Z"
    assert stats["sitemaps"] == 3


# --- a build stopped part-way ----------------------------------------------------------------


class BlockingUG(FakeUG):
    """UG answering 403 for the sitemaps in ``blocked``."""

    def __init__(self, files, blocked):
        super().__init__(files)
        self.blocked = set(blocked)

    def handler(self, request):
        if request.url.path.lstrip("/") in self.blocked:
            self.requests.append((request.url.path.lstrip("/"), None))
            return httpx.Response(403, content=b"blocked")
        return super().handler(request)


def test_a_build_stopped_by_a_block_leaves_the_index_partial(conn, tmp_path):
    from caracole.http import ProviderBlocked
    from caracole.ug.index import index_state

    assert index_state(conn) == "empty"
    ug = BlockingUG(site().files, blocked={"sitemap2.xml"})
    with pytest.raises(ProviderBlocked):
        build_index(conn, ug.client(tmp_path / "cache"), NOW)
    assert index_count(conn) == 4  # sitemap1 was stored before the block
    assert index_state(conn) == "partial"
    assert index_stats(conn)["built_at"] is None


def test_a_refresh_that_reads_what_a_stopped_build_left_completes_the_index(conn, tmp_path):
    from caracole.ug.index import index_state

    blocked = BlockingUG(site().files, blocked={"sitemap2.xml"})
    with pytest.raises(ProviderError):
        build_index(conn, blocked.client(tmp_path / "cache"), NOW)
    # The refresh reads every numbered sitemap never indexed, so sitemap2 too.
    stats = refresh_index(conn, site().client(tmp_path / "cache"), LATER)
    assert index_state(conn) == "complete" and stats.completed
    assert index_stats(conn)["built_at"] == "2026-10-19T03:30:00Z"


def test_a_refresh_cut_short_leaves_the_index_partial(conn, tmp_path):
    from caracole.http import BudgetExhausted
    from caracole.ug.index import index_state

    blocked = BlockingUG(site().files, blocked={"sitemap2.xml"})
    with pytest.raises(ProviderError):
        build_index(conn, blocked.client(tmp_path / "cache"), NOW)
    with pytest.raises(BudgetExhausted):
        refresh_index(conn, site().client(tmp_path / "cache", budget=1), LATER)  # the sitemap index only
    assert index_state(conn) == "partial"


def test_a_build_that_finishes_is_complete(conn, tmp_path):
    from caracole.ug.index import index_state

    build_index(conn, site().client(tmp_path / "cache"), NOW)
    assert index_state(conn) == "complete"


# --- tabs robots.txt closes ------------------------------------------------------------------

# robots.txt on the tabs host closes /tab/track/ and every path that starts with /tab/download, so
# caracole may never read these pages; the live sitemaps list four such tabs, these three among them.
SE_QUE_ES_TARDE = "track/se-que-es-tarde-chords-1126580"
AVE_FENIX = "track/ave-fenix-guitar-pro-1149792"
SHINE = "download-kids-worship/shine-your-light-chords-4818770"


def test_tabs_robots_txt_closes_are_left_out_of_the_index(conn, tmp_path):
    # No song may match a tab caracole may never read. "tracks/" is open; "./download…" is
    # /tab/download… once the URL drops its dot segment.
    ug = site(**{"sitemap_last.xml": urlset("radiohead/creep-chords-2002", SE_QUE_ES_TARDE, AVE_FENIX, SHINE,
                                            "tracks/tracks-chords-3004", "./download-chords-3005")})
    seen = []
    stats = build_index(conn, ug.client(tmp_path / "cache"), NOW, progress=seen.append)
    assert [r[0] for r in rows(conn)] == [1001, 1002, 1005, 1006, 2001, 2002, 3004]
    assert stats.new_tab_ids == (1001, 1002, 1005, 1006, 2001, 2002, 3004)
    # The three closed ones counted apart, and the Guitar Pro file as a type the index doesn't keep.
    assert seen[-1].tabs == TabCounts(urls=6, indexed=2, other={"guitar-pro": 1}, closed=3)


def test_a_refresh_drops_the_indexed_tabs_robots_txt_closes(conn, tmp_path):
    # Indexed before caracole checked robots.txt, in sitemaps a refresh doesn't read again.
    ug = site()
    build_index(conn, ug.client(tmp_path / "cache"), NOW)
    upsert_rows(conn, [IndexRow(1126580, "track", "se-que-es-tarde", "chords", SE_QUE_ES_TARDE),
                       IndexRow(4818770, "download-kids-worship", "shine-your-light", "chords", SHINE),
                       IndexRow(1126581, "track", "se-que-es-tarde", "chords", "the-track/se-que-es-tarde-chords-1126581"),
                       IndexRow(1126582, ".", "download", "chords", "./download-chords-1126582")], "1", NOW)
    fenix = accepted(conn, "Track", "Ave Fénix", "track", "ave-fenix")
    ug.files["sitemap_last.xml"] = urlset("radiohead/creep-chords-2002", "radiohead/creep-acoustic-tabs-3001",
                                          AVE_FENIX)

    seen = []
    stats = refresh_index(conn, ug.client(tmp_path / "cache"), LATER, progress=seen.append)

    assert [r[0] for r in rows(conn)] == [1001, 1002, 1005, 1006, 2001, 2002, 3001, 1126581]
    assert seen[0].dropped == 3  # the plan says how many indexed tabs were dropped
    assert stats.new_tab_ids == () and get_song(conn, fenix).ug_dirty is False  # a closed new tab is no news


def test_a_build_drops_the_indexed_tabs_robots_txt_closes(conn, tmp_path):
    upsert_rows(conn, [IndexRow(1126580, "track", "se-que-es-tarde", "chords", SE_QUE_ES_TARDE)], "12", NOW)
    d = tmp_path / "sitemaps"
    d.mkdir()
    (d / "sitemap_last.xml").write_bytes(urlset("radiohead/creep-chords-2002", AVE_FENIX))

    build_index(conn, None, LATER, from_dir=d)

    assert [r[0] for r in rows(conn)] == [2002]


def test_only_rows_a_rule_may_reach_are_checked_and_a_rule_that_may_reach_any_is_not_missed(monkeypatch):
    # The nightly drop reads the rows whose path starts as a rule's text does. A rule that starts
    # before /tab/ ends, such as the "/*?no_takeover" www has, may close any tab page: every row.
    from caracole.ug import index

    rules = ("/forum/", "/tab/track/", "/tab/print?", "/*?no_takeover")
    monkeypatch.setattr(index, "ROBOTS_DISALLOW", {"tabs.ultimate-guitar.com": rules})
    assert set(index._closed_starts()) == {".", "track/", "print?", ""}


# --- what the index covers, and how a refresh resumes ---------------------------------------


def test_coverage_names_what_a_stopped_build_left_and_a_refresh_reads_exactly_that(conn, tmp_path):
    from caracole.http import ProviderBlocked
    from caracole.ug.sitemap import sitemap_label

    assert index_coverage(conn).listed is None  # no sitemap index read yet
    blocked = BlockingUG(site().files, blocked={"sitemap2.xml"})
    with pytest.raises(ProviderBlocked):
        build_index(conn, blocked.client(tmp_path / "cache"), NOW)
    cov = index_coverage(conn)
    assert (cov.listed, cov.indexed, cov.left) == (("1", "2", "last"), ("1",), ("2", "last"))
    assert cov.tabs == TabCounts(urls=7, indexed=4, bare=1, other={"bass": 1, "ukulele": 1})
    ug = site()
    refresh_index(conn, ug.client(tmp_path / "cache"), LATER)
    assert ug.names()[1:] == [sitemap_label(n) for n in cov.refresh] == ["sitemap2.xml", "sitemap_last.xml"]


def test_coverage_of_a_complete_index_sums_what_its_sitemaps_held(conn, tmp_path):
    build_index(conn, site().client(tmp_path / "cache"), NOW)
    cov = index_coverage(conn)
    assert cov.left == () and cov.refresh == ("2", "last")
    assert cov.tabs == TabCounts(urls=11, indexed=8, bare=1, other={"bass": 1, "ukulele": 1})


@pytest.mark.parametrize(
    ("stats", "refetch", "line"),
    [
        (IndexStats(sitemaps_fetched=1, sitemaps_unchanged=1, rows=3, new_tab_ids=(3002,), parsed=("last",)), 1,
         "1 of 2 sitemaps changed (sitemap_last.xml): +1 tab, 1 song to refetch"),
        (IndexStats(sitemaps_fetched=1, sitemaps_unchanged=1, rows=3, parsed=("40",)), 0,
         "1 of 2 sitemaps changed (sitemap40.xml): no new tabs, no song to refetch"),
        (IndexStats(sitemaps_unchanged=2), 0, "2 sitemaps checked, none changed"),
        (IndexStats(sitemaps_fetched=29, rows=1_000_000, new_tab_ids=tuple(range(1259)),
                    parsed=(*map(str, range(13, 41)), "last"), completed=True), None,
         "29 of 29 sitemaps changed (sitemap13.xml to sitemap40.xml and sitemap_last.xml): +1,259 tabs; "
         "the index is now complete"),
    ],
)
def test_a_refresh_sums_itself_up_in_one_line(stats, refetch, line):
    assert stats.summary(refetch) == line


@pytest.mark.parametrize(
    ("names", "text"),
    [
        (("last",), "sitemap_last.xml"),
        (("40", "last"), "sitemap40.xml and sitemap_last.xml"),
        (("1", "2", "last"), "sitemap1.xml, sitemap2.xml and sitemap_last.xml"),
        ((*map(str, range(1, 41)), "last"), "sitemap1.xml to sitemap40.xml and sitemap_last.xml"),
        (("3", "7", "8", "9", "12", "20", "last"),
         "sitemap3.xml, sitemap7.xml to sitemap9.xml, sitemap12.xml and 2 more"),
    ],
)
def test_describe_sitemaps_names_runs_of_numbers_as_ranges(names, text):
    assert describe_sitemaps(names) == text
