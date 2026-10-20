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
import threading
from datetime import UTC, datetime

import pytest
from helpers import browser
from helpers.browser import CHROMIUM_MARKS

from caracole import db
from caracole.library import song_dir
from caracole.overrides import override_key
from caracole.songs import find_song, update_song
from caracole.web.app import Request, Response, WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

from conftest import add_song

pytestmark = CHROMIUM_MARKS  # every test here opens the page in Chromium


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
    seen it run, ``review --pick`` settles the song's match on the candidate picked once the page has asked
    once. A lookup's ``get`` (Fetch it now, Fetch now) does what add and fetch do, its stages reported as
    ``caracole get --progress`` reports them. A song in ``fail`` fails its fetch with that error, as the CLI
    says one. With ``slow_add``, ``add`` (and a lookup's song stage) too waits for the page to ask twice; the
    next ``down`` times the page asks, the server answers 503.
    """

    def __init__(self, cfg, *, fail=None, slow_add=False, down=0):
        self.cfg = cfg
        self.fail = fail or {}
        self.slow_add = slow_add
        self.down = down
        self.polls = Polls()

    def __call__(self, args, emit):
        from caracole.wanted import sync_wanted

        conn = db.connect(self.cfg.db_path)
        try:
            if args[0] == "get":
                return self._get(conn, args, emit)
            if args[0] == "add":
                if self.slow_add:
                    self.polls.wait(2, timeout=30)
                sync_wanted(conn, self.cfg.wanted_file, datetime.now(UTC))
            elif args[0] == "review":
                said = dict(arg.removeprefix("--").split("=", 1) for arg in args[1:] if "=" in arg)
                self.polls.wait(1)
                artist_key, song_key = said["pick"].split("/")
                song = find_song(conn, override_key(said["song"]))
                update_song(conn, song.id, match_decision="accept", review=False, match_artist_key=artist_key,
                            match_song_key=song_key)
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


    def _get(self, conn, args, emit):
        from caracole.get import PROGRESS_PREFIX
        from caracole.wanted import sync_wanted

        def stage(name, state, detail=""):
            emit(PROGRESS_PREFIX + json.dumps({"stage": name, "state": state, "detail": detail}))

        display = f"{args[-2]} - {args[-1]}"
        stage("song", "running")
        if self.slow_add:
            self.polls.wait(2, timeout=30)
        sync_wanted(conn, self.cfg.wanted_file, datetime.now(UTC))
        stage("song", "done", "in the library")
        stage("sheet", "running")
        self.polls.wait(2)
        if display in self.fail:
            emit(f"error: {self.fail[display]}")
            return 1
        song = find_song(conn, override_key(display))
        folder = song_dir(self.cfg.library_dir, song)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "sheet.pdf").write_bytes(b"%PDF-1.4")
        update_song(conn, song.id, status="found", ug_dirty=False)
        stage("sheet", "done", "tab 1 from Ultimate Guitar")
        emit("ran get")
        return 0


def sha(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


def with_script(page: str, script: str) -> str:
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', page).group(1)
    page = page.replace(csp, csp.replace("script-src ", f"script-src {sha(script)} "))
    return page.replace("</body>", f"<script>{script}</script>\n</body>")


@pytest.fixture
def serve(cfg, monkeypatch):
    """``serve(runner, script)``: the server on a free port, its page with ``script``; returns its address.
    ``before(app)`` runs before the queue starts."""
    started = []

    def start(runner, script, *, before=None):
        import caracole.library_page as library_page

        real = library_page.build_library_page
        monkeypatch.setattr(library_page, "build_library_page", lambda *a, **k: with_script(real(*a, **k), script))
        queue = JobQueue(runner)
        app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok")
        answer = app.handle

        def handle(request):
            if request.target.startswith("/jobs.json") and runner.down > 0:
                runner.down -= 1
                response = app.finish(Response(503, json.dumps({"error": "The database can't be read: locked."})
                                               .encode(), [("Content-Type", "application/json; charset=utf-8")]))
            else:
                response = answer(request)
            if request.target.startswith("/jobs.json"):
                runner.polls.tick()
            return response

        app.handle = handle
        if before is not None:
            before(app)
        server = make_server(app, "127.0.0.1", 0)
        # shutdown() returns at the next poll: every 10 ms, not every 500
        threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
        queue.start()
        started.append((server, queue))
        return f"http://127.0.0.1:{server.server_address[1]}/"

    yield start
    for server, queue in started:
        queue.stop()
        server.shutdown()
        server.server_close()


def dump_dom(url: str, tmp_path, size: str = "1280,900") -> str:
    """The page's DOM once its timers ran for a minute of virtual time, in a browser context of its
    own (helpers/browser.py); a phone's width is laid out as a phone's screen (test_library_page.py)."""
    width, height = (int(n) for n in size.split(","))
    return browser.dump_dom(url, (width, height), hide_scrollbars=True, mobile=width < 500, budget_ms=60000)


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


def clicks_in_turn(*titles: str) -> str:
    """The test script: Fetch now on each card titled so, each once the server has answered the one before
    (its card's button gone), so that the server takes them in that order: requests sent together are
    taken in whatever order its threads get to them."""
    return "(() => {\n" + WATCH + f"""
const titles = {json.dumps(list(titles))};
const next = () => {{
  const title = titles.shift();
  if (title === undefined) return;
  cardOf(title).querySelector("form.fetch button").click();
  const answered = () => cardOf(title).querySelector("form.fetch") ? setTimeout(answered, 10) : next();
  answered();
}};
next();
""" + "})();\n"


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
    assert ">Open PDF</a>" in shown and 'action="/fetch"' not in shown
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
    assert ">Open PDF</a>" in shown  # the card is the song's new one all the same
    assert attribute(dom, "data-same") == {"list Creep": True}
    assert attribute(dom, "data-focus") == ["p.progress", "Creep"]


def test_a_requested_song_gets_a_card_of_its_own_on_the_page(serve, cfg, conn, tmp_path):
    add_song(conn, "Oasis", "Wonderwall")
    url = serve(FakeCaracole(cfg), requests_song("Radiohead", "Creep", extra=FIRST_LINE_AND_FOCUS))

    dom = dump_dom(url, tmp_path)

    requested = re.search(r'<section[^>]*id="requested"[^>]*>(.*?)</section>', dom, re.S)
    assert requested and "hidden" not in requested.group(0)[:80], dom[-3000:]
    shown = card(requested.group(1), "Creep")
    assert "Radiohead" in shown and "Ready" in shown and ">Open PDF</a>" in shown
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
    url = serve(FakeCaracole(cfg), clicks_in_turn("Creep", "Wonderwall", "Hysteria"))

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
    # On a desktop the list is open.
    assert 'aria-expanded="true"' in tray.group(1) and not re.search(r'<ol[^>]*id="tray-list"[^>]*hidden', dom)


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
    # Folded: only its one line shows ("2 requests · all done"), over cards that say the same.
    assert re.search(r'<button[^>]*id="tray-toggle"[^>]*aria-expanded="false"', dom)
    assert re.search(r'<ol[^>]*id="tray-list"[^>]*hidden', dom)


def test_a_new_songs_request_shows_after_a_reload(serve, cfg, conn, tmp_path):
    # Asked for before the page loaded, and still on its way: the library has no card for it yet.
    def request(app):
        sent = {"host": "127.0.0.1", "content-type": "application/x-www-form-urlencoded",
                "sec-fetch-site": "same-origin"}
        body = b"csrf=tok&artist=Radiohead&title=Creep&fetch=1"
        assert app.handle(Request("POST", "/request", sent, body)).status == 303

    url = serve(FakeCaracole(cfg, slow_add=True), "(() => {\n" + WATCH + "})();\n", before=request)

    dom = dump_dom(url, tmp_path)

    requested = re.search(r'<section[^>]*id="requested"[^>]*>(.*?)</section>', dom, re.S)
    assert requested and "hidden" not in requested.group(0)[:80], dom[-3000:]
    shown = card(requested.group(1), "Creep")
    assert "Radiohead" in shown and "Ready" in shown and ">Open PDF</a>" in shown
    assert "Adding to the library…" in attribute(dom, "data-seen")


def test_a_server_that_doesnt_answer_says_so_on_the_card_then_goes_on(serve, cfg, conn, tmp_path):
    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep")
    url = serve(FakeCaracole(cfg, down=3), clicks("Creep"))

    dom = dump_dom(url, tmp_path)

    seen = attribute(dom, "data-seen")
    assert "The database can't be read: locked. Trying again…" in seen, seen
    line = re.search(r'<p class="progress"[^>]*>.*?</p>', card(dom, "Creep"), re.S).group(0)
    assert 'data-tone="ready"' in line and "Trying again" not in line


ASKS_THREE_TIMES = """
const form = document.querySelector("form.request-form");
const ask = (artist, title) => {
  form.elements.namedItem("artist").value = artist;
  form.elements.namedItem("title").value = title;
  form.querySelector('button[type="submit"]').click();
};
const once = (test, then) => {
  const timer = setInterval(() => {
    if (test()) {
      clearInterval(timer);
      then();
    }
  }, 50);
};
const tones = () => Array.from(document.querySelectorAll("#requested .progress")).map((p) => p.dataset.tone);
ask("Simon - Garfunkel", "Mrs Robinson");
once(() => tones().includes("failed"), () => {
  ask("Simon & Garfunkel", "Mrs Robinson");
  once(() => tones().includes("ready"), () => {
    document.body.setAttribute("data-cards", String(document.querySelectorAll("#requested article").length));
    ask("Simon & Garfunkel", "Mrs Robinson");
    once(() => document.body.hasAttribute("data-cards") && tones().includes("queued"), () => {
      document.body.setAttribute("data-again", JSON.stringify(tones()));
    });
  });
});
"""


def test_asking_again_shows_on_the_same_card(serve, cfg, conn, tmp_path):
    # Refused first ("Simon - Garfunkel" can't be an artist), then asked for right, then asked for again once
    # done: one card, the song's.
    url = serve(FakeCaracole(cfg), "(() => {\n" + WATCH + ASKS_THREE_TIMES + "})();\n")

    dom = dump_dom(url, tmp_path)

    requested = re.search(r'<section[^>]*id="requested"[^>]*>(.*?)</section>', dom, re.S).group(1)
    assert attribute(dom, "data-cards") == 1  # the refused request's card went at the next request
    assert attribute(dom, "data-again") == ["queued"]  # asked again: the same card says so
    assert len(re.findall(r"<article", requested)) == 1, requested
    assert "Simon &amp; Garfunkel" in requested and 'data-tone="ready"' in requested


# --- the picker on a card ---------------------------------------------------------------------------

CANDIDATES = [{"artist_key": "radiohead", "song_key": "creep", "score": 88, "step": "fuzzy"},
              {"artist_key": "radiohead", "song_key": "creep-acoustic", "score": 86, "step": "fuzzy"}]


def in_review(conn):
    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="review", match_candidates=CANDIDATES, review=True)
    return creep


def picks(title: str, ref: str) -> str:
    """The test script: on the card titled so, the picker opened, the candidate ``ref`` chosen, and Pick; it
    notes (data-both) if the card ever offered a pick while its line said how the request goes."""
    return "(() => {\n" + WATCH + f"""
new MutationObserver(() => {{
  const c = cardOf({json.dumps(title)});
  const p = c && c.querySelector(".progress");
  if (p && /Queued|Writing|Fetching/.test(p.textContent) && c.querySelector("form.pick-form")) {{
    document.body.setAttribute("data-both", "1");
  }}
}}).observe(document.body, {{ subtree: true, childList: true, characterData: true }});
const card = cardOf({json.dumps(title)});
card.querySelector("details.picker").open = true;
card.querySelector('input[name="pick"][value={json.dumps(ref)}]').checked = true;
card.querySelector("form.pick-form button[type=submit]").click();
""" + "})();\n"


def test_a_pick_on_a_card_shows_how_it_goes_there_then_the_sheet(serve, cfg, conn, tmp_path):
    # As Fetch now: the page stays where it is, the picker gives way to the card's line, and the card is drawn
    # again once the request is over, from what the library has then.
    in_review(conn)
    url = serve(FakeCaracole(cfg), picks("Creep", "radiohead/creep"))

    dom = dump_dom(url, tmp_path)

    assert '<main class="list" id="list">' in dom  # still the library: no other page
    seen = attribute(dom, "data-seen")
    assert "Writing the answer to overrides.toml…" in seen and "Fetching from Ultimate Guitar…" in seen, seen
    shown = card(dom, "Creep")
    line = re.search(r'<p class="progress"[^>]*>.*?</p>', shown, re.S).group(0)
    assert 'data-tone="ready"' in line and "Open sheet" in line
    assert ">Open PDF</a>" in shown and 'class="picker"' not in shown and "Needs review" not in shown
    assert not re.search(r"<body[^>]*data-both", dom)  # no second pick while the first one ran


# Clicks the "Pick the match" of Creep's line once it shows, then notes where the page is, whether the
# card's picker is open, and which candidate has the focus.
FOLLOWS_THE_LINE = """
const timer = setInterval(() => {
  const go = Array.from(cardOf("Creep").querySelectorAll(".progress a")).find((a) => a.textContent === "Pick the match");
  if (!go) return;
  clearInterval(timer);
  go.click();
  setTimeout(() => {
    const at = document.activeElement;
    document.body.setAttribute("data-after", JSON.stringify({
      path: location.pathname, href: go.getAttribute("href"),
      open: cardOf("Creep").querySelector("details.picker").open,
      focus: at && at.name === "pick" ? at.value : null,
    }));
  }, 300);
}, 50);
"""


def test_a_request_that_ends_in_a_review_offers_its_picker_on_the_card(serve, cfg, conn, tmp_path):
    # Its fetch refused the song as needing review: the card's line says Needs review, and its link opens the
    # card's own picker, here, rather than its page.
    creep = in_review(conn)

    def fetch_it(app):
        from caracole.web.jobs import fetch_steps

        app.queue.submit("Fetch Radiohead - Creep", creep.key, fetch_steps(creep.display), fetching=True,
                         display=creep.display)

    error = '"Radiohead - Creep" needs review first: run `caracole review`.'
    url = serve(FakeCaracole(cfg, fail={"Radiohead - Creep": error}), "(() => {\n" + WATCH + FOLLOWS_THE_LINE
                + "})();\n", before=fetch_it)

    dom = dump_dom(url, tmp_path)

    shown = card(dom, "Creep")
    line = re.search(r'<p class="progress"[^>]*>.*?</p>', shown, re.S).group(0)
    assert 'data-tone="review"' in line and "Needs review" in line and "needs review first" not in line
    assert attribute(dom, "data-after") == {"path": "/", "href": f"review?song={creep.id}", "open": True,
                                            "focus": "radiohead/creep"}
    assert 'action="/review"' in shown and 'action="/fetch"' not in shown


def test_a_requests_picker_on_the_requests_page_takes_the_requests_whole_width(serve, cfg, conn, tmp_path):
    # A request is a line with its Output folded beside it; the picker under it spans the whole request, not
    # the line's column alone.
    from helpers.chromium import Chromium

    from caracole.web.jobs import fetch_steps

    creep = in_review(conn)

    def refuses(args, emit):
        if args[0] == "fetch":
            emit('error: "Radiohead - Creep" needs review first: run `caracole review`.')
            return 1
        return 0

    refuses.down, refuses.polls = 0, Polls()

    def ended_in_a_review(app):
        app.queue.submit("Fetch Radiohead - Creep", creep.key, fetch_steps(creep.display), fetching=True,
                         display=creep.display)
        app.queue.run_pending()

    url = serve(refuses, "", before=ended_in_a_review)
    with Chromium(tmp_path / "profile") as browser:
        tab = browser.open(url + "jobs?refresh=0")
        tab.wait_for("document.querySelector('#job-1 .waits form.pick-form') !== null")
        widths = tab.eval("""(() => {
          const job = document.querySelector("#job-1");
          const style = getComputedStyle(job);
          const inside = job.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
          return [document.querySelector("#job-1 .waits").getBoundingClientRect().width, inside];
        })()""")
    waits, inside = widths
    assert waits >= inside - 1, widths


# --- the same in the Rows view ------------------------------------------------------------------

ROWS_FIRST = 'document.querySelector(\'button[data-view="rows"]\').click();\n'


def row(dom: str, title: str) -> str:
    found = re.search(r'<article class="row"[^>]*>(?:(?!</article>).)*?<h2 class="row-title"[^>]*>' + re.escape(title)
                      + r"</h2>.*?</article>", dom, re.S)
    assert found, dom[-3000:]
    return found.group(0)


def listed(dom: str) -> str:
    return re.search(r'<main[^>]*id="list"[^>]*>(.*?)</main>', dom, re.S).group(1)


def test_fetch_now_in_a_row_shows_its_progress_on_the_row_then_its_sheet(serve, cfg, conn, tmp_path):
    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep")
    add_song(conn, "Oasis", "Wonderwall")
    script = ("(() => {\n" + WATCH + FIRST_LINE_AND_FOCUS + ROWS_FIRST
              + 'const go = cardOf("Creep").querySelector("form.fetch button");\ngo.focus();\ngo.click();\n})();\n')
    url = serve(FakeCaracole(cfg), script)

    dom = dump_dom(url, tmp_path)

    seen = attribute(dom, "data-seen")
    assert "Fetching from Ultimate Guitar…" in seen, seen
    # Once done, the row is drawn again, as a row, around its line: the sheet is its button now.
    assert 'class="card"' not in listed(dom) and listed(dom).count('<article class="row"') == 2
    shown = row(dom, "Creep")
    line = re.search(r'<p class="progress"[^>]*>.*?</p>', shown, re.S).group(0)
    assert 'role="status"' in line and 'data-tone="ready"' in line and "Open sheet" in line
    assert re.search(r'<div class="row-action"><a [^>]*>Sheet PDF</a>', shown) and 'action="/fetch"' not in shown
    assert 'data-status="found"' in shown and shown.count('class="progress"') == 1
    assert attribute(dom, "data-same") == {"list Creep": True}  # the same live region all along
    assert attribute(dom, "data-focus") == ["p.progress", "Creep"]  # the focus went from the button to the line
    assert 'action="/fetch"' in row(dom, "Wonderwall")


def test_a_rows_pick_opens_its_picker_there_and_the_row_shows_how_it_goes(serve, cfg, conn, tmp_path):
    in_review(conn)
    script = "(() => {\n" + WATCH + ROWS_FIRST + """
new MutationObserver(() => {
  const r = cardOf("Creep");
  const p = r && r.querySelector(".progress");
  if (p && /Queued|Writing|Fetching/.test(p.textContent) && r.querySelector("form.pick-form, .row-pick")) {
    document.body.setAttribute("data-both", "1");
  }
}).observe(document.body, { subtree: true, childList: true, characterData: true });
const r = cardOf("Creep");
r.querySelector(".row-action .row-pick").click();
const panel = r.querySelector(".row-panel");
document.body.setAttribute("data-opened", JSON.stringify({
  panel: !panel.hidden, picker: panel.querySelector("details.picker").open }));
r.querySelector('input[name="pick"][value="radiohead/creep"]').checked = true;
r.querySelector("form.pick-form button[type=submit]").click();
})();
"""
    url = serve(FakeCaracole(cfg), script)

    dom = dump_dom(url, tmp_path)

    assert attribute(dom, "data-opened") == {"panel": True, "picker": True}
    seen = attribute(dom, "data-seen")
    assert "Writing the answer to overrides.toml…" in seen and "Fetching from Ultimate Guitar…" in seen, seen
    assert 'class="card"' not in listed(dom)
    shown = row(dom, "Creep")
    line = re.search(r'<p class="progress"[^>]*>.*?</p>', shown, re.S).group(0)
    assert 'data-tone="ready"' in line and "Open sheet" in line
    assert re.search(r'<div class="row-action"><a [^>]*>Sheet PDF</a>', shown)
    assert 'class="picker"' not in shown and "row-pick" not in shown and "Needs review" not in shown
    assert not re.search(r"<body[^>]*data-both", dom)  # no second pick while the first one ran
