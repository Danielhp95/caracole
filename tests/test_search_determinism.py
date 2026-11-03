"""search.py, lacuerda_index.py and ug/key_search.py give one answer whatever the hash seed and whatever the rowids.

The phone runs the same queries on the same SQLite (the conformance corpus, tests/test_conformance_search.py, holds
Python's answers): an answer that hangs on the order a set iterates in (``PYTHONHASHSEED``), or on the order rows
went into a table (a scan without ``ORDER BY``, a tie a sort leaves as it found it, a ``LIMIT`` that cuts rows of no
order), is no answer the phone can agree with. Each test below puts the same rows in two orders, or runs the same
search under several hash seeds, and asks for one answer; each fails without the fix it names.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from caracole import db, search
from helpers.corpus import plain

from conftest import migrated_database, subprocess_pythonpath

SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parent
NOW = datetime(2026, 10, 27, tzinfo=UTC)


def fresh(tmp_path: Path, name: str):
    path = tmp_path / name / "caracole.sqlite"
    path.parent.mkdir(parents=True)
    path.write_bytes(migrated_database())
    return db.connect(path)


def both_orders(tmp_path: Path, fill, rows):
    """Two databases, ``rows`` put into each by ``fill``: as listed, and the other way round."""
    first, second = fresh(tmp_path, "first"), fresh(tmp_path, "second")
    fill(first, list(rows))
    fill(second, list(reversed(rows)))
    return first, second


def ug_rows(conn, rows):
    conn.executemany("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
                     "VALUES (?, ?, ?, ?, '1', 'x', ?)", [(t, a, s, k, f"{a}/{s}-{k}-{t}") for t, a, s, k in rows])


def gtptabs_rows(conn, urls):
    from caracole.gtptabs import parse_page_url

    conn.executemany("INSERT INTO gtptabs_index (path, artist_path, artist_key, title_key, base_key, sitemap) "
                     "VALUES (?, ?, ?, ?, ?, '1')", [tuple(parse_page_url(u)) for u in urls])


def harptabs_rows(conn, paths):
    from caracole.harptabs import parse_page_url

    conn.executemany("INSERT INTO harptabs_index (path, kind, page_id, key, sitemap) VALUES (?, ?, ?, ?, 'sitemap')",
                     [tuple(parse_page_url(f"https://www.harptabs.com/{p}")) for p in paths])


def gametabs_rows(conn, urls):
    from caracole.gametabs import parse_page_url

    conn.executemany("INSERT INTO gametabs_index (path, kind, game, slug, page, key, slug_key, sitemap) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, 'sitemap_1.xml')", [tuple(parse_page_url(u)) for u in urls])


# --- ug/key_search.py ------------------------------------------------------------------------------------------------


def test_the_prefilter_gives_its_rows_in_the_keys_order_whatever_order_they_went_in(tmp_path):
    # An artist key that holds the word, and a song key that does under an artist that doesn't: its two halves.
    from caracole.ug.key_search import rows_like

    rows = [(1, "zz-love", "a-song", "chords"), (2, "aa", "love", "chords"), (3, "mm", "lovely", "tabs"),
            (4, "zz-love", "b-song", "chords")]
    first, second = both_orders(tmp_path, ug_rows, rows)
    found = rows_like(first, ["%love%"])
    assert found == sorted(found)
    assert found == rows_like(second, ["%love%"])


# --- search.py: what a LIMIT cuts ------------------------------------------------------------------------------------


def test_gtptabs_pages_past_the_rows_read_are_the_same_whichever_went_in_first(tmp_path, monkeypatch):
    monkeypatch.setattr(search, "SITE_ROWS_READ", 1)
    first, second = both_orders(tmp_path, gtptabs_rows, ["https://gtptabs.com/tabs/18/radiohead/creep.html",
                                                         "https://gtptabs.com/tabs/20/stone-temple-pilots/creep.html"])
    assert plain(search.search_gtptabs(first, "creep")) == plain(search.search_gtptabs(second, "creep"))


def test_harptabs_artists_past_the_rows_read_are_the_same_whichever_went_in_first(tmp_path, monkeypatch):
    monkeypatch.setattr(search, "SITE_ROWS_READ", 1)
    # One key, two pages: the key's index gives them in the order they went in.
    first, second = both_orders(tmp_path, harptabs_rows, ["artist/1178/billy-joel", "artist/77/billy-joel"])
    assert plain(search.search_harptabs(first, "billy joel")) == plain(search.search_harptabs(second, "billy joel"))


def test_gametabs_tabs_past_the_rows_read_are_the_same_whichever_went_in_first(tmp_path, monkeypatch):
    monkeypatch.setattr(search, "SITE_ROWS_READ", 1)
    first, second = both_orders(tmp_path, gametabs_rows, ["https://gametabs.net/tabs/zelda/main-theme",
                                                          "https://gametabs.net/tabs/mario/main-theme"])
    assert plain(search.search_gametabs(first, "main theme")) == plain(search.search_gametabs(second, "main theme"))


def test_gametabs_tabs_a_composer_finds_past_the_rows_read_are_the_same_whichever_went_in_first(tmp_path,
                                                                                               monkeypatch):
    monkeypatch.setattr(search, "SITE_ROWS_READ", 1)
    urls = ["https://gametabs.net/tabs/zelda/overworld", "https://gametabs.net/tabs/mario/overworld"]

    def fill(conn, tabs):
        gametabs_rows(conn, urls)
        conn.executemany(
            "INSERT INTO gametabs_game_tabs (page, path, game, title, title_key, composers, views, place) "
            "VALUES (?, ?, ?, 'Overworld', 'overworld', '[\"Koji Kondo\"]', 5, 0)", tabs)

    first, second = both_orders(tmp_path, fill, [("tabs/zelda", "tabs/zelda/overworld", "zelda"),
                                                 ("tabs/mario", "tabs/mario/overworld", "mario")])
    assert plain(search.search_gametabs(first, "koji kondo")) == plain(search.search_gametabs(second, "koji kondo"))


def test_a_gametabs_tab_two_pages_list_is_named_alike_whichever_went_in_first(tmp_path):
    def fill(conn, tabs):
        gametabs_rows(conn, ["https://gametabs.net/tabs/zelda/overworld"])
        conn.executemany(
            "INSERT INTO gametabs_game_tabs (page, path, game, title, title_key, views, place) "
            "VALUES (?, 'tabs/zelda/overworld', 'zelda', ?, 'overworld', 5, 0)", tabs)

    first, second = both_orders(tmp_path, fill, [("tabs/zelda", "Overworld"), ("tabs/zelda?page=2", "OVERWORLD")])
    assert plain(search.search_gametabs(first, "overworld")) == plain(search.search_gametabs(second, "overworld"))


def test_harptabs_tabs_of_one_id_past_the_pages_asked_for_are_the_same_whichever_went_in_first(tmp_path):
    # One tab under two slugs, its apostrophe written either way: one key, one id, and one page asked for.
    first, second = both_orders(tmp_path, harptabs_rows, ["tab/30906/can-t-help-falling-in-love",
                                                          "tab/30906/cant-help-falling-in-love"])
    query = "can't help falling in love"
    assert plain(search.search_harptabs(first, query, songs=1)) == plain(search.search_harptabs(second, query, songs=1))


def test_a_gametabs_tab_two_pages_list_is_its_last_pages_by_their_numbers(tmp_path):
    # Page 10 comes after page 2, though "?page=10" sorts before "?page=2" as text.
    def fill(conn, tabs):
        gametabs_rows(conn, ["https://gametabs.net/tabs/zelda/overworld"])
        conn.executemany(
            "INSERT INTO gametabs_game_tabs (page, path, game, title, title_key, views, place) "
            "VALUES (?, 'tabs/zelda/overworld', 'zelda', ?, 'overworld', 5, 0)", tabs)

    for conn in both_orders(tmp_path, fill, [("tabs/zelda?page=2", "Overworld"), ("tabs/zelda?page=10", "OVERWORLD")]):
        assert [h.title for h in search.search_gametabs(conn, "overworld")] == ["OVERWORLD"]


def test_ultimate_guitars_artists_past_those_a_suggestion_reads_are_the_same_whichever_went_in_first(tmp_path,
                                                                                                      monkeypatch):
    monkeypatch.setattr(search, "CLOSE_ARTISTS", 1)
    first, second = both_orders(tmp_path, ug_rows, [(1, "metallica", "one", "tabs"),
                                                    (2, "metalica-band", "fuego", "chords")])
    assert plain(search.suggest_artists(first, "metalica")) == plain(search.suggest_artists(second, "metalica"))


# --- search.py: ties a sort leaves in the rows' order ----------------------------------------------------------------


def test_harmonica_tabs_tied_in_views_and_place_come_in_one_order(tmp_path):
    from caracole.harptabs import ArtistPage, ListedTab
    from caracole.harptabs_index import store_artist_page

    pages = [("artist/1/billy-joel", ArtistPage("billy joel", 3, (ListedTab(25, "tab/25/piano-man", "Piano Man",
                                                                           views=10),))),
             ("artist/2/ann-joel", ArtistPage("ann joel", 3, (ListedTab(26, "tab/26/piano-man", "Piano Man",
                                                                       views=10),)))]

    def fill(conn, read):
        harptabs_rows(conn, [path for path, _ in read])
        for path, page in read:
            store_artist_page(conn, path, page, NOW)

    first, second = both_orders(tmp_path, fill, pages)
    assert plain(search.search_harptabs(first, "piano man")) == plain(search.search_harptabs(second, "piano man"))


def test_lacuerdas_artists_of_one_name_are_suggested_alike_whichever_went_in_first(tmp_path):
    from caracole import lacuerda_index as li
    from caracole.lacuerda import LCArtist

    def fill(conn, artists):
        li.store_artists(conn, "tabs/b/index0.html", [LCArtist(slug, name, n) for slug, name, n in artists])

    first, second = both_orders(tmp_path, fill, [("beyonce", "Beyonce", 3), ("beyonce_2", "Beyonce", 3)])
    assert plain(search.suggest_artists(first, "beyonse")) == plain(search.suggest_artists(second, "beyonse"))


def test_harptabs_artists_of_one_name_are_suggested_alike_whichever_went_in_first(tmp_path):
    first, second = both_orders(tmp_path, harptabs_rows, ["artist/1/billy-joel", "artist/2/billy-joel"])
    assert plain(search.suggest_artists(first, "bily joel")) == plain(search.suggest_artists(second, "bily joel"))


def test_a_lacuerda_artist_whose_listing_isnt_read_is_named_alike_whichever_song_went_in_first(tmp_path):
    def fill(conn, rows):
        conn.executemany("INSERT INTO lacuerda_index (path, artist_slug, artist, artist_key, title, title_key, page) "
                         "VALUES (?, 'estopa', ?, 'estopa', ?, ?, 'busca.php')", rows)

    first, second = both_orders(tmp_path, fill, [("estopa/vino_tinto", "Estopa", "Vino Tinto", "vino-tinto"),
                                                 ("estopa/tu_calorro", "ESTOPA", "Tu Calorro", "tu-calorro")])
    assert plain(search.lacuerda_artist(first, "estopa")) == plain(search.lacuerda_artist(second, "estopa"))


def test_a_song_an_artist_page_lists_is_named_alike_whichever_tombstone_of_theirs_went_in_first(tmp_path):
    # Two of your removed songs name UG's "Song Dongye (宋冬野)", removed in the same second: one name, either way.
    from helpers.ug_pages import SONG_DONGYE, SONG_DONGYE_URL, song_dongye_chords

    from caracole.ug import artist_tabs
    from caracole.ug.page import parse_version

    def fill(conn, gone):
        conn.executemany("INSERT INTO removed (key, artist, title, removed_at) VALUES (?, ?, ?, "
                         "'2026-10-20T09:00:00Z')", gone)
        artist_tabs.store(conn, SONG_DONGYE_URL, SONG_DONGYE, [parse_version(t) for t in song_dongye_chords()],
                          read_at="2026-10-18T00:00:00Z")

    first, second = both_orders(tmp_path, fill, [("song dong ye|an he qiao", "宋冬野", "安和桥"),
                                                 ("song dongye|nan fang", "Song Dongye", "南方")])
    assert plain(search.find_index(first, "董小姐")) == plain(search.find_index(second, "董小姐"))


# --- search.py: the words a process keeps ----------------------------------------------------------------------------


def test_the_words_a_process_keeps_are_in_the_terms_order_however_the_index_gained_them(tmp_path):
    # Read whole at once, or a word gained after the first search read its letter: the same close spellings, in the
    # same order (fuzz.ratio ties them, and process.extract keeps a tie in its choices' order).
    whole = fresh(tmp_path, "whole")
    ug_rows(whole, [(1, "heavy-x", "a", "chords"), (2, "heave-y", "b", "chords")])
    grown = fresh(tmp_path, "grown")
    ug_rows(grown, [(1, "heavy-x", "a", "chords")])
    search._near(grown, "heavn")
    ug_rows(grown, [(2, "heave-y", "b", "chords")])
    assert search._near(grown, "heavn") == search._near(whole, "heavn") == ["heavn", "heave", "heavy"]


# --- lacuerda_index.py: already one answer, kept so ------------------------------------------------------------------


def test_lacuerdas_index_answers_alike_whichever_rows_went_in_first(tmp_path):
    from caracole import lacuerda_index as li
    from caracole.lacuerda import LCArtist

    artists = [("andres_calamaro", "Andrés Calamaro", 325), ("andres", "Andrés", 3),
               ("andres_canalla", "Andrés Canalla", 9), ("andresito", "Andresito", 40),
               ("enanitos", "Enanitos Verdes", 151), ("enanitos_2", "Enanitos Verdes", 151)]

    def fill(conn, rows):
        li.store_artists(conn, "tabs/a/index0.html", [LCArtist(s, n, c) for s, n, c in rows])

    first, second = both_orders(tmp_path, fill, artists)
    for query in ("andres", "andres calamaro", "enanitos verdes", "andres calamar"):
        assert plain(li.find(first, query)) == plain(li.find(second, query)), query
    assert plain(li.songs_like(first, ["%andres%"])) == plain(li.songs_like(second, ["%andres%"]))


# --- the hash seed --------------------------------------------------------------------------------------------------

# Each case hangs on the order of two things a set held: the score of each is made to tie (the readings patched), so
# the first one iterated says which reading the hit is, or which game comes first.
SEEDED = r'''
import json, sys
from pathlib import Path

from caracole import db, search
from caracole.ug import artist_tabs

out = {}
readings = search._Query.readings


def by_name(self, artist, title):
    return (100.0, 0.0, 0.0) if artist in ("宋冬野", "abc") else (0.0, 0.0, 100.0)


search._Query.readings = by_name
# _names_reading: the plain and the pinyin pair of a Chinese song.
out["names_reading"] = search._names_reading([search._Query("x")], ["宋冬野"], "斑马")
search._Query.readings = readings

conn = db.connect(Path(sys.argv[1]) / "c.sqlite")
# _harp_songs: an artist's page read, whose name and slug are two forms.
conn.execute("INSERT INTO harptabs_index (path, kind, page_id, key, sitemap) VALUES ('artist/1/abc', 'artist', 1, "
             "'abc', 's')")
conn.execute("INSERT INTO harptabs_artists (path, page_id, key, name, tabs, read_at) VALUES ('artist/1/abc', 1, 'abc', "
             "'xyz', 1, '2026-10-27T00:00:00Z')")
conn.execute("INSERT INTO harptabs_artist_tabs (artist, tab_id, path, title, song_key, views, place) VALUES "
             "('artist/1/abc', 5, 'tab/5/song', 'Song', 'song', 1, 0)")
search._Query.readings = by_name
out["harp_songs"] = [h.via for h in search.search_harptabs(conn, "song")[1]]
search._Query.readings = readings

# _listed_rows: two tabs of one song an artist page lists, under two forms of its names.
real = artist_tabs.rows_like


def listed(conn, patterns):
    tab = artist_tabs.ListedTab("p", 1, "chords", "A", "T", None, 0.0, 0, "u", "a", "t", ("abc",), ("t",), "x")
    return [tab, tab.__class__(**{**tab.__dict__, "tab_id": 2, "artist_forms": ("xyz",)})]


def forms_readings(queries, artist_forms, title_forms):
    yield (100.0, 0.0, 0.0) if artist_forms == ("abc",) else (0.0, 0.0, 100.0)


artist_tabs.rows_like, forms = listed, search._forms_readings
search._forms_readings = forms_readings
out["listed_rows"] = [r.via for r in search._listed_rows(conn, [search._Query("x")], ["%x%"], None)[0]]
artist_tabs.rows_like, search._forms_readings = real, forms

# _gametabs_paths: the same track of two games of one name.
for game in ("game-a", "game-b"):
    conn.execute("INSERT INTO gametabs_index (path, kind, game, slug, page, key, slug_key, sitemap) VALUES "
                 "(?, 'tab', ?, 'theme', 0, 'theme', 'theme', 's')", (f"tabs/{game}/theme", game))
    conn.execute("INSERT INTO gametabs_games (path, game, name, tabs, read_at) VALUES (?, ?, 'Same Game', 1, "
                 "'2026-10-28T00:00:00Z')", (f"tabs/{game}", game))
out["gametabs"] = [h.page for h in search.search_gametabs(conn, "same game theme")]
sys.stdout.write(json.dumps(out, ensure_ascii=False))
'''


@pytest.mark.slow
def test_a_set_of_names_is_read_in_one_order_whatever_the_hash_seed(tmp_path):
    env = {**os.environ, "PYTHONPATH": subprocess_pythonpath(f"{SRC}{os.pathsep}{TESTS}")}
    answers = {}
    for seed in range(8):
        (tmp_path / str(seed)).mkdir()
        done = subprocess.run([sys.executable, "-c", SEEDED, str(tmp_path / str(seed))],
                              env={**env, "PYTHONHASHSEED": str(seed)}, capture_output=True, text=True, check=True)
        answers[seed] = json.loads(done.stdout)
    for case in answers[0]:
        seen = {json.dumps(a[case]) for a in answers.values()}
        assert len(seen) == 1, (case, {seed: a[case] for seed, a in answers.items()})
    # The order of first appearance: the plain pair before the pinyin one, the slug's form before the page's name,
    # the first tab's forms; the games by their tabs' paths.
    assert answers[0] == {"names_reading": [100.0, "title"], "harp_songs": ["title"], "listed_rows": ["title"],
                          "gametabs": ["game-a", "game-b"]}
