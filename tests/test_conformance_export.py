"""Export PDF and Make this my version on the phone: what android/server's ``ExportRoutes`` (``GET /export.pdf``) and
the render runner (``caracole render --song --version --mine``) answer (lane export-print), written for
``ExportReplay`` to agree with.

The phone prints the viewer it shows (Android's print framework) and makes no PDF, so its ``GET /export.pdf`` answers
the version's name instead of the PDF: ``{"name", "label"}``, the download name caracole serve's answer is named by
(download_names.py) and the version's label. Its reference is caracole serve's own route
(``export_routes.export_pdf``) with ``render.version_pdf`` giving the label alone (``ExportSheet.label``, which is the
label ``render._export_text`` gives the PDF: the generator checks the two agree wherever the sheet's words aren't
Chinese, whose PDF needs a CJK font), every other check, refusal and job as caracole serve has them.

**The library** (``build_library``): songs with each kind of sheet an export is made from, their sheet viewers
written as render.py records them (kv ``render:files:<id>``: the record alone, as the route reads it, no page), and
overrides.toml as the phone holds it (``test_conformance_overrides.rows_of``):

- Soda Stereo - De Música Ligera: a UG sheet in G, its viewer, a kept version's page beside it and a harmonica tab's;
- Placeholder Band - Synthetic Song: an auto sheet with a UG sheet beside it, both viewers;
- Los Autómatas - Canción Sintética: an auto sheet alone, made from a YouTube video (its credit, the video's);
- 宋冬野 - 斑馬斑馬: a sheet in Traditional characters;
- Héroes del Silencio - Entre Dos Tierras: a sheet with a capo of 2 and a ``[version]`` kept by its key;
- Estopa - Tu Calorro: a sheet under ``[transpose]``;
- Nadie - Sin Acordes: a sheet with no chord, so no key;
- Café Tacvba - Eres: a sheet, ignored;
- Fito Páez - Mariposa Tecknicolor: a viewer recorded, its sheet no longer kept;
- Los Fabulosos Cadillacs - Matador: a sheet whose ``[version]`` is a move with no key, as caracole wrote one before
  (``t=2&mode=dorian``);
- Los Rotos: kept sheets whose sheet.json can't be read (``BROKEN``): none there, not UTF-8, not JSON, no content.

Dumped whole into the vector's first record (``helpers.corpus.dump_fixture``), which the replay loads into a fresh
database.

**vectors/web/export.jsonl**: a header, then:

- ``{"fn": "fixture", "records": [...]}``: the library, as above;
- ``{"fn": "GET /export.pdf", "case", "target", "method", "full", "out"}``: the request's target as the viewer's link
  sends it (``method`` GET, or HEAD, which changes nothing), to a fresh queue that runs nothing (``full``: one with no
  room); ``out`` a refusal, ``{status, title, message}``, or the answer, ``{status, name, label, job}``: ``name`` the
  download name, ``label`` the version's, and ``job`` what ``mine=1`` queued (``{title, key, steps: [[label, [args]]],
  display, song}``, ``song`` its id), else null. A message names the library's folder ``{library}``; with
  ``"prefix": true`` it is the start of the message alone, up to the reader's own words on a file it couldn't read
  (Python's OSError, UnicodeDecodeError or JSONDecodeError, which no other reader words alike);
- ``{"fn": "render.ExportSheet", "case", "song", "query", "out"}``: the song's export sheet (``export_sheet``) and the
  version ``query`` holds (``export_version`` over ``ExportSheet.own``): ``{own, version, label, traditional, entry,
  kept}``, the own version and the version as ``export_query`` writes them, the version's label and its label asked
  in Traditional characters, ``ExportSheet.entry`` and ``ExportSheet.kept`` (null: the song follows its sheet);
- ``{"fn": "render --mine", "case", "args", "out"}``: commands/render.py's ``_make_mine`` for the command line
  ``args`` (``render --song=… --version=… --mine``) over the library's overrides: ``{said, version}``, the line it says
  and the song's ``[version]`` after it (null: none), or ``{exit, error}`` for a refusal (``{library}`` and
  ``prefix`` as above).

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_export.py``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import quote, urlencode

import typer
from helpers.corpus import VECTORS, check, dump_fixture, jsonl, phone_schema

from caracole import db
from caracole.web.pages import Refused

MADE_BY = "tests/test_conformance_export.py"
EXPORT = VECTORS / "web" / "export.jsonl"
FETCHED = "2026-10-18T03:00:00Z"

SODA = ("Soda Stereo", "De Música Ligera")
BESIDE = ("Placeholder Band", "Synthetic Song")
AUTO = ("Los Autómatas", "Canción Sintética")
CHINESE = ("宋冬野", "斑馬斑馬")
CAPO = ("Héroes del Silencio", "Entre Dos Tierras")
TRANSPOSED = ("Estopa", "Tu Calorro")
NO_KEY = ("Nadie", "Sin Acordes")
IGNORED = ("Café Tacvba", "Eres")
GONE = ("Fito Páez", "Mariposa Tecknicolor")
OLD_MOVE = ("Los Fabulosos Cadillacs", "Matador")
NO_DOC = ("Los Rotos", "Sin Documento")
NOT_UTF8 = ("Los Rotos", "Bytes Sueltos")
NOT_JSON = ("Los Rotos", "Sin JSON")
NO_CONTENT = ("Los Rotos", "Hoja Vacía")
BROKEN = {  # a kept sheet whose sheet.json can't be read: its bytes (None: there is none)
    NO_DOC: None,
    NOT_UTF8: b"\xff\xfe{}",
    NOT_JSON: b"{not json",
    NO_CONTENT: b'{"content": "  \\r\\n", "meta": []}',
}
LIBRARY = "{library}"  # the library's folder in a message, wherever the generator's and the replay's are

SHEET = (  # a UG chords sheet in G, as wiki_tab.content holds it (helpers/rendered.py's)
    "[Verse]\r\n"
    "[tab][ch]G[/ch]           [ch]D[/ch]\r\n"
    "Palabras de prueba[/tab]\r\n"
    "[tab][ch]Em[/ch]          [ch]C[/ch]\r\n"
    "solo para el visor[/tab]\r\n"
)
MINOR = (  # in A minor, played with a capo of 2
    "[Intro]\n"
    "[tab][ch]Am[/ch]        [ch]G[/ch]        [ch]F[/ch]       [ch]E7[/ch]\n"
    "Tierra de prueba, palabras al viento[/tab]\n"
    "[tab][ch]Am[/ch]   [ch]Dm[/ch]   [ch]E[/ch]\n"
    "entre dos ejemplos[/tab]\n"
)
NO_CHORDS = "[Verse]\nUna letra sin acordes\nque nadie toca\n"
TRADITIONAL = (  # test_render_hanzi.py's
    "[Verse]\n"
    "[tab][ch]C[/ch]       [ch]D[/ch]\n"
    "斑馬斑馬 你不要睡著啦[/tab]\n"
    "[tab][ch]Bm[/ch]          [ch]Em[/ch]\n"
    "我只想掀起你的頭髮[/tab]\n"
)
VIDEO = {"id": "dQw4w9WgXcQ", "title": "Canción  Sintética (audio)", "channel": "Los Autómatas - Topic"}

OVERRIDES = """\
[transpose]
"Estopa - Tu Calorro" = 2

[version]
"Héroes del Silencio - Entre Dos Tierras" = "key=Bm&capo=0"
"Los Fabulosos Cadillacs - Matador" = "t=2&mode=dorian"

[ignore]
songs = ["Café Tacvba - Eres"]
"""


# --- the library ---------------------------------------------------------------------------------------------------


def _record_written(conn, song, *names: str) -> None:
    """render.py's record of the viewers it wrote for ``song`` (kv ``render:files:<id>``), each as an empty page:
    the route reads the record alone."""
    from caracole.db import kv_get_json, kv_set_json
    from caracole.render import FILES_KEY

    record = kv_get_json(conn, f"{FILES_KEY}{song.id}") or {}
    for name in names:
        record[name] = {"sha256": hashlib.sha256(name.encode("utf-8")).hexdigest(), "size": len(name)}
    kv_set_json(conn, f"{FILES_KEY}{song.id}", record)


def _ug_sheet(conn, cfg, song, content: str, *, tab: int, key: str | None, capo: int | None = None) -> None:
    """A UG chords sheet kept as the fetch step keeps one: sheet.txt, and sheet.json beside it."""
    from helpers.ug_pages import version_dict

    from caracole.library import keep_file, song_dir, write_atomic
    from caracole.ug.page import strip_markup
    from caracole.versions import upsert_version

    raw = version_dict(tab, song=song.title, artist=song.artist, tonality_name=key or "")
    vid = upsert_version(conn, provider="ug", tab_id=str(raw["id"]), song_id=song.id, slot="sheet", kind="chords",
                         rating=4.5, votes=10, version=1, label=None, url=raw["tab_url"], raw=raw, now=FETCHED)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
              data=strip_markup(content).encode("utf-8"), rank=1)
    meta = {"capo": capo} if capo is not None else []
    doc = {"version": raw, "content": content, "url": raw["tab_url"], "meta": meta}
    write_atomic(song_dir(cfg.library_dir, song) / "sheet.json", json.dumps(doc, ensure_ascii=False).encode())


def _auto_sheet(conn, cfg, song, *, video: dict[str, str] | None = None) -> None:
    """An auto-chords sheet kept as the autochords step keeps one, from a YouTube video's audio with ``video``."""
    from caracole.autochords import ChordSegment, build_sheet
    from caracole.autochords.merge import youtube_credit
    from caracole.library import keep_file
    from caracole.versions import upsert_version

    source = youtube_credit(video["title"], video["channel"], video["id"]) if video else None
    text = build_sheet([ChordSegment(0.0, 4.0, "C"), ChordSegment(4.0, 8.0, "G"), ChordSegment(8.0, 12.0, "Am")],
                       title=song.title, artist=song.artist, source=source,
                       synced="[00:00.00]palabras de prueba\n[00:04.00]para el visor\n[00:08.00]y nada más\n")
    raw = {"youtube": video} if video else {}
    vid = upsert_version(conn, provider="auto", tab_id=f"auto-{song.id}", song_id=song.id, slot="sheet", kind="auto",
                         rating=0, votes=0, version=1, label=None, url="", raw=raw, now=FETCHED)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet (auto).txt", data=text.encode("utf-8"),
              rank=1)


def build_library(conn, cfg) -> dict[tuple[str, str], Any]:
    """The cases' library in ``conn`` (a fresh database), overrides.toml written to ``cfg``'s and held as the phone's
    rows too; the songs by (artist, title)."""
    from conftest import add_song
    from test_conformance_overrides import rows_of

    from caracole.library import song_dir
    from caracole.songs import get_song

    phone_schema(conn)
    songs = {}
    for n, names in enumerate((SODA, BESIDE, AUTO, CHINESE, CAPO, TRANSPOSED, NO_KEY, IGNORED, GONE, OLD_MOVE,
                               *BROKEN)):
        songs[names] = add_song(conn, *names, added_at=f"2026-10-02T00:{n:02d}:00Z")
    _ug_sheet(conn, cfg, songs[SODA], SHEET, tab=85001, key="G")
    _record_written(conn, songs[SODA], "sheet.cho", "sheet.html", "version-85002.html", "harmonica-1.html")
    _auto_sheet(conn, cfg, songs[BESIDE])
    _ug_sheet(conn, cfg, songs[BESIDE], SHEET, tab=85003, key="G")
    _record_written(conn, songs[BESIDE], "sheet.html", "sheet (auto).html")
    _auto_sheet(conn, cfg, songs[AUTO], video=VIDEO)
    _record_written(conn, songs[AUTO], "sheet (auto).html")
    _ug_sheet(conn, cfg, songs[CHINESE], TRADITIONAL, tab=85004, key=None)
    _record_written(conn, songs[CHINESE], "sheet.html")
    _ug_sheet(conn, cfg, songs[CAPO], MINOR, tab=85005, key="Am", capo=2)
    _record_written(conn, songs[CAPO], "sheet.html")
    _ug_sheet(conn, cfg, songs[TRANSPOSED], SHEET, tab=85006, key="G")
    _record_written(conn, songs[TRANSPOSED], "sheet.html")
    _ug_sheet(conn, cfg, songs[NO_KEY], NO_CHORDS, tab=85007, key=None)
    _record_written(conn, songs[NO_KEY], "sheet.html")
    _ug_sheet(conn, cfg, songs[IGNORED], SHEET, tab=85008, key="G")
    _record_written(conn, songs[IGNORED], "sheet.html")
    _record_written(conn, songs[GONE], "sheet.html")
    _ug_sheet(conn, cfg, songs[OLD_MOVE], SHEET, tab=85009, key="G")
    _record_written(conn, songs[OLD_MOVE], "sheet.html")
    for n, (names, doc) in enumerate(BROKEN.items()):
        _ug_sheet(conn, cfg, songs[names], SHEET, tab=85010 + n, key="G")
        _record_written(conn, songs[names], "sheet.html")
        path = song_dir(cfg.library_dir, songs[names]) / "sheet.json"
        if doc is None:
            path.unlink()
        else:
            path.write_bytes(doc)
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (FETCHED, FETCHED))
    conn.execute("UPDATE files SET created_at = ?", (FETCHED,))
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(OVERRIDES, encoding="utf-8")
    for row in rows_of(cfg.overrides_file):
        conn.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)",
                     (row["tbl"], row["key"], row["written"], row["value"]))
    return {names: get_song(conn, s.id) for names, s in songs.items()}


@contextmanager
def _library(tmp: Path) -> Iterator[tuple[Any, Any, dict[tuple[str, str], Any]]]:
    """A config over ``tmp`` and its database with the cases' library: (cfg, conn, songs)."""
    from caracole.config import load_config

    cfg = load_config(None, env={"HOME": str(tmp / "home"), "STATE_DIRECTORY": str(tmp / "state"),
                                 "CACHE_DIRECTORY": str(tmp / "cache")})
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    with closing(db.connect(cfg.db_path)) as conn:
        songs = build_library(conn, cfg)
        yield cfg, conn, songs


# --- GET /export.pdf -----------------------------------------------------------------------------------------------


@contextmanager
def _labels_alone() -> Iterator[None]:
    """``render.version_pdf`` as the phone answers it: the label alone (``ExportSheet.label``), no PDF. Where the
    sheet's words aren't Chinese it is checked against the label ``_export_text`` gives the PDF itself."""
    from caracole import render

    def labelled(conn, cfg, song, v, *, traditional: bool = False, **_: Any) -> tuple[str, bytes]:
        sheet = render.export_sheet(conn, cfg, song)
        label = sheet.label(v, traditional=traditional)
        if not sheet.chinese():
            assert render._export_text(conn, cfg, song, v, None, traditional=traditional).label == label
        return label, b""

    with mock.patch.object(render, "version_pdf", labelled):
        yield


def _app(cfg, *, full: bool = False):
    from caracole.web.app import WebApp
    from caracole.web.jobs import JobQueue

    def runner(args, emit):  # nothing runs: the queue is never started
        raise AssertionError(f"a route ran {args}")

    return WebApp(cfg, JobQueue(runner, limit=0 if full else 20), allowed=frozenset({"localhost"}), csrf="tok")


def _asked(cfg, case: str, target: str, *, method: str = "GET", full: bool = False) -> dict[str, Any]:
    """One request's record: caracole serve's route over a fresh queue, its answer and what it queued."""
    from urllib.parse import unquote

    from caracole.web.export_routes import export_pdf

    app = _app(cfg, full=full)
    try:
        with _labels_alone():
            response = export_pdf(app, target, change=method == "GET")
    except Refused as e:
        out: dict[str, Any] = {"status": e.status, "title": e.title, **_said(cfg, e.message)}
    else:
        disposition = next(v for k, v in response.headers if k == "Content-Disposition")
        name = unquote(disposition.split("filename*=UTF-8''", 1)[1])
        label = name[name.rindex(" (") + 2:-len(").pdf")]
        jobs = app.queue.snapshot()
        assert len(jobs) <= 1, (case, jobs)
        job = None
        if jobs:
            j = jobs[0]
            job = {"title": j.title, "key": j.song_key, "steps": [[s.label, list(s.args)] for s in j.steps],
                   "display": j.display, "song": j.song_id}
        out = {"status": response.status, "name": name, "label": label, "job": job}
    return {"fn": "GET /export.pdf", "case": case, "target": target, "method": method, "full": full, "out": out}


def _said(cfg, message: str, name: str = "message") -> dict[str, Any]:
    """A refusal's ``message`` as a record holds it: the library's folder named ``{library}``, and a file that couldn't
    be read named up to the reader's own words (``prefix``), which only caracole's own words before them match."""
    message = message.replace(str(cfg.library_dir), LIBRARY)
    for read in ("cannot read ",):
        at = message.find(read + LIBRARY)
        end = message.find(": ", at + len(read)) if at >= 0 else -1
        if end >= 0 and message[end - len(".json"):end] == ".json":
            return {name: message[:end + 2], "prefix": True}
    return {name: message}


def _target(sheet: str | None, query: str = "", *, encode: bool = True) -> str:
    """The viewer's link: ``/export.pdf?sheet=<its path>&<its address after #>``."""
    parts = [] if sheet is None else [f"sheet={quote(sheet, safe='/') if encode else sheet}"]
    if query:
        parts.append(query)
    return "/export.pdf?" + "&".join(parts)


def _query(**fields: Any) -> str:
    """A version's address as the viewer writes it (``version_query``)."""
    from caracole.viewer.version import Version, version_query

    return version_query(Version(**fields))


def requests(cfg, songs) -> list[dict[str, Any]]:
    soda = "/".join((*_folder(SODA), "sheet.html"))
    out = []
    a = out.append
    # the song's own human sheet, in its versions
    a(_asked(cfg, "the song's own version: an address naming none", _target(soda)))
    a(_asked(cfg, "two up, capo 0", _target(soda, "t=2&capo=0")))
    a(_asked(cfg, "the viewer's reading settings beside the version", _target(soda, "t=2&capo=0&fs=20&necks=0&py=1")))
    a(_asked(cfg, "a mode alone", _target(soda, "mode=dorian")))
    a(_asked(cfg, "a capo alone", _target(soda, "capo=3")))
    a(_asked(cfg, "one down", _target(soda, "t=-1")))
    a(_asked(cfg, "a move past the octave", _target(soda, "t=14")))
    a(_asked(cfg, "on the ukulele", _target(soda, "inst=ukulele")))
    a(_asked(cfg, "on the piano, two up", _target(soda, "t=2&inst=piano")))
    a(_asked(cfg, "on the guitar, named", _target(soda, "inst=guitar")))
    a(_asked(cfg, "an instrument there is none of", _target(soda, "inst=banjo")))
    a(_asked(cfg, "a chord's shape chosen", _target(soda, _query(t=2, at={0: 1}))))
    a(_asked(cfg, "a chord swapped in a mode", _target(soda, _query(mode="dorian", alt={"dorian": {1: (2, "m", None)}}))))
    a(_asked(cfg, "Traditional characters asked of a sheet in none", _target(soda, "t=2&capo=0&trad=1")))
    a(_asked(cfg, "the sheet named twice: the first counts", _target(soda, "sheet=Nobody/Nothing/sheet.html&t=2")))
    a(_asked(cfg, "its path written as the viewer encodes it", _target(soda, "t=2", encode=False)))
    a(_asked(cfg, "a HEAD", _target(soda, "t=2"), method="HEAD"))
    # Make this my version
    a(_asked(cfg, "mine: queued", _target(soda, "t=2&capo=0&mine=1")))
    a(_asked(cfg, "mine with no version: the song's own", _target(soda, "mine=1")))
    a(_asked(cfg, "mine that isn't 1", _target(soda, "t=2&mine=yes")))
    a(_asked(cfg, "mine twice: the first counts", _target(soda, "t=2&mine=0&mine=1")))
    a(_asked(cfg, "mine on a HEAD: nothing queued", _target(soda, "t=2&mine=1"), method="HEAD"))
    a(_asked(cfg, "mine on a full queue", _target(soda, "t=2&mine=1"), full=True))
    a(_asked(cfg, "a full queue with no mine", _target(soda, "t=2"), full=True))
    # the other sheets
    beside = "/".join(_folder(BESIDE))
    a(_asked(cfg, "the auto sheet beside a human one", _target(f"{beside}/sheet (auto).html", "t=2")))
    a(_asked(cfg, "the auto sheet beside a human one, mine", _target(f"{beside}/sheet (auto).html", "t=2&mine=1")))
    a(_asked(cfg, "the human sheet an auto one is beside", _target(f"{beside}/sheet.html", "t=2")))
    auto = "/".join((*_folder(AUTO), "sheet (auto).html"))
    a(_asked(cfg, "an auto sheet alone", _target(auto)))
    a(_asked(cfg, "an auto sheet alone, a version", _target(auto, "t=3&mode=mixolydian")))
    a(_asked(cfg, "an auto sheet alone, mine", _target(auto, "t=3&mine=1")))
    chinese = "/".join((*_folder(CHINESE), "sheet.html"))
    a(_asked(cfg, "a Chinese sheet, in Simplified characters", _target(chinese, "t=2")))
    a(_asked(cfg, "a Chinese sheet, in Traditional ones", _target(chinese, "t=2&trad=1")))
    a(_asked(cfg, "a Chinese sheet, trad that isn't 1", _target(chinese, "t=2&trad=0&trad=1")))
    a(_asked(cfg, "a Chinese sheet, mine in Traditional", _target(chinese, "t=2&trad=1&mine=1")))
    capo = "/".join((*_folder(CAPO), "sheet.html"))
    a(_asked(cfg, "a [version] kept by its key: an address naming none", _target(capo)))
    a(_asked(cfg, "a [version] kept by its key: another instrument", _target(capo, "inst=ukulele")))
    a(_asked(cfg, "a [version] kept by its key: a mode, no t", _target(capo, "mode=dorian")))
    a(_asked(cfg, "a [version] kept by its key: mine", _target(capo, "t=1&capo=3&mine=1")))
    transposed = "/".join((*_folder(TRANSPOSED), "sheet.html"))
    a(_asked(cfg, "[transpose]: an address naming none", _target(transposed)))
    a(_asked(cfg, "[transpose]: a capo, no t", _target(transposed, "capo=0")))
    a(_asked(cfg, "[transpose]: mine where it plays", _target(transposed, "t=2&mine=1")))
    no_key = "/".join((*_folder(NO_KEY), "sheet.html"))
    a(_asked(cfg, "a sheet with no key", _target(no_key, "t=2")))
    a(_asked(cfg, "a sheet with no key, mine", _target(no_key, "t=2&mine=1")))
    ignored = "/".join((*_folder(IGNORED), "sheet.html"))
    a(_asked(cfg, "an ignored song: the route reads no [ignore]", _target(ignored, "t=2&mine=1")))
    # refusals
    a(_asked(cfg, "no sheet", "/export.pdf?t=2"))
    a(_asked(cfg, "nothing at all", "/export.pdf"))
    a(_asked(cfg, "an empty sheet", _target("", "t=2")))
    a(_asked(cfg, "a sheet of one part", _target("sheet.html", "t=2")))
    a(_asked(cfg, "a sheet up the tree", _target("../sheet.html", "t=2")))
    a(_asked(cfg, "a sheet with an empty part", _target("Soda Stereo//sheet.html", "t=2")))
    a(_asked(cfg, "a sheet with a dot part", _target("Soda Stereo/./sheet.html", "t=2")))
    a(_asked(cfg, "no song's folder", _target("Nobody/Nothing/sheet.html", "t=2")))
    a(_asked(cfg, "the song's PDF, no viewer", _target(soda.replace(".html", ".pdf"), "t=2")))
    a(_asked(cfg, "the song's .cho, recorded", _target(soda.replace(".html", ".cho"), "t=2")))
    a(_asked(cfg, "a songbook's page", _target(soda.replace("sheet.html", "songbook.html"), "t=2")))
    a(_asked(cfg, "the library page", _target(soda.replace("sheet.html", "index.html"), "t=2")))
    a(_asked(cfg, "an auto viewer never written", _target(soda.replace("sheet.html", "sheet (auto).html"), "t=2")))
    a(_asked(cfg, "a kept version's page", _target(soda.replace("sheet.html", "version-85002.html"), "t=2")))
    a(_asked(cfg, "a kept version's page, mine", _target(soda.replace("sheet.html", "version-85002.html"),
                                                          "t=2&mine=1")))
    a(_asked(cfg, "a version's page never written", _target(soda.replace("sheet.html", "version-99999.html"), "t=2")))
    a(_asked(cfg, "a harmonica tab's page", _target(soda.replace("sheet.html", "harmonica-1.html"), "t=2")))
    a(_asked(cfg, "a viewer whose sheet is no longer kept", _target("/".join((*_folder(GONE), "sheet.html")), "t=2")))
    a(_asked(cfg, "a sheet's path in another case", _target(soda.lower(), "t=2")))
    a(_asked(cfg, "an address too long", _target(soda, "t=2&" + "x" * 2000)))
    base = _target(soda, "t=2&x=").removeprefix("/export.pdf?")
    a(_asked(cfg, "an address of 2000 characters", "/export.pdf?" + base + "y" * (2000 - len(base))))
    a(_asked(cfg, "an address of 2001 characters", "/export.pdf?" + base + "y" * (2001 - len(base))))
    a(_asked(cfg, "a NUL in a value", _target(soda, "t=2%00")))
    a(_asked(cfg, "a control character in a value", _target(soda, "fs=%1F")))
    a(_asked(cfg, "DEL in a value", _target(soda, "fs=%7F")))
    a(_asked(cfg, "a control character in a name", _target(soda, "f%01s=2")))
    a(_asked(cfg, "an escape that isn't UTF-8", _target(soda, "t=%ff%fe")))
    a(_asked(cfg, "an escape that isn't UTF-8 in a name", _target(soda, "%ff=2")))
    a(_asked(cfg, "sixty fields", _target(soda, "&".join(f"f{n}=1" for n in range(59)))))
    a(_asked(cfg, "sixty-one fields", _target(soda, "&".join(f"f{n}=1" for n in range(60)))))
    a(_asked(cfg, "a field with no value and no =", _target(soda, "t=2&necks")))
    a(_asked(cfg, "a plus for a space", _target(soda.replace(" ", "+"), "t=2", encode=False)))
    a(_asked(cfg, "its path as the viewer's URLSearchParams writes it, '/' as %2F",
             "/export.pdf?" + urlencode([("sheet", soda)]) + "&t=2&capo=0"))
    # a [version] written before, a move with no key
    old_move = "/".join((*_folder(OLD_MOVE), "sheet.html"))
    a(_asked(cfg, "a [version] that is a move: an address naming none", _target(old_move)))
    a(_asked(cfg, "a [version] that is a move: another instrument", _target(old_move, "inst=piano")))
    a(_asked(cfg, "a [version] that is a move: a capo, no t", _target(old_move, "capo=2")))
    a(_asked(cfg, "a [version] that is a move: mine", _target(old_move, "t=1&mine=1")))
    # a kept sheet whose sheet.json can't be read
    for names in BROKEN:
        broken = "/".join((*_folder(names), "sheet.html"))
        a(_asked(cfg, f"a sheet.json that can't be read: {names[1]}", _target(broken, "t=2")))
        a(_asked(cfg, f"a sheet.json that can't be read, mine: {names[1]}", _target(broken, "t=2&mine=1")))
    return out


def _folder(names: tuple[str, str]) -> tuple[str, str]:
    from caracole.library import song_folder

    return song_folder(*names)


# --- ExportSheet and Make this my version --------------------------------------------------------------------------


SHEETS = (  # (song, case, query)
    (SODA, "no version: the song's own", ""),
    (SODA, "the sheet as written", "t=0"),
    (SODA, "two up, capo 0", "t=2&capo=0"),
    (SODA, "two up, its capo the sheet's", "t=2"),
    (SODA, "a capo of 5, the same key", "t=-5&capo=5"),
    (SODA, "dorian", "mode=dorian"),
    (SODA, "the relative minor", "mode=aeolian"),
    (SODA, "a shape chosen", "t=2&at=0.1"),
    (SODA, "a chord swapped", "alt=ionian.1.2.m."),
    (SODA, "on the ukulele", "inst=ukulele"),
    (SODA, "on the piano, three up", "t=3&inst=piano&capo=2"),
    (SODA, "on the baritone, a shape", "inst=baritone&at=2.1"),
    (BESIDE, "the human sheet", "t=1"),
    (AUTO, "an auto sheet: its own", ""),
    (AUTO, "an auto sheet: a version", "t=3&mode=mixolydian"),
    (CHINESE, "a Chinese sheet", "t=2"),
    (CAPO, "a [version] kept by its key: its own", ""),
    (CAPO, "a [version] kept by its key: the sheet as written", "t=0"),
    (CAPO, "a [version] kept by its key: capo 3, one up", "t=1&capo=3"),
    (CAPO, "a [version] kept by its key: on the ukulele", "inst=ukulele"),
    (TRANSPOSED, "[transpose]: its own", ""),
    (TRANSPOSED, "[transpose]: where it plays", "t=2"),
    (TRANSPOSED, "[transpose]: the sheet as written", "t=0"),
    (TRANSPOSED, "[transpose]: a capo, no t", "capo=4"),
    (NO_KEY, "a sheet with no key", "t=2"),
    (NO_KEY, "a sheet with no key: as written", ""),
    (IGNORED, "an ignored song's sheet", "t=2&capo=0"),
    (OLD_MOVE, "a [version] that is a move: its own", ""),
    (OLD_MOVE, "a [version] that is a move: the sheet as written", "t=0"),
    (OLD_MOVE, "a [version] that is a move: a mode, no t", "mode=aeolian"),
)


def sheets(cfg, conn, songs) -> list[dict[str, Any]]:
    from caracole.overrides import load_overrides
    from caracole.render import export_query, export_sheet, export_version

    overrides = load_overrides(cfg.overrides_file)
    out = []
    for names, case, query in SHEETS:
        sheet = export_sheet(conn, cfg, songs[names])
        own = sheet.own(overrides)
        v = export_version(query, own)
        out.append({"fn": "render.ExportSheet", "case": case, "song": songs[names].id, "query": query,
                    "out": {"own": export_query(own), "version": export_query(v), "label": sheet.label(v),
                            "traditional": sheet.label(v, traditional=True), "entry": sheet.entry(v),
                            "kept": sheet.kept(v, overrides)}})
    return out


class _Failed(Exception):
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


MINE = (  # (case, song's name as given, query)
    ("two up, capo 0", "Soda Stereo - De Música Ligera", "t=2&capo=0"),
    ("the sheet as written: the [version] goes", "Soda Stereo - De Música Ligera", "t=0"),
    ("the name spelled otherwise", "soda stereo - de musica ligera", "t=2&capo=0"),
    ("a [version] kept by its key, another", "Héroes del Silencio - Entre Dos Tierras", "t=1&capo=3"),
    ("a [version] kept by its key, as written: it goes", "Héroes del Silencio - Entre Dos Tierras", "t=0"),
    ("[transpose], where it plays: none written", "Estopa - Tu Calorro", "t=2"),
    ("[transpose], another", "Estopa - Tu Calorro", "t=4&capo=1"),
    ("a sheet with no key: a move", "Nadie - Sin Acordes", "t=2"),
    ("an auto sheet", "Los Autómatas - Canción Sintética", "t=3&mode=mixolydian"),
    ("on the ukulele", "Soda Stereo - De Música Ligera", "inst=ukulele&t=2"),
    ("a Chinese sheet in Traditional", "宋冬野 - 斑馬斑馬", "t=2&trad=1"),
    ("an ignored song", "Café Tacvba - Eres", "t=2"),
    ("no such song", "Nobody - Nothing", "t=2"),
    ("not a song's name", "Nothing", "t=2"),
    ("a song whose sheet is no longer kept", "Fito Páez - Mariposa Tecknicolor", "t=2"),
    ("a [version] that is a move, another: kept by its key", "Los Fabulosos Cadillacs - Matador", "t=4&capo=0"),
    ("a [version] that is a move, as written: it goes", "Los Fabulosos Cadillacs - Matador", "t=0"),
    *((f"a sheet.json that can't be read: {names[1]}", " - ".join(names), "t=2") for names in BROKEN),
)


def mines(cfg, conn) -> list[dict[str, Any]]:
    from caracole.commands import _common, render as render_cmd
    from caracole.overrides import load_overrides, override_key

    out = []
    for case, name, query in MINE:
        cfg.overrides_file.write_text(OVERRIDES, encoding="utf-8")
        said: list[str] = []

        def fail(message: str, code: int = 1):
            raise _Failed(message, code)

        args = ["render", f"--song={name}", f"--version={query}", "--mine"]
        with mock.patch.object(_common, "fail", fail), mock.patch.object(typer, "echo", said.append):
            try:
                render_cmd._make_mine(conn, cfg, load_overrides(cfg.overrides_file), name, query)
            except _Failed as e:
                result: dict[str, Any] = {"exit": e.code, **_said(cfg, str(e), "error")}
            else:
                versions = load_overrides(cfg.overrides_file).version
                result = {"said": said, "version": versions.get(override_key(name))}
        out.append({"fn": "render --mine", "case": case, "args": args, "out": result})
    cfg.overrides_file.write_text(OVERRIDES, encoding="utf-8")
    return out


# --- the vector ----------------------------------------------------------------------------------------------------


def test_export_routes_vectors(tmp_path):
    with _library(tmp_path) as (cfg, conn, songs):
        fixture = dump_fixture(conn, cfg.library_dir)
        records = [{"fn": "fixture", "records": fixture}]
        records += requests(cfg, songs)
        records += sheets(cfg, conn, songs)
        records += mines(cfg, conn)
    check(EXPORT, jsonl(records, corpus="web/export", made_by=MADE_BY))
