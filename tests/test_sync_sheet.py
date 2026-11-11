"""The sync's one flow (library_assets/sync.js, sync-words.js, sync-sheet.html, sync-panel.html), in Chromium, on the
page caracole serve serves (``WebControls.sync`` "tab": the Sync tab, the last, and the sheet) and on the phone's
(``"sheet"``: the sheet alone), against a fake of the sync's routes (``FakeSync``), which answers the shapes both
servers answer (docs/superpowers/plans/2026-11-03-sync-redesign.md §3.4): GET /api/sync, POST /sync/test, POST
/sync/compare, GET /api/sync/unit, POST /sync/apply, GET /api/sync/sizes, POST /sync/export, GET /api/sync/export,
POST /sync/import/open, POST /sync/import/part and POST /sync/import/compare, and /jobs.json tells the sync's view a
stage at a time, as the page follows any request.

The laptop's tab bar splits (Library and Songbooks left, Sites, Requests and Sync right) and a phone's stays one row;
the sheet asks what to sync, with every part ticked and what waits in each; a conflict stops it, card by card, each
side's version told apart, with no Skip; Cancel queues nothing; Sync posts the parts and the conflicts' choices in one
field; a refusal says the server's words and compares again; the sync is followed to its end (and one on its way as
the page loads), and its summary draws each kind of change, closed; export offers the parts with their sizes and
downloads the file; import sends a file in parts, then syncs with it, with no arrow out. It fits a phone and a laptop,
in light and dark. test_web_sync.py checks the fake's answers are shaped as the real routes answer."""

from __future__ import annotations

import copy
import dataclasses
import json
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
ADDRESS = "http://10.0.0.7:8737"
MIB = 1024 * 1024

STATE = {"server": "a1b2c3d4e5f60718", "name": "Laptop", "device": "computer", "address": ADDRESS,
         "peers": [{"address": ADDRESS, "server": "0f1e2d3c4b5a6978", "name": "Studio",
                    "synced_at": "2026-11-02T21:04:00Z"},
                   {"address": "http://192.168.1.20:8737", "server": "9a8b7c6d5e4f3021", "name": "Desk",
                    "synced_at": "2026-10-30T08:00:00Z"}],
         "songs": 111, "songbooks": 2}
PHONE_STATE = dict(STATE, name="Phone", device="phone",
                   peers=[dict(STATE["peers"][0], name="horde_logbook")])
TESTED = {"peer": {"address": ADDRESS, "server": "0f1e2d3c4b5a6978", "caracole": "0.1.0", "name": "Studio"},
          "songs": 96, "songbooks": 3, "indexes": "2026-11-02T09:00:00Z", "synced_at": "2026-11-02T21:04:00Z",
          "said": "Studio answered: 96 songs, 3 songbooks, its indexes read 02/11/26"}


def difference(unit: str, label: str, proposal: str, why: str, change: tuple, *, names=None, listed=()) -> dict:
    """A difference as POST /sync/compare answers it: its digests made up, its names, each side's change, its part
    and the songbooks that list it."""
    kind = unit.split("/")[0]
    part = {"songbook": "songbooks"}.get(kind, "library")
    here = None if change[0] == "gone" or (change[0] is None and change[1] == "new") else "a1" * 32
    there = None if change[1] == "gone" or (change[1] is None and change[0] == "new") else "b2" * 32
    return {"id": unit, "label": label, "kind": kind, "proposal": proposal, "why": why, "here": here, "there": there,
            "names": names, "change": list(change), "part": part, "with": list(listed)}


def song(unit: str, artist: str, title: str, proposal: str, change: tuple, **more) -> dict:
    why = {"mine": "changed here since the last sync", "theirs": "changed there since the last sync",
           "conflict": "both books changed it since the last share"}[proposal]
    return difference(unit, f"{artist} - {title}", proposal, why, change, names={"artist": artist, "title": title},
                      **more)


DIFFERENCES = [
    song("song/the beatles/let it be", "The Beatles", "Let It Be", "theirs", (None, "new")),
    song("song/pomme/mononoke", "Pomme", "Mononoke", "theirs", (None, "changed")),
    song("song/traditional/barbara allen", "Traditional", "Barbara Allen", "mine", ("new", None)),
    song("song/eagles/hotel california", "Eagles", "Hotel California", "conflict", ("changed", "changed"),
         listed=["songbook/campfire"]),
    song("song/oasis/wonderwall", "Oasis", "Wonderwall", "conflict", ("changed", "changed")),
    song("song/radiohead/creep", "Radiohead", "Creep", "theirs", (None, "changed"), listed=["songbook/campfire"]),
    difference("songbook/campfire", "songbook Campfire", "theirs", "changed there since the last sync",
               (None, "changed")),
    difference("songbook/wedding set", "the songbook Wedding set", "theirs", "new there since the last sync",
               (None, "new")),
    difference("alias/soda-stereo", "the alias of soda-stereo", "mine", "changed here since the last sync",
               ("changed", None)),
]
INDEXES = [{"site": "ug", "title": "Ultimate Guitar", "here": "2026-10-30T03:00:00Z", "there": "2026-11-03T03:00:00Z",
            "newer": "there"},
           {"site": "lacuerda", "title": "LaCuerda", "here": "2026-10-29T03:00:00Z", "there": "2026-11-02T03:00:00Z",
            "newer": "there"}]
CAMPFIRE_HERE = {"name": "Campfire", "songs": [["Eagles - Hotel California", {}], ["Radiohead - Creep", {"key": "G"}]]}
CAMPFIRE_THERE = {"name": "Campfire", "songs": [["Eagles - Hotel California", {}], ["Radiohead - Creep", {"key": "G"}],
                                                ["Pomme - Mononoke", {}], ["Oasis - Wonderwall", {}],
                                                ["The Beatles - Let It Be", {}]]}
WEDDING = {"name": "Wedding set", "songs": [[f"Artist {n} - Song {n}", {}] for n in range(12)]}
COMPARISON = {"comparison": "5a1c0ffee0ddba11",
              "peer": {"address": ADDRESS, "server": "0f1e2d3c4b5a6978", "caracole": "0.1.0", "name": "Studio",
                       "kind": "server", "made": None},
              "synced_before": "2026-11-02T21:04:00Z", "holds": ["library", "songbooks", "indexes"],
              "differences": DIFFERENCES,
              "songbooks": {"songbook/campfire": {"here": CAMPFIRE_HERE, "there": CAMPFIRE_THERE},
                            "songbook/wedding set": {"here": None, "there": WEDDING}},
              "indexes": INDEXES}


def song_doc(artist: str, title: str, *, version: str | None = None, pick=("ug", "1234567"), more=(),
             lyrics="found", status="found", album=None) -> dict:
    """A song unit's document, as GET /api/sync/unit answers it (peer_sync.song_document): its sheet the version of
    the lowest pick rank, ``more`` versions after it."""
    versions = [{"provider": pick[0], "tab_id": pick[1], "slot": "chords", "kind": "chords", "rating": 4.8,
                 "votes": 120, "version": 1, "label": "", "coverage": 0.9, "url": "", "raw": None,
                 "fetched_at": "2026-11-01T10:00:00Z", "pick_rank": 1, "gone": 0,
                 "files": [{"name": "sheet.txt", "sha256": "c3" * 32, "kept_rank": 1}]}]
    for n, (provider, tab) in enumerate(more, start=2):
        versions.append(dict(versions[0], provider=provider, tab_id=tab, pick_rank=n, files=[]))
    return {"key": f"{artist.lower()}/{title.lower()}",
            "names": {"artist": artist, "artists": [artist], "title": title, "album": album, "duration_ms": None,
                      "variant": None},
            "song": {"status": status, "review": 0, "lyrics_status": lyrics},
            "versions": versions, "kv": {}, "overrides": {} if version is None else {"version": version}}


UNITS = {
    "song/eagles/hotel california": {"here": song_doc("Eagles", "Hotel California", version="key=Am&capo=2"),
                                     "there": song_doc("Eagles", "Hotel California", pick=("ug", "7654321"))},
    "song/oasis/wonderwall": {"here": song_doc("Oasis", "Wonderwall", lyrics="missing"),
                              "there": song_doc("Oasis", "Wonderwall", lyrics="found")},
}


def sync_view(state: str, stages: dict[str, tuple[str, str]], units=(), report=None, *, name="Studio",
              address=ADDRESS) -> dict:
    """The sync's job as /jobs.json gives it, jobs_routes.view's (§5.3's view) of a job of caracole serve's queue in
    ``state``, its stages as ``stages`` says (waiting else), its units as its command said them, and its report
    (§3.5) once over."""
    from caracole.web.jobs_routes import view

    from test_web_sync import peer_job

    job = peer_job("sync", state, stages, units=units, job_id=JOB, name=name, address=address)
    seen = view(job, [job], None, None)
    if report is not None and seen.get("outcome") is not None:
        seen["outcome"] = dict(seen["outcome"], report=report)
    return seen


REPORT = {"with": {"name": "Studio", "kind": "server", "address": ADDRESS}, "at": "2026-11-03T18:42:00Z",
          "parts": ["library", "songbooks", "indexes"],
          "indexes": [{"site": "ug", "title": "Ultimate Guitar", "direction": "taken", "before": 1503236,
                       "after": 1515576, "read": "2026-11-03T03:00:00Z"},
                      {"site": "lacuerda", "title": "LaCuerda", "direction": "taken", "before": 23105,
                       "after": 22895, "read": "2026-11-02T03:00:00Z"}]}
TAKEN_GIVEN = [("song/the beatles/let it be", "taken", ""), ("song/pomme/mononoke", "taken", ""),
               ("song/radiohead/creep", "taken", ""), ("song/eagles/hotel california", "given", ""),
               ("song/oasis/wonderwall", "taken", ""), ("songbook/campfire", "taken", ""),
               ("songbook/wedding set", "taken", ""), ("song/traditional/barbara allen", "given", ""),
               ("alias/soda-stereo", "given", "")]
VIEWS = [
    sync_view("queued", {}),
    sync_view("running", {"compare": ("done", "9 differences"), "take": ("running", "6 changes")}),
    sync_view("running", {"compare": ("done", "9 differences"), "take": ("done", "took 6"),
                          "give": ("running", "3 changes")}),
    sync_view("done", {"compare": ("done", "9 differences"), "take": ("done", "took 6"), "give": ("done", "gave 3"),
                       "agree": ("done", "312 units the two agree on"), "index": ("done", "2 indexes")},
              TAKEN_GIVEN, REPORT),
]
# The phone's: the computer it syncs with, by its library's name.
PHONE_REPORT = dict(REPORT, **{"with": {"name": "Studio", "kind": "computer", "address": ADDRESS}})
PHONE_VIEWS = VIEWS[:-1] + [dict(VIEWS[-1], outcome=dict(VIEWS[-1]["outcome"], report=PHONE_REPORT))]
SIZES = {"name": "Laptop", "songs": 111, "songbooks": 2, "made": "2026-11-03T18:42:00Z", "library": 34_000_000,
         "indexes": 207_000_000, "tabs": 1515576}
EXPORTED = {"export": "0123456789abcdef", "name": "Laptop-03-11-26.caracole", "size": 34_200_000}
FILE_COMPARISON = dict(COMPARISON, comparison="f11ec0ffee0ddba1",
                       peer={"address": None, "server": "1234abcd5678ef90", "caracole": "0.1.0", "name": "Phone",
                             "kind": "file", "made": "2026-11-03T20:10:00Z"},
                       holds=["library", "songbooks"], indexes=[],
                       differences=[d for d in DIFFERENCES if d["proposal"] != "mine"])
FILE_REPORT = {"with": {"name": "Phone", "kind": "file", "address": None}, "at": "2026-11-03T20:14:00Z",
               "parts": ["library", "songbooks"], "indexes": []}


class FakeSync:
    """The sync's routes, faked in front of a real WebApp (§3.4's shapes): ``state`` for GET /api/sync, ``tested``
    for POST /sync/test, ``comparison`` for POST /sync/compare, ``units`` for GET /api/sync/unit, a job of ``views``
    for POST /sync/apply, whose view /jobs.json gives is ``views[at]`` (``auto``: the next one at each ask); and the
    export's and the import's (``sizes``, ``exported``, ``file_comparison``), one import open at a time, as caracole
    serve stages them (409 for another until it is dropped, or refused at its comparison, which deletes it).
    ``refuse[path]`` holds refusals (status, words), each answered once in its turn; ``hold_on(path)`` holds the next
    answer to a post there until the event it gives is set. It records what the page asked (``asked``: each GET's
    path and query) and posted (``posts``: each form's fields, each JSON document, each part's place and size)."""

    def __init__(self, *, state=None, comparison=None, views=None):
        self.state = copy.deepcopy(state or STATE)
        self.tested = copy.deepcopy(TESTED)
        self.comparison = copy.deepcopy(comparison or COMPARISON)
        self.units = copy.deepcopy(UNITS)
        self.views = list(views or VIEWS)
        self.sizes = dict(SIZES)
        self.exported = dict(EXPORTED)
        self.file_comparison = copy.deepcopy(FILE_COMPARISON)
        self.at = 0
        self.auto = False
        self.refuse: dict[str, list[tuple[int, str]]] = {}
        self.asked: list[str] = []
        self.posts: list[tuple[str, object]] = []
        self.received = bytearray()
        self.size = 0
        self.opened: str | None = None  # the import open now
        self.imports = 0
        self.held: dict[str, threading.Event] = {}
        self.lock = threading.Lock()

    def hold_on(self, path: str) -> threading.Event:
        """The next post to ``path`` answered only once the event this gives is set."""
        event = threading.Event()
        with self.lock:
            self.held[path] = event
        return event

    def posted(self, path: str) -> list:
        with self.lock:
            return [body for where, body in self.posts if where == path]

    def awaited(self, path: str, n: int = 1, timeout: float = 10.0) -> list:
        """What the page posted to ``path``, once it has posted ``n`` times there (a view may change before its
        request reaches the server)."""
        import time

        deadline = time.monotonic() + timeout
        while len(self.posted(path)) < n and time.monotonic() < deadline:
            time.sleep(0.02)
        return self.posted(path)

    def gets(self, path: str) -> list[str]:
        with self.lock:
            return [a for a in self.asked if urlsplit(a).path == path]

    def view(self) -> dict:
        with self.lock:
            seen = self.views[min(self.at, len(self.views) - 1)]
            if self.auto:
                self.at += 1
            return seen

    def _refused(self, path: str):
        with self.lock:
            waiting = self.refuse.get(path)
            return waiting.pop(0) if waiting else None

    def wrap(self, app: WebApp) -> None:
        real, limit = app.handle, app.body_limit

        def body_limit(method, target):
            return 8 * MIB if urlsplit(target).path == "/sync/import/part" else limit(method, target)

        def answer(status, body):
            return app.finish(json_response(status, body))

        def handle(request):
            parts = urlsplit(request.target)
            path, query = parts.path, parse_qs(parts.query)
            if request.method == "GET" and (path.startswith("/api/sync") or path == "/jobs.json"
                                            and str(JOB) in query.get("jobs", [""])[0].split(",")):
                with self.lock:
                    self.asked.append(request.target)
                refused = self._refused(path)
                if refused is not None:
                    return answer(refused[0], {"error": refused[1]})
                if path == "/api/sync":
                    return answer(200, self.state)
                if path == "/jobs.json":
                    view = self.view()
                    return answer(200, {"active": int(view["state"] in ("queued", "running")), "jobs": [view]})
                if path == "/api/sync/unit":  # the page's own script's alone: the token in its header
                    if request.headers.get("x-caracole-form-token") != "tok":
                        return answer(403, {"error": "Refused", "reload": True})
                    unit = query.get("id", [""])[0]
                    if unit not in self.units:
                        return answer(404, {"error": "Not compared."})
                    return answer(200, {"id": unit, **self.units[unit]})
                if path == "/api/sync/sizes":
                    return answer(200, self.sizes)
                if path == "/api/sync/export":
                    from caracole.download_names import content_disposition

                    return app.finish(type(json_response(200, {}))(200, b"PK\x03\x04 a .caracole file", [
                        ("Content-Type", "application/vnd.caracole+zip"),
                        ("Content-Disposition", content_disposition(self.exported["name"]))]))
                return answer(404, {"error": "No such route."})
            if request.method == "POST" and path.startswith("/sync/"):
                kind = request.headers.get("content-type", "").split(";")[0]
                if kind == "application/x-www-form-urlencoded":
                    body: object = parse_qs(request.body.decode("utf-8"), keep_blank_values=True)
                    token = body.get("csrf", [""])[0]
                elif kind == "application/json":
                    body = json.loads(request.body)
                    token = request.headers.get("x-caracole-form-token", "")
                else:
                    body = {"at": int(query.get("at", ["-1"])[0]), "size": len(request.body),
                            "import": query.get("import", [""])[0]}
                    token = request.headers.get("x-caracole-form-token", "")
                with self.lock:
                    self.posts.append((path, body))
                    held = self.held.pop(path, None)
                if held is not None:
                    held.wait(20)
                if token != "tok":
                    return answer(403, {"error": "Refused", "reload": True})
                refused = self._refused(path)
                if refused is not None:
                    if path == "/sync/import/compare":  # a file refused is deleted: another may be opened
                        with self.lock:
                            self.opened = None
                    return answer(refused[0], {"error": refused[1]})
                if path == "/sync/test":
                    return answer(200, self.tested)
                if path == "/sync/compare":
                    return answer(200, self.comparison)
                if path == "/sync/import/compare":
                    return answer(200, self.file_comparison)
                if path == "/sync/apply":
                    return answer(200, {"job": self.views[0]})
                if path == "/sync/export":
                    return answer(200, self.exported)
                if path == "/sync/import/open":
                    with self.lock:
                        if self.opened is not None:
                            return answer(409, {"error": "A file is being sent here already: try again once it is "
                                                         "taken, or in an hour."})
                        self.opened = format(0xfedcba9876543210 - self.imports, "016x")
                        self.imports += 1
                        self.size = int(body["size"])
                        self.received = bytearray()
                        opened_ = self.opened
                    return answer(200, {"import": opened_, "part": 8 * MIB})
                if path == "/sync/import/part":
                    with self.lock:
                        if body["import"] != self.opened:
                            return answer(404, {"error": "No such import is open here: choose the file again."})
                        if body["at"] != len(self.received):
                            return answer(400, {"error": "That part isn't the next one."})
                        self.received.extend(request.body)
                        have = len(self.received)
                    return answer(200, {"have": have})
                if path == "/sync/import/drop":
                    with self.lock:
                        if body.get("import") != self.opened:
                            return answer(404, {"error": "No such import is open here: choose the file again."})
                        self.opened = None
                    return answer(200, {"dropped": body["import"]})
                return answer(404, {"error": "No such route."})
            return real(request)

        app.handle = handle
        app.body_limit = body_limit


@pytest.fixture
def served(cfg, monkeypatch):
    """``served(fake, script="", sync="tab", jobs=())``: caracole serve on a free port, its library page with the
    sync as ``sync`` says (``"tab"``: the computer's; ``"sheet"``: the phone's), ``script`` after its own, the sync's
    routes ``fake``'s, ``jobs`` among the requests the page loads with; returns the page's address."""
    import caracole.library_page as library_page

    started = []
    real = library_page.build_library_page  # each start's page its own, the last start's settings

    def start(fake: FakeSync, script: str = "", *, sync: str = "tab", jobs: tuple[dict, ...] = ()) -> str:
        def build(*args, controls=None, **kwargs):
            if controls is not None:
                controls = dataclasses.replace(controls, sync=sync, jobs=tuple(controls.jobs) + tuple(jobs),
                                               badge="Phone" if sync == "sheet" else controls.badge)
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


# --- the tab bar, and which page has what -------------------------------------------------------------------------

TABS = """(() => Array.from(document.querySelectorAll(".masthead [role=tab]")).map((t) => {
  const r = t.getBoundingClientRect();
  return [t.id, Math.round(r.left), Math.round(r.right), Math.round(r.top)];
}))()"""


@in_chromium
def test_the_laptops_tab_bar_splits_library_and_songbooks_from_sites_requests_and_sync(served):
    url = served(FakeSync(), noting("data-tabs", TABS) + noting("data-middle", "innerWidth / 2"))
    for scheme in ("light", "dark"):
        dom = browser.dump_dom(url, (1280, 900), media={"prefers-color-scheme": scheme})
        tabs = noted(dom, "data-tabs")
        assert [t[0] for t in tabs] == ["tab-library", "tab-songbooks", "tab-sites", "tab-requests", "tab-sync"]
        assert len({top for *_, top in tabs}) == 1, tabs
        library, songbooks, sites = tabs[0], tabs[1], tabs[2]
        assert sites[1] > noted(dom, "data-middle") > songbooks[2], tabs  # Sites on the right half, Songbooks left
        assert songbooks[1] - library[2] <= 8 and all(b[1] - a[2] <= 8 for a, b in zip(tabs[2:], tabs[3:])), tabs


@in_chromium
@pytest.mark.parametrize(("sync", "width"), [("tab", 390), ("sheet", 390), ("sheet", 800)])
def test_on_a_phone_the_tabs_stay_one_row_unsplit(served, sync, width):
    """A phone's width, and the phone's page at any (in landscape, or a tablet's 800 px): one row, none pushed
    aside; only caracole serve's page, the one with a Sync tab, splits from 720 px."""
    url = served(FakeSync(), noting("data-tabs", TABS) + noting("data-wide", "document.documentElement.scrollWidth"),
                 sync=sync)
    dom = browser.dump_dom(url, (width, 844), mobile=True, touch=True)
    tabs = noted(dom, "data-tabs")
    names = ["tab-library", "tab-songbooks", "tab-sites", "tab-requests"] + (["tab-sync"] if sync == "tab" else [])
    assert [t[0] for t in tabs] == names
    assert len({top for *_, top in tabs}) == 1, tabs
    assert all(0 <= b[1] - a[2] <= 8 for a, b in zip(tabs, tabs[1:])), tabs  # one row, none pushed aside
    assert noted(dom, "data-wide") <= width


def test_the_phones_page_has_the_sheet_and_no_sync_tab(conn, cfg):
    from caracole.library_page import WebControls, assemble_page

    data = {"songs": [], "server": {"csrf": "tok", "jobs": []}}
    phone = assemble_page(data, WebControls("tok", sync="sheet"), problem=None, library_name="Phone")
    laptop = assemble_page(data, WebControls("tok", sync="tab"), problem=None, library_name="Laptop")
    served = assemble_page(data, WebControls("tok"), problem=None, library_name="Laptop")
    written = assemble_page(data, None, problem=None, library_name="Laptop")
    markup = [page.split('<script type="application/json"')[0] for page in (phone, laptop, served, written)]
    assert 'id="tab-sync"' not in markup[0] and 'id="sync"' not in markup[0]
    assert markup[0].count('id="sync-sheet"') == 1 and markup[0].count('id="sync-file"') == 1
    assert markup[1].count('id="tab-sync"') == 1 and markup[1].count('id="sync-sheet"') == 1
    assert markup[1].index('id="tab-requests"') < markup[1].index('id="tab-sync"')  # Sync last
    assert markup[1].count('id="sync-start"') == 1 and markup[1].count('for="sync-file"') == 1
    for page in markup[2:]:
        assert 'id="tab-sync"' not in page and 'id="sync-sheet"' not in page


def test_the_sheet_never_puts_markup_in_from_a_text_and_asks_nothing_of_another_site():
    from caracole.library_assets import HERE

    for name in ("sync.js", "sync-words.js"):
        path = HERE / name
        if not path.exists():
            continue
        script = path.read_text(encoding="utf-8")
        for word in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            assert word not in script, (name, word)
        # Every request it makes is to the server that served it, by a path of its own: a literal relative path,
        # or the one its helpers pass on.
        for call in re.findall(r"fetch\(\s*([^,)]*)", script):
            assert call.strip() == "path" or re.fullmatch(r'"[a-z][a-z/.]*(\?[a-z=]*)?"( \+ .*)?', call.strip()), (
                name, call)
        for call in re.findall(r"\b(?:ask|post|send)\(\s*([^,)]*)", script):
            if call.strip().startswith('"'):
                assert re.fullmatch(r'"[a-z][a-z/.]*(\?[a-z=&]*)?"( \+ .*)?', call.strip()), (name, call)


# --- the Sync tab's panels -------------------------------------------------------------------------------------

@in_chromium
def test_the_tab_tests_a_server_and_says_when_it_last_synced_with_it(served, tmp_path):
    fake = FakeSync()
    with opened(tmp_path, served(fake)) as page:
        assert fake.gets("/api/sync") == []  # the library first: the tab asks nothing until it is shown
        page.click("#tab-sync")
        assert page.wait(f"document.getElementById('sync-address').value === '{ADDRESS}'")
        assert len(fake.gets("/api/sync")) == 1 and page.js("location.hash") == "#tab=sync"
        assert page.js("document.getElementById('sync-last').textContent") == "Last synced with Studio 02/11/26, 22:04"
        assert page.js("Array.from(document.querySelectorAll('#sync-peers option')).map((o) => o.value)") == [
            ADDRESS, "http://192.168.1.20:8737"]
        assert page.js("Array.from(document.querySelectorAll('#sync .sync-panel-head')).map((h) => h.textContent)") == [
            "Sync with a server", "Export", "Import a file"]
        page.click("#sync-test")
        assert page.wait("document.getElementById('sync-tested').dataset.tone === 'done'")
        assert page.js("document.getElementById('sync-tested').textContent") == (
            "✓ Studio answered: 96 songs, 3 songbooks, its indexes read 02/11/26")
        assert fake.posted("/sync/test") == [{"csrf": ["tok"], "address": [ADDRESS]}]
        assert fake.posted("/sync/compare") == []  # Test changes nothing, compares nothing
        # Another address: never synced with it; none: neither Test nor Sync.
        page.js("document.getElementById('sync-address').select()")
        page.type("http://10.0.0.9:8737")
        assert page.wait("document.getElementById('sync-last').textContent === 'Never synced with it'")
        assert page.js("document.getElementById('sync-tested').textContent") == ""
        fake.refuse["/sync/test"] = [(502, "Nothing answered at http://10.0.0.9:8737.")]
        page.click("#sync-test")
        assert page.wait("document.getElementById('sync-tested').dataset.tone === 'failed'")
        assert page.js("document.getElementById('sync-tested').textContent") == "Nothing answered at http://10.0.0.9:8737."
        page.js("const a = document.getElementById('sync-address'); a.value = ''; a.dispatchEvent(new Event('input'))")
        assert page.js("[document.getElementById('sync-test').disabled, document.getElementById('sync-start').disabled]") == [
            True, True]


@pytest.mark.parametrize("width", [390, 1280])
@in_chromium
def test_the_tabs_panels_fit_a_phone_and_a_laptop_in_light_and_dark(served, width):
    phone = width < 500
    panels = ":not(#sync *)"
    url = served(FakeSync(), noting("data-short", small_targets(panels)) + noting("data-weak", weak_edges(panels))
                 + noting("data-wide", "document.documentElement.scrollWidth")
                 + noting("data-tops", "Array.from(document.querySelectorAll('.sync-panel')).map((p) => "
                                       "Math.round(p.getBoundingClientRect().top))"))
    for scheme in ("light", "dark"):
        dom = browser.dump_dom(url + "#tab=sync", (width, 900), mobile=phone, touch=phone,
                               media={"prefers-color-scheme": scheme})
        assert noted(dom, "data-wide") <= width, scheme
        assert noted(dom, "data-weak") == [], scheme
        if phone:
            assert noted(dom, "data-short") == [], scheme
        tops = noted(dom, "data-tops")
        assert len(set(tops)) == (3 if phone else 1), tops  # stacked on a phone, side by side on a laptop


# --- the flow, driven as the owner drives it --------------------------------------------------------------------

SHEET = "document.getElementById('sync-sheet')"
PARTS_SAID = """Array.from(document.querySelectorAll('#sync-parts .sync-part')).map((p) => [
  p.querySelector('.sync-part-name').textContent + ' · ' + p.querySelector('.sync-part-said').textContent,
  p.querySelector('input').checked, p.querySelector('input').disabled])"""
COUNTS = ("Array.from(document.querySelectorAll('#sync-counts li')).filter((li) => !li.hidden)"
          ".map((li) => [li.className, li.textContent.trim().replace(/\\s+/g, ' ')])")
CHIPS = "Array.from(document.querySelectorAll('#sync-chips li')).map((li) => [li.textContent, li.dataset.state || ''])"
CARD = """(() => {
  const lines = (id) => Array.from(document.querySelectorAll('#' + id + ' .sync-lines > *')).map((n) => n.textContent);
  const head = (id) => document.querySelector('#' + id + ' .sync-side-head').textContent;
  return {name: document.getElementById('sync-card-name').textContent,
          at: document.getElementById('sync-card-at').textContent,
          heads: [head('sync-card-here'), head('sync-card-there')],
          here: lines('sync-card-here'), there: lines('sync-card-there'),
          keep: [document.getElementById('sync-keep-here').textContent,
                 document.getElementById('sync-keep-there').textContent],
          same: document.getElementById('sync-same-row').hidden ? null
            : document.getElementById('sync-same-said').textContent};
})()"""
SUMMARY = """Array.from(document.querySelectorAll('#sync-done .sync-section')).map((s) => ({
  kind: s.dataset.kind, said: s.querySelector('.sync-lane-said').textContent,
  open: s.querySelector('.sync-lane').getAttribute('aria-expanded'), hidden: s.querySelector('.sync-rows').hidden,
  way: s.querySelector('.sync-arrow').dataset.way,
  rows: Array.from(s.querySelectorAll('.sync-rows li')).map((li) => Array.from(li.children).map((c) => c.textContent))}))"""
STATUS = "document.getElementById('sync-status').textContent"


def at_view(page: Browser, view: str, timeout: float = 10.0) -> None:
    assert page.wait(f"{SHEET}.open && {SHEET}.dataset.view === '{view}'", timeout), (
        page.js(f"[{SHEET}.open, {SHEET}.dataset.view, {STATUS}]"))


def at_card(page: Browser) -> None:
    """A conflict's card, its two versions read: nothing on it moves any more under a click."""
    at_view(page, "conflict")
    assert page.wait("document.querySelector('#sync-card-here .sync-lines').dataset.state !== 'reading'")


def opened(tmp_path, url: str, *, width=1280, height=900, mobile=False) -> Browser:
    page = Browser(tmp_path / "chrome", width=width, height=height, mobile=mobile)
    page.send("Emulation.setTimezoneOverride", timezoneId="Europe/Madrid")
    # No sheet sliding up while a test clicks in it: a click lands where its button is.
    page.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-reduced-motion", "value": "reduce"}])
    page.open(url)
    return page


def fresh(fake: FakeSync) -> FakeSync:
    """The comparison's indexes read now, so that what waits says "today"."""
    from datetime import UTC, datetime, timedelta

    now = (datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    fake.comparison["indexes"][0]["there"] = now
    return fake


def start_on_the_laptop(page: Browser) -> None:
    """The Sync tab, its address the one it synced with last, then Sync: the sheet, compared."""
    assert page.wait(f"document.getElementById('sync-address').value === '{ADDRESS}'")
    assert page.wait("document.getElementById('sync-last').textContent.startsWith('Last synced with Studio ')")
    page.click("#sync-start")
    at_view(page, "what")
    assert page.wait("!document.getElementById('sync-counts').hidden")


@in_chromium
def test_the_sheet_asks_what_to_sync_with_every_part_ticked_and_says_whats_waiting(served, tmp_path):
    fake = fresh(FakeSync())
    with opened(tmp_path, served(fake) + "#tab=sync") as page:
        assert fake.gets("/api/sync/unit") == [] and fake.posted("/sync/compare") == []  # nothing until asked
        start_on_the_laptop(page)
        assert fake.posted("/sync/compare") == [{"csrf": ["tok"], "address": [ADDRESS]}]
        assert page.js("document.getElementById('sync-title').textContent") == "Sync with Studio"
        assert page.js("document.getElementById('sync-sub').textContent").startswith(ADDRESS + " · last synced 02/11/26,")
        assert page.js(PARTS_SAID) == [
            ["Library · Your songs, their sheets and pages, both ways · 5 changed on Studio, 4 changed on this "
             "computer", True, False],
            ["Songbooks · Your songbooks and their set lists, both ways · 2 changed on Studio", True, False],
            ["Site indexes · For searching offline · newer on Studio: Ultimate Guitar (read today) and 1 more",
             True, False]]
        assert page.js(COUNTS) == [["take", "5 to take"], ["give", "2 to give"], ["both", "2 changed on both"]]
        assert page.js(CHIPS) == [["Compared", "done"], ["Your choice", ""], ["Library", ""], ["Songbooks", ""],
                                  ["Indexes", ""]]
        assert page.js("[document.getElementById('sync-cancel').textContent, "
                       "document.getElementById('sync-go').textContent]") == ["Cancel", "Sync"]
        # Escape before Sync is Cancel: nothing sent.
        page.press("Escape")
        assert page.wait(f"!{SHEET}.open")
        assert fake.posted("/sync/apply") == []
    # On the phone: the sheet from its address, the computer by its name, the word taken out of the address.
    fake = fresh(FakeSync(state=PHONE_STATE))
    with opened(tmp_path, served(fake, sync="sheet") + "#sheet=sync", width=390, height=844, mobile=True) as page:
        at_view(page, "what")
        assert page.wait("!document.getElementById('sync-counts').hidden")
        assert page.js("location.hash") in ("", "#")
        assert page.js("document.getElementById('sync-title').textContent") == "Sync with Studio"
        assert [said for said, *_ in page.js(PARTS_SAID)] == [
            "Library · Your songs, their sheets and pages, both ways · 5 changed on the computer, 4 changed on the "
            "phone",
            "Songbooks · Your songbooks and their set lists, both ways · 2 changed on the computer",
            "Site indexes · For searching offline · newer on the computer: Ultimate Guitar (read today) and 1 more"]
        assert fake.posted("/sync/compare") == [{"csrf": ["tok"], "address": [ADDRESS]}]


@in_chromium
@pytest.mark.parametrize("device", ["computer", "phone"])
def test_a_conflict_stops_it_card_by_card_with_each_sides_lines_and_the_sides_named(served, tmp_path, device):
    fake = FakeSync(state=PHONE_STATE if device == "phone" else STATE)
    url = served(fake, sync="sheet" if device == "phone" else "tab") + "#sheet=sync"
    with opened(tmp_path, url, **({"width": 390, "height": 844, "mobile": True} if device == "phone" else {})) as page:
        at_view(page, "what")
        assert page.wait("!document.getElementById('sync-go').disabled")
        page.click("#sync-go")
        at_card(page)
        here, there = ("This computer", "Studio") if device == "computer" else ("Phone", "Computer")
        on = ("On this computer", "On Studio") if device == "computer" else ("On the phone", "On the computer")
        assert page.js(CARD) == {
            "name": "Eagles · Hotel California", "at": "1 of 2", "heads": list(on),
            "here": ["Its own key", "A minor, capo 2", "Its sheet", "UG · tab 1234567"],
            "there": ["Its own key", "as the sheet's", "Its sheet", "UG · tab 7654321"],
            "keep": [here, there], "same": "Same for the other 1"}
        assert fake.gets("/api/sync/unit") == ["/api/sync/unit?comparison=5a1c0ffee0ddba11&id=song%2Feagles%2Fhotel%20"
                                               "california"]
        assert page.js(CHIPS)[:2] == [["Compared", "done"], ["Your choice", "now"]]
        assert page.js("document.querySelector('#sync-conflict').textContent").count("Skip") == 0  # no Skip
        page.click("#sync-keep-here")
        assert page.wait("document.getElementById('sync-card-at').textContent === '2 of 2'")
        assert page.wait("document.querySelector('#sync-card-here .sync-lines').dataset.state === ''")
        card = page.js(CARD)
        assert (card["name"], card["here"], card["there"], card["same"]) == (
            "Oasis · Wonderwall", ["Its lyrics", "missing"], ["Its lyrics", "found"], None)
        assert fake.posted("/sync/apply") == []  # nothing sent until the last card is answered


@in_chromium
def test_same_for_the_other_n_settles_every_conflict_left_and_sync_posts_one_field_of_choices(served, tmp_path):
    fake = FakeSync()
    with opened(tmp_path, served(fake) + "#sheet=sync") as page:
        at_view(page, "what")
        assert page.wait("!document.getElementById('sync-go').disabled")
        page.click("#sync-go")
        at_card(page)
        page.click("#sync-same")
        page.click("#sync-keep-here")
        at_view(page, "going")
        [form] = fake.awaited("/sync/apply")
        assert form == {"csrf": ["tok"], "comparison": ["5a1c0ffee0ddba11"], "prefer": [""],
                        "choices": ["here\tsong/eagles/hotel california\nhere\tsong/oasis/wonderwall"],
                        "parts": ["library,songbooks,indexes"]}
        assert len(fake.gets("/api/sync/unit")) == 1  # the one card shown
        assert page.js("document.getElementById('sync-title').textContent") == "Syncing with Studio"
        assert page.wait("document.activeElement.id === 'sync-going-line'")


@in_chromium
def test_cancel_on_a_card_queues_nothing(served, tmp_path):
    fake = FakeSync()
    with opened(tmp_path, served(fake) + "#sheet=sync") as page:
        at_view(page, "what")
        assert page.wait("!document.getElementById('sync-go').disabled")
        page.click("#sync-go")
        at_card(page)
        page.click("#sync-keep-there")
        assert page.wait("document.getElementById('sync-card-at').textContent === '2 of 2'")
        page.click("#sync-cancel")
        assert page.wait(f"!{SHEET}.open")
        assert fake.posted("/sync/apply") == []
        assert page.js("document.documentElement.classList.contains('sheet-open')") is False
        # Opened again, it compares afresh and starts at the beginning: Cancel forgot the side chosen on a card too.
        page.js("location.hash = '#sheet=sync'")
        at_view(page, "what")
        assert page.wait("!document.getElementById('sync-go').disabled")
        assert len(fake.posted("/sync/compare")) == 2
        page.click("#sync-go")
        at_card(page)
        assert page.js(CARD)["name"] == "Eagles · Hotel California" and page.js(CARD)["at"] == "1 of 2"
        page.press("Escape")  # Escape on a card is Cancel too
        assert page.wait(f"!{SHEET}.open")
        assert fake.posted("/sync/apply") == []


@in_chromium
def test_unticked_parts_are_sent_and_their_differences_counted_out(served, tmp_path):
    fake = FakeSync()
    with opened(tmp_path, served(fake) + "#sheet=sync") as page:
        at_view(page, "what")
        assert page.wait("!document.getElementById('sync-go').disabled")
        page.click(".sync-part[data-part=library] input")
        page.click(".sync-part[data-part=indexes] input")
        # Songbooks alone: its two songbooks, and the songs they list, which come along with them.
        assert page.js(COUNTS) == [["take", "3 to take"], ["give", "0 to give"], ["both", "1 changed on both"]]
        assert page.js(CHIPS) == [["Compared", "done"], ["Your choice", ""], ["Songbooks", ""]]
        page.click(".sync-part[data-part=songbooks] input")
        assert page.js("document.getElementById('sync-go').disabled") is True  # nothing ticked, nothing to sync
        page.click(".sync-part[data-part=songbooks] input")
        page.click("#sync-go")
        at_card(page)
        assert page.js("document.getElementById('sync-card-at').textContent") == "1 of 1"
        page.click("#sync-keep-there")
        at_view(page, "going")
        [form] = fake.awaited("/sync/apply")
        assert form["parts"] == ["songbooks"] and form["choices"] == ["there\tsong/eagles/hotel california"]


@in_chromium
def test_a_song_a_songbook_lists_comes_along_with_songbooks_but_is_never_removed_by_them(served, tmp_path):
    """peer_sync.in_scope, as POST /sync/apply reads it: with Songbooks alone, a song a songbook lists comes along to
    the side that lacks it, but a removal of it (a side that lacks it, and the sync not to bring it there), given or
    changed on both, is the library's: neither counted, nor carded, nor sent."""
    comparison = copy.deepcopy(COMPARISON)
    by = {d["id"]: d for d in comparison["differences"]}
    # Creep, which Campfire lists, removed here: the sync would remove it there (given). Hotel California, listed
    # too, removed here and changed there: a conflict whose one side is a removal.
    by["song/radiohead/creep"].update(song("song/radiohead/creep", "Radiohead", "Creep", "mine", ("gone", None),
                                           listed=["songbook/campfire"]))
    by["song/eagles/hotel california"].update(song("song/eagles/hotel california", "Eagles", "Hotel California",
                                                   "conflict", ("gone", "changed"), listed=["songbook/campfire"]))
    assert by["song/radiohead/creep"]["here"] is None and by["song/eagles/hotel california"]["here"] is None
    # Wonderwall, newly listed there and here alone: it comes along (here has it, the sync brings it there).
    by["song/oasis/wonderwall"].update(song("song/oasis/wonderwall", "Oasis", "Wonderwall", "mine", ("new", None),
                                            listed=["songbook/campfire"]))
    fake = FakeSync(comparison=comparison)
    with opened(tmp_path, served(fake) + "#sheet=sync") as page:
        at_view(page, "what")
        assert page.wait("!document.getElementById('sync-go').disabled")
        # Every part: both removals counted, the conflict among them.
        assert page.js(COUNTS) == [["take", "4 to take"], ["give", "4 to give"], ["both", "1 changed on both"]]
        page.click(".sync-part[data-part=library] input")
        page.click(".sync-part[data-part=indexes] input")
        # Songbooks alone: its two songbooks taken and Wonderwall given; neither removal.
        assert page.js(COUNTS) == [["take", "2 to take"], ["give", "1 to give"], ["both", "0 changed on both"]]
        fake.auto = True
        page.click("#sync-go")
        at_view(page, "done", timeout=15)  # no card: the one conflict is out of these parts
        [form] = fake.awaited("/sync/apply")
        assert form["parts"] == ["songbooks"] and form["choices"] == [""]
        assert fake.gets("/api/sync/unit") == []
        assert "conflicts" not in [s["kind"] for s in page.js(SUMMARY)]


@in_chromium
def test_escape_while_the_sync_is_sent_hides_it_and_the_sync_is_followed_all_the_same(served, tmp_path):
    """The last card answered posts the sync at once: Escape before its answer comes only hides the sheet (as Hide
    does), and the sync queued is followed, its summary drawn from the cards it showed; opened again, the sheet shows
    that sync and never sends another."""
    fake = FakeSync()
    answered = fake.hold_on("/sync/apply")
    with opened(tmp_path, served(fake) + "#sheet=sync") as page:
        at_view(page, "what")
        assert page.wait("!document.getElementById('sync-go').disabled")
        page.click("#sync-go")
        at_card(page)
        page.click("#sync-same")
        page.click("#sync-keep-here")
        at_view(page, "going")
        fake.awaited("/sync/apply")  # it reached the server, whose answer waits
        page.press("Escape")
        assert page.wait(f"!{SHEET}.open")
        fake.auto = True
        answered.set()
        page.js("location.hash = '#sheet=sync'")
        at_view(page, "done", timeout=15)
        assert len(fake.posted("/sync/apply")) == 1 and len(fake.posted("/sync/compare")) == 1
        assert page.js("document.getElementById('sync-title').textContent") == "Synced with: Studio"
        conflicts = next(s for s in page.js(SUMMARY) if s["kind"] == "conflicts")
        assert conflicts["rows"][0] == ["Hotel California – Eagles", "this computer's version kept: its own key, A "
                                        "minor, capo 2, its sheet, UG · tab 1234567"]
        page.click("#sync-go")  # Done
        assert page.wait(f"!{SHEET}.open")
        # Over, a sync is a new one: the next opening compares afresh.
        page.js("location.hash = '#sheet=sync'")
        at_view(page, "what")
        assert page.wait("!document.getElementById('sync-counts').hidden")
        assert len(fake.posted("/sync/compare")) == 2 and len(fake.posted("/sync/apply")) == 1


@in_chromium
def test_a_refusal_says_the_servers_words_and_compares_again(served, tmp_path):
    from caracole.web import sync_routes

    fake = FakeSync()
    fake.refuse["/sync/apply"] = [(409, sync_routes.STALE)]
    with opened(tmp_path, served(fake) + "#sheet=sync") as page:
        at_view(page, "what")
        assert page.wait("!document.getElementById('sync-go').disabled")
        page.click("#sync-go")
        at_card(page)
        page.click("#sync-same")
        page.click("#sync-keep-there")
        at_view(page, "what")
        assert page.wait(f"{STATUS} === {json.dumps(sync_routes.STALE)} && "
                         "!document.getElementById('sync-go').disabled")
        assert page.js("document.getElementById('sync-status').dataset.tone") == "failed"
        assert len(fake.posted("/sync/compare")) == 2 and len(fake.posted("/sync/apply")) == 1
        # Compared again, the conflicts as they were keep their choices: Sync sends them, no card asked again.
        page.click("#sync-go")
        at_view(page, "going")
        assert fake.awaited("/sync/apply", 2)[1]["choices"] == [
            "there\tsong/eagles/hotel california\nthere\tsong/oasis/wonderwall"]
    # A refusal of the comparison itself: its words, and Compare again.
    fake = FakeSync()
    fake.refuse["/sync/compare"] = [(502, "The caracole at http://10.0.0.7:8737 can't be reached.")]
    with opened(tmp_path, served(fake) + "#sheet=sync") as page:
        at_view(page, "what")
        assert page.wait(f"{STATUS} === \"The caracole at http://10.0.0.7:8737 can't be reached.\"")
        assert page.js("document.getElementById('sync-go').textContent") == "Compare again"
        page.click("#sync-go")
        assert page.wait("!document.getElementById('sync-counts').hidden")
        assert page.js("document.getElementById('sync-go').textContent") == "Sync"


# --- following it, and what it did ------------------------------------------------------------------------------

def sync_through(page: Browser, fake: FakeSync, sides=("here", "there")) -> None:
    """Sync, each conflict answered in turn, and the job followed to its end."""
    at_view(page, "what")
    assert page.wait("!document.getElementById('sync-go').disabled")
    fake.auto = True
    page.click("#sync-go")
    for side in sides:
        at_card(page)
        before = page.js("document.getElementById('sync-card-at').textContent")
        assert page.wait("document.querySelector('#sync-card-here .sync-lines').dataset.state === ''")
        page.click(f"#sync-keep-{side}")
        assert page.wait(f"document.getElementById('sync-card-at').textContent !== {json.dumps(before)} || "
                         f"{SHEET}.dataset.view !== 'conflict'")
    at_view(page, "done", timeout=15)


@in_chromium
def test_the_summary_draws_each_kind_of_change_closed_and_opens_on_its_chevron(served, tmp_path):
    fake = FakeSync()
    with opened(tmp_path, served(fake) + "#sheet=sync") as page:
        sync_through(page, fake)
        assert page.js("document.getElementById('sync-title').textContent") == "Synced with: Studio"
        assert page.js("document.getElementById('sync-sub').textContent") == "03/11/26, 19:42"
        assert page.js("Array.from(document.querySelectorAll('#sync-devs .sync-dev')).map((d) => d.textContent)") == [
            "This computer", "Studio"]
        summary = page.js(SUMMARY)
        assert [(s["kind"], s["said"], s["way"]) for s in summary] == [
            ("taken", "3 songs taken", "left"), ("given", "1 song and 1 other change given", "right"),
            ("conflicts", "2 conflicts · mixed", "left right"), ("songbooks", "2 songbooks taken", "left"),
            ("indexes", "2 indexes taken · +12,130 tabs", "left")]
        assert all(s["open"] == "false" and s["hidden"] for s in summary)  # each starts closed
        assert [s["rows"] for s in summary] == [
            [["Let It Be – The Beatles"], ["Mononoke – Pomme"], ["Creep – Radiohead"]],
            [["Barbara Allen – Traditional", "added on this computer"],
             ["the alias of soda-stereo", "changed on this computer"]],
            [["Hotel California – Eagles", "this computer's version kept: its own key, A minor, capo 2, its sheet, "
                                           "UG · tab 1234567"],
             ["Wonderwall – Oasis", "Studio's version kept: its lyrics, found"]],
            [["Campfire", "3 songs added"], ["Wedding set", "12 songs"]],
            [["Ultimate Guitar · ", "+12,340 tabs", "1,503,236 → 1,515,576 tabs tracked · read by Studio on 03/11/26"],
             ["LaCuerda · ", "−210 tabs", "23,105 → 22,895 tabs tracked · its listings no longer name them, so they "
                                         "would not have opened · read by Studio on 02/11/26"]]]
        page.click(".sync-section[data-kind=indexes] .sync-lane")
        assert page.js(SUMMARY)[4]["open"] == "true" and page.js(SUMMARY)[4]["hidden"] is False
        assert page.js("document.querySelector('.sync-section[data-kind=taken] .sync-rows').hidden") is True
        # The name the only bold text of the summary (Done, a button, aside).
        bold = page.js("""Array.from(document.querySelectorAll('#sync-sheet .sync-top *, #sync-done *'))
          .filter((n) => n.checkVisibility() && Array.from(n.childNodes).some((c) => c.nodeType === 3 && c.textContent.trim())
            && Number(getComputedStyle(n).fontWeight) >= 600).map((n) => n.textContent)""")
        assert bold == ["Studio"]
        assert page.js("document.getElementById('sync-go').textContent") == "Done"
        assert page.js("document.getElementById('sync-file-note').hidden") is True
        page.click("#sync-go")
        assert page.wait(f"!{SHEET}.open")


@in_chromium
def test_an_index_that_fell_is_red_and_says_why(served, tmp_path):
    fake = FakeSync(state=PHONE_STATE, views=PHONE_VIEWS)
    with opened(tmp_path, served(fake, sync="sheet") + "#sheet=sync", width=390, height=844, mobile=True) as page:
        sync_through(page, fake)
        page.click(".sync-section[data-kind=indexes] .sync-lane")
        rows = page.js(SUMMARY)[4]["rows"]
        assert rows[1] == ["LaCuerda · ", "−210 tabs", "23,105 → 22,895 tabs tracked · its listings no longer name them, "
                                                      "so they would not have opened · read by the computer on 02/11/26"]
        colours = page.js("""['.sync-up', '.sync-down', '.sync-section[data-kind=indexes]'].map((s) =>
          getComputedStyle(document.querySelector('#sync-done ' + s)).color)""")
        found, failed = page.js("['--found', '--failed'].map((v) => { const p = document.createElement('p');"
                                " p.style.color = 'var(' + v + ')'; document.body.append(p);"
                                " const c = getComputedStyle(p).color; p.remove(); return c; })")
        assert colours[:2] == [found, failed] and colours[2] not in (found, failed)
        assert page.js("Array.from(document.querySelectorAll('#sync-devs .sync-dev')).map((d) => d.textContent)") == [
            "Phone", "Computer"]


@in_chromium
def test_a_sync_on_its_way_as_the_page_loads_is_followed_to_its_summary(served, tmp_path):
    fake = FakeSync(state=PHONE_STATE, views=PHONE_VIEWS)
    fake.at = 1
    url = served(fake, sync="sheet", jobs=(VIEWS[1],)) + "#sheet=sync"
    with opened(tmp_path, url, width=390, height=844, mobile=True) as page:
        at_view(page, "going")
        assert page.js("document.getElementById('sync-going-line').textContent") == "Taking their entries…"
        assert page.js("document.getElementById('sync-title').textContent") == "Syncing with Studio"
        assert page.js(CHIPS) == [["Compared", "done"], ["Your choice", "done"], ["Library", "now"],
                                  ["Songbooks", "now"], ["Indexes", ""]]
        # Hidden, it goes on; opened again, it is that sync, never another.
        page.click("#sync-go")
        assert page.wait(f"!{SHEET}.open")
        page.js("location.hash = '#sheet=sync'")
        at_view(page, "going")
        fake.at = 3
        at_view(page, "done", timeout=15)
        assert fake.posted("/sync/compare") == [] and fake.posted("/sync/apply") == []
        assert page.js("document.getElementById('sync-title').textContent") == "Synced with: Studio"
        summary = page.js(SUMMARY)
        assert [(s["kind"], s["said"]) for s in summary] == [
            ("taken", "4 songs taken"), ("given", "2 songs and 1 other change given"), ("songbooks", "2 songbooks taken"),
            ("indexes", "2 indexes taken · +12,130 tabs")]
        # Names from the library's own cards where it has them, else the song's key.
        assert summary[0]["rows"][0] == ["let it be – the beatles"]


@in_chromium
def test_a_report_missing_draws_the_summary_from_the_outcome_alone(served, tmp_path):
    over = sync_view("done", {"compare": ("done", "9 differences"), "take": ("done", "took 6"),
                              "give": ("done", "gave 3"), "agree": ("done", "312 units the two agree on")}, TAKEN_GIVEN)
    assert "report" not in over["outcome"]
    fake = FakeSync(views=VIEWS[:-1] + [over])
    with opened(tmp_path, served(fake) + "#sheet=sync") as page:
        sync_through(page, fake)
        assert page.js("document.getElementById('sync-title').textContent") == "Synced with: Studio"
        assert [s["kind"] for s in page.js(SUMMARY)] == ["taken", "given", "conflicts", "songbooks"]  # no indexes
        assert re.fullmatch(r"\d\d/\d\d/\d\d, \d\d:\d\d", page.js("document.getElementById('sync-sub').textContent"))


# What the sheet shows at a width: what to sync, a card, then what it did, every section open; how wide it got and
# its controls short of a thumb's size, at each.
DRIVEN = """
(() => {
  const later = (test, then) => (test() ? then() : setTimeout(() => later(test, then), 50));
  const sheet = document.getElementById("sync-sheet");
  const measure = (name) => document.body.setAttribute("data-" + name, JSON.stringify({
    wide: document.documentElement.scrollWidth, sheet: Math.round(sheet.getBoundingClientRect().right),
    short: __SHORT__, weak: __WEAK__ }));
  later(() => document.readyState === "complete", () => {
    location.hash = "#sheet=sync";
    later(() => sheet.open && !document.getElementById("sync-counts").hidden, () => {
      measure("what");
      document.getElementById("sync-go").click();
      later(() => sheet.dataset.view === "conflict" && document.querySelector("#sync-card-here .sync-lines")
        .dataset.state === "", () => {
        measure("card");
        document.getElementById("sync-same").click();
        document.getElementById("sync-keep-here").click();
        later(() => sheet.dataset.view === "done", () => {
          for (const b of document.querySelectorAll(".sync-lane")) b.click();
          measure("done");
        });
      });
    });
  });
})();
"""


@pytest.mark.parametrize("width", [390, 1280])
@in_chromium
def test_the_sheet_fits_a_phone_and_a_laptop_in_light_and_dark(served, width):
    fake = FakeSync()
    fake.auto = True
    phone = width < 500
    behind = ":not(#sync-sheet *)"  # the page under the sheet, which a modal sheet leaves out of reach
    url = served(fake, DRIVEN.replace("__SHORT__", small_targets(behind)).replace("__WEAK__", weak_edges(behind)),
                 sync="sheet" if phone else "tab")
    for scheme in ("light", "dark"):
        fake.at = 0
        dom = browser.dump_dom(url, (width, 844), mobile=phone, touch=phone, media={"prefers-color-scheme": scheme},
                               budget_ms=20000)
        for step in ("what", "card", "done"):
            seen = noted(dom, "data-" + step)
            assert seen["wide"] <= width and seen["sheet"] <= width, (scheme, step, seen)
            assert seen["weak"] == [], (scheme, step, seen["weak"])
            if phone:  # on a touch screen every control is a thumb's size
                assert seen["short"] == [], (scheme, step, seen["short"])


# --- export and import ------------------------------------------------------------------------------------------

@in_chromium
def test_export_offers_the_parts_with_their_sizes_indexes_unticked_and_downloads_the_file(served, tmp_path):
    fake = FakeSync()
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    with opened(tmp_path, served(fake) + "#tab=sync") as page:
        page._send("Browser.setDownloadBehavior", behavior="allow", downloadPath=str(downloads))
        page.click("#sync-export")
        at_view(page, "what")
        assert page.wait("!document.getElementById('sync-go').disabled")
        assert page.js("[document.getElementById('sync-title').textContent, "
                       "document.getElementById('sync-sub').textContent]") == ["Export this library",
                                                                               "Laptop · 111 songs · 03/11/26"]
        assert page.js(PARTS_SAID) == [["Library · Your songs, their sheets and pages · 34 MB", True, False],
                                       ["Songbooks · 2 songbooks", True, False],
                                       ["Site indexes · For searching offline · 207 MB", False, False]]
        assert page.js("document.getElementById('sync-counts').hidden && document.getElementById('sync-chips').hidden")
        assert page.js("document.getElementById('sync-go').textContent") == "Export"
        page.click("#sync-go")
        link = "document.querySelector('#sync-status a[download]')"
        assert page.wait(f"{link} !== null")
        assert fake.posted("/sync/export") == [{"parts": ["library", "songbooks"]}]
        assert page.js(f"[{link}.getAttribute('href'), {link}.getAttribute('download')]") == [
            "api/sync/export?export=0123456789abcdef", "Laptop-03-11-26.caracole"]
        assert page.js(STATUS) == "Made Laptop-03-11-26.caracole · 34 MB"
        assert _saved(downloads) == ["Laptop-03-11-26.caracole"]
        assert fake.gets("/api/sync/export") == ["/api/sync/export?export=0123456789abcdef"]  # once
        assert page.js("document.getElementById('sync-go').textContent") == "Done"
        # caracole serve sends it once: clicked again, the link says so, and asks nothing.
        page.click("#sync-status a[download]")
        assert page.wait(f"{STATUS}.endsWith('sent once already: Export again for another copy')")
        assert len(fake.gets("/api/sync/export")) == 1 and _saved(downloads) == ["Laptop-03-11-26.caracole"]
        page.click("#sync-go")
        assert page.wait(f"!{SHEET}.open")
        # The indexes' size unknown: their tabs instead; neither library nor songbooks: no export.
        fake.sizes["indexes"] = None
        page.click("#sync-export")
        assert page.wait("document.querySelector('.sync-part[data-part=indexes] .sync-part-said').textContent === "
                         "'For searching offline · 1,515,576 tabs'")
        page.click(".sync-part[data-part=library] input")
        page.click(".sync-part[data-part=songbooks] input")
        page.click(".sync-part[data-part=indexes] input")
        assert page.js("document.getElementById('sync-go').disabled") is True


def _saved(folder, timeout: float = 10.0) -> list[str]:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        names = sorted(p.name for p in folder.iterdir() if not p.name.endswith(".crdownload"))
        if names:
            return names
        time.sleep(0.05)
    return []


def choose_file(page: Browser, path) -> None:
    """A file picked in #sync-file, as the browser's chooser picks one."""
    root = page.send("DOM.getDocument")["root"]["nodeId"]
    node = page.send("DOM.querySelector", nodeId=root, selector="#sync-file")["nodeId"]
    page.send("DOM.setFileInputFiles", files=[str(path)], nodeId=node)


@in_chromium
def test_import_sends_the_file_in_parts_then_syncs_as_with_a_file_with_no_arrow_out(served, tmp_path):
    file_views = [sync_view(v["state"], {s["name"]: (s["state"], s["detail"]) for s in v.get("steps", [])}, name="a file "
                            "from Phone") for v in VIEWS[:-1]]
    file_views.append(sync_view("done", {"compare": ("done", "6 differences"), "take": ("done", "took 6"),
                                         "agree": ("done", "300 units the two agree on")},
                                [u for u in TAKEN_GIVEN if u[1] == "taken"] + [("song/eagles/hotel california", "left",
                                                                                "kept here")], FILE_REPORT))
    fake = FakeSync(views=file_views)
    picked = tmp_path / "Phone-03-11-26.caracole"
    picked.write_bytes(bytes(range(256)) * (20 * MIB // 256))
    with opened(tmp_path, served(fake) + "#tab=sync") as page:
        assert page.wait("document.getElementById('sync-address').value !== ''")
        choose_file(page, picked)
        at_view(page, "what")
        assert page.wait("!document.getElementById('sync-counts').hidden", 20)
        assert fake.posted("/sync/import/open") == [{"size": 20 * MIB, "name": "Phone-03-11-26.caracole"}]
        assert fake.posted("/sync/import/part") == [{"at": 0, "size": 8 * MIB, "import": "fedcba9876543210"},
                                                    {"at": 8 * MIB, "size": 8 * MIB, "import": "fedcba9876543210"},
                                                    {"at": 16 * MIB, "size": 4 * MIB, "import": "fedcba9876543210"}]
        assert bytes(fake.received) == picked.read_bytes()
        assert fake.posted("/sync/import/compare") == [{"csrf": ["tok"], "import": ["fedcba9876543210"]}]
        assert page.js("document.getElementById('sync-title').textContent") == "Sync with a file from Phone"
        assert page.js("document.querySelector('#sync-title .sync-name').textContent") == "Phone"
        assert page.js("document.getElementById('sync-sub').textContent").startswith(
            "Phone-03-11-26.caracole · exported 03/11/26, 21:10")
        assert page.js(PARTS_SAID) == [
            ["Library · Its songs, sheets and pages · it takes nothing back · 5 changed in the file", True, False],
            ["Songbooks · Its songbooks and their set lists · 2 changed in the file", True, False],
            ["Site indexes · Not in this file", False, True]]
        assert page.js(COUNTS) == [["take", "5 to take"], ["both", "2 changed on both"]]  # no arrow out
        assert page.js(CHIPS) == [["Compared", "done"], ["Your choice", ""], ["Library", ""], ["Songbooks", ""]]
        fake.auto = True
        page.click("#sync-go")
        at_card(page)
        assert page.js(CARD)["heads"] == ["On this computer", "In the file"]
        assert page.js(CARD)["keep"] == ["This computer", "File"]
        page.click("#sync-same")
        page.click("#sync-keep-here")
        at_view(page, "done", timeout=15)
        assert fake.posted("/sync/apply")[0]["parts"] == ["library,songbooks"]
        assert page.js("document.getElementById('sync-title').textContent") == "Synced with: Phone"
        summary = page.js(SUMMARY)
        assert [s["kind"] for s in summary] == ["taken", "conflicts", "songbooks", "left"]  # nothing given
        # A conflict it left as it was (changed since) is no conflict settled: said with why, apart.
        assert (summary[1]["said"], summary[1]["way"]) == ("1 conflict · this computer's kept", "left")
        assert summary[3]["said"] == "1 change left as it was"
        assert summary[3]["rows"] == [["Hotel California – Eagles", "kept here"]]
        assert page.js("Array.from(document.querySelectorAll('#sync-devs .sync-dev')).map((d) => d.textContent)") == [
            "This computer", "File"]
        assert page.js("document.getElementById('sync-file-note').hidden") is False
        assert page.js("document.getElementById('sync-file-note').textContent").split() == (
            'A file takes nothing back: no "given" arrow. To give your changes, export a file of your own.'.split())


@in_chromium
def test_a_file_cancelled_left_or_refused_is_let_go_so_the_next_one_is_sent_at_once(served, tmp_path):
    """caracole serve stages one import at a time: a file cancelled while it is sent, or whose sheet is closed after
    its comparison, is dropped at once (POST /sync/import/drop), and one refused at its comparison is deleted there,
    so that the next file chosen is sent right after, with no hour to wait."""
    from caracole.peer_file import OLDER

    fake = FakeSync()
    big, small = tmp_path / "Phone-03-11-26.caracole", tmp_path / "Phone-04-11-26.caracole"
    big.write_bytes(bytes(range(256)) * (20 * MIB // 256))
    small.write_bytes(b"PK\x03\x04 a small file")
    first = fake.hold_on("/sync/import/part")
    with opened(tmp_path, served(fake) + "#sheet=import") as page:
        at_view(page, "what")
        choose_file(page, big)
        fake.awaited("/sync/import/part")  # its first part on its way
        page.click("#sync-cancel")
        assert page.wait(f"!{SHEET}.open")
        assert fake.awaited("/sync/import/drop") == [{"import": "fedcba9876543210"}]
        first.set()
        # The next file, at once; then the sheet closed after its comparison, never synced: dropped too.
        for n, shut in ((1, "#sync-cancel"), (2, None)):
            page.js("location.hash = '#sheet=import'")
            at_view(page, "what")
            choose_file(page, small)
            assert page.wait("!document.getElementById('sync-counts').hidden", 20), page.js(STATUS)
            if shut:
                page.click(shut)
                assert page.wait(f"!{SHEET}.open")
                assert fake.awaited("/sync/import/drop", 2)[1] == {"import": format(0xfedcba9876543210 - n, "016x")}
            else:
                page.press("Escape")
                assert page.wait(f"!{SHEET}.open")
                assert len(fake.awaited("/sync/import/drop", 3)) == 3
        # A file refused at its comparison is deleted there: the next one is sent right after.
        older = OLDER.format(name="horde_logbook", day="03/11/26")
        fake.refuse["/sync/import/compare"] = [(409, older)]
        page.js("location.hash = '#sheet=import'")
        at_view(page, "what")
        choose_file(page, small)
        assert page.wait(f"{STATUS} === {json.dumps(older)}")
        choose_file(page, small)
        assert page.wait("!document.getElementById('sync-counts').hidden", 20), page.js(STATUS)
        assert len(fake.posted("/sync/import/open")) == 5 and fake.posted("/sync/apply") == []


@in_chromium
def test_a_file_refused_says_its_words(served, tmp_path):
    older = "Nothing in this file is newer than your sync with horde_logbook on 03/11/26."
    fake = FakeSync()
    fake.refuse["/sync/import/compare"] = [(409, older)]
    picked = tmp_path / "horde_logbook-01-11-26.caracole"
    picked.write_bytes(b"PK\x03\x04 an old file")
    with opened(tmp_path, served(fake, sync="sheet") + "#sheet=import", width=390, height=844, mobile=True) as page:
        at_view(page, "what")
        assert page.js("[document.getElementById('sync-title').textContent, document.getElementById('sync-sub')"
                       ".textContent, document.getElementById('sync-go').textContent]") == [
            "Import a file", "A file a phone or a server exported, synced as if its caracole were here", "Choose a file"]
        assert page.js("document.getElementById('sync-parts').hidden") is True
        choose_file(page, picked)
        assert page.wait(f"{STATUS} === {json.dumps(older)}")
        assert page.js("document.getElementById('sync-status').dataset.tone") == "failed"
        assert page.js("document.getElementById('sync-go').textContent") == "Choose a file"
        assert fake.posted("/sync/apply") == []


@in_chromium
def test_the_phones_settings_open_the_sheet_at_export_and_import_by_its_address(served, tmp_path):
    fake = FakeSync(state=PHONE_STATE)
    fake.sizes = dict(SIZES, name="Phone")
    url = served(fake, sync="sheet")
    with opened(tmp_path, url + "#sheet=export", width=390, height=844, mobile=True) as page:
        at_view(page, "what")
        assert page.wait("document.getElementById('sync-sub').textContent === 'Phone · 111 songs · 03/11/26'")
        assert page.js("document.getElementById('sync-title').textContent") == "Export this library"
        assert page.js("location.hash") in ("", "#")
        page.click("#sync-cancel")
        # The Settings' Import a file loads the page at its address: the sheet at Import.
        page.js("location.hash = '#sheet=import'")
        assert page.wait("document.getElementById('sync-title').textContent === 'Import a file'")
        assert page.js("location.hash") in ("", "#")
        page.click("#sync-cancel")
        # Compare again in the Requests tab leads to #tab=sync, which on the phone is the sheet.
        page.js("(() => { const a = document.createElement('a'); a.id = 'again'; a.href = '/#tab=sync';"
                " a.textContent = 'Compare again'; document.getElementById('list').prepend(a); })()")
        page.click("#again")
        at_view(page, "what")
        assert page.wait("document.getElementById('sync-title').textContent === 'Sync with Studio'")
    # Loaded at #tab=sync (the phone has no Sync tab): the sheet all the same.
    with opened(tmp_path, url + "#tab=sync", width=390, height=844, mobile=True) as page:
        at_view(page, "what")
        assert page.js("document.querySelector('[role=tab][aria-selected=true]').id") == "tab-library"
