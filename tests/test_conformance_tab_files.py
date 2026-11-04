"""gtptabs.com's Guitar Pro files and MuseScore's links, for the phone's lane tab-files (core.sites' ``GtpTabsFetch``,
``GtpTabsPages`` and ``MuseScorePages``, the lookup's gtptabs stage) to replay: gtptabs.py's pages and files read,
gtptabs_fetch.py's pass for one song and its ``title_page``, get.py's gtptabs stage, and musescore.py's links.

**Pages and files** (``vectors/sites/gtptabs.jsonl``), a record a call, over tests/fixtures/gtptabs, tests/fixtures/guitar
and the pages and files helpers/gtptabs_site.py makes: ``page_url``, ``download_url``, ``https``, ``sitemap_name``,
``parse_page_url`` (``out`` the ``IndexRow``'s fields, or null), ``artist_keys``, ``title_key``, ``_title`` (``out``
``[title, version]``), ``parse_artist_page`` (``html`` a ``corpus.fixture_ref`` or ``{"text"}``, ``out`` each
``GtpTab``'s fields and its ``guitar``; a parse that raises records ``raises``: ``{"type", "message"}``) and ``sniff``
(``data`` a fixture's reference or ``{"base64"}``, ``out`` the extension or null). One ``sniff`` record of ``"case":
"seeded mutations"`` holds a ``base`` file and its ``mutations``, each bytes ``set`` (``[offset, byte]``) and a ``cut``
(the length kept, or null), with what sniff said of it: Guitar Pro 7's zips, read by their central directory alone, as
zipfile reads one.

**Lookups** (``vectors/lookup/gtptabs.jsonl``), scenario records (tests/helpers/scenario.py, the corpus spec's "Scenario
records"), each in a world of its own: gtptabs.com's index as the computer's sitemap read left it (``site_index.refresh``
over the fixture sitemaps, with more rows where a case says), the songs, files and kv the case needs, ``ignore`` as the
phone holds overrides.toml (``phone_overrides``), a client of provider ``gtptabs`` and the site's answers, every request
with caracole's own user agent (each record's ``agent``).

- ``gtptabs_fetch.gtptabs_files`` for one song as a lookup asks it (``only`` its id, ``refresh_index=False``: the phone
  reads no sitemap): ``out.result`` the stats (``tried``, ``errors``, ``budget_exhausted``, ``failures`` each ``[song
  id, the error's class, its message]``, ``sitemaps``, ``kept``, ``missing``).
- get.py's gtptabs stage (``fn`` ``caracole.get._Lookup.gtptabs``: ``out.result`` its ``[state, detail]``, a detail
  alone being ``done``'s), its envelope's words for a block, a spent budget, an error, a cooldown and a site turned off
  among them, with what each records (kv ``provider:gtptabs``); the settings as the phone keeps them (kv
  ``phone:settings``).

**title_page** (``vectors/sites/gtptabs_title_page.jsonl``): gtptabs_fetch.title_page over one index and library
(``fixture``), each case a song id and ``now`` with the page, or null.

**MuseScore** (``vectors/sites/musescore.jsonl``): ``parse_song_url``, ``sitemap_name``, ``title_key``, and
``song_pages`` over a fixture of ``musescore_index`` (the fixture sitemaps read by ``site_index.refresh``, with more pages
where a case says) and songs: each case a song id and ``limit`` with the pages, oldest first. It sends no request.

Stamps: songs.py's clock is ``ADDED`` while a world is made; keep_file's ``created_at``, SQLite's clock, is the
record's ``now`` once checked to be a time of that form now (what the phone's ``Kept.keepFile`` is given); a file kept
before a record is stamped ``ADDED``. ``write_info`` (info.json) is the viewer's, milestone 5's: no pass writes it here,
as the phone writes none.

Regenerate with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import base64
import io
import json
import random
import re
import struct
import warnings
import zipfile
import zlib
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

import pytest

from helpers.corpus import VECTORS, check, dump_fixture, fixture_bytes, fixture_ref, jsonl, phone_schema
from helpers.gtptabs_site import BASE, FakeGtpTabs, artist_page, entry, fixture, gp7_file, gp_file, gpx_file, ptb_file
from helpers.scenario import record
from helpers.zips import dated_entry

MADE_BY = "tests/test_conformance_tab_files.py"
SITES_FILE = VECTORS / "sites" / "gtptabs.jsonl"
TITLE_PAGE_FILE = VECTORS / "sites" / "gtptabs_title_page.jsonl"
MUSESCORE_FILE = VECTORS / "sites" / "musescore.jsonl"
LOOKUP_FILE = VECTORS / "lookup" / "gtptabs.jsonl"

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
STAMP = "2026-11-03T12:00:00Z"
ADDED = "2026-10-01T00:00:00Z"
SITEMAP_READ = datetime(2026, 10, 27, 3, 30, tzinfo=UTC)  # when the computer's nightly run read the sitemaps
LONG_AGO = "2026-09-20T12:00:00Z"  # more than 30 days before NOW
LATELY = "2026-10-20T12:00:00Z"  # less than 30 days before NOW
FETCHED = "2026-10-24T09:00:00Z"  # a page the cache holds from within 30 days
OLD_FETCH = "2026-09-01T09:00:00Z"  # a page the cache holds from before them
HTML = [["content-type", "text/html; charset=UTF-8"]]
BLUR = f"{BASE}/tabs/2/blur.html"
NOT_FOUND = "download_404.html"
MAINTENANCE = "<html><body><h1>Site maintenance</h1></body></html>"
HTML_PAGE = "<!DOCTYPE html><html><head><title>GtpTabs.com</title></head><body>Sorry</body></html>"
_STAMPED = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def text(s: str) -> dict[str, str]:
    return {"text": s}


def b64(data: bytes) -> dict[str, str]:
    return {"base64": base64.b64encode(data).decode("ascii")}


def page(name_or_html: str) -> dict[str, str]:
    """A fixture page of tests/fixtures/gtptabs by its name, else the text given."""
    return fixture_ref(f"gtptabs/{name_or_html}") if name_or_html.endswith(".html") and "<" not in name_or_html \
        else text(name_or_html)


def ok(body: str) -> dict[str, Any]:
    return {"status": 200, "headers": HTML, "body": page(body)}


def status(code: int, body: str = NOT_FOUND) -> dict[str, Any]:
    return {"status": code, "headers": HTML, "body": page(body)}


def file_answer(data: bytes, tab_id: int) -> dict[str, Any]:
    return {"status": 200, "headers": [["content-type", "application/octet-stream"],
                                       ["content-disposition", f"attachment; filename=tab-{tab_id}.gp5"]],
            "body": b64(data)}


def moved(to: str) -> dict[str, Any]:
    return {"status": 302, "headers": [["location", to], *HTML], "body": text("")}


def held(answer: dict[str, Any], at: str = FETCHED) -> dict[str, Any]:
    """An answer as the HTTP cache holds it."""
    return {"status": answer["status"], "fetched_at": at, "headers": {"content-type": HTML[0][1]},
            "body": answer["body"]}


def download(tab_id: int) -> str:
    return f"{BASE}/tabs/download/{tab_id}.html"


def raised(e: BaseException) -> dict[str, str]:
    return {"type": type(e).__name__, "message": str(e)}


# --- pages and files ----------------------------------------------------------------------------------------------


def _calls(fn: str, f, inputs: list[Any]) -> list[dict[str, Any]]:
    return [{"fn": f"caracole.gtptabs.{fn}", "args": [x], "out": f(x)} for x in inputs]


def _row(row) -> dict[str, Any] | None:
    return None if row is None else row._asdict()


URLS = [
    "http://gtptabs.com/tabs/2/blur.html", "https://gtptabs.com/tabs/2/blur.html",
    "http://gtptabs.com/tabs/2/blur/country-house.html", "http://gtptabs.com/tabs/2/blur/song-2-2.html",
    "http://gtptabs.com/tabs/2/blur/song-2.html", "http://gtptabs.com/tabs/2/blur/song-1.html",
    "http://gtptabs.com/tabs/2/blur/song-1000.html", "http://gtptabs.com/tabs/2/blur/song-02.html",
    "http://gtptabs.com/tabs/2/blur/2.html", "http://gtptabs.com/tabs/2/blur/-2.html", "http://gtptabs.com/tabs/2/blur/a--2.html",
    "http://gtptabs.com/tabs/2/beatles-the/yesterday-13.html", "http://gtptabs.com/tabs/18/rolling-stones-the.html",
    "http://gtptabs.com/tabs/20/the-the.html", "http://gtptabs.com/tabs/20/the.html", "http://gtptabs.com/tabs/20/the-the-the.html",
    "http://gtptabs.com/tabs/10/john-elton/crocodile-rock.html", "http://gtptabs.com/tabs/1/ac-dc/tnt.html",
    "http://gtptabs.com/tabs/1/---.html", "http://gtptabs.com/tabs/1/blur/---.html", "http://gtptabs.com/tabs/1/the-/x.html",
    "http://gtptabs.com/", "http://gtptabs.com/tabs/2/", "http://gtptabs.com/news/first.html",
    "http://gtptabs.com/advertisement.html", "http://gtptabs.com/ru/tabs/2/blur/country-house.html",
    "https://example.com/tabs/2/blur.html", "http://gtptabs.com/tabs/2/blur/a/b.html",
    "http://gtptabs.com/tabs/2/blur/song-2)[x](y.html", "http://gtptabs.com/tabs/2/Blur.html",
    "http://gtptabs.com/tabs/2/blur/song%202.html", "http://gtptabs.com/tabs/12345/blur.html",
    "http://gtptabs.com/tabs/1234/blur.html", "http://gtptabs.com/tabs/٢/blur.html", "http://gtptabs.com/tabs/2/blur",
    "http://gtptabs.com/tabs/2/blur.htm", "http://www.gtptabs.com/tabs/2/blur.html", "ftp://gtptabs.com/tabs/2/blur.html",
    "http://gtptabs.com/tabs/2/blur.html?x=1", "http://gtptabs.com/tabs/2/blur.html\n", "http://gtptabs.com/tabs/2/" + "a" * 200
    + ".html", "http://gtptabs.com/tabs/2/" + "a" * 201 + ".html", "http://gtptabs.com/tabs/download/12.html",
    "http://gtptabs.com/tabs/upload.html", "http://gtptabs.com/tabs/2/mötley.html", "",
]

NAMES = ["Blur", "The Beatles", "Elton John", "Ewan Dobson", "Stevie Ray Vaughan", "Simon & Garfunkel", "Mötley Crüe",
         "!!!", "", "AC/DC", "Guns N' Roses", "The The", "  Elton   John  ", "Beatles, The", "宋冬野", "Björk",
         "John Lennon & Yoko Ono", "a", "Sigur Rós", "Rolling Stones"]

TITLES = ["Song 2 - 2012 Remaster", "Coffee & TV", "Coffee And Tv", "Beetlebum", "Song 2 (Live)", "Yesterday (Remastered)",
          "", "!!!", "Tumbling Dice", "斑马斑马", "Crocodile Rock [Live]", "Here Comes the Sun - Remastered 2009",
          "Don't Stop Me Now", "Ça plane pour moi", "Time (8 String)"]

TITLE_TEXTS = ["Song 2 (2)", "Song 2", "Song 2 (Live)", "Song 2 (1000)", "Song 2(3)", "Song 2  (3)", "(3)", " (3)",
               "Song (٣)", "Song (03)", "Song (0)", "Song 2 (2) (3)", "Song (2) x", "", "Song (2)\n", "Song\n(2)",
               "Ça (12)", "Song (2 )", "Song (²)"]


def _artist(html: Any, url: str = BLUR) -> dict[str, Any]:
    from caracole.gtptabs import GtpTabsParseError, parse_artist_page

    if isinstance(html, dict):
        carried, body = html, fixture_bytes(html).decode("utf-8")
    else:
        carried, body = text(html), html
    rec: dict[str, Any] = {"fn": "caracole.gtptabs.parse_artist_page", "html": carried, "url": url}
    try:
        tabs = parse_artist_page(body, url)
    except GtpTabsParseError as e:
        rec["raises"] = raised(e)
    else:
        rec["out"] = [{**tab.__dict__, "instruments": list(tab.instruments), "guitar": tab.guitar} for tab in tabs]
    return rec


def mini(*entries: str, heading: str = '<div class="autorInfo"><h1>Artist "Somebody"</h1></div>') -> str:
    """An artist page of the captured one's frame alone: its heading and list, and these entries."""
    return f'<html><body>{heading}<div class="autorSongs">{"".join(entries)}</div></body></html>'


def item(tab_id: str = "7", href: str = "/tabs/2/blur/song-2.html", title: str = "Song 2", *, cls: str = "autorSong gp5",
         stars: int = 3, info: str | None = "(31.17 Kb)", labels: str = "") -> str:
    """One entry, as the captured page writes one but its whitespace."""
    actives = "".join('<a class="realActive active">1</a>' for _ in range(stars)) + '<a>5</a>'
    songinfo = "" if info is None else f'<div class="songInfo">{labels}{info}</div>'
    return (f'<div class="{cls}"><div class="title"><a href="{href}">{title}</a>'
            f'<div class="ratingSmall " data-model="Tab" data-item="{tab_id}">{actives}</div></div>{songinfo}</div>')


def label(*classes: str) -> str:
    return ('<div class="instrumentsSmall">' + "".join(f'<div class="labelSmall {c}"></div>' for c in classes)
            + "</div>")


def artist_records() -> list[dict[str, Any]]:
    blur = fixture("artist.html")
    out = [
        _artist(fixture_ref("gtptabs/artist.html")),
        _artist(blur.replace('href="/tabs/2/blur/beetlebum.html"', 'href="/storage/x.gp3"')),
        _artist(artist_page("Elton John", "tabs/10/john-elton.html",
                            entry(1, "tabs/10/john-elton/crocodile-rock.html", "Crocodile Rock", stars=5,
                                  instruments=("acoustic guitar",)),
                            entry(2, "tabs/10/john-elton/crocodile-rock-2.html", "Crocodile Rock (2)", fmt="gp4", stars=0,
                                  size="6000.00", instruments=("bass", "drums")),
                            entry(3, "tabs/10/john-elton/crocodile-rock-3.html", "Crocodile Rock (3)", fmt="ptb",
                                  stars=2, size="12"),
                            entry(4, "tabs/10/john-elton/crocodile-rock-4.html", "Crocodile Rock (4)", fmt="pdf"),
                            entry(5, "tabs/10/john-elton/rocket-man.html", "Rocket   Man", fmt="gp", stars=1,
                                  instruments=("vocals", "electric guitar"))),
                url=f"{BASE}/tabs/10/john-elton.html"),
        _artist("<html><body><h1>Site maintenance</h1></body></html>"),
        _artist(mini(heading='<div class="autorInfo"></div>')),
        _artist('<html><body><div class="autorInfo"><h1>Artist</h1></div></body></html>'),
        _artist('<html><body><div class="autorSongs"></div><div class="autorInfo"><h1>A</h1></div></body></html>'),
        _artist('<html><body><div class="autorInfo"><h2><h1>Deep</h1></h2></div><span class="autorSongs"></span></body>'
                '</html>'),
        _artist(mini()),
        _artist(mini(item(), item("8", title="Song 2 (2)", href="/tabs/2/blur/song-2-2.html", stars=0))),
        _artist(mini(*(item(tid) for tid in ("007", "1234567890123", "", "12a", "١٢", " 9", "999999999999")))),
        _artist(mini(*(item(str(n), info=i) for n, i in enumerate((
            "(12 Kb)", "( 12.5 kb )", "(12KB)", "(12.1234 Kb)", "(1234567 Kb)", "(12345678 Kb)", "(١٢ Kb)",
            "(12 Kb)", "(12 K b)", "size (3.27 Kb) Added by: x", "(.5 Kb)", "(5. Kb)", "(1 Kb)(2 Kb)", "",
            "(12 Kb)", "(\n12\nKb\n)", "(0 Kb)", "(00012.100 Kb)"), start=1)), item("99", info=None))),
        _artist(mini(*(item(str(n), cls=c) for n, c in enumerate((
            "autorSong gp3", "autorSong", "autorSong  gpx extra", "gp4 autorSong", "autorSong GP5", "autorSong\tgp",
            "autorSong ptb", "autorSong pdf", "autorSong autorSong gp5"), start=1)))),
        _artist(mini(*(item(str(n), labels=lb) for n, lb in enumerate((
            label("electroGuitarLabelSmall"), label("bassGuitarLabelSmall", "drumsLabelSmall"),
            label("keyboardsLabelSmall", "violinLabelSmall"), label("fluteLabelSmall"), label("weird"),
            label("electroGuitarLabelSmall extra"), label(""), '<div class="labelSmall electroGuitarLabelSmall"></div>',
            '<div class="instrumentsSmall"><span class="labelSmall vocalsLabelSmall"></span></div>',
            label("acousticGuitarLabelSmall", "acousticGuitarLabelSmall")), start=1)))),
        _artist(mini(*(item(str(n), href=h) for n, h in enumerate((
            "/tabs/2/blur/song-2.html", "https://gtptabs.com/tabs/2/blur/song-2.html", "/tabs/2/blur.html",
            "/tabs/2/Blur/x.html", "/ru/tabs/2/blur/x.html", "/tabs/2/blur/x.html?y", "tabs/2/blur/x.html",
            "/tabs/2/blur/x.html#a", "/tabs//x.html", "/tabs/2/the/x.html", "/tabs/2/blur/x-2.html"), start=1)))),
        _artist(mini(*(item(str(n), title=t) for n, t in enumerate((
            "Song 2 (2)", "  Song\n 2   (3) ", "Song &amp; Dance", "<b>Bold</b> (4)", "Song (٣)", "", "   ",
            "Song<!-- c --> (5)", "Song 2(6)", "Ça (7)"), start=1)))),
        _artist(mini('<div class="autorSong gp5"><div class="title"><a>No href</a>'
                     '<div class="ratingSmall" data-item="1"></div></div></div>',
                     '<div class="autorSong gp5"><div class="title"><a href="/tabs/2/blur/a.html">No rating</a></div></div>',
                     '<div class="autorSong gp5"><div class="title"><a href="/tabs/2/blur/b.html">No id</a>'
                     '<div class="ratingSmall"></div></div></div>',
                     '<div class="autorSong gp5"><div class="title"><span><a href="/tabs/2/blur/c.html">Not a child</a>'
                     '</span><div class="ratingSmall" data-item="3"></div></div></div>',
                     '<div class="autorSong gp5"><div class="title"><a href="/tabs/2/blur/d.html">D</a>'
                     '<a href="/tabs/2/blur/e.html">E</a><div class="ratingSmall" data-item="4"><a class="active">1</a>'
                     '<span><a class="active">2</a></span><a class="realActive">3</a></div></div></div>',
                     '<div class="autorSong gp5"><div class="title"><a href="">Empty</a>'
                     '<div class="ratingSmall" data-item="5"></div></div></div>',
                     '<div class="autorSong gp5"><div class="ratingSmall" data-item="6"></div><div class="title">'
                     '<a href="/tabs/2/blur/f.html">Rating first</a></div></div>',
                     '<div class="autorSong gp5"><div class="title"><a href="/tabs/2/blur/g.html">G</a>'
                     '<div class="ratingSmall" data-item="7" data-item="8"></div></div></div>')),
        _artist(mini(item("1")) + mini(item("2"))),
        _artist(mini('<div class="autorSongs"><div class="autorSong gp3"><div class="title">'
                     '<a href="/tabs/2/blur/nested.html">Nested</a><div class="ratingSmall" data-item="9"></div>'
                     '</div></div></div>')),
        _artist(mini(item("1"), item("1", title="Song 2 (2)", stars=5))),
        _artist(blur[: len(blur) // 2]),
    ]
    return out


def _sniffed(data: Any) -> dict[str, Any]:
    from caracole.gtptabs import sniff

    with warnings.catch_warnings():  # zipfile's, for an empty Unicode Path field: it reads the entry on
        warnings.simplefilter("ignore")
        if isinstance(data, dict):
            return {"fn": "caracole.gtptabs.sniff", "data": data, "out": sniff(fixture_bytes(data))}
        return {"fn": "caracole.gtptabs.sniff", "data": b64(data), "out": sniff(data)}


def _zip(entries: list[tuple[str, bytes]], *, comment: bytes = b"", flags: int = 0) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries:
            info = dated_entry(z, name)
            info.flag_bits |= flags
            z.writestr(info, data)
        z.comment = comment
    return buf.getvalue()


def _eocd(data: bytes) -> int:
    return data.rindex(b"PK\x05\x06")


def _cd(data: bytes) -> int:
    return struct.unpack("<L", data[_eocd(data) + 16:_eocd(data) + 20])[0]


def _with_cd_field(data: bytes, entry_index: int, offset: int, fmt: str, value: int) -> bytes:
    """``data`` with a field of its ``entry_index``-th central directory entry set."""
    at = _cd(data)
    for _ in range(entry_index):
        n, e, c = struct.unpack("<3H", data[at + 28:at + 34])
        at += 46 + n + e + c
    out = bytearray(data)
    struct.pack_into(fmt, out, at + offset, value)
    return bytes(out)


def _extra_cd(name: str, extra: bytes, *, csize: int | None = None, usize: int | None = None,
              header: int | None = None, raw_name: bytes | None = None) -> bytes:
    """A zip of one entry whose central directory entry carries ``extra`` (and these fields), written by hand."""
    data = b"x"
    name_b = raw_name if raw_name is not None else name.encode("utf-8")
    local = struct.pack("<4s5H3L2H", b"PK\x03\x04", 20, 0, 0, 0, 0x21, zlib.crc32(data), 1, 1, len(name_b), 0)
    body = local + name_b + data
    cd = struct.pack("<4s4B4HL2L5H2L", b"PK\x01\x02", 20, 3, 20, 0, 0, 0, 0, 0x21, zlib.crc32(data),
                     1 if csize is None else csize, 1 if usize is None else usize, len(name_b), len(extra), 0, 0, 0,
                     0, 0 if header is None else header)
    cd += name_b + extra
    end = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 1, 1, len(cd), len(body), 0)
    return body + cd + end


def _zip64(*, locator_disk: int = 0, disks: int = 1, record_ok: bool = True, size_fix: int = 0,
           extensible: bytes = b"", reloff_shift: int = 0) -> bytes:
    """Guitar Pro 7's zip with a zip64 end of central directory record and its locator before the plain one."""
    base = gp7_file()
    cd_at, eocd_at = _cd(base), _eocd(base)
    cd = base[cd_at:eocd_at]
    count = struct.unpack("<H", base[eocd_at + 10:eocd_at + 12])[0]
    rec64_at = cd_at + len(cd)
    rec64 = struct.pack("<4sQ2H2L4Q", b"PK\x06\x06" if record_ok else b"PK\x06\x00", 44 + len(extensible) + size_fix,
                        45, 45, 0, 0, count, count, len(cd), cd_at) + extensible
    locator = struct.pack("<4sLQL", b"PK\x06\x07", locator_disk, rec64_at + reloff_shift, disks)
    end = struct.pack("<4s4H2LH", b"PK\x05\x06", 0, 0, 0xFFFF, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0)
    return base[:eocd_at] + rec64 + locator + end


def zip_cases() -> list[bytes]:
    score = b"<GPIF/>"
    gp7 = gp7_file()
    cases = [
        gp7, gp7_file(score=False), _zip([("Content/score.gpif", score)]), _zip([("VERSION", b"7"), ("Content/", b"")]),
        _zip([("content/score.gpif", score)]), _zip([("Content\\score.gpif", score)]), _zip([("Content/score.gpif ", score)]),
        _zip([("x/Content/score.gpif", score)]), _zip([("Content/score.gpif", score)], comment=b"a comment"),
        _zip([("Content/score.gpif", score)], comment=b"PK\x05\x06 in the comment"),
        _zip([("Content/score.gpif", score)], comment=b"x" * 300),
        _zip([("Content/score.gpif", score)], flags=0x800), _zip([("Contént/score.gpif", score)]),
        _zip([("Content/score.gpif\x00.txt", score)]), _zip([("A", b"a"), ("B", b"b"), ("Content/score.gpif", score)]),
        gp7 + b"trailing", gp7[:-1], gp7[:-22], gp7[: len(gp7) // 2], b"PK\x03\x04", b"PK\x03\x04" + b"\x00" * 30,
        b"PK\x03\x04 not really a zip", gp7[:_cd(gp7)] + b"JUNK" + gp7[_cd(gp7):],
        _with_cd_field(gp7, 0, 0, "<4s", b"PK\x01\x03"), _with_cd_field(gp7, 1, 6, "<B", 64),
        _with_cd_field(gp7, 1, 6, "<B", 63), _with_cd_field(gp7, 1, 8, "<H", 0x800),
        _with_cd_field(gp7, 0, 28, "<H", 200), _with_cd_field(gp7, 1, 30, "<H", 5000),
        _zip64(), _zip64(locator_disk=1), _zip64(disks=2), _zip64(disks=0), _zip64(record_ok=False), _zip64(size_fix=1),
        _zip64(extensible=b"\x00" * 8), _zip64(reloff_shift=-4), _zip64(reloff_shift=100000),
        _extra_cd("Content/score.gpif", b""), _extra_cd("Content/score.gpif", struct.pack("<HH", 0xCAFE, 2) + b"ab"),
        _extra_cd("Content/score.gpif", struct.pack("<HH", 0xCAFE, 9) + b"ab"),
        _extra_cd("Content/score.gpif", struct.pack("<HH", 1, 8) + struct.pack("<Q", 1), usize=0xFFFFFFFF),
        _extra_cd("Content/score.gpif", struct.pack("<HH", 1, 4) + b"abcd", usize=0xFFFFFFFF),
        _extra_cd("Content/score.gpif", struct.pack("<HH", 1, 16) + struct.pack("<QQ", 1, 2), usize=0xFFFFFFFF,
                  csize=0xFFFFFFFF),
        _extra_cd("Content/score.gpif", struct.pack("<HH", 1, 8) + struct.pack("<Q", 1), csize=0xFFFFFFFF,
                  header=0xFFFFFFFF),
        _extra_cd("Content/score.gpif", struct.pack("<HH", 1, 8) + struct.pack("<Q", 0xFFFFFFFF) + struct.pack(
            "<HH", 1, 8) + struct.pack("<Q", 7), usize=0xFFFFFFFF),
        _extra_cd("Content/score.gpif", struct.pack("<HH", 1, 0), usize=0xFFFFFFFF),
        _extra_cd("Content/score.gpif", struct.pack("<HH", 1, 0)),
        _extra_cd("x", _unicode_path(b"x", "Content/score.gpif")),
        _extra_cd("x", _unicode_path(b"y", "Content/score.gpif")),
        _extra_cd("x", _unicode_path(b"x", "Content/score.gpif", version=2)),
        _extra_cd("Content/score.gpif", _unicode_path(b"Content/score.gpif", "other")),
        _extra_cd("x", _unicode_path(b"x", "Content/score.gpif\x00z")),
        _extra_cd("x", struct.pack("<HH", 0x7075, 3) + b"\x01ab"),
        _extra_cd("x", struct.pack("<HH", 0x7075, 5) + b"\x01" + struct.pack("<L", zlib.crc32(b"x"))[:4],
                  raw_name=b"x"),
        _extra_cd("x", struct.pack("<HH", 0x7075, 7) + b"\x01" + struct.pack("<L", zlib.crc32(b"x")) + b"\xff\xfe"),
        _extra_cd("x", struct.pack("<HH", 0x7075, 1) + b"\x01"),
        _extra_cd("", b"", raw_name=b"Content/score.gpif\xff"),
        _extra_cd("", b"", raw_name="Content/score.gpif".encode("cp437")),
        _extra_cd("", b"", raw_name=b"Content/scor\x82.gpif"),
    ]
    utf8_named = _zip([("Content/score.gpif", score)])
    cases += [_with_cd_field(utf8_named, 0, 8, "<H", 0x800)]
    bad_utf8 = _extra_cd("", b"", raw_name=b"Content/score.gpif\xc3")
    cases += [_with_cd_field(bad_utf8, 0, 8, "<H", 0x800)]
    surrogate = _extra_cd("", b"", raw_name=b"Content/score.gpif\xed\xa0\x80")
    cases += [_with_cd_field(surrogate, 0, 8, "<H", 0x800)]
    return cases


def _unicode_path(name: bytes, unicode_name: str, version: int = 1) -> bytes:
    data = struct.pack("<BL", version, zlib.crc32(name)) + unicode_name.encode("utf-8")
    return struct.pack("<HH", 0x7075, len(data)) + data


def mutations() -> dict[str, Any]:
    """Seeded edits of Guitar Pro 7's zip where its reader looks: the central directory and what ends the file."""
    from caracole.gtptabs import sniff

    base = gp7_file()
    rng = random.Random(20261104)
    cd = _cd(base)
    out = []
    for n in range(160):
        data = bytearray(base)
        edits = []
        for _ in range(rng.choice((1, 1, 2, 3))):
            at = rng.randrange(cd, len(base)) if rng.random() < 0.85 else rng.randrange(len(base))
            value = rng.choice((0, 0xFF, 1, rng.randrange(256)))
            data[at] = value
            edits.append([at, value])
        cut = rng.randrange(len(base) - 40, len(base)) if n % 9 == 0 else None
        mutated = bytes(data if cut is None else data[:cut])
        out.append({"set": edits, "cut": cut, "out": sniff(mutated)})
    return {"fn": "caracole.gtptabs.sniff", "case": "seeded mutations", "base": b64(base), "mutations": out}


def sniff_records() -> list[dict[str, Any]]:
    files = [
        gp_file(b"v3.00"), gp_file(b"v4.06"), gp_file(b"v5.10"), gp_file(b"v5.00"), gp_file(b"L4.06"), gp_file(b"v6.00"),
        gp_file(b"v2.21"), gp_file(b"v1.04", word=b"GUITARE"), gp_file(b"v5.0"), gp_file(b"v5.000"), gp_file(b"v3.0x"),
        gp_file(b"V5.00"), gp_file(b"v5.\xd9\xa0\xd9\xa0"), gpx_file(), b"BCFS" + b"\x00" * 40, b"BCFZ", b"BCF",
        ptb_file(), b"ptab", b"pta", b"PTAB" + b"\x00" * 40, b"", b"\x18FICHIER GUITAR PRO",
        b"\x18FICHIER GUITAR PRO v5.00", b"\x18FICHIER GUITAR PRO v5.00" + b"\x00" * 5,
        b"\x18FICHIER GUITAR PRO v5.00" + b"\x00" * 6, b"\x19FICHIER GUITAR PRO v5.00 " + b"\x00" * 10,
        b"\xffFICHIER GUITAR PRO v5.00" + b"\x00" * 10, b"\x00" + b"FICHIER GUITAR PRO v5.00" + b"\x00" * 10,
        b"\x18fichier guitar pro v5.00" + b"\x00" * 10, b"\x18FICHIER GUITAR PRO v5.00\nxx" + b"\x00" * 10,
        b"<!DOCTYPE html><html><body>Too many downloads</body></html>", b"\xef\xbb\xbfptab",
    ]
    out = [_sniffed(fixture_ref("guitar/synthetic.gp")), _sniffed(fixture_ref("gtptabs/download_404.html")),
           _sniffed(fixture_ref("guitar/synthetic.alphatex"))]
    out += [_sniffed(f) for f in files]
    out += [_sniffed(z) for z in zip_cases()]
    out.append(mutations())
    return out


def sites_records() -> list[dict[str, Any]]:
    from caracole import gtptabs as g

    out = _calls("page_url", g.page_url, ["tabs/2/blur.html", "tabs/2/blur/song-2.html", ""])
    out += _calls("download_url", g.download_url, [58155, 0, 7, 123456789012])
    out += _calls("https", g.https, ["http://gtptabs.com/tabs/2/blur.html", "https://gtptabs.com/x",
                                     "http://gtptabs.com", "http://gtptabs.com.evil/x", "http://example.com/", ""])
    out += _calls("sitemap_name", g.sitemap_name, [
        "http://gtptabs.com/sitemapGoogle6.xml", "https://gtptabs.com/sitemapGoogle1.xml",
        "http://gtptabs.com/sitemapYandex.xml", "https://example.com/sitemapGoogle1.xml",
        "https://gtptabs.com/sitemapGoogle12345.xml", "https://gtptabs.com/sitemapGoogle٣.xml",
        "https://gtptabs.com/sitemapGoogle.xml", ""])
    out += _calls("parse_page_url", lambda u: _row(g.parse_page_url(u)), URLS)
    out += _calls("artist_keys", lambda n: list(g.artist_keys(n)), NAMES)
    out += _calls("title_key", g.title_key, TITLES)
    out += _calls("_title", lambda t: list(g._title(t)), TITLE_TEXTS)
    return out + artist_records() + sniff_records()


def test_gtptabs_sites_jsonl():
    check(SITES_FILE, jsonl(sites_records(), corpus="sites/gtptabs", made_by=MADE_BY))


def test_the_pages_and_files_cover_each_outcome():
    records = sites_records()
    artists = [r for r in records if r["fn"].endswith("parse_artist_page")]
    assert {r["raises"]["type"] for r in artists if "raises" in r} == {"GtpTabsParseError"}
    assert any(r.get("out") == [] for r in artists)
    tabs = [t for r in artists for t in r.get("out", [])]
    assert any(t["size_kb"] is None for t in tabs) and any(not t["guitar"] for t in tabs)
    assert any(t["title"] == "Song" and t["version"] == 3 for t in tabs)  # "Song (٣)"
    sniffs = [r for r in records if r["fn"].endswith("sniff") and "out" in r]
    assert {r["out"] for r in sniffs} == {".gp3", ".gp4", ".gp5", ".gpx", ".gp", ".ptb", None}
    [mutated] = [r for r in records if r.get("case") == "seeded mutations"]
    assert {m["out"] for m in mutated["mutations"]} == {".gp", None}


# --- the worlds ---------------------------------------------------------------------------------------------------


@contextmanager
def clock() -> Iterator[None]:
    """songs.py's clock at ``ADDED``, and no info.json (the viewer's, milestone 5's)."""
    with mock.patch("caracole.songs.utc_now_iso", lambda: ADDED), \
            mock.patch("caracole.gtptabs_fetch.write_info", lambda *a, **k: None):
        yield


def rows_of(o, display: str) -> list[dict[str, str]]:
    """The phone's ``phone_overrides`` rows of ``o``, as the phone holds overrides.toml (phone.sql)."""
    from caracole import canonical as c
    from caracole.overrides import SONG_TABLES, song_entries

    rows = []
    keys = sorted({k for t in SONG_TABLES for k in getattr(o, t)} | set(o.ignore))
    for key in keys:
        entries = song_entries(o, key)
        for table in (*SONG_TABLES, "ignore"):
            if table in entries:
                rows.append({"tbl": table, "key": key, "written": display, "value": c.dumps(entries[table])})
    return sorted(rows, key=lambda r: (r["tbl"], r["key"]))


def _stamped(done: dict[str, Any], before: list[dict[str, Any]]) -> None:
    """keep_file's ``created_at``, SQLite's clock: each files row it wrote holds a time of that form now, recorded as
    ``STAMP``, the time the phone's writer is given."""
    old = {r["row"]["id"]: r["row"]["created_at"] for r in before if r.get("table") == "files"}
    for row in done["rows"].get("files", []):
        if old.get(row["id"]) == row["created_at"]:
            continue
        stamp = row["created_at"]
        assert _STAMPED.fullmatch(stamp), stamp
        at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        assert abs(datetime.now(UTC) - at) < timedelta(minutes=5), stamp
        row["created_at"] = STAMP


class World:
    """A phone's library: its database (gtptabs.com's index as the computer's sitemap read left it), its library
    folder, its config and its overrides."""

    def __init__(self, tmp: Path, name: str, *, toml: str = "", extra: tuple[str, ...] = (), index: bool = True,
                 whole: bool = False):
        from caracole import db
        from caracole.config import load_config

        self.dir = tmp / name
        self.dir.mkdir(parents=True)
        self.library = self.dir / "library"
        self.library.mkdir()
        (self.dir / "caracole.toml").write_text(
            f'library_dir = "{self.library}"\nstate_dir = "{self.dir / "state"}"\n'
            f'cache_dir = "{self.dir / "cache"}"\n{toml}', encoding="utf-8")
        self.cfg = load_config(self.dir / "caracole.toml", env={"HOME": str(self.dir / "home")})
        self.conn = db.connect(self.dir / "caracole.sqlite")
        phone_schema(self.conn)
        self.records = 0
        self.overrides = None
        if index:
            self.sitemaps(whole)
        self.index(*extra)

    def sitemaps(self, whole: bool) -> None:
        """gtptabs.com's index as the computer's nightly run reads it: the fixture sitemaps (the first alone unless
        ``whole``, which a lookup's songs need: a record carries its world)."""
        from caracole import site_index
        from caracole.gtptabs_fetch import SITE

        client = FakeGtpTabs().client(self.dir / "sitemap-cache", now=SITEMAP_READ)
        try:
            site_index.refresh(self.conn, client, SITE, SITEMAP_READ)
        finally:
            client.close()
        self.conn.execute("DELETE FROM kv WHERE key LIKE 'gtptabs:%'")  # the sitemaps' records: no lookup reads them
        if not whole:
            self.conn.execute("DELETE FROM gtptabs_index WHERE sitemap != '1'")

    def index(self, *urls: str) -> None:
        """More pages in the index, as a sitemap would list them."""
        from caracole.gtptabs import parse_page_url

        for u in urls:
            row = parse_page_url(u)
            assert row is not None, u
            self.conn.execute("INSERT OR REPLACE INTO gtptabs_index (path, artist_path, artist_key, title_key, "
                              "base_key, sitemap) VALUES (?, ?, ?, ?, ?, '6')", tuple(row))

    def song(self, artist: str, title: str, *, artists: list[str] | None = None, added: str = ADDED):
        from caracole.normalize import identity_key
        from caracole.songs import get_song, upsert_song

        with clock():
            song_id, _ = upsert_song(self.conn, artists=artists or [artist], title=title, album=None,
                                     duration_ms=None, isrc=None, source="wanted",
                                     source_id=identity_key(artist, title), added_at=added)
        return get_song(self.conn, song_id)

    def kv(self, key: str, value: str) -> None:
        from caracole.db import kv_set

        kv_set(self.conn, key, value)

    def keep(self, song, tab_id: str, name: str, data: bytes, *, kind: str = "guitar-pro",
             provider: str = "gtptabs") -> None:
        """A file the song keeps already, as a pass kept it."""
        from caracole.library import keep_file
        from caracole.versions import upsert_version

        version = upsert_version(self.conn, provider=provider, tab_id=tab_id, song_id=song.id, slot="guitar",
                                 kind=kind, rating=0.0, votes=0, version=1, label=None,
                                 url=f"{BASE}/tabs/x/{tab_id}.html", raw={}, now=ADDED)
        keep_file(self.conn, self.library, song=song, version_id=version, name=name, data=data, rank=1)
        self.conn.execute("UPDATE files SET created_at = ?", (ADDED,))

    def file(self, song, name: str, data: str) -> None:
        """A file of the song's folder caracole doesn't keep (put there by hand)."""
        from caracole.library import song_dir, write_atomic

        write_atomic(song_dir(self.library, song) / name, data.encode("utf-8"))

    def write_overrides(self, toml: str, display: str) -> None:
        from caracole.overrides import load_overrides

        path = self.dir / "overrides.toml"
        path.write_text(toml, encoding="utf-8")
        self.overrides = load_overrides(path)
        self.conn.execute("DELETE FROM phone_overrides")
        for row in rows_of(self.overrides, display):
            self.conn.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)",
                              (row["tbl"], row["key"], row["written"], row["value"]))

    def settings(self) -> None:
        """The config's settings as the phone keeps them (kv ``phone:settings``)."""
        from caracole.politeness import settings_document

        self.kv("phone:settings", json.dumps(settings_document(self.cfg)))

    def record(self, fn: str, case: str, call, kw: dict[str, Any], answers: dict[str, dict[str, Any]],
               cache: dict[str, Any] | None = None, budget: int = 6) -> dict[str, Any]:
        from caracole.config import DEFAULT_USER_AGENT

        self.records += 1
        with clock():
            made = record(self.conn, self.library, fn=fn, case=case, call=call, kw=kw, now=NOW,
                          clients={"gtptabs": {"budget": budget, "delay": [0.0, 0.0]}}, answers=answers,
                          cache={"gtptabs": cache} if cache else None, cache_dir=self.dir / f"cache-{self.records}")
        done = made.get("out") or made["after"]
        _stamped(done, made["fixture"])
        made["answers"] = {r: a for r, a in made["answers"].items() if r in done["requests"]}  # what was asked alone
        made["agent"] = DEFAULT_USER_AGENT
        return made

    def close(self) -> None:
        self.conn.close()


def stats_of(s) -> dict[str, Any]:
    """A pass's stats as a record holds them."""
    return {"tried": s.tried, "errors": s.errors, "budget_exhausted": s.budget_exhausted,
            "failures": [[song.id, type(e).__name__, str(e)] for song, e in s.failures],
            "sitemaps": s.sitemaps, "kept": s.kept, "missing": s.missing}


# --- gtptabs_fetch.gtptabs_files for one song, and get.py's stage -------------------------------------------------


ELTON = f"{BASE}/tabs/10/john-elton.html"


def artist(name: str, *entries: str) -> dict[str, Any]:
    """An artist's page of the captured frame's heading and list alone (the parser reads nothing else), these
    entries in the captured markup (helpers/gtptabs_site.entry)."""
    return ok(mini(*entries, heading=f'<div class="autorInfo"><h1>Artist "{name}"</h1></div>'))


def elton(*entries: str) -> dict[str, Any]:
    return artist("Elton John", *entries)


def rock(tab_id: int, n: int = 1, **kw: Any) -> str:
    path = "tabs/10/john-elton/crocodile-rock" + ("" if n == 1 else f"-{n}") + ".html"
    return entry(tab_id, path, "Crocodile Rock" + ("" if n == 1 else f" ({n})"), **kw)


class Lookups:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.n = 0
        self.records: list[dict[str, Any]] = []

    def world(self, **kw: Any) -> World:
        self.n += 1
        return World(self.tmp, f"lookup-{self.n}", **kw)

    def files(self, w: World, case: str, song, answers: dict[str, dict[str, Any]], *, cache=None, budget: int = 6):
        from caracole.gtptabs_fetch import gtptabs_files

        def call(made):
            return stats_of(gtptabs_files(w.conn, made["gtptabs"], w.library, NOW, overrides=w.overrides,
                                          only={song.id}, refresh_index=False))

        rec = w.record("caracole.gtptabs_fetch.gtptabs_files", case, call, {"only": [song.id]},
                       {f"GET {u}": a for u, a in answers.items()}, cache=cache, budget=budget)
        self.records.append(rec)
        return rec

    def stage(self, w: World, case: str, song, answers: dict[str, dict[str, Any]], *, cache=None, budget: int = 6):
        from caracole.get import LookupRequest, Progress, _Lookup
        from caracole.overrides import Overrides
        from caracole.songs import get_song

        w.settings()

        def call(made):
            lk = _Lookup(w.cfg, LookupRequest(song.artist, song.title), Progress(), runner=None, now=NOW,
                         clock=lambda: 0.0)
            lk.conn, lk.song, lk.overrides = w.conn, get_song(w.conn, song.id), w.overrides or Overrides()
            lk.clients = dict(made)
            out = lk.gtptabs()
            return list(out) if isinstance(out, tuple) else ["done", out]

        rec = w.record("caracole.get._Lookup.gtptabs", case, call, {"only": [song.id]},
                       {f"GET {u}": a for u, a in answers.items()}, cache=cache, budget=budget)
        self.records.append(rec)
        return rec

    def build(self) -> list[dict[str, Any]]:  # noqa: PLR0915 (one case after another)
        gp3, gp5, gpx, ptb, gp7 = gp_file(b"v3.00"), gp_file(b"v5.00"), gpx_file(), ptb_file(), gp7_file()

        w = self.world()
        self.files(w, "a song gets the best rated upload of its title, kept as guitar-1 with its version",
                   w.song("Blur", "Beetlebum"), {BLUR: ok("artist.html"), download(26): file_answer(gp3, 26)})
        w = self.world()
        self.files(w, "a page where the file should be is passed over and the next upload kept, its format by its bytes",
                   w.song("Blur", "Beetlebum"), {BLUR: ok("artist.html"), download(26): ok(HTML_PAGE),
                                                 download(58155): file_answer(gpx, 58155)})
        w = self.world()
        self.files(w, "a download the site no longer has is passed over for 30 days", w.song("Blur", "Beetlebum"),
                   {BLUR: ok("artist.html"), download(26): status(404), download(58155): file_answer(gp5, 58155)})
        w = self.world()
        song = w.song("Blur", "Beetlebum")
        w.kv("gtptabs:unusable:26", LATELY)
        self.files(w, "an upload passed over within 30 days isn't asked for", song,
                   {BLUR: ok("artist.html"), download(58155): file_answer(gp5, 58155)})
        w = self.world()
        song = w.song("Blur", "Beetlebum")
        w.kv("gtptabs:unusable:26", LONG_AGO)
        self.files(w, "an upload passed over more than 30 days ago is asked for again", song,
                   {BLUR: ok("artist.html"), download(26): file_answer(gp3, 26)})
        w = self.world()
        song = w.song("Blur", "Beetlebum")
        w.kv("gtptabs:unusable:26", "soon")
        self.files(w, "an unusable record that is no time is older than any", song,
                   {BLUR: ok("artist.html"), download(26): file_answer(gp3, 26)})
        four = elton(*(rock(n, n) for n in (1, 2, 3, 4)))
        w = self.world()
        self.files(w, "at most three downloads a song, then it waits", w.song("Elton John", "Crocodile Rock"),
                   {ELTON: four, **{download(n): status(404) for n in (1, 2, 3)}}, budget=8)
        w = self.world()
        self.files(w, "three pages in a row where files should be end the pass as an error",
                   w.song("Elton John", "Crocodile Rock"), {ELTON: four, **{download(n): ok(HTML_PAGE) for n in (1, 2, 3)}},
                   budget=8)
        w = self.world()
        self.files(w, "a page, a 404, then a page: two in a row never", w.song("Elton John", "Crocodile Rock"),
                   {ELTON: four, download(1): ok(HTML_PAGE), download(2): status(404), download(3): ok(HTML_PAGE)},
                   budget=8)
        w = self.world()
        self.files(w, "uploads are ranked by stars, then the first upload, then the lowest id",
                   w.song("Elton John", "Crocodile Rock"),
                   {ELTON: elton(rock(9, 1, stars=3), rock(4, 2, stars=5), rock(7, 3, stars=5), rock(2, 4, stars=3),
                                 rock(3, 3, stars=5)),
                    download(3): status(404), download(7): status(404), download(4): file_answer(gp5, 4)}, budget=8)
        w = self.world()
        self.files(w, "an upload listed twice is the last listing of it", w.song("Elton John", "Crocodile Rock"),
                   {ELTON: elton(rock(5, 1, stars=5), rock(6, 2, stars=4), rock(5, 3, stars=1)),
                    download(6): file_answer(gp5, 6)})
        w = self.world()
        self.files(w, "uploads with no guitar part, too big or of a format the library doesn't file are passed over",
                   w.song("Elton John", "Crocodile Rock"),
                   {ELTON: elton(rock(1, 1, stars=5, instruments=("bass", "drums")), rock(2, 2, stars=5, size="6000"),
                                 rock(3, 3, stars=5, fmt="pdf"), rock(4, 4, stars=1, instruments=("vocals", "acoustic guitar")),
                                 rock(5, 5, stars=0, size="5120")),
                    download(4): file_answer(ptb, 4)})
        w = self.world()
        self.files(w, "a title its artist's page doesn't list is a miss, asked about again after 30 days",
                   w.song("Elton John", "Crocodile Rock"), {ELTON: elton(entry(8, "tabs/10/john-elton/rocket-man.html",
                                                                               "Rocket Man"))})
        w = self.world()
        self.files(w, "uploads of none but formats the library doesn't file are a miss",
                   w.song("Elton John", "Crocodile Rock"), {ELTON: elton(rock(1, 1, fmt="pdf"))})
        w = self.world()
        song = w.song("Elton John", "Crocodile Rock")
        w.kv(f"gtptabs:checked:{song.id}", LATELY)
        self.files(w, "a song looked up there within 30 days asks nothing", song, {})
        w = self.world()
        song = w.song("Elton John", "Crocodile Rock")
        w.kv(f"gtptabs:checked:{song.id}", LONG_AGO)
        self.files(w, "a song looked up more than 30 days ago is asked about again", song,
                   {ELTON: elton(rock(1)), download(1): file_answer(gp5, 1)})
        w = self.world()
        song = w.song("Elton John", "Crocodile Rock")
        w.kv(f"gtptabs:checked:{song.id}", "2026-10-04T12:00:00+00:00")
        self.files(w, "a checked record of another form is read as a time", song, {})
        w = self.world()
        song = w.song("Elton John", "Crocodile Rock")
        w.kv(f"gtptabs:checked:{song.id}", "not a time")
        self.files(w, "a checked record that is no time is older than any", song,
                   {ELTON: elton(rock(1)), download(1): file_answer(gp5, 1)})
        w = self.world()
        self.files(w, "a song whose artist the index doesn't know costs nothing", w.song("Nobody Known", "Beetlebum"), {})
        w = self.world(index=False)
        self.files(w, "an empty index asks nothing", w.song("Blur", "Beetlebum"), {})
        w = self.world()
        self.files(w, "a title with no key has no candidate, and is a miss", w.song("Blur", "!!!"),
                   {BLUR: ok("artist.html")})
        w = self.world()
        song = w.song("Blur", "Beetlebum")
        w.write_overrides(f'[ignore]\nsongs = ["{song.display}"]\n', song.display)
        self.files(w, "an ignored song gets nothing", song, {})
        w = self.world()
        song = w.song("Blur", "Beetlebum")
        w.conn.execute("UPDATE songs SET status = 'ignored' WHERE id = ?", (song.id,))
        self.files(w, "a song of status ignored gets nothing", song, {})
        w = self.world()
        song = w.song("Blur", "Beetlebum")
        w.keep(song, "1", "guitar-1.gp5", gp5)
        self.files(w, "a song with a Guitar Pro file gets no other", song, {})
        w = self.world()
        song = w.song("Blur", "Beetlebum")
        w.keep(song, "1", "guitar-1.ptb", ptb, kind="power", provider="inbox")
        self.files(w, "a song with a Power Tab file filed from the inbox gets no other", song, {})
        w = self.world()
        song = w.song("Blur", "Beetlebum")
        w.keep(song, "1", "score-1.pdf", b"%PDF-1.4 a score", kind="score", provider="inbox")
        self.files(w, "a song keeping a score still gets a Guitar Pro file", song,
                   {BLUR: ok("artist.html"), download(26): file_answer(gp3, 26)})
        w = self.world()
        song = w.song("Blur", "Beetlebum")
        w.keep(song, "1", "score-1.gp3", gp3, kind="score", provider="inbox")
        self.files(w, "a download whose bytes the song keeps already under another name is recorded and not written",
                   song, {BLUR: ok("artist.html"), download(26): file_answer(gp3, 26)})
        w = self.world()
        song = w.song("Blur", "Beetlebum")
        w.file(song, "guitar-1.gp5", "put there by hand")
        w.file(song, "GUITAR-2.txt", "notes")
        self.files(w, "a number a file in the folder holds is never reused", song,
                   {BLUR: ok("artist.html"), download(26): file_answer(gp3, 26)})
        w = self.world()
        self.files(w, "a Guitar Pro 7 file is kept as .gp", w.song("Blur", "Beetlebum"),
                   {BLUR: ok("artist.html"), download(26): file_answer(gp7, 26)})
        w = self.world()
        self.files(w, "a Power Tab file is kept as a power version", w.song("Elton John", "Crocodile Rock"),
                   {ELTON: elton(rock(1, fmt="ptb")), download(1): file_answer(ptb, 1)})
        w = self.world()
        self.files(w, "a zip that holds no score is no file", w.song("Elton John", "Crocodile Rock"),
                   {ELTON: elton(rock(1, fmt="gp"), rock(2, 2)), download(1): file_answer(gp7_file(score=False), 1),
                    download(2): file_answer(gp5, 2)})
        w = self.world()
        self.files(w, "titles meet as caracole's keys do", w.song("Blur", "Song 2 - 2012 Remaster"),
                   {BLUR: ok("artist.html"), download(12): file_answer(gp3, 12)})
        w = self.world(extra=("http://gtptabs.com/tabs/1/ac-dc/tnt.html",))
        self.files(w, "an artist's key meets the index's with its hyphens aside", w.song("ACDC", "TNT"),
                   {f"{BASE}/tabs/1/ac-dc.html": artist("AC/DC", entry(41, "tabs/1/ac-dc/tnt.html", "T.N.T.")),
                    download(41): file_answer(gp5, 41)})
        w = self.world()
        self.files(w, "people are found under the site's Last, First", w.song("Elton John", "Crocodile Rock"),
                   {ELTON: elton(rock(1)), download(1): file_answer(gp5, 1)})
        w = self.world()
        self.files(w, "a band named The is found under the site's name", w.song("The Beatles", "Yesterday"),
                   {f"{BASE}/tabs/2/beatles-the.html": artist("Beatles, The", entry(
                       13, "tabs/2/beatles-the/yesterday.html", "Yesterday", stars=4)),
                    download(13): file_answer(gp5, 13)})
        w = self.world()
        self.files(w, "a song of two artists reads both artists' pages", w.song(
            "Blur & Elton John", "Crocodile Rock", artists=["Blur", "Elton John"]),
            {BLUR: ok("artist.html"), ELTON: elton(rock(1)), download(1): file_answer(gp5, 1)})
        w = self.world(extra=("http://gtptabs.com/tabs/2/blur/song-2-2.html", "http://gtptabs.com/tabs/22/blur.html"))
        self.files(w, "an artist of two pages reads both, in order", w.song("Blur", "Song 2"),
                   {BLUR: ok("artist.html"), f"{BASE}/tabs/22/blur.html": status(404),
                    download(12): file_answer(gp3, 12)})
        w = self.world()
        self.files(w, "a song uploaded after the sitemaps is found on its artist's page, its title's spellings met",
                   w.song("Blur", "Coffee & TV"), {BLUR: ok("artist.html"), download(79720): file_answer(gp5, 79720)})
        w = self.world()
        self.files(w, "a title whose one upload has no guitar part is a miss", w.song("Blur", "Oily Water"),
                   {BLUR: ok("artist.html")})
        w = self.world()
        self.files(w, "an artist's page gone has no tab, and the song is a miss", w.song("Blur", "Beetlebum"),
                   {BLUR: status(404)})
        w = self.world()
        self.files(w, "a page that isn't an artist page is an error, never a miss", w.song("Blur", "Beetlebum"),
                   {BLUR: ok(MAINTENANCE)})
        w = self.world()
        self.files(w, "a cached page that won't parse is asked for once more, and read", w.song("Blur", "Beetlebum"),
                   {BLUR: ok("artist.html"), download(26): file_answer(gp3, 26)},
                   cache={f"GET {BLUR}": held(ok(MAINTENANCE))})
        w = self.world()
        self.files(w, "a cached page that won't parse, asked again, is an error", w.song("Blur", "Beetlebum"),
                   {BLUR: ok(MAINTENANCE)}, cache={f"GET {BLUR}": held(ok(MAINTENANCE))})
        w = self.world()
        self.files(w, "an artist's page the cache holds from within 30 days is read from it", w.song("Blur", "Beetlebum"),
                   {download(26): file_answer(gp3, 26)}, cache={f"GET {BLUR}": held(ok("artist.html"))})
        w = self.world()
        self.files(w, "an artist's page cached more than 30 days ago is asked for again", w.song("Blur", "Beetlebum"),
                   {BLUR: ok("artist.html"), download(26): file_answer(gp3, 26)},
                   cache={f"GET {BLUR}": held(ok("artist.html"), OLD_FETCH)})
        w = self.world()
        self.files(w, "an old copy with the budget spent is no answer for today", w.song("Blur", "Beetlebum"), {},
                   cache={f"GET {BLUR}": held(ok("artist.html"), OLD_FETCH)}, budget=0)
        w = self.world()
        self.files(w, "a spent budget ends the pass, the song checked never", w.song("Blur", "Beetlebum"),
                   {BLUR: ok("artist.html")}, budget=1)
        w = self.world()
        self.files(w, "a block propagates and keeps nothing", w.song("Blur", "Beetlebum"), {BLUR: status(403, HTML_PAGE)})
        w = self.world()
        self.files(w, "a 429 on a download is a block too", w.song("Blur", "Beetlebum"),
                   {BLUR: ok("artist.html"), download(26): status(429, HTML_PAGE)})
        w = self.world()
        self.files(w, "a server error leaves the song for the next run", w.song("Blur", "Beetlebum"),
                   {BLUR: status(500, HTML_PAGE)})
        w = self.world()
        self.files(w, "a download's server error leaves the song too, nothing passed over", w.song("Blur", "Beetlebum"),
                   {BLUR: ok("artist.html"), download(26): status(503, HTML_PAGE)})
        w = self.world()
        self.files(w, "a download redirected where robots.txt closes is never followed", w.song("Blur", "Beetlebum"),
                   {BLUR: ok("artist.html"), download(26): moved(f"{BASE}/storage/blur.zip"),
                    download(58155): file_answer(gpx, 58155)})
        w = self.world()
        self.files(w, "an artist's page redirected where robots.txt closes is no page", w.song("Blur", "Beetlebum"),
                   {BLUR: moved(f"{BASE}/ru/tabs/2/blur.html")})
        w = self.world()
        self.files(w, "a download redirected to a file is followed", w.song("Blur", "Beetlebum"),
                   {BLUR: ok("artist.html"), download(26): moved(f"{BASE}/files/26.gp3"),
                    f"{BASE}/files/26.gp3": file_answer(gp3, 26)})

        # get.py's gtptabs stage: its own words, and its envelope's
        w = self.world()
        self.stage(w, "the stage: a file kept", w.song("Blur", "Beetlebum"),
                   {BLUR: ok("artist.html"), download(26): file_answer(gp3, 26)})
        w = self.world()
        self.stage(w, "the stage: a miss", w.song("Elton John", "Crocodile Rock"),
                   {ELTON: elton(entry(8, "tabs/10/john-elton/rocket-man.html", "Rocket Man"))})
        w = self.world()
        self.stage(w, "the stage: every download a page or gone", w.song("Blur", "Beetlebum"),
                   {BLUR: ok("artist.html"), download(26): status(404), download(58155): ok(HTML_PAGE),
                    download(89061): status(404)})
        w = self.world()
        self.stage(w, "the stage: no file wanted", w.song("Nobody Known", "Beetlebum"), {})
        w = self.world()
        song = w.song("Blur", "Beetlebum")
        w.keep(song, "1", "guitar-1.gp5", gp5)
        self.stage(w, "the stage: a song with a file", song, {})
        w = self.world()
        self.stage(w, "the stage: a page that won't parse", w.song("Blur", "Beetlebum"), {BLUR: ok(MAINTENANCE)})
        w = self.world()
        self.stage(w, "the stage: three pages in a row", w.song("Elton John", "Crocodile Rock"),
                   {ELTON: four, **{download(n): ok(HTML_PAGE) for n in (1, 2, 3)}}, budget=8)
        w = self.world()
        self.stage(w, "the stage: a block", w.song("Blur", "Beetlebum"), {BLUR: status(403, HTML_PAGE)})
        w = self.world()
        self.stage(w, "the stage: the hour's lookup requests spent", w.song("Blur", "Beetlebum"),
                   {BLUR: ok("artist.html")}, budget=1)
        many = tuple(f"http://gtptabs.com/tabs/3/artist-{n}.html" for n in range(1, 8))
        w = self.world(extra=many)
        self.stage(w, "the stage: the lookup's requests spent", w.song(
            "Seven Artists", "Crocodile Rock", artists=[f"Artist {n}" for n in range(1, 8)]),
            {u.replace("http:", "https:"): status(404) for u in many[:6]})
        w = self.world()
        w.kv("provider:gtptabs", json.dumps({"strikes": 1, "cooldown_until": "2026-11-04T14:00:00Z", "last_ok": None,
                                             "last_error": "403", "last_error_at": "2026-11-03T10:00:00Z"}))
        self.stage(w, "the stage: cooling down after a block", w.song("Blur", "Beetlebum"), {})
        w = self.world()
        w.kv("provider:gtptabs", json.dumps({"strikes": 1, "cooldown_until": "2026-11-03T11:00:00Z", "last_ok": None,
                                             "last_error": "403", "last_error_at": "2026-11-01T09:00:00Z"}))
        self.stage(w, "the stage: a cooldown over asks again", w.song("Blur", "Beetlebum"),
                   {BLUR: ok("artist.html"), download(26): file_answer(gp3, 26)})
        w = self.world(toml="[providers.gtptabs]\nenabled = false\n")
        self.stage(w, "the stage: gtptabs.com turned off", w.song("Blur", "Beetlebum"), {})
        return self.records


@pytest.fixture(scope="module")
def lookups(tmp_path_factory) -> list[dict[str, Any]]:
    return Lookups(tmp_path_factory.mktemp("gtptabs-lookups")).build()


def test_gtptabs_lookup_jsonl(lookups):
    check(LOOKUP_FILE, jsonl(lookups, corpus="lookup/gtptabs", made_by=MADE_BY))


def _done(rec: dict[str, Any]) -> dict[str, Any]:
    return rec.get("out") or rec["after"]


def test_the_lookups_cover_each_outcome(lookups):
    passes = {r["case"]: r for r in lookups if r["fn"].endswith("gtptabs_files")}
    results = [r["out"]["result"] for r in passes.values() if "out" in r]
    assert any(s["kept"] for s in results) and any(s["missing"] for s in results)
    assert any(s["failures"] for s in results) and any(s["budget_exhausted"] for s in results)
    assert any(s["tried"] == 0 for s in results)
    assert {r["raises"]["type"] for r in passes.values() if "raises" in r} == {"ProviderBlocked"}
    kept = passes["a song gets the best rated upload of its title, kept as guitar-1 with its version"]["out"]
    assert [row["name"] for row in kept["rows"]["files"]] == ["guitar-1.gp3"]
    assert kept["requests"] == [f"GET {BLUR}", f"GET {download(26)}"]
    assert kept["kv"] == {"gtptabs:checked:1": STAMP}
    three = passes["three pages in a row where files should be end the pass as an error"]["out"]
    assert three["result"]["failures"][0][1] == "PagesNotFiles"
    assert len(passes["at most three downloads a song, then it waits"]["out"]["requests"]) == 4
    by_hand = passes["a number a file in the folder holds is never reused"]["out"]
    assert [row["name"] for row in by_hand["rows"]["files"]] == ["guitar-3.gp3"]
    stages = {r["case"]: _done(r).get("result") for r in lookups if r["fn"].endswith("_Lookup.gtptabs")}
    assert stages["the stage: a file kept"] == ["done", "Guitar Pro file downloaded"]
    assert stages["the stage: no file wanted"][0] == "skipped"
    assert {s[0] for s in stages.values()} == {"done", "skipped", "failed"}


# --- gtptabs_fetch.title_page -------------------------------------------------------------------------------------


def title_page_records(tmp: Path) -> list[dict[str, Any]]:
    from caracole.gtptabs_fetch import title_page

    w = World(tmp, "title-page", whole=True, extra=("http://gtptabs.com/tabs/1/ac-dc/tnt.html",
                                        "http://gtptabs.com/tabs/2/blur/beetlebum-2.html"))
    songs = [w.song("Blur", "Beetlebum"), w.song("Blur", "Song 2"), w.song("Blur", "Song 2 (2)"),
             w.song("Elton John", "Crocodile Rock"), w.song("The Beatles", "Yesterday - Remastered"),
             w.song("Blur", "Oily Water"), w.song("Nobody", "Beetlebum"), w.song("Blur", "!!!"),
             w.song("!!!", "Beetlebum"), w.song("AC-DC", "TNT"), w.song("ACDC", "TNT"),
             w.song("Rolling Stones", "Tumbling Dice"), w.song("Blur & Elton John", "Crocodile Rock",
                                                               artists=["Blur", "Elton John"]),
             w.song("Blur", "Girls and Boys")]
    with_file, lately, long_ago, not_a_time = (w.song("Blur", t) for t in ("Country House", "Song 2 Again", "Beetlebum 2",
                                                                          "Beetlebum 3"))
    w.index("http://gtptabs.com/tabs/2/blur/song-2-again.html", "http://gtptabs.com/tabs/2/blur/beetlebum-3.html")
    w.keep(with_file, "1", "guitar-1.gp5", gp_file(b"v5.00"))
    w.kv(f"gtptabs:checked:{lately.id}", LATELY)
    w.kv(f"gtptabs:checked:{long_ago.id}", LONG_AGO)
    w.kv(f"gtptabs:checked:{not_a_time.id}", "never")
    cases = []
    for song in [*songs, with_file, lately, long_ago, not_a_time]:
        cases.append([song.id, STAMP, title_page(w.conn, song, NOW)])
    cases.append([lately.id, "2026-11-25T12:00:00Z", title_page(w.conn, lately, datetime(2026, 11, 25, 12, tzinfo=UTC))])
    rec = {"fn": "caracole.gtptabs_fetch.title_page", "case": "a song's page on gtptabs.com, by the index alone",
           "fixture": dump_fixture(w.conn), "cases": cases}
    w.close()
    return [rec]


def test_gtptabs_title_page_jsonl(tmp_path):
    records = title_page_records(tmp_path)
    pages = [c[2] for c in records[0]["cases"]]
    assert None in pages and f"{BASE}/tabs/2/blur/beetlebum.html" in pages
    check(TITLE_PAGE_FILE, jsonl(records, corpus="sites/gtptabs_title_page", made_by=MADE_BY))


# --- MuseScore ------------------------------------------------------------------------------------------------------


MUSESCORE_URLS = [
    "https://musescore.com/song/yesterday-123", "https://musescore.com/song/ave_maria-1", "https://musescore.com/song/x-0",
    "https://musescore.com/song/lideal-2", "https://musescore.com/song/a-b-c-12", "https://musescore.com/song/-12",
    "https://musescore.com/song/___-5", "https://musescore.com/song/yesterday-1234567890123",
    "https://musescore.com/song/yesterday-123456789012", "https://musescore.com/song/Yesterday-1",
    "https://musescore.com/song/yesterday-١", "https://musescore.com/song/yesterday", "http://musescore.com/song/x-1",
    "https://musescore.com/song/x-1/", "https://musescore.com/user/1/scores/2", "https://www.musescore.com/song/x-1",
    "https://musescore.com/song/" + "a" * 300 + "-1", "https://musescore.com/song/" + "a" * 301 + "-1", "",
]


def musescore_records(tmp: Path) -> list[dict[str, Any]]:
    from caracole import musescore as m
    from caracole import site_index
    from caracole.musescore_fetch import SITE
    from helpers.musescore_site import FakeMuseScore

    out = [{"fn": "caracole.musescore.parse_song_url", "args": [u], "out": _row(m.parse_song_url(u))}
           for u in MUSESCORE_URLS]
    out += [{"fn": "caracole.musescore.sitemap_name", "args": [u], "out": m.sitemap_name(u)} for u in (
        "https://musescore.com/sitemaps/song-index/sitemap_songs18.xml",
        "https://musescore.com/sitemaps/song-index/sitemap_songs1.xml",
        "https://musescore.com/sitemaps/song-index/sitemap_songs12345.xml",
        "http://musescore.com/sitemaps/song-index/sitemap_songs1.xml", "https://musescore.com/sitemaps/song-index.xml",
        "")]
    out += [{"fn": "caracole.musescore.title_key", "args": [t], "out": m.title_key(t)} for t in TITLES]
    w = World(tmp, "musescore", index=False)
    client = FakeMuseScore().client(w.dir / "musescore-cache", now=SITEMAP_READ)
    try:
        site_index.refresh(w.conn, client, SITE, SITEMAP_READ)
    finally:
        client.close()
    for n, path in enumerate(("song/yesterday-900", "song/yesterday-7", "song/yesterday-1000000000", "song/yesterday-5",
                              "song/here_comes_the_sun-44", "song/coffee_tv-3"), start=1):
        row = m.parse_song_url(f"{m.BASE_URL}/{path}")
        w.conn.execute("INSERT OR REPLACE INTO musescore_index (page_id, path, title_key, sitemap) VALUES (?, ?, ?, ?)",
                       (row.page_id, row.path, row.title_key, "99"))
    titles = ["Yesterday", "Yesterday - Remastered 2009", "Ave Maria", "Here Comes the Sun", "Coffee & TV", "Nothing",
              "!!!", "L'idéal", "Hallelujah"]
    songs = [w.song("Somebody", t) for t in titles]
    cases = [[song.id, limit, [p._asdict() for p in m.song_pages(w.conn, song, limit=limit)]]
             for song in songs for limit in (3, 1, 10)]
    cases += [[songs[0].id, 0, [p._asdict() for p in m.song_pages(w.conn, songs[0], limit=0)]],
              [songs[0].id, -1, [p._asdict() for p in m.song_pages(w.conn, songs[0], limit=-1)]]]
    out.append({"fn": "caracole.musescore.song_pages", "case": "a song's pages by its title, oldest first",
                "fixture": dump_fixture(w.conn), "cases": cases})
    w.close()
    return out


def test_musescore_jsonl(tmp_path):
    records = musescore_records(tmp_path)
    [pages] = [r for r in records if r["fn"].endswith("song_pages")]
    assert any(len(c[2]) == 3 for c in pages["cases"]) and any(c[2] == [] for c in pages["cases"])
    assert len([c for c in pages["cases"] if c[1] == 10 and len(c[2]) > 3]) >= 1
    check(MUSESCORE_FILE, jsonl(records, corpus="sites/musescore", made_by=MADE_BY))
