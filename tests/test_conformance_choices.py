"""A sheet's versions and a harmonica tab's readings, chosen on the phone: what android/server's ``VersionsRoutes``,
``HarmonicaRoutes`` and ``HarmonicaRunner`` (lane versions-harmonica) answer, written for ``ChoicesReplay`` to agree
with. Each is caracole serve's own: web/versions_routes.py, web/harmonica_routes.py and ``caracole harmonica``
(commands/harmonica.py, harmonica_cmd.py).

**The scenes.** Each is a library in a fresh database, dumped whole into a ``fixture`` record of its file
(``helpers.corpus.dump_fixture``, overrides.toml as the phone's ``phone_overrides`` rows,
``test_conformance_overrides.rows_of``), which the replay loads into a database of its own; every record after it
names the scene it asks over. The viewers a song has are kv ``render:files:<id>``'s records alone (render.py's
``_note_written``): no route reads a viewer's bytes.

- versions_routes.jsonl's ``base``: De Música Ligera, its sheet Ultimate Guitar's Ver 1, Ver 2 kept beside it (its
  page written) with the tabber's note, Ver 3 not kept, Ver 4 gone from UG, Ver 5 under ``[block]``, and a ``[pin]``
  of a text tab (no pin of its sheet); Tren al Sur, LaCuerda's sheet, two chords versions on UG and a ``[pin]`` of one
  of them, which chooses its sheet; Eres, ignored; Mariposa Tecknicolor, an auto sheet; Demoliendo Hoteles, no sheet
  at all. ``chosen``: Ver 2 became the one (its page gone, its pin recorded); ``kept``: Ver 3 kept beside the sheet
  too; ``pinned``: a ``[pin]`` of Ver 3 recorded, the sheet still Ver 1; ``unpinned``: Tren al Sur's pin gone.
- harmonica_routes.jsonl's ``spokey``: Spokey Dokey, harmonica-1.txt a tab with its own legend (its page written),
  harmonica-2.txt a tab of signs with a bend changed, harptabs.com's chip Diatonic, harmonica-3.txt one of chip
  Chromatic, harmonica-4.txt kept but its file gone, a page harmonica-5.html written of no tab kept; Eres, ignored,
  its tab and page. ``letters``, ``table``, ``signs``: harmonica-1.txt pinned so; ``legend``: harmonica-2.txt pinned
  by a legend it hasn't got.

**Records**, after the header and the fixtures:

- ``{"fn": "GET /versions" | "GET /harmonica", "scene", "case", "target", "job", "out"}``: the page of ``target``
  (``versions_page``, ``harmonica_page``), with ``job`` the request it names (``&job=``) as the phone holds it
  (JobViewsReplay.jobOf's shape: title, key, kind, display, fetching, note, its stages and commands each with its
  state, detail and output), or null; ``out`` the refusal, ``{status, title, message}``, or ``{status, page}``, the
  page's HTML with its stylesheet's text taken out (``<style></style>``: the message pages' own,
  message.json's). Pages name the library as the phone's do (``LibraryName("", "Phone")``) and carry the form token
  ``tok``.
- ``{"fn": "POST /versions/<do>" | "POST /harmonica/<do>", "scene", "case", "before", "form", "out"}``: ``form``
  posted (``versions_post``, ``harmonica_post``) to a fresh queue that runs nothing, after the posts ``before``
  (each ``[path, form]``); ``out`` the refusal, or ``{status, location, job: {title, key, steps, fetching, display,
  song_id}, jobs}``, its job and how many the queue holds.
- ``{"fn": "caracole harmonica", "scene", "case", "args", "out": {code, lines, error, rendered, harmonica}}``: the
  command run over the scene (``caracole harmonica ARGS``, its pages' render stood in for: ``rendered``, whether it
  rendered the song again), its exit code, what it printed, the error it failed with (or null), and overrides.toml's
  ``[harmonica]`` after it, by song key and tab.

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_choices.py``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import urlencode

import pytest
import typer
from helpers.corpus import FIXTURES, VECTORS, check, dump_fixture, jsonl

from caracole import db
from caracole.web.pages import Refused

MADE_BY = "tests/test_conformance_choices.py"
VERSIONS = VECTORS / "web" / "versions_routes.jsonl"
HARMONICA = VECTORS / "web" / "harmonica_routes.jsonl"
STAMP = "2026-11-03T10:00:00Z"
CSRF = "tok"

FOLDER = "Soda Stereo/De Música Ligera"
SHEET = f"{FOLDER}/sheet.html"
ONE, KEPT, OTHER, GONE, BLOCKED, TEXT_TAB = "1001", "39144", "1064463", "777", "5555", "1009"
SLUGGED = "https://tabs.ultimate-guitar.com/tab/soda-stereo/de-musica-ligera-chords-{}"
TREN = "Los Prisioneros/Tren al Sur"
TREN_TABS = ("2001", "2002")
ERES = "Café Tacvba/Eres"
MARIPOSA = "Fito Páez/Mariposa Tecknicolor"

SPOKEY_FOLDER = "Cowboy Bebop/Spokey Dokey"
SPOKEY_PAGE = f"{SPOKEY_FOLDER}/harmonica-1.html"
SPOKEY = (FIXTURES / "harptabs" / "legends" / "693_spokey-dokey.txt").read_text("utf-8")
SPOKEY_DISPLAY = "Cowboy Bebop - Spokey Dokey"
BENT = "-1 -2 -3* -3*\nla la la la\n"
CHROMATIC = "Intro\n4 -4 5 -5 6 -6 7\n-7 7 -6 6 -5 5 4\n"


# --- a library ------------------------------------------------------------------------------------------------------


@contextmanager
def _library(tmp: Path) -> Iterator[tuple[Any, Any]]:
    """A config over ``tmp`` (its data_dir, written as caracole.toml for the command) and its fresh database."""
    from caracole.config import load_config

    tmp.mkdir(parents=True, exist_ok=True)
    config = tmp / "caracole.toml"
    config.write_text(f'data_dir = "{tmp}"\n', encoding="utf-8")
    cfg = load_config(config, env={"HOME": str(tmp / "home")})
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    with closing(db.connect(cfg.db_path)) as conn:
        yield cfg, conn


def _song(conn, artist: str, title: str, n: int):
    from conftest import add_song

    return add_song(conn, artist, title, added_at=f"2026-10-02T00:{n:02d}:00Z")


def _ug(conn, song, tab: str, *, number: int, rating: float, votes: int, kind: str = "chords",
        coverage: float | None = None, note: str | None = None, slot: str = "sheet") -> int:
    from caracole.versions import set_coverage, upsert_version

    raw: dict[str, Any] = {"id": int(tab)}
    if note:
        raw["version_description"] = note
    vid = upsert_version(conn, provider="ug", tab_id=tab, song_id=song.id, slot=slot, kind=kind, rating=rating,
                         votes=votes, version=number, label=None, url=SLUGGED.format(tab), raw=raw, now=STAMP)
    if coverage is not None:
        set_coverage(conn, vid, coverage)
    return vid


def _keep(conn, cfg, song, vid: int, name: str, data: bytes, rank: int = 1) -> None:
    from caracole.library import keep_file

    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name=name, data=data, rank=rank)


def _written(conn, song, name: str) -> None:
    """The viewer ``name`` recorded as caracole wrote it in the song's folder (no file: no route reads one)."""
    from caracole.render import _note_written

    _note_written(conn, song.id, name, f"<!doctype html>{name}".encode())


def _settled(conn) -> None:
    """Every time the library holds, the scenes' own: the same on every run."""
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (STAMP, STAMP))
    conn.execute("UPDATE files SET created_at = ?", (STAMP,))


def _phone_overrides(conn, cfg) -> None:
    """overrides.toml as the phone holds it: its rows, in place of any before."""
    from test_conformance_overrides import rows_of

    conn.execute("DELETE FROM phone_overrides")
    for row in rows_of(cfg.overrides_file):
        conn.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)",
                     (row["tbl"], row["key"], row["written"], row["value"]))


def _fixture(conn, cfg, scene: str, *, files: bool) -> dict[str, Any]:
    from helpers.corpus import phone_schema

    if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'phone_overrides'").fetchone() is None:
        phone_schema(conn)
    _phone_overrides(conn, cfg)
    records = dump_fixture(conn, cfg.library_dir if files else None)
    return {"fn": "fixture", "scene": scene, "records": [r for r in records if r.get("file") != "overrides.toml"]}


def _app(cfg):
    from caracole.library_name import LibraryName
    from caracole.web.app import WebApp
    from caracole.web.jobs import JobQueue

    def runner(args, emit):  # nothing runs: the queue is never started
        raise AssertionError(f"a route ran {args}")

    app = WebApp(cfg, JobQueue(runner, limit=20), allowed=frozenset({"localhost"}), csrf=CSRF,
                 searches_lacuerda=False, searches_youtube=False)
    app.library_name = LibraryName("", "Phone")  # as the phone's pages name it before a sync gave a name
    return app


# --- the versions' scenes -------------------------------------------------------------------------------------------


def build_versions(conn, cfg) -> dict[str, Any]:
    """The base scene; the songs by title."""
    from caracole.overrides import add_block, add_ignore, add_pin
    from caracole.sheet_versions import version_names
    from caracole.versions import mark_gone, upsert_version

    songs = {}
    ligera = songs["De Música Ligera"] = _song(conn, "Soda Stereo", "De Música Ligera", 0)
    one = _ug(conn, ligera, ONE, number=1, rating=4.9, votes=5021, coverage=0.95)
    _keep(conn, cfg, ligera, one, "sheet.txt", b"[G]De musica ligera\n")
    kept = _ug(conn, ligera, KEPT, number=2, rating=4.85, votes=12629, coverage=0.9,
               note="the version they play\n  live in 2007")
    _ug(conn, ligera, OTHER, number=3, rating=4.86, votes=408)
    mark_gone(conn, _ug(conn, ligera, GONE, number=4, rating=4.0, votes=3))
    _ug(conn, ligera, BLOCKED, number=5, rating=3.25, votes=1_234_567)
    _ug(conn, ligera, TEXT_TAB, number=1, rating=4.5, votes=80, kind="tabs", slot="guitar")
    txt, data, page = version_names(KEPT)
    _keep(conn, cfg, ligera, kept, txt, f"[G]Otra {KEPT}\n".encode(), rank=2)
    _keep(conn, cfg, ligera, kept, data, b"{}", rank=2)
    _written(conn, ligera, "sheet.html")
    _written(conn, ligera, page)

    tren = songs["Tren al Sur"] = _song(conn, "Los Prisioneros", "Tren al Sur", 1)
    lacuerda = upsert_version(conn, provider="lacuerda", tab_id="los_prisioneros/tren_al_sur", song_id=tren.id,
                              slot="sheet", kind="chords", rating=None, votes=None, version=None, label=None,
                              url="https://acordes.lacuerda.net/los_prisioneros/tren_al_sur", raw={}, now=STAMP)
    _keep(conn, cfg, tren, lacuerda, "sheet.txt", b"[Am]Tren\n")
    for n, tab in enumerate(TREN_TABS, 1):
        _ug(conn, tren, tab, number=n, rating=4.0 + n / 10, votes=100 * n)
    _written(conn, tren, "sheet.html")

    eres = songs["Eres"] = _song(conn, "Café Tacvba", "Eres", 2)
    sheet = _ug(conn, eres, "3001", number=1, rating=4.7, votes=900)
    _keep(conn, cfg, eres, sheet, "sheet.txt", b"[C]Eres\n")
    _ug(conn, eres, "3002", number=2, rating=4.6, votes=300)
    _written(conn, eres, "sheet.html")

    mariposa = songs["Mariposa Tecknicolor"] = _song(conn, "Fito Páez", "Mariposa Tecknicolor", 3)
    auto = upsert_version(conn, provider="auto", tab_id="btc", song_id=mariposa.id, slot="sheet", kind="chords",
                          rating=None, votes=None, version=None, label=None, url="", raw={}, now=STAMP)
    _keep(conn, cfg, mariposa, auto, "sheet (auto).txt", b"auto-generated, unverified\n[D]Mariposa\n")
    _ug(conn, mariposa, "4001", number=1, rating=4.2, votes=50)
    _written(conn, mariposa, "sheet (auto).html")

    hoteles = songs["Demoliendo Hoteles"] = _song(conn, "Charly García", "Demoliendo Hoteles", 4)
    _ug(conn, hoteles, "5001", number=1, rating=4.4, votes=77)

    add_block(cfg.overrides_file, int(BLOCKED))
    add_pin(cfg.overrides_file, ligera.display, [SLUGGED.format(TEXT_TAB)])
    add_pin(cfg.overrides_file, tren.display, [SLUGGED.format(TREN_TABS[1])])
    add_ignore(cfg.overrides_file, eres.display)
    _settled(conn)
    from caracole.songs import get_song

    return {title: get_song(conn, s.id) for title, s in songs.items()}


def to_chosen(conn, cfg, songs) -> None:
    """Ver 2 is the one now: kept as sheet.txt, its files beside the sheet and its page gone, its [pin] recorded."""
    from caracole.overrides import add_pin
    from caracole.render import _forget_written
    from caracole.sheet_versions import version_names

    ligera = songs["De Música Ligera"]
    vid = conn.execute("SELECT id FROM versions WHERE provider = 'ug' AND tab_id = ?", (KEPT,)).fetchone()[0]
    txt, data, page = version_names(KEPT)
    conn.execute("DELETE FROM files WHERE song_id = ? AND name IN (?, ?)", (ligera.id, txt, data))
    conn.execute("UPDATE files SET version_id = ? WHERE song_id = ? AND name = 'sheet.txt'", (vid, ligera.id))
    _forget_written(conn, ligera.id, (page,))
    add_pin(cfg.overrides_file, ligera.display, [SLUGGED.format(TEXT_TAB), SLUGGED.format(KEPT)])
    _settled(conn)


def to_kept(conn, cfg, songs) -> None:
    """Ver 3 kept beside the sheet too, its page written."""
    from caracole.sheet_versions import version_names

    ligera = songs["De Música Ligera"]
    vid = conn.execute("SELECT id FROM versions WHERE provider = 'ug' AND tab_id = ?", (OTHER,)).fetchone()[0]
    txt, data, page = version_names(OTHER)
    _keep(conn, cfg, ligera, vid, txt, f"[G]Otra {OTHER}\n".encode(), rank=3)
    _keep(conn, cfg, ligera, vid, data, b"{}", rank=3)
    _written(conn, ligera, page)
    _settled(conn)


def to_pinned(conn, cfg, songs) -> None:
    """A [pin] of Ver 3 recorded, the sheet still Ver 1 (the lookup made it no sheet)."""
    from caracole.overrides import add_pin

    add_pin(cfg.overrides_file, songs["De Música Ligera"].display,
            [SLUGGED.format(TEXT_TAB), SLUGGED.format(OTHER)])


def to_unpinned(conn, cfg, songs) -> None:
    """Tren al Sur's pin taken out."""
    from caracole.overrides import remove_pin

    remove_pin(cfg.overrides_file, songs["Tren al Sur"].display)


# --- jobs as the phone holds them ------------------------------------------------------------------------------------


STEP_STATES = {"queued": "waiting", "running": "running", "done": "done", "failed": "failed",
               "cancelled": "skipped", "interrupted": "interrupted"}


def _hold(app, job_id: int, state: str, *, stages: dict[str, tuple[str, str]] | None = None,
          output: tuple[str, ...] = ()) -> dict[str, Any]:
    """The queue's job ``job_id`` put in ``state``, its stages as ``stages`` says (each else waiting, or done once
    the job is), its commands' ``output``; and the job as the phone holds it (JobViewsReplay.jobOf's shape)."""
    job = next(j for j in app.queue._jobs if j.id == job_id)
    job.state = state
    for step in job.steps:
        step.state = STEP_STATES[state]
        step.code = {"done": 0, "failed": 1}.get(state)
        step.output = list(output)
    for stage in job.stages:
        stage.state, stage.detail = (stages or {}).get(stage.name, ("done" if state == "done" else "waiting", ""))
    kind = "harmonica" if job.song_key.startswith("harmonica:") else "versions"
    return {"id": job.id, "title": job.title, "key": job.song_key, "kind": kind, "display": job.display,
            "job_song_id": job.song_id, "fetching": job.fetching, "note": job.note, "state": job.state,
            "stages": [{"name": s.name, "label": s.label, "state": s.state, "detail": s.detail,
                        "running_detail": s.running_detail} for s in job.stages],
            "commands": [{"label": s.label, "args": list(s.args), "state": s.state, "code": s.code,
                          "output": list(s.output)} for s in job.steps]}


def _page_of(response) -> str:
    return re.sub(r"<style>.*?</style>", "<style></style>", response.body.decode("utf-8"), count=1, flags=re.S)


def _refusal(e: Refused) -> dict[str, Any]:
    return {"status": e.status, "title": e.title, "message": str(e)}


def _job_out(app, response) -> dict[str, Any]:
    location = next((v for k, v in response.headers if k == "Location"), None)
    jobs = app.queue.snapshot()
    job_id = response.data["job"]["id"]
    job = next(j for j in jobs if j.id == job_id)
    return {"status": response.status, "location": location,
            "job": {"title": job.title, "key": job.song_key, "steps": [[s.label, list(s.args)] for s in job.steps],
                    "fetching": job.fetching, "display": job.display, "song_id": job.song_id},
            "jobs": len(jobs)}


class Scene:
    """One scene's records: its pages and posts, each over a fresh queue."""

    def __init__(self, name: str, cfg, page: Callable, post: Callable, kind: str):
        self.name, self.cfg, self._page, self._post, self.kind = name, cfg, page, post, kind
        self.records: list[dict[str, Any]] = []

    def get(self, case: str, target: str, *, job: Callable[[Any], tuple[str, dict[str, Any]]] | None = None) -> None:
        """The page of ``target``; with ``job``, a post made first (``job(app)`` posts it and puts its job in a
        state, giving the page's address and the job held)."""
        app = _app(self.cfg)
        held = None
        if job is not None:
            target, held = job(app)
        try:
            response = self._page(app, target)
            out: dict[str, Any] = {"status": response.status, "page": _page_of(response)}
        except Refused as e:
            out = _refusal(e)
        self.records.append({"fn": f"GET /{self.kind}", "scene": self.name, "case": case, "target": target,
                             "job": held, "out": out})

    def post(self, case: str, do: str, form: list[tuple[str, str]], *,
             before: list[tuple[str, list[tuple[str, str]]]] = ()) -> None:
        app = _app(self.cfg)
        for path, fields in before:
            self._post(app, path.rsplit("/", 1)[1], dict(fields))
        try:
            out = _job_out(app, self._post(app, do, dict(form)))
        except Refused as e:
            out = _refusal(e)
        self.records.append({"fn": f"POST /{self.kind}/{do}", "scene": self.name, "case": case,
                             "before": [[p, [list(f) for f in fields]] for p, fields in before],
                             "form": [list(f) for f in form], "out": out})


def _versions_scene(name: str, cfg) -> Scene:
    from caracole.web.versions_routes import versions_page, versions_post

    return Scene(name, cfg, versions_page, versions_post, "versions")


def versions_url(tab: str = KEPT, do: str = "choose", sheet: str = SHEET, extra: str = "") -> str:
    return "/versions?" + urlencode([("sheet", sheet), ("tab", tab), ("do", do)]) + extra


def _posted(do: str, form: dict[str, str], state: str, **held: Any) -> Callable[[Any], tuple[str, dict[str, Any]]]:
    """A post of ``do`` whose job is then in ``state``: the page its answer goes to, and the job."""
    from caracole.web.versions_routes import versions_post

    def made(app) -> tuple[str, dict[str, Any]]:
        response = versions_post(app, do, form)
        location = next(v for k, v in response.headers if k == "Location")
        return location, _hold(app, response.data["job"]["id"], state, **held)

    return made


def base_versions(cfg, songs) -> list[dict[str, Any]]:
    s = _versions_scene("base", cfg)
    tren, eres, mariposa, hoteles = (songs[t] for t in ("Tren al Sur", "Eres", "Mariposa Tecknicolor",
                                                         "Demoliendo Hoteles"))
    # the pages: each version, each doing
    for tab, do in ((OTHER, "choose"), (OTHER, "keep"), (KEPT, "choose"), (KEPT, "keep"), (ONE, "choose"),
                    (ONE, "keep"), (GONE, "choose"), (GONE, "keep"), (BLOCKED, "choose"), (BLOCKED, "keep"),
                    ("", "clear")):
        s.get(f"{do} Ver {tab or 'none'}", versions_url(tab, do))
    s.get("from a kept version's own page", versions_url(KEPT, "choose", sheet=f"{FOLDER}/version-{KEPT}.html"))
    s.get("a version with its note, keep", versions_url(KEPT, "keep", sheet=f"{FOLDER}/version-{KEPT}.html"))
    s.get("LaCuerda's sheet is the one, a chords pin to go back from",
          versions_url("", "clear", sheet=f"{TREN}/sheet.html"))
    s.get("LaCuerda's sheet is the one, a version", versions_url(TREN_TABS[0], "choose", sheet=f"{TREN}/sheet.html"))
    s.get("the auto sheet is the one", versions_url("4001", "keep", sheet=f"{MARIPOSA}/sheet (auto).html"))
    s.get("an ignored song's page", versions_url("3002", "choose", sheet=f"{ERES}/sheet.html"))
    # the page refuses
    s.get("no doing", "/versions?" + urlencode([("sheet", SHEET), ("tab", KEPT)]))
    s.get("a doing that is none", versions_url(KEPT, "nothing"))
    s.get("keep-more is no doing of the page", versions_url(KEPT, "keep-more"))
    s.get("a tab that is no number", versions_url("abc", "choose"))
    s.get("no tab", versions_url("", "keep"))
    s.get("a tab of thirteen digits", versions_url("1" * 13, "choose"))
    s.get("a tab of twelve digits, no version", versions_url("1" * 12, "choose"))
    s.get("a tab no version is", versions_url("424242", "choose"))
    s.get("a tab of another song's", versions_url(TREN_TABS[0], "choose"))
    s.get("a text tab", versions_url(TEXT_TAB, "choose"))
    s.get("a tab of other digits", versions_url("١٢٣", "choose"))
    for sheet in ("", "sheet.html", f"{FOLDER}/sheet.txt", f"{FOLDER}/sheet.pdf", "Nobody/Nothing/sheet.html",
                  f"{FOLDER}/../{FOLDER}/sheet.html", f"./{FOLDER}/sheet.html", f"{FOLDER}//sheet.html",
                  f"{FOLDER}/x/sheet.html", f"{FOLDER}/sheet (auto).html",
                  f"{FOLDER}/version-{OTHER}.html", f"{FOLDER}/version-{KEPT}.json", f"{FOLDER}/version-.html",
                  f"{FOLDER}/Version-{KEPT}.html", f"{hoteles.artist}/{hoteles.title}/sheet.html"):
        s.get(f"the sheet {sheet!r}", versions_url(OTHER, "choose", sheet=sheet))
    s.get("a job that is no number", versions_url(extra="&job=abc"))
    s.get("a job of twelve digits", versions_url(extra="&job=" + "1" * 12))
    s.get("a job no queue has", versions_url(extra="&job=7"))
    s.get("an address that can't be read", "/versions?sheet=%ff&tab=1&do=choose")
    s.get("eleven fields", versions_url() + "".join(f"&x{n}=1" for n in range(8)))
    s.get("a field twice: the last counts", versions_url(OTHER, "keep") + "&do=choose")
    # how a job goes
    keep, choose = {"sheet": SHEET, "tab": OTHER}, {"sheet": SHEET, "tab": OTHER}
    clear = {"sheet": f"{TREN}/sheet.html"}
    for state in ("queued", "running", "cancelled", "interrupted"):
        s.get(f"keep, {state}", "", job=_posted("keep", keep, state))
        s.get(f"choose, {state}", "", job=_posted("choose", choose, state))
        s.get(f"clear, {state}", "", job=_posted("clear", clear, state))
    s.get("keep, failed", "", job=_posted("keep", keep, "failed", output=(
        "caracole-progress: {\"stage\":\"song\",\"state\":\"done\"}", "error: Ultimate Guitar is blocking caracole",
        "")))
    s.get("choose, failed with no output", "", job=_posted("choose", choose, "failed"))
    s.get("keep, done, not kept", "", job=_posted("keep", keep, "done", stages={"version": (
        "skipped", "the hour's lookups to Ultimate Guitar are spent.")}))
    s.get("keep, done, not kept, nothing said", "", job=_posted("keep", keep, "done"))
    s.get("choose, done, not the one", "", job=_posted("choose", choose, "done", stages={"sheet": (
        "failed", "Ultimate Guitar answered 500..")}))
    s.get("choose, done, not the one, nothing said", "", job=_posted("choose", choose, "done"))
    s.get("clear, done, the pin still there", "", job=_posted("clear", clear, "done"))

    def another(app) -> tuple[str, dict[str, Any]]:
        from caracole.web.versions_routes import versions_post

        response = versions_post(app, "keep", keep)
        held = _hold(app, response.data["job"]["id"], "running")
        return versions_url(KEPT, "choose", extra=f"&job={held['id']}"), held

    s.get("a job of another version's is not this page's", "", job=another)

    def other_song(app) -> tuple[str, dict[str, Any]]:
        from caracole.web.versions_routes import versions_post

        response = versions_post(app, "clear", clear)
        held = _hold(app, response.data["job"]["id"], "running")
        return versions_url(OTHER, "keep", extra=f"&job={held['id']}"), held

    s.get("a job of another song's is not this page's", "", job=other_song)
    # the posts
    s.post("choose a version", "choose", [("sheet", SHEET), ("tab", OTHER)])
    s.post("choose a kept version", "choose", [("sheet", SHEET), ("tab", KEPT)])
    s.post("keep a version", "keep", [("sheet", SHEET), ("tab", OTHER)])
    s.post("keep a version, from a kept one's page", "keep", [("sheet", f"{FOLDER}/version-{KEPT}.html"),
                                                               ("tab", OTHER)])
    s.post("clear a chords pin", "clear", [("sheet", f"{TREN}/sheet.html")])
    s.post("clear with a tab of no matter", "clear", [("sheet", f"{TREN}/sheet.html"), ("tab", "abc")])
    s.post("choose LaCuerda's song's version", "choose", [("sheet", f"{TREN}/sheet.html"), ("tab", TREN_TABS[0])])
    s.post("keep the auto sheet's song's version", "keep", [("sheet", f"{MARIPOSA}/sheet (auto).html"),
                                                            ("tab", "4001")])
    for do, tab, case in (("choose", ONE, "the one already"), ("keep", ONE, "the one, kept"),
                          ("keep", KEPT, "kept already"), ("choose", GONE, "gone"), ("keep", GONE, "gone"),
                          ("choose", BLOCKED, "blocked"), ("keep", BLOCKED, "blocked"),
                          ("clear", "", "no pin of its sheet, a text tab's pin stays")):
        s.post(f"{do}: {case}", do, [("sheet", SHEET), ("tab", tab)])
    s.post("an ignored song", "choose", [("sheet", f"{ERES}/sheet.html"), ("tab", "3002")])
    s.post("a tab that is no number", "keep", [("sheet", SHEET), ("tab", "x")])
    s.post("no tab", "choose", [("sheet", SHEET)])
    s.post("a tab no version is", "keep", [("sheet", SHEET), ("tab", "99")])
    s.post("no sheet", "keep", [("tab", OTHER)])
    s.post("a sheet no viewer was written for", "keep", [("sheet", f"{FOLDER}/version-{OTHER}.html"), ("tab", OTHER)])
    s.post("a sheet of no song", "keep", [("sheet", "Nobody/Nothing/sheet.html"), ("tab", OTHER)])
    # by the song's id, as the library page's card posts it
    ligera = songs["De Música Ligera"]
    s.post("by song: choose", "choose", [("song", str(ligera.id)), ("tab", OTHER)])
    s.post("by song: keep", "keep", [("song", f" {ligera.id} "), ("tab", OTHER)])
    s.post("by song: clear", "clear", [("song", str(tren.id))])
    s.post("by song: clear, no pin", "clear", [("song", str(ligera.id))])
    s.post("by song: a song with no sheet", "keep", [("song", str(hoteles.id)), ("tab", "5001")])
    s.post("by song: a song with no sheet, choose", "choose", [("song", str(hoteles.id)), ("tab", "5001")])
    s.post("by song: the auto sheet's", "choose", [("song", str(mariposa.id)), ("tab", "4001")])
    s.post("by song: an ignored song", "keep", [("song", str(eres.id)), ("tab", "3002")])
    s.post("by song: a tab of another song's", "keep", [("song", str(ligera.id)), ("tab", "5001")])
    s.post("by song: no tab", "keep", [("song", str(ligera.id))])
    s.post("by song: an id that is no number", "keep", [("song", "abc"), ("tab", OTHER)])
    s.post("by song: an id no song has", "keep", [("song", "9999"), ("tab", OTHER)])
    s.post("by song: spaces alone are no song", "keep", [("song", "   "), ("sheet", SHEET), ("tab", OTHER)])
    # the queue's joins
    s.post("the same version kept twice is one job", "keep", [("sheet", SHEET), ("tab", OTHER)],
           before=[("/versions/keep", [("sheet", SHEET), ("tab", OTHER)])])
    s.post("two versions kept are two commands of one job", "keep", [("sheet", SHEET), ("tab", BLOCKED)],
           before=[("/versions/keep", [("sheet", SHEET), ("tab", OTHER)])])
    s.post("choose while a keep waits", "choose", [("sheet", SHEET), ("tab", KEPT)],
           before=[("/versions/keep", [("sheet", SHEET), ("tab", OTHER)])])
    s.post("keep while a choose waits", "keep", [("sheet", SHEET), ("tab", OTHER)],
           before=[("/versions/choose", [("sheet", SHEET), ("tab", KEPT)])])
    return s.records


def chosen_versions(cfg, songs) -> list[dict[str, Any]]:
    s = _versions_scene("chosen", cfg)
    choose = {"sheet": f"{FOLDER}/version-{KEPT}.html", "tab": KEPT}
    s.get("a version's page gone once it is the one", versions_url(KEPT, "choose",
                                                                 sheet=f"{FOLDER}/version-{KEPT}.html"))
    s.get("the one now, by the sheet", versions_url(KEPT, "choose"))
    s.get("the old one, keep", versions_url(ONE, "keep"))
    s.get("clear: a chords pin now", versions_url("", "clear"))
    s.get("a gone page of a version not the one", versions_url(OTHER, "choose", sheet=f"{FOLDER}/version-{OTHER}.html"))

    def posted_before(app) -> tuple[str, dict[str, Any]]:
        # the post was made before Ver 2 became the one: its job is done now
        from caracole.web.jobs import version_steps

        song = songs["De Música Ligera"]
        job, _ = app.submit(f"Make a version the one: {song.display}", song.key,
                            version_steps(song.artist, song.title, choose=KEPT), fetching=True, display=song.display)
        held = _hold(app, job.id, "done")
        return versions_url(KEPT, "choose", sheet=choose["sheet"], extra=f"&job={job.id}"), held

    s.get("choose, done: the one now", "", job=posted_before)
    s.post("choose the one now", "choose", [("sheet", SHEET), ("tab", KEPT)])
    s.post("clear its pin", "clear", [("sheet", SHEET)])
    return s.records


def kept_versions(cfg, songs) -> list[dict[str, Any]]:
    s = _versions_scene("kept", cfg)

    def kept(app) -> tuple[str, dict[str, Any]]:
        from caracole.web.jobs import version_steps

        song = songs["De Música Ligera"]
        job, _ = app.submit(f"Keep a version of {song.display}", song.key,
                            version_steps(song.artist, song.title, keep=OTHER), fetching=True, display=song.display)
        return versions_url(OTHER, "keep", extra=f"&job={job.id}"), _hold(app, job.id, "done")

    s.get("keep, done: kept", "", job=kept)
    s.get("a kept version's page offers to open it", versions_url(OTHER, "choose"))
    s.post("keep it again", "keep", [("sheet", SHEET), ("tab", OTHER)])
    return s.records


def pinned_versions(cfg, songs) -> list[dict[str, Any]]:
    s = _versions_scene("pinned", cfg)

    def chose(app) -> tuple[str, dict[str, Any]]:
        from caracole.web.jobs import version_steps

        song = songs["De Música Ligera"]
        job, _ = app.submit(f"Make a version the one: {song.display}", song.key,
                            version_steps(song.artist, song.title, choose=OTHER), fetching=True, display=song.display)
        return versions_url(OTHER, "choose", extra=f"&job={job.id}"), _hold(app, job.id, "done", stages={
            "sheet": ("skipped", "the hour's lookups to Ultimate Guitar are spent.")})

    s.get("choose, done: pinned, not the one yet", "", job=chose)
    s.get("clear: a pin of its sheet", versions_url("", "clear"))
    s.post("clear it", "clear", [("sheet", SHEET)])
    return s.records


def unpinned_versions(cfg, songs) -> list[dict[str, Any]]:
    s = _versions_scene("unpinned", cfg)

    def cleared(app) -> tuple[str, dict[str, Any]]:
        from caracole.web.jobs import version_steps

        song = songs["Tren al Sur"]
        job, _ = app.submit(f"Back to caracole's pick: {song.display}", song.key,
                            version_steps(song.artist, song.title), fetching=True, display=song.display)
        return versions_url("", "clear", sheet=f"{TREN}/sheet.html", extra=f"&job={job.id}"), _hold(app, job.id, "done")

    s.get("clear, done: caracole picks again", "", job=cleared)
    s.post("clear again", "clear", [("sheet", f"{TREN}/sheet.html")])
    return s.records


def versions_records(tmp: Path) -> list[dict[str, Any]]:
    out = []
    for scene, change, records in (("base", None, base_versions), ("chosen", to_chosen, chosen_versions),
                                   ("kept", to_kept, kept_versions), ("pinned", to_pinned, pinned_versions),
                                   ("unpinned", to_unpinned, unpinned_versions)):
        with _library(tmp / f"versions-{scene}") as (cfg, conn):
            songs = build_versions(conn, cfg)
            if change is not None:
                change(conn, cfg, songs)
            out.append(_fixture(conn, cfg, scene, files=False))
            out += records(cfg, songs)
    return out


# --- the harmonica tabs' scenes ------------------------------------------------------------------------------------


def _harmonica_tab(conn, cfg, song, number: int, text: str | None, harp: str | None = None,
                   key: str | None = "C") -> None:
    """A harmonica tab kept as harptabs_fetch.py keeps one, its page's chips ``key`` and ``harp``; ``text`` None: its
    file gone since."""
    from caracole.library import song_dir
    from caracole.versions import upsert_version

    vid = upsert_version(conn, provider="harptabs", tab_id=str(588 + number), song_id=song.id, slot="guitar",
                         kind="harmonica", rating=3.3, votes=224000, version=1, label=None,
                         url=f"https://www.harptabs.com/song/{588 + number}/spokey-dokey",
                         raw={"title": song.title, "artist": song.artist, "key": key, "harp": harp,
                              "difficulty": "Beginner", "views": 224000, "rating": 3.3}, now=STAMP)
    _keep(conn, cfg, song, vid, f"harmonica-{number}.txt", (text or "gone").encode("utf-8"), rank=number)
    if text is None:
        (song_dir(cfg.library_dir, song) / f"harmonica-{number}.txt").unlink()
    _written(conn, song, f"harmonica-{number}.html")


def build_harmonica(conn, cfg) -> dict[str, Any]:
    from caracole.overrides import add_ignore
    from caracole.songs import get_song

    spokey = _song(conn, "Cowboy Bebop", "Spokey Dokey", 0)
    _harmonica_tab(conn, cfg, spokey, 1, SPOKEY)
    _harmonica_tab(conn, cfg, spokey, 2, BENT, harp="Diatonic", key=None)
    _harmonica_tab(conn, cfg, spokey, 3, CHROMATIC, harp="Chromatic")
    _harmonica_tab(conn, cfg, spokey, 4, None)
    _written(conn, spokey, "harmonica-5.html")
    eres = _song(conn, "Café Tacvba", "Eres", 1)
    _harmonica_tab(conn, cfg, eres, 1, BENT)
    add_ignore(cfg.overrides_file, eres.display)
    _settled(conn)
    return {"Spokey Dokey": get_song(conn, spokey.id), "Eres": get_song(conn, eres.id)}


def _pinned(spec: Any, tab: str = "harmonica-1.txt") -> Callable:
    def change(conn, cfg, songs) -> None:
        from caracole.overrides import add_harmonica

        add_harmonica(cfg.overrides_file, SPOKEY_DISPLAY, tab, spec)

    return change


def page_url(page: str = SPOKEY_PAGE, extra: str = "") -> str:
    return "/harmonica?" + urlencode([("page", page)]) + extra


def _harmonica_scene(name: str, cfg) -> Scene:
    from caracole.web.harmonica_routes import harmonica_page, harmonica_post

    return Scene(name, cfg, harmonica_page, harmonica_post, "harmonica")


def _pin_posted(do: str, form: dict[str, str], state: str, **held: Any) -> Callable:
    from caracole.web.harmonica_routes import harmonica_post

    def made(app) -> tuple[str, dict[str, Any]]:
        response = harmonica_post(app, do, form)
        location = next(v for k, v in response.headers if k == "Location")
        return location, _hold(app, response.data["job"]["id"], state, **held)

    return made


def _submitted(tab: str, options: tuple[str, ...], said: str, state: str) -> Callable:
    """A pin's job queued before the scene's overrides.toml was as it is now."""
    from caracole.web.jobs import MINE, READING

    def made(app) -> tuple[str, dict[str, Any]]:
        from caracole.songs import find_song
        from caracole.normalize import identity_key

        with app.db() as conn:
            song = find_song(conn, identity_key("Cowboy Bebop", "Spokey Dokey"))
        steps = [("Reading the harmonica tab", ("harmonica", f"--tab={tab}", *options, "--", song.artist, song.title))]
        job, _ = app.submit(f"Read {tab} of {song.display}", f"{READING}{song.key}:{tab}:{said}{MINE}", steps,
                            display=song.display, song_id=song.id)
        page = f"{SPOKEY_FOLDER}/{tab.replace('.txt', '.html')}"
        return page_url(page, f"&job={job.id}"), _hold(app, job.id, state)

    return made


def harmonica_pages(scene: str, cfg) -> list[dict[str, Any]]:
    s = _harmonica_scene(scene, cfg)
    for n in (1, 2, 3):
        s.get(f"harmonica-{n}", page_url(f"{SPOKEY_FOLDER}/harmonica-{n}.html"))
    if scene == "spokey":
        for page in (f"{SPOKEY_FOLDER}/harmonica-4.html", f"{SPOKEY_FOLDER}/harmonica-5.html",
                     f"{SPOKEY_FOLDER}/harmonica-6.html", f"{SPOKEY_FOLDER}/sheet.html",
                     f"{SPOKEY_FOLDER}/harmonica-1.txt", "Unknown/Song/harmonica-1.html",
                     f"{SPOKEY_FOLDER}/../{SPOKEY_FOLDER}/harmonica-1.html", f"x/{SPOKEY_FOLDER}/harmonica-1.html",
                     "harmonica-1.html", "", f"{SPOKEY_FOLDER}/harmonica-01.html", f"{SPOKEY_FOLDER}/harmonica-١.html"):
            s.get(f"the page {page!r}", page_url(page))
        s.get("the ignored song's tab", page_url("Café Tacvba/Eres/harmonica-1.html"))
        s.get("a job that is no number", page_url(extra="&job=x"))
        s.get("a job no queue has", page_url(extra="&job=3"))
        s.get("an address that can't be read", "/harmonica?page=%ff")
        s.get("eleven fields", page_url() + "".join(f"&x{n}=1" for n in range(10)))
        pin = {"page": SPOKEY_PAGE, "as": "letters"}
        for state in ("queued", "running", "cancelled", "interrupted"):
            s.get(f"pin, {state}", "", job=_pin_posted("pin", pin, state))
        s.get("pin, failed", "", job=_pin_posted("pin", pin, "failed", output=(
            "harmonica-1.txt of Cowboy Bebop - Spokey Dokey can't be read", "  ")))
        s.get("pin, failed with no output", "", job=_pin_posted("pin", pin, "failed"))
        s.get("pin, done, but no pin", "", job=_pin_posted("pin", pin, "done"))
        s.get("clear, done: guessed again", "", job=_submitted("harmonica-1.txt", ("--clear",), "clear", "done"))

        def other_tab(app) -> tuple[str, dict[str, Any]]:
            from caracole.web.harmonica_routes import harmonica_post

            response = harmonica_post(app, "pin", {"page": f"{SPOKEY_FOLDER}/harmonica-2.html", "as": "letters"})
            held = _hold(app, response.data["job"]["id"], "running")
            return page_url(extra=f"&job={held['id']}"), held

        s.get("a job of another tab's is not this page's", "", job=other_tab)

        def not_harmonica(app) -> tuple[str, dict[str, Any]]:
            from caracole.normalize import identity_key
            from caracole.web.jobs import MINE, READING

            song_key = identity_key("Cowboy Bebop", "Spokey Dokey")
            job, _ = app.submit("Other", f"{READING}{song_key}:harmonica-1.txt:x{MINE}",
                                [("Other", ("render", "--song=Cowboy Bebop - Spokey Dokey"))])
            return page_url(extra=f"&job={job.id}"), _hold(app, job.id, "running")

        s.get("a job of the tab's key that is no harmonica command", "", job=not_harmonica)
        # the posts
        for spec, case in (("letters", "a notation"), ("legend", "its own legend"), ("signs", "harptabs.com's own"),
                           ("signs after", "a notation of two words"),
                           (json.dumps({"as": "signs", "*": "bend", "(w)": "wah"}), "a table"),
                           (json.dumps({"*": "bend"}), "a table with no notation named"),
                           (json.dumps({"(w)": "wah", "as": "letters"}), "a table, its notation last"),
                           ('{"as": "brackets", "as": "letters"}', "a table naming its notation twice"),
                           ("staff", "no notation"), ("{not json", "no JSON"),
                           (json.dumps({"*": "squeak"}), "no meaning"),
                           (json.dumps({"as": 5}), "a notation that is no name"), ("[1]", "a list"), ("", "nothing"),
                           ('"letters"', "a name in quotes"), (json.dumps({"*": 4}), "a meaning that is no word")):
            s.post(f"pin {case}", "pin", [("page", SPOKEY_PAGE), ("as", spec)])
        s.post("pin the tab of signs", "pin", [("page", f"{SPOKEY_FOLDER}/harmonica-2.html"), ("as", "letters")])
        s.post("clear with no pin", "clear", [("page", SPOKEY_PAGE)])
        s.post("pin an ignored song's tab", "pin", [("page", "Café Tacvba/Eres/harmonica-1.html"), ("as", "letters")])
        s.post("pin a page of no tab", "pin", [("page", f"{SPOKEY_FOLDER}/harmonica-5.html"), ("as", "letters")])
        s.post("pin no page", "pin", [("as", "letters")])
        s.post("the same reading twice is one job", "pin", [("page", SPOKEY_PAGE), ("as", "letters")],
               before=[("/harmonica/pin", [("page", SPOKEY_PAGE), ("as", "letters")])])
        s.post("two readings are two jobs", "pin", [("page", SPOKEY_PAGE), ("as", "brackets")],
               before=[("/harmonica/pin", [("page", SPOKEY_PAGE), ("as", "letters")])])
    else:
        s.post("pin as it is pinned", "pin", [("page", SPOKEY_PAGE), ("as", PINS[scene][0])])
        s.post("pin another", "pin", [("page", SPOKEY_PAGE), ("as", "barrett")])
        s.post("clear", "clear", [("page", SPOKEY_PAGE)])
        said = PINS[scene][0]
        options = (f"--as={said}",) if not said.startswith("{") else ()
        s.get("pin, done: read as set", "", job=_submitted("harmonica-1.txt", options or ("--as=signs",),
                                                           json.dumps(PINS[scene][1], sort_keys=True), "done"))
        s.get("clear, done, but the pin still there", "", job=_submitted("harmonica-1.txt", ("--clear",), "clear",
                                                                         "done"))
    return s.records


PINS = {  # each pinned scene: the form's reading, overrides.toml's
    "letters": ("letters", "letters"),
    "table": (json.dumps({"as": "signs", "*": "bend", "(w)": "wah"}), {"as": "signs", "*": "bend", "(w)": "wah"}),
    "signs": ("signs", "signs"),
}


def harmonica_command(scene: str, cfg, case: str, args: list[str]) -> dict[str, Any]:
    """``caracole harmonica ARGS`` over the scene's library (``cfg``'s), its render stood in for."""
    from typer.testing import CliRunner

    from caracole.cli import build_app
    from caracole.overrides import load_overrides

    failed: list[tuple[int, str]] = []
    rendered: list[int] = []

    def fail(message: str, code: int = 1):
        failed.append((code, message))
        raise typer.Exit(code)

    before = cfg.overrides_file.read_bytes() if cfg.overrides_file.exists() else None
    with mock.patch("caracole.commands.harmonica.fail", fail), mock.patch("caracole.harmonica_cmd.fail", fail), \
            mock.patch("caracole.commands._common.fail", fail), \
            mock.patch("caracole.harmonica_cmd._render", lambda conn, cfg, song: rendered.append(song.id)):
        result = CliRunner().invoke(build_app(), ["--config", str(cfg.library_dir.parent / "caracole.toml"),
                                                  "harmonica", *args])
    harmonica = load_overrides(cfg.overrides_file).harmonica
    if before is None:
        cfg.overrides_file.unlink(missing_ok=True)
    else:
        cfg.overrides_file.write_bytes(before)
    assert result.exception is None or isinstance(result.exception, SystemExit), result.exception
    out = {"code": result.exit_code, "lines": result.stdout.splitlines(),
           "error": failed[0][1] if failed else None, "rendered": bool(rendered),
           "harmonica": {k: dict(v) for k, v in harmonica.items()}}
    return {"fn": "caracole harmonica", "scene": scene, "case": case, "args": args, "out": out}


SONG = ["--", "Cowboy Bebop", "Spokey Dokey"]


def harmonica_commands(scene: str, cfg) -> list[dict[str, Any]]:
    out = []
    a = out.append
    if scene == "spokey":
        a(harmonica_command(scene, cfg, "a notation", ["--tab=harmonica-1.txt", "--as=letters", *SONG]))
        a(harmonica_command(scene, cfg, "a table", ["--tab=harmonica-1.txt", "--as=signs", "--symbol=*=bend",
                                                     "--symbol=(w)=wah", *SONG]))
        a(harmonica_command(scene, cfg, "the tab's own legend", ["--tab=harmonica-1.txt", "--as=legend", *SONG]))
        a(harmonica_command(scene, cfg, "a legend the tab hasn't got", ["--tab=harmonica-2.txt", "--as=legend", *SONG]))
        a(harmonica_command(scene, cfg, "the chromatic tab", ["--tab=harmonica-3.txt", "--as=signs", *SONG]))
        a(harmonica_command(scene, cfg, "options apart from their values", ["--tab", "harmonica-2.txt", "--as",
                                                                             "letters", *SONG]))
        a(harmonica_command(scene, cfg, "a tab the song hasn't got", ["--tab=harmonica-9.txt", "--as=letters", *SONG]))
        a(harmonica_command(scene, cfg, "no tab named, of several", ["--as=letters", *SONG]))
        a(harmonica_command(scene, cfg, "a tab whose file is gone", ["--tab=harmonica-4.txt", "--as=letters", *SONG]))
        a(harmonica_command(scene, cfg, "clear with no pin", ["--tab=harmonica-1.txt", "--clear", *SONG]))
        a(harmonica_command(scene, cfg, "no notation", ["--tab=harmonica-1.txt", "--as=staff", *SONG]))
        a(harmonica_command(scene, cfg, "a symbol of no meaning", ["--tab=harmonica-1.txt", "--as=signs",
                                                                    "--symbol=*=squeak", *SONG]))
        a(harmonica_command(scene, cfg, "a symbol with no meaning", ["--tab=harmonica-1.txt", "--as=signs",
                                                                      "--symbol=bend", *SONG]))
        a(harmonica_command(scene, cfg, "a symbol with no notation", ["--tab=harmonica-1.txt", "--symbol=*=bend",
                                                                       *SONG]))
        a(harmonica_command(scene, cfg, "both --as and --clear", ["--tab=harmonica-1.txt", "--as=letters", "--clear",
                                                                   *SONG]))
        a(harmonica_command(scene, cfg, "the song as one text", ["--tab=harmonica-1.txt", "--as=barrett", "--",
                                                                  "Cowboy Bebop - Spokey Dokey"]))
        a(harmonica_command(scene, cfg, "no song of that name", ["--tab=harmonica-1.txt", "--as=letters", "--",
                                                                  "Cowboy Bebop", "Tank!"]))
        a(harmonica_command(scene, cfg, "an ignored song", ["--as=letters", "--", "Café Tacvba", "Eres"]))
        a(harmonica_command(scene, cfg, "a song that is no name", ["--as=letters", "--", "Cowboy Bebop"]))
        a(harmonica_command(scene, cfg, "the readings listed", SONG))
        a(harmonica_command(scene, cfg, "the readings listed, a tab named", ["--tab=harmonica-2.txt", *SONG]))
        a(harmonica_command(scene, cfg, "the readings of an ignored song", ["--", "Café Tacvba", "Eres"]))
    else:
        a(harmonica_command(scene, cfg, "the readings listed", SONG))
        a(harmonica_command(scene, cfg, "clear", ["--tab=harmonica-1.txt", "--clear", *SONG]))
        a(harmonica_command(scene, cfg, "pin another", ["--tab=harmonica-1.txt", "--as=brackets", *SONG]))
        a(harmonica_command(scene, cfg, "pin another tab", ["--tab=harmonica-2.txt", "--as=letters", *SONG]))
    return out


def harmonica_records(tmp: Path) -> list[dict[str, Any]]:
    out = []
    for scene, change in (("spokey", None), ("letters", _pinned("letters")),
                          ("table", _pinned({"as": "signs", "*": "bend", "(w)": "wah"})), ("signs", _pinned("signs")),
                          ("legend", _pinned("legend", "harmonica-2.txt"))):
        with _library(tmp / f"harmonica-{scene}") as (cfg, conn):
            songs = build_harmonica(conn, cfg)
            if change is not None:
                change(conn, cfg, songs)
            out.append(_fixture(conn, cfg, scene, files=True))
            if scene == "legend":
                s = _harmonica_scene(scene, cfg)
                s.get("a pin by a legend it hasn't got", page_url(f"{SPOKEY_FOLDER}/harmonica-2.html"))
                s.post("pin it so again", "pin", [("page", f"{SPOKEY_FOLDER}/harmonica-2.html"), ("as", "legend")])
                out += s.records
            else:
                out += harmonica_pages(scene, cfg)
            out += harmonica_commands(scene, cfg) if scene != "legend" else []
    return out


# --- the vectors ---------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> dict[str, list[dict[str, Any]]]:
    tmp = tmp_path_factory.mktemp("choices")
    return {"versions": versions_records(tmp / "one"), "harmonica": harmonica_records(tmp / "one")}


def test_the_versions_vectors_are_caracole_serves_answers(made):
    check(VERSIONS, jsonl(made["versions"], corpus="web/versions_routes", made_by=MADE_BY))


def test_the_harmonica_vectors_are_caracole_serves_answers(made):
    check(HARMONICA, jsonl(made["harmonica"], corpus="web/harmonica_routes", made_by=MADE_BY))


def _out(records: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {(r["fn"], r["scene"], r["case"]): r["out"] for r in records if r["fn"] != "fixture"}


def test_the_versions_cases_meet_what_they_name(made):
    out = _out(made["versions"])
    page = out[("GET /versions", "base", "choose Ver 1064463")]
    assert page["status"] == 200 and 'action="/versions/choose"' in page["page"]
    assert 'name="csrf" value="tok"' in page["page"] and "<style></style>" in page["page"]
    assert "Make this the one" in page["page"] and "Phone" in page["page"]
    for case in ("keep Ver 39144", "choose Ver 1001", "choose Ver 777", "choose Ver 5555", "clear Ver none"):
        assert "<form" not in out[("GET /versions", "base", case)]["page"], case
    assert out[("GET /versions", "base", "a tab that is no number")]["status"] == 400
    assert out[("GET /versions", "base", "a tab no version is")]["status"] == 404
    assert out[("GET /versions", "base", "the sheet 'Nobody/Nothing/sheet.html'")]["status"] == 404
    assert out[("GET /versions", "base", "a job that is no number")]["status"] == 400
    assert out[("GET /versions", "base", "eleven fields")]["status"] == 400
    assert "Fetching the version…" in out[("GET /versions", "base", "keep, running")]["page"]
    assert 'http-equiv="refresh"' in out[("GET /versions", "base", "keep, queued")]["page"]
    assert 'http-equiv="refresh"' not in out[("GET /versions", "base", "keep, failed")]["page"]
    assert "Done: it is the one now." in out[("GET /versions", "chosen", "choose, done: the one now")]["page"]
    assert "Done: it is kept beside the sheet." in out[("GET /versions", "kept", "keep, done: kept")]["page"]
    assert "recorded under [pin]" in out[("GET /versions", "pinned", "choose, done: pinned, not the one yet")]["page"]
    assert "caracole picks the sheet again" in out[("GET /versions", "unpinned", "clear, done: caracole picks again")][
        "page"]
    posted = out[("POST /versions/choose", "base", "choose a version")]
    assert posted["status"] == 303 and posted["location"].startswith("/versions?") and posted["job"]["steps"]
    assert out[("POST /versions/keep", "base", "by song: keep")]["location"] == "/#tab=requests&job=1"
    for case in ("choose: the one already", "keep: kept already", "choose: gone", "keep: blocked", "an ignored song",
                 "clear: no pin of its sheet, a text tab's pin stays"):
        assert out[(f"POST /versions/{case.split(':')[0] if ':' in case else 'choose'}", "base", case)][
            "status"] == 409, case
    assert out[("POST /versions/keep", "base", "the same version kept twice is one job")]["jobs"] == 1


def test_the_harmonica_cases_meet_what_they_name(made):
    out = _out(made["harmonica"])
    page = out[("GET /harmonica", "spokey", "harmonica-1")]
    assert page["status"] == 200 and "from the tab&#x27;s own legend" in page["page"]
    assert page["page"].count('action="/harmonica/pin"') == 6
    assert out[("GET /harmonica", "spokey", "the page 'Cowboy Bebop/Spokey Dokey/harmonica-4.html'")]["status"] == 404
    assert out[("GET /harmonica", "spokey", "the page 'Cowboy Bebop/Spokey Dokey/harmonica-5.html'")]["status"] == 404
    assert "Back to caracole&#x27;s guess" in out[("GET /harmonica", "letters", "harmonica-1")]["page"]
    for case, status in (("pin no notation", 400), ("pin no JSON", 400), ("pin no meaning", 400),
                         ("clear with no pin", 409), ("pin an ignored song's tab", 409)):
        do = "clear" if case.startswith("clear") else "pin"
        assert out[(f"POST /harmonica/{do}", "spokey", case)]["status"] == status, case
    assert out[("POST /harmonica/pin", "letters", "pin as it is pinned")]["status"] == 409
    table = out[("POST /harmonica/pin", "spokey", "pin a table")]["job"]
    assert table["steps"][0][1][:5] == ["harmonica", "--tab=harmonica-1.txt", "--as=signs", "--symbol=*=bend",
                                        "--symbol=(w)=wah"]
    assert table["key"].endswith(':{"(w)": "wah", "*": "bend", "as": "signs"}:mine')
    said = out[("caracole harmonica", "spokey", "a notation")]
    assert said["code"] == 0 and said["rendered"] and said["lines"][0].startswith("harmonica-1.txt of Cowboy Bebop")
    assert out[("caracole harmonica", "spokey", "a legend the tab hasn't got")]["code"] == 2
    assert out[("caracole harmonica", "spokey", "clear with no pin")]["rendered"] is False
    assert out[("caracole harmonica", "letters", "clear")]["harmonica"] == {}


def test_the_vectors_are_the_same_on_another_run(made, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("again")
    assert versions_records(tmp / "two") == made["versions"]
    assert harmonica_records(tmp / "two") == made["harmonica"]
