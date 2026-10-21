"""caracole serve's lookup and search: the lookup page, search as you type, and a song looked up now.

    GET  /lookup          look a song up as you type (lookup_page.py), and read its sheet
    GET  /api/search?q=   your library and the offline indexes, as JSON (search.py): your songs, the
                          artists the query names, the UG index's songs, which comes first and the
                          row Enter may act on; LaCuerda's artists and songs, gtptabs.com's and
                          MuseScore's pages, and the sites not searched, or not whole, with why
    GET  /api/artist?key= an artist of the offline index: their songs, most tabbed first, 50 from
                          ``offset``, and yours by them; ``?lacuerda=SLUG`` (``?lacuerda_name=NAME``),
                          a LaCuerda artist's songs the index holds, and whether caracole read their page
    POST /lookup          look a song up now: the UG song (``ug``) or tab (``tab``), or the LaCuerda
                          song (``lacuerda``), you picked
    POST /lacuerda/artist read a LaCuerda artist's page into its index, by ``slug`` or ``name``:
                          ``caracole lacuerda --artist`` queued, a request per slug tried, usually one

A lookup is one ``caracole get --progress``. Without JavaScript, the answer
sends the browser to the lookup page, which follows it; the lookup page's
script gets the job's address (202), which it follows on /api/jobs, and the
job as the library page reads it (``view``), so that a result's Get it there
shows how it goes in its row.

A lookup of a song your library has (named by its id, or the UG song you
picked is its match or its names' own: ``_Mine``) runs under that song's own
names and writes nothing to wanted.txt: no second song for UG's spelling of
it, and no new source for a song from Spotify. A lookup and a removal of the
same song never join (``jobs.REMOVING``): they run in the order they were
asked for, and a lookup after a removal asks for the song again, as a
wanted.txt line does.

Searching reads, and sends no request: one search runs at a time, one asked
for meanwhile wins over the older ones still waiting (``superseded``: the
page asks again if it still wants it), and the offline indexes' answers are
kept a few minutes. A query of fewer than three letters (two in Chinese)
looks nowhere. Of LaCuerda, gtptabs.com and MuseScore it reads only the tables
their listings and sitemaps filled (``search.search_lacuerda``,
``search.search_gtptabs``, ``search.search_musescore``), and says why it left a
site out (``skipped``): turned off, its index still empty, or MuseScore blocking
caracole; and why it searched one only in part (``partial``): LaCuerda's index
while the nightly run still reads its listings, with the letters read so far.
LaCuerda's index holds every artist it has read, but the songs only of the
artists whose page caracole has read: an artist's Songs offers to read it
(``POST /lacuerda/artist``), a job like the others; and while the nightly run
hasn't read the listing of a letter whole, a query it has no artist by under
that letter offers to read the page of that name (``lacuerda_unlisted``), never
a page LaCuerda's own songs or artists already name. Once such a read is over,
the answers kept are dropped, so a search finds their songs at once. LaCuerda's
group leads (``lacuerda_leads``) when it has the artist the query names and
Ultimate Guitar's index has nothing strong.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Sequence
from contextlib import closing
from typing import TYPE_CHECKING, Any

from caracole.web.app import (
    Request,
    Response,
    Route,
    WebApp,
    html_response,
    json_response,
    no_such_song,
    query,
    redirect,
    wants_json,
)
from caracole.web.jobs import LACUERDA_ARTIST, lacuerda_artist_steps, lookup_steps
from caracole.web.library_routes import LIMITS, PICK_LIMITS, lacuerda_field, wanted_line
from caracole.web.pages import Refused

if TYPE_CHECKING:
    from caracole.search import IndexFound, IndexHit, LibraryHit, SiteArtist, SiteHit
    from caracole.songs import Song

QUERY_LIMIT = 200  # characters of a search
LIBRARY_HITS, INDEX_HITS, TABS_SHOWN, SITE_HITS = 5, 8, 24, 5
ARTIST_PAGE = 50  # an artist's songs /api/artist gives at a time
LACUERDA_SONGS = 1000  # a LaCuerda artist's songs /api/artist gives: all of them, the index holds no more
CACHE_SIZE, CACHE_SECONDS = 128, 300.0  # the offline index's answers kept
_SLUG = re.compile(r"[a-z0-9_]{1,200}")  # the slug of a LaCuerda artist's page
SEARCH_CHECK_STEPS = 20_000  # SQLite steps between two looks for a newer search, a millisecond or so


def _artist(app: WebApp, request: Request) -> Response:
    asked = query(request)
    if "lacuerda" in asked or "lacuerda_name" in asked:
        return api_lacuerda_artist(app, asked.get("lacuerda", [""])[0].strip(),
                                   name=" ".join(asked.get("lacuerda_name", [""])[0].split()))
    return api_artist(app, asked.get("key", [""])[0].strip(), asked.get("offset", ["0"])[0].strip())


# The lookup page's script follows the job's address (wants_json).
ROUTES = (
    Route("GET", "/lookup", lambda app, asked: lookup_page(app)),
    Route("GET", "/api/search", lambda app, asked: api_search(app, query(asked).get("q", [""])[0])),
    Route("GET", "/api/artist", _artist),
    Route("POST", "/lookup", lambda app, asked, form: lookup(app, form, wants_json=wants_json(asked)),
          page="the page"),
    Route("POST", "/lacuerda/artist", lambda app, asked, form: lacuerda_read(app, form, wants_json=wants_json(asked)),
          page="the page"),
)


def lookup_page(app: WebApp) -> Response:
    from caracole.icons import page_icons
    from caracole.web import lookup_page as page

    return html_response(200, page.lookup_page(app.csrf, page_icons(app.cfg.cache_dir)), csp=page.LOOKUP_CSP)


# --- a song looked up now --------------------------------------------------------------------------


def lookup(app: WebApp, form: dict[str, str], *, wants_json: bool) -> Response:
    """The song you picked on the lookup page, looked up now: a song of your library as it is (``song``,
    its id; or the one your pick or its name is already), else a new one, in wanted.txt at once."""
    from caracole.overrides import OverridesError, tab_id_from_url

    pick = {name: form.get(name, "").strip() for name in PICK_LIMITS}
    for name, value in pick.items():
        if len(value) > PICK_LIMITS[name]:
            raise Refused(400, "Too long", f"The {name} is too long: {PICK_LIMITS[name]} characters at most.")
    artist_key, sep, song_key = pick["ug"].partition("/")
    if pick["ug"] and (not sep or not artist_key or not song_key or "/" in song_key):
        raise Refused(400, "Not a pick", f"{pick['ug']!r} isn't an Ultimate Guitar song (artist-key/song-key).")
    if pick["tab"]:
        try:
            tab_id_from_url(pick["tab"])
        except OverridesError as e:
            raise Refused(400, "Not a pick", f"That isn't an Ultimate Guitar tab: {e}") from e
    lacuerda = lacuerda_field(form)
    found = _library_song(app, form, (artist_key, song_key) if pick["ug"] else None)
    if found is not None:  # the song as your library has it: no second song, and no new source for it
        artist, title, album, duration_ms, key = found.artist, found.title, None, None, found.key
        note, display = f"In your library as {found.display}.", found.display
    else:
        line, note = wanted_line(app, form)
        artist, title, album, duration_ms, key = line.artist, line.title, line.album, line.duration_ms, line.identity
        display = f"{artist} - {title}"
    steps = lookup_steps(artist, title, album=album, duration_ms=duration_ms,
                         ug=pick["ug"] or None, tab=pick["tab"] or None, lacuerda=lacuerda)
    job, _ = app.submit(f"Fetch {artist} - {title}", key, steps, fetching=True, note=note, display=display,
                        full=f"{note} The queue is full, so it wasn't looked up now: the nightly run looks for "
                             "it, or ask again once the queue empties.")
    if wants_json:  # the lookup page follows its address; the library page, its line (view)
        return json_response(202, {"job": job.id, "url": f"/api/jobs/{job.id}", "view": app.job_view(job)})
    return redirect(f"/lookup?job={job.id}")


def _library_song(app: WebApp, form: dict[str, str], ug: tuple[str, str] | None) -> Song | None:
    """The library song a lookup is about: the one ``song`` names; else the one your UG pick is (matched
    to it, or by its names); else the one of the form's artist and title. None for a song new to the
    library; Refused when it can't be told."""
    from caracole.normalize import identity_key
    from caracole.songs import find_song, get_song, list_songs

    with app.db() as conn:
        if form.get("song", "").strip():
            with no_such_song():
                try:
                    return get_song(conn, int(form["song"]))
                except ValueError:
                    raise Refused(400, "Not a song", "Which song? The form names none.") from None
        artist, title = form.get("artist", "").strip(), form.get("title", "").strip()
        if ug is not None:
            found = _Mine(list_songs(conn), app._song_forms).song_for(*ug, artist, title)
            if found is not None:
                return found
        if artist and title:
            return find_song(conn, identity_key(artist, title))
        return None


# --- search as you type ------------------------------------------------------------------------


def api_search(app: WebApp, query: str) -> Response:
    """Your library and the offline UG index, for a query typed into the lookup page."""
    from caracole.normalize import has_han

    q = " ".join(query.split())[:QUERY_LIMIT]
    letters = sum(c.isalnum() for c in q)
    if letters < (2 if has_han(q) else 3):
        return json_response(200, {"query": q, "library": [], "index": [], "short": True})
    ticket = next(app._tickets)
    app._newest = ticket
    superseded = {"query": q, "superseded": True}

    def typed_over() -> int:  # SQLite asks every few thousand steps: non-zero interrupts the query
        return int(ticket != app._newest)

    with app._searching:
        if typed_over():  # typed on meanwhile: the newer query goes first
            return json_response(200, superseded)
        try:
            with closing(app.connect()) as conn:
                conn.set_progress_handler(typed_over, SEARCH_CHECK_STEPS)
                return json_response(200, _found_for(app, conn, q))
        except sqlite3.OperationalError as e:
            if typed_over():  # interrupted: the newer one reads now
                return json_response(200, superseded)
            return json_response(503, {"query": q, "error": f"The database can't be read: {e}"})
        except (sqlite3.Error, OSError) as e:
            return json_response(503, {"query": q, "error": f"The database can't be read: {e}"})


def _found_for(app: WebApp, conn: sqlite3.Connection, q: str) -> dict[str, Any]:
    """The search's answer (``search.found``'s): your songs, the artists the query names, the index's
    songs, which leads, and the row Enter may act on (``best``: a song of yours by its id, or an
    Ultimate Guitar song by its keys; None for none). A song of your library comes as its card
    has it (``_rows``)."""
    from caracole.search import (
        LibraryHit,
        found,
        lacuerda_leads,
        search_gtptabs,
        search_lacuerda,
        search_library,
        search_musescore,
    )
    from caracole.songs import list_songs

    mine = search_library(conn, q, LIBRARY_HITS)
    skipped, partial = _skipped(app, conn)
    left_out = {s["source"] for s in skipped}
    _after_reads(app)
    cached = app._found.get(q)
    if cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
        index_found, index, artists, hint, gtptabs, musescore, lc_artists, lacuerda = cached[1:]
    else:
        index_found, index, artists, hint = _index_hits(conn, q)
        gtptabs = search_gtptabs(conn, q, SITE_HITS) if "gtptabs" not in left_out else []
        musescore = search_musescore(conn, q, SITE_HITS) if "musescore" not in left_out else []
        lc_artists, lacuerda = (search_lacuerda(conn, q, songs=SITE_HITS) if "lacuerda" not in left_out
                                else ([], []))
        app._found[q] = (time.monotonic(), index_found, index, artists, hint, gtptabs, musescore, lc_artists,
                         lacuerda)
        while len(app._found) > CACHE_SIZE:
            app._found.popitem(last=False)
    answer = found(mine, index_found)
    songs = list_songs(conn)
    library, hits = _rows(app, conn, mine, index, songs)
    best = answer.best
    pick = None if best is None else (
        {"library": best.song.id} if isinstance(best, LibraryHit) else {"ug": f"{best.artist_key}/{best.song_key}"})
    return {"query": q, "library": library, "index": hits, "artists": artists, "lead": answer.lead,
            "best": pick, "hint": hint,
            "gtptabs": _gtptabs_rows(app, conn, gtptabs if "gtptabs" not in left_out else [], songs),
            "musescore": [{"source": h.source, "title": h.title, "url": h.url, "score": h.score}
                          for h in (musescore if "musescore" not in left_out else [])],
            "lacuerda": _lacuerda_rows(app, conn, lacuerda, songs),
            "lacuerda_artists": [_lacuerda_artist_json(a) for a in lc_artists],
            "lacuerda_unlisted": _lacuerda_unlisted(conn, q, index_found, lc_artists, lacuerda),
            "lacuerda_leads": lacuerda_leads(index_found, lc_artists),
            "skipped": skipped, "partial": partial}


def _after_reads(app: WebApp) -> None:
    """Drop the offline indexes' answers kept, once a LaCuerda artist page asked for is read: the index holds
    their songs now, which an answer from before it lacks. Under ``app._searching``."""
    over = {i for i in app._reads if (job := app.queue.job(i)) is None or not job.active}
    if over:
        app._reads -= over
        app._found.clear()


def _gtptabs_rows(app: WebApp, conn: sqlite3.Connection, hits: Sequence[SiteHit],
                  songs: list[Song]) -> list[dict[str, Any]]:
    """gtptabs.com's pages as the page draws them; one your library has (``_Mine``, by its names) names it,
    so that Get it looks it up as that song."""
    return [{"source": h.source, "artist": h.artist, "title": h.title, "url": h.url, "uploads": h.uploads,
             "score": h.score, "via": h.via, **_keys(h.artist, h.title), **mine}
            for h, mine in zip(hits, _owners(app, conn, hits, songs))]


def _lacuerda_rows(app: WebApp, conn: sqlite3.Connection, hits: Sequence[SiteHit],
                   songs: list[Song]) -> list[dict[str, Any]]:
    """LaCuerda's songs as the page draws them: its page, the page of the sheet Get it keeps (``sheet``, None
    for a song without chords there) and its versions; one your library has names it, as gtptabs.com's do."""
    return [{"source": h.source, "artist": h.artist, "title": h.title, "url": h.url, "sheet": h.sheet,
             "versions": h.uploads, "score": h.score, "via": h.via, **_keys(h.artist, h.title), **mine}
            for h, mine in zip(hits, _owners(app, conn, hits, songs))]


def _keys(artist: str, title: str) -> dict[str, str]:
    """The keys a row merges on across sites (``normalize.identity_key``, split): the same song from
    Ultimate Guitar, LaCuerda and gtptabs.com shares both."""
    from caracole.normalize import identity_key

    artist_key, title_key = identity_key(artist, title).split("/", 1)
    return {"artist_key": artist_key, "title_key": title_key}


def _owners(app: WebApp, conn: sqlite3.Connection, hits: Sequence[SiteHit], songs: list[Song]) -> list[dict[str, Any]]:
    """Each site hit's song of your library (``_Mine``, by its names), as ``song`` and ``library`` (its names
    and its card's links); None for one your library hasn't."""
    from caracole.library_page import result_cards

    owners_of = _Mine(songs, app._song_forms)
    owners = [owners_of.song_for(h.artist_key, h.title_key, h.artist, h.title) for h in hits]
    cards = result_cards(conn, app.cfg, list({s.id: s for s in owners if s}.values()))
    return [{"song": song.id if song else None,
             "library": {"id": song.id, "artist": song.artist, "title": song.title, "display": song.display,
                         "links": cards[song.id]["links"]} if song else None} for song in owners]


def _skipped(app: WebApp, conn: sqlite3.Connection) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """The sites a search leaves out, and why: one turned off, one whose index the nightly run hasn't
    filled yet (MuseScore's, while it blocks caracole); and those it searches only in part: LaCuerda's,
    while the nightly run reads its listings (``search.lacuerda_left_out``)."""
    from caracole.health import get_state
    from caracole.search import lacuerda_left_out

    left = []
    for source, name, table in (("gtptabs", "gtptabs.com", "gtptabs_index"),
                                ("musescore", "MuseScore", "musescore_index")):
        if not app.cfg.provider(source).enabled:
            why = "turned off in caracole.toml"
        elif conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() is not None:
            continue
        elif source == "musescore" and get_state(conn, source).strikes:
            why = "MuseScore is blocking caracole, so its index is empty"
        else:
            why = "its index is empty: the nightly run reads its sitemaps"
        left.append({"source": source, "name": name, "why": why})
    partial: list[dict[str, str]] = []
    lacuerda = lacuerda_left_out(conn)
    if lacuerda is not None:
        said = {"source": "lacuerda", "name": "LaCuerda", "why": f"its {lacuerda[1]}"}
        (left if lacuerda[0] == "empty" else partial).append(said)
    return left, partial


def _rows(app: WebApp, conn: sqlite3.Connection, mine: Sequence[LibraryHit], index: list[dict[str, Any]],
          songs: list[Song] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Your songs and the index's, as the page draws them. A song of your library comes as its card
    has it (``result_cards``): its files (``links``, its viewer the primary one), where its sheet
    came from, its key; and the files its sheet can be read in on the page (``files``). An index
    song your library has (``_Mine``) names it, with its links."""
    from caracole.get import readable_files
    from caracole.library_page import result_cards
    from caracole.songs import list_songs

    owners_of = _Mine(songs if songs is not None else list_songs(conn), app._song_forms)
    owners = [owners_of.song_for(*hit["ug"].split("/", 1), hit["artist"], hit["title"]) for hit in index]
    cards = result_cards(conn, app.cfg, list({s.id: s for s in [h.song for h in mine] + owners if s}.values()))
    library = [{"id": h.song.id, "display": h.song.display, "artist": h.song.artist, "title": h.song.title,
                "status": h.song.status, "review": bool(h.song.review), "score": h.score, "via": h.via,
                "files": readable_files(conn, app.cfg.library_dir, h.song), **cards[h.song.id]}
               for h in mine]
    hits = [{**hit, **_keys(hit["artist"], hit["title"]), "song": song.id if song else None,
             "library": {"id": song.id, "artist": song.artist, "title": song.title, "display": song.display,
                         "links": cards[song.id]["links"]} if song else None}
            for hit, song in zip(index, owners)]
    return library, hits


def _index_hits(conn: sqlite3.Connection, q: str) -> tuple[IndexFound, list[dict[str, Any]],
                                                           list[dict[str, Any]], str | None]:
    from caracole.search import IndexFound, bare_id_hint, find_index
    from caracole.ug.index import index_count

    if index_count(conn) == 0:
        return (IndexFound(), [], [],
                "The offline Ultimate Guitar index is empty: run caracole index build once (about 10 minutes).")
    answer = find_index(conn, q, songs=INDEX_HITS)
    artists = [{"artist_key": a.artist_key, "artist": a.artist, "score": a.score, "songs": a.songs, "tabs": a.tabs,
                "top": [{"artist": h.artist, "title": h.title, "ug": f"{h.artist_key}/{h.song_key}",
                         "counts": dict(h.counts)} for h in a.top]}
               for a in answer.artists]
    index = [_hit_json(conn, h) for h in answer.songs]
    return answer, index, artists, bare_id_hint(q, [*answer.songs, *answer.artists])


def _hit_json(conn: sqlite3.Connection, h: IndexHit) -> dict[str, Any]:
    """An Ultimate Guitar song of the index as the page draws it: its names, its tabs per type and
    its first ``TABS_SHOWN`` tabs, chords first; ``no_ones`` when its artist is one of UG's ``misc-…``
    keys, no one's name (``search.no_ones``)."""
    from caracole.search import TYPE_ORDER, no_ones
    from caracole.ug.lookup import song_tabs

    def rank(t) -> tuple:
        return (TYPE_ORDER.index(t.type) if t.type in TYPE_ORDER else len(TYPE_ORDER), t.label is not None,
                t.tab_id)

    return {"artist": h.artist, "title": h.title, "ug": f"{h.artist_key}/{h.song_key}", "counts": dict(h.counts),
            "score": h.score, "url": h.url, "labels": list(h.labels), "via": h.via, "no_ones": no_ones(h.artist_key),
            "tabs": [{"id": t.tab_id, "type": t.type, "label": t.label, "url": t.url}
                     for t in sorted(song_tabs(conn, h.artist_key, h.song_key), key=rank)[:TABS_SHOWN]]}


# --- an artist's songs ---------------------------------------------------------------------------


def api_artist(app: WebApp, key: str, offset: str) -> Response:
    """An artist of the offline index, for the lookup page: their songs, ``ARTIST_PAGE`` from
    ``offset``, most tabbed first, and yours by them (``search.library_by_artist``). It only reads,
    one at a time with the searches."""
    if not key:
        return json_response(400, {"error": "Which artist? The address names none."})
    if not (offset.isascii() and offset.isdigit()):
        return json_response(400, {"error": "That offset isn't a number."})
    with app._searching:
        try:
            with closing(app.connect()) as conn:
                return _artist_songs(app, conn, key, int(offset))
        except (sqlite3.Error, OSError) as e:
            return json_response(503, {"error": f"The database can't be read: {e}"})


def api_lacuerda_artist(app: WebApp, slug: str, *, name: str = "") -> Response:
    """A LaCuerda artist, for the pages: the songs LaCuerda's index holds of theirs, most popular first, and
    yours by them; ``read`` says whether it holds any, which it does once caracole has read their page. By the
    slug of their page, or by their ``name``, as a page read by name (``POST /lacuerda/artist``) left them."""
    from caracole.search import LibraryHit, lacuerda_artist, lacuerda_artist_named, lacuerda_songs, library_by_artist
    from caracole.songs import list_songs

    if not slug and not name:
        return json_response(400, {"error": "Which artist? The address names none."})
    with app._searching:
        try:
            with closing(app.connect()) as conn:
                named = lacuerda_artist(conn, slug) if slug else lacuerda_artist_named(conn, name)
                if named is None:
                    return json_response(404, {"error": "LaCuerda's index has no such artist."})
                songs = list_songs(conn)
                theirs = [LibraryHit(s, 100.0, "artist") for s in library_by_artist(songs, named.artist)]
                library, _ = _rows(app, conn, theirs, [], songs)
                hits = _lacuerda_rows(app, conn, lacuerda_songs(conn, named.slug)[:LACUERDA_SONGS], songs)
        except (sqlite3.Error, OSError) as e:
            return json_response(503, {"error": f"The database can't be read: {e}"})
    return json_response(200, {"source": "lacuerda", "slug": named.slug, "artist": named.artist, "url": named.url,
                               "listed": named.songs, "total": named.known, "read": named.known > 0, "songs": hits,
                               "library": library})


def lacuerda_read(app: WebApp, form: dict[str, str], *, wants_json: bool) -> Response:
    """A LaCuerda artist's page read into the index: ``caracole lacuerda --artist`` queued, a job of its own
    (at the lookup pace: one request for an artist the index lists, one per spelling of a ``name`` tried,
    usually one); asked again while it waits or runs, that job. By the ``slug`` of a page the index lists,
    or by a ``name``, for an artist under a letter of LaCuerda's listings not read yet."""
    from caracole.lacuerda import artist_slug_candidates
    from caracole.lacuerda_index import name_key
    from caracole.search import lacuerda_artist

    slug, name = form.get("slug", "").strip(), " ".join(form.get("name", "").split())
    if name and not slug:
        if len(name) > LIMITS["artist"] or not artist_slug_candidates(name):
            raise Refused(400, "Not an artist", "That name makes no LaCuerda artist page's address.")
        display, key, who = name, LACUERDA_ARTIST + "name:" + name_key(name), name
    else:
        if not _SLUG.fullmatch(slug):
            raise Refused(400, "Not an artist", "Which artist? The form names no LaCuerda artist page.")
        with app.db() as conn:
            named = lacuerda_artist(conn, slug)
        if named is None:
            raise Refused(404, "No such artist", "LaCuerda's index has no such artist.")
        display, key, who = named.artist, LACUERDA_ARTIST + slug, slug
    job, _ = app.submit(f"Read the page of {display} on LaCuerda", key, lacuerda_artist_steps(who, display),
                        display=f"{display} on LaCuerda")
    with app._searching:
        app._reads.add(job.id)
    if wants_json:
        return json_response(202, {"job": job.id, "url": f"/api/jobs/{job.id}"})
    return redirect(f"/jobs#job-{job.id}")


def _artist_songs(app: WebApp, conn: sqlite3.Connection, key: str, offset: int) -> Response:
    from caracole.search import LibraryHit, artist_songs, index_artist, library_by_artist
    from caracole.songs import list_songs

    named = index_artist(conn, key)
    if named is None:
        return json_response(404, {"error": "The offline Ultimate Guitar index has no such artist."})
    hits, total = artist_songs(conn, key, limit=ARTIST_PAGE, offset=offset)
    songs = list_songs(conn)
    theirs = [LibraryHit(s, 100.0, "artist") for s in library_by_artist(songs, named.artist, key)]
    library, index = _rows(app, conn, theirs, [_hit_json(conn, h) for h in hits], songs)
    return json_response(200, {"artist_key": key, "artist": named.artist, "songs": index, "total": total,
                               "offset": offset, "tabs": named.tabs, "library": library})


def _lacuerda_artist_json(a: SiteArtist) -> dict[str, Any]:
    """A LaCuerda artist as the page draws them: their songs as the listing counts them, those the index holds
    (``known``: 0 until caracole has read their page), and the most popular with chords."""
    return {"source": a.source, "artist": a.artist, "slug": a.slug, "url": a.url, "songs": a.songs, "known": a.known,
            "score": a.score, "via": a.via, "top": [{"title": t.title, "url": t.url, "sheet": t.sheet} for t in a.top]}


def _lacuerda_unlisted(conn: sqlite3.Connection, q: str, ug: IndexFound, lc_artists: Sequence[SiteArtist],
                       lc_songs: Sequence[SiteHit]) -> dict[str, str] | None:
    """A query LaCuerda's index has no artist by (none it found is a strong match, as "Bomba Estereo" isn't for
    "soda stereo", nor a song: "como camaron" is Estopa's title), under a letter of its listings not read yet
    (``search.lacuerda_unlisted``, with the Ultimate Guitar index's answer ``ug`` and LaCuerda's): the name whose
    page Read LaCuerda's page reads, and the letter."""
    from caracole.search import lacuerda_unlisted

    found = lacuerda_unlisted(conn, q, ug.artists, ug.songs, ug.lead, lacuerda=[*lc_artists, *lc_songs])
    return {"name": found[0], "letter": found[1]} if found is not None else None


FORMS_KEPT = 10_000  # songs whose name forms _Mine keeps between two searches


class _Mine:
    """Your library's songs, to tell which one an Ultimate Guitar song of the offline index is.

    As ``caracole search --add`` tells it (commands/search.py): the song matched
    to it (an accepted or pinned match, a variant counted as its song), else the
    song its names are, by identity key or by ``normalize.name_forms`` (UG's
    "Acdc", "R E M" and "Song Dongye" are your AC/DC, R.E.M. and 宋冬野). A
    review's keys are only a candidate's, often a cover by another artist, so
    they make no song of yours. ``forms`` keeps each song's forms, by its names.
    """

    def __init__(self, songs: list[Song], forms: dict[tuple, tuple[frozenset[str], frozenset[str]]]):
        from caracole.normalize import split_variant

        self.songs = sorted(songs, key=lambda s: s.id)
        self.by_key = {s.key: s for s in self.songs}
        self.matched: dict[tuple[str, str], Song] = {}
        for s in self.songs:
            if s.match_decision in ("accept", "pinned") and s.match_artist_key and s.match_song_key:
                self.matched.setdefault((s.match_artist_key, split_variant(s.match_song_key)[0]), s)
        self.forms = forms

    def song_for(self, artist_key: str, song_key: str, artist: str, title: str) -> Song | None:
        from caracole.normalize import compact, identity_key, split_variant

        base = split_variant(song_key)[0]
        found = self.matched.get((artist_key, base)) or self.by_key.get(identity_key(artist, title))
        if found is not None:
            return found
        wanted_artist, wanted_title = compact(artist_key), compact(base)
        for song in self.songs:
            artists, titles = self._forms_of(song)
            if wanted_artist in artists and wanted_title in titles:
                return song
        return None

    def _forms_of(self, song: Song) -> tuple[frozenset[str], frozenset[str]]:
        from caracole.normalize import clean_title, compact, name_forms

        names = (song.artist, tuple(song.artists), song.title)
        forms = self.forms.get(names)
        if forms is None:
            if len(self.forms) >= FORMS_KEPT:
                self.forms.clear()
            artists = frozenset(compact(f) for a in dict.fromkeys(song.artists or [song.artist]) for f in name_forms(a))
            forms = (artists, frozenset(compact(f) for f in name_forms(clean_title(song.title))))
            self.forms[names] = forms
        return forms
