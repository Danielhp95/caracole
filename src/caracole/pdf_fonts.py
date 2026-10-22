"""The fonts the PDFs are set in (``pdf_fonts``, or CARACOLE_PDF_FONTS): a folder of four fonts, and what
caracole reads of each, with the standard library alone.

The folder holds ``regular``, ``bold``, ``italic`` and ``mono``, each a ``.ttf`` or an ``.otf``: the words in
the regular one, the title, the chords and the section names in the bold one, the repeat marks in the italic
one, a tab in the monospaced one (render.py ``PDF_FONT_ELEMENTS`` says where each goes). Each must be one static
font ChordPro 6.050.7 draws right (render.py checks it): a variable font draws as its default instance alone, so
a "bold" variable font would print regular.

The packages' wrappers set CARACOLE_PDF_FONTS to nix/pdf-fonts.nix's folder: GNOME's Adwaita Sans (a
variation of Inter) as static Regular, Bold and Italic instances of its variable fonts, and Adwaita Mono, the
fonts a GNOME desktop shows, Firefox's pages among them. Without the setting, the PDFs keep ChordPro's built-in
Helvetica and Courier.

What a font has and how wide each letter is (``metrics``) is what the PDF's font is chosen by (render.py
``pdf_font``: a letter the regular font lacks needs the CJK font) and what pdf_text.py lays out its two
columns by.
"""

from __future__ import annotations

import struct
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROLES = ("regular", "bold", "italic", "mono")
_EXTENSIONS = (".ttf", ".otf")


@dataclass(frozen=True)
class PdfFonts:
    """The four fonts of the folder ``folder`` (``in_folder``)."""

    folder: Path
    regular: Path
    bold: Path
    italic: Path
    mono: Path


def in_folder(folder: Path) -> PdfFonts:
    """The fonts of ``folder``, each ``<role>.ttf`` or ``<role>.otf``; FileNotFoundError naming the first one
    it lacks."""
    folder = Path(folder).expanduser().absolute()
    found: dict[str, Path] = {}
    for role in ROLES:
        path = next((p for p in (folder / f"{role}{ext}" for ext in _EXTENSIONS) if p.is_file()), None)
        if path is None:
            raise FileNotFoundError(f"{folder} holds no {role}.ttf or {role}.otf")
        found[role] = path
    return PdfFonts(folder, **found)


@dataclass(frozen=True, eq=False)
class Metrics:
    """What caracole reads of a font: each character it has, by its advance width in whole thousandths of the
    size, cut down as ChordPro's PDF library counts them (PDF::API2's ``wx``), so a line wraps where chordpro
    wraps it (``widths``); and whether it is a variable font (an ``fvar`` table)."""

    widths: Mapping[str, int]
    variable: bool


def metrics(path: Path) -> Metrics:
    """The font file ``path``'s ``Metrics``, read once while its size and time stay the same. ValueError when
    it is no TrueType or OpenType font this reads (a collection among them), OSError when it can't be read."""
    stat = Path(path).stat()
    return _metrics(str(path), stat.st_size, stat.st_mtime_ns)


@lru_cache(maxsize=16)
def _metrics(path: str, size: int, mtime_ns: int) -> Metrics:
    data = Path(path).read_bytes()
    try:
        tables = _tables(data)
        (units,) = struct.unpack_from(">H", data, tables[b"head"][0] + 18)
        (count,) = struct.unpack_from(">H", data, tables[b"hhea"][0] + 34)
        start = tables[b"hmtx"][0]
        advances = [a for a, _ in struct.iter_unpack(">Hh", data[start:start + 4 * count])]
        codes = _cmap(data, tables[b"cmap"][0])
    except (KeyError, struct.error, IndexError) as e:
        raise ValueError(f"{path} cannot be read as a TrueType/OpenType font ({e!r})") from e
    if not advances or not units:
        raise ValueError(f"{path} has no advance widths")
    widths = {chr(code): advances[min(glyph, len(advances) - 1)] * 1000 // units
              for code, glyph in codes.items() if glyph and code < 0x110000}
    return Metrics(widths, b"fvar" in tables)


def _tables(data: bytes) -> dict[bytes, tuple[int, int]]:
    """The font's tables, by tag: (offset, length)."""
    if data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        raise ValueError("not a single TrueType/OpenType font")
    (count,) = struct.unpack_from(">H", data, 4)
    return {tag: (offset, length) for tag, _, offset, length in struct.iter_unpack(">4sIII", data[12:12 + 16 * count])}


def _cmap(data: bytes, at: int) -> dict[int, int]:
    """Each character's glyph, from the font's Unicode cmap subtable: a format 12 one (every plane) when it has
    one, else a format 4 one (the Basic Multilingual Plane)."""
    _, count = struct.unpack_from(">HH", data, at)
    found: dict[int, int] = {}
    for platform, encoding, offset in struct.iter_unpack(">HHI", data[at + 4:at + 4 + 8 * count]):
        if (platform, encoding) in ((3, 10), (3, 1), (0, 3), (0, 4), (0, 6)):
            (form,) = struct.unpack_from(">H", data, at + offset)
            if form in (4, 12):
                found.setdefault(form, at + offset)
    if 12 in found:
        return _format12(data, found[12])
    if 4 in found:
        return _format4(data, found[4])
    raise ValueError("no Unicode cmap of format 4 or 12")


def _format12(data: bytes, at: int) -> dict[int, int]:
    (groups,) = struct.unpack_from(">I", data, at + 12)
    out: dict[int, int] = {}
    for first, last, glyph in struct.iter_unpack(">III", data[at + 16:at + 16 + 12 * groups]):
        out.update(zip(range(first, last + 1), range(glyph, glyph + last - first + 1), strict=True))
    return out


def _format4(data: bytes, at: int) -> dict[int, int]:
    (seg_x2,) = struct.unpack_from(">H", data, at + 6)
    segs = seg_x2 // 2
    ends = struct.unpack_from(f">{segs}H", data, at + 14)
    starts = struct.unpack_from(f">{segs}H", data, at + 16 + seg_x2)
    deltas = struct.unpack_from(f">{segs}h", data, at + 16 + 2 * seg_x2)
    ranges_at = at + 16 + 3 * seg_x2
    ranges = struct.unpack_from(f">{segs}H", data, ranges_at)
    out: dict[int, int] = {}
    for i, (start, end, delta, offset) in enumerate(zip(starts, ends, deltas, ranges, strict=True)):
        for code in range(start, end + 1):
            if code == 0xFFFF:
                continue
            if offset:
                (glyph,) = struct.unpack_from(">H", data, ranges_at + 2 * i + offset + 2 * (code - start))
                glyph = (glyph + delta) & 0xFFFF if glyph else 0
            else:
                glyph = (code + delta) & 0xFFFF
            out[code] = glyph
    return out
