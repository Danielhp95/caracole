"""The page caracole serve serves, in a real browser against a real server: requests answered on the page.

The queue runs a fake caracole (``FakeCaracole``) that does what the commands
would, with no request: ``add`` syncs wanted.txt into the database, ``fetch``
keeps a sheet once the page has asked twice how it goes (Chromium's virtual
clock runs the page's timers faster than the server's real one). The page gets
a test script after its own, allowed by its hash, that clicks or fills in the
forms and notes each line the page shows.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import shutil
import subprocess
import threading
from datetime import UTC, datetime

import pytest

from caracole import db
from caracole.library import song_dir
from caracole.overrides import override_key
from caracole.songs import find_song, update_song
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

from conftest import add_song

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
pytestmark = pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")


class Polls:
    """How many times the page asked /jobs.json; ``wait`` blocks until it asked ``n`` more times."""

    def __init__(self):
        self.count = 0
        self.changed = threading.Condition()

    def tick(self):
        with self.changed:
            self.count += 1
            self.changed.notify_all()

    def wait(self, n, timeout=10):
        with self.changed:
            target = self.count + n
            self.changed.wait_for(lambda: self.count >= target, timeout)


class FakeCaracole:
    """The job's commands, faked: ``add`` syncs wanted.txt, ``fetch`` keeps a sheet.pdf once the page has
    seen it run. A song in ``fail`` fails its fetch with that error, as the CLI says one.
    """

    def __init__(self, cfg, *, fail=None):
        self.cfg = cfg
        self.fail = fail or {}
        self.polls = Polls()

    def __call__(self, args, emit):
        from caracole.wanted import sync_wanted

        conn = db.connect(self.cfg.db_path)
        try:
            if args[0] == "add":
                sync_wanted(conn, self.cfg.wanted_file, datetime.now(UTC))
            elif args[0] == "fetch":
                display = args[-1].removeprefix("--song=")
                self.polls.wait(2)
                if display in self.fail:
                    emit(f"error: {self.fail[display]}")
                    return 1
                song = find_song(conn, override_key(display))
                folder = song_dir(self.cfg.library_dir, song)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / "sheet.pdf").write_bytes(b"%PDF-1.4")
                update_song(conn, song.id, status="found", ug_dirty=False)
            emit(f"ran {args[0]}")
            return 0
        finally:
            conn.close()


def sha(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


def with_script(page: str, script: str) -> str:
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', page).group(1)
    page = page.replace(csp, csp.replace("script-src ", f"script-src {sha(script)} "))
    return page.replace("</body>", f"<script>{script}</script>\n</body>")


@pytest.fixture
def serve(cfg, monkeypatch):
    """``serve(runner, script)``: the server on a free port, its page with ``script``; returns its address."""
    started = []

    def start(runner, script):
        import caracole.library_page as library_page

        real = library_page.build_library_page
        monkeypatch.setattr(library_page, "build_library_page", lambda *a, **k: with_script(real(*a, **k), script))
        queue = JobQueue(runner)
        app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok")
        answer = app.handle

        def handle(request):
            response = answer(request)
            if request.target.startswith("/jobs.json"):
                runner.polls.tick()
            return response

        app.handle = handle
        server = make_server(app, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        queue.start()
        started.append((server, queue))
        return f"http://127.0.0.1:{server.server_address[1]}/"

    yield start
    for server, queue in started:
        queue.stop()
        server.shutdown()
        server.server_close()


def dump_dom(url: str, tmp_path, size: str = "1280,900") -> str:
    try:
        result = subprocess.run(
            [CHROMIUM, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={tmp_path / 'chrome'}", f"--window-size={size}", "--hide-scrollbars",
             "--virtual-time-budget=60000", "--dump-dom", url],
            capture_output=True, text=True, timeout=90,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        pytest.skip(f"chromium couldn't run: {e}")
    if result.returncode != 0 or "<html" not in result.stdout:
        pytest.skip(f"chromium couldn't run: {result.stderr[-500:]}")
    return result.stdout


# Notes each line the page shows, in order, and how wide the page ever got.
WATCH = """
const seen = [];
const note = () => {
  for (const p of document.querySelectorAll(".progress")) {
    const text = p.textContent;
    if (!seen.includes(text)) seen.push(text);
  }
  document.body.setAttribute("data-seen", JSON.stringify(seen));
  const wide = Math.max(Number(document.body.getAttribute("data-wide") || 0), document.documentElement.scrollWidth);
  document.body.setAttribute("data-wide", String(wide));
  document.body.setAttribute("data-page", String(window.innerWidth));
};
new MutationObserver(note).observe(document.body, { subtree: true, childList: true, characterData: true });
const cardOf = (title, where) => Array.from(document.querySelectorAll((where || "#list") + " article"))
  .find((c) => c.querySelector("h2").textContent === title);
"""


def clicks(*titles: str) -> str:
    """The test script: Fetch now on each card titled so."""
    calls = "".join(f'cardOf({json.dumps(t)}).querySelector("form.fetch button").click();\n' for t in titles)
    return "(() => {\n" + WATCH + calls + "})();\n"


def requests_song(artist: str, title: str, *, extra: str = "") -> str:
    """The test script: the request form, filled in and sent; ``extra`` runs first."""
    return "(() => {\n" + WATCH + extra + f"""
const form = document.querySelector("form.request-form");
form.elements.namedItem("artist").value = {json.dumps(artist)};
form.elements.namedItem("title").value = {json.dumps(title)};
form.querySelector('button[type="submit"]').click();
""" + "})();\n"


def attribute(dom: str, name: str):
    found = re.search(rf'<body[^>]*\b{name}="([^"]*)"', dom)
    assert found, dom[-3000:]
    return json.loads(html.unescape(found.group(1)))


def card(dom: str, title: str) -> str:
    found = re.search(r"<article[^>]*>(?:(?!</article>).)*?<h2>" + re.escape(title) + r"</h2>.*?</article>", dom, re.S)
    assert found, dom[-3000:]
    return found.group(0)


def test_fetch_now_shows_its_progress_on_the_card_then_its_files(serve, cfg, conn, tmp_path):
    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep")
    add_song(conn, "Oasis", "Wonderwall")
    url = serve(FakeCaracole(cfg), clicks("Creep"))

    dom = dump_dom(url, tmp_path)

    assert '<main class="list" id="list">' in dom  # still the library: no other page
    seen = attribute(dom, "data-seen")
    assert "Fetching from Ultimate Guitar…" in seen, seen
    shown = card(dom, "Creep")
    line = re.search(r'<p class="progress"[^>]*>.*?</p>', shown, re.S).group(0)
    assert 'role="status"' in line and 'data-tone="ready"' in line  # read out as it changes
    assert "Ready" in line and 'href="Radiohead/Creep/sheet.pdf"' in line and "Open sheet" in line
    # Once done, the card shows what the library has now: the sheet, and no Fetch now.
    assert ">Sheet PDF</a>" in shown and 'action="/fetch"' not in shown
    assert 'data-status="found"' in shown
    assert 'action="/fetch"' in card(dom, "Wonderwall")  # the other card is as it was
    # The counts follow: one found song now, in the masthead and on the buttons.
    assert re.search(r'<li class="stat"><b>1</b> found</li>', dom)
    assert re.search(r'data-show="found"[^>]*>Found <span class="n">1</span>', dom)


# Notes whether each card's line is still the first node it showed one in (data-same, by where the card is
# and its title), and where the focus is, every 100 ms (data-focus).
FIRST_LINE_AND_FOCUS = """
const firsts = new Map();
const same = {};
new MutationObserver(() => {
  for (const p of document.querySelectorAll("article .progress")) {
    const card = p.closest("article");
    const where = (card.closest("#requested") ? "requested " : "list ") + card.querySelector("h2").textContent;
    if (!firsts.has(where)) firsts.set(where, p);
    same[where] = firsts.get(where) === p;
  }
  document.body.setAttribute("data-same", JSON.stringify(same));
}).observe(document.body, { subtree: true, childList: true, characterData: true });
setInterval(() => {
  const at = document.activeElement;
  const card = at && at.closest ? at.closest("article") : null;
  document.body.setAttribute("data-focus", JSON.stringify(
    [at ? at.tagName.toLowerCase() + "." + at.className : null, card ? card.querySelector("h2").textContent : null]));
}, 100);
"""


def test_a_cards_line_stays_the_same_live_region_until_its_request_ends(serve, cfg, conn, tmp_path):
    # A live region put in the page with its text in it isn't read out: the card's line must be the node
    # that was there all along, its text changed in place. And the focus, on Fetch now, isn't lost.
    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep")
    script = ("(() => {\n" + WATCH + FIRST_LINE_AND_FOCUS
              + 'const go = cardOf("Creep").querySelector("form.fetch button");\ngo.focus();\ngo.click();\n})();\n')
    url = serve(FakeCaracole(cfg), script)

    dom = dump_dom(url, tmp_path)

    shown = card(dom, "Creep")
    assert re.search(r'<p class="progress"[^>]*data-tone="ready"', shown) and shown.count('class="progress"') == 1
    assert ">Sheet PDF</a>" in shown  # the card is the song's new one all the same
    assert attribute(dom, "data-same") == {"list Creep": True}
    assert attribute(dom, "data-focus") == ["p.progress", "Creep"]


def test_a_requested_song_gets_a_card_of_its_own_on_the_page(serve, cfg, conn, tmp_path):
    add_song(conn, "Oasis", "Wonderwall")
    url = serve(FakeCaracole(cfg), requests_song("Radiohead", "Creep", extra=FIRST_LINE_AND_FOCUS))

    dom = dump_dom(url, tmp_path)

    requested = re.search(r'<section[^>]*id="requested"[^>]*>(.*?)</section>', dom, re.S)
    assert requested and "hidden" not in requested.group(0)[:80], dom[-3000:]
    shown = card(requested.group(1), "Creep")
    assert "Radiohead" in shown and "Ready" in shown and ">Sheet PDF</a>" in shown
    # Its line is the one "Sending…" was written in: a screen reader hears it change, to the end.
    assert shown.count('class="progress"') == 1 and attribute(dom, "data-same") == {"requested Creep": True}
    seen = attribute(dom, "data-seen")
    assert "Adding to the library…" in seen or "Queued…" in seen, seen
    assert "Radiohead - Creep" in cfg.wanted_file.read_text(encoding="utf-8")
    # The masthead counts it.
    assert re.search(r'<li class="stat"><b>2</b> songs</li><li class="stat"><b>1</b> found</li>', dom)
    # One song: no list of requests.
    assert re.search(r'<aside[^>]*id="tray"[^>]*hidden', dom)


def test_several_requests_show_as_one_short_list(serve, cfg, conn, tmp_path):
    for artist, title in (("Radiohead", "Creep"), ("Oasis", "Wonderwall"), ("Muse", "Hysteria")):
        song = add_song(conn, artist, title)
        update_song(conn, song.id, match_decision="accept", match_artist_key=artist.lower(),
                    match_song_key=title.lower())
    url = serve(FakeCaracole(cfg), clicks("Creep", "Wonderwall", "Hysteria"))

    dom = dump_dom(url, tmp_path)

    tray = re.search(r'<aside[^>]*id="tray"[^>]*>(.*?)</aside>', dom, re.S)
    assert tray and "hidden" not in tray.group(0)[:60], dom[-3000:]
    lines = re.findall(r'<li[^>]*><span class="tray-song">([^<]*)</span><p class="progress"[^>]*>(.*?)</p>',
                       tray.group(1), re.S)
    assert [name for name, _ in lines] == ["Muse - Hysteria", "Oasis - Wonderwall", "Radiohead - Creep"]
    assert all("Ready" in said for _, said in lines), lines
    assert "3 requests" in tray.group(1) and 'href="jobs"' in tray.group(1)
    # The lines in the list aren't read out a second time: the cards' are.
    assert 'role="status"' not in tray.group(1)


def test_a_failed_request_says_why_in_one_sentence_with_its_details(serve, cfg, conn, tmp_path):
    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep")
    runner = FakeCaracole(cfg, fail={"Radiohead - Creep": "UG answered 503 for Radiohead's page. It waits."})
    url = serve(runner, clicks("Creep"))

    dom = dump_dom(url, tmp_path)

    line = re.search(r'<p class="progress"[^>]*>.*?</p>', card(dom, "Creep"), re.S).group(0)
    assert 'data-tone="failed"' in line and "UG answered 503 for Radiohead's page." in line
    assert "It waits" not in line and 'href="jobs?job=1#job-1"' in line and "Details" in line
    assert 'action="/fetch"' in card(dom, "Creep")  # it can be asked for again


def test_a_refused_request_says_why_on_its_card(serve, cfg, conn, tmp_path):
    url = serve(FakeCaracole(cfg), requests_song("Simon - Garfunkel", "Mrs Robinson"))

    dom = dump_dom(url, tmp_path)

    shown = card(dom, "Mrs Robinson")
    assert 'data-tone="failed"' in shown and "caracole can't add this song" in shown
    assert not cfg.wanted_file.exists()


def test_the_progress_fits_a_phone(serve, cfg, conn, tmp_path):
    long = "Matador de la Noche Interminable que Nunca Termina en Buenos Aires"
    for artist, title in (("Radiohead", "Creep"), ("Los Fabulosos Cadillacs y la Orquesta de Todos", long)):
        song = add_song(conn, artist, title)
        update_song(conn, song.id, match_decision="accept", match_artist_key="x", match_song_key=title.lower())
    url = serve(FakeCaracole(cfg), clicks("Creep", long))

    dom = dump_dom(url, tmp_path, size="390,844")

    assert attribute(dom, "data-wide") <= attribute(dom, "data-page")  # nothing wider than the screen
    assert re.search(r'<aside[^>]*id="tray"(?![^>]*hidden)', dom)
