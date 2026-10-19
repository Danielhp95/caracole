"""ChordPro files and the PDFs the ``chordpro`` program renders from them.

The command line was checked against ChordPro 6.050.7 (nixpkgs
``perl5Packages.AppMusicChordPro``): ``--output=FILE`` picks the PDF backend by
its extension, ``--transpose=N`` shifts the chords and the key by N semitones,
and ``--define=a.b.c=VALUE`` sets one config item.

``--nodefaultconfigs`` is essential, not tidiness: for ``sheet.cho`` ChordPro
reads ``sheet.json`` beside it as a song config, and the library keeps UG's raw
JSON under exactly that name (ChordPro dies on it). The option also keeps a
stray ``chordpro.json`` in the working directory, or a user config, out of the
nightly run.

ChordPro's built-in PDF fonts have no CJK glyphs, so Chinese text vanishes from
the PDF. ``font_file`` names a TrueType/OpenType font for the lyrics and titles.
Two kinds of font come out wrong, so ``render_pdf`` refuses them up front:

- collections (``.ttc``), such as nixpkgs' Noto CJK fonts, variable or static:
  ChordPro 6.050.7 can't open them at all;
- TrueType fonts with odd-length glyph records, such as LXGW Neo XiHei. PDF::API2
  2.045 embeds a subset of the glyphs and writes it with short ``loca`` offsets,
  which can only point at even addresses, so every glyph after an odd-length one
  is read from the wrong place. Text extraction still works, but viewers show
  the glyphs missing.

``FusionKaiJ-Regular.ttf`` from nixpkgs' ``lxgw-fusionkai`` passes both checks
(every glyph record has an even length). A CFF-flavoured ``.otf`` works too;
PDF::API2 embeds those whole, so the PDFs are larger.
"""

from __future__ import annotations

import os
import struct
import subprocess
from collections.abc import Callable
from functools import lru_cache
from itertools import pairwise
from pathlib import Path

from tabarr.chordpro import to_chordpro

TIMEOUT = 120  # seconds; a sheet renders in about one

# Every other text element (subtitle, comments, chorus, footer, ...) derives its
# font from "text". Chords and tablature keep their own fonts: chord names are
# ASCII, and tablature needs the monospaced Courier.
FONT_ELEMENTS = ("text", "title")

# ChordPro prints neither {artist} nor {capo} by default; a capo the guitarist
# can't see means playing in the wrong key. The line under the title shows the
# key (transposed along with the chords), the artist and the capo.
LAYOUT = (
    "--define=pdf.formats.title.subtitle.0=%{key|Key: %{}}",
    "--define=pdf.formats.title.subtitle.1=%{artist}",
    "--define=pdf.formats.title.subtitle.2=%{capo|Capo: %{}}",
)

Runner = Callable[..., subprocess.CompletedProcess]


class RenderError(Exception):
    """``chordpro`` is missing, failed or wrote nothing; ``stderr`` holds what it said."""

    def __init__(self, message: str, *, stderr: str = ""):
        self.stderr = stderr
        detail = stderr.strip()
        super().__init__(f"{message}: {detail}" if detail else message)


def needs_font_file(text: str) -> bool:
    """Whether ChordPro's built-in fonts would lose some of this text.

    They are PDF core fonts in WinAnsi encoding, so anything cp1252 can't
    encode (Chinese, for one) renders as nothing unless ``font_file`` is given.
    """
    try:
        text.encode("cp1252")
    except UnicodeEncodeError:
        return True
    return False


def write_chordpro(
    markup: str,
    cho_path: Path,
    *,
    title: str,
    artist: str,
    key: str | None = None,
    capo: int | str | None = None,
    auto: bool = False,
) -> Path:
    """Convert UG sheet markup and write it to ``cho_path``.

    An existing file with the same content is left alone, so Syncthing has
    nothing to sync; otherwise the file is replaced in one rename.
    """
    path = Path(cho_path)
    text = to_chordpro(markup, title=title, artist=artist, key=key, capo=capo, auto=auto)
    try:
        if path.read_text(encoding="utf-8") == text:
            return path
    except (OSError, UnicodeDecodeError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def render_pdf(
    cho: Path,
    pdf: Path,
    *,
    transpose: int = 0,
    chordpro_bin: str = "chordpro",
    font_file: Path | None = None,
    runner: Runner = subprocess.run,
) -> None:
    """Render ``cho`` to ``pdf``, transposed by ``transpose`` semitones.

    Raises RenderError when the binary is missing, exits non-zero, times out
    or writes no PDF.
    """
    cmd = [chordpro_bin, "--nodefaultconfigs", *LAYOUT]
    if transpose:
        cmd.append(f"--transpose={transpose}")
    if font_file is not None:
        cmd += _font_options(Path(font_file))
    cmd += [f"--output={pdf}", str(cho)]
    try:
        result = runner(
            cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=TIMEOUT
        )
    except FileNotFoundError as e:
        raise RenderError(f"chordpro not found: {chordpro_bin}") from e
    except subprocess.TimeoutExpired as e:
        raise RenderError(f"chordpro timed out after {TIMEOUT} s on {cho}") from e
    except OSError as e:
        raise RenderError(f"cannot run {chordpro_bin}: {e}") from e
    stderr = result.stderr or ""
    if result.returncode != 0:
        raise RenderError(f"chordpro failed on {cho} (exit {result.returncode})", stderr=stderr)
    if not Path(pdf).is_file():
        raise RenderError(f"chordpro wrote no PDF for {cho}", stderr=stderr)


def _font_options(font: Path) -> list[str]:
    font = font.expanduser().absolute()
    if not font.is_file():
        raise RenderError(f"font file not found: {font}")
    stat = font.stat()
    if problem := _font_problem(str(font), stat.st_size, stat.st_mtime_ns):
        raise RenderError(f"{font} {problem}")
    return [f"--define=pdf.fonts.{element}.file={font}" for element in FONT_ELEMENTS]


_SFNT_VERSIONS = (b"\x00\x01\x00\x00", b"OTTO", b"true")


@lru_cache(maxsize=16)
def _font_problem(path: str, size: int, mtime_ns: int) -> str | None:
    """Why ChordPro would render this font wrongly, or None. Size and mtime key the cache."""
    try:
        with open(path, "rb") as f:
            header = f.read(12)
            if header[:4] == b"ttcf":
                return "is a font collection; ChordPro 6.050.7 reads only single .ttf/.otf fonts"
            if len(header) < 12 or header[:4] not in _SFNT_VERSIONS:
                return "is not a TrueType/OpenType font"
            (count,) = struct.unpack(">H", header[4:6])
            tables = {
                tag: (offset, length)
                for tag, _, offset, length in struct.iter_unpack(">4sIII", f.read(16 * count))
            }
            if b"glyf" not in tables:
                return None  # CFF outlines: PDF::API2 embeds them whole, unsubsetted
            f.seek(tables[b"head"][0] + 50)
            (long_offsets,) = struct.unpack(">h", f.read(2))
            if not long_offsets:
                return None  # short offsets can only describe even-length records
            f.seek(tables[b"loca"][0])
            loca = f.read(tables[b"loca"][1])
    except (OSError, KeyError, struct.error) as e:
        return f"cannot be read as a TrueType/OpenType font ({e})"
    offsets = struct.unpack(f">{len(loca) // 4}I", loca[: len(loca) // 4 * 4])
    odd = sum((end - start) & 1 for start, end in pairwise(offsets))
    if odd:
        return (
            f"has {odd} odd-length glyph records; PDF::API2 2.045 (ChordPro's PDF library) "
            "corrupts subsets of such fonts and the PDF shows glyphs missing. Use a font with "
            "even-length glyph records, such as FusionKaiJ-Regular.ttf from nixpkgs "
            "lxgw-fusionkai, or a CFF-based .otf"
        )
    return None
