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
pinyin for Chinese ("ban ma ban ma", "banma"). The page folds what you type the
same way, so "musica" finds "Música" and "ban ma" finds 斑马，斑马.
Of a song's key, the string holds only the mode ("minor"): the script reads a
key typed in the box ("a minor", "f#m") and compares it, as the Key menu does,
by the tonic's pitch class and the mode, so "Gb minor" finds "F# minor".

The songs are one grid of cards, as many columns as the screen holds, in every
order: a section per artist left one narrow card per row on a desktop. Each
card has its artist's monogram, in a colour of that artist's, and an A-Z strip
jumps to the first card of a letter.

``caracole serve`` serves the same page with ``controls`` (``WebControls``): a
form to request a song, a "Fetch now" button on each wanted song, and a CSP
that lets the forms post to the server (``form-action 'self'``). The file on
disk has neither, and lets no form be sent.
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
from caracole.inbox import SCORE_EXTENSIONS
from caracole.keys import SongKey, key_name, song_key
from caracole.library import song_dir, write_atomic
from caracole.musescore import song_pages
from caracole.normalize import clean_title, fold, has_han, romanize, slug_key
from caracole.overrides import Overrides
from caracole.songs import Song, list_songs
from caracole.todo import search_links, songs_to_buy

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
_WORD = re.compile(r"[^\W_]+")
HUES = 8  # monogram colours, .hue-0 to .hue-7


@dataclass(frozen=True)
class WebControls:
    """What ``caracole serve`` adds to the page it serves (caracole/web/).

    ``csrf`` is the token every form posts back; ``busy`` holds the songs with a
    fetch queued or running, whose cards say so instead of offering another;
    ``active`` is how many requests are queued or running, for the masthead;
    ``held`` holds the songs a fetch must wait for a review of, whose cards say so.
    """

    csrf: str
    busy: frozenset[int] = frozenset()
    active: int = 0
    held: frozenset[int] = frozenset()


def build_library_page(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, now: datetime, *,
                       controls: WebControls | None = None) -> str:
    """The whole page: every song, its files, and the links to find what's missing.

    With ``controls``, the page ``caracole serve`` serves: the same, with its forms.
    """
    pages = _guitar_pro_pages(conn)
    sources = _downloaded(conn)
    library = list_songs(conn)
    keys = {s.id: song_key(conn, cfg.library_dir, s) for s in library}
    to_buy = {s.id for s in songs_to_buy(conn, library, overrides, now)[0]}  # the to-do page's buy list
    musescore = cfg.provider("musescore").enabled
    songs = [_song(cfg.library_dir, s, overrides, keys.get(s.id), pages.get(s.id, []), s.id in to_buy,
                   sources.get(s.id, {}), _musescore_links(conn, s, overrides) if musescore else [])
             for s in library]
    data: dict[str, Any] = {
        "generated": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fold": {c: fold(c) for c in _TRANSLITERATED},
        "songs": songs,
    }
    if controls is not None:
        data["server"] = {"csrf": controls.csrf, "busy": sorted(controls.busy), "active": controls.active}
        for song in songs:
            song["fetchable"] = song["id"] not in controls.held
    books, data["songbooks"] = songbooks_section(conn, cfg, overrides, controls)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    csp = _CSP.replace("__FORMS__", "'self'" if controls is not None else "'none'")
    return (
        _HEAD.replace("__CSP__", csp).replace("__STYLE__", _PAGE_STYLE)
        + _BODY.replace("__NAV__", _nav(controls)).replace("__REQUEST__", _request_form(controls))
        .replace("__SONGBOOKS__", books)
        + f'<script type="application/json" id="songs">{payload}</script>\n'
        + f"<script>{_PAGE_SCRIPT}</script>\n</body>\n</html>\n"
    )


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
    return [{"label": f"{p.path.removeprefix('song/')} (possible match)", "href": p.url} for p in song_pages(conn, song)]


def _song(library_dir: Path, song: Song, overrides: Overrides, key: SongKey | None,
          guitar_pro: list[dict[str, str]], for_buying: bool, sources: dict[str, str],
          musescore: list[dict[str, str]]) -> dict[str, Any]:
    """One song's card; ``for_buying`` when the to-do page's buy list holds it (``todo.songs_to_buy``),
    ``sources`` the site each file caracole downloaded for it came from, by name, and ``musescore``
    the song's MuseScore pages.

    ``key`` and ``key_source`` are the song's key and where it came from, as in its info.json.
    """
    title = clean_title(song.title)
    status = "ignored" if song.key in overrides.ignore else song.status
    names = _file_names(song_dir(library_dir, song))
    has_sheet = any(n in names for n in _HUMAN_SHEETS + _AUTO_SHEETS)
    links: list[dict[str, str]] = []
    buy: list[dict[str, str]] = []
    if not has_sheet and status != "ignored":
        found = search_links(song.artist, song.title)
        links = [{"label": "Chordify", "href": found["chordify"]}, {"label": "YouTube", "href": found["youtube"]}]
        if for_buying:  # not while caracole may still find a sheet, nor once you have the audio
            buy = [{"label": label, "href": found[name]}
                   for label, name in (("Bandcamp", "bandcamp"), ("Qobuz", "qobuz"), ("iTunes", "itunes"))]
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
        "files": _files(library_dir, song, names, sources),
        "guitarPro": guitar_pro,
        "museScore": musescore,
        "links": links,
        "buy": buy,
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
    }


def _file_names(folder: Path) -> set[str]:
    try:
        return {p.name for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")}
    except OSError:  # no folder yet
        return set()


def _files(library_dir: Path, song: Song, names: set[str], sources: dict[str, str]) -> list[dict[str, Any]]:
    """Links to the kept files that exist, as paths relative to index.html, percent-encoded. The
    primary one is the sheet's PDF, else its text: never a score, whatever its format."""
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
        {"name": n, "label": _label(n, sources.get(n)), "href": f"{base}/{quote(n, safe='')}", "primary": n == primary}
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
        pages.setdefault(v["song_id"], []).append({"label": text, "href": url})
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

# Shared with the pages caracole serve writes itself (caracole/web/): colours, type, buttons.
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
.f input { width: 100%; height: 44px; padding: 0 12px; border-radius: 10px; border: 1px solid var(--border-strong);
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
@media (prefers-reduced-motion: no-preference) {
  .btn, .navlink { transition: background-color .12s, border-color .12s; }
}
"""

_STYLE = BASE_STYLE + """
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
.stat { padding: 3px 10px; border-radius: 999px; background: var(--raised); color: var(--muted); font-size: .82rem;
  font-variant-numeric: tabular-nums; }
.stat b { color: var(--text); font-weight: 650; }
.request { margin: 8px 0 0; border: 1px solid var(--border); border-radius: 16px; background: var(--surface); }
.request > summary { display: flex; align-items: center; gap: 10px; min-height: 52px; padding: 0 16px; cursor: pointer;
  font-weight: 650; list-style: none; }
.request > summary::-webkit-details-marker { display: none; }
.plus { display: inline-grid; place-items: center; width: 26px; height: 26px; border-radius: 8px;
  background: var(--accent); color: var(--on-accent); font-size: 1.15rem; line-height: 1; }
.request[open] > summary .plus { transform: rotate(45deg); }
.request-form { display: grid; gap: 12px; padding: 0 16px 16px; }
.fields { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 220px), 1fr)); }
.request-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 20px; }
.check { display: inline-flex; align-items: center; gap: 8px; min-height: 44px; font-weight: 600; cursor: pointer; }
.check input { width: 20px; height: 20px; margin: 0; accent-color: var(--accent); }
.hint { margin: 0; color: var(--muted); font-size: .85rem; }
.searchbar { position: sticky; top: 0; z-index: 2; background: var(--bg); padding: 12px 0 10px; }
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
.toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 12px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { display: inline-flex; align-items: center; gap: 6px; min-height: 40px; padding: 0 14px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface); color: var(--text); font: inherit; font-size: .9rem;
  cursor: pointer; }
.chip .n { color: var(--muted); font-variant-numeric: tabular-nums; }
.chip[aria-pressed="true"] { background: var(--text); border-color: var(--text); color: var(--bg); }
.chip[aria-pressed="true"] .n { color: inherit; opacity: .75; }
.chip.person { border-color: var(--accent); color: var(--accent); font-weight: 600; }
.sort { display: inline-flex; align-items: center; gap: 8px; margin-left: auto; color: var(--muted); font-size: .9rem; }
.controls { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px 12px; margin-left: auto; }
.sort select { min-height: 40px; padding: 0 10px; border-radius: 10px; border: 1px solid var(--border);
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
.artist { display: inline; margin: 2px 0 0; padding: 0; border: 0; background: none; color: var(--muted); font: inherit;
  font-size: .9rem; text-align: left; overflow-wrap: anywhere; cursor: pointer; }
.artist:hover { color: var(--text); text-decoration: underline; text-underline-offset: 2px; }
.badges { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; flex: none; max-width: 42%; }
.facts { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 0; color: var(--muted); font-size: .85rem; }
.facts .key, .facts .transpose { color: var(--text); font-weight: 600; }
.note { margin: 0; color: var(--review); font-size: .85rem; }
.busy { margin: 0; color: var(--wanted); font-size: .88rem; font-weight: 600; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
.actions form { margin: 0; }
.subhead { margin: 2px 0 -2px; color: var(--muted); font-size: .75rem; font-weight: 650; letter-spacing: .06em;
  text-transform: uppercase; }
.more { margin-top: auto; padding-top: 6px; border-top: 1px solid var(--border); }
.more > summary { display: flex; align-items: center; gap: 4px; min-height: 32px; color: var(--muted);
  font-size: .85rem; font-weight: 600; list-style: none; cursor: pointer; }
.more > summary::-webkit-details-marker { display: none; }
.more > summary::before { content: "›"; display: inline-block; width: 1em; font-size: 1.15rem; line-height: 1;
  text-align: center; }
.more[open] > summary::before { transform: rotate(90deg); }
.more > .subhead { margin: 8px 0 6px; }
.empty { margin: 32px 0 8px; font-size: 1.05rem; }
.empty-hint { margin: 0; color: var(--muted); }
@media (min-width: 720px) {
  .jump { flex-wrap: wrap; overflow: visible; }
}
@media (prefers-reduced-motion: no-preference) {
  .plus { transition: transform .15s; }
}
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
  const sort = byId("sort");
  const count = byId("count");
  const jump = byId("jump");
  const chips = Array.from(document.querySelectorAll(".chip[data-show]"));
  const artistChip = byId("artist");

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
  const shellQuote = (text) => '"' + text.replace(/(["\\$`])/g, "\\$1") + '"';
  const hay = songs.map((s) => String(s.search || ""));

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
  const songKeys = songs.map((s) => keyId(s.key));

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
    return a;
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
    return form;
  };

  let setArtist = () => {};
  const makeCard = (s) => {
    const card = el("article", "card");
    card.dataset.status = String(s.status);
    card.dataset.id = String(s.id);
    card.tabIndex = -1;  // the A-Z strip moves the focus to it
    const head = el("div", "head");
    const hue = Number.isInteger(s.hue) && s.hue >= 0 && s.hue < 8 ? s.hue : 0;
    const mono = el("span", "mono hue-" + hue, s.monogram || "");
    mono.setAttribute("aria-hidden", "true");
    head.appendChild(mono);
    const names = el("div", "names");
    names.appendChild(el("h2", null, s.title));
    const artists = listOf(s.artists);
    const who = el("button", "artist", artists.length > 1 ? artists.join(", ") : s.artist);
    who.type = "button";
    who.title = "Show only " + String(s.artist) + "'s songs";
    who.addEventListener("click", () => {
      setArtist(String(s.sortArtist || ""));
      window.scrollTo(0, 0);
    });
    names.appendChild(who);
    head.appendChild(names);
    const badges = el("div", "badges");
    badges.appendChild(el("span", "badge " + String(s.status), label(STATUS_TEXT, s.status) || s.status));
    if (SHOWS.review(s)) badges.appendChild(el("span", "badge review", "Needs review"));
    if (s.auto) badges.appendChild(el("span", "badge auto", "Auto sheet"));
    head.appendChild(badges);
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
    if (SHOWS.review(s)) {
      const note = el("p", "note", "caracole isn't sure about this match: see the ");
      const todo = el("a", null, "to-do page");
      todo.href = "_todo.md";
      note.appendChild(todo);
      note.appendChild(document.createTextNode(", or run caracole review."));
      card.appendChild(note);
    }

    const actions = el("div", "actions");
    if (server && s.status === "wanted") {
      if (busy.has(Number(s.id))) {
        const note = el("p", "busy", "Fetching… ");
        const jobs = el("a", null, "see the requests");
        jobs.href = "/jobs";
        note.appendChild(jobs);
        card.appendChild(note);
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
    }
    for (const f of listOf(s.files)) actions.appendChild(link(f, f.primary ? "btn primary" : "btn", false));
    if (actions.childNodes.length) card.appendChild(actions);
    linkRow(card, "Guitar Pro to download", listOf(s.guitarPro), "btn small");
    if (listOf(s.museScore).length || listOf(s.links).length || listOf(s.buy).length) {
      const more = el("details", "more");
      more.appendChild(el("summary", null, "Find it elsewhere"));
      linkRow(more, "Scores on MuseScore", listOf(s.museScore), "btn small");
      linkRow(more, "Find the chords", listOf(s.links), "btn small");
      linkRow(more, "Buy the track for an auto sheet", listOf(s.buy), "btn small");
      card.appendChild(more);
    }
    return card;
  };
  const cards = new Map();
  const cardFor = (i) => {
    if (!cards.has(i)) cards.set(i, makeCard(songs[i]));
    return cards.get(i);
  };

  // artist: one artist's songs alone, by sortArtist, which a search for the name wouldn't give
  // ("Queen" also finds "Dancing Queen").
  const state = { q: "", show: "all", sort: "artist", artist: "", key: "" };
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
    try {
      history.replaceState(null, "", "#" + params.toString());
    } catch (err) {
      // Some browsers refuse this for local files; the page works the same, it just isn't remembered.
    }
  };

  const plural = (n, word) => n + " " + word + (n === 1 ? "" : "s");
  const summarize = () => {
    const by = { found: 0, wanted: 0, ignored: 0 };
    for (const s of songs) if (own.call(by, s.status)) by[s.status] += 1;
    const summary = byId("summary");
    const stat = (n, word) => {
      const item = el("li", "stat");
      item.appendChild(el("b", null, n));
      item.appendChild(document.createTextNode(" " + word));
      summary.appendChild(item);
    };
    stat(songs.length, songs.length === 1 ? "song" : "songs");
    stat(by.found, "found");
    stat(by.wanted, "wanted");
    if (by.ignored) stat(by.ignored, "ignored");
    const when = String(data.generated || "").replace("T", " ").slice(0, 16);
    if (when) byId("updated").textContent = "Updated by caracole " + when + " UTC. ";
  };
  const smooth = () => (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? "auto" : "smooth");

  const render = () => {
    const query = parseQuery(state.q);
    const inKey = keyId(state.key);
    const matching = ORDERS[state.sort].filter((i) =>
      (!state.artist || String(songs[i].sortArtist || "") === state.artist) &&
      (!inKey || songKeys[i] === inKey) &&
      query.keys.every((k) => songKeys[i] === k) &&
      query.either.every((e) => songKeys[i] === e.key || (e.word && hay[i].indexOf(e.word) >= 0)) &&
      query.words.every((w) => hay[i].indexOf(w) >= 0));
    const tally = { all: matching.length, found: 0, wanted: 0, review: 0 };
    for (const i of matching) {
      for (const k of ["found", "wanted", "review"]) if (SHOWS[k](songs[i])) tally[k] += 1;
    }
    const shown = matching.filter((i) => SHOWS[state.show](songs[i]));
    for (const chip of chips) {
      chip.setAttribute("aria-pressed", String(chip.dataset.show === state.show));
      chip.querySelector(".n").textContent = String(tally[chip.dataset.show]);
    }
    sort.value = state.sort;
    keySelect.value = state.key;
    clear.hidden = !state.q;
    artistChip.hidden = !state.artist;
    artistChip.textContent = state.artist ? artistName(state.artist) + " ×" : "";
    artistChip.setAttribute("aria-label", state.artist ? "Show every artist, not only " + artistName(state.artist) : "");

    // One grid, whatever the order, so the cards fill each row; the strip jumps to a letter's first card.
    list.textContent = "";
    jump.textContent = "";
    const grid = el("div", "grid");
    const letterOf = LETTERS[state.sort];
    const firsts = new Map();
    for (const i of shown) {
      const card = cardFor(i);
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
    jump.hidden = firsts.size < 2;

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
      if (!query.keys.length) {  // the offline index has no keys
        const hint = el("p", "empty-hint", "To look in the offline Ultimate Guitar index, run ");
        hint.appendChild(el("code", null, "caracole search " + shellQuote(state.q)));
        list.appendChild(hint);
      }
    } else if (!shown.length) {
      list.appendChild(el("p", "empty", state.show === "review" ? "Nothing needs review." : "No songs here."));
    }
    count.textContent = shown.length === songs.length ? plural(songs.length, "song")
      : shown.length + " of " + plural(songs.length, "song");
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
  input.value = state.q;
  input.addEventListener("input", () => {
    state.q = input.value;
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
  document.addEventListener("keydown", (e) => {
    const typing = document.activeElement === input;
    if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      input.focus();
      input.select();
    } else if (e.key === "Escape" && typing && input.value) {
      setQuery("");
    }
  });
  summarize();
  render();
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
  border-radius: 14px; background: var(--bg); }
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
.sb-names .why { display: block; font-size: .8rem; font-style: italic; }
.sb-tools { flex: none; display: flex; gap: 4px; }
.sb-tools form, .sb-more form { margin: 0; }
.sb-btn { display: inline-grid; place-items: center; width: 44px; height: 44px; padding: 0; border-radius: 10px;
  border: 1px solid var(--border); background: var(--surface); color: var(--text); font: inherit; font-size: 1rem;
  cursor: pointer; }
.sb-btn:hover { border-color: var(--border-strong); }
.sb-more > summary { min-height: 40px; color: var(--muted); font-size: .85rem; font-weight: 600; cursor: pointer; }
.sb-more form { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 8px; margin-top: 8px; }
.sb-more .f { flex: 1 1 180px; }
.sb-sure { display: flex; flex: 1 1 100%; align-items: center; gap: 10px; min-height: 44px; font-size: .9rem; }
.sb-sure input { flex: none; width: 22px; height: 22px; margin: 0; accent-color: var(--accent); }
.sb-error { margin: 0 16px 16px; color: var(--failed); font-weight: 600; overflow-wrap: anywhere; }
.pick { display: none; }
.selecting .card .mono { display: none; }
.selecting .pick { flex: none; position: relative; display: grid; place-items: center; width: 44px; height: 44px;
  border-radius: 12px; border: 2px solid var(--border-strong); background: var(--surface); cursor: pointer; }
.pick input { position: absolute; inset: 0; width: 100%; height: 100%; margin: 0; opacity: 0; cursor: pointer; }
.pick:focus-within { outline: 3px solid var(--focus); outline-offset: 2px; }
.pick-n { font-weight: 750; font-variant-numeric: tabular-nums; }
.card.picked { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent); }
.card.picked .pick { border-color: var(--accent); background: var(--accent); color: var(--on-accent); }
.pick-toggle[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.selecting .page { padding-bottom: 260px; }
.pickbar { position: fixed; z-index: 10; left: 0; right: 0; bottom: 0; border-top: 1px solid var(--border);
  background: var(--surface); box-shadow: 0 -6px 24px rgb(0 0 0 / 14%);
  padding: 10px max(16px, env(safe-area-inset-right)) calc(10px + env(safe-area-inset-bottom))
    max(16px, env(safe-area-inset-left)); }
.pickbar-in { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; max-width: 1320px; margin: 0 auto; }
.pick-count { margin: 0; font-weight: 700; font-variant-numeric: tabular-nums; }
.pick-form { display: flex; flex: 1 1 340px; flex-wrap: wrap; align-items: center; gap: 8px; min-width: 0; margin: 0; }
.pick-form label { display: flex; flex: 1 1 150px; min-width: 0; }
.pick-form input, .pick-form select { width: 100%; min-width: 0; height: 44px; padding: 0 10px; border-radius: 10px;
  border: 1px solid var(--border-strong); background: var(--bg); color: var(--text); font: inherit; font-size: 1rem; }
.pick-error { flex-basis: 100%; margin: 0; color: var(--failed); font-size: .85rem; }
.pick-error:empty { display: none; }
.pick-command { flex-basis: 100%; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.pick-command code { flex: 1 1 260px; padding: 8px 10px; user-select: all; }
"""

# The Select mode: a box on each card (any element of #list with a data-id: a row too), and a bar to
# name the songbook. It goes with the page's own script, after it: it finds the cards by their song's
# id and builds everything with createElement and textContent, as the page does. On caracole serve
# the bar posts the songbook (the server's token, the songs' ids in the order picked); on the file on
# disk it shows the caracole songbook command to run instead.
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
  const books = (Array.isArray(data.songbooks) ? data.songbooks : []).map((b) => String(b && b.name || ""))
    .filter(Boolean);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  // Each word in single quotes, each ' written '\'': bash and zsh expand ! even in double quotes.
  const shellQuote = (text) => "'" + String(text).replace(/'/g, "'\\''") + "'";
  const picked = [];  // song ids, in the order they were picked: the songbook's order

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
  const count = el("p", "pick-count");
  count.setAttribute("aria-live", "polite");
  const form = el("form", "pick-form");
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
  const command = el("div", "pick-command");
  command.hidden = true;
  const commandText = el("code");
  const copy = el("button", "btn small", "Copy");
  copy.type = "button";
  command.appendChild(el("span", "hint", "Run this where caracole runs:"));
  command.appendChild(commandText);
  command.appendChild(copy);
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
  inner.append(count, form, command);
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
    submit.disabled = !picked.length;
    const existing = into.value;
    submit.textContent = existing ? "Add to " + existing : "Make songbook";
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
  // A box on each card, as the page's script puts them in the list (it keeps each card it made).
  const decorate = () => {
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
  decorate();

  const setMode = (on) => {
    document.body.classList.toggle("selecting", on);
    toggle.setAttribute("aria-pressed", on ? "true" : "false");  // its name stays "Select": pressed or not
    bar.hidden = !on;
    paintAll();
  };
  toggle.addEventListener("click", () => setMode(!document.body.classList.contains("selecting")));
  clear.addEventListener("click", () => {
    picked.length = 0;
    paintAll();
  });
  into.addEventListener("change", paintAll);
  copy.addEventListener("click", () => {
    const text = commandText.textContent;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => { copy.textContent = "Copied"; }, () => {});
    }
    const range = document.createRange();
    range.selectNodeContents(commandText);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
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
      return;  // the server queues caracole songbook, and its requests page shows how it went
    }
    e.preventDefault();
    const words = ["caracole songbook", existing ? "add" : "make", shellQuote(name)];
    for (const id of picked) words.push(shellQuote(songs.get(id).display));
    commandText.textContent = words.join(" ");
    command.hidden = false;
    copy.textContent = "Copy";
  });
})();
"""

_PAGE_STYLE = _STYLE + _SONGBOOK_STYLE
_PAGE_SCRIPT = _SCRIPT + _SELECT_SCRIPT


def sha256_source(text: str) -> str:
    """A CSP source allowing exactly this inline script or stylesheet."""
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


# default-src 'none' blocks every fetch the page could make; links still navigate. Forms may post
# only to caracole serve, and only on the page it serves.
_CSP = (
    f"default-src 'none'; script-src {sha256_source(_PAGE_SCRIPT)}; style-src {sha256_source(_PAGE_STYLE)}; "
    "base-uri 'none'; form-action __FORMS__"
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
<header class="masthead">
  <div>
    <p class="app">caracole</p>
    <h1>Your library</h1>
    <ul class="summary" id="summary" aria-label="The library in numbers"></ul>
  </div>
  <nav class="links" aria-label="Pages">__NAV__</nav>
</header>
__REQUEST____SONGBOOKS__<div class="searchbar" role="search">
  <label class="visually-hidden" for="q">Search your songs</label>
  <div class="field">
    <input id="q" type="search" placeholder="Search artist, title, pinyin or key" autocomplete="off"
      autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="search">
    <button type="button" id="clear" class="clear" aria-label="Clear the search" hidden>×</button>
  </div>
</div>
<div class="toolbar">
  <div class="chips" role="group" aria-label="Show">
    <button type="button" class="chip" data-show="all" aria-pressed="true">All <span class="n"></span></button>
    <button type="button" class="chip" data-show="found" aria-pressed="false">Found <span class="n"></span></button>
    <button type="button" class="chip" data-show="wanted" aria-pressed="false">Wanted <span class="n"></span></button>
    <button type="button" class="chip" data-show="review" aria-pressed="false">Needs review <span class="n"></span></button>
    <button type="button" class="chip person" id="artist" hidden></button>
  </div>
  <div class="controls">
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

# The form caracole serve adds: a song for wanted.txt, written as `caracole add` writes it.
_REQUEST = """<details class="request">
  <summary><span class="plus" aria-hidden="true">+</span>Request a song</summary>
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
    <p class="hint">It goes into wanted.txt, as <code>caracole add</code> writes it. Fetch it now asks
      Ultimate Guitar for this song alone, under the same pauses as every caracole command; its lyrics
      come with the nightly run.</p>
  </form>
</details>
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


# --- songbooks: the section (songbook.py) ---------------------------------------------------------


def songbooks_section(conn: sqlite3.Connection, cfg: Config, overrides: Overrides,
                      controls: WebControls | None) -> tuple[str, list[dict[str, Any]]]:
    """The Songbooks section, and the songbooks for the Select mode's bar ({"name", "songs"}).

    Each songbook lists its songs in order, the missing ones marked, and links its files. On
    caracole serve (``controls``) each song can move up or down or be taken out, and the songbook
    renamed or deleted, by forms that post to the server; the file on disk says which command does it.
    No songbook, no section; a songbooks.toml that can't be read is said there, and costs the rest of
    the page nothing.
    """
    from caracole.songbook import SongbookError, load_songbooks, songbooks_file

    try:
        books = load_songbooks(songbooks_file(cfg.library_dir))
    except SongbookError as e:
        body = (f'<p class="sb-error">songbooks.toml can\'t be read: {html_text.escape(str(e))}. Fix it, and '
                "the songbooks are back; until then each keeps its files.</p>\n")
        return _songbooks_wrap("!", body), []
    if not books:
        return "", []
    cards = "".join(_songbook_card(conn, cfg, overrides, book, controls) for book in books)
    body = f'<div class="sb-list">\n{cards}</div>\n'
    return _songbooks_wrap(str(len(books)), body), [{"name": b.name, "songs": len(b.songs)} for b in books]


def _songbooks_wrap(count: str, body: str) -> str:
    return (
        '<section class="songbooks" id="songbooks" aria-labelledby="songbooks-title">\n<details>\n'
        '<summary><span class="sb-icon" aria-hidden="true">♪</span><span id="songbooks-title">Songbooks</span>'
        f' <span class="n">{count}</span></summary>\n{body}</details>\n</section>\n'
    )


_SONGBOOK_FILES = (("songbook.html", "Songbook for the phone"), ("songbook.pdf", "PDF"), ("songbook.cho", "ChordPro"))


def _songbook_card(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, book: Any,
                   controls: WebControls | None) -> str:
    from caracole.songbook import FOLDER, songbook_entries

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
    files = (f'<div class="actions">{"".join(links)}</div>\n' if links
             else '<p class="hint">Not made yet: caracole render, or caracole songbook render, makes its files.</p>\n')
    rows = []
    for n, entry in enumerate(entries, start=1):
        title, artist = esc(entry.title), esc(entry.artist)
        why = f'<span class="why">missing: {esc(entry.missing)}</span>' if entry.missing else ""
        tools = _songbook_tools(book.name, entry.text, entry.title, n, len(entries), controls) if controls else ""
        rows.append(f'<li{" class=\"missing\"" if entry.missing else ""}><span class="sb-n">{n}</span>'
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
        f'<article class="sb-card">\n<div><h2>{esc(book.name)}</h2><p class="hint">{songs}</p></div>\n'
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
