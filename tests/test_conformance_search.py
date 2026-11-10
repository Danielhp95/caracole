"""The search corpus, for the phone: what search.py, lacuerda_index.py, ug/key_search.py, song_names.py and caracole
serve's /api/search and /api/artist answer, over fixture libraries, written for the Kotlin search lanes to agree with.

**Fixtures** (``vectors/search/fixtures/<name>.jsonl``, helpers.corpus's format): each a library built with caracole's
own functions (the index writers, ``lacuerda_index.store_*``, ``harptabs_index.store_artist_page``,
``gametabs_index.store_game_page``, ``ug.artist_tabs.store``, ``songs.upsert_song``, ``songs.mark_removed``) from the
search tests' own data (test_search.py's row sets and site helpers, test_lacuerda_index.py's, test_song_names.py's),
every stamp caracole would write as now made ``STAMP``, then dumped (``dump_fixture``). Every query below runs
against the fixture replayed into a fresh database (``replay_fixture``), never the one it was built in:

- ``ug``: Ultimate Guitar's index read either way (test_search.py's ``EITHER``, the catch-alls, the artist pages read
  of 宋冬野 and Soda Stereo), your songs (one matched, one in review, one ignored, one under a placeholder artist)
  and the songs you removed;
- ``by_word``: artists by a word of their name, the well-known ones and their namesakes, close spellings, and
  LaCuerda's artists beside them;
- ``titles``: close spellings of titles, on Ultimate Guitar's index, LaCuerda's and harptabs.com's;
- ``sites``: gtptabs.com's, MuseScore's, harptabs.com's and gametabs.net's indexes (their captured sitemaps and pages);
- ``lacuerda``: LaCuerda's index (test_lacuerda_index.py's listings, artist pages and search answers), its listings
  read in part (kv ``lacuerda:index:pages``);
- ``names``: what song_names.py knows an artist by (test_song_names.py's);
- ``common``: words too common for what a search reads, each past the cap that bounds it: "love" in more than
  ``key_search.KEYS_PER_PATTERN`` keys and more than ``search.CLOSE_TABS`` rows of Ultimate Guitar's index,
  "crooner" in as many artists' keys (more than ``search.CLOSE_ARTISTS``), a key of both that only the keys every
  pattern is in bring in (``key_search._every``), more than ``search.SITE_ROWS_READ`` of gtptabs.com's pages and more
  than ``lacuerda_index.ROWS_READ`` (and ``search.SITE_TITLES_READ``) of LaCuerda's songs a pattern finds; a row each
  cap cuts the one that would answer (``test_the_common_fixture_is_past_each_cap_its_queries_meet``);
- ``empty``: a database with nothing in it.

**Vectors** (``vectors/search/<name>.jsonl``): a header, then a record a line, ``{fn, fixture, args, kw, out}``: the
function's dotted name, the fixture whose replayed database is its ``conn`` (null for a function that takes none),
its other arguments and keywords, and ``out``, the answer as ``helpers.corpus.plain`` writes it (a ``Song`` its key,
so ``LibraryHit.song`` is the song's key). A record whose ``fn`` is a composition says so here:

- query.jsonl: ``_forms`` and ``_pinyin_runs`` of ``args[0]`` (``_pinyin_runs`` of ``name_words(text)``, its
  ``args[0]`` those words), ``_patterns`` of ``args[0]`` (the tokens, ``name_words(text)``), ``_queries`` (each
  ``{text, compact, runs}``); ``caracole.search._Query``: one form of a query (``args``: its text, its runs, an
  artist, a title) and its ``{readings, score, name, holds}`` (``readings(artist, title)``, ``score(artist, title)``,
  ``name(artist)``, ``holds(artist, title)``); ``_reading`` (``args[0]`` the triples, ``kw.reading``);
  ``_names_reading`` (``args``: the query, the artists, the title; its queries ``_queries(query)``);
  ``caracole.ug.key_search.rows_like`` over a fixture (``args[0]`` the patterns, the query's ``_patterns``; one
  record a set of them, in any order the same keys).
- library.jsonl: ``search_library``, ``search_removed``; ``library_by_artist`` of the fixture's songs
  (``songs.list_songs``).
- index.jsonl: ``find_index``; ``found``: ``found(search_library(conn, q, 5), find_index(conn, q))``, as
  /api/search puts them together; ``artist_songs``, ``index_artist`` (of the fixture's artist keys, ``sampled``: of
  keys alike but for a number, the first three and the last); ``bare_id_hint`` and ``bare_id_unseen`` of
  ``find_index(conn, q)``'s songs then its artists (no overrides.toml); ``no_ones``.
- suggest.jsonl: ``suggest_artists``, ``suggest_titles``; ``suggestions`` of ``find_index(conn, q)``, and, with
  ``kw.sites`` ``"api"``, the other sites' answers /api/search hands it: ``search_lacuerda(conn, q, songs=5)``'s
  artists and songs, ``search_gtptabs(conn, q, 5)``, ``search_musescore(conn, q, 5)``,
  ``search_harptabs(conn, q, songs=5)``'s artists and songs, in that order (else none).
- sites.jsonl: ``search_gtptabs``, ``gtptabs_songs``, ``search_musescore``, ``search_harptabs``, ``harptabs_artist``,
  ``harptabs_songs``, ``search_gametabs``.
- lacuerda.jsonl: ``lacuerda_index.find``, ``search_lacuerda``, ``lacuerda_artist``, ``lacuerda_artist_named``,
  ``lacuerda_songs``, ``lacuerda_left_out``, ``lacuerda_index.letters_read``; ``lacuerda_leads``:
  ``lacuerda_leads(find_index(conn, q), search_lacuerda(conn, q)[0])``.
- names.jsonl: ``song_names.clean``, ``clean_channel``; ``read_names`` with the fixture's database and its songs
  (``songs=list_songs(conn)``), or, with no fixture, no database and no songs (``read_names(None, text, songs=())``).

**/api/search and /api/artist** (``vectors/web/api_search.jsonl``): records ``{fn: "caracole.web.app.WebApp.handle",
fixture, args: ["GET", path], kw: {}, out: {status, json}}``, each answered by a real ``WebApp`` over the fixture
replayed into its state folder, with an empty library folder, ``searches_lacuerda=False`` and
``searches_youtube=False``: each fixture's queries and artists, over ug the texts and addresses of ``API_TEXTS`` and
``API_RAW`` (how the route reads a query), and on every fixture ``API_ARTIST``'s. The phone answers ``progression``
and ``youtube`` as null (and ``lacuerda_search``, as ``searches_lacuerda=False`` does: its gate is
vectors/web/api_search_gate.jsonl's, tests/test_conformance_lookup_routes.py), and a progression can add rows to
``library``, so the generator patches, for its ``WebApp`` alone, ``progressions.read_progression`` to answer None: the
answers recorded are those the phone computes, ``lacuerda_unlisted`` among them. The rest of an answer is caracole
serve's own. What a song's card says of the files of its folder is masked: in every object with a
``links`` member (a ``library`` row, a site row's song of yours), ``links``, ``files``, ``source``, ``key`` and
``instruments`` are ``"*"``.

The generator's answers are the same under any hash seed (``test_the_corpus_is_the_same_whatever_the_hash_seed``,
which runs it twice, in subprocesses with ``PYTHONHASHSEED`` 1 and 2). Regenerate with ``CARACOLE_CORPUS=write``
(tests/conformance/README.md).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator, Sequence
import re
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import pytest

from helpers.corpus import VECTORS, check, dump_fixture, jsonl, plain, read_fixture, replay_fixture

TESTS = Path(__file__).resolve().parent
SRC = TESTS.parent / "src"
MADE_BY = "tests/test_conformance_search.py"
STAMP = "2026-11-03T10:00:00Z"
SEARCH = VECTORS / "search"
API = VECTORS / "web" / "api_search.jsonl"
FILES = ("query", "library", "index", "suggest", "sites", "lacuerda", "names")


# --- the fixtures ---------------------------------------------------------------------------------------------------


class Ids:
    """Tab ids, a block at a time: rows of several tests' sets in one fixture never share one."""

    def __init__(self, start: int = 100_000):
        self.next = start

    def songs_of(self, artist_key: str, n: int, top_tabs: int = 1) -> list[tuple]:
        import test_search as ts

        rows = ts.songs_of(artist_key, n, self.next, top_tabs)
        self.next += n + top_tabs + 1
        return rows


def _ug(conn, rows) -> None:
    import test_search as ts

    ts.index(conn, rows)


def _songs(conn, *songs: tuple) -> dict[str, Any]:
    """Songs of yours, through ``songs.upsert_song`` (conftest's ``add_song``): (artist, title) or (artist, title,
    artists), added a minute apart, the first the newest."""
    from conftest import add_song

    made = {}
    for n, song in enumerate(songs):
        artist, title, *rest = song
        made[f"{artist} - {title}"] = add_song(conn, artist, title, added_at=f"2026-10-01T00:{59 - n:02d}:00Z",
                                               artists=rest[0] if rest else None)
    return made


def _removed(conn, *songs: tuple[str, str]) -> None:
    """Songs you removed: a tombstone each (``songs.mark_removed``), an hour apart, the last two in the same second."""
    import test_search as ts

    for n, (artist, title) in enumerate(songs):
        ts.remove_song(conn, artist, title, when=f"2026-10-20T{min(n, len(songs) - 2):02d}:00:00+00:00")


def _listed(conn, url: str, artist: str, tabs: list[dict]) -> None:
    from caracole.ug import artist_tabs
    from caracole.ug.page import parse_version

    artist_tabs.store(conn, url, artist, [parse_version(t) for t in tabs], read_at="2026-10-18T00:00:00Z")


def _lc(conn, page: str, *artists: tuple[str, str, int]) -> None:
    from caracole import lacuerda_index as li
    from caracole.lacuerda import LCArtist

    li.store_artists(conn, page, [LCArtist(slug, name, n) for slug, name, n in artists])


def build_ug(conn, library: Path) -> None:
    import test_search as ts
    from helpers.ug_pages import SONG_DONGYE, SONG_DONGYE_URL, song_dongye_chords, song_dongye_tab, version_dict

    from caracole.songs import update_song

    _ug(conn, ts.EITHER + [ts.EPIC, ts.NEAR_EPIC, (77, "misc-musicals", "hamilton-my-shot", "chords"),
                           (20061, "a-great-big-world", "oasis", "chords"),
                           (1, "eagles", "hotel-california", "chords"), (2, "eagles", "desperado", "chords"),
                           (3, "beagles", "the-ballad", "chords"), ts.PARALAMAS, ts.CAMARON_UG, ts.ESTOPA_UG,
                           (6236009, "misc-traditional", "froggy-went-a-courtin-intro", "chords"),
                           (20071, "anju-panta", "banma-phulyo", "chords"),
                           (389691, "rifles", "local-boy", "chords")])
    _listed(conn, SONG_DONGYE_URL, SONG_DONGYE, [
        *song_dongye_chords(t4180894=(4.8, 120), t4689017=(4.6, 40), t3016223=(4.7, 90), t3204647=(4.1, 9)),
        song_dongye_tab(5000001, "安和桥 Anhe Bridge", type="Tabs")])
    _listed(conn, "https://www.ultimate-guitar.com/artist/soda_stereo_1234", "Soda Stereo", [
        version_dict(1081460, song="Persiana Americana", artist="Soda Stereo", rating=4.9, votes=300),
        version_dict(7700001, song="De Música Ligera", artist="Soda Stereo", rating=4.7, votes=80),
        version_dict(7700002, song="De Música Ligera", artist="Soda Stereo", type="Tabs", rating=4.2, votes=5)])
    made = _songs(conn, ("Radiohead", "Creep"), ("Oasis", "Wonderwall"), ("Soda Stereo", "De Música Ligera"),
                  ("宋冬野", "斑马，斑马"), ("Shakira", "La Tortura", ["Shakira", "Alejandro Sanz"]),
                  ("Frenzal Rhomb", "Suburban Male"), ("Metallica", "Creeping Death"), ("TLC", "Creep"),
                  ("misc", "斑马"), ("Song Dong Ye", "郭源潮"), ("Bill Fox", "I'm Not Over Loving You"),
                  ("Ryan Adams", "Wonderwall"))
    update_song(conn, made["Radiohead - Creep"].id, status="found", match_decision="accept", match_step="exact",
                match_score=100.0, match_artist_key="radiohead", match_song_key="creep")
    update_song(conn, made["Ryan Adams - Wonderwall"].id, match_decision="accept", match_artist_key="oasis",
                match_song_key="wonderwall")  # your cover, matched to the original's tab
    update_song(conn, made["Bill Fox - I'm Not Over Loving You"].id, review=1, match_candidates=[
        {"artist_key": "bill-fox", "song_key": "im-not-over-loving-you", "score": 88.0, "step": "fuzzy"}])
    update_song(conn, made["TLC - Creep"].id, status="ignored")
    _removed(conn, ("宋冬野", "安和桥"), ("Plain Jane", "Nothing"), ("Radiohead", "Karma Police"),
             ("Eagles", "Hotel California"), ("Song Dongye", "南方姑娘"))


def build_by_word(conn, library: Path) -> None:
    import test_search as ts

    from caracole import search

    ids = Ids()
    many = [(40000 + i, f"number-{i}-the-band", "a-song", "chords") for i in range(search.WORD_ARTISTS + 1)]
    _ug(conn, ts.BY_WORD + many + [
        (41000, "band", "the-weight", "chords"), (41001, "the-the", "uncertain-smile", "chords"),
        (41010, "ub-forty", "red-wine", "chords"), (30130, "la-naranja-metalica", "fuego", "chords"),
        *ids.songs_of("bob-dylan", search.WELL_KNOWN, top_tabs=5), *ids.songs_of("dylan", 3),
        *ids.songs_of("dylan-scott", 4), (53000, "deyaz", "dylan", "chords"), (53001, "deyaz", "dylan", "tabs"),
        *ids.songs_of("eric-clapton", search.WELL_KNOWN, top_tabs=3), *ids.songs_of("claptone", 2),
        *ids.songs_of("prince", search.WELL_KNOWN // 2, top_tabs=4), *ids.songs_of("prince-royce", search.WELL_KNOWN),
        *ids.songs_of("daniel-paez", search.MOST_SONGS - 1),
        *ids.songs_of("willie-nelson", search.WELL_KNOWN + 30, top_tabs=5),
        *ids.songs_of("ricky-nelson", search.WELL_KNOWN + 20), *ids.songs_of("hawk-nelson", search.WELL_KNOWN),
        *ids.songs_of("nelson", 3),
        *ids.songs_of("george-jones", search.WELL_KNOWN + 10, top_tabs=3), *ids.songs_of("tom-jones", 40),
        *ids.songs_of("norah-jones", search.WELL_KNOWN - 1), (53100, "brian-mcfadden", "jones", "chords"),
        *[(53110 + i, "duke-ellington", "pirates-of-the-caribbean-davy-jones", "tabs") for i in range(5)],
        *ids.songs_of("eminem", 20), (51000, "the-who", "eminence-front", "chords"),
        (51001, "the-who", "eminence-front", "tabs"), *ids.songs_of("adele", 20),
        *ids.songs_of("burst-of-bonse", 4), *ids.songs_of("julien-bense", 2), *ids.songs_of("malika-ayane", 2),
        *ids.songs_of("javier-calamaro", search.MOST_SONGS), (50000, "jose-antonio-mendez", "un-bolero", "chords")])
    _lc(conn, "tabs/a/index0.html", ("andres_calamaro", "Andrés Calamaro", 325), ("andres", "Andrés", 3),
        ("andres_canalla", "Andrés Canalla", 9), ("andresito", "Andresito", 40), ("antonio_jose", "Antonio José", 44),
        ("adelle", "Adelle", 3))
    _lc(conn, "tabs/b/index0.html", ("beyonce", "Beyonce", 3), ("banda_el_limon", "Banda el Limón", 184),
        ("banda_ms", "Banda MS", 107))
    _lc(conn, "tabs/d/index0.html", ("dylan", "Dylan", 3))
    _lc(conn, "tabs/g/index0.html", *[(f"grupo_{i}_band", f"Grupo {i} Band", 5 + i) for i in range(11)])
    _lc(conn, "tabs/l/index0.html", ("la_banda_del_lechuga", "La Banda del Lechuga", 5))
    _songs(conn, ("Lynyrd Skynyrd", "Free Bird"), ("Bob Dylan", "Song 0"))


def build_titles(conn, library: Path) -> None:
    import test_search as ts

    ids = Ids()
    _ug(conn, ts.TITLES + ts.PINYIN_ROWS + [
        *ids.songs_of("we-are-scientists", 40), *[(64100 + i, "coldplay", "scientist", "chords") for i in range(8)],
        *[(61000 + i, "queen", "bohemian-rhapsody", "chords") for i in range(3)],
        (62000, "estopa", "como-camaron", "chords"), (62001, "estopa", "como-camaron", "chords"),
        *[(65000 + i, "billy-joel", "piano-man", "chords") for i in range(3)],
        *[(66000 + i, "guns-n-roses", "sweet-child-o-mine", "chords") for i in range(6)]])
    ts.lacuerda(conn)
    ts.harptabs_index(conn)
    _songs(conn, ("Eagles", "Hotel California"), ("Coldplay", "The Scientist"))


def build_sites(conn, library: Path) -> None:
    import test_search as ts

    from caracole.harptabs import parse_page_url

    gtp = ts.GTP
    ts.gtptabs_pages(conn, gtp + "18/radiohead/creep.html", gtp + "18/radiohead/creep-2.html",
                     gtp + "18/radiohead/karma-police.html", gtp + "20/stone-temple-pilots/creep.html",
                     gtp + "13/metallica/creeping-death.html", gtp + "18/radiohead.html",
                     gtp + "10/john-elton/your-song.html", gtp + "10/john-elton/rocket-man.html",
                     gtp + "2/beatles-the/yesterday.html")
    _ug(conn, [(1, "elton-john", "your-song", "chords"), (2, "oasis", "wonderwall", "chords"),
               (3, "oasis", "live-forever", "chords"), (4, "eagles", "hotel-california", "chords"),
               (5, "hotel", "lobby", "chords"), (6, "forever", "young", "chords"),
               (7, "billy-joel", "piano-man", "chords"), (8, "radiohead", "creep", "chords")])
    ts.musescore_pages(conn, *(f"https://musescore.com/song/{t}" for t in (
        "wonderwall-1524", "wonderwall-99", "creep-7", "live_forever-8", "ban_ma_ban_ma-5", "oasis-11",
        "hotel_california-12", "eagles-13", "the-14", "california-15", "live-16", "forever-17", "your_song-9")))
    ts.gametabs_index(conn)
    ts.harptabs_index(conn)
    conn.executemany("INSERT INTO harptabs_index (path, kind, page_id, key, sitemap) VALUES (?, ?, ?, ?, 'sitemap')",
                     [tuple(parse_page_url(f"https://www.harptabs.com/{p}")) for p in (
                         "tab/30906/can-t-help-falling-in-love", "tab/1247/knockin-on-heavens-door")])
    _songs(conn, ("Forever", "Live"), ("Radiohead", "Creep"))


def build_lacuerda(conn, library: Path) -> None:
    from helpers.lacuerda_site import artist_page, artists_search_page, fixture, search_page
    from test_lacuerda_index import E1, E2, S1

    from caracole import lacuerda_index as li
    from caracole.db import kv_set_json
    from caracole.lacuerda import LCSong, parse_search
    from caracole.ug.index import upsert_rows

    _lc(conn, "tabs/e/index0.html", *E1, *E2, ("ego", "E.G.O.", 3), ("ecos_del_rocio", "Ecos del Rocío", 13))
    _lc(conn, "tabs/e/index100.html", ("ecos_band", "Ecos", 50))
    _lc(conn, "tabs/j/index0.html", ("joaquin_sabina", "Joaquín Sabina", 241))
    _lc(conn, "tabs/s/index0.html", *S1, ("song_dongye", "宋冬野", 4))
    _lc(conn, "tabs/l/index0.html", ("los_rock_star", "Los Rock Star", 6), ("lady_pank", "Lady Pank", 3))
    _lc(conn, "tabs/b/index0.html", ("bohemia_suburbana", "Bohemia Suburbana", 20),
        ("bohemia_urbana", "Bohemia Urbana", 12), ("el_bananero", "El Bananero", 7), ("anabantha", "Anabantha", 9))
    _lc(conn, "tabs/d/index0.html", ("david_chumana", "David Chumaña", 7),
        ("cuarteto_almanaque", "Cuarteto Almanaque", 6), ("alimana", "Alimaña", 2),
        ("bragas_de_la_flaca", "Las Bragas de la Flaca", 1), ("enrique_bunbury", "Enrique Bunbury", 264))
    _lc(conn, "tabs/a/index0.html", ("amaral", "Amaral", 119), ("abuelos_de_la_nada", "Abuelos de la Nada", 135),
        ("corazon_serrano", "Corazón Serrano", 53), ("un_corazon", "Un Corazón", 64),
        ("alma_corazon_y_vida", "Alma Corazón y vida", 8))
    _lc(conn, "tabs/a/index100.html", *[(f"amor_{n}", f"Amor {w}", 5) for n, w in enumerate(
        "Prohibido Eterno Salvaje Propio Ciego Gitano Bandido Moreno Ausente Lejano Dormido Perdido".split())])
    _lc(conn, "tabs/g/index0.html", ("gaviota", "Gaviota", 12))
    li.store_artist_page(conn, "soda_stereo", fixture("artist.html"))
    li.store_artist_page(conn, "estopa", artist_page(
        "Estopa", "estopa", ("como_camaron", "Como Camarón", "RRT-213"), ("tu_calorro", "Tu Calorro", "R-1"),
        ("vino_tinto", "Vino Tinto", "T-1"), ("esta_manana", "Esta mañana", "R-1"),
        ("fin_de_semana", "Fín de semana", "R-1"), ("manana_clara", "Mañana Clara", "R-1"),
        ("mananitas", "Mañanitas", "R-1")))
    for slug, name in (("bohemia_suburbana", "Bohemia Suburbana"), ("bohemia_urbana", "Bohemia Urbana"),
                       ("el_bananero", "El Bananero"), ("anabantha", "Anabantha")):
        li.store_songs(conn, slug, name, [LCSong("banda", "Banda", "R", (1,)), LCSong("mar", "Mar", "R", (1,))])
    li.store_songs(conn, "song_dongye", "宋冬野", [LCSong("banma_banma", "斑马斑马", "R", (1,))])
    li.store_search(conn, parse_search(search_page(
        ("imaginarios", "Los Imaginarios", [("corazon_de_tiza", "Corazón de Tiza", "RT-12")]),
        ("soda_stereo", "Soda Stereo", [("de_musica_ligera", "De Música Ligera", "TR-21")]))))
    li.store_search(conn, parse_search(artists_search_page([("bragas_de_la_gaviota", "Las Bragas de la Gaviota", 1),
                                                            ("gaviota", "Gaviota", 30)])))
    upsert_rows(conn, [(9001, "lady-pank", "zawsze-tam", "chords", "lady-pank/zawsze-tam-chords-9001")], "1",
                datetime(2026, 10, 19, tzinfo=UTC))
    # The listings read so far: A and B whole, E in part (its second page missing), nothing of the rest.
    checked = {"checked_at": "2026-10-20T03:30:00Z", "etag": None, "last_modified": None}
    kv_set_json(conn, li.PAGES_KEY, {
        "tabs/a/index0.html": {**checked, "rows": 5, "pages": ["index0.html", "index100.html"], "total": 17},
        "tabs/a/index100.html": {**checked, "rows": 12, "pages": [], "total": 17},
        "tabs/b/index0.html": {**checked, "rows": 4, "pages": ["index0.html"], "total": 4},
        "tabs/e/index0.html": {**checked, "rows": 7, "pages": ["index0.html", "index100.html", "index200.html"],
                               "total": 250},
        "tabs/e/index100.html": {**checked, "rows": 1, "pages": [], "total": 250}})
    _songs(conn, ("Estopa", "Como Camarón"), ("Joaquín Sabina", "19 Días y 500 Noches"))


def build_names(conn, library: Path) -> None:
    import test_search as ts
    from test_song_names import SILVANA

    ids = Ids()
    _ug(conn, [*SILVANA, *ids.songs_of("ben-e-king", 6), (67100, "ben-e-king", "stand-by-me", "chords"),
               *ids.songs_of("me", 6), *ids.songs_of("stand", 6), *ids.songs_of("love", 8),
               (66100, "elvis-presley", "love-me-tender", "chords"), *ids.songs_of("hyperfanes", 5)])
    ts.lacuerda(conn)
    ts.gtptabs_pages(conn, "https://gtptabs.com/tabs/1/silvana-estrada/tregua.html")
    ts.harptabs_index(conn)
    made = _songs(conn, ("Natalia Lafourcade", "Hasta la Raíz"), ("Björk", "Jóga"), ("Björk", "Hyperballad"),
                  ("Nick Cani", "Vegan Vikings"), ("Silvana", "Estrada"), ("Onda", "Una"), ("Onda", "Otra"),
                  ("Lumbre", "Fuego"))
    ts.keep_sheet(conn, library, made["Lumbre - Fuego"], "[Am]la", tab_id=1)


def _letters(n: int) -> str:
    """``n`` in three letters: a word gtptabs.com's slugs keep whole (a number after a hyphen is an upload's)."""
    return "".join("abcdefghijklmnopqrstuvwxyz"[n // 26 ** k % 26] for k in (2, 1, 0))


def build_common(conn, library: Path) -> None:
    import test_search as ts

    from caracole import lacuerda_index as li
    from caracole import search
    from caracole.lacuerda import LCArtist, LCSong
    from caracole.ug import key_search

    # Ultimate Guitar's index: "crooner-0" ... "crooner-1099", one song each, "love-0" ... "love-1099", of 1 to 9 tabs:
    # more keys of a word than one pattern brings in (its shortest), as many artists of one, more than a suggestion
    # reads, and more rows of a word than a title is suggested from; "crooner-999", whose key sorts last, the one with
    # the most songs.
    songs = key_search.KEYS_PER_PATTERN + 100
    rows, tab = [], 200_000
    for n in range(songs):
        for k in range(1 + n % 9):
            rows.append((tab, f"crooner-{n}", f"love-{n}", "tabs" if k % 2 else "chords"))
            tab += 1
    assert len(rows) > search.CLOSE_TABS
    rows += [(tab + n, "crooner-999", f"serenade-{_letters(n)}", "chords") for n in range(6)]
    tab += 6
    # The shortest key of the word; a key of both words longer than the shortest of either ("love crooner"); more
    # songs of love, a baby's among them.
    rows += [(tab, "nat-king-cole", "love", "chords"), (tab + 1, "the-love-crooners", "love-me-tender", "chords"),
             (tab + 2, "the-supremes", "baby-love", "chords"), (tab + 3, "the-supremes", "baby-love", "tabs"),
             (tab + 4, "frankie-valli", "i-love-you-baby", "chords")]
    _ug(conn, rows)
    # gtptabs.com: more of the crooners' pages than a search reads, the last by its path the one "love cyy" names.
    ts.gtptabs_pages(conn, *(f"{ts.GTP}3/crooners/love-{_letters(n)}.html" for n in range(search.SITE_ROWS_READ + 1)))
    # LaCuerda: more songs holding "love" than it reads, under fifty crooners; those it cuts last, by their keys'
    # length then their paths (Love Baby) or by their paths alone (a Love whose slug sorts last), the ones that answer.
    crooners = 50
    li.store_artists(conn, "tabs/c/index0.html", [LCArtist(f"crooner_{j:02d}", f"Crooner {j:02d}", 0)
                                                  for j in range(crooners)])
    by_artist: dict[int, list] = {}
    for n in range(li.ROWS_READ + 1):
        by_artist.setdefault(n % crooners, []).append(LCSong(f"love_{n}", f"Love {n}", "R", (1,)))
    by_artist[crooners - 1] += [LCSong("love_baby", "Love Baby", "RT", (1, 2)),
                                LCSong("zz_love", "Love", "RRRT", (1, 2, 3, 4))]
    for j, lc_songs in sorted(by_artist.items()):
        li.store_songs(conn, f"crooner_{j:02d}", f"Crooner {j:02d}", lc_songs)
    _songs(conn, ("Nat King Cole", "L-O-V-E"), ("Crooner 999", "Serenade"))


def build_empty(conn, library: Path) -> None:
    pass


FIXTURES: dict[str, Callable[[Any, Path], None]] = {
    "ug": build_ug, "by_word": build_by_word, "titles": build_titles, "sites": build_sites,
    "lacuerda": build_lacuerda, "names": build_names, "common": build_common, "empty": build_empty,
}


def _settled(conn) -> None:
    """Every stamp caracole writes as now, made ``STAMP``: a fixture is the same on every run."""
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (STAMP, STAMP))
    conn.execute("UPDATE files SET created_at = ?", (STAMP,))
    conn.execute("UPDATE versions SET fetched_at = ?", (STAMP,))


def _fresh(path: Path):
    from caracole import db

    from conftest import migrated_database

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(migrated_database())
    return db.connect(path)


class Corpus:
    """The fixtures, built and replayed in ``workdir`` once each, and the vectors' records made over them."""

    def __init__(self, workdir: Path):
        self.workdir = workdir
        self._texts: dict[str, str] = {}
        self._replayed: dict[str, Path] = {}

    def fixture_text(self, name: str) -> str:
        if name not in self._texts:
            where = self.workdir / "built" / name
            with closing(_fresh(where / "caracole.sqlite")) as conn:
                FIXTURES[name](conn, where / "library")
                _settled(conn)
                records = dump_fixture(conn)
            self._texts[name] = jsonl(records, corpus=f"search/fixtures/{name}", made_by=MADE_BY)
        return self._texts[name]

    def state(self, name: str) -> Path:
        """The folder whose caracole.sqlite is the fixture replayed (and a home with an empty library)."""
        if name not in self._replayed:
            where = self.workdir / "replayed" / name
            with closing(_fresh(where / "state" / "caracole.sqlite")) as conn:
                replay_fixture(conn, read_fixture(self.fixture_text(name)))
            (where / "home" / "Tabs").mkdir(parents=True, exist_ok=True)
            self._replayed[name] = where
        return self._replayed[name]

    @contextmanager
    def conn(self, name: str) -> Iterator[Any]:
        from caracole import db

        with closing(db.connect(self.state(name) / "state" / "caracole.sqlite")) as conn:
            yield conn


# --- the queries ----------------------------------------------------------------------------------------------------

# Every fixture's: nothing, too little, noise, Chinese, Korean, Japanese, initials, a typo, numerals, names under a
# letter LaCuerda's listings haven't read.
COMMON = ["", " — ", "a", "x", "ab", "zz", "zzzz qqqq", "I V vi IV", "vi IV I V", "ii V I", "宋冬野", "斑马",
          "斑马，斑马", "斑馬", "宋冬野 斑马", "방탄소년단", "아이유 좋은 날", "宇多田ヒカル First Love", "さくら", "AC/DC",
          "R.E.M.", "E.G.O.", "radiohed crep", "creep", "Joaquín Sabina", "zoé", "ñu", "2 minutos", "Ünd"]

QUERIES: dict[str, list[str]] = {
    "ug": ["Persiana Américana", "stone temple pilots creep", "radiohed creep", "AC/DC — “Highway to Hell”",
           "froggy went a courtin", "MUSICA", "ban ma", "banma", "song dongye", "斑马斑马", "alejandro sanz", "radiohed",
           "epic not sorry for loving you", "EPIC the musical - Not Sorry for Loving You", "hamilton my shot", "oasis",
           "wonderwall", "radiohead", "radiohead creep", "eagles", "beagle", "misc musicals", "misc mashups",
           "police karma", "董小姐", "lilian", "安和桥", "nothing", "karma police", "musica ligera",
           "de musica ligera soda stereo", "la tortura", "suburban male", "the rifles local boy", "in april wonderwall",
           "creep radiohed", "rem losing", "ac dc", "musica", "persiana", "song dong ye", "郭源潮", "南方姑娘",
           "banma phulyo"],
    "by_word": ["lynyrd", "skynyrd", "Lynyrd", "skynyrd lynyrd", "lynyrd skynyrd", "horse", "beatle", "lynyr", "band",
                "the", "ub", "horse band", "伍佰", "sabina", "Joaquín", "SABINA", "lynrd", "lynrd skynrd", "metalica",
                "beatels", "zzzzqqq", "ly", "宋冬", "metallica", "dylan", "clapton", "prince", "paez", "antonio josé",
                "calamaro", "beyonse", "metalika", "eminen", "adelle", "nelson", "jones", "andres", "andres calamaro",
                "andres calamar", "sabinna", "free bird", "bob dylan song 0"],
    "titles": ["hotl califronia", "stairwy to heavn", "wonderwal oasys", "oasys wonderwal", "yesterdy", "wonderwal",
               "hotl califronia zebra", "wonderwal blurr", "oasys", "metalika", "zzzzqqq", "hte", "the scientst",
               "scientst", "hotel california", "hotel califronia", "wonderwall oasis", "stairway to heaven",
               "bohemian rapsody", "como camaon", "vino tintoo", "piano mann", "bily joel", "sweet chld o mine",
               "estopa", "billy joel"],
    "sites": ["radiohead creep", "radiohead", "your song", "yesterday", "wonderwall", "oasis wonderwall",
              "live forever oasis", "wonder", "hollow knight resting grounds", "fillmore", "yuzo koshiro fillmore",
              "yuzo koshiro", "aeris theme", "main theme", "nothing like it", "billy joel piano man", "piano man",
              "vienna billy joel", "billy joel", "ritchie valens", "joel", "the beatles", "piano",
              "can't help falling in love", "cant help falling in love", "knockin' on heaven's door",
              "knockin on heavens door", "oasis live forever", "the eagles hotel california", "hotel california",
              "eagles", "california eagles", "elton john your song", "forever live", "hollow knight",
              "christopher larkin"],
    "lacuerda": ["estopa", "como camaron", "estopa como camaron", "camaron estopa", "vino tinto", "joaquin sabina",
                 "los ecos", "los enanitos verdes", "musica ligera", "sabina", "ecos", "joaquin sabinna", "rockstar",
                 "song dongye", "songdongye", "zzzzqqq", "soda", "斑马斑马", "banma", "banma banma", "宋冬野 斑马斑马",
                 "corazon de tiza", "maná", "flaca", "joaquin sab", "bunbury lady blue", "lady blue bunbury",
                 "lady bunbury blue", "bunburys lady blue", "lady zawsze tam", "amaral sin ti no soy nada",
                 "corazon espinado", "amor de mis amores", "estopazo de verano", "andres", "gaviota", "soda stereo",
                 "de musica ligera", "esta mañana", "los imaginarios"],
    "names": ["silvana estrada que problema", "Silvana Estrada Que problema", "que problema", "Stand by Me",
              "Ben E King Stand by Me", "Love Me Tender", "Love Alone Again Or", "bjork army of me", "hyperfanes",
              "natalia lafourcade nunca es suficiente", "Estopa La raja de tu falda", "billy joel uptown girl"],
    # Each cap's query (test_the_common_fixture_is_past_each_cap_its_queries_meet), and the words beside them.
    "common": ["love", "love crooner", "love baby", "i love you baby", "baby love", "love 999", "love cyy", "lovee",
               "babby", "love babby", "croonr", "crooner", "serenade", "nat king cole love", "the supremes baby love"],
    "empty": [],
}


def queries(name: str) -> list[str]:
    return list(dict.fromkeys([*COMMON, *QUERIES[name]]))


# --- the records ----------------------------------------------------------------------------------------------------


def record(fn: str, fixture: str | None, args: Sequence[Any], kw: dict[str, Any], call: Callable[[], Any]) -> dict:
    """A record of what ``call`` answers. None of these functions raises for any query, so an exception is the
    generator's bug, never an answer to keep: it fails the test."""
    return {"fn": fn, "fixture": fixture, "args": list(args), "kw": kw, "out": plain(call())}


def sampled(names: Sequence[str]) -> list[str]:
    """``names`` less the middle of each run of names alike but for their numbers ("number-0-the-band" ...
    "number-300-the-band", "crooner_00" ... "crooner_49"): the first three of each and its last, in their order."""
    runs: dict[str, list[str]] = {}
    for name in names:
        runs.setdefault(re.sub(r"[0-9]+", "#", name), []).append(name)
    kept = {n for run in runs.values() for n in (*run[:3], run[-1])}
    return [n for n in names if n in kept]


def query_records(corpus: Corpus) -> list[dict]:
    from caracole import search
    from caracole.normalize import name_words
    from caracole.ug.key_search import rows_like

    texts = list(dict.fromkeys([q for name in FIXTURES for q in queries(name)]))
    out = []
    for text in texts:
        out.append(record("caracole.search._forms", None, [text], {}, lambda: search._forms(text)))
        tokens = name_words(text)
        out.append(record("caracole.search._patterns", None, [tokens], {}, lambda: search._patterns(tokens)))
        out.append(record("caracole.search._pinyin_runs", None, [tokens], {}, lambda: search._pinyin_runs(tokens)))
        out.append(record("caracole.search._queries", None, [text], {}, lambda: [
            {"text": q.text, "compact": q.compact, "runs": list(q.runs)} for q in search._queries(text)]))
    names = [("radiohead", "creep"), ("metallica", "creeping death"), ("soda stereo", "de musica ligera"),
             ("oasis", "wonderwall"), ("wonderwall", "in april"), ("misc mashups", "oasis wonderwall"),
             ("", "epic the musical not sorry for loving you"), ("acdc", "highway to hell"), ("r e m", "losing"),
             ("song dongye", "ban ma ban ma"), ("songdongye", "banma"), ("frenzal rhomb", "suburban male"),
             ("band maid", "thrill"), ("宋冬野", "斑马 斑马"), ("lynyrd skynyrd", "free bird"), ("", ""),
             ("eagles", "hotel california"), ("joaquin sabina", "19 dias y 500 noches")]
    for text in ["creep", "radiohead", "radiohead creep", "creep radiohed", "musica", "oasis wonderwall",
                 "wonderwall", "ac dc", "epic not sorry", "rem losing", "in april wonderwall", "x", "宋冬野", "斑马",
                 "宋冬野 斑马斑马", "banma", "skynyrd", "hotl califronia", "joaquin sabina 19 dias", "zzzz"]:
        for q in search._queries(text):
            for artist, title in names:
                out.append(record("caracole.search._Query", None, [q.text, list(q.runs), artist, title], {},
                                  lambda: {"readings": q.readings(artist, title), "score": q.score(artist, title),
                                           "name": q.name(artist), "holds": q.holds(artist, title)}))
    triples = [[(100.0, 90.0, 0.0), (0.0, 100.0, 100.0)], [(90.0, 90.0, 90.0)], [(0.0, 0.0, 95.5), (95.5, 0.0, 0.0)],
               [], [(70.0, 80.0, 75.0)]]
    for scores in triples:
        for reading in (None, "title", "both", "artist"):
            out.append(record("caracole.search._reading", None, [scores], {"reading": reading},
                              lambda: search._reading(scores, reading)))
    for text in ["creep", "宋冬野", "斑马", "banma", "radiohead creep", "alejandro sanz", "song dongye"]:
        for artists, title in ((["宋冬野"], "斑马，斑马"), (["Radiohead"], "Creep"),
                               (["Shakira", "Alejandro Sanz"], "La Tortura"), (["Song Dongye", "宋冬野"], "斑马斑马"),
                               ([], "Creep (Acoustic)")):
            for reading in (None, "title"):
                out.append(record("caracole.search._names_reading", None, [text, artists, title], {"reading": reading},
                                  lambda: search._names_reading(search._queries(text), artists, title, reading)))
    for name in FIXTURES:
        with corpus.conn(name) as conn:
            # One a set of patterns, as a query first gives it: in any order they bring in the same keys.
            sets: dict[frozenset[str], list[str]] = {}
            for q in queries(name):
                sets.setdefault(frozenset(p := search._patterns(name_words(q))), p)
            for p in [p for p in sets.values() if p]:
                out.append(record("caracole.ug.key_search.rows_like", name, [p], {}, lambda: rows_like(conn, p)))
    return out


def library_records(corpus: Corpus) -> list[dict]:
    from caracole import search
    from caracole.songs import list_songs

    out = []
    for name in FIXTURES:
        with corpus.conn(name) as conn:
            songs = list_songs(conn)
            for q in queries(name):
                out.append(record("caracole.search.search_library", name, [q], {},
                                  lambda: search.search_library(conn, q)))
                out.append(record("caracole.search.search_removed", name, [q], {},
                                  lambda: search.search_removed(conn, q)))
            for q in ("creep", "radiohead", "斑马"):
                for kw in ({"limit": 1}, {"limit": 5, "reading": "title"}, {"reading": "artist"}):
                    out.append(record("caracole.search.search_library", name, [q], kw,
                                      lambda: search.search_library(conn, q, **kw)))
                out.append(record("caracole.search.search_removed", name, [q], {"limit": 1},
                                  lambda: search.search_removed(conn, q, 1)))
            artists = list(dict.fromkeys([a for s in songs for a in (s.artists or [s.artist])]))
            for artist in [*artists, "Song Dongye", "Acdc", "R E M", "Nobody", ""]:
                for key in (None, "radiohead", "oasis", "song-dongye"):
                    out.append(record("caracole.search.library_by_artist", name, [artist], {"artist_key": key},
                                      lambda: search.library_by_artist(songs, artist, key)))
    return out


def _artist_keys(conn) -> list[str]:
    return sampled([r[0] for r in conn.execute("SELECT DISTINCT artist_key FROM ug_index ORDER BY artist_key")]) + \
        [r[0] for r in conn.execute("SELECT DISTINCT artist_key FROM ug_artist_tabs ORDER BY artist_key")] + \
        ["nobody-at-all", ""]


def _column(conn, sql: str, limit: int) -> list[str]:
    """The values ``sql`` selects, ``sampled``, the first ``limit``."""
    return sampled([r[0] for r in conn.execute(sql)])[:limit]


def index_records(corpus: Corpus) -> list[dict]:
    from caracole import search

    out = []
    for name in FIXTURES:
        with corpus.conn(name) as conn:
            for q in queries(name):
                out.append(record("caracole.search.find_index", name, [q], {}, lambda: search.find_index(conn, q)))
                out.append(record("caracole.search.found", name, [q], {}, lambda: search.found(
                    search.search_library(conn, q, 5), search.find_index(conn, q))))
                hits = lambda: [*(f := search.find_index(conn, q)).songs, *f.artists]  # noqa: E731
                out.append(record("caracole.search.bare_id_hint", name, [q], {},
                                  lambda: search.bare_id_hint(q, hits())))
                out.append(record("caracole.search.bare_id_unseen", name, [q], {},
                                  lambda: search.bare_id_unseen(q, hits())))
            for q in ("creep", "horse", "dylan", "oasis", "wonderwall", "宋冬野", "jones", "nelson"):
                for kw in ({"artists": 1}, {"songs": 2}, {"artists": 0, "songs": 0}, {"reading": "title"}):
                    out.append(record("caracole.search.find_index", name, [q], kw,
                                      lambda: search.find_index(conn, q, **kw)))
            for q in ("Joaquín Sabina", "斑马斑马", "宋冬野 斑马", "creep"):
                for artist in ("宋冬野", "Joaquín Sabina"):
                    out.append(record("caracole.search.bare_id_hint", name, [q], {"artist": artist},
                                      lambda: search.bare_id_hint(q, [*(f := search.find_index(conn, q)).songs,
                                                                      *f.artists], artist=artist)))
            for key in _artist_keys(conn):
                out.append(record("caracole.search.index_artist", name, [key], {},
                                  lambda: search.index_artist(conn, key)))
                out.append(record("caracole.search.artist_songs", name, [key], {},
                                  lambda: search.artist_songs(conn, key)))
            for key in ("radiohead", "oasis", "bob-dylan", "lynyrd-skynyrd", "eagles", "song-dongye-宋冬野"):
                for kw in ({"limit": 1}, {"limit": 1, "offset": 1}, {"limit": 3, "offset": 2}, {"title": "live"},
                           {"title": "song 1"}, {"title": "free"}, {"offset": 100}):
                    out.append(record("caracole.search.artist_songs", name, [key], kw,
                                      lambda: search.artist_songs(conn, key, **kw)))
    for key in ("misc-musicals", "misc-mashups", "misc", "miscellaneous", "radiohead", ""):
        out.append(record("caracole.search.no_ones", None, [key], {}, lambda: search.no_ones(key)))
    return out


def _sites(conn, q: str) -> list:
    """The other sites' answers /api/search hands ``suggestions`` (search_routes.py ``_suggested``)."""
    from caracole import search

    lc_artists, lc_songs = search.search_lacuerda(conn, q, songs=5)
    harp_artists, harp_songs = search.search_harptabs(conn, q, songs=5)
    return [*lc_artists, *lc_songs, *search.search_gtptabs(conn, q, 5), *search.search_musescore(conn, q, 5),
            *harp_artists, *harp_songs]


def suggest_records(corpus: Corpus) -> list[dict]:
    from caracole import search

    out = []
    for name in FIXTURES:
        with corpus.conn(name) as conn:
            for q in queries(name):
                out.append(record("caracole.search.suggest_artists", name, [q], {},
                                  lambda: search.suggest_artists(conn, q)))
                out.append(record("caracole.search.suggest_titles", name, [q], {},
                                  lambda: search.suggest_titles(conn, q)))
                out.append(record("caracole.search.suggestions", name, [q], {},
                                  lambda: search.suggestions(conn, q, search.find_index(conn, q))))
                out.append(record("caracole.search.suggestions", name, [q], {"sites": "api"},
                                  lambda: search.suggestions(conn, q, search.find_index(conn, q), _sites(conn, q))))
            for q in ("sabinna", "bily joel", "beyonse", "piano mann", "vino tintoo", "como camaon", "lynrd"):
                for kw in ({"limit": 1}, {"lacuerda": False}, {"harptabs": False}):
                    out.append(record("caracole.search.suggest_artists", name, [q], kw,
                                      lambda: search.suggest_artists(conn, q, **kw)))
                for kw in ({"limit": 1}, {"lacuerda": False}, {"harptabs": False}, {"gtptabs": False}):
                    out.append(record("caracole.search.suggest_titles", name, [q], kw,
                                      lambda: search.suggest_titles(conn, q, **kw)))
                for kw in ({"lacuerda": False}, {"harptabs": False}, {"gtptabs": False}):
                    out.append(record("caracole.search.suggestions", name, [q], {**kw, "sites": "api"},
                                      lambda: search.suggestions(conn, q, search.find_index(conn, q),
                                                                 _sites(conn, q), **kw)))
    return out


def site_records(corpus: Corpus) -> list[dict]:
    from caracole import search

    out = []
    for name in FIXTURES:
        with corpus.conn(name) as conn:
            for q in queries(name):
                out.append(record("caracole.search.search_gtptabs", name, [q], {},
                                  lambda: search.search_gtptabs(conn, q)))
                out.append(record("caracole.search.search_musescore", name, [q], {},
                                  lambda: search.search_musescore(conn, q)))
                out.append(record("caracole.search.search_harptabs", name, [q], {},
                                  lambda: search.search_harptabs(conn, q)))
                out.append(record("caracole.search.search_gametabs", name, [q], {},
                                  lambda: search.search_gametabs(conn, q)))
            for q in ("creep", "wonderwall", "main theme", "piano man", "billy joel", "yuzo koshiro"):
                for kw in ({"limit": 1}, {"limit": 10}):
                    for fn in ("search_gtptabs", "search_musescore", "search_gametabs"):
                        out.append(record(f"caracole.search.{fn}", name, [q], kw,
                                          lambda: getattr(search, fn)(conn, q, **kw)))
                for kw in ({"songs": 1}, {"artists": 1}, {"songs": 0, "artists": 0}):
                    out.append(record("caracole.search.search_harptabs", name, [q], kw,
                                      lambda: search.search_harptabs(conn, q, **kw)))
            for artist in ("Radiohead", "Elton John", "The Beatles", "Stone Temple Pilots", "Muse", "Silvana Estrada",
                           "宋冬野", "misc", "", " — "):
                out.append(record("caracole.search.gtptabs_songs", name, [artist], {},
                                  lambda: search.gtptabs_songs(conn, artist)))
            paths = _column(conn, "SELECT path FROM harptabs_index WHERE kind = 'artist' ORDER BY path", 40)
            for path in [*paths, "artist/9/nobody"]:
                out.append(record("caracole.search.harptabs_artist", name, [path], {},
                                  lambda: search.harptabs_artist(conn, path)))
                out.append(record("caracole.search.harptabs_songs", name, [path], {},
                                  lambda: search.harptabs_songs(conn, path)))
            for path, title in (("artist/1178/billy-joel", "vienna"), ("artist/1178/billy-joel", "piano"),
                                ("artist/50/the-beatles", "yesterday"), ("artist/7829/ritchie-valens", "donna")):
                out.append(record("caracole.search.harptabs_songs", name, [path], {"title": title},
                                  lambda: search.harptabs_songs(conn, path, title=title)))
    return out


def lacuerda_records(corpus: Corpus) -> list[dict]:
    from caracole import lacuerda_index as li
    from caracole import search

    out = []
    for name in FIXTURES:
        with corpus.conn(name) as conn:
            for q in queries(name):
                out.append(record("caracole.lacuerda_index.find", name, [q], {}, lambda: li.find(conn, q)))
                out.append(record("caracole.search.search_lacuerda", name, [q], {},
                                  lambda: search.search_lacuerda(conn, q)))
                out.append(record("caracole.search.lacuerda_leads", name, [q], {}, lambda: search.lacuerda_leads(
                    search.find_index(conn, q), search.search_lacuerda(conn, q)[0])))
            for q in ("ecos", "soda", "estopa", "andres", "banma"):
                for kw in ({"artists": 1}, {"songs": 0}, {"artists": 10, "songs": 10}):
                    out.append(record("caracole.lacuerda_index.find", name, [q], kw, lambda: li.find(conn, q, **kw)))
                    out.append(record("caracole.search.search_lacuerda", name, [q], kw,
                                      lambda: search.search_lacuerda(conn, q, **kw)))
            slugs = _column(conn, "SELECT DISTINCT artist_slug FROM lacuerda_index ORDER BY artist_slug", 60)
            for slug in [*slugs, "nobody"]:
                out.append(record("caracole.search.lacuerda_artist", name, [slug], {},
                                  lambda: search.lacuerda_artist(conn, slug)))
                out.append(record("caracole.search.lacuerda_songs", name, [slug], {},
                                  lambda: search.lacuerda_songs(conn, slug)))
            for slug, title in (("estopa", "tinto"), ("estopa", "mañana"), ("soda_stereo", "musica"),
                                ("song_dongye", "斑马")):
                out.append(record("caracole.search.lacuerda_songs", name, [slug], {"title": title},
                                  lambda: search.lacuerda_songs(conn, slug, title=title)))
            names = _column(conn, "SELECT DISTINCT artist FROM lacuerda_index ORDER BY artist", 60)
            for artist in [*names, "Los Enanitos Verdes", "Song Dongye", "Enanitos", "Nobody", ""]:
                out.append(record("caracole.search.lacuerda_artist_named", name, [artist], {},
                                  lambda: search.lacuerda_artist_named(conn, artist)))
            out.append(record("caracole.search.lacuerda_left_out", name, [], {},
                              lambda: search.lacuerda_left_out(conn)))
            out.append(record("caracole.lacuerda_index.letters_read", name, [], {}, lambda: li.letters_read(conn)))
    return out


def _parametrized(test: Callable) -> list[tuple]:
    """The cases a parametrized test of test_song_names.py lists."""
    return [tuple(case) for mark in test.pytestmark if mark.name == "parametrize" for case in mark.args[1]]


def names_records(corpus: Corpus) -> list[dict]:
    import test_song_names as tsn

    from caracole.song_names import clean, clean_channel, read_names
    from caracole.songs import list_songs

    out = []
    cleaned = [t for t, _ in _parametrized(tsn.test_a_text_loses_what_a_videos_title_adds_to_a_songs_name)]
    for text in [*cleaned, "Song (Official Music Video) [HD]", "「MV」 曲", "Artist – Title (Lyric Video) 4K", "''"]:
        out.append(record("caracole.song_names.clean", None, [text], {}, lambda: clean(text)))
    channels = [c for c, _ in _parametrized(tsn.test_a_channels_name_loses_its_label_words)]
    for channel in [*channels, "Silvana Estrada - Topic", "BTSVEVO", "Rosalía Official", "VEVO - Topic"]:
        out.append(record("caracole.song_names.clean_channel", None, [channel], {}, lambda: clean_channel(channel)))
    videos = [*_parametrized(tsn.test_a_videos_title_of_two_parts_is_its_artist_and_its_song),
              *_parametrized(tsn.test_a_videos_title_none_of_the_rules_reads_is_its_channels_song),
              (*tsn.VIKINGOS_VIDEO, None), (*tsn.SILVANA_VIDEO, None), ("Wonderwall - Oasis", "Oasis", None),
              ("Silvana Estrada Que problema", "kintanedu", None), ("Love Me Tender", "Elvis Presley - Topic", None)]
    texts = ["Silvana Estrada - Que problema", "Silvana Estrada – Que problema", "Silvana Estrada — Que problema",
             "Silvana Estrada | Que problema", "Muse - Hysteria - Live", "Nick Cani – Vikingos veganos",
             "宋冬野 - 斑马斑马", "Sílvana Éstrada - Qué problema", " - Creep", "Radiohead - ", "!! - Creep", "-", "",
             "Estopa - Como Camarón [Videoclip Oficial] HD", "“Bohemian Rhapsody” (Official Lyric Video)",
             "Somos vikingos veganos - Hyperfanes", "Hyperfanes - Vikingos", "Que problema by Silvana Estrada",
             "Stand by Me by Ben E King", "Que problema BY silvana estrada", "Que problema by Nick Cani", "Stand by Me",
             "Ben E King Stand by Me", "Silvana Estrada Que problema", "silvana estrada que problema",
             "Silvana Estrada Qué problema", "silvana  estrada   qué problema", "Sílvana Estrada Que problema",
             "Silvana Estrada Tregua", "Silvana Estrada Y", "Que problema", "Estrada de tierra",
             "Nick Cani Vikingos veganos", "Silvana", "Silvana Estrada", "Silvana Estrada !!", "   ",
             "Silvanas Adio Maria", "Love Me Tender", "Love Alone Again Or", "natalia lafourcade Nunca es suficiente",
             "bjork army of me", "Joaquín Sabina 19 días y 500 noches", "joaquin sabina y nos dieron las diez",
             "Estopa La raja de tu falda", "Hasta la Raíz", "Billy Joel Uptown girl", "Silvana Tregua",
             "silvana tregua", "Hyperfanes Somos vikingos veganos", "hyperfanes Somos vikingos veganos",
             "nick cani vikingos veganos", "onda una mas", "Onda Una más", "lumbre agua", "creep"]
    for name in [None, *FIXTURES]:
        with corpus.conn(name) if name else _no_conn() as conn:
            songs = list_songs(conn) if conn is not None else ()
            for text in list(dict.fromkeys([*texts, *(queries(name) if name else ())])):
                out.append(record("caracole.song_names.read_names", name, [text], {},
                                  lambda: read_names(conn, text, songs=songs)))
            for title, channel, *_ in videos:
                out.append(record("caracole.song_names.read_names", name, [title], {"channel": channel},
                                  lambda: read_names(conn, title, songs=songs, channel=channel)))
    return out


@contextmanager
def _no_conn() -> Iterator[None]:
    yield None


# --- /api/search and /api/artist -------------------------------------------------------------------------------------

CARD = ("links", "files", "source", "key", "instruments")


def masked(value: Any) -> Any:
    """``value`` with what a song's card says of its folder's files as ``"*"``: in every object with ``links``."""
    if isinstance(value, list):
        return [masked(v) for v in value]
    if isinstance(value, dict):
        card = "links" in value
        return {k: "*" if card and k in CARD else masked(v) for k, v in value.items()}
    return value


def _app(state: Path):
    from caracole.config import load_config
    from caracole.web.app import WebApp
    from caracole.web.jobs import JobQueue

    cfg = load_config(None, env={"HOME": str(state / "home"), "STATE_DIRECTORY": str(state / "state"),
                                 "CACHE_DIRECTORY": str(state / "cache")})

    def runner(args, emit):  # nothing is queued by a read
        raise AssertionError(f"a search queued {args}")

    return WebApp(cfg, JobQueue(runner, limit=1), allowed=frozenset({"localhost"}), csrf="tok",
                  searches_lacuerda=False, searches_youtube=False)


@contextmanager
def _as_the_phone() -> Iterator[None]:
    """What the phone answers null in its place: no progression read."""
    from unittest import mock

    with mock.patch("caracole.progressions.read_progression", lambda text: None):
        yield


# What /api/search folds before it searches, over the ug fixture: the query's words joined by one space (Python's
# whitespace: Unicode's spaces, NEL, U+001C-U+001F, U+2028; never a zero-width space), cut at 200 code points (an
# emoji is one), and too short to search by fewer than three letters or digits (two for Chinese) as str.isalnum
# counts them (Ⅻ and ² are). Then the address itself, as parse_qs reads it: a bad escape kept, bad UTF-8 replaced,
# the first of two fields, none at all.
API_TEXTS = ["宋冬野\u3000斑马", "creep\u00a0radiohead", "\tcreep\n", "creep\x85radiohead", "\u200bcreep",
             "\x1ccreep\x1f", "creep\u2028radiohead", "creep\u2003\u2003radiohead", "creep+radiohead", "宋", "宋冬",
             "a1", "ab1", "😀😀😀", "a😀b", "Ⅻ", "Ⅻ²³", "²³¹", "x" * 250, "creep " + "😀" * 300, "😀" * 199 + " creep",
             "radiohead " * 30]
API_RAW = ["/api/search?q=%ZZcreep&box=corpus", "/api/search?q=caf%C3&box=corpus",
           "/api/search?q=creep&q=oasis&box=corpus", "/api/search?box=corpus", "/api/search?q=creep",
           "/api/search?q=creep&box=not%20a%20box", "/api/search?q=+creep+&box=corpus"]
# /api/artist's fields as the route reads them, on every fixture: harptabs before LaCuerda's, a slug before a name,
# each stripped of Python's whitespace (NBSP, NEL, U+3000).
API_ARTIST = ["/api/artist?lacuerda=estopa&lacuerda_name=Nobody", "/api/artist?lacuerda=&lacuerda_name=Estopa",
              "/api/artist?lacuerda_name=%E3%80%80Estopa%E3%80%80", "/api/artist?lacuerda=%C2%85estopa",
              "/api/artist?key=%C2%A0radiohead%C2%A0&offset=0", "/api/artist?key=radiohead&offset=%201%20",
              "/api/artist?harptabs=artist/1178/billy-joel&lacuerda=estopa"]


def api_records(corpus: Corpus) -> list[dict]:
    from caracole.web.app import Request

    out = []
    with _as_the_phone():
        for name in FIXTURES:
            app = _app(corpus.state(name))
            paths = [f"/api/search?{urlencode({'q': q, 'box': 'corpus'})}" for q in queries(name)]
            if name == "ug":
                paths += [f"/api/search?{urlencode({'q': q, 'box': 'corpus'})}" for q in API_TEXTS] + API_RAW
            with corpus.conn(name) as conn:
                keys = _artist_keys(conn)[:30]
                slugs = _column(conn, "SELECT DISTINCT artist_slug FROM lacuerda_index ORDER BY artist_slug", 20)
                harps = _column(conn, "SELECT path FROM harptabs_index WHERE kind = 'artist' ORDER BY path", 20)
            paths += [f"/api/artist?key={quote(k)}&offset=0" for k in keys]
            paths += [f"/api/artist?key={quote(k)}&offset=1" for k in keys[:3]]
            paths += ["/api/artist?key=bob-dylan&offset=50", "/api/artist?key=", "/api/artist?key=radiohead&offset=x",
                      "/api/artist?key=nobody-at-all&offset=0", "/api/artist"]
            paths += [f"/api/artist?lacuerda={quote(s)}" for s in slugs]
            paths += [f"/api/artist?lacuerda_name={quote(n)}" for n in ("Estopa", "Los Enanitos Verdes", "宋冬野",
                                                                         "Nobody", "")]
            paths += ["/api/artist?lacuerda=nobody", "/api/artist?lacuerda=NOT%20A%20SLUG"]
            paths += [f"/api/artist?harptabs={quote(p)}" for p in harps]
            paths += ["/api/artist?harptabs=artist/9/nobody", "/api/artist?harptabs=not-a-path", *API_ARTIST]
            for path in paths:
                response = app.handle(Request("GET", path, {"host": "localhost"}))
                out.append({"fn": "caracole.web.app.WebApp.handle", "fixture": name, "args": ["GET", path], "kw": {},
                            "out": {"status": response.status, "json": masked(json.loads(response.body))}})
    return out


# --- the corpus -----------------------------------------------------------------------------------------------------

MAKERS: dict[str, Callable[[Corpus], list[dict]]] = {
    "query": query_records, "library": library_records, "index": index_records, "suggest": suggest_records,
    "sites": site_records, "lacuerda": lacuerda_records, "names": names_records,
}


def vector_text(corpus: Corpus, name: str) -> str:
    return jsonl(MAKERS[name](corpus), corpus=f"search/{name}", made_by=MADE_BY)


def api_text(corpus: Corpus) -> str:
    return jsonl(api_records(corpus), corpus="web/api_search", made_by=MADE_BY)


def every_file(workdir: Path) -> dict[Path, str]:
    """Every file of this corpus, by its path, made in ``workdir``."""
    corpus = Corpus(workdir)
    files = {SEARCH / "fixtures" / f"{name}.jsonl": corpus.fixture_text(name) for name in FIXTURES}
    files.update({SEARCH / f"{name}.jsonl": vector_text(corpus, name) for name in FILES})
    files[API] = api_text(corpus)
    return files


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> Corpus:
    return Corpus(tmp_path_factory.mktemp("search-corpus"))


@pytest.mark.parametrize("name", list(FIXTURES))
def test_a_fixture_is_its_library_dumped(corpus, name):
    check(SEARCH / "fixtures" / f"{name}.jsonl", corpus.fixture_text(name))


def test_a_fixture_replayed_dumps_as_it_was_built(corpus, tmp_path):
    # Replayed as Corpus.state replays it, into a database of its own: the shared one is read by the other tests,
    # and a read may write (songs.ensure_current_keys stamps songs:key_version in the empty fixture's), whatever
    # order the workers run them in.
    for name in FIXTURES:
        records = read_fixture(corpus.fixture_text(name))
        with closing(_fresh(tmp_path / name / "caracole.sqlite")) as conn:
            replay_fixture(conn, records)
            again = [r for r in dump_fixture(conn) if r.get("kv") != "phone:schema"]
        assert again == records, name


# Each cap the common fixture passes: the module and its constant, the query its vectors hold for it
# (QUERIES["common"]), and a call over the fixture that meets it.
CAPS = [
    ("caracole.ug.key_search", "KEYS_PER_PATTERN", "love",
     lambda conn: _of("ug.key_search").rows_like(conn, ["%love%"])),
    ("caracole.search", "CLOSE_TABS", "lovee",
     lambda conn: _of("search").suggest_titles(conn, "lovee", lacuerda=False)),
    ("caracole.search", "CLOSE_ARTISTS", "croonr", lambda conn: _of("search").suggest_artists(conn, "croonr")),
    ("caracole.search", "SITE_ROWS_READ", "love cyy", lambda conn: _of("search").search_gtptabs(conn, "love cyy")),
    ("caracole.lacuerda_index", "ROWS_READ", "love babby", lambda conn: _of("lacuerda_index").find(conn, "love babby")),
    ("caracole.search", "SITE_TITLES_READ", "lovee", lambda conn: _of("search").suggest_titles(conn, "lovee")),
]


def _of(module: str):
    import importlib

    return importlib.import_module(f"caracole.{module}")


@pytest.mark.parametrize("module, cap, query, call", CAPS, ids=[c[1] for c in CAPS])
def test_the_common_fixture_is_past_each_cap_its_queries_meet(corpus, monkeypatch, module, cap, query, call):
    # The answer with the cap lifted is another: a port that drops the cap, or cuts other rows, fails its vectors.
    assert query in QUERIES["common"]
    with corpus.conn("common") as conn:
        capped = plain(call(conn))
        monkeypatch.setattr(_of(module.removeprefix("caracole.")), cap, 10 ** 6)
        assert plain(call(conn)) != capped


def test_the_common_fixtures_key_of_two_words_comes_from_the_keys_every_pattern_is_in(corpus):
    # "love crooner": a key of both words longer than the shortest of either, which neither pattern alone brings in.
    from caracole.normalize import name_words
    from caracole.search import _patterns
    from caracole.ug.key_search import rows_like

    patterns = _patterns(name_words("love crooner"))
    with corpus.conn("common") as conn:
        alone = {(a, s) for p in patterns for a, s, _ in rows_like(conn, [p])}
        both = {(a, s) for a, s, _ in rows_like(conn, patterns)}
    assert both - alone == {("the-love-crooners", "love-me-tender")}
    assert "love crooner" in QUERIES["common"]


@pytest.mark.slow  # every fixture searched: a second or two each
@pytest.mark.parametrize("name", FILES)
def test_a_vector_is_what_search_answers_over_the_fixtures(corpus, name):
    check(SEARCH / f"{name}.jsonl", vector_text(corpus, name))


@pytest.mark.slow
def test_api_search_is_what_caracole_serve_answers_over_the_fixtures(corpus):
    check(API, api_text(corpus))


@pytest.mark.slow  # the whole corpus made twice, in two processes
def test_the_corpus_is_the_same_whatever_the_hash_seed(tmp_path):
    from conftest import subprocess_pythonpath

    env = {**os.environ, "PYTHONPATH": subprocess_pythonpath(f"{SRC}{os.pathsep}{TESTS}"),
           "CARACOLE_YTDLP_BIN": str(tmp_path / "no-yt-dlp"), "CARACOLE_SERVICE_FILE": str(tmp_path / "no-service")}
    script = "import sys, test_conformance_search as m; m.write_all(sys.argv[1], sys.argv[2])"
    running = {seed: subprocess.Popen([sys.executable, "-c", script, str(tmp_path / f"seed-{seed}"),
                                       str(tmp_path / f"work-{seed}")], env={**env, "PYTHONHASHSEED": seed}, cwd=TESTS)
               for seed in ("1", "2")}
    made = {}
    for seed, process in running.items():
        assert process.wait(timeout=300) == 0, seed
        out = tmp_path / f"seed-{seed}"
        made[seed] = {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*")) if p.is_file()}
    assert made["1"].keys() == made["2"].keys() and made["1"]
    for path in made["1"]:
        assert made["1"][path] == made["2"][path], path


def write_all(out: str, workdir: str) -> None:
    """Every file of the corpus written under ``out`` (by its path under tests/conformance/vectors), made in
    ``workdir``: what the hash seed test compares."""
    for path, text in every_file(Path(workdir)).items():
        target = Path(out) / path.relative_to(VECTORS)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

