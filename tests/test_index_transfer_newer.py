"""index_transfer.py's partial export (``export(have=)``, the phone's take, ``POST /peer/index/newer``): of each
site only the sitemaps the asker doesn't hold alike, each with all of its rows, and the rows read a row or a page at a
time since it last merged an export of this side's; merged, it ends where a whole export's merge does. With the
merge's rules it shares: a sitemap a partial export left out is never read as gone, a LaCuerda listing page re-checked
and found unchanged moves its record alone, and a merge that moves records alone makes no backup.

Each test fills "home" (the computer, the file's source) and ``conn`` (the phone, merged into) through the indexes'
own writers, as test_index_transfer.py does.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import test_index_transfer as tt

from caracole import backup, db, gtptabs_fetch, harptabs_fetch, lacuerda_index, stamps
from caracole import index_transfer as transfer

WEEK = datetime(2026, 10, 29, 18, 0, tzinfo=UTC)  # last week's sync: the export the phone merged
NIGHT = datetime(2026, 11, 5, 3, 30, tzinfo=UTC)  # one more night's refresh on the computer
TONIGHT = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)  # this sync's export
GTP = "https://gtptabs.com/tabs/"
UG_SITEMAPS = [str(n) for n in range(1, 13)]  # twelve of UG's sitemaps, as a real index holds tens

home = tt.home  # the computer's database, test_index_transfer.py's fixture


CUT = "sync:cut:"  # the phone's kv of each site's cut of a computer, by its id (core.index.Have.CUT_KEY)


def have_document(conn: sqlite3.Connection, computer: str, sites=None) -> dict:
    """``POST /peer/index/newer``'s document as the phone builds it of its database (core.index.Have.document, held to
    this by vectors/index/have.jsonl): the sites asked, and of each the phone's record of every sitemap (listing page)
    it holds, an object, less its ``checked_at``, and ``since``, its kv ``sync:cut:<computer>``'s text of the site,
    else null."""
    try:
        cuts = json.loads(db.kv_get(conn, CUT + computer) or "{}")
    except ValueError:
        cuts = {}
    cuts = cuts if isinstance(cuts, dict) else {}
    names = list(transfer.chosen(sites))
    return {"sites": names, "have": {name: {
        "sitemaps": {n: {k: v for k, v in r.items() if k != "checked_at"}
                     for n, r in transfer._records(conn, "main", transfer.SITEMAPPED[name].key).items()
                     if isinstance(r, dict)},
        "since": cuts.get(name) if isinstance(cuts.get(name), str) else None} for name in names}}


def have_of(conn: sqlite3.Connection, sites=None, since: str | None = None) -> dict[str, transfer.Have]:
    """What the phone holds of each site, as its sync asks with it (``have_document``, read as the route reads it),
    with ``since`` in place of its cuts."""
    _, have = transfer.read_have(have_document(conn, "", sites))
    return {name: transfer.Have(h.sitemaps, since) for name, h in have.items()}


def computer(conn: sqlite3.Connection) -> None:
    """A computer's indexes of realistic shape: many sitemaps, the pages read a page at a time, every site."""
    for n in UG_SITEMAPS:
        tt.ug_sitemap(conn, n, [f"artist-{n}/song-{i}-chords-{int(n) * 100 + i}" for i in range(5)], tt.EARLY)
    tt.ug_listed(conn, UG_SITEMAPS, tt.EARLY)
    tt.artist_tab(conn, "https://www.ultimate-guitar.com/artist/634073", 2001, "斑马 斑马", tt.EARLY)
    tt.artist_tab(conn, "https://www.ultimate-guitar.com/artist/12", 4001, "春天里", tt.EARLY)
    tt.directory_page(conn, "s", 1, 1, [(634073, "Song Dongye (宋冬野)", "", 42),
                                        (274, "Simon & Garfunkel", "simon_garfunkel", 673)], tt.EARLY)
    tt.directory_page(conn, "t", 1, 1, [(90, "Toto", "toto", 300)], tt.EARLY)
    tt.listing(conn, "tabs/e/index0.html", [("estopa", "Estopa"), ("enanitos_verdes", "Enanitos Verdes")], tt.EARLY)
    tt.listing(conn, "tabs/s/index0.html", [("soda_stereo", "Soda Stereo")], tt.EARLY)
    db.kv_set(conn, lacuerda_index.COMPLETE_KEY, tt.db_stamp(tt.EARLY))
    tt.artist_songs(conn, "estopa", "Estopa", ["Como Camarón", "Vino Tinto"])
    for n in range(1, 7):
        tt.sitemap(conn, gtptabs_fetch.SITE, f"sitemap-tabs-{n}.xml",
                   [f"{GTP}{n}/band-{n}.html", f"{GTP}{n}/band-{n}/song-{n}.html"], tt.EARLY)
    db.kv_set(conn, gtptabs_fetch.SITE.complete_key, tt.db_stamp(tt.EARLY))
    tt.sitemap(conn, harptabs_fetch.SITE, "sitemap.xml", ["https://www.harptabs.com/artist/1178/billy-joel",
                                                          "https://www.harptabs.com/tab/25/piano-man"], tt.EARLY)
    db.kv_set(conn, harptabs_fetch.KEYS_KEY, harptabs_fetch.ROW_KEYS)
    tt.harp_page(conn, "artist/1178/billy-joel", ["Piano Man", "Honesty"], tt.EARLY)
    tt.harp_page(conn, "artist/50/the-beatles", ["Yesterday"], tt.EARLY)
    tt.game_page(conn, "tabs/actraiser", ["Fillmore", "Bloodpool"], tt.EARLY)
    tt.game_page(conn, "tabs/hollow-knight", ["Greenpath"], tt.EARLY)


def night(conn: sqlite3.Connection) -> None:
    """One more night on the computer: three sitemaps read again (two of UG's, one of gtptabs.com's), one re-checked
    and found unchanged (a 304), a LaCuerda listing page re-checked alike, and a page or two read a page at a time."""
    for n in ("11", "12"):
        tt.ug_sitemap(conn, n, [f"artist-{n}/song-{i}-chords-{int(n) * 100 + i}" for i in range(6)], NIGHT)
    tt.ug_listed(conn, UG_SITEMAPS, NIGHT)
    tt.sitemap(conn, gtptabs_fetch.SITE, "sitemap-tabs-6.xml",
               [f"{GTP}6/band-6.html", f"{GTP}6/band-6/song-6.html", f"{GTP}6/band-6/encore.html"], NIGHT)
    tt.rechecked(conn, gtptabs_fetch.SITE, "sitemap-tabs-1.xml", NIGHT)
    lacuerda = lacuerda_index.pages(conn)
    lacuerda_index._record(conn, "tabs/e/index0.html", {**lacuerda["tabs/e/index0.html"],
                                                         "checked_at": tt.db_stamp(NIGHT)})
    db.kv_set(conn, gtptabs_fetch.SITE.complete_key, tt.db_stamp(NIGHT))
    tt.artist_tab(conn, "https://www.ultimate-guitar.com/artist/634073", 2002, "安和桥", NIGHT)
    tt.directory_page(conn, "t", 1, 1, [(90, "Toto", "toto", 301)], NIGHT)
    tt.harp_page(conn, "artist/1178/billy-joel", ["Piano Man", "Honesty", "Vienna"], NIGHT)


def tables() -> list[str]:
    return [t for site in transfer.SITES.values() for t in site.tables]


def keys() -> list[str]:
    return [k for site in transfer.SITES.values() for k in site.kv]


def state(conn: sqlite3.Connection) -> dict[str, object]:
    """Every index table's rows and every progress record, to compare two databases by."""
    return {**{t: tt.rows(conn, t) for t in tables()}, **{k: tt.kv(conn, k) for k in keys()}}


def exported(path: Path) -> dict[str, list[tuple]]:
    with sqlite3.connect(path) as file:
        return {t: tt.rows(file, t) for t in tables()}


def meta(path: Path) -> dict[str, str]:
    with sqlite3.connect(path) as file:
        return dict(file.execute(f"SELECT key, value FROM {transfer.META}"))


@pytest.fixture
def week(tmp_path):
    """The computer as last week's export left it, the phone that merged that export, and the computer after one
    more night."""
    home = tt.database(tmp_path, "home")
    phone = tt.database(tmp_path, "phone")
    computer(home)
    last = tmp_path / "week.sqlite"
    transfer.export(home, last, now=WEEK)
    transfer.merge(phone, last, state_dir=tmp_path / "phone-state", now=WEEK)
    night(home)
    yield home, phone, meta(last)["exported_at"]
    home.close()
    phone.close()


def test_a_partial_export_holds_only_the_sitemaps_that_differ(week, tmp_path):
    home, phone, since = week
    path = tmp_path / "newer.sqlite"

    done = transfer.export(home, path, now=TONIGHT, have=have_of(phone, since=since))

    rows = exported(path)
    assert {r[4] for r in rows["ug_index"]} == {"11", "12"}  # UG's re-read sitemaps' rows, every one of them
    assert len(rows["ug_index"]) == 12
    assert {r[5] for r in rows["gtptabs_index"]} == {"sitemap-tabs-6.xml"}  # not the one found unchanged
    assert rows["musescore_index"] == [] and rows["harptabs_index"] == [] and rows["gametabs_index"] == []
    listing = [r for r in rows["lacuerda_index"] if r[10].startswith("tabs/")]
    assert listing == []  # the re-checked listing page's rows: the phone holds them alike
    assert {r[10] for r in rows["lacuerda_index"]} == {"estopa/"}  # its artist pages hold no time: sent whole
    assert [(r[0], r[1]) for r in rows["ug_artist_tabs"]] == [("https://www.ultimate-guitar.com/artist/634073", 2002)]
    assert [r[0] for r in rows["ug_directory"]] == [90]
    assert {r[0] for r in rows["harptabs_artists"]} == {"artist/1178/billy-joel"}
    assert {r[0] for r in rows["harptabs_artist_tabs"]} == {"artist/1178/billy-joel"}  # its tabs, all of them
    assert len(rows["harptabs_artist_tabs"]) == 3
    assert rows["gametabs_games"] == [] and rows["gametabs_game_tabs"] == []
    said = meta(path)
    assert json.loads(said["sites"]) == list(transfer.SITES) and said["exported_at"] == stamps.stamp(TONIGHT)
    cut = json.loads(said[transfer.PARTIAL])
    assert cut["ug"] == {"since": since, "from": stamps.stamp(stamps.parse(since) - transfer.SINCE_MARGIN),
                         "same": sorted(UG_SITEMAPS[:10])}
    assert cut["gtptabs"]["same"] == [f"sitemap-tabs-{n}.xml" for n in range(1, 6)]
    assert cut["gtptabs"]["from"] is None and cut["lacuerda"]["same"] == ["tabs/e/index0.html", "tabs/s/index0.html"]
    with sqlite3.connect(path) as file:  # every progress record whole, as a whole export holds them
        assert dict(file.execute("SELECT key, value FROM kv")) == {k: tt.kv(home, k) for k in keys()
                                                                   if tt.kv(home, k) is not None}
    whole = transfer.export(home, tmp_path / "whole.sqlite", now=TONIGHT)
    print(f"partial: {sum(done.rows.values())} rows, {done.size} bytes; "
          f"whole: {sum(whole.rows.values())} rows, {whole.size} bytes")
    assert sum(done.rows.values()) < sum(whole.rows.values()) / 3


def test_merging_a_partial_export_ends_where_a_whole_one_does(week, tmp_path):
    home, phone, since = week
    newer = tmp_path / "newer.sqlite"
    transfer.export(home, newer, now=TONIGHT, have=have_of(phone, since=since))
    whole = tmp_path / "whole.sqlite"
    transfer.export(home, whole, now=TONIGHT)
    (tmp_path / "other").mkdir()
    phone.execute("VACUUM INTO ?", (str(tmp_path / "other" / "caracole.sqlite"),))  # a copy of last week's phone
    other = db.connect(tmp_path / "other" / "caracole.sqlite")
    try:
        by_part = transfer.merge(phone, newer, state_dir=tmp_path / "phone-state", now=TONIGHT)
        by_whole = transfer.merge(other, whole, state_dir=tmp_path / "other-state", now=TONIGHT)

        assert state(phone) == state(other)  # row for row, record for record
        assert {t: tt.rows(phone, t) for t in tables()} == {t: tt.rows(home, t) for t in tables()}
        part = {s.site: (s.taken, s.checked) for s in by_part.sites}
        assert part["ug"][0][0] == ("sitemap", 2) and part["ug"][1] == 12  # the rows of the sitemaps in the file
        assert part["gtptabs"] == ([("sitemap", 1)], 3)
        assert [(s.site, s.taken, s.records) for s in by_part.sites] == \
            [(s.site, s.taken, s.records) for s in by_whole.sites]
    finally:
        other.close()


def test_with_no_since_every_row_read_a_page_at_a_time_is_sent_and_with_one_only_those_read_since(week, tmp_path):
    home, phone, since = week
    first = tmp_path / "first.sqlite"
    transfer.export(home, first, now=TONIGHT, have=have_of(phone))
    assert len(exported(first)["ug_artist_tabs"]) == 3 and len(exported(first)["ug_directory"]) == 3
    assert len(exported(first)["gametabs_games"]) == 2  # a stamp from no export of this side's: every row
    assert json.loads(meta(first)[transfer.PARTIAL])["ug"]["from"] is None

    # A read a little before the stamp (stamped before that export's snapshot, stored after it) is sent too.
    just = stamps.parse(since) - timedelta(minutes=30)
    tt.game_page(home, "tabs/celeste", ["Resurrections"], just)
    later = tmp_path / "later.sqlite"
    transfer.export(home, later, now=TONIGHT, have=have_of(phone, since=since))
    assert [r[0] for r in exported(later)["gametabs_games"]] == ["tabs/celeste"]
    assert [r[0] for r in exported(later)["gametabs_game_tabs"]] == ["tabs/celeste"]


def test_rows_a_merge_took_here_since_the_askers_last_take_are_sent_whatever_their_times(week, tmp_path):
    home, phone, since = week
    # Another caracole's pages (the phone's own push, a file), read long before: merged into the computer after the
    # phone's last take, so a bound by the stamp alone would leave them out for good.
    elsewhere = tt.database(tmp_path, "elsewhere")
    tt.game_page(elsewhere, "tabs/ys", ["Feena"], tt.EARLY - timedelta(days=30))
    pages = tmp_path / "pages.sqlite"
    transfer.export(elsewhere, pages, now=tt.NOW, pages={"gametabs": ["tabs/ys"]})
    elsewhere.close()
    transfer.merge(home, pages, state_dir=tmp_path / "home-state", now=TONIGHT)
    [[_, low]] = json.loads(tt.kv(home, transfer.ARRIVED_KEY))["gametabs"]
    assert low == tt.db_stamp(tt.EARLY - timedelta(days=30))

    path = tmp_path / "newer.sqlite"
    transfer.export(home, path, now=TONIGHT, have=have_of(phone, since=since))

    assert {r[0] for r in exported(path)["gametabs_games"]} == {"tabs/ys", "tabs/actraiser", "tabs/hollow-knight"}
    assert json.loads(meta(path)[transfer.PARTIAL])["gametabs"]["from"] == low
    # An arrival before the stamp (less its margin) bounds nothing: the asker took what it brought then.
    db.kv_set_json(home, transfer.ARRIVED_KEY, {"gametabs": [[tt.db_stamp(tt.EARLY), ""]]})
    again = tmp_path / "again.sqlite"
    transfer.export(home, again, now=TONIGHT, have=have_of(phone, since=since))
    assert exported(again)["gametabs_games"] == []  # nothing read since: the phone took the rest last week


def test_a_merge_notes_its_arrivals_a_bounded_list_and_a_second_merge_notes_none(home, conn, tmp_path):
    for n in range(transfer.ARRIVALS_KEPT + 3):
        source = tt.database(tmp_path, f"source-{n}")
        tt.game_page(source, "tabs/ys", ["Feena"], tt.EARLY + timedelta(days=n))
        path = tmp_path / f"pages-{n}.sqlite"
        transfer.export(source, path, now=tt.NOW, pages={"gametabs": ["tabs/ys"]})
        source.close()
        transfer.merge(conn, path, state_dir=tmp_path / "state", now=tt.NOW)
    arrived = json.loads(tt.kv(conn, transfer.ARRIVED_KEY))["gametabs"]
    assert len(arrived) == transfer.ARRIVALS_KEPT
    assert arrived[0][1] == tt.db_stamp(tt.EARLY)  # the oldest made one keep the earliest low
    assert not transfer.merge(conn, path, state_dir=tmp_path / "state", now=tt.NOW).changed
    assert len(json.loads(tt.kv(conn, transfer.ARRIVED_KEY))["gametabs"]) == transfer.ARRIVALS_KEPT
    no_arrival = tt.database(tmp_path, "no-arrival")
    try:  # the phone's merge (and the corpus's) notes none
        transfer.merge(no_arrival, path, state_dir=tmp_path / "state2", now=tt.NOW, arrivals=False)
        assert tt.kv(no_arrival, transfer.ARRIVED_KEY) is None
    finally:
        no_arrival.close()


def test_a_sitemap_a_partial_export_left_out_is_never_read_as_gone(week, tmp_path):
    home, phone, since = week
    path = tmp_path / "newer.sqlite"
    transfer.export(home, path, now=TONIGHT, have=have_of(phone, since=since))
    # A file that says it left out gtptabs.com's re-read sitemap and UG's sitemap 12, which the phone holds otherwise.
    with sqlite3.connect(path) as file:
        cut = json.loads(file.execute(f"SELECT value FROM {transfer.META} WHERE key = 'partial'").fetchone()[0])
        cut["gtptabs"]["same"].append("sitemap-tabs-6.xml")
        cut["ug"]["same"].append("12")
        file.execute(f"UPDATE {transfer.META} SET value = ? WHERE key = 'partial'", (json.dumps(cut),))
        file.execute("DELETE FROM gtptabs_index WHERE sitemap = 'sitemap-tabs-6.xml'")
        file.execute("DELETE FROM ug_index WHERE sitemap = '12'")
    gtp_before = tt.rows(phone, "gtptabs_index")
    record_before = json.loads(tt.kv(phone, gtptabs_fetch.SITE.sitemaps_key))["sitemap-tabs-6.xml"]
    ug_before = json.loads(tt.kv(phone, "ug:sitemaps"))["12"]

    merged = transfer.merge(phone, path, state_dir=tmp_path / "phone-state", now=TONIGHT)

    assert tt.rows(phone, "gtptabs_index") == gtp_before  # no row of it removed
    assert json.loads(tt.kv(phone, gtptabs_fetch.SITE.sitemaps_key))["sitemap-tabs-6.xml"] == record_before
    assert json.loads(tt.kv(phone, "ug:sitemaps"))["12"] == ug_before  # nor its record taken
    assert json.loads(tt.kv(phone, "ug:sitemaps"))["11"] == json.loads(tt.kv(home, "ug:sitemaps"))["11"]
    assert dict(merged.sites[0].taken)["sitemap"] == 1


@pytest.mark.parametrize("partial", ["[]", '{"ug": []}', '{"ug": {"same": "12"}}', '{"ug": {"same": [12]}}', "x"])
def test_a_partial_export_that_cant_say_what_it_left_out_is_refused_and_nothing_changes(week, tmp_path, partial):
    home, phone, since = week
    path = tmp_path / "newer.sqlite"
    transfer.export(home, path, now=TONIGHT, have=have_of(phone, since=since))
    with sqlite3.connect(path) as file:
        file.execute(f"UPDATE {transfer.META} SET value = ? WHERE key = 'partial'", (partial,))
    before = state(phone)
    with pytest.raises(transfer.TransferError, match="which part"):
        transfer.merge(phone, path, state_dir=tmp_path / "phone-state", now=TONIGHT)
    assert state(phone) == before


def test_a_lacuerda_listing_page_rechecked_and_found_unchanged_moves_its_record_alone(home, conn, tmp_path):
    tt.listing(home, "tabs/e/index0.html", [("estopa", "Estopa"), ("enanitos_verdes", "Enanitos Verdes")], tt.EARLY)
    transfer.merge(conn, tt.export(home, tmp_path, ["lacuerda"], name="first.sqlite"), state_dir=tmp_path / "state",
                   now=tt.NOW)
    before = tt.rows(conn, "lacuerda_index")
    entry = lacuerda_index.pages(home)["tabs/e/index0.html"]
    lacuerda_index._record(home, "tabs/e/index0.html", {**entry, "checked_at": tt.db_stamp(tt.LATE)})
    path = tt.export(home, tmp_path, ["lacuerda"], name="week.sqlite")
    changes = conn.total_changes

    merged = transfer.merge(conn, path, state_dir=tmp_path / "state", now=tt.NOW)

    assert conn.total_changes - changes == 1  # its record alone: no row deleted or inserted
    assert tt.rows(conn, "lacuerda_index") == before
    assert lacuerda_index.pages(conn) == lacuerda_index.pages(home)
    [done] = merged.sites
    assert (done.taken, done.checked, done.records) == ([], 0, ["listing pages found unchanged"])
    assert not transfer.merge(conn, path, state_dir=tmp_path / "state", now=tt.NOW).changed
    # One whose content differs (its artists' count) is taken as before.
    lacuerda_index._record(home, "tabs/e/index0.html", {**entry, "checked_at": tt.db_stamp(tt.NOW), "rows": 3})
    merged = transfer.merge(conn, tt.export(home, tmp_path, ["lacuerda"], name="next.sqlite"),
                            state_dir=tmp_path / "state", now=tt.NOW)
    assert merged.sites[0].taken == [("listing page", 1)]


def test_a_merge_that_moves_records_alone_makes_no_backup_and_a_second_writes_nothing(home, conn, tmp_path):
    site = gtptabs_fetch.SITE
    tt.sitemap(home, site, "sitemap-tabs-1.xml", [f"{GTP}2/blur.html"], tt.EARLY)
    transfer.merge(conn, tt.export(home, tmp_path, ["gtptabs"], name="first.sqlite"), state_dir=tmp_path / "state",
                   now=tt.NOW)
    assert len(backup.backups(tmp_path / "state")) == 1
    tt.rechecked(home, site, "sitemap-tabs-1.xml", tt.LATE)
    path = tt.export(home, tmp_path, ["gtptabs"], name="week.sqlite")
    told = []

    merged = transfer.merge(conn, path, state_dir=tmp_path / "state", now=tt.NOW, backing_up=lambda: told.append(1))

    assert merged.changed and merged.backup is None and told == []
    assert len(backup.backups(tmp_path / "state")) == 1  # none made for a record
    changes = conn.total_changes
    assert not transfer.merge(conn, path, state_dir=tmp_path / "state", now=tt.NOW).changed
    assert conn.total_changes == changes


@pytest.mark.parametrize(("doc", "said"), [
    ([], "no object"),
    ({}, "names no site"),
    ({"sites": []}, "names no site"),
    ({"sites": ["spotify"]}, "no site 'spotify'"),
    ({"sites": ["ug"], "have": {"gtptabs": {}}}, "a site not asked"),
    ({"sites": ["ug"], "have": []}, "no object"),
    ({"sites": ["ug"], "have": {"ug": {"sitemaps": []}}}, "no object"),
    ({"sites": ["ug"], "have": {"ug": {"sitemaps": {"1": {"etag": {"a": {"b": {"c": [1]}}}}}}}}, "of plain values"),
    ({"sites": ["ug"], "have": {"ug": {"sitemaps": {"1": "x"}}}}, "no object of plain values"),
    ({"sites": ["ug"], "have": {"ug": {"since": "yesterday"}}}, "no time"),
    ({"sites": ["ug"], "have": {"ug": {"since": 5}}}, "no time"),
    ({"sites": ["ug"], "have": {"ug": {"sitemaps": {str(n): {} for n in range(transfer.HAVE_SITEMAPS + 1)}}}},
     "more than"),
])
def test_what_the_asker_says_it_holds_is_read_as_data_and_anything_else_refused_in_words(doc, said):
    with pytest.raises(transfer.TransferError, match=said):
        transfer.read_have(doc)


def test_what_the_asker_holds_is_read_by_site_in_caracoles_order():
    sites, have = transfer.read_have({"sites": ["gtptabs", "ug"], "have": {"ug": {
        "sitemaps": {"1": {"etag": '"a"', "rows": 5, "pages": ["x"], "tabs": {"other": {"pro": 2}}}},
        "since": "2026-11-05T12:00:00Z"}}})
    assert sites == ("ug", "gtptabs")
    assert have == {"ug": transfer.Have({"1": {"etag": '"a"', "rows": 5, "pages": ["x"], "tabs": {"other": {"pro": 2}}}},
                                        "2026-11-05T12:00:00Z")}


def test_a_since_later_than_this_sides_clock_sends_every_row_once(week, tmp_path):
    home, phone, since = week
    path = tmp_path / "ahead.sqlite"
    ahead = stamps.stamp(TONIGHT + timedelta(days=3))  # this side's clock stepped back, or a cut of another clock's

    transfer.export(home, path, now=TONIGHT, have=have_of(phone, since=ahead))

    assert len(exported(path)["ug_artist_tabs"]) == 3 and len(exported(path)["ug_directory"]) == 3
    cut = json.loads(meta(path)[transfer.PARTIAL])["ug"]
    assert cut["since"] == ahead and cut["from"] is None  # the cut asked said back, every row sent


def test_no_body_the_route_takes_names_more_sitemaps_than_read_have_allows():
    from caracole.web import peer_routes

    # The smallest sitemap a have can name, '"":{},', is 6 bytes: a body within the route's limit stays within
    # read_have's count, so the one size refusal is the route's 413, after which the phone asks for the whole.
    assert transfer.HAVE_SITEMAPS * 6 >= peer_routes.HAVE_MAX


def test_a_since_before_the_first_day_less_its_margin_sends_every_row_never_an_error(week, tmp_path):
    home, phone, _ = week
    path = tmp_path / "first-day.sqlite"
    transfer.export(home, path, now=TONIGHT, have=have_of(phone, since="0001-01-01T00:00:00Z"))
    assert len(exported(path)["ug_artist_tabs"]) == 3 and json.loads(meta(path)[transfer.PARTIAL])["ug"]["from"] is None


def test_an_arrival_is_stamped_with_the_merges_own_clock(home, conn, tmp_path):
    tt.game_page(home, "tabs/ys", ["Feena"], tt.EARLY)
    pages = tmp_path / "pages.sqlite"
    transfer.export(home, pages, now=tt.NOW, pages={"gametabs": ["tabs/ys"]})
    transfer.merge(conn, pages, state_dir=tmp_path / "state", now=TONIGHT)
    [[at, _]] = json.loads(tt.kv(conn, transfer.ARRIVED_KEY))["gametabs"]
    assert at == stamps.stamp(TONIGHT)
