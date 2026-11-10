"""The fake sites server: what a scenario's sites answer, for lookups end to end against no real site (the Android
plan's §9, lane lookups-e2e: tests/test_android_e2e.py's lookups phase on the JVM, LookupOnDeviceTest on the
emulator), and a caracole of the computer's sent there too::

    python -m tests.helpers.fake_sites serve lookups PORT [--address 127.0.0.1]
    python -m tests.helpers.fake_sites caracole http://127.0.0.1:PORT --config FILE get "Artist - Title"

``serve`` (in nix develop, from the repository's root) answers on PORT, never 8737 (the owner's caracole-web), every
request a caracole sends a site as Kotlin's ``core.http.RoutedTransport`` carries it: ``GET /fetch?url=<the site's
URL, quoted>``, with the headers it was sent with (the user agent). The site's URL is answered as the site would:

- Ultimate Guitar's tab pages and artist page, made by ug_pages.py as UG makes them, a chart of the song's made-up
  words (chords over words that are no song's), and its other versions listed on each, as UG lists them;
- LRCLIB's ``/api/get`` (a record in tests/fixtures/lrclib/get_hit.json's shape, or its 404) and ``/api/search``
  (those records whose names fit, else ``[]``);
- Megalobiz's search (megalobiz_site.py's fake, with no record: a search finds nothing), AZLyrics' artist pages
  (azlyrics_site.py's 404: it lists none of the scenario's artists) and LaCuerda's (its 404 page,
  tests/fixtures/lacuerda/not_found.html);
- gtptabs.com's artist pages (``/tabs/<n>/<artist>.html``, which a lookup asks for an artist gtptabs.com's index
  lists, as the computer's lists Traditional): gtptabs_site.py's page of the artist, listing none of the scenario's
  songs, so that gtptabs.com has no Guitar Pro file of them.

A URL the scenario has no rule for gets its site's 404 and is logged as unknown (on stderr, ``known`` false), so that
a caracole asking a URL the computer's wouldn't is seen, never read as the site's miss; one robots.txt closes
(``caracole.http.robots_disallows``) is never answered either, a 404, logged ``closed``. Every request is counted, in
order, and its own routes, which no site is, say what was asked:

- ``GET /log`` (``?since=N``: those after the N-th): ``{"requests": [{"n", "url", "provider", "status", "known",
  "closed", "user_agent"}, ...]}``, each as it came;
- ``GET /scenario.json``: ``document(name)``, what each of the scenario's songs is for (below), with the names and
  keys a search of its index finds it by;
- ``GET /index.sqlite``: Ultimate Guitar's index of the scenario's songs, as ``caracole index export`` writes one
  (built from a sitemap as ``caracole index build --from`` reads one), for a phone to import as the computer's;
- ``GET /``: a line saying it is up.

``caracole SITES ARGS…`` runs caracole's CLI (``python -m caracole ARGS``) with every client's transport routed to the
server at SITES (``routed``, RoutedTransport's twin in httpx), so that the computer looks a song up against the same
pages the phone does. In a test, ``FakeSites(name)`` is the server on a free port of 127.0.0.1, in a thread
(``with FakeSites("lookups") as sites: sites.url``).

The scenario ``lookups`` (``LOOKUPS``): five songs, each with a part (``role``) in the lookups the phase makes:

- ``get_it``, Thomas Moore's The Minstrel Boy: four chords versions in UG's index and on each of its pages, the best
  rated first, and LRCLIB's timed lyrics. Get it on its search row keeps its sheet; Fetch them keeps more of its
  versions. Every page of it read again says a few votes more (``VOTES_PER_READ``): UG's ratings change between two
  reads, so a song looked up on two caracoles between two syncs differs in them (the plan's §11, Q2).
- ``fetch_now``, Thomas Moore's Oft in the Stilly Night: one version, and no lyrics on any site: asked for with no
  fetch, then Fetch now on its card.
- ``artist_page``, Thomas Moore's The Last Rose of Summer: a tab at a bare ``/tab/<id>``, in no sitemap, listed on
  Thomas Moore's artist page alone (A6), which his other pages name (``artist_url``): asked for with Fetch now.
- ``closed``, The Wild Rover (Traditional): its tab page answers a 301 to its print view, ``/tab/print?id=…``, which
  robots.txt closes: a redirect a caracole never follows, an error and never a miss.
- ``blocked``, Whiskey in the Jar (Traditional): its tab page answers 403, a block.

The standard library alone at import, so that e2e_library.py can import its songs; caracole, httpx and the suite's
helpers are imported where they are used.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import tempfile
import threading
import unicodedata
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
TESTS = REPO / "tests"
FIXTURES = TESTS / "fixtures"

OWNERS_PORT = 8737  # caracole-web, the owner's service: never this server's
NOW = datetime(2026, 10, 22, 3, 0, tzinfo=UTC)
UG_TAB = "https://tabs.ultimate-guitar.com/tab/"
UG_WWW = "https://www.ultimate-guitar.com"
VOTES_PER_READ = 3  # a page of the get_it song read again says this many votes more

# Each site's hosts, by the provider caracole names it (config.DEFAULT_PROVIDERS).
HOSTS = {
    "tabs.ultimate-guitar.com": "ug", "www.ultimate-guitar.com": "ug", "ultimate-guitar.com": "ug",
    "lrclib.net": "lrclib",
    "api.megalobiz.com": "megalobiz", "megalobiz.com": "megalobiz", "www.megalobiz.com": "megalobiz",
    "www.azlyrics.com": "azlyrics", "azlyrics.com": "azlyrics",
    "acordes.lacuerda.net": "lacuerda",
    "gtptabs.com": "gtptabs", "www.gtptabs.com": "gtptabs",
    "www.harptabs.com": "harptabs", "harptabs.com": "harptabs",
    "gametabs.net": "gametabs", "www.gametabs.net": "gametabs",
    "musescore.com": "musescore",
    "www.youtube.com": "youtube", "i.ytimg.com": "ytimg",
}


@dataclass(frozen=True)
class Artist:
    name: str
    id: int

    @property
    def page(self) -> str:
        """The address of the artist's page, as UG writes it (ug_pages.artist_path): /artist/thomas_moore_70001."""
        stripped = re.sub(r"[\W_]+", "_", _fold(self.name)).strip("_")
        return f"{UG_WWW}/artist/{stripped}_{self.id}"


@dataclass(frozen=True)
class SiteSong:
    """A song of a scenario: what its part is (``role``), its names and chart, and what the sites hold of it."""

    role: str
    artist: Artist
    title: str
    key: str  # the chart's key
    chords: tuple[str, ...]
    tabs: tuple[int, ...] = ()  # its chords versions in UG's index, best rated first: slugged pages
    bare: int | None = None  # its one tab, at a bare /tab/<id>, on the artist's page alone
    lyrics: bool = False  # LRCLIB has its timed lyrics
    blocked: bool = False  # UG answers its tab page with a 403
    closed: bool = False  # UG answers its tab page with a 301 to its print view, which robots.txt closes
    query: str = ""  # what a search for it types (a song of UG's index)

    def tab_url(self, tab: int) -> str:
        if self.bare is not None:
            return f"{UG_TAB}{tab}"
        return f"{UG_TAB}{slug(self.artist.name)}/{slug(self.title)}-chords-{tab}"

    def print_url(self, tab: int) -> str:
        """Its tab's print view, where a ``closed`` song's page redirects: robots.txt closes ``/tab/print?``."""
        return f"{UG_TAB}print?id={tab}"

    @property
    def every_tab(self) -> tuple[int, ...]:
        return self.tabs if self.bare is None else (self.bare,)


THOMAS_MOORE = Artist("Thomas Moore", 70001)
TRADITIONAL = Artist("Traditional", 70002)
LOOKUPS = (
    SiteSong("get_it", THOMAS_MOORE, "The Minstrel Boy", "Am", ("Am", "G", "C", "E"),
             tabs=(7000001, 7000002, 7000003, 7000004), lyrics=True, query="minstrel boy"),
    SiteSong("fetch_now", THOMAS_MOORE, "Oft in the Stilly Night", "D", ("D", "G", "A", "Bm"), tabs=(7000011,)),
    SiteSong("artist_page", THOMAS_MOORE, "The Last Rose of Summer", "G", ("G", "C", "D", "Em"), bare=7000021),
    SiteSong("closed", TRADITIONAL, "The Wild Rover", "C", ("C", "F", "G", "Am"), tabs=(7000041,), closed=True,
             query="wild rover"),
    SiteSong("blocked", TRADITIONAL, "Whiskey in the Jar", "G", ("G", "Em", "C", "D"), tabs=(7000031,),
             blocked=True, query="whiskey in the jar"),
)
SCENARIOS = {"lookups": LOOKUPS}


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def slug(name: str) -> str:
    """A name as Ultimate Guitar's addresses write it: "Oft in the Stilly Night" is oft-in-the-stilly-night."""
    return re.sub(r"[^a-z0-9]+", "-", _fold(name).lower()).strip("-")


def index_rows(name: str = "lookups") -> list[tuple[str, str, int]]:
    """The scenario's rows of UG's index, as its sitemaps list them: (artist slug, song slug, tab id) of each slugged
    chords version (never a bare tab, which no sitemap lists)."""
    return [(slug(s.artist.name), slug(s.title), tab) for s in SCENARIOS[name] for tab in s.tabs]


def sitemap(rows: Sequence[tuple[str, str, int]]) -> str:
    """A sitemap of UG's tab pages, as ``caracole index build --from`` reads one."""
    urls = "".join(f"<url><loc>{UG_TAB}{a}/{s}-chords-{tab}</loc></url>\n" for a, s, tab in rows)
    return (f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{urls}</urlset>\n")


def chart(title: str, chords: Sequence[str], version: int = 1) -> str:
    """A chart in Ultimate Guitar's markup: two verses and a chorus, each line's two chords over its made-up words."""
    lines = [f"{title}: a chart made up for caracole's tests, version {version}"]
    for section in ("Verse 1", "Chorus", "Verse 2"):
        lines.append(f"[{section}]")
        for n in range(4):
            first, second = chords[n % len(chords)], chords[(n + 1) % len(chords)]
            lines.append(f"[tab][ch]{first}[/ch]" + " " * (16 - len(first)) + f"[ch]{second}[/ch]")
            lines.append(f"Made-up words of {section.lower()}, line {n + 1}, for the lookups[/tab]")
    return "\r\n".join(lines) + "\r\n"


def lyrics_lines() -> list[str]:
    """The made-up words a chart of the scenario sings, LRCLIB's lines of it."""
    return [f"Made-up words of {section.lower()}, line {n + 1}, for the lookups"
            for section in ("Verse 1", "Chorus", "Verse 2") for n in range(4)]


# --- the scenario's document, from its index --------------------------------------------------------------------


def build_index(conn: sqlite3.Connection, folder: Path, name: str = "lookups") -> None:
    """The scenario's songs into ``conn``'s UG index, read from a sitemap written in ``folder`` as ``caracole index
    build --from`` reads one (its records, so that a merge takes them)."""
    from caracole.ug.index import build_index as build

    folder.mkdir(parents=True, exist_ok=True)
    (folder / "sitemap1.xml").write_text(sitemap(index_rows(name)), encoding="utf-8")
    build(conn, None, NOW, from_dir=folder)


def document(conn: sqlite3.Connection, name: str = "lookups") -> dict:
    """What each of the scenario's songs is for, by its part (``role``): its names as the scenario writes them and
    its identity key; for a song of the index, its query and the row a search finds it by (search.py's
    ``search_index`` over ``conn``'s index: the names it gives, their identity key, ``ug`` its pick,
    artist-key/song-key); its tab pages and its artist's page; and the lookup limits it is held to
    (config.DEFAULT_PROVIDERS': each provider's ``lookup_requests`` and ``lookup_per_hour``)."""
    from caracole.config import DEFAULT_PROVIDERS
    from caracole.normalize import identity_key, ug_slug_key
    from caracole.search import search_index

    songs = {}
    for song in SCENARIOS[name]:
        entry = {"artist": song.artist.name, "title": song.title, "key": identity_key(song.artist.name, song.title),
                 "tabs": [song.tab_url(t) for t in song.every_tab], "artist_page": song.artist.page,
                 "lyrics": song.lyrics, "blocked": song.blocked,
                 "closed": [song.print_url(t) for t in song.every_tab] if song.closed else []}
        if song.query:
            want = (ug_slug_key(slug(song.artist.name)), ug_slug_key(slug(song.title)))  # as ug_index keeps them
            hit = next((h for h in search_index(conn, song.query) if (h.artist_key, h.song_key) == want), None)
            if hit is None:
                hits = [(h.artist_key, h.song_key) for h in search_index(conn, song.query)]
                raise AssertionError(f"search_index({song.query!r}) doesn't find {want}: {hits}")
            entry["search"] = {"query": song.query, "ug": f"{hit.artist_key}/{hit.song_key}", "artist": hit.artist,
                               "title": hit.title, "key": identity_key(hit.artist, hit.title)}
        songs[song.role] = entry
    limits = {provider: {"lookup_requests": p.lookup_requests, "lookup_per_hour": p.lookup_per_hour}
              for provider, p in DEFAULT_PROVIDERS.items()}
    return {"format": 1, "scenario": name, "songs": songs, "limits": limits, "hosts": HOSTS}


# --- what the sites answer --------------------------------------------------------------------------------------


@dataclass
class Answer:
    status: int
    content_type: str
    body: bytes
    known: bool = True
    location: str | None = None  # a redirect's


HTML = "text/html; charset=utf-8"
JSON = "application/json; charset=utf-8"


def _fixture(path: str) -> bytes:
    return (FIXTURES / path).read_bytes()


class Sites:
    """The scenario's sites: ``answer(url)`` is what the site at ``url`` answers. Thread-safe: the get_it song's
    pages count their reads (``VOTES_PER_READ``)."""

    def __init__(self, name: str = "lookups"):
        if str(TESTS) not in sys.path:  # the suite's helpers, when run as python -m tests.helpers.fake_sites
            sys.path.insert(0, str(TESTS))
        self.name = name
        self.songs = SCENARIOS[name]
        self._lock = threading.Lock()
        self._reads: dict[str, int] = {}
        from helpers.azlyrics_site import FakeAzLyrics
        from helpers.megalobiz_site import FakeMegalobiz

        self.megalobiz = FakeMegalobiz()  # no record: a search finds nothing
        self.azlyrics = FakeAzLyrics(pages={})  # no page: an artist it hasn't got is its 404

    # Ultimate Guitar.

    def _version(self, song: SiteSong, tab: int, reads: int) -> dict:
        from helpers.ug_pages import version_dict

        n = song.every_tab.index(tab)
        votes = 120 - 20 * n + (VOTES_PER_READ * max(reads - 1, 0) if song.role == "get_it" else 0)
        return version_dict(tab, song=song.title, artist=song.artist.name, artist_id=song.artist.id,
                            version=n + 1, rating=round(4.8 - 0.3 * n, 2), votes=votes, tonality_name=song.key,
                            tab_url=song.tab_url(tab), artist_url=song.artist.page)

    def _tab_page(self, song: SiteSong, tab: int) -> Answer:
        from helpers.ug_pages import make_tab_page_html

        if song.blocked:
            return Answer(403, HTML, b"<html><head><title>Access denied</title></head><body>Forbidden</body></html>")
        if song.closed:
            return Answer(301, HTML, b"<html><title>Moved</title></html>", location=song.print_url(tab))
        with self._lock:
            reads = self._reads[song.tab_url(tab)] = self._reads.get(song.tab_url(tab), 0) + 1
        own = self._version(song, tab, reads)
        others = [self._version(song, t, reads) for t in song.every_tab if t != tab]
        n = song.every_tab.index(tab)
        page = make_tab_page_html(own, others, content=chart(song.title, song.chords, n + 1),
                                  artist_url=song.artist.page)
        return Answer(200, HTML, page.encode("utf-8"))

    def _artist_page(self, artist: Artist) -> Answer:
        from helpers.ug_pages import make_artist_page_html

        tabs = [self._version(s, t, 1) for s in self.songs if s.artist == artist for t in s.every_tab]
        page = make_artist_page_html(artist.id, artist.name, tabs, path=urllib.parse.urlsplit(artist.page).path)
        return Answer(200, HTML, page.encode("utf-8"))

    def _ug(self, url: str, parts: urllib.parse.SplitResult) -> Answer | None:
        if parts.hostname == "tabs.ultimate-guitar.com" and not parts.query:
            for song in self.songs:
                for tab in song.every_tab:
                    if url == song.tab_url(tab):
                        return self._tab_page(song, tab)
        if parts.hostname == "www.ultimate-guitar.com":
            for artist in {s.artist for s in self.songs}:
                if f"{UG_WWW}{parts.path}" == artist.page:
                    query = urllib.parse.parse_qs(parts.query)
                    if query.get("page", ["1"]) == ["1"]:
                        return self._artist_page(artist)
        return None

    # LRCLIB.

    def _record(self, song: SiteSong, n: int) -> dict:
        record = json.loads(_fixture("lrclib/get_hit.json"))
        lines = lyrics_lines()
        record.update(id=990000 + n, name=song.title, trackName=song.title, artistName=song.artist.name,
                      albumName="", duration=180.0, instrumental=False, hasWordSync=False,
                      plainLyrics="\n".join(lines),
                      syncedLyrics="\n".join(f"[00:{10 + 4 * i:02d}.00] {line}" for i, line in enumerate(lines)))
        record.pop("lyricsfile", None)
        return record

    def _lyrics(self) -> list[tuple[SiteSong, dict]]:
        return [(s, self._record(s, n)) for n, s in enumerate(self.songs) if s.lyrics]

    def _lrclib(self, parts: urllib.parse.SplitResult) -> Answer | None:
        from caracole.normalize import fold

        params = dict(urllib.parse.parse_qsl(parts.query))

        def same(a: str, b: str) -> bool:
            return fold(a).lower().strip() == fold(b).lower().strip()

        if parts.path == "/api/get":
            for song, record in self._lyrics():
                if same(params.get("artist_name", ""), song.artist.name) and \
                        same(params.get("track_name", ""), song.title):
                    return Answer(200, JSON, json.dumps(record).encode("utf-8"))
            return Answer(404, JSON, b'{"code":404,"name":"TrackNotFound","message":"Failed to find specified track"}')
        if parts.path == "/api/search":
            title = fold(params.get("track_name", params.get("q", ""))).lower()
            found = [record for song, record in self._lyrics() if title and title in fold(song.title).lower()]
            return Answer(200, JSON, json.dumps(found).encode("utf-8"))
        return None

    # gtptabs.com.

    def _gtptabs_artist(self, path: str) -> Answer | None:
        from helpers.gtptabs_site import artist_page

        artist = re.fullmatch(r"/tabs/\d+/([a-z0-9]+(?:-[a-z0-9]+)*)\.html", path)
        if artist is None:
            return None
        name = " ".join(word.capitalize() for word in artist[1].split("-"))
        return Answer(200, HTML, artist_page(name, path.lstrip("/")).encode("utf-8"))

    # The rest: the suite's fakes, or the site's 404.

    def _fake(self, handler, url: str) -> Answer | None:
        import httpx

        try:
            response = handler(httpx.Request("GET", url))
        except AssertionError:
            return None
        return Answer(response.status_code, response.headers.get("content-type", HTML), response.content)

    def answer(self, url: str) -> Answer:
        """What the site at ``url`` answers: the scenario's page, its site's answer of nothing, or (``known`` false)
        the site's 404 for a URL the scenario has no rule for."""
        parts = urllib.parse.urlsplit(url)
        provider = HOSTS.get(parts.hostname or "")
        found: Answer | None = None
        if provider == "ug":
            found = self._ug(url, parts)
        elif provider == "lrclib":
            found = self._lrclib(parts)
        elif provider == "megalobiz" and parts.hostname == "api.megalobiz.com":
            found = self._fake(self.megalobiz.handler, url)
        elif provider == "azlyrics" and re.fullmatch(r"/([a-z]|19)/[a-z0-9]+\.html", parts.path):
            found = self._fake(self.azlyrics.handler, url)
        elif provider == "lacuerda" and re.fullmatch(r"/[a-z0-9_]+/", parts.path):
            found = Answer(404, HTML, _fixture("lacuerda/not_found.html"))
        elif provider == "gtptabs" and not parts.query:
            found = self._gtptabs_artist(parts.path)
        if found is not None:
            return found
        return Answer(404, JSON if provider == "lrclib" else HTML, b"<html><title>Not Found</title></html>",
                      known=False)


# --- the server ---------------------------------------------------------------------------------------------------


class FakeSites:
    """The server of scenario ``name`` on ``address``:``port`` (a free one with 0), in a thread of this process
    until ``stop`` (a context manager too); ``url`` its address, ``requests`` every request it was sent so far."""

    def __init__(self, name: str = "lookups", port: int = 0, address: str = "127.0.0.1"):
        if port == OWNERS_PORT:
            raise ValueError(f"port {OWNERS_PORT} is the owner's caracole-web: the fake sites take another")
        self.name = name
        self.sites = Sites(name)
        self._requests: list[dict] = []
        self._lock = threading.Lock()
        self._folder = tempfile.TemporaryDirectory(prefix="caracole-fake-sites-")
        self._index: bytes | None = None
        self._document: dict | None = None
        self._server = ThreadingHTTPServer((address, port), _handler(self))
        self._server.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def url(self) -> str:
        host = self._server.server_address[0]
        return f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{self.port}"

    @property
    def requests(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._requests]

    def start(self) -> FakeSites:
        self._thread = threading.Thread(target=self._server.serve_forever, name="fake-sites", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._folder.cleanup()

    def __enter__(self) -> FakeSites:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def _built(self) -> None:
        """The scenario's index and document, made once: a database of its own, its UG index read from a sitemap,
        exported as ``caracole index export`` exports one."""
        with self._lock:
            if self._index is not None:
                return
            from caracole import db
            from caracole.index_transfer import export

            folder = Path(self._folder.name)
            conn = db.connect(folder / "caracole.sqlite")
            try:
                build_index(conn, folder / "sitemaps", self.name)
                self._document = document(conn, self.name)
                export(conn, folder / "index.sqlite", now=NOW)
            finally:
                conn.close()
            self._index = (folder / "index.sqlite").read_bytes()

    def index(self) -> bytes:
        self._built()
        assert self._index is not None
        return self._index

    def document(self) -> dict:
        self._built()
        assert self._document is not None
        return self._document

    def fetch(self, url: str, user_agent: str) -> Answer:
        from caracole.http import robots_disallows

        closed = robots_disallows(url) is not None
        answer = Answer(404, HTML, b"<html><title>Not Found</title></html>", known=False) if closed \
            else self.sites.answer(url)
        provider = HOSTS.get(urllib.parse.urlsplit(url).hostname or "", "")
        with self._lock:
            entry = {"n": len(self._requests) + 1, "url": url, "provider": provider, "status": answer.status,
                     "known": answer.known and not closed, "closed": closed, "user_agent": user_agent}
            self._requests.append(entry)
        if closed or not answer.known:
            print(f"fake sites: {'closed' if closed else 'unknown'} {url} -> {answer.status}", file=sys.stderr,
                  flush=True)
        return answer


def _handler(fake: FakeSites) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "caracole-fake-sites"

        def log_message(self, format, *args):  # the log is /log's, and stderr's unknown lines
            pass

        def _send(self, status: int, content_type: str, body: bytes, location: str | None = None) -> None:
            self.send_response(status)
            if location is not None:
                self.send_header("Location", location)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parts = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
            if parts.path == "/fetch" and "url" in query:
                answer = fake.fetch(query["url"], self.headers.get("User-Agent", ""))
                self._send(answer.status, answer.content_type, answer.body, answer.location)
            elif parts.path == "/log":
                since = int(query.get("since") or 0)
                body = {"requests": [r for r in fake.requests if r["n"] > since]}
                self._send(200, JSON, json.dumps(body, ensure_ascii=False).encode("utf-8"))
            elif parts.path == "/scenario.json":
                self._send(200, JSON, json.dumps(fake.document(), ensure_ascii=False).encode("utf-8"))
            elif parts.path == "/index.sqlite":
                self._send(200, "application/vnd.sqlite3", fake.index())
            elif parts.path == "/":
                self._send(200, "text/plain; charset=utf-8", f"caracole's fake sites: {fake.name}\n".encode())
            else:
                self._send(404, "text/plain; charset=utf-8", b"no such route of the fake sites\n")

        def do_POST(self):
            self._send(405, "text/plain; charset=utf-8", b"the fake sites answer GET alone\n")

    return Handler


# --- caracole on the computer, against the fake sites --------------------------------------------------------------


def routed(base: str):
    """An httpx transport sending every request to the fake sites at ``base`` as RoutedTransport sends one: ``GET
    {base}/fetch?url=<its URL>``, its headers but the Host as they are; the answer as the server gave it."""
    import httpx

    class Routed(httpx.BaseTransport):
        def __init__(self):
            self.inner = httpx.HTTPTransport()

        def handle_request(self, request: httpx.Request) -> httpx.Response:
            sent = httpx.Request("GET", f"{base.rstrip('/')}/fetch", params={"url": str(request.url)},
                                 headers=[(k, v) for k, v in request.headers.raw if k.lower() != b"host"])
            return self.inner.handle_request(sent)

        def close(self) -> None:
            self.inner.close()

    return Routed()


def run_caracole(base: str, args: Sequence[str]) -> None:
    """``python -m caracole ARGS`` with every client's transport routed to the fake sites at ``base``."""
    from caracole.commands import _common

    _common.transport_for = lambda provider: routed(base)
    sys.argv = ["caracole", *args]
    from caracole.cli import main as caracole

    caracole()


def wait_until_up(url: str, timeout: float = 120) -> None:
    """Until the fake sites at ``url`` answer; TimeoutError else. Asked straight, never through a proxy."""
    import time
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with opener.open(url + "/", timeout=5) as answer:
                if answer.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.2)
    raise TimeoutError(f"the fake sites didn't answer at {url} in {timeout:.0f} s")


def log(url: str, since: int = 0) -> list[dict]:
    """``GET {url}/log``'s requests, asked straight."""
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"{url}/log?since={since}", timeout=30) as answer:
        return json.load(answer)["requests"]


def _stop_with_parent() -> None:
    """The server ends when the process that started it does (a script killed, a nix develop stopped): a thread
    watches its parent, and exits the process once it is another."""
    import os
    import time

    parent = os.getppid()

    def watch() -> None:
        while os.getppid() == parent:
            time.sleep(1)
        os._exit(0)

    threading.Thread(target=watch, name="fake-sites-parent", daemon=True).start()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m tests.helpers.fake_sites",
                                     description="The fake sites server, and caracole sent to it.")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="answer what a scenario's sites would, on PORT, until stopped")
    serve.add_argument("scenario", choices=sorted(SCENARIOS), metavar="SCENARIO")
    serve.add_argument("port", type=int, metavar="PORT")
    serve.add_argument("--address", default="127.0.0.1",
                       help="where it listens (127.0.0.1, which an emulator reaches as 10.0.2.2)")
    run = commands.add_parser("caracole", help="caracole's CLI, every site it asks the fake sites at SITES")
    run.add_argument("sites", metavar="SITES")
    run.add_argument("args", nargs=argparse.REMAINDER, metavar="ARGS")
    args = parser.parse_args(argv)

    if args.command == "caracole":
        run_caracole(args.sites, args.args[1:] if args.args[:1] == ["--"] else args.args)
        return
    fake = FakeSites(args.scenario, args.port, args.address)
    fake.document()  # built before it says it is up
    _stop_with_parent()
    print(f"the fake sites of {args.scenario} on {args.address}:{fake.port} (an emulator reaches them at "
          f"http://10.0.2.2:{fake.port}; Ctrl-C stops them)", flush=True)
    try:
        fake._server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        fake._server.server_close()
        fake._folder.cleanup()


def by_provider(requests: Sequence[dict]) -> dict[str, int]:
    """How many of ``requests`` (``/log``'s) went to each provider."""
    out: dict[str, int] = {}
    for r in requests:
        out[r["provider"]] = out.get(r["provider"], 0) + 1
    return out


if __name__ == "__main__":
    main()
