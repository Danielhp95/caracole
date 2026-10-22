"""caracole serve's Guitar Pro page in Chromium, with the real alphaTab (``CARACOLE_ALPHATAB_DIR``, which both dev
shells set) and the synthetic score (helpers/guitar.py): it draws a track, breaks no rule of its policy, loads
nothing but alphaTab's bundle, switches tracks, plays on a click, and fits a phone; the library page's link opens it.

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


def test_the_page_draws_the_first_track_within_its_policy_and_loads_the_bundle_alone(served, tmp_path):
    base, url = served
    page = opened(tmp_path, url)
    try:
        assert page.wait(RENDERED, 30), page.js("document.getElementById('gp-status').textContent")
        assert page.js("document.getElementById('gp-status').classList.contains('failed')") is False
        assert page.js("document.documentElement.dataset.track") == "0"
        assert page.js("document.getElementById('track-name').textContent") == "Lead guitar"
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


def test_the_track_picker_switches_tracks(served, tmp_path):
    _, url = served
    page = opened(tmp_path, url)
    try:
        assert page.wait(RENDERED, 30)
        assert page.js("document.getElementById('tracks').hidden") is False
        page.click("#tracks > summary")
        assert page.wait("document.getElementById('tracks').open")
        labels = page.js("[...document.querySelectorAll('#track-list label')].map((l) => l.textContent)")
        assert labels == ["Lead guitar6 strings", "Bass4 strings"]
        page.click("#track-list label:nth-of-type(2)")
        assert page.wait("document.documentElement.dataset.track === '1'")
        assert page.wait("Number(document.documentElement.dataset.rendered) >= 2", 30)
        assert page.js("document.getElementById('track-name').textContent") == "Bass"
        assert page.js("document.getElementById('tracks').open") is False
        assert page.js("window.caracoleGuitar.tracks.map((t) => t.name)") == ["Bass"]
        assert page.js("window.caracoleViolations") == []
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
        small = page.js("[...document.querySelectorAll('#gp-bar button, #gp-bar summary, #gp-bar .view label,"
                        " #gp-bar input[type=range], .links a')].map((e) => e.getBoundingClientRect())"
                        ".filter((r) => r.height < 44 || r.width < 44).length")
        assert small == 0
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
        opener = "[...document.querySelectorAll('a')].find((a) => a.textContent === 'Open in the browser')"
        assert page.wait(f"!!{opener}")
        assert page.js(f"{opener}.href") == url
        assert page.js("[...document.querySelectorAll('a')].some((a) => a.textContent === 'Download' && "
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
        assert page.js(f"{link}.textContent") == "Guitar Pro tab"
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
