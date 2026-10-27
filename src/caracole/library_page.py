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
from wanted.txt, which every synced device can write, so the page's script builds every
element with ``createElement`` and ``textContent``, never ``innerHTML``, and
the JSON has each ``<`` written as ``\\u003c``: escaping only ``</`` would
still let a ``<!--`` change how the HTML tokenizer reads the block.

Each song carries a search string: its artist, title and display name folded
(accents stripped, lowercase), the same without punctuation ("acdc"), and
pinyin for Chinese ("ban ma ban ma", "banma"), and its title's initials
("wywh", typed whole). The page folds what you type the same way, so "musica"
finds "Música" and "ban ma" finds 斑马，斑马.
Of a song's key, the string holds only the mode ("minor"): the script reads a
key typed in the box ("a minor", "f#m") and compares it, as the Filter panel's
Key does, by the tonic's pitch class and the mode, so "Gb minor" finds "F#
minor".

The songs are dense lines (``resultRow``'s ``dense`` form, ROWS_SCRIPT's), a
song a line on a laptop, about thirty to its screen, two lines a song on a
phone. By artist, the order the page opens in, they are grouped under their
artist's name, artists A to Z, each group's header saying how many of their
songs you have, whatever the search or a filter leaves out ("Soda Stereo · you
have 2"); by title or by when they came,
they stand alone, each with its artist. A line holds the song's title, which
opens its sheet (its viewer, else its PDF, else its text), its status when it
needs something (Wanted, Needs review, Not found, Ignored: a found song says
nothing), what it holds, a glyph each (its sheet, a Guitar Pro file or a tab, a
harmonica tab, its lyrics, a score: rows.js ``glyph``, read from its files and
``instruments``), its key as a chip and its main action: Open, or, served, Fetch
now or Pick the match. Everything else a song has is under its chevron, which
unfolds it in place as a card (library_assets/card.js): its facts (the key in words
and where it came from, the transposition, the lyrics, when it came), its
review's picker, where its audio comes from; a tile for each thing it holds, read
from its ``files``: its sheet, its Guitar Pro file or text tab, its harmonica tab,
its lyrics, a score you filed, each with its formats as downloads (a harmonica tab with its
page beside it, ``harmonicaPage``: render.py's ``harmonica-N.html``, opens that page, its text a download) (the sheet's PDF
exports among them, each file's ``version``) and its versions per source as chips,
which open a drawer: Ultimate Guitar's (``versions``: those kept, the one and those
beside it, sheet_versions.py's, each opening its viewer page, and those not kept
counted), LaCuerda's (``lacuerdaVersions``), the auto sheet beside a human one
(``autoSheet``), a source's files; its progressions, its MuseScore pages, its search
and buy links, Add to a songbook… (the Select mode, the song picked) and, served,
Fetch again and Use LaCuerda's sheet (``lacuerdaSheet``, or the search's LaCuerda
row of it: each the ``POST /lookup`` the lookup page sends for the song) and
Remove. Served, a Guitar Pro file caracole serve shows in the browser (its
``guitarPage``, ``guitar_pages``) opens there from its tile and its drawer
(web/guitar_routes.py); without alphaTab there (``WebControls.guitar``), a note says they are downloads. An
artist's name, marked with a funnel (``artistFilter``, ROWS_SCRIPT's), shows that
artist's songs alone. An A-Z strip jumps to the first group (or line) of a letter
once more than 40 songs show. On a phone the header is short (the numbers beside
the title, then one row of buttons and menus that scrolls sideways), so the first
song starts on the first screen; the bar stays at the top, with an edge once the
page scrolls under it. The address remembers the search, the filters, the sort
and the key.

On a touch screen (``pointer: coarse``) every control is a thumb's target, 44
px each way at the least: buttons, folds, chips, menus, letters, a line's
button and chevron and an artist's name; a mouse keeps the compact sizes. Fields,
menus and the Select boxes have the ``--control-edge`` colour, 3:1 or more
against every background (WCAG 1.4.11); boxes and dividers keep the soft
``--border``. ``BASE_STYLE`` and ``PICKER_STYLE`` carry both to
the pages caracole serve writes itself (web/pages.py, web/lookup_page.py).

Each file and link, and a site's song's line, shows where it came from (icons.py): the site's own
icon, inlined in the data as a ``data:`` URI (the CSP allows images from
``data:`` alone), else the site's lettered badge, or a glyph for the audio
model and the inbox; each is named "from Ultimate Guitar" for a screen reader.
A song of yours says on its line what it holds instead. An auto sheet made from the audio caracole took from
YouTube shows YouTube's on its files (``icons.kept_sources``), and its line's panel the video.

The seam for lists the page doesn't make itself (the results of caracole
serve's lookup page, web/lookup_page.py, which runs ``ROWS_SCRIPT`` and has
``ROWS_STYLE`` as this page does, and gets each song's files from
``result_cards``): ``window.caracole.resultRow(result)`` returns a row
element, to put in a ``<div class="rows">``, or with ``dense``, a line as a
song's is (``article.line``: ``.line-title``, ``.line-status``, ``.line-holds`` or
``.line-sources``, ``.line-key``, ``.line-action``, ``.line-more``), to put in a ``<div
class="lines">``. ``result`` is a plain object, every field optional:

- ``title``, ``artist``: text; ``onArtist``, a function, makes the artist a button that
  shows it filters (a funnel after the name), as a group's name is; a line shows its
  artist only where no artist's group holds it;
- ``href``: what the title opens (the song's sheet, as its button does), the same way as
  ``action``'s link; out of the Tab order, since the button says what it opens;
- ``source``: a key of the data's ``icons`` (``icons.SOURCES``: "ug", "lacuerda"…), or, for
  a line, ``sources``, several, each marked once; or, for a song of yours, ``holds``, what it
  holds (rows.js ``HOLDS``: "sheet", "auto", "ukulele", "guitar", "tab", "harmonica", "lyrics",
  "score"), a glyph each named for a screen reader, in place of any mark;
- ``key`` ("A minor"), and ``keyText``, what a screen reader hears for it;
- ``status``, which its ``data-status`` gets; ``badges``: ``[{kind, text}]``,
  ``kind`` a badge class (found, wanted, review, auto…); ``facts``: a line of text;
- ``action``: the main control, a Node, or ``{label, href, source}``: an http(s)
  link opens in a new tab, any other address stays relative or goes nowhere;
- ``more``: what its "⋯" button (a line's chevron) shows, Nodes or
  ``{heading, links: [{label, href, source}]}``.

``window.caracole.sourceMark(key)`` gives a source's mark alone, and
``window.caracole.icons`` the icons' data. ``ROWS_SCRIPT`` also draws the
offline indexes' hits, as ``/api/search`` and ``/api/artist`` give them: for
this page's search, a song of the sites as a dense line (``indexLine``: one
line however many sites have it, each site's mark and counts on it, its
identity its ``data-hit``) and MuseScore's pages (``titleLine``); for the
lookup page, rows (``ugHit``, ``artistHit``, ``siteHit``, ``siteArtist`` and
``siteArtistSongs``, LaCuerda's artists and their songs); and for both what a
search says beside its results: for a query that found nothing, the closest
artists' names the indexes have (``didYouMean``, from ``suggest``: each one's
Their songs), then one card (``nothingFound``: the request by name first, Ask
LaCuerda (1 request) for a name under a letter LaCuerda's listings aren't read
to yet, where caracole looked as chips, ``lookedChips`` from ``looked``, and
"Why can't caracole find it?" folded, from ``unseen``); under results, the chips
in one muted line when a site wasn't searched whole (``lookedLine``). With them
``readArtistPage``, which asks the server to read an artist's page, by its slug
or by a name, and ``readOutcome``, what LaCuerda answered a read that left
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
query alone), a song a
line, keyed by its identity key's two parts (the rows' ``artist_key`` and
``title_key``, an artist's ``group_key``; a song of yours by its ``identity``),
so that Ultimate Guitar's, LaCuerda's and gtptabs.com's rows of one song are
one line, and a row of a song of yours is your song's line, its artist's rows
under your artist's header. An artist the query names shows their most tabbed
songs, then "+ 57 more by Estopa", the rest in the group fifty at a time
(``/api/artist``); a LaCuerda artist the rest the index holds of theirs, or the
offer to read their page (``POST /lacuerda/artist``), and a query LaCuerda's
index has no artist by while the listing of its letter isn't read whole has Ask
LaCuerda, under the groups. MuseScore's pages, titles alone, come last under a
header of their own, and harptabs.com's harmonica tabs after them (``titleLine``, by
each one's ``source``). A row for one instrument says which (``instrumentBadges``:
Ukulele for UG's Ukulele Chords, Harmonica for harptabs.com's, Score for MuseScore's;
a song's card's ``instruments``, ``instruments_of``), and nothing is filtered by one. Under them, where caracole looked: chips in one muted line
(UG ✓, LaCuerda: up to C, MuseScore blocked…), each one's detail its tooltip, or,
for a query that found nothing, "Did you mean" (Their songs opens that artist's
group, first, from ``/api/artist``) and one card, whose Request “…” by name
opens the request form. A line's Get it (``POST /lookup``) shows its request's
line in the line itself. Enter moves the focus to the first result and asks for no song;
the one request it may send is LaCuerda's search, at once and by hand, as its button
sends it, when ``/api/search``'s ``lacuerda_search`` says ``auto`` or ``button``
(rows.js ``lacuerdaSearcher``). A wanted song whose sheet you picked on LaCuerda says that tonight's
run gets it (``lacuerda``), and isn't a song not found (``notFound``). The
request form sits under the results, filled in from the query.

``caracole serve`` serves the same page with ``controls`` (``WebControls``): the
search of the sites as you type, a form to request a song, a "Fetch now" button on each wanted song, a "Remove"
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

Remove stays on the page: one tap and the song's own line says "Removing in 5 s
· Undo", the focus on Undo, with what goes in one sentence under it (the
server's answer to the question, ``removal.brief``: caracole's files of the
song, its record, its wanted.txt line; never Music/). Nothing else is sent for
those five seconds, and Undo stops it ("Not removed", the focus back on
Remove); then the page posts the removal with the song's key, and the line
follows it ("Removing…", "Removing from caracole…", then "Removed"), as tall as
it was. The song's line is then a ``gone`` one, its name alone, as tall as it was and
its request line where it was, until the page is loaded again. Without JavaScript,
Remove's question is a page of the server's; Remove it, and Keep it, come back
to this page as it was left (Remove sends the address after # along, ``back``),
at the song's line: ``song=ID`` in the address, which the script scrolls to and
focuses, then drops.

**Two tabs.** Library, all of the above, and Songbooks (``#tab=songbooks`` in
the address, ``book=NAME`` the songbook open; library_assets/songbooks.js draws
it from the data's ``songbooks``, songbook_section.py's): on the left the
songbooks as lines, each with how many songs, how many still without a sheet and
when caracole last made its files, and "+ New songbook" (Select, on the
library); on the right, side by side from 900 px and one at a time on a phone,
the songbook opened as a set list, each song with where the songbook plays it
(``songbook.plays_in``) and a guitar after its title when caracole keeps a Guitar
Pro file for it (its Guitar Pro page served, else the file), and its files: the PDF, the phone
page, ChordPro. The file on disk shows it read-only, with the ``caracole songbook`` commands that
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
the song plays it, and the named progressions a section plays within it by their name's key), and the page
the catalogue's names by key (``catalogue``). A song's "⋯" lists them,
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

**The Android app's copy.** The file on disk is where caracole's Android app starts (caracole serve's
``/api/offline``, web/offline_routes.py): the pages write it with its SHA-256 and length recorded
(``write_library_page``, kv ``library_page:written``), and the server sends it only while it is still
those bytes (``pages_written``), with the policy its ``<meta>`` tag holds (``page_csp``); the app copies
every file it links to (``linked_files``).
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
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

from caracole.config import Config
from caracole.db import kv_get_json, kv_set_json
from caracole.download_names import download_name
from caracole.icons import kept_sources, page_icons, source_of
from caracole.inbox import SCORE_EXTENSIONS, guitar_files, harmonica_page
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
from caracole.songs import HUMAN_SHEET, Song, is_export, list_songs
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

if TYPE_CHECKING:
    from caracole.sheet_versions import SheetVersion

# Importable from here too: the style and script caracole serve's own pages share with this one (BASE_STYLE,
# PICKER_STYLE, ROWS_STYLE, ROWS_SCRIPT: library_assets/), and the Songbooks tab's data (songbook_section.py).

PAGE_NAME = "index.html"
WRITTEN_KEY = "library_page:written"  # kv: the SHA-256 and the length of the index.html last written

# Kept files, in the order a song's line lists them: the sheets' viewers and PDFs, then the song's exports (the
# sheet's PDF in other versions, by their versions), the rest of the first group; guitar-N.* goes between the two
# groups.
_SHEET_PAGES = ("sheet.html", "sheet.pdf", "sheet (auto).html", "sheet (auto).pdf")
_FIRST = (*_SHEET_PAGES, "sheet.txt", "sheet.cho", "lyrics.txt", "lyrics.lrc")
_LAST = ("tab.txt", "sheet (auto).txt", "sheet (auto).cho", "info.json")
_GUITAR = re.compile(r"guitar-(\d+)(\.[A-Za-z0-9]+)")
# Scores filed from _inbox/ (inbox.py), after the guitar files, in SCORE_EXTENSIONS' order.
_SCORE = re.compile(r"score-(\d+)(\.[a-z]+)")
# Harmonica tabs kept from harptabs.com (harptabs_fetch.py), after the scores.
_HARMONICA = re.compile(r"harmonica-(\d+)\.txt")
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
    users get carries none. ``guitar``: whether it shows Guitar Pro files in the browser (it has alphaTab:
    web/alphatab.py), so a song's Guitar Pro files offer Open in the browser beside Download.
    """

    csrf: str
    busy: frozenset[int] = frozenset()
    active: int = 0
    held: frozenset[int] = frozenset()
    removing: frozenset[int] = frozenset()
    jobs: tuple[dict[str, Any], ...] = ()
    timers: Mapping[str, int] | None = None
    guitar: bool = False


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
                          "removing": sorted(controls.removing), "jobs": list(controls.jobs),
                          "guitar": controls.guitar}
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

    browsable = guitar_pages(conn)
    sources = _downloaded(conn)
    origins = kept_sources(conn)
    ukulele = ukulele_sheets(conn)
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
    asked = None if songs is None else {s.id for s in songs}  # a card or a few: their rows alone
    met = _lacuerda_versions(conn, asked)
    ug = _ug_versions(conn, cfg, overrides, library)
    cards = [_song(cfg.library_dir, s, overrides, keys.get(s.id), s.id in to_buy,
                   sources.get(s.id, {}), _musescore_links(conn, s, overrides) if musescore else [],
                   _youtube_note(youtube.get(s.id)), origins=origins.get(s.id, {}), exports=exports.get(s.id, {}),
                   transpose=pdf_transpose(conn, overrides, s), lacuerda=met.get(s.id, []),
                   versions=ug.get(s.id), guitar=browsable.get(s.id), ukulele=s.id in ukulele)
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
    browsable = guitar_pages(conn)
    ukulele = ukulele_sheets(conn)
    cards = {}
    for s in songs:
        names = _file_names(song_dir(cfg.library_dir, s))
        files = _files(cfg.library_dir, s, names, {}, origins.get(s.id, {}),
                       exports.get(s.id, {}), browsable.get(s.id), ukulele=s.id in ukulele)
        key = song_key(conn, cfg.library_dir, s)
        cards[s.id] = {"links": files, "source": next((f["source"] for f in files if f["primary"]), None),
                       "key": key.key if key else None, "instruments": instruments_of(names, ukulele=s.id in ukulele)}
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


_TAB_KINDS = {"chords": "Chords", "tabs": "Tabs", "ukulele": "Ukulele Chords"}


def _tab_counts(counts: Any) -> str:
    """"Chords ×2 · Tabs ×1": a UG song's tabs per type, best type first, as ``caracole search`` counts them."""
    return " · ".join(f"{_TAB_KINDS.get(kind, kind)} ×{n}" for kind, n in counts.items())


def write_library_page(library_dir: Path, html: str, conn: sqlite3.Connection | None = None) -> Path:
    """Write ``index.html`` in the library folder, atomically, and return its path; with ``conn``, record its
    SHA-256 and length (kv ``library_page:written``), as ``todo.write_pages`` does, so that caracole serve sends
    it to the Android app only while it is still those bytes (``pages_written``)."""
    path = library_dir / PAGE_NAME
    data = html.encode("utf-8")
    sha = write_atomic(path, data)
    if conn is not None:
        kv_set_json(conn, WRITTEN_KEY, {"sha256": sha, "size": len(data)})
    return path


def pages_written(conn: sqlite3.Connection, library_dir: Path, parts: tuple[str, ...]) -> list[tuple[str, int]]:
    """The record of the library page a server is asked for, by its path's parts in the library: the SHA-256 and
    the length of the index.html caracole last wrote at the library's top (``write_library_page``), [] for any
    other path or none recorded (one written by an older caracole: the next command that writes the pages
    records it). As ``songbook.pages_written`` does for a songbook's page: anyone with a synced device can put a
    page in the library, whose script would run as the server's. ``library_dir`` goes unused: the lookups of the
    server's pages all take the same arguments."""
    from caracole.render import written_entry

    if parts != (PAGE_NAME,):
        return []
    written = written_entry(kv_get_json(conn, WRITTEN_KEY))
    return [] if written is None else [written]


# What a server says for a library page it won't send (web/offline_routes.py): the Android app asks for it first.
PAGE_REFUSED = ("This library page isn't the one caracole last wrote here (it was changed on a synced device, say, "
                "or caracole has no record of it yet), so the server won't send it: caracole todo writes it again.")


def page_csp(page: bytes) -> str:
    """The Content-Security-Policy header a server sends with ``page``, an index.html caracole wrote: the page's own
    policy, as its ``<meta>`` tag holds it (its script and stylesheet by their hashes, images from ``data:``, no
    form to send, nothing to connect to), which the header repeats. No sandbox, as caracole serve's own library
    page has none: its script needs no origin of its own, and its links to the sites open in a new tab, and its
    Guitar Pro files download, which a sandbox would stop. A page whose policy can't be read gets a sandbox that
    runs and loads nothing.

    Serve only a page still as caracole wrote it (``pages_written``, ``files.read_written_page``)."""
    found = _META_POLICY.search(page)
    try:
        policy = html_text.unescape(found.group(1).decode("utf-8")) if found else ""
    except UnicodeDecodeError:
        policy = ""
    return policy if _HEADER_TEXT.fullmatch(policy) else _NOTHING


def linked_files(page: bytes) -> list[str]:
    """The files of the library ``page`` (an index.html caracole wrote) links to, as paths in the library, decoded
    ("Soda Stereo/De Música Ligera/sheet.pdf"), each once, in the page's order: every relative link (``href``) in
    its data, its songs' files, their kept versions' pages and their harmonica tabs' pages, its songbooks' files and
    their songs' sheets and Guitar Pro files. A link to a site, or with a query or a fragment, is none; a page whose data can't be read
    links none."""
    from urllib.parse import unquote, urlsplit

    found = _DATA.search(page)
    try:
        data = json.loads(found.group(1)) if found else None
    except (ValueError, RecursionError):  # not UTF-8, not JSON, or too deep
        return []
    paths: dict[str, None] = {}
    stack = [data]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            href = node.get("href")
            if isinstance(href, str):
                try:
                    link = urlsplit(href)
                    path = unquote(link.path, errors="strict")
                except (UnicodeDecodeError, ValueError):
                    path = ""
                if path and not (link.scheme or link.netloc or link.query or link.fragment or path.startswith("/")):
                    paths[path] = None
            stack.extend(reversed([value for key, value in node.items() if key != "href"]))
        elif isinstance(node, list):
            stack.extend(reversed(node))
    return list(paths)


# The page's own policy, as head.html writes it; what a header may hold (no line break); the header for a page
# whose policy can't be read: a sandbox that runs and loads nothing (as viewer.viewer_csp's). And its data.
_META_POLICY = re.compile(rb'<meta http-equiv="Content-Security-Policy" content="([^"<>]*)">')
_HEADER_TEXT = re.compile(r"[ -~]+")
_NOTHING = "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'"
_DATA = re.compile(rb'<script type="application/json" id="songs">(.*?)</script>', re.S)


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


@dataclass(frozen=True)
class _UgVersions:
    """A song's Ultimate Guitar versions as the page counts them (``_ug_versions``): ``listed``, every one
    ``sheet_versions.in_library`` lists, in rank order, gone ones last; ``rest``, how many a keep may still keep
    (``sheet_versions.may_keep``); ``keep_more``, how many of those one press of Fetch them keeps (``caracole
    versions --keep-more``, a lookup: its ``lookup_requests`` at most); ``pinned``, whether a ``[pin]`` chooses its
    sheet (``sheet_versions.sheet_pins``)."""

    listed: list[SheetVersion]
    rest: int
    keep_more: int
    pinned: bool


def _ug_versions(conn: sqlite3.Connection, cfg: Config, overrides: Overrides,
                 songs: list[Song]) -> dict[int, _UgVersions]:
    """The UG versions of each of ``songs`` that has some listed for its sheet (``sheet_versions.in_library_of``: as
    its viewer lists them, read for every song at once), by song id, and ``may_keep``'s count of those a keep may
    still keep. A song with none recorded (or found under an earlier match alone) is none."""
    from caracole.sheet_versions import PROVIDER, in_library_of, may_keep, sheet_pins

    listings = in_library_of(conn, [s.id for s in songs], cfg.rank)
    budget = cfg.provider(PROVIDER).lookup_requests
    found: dict[int, _UgVersions] = {}
    for song in songs:
        listed = listings.get(song.id)
        if listed is None:
            continue
        rest = len(may_keep(conn, song.id, listed, overrides.block))
        found[song.id] = _UgVersions(listed=listed, rest=rest, keep_more=min(rest, budget),
                                     pinned=bool(sheet_pins(conn, song.id, overrides.pin.get(song.key, ()))))
    return found


def _versions_data(versions: _UgVersions | None, names: set[str], base: str) -> dict[str, Any] | None:
    """A song's Ultimate Guitar versions as its card shows them (``_ug_versions``), for library.js alone:

    - ``list``, the kept ones (the one and those kept beside it) in rank order, as ``as_data`` gives each, with the
      link that opens it (its viewer page, else its text while render hasn't written the page; the one, else its
      PDF, as its title opens it), where it came from (``source``, Ultimate Guitar), and what its lyric score was,
      ``coverage`` and ``complete`` (None for one never scored);
    - ``total``, the chords versions UG still has (neither gone nor found under an earlier match);
    - ``rest``, how many of those a keep may still keep, and ``keepMore``, how many one press of Fetch them keeps;
    - ``pinned``, whether a ``[pin]`` chooses its sheet (Back to caracole's pick).

    None for a song with no UG version recorded for its sheet. Not ``as_data``'s shape, which the viewer pages'
    ``versions`` is (every version, gone ones too): the library page lists what its folder holds, and counts the
    rest."""
    from caracole.sheet_versions import as_data, version_names

    if versions is None:
        return None
    data = as_data(versions.listed, len(versions.listed))
    listed = []
    for version, entry in zip(versions.listed, data["list"], strict=True):
        if not entry["kept"]:
            continue
        opens = ((entry["page"], "sheet.txt", "sheet.pdf") if entry["chosen"]
                 else (entry["page"], version_names(entry["tab"])[0]))
        name = next((n for n in opens if n in names), None)
        if name is not None:
            listed.append({**entry, "href": f"{base}/{quote(name, safe='')}", "source": "ug",
                           "complete": version.complete, "coverage": version.coverage})
    return {"total": sum(not v.gone for v in versions.listed), "list": listed, "rest": versions.rest,
            "keepMore": versions.keep_more, "pinned": versions.pinned}


def _lacuerda_versions(conn: sqlite3.Connection, ids: set[int] | None = None) -> dict[int, list[dict[str, Any]]]:
    """The LaCuerda sheets caracole met for each song (lacuerda_fetch.py records each, kept or not) that LaCuerda
    still has, the one that covers the most of its lyrics first, by song id: each its page (``href``), its
    ``coverage`` (None for one never scored), and whether it is the song's kept sheet (``sheet``). ``ids``: of these
    songs alone, else of every song."""
    only = "" if ids is None else " AND v.song_id IN (SELECT value FROM json_each(?))"
    rows = conn.execute(
        "SELECT v.song_id, v.url, v.coverage, f.id IS NOT NULL FROM versions v "
        "LEFT JOIN files f ON f.version_id = v.id AND f.song_id = v.song_id AND f.name = ? "
        "WHERE v.provider = 'lacuerda' AND v.slot = 'sheet' AND v.gone = 0"
        + only + " ORDER BY v.song_id, v.coverage IS NULL, v.coverage DESC, v.id",
        (HUMAN_SHEET,) if ids is None else (HUMAN_SHEET, json.dumps(sorted(ids))),
    )
    met: dict[int, list[dict[str, Any]]] = {}
    for song_id, url, coverage, sheet in rows:
        met.setdefault(song_id, []).append({"href": url, "coverage": coverage, "sheet": bool(sheet)})
    return met


def _lacuerda_sheet(song: Song, overrides: Overrides, status: str, origins: Mapping[str, str],
                    met: str | None) -> str | None:
    """The LaCuerda sheet a song of yours could be looked up with now (its served line's "Use LaCuerda's sheet",
    ``POST /lookup`` with it, as ``caracole get --lacuerda`` takes it): your pick on LaCuerda, else the best one
    caracole met for it (``_lacuerda_versions``' first); None when its kept sheet is LaCuerda's already, or the song
    is ignored."""
    if status == "ignored" or origins.get("sheet.txt") == "lacuerda":
        return None
    pick = overrides.lacuerda.get(song.key)
    url = pick.url if pick is not None else met
    return url if url and url.startswith("https://") else None


def _youtube_note(state: SongState | None) -> dict[str, Any] | None:
    """What a song's line says of it on the YouTube route, and the video its audio came from."""
    if state is None or state.state not in _YOUTUBE_NOTES:
        return None
    video = state.video if state.state in (DOWNLOADED, CHORDS) else None
    name = f"{video.title} ({video.channel})" if video and video.title and video.channel else None
    return {"text": _YOUTUBE_NOTES[state.state],
            "video": {"label": name or (video.title or video.url), "href": video.url} if video else None}


def _song(library_dir: Path, song: Song, overrides: Overrides, key: SongKey | None,
          for_buying: bool, sources: dict[str, str],
          musescore: list[dict[str, str]], youtube: dict[str, Any] | None = None, *,
          origins: dict[str, str] | None = None, exports: Mapping[str, str] | None = None,
          transpose: int = 0, lacuerda: list[dict[str, Any]] | None = None,
          versions: _UgVersions | None = None, guitar: Mapping[str, str] | None = None,
          ukulele: bool = False) -> dict[str, Any]:
    """One song's data; ``for_buying`` when the to-do page's buy list holds it (``todo.songs_to_buy``),
    ``sources`` the site each file caracole downloaded for it came from, by name, ``musescore``
    the song's MuseScore pages, and ``youtube`` where the song stands on the YouTube route.

    ``key`` and ``key_source`` are the song's key and where it came from, as in its info.json.
    ``origins`` is where each of its kept files came from (``icons.kept_sources``): each file gets
    its ``source``, and the song its primary file's. ``exports``: the PDFs caracole made of its sheet in
    other versions, by file name, each with its version's label (``_exports``); ``transpose``, how many semitones
    its PDF is moved by (``render.pdf_transpose``). ``lacuerda``: the LaCuerda sheets caracole met for it, best first
    (``_lacuerda_versions``), its ``lacuerdaVersions``, the first of which is the one ``lacuerdaSheet`` may name
    (``_lacuerda_sheet``). ``versions``: its UG versions as the page counts them, for a song with some recorded for
    its sheet (``_ug_versions``), its ``versions`` (``_versions_data``): its card's Versions chip of Ultimate Guitar
    and that chip's drawer, kept ones listed and the rest counted. ``guitar``: the address of caracole serve's Guitar
    Pro page of each of its Guitar Pro files, by name (``guitar_pages``). ``ukulele``: its sheet is UG's Ukulele
    Chords version (``ukulele_sheets``), which its sheet's files say. ``autoSheet``: an auto sheet beside its human
    one (``_auto_sheet``), the sheet tile's Auto chip.
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
    files = _files(library_dir, song, names, sources, origins or {}, exports or {}, guitar, ukulele=ukulele)
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
        "instruments": instruments_of(names, ukulele=ukulele),  # what it holds for one instrument, its line's marks
        "versions": _versions_data(versions, names, _folder_href(library_dir, song)),  # UG's: kept, and counted
        "autoSheet": _auto_sheet(library_dir, song, names),
        "source": next((f["source"] for f in files if f["primary"]), None),  # where its sheet came from
        "museScore": musescore,
        "links": links,
        "buy": buy,
        "youtube": youtube if status != "ignored" else None,
        "lacuerda": _lacuerda_pick(song, overrides, status),
        "lacuerdaVersions": lacuerda or [],
        "lacuerdaSheet": _lacuerda_sheet(song, overrides, status, origins or {},
                                         lacuerda[0]["href"] if lacuerda else None),
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


# An auto sheet's files beside a human sheet, as its chip's drawer offers them, by the labels it shows.
_AUTO_OPENS = ("sheet (auto).html", "sheet (auto).pdf", "sheet (auto).txt")
_AUTO_FILES = (("sheet (auto).pdf", "PDF"), ("sheet (auto).txt", "Text"), ("sheet (auto).cho", "ChordPro"))


def _auto_sheet(library_dir: Path, song: Song, names: set[str]) -> dict[str, Any] | None:
    """The auto sheet of a song that has a human sheet too, which is its sheet: its viewer (else its PDF, else its
    text, as a line's title opens a sheet) as ``href``, and its PDF, text and ChordPro that exist, each with the name
    it downloads under ("Eagles - Hotel California (auto).pdf", download_names.py's with "(auto)" after the title,
    so it never takes the human sheet's name). None for any other song: an auto sheet alone is the song's sheet,
    which its files and its title give."""
    if not (any(n in names for n in _HUMAN_SHEETS) and any(n in names for n in _AUTO_SHEETS)):
        return None
    base = _folder_href(library_dir, song)
    opens = next(n for n in _AUTO_OPENS if n in names)
    title = f"{clean_title(song.title)} (auto)"
    return {"href": f"{base}/{quote(opens, safe='')}",
            "files": [{"label": label, "href": f"{base}/{quote(n, safe='')}",
                       "download": download_name(song.artist, title, n)}
                      for n, label in _AUTO_FILES if n in names]}


def _file_names(folder: Path) -> set[str]:
    try:
        return {p.name for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")}
    except OSError:  # no folder yet
        return set()


def _files(library_dir: Path, song: Song, names: set[str], sources: dict[str, str],
           origins: dict[str, str] | None = None, exports: Mapping[str, str] | None = None,
           guitar: Mapping[str, str] | None = None, *, ukulele: bool = False) -> list[dict[str, Any]]:
    """Links to the kept files that exist, as paths relative to index.html, percent-encoded. The
    primary one is the sheet's PDF, else its text: never a score, whatever its format. Each says
    where it came from (``icons.source_of``). ``exports`` (``_exports``) are listed after the sheets' viewers
    and PDFs, by their labels, those still in the folder alone, each with its ``version`` ("G Dorian, capo 0"),
    which its line's "⋯" lists it by, under PDF exports. A version kept beside the sheet (``version-<tab>.*``) is
    none of them: the line lists it under Sheet versions (``_versions_data``). ``guitar`` (``guitar_pages``): each
    Guitar Pro file caracole serve shows in the browser gets that page's address, its ``guitarPage``, which the
    page it serves offers as Open in the browser beside the file's Download. A Guitar Pro or Power Tab file, and a
    score but its PDF, gets the name it downloads under, its ``download`` ("Eagles - Hotel California (2).gp5":
    download_names.py), its links' ``download`` attribute, as caracole serve's header names it. ``ukulele``: the
    sheet is UG's Ukulele Chords version (``ukulele_sheets``), and its files' labels say so ("Sheet viewer ·
    Ukulele Chords"). A harmonica tab whose page is beside it (``harmonica-N.html``, render.py) gets that page's
    address, its ``harmonicaPage`` (``{"href"}``, a link the offline copy takes: ``linked_files``), which its line
    lists as a group of its own, Open and Download (the text); the page is no file of the list."""
    pages = guitar or {}
    guitar_names = sorted((int(m.group(1)), n) for n in names if (m := _GUITAR.fullmatch(n)))
    scores = sorted((int(m.group(1)), SCORE_EXTENSIONS.index(m.group(2)), n)
                    for n in names if (m := _SCORE.fullmatch(n)) and m.group(2) in SCORE_EXTENSIONS)
    harmonica = sorted((int(m.group(1)), n) for n in names if (m := _HARMONICA.fullmatch(n)))
    made = sorted((label, n) for n, label in (exports or {}).items() if n in names)
    labels = {n: f"Sheet PDF, {label}" for label, n in made}
    ordered = ([n for n in _SHEET_PAGES if n in names] + [n for _, n in made]
               + [n for n in _FIRST if n in names and n not in _SHEET_PAGES]
               + [n for _, n in guitar_names] + [n for _, _, n in scores] + [n for _, n in harmonica]
               + [n for n in _LAST if n in names])
    base = _folder_href(library_dir, song)
    primary = next((n for n in ordered if n in ("sheet.html", "sheet (auto).html", "sheet.pdf", "sheet (auto).pdf")),
                   None) or next(
        (n for n in ordered if n in ("sheet.txt", "sheet (auto).txt")), None)
    versions = {n: label for label, n in made}
    downloads = {n: download_name(song.artist, clean_title(song.title), n) for n in ordered
                 if _GUITAR.fullmatch(n) or (_SCORE.fullmatch(n) and not n.endswith(".pdf"))}
    if ukulele:
        labels.update({n: f"{_LABELS[n]} · {UKULELE_SHEET}" for n in _UKULELE_LABELLED if n in names})
    harp_pages = {n: page for _, n in harmonica if (page := harmonica_page(n)) in names}
    return [
        {"name": n, "label": labels.get(n) or _label(n, sources.get(n)), "href": f"{base}/{quote(n, safe='')}",
         "primary": n == primary, "source": source_of(n, origins or {}),
         **({"version": versions[n]} if n in versions else {}),
         **({"guitarPage": pages[n]} if n in pages else {}),
         **({"harmonicaPage": {"href": f"{base}/{quote(harp_pages[n], safe='')}"}} if n in harp_pages else {}),
         **({"download": downloads[n]} if n in downloads else {})}
        for n in ordered
    ]


def _folder_href(library_dir: Path, song: Song) -> str:
    """The song's folder, relative to index.html and percent-encoded: its files' links start with it."""
    folder = song_dir(library_dir, song).relative_to(library_dir)
    return "/".join(quote(part, safe="") for part in folder.parts)


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
    m = _HARMONICA.fullmatch(name)
    if m:
        return f"Harmonica tab {m.group(1)}" + (f" · {source}" if source else "")
    return _LABELS[name]


def instruments_of(names: set[str], *, ukulele: bool = False) -> list[str]:
    """What a song's folder holds for one instrument, which its line marks as the search's rows are (rows.js
    ``instrumentBadges``): "ukulele", its sheet one of UG's Ukulele Chords; "harmonica", a harmonica tab kept from
    harptabs.com; "score", a score you filed. A chord sheet is every instrument's, and is no mark."""
    found = ["ukulele"] if ukulele else []
    if any(_HARMONICA.fullmatch(n) for n in names):
        found.append("harmonica")
    if any((m := _SCORE.fullmatch(n)) and m.group(2) in SCORE_EXTENSIONS for n in names):
        found.append("score")
    return found


UKULELE_SHEET = "Ukulele Chords"  # what a sheet from UG's Ukulele Chords type is called on the page
_UKULELE_LABELLED = ("sheet.html", "sheet.pdf", "sheet.txt", "sheet.cho")  # the human sheet's files


def ukulele_sheets(conn: sqlite3.Connection) -> set[int]:
    """The songs whose sheet is a version of Ultimate Guitar's Ukulele Chords type (ug/fetch.py: a song with no
    chords there takes those), by the version its kept ``sheet.txt`` came from."""
    return {r[0] for r in conn.execute(
        "SELECT f.song_id FROM files f JOIN versions v ON v.id = f.version_id "
        "WHERE f.name = 'sheet.txt' AND v.provider = 'ug' AND v.kind = 'ukulele'")}


def guitar_pages(conn: sqlite3.Connection) -> dict[int, dict[str, str]]:
    """The address of caracole serve's Guitar Pro page (web/guitar_routes.py, relative to the library page) of each
    Guitar Pro file caracole keeps that it shows (``inbox.guitar_files``: not a Power Tab file), as {song id: {file
    name: "guitar?file=…"}}."""
    found: dict[int, dict[str, str]] = {}
    for f in guitar_files(conn):
        if f.in_browser:
            found.setdefault(f.song_id, {})[f.name] = "guitar?" + urlencode({"file": f.path})
    return found


_DOWNLOADED_FROM = {"gtptabs": "gtptabs.com", "harptabs": "harptabs.com"}


def _downloaded(conn: sqlite3.Connection) -> dict[int, dict[str, str]]:
    """The files caracole downloaded from gtptabs.com and harptabs.com, as {song id: {file name: "gtptabs.com"}}."""
    found: dict[int, dict[str, str]] = {}
    rows = conn.execute(
        "SELECT f.song_id, f.name, v.provider FROM files f JOIN versions v ON v.id = f.version_id "
        "WHERE v.provider IN ('gtptabs', 'harptabs')"
    )
    for song_id, name, provider in rows:
        found.setdefault(song_id, {})[name] = _DOWNLOADED_FROM[provider]
    return found


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
STYLESHEETS = ("base.css", "picker.css", "library.css", "filter.css", "rows.css", "card.css", "steps.css", "library-screens.css",
               "songbooks.css")
SCRIPTS = ("rows.js", "card.js", "library.js", "select.js", "songbooks.js", "drawn.js")
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
