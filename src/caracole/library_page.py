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
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from caracole.config import Config
from caracole.library import song_dir, write_atomic
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


def build_library_page(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, now: datetime) -> str:
    """The whole page: every song, its files, and the links to find what's missing."""
    keys = _sheet_keys(conn)
    pages = _guitar_pro_pages(conn)
    library = list_songs(conn)
    to_buy = {s.id for s in songs_to_buy(conn, library, overrides, now)[0]}  # the to-do page's buy list
    songs = [_song(cfg.library_dir, s, overrides, keys.get(s.id), pages.get(s.id, []), s.id in to_buy)
             for s in library]
    data = {
        "generated": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fold": {c: fold(c) for c in _TRANSLITERATED},
        "songs": songs,
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return (
        _HEAD.replace("__CSP__", _CSP).replace("__STYLE__", _STYLE)
        + _BODY
        + f'<script type="application/json" id="songs">{payload}</script>\n'
        + f"<script>{_SCRIPT}</script>\n</body>\n</html>\n"
    )


def write_library_page(library_dir: Path, html: str) -> Path:
    """Write ``index.html`` in the library folder, atomically, and return its path."""
    path = library_dir / PAGE_NAME
    write_atomic(path, html.encode("utf-8"))
    return path


# --- the data ---------------------------------------------------------------------------


def _song(library_dir: Path, song: Song, overrides: Overrides, key: str | None,
          guitar_pro: list[dict[str, str]], for_buying: bool) -> dict[str, Any]:
    """One song's card; ``for_buying`` when the to-do page's buy list holds it (``todo.songs_to_buy``)."""
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
        "key": key,
        "transpose": overrides.transpose.get(song.key, 0),
        "lyrics": song.lyrics_status,
        "auto": not any(n in names for n in _HUMAN_SHEETS) and any(n in names for n in _AUTO_SHEETS),
        "files": _files(library_dir, song, names),
        "guitarPro": guitar_pro,
        "links": links,
        "buy": buy,
        "sortArtist": _sort_key(song.artist),
        "sortTitle": _sort_key(title),
        "search": _haystack([song.artist, *song.artists, title, song.display]),
    }


def _file_names(folder: Path) -> set[str]:
    try:
        return {p.name for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")}
    except OSError:  # no folder yet
        return set()


def _files(library_dir: Path, song: Song, names: set[str]) -> list[dict[str, Any]]:
    """Links to the kept files that exist, as paths relative to index.html, percent-encoded."""
    guitar = sorted((int(m.group(1)), n) for n in names if (m := _GUITAR.fullmatch(n)))
    ordered = [n for n in _FIRST if n in names] + [n for _, n in guitar] + [n for n in _LAST if n in names]
    folder = song_dir(library_dir, song).relative_to(library_dir)
    base = "/".join(quote(part, safe="") for part in folder.parts)
    primary = next((n for n in ordered if n.endswith((".html", ".pdf"))), None) or next(
        (n for n in ordered if n in ("sheet.txt", "sheet (auto).txt")), None)
    return [
        {"name": n, "label": _label(n), "href": f"{base}/{quote(n, safe='')}", "primary": n == primary}
        for n in ordered
    ]


def _label(name: str) -> str:
    m = _GUITAR.fullmatch(name)
    if m:
        return f"{'Power Tab' if m.group(2).lower() == '.ptb' else 'Guitar Pro'} {m.group(1)}"
    return _LABELS[name]


def _sheet_keys(conn: sqlite3.Connection) -> dict[int, str]:
    """The key UG gives each kept sheet's version (``tonality_name``), by song."""
    keys: dict[int, str] = {}
    rows = conn.execute(
        "SELECT f.song_id, v.raw FROM files f JOIN versions v ON v.id = f.version_id WHERE f.name = 'sheet.txt'"
    )
    for song_id, raw in rows:
        try:
            value = json.loads(raw or "{}").get("tonality_name")
        except (ValueError, AttributeError):
            continue
        if isinstance(value, str) and value.strip():
            keys[song_id] = value.strip()
    return keys


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

_STYLE = """
:root {
  color-scheme: light dark;
  --bg: #f7f6f3;
  --surface: #ffffff;
  --raised: #f0eee9;
  --text: #1f1e1c;
  --muted: #645f57;
  --border: #e1ddd5;
  --accent: #b4441e;
  --on-accent: #ffffff;
  --focus: #1f6feb;
  --found: #1d6b43; --found-bg: #def1e5;
  --wanted: #7a4c00; --wanted-bg: #fbeed2;
  --ignored: #5c5c5c; --ignored-bg: #ebebeb;
  --review: #5b34a8; --review-bg: #ece4fa;
  --auto: #0e5c6e; --auto-bg: #dbf0f5;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #131312;
    --surface: #1d1c1b;
    --raised: #292826;
    --text: #edebe7;
    --muted: #aaa59c;
    --border: #363431;
    --accent: #f0895c;
    --on-accent: #1b0e07;
    --focus: #6ea8fe;
    --found: #83d6a6; --found-bg: #133222;
    --wanted: #f2c46e; --wanted-bg: #36290d;
    --ignored: #b8b8b8; --ignored-bg: #2d2d2d;
    --review: #c6adff; --review-bg: #2b2047;
    --auto: #8fd6e8; --auto-bg: #102f37;
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
.page { max-width: 1120px; margin: 0 auto; padding: 0 16px 48px; }
.masthead { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; padding: 20px 0 4px; }
.masthead h1 { margin: 0; font-size: 1.6rem; line-height: 1.2; letter-spacing: -0.01em; }
.masthead .app { display: block; color: var(--muted); font-size: .8rem; font-weight: 600; letter-spacing: .08em;
  text-transform: uppercase; }
.summary { margin: 4px 0 0; color: var(--muted); font-size: .9rem; }
.nowrap { white-space: nowrap; }
.todo { flex: none; display: inline-flex; align-items: center; min-height: 44px; padding: 0 16px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface); text-decoration: none; font-weight: 600; }
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
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 12px;
  margin: 10px 0 4px; }
.chip { display: inline-flex; align-items: center; gap: 6px; min-height: 40px; padding: 0 14px; border-radius: 999px;
  border: 1px solid var(--border); background: var(--surface); color: var(--text); font: inherit; font-size: .9rem;
  cursor: pointer; }
.chip .n { color: var(--muted); font-variant-numeric: tabular-nums; }
.chip[aria-pressed="true"] { background: var(--text); border-color: var(--text); color: var(--bg); }
.chip[aria-pressed="true"] .n { color: inherit; opacity: .75; }
.sort { display: inline-flex; align-items: center; gap: 8px; margin-left: auto; color: var(--muted); font-size: .9rem; }
.sort select { min-height: 40px; padding: 0 10px; border-radius: 10px; border: 1px solid var(--border);
  background: var(--surface); color: var(--text); font: inherit; font-size: .9rem; }
.count { margin: 0; color: var(--muted); font-size: .85rem; }
.group { margin-top: 20px; }
.group h2 { display: flex; align-items: baseline; gap: 8px; margin: 0 0 10px; font-size: 1.05rem; overflow-wrap: anywhere; }
.group h2 .n { color: var(--muted); font-size: .85rem; font-weight: 500; }
.grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr)); }
.list:not(.grouped) .grid { margin-top: 12px; }
.card { display: flex; flex-direction: column; gap: 10px; min-width: 0; padding: 14px 16px 16px;
  border: 1px solid var(--border); border-radius: 16px; background: var(--surface);
  content-visibility: auto; contain-intrinsic-size: auto 190px; }
.card[data-status="ignored"] { opacity: .7; }
.card .head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.card .names { min-width: 0; }
.card h3 { margin: 0; font-size: 1.08rem; line-height: 1.3; overflow-wrap: anywhere; }
.card .artist { margin: 2px 0 0; color: var(--muted); font-size: .9rem; overflow-wrap: anywhere; }
.grouped .card .artist { display: none; }
.badges { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; flex: none; max-width: 50%; }
.badge { padding: 2px 9px; border-radius: 999px; font-size: .75rem; font-weight: 650; white-space: nowrap; }
.badge.found { color: var(--found); background: var(--found-bg); }
.badge.wanted { color: var(--wanted); background: var(--wanted-bg); }
.badge.ignored { color: var(--ignored); background: var(--ignored-bg); }
.badge.review { color: var(--review); background: var(--review-bg); }
.badge.auto { color: var(--auto); background: var(--auto-bg); }
.facts { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 0; color: var(--muted); font-size: .85rem; }
.facts .key, .facts .transpose { color: var(--text); font-weight: 600; }
.note { margin: 0; color: var(--review); font-size: .85rem; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; }
.subhead { margin: 2px 0 -2px; color: var(--muted); font-size: .75rem; font-weight: 650; letter-spacing: .06em;
  text-transform: uppercase; }
.btn { display: inline-flex; align-items: center; min-height: 44px; padding: 0 14px; border-radius: 12px;
  border: 1px solid var(--border); background: var(--raised); color: var(--text); font-size: .92rem;
  font-weight: 550; text-decoration: none; overflow-wrap: anywhere; }
.btn.primary { background: var(--accent); border-color: var(--accent); color: var(--on-accent); }
.btn.small { min-height: 40px; padding: 0 12px; font-size: .88rem; }
.empty { margin: 32px 0 8px; font-size: 1.05rem; }
.empty-hint { margin: 0; color: var(--muted); }
.empty-hint code, .footer code { font: .9em ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  padding: 1px 5px; border-radius: 6px; background: var(--raised); overflow-wrap: anywhere; }
.footer { margin-top: 40px; color: var(--muted); font-size: .8rem; }
.visually-hidden { position: absolute; width: 1px; height: 1px; margin: -1px; overflow: hidden; clip: rect(0 0 0 0);
  white-space: nowrap; border: 0; }
@media (min-width: 720px) {
  .masthead h1 { font-size: 2rem; }
  .masthead { padding-top: 28px; }
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
  const chips = Array.from(document.querySelectorAll(".chip"));

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
  const terms = (query) => fold(query).split(/\s+/)
    .map((w) => w.replace(APOSTROPHES, "").replace(EDGES, "")).filter(Boolean);
  const shellQuote = (text) => '"' + text.replace(/(["\\$`])/g, "\\$1") + '"';
  const hay = songs.map((s) => String(s.search || ""));
  const listOf = (value) => (Array.isArray(value) ? value : []);

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
  const SORTS = ["artist", "recent"];

  const compare = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
  const order = songs.map((_, i) => i);
  const byArtist = order.slice().sort((i, j) =>
    compare(String(songs[i].sortArtist), String(songs[j].sortArtist)) ||
    compare(String(songs[i].sortTitle), String(songs[j].sortTitle)) || i - j);
  const byRecent = order.slice().sort((i, j) =>
    compare(String(songs[j].added || ""), String(songs[i].added || "")) || (songs[j].id || 0) - (songs[i].id || 0));

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
  const linkRow = (card, heading, items, cls) => {
    if (!items.length) return;
    card.appendChild(el("p", "subhead", heading));
    const row = el("div", "actions");
    for (const item of items) row.appendChild(link(item, cls, true));
    card.appendChild(row);
  };

  const makeCard = (s) => {
    const card = el("article", "card");
    card.dataset.status = String(s.status);
    const head = el("div", "head");
    const names = el("div", "names");
    names.appendChild(el("h3", null, s.title));
    const artists = listOf(s.artists);
    names.appendChild(el("p", "artist", artists.length > 1 ? artists.join(", ") : s.artist));
    head.appendChild(names);
    const badges = el("div", "badges");
    badges.appendChild(el("span", "badge " + String(s.status), label(STATUS_TEXT, s.status) || s.status));
    if (SHOWS.review(s)) badges.appendChild(el("span", "badge review", "Needs review"));
    if (s.auto) badges.appendChild(el("span", "badge auto", "Auto sheet"));
    head.appendChild(badges);
    card.appendChild(head);

    const facts = el("p", "facts");
    if (s.key) facts.appendChild(el("span", "key", "Key " + s.key));
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

    const files = listOf(s.files);
    if (files.length) {
      const row = el("div", "actions");
      for (const f of files) row.appendChild(link(f, f.primary ? "btn primary" : "btn", false));
      card.appendChild(row);
    }
    linkRow(card, "Guitar Pro to download", listOf(s.guitarPro), "btn small");
    linkRow(card, "Find the chords", listOf(s.links), "btn small");
    linkRow(card, "Buy the track for an auto sheet", listOf(s.buy), "btn small");
    return card;
  };
  const cards = new Map();
  const cardFor = (i) => {
    if (!cards.has(i)) cards.set(i, makeCard(songs[i]));
    return cards.get(i);
  };

  const state = { q: "", show: "all", sort: "artist" };
  try {
    const params = new URLSearchParams(location.hash.slice(1));
    state.q = params.get("q") || "";
    if (own.call(SHOWS, params.get("show"))) state.show = params.get("show");
    if (SORTS.indexOf(params.get("sort")) >= 0) state.sort = params.get("sort");
  } catch (err) {
    // A malformed address: start from the defaults.
  }
  const save = () => {
    const params = new URLSearchParams();
    if (state.q) params.set("q", state.q);
    if (state.show !== "all") params.set("show", state.show);
    if (state.sort !== "artist") params.set("sort", state.sort);
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
    const parts = [plural(songs.length, "song"), by.found + " found", by.wanted + " wanted", by.ignored + " ignored"];
    parts.forEach((part, k) => {
      if (k) summary.appendChild(document.createTextNode(" · "));
      summary.appendChild(el("span", "nowrap", part));
    });
    const when = String(data.generated || "").replace("T", " ").slice(0, 16);
    if (when) byId("updated").textContent = "Updated by caracole " + when + " UTC. ";
  };

  const render = () => {
    const words = terms(state.q);
    const matching = (state.sort === "recent" ? byRecent : byArtist)
      .filter((i) => words.every((w) => hay[i].indexOf(w) >= 0));
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
    clear.hidden = !state.q;

    list.textContent = "";
    list.className = state.sort === "artist" ? "list grouped" : "list";
    const frag = document.createDocumentFragment();
    if (state.sort === "artist") {
      let key = null;
      let grid = null;
      let tag = null;
      let n = 0;
      for (const i of shown) {
        const s = songs[i];
        if (String(s.sortArtist) !== key || grid === null) {
          if (tag) tag.textContent = String(n);
          key = String(s.sortArtist);
          n = 0;
          const group = el("section", "group");
          const h = el("h2", null, s.artist);
          tag = el("span", "n");
          h.appendChild(tag);
          grid = el("div", "grid");
          group.appendChild(h);
          group.appendChild(grid);
          frag.appendChild(group);
        }
        grid.appendChild(cardFor(i));
        n += 1;
      }
      if (tag) tag.textContent = String(n);
    } else {
      const grid = el("div", "grid");
      for (const i of shown) grid.appendChild(cardFor(i));
      frag.appendChild(grid);
    }
    list.appendChild(frag);

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
    } else if (!shown.length && state.q) {
      list.appendChild(el("p", "empty", "No songs match “" + state.q + "”."));
      const hint = el("p", "empty-hint", "To look in the offline Ultimate Guitar index, run ");
      hint.appendChild(el("code", null, "caracole search " + shellQuote(state.q)));
      list.appendChild(hint);
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
  input.value = state.q;
  input.addEventListener("input", () => {
    state.q = input.value;
    update();
  });
  clear.addEventListener("click", () => {
    input.value = "";
    state.q = "";
    render();
    save();
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
  document.addEventListener("keydown", (e) => {
    const typing = document.activeElement === input;
    if (e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      input.focus();
      input.select();
    } else if (e.key === "Escape" && typing && input.value) {
      input.value = "";
      state.q = "";
      render();
      save();
    }
  });
  summarize();
  render();
})();
"""


def _sha256(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


# default-src 'none' blocks every fetch the page could make; links still navigate.
_CSP = (
    f"default-src 'none'; script-src {_sha256(_SCRIPT)}; style-src {_sha256(_STYLE)}; "
    "base-uri 'none'; form-action 'none'"
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
    <h1><span class="app">caracole</span>Your library</h1>
    <p class="summary" id="summary"></p>
  </div>
  <a class="todo" href="_todo.md">To-do</a>
</header>
<div class="searchbar" role="search">
  <label class="visually-hidden" for="q">Search your songs</label>
  <div class="field">
    <input id="q" type="search" placeholder="Search artist, title or pinyin" autocomplete="off"
      autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="search">
    <button type="button" id="clear" class="clear" aria-label="Clear the search" hidden>×</button>
  </div>
</div>
<div class="chips" role="group" aria-label="Show">
  <button type="button" class="chip" data-show="all" aria-pressed="true">All <span class="n"></span></button>
  <button type="button" class="chip" data-show="found" aria-pressed="false">Found <span class="n"></span></button>
  <button type="button" class="chip" data-show="wanted" aria-pressed="false">Wanted <span class="n"></span></button>
  <button type="button" class="chip" data-show="review" aria-pressed="false">Needs review <span class="n"></span></button>
</div>
<div class="toolbar">
  <p class="count" id="count" aria-live="polite"></p>
  <label class="sort">Sort
    <select id="sort">
      <option value="artist">Artist A–Z</option>
      <option value="recent">Recently added</option>
    </select>
  </label>
</div>
<main class="list grouped" id="list"></main>
<noscript><p class="empty">This page needs JavaScript to list your songs. Each song's files are in its
  folder, next to this page.</p></noscript>
<footer class="footer"><span id="updated"></span>Keep this library private: the sheets and lyrics are other
  people's work.</footer>
</div>
"""
