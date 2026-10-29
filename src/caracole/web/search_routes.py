"""caracole serve's lookup and search: the lookup page, search as you type, and a song looked up now.

    GET  /lookup          look a song up as you type (lookup_page.py), and read its sheet
    GET  /api/search?q=   your library and the offline indexes, as JSON (search.py), for a search box (``box``,
                          the id its page made): your songs (and
                          those that play the progression the query types or names: ``progression``,
                          progressions.py), the songs you removed (``removed``), the artists the query names, the UG
                          index's songs, which comes first and the row Enter may act on; LaCuerda's
                          artists and songs, gtptabs.com's and MuseScore's pages, and the sites not
                          searched, or not whole, with why (``skipped``, ``partial``), and where it
                          looked, a mark a site (``looked``); for a query the index may not see the
                          artist of, what to paste (``unseen``). Each song's row has the two parts of its
                          identity key (``artist_key``, ``title_key``), and an artist's the first
                          (``group_key``): the library page puts what shares them on one line, and
                          under one header, which counts an artist's songs on each site (an artist's
                          ``songs`` on theirs, ``gtptabs`` gtptabs.com's); an artist the query names only
                          by a word of their name says so (``part``); and, for a query nothing matches
                          well, the artists and the songs spelled close to it (``suggest``: each one's site,
                          name, songs, group, and their ``artist_key``, LaCuerda ``slug`` or harptabs.com
                          ``path``, for /api/artist; a song's ``title``, its row on each site, ``song``, and
                          your song's row, ``library``, for a song of yours); and whether LaCuerda's own
                          search may be sent for the query (``lacuerda_search``)
    GET  /api/artist?key= an artist of the offline index: their songs, most tabbed first, 50 from
                          ``offset``, and yours by them; ``?lacuerda=SLUG`` (``?lacuerda_name=NAME``),
                          a LaCuerda artist's songs the index holds, and whether caracole read their page
                          (and ``gtptabs``, as the search gives it); ``?harptabs=PATH``, a
                          harptabs.com artist's songs the index holds (their page's path), and whether
                          caracole read their page
    POST /lookup          look a song up now: the UG song (``ug``) or tab (``tab``), the LaCuerda
                          song (``lacuerda``), the harptabs.com tab (``harptabs``) or the gametabs.net
                          tab (``gametabs``), you picked
    POST /lacuerda/artist read a LaCuerda artist's page into its index, by ``slug`` or ``name``:
                          ``caracole lacuerda --artist`` queued, a request per slug tried, usually one
    POST /lacuerda/search ask LaCuerda's search for the songs of a query (``q``) and put them into its index:
                          ``caracole lacuerda --search --progress`` queued, one request; ``by_hand``, the
                          button's (and Enter's), past the share of the searches the page sends by itself
    POST /harptabs/artist read a harptabs.com artist's page into its index, by its ``path``: ``caracole
                          harptabs --artist`` queued, one request

A lookup is one ``caracole get --progress``. Without JavaScript, the answer
sends the browser to the lookup page, which follows it; the lookup page's
script gets the job's address (202), which it follows on /api/jobs, and the
job as the library page reads it (``view``), so that a result's Get it there
shows how it goes in its row.

A lookup of a song your library has (named by its id, or the UG song you
picked is its match or its names' own: ``_Mine``) runs under that song's own
names and writes nothing to wanted.txt: no second song for UG's spelling of
it, and no line back for a song you took off wanted.txt (deleting a line never
deletes the song). A lookup and a removal of the
same song never join (``jobs.REMOVING``): they run in the order they were
asked for, and a lookup after a removal asks for the song again, as a
wanted.txt line does.

A removed song (``search.search_removed``) is never ``best``: the library page
shows it with Add again, which asks for it again as a request does, with a line
in wanted.txt.

Searching reads, and sends no request (LaCuerda's search, below, is a job of
its own): one search runs at a time, and one asked for meanwhile in the same
search box (``box``: an id each box's page makes, ``search_box``; a search
naming none is of one box with every other such) wins over that box's older
ones, running or waiting (``superseded``: the page asks again if it still
wants it). A search of another box, another page or another person's phone,
never stops one: it waits its turn, and both are answered. The offline
indexes' answers are kept a few minutes. A query of fewer than three letters (two in Chinese)
looks nowhere. Of LaCuerda, gtptabs.com, MuseScore and harptabs.com it reads only the tables
their listings, sitemaps and artist pages filled (``search.search_lacuerda``,
``search.search_gtptabs``, ``search.search_musescore``, ``search.search_harptabs``: harptabs.com's
artists, ``harptabs_artists``, as LaCuerda's are, and its songs, ``harptabs``, a song's harmonica tabs by
an artist whose page caracole read, each with its ``tabs``, else a tab by its title alone, as
MuseScore's pages; none while harptabs.com is turned off), and says why it left a site out
(``skipped``): turned off, its index still empty, or MuseScore blocking caracole; and why it
searched one only in part (``partial``): LaCuerda's index while the nightly run still reads its
listings, with the letters read so far, and harptabs.com's while its artist pages aren't all read
(harptabs_index.py, "2 of 10,428 artists"). Of gametabs.net it reads its sitemaps' and game pages' tables
(``search.search_gametabs``: ``gametabs``, a track of a game a song, the game its artist, its tabs the most viewed
first, each with the instruments and composers its game's page said; none while gametabs.net is turned off, and no
mark among ``looked``'s yet). A song's Get it on a gametabs.net row looks the song up and keeps that tab
(``gametabs``: ``caracole get --gametabs``, recorded under ``[gametabs]``).
``looked`` says the same of every site, Ultimate Guitar's index too, as the
pages' marks show it (``_looked``: a state, a short label, a line of detail), and
``unseen`` (``search.bare_id_unseen``) what ``hint`` says of an artist UG's
sitemaps may list only by a bare id, as facts the pages word themselves.
LaCuerda's index holds every artist it has read, but the songs only of the
artists whose page caracole has read: an artist's Songs offers to read it
(``POST /lacuerda/artist``), a job like the others; and while the nightly run
hasn't read the listing of a letter whole, a query it has no artist by under
that letter offers to read the page of that name (``lacuerda_unlisted``), never
a page LaCuerda's own songs or artists already name. Once such a read is over,
the answers kept are dropped, so a search finds their songs at once. LaCuerda's
group leads (``lacuerda_leads``) when it has the artist the query names and
Ultimate Guitar's index has nothing strong; an Ultimate Guitar artist a word of
the query names then leads nothing (``lead`` is "song"), so Enter opens
LaCuerda's.

harptabs.com's artists come from its sitemap, named by their slug until caracole reads
their page: an artist's Songs lists the tabs it holds of theirs, or offers to read
their page (``POST /harptabs/artist``), a job like LaCuerda's, whose end drops the
answers kept too. A song's Get it on a harptabs.com row looks the song up and keeps
that tab (``harptabs``: ``caracole get --harptabs``, recorded under ``[harptabs]``).

LaCuerda's own search answers what its index can't: the songs of an artist
whose page caracole hasn't read. ``lacuerda_search`` says, with no request and
no lock, what sending it would be (lacuerda_search.py's ``gate``): None for a
query LaCuerda reads no word of, or that LaCuerda's index answers well (a
strong song, or the artist the query names, whose page caracole has read);
else its ``state``, ``auto`` (the library page and the lookup page send it by
themselves once the query has settled), ``button`` (the share of the hour's
lookups such searches have is spent: the page offers Ask LaCuerda, which
asks by hand), ``failed`` (its search failed within the hour, or three did:
the page says ``why`` and offers the button), ``asked`` (within 30 days) or
``spent`` (a cooldown, or the hour's lookups to LaCuerda), with the ``query``
and its ``key``. A strong song of your library makes it None too: you are
looking through your songs. ``POST
/lacuerda/search`` queues it (``LACUERDA_SEARCH`` and the key, so asking again
joins it), refusing what that gate refuses, and its end drops the answers
kept, as a read's does.
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
from caracole.web.jobs import (
    HARPTABS_ARTIST,
    LACUERDA_ARTIST,
    LACUERDA_SEARCH,
    Job,
    harptabs_artist_steps,
    lacuerda_artist_steps,
    lacuerda_search_steps,
    lookup_steps,
)
from caracole.web.library_routes import (
    LIMITS,
    PICK_LIMITS,
    gametabs_field,
    harptabs_field,
    lacuerda_field,
    wanted_line,
)
from caracole.web.pages import Refused
from caracole.web.status import details_href

if TYPE_CHECKING:
    from caracole.search import IndexFound, IndexHit, LibraryHit, SiteArtist, SiteHit, Suggestion
    from caracole.songs import Song

QUERY_LIMIT = 200  # characters of a search
LIBRARY_HITS, INDEX_HITS, TABS_SHOWN, SITE_HITS = 5, 8, 24, 5
ARTIST_PAGE = 50  # an artist's songs /api/artist gives at a time
LACUERDA_SONGS = 1000  # a LaCuerda artist's songs /api/artist gives: all of them, the index holds no more
CACHE_SIZE, CACHE_SECONDS = 128, 300.0  # the offline index's answers kept
_SLUG = re.compile(r"[a-z0-9_]{1,200}")  # the slug of a LaCuerda artist's page
_HARP_ARTIST = re.compile(r"artist/\d{1,9}/[a-z0-9-]{1,200}")  # the path of a harptabs.com artist's page
UG_EMPTY = "The offline Ultimate Guitar index is empty: run caracole index build once (about 10 minutes)."
SEARCH_CHECK_STEPS = 20_000  # SQLite steps between two looks for a newer search, a millisecond or so
_BOX = re.compile(r"[A-Za-z0-9_-]{1,64}")  # a search box's id, as its page makes it
BOXES = 256  # the search boxes whose newest search the server keeps: those that asked last


def _artist(app: WebApp, request: Request) -> Response:
    asked = query(request)
    if "harptabs" in asked:
        return api_harptabs_artist(app, asked.get("harptabs", [""])[0].strip())
    if "lacuerda" in asked or "lacuerda_name" in asked:
        return api_lacuerda_artist(app, asked.get("lacuerda", [""])[0].strip(),
                                   name=" ".join(asked.get("lacuerda_name", [""])[0].split()))
    return api_artist(app, asked.get("key", [""])[0].strip(), asked.get("offset", ["0"])[0].strip())


# The lookup page's script follows the job's address (wants_json).
ROUTES = (
    Route("GET", "/lookup", lambda app, asked: lookup_page(app)),
    Route("GET", "/api/search", lambda app, asked: api_search(app, query(asked).get("q", [""])[0],
                                                              box=search_box(query(asked)))),
    Route("GET", "/api/artist", _artist),
    Route("POST", "/lookup", lambda app, asked, form: lookup(app, form, wants_json=wants_json(asked)),
          page="the page"),
    Route("POST", "/lacuerda/artist", lambda app, asked, form: lacuerda_read(app, form, wants_json=wants_json(asked)),
          page="the page"),
    Route("POST", "/lacuerda/search", lambda app, asked, form: lacuerda_search(app, form, wants_json=wants_json(asked)),
          page="the page"),
    Route("POST", "/harptabs/artist", lambda app, asked, form: harptabs_read(app, form, wants_json=wants_json(asked)),
          page="the page"),
)


def lookup_page(app: WebApp) -> Response:
    from caracole.icons import page_icons
    from caracole.web import lookup_page as page

    return html_response(200, page.lookup_page(app.csrf, page_icons(app.cfg.cache_dir)), csp=page.LOOKUP_CSP)


# --- a song looked up now --------------------------------------------------------------------------


def lookup(app: WebApp, form: dict[str, str], *, wants_json: bool) -> Response:
    """The song you picked on the lookup page, looked up now (``queue_lookup``)."""
    job, _ = queue_lookup(app, form)
    if wants_json:  # the lookup page follows its address; the library page, its line (view)
        return json_response(202, {"job": job.id, "url": f"/api/jobs/{job.id}", "view": app.job_view(job)})
    return redirect(f"/lookup?job={job.id}")


def queue_lookup(app: WebApp, form: dict[str, str]) -> tuple[Job, str]:
    """A song looked up now: a song of your library as it is (``song``, its id; or the one your pick or its name
    is already), else a new one, in wanted.txt at once; its job, and the song as the library names it, or will
    ("Artist - Title")."""
    request, display, full = lookup_request(app, form)
    job, _ = app.submit(**request, full=full)
    return job, display


def lookup_request(app: WebApp, form: dict[str, str]) -> tuple[dict[str, Any], str, str]:
    """``queue_lookup`` short of queueing: the arguments of its ``JobQueue.submit`` (wanted.txt written already, for
    a song new to the library), the song's name, and what to say when the queue is full. The library page's Add a
    song (songbook_routes.py) queues it with the songbook's change, both or neither."""
    pick, ug = _pick(form)
    lacuerda = lacuerda_field(form)
    harptabs = harptabs_field(form)
    gametabs = gametabs_field(form)
    found = _library_song(app, form, ug)
    if found is not None:  # the song as your library has it: no second song, and no new source for it
        artist, title, album, duration_ms, key = found.artist, found.title, None, None, found.key
        note, display = f"In your library as {found.display}.", found.display
    else:
        line, note = wanted_line(app, form)
        artist, title, album, duration_ms, key = line.artist, line.title, line.album, line.duration_ms, line.identity
        display = f"{artist} - {title}"
    steps = lookup_steps(artist, title, album=album, duration_ms=duration_ms,
                         ug=pick["ug"] or None, tab=pick["tab"] or None, lacuerda=lacuerda, harptabs=harptabs,
                         gametabs=gametabs)
    request = {"title": f"Fetch {artist} - {title}", "song_key": key, "steps": steps, "fetching": True,
               "note": note, "display": display}
    full = (f"{note} The queue is full, so it wasn't looked up now: the nightly run looks for "
            "it, or ask again once the queue empties.")
    return request, display, full


def library_song(app: WebApp, form: dict[str, str]) -> Song | None:
    """The song of your library a form names as a lookup's does (by its id, its Ultimate Guitar pick or its
    names); None for a song new to the library; Refused for a pick that isn't one, or an id no song has."""
    _, ug = _pick(form)
    return _library_song(app, form, ug)


def _pick(form: dict[str, str]) -> tuple[dict[str, str], tuple[str, str] | None]:
    """The Ultimate Guitar song and tab, and the LaCuerda song, a form picks (each "" for none), and the UG
    song's keys; Refused for one that is too long, or isn't one."""
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
    return pick, (artist_key, song_key) if pick["ug"] else None


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


def search_box(asked: dict[str, list[str]]) -> str:
    """The search box a search comes from (``box``: the id its page made); "" for one that names none, or an id
    that isn't one."""
    box = asked.get("box", [""])[0]
    return box if _BOX.fullmatch(box) else ""


def api_search(app: WebApp, query: str, *, box: str = "") -> Response:
    """Your library and the offline UG index, for a query typed into a search box (``box``, its id): a search
    typed on in that box stops this one, never one of another box's."""
    from caracole.normalize import has_han

    q = " ".join(query.split())[:QUERY_LIMIT]
    letters = sum(c.isalnum() for c in q)
    if letters < (2 if has_han(q) else 3):
        return json_response(200, {"query": q, "library": [], "index": [], "short": True})
    with app._newest_lock:
        ticket = next(app._tickets)
        app._newest[box] = ticket
        app._newest.move_to_end(box)
        while len(app._newest) > BOXES:
            app._newest.popitem(last=False)
    superseded = {"query": q, "superseded": True}

    def typed_over() -> int:  # SQLite asks every few thousand steps: non-zero interrupts the query
        return int(app._newest.get(box, ticket) != ticket)  # a box forgotten (BOXES asked since): this is its newest

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
        STRONG,
        LibraryHit,
        found,
        lacuerda_leads,
        search_gametabs,
        search_gtptabs,
        search_harptabs,
        search_lacuerda,
        search_library,
        search_musescore,
        search_removed,
        suggestions,
    )
    from caracole.songs import list_songs

    mine = search_library(conn, q, LIBRARY_HITS)
    # A song of yours by its title matches well: nothing to suggest, and no close spelling looked for.
    yours = any(h.score >= STRONG and h.via != "artist" for h in mine)
    removed = search_removed(conn, q, LIBRARY_HITS)
    skipped, partial = _skipped(app, conn)
    left_out = {s["source"] for s in skipped}
    _after_reads(app)
    cached = app._found.get(q)
    if cached is not None and time.monotonic() - cached[0] < CACHE_SECONDS:
        (index_found, index, artists, hint, unseen, gtptabs, musescore, harp_artists, harptabs, lc_artists, lacuerda,
         gametabs, close) = cached[1:]
    else:
        index_found, index, artists, hint, unseen = _index_hits(conn, q)
        gtptabs = search_gtptabs(conn, q, SITE_HITS) if "gtptabs" not in left_out else []
        musescore = search_musescore(conn, q, SITE_HITS) if "musescore" not in left_out else []
        harp_artists, harptabs = (search_harptabs(conn, q, songs=SITE_HITS) if "harptabs" not in left_out
                                  else ([], []))
        lc_artists, lacuerda = (search_lacuerda(conn, q, songs=SITE_HITS) if "lacuerda" not in left_out
                                else ([], []))
        gametabs = search_gametabs(conn, q, SITE_HITS) if app.cfg.provider("gametabs").enabled else []
        close = None  # looked for below, once a song of yours doesn't make it moot
        app._found[q] = (time.monotonic(), index_found, index, artists, hint, unseen, gtptabs, musescore,
                         harp_artists, harptabs, lc_artists, lacuerda, gametabs, close)
        while len(app._found) > CACHE_SIZE:
            app._found.popitem(last=False)
    if close is None and not yours:
        close = suggestions(conn, q, index_found, [*lc_artists, *lacuerda, *gtptabs, *musescore, *harp_artists,
                                                   *harptabs], lacuerda="lacuerda" not in left_out,
                            harptabs="harptabs" not in left_out, gtptabs="gtptabs" not in left_out)
        if q in app._found:
            app._found[q] = (*app._found[q][:-1], close)
    answer = found(mine, index_found)
    leads = lacuerda_leads(index_found, lc_artists)
    songs = list_songs(conn)
    progression, playing = _progression(conn, q, {h.song.id for h in mine})
    # The artists' most tabbed songs are the index's songs too, drawn as they are: each with its song of yours.
    tops = [t for a in artists for t in a["top"]]
    library, hits = _rows(app, conn, [*mine, *playing], [*index, *tops], songs)
    hits, owned = hits[:len(index)], iter(hits[len(index):])
    artists = [{**a, "top": [next(owned) for _ in a["top"]], "gtptabs": _gtptabs_songs(app, conn, a["artist"])}
               for a in artists]
    best = answer.best
    # LaCuerda's group leads: Ultimate Guitar's artist a word names (Javier Calamaro, beside LaCuerda's Andrés
    # Calamaro) is no lead, and Enter opens LaCuerda's artist.
    lead = "song" if leads and answer.lead == "artist" else answer.lead
    pick = None if best is None else (
        {"library": best.song.id} if isinstance(best, LibraryHit) else {"ug": f"{best.artist_key}/{best.song_key}"})
    return {"query": q, "library": library, "index": hits, "artists": artists, "lead": lead,
            "best": pick, "hint": hint, "progression": progression, "unseen": unseen,
            "removed": [{"artist": h.artist, "title": h.title, "key": h.key, "removed_at": h.removed_at,
                         **_key_parts(h.key)} for h in removed],
            "gtptabs": _gtptabs_rows(app, conn, gtptabs if "gtptabs" not in left_out else [], songs),
            "musescore": [{"source": h.source, "title": h.title, "url": h.url, "score": h.score}
                          for h in (musescore if "musescore" not in left_out else [])],
            # harptabs.com's songs, a song's harmonica tabs by an artist whose page caracole read, else a tab by its
            # title alone, a possible match, as MuseScore's pages are; and its artists, as LaCuerda's
            "harptabs": _harptabs_rows(app, conn, harptabs, songs),
            "harptabs_artists": [_harptabs_artist_json(app, conn, a, songs) for a in harp_artists],
            # gametabs.net's tracks of games, the game as the artist, each with its tabs
            "gametabs": _gametabs_rows(app, conn, gametabs, songs),
            "lacuerda": _lacuerda_rows(app, conn, lacuerda, songs),
            "lacuerda_artists": [{**_lacuerda_artist_json(app, conn, a, songs),
                                  "gtptabs": _gtptabs_songs(app, conn, a.artist)} for a in lc_artists],
            "lacuerda_unlisted": _lacuerda_unlisted(conn, q, index_found, lc_artists, lacuerda),
            "lacuerda_leads": leads,
            "lacuerda_search": (_lacuerda_search_gate(app, conn, q, lc_artists, lacuerda, mine)
                                if app.searches_lacuerda else None),
            "suggest": [_suggestion_json(app, conn, s, songs) for s in (() if yours else close or ())],
            "skipped": skipped, "partial": partial, "looked": _looked(conn, skipped, partial)}


SUGGESTED_KEY = {"ug": "artist_key", "lacuerda": "slug", "harptabs": "path"}  # what /api/artist takes of each site


def _suggestion_json(app: WebApp, conn: sqlite3.Connection, s: Suggestion, songs: list[Song]) -> dict[str, Any]:
    """A suggestion as the pages draw it: the artist's band (their site, name, songs there, group, and what /api/artist
    takes of them: Ultimate Guitar's ``artist_key``, the ``slug`` of their LaCuerda page, the ``path`` of their
    harptabs.com page); a song's, its ``title`` too, the song on each index that has it (``song``: its ``ug``,
    ``lacuerda``, ``gtptabs`` and ``harptabs`` rows, each as the search's rows of that site are, a song of yours named
    on them) and, for a song of yours, its row as your songs' rows are (``library``), else None."""
    from caracole.search import IndexHit, LibraryHit

    said = {"source": s.source, "artist": s.artist, SUGGESTED_KEY.get(s.source, "key"): s.key, "songs": s.songs,
            "group_key": _group_key(s.artist)}
    if not s.title:
        return said
    rows: dict[str, dict[str, Any]] = {}
    for h in s.hits:
        source = "ug" if isinstance(h, IndexHit) else h.source
        if source in rows:
            continue
        if isinstance(h, IndexHit):
            rows[source] = _rows(app, conn, [], [_hit_json(conn, h)], songs)[1][0]
        elif source == "lacuerda":
            rows[source] = _lacuerda_rows(app, conn, [h], songs)[0]
        elif source == "gtptabs":
            rows[source] = _gtptabs_rows(app, conn, [h], songs)[0]
        else:
            rows[source] = _harptabs_rows(app, conn, [h], songs)[0]
    yours = next((r["song"] for r in rows.values() if r.get("song") is not None), None)
    song = next((x for x in songs if x.id == yours), None)
    library = _rows(app, conn, [LibraryHit(song, 100.0, "title")], [], songs)[0][0] if song is not None else None
    return {**said, "title": s.title, "song": rows, "library": library}


def _progression(conn: sqlite3.Connection, q: str, mine: set[int]) -> tuple[dict[str, Any] | None, list[LibraryHit]]:
    """The progression the query types or names (``progressions.read_progression``), as the answer's
    ``progression`` says it (its key, how it is said, its catalogue name, how many of your songs play it),
    and those songs the words didn't find already, the first ``LIBRARY_HITS``, as your songs read by it
    (``via`` "progression"); None and none for a query that is no progression."""
    from caracole.progressions import read_progression, songs_with
    from caracole.search import LibraryHit

    wanted = read_progression(q)
    if wanted is None:
        return None, []
    playing = songs_with(conn, wanted)
    said = {"key": wanted.key, "label": wanted.label, "name": wanted.name, "songs": len(playing)}
    return said, [LibraryHit(p.song, 100.0, "progression") for p in playing if p.song.id not in mine][:LIBRARY_HITS]


def _gtptabs_songs(app: WebApp, conn: sqlite3.Connection, artist: str) -> int:
    """How many songs gtptabs.com's index lists by an artist the query names (``search.gtptabs_songs``), which their
    group's header on the library page says ("Estopa · UG 60 · LaCuerda 159 · Guitar Pro 12"); none while gtptabs.com
    is turned off, as the search then lists none of its pages."""
    from caracole.search import gtptabs_songs

    return gtptabs_songs(conn, artist) if app.cfg.provider("gtptabs").enabled else 0


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


def _harptabs_rows(app: WebApp, conn: sqlite3.Connection, hits: Sequence[SiteHit],
                   songs: list[Song]) -> list[dict[str, Any]]:
    """harptabs.com's songs as the pages draw them: a song by an artist whose page caracole read, with its tabs, the
    most viewed first (``tabs``: each one's title, page and chips), and its song of your library, as gtptabs.com's
    are; a tab by its title alone (no artist), a possible match, its title and page alone."""
    known = [h for h in hits if h.artist]
    owners = iter(_owners(app, conn, known, songs))
    return [{"source": h.source, "artist": h.artist, "title": h.title, "url": h.url, "uploads": h.uploads,
             "score": h.score, "via": h.via, "page": h.page,
             "tabs": [{"title": t.title, "url": t.url, "views": t.views, "rating": t.rating, "key": t.key,
                       "difficulty": t.difficulty} for t in h.tabs],
             **_keys(h.artist, h.title), **next(owners)} if h.artist else
            {"source": h.source, "title": h.title, "url": h.url, "score": h.score} for h in hits]


def _gametabs_rows(app: WebApp, conn: sqlite3.Connection, hits: Sequence[SiteHit],
                   songs: list[Song]) -> list[dict[str, Any]]:
    """gametabs.net's tracks as the pages draw them: the game as the artist, the track as the title, its tabs, the
    most viewed first (``tabs``: each one's title, page, views, rating, instruments and composers, as its game's page
    said them), what they are for (``instruments``) and who composed them (``composers``), and its song of your
    library, as gtptabs.com's are."""
    owners = iter(_owners(app, conn, hits, songs))

    def names(h: SiteHit, part: str) -> list[str]:
        return list(dict.fromkeys(n for t in h.tabs for n in getattr(t, part, ())))

    return [{"source": h.source, "artist": h.artist, "title": h.title, "url": h.url, "uploads": h.uploads,
             "score": h.score, "via": h.via, "page": h.page, "instruments": names(h, "instruments"),
             "composers": names(h, "composers"),
             "tabs": [{"title": t.title, "url": t.url, "views": t.views, "rating": t.rating,
                       "instruments": list(getattr(t, "instruments", ())), "composers": list(getattr(t, "composers", ()))}
                      for t in h.tabs],
             **_keys(h.artist, h.title), **next(owners)} for h in hits]


def _harptabs_artist_json(app: WebApp, conn: sqlite3.Connection, a: SiteArtist, songs: list[Song]) -> dict[str, Any]:
    """A harptabs.com artist as the pages draw them: the tabs their page says they have (``songs``, 0 until it is
    read), those the index holds (``known``) and the songs they are of (``held``), whether caracole has read their
    page (``read``, one that lists no tab too), their most viewed songs (``top``, as ``_harptabs_rows``), their page's
    ``path``, and the group the library page puts them in (``group_key``)."""
    held = conn.execute("SELECT COUNT(DISTINCT song_key) FROM harptabs_artist_tabs WHERE artist = ?",
                        (a.slug,)).fetchone()[0]
    return {"source": a.source, "artist": a.artist, "path": a.slug, "url": a.url, "songs": a.songs, "known": a.known,
            "held": held, "read": a.read, "score": a.score, "via": a.via, "part": a.part,
            "group_key": _group_key(a.artist),
            "top": _harptabs_rows(app, conn, a.top, songs)}


def _keys(artist: str, title: str) -> dict[str, str]:
    """The keys a row merges on across sites (``normalize.identity_key``, split): the same song from
    Ultimate Guitar, LaCuerda and gtptabs.com shares both, and a song of yours (its key) or one you removed."""
    from caracole.normalize import identity_key

    return _key_parts(identity_key(artist, title))


def _key_parts(key: str) -> dict[str, str]:
    artist_key, _, title_key = key.partition("/")
    return {"artist_key": artist_key, "title_key": title_key}


def _group_key(artist: str) -> str:
    """An artist's group on the library page: the artist key of their songs' rows (``_keys``)."""
    return _keys(artist, "")["artist_key"]


def _owners(app: WebApp, conn: sqlite3.Connection, hits: Sequence[SiteHit], songs: list[Song]) -> list[dict[str, Any]]:
    """Each site hit's song of your library (``_Mine``, by its names), as ``song`` and ``library`` (its names,
    its status and its card's links), and whether its artist is your song's (``same_artist``); None for one your library
    hasn't."""
    from caracole.library_page import result_cards

    owners_of = _Mine(songs, app._song_forms)
    owners = [owners_of.song_for(h.artist_key, h.title_key, h.artist, h.title) for h in hits]
    cards = result_cards(conn, app.cfg, list({s.id: s for s in owners if s}.values()))
    return [{"song": song.id if song else None,
             "same_artist": song is not None and owners_of.same_artist(song, h.artist_key, h.artist),
             "library": {"id": song.id, "artist": song.artist, "title": song.title, "display": song.display,
                         "status": song.status, "links": cards[song.id]["links"]} if song else None}
            for h, song in zip(hits, owners)]


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
    harptabs = _harptabs_left_out(app, conn)
    if harptabs is not None:
        said = {"source": "harptabs", "name": "harptabs.com", "why": harptabs[1]}
        (partial if harptabs[0] == "partial" else left).append(said)
    return left, partial


def _harptabs_left_out(app: WebApp, conn: sqlite3.Connection) -> tuple[str, str] | None:
    """Why a search of harptabs.com's index finds less than the site has, worded to follow "harptabs.com's" as
    ``_skipped`` words a site's: ("off", …) turned off, ("empty", …) before its sitemap is read, ("partial", …) while
    its artist pages aren't all read, with how many are (harptabs_index.py); None once every one is."""
    from caracole.harptabs_index import index_state

    if not app.cfg.provider("harptabs").enabled:
        return "off", "turned off in caracole.toml"
    if conn.execute("SELECT 1 FROM harptabs_index LIMIT 1").fetchone() is None:
        return "empty", "its index is empty: the nightly run reads its sitemap"
    state = index_state(conn)
    if state.read >= state.artists:
        return None
    return "partial", (f"its artist pages are still being read: {state.read:,} of {state.artists:,} artists so far; "
                       "caracole harptabs --index reads the rest")


def _looked(conn: sqlite3.Connection, skipped: list[dict[str, str]],
            partial: list[dict[str, str]]) -> list[dict[str, str]]:
    """Where the search looked, a site a mark on the pages: Ultimate Guitar's index, gtptabs.com's, LaCuerda's and
    MuseScore's, each with its ``state`` (``done``: searched whole; ``partial``: LaCuerda's while its listings are
    read; ``empty``, ``blocked``: MuseScore's, while it blocks caracole; ``off``: turned off in caracole.toml), its
    ``label`` ("UG ✓", "LaCuerda: up to C": the letters read whole run from the first to C) and its ``detail``, one
    line: what ``skipped`` and ``partial`` say of it."""
    from caracole.lacuerda import LETTERS
    from caracole.lacuerda_index import letters_read, letters_text

    said = {s["source"]: s for s in [*skipped, *partial]}
    looked = []
    ug_empty = conn.execute("SELECT 1 FROM ug_index LIMIT 1").fetchone() is None
    looked.append({"source": "ug", "name": "Ultimate Guitar", "state": "empty" if ug_empty else "done",
                   "label": "UG: empty" if ug_empty else "UG ✓",
                   "detail": UG_EMPTY if ug_empty else "Ultimate Guitar: caracole's copy of its index, searched whole."})
    for source, name in (("gtptabs", "gtptabs.com"), ("lacuerda", "LaCuerda"), ("musescore", "MuseScore"),
                         ("harptabs", "harptabs.com")):
        s = said.get(source)
        why = str(s["why"]) if s else ""
        if source == "harptabs" and s in partial:  # its artist pages read so far, as the line says them
            from caracole.harptabs_index import index_state

            state = index_state(conn)
            looked.append({"source": source, "name": name, "state": "partial",
                           "label": f"{name}: {state.read:,} of {state.artists:,} artists",
                           "detail": f"{name}'s {why.removeprefix('its ')}."})
            continue
        if s is None:
            state, label, detail = "done", f"{name} ✓", f"{name}: caracole's copy of its index, searched whole."
        elif why.startswith("turned off"):
            state, label, detail = "off", f"{name}: off", f"{name} is turned off in caracole.toml."
        elif "blocking" in why:
            state, label, detail = "blocked", f"{name} blocked", why[:1].upper() + why[1:] + "."
        elif s in partial:
            read = letters_read(conn)
            run = 0
            while run < len(read) and read[run] == LETTERS[run]:
                run += 1
            state = "partial"
            label = (f"{name}: up to {letters_text(read[run - 1:run])}" if run == len(read) and run else
                     f"{name}: {letters_text(read)} only" if read else f"{name}: in part")
            detail = f"{name}'s {why.removeprefix('its ')}."
        else:
            state, label, detail = "empty", f"{name}: empty", f"{name}'s {why.removeprefix('its ')}."
        looked.append({"source": source, "name": name, "state": state, "label": label, "detail": detail})
    return looked


def _rows(app: WebApp, conn: sqlite3.Connection, mine: Sequence[LibraryHit], index: list[dict[str, Any]],
          songs: list[Song] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Your songs and the index's, as the page draws them. A song of your library comes as its card
    has it (``result_cards``): its files (``links``, its viewer the primary one), where its sheet
    came from, its key; and the files its sheet can be read in on the page (``files``). An index
    song your library has (``_Mine``) names it, with its links, and says whether its artist is your
    song's (``same_artist``: not for your cover matched to the original's tab)."""
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
             "same_artist": song is not None and owners_of.same_artist(song, hit["ug"].split("/", 1)[0], hit["artist"]),
             "library": {"id": song.id, "artist": song.artist, "title": song.title, "display": song.display,
                         "status": song.status, "links": cards[song.id]["links"]} if song else None}
            for hit, song in zip(index, owners)]
    return library, hits


def _index_hits(conn: sqlite3.Connection, q: str) -> tuple[IndexFound, list[dict[str, Any]],
                                                           list[dict[str, Any]], str | None, dict[str, Any] | None]:
    from caracole.search import IndexFound, bare_id_hint, bare_id_unseen, find_index
    from caracole.ug.index import index_count

    if index_count(conn) == 0:
        return IndexFound(), [], [], UG_EMPTY, None
    answer = find_index(conn, q, songs=INDEX_HITS)
    # An artist with their most tabbed songs, each as the index's songs are (``_hit_json``), and the group the
    # library page puts them in (``group_key``); ``artist_key`` is UG's, which /api/artist takes.
    artists = [{"artist_key": a.artist_key, "artist": a.artist, "score": a.score, "songs": a.songs, "tabs": a.tabs,
                "part": a.part, "group_key": _group_key(a.artist), "top": [_hit_json(conn, h) for h in a.top]}
               for a in answer.artists]
    index = [_hit_json(conn, h) for h in answer.songs]
    hits = [*answer.songs, *answer.artists]
    return answer, index, artists, bare_id_hint(q, hits), bare_id_unseen(q, hits)


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
                gtptabs = _gtptabs_songs(app, conn, named.artist)
        except (sqlite3.Error, OSError) as e:
            return json_response(503, {"error": f"The database can't be read: {e}"})
    return json_response(200, {"source": "lacuerda", "slug": named.slug, "artist": named.artist, "url": named.url,
                               "group_key": _group_key(named.artist), "listed": named.songs, "total": named.known,
                               "read": named.known > 0, "gtptabs": gtptabs, "songs": hits, "library": library})


def api_harptabs_artist(app: WebApp, path: str) -> Response:
    """A harptabs.com artist, for the pages: the songs its index holds of theirs, most viewed first, and yours by
    them; ``read`` says whether caracole has read their page, ``listed`` the tabs it says they have and ``total``
    those the index holds. By their page's path."""
    from caracole.search import LibraryHit, harptabs_artist, harptabs_songs, library_by_artist
    from caracole.songs import list_songs

    if not path:
        return json_response(400, {"error": "Which artist? The address names none."})
    with app._searching:
        try:
            with closing(app.connect()) as conn:
                named = harptabs_artist(conn, path) if _HARP_ARTIST.fullmatch(path) else None
                if named is None:
                    return json_response(404, {"error": "harptabs.com's index has no such artist."})
                read = conn.execute("SELECT 1 FROM harptabs_artists WHERE path = ?", (path,)).fetchone() is not None
                songs = list_songs(conn)
                theirs = [LibraryHit(s, 100.0, "artist") for s in library_by_artist(songs, named.artist)]
                library, _ = _rows(app, conn, theirs, [], songs)
                hits = _harptabs_rows(app, conn, harptabs_songs(conn, path), songs)
        except (sqlite3.Error, OSError) as e:
            return json_response(503, {"error": f"The database can't be read: {e}"})
    return json_response(200, {"source": "harptabs", "path": path, "artist": named.artist, "url": named.url,
                               "group_key": _group_key(named.artist), "listed": named.songs, "total": named.known,
                               "read": read, "songs": hits, "library": library})


def harptabs_read(app: WebApp, form: dict[str, str], *, wants_json: bool) -> Response:
    """A harptabs.com artist's page read into its index: ``caracole harptabs --artist`` queued, a job of its own (one
    request at the lookup pace, none when caracole read it within 30 days); asked again while it waits or runs, that
    job. By the ``path`` of a page the sitemap lists."""
    from caracole.search import harptabs_artist

    path = form.get("path", "").strip()
    if not _HARP_ARTIST.fullmatch(path):
        raise Refused(400, "Not an artist", "Which artist? The form names no harptabs.com artist page.")
    with app.db() as conn:
        named = harptabs_artist(conn, path)
    if named is None:
        raise Refused(404, "No such artist", "harptabs.com's index has no such artist.")
    job, _ = app.submit(f"Read the page of {named.artist} on harptabs.com", HARPTABS_ARTIST + path,
                        harptabs_artist_steps(path, named.artist), display=f"{named.artist} on harptabs.com")
    with app._searching:
        app._reads.add(job.id)
    if wants_json:
        return json_response(202, {"job": job.id, "url": f"/api/jobs/{job.id}"})
    return redirect(f"/{details_href(job.id)}")


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
    return redirect(f"/{details_href(job.id)}")


def _lacuerda_search_gate(app: WebApp, conn: sqlite3.Connection, q: str, lc_artists: Sequence[SiteArtist],
                          lc_songs: Sequence[SiteHit], mine: Sequence[LibraryHit]) -> dict[str, str] | None:
    """What sending LaCuerda's search for ``q`` would be (lacuerda_search.py's ``gate``), with no request: None, or
    its ``state``, the ``query`` and its ``key``, and, ``failed``, why the page doesn't send it by itself (``why``).
    ``lc_artists``, ``lc_songs``: LaCuerda's index's answer for it, and ``mine`` your library's, which make it none
    when they answer well already (``lacuerda_search.answers_well``): a strong song, an artist the query names,
    whole, whose page caracole has read, or a strong song of yours."""
    from datetime import UTC, datetime

    from caracole.lacuerda_search import answers_well, gate

    said = gate(app.cfg, conn, q, strong=answers_well(lc_artists, lc_songs, mine), now=datetime.now(UTC))
    if said is None:
        return None
    why = {"why": said.failure.said(f"“{q}”") + "."} if said.failure is not None else {}
    return {"state": said.state, "query": q, "key": said.key, **why}


def lacuerda_search(app: WebApp, form: dict[str, str], *, wants_json: bool) -> Response:
    """LaCuerda's search for a query (``q``), its rows read into the index: ``caracole lacuerda --search --progress``
    queued, a job of its own (one request, at the lookup pace), ``--auto`` unless asked ``by_hand`` (the button, Enter);
    asked again while it waits or runs, under any spelling LaCuerda reads the same, that job. Refused as its gate
    refuses it (``_lacuerda_search_gate``): no word LaCuerda reads (400), LaCuerda's index or your library has the
    song or the query was asked within 30 days (409), a cooldown or the hour's lookups spent, or, without
    ``by_hand``, the page's share of them spent or a search that failed lately (429)."""
    from caracole.lacuerda_search import SEARCHES_PER_HOUR, query_key
    from caracole.search import search_lacuerda, search_library

    q = " ".join(form.get("q", "").split())
    by_hand = form.get("by_hand", "") == "1"
    if not q or len(q) > QUERY_LIMIT:
        raise Refused(400, "Not a query", f"Which query? A search is 1 to {QUERY_LIMIT} characters.")
    if not query_key(q):
        raise Refused(400, "Not a query", f"LaCuerda's search reads only words of 4 letters or more: “{q}” has none.")
    with app.db() as conn:
        artists, songs = search_lacuerda(conn, q, songs=SITE_HITS)
        mine = search_library(conn, q, LIBRARY_HITS)
        said = _lacuerda_search_gate(app, conn, q, artists, songs, mine) if app.searches_lacuerda else None
    if said is None:
        raise Refused(409, "Found already", f"Your library or LaCuerda's index has “{q}” already: no search "
                                            "needed.")
    if said["state"] == "asked":
        raise Refused(409, "Searched already", f"LaCuerda was asked for “{q}” within 30 days: what it answered is "
                                               "in its index.")
    if said["state"] == "spent":
        raise Refused(429, "Not now", "LaCuerda is cooling down after a block, or this hour's lookups to it are "
                                      "spent: ask again later.")
    if said["state"] == "failed" and not by_hand:
        raise Refused(429, "Not by itself", f"{said['why'].removesuffix('.')}: press Ask LaCuerda to ask anyway.")
    if said["state"] == "button" and not by_hand:
        raise Refused(429, "Not by itself", f"This hour's {SEARCHES_PER_HOUR} searches the page sends by itself are "
                                            "spent: press Ask LaCuerda to ask anyway.")
    job, _ = app.submit(f"Search LaCuerda for “{q}”", LACUERDA_SEARCH + said["key"],
                        lacuerda_search_steps(q, auto=not by_hand), display=f"“{q}” on LaCuerda")
    with app._searching:
        app._reads.add(job.id)
    if wants_json:
        return json_response(202, {"job": job.id, "url": f"/api/jobs/{job.id}"})
    return redirect(f"/{details_href(job.id)}")


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


def _lacuerda_artist_json(app: WebApp, conn: sqlite3.Connection, a: SiteArtist, songs: list[Song]) -> dict[str, Any]:
    """A LaCuerda artist as the page draws them: their songs as the listing counts them, those the index holds
    (``known``: 0 until caracole has read their page), the most popular with chords, as LaCuerda's songs are
    (``_lacuerda_rows``), and the group the library page puts them in (``group_key``)."""
    return {"source": a.source, "artist": a.artist, "slug": a.slug, "url": a.url, "songs": a.songs, "known": a.known,
            "score": a.score, "via": a.via, "group_key": _group_key(a.artist),
            "top": _lacuerda_rows(app, conn, a.top, songs)}


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

    def same_artist(self, song: Song, artist_key: str, artist: str) -> bool:
        """Whether a site's artist (its key and its name) is one of your song's artists, by their names'
        forms: UG's "Acdc" is your AC/DC, "Song Dongye" your 宋冬野; the artist of the original you matched
        your cover to is not."""
        from caracole.normalize import compact, name_forms

        artists, _ = self._forms_of(song)
        return compact(artist_key) in artists or any(compact(f) in artists for f in name_forms(artist))

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
