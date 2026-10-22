"""Synthetic fonts: just enough TrueType for render.py's font check and for what pdf_fonts.py reads of a
font (the characters it has, how wide each is, whether it is variable), and the real fonts of the shells::

    from helpers.fonts import PDF_FONTS, font_folder, truetype

    path.write_bytes(truetype("abc", advance=500))   # these characters, each half its size wide
    folder = font_folder(tmp_path / "fonts")          # regular, bold, italic and mono .ttf: Latin, Greek, Cyrillic
    PDF_FONTS                                         # CARACOLE_PDF_FONTS's folder (nix/pdf-fonts.nix), or None

Each glyph record has an even length, as ChordPro's PDF library needs (render.py ``_font_problem``), unless
``odd``.
"""

from __future__ import annotations

import os
import struct
from collections.abc import Iterable
from pathlib import Path

# Adwaita Sans's folder as both shells and the packages' wrappers set it, when it is there.
PDF_FONTS = (Path(os.environ["CARACOLE_PDF_FONTS"]) if os.environ.get("CARACOLE_PDF_FONTS")
             and Path(os.environ["CARACOLE_PDF_FONTS"]).is_dir() else None)

# What a synthetic folder's fonts hold: ASCII, Latin-1, Latin Extended-A, the modifier letters (ʼ), Greek,
# Cyrillic and the general punctuation (’ “ ” —); no Chinese.
LATIN_GREEK_CYRILLIC = "".join(map(chr, [*range(0x20, 0x7F), *range(0xA0, 0x180), *range(0x2B0, 0x300),
                                         *range(0x370, 0x400), *range(0x400, 0x500), *range(0x2000, 0x2070)]))
ROLES = ("regular", "bold", "italic", "mono")


def truetype(chars: Iterable[str], *, advance: int = 600, variable: bool = False, odd: bool = False,
             cmap_format: int = 12) -> bytes:
    """A TrueType font of ``chars`` (each a glyph of its own, after .notdef), each ``advance`` thousandths of
    the size wide; ``variable`` gives it an (empty) ``fvar`` table, as a variable font has, ``odd`` a glyph
    record of an odd length, whose subsets ChordPro's PDF library corrupts, and ``cmap_format`` 4 its characters
    in a format 4 cmap (the Basic Multilingual Plane's) rather than a format 12 one."""
    codes = sorted({ord(ch) for ch in chars})
    glyphs = len(codes) + 1
    groups: list[list[int]] = []  # [first code, last code, first glyph]
    for gid, code in enumerate(codes, start=1):
        if groups and groups[-1][1] == code - 1:
            groups[-1][1] = code
        else:
            groups.append([code, code, gid])
    if cmap_format == 4:
        segments = [(first, last, (glyph - first + 0x8000) % 0x10000 - 0x8000) for first, last, glyph in groups]
        segments.append((0xFFFF, 0xFFFF, 1))
        n = len(segments)
        arrays = (struct.pack(f">{n}H", *(last for _, last, _ in segments)) + bytes(2)
                  + struct.pack(f">{n}H", *(first for first, _, _ in segments))
                  + struct.pack(f">{n}h", *(delta for _, _, delta in segments)) + bytes(2 * n))
        cmap = struct.pack(">HHHHI", 0, 1, 3, 1, 12) + struct.pack(">7H", 4, 14 + len(arrays), 0, 2 * n, 0, 0, 0) + arrays
    else:
        cmap = struct.pack(">HHHHI", 0, 1, 3, 10, 12) + struct.pack(
            ">HHIII", 12, 0, 16 + 12 * len(groups), 0, len(groups)) + b"".join(struct.pack(">III", *g) for g in groups)
    tables = {
        b"cmap": cmap,
        b"glyf": bytes(2 * glyphs + odd),
        # unitsPerEm 1000 at 18, long loca offsets at 50
        b"head": struct.pack(">IIII", 0x10000, 0, 0, 0x5F0F3CF5) + struct.pack(">HH", 0, 1000) + bytes(30)
        + struct.pack(">hh", 1, 0),
        b"hhea": bytes(34) + struct.pack(">H", glyphs),
        b"hmtx": struct.pack(f">{2 * glyphs}h", *[v for _ in range(glyphs) for v in (advance, 0)]),
        b"loca": struct.pack(f">{glyphs + 1}I", 0, *range(2 + odd, 2 * glyphs + 1 + odd, 2)),
        b"maxp": struct.pack(">IH", 0x5000, glyphs),
    }
    if variable:
        tables[b"fvar"] = bytes(16)
    directory, data = b"", b""
    start = 12 + 16 * len(tables)
    for tag, body in sorted(tables.items()):
        directory += struct.pack(">4sIII", tag, 0, start + len(data), len(body))
        data += body + bytes(-len(body) % 4)
    return struct.pack(">IHHHH", 0x10000, len(tables), 0, 0, 0) + directory + data


def font_folder(folder: Path, chars: str = LATIN_GREEK_CYRILLIC, **files: bytes) -> Path:
    """A folder of the four fonts ``pdf_fonts`` names: each of ``chars``, unless ``files`` gives a role's bytes
    (``bold=truetype(..., variable=True)``)."""
    folder.mkdir(parents=True, exist_ok=True)
    for role in ROLES:
        (folder / f"{role}.ttf").write_bytes(files.get(role, truetype(chars, advance=500 if role != "mono" else 600)))
    return folder
