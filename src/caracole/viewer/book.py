"""songbook.html: a songbook as one page for the phone, each song in the sheet viewer.

The page opens on the contents, every song in the songbook's order; a song without a
sheet is named there as missing, and has no page. Each song with a sheet is a section
built the way ``page.build_viewer`` builds a sheet.html, with its own data block (its
key, its ``[transpose]``, its chords in every mode); the fingerings, which most songs
share, are one block for the page (``voicings``).

Without a script, the page is every song one after the other, with links between them,
and prints. With it (book.js), it shows the contents or one song, chosen by the address
(``#song-3``, ``#contents``), else the song you had open last. book.js runs before the
viewer's own script: it gives the song's elements the names the viewer looks for
(``sheet``, ``facts``, ``strip``, ``song``), hands it the fingerings, and swaps each
song's settings in and out of the one place the viewer keeps a page's, so every song
keeps its own transposition, mode and chords. Next and previous, a swipe or the arrow
keys go from song to song, skipping the missing ones; each step reloads the page, so
the viewer starts afresh on each song.

The page is self-contained and loads nothing, as a sheet.html: a Content-Security-Policy
with the hashes of its two scripts and two stylesheets. A server serves it only while it
is the page caracole wrote, with ``songbook_csp(page)``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from html import escape, unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote

from caracole.normalize import has_han
from caracole.viewer.page import (
    _CONTROLS,
    CREDIT_URL,
    _assets,
    _credit_notice,
    _data,
    _sha256,
    _sheet_html,
    _song_key,
    _texts,
)
from caracole.viewer.sheet import parse_sheet
from caracole.viewer.theory import key_name, parse_chord

HERE = Path(__file__).parent
LIBRARY_PAGE = "../../index.html"  # Library/_songbooks/<name>/songbook.html -> Library/index.html
VERSION = 3  # of the page's markup: a new one makes every songbook.html again


@dataclass(frozen=True)
class BookSong:
    """One song of the songbook: its sheet's ChordPro (``cho``, as caracole wrote it) or why it has none
    (``missing``), with the key info.json gives it and its ``[transpose]``. ``id`` names it the same
    wherever the songbook puts it: the page remembers the song you had open by it."""

    title: str
    artist: str
    cho: str | None = None
    key: str | None = None
    key_source: str | None = None
    transpose: int = 0
    missing: str | None = None
    id: str = ""


@lru_cache(maxsize=1)
def _book_assets() -> tuple[str, str]:
    return (HERE / "book.css").read_text(encoding="utf-8"), (HERE / "book.js").read_text(encoding="utf-8")


def assets_version() -> str:
    """What the page's scripts and stylesheets are, and its markup's version: a new one, and every
    songbook's page is made again."""
    digest = hashlib.sha256(str(VERSION).encode())
    for text in (*_assets(), *_book_assets()):
        digest.update(hashlib.sha256(text.encode("utf-8")).digest())
    return digest.hexdigest()


def songbook_csp(page: bytes) -> str:
    """The Content-Security-Policy header a server sends with ``page``, a songbook's page caracole wrote.

    It is the page's own policy, as its ``<meta>`` tag holds it (its two scripts and two
    stylesheets, by their hashes, and nothing else to load, no form to send, no base to change),
    with a sandbox, which a ``<meta>`` policy can't set: the page then runs in an origin of its
    own, with no cookie, no storage and no way to ask the server for anything. Its scripts still
    run; the address (``#song-3``) says which song it shows.

    The policy is the page's, not this caracole's: a page written before an upgrade carries the
    hashes of the scripts it was written with, until the next render writes it again. A page whose
    policy can't be read, or wouldn't fit in a header, gets a sandbox that runs and loads nothing.
    Serve only a page still as caracole wrote it (``songbook.pages_written``): anyone with a synced
    device can put a page of their own in the library, and its policy too.
    """
    found = _META_POLICY.search(page)
    try:
        policy = unescape(found.group(1).decode("utf-8")) if found else ""
    except UnicodeDecodeError:
        policy = ""
    return "sandbox allow-scripts; " + policy if _HEADER_TEXT.fullmatch(policy) else _NOTHING


# The page's own policy, as build_songbook writes it; what a header may hold (no line break); and the
# header for a page whose policy can't be read: a sandbox that runs and loads nothing.
_META_POLICY = re.compile(rb'<meta http-equiv="Content-Security-Policy" content="([^"<>]*)">')
_HEADER_TEXT = re.compile(r"[ -~]+")
_NOTHING = "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'"


def _policy() -> str:
    style, script = _assets()
    book_style, book_script = _book_assets()
    return (
        f"default-src 'none'; script-src {_sha256(book_script)} {_sha256(script)}; "
        f"style-src {_sha256(style)} {_sha256(book_style)}; base-uri 'none'; form-action 'none'"
    )


def build_songbook(name: str, songs: list[BookSong], *, pdf: str | None = None, cho: str | None = None) -> str:
    """The page of a songbook called ``name``: its contents, then each song with a sheet.

    ``pdf`` and ``cho`` name the songbook's PDF and ChordPro file beside the page, linked when given.
    """
    style, script = _assets()
    book_style, book_script = _book_assets()
    playable = [n for n, song in enumerate(songs, start=1) if song.cho is not None]
    voicings: dict[str, Any] = {}
    sections = []
    for i, n in enumerate(playable):
        prev = playable[i - 1] if i > 0 else None
        nxt = playable[i + 1] if i + 1 < len(playable) else None
        html, data = _song(songs[n - 1], n, len(songs), prev, nxt)
        voicings.update(data.pop("voicings"))
        sections.append(html + _json(f"data-{n}", data) + "</section>\n")
    count = f"{len(songs)} song{'' if len(songs) == 1 else 's'}"
    files = "".join(f'<a class="pdf" href="{escape(quote(f))}">{label}</a>\n'
                    for f, label in ((pdf, "PDF"), (cho, "ChordPro, for a songbook app")) if f)
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="color-scheme" content="light dark">\n<meta name="referrer" content="no-referrer">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{_policy()}">\n'
        f"<title>{escape(name)} · songbook</title>\n<style>{style}</style>\n<style>{book_style}</style>\n"
        "</head>\n<body>\n<div class=\"page\">\n"
        '<header class="head book-head">\n'
        f'<a class="back" href="{LIBRARY_PAGE}">‹ Library</a>\n'
        f"<h1>{escape(name)}</h1>\n<p class=\"artist\">Songbook · {count}</p>\n</header>\n"
        + _contents(songs, files)
        + "".join(sections)
        + _json("voicings", voicings)
        + '<footer class="foot">\n'
        + files
        + f'<p>Chord shapes from <a href="{CREDIT_URL}">chords-db</a>, © 2016 David Rubert, MIT licence.</p>\n'
        + f'<details class="licence"><summary>The chords-db licence</summary><pre>{escape(_credit_notice())}</pre></details>\n'
        + "<p>Keep this page private: the lyrics and chords are other people's work.</p>\n"
        + "</footer>\n</div>\n"
        + _CONTROLS
        + f"<script>{book_script}</script>\n<script>{script}</script>\n</body>\n</html>\n"
    )


def _json(element_id: str, data: Any) -> str:
    """A data block: every ``<`` written ``\\u003c``, so no text in it can end the block."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return f'<script type="application/json" id="{element_id}">{payload}</script>\n'


def _contents(songs: list[BookSong], files: str) -> str:
    items = []
    for n, song in enumerate(songs, start=1):
        names = (f'<span class="n">{n}</span><span class="t">{escape(song.title)}</span>'
                 f'<span class="a">{escape(song.artist)}</span>')
        if song.cho is None:
            why = escape(song.missing or "no sheet yet")
            items.append(f'<li class="missing"><span class="row">{names}<span class="why">Missing: {why}</span>'
                         "</span></li>")
        else:
            items.append(f'<li><a class="row" href="#song-{n}" data-id="{escape(song.id)}">{names}</a></li>')
    files_row = f'<p class="files">\n{files}</p>\n' if files else ""
    return (
        '<nav class="toc" id="contents" aria-labelledby="contents-title">\n'
        '<h2 class="lbl" id="contents-title">Contents</h2>\n'
        f'<ol class="toc-list">\n{chr(10).join(items)}\n</ol>\n{files_row}</nav>\n'
    )


def _song(song: BookSong, n: int, total: int, prev: int | None, nxt: int | None) -> tuple[str, dict[str, Any]]:
    """A song's section, without its closing tag, and its data (with its fingerings)."""
    sheet = parse_sheet(song.cho or "")
    chords = [parse_chord(name, strict=False) for name in sheet.chords]
    key, origin = _song_key(sheet, chords, song.key, song.key_source)
    data = _data(sheet, chords, key, origin, song.transpose)
    facts = []
    if key is not None:
        facts.append(f"Key <b>{escape(key_name(key))}</b> <span class=\"from\">{escape(origin or '')}</span>")
    if sheet.capo:
        facts.append(f"Capo <b>{sheet.capo}</b>")
    notice = (
        '<p class="notice">Auto-generated, unverified: caracole heard these chords in the recording.</p>\n'
        if sheet.auto else ""
    )
    lang = ' lang="zh"' if has_han(song.title + sheet.title + "".join(_texts(sheet))) else ""
    html = (
        f'<section class="song" id="song-{n}" data-n="{n}" data-id="{escape(song.id)}" '
        f'aria-labelledby="title-{n}">\n<header class="head">\n'
        + _pager("Songs", prev, nxt)
        + f'<p class="pos">Song {n} of {total}</p>\n'
        + f'<h2 class="title" id="title-{n}">{escape(song.title)}</h2>\n'
        + (f'<p class="artist">{escape(song.artist)}</p>\n' if song.artist else "")
        + f'<p class="facts" id="facts-{n}">{" · ".join(facts)}</p>\n</header>\n'
        + notice
        + f'<div class="strip" id="strip-{n}" hidden></div>\n'
        + f'<article class="sheet" id="sheet-{n}"{lang}>\n{_sheet_html(sheet)}</article>\n'
        + _pager("Songs, after the sheet", prev, nxt)  # at the end of a long sheet, no scrolling back up
    )
    return html, data


def _pager(label: str, prev: int | None, nxt: int | None) -> str:
    """Previous, Contents and Next: above a song's sheet, and again after it, each named for a screen reader."""
    return (
        f'<nav class="pager" aria-label="{escape(label)}">'
        + (f'<a href="#song-{prev}" rel="prev">‹ Previous</a>' if prev else '<span class="none"></span>')
        + '<a href="#contents">Contents</a>'
        + (f'<a href="#song-{nxt}" rel="next">Next ›</a>' if nxt else '<span class="none"></span>')
        + "</nav>\n"
    )
