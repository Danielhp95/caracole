"""The README's screenshots, taken again: a demo library of public-domain songs, served, and photographed.

Run it from the repository's root, in the dev shell (chordpro, the PDF fonts, alphaTab and Python's packages), with
Chromium on PATH, and with poppler's ``pdftoppm`` (the PDF page) and ``oxipng`` (smaller files) from nixpkgs::

    nix shell nixpkgs#poppler-utils nixpkgs#oxipng -c nix develop -c python docs/screenshots/make.py

It writes the pictures here, in docs/screenshots/, over the ones there; ``--serve`` builds the library and serves it
until Ctrl-C instead, to look around in a browser of your own (``--port``, 8740 by default).

Nothing here goes on the network. The songs are traditional or long out of copyright, and their chord charts are
written below, by hand, in Ultimate Guitar's markup; the library is built in a temporary folder the way the nightly
run leaves one, with caracole's own functions (the test suite's helpers where a test builds the same thing):
wanted.txt synced, each chart kept as a fetched sheet is (``sheet.txt``, ``sheet.json``), Ultimate Guitar's index
read from a sitemap written here (as ``caracole index build --from`` reads one), a Guitar Pro file kept as a
download from gtptabs.com is (Greensleeves' melody and chords, written below in alphaTex and exported by alphaTab
itself), every sheet and the songbook rendered by the real chordpro, and the pages written. Then caracole serve's
own app answers on a free port of 127.0.0.1, its queue never started (no job runs, no command, no request), and the
LaCuerda search the pages send by themselves off (``WebApp(searches_lacuerda=False)``), its pages badged Demo
(``WebApp(badge="Demo")``, as ``caracole serve --label Demo`` badges them: library_name.py), and a headless Chromium,
which resolves no host name (tests/helpers/browser.py), takes each picture at twice its CSS size.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "tests")]

NOW = datetime(2026, 10, 22, 3, 0, tzinfo=UTC)
FETCHED = "2026-10-22T03:00:00Z"
SCALE = 2  # device pixels per CSS pixel

# --- the songs --------------------------------------------------------------------------------------------------
# The repository is public, so every song is in the public domain: traditional (Scarborough Fair in the ballad's old
# words, Greensleeves, Shenandoah, 茉莉花), or published long ago by authors long dead (John Newton's 1779 hymn, Robert
# Burns's 1788 words, Stephen Foster's 1854 song, Frederic Weatherly's 1913 words); the chord charts are written for
# this script. Each is written with its chords inline, as ChordPro writes them ("[Am]Are you [G]going"), and a
# section by "# Name"; ``ug_markup`` turns it into Ultimate Guitar's chord lines over lyric lines, the shape a fetched
# sheet has.

SCARBOROUGH = """\
# Verse 1
[Am]Are you [G]going to [Am]Scarborough Fair?
[C]Parsley, [Am]sage, rose[C]mary [D]and [Am]thyme,
Re[Am]member [C]me to one who [G]lives there,
For [Am]once she [G]was a true love of [Am]mine.
# Verse 2
[Am]Tell her to [G]make me a [Am]cambric shirt,
[C]Parsley, [Am]sage, rose[C]mary [D]and [Am]thyme,
[Am]Without any [C]seam or [G]needlework,
And [Am]then she shall [G]be a true lover of [Am]mine.
# Verse 3
[Am]Tell her to [G]find me an [Am]acre of land,
[C]Parsley, [Am]sage, rose[C]mary [D]and [Am]thyme,
[Am]Between the salt [C]water and the [G]sea sand,
And [Am]then she shall [G]be a true lover of [Am]mine.
"""

GREENSLEEVES = """\
# Verse 1
A[Am]las, my [C]love, you [G]do me [Em]wrong,
To [Am]cast me off dis[E]courteously,
For [Am]I have [C]loved you [G]well and [Em]long,
De[Am]lighting [E7]in your [Am]company.
# Chorus
[C]Greensleeves was [G]all my [Em]joy,
[Am]Greensleeves was my [E]delight,
[C]Greensleeves was my [G]heart of [Em]gold,
And [Am]who but my [E7]lady [Am]Greensleeves?
# Verse 2
I [Am]have been [C]ready [G]at your [Em]hand
To [Am]grant whatever you would [E]crave;
I [Am]have both [C]waged [G]life and [Em]land,
Your [Am]love and [E7]good will for to [Am]have.
"""

SHENANDOAH = """\
# Verse 1
Oh [D]Shenan[G]doah, I [D]long to [Bm]see you,
A[G]way, you [A]rolling [D]river.
Oh [D]Shenan[G]doah, I [D]long to [Bm]see you,
A[Bm]way, I'm [G]bound a[D]way, 'cross the [A]wide Mis[D]souri.
# Verse 2
Oh [D]Shenan[G]doah, I [D]love your [Bm]daughter,
A[G]way, you [A]rolling [D]river.
For [D]her I'd [G]cross your [D]roaming [Bm]waters,
A[Bm]way, I'm [G]bound a[D]way, 'cross the [A]wide Mis[D]souri.
"""

DANNY_BOY = """\
# Verse 1
Oh [C]Danny [C7]boy, the [F]pipes, the pipes are [C]calling
From [C]glen to [Am]glen, and [D7]down the mountain [G7]side.
The [C]summer's [C7]gone, and [F]all the roses [Fm]falling,
'Tis [C]you, 'tis [Am]you must [G7]go and I must [C]bide.
# Refrain
But [G7]come ye back when [C]summer's in the [F]meadow,
Or [G7]when the valley's [C]hushed and white with [E7]snow,
'Tis [C]I'll be [C7]here in [F]sunshine or in [Fm]shadow,
Oh [C]Danny [Am]boy, oh [Dm]Danny [G7]boy, I [C]love you [F]so. [C]
"""

AMAZING_GRACE = """\
# Verse 1
A[G]mazing [G7]grace, how [C]sweet the [G]sound
That saved a [Em]wretch like [D]me.
I [G]once was [G7]lost, but [C]now am [G]found,
Was [Em]blind, but [D]now I [G]see.
# Verse 2
'Twas [G]grace that [G7]taught my [C]heart to [G]fear,
And grace my [Em]fears re[D]lieved;
How [G]precious [G7]did that [C]grace ap[G]pear
The [Em]hour I [D]first be[G]lieved.
# Verse 3
Through [G]many [G7]dangers, [C]toils and [G]snares
I have al[Em]ready [D]come;
'Tis [G]grace hath [G7]brought me [C]safe thus [G]far,
And [Em]grace will [D]lead me [G]home.
"""

HARD_TIMES = """\
# Verse 1
Let us [D]pause in life's [G]pleasures and [D]count its many [A]tears,
While we [D]all sup [G]sorrow [D]with the [A]poor;
There's a [D]song that will [G]linger for[D]ever in our [Bm]ears;
Oh! [D]Hard times [A]come again no [D]more.
# Chorus
'Tis the [G]song, the [D]sigh of the [A]weary,
[D]Hard times, hard [G]times, come a[D]gain no [A]more.
Many [D]days you have [G]lingered a[D]round my cabin [Bm]door;
Oh! [D]Hard times [A]come again no [D]more.
"""

AULD_LANG_SYNE = """\
# Verse 1
Should [G]auld acquaintance [D]be forgot,
And [G]never brought to [C]mind?
Should [G]auld acquaintance [D]be forgot,
And [Em]auld [C]lang [D]syne[G]!
# Chorus
For [G]auld lang [D]syne, my jo,
For [G]auld lang [C]syne,
We'll [G]tak a cup o' [D]kindness yet,
For [Em]auld [C]lang [D]syne[G].
"""

# 茉莉花 (Jasmine Flower), the folk song in its traditional words: the Chinese for the pinyin over it.
JASMINE = """\
# Verse 1
[G]好一朵[C]茉莉[G]花
[G]好一朵[C]茉莉[G]花
[C]满园花开[G]香也[Em]香不过[D]它
[G]我有心[C]采一朵[G]戴
[Em]又怕看[C]花的[D]人儿[G]骂
# Verse 2
[G]好一朵[C]茉莉[G]花
[G]好一朵[C]茉莉[G]花
[C]满园花开[G]比也[Em]比不过[D]它
[G]我有心[C]采一朵[G]戴
[Em]又怕来[C]年不[D]发[G]芽
"""

# (artist, title, chart, key): the library, in the order wanted.txt lists it.
SONGS = (
    ("Traditional", "Scarborough Fair", SCARBOROUGH, "Am"),
    ("Traditional", "Greensleeves", GREENSLEEVES, "Am"),
    ("Traditional", "Shenandoah", SHENANDOAH, "D"),
    ("Traditional", "茉莉花", JASMINE, "G"),
    ("John Newton", "Amazing Grace", AMAZING_GRACE, "G"),
    ("Frederic Weatherly", "Danny Boy", DANNY_BOY, "C"),
    ("Stephen Foster", "Hard Times Come Again No More", HARD_TIMES, "D"),
    ("Robert Burns", "Auld Lang Syne", AULD_LANG_SYNE, "G"),
)

# The rest of Ultimate Guitar's index, as its sitemaps list chords: what a search finds beside your songs.
INDEX = (
    ("stephen-foster", "beautiful-dreamer"), ("stephen-foster", "camptown-races"),
    ("stephen-foster", "jeanie-with-the-light-brown-hair"), ("stephen-foster", "my-old-kentucky-home"),
    ("stephen-foster", "oh-susanna"), ("stephen-foster", "old-folks-at-home"),
    ("robert-burns", "a-red-red-rose"), ("traditional", "the-water-is-wide"),
    ("traditional", "wayfaring-stranger"), ("traditional", "the-parting-glass"),
)
FIRST_TAB = 4000001  # the made-up tab id of the first song's sheet, and so on

SONGBOOK = "Campfire"
SET_LIST = ("Traditional - Greensleeves", "John Newton - Amazing Grace", "Traditional - Scarborough Fair",
            "Traditional - Shenandoah", "Frederic Weatherly - Danny Boy", "Robert Burns - Auld Lang Syne")

# Greensleeves for the Guitar Pro page, in 3/4: its melody an octave down in open position, and its chords.
GREENSLEEVES_TEX = r"""\title "Greensleeves"
\artist "Traditional"
\tempo 84
.
\track "Melody"
\staff {score tabs}
\instrument 25
\ts 3 4
:2 r :4 2.3 |
:2 1.2 :4 3.2 | :4 0.1{d} :8 1.1 :4 0.1 | :2 3.2 :4 0.2 | :4 0.3{d} :8 2.3 :4 0.2 |
:2 1.2 :4 2.3 | :4 2.3{d} :8 1.3 :4 2.3 | :2 0.2 :4 1.3 | :2 2.4 :4 2.3 |
:2 1.2 :4 3.2 | :4 0.1{d} :8 1.1 :4 0.1 | :2 3.2 :4 0.2 | :4 0.3{d} :8 2.3 :4 0.2 |
:4 1.2{d} :8 0.2 :4 2.3 | :4 1.3{d} :8 4.4 :4 1.3 | :2 2.3{d} |
\track "Chords"
\staff {score tabs}
\instrument 25
\ts 3 4
:2 r :4 r |
"""
GREENSLEEVES_CHORDS = ("Am", "C", "G", "Em", "Am", "E", "E", "E", "Am", "C", "G", "Em", "Am", "E7", "Am")  # a bar each
SHAPES = {  # each chord's notes, fret.string from the first string
    "Am": "(0.1 1.2 2.3 2.4 0.5)", "C": "(0.1 1.2 0.3 2.4 3.5)", "G": "(3.1 0.2 0.3 0.4 2.5 3.6)",
    "Em": "(0.1 0.2 0.3 2.4 2.5 0.6)", "E": "(0.1 0.2 1.3 2.4 2.5 0.6)", "E7": "(0.1 3.2 1.3 0.4 2.5 0.6)",
}


def greensleeves_tex() -> str:
    """Greensleeves in alphaTex, its chords strummed once a bar, a dotted half each."""
    return GREENSLEEVES_TEX + " ".join(f":2 {SHAPES[c]}{{d}} |" for c in GREENSLEEVES_CHORDS) + "\n"


def slug(name: str) -> str:
    """A name as Ultimate Guitar's addresses write it: "Robert Burns" is robert-burns."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def width(ch: str) -> int:
    """The columns a character takes in a monospace font, as chordpro.py counts them: two for a Chinese one."""
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def ug_markup(chart: str) -> str:
    """A chart written inline, as Ultimate Guitar's markup: each chord over the column of its syllable."""
    out = []
    for line in chart.splitlines():
        if line.startswith("# "):
            out.append(f"[{line[2:]}]")
            continue
        chords, lyric, column = [], "", 0
        for part in re.split(r"(\[[^\]]+\])", line):
            if part.startswith("["):
                chords.append((column, part[1:-1]))
            else:
                lyric += part
                column += sum(width(c) for c in part)
        chord_line, used = "", 0
        for at, name in chords:
            if chord_line and at <= used:
                raise ValueError(f"chords too close together in {line!r}")
            chord_line += " " * (at - used) + f"[ch]{name}[/ch]"
            used = at + len(name)
        out += [f"[tab]{chord_line}", f"{lyric.rstrip()}[/tab]"] if lyric.strip() else [chord_line]
    return "\r\n".join(out) + "\r\n"


# --- the library ------------------------------------------------------------------------------------------------


def environment(root: Path) -> dict[str, str]:
    """What caracole's config reads: every folder under ``root``, and the dev shell's fonts and alphaTab."""
    env = {"HOME": str(root / "home"), "STATE_DIRECTORY": str(root / "state"),
           "CACHE_DIRECTORY": str(root / "cache"), "CARACOLE_YTDLP_BIN": str(root / "no-yt-dlp")}
    for name in ("CARACOLE_CJK_FONT", "CARACOLE_PDF_FONTS", "CARACOLE_ALPHATAB_DIR"):
        if os.environ.get(name):
            env[name] = os.environ[name]
    return env


def build(root: Path, browser_profile: Path):
    """The demo library under ``root``; its config."""
    from helpers.guitar import keep_guitar
    from helpers.ug_pages import version_dict

    from caracole import db
    from caracole.config import load_config
    from caracole.library import keep_file, song_dir, write_atomic, write_info
    from caracole.normalize import identity_key, ug_slug_key
    from caracole.overrides import Overrides
    from caracole.render import render_all
    from caracole.songbook import make_songbook, render_songbooks, set_song_setting, songbooks_file
    from caracole.songs import find_song, get_song, refresh_status, update_song
    from caracole.todo import write_pages
    from caracole.ug.index import build_index
    from caracole.ug.page import strip_markup
    from caracole.versions import upsert_version
    from caracole.viewer.version import Setting
    from caracole.wanted import sync_wanted

    for name in ("CARACOLE_PDF_FONTS", "CARACOLE_ALPHATAB_DIR"):
        if not os.environ.get(name):
            sys.exit(f"{name} isn't set: run this in nix develop")
    cfg = load_config(None, env=environment(root))
    cfg.library_dir.mkdir(parents=True)
    cfg.wanted_file.write_text("".join(f"{a} - {t}\n" for a, t, _, _ in SONGS), encoding="utf-8")
    conn = db.connect(cfg.db_path)
    sync_wanted(conn, cfg.wanted_file, NOW)

    sitemap = []
    for n, (artist, title, chart, key) in enumerate(SONGS):
        song = find_song(conn, identity_key(artist, title))
        content = ug_markup(chart)
        raw = version_dict(FIRST_TAB + n, song=title, artist=artist, tonality_name=key, rating=4.8, votes=120)
        vid = upsert_version(conn, provider="ug", tab_id=str(raw["id"]), song_id=song.id, slot="sheet",
                             kind="chords", rating=4.8, votes=120, version=1, label=None, url=raw["tab_url"],
                             raw=raw, now=FETCHED)
        keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
                  data=strip_markup(content).encode("utf-8"), rank=1)
        doc = {"version": raw, "content": content, "url": raw["tab_url"], "meta": []}
        write_atomic(song_dir(cfg.library_dir, song) / "sheet.json", json.dumps(doc, ensure_ascii=False).encode())
        if title.isascii():  # as the match and fetch steps leave a song they found
            sitemap.append((slug(artist), slug(title), FIRST_TAB + n))
            update_song(conn, song.id, match_decision="accept", match_step="exact", match_score=100.0,
                        match_artist_key=ug_slug_key(slug(artist)), match_song_key=ug_slug_key(slug(title)),
                        matched_at=FETCHED, ug_dirty=False, ug_checked_at=FETCHED)
        refresh_status(conn, song.id, ignored=False)
        write_info(conn, cfg.library_dir, get_song(conn, song.id))
    sitemap += [(a, s, FIRST_TAB + 100 + n) for n, (a, s) in enumerate(INDEX)]

    sitemaps = root / "sitemaps"
    sitemaps.mkdir()
    urls = "".join(f"<url><loc>https://tabs.ultimate-guitar.com/tab/{a}/{s}-chords-{tab}</loc></url>\n"
                   for a, s, tab in sitemap)
    (sitemaps / "sitemap1.xml").write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}</urlset>\n", encoding="utf-8")
    build_index(conn, None, NOW, from_dir=sitemaps)

    greensleeves = find_song(conn, identity_key("Traditional", "Greensleeves"))
    keep_guitar(conn, cfg, greensleeves, guitar_file(browser_profile), name="guitar-1.gp")

    render = render_all(conn, cfg, Overrides())
    if render.failed:
        sys.exit(f"rendering failed: {render}")
    book = songbooks_file(cfg.library_dir)
    make_songbook(book, SONGBOOK, list(SET_LIST))
    set_song_setting(book, SONGBOOK, "John Newton - Amazing Grace", Setting(key="A", capo=0))
    books = render_songbooks(conn, cfg, Overrides())
    if books.failed or books.error:
        sys.exit(f"the songbook failed: {books}")
    for made in (cfg.library_dir / "_songbooks" / SONGBOOK).iterdir():  # the day the Songbooks tab says it changed
        os.utime(made, (NOW.timestamp(), NOW.timestamp()))
    write_pages(conn, cfg, Overrides(), NOW)
    conn.commit()
    conn.close()
    return cfg


def guitar_file(profile: Path) -> bytes:
    """Greensleeves as a Guitar Pro 7 file, written by alphaTab's own exporter in a page of nothing."""
    from helpers import browser
    from helpers.guitar import export_alphatex

    browser.marked = True  # the helpers' guard for the test suite: this is no test
    with browser.Browser(profile / "export") as b:
        return export_alphatex(b, greensleeves_tex())


# --- caracole serve ---------------------------------------------------------------------------------------------


def serve(cfg, port: int = 0):
    """caracole serve's app for ``cfg`` on 127.0.0.1, its queue never started; the server and its address."""
    from caracole.web.app import WebApp
    from caracole.web.jobs import JobQueue
    from caracole.web.security import allowed_hosts
    from caracole.web.server import make_server

    def refuse(args, emit):
        raise RuntimeError(f"the demo runs no command: {args}")

    app = WebApp(cfg, JobQueue(refuse), allowed=allowed_hosts("127.0.0.1"), searches_lacuerda=False, badge="Demo")
    server = make_server(app, "127.0.0.1", port)
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


# --- the pictures -----------------------------------------------------------------------------------------------

DESKTOP = (1280, 800, False)  # width, height in CSS pixels, a phone's screen
SHORTER = (1280, 790, False)  # the foot's PDF button under the bar, and the Harmony panel cut between two links
PHONE = (390, 844, True)
SETTLED = ("document.readyState === 'complete' && document.fonts.status === 'loaded'"
           " && document.getAnimations().every((a) => a.playState !== 'running')")


def named(selector: str, starts: str, as_id: str) -> str:
    """JavaScript that gives the first element ``selector`` finds whose text starts with ``starts`` the id
    ``as_id``, to click it by; true once it has."""
    return (f"(() => {{ const e = [...document.querySelectorAll({json.dumps(selector)})]"
            f".find((e) => e.textContent.trim().startsWith({json.dumps(starts)}));"
            f" if (e) e.id = {json.dumps(as_id)}; return Boolean(e); }})()")


def below(selector: str, margin: int = 24) -> str:
    """JavaScript for a clip of the page's whole width, from its top to ``margin`` below what ``selector`` finds."""
    return (f"(() => {{ const r = document.querySelector({json.dumps(selector)}).getBoundingClientRect();"
            f" return [0, 0, innerWidth, Math.ceil(r.bottom + scrollY) + {margin}]; }})()")


# Each picture: its file's name, its address on the server, the screen, then what is done before it is taken, in
# order ("wait" an expression, "click" a selector, "type" text into the focused field, "js" an expression), and
# its clip (JavaScript for [x, y, width, height] in CSS pixels, within the screen; None: the screen whole). The last
# "wait" must still hold once the picture is taken, or the script stops: a picture that missed it is never written.
SHOTS = (
    ("library", "", DESKTOP, (
        ("wait", "document.getElementById('q') !== null"),
        ("js", "document.getElementById('q').focus()"),
        ("type", "traditional"),
        ("wait", named("#found button", "+ ", "more")),
        ("click", "#more"),
        ("wait", "document.querySelectorAll('#found .groups section.artist .line').length >= 7"),
        ("js", "document.activeElement.blur()"),
    ), below("#found .groups", 12)),
    ("sheet", "Traditional/Greensleeves/sheet.html", DESKTOP, (
        ("wait", "document.querySelector('#sheet .c') !== null"),
        ("click", "#more"),
        ("wait", "!document.getElementById('panel').hidden"),
        ("js", "document.activeElement.blur()"),
    ), None),
    ("harmony", "Frederic%20Weatherly/Danny%20Boy/sheet.html#nm=both&necks=0", SHORTER, (
        ("wait", "document.querySelector('#sheet .c') !== null"),
        ("click", "#more"),
        ("click", "#harmony-open"),
        ("wait", "!document.getElementById('harmony').hidden"),
        ("js", "document.activeElement.blur()"),
    ), None),
    ("phone-chord", "Traditional/Scarborough%20Fair/sheet.html", PHONE, (
        ("wait", "document.querySelectorAll('#sheet .c').length > 1"),
        ("js", "document.querySelectorAll('#sheet .c')[1].id = 'tapped'"),  # the first line's G
        ("click", "#tapped"),
        ("wait", "!document.getElementById('card').hidden"),
        ("js", "scrollTo(0, 0)"),
    ), None),
    ("phone-pinyin", "Traditional/%E8%8C%89%E8%8E%89%E8%8A%B1/sheet.html#py=1", PHONE, (
        ("wait", "document.querySelector('#sheet ruby') !== null"),
    ), None),
    ("songbooks", "#tab=songbooks", DESKTOP, (
        ("wait", "document.querySelector('#songbooks button.plays.set') !== null"),
        ("js", "document.querySelector('#songbooks button.plays.set').id = 'chip'"),  # Amazing Grace, set in A
        ("click", "#chip"),  # its key, mode and capo, open
        ("js", "document.activeElement.blur()"),  # no focus ring on its Key menu
        ("wait", "document.querySelector('#songbooks .set-line.editing select') !== null"),
    ), below("#songbooks article.book")),
    ("guitar-pro", "guitar?file=Traditional%2FGreensleeves%2Fguitar-1.gp", DESKTOP, (
        ("wait", "document.documentElement.dataset.player === 'ready'"),
    ), "[0, 0, innerWidth, 662]"),  # the first line of the score
)
PDF_PAGE = 3  # the songbook's first song, after its cover and its contents
PDF_DPI = 144
PDF_CROP = (0.72, 0.58)  # of the page's width and height: the song, without the blank beside and below it


def take(url: str, out: Path, profile: Path, cfg) -> list[Path]:
    """Every picture of SHOTS, from the server at ``url``, and the songbook's page; their paths."""
    from helpers import browser

    browser.marked = True
    written = []
    for n, (name, address, (width, height, mobile), steps, clip) in enumerate(SHOTS):
        with browser.Browser(profile / f"shot-{n}", width=width, height=height, mobile=mobile, timeout=60) as b:
            b.send("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=SCALE,
                   mobile=mobile)
            b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
            b.send("Emulation.setScrollbarsHidden", hidden=True)
            b.open(url + address)
            for do, what in steps:
                if do == "wait" and not b.wait(what, timeout=60):
                    sys.exit(f"{name}: the page never came to {what}")
                elif do == "click":
                    b.click(what)
                elif do == "type":
                    b.type(what)
                elif do == "js":
                    b.js(what)
            b.send("Input.dispatchMouseEvent", type="mouseMoved", x=0, y=0)  # no hover left where it clicked
            if not b.wait(SETTLED, timeout=30):
                sys.exit(f"{name}: the page never settled")
            x, y, w, h = b.js(clip) if clip else (0, 0, width, height)
            if x < 0 or y < 0 or x + w > width or y + h > height:
                sys.exit(f"{name}: the clip {[x, y, w, h]} goes past the screen, {width} × {height}")
            # Never beyond the screen: Chromium would resize it for the picture, and a page that redraws for its
            # width (the Songbooks tab, closing the key editor) would come out in another state.
            shot = b.send("Page.captureScreenshot", format="png", captureBeyondViewport=False,
                          clip={"x": x, "y": y, "width": w, "height": h, "scale": 1})
            last = [what for do, what in steps if do == "wait"][-1]
            if not b.js(last):
                sys.exit(f"{name}: the page left {last} while its picture was taken")
        path = out / f"{name}.png"
        path.write_bytes(base64.b64decode(shot["data"]))
        written.append(path)

    pdf = cfg.library_dir / "_songbooks" / SONGBOOK / "songbook.pdf"
    side = round(PDF_DPI / 72 * 595 * PDF_CROP[0]), round(PDF_DPI / 72 * 842 * PDF_CROP[1])  # A4: 595 × 842 pt
    subprocess.run(["pdftoppm", "-f", str(PDF_PAGE), "-l", str(PDF_PAGE), "-r", str(PDF_DPI), "-png", "-singlefile",
                    "-W", str(side[0]), "-H", str(side[1]), str(pdf), str(out / "songbook-pdf")], check=True)
    written.append(out / "songbook-pdf.png")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--serve", action="store_true", help="build the library and serve it until Ctrl-C")
    parser.add_argument("--port", type=int, default=8740)
    parser.add_argument("--out", type=Path, default=HERE, help="where the pictures go (this folder)")
    args = parser.parse_args()
    from helpers.browser import CHROMIUM

    missing = [tool for tool in ("chordpro", *(() if args.serve else ("pdftoppm", "oxipng")))
               if shutil.which(tool) is None] + (["chromium"] if CHROMIUM is None else [])
    if missing:
        sys.exit(f"not on PATH: {', '.join(missing)} (see this script's docstring)")
    with tempfile.TemporaryDirectory(prefix="caracole-demo-") as tmp:
        root = Path(tmp)
        cfg = build(root, root / "chromium")
        if args.serve:
            server, url = serve(cfg, args.port)
            print(f"the demo library: {url} (Ctrl-C stops it)", flush=True)
            signal.signal(signal.SIGTERM, signal.default_int_handler)  # a kill stops it as Ctrl-C does
            signal.signal(signal.SIGINT, signal.default_int_handler)  # even started in the background
            try:
                while True:
                    time.sleep(3600)
            except KeyboardInterrupt:
                pass
            finally:
                server.shutdown()
                server.server_close()
            return
        server, url = serve(cfg)
        try:
            written = take(url, args.out, root / "chromium", cfg)
        finally:
            server.shutdown()
            server.server_close()
    subprocess.run(["oxipng", "-q", "-o", "max", "--strip", "safe", *map(str, written)], check=True)
    for path in written:
        print(f"{path.relative_to(REPO) if path.is_relative_to(REPO) else path}: {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
