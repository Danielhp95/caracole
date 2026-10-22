"""The Guitar Pro page caracole serve writes for a song's Guitar Pro file (guitar_routes.py): the file drawn and
played in the browser by alphaTab (alphatab.py).

At its top, the song's title and artist, the file it shows, and links: back to the song in the library
(``/#song=<id>``), its sheet viewer when it has one, and the file itself as a download. Under them a bar that
stays at the top while the score scrolls: on one row Play (Pause while it plays) and Stop, the tempo (50 to 125 %,
alphaTab's ``playbackSpeed``) and Tab only or Score and tab ("Tab" and "Score" on a phone; tab only from the start on
a screen under 600 px wide, where the tab is drawn at 0.8 of its size: three or four bars a line on a phone); under
it the score's tracks, laid out (guitar.js: the one it opens on, and how to show several; none for a score of one
track), each a button that shows it, pressed while it is shown, with a speaker on it that mutes it; they wrap on a wide screen and scroll sideways in their own row on a
phone. Then the score, in the page's light or dark colours. Every target is 44 px each way at the least.

The page holds the file's bytes (base64, in a ``<script type="application/octet-stream">`` block, which nothing
runs), its stylesheet (base.css, then guitar.css) and its script (guitar.js), and loads one thing: alphaTab's
bundle, from caracole serve (``alphatab.ASSETS``), checked by its hash. Its policy (``policy``) is that and nothing
else: the bundle and the page's script by their hashes, its stylesheet, the empty one that keeps alphaTab from
adding its shared rules (``SHARED_STUB``) and the one alphaTab adds for its font, by theirs; fonts from ``data:``
URIs alone (the music font is one), a worker from a ``blob:`` alone (alphaTab's synthesizer, guitar.js), an image
from a ``data:`` URI alone (the page's icon, page_icon.py); no connection, no form, no base. It is served in a sandbox (``sandbox allow-scripts``): an origin of its own, with
no cookie and no way to ask caracole serve for anything but the bundle, which caracole serve answers to any origin.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import quote

from caracole.inline import sha256_source
from caracole.library_assets import BASE_STYLE
from caracole.page_icon import LINK as PAGE_ICON
from caracole.web.alphatab import AlphaTab

HERE = Path(__file__).resolve().parent
# The stylesheet named alphaTabStyle, whose being there keeps alphaTab from adding its own shared rules (they are in
# guitar.css).
SHARED_STUB = "/* alphaTab's shared rules are in the page's stylesheet */"


@lru_cache(maxsize=1)
def style() -> str:
    return BASE_STYLE + (HERE / "guitar.css").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def script() -> str:
    return (HERE / "guitar.js").read_text(encoding="utf-8")


def policy(at: AlphaTab) -> str:
    """The page's Content-Security-Policy, without the sandbox and ``frame-ancestors``, which the route adds."""
    return (
        f"default-src 'none'; script-src {at.script_source} {sha256_source(script())}; "
        f"style-src {sha256_source(style())} {sha256_source(SHARED_STUB)} {at.font_face}; "
        "img-src data:; font-src data:; worker-src blob:; base-uri 'none'; form-action 'none'"
    )


def build_page(*, title: str, artist: str, song_id: int, path: str, label: str, data: bytes, at: AlphaTab,
               sheet: str | None = None) -> str:
    """The page for the Guitar Pro file at ``path`` (its library path, ``label`` naming it: "Guitar Pro 1"), of the
    song ``song_id`` (``title`` by ``artist``), its bytes ``data``; ``sheet``, the library path of the song's sheet
    viewer, when it has one."""
    href = "/" + quote(path)
    links = [f'<a class="navlink" href="/#song={song_id}">‹ The song</a>']
    if sheet:
        links.append(f'<a class="navlink" href="/{escape(quote(sheet))}">Sheet</a>')
    links.append(f'<a class="navlink" href="{escape(href)}" download>Download</a>')
    name = path.rsplit("/", 1)[-1]
    return "".join((
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n<meta name="referrer" content="same-origin">\n',
        PAGE_ICON,
        f"<title>{escape(title)} · {escape(label)} · caracole</title>\n",
        f"<style>{style()}</style>\n",
        f'<style id="alphaTabStyle">{SHARED_STUB}</style>\n',
        '</head>\n<body>\n<div class="page gp">\n<header class="masthead">\n<div>\n',
        '<p class="app"><a href="/">caracole</a></p>\n',
        f"<h1>{escape(title)}</h1>\n",
        f'<p class="by">{escape(artist)}</p>\n' if artist else "",
        f'<p class="file">{escape(label)} · {escape(name)}</p>\n</div>\n',
        f'<nav class="links" aria-label="This song">{"".join(links)}</nav>\n</header>\n',
        _BAR,
        '<p class="gp-status" id="gp-status" role="status">Loading alphaTab…</p>\n',
        '<div class="score" id="score"></div>\n',
        '<noscript><p class="gp-status">Turn on JavaScript to see and hear the tab, or download the file.</p></noscript>\n',
        "</div>\n",
        f'<script type="application/octet-stream" id="gp">{base64.b64encode(data).decode("ascii")}</script>\n',
        f'<script src="{escape(at.href)}" integrity="{escape(at.integrity)}" crossorigin="anonymous"></script>\n',
        f"<script>{script()}</script>\n</body>\n</html>\n",
    ))


_BAR = """<div class="gp-bar" id="gp-bar">
<div class="gp-play" role="toolbar" aria-label="Playback">
<button type="button" class="btn primary" id="play" aria-pressed="false" disabled>Play</button>
<button type="button" class="btn" id="stop" disabled>Stop</button>
<label class="tempo" for="tempo"><span class="word">Tempo</span> <input type="range" id="tempo" min="50" max="125" step="5" value="100">
<output id="tempo-now" for="tempo">100%</output></label>
<fieldset class="view" id="view"><legend class="visually-hidden">Show</legend>
<label><input type="radio" name="view" value="tab"><span>Tab<span class="long"> only</span></span></label>
<label><input type="radio" name="view" value="score"><span><span class="long">Score and tab</span><span class="short">Score</span></span></label></fieldset>
</div>
<div class="gp-tracks" id="tracks" role="group" aria-label="Tracks" hidden></div>
</div>
"""
