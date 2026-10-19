import random
import socket
import sqlite3
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tabarr import db
from tabarr.cli import build_app
from tabarr.search import bare_id_hint, display_from_keys, search_index, search_library
from tabarr.songs import find_song, update_song

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
    assert '"宋冬野" = "https://www.ultimate-guitar.com/artist/<name>_<id>"' in bare_id_hint(
        "宋冬野 斑马", [], artist="宋冬野")
    assert '"Joaquín Sabina" = "https://www.ultimate-guitar.com/artist/' in bare_id_hint("Joaquín Sabina", [])


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


# --- tabarr search -----------------------------------------------------------------


def config(tmp_path: Path) -> Path:
    p = tmp_path / "tabarr.toml"
    p.write_text(
        f'library_dir = "{tmp_path / "lib"}"\nmusic_dir = "{tmp_path / "music"}"\n'
        f'state_dir = "{tmp_path / "state"}"\ncache_dir = "{tmp_path / "cache"}"\n',
        encoding="utf-8",
    )
    return p


def run(tmp_path, *args):
    return CliRunner().invoke(build_app(), ["--config", str(config(tmp_path)), *args])


def seed(tmp_path, rows=ROWS):
    conn = db.connect(tmp_path / "state" / "tabarr.sqlite")
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
    assert "1. Radiohead - Creep" in ug
    assert "chords×3 tabs×2 guitar-pro×1" in ug
    assert "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169" in ug
    assert "2. Stone Temple Pilots - Creep" in ug
    assert 'tabarr add "Stone Temple Pilots" "Creep"' in ug


def test_cli_add_appends_the_hit_to_wanted_and_syncs(tmp_path):
    conn = seed(tmp_path)
    result = run(tmp_path, "search", "creep", "--add", "2")
    assert result.exit_code == 0, result.output
    wanted = (tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8")
    assert "Stone Temple Pilots - Creep" in wanted
    song = find_song(conn, "stone-temple-pilots/creep")
    assert song is not None and "wanted" in song.source_ids
    assert "Stone Temple Pilots - Creep" in result.output and "wanted.txt" in result.output


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


def test_cli_add_keeps_the_line_when_the_database_cannot_be_updated(tmp_path, monkeypatch):
    seed(tmp_path)

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("tabarr.wanted.sync_wanted", locked)
    result = run(tmp_path, "search", "creep", "--add", "2")
    assert result.exit_code == 0, result.output
    wanted = (tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8")
    assert wanted.endswith("\nStone Temple Pilots - Creep\n")  # the file is the source of truth
    assert "The database couldn't be updated (database is locked)" in result.output
    assert "`tabarr sync`" in result.output


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


def test_cli_empty_index_says_how_to_build_it(tmp_path):
    seed(tmp_path, rows=[])
    result = run(tmp_path, "search", "creep")
    assert result.exit_code == 0, result.output
    assert "tabarr index build" in result.output


def test_cli_never_touches_the_network(tmp_path, monkeypatch):
    seed(tmp_path)

    def no_network(*args, **kwargs):
        raise AssertionError("tabarr search made a network call")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    result = run(tmp_path, "search", "creep", "--add", "1")
    assert result.exit_code == 0, result.output
