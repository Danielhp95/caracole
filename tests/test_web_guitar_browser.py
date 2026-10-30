"""caracole serve's Guitar Pro page in Chromium, with the real alphaTab (``CARACOLE_ALPHATAB_DIR``, which both dev
shells set) and the synthetic score (helpers/guitar.py): it opens on the guitar's track, breaks no rule of its
policy, loads nothing but alphaTab's bundle, lays the tracks out as buttons that show them and mute them one by one
(by mouse, keyboard or finger), draws the score's header in the page's text colour, dark or light, cuts no part of
the score at its top or its bottom, plays on a click or Space, and fits a phone with a compact bar; the library page's link
opens it.

The Guitar Pro 3, 5 and GPX files of real songs were checked by hand against a library of copies (alphaTab reads
them all); no real song's tab is a fixture in this public repository."""

import base64
import hashlib
import threading
from dataclasses import replace
from urllib.parse import quote, urlencode

import pytest
from helpers.browser import CHROMIUM_MARKS, Browser, BrowserError
from helpers.guitar import SYNTHETIC, SYNTHETIC_TEX, alphatab_dir, export_alphatex, keep_guitar

from caracole.web import alphatab
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

from conftest import add_song

pytestmark = CHROMIUM_MARKS

# Every policy violation and every request the page makes, noted from its first moment.
WATCH = """window.caracoleViolations = [];
document.addEventListener("securitypolicyviolation", (e) => window.caracoleViolations.push(
  e.effectiveDirective + " " + e.blockedURI + " " + (e.sample || "")), true);"""
RENDERED = "Number(document.documentElement.dataset.rendered) >= 1 && !!document.querySelector('#score canvas')"


@pytest.fixture
def served(cfg, conn):
    """caracole serve on a socket, with alphaTab and a song whose Guitar Pro file is the synthetic score; the address
    of its Guitar Pro page."""
    cfg = replace(cfg, alphatab_dir=alphatab_dir())
    song = add_song(conn, "caracole tests", "Synthetic Study")
    path = keep_guitar(conn, cfg, song, SYNTHETIC.read_bytes())
    app = WebApp(cfg, JobQueue(lambda args, emit: 0), allowed=allowed_hosts("127.0.0.1"), csrf="tok")
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"
    yield base, base + "guitar?" + urlencode({"file": path})
    server.shutdown()
    server.server_close()


def opened(tmp_path, url, **size):
    try:
        page = Browser(tmp_path / "chrome", **size)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    page.send("Network.enable")
    page.send("Page.addScriptToEvaluateOnNewDocument", source=WATCH)
    page.open(url)
    return page


def requests(page):
    return [e["params"]["request"]["url"] for e in page.events if e.get("method") == "Network.requestWillBeSent"]


def test_the_page_draws_the_guitar_s_track_within_its_policy_and_loads_the_bundle_alone(served, tmp_path):
    base, url = served
    page = opened(tmp_path, url)
    try:
        assert page.wait(RENDERED, 30), page.js("document.getElementById('gp-status').textContent")
        assert page.js("document.getElementById('gp-status').classList.contains('failed')") is False
        # The lead guitar, not the vocals before it, though a Guitar Pro 3 file writes them as a tab too.
        assert page.js("document.documentElement.dataset.track") == "1"
        assert page.js("window.caracoleGuitar.tracks.map((t) => t.name)") == ["Lead guitar"]
        assert page.wait("document.documentElement.dataset.player === 'ready'", 30)
        assert page.js("window.caracoleViolations") == []
        at = alphatab.load(alphatab_dir())
        # The page, the bundle by its address and the worker made from it: nothing else, from nowhere else.
        asked = [u for u in requests(page) if not u.startswith("data:")]
        assert asked[:2] == [url, base.rstrip("/") + at.href]
        assert all(u.startswith("blob:null/") for u in asked[2:]) and len(asked) <= 4, asked
        # The stylesheet alphaTab added for its font is the one the policy allows by its hash: an alphaTab whose
        # stylesheet differs fails here (web/alphatab.py's font_face).
        styles = page.js("[...document.querySelectorAll('style')].map((s) => s.textContent)")
        added = [s for s in styles if "@font-face" in s]
        assert len(added) == 1
        assert "'sha256-" + base64.b64encode(hashlib.sha256(added[0].encode()).digest()).decode() + "'" == at.font_face
        # Its own shared stylesheet it never added: the page's empty one stands in for it.
        assert page.js("!!document.getElementById('alphaTabStyleShared')") is False
    finally:
        page.close()


TRACKS = "[...document.querySelectorAll('#tracks .track')]"
VOCALS = "Vocals, the melody written as a tab"
SHOW = "#tracks .track:nth-child({n}) .show"
MUTE = "#tracks .track:nth-child({n}) .mute"
# Every call to changeTrackMute, noted: the tracks' indexes and whether muted.
SPY_MUTE = """(() => { const api = window.caracoleGuitar; const real = api.changeTrackMute.bind(api);
  window.mutes = []; api.changeTrackMute = (tracks, muted) => {
    window.mutes.push([tracks.map((t) => t.index), muted]); return real(tracks, muted); }; })()"""


def pressed(page, selector):
    return page.js(f"[...document.querySelectorAll({selector!r})].map((b) => b.getAttribute('aria-pressed'))")


def accessible_names(page, selector):
    """What a screen reader names each element ``selector`` finds."""
    root = page.send("DOM.getDocument")["root"]["nodeId"]
    names = []
    for node in page.send("DOM.querySelectorAll", nodeId=root, selector=selector)["nodeIds"]:
        tree = page.send("Accessibility.getPartialAXTree", nodeId=node, fetchRelatives=False)["nodes"]
        names.append(tree[0]["name"]["value"])
    return names


def test_the_tracks_are_laid_out_as_buttons_and_a_tap_shows_one(served, tmp_path):
    _, url = served
    page = opened(tmp_path, url)
    try:
        assert page.wait(RENDERED, 30)
        assert page.js("document.querySelector('#gp-bar select, #gp-bar details')") is None
        assert page.js("document.getElementById('tracks').hidden") is False
        # Each its name and its kind: its strings, the drums (which a track named so doesn't say twice), or no tab.
        assert page.js(f"{TRACKS}.map((t) => [...t.querySelector('.show').children].map((s) => s.textContent))") == [
            [VOCALS, "6 strings"], ["Lead guitar", "6 strings"], ["Bass", "4 strings"], ["Keys", "no tab"],
            ["Drums"]]
        assert accessible_names(page, "#tracks .show") == [
            VOCALS + ", 6 strings", "Lead guitar, 6 strings", "Bass, 4 strings", "Keys, no tab", "Drums"]
        # A name too long for its button is cut short, and whole in its title.
        assert page.js("[...document.querySelectorAll('#tracks .show')].map((b) => b.title)") == [
            VOCALS, "", "", "", ""]
        assert pressed(page, "#tracks .show") == ["false", "true", "false", "false", "false"]
        page.click(SHOW.format(n=3))
        assert page.wait("document.documentElement.dataset.track === '2'")
        assert page.wait("Number(document.documentElement.dataset.rendered) >= 2", 30)
        assert page.js("window.caracoleGuitar.tracks.map((t) => t.name)") == ["Bass"]
        assert pressed(page, "#tracks .show") == ["false", "false", "true", "false", "false"]
        # Shift (or Ctrl) and a tap adds a track to those shown, and takes it away again; the last one stays.
        for kind in ("mousePressed", "mouseReleased"):
            box = page.js(f"(() => {{ const r = document.querySelector({SHOW.format(n=2)!r})"
                          ".getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
            page.send("Input.dispatchMouseEvent", type=kind, x=box[0], y=box[1], button="left", clickCount=1,
                      modifiers=8)
        assert page.wait("document.documentElement.dataset.track === '1,2'")
        assert page.wait("Number(document.documentElement.dataset.rendered) >= 3", 30)
        assert page.js("window.caracoleGuitar.tracks.map((t) => t.name)") == ["Lead guitar", "Bass"]
        assert pressed(page, "#tracks .show") == ["false", "true", "true", "false", "false"]
        assert page.js("window.caracoleViolations") == []
    finally:
        page.close()


def test_each_track_mutes_on_its_own_whichever_is_shown(served, tmp_path):
    _, url = served
    page = opened(tmp_path, url)
    try:
        assert page.wait(RENDERED, 30)
        page.js(SPY_MUTE)
        labels = page.js(f"{TRACKS}.map((t) => t.querySelector('.mute').getAttribute('aria-label'))")
        assert labels == ["Mute " + VOCALS, "Mute Lead guitar", "Mute Bass", "Mute Keys", "Mute Drums"]
        assert pressed(page, "#tracks .mute") == ["false"] * 5
        page.click(MUTE.format(n=3))  # the bass, not shown
        assert page.wait("window.mutes.length === 1")
        assert page.js("window.mutes") == [[[2], True]]
        assert pressed(page, "#tracks .mute") == ["false", "false", "true", "false", "false"]
        assert page.js("window.caracoleGuitar.score.tracks.map((t) => t.playbackInfo.isMute)") == [
            False, False, True, False, False]
        assert page.js("document.querySelector('#tracks .track:nth-child(3)').classList.contains('muted')") is True
        assert page.js("document.documentElement.dataset.track") == "1"  # muting shows nothing else
        # Showing the bass keeps it muted, and the sound alphaTab loads again is told so.
        page.click(SHOW.format(n=3))
        assert page.wait("Number(document.documentElement.dataset.rendered) >= 2", 30)
        assert pressed(page, "#tracks .mute") == ["false", "false", "true", "false", "false"]
        assert page.js("window.caracoleGuitar.score.tracks[2].playbackInfo.isMute") is True
        assert all(call == [[2], True] for call in page.js("window.mutes"))
        # Unmuted again with a tap.
        page.click(MUTE.format(n=3))
        assert page.wait("window.mutes.at(-1)[1] === false")
        assert page.js("window.mutes.at(-1)") == [[2], False]
        assert pressed(page, "#tracks .mute") == ["false"] * 5
    finally:
        page.close()


def test_the_tracks_work_from_the_keyboard(served, tmp_path):
    _, url = served
    page = opened(tmp_path, url)
    try:
        assert page.wait(RENDERED, 30)
        page.js(SPY_MUTE)
        page.js(f"document.querySelector({SHOW.format(n=3)!r}).focus()")
        page.press("Enter")
        assert page.wait("document.documentElement.dataset.track === '2'")
        page.js(f"document.querySelector({MUTE.format(n=2)!r}).focus()")
        page.press("Enter")
        assert page.wait("window.mutes.length === 1")
        assert pressed(page, "#tracks .mute") == ["false", "true", "false", "false", "false"]
        # Every track's buttons are in the order Tab goes through.
        assert page.js("[...document.querySelectorAll('#tracks button')].every((b) => b.tabIndex === 0)") is True
    finally:
        page.close()


def finger(page, selector, kind):
    """A finger on the element ``selector`` finds, brought into the row's view: put down (``touchStart``) or lifted
    (``touchEnd``)."""
    box = page.js(f"(() => {{ const e = document.querySelector({selector!r}); "
                  "e.scrollIntoView({block: 'nearest', inline: 'center'}); const r = e.getBoundingClientRect(); "
                  "return [r.x + r.width / 2, r.y + r.height / 2]; })()")
    page.send("Input.dispatchTouchEvent", type=kind, touchPoints=[{"x": box[0], "y": box[1]}] if kind == "touchStart"
              else [])


FRAMES = "new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(() => done(true))))"


def test_a_long_press_shows_a_track_beside_those_shown_on_a_touch_screen(served, tmp_path):
    _, url = served
    page = opened(tmp_path, url, width=390, height=844, mobile=True)
    try:
        assert page.wait(RENDERED, 30)
        # Held, the bass is shown beside the guitar, at once, the finger still down; let go, nothing more.
        finger(page, SHOW.format(n=3), "touchStart")
        assert page.wait("document.documentElement.dataset.track === '1,2'", 5)
        finger(page, SHOW.format(n=3), "touchEnd")
        assert page.js(FRAMES)
        assert page.js("document.documentElement.dataset.track") == "1,2"
        assert pressed(page, "#tracks .show") == ["false", "true", "true", "false", "false"]
        assert page.wait("Number(document.documentElement.dataset.rendered) >= 2", 30)
        assert page.js("window.caracoleGuitar.tracks.map((t) => t.name)") == ["Lead guitar", "Bass"]
        # Held again, taken away.
        finger(page, SHOW.format(n=2), "touchStart")
        assert page.wait("document.documentElement.dataset.track === '2'", 5)
        finger(page, SHOW.format(n=2), "touchEnd")
        assert page.js(FRAMES)
        assert page.js("document.documentElement.dataset.track") == "2"
        # A tap shows a track alone, as a click does.
        finger(page, SHOW.format(n=4), "touchStart")
        finger(page, SHOW.format(n=4), "touchEnd")
        assert page.wait("document.documentElement.dataset.track === '3'", 5)
        assert page.js("window.caracoleViolations") == []
    finally:
        page.close()


SCHEME = """(() => { const c = [...document.querySelectorAll('#score canvas')]
  .sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top)[0];
  const { data, width } = c.getContext('2d').getImageData(0, 0, c.width, c.height);
  const counts = {}; let top = null;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 255) continue;
    const key = data[i] + ',' + data[i + 1] + ',' + data[i + 2];
    counts[key] = (counts[key] || 0) + 1;
    if (top === null) top = Math.floor(i / 4 / width);
  }
  const surface = getComputedStyle(document.documentElement).getPropertyValue('--surface').trim();
  return { counts, top, ratio: window.devicePixelRatio, surface }; })()"""


def luminance(rgb):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def header_text(page):
    """The colour most of the score's header (the title, the artist) is drawn in, the page's surface under it, and
    the first row of the header's canvas that has ink."""
    seen = page.js(SCHEME)
    assert seen["counts"], "the header canvas has no ink"
    colour = max(seen["counts"], key=seen["counts"].get)
    surface = seen["surface"].lstrip("#")
    return (tuple(int(c) for c in colour.split(",")), tuple(int(surface[i:i + 2], 16) for i in (0, 2, 4)),
            seen["top"])


def test_the_score_s_header_is_drawn_in_the_page_s_text_colour_dark_or_light(served, tmp_path):
    _, url = served
    page = opened(tmp_path, url)
    try:
        page.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
        page.open(url)
        assert page.wait(RENDERED, 30)
        # Drawn again in the same colours, as a track's tap, the switch or a turned phone draw it: alphaTab's canvas
        # then started the header in the colour the last drawing ended in, which a fresh canvas hadn't got (black).
        page.js("window.caracoleGuitar.render()")
        assert page.wait("Number(document.documentElement.dataset.rendered) >= 2", 30)
        text, surface, top = header_text(page)
        assert luminance(text) > luminance(surface), (text, surface)  # light on dark
        assert contrast(text, surface) >= 4.5, (text, surface)
        assert top >= 4, top  # the title's first line isn't cut at the top
        page.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "light"}])
        assert page.wait("Number(document.documentElement.dataset.rendered) >= 3", 30)
        page.js("window.caracoleGuitar.render()")
        assert page.wait("Number(document.documentElement.dataset.rendered) >= 4", 30)
        text, surface, _ = header_text(page)
        assert luminance(text) < luminance(surface)  # dark on light
        assert contrast(text, surface) >= 4.5, (text, surface)
    finally:
        page.close()


# Each canvas of the score: its height in rows and the first and the last row it has ink on (-1: none).
INK_ROWS = """[...document.querySelectorAll('#score canvas')].map((c) => {
  const { data, width, height } = c.getContext('2d').getImageData(0, 0, c.width, c.height);
  let first = -1, last = -1;
  for (let i = 3; i < data.length; i += 4) if (data[i]) { const row = Math.floor(i / 4 / width);
    if (first < 0) first = row; last = row; }
  return [height, first, last]; })"""


@pytest.mark.parametrize("size", [{"width": 390, "height": 844, "mobile": True}, {"width": 1280, "height": 800}],
                         ids=["phone", "wide"])
def test_no_part_of_the_score_is_cut_at_its_top_or_its_bottom(served, tmp_path, size):
    """alphaTab draws each part of the score (the header, the tuning's box, each line of bars, its name at the
    foot) on a canvas of its own: nothing it draws reaches the first or the last row of its canvas, where it would
    be cut, as the lead guitar's dropped D was ("Guitar Dropped D Tuning" over the circled strings, which lost
    their bottoms), or a title's tops."""
    _, url = served
    page = opened(tmp_path, url, **size)
    try:
        assert page.wait(RENDERED, 30)
        assert page.js("window.caracoleGuitar.tracks[0].staves[0].stringTuning.name") == "Guitar Dropped D Tuning"
        parts = page.js(INK_ROWS)
        assert len(parts) >= 3, parts  # the header, the tuning's box, the bars
        for height, first, last in parts:
            assert first == -1 or (first > 0 and last < height - 1), parts
        # And drawn again (a track's tap, the switch, a turned phone).
        page.js("window.caracoleGuitar.render()")
        assert page.wait("Number(document.documentElement.dataset.rendered) >= 2", 30)
        for height, first, last in page.js(INK_ROWS):
            assert first == -1 or (first > 0 and last < height - 1)
    finally:
        page.close()


def test_play_starts_on_a_click_and_stop_stops(served, tmp_path):
    _, url = served
    page = opened(tmp_path, url)
    try:
        assert page.wait("document.documentElement.dataset.player === 'ready' && !document.getElementById('play')"
                         ".disabled", 30)
        page.click("#play")
        assert page.wait("document.documentElement.dataset.player === 'playing'", 15)
        assert page.wait("window.caracoleGuitar.timePosition > 0", 15)
        assert page.js("document.getElementById('play').textContent") == "Pause"
        page.click("#stop")
        assert page.wait("document.documentElement.dataset.player === 'paused'", 15)
        assert page.js("window.caracoleViolations") == []
        # The tempo: 50 to 125 %, alphaTab's playbackSpeed.
        page.js("(() => { const t = document.getElementById('tempo'); t.value = '75';"
                " t.dispatchEvent(new Event('input')); })()")
        assert page.js("window.caracoleGuitar.playbackSpeed") == 0.75
        assert page.js("document.getElementById('tempo-now').textContent") == "75%"
    finally:
        page.close()


# Every playPause the page asks of alphaTab, counted.
SPY_PLAY = """(() => { const api = window.caracoleGuitar; const real = api.playPause.bind(api);
  window.toggles = 0; api.playPause = () => { window.toggles += 1; return real(); }; })()"""
PLAYER = "document.documentElement.dataset.player === '{state}'"


def test_space_plays_and_pauses_wherever_the_focus_is(served, tmp_path):
    _, url = served
    page = opened(tmp_path, url)
    try:
        assert page.wait(PLAYER.format(state="ready") + " && !document.getElementById('play').disabled", 30)
        page.js(SPY_PLAY)
        page.press(" ")
        assert page.wait(PLAYER.format(state="playing"), 15)
        page.press(" ")
        assert page.wait(PLAYER.format(state="paused"), 15)
        assert page.js("window.toggles") == 2
        # On a track's button Space plays, and shows no other track; on Play itself, it plays once, not twice.
        page.js(f"document.querySelector({SHOW.format(n=3)!r}).focus()")
        page.press(" ")
        assert page.wait(PLAYER.format(state="playing"), 15)
        assert page.js("document.documentElement.dataset.track") == "1"
        page.js("document.getElementById('play').focus()")
        page.press(" ")
        assert page.wait(PLAYER.format(state="paused"), 15)
        assert page.js("window.toggles") == 4
        # With Alt, Ctrl, Meta or Shift held, Space is left to the browser and the desktop (which, on a button,
        # presses it: so with no button focused here).
        page.js("document.activeElement.blur()")
        for modifiers in (1, 2, 4, 8):
            page.press(" ", modifiers=modifiers)
        assert page.js("window.toggles") == 4
        assert page.js("window.caracoleViolations") == []
    finally:
        page.close()


def test_a_phone_gets_the_tab_alone_with_no_sideways_scroll(served, tmp_path):
    _, url = served
    page = opened(tmp_path, url, width=390, height=844, mobile=True)
    try:
        assert page.wait(RENDERED, 30)
        assert page.js("document.querySelector('input[name=view]:checked').value") == "tab"
        assert page.js("window.caracoleGuitar.settings.display.staveProfile") == page.js("alphaTab.StaveProfile.Tab")
        assert page.js("window.caracoleGuitar.settings.display.scale") == 0.8
        assert page.js("document.documentElement.scrollWidth <= document.documentElement.clientWidth") is True
        # Every control a thumb's target.
        small = page.js("[...document.querySelectorAll('#gp-bar button, #gp-bar .view label,"
                        " #gp-bar input[type=range], .links a')].map((e) => e.getBoundingClientRect())"
                        ".filter((r) => r.height < 44 || r.width < 44).length")
        assert small == 0
        # The bar is compact: Play, Stop, the tempo and the switch on one row, the tracks on one more, which
        # scrolls sideways itself when they don't fit.
        bar = page.js("document.getElementById('gp-bar').getBoundingClientRect().height")
        assert bar <= 0.15 * 844, bar
        assert page.js("getComputedStyle(document.getElementById('tracks')).overflowX") == "auto"
        # The track it opens on, the second, is in that row's view, whole, off its edge.
        assert page.js("document.documentElement.dataset.track") == "1"
        chip = page.js("(() => { const r = document.querySelector('#tracks .track:nth-child(2)')"
                       ".getBoundingClientRect(); return [r.left, r.right]; })()")
        assert chip[0] >= 16 and chip[1] <= 390 - 15, chip
        assert page.js("document.getElementById('tracks').scrollLeft") > 0
        assert page.js("scrollY") == 0
        middles = page.js("[...document.querySelectorAll('#gp-bar .gp-play > *')]"
                          ".map((e) => { const r = e.getBoundingClientRect(); return r.top + r.height / 2; })")
        assert len(middles) == 4 and max(middles) - min(middles) < 4, middles
        # Score and tab, when asked for.
        page.click(".view label:nth-of-type(2)")
        assert page.wait("window.caracoleGuitar.settings.display.staveProfile === alphaTab.StaveProfile.Default")
        assert page.wait("Number(document.documentElement.dataset.rendered) >= 2", 30)
        assert page.js("document.documentElement.scrollWidth <= document.documentElement.clientWidth") is True
    finally:
        page.close()


def test_a_wide_screen_starts_with_the_score_and_the_tab(served, tmp_path):
    _, url = served
    page = opened(tmp_path, url, width=1280, height=800)
    try:
        assert page.wait(RENDERED, 30)
        assert page.js("document.querySelector('input[name=view]:checked').value") == "score"
        assert page.js("window.caracoleGuitar.settings.display.scale") == 1
    finally:
        page.close()


def test_the_served_library_page_opens_it(served, tmp_path):
    base, url = served
    page = opened(tmp_path, base)
    try:
        assert page.wait("!!document.querySelector('.line-more')", 15)
        page.click(".line-more")
        opener = "document.querySelector('.tile-guitar a.tile-open')"  # the card's Guitar Pro tile
        assert page.wait(f"!!{opener}")
        assert page.js(f"{opener}.href") == url
        assert page.js("[...document.querySelectorAll('.tile-guitar a.dl')].some((a) => "
                       "a.getAttribute('href').endsWith('guitar-1.gp'))")
        page.js(f"{opener}.click()")
        assert page.wait("location.pathname === '/guitar'", 15)
        assert page.wait(RENDERED, 30)
    finally:
        page.close()


def test_the_served_sheet_viewer_offers_the_guitar_pro_tab_in_its_settings(cfg, conn, tmp_path):
    from helpers.rendered import fake_chordpro, rendered_song

    from caracole.overrides import Overrides
    from caracole.render import render_all

    cfg = replace(cfg, alphatab_dir=alphatab_dir())
    song = rendered_song(conn, cfg)
    path = keep_guitar(conn, cfg, song, SYNTHETIC.read_bytes(), name="guitar-1.gp5")
    render_all(conn, cfg, Overrides(), runner=fake_chordpro)
    app = WebApp(cfg, JobQueue(lambda args, emit: 0), allowed=allowed_hosts("127.0.0.1"), csrf="tok")
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"
    page = opened(tmp_path, base + "Soda%20Stereo/De%20M%C3%BAsica%20Ligera/sheet.html")
    try:
        page.click("#more")
        assert page.wait("!document.getElementById('guitar-row').hidden")
        link = "document.querySelector('#guitar-links a')"
        assert page.js(f"{link}.querySelector('.goto-lab').textContent") == "Guitar Pro tab"
        assert page.js(f"{link}.querySelector('.goto-v').textContent") == "in the browser"
        assert page.js(f"{link}.href") == base + "guitar?file=" + quote(path, safe="")
        page.js(f"{link}.click()")
        assert page.wait("location.pathname === '/guitar'", 15)
        assert page.wait(RENDERED, 30)
        assert page.js("window.caracoleViolations") == []
    finally:
        page.close()
        server.shutdown()
        server.server_close()


def test_the_fixture_is_what_alphatab_makes_of_its_alphatex(tmp_path):
    try:
        page = Browser(tmp_path / "chrome")
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    try:
        assert export_alphatex(page, SYNTHETIC_TEX.read_text(encoding="utf-8")) == SYNTHETIC.read_bytes()
    finally:
        page.close()
