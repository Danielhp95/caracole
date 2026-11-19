"""A chosen theme picks the viewer's palette on screen, whatever the system's scheme (viewer.css), and Aa chooses
it, kept for every viewer page (screen.js, ``window.caracoleScreen``).

``html[data-theme="light"|"dark"]`` wins over ``prefers-color-scheme``; no attribute is Auto, today's rule. The dark
palette is written twice (a media query and an attribute can't share a selector): a test fails on any token one
copy lacks. The choice is kept as the rail of necks is: localStorage ``caracole-viewer-theme`` (``auto``, ``light``,
``dark``), and ``theme=`` in the address while it isn't Auto, which a link to another page of the song and a songbook's
next song take on, so that it holds where the browser keeps nothing (caracole serve's sandbox).
"""

from __future__ import annotations

import re

import pytest

from caracole.inline import sha256_source
from caracole.viewer import build_viewer, page
from caracole.viewer.book import BookSong, build_songbook
from caracole.viewer.harptab_page import build_harmonica_viewer

from helpers.browser import in_chromium
from helpers.version_pages import WONDERWALL, folder
from helpers.viewer_pages import NO_STORAGE, key, viewer, written
from test_viewer_necks import reload
from test_viewer_numerals import IN_C, contrast, middle

SONG = """{title: Theme Song}
{key: C}
{start_of_verse: Verse}
[C]First line of the [G]song
[Am]Second line goes [F]on
[C]Third line of the [G]song
{end_of_verse}
{start_of_chorus: Chorus}
[F]Fourth line to [C]sing
[G]Fifth line to [Am]sing
[F]Sixth line to [C]end
{end_of_chorus}
"""

PALETTE = """(() => { const root = [...document.styleSheets].flatMap((s) => [...s.cssRules])
    .find((r) => r.selectorText === ":root" && r.style.getPropertyValue("--bg"));
  const css = getComputedStyle(document.documentElement);
  return {scheme: css.colorScheme, vars: Object.fromEntries([...root.style].filter((n) => n.startsWith("--"))
    .map((n) => [n, css.getPropertyValue(n).trim()]))}; })()"""


@in_chromium
def test_a_chosen_theme_wins_over_the_system_on_screen(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        own, chosen = {}, {}
        for system in ("light", "dark"):
            b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": system}])
            b.js("delete document.documentElement.dataset.theme")
            own[system] = b.js(PALETTE)
            for theme in ("light", "dark"):
                b.js(f"document.documentElement.dataset.theme = '{theme}'")
                chosen[system, theme] = b.js(PALETTE)
    assert own["light"]["vars"]["--bg"] == "#f7f6f3" and own["dark"]["vars"]["--bg"] == "#131312"
    for (system, theme), seen in chosen.items():
        assert seen["vars"] == own[theme]["vars"], (system, theme)  # one dark palette, one light
        assert seen["scheme"] == theme


# --- Aa: Auto, Light or Dark, kept for every page ------------------------------------------------------------------

OTHER = SONG.replace("Theme Song", "Other Song")
DARK, LIGHT = "rgb(19, 19, 18)", "rgb(247, 246, 243)"  # the body's --bg in each palette
READY = "document.documentElement.dataset.ready === '1'"
# What the page shows of the theme: the attribute, the body's background and the root's scheme, the Aa box's buttons
# pressed, what the browser keeps ("refused" where it keeps nothing) and the address.
STATE = """(() => { const doc = document.documentElement;
  let kept;
  try { kept = localStorage.getItem('caracole-viewer-theme'); } catch (err) { kept = 'refused'; }
  return {theme: doc.dataset.theme || null, bg: getComputedStyle(document.body).backgroundColor,
    scheme: getComputedStyle(doc).colorScheme, kept, hash: location.hash, error: doc.dataset.error || null,
    pressed: [...document.querySelectorAll('#theme > button')].filter((e) => e.getAttribute('aria-pressed') === 'true')
      .map((e) => e.id)}; })()"""


def inlined(name: str) -> str:
    """viewer/'s script ``name`` as a page inlines it."""
    return f"<script>{(page.HERE / name).read_text(encoding='utf-8')}</script>"


def system(b, scheme: str) -> None:
    """The system's colour scheme, ``light`` or ``dark`` (with no reduced motion, as ``viewer`` opens a page)."""
    b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme},
                                                   {"name": "prefers-reduced-motion", "value": "no-preference"}])


def choose(b, theme: str) -> None:
    """Aa opened (unless it is), and ``theme`` chosen there: Auto, Light or Dark."""
    if b.js("document.getElementById('sizes').hidden"):
        b.click("#size")
    b.click(f"#theme-{theme}")
    assert b.wait(f"document.getElementById('theme-{theme}').getAttribute('aria-pressed') === 'true'")


def test_screen_js_is_inlined_in_the_head_of_every_viewer_page():
    # In the head, so the theme is the page's before its body is drawn: a slow phone never shows the other palette
    # first. Allowed by its hash as every script is, the first the policy names (the page's order).
    assert page.HERE / "screen.js" in page.BUILD_FILES
    screen = inlined("screen.js")
    pages = [
        build_viewer(SONG),
        build_viewer(SONG, export=False),  # a kept version's page
        build_songbook("Book", [BookSong("Theme Song", "Artist", cho=SONG, id="aaaa")]),
        build_harmonica_viewer("4 -4 5", title="T", tab_file="harmonica-1.txt"),
    ]
    for html in pages:
        head = html[:html.index("</head>")]
        assert html.count(screen) == 1 and screen in head
        assert head.index("<style>") < head.index(screen)  # after the stylesheets, the head's last
        assert html.index("</head>") < html.index("<body>") < html.index("<script>", html.index("<body>"))
        assert re.search(r"script-src (\S+)", html).group(1) == sha256_source(page._screen())
    # It makes no element of its own and loads nothing; at start-up it reads the root, the address, storage and the
    # navigation alone, never the body (the head has none).
    for word in ("innerHTML", "createElement", "fetch(", "XMLHttpRequest", "import(", "eval(", "new Function",
                 "document.body", "getElementById", "querySelector"):
        assert word not in page._screen(), word


# A script run as each document starts (``viewer``'s ``before``): the theme the root has once the body is there, read
# at the first chance after the body is made (a microtask checkpoint comes before the body's first script runs).
AT_BODY = """new MutationObserver((records, observer) => {
  if (!document.body) return;
  window.caracoleAtBody = document.documentElement.dataset.theme || null;
  observer.disconnect();
}).observe(document, {childList: true, subtree: true});"""


@in_chromium
@pytest.mark.parametrize("kind", ["sheet", "songbook", "harmonica"])
def test_the_theme_is_the_pages_before_its_body_is(tmp_path, kind):
    if kind == "sheet":
        url = written(tmp_path, SONG) + "#theme=dark"
    elif kind == "songbook":
        path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
        path.parent.mkdir(parents=True)
        path.write_text(build_songbook("Campfire", [BookSong("Theme Song", "Synthetic", cho=SONG, id="aaaa")]),
                        encoding="utf-8")
        url = path.as_uri() + "#song-1&theme=dark"
    else:
        path = tmp_path / "Artist" / "Title" / "harmonica-1.html"
        path.parent.mkdir(parents=True)
        path.write_text(build_harmonica_viewer("4 -4 5", title="T", tab_file="harmonica-1.txt"), encoding="utf-8")
        url = path.as_uri() + "#theme=dark"
    with viewer(tmp_path, url, before=[AT_BODY]) as b:
        system(b, "light")
        named = b.js("window.caracoleAtBody")
        if kind == "sheet":  # and Dark kept by the browser, the address naming none
            choose(b, "dark")
            b.open(url.split("#")[0])
            assert b.wait(READY)
            kept = b.js("[window.caracoleAtBody, location.hash]")
            assert kept[0] == "dark", kept
    assert named == "dark"


@in_chromium
def test_aa_offers_auto_light_and_dark_and_the_choice_holds_for_every_page(tmp_path):
    url, other = written(tmp_path, SONG), written(tmp_path, OTHER, name="Other")
    with viewer(tmp_path, url) as b:
        system(b, "light")
        b.click("#size")
        offered = b.js("[...document.querySelectorAll('#theme > button')].map((e) => e.textContent)")
        group = b.js("[document.getElementById('theme').getAttribute('role'),"
                     " document.getElementById('theme').getAttribute('aria-label')]")
        first = b.js(STATE)
        choose(b, "dark")
        dark = b.js(STATE)
        b.open(other)  # another song's page, its address naming no theme
        assert b.wait(READY + " && location.href.includes('Other')")
        elsewhere = b.js(STATE)
        b.open(url)
        assert b.wait(READY + " && !location.href.includes('Other')")
        choose(b, "auto")
        auto = b.js(STATE)
        system(b, "dark")
        auto_dark = b.js(STATE)
    assert offered == ["Auto", "Light", "Dark"] and group == ["group", "Theme"]
    assert first["pressed"] == ["theme-auto"] and first["theme"] is None and first["bg"] == LIGHT
    assert dark["theme"] == "dark" and dark["bg"] == DARK and dark["pressed"] == ["theme-dark"]
    assert dark["kept"] == "dark" and "theme=dark" in dark["hash"]
    assert elsewhere["theme"] == "dark" and elsewhere["bg"] == DARK and elsewhere["pressed"] == ["theme-dark"]
    assert auto["theme"] is None and "theme=" not in auto["hash"] and auto["kept"] == "auto"
    assert auto["pressed"] == ["theme-auto"] and auto["bg"] == LIGHT
    assert auto_dark["theme"] is None and auto_dark["bg"] == DARK  # Auto: as the system is


@in_chromium
def test_light_chosen_holds_on_a_dark_system(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        system(b, "dark")
        own = b.js(STATE)
        choose(b, "light")
        chosen = b.js(STATE)
        reload(b)
        again = b.js(STATE)
    assert own["bg"] == DARK and own["theme"] is None
    for seen in (chosen, again):
        assert seen["theme"] == "light" and seen["bg"] == LIGHT and seen["scheme"] == "light", seen
        assert seen["pressed"] == ["theme-light"] and "theme=light" in seen["hash"]


@in_chromium
def test_without_storage_the_address_carries_the_theme(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG), before=[NO_STORAGE]) as b:
        system(b, "light")
        choose(b, "dark")
        reload(b)
        again = b.js(STATE)
    assert again["kept"] == "refused" and again["error"] is None
    assert again["theme"] == "dark" and again["bg"] == DARK and "theme=dark" in again["hash"]
    assert again["pressed"] == ["theme-dark"]


@in_chromium
def test_a_songbook_carries_the_theme_to_its_next_song_and_its_contents_follow(tmp_path):
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_songbook("Campfire", [BookSong("Theme Song", "Synthetic", cho=SONG, id="aaaa"),
                                                BookSong("Other Song", "Synthetic", cho=OTHER, id="bbbb")]),
                    encoding="utf-8")
    with viewer(tmp_path, path.as_uri() + "#song-1", before=[NO_STORAGE]) as b:
        system(b, "light")
        choose(b, "dark")
        b.js("window.before = true")
        key(b, "ArrowRight", 39)
        assert b.wait(f"!window.before && location.hash.startsWith('#song-2') && {READY}")
        second = b.js(STATE)
        b.js("window.before = true; location.hash = ''")  # the contents
        assert b.wait("!window.before && document.documentElement.dataset.view === 'contents'")
        contents = b.js(STATE)
    assert second["theme"] == "dark" and second["bg"] == DARK and "theme=dark" in second["hash"]
    assert second["pressed"] == ["theme-dark"] and second["error"] is None
    assert "theme=dark" in contents["hash"] and contents["theme"] == "dark" and contents["bg"] == DARK


@in_chromium
def test_a_link_to_another_page_of_the_song_takes_the_theme(tmp_path):
    pages = folder(tmp_path, WONDERWALL)
    with viewer(tmp_path, pages["sheet.html"].as_uri()) as b:
        choose(b, "dark")
        links = b.js("[...document.querySelectorAll('#version-list a[data-page]')].map((a) => a.getAttribute('href'))")
    assert links and all("#" in link and "theme=dark" in link.split("#", 1)[1] for link in links), links


@in_chromium
def test_reset_all_leaves_the_theme(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG) + "#t=2") as b:
        system(b, "light")
        choose(b, "dark")
        b.click("#more")
        assert b.wait("!document.getElementById('panel').hidden")
        b.click("#reset-all")
        assert b.wait("!location.hash.includes('t=2')")
        reset = b.js(STATE)
    assert reset["theme"] == "dark" and reset["bg"] == DARK and reset["kept"] == "dark"
    assert "theme=dark" in reset["hash"] and reset["pressed"] == ["theme-dark"]


@in_chromium
def test_the_aa_box_is_whole_on_a_320_px_phone(tmp_path):
    with viewer(tmp_path, written(tmp_path, SONG), width=320, height=640) as b:
        b.click("#size")
        assert b.wait("!document.getElementById('sizes').hidden")
        box = b.js("""(() => { const r = document.getElementById('sizes').getBoundingClientRect();
          return {left: r.left, right: r.right, page: document.documentElement.scrollWidth,
            coarse: matchMedia('(pointer: coarse)').matches,
            heights: [...document.querySelectorAll('#sizes button')].map((e) => e.getBoundingClientRect().height)};
          })()""")
    assert box["coarse"] and box["left"] >= 0 and box["right"] <= 320 and box["page"] <= 320, box
    # A finger's 48 px, every button of the box alike (5d's), the theme's too
    assert len(box["heights"]) == 5 and min(box["heights"]) >= 48, box


@in_chromium
def test_the_text_size_is_as_it_was(tmp_path):
    """D5 A: Aa's text size is today's, A− and A+ stepping 13 to 30 px by 2 from 18 px."""
    said = ("[document.getElementById('fs-now').textContent, location.hash,"
            " document.getElementById('smaller').getAttribute('aria-disabled'),"
            " document.getElementById('bigger').getAttribute('aria-disabled')]")
    with viewer(tmp_path, written(tmp_path, SONG)) as b:
        b.click("#size")
        start = b.js(said)
        up = []
        for _ in range(7):
            b.click("#bigger")
            up.append(b.js(said))
        down = []
        for _ in range(10):
            b.click("#smaller")
            down.append(b.js(said)[0])
        low = b.js(said)
    assert start == ["18 px", "", "false", "false"]
    assert up[0][:2] == ["20 px", "#fs=20"]
    assert [seen[0] for seen in up] == ["20 px", "22 px", "24 px", "26 px", "28 px", "30 px", "30 px"]
    assert up[-1][3] == "true"
    assert down[:9] == ["28 px", "26 px", "24 px", "22 px", "20 px", "18 px", "16 px", "14 px", "13 px"]
    assert low[0] == "13 px" and low[2] == "true" and low[1] == "#fs=13"


UNREADABLE = "Intro\nthis is not a tab at all\njust words\n"


@in_chromium
@pytest.mark.parametrize("stem", ["124_heart-of-gold", None], ids=["read", "as written"])
def test_the_harmonica_tabs_page_offers_the_theme_and_takes_it_back_to_the_sheet(tmp_path, stem):
    from test_viewer_harptab_browser import tab

    text = tab(stem) if stem else UNREADABLE
    path = tmp_path / "Artist" / "Title" / "harmonica-1.html"
    path.parent.mkdir(parents=True)
    path.write_text(build_harmonica_viewer(text, title="T", tab_file="harmonica-1.txt", back="sheet.html"),
                    encoding="utf-8")
    url = path.as_uri()
    with viewer(tmp_path, url) as b:
        system(b, "light")
        choose(b, "dark")
        dark = b.js(STATE)
        href = b.js("document.querySelector('a.back[data-sheet]').getAttribute('href')")
    assert dark["theme"] == "dark" and dark["bg"] == DARK and dark["pressed"] == ["theme-dark"]
    assert "theme=dark" in href.split("#", 1)[1], href
    with viewer(tmp_path, url + "#theme=light") as b:
        system(b, "dark")
        named = b.js(STATE)
    assert named["theme"] == "light" and named["bg"] == LIGHT, named
    with viewer(tmp_path, url, width=320, height=640) as b:
        b.click("#size")
        assert b.wait("!document.getElementById('sizes').hidden")
        box = b.js("""(() => { const r = document.getElementById('sizes').getBoundingClientRect();
          return {left: r.left, right: r.right, page: document.documentElement.scrollWidth,
            heights: [...document.querySelectorAll('#sizes button')].map((e) => e.getBoundingClientRect().height)};
          })()""")
    assert box["left"] >= 0 and box["right"] <= 320 and box["page"] <= 320, box
    assert len(box["heights"]) == 5 and min(box["heights"]) >= 48, box


def lightness(colour: str) -> float:
    """CIE L* of an ``rgb(r, g, b)`` colour."""
    from test_viewer_numerals import luminance
    return 116 * luminance(colour) ** (1 / 3) - 16


COLOURS = """(() => { const css = (el, p) => getComputedStyle(el)[p];
  const on = document.querySelector("#sheet .c.on");
  const root = getComputedStyle(document.documentElement);
  return {bg: css(document.body, "backgroundColor"), surface: root.getPropertyValue("--surface").trim(),
    mark: root.getPropertyValue("--mark").trim(), on: on && css(on, "color"), onBg: on && css(on, "backgroundColor"),
    nms: on ? [...on.querySelectorAll(".nm")].map((n) => css(n, "color")) : [],
    roles: Object.fromEntries(["h", "a", "p"].map((r) => [r, css(document.querySelector(".nm.r-" + r), "color")]))}; })()"""


def hexrgb(h: str) -> str:
    h = h.lstrip("#")
    return "rgb(%d, %d, %d)" % tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


@in_chromium
@pytest.mark.parametrize("system,theme", [("light", ""), ("dark", "&theme=light")])
def test_a_tapped_chord_reads_at_4_5_to_1_in_the_light_theme(tmp_path, system, theme):
    with viewer(tmp_path, written(tmp_path, IN_C) + "#nm=both" + theme) as b:
        b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": system}])
        from helpers.viewer_pages import tap_at
        tap_at(b, *middle(b, "#sheet .c", 2))
        assert b.wait("!!document.querySelector('#sheet .c.on')")
        seen = b.js(COLOURS)
    assert contrast(seen["on"], seen["onBg"]) >= 4.5, seen
    assert seen["nms"] and all(contrast(n, seen["onBg"]) >= 4.5 for n in seen["nms"]), seen


@in_chromium
@pytest.mark.parametrize("system,theme", [("dark", ""), ("light", "&theme=dark")])
def test_the_dark_role_colours_differ_in_lightness(tmp_path, system, theme):
    with viewer(tmp_path, written(tmp_path, IN_C) + "#nm=both" + theme) as b:
        b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": system}])
        assert b.wait("getComputedStyle(document.body).backgroundColor === 'rgb(19, 19, 18)'")
        seen = b.js(COLOURS)
    roles = seen["roles"]
    for role, colour in roles.items():
        for ground in (seen["bg"], hexrgb(seen["surface"]), hexrgb(seen["mark"])):
            assert contrast(colour, ground) >= 4.5, (role, colour, ground)
    ls = sorted(lightness(c) for c in roles.values())
    assert ls[1] - ls[0] >= 10 and ls[2] - ls[1] >= 10, roles
