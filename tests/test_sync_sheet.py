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
from helpers.targets import noted, noting, small_targets

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
           "conflict": "changed on both sides since the last sync"}[proposal]
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
    difference("songbook/campfire", "the songbook Campfire", "theirs", "changed there since the last sync",
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
    export's and the import's (``sizes``, ``exported``, ``file_comparison``, ``file_views``). ``refuse[path]`` holds
    refusals (status, words), each answered once in its turn. It records what the page asked (``asked``: each GET's
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
        self.lock = threading.Lock()

    def posted(self, path: str) -> list:
        with self.lock:
            return [body for where, body in self.posts if where == path]

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
                if path == "/api/sync/unit":
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
                if token != "tok":
                    return answer(403, {"error": "Refused", "reload": True})
                refused = self._refused(path)
                if refused is not None:
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
                        self.size = int(body["size"])
                    return answer(200, {"import": "fedcba9876543210", "part": 8 * MIB})
                if path == "/sync/import/part":
                    with self.lock:
                        if body["at"] != len(self.received):
                            return answer(400, {"error": "That part isn't the next one."})
                        self.received.extend(request.body)
                        have = len(self.received)
                    return answer(200, {"have": have})
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

    def start(fake: FakeSync, script: str = "", *, sync: str = "tab", jobs: tuple[dict, ...] = ()) -> str:
        real = library_page.build_library_page

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
@pytest.mark.parametrize("sync", ["tab", "sheet"])
def test_on_a_phone_the_tabs_stay_one_row_unsplit(served, sync):
    url = served(FakeSync(), noting("data-tabs", TABS) + noting("data-wide", "document.documentElement.scrollWidth"),
                 sync=sync)
    dom = browser.dump_dom(url, (390, 844), mobile=True, touch=True)
    tabs = noted(dom, "data-tabs")
    names = ["tab-library", "tab-songbooks", "tab-sites", "tab-requests"] + (["tab-sync"] if sync == "tab" else [])
    assert [t[0] for t in tabs] == names
    assert len({top for *_, top in tabs}) == 1, tabs
    assert all(0 <= b[1] - a[2] <= 8 for a, b in zip(tabs, tabs[1:])), tabs  # one row, none pushed aside
    assert noted(dom, "data-wide") <= 390


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
