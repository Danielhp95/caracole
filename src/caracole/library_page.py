"""Library/index.html: browse and search the whole library, on a phone or a laptop (A7).

One self-contained file, rewritten wherever ``_todo.md`` is. It opens from the
Syncthing folder with no server: it loads nothing from the network (a
Content-Security-Policy with the hashes of its one script and one stylesheet
makes the browser enforce that), and it links to each song's files by
relative paths.

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
(``ugHit``, ``artistHit``, ``siteHit``), for this page's search of the sites
and the lookup page alike.

**One bar.** The search box filters your songs as you type, here, asking
nothing. Enter, or Search all, searches the sites too. The file can ask
nothing of anyone: it shows the ``caracole search`` line to run, with Copy,
above your songs (in their empty list when none match). Served, the results
take the grid's place until Escape: your songs that match, as their own rows,
then the Ultimate Guitar index's songs and artists, gtptabs.com's pages and
MuseScore's (``GET /api/search``, a moment after the last key, the newest
query alone, the sites left out said with why), each with Get it (``POST
/lookup``), whose request's line shows in the result's own row. Enter never
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

import base64
import hashlib
import html as html_text
import json
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
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    # The page caracole serve serves may also ask it how its requests go (connect-src); the file can't.
    csp = (_CSP.replace("__FORMS__", "'self'; connect-src 'self'") if controls is not None
           else _CSP.replace("__FORMS__", "'none'"))
    return (
        _HEAD.replace("__CSP__", csp).replace("__STYLE__", _PAGE_STYLE)
        + _BODY.replace("__NAV__", _nav(controls)).replace("__REQUEST__", _request_form(controls))
        .replace("__REQUESTED__", _requested(controls)).replace("__SONGBOOKS__", books)
        + f'<script type="application/json" id="songs">{payload}</script>\n'
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
        elif song.match_decision == "not_found" and card["status"] != "ignored":
            card["notFound"] = True


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

# Shared with the pages caracole serve writes itself (caracole/web/): colours, type, buttons. --border is
# the soft line of cards and dividers; --control-edge, the edge that tells a field, a menu or a box from
# what is around it, at 3:1 or more against every background (WCAG 1.4.11). On a touch screen
# (pointer: coarse) every button is a thumb's target, 44 px; a mouse keeps the compact ones.
BASE_STYLE = """
:root {
  color-scheme: light dark;
  --bg: #f6f5f1;
  --surface: #ffffff;
  --raised: #f1efea;
  --text: #1d1c1a;
  --muted: #645f57;
  --border: #e3dfd6;
  --border-strong: #cdc7bb;
  --control-edge: #8d877c;
  --accent: #b4441e;
  --accent-hover: #9a3915;
  --on-accent: #ffffff;
  --focus: #1f6feb;
  --shadow: 0 1px 2px rgb(31 30 28 / 6%), 0 6px 18px rgb(31 30 28 / 5%);
  --found: #1d6b43; --found-bg: #def1e5;
  --wanted: #7a4c00; --wanted-bg: #fbeed2;
  --ignored: #5c5c5c; --ignored-bg: #ebebeb;
  --review: #5b34a8; --review-bg: #ece4fa;
  --auto: #0e5c6e; --auto-bg: #dbf0f5;
  --failed: #a3261b; --failed-bg: #fbe1dd;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #131312;
    --surface: #1c1b1a;
    --raised: #282725;
    --text: #edebe7;
    --muted: #aaa59c;
    --border: #34322f;
    --border-strong: #4b4844;
    --control-edge: #7a756e;
    --accent: #f0895c;
    --accent-hover: #f5a47f;
    --on-accent: #1b0e07;
    --focus: #6ea8fe;
    --shadow: none;
    --found: #83d6a6; --found-bg: #133222;
    --wanted: #f2c46e; --wanted-bg: #36290d;
    --ignored: #b8b8b8; --ignored-bg: #2d2d2d;
    --review: #c6adff; --review-bg: #2b2047;
    --auto: #8fd6e8; --auto-bg: #102f37;
    --failed: #ff9d92; --failed-bg: #3d1713;
  }
}
*, *::before, *::after { box-sizing: border-box; }
[hidden] { display: none !important; }
html { -webkit-text-size-adjust: 100%; text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 16px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", "Helvetica Neue", Arial,
    "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", sans-serif;
}
a { color: inherit; }
:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
code { font: .9em ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; padding: 1px 5px; border-radius: 6px;
  background: var(--raised); overflow-wrap: anywhere; }
.page { max-width: 1320px; margin: 0 auto; padding: 0 16px 56px; }
.masthead { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 12px 16px;
  padding: 20px 0 8px; }
.masthead h1 { margin: 0; font-size: 1.6rem; line-height: 1.15; letter-spacing: -0.015em; }
.app { margin: 0 0 2px; color: var(--accent); font-size: .78rem; font-weight: 700; letter-spacing: .1em;
  text-transform: uppercase; }
.app a { text-decoration: none; }
.links { display: flex; flex-wrap: wrap; gap: 8px; }
.navlink { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; padding: 0 16px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface); text-decoration: none; font-weight: 600; }
.navlink:hover { border-color: var(--border-strong); }
.navlink .n { min-width: 22px; padding: 0 7px; border-radius: 999px; background: var(--accent); color: var(--on-accent);
  font-size: .78rem; line-height: 22px; text-align: center; font-variant-numeric: tabular-nums; }
.btn { display: inline-flex; align-items: center; justify-content: center; min-height: 40px; padding: 0 13px;
  border-radius: 11px; border: 1px solid var(--border); background: var(--raised); color: var(--text); font: inherit;
  font-size: .9rem; font-weight: 550; text-decoration: none; overflow-wrap: anywhere; cursor: pointer; }
.btn:hover { border-color: var(--border-strong); }
.btn:disabled { color: var(--muted); border-style: dashed; cursor: default; }
.btn.primary { min-height: 44px; background: var(--accent); border-color: var(--accent); color: var(--on-accent);
  font-weight: 650; }
.btn.primary:hover { background: var(--accent-hover); border-color: var(--accent-hover); }
.btn.small { min-height: 36px; padding: 0 11px; font-size: .85rem; }
.badge { padding: 2px 9px; border-radius: 999px; font-size: .75rem; font-weight: 650; white-space: nowrap; }
.badge.found, .badge.done { color: var(--found); background: var(--found-bg); }
.badge.wanted, .badge.queued, .badge.running { color: var(--wanted); background: var(--wanted-bg); }
.badge.ignored { color: var(--ignored); background: var(--ignored-bg); }
.badge.review { color: var(--review); background: var(--review-bg); }
.badge.auto { color: var(--auto); background: var(--auto-bg); }
.badge.failed { color: var(--failed); background: var(--failed-bg); }
.f { display: grid; gap: 4px; min-width: 0; color: var(--muted); font-size: .85rem; font-weight: 600; }
.f em { font-style: normal; font-weight: 500; }
.f input { width: 100%; height: 44px; padding: 0 12px; border-radius: 10px; border: 1px solid var(--control-edge);
  background: var(--bg); color: var(--text); font: inherit; font-size: 1rem; font-weight: 400; }
.f input:focus { border-color: var(--focus); outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--focus) 30%, transparent); }
.footer { margin-top: 40px; color: var(--muted); font-size: .8rem; }
.visually-hidden { position: absolute; width: 1px; height: 1px; margin: -1px; overflow: hidden; clip: rect(0 0 0 0);
  white-space: nowrap; border: 0; }
@media (min-width: 720px) {
  .page { padding: 0 24px 64px; }
  .masthead { padding-top: 32px; }
  .masthead h1 { font-size: 2.1rem; }
}
@media (pointer: coarse) {
  .btn, .btn.small { min-height: 44px; }
}
@media (prefers-reduced-motion: no-preference) {
  .btn, .navlink { transition: background-color .12s, border-color .12s; }
}
"""

# The picker of a song in review's candidates: on the cards, and on the pages caracole serve writes
# itself (web/pages.py), which build the same markup.
PICKER_STYLE = """
.picker { min-width: 0; }
.picker > summary ~ * { margin-top: 8px; }
.picker > summary { display: inline-flex; align-items: center; width: fit-content; max-width: 100%; list-style: none;
  cursor: pointer; }
.picker > summary::-webkit-details-marker { display: none; }
.picker > summary:not(.btn) { min-height: 32px; color: var(--review); font-size: .88rem; font-weight: 650; }
.picker > summary:not(.btn)::before { content: "›"; display: inline-block; width: 1em; font-size: 1.15rem;
  line-height: 1; text-align: center; }
.picker[open] > summary:not(.btn)::before { transform: rotate(90deg); }
.picker > summary.btn { border-color: var(--review); color: var(--review); background: var(--review-bg); }
.picker-n { margin-left: .35em; font-weight: 500; }
.pick-form { display: grid; gap: 10px; margin: 0; }
.choices { display: grid; gap: 6px; min-width: 0; margin: 0; padding: 0; border: 0; list-style: none; }
.choices legend { margin: 0 0 6px; padding: 0; font-size: .92rem; font-weight: 650; overflow-wrap: anywhere; }
.choice { display: flex; align-items: center; gap: 8px; min-width: 0; padding: 4px 8px 4px 10px;
  border: 1px solid var(--border); border-radius: 12px; background: var(--raised); }
.choice:has(input:checked) { border-color: var(--accent); }
.choice-pick { display: flex; flex: 1; align-items: center; gap: 10px; min-width: 0; min-height: 44px; }
label.choice-pick { cursor: pointer; }
.choice-pick input { flex: none; width: 20px; height: 20px; margin: 0; accent-color: var(--accent); }
.choice-text { display: grid; gap: 1px; min-width: 0; padding: 4px 0; }
.choice-name { font-size: .92rem; font-weight: 600; overflow-wrap: anywhere; }
.choice-why { color: var(--muted); font-size: .8rem; overflow-wrap: anywhere; }
.choice-link { flex: none; display: inline-flex; align-items: center; min-height: 36px; padding: 0 10px;
  border-radius: 10px; border: 1px solid var(--border); background: var(--surface); font-size: .82rem;
  font-weight: 600; text-decoration: none; }
.choice-link:hover { border-color: var(--border-strong); }
.pick-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 20px; }
.pick-check { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; font-weight: 600;
  cursor: pointer; }
.pick-check input { width: 20px; height: 20px; margin: 0; accent-color: var(--accent); }
.pick-hint { margin: 0; color: var(--muted); font-size: .82rem; }
@media (pointer: coarse) {
  .picker > summary:not(.btn), .choice-link { min-height: 44px; }
}
"""

# A list's rows and the marks of where each thing came from: index.html's Rows view, and the results of
# caracole serve's lookup page (web/lookup_page.py), which builds them with ROWS_SCRIPT.
ROWS_STYLE = """
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
.actions form { margin: 0; }
.subhead { margin: 2px 0 -2px; color: var(--muted); font-size: .75rem; font-weight: 650; letter-spacing: .06em;
  text-transform: uppercase; }
.source { flex: none; display: inline-grid; place-items: center; width: 16px; height: 16px; border-radius: 4px;
  vertical-align: -3px; }
/* A site with no icon (yet), or no site: a badge a little bigger than an icon, so its letters read. */
.source.letters, .source.glyph { width: 20px; height: 20px; border: 1px solid var(--border-strong);
  border-radius: 5px; background: var(--raised); color: var(--text); font-size: 10px; font-weight: 750;
  letter-spacing: -.02em; line-height: 1; vertical-align: -5px; }
.source.glyph { font-size: 12px; font-weight: 600; }
.btn.sourced { gap: 7px; }
.btn.sourced .source { order: -1; }
.badges .source { align-self: center; }
/* An artist's name that shows that artist's songs alone: a button, the name and a filter's mark (a funnel),
   so that it shows it is one without a pointer to hover it. */
.artist { display: inline-flex; align-items: center; gap: 5px; min-width: 0; margin: 0; padding: 0; border: 0;
  background: none; color: var(--muted); font: inherit; font-size: .9rem; text-align: left; cursor: pointer; }
.artist-name { min-width: 0; overflow-wrap: anywhere; }
.artist:hover { color: var(--text); }
.artist:hover .artist-name { text-decoration: underline; text-underline-offset: 2px; }
.filter-mark { flex: none; width: .7em; height: .75em; background: currentColor; opacity: .8;
  clip-path: polygon(0 0, 100% 0, 60% 48%, 60% 90%, 40% 100%, 40% 48%); }
/* A title that opens the sheet: the heading as it was, underlined under the pointer. */
.title-link { display: block; width: fit-content; max-width: 100%; color: inherit; text-decoration: none; }
.title-link:hover > h2 { text-decoration: underline; text-decoration-thickness: 1px; text-underline-offset: 3px; }
.rows { margin-top: 10px; border: 1px solid var(--border); border-radius: 14px; background: var(--surface);
  box-shadow: var(--shadow); }
/* Below 900px a row is two lines: the title and the main action, then the artist with the key and
   badges (.row-sub, as wide as the row but for the "⋯" button), the artist at least 3rem wide. */
.row { --row-more: 34px; display: grid; grid-template-columns: 20px minmax(0, 1fr) auto var(--row-more);
  grid-template-areas: "src title act act" ". sub sub more"; align-items: center; gap: 2px 10px;
  min-width: 0; padding: 8px 10px 8px 12px; border-top: 1px solid var(--border); scroll-margin-top: 84px; }
.row:first-child { border-top: 0; }
.row[data-status="ignored"] { opacity: .7; }
.row > .source { grid-area: src; justify-self: center; }
.row-title { grid-area: title; min-width: 0; margin: 0; overflow: hidden; font-size: .98rem; line-height: 1.3;
  white-space: nowrap; text-overflow: ellipsis; }
/* A row's title link fills its line: as easy to hit as the button beside it. */
.row > .title-link { grid-area: title; display: flex; align-items: center; align-self: stretch; width: auto;
  min-width: 0; }
.row-sub { grid-area: sub; display: flex; flex-wrap: wrap; align-items: center; gap: 2px 8px; min-width: 0; }
.row-artist { flex: 1 1 3rem; min-width: 0; max-width: max-content; overflow: hidden; color: var(--muted);
  font-size: .86rem; white-space: nowrap; text-overflow: ellipsis; }
.row-artist .artist-name { overflow: hidden; text-overflow: ellipsis; }
.row-meta { flex: 0 1 auto; display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center;
  gap: 4px 6px; min-width: 0; margin: 0 0 0 auto; color: var(--muted); font-size: .82rem; }
.row-key { color: var(--text); font-weight: 650; font-variant-numeric: tabular-nums; }
.row-action { grid-area: act; justify-self: end; display: flex; min-width: 0; }
.row-action form { margin: 0; }
.row .btn { min-height: 34px; padding: 0 11px; font-size: .85rem; }
.row-busy { display: inline-flex; align-items: center; min-height: 34px; color: var(--wanted); font-size: .85rem;
  font-weight: 650; text-underline-offset: 2px; }
.row .btn.row-pick { border-color: var(--review); color: var(--review); background: var(--review-bg); }
/* A request's line: a line of the row's own, under the title, the artist and the button. */
.row > .progress { grid-column: 2 / -1; font-size: .85rem; }
.row-panel .foot { margin-top: 2px; }
.row-more { grid-area: more; justify-self: end; display: grid; place-items: center; width: var(--row-more); height: 30px;
  padding: 0; border: 1px solid transparent; border-radius: 9px; background: transparent; color: var(--muted);
  font: inherit; font-size: 1.15rem; line-height: 1; cursor: pointer; }
.row-more:hover, .row-more[aria-expanded="true"] { border-color: var(--border); background: var(--raised);
  color: var(--text); }
.row-panel { grid-column: 1 / -1; display: grid; gap: 4px; padding: 4px 0 6px 30px; }
.row-panel .note { margin: 0; }
.row-group .subhead { margin: 4px 0 6px; }
/* An Ultimate Guitar song's versions, under its "⋯": each a button, with a link to look at it on UG. */
.versions { display: flex; flex-wrap: wrap; gap: 6px; margin: 0; padding: 0; list-style: none; }
.version { display: inline-flex; align-items: center; gap: 4px; }
.on-ug { color: var(--muted); font-size: .78rem; }
@media (min-width: 900px) {
  .row { grid-template-columns: 20px minmax(0, 1.3fr) minmax(0, 1fr) minmax(0, 14rem) 9.5rem var(--row-more);
    grid-template-areas: "src title artist meta act more"; padding: 3px 10px 3px 12px; }
  .row-sub { display: contents; }
  .row-artist { grid-area: artist; justify-self: start; max-width: 100%; }
  .row-meta { grid-area: meta; margin: 0; }
  .row .btn { min-height: 30px; }
  .row-more { height: 28px; }
}
/* A thumb's targets: a row's button, its "⋯" and its artist (on a phone the title's line and the artist's,
   two thumbs high), and a version's page on UG beside its button; a mouse keeps the compact rows. */
@media (pointer: coarse) {
  .row { --row-more: 44px; padding-top: 4px; padding-bottom: 4px; }
  .row .btn, .row-busy { min-height: 44px; }
  .row-more { height: 44px; }
  .artist { min-width: 44px; min-height: 44px; }
  .on-ug { display: inline-flex; align-items: center; justify-content: center; min-width: 44px; min-height: 44px; }
}
"""

_STYLE = BASE_STYLE + PICKER_STYLE + """
:root {
  --h0: #8a3313; --h0-bg: #f6ded3;
  --h1: #7a4c00; --h1-bg: #f7e8c7;
  --h2: #4c5a12; --h2-bg: #e6edcf;
  --h3: #1d6b43; --h3-bg: #d7eedf;
  --h4: #0e5c5a; --h4-bg: #d3eceb;
  --h5: #23508f; --h5-bg: #dbe6f7;
  --h6: #5b34a8; --h6-bg: #e8e0f7;
  --h7: #8e2a52; --h7-bg: #f6dde6;
}
@media (prefers-color-scheme: dark) {
  :root {
    --h0: #f4b298; --h0-bg: #3d2117;
    --h1: #f2c46e; --h1-bg: #36290d;
    --h2: #c9d98a; --h2-bg: #2a3110;
    --h3: #83d6a6; --h3-bg: #133222;
    --h4: #7fd3cf; --h4-bg: #0f302f;
    --h5: #9dbff2; --h5-bg: #172843;
    --h6: #c6adff; --h6-bg: #2b2047;
    --h7: #f2a3c1; --h7-bg: #3b1828;
  }
}
.summary { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 0; padding: 0; list-style: none; }
/* The library's header: caracole and the pages on one line, the title with its numbers beside it on the next. */
.masthead.lib { display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: "app links" "title title";
  align-items: center; gap: 2px 12px; padding: 10px 0 6px; }
.masthead.lib .app { grid-area: app; margin: 0; }
.masthead.lib .links { grid-area: links; flex-wrap: nowrap; }
.masthead.lib .navlink { min-height: 40px; padding: 0 13px; font-size: .9rem; }
.title-line { grid-area: title; display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 14px; min-width: 0; }
.title-line .summary { gap: 0; margin: 0; }
.title-line .stat { padding: 0; background: none; }
.title-line .stat + .stat::before { content: "·"; margin: 0 6px; color: var(--muted); }
.stat { padding: 3px 10px; border-radius: 999px; background: var(--raised); color: var(--muted); font-size: .82rem;
  font-variant-numeric: tabular-nums; }
.stat b { color: var(--text); font-weight: 650; }
.request { margin: 8px 0 0; border: 1px solid var(--border); border-radius: 16px; background: var(--surface); }
.request > summary { display: flex; align-items: center; gap: 10px; min-height: 52px; padding: 0 16px; cursor: pointer;
  font-weight: 650; list-style: none; }
.request > summary::-webkit-details-marker { display: none; }
.plus { display: inline-grid; place-items: center; width: 26px; height: 26px; border-radius: 8px;
  background: var(--accent); color: var(--on-accent); font-size: 1.15rem; line-height: 1; }
.plus span { display: inline-block; }
.request[open] > summary .plus span { transform: rotate(45deg); }  /* the + turns into a ×, the square stays */
.request-form { display: grid; gap: 12px; padding: 0 16px 16px; }
.fields { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 220px), 1fr)); }
.request-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 20px; }
.check { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; font-weight: 600; cursor: pointer; }
.check input { width: 20px; height: 20px; margin: 0; accent-color: var(--accent); }
.hint { margin: 0; color: var(--muted); font-size: .85rem; }
/* Kept at the top, side to side across the page, with an edge once the page scrolls under it (.stuck). */
.searchbar { position: sticky; top: 0; z-index: 2; margin: 0 -16px; padding: 10px 16px 8px; background: var(--bg); }
.searchbar.stuck { box-shadow: 0 1px 0 var(--border-strong), 0 8px 16px -10px rgb(0 0 0 / 35%); }
.bar-edge { height: 0; }
.field { position: relative; }
.field input {
  width: 100%; height: 50px; padding: 0 48px 0 16px; border-radius: 14px; border: 1px solid var(--border);
  background: var(--surface); color: var(--text); font: inherit; font-size: 1rem; -webkit-appearance: none; appearance: none;
}
.field input::placeholder { color: var(--muted); opacity: 1; }
.field input::-webkit-search-cancel-button { -webkit-appearance: none; appearance: none; }
.field input:focus { border-color: var(--focus); outline: none; box-shadow: 0 0 0 3px color-mix(in srgb, var(--focus) 30%, transparent); }
.clear { position: absolute; top: 3px; right: 3px; width: 44px; height: 44px; border: 0; border-radius: 12px;
  background: transparent; color: var(--muted); font-size: 1.5rem; line-height: 1; cursor: pointer; }
.bar-row { display: flex; align-items: center; gap: 8px; }
.bar-row .field { flex: 1; min-width: 0; }
.btn.all { flex: none; min-height: 50px; padding: 0 16px; border-radius: 14px; white-space: nowrap; }
/* One line, its height kept: what Enter does, or how the search of the sites goes. */
.bar-status { min-height: 1.35em; margin: 6px 2px 0; overflow: hidden; color: var(--muted); font-size: .8rem;
  line-height: 1.35; white-space: nowrap; text-overflow: ellipsis; }
.searching-all .toolbar, .searching-all .jump, .searching-all .count, .searching-all .list { display: none; }
.waiting-sites .results .request, .waiting-sites .footer { display: none; }
.results-head { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; margin: 4px 0 0; }
.results .group { margin: 18px 0 0; color: var(--muted); font-size: .78rem; font-weight: 700; letter-spacing: .08em;
  text-transform: uppercase; }
.results .rows { margin-top: 6px; }
.all-mine, .more-songs { margin: 10px 0 0; }
.artist-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 6px 12px;
  margin: 14px 0 0; }
.artist-head h2 { margin: 0; font-size: 1.2rem; overflow-wrap: anywhere; }
.artist-head h2:focus { outline: none; }
.skipped { margin: 16px 0 0; color: var(--muted); font-size: .85rem; }
.index-hint { max-width: 72ch; margin-top: 10px; white-space: pre-wrap; }
.results .request { margin-top: 20px; }
.file-answer { display: grid; gap: 8px; max-width: 72ch; margin: 6px 0 12px; padding: 12px 14px;
  border: 1px solid var(--border); border-radius: 14px; background: var(--surface); font-size: .92rem; }
.file-answer p { margin: 0; }
.command { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.command code { flex: 1 1 240px; padding: 8px 10px; user-select: all; }
.empty + .btn.primary { margin-top: 4px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 12px; }
/* One row of buttons that scrolls sideways on a phone; Key, Sort and the view under View there. */
.chips { display: flex; flex: 1 1 0; flex-wrap: nowrap; gap: 8px; min-width: 0; margin: -4px; padding: 4px;
  overflow-x: auto; scrollbar-width: none; }
.chips::-webkit-scrollbar { display: none; }
/* Buttons out of sight: the row fades where it goes on, so it says it scrolls (no fade, no more). */
.chips.more-end { --fade-start: #000; --fade-end: transparent; }
.chips.more-start { --fade-start: transparent; }
.chips.more-start, .chips.more-end {
  -webkit-mask-image: linear-gradient(to right, var(--fade-start, #000), #000 28px, #000 calc(100% - 28px), var(--fade-end, #000));
  mask-image: linear-gradient(to right, var(--fade-start, #000), #000 28px, #000 calc(100% - 28px), var(--fade-end, #000)); }
.chip { flex: none; }
.view-panel { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 8px 12px; }
.toolbar .view-toggle { display: none; }
.view-toggle::after { content: "▾"; color: var(--muted); }
.view-toggle[aria-expanded="true"]::after { content: "▴"; }
.chip { display: inline-flex; align-items: center; gap: 6px; min-height: 40px; padding: 0 14px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface); color: var(--text); font: inherit; font-size: .9rem;
  cursor: pointer; }
.chip .n { color: var(--muted); font-variant-numeric: tabular-nums; }
.chip[aria-pressed="true"] { background: var(--text); border-color: var(--text); color: var(--bg); }
.chip[aria-pressed="true"] .n { color: inherit; opacity: .75; }
.chip.person { border-color: var(--accent); color: var(--accent); font-weight: 600; }
.sort { display: inline-flex; align-items: center; gap: 8px; margin-left: auto; color: var(--muted); font-size: .9rem; }
.controls { display: flex; flex: none; justify-content: flex-end; gap: 8px; }
.sort select { min-height: 40px; padding: 0 10px; border-radius: 10px; border: 1px solid var(--control-edge);
  background: var(--surface); color: var(--text); font: inherit; font-size: .9rem; }
.jump { display: flex; gap: 2px; margin: 10px 0 0; padding: 2px 0; overflow-x: auto; scrollbar-width: none; }
.jump::-webkit-scrollbar { display: none; }
.jump button { flex: none; min-width: 36px; height: 36px; padding: 0 8px; border: 0; border-radius: 10px;
  background: transparent; color: var(--muted); font: inherit; font-size: .9rem; font-weight: 650; cursor: pointer; }
.jump button:hover { background: var(--raised); color: var(--text); }
.count { margin: 8px 0 0; color: var(--muted); font-size: .85rem; }
.grid { display: grid; gap: 12px; margin-top: 10px;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr)); }
.card { display: flex; flex-direction: column; gap: 10px; min-width: 0; padding: 14px; border: 1px solid var(--border);
  border-radius: 16px; background: var(--surface); box-shadow: var(--shadow); scroll-margin-top: 84px; }
.card[data-status="ignored"] { opacity: .7; }
/* A song caracole removed while the page was open: it says so, and nothing more, until the page is loaded again. */
.card.gone { border-style: dashed; box-shadow: none; }
.row.gone { align-content: start; }  /* kept as tall as it was: its lines stay where they were */
.gone h2 { color: var(--muted); }
.head { display: flex; align-items: flex-start; gap: 12px; }
.mono { flex: none; display: grid; place-items: center; width: 42px; height: 42px; border-radius: 12px;
  font-size: .95rem; font-weight: 700; letter-spacing: .02em; color: var(--h0); background: var(--h0-bg); }
.hue-1 { color: var(--h1); background: var(--h1-bg); }
.hue-2 { color: var(--h2); background: var(--h2-bg); }
.hue-3 { color: var(--h3); background: var(--h3-bg); }
.hue-4 { color: var(--h4); background: var(--h4-bg); }
.hue-5 { color: var(--h5); background: var(--h5-bg); }
.hue-6 { color: var(--h6); background: var(--h6-bg); }
.hue-7 { color: var(--h7); background: var(--h7-bg); }
.names { flex: 1; min-width: 0; }
.card h2 { margin: 0; font-size: 1.05rem; line-height: 1.3; overflow-wrap: anywhere; }
/* Under the title, which keeps its line: the artist, then the badges, at the end of its line or under it. */
.byline { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 10px; margin-top: 2px; }
.badges { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 6px; min-width: 0;
  margin-left: auto; }
.facts { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 0; color: var(--muted); font-size: .85rem; }
.facts .key, .facts .transpose { color: var(--text); font-weight: 600; }
.note { margin: 0; color: var(--review); font-size: .85rem; }
.progress { margin: 0; color: var(--muted); font-size: .9rem; font-weight: 600; overflow-wrap: anywhere; }
.progress::before { content: ""; display: inline-block; width: 8px; height: 8px; margin-right: 7px;
  border-radius: 50%; background: currentColor; vertical-align: .05em; }
.progress[data-tone="queued"], .progress[data-tone="running"], .progress[data-tone="waiting"] { color: var(--wanted); }
.progress[data-tone="ready"] { color: var(--found); }
.progress[data-tone="review"] { color: var(--review); }
.progress[data-tone="failed"] { color: var(--failed); }
.progress a { padding: 6px 0; color: inherit; text-underline-offset: 2px; }
.progress .dot { margin: 0 .4em; opacity: .6; }
/* A removal counting down: its seconds, Undo, and what goes, under it. */
.progress .left { font-variant-numeric: tabular-nums; }
.progress .undo { min-height: 32px; margin: 0; padding: 0 6px; border: 0; border-radius: 8px; background: none;
  color: inherit; font: inherit; font-weight: 700; text-decoration: underline; text-underline-offset: 2px;
  cursor: pointer; }
.progress .undo:hover { background: var(--raised); }
.progress .goes { display: block; margin-top: 2px; color: var(--muted); font-size: .85rem; font-weight: 500; }
.requested { margin-top: 14px; }
.requested .grid { margin-top: 6px; }
.card .by { margin: 2px 0 0; color: var(--muted); font-size: .9rem; overflow-wrap: anywhere; }
/* The requests, folded to a pill in the corner over the page's margin, on every width; opened, a list above it. */
.tray { position: fixed; z-index: 3; right: 16px; bottom: calc(16px + env(safe-area-inset-bottom)); display: flex;
  flex-direction: column-reverse; width: max-content; max-width: calc(100vw - 32px); border: 1px solid var(--border-strong);
  border-radius: 999px; background: var(--surface); box-shadow: 0 8px 28px rgb(0 0 0 / 18%); }
.tray.open { width: min(26rem, calc(100vw - 32px)); border-radius: 16px; }
.tray-head { display: flex; align-items: center; gap: 2px; padding: 2px 4px; }
.tray-toggle { flex: 1; min-width: 0; min-height: 44px; padding: 0 10px; border: 0; border-radius: 12px;
  background: none; color: var(--text); font: inherit; font-weight: 650; text-align: left; cursor: pointer; }
.tray-toggle::after { content: "▾"; display: inline-block; margin-left: 6px; color: var(--muted); }
.tray-toggle[aria-expanded="false"]::after { transform: rotate(180deg); }
.tray-all { display: inline-flex; align-items: center; min-height: 44px; padding: 0 8px; color: var(--muted);
  font-size: .85rem; font-weight: 600; }
.tray-close { flex: none; width: 44px; height: 44px; border: 0; border-radius: 12px; background: none;
  color: var(--muted); font-size: 1.4rem; line-height: 1; cursor: pointer; }
.tray-list { display: grid; gap: 8px; max-height: min(40vh, 18rem); margin: 0; padding: 12px 14px 4px;
  overflow-y: auto; list-style: none; }
.tray-list li { display: grid; gap: 1px; min-width: 0; }
.tray-song { overflow: hidden; font-size: .9rem; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.tray .progress { font-size: .85rem; }
body.with-tray .page { padding-bottom: 88px; }
.youtube { margin: 0; color: var(--auto); font-size: .85rem; }
.more { margin-top: auto; padding-top: 6px; border-top: 1px solid var(--border); }
.more > summary { display: flex; align-items: center; gap: 4px; min-height: 32px; color: var(--muted);
  font-size: .85rem; font-weight: 600; list-style: none; cursor: pointer; }
.more > summary::-webkit-details-marker { display: none; }
.more > summary::before { content: "›"; display: inline-block; width: 1em; font-size: 1.15rem; line-height: 1;
  text-align: center; }
.more[open] > summary::before { transform: rotate(90deg); }
.more > .subhead { margin: 8px 0 6px; }
.more > summary + .actions { margin-top: 6px; }
.more + .more { margin-top: 0; }  /* Files, then Find it elsewhere: one fold under the other */
.foot { display: flex; justify-content: flex-end; margin-top: auto; }
.more + .foot { margin-top: 0; }
.foot form { margin: 0; }
.busy { margin: 0; color: var(--wanted); font-size: .88rem; font-weight: 600; }
.btn.quiet { background: transparent; border-color: transparent; color: var(--muted); }
.btn.quiet:hover { border-color: var(--border); color: var(--failed); }
.empty { margin: 32px 0 8px; font-size: 1.05rem; }
.empty-hint { margin: 0; color: var(--muted); }
.views { display: inline-flex; gap: 2px; padding: 2px; border: 1px solid var(--border); border-radius: 12px;
  background: var(--surface); }
.views button { min-height: 34px; padding: 0 12px; border: 0; border-radius: 9px; background: transparent;
  color: var(--muted); font: inherit; font-size: .88rem; font-weight: 600; cursor: pointer; }
.views button:hover { color: var(--text); }
.views button[aria-pressed="true"] { background: var(--text); color: var(--bg); }
""" + ROWS_STYLE + """.card, .list .row { scroll-margin-top: 108px; }  /* below the bar kept at the top */
@media (max-width: 719px) {
  .toolbar .view-toggle { display: inline-flex; }
  .view-panel { flex-basis: 100%; justify-content: flex-start; }
  .view-panel:not(.open) { display: none; }
  .view-panel .sort { margin-left: 0; }
}
@media (min-width: 720px) {
  .jump { flex-wrap: wrap; overflow: visible; }
  .searchbar { margin: 0 -24px; padding: 12px 24px 8px; }
  .masthead.lib { grid-template-areas: "app links" "title links"; align-items: end; padding: 28px 0 8px; }
  .chips { flex-wrap: wrap; overflow: visible; }
}
/* A thumb's targets: the pages' links, the chips and View, the menus, Cards/Rows, a card's folds and the
   letters. Every .btn has its 44 px from BASE_STYLE, and a row's from ROWS_STYLE. */
@media (pointer: coarse) {
  .masthead.lib .navlink, .more > summary, .chip, .sort select, .views button { min-height: 44px; }
  .progress .undo { min-width: 44px; min-height: 44px; }
  .jump button { min-width: 44px; height: 44px; }
  /* A card's title and its artist share the thumb's height between them: the title's target reaches up into
     the card's padding and down to the artist's name, which stands at the top of its own 44 px, so that a tap
     a little under the title opens the sheet and never filters the list. */
  .card .title-link { padding: 14px 0 8px; margin: -14px 0 -8px; }
  .card .byline { align-items: flex-start; margin-top: 8px; }
  .card .byline .artist { align-items: baseline; }
}
@media (prefers-reduced-motion: no-preference) {
  .plus span { transition: transform .15s; }
  .progress[data-tone="running"]::before { animation: pulse 1.2s ease-in-out infinite; }
}
@keyframes pulse { 50% { opacity: .25; } }
"""

ROWS_SCRIPT = r"""
// Where each thing came from, and a list's rows (``resultRow``): index.html's, and the results of
// caracole serve's lookup page (web/lookup_page.py), which runs this script before its own.
const caracoleRows = (icons) => {
  "use strict";
  const own = Object.prototype.hasOwnProperty;
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const listOf = (value) => (Array.isArray(value) ? value : []);
  const keyName = (key) => (/ minor$/.test(key) ? key : key + " major");
  // Its site's own icon, inlined as a data: URI, else its lettered badge; a glyph for the audio model
  // and the inbox (icons.py). Each is named for a screen reader: "from LaCuerda".
  const ICONS = icons && typeof icons === "object" ? icons : {};
  const PNG_URI = /^data:image\/png;base64,[A-Za-z0-9+/]+={0,2}$/;
  const sourceMark = (key) => {
    if (typeof key !== "string" || !key) return null;
    const info = own.call(ICONS, key) && ICONS[key] && typeof ICONS[key] === "object" ? ICONS[key] : {};
    const name = "from " + String(info.name || key);
    let mark;
    if (typeof info.src === "string" && PNG_URI.test(info.src)) {
      mark = el("img", "source");
      mark.setAttribute("src", info.src);
      mark.setAttribute("alt", name);
      mark.setAttribute("width", "16");
      mark.setAttribute("height", "16");
    } else {
      mark = el("span", info.glyph ? "source glyph" : "source letters",
        String(info.letters || key.slice(0, 2).toUpperCase()));
      mark.setAttribute("role", "img");
      mark.setAttribute("aria-label", name);
    }
    mark.title = name;
    mark.dataset.source = key;
    return mark;
  };
  const safeHref = (href, external) => {
    const value = String(href || "");
    if (external) return /^https?:/i.test(value) ? value : "#";
    return /^[a-z][a-z0-9+.-]*:/i.test(value) || value.startsWith("/") ? "#" : value;
  };
  const link = (item, cls, external) => {
    const a = el("a", cls, String(item.label || "") + (external ? " ↗" : ""));
    a.href = safeHref(item.href, external);
    if (external) {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    }
    const mark = sourceMark(item.source);  // after the label, so the link reads "Sheet PDF from LaCuerda"
    if (mark) {
      a.classList.add("sourced");
      a.appendChild(mark);
    }
    return a;
  };
  let rowSerial = 0;
  const isWeb = (href) => /^https?:/i.test(String(href || ""));
  // A title that opens what its card's or its row's main button opens: around the heading, so the heading
  // stays the song's name alone. Out of the Tab order: the button, which says what it opens, is the keyboard's.
  const titleLink = (href, heading) => {
    const external = isWeb(href);
    const a = el("a", "title-link");
    a.href = safeHref(href, external);
    if (external) {
      a.target = "_blank";
      a.rel = "noopener noreferrer";
    }
    a.tabIndex = -1;
    a.appendChild(heading);
    return a;
  };
  // An artist's name that shows that artist's songs alone (``whose``, for its title): a button, the name and a
  // filter's mark (a funnel, drawn by the stylesheet), which a screen reader skips.
  const artistFilter = (name, whose, onArtist, cls) => {
    const who = el("button", cls ? "artist " + cls : "artist");
    who.type = "button";
    who.title = "Show only " + whose + "'s songs";
    who.appendChild(el("span", "artist-name", name));
    const mark = el("span", "filter-mark");
    mark.setAttribute("aria-hidden", "true");
    who.appendChild(mark);
    who.addEventListener("click", onArtist);
    return who;
  };
  const shortKey = (key) => String(key).replace(/ minor$/, "m").replace(/ major$/, "");
  const linkGroup = (group) => {
    if (group instanceof Node) return group;
    const items = listOf(group && group.links).filter((item) => item && typeof item === "object");
    if (!items.length) return null;
    const box = el("div", "row-group");
    if (group.heading) box.appendChild(el("p", "subhead", group.heading));
    const line = el("div", "actions");
    for (const item of items) line.appendChild(link(item, "btn small", isWeb(item.href)));
    box.appendChild(line);
    return box;
  };
  const resultRow = (result) => {
    const r = result && typeof result === "object" ? result : {};
    const title = String(r.title || "");
    const artist = String(r.artist || "");
    const row = el("article", "row");
    row.tabIndex = -1;
    if (r.status) row.dataset.status = String(r.status);
    const heading = el("h2", "row-title", title);
    heading.title = title;
    row.appendChild(r.href ? titleLink(r.href, heading) : heading);
    // The artist and the key, the status and the badges: one wrapping line under the title on a phone,
    // where badges that don't fit go under the artist, never over it; their own columns on a desktop.
    const sub = el("div", "row-sub");
    if (artist && typeof r.onArtist === "function") {
      sub.appendChild(artistFilter(artist, artist, r.onArtist, "row-artist"));
    } else if (artist) {
      sub.appendChild(el("span", "row-artist", artist));
    }
    const meta = el("p", "row-meta");
    if (typeof r.key === "string" && r.key) {
      const said = String(r.keyText || "Key " + keyName(r.key));
      const key = el("span", "row-key");
      key.title = said;
      const shown = el("span", null, shortKey(r.key));
      shown.setAttribute("aria-hidden", "true");
      key.appendChild(shown);
      key.appendChild(el("span", "visually-hidden", said));
      meta.appendChild(key);
    }
    for (const badge of listOf(r.badges)) {
      if (badge && badge.text) meta.appendChild(el("span", "badge " + String(badge.kind || ""), badge.text));
    }
    if (r.facts) meta.appendChild(el("span", "row-facts", r.facts));
    if (meta.childNodes.length) sub.appendChild(meta);
    if (sub.childNodes.length) row.appendChild(sub);
    const mark = sourceMark(r.source);
    if (mark) row.appendChild(mark);
    const action = el("div", "row-action");
    const main = r.action instanceof Node ? r.action
      : r.action && typeof r.action === "object" ? link(r.action, "btn small primary", isWeb(r.action.href)) : null;
    if (main) action.appendChild(main);
    row.appendChild(action);
    const extra = listOf(r.more).map(linkGroup).filter(Boolean);
    if (extra.length) {
      const panel = el("div", "row-panel");
      rowSerial += 1;
      panel.id = "row-more-" + rowSerial;
      panel.hidden = true;
      for (const node of extra) panel.appendChild(node);
      const more = el("button", "row-more");
      more.type = "button";
      more.setAttribute("aria-expanded", "false");
      more.setAttribute("aria-controls", panel.id);
      more.title = "More for " + title;
      const dots = el("span", null, "⋯");
      dots.setAttribute("aria-hidden", "true");
      more.appendChild(dots);
      more.appendChild(el("span", "visually-hidden", "More for " + title));
      more.addEventListener("click", () => {
        const open = more.getAttribute("aria-expanded") !== "true";
        more.setAttribute("aria-expanded", String(open));
        panel.hidden = !open;
      });
      row.appendChild(more);
      row.appendChild(panel);
    }
    return row;
  };

  // --- the offline indexes' hits, as /api/search and /api/artist give them --------------------------
  // index.html's search of the sites and caracole serve's lookup page draw them alike: each is a row with
  // its site's mark. ``get(pick, display, row, button)`` is what a Get it does: ``pick`` is the form
  // POST /lookup takes (a song of yours by its id, else its artist and title; the UG song, the tab).
  const many = (n, word) => Number(n || 0).toLocaleString("en") + " " + word + (Number(n) === 1 ? "" : "s");
  const button = (label, cls, onclick, aria) => {
    const b = el("button", "btn " + (cls || "small"), label);
    b.type = "button";
    if (aria) b.setAttribute("aria-label", aria);
    b.addEventListener("click", onclick);
    return b;
  };
  const KINDS = { chords: "Chords", tabs: "Tab", "guitar-pro": "Guitar Pro", power: "Power Tab" };
  const COUNTED = { chords: "chords", tabs: "tabs", "guitar-pro": "Guitar Pro", power: "Power Tab" };
  const counts = (c) => Object.entries(c && typeof c === "object" ? c : {})
    .map(([kind, n]) => n + " " + (own.call(COUNTED, kind) ? COUNTED[kind] : kind)).join(" · ");
  // A song's sheet viewer or PDF, as its card opens it: a link of the library's, relative to the page.
  const opener = (files) => listOf(files).find((f) => f && f.primary && /[.](html|pdf)$/i.test(String(f.name || "")))
    || null;
  const yours = (hit) => (hit && hit.library && typeof hit.library === "object" ? hit.library : null);
  // Under a hit's "⋯", given ``later(pick, display, row, button)``: the song into wanted.txt under the site's
  // names, for the nightly run to look up (index.html's results; /lookup gets songs now alone).
  const laterGroup = (later, pick, display, row) => {
    const box = el("div", "row-group later");
    box.appendChild(el("p", "subhead", "Later"));
    const go = button("Add for tonight's run", "small", (e) => later(pick, display, row(), e.currentTarget),
      "Add " + display + " for tonight's run");
    go.title = "Into wanted.txt, as caracole add writes it: the nightly run looks it up";
    box.appendChild(go);
    return box;
  };
  // An Ultimate Guitar song: Get it (Get it again for a song of yours, looked up as that song), and its
  // versions under "⋯", each numbered within its kind ("Chords 2 of 13"), with a link to look at it on UG.
  const ugHit = (h, get, later) => {
    const hit = h && typeof h === "object" ? h : {};
    const mine = yours(hit);
    const artist = String(hit.artist || "");
    const title = String(hit.title || "");
    const display = mine ? String(mine.display || "") : artist + " - " + title;
    const pick = (extra) => Object.assign(mine ? { song: mine.id } : { artist, title }, { ug: hit.ug }, extra);
    let row = null;
    const main = button(mine ? "Get it again" : "Get it", "small primary", (e) => get(pick({}), display, row, e.currentTarget),
      (mine ? "Get " + display + " again" : "Get " + display) + " from Ultimate Guitar");
    const more = [];
    const tabs = listOf(hit.tabs).filter((t) => t && typeof t === "object");
    if (tabs.length) {
      const versions = el("ul", "versions");
      const nth = {};
      const totals = hit.counts && typeof hit.counts === "object" ? hit.counts : {};
      for (const t of tabs) {
        nth[t.type] = (nth[t.type] || 0) + 1;
        const kind = own.call(KINDS, t.type) ? KINDS[t.type] : String(t.type);
        const name = kind + " " + nth[t.type] + " of " + (totals[t.type] || nth[t.type]) + (t.label ? " · " + t.label : "");
        const item = el("li", "version");
        item.appendChild(button(name, "small", (e) => get(pick({ tab: t.url }), display, row, e.currentTarget),
          "Get " + name + ", " + display));
        const ug = el("a", "on-ug", "on UG");
        ug.href = /^https:[/][/]/i.test(String(t.url || "")) ? String(t.url) : "#";
        ug.target = "_blank";
        ug.rel = "noopener noreferrer";
        ug.setAttribute("aria-label", name + ", " + display + ", on Ultimate Guitar");
        item.appendChild(ug);
        versions.appendChild(item);
      }
      const box = el("div", "row-group");
      box.appendChild(el("p", "subhead", "Versions"));
      box.appendChild(versions);
      more.push(box);
    }
    const opens = mine ? opener(mine.links) : null;
    if (opens) more.push({ heading: "In your library", links: [{ label: opens.label, href: opens.href, source: opens.source }] });
    // Not under one of UG's misc-… names ("Misc Mashups"): no one's, the song would never be found by it.
    if (later && !mine && !hit.no_ones) more.push(laterGroup(later, { artist, title }, display, () => row));
    row = resultRow({ title, artist, source: "ug", facts: counts(hit.counts),
      badges: mine ? [{ kind: "found", text: "In your library" }] : [], action: main, more });
    row.classList.add("hit");
    row.dataset.ug = String(hit.ug || "");
    row.dataset.source = "ug";
    const dots = row.querySelector(".row-more");
    if (dots && tabs.length) {  // what "⋯" holds, said: its versions
      dots.title = "Versions of " + display;
      dots.setAttribute("aria-label", "Versions of " + display);
    }
    return row;
  };
  // An artist of the offline index, with their most tabbed songs said: ``open(a)`` lists every one.
  const artistHit = (a, open) => {
    const top = listOf(a && a.top).map((t) => t && t.title).filter(Boolean);
    const go = button("Songs", "small primary", () => open(a), "Songs by " + String(a.artist) + " on Ultimate Guitar");
    const row = resultRow({ title: a.artist, artist: top.length ? "Artist · " + top.join(", ") : "Artist", source: "ug",
      facts: many(a.songs, "song"), action: go });
    row.classList.add("hit", "artist-hit");
    row.dataset.artist = String(a.artist_key || "");
    row.dataset.source = "ug";
    return row;
  };
  // A page of gtptabs.com's index (a song with a Guitar Pro file there): Get it looks the song up as
  // caracole get does, whose gtptabs.com stage downloads one file for a song that has none; or MuseScore's,
  // a title alone, which caracole never fetches: a link to open.
  const siteHit = (h, get, later) => {
    const hit = h && typeof h === "object" ? h : {};
    const title = String(hit.title || "");
    let row = null;
    if (hit.source === "musescore") {
      row = resultRow({ title, artist: "Same title: maybe another song", source: "musescore",
        action: { label: "Open", href: hit.url } });
      const open = row.querySelector(".row-action a");
      if (open) open.setAttribute("aria-label", "Open " + title + " on MuseScore, in a new tab");
    } else {
      const mine = yours(hit);
      const artist = String(hit.artist || "");
      const display = mine ? String(mine.display || "") : artist + " - " + title;
      const pick = mine ? { song: mine.id } : { artist, title };
      const main = button(mine ? "Get it again" : "Get it", "small primary", (e) => get(pick, display, row, e.currentTarget),
        (mine ? "Get " + display + " again" : "Get " + display) + ", with a Guitar Pro file from gtptabs.com");
      main.title = "Looks the song up now, as caracole get does: its sheet, then a Guitar Pro file from gtptabs.com";
      const uploads = Number(hit.uploads) || 1;
      const more = [{ heading: "On gtptabs.com", links: [{ label: "Its page", href: hit.url, source: "gtptabs" }] }];
      if (later && !mine) more.push(laterGroup(later, { artist, title }, display, () => row));
      row = resultRow({ title, artist, source: "gtptabs", facts: uploads > 1 ? many(uploads, "upload") : "Guitar Pro",
        badges: mine ? [{ kind: "found", text: "In your library" }] : [], action: main, more });
    }
    row.classList.add("hit");
    row.dataset.source = String(hit.source || "");
    return row;
  };
  // A paragraph of the server's, its commands in backticks as the terminal prints them: those as code.
  const prose = (cls, text) => {
    const p = el("p", cls);
    const parts = String(text).split("`");
    if (parts.length % 2 === 0) p.textContent = String(text);  // a backtick unpaired: as it is
    else parts.forEach((part, i) => { if (part) p.appendChild(i % 2 ? el("code", null, part) : document.createTextNode(part)); });
    return p;
  };
  return { resultRow, sourceMark, link, titleLink, artistFilter, button, many, counts, opener, ugHit, artistHit,
    siteHit, prose };
};
"""


_SCRIPT = r"""
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const list = byId("list");
  const input = byId("q");
  const clear = byId("clear");
  const allButton = byId("all");
  const barStatus = byId("bar-status");
  const results = byId("results");
  const found = byId("found");
  const sort = byId("sort");
  const count = byId("count");
  const jump = byId("jump");
  const chips = Array.from(document.querySelectorAll(".chip[data-show]"));
  const artistChip = byId("artist");
  const viewToggle = byId("view-toggle");
  const viewPanel = byId("view-panel");
  const JUMP_FROM = 40;  // songs shown before the A-Z strip is worth its room: fewer, and a thumb scrolls

  let data;
  try {
    data = JSON.parse(byId("songs").textContent);
  } catch (err) {
    list.appendChild(el("p", "empty", "This page's song list can't be read. Run caracole todo to write it again."));
    return;
  }
  const songs = Array.isArray(data.songs) ? data.songs : [];
  const table = data.fold && typeof data.fold === "object" ? data.fold : {};
  const own = Object.prototype.hasOwnProperty;
  const listOf = (value) => (Array.isArray(value) ? value : []);
  // Served by caracole serve: its forms' token, and the songs it is fetching already.
  const server = data.server && typeof data.server === "object" ? data.server : null;
  const busy = new Set(listOf(server && server.busy).map(Number));
  const removing = new Set(listOf(server && server.removing).map(Number));

  // The same folding as caracole's normalize.fold: NFKD, no accents, a few letters spelled out, lowercase.
  const fold = (text) => {
    let out = "";
    for (const ch of String(text).normalize("NFKD").replace(/\p{Mn}/gu, "")) {
      out += own.call(table, ch) ? table[ch] : ch;
    }
    return out.toLowerCase();
  };
  // Apostrophes go, as in caracole's keys: "don’t" and "don't" both find "dont" (the search text has every
  // name without punctuation too). Other punctuation is only trimmed off the ends of a word.
  const APOSTROPHES = /['’‘`´ʼ]/g;
  const EDGES = /^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu;
  const term = (word) => word.replace(APOSTROPHES, "").replace(EDGES, "");
  const terms = (folded) => folded.split(/\s+/).map(term).filter(Boolean);
  // Each word in single quotes, each ' written '\'': bash and zsh expand ! even in double quotes.
  const shellQuote = (text) => "'" + String(text).replace(/'/g, "'\\''") + "'";
  const hay = songs.map((s) => String(s.search || ""));
  const inits = songs.map((s) => String(s.initials || ""));  // a title's initials: "wywh" finds Wish You Were Here

  const STATUS_TEXT = { found: "Found", wanted: "Wanted", ignored: "Ignored" };
  const LYRICS_TEXT = { pending: "Lyrics pending", missing: "No lyrics found", instrumental: "Instrumental" };
  const label = (texts, value) => (own.call(texts, value) ? texts[value] : "");
  const SHOWS = {
    all: () => true,
    found: (s) => s.status === "found",
    wanted: (s) => s.status === "wanted",
    review: (s) => Boolean(s.review) && s.status !== "ignored",
  };
  const CHIP_TEXT = { found: "found songs", wanted: "wanted songs", review: "songs that need review" };
  const SORTS = ["artist", "title", "recent"];
  const LETTERS = { artist: "artistLetter", title: "titleLetter" };  // the A-Z strip's letter, by sort
  // A key is "A minor" or "C" (keys.py); where it came from, as keys.SOURCES says.
  const KEY_SOURCES = { tab: "from the tab", chords: "estimated from the chords", audio: "from the audio" };
  const keyName = (key) => (/ minor$/.test(key) ? key : key + " major");
  const keyText = (s) => "Key " + keyName(String(s.key)) +
    (label(KEY_SOURCES, s.key_source) ? " (" + label(KEY_SOURCES, s.key_source) + ")" : "");
  // Which key a spelling names, as keys.same_key compares them: the tonic's pitch class and the mode, so
  // "F# minor" and "Gb minor" are one key. It reads keys as keys.py writes them, and as typed: "f#m", "bb major".
  const PITCH = { c: 0, d: 2, e: 4, f: 5, g: 7, a: 9, b: 11 };
  const SHIFT = { "": 0, "#": 1, "♯": 1, b: -1, "♭": -1 };
  const MINOR = ["m", "min", "minor"];
  const KEY = /^([a-g])([#♯b♭]?)\s*(m|min|minor|maj|major)?$/i;
  const keyId = (text) => {
    const m = KEY.exec(String(text || "").trim());
    if (!m) return "";
    const pitch = (PITCH[m[1].toLowerCase()] + SHIFT[m[2].toLowerCase()] + 12) % 12;
    return pitch + (MINOR.indexOf((m[3] || "").toLowerCase()) >= 0 ? " minor" : " major");
  };
  // A key typed in the search box: a letter, maybe a sharp or a flat, then the mode ("a minor", "F# major",
  // "bbm"). Its words leave the text search, and it keeps the songs in that key, however they spell it.
  // Written as a chord ("am", "f#m"), it is a word too, so "am" also finds "I Am the Walrus".
  const TYPED_KEY = /(^|[^\p{L}\p{N}])([a-g][#♯b♭]?)(?:\s*(major|minor|maj|min)|(m))(?![\p{L}\p{N}#♯♭])/gu;
  const parseQuery = (query) => {
    const keys = [];
    const either = [];
    const rest = fold(query).replace(TYPED_KEY, (all, before, tonic, mode, chord) => {
      if (chord) either.push({ key: keyId(tonic + chord), word: term(tonic + chord) });
      else keys.push(keyId(tonic + " " + mode));
      return before + " ";
    });
    return { keys, either, words: terms(rest) };
  };
  // Whether a key is typed ("a minor", not "am"): it filters your songs alone, as the sites' indexes know no keys.
  const keyed = (text) => parseQuery(text).keys.length > 0;
  const songKeys = songs.map((s) => keyId(s.key));
  // Whether song i matches what is typed: each word in its search text, or its title's initials whole, and
  // each key typed.
  const typedMatch = (query) => (i) =>
    query.keys.every((k) => songKeys[i] === k) &&
    query.either.every((e) => songKeys[i] === e.key || (e.word && hay[i].indexOf(e.word) >= 0)) &&
    query.words.every((w) => hay[i].indexOf(w) >= 0 || (w.length > 1 && inits[i] === w));

  const compare = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  // The Key menu: one entry per key the library has, its spellings together ("F# / Gb minor"), with how
  // many songs it has. Its commonest spelling stands for it in the menu and in the address.
  const keyGroups = new Map();
  songs.forEach((s, i) => {
    if (!songKeys[i]) return;
    const group = keyGroups.get(songKeys[i]) || { spellings: new Map(), n: 0 };
    group.spellings.set(String(s.key), (group.spellings.get(String(s.key)) || 0) + 1);
    group.n += 1;
    keyGroups.set(songKeys[i], group);
  });
  for (const [id, group] of keyGroups) {
    const spelled = Array.from(group.spellings.keys())
      .sort((a, b) => group.spellings.get(b) - group.spellings.get(a) || compare(a, b));
    group.value = spelled[0];
    group.name = spelled.map((k) => k.replace(/ minor$/, "")).join(" / ") + id.replace(/^\d+/, "");
  }
  const keyGroup = (spelling) => keyGroups.get(keyId(spelling));
  const order = songs.map((_, i) => i);
  const sortedBy = (first, second) => order.slice().sort((i, j) =>
    compare(String(songs[i][first]), String(songs[j][first])) ||
    compare(String(songs[i][second]), String(songs[j][second])) || i - j);
  const ORDERS = {
    artist: sortedBy("sortArtist", "sortTitle"),
    title: sortedBy("sortTitle", "sortArtist"),
    recent: order.slice().sort((i, j) =>
      compare(String(songs[j].added || ""), String(songs[i].added || "")) || (songs[j].id || 0) - (songs[i].id || 0)),
  };

  // Where each file came from (icons.py): its site's own icon, inlined as a data: URI, else its lettered
  // badge; a glyph for the audio model and the inbox. Each is named for a screen reader: "from LaCuerda".
  const ICONS = data.icons && typeof data.icons === "object" ? data.icons : {};
  // ROWS_SCRIPT's, which the lookup page shares
  const { sourceMark, link, resultRow, titleLink, artistFilter, button, many, ugHit, artistHit, siteHit, prose } =
    caracoleRows(ICONS);
  // A song's file from where its sheet came from has no mark of its own: its card's, or its row's, says it.
  const elsewhere = (s, item) => (item && item.source && item.source === s.source
    ? Object.assign({}, item, { source: null }) : item);
  // The file a song opens with, from its title and its card's one button: its viewer, else its PDF, else its
  // text (the data marks it primary).
  const primaryOf = (s) => listOf(s.files).find((f) => f && f.primary) || null;
  // A card's button for it: "Open" for the viewer, "Open PDF" and "Open text" for the others. The card's
  // primary one unless it has another (a wanted song's Fetch now, which its row's button is too).
  const openButton = (s, f, lead) => {
    const kind = /\.html$/i.test(String(f.name || "")) ? "" : /\.pdf$/i.test(String(f.name || "")) ? "PDF" : "text";
    const text = kind ? "Open " + kind : "Open";
    const open = link({ label: text, href: f.href }, lead ? "btn primary" : "btn", false);
    open.setAttribute("aria-label", text + (kind ? " of " : " ") + String(s.title) + " by " + String(s.artist));
    open.title = String(f.label || "");  // "Sheet viewer", "Auto sheet PDF"
    return open;
  };

  // The song has no human sheet, and caracole takes its audio from YouTube (youtube_fetch.py): where
  // that stands, and the video its audio came from.
  const youtubeNote = (s) => {
    if (!s.youtube || typeof s.youtube.text !== "string") return null;
    const note = el("p", "youtube", s.youtube.text);
    if (s.youtube.video && typeof s.youtube.video === "object") {
      note.appendChild(document.createTextNode(" · "));
      note.appendChild(link(s.youtube.video, null, true));
    }
    return note;
  };
  const linkRow = (parent, heading, items, cls) => {
    if (!items.length) return;
    parent.appendChild(el("p", "subhead", heading));
    const row = el("div", "actions");
    for (const item of items) row.appendChild(link(item, cls, true));
    parent.appendChild(row);
  };
  const hidden = (name, value) => {
    const field = el("input");
    field.setAttribute("type", "hidden");
    field.setAttribute("name", name);
    field.setAttribute("value", String(value));
    return field;
  };
  // A wanted song's "Fetch now": caracole serve queues a fetch of this song alone.
  const fetchForm = (s) => {
    const form = el("form", "fetch");
    form.setAttribute("method", "post");
    form.setAttribute("action", "/fetch");
    form.appendChild(hidden("csrf", String(server.csrf || "")));
    form.appendChild(hidden("song", Number(s.id)));
    const go = el("button", "btn primary", "Fetch now");
    go.type = "submit";
    go.setAttribute("aria-label", "Fetch " + String(s.title) + " by " + String(s.artist) + " now");
    go.title = "Ask Ultimate Guitar for this song now, politely";
    form.appendChild(go);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const card = form.closest("article");
      const line = progressIn(card);  // in the page before its first words, so they are read out
      showLine(line, { line: { tone: "queued", text: "Sending…" } });
      if (form.contains(document.activeElement)) focusOn(line);  // a disabled button would drop it
      go.disabled = true;
      send(form).then((answer) => {
        const view = answer.ok && answer.body && answer.body.job;
        if (!view) {
          go.disabled = false;
          showLine(progressIn(card), failure(answer));
          return;
        }
        if (card && !isOwn(s, card)) spots.set(Number(view.id), card);
        track(view);  // its line takes the button's place
      }, () => {
        go.disabled = false;
        showLine(progressIn(card), UNREACHABLE);
      });
    });
    return form;
  };
  // Every card's "Remove…" (a row's, under its "⋯"): one tap counts down REMOVE_WAIT seconds on the song's own
  // line, "Removing in 5 s · Undo", with what goes (the server's answer to the question, ``removal.brief``), and
  // sends nothing else meanwhile; then the removal, whose line the card follows to Removed, never leaving the
  // page. Undo stops it. Without JavaScript the form posts, and caracole serve asks on a page of its own, whose
  // answers go back to the library as you left it (`back`: the address after #, its search, filters and view).
  const REMOVE_WAIT = 5;  // seconds
  const removals = new Map();  // song id -> its removal counting down (startRemoval)
  const removeForm = (s) => {
    const form = el("form", "remove");
    form.setAttribute("method", "post");
    form.setAttribute("action", "/remove");
    form.appendChild(hidden("csrf", String(server.csrf || "")));
    form.appendChild(hidden("song", Number(s.id)));
    const back = form.appendChild(hidden("back", ""));
    form.addEventListener("submit", (e) => {
      back.value = location.hash.slice(1);
      e.preventDefault();
      startRemoval(s, form.closest("article"));
    });
    const go = el("button", "btn small quiet", "Remove…");
    go.type = "submit";
    go.setAttribute("aria-label", "Remove " + String(s.title) + " by " + String(s.artist) + " from caracole");
    go.title = "Delete the files caracole wrote for it, and keep caracole from bringing it back; Undo, for " +
      REMOVE_WAIT + " seconds, keeps it";
    form.appendChild(go);
    return form;
  };
  // The song's card and row, and the card that showed it elsewhere (#requested's), if any: where its removal shows.
  const removalItems = (id, r) => {
    const i = byIndex.get(id);
    const own = i === undefined ? [] : [cards.get(i), rows.get(i)];
    return own.concat([r.spot]).filter((item, n, all) => item && all.indexOf(item) === n);
  };
  // A removal's line while it counts down: a screen reader hears it once ("Removing Creep in 5 seconds."), the
  // seconds left are for the eye; then Undo, and what goes. The item's other buttons wait meanwhile.
  const countdownIn = (item, r) => {
    const s = r.song;
    const p = progressIn(item);
    p.dataset.key = "";  // drawn here: the next showLine draws its own
    p.dataset.tone = "waiting";
    p.textContent = "";
    const shown = el("span");
    shown.setAttribute("aria-hidden", "true");
    shown.append("Removing in ", el("span", "left", r.left), " s");
    const dot = el("span", "dot", "·");
    dot.setAttribute("aria-hidden", "true");
    const undo = el("button", "undo", "Undo");
    undo.type = "button";
    undo.setAttribute("aria-label", "Undo: keep " + String(s.title) + " by " + String(s.artist));
    undo.addEventListener("click", () => undoRemoval(Number(s.id)));
    p.append(shown, el("span", "visually-hidden", "Removing " + String(s.title) + " in " + REMOVE_WAIT +
      " seconds."), dot, undo, el("span", "goes", r.brief));
    for (const b of item.querySelectorAll("form button")) {
      if (!b.disabled) {
        b.disabled = true;
        r.held.add(b);
      }
    }
    return undo;
  };
  const eachLine = (id, r, part, text) => {
    for (const item of removalItems(id, r)) {
      const node = item.querySelector(".progress " + part);
      if (node) node.textContent = text;
    }
  };
  // The removal over before it was sent: undone, or refused (``view``'s line says why). Its buttons are back.
  const stopRemoval = (id, view, focusBack) => {
    const r = removals.get(id);
    if (!r) return;
    removals.delete(id);
    clearTimeout(r.timer);
    const items = removalItems(id, r);
    const from = items.find((item) => item.contains(document.activeElement));
    for (const item of items) {
      const p = progressIn(item);
      p.style.minHeight = "";
      showLine(p, view);
    }
    for (const b of r.held) b.disabled = false;
    const go = focusBack && from ? from.querySelector("form.remove button") : null;
    if (go) go.focus();
  };
  const undoRemoval = (id) => stopRemoval(id, { line: { tone: "kept", text: "Not removed" } }, true);
  const startRemoval = (s, item) => {
    const id = Number(s.id);
    if (removals.has(id)) return;
    const r = { song: s, left: REMOVE_WAIT, timer: 0, brief: "Asking what goes…", key: null, ready: null,
                spot: item && !isOwn(s, item) ? item : null, held: new Set() };
    removals.set(id, r);
    let undo = null;
    for (const at of removalItems(id, r)) {
      const made = countdownIn(at, r);
      if (at === item) undo = made;
    }
    if (undo) undo.focus();
    // The question alone: what goes. It changes nothing; the removal is sent once the seconds are over.
    r.ready = postTo("/remove", new URLSearchParams({ csrf: String(server.csrf || ""), song: String(id) }))
      .then((answer) => {
        const plan = answer.ok && answer.body && answer.body.removal;
        if (!plan || typeof plan !== "object") throw failure(answer);
        r.key = String(plan.key || "");
        r.brief = String(plan.brief || "");
        eachLine(id, r, ".goes", r.brief);
      }, () => { throw UNREACHABLE; });
    r.ready.catch((said) => {
      if (removals.get(id) === r) stopRemoval(id, said && said.line ? said : UNREACHABLE, false);
    });
    const tick = () => {
      if (removals.get(id) !== r) return;
      r.left -= 1;
      if (r.left > 0) {
        eachLine(id, r, ".left", String(r.left));
        r.timer = setTimeout(tick, 1000);
      } else {
        sendRemoval(id, r);
      }
    };
    r.timer = setTimeout(tick, 1000);
  };
  // The seconds are over: the removal, sent with the song's key (an id the library gave another song since
  // removes nothing); its line follows the job from here, as tall as it was, so that nothing under it moves.
  const sendRemoval = (id, r) => {
    for (const item of removalItems(id, r)) {
      const p = progressIn(item);
      const tall = p.getBoundingClientRect().height;
      if (tall) p.style.minHeight = tall + "px";
      showLine(p, { line: { tone: "running", text: "Removing…" } });
    }
    r.ready.then(() => {
      if (removals.get(id) !== r) return;
      const body = new URLSearchParams({ csrf: String(server.csrf || ""), song: String(id), key: r.key || "",
                                         confirm: "1" });
      postTo("/remove", body).then((answer) => {
        const view = answer.ok && answer.body && answer.body.job;
        if (!view || typeof view !== "object") {
          stopRemoval(id, failure(answer), false);
          return;
        }
        removals.delete(id);
        removing.add(id);
        if (r.spot) spots.set(Number(view.id), r.spot);
        track(view);
      }, () => stopRemoval(id, UNREACHABLE, false));
    }, () => {});  // refused already: its line says why
  };

  // --- caracole serve: requests answered on the page ------------------------------------------
  // The forms post with fetch(), so the page stays where it is, and each song's card says on one line how its
  // request goes. /jobs.json gives each request's line, and a request's card once it is over; the page asks
  // it every POLL ms while one it shows waits or runs. Without JavaScript the forms post as forms, and the
  // server sends the browser to the request on /jobs.
  const POLL = 1500;
  const BACKGROUND_POLL = 6000;  // a page in a background tab asks less often
  const UNREACHABLE = { line: { tone: "failed", text: "caracole serve can't be reached: is it running?" } };
  const UNREACHABLE_NOW = "caracole serve can't be reached; trying again…";
  const MISSES = 3;  // asked in vain this many times in a row, the lines say so
  const views = new Map();  // job id -> what the server last said of it
  const songJob = new Map();  // song id -> the newest job of the song this page shows
  const watched = new Set();  // the jobs this page shows: asked for here, or waiting or running when it loaded
  const settled = new Set();  // watched jobs that are over, their cards drawn again
  const spots = new Map();  // job id -> a card outside the grid that shows it (#requested's)
  const byIndex = new Map(songs.map((s, i) => [Number(s.id), i]));  // song id -> its place in songs
  const isActive = (view) => view.state === "queued" || view.state === "running";
  const jobOfSong = (id) => (songJob.has(Number(id)) ? views.get(songJob.get(Number(id))) : null);
  // Whether node is the song's own card or row in the list, which the page draws again itself; any other
  // (#requested's card) is a spot of the job's.
  const isOwn = (s, node) => {
    const i = byIndex.get(Number(s.id));
    return i !== undefined && (cards.get(i) === node || rows.get(i) === node);
  };
  // A request's line, written into p only when it changed, so a screen reader hears each change once.
  // Its link says where to go next; details, the request's output on /jobs, follows it.
  const showLine = (p, view) => {
    const line = view && view.line && typeof view.line === "object" ? view.line : {};
    const to = line.link && typeof line.link === "object" ? line.link : null;
    const more = typeof line.details === "string" ? line.details : "";
    const key = [line.tone, line.text, to ? to.href : "", more].map(String).join("|");
    if (p.dataset.key === key) return;
    const focused = p !== document.activeElement && p.contains(document.activeElement);
    p.dataset.key = key;
    p.dataset.tone = String(line.tone || "");
    p.textContent = "";
    p.appendChild(el("span", null, line.text || ""));
    for (const go of [to, more ? { label: "Details", href: more } : null]) {
      if (!go) continue;
      const dot = el("span", "dot", "·");
      dot.setAttribute("aria-hidden", "true");
      p.appendChild(dot);
      const a = link(go, null, false);
      if (go === to) a.addEventListener("click", (e) => pickHere(e, p));
      p.appendChild(a);
    }
    if (focused) focusOn(p);  // its link is gone: the focus stays on the line
  };
  // A song in review's line sends you to its picker (review?song=ID): on a card that has the picker, it opens
  // that one, where you are, rather than the picker's own page. The list of requests has none: it goes there.
  const pickHere = (e, p) => {
    const card = p.closest("article");
    const box = card && card.querySelector("details.picker");
    const href = e.currentTarget.getAttribute("href") || "";
    if (!box || !box.querySelector("form") || !/^review\?song=\d+$/.test(href)) return;
    e.preventDefault();
    showPicker(box);
  };
  // Opens a picker where it is, a row's in its panel (the "⋯" button's), which opens first. Opened, the
  // picker takes the focus to its first candidate (its toggle); open already, the focus goes there.
  const showPicker = (box) => {
    const panel = box.closest(".row-panel");
    if (panel && panel.hidden) {
      const more = panel.parentNode.querySelector(".row-more");
      if (more) more.setAttribute("aria-expanded", "true");
      panel.hidden = false;
    }
    if (!box.open) {
      box.open = true;
      return;
    }
    const first = box.querySelector("input[name=pick]:checked") || box.querySelector("input[name=pick]");
    if (first) first.focus();
  };
  const focusOn = (p) => {
    p.tabIndex = -1;
    p.focus({ preventScroll: true });
  };
  // A card's line, made the first time: role="status" has it read out when it changes. A live region
  // put in the page with its text already in it is not read out, so a card keeps its line from the first
  // text to the last (refill), and only that text changes.
  const progressIn = (card) => {
    let p = card.querySelector(".progress");
    if (!p) {
      p = el("p", "progress");
      p.setAttribute("role", "status");
      // A card's under its facts; a row's under its artist, a line of its own across the row.
      const after = card.querySelector(".facts") || card.querySelector(".head") || card.querySelector(".row-sub") ||
        card.querySelector(".row-title");
      if (after) after.after(p);
      else card.appendChild(p);
    }
    return p;
  };
  // The card old, drawn again as fresh (makeCard's) where it is, around its own line, which never leaves
  // the page; returns old. The focus, if it was on something of old's that goes, moves to the line.
  const refill = (old, fresh) => {
    const kept = old.querySelector(".progress");
    if (!kept) {
      if (old.parentNode) old.replaceWith(fresh);
      return fresh;
    }
    const at = document.activeElement;
    const focused = at !== old && old.contains(at) && !kept.contains(at);  // on something that goes
    const drawn = progressIn(fresh);  // where fresh has its line
    for (const child of Array.from(old.childNodes)) if (child !== kept) child.remove();
    let before = true;
    for (const child of Array.from(fresh.childNodes)) {
      if (child === drawn) before = false;
      else if (before) old.insertBefore(child, kept);
      else old.appendChild(child);
    }
    old.className = fresh.className;
    old.tabIndex = fresh.tabIndex;
    for (const name of Object.keys(old.dataset)) delete old.dataset[name];
    Object.assign(old.dataset, fresh.dataset);
    if (focused && old.isConnected) focusOn(kept);
    return old;
  };
  const failure = (answer) => ({ line: { tone: "failed", text: (answer.body && answer.body.error) ||
    "caracole serve answered " + answer.status + ": reload the page." } });
  // A form, posted as the page's script: the answer is the job, or {error}, never a page.
  const postTo = (path, body) => fetch(path, {
    method: "POST", body, credentials: "same-origin", headers: { Accept: "application/json" },
  }).then((r) => r.json().catch(() => null).then((answer) => ({ ok: r.ok, status: r.status, body: answer })));
  const send = (form) => postTo(form.getAttribute("action"), new URLSearchParams(new FormData(form)));
  let track = () => {};

  // A song not found: caracole serve's picker page shows what `caracole search` finds for it.
  const lookLink = (s, cls) => {
    const look = el("a", cls || "btn", "Look in the index");
    look.href = "/review?song=" + Number(s.id);
    look.setAttribute("aria-label", "Look for " + String(s.title) + " by " + String(s.artist) + " in the index");
    look.title = "What caracole search finds for it in the offline Ultimate Guitar index, to pick from";
    return look;
  };

  // A song not found, on the file, which can't search: the line that lists its search hits, numbered as
  // `caracole review --song … --pick N` takes them.
  const notFoundHint = (s) => {
    const hint = el("p", "pick-hint", "Not in the offline Ultimate Guitar index under this name: ");
    hint.appendChild(el("code", null, "caracole review --song " + shellQuote(String(s.display))));
    hint.appendChild(document.createTextNode(" lists what caracole search finds for it, to pick one."));
    return hint;
  };

  // The picker: a song in review's candidates, numbered as `caracole review` numbers them. The file shows
  // them with the line that picks one; caracole serve, with a form whose answer `caracole review --song`
  // writes (web/app.py). makePicker(song) builds it from a song of the data that has `candidates`.
  const choiceRow = (c, pickable) => {
    const row = el(pickable ? "div" : "li", "choice");
    const pick = el(pickable ? "label" : "div", "choice-pick");
    if (pickable) {
      const radio = el("input");
      radio.setAttribute("type", "radio");
      radio.setAttribute("name", "pick");
      radio.setAttribute("value", String(c.ref));
      radio.setAttribute("required", "");
      pick.appendChild(radio);
    }
    const text = el("span", "choice-text");
    text.appendChild(el("span", "choice-name", c.n + ". " + String(c.artist) + " – " + String(c.title)));
    const why = [c.why, "score " + (Number(c.score) || 0), c.tabs].filter(Boolean).map(String).join(" · ");
    text.appendChild(el("span", "choice-why", why));
    pick.appendChild(text);
    row.appendChild(pick);
    if (c.href) {
      const page = link({ label: "UG", href: c.href }, "choice-link", true);
      page.setAttribute("aria-label", String(c.artist) + " – " + String(c.title) + " on Ultimate Guitar, in a new tab");
      row.appendChild(page);
    }
    return row;
  };
  const noneRow = () => {
    const row = el("div", "choice none");
    const pick = el("label", "choice-pick");
    const radio = el("input");
    radio.setAttribute("type", "radio");
    radio.setAttribute("name", "pick");
    radio.setAttribute("value", "none");
    radio.setAttribute("required", "");
    pick.appendChild(radio);
    const text = el("span", "choice-text");
    text.appendChild(el("span", "choice-name", "None of these"));
    text.appendChild(el("span", "choice-why", "caracole drops them for good and goes on looking for the song"));
    pick.appendChild(text);
    row.appendChild(pick);
    return row;
  };
  const makePicker = (s) => {
    const cands = listOf(s.candidates).filter((c) => c && c.ref);
    const box = el("details", "picker");
    const question = "Which Ultimate Guitar song is “" + String(s.title) + "” by " + String(s.artist) + "?";
    const job = server ? jobOfSong(s.id) : null;
    const pickable = Boolean(server) && !busy.has(Number(s.id)) && !(job && isActive(job));
    const many = plural(cands.length, "candidate");
    const summary = el("summary", pickable ? "btn picker-open" : "picker-open", pickable ? "Pick the match" : many);
    if (pickable) summary.appendChild(el("span", "picker-n", "· " + many));
    box.appendChild(summary);
    if (!pickable) {
      const list = el("ol", "choices");
      list.setAttribute("aria-label", question);
      for (const c of cands) list.appendChild(choiceRow(c, false));
      box.appendChild(list);
      if (server) {
        box.appendChild(el("p", "pick-hint", "A request for this song is running: pick one once it ends."));
      } else {
        const hint = el("p", "pick-hint", "Pick one with ");
        hint.appendChild(el("code", null, "caracole review --song " + shellQuote(String(s.display))));
        hint.appendChild(document.createTextNode(": its number, or "));
        hint.appendChild(el("code", null, "n"));
        hint.appendChild(document.createTextNode(" for none of these."));
        box.appendChild(hint);
      }
      return box;
    }
    const form = el("form", "pick-form");
    form.setAttribute("method", "post");
    form.setAttribute("action", "/review");
    form.appendChild(hidden("csrf", String(server.csrf || "")));
    form.appendChild(hidden("song", Number(s.id)));
    form.appendChild(hidden("shown", cands.map((c) => String(c.ref)).join(" ")));
    const group = el("fieldset", "choices");
    group.appendChild(el("legend", null, question));
    for (const c of cands) group.appendChild(choiceRow(c, true));
    group.appendChild(noneRow());
    form.appendChild(group);
    const row = el("div", "pick-row");
    const now = el("label", "pick-check");
    const fetch = el("input");
    fetch.setAttribute("type", "checkbox");
    fetch.setAttribute("name", "fetch");
    fetch.setAttribute("value", "1");
    fetch.setAttribute("checked", "");
    now.appendChild(fetch);
    now.appendChild(document.createTextNode("Fetch it now"));
    row.appendChild(now);
    const go = el("button", "btn primary", "Pick");
    go.type = "submit";
    row.appendChild(go);
    form.appendChild(row);
    form.appendChild(el("p", "pick-hint", "Your answer goes into overrides.toml, as caracole review writes it. " +
      "Fetch it now then asks Ultimate Guitar for the song picked; None of these fetches nothing."));
    box.appendChild(form);
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const card = form.closest("article");
      const line = progressIn(card);  // in the page before its first words, so they are read out
      showLine(line, { line: { tone: "queued", text: "Sending…" } });
      if (form.contains(document.activeElement)) focusOn(line);  // a disabled button would drop it
      go.disabled = true;
      send(form).then((answer) => {
        const view = answer.ok && answer.body && answer.body.job;
        if (!view) {
          go.disabled = false;
          showLine(progressIn(card), failure(answer));
          return;
        }
        if (card && !isOwn(s, card)) spots.set(Number(view.id), card);
        track(view);  // its line takes the picker's place
      }, () => {
        go.disabled = false;
        showLine(progressIn(card), UNREACHABLE);
      });
    });
    // Opened, the picker takes the focus to its candidates: the arrow keys then move between them.
    box.addEventListener("toggle", () => {
      if (!box.open) return;
      const first = form.querySelector("input[name=pick]:checked") || form.querySelector("input[name=pick]");
      if (first) first.focus();
    });
    return box;
  };

  let setArtist = () => {};
  // An artist's monogram, in that artist's colour (one of eight), which a screen reader skips.
  const monogram = (letters, hue) => {
    const mono = el("span", "mono hue-" + (Number.isInteger(hue) && hue >= 0 && hue < 8 ? hue : 0), letters || "");
    mono.setAttribute("aria-hidden", "true");
    return mono;
  };
  // A card's head without its links or badges: the monogram, the title and the artist (a removed song's card;
  // a requested song's, before the library has it).
  const plainHead = (letters, hue, title, artist) => {
    const head = el("div", "head");
    const names = el("div", "names");
    names.append(el("h2", null, title), el("p", "by", artist));
    head.append(monogram(letters, hue), names);
    return head;
  };
  const makeCard = (s) => {
    const card = el("article", "card");
    card.dataset.status = String(s.status);
    card.dataset.id = String(s.id);
    card.tabIndex = -1;  // the A-Z strip moves the focus to it
    const head = el("div", "head");
    head.appendChild(monogram(s.monogram, s.hue));
    const names = el("div", "names");
    const primary = primaryOf(s);
    names.appendChild(primary ? titleLink(primary.href, el("h2", null, s.title)) : el("h2", null, s.title));
    const artists = listOf(s.artists);
    // The artist, then the badges: at the end of the artist's line, or under it, never beside the title.
    const byline = el("div", "byline");
    byline.appendChild(artistFilter(artists.length > 1 ? artists.join(", ") : String(s.artist), String(s.artist),
      () => {
        setArtist(String(s.sortArtist || ""));
        window.scrollTo(0, 0);
      }));
    names.appendChild(byline);
    head.appendChild(names);
    const badges = el("div", "badges");
    const mark = sourceMark(s.source);  // where its sheet came from
    if (mark) badges.appendChild(mark);
    badges.appendChild(el("span", "badge " + String(s.status), label(STATUS_TEXT, s.status) || s.status));
    if (SHOWS.review(s)) badges.appendChild(el("span", "badge review", "Needs review"));
    if (s.auto) badges.appendChild(el("span", "badge auto", "Auto sheet"));
    byline.appendChild(badges);
    card.appendChild(head);

    const facts = el("p", "facts");
    if (typeof s.key === "string" && s.key) facts.appendChild(el("span", "key", keyText(s)));
    const shift = Number(s.transpose) || 0;
    if (shift) {
      const t = el("span", "transpose", (shift > 0 ? "+" : "−") + Math.abs(shift));
      t.title = "The PDF is transposed " + (shift > 0 ? "up " : "down ") + Math.abs(shift) +
        " semitone" + (Math.abs(shift) === 1 ? "" : "s");
      facts.appendChild(t);
    }
    if (label(LYRICS_TEXT, s.lyrics)) facts.appendChild(el("span", "lyrics", label(LYRICS_TEXT, s.lyrics)));
    if (s.added) facts.appendChild(el("span", "added", "Added " + String(s.added).slice(0, 10)));
    if (facts.childNodes.length) card.appendChild(facts);
    const picks = SHOWS.review(s) && listOf(s.candidates).length > 0;
    if (picks) {
      card.appendChild(makePicker(s));
    } else if (SHOWS.review(s)) {
      const note = el("p", "note", "caracole isn't sure about this match: see the ");
      const todo = el("a", null, "to-do page");
      todo.href = "_todo.md";
      note.appendChild(todo);
      note.appendChild(document.createTextNode(", or run caracole review."));
      card.appendChild(note);
    } else if (!server && s.notFound && s.status === "wanted") {
      card.appendChild(notFoundHint(s));
    }
    const fromYouTube = youtubeNote(s);
    if (fromYouTube) card.appendChild(fromYouTube);

    // Served by caracole serve: how the song's request goes, on one line, and Fetch now unless one runs.
    const job = server ? jobOfSong(s.id) : null;
    if (job) showLine(progressIn(card), job);
    const actions = el("div", "actions");
    if (server && s.status === "wanted" && !removing.has(Number(s.id))) {  // removing: its foot says so
      if ((job && isActive(job)) || busy.has(Number(s.id))) {
        if (!job) showLine(progressIn(card), { line: { tone: "running", text: "Fetching…" } });
      } else if (s.fetchable === false && picks) {
        // caracole fetch would refuse it until the match is picked: the picker above does that.
      } else if (s.fetchable === false) {
        // caracole fetch would refuse it: the match needs review first (the note above says how).
        const held = el("button", "btn", "Review first");
        held.type = "button";
        held.disabled = true;
        held.title = "caracole review settles this match; then it can be fetched";
        actions.appendChild(held);
      } else {
        actions.appendChild(fetchForm(s));
      }
      if (s.notFound) actions.appendChild(lookLink(s));
    }
    if (primary) actions.appendChild(openButton(s, primary, !actions.querySelector(".btn.primary")));
    if (actions.childNodes.length) card.appendChild(actions);
    // The other files, and the Guitar Pro versions to download, folded away as a row's "⋯" folds them.
    const others = listOf(s.files).filter((f) => f && f !== primary).map((f) => elsewhere(s, f));
    if (others.length || listOf(s.guitarPro).length) {
      const files = el("details", "more files");
      files.appendChild(el("summary", null, "Files"));
      if (others.length) {
        const line = el("div", "actions");
        for (const f of others) line.appendChild(link(f, "btn small", false));
        files.appendChild(line);
      }
      linkRow(files, "Guitar Pro to download", listOf(s.guitarPro), "btn small");
      card.appendChild(files);
    }
    if (listOf(s.museScore).length || listOf(s.links).length || listOf(s.buy).length) {
      const more = el("details", "more");
      more.appendChild(el("summary", null, "Find it elsewhere"));
      linkRow(more, "Scores on MuseScore", listOf(s.museScore), "btn small");
      linkRow(more, "Find the chords", listOf(s.links), "btn small");
      linkRow(more, "Buy the track for an auto sheet", listOf(s.buy), "btn small");
      card.appendChild(more);
    }
    if (server) {
      const foot = el("div", "foot");
      if (!removing.has(Number(s.id))) {
        foot.appendChild(removeForm(s));
      } else if (!job || job.kind !== "remove") {  // a removal the page follows says how it goes on its line
        const note = el("p", "busy", "Removing… ");
        const jobs = el("a", null, "see the requests");
        jobs.href = "/jobs";
        note.appendChild(jobs);
        foot.appendChild(note);
      }
      if (foot.childNodes.length) card.appendChild(foot);
      if (removals.has(Number(s.id))) countdownIn(card, removals.get(Number(s.id)));  // drawn again meanwhile
    }
    return card;
  };
  const cards = new Map();
  const cardFor = (i) => {
    if (!cards.has(i)) cards.set(i, makeCard(songs[i]));
    return cards.get(i);
  };

  // Rows: one compact line a song (resultRow, from ROWS_SCRIPT: the seam the module docstring describes).
  // A row is an article titled by its h2; the A-Z strip moves the focus to it.
  // A song's main action in its row, as its card has it, when the server's control holds the row's button
  // (``held``): a wanted song's fetch, or the button that opens its picker; Removing… while caracole removes it;
  // no button at all (``action`` null) while its request, or its removal, waits or runs, as the row's line
  // then says how it goes. Not held, the row's button is its sheet (sheetAction), as it is on the file.
  const serverAction = (s, picker) => {
    const held = (action) => ({ held: true, action });
    if (server && removing.has(Number(s.id))) {
      const job = jobOfSong(s.id);
      if (job && job.kind === "remove") return held(null);
      const going = el("a", "row-busy", "Removing…");
      going.href = "/jobs";
      going.title = "See the requests";
      return held(going);
    }
    if (server && s.status === "wanted") {
      const job = jobOfSong(s.id);
      if ((job && isActive(job)) || busy.has(Number(s.id))) return held(null);
      if (s.fetchable === false && picker && picker.querySelector("form")) {
        // caracole fetch would refuse it until the match is picked: this opens the picker, in the row's panel.
        const pick = el("button", "btn small row-pick", "Pick the match");
        pick.type = "button";
        pick.setAttribute("aria-label", "Pick the match for " + String(s.title) + " by " + String(s.artist));
        pick.title = "Which Ultimate Guitar song this is: caracole isn't sure";
        pick.addEventListener("click", () => showPicker(picker));
        return held(pick);
      }
      if (s.fetchable === false) {
        const later = el("button", "btn small", "Review first");
        later.type = "button";
        later.disabled = true;
        later.title = "caracole review settles this match; then it can be fetched";
        return held(later);
      }
      return held(fetchForm(s));
    }
    return { held: false, action: null };
  };
  // The row's button for its sheet: the primary one, as Fetch now is, named for what it opens ("Sheet viewer").
  const sheetAction = (s, primary) => {
    const open = link({ label: primary.label, href: primary.href }, "btn small primary", false);
    open.setAttribute("aria-label", String(primary.label) + " of " + String(s.title) + " by " + String(s.artist));
    return open;
  };
  const songRow = (s) => {
    const id = Number(s.id);
    const files = listOf(s.files);
    const primary = primaryOf(s);
    const more = [];
    // What a card shows under its facts, in the row's panel: the picker, or the note that says why not.
    const picker = SHOWS.review(s) && listOf(s.candidates).length > 0 ? makePicker(s) : null;
    if (picker) {
      // The row's button says Pick the match: its picker folds as a read-only one does, "3 candidates".
      const summary = picker.querySelector("summary");
      summary.className = "picker-open";
      summary.textContent = plural(listOf(s.candidates).filter((c) => c && c.ref).length, "candidate");
      more.push(picker);
    } else if (SHOWS.review(s)) {
      const note = el("p", "note", "caracole isn't sure about this match: see the ");
      const todo = el("a", null, "to-do page");
      todo.href = "_todo.md";
      note.appendChild(todo);
      note.appendChild(document.createTextNode(", or run caracole review."));
      more.push(note);
    } else if (!server && s.notFound && s.status === "wanted") {
      more.push(notFoundHint(s));
    }
    const fromYouTube = youtubeNote(s);  // as on its card, first in the row's panel
    if (fromYouTube) more.push(fromYouTube);
    if (server && s.notFound && s.status === "wanted" && !removing.has(id)) {
      const look = el("div", "actions");
      look.appendChild(lookLink(s, "btn small"));
      more.push(look);
    }
    // The sheet is the row's button unless the server's control has its place (Fetch now beside an auto
    // sheet): then it leads the files, and the title opens it all the same.
    const control = serverAction(s, picker);
    const action = control.held ? control.action : primary ? sheetAction(s, primary) : null;
    const listed = control.held ? files : files.filter((f) => f !== primary);
    more.push({ heading: "Files", links: listed.map((f) => elsewhere(s, f)) },
      { heading: "Guitar Pro to download", links: listOf(s.guitarPro) },
      { heading: "Scores on MuseScore", links: listOf(s.museScore) },
      { heading: "Find the chords", links: listOf(s.links) },
      { heading: "Buy the track for an auto sheet", links: listOf(s.buy) });
    if (server && !removing.has(id)) {  // removing: its action says so
      const foot = el("div", "foot");
      foot.appendChild(removeForm(s));
      more.push(foot);
    }
    // No "Auto sheet" badge: the row's mark (♪, "from the audio") and its button ("Auto sheet PDF") say so.
    const badges = [{ kind: s.status, text: label(STATUS_TEXT, s.status) || s.status }];
    if (SHOWS.review(s)) badges.push({ kind: "review", text: "Needs review" });
    const artists = listOf(s.artists);
    const keyed = typeof s.key === "string" && s.key;
    const row = resultRow({
      title: s.title,
      href: primary ? primary.href : "",
      artist: artists.length > 1 ? artists.join(", ") : s.artist,
      source: s.source,
      status: s.status,
      key: keyed ? s.key : "",
      keyText: keyed ? keyText(s) : "",
      badges,
      action,
      more,
      onArtist: () => {
        setArtist(String(s.sortArtist || ""));
        window.scrollTo(0, 0);
      },
    });
    row.dataset.id = String(s.id);  // as a card's: the Select mode finds the song's row by it
    // How the song's request goes, on a line of the row's own, as on its card.
    const job = server ? jobOfSong(id) : null;
    if (job) {
      showLine(progressIn(row), job);
    } else if (server && s.status === "wanted" && !removing.has(id) && busy.has(id)) {
      showLine(progressIn(row), { line: { tone: "running", text: "Fetching…" } });
    }
    if (removals.has(id)) countdownIn(row, removals.get(id));  // drawn again while its removal counts down
    return row;
  };
  const rows = new Map();
  const rowFor = (i) => {
    if (!rows.has(i)) rows.set(i, songRow(songs[i]));
    return rows.get(i);
  };
  const VIEWS = ["cards", "rows"];
  const viewButtons = Array.from(document.querySelectorAll("button[data-view]"));
  // For lists the page doesn't make itself (the served page's type-ahead): the same rows and marks.
  window.caracole = Object.freeze({ resultRow, sourceMark, icons: ICONS });

  // artist: one artist's songs alone, by sortArtist, which a search for the name wouldn't give
  // ("Queen" also finds "Dancing Queen").
  // all: the search of the sites (served; on the file, the line that searches them), under the bar.
  const state = { q: "", show: "all", sort: "artist", artist: "", key: "", view: "cards", all: false };
  const itemFor = (i) => (state.view === "rows" ? rowFor(i) : cardFor(i));
  const artistName = (key) => {
    const s = key ? songs.find((song) => String(song.sortArtist || "") === key) : undefined;
    return s ? String(s.artist) : "";
  };
  try {
    const params = new URLSearchParams(location.hash.slice(1));
    state.q = params.get("q") || "";
    if (artistName(params.get("artist") || "")) state.artist = params.get("artist");
    if (own.call(SHOWS, params.get("show"))) state.show = params.get("show");
    if (SORTS.indexOf(params.get("sort")) >= 0) state.sort = params.get("sort");
    if (keyGroup(params.get("key"))) state.key = keyGroup(params.get("key")).value;  // any spelling of it
    if (VIEWS.indexOf(params.get("view")) >= 0) state.view = params.get("view");
    state.all = params.get("all") === "1" && Boolean(state.q.trim()) && !keyed(state.q);
  } catch (err) {
    // A malformed address: start from the defaults.
  }
  const keySelect = byId("key");
  for (const group of Array.from(keyGroups.values()).sort((a, b) => compare(a.name, b.name))) {
    const option = el("option", null, group.name + " · " + group.n);
    option.value = group.value;
    keySelect.appendChild(option);
  }
  byId("keys").hidden = keyGroups.size === 0;
  const save = () => {
    const params = new URLSearchParams();
    if (state.q) params.set("q", state.q);
    if (state.show !== "all") params.set("show", state.show);
    if (state.sort !== "artist") params.set("sort", state.sort);
    if (state.artist) params.set("artist", state.artist);
    if (state.key) params.set("key", state.key);
    if (state.view !== "cards") params.set("view", state.view);
    if (state.all) params.set("all", "1");
    try {
      history.replaceState(null, "", "#" + params.toString());
    } catch (err) {
      // Some browsers refuse this for local files; the page works the same, it just isn't remembered.
    }
  };

  const plural = (n, word) => n + " " + word + (n === 1 ? "" : "s");
  const arrived = new Map();  // song id -> the card data of a song new to the library since the page loaded
  // A song removed since the page loaded counts nowhere, though its card says Removed until the next load.
  const counted = (s) => s.status !== "removed";
  const summarize = () => {
    const by = { found: 0, wanted: 0, ignored: 0 };
    const every = songs.concat(Array.from(arrived.values())).filter(counted);
    for (const s of every) if (own.call(by, s.status)) by[s.status] += 1;
    const summary = byId("summary");
    summary.textContent = "";
    const stat = (n, word) => {
      const item = el("li", "stat");
      item.appendChild(el("b", null, n));
      item.appendChild(document.createTextNode(" " + word));
      summary.appendChild(item);
    };
    stat(every.length, every.length === 1 ? "song" : "songs");
    stat(by.found, "found");
    stat(by.wanted, "wanted");
    if (by.ignored) stat(by.ignored, "ignored");
    const when = String(data.generated || "").replace("T", " ").slice(0, 16);
    if (when) byId("updated").textContent = "Updated by caracole " + when + " UTC. ";
  };
  const smooth = () => (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? "auto" : "smooth");

  // The row of buttons, one line that scrolls sideways on a phone: which of its ends hide buttons.
  const chipRow = document.querySelector(".chips");
  const chipEdges = () => {
    if (!chipRow) return;
    const room = chipRow.scrollWidth - chipRow.clientWidth;
    chipRow.classList.toggle("more-start", room > 1 && chipRow.scrollLeft > 1);
    chipRow.classList.toggle("more-end", room > 1 && chipRow.scrollLeft < room - 1);
  };
  if (chipRow) {
    chipRow.addEventListener("scroll", chipEdges, { passive: true });
    if ("ResizeObserver" in window) new ResizeObserver(chipEdges).observe(chipRow);
  }
  // How many of the songs the search and filters match each button would show; a card drawn again changes it.
  let matchingNow = [];
  let shownNow = [];
  const tallyChips = () => {
    const tally = { all: matchingNow.filter((i) => counted(songs[i])).length, found: 0, wanted: 0, review: 0 };
    for (const i of matchingNow) {
      for (const k of ["found", "wanted", "review"]) if (SHOWS[k](songs[i])) tally[k] += 1;
    }
    // Needs review, only while a song does (or while it is the one pressed).
    const reviewing = songs.some((s) => SHOWS.review(s)) || Array.from(arrived.values()).some((s) => SHOWS.review(s));
    for (const chip of chips) {
      chip.setAttribute("aria-pressed", String(chip.dataset.show === state.show));
      chip.querySelector(".n").textContent = String(tally[chip.dataset.show]);
      chip.hidden = chip.dataset.show === "review" && !reviewing && state.show !== "review";
    }
    chipEdges();
  };
  // How many songs the list shows, of how many.
  const tell = () => {
    const total = songs.filter(counted).length;
    const n = shownNow.filter((i) => counted(songs[i])).length;
    count.textContent = n === total ? plural(total, "song") : n + " of " + plural(total, "song");
  };

  const render = () => {
    const query = parseQuery(state.q);
    const inKey = keyId(state.key);
    const fits = typedMatch(query);
    const matching = ORDERS[state.sort].filter((i) =>
      (!state.artist || String(songs[i].sortArtist || "") === state.artist) &&
      (!inKey || songKeys[i] === inKey) && fits(i));
    matchingNow = matching;
    tallyChips();
    const shown = matching.filter((i) => SHOWS[state.show](songs[i]));
    sort.value = state.sort;
    keySelect.value = state.key;
    // On a phone Key, Sort and the view are under View, which says a key chosen there.
    viewToggle.textContent = state.key && keyGroup(state.key) ? "View · " + keyGroup(state.key).name : "View";
    for (const button of viewButtons) button.setAttribute("aria-pressed", String(button.dataset.view === state.view));
    clear.hidden = !state.q;
    artistChip.hidden = !state.artist;
    artistChip.textContent = state.artist ? artistName(state.artist) + " ×" : "";
    artistChip.setAttribute("aria-label", state.artist ? "Show every artist, not only " + artistName(state.artist) : "");
    // Searching the sites, served: the results take the grid's place, its tools with it, until Escape.
    const searchingAll = Boolean(server) && state.all;
    document.body.classList.toggle("searching-all", searchingAll);
    drawBar(matching.length === 0, query.keys.length > 0);
    let answerInList = false;  // the file's line that searches the sites, in the list's empty state
    if (searchingAll) {
      drawResults(query, false);
      return;
    }

    // One grid, whatever the order, so the cards fill each row; the strip jumps to a letter's first card.
    // In rows, one list of rows.
    list.textContent = "";
    jump.textContent = "";
    const grid = el("div", state.view === "rows" ? "rows" : "grid");
    const letterOf = LETTERS[state.sort];
    const firsts = new Map();
    for (const i of shown) {
      const card = itemFor(i);
      if (letterOf) {
        const letter = String(songs[i][letterOf] || "#");
        if (!firsts.has(letter)) firsts.set(letter, card);
      }
      grid.appendChild(card);
    }
    if (shown.length) list.appendChild(grid);
    for (const [letter, card] of firsts) {
      const to = el("button", null, letter);
      to.type = "button";
      to.setAttribute("aria-label", "Jump to " + letter);
      to.addEventListener("click", () => {
        card.scrollIntoView({ block: "start", behavior: smooth() });
        card.focus({ preventScroll: true });  // so the next Tab goes on from this card
      });
      jump.appendChild(to);
    }
    jump.hidden = firsts.size < 2 || shown.length < JUMP_FROM;

    if (!songs.length) {
      list.appendChild(el("p", "empty", "No songs yet."));
      const hint = el("p", "empty-hint", "Add a line to wanted.txt, or run ");
      hint.appendChild(el("code", null, "caracole add ARTIST TITLE"));
      hint.appendChild(document.createTextNode("; the next run lists the song here."));
      list.appendChild(hint);
    } else if (!shown.length && matching.length) {
      // The words match songs that the status filter hides: offer them.
      list.appendChild(el("p", "empty", "No " + CHIP_TEXT[state.show] + " match “" + state.q + "”."));
      const n = matching.length;
      const all = el("button", "btn", "Show all " + n + " match" + (n === 1 ? "" : "es"));
      all.type = "button";
      all.addEventListener("click", () => {
        state.show = "all";
        render();
        save();
      });
      list.appendChild(all);
    } else if (!shown.length && state.artist) {
      // The artist filter hides what the search finds: say so, and offer every artist.
      const who = artistName(state.artist);
      list.appendChild(el("p", "empty", state.q ? "No songs of " + who + " match “" + state.q + "”."
        : "No songs of " + who + " here."));
      const every = el("button", "btn", "Look in every artist's songs");
      every.type = "button";
      every.addEventListener("click", () => {
        state.artist = "";
        render();
        save();
      });
      list.appendChild(every);
    } else if (!shown.length && state.key) {
      // The key filter hides them: offer every key.
      list.appendChild(el("p", "empty", "No songs in " + keyGroup(state.key).name +
        (state.q ? " match “" + state.q + "”." : ".")));
      const any = el("button", "btn", "Any key");
      any.type = "button";
      any.addEventListener("click", () => {
        state.key = "";
        render();
        save();
      });
      list.appendChild(any);
    } else if (!shown.length && state.q) {
      list.appendChild(el("p", "empty", "No songs match “" + state.q + "”."));
      if (!query.keys.length && server) {  // the offline indexes have no keys
        const go = button("Search the sites for “" + state.q.trim() + "”", "primary", () => enterAll());
        list.appendChild(go);
      } else if (!query.keys.length) {
        list.appendChild(fileAnswer(state.q.trim()));
        answerInList = true;
      }
    } else if (!shown.length) {
      list.appendChild(el("p", "empty", state.show === "review" ? "Nothing needs review." : "No songs here."));
    }
    shownNow = shown;
    tell();
    drawResults(query, answerInList);
  };

  let frame = 0;
  const update = () => {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      render();
      save();
    });
  };
  const setQuery = (q) => {
    input.value = q;
    state.q = q;
    if (state.all && !q.trim()) {  // out of the sites' results as Escape goes, with what their rows asked for
      leaveAll(false);
      return;
    }
    render();
    save();
  };
  setArtist = (key) => {
    state.artist = key;
    setQuery("");
  };
  artistChip.addEventListener("click", () => {
    state.artist = "";
    render();
    save();
  });
  viewToggle.addEventListener("click", () => {
    const open = viewToggle.getAttribute("aria-expanded") !== "true";
    viewToggle.setAttribute("aria-expanded", String(open));
    viewPanel.classList.toggle("open", open);
  });
  // The bar kept at the top gets its edge once the page scrolls under it.
  const edge = byId("bar-edge");
  const bar = document.querySelector(".searchbar");
  if (edge && bar && "IntersectionObserver" in window) {
    new IntersectionObserver((seen) => {
      bar.classList.toggle("stuck", !seen[seen.length - 1].isIntersecting);
    }).observe(edge);
  }
  input.value = state.q;
  input.addEventListener("input", () => {
    state.q = input.value;
    if (state.all && (!state.q.trim() || keyed(state.q))) {  // nothing the sites can search: your songs again
      leaveAll(false);
      return;
    }
    update();
  });
  clear.addEventListener("click", () => {
    setQuery("");
    input.focus();
  });
  for (const chip of chips) {
    chip.addEventListener("click", () => {
      state.show = chip.dataset.show;
      render();
      save();
    });
  }
  sort.addEventListener("change", () => {
    state.sort = SORTS.indexOf(sort.value) >= 0 ? sort.value : "artist";
    render();
    save();
  });
  keySelect.addEventListener("change", () => {
    state.key = keyGroup(keySelect.value) ? keyGroup(keySelect.value).value : "";
    render();
    save();
  });
  for (const button of viewButtons) {
    button.addEventListener("click", () => {
      state.view = VIEWS.indexOf(button.dataset.view) >= 0 ? button.dataset.view : "cards";
      render();
      save();
    });
  }

  // --- the bar: your songs as you type, the sites on Enter ---------------------------------------
  // Typing filters your songs, here, asking nothing. Enter, or Search all, searches the sites too: served, one
  // list under the bar, your songs first (as their own rows), then what caracole's offline indexes hold of
  // Ultimate Guitar, gtptabs.com and MuseScore (/api/search), following what you type a moment after you
  // stop, the newest query alone; on the file, which can ask nothing, the line that searches them. Enter
  // never spends a request: only a result's Get it does. Escape goes back to your songs.
  const normal = (text) => String(text).trim().replace(/\s+/g, " ");
  const say = (text) => {
    if (barStatus.textContent === text) return;
    barStatus.textContent = text;
    barStatus.title = text;  // one line on a phone: the whole of it on hovering
  };
  const drawBar = (none, key) => {
    const q = normal(state.q);
    allButton.classList.toggle("primary", Boolean(q) && none && !key);
    allButton.disabled = key;
    if (key) allButton.title = "The sites' indexes know no keys";
    else allButton.removeAttribute("title");
    if (server && state.all) return;  // the search of the sites says how it goes
    if (!q) say(server ? "Filter your songs; Enter searches the sites too" : "Filter your songs as you type");
    else if (key) say(none ? "None of yours match: the sites know no keys" : "A key filters your songs alone: the sites know no keys");
    else if (none) say(server ? "None of yours match: Enter searches the sites" : "None of yours match: see the line below");
    else if (!server && state.all) say("The sites need caracole serve: run the line below");
    else say(server ? "Enter or Search all looks on the sites too" : "Enter or Search all: the line that searches the sites");
  };
  // Each word in single quotes, as the Select bar copies its command: on the file, Copy selects it too.
  const copyText = (code, copy) => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(code.textContent).then(() => { copy.textContent = "Copied"; }, () => {});
    }
    const range = document.createRange();
    range.selectNodeContents(code);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  };
  // The file's answer to Enter: what to run where caracole runs, since searching the sites needs caracole serve.
  const fileAnswer = (q) => {
    const box = el("div", "file-answer");
    box.appendChild(el("p", null, "Searching Ultimate Guitar, gtptabs.com and MuseScore needs caracole serve. " +
      "Where caracole runs, this searches its copy of Ultimate Guitar's index:"));
    const line = el("div", "command");
    const code = el("code", null, "caracole search " + shellQuote(q));
    const copy = button("Copy", "small", () => copyText(code, copy), "Copy the line");
    line.appendChild(code);
    line.appendChild(copy);
    box.appendChild(line);
    const then = el("p", "hint", "Each hit comes with the line that adds it; ");
    then.appendChild(el("code", null, "caracole get 'Artist - Title'"));
    then.appendChild(document.createTextNode(" looks one up now."));
    box.appendChild(then);
    return box;
  };

  const MINE_SHOWN = 5;  // your songs at the top of the results; the grid has them all
  const SEARCH_PAUSE = 150;  // ms after the last key before the sites are searched
  const mineBox = el("div", "mine");
  const sitesBox = el("div", "sites");
  const group = (title, rows) => {
    const box = el("div", "rows");
    for (const row of rows) box.appendChild(row);
    return [el("h2", "group", title), box];
  };
  let asking = null;  // the search of the sites on its way, to abort
  let asked = 0;  // the newest search sent: an older one's answer is dropped
  let askTimer = 0;
  let askedFor = null;  // the query the newest search was sent for
  let answer = null;  // the answer on the screen, and its query
  let close = { q: null, ids: [] };  // your songs the server found (typos and all) for a query
  // Until the first answer since Enter, what goes under the results (the request form, the footer) waits too:
  // shown at once, the answer would only push it down.
  let waiting = true;
  const heard = () => {
    waiting = false;
    document.body.classList.remove("waiting-sites");
  };
  let settleSpots = () => {};
  let prefill = () => {};
  let getIt = () => {};
  let later = () => {};

  // Your songs that match what is typed, whatever the buttons show: the page's own rows, with what their cards
  // offer; then the server's close matches the filter missed.
  const drawMine = (query) => {
    const mine = ORDERS[state.sort].filter(typedMatch(query));
    const q = normal(state.q);
    const extra = close.q === q ? close.ids.map((id) => byIndex.get(id))
      .filter((i) => i !== undefined && mine.indexOf(i) < 0).slice(0, Math.max(0, MINE_SHOWN - mine.length)) : [];
    mineBox.textContent = "";
    if (mine.length) {
      mineBox.append(...group("In your library · " + mine.length, mine.slice(0, MINE_SHOWN).map(rowFor)));
      if (mine.length > MINE_SHOWN) {
        const every = el("p", "all-mine");
        every.appendChild(button("All " + mine.length + " of your songs", "small", () => leaveAll(true)));
        mineBox.appendChild(every);
      }
    }
    if (extra.length) {
      mineBox.append(...group(mine.length ? "Close to it, in your library" : "In your library, close to it",
        extra.map(rowFor)));
    }
  };
  const drawResults = (query, answerInList) => {
    const q = normal(state.q);
    const open = state.all && Boolean(q);
    if (!server) {  // the file: the line to run, above your songs, unless their empty list shows it already
      found.hidden = !open || answerInList;
      results.hidden = found.hidden;
      if (!found.hidden && found.dataset.query !== q) {
        found.replaceChildren(fileAnswer(q));
        found.dataset.query = q;
      }
      return;
    }
    results.hidden = !open;
    found.hidden = !open;
    document.body.classList.toggle("waiting-sites", open && waiting);
    if (!open) return;
    drawMine(query);
    askSources(false);
  };

  const askSources = (now) => {
    const q = normal(state.q);
    if (!now && q === askedFor) return;
    clearTimeout(askTimer);
    askTimer = setTimeout(() => sendAsk(q), now ? 0 : SEARCH_PAUSE);
  };
  const sendAsk = (q) => {
    if (!state.all || !q) return;
    askedFor = q;
    asked += 1;
    const mine = asked;
    if (asking) asking.abort();
    asking = new AbortController();
    say("Searching the sites…");
    found.setAttribute("aria-busy", "true");
    fetch("api/search?q=" + encodeURIComponent(q), {
      signal: asking.signal, credentials: "same-origin", cache: "no-store", headers: { Accept: "application/json" },
    }).then((r) => r.json().catch(() => null).then((body) => ({ ok: r.ok, status: r.status, body })))
      .then((reply) => {
        if (mine !== asked || !state.all) return;
        const data = reply.body && typeof reply.body === "object" ? reply.body : null;
        if (data && data.superseded) {  // another search went first: ask again, still the newest
          askTimer = setTimeout(() => sendAsk(q), SEARCH_PAUSE);
          return;
        }
        found.removeAttribute("aria-busy");
        heard();
        if (!reply.ok || !data || data.error) {
          say(failure(reply).line.text);
          return;
        }
        showSites(data, q);
      }, (e) => {
        if (mine !== asked || (e && e.name === "AbortError")) return;
        found.removeAttribute("aria-busy");
        heard();
        say(UNREACHABLE.line.text);
      });
  };
  // What a result's row stands for, the same in an older answer and a newer one: its site, its UG song, its names.
  const hitKey = (row) => [row.dataset.source, row.dataset.ug, row.querySelector(".row-title"),
    row.querySelector(".row-artist")].map((x) => (x && typeof x === "object" ? x.textContent : String(x || ""))).join("|");
  // The answer of the newest search, in one go: the old one stays until then, so nothing flashes.
  const showSites = (data, q) => {
    answer = { data, q };
    found.dataset.query = q;
    close = { q, ids: listOf(data.library).map((h) => Number(h && h.id)) };
    mineBox.hidden = false;
    drawMine(parseQuery(state.q));
    if (data.short) {
      sitesBox.replaceChildren();
      say("Type three letters or more to search the sites");
      return;
    }
    const objects = (value) => listOf(value).filter((x) => x && typeof x === "object");
    const artists = objects(data.artists);
    const index = objects(data.index);
    const gtp = objects(data.gtptabs);
    const ms = objects(data.musescore);
    const box = document.createDocumentFragment();
    // The artists the query names: first when one leads ("oasis"), after the songs when a song does.
    const named = artists.length ? group("Artists on Ultimate Guitar", artists.map((a) => artistHit(a, openArtist))) : [];
    if (data.lead === "artist") box.append(...named);
    if (index.length) box.append(...group("Ultimate Guitar · " + many(index.length, "song"), index.map((h) => ugHit(h, getIt, later))));
    if (data.lead !== "artist") box.append(...named);
    if (gtp.length) {
      box.append(...group("Guitar Pro on gtptabs.com · " + many(gtp.length, "song"), gtp.map((h) => siteHit(h, getIt, later))));
    }
    if (ms.length) {
      box.append(...group("MuseScore · " + many(ms.length, "page") + " by that title", ms.map((h) => siteHit(h, getIt))));
    }
    const left = objects(data.skipped);
    if (left.length) {
      box.appendChild(el("p", "skipped", "Not searched: " +
        left.map((x) => String(x.name || x.source) + " (" + String(x.why || "") + ")").join("; ") + "."));
    }
    if (typeof data.hint === "string" && data.hint) box.appendChild(prose("hint index-hint", data.hint));
    // A row whose request is on its way stays, its line in it, where the newer answer has it; one the newer
    // answer lacks becomes its card under the bar (settleSpots), its line going on there.
    const going = new Map();
    for (const [id, node] of spots) {
      if (sitesBox.contains(node) && views.has(id) && isActive(views.get(id))) going.set(hitKey(node), node);
    }
    for (const fresh of box.querySelectorAll(".hit")) {
      const was = going.get(hitKey(fresh));
      if (!was) continue;
      fresh.replaceWith(was);
      going.delete(hitKey(fresh));
    }
    sitesBox.replaceChildren(box);
    if (going.size) settleSpots(true);
    const parts = [];
    if (index.length || artists.length) parts.push((index.length + artists.length) + " on Ultimate Guitar");
    if (gtp.length) parts.push(gtp.length + " on gtptabs.com");
    if (ms.length) parts.push(ms.length + " on MuseScore");
    say(parts.length ? parts.join(" · ") : "Nothing on the sites: request it by name below");
    prefill(data.lead);
  };

  // An artist's songs in place of the sites' results, yours by them first; All results, or typing, brings
  // those back.
  const artistPage = (key, offset, signal) => fetch("api/artist?key=" + encodeURIComponent(key) + "&offset=" + offset,
    { signal, credentials: "same-origin", headers: { Accept: "application/json" } })
    .then((r) => r.json().catch(() => null).then((body) => ({ ok: r.ok, status: r.status, body })))
    .then((reply) => {
      if (!reply.ok || !reply.body || reply.body.error) {
        say(failure(reply).line.text);
        return null;
      }
      return reply.body;
    }, (e) => {
      if (!(e && e.name === "AbortError")) say(UNREACHABLE.line.text);
      return null;
    });
  const openArtist = (a) => {
    clearTimeout(askTimer);
    asked += 1;
    const mine = asked;
    if (asking) asking.abort();
    asking = new AbortController();
    say("Listing " + String(a.artist) + "'s songs…");
    artistPage(String(a.artist_key || ""), 0, asking.signal).then((page) => {
      if (page && mine === asked && state.all) showArtist(page);
    });
  };
  const backToResults = () => {
    if (answer) showSites(answer.data, answer.q);
    input.focus();
  };
  const showArtist = (page) => {
    const box = document.createDocumentFragment();
    const head = el("div", "artist-head");
    const name = el("h2", null, page.artist);
    name.tabIndex = -1;
    head.appendChild(name);
    head.appendChild(button("All results", "small", backToResults, "Back to all the results"));
    box.appendChild(head);
    const theirs = listOf(page.library).map((x) => byIndex.get(Number(x && x.id))).filter((i) => i !== undefined);
    if (theirs.length) box.append(...group("Yours by " + page.artist, theirs.map(rowFor)));
    const [heading, rows] = group("Ultimate Guitar, the most tabbed first", listOf(page.songs).map((h) => ugHit(h, getIt, later)));
    box.appendChild(heading);
    box.appendChild(rows);
    let listed = listOf(page.songs).length;
    if (listed < Number(page.total)) {
      const more = el("p", "more-songs");
      const go = button("Show more (" + (page.total - listed) + " left)", "small", () => {
        go.disabled = true;
        artistPage(String(page.artist_key), listed).then((next) => {
          go.disabled = false;
          if (!next || !rows.isConnected) return;
          for (const h of listOf(next.songs)) rows.appendChild(ugHit(h, getIt, later));
          listed += listOf(next.songs).length;
          if (listed >= next.total || !listOf(next.songs).length) more.remove();
          else go.textContent = "Show more (" + (next.total - listed) + " left)";
        });
      }, "Show more of " + page.artist + "'s songs");
      more.appendChild(go);
      box.appendChild(more);
    }
    mineBox.hidden = true;  // the query's songs of yours: back with All results
    sitesBox.replaceChildren(box);
    say(page.artist + ": " + many(page.total, "song"));
    name.focus();
  };

  // Searching the sites: on Enter, Search all or the address (#all=1); on Enter again, at once.
  const enterAll = () => {
    if (!normal(state.q) || keyed(state.q)) {  // the line under the box says why a key searches no site
      input.focus();
      return;
    }
    state.all = true;
    render();
    save();
    if (server) {
      prefill(answer && answer.q === normal(state.q) ? answer.data.lead : null);
      askSources(true);
    }
  };
  const leaveAll = (focus) => {
    if (!state.all) return;
    state.all = false;
    clearTimeout(askTimer);
    if (asking) asking.abort();
    asked += 1;
    askedFor = null;
    found.removeAttribute("aria-busy");
    waiting = true;
    document.body.classList.remove("waiting-sites");
    settleSpots();
    render();
    save();
    if (focus) input.focus();
  };
  if (server) {
    const head = el("div", "results-head");
    head.appendChild(button("Back to your songs", "small", () => leaveAll(true), "Back to your songs (Escape)"));
    found.append(head, mineBox, sitesBox);
  }
  allButton.addEventListener("click", enterAll);
  // A key that ends an input method's word (pinyin, kana) is still typing, never a command.
  const composing = (e) => e.isComposing || e.keyCode === 229;
  input.addEventListener("keydown", (e) => {
    if (composing(e)) return;
    if (e.key === "Enter") {
      e.preventDefault();
      enterAll();
    } else if (e.key === "ArrowDown" && state.all && server) {  // on to the first result's button
      const first = found.querySelector(".row-action button, .row-action a");
      if (first) {
        e.preventDefault();
        first.focus();
      }
    }
  });
  document.addEventListener("keydown", (e) => {
    if (composing(e)) return;
    const typing = document.activeElement === input;
    if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      input.focus();
      input.select();
    } else if (e.key === "Escape" && state.all) {
      e.preventDefault();  // a search field clears itself on Escape: here it keeps what you typed
      leaveAll(!typing && results.contains(document.activeElement));
    } else if (e.key === "Escape" && typing && input.value) {
      setQuery("");
    }
  });
  // --- caracole serve: what the page does with a request's answers ----------------------------
  const tray = byId("tray");
  const trayList = byId("tray-list");
  const traySum = byId("tray-sum");
  const trayToggle = byId("tray-toggle");
  const trayItems = new Map();  // job id -> its line in the list of requests
  const quiet = new Set();  // the lookups of a songbook's missing songs: its card says how they go
  let trayClosed = false;
  // The list of requests, once there are two or more: one line each, not read out (the cards' lines are). A
  // songbook's change, or a removal, is left out: its card, where it was asked for, says how it goes.
  const trayShow = (view) => {
    if (!tray || view.kind === "songbook" || view.kind === "remove" || quiet.has(Number(view.id))) return;
    const id = Number(view.id);
    let item = trayItems.get(id);
    if (!item) {
      item = el("li");
      item.appendChild(el("span", "tray-song", view.display || ""));
      item.appendChild(el("p", "progress"));
      trayItems.set(id, item);
      trayList.prepend(item);
    }
    // One Details link, the list's own: a line here says how its request goes, and its card links the rest.
    const line = view.line && typeof view.line === "object" ? view.line : {};
    showLine(item.querySelector(".progress"), { line: Object.assign({}, line, { details: null }) });
    const shown = Array.from(trayItems.keys()).map((n) => views.get(n)).filter(Boolean);
    const going = shown.filter(isActive).length;
    traySum.textContent = plural(shown.length, "request") + (going ? " · " + going + " to go" : " · all done");
    tray.hidden = trayClosed || shown.length < 2;
    document.body.classList.toggle("with-tray", !tray.hidden);
  };
  // The cards drawn again from what the library has now: a request is over. Each keeps its line. A removal
  // done leaves its song's card saying so; a songbook's change, the Songbooks section drawn again.
  const redraw = (view) => {
    if (view.kind === "remove" && songOf(view) !== null) {
      removing.delete(songOf(view));
      if (view.state === "done") {
        removed(songOf(view));
        return;
      }
    }
    if (view.kind === "songbook" && view.songbooks && typeof view.songbooks === "object") {
      drawSongbooks(view);
      return;
    }
    const data = view.card && typeof view.card === "object" ? view.card : null;
    if (!data) return;
    const i = byIndex.get(Number(data.id));
    if (i !== undefined) {
      songs[i] = data;
      songKeys[i] = keyId(data.key);
      hay[i] = String(data.search || "");
      if (cards.has(i)) cards.set(i, refill(cards.get(i), makeCard(data)));  // else drawn when shown
      if (rows.has(i)) rows.set(i, refill(rows.get(i), songRow(data)));
    } else {
      arrived.set(Number(data.id), data);  // counted, and shown under the form until the next load
    }
    const spot = spots.get(Number(view.id));  // a result's row stays a row: the song's own, now
    if (spot) spots.set(Number(view.id), refill(spot, spot.classList.contains("row") ? songRow(data) : makeCard(data)));
    summarize();
    tallyChips();  // the grid itself stays as it is: a card the filter now hides goes at the next search
  };
  const songOf = (view) => (view.songId === null || view.songId === undefined ? null : Number(view.songId));
  // Whether a job that is over brings what the page draws again: its song's card (none for a song the library
  // hasn't got), or the Songbooks section, for a songbook's change; a removal's song is gone, or as it was.
  const drawable = (view) => (view.kind === "songbook" ? Boolean(view.songbooks)
    : view.kind === "remove" || Boolean(view.card) || songOf(view) === null);
  const apply = (view) => {
    const id = Number(view.id);
    views.set(id, view);
    const song = songOf(view);
    if (song !== null) {
      if (!songJob.has(song) || songJob.get(song) <= id) songJob.set(song, id);
      if (!isActive(view)) busy.delete(song);
    }
    if (!isActive(view) && !settled.has(id) && drawable(view)) {
      settled.add(id);
      redraw(view);
    }
    paint(view);
  };
  // The job's line on the cards and rows that show it, and in the list of requests.
  const paint = (view) => {
    const id = Number(view.id);
    const song = songOf(view);
    const i = song !== null && songJob.get(song) === id ? byIndex.get(song) : undefined;
    for (const card of [i === undefined ? null : cards.get(i), i === undefined ? null : rows.get(i), spots.get(id)]) {
      if (!card || (song !== null && removals.has(song))) continue;  // its line counts down to its removal
      const p = progressIn(card);
      showLine(p, view);
      if (view.kind === "remove") continue;  // its buttons wait where they are: the card is gone once it is done
      const button = card.querySelector("form.fetch");
      if (button && isActive(view)) {
        if (button.contains(document.activeElement)) focusOn(p);  // the line takes the button's place
        button.remove();
      }
      const picker = card.querySelector("form.pick-form");
      if (picker && isActive(view)) {  // POST /review would refuse a pick now: the card is drawn again after
        const box = picker.closest("details.picker");
        if (box.contains(document.activeElement)) focusOn(p);
        box.remove();
        const pick = card.querySelector(".row-pick");  // a row's button that opened it
        if (pick) {
          if (pick.contains(document.activeElement)) focusOn(p);
          pick.remove();
        }
      }
    }
    if (i !== undefined && view.kind === "song") bookSongs(song, view);
    trayShow(view);
  };
  // A song's line in the songbooks that hold it too (each song of a songbook names its id, data-song), under its
  // name: Get the missing songs now's lookups show there. Not read out: its songbook's own line says how it goes.
  const bookSongLine = (li, view) => {
    const names = li.querySelector(".sb-names");
    if (!names) return;
    const line = names.querySelector(".progress") || names.appendChild(el("span", "progress"));
    const said = view.line && typeof view.line === "object" ? view.line : {};
    showLine(line, { line: Object.assign({}, said, { details: null }) });
  };
  const bookSongs = (song, view) => {
    for (const li of document.querySelectorAll('#songbooks li[data-song="' + Number(song) + '"]')) bookSongLine(li, view);
  };
  const requestsCount = (n) => {
    const nav = document.querySelector('.navlink[href="/jobs"]');
    if (!nav) return;
    let badge = nav.querySelector(".n");
    if (!n) {
      if (badge) badge.remove();
      return;
    }
    if (!badge) {
      badge = el("span", "n");
      nav.appendChild(badge);
    }
    badge.textContent = String(n);
  };

  // A song caracole removed: its card, and its row, say so until the page is loaded again, with nothing left to
  // open, fetch or pick (its files are gone, and so is its data-id, which the Select mode finds songs by).
  const goneItem = (s, asRow) => {
    const artist = listOf(s.artists).length > 1 ? listOf(s.artists).join(", ") : String(s.artist);
    if (asRow) {
      const row = resultRow({ title: s.title, artist, status: "removed" });
      row.classList.add("gone");
      return row;
    }
    const card = el("article", "card gone");
    card.tabIndex = -1;
    card.appendChild(plainHead(s.monogram, s.hue, s.title, artist));
    return card;
  };
  const removed = (id) => {
    const i = byIndex.get(id);
    if (i === undefined) return;
    songs[i] = Object.assign({}, songs[i], { status: "removed" });
    // Drawn again where it is, as tall as it was, its line where it was: nothing on the screen moves, seconds
    // after the tap.
    const gone = (old, asRow) => {
      const fresh = goneItem(songs[i], asRow);
      if (!old) return fresh;
      const tall = old.isConnected ? old.getBoundingClientRect().height : 0;
      const line = old.querySelector(".progress");
      const top = line && old.isConnected ? line.getBoundingClientRect().top : null;
      const kept = refill(old, fresh);
      if (tall) kept.style.minHeight = tall + "px";
      if (line) line.style.minHeight = "";  // the last thing on the card, which keeps the height: as tall as it says
      if (top !== null && line.isConnected) {  // measured before a frame is drawn: it never moves
        const drop = top - line.getBoundingClientRect().top;
        if (drop > 0) line.style.marginTop = drop + "px";
      }
      return kept;
    };
    cards.set(i, gone(cards.get(i), false));
    rows.set(i, gone(rows.get(i), true));
    summarize();
    tallyChips();
    tell();
  };

  // --- caracole serve: the songbooks' forms ---------------------------------------------------------
  // ↑, ↓, × and Rename or delete in the Songbooks section, and the Select bar's Make songbook (or Add to),
  // post with fetch() as Fetch now does: the songbook's card says how its change goes, on a line under its
  // name, its buttons put away until the change is over (each moves a song by its place now); a songbook on
  // its way gets a card at the end of the section. Once a change is over, /jobs.json gives the section as
  // the server draws it now (the job's `songbooks`): the HTML the page was served with, read by DOMParser,
  // which runs no script of it, and put in place card by card, a card with a line kept where it is around
  // it, so that its line goes on being read out to the last. The section is in the served page even with
  // no songbook, hidden, for the first one. Without JavaScript the forms post as forms, and the server
  // answers with the requests page.
  const SONGBOOK_FORM = /^\/songbook\/(make|add|move|remove|rename|delete|get)$/;
  // job id -> {book: the songbook it changes, card: its card, focus: the button sent, reveal: from the Select bar}
  const bookJobs = new Map();
  const shelf = () => {
    const section = byId("songbooks");
    const details = section ? section.querySelector(":scope > details") : null;
    const list = details ? details.querySelector(":scope > .sb-list") : null;
    return list ? { section, details, list } : null;
  };
  const bookCard = (name) => {
    const at = shelf();
    return (at && Array.from(at.list.children).find((c) => c.dataset.songbook === name)) || null;
  };
  // A songbook card's line, under its name, made the first time, as a song card's is (progressIn).
  const bookLine = (card) => {
    let p = card.querySelector(".progress");
    if (!p) {
      p = el("p", "progress");
      p.setAttribute("role", "status");
      const head = card.querySelector(".sb-head");
      if (head) head.after(p);
      else card.prepend(p);
    }
    return p;
  };
  const lockBook = (card, on) => {
    card.classList.toggle("sb-busy", on);
    for (const control of card.querySelectorAll("form button, form input")) control.disabled = on;
    const at = document.activeElement;
    if (on && at && at.disabled && card.contains(at)) focusOn(bookLine(card));  // a disabled button drops it
  };
  // Deleted, or never made: a songbook's card says so where it was, as tall as it was, so that what is under it
  // doesn't move, until the page is loaded again.
  const goneBook = (card) => {
    const line = bookLine(card);
    const tall = card.isConnected ? card.getBoundingClientRect().height : 0;
    if (tall) card.style.minHeight = tall + "px";
    if (card.contains(document.activeElement) && !line.contains(document.activeElement)) focusOn(line);
    for (const child of Array.from(card.children)) {
      if (!child.classList.contains("sb-head") && child !== line) child.remove();
    }
    card.classList.remove("sb-busy");
    card.classList.add("sb-gone");
  };
  // The card that shows a songbook's change (a new songbook's, made for it at the end of the section): its
  // line says how the change goes, the newest change's alone, and its buttons wait until it is over.
  const bookSpot = (view, hint, focus) => {
    const book = view.songbook && typeof view.songbook === "object" ? view.songbook : null;
    const at = shelf();
    if (!book || !at) return null;
    let card = bookCard(String(book.name));
    if (!card) {
      card = el("article", "sb-card");
      card.dataset.songbook = String(book.name);
      const head = el("div", "sb-head");
      head.append(el("h2", null, String(book.name)), el("p", "hint", hint || ""));
      card.appendChild(head);
      at.list.appendChild(card);
      at.section.hidden = false;
    }
    bookLine(card);
    if (isActive(view)) lockBook(card, true);
    for (const [id, other] of spots) if (other === card) spots.delete(id);
    spots.set(Number(view.id), card);
    bookJobs.set(Number(view.id), { book, card, focus: focus || "" });
    return card;
  };
  // A card keeps the height ``tall`` while it is taller than what it holds, until your next click or key, when what
  // moves under it moves for you; measured before a frame is drawn, so nothing moves meanwhile.
  const holdHeight = (card, tall) => {
    const was = card.style.minHeight;
    card.style.minHeight = "";
    if (!tall || card.getBoundingClientRect().height >= tall - 0.5) return;
    card.style.minHeight = Math.max(tall, parseFloat(was) || 0) + "px";
    const release = () => {
      document.removeEventListener("click", release, true);
      document.removeEventListener("keydown", release, true);
      if (!card.classList.contains("sb-gone")) card.style.minHeight = "";
    };
    document.addEventListener("click", release, true);
    document.addEventListener("keydown", release, true);
  };
  const drawSongbooks = (view) => {
    const at = shelf();
    if (!at) return;
    const page = new DOMParser().parseFromString(String(view.songbooks.html || ""), "text/html");
    const fresh = page.querySelector("#songbooks > details");
    const count = at.details.querySelector(":scope > summary .n");
    const counted = fresh ? fresh.querySelector(":scope > summary .n") : null;
    if (count) count.textContent = counted ? counted.textContent : "0";
    // What the section says besides its songbooks: a songbooks.toml that can't be read.
    for (const part of Array.from(at.details.children)) {
      if (part.tagName !== "SUMMARY" && part !== at.list) part.remove();
    }
    for (const part of fresh ? Array.from(fresh.children) : []) {
      if (part.tagName !== "SUMMARY" && !part.classList.contains("sb-list")) {
        at.details.insertBefore(document.importNode(part, true), at.list);
      }
    }
    const job = bookJobs.get(Number(view.id));
    if (job && job.book.action === "rename" && view.state === "done") job.card.dataset.songbook = String(job.book.after);
    const old = Array.from(at.list.children);
    const kept = old.filter((c) => c.querySelector(".progress"));  // a change's line: read out to the last
    const tall = new Map(kept.map((c) => [c, c.isConnected ? c.getBoundingClientRect().height : 0]));
    const order = (fresh ? Array.from(fresh.querySelectorAll(":scope > .sb-list > .sb-card")) : []).map((f) => {
      const card = document.importNode(f, true);
      const was = kept.find((c) => c.dataset.songbook === card.dataset.songbook);
      if (!was) return card;
      bookLine(card);  // where its line goes
      return refill(was, card);
    });
    for (const card of kept) {
      if (order.indexOf(card) >= 0) continue;
      goneBook(card);
      order.splice(Math.min(old.indexOf(card), order.length), 0, card);
    }
    for (const card of old) if (order.indexOf(card) < 0) card.remove();
    let before = null;
    for (const card of order) {  // in the server's order, a card kept moved only if its place changed
      const next = before ? before.nextElementSibling : at.list.firstElementChild;
      if (card !== next) at.list.insertBefore(card, next);
      before = card;
    }
    at.section.hidden = !order.length && !at.details.querySelector(".sb-error");
    // Drawn again, its songs' lines are back under their names, and a card that showed a change keeps the height it
    // had while it is taller than what it holds now (its songs' "missing" notes gone, say), until your next click
    // or key: nothing under it moves seconds after your tap (a songbook from the Select bar is stretched, below).
    for (const [song, id] of songJob) {
      const shown = views.get(id);
      if (shown && shown.kind === "song") bookSongs(song, shown);
    }
    for (const card of kept) {
      if (card.isConnected && !card.classList.contains("sb-gone") && !(job && job.reveal && card === job.card)) {
        holdHeight(card, tall.get(card));
      }
    }
    for (const [id, other] of bookJobs) {  // the songbooks of changes still on their way wait
      if (id !== Number(view.id) && other.card.isConnected && views.has(id) && isActive(views.get(id))) {
        lockBook(other.card, true);
      }
    }
    // The focus waited on the line: back on the button it was sent with, where it is now (↓ again, say).
    if (job && job.focus && document.activeElement === job.card.querySelector(".progress")) {
      const again = Array.from(job.card.querySelectorAll("button"))
        .find((b) => !b.disabled && (b.getAttribute("aria-label") || b.textContent) === job.focus);
      if (again) again.focus();
    }
    // Made, or added to, from the Select bar: the songbook scrolls into view whole, if its line is still where
    // you left it (scrolling moves nothing on the page, as a card growing over what is on the screen would).
    if (job && job.reveal && view.state === "done" && job.card.isConnected) {
      const at = bookLine(job.card).getBoundingClientRect();
      if (at.top >= 0 && at.bottom <= window.innerHeight) {
        job.card.scrollIntoView({ block: "nearest", behavior: smooth() });
      }
    }
    // A card stretched while its change ran keeps that height while it is taller than what it holds now, until
    // your next click or key, when what moves under it moves for you.
    if (job && job.reveal && !isActive(view) && job.card.style.minHeight) {
      const stretched = parseFloat(job.card.style.minHeight);
      job.card.style.minHeight = "";
      holdHeight(job.card, stretched);  // no frame drawn in between: nothing moves
    }
    // The Select bar's menu of songbooks follows.
    document.dispatchEvent(new CustomEvent("caracole:songbooks", { detail: { books: listOf(view.songbooks.books) } }));
  };

  let timer = 0;
  let misses = 0;
  let stopped = false;
  const pending = () => Array.from(watched).filter((id) => !settled.has(id));
  const schedule = (delay) => {
    if (timer || stopped || !pending().length) return;
    timer = setTimeout(poll, delay !== undefined ? delay : document.hidden ? BACKGROUND_POLL : POLL);
  };
  // The server can't answer this page any more (it restarted, or signs in again): say so on each line.
  const stop = (text) => {
    stopped = true;
    for (const id of pending()) apply(Object.assign({}, views.get(id), { line: { tone: "failed", text } }));
  };
  const poll = () => {
    timer = 0;
    const ask = pending();
    fetch("jobs.json?jobs=" + ask.join(","), {
      credentials: "same-origin", cache: "no-store",
      headers: { Accept: "application/json", "X-Caracole-Form-Token": String(server.csrf || "") },
    }).then((r) => r.json().catch(() => null).then((body) => ({ ok: r.ok, status: r.status, body })))
      .then((answer) => {
        if (answer.status === 401 || answer.status === 403) {
          stop(failure(answer).line.text);
          return;
        }
        if (!answer.ok || !answer.body) {
          const e = new Error(String(answer.status));
          e.said = answer.body && typeof answer.body.error === "string" ? answer.body.error : "";
          throw e;
        }
        misses = 0;
        requestsCount(Number(answer.body.active) || 0);
        const seen = new Set();
        for (const view of listOf(answer.body.jobs)) {
          if (!view || typeof view !== "object" || !watched.has(Number(view.id))) continue;
          seen.add(Number(view.id));
          apply(view);
        }
        for (const id of ask) if (!seen.has(id)) settled.add(id);  // forgotten: the server keeps the last few
        schedule();
      })
      .catch((e) => {
        // The server is restarting, or the network is down: ask again, less and less often. From the third
        // miss in a row the lines say so, until an answer gives them back.
        misses += 1;
        if (misses >= MISSES) {
          const text = e && e.said ? String(e.said) + " Trying again…" : UNREACHABLE_NOW;
          for (const id of pending()) paint(Object.assign({}, views.get(id), { line: { tone: "waiting", text } }));
        }
        schedule(Math.min(POLL * 2 ** misses, 30000));
      });
  };
  track = (view) => {
    watched.add(Number(view.id));
    trayClosed = false;
    apply(view);
    schedule();
  };

  if (server) {
    const requested = byId("requested");
    const requestedGrid = byId("requested-grid");
    const placeholder = (artist, title) => {
      const card = el("article", "card pending");
      card.appendChild(plainHead((artist.match(/[\p{L}\p{N}]/u) || ["?"])[0].toUpperCase(), 0, title, artist));
      showLine(progressIn(card), { line: { tone: "queued", text: "Sending…" } });
      return card;
    };
    // A result's request, its line in the result's own row, from "Sending…" on: ``view`` finds the job in the
    // answer.
    const askFrom = (path, fields, names, row, go, view) => {
      if (!row) return;
      const line = progressIn(row);  // in the page before its first words, so they are read out
      showLine(line, { line: { tone: "queued", text: "Sending…" } });
      if (row.contains(document.activeElement)) focusOn(line);  // a disabled button would drop it
      if (go) go.disabled = true;
      const body = new URLSearchParams({ csrf: String(server.csrf || "") });
      for (const name of names) {
        if (fields && fields[name] !== undefined && fields[name] !== null && fields[name] !== "") {
          body.set(name, String(fields[name]));
        }
      }
      fetch(path, { method: "POST", body, credentials: "same-origin", headers: { Accept: "application/json" } })
        .then((r) => r.json().catch(() => null).then((answer) => ({ ok: r.ok, status: r.status, body: answer })))
        .then((reply) => {
          const job = reply.ok && reply.body && view(reply.body);
          if (go) go.disabled = false;
          if (!job || typeof job !== "object") {
            showLine(progressIn(row), failure(reply));
            return;
          }
          if (go && go.closest(".row-action, .later")) go.remove();  // its line takes the button's place
          spots.set(Number(job.id), row);
          track(job);
        }, () => {
          if (go) go.disabled = false;
          showLine(progressIn(row), UNREACHABLE);
        });
    };
    // Get it: the song looked up now (POST /lookup, one caracole get), to its sheet; a version picked under "⋯" too.
    getIt = (pick, display, row, go) => askFrom("lookup", pick, ["song", "artist", "title", "ug", "tab"], row, go,
      (answer) => answer.view);
    // Add for tonight's run: the song into wanted.txt under the site's names (POST /request, not fetched now).
    later = (pick, display, row, go) => askFrom("request", pick, ["artist", "title"], row, go, (answer) => answer.job);
    // Back to your songs: a request's row in the results that is a song new to the library becomes its card
    // under the bar, which goes on saying how it goes; a song the grid has says it on its own card. With
    // ``dropped``, only the rows a newer answer left out, at once.
    settleSpots = (dropped) => {
      for (const [id, node] of Array.from(spots)) {
        const left = !node.isConnected && node.classList.contains("hit");  // a newer answer has no such row
        if (dropped ? !left : !left && !results.contains(node)) continue;
        const view = views.get(id);
        const song = view ? songOf(view) : null;
        if (song !== null && byIndex.has(song)) {
          spots.delete(id);
          continue;
        }
        const [artist, ...title] = String((view && view.display) || "").split(" - ");
        const card = song !== null && arrived.has(song) ? makeCard(arrived.get(song))
          : title.length ? placeholder(artist, title.join(" - ")) : placeholder("", artist);
        if (view) showLine(progressIn(card), view);
        requestedGrid.prepend(card);
        requested.hidden = false;
        spots.set(id, card);
      }
    };
    for (const view of listOf(server.jobs)) {
      if (!view || typeof view !== "object") continue;
      watched.add(Number(view.id));
      const song = songOf(view);
      if (view.kind === "songbook") {
        bookSpot(view);  // a songbook's change: on its songbook's card
      } else if (requestedGrid && isActive(view) && view.kind === "song" && (song === null || !byIndex.has(song))) {
        // A song new to the library, on its way since before this page loaded: its card under the form.
        const [artist, ...title] = String(view.display || "").split(" - ");
        const spot = title.length ? placeholder(artist, title.join(" - ")) : placeholder("", artist);
        requestedGrid.appendChild(spot);  // newest first, as they come
        requested.hidden = false;
        spots.set(Number(view.id), spot);
      }
      apply(view);
    }
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && timer) {
        clearTimeout(timer);
        timer = 0;
        poll();
      }
    });
    if (tray) {  // folded, on every width: the cards say how each goes, and it would cover them
      trayToggle.addEventListener("click", () => {
        const open = trayToggle.getAttribute("aria-expanded") !== "true";
        trayToggle.setAttribute("aria-expanded", String(open));
        trayList.hidden = !open;
        tray.classList.toggle("open", open);
      });
      byId("tray-close").addEventListener("click", () => {
        for (const [id, item] of trayItems) {
          if (!isActive(views.get(id) || {})) {
            item.remove();
            trayItems.delete(id);
          }
        }
        trayClosed = true;
        tray.hidden = true;
        document.body.classList.remove("with-tray");
      });
    }
    // The request form, under the results: a card for the song at once, under the bar, which says how its
    // request goes. It is filled in from what was searched ("Artist - Title", or the artist alone when an
    // artist leads, else the title), each field until you type into it yourself.
    const requestForm = document.querySelector("form.request-form");
    const typedInto = new Set();
    if (requestForm) {
      for (const name of ["artist", "title"]) {
        const field = requestForm.elements.namedItem(name);
        if (field) field.addEventListener("input", () => typedInto.add(name));
      }
      prefill = (lead) => {
        const q = normal(state.q);
        const [first, ...rest] = q.split(" - ");
        const values = rest.length ? { artist: first.trim(), title: rest.join(" - ").trim() }
          : lead === "artist" ? { artist: q, title: "" } : { artist: "", title: q };
        for (const name of ["artist", "title"]) {
          const field = requestForm.elements.namedItem(name);
          if (field && !typedInto.has(name)) field.value = values[name];
        }
      };
    }
    const refused = new Set();  // the cards of requests the server refused, gone at the next one
    // The card #requested shows already for the job's song (or, before the song is in the library, for the
    // same "Artist - Title"), if any: asked for again, it is the one that says how this request goes.
    const spotOf = (view) => {
      const song = songOf(view);
      for (const [id, card] of spots) {
        const was = views.get(id);
        if (!was || !card.isConnected || !requestedGrid.contains(card)) continue;
        const same = song !== null && songOf(was) !== null ? songOf(was) === song : was.display === view.display;
        if (same) return [id, card];
      }
      return null;
    };
    if (requestForm && requested) {
      requestForm.addEventListener("submit", (e) => {
        e.preventDefault();
        for (const card of refused) card.remove();
        refused.clear();
        const field = (name) => requestForm.elements.namedItem(name);
        const typed = (name) => String(field(name).value || "").trim().replace(/\s+/g, " ");
        let spot = placeholder(typed("artist"), typed("title"));
        requestedGrid.prepend(spot);
        requested.hidden = false;
        if (state.all) spot.scrollIntoView({ block: "nearest", behavior: smooth() });  // under the bar, in view
        const button = requestForm.querySelector('button[type="submit"]');
        button.disabled = true;
        send(requestForm).then((answer) => {
          button.disabled = false;
          const view = answer.ok && answer.body && answer.body.job;
          if (!view) {
            showLine(progressIn(spot), failure(answer));
            refused.add(spot);
            return;
          }
          for (const name of ["artist", "title", "album", "duration"]) field(name).value = "";
          typedInto.clear();
          const id = Number(view.id);
          const shown = spots.has(id) ? [id, spots.get(id)] : spotOf(view);
          if (shown) {  // asked for again: its card says how it goes, where it is, its line still in the page
            spot.remove();
            spot = shown[1];
            if (shown[0] !== id) spots.delete(shown[0]);
          } else {
            const i = songOf(view) === null ? undefined : byIndex.get(songOf(view));
            if (i !== undefined) spot = refill(spot, makeCard(songs[i]));  // a song the library has: its card
          }
          spots.set(id, spot);
          track(view);
        }, () => {
          button.disabled = false;
          showLine(progressIn(spot), UNREACHABLE);
          refused.add(spot);
        });
      });
    }
    // The songbooks' forms, and the Select bar's, once its own script has checked it (an unchecked form is
    // stopped there): posted as the page's script, they leave you where you are.
    document.addEventListener("submit", (e) => {
      const form = e.target;
      if (e.defaultPrevented || !(form instanceof HTMLFormElement)) return;
      if (!SONGBOOK_FORM.test(form.getAttribute("action") || "")) return;
      e.preventDefault();
      const bar = form.closest(".pickbar");
      const card = bar ? null : form.closest(".sb-card");
      const sent = e.submitter ? e.submitter.getAttribute("aria-label") || e.submitter.textContent : "";
      const songs = form.elements.namedItem("songs");
      const many = songs ? String(songs.value).split(",").filter(Boolean).length : 0;
      const sending = send(form);  // the form read as it is, before its fields wait
      if (card) {
        showLine(bookLine(card), { line: { tone: "queued", text: "Sending…" } });
        if (/\/get$/.test(form.getAttribute("action") || "")) {  // each song it looks up, at once, under its name
          for (const li of card.querySelectorAll("li[data-get]")) {
            bookSongLine(li, { line: { tone: "queued", text: "Sending…" } });
          }
        }
        lockBook(card, true);
      }
      const answered = (view, refusal) => {
        // The Select bar says why the server refused it; told it is on its way, it lets the picks go.
        if (bar) form.dispatchEvent(new CustomEvent("caracole:sent", { detail: { ok: Boolean(view), error: refusal } }));
        if (!view) {
          if (card) {
            lockBook(card, false);
            showLine(bookLine(card), { line: { tone: "failed", text: refusal } });
          }
          return;
        }
        const spot = bookSpot(view, plural(many, "song"), sent);
        if (spot && bar) {  // from the Select bar, the section opens on the songbook
          shelf().details.open = true;
          // Its foot at the screen's (its head at the top, if it is taller than the screen): what it gains once
          // the change is over, its files and its songs, grows below the screen, and nothing on it moves then;
          // the page scrolls it into view whole after that (drawSongbooks). Near the top of the page, which
          // can't scroll that far, it is stretched to the screen's foot instead, now, as you tap.
          const box = spot.getBoundingClientRect();
          const taller = box.height > window.innerHeight * 0.75;
          const reach = window.innerHeight - 16 - (box.top + window.scrollY);
          if (!taller && reach > box.height) spot.style.minHeight = reach + "px";
          spot.scrollIntoView({ block: taller ? "start" : "end", behavior: smooth() });
          focusOn(bookLine(spot));
          bookJobs.get(Number(view.id)).reveal = true;
        }
        track(view);
      };
      sending.then((answer) => {
        const view = answer.ok && answer.body && answer.body.job;
        answered(view && view.songbook ? view : null, failure(answer).line.text);
        // Get the missing songs now: each song's lookup, on its card, its row and its line in the songbook.
        for (const each of view && view.songbook ? listOf(answer.body.jobs) : []) {
          if (!each || typeof each !== "object") continue;
          quiet.add(Number(each.id));
          track(each);
        }
      }, () => answered(null, UNREACHABLE.line.text));
    });
    schedule();
  }
  summarize();
  render();
  // Back from a page of caracole serve's about a song (Remove's question): its card in view, and the focus
  // on it, as the A-Z strip leaves it; the address keeps the rest. In the next frame, once every script
  // has drawn what it draws above the list (the Songbooks section, opened as it was left).
  let back = NaN;
  try {
    back = Number(new URLSearchParams(location.hash.slice(1)).get("song"));
  } catch (err) {
    // A malformed address: nothing to show.
  }
  if (back) {
    requestAnimationFrame(() => {
      const i = byIndex.get(back);
      const item = i === undefined ? null : (state.view === "rows" ? rows : cards).get(i);
      if (item && item.isConnected) {
        item.scrollIntoView({ block: "center" });
        item.focus({ preventScroll: true });
      }
      save();
    });
  }
})();
"""

# --- songbooks: the Songbooks section, and the Select mode that makes one (songbook.py) ---------------

_SONGBOOK_STYLE = """
.songbooks { margin: 8px 0 0; border: 1px solid var(--border); border-radius: 16px; background: var(--surface); }
.songbooks > details > summary { display: flex; align-items: center; gap: 10px; min-height: 52px; padding: 0 16px;
  cursor: pointer; font-weight: 650; list-style: none; }
.songbooks > details > summary::-webkit-details-marker { display: none; }
.songbooks .sb-icon { display: inline-grid; place-items: center; width: 26px; height: 26px; border-radius: 8px;
  background: var(--raised); color: var(--accent); font-size: 1rem; line-height: 1; }
.songbooks summary .n { min-width: 22px; padding: 0 7px; border-radius: 999px; background: var(--raised);
  color: var(--muted); font-size: .78rem; line-height: 22px; text-align: center; font-variant-numeric: tabular-nums; }
.sb-list { display: grid; gap: 12px; padding: 0 16px 16px;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr)); }
.sb-card { display: flex; flex-direction: column; gap: 10px; min-width: 0; padding: 14px; border: 1px solid var(--border);
  border-radius: 14px; background: var(--bg); scroll-margin: 84px 0 16px; }
.sb-card h2 { margin: 0; font-size: 1.05rem; line-height: 1.3; overflow-wrap: anywhere; }
.sb-songs { margin: 0; padding: 0; list-style: none; }
.sb-songs li { display: flex; align-items: center; gap: 8px; min-height: 44px; padding: 2px 0;
  border-top: 1px solid var(--border); }
.sb-n { flex: none; min-width: 2ch; color: var(--muted); font-size: .8rem; text-align: right;
  font-variant-numeric: tabular-nums; }
.sb-names { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.sb-names .t { font-weight: 600; }
.sb-names .a, .sb-names .why { color: var(--muted); font-size: .88rem; }
.sb-songs .missing .t { color: var(--muted); font-weight: 500; }
/* A lookup of the song: how it goes, on one line whatever it says, so that the songbook keeps its height. */
.sb-names .progress { display: block; overflow: hidden; font-size: .8rem; white-space: nowrap; text-overflow: ellipsis; }
.sb-names .why { display: block; font-size: .8rem; font-style: italic; }
.sb-tools { flex: none; display: flex; gap: 4px; }
.sb-tools form, .sb-more form { margin: 0; }
.sb-btn { display: inline-grid; place-items: center; width: 44px; height: 44px; padding: 0; border-radius: 10px;
  border: 1px solid var(--border); background: var(--surface); color: var(--text); font: inherit; font-size: 1rem;
  cursor: pointer; }
.sb-btn:hover { border-color: var(--border-strong); }
/* While a change of the songbook is on its way (its line under its name says how it goes), its buttons wait. */
.sb-btn:disabled { color: var(--muted); border-style: dashed; cursor: default; }
.sb-gone { align-self: start; border-style: dashed; }
.sb-gone h2 { color: var(--muted); }
.sb-more > summary { min-height: 40px; align-content: center; color: var(--muted); font-size: .85rem; font-weight: 600;
  cursor: pointer; }
.sb-more form { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 8px; margin-top: 8px; }
.sb-more .f { flex: 1 1 180px; }
.sb-sure { display: flex; flex: 1 1 100%; align-items: center; gap: 10px; min-height: 44px; font-size: .9rem; }
.sb-sure input { flex: none; width: 22px; height: 22px; margin: 0; accent-color: var(--accent); }
.sb-error { margin: 0 16px 16px; color: var(--failed); font-weight: 600; overflow-wrap: anywhere; }
.pick { display: none; }
.selecting .card .mono { display: none; }
.selecting .pick { flex: none; position: relative; display: grid; place-items: center; width: 44px; height: 44px;
  border-radius: 12px; border: 2px solid var(--control-edge); background: var(--surface); cursor: pointer; }
.pick input { position: absolute; inset: 0; width: 100%; height: 100%; margin: 0; opacity: 0; cursor: pointer; }
.pick:focus-within { outline: 3px solid var(--focus); outline-offset: 2px; }
.pick-n { font-weight: 750; font-variant-numeric: tabular-nums; }
/* Picked, while selecting: out of the mode the picks wait, unseen, for when it is on again. */
.selecting .card.picked { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent); }
.picked .pick { border-color: var(--accent); background: var(--accent); color: var(--on-accent); }
/* While selecting, a card or a row is one target: a tap anywhere on it lands on it, and the Select script
   picks it or lets it go; only its box takes a tap of its own. What opens a file or acts on the song is put
   away, and so are the lines that say what to do about its match and the links of its request's line (which
   still says how the request goes), so that a pick never opens or fetches anything; a key pressed on what
   stays (its artist's filter) still does what it says. */
.selecting [data-picker] { cursor: pointer; -webkit-tap-highlight-color: transparent; -webkit-user-select: none;
  user-select: none; }
.selecting [data-picker] * { pointer-events: none; }
.selecting [data-picker] .pick, .selecting [data-picker] .pick * { pointer-events: auto; }
.selecting [data-picker] > .actions, .selecting [data-picker] > .more, .selecting [data-picker] > .foot,
.selecting [data-picker] > .picker, .selecting [data-picker] > .row-action, .selecting [data-picker] > .row-more,
.selecting [data-picker] > .row-panel, .selecting [data-picker] > .note, .selecting [data-picker] > .pick-hint,
.selecting [data-picker] .filter-mark, .selecting [data-picker] .progress a,
.selecting [data-picker] .progress .dot { display: none; }
.selecting [data-picker] .artist { min-height: 0; }  /* no target of its own: the card is */
/* A row's box stands where its source's mark was, beside the title and the artist (both lines on a phone). */
.selecting .row { grid-template-columns: 44px minmax(0, 1fr); grid-template-areas: "src title" "src sub"; }
.selecting .row > .source { display: none; }
.selecting .row > .pick { grid-area: src; align-self: center; }
.selecting .row.picked { background: var(--raised); box-shadow: inset 3px 0 0 var(--accent); }
@media (min-width: 900px) {
  .selecting .row { grid-template-columns: 44px minmax(0, 1.3fr) minmax(0, 1fr) minmax(0, 14rem);
    grid-template-areas: "src title artist meta"; }
}
.pick-toggle[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.selecting .page { padding-bottom: 104px; }
.selecting:has(.pickbar.open, .pick-command:not([hidden])) .page { padding-bottom: 300px; }
.pickbar { position: fixed; z-index: 10; left: 0; right: 0; bottom: 0; border-top: 1px solid var(--border);
  background: var(--surface); box-shadow: 0 -6px 24px rgb(0 0 0 / 14%);
  padding: 10px max(16px, env(safe-area-inset-right)) calc(10px + env(safe-area-inset-bottom))
    max(16px, env(safe-area-inset-left)); }
/* One line: the way out, the count, then the songbook's menu, its name and the buttons; on a phone a
   "Make songbook…" button in their place, which unfolds them under the line (.open), the bar growing upwards. */
.pickbar-in { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; max-width: 1320px; margin: 0 auto; }
.pick-done { flex: none; display: grid; place-items: center; width: 44px; height: 44px; margin-left: -8px; padding: 0;
  border: 0; border-radius: 12px; background: none; color: var(--muted); font: inherit; font-size: 1.5rem;
  line-height: 1; cursor: pointer; }
.pick-done:hover { background: var(--raised); color: var(--text); }
.pick-count { margin: 0 auto 0 0; font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
.pick-open { display: none; }
.pickbar-form { display: flex; flex: 1 1 340px; flex-wrap: wrap; align-items: center; gap: 8px; min-width: 0; margin: 0; }
.pickbar-form label { display: flex; flex: 1 1 150px; min-width: 0; }
.pickbar-form input, .pickbar-form select { width: 100%; min-width: 0; height: 44px; padding: 0 10px; border-radius: 10px;
  border: 1px solid var(--control-edge); background: var(--bg); color: var(--text); font: inherit; font-size: 1rem; }
.pick-error { flex-basis: 100%; margin: 0; color: var(--failed); font-size: .85rem; }
.pick-error:empty { display: none; }
/* The file's command to run: folded, on one line beside Copy; unfolded, it scrolls within the bar. */
.pick-command { flex-basis: 100%; display: flex; align-items: flex-start; gap: 8px; min-width: 0; }
.pick-command details { flex: 1 1 0; min-width: 0; }
.pick-command summary { display: flex; align-items: center; min-height: 36px; color: var(--muted); font-size: .88rem;
  font-weight: 600; list-style: none; cursor: pointer; }
.pick-command summary::-webkit-details-marker { display: none; }
.pick-command summary::before { content: "›"; flex: none; display: inline-block; width: 1em; font-size: 1.15rem;
  line-height: 1; text-align: center; }
.pick-command details[open] > summary::before { transform: rotate(90deg); }
.pick-command .hint { margin-top: 2px; }
.pick-command code { display: block; max-height: 30vh; margin-top: 4px; padding: 8px 10px; overflow-y: auto;
  user-select: all; -webkit-user-select: all; }
.pick-command .btn { flex: none; }
@media (max-width: 719px) {
  .pick-open { display: inline-flex; }
  .pickbar:not(.open) .pickbar-form, .pickbar:not(.open) .pick-command { display: none; }
  .pickbar-form { flex-basis: 100%; }
  /* Unfolded, the button is a caret that folds the fields away: the bar's one primary button makes the songbook. */
  .pickbar.open .pick-open { position: relative; width: 44px; min-height: 44px; padding: 0; }
  .pickbar.open .pick-open .pick-open-text { position: absolute; width: 1px; height: 1px; overflow: hidden;
    clip: rect(0 0 0 0); white-space: nowrap; }
  .pickbar.open .pick-open::after { content: ""; width: 12px; height: 7px; background: currentColor;
    clip-path: polygon(0 0, 100% 0, 50% 100%); }
}
@media (pointer: coarse) {
  .sb-more > summary, .pick-command summary { min-height: 44px; }
}
"""

# The Select mode: a box on each card (any element of #list with a data-id: a row too), and a bar to
# name the songbook. It goes with the page's own script, after it: it finds the cards by their song's
# id and builds everything with createElement and textContent, as the page does. While it is on, a tap
# anywhere on a card picks it (the stylesheet puts its files and actions away, and lets the taps through
# to the card). The bar is one line: on a phone, "2 selected · Make songbook…", which unfolds the menu
# and the name field. On caracole serve the bar posts the songbook (the server's token, the songs' ids
# in the order picked), with the page's script (its "caracole:sent" says how the server answered: on
# its way, the picks go and the mode ends; refused, the bar says why), and its menu follows the
# Songbooks section as the page draws it again ("caracole:songbooks"); on the file on disk it shows
# the caracole songbook command to run instead, folded beside Copy.
_SELECT_SCRIPT = r"""
(() => {
  "use strict";
  const byId = (id) => document.getElementById(id);
  const list = byId("list");
  const toolbar = document.querySelector(".toolbar");
  let data;
  try {
    data = JSON.parse(byId("songs").textContent);
  } catch (err) {
    return;
  }
  const songs = new Map((Array.isArray(data.songs) ? data.songs : []).map((s) => [String(s.id), s]));
  if (!list || !toolbar || !songs.size) return;
  const server = data.server && typeof data.server === "object" ? data.server : null;
  const names = (list) => (Array.isArray(list) ? list : []).map((b) => String(b && b.name || "")).filter(Boolean);
  const books = names(data.songbooks);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  // Each word in single quotes, each ' written '\'': bash and zsh expand ! even in double quotes.
  const shellQuote = (text) => "'" + String(text).replace(/'/g, "'\\''") + "'";
  const picked = [];  // song ids, in the order they were picked: the songbook's order
  let sending = false;  // on caracole serve, until the server answers the bar's form

  // Remember whether the Songbooks section was open, across reloads (the served page comes back to it).
  const shelf = document.querySelector("#songbooks > details");
  const OPEN = "caracole-library:songbooks-open";
  if (shelf) {
    try {
      if (localStorage.getItem(OPEN) === "1") shelf.open = true;
    } catch (err) { /* no storage */ }
    shelf.addEventListener("toggle", () => {
      try {
        localStorage.setItem(OPEN, shelf.open ? "1" : "0");
      } catch (err) { /* no storage */ }
    });
  }

  const toggle = el("button", "chip pick-toggle", "Select");
  toggle.type = "button";
  toggle.title = "Pick songs for a songbook";
  toggle.setAttribute("aria-pressed", "false");
  (toolbar.querySelector(".controls") || toolbar).prepend(toggle);

  const bar = el("section", "pickbar");
  bar.hidden = true;
  bar.setAttribute("aria-label", "Make a songbook");
  const inner = el("div", "pickbar-in");
  // The way out, as the Select button is, which the page has scrolled away by now: the picks stay.
  const done = el("button", "pick-done");
  done.type = "button";
  done.setAttribute("aria-label", "Leave Select");
  done.title = "Leave Select (the picks stay)";
  const cross = el("span", null, "×");
  cross.setAttribute("aria-hidden", "true");
  done.appendChild(cross);
  const count = el("p", "pick-count");
  count.setAttribute("aria-live", "polite");
  const form = el("form", "pickbar-form");
  form.id = "pickbar-form";
  // On a phone the menu and the name wait under this button, so that the bar is one line while you pick.
  const unfold = el("button", "btn primary pick-open");
  unfold.type = "button";
  unfold.setAttribute("aria-expanded", "false");
  unfold.setAttribute("aria-controls", form.id);
  const unfoldText = el("span", "pick-open-text", "Make songbook…");
  unfold.appendChild(unfoldText);
  const into = el("select", "pick-into");
  into.setAttribute("aria-label", "Into which songbook");
  into.appendChild(new Option("New songbook", ""));
  for (const name of books) into.appendChild(new Option(name, name));
  const intoLabel = el("label");
  intoLabel.appendChild(into);
  intoLabel.hidden = !books.length;
  const nameLabel = el("label");
  const nameInput = el("input", "pick-name");
  nameInput.type = "text";
  nameInput.maxLength = 80;
  nameInput.placeholder = "Songbook name";
  nameInput.autocomplete = "off";
  nameInput.setAttribute("aria-label", "The songbook's name");
  nameLabel.appendChild(nameInput);
  const submit = el("button", "btn primary", "Make songbook");
  submit.type = "submit";
  const clear = el("button", "btn", "Clear");
  clear.type = "button";
  const error = el("p", "pick-error");
  error.setAttribute("role", "alert");
  // The file's command, folded: one line of the bar, which Copy copies without unfolding it.
  const command = el("div", "pick-command");
  command.hidden = true;
  const commandFold = el("details");
  commandFold.appendChild(el("summary", null, "The command to run"));
  commandFold.appendChild(el("p", "hint", "Run it where caracole runs:"));
  const commandText = el("code");
  commandFold.appendChild(commandText);
  const copy = el("button", "btn small", "Copy");
  copy.type = "button";
  copy.setAttribute("aria-label", "Copy the command");
  copy.title = "Copy the command, to run where caracole runs";
  command.append(commandFold, copy);
  const fields = {};
  if (server) {
    form.method = "post";
    form.setAttribute("action", "/songbook/make");
    for (const name of ["csrf", "name", "songs"]) {
      const field = el("input");
      field.type = "hidden";
      field.name = name;
      form.appendChild(field);
      fields[name] = field;
    }
    fields.csrf.value = String(server.csrf || "");
  }
  form.append(intoLabel, nameLabel, submit, clear, error);
  inner.append(done, count, unfold, form, command);
  bar.appendChild(inner);
  document.body.appendChild(bar);

  const ordinal = (n) => {
    const tens = n % 100;
    return n + (tens >= 11 && tens <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" })[n % 10] || "th");
  };
  // Only what changed is touched: the list's observer sees every change to a card's children.
  const paint = (card) => {
    const at = picked.indexOf(card.dataset.id);
    const box = card.querySelector(".pick input");
    if (box && box.checked !== (at >= 0)) box.checked = at >= 0;
    const n = card.querySelector(".pick-n");
    const number = at >= 0 ? String(at + 1) : "";
    if (n && n.textContent !== number) n.textContent = number;
    // The box's name says its place too: the number on it is hidden from a screen reader.
    const said = card.querySelector(".pick-label");
    const s = songs.get(card.dataset.id);
    const name = s ? "Pick " + s.title + " by " + s.artist + (at >= 0 ? ", " + ordinal(at + 1) : "") : "";
    if (said && s && said.textContent !== name) said.textContent = name;
    if (card.classList.contains("picked") !== (at >= 0)) card.classList.toggle("picked", at >= 0);
  };
  const paintAll = () => {
    for (const card of list.querySelectorAll("[data-picker]")) paint(card);
    count.textContent = picked.length + " selected";
    submit.disabled = sending || !picked.length;
    const existing = into.value;
    submit.textContent = existing ? "Add to " + existing : "Make songbook";
    unfoldText.textContent = submit.textContent + "…";
    nameLabel.hidden = Boolean(existing);
    command.hidden = true;
  };
  const pick = (id, on) => {
    const at = picked.indexOf(id);
    if (on && at < 0) picked.push(id);
    if (!on && at >= 0) picked.splice(at, 1);
    error.textContent = "";
    paintAll();
  };
  // A box on each card, as the page's script puts them in the list (it keeps each card it made), once
  // Select is pressed: until then a card holds nothing to tick (the file's sends nothing, and a review's
  // picker is the card's only choice).
  const selecting = () => document.body.classList.contains("selecting");
  const decorate = () => {
    if (!selecting()) return;
    for (const card of list.querySelectorAll("[data-id]")) {
      const id = card.dataset.id;
      if (!songs.has(id)) continue;
      if (!card.dataset.picker) {
        card.dataset.picker = "1";
        const s = songs.get(id);
        const label = el("label", "pick");
        const box = el("input");
        box.type = "checkbox";
        const order = el("span", "pick-n");
        order.setAttribute("aria-hidden", "true");
        label.append(box, order, el("span", "visually-hidden pick-label", "Pick " + s.title + " by " + s.artist));
        box.addEventListener("change", () => pick(id, box.checked));
        (card.querySelector(".head") || card).prepend(label);
      }
      paint(card);
    }
  };
  new MutationObserver(decorate).observe(list, { childList: true, subtree: true });
  // A tap anywhere on a card while selecting: the stylesheet lets it through to the card itself, all but a
  // tap on its box, which ticks it alone. A key pressed on the card's artist, say, has that for its target, and
  // does what the artist's button says.
  list.addEventListener("click", (e) => {
    const card = e.target;
    if (!selecting() || !(card instanceof HTMLElement) || !card.dataset.picker) return;
    const box = card.querySelector(".pick input");
    if (box) box.click();  // its change event picks the song, or lets it go
  });

  // On a phone: whether the menu and the name show, unfolded under the bar's line by its button.
  const folds = () => getComputedStyle(unfold).display !== "none";
  const setOpen = (on, focus) => {
    bar.classList.toggle("open", on);
    unfold.setAttribute("aria-expanded", on ? "true" : "false");
    unfold.className = on ? "btn pick-open" : "btn primary pick-open";  // open, the button that makes it leads
    if (on && focus) (nameLabel.hidden ? into : nameInput).focus();
  };
  unfold.addEventListener("click", () => setOpen(!bar.classList.contains("open"), true));
  bar.addEventListener("keydown", (e) => {
    // A name may hold a "/", which elsewhere on the page goes to the search box.
    if (e.key === "/" && e.target === nameInput) e.stopPropagation();
    if (e.key === "Escape" && bar.classList.contains("open") && folds()) {
      setOpen(false);
      unfold.focus();
    }
  });

  const setMode = (on) => {
    document.body.classList.toggle("selecting", on);
    toggle.setAttribute("aria-pressed", on ? "true" : "false");  // its name stays "Select": pressed or not
    const inBar = bar.contains(document.activeElement);
    bar.hidden = !on;
    setOpen(false);
    if (!on && inBar) toggle.focus({ preventScroll: true });  // not lost with the bar
    decorate();
    paintAll();
  };
  toggle.addEventListener("click", () => setMode(!selecting()));
  done.addEventListener("click", () => setMode(false));
  clear.addEventListener("click", () => {
    picked.length = 0;
    paintAll();
  });
  into.addEventListener("change", paintAll);
  // The songbooks there are now, once the page has drawn the section again: the menu keeps its choice.
  document.addEventListener("caracole:songbooks", (e) => {
    const now = names(e.detail && e.detail.books);
    const chosen = into.value;
    while (into.options.length > 1) into.remove(1);
    for (const name of now) into.appendChild(new Option(name, name));
    into.value = now.indexOf(chosen) >= 0 ? chosen : "";
    intoLabel.hidden = !now.length;
    paintAll();
  });
  // The server's answer to the bar's form: on its way, the picks go and the mode ends (the page shows the
  // songbook in its section); refused, the bar says why, and the picks stay.
  form.addEventListener("caracole:sent", (e) => {
    sending = false;
    if (e.detail && e.detail.ok) {
      picked.length = 0;
      nameInput.value = "";
      into.value = "";
      setMode(false);
    } else {
      error.textContent = String(e.detail && e.detail.error || "");
      paintAll();
    }
  });
  copy.addEventListener("click", () => {
    // Without the clipboard (refused, or none), the command unfolds, selected, to copy by hand.
    const byHand = () => {
      commandFold.open = true;
      const range = document.createRange();
      range.selectNodeContents(commandText);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(commandText.textContent).then(() => { copy.textContent = "Copied"; }, byHand);
    } else {
      byHand();
    }
  });
  form.addEventListener("submit", (e) => {
    const existing = into.value;
    const name = existing || nameInput.value.split(/\s+/).filter(Boolean).join(" ");
    error.textContent = "";
    if (!picked.length) {
      e.preventDefault();
      error.textContent = "Pick a song or more first.";
      return;
    }
    if (!name || name.startsWith(".")) {
      e.preventDefault();
      error.textContent = name ? "A songbook's name can't start with a dot." : "Give the songbook a name.";
      nameInput.focus();
      return;
    }
    if (server) {
      form.setAttribute("action", existing ? "/songbook/add" : "/songbook/make");
      fields.name.value = name;
      fields.songs.value = picked.join(",");
      sending = true;
      submit.disabled = true;
      return;  // the page's script posts it, and its songbook's card says how it goes
    }
    e.preventDefault();
    const words = ["caracole songbook", existing ? "add" : "make", shellQuote(name)];
    for (const id of picked) words.push(shellQuote(songs.get(id).display));
    commandText.textContent = words.join(" ");
    commandFold.open = false;
    command.hidden = false;
    copy.textContent = "Copy";
  });
})();
"""

_PAGE_STYLE = _STYLE + _SONGBOOK_STYLE
_PAGE_SCRIPT = ROWS_SCRIPT + _SCRIPT + _SELECT_SCRIPT


def sha256_source(text: str) -> str:
    """A CSP source allowing exactly this inline script or stylesheet."""
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


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
