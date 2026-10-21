"""Library/index.html: browse and search the whole library, on a phone or a laptop (A7).

One self-contained file, rewritten wherever ``_todo.md`` is. It opens from the
Syncthing folder with no server: it loads nothing from the network (a
Content-Security-Policy with the hashes of its one script and one stylesheet
makes the browser enforce that), and it links to each song's files by
relative paths. That script and that stylesheet are the files of
library_assets/, inlined as they are (``STYLESHEETS``, ``SCRIPTS``).

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

The songs are one grid of cards, as many columns as the screen holds, in every
order: a section per artist left one narrow card per row on a desktop. Each
card has its artist's monogram, in a colour of that artist's, and an A-Z strip
jumps to the first card of a letter once more than 40 songs show. A card's
title and its one Open button open its sheet (its viewer, else its PDF, else
its text); its other files, and the Guitar Pro versions to download from UG,
fold under Files, as a row's "⋯" folds them. The title keeps its line: the
artist goes under it, with the badges at the end of that line or under it. The
artist's name, marked with a funnel (``artistFilter``, ROWS_SCRIPT's), shows
that artist's songs alone, on a card and on a row. On a phone the header is
short (the numbers beside the title, one row of buttons that scrolls sideways,
Key, Sort and the view under View), so the first song starts on the first
screen; the bar stays at the top, with an edge once the page scrolls under it.
A Cards/Rows toggle shows them as rows
instead, one compact line a song (two on a phone), remembered in the address
(``#view=rows``) as the search, the filters, the sort and the key are.

On a touch screen (``pointer: coarse``) every control is a thumb's target, 44
px each way at the least: buttons, folds, chips, menus, letters, a row's "⋯"
and an artist's name (a card's at the top of its box, under its title, whose
target reaches down to it); a mouse keeps the compact sizes, about twenty rows to a
laptop's screen. Fields, menus and the Select boxes have the ``--control-edge``
colour, 3:1 or more against every background (WCAG 1.4.11); cards and dividers
keep the soft ``--border``. ``BASE_STYLE`` and ``PICKER_STYLE`` carry both to
the pages caracole serve writes itself (web/pages.py, web/lookup_page.py).

Each file, link and row shows where it came from (icons.py): the site's own
icon, inlined in the data as a ``data:`` URI (the CSP allows images from
``data:`` alone), else the site's lettered badge, or a glyph for the audio
model and the inbox; each is named "from Ultimate Guitar" for a screen reader.
An auto sheet made from the audio caracole took from YouTube shows YouTube's
(``icons.kept_sources``), and its card, or its row's "⋯", the video.

The seam for lists the page doesn't make itself (the results of caracole
serve's lookup page, web/lookup_page.py, which runs ``ROWS_SCRIPT`` and has
``ROWS_STYLE`` as this page does, and gets each song's files from
``result_cards``): ``window.caracole.resultRow(result)`` returns a row
element, the same as a song's row, to put in a ``<div class="rows">``.
``result`` is a plain object, every field optional:

- ``title``, ``artist``: text; ``onArtist``, a function, makes the artist a button that
  shows it filters (a funnel after the name), as on a card;
- ``href``: what the title opens (the row's sheet, as its button does), the same way as
  ``action``'s link; out of the Tab order, since the button says what it opens;
- ``source``: a key of the data's ``icons`` (``icons.SOURCES``: "ug", "lacuerda"…);
- ``key`` ("A minor"), and ``keyText``, what a screen reader hears for it;
- ``status``, which the row's ``data-status`` gets; ``badges``: ``[{kind, text}]``,
  ``kind`` a badge class (found, wanted, review, auto…); ``facts``: a line of text;
- ``action``: the main control, a Node, or ``{label, href, source}``: an http(s)
  link opens in a new tab, any other address stays relative or goes nowhere;
- ``more``: what the row's "⋯" button shows, Nodes or
  ``{heading, links: [{label, href, source}]}``.

``window.caracole.sourceMark(key)`` gives a source's mark alone, and
``window.caracole.icons`` the icons' data. ``ROWS_SCRIPT`` also draws the
offline indexes' hits, as ``/api/search`` and ``/api/artist`` give them
(``ugHit``, ``artistHit``, ``siteHit``, ``siteArtist`` and ``siteArtistSongs``,
LaCuerda's artists and their songs, ``siteUnlisted``, a name under a letter its
listings aren't read to yet, with ``readArtistPage``, which asks the server to
read an artist's page, by its slug or by a name, and ``readOutcome``, what
LaCuerda answered a read that left nothing to list), for this page's search of
the sites and the lookup page alike.

**One bar.** The search box filters your songs as you type, here, asking
nothing. Enter, or Search all, searches the sites too. The file can ask
nothing of anyone: it shows the ``caracole search`` line to run, with Copy,
above your songs (in their empty list when none match). Served, the results
take the grid's place until Escape: your songs that match, as their own rows,
then the Ultimate Guitar index's songs and artists, LaCuerda's artists and
songs, gtptabs.com's pages and MuseScore's (``GET /api/search``, a moment after
the last key, the newest query alone, the sites left out, or searched in part,
said with why), each with Get it (``POST /lookup``), whose request's line shows
in the result's own row. A LaCuerda artist's Songs lists the songs the index
holds of theirs, or offers to read their page (``POST /lacuerda/artist``), and
so does a query LaCuerda's index has no artist by while the listing of its
letter isn't read whole. A wanted song whose sheet you picked on LaCuerda says
that tonight's run gets it (``lacuerda``), and isn't a song not found
(``notFound``). Enter never
spends a request. The request form sits under the results, filled in from
the query.

``caracole serve`` serves the same page with ``controls`` (``WebControls``): the
search of the sites, a form to request a song, a "Fetch now" button on each wanted song, a "Remove…"
button on each card (it counts down five seconds, with Undo, before it sends anything), and a CSP
that lets the forms post to the server (``form-action 'self'``) and the script
ask it how its requests go (``connect-src 'self'``). The script posts the forms
with fetch(), so the page stays where it is: each song's card shows its
request's one line (web/status.py), from ``/jobs.json``, asked every 1.5 s
while one waits or runs, and is drawn again from the song's new data once the
request is over. A song's row carries what its card does: the line, on a line
of the row's own; Pick the match, or Removing…, as its button; the picker,
Look in the index and Remove… under its "⋯". A song new to the library gets a card of its own under the
bar, and two requests or more also show in a corner, folded to one line that opens upwards. Without
JavaScript the forms post as forms. The file on disk has none of it, and lets
no form be sent and nothing be asked.

Remove… stays on the page: one tap and the song's own line says "Removing in 5 s
· Undo", the focus on Undo, with what goes in one sentence under it (the
server's answer to the question, ``removal.brief``: caracole's files of the
song, its record, its wanted.txt line; never Music/). Nothing else is sent for
those five seconds, and Undo stops it ("Not removed", the focus back on
Remove…); then the page posts the removal with the song's key, and the line
follows it ("Removing…", "Removing from caracole…", then "Removed"), as tall as
it was. The card is then a ``gone`` one, its name alone, as tall as it was and
its line where it was, until the page is loaded again. Without JavaScript,
Remove…'s question is a page of the server's; Remove it, and Keep it, come back
to this page as it was left (Remove… sends the address after # along, ``back``),
at the song's card: ``song=ID`` in the address, which the script scrolls to and
focuses, then drops.

The Songbooks section's forms, and the Select bar's Make songbook, post with
fetch() too: the songbook's card says how its change goes on a line under its
name, its buttons waiting (a song moves by its place now), a new songbook's
card at the section's end, which opens on it; once the change is over the
section is drawn again from the server's own HTML (``songbooks_section``,
which ``/jobs.json`` gives with the job: the script's ``drawSongbooks`` reads
it with DOMParser, which runs no script, and keeps each card that shows a line
where it is, so that its line goes on being read out, and the height it had while
it is taller than what it holds, until the next click or key). On the served page the
section is there even before the first songbook, hidden. A songbook with songs
of yours that have no sheet yet has Get the N missing songs now (each such
song's ``<li>`` marked ``data-get``; every song's names its id, ``data-song``):
one lookup per song, each one's line under its name there and on its card, then
the songbook made again, on its own line.

A song in review carries its candidates (``review_choices``), numbered as
``caracole review`` numbers them, and its card a picker (the script's
``makePicker``): a disclosure that lists them, each with its UG names, its
score, why the matcher thought of it and a link to its UG page. On the file
it is read-only, with the ``caracole review --song`` line that picks one;
served, it is a radio group posted to ``/review`` (web/app.py), in place of the
"Review first" button, and opening it takes the focus to the first candidate.
A pick posts with fetch() as the other forms do, and the card's line says how
it goes; while any request of the song waits or runs, the picker offers no
pick, and the line's "Pick the match" (a request that ended in a review)
opens it.
A song not found carries ``notFound``, and its served card links to
``/review?song=ID``, which offers what ``caracole search`` finds for it: a
search per song would cost every page a moment each.
"""

from __future__ import annotations

import hashlib
import html as html_text
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from caracole.config import Config
from caracole.icons import kept_sources, page_icons, source_of
from caracole.inbox import SCORE_EXTENSIONS
from caracole.inline import json_block, sha256_source
# The page's style and script are files (library_assets/); the pieces caracole serve's own pages share
# stay importable from here.
from caracole.library_assets import BASE_STYLE, PICKER_STYLE, ROWS_SCRIPT, ROWS_STYLE  # noqa: F401
from caracole.library_assets import read as read_asset
from caracole.keys import SongKey, key_name, song_key
from caracole.library import song_dir, write_atomic
from caracole.musescore import song_pages
from caracole.normalize import clean_title, fold, has_han, romanize, slug_key
from caracole.overrides import Overrides
from caracole.songs import Song, list_songs
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

PAGE_NAME = "index.html"

# Kept files, in the order a card shows them; guitar-N.* goes between the two groups.
_FIRST = ("sheet.html", "sheet.pdf", "sheet (auto).html", "sheet (auto).pdf", "sheet.txt", "sheet.cho",
          "lyrics.txt", "lyrics.lrc")
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
HUES = 8  # monogram colours, .hue-0 to .hue-7


@dataclass(frozen=True)
class WebControls:
    """What ``caracole serve`` adds to the page it serves (caracole/web/).

    ``csrf`` is the token every form posts back; ``busy`` holds the songs with a
    fetch queued or running, whose cards say so instead of offering another;
    ``active`` is how many requests are queued or running, for the masthead;
    ``held`` holds the songs a fetch must wait for a review of, whose cards say so;
    ``removing`` holds the songs with a removal queued or running, whose cards
    say so instead of offering Remove; ``jobs`` are the requests queued or
    running, as ``/jobs.json`` gives them, so their cards show their progress
    from the start: a song's, a removal's on its song's card, and a songbook's
    change on its songbook's (``kind``).
    """

    csrf: str
    busy: frozenset[int] = frozenset()
    active: int = 0
    held: frozenset[int] = frozenset()
    removing: frozenset[int] = frozenset()
    jobs: tuple[dict[str, Any], ...] = ()


def build_library_page(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, now: datetime, *,
                       controls: WebControls | None = None) -> str:
    """The whole page: every song, its files, and the links to find what's missing.

    With ``controls``, the page ``caracole serve`` serves: the same, with its forms.
    """
    songs = song_cards(conn, cfg, overrides, now)
    data: dict[str, Any] = {
        "generated": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fold": {c: fold(c) for c in _TRANSLITERATED},
        "songs": songs,
        "icons": page_icons(cfg.cache_dir),  # each source's name, badge and inlined icon (icons.py)
    }
    if controls is not None:
        data["server"] = {"csrf": controls.csrf, "busy": sorted(controls.busy), "active": controls.active,
                          "removing": sorted(controls.removing), "jobs": list(controls.jobs)}
        for song in songs:
            song["fetchable"] = song["id"] not in controls.held
    books, data["songbooks"] = songbooks_section(conn, cfg, overrides, controls)
    # The page caracole serve serves may also ask it how its requests go (connect-src); the file can't.
    csp = (_CSP.replace("__FORMS__", "'self'; connect-src 'self'") if controls is not None
           else _CSP.replace("__FORMS__", "'none'"))
    return (
        _HEAD.replace("__CSP__", csp).replace("__STYLE__", _PAGE_STYLE)
        + _BODY.replace("__NAV__", _nav(controls)).replace("__REQUEST__", _request_form(controls))
        .replace("__REQUESTED__", _requested(controls)).replace("__SONGBOOKS__", books)
        + json_block("songs", data)
        + f"<script>{_PAGE_SCRIPT}</script>\n</body>\n</html>\n"
    )


def song_cards(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, now: datetime,
               songs: list[Song] | None = None) -> list[dict[str, Any]]:
    """The cards' data, as the page's JSON holds it: of every song, or of ``songs``; a song in review
    with its candidates, for the picker (``_add_picks``); each file with where it came from."""
    pages = _guitar_pro_pages(conn)
    sources = _downloaded(conn)
    origins = kept_sources(conn)
    library = list_songs(conn) if songs is None else songs
    keys = {s.id: song_key(conn, cfg.library_dir, s) for s in library}
    to_buy = {s.id for s in songs_to_buy(conn, library, overrides, now)[0]}  # the to-do page's buy list
    # With the YouTube route on, caracole takes those songs' audio itself: their cards say how it goes,
    # and only a song you turned YouTube down for is for buying.
    youtube = song_states(conn, cfg, overrides, now) if route_problem(cfg) is None else {}
    if youtube:
        to_buy = {i for i in to_buy if i not in youtube or youtube[i].state == DECLINED}
    musescore = cfg.provider("musescore").enabled
    cards = [_song(cfg.library_dir, s, overrides, keys.get(s.id), pages.get(s.id, []), s.id in to_buy,
                   sources.get(s.id, {}), _musescore_links(conn, s, overrides) if musescore else [],
                   _youtube_note(youtube.get(s.id)), origins=origins.get(s.id, {}))
             for s in library]
    _add_picks(conn, library, cards)
    return cards


def result_cards(conn: sqlite3.Connection, cfg: Config, songs: list[Song]) -> dict[int, dict[str, Any]]:
    """What a list the page doesn't make itself shows of each song as its card does (caracole serve's
    lookup page, which draws them with ``ROWS_SCRIPT``): its files, relative to the library and
    percent-encoded, the primary one marked (its viewer, else its PDF, else its text), each with where
    it came from; where its sheet came from; its key. By song id."""
    origins = kept_sources(conn)
    cards = {}
    for s in songs:
        files = _files(cfg.library_dir, s, _file_names(song_dir(cfg.library_dir, s)), {}, origins.get(s.id, {}))
        key = song_key(conn, cfg.library_dir, s)
        cards[s.id] = {"links": files, "source": next((f["source"] for f in files if f["primary"]), None),
                       "key": key.key if key else None}
    return cards


def sheet_href(library_dir: Path, song: Song) -> str | None:
    """The link to the song's sheet, its card's main file (relative to index.html), or None without one."""
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
    """Give each card of a song in review (not ignored) its candidates, for the picker, and mark a song
    not found (``notFound``), whose served card links to its search hits: a search each would cost
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
    """The sheet you picked on LaCuerda (``[lacuerda]``), for a wanted song's card to say that tonight's run
    gets it; None once LaCuerda was asked for it, and for any other song."""
    pick = overrides.lacuerda.get(song.key)
    if pick is None or status != "wanted" or song.lacuerda_checked_at is not None:
        return None
    return {"label": "the sheet you picked on LaCuerda", "href": pick.url}


def _youtube_note(state: SongState | None) -> dict[str, Any] | None:
    """What a card says of a song on the YouTube route, and the video its audio came from."""
    if state is None or state.state not in _YOUTUBE_NOTES:
        return None
    video = state.video if state.state in (DOWNLOADED, CHORDS) else None
    name = f"{video.title} ({video.channel})" if video and video.title and video.channel else None
    return {"text": _YOUTUBE_NOTES[state.state],
            "video": {"label": name or (video.title or video.url), "href": video.url} if video else None}


def _song(library_dir: Path, song: Song, overrides: Overrides, key: SongKey | None,
          guitar_pro: list[dict[str, str]], for_buying: bool, sources: dict[str, str],
          musescore: list[dict[str, str]], youtube: dict[str, Any] | None = None, *,
          origins: dict[str, str] | None = None) -> dict[str, Any]:
    """One song's card; ``for_buying`` when the to-do page's buy list holds it (``todo.songs_to_buy``),
    ``sources`` the site each file caracole downloaded for it came from, by name, ``musescore``
    the song's MuseScore pages, and ``youtube`` where the song stands on the YouTube route.

    ``key`` and ``key_source`` are the song's key and where it came from, as in its info.json.
    ``origins`` is where each of its kept files came from (``icons.kept_sources``): each file gets
    its ``source``, and the song its primary file's.
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
    files = _files(library_dir, song, names, sources, origins or {})
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
        "transpose": overrides.transpose.get(song.key, 0),
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
        "sortArtist": _sort_key(song.artist),
        "sortTitle": _sort_key(title),
        "artistLetter": _letter(_sort_key(song.artist)),
        "titleLetter": _letter(_sort_key(title)),
        "monogram": _monogram(song.artist),
        "hue": _hue(song.artist),
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
           origins: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Links to the kept files that exist, as paths relative to index.html, percent-encoded. The
    primary one is the sheet's PDF, else its text: never a score, whatever its format. Each says
    where it came from (``icons.source_of``)."""
    guitar = sorted((int(m.group(1)), n) for n in names if (m := _GUITAR.fullmatch(n)))
    scores = sorted((int(m.group(1)), SCORE_EXTENSIONS.index(m.group(2)), n)
                    for n in names if (m := _SCORE.fullmatch(n)) and m.group(2) in SCORE_EXTENSIONS)
    ordered = ([n for n in _FIRST if n in names] + [n for _, n in guitar] + [n for _, _, n in scores]
               + [n for n in _LAST if n in names])
    folder = song_dir(library_dir, song).relative_to(library_dir)
    base = "/".join(quote(part, safe="") for part in folder.parts)
    primary = next((n for n in ordered if n in ("sheet.html", "sheet (auto).html", "sheet.pdf", "sheet (auto).pdf")),
                   None) or next(
        (n for n in ordered if n in ("sheet.txt", "sheet (auto).txt")), None)
    return [
        {"name": n, "label": _label(n, sources.get(n)), "href": f"{base}/{quote(n, safe='')}", "primary": n == primary,
         "source": source_of(n, origins or {})}
        for n in ordered
    ]


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


def _monogram(artist: str) -> str:
    """The card's badge for an artist: two initials ("SS"), or the first Han character ("宋")."""
    if has_han(artist):
        return next(c for c in artist if has_han(c))
    words = _WORD.findall(artist)
    if not words:
        return artist.strip()[:1] or "?"
    return "".join(w[0] for w in words[:2]).upper()


def _hue(artist: str) -> int:
    """The monogram's colour, the same for every song of an artist."""
    return int.from_bytes(hashlib.sha256(fold(artist).encode("utf-8")).digest()[:4], "big") % HUES


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
SCRIPTS = ("rows.js", "library.js", "select.js")
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

_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="__CSP__">
<title>caracole library</title>
<style>__STYLE__</style>
</head>
"""

_BODY = """<body>
<div class="page">
<header class="masthead lib">
  <p class="app">caracole</p>
  <div class="title-line">
    <h1>Your library</h1>
    <ul class="summary" id="summary" aria-label="The library in numbers"></ul>
  </div>
  <nav class="links" aria-label="Pages">__NAV__</nav>
</header>
__SONGBOOKS__<div class="bar-edge" id="bar-edge" aria-hidden="true"></div>
<div class="searchbar" role="search">
  <label class="visually-hidden" for="q">Search your songs</label>
  <div class="bar-row">
    <div class="field">
      <input id="q" type="search" placeholder="Artist, title or key" autocomplete="off" autocapitalize="off"
        autocorrect="off" spellcheck="false" enterkeyhint="search" aria-describedby="bar-status">
      <button type="button" id="clear" class="clear" aria-label="Clear the search" hidden>×</button>
    </div>
    <button type="button" id="all" class="btn all">Search all</button>
  </div>
  <p class="bar-status" id="bar-status" aria-live="polite"></p>
</div>
__REQUESTED__<section class="results" id="results" aria-label="Search results">
<div class="found" id="found" hidden></div>
__REQUEST__</section>
<div class="toolbar">
  <div class="chips" role="group" aria-label="Show">
    <button type="button" class="chip" data-show="all" aria-pressed="true">All <span class="n"></span></button>
    <button type="button" class="chip" data-show="found" aria-pressed="false">Found <span class="n"></span></button>
    <button type="button" class="chip" data-show="wanted" aria-pressed="false">Wanted <span class="n"></span></button>
    <button type="button" class="chip" data-show="review" aria-pressed="false">Needs review <span class="n"></span></button>
    <button type="button" class="chip person" id="artist" hidden></button>
  </div>
  <div class="controls">
    <button type="button" class="chip view-toggle" id="view-toggle" aria-expanded="false"
      aria-controls="view-panel">View</button>
  </div>
  <div class="view-panel" id="view-panel">
  <div class="views" role="group" aria-label="View">
    <button type="button" data-view="cards" aria-pressed="true">Cards</button>
    <button type="button" data-view="rows" aria-pressed="false">Rows</button>
  </div>
  <label class="sort" id="keys" hidden>Key
    <select id="key"><option value="">Any</option></select>
  </label>
  <label class="sort">Sort
    <select id="sort">
      <option value="artist">Artist A–Z</option>
      <option value="title">Title A–Z</option>
      <option value="recent">Recently added</option>
    </select>
  </label>
  </div>
</div>
<nav class="jump" id="jump" aria-label="Jump to a letter" hidden></nav>
<p class="count" id="count" aria-live="polite"></p>
<main class="list" id="list"></main>
<noscript><p class="empty">This page needs JavaScript to list your songs. Each song's files are in its
  folder, next to this page.</p></noscript>
<footer class="footer"><span id="updated"></span>Keep this library private: the sheets and lyrics are other
  people's work.</footer>
</div>
"""

# The form caracole serve adds, under the search's results: a song for wanted.txt, written as `caracole add`
# writes it. The script fills it in from what was searched; without the script it posts as a form.
_REQUEST = """<details class="request" id="request-box">
  <summary><span class="plus" aria-hidden="true"><span>+</span></span>Not in the list? Request it by name</summary>
  <form class="request-form" method="post" action="/request">
    <input type="hidden" name="csrf" value="__CSRF__">
    <div class="fields">
      <label class="f">Artist<input name="artist" required maxlength="200" autocomplete="off"></label>
      <label class="f">Title<input name="title" required maxlength="300" autocomplete="off"></label>
      <label class="f"><span>Album <em>(optional)</em></span><input name="album" maxlength="300"
        autocomplete="off"></label>
      <label class="f"><span>Length <em>(optional: m:ss or seconds)</em></span><input name="duration"
        maxlength="12" autocomplete="off" placeholder="3:45"></label>
    </div>
    <div class="request-row">
      <label class="check"><input type="checkbox" name="fetch" value="1" checked>Fetch it now</label>
      <button class="btn primary" type="submit">Request</button>
    </div>
    <p class="hint">It goes into wanted.txt, as <code>caracole add</code> writes it. Fetch it now looks it
      up at once, as <code>caracole get</code> does: its sheet in seconds, then its lyrics, PDF and the rest,
      a few requests about a second apart.</p>
  </form>
</details>
"""

# What caracole serve adds under the bar: the songs just requested, each a card with its line, and the
# requests, a short list in a corner.
_REQUESTED = """<section class="requested" id="requested" aria-label="Songs you just requested" hidden>
  <p class="subhead">Just requested</p>
  <div class="grid" id="requested-grid"></div>
</section>
<aside class="tray" id="tray" aria-label="Your requests" hidden>
  <div class="tray-head">
    <button type="button" class="tray-toggle" id="tray-toggle" aria-expanded="false" aria-controls="tray-list"><span
      id="tray-sum">Requests</span></button>
    <a class="tray-all" href="jobs">Details</a>
    <button type="button" class="tray-close" id="tray-close" aria-label="Close this list">×</button>
  </div>
  <ol class="tray-list" id="tray-list" hidden></ol>
</aside>
"""


def _nav(controls: WebControls | None) -> str:
    """The masthead's links: the to-do page, and caracole serve's requests."""
    links = '<a class="navlink" href="_todo.md">To-do</a>'
    if controls is not None:
        n = f'<span class="n">{controls.active}</span>' if controls.active else ""
        links += f'<a class="navlink" href="/jobs">Requests{n}</a>'
    return links


def _request_form(controls: WebControls | None) -> str:
    if controls is None:
        return ""
    return _REQUEST.replace("__CSRF__", html_text.escape(controls.csrf, quote=True))


def _requested(controls: WebControls | None) -> str:
    return _REQUESTED if controls is not None else ""


# --- songbooks: the section (songbook.py) ---------------------------------------------------------


def songbooks_section(conn: sqlite3.Connection, cfg: Config, overrides: Overrides,
                      controls: WebControls | None) -> tuple[str, list[dict[str, Any]]]:
    """The Songbooks section, and the songbooks for the Select mode's bar ({"name", "songs"}).

    Each songbook lists its songs in order, the missing ones marked, and links its files. On
    caracole serve (``controls``) each song can move up or down or be taken out, and the songbook
    renamed or deleted, by forms that post to the server; the file on disk says which command does it.
    No songbook, no section (on caracole serve, a hidden one, where the page's script shows the first
    songbook made); a songbooks.toml that can't be read is said there, and costs the rest of the page
    nothing. Each card is named by its songbook (``data-songbook``), which the served page's script
    finds it by.
    """
    from caracole.songbook import SongbookError, load_songbooks, songbooks_file

    try:
        books = load_songbooks(songbooks_file(cfg.library_dir))
    except SongbookError as e:
        body = (f'<p class="sb-error">songbooks.toml can\'t be read: {html_text.escape(str(e))}. Fix it, and '
                "the songbooks are back; until then each keeps its files.</p>\n")
        return _songbooks_wrap("!", body), []
    if not books:
        return (_songbooks_wrap("0", '<div class="sb-list">\n</div>\n', hidden=True) if controls else ""), []
    cards = "".join(_songbook_card(conn, cfg, overrides, book, controls) for book in books)
    body = f'<div class="sb-list">\n{cards}</div>\n'
    return _songbooks_wrap(str(len(books)), body), [{"name": b.name, "songs": len(b.songs)} for b in books]


def _songbooks_wrap(count: str, body: str, *, hidden: bool = False) -> str:
    return (
        f'<section class="songbooks" id="songbooks" aria-labelledby="songbooks-title"{" hidden" if hidden else ""}>'
        '\n<details>\n<summary><span class="sb-icon" aria-hidden="true">♪</span>'
        '<span id="songbooks-title">Songbooks</span>'
        f' <span class="n">{count}</span></summary>\n{body}</details>\n</section>\n'
    )


_SONGBOOK_FILES = (("songbook.html", "Songbook for the phone"), ("songbook.pdf", "PDF"), ("songbook.cho", "ChordPro"))


def _songbook_card(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, book: Any,
                   controls: WebControls | None) -> str:
    from caracole.songbook import FOLDER, songbook_entries, songs_to_get

    esc = html_text.escape
    entries = songbook_entries(conn, cfg.library_dir, overrides, book)
    missing = sum(1 for e in entries if e.cho is None)
    songs = f"{len(entries)} song{'' if len(entries) == 1 else 's'}"
    if missing:
        songs += f", {missing} without a sheet"
    names = _file_names(cfg.library_dir / FOLDER / book.folder)
    base = f"{FOLDER}/{quote(book.folder, safe='')}"
    links = [f'<a class="btn{" primary" if n == 0 else ""}" href="{base}/{quote(name)}">{label}</a>'
             for n, (name, label) in enumerate(f for f in _SONGBOOK_FILES if f[0] in names)]
    # On caracole serve, its songs without a sheet looked up now, one lookup each, then the songbook made again.
    getting = {song.id for song in songs_to_get(entries, overrides)} if controls is not None else set()
    to_get = len(getting)
    get_form = _songbook_form(
        "get", book.name, controls,
        '<button class="btn" type="submit" title="Looks each one up now, as caracole get does, then makes the '
        f'songbook again">{"Get the missing song now" if to_get == 1 else f"Get the {to_get} missing songs now"}'
        "</button>") if to_get and controls is not None else ""
    if links:
        files = f'<div class="actions">{"".join(links)}{get_form}</div>\n'
    else:
        files = ('<p class="hint">Not made yet: caracole render, or caracole songbook render, makes its files.</p>\n'
                 + (f'<div class="actions">{get_form}</div>\n' if get_form else ""))
    rows = []
    for n, entry in enumerate(entries, start=1):
        title, artist = esc(entry.title), esc(entry.artist)
        why = f'<span class="why">missing: {esc(entry.missing)}</span>' if entry.missing else ""
        tools = _songbook_tools(book.name, entry.text, entry.title, n, len(entries), controls) if controls else ""
        song = f' data-song="{entry.song.id}"' if controls is not None and entry.song is not None else ""
        if entry.song is not None and entry.song.id in getting:  # Get the missing songs now looks it up
            song += " data-get"
        rows.append(f'<li{" class=\"missing\"" if entry.missing else ""}{song}><span class="sb-n">{n}</span>'
                    f'<span class="sb-names"><span class="t">{title}</span> <span class="a">{artist}</span>{why}</span>'
                    f"{tools}</li>")
    if controls is not None:
        more = (
            '<details class="sb-more"><summary>Rename or delete</summary>\n'
            + _songbook_form("rename", book.name, controls,
                             f'<label class="f">New name<input name="new" required maxlength="80" autocomplete="off" '
                             f'value="{esc(book.name, quote=True)}"></label>'
                             '<button class="btn" type="submit">Rename</button>')
            + _songbook_form("delete", book.name, controls,
                             '<label class="sb-sure"><input type="checkbox" required> Delete it, and the files '
                             'caracole made of it</label>'
                             f'<button class="btn" type="submit">Delete {esc(book.name)}</button>')
            + "</details>\n"
        )
    else:
        more = ('<p class="hint">Change it with <code>caracole songbook add</code>, <code>remove</code>, '
                "<code>move</code>, <code>rename</code> or <code>delete</code>, or in songbooks.toml.</p>\n")
    return (
        f'<article class="sb-card" data-songbook="{esc(book.name, quote=True)}">\n'
        f'<div class="sb-head"><h2>{esc(book.name)}</h2><p class="hint">{songs}</p></div>\n'
        + files + f'<ol class="sb-songs">\n{chr(10).join(rows)}\n</ol>\n' + more + "</article>\n"
    )


def _songbook_form(action: str, name: str, controls: WebControls, inner: str, **fields: Any) -> str:
    """A form that posts to caracole serve's /songbook/<action>, with its token and the songbook's name."""
    esc = html_text.escape
    hidden = "".join(f'<input type="hidden" name="{key}" value="{esc(str(value), quote=True)}">'
                     for key, value in (("csrf", controls.csrf), ("name", name), *fields.items()))
    return f'<form method="post" action="/songbook/{action}">{hidden}{inner}</form>'


def _songbook_tools(name: str, entry: str, title: str, n: int, total: int, controls: WebControls) -> str:
    """A song's buttons on the served page: up, down, and out of the songbook."""
    esc = html_text.escape
    tools = []
    if n > 1:
        tools.append(_songbook_form("move", name, controls,
                                    f'<button class="sb-btn" type="submit" aria-label="Move {esc(title)} up" '
                                    'title="Up">↑</button>', song=entry, position=n - 1))
    if n < total:
        tools.append(_songbook_form("move", name, controls,
                                    f'<button class="sb-btn" type="submit" aria-label="Move {esc(title)} down" '
                                    'title="Down">↓</button>', song=entry, position=n + 1))
    tools.append(_songbook_form("remove", name, controls,
                                f'<button class="sb-btn" type="submit" aria-label="Take {esc(title)} out of '
                                f'{esc(name)}" title="Take it out">×</button>', song=entry))
    return f'<span class="sb-tools">{"".join(tools)}</span>'
