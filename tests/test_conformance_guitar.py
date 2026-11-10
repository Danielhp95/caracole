"""The Guitar Pro page and alphaTab's bundle, for the phone: tests/conformance/vectors/web/guitar.jsonl, which the
Kotlin port's ``server.guitar`` (``AlphaTabBundle``, ``GuitarPage``), ``routes.GuitarRoutes`` and :core's
``inbox.GuitarFiles`` replay (lane guitar-alphatab: ``server.testing.replays.GuitarReplay``), and the app's
GuitarPageTest checks the APK by.

The page and the routes are given a bundle of stand-ins (``STANDINS``: alphaTab's three file names, each a few bytes);
alphaTab's own files, nix/alphatab.nix's through ``CARACOLE_ALPHATAB_DIR``, are recorded by their SHA-256 alone, with
the bundle they make. A record a line:

- ``{"fn": "caracole.web.alphatab.bundle", "args": [library, font_uri, sound_font], "out": text}`` and
  ``{"fn": "caracole.web.alphatab.font_face", "args": [font_uri], "out": text}``: the one script and the stylesheet
  alphaTab adds, whole;
- ``{"fn": "caracole.web.alphatab.load", "case": "stand-ins", "files": {name: base64}, "out": {...}}``: the bundle of
  ``files`` (``name``, ``href``, ``integrity``, ``script_source``, ``font_face``, ``sha256`` and ``length`` of its
  body, and the body itself), or ``"err": "Missing"`` for files that make none (a library that isn't UTF-8, a file
  missing);
- ``{"fn": "caracole.web.alphatab.load", "case": "nix/alphatab.nix", "files": {name: sha256}, "licenses": {name:
  sha256}, "out": {...}}``: alphaTab 1.8.4's own bundle, the same members less the body, and the licences beside the
  files (``licenses/``), which the APK carries beside the bundle;
- ``{"fn": "caracole.web.guitar_page.style" | ".script", "out": {"sha256_source", "length"}}`` and
  ``{"fn": "caracole.web.guitar_page.policy", "out": text}`` (the stand-ins' bundle);
- ``{"fn": "caracole.web.guitar_page.build_page", "kw": {title, artist, song_id, path, label, data, sheet,
  library_name}, "out": {"sha256", "length"}}``: the page of the stand-ins' bundle, ``data`` a fixture reference or
  ``{"base64": …}``, ``library_name`` ``[name, badge]`` or null; one of them ``"page"`` whole too;
- ``{"fn": "library", "records": [...], "outside": [...], "make": [...], "library_name": [name, badge]}``: the library
  every record after it reads (``helpers.corpus.dump_fixture``, its database and files), then what the replay makes
  after loading it: ``outside``, files out of the library (``{"path", "base64"}``), and ``make``, ``{"zeros": path,
  "size": n}`` (a file of ``n`` zero bytes, sparse where it can be) or ``{"link": path, "to": outside path}`` (a
  symbolic link in place of a file or of a song's folder); and the library's name as caracole serve's pages name it
  (the phone's badge);
- ``{"fn": "caracole.inbox.guitar_files", "kw": {song_id?, path?}, "out": [[song_id, name, path, number,
  in_browser], ...]}``;
- ``{"fn": "GET", "target", "alphatab": true | false, "out": {"status", "headers", "sha256", "length", "title"?,
  "message"?}}``: caracole serve's answer to a GET of ``target`` (``WebApp.handle``, its headers whole, its body by
  digest), with the stand-ins' bundle or with none, and a refusal's title and message
  (``guitar_routes.guitar`` and ``asset``'s ``Refused``).

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_guitar.py``.
"""

from __future__ import annotations

import base64
import hashlib
import os
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import pytest
from helpers.corpus import FIXTURES, VECTORS, check, dump_fixture, fixture_ref, jsonl
from helpers.guitar import SYNTHETIC, alphatab_dir, keep_guitar

from caracole import db
from caracole.inline import sha256_source
from caracole.library import song_dir
from caracole.library_name import LibraryName
from caracole.web import alphatab, guitar_page, guitar_routes
from caracole.web.pages import Refused

MADE_BY = "tests/test_conformance_guitar.py"
VECTOR = VECTORS / "web" / "guitar.jsonl"

# alphaTab's three files, stood in for: a library with a letter past ASCII (the bundle is UTF-8), a font and a
# SoundFont of bytes no text decodes.
STANDINS = {
    alphatab.LIBRARY: "/*! alphaTab, as far as the phone's tests go: é */\n!function(t){t.alphaTab={}}(this);\n"
                      .encode("utf-8"),
    alphatab.FONT: b"wOF2\x00\x01\xff a stand-in font",
    alphatab.SOUND_FONT: b"sfbk\x80\xfe a stand-in SoundFont",
}
NAME = LibraryName("Music", "Phone")  # the library's name on the phone, after a sync gave it
STAMP = "2026-10-01T00:00:00Z"
SYNTHETIC_BYTES = SYNTHETIC.read_bytes()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def standins(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in STANDINS.items():
        (folder / name).write_bytes(data)
    return folder


def bundle_out(at: alphatab.AlphaTab, *, body: bool) -> dict[str, Any]:
    out = {"name": at.name, "href": at.href, "integrity": at.integrity, "script_source": at.script_source,
           "font_face": at.font_face, "sha256": sha(at.body), "length": len(at.body)}
    if body:
        out["body"] = at.body.decode("utf-8")
    return out


# --- the bundle ------------------------------------------------------------------------------------------------------


FONT_URIS = ["data:font/woff2;base64,", "data:font/woff2;base64," + b64(STANDINS[alphatab.FONT])]


def bundle_records(tmp: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for library, font_uri, sound_font in (
        ("", "", ""),
        (STANDINS[alphatab.LIBRARY].decode("utf-8"), FONT_URIS[1], b64(STANDINS[alphatab.SOUND_FONT])),
        ('"use strict"; window.x = "</script>\\u2028 — 宋";\n', FONT_URIS[0], "AAAA"),
    ):
        out.append({"fn": "caracole.web.alphatab.bundle", "args": [library, font_uri, sound_font],
                    "out": alphatab.bundle(library, font_uri, sound_font)})
    for font_uri in FONT_URIS:
        out.append({"fn": "caracole.web.alphatab.font_face", "args": [font_uri], "out": alphatab.font_face(font_uri)})

    at = alphatab.load(standins(tmp / "standins"))
    out.append({"fn": "caracole.web.alphatab.load", "case": "stand-ins",
                "files": {name: b64(data) for name, data in STANDINS.items()}, "out": bundle_out(at, body=True)})
    # Files that make no bundle: a library that isn't UTF-8, a file missing.
    for case, files in (("a library that isn't UTF-8", {**STANDINS, alphatab.LIBRARY: b"\xff\xfe not UTF-8"}),
                        ("no SoundFont", {k: v for k, v in STANDINS.items() if k != alphatab.SOUND_FONT})):
        folder = tmp / case.replace(" ", "-").replace("'", "")
        folder.mkdir()
        for name, data in files.items():
            (folder / name).write_bytes(data)
        with pytest.raises(alphatab.Missing):
            alphatab.load(folder)
        out.append({"fn": "caracole.web.alphatab.load", "case": case,
                    "files": {name: b64(data) for name, data in files.items()}, "err": "Missing"})

    real = alphatab_dir()
    at = alphatab.load(real)
    licences = sorted(p for p in (real / "licenses").iterdir() if p.is_file())
    out.append({"fn": "caracole.web.alphatab.load", "case": "nix/alphatab.nix",
                "files": {name: sha((real / name).read_bytes()) for name in alphatab.FILES},
                "licenses": {p.name: sha(p.read_bytes()) for p in licences},
                "out": bundle_out(at, body=False)})
    return out


# --- the page --------------------------------------------------------------------------------------------------------


def page_records(at: alphatab.AlphaTab) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [
        {"fn": "caracole.web.guitar_page.style",
         "out": {"sha256_source": sha256_source(guitar_page.style()), "length": len(guitar_page.style())}},
        {"fn": "caracole.web.guitar_page.script",
         "out": {"sha256_source": sha256_source(guitar_page.script()), "length": len(guitar_page.script())}},
        {"fn": "caracole.web.guitar_page.policy", "out": guitar_page.policy(at)},
    ]
    synthetic = fixture_ref(SYNTHETIC)
    small = {"base64": b64(b"FICHIER GUITAR PRO v5.00\x00\xff")}
    cases = [
        # (title, artist, song_id, path, label, data, sheet, library_name)
        ("Synthetic Étude", "caracole tests", 1, "caracole tests/Synthetic Étude/guitar-1.gp", "Guitar Pro 1",
         synthetic, None, None),
        ("De Música Ligera", "Soda Stereo", 7, "Soda Stereo/De Música Ligera/guitar-2.gp5", "Guitar Pro 2",
         synthetic, "Soda Stereo/De Música Ligera/sheet.html", NAME),
        ("Canción #1?", "Ñandú & <Co>", 12, "Ñandú & <Co>/Canción #1?/guitar-10.gpx", "Guitar Pro 10", small,
         "Ñandú & <Co>/Canción #1?/sheet (auto).html", LibraryName("", "Phone")),
        ('<script>"x" & \'y\'</script>', "", 3, "a/b/guitar-3.gp4", "Guitar Pro 3", small, None,
         LibraryName('<b>"Tabs" & chords</b>', "Phone")),
        ("宋冬野的歌", "宋冬野, 董小姐", 99999999999, "宋冬野/安和桥 🎸/guitar-1.gp3", "Guitar Pro 1",
         {"base64": ""}, "宋冬野/安和桥 🎸/sheet.html", LibraryName("Music", None)),
        ("Tu calorro", "Estopa", 2, "Estopa/Tu calorro/guitar-1.gp5", "Guitar Pro 1", small,
         "Estopa/Tu calorro/sheet.html", LibraryName("Dani's songs", "Phone")),
    ]
    for n, (title, artist, song_id, path, label, data, sheet, name) in enumerate(cases):
        raw = SYNTHETIC_BYTES if "fixture" in data else base64.b64decode(data["base64"])
        page = guitar_page.build_page(title=title, artist=artist, song_id=song_id, path=path, label=label, data=raw,
                                      at=at, sheet=sheet, library_name=name)
        encoded = page.encode("utf-8")
        record: dict[str, Any] = {
            "fn": "caracole.web.guitar_page.build_page",
            "kw": {"title": title, "artist": artist, "song_id": song_id, "path": path, "label": label, "data": data,
                   "sheet": sheet, "library_name": None if name is None else [name.name, name.badge]},
            "out": {"sha256": sha(encoded), "length": len(encoded)},
        }
        if n == 2:
            record["page"] = page
        out.append(record)
    return out


# --- the library and the routes --------------------------------------------------------------------------------------


@contextmanager
def _library(tmp: Path):
    from caracole.config import load_config

    cfg = load_config(None, env={"HOME": str(tmp / "home"), "STATE_DIRECTORY": str(tmp / "state"),
                                 "CACHE_DIRECTORY": str(tmp / "cache")})
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    with closing(db.connect(cfg.db_path)) as conn:
        yield cfg, conn


def _version(conn, song, *, kind: str, tab: str) -> int:
    from caracole.versions import upsert_version

    return upsert_version(conn, provider="gtptabs", tab_id=tab, song_id=song.id, slot="guitar", kind=kind, rating=4,
                          votes=0, version=1, label=None, url=f"https://gtptabs.com/tabs/{tab}.html", raw={},
                          now="2026-10-01T00:00:00Z")


def build_library(cfg, conn) -> dict[str, Any]:
    """The songs and files the routes are asked about; what the replay makes after the fixture is loaded."""
    from caracole.library import keep_file
    from conftest import add_song

    paths: dict[str, str] = {}

    def keep(song, name: str, data: bytes, tab: str, *, kind: str | None = None) -> str:
        if kind is None:
            keep_guitar(conn, cfg, song, data, name=name, tab=tab)
        else:
            keep_file(conn, cfg.library_dir, song=song, version_id=_version(conn, song, kind=kind, tab=tab),
                      name=name, data=data, rank=1)
        (path,) = conn.execute("SELECT path FROM files WHERE song_id = ? AND name = ?", (song.id, name)).fetchone()
        return path

    study = add_song(conn, "caracole tests", "Synthetic Étude")
    paths["plain"] = keep(study, "guitar-1.gp", SYNTHETIC_BYTES, "1")

    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    paths["with a sheet"] = keep(soda, "guitar-2.gp5", SYNTHETIC_BYTES + b"\x02", "2")
    paths["ten"] = keep(soda, "guitar-10.gp5", SYNTHETIC_BYTES + b"\x0a", "10")
    paths["power tab"] = keep(soda, "guitar-9.ptb", b"ptab a stand-in", "9")
    paths["one, padded"] = keep(soda, "guitar-01.gp3", SYNTHETIC_BYTES + b"\x01", "11")
    paths["upper case"] = keep(soda, "guitar-3.GP5", SYNTHETIC_BYTES + b"\x03", "13")
    paths["another kind"] = keep(soda, "guitar-4.gp5", SYNTHETIC_BYTES + b"\x04", "14", kind="chords")
    paths["not guitar pro"] = keep(soda, "guitar-5.txt", b"a text", "15", kind="guitar-pro")
    paths["capital G"] = keep(soda, "Guitar-6.gp5", SYNTHETIC_BYTES + b"\x06", "16", kind="guitar-pro")
    paths["arabic digit"] = keep(soda, "guitar-٧.gp4", SYNTHETIC_BYTES + b"\x07", "17", kind="guitar-pro")
    folder = song_dir(cfg.library_dir, soda)
    (folder / "sheet.html").write_text("<!doctype html><title>a stand-in viewer</title>\n", encoding="utf-8")
    (folder / "guitar-8.gp5").write_bytes(SYNTHETIC_BYTES + b"\x08")  # put there by hand: no record
    paths["by hand"] = (folder / "guitar-8.gp5").relative_to(cfg.library_dir).as_posix()

    nandu = add_song(conn, "Ñandú & <Co>", "Canción #1?")
    paths["markup in its names"] = keep(nandu, "guitar-1.gpx", SYNTHETIC_BYTES + b"\x11", "21")
    folder = song_dir(cfg.library_dir, nandu)
    (folder / "sheet (auto).html").write_text("<!doctype html><title>an auto viewer</title>\n", encoding="utf-8")

    pdf_first = add_song(conn, "Estopa", "Tu Calorro")
    paths["a PDF before the auto viewer"] = keep(pdf_first, "guitar-1.gp5", SYNTHETIC_BYTES + b"\x12", "22")
    folder = song_dir(cfg.library_dir, pdf_first)
    (folder / "sheet.pdf").write_bytes(b"%PDF-1.4 a stand-in\n")
    (folder / "sheet (auto).html").write_text("<!doctype html><title>an auto viewer</title>\n", encoding="utf-8")

    chinese = add_song(conn, "宋冬野", "安和桥 🎸")
    paths["chinese"] = keep(chinese, "guitar-1.gp", SYNTHETIC_BYTES + b"\x13", "23")

    big = add_song(conn, "caracole tests", "Too Large")
    paths["too large"] = keep(big, "guitar-1.gp5", SYNTHETIC_BYTES + b"\x14", "24")
    huge = add_song(conn, "caracole tests", "Past The Limit")
    paths["past the limit"] = keep(huge, "guitar-1.gp5", SYNTHETIC_BYTES + b"\x15", "25")
    gone = add_song(conn, "caracole tests", "Gone")
    paths["gone"] = keep(gone, "guitar-1.gp", SYNTHETIC_BYTES + b"\x16", "26")
    linked = add_song(conn, "caracole tests", "A Link In Its Place")
    paths["a link in its place"] = keep(linked, "guitar-1.gp", SYNTHETIC_BYTES + b"\x17", "27")
    moved = add_song(conn, "caracole tests", "A Folder That Is A Link")
    paths["a folder that is a link"] = keep(moved, "guitar-1.gp", SYNTHETIC_BYTES + b"\x18", "28")

    # The times SQLite's clock and the songs' writers stamped, fixed: the vector is the same on every run.
    conn.execute("UPDATE files SET created_at = ?", (STAMP,))
    conn.execute("UPDATE songs SET created_at = ?, updated_at = ?", (STAMP, STAMP))
    records = dump_fixture(conn, cfg.library_dir)
    # The files the replay makes itself: a file past 8 MiB, one past 64 MiB, a file gone, and links.
    made_by_replay = {paths[k] for k in ("too large", "past the limit", "gone", "a link in its place")}
    moved_folder = song_dir(cfg.library_dir, moved).relative_to(cfg.library_dir).as_posix()
    records = [r for r in records
               if not ("file" in r and (r["file"] in made_by_replay or r["file"].startswith(moved_folder + "/")))]
    outside = [{"path": "elsewhere.gp", "base64": b64(SYNTHETIC_BYTES)},
               {"path": "moved/guitar-1.gp", "base64": b64(SYNTHETIC_BYTES + b"\x18")}]
    make: list[dict[str, Any]] = [
        {"zeros": paths["too large"], "size": guitar_routes.MAX_FILE + 1},
        {"zeros": paths["past the limit"], "size": 64 * 1024 * 1024 + 1},
        {"link": paths["a link in its place"], "to": "elsewhere.gp"},
        {"link": moved_folder, "to": "moved"},
    ]
    out_dir = cfg.library_dir.parent / "outside"
    for o in outside:
        (out_dir / o["path"]).parent.mkdir(parents=True, exist_ok=True)
        (out_dir / o["path"]).write_bytes(base64.b64decode(o["base64"]))
    for m in make:
        if "zeros" in m:
            with open(cfg.library_dir / m["zeros"], "wb") as f:
                f.truncate(m["size"])
        else:
            target = cfg.library_dir / m["link"]
            if target.is_dir():
                for child in target.iterdir():
                    child.unlink()
                target.rmdir()
            else:
                target.unlink()
            target.symlink_to(out_dir / m["to"])
    (cfg.library_dir / paths["gone"]).unlink()
    return {"record": {"fn": "library", "records": records, "outside": outside, "make": make,
                       "library_name": [NAME.name, NAME.badge]}, "paths": paths}


def guitar_files_records(conn, paths: dict[str, str]) -> list[dict[str, Any]]:
    from caracole.inbox import guitar_files

    song_ids = [row[0] for row in conn.execute("SELECT id FROM songs ORDER BY id")]
    asks: list[dict[str, Any]] = [{}]
    asks += [{"song_id": i} for i in song_ids] + [{"song_id": 999}]
    asks += [{"path": p} for p in sorted(paths.values())] + [{"path": "nowhere/guitar-1.gp"}]
    asks += [{"song_id": song_ids[1], "path": paths["with a sheet"]}, {"song_id": song_ids[0], "path": paths["ten"]}]
    out = []
    for kw in asks:
        found = guitar_files(conn, **kw)
        out.append({"fn": "caracole.inbox.guitar_files", "kw": kw,
                    "out": [[f.song_id, f.name, f.path, f.number, f.in_browser] for f in found]})
    return out


def _app(cfg, *, with_alphatab: Path | None):
    from caracole.web.app import WebApp
    from caracole.web.jobs import JobQueue

    def runner(args, emit):
        raise AssertionError(f"a route ran {args}")

    app = WebApp(replace(cfg, alphatab_dir=with_alphatab), JobQueue(runner), allowed=frozenset({"localhost"}),
                 csrf="tok", searches_lacuerda=False, searches_youtube=False)
    app.library_name = NAME
    return app


def guitar_target(path: str) -> str:
    return "/guitar?" + urlencode({"file": path})


def route_targets(paths: dict[str, str], at: alphatab.AlphaTab) -> list[str]:
    plain = paths["plain"]
    targets = ["/guitar", "/guitar?", "/guitar?file=", "/guitar?file", "/guitar?other=" + quote(plain, safe="")]
    targets += [guitar_target(p) for _, p in sorted(paths.items())]
    targets += [
        "/guitar?file=" + quote(plain, safe="/"),  # its slashes as they are
        "/guitar?file=" + plain.replace(" ", "+").replace("É", "%C3%89"),  # a space as a plus
        guitar_target(plain) + "&" + urlencode({"file": plain}),  # two files
        guitar_target(plain) + "&file=",  # a blank one after it, dropped
        guitar_target(plain) + "&a=1&b=2&c=3",  # four fields
        guitar_target(plain) + "&a=1&b=2&c=3&d=4",  # five: past parse_qs's limit
        guitar_target(plain) + "&&&&",
        "/guitar?file=%ff%fe",  # no UTF-8
        "/guitar?file=caracole%20tests%2F%C3",  # cut short in a letter
        guitar_target(plain + "\n"), guitar_target(plain + "\x7f"), guitar_target("\x1f" + plain),
        guitar_target(plain + ";x=1"), "/guitar?file=" + quote(plain, safe="") + ";x=1",
        guitar_target("../" + plain), guitar_target("/" + plain), guitar_target(plain.upper()),
        guitar_target("x" * guitar_routes.MAX_PATH), guitar_target("x" * (guitar_routes.MAX_PATH + 1)),
        guitar_target("é" * (guitar_routes.MAX_PATH + 1)),
        guitar_target(plain) + "#fragment",
        "/guitar/?file=" + quote(plain, safe=""),
        "/%67uitar?file=" + quote(plain, safe=""),  # its path percent-encoded
    ]
    targets += [
        "/assets/alphatab/" + at.name, "/assets/alphatab/" + at.name + "?v=1", "/assets/alphatab/",
        "/assets/alphatab", "/assets/alphatab/alphaTab.min.js", "/assets/alphatab/Bravura.woff2",
        "/assets/alphatab/alphatab-1.8.4-0000000000000000.js", "/assets/alphatab/%2e%2e/" + at.name,
        "/assets/alphatab/" + at.name.upper(), "/assets/alphatab/" + at.name + "/", "/assets/alphatab/x/" + at.name,
        "/assets/alphatab/%61" + at.name[1:],
    ]
    return targets


def _refusal(app, target: str) -> Refused | None:
    """The guitar routes' own refusal of ``target``, as the route raises it (None: it answers, or another refuses)."""
    from urllib.parse import unquote, urlsplit

    try:
        path = unquote(urlsplit(target).path, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    try:
        if path == "/guitar":
            guitar_routes.guitar(app, target)
        elif path.startswith(guitar_routes.ASSETS):
            guitar_routes.asset(app, path[len(guitar_routes.ASSETS):])
    except Refused as e:
        return e
    return None


def route_records(cfg, paths: dict[str, str], tmp: Path) -> list[dict[str, Any]]:
    from caracole.web.app import Request

    folder = standins(tmp / "route-standins")
    at = alphatab.load(folder)
    out = []
    for with_alphatab in (True, False):
        app = _app(cfg, with_alphatab=folder if with_alphatab else None)
        targets = route_targets(paths, at)
        if not with_alphatab:  # a page, a refusal before alphaTab is asked for, the bundle and another name there
            targets = [guitar_target(paths["plain"]), guitar_target(paths["power tab"]), guitar_target(paths["gone"]),
                       guitar_target(paths["by hand"]), "/guitar?file=", "/assets/alphatab/" + at.name,
                       "/assets/alphatab/alphaTab.min.js", "/assets/alphatab/"]
        for target in targets:
            response = app.handle(Request("GET", target, {"host": "localhost", "sec-fetch-site": "same-origin"}))
            answer: dict[str, Any] = {"status": response.status, "headers": [list(h) for h in response.headers],
                                      "sha256": sha(response.body), "length": len(response.body)}
            refused = _refusal(app, target)
            if refused is not None:
                assert refused.status == response.status, target
                answer["title"] = refused.title
                answer["message"] = refused.message
            out.append({"fn": "GET", "target": target, "alphatab": with_alphatab, "out": answer})
    return out


# --- the vectors -----------------------------------------------------------------------------------------------------


def records(tmp: Path) -> list[dict[str, Any]]:
    out = bundle_records(tmp)
    at = alphatab.load(standins(tmp / "page-standins"))
    out += page_records(at)
    with _library(tmp / "library") as (cfg, conn):
        library = build_library(cfg, conn)
        out.append(library["record"])
        out += guitar_files_records(conn, library["paths"])
        out += route_records(cfg, library["paths"], tmp)
    return out


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> list[dict[str, Any]]:
    return records(tmp_path_factory.mktemp("guitar"))


def test_guitar_jsonl_is_the_guitar_pro_page_s_answers(made):
    check(VECTOR, jsonl(made, corpus="web/guitar", made_by=MADE_BY))


def test_the_cases_meet_what_they_name(made):
    routes = {(r["target"], r["alphatab"]): r["out"] for r in made if r["fn"] == "GET"}
    library = next(r for r in made if r["fn"] == "library")
    by_status: dict[int, set[str]] = {}
    for (target, _), out in routes.items():
        by_status.setdefault(out["status"], set()).add(out.get("title", ""))
    # A page, the bundle, and every refusal the routes make: Power Tab, past 8 MiB, not a file caracole keeps.
    assert by_status[200] == {""}
    assert {"Not a Guitar Pro file", "A Power Tab file", "Not in the library", "Not found"} <= by_status[404]
    assert by_status[413] == {"Too large"} and by_status[400] == {"Not an address"}
    assert by_status[503] == {"No alphaTab here"}
    pages = [out for (target, _), out in routes.items() if out["status"] == 200 and target.startswith("/guitar")]
    assert len(pages) >= 6
    bundle = [out for (target, _), out in routes.items() if out["status"] == 200 and target.startswith("/assets/")]
    assert bundle and all(["Access-Control-Allow-Origin", "*"] in out["headers"] for out in bundle)
    assert len(library["make"]) == 4
    found = {tuple(r["kw"].items()): r["out"] for r in made if r["fn"] == "caracole.inbox.guitar_files"}
    every = found[()]
    names = [row[1] for row in every]
    assert "guitar-٧.gp4" in names and "guitar-3.GP5" in names and "guitar-01.gp3" in names
    assert not {"guitar-4.gp5", "guitar-5.txt", "Guitar-6.gp5", "guitar-8.gp5"} & set(names)
    assert names.index("guitar-2.gp5") < names.index("guitar-10.gp5")
    real = next(r for r in made if r.get("case") == "nix/alphatab.nix")
    assert set(real["files"]) == set(alphatab.FILES) and real["licenses"]
    whole = [r for r in made if "page" in r]
    assert len(whole) == 1 and hashlib.sha256(whole[0]["page"].encode()).hexdigest() == whole[0]["out"]["sha256"]


def test_the_vectors_are_the_same_on_another_run(made, tmp_path_factory):
    assert records(tmp_path_factory.mktemp("again")) == made


def test_the_fixture_it_names_is_there():
    assert (FIXTURES / fixture_ref(SYNTHETIC)["fixture"]).read_bytes() == SYNTHETIC_BYTES
    assert os.path.getsize(SYNTHETIC) < 64 * 1024
