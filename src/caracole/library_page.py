"""Library/index.html: browse and search the whole library, on a phone or a laptop (A7).

One self-contained file, rewritten wherever ``_todo.md`` is. It opens from the
Syncthing folder with no server: it loads nothing from the network (a
Content-Security-Policy with the hashes of its one script and one stylesheet
makes the browser enforce that), and it links to each song's files by
relative paths. That script and that stylesheet are the files of
library_assets/, inlined as they are (``STYLESHEETS``, ``SCRIPTS``), and so
is the markup around the songs (``TEMPLATES``); its Songbooks tab's data is
songbook_section.py's.

Every song is in a ``<script type="application/json">`` block. Titles come
from Spotify and from your own wanted.txt, so the page's script builds every
element with ``createElement`` and ``textContent``, never ``innerHTML``, and
the JSON has each ``<`` written as ``\\u003c``: escaping only ``</`` would
still let a ``<!--`` change how the HTML tokenizer reads the block.

Each song carries a search string: its artist, title and display name folded
(accents stripped, lowercase), the same without punctuation ("acdc"), and
pinyin for Chinese ("ban ma ban ma", "banma"), and its title's initials
("wywh", typed whole). The page folds what you type the same way, so "musica"
finds "Música" and "ban ma" finds 斑马，斑马.
Of a song's key, the string holds only the mode ("minor"): the script reads a
key typed in the box ("a minor", "f#m") and compares it, as the Key menu does,
by the tonic's pitch class and the mode, so "Gb minor" finds "F# minor".

The songs are dense lines (``resultRow``'s ``dense`` form, ROWS_SCRIPT's), a
song a line on a laptop, about thirty to its screen, two lines a song on a
phone. By artist, the order the page opens in, they are grouped under their
artist's name, artists A to Z, each group's header saying how many of their
songs you have, whatever the search or a filter leaves out ("Soda Stereo · you
have 2"); by title or by when they came,
they stand alone, each with its artist. A line holds the song's title, which
opens its sheet (its viewer, else its PDF, else its text), its status (Found,
Wanted, Needs review, Not found), its key, the marks of where its sheet and its
files came from and its main action: Open, or, served, Fetch now or Pick the
match. Everything else a song has is under its "⋯": its facts (the key in words
and where it came from, the transposition, the lyrics, when it came), its
review's picker, where its audio comes from, its versions (the sheet's PDFs
in other versions, each file's ``version``), its other files, the Guitar Pro
versions to download from UG, its MuseScore pages, its search and buy links, Add
to a songbook… (the Select mode, the song picked) and, served, Remove…. An
artist's name, marked with a funnel (``artistFilter``, ROWS_SCRIPT's), shows that
artist's songs alone. An A-Z strip jumps to the first group (or line) of a letter
once more than 40 songs show. On a phone the header is short (the numbers beside
the title, then one row of buttons and menus that scrolls sideways), so the first
song starts on the first screen; the bar stays at the top, with an edge once the
page scrolls under it. The address remembers the search, the filters, the sort
and the key.

On a touch screen (``pointer: coarse``) every control is a thumb's target, 44
px each way at the least: buttons, folds, chips, menus, letters, a line's
button and "⋯" and an artist's name; a mouse keeps the compact sizes. Fields,
menus and the Select boxes have the ``--control-edge`` colour, 3:1 or more
against every background (WCAG 1.4.11); boxes and dividers keep the soft
``--border``. ``BASE_STYLE`` and ``PICKER_STYLE`` carry both to
the pages caracole serve writes itself (web/pages.py, web/lookup_page.py).

Each file, link and line shows where it came from (icons.py): the site's own
icon, inlined in the data as a ``data:`` URI (the CSP allows images from
``data:`` alone), else the site's lettered badge, or a glyph for the audio
model and the inbox; each is named "from Ultimate Guitar" for a screen reader.
An auto sheet made from the audio caracole took from YouTube shows YouTube's
(``icons.kept_sources``), and its line's "⋯" the video.

The seam for lists the page doesn't make itself (the results of caracole
serve's lookup page, web/lookup_page.py, which runs ``ROWS_SCRIPT`` and has
``ROWS_STYLE`` as this page does, and gets each song's files from
``result_cards``): ``window.caracole.resultRow(result)`` returns a row
element, to put in a ``<div class="rows">``, or with ``dense``, a line as a
song's is (``article.line``: ``.line-title``, ``.line-status``, ``.line-key``,
``.line-sources``, ``.line-action``, ``.line-more``), to put in a ``<div
class="lines">``. ``result`` is a plain object, every field optional:

- ``title``, ``artist``: text; ``onArtist``, a function, makes the artist a button that
  shows it filters (a funnel after the name), as a group's name is; a line shows its
  artist only where no artist's group holds it;
- ``href``: what the title opens (the song's sheet, as its button does), the same way as
  ``action``'s link; out of the Tab order, since the button says what it opens;
- ``source``: a key of the data's ``icons`` (``icons.SOURCES``: "ug", "lacuerda"…), or, for
  a line, ``sources``, several, each marked once;
- ``key`` ("A minor"), and ``keyText``, what a screen reader hears for it;
- ``status``, which its ``data-status`` gets; ``badges``: ``[{kind, text}]``,
  ``kind`` a badge class (found, wanted, review, auto…); ``facts``: a line of text;
- ``action``: the main control, a Node, or ``{label, href, source}``: an http(s)
  link opens in a new tab, any other address stays relative or goes nowhere;
- ``more``: what its "⋯" button shows, Nodes or
  ``{heading, links: [{label, href, source}]}``.

``window.caracole.sourceMark(key)`` gives a source's mark alone, and
``window.caracole.icons`` the icons' data. ``ROWS_SCRIPT`` also draws the
offline indexes' hits, as ``/api/search`` and ``/api/artist`` give them: for
this page's search, a song of the sites as a dense line (``indexLine``: one
line however many sites have it, each site's mark and counts on it, its
identity its ``data-hit``) and MuseScore's pages (``titleLine``); for the
lookup page, rows (``ugHit``, ``artistHit``, ``siteHit``, ``siteArtist`` and
``siteArtistSongs``, LaCuerda's artists and their songs); and for both
``siteUnlisted``, a name under a letter LaCuerda's listings aren't read to yet,
with ``readArtistPage``, which asks the server to read an artist's page, by its
slug or by a name, and ``readOutcome``, what LaCuerda answered a read that left
nothing to list.

**One bar.** The search box filters your songs as you type, here. The file can
ask nothing of anyone: Enter shows the ``caracole search`` line to run, with
Copy, above your songs (in their empty list when none match). Served, typing
searches the sites too, from the third letter (two with a Chinese character,
as ``/api/search`` looks nowhere for fewer), a moment after the last key, no
Enter and no button: the results take the list's place until Escape, under the
same artist headers as the list's (the script's ``mergeSites``), each artist's
header counting your songs of theirs and, for an artist the query names, the
songs Ultimate Guitar's and LaCuerda's indexes list ("Estopa · you have 2 · UG
60 · LaCuerda 159"). Under an artist: your songs that match, as their own lines;
the songs you removed that match ("Removed 2026-10-20", Add again: a
``POST /request`` with Fetch it now, as the request form asks, whose wanted.txt
line brings it back); then the indexes' songs (``GET /api/search``: the newest
query alone, the sites left out, or searched in part, said with why), a song a
line, keyed by its identity key's two parts (the rows' ``artist_key`` and
``title_key``, an artist's ``group_key``; a song of yours by its ``identity``),
so that Ultimate Guitar's, LaCuerda's and gtptabs.com's rows of one song are
one line, and a row of a song of yours is your song's line, its artist's rows
under your artist's header. An artist the query names shows their most tabbed
songs, then "+ 57 more by Estopa", the rest in the group fifty at a time
(``/api/artist``); a LaCuerda artist the rest the index holds of theirs, or the
offer to read their page (``POST /lacuerda/artist``), and so does a query
LaCuerda's index has no artist by while the listing of its letter isn't read
whole, under the groups. MuseScore's pages, titles alone, come last under a
header of their own. A line's Get it (``POST /lookup``) shows its request's line
in the line itself. Enter moves the focus to the first result and never spends a
request. A wanted song whose sheet you picked on LaCuerda says that tonight's
run gets it (``lacuerda``), and isn't a song not found (``notFound``). The
request form sits under the results, filled in from the query.

``caracole serve`` serves the same page with ``controls`` (``WebControls``): the
search of the sites as you type, a form to request a song, a "Fetch now" button on each wanted song, a "Remove…"
button under each song's "⋯" (it counts down five seconds, with Undo, before it sends anything), and a
CSP that lets the forms post to the server (``form-action 'self'``) and the script
ask it how its requests go (``connect-src 'self'``). The script posts the forms
with fetch(), so the page stays where it is: each song's line shows its
request's one line (web/status.py), a line of its own across it, from ``/jobs.json``, asked every
1.5 s while one waits or runs, and is drawn again from the song's new data once the
request is over. Pick the match (a review held up a fetch), or Removing…, is a line's button then;
the picker and Look in the index are under its "⋯". A song new to the library gets a line of its own
under the bar, and two requests or more also show in a corner, folded to one line that opens upwards. Without
JavaScript the forms post as forms. The file on disk has none of it, and lets
no form be sent and nothing be asked.

Remove… stays on the page: one tap and the song's own line says "Removing in 5 s
· Undo", the focus on Undo, with what goes in one sentence under it (the
server's answer to the question, ``removal.brief``: caracole's files of the
song, its record, its wanted.txt line; never Music/). Nothing else is sent for
those five seconds, and Undo stops it ("Not removed", the focus back on
Remove…); then the page posts the removal with the song's key, and the line
follows it ("Removing…", "Removing from caracole…", then "Removed"), as tall as
it was. The song's line is then a ``gone`` one, its name alone, as tall as it was and
its request line where it was, until the page is loaded again. Without JavaScript,
Remove…'s question is a page of the server's; Remove it, and Keep it, come back
to this page as it was left (Remove… sends the address after # along, ``back``),
at the song's line: ``song=ID`` in the address, which the script scrolls to and
focuses, then drops.

**Two tabs.** Library, all of the above, and Songbooks (``#tab=songbooks`` in
the address, ``book=NAME`` the songbook open; library_assets/songbooks.js draws
it from the data's ``songbooks``, songbook_section.py's): on the left the
songbooks as lines, each with how many songs, how many still without a sheet and
when caracole last made its files, and "+ New songbook" (Select, on the
library); on the right, side by side from 900 px and one at a time on a phone,
the songbook opened as a set list, each song with where the songbook plays it
(``songbook.plays_in``) and its files: the PDF, the phone page, ChordPro. The
file on disk shows it read-only, with the ``caracole songbook`` commands that
change it. Served, a song's grip drags it to its place (or ↑ and ↓ move it, sent
a moment after the last key), its chip changes where it plays (its key, mode and
capo, ``POST /songbook/set``, the capo always sent with them, or its own
version), × takes it out, Get it looks it up now (``POST /songbook/get`` with
the song: its lookup, then the songbook made again), Get the N missing songs
now looks each up; Add a song searches your songs and the indexes as you type
(``/api/search``, which asks no site) and puts one in, looked up first when the
library hasn't got it (``POST /songbook/add-song``); Rename and Delete, under
Rename or delete. Each posts with fetch(): the songbook's status line says how
its change goes, a lookup's line its song's, and once a change is over
``/jobs.json`` brings the songbooks as they are now, which the tab draws again,
each line where it was (a song taken out, or a songbook deleted, says so where
it was until your next click or key, so that nothing moves meanwhile). Select's
Make songbook (or Add to) lands in the tab, on the songbook, its songs there at
once.

**Progressions.** Each song carries its sheet's progressions as its last render read them
(``progressions.library_progressions``: each cycle's key, the same in every key and rotation, and how
the song plays it), and the page the catalogue's names by key (``catalogue``). A song's "⋯" lists them,
each a button that shows the songs that play it alone, and so does ``#prog=<key>`` in the address (a
viewer's Harmony panel links there), under a line that says which ("Songs with I–V–vi–IV, the pop
progression · Show all"); a named progression stands for every progression of its name, so the pop
progression read in A minor is there too. Served, a progression typed or named in the bar
(``/api/search``'s ``progression``) says how many of your songs play it, with Show them.

A song in review carries its candidates (``review_choices``), numbered as
``caracole review`` numbers them, and its line a picker under its "⋯" (the script's
``makePicker``): a disclosure that lists them, each with its UG names, its
score, why the matcher thought of it and a link to its UG page. On the file
it is read-only, with the ``caracole review --song`` line that picks one;
served, it is a radio group posted to ``/review`` (web/review_routes.py), which the line's
Pick the match opens, in place of the "Review first" button, the focus on the first candidate.
A pick posts with fetch() as the other forms do, and the song's line says how
it goes; while any request of the song waits or runs, the picker offers no
pick, and the line's "Pick the match" (a request that ended in a review)
opens it.
A song not found carries ``notFound``, says "Not found", and its served line's "⋯" links to
``/review?song=ID``, which offers what ``caracole search`` finds for it: a
search per song would cost every page a moment each.
"""

from __future__ import annotations

import html as html_text
import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from caracole.config import Config
from caracole.icons import kept_sources, page_icons, source_of
from caracole.inbox import SCORE_EXTENSIONS
from caracole.inline import json_block, sha256_source
from caracole.keys import SongKey, key_name, song_key
from caracole.library import song_dir, write_atomic
from caracole.library_assets import BASE_STYLE, PICKER_STYLE, ROWS_SCRIPT, ROWS_STYLE  # noqa: F401
from caracole.library_assets import read as read_asset
from caracole.musescore import song_pages
from caracole.normalize import clean_title, fold, has_han, romanize, slug_key
from caracole.overrides import Overrides
from caracole.page_icon import LINK as PAGE_ICON
from caracole.progressions import catalogue, library_progressions
from caracole.songbook_section import songbooks_data
from caracole.songs import Song, is_export, list_songs
from caracole.todo import search_links, songs_to_buy
from caracole.youtube_fetch import (
    BLOCKED,
    CHORDS,
    DECLINED,
    DOWNLOADED,
    MISSING,
    QUEUED,
    UNUSABLE,
    SongState,
    route_problem,
    song_states,
)

# Importable from here too: the style and script caracole serve's own pages share with this one (BASE_STYLE,
# PICKER_STYLE, ROWS_STYLE, ROWS_SCRIPT: library_assets/), and the Songbooks tab's data (songbook_section.py).

PAGE_NAME = "index.html"

# Kept files, in the order a song's line lists them: the sheets' viewers and PDFs, then the song's exports (the
# sheet's PDF in other versions, by their versions), the rest of the first group; guitar-N.* goes between the two
# groups.
_SHEET_PAGES = ("sheet.html", "sheet.pdf", "sheet (auto).html", "sheet (auto).pdf")
_FIRST = (*_SHEET_PAGES, "sheet.txt", "sheet.cho", "lyrics.txt", "lyrics.lrc")
_LAST = ("tab.txt", "sheet (auto).txt", "sheet (auto).cho", "info.json")
_GUITAR = re.compile(r"guitar-(\d+)(\.[A-Za-z0-9]+)")
# Scores filed from _inbox/ (inbox.py), after the guitar files, in SCORE_EXTENSIONS' order.
_SCORE = re.compile(r"score-(\d+)(\.[a-z]+)")
_SCORE_FORMATS = {".mscz": "MuseScore", ".mxl": "MusicXML", ".musicxml": "MusicXML", ".pdf": "PDF", ".mid": "MIDI",
                  ".midi": "MIDI"}
_LABELS = {
    "sheet.html": "Sheet viewer",  # caracole/viewer: the sheet for the phone
    "sheet (auto).html": "Auto sheet viewer",
    "sheet.pdf": "Sheet PDF",
    "sheet (auto).pdf": "Auto sheet PDF",
    "sheet.txt": "Sheet text",
    "sheet.cho": "ChordPro",
    "lyrics.txt": "Lyrics",
    "lyrics.lrc": "Timed lyrics",
    "tab.txt": "Tab",
    "sheet (auto).txt": "Auto sheet text",
    "sheet (auto).cho": "Auto ChordPro",
    "info.json": "Info",
}
_HUMAN_SHEETS = ("sheet.txt", "sheet.pdf")
_AUTO_SHEETS = ("sheet (auto).txt", "sheet (auto).pdf")
_KIND_NAMES = {"guitar-pro": "Guitar Pro", "power": "Power Tab"}
# Letters normalize.fold transliterates because NFKD can't decompose them; the page folds
# typed queries with this table, so the values come from fold itself.
_TRANSLITERATED = "øØæÆœŒßẞđĐłŁþÞðÐıħĦ"
_PUNCTUATION = re.compile(r"[\W_]+")
_APOSTROPHES = re.compile(r"['’‘`´ʼ]")
_WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class WebControls:
    """What ``caracole serve`` adds to the page it serves (caracole/web/).

    ``csrf`` is the token every form posts back; ``busy`` holds the songs with a
    fetch queued or running, whose lines say so instead of offering another;
    ``active`` is how many requests are queued or running, for the masthead;
    ``held`` holds the songs a fetch must wait for a review of, whose lines say so;
    ``removing`` holds the songs with a removal queued or running, whose lines
    say so instead of offering Remove; ``jobs`` are the requests queued or
    running, as ``/jobs.json`` gives them, so they show their progress from the
    start: a song's, and a removal's, on its song's line, and a songbook's change
    on its songbook in the Songbooks tab (``kind``). ``timers``, which only the tests that
    drive the page on real time set (``WebApp(timers=...)``), are the script's
    timers in milliseconds in place of its own: ``poll``, between two asks of
    ``/jobs.json`` (1500), and ``undo``, Remove's countdown (5000); the page
    users get carries none.
    """

    csrf: str
    busy: frozenset[int] = frozenset()
    active: int = 0
    held: frozenset[int] = frozenset()
    removing: frozenset[int] = frozenset()
    jobs: tuple[dict[str, Any], ...] = ()
    timers: Mapping[str, int] | None = None


def build_library_page(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, now: datetime, *,
                       controls: WebControls | None = None, youtube: dict[int, SongState] | None = None) -> str:
    """The whole page: every song, its files, and the links to find what's missing.

    With ``controls``, the page ``caracole serve`` serves: the same, with its forms. ``youtube``: as
    ``song_cards`` takes it.
    """
    songs = song_cards(conn, cfg, overrides, now, youtube=youtube)
    data: dict[str, Any] = {
        "generated": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fold": {c: fold(c) for c in _TRANSLITERATED},
        "songs": songs,
        "icons": page_icons(cfg.cache_dir),  # each source's name, badge and inlined icon (icons.py)
        "catalogue": catalogue(),  # the progressions with a name, by key: #prog= finds each name's every reading
    }
    if controls is not None:
        data["server"] = {"csrf": controls.csrf, "busy": sorted(controls.busy), "active": controls.active,
                          "removing": sorted(controls.removing), "jobs": list(controls.jobs)}
        if controls.timers is not None:
            data["server"]["timers"] = dict(controls.timers)
        for song in songs:
            song["fetchable"] = song["id"] not in controls.held
    data["songbooks"] = songbooks_data(conn, cfg, overrides)  # the Songbooks tab's (songbooks.js draws it)
    # The page caracole serve serves may also ask it how its requests go (connect-src); the file can't.
    csp = (_CSP.replace("__FORMS__", "'self'; connect-src 'self'") if controls is not None
           else _CSP.replace("__FORMS__", "'none'"))
    return (
        _HEAD.replace("__CSP__", csp).replace("__ICON__", PAGE_ICON).replace("__STYLE__", _PAGE_STYLE)
        + _BODY.replace("__NAV__", _nav(controls)).replace("__REQUEST__", _request_form(controls))
        .replace("__REQUESTED__", _requested(controls))
        + json_block("songs", data)
        + f"<script>{_PAGE_SCRIPT}</script>\n</body>\n</html>\n"
    )


def song_cards(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, now: datetime,
               songs: list[Song] | None = None, *, youtube: dict[int, SongState] | None = None) -> list[dict[str, Any]]:
    """The songs' data (each song's "card", as ``/jobs.json`` names it), as the page's JSON holds it: of
    every song, or of ``songs``; a song in review with its candidates, for the picker (``_add_picks``);
    each file with where it came from. ``youtube``: where each song stands on the YouTube route
    (``song_states``; empty with the route off), when the caller has it already, else asked of these
    songs alone."""
    from caracole.render import pdf_transpose

    pages = _guitar_pro_pages(conn)
    sources = _downloaded(conn)
    origins = kept_sources(conn)
    exports = _exports(conn)
    library = list_songs(conn) if songs is None else songs
    keys = {s.id: song_key(conn, cfg.library_dir, s) for s in library}
    to_buy = {s.id for s in songs_to_buy(conn, library, overrides, now)[0]}  # the to-do page's buy list
    # With the YouTube route on, caracole takes those songs' audio itself: their lines say how it goes,
    # and only a song you turned YouTube down for is for buying.
    if youtube is None:
        youtube = song_states(conn, overrides, now, songs=library) if route_problem(cfg) is None else {}
    if youtube:
        to_buy = {i for i in to_buy if i not in youtube or youtube[i].state == DECLINED}
    musescore = cfg.provider("musescore").enabled
    cards = [_song(cfg.library_dir, s, overrides, keys.get(s.id), pages.get(s.id, []), s.id in to_buy,
                   sources.get(s.id, {}), _musescore_links(conn, s, overrides) if musescore else [],
                   _youtube_note(youtube.get(s.id)), origins=origins.get(s.id, {}), exports=exports.get(s.id, {}),
                   transpose=pdf_transpose(conn, overrides, s))
             for s in library]
    _add_picks(conn, library, cards)
    played = library_progressions(conn)  # each song's, as its last render read its sheet
    for song, card in zip(library, cards, strict=True):
        card["progressions"] = played.get(song.id, [])
    return cards


def result_cards(conn: sqlite3.Connection, cfg: Config, songs: list[Song]) -> dict[int, dict[str, Any]]:
    """What a list the page doesn't make itself shows of each song as its line does (caracole serve's
    lookup page, which draws them with ``ROWS_SCRIPT``): its files, relative to the library and
    percent-encoded, the primary one marked (its viewer, else its PDF, else its text), each with where
    it came from; where its sheet came from; its key. By song id."""
    origins = kept_sources(conn)
    exports = _exports(conn)
    cards = {}
    for s in songs:
        files = _files(cfg.library_dir, s, _file_names(song_dir(cfg.library_dir, s)), {}, origins.get(s.id, {}),
                       exports.get(s.id, {}))
        key = song_key(conn, cfg.library_dir, s)
        cards[s.id] = {"links": files, "source": next((f["source"] for f in files if f["primary"]), None),
                       "key": key.key if key else None}
    return cards


def sheet_href(library_dir: Path, song: Song) -> str | None:
    """The link to the song's sheet, its line's main file (relative to index.html), or None without one."""
    names = _file_names(song_dir(library_dir, song))
    return next((f["href"] for f in _files(library_dir, song, names, {}) if f["primary"]), None)


def review_choices(conn: sqlite3.Connection, song: Song,
                   cands: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The candidates of a song in review as the picker shows them, numbered as ``caracole review``
    numbers them (``review.candidates_of``), or ``cands`` (a song not found's search hits): the UG
    song (``ref``, as overrides.toml names it), its artist and title as UG writes them, its score, why
    the matcher thought of it (``review.step_words``), its tabs per type and a page of it on UG. A
    candidate the index no longer has is named from its keys, with no tabs and no page."""
    from caracole.review import candidates_of, ref, step_words
    from caracole.search import display_from_keys, index_song

    choices = []
    for n, cand in enumerate(candidates_of(song) if cands is None else cands, start=1):
        hit = index_song(conn, cand["artist_key"], cand["song_key"])
        artist, title = (hit.artist, hit.title) if hit else display_from_keys(cand["artist_key"], cand["song_key"])
        choices.append({
            "n": n,
            "ref": ref(cand),
            "artist": artist,
            "title": title,
            "score": round(float(cand.get("score") or 0)),
            "why": step_words(cand),
            "tabs": _tab_counts(hit.counts) if hit else "",
            "href": hit.url if hit else "",
        })
    return choices


def _add_picks(conn: sqlite3.Connection, library: list[Song], songs: list[dict[str, Any]]) -> None:
    """Give the data of each song in review (not ignored) its candidates, for the picker, and mark a song
    not found (``notFound``), whose served line links to its search hits: a search each would cost
    every page a moment per song."""
    for song, card in zip(library, songs, strict=True):
        if card["review"]:
            choices = review_choices(conn, song)
            if choices:
                card["candidates"] = choices
        elif song.match_decision == "not_found" and card["status"] != "ignored" and not card["lacuerda"]:
            card["notFound"] = True  # not for the sheet picked on LaCuerda, still to come: that is the song's


_TAB_KINDS = {"chords": "Chords", "tabs": "Tabs", "guitar-pro": "Guitar Pro", "power": "Power Tab"}


def _tab_counts(counts: Any) -> str:
    """"Chords ×2 · Tabs ×1": a UG song's tabs per type, best type first, as ``caracole search`` counts them."""
    return " · ".join(f"{_TAB_KINDS.get(kind, kind)} ×{n}" for kind, n in counts.items())


def write_library_page(library_dir: Path, html: str) -> Path:
    """Write ``index.html`` in the library folder, atomically, and return its path."""
    path = library_dir / PAGE_NAME
    write_atomic(path, html.encode("utf-8"))
    return path


# --- the data ---------------------------------------------------------------------------


def _musescore_links(conn: sqlite3.Connection, song: Song, overrides: Overrides) -> list[dict[str, str]]:
    """The song's MuseScore pages, each a possible match: the sitemaps give titles only."""
    if song.status == "ignored" or song.key in overrides.ignore:
        return []
    return [{"label": f"{p.path.removeprefix('song/')} (possible match)", "href": p.url, "source": "musescore"}
            for p in song_pages(conn, song)]


_YOUTUBE_NOTES = {
    QUEUED: "No human sheet yet: caracole takes the audio from YouTube next",
    BLOCKED: "No human sheet yet: YouTube is blocking caracole for now, so its audio waits",
    DOWNLOADED: "Audio from YouTube: auto-chords works out the chords next",
    CHORDS: "Auto sheet from YouTube audio",
    MISSING: "Nothing on YouTube fits: see the to-do page",
    UNUSABLE: "The video under [youtube] can't be downloaded: see the to-do page",
}


def _lacuerda_pick(song: Song, overrides: Overrides, status: str) -> dict[str, str] | None:
    """The sheet you picked on LaCuerda (``[lacuerda]``), for a wanted song's line to say that tonight's run
    gets it; None once LaCuerda was asked for it, and for any other song."""
    pick = overrides.lacuerda.get(song.key)
    if pick is None or status != "wanted" or song.lacuerda_checked_at is not None:
        return None
    return {"label": "the sheet you picked on LaCuerda", "href": pick.url}


def _youtube_note(state: SongState | None) -> dict[str, Any] | None:
    """What a song's line says of it on the YouTube route, and the video its audio came from."""
    if state is None or state.state not in _YOUTUBE_NOTES:
        return None
    video = state.video if state.state in (DOWNLOADED, CHORDS) else None
    name = f"{video.title} ({video.channel})" if video and video.title and video.channel else None
    return {"text": _YOUTUBE_NOTES[state.state],
            "video": {"label": name or (video.title or video.url), "href": video.url} if video else None}


def _song(library_dir: Path, song: Song, overrides: Overrides, key: SongKey | None,
          guitar_pro: list[dict[str, str]], for_buying: bool, sources: dict[str, str],
          musescore: list[dict[str, str]], youtube: dict[str, Any] | None = None, *,
          origins: dict[str, str] | None = None, exports: Mapping[str, str] | None = None,
          transpose: int = 0) -> dict[str, Any]:
    """One song's data; ``for_buying`` when the to-do page's buy list holds it (``todo.songs_to_buy``),
    ``sources`` the site each file caracole downloaded for it came from, by name, ``musescore``
    the song's MuseScore pages, and ``youtube`` where the song stands on the YouTube route.

    ``key`` and ``key_source`` are the song's key and where it came from, as in its info.json.
    ``origins`` is where each of its kept files came from (``icons.kept_sources``): each file gets
    its ``source``, and the song its primary file's. ``exports``: the PDFs caracole made of its sheet in
    other versions, by file name, each with its version's label (``_exports``); ``transpose``, how many semitones
    its PDF is moved by (``render.pdf_transpose``).
    """
    title = clean_title(song.title)
    status = "ignored" if song.key in overrides.ignore else song.status
    names = _file_names(song_dir(library_dir, song))
    has_sheet = any(n in names for n in _HUMAN_SHEETS + _AUTO_SHEETS)
    links: list[dict[str, str]] = []
    buy: list[dict[str, str]] = []
    if not has_sheet and status != "ignored":
        found = search_links(song.artist, song.title)
        links = [{"label": "Chordify", "href": found["chordify"]},
                 {"label": "YouTube", "href": found["youtube"], "source": "youtube"}]
        if for_buying:  # not while caracole may still find a sheet, nor once you have the audio
            buy = [{"label": label, "href": found[name]}
                   for label, name in (("Bandcamp", "bandcamp"), ("Qobuz", "qobuz"), ("iTunes", "itunes"))]
    files = _files(library_dir, song, names, sources, origins or {}, exports or {})
    return {
        "id": song.id,
        "artist": song.artist,
        "artists": song.artists or [song.artist],
        "title": title,
        "display": song.display,
        "status": status,
        "review": bool(song.review) and status != "ignored",
        "added": song.added_at,
        "key": key.key if key else None,
        "key_source": key.source if key else None,
        "transpose": transpose,  # what its PDF is moved by (render.pdf_transpose): [version] wins over [transpose]
        "lyrics": song.lyrics_status,
        "auto": not any(n in names for n in _HUMAN_SHEETS) and any(n in names for n in _AUTO_SHEETS),
        "files": files,
        "source": next((f["source"] for f in files if f["primary"]), None),  # where its sheet came from
        "guitarPro": guitar_pro,
        "museScore": musescore,
        "links": links,
        "buy": buy,
        "youtube": youtube if status != "ignored" else None,
        "lacuerda": _lacuerda_pick(song, overrides, status),
        # Its identity key (normalize.identity_key): the served search puts it, and the sites' rows of its artist and
        # of it, under one header by the artist's part, as /api/search keys its rows.
        "identity": song.key,
        "sortArtist": _sort_key(song.artist),
        "sortTitle": _sort_key(title),
        "artistLetter": _letter(_sort_key(song.artist)),
        "titleLetter": _letter(_sort_key(title)),
        # Only the key's mode, so that "minor" finds every minor song: the script finds a typed key
        # ("a minor", "f#m") by its pitch class instead, which a substring of "a minor" can't do.
        "search": _haystack([song.artist, *song.artists, title, song.display,
                             *([key_name(key.key).rpartition(" ")[2]] if key else [])]),
        **({"initials": initials} if (initials := _initials(title)) else {}),
    }


def _file_names(folder: Path) -> set[str]:
    try:
        return {p.name for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")}
    except OSError:  # no folder yet
        return set()


def _files(library_dir: Path, song: Song, names: set[str], sources: dict[str, str],
           origins: dict[str, str] | None = None, exports: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Links to the kept files that exist, as paths relative to index.html, percent-encoded. The
    primary one is the sheet's PDF, else its text: never a score, whatever its format. Each says
    where it came from (``icons.source_of``). ``exports`` (``_exports``) are listed after the sheets' viewers
    and PDFs, by their labels, those still in the folder alone, each with its ``version`` ("G Dorian, capo 0"),
    which its line's "⋯" lists it by, under Versions."""
    guitar = sorted((int(m.group(1)), n) for n in names if (m := _GUITAR.fullmatch(n)))
    scores = sorted((int(m.group(1)), SCORE_EXTENSIONS.index(m.group(2)), n)
                    for n in names if (m := _SCORE.fullmatch(n)) and m.group(2) in SCORE_EXTENSIONS)
    made = sorted((label, n) for n, label in (exports or {}).items() if n in names)
    labels = {n: f"Sheet PDF, {label}" for label, n in made}
    ordered = ([n for n in _SHEET_PAGES if n in names] + [n for _, n in made]
               + [n for n in _FIRST if n in names and n not in _SHEET_PAGES]
               + [n for _, n in guitar] + [n for _, _, n in scores] + [n for n in _LAST if n in names])
    folder = song_dir(library_dir, song).relative_to(library_dir)
    base = "/".join(quote(part, safe="") for part in folder.parts)
    primary = next((n for n in ordered if n in ("sheet.html", "sheet (auto).html", "sheet.pdf", "sheet (auto).pdf")),
                   None) or next(
        (n for n in ordered if n in ("sheet.txt", "sheet (auto).txt")), None)
    versions = {n: label for label, n in made}
    return [
        {"name": n, "label": labels.get(n) or _label(n, sources.get(n)), "href": f"{base}/{quote(n, safe='')}",
         "primary": n == primary, "source": source_of(n, origins or {}),
         **({"version": versions[n]} if n in versions else {})}
        for n in ordered
    ]


def _exports(conn: sqlite3.Connection) -> dict[int, dict[str, str]]:
    """The PDFs caracole made of each song's sheet in other versions (render.py ``render_version``, recorded in kv
    ``render:export:<song id>``), as {song id: {file name: its version's label, "G Dorian, capo 0"}}."""
    from caracole.render import EXPORT_KV

    found: dict[int, dict[str, str]] = {}
    rows = conn.execute("SELECT key, value FROM kv WHERE substr(key, 1, ?) = ?", (len(EXPORT_KV), EXPORT_KV))
    for key, value in rows:
        number = key[len(EXPORT_KV):]
        try:
            record = json.loads(value)
        except ValueError:
            continue
        if not (number.isascii() and number.isdigit()) or not isinstance(record, dict):
            continue
        for label, entry in record.items():
            name = entry.get("pdf") if isinstance(entry, dict) else None
            if isinstance(name, str) and is_export(name):
                found.setdefault(int(number), {})[name] = label
    return found


def _label(name: str, source: str | None = None) -> str:
    m = _GUITAR.fullmatch(name)
    if m:
        kind = "Power Tab" if m.group(2).lower() == ".ptb" else "Guitar Pro"
        return f"{kind} {m.group(1)}" + (f" · {source}" if source else "")
    m = _SCORE.fullmatch(name)
    if m:
        return f"Score {m.group(1)} ({_SCORE_FORMATS[m.group(2)]})"
    return _LABELS[name]


def _downloaded(conn: sqlite3.Connection) -> dict[int, dict[str, str]]:
    """The files caracole downloaded from gtptabs.com, as {song id: {file name: "gtptabs.com"}}."""
    found: dict[int, dict[str, str]] = {}
    rows = conn.execute(
        "SELECT f.song_id, f.name FROM files f JOIN versions v ON v.id = f.version_id WHERE v.provider = 'gtptabs'"
    )
    for song_id, name in rows:
        found.setdefault(song_id, {})[name] = "gtptabs.com"
    return found


def _guitar_pro_pages(conn: sqlite3.Connection) -> dict[int, list[dict[str, str]]]:
    """Guitar Pro and Power Tab picks still to download by hand (no file yet), by song."""
    rows = conn.execute(
        "SELECT v.* FROM versions v WHERE v.kind IN ('guitar-pro', 'power') AND v.pick_rank IS NOT NULL "
        "AND v.gone = 0 AND NOT EXISTS (SELECT 1 FROM files f WHERE f.version_id = v.id) "
        "ORDER BY v.song_id, v.pick_rank"
    )
    pages: dict[int, list[dict[str, str]]] = {}
    for v in rows:
        url = (v["url"] or "").strip()
        if not url.startswith(("https://", "http://")):
            continue
        label = f" ({v['label']})" if v["label"] else ""
        votes = f"{v['votes']} vote{'s' if v['votes'] != 1 else ''}"
        text = f"{_KIND_NAMES[v['kind']]} ver {v['version']}{label} · {v['rating']:.1f}★ · {votes}"
        pages.setdefault(v["song_id"], []).append({"label": text, "href": url, "source": v["provider"]})
    return pages


def _sort_key(text: str) -> str:
    """Sorts "The Beatles" under B and 宋冬野 under S (by pinyin)."""
    return slug_key(romanize(text)) or fold(text)


def _letter(sort_key: str) -> str:
    """The A-Z strip's letter for a sort key; "#" for a digit or anything else."""
    first = sort_key[:1]
    return first.upper() if "a" <= first <= "z" else "#"


def _initials(title: str) -> str:
    """A title's initials, "wywh" for Wish You Were Here (斑马斑马's by pinyin, "bmbm"): typed whole in the
    search box, they find it. None for a title of one word."""
    words = _WORD.findall(_APOSTROPHES.sub("", fold(romanize(title) if has_han(title) else title)))
    return "".join(w[0] for w in words) if len(words) > 1 else ""


def _haystack(texts: list[str]) -> str:
    """What the page's filter looks in: folded text, the same without punctuation, and pinyin."""
    parts: dict[str, None] = {}
    for text in texts:
        forms = [fold(text)]
        if has_han(text):
            forms.append(fold(romanize(text)))
        for form in forms:
            parts.setdefault(form, None)
            parts.setdefault(_PUNCTUATION.sub("", form), None)
    return " | ".join(p for p in parts if p)


# --- the page ---------------------------------------------------------------------------

# index.html's one stylesheet and one script: the files of library_assets/, in this order (what each one
# is: its __init__.py). BASE_STYLE, PICKER_STYLE, ROWS_STYLE and ROWS_SCRIPT, the ones caracole serve's own
# pages share, are importable from here too.
STYLESHEETS = ("base.css", "picker.css", "library.css", "rows.css", "library-screens.css", "songbooks.css")
SCRIPTS = ("rows.js", "library.js", "select.js", "songbooks.js", "drawn.js")
_SCRIPT = read_asset("library.js")  # the page's own
_PAGE_STYLE = "".join(read_asset(name) for name in STYLESHEETS)
_PAGE_SCRIPT = "".join(read_asset(name) for name in SCRIPTS)


# default-src 'none' blocks every fetch the page could make; links still navigate. Forms may post
# only to caracole serve, and only on the page it serves. Images come from data: URIs alone: the
# sites' icons, inlined (icons.py).
_CSP = (
    f"default-src 'none'; script-src {sha256_source(_PAGE_SCRIPT)}; style-src {sha256_source(_PAGE_STYLE)}; "
    "img-src data:; base-uri 'none'; form-action __FORMS__"
)

# The page's skeleton, as templates whose __BLANKS__ build_library_page fills in: head.html and body.html;
# request.html, the form caracole serve adds under the search's results (a song for wanted.txt, written
# as `caracole add` writes it; the script fills it in from what was searched, and without the script it
# posts as a form); requested.html, what caracole serve adds under the bar (the songs just requested,
# each a line with its request line, and the requests, a short list in a corner).
TEMPLATES = ("head.html", "body.html", "request.html", "requested.html")
_HEAD, _BODY, _REQUEST, _REQUESTED = (read_asset(name) for name in TEMPLATES)


def _nav(controls: WebControls | None) -> str:
    """The masthead's links: caracole serve's requests; on the file, none, and no nav."""
    if controls is None:
        return ""
    n = f'<span class="n">{controls.active}</span>' if controls.active else ""
    return f'<nav class="links" aria-label="Pages"><a class="navlink" href="/jobs">Requests{n}</a></nav>'


def _request_form(controls: WebControls | None) -> str:
    if controls is None:
        return ""
    return _REQUEST.replace("__CSRF__", html_text.escape(controls.csrf, quote=True))


def _requested(controls: WebControls | None) -> str:
    return _REQUESTED if controls is not None else ""
