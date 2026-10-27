"""songbook.html: a songbook as one page for the phone, each song in the sheet viewer.

The page opens on the contents, every song in the songbook's order, each with its artist,
key and capo on a line under its title; a song without a sheet is named there as missing,
and has no page. Each song with a sheet is a section
built the way ``page.build_viewer`` builds a sheet.html, with its own data block (its
key, its ``[transpose]``, the version it starts in, its chords in every mode); the fingerings,
which most songs share, are one block for the page (``voicings``), and so are the easy keys of each
instrument (``easy``), the same for every song with a key, and the names of its songs whose sheets are Chinese
(``song-names``, page.py ``names_table``: their titles and their artists' names, in the contents, the pagers and their
pages), which the page shows in the characters the viewer's Chinese characters chose.

Without a script, the page is every song one after the other, with links between them,
and prints. With it (book.js), it shows the contents or one song, chosen by the address
(``#song-3``, ``#contents``), else the song you had open last. book.js runs before the
viewer's own script: it gives the song's elements the names the viewer looks for
(``sheet``, ``facts``, ``strip``, ``song``), hands it the fingerings, and swaps each
song's settings in and out of the one place the viewer keeps a page's, so every song
keeps its own transposition, mode and chords. Next and previous, which name the song
they go to, a swipe or the arrow keys go from song to song, skipping the missing ones;
each step reloads the page, so the viewer starts afresh on each song.

The page is self-contained and loads nothing, as a sheet.html: a Content-Security-Policy
with the hashes of its six scripts (book.js, the viewer's strum.js, overlay.js, instruments.js, winds.js and
viewer.js) and
two stylesheets. A server serves it only while it is the page caracole wrote, with
``songbook_csp(page)``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from functools import lru_cache
from html import escape
from typing import Any
from urllib.parse import parse_qsl, quote

from caracole.inline import json_block
from caracole.viewer import page as viewer_page
from caracole.viewer.page import (
    _CONTROLS,
    HERE,
    LIBRARY_PAGE,
    _assets,
    _instruments,
    _overlay,
    _winds,
    _sound,
    _facts,
    _footer,
    _page,
    _read_song,
    _song_html,
    artist_line,
    is_chinese,
    names_table,
    viewer_csp,
    zh_attr,
)
from caracole.viewer.theory import Key, key_name
from caracole.viewer.version import Version, played_key, version_from_query

# What the page is made from besides the sheet viewer's own files (``page.BUILD_FILES``).
BOOK_FILES = (HERE / "book.py", HERE / "book.js", HERE / "book.css")


@dataclass(frozen=True)
class BookSong:
    """One song of the songbook: its sheet's ChordPro (``cho``, as caracole wrote it) or why it has none
    (``missing``), with its key (``keys.sheet_keys``) and its ``[transpose]``. ``start`` is the version the
    viewer starts it in (its songbook setting, else its own version: songbook.py ``Entry.version``), as the
    viewer's address writes one ("t=-2&mode=dorian&capo=0", viewer/version.py), None for its ``transpose``
    alone. ``id`` names it the same wherever the songbook puts it: the page remembers the song you had open by
    it."""

    title: str
    artist: str
    cho: str | None = None
    key: str | None = None
    key_source: str | None = None
    transpose: int = 0
    missing: str | None = None
    id: str = ""
    start: str | None = None


@lru_cache(maxsize=1)
def _book_assets() -> tuple[str, str]:
    return (HERE / "book.css").read_text(encoding="utf-8"), (HERE / "book.js").read_text(encoding="utf-8")


def assets_version() -> str:
    """What the page is made from besides its songs, as a SHA-256: the sheet viewer
    (``page.build_version``), then this module, its script and its stylesheet. An upgrade that
    changes any of them, and every songbook's page is made again, as every sheet.html is."""
    digest = hashlib.sha256(viewer_page.build_version().encode("utf-8"))
    for path in BOOK_FILES:
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


# The header a server sends with a songbook's page caracole wrote: its own policy (its three scripts and
# two stylesheets, by their hashes) in a sandbox, as a sheet.html's (``page.viewer_csp``).
songbook_csp = viewer_csp


def build_songbook(name: str, songs: list[BookSong], *, pdf: str | None = None, cho: str | None = None) -> str:
    """The page of a songbook called ``name``: its contents, then each song with a sheet.

    ``pdf`` and ``cho`` name the songbook's PDF and ChordPro file beside the page, linked when given.
    """
    style, script = _assets()
    book_style, book_script = _book_assets()
    playable = [(n, song.title) for n, song in enumerate(songs, start=1) if song.cho is not None]
    chinese = [name for song in songs if song.cho is not None and is_chinese(song.cho)
               for name in (song.title, song.artist)]
    names = names_table(bool(chinese), chinese)
    voicings: dict[str, Any] = {}
    easy: dict[str, Any] | None = None  # every song's alike: one block for the page
    wind_facts: dict[str, Any] | None = None  # so are the winds' fingerings and the harps' notes
    sections = []
    about: dict[int, str] = {}
    for i, (n, _) in enumerate(playable):
        prev = playable[i - 1] if i > 0 else None
        nxt = playable[i + 1] if i + 1 < len(playable) else None
        html, data, about[n] = _song(songs[n - 1], n, len(songs), prev, nxt, names)
        voicings.update(data.pop("voicings"))
        easy = data.pop("easy", easy)
        wind_facts = data.pop("winds", wind_facts)
        sections.append(html + json_block(f"data-{n}", data) + "</section>\n")
    count = f"{len(songs)} song{'' if len(songs) == 1 else 's'}"
    files = "".join(f'<a class="pdf" href="{escape(quote(f))}">{label}</a>\n'
                    for f, label in ((pdf, "PDF"), (cho, "ChordPro, for a songbook app")) if f)
    body = (
        '<div class="page">\n<header class="head book-head">\n'
        f'<a class="back" href="{LIBRARY_PAGE}">‹ Library</a>\n'
        f"<h1>{escape(name)}</h1>\n<p class=\"artist\">Songbook · {count}</p>\n</header>\n"
        + _contents(songs, about, files, names)
        + "".join(sections)
        + json_block("voicings", voicings)
        + (json_block("easy", easy) if easy is not None else "")
        + (json_block("winds", wind_facts) if wind_facts is not None else "")
        + (json_block("song-names", names) if names else "")
        + _footer(files)
        + "</div>\n"
        + _CONTROLS
    )
    return _page(f"{name} · songbook", body, styles=(style, book_style),
                 scripts=(book_script, _sound(), _overlay(), _instruments(), _winds(), script))


def _contents(songs: list[BookSong], about: dict[int, str], files: str,
              shown: dict[str, dict[str, str]] | None = None) -> str:
    """The contents: each song's number and title, and on a line under it, its artist and, for a song
    with a sheet, its key and capo (``about``, by number); a name the page's names convert marked so (``shown``)."""
    items = []
    for n, song in enumerate(songs, start=1):
        artist = (f"<span{mark}>{escape(song.artist)}</span>" if (mark := zh_attr(song.artist, shown))
                  else escape(song.artist))
        line = " · ".join(part for part in (artist, about.get(n, "")) if part)
        names = (f'<span class="n">{n}</span><span class="t"{zh_attr(song.title, shown)}>{escape(song.title)}</span>'
                 + (f'<span class="a">{line}</span>' if line else ""))
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


def _song(song: BookSong, n: int, total: int, prev: tuple[int, str] | None,
          nxt: tuple[int, str] | None, names: dict[str, dict[str, str]] | None = None
          ) -> tuple[str, dict[str, Any], str]:
    """A song's section, without its closing tag, its data (with its fingerings), and its key and capo
    as the contents give them. ``prev`` and ``nxt`` are the songs with a sheet around it: number, title; a name
    the page's ``names`` convert is marked so (page.py ``zh_attr``)."""
    sheet, key, origin, data = _read_song(song.cho or "", song.key, song.key_source, song.transpose)
    data["start"] = song.start  # where the viewer starts when the address names no version (as sheet.html)
    html = (
        f'<section class="song" id="song-{n}" data-n="{n}" data-id="{escape(song.id)}" '
        f'aria-labelledby="title-{n}">\n<header class="head">\n'
        + _pager("Songs", prev, nxt, names)
        + f'<p class="pos">Song {n} of {total}</p>\n'
        + f'<h2 class="title" id="title-{n}"{zh_attr(song.title, names)}>{escape(song.title)}</h2>\n'
        + artist_line(song.artist, names)
        + f'<p class="facts" id="facts-{n}">{_facts(key, origin, sheet.capo or 0)}</p>\n</header>\n'
        + _song_html(sheet, f"-{n}", song.title)
        + _pager("Songs, after the sheet", prev, nxt, names)  # at the end of a long sheet, no scrolling back up
    )
    return html, data, _key_and_capo(key, _opens_in(song), sheet.capo)


def _opens_in(song: BookSong) -> Version:
    """The version the viewer opens the song in, as viewer.js reads its data: its ``start``, at its
    ``transpose`` where that names no ``t``; else its ``transpose``."""
    if not song.start:
        return Version(t=song.transpose)
    version = version_from_query(song.start)
    query = song.start[1:] if song.start[:1] in ("#", "?") else song.start
    named = {name for name, _ in parse_qsl(query, keep_blank_values=True)}
    return version if "t" in named else replace(version, t=song.transpose)


def _key_and_capo(key: Key | None, version: Version, capo_sheet: int | None) -> str:
    """"Em · capo 2", as the contents give a song: the key of the shapes the viewer opens it in (``version``,
    as the songbook's PDF plays it: ``version.played_key``) and its capo. A screen reader hears "key Em"."""
    shown, capo = played_key(version, key, capo_sheet)
    parts = []
    if shown is not None:
        parts.append(f'<span class="vh">key </span>{escape(key_name(shown))}')
    if capo:
        parts.append(f"capo {capo}")
    return " · ".join(parts)


def _pager(label: str, prev: tuple[int, str] | None, nxt: tuple[int, str] | None,
           names: dict[str, dict[str, str]] | None = None) -> str:
    """Previous, Contents and Next, above a song's sheet and again after it, each named for a screen reader:
    "‹ Title" and "Next: Title ›", the songs they go to, a title too long for the phone cut short ("…")
    by book.css. The arrows are hidden from a screen reader, which hears "Previous: Title"."""
    return (
        f'<nav class="pager" aria-label="{escape(label)}">'
        + (f'<a href="#song-{prev[0]}" rel="prev"><span class="arrow" aria-hidden="true">‹ </span>'
           f'<span class="vh">Previous: </span><span class="name"{zh_attr(prev[1], names)}>{escape(prev[1])}</span></a>'
           if prev else '<span class="none"></span>')
        + '<a href="#contents">Contents</a>'
        + (f'<a href="#song-{nxt[0]}" rel="next"><span class="lead">Next: </span>'
           f'<span class="name"{zh_attr(nxt[1], names)}>{escape(nxt[1])}</span>'
           '<span class="arrow" aria-hidden="true"> ›</span></a>'
           if nxt else '<span class="none"></span>')
        + "</nav>\n"
    )
