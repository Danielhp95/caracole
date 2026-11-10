"""Export and Import a file on caracole serve, for the phone: what android/server's SyncFileRoutes (lane sync-phone)
answers to (docs/superpowers/plans/2026-11-03-sync-redesign.md §3.4.2).

``vectors/web/sync_file_routes.jsonl``: caracole serve's routes of the sync's Export and Import a file
(web/sync_file_routes.py, and ``POST /sync/apply`` on a file's comparison, web/sync_routes.py), each record a request
the page's script makes and its answer, ``{fn: "<METHOD> <path>", note, here, json | form | parts, status, out}``,
under TZ=UTC with the routes' clock at ``NOW``:

- ``here``: the side asked, ``{fixture, id, name, kv}``: the sync corpus's fixture its database is (replayed), its kv
  ``sync:id``, its library's name and more kv it holds (a base for the file's caracole);
- ``file``: a file sent before the request, by its name in ``vectors/sync/files/`` (``sync/files/full.caracole``:
  the sync file corpus's, test_conformance_sync_file.py's), or ``{"bytes": base64}``, or ``{"cut": n}``, that file
  less its last n bytes; ``sent``, how much of it was sent (all, unless it says less);
- ``GET /api/sync/sizes``: ``out`` ``{name, songs, songbooks, made, library, indexes, tabs}``, ``indexes`` masked
  (``"<bytes>"``: SQLite's pages, whichever SQLite counts them) where it isn't null;
- ``POST /sync/export``: ``json`` its document, ``out`` ``{export, name, size}``, the id ``"<export>"`` and the size
  ``"<size>"`` (a zip's bytes are its writer's), or the refusal;
- ``GET /api/sync/export``: ``export`` the parts of the export it follows, ``query`` ``{export}`` (``"<export>"`` for
  that one's id, any other text one no export has), ``out`` ``{headers: {Content-Type, Content-Disposition},
  manifest}`` (the file's caracole.json) or the refusal; ``again``, a second GET of it;
- ``POST /sync/import/open``: ``json``, ``out`` ``{import: "<import>", part}`` or the refusal;
- ``POST /sync/import/part``: ``parts``, each ``{at, bytes}`` (``bytes`` its length, of the file), sent in order, and
  ``out`` each answer, ``[status, body]``;
- ``POST /sync/import/compare``: the file sent whole first (``file``), ``form`` ``{import: "<import>"}`` (or another
  text), ``out`` as ``POST /sync/compare``'s, ``comparison`` ``"<comparison>"``, or the refusal, with ``staged``,
  whether the file is still here after (a refused file is deleted);
- ``POST /sync/import/drop``: ``json`` ``{import}`` (``"<import>"``: the file sent), ``out`` or the refusal;
- ``POST /sync/apply``: on the file's comparison (``form``: ``comparison`` ``"<comparison>"``), ``moved`` a song this
  side added between the two (null: none), ``out`` the job queued (``{job: view}``) or the refusal, ``queued`` its
  command's arguments, the staged folder ``"<folder>"``;
- ``limits``: each route's declared kind and limit, ``{"<METHOD> <path>": [body, limit]}``, so that the phone's
  routes declare the same.

A refusal's words are the routes'; the phone's routes say the same. Regenerate with ``CARACOLE_CORPUS=write``.
"""

from __future__ import annotations

import base64
import io
import json
import time
import zipfile
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import pytest
from helpers.corpus import VECTORS, check, jsonl

from caracole import db
from caracole import peer_sync as sync
from caracole.web import sync_file_routes
from caracole.web.app import Request, WebApp
from caracole.web.jobs import JobQueue

from test_conformance_sync_file import EXPORTER, IMPORTER, MADE, FileCorpus
from test_web_app import ALLOWED, HOST, Recorder

MADE_BY = "tests/test_conformance_sync_file_routes.py"
VECTOR = VECTORS / "web" / "sync_file_routes.jsonl"
NOW = datetime(2026, 11, 3, 22, 0, tzinfo=UTC)
JSON = "application/json"
BYTES = "application/octet-stream"
EXPORT, IMPORT, COMPARISON, FOLDER = "<export>", "<import>", "<comparison>", "<folder>"


class Here:
    """The side asked: a fixture of the sync corpus replayed, its id and more kv, and its caracole serve, whose queue
    records what it is asked to run."""

    def __init__(self, corpus: FileCorpus, fixture: str, tag: str, *, sync_id: str = IMPORTER,
                 kv: dict[str, Any] | None = None):
        self.lib = corpus.replayed("sync", fixture, tag)
        db.kv_set(self.lib.conn, sync.ID_KEY, sync_id)
        self.kv = {key: value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
                   for key, value in (kv or {}).items()}
        for key, text in self.kv.items():
            db.kv_set(self.lib.conn, key, text)
        self.app = WebApp(self.lib.cfg, JobQueue(Recorder()), allowed=ALLOWED, csrf="tok")
        self.described = {"fixture": f"sync/fixtures/{fixture}", "id": sync_id, "name": self.lib.cfg.library_name,
                          "kv": self.kv}

    def ask(self, method: str, path: str, *, doc: Any = None, data: bytes | None = None,
            form: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
        """The page's script asking: a GET or a JSON or bytes POST with the form token in its header, or a form."""
        headers = {"host": HOST, "accept": JSON, "sec-fetch-site": "same-origin", "x-caracole-form-token": "tok"}
        if method == "GET" or method == "HEAD":
            answer = self.app.handle(Request(method, path, headers))
        elif form is not None:
            headers |= {"content-type": "application/x-www-form-urlencoded", "origin": f"http://{HOST}"}
            answer = self.app.handle(Request("POST", path, headers, urlencode({"csrf": "tok", **form}).encode()))
        else:
            body = data if data is not None else json.dumps(doc).encode("utf-8")
            headers |= {"content-type": BYTES if data is not None else JSON}
            answer = self.app.handle(Request("POST", path, headers, body))
        answer = WebApp.finish(answer)
        body = answer.body if answer.stream is None else answer.stream.read()
        if answer.stream is not None:
            answer.stream.close()
        return answer.status, dict(answer.headers), body

    def json(self, method: str, path: str, **kw) -> tuple[int, Any]:
        status, _, body = self.ask(method, path, **kw)
        return status, json.loads(body)

    def send(self, data: bytes, name: str, *, upto: int | None = None) -> str:
        """``data`` sent to Import a file as the page sends one, all of it or its first ``upto`` bytes: its id."""
        status, opened = self.json("POST", "/sync/import/open", doc={"size": len(data), "name": name})
        assert status == 200, opened
        end = len(data) if upto is None else upto
        for at in range(0, end, 4096):
            status, said = self.json("POST", f"/sync/import/part?import={opened['import']}&at={at}",
                                     data=data[at:min(at + 4096, end)])
            assert status == 200, said
        return opened["import"]

    def staged(self) -> list[str]:
        folder = self.lib.cfg.state_dir / "peer"
        return sorted(p.name for p in folder.iterdir() if p.name.startswith("import-")) if folder.exists() else []


def masked(out: Any, **ids: str) -> Any:
    """``out`` with each id of ``ids`` (its value) put as its mask (its key's), wherever a string holds it."""
    if isinstance(out, dict):
        return {k: masked(v, **ids) for k, v in out.items()}
    if isinstance(out, list):
        return [masked(v, **ids) for v in out]
    if isinstance(out, str):
        for mask, value in ids.items():
            if value:
                out = out.replace(value, mask)
    return out


def file_of(corpus: FileCorpus, given: Any) -> tuple[bytes, Any]:
    """A file to send and how a record names it: a corpus file by its name, a cut of one, or bytes."""
    if isinstance(given, str):
        return corpus.file_path(given).read_bytes(), f"sync/files/{given}.caracole"
    if "cut" in given:
        data = corpus.file_path(given["file"]).read_bytes()
        return data[:-given["cut"]], {"file": f"sync/files/{given['file']}.caracole", "cut": given["cut"]}
    return given["bytes"], {"bytes": base64.b64encode(given["bytes"]).decode("ascii")}


def route_records(corpus: FileCorpus) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def add(fn: str, note: str, here: Here, status: int, out: Any, **fields: Any) -> None:
        records.append({"fn": fn, "note": note, "here": here.described, **fields, "status": status, "out": out})

    # --- what an export would hold ----------------------------------------------------------------------------
    for fixture in ("empty", "rich", "file_indexed"):
        here = Here(corpus, fixture, f"-file-routes-sizes-{fixture}")
        status, out = here.json("GET", "/api/sync/sizes")
        if isinstance(out.get("indexes"), int):
            out["indexes"] = "<bytes>"
        add("GET /api/sync/sizes", f"{fixture}: its songs, songbooks, kept files' bytes and the indexes' tabs",
            here, status, out)

    # --- the export, and its one GET ---------------------------------------------------------------------------
    for parts, note in ((["library", "songbooks"], "the library and the songbooks"),
                        (["songbooks"], "the songbooks alone, with the songs they list"),
                        (["indexes", "library"], "the library with the indexes, named in any order")):
        here = Here(corpus, "rich", f"-file-routes-export-{len(records)}")
        status, made = here.json("POST", "/sync/export", doc={"parts": parts})
        out = dict(made, export=EXPORT, size="<size>") if status == 200 else made
        add("POST /sync/export", note, here, status, out, json={"parts": parts})
        status, headers, body = here.ask("GET", f"/api/sync/export?export={made['export']}")
        manifest = json.loads(zipfile.ZipFile(io.BytesIO(body)).read("caracole.json")) if status == 200 else None
        again = here.json("GET", f"/api/sync/export?export={made['export']}")
        add("GET /api/sync/export", f"{note}: sent once", here, status,
            {"headers": {k: headers[k] for k in ("Content-Type", "Content-Disposition")}, "manifest": manifest},
            export={"parts": parts}, query={"export": EXPORT}, again=list(again))
    here = Here(corpus, "rich", "-file-routes-export-refused")
    for doc, note in (({"parts": ["indexes"]}, "the indexes alone: caracole index export's"),
                      ({"parts": ["library", "lyrics"]}, "a part that isn't one"),
                      ({"parts": []}, "no part"), ({"parts": "library"}, "parts that aren't a list"),
                      ({}, "no parts named"), (["library"], "no object")):
        status, out = here.json("POST", "/sync/export", doc=doc)
        add("POST /sync/export", f"refused: {note}", here, status, out, json=doc)
    with sync_file_routes._making:  # another export being made
        status, out = here.json("POST", "/sync/export", doc={"parts": ["library"]})
    add("POST /sync/export", "refused: another export is being made", here, status, out,
        json={"parts": ["library"]}, making=True)
    status, out = here.json("GET", "/api/sync/export?export=0123456789abcdef")
    add("GET /api/sync/export", "an export never made", here, status, out, query={"export": "0123456789abcdef"})
    status, out = here.json("GET", "/api/sync/export?export=../../etc")
    add("GET /api/sync/export", "an id that isn't one", here, status, out, query={"export": "../../etc"})
    status, headers, _ = here.ask("HEAD", "/api/sync/export?export=0123456789abcdef")
    add("HEAD /api/sync/export", "a HEAD would spend the one GET", here, status, {"Allow": headers.get("Allow")},
        query={"export": "0123456789abcdef"})

    # --- a file sent in parts ----------------------------------------------------------------------------------
    here = Here(corpus, "plain", "-file-routes-open")
    for doc, note in (({"size": 8 * 1024 ** 3 + 1, "name": "big.caracole"}, "past 8 GiB"),
                      ({"size": 0, "name": "d.caracole"}, "no size"), ({"size": "big", "name": "d.caracole"},
                                                                       "a size that isn't a number"),
                      ({"size": 10}, "no name")):
        status, out = here.json("POST", "/sync/import/open", doc=doc)
        add("POST /sync/import/open", f"refused: {note}", here, status, out, json=doc)
    status, opened = here.json("POST", "/sync/import/open", doc={"size": 3000, "name": "lib-03-11-26.caracole"})
    add("POST /sync/import/open", "opened: its id and how big a part may be", here, status,
        dict(opened, **{"import": IMPORT}), json={"size": 3000, "name": "lib-03-11-26.caracole"})
    status, out = here.json("POST", "/sync/import/open", doc={"size": 10, "name": "e.caracole"})
    add("POST /sync/import/open", "refused: one is being sent here already", here, status, out,
        json={"size": 10, "name": "e.caracole"})
    answers = []
    sent = [(0, 1000), (1000, 1000), (1000, 1000), (2000, 1001), (2000, 1000)]
    for at, size in sent:
        status, said = here.json("POST", f"/sync/import/part?import={opened['import']}&at={at}", data=b"x" * size)
        answers.append([status, said])
    add("POST /sync/import/part", "two parts, one again (not the next), one past the size, the last", here, None,
        answers, parts=[{"at": at, "bytes": size} for at, size in sent])
    answers = [list(here.json("POST", "/sync/import/part?import=0123456789abcdef&at=0", data=b"x")),
               list(here.json("POST", f"/sync/import/part?import={opened['import']}&at=", data=b"x")),
               list(here.json("POST", "/sync/import/part?import=../x&at=0", data=b"x"))]
    add("POST /sync/import/part", "refused: no such import, no at, an id that isn't one", here, None, answers,
        parts=[{"import": "0123456789abcdef", "at": 0, "bytes": 1}, {"import": IMPORT, "at": "", "bytes": 1},
               {"import": "../x", "at": 0, "bytes": 1}])

    # --- a file compared --------------------------------------------------------------------------------------
    later = {sync.BASE_KEY + EXPORTER: {"format": sync.FORMAT, "units": {
        "song/radiohead/creep": ["0" * 64, "2026-11-04T08:00:00Z"]}}}
    cases = (("plain", "full", {}, IMPORTER, "a library and a file that never synced"),
             ("file_conflict", "full", {}, IMPORTER, "a conflict: the two chorded alike songs otherwise"),
             ("plain", "songbooks", {}, IMPORTER, "a file of the songbooks alone: no song it lacks is a removal"),
             ("plain", "indexes", {}, IMPORTER, "a file with the indexes: the sites it read more recently"),
             ("rich", "full", {}, EXPORTER, "refused: this library's own export"),
             ("plain", "full", later, IMPORTER, "refused: no newer than the last sync with its caracole"),
             ("plain", {"bytes": b"hello, not a file"}, {}, IMPORTER, "refused: no file caracole exported"),
             ("plain", {"file": "full", "cut": 200}, {}, IMPORTER, "refused: a file cut short"))
    for fixture, given, kv, sync_id, note in cases:
        here = Here(corpus, fixture, f"-file-routes-compare-{len(records)}", sync_id=sync_id, kv=kv)
        data, named = file_of(corpus, given)
        import_id = here.send(data, "lib-03-11-26.caracole")
        status, out = here.json("POST", "/sync/import/compare", form={"import": import_id})
        out = dict(out, comparison=COMPARISON) if "comparison" in out else out
        add("POST /sync/import/compare", note, here, status, out, file=named, form={"import": IMPORT},
            staged=bool(here.staged()))
    here = Here(corpus, "plain", "-file-routes-compare-partly")
    data, named = file_of(corpus, "full")
    import_id = here.send(data, "lib-03-11-26.caracole", upto=4096)
    status, out = here.json("POST", "/sync/import/compare", form={"import": import_id})
    add("POST /sync/import/compare", "refused: a file not whole yet, kept for the rest", here, status, out,
        file=named, sent=4096, form={"import": IMPORT}, staged=bool(here.staged()))
    status, out = here.json("POST", "/sync/import/compare", form={"import": "0123456789abcdef"})
    add("POST /sync/import/compare", "refused: no such file here", here, status, out, form={"import":
                                                                                           "0123456789abcdef"})

    # --- Sync on a file's comparison, and a file dropped ------------------------------------------------------
    for fixture, form, moved, note in (
            ("plain", {"prefer": "", "choices": ""}, None, "taken as compared: peer import queued"),
            ("file_conflict", {"prefer": "", "choices": ""}, None, "refused: a conflict with no side"),
            ("file_conflict", {"prefer": "", "choices": "here\tsong/radiohead/creep\nthere\tsong/radiohead/"
                                                        "karma-police"}, None, "each conflict chosen"),
            ("file_conflict", {"prefer": "there", "choices": "", "parts": "songbooks"}, None,
             "of the songbooks alone, every other conflict preferred so"),
            ("plain", {"prefer": "", "choices": ""}, ("Muse", "Uprising"), "refused: this library moved since")):
        here = Here(corpus, fixture, f"-file-routes-apply-{len(records)}")
        import_id = here.send(corpus.file_path("full").read_bytes(), "lib-03-11-26.caracole")
        _, found = here.json("POST", "/sync/import/compare", form={"import": import_id})
        if moved is not None:
            here.lib.song(*moved)
        status, out = here.json("POST", "/sync/apply", form={"comparison": found["comparison"], **form})
        folder = str(here.lib.cfg.state_dir / "peer" / f"import-{import_id}")
        queued = [list(step.args) for job in here.app.queue.snapshot() for step in job.steps]
        add("POST /sync/apply", note, here, status, masked(out, **{FOLDER: folder, IMPORT: import_id}),
            file="sync/files/full.caracole", form={**form, "comparison": COMPARISON},
            moved=" - ".join(moved) if moved else None, queued=masked(queued, **{FOLDER: folder}))
        if status == 200 and not records[-1]["note"].startswith("refused"):
            if fixture == "plain" and moved is None:
                status, out = here.json("POST", "/sync/import/drop", doc={"import": import_id})
                add("POST /sync/import/drop", "refused: its import waits", here, status, out,
                    file="sync/files/full.caracole", json={"import": IMPORT})
    here = Here(corpus, "plain", "-file-routes-drop")
    import_id = here.send(corpus.file_path("songbooks").read_bytes(), "lib-03-11-26.caracole")
    for doc, note in (({"import": import_id}, "dropped, as the page's Cancel"), ({"import": import_id}, "gone"),
                      ({"id": import_id}, "no import named"), ({"import": "../x"}, "an id that isn't one")):
        status, out = here.json("POST", "/sync/import/drop", doc=doc)
        add("POST /sync/import/drop", note, here, status, masked(out, **{IMPORT: import_id}),
            file="sync/files/songbooks.caracole", json=masked(doc, **{IMPORT: import_id}))

    # --- what each route declares ----------------------------------------------------------------------------
    from caracole.web import sync_routes

    limits = {f"{r.method} {r.path}": [r.body, r.limit] for module in (sync_file_routes, sync_routes)
              for r in module.ROUTES if r.method == "POST"}
    records.append({"fn": "limits", "note": "each POST route's body and its limit, in bytes", "out": limits})
    return records


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    made = FileCorpus(tmp_path_factory.mktemp("sync-file-routes-corpus"))
    yield made
    made.close()


@pytest.fixture(scope="module")
def made(corpus):
    """The records, made once: the server's zone UTC and the routes' clock at ``NOW``, as the vectors'."""
    with pytest.MonkeyPatch.context() as patched:
        patched.setenv("TZ", "UTC")
        time.tzset()
        patched.setattr(sync_file_routes, "_now", lambda: NOW)
        try:
            yield route_records(corpus)
        finally:
            patched.undo()
            time.tzset()


def test_sync_file_routes_jsonl_is_what_the_routes_answer(made):
    assert {r["fn"] for r in made} >= {"GET /api/sync/sizes", "POST /sync/export", "GET /api/sync/export",
                                       "POST /sync/import/open", "POST /sync/import/part",
                                       "POST /sync/import/compare", "POST /sync/import/drop", "POST /sync/apply",
                                       "limits"}
    check(VECTOR, jsonl(made, corpus="web/sync_file_routes", made_by=MADE_BY))


def test_the_vectors_show_what_each_case_says(made):
    from caracole import peer_file, peer_import

    by = {(r["fn"], r["note"]): r for r in made}
    full = by["POST /sync/import/compare", "a library and a file that never synced"]
    assert full["status"] == 200 and full["out"]["peer"]["kind"] == "file" and full["out"]["peer"]["made"] == MADE
    assert full["staged"] and full["out"]["holds"] == ["library", "songbooks"]
    books = by["POST /sync/import/compare", "a file of the songbooks alone: no song it lacks is a removal"]
    assert books["out"]["holds"] == ["songbooks"]
    assert not any(d["there"] is None for d in books["out"]["differences"])  # nothing read as removed
    assert by["POST /sync/import/compare", "a file with the indexes: the sites it read more recently"]["out"][
        "indexes"][0]["newer"] == "there"
    own = by["POST /sync/import/compare", "refused: this library's own export"]
    assert (own["status"], own["out"]["error"], own["staged"]) == (409, peer_file.OWN_EXPORT, False)
    older = by["POST /sync/import/compare", "refused: no newer than the last sync with its caracole"]
    assert older["status"] == 409 and older["out"]["error"].startswith("Nothing in this file is newer")
    assert by["POST /sync/import/compare", "refused: a file not whole yet, kept for the rest"]["staged"]
    taken = by["POST /sync/apply", "taken as compared: peer import queued"]
    assert taken["out"]["job"]["kind"] == "sync" and taken["queued"][0][:2] == ["peer", "import"]
    assert taken["queued"][0][-1] == FOLDER
    assert by["POST /sync/import/drop", "refused: its import waits"]["status"] == 409
    assert by["POST /sync/import/open", "opened: its id and how big a part may be"]["out"]["part"] == \
        peer_import.PART_MAX
    limits = by["limits", "each POST route's body and its limit, in bytes"]["out"]
    assert limits["POST /sync/import/part"] == ["bytes", peer_import.PART_MAX]
    assert limits["POST /sync/export"] == ["json", 16 * 1024]  # the plan's 4 KiB is under the router's least
