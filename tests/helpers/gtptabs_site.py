"""A fake gtptabs.com behind a real ``PoliteClient``, and synthetic Guitar Pro files.

The pages are the captured ones in tests/fixtures/gtptabs/ (19 October 2026): the sitemap
index trimmed to its first and last child, those two sitemaps trimmed to a few dozen URLs,
Blur's artist page trimmed to 14 of its 58 entries, robots.txt, and the 404 page a missing
download gets. Other artists' pages are made from Blur's (:func:`artist_page`).

No file here is anyone's tab: each is a format's magic header, then a line of filler.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
from helpers.zips import dated_entry

from caracole.config import ProviderPolicy
from caracole.http import PoliteClient

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "gtptabs"
BASE = "https://gtptabs.com"
NOW = datetime(2026, 10, 19, 3, 30, tzinfo=UTC)
FILLER = b"synthetic file for caracole's tests\n"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- synthetic files ---------------------------------------------------------------------


def gp_file(version: bytes = b"v5.00", *, word: bytes = b"GUITAR") -> bytes:
    """A Guitar Pro 3, 4 or 5 file's start: its version string as Guitar Pro writes it, a length
    byte and 30 bytes ("FICHIER GUITAR PRO v5.00"), then filler. ``word=b"GUITARE"`` makes the
    Guitar Pro 1 and 2 header ("FICHIER GUITARE PRO v1.04")."""
    head = b"FICHIER " + word + b" PRO " + version
    return bytes([len(head)]) + head.ljust(30, b"\x00") + FILLER


def gpx_file() -> bytes:
    """A Guitar Pro 6 file's start: the magic of its compressed container, BCFZ."""
    return b"BCFZ" + b"\x00\x10\x00\x00" + FILLER


def gp7_file(score: bool = True) -> bytes:
    """A Guitar Pro 7 file: a zip holding Content/score.gpif (or, ``score=False``, some other zip)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(dated_entry(z, "VERSION"), "7.0")
        z.writestr(dated_entry(z, "Content/score.gpif" if score else "Content/notes.txt"), FILLER.decode())
    return buf.getvalue()


def ptb_file() -> bytes:
    """A Power Tab file's start: its marker, "ptab"."""
    return b"ptab" + b"\x04\x00" + FILLER


# --- artist pages -----------------------------------------------------------------------------

_LABELS = {
    "electric guitar": ("Еlectro Guitar", "electroGuitarLabelSmall"),  # the site's title has a Cyrillic Е
    "acoustic guitar": ("Acoustic Guitar", "acousticGuitarLabelSmall"),
    "bass": ("Bass Guitar", "bassGuitarLabelSmall"),
    "drums": ("Drums", "drumsLabelSmall"),
    "vocals": ("Vocals", "vocalsLabelSmall"),
}


def entry(tab_id: int, path: str, title: str, *, fmt: str = "gp5", stars: int = 3, size: str = "31.17",
          instruments: tuple[str, ...] = ()) -> str:
    """One artist page entry, in the markup of the captured page's entries."""
    stars_html = "\n".join(
        f'                <a class="realActive active">{n}</a>' if n <= stars else f"                <a >{n}</a>"
        for n in range(1, 6)
    )
    labels = ""
    if instruments:
        divs = "\n".join(
            f'                                <div title="{_LABELS[i][0]}" class="labelSmall {_LABELS[i][1]}"></div>'
            for i in instruments
        )
        labels = f'                        <div class="instrumentsSmall">\n{divs}\n                            </div>\n'
    return f"""
    <div class="autorSong {fmt}">
        <div class="typeIco">&nbsp;</div>
        <div class="title">
                            <a href="/{path}">{title}</a>
                <div class="ratingSmall " data-model="Tab" data-item="{tab_id}" data-class="ratingSmall">
{stars_html}
            </div>

        </div>

        <div class="songInfo">

{labels}
            ({size} Kb)


        </div>

    </div>"""


def artist_page(name: str, path: str, *entries: str) -> str:
    """An artist page as gtptabs.com writes it: the captured page's frame, ``name`` in its heading
    and ``path`` as its address, and these entries in place of Blur's."""
    page = fixture("artist.html")
    start = page.index('<div class="autorSongs">') + len('<div class="autorSongs">')
    end = page.index('<div class="similarBlock">')
    tail = page[end:].replace("Blur", name)
    closing = "\n        </div>\n    </div>\n"
    head = page[:start].replace('Artist "Blur"', f'Artist "{name}"').replace(
        "https://gtptabs.com/tabs/2/blur.html", f"{BASE}/{path}").replace("<span>Blur</span>", f"<span>{name}</span>")
    return head + "".join(entries) + closing + tail


# --- the site ------------------------------------------------------------------------------------

HTML = {"Content-Type": "text/html; charset=UTF-8"}
XML = {"Content-Type": "text/xml"}


def sitemaps() -> dict[str, tuple[int, str, dict[str, str]]]:
    """The captured sitemap index and its two children, with the validators the live server sends."""
    return {
        f"{BASE}/sitemapGoogle.xml": (200, fixture("sitemap_index.xml"),
                                      {**XML, "ETag": 'W/"2b7-5177b1f3c1200"',
                                       "Last-Modified": "Mon, 01 Jun 2015 21:00:56 GMT"}),
        f"{BASE}/sitemapGoogle1.xml": (200, fixture("sitemap1.xml"),
                                       {**XML, "ETag": 'W/"7239fa-5177b1f3c1200"',
                                        "Last-Modified": "Mon, 01 Jun 2015 21:00:56 GMT"}),
        f"{BASE}/sitemapGoogle6.xml": (200, fixture("sitemap6.xml"),
                                       {**XML, "ETag": 'W/"57a0e3-5177b1f3c1200"',
                                        "Last-Modified": "Mon, 01 Jun 2015 21:00:56 GMT"}),
    }


class FakeGtpTabs:
    """gtptabs.com: pages and files by URL, every request recorded.

    By default it has the captured sitemaps and Blur's artist page, and no file: put each
    download in ``files`` by tab id. A sitemap asked for with the ETag it has answers 304,
    as the live server's do. A download it has no file for answers 404 with the captured page.
    Any other URL fails the test: caracole asked for something it shouldn't.
    """

    def __init__(self, pages=None, files=None):
        self.pages: dict[str, tuple[int, str | bytes, dict[str, str]]] = dict(sitemaps())
        self.pages[f"{BASE}/tabs/2/blur.html"] = (200, fixture("artist.html"), HTML)
        self.pages.update(pages or {})
        self.files: dict[int, bytes] = dict(files or {})
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(url)
        if url in self.pages:
            status, body, headers = self.pages[url]
            if status == 200 and headers.get("ETag") and request.headers.get("if-none-match") == headers["ETag"]:
                return httpx.Response(304, headers=headers)
            content = body.encode("utf-8") if isinstance(body, str) else body
            return httpx.Response(status, content=content, headers=headers)
        prefix = f"{BASE}/tabs/download/"
        if url.startswith(prefix) and url.endswith(".html"):
            tab_id = int(url[len(prefix):-len(".html")])
            if tab_id in self.files:
                return httpx.Response(200, content=self.files[tab_id], headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Disposition": f"attachment; filename=tab-{tab_id}.gp5",
                })
            return httpx.Response(404, text=fixture("download_404.html"), headers=HTML)
        raise AssertionError(f"unexpected request: {url}")

    def client(self, cache_dir: Path, *, budget: int = 20, now: datetime = NOW, events=None) -> PoliteClient:
        return PoliteClient(
            "gtptabs",
            ProviderPolicy(budget=budget, delay=(0.0, 0.0)),
            cache_dir,
            user_agent="caracole-test",
            transport=httpx.MockTransport(self.handler),
            sleep=lambda seconds: None,
            wall_clock=lambda: now,
            on_event=events.append if events is not None else None,
        )
