"""The library page's Songbooks section: each songbook of songbooks.toml as a card, in index.html
(library_page.py) and in caracole serve's ``/jobs.json``, which gives it drawn again once a songbook's
change is over (web/app.py).

Its style is library_assets/songbooks.css; the page's script draws it again from this HTML
(library.js's ``drawSongbooks``), and select.js makes a songbook from the page. The HTML is written
here, every text in it escaped.
"""

from __future__ import annotations

import html as html_text
import sqlite3
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from caracole.config import Config
from caracole.overrides import Overrides

if TYPE_CHECKING:
    from caracole.library_page import WebControls


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
    from caracole.library_page import _file_names  # which imports this module
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
