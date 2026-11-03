"""The library page's Sync tab (library_assets/sync.js, sync-tab.html, sync-panel.html), in Chromium, on the page
caracole serve serves with the tab (``WebControls.sync``) against a fake of the sync's routes (``FakeSync``): GET
/api/sync, POST /sync/compare and POST /sync/apply answer the shapes the computer's and the phone's routes answer
(docs/superpowers/plans/2026-11-03-android-port-m1-m3.md §5.3), and /jobs.json tells the sync's view a stage at a
time, as the page follows any request.

The tab draws what it synced with before and the address it remembers; Compare draws the differences grouped by kind,
each with its proposal in words and its choice; Sync waits for every conflict's choice, then posts the comparison and
the choices that aren't the proposals' in one field, never a unit's document, and is offered with nothing to take or
give too; the sync's stages show as it goes, and at its end what it took, gave and left, and Reload. It fits a phone,
five tabs and all, in light and dark. The sync's views are jobs_routes.view's own, of jobs as caracole serve's queue
holds them, and test_web_sync.py checks the fake's other answers are shaped as the real routes answer."""

from __future__ import annotations

import dataclasses
import re
import threading
from urllib.parse import parse_qs, urlsplit

import pytest
from helpers import browser
from helpers.browser import Browser, in_chromium
from helpers.targets import noted, noting, small_targets, weak_edges

from caracole.web.app import WebApp, json_response
from caracole.web.jobs import JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

from test_web_page import with_script

QUICK = {"poll": 100, "undo": 500, "idle": 300}  # the page's timers, for a test on real time
JOB = 41  # the sync's request
ADDRESS = "http://192.168.1.20:8737"

STATE = {"server": "a1b2c3d4e5f60718", "name": "Laptop", "address": ADDRESS,
         "peers": [{"address": ADDRESS, "server": "0f1e2d3c4b5a6978", "name": "Desk",
                    "synced_at": "2026-11-02T21:04:00Z"},
                   {"address": "http://10.0.0.7:8737", "server": "9a8b7c6d5e4f3021", "name": "Studio",
                    "synced_at": "2026-10-30T08:00:00Z"}]}


def difference(unit: str, label: str, proposal: str, why: str, here: str | None, there: str | None) -> dict:
    return {"id": unit, "label": label, "kind": unit.split("/")[0], "proposal": proposal, "why": why,
            "here": here, "there": there}


DIFFERENCES = [
    difference("song/radiohead/creep", "Radiohead - Creep", "theirs", "changed there since the last sync", "a1" * 32,
               "b2" * 32),
    difference("song/muse/hysteria", "Muse - Hysteria", "mine", "new here since the last sync", "c3" * 32, None),
    difference("song/oasis/wonderwall", "Oasis - Wonderwall", "conflict", "changed on both sides since the last sync",
               "d4" * 32, "e5" * 32),
    difference("removed/blur/song 2", "Blur - Song 2 (removed)", "theirs", "new there since the last sync", None,
               "f6" * 32),
    difference("songbook/campfire", "the songbook Campfire", "conflict", "changed on both sides since the last sync",
               "a7" * 32, "b8" * 32),
    difference("alias/soda-stereo", "the alias of soda-stereo", "mine", "changed here since the last sync", "c9" * 32,
               "d0" * 32),
    difference("artist_url/banma", "the UG page of Banma", "theirs", "new there since the last sync", None, "e1" * 32),
    difference("block/1234567", "the blocked tab 1234567", "mine", "new here since the last sync", "f2" * 32, None),
]
COMPARISON = {"comparison": "5a1c0ffee0ddba11", "peer": {"address": ADDRESS, "server": "0f1e2d3c4b5a6978",
                                                        "caracole": "0.1.0", "name": "Desk"},
              "synced_before": "2026-11-02T21:04:00Z", "differences": DIFFERENCES}

def sync_view(state: str, stages: dict[str, tuple[str, str]], units=()) -> dict:
    """The sync's job as /jobs.json gives it, jobs_routes.view's (§5.3's view) of a job of caracole serve's queue in
    ``state``, its stages as ``stages`` says (waiting else), its units as its command said them."""
    from caracole.web.jobs_routes import view

    from test_web_sync import peer_job

    job = peer_job("sync", state, stages, units=units, job_id=JOB, name="Desk", address=ADDRESS)
    return view(job, [job], None, None)


UNITS = [("song/oasis/wonderwall", "taken", ""), ("removed/blur/song 2", "taken", ""), ("artist_url/banma", "taken", ""),
         ("song/muse/hysteria", "given", ""), ("songbook/campfire", "given", ""), ("alias/soda-stereo", "given", ""),
         ("block/1234567", "given", ""), ("song/radiohead/creep", "left", "skipped, as chosen")]
DONE = "Synced: 1 change left as it was"  # its line once it is over
VIEWS = [
    sync_view("queued", {}),
    sync_view("running", {"compare": ("done", "8 differences"), "take": ("running", "3 changes")}),
    sync_view("running", {"compare": ("done", "8 differences"), "take": ("done", "took 3"),
                          "give": ("running", "4 changes")}),
    sync_view("done", {"compare": ("done", "8 differences"), "take": ("done", "took 3"), "give": ("done", "gave 4"),
                       "agree": ("done", "312 units the two agree on")}, UNITS),
]


class FakeSync:
    """The sync's routes, faked in front of a real WebApp: ``state`` for GET /api/sync, ``comparison`` (or a refusal,
    ``refuse_compare``: status and words) for POST /sync/compare, a job of ``views`` for POST /sync/apply (or
    ``refuse_apply``), whose view /jobs.json gives is ``views[at]`` (``auto``: the next one at each ask). It records
    what the page asked and posted, each form's fields."""

    def __init__(self, *, comparison=None, views=None):
        self.state = STATE
        self.comparison = comparison or COMPARISON
        self.views = list(views or VIEWS)
        self.at = 0
        self.auto = False
        self.refuse_compare: tuple[int, str] | None = None
        self.refuse_apply: tuple[int, str] | None = None
        self.asked: list[str] = []  # each GET /api/sync, /jobs.json about the sync
        self.posts: list[tuple[str, dict[str, list[str]]]] = []
        self.lock = threading.Lock()

    def posted(self, path: str) -> list[dict[str, list[str]]]:
        with self.lock:
            return [form for where, form in self.posts if where == path]

    def view(self) -> dict:
        with self.lock:
            seen = self.views[min(self.at, len(self.views) - 1)]
            if self.auto:
                self.at += 1
            return seen

    def wrap(self, app: WebApp) -> None:
        real = app.handle

        def handle(request):
            parts = urlsplit(request.target)
            if request.method == "GET" and parts.path == "/api/sync":
                with self.lock:
                    self.asked.append("state")
                return app.finish(json_response(200, self.state))
            if request.method == "GET" and parts.path == "/jobs.json" and str(JOB) in parse_qs(parts.query).get(
                    "jobs", [""])[0].split(","):
                with self.lock:
                    self.asked.append("job")
                view = self.view()
                return app.finish(json_response(200, {"active": int(view["state"] in ("queued", "running")),
                                                      "jobs": [view]}))
            if request.method == "POST" and parts.path in ("/sync/compare", "/sync/apply"):
                form = parse_qs(request.body.decode("utf-8"), keep_blank_values=True)
                with self.lock:
                    self.posts.append((parts.path, form))
                if form.get("csrf") != ["tok"]:
                    return app.finish(json_response(403, {"error": "Refused", "reload": True}))
                refused = self.refuse_compare if parts.path == "/sync/compare" else self.refuse_apply
                if refused is not None:
                    return app.finish(json_response(refused[0], {"error": refused[1]}))
                if parts.path == "/sync/compare":
                    return app.finish(json_response(200, self.comparison))
                return app.finish(json_response(200, {"job": self.views[0]}))
            return real(request)

        app.handle = handle


@pytest.fixture
def served(cfg, monkeypatch):
    """``served(fake, script="", jobs=())``: caracole serve on a free port, its library page with the Sync tab and
    ``script`` after its own, the sync's routes ``fake``'s, ``jobs`` among the requests the page loads with; returns
    the page's address."""
    import caracole.library_page as library_page

    started = []

    def start(fake: FakeSync, script: str = "", *, jobs: tuple[dict, ...] = ()) -> str:
        real = library_page.build_library_page

        def build(*args, controls=None, **kwargs):
            if controls is not None:
                controls = dataclasses.replace(controls, sync=True, jobs=tuple(controls.jobs) + tuple(jobs))
            page = real(*args, controls=controls, **kwargs)
            return with_script(page, script) if script else page

        monkeypatch.setattr(library_page, "build_library_page", build)
        queue = JobQueue(lambda args, emit: 0)
        app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok", timers=QUICK, searches_lacuerda=False)
        fake.wrap(app)
        server = make_server(app, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
        queue.start()
        started.append((server, queue))
        return f"http://127.0.0.1:{server.server_address[1]}/"

    yield start
    for server, queue in started:
        queue.stop()
        server.shutdown()
        server.server_close()


ROWS = "document.querySelectorAll('#sync-groups .sync-diff').length"
DRAWN = """Array.from(document.querySelectorAll('#sync-groups .sync-diff')).map((row) => [
  row.querySelector('.sync-label').textContent, row.querySelector('.sync-proposal').textContent,
  row.querySelector('.sync-why').textContent,
  (row.querySelector('input:checked') || {}).value || null, row.classList.contains('unchosen')])"""
HEADS = """Array.from(document.querySelectorAll('#sync-groups .sync-group-head')).map((h) => [
  h.firstChild.textContent.trim(), h.querySelector('.n').textContent,
  (h.querySelector('.sync-group-conflicts') || {}).textContent || ''])"""
GO = "document.getElementById('sync-go')"
PLAN = "document.getElementById('sync-plan').textContent"


def pick(page: Browser, label: str, side: str) -> None:
    """A real click on the choice ``side`` (here, there, skip) of the difference ``label``, once it is checked."""
    row = "#sync-groups li.sync-diff[data-id='" + next(d["id"] for d in DIFFERENCES if d["label"] == label) + "']"
    page.click(f"{row} .sync-side.{side}")
    assert page.wait(f"(document.querySelector(\"{row} input:checked\") || {{}}).value === '{side}'"), page.js(DRAWN)


@in_chromium
def test_the_tab_compares_draws_by_kind_waits_for_every_conflict_and_syncs_with_one_field(served, tmp_path):
    fake = FakeSync()
    url = served(fake)
    with Browser(tmp_path / "chrome", width=1280, height=900) as page:
        page.open(url)
        # The library first: the tab asks nothing until it is shown.
        assert page.js("document.getElementById('sync').hidden") is True
        assert page.js("document.querySelector('#tab-sync').textContent") == "Sync"
        page.click("#tab-sync")
        assert page.wait("document.querySelectorAll('#sync-peer-list button').length === 2")
        assert fake.asked.count("state") == 1
        assert page.js("location.hash") == "#tab=sync"
        # The address it synced with last, and each caracole it synced with before, a button that compares with it.
        assert page.js("document.getElementById('sync-address').value") == ADDRESS
        assert page.js("Array.from(document.querySelectorAll('#sync-peer-list .sync-peer-name'))"
                       ".map((n) => n.textContent)") == ["Desk", "Studio"]
        page.click("#sync-compare")
        assert page.wait(f"{ROWS} === 8"), page.js("document.getElementById('sync').innerText")
        [compared] = fake.posted("/sync/compare")
        assert compared == {"csrf": ["tok"], "address": [ADDRESS]}
        assert page.js(HEADS) == [["Songs", "3", "1 conflict"], ["Removals", "1", ""],
                                  ["Songbooks", "1", "1 conflict"], ["Artists' aliases", "1", ""],
                                  ["Artists' UG pages", "1", ""], ["Blocked tabs", "1", ""]]
        assert page.js(DRAWN) == [
            ["Radiohead - Creep", "take there's", "changed there since the last sync", "there", False],
            ["Muse - Hysteria", "keep here's", "new here since the last sync", "here", False],
            ["Oasis - Wonderwall", "CONFLICT", "changed on both sides since the last sync", None, True],
            ["Blur - Song 2 (removed)", "take there's", "new there since the last sync", "there", False],
            ["the songbook Campfire", "CONFLICT", "changed on both sides since the last sync", None, True],
            ["the alias of soda-stereo", "keep here's", "changed here since the last sync", "here", False],
            ["the UG page of Banma", "take there's", "new there since the last sync", "there", False],
            ["the blocked tab 1234567", "keep here's", "new here since the last sync", "here", False]]
        sides = page.js("document.getElementById('sync-sides').textContent")
        assert sides.startswith("Here LaptopThere Desk · " + ADDRESS + "Last synced "), sides
        # Two conflicts: Sync waits for both.
        assert page.js(GO + ".disabled") is True and page.js(PLAN) == "Choose a side for 2 conflicts first."
        pick(page, "Oasis - Wonderwall", "there")
        assert page.js(GO + ".disabled") is True and page.js(PLAN) == "Choose a side for 1 conflict first."
        # Every conflict at once, then one of them the other way.
        page.click("#sync-all-here")
        assert page.wait(GO + ".disabled === false"), page.js(PLAN)
        assert [row[3] for row in page.js(DRAWN)][2::2][:2] == ["here", "here"]
        pick(page, "Oasis - Wonderwall", "there")
        # A proposal flipped and one skipped, which Sync sends too.
        pick(page, "Muse - Hysteria", "there")
        pick(page, "Radiohead - Creep", "skip")
        assert page.js("document.querySelector(\"li[data-id='song/muse/hysteria']\").classList.contains('flipped')")
        assert page.js(PLAN) == "Sync takes 4 here and gives 3 there; 1 skipped."
        page.click("#sync-go")
        assert page.wait("!document.getElementById('sync-job').hidden"), page.js("document.getElementById('sync')"
                                                                                 ".innerText")
        # One field of choices, a line each: every conflict's and each one flipped; nothing else but the comparison.
        [form] = fake.posted("/sync/apply")
        assert sorted(form) == ["choices", "comparison", "csrf", "prefer"]
        assert form["comparison"] == ["5a1c0ffee0ddba11"] and form["prefer"] == [""]
        assert form["choices"][0].split("\n") == ["skip\tsong/radiohead/creep", "there\tsong/muse/hysteria",
                                                  "there\tsong/oasis/wonderwall", "here\tsongbook/campfire"]
        assert page.js("document.getElementById('sync-found').hidden") is True
        assert page.js("document.activeElement.id") == "sync-job-line"
        assert page.js("document.getElementById('sync-job-name').textContent") == "Sync with Desk"
        assert page.js("document.getElementById('sync-compare').disabled") is True  # no second sync meanwhile
        # The job, followed as the page follows a request: its stages as they go.
        fake.at = 1
        assert page.wait("document.getElementById('sync-job-line').textContent === 'Taking what changed there…'")
        assert page.js("Array.from(document.querySelectorAll('#sync-steps .step-chip')).map((c) => c.textContent)") == [
            "✓ Compare: done", "Take: running", "Give: waiting", "Agree: waiting"]
        assert page.js("document.getElementById('sync-job-detail').textContent") == "3 changes"
        assert page.js("document.querySelector('#sync-steps [aria-current=step]').textContent") == "Take: running"
        assert page.js("document.getElementById('sync-reload').hidden") is True
        assert page.js("document.querySelector('#tray-list li')") is None  # the tab says how it goes, not the list
        fake.at = 2
        assert page.wait("document.getElementById('sync-job-line').textContent === 'Giving what changed here…'")
        fake.at = 3
        assert page.wait("!document.getElementById('sync-reload').hidden"), page.js("document.getElementById('sync')"
                                                                                    ".innerText")
        assert page.js("document.getElementById('sync-job-line').textContent").startswith(DONE)
        assert page.js("document.getElementById('sync-job-line').dataset.tone") == "waiting"
        # Its output, in the Requests tab: the line's Details.
        assert page.js("document.querySelector('#sync-job-line a').getAttribute('href')") == f"#tab=requests&job={JOB}"
        assert page.js("""Array.from(document.querySelectorAll('#sync-outcome .sync-done')).map((s) => [
          s.querySelector('h3').textContent, Array.from(s.querySelectorAll('li')).map((li) => li.textContent)])""") == [
            ["Taken here 3", ["Oasis - Wonderwall", "Blur - Song 2 (removed)", "the UG page of Banma"]],
            ["Given there 4", ["Muse - Hysteria", "the songbook Campfire", "the alias of soda-stereo",
                               "the blocked tab 1234567"]],
            ["Left as they were 1", ["Radiohead - Creep — skipped, as chosen"]]]
        assert page.js("document.querySelector('#sync-outcome .sync-note').textContent") == (
            "The two agree on 312 units now.")
        # Reload: the page again, on the Sync tab.
        page.js("window.before = 1")
        page.click("#sync-reload")
        assert page.wait("window.before === undefined && document.readyState === 'complete'"
                         " && !document.getElementById('sync').hidden", timeout=15)
        assert page.wait("document.querySelectorAll('#sync-peer-list button').length === 2")


@in_chromium
def test_a_refusal_says_the_servers_words_and_a_comparison_again_keeps_the_choices_still_as_they_were(served,
                                                                                                    tmp_path):
    fake = FakeSync()
    fake.refuse_compare = (502, "The other caracole can't be reached at http://192.168.1.20:8737.")
    url = served(fake)
    with Browser(tmp_path / "chrome", width=390, height=844, mobile=True) as page:
        page.open(url + "#tab=sync")
        assert page.wait("document.getElementById('sync-address').value !== ''")
        page.click("#sync-compare")
        assert page.wait("document.getElementById('sync-status').textContent === "
                         "\"The other caracole can't be reached at http://192.168.1.20:8737.\"")
        assert page.js("document.getElementById('sync-status').dataset.tone") == "failed"
        assert page.js("document.getElementById('sync-found').hidden") is True
        assert page.js("document.getElementById('sync-compare').disabled") is False
        # A peer synced before compares with its address.
        fake.refuse_compare = None
        page.click("#sync-peer-list li:nth-child(2) button")
        assert page.wait(f"{ROWS} === 8")
        assert fake.posted("/sync/compare")[-1]["address"] == ["http://10.0.0.7:8737"]
        assert page.js("document.getElementById('sync-address').value") == "http://10.0.0.7:8737"
        page.click("#sync-all-there")
        pick(page, "Muse - Hysteria", "skip")
        # Too late: the comparison is gone. Sync says why, and the differences stay as they were.
        fake.refuse_apply = (409, "That comparison is more than 10 minutes old: compare again.")
        page.click("#sync-go")
        assert page.wait("document.getElementById('sync-status').textContent === "
                         "'That comparison is more than 10 minutes old: compare again.'")
        assert page.js("document.getElementById('sync-found').hidden") is False
        assert page.js("document.getElementById('sync-job').hidden") is True
        # Compared again: a difference as it was keeps its choice, one that changed since is proposed afresh.
        changed = dict(DIFFERENCES[2], there="0e" * 32)  # Oasis - Wonderwall, changed there again
        newer = dict(DIFFERENCES[7], kind="blocked-tab")  # a kind this page doesn't know: its id's then
        fake.comparison = dict(COMPARISON, comparison="0ddba11c0ffee5a1",
                               differences=DIFFERENCES[:2] + [changed] + DIFFERENCES[3:7] + [newer])
        fake.refuse_apply = None
        page.click("#sync-compare")
        assert page.wait("document.getElementById('sync-status').textContent === '8 differences with Desk.'")
        drawn = {row[0]: row[3] for row in page.js(DRAWN)}
        assert drawn["Muse - Hysteria"] == "skip" and drawn["the songbook Campfire"] == "there"
        assert drawn["Oasis - Wonderwall"] is None
        assert page.js(PLAN) == "Choose a side for 1 conflict first."
        assert page.js(HEADS)[-1] == ["Blocked tabs", "1", ""]


@in_chromium
def test_nothing_differing_says_the_two_agree_and_still_offers_sync(served, tmp_path):
    fake = FakeSync(comparison=dict(COMPARISON, differences=[]))
    url = served(fake)
    with Browser(tmp_path / "chrome", width=1280, height=900) as page:
        page.open(url + "#tab=sync")
        assert page.wait("document.getElementById('sync-address').value !== ''")
        page.js("document.getElementById('sync-address').focus()")
        page.press("Enter")  # in the field, Enter compares
        assert page.wait("document.getElementById('sync-status').textContent === 'Nothing differs: Laptop and Desk "
                         "agree.'")
        assert len(fake.posted("/sync/compare")) == 1
        # Sync still keeps what the two agree on, and on the phone brings the computer's newer pages and indexes.
        assert page.js("document.getElementById('sync-found').hidden") is False
        assert page.js("document.getElementById('sync-groups').hidden") is True
        assert page.js("document.getElementById('sync-bulk').hidden") is True
        assert page.js(PLAN) == ("Nothing to take or give. Sync still records that the two agree, and brings newer "
                                 "pages and indexes where there are any.")
        assert page.js(GO + ".disabled") is False
        page.click("#sync-go")
        assert page.wait("!document.getElementById('sync-job').hidden")
        [form] = fake.posted("/sync/apply")
        assert form["choices"] == [""] and form["prefer"] == [""]


@in_chromium
def test_every_difference_skipped_still_offers_sync(served, tmp_path):
    fake = FakeSync(comparison=dict(COMPARISON, differences=DIFFERENCES[:2]))
    url = served(fake)
    with Browser(tmp_path / "chrome", width=1280, height=900) as page:
        page.open(url + "#tab=sync")
        assert page.wait("document.getElementById('sync-address').value !== ''")
        page.click("#sync-compare")
        assert page.wait(f"{ROWS} === 2")
        pick(page, "Radiohead - Creep", "skip")
        pick(page, "Muse - Hysteria", "skip")
        assert page.js(PLAN).startswith("Nothing to take or give: every difference is skipped. Sync still")
        assert page.js(GO + ".disabled") is False
        page.click("#sync-go")
        assert page.wait("!document.getElementById('sync-job').hidden")
        [form] = fake.posted("/sync/apply")
        assert form["choices"][0].split("\n") == ["skip\tsong/radiohead/creep", "skip\tsong/muse/hysteria"]


@in_chromium
def test_a_sync_on_its_way_as_the_page_loads_shows_at_once_and_is_followed_to_its_end(served, tmp_path):
    fake = FakeSync()
    fake.at = 1
    url = served(fake, jobs=(VIEWS[1],))
    with Browser(tmp_path / "chrome", width=1280, height=900) as page:
        page.open(url + "#tab=sync")
        assert page.js("document.getElementById('sync-job').hidden") is False
        assert page.js("document.getElementById('sync-job-line').textContent") == "Taking what changed there…"
        assert page.js("document.getElementById('sync-compare').disabled") is True
        fake.at = 3
        assert page.wait("!document.getElementById('sync-reload').hidden")
        assert page.js("document.getElementById('sync-compare').disabled") is False  # over: compare again, or Reload
        assert "job" in fake.asked
        assert page.js("document.getElementById('tray').hidden") is True  # followed quietly: the tab says how


# What the page shows at a width: the tab with every difference drawn, then the sync over; where its five tabs are,
# how wide it got, its controls short of a thumb's size and its fields' edges.
MEASURED = """
(() => {
  const tabs = () => Array.from(document.querySelectorAll(".masthead [role=tab]")).map((t) => {
    const r = t.getBoundingClientRect();
    return [t.id, Math.round(r.left), Math.round(r.right), Math.round(r.top)];
  });
  const later = (test, then) => (test() ? then() : setTimeout(() => later(test, then), 50));
  later(() => document.querySelectorAll("#sync-peer-list button").length === 2, () => {
    document.getElementById("sync-compare").click();
    later(() => document.querySelectorAll("#sync-groups .sync-diff").length === 8, () => {
      document.querySelector("#tab-songbooks .n").textContent = "12";
      document.querySelector("#tab-requests .n").textContent = "3";
      __DIFFS__
      document.getElementById("sync-all-here").click();
      document.getElementById("sync-go").click();
      later(() => !document.getElementById("sync-reload").hidden, () => {
        __DONE__
      });
    });
  });
})();
"""


@pytest.mark.parametrize("width", [320, 390, 1280])
@in_chromium
def test_the_tab_fits_a_phone_with_five_tabs_in_light_and_dark(served, width):
    measure = (noting("data-tabs", "tabs()") + noting("data-edge", "Math.round(document.querySelector('.masthead')"
                                                                     ".getBoundingClientRect().right)")
               + noting("data-row", "(() => { const t = document.querySelector('.masthead .tabs'); "
                                    "return [t.scrollWidth, t.clientWidth, Math.round(t.getBoundingClientRect().left)]; "
                                    "})()")
               + noting("data-diffs-short", small_targets()) + noting("data-diffs-weak", weak_edges())
               + noting("data-diffs-wide", "document.documentElement.scrollWidth"))
    done = (noting("data-done-short", small_targets())
            + noting("data-done-wide", "document.documentElement.scrollWidth")
            + noting("data-done", "document.getElementById('sync-job-line').textContent"))
    fake = FakeSync()
    fake.auto = True
    url = served(fake, MEASURED.replace("__DIFFS__", measure).replace("__DONE__", done))
    for scheme in ("light", "dark"):
        fake.at = 0
        dom = browser.dump_dom(url + "#tab=sync", (width, 900), mobile=width < 500, touch=width < 500,
                               media={"prefers-color-scheme": scheme}, budget_ms=20000)
        tabs = noted(dom, "data-tabs")
        assert [t[0] for t in tabs] == ["tab-library", "tab-songbooks", "tab-sites", "tab-sync", "tab-requests"]
        # The five tabs on one line, inside the page, with counts of two digits and one; on a small phone (320 px)
        # a row of their own under the mark, which scrolls by itself the little they need, never the page.
        assert len({top for *_, top in tabs}) == 1, (scheme, tabs)
        assert all(a[2] <= b[1] for a, b in zip(tabs, tabs[1:])), tabs
        row = noted(dom, "data-row")
        if width < 380:
            assert row[2] == 16 and row[1] == width - 32, row  # the whole row's width, from the gutter
            assert row[0] - row[1] <= 48, row
        else:
            assert tabs[-1][2] <= noted(dom, "data-edge") and row[0] <= row[1], (scheme, tabs, row)
        assert noted(dom, "data-diffs-wide") <= width and noted(dom, "data-done-wide") <= width, scheme
        assert noted(dom, "data-diffs-weak") == [], scheme
        if width < 500:  # on a touch screen every control is a thumb's size
            assert noted(dom, "data-diffs-short") == [], scheme
            assert noted(dom, "data-done-short") == [], scheme
        assert noted(dom, "data-done").startswith(DONE), scheme


def test_the_tab_never_puts_markup_in_from_a_text_and_asks_nothing_of_another_site():
    from caracole.library_assets import HERE

    script = (HERE / "sync.js").read_text(encoding="utf-8")
    for word in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert word not in script, word
    # Every request it makes is to the server that served it, by a path of its own.
    asked = re.findall(r'fetch\(\s*"([^"]*)"', script) + re.findall(r'post\(\s*"([^"]*)"', script)
    assert sorted(set(asked)) == ["api/sync", "sync/apply", "sync/compare"], asked
