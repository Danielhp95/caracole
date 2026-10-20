"""Where a sheet, a tab or a file came from, shown by its site's own icon (index.html, search).

Each source (``SOURCES``) is a value of ``versions.provider`` ("ug", "lacuerda", "gtptabs",
"inbox", "auto"), or LRCLIB for the lyrics. A site's icon is its favicon, fetched once
(``fetch_icons``) and kept in ``cache_dir/icons/<source>.png``; the page inlines it as a
``data:`` URI, so index.html still loads nothing from the network. A source with no icon
yet (never fetched, blocked, closed by robots.txt, none there) shows a lettered badge
instead ("UG"), and the audio model and your inbox, which are no site, a glyph of
caracole's own.

An icon is small and sanitized (``sanitize``): only a PNG or an ICO is read, by its bytes,
never by its name or its Content-Type, and only up to ``MAX_DOWNLOAD``.

- A PNG is checked chunk by chunk (each CRC, the header's size and format, the pixels its
  header promises, inflated within that bound), then written again with its image chunks
  alone: no text, no metadata, no animation.
- An ICO gives its image nearest 32 pixels (the smallest of 32 or more, else its biggest),
  a PNG inside it read as above, a bitmap decoded pixel by pixel, its AND mask made
  transparency, and encoded as a PNG here.
- Anything else is refused: an SVG too, which the standard library can't rasterize and
  which a filter of its scripts would have to get right forever.

What is kept is a PNG of at most ``MAX_SIDE`` pixels a side and ``MAX_ICON`` bytes, and the
page inlines a kept file only when it is still exactly what ``sanitize`` writes.

Fetching is a request like any other: through the provider's ``PoliteClient`` (robots.txt,
budget, pause, every 200 and 404 cached forever), never while it cools down. A site is
asked for ``/favicon.ico`` first (where every source's was, by hand, on 2026-10-19), then,
when that gives no icon, its home page, for a ``<link rel="icon">`` or an
``apple-touch-icon`` on the same site. A site that gave no icon, or failed, is left alone
for ``RETRY``; then its answers older than that are asked for again (``_look``), so a site
that puts an icon up later gets it within a week or so, and no URL is asked twice a week.
An icon the cache holds is read again from it, however old, without a request.
"""

from __future__ import annotations

import base64
import logging
import re
import sqlite3
import struct
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING

from caracole.library import open_regular, write_atomic

if TYPE_CHECKING:
    from caracole.http import Client

log = logging.getLogger(__name__)

MAX_DOWNLOAD = 256 * 1024  # bytes of an icon file read at most
MAX_ICON = 16 * 1024  # bytes of a kept icon at most: the page inlines every one
MAX_SIDE = 256  # pixels
TARGET = 32  # the side an ICO's image is picked by
RETRY = timedelta(days=7)  # how long a site that gave no icon is left alone
LYRICS = "lrclib"  # the source of lyrics.txt and lyrics.lrc
AUTO = "auto"  # the auto-chords sheet's (autochords/run.py PROVIDER)
INBOX = "inbox"  # a score you filed from _inbox/ (inbox.py)
FOLDER = "icons"  # in cache_dir


@dataclass(frozen=True)
class Source:
    """A place a file comes from: ``name`` as people call it, ``tag`` for the command line,
    ``letters`` for its badge, and, for a site, its home page and the favicon to ask for."""

    key: str
    name: str
    tag: str
    letters: str
    site: str | None = None
    icon: str | None = None

    @property
    def label(self) -> str:
        """The icon's accessible name: "from Ultimate Guitar"."""
        return f"from {self.name}"

    @property
    def glyph(self) -> bool:
        """No site: a glyph of caracole's own stands for it, and nothing is fetched."""
        return self.site is None


def _site(key: str, name: str, tag: str, letters: str, home: str) -> Source:
    return Source(key, name, tag, letters, home, home + "favicon.ico")


SOURCES: Mapping[str, Source] = {
    s.key: s for s in (
        _site("ug", "Ultimate Guitar", "UG", "UG", "https://www.ultimate-guitar.com/"),
        _site("lacuerda", "LaCuerda", "LaCuerda", "LC", "https://acordes.lacuerda.net/"),
        _site("lrclib", "LRCLIB", "LRCLIB", "LR", "https://lrclib.net/"),
        _site("gtptabs", "gtptabs.com", "gtptabs", "GT", "https://gtptabs.com/"),
        _site("musescore", "MuseScore", "MuseScore", "MS", "https://musescore.com/"),
        _site("youtube", "YouTube", "YouTube", "YT", "https://www.youtube.com/"),
        Source(AUTO, "the audio (auto-chords)", "auto", "♪"),
        Source(INBOX, "your inbox", "inbox", "↓"),
    )
}


# Files caracole makes from another it kept, which come from where that one came from.
_MADE_FROM = {"sheet.pdf": "sheet.txt", "sheet.cho": "sheet.txt",
              "sheet (auto).pdf": "sheet (auto).txt", "sheet (auto).cho": "sheet (auto).txt"}
_LYRICS_FILES = ("lyrics.txt", "lyrics.lrc")
SHEETS = ("sheet.txt", "sheet (auto).txt")  # a song's sheet, the human one first


def kept_sources(conn: sqlite3.Connection) -> dict[int, dict[str, str]]:
    """Where each kept file came from, by song and file name: its version's provider."""
    found: dict[int, dict[str, str]] = {}
    for song_id, name, provider in conn.execute(
        "SELECT f.song_id, f.name, v.provider FROM files f JOIN versions v ON v.id = f.version_id"
    ):
        found.setdefault(song_id, {})[name] = provider
    return found


def source_of(name: str, kept: Mapping[str, str]) -> str | None:
    """Where a song's file ``name`` came from, given its ``kept`` files' sources (``kept_sources``):
    a file it made from one kept comes from where that did; lyrics from LRCLIB; an auto sheet
    from the audio model. None for a file of caracole's own (info.json), or one put there by hand."""
    if name in kept:
        return kept[name]
    if name in _LYRICS_FILES:
        return LYRICS
    base = _MADE_FROM.get(name, name)
    if base in kept:
        return kept[base]
    return AUTO if base == "sheet (auto).txt" else None


def sheet_source(kept: Mapping[str, str]) -> str | None:
    """Where a song's sheet came from: its human sheet's source, else its auto sheet's."""
    return next((kept[name] for name in SHEETS if name in kept), None)


def source_name(key: str) -> str:
    """A source as people call it; an unknown one by its key."""
    return SOURCES[key].name if key in SOURCES else key


def tag(key: str) -> str:
    """A source's tag on the command line: "UG", "LaCuerda"; an unknown one's key."""
    return SOURCES[key].tag if key in SOURCES else key


# --- what an icon may be ------------------------------------------------------------------------

_PNG = b"\x89PNG\r\n\x1a\n"
_ICO = b"\x00\x00\x01\x00"
# The chunks a kept PNG keeps: its image, and how to show its colours.
_KEPT = (b"IHDR", b"PLTE", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"IDAT", b"IEND")
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}  # by colour type
_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
_ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))


def sanitize(data: bytes) -> bytes | None:
    """The icon in ``data`` as a small, clean PNG, or None when it is no icon caracole keeps."""
    if len(data) > MAX_DOWNLOAD:
        return None
    if data.startswith(_PNG):
        out = _clean_png(data)
    elif data.startswith(_ICO):
        out = _from_ico(data)
    else:
        return None
    return out if out is not None and len(out) <= MAX_ICON else None


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def _header(body: bytes) -> tuple[int, int, int, int, int] | None:
    """A PNG's IHDR: width, height, bit depth, colour type, interlace; None when it isn't one caracole keeps."""
    if len(body) != 13:
        return None
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(">IIBBBBB", body)
    if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE) or depth not in _DEPTHS.get(colour, ()):
        return None
    if compression or filtering or interlace not in (0, 1):
        return None
    return width, height, depth, colour, interlace


def _raw_size(width: int, height: int, depth: int, colour: int, interlace: int) -> int:
    """How many bytes the image's pixels inflate to, a filter byte a row, pass by pass when interlaced."""
    bits = _CHANNELS[colour] * depth
    passes = _ADAM7 if interlace else ((0, 0, 1, 1),)
    total = 0
    for x0, y0, dx, dy in passes:
        w = (width - x0 + dx - 1) // dx if width > x0 else 0
        h = (height - y0 + dy - 1) // dy if height > y0 else 0
        if w and h:
            total += h * (1 + (w * bits + 7) // 8)
    return total


def _clean_png(data: bytes) -> bytes | None:
    """The PNG with its image chunks alone, once every chunk and the pixels check out."""
    at, kept, idat, header = len(_PNG), [], [], None
    while True:
        if at + 12 > len(data):
            return None
        length = int.from_bytes(data[at:at + 4], "big")
        kind = data[at + 4:at + 8]
        end = at + 12 + length
        if end > len(data):
            return None
        body = data[at + 8:end - 4]
        if zlib.crc32(kind + body) != int.from_bytes(data[end - 4:end], "big"):
            return None
        if (kind == b"IHDR") != (header is None):  # IHDR first, and once
            return None
        if kind == b"IHDR":
            header = _header(body)
            if header is None:
                return None
        elif kind == b"IDAT":
            idat.append(body)
        if kind in _KEPT:
            kept.append((kind, body))
        at = end
        if kind == b"IEND":
            break
    width, height, depth, colour, interlace = header
    if not idat or (colour == 3 and not any(k == b"PLTE" for k, _ in kept)):
        return None
    expected = _raw_size(width, height, depth, colour, interlace)
    inflater = zlib.decompressobj()
    try:
        pixels = inflater.decompress(b"".join(idat), expected + 1)
    except zlib.error:
        return None
    if len(pixels) != expected or not inflater.eof:
        return None
    return _PNG + b"".join(_chunk(kind, body) for kind, body in kept)


def _encode_png(width: int, height: int, rgba: bytes) -> bytes:
    """An RGBA PNG of these pixels, row by row from the top."""
    stride = 4 * width
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(height))
    return (_PNG + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))


def _from_ico(data: bytes) -> bytes | None:
    """The ICO's image nearest ``TARGET`` pixels, as a PNG: of its images that read well and fit
    ``MAX_ICON``, the smallest of ``TARGET`` pixels or more, else the biggest."""
    if len(data) < 6:
        return None
    _, kind, count = struct.unpack_from("<HHH", data)
    first = 6 + 16 * count
    if kind != 1 or not 1 <= count <= 64 or len(data) < first:
        return None
    images = []
    for i in range(count):
        width, height, _, _, _, bpp, size, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        if size == 0 or offset < first or offset + size > len(data):
            return None
        body = data[offset:offset + size]
        side = _side(body)
        if side is not None:
            images.append((side, bpp, body, (width or 256, height or 256)))
    for _, _, body, listed in sorted(images, key=lambda m: ((0, m[0]) if m[0] >= TARGET else (1, -m[0]), -m[1])):
        out = _clean_png(body) if body.startswith(_PNG) else _from_bitmap(body, listed)
        if out is not None and len(out) <= MAX_ICON:
            return out
    return None


def _side(body: bytes) -> int | None:
    """The width of an ICO's image, from its own header (the directory's may lie)."""
    if body.startswith(_PNG):
        return int.from_bytes(body[16:20], "big") if len(body) >= 24 else None
    return struct.unpack_from("<i", body, 4)[0] if len(body) >= 40 else None


def _from_bitmap(body: bytes, listed: tuple[int, int]) -> bytes | None:
    """An ICO's bitmap (a BITMAPINFOHEADER, the colours bottom row first, then the AND mask) as a PNG;
    ``listed`` is its width and height as the ICO's directory gives them, which the header must match.

    A 32-bit image keeps its alpha, unless every alpha is 0, as in icons older than alpha;
    then, as for fewer bits, a pixel the mask sets is transparent and the rest opaque.
    """
    if len(body) < 40:
        return None
    size, width, doubled, planes, bpp, compression, _, _, _, used, _ = struct.unpack_from("<IiiHHIIiiII", body)
    height = doubled // 2
    if size != 40 or planes != 1 or compression != 0 or bpp not in (1, 4, 8, 24, 32):
        return None
    if (width, doubled) != (listed[0], 2 * listed[1]) or not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
        return None
    colours = (used or 1 << bpp) if bpp <= 8 else 0
    if colours > 1 << bpp:
        return None
    palette = [body[40 + 4 * i:43 + 4 * i][::-1] for i in range(colours)]  # BGRx to RGB
    xor_stride = (width * bpp + 31) // 32 * 4
    and_stride = (width + 31) // 32 * 4
    pixels_at = 40 + 4 * colours
    mask_at = pixels_at + height * xor_stride
    has_mask = len(body) >= mask_at + height * and_stride
    if len(body) < mask_at or (bpp < 32 and not has_mask):
        return None
    rows: list[bytes] = []
    for y in range(height):  # from the top
        line = body[pixels_at + (height - 1 - y) * xor_stride:][:xor_stride]
        if bpp == 32:
            rows.append(b"".join(line[4 * x:4 * x + 3][::-1] + line[4 * x + 3:4 * x + 4] for x in range(width)))
        elif bpp == 24:
            rows.append(b"".join(line[3 * x:3 * x + 3][::-1] + b"\xff" for x in range(width)))
        else:
            out = []
            for x in range(width):
                bit = x * bpp
                index = (line[bit // 8] >> (8 - bpp - bit % 8)) & ((1 << bpp) - 1)
                if index >= colours:
                    return None
                out.append(palette[index] + b"\xff")
            rows.append(b"".join(out))
    rgba = bytearray(b"".join(rows))
    if bpp == 32 and any(rgba[3::4]):
        return _encode_png(width, height, bytes(rgba))
    if not has_mask:  # 32-bit, every alpha 0, no mask: every pixel opaque
        rgba[3::4] = b"\xff" * (width * height)
        return _encode_png(width, height, bytes(rgba))
    for y in range(height):
        mask = body[mask_at + (height - 1 - y) * and_stride:][:and_stride]
        for x in range(width):
            at = 4 * (y * width + x)
            if mask[x // 8] & (0x80 >> (x % 8)):
                rgba[at:at + 4] = b"\x00\x00\x00\x00"
            else:
                rgba[at + 3] = 255
    return _encode_png(width, height, bytes(rgba))


# --- the cache ---------------------------------------------------------------------------------

_KEY = re.compile(r"[a-z0-9]{1,32}")


def _path(cache_dir: Path, key: str) -> Path:
    if not _KEY.fullmatch(key):
        raise ValueError(f"not a source: {key!r}")
    return cache_dir / FOLDER / f"{key}.png"


def keep_icon(cache_dir: Path, key: str, icon: bytes) -> Path:
    """Keep a sanitized icon (``sanitize``) as the source's, and return where."""
    path = _path(cache_dir, key)
    write_atomic(path, icon)
    return path


def has_icon(cache_dir: Path, key: str) -> bool:
    return icon_uri(cache_dir, key) is not None


def icon_uri(cache_dir: Path, key: str) -> str | None:
    """The source's kept icon as a ``data:`` URI, when it is there and still as caracole wrote it."""
    try:
        fd = open_regular(_path(cache_dir, key))
    except (OSError, ValueError):
        return None
    with open(fd, "rb") as f:
        data = f.read(MAX_ICON + 1)
    if len(data) > MAX_ICON or sanitize(data) != data:
        return None
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def _asked_key(key: str) -> str:
    return f"icon:asked:{key}"


# --- fetching -----------------------------------------------------------------------------------


@dataclass
class IconRun:
    """What ``fetch_icons`` did, by source: ``fetched`` and kept; ``missing``, the site gave none;
    ``errors``, it failed; ``waiting``, not asked this time (no client for it, or its budget spent);
    ``left``, asked less than ``RETRY`` ago without an icon."""

    fetched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)
    left: list[str] = field(default_factory=list)


def sources_in_use(conn: sqlite3.Connection) -> set[str]:
    """The sources the library has something from, which its pages show a mark for: a version
    of theirs (a kept file, a Guitar Pro page to click), LRCLIB's lyrics, MuseScore's pages."""
    used = {row[0] for row in conn.execute("SELECT DISTINCT provider FROM versions")}
    if conn.execute("SELECT 1 FROM songs WHERE lyrics_status = 'found' LIMIT 1").fetchone():
        used.add(LYRICS)
    if conn.execute("SELECT 1 FROM musescore_index LIMIT 1").fetchone():
        used.add("musescore")
    return used


def fetch_icons(conn: sqlite3.Connection, cache_dir: Path, clients: Mapping[str, Client], now: datetime, *,
                wait: timedelta | None = RETRY, only: set[str] | None = None) -> IconRun:
    """Ask each site that has no icon kept for its favicon, through ``clients[source]``, and keep it.

    ``only`` keeps to those sources (the nightly run's: ``sources_in_use``, so a site the library
    has nothing from is never asked). A source with no client waits, and so does one whose
    budget is spent: nothing marks it, so the next run asks. Any other end without an icon
    (none there, an error) is noted in kv ``icon:asked:<source>``, and the site is left alone
    for ``wait`` (None: ask now). Either way what a site answered less than ``RETRY`` ago
    comes from the cache (``_look``): asking now retries an error, not an answer. A block
    raises, as any block does: the caller cools the provider down.
    """
    from caracole.db import kv_delete, kv_get, kv_set
    from caracole.http import BudgetExhausted, ProviderBlocked, ProviderError

    run = IconRun()
    for key, source in SOURCES.items():
        if source.glyph or (only is not None and key not in only) or has_icon(cache_dir, key):
            continue
        asked = kv_get(conn, _asked_key(key))
        if wait is not None and asked is not None and now - _when(asked) < wait:
            run.left.append(key)
            continue
        client = clients.get(key)
        if client is None:
            run.waiting.append(key)
            continue
        try:
            icon = _look(client, source)
        except BudgetExhausted:
            run.waiting.append(key)
            continue
        except ProviderBlocked:
            kv_set(conn, _asked_key(key), _stamp(now))
            raise
        except ProviderError as e:
            log.info("%s's icon: %s", source.name, e)
            kv_set(conn, _asked_key(key), _stamp(now))
            run.errors.append(key)
            continue
        if icon is None:
            kv_set(conn, _asked_key(key), _stamp(now))
            run.missing.append(key)
            continue
        keep_icon(cache_dir, key, icon)
        kv_delete(conn, _asked_key(key))
        run.fetched.append(key)
    return run


def _stamp(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _when(stamp: str) -> datetime:
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


CANDIDATES = 2  # icon links of a home page tried at most


def _look(client: Client, source: Source) -> bytes | None:
    """The site's icon: what the cache holds first, however old, and what it doesn't asked for;
    then, when that gives none, the same again with the answers older than ``RETRY`` asked for
    once more. So an icon kept is read again for free, and a miss is asked again a week on,
    never sooner: at most one request a URL a week."""
    icon = _find(client, source, None)
    return icon if icon is not None else _find(client, source, RETRY)


def _find(client: Client, source: Source, max_age: timedelta | None) -> bytes | None:
    """The site's favicon, else the first of its home page's icon links that is one, of those
    robots.txt leaves open; a cached answer older than ``max_age`` is asked for again."""
    from caracole.http import robots_disallows

    assert source.icon is not None and source.site is not None
    icon = _icon_at(client, source.icon, max_age)
    if icon is not None:
        return icon
    home = _page(client, source.site, max_age)
    if home is None:
        return None
    links = [u for u in _icon_links(home, source.site) if u != source.icon and robots_disallows(u) is None]
    for url in links[:CANDIDATES]:
        icon = _icon_at(client, url, max_age)
        if icon is not None:
            return icon
    return None


def _page(client: Client, url: str, max_age: timedelta | None) -> bytes | None:
    """The body of a 200 for ``url``, or None for a 404 or a URL robots.txt closes (never asked)."""
    from caracole.http import RobotsClosed, robots_disallows

    if robots_disallows(url) is not None:
        return None
    try:
        resp = client.get(url, accept=(200, 404), max_age=max_age)
    except RobotsClosed:  # a redirect to a closed URL
        return None
    return resp.content if resp.status == 200 else None


def _icon_at(client: Client, url: str, max_age: timedelta | None) -> bytes | None:
    body = _page(client, url, max_age)
    return sanitize(body) if body is not None else None


class _IconLinks(HTMLParser):
    """The ``<link rel="icon">`` and ``apple-touch-icon`` links of a page's head."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[set[str], dict[str, str]]] = []
        self.done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body":
            self.done = True
        if self.done or tag != "link":
            return
        values = {name: value or "" for name, value in attrs}
        rels = set(values.get("rel", "").lower().split())
        if rels & {"icon", "apple-touch-icon", "apple-touch-icon-precomposed"} and values.get("href"):
            self.found.append((rels, values))

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.done = True


def _icon_links(page: bytes, base: str) -> list[str]:
    """The page's icon links on the site at ``base``, best first: an icon of 32 pixels, then any
    other icon, then an Apple touch icon; never an SVG."""
    from urllib.parse import urljoin, urlsplit

    parser = _IconLinks()
    try:
        parser.feed(page[:MAX_DOWNLOAD].decode("utf-8", "replace"))
        parser.close()
    except AssertionError:  # html.parser on a broken declaration
        pass
    site = _registered(urlsplit(base).hostname or "")
    ranked: list[tuple[int, int, str]] = []
    for n, (rels, values) in enumerate(parser.found):
        url = urljoin(base, values["href"].strip())
        parts = urlsplit(url)
        if parts.scheme != "https" or _registered(parts.hostname or "") != site:
            continue
        if "svg" in values.get("type", "").lower() or parts.path.lower().endswith(".svg"):
            continue
        if "icon" in rels:
            rank = 0 if f"{TARGET}x{TARGET}" in values.get("sizes", "").lower() else 1
        else:
            rank = 2
        ranked.append((rank, n, url))
    return list(dict.fromkeys(url for _, _, url in sorted(ranked)))


def _registered(host: str) -> str:
    """A host's site, as PoliteClient tells sites apart: its last two labels."""
    return ".".join(host.lower().split(".")[-2:])


def page_icons(cache_dir: Path) -> dict[str, dict[str, object]]:
    """Every source for the page: its name, its badge, and its icon when one is kept."""
    shown: dict[str, dict[str, object]] = {}
    for key, source in SOURCES.items():
        entry: dict[str, object] = {"name": source.name, "letters": source.letters}
        if source.glyph:
            entry["glyph"] = True
        else:
            uri = icon_uri(cache_dir, key)
            if uri is not None:
                entry["src"] = uri
        shown[key] = entry
    return shown
