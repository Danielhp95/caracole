"""LaCuerda's artist index: its listings read into lacuerda_index, resumed across runs, and searched.

LaCuerda has no sitemap. Its listings of every artist, a letter at a time and 100 artists a
page, are played by ``LaCuerdaSite`` (helpers/lacuerda_site.py) behind a real ``PoliteClient``,
in the shape of the page captured on 20 October 2026; the budget, the cache and the
conditional requests are the client's real behaviour.
"""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from helpers.lacuerda_site import BASE, NOW, LaCuerdaSite, artist_page, fixture

from caracole import lacuerda_index as li
from caracole import normalize
from caracole.db import kv_get, kv_set
from caracole.http import BudgetExhausted, ProviderBlocked, ProviderError
from caracole.lacuerda import LETTERS, LCArtist, LCSong, listing_path, listing_url

FIRST_PAGES = [listing_url(listing_path(letter)) for letter in LETTERS]
E1 = [("ebenezer", "Ebenezer", 268), ("ecos", "Los Ecos", 5), ("enanitos", "Enanitos Verdes", 151)]
E2 = [("estopa", "Estopa", 159), ("extremoduro", "Extremoduro", 112)]
S1 = [("sabina", "Sabina y Fito", 1), ("soda_stereo", "Soda Stereo", 89)]
E_PAGES = [f"{BASE}/tabs/e/index0.html", f"{BASE}/tabs/e/index100.html"]


def site_with(**letters) -> LaCuerdaSite:
    site = LaCuerdaSite()
    for letter, pages in letters.items():
        site.letter(letter, *pages)
    return site


def refresh(site, conn, tmp_path, now=NOW, *, budget=100, on_read=lambda: None):
    client = site.client(tmp_path / "cache", budget=budget, now=now)
    try:
        li.refresh(conn, client, now, on_read=on_read)
    finally:
        client.close()
    return client


def artists(conn) -> dict[str, tuple[str, str, int, str]]:
    """Each artist row by slug: its name, key, songs and the listing page it came from."""
    return {r[0]: tuple(r[1:]) for r in conn.execute(
        "SELECT artist_slug, artist, artist_key, songs, page FROM lacuerda_index WHERE title = ''")}


def songs_of(conn, slug) -> list[str]:
    return sorted(r[0] for r in conn.execute(
        "SELECT title FROM lacuerda_index WHERE artist_slug = ? AND title != ''", (slug,)))


# --- the refresh ---------------------------------------------------------------------------


def test_a_first_refresh_reads_every_page_of_every_letter(conn, tmp_path):
    site = site_with(e=[E1, E2], s=[S1])
    read = []
    refresh(site, conn, tmp_path, on_read=lambda: read.append(1))
    # A letter's first page, then the others it links; a letter LaCuerda has no listing for answers 404.
    expected = FIRST_PAGES[:6] + [E_PAGES[1]] + FIRST_PAGES[6:]
    assert site.requests == expected
    assert len(read) == 3  # the three pages with artists
    assert artists(conn) == {
        "ebenezer": ("Ebenezer", "ebenezer", 268, "tabs/e/index0.html"),
        "ecos": ("Los Ecos", "ecos", 5, "tabs/e/index0.html"),
        "enanitos": ("Enanitos Verdes", "enanitos-verdes", 151, "tabs/e/index0.html"),
        "estopa": ("Estopa", "estopa", 159, "tabs/e/index100.html"),
        "extremoduro": ("Extremoduro", "extremoduro", 112, "tabs/e/index100.html"),
        "sabina": ("Sabina y Fito", "sabina-fito", 1, "tabs/s/index0.html"),
        "soda_stereo": ("Soda Stereo", "soda-stereo", 89, "tabs/s/index0.html"),
    }
    assert li.complete_at(conn) == NOW
    assert li.index_size(conn) == (7, 0)


def test_the_listings_are_asked_again_after_30_days_with_conditional_requests(conn, tmp_path):
    site = site_with(e=[E1, E2], s=[S1])
    refresh(site, conn, tmp_path)
    site.requests.clear()
    refresh(site, conn, tmp_path, NOW + timedelta(days=29))
    assert site.requests == []

    read = []
    later = NOW + timedelta(days=31)
    refresh(site, conn, tmp_path, later, on_read=lambda: read.append(1))
    assert len(site.requests) == 29
    # Unchanged since: each answered 304, and nothing was parsed again.
    assert site.conditional == [*E_PAGES, f"{BASE}/tabs/s/index0.html"]
    assert read == []
    assert len(artists(conn)) == 7
    assert li.complete_at(conn) == later


def test_a_spent_budget_leaves_the_rest_for_the_next_run_which_goes_on_where_it_stopped(conn, tmp_path):
    site = site_with(e=[E1, E2], s=[S1])
    with pytest.raises(BudgetExhausted):
        refresh(site, conn, tmp_path, budget=6)
    assert site.requests == FIRST_PAGES[:6]  # e's first page is read, its second waits
    assert set(artists(conn)) == {"ebenezer", "ecos", "enanitos"}
    assert li.complete_at(conn) is None

    site.requests.clear()
    refresh(site, conn, tmp_path, NOW + timedelta(hours=24))
    assert site.requests == [E_PAGES[1], *FIRST_PAGES[6:]]
    assert len(artists(conn)) == 7
    assert li.complete_at(conn) == NOW + timedelta(hours=24)


def test_index_pass_counts_the_pages_read_and_a_spent_budget(conn, tmp_path):
    site = site_with(e=[E1, E2], s=[S1])
    client = site.client(tmp_path / "cache", budget=6)
    assert li.index_pass(conn, client, NOW) == li.IndexStats(pages=1, budget_exhausted=True)
    client = site.client(tmp_path / "cache")
    assert li.index_pass(conn, client, NOW) == li.IndexStats(pages=2)
    assert li.index_pass(conn, client, NOW) == li.IndexStats()  # nothing is due


def test_a_block_propagates_and_keeps_the_index(conn, tmp_path):
    site = site_with(e=[E1, E2], s=[S1])
    refresh(site, conn, tmp_path)
    site.status = 403
    with pytest.raises(ProviderBlocked):
        refresh(site, conn, tmp_path, NOW + timedelta(days=31))
    with pytest.raises(ProviderBlocked):
        li.index_pass(conn, site.client(tmp_path / "cache"), NOW + timedelta(days=31))
    assert len(artists(conn)) == 7
    assert li.complete_at(conn) == NOW


def test_a_page_that_wont_parse_is_an_error_and_its_artists_stay(conn, tmp_path):
    site = site_with(e=[E1, E2], s=[S1])
    refresh(site, conn, tmp_path)
    site.pages[E_PAGES[0]] = (200, fixture("not_found.html"), {"Last-Modified": "Sat, 1 Nov 2026 00:00:00 GMT"})
    later = NOW + timedelta(days=31)
    with pytest.raises(ProviderError, match="i_main"):
        refresh(site, conn, tmp_path, later)
    assert li.index_pass(conn, site.client(tmp_path / "cache"), later) == li.IndexStats(errors=1)
    assert len(artists(conn)) == 7  # an error is never a letter without artists
    assert li.complete_at(conn) == NOW


def test_a_server_error_is_an_error(conn, tmp_path):
    site = site_with(e=[E1])
    site.status = 500
    assert li.index_pass(conn, site.client(tmp_path / "cache"), NOW) == li.IndexStats(errors=1)
    assert artists(conn) == {}


def test_a_changed_page_replaces_its_artists_and_a_page_no_longer_listed_leaves(conn, tmp_path):
    site = site_with(e=[E1, E2, [("ezio", "Ezio", 2)]], s=[S1])
    refresh(site, conn, tmp_path)
    assert "ezio" in artists(conn)
    site.pages.pop(f"{BASE}/tabs/e/index200.html")
    site.letter("e", [*E1, ("eskorbuto", "Eskorbuto", 101)], E2, modified="Sun, 1 Nov 2026 00:00:00 GMT")
    refresh(site, conn, tmp_path, NOW + timedelta(days=31))
    assert f"{BASE}/tabs/e/index200.html" not in site.requests[30:]
    assert set(artists(conn)) == {"ebenezer", "ecos", "enanitos", "eskorbuto", "estopa", "extremoduro",
                                  "sabina", "soda_stereo"}
    assert "tabs/e/index200.html" not in li.pages(conn)


def test_a_letter_whose_listing_is_gone_loses_its_artists(conn, tmp_path):
    site = site_with(e=[E1, E2], s=[S1])
    refresh(site, conn, tmp_path)
    for url in E_PAGES:
        site.pages.pop(url)
    refresh(site, conn, tmp_path, NOW + timedelta(days=31))
    assert set(artists(conn)) == {"sabina", "soda_stereo"}


def test_the_songs_of_an_artist_whose_page_is_cached_come_from_the_cache(conn, tmp_path):
    site = site_with(s=[S1])
    site.pages[f"{BASE}/soda_stereo/"] = (200, fixture("artist.html"), {})
    site.pages[f"{BASE}/sabina/"] = (200, "aqui llega:../tabs/s/sabina/index.html", {})
    warm = site.client(tmp_path / "cache")
    for url in (f"{BASE}/soda_stereo/", f"{BASE}/sabina/"):
        warm.get(url, accept=(200, 404))
    site.requests.clear()

    refresh(site, conn, tmp_path)

    assert site.requests == FIRST_PAGES  # no artist page was asked for
    assert len(songs_of(conn, "soda_stereo")) == 14
    assert songs_of(conn, "sabina") == []  # LaCuerda's "no such artist", cached
    row = conn.execute("SELECT artist, artist_key, title_key, versions, acordes, popular, page FROM lacuerda_index "
                       "WHERE path = 'soda_stereo/de_musica_ligera'").fetchone()
    assert tuple(row) == ("Soda Stereo", "soda-stereo", "de-musica-ligera", "RHRTTTDTB", 3, 0, "soda_stereo/")


def test_the_state_says_which_letters_a_search_finds_every_artist_of(conn, tmp_path):
    assert li.index_state(conn) == li.IndexState(0, 0, False, ())
    assert li.index_state(conn).empty
    site = site_with(e=[E1, E2], s=[S1])
    with pytest.raises(BudgetExhausted):
        refresh(site, conn, tmp_path, budget=6)  # #, A–D answer 404 (no listing), E's first page is read
    state = li.index_state(conn)
    assert (state.artists, state.complete, state.letters) == (3, False, ("_num", "a", "b", "c", "d"))
    assert not state.empty and li.letters_text(state.letters) == "#, A–D"  # E waits for its second page
    refresh(site, conn, tmp_path, NOW + timedelta(hours=24))
    state = li.index_state(conn)
    assert (state.artists, state.songs, state.complete) == (7, 0, True) and len(state.letters) == len(LETTERS)


def test_the_letter_a_name_would_be_listed_under_while_the_index_hasnt_read_it(conn, tmp_path):
    # While a letter isn't read whole, the index can't tell LaCuerda lacks an artist under it: their page can.
    assert li.unread_letter(conn, "Estopa") == "e"  # an empty index has read no letter
    site = site_with(e=[E1, E2], s=[S1])
    with pytest.raises(BudgetExhausted):
        refresh(site, conn, tmp_path, budget=6)  # #, A–D read whole, E in part
    assert li.unread_letter(conn, "Estopa") == "e"
    assert li.unread_letter(conn, "Caifanes") is None  # C is read whole: none there is none on LaCuerda
    assert li.unread_letter(conn, "4 Non Blondes") is None  # "#"
    assert li.unread_letter(conn, "The Beatles") == "t"  # beatles, then the_beatles: B is read, T isn't
    assert li.unread_letter(conn, "!!!") is None and li.unread_letter(conn, "宋冬野") is None  # no slug to try
    refresh(site, conn, tmp_path, NOW + timedelta(hours=24))
    assert li.unread_letter(conn, "Estopa") is None  # every letter read


def test_letters_are_named_as_lacuerdas_menu_names_them_runs_as_ranges():
    assert li.letters_text(["_num", "a", "b", "c"]) == "#, A–C"
    assert li.letters_text(["a", "b", "e"]) == "A, B, E"
    assert li.letters_text(["m", "n", "nn", "o", "z"]) == "M–O, Z"  # Ñ in its place, as LaCuerda lists it
    assert li.letters_text(["nn"]) == "Ñ" and li.letters_text([]) == ""


# --- what lacuerda_fetch reads --------------------------------------------------------------


def test_an_artist_page_puts_its_songs_in_the_index_in_place_of_those_it_gave_before(conn):
    html = fixture("artist.html")
    li.store_artist_page(conn, "soda_stereo", html)
    assert len(songs_of(conn, "soda_stereo")) == 14
    li.store_artist_page(conn, "soda_stereo", artist_page("Soda Stereo", "soda_stereo",
                                                        ("persiana_americana", "Persiana Americana", "R-1")))
    assert songs_of(conn, "soda_stereo") == ["Persiana Americana"]
    # The artist's name comes from the index's row when the page has no heading.
    li.store_artists(conn, "tabs/s/index0.html", [LCArtist("soda_stereo", "Soda Stereo", 89)])
    songs = [LCSong("signos", "Signos", "R", (1,))]
    li.store_songs(conn, "soda_stereo", None, songs)
    assert conn.execute("SELECT artist FROM lacuerda_index WHERE path = 'soda_stereo/signos'").fetchone()[0] == \
        "Soda Stereo"


def test_artist_slugs_names_the_index_slug_of_an_artist(conn):
    li.store_artists(conn, "tabs/e/index0.html", [LCArtist(s, n, c) for s, n, c in E1])
    assert li.artist_slugs(conn, "Enanitos Verdes") == ["enanitos"]
    assert li.artist_slugs(conn, "Los Enanitos Verdes") == ["enanitos"]
    assert li.artist_slugs(conn, "Ecos") == ["ecos"]
    assert li.artist_slugs(conn, "Nobody") == []
    # A name in two scripts meets the listing's by each of its parts (normalize.name_forms).
    li.store_artists(conn, "tabs/s/index0.html", [LCArtist("song_dongye", "宋冬野", 4)])
    assert li.artist_slugs(conn, "Song Dongye (宋冬野)") == ["song_dongye"]


# --- keys ------------------------------------------------------------------------------------


def test_keys_are_identity_keys_and_chinese_is_pinyin():
    assert li.name_key("Los Enanitos Verdes") == "enanitos-verdes"
    assert li.name_key("Fito y Fitipaldis") == "fito-fitipaldis"
    assert li.name_key("Joaquín Sabina") == "joaquin-sabina"
    assert li.name_key("宋冬野") == "song-dong-ye"
    assert li.title_key("Té para tres (En Vivo)") == "te-para-3"
    assert li.title_key("斑馬斑馬") == "ban-ma-ban-ma"


def test_rows_made_with_older_keys_are_made_again_from_their_names(conn, monkeypatch):
    li.store_artists(conn, "tabs/e/index0.html", [LCArtist("ecos", "Los Ecos", 5)])
    conn.execute("UPDATE lacuerda_index SET artist_key = 'los-ecos'")
    kv_set(conn, li.KEYS_KEY, "0")
    assert li.ensure_current_keys(conn) == 1
    assert artists(conn)["ecos"][1] == "ecos"
    assert kv_get(conn, li.KEYS_KEY) == str(normalize.KEY_VERSION)
    assert li.ensure_current_keys(conn) == 0


# --- searching -------------------------------------------------------------------------------


@pytest.fixture
def index(conn):
    li.store_artists(conn, "tabs/e/index0.html", [LCArtist(s, n, c) for s, n, c in [*E1, *E2]] + [
        LCArtist("ego", "E.G.O.", 3), LCArtist("ecos_del_rocio", "Ecos del Rocío", 13)])
    li.store_artists(conn, "tabs/j/index0.html", [LCArtist("joaquin_sabina", "Joaquín Sabina", 241)])
    li.store_artists(conn, "tabs/s/index0.html", [LCArtist(s, n, c) for s, n, c in S1] + [
        LCArtist("song_dongye", "宋冬野", 4)])
    li.store_artist_page(conn, "soda_stereo", fixture("artist.html"))
    li.store_artist_page(conn, "estopa", artist_page(
        "Estopa", "estopa", ("como_camaron", "Como Camarón", "RRT-213"), ("tu_calorro", "Tu Calorro", "R-1"),
        ("vino_tinto", "Vino Tinto", "T-1")))
    return conn


def test_estopa_finds_the_artist(index):
    found = li.find(index, "estopa")
    (estopa,) = found.artists
    assert (estopa.artist, estopa.artist_slug, estopa.url, estopa.score, estopa.via, estopa.songs) == (
        "Estopa", "estopa", f"{BASE}/estopa/", 100.0, "artist", 159)
    assert (estopa.kind, estopa.source) == ("artist", "lacuerda")
    # Its songs the index holds are its row's, not hits of their own: the most popular with chords first.
    assert found.songs == ()
    assert [s.title for s in estopa.top] == ["Como Camarón", "Tu Calorro"]


def test_a_title_finds_the_song_where_the_index_has_it(index):
    (song,) = li.find(index, "como camaron").songs
    assert (song.kind, song.artist, song.title, song.via, song.score) == ("song", "Estopa", "Como Camarón", "title", 100.0)
    assert song.url == f"{BASE}/estopa/como_camaron"
    assert song.sheet_url == f"{BASE}/estopa/como_camaron-2.shtml"
    assert (song.versions, song.acordes) == ("RRT", 2)
    for query in ("estopa como camaron", "Como Camarón Estopa"):
        (both,) = li.find(index, query).songs
        assert (both.title, both.via, both.score) == ("Como Camarón", "both", 100.0)


def test_an_artist_named_with_a_title_the_index_doesnt_hold_is_a_possible_match(conn):
    # Most artists' songs aren't in the index: the query that names one, and a title, still finds them,
    # below a strong hit, as the reading of both their names.
    li.store_artists(conn, "tabs/e/index0.html", [LCArtist(s, n, c) for s, n, c in [*E1, *E2]])
    li.store_artists(conn, "tabs/j/index0.html", [LCArtist("joaquin_sabina", "Joaquín Sabina", 241)])
    for query, artist in (("estopa como camaron", "Estopa"), ("Como Camarón - Estopa", "Estopa"),
                          ("joaquin sabina y nos dieron las diez", "Joaquín Sabina"),
                          ("los enanitos verdes lamento boliviano", "Enanitos Verdes")):
        found = li.find(conn, query)
        assert [(h.artist, h.score, h.via) for h in found.artists][:1] == [(artist, 80.0, "both")], query
        assert found.songs == ()
    # A name is whole words of the query, never letters inside one.
    assert li.find(conn, "estopazo de verano").artists == ()


def test_a_song_without_chords_has_no_sheet(index):
    (song,) = li.find(index, "vino tinto").songs
    assert (song.acordes, song.sheet_url) == (0, None)


def test_accents_articles_and_y_are_folded(index):
    assert [a.artist for a in li.find(index, "joaquin sabina").artists][:1] == ["Joaquín Sabina"]
    assert li.find(index, "Joaquín Sabina").artists[0].score == 100.0
    assert li.find(index, "los ecos").artists[0].artist == "Los Ecos"
    (enanitos,) = li.find(index, "los enanitos verdes").artists
    assert (enanitos.url, enanitos.score) == (f"{BASE}/enanitos/", 100.0)
    assert li.find(index, "musica ligera").songs[0].title == "De Música Ligera"


def test_part_of_a_name_finds_the_artist_below_a_whole_one(index):
    hits = li.find(index, "sabina").artists
    assert [(h.artist, h.score) for h in hits] == [("Joaquín Sabina", 90.0), ("Sabina y Fito", 90.0)]
    hits = li.find(index, "ecos").artists
    assert [h.artist for h in hits] == ["Los Ecos", "Ecos del Rocío"]
    assert hits[0].score == 100.0 > hits[1].score


def test_a_tie_goes_to_the_artist_with_more_songs(index):
    li.store_artists(index, "tabs/e/index100.html", [LCArtist("ecos_band", "Ecos", 50)])
    assert [(h.artist, h.songs) for h in li.find(index, "ecos").artists[:2]] == [("Ecos", 50), ("Los Ecos", 5)]


def test_a_typo_in_one_word_still_finds_the_artist(index):
    # The prefilter looks for the query's two longest words: a typo in one of them still finds it.
    assert li.find(index, "joaquin sabinna").artists[0].artist == "Joaquín Sabina"


def test_initials_find_their_artist(index):
    assert li.find(index, "E.G.O.").artists[0].artist == "E.G.O."


def test_chinese_is_compared_as_pinyin(index):
    for query in ("宋冬野", "song dongye", "Song Dong Ye"):
        assert [h.artist_slug for h in li.find(index, query).artists] == ["song_dongye"], query


def test_nothing_or_too_little_finds_nothing(index):
    assert li.find(index, "zzzzqqq") == li.LaCuerdaFound()
    assert li.find(index, "ab") == li.LaCuerdaFound()
    assert li.find(index, "") == li.LaCuerdaFound()


def test_limits(index):
    assert len(li.find(index, "ecos", artists=1).artists) == 1
    assert li.find(index, "soda", songs=0).songs == ()


def test_artist_songs_lists_what_the_index_holds_most_popular_first(index):
    hits = li.artist_songs(index, "soda_stereo")
    # LaCuerda's own order of popularity, as the artist page gives it.
    assert [h.title for h in hits[:3]] == ["De Música Ligera", "Persiana Americana", "Té para 3"]
    assert len(hits) == 14 and {h.via for h in hits} == {"artist"}
    assert li.artist_songs(index, "nobody") == []


def test_songs_whose_artist_the_listings_dont_have_yet_make_an_artist_row(conn):
    li.store_artist_page(conn, "estopa", artist_page("Estopa", "estopa", ("como_camaron", "Como Camarón", "R-1")))
    (estopa,) = li.find(conn, "estopa").artists
    assert (estopa.artist, estopa.songs, [s.title for s in estopa.top]) == ("Estopa", 1, ["Como Camarón"])


def test_find_reads_no_more_than_the_query_needs_on_a_table_lacuerdas_size(conn):
    # About 20,000 artists (E has 639, and 100 a page) and the songs of a few hundred artist pages.
    rows = []
    for n in range(25_000):
        rows.append((f"artist_{n}/", f"artist_{n}", f"Artista Número {n}", f"artista-numero-{n}", "", "", n % 300,
                     "", 0, None, f"tabs/a/index{n // 100 * 100}.html"))
    for n in range(50_000):
        a = n // 100
        rows.append((f"artist_{a}/song_{n}", f"artist_{a}", f"Artista Número {a}", f"artista-numero-{a}",
                     f"Canción {n} del Amor", f"cancion-{n}-del-amor", 0, "RT", 1, n % 100, f"artist_{a}/"))
    conn.executemany("INSERT INTO lacuerda_index VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    li.store_artists(conn, "tabs/e/index0.html", [LCArtist("estopa", "Estopa", 159)])
    for query in ("estopa", "cancion 4242 del amor", "artista numero 77"):
        started = time.perf_counter()
        found = li.find(conn, query)
        assert time.perf_counter() - started < 1.0, query
        assert found.artists or found.songs, query



# --- Chinese counts as pinyin only in whole words -------------------------------------------

NOISE = ("Bohemia Suburbana", "Bohemia Urbana", "El Bananero", "Anabantha")


@pytest.fixture
def banma(conn):
    """Artists that merely hold the syllable "ban" (artist rows and a song row of each), and a Chinese
    song LaCuerda might hold."""
    li.store_artists(conn, "tabs/b/index0.html", [
        LCArtist("bohemia_suburbana", "Bohemia Suburbana", 20), LCArtist("bohemia_urbana", "Bohemia Urbana", 12),
        LCArtist("el_bananero", "El Bananero", 7), LCArtist("anabantha", "Anabantha", 9)])
    for slug, name in (("bohemia_suburbana", "Bohemia Suburbana"), ("bohemia_urbana", "Bohemia Urbana"),
                       ("el_bananero", "El Bananero"), ("anabantha", "Anabantha")):
        li.store_songs(conn, slug, name, [LCSong("banda", "Banda", "R", (1,)), LCSong("mar", "Mar", "R", (1,))])
    li.store_artists(conn, "tabs/s/index0.html", [LCArtist("song_dongye", "宋冬野", 4)])
    li.store_songs(conn, "song_dongye", "宋冬野", [LCSong("banma_banma", "斑马斑马", "R", (1,))])
    return conn


@pytest.mark.parametrize("query", ["斑马", "斑马斑马"])
def test_a_chinese_query_finds_none_of_the_names_that_merely_hold_its_syllables(banma, query):
    found = li.find(banma, query, artists=10, songs=10)
    names = {h.artist for h in (*found.artists, *found.songs)}
    assert not names & set(NOISE)


@pytest.mark.parametrize("query", ["斑马", "斑马斑马", "banma", "banma banma"])
def test_a_chinese_song_is_found_by_its_characters_and_its_pinyin(banma, query):
    found = li.find(banma, query, artists=10, songs=10)
    assert [(h.artist, h.title) for h in found.songs][:1] == [("宋冬野", "斑马斑马")], query


def test_a_partial_match_in_pinyin_is_no_strong_hit(banma):
    (hit,) = li.find(banma, "斑马", artists=10, songs=10).songs
    assert hit.score <= 100 * li.PINYIN_PARTIAL_SCALE + 0.1
    assert li.find(banma, "宋冬野 斑马斑马").songs[0].score == 100
