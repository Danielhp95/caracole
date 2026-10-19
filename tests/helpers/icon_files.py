"""Synthetic site icons for the tests: PNG and ICO files built here, pixel by pixel.

No site's logo is in the repository: each icon is a square of one colour (or a few), made
the way an icon editor writes the format, so icons.py can be checked against what it reads.
"""

from __future__ import annotations

import struct
import zlib

RED = (220, 30, 40, 255)
CLEAR = (0, 0, 0, 0)


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(size: int = 32, colour: tuple[int, int, int, int] = RED, *, height: int | None = None,
        extra: list[tuple[bytes, bytes]] = (), before_idat: list[tuple[bytes, bytes]] = ()) -> bytes:
    """An RGBA PNG of one colour. ``extra`` chunks go before IEND, ``before_idat`` before IDAT."""
    h = height or size
    row = b"\x00" + bytes(colour) * size
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, h, 8, 6, 0, 0, 0))
    for kind, data in before_idat:
        out += chunk(kind, data)
    out += chunk(b"IDAT", zlib.compress(row * h))
    for kind, data in extra:
        out += chunk(kind, data)
    return out + chunk(b"IEND", b"")


def pixels(data: bytes) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    """An RGBA 8-bit, non-interlaced PNG's width, height and pixels, row by row (filter 0 only)."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    at, idat, width, height = 8, b"", 0, 0
    while at < len(data):
        (length,), kind = struct.unpack(">I", data[at:at + 4]), data[at + 4:at + 8]
        body = data[at + 8:at + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour_type = struct.unpack(">IIBB", body[:10])
            assert (depth, colour_type) == (8, 6)
        elif kind == b"IDAT":
            idat += body
        at += 12 + length
    raw = zlib.decompress(idat)
    stride = 1 + 4 * width
    out = []
    for y in range(height):
        line = raw[y * stride:(y + 1) * stride]
        assert line[0] == 0
        out += [tuple(line[1 + 4 * x:5 + 4 * x]) for x in range(width)]
    return width, height, out


def bmp_image(size: int, colour: tuple[int, int, int, int] = RED, *, bpp: int = 32,
              transparent: set[tuple[int, int]] = frozenset(), alpha: bool = True) -> bytes:
    """An icon's DIB, as an ICO holds it: BITMAPINFOHEADER (height doubled), the colours bottom row
    first, then the AND mask, in which ``transparent`` pixels (x, y from the top) are set.

    ``bpp`` 32 (BGRA; ``alpha=False`` leaves every alpha 0, as old icons do), 24 (BGR) or 8 (a
    palette: index 0 is the colour, index 1 white)."""
    r, g, b, a = colour
    palette = b""
    if bpp == 8:
        palette = bytes((b, g, r, 0)) + bytes((255, 255, 255, 0)) + b"\x00" * 4 * 254
    head = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, bpp, 0, 0, 0, 0, 256 if bpp == 8 else 0, 0)
    xor_stride = (size * bpp + 31) // 32 * 4
    and_stride = (size + 31) // 32 * 4
    rows = b""
    mask = b""
    for y in reversed(range(size)):
        line = b""
        bits = bytearray(and_stride)
        for x in range(size):
            if bpp == 32:
                line += bytes((b, g, r, a if alpha else 0))
            elif bpp == 24:
                line += bytes((b, g, r))
            else:
                line += b"\x00"
            if (x, y) in transparent:
                bits[x // 8] |= 0x80 >> (x % 8)
        rows += line.ljust(xor_stride, b"\x00")
        mask += bytes(bits)
    return head + palette + rows + mask


def ico(*images: tuple[int, bytes], kind: int = 1) -> bytes:
    """An ICO holding ``images``, each (its size, its bytes: a DIB or a PNG)."""
    out = struct.pack("<HHH", 0, kind, len(images))
    offset = 6 + 16 * len(images)
    entries, bodies = b"", b""
    for size, body in images:
        side = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(body), offset)
        bodies += body
        offset += len(body)
    return out + entries + bodies
