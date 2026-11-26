"""Stage 1f, a calmer page (library_assets/), in Chromium: four corner radii, one set of tokens in base.css; no outline
around the list or the key, one weight a role.

The page is served (a real server, a lookup running and one queued), so that a song's card, the tray, the Requests tab,
the Songbooks tab, the Sync sheet and a search's results hold what is measured: each state names what must be shown, and
how many; every element shown is measured, no lane left out.
The list's outline is measured on the page opened as a file too, by artist and by title, and on the lookup page."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from helpers import cards
from helpers.audio_files import audio
from helpers.browser import CHROMIUM_MARKS
from helpers.targets import odd_radii
from test_web_lookup_page import index_songs
from test_web_page_steps import driven, live  # noqa: F401  (``live``: a fixture)

from caracole.library import keep_file, song_dir
from caracole.library_page import build_library_page, write_library_page
from caracole.overrides import Overrides
from caracole.songbook import make_songbook, songbooks_file
from caracole.songs import update_song
from caracole.versions import upsert_version

from conftest import add_song

pytestmark = CHROMIUM_MARKS

# What a state shows: a selector, and at least how many of it are rendered (checkVisibility), so that a state that
# drew nothing fails rather than passes by having nothing to measure.
SHOWN = "Array.from(document.querySelectorAll(%s)).filter((n) => n.checkVisibility()).length"


def put_sheet(conn, cfg, song, tab_id, key):
    v = upsert_version(conn, provider="ug", tab_id=str(tab_id), song_id=song.id, slot="sheet", kind="chords",
                       rating=4.5, votes=12, version=1, label=None, url=f"https://tabs.ultimate-guitar.com/tab/{tab_id}",
                       raw={"tonality_name": key}, now="2026-10-27T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=song, version_id=v, name="sheet.txt", data=b"Words\n", rank=1)
    folder = song_dir(cfg.library_dir, song)
    (folder / "sheet.html").write_bytes(b"x")
    update_song(conn, song.id, status="found")


@pytest.fixture
def library(conn, cfg):
    """Three songs with sheets, each in its key (Oasis twice, so a band), a songbook of two of them, and two songs wanted
    (Creep, matched to Ultimate Guitar, and Hysteria) whose lines offer Fetch now."""
    for n, (artist, title, key) in enumerate((("Oasis", "Wonderwall", "Em"), ("Oasis", "Live Forever", "Am"),
                                             ("Eagles", "Desperado", "Gm"))):
        put_sheet(conn, cfg, add_song(conn, artist, title), n + 1, key)
    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep")
    add_song(conn, "Muse", "Hysteria")
    make_songbook(songbooks_file(cfg.library_dir), "Campfire", ["Oasis - Wonderwall", "Eagles - Desperado"])
    return creep


def odd_in(page, where: str, selector: str, floor: int) -> None:
    """Wait for ``selector`` to be rendered ``floor`` times or more, then: no corner radius but the four, anywhere on
    the page."""
    shown = SHOWN % json.dumps(selector)
    assert page.wait(f"{shown} >= {floor}", timeout=20), (where, selector, page.js(shown))
    assert page.js(odd_radii()) == [], where


@pytest.mark.parametrize("size", [(390, 844), (1280, 900)], ids=["phone", "laptop"])
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_the_library_page_has_four_corner_radii(library, live, tmp_path, size, scheme, monkeypatch):  # noqa: F811
    import caracole.library_page as library_page
    from caracole.audio_store import AUDIO_MAX

    # The bar's "+" drawn (a sheet from an audio file: its dialog measured too, refused, as this caracole makes none).
    monkeypatch.setattr(library_page, "audio_member", lambda cfg: {"ok": True, "why": None, "limit": AUDIO_MAX})
    base, runner = live
    from test_web_page_steps import FROM_UG

    runner.script = FROM_UG
    width, _ = size
    with driven(tmp_path, width) as page:
        page.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme},
                                                          {"name": "prefers-reduced-motion", "value": "reduce"}])
        page.open(base)
        odd_in(page, "library", "#list article.line", 5)
        # A lookup running and one waiting: a bar on a line, the tray (it shows from two requests), the Requests tab.
        for title in ("Creep", "Hysteria"):
            line = page.js("Array.from(document.querySelectorAll('#list article.line')).find((l) => "
                           f"l.querySelector('h3').textContent.includes({json.dumps(title)})).dataset.id")
            page.click(f"#list article.line[data-id='{line}'] form.fetch button")
        odd_in(page, "lines with a bar", "#list .progress.barred .step-segs", 1)
        odd_in(page, "the tray", "#tray:not([hidden]) .tray-toggle", 1)
        page.click("#tray-toggle")
        odd_in(page, "the tray open", "#tray-list:not([hidden]) li", 2)
        page.click("#tray-toggle")
        # The Filter panel.
        page.click("#filter")
        odd_in(page, "the filter panel", "#filter-panel[open] .seg", 1)
        page.press("Escape")
        assert page.wait("!document.getElementById('filter-panel').open")
        # The "+" and its dialog, a file chosen and refused.
        odd_in(page, "the + tool", "#add-audio", 1)
        picked = tmp_path / "song.mp3"
        picked.write_bytes(audio("MP3", 2.0))
        root = page.send("DOM.getDocument")["root"]["nodeId"]
        node = page.send("DOM.querySelector", nodeId=root, selector="#audio-file")["nodeId"]
        page.send("DOM.setFileInputFiles", files=[str(picked)], nodeId=node)
        odd_in(page, "the audio dialog", "#audio-sheet[open] .audio-acts .btn", 2)
        page.press("Escape")
        assert page.wait("!document.getElementById('audio-sheet').open")
        # A song's card (under its line on a phone, in the pane on a laptop): its tiles, a tile's drawer, the ⋯ menu.
        wonderwall = page.js("Array.from(document.querySelectorAll('#list article.line')).find((l) => "
                             "l.querySelector('h3').textContent.includes('Wonderwall')).dataset.id")
        page.click(cards.name_of(f"#list article.line[data-id='{wonderwall}']"))
        odd_in(page, "a card", ".song-card .tile", 1)
        page.click(".song-card .tile-more")
        odd_in(page, "a tile's drawer", ".song-card .drawer", 1)
        page.click(".song-card .foot-more-btn")
        odd_in(page, "the card's ⋯ menu", ".song-card .foot-more[open] .foot-menu", 1)
        page.click(".song-card .foot-more-btn")  # closed, on a touch screen it takes its history entry back
        assert page.wait("!document.querySelector('.song-card .foot-more[open]') && "
                         "!(history.state && history.state.caracoleMenu)")
        page.click(cards.name_of(f"#list article.line[data-id='{wonderwall}']"))
        assert page.wait(SHOWN % json.dumps(".song-card .tile") + " === 0")
        # A search's results.
        page.click("#q")
        page.type("wonder")
        odd_in(page, "a search", "body.search-mode #results article.line", 1)
        page.click("#leave")
        # Each tab.
        page.js("location.hash = '#tab=songbooks'")
        odd_in(page, "songbooks", "#songbooks .book-line", 1)
        page.click("#songbooks .book-line")
        odd_in(page, "a songbook opened", "#songbooks .set-line", 2)
        for tab, selector, floor in (("sites", "#sites .site-row", 3),
                                     ("requests", "#requests .req", 2),
                                     ("sync", "#sync .sync-panel", 1)):
            page.js(f"location.hash = '#tab={tab}'")
            odd_in(page, tab, selector, floor)
        page.js("location.hash = '#sheet=sync'")
        odd_in(page, "the sync sheet", "#sync-sheet[open] .sync-top", 1)


# The list with no outline, one weight a role: what is wrong of each, and how many of each were measured. A box of lines
# (.groups, .lines, .rows) has no border, shadow or fill of its own; each line or row after its box's first, and each
# group after its box's first, keeps its 1 px divider; a key is plain muted bold text; a song's title is semi-bold; a
# band names its artist bold in their colour, the count of yours muted.
CALM = """(() => {
  const css = getComputedStyle;
  const probe = (name) => { const i = document.createElement("i"); i.style.color = "var(" + name + ")";
    document.body.appendChild(i); const c = css(i).color; i.remove(); return c; };
  const muted = probe("--muted"), artist = probe("--artist");
  const shown = (root, selector) => Array.from(root.querySelectorAll(selector)).filter((n) => n.checkVisibility());
  const path = (n) => n.tagName.toLowerCase() + (n.id ? "#" + n.id : "") + "." + Array.from(n.classList).join(".") +
    " " + String(n.textContent || "").trim().replace(/\\s+/g, " ").slice(0, 24);
  const edges = (n) => ["Top", "Right", "Bottom", "Left"].map((side) => css(n)["border" + side + "Width"]);
  const pads = (n) => ["Top", "Right", "Bottom", "Left"].map((side) => css(n)["padding" + side]);
  const wrong = [], n = {};
  const count = (what, k) => { n[what] = (n[what] || 0) + k; };
  const boxes = shown(document, ".groups, .lines, .rows");
  count("boxes", boxes.length);
  for (const box of boxes) {
    const s = css(box);
    if (edges(box).some((w) => w !== "0px") || s.boxShadow !== "none" || s.backgroundColor !== "rgba(0, 0, 0, 0)") {
      wrong.push(["box", path(box), edges(box), s.boxShadow, s.backgroundColor]);
    }
  }
  for (const [what, box] of [["#list .groups", "#list .groups"], ["#list section.flat .lines", "#list section.flat .lines"],
                              ["#results .groups", "#results .groups"], [".rows", ".rows"]]) {
    count(what, shown(document, box).length);
  }
  const divided = (items, what) => items.forEach((item, i) => {
    const top = css(item).borderTopWidth;
    if (top !== (i ? "1px" : "0px")) wrong.push([what, path(item), i, top]);
  });
  for (const box of shown(document, ".lines, .rows")) {
    const items = shown(box, ":scope > article.line, :scope > .run > article.line, :scope > article.row");
    count("lines", items.length);
    divided(items, "line");
  }
  for (const box of shown(document, ".groups")) {
    const groups = shown(box, ":scope > section, :scope > .run > section");
    count("groups", groups.length);
    divided(groups, "group");
  }
  for (const key of shown(document, ".line-key, .row-key")) {
    count("keys", 1);
    const s = css(key);
    if (edges(key).some((w) => w !== "0px") || pads(key).some((p) => p !== "0px") || s.color !== muted ||
        s.fontWeight !== "700") wrong.push(["key", path(key), edges(key), pads(key), s.color, s.fontWeight]);
  }
  for (const title of shown(document, "#list .line-title h3, #results .line h3, .row-title")) {
    count("titles", 1);
    if (title.closest("#results")) count("results' titles", 1);
    if (css(title).fontWeight !== "600") wrong.push(["title", path(title), css(title).fontWeight]);
  }
  for (const name of shown(document, ".artist-title .artist-name")) {
    count("bands", 1);
    if (css(name).fontWeight !== "700" || css(name).color !== artist) {
      wrong.push(["band", path(name), css(name).fontWeight, css(name).color]);
    }
  }
  for (const counts of shown(document, ".artist-counts")) {
    if (css(counts).color !== muted) wrong.push(["counts", path(counts), css(counts).color]);
  }
  return { wrong, n, tokens: { muted, artist } };
})()"""


def calm_in(page, where: str, floors: dict[str, int]) -> None:
    """Nothing wrong with the list's outline and weights, and at least ``floors`` of each kind measured."""
    calm = page.js(CALM)
    assert calm["wrong"] == [], (where, calm["wrong"][:12])
    assert all(calm["n"].get(what, 0) >= floor for what, floor in floors.items()), (where, calm["n"])


@pytest.mark.parametrize("size", [(390, 844), (1280, 900)], ids=["phone", "laptop"])
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_no_outline_around_the_list_or_the_key(conn, cfg, library, live, tmp_path, size, scheme):  # noqa: F811
    base, _ = live
    width, _ = size
    index_songs(cfg, [("oasis", "wonderwall", 2)])  # Ultimate Guitar's versions too: a site's lines and rows
    html = build_library_page(conn, cfg, Overrides(), datetime(2026, 10, 27, tzinfo=UTC))
    path = write_library_page(cfg.library_dir, html)
    with driven(tmp_path, width) as page:
        page.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
        # The page as a file: by artist (Oasis's band over its two lines, Eagles, Radiohead and Muse folded), then by title.
        page.open(path.as_uri())
        assert page.wait(SHOWN % json.dumps("#list .groups article.line") + " >= 5")
        calm_in(page, "by artist", {"#list .groups": 1, "lines": 5, "groups": 4, "keys": 3, "titles": 5, "bands": 1})
        page.open(path.as_uri() + "#sort=title")
        assert page.wait(SHOWN % json.dumps("#list section.flat .lines article.line") + " >= 5")
        calm_in(page, "by title", {"#list section.flat .lines": 1, "lines": 5, "keys": 3, "titles": 5})
        # A served search's results: Oasis's two songs under their band, and Ultimate Guitar's Wonderwall.
        page.open(base)
        page.click("#q")
        page.type("oasis")
        assert page.wait(SHOWN % json.dumps("body.search-mode #results article.line") + " >= 2", timeout=20)
        calm_in(page, "a search", {"#results .groups": 1, "lines": 2, "results' titles": 2, "keys": 2, "bands": 1})
        # The lookup page's rows: your Wonderwall, and Ultimate Guitar's.
        page.open(base + "lookup")
        page.click("#q")
        page.type("wonder")
        assert page.wait(SHOWN % json.dumps("#results .rows article.row") + " >= 2", timeout=20)
        calm_in(page, "the lookup page", {".rows": 1, "lines": 2, "titles": 2, "keys": 1})


@pytest.mark.parametrize("size", [(390, 844), (1280, 900)], ids=["phone", "laptop"])
def test_caracole_serves_own_pages_have_the_same_four_radii(cfg, conn, live, tmp_path, size):  # noqa: F811
    """The pick, the removal, a message page, the lookup page with results and the Guitar Pro page (with alphaTab):
    no corner radius but the four. Their own radii come to the tokens (base.css's, which each page inlines first)."""
    import test_web_guitar_browser as guitar
    from helpers import browser
    from helpers.guitar import SYNTHETIC, alphatab_dir
    from helpers.targets import noted, noting
    from test_web_pages import pages

    from caracole.web.pages import page as message_page

    width, height = size
    static = dict(pages())
    static["message"] = message_page("Not found", "<p>No such song.</p>")
    # What each page must show, and how many, so that a page that drew nothing fails rather than passes unmeasured.
    drawn = {"pick": (".pick-form .choice, .pick-form .btn", 3), "remove": (".confirm .btn", 2),
             "message": ("header.top .navlink, .page > p", 2)}
    for name, html in static.items():
        selector, floor = drawn[name]
        script = noting("data-odd", odd_radii(())) + noting("data-shown", SHOWN % json.dumps(selector))
        path = tmp_path / f"{name}.html"
        path.write_text(html.replace("</body>", f"<script>{script}</script>\n</body>"), encoding="utf-8")
        dom = browser.dump_dom(path.as_uri(), size, mobile=width < 500)
        assert noted(dom, "data-shown") >= floor, (name, selector, noted(dom, "data-shown"))
        assert noted(dom, "data-odd") == [], name
    base, _ = live
    index_songs(cfg, [("soda-stereo", "de-musica-ligera", 2)])
    with driven(tmp_path, width) as page:
        page.open(base + "lookup")
        page.type("musica ligera")
        assert page.wait("document.querySelectorAll('#results .hit').length >= 1", timeout=20), page.js("document.body.innerText")
        assert page.js(odd_radii(())) == [], "the lookup page"
    if alphatab_dir() is None:
        pytest.skip("the Guitar Pro page needs alphaTab (CARACOLE_ALPHATAB_DIR)")
    server, _, url = guitar.serving(cfg, conn, SYNTHETIC.read_bytes())
    try:
        page = guitar.opened(tmp_path, url, width=width, height=height, mobile=width < 500)
        try:
            assert page.wait(guitar.RENDERED, 30)
            # alphaTab's own drawing inside the score is left out, caracole's container around it measured.
            assert page.js(odd_radii(("#score *",))) == [], "the Guitar Pro page"
        finally:
            page.close()
    finally:
        server.shutdown()
        server.server_close()
