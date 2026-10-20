import json
import random
import re
import socket
import sqlite3
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.library import keep_file
from caracole.search import bare_id_hint, display_from_keys, search_index, search_library
from caracole.songs import find_song, update_song
from caracole.versions import upsert_version

from conftest import add_song

# (tab_id, artist_key, song_key, type); paths are built the way the sitemaps write them.
ROWS = [
    (4169, "radiohead", "creep", "chords"),
    (4170, "radiohead", "creep", "chords"),
    (4171, "radiohead", "creep", "chords"),
    (4172, "radiohead", "creep", "tabs"),
    (4173, "radiohead", "creep", "tabs"),
    (4174, "radiohead", "creep-acoustic", "guitar-pro"),
    (5001, "stone-temple-pilots", "creep", "chords"),
    (6001, "metallica", "creeping-death", "guitar-pro"),
    (6002, "metallica", "creeping-death", "tabs"),
    (7001, "radiohead", "karma-police", "chords"),
    (1081460, "soda-stereo", "persiana-americana", "chords"),
    (1081462, "soda-stereo", "persiana-americana", "tabs"),
    (1081470, "soda-stereo", "persiana-americana-intro", "tabs"),
    (9001, "acdc", "highway-to-hell", "chords"),
    (9101, "r-e-m", "losing-my-religion", "chords"),
]
PINYIN_ROWS = [(8001, "song-dongye", "ban-ma-ban-ma", "chords")]


def index(conn, rows):
    conn.executemany(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (?, ?, ?, ?, '1', 'x', ?)",
        [(tid, a, s, t, f"{a}/{s}-{t}-{tid}") for tid, a, s, t in rows],
    )


def keys(hits):
    return [(h.artist_key, h.song_key) for h in hits]


# --- display_from_keys -------------------------------------------------------------


@pytest.mark.parametrize("artist_key,song_key,expected", [
    ("soda-stereo", "de-musica-ligera", ("Soda Stereo", "De Musica Ligera")),
    ("matchbox-twenty", "3am", ("Matchbox Twenty", "3am")),
    ("r-e-m", "losing-my-religion", ("R E M", "Losing My Religion")),
])
def test_display_from_keys_title_cases_words(artist_key, song_key, expected):
    assert display_from_keys(artist_key, song_key) == expected


# --- search_index ------------------------------------------------------------------


def test_exact_title_ranks_first_and_popular_songs_lead_ties(conn):
    index(conn, ROWS)
    hits = search_index(conn, "creep")
    assert keys(hits)[:3] == [
        ("radiohead", "creep"), ("stone-temple-pilots", "creep"), ("metallica", "creeping-death"),
    ]
    assert hits[0].score == 100


def test_index_hit_groups_variant_slugs_and_counts_types(conn):
    index(conn, ROWS)
    top = search_index(conn, "creep")[0]
    assert dict(top.counts) == {"chords": 3, "tabs": 2, "guitar-pro": 1}
    assert list(top.counts) == ["chords", "tabs", "guitar-pro"]
    assert top.labels == ("acoustic",)
    assert top.url == "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"


def test_variant_only_match_is_grouped_under_its_song(conn):
    index(conn, ROWS)
    top = search_index(conn, "Persiana Américana")[0]
    assert (top.artist_key, top.song_key) == ("soda-stereo", "persiana-americana")
    assert dict(top.counts) == {"chords": 1, "tabs": 2}
    assert top.labels == ("intro",)
    assert top.url == "https://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-chords-1081460"


def test_artist_and_title_beats_title_alone(conn):
    index(conn, ROWS)
    hits = search_index(conn, "stone temple pilots creep")
    assert keys(hits)[0] == ("stone-temple-pilots", "creep")
    assert hits[0].score == 100


def test_typo_in_the_longest_word_still_finds_the_song(conn):
    index(conn, ROWS)
    assert keys(search_index(conn, "radiohed creep"))[0] == ("radiohead", "creep")


@pytest.mark.parametrize("query,expected", [
    ("AC/DC", ("acdc", "highway-to-hell")),
    ("R.E.M.", ("r-e-m", "losing-my-religion")),
])
def test_names_made_of_initials(conn, query, expected):
    index(conn, ROWS)
    assert keys(search_index(conn, query))[0] == expected


def test_hit_names_come_from_ugs_slugs_which_keep_the_and_and(conn):
    conn.executemany(
        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
        "VALUES (?, ?, ?, 'chords', '1', 'x', ?)",
        [(389691, "rifles", "local-boy", "the-rifles/local-boy-chords-389691"),
         (767025, "adam-the-ants", "stand-deliver", "adam-and-the-ants/stand-and-deliver-chords-767025")],
    )
    hit = search_index(conn, "the rifles local boy")[0]
    assert (hit.artist, hit.title) == ("The Rifles", "Local Boy")
    hit = search_index(conn, "adam and the ants stand and deliver")[0]
    assert (hit.artist, hit.title) == ("Adam And The Ants", "Stand And Deliver")


def test_a_song_listed_only_by_its_variant_is_named_without_the_label(conn):
    index(conn, [(6236009, "misc-traditional", "froggy-went-a-courtin-intro", "chords")])
    hit = search_index(conn, "froggy went a courtin")[0]
    assert (hit.song_key, hit.labels) == ("froggy-went-a-courtin", ("intro",))
    assert hit.title == "Froggy Went A Courtin"


def test_limit_and_unrelated_rows_left_out(conn):
    index(conn, ROWS)
    hits = search_index(conn, "creep", limit=2)
    assert keys(hits) == [("radiohead", "creep"), ("stone-temple-pilots", "creep")]
    assert ("radiohead", "karma-police") not in keys(search_index(conn, "creep"))


@pytest.mark.parametrize("query", ["宋冬野", "斑马，斑马", "宋冬野 斑马"])
def test_chinese_queries_try_romanized_keys(conn, query):
    index(conn, ROWS + PINYIN_ROWS)
    assert keys(search_index(conn, query))[0] == ("song-dongye", "ban-ma-ban-ma")


@pytest.mark.parametrize("artist_key", ["song-dongye", "songdongye", "song-dong-ye"])
def test_pinyin_syllables_match_however_ug_hyphenates_them(conn, artist_key):
    index(conn, ROWS + [(8001, artist_key, "ban-ma-ban-ma", "chords")])
    assert keys(search_index(conn, "宋冬野"))[0] == (artist_key, "ban-ma-ban-ma")


def test_chinese_query_without_pinyin_rows_finds_nothing_and_hints_at_artist_url(conn):
    index(conn, ROWS)
    hits = search_index(conn, "宋冬野")
    assert hits == []
    hint = bare_id_hint("宋冬野", hits)
    assert hint is not None and "[artist_url]" in hint and "bare" in hint


def test_no_hint_for_a_plain_query_with_a_good_hit(conn):
    index(conn, ROWS)
    assert bare_id_hint("creep", search_index(conn, "creep")) is None


def test_no_hint_for_typographic_punctuation_around_a_strong_hit(conn):
    index(conn, ROWS)
    query = "AC/DC — “Highway to Hell”"
    hits = search_index(conn, query)
    assert keys(hits)[0] == ("acdc", "highway-to-hell") and hits[0].score >= 90
    assert bare_id_hint(query, hits) is None


def test_hint_for_an_accented_name_without_a_strong_hit(conn):
    index(conn, ROWS)
    hits = search_index(conn, "Joaquín Sabina")
    assert all(h.score < 90 for h in hits)
    assert "[artist_url]" in bare_id_hint("Joaquín Sabina", hits)


def test_accented_query_with_a_strong_hit_still_mentions_bare_ids_briefly(conn):
    index(conn, ROWS)
    hits = search_index(conn, "Persiana Américana")
    assert hits[0].score == 100
    brief = bare_id_hint("Persiana Américana", hits)
    assert "[artist_url]" in brief and "bare" in brief
    assert len(brief) < len(bare_id_hint("Persiana Américana", []))


def test_hint_says_the_paste_lines_key_is_the_artist():
    assert "artist's name" in bare_id_hint("joaquin sabina 19 dias", [])


def test_hint_paste_line_names_the_artist():
    hint = bare_id_hint("宋冬野 斑马", [], artist="宋冬野")
    assert '"宋冬野" = "https://www.ultimate-guitar.com/artist/…"' in hint and "<name>" not in hint
    assert '"Joaquín Sabina" = "https://www.ultimate-guitar.com/artist/' in bare_id_hint("Joaquín Sabina", [])


def test_hint_takes_a_tab_page_of_the_artist_too():
    for hint in (bare_id_hint("宋冬野", []), bare_id_hint("Persiana Américana", [], artist="Soda Stereo")):
        assert "or one of their tab pages" in hint


def test_hint_knows_an_entry_written_as_ug_names_the_artist():
    from caracole.overrides import Overrides

    o = Overrides(artist_url={"song-dongye-宋冬野": "https://tabs.ultimate-guitar.com/tab/4180894"},
                  artist_url_names={"song-dongye-宋冬野": "Song Dongye (宋冬野)"})  # as load_overrides keeps it
    hint = bare_id_hint("宋冬野", [], overrides=o)
    assert "overrides.toml has 宋冬野's page already (https://tabs.ultimate-guitar.com/tab/4180894)" in hint


MANA = '[artist_url]\n"Maná" = "https://www.ultimate-guitar.com/artist/mana_98"\n'


@pytest.mark.parametrize("query,hits", [("Joaquín Sabina", []), ("Persiana Américana", None)])
def test_hint_leaves_the_header_out_when_overrides_has_the_table(conn, query, hits):
    # A second [artist_url] header would make overrides.toml unreadable, as on the to-do page.
    from caracole.overrides import Overrides

    index(conn, ROWS)
    hits = search_index(conn, query) if hits is None else hits
    o = Overrides(artist_url={"mana": "https://www.ultimate-guitar.com/artist/mana_98"})
    hint = bare_id_hint(query, hits, overrides=o)
    assert "    [artist_url]\n" not in hint and "under the [artist_url] table it has already" in hint
    assert "    [artist_url]\n" in bare_id_hint(query, hits, overrides=Overrides())
    assert "    [artist_url]\n" in bare_id_hint(query, hits)


def test_empty_query_finds_nothing(conn):
    index(conn, ROWS)
    assert search_index(conn, " — ") == []
    assert search_library(conn, "") == []


WORDS = (
    "love night heart blue fire rain summer dance dream girl road home light world time river moon "
    "song wild sweet black white angel city stone gold sun star money baby kiss tears ghost queen "
    "king band boys club hotel radio electric velvet silver paper glass iron sugar honey diamond"
).split()
TYPES = ("chords", "tabs", "guitar-pro", "power")


def synthetic_rows(n, seed=7):
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        artist = "-".join(rng.sample(WORDS, 2)) + f"-{i % 997}"
        song = "-".join(rng.sample(WORDS, rng.randint(1, 4)))
        rows.append((10_000_000 + i, artist, song, rng.choice(TYPES)))
    return rows


@pytest.mark.parametrize("patterns", [
    ["%love%"], ["%love%", "%night%"], ["%creep%"], ["%u2%"], ["%r-e-m%", "%rem%"], ["%ban%ma%ban%ma%"],
    ["%song%dong%ye%"], ["%acdc%"], ["%nothing-at-all%"],
])
def test_the_prefilter_finds_through_the_key_index_what_a_scan_of_every_row_finds(conn, patterns):
    from caracole.ug.key_search import rows_like

    index(conn, synthetic_rows(3_000) + ROWS + PINYIN_ROWS)
    where = " OR ".join(f"artist_key LIKE ?{i} OR song_key LIKE ?{i}" for i in range(1, len(patterns) + 1))
    scan = conn.execute(f"SELECT artist_key, song_key, COUNT(*) FROM ug_index WHERE {where} "
                        "GROUP BY artist_key, song_key", patterns).fetchall()
    assert sorted(rows_like(conn, patterns)) == sorted(tuple(r) for r in scan)


def test_a_common_word_brings_in_its_shortest_keys_and_those_every_word_is_in(conn, monkeypatch):
    # "the" or "love" is in tens of thousands of keys: ranking them all took a second a keystroke.
    from caracole.ug import key_search

    monkeypatch.setattr(key_search, "KEYS_PER_PATTERN", 2)
    index(conn, [(1, "x", "love", "chords"), (2, "y", "lovely", "chords"), (3, "z", "glove-box", "chords"),
                 (4, "w", "i-love-you-baby", "chords"), (5, "v", "baby", "chords"), (6, "u", "babylon", "chords")])
    found = {song for _, song, _ in key_search.rows_like(conn, ["%love%"])}
    assert found == {"love", "lovely"}  # the two shortest
    both = {song for _, song, _ in key_search.rows_like(conn, ["%love%", "%baby%"])}
    assert both == {"love", "lovely", "baby", "babylon", "i-love-you-baby"}  # and the one with both words


def test_the_prefilter_reads_the_trigram_index_not_every_row(conn):
    from caracole.ug import key_search

    plans = []
    real = conn.execute

    class Spy:
        def execute(self, sql, *args):
            if "ug_keys_fts" in sql:
                plans.append(" ".join(r[3] for r in real(f"EXPLAIN QUERY PLAN {sql}", *args)))
            return real(sql, *args)

    index(conn, ROWS)
    key_search.rows_like(Spy(), ["%creep%"])
    assert plans and all("VIRTUAL TABLE INDEX" in p for p in plans)


def test_index_search_is_fast_on_a_large_index(conn):
    conn.execute("BEGIN")
    index(conn, synthetic_rows(50_000) + ROWS + PINYIN_ROWS)
    conn.execute("COMMIT")
    for query in ("radiohead creep", "radiohed creep", "persiana americana", "宋冬野 斑马", "love", "AC/DC"):
        start = time.perf_counter()
        hits = search_index(conn, query)
        elapsed = time.perf_counter() - start
        assert hits, query
        assert elapsed < 0.5, f"{query!r} took {elapsed:.2f} s"
    assert keys(search_index(conn, "radiohead creep"))[0] == ("radiohead", "creep")


# --- search_library ----------------------------------------------------------------


def test_library_search_ignores_accents_and_case(conn):
    add_song(conn, "Soda Stereo", "De Música Ligera")
    add_song(conn, "Radiohead", "Creep")
    assert [h.song.title for h in search_library(conn, "MUSICA")] == ["De Música Ligera"]


@pytest.mark.parametrize("query", ["ban ma", "banma", "song dongye", "斑马斑马", "宋冬野"])
def test_library_search_matches_han_text_and_pinyin(conn, query):
    add_song(conn, "宋冬野", "斑马，斑马")
    add_song(conn, "Radiohead", "Creep")
    hits = search_library(conn, query)
    assert [h.song.artist for h in hits] == ["宋冬野"]


def test_library_search_finds_simplified_titles_from_traditional_characters(conn):
    add_song(conn, "宋冬野", "斑马，斑马")
    add_song(conn, "Radiohead", "Creep")
    assert [h.song.artist for h in search_library(conn, "斑馬")] == ["宋冬野"]


def test_library_search_matches_any_of_a_songs_artists(conn):
    add_song(conn, "Shakira", "La Tortura", artists=["Shakira", "Alejandro Sanz"])
    add_song(conn, "Radiohead", "Creep")
    assert [h.song.title for h in search_library(conn, "alejandro sanz")] == ["La Tortura"]


def test_library_search_finds_songs_of_any_status(conn):
    s = add_song(conn, "Radiohead", "Creep")
    update_song(conn, s.id, status="ignored")
    assert [h.song.id for h in search_library(conn, "creep")] == [s.id]


def test_library_search_ranks_exact_titles_first_and_limits(conn):
    add_song(conn, "Metallica", "Creeping Death")
    add_song(conn, "Radiohead", "Creep")
    add_song(conn, "TLC", "Creep")
    hits = search_library(conn, "creep", limit=2)
    assert sorted(h.song.artist for h in hits) == ["Radiohead", "TLC"]
    assert [h.song.artist for h in search_library(conn, "creep")][-1] == "Metallica"


def test_library_search_artist_with_typo(conn):
    add_song(conn, "Radiohead", "Creep")
    add_song(conn, "Soda Stereo", "Persiana Americana")
    assert [h.song.artist for h in search_library(conn, "radiohed")] == ["Radiohead"]


def test_library_search_without_a_match(conn):
    add_song(conn, "Radiohead", "Creep")
    assert search_library(conn, "zzzz qqqq") == []


# --- gtptabs.com's and MuseScore's offline indexes -------------------------------------------


def gtptabs_pages(conn, *urls):
    """gtptabs.com's song pages, as its sitemaps list them (gtptabs.parse_page_url makes the rows)."""
    from caracole.gtptabs import parse_page_url

    rows = [parse_page_url(u) for u in urls]
    conn.executemany("INSERT INTO gtptabs_index (path, artist_path, artist_key, title_key, base_key, sitemap) "
                     "VALUES (?, ?, ?, ?, ?, '1')", [tuple(r) for r in rows])


def musescore_pages(conn, *urls):
    from caracole.musescore import parse_song_url

    conn.executemany("INSERT INTO musescore_index (page_id, path, title_key, sitemap) VALUES (?, ?, ?, '1')",
                     [tuple(parse_song_url(u)) for u in urls])


GTP = "https://gtptabs.com/tabs/"


def test_gtptabs_pages_are_found_by_artist_and_title_or_either_alone(conn):
    from caracole.search import search_gtptabs

    gtptabs_pages(conn, GTP + "18/radiohead/creep.html", GTP + "18/radiohead/creep-2.html",
                  GTP + "18/radiohead/karma-police.html", GTP + "20/stone-temple-pilots/creep.html",
                  GTP + "13/metallica/creeping-death.html", GTP + "18/radiohead.html")
    hits = search_gtptabs(conn, "radiohead creep")
    assert [(h.artist_key, h.title_key) for h in hits][:1] == [("radiohead", "creep")]
    first = hits[0]
    assert (first.source, first.artist, first.title, first.uploads) == ("gtptabs", "Radiohead", "Creep", 2)
    assert first.url == GTP + "18/radiohead/creep.html"  # the first upload's page, never an artist page
    assert {(h.artist_key, h.title_key) for h in search_gtptabs(conn, "creep")} >= {
        ("radiohead", "creep"), ("stone-temple-pilots", "creep")}
    assert [h.title_key for h in search_gtptabs(conn, "radiohead")] == ["creep", "karma-police"]
    assert search_gtptabs(conn, "zzzz qqqq") == [] and search_gtptabs(conn, " — ") == []
    assert len(search_gtptabs(conn, "creep", limit=1)) == 1


def test_a_gtptabs_artist_filed_last_name_first_is_named_as_ultimate_guitar_names_them(conn):
    from caracole.search import search_gtptabs

    index(conn, [(1, "elton-john", "your-song", "chords")])
    gtptabs_pages(conn, GTP + "10/john-elton/your-song.html", GTP + "2/beatles-the/yesterday.html")
    [elton] = search_gtptabs(conn, "your song")
    assert (elton.artist, elton.title) == ("Elton John", "Your Song")  # not "John Elton", the site's filing
    [beatles] = search_gtptabs(conn, "yesterday")
    assert beatles.artist == "Beatles"  # no UG row: from its key


def test_musescore_pages_are_found_by_their_whole_title_alone(conn):
    from caracole.search import search_musescore

    index(conn, [(1, "oasis", "wonderwall", "chords"), (2, "oasis", "live-forever", "chords")])
    musescore_pages(conn, "https://musescore.com/song/wonderwall-1524", "https://musescore.com/song/wonderwall-99",
                    "https://musescore.com/song/creep-7", "https://musescore.com/song/live_forever-8")
    hits = search_musescore(conn, "wonderwall")
    assert [(h.source, h.title, h.artist, h.url) for h in hits] == [
        ("musescore", "Wonderwall", "", "https://musescore.com/song/wonderwall-99"),
        ("musescore", "Wonderwall", "", "https://musescore.com/song/wonderwall-1524")]
    # The artist's words around the title are left for it, the sitemaps naming no artist: Oasis has a Wonderwall.
    assert [h.url for h in search_musescore(conn, "oasis wonderwall")][:1] == ["https://musescore.com/song/wonderwall-99"]
    assert [h.title for h in search_musescore(conn, "live forever oasis")] == ["Live Forever"]
    assert search_musescore(conn, "wonder") == []  # a part of a word is no title
    musescore_pages(conn, "https://musescore.com/song/ban_ma_ban_ma-5")
    assert [h.url for h in search_musescore(conn, "斑马，斑马")] == ["https://musescore.com/song/ban_ma_ban_ma-5"]
    assert len(search_musescore(conn, "wonderwall", limit=1)) == 1



def test_a_musescore_title_is_never_a_word_of_the_query_that_leaves_no_known_song(conn):
    from caracole.search import search_musescore

    index(conn, [(1, "oasis", "live-forever", "chords"), (2, "eagles", "hotel-california", "chords"),
                 (3, "hotel", "lobby", "chords"), (4, "forever", "young", "chords")])
    musescore_pages(conn, *(f"https://musescore.com/song/{title}-{n}" for n, title in enumerate(
        ["oasis", "hotel_california", "eagles", "the", "california", "live", "forever", "live_forever"], 1)))

    def titles(query):
        return [h.title for h in search_musescore(conn, query)]

    # A run of the query's words is a title only when the rest names the artist of a song by that title:
    # "Forever" leaves "oasis live", no one's name, and "Oasis" leaves "live forever", no one's song.
    assert titles("oasis live forever") == ["Live Forever"]
    assert titles("the eagles hotel california") == ["Hotel California"]
    assert titles("hotel california") == ["Hotel California"]  # Hotel, an artist, has no song "California"
    assert titles("eagles") == ["Eagles"]  # a whole query is a title whoever sings it
    assert titles("california eagles") == []  # Eagles have no "California"
    gtptabs_pages(conn, GTP + "10/john-elton/your-song.html")
    musescore_pages(conn, "https://musescore.com/song/your_song-9")
    assert titles("elton john your song") == ["Your Song"]  # gtptabs.com's, filed last name first
    assert titles("forever live") == []  # Forever's one song is "Young"
    add_song(conn, "Forever", "Live")  # a song of yours names its artist too
    assert titles("forever live") == ["Live"]


# --- caracole search -----------------------------------------------------------------


def config(tmp_path: Path) -> Path:
    p = tmp_path / "caracole.toml"
    p.write_text(
        f'library_dir = "{tmp_path / "lib"}"\nmusic_dir = "{tmp_path / "music"}"\n'
        f'state_dir = "{tmp_path / "state"}"\ncache_dir = "{tmp_path / "cache"}"\n',
        encoding="utf-8",
    )
    return p


def run(tmp_path, *args):
    return CliRunner().invoke(build_app(), ["--config", str(config(tmp_path)), *args])


def seed(tmp_path, rows=ROWS):
    conn = db.connect(tmp_path / "state" / "caracole.sqlite")
    index(conn, rows)
    s = add_song(conn, "Radiohead", "Creep")
    update_song(conn, s.id, status="found")
    (tmp_path / "lib" / "Radiohead" / "Creep").mkdir(parents=True)
    return conn


def test_cli_prints_library_hits_and_numbered_index_hits(tmp_path):
    seed(tmp_path)
    result = run(tmp_path, "search", "creep")
    assert result.exit_code == 0, result.output
    out = result.output
    library, _, ug = out.partition("On Ultimate Guitar (offline index)")
    assert "In your library" in library
    assert "Radiohead - Creep" in library and "found" in library
    assert str(tmp_path / "lib" / "Radiohead" / "Creep") in library
    assert "1. [UG] Radiohead - Creep" in ug
    assert "chords×3 tabs×2 guitar-pro×1" in ug
    assert "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169" in ug
    assert "2. [UG] Stone Temple Pilots - Creep" in ug
    assert 'caracole add "Stone Temple Pilots" "Creep"' in ug


def test_cli_add_appends_the_hit_to_wanted_and_syncs(tmp_path):
    conn = seed(tmp_path)
    result = run(tmp_path, "search", "creep", "--add", "2")
    assert result.exit_code == 0, result.output
    wanted = (tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8")
    assert "Stone Temple Pilots - Creep" in wanted
    song = find_song(conn, "stone-temple-pilots/creep")
    assert song is not None and "wanted" in song.source_ids
    assert "Stone Temple Pilots - Creep" in result.output and "wanted.txt" in result.output


def test_cli_add_says_in_one_line_what_it_did_as_caracole_add_does(tmp_path):
    seed(tmp_path)
    result = run(tmp_path, "search", "creep", "--add", "2")
    assert result.exit_code == 0, result.output
    assert result.output == (
        "Added Stone Temple Pilots - Creep to wanted.txt; the next `caracole run` looks for it.\n"
        "On Ultimate Guitar: stone-temple-pilots/creep (exact)\n")  # then what the offline index says, as add does
    again = run(tmp_path, "-v", "search", "creep", "--add", "2")
    assert again.exit_code == 0, again.output
    assert ("Stone Temple Pilots - Creep is in wanted.txt already; the library has it, with no sheet yet.\n"
            in again.output)
    path = tmp_path / "lib" / "wanted.txt"
    assert re.search(rf"wanted.txt line \d+ \({re.escape(str(path))}\): Stone Temple Pilots - Creep\n",
                     again.output)  # at -v, where it is
    assert "Song stone-temple-pilots/creep: already known, wanted" in again.output


def test_cli_add_twice_keeps_one_line(tmp_path):
    seed(tmp_path)
    run(tmp_path, "search", "creep", "--add", "2")
    result = run(tmp_path, "search", "creep", "--add", "2")
    assert result.exit_code == 0, result.output
    wanted = (tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8")
    assert wanted.count("Stone Temple Pilots - Creep") == 1
    assert "already" in result.output


def test_cli_add_skips_a_hit_your_library_has_under_another_name(tmp_path):
    conn = seed(tmp_path)
    other = add_song(conn, "Stone Temple Pilot", "Creep")
    update_song(conn, other.id, match_decision="accept", match_artist_key="stone-temple-pilots", match_song_key="creep")
    result = run(tmp_path, "search", "creep", "--add", "2")
    assert result.exit_code == 0, result.output
    assert "Stone Temple Pilot - Creep" in result.output
    assert not (tmp_path / "lib" / "wanted.txt").exists()
    assert find_song(conn, "stone-temple-pilots/creep") is None


PARALAMAS = (9201, "os-paralamas-do-sucesso", "de-musica-ligera", "chords")


def test_cli_a_review_candidate_is_not_a_song_in_your_library(tmp_path):
    # De Música Ligera is reviewed on its title alone: its only candidate is a Portuguese cover.
    conn = seed(tmp_path, rows=ROWS + [PARALAMAS])
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    update_song(conn, soda.id, review=True, match_decision="review", match_step="title_only",
                match_artist_key="os-paralamas-do-sucesso", match_song_key="de-musica-ligera", match_candidates=[
                    {"artist_key": "os-paralamas-do-sucesso", "song_key": "de-musica-ligera", "score": 100.0,
                     "step": "title_only"}])
    listed = run(tmp_path, "search", "os paralamas de musica ligera").output
    assert 'caracole add "Os Paralamas Do Sucesso" "De Musica Ligera"' in listed, listed
    result = run(tmp_path, "search", "os", "paralamas", "de", "musica", "ligera", "--add", "1")
    assert result.exit_code == 0, result.output
    assert "Soda Stereo" not in result.output
    assert find_song(conn, "os-paralamas-do-sucesso/de-musica-ligera") is not None


def test_cli_add_names_the_hits_own_song_before_a_misspelled_review(tmp_path):
    conn = seed(tmp_path)  # Radiohead - Creep is in the library, accepted
    creep = find_song(conn, "radiohead/creep")
    update_song(conn, creep.id, match_decision="accept", match_step="exact", match_artist_key="radiohead",
                match_song_key="creep")
    (tmp_path / "lib" / "wanted.txt").write_text("Radiohead - Creep\n", encoding="utf-8")
    typo = add_song(conn, "Radio Head", "Crep")
    update_song(conn, typo.id, review=True, match_decision="review", match_step="fuzzy_title",
                match_artist_key="radiohead", match_song_key="creep", match_candidates=[
                    {"artist_key": "radiohead", "song_key": "creep", "score": 88.9, "step": "fuzzy_title"}])
    result = run(tmp_path, "search", "creep", "--add", "1")
    assert result.exit_code == 0, result.output
    assert "Radio Head - Crep" not in result.output
    assert "Radiohead - Creep is in wanted.txt already" in result.output


def test_cli_add_keeps_the_line_when_the_database_cannot_be_updated(tmp_path, monkeypatch):
    seed(tmp_path)

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("caracole.wanted.sync_wanted", locked)
    result = run(tmp_path, "search", "creep", "--add", "2")
    assert result.exit_code == 0, result.output
    wanted = (tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8")
    assert wanted.endswith("\nStone Temple Pilots - Creep\n")  # the file is the source of truth
    assert "the database couldn't be updated (database is locked)" in result.output
    assert "`caracole sync`" in result.output


def test_cli_add_out_of_range_is_a_usage_error(tmp_path):
    seed(tmp_path)
    result = run(tmp_path, "search", "creep", "--add", "9")
    assert result.exit_code == 2
    assert "9" in result.output
    assert not (tmp_path / "lib" / "wanted.txt").exists()


def test_cli_add_a_hit_beyond_those_shown_is_refused(tmp_path):
    # `--limit 1` shows one hit: hit 2 was never seen (a typo such as --add 12 for --add 2 does the same).
    seed(tmp_path)
    result = run(tmp_path, "search", "creep", "--limit", "1", "--add", "2")
    assert not (tmp_path / "lib" / "wanted.txt").exists(), result.output
    assert result.exit_code == 2
    assert "only the first hit is shown" in result.output and "--limit 2" in result.output
    shown = run(tmp_path, "search", "creep", "--limit", "2", "--add", "2")
    assert shown.exit_code == 0, shown.output
    assert "Stone Temple Pilots - Creep" in (tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8")


def test_cli_add_12_for_add_2_with_the_default_limit_is_refused(tmp_path):
    covers = [(8100 + i, f"cover-band-{i:02d}", "creep", "chords") for i in range(12)]
    seed(tmp_path, rows=ROWS + covers)
    listed = run(tmp_path, "search", "creep").output
    assert "10. " in listed and "11. " not in listed  # ten hits shown
    result = run(tmp_path, "search", "creep", "--add", "12")
    assert not (tmp_path / "lib" / "wanted.txt").exists(), result.output
    assert result.exit_code == 2
    assert "only the first 10 hits are shown" in result.output and "--limit 12" in result.output


def test_cli_chinese_query_points_to_artist_url(tmp_path):
    seed(tmp_path)
    result = run(tmp_path, "search", "宋冬野")
    assert result.exit_code == 0, result.output
    assert "[artist_url]" in result.output and "bare" in result.output


def paste_hint(output: str, overrides: Path) -> None:
    """The hint's lines, pasted into overrides.toml as it says: a block with its header at the end,
    lines without one under the [artist_url] table the file has."""
    block = re.findall(r"^    (\S.*)$", output, re.M)
    lines = "".join(f"{line}\n" for line in block).replace("…", "joaquin_sabina_1234")
    text = overrides.read_text(encoding="utf-8")
    if block[0] == "[artist_url]":
        text += "\n" + lines
    else:
        text = text.replace("[artist_url]\n", "[artist_url]\n" + lines, 1)
    overrides.write_text(text, encoding="utf-8")


def test_cli_hint_pasted_as_shown_keeps_overrides_readable(tmp_path):
    from caracole.overrides import load_overrides

    seed(tmp_path)
    overrides = tmp_path / "lib" / "overrides.toml"
    for before, artists in (("", {"joaquin-sabina"}), (MANA, {"mana", "joaquin-sabina"})):
        overrides.write_text(before, encoding="utf-8")
        result = run(tmp_path, "search", "Joaquín", "Sabina")
        assert result.exit_code == 0, result.output
        paste_hint(result.output, overrides)
        assert set(load_overrides(overrides).artist_url) == artists, overrides.read_text(encoding="utf-8")


def test_cli_hint_for_an_artist_whose_page_overrides_has_gives_no_second_line(tmp_path):
    # The song is in your library, by an artist UG lists only by bare ids, whose page you pasted: a
    # second line for the artist under [artist_url] would make overrides.toml unreadable.
    from caracole.overrides import load_overrides

    conn = seed(tmp_path)
    add_song(conn, "Joaquín Sabina", "19 Días y 500 Noches")
    overrides = tmp_path / "lib" / "overrides.toml"
    page = "https://www.ultimate-guitar.com/artist/joaquin_sabina_1234"
    overrides.write_text(f'[artist_url]\n"Joaquín Sabina" = "{page}"\n', encoding="utf-8")
    result = run(tmp_path, "search", "19", "dias", "y", "500", "noches")
    assert result.exit_code == 0, result.output
    assert not re.findall(r"^    (\S.*)$", result.output, re.M), result.output
    hint = " ".join(result.output.split())
    assert f"overrides.toml has Joaquín Sabina's page already ({page})" in hint
    assert set(load_overrides(overrides).artist_url) == {"joaquin-sabina"}


def test_cli_search_still_hints_when_overrides_cant_be_read(tmp_path):
    seed(tmp_path)
    (tmp_path / "lib" / "overrides.toml").write_text(MANA + "\n" + MANA, encoding="utf-8")
    result = run(tmp_path, "search", "Joaquín", "Sabina")
    assert result.exit_code == 0, result.output
    assert "[artist_url]" in result.output and "bare" in result.output


def test_cli_empty_index_says_how_to_build_it(tmp_path):
    seed(tmp_path, rows=[])
    result = run(tmp_path, "search", "creep")
    assert result.exit_code == 0, result.output
    assert "caracole index build" in result.output


def test_cli_never_touches_the_network(tmp_path, monkeypatch):
    seed(tmp_path)

    def no_network(*args, **kwargs):
        raise AssertionError("caracole search made a network call")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    result = run(tmp_path, "search", "creep", "--add", "1")
    assert result.exit_code == 0, result.output


# --- caracole search --key ------------------------------------------------------------


def keep_sheet(conn, lib, song, content, *, raw=None, tab_id):
    v = upsert_version(conn, provider="ug", tab_id=str(tab_id), song_id=song.id, slot="sheet",
                       kind="chords", rating=4.5, votes=10, version=1, label=None,
                       url=f"https://tabs.ultimate-guitar.com/tab/{tab_id}", raw=raw or {}, now="x")
    keep_file(conn, lib, song=song, version_id=v, name="sheet.json",
              data=json.dumps({"content": content}).encode(), rank=1)
    keep_file(conn, lib, song=song, version_id=v, name="sheet.txt", data=content.encode(), rank=1)
    update_song(conn, song.id, status="found")


def seed_keys(tmp_path):
    """Creep in G (UG says so), De Música Ligera in A minor (its chords), Lucky in F# minor."""
    conn = seed(tmp_path)
    lib = tmp_path / "lib"
    keep_sheet(conn, lib, find_song(conn, "radiohead/creep"), "Words\n", raw={"tonality_name": "G"},
               tab_id=4169)
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    keep_sheet(conn, lib, soda, "[ch]Am[/ch] [ch]F[/ch] [ch]C[/ch] [ch]G[/ch]\nWords\n" * 3, tab_id=1)
    lucky = add_song(conn, "Radiohead", "Lucky")
    keep_sheet(conn, lib, lucky, "Words\n", raw={"tonality_name": "F#m"}, tab_id=2)
    add_song(conn, "Queen", "Don't Stop Me Now")
    return conn


def test_cli_library_hits_show_their_key(tmp_path):
    seed_keys(tmp_path)
    result = run(tmp_path, "search", "creep")
    assert result.exit_code == 0, result.output
    assert "Radiohead - Creep · found · Key G major (from the tab) · " in result.output


def test_cli_hits_are_tagged_with_where_they_came_from(tmp_path):
    conn = seed_keys(tmp_path)
    lucky = find_song(conn, "radiohead/lucky")
    lc = upsert_version(conn, provider="lacuerda", tab_id="radiohead/lucky", song_id=lucky.id, slot="sheet",
                        kind="acordes", rating=0, votes=0, version=2, label=None,
                        url="https://acordes.lacuerda.net/radiohead/lucky.shtml", raw={}, now="x")
    keep_file(conn, tmp_path / "lib", song=lucky, version_id=lc, name="sheet.txt", data=b"LaCuerda's\n", rank=1)
    add_song(conn, "Radiohead", "Airbag")  # wanted: no sheet yet, so no tag
    result = run(tmp_path, "search", "radiohead")
    assert result.exit_code == 0, result.output
    library, _, ug = result.output.partition("On Ultimate Guitar (offline index)")
    assert "\n  [UG] Radiohead - Creep · found · Key G major (from the tab) · " in library
    assert "\n  [LaCuerda] Radiohead - Lucky · found" in library
    assert "\n  Radiohead - Airbag · wanted, no sheet yet · no folder yet" in library
    assert "\n  1. [UG] Radiohead - Creep · chords×3" in ug  # the offline index is Ultimate Guitar's


def test_cli_search_by_key_alone_lists_your_songs_in_that_key(tmp_path):
    seed_keys(tmp_path)
    result = run(tmp_path, "search", "--key", "Am")
    assert result.exit_code == 0, result.output
    assert "In your library, in A minor" in result.output
    assert "Soda Stereo - De Música Ligera · found · Key A minor (estimated from the chords)" in result.output
    assert "Creep" not in result.output and "Queen" not in result.output
    # The offline index knows no keys: it isn't searched.
    assert "On Ultimate Guitar" not in result.output and "without --key" in result.output


def test_cli_search_by_key_and_words(tmp_path):
    seed_keys(tmp_path)
    result = run(tmp_path, "search", "radiohead", "--key", "G major")
    assert result.exit_code == 0, result.output
    assert "Radiohead - Creep" in result.output and "Lucky" not in result.output
    result = run(tmp_path, "search", "soda", "--key", "G")
    assert result.exit_code == 0, result.output
    assert "nothing matches" in result.output


def test_cli_search_by_key_matches_any_spelling_of_the_key(tmp_path):
    seed_keys(tmp_path)
    result = run(tmp_path, "search", "--key", "Gbm")
    assert result.exit_code == 0, result.output
    assert "Radiohead - Lucky · found · Key F# minor (from the tab)" in result.output


@pytest.mark.parametrize(
    ("typed", "heading", "song"),
    [
        ("am", "A minor", "Soda Stereo - De Música Ligera"),
        ("a minor", "A minor", "Soda Stereo - De Música Ligera"),
        ("f#m", "F# minor", "Radiohead - Lucky"),
        ("g", "G major", "Radiohead - Creep"),
        ("bbm", "Bb minor", "Muse - Hysteria"),  # the b after the letter is a flat
        ("la menor", "A minor", "Soda Stereo - De Música Ligera"),
    ],
)
def test_cli_search_by_key_takes_the_key_in_lowercase(tmp_path, typed, heading, song):
    conn = seed_keys(tmp_path)
    keep_sheet(conn, tmp_path / "lib", add_song(conn, "Muse", "Hysteria"), "Words\n",
               raw={"tonality_name": "Bbm"}, tab_id=3)
    result = run(tmp_path, "search", "--key", typed)
    assert result.exit_code == 0, result.output
    assert f"In your library, in {heading}" in result.output
    assert f"  [UG] {song} · found · Key {heading}" in result.output


def test_cli_search_by_key_says_when_limit_cuts_the_list(tmp_path):
    conn = seed_keys(tmp_path)
    for tab_id, title in enumerate(("Airbag", "Bones", "Climbing Up the Walls"), start=10):
        keep_sheet(conn, tmp_path / "lib", add_song(conn, "Radiohead", title), "Words\n",
                   raw={"tonality_name": "G"}, tab_id=tab_id)
    result = run(tmp_path, "search", "--key", "G", "--limit", "2")
    assert result.exit_code == 0, result.output
    assert "Radiohead - Airbag" in result.output and "Radiohead - Bones" in result.output
    assert "Climbing" not in result.output and "Creep" not in result.output
    assert "  … and 2 more: see them with --limit 4" in result.output
    result = run(tmp_path, "search", "--key", "G", "--limit", "4")
    assert result.exit_code == 0, result.output
    assert "Radiohead - Creep" in result.output and "more" not in result.output


def test_cli_search_key_that_is_no_key_is_a_usage_error(tmp_path):
    seed_keys(tmp_path)
    result = run(tmp_path, "search", "--key", "Hm7")
    assert result.exit_code == 2
    assert "is not a key" in result.output


def test_cli_search_key_with_add_is_a_usage_error(tmp_path):
    seed_keys(tmp_path)
    result = run(tmp_path, "search", "creep", "--key", "G", "--add", "1")
    assert result.exit_code == 2
    assert "--add" in result.output and "--key" in result.output
    assert not (tmp_path / "lib" / "wanted.txt").exists()


def test_cli_search_needs_words_or_a_key(tmp_path):
    seed_keys(tmp_path)
    result = run(tmp_path, "search")
    assert result.exit_code == 2
    assert "nothing to search for" in result.output


# --- names that aren't quite UG's ------------------------------------------------------------

EPIC = (4742072, "misc-musicals", "epic-the-musical-not-sorry-for-loving-you", "chords")
NEAR_EPIC = (1066803, "bill-fox", "im-not-over-loving-you", "chords")


def epic_review(conn):
    """The matcher's review of "epic - I'm not sorry for loving you": a catch-all artist's song first."""
    s = add_song(conn, "epic", "I'm not sorry for loving you")
    update_song(conn, s.id, review=True, match_decision="review", match_step="catch_all", match_score=94.1,
                match_artist_key="misc-musicals", match_song_key=EPIC[2], match_candidates=[
                    {"artist_key": "misc-musicals", "song_key": EPIC[2], "score": 94.1, "step": "catch_all"},
                    {"artist_key": "bill-fox", "song_key": NEAR_EPIC[2], "score": 81.6, "step": "title_only"},
                    *({"artist_key": f"cover-{i}", "song_key": "for-loving-you", "score": 76.0, "step": "title_only"}
                      for i in range(3))])
    return s


def test_cli_shows_a_reviews_first_candidates_under_its_song(tmp_path):
    epic_review(seed(tmp_path, rows=ROWS + [EPIC, NEAR_EPIC]))
    result = run(tmp_path, "search", "epic")
    assert result.exit_code == 0, result.output
    library = result.output.partition("On Ultimate Guitar (offline index)")[0]
    assert ("  epic - I'm not sorry for loving you · wanted, needs review · no folder yet\n"
            "     Did you mean (`caracole review` settles it):\n"
            "       94  misc-musicals/epic-the-musical-not-sorry-for-loving-you (catch_all)\n"
            "       82  bill-fox/im-not-over-loving-you (title_only)\n"
            "       76  cover-0/for-loving-you (title_only)\n") in library
    assert "cover-1" not in library  # three at most: `caracole review` and the to-do page have them all


def test_cli_a_review_with_a_sheet_from_elsewhere_keeps_its_tag_and_its_candidates(tmp_path):
    conn = seed(tmp_path, rows=ROWS + [EPIC, NEAR_EPIC])
    s = epic_review(conn)
    lc = upsert_version(conn, provider="lacuerda", tab_id="epic/not_sorry", song_id=s.id, slot="sheet",
                        kind="acordes", rating=0, votes=0, version=1, label=None,
                        url="https://acordes.lacuerda.net/epic/not_sorry.shtml", raw={}, now="x")
    keep_file(conn, tmp_path / "lib", song=s, version_id=lc, name="sheet.txt", data=b"LaCuerda's\n", rank=1)
    update_song(conn, s.id, status="found")
    result = run(tmp_path, "search", "epic")
    assert result.exit_code == 0, result.output
    library = result.output.partition("On Ultimate Guitar (offline index)")[0]
    assert "\n  [LaCuerda] epic - I'm not sorry for loving you · found · " in library
    assert ("     Did you mean (`caracole review` settles it):\n"
            "       94  misc-musicals/epic-the-musical-not-sorry-for-loving-you (catch_all)\n") in library


def test_cli_says_a_hit_is_under_ugs_catch_all_artist(tmp_path):
    seed(tmp_path, rows=ROWS + [EPIC, NEAR_EPIC])
    result = run(tmp_path, "search", "epic", "not", "sorry", "for", "loving", "you")
    assert result.exit_code == 0, result.output
    ug = result.output.partition("On Ultimate Guitar (offline index)")[2]
    first, second = ug.split("\n  2. ", 1)
    assert "1. [UG] Misc Musicals - Epic The Musical Not Sorry For Loving You" in first
    # Added under UG's names, the song's artist would be "Misc Musicals": no line to paste does that.
    assert 'caracole add "Misc Musicals"' not in first
    assert ("misc-musicals is UG's catch-all artist, no one's name: add the song as you know it, then pick "
            "this hit in `caracole review`:") in " ".join(first.split())
    assert '\n       caracole add "<the show or singer>" "<the song>"\n' in first + "\n"
    assert "catch-all" not in second and 'caracole add "Bill Fox"' in second


def test_cli_add_refuses_a_catch_all_hit_and_says_how_to_add_the_song(tmp_path):
    conn = seed(tmp_path, rows=ROWS + [EPIC, NEAR_EPIC])
    result = run(tmp_path, "search", "epic", "not", "sorry", "for", "loving", "you", "--add", "1")
    assert result.exit_code == 2, result.output
    out = " ".join(result.output.split())
    assert "misc-musicals is UG's catch-all artist, no one's name" in out
    assert 'caracole add "<the show or singer>" "<the song>"' in out
    assert "misc-musicals/epic-the-musical-not-sorry-for-loving-you in `caracole review`" in out
    assert not (tmp_path / "lib" / "wanted.txt").exists()
    assert find_song(conn, "misc-musicals/epic-the-musical-not-sorry-for-loving-you") is None


def test_a_catch_all_hit_is_scored_on_its_title_alone(conn):
    # misc-musicals is no one's name: the query is the show's name and the song's, both in UG's title.
    index(conn, ROWS + [EPIC, NEAR_EPIC, (77, "misc-musicals", "hamilton-my-shot", "chords")])
    for query in ("epic not sorry for loving you", "EPIC the musical - Not Sorry for Loving You"):
        hits = search_index(conn, query)
        assert keys(hits)[0] == ("misc-musicals", EPIC[2]) and hits[0].score >= 95, (query, hits)
        assert bare_id_hint(query, hits) is None  # a strong hit: no word of artists UG can't see
    assert keys(search_index(conn, "hamilton my shot"))[0] == ("misc-musicals", "hamilton-my-shot")


# --- an artist alone, or a title alone ----------------------------------------------------------

# The band Wonderwall, Oasis and a song titled Oasis, a mashup filed under misc-mashups, and two keys
# that hold the letters of "ban ma" inside words: noise for 斑马.
EITHER = ROWS + PINYIN_ROWS + [
    (20001, "wonderwall", "in-april", "chords"), (20002, "wonderwall", "in-april", "tabs"),
    (20011, "oasis", "wonderwall", "chords"), (20012, "oasis", "wonderwall", "chords"),
    (20013, "oasis", "wonderwall", "tabs"), (20014, "oasis", "live-forever", "chords"),
    (20021, "ryan-adams", "wonderwall", "chords"),
    (20031, "misc-mashups", "oasis-wonderwall", "chords"),
    (20041, "frenzal-rhomb", "suburban-male", "chords"),
    (20051, "band-maid", "thrill", "chords"),
]


def test_each_hit_says_which_reading_of_the_query_it_answers(conn):
    index(conn, EITHER)
    creep = search_index(conn, "creep")
    assert [(h.song_key, h.via) for h in creep[:2]] == [("creep", "title"), ("creep", "title")]
    assert ("creeping-death", "title") in [(h.song_key, h.via) for h in creep]  # a part of the title
    assert [h.via for h in search_index(conn, "radiohead creep")][:1] == ["both"]
    assert {(h.song_key, h.via) for h in search_index(conn, "radiohead")} == {
        ("creep", "artist"), ("karma-police", "artist")}
    assert [h.score for h in creep[:3]] == [100, 100, 90]  # the scores are what they were


def test_an_artist_alone_gives_the_artist_with_its_songs_and_tabs_counted(conn):
    from caracole.search import find_index

    index(conn, EITHER)
    found = find_index(conn, "oasis")
    [oasis] = found.artists
    assert (oasis.artist_key, oasis.artist, oasis.score, oasis.songs, oasis.tabs) == ("oasis", "Oasis", 100, 2, 4)
    assert [h.song_key for h in oasis.top] == ["wonderwall", "live-forever"]  # the most tabbed first
    assert dict(oasis.top[0].counts) == {"chords": 2, "tabs": 1}
    # Its songs are in its row: what is left is songs with the word in their title.
    assert [(h.artist_key, h.song_key, h.via) for h in found.songs] == [
        ("misc-mashups", "oasis-wonderwall", "title")]
    assert found.lead == "artist"


def test_a_title_alone_lists_that_title_by_every_artist_before_an_artist_of_that_name(conn):
    from caracole.search import find_index

    index(conn, EITHER)
    found = find_index(conn, "wonderwall")
    assert [(h.artist_key, h.song_key) for h in found.songs] == [
        ("oasis", "wonderwall"), ("ryan-adams", "wonderwall"), ("misc-mashups", "oasis-wonderwall")]
    assert [h.via for h in found.songs] == ["title", "title", "title"]
    # The band Wonderwall is an artist row, its song in it, not a song between the others.
    [band] = found.artists
    assert (band.artist_key, band.songs, band.tabs, [h.song_key for h in band.top]) == (
        "wonderwall", 1, 2, ["in-april"])
    assert found.lead == "song" and found.best.song_key == "wonderwall" and found.best.artist_key == "oasis"


def test_an_artist_with_more_tabbed_songs_leads_songs_titled_like_it(conn):
    from caracole.search import find_index

    index(conn, EITHER + [(20061, "a-great-big-world", "oasis", "chords")])
    found = find_index(conn, "oasis")
    assert found.lead == "artist" and found.best is None  # Enter shows the artist, it looks nothing up
    assert [(h.artist_key, h.score, h.via) for h in found.songs][:1] == [("a-great-big-world", 100, "title")]
    index(conn, [(20062 + i, "a-great-big-world", "oasis", "tabs") for i in range(4)])
    found = find_index(conn, "oasis")  # now the song titled Oasis has more tabs than Oasis's best one
    assert found.lead == "song" and found.best.artist_key == "a-great-big-world"


def test_artist_songs_lists_every_song_most_tabbed_first_variants_with_their_song(conn):
    from caracole.search import artist_songs

    index(conn, EITHER)
    hits, total = artist_songs(conn, "radiohead")
    assert total == 2 and [h.song_key for h in hits] == ["creep", "karma-police"]
    assert dict(hits[0].counts) == {"chords": 3, "tabs": 2, "guitar-pro": 1} and hits[0].labels == ("acoustic",)
    assert (hits[0].artist, hits[0].title) == ("Radiohead", "Creep")
    assert [h.song_key for h in artist_songs(conn, "radiohead", limit=1)[0]] == ["creep"]
    assert [h.song_key for h in artist_songs(conn, "radiohead", limit=1, offset=1)[0]] == ["karma-police"]
    assert artist_songs(conn, "nobody-at-all") == ([], 0)


def test_artist_songs_can_be_narrowed_to_titles(conn):
    from caracole.search import artist_songs

    index(conn, EITHER)
    hits, total = artist_songs(conn, "oasis", title="live")
    assert (total, [h.song_key for h in hits]) == (1, ["live-forever"])


def test_a_catch_all_is_never_an_artist_row(conn):
    from caracole.search import find_index

    index(conn, EITHER + [EPIC, (77, "misc-musicals", "hamilton-my-shot", "chords")])
    for query in ("misc musicals", "misc mashups"):
        found = find_index(conn, query)
        assert found.artists == () and found.lead != "artist", query


def test_pinyin_never_matches_inside_a_word(conn):
    # "斑马" is ban ma: in suburban-male and band-maid only inside words, never as words of their own.
    index(conn, EITHER)
    assert keys(search_index(conn, "斑马")) == [("song-dongye", "ban-ma-ban-ma")]
    add_song(conn, "Frenzal Rhomb", "Suburban Male")
    add_song(conn, "宋冬野", "斑马，斑马")
    assert [h.song.artist for h in search_library(conn, "斑马")] == ["宋冬野"]


def test_a_pinyin_match_of_part_of_a_name_is_never_strong(conn):
    # Short syllables are no proof: a part of a title in pinyin is a hit, never the song Enter takes.
    from caracole.search import find_index

    index(conn, EITHER + [(20071, "anju-panta", "banma-phulyo", "chords")])
    found = find_index(conn, "斑马")
    assert {h.song_key for h in found.songs} == {"ban-ma-ban-ma", "banma-phulyo"}
    assert all(h.score < 90 for h in found.songs) and found.best is None
    assert find_index(conn, "斑马，斑马").best.song_key == "ban-ma-ban-ma"  # the whole title is


def test_a_chinese_artist_alone_is_an_artist_row_however_ug_hyphenates_it(conn):
    from caracole.search import find_index

    index(conn, EITHER)
    [artist] = find_index(conn, "宋冬野").artists
    assert (artist.artist_key, artist.songs, artist.artist) == ("song-dongye", 1, "Song Dongye")


def test_best_is_none_for_a_weak_hit_and_when_an_artist_leads(conn):
    from caracole.search import find_index

    index(conn, EITHER)
    assert find_index(conn, "creep").best.artist_key == "radiohead"
    assert find_index(conn, "radiohead").best is None
    weak = find_index(conn, "police karma")
    assert weak.songs and all(h.score < 90 for h in weak.songs) and weak.best is None
    nothing = find_index(conn, "zzzz qqqq")
    assert (nothing.artists, nothing.songs, nothing.lead, nothing.best) == ((), (), None, None)


def test_library_hits_say_their_reading_too(conn):
    add_song(conn, "Radiohead", "Creep")
    add_song(conn, "Oasis", "Wonderwall")
    assert [(h.song.title, h.via) for h in search_library(conn, "creep")] == [("Creep", "title")]
    assert [(h.song.title, h.via) for h in search_library(conn, "radiohead")] == [("Creep", "artist")]
    assert [(h.song.title, h.via) for h in search_library(conn, "radiohead creep")] == [("Creep", "both")]


def test_find_takes_your_song_before_an_artist_and_never_one_read_as_its_artist(conn):
    from caracole.search import find

    index(conn, EITHER)
    add_song(conn, "Oasis", "Wonderwall")
    found = find(conn, "wonderwall")
    assert [h.song.title for h in found.library] == ["Wonderwall"]
    assert found.best is found.library[0]  # yours, which costs no request
    by_artist = find(conn, "oasis")
    assert by_artist.library[0].via == "artist" and by_artist.best is None and by_artist.lead == "artist"


def test_a_hint_for_a_bare_query_reads_it_as_an_artist_or_a_title():
    hint = bare_id_hint("斑马斑马", [])
    assert "If 斑马斑马 is the artist's name" in hint and '"斑马斑马" = "https://www.ultimate-guitar.com/artist/' in hint
    assert 'If 斑马斑马 is a title, caracole needs its artist too: `caracole add ARTIST "斑马斑马"`' in hint
    as_artist = bare_id_hint("斑马斑马", [], artist="斑马斑马")  # caracole search --artist
    assert "Find the artist's page" in as_artist and "is a title" not in as_artist
    assert "is a title" not in bare_id_hint("宋冬野 斑马", [], artist="宋冬野")  # the artist is known


def _score_before_readings(q: str, artist: str, title: str) -> float:
    """``_Query.score`` as it was before it was split into readings."""
    from rapidfuzz import fuzz

    full = f"{artist} {title}"
    best = max(fuzz.ratio(q, title), fuzz.ratio(q, artist), fuzz.token_sort_ratio(q, full))
    if len(q) < len(full):
        best = max(best, 0.9 * fuzz.partial_ratio(q, full))
    qc, a, t = q.replace(" ", ""), artist.replace(" ", ""), title.replace(" ", "")
    best = max(best, fuzz.ratio(qc, t), fuzz.ratio(qc, a), fuzz.ratio(qc, a + t))
    if len(qc) < len(a) + len(t):
        best = max(best, 0.9 * fuzz.partial_ratio(qc, a + t))
    return best


def test_the_readings_split_the_score_a_query_always_had():
    from caracole.search import _Query

    names = [("radiohead", "creep"), ("metallica", "creeping death"), ("soda stereo", "de musica ligera"),
             ("oasis", "wonderwall"), ("wonderwall", "in april"), ("misc mashups", "oasis wonderwall"),
             ("", "epic the musical not sorry for loving you"), ("acdc", "highway to hell"), ("r e m", "losing")]
    for query in ("creep", "radiohead", "radiohead creep", "creep radiohed", "musica", "oasis wonderwall",
                  "wonderwall", "ac dc", "epic not sorry", "rem losing", "in april wonderwall", "x"):
        q = _Query(query)
        for artist, title in names:
            assert max(q.readings(artist, title)) == q.score(artist, title) == pytest.approx(
                _score_before_readings(query, artist, title)), (query, artist, title)


def test_a_catch_alls_song_is_never_what_enter_takes(conn):
    # Added under UG's names, its artist would be "Misc Musicals": the song is to be added as you know it.
    from caracole.search import find_index

    index(conn, ROWS + [EPIC, NEAR_EPIC])
    found = find_index(conn, "epic not sorry for loving you")
    assert found.songs[0].artist_key == "misc-musicals" and found.songs[0].score >= 90
    assert found.lead == "song" and found.best is None


# --- caracole search: an artist alone, a title alone, --artist and --title ----------------------


def ug_part(output: str) -> str:
    return output.partition("On Ultimate Guitar (offline index)")[2]


def test_cli_an_artist_alone_says_how_many_songs_it_has_and_lists_the_most_tabbed(tmp_path):
    seed(tmp_path, rows=EITHER)
    result = run(tmp_path, "search", "oasis")
    assert result.exit_code == 0, result.output
    ug = ug_part(result.output)
    assert "  Oasis, an artist: 2 songs (4 tabs). The most tabbed:\n  1. [UG] Oasis - Wonderwall · chords×2 tabs×1" in ug
    assert "  2. [UG] Oasis - Live Forever · chords×1" in ug
    assert "caracole search --artist" not in ug  # both of its songs are shown
    # Then the songs with the word in their title, numbered on.
    assert ug.index("Live Forever") < ug.index("Songs titled like oasis") < ug.index("3. [UG] Misc Mashups - Oasis Wonderwall")


def test_cli_an_artist_with_more_songs_than_shown_says_how_to_list_them_all(tmp_path):
    many = [(30000 + i, "oasis", f"song-{i:02d}", "chords") for i in range(5)]
    seed(tmp_path, rows=EITHER + many)
    ug = ug_part(run(tmp_path, "search", "oasis").output)
    assert "Oasis, an artist: 7 songs (9 tabs). The most tabbed:" in ug
    assert "  2. [UG] Oasis - Live Forever" in ug and "  3. [UG] Oasis - Song 00" in ug  # its three most tabbed
    assert "Song 01" not in ug
    assert '     All 7: caracole search --artist "Oasis"\n' in ug


def test_cli_a_title_alone_lists_the_songs_and_says_it_is_an_artist_too(tmp_path):
    seed(tmp_path, rows=EITHER)
    result = run(tmp_path, "search", "wonderwall")
    assert result.exit_code == 0, result.output
    ug = ug_part(result.output)
    assert "  1. [UG] Oasis - Wonderwall" in ug and "  2. [UG] Ryan Adams - Wonderwall" in ug
    assert "In April" not in ug  # the band Wonderwall's song is in its own line, not between the others
    assert ('  Also an artist: Wonderwall, 1 song (2 tabs)\n'
            '     caracole search --artist "Wonderwall"\n') in ug


def test_cli_add_numbers_what_the_search_printed(tmp_path):
    seed(tmp_path, rows=EITHER + [(20061, "a-great-big-world", "oasis", "chords")])
    ug = ug_part(run(tmp_path, "search", "oasis").output)
    assert "  3. [UG] A Great Big World - Oasis" in ug
    result = run(tmp_path, "search", "oasis", "--add", "3")
    assert result.exit_code == 0, result.output
    assert (tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8").endswith("\nA Great Big World - Oasis\n")


def test_cli_search_artist_lists_its_songs_with_limit_and_add(tmp_path):
    conn = seed(tmp_path, rows=EITHER)
    add_song(conn, "Oasis", "Wonderwall")
    result = run(tmp_path, "search", "--artist", "oasis")
    assert result.exit_code == 0, result.output
    library, ug = result.output.split("On Ultimate Guitar (offline index)")
    assert "Oasis - Wonderwall" in library and "Radiohead" not in library  # yours by them, first
    assert "  Oasis: 2 songs (4 tabs), the most tabbed first:\n  1. [UG] Oasis - Wonderwall" in ug
    assert "  2. [UG] Oasis - Live Forever" in ug and "Misc Mashups" not in ug and "Ryan Adams" not in ug
    cut = ug_part(run(tmp_path, "search", "--artist", "oasis", "--limit", "1").output)
    assert "  1. [UG] Oasis - Wonderwall" in cut and "2. " not in cut
    assert "  … and 1 more: see them with --limit 2" in cut
    narrowed = ug_part(run(tmp_path, "search", "--artist", "oasis", "live").output)  # words: its titles
    assert "  1. [UG] Oasis - Live Forever" in narrowed and "Wonderwall" not in narrowed
    added = run(tmp_path, "search", "--artist", "oasis", "--add", "2")
    assert added.exit_code == 0, added.output
    assert (tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8").endswith("\nOasis - Live Forever\n")


def test_cli_search_artist_the_index_lacks_lists_yours_and_hints_with_its_name(tmp_path):
    conn = seed(tmp_path, rows=ROWS)
    add_song(conn, "宋冬野", "斑马，斑马")
    result = run(tmp_path, "search", "--artist", "宋冬野")
    assert result.exit_code == 0, result.output
    library, ug = result.output.split("On Ultimate Guitar (offline index)")
    assert "宋冬野 - 斑马，斑马" in library
    assert "No artist named 宋冬野 in the offline index" in ug
    out = " ".join(ug.split())
    assert "Find the artist's page" in out and '"宋冬野" = "https://www.ultimate-guitar.com/artist/' in out
    assert "is a title" not in out


def test_cli_search_title_lists_that_title_by_any_artist(tmp_path):
    seed(tmp_path, rows=EITHER)
    result = run(tmp_path, "search", "--title", "wonderwall")
    assert result.exit_code == 0, result.output
    ug = ug_part(result.output)
    assert "  1. [UG] Oasis - Wonderwall" in ug and "  2. [UG] Ryan Adams - Wonderwall" in ug
    assert "Also an artist" not in ug and "In April" not in ug
    radiohead = ug_part(run(tmp_path, "search", "--title", "radiohead").output)
    assert "Creep" not in radiohead  # the artist's name is no title


@pytest.mark.parametrize("args", [
    ("--title", "creep", "radiohead"),  # --title is the title: no other words
    ("--key", "Am", "--artist", "radiohead"),
    ("--key", "Am", "--title", "creep"),
    ("--artist", " "),
])
def test_cli_title_with_a_query_and_key_with_a_name_are_usage_errors(tmp_path, args):
    seed(tmp_path, rows=EITHER)
    result = run(tmp_path, "search", *args)
    assert result.exit_code == 2, result.output


def test_cli_hint_never_keys_a_line_by_a_placeholder_artist(tmp_path):
    # The owner's wanted.txt has "misc - 斑马": the song's artist is no one's name, so the query is.
    conn = seed(tmp_path, rows=ROWS)
    add_song(conn, "misc", "斑马")
    out = " ".join(run(tmp_path, "search", "斑马").output.split())
    assert '"misc" = ' not in out
    assert '"斑马" = "https://www.ultimate-guitar.com/artist/' in out
    assert 'If 斑马 is a title, caracole needs its artist too: `caracole add ARTIST "斑马"`' in out


def test_a_song_of_yours_under_a_placeholder_artist_is_never_what_enter_takes(conn):
    # The owner's "misc - 斑马": looked up under "misc", it can't be found, so Enter would spend requests on it.
    from caracole.search import find

    index(conn, EITHER)
    add_song(conn, "misc", "斑马")
    answer = find(conn, "斑马")
    assert [h.song.artist for h in answer.library] == ["misc"] and answer.library[0].score >= 90
    assert answer.best is None  # and the index's partial pinyin match is no clear song either
