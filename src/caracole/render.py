"""ChordPro files and the PDFs the ``chordpro`` program renders from them.

The command line was checked against ChordPro 6.050.7 (nixpkgs
``perl5Packages.AppMusicChordPro``): ``--output=FILE`` picks the PDF backend by
its extension, and ``--define=a.b.c=VALUE`` sets one config item. chordpro
transposes nothing: its ``--transpose`` spells A# where the viewer shows Bb and
leaves ``{define}`` shapes where they were, so the text it is given names each
chord where the song is played (viewer/version.py ``apply_version``).

``--nodefaultconfigs`` is essential, not tidiness: for ``sheet.cho`` ChordPro
reads ``sheet.json`` beside it as a song config, and the library keeps UG's raw
JSON under exactly that name (ChordPro dies on it). The option also keeps a
stray ``chordpro.json`` in the working directory, or a user config, out of the
nightly run.

The PDFs are set in the fonts of ``pdf_fonts`` (pdf_fonts.py; the packages' Adwaita Sans and
Mono, nix/pdf-fonts.nix), each element in the one ``PDF_FONT_ELEMENTS`` names: the words regular,
the title, the chords and the section names bold, a repeat mark italic, a tab monospaced. Without
them, or when one of them is a font ChordPro draws wrongly (below; a variable font draws as its
default instance alone), ChordPro's built-in Helvetica and Courier, as before them.

Neither has CJK glyphs, so Chinese text vanishes from the PDF. ``font_file`` names a
TrueType/OpenType font for the lyrics and titles, and every element that derives its font
from theirs; the chords and a tab keep theirs (``fonts_options``). Which text needs it is judged
by the letters of the PDF's own fonts (``pdf_font``): Adwaita Sans has Latin, Greek and Cyrillic
and the curly apostrophes, the built-in fonts only WinAnsi's.
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

``render_all`` gives every kept sheet in the library (or a few songs', as a
lookup's) a ChordPro file, a PDF and a viewer (a phone-friendly page, see
caracole/viewer) beside it:

- a human sheet (``sheet.txt``, from UG or LaCuerda) is rendered from the
  ``content`` of the ``sheet.json`` next to it, with the key UG gives the
  version (``tonality_name``) and the capo in ``meta``, to ``sheet.cho``,
  ``sheet.pdf`` and ``sheet.html``;
- an auto-chords sheet (``sheet (auto).txt``) is rendered to
  ``sheet (auto).cho``, ``sheet (auto).pdf`` and ``sheet (auto).html``, so a
  human sheet never collides with them. The fetch steps keep the auto sheet
  until a complete human sheet arrives, so beside a partial human sheet it is
  rendered too. Once they retire it, its outputs are removed as soon as the
  human sheet's PDF is in place.

The viewer is made from the .cho, needs no font, and is written at every pass
when it has changed (a new key, a PDF now there to link), and when the PDF
could not be rendered too. Each viewer takes its own sheet's musical key as
``keys.sheet_keys`` finds it, the key info.json records: the human sheet's
from the tab or its chords, the auto sheet's heard in the audio. It is an extra: one that
can't be built (a bug) or written (a link in its place) is logged as "no
viewer for", with the traceback of a bug, and counts the song as failed, but
never costs it a PDF. Its progressions are read then too, for finding the song by them
(progressions.py, kv ``render:progressions:<song id>``: the human sheet's, else the auto
sheet's; an extra, as the viewer is). kv ``render:files:<song id>`` keeps the SHA-256 and the
length of each .cho and viewer written (``written_file``), PDF or no PDF: a
server serves a viewer only while it is still those bytes.

Each UG version the fetch keeps beside the sheet (sheet_versions.py: ``version-<tab>.txt``
and ``.json``) gets a viewer of its own, ``version-<tab>.html``, made from its JSON as the
sheet's is from sheet.json, in its own key and as written, with no .cho or PDF and no
Export PDF, as an export is the one's (``export_viewer``) (``_render_versions``); it is
recorded like the sheet's viewer, and goes, while it is still as written, once the version
is no longer kept. Every viewer of the song (the one's, and each
version's) lists the song's UG chords versions in its data's ``versions`` (``_versions_data``).

Each harmonica tab the song keeps (harptabs_fetch.py: ``harmonica-N.txt``) gets a page of its own,
``harmonica-N.html`` (viewer/harptab_page.py), made from its text with the song's chord sheet (its human
one, else its auto one), whose chords tell the harp that plays with the record (``_render_harmonica``),
whatever came of the sheet's PDF; it is recorded like a viewer, linked from the sheet's viewers (their data's
``harmonicaTabs``, each with its ``page``), and goes, while it is still as written, once the tab is no longer
kept or its text is gone from the folder.

A human sheet the song no longer keeps (the fetch drops one whose UG match was
undone when nothing replaces it) takes the ``sheet.cho``, ``sheet.pdf`` and
``sheet.html`` rendered from it along, at the next pass. Only what the records
say caracole wrote goes: the three when the PDF's record below names it, else
the .cho and the viewer while they are still as written. Files of yours by
those names stay.

The PDFs take caracole's look (``STYLE_FILE``, a ChordPro config) and are in
the song's own version (``own_version``): its ``[version]`` override ("Make
this my version": the key it plays in, its mode and its capo, so that a sheet
in another key in its place plays in that key too, and the shapes and swaps it
chose), else its ``[transpose]``, else the sheet as written; the viewer starts
there too. Each
is made from a text of its own (caracole/pdf_text.py), the .cho staying as the
viewer reads it: in a version, each chord named and shaped as the viewer shows
it there (``apply_version``); without the tab's notes, the shapes its viewer shows
(its chord legend's) as chord diagrams,
the viewer's key line under the title, section names in capitals, in two columns that end
level when the first page's two hold the song. That
text runs the viewer's code: a bug there fails that song's PDF alone, logged with its traceback,
as a chordpro failure does, and its viewer is still written. kv ``render:<song id>``
keeps what the song's PDF was made from (the SHA-256 of the .cho, the
version's transposition, the CJK font, the PDF fonts' folder, the SHA-256 of the style, the PDF's name,
``pdf_text.PDF_TEXT_VERSION`` and the SHA-256 of the text chordpro prints, whose
key line and chord diagrams come from more than the .cho) and what was
written (the PDF's length and SHA-256): its human sheet's, else its auto
sheet's. ``render:<song id>:auto`` does the same for an auto sheet's PDF
beside a human one. A PDF is rendered again only when one of those changes,
when it is missing or no longer what was written (cut short by a power cut,
changed on a synced device, a link in its place), or when forced: its length
is compared, then, when that matches, its SHA-256. A sheet whose letters the
PDF's fonts lack gets its .cho and viewer but no PDF until a usable CJK font is set:
one font error for the pass, naming each sheet's first such letter, not a
failure per song. A font that is set but unusable (a collection, a missing
file) counts as none. Cyrillic and Greek letters that look like Latin ones,
which UG transcribers type now and then ("(х2)" with a Cyrillic х), are
written as those Latin letters when they are a sheet's only such letters, so
the sheet keeps the built-in fonts.

Others can write to the library (the Syncthing group, every synced device), so
no sheet there is read through a symbolic link: a link or a FIFO in the place of
``sheet.json``, ``sheet (auto).txt``, a .cho or a viewer fails that song (a viewer's
alone: the PDFs are still rendered). chordpro reads the
PDF's text and writes the PDF in a private directory under the cache
directory, and the PDF then goes into the song's folder in one rename.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import struct
import subprocess
import tempfile
import unicodedata
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl, quote

from caracole import progressions
from caracole.autochords.merge import AUTO_MARKER
from caracole.chordpro import to_chordpro
from caracole.config import Config
from caracole.db import kv_delete, kv_get_json, kv_set_json
from caracole.inbox import HARMONICA_PAGE, HarmonicaFile, guitar_files, harmonica_files
from caracole.library import (
    KeptFile,
    NotRegularFile,
    holds,
    kept_files,
    open_regular,
    read_json,
    read_regular,
    safe_name,
    song_dir,
    write_atomic,
    write_info,
)
from caracole.keys import SongKey, sheet_key, sheet_keys
from caracole.normalize import clean_title
from caracole.overrides import Overrides, OverridesError, load_overrides
from caracole.pdf_fonts import ROLES, PdfFonts, in_folder, metrics
from caracole.pdf_text import PDF_TEXT_VERSION, STYLE_FILE, pdf_text
from caracole.sheet_versions import SheetVersion, as_data, in_library, sheet_pins, tab_of, version_names
from caracole.songs import (
    AUTO_SHEET,
    HUMAN_SHEET,
    SHEET_OUTPUTS,
    Song,
    ensure_current_keys,
    get_song,
    is_export,
    list_songs,
)
from caracole.ug.page import decode_twice, json_int
from caracole.versions import get_version
from caracole.viewer import build_viewer
from caracole.viewer.harptab_page import build_harmonica_viewer
from caracole.viewer.page import viewer_key
from caracole.viewer.sheet import parse_sheet
from caracole.viewer.theory import Key
from caracole.viewer.version import (
    KeyVersion,
    Version,
    apply_version,
    in_key,
    key_version,
    played_key,
    played_on,
    version_entry,
    version_from_query,
    version_label,
    version_query,
)

log = logging.getLogger(__name__)

# Each kept sheet's .cho, .pdf and .html, named in songs.SHEET_OUTPUTS.
HUMAN_OUTPUTS = SHEET_OUTPUTS[HUMAN_SHEET]
AUTO_OUTPUTS = SHEET_OUTPUTS[AUTO_SHEET]
STATUS_KEY = "render:status"  # kv: the last pass, for the to-do page
FILES_KEY = "render:files:"  # kv, then the song's id: each .cho and viewer written (written_file)
EXPORT_KV = "render:export:"  # kv, then the song's id: {label: the export's PDF and what it was made from}
FONT_HINT = "set cjk_font or CARACOLE_CJK_FONT"

TIMEOUT = 120  # seconds; a sheet renders in about one

# Every other text element (subtitle, comments, chorus, footer, ...) derives its
# font file from "text". Chords and tablature keep their own fonts: chord names
# are ASCII, and tablature needs the monospaced Courier.
FONT_ELEMENTS = ("text", "title")

# With ``pdf_fonts``, the font of the four each element is set in: STYLE_FILE's elements, and those chordpro
# derives from them (Output/PDF.pm's configurator: a chorus, an empty line, its own comment_italic and
# comment_box, the songbook's contents, a grid), which would take the font file of the one they derive from
# otherwise. Bold, italic and monospaced where the style has Helvetica-Bold, Helvetica-Oblique and Courier.
PDF_FONT_ELEMENTS = {
    "title": "bold", "subtitle": "regular", "text": "regular", "chorus": "regular", "empty": "regular",
    "chord": "bold", "annotation": "italic", "comment": "bold", "comment_italic": "italic",
    "comment_box": "regular", "tab": "mono", "footer": "regular", "toc": "regular", "diagram": "bold",
    "diagram_base": "regular", "grid": "bold", "grid_margin": "bold",
}
# Those a CJK font leaves to them, as it leaves them their built-in fonts: the chords, their annotations and a
# grid (chord names are Latin; none derives from "text") and a tab (monospaced). Every other takes the CJK font.
_KEPT_BESIDE_CJK = frozenset({"chord", "annotation", "grid", "tab"})
# Where render_version takes the PDF fonts from unless told: the config, as an export a command asks for does. A
# render pass hands over its own, checked once for the pass (``_usable_pdf_fonts``).
_CONFIG: Any = object()

# How the PDFs look (a ChordPro config): Helvetica (with ``pdf_fonts``, PDF_FONT_ELEMENTS' fonts), bold
# chords in caracole's rust, the chord diagrams above the song, section names in small rust capitals with no band,
# and under the title the text's {subtitle} (pdf_text.py: the artist, the viewer's key
# line, a capo or a tuning the notes name), as ChordPro prints neither the artist nor the
# capo by default: a capo the guitarist can't see means playing in the wrong key. Its
# SHA-256 is in each PDF's record, so a new look renders every PDF once more. It is
# pdf_text.STYLE_FILE, whose page sizes and spacings say where the PDF's two columns end level.

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


# Cyrillic and Greek letters drawn exactly like Latin ones, by code point: written out, they
# would look like the Latin letters here too.
_LATIN_LOOKALIKES = str.maketrans({
    # Cyrillic capitals, then small letters
    0x0410: "A", 0x0412: "B", 0x0415: "E", 0x041A: "K", 0x041C: "M", 0x041D: "H", 0x041E: "O",
    0x0420: "P", 0x0421: "C", 0x0422: "T", 0x0425: "X", 0x0405: "S", 0x0406: "I", 0x0408: "J",
    0x0430: "a", 0x0435: "e", 0x043E: "o", 0x0440: "p", 0x0441: "c", 0x0443: "y", 0x0445: "x",
    0x0455: "s", 0x0456: "i", 0x0458: "j", 0x0501: "d", 0x04BB: "h",
    # Greek capitals, then small omicron
    0x0391: "A", 0x0392: "B", 0x0395: "E", 0x0396: "Z", 0x0397: "H", 0x0399: "I", 0x039A: "K",
    0x039C: "M", 0x039D: "N", 0x039F: "O", 0x03A1: "P", 0x03A4: "T", 0x03A5: "Y", 0x03A7: "X",
    0x03BF: "o",
})


def _lost_letter(ch: str) -> bool:
    """Whether ``ch`` is a letter ChordPro's built-in fonts would lose."""
    return unicodedata.category(ch).startswith("L") and needs_font_file(ch)


def _first_lost_letter(text: str, fonts: PdfFonts | None = None) -> str | None:
    """The letter a font file is needed for: the first the PDF's fonts lose (``_lacks``) with no Latin twin, if
    any."""
    lacks = _lacks(fonts)
    lost = [ch for ch in text if unicodedata.category(ch).startswith("L") and lacks(ch)]
    return next((ch for ch in lost if ord(ch) not in _LATIN_LOOKALIKES), lost[0] if lost else None)


def _as_latin(text: str) -> str:
    """``text`` with its look-alike letters written in Latin, when they are its only lost letters.

    A stray "х2" in an English sheet then needs no font file. Text with other
    such letters (a Russian or a Chinese sheet) is left as written.
    """
    lost = {ch for ch in set(text) if _lost_letter(ch)}
    if lost and all(ord(ch) in _LATIN_LOOKALIKES for ch in lost):
        return text.translate(_LATIN_LOOKALIKES)
    return text


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
    nothing to sync; otherwise the file is replaced in one rename
    (``library.write_atomic``). Stray letters that only look foreign are
    written in Latin (``_as_latin``). Raises RenderError when something other
    than a regular file, such as a symbolic link, is in the file's place: the
    old file is read only to compare, but never through a link (``read_regular``).
    """
    path = Path(cho_path)
    text = _chordpro_text(markup, title=title, artist=artist, key=key, capo=capo, auto=auto)
    _write_if_changed(path, text.encode("utf-8"))
    return path


def _chordpro_text(markup: str, *, title: str, artist: str, key: str | None = None,
                   capo: int | str | None = None, auto: bool = False) -> str:
    """The .cho text of a sheet: its UG markup in ChordPro (``to_chordpro``), then its stray
    look-alike letters written in Latin (``_as_latin``)."""
    return _as_latin(to_chordpro(markup, title=title, artist=artist, key=key, capo=capo, auto=auto))


def _write_if_changed(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` (``write_atomic``) unless the file holds it already.

    The old file is read only to compare, never through a link: RenderError when
    something other than a regular file is in its place.
    """
    try:
        if read_regular(path) == data:
            return
    except NotRegularFile as e:
        raise RenderError(f"cannot read {path}: {e}") from e
    except OSError:
        pass
    write_atomic(path, data)


@lru_cache(maxsize=1)
def _style() -> str:
    """The SHA-256 of the PDF style (STYLE_FILE), which each PDF's record keeps."""
    return hashlib.sha256(STYLE_FILE.read_bytes()).hexdigest()


def render_pdf(
    cho: Path,
    pdf: Path,
    *,
    chordpro_bin: str = "chordpro",
    font_file: Path | None = None,
    fonts: PdfFonts | None = None,
    runner: Runner = subprocess.run,
) -> None:
    """Render ``cho`` to ``pdf``, its chords where it names them (chordpro transposes nothing), in the PDF
    fonts ``fonts`` (None: ChordPro's built-in ones), its words in the CJK font ``font_file`` when one is given
    (``fonts_options``).

    Raises RenderError when the binary is missing, exits non-zero, times out
    or writes no PDF, or when a font is one chordpro would draw wrongly.
    """
    cmd = [chordpro_bin, "--nodefaultconfigs", f"--config={STYLE_FILE}"]
    cmd += fonts_options(fonts, Path(font_file) if font_file is not None else None)
    cmd += [f"--output={pdf}", str(cho)]
    run_chordpro(cmd, Path(pdf), runner=runner, timeout=TIMEOUT, chordpro_bin=chordpro_bin, on=f" on {cho}",
                 nothing=f"no PDF for {cho}")


def run_chordpro(cmd: list[str], out: Path, *, runner: Runner, timeout: float, chordpro_bin: str, on: str = "",
                 nothing: str | None = None) -> None:
    """Run the chordpro command ``cmd``, which writes ``out``, for at most ``timeout`` seconds (a sheet's PDF,
    a songbook's files). RenderError when ``chordpro_bin`` is missing or can't be run, times out, exits
    non-zero (with its stderr) or writes nothing: ``on`` ends the messages of a run on one sheet
    (" on sheet.cho"), and ``nothing`` says what it didn't write ("no PDF for sheet.cho"; "no <out's name>"
    without it)."""
    try:
        result = runner(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    except FileNotFoundError as e:
        raise RenderError(f"chordpro not found: {chordpro_bin}") from e
    except subprocess.TimeoutExpired as e:
        raise RenderError(f"chordpro timed out after {timeout} s{on}") from e
    except OSError as e:
        raise RenderError(f"cannot run {chordpro_bin}: {e}") from e
    stderr = result.stderr or ""
    if result.returncode != 0:
        raise RenderError(f"chordpro failed{on} (exit {result.returncode})", stderr=stderr)
    if not out.is_file():
        raise RenderError(f"chordpro wrote {nothing or 'no ' + out.name}", stderr=stderr)


def _font_options(font: Path, elements: tuple[str, ...] = FONT_ELEMENTS) -> list[str]:
    """chordpro's options that print ``elements`` in the font file ``font``; RenderError when it is
    missing or chordpro can't use it (``_font_problem``)."""
    font = font.expanduser().absolute()
    if not font.is_file():
        raise RenderError(f"font file not found: {font}")
    stat = font.stat()
    if problem := _font_problem(str(font), stat.st_size, stat.st_mtime_ns):
        raise RenderError(f"{font} {problem}")
    return [f"--define=pdf.fonts.{element}.file={font}" for element in elements]


def fonts_options(fonts: PdfFonts | None, cjk: Path | None, elements: tuple[str, ...] = FONT_ELEMENTS) -> list[str]:
    """chordpro's options that set the PDF in the fonts ``fonts`` (``PDF_FONT_ELEMENTS``), the CJK font ``cjk``
    taking every element but the chords' and the tab's (``_KEPT_BESIDE_CJK``); without ``fonts``, the built-in
    fonts, ``cjk`` taking ``elements`` and those derived from them. RenderError for a font chordpro can't use."""
    if fonts is None:
        return _font_options(cjk, elements) if cjk is not None else []
    out: list[str] = []
    for element, role in PDF_FONT_ELEMENTS.items():
        font = cjk if cjk is not None and element not in _KEPT_BESIDE_CJK else getattr(fonts, role)
        out += _font_options(font, (element,))
    return out


def _pdf_fonts(folder: Path | None) -> tuple[PdfFonts | None, str | None]:
    """The fonts of the folder ``pdf_fonts`` when chordpro can use each; otherwise None, and what is wrong with
    them: the PDFs then keep the built-in fonts. A font missing, a collection, one with odd-length glyph records
    (``_font_problem``) or a variable one, which chordpro draws as its default instance alone."""
    if folder is None:
        return None, None
    try:
        fonts = in_folder(folder)
        for role in ROLES:
            font = getattr(fonts, role)
            _font_options(font)
            if metrics(font).variable:
                raise RenderError(f"{font} is a variable font; ChordPro 6.050.7 draws only its default instance, "
                                  "so use a static one (fonttools varLib.instancer makes one)")
    except (RenderError, OSError, ValueError) as e:
        return None, f"pdf_fonts is unusable ({e}): the PDFs keep ChordPro's built-in fonts"
    return fonts, None


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


# --- the library ---------------------------------------------------------------------

Outcome = Literal["rendered", "skipped", "no font", "pages"]  # "pages": the version pages, no PDF


@dataclass
class RenderStats:
    """What one pass over the library did.

    ``rendered`` PDFs were written, ``skipped`` ones were already up to date and
    ``failed`` songs could not be rendered. ``font_error`` says, once for the
    pass, which sheets have no PDF for want of a usable CJK font.
    """

    rendered: int = 0
    skipped: int = 0
    failed: int = 0
    font_error: str | None = None


def render_all(
    conn: sqlite3.Connection,
    cfg: Config,
    overrides: Overrides,
    *,
    runner: Runner = subprocess.run,
    force: bool = False,
    now: datetime | None = None,
    between: Callable[[], bool] | None = None,
    song_ids: Collection[int] | None = None,
) -> RenderStats:
    """Write every kept sheet as ChordPro and render it to a PDF in the song's key.

    Ignored songs are left alone. A song that fails (a ``RenderError``, or a
    file that can't be read or written) is logged and counted, and the others
    go on. The pass is recorded in kv ``render:status`` for the to-do page:
    ``{"at", "rendered", "failed": [display keys], "font_error", "no_font":
    {display key: the first letter its sheet needs a CJK font for}}``, stamped
    with ``now`` (by default the current time). ``force`` renders every PDF
    again, up to date or not; ``runner`` runs chordpro (tests pass a fake).

    With ``song_ids``, only those songs (``caracole get`` and ``caracole render
    --song`` render their one song), and the stats are theirs alone. The record
    stays the last full pass's (``_status_after``): their names leave its
    ``failed`` list and ``no_font``, and go back on, at the end, as this pass
    found them; the next full pass puts them back in the library's order.

    ``between`` is called between two songs, in no transaction: bulk work hands
    caracole's lock to a waiting lookup there (``_common.hand_over``), as a pass
    that renders many PDFs takes minutes. When it says it did, overrides.toml
    and each song after are read again, since the lookup may have changed them.
    """
    stats = RenderStats()
    failed: list[str] = []
    no_font: dict[str, str] = {}
    font, font_problem = _cjk_font(cfg.cjk_font)
    fonts = _usable_pdf_fonts(cfg)
    handed = False
    songs = list_songs(conn) if song_ids is None else _songs_of(conn, song_ids)
    for n, listed in enumerate(songs):
        if n and between is not None and between():
            handed = True
            try:
                overrides = load_overrides(cfg.overrides_file)
            except OverridesError as e:
                log.info("overrides.toml couldn't be read again (%s); the render goes on with what it read.", e)
        song = listed
        if handed:
            try:
                song = get_song(conn, listed.id)
            except KeyError:  # merged into another song meanwhile
                continue
        if song.status == "ignored" or song.key in overrides.ignore:
            continue
        try:
            done = _render_song(
                conn, cfg, overrides, song, cjk_font=font, fonts=fonts, runner=runner, force=force
            )
        except (RenderError, OSError) as e:
            log.warning("no PDF for %s: %s", song.display, e)
            failed.append(song.display)
            continue
        stats.rendered += sum(1 for d in done if d.outcome == "rendered")
        stats.skipped += sum(1 for d in done if d.outcome == "skipped")
        if any(d.viewer_failed for d in done):
            failed.append(song.display)
        if missing := next((d.missing for d in done if d.outcome == "no font"), None):
            no_font[song.display] = missing
    stats.failed = len(failed)
    if no_font:
        stats.font_error = _font_error(no_font, font_problem)
        log.warning("%s", stats.font_error)
    at = (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    status = {"at": at, "rendered": stats.rendered, "failed": failed, "font_error": stats.font_error,
              "no_font": no_font}
    if song_ids is not None:
        status = _status_after(kv_get_json(conn, STATUS_KEY, default=None), status, {s.display for s in songs},
                               font_problem)
    kv_set_json(conn, STATUS_KEY, status)
    return stats


def _songs_of(conn: sqlite3.Connection, song_ids: Collection[int]) -> list[Song]:
    """The songs of ``song_ids`` the library still has, newest first as ``list_songs`` gives them."""
    ensure_current_keys(conn)
    songs = []
    for song_id in song_ids:
        try:
            songs.append(get_song(conn, song_id))
        except KeyError:  # merged into another song, or removed
            continue
    return sorted(songs, key=lambda s: (s.added_at, s.id), reverse=True)


def _status_after(stored: Any, status: dict[str, Any], names: set[str], font_problem: str | None) -> dict[str, Any]:
    """kv ``render:status`` after a pass over some songs (``names``: theirs), whose own record is
    ``status``: the last full pass's record, with those songs' failures, and the sheets that wait
    for a font, brought up to date. With no record yet, ``status`` itself."""
    if not isinstance(stored, dict):
        return status
    before = stored.get("failed")
    if isinstance(before, list):
        failed: list[Any] | int = [name for name in before if str(name) not in names] + status["failed"]
    elif isinstance(before, int) and not isinstance(before, bool):
        failed = before  # an older caracole's count, naming no song: the last full pass's until the next
    else:
        failed = status["failed"]
    waiting = stored.get("no_font")
    if isinstance(waiting, dict):
        no_font = {name: letter for name, letter in waiting.items()
                   if name not in names and isinstance(letter, str) and len(letter) == 1} | status["no_font"]
        font = {"no_font": no_font, "font_error": _font_error(no_font, font_problem) if no_font else None}
    else:  # recorded by a caracole that kept no "no_font": the font error this pass hit, if any
        font = {"font_error": status["font_error"] or stored.get("font_error")}
    return {**stored, "failed": failed, **font}


@dataclass(frozen=True)
class _Done:
    """One sheet's pass; for "no font", ``missing`` is its first letter the built-in fonts lack.
    ``viewer_failed``: its viewer couldn't be built or written (``_write_viewer`` logged why)."""

    outcome: Outcome
    missing: str | None = None
    viewer_failed: bool = False


def _render_song(
    conn: sqlite3.Connection,
    cfg: Config,
    overrides: Overrides,
    song: Song,
    *,
    cjk_font: Path | None,
    runner: Runner,
    force: bool,
    fonts: PdfFonts | None = None,
) -> list[_Done]:
    """Render every sheet the song keeps, the human one first, after the pages of the versions kept beside
    it, then the pages of its harmonica tabs: theirs are the first ``_Done("pages")`` and the last, so a song that
    keeps no sheet has those alone.

    ``cjk_font`` is a usable font or None, and ``fonts`` the PDF fonts (``_pdf_fonts``) or None. The auto sheet is kept, and so
    rendered, until the fetch steps retire it for a complete human sheet; its
    outputs go once that has happened and the human sheet's PDF is in place.
    A human sheet the song no longer keeps takes its outputs along
    (``_drop_human_outputs``).

    Each viewer takes its own sheet's key, as ``keys.sheet_keys`` finds it and info.json
    records it: the human sheet's from the tab or its chords, the auto sheet's heard in the audio.

    The versions kept beside the sheet get their pages first (``_render_versions``), so a sheet
    whose PDF fails costs them nothing. The song's UG chords versions are in the viewer of the
    one (the human sheet's, else an auto sheet's standing alone) and in each version page.
    Its harmonica tabs get theirs last (``_render_harmonica``), whatever came of the sheets, with the
    text of the sheet it reads (the human one, else the auto one) when that was read.
    """
    files = {f.name: f for f in kept_files(conn, song.id)}
    human, auto = files.get(HUMAN_SHEET), files.get(AUTO_SHEET)
    folder = song_dir(cfg.library_dir, song)
    versions = in_library(conn, song.id, cfg.rank)
    listed = _versions_data(conn, versions, human or auto,
                            pinned=bool(sheet_pins(conn, song.id, overrides.pin.get(song.key, ()))))
    # Its Guitar Pro files caracole serve shows in the browser, which each of its viewers links (viewer/page.py).
    guitar = tuple(f.name for f in guitar_files(conn, song.id) if f.in_browser)
    # Its harmonica tabs (harptabs_fetch.py), which its sheet's viewers name for the harmonica's panel, each with the
    # page written beside it (_render_harmonica).
    tabs = harmonica_files(conn, song.id)
    harmonica = tuple({"name": f.name, "href": quote(f.name, safe=""), "page": quote(f.page, safe=""),
                       **({"key": f.key} if f.key else {})} for f in tabs)
    done: list[_Done] = [_render_versions(conn, cfg, song, files, versions, listed, guitar)]
    human_key, auto_key = sheet_keys(conn, cfg.library_dir, song) if human or auto else (None, None)
    chosen = next((v.tab_id for v in versions if v.chosen), None)
    primary: list[tuple[str, tuple[str | None, str | None]]] = []  # the sheet the harmonica tabs' pages read

    def render(kept: KeptFile, sheet: _Sheet, state_key: str, *, beside: bool = False,
               listed: dict[str, Any] | None = None) -> None:
        found = auto_key if sheet.auto else human_key
        mine = (found.key, found.source) if found is not None else (None, None)
        text = _sheet_cho(song, sheet)
        if not sheet.auto or human is None:
            primary.append((text, mine))
        # Each sheet in its own place: a version kept by its key moves each by what puts it in that key
        played = own_version(overrides, song, text, *mine)
        if beside:
            # Beside the human sheet, the version's shapes and swaps were chosen on that sheet, and an export is
            # that sheet's (export_viewer): its viewer offers none
            played = replace(played, at={}, alt={})
        done.append(_render_sheet(conn, cfg, song, folder, kept, text, state_key, played,
                                  start=export_query(played) if song.key in overrides.version else None,
                                  cjk_font=cjk_font, fonts=fonts, runner=runner, force=force, key=mine,
                                  export=not beside,
                                  primary=not sheet.auto or human is None, versions=listed, guitar=guitar,
                                  harmonica=harmonica))
        if done[-1].outcome == "rendered":
            _say_if_keyless(overrides, song, text, mine[0], Path(kept.name).stem + ".pdf")

    try:
        if human is not None:
            render(human, _human_sheet(conn, cfg.library_dir, human), _state_key(song.id),
                   listed=_on_page(listed, chosen))
            if auto is None and done[-1].outcome != "no font":  # its PDF is in place
                for name in AUTO_OUTPUTS:
                    (folder / name).unlink(missing_ok=True)
                kv_delete(conn, _state_key(song.id, auto=True))
                _forget_written(conn, song.id, AUTO_OUTPUTS)
        else:
            _drop_human_outputs(conn, cfg.library_dir, song, folder)
            if auto is None:
                progressions.forget(conn, song.id)
        if auto is not None:
            beside = human is not None
            render(auto, _auto_sheet(cfg.library_dir, auto), _state_key(song.id, auto=beside), beside=beside,
                   listed=None if beside else _on_page(listed, None))
        if human is not None or auto is not None:
            _remake_exports(conn, cfg, overrides, song, cjk_font=cjk_font, fonts=fonts, runner=runner, force=force)
    finally:  # the tabs' pages, whatever came of the sheet's PDF: with the sheet's text read, if it was
        back = HUMAN_OUTPUTS[2] if human is not None else AUTO_OUTPUTS[2] if auto is not None else None
        done.append(_render_harmonica(conn, cfg, song, folder, tabs, files, primary[0] if primary else None, back))
    return done


# --- the versions kept beside the sheet: a viewer each ----------------------------------


def _versions_data(conn: sqlite3.Connection, versions: list[SheetVersion], one: KeptFile | None, *,
                   pinned: bool = False) -> dict[str, Any] | None:
    """What every viewer of the song says of its UG chords versions: ``sheet_versions.as_data``, its
    ``total`` every version listed (gone ones too), ``sheet``, the provider of the sheet the title
    opens ("ug", "lacuerda", "auto"; None when it keeps none), and ``pinned``, whether a ``[pin]`` of yours
    chooses it (``sheet_versions.sheet_pins``: what ``caracole versions --clear`` takes out, so the viewer
    offers Back to caracole's pick). None when UG lists no chords version of the song: then no viewer has a
    ``versions`` (and shows no switcher)."""
    if not versions:
        return None
    provider = get_version(conn, one.version_id).provider if one is not None else None
    return {**as_data(versions, len(versions)), "sheet": provider, "pinned": pinned}


def _on_page(listed: dict[str, Any] | None, tab: str | None) -> dict[str, Any] | None:
    """``listed`` as one page holds it: each entry's ``this`` says whether it is the page's own (``tab``'s;
    with None, the page of a sheet that is none of them, a LaCuerda or an auto sheet)."""
    if listed is None:
        return None
    return {**listed, "list": [{**v, "this": tab is not None and v["tab"] == tab} for v in listed["list"]]}


def _render_versions(conn: sqlite3.Connection, cfg: Config, song: Song, files: Mapping[str, KeptFile],
                     versions: list[SheetVersion], listed: dict[str, Any] | None,
                     guitar: tuple[str, ...] = ()) -> _Done:
    """Write a viewer page for each version kept beside the sheet, ``version-<tab>.html`` (its ``page``),
    from its ``version-<tab>.json`` as the sheet's is from sheet.json, and no ChordPro file or PDF. It offers
    no export: an export is made from the sheet ``export_viewer`` names, so this page's would be the one's PDF.
    Each page starts as the version is written, in its own key (``keys.sheet_key``), and is recorded
    (``_note_written``) and written only when its bytes change.

    The page of a version no longer kept (the fetch let it go) goes while it still holds what caracole wrote
    (``_forget_written``): one changed since, on a synced device, stays, and is forgotten. A page that can't
    be made (its JSON unreadable, a bug) is logged as "no viewer for" and fails the song, as a sheet's viewer
    does; the last one written stays."""
    folder = song_dir(cfg.library_dir, song)
    pages = {v.page: v for v in versions if v.page == version_names(v.tab_id)[2]}  # kept, and not the one
    ok = True
    for page, v in pages.items():
        ok = _render_version(conn, cfg, song, folder, files, v, _on_page(listed, v.tab_id), guitar) and ok
    left = tuple(name for name in _written(conn, song.id) if tab_of(name) is not None and name not in pages)
    _forget_written(conn, song.id, left, folder)
    return _Done("pages", viewer_failed=not ok)


def _render_version(conn: sqlite3.Connection, cfg: Config, song: Song, folder: Path, files: Mapping[str, KeptFile],
                    v: SheetVersion, listed: dict[str, Any] | None, guitar: tuple[str, ...] = ()) -> bool:
    """Write the kept version ``v``'s viewer page; False, logged, when it can't be made or written."""
    _, doc, page = version_names(v.tab_id)
    kept = files.get(doc)
    if kept is None:
        log.warning("no viewer for %s: %s isn't kept", song.display, doc)
        return False
    raw = get_version(conn, kept.version_id).raw
    try:
        sheet = _ug_sheet(cfg.library_dir / kept.path, raw)
    except RenderError as e:
        log.warning("no viewer for %s: %s", song.display, e)
        return False
    found = sheet_key(raw, sheet.markup, sheet.capo)
    text = _chordpro_text(sheet.markup, title=clean_title(song.title), artist=song.artist,
                          key=sheet.key, capo=sheet.capo)
    data = _write_viewer(song, text, folder / page, None, key=(found.key, found.source) if found else (None, None),
                         transpose=0, start=None, export=False, versions=listed, guitar=guitar)
    if data is None:
        return False
    _note_written(conn, song.id, page, data)
    return True


# --- the harmonica tabs kept: a page each --------------------------------------------


def _render_harmonica(conn: sqlite3.Connection, cfg: Config, song: Song, folder: Path, tabs: list[HarmonicaFile],
                      files: Mapping[str, KeptFile], sheet: tuple[str, tuple[str | None, str | None]] | None,
                      back: str | None) -> _Done:
    """Write a page for each harmonica tab the song keeps (harptabs_fetch.py), ``harmonica-N.html`` beside its
    ``harmonica-N.txt`` (viewer/harptab_page.py), from the tab's text and what its version says of it (its page, its
    key, its difficulty, its views, its rating), with the song's chord sheet ``sheet`` (its ChordPro and its key as
    keys.py found it: the human one, else the auto one), for the harp that plays with the record. ``back`` names the
    song's sheet viewer, which its ‹ Chord sheet opens. Each page is recorded (``_note_written``) and written only
    when its bytes change.

    The page of a tab no longer kept, or whose text is no longer in the folder (deleted on a synced device), goes
    while it still holds what caracole wrote (``_forget_written``). A page that can't be made or written (its text
    read through a link, a bug) is logged as "no viewer for" and fails the song, as a sheet's viewer does; the last
    one written stays."""
    cho, (key, key_source) = sheet if sheet is not None else (None, (None, None))
    ok = True
    pages: set[str] = set()
    for tab in tabs:
        kept = files.get(tab.name)
        if kept is None or not tab.page:
            continue
        try:
            text = read_regular(cfg.library_dir / kept.path).decode("utf-8", errors="replace")
        except FileNotFoundError:  # deleted from the folder: its page goes too
            continue
        except OSError as e:
            log.warning("no viewer for %s: cannot read %s: %s", song.display, tab.name, e)
            pages.add(tab.page)
            ok = False
            continue
        pages.add(tab.page)
        version = get_version(conn, kept.version_id)
        raw = version.raw if isinstance(version.raw, dict) else {}
        try:
            html = build_harmonica_viewer(
                text, title=clean_title(song.title), artist=song.artist, tab_file=tab.name, url=version.url,
                page_key=tab.key, facts=raw, cho=cho, key=key, key_source=key_source, back=back)
        except Exception:  # a tab the page can't read must never cost the song's other pages
            log.warning("no viewer for %s: cannot build %s", song.display, tab.page, exc_info=True)
            ok = False
            continue
        data = html.encode("utf-8")
        try:
            _write_if_changed(folder / tab.page, data)
        except (RenderError, OSError) as e:
            log.warning("no viewer for %s: %s", song.display, e)
            ok = False
            continue
        _note_written(conn, song.id, tab.page, data)
    left = tuple(name for name in _written(conn, song.id) if HARMONICA_PAGE.fullmatch(name) and name not in pages)
    _forget_written(conn, song.id, left, folder)
    return _Done("pages", viewer_failed=not ok)


# --- an export: the sheet's PDF in another version ------------------------------------


# What of a viewer's address names where the song is played (viewer/version.py), besides its text size and the rest
_VERSION_NAMES = frozenset({"t", "mode", "capo", "alt", "at"})


def own_version(overrides: Overrides, song: Song, cho: str, key: str | None, key_source: str | None = None) -> Version:
    """The song's own version on its sheet ``cho`` (its ChordPro as caracole writes it; ``key``, the sheet's,
    ``keys.sheet_keys``, and ``key_source`` where it came from), where its PDF, its viewer and its songbooks
    start: its ``[version]`` ("Make this my version"), else its ``[transpose]`` alone, else the sheet as written
    (``Version()``).

    A ``[version]`` kept by its key (``key=Gm&mode=dorian&capo=0``, as Make this my version writes it) plays in
    that key on whatever sheet the song has, by a songbook setting's rule, its chords read in the notes of the
    sheet's key (``version.in_key``): as written on a
    sheet with no key, or one the viewer's code can't read (a bug, logged with its traceback). One without a key
    (``t=2&mode=dorian``, as caracole wrote it before) is a move from the sheet, as the viewer's address writes
    it, at the song's ``[transpose]`` when it names no ``t``."""
    own = _own(overrides, song)
    if isinstance(own, Version):
        return own
    try:
        return in_key(own, cho, key=viewer_key(cho, key, key_source), capo_sheet=parse_sheet(cho).capo)
    except Exception:  # a sheet the viewer's code can't read (a bug) never stops the song's other files
        log.warning("%s: cannot place it in its own version", song.display, exc_info=True)
        return Version()


def _own(overrides: Overrides, song: Song) -> Version | KeyVersion:
    """The song's own version as overrides.toml holds it: kept by its key (``KeyVersion``), which each sheet
    places, or a move from the sheet (``own_version``)."""
    transpose = overrides.transpose.get(song.key, 0)
    query = overrides.version.get(song.key)
    if query is None:
        return Version(t=transpose)
    if (kept := key_version(query)) is not None:
        return kept
    version = version_from_query(query)
    return version if "t" in _names(query) else replace(version, t=transpose)


def _say_if_keyless(overrides: Overrides, song: Song, cho: str, key: str | None, pdf: str) -> None:
    """Log, as a PDF is made, that it is as written where the song's own version is kept by a key (``KeyVersion``)
    its sheet ``cho`` has none to place by: no chord caracole can read, none to estimate one from."""
    own = _own(overrides, song)
    if isinstance(own, KeyVersion) and _no_key(cho, key):
        log.warning("%s: %s is as written, not in your version (%s): its sheet has no key caracole can read",
                    song.display, pdf, own.label())


def _no_key(cho: str, key: str | None) -> bool:
    try:
        return viewer_key(cho, key) is None
    except Exception:  # a bug in the viewer's code: said where it stopped the version (own_version)
        return False


def keeps_key(overrides: Overrides, song: Song) -> bool:
    """Whether the song's own version is kept by its key (a ``[version]`` with one), which a sheet with no key
    can't take: it is then as written, and a songbook says so (``songbook.KEY_UNKNOWN``)."""
    return isinstance(_own(overrides, song), KeyVersion)


def pdf_transpose(conn: sqlite3.Connection, overrides: Overrides, song: Song) -> int:
    """How many semitones the song's PDF is moved by, as its line on the library page says: its own version's
    ``t``, which needs no sheet (``own_version``); for one kept by its key, which moves each sheet by its own, the
    PDF's as it was last made (kv ``render:<song id>``), 0 before it is made."""
    own = _own(overrides, song)
    if isinstance(own, Version):
        return own.t
    made = kv_get_json(conn, _state_key(song.id))
    t = made.get("transpose") if isinstance(made, Mapping) else None
    return t if isinstance(t, int) and not isinstance(t, bool) else 0


def on_the_guitar(v: Version) -> Version:
    """The version ``v`` as the song's own PDF plays it: on the guitar, whatever instrument ``v`` is on (its viewer
    starts there; another instrument's PDF is an export's or a songbook's), without the shapes chosen on that one."""
    return v if v.inst is None else replace(v, inst=None, at={})


def _names(query: str) -> set[str]:
    """The names an address's query or fragment holds, as the viewer's URLSearchParams reads them."""
    return {name for name, _ in parse_qsl(query[1:] if query[:1] in ("#", "?") else query, keep_blank_values=True)}


def export_version(query: str, own: Version) -> Version:
    """The version an address ``query`` holds (``version_from_query``), for an export, as the viewer reads its
    own address: one that names none of the version (its ``t``, ``mode``, ``capo``, ``alt`` or ``at``) is the
    song's own, ``own`` (``ExportSheet.own``), where the viewer starts, and one that names no ``t`` is at the own
    version's, which the viewer leaves out of its address. Its instrument is the one ``inst`` names (the guitar's
    too: ``inst=guitar``, which the viewer writes when the song's own is on another); with none named, the own
    version's where the address names none of the version, else the guitar."""
    names = _names(query)
    version = version_from_query(query)
    if not names & _VERSION_NAMES:
        return own if "inst" not in names else replace(own, inst=version.inst, at={} if version.inst != own.inst
                                                       else own.at)
    return version if "t" in names else replace(version, t=own.t)


@dataclass(frozen=True)
class ExportSheet:
    """The sheet the song's exports are made from (``export_viewer``: the human one, else the auto one), read once
    for what a request asks of it (``export_sheet``): its ChordPro text, its key (``keys.sheet_keys``), and the key
    of its shapes and its capo as its viewer reads them. Its methods raise RenderError for a sheet the viewer's code
    can't read (a bug)."""

    song: Song
    text: str
    found: SongKey | None
    shapes: Key | None
    capo: int | None

    def own(self, overrides: Overrides) -> Version:
        """The song's own version (``own_version``) on this sheet, where its viewer starts."""
        return own_version(overrides, self.song, self.text, *_key_of(self.found))

    def label(self, v: Version) -> str:
        """The name of the version ``v`` of this sheet ("G Dorian, capo 0"), as its export is recorded under."""
        return self._read(lambda: version_label(v, self.shapes, self.capo))

    def entry(self, v: Version) -> str:
        """The ``[version]`` entry Make this my version writes for the version ``v`` of this sheet: ``v`` kept by its
        key (``version.version_entry``: ``key=Gm&mode=dorian&capo=0``), so that a sheet in another key in its place
        plays there too; for a sheet with no key, a move from it, as an address that names its ``t``
        (``export_query``), which the song's ``[transpose]`` never takes the place of. Two versions with one entry
        play this sheet alike."""
        found = self._read(lambda: version_entry(v, self.text, key=self.shapes, capo_sheet=self.capo))
        return export_query(v) if found is None else found

    def kept(self, v: Version, overrides: Overrides) -> str | None:
        """What Make this my version leaves in the song's ``[version]`` for ``v`` (``entry``), or None where ``v``
        plays this sheet where the song plays without one (its ``[transpose]``, else as written): the entry goes,
        and the song follows its sheet again."""
        entry = self.entry(v)
        return None if entry == self.entry(Version(t=overrides.transpose.get(self.song.key, 0))) else entry

    def _read(self, read):
        try:
            return read()
        except Exception as e:
            raise RenderError(f"cannot read the sheet: {type(e).__name__}: {e}") from e


def export_sheet(conn: sqlite3.Connection, cfg: Config, song: Song) -> ExportSheet:
    """The sheet the song's exports are made from, as its viewer reads it (``ExportSheet``). Raises RenderError
    when the song keeps no sheet, or keeps one the viewer's code can't read (a bug)."""
    _, text, found = _export_source(conn, cfg, song)
    try:
        shapes = viewer_key(text, *_key_of(found))
        capo = parse_sheet(text).capo
    except Exception as e:
        raise RenderError(f"cannot read the sheet: {type(e).__name__}: {e}") from e
    return ExportSheet(song, text, found, shapes, capo)


def export_query(v: Version) -> str:
    """The version as an address that always says its ``t``, so reading it back needs no song."""
    rest = [part for part in version_query(v).split("&") if part and not part.startswith("t=")]
    return "&".join([f"t={v.t}", *rest])


def export_viewer(conn: sqlite3.Connection, song: Song) -> str | None:
    """The viewer of the sheet the song's exports are made from: the human sheet's ("sheet.html"), else the auto
    sheet's ("sheet (auto).html"); None when it keeps no sheet. An auto sheet kept beside a human one shows
    other chords, so its viewer offers no export (``_render_song``), and caracole serve refuses one from it."""
    names = {f.name for f in kept_files(conn, song.id)}
    if HUMAN_SHEET in names:
        return HUMAN_OUTPUTS[2]
    return AUTO_OUTPUTS[2] if AUTO_SHEET in names else None


def _export_source(conn: sqlite3.Connection, cfg: Config, song: Song):
    """The sheet an export is made from (the human one, else the auto one: ``export_viewer``), its ChordPro text
    and its key. Raises RenderError when the song keeps no sheet."""
    files = {f.name: f for f in kept_files(conn, song.id)}
    if (kept := files.get(HUMAN_SHEET)) is not None:
        sheet = _human_sheet(conn, cfg.library_dir, kept)
    elif (kept := files.get(AUTO_SHEET)) is not None:
        sheet = _auto_sheet(cfg.library_dir, kept)
    else:
        raise RenderError(f"{song.display} keeps no sheet to export")
    found = sheet_keys(conn, cfg.library_dir, song)[1 if sheet.auto else 0]
    return sheet, _sheet_cho(song, sheet), found


def _key_of(found: SongKey | None) -> tuple[str | None, str | None]:
    """A sheet's key as ``keys.sheet_keys`` finds it, and where it came from (its ``source``), for the viewer's code
    (``page.viewer_key``): (None, None) for none."""
    return (found.key, found.source) if found is not None else (None, None)


def _sheet_cho(song: Song, sheet: _Sheet) -> str:
    """The ChordPro text of one of the song's sheets, as ``sheet.cho`` (or ``sheet (auto).cho``) is written."""
    return _chordpro_text(sheet.markup, title=clean_title(song.title), artist=song.artist,
                          key=sheet.key, capo=sheet.capo, auto=sheet.auto)


def render_version(
    conn: sqlite3.Connection,
    cfg: Config,
    overrides: Overrides,
    song: Song,
    v: Version,
    *,
    runner: Runner = subprocess.run,
    force: bool = False,
    pdf_fonts: Any = _CONFIG,
) -> Path:
    """Render the song's sheet in the version ``v`` (its key, capo, mode, chosen shapes and swaps, as the
    viewer shows it: ``apply_version``) to ``sheet (<label>).pdf`` in its folder, and return the path.

    The sheet is the human one, else the auto one. The export is recorded in kv ``render:export:<song id>``
    under its label (``version_label``): {"pdf", "query", "source_sha", "style", "printed_sha", "pdf_text",
    "font", "fonts", "pdf_sha256", "pdf_size"}; another export with the same label replaces the file and the record,
    and one whose record says it was made from this very text and is still on disk is not rendered again
    (unless ``force``). A render pass remakes the exports whose sheet or style changed (``_remake_exports``).
    It is set in the PDF fonts ``pdf_fonts`` hands over (a pass's), else ``cfg``'s when chordpro can use them.
    Raises RenderError: no sheet kept, a sheet that can't be read or made, a CJK font needed and missing, or
    chordpro failing.
    """
    sheet, text, found = _export_source(conn, cfg, song)
    folder = song_dir(cfg.library_dir, song)
    fonts = _pdf_fonts(cfg.pdf_fonts)[0] if pdf_fonts is _CONFIG else pdf_fonts
    try:
        shapes = viewer_key(text, *_key_of(found))
        capo = parse_sheet(text).capo
        label = version_label(v, shapes, capo)
        printed = _version_text(text, v, shapes, capo, fonts=fonts)
    except Exception as e:  # a sheet the viewer's code can't read
        log.warning("%s: cannot make the export %s", song.display, version_query(v), exc_info=True)
        raise RenderError(f"cannot make the export: {type(e).__name__}: {e}") from e
    pdf = folder / f"sheet ({safe_name(label)}).pdf"
    font, lost = pdf_font(printed, _cjk_font(cfg.cjk_font)[0], fonts)
    if lost is not None:
        raise RenderError(f"{pdf.name} needs a CJK font: {FONT_HINT}")
    state = {
        "pdf": pdf.name,
        "query": export_query(v),
        "source_sha": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "style": _style(),
        "pdf_text": PDF_TEXT_VERSION,
        "printed_sha": hashlib.sha256(printed.encode("utf-8")).hexdigest(),
        "font": str(font) if font else None,
        "fonts": _fonts_record(fonts),
    }
    key = f"{EXPORT_KV}{song.id}"
    record = kv_get_json(conn, key)
    record = {k: e for k, e in record.items() if isinstance(e, Mapping)} if isinstance(record, Mapping) else {}
    if not force and _up_to_date(pdf, record.get(label), state):
        return pdf
    sha, size = _render_into(printed, pdf, work_dir=cfg.cache_dir, chordpro_bin=cfg.chordpro_bin, font_file=font,
                             fonts=fonts, runner=runner)
    # The label names the file, so another label never names the same one; a name that sorts the same
    # after safe_name is the same file, and its older record goes.
    record = {k: e for k, e in record.items() if e.get("pdf") != pdf.name}
    record[label] = {**state, "pdf_sha256": sha, "pdf_size": size}
    kv_set_json(conn, key, record)
    return pdf


def _remake_exports(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, song: Song, *,
                    cjk_font: Path | None, runner: Runner, force: bool, fonts: PdfFonts | None = None) -> None:
    """Render the song's exports again that its sheet, the style or the viewer's theory changed; the others
    are left (``render_version``). One that can't be made is logged, and the rest go on.

    An export whose version is named otherwise now (a sheet in another key or capo took the old one's place, an
    auto sheet's key was heard again) is made under its new name, and the PDF under the old one goes with its
    record (``_drop_export``)."""
    record = kv_get_json(conn, f"{EXPORT_KV}{song.id}")
    if not isinstance(record, Mapping):
        return
    for label, entry in list(record.items()):
        query = entry.get("query") if isinstance(entry, Mapping) else None
        if not isinstance(query, str):
            continue
        try:
            pdf = render_version(conn, cfg, overrides, song, version_from_query(query), runner=runner, force=force,
                                 pdf_fonts=fonts)
        except (RenderError, OSError) as e:
            log.warning("no export for %s (%s): %s", song.display, query, e)
            continue
        if pdf.name != entry.get("pdf"):
            _drop_export(conn, cfg.library_dir, song, label, entry)


def _drop_export(conn: sqlite3.Connection, library_dir: Path, song: Song, label: str, entry: Mapping[str, Any]) -> None:
    """Forget the export recorded under ``label`` as ``entry``, made again under another name, and delete its PDF
    while it holds what caracole wrote (``_delete_as_written``). Neither when another export has taken that
    label or that file since: two exports can swap names."""
    key = f"{EXPORT_KV}{song.id}"
    record = kv_get_json(conn, key)
    record = {k: e for k, e in record.items() if isinstance(e, Mapping)} if isinstance(record, Mapping) else {}
    if record.get(label) == entry:
        del record[label]
        if record:
            kv_set_json(conn, key, record)
        else:
            kv_delete(conn, key)
    name = entry.get("pdf")
    if isinstance(name, str) and is_export(name) and all(e.get("pdf") != name for e in record.values()):
        _delete_as_written(library_dir, song, name, entry.get("pdf_sha256"), entry.get("pdf_size"))


def _delete_as_written(library_dir: Path, song: Song, name: str, sha256: Any, size: Any) -> None:
    """Delete the file ``name`` in the song's folder while it holds what caracole wrote there (``sha256``,
    ``size``), as removal.py deletes: each folder opened from the library down and the file by name, none
    through a link. A file changed since (on a synced device, say) is yours and stays, and so does a link."""
    if not isinstance(sha256, str) or not isinstance(size, int) or "/" in name:
        return
    fds: list[int] = []
    try:
        fds.append(os.open(library_dir, os.O_RDONLY | os.O_DIRECTORY))
        for part in song_dir(library_dir, song).relative_to(library_dir).parts:
            fds.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[-1]))
        with open(open_regular(Path(name), dir_fd=fds[-1]), "rb") as f:
            if os.fstat(f.fileno()).st_size != size or hashlib.file_digest(f, "sha256").hexdigest() != sha256:
                return
        os.unlink(name, dir_fd=fds[-1])
    except OSError as e:  # gone already, a link or no regular file in its place, a folder that is a link
        log.info("%s: the export %s stays (%s)", song.display, name, e)
    finally:
        for fd in fds:
            os.close(fd)


def _render_sheet(
    conn: sqlite3.Connection,
    cfg: Config,
    song: Song,
    folder: Path,
    kept: KeptFile,
    text: str,
    state_key: str,
    version: Version,
    *,
    start: str | None,
    cjk_font: Path | None,
    runner: Runner,
    force: bool,
    fonts: PdfFonts | None = None,
    key: tuple[str | None, str | None] = (None, None),
    export: bool = True,
    primary: bool = False,
    versions: dict[str, Any] | None = None,
    guitar: tuple[str, ...] = (),
    harmonica: tuple[Mapping[str, str], ...] = (),
) -> _Done:
    """Write one sheet's .cho, ``text`` (``_sheet_cho``), render its PDF in ``version`` unless kv ``state_key``
    says it is up to date, then write its viewer (``_write_viewer``), which needs no PDF: a failed render, or a
    sheet waiting for a CJK font, still gets one. ``key`` is the sheet's (``keys.sheet_keys``); ``start``, the
    song's own version as the viewer's address writes it, where the viewer starts, or None for none;
    ``export``, whether the viewer offers an export (``export_viewer``); ``primary``, whether this is the
    song's sheet the library finds it by (its human one, else its auto one: ``_note_progressions``);
    ``versions``, the song's versions as this viewer lists them (``_on_page``), or None; ``guitar``, the names of the
    song's Guitar Pro files its viewer links; ``harmonica``, its harmonica tabs, which its viewer names.

    The PDF, the viewer and the record of the .cho are made from the text written, never read
    back: a synced device may write there a moment later."""
    stem = Path(kept.name).stem
    cho = folder / f"{stem}.cho"
    data = text.encode("utf-8")
    _write_if_changed(cho, data)
    _note_written(conn, song.id, cho.name, data)
    if primary:
        _note_progressions(conn, song, text, *key)
    pdf = folder / f"{stem}.pdf"

    def viewer() -> bool:
        page = folder / f"{stem}.html"
        data = _write_viewer(song, text, page, pdf, key=key, transpose=version.t, start=start, export=export,
                             versions=versions, guitar=guitar, harmonica=harmonica)
        if data is not None:
            _note_written(conn, song.id, page.name, data)
        return data is not None

    try:
        done = _render_sheet_pdf(conn, cfg, song, text, pdf, state_key, on_the_guitar(version), key=key,
                                 cjk_font=cjk_font, fonts=fonts, runner=runner, force=force)
    except RenderError:
        viewer()  # the PDF's error is the song's; the viewer's own, if any, is logged
        raise
    return done if viewer() else replace(done, viewer_failed=True)


def _note_progressions(conn: sqlite3.Connection, song: Song, text: str, key: str | None,
                       key_source: str | None = None) -> None:
    """Record what the sheet ``text`` plays, in its key (``key``, from ``key_source``), for finding the song by its
    progressions (``progressions.record``). An extra, as the viewer is: a sheet its code can't read leaves no
    record, logged with its traceback, and costs the song nothing else."""
    try:
        progressions.record(conn, song.id, text, key, key_source)
    except Exception:  # a bug in the theory must never cost the PDFs
        log.warning("no progressions for %s", song.display, exc_info=True)
        progressions.forget(conn, song.id)


def _render_sheet_pdf(
    conn: sqlite3.Connection,
    cfg: Config,
    song: Song,
    text: str,
    pdf: Path,
    state_key: str,
    version: Version,
    *,
    key: tuple[str | None, str | None],
    cjk_font: Path | None,
    runner: Runner,
    force: bool,
    fonts: PdfFonts | None = None,
) -> _Done:
    """Render the ChordPro ``text`` to ``pdf`` in ``version`` unless kv ``state_key`` says it is up to date:
    chordpro prints the PDF's own text (``_sheet_text``, in ``key``: the sheet's and where it came from), in the
    PDF fonts ``fonts``, and the CJK font is there when that text needs it (``pdf_font``). A text that can't be made (a bug in the viewer's code it runs) is a
    RenderError, logged with its traceback: this PDF fails, and the pass goes on."""
    try:
        printed = _sheet_text(text, key=key[0], key_source=key[1], version=version, fonts=fonts)
    except Exception as e:  # a sheet the viewer's code can't read must never cost the other PDFs
        log.warning("%s: cannot make the text of %s", song.display, pdf.name, exc_info=True)
        raise RenderError(f"cannot make the text of {pdf.name}: {type(e).__name__}: {e}") from e
    font, lost = pdf_font(printed, cjk_font, fonts)
    if lost is not None:
        return _Done("no font", missing=lost)
    state = {
        "source_sha": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "transpose": version.t,  # info.json's; the rest of the version is in the text printed
        "font": str(font) if font else None,
        "fonts": _fonts_record(fonts),
        "style": _style(),
        "pdf": pdf.name,
        "pdf_text": PDF_TEXT_VERSION,
        # What chordpro prints, made from more than the .cho: the sheet's key (an auto sheet's is
        # heard, in its version's data) and the viewer's theory and shapes, which a newer caracole changes
        "printed_sha": hashlib.sha256(printed.encode("utf-8")).hexdigest(),
    }
    if not force and _up_to_date(pdf, kv_get_json(conn, state_key), state):
        return _Done("skipped")
    sha, size = _render_into(printed, pdf, work_dir=cfg.cache_dir, chordpro_bin=cfg.chordpro_bin, font_file=font,
                             fonts=fonts, runner=runner)
    kv_set_json(conn, state_key, {**state, "pdf_sha256": sha, "pdf_size": size})
    write_info(conn, cfg.library_dir, song)  # its "render" entry: the PDF, the transposition
    return _Done("rendered")


def _sheet_text(text: str, *, key: str | None, version: Version, key_source: str | None = None,
                fonts: PdfFonts | None = None, diagrams: bool = True) -> str:
    """The text chordpro prints of the sheet ``text`` in ``version``: the sheet as written (``Version()``) as it
    is (``_printed``), else in that version as its viewer shows it (``_version_text``), on its instrument.
    ``key`` is the sheet's (``keys.sheet_keys``), and ``key_source`` where it came from; ``fonts``, the PDF fonts
    its columns are levelled in (``pdf_text``); ``diagrams``, whether a fretted instrument's are drawn."""
    if version == Version() and diagrams:
        return _printed(text, key=key, key_source=key_source, capo=parse_sheet(text).capo, fonts=fonts)
    return _version_text(text, version, viewer_key(text, key, key_source), parse_sheet(text).capo, fonts=fonts,
                         diagrams=diagrams)


def _version_text(text: str, v: Version, shapes: Key | None, capo: int | None, *,
                  fonts: PdfFonts | None = None, diagrams: bool = True) -> str:
    """The text chordpro prints of the sheet ``text`` in the version ``v``: each chord named and shaped as the
    viewer shows it there (``apply_version``), then the PDF's own text of that (``pdf_text``), each chord's diagram
    the shape its ``{define}`` gives, with the key line of the shapes the version plays and its capo. A capo the
    sheet's notes name is printed only where the version plays its chords where the sheet writes them, at the
    sheet's capo: one that moves them or the capo plays them elsewhere (A shapes with the capo off a sheet whose
    notes say capo 2 sound A). ``shapes`` and ``capo`` are the sheet's, as its viewer reads them
    (``page.viewer_key``, its ``{capo}``). On the version's instrument (``v.inst``: pdf_text.py), its fretted
    shapes drawn unless not ``diagrams`` (a songbook's PDF draws one number of strings)."""
    played, played_capo = played_key(v, shapes, capo)
    in_place = v.t == 0 and played_capo == (capo or 0)  # no move: the chords' shift is t less the capo's move
    return _as_latin(pdf_text(apply_version(text, v, key=shapes, capo_sheet=capo), key=played, capo=played_capo,
                              notes_capo=in_place, defined=True, fonts=fonts, instrument=played_on(v),
                              diagrams=diagrams))


def _printed(text: str, *, key: str | None, capo: int | None, key_source: str | None = None,
             fonts: PdfFonts | None = None) -> str:
    """The text chordpro prints of the sheet ``text`` as written (``pdf_text``), with the key of its shapes as
    its viewer names it from ``key`` (the sheet's, ``keys.sheet_keys``, from ``key_source``), and the look-alike
    letters capitals can make written in Latin (``_as_latin``)."""
    return _as_latin(pdf_text(text, key=viewer_key(text, key, key_source), capo=capo, fonts=fonts))


def _write_viewer(song: Song, text: str, page: Path, pdf: Path | None, *, key: tuple[str | None, str | None],
                  transpose: int, start: str | None, export: bool = True,
                  versions: dict[str, Any] | None = None, guitar: tuple[str, ...] = (),
                  harmonica: tuple[Mapping[str, str], ...] = ()) -> bytes | None:
    """Write the sheet's viewer (``viewer.build_viewer``) beside its PDF, linking the PDF when
    there is one (a version page has none: ``pdf`` None), and return the page's bytes. It starts where the
    PDF is: at ``transpose``, in the song's own version (``start``) when it has one, and takes the sheet's
    key (``keys.sheet_keys``) when it has one; with ``export``, it offers Export PDF of this version;
    ``versions`` lists the song's versions, and ``guitar`` its Guitar Pro files caracole serve shows in the
    browser (``inbox.guitar_files``), and ``harmonica`` its harmonica tabs (``inbox.harmonica_files``). A viewer that
    hasn't changed isn't written again.

    The viewer is an extra: None, logged as "no viewer for", when it can't be built (a bug,
    with its traceback) or written (a link or a FIFO in its place), and the song's PDFs and
    its other sheet go on all the same.
    """
    linked = pdf.name if pdf is not None and pdf.is_file() and not pdf.is_symlink() else None
    try:
        html = build_viewer(text, key=key[0], key_source=key[1], transpose=transpose, start=start, pdf=linked,
                            export=export, versions=versions, guitar=guitar, harmonica=harmonica)
    except Exception:  # a sheet the viewer can't read must never cost the PDFs
        log.warning("no viewer for %s: cannot build %s", song.display, page.name, exc_info=True)
        return None
    data = html.encode("utf-8")
    try:
        _write_if_changed(page, data)
    except (RenderError, OSError) as e:
        log.warning("no viewer for %s: %s", song.display, e)
        return None
    return data


def written_file(conn: sqlite3.Connection, song_id: int, name: str) -> tuple[str, int] | None:
    """The SHA-256 and the length of the .cho or the viewer ``name`` caracole last wrote in the
    song's folder ("sheet.html", "sheet (auto).cho"), or None when it wrote none there.

    For a server: anyone with a synced device can put a page in the library, so a viewer is
    served only while ``library.holds`` says it is still these bytes, and with
    ``viewer.viewer_csp(page)``, the policy of those bytes, as its Content-Security-Policy header.
    """
    return written_entry(_written(conn, song_id).get(name))


def written_entry(entry: Any) -> tuple[str, int] | None:
    """The SHA-256 and the length a record's entry of a file written says (``{"sha256", "size"}``), or None
    for an entry that says neither (a device's edit of the database's JSON, an older shape): the one
    reading of those records, a sheet's .cho and viewer's (``written_file``) and a songbook's files'."""
    if not isinstance(entry, Mapping):
        return None
    sha, size = entry.get("sha256"), entry.get("size")
    return (sha, size) if isinstance(sha, str) and type(size) is int else None


def _written(conn: sqlite3.Connection, song_id: int) -> dict[str, dict[str, Any]]:
    """kv ``render:files:<song id>``: {name: {"sha256", "size"}}, its odd entries left out."""
    record = kv_get_json(conn, f"{FILES_KEY}{song_id}")
    if not isinstance(record, Mapping):
        return {}
    return {name: entry for name, entry in record.items() if written_entry(entry) is not None}


def _note_written(conn: sqlite3.Connection, song_id: int, name: str, data: bytes) -> None:
    """Record that the file ``name`` in the song's folder holds ``data``, as caracole wrote it."""
    written = _written(conn, song_id)
    entry = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    if written.get(name) != entry:
        written[name] = entry
        kv_set_json(conn, f"{FILES_KEY}{song_id}", written)


def _forget_written(conn: sqlite3.Connection, song_id: int, names: tuple[str, ...],
                    folder: Path | None = None) -> None:
    """Forget the files ``names``; with ``folder``, first remove each one still as written there
    (``library.holds``): one of yours by that name stays."""
    written = _written(conn, song_id)
    gone = [name for name in names if name in written]
    if not gone:
        return
    for name in gone:
        entry = written.pop(name)
        if folder is not None and holds(folder / name, entry["sha256"], entry["size"]):
            (folder / name).unlink(missing_ok=True)
    if written:
        kv_set_json(conn, f"{FILES_KEY}{song_id}", written)
    else:
        kv_delete(conn, f"{FILES_KEY}{song_id}")


def _up_to_date(pdf: Path, record: Any, state: Mapping[str, Any]) -> bool:
    """Whether the kv ``record`` says the PDF was rendered from ``state``, and the PDF is still what was
    written: its length, then its SHA-256 (``library.holds``). A record without those predates them,
    and its PDF is rendered once more."""
    if not isinstance(record, Mapping) or any(record.get(k) != v for k, v in state.items()):
        return False
    sha, size = record.get("pdf_sha256"), record.get("pdf_size")
    return isinstance(sha, str) and isinstance(size, int) and holds(pdf, sha, size)


def _drop_human_outputs(conn: sqlite3.Connection, library_dir: Path, song: Song, folder: Path) -> None:
    """The song keeps no human sheet now (the fetch dropped one whose UG match was undone, say): the
    .cho, the PDF and the viewer rendered from the one it kept go, with their record, before an
    auto sheet's PDF takes the record's place. Only when the record says caracole rendered them: a
    ``sheet.cho`` or ``sheet.pdf`` of yours, in a folder caracole never rendered a human sheet in,
    stays. A sheet that never got a PDF (waiting for a font, or chordpro failed on it) still had
    its .cho and viewer written: each goes while it is still as written (``_forget_written``)."""
    _forget_written(conn, song.id, (HUMAN_OUTPUTS[0], HUMAN_OUTPUTS[2]), folder)
    key = _state_key(song.id)
    record = kv_get_json(conn, key)
    if not isinstance(record, Mapping) or record.get("pdf") != HUMAN_OUTPUTS[1]:
        return
    for name in HUMAN_OUTPUTS:
        (folder / name).unlink(missing_ok=True)
    kv_delete(conn, key)
    write_info(conn, library_dir, song)  # its "render" entry is gone too


def _state_key(song_id: int, *, auto: bool = False) -> str:
    """kv: what a PDF was made from (written here; ``library.write_info`` reads the song's own).

    ``auto`` names the record of an auto sheet's PDF rendered beside a human sheet's.
    """
    return f"render:{song_id}:auto" if auto else f"render:{song_id}"


# --- where a sheet comes from ----------------------------------------------------------


@dataclass(frozen=True)
class _Sheet:
    """What a song's ChordPro file is made from."""

    markup: str
    key: str | None = None
    capo: int | None = None
    auto: bool = False


def _read_text(path: Path) -> str:
    """A file in the library as UTF-8 text, never read through a symbolic link (``read_regular``).

    Others can write to the library (the Syncthing group, every synced device). A
    link planted there to one of caracole's private files would have it printed into
    the .cho and the PDF, and a FIFO would hold up the pass. Raises RenderError.
    """
    try:
        return read_regular(path).decode("utf-8")
    except (OSError, ValueError) as e:  # NotRegularFile is an OSError; ValueError: not UTF-8
        raise RenderError(f"cannot read {path}: {e}") from e


def _human_sheet(conn: sqlite3.Connection, library_dir: Path, kept: KeptFile) -> _Sheet:
    """The sheet the fetch step kept: the markup in sheet.json, the key UG gives the version."""
    return _ug_sheet((library_dir / kept.path).with_name("sheet.json"), get_version(conn, kept.version_id).raw)


def _ug_sheet(path: Path, raw: Mapping[str, Any]) -> _Sheet:
    """A sheet from the JSON the fetch keeps beside its text (sheet.json, a version's
    ``version-<tab>.json``): its markup and its capo, and the key UG gives the version (``raw``)."""
    try:
        doc = read_json(path)
    except (OSError, ValueError) as e:  # ValueError: not UTF-8, not JSON, or nested too deep
        raise RenderError(f"cannot read {path}: {e}") from e
    content = doc.get("content") if isinstance(doc, Mapping) else None
    if not isinstance(content, str) or not content.strip():
        raise RenderError(f"{path} holds no sheet content")
    return _Sheet(decode_twice(content), key=_key(raw), capo=_capo(doc.get("meta")))


def _key(raw: Mapping[str, Any]) -> str | None:
    """The key UG gives a version (``tonality_name``, often empty)."""
    value = raw.get("tonality_name")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _capo(meta: Any) -> int | None:
    """The capo fret in UG's ``tab_view.meta``: a number or a digit string, else no capo."""
    value = meta.get("capo") if isinstance(meta, Mapping) else None
    fret = None if isinstance(value, bool) else json_int(value)
    return fret if fret is not None and fret > 0 else None


def _auto_sheet(library_dir: Path, kept: KeptFile) -> _Sheet:
    """An auto-chords sheet without its two header lines, which to_chordpro writes as directives."""
    lines = _read_text(library_dir / kept.path).splitlines()
    if lines and lines[0].strip() == AUTO_MARKER:
        lines = lines[2:]  # the marker, then "Artist - Title"
    return _Sheet("\n".join(lines), auto=True)


# --- the PDF ---------------------------------------------------------------------------


def _render_into(
    text: str,
    pdf: Path,
    *,
    work_dir: Path,
    chordpro_bin: str,
    font_file: Path | None,
    runner: Runner,
    fonts: PdfFonts | None = None,
) -> tuple[str, int]:
    """``render_pdf`` of the ChordPro ``text`` (a PDF's own, ``_printed``) in a private directory, then
    the PDF to ``pdf``; return the SHA-256 and the length of the PDF written.

    chordpro opens its input and its output by name and follows symbolic links, and
    others can write to the song's folder: either file could be swapped for a link
    while it runs, to print one of caracole's private files into the PDF or to write
    over it. So chordpro reads the text, as a file, and writes the PDF in a directory
    of its own under ``work_dir`` (the cache), which only caracole can enter (mode
    0700). The PDF then goes to ``pdf`` through ``write_atomic``, so a failed run
    leaves the last good one in place, and another caracole rendering the same sheet
    isn't in the way. Both files keep the sheet's names: chordpro picks its backend
    by the extension, and its messages then say which sheet failed.
    """
    with private_dir(work_dir, "render-") as tmp:
        cho, out = tmp / f"{pdf.stem}.cho", tmp / pdf.name
        cho.write_bytes(text.encode("utf-8"))
        render_pdf(cho, out, chordpro_bin=chordpro_bin, font_file=font_file, fonts=fonts, runner=runner)
        data = out.read_bytes()
        return write_atomic(pdf, data), len(data)


@contextmanager
def private_dir(cache_dir: Path, prefix: str) -> Iterator[Path]:
    """A folder of its own under ``cache_dir``, named from ``prefix``, which only caracole can enter (mode
    0700), and gone once done: where chordpro reads copies and writes its file (``_render_into``, a
    songbook's files), as it follows links and the library is anyone's to write."""
    cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=prefix, dir=cache_dir) as tmp:
        yield Path(tmp)


_INVISIBLE = frozenset({"Cc", "Cf"})  # controls, zero-width spaces, byte-order marks


def pdf_font(text: str, cjk_font: Path | None, fonts: PdfFonts | None = None) -> tuple[Path | None, str | None]:
    """The font file chordpro prints the words of the PDF text ``text`` in, and the first letter it would lose:
    the CJK font ``cjk_font`` (one ``_cjk_font`` found usable, or None) when the PDF's fonts lose some of
    ``text``, else none; a letter lost only when they lose letters (``_font_need``) and no font is set,
    and the PDF then waits for one.

    The PDF's fonts are ``fonts`` (``_pdf_fonts``), judged by the letters their regular font has: Latin,
    Greek and Cyrillic, curly quotes and a modifier letter's apostrophe (ʼ) need no CJK font, so a Latin
    sheet is never set in its brush face; Chinese still does, and a symbol they lack only blemishes the PDF.
    Without them, ChordPro's built-in fonts, which lose anything WinAnsi lacks, and a lost symbol takes the
    CJK font too."""
    need = _font_need(text, fonts)
    if need == "letters" and cjk_font is None:
        return None, _first_lost_letter(text, fonts)
    if fonts is not None:
        return (cjk_font if need == "letters" else None), None
    return (cjk_font if need else None), None


def _font_need(text: str, fonts: PdfFonts | None = None) -> Literal["letters", "symbols"] | None:
    """What the PDF's fonts would lose of ``text``: ``fonts``' regular one, else ChordPro's built-in fonts.

    Invisible characters don't count, as there is nothing to lose. Lost letters
    (Chinese lyrics, say) leave a sheet unsingable; a lost symbol, such as a
    music note, only blemishes it.
    """
    lacks = _lacks(fonts)
    lost = {unicodedata.category(ch) for ch in set(text) if lacks(ch)} - _INVISIBLE
    if any(category.startswith("L") for category in lost):
        return "letters"
    return "symbols" if lost else None


def _lacks(fonts: PdfFonts | None) -> Callable[[str], bool]:
    """Whether the PDF's fonts lack a character: ``fonts``' regular one (its characters, ``pdf_fonts.metrics``),
    else ChordPro's built-in fonts (``needs_font_file``)."""
    if fonts is None:
        return needs_font_file
    have = metrics(fonts.regular).widths
    return lambda ch: ch not in have


def _fonts_record(fonts: PdfFonts | None) -> str | None:
    """What a PDF's record keeps of the PDF fonts it was set in: their folder, None for the built-in fonts (a
    record from before ``pdf_fonts`` has none, and is still up to date without them: ``_up_to_date``)."""
    return str(fonts.folder) if fonts is not None else None


def _usable_pdf_fonts(cfg: Config) -> PdfFonts | None:
    """``cfg.pdf_fonts`` when chordpro can use them (``_pdf_fonts``), checked once for a pass, which says once
    why it can't: the PDFs keep the built-in fonts."""
    fonts, problem = _pdf_fonts(cfg.pdf_fonts)
    if problem:
        log.warning("%s", problem)
    return fonts


def _cjk_font(path: Path | None) -> tuple[Path | None, str | None]:
    """The CJK font when ChordPro can use it; otherwise None, and what is wrong with the one set.

    Checked once per pass: an unusable font (a .ttc collection, a missing file)
    then counts as none, instead of failing every sheet that needs it.
    """
    if path is None:
        return None, None
    try:
        _font_options(path)
    except RenderError as e:
        return None, f"cjk_font is unusable: {e}"
    return path, None


def _font_error(songs: Mapping[str, str], problem: str | None = None, shown: int = 3) -> str:
    """One line for every sheet that has no PDF for want of a usable CJK font (``songs``: each one's
    first letter that needs it)."""
    listed = [f"{name} ({letter} U+{ord(letter):04X})" for name, letter in songs.items()]
    names = ", ".join(listed[:shown])
    more = f" and {len(listed) - shown} more" if len(listed) > shown else ""
    reason = f"{problem}; " if problem else ""
    return f"{reason}{FONT_HINT} to render {names}{more}"
