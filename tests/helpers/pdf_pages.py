"""Where a ChordPro PDF draws its text: each page's strings, with their places on the page.

Just enough PDF for chordpro's own output (as test_render.py's ``pdf_runs``): Flate streams, a
page's content streams in order, ``Tm`` for where a string starts, the built-in fonts' strings read
as WinAnsi and a TrueType font's (Identity-H) through its ToUnicode map::

    from helpers.pdf_pages import pdf_pages

    pages = pdf_pages(pdf)              # one list a page, in page order
    for x, y, text in pages[0]:         # in points from the page's bottom left, in drawing order
        ...
"""

from __future__ import annotations

import re
import zlib
from pathlib import Path

_OBJECT = re.compile(rb"(\d+) 0 obj(.*?)endobj", re.DOTALL)
_TOKEN = re.compile(
    rb"/([^\s/\[\]()<>]+)\s+[\d.]+\s+Tf"  # a font switch
    rb"|([-\d.]+)\s+([-\d.]+)\s+Tm"  # where the next string starts (1 0 0 1 x y Tm)
    rb"|\[((?:\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f]*>|[^\]])*)\]\s*TJ"  # a string array
    rb"|(\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f]*>)\s*Tj"  # a string
)
_PART = re.compile(rb"\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f]*>")
_ESCAPES = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}


def pdf_pages(path: Path) -> list[list[tuple[float, float, str]]]:
    """Each page's strings as (x, y, text), in page order."""
    data = Path(path).read_bytes()
    objects: dict[int, tuple[bytes, bytes | None]] = {}
    for m in _OBJECT.finditer(data):
        head, _, rest = m.group(2).partition(b"stream")
        stream = None
        if rest:
            stream = rest.lstrip(b"\r\n").rpartition(b"endstream")[0]
            if b"/FlateDecode" in head:
                stream = zlib.decompress(stream)
        objects[int(m.group(1))] = (head, stream)
    maps: dict[str, dict[int, str] | None] = {}
    for head, _ in objects.values():
        name = re.search(rb"/Name /(\S+)", head)
        if b"/Type /Font" in head and name:
            to_unicode = re.search(rb"/ToUnicode (\d+) 0 R", head)
            maps[name.group(1).decode()] = _cmap(objects[int(to_unicode.group(1))][1] or b"") if to_unicode else None
    pages = []
    for _, (head, _) in sorted(objects.items()):
        contents = re.search(rb"/Contents (\[[^\]]*\]|\d+ 0 R)", head)
        if not (re.search(rb"/Type /Page\b", head) and contents):
            continue
        stream = b" ".join(objects[int(n)][1] or b"" for n in re.findall(rb"(\d+) 0 R", contents.group(1)))
        cmap, x, y, shown = None, 0.0, 0.0, []
        for m in _TOKEN.finditer(stream):
            if m.group(1):
                cmap = maps.get(m.group(1).decode())
            elif m.group(2):
                x, y = float(m.group(2)), float(m.group(3))
            else:
                shown.append((x, y, "".join(_decode(p, cmap) for p in _PART.findall(m.group(4) or m.group(5)))))
        pages.append(shown)
    return pages


def _cmap(text: bytes) -> dict[int, str]:
    cmap: dict[int, str] = {}
    for lo, hi, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", text):
        for i, code in enumerate(range(int(lo, 16), int(hi, 16) + 1)):
            cmap[code] = chr(int(dst, 16) + i)
    return cmap


def _decode(part: bytes, cmap: dict[int, str] | None) -> str:
    if part.startswith(b"<"):
        raw = bytes.fromhex(part[1:-1].decode())
        if cmap is not None:
            return "".join(cmap.get(int.from_bytes(raw[i:i + 2]), "") for i in range(0, len(raw), 2))
        return raw.decode("cp1252", "replace")

    def one(m: re.Match[bytes]) -> bytes:
        code = m.group(1)
        return bytes([int(code, 8) & 0xFF]) if code[:1].isdigit() else _ESCAPES.get(code, code)

    return re.sub(rb"\\([0-7]{1,3}|.)", one, part[1:-1], flags=re.DOTALL).decode("cp1252", "replace")
