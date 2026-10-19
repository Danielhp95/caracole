"""sheet.html: one sheet as a page for a phone, written beside its PDF.

The page is one self-contained file. It opens from the synced library folder with
no server: it loads nothing (a Content-Security-Policy with the hashes of its one
script and one stylesheet makes the browser enforce that) and links only to the PDF
beside it and to the library's index.html two folders up. A server may serve it
too, only while it is the page caracole wrote, with ``viewer_csp()`` as its header.

The sheet itself is static HTML, so it reads without the script, and prints. Every
text from the sheet is escaped. The script (viewer.js) relabels the chords from the
song data in a ``<script type="application/json">`` block, whose every ``<`` is
written ``\\u003c``:

- ``chords``: each chord of the sheet (by its ``data-c`` index) as
  ``[root, suffix, bass, fingerings, nearest, slash fingerings]`` (pitch classes,
  the suffix as written, ``voicings.voicing_keys``), or null when caracole can't
  read it: it then stays as written;
- ``key``: ``{"tonic", "mode", "from"}`` (where the key came from, in words), or
  null for a sheet without chords; ``transpose``: where the viewer starts (the
  song's ``[transpose]``, as the PDF); ``capoSheet``: the sheet's own capo;
- for each mode of the key's tonic: ``mapped`` chords (``theory.map_chord``),
  their ``alts`` (``theory.alternatives``), ``names`` (each pitch class's name in
  that mode on each tonic, ``theory.spelling``), ``keyNames``, and ``capo`` hints
  for each transposition (``theory.capo_hints``);
- ``voicings``: the fingerings of every chord the page can show, on every root.
"""

from __future__ import annotations

import base64
import hashlib
import json
import unicodedata
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

from caracole.normalize import has_han
from caracole.viewer.sheet import Blank, ChordRow, Lyrics, Section, Sheet, Tab, Text, parse_sheet
from caracole.viewer.theory import (
    DISPLAY,
    MODES,
    Chord,
    Key,
    alternatives,
    capo_hints,
    estimate_key,
    key_name,
    map_chord,
    parse_chord,
    parse_key,
    spelling,
)
from caracole.viewer.voicings import page_voicings, voicing_keys

HERE = Path(__file__).parent
LIBRARY_PAGE = "../../index.html"  # Library/<artist>/<title>/sheet.html -> Library/index.html
CREDIT_URL = "https://github.com/tombatossals/chords-db"

# What info.json's "key_source" says, in words for the page.
_SOURCES = {
    "tab": "from the tab", "ug": "from the tab", "sheet": "from the tab", "lacuerda": "from the tab",
    "model": "from the audio", "autochords": "from the audio", "audio": "from the audio",
    "estimate": "guessed from the chords", "estimated": "guessed from the chords",
    "chords": "guessed from the chords",
}


@lru_cache(maxsize=1)
def _assets() -> tuple[str, str]:
    return (HERE / "viewer.css").read_text(encoding="utf-8"), (HERE / "viewer.js").read_text(encoding="utf-8")


def key_heard(source: str | None) -> bool:
    """Whether info.json's "key_source" says the key was heard in the audio (an auto sheet's).

    Such a key is the auto sheet's alone, and any other key a human sheet's: the model's chords
    may be in another key than the tab's (another transposition, or the capo).
    """
    return isinstance(source, str) and _SOURCES.get(" ".join(source.split()).lower()) == "from the audio"


def info_key(info: Any) -> tuple[str | None, str | None]:
    """The musical key in a song's info.json, and where it came from: ("Am", "tab").

    (None, None) when there is none. info.json's "key" names the song itself in
    caracole's older files ("radiohead|creep"), so only a key ``theory.parse_key``
    reads counts.
    """
    if not isinstance(info, dict) or parse_key(info.get("key")) is None:
        return None, None
    source = info.get("key_source")
    return info["key"], source if isinstance(source, str) and source.strip() else None


def build_viewer(
    cho: str,
    *,
    key: str | None = None,
    key_source: str | None = None,
    transpose: int = 0,
    pdf: str | None = None,
) -> str:
    """The page for a ChordPro sheet (as caracole writes it).

    The key comes from ``key`` (info.json's, with ``key_source``), else from the
    sheet's own ``{key}``, else it is guessed from the chords. ``transpose`` is where
    the viewer starts; ``pdf`` names the PDF beside the page, linked when given.
    """
    sheet = parse_sheet(cho)
    chords = [parse_chord(name, strict=False) for name in sheet.chords]
    song_key, origin = _song_key(sheet, chords, key, key_source)
    data = _data(sheet, chords, song_key, origin, transpose)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    style, script = _assets()
    csp = _policy()
    title = sheet.title or "Untitled"
    head_title = f"{title} · {sheet.artist}" if sheet.artist else title
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="color-scheme" content="light dark">\n<meta name="referrer" content="no-referrer">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{csp}">\n'
        f"<title>{escape(head_title)}</title>\n<style>{style}</style>\n</head>\n<body>\n"
        + _body(sheet, title, song_key, origin, pdf)
        + f'<script type="application/json" id="song">{payload}</script>\n'
        + f"<script>{script}</script>\n</body>\n</html>\n"
    )


def viewer_csp() -> str:
    """The Content-Security-Policy header a server sends with a viewer caracole wrote.

    It is the page's own policy (its one script and one stylesheet, by their hashes, and
    nothing else to load, no form to send, no base to change) with a sandbox, which a
    ``<meta>`` policy can't set: the page then runs in an origin of its own, with no cookie
    and no way to ask the server for anything. Its script still runs; it can't remember
    settings there, and does without. Serve only a viewer still as caracole wrote it
    (``render.written_file``, ``library.holds``): anyone with a synced device can put a page
    of their own in the library.
    """
    return "sandbox allow-scripts; " + _policy()


def _policy() -> str:
    style, script = _assets()
    return (
        f"default-src 'none'; script-src {_sha256(script)}; style-src {_sha256(style)}; "
        "base-uri 'none'; form-action 'none'"
    )


def _sha256(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


# --- the key and the data ------------------------------------------------------------------------


def _song_key(sheet: Sheet, chords: list[Chord | None], key: str | None,
              source: str | None) -> tuple[Key | None, str | None]:
    if (found := parse_key(key)) is not None:
        return found, _origin(source)
    if (found := parse_key(sheet.key)) is not None:
        return found, "from the sheet"
    played = [chords[i] for i in _played(sheet) if chords[i] is not None]
    found = estimate_key(played)
    return found, "guessed from the chords" if found else None


def _origin(source: str | None) -> str:
    if source is None:
        return "from info.json"
    words = " ".join(str(source).split())[:40]
    return _SOURCES.get(words.lower(), f"from {words}")


def _played(sheet: Sheet) -> list[int]:
    """The sheet's chords in the order they are played, repeats and all."""
    order: list[int] = []
    for section in sheet.sections:
        for line in section.lines:
            if isinstance(line, Lyrics):
                order += [c for c, _ in line.parts if isinstance(c, int)]
            elif isinstance(line, ChordRow):
                order += [c for c in line.items if isinstance(c, int)]
    return order


def _data(sheet: Sheet, chords: list[Chord | None], key: Key | None, origin: str | None,
          transpose: int) -> dict[str, Any]:
    needed: set[str] = set()

    def rep(chord: Chord | None) -> list[Any] | None:
        if chord is None:
            return None
        fingering, nearest, slash = voicing_keys(chord)
        needed.add(fingering)
        if slash:
            needed.add(slash)
        return [chord.root, chord.suffix, chord.bass, fingering, int(nearest), slash]

    data: dict[str, Any] = {
        "chords": [rep(c) for c in chords],
        "key": None if key is None else {"tonic": key.tonic, "mode": key.mode, "from": origin},
        "transpose": transpose,
        "capoSheet": sheet.capo,
        "modes": [],
        "mapped": {},
        "alts": {},
        "names": {"": " ".join(spelling(None))},
        "keyNames": {},
        "capo": {},
        "qualities": DISPLAY,
    }
    if key is not None:
        data["modes"] = list(MODES)
        data["names"] = {}
        for mode in MODES:
            in_mode = Key(key.tonic, mode)
            mapped = [None if c is None else map_chord(c, key, mode) for c in chords]
            data["mapped"][mode] = [rep(c) for c in mapped]
            data["alts"][mode] = [[] if c is None else [rep(a) for a in alternatives(c, in_mode)]
                                  for c in mapped]
            data["names"][mode] = [" ".join(spelling(Key(t, mode))) for t in range(12)]
            data["keyNames"][mode] = [key_name(Key(t, mode)) for t in range(12)]
            data["capo"][mode] = [
                [[fret, key_name(shapes)] for fret, shapes in capo_hints(Key((key.tonic + t) % 12, mode))]
                for t in range(12)
            ]
    data["voicings"] = page_voicings(needed)
    return data


# --- the page ------------------------------------------------------------------------------------


def _body(sheet: Sheet, title: str, key: Key | None, origin: str | None, pdf: str | None) -> str:
    facts = []
    if key is not None:
        facts.append(f"Key <b>{escape(key_name(key))}</b> <span class=\"from\">{escape(origin or '')}</span>")
    if sheet.capo:
        facts.append(f"Capo <b>{sheet.capo}</b>")
    notice = (
        '<p class="notice">Auto-generated, unverified: caracole heard these chords in the recording.</p>\n'
        if sheet.auto else ""
    )
    lang = ' lang="zh"' if has_han(sheet.title + "".join(_texts(sheet))) else ""
    pdf_link = f'<a class="pdf" href="{escape(quote(pdf))}">PDF</a>\n' if pdf else ""
    return (
        '<div class="page">\n<header class="head">\n'
        f'<a class="back" href="{LIBRARY_PAGE}">‹ Library</a>\n'
        f"<h1>{escape(title)}</h1>\n"
        + (f'<p class="artist">{escape(sheet.artist)}</p>\n' if sheet.artist else "")
        + f'<p class="facts" id="facts">{" · ".join(facts)}</p>\n</header>\n'
        + notice
        + '<div class="strip" id="strip" hidden></div>\n'
        + f'<article class="sheet" id="sheet"{lang}>\n{_sheet_html(sheet)}</article>\n'
        + '<footer class="foot">\n'
        + pdf_link
        + f'<p>Chord shapes from <a href="{CREDIT_URL}">chords-db</a> by David Rubert (MIT licence).</p>\n'
        + "<p>Keep this page private: the lyrics and chords are other people's work.</p>\n"
        + "</footer>\n</div>\n"
        + _CONTROLS
    )


def _texts(sheet: Sheet) -> list[str]:
    out = []
    for section in sheet.sections:
        for line in section.lines:
            if isinstance(line, Lyrics):
                out += [text for _, text in line.parts]
            elif isinstance(line, Text):
                out.append(line.text)
    return out


def _sheet_html(sheet: Sheet) -> str:
    return "".join(_section_html(s, sheet.chords) for s in sheet.sections)


def _section_html(section: Section, names: list[str]) -> str:
    cls = "sec chorus" if section.chorus else "sec"
    out = [f'<section class="{cls}">']
    if section.label:
        out.append(f'<h2 class="lbl">{escape(section.label)}</h2>')
    out += [_line_html(line, names) for line in section.lines]
    out.append("</section>\n")
    return "\n".join(out)


def _chord_html(index: int, names: list[str]) -> str:
    return f'<b class="c" data-c="{index}" tabindex="0" role="button">{escape(names[index])}</b>'


def _mark_html(mark: str) -> str:
    return f'<i class="m">{escape(mark)}</i>'


def _line_html(line, names: list[str]) -> str:
    if isinstance(line, Lyrics):
        out = []
        for head, text in line.parts:
            words = _words(text)
            if head is not None:
                top = _chord_html(head, names) if isinstance(head, int) else _mark_html(head)
                first = escape(words.pop(0)) if words else ""
                out.append(f'<span class="s">{top}<span class="y">{first}</span></span>')
            out += [f'<span class="w">{escape(w)}</span>' for w in words]
        return f'<p class="l">{"".join(out)}</p>'
    if isinstance(line, ChordRow):
        items = [_chord_html(i, names) if isinstance(i, int) else _mark_html(i) for i in line.items]
        return f'<p class="l chords">{" ".join(items)}</p>'
    if isinstance(line, Text):
        return f'<p class="l">{escape(line.text)}</p>'
    if isinstance(line, Tab):
        return f'<pre class="tab">{escape(chr(10).join(line.lines))}</pre>'
    assert isinstance(line, Blank)
    return '<div class="gap"></div>'


def _wide(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


def _words(text: str) -> list[str]:
    """``text`` cut where a line may wrap: after each word's trailing spaces, and around each
    wide (CJK) character, which wraps on its own."""
    words: list[str] = []
    word = ""
    for ch in text:
        if not ch.isspace() and word and (_wide(ch) or word[-1].isspace() or _wide(word[-1])):
            words.append(word)
            word = ""
        word += ch
    if word:
        words.append(word)
    return words


# The settings sheet and the chord card the script fills in; hidden until it runs.
_CONTROLS = """<button type="button" class="fab" id="fab" hidden aria-controls="panel" aria-expanded="false">Key</button>
<div class="scrim" id="scrim" hidden></div>
<section class="sheet-ui panel" id="panel" hidden role="dialog" aria-labelledby="panel-title">
<header class="ui-head"><h2 id="panel-title">Key <span id="key-now"></span></h2>
<button type="button" class="x" data-close aria-label="Close">×</button></header>
<div class="row"><span class="lab">Transpose</span>
<span class="stepper"><button type="button" id="down" aria-label="Down a semitone">−</button>
<output id="shift">0</output><button type="button" id="up" aria-label="Up a semitone">+</button></span>
<button type="button" class="link" id="reset-t">Reset</button><p class="hint" id="shift-hint"></p></div>
<div class="row" id="capo-row" hidden><span class="lab">Capo</span><span class="chips" id="capo"></span>
<p class="hint" id="capo-hint"></p></div>
<div class="row" id="mode-row" hidden><span class="lab">Mode</span><span class="chips" id="modes"></span>
<p class="hint" id="mode-hint"></p></div>
<div class="row"><span class="lab">Text</span>
<span class="stepper"><button type="button" id="smaller" aria-label="Smaller text">A−</button>
<button type="button" id="bigger" aria-label="Bigger text">A+</button></span></div>
<div class="row"><span class="lab">Chord shapes</span>
<button type="button" class="chip" id="strip-toggle" aria-pressed="false">Show all</button></div>
<div class="row"><span class="lab">Scroll</span>
<button type="button" class="chip" id="scroll" aria-pressed="false">Start</button>
<input type="range" id="speed" min="1" max="10" value="3" aria-label="Scroll speed"></div>
<div class="row"><button type="button" class="link" id="reset-all">Reset everything</button></div>
</section>
<section class="sheet-ui card" id="card" hidden role="dialog" aria-labelledby="card-name">
<header class="ui-head"><h2 id="card-name"></h2>
<button type="button" class="x" data-close aria-label="Close">×</button></header>
<div class="shape"><button type="button" class="round" id="prev" aria-label="Previous shape">‹</button>
<div class="diagram" id="diagram"></div>
<button type="button" class="round" id="next" aria-label="Next shape">›</button></div>
<p class="hint center" id="shape-note"></p>
<h3 class="sub" id="alts-title">Instead, in the key</h3>
<div class="chips" id="alts"></div>
<div class="actions"><button type="button" class="btn primary" id="use" hidden></button></div>
</section>
<noscript><p class="noscript">Turn on JavaScript to transpose, change the mode and see chord shapes.</p></noscript>
"""
