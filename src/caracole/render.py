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
never costs it a PDF. kv ``render:files:<song id>`` keeps the SHA-256 and the
length of each .cho and viewer written (``written_file``), PDF or no PDF: a
server serves a viewer only while it is still those bytes.

A human sheet the song no longer keeps (the fetch drops one whose UG match was
undone when nothing replaces it) takes the ``sheet.cho``, ``sheet.pdf`` and
``sheet.html`` rendered from it along, at the next pass. Only what the records
say caracole wrote goes: the three when the PDF's record below names it, else
the .cho and the viewer while they are still as written. Files of yours by
those names stay.

The PDFs take caracole's look (``STYLE_FILE``, a ChordPro config) and are in
the song's own version (``own_version``): its ``[version]`` override ("Make
this my version": a key, mode, capo, shapes and swaps), else its
``[transpose]``, else the sheet as written; the viewer starts there too. Each
is made from a text of its own (caracole/pdf_text.py), the .cho staying as the
viewer reads it: in a version, each chord named and shaped as the viewer shows
it there (``apply_version``); without the tab's notes, the shapes its viewer shows
(its chord legend's) as chord diagrams,
the viewer's key line under the title, section names in capitals, in two columns. That
text runs the viewer's code: a bug there fails that song's PDF alone, logged with its traceback,
as a chordpro failure does, and its viewer is still written. kv ``render:<song id>``
keeps what the song's PDF was made from (the SHA-256 of the .cho, the
version's transposition, the font, the SHA-256 of the style, the PDF's name,
``pdf_text.PDF_TEXT_VERSION`` and the SHA-256 of the text chordpro prints, whose
key line and chord diagrams come from more than the .cho) and what was
written (the PDF's length and SHA-256): its human sheet's, else its auto
sheet's. ``render:<song id>:auto`` does the same for an auto sheet's PDF
beside a human one. A PDF is rendered again only when one of those changes,
when it is missing or no longer what was written (cut short by a power cut,
changed on a synced device, a link in its place), or when forced: its length
is compared, then, when that matches, its SHA-256. A sheet whose letters the
built-in fonts lack gets its .cho and viewer but no PDF until a usable CJK font is set:
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
import sqlite3
import struct
import subprocess
import tempfile
import unicodedata
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qsl

from caracole.autochords.merge import AUTO_MARKER
from caracole.chordpro import to_chordpro
from caracole.config import Config
from caracole.db import kv_delete, kv_get_json, kv_set_json
from caracole.library import (
    KeptFile,
    NotRegularFile,
    holds,
    kept_files,
    read_json,
    read_regular,
    safe_name,
    song_dir,
    write_atomic,
    write_info,
)
from caracole.keys import sheet_keys
from caracole.normalize import clean_title
from caracole.overrides import Overrides, OverridesError, load_overrides
from caracole.pdf_text import PDF_TEXT_VERSION, pdf_text
from caracole.songs import (
    AUTO_SHEET,
    HUMAN_SHEET,
    SHEET_OUTPUTS,
    Song,
    ensure_current_keys,
    get_song,
    list_songs,
)
from caracole.ug.page import decode_twice, json_int
from caracole.versions import get_version
from caracole.viewer import build_viewer
from caracole.viewer.page import viewer_key
from caracole.viewer.sheet import parse_sheet
from caracole.viewer.theory import Key
from caracole.viewer.version import (
    Version,
    apply_version,
    played_key,
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

# How the PDFs look (a ChordPro config): Helvetica, bold chords in caracole's rust,
# the chord diagrams above the song, section names in small rust capitals with no band,
# and under the title the text's {subtitle} (pdf_text.py: the artist, the viewer's key
# line, a capo or a tuning the notes name), as ChordPro prints neither the artist nor the
# capo by default: a capo the guitarist can't see means playing in the wrong key. Its
# SHA-256 is in each PDF's record, so a new look renders every PDF once more.
STYLE_FILE = Path(__file__).with_name("chordpro-style.json")

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


def _first_lost_letter(text: str) -> str | None:
    """The letter a font file is needed for: the first lost one with no Latin twin, if any."""
    lost = [ch for ch in text if _lost_letter(ch)]
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
    runner: Runner = subprocess.run,
) -> None:
    """Render ``cho`` to ``pdf``, its chords where it names them (chordpro transposes nothing).

    Raises RenderError when the binary is missing, exits non-zero, times out
    or writes no PDF.
    """
    cmd = [chordpro_bin, "--nodefaultconfigs", f"--config={STYLE_FILE}"]
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


# --- the library ---------------------------------------------------------------------

Outcome = Literal["rendered", "skipped", "no font"]


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
                conn, cfg, overrides, song, cjk_font=font, runner=runner, force=force
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
) -> list[_Done]:
    """Render every sheet the song keeps, the human one first; [] when it keeps none.

    ``cjk_font`` is a usable font or None. The auto sheet is kept, and so
    rendered, until the fetch steps retire it for a complete human sheet; its
    outputs go once that has happened and the human sheet's PDF is in place.
    A human sheet the song no longer keeps takes its outputs along
    (``_drop_human_outputs``).

    Each viewer takes its own sheet's key, as ``keys.sheet_keys`` finds it and info.json
    records it: the human sheet's from the tab or its chords, the auto sheet's heard in the audio.
    """
    files = {f.name: f for f in kept_files(conn, song.id)}
    human, auto = files.get(HUMAN_SHEET), files.get(AUTO_SHEET)
    folder = song_dir(cfg.library_dir, song)
    done: list[_Done] = []
    human_key, auto_key = sheet_keys(conn, cfg.library_dir, song) if human or auto else (None, None)
    version = own_version(overrides, song)

    def render(kept: KeptFile, sheet: _Sheet, state_key: str, played: Version) -> None:
        found = auto_key if sheet.auto else human_key
        mine = (found.key, found.source) if found is not None else (None, None)
        done.append(_render_sheet(conn, cfg, song, folder, kept, sheet, state_key, played,
                                  start=export_query(played) if song.key in overrides.version else None,
                                  cjk_font=cjk_font, runner=runner, force=force, key=mine))

    if human is not None:
        render(human, _human_sheet(conn, cfg.library_dir, human), _state_key(song.id), version)
        if auto is None and done[-1].outcome != "no font":  # its PDF is in place
            for name in AUTO_OUTPUTS:
                (folder / name).unlink(missing_ok=True)
            kv_delete(conn, _state_key(song.id, auto=True))
            _forget_written(conn, song.id, AUTO_OUTPUTS)
    else:
        _drop_human_outputs(conn, cfg.library_dir, song, folder)
    if auto is not None:
        beside = human is not None
        # Beside the human sheet, the version's shapes and swaps are that sheet's chords', by their places
        render(auto, _auto_sheet(cfg.library_dir, auto), _state_key(song.id, auto=beside),
               replace(version, at={}, alt={}) if beside else version)
    if human is not None or auto is not None:
        _remake_exports(conn, cfg, overrides, song, cjk_font=cjk_font, runner=runner, force=force)
    return done


# --- an export: the sheet's PDF in another version ------------------------------------


# What of a viewer's address names where the song is played (viewer/version.py), besides its text size and the rest
_VERSION_NAMES = frozenset({"t", "mode", "capo", "alt", "at"})


def own_version(overrides: Overrides, song: Song) -> Version:
    """The song's own version, where its PDF, its viewer and its songbooks start: its ``[version]`` ("Make this
    my version"), at its ``[transpose]`` if that names no ``t``; else its ``[transpose]`` alone; else the sheet
    as written (``Version()``)."""
    transpose = overrides.transpose.get(song.key, 0)
    query = overrides.version.get(song.key)
    if query is None:
        return Version(t=transpose)
    version = version_from_query(query)
    return version if "t" in _names(query) else replace(version, t=transpose)


def _names(query: str) -> set[str]:
    """The names an address's query or fragment holds, as the viewer's URLSearchParams reads them."""
    return {name for name, _ in parse_qsl(query[1:] if query[:1] in ("#", "?") else query, keep_blank_values=True)}


def export_version(query: str, overrides: Overrides, song: Song) -> Version:
    """The version an address ``query`` holds (``version_from_query``), for an export, as the viewer reads its
    own address: one that names none of the version (its ``t``, ``mode``, ``capo``, ``alt`` or ``at``) is the
    song's own (``own_version``), where the viewer starts, and one that names no ``t`` is at the own version's,
    which the viewer leaves out of its address."""
    names = _names(query)
    mine = own_version(overrides, song)
    if not names & _VERSION_NAMES:
        return mine
    version = version_from_query(query)
    return version if "t" in names else replace(version, t=mine.t)


def export_query(v: Version) -> str:
    """The version as an address that always says its ``t``, so reading it back needs no song."""
    rest = [part for part in version_query(v).split("&") if part and not part.startswith("t=")]
    return "&".join([f"t={v.t}", *rest])


def _export_source(conn: sqlite3.Connection, cfg: Config, song: Song):
    """The sheet an export is made from (the human one, else the auto one), its ChordPro text and its key.
    Raises RenderError when the song keeps no sheet."""
    files = {f.name: f for f in kept_files(conn, song.id)}
    if (kept := files.get(HUMAN_SHEET)) is not None:
        sheet = _human_sheet(conn, cfg.library_dir, kept)
    elif (kept := files.get(AUTO_SHEET)) is not None:
        sheet = _auto_sheet(cfg.library_dir, kept)
    else:
        raise RenderError(f"{song.display} keeps no sheet to export")
    found = sheet_keys(conn, cfg.library_dir, song)[1 if sheet.auto else 0]
    text = _chordpro_text(sheet.markup, title=clean_title(song.title), artist=song.artist,
                          key=sheet.key, capo=sheet.capo, auto=sheet.auto)
    return sheet, text, found


def export_label(conn: sqlite3.Connection, cfg: Config, song: Song, v: Version) -> str:
    """The name of the version ``v`` of the song's sheet ("G Dorian, capo 0"), as its export is recorded
    under. Raises RenderError: no sheet kept, or a sheet the viewer's code can't read."""
    _, text, found = _export_source(conn, cfg, song)
    try:
        shapes = viewer_key(text, found.key if found is not None else None)
        return version_label(v, shapes, parse_sheet(text).capo)
    except Exception as e:
        raise RenderError(f"cannot read the sheet: {type(e).__name__}: {e}") from e


def render_version(
    conn: sqlite3.Connection,
    cfg: Config,
    overrides: Overrides,
    song: Song,
    v: Version,
    *,
    runner: Runner = subprocess.run,
    force: bool = False,
) -> Path:
    """Render the song's sheet in the version ``v`` (its key, capo, mode, chosen shapes and swaps, as the
    viewer shows it: ``apply_version``) to ``sheet (<label>).pdf`` in its folder, and return the path.

    The sheet is the human one, else the auto one. The export is recorded in kv ``render:export:<song id>``
    under its label (``version_label``): {"pdf", "query", "source_sha", "style", "printed_sha", "pdf_text",
    "font", "pdf_sha256", "pdf_size"}; another export with the same label replaces the file and the record,
    and one whose record says it was made from this very text and is still on disk is not rendered again
    (unless ``force``). A render pass remakes the exports whose sheet or style changed (``_remake_exports``).
    Raises RenderError: no sheet kept, a sheet that can't be read or made, a CJK font needed and missing, or
    chordpro failing.
    """
    sheet, text, found = _export_source(conn, cfg, song)
    folder = song_dir(cfg.library_dir, song)
    try:
        shapes = viewer_key(text, found.key if found is not None else None)
        capo = parse_sheet(text).capo
        label = version_label(v, shapes, capo)
        printed = _version_text(text, v, shapes, capo)
    except Exception as e:  # a sheet the viewer's code can't read
        log.warning("%s: cannot make the export %s", song.display, version_query(v), exc_info=True)
        raise RenderError(f"cannot make the export: {type(e).__name__}: {e}") from e
    pdf = folder / f"sheet ({safe_name(label)}).pdf"
    need = _font_need(printed)
    font = _cjk_font(cfg.cjk_font)[0] if need else None
    if need == "letters" and font is None:
        raise RenderError(f"{pdf.name} needs a CJK font: {FONT_HINT}")
    state = {
        "pdf": pdf.name,
        "query": export_query(v),
        "source_sha": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "style": _style(),
        "pdf_text": PDF_TEXT_VERSION,
        "printed_sha": hashlib.sha256(printed.encode("utf-8")).hexdigest(),
        "font": str(font) if font else None,
    }
    key = f"{EXPORT_KV}{song.id}"
    record = kv_get_json(conn, key)
    record = {k: e for k, e in record.items() if isinstance(e, Mapping)} if isinstance(record, Mapping) else {}
    if not force and _up_to_date(pdf, record.get(label), state):
        return pdf
    sha, size = _render_into(printed, pdf, work_dir=cfg.cache_dir, chordpro_bin=cfg.chordpro_bin, font_file=font,
                             runner=runner)
    # The label names the file, so another label never names the same one; a name that sorts the same
    # after safe_name is the same file, and its older record goes.
    record = {k: e for k, e in record.items() if e.get("pdf") != pdf.name}
    record[label] = {**state, "pdf_sha256": sha, "pdf_size": size}
    kv_set_json(conn, key, record)
    return pdf


def _remake_exports(conn: sqlite3.Connection, cfg: Config, overrides: Overrides, song: Song, *,
                    cjk_font: Path | None, runner: Runner, force: bool) -> None:
    """Render the song's exports again that its sheet, the style or the viewer's theory changed; the others
    are left (``render_version``). One that can't be made is logged, and the rest go on."""
    record = kv_get_json(conn, f"{EXPORT_KV}{song.id}")
    if not isinstance(record, Mapping):
        return
    for entry in list(record.values()):
        query = entry.get("query") if isinstance(entry, Mapping) else None
        if not isinstance(query, str):
            continue
        try:
            render_version(conn, cfg, overrides, song, version_from_query(query), runner=runner, force=force)
        except (RenderError, OSError) as e:
            log.warning("no export for %s (%s): %s", song.display, query, e)


def _render_sheet(
    conn: sqlite3.Connection,
    cfg: Config,
    song: Song,
    folder: Path,
    kept: KeptFile,
    sheet: _Sheet,
    state_key: str,
    version: Version,
    *,
    start: str | None,
    cjk_font: Path | None,
    runner: Runner,
    force: bool,
    key: tuple[str | None, str | None] = (None, None),
) -> _Done:
    """Write one sheet's .cho, render its PDF in ``version`` unless kv ``state_key`` says it is up to date,
    then write its viewer (``_write_viewer``), which needs no PDF: a failed render, or a sheet
    waiting for a CJK font, still gets one. ``key`` is the sheet's (``keys.sheet_keys``); ``start``, the
    song's own version as the viewer's address writes it, where the viewer starts, or None for none.

    The PDF, the viewer and the record of the .cho are made from the text written, never read
    back: a synced device may write there a moment later."""
    stem = Path(kept.name).stem
    cho = folder / f"{stem}.cho"
    text = _chordpro_text(sheet.markup, title=clean_title(song.title), artist=song.artist,
                          key=sheet.key, capo=sheet.capo, auto=sheet.auto)
    data = text.encode("utf-8")
    _write_if_changed(cho, data)
    _note_written(conn, song.id, cho.name, data)
    pdf = folder / f"{stem}.pdf"

    def viewer() -> bool:
        page = folder / f"{stem}.html"
        data = _write_viewer(song, text, page, pdf, key=key, transpose=version.t, start=start)
        if data is not None:
            _note_written(conn, song.id, page.name, data)
        return data is not None

    try:
        done = _render_sheet_pdf(conn, cfg, song, text, pdf, state_key, version, key=key[0],
                                 cjk_font=cjk_font, runner=runner, force=force)
    except RenderError:
        viewer()  # the PDF's error is the song's; the viewer's own, if any, is logged
        raise
    return done if viewer() else replace(done, viewer_failed=True)


def _render_sheet_pdf(
    conn: sqlite3.Connection,
    cfg: Config,
    song: Song,
    text: str,
    pdf: Path,
    state_key: str,
    version: Version,
    *,
    key: str | None,
    cjk_font: Path | None,
    runner: Runner,
    force: bool,
) -> _Done:
    """Render the ChordPro ``text`` to ``pdf`` in ``version`` unless kv ``state_key`` says it is up to date:
    chordpro prints the PDF's own text (``_sheet_text``), and the font is the one that text needs. A text that
    can't be made (a bug in the viewer's code it runs) is a RenderError, logged with its traceback:
    this PDF fails, and the pass goes on."""
    try:
        printed = _sheet_text(text, key=key, version=version)
    except Exception as e:  # a sheet the viewer's code can't read must never cost the other PDFs
        log.warning("%s: cannot make the text of %s", song.display, pdf.name, exc_info=True)
        raise RenderError(f"cannot make the text of {pdf.name}: {type(e).__name__}: {e}") from e
    need = _font_need(printed)
    font = cjk_font if need else None
    if need == "letters" and font is None:
        return _Done("no font", missing=_first_lost_letter(printed))
    state = {
        "source_sha": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "transpose": version.t,  # info.json's; the rest of the version is in the text printed
        "font": str(font) if font else None,
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
                             runner=runner)
    kv_set_json(conn, state_key, {**state, "pdf_sha256": sha, "pdf_size": size})
    write_info(conn, cfg.library_dir, song)  # its "render" entry: the PDF, the transposition
    return _Done("rendered")


def _sheet_text(text: str, *, key: str | None, version: Version) -> str:
    """The text chordpro prints of the sheet ``text`` in ``version``: the sheet as written (``Version()``) as it
    is (``_printed``), else in that version as its viewer shows it (``_version_text``). ``key`` is the sheet's
    (``keys.sheet_keys``)."""
    if version == Version():
        return _printed(text, key=key, capo=parse_sheet(text).capo, transpose=0)
    return _version_text(text, version, viewer_key(text, key), parse_sheet(text).capo)


def _version_text(text: str, v: Version, shapes: Key | None, capo: int | None) -> str:
    """The text chordpro prints of the sheet ``text`` in the version ``v``: each chord named and shaped as the
    viewer shows it there (``apply_version``), then the PDF's own text of that (``pdf_text``), with the key line
    of the shapes the version plays and its capo. ``shapes`` and ``capo`` are the sheet's, as its viewer reads
    them (``page.viewer_key``, its ``{capo}``)."""
    played, played_capo = played_key(v, shapes, capo)
    return _as_latin(pdf_text(apply_version(text, v, key=shapes, capo_sheet=capo), key=played, capo=played_capo))


def _printed(text: str, *, key: str | None, capo: int | None, transpose: int) -> str:
    """The text chordpro prints of the sheet ``text`` (``pdf_text``), with the key of its shapes as its
    viewer names it from ``key`` (the sheet's, ``keys.sheet_keys``), moved by ``transpose`` as a
    ``{transpose}`` before it moves the chords (a songbook's), and the look-alike letters capitals can make
    written in Latin (``_as_latin``)."""
    shapes = viewer_key(text, key)
    if shapes is not None:
        shapes = Key((shapes.tonic + transpose) % 12, shapes.mode)
    return _as_latin(pdf_text(text, key=shapes, capo=capo))


def _write_viewer(song: Song, text: str, page: Path, pdf: Path, *,
                  key: tuple[str | None, str | None], transpose: int, start: str | None) -> bytes | None:
    """Write the sheet's viewer (``viewer.build_viewer``) beside its PDF, linking the PDF when
    there is one, and return the page's bytes. It starts where the PDF is: at ``transpose``, in the song's
    own version (``start``) when it has one, and takes the sheet's key (``keys.sheet_keys``) when it has
    one. A viewer that hasn't changed isn't written again.

    The viewer is an extra: None, logged as "no viewer for", when it can't be built (a bug,
    with its traceback) or written (a link or a FIFO in its place), and the song's PDFs and
    its other sheet go on all the same.
    """
    linked = pdf.name if pdf.is_file() and not pdf.is_symlink() else None
    try:
        html = build_viewer(text, key=key[0], key_source=key[1], transpose=transpose, start=start, pdf=linked)
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
    entry = _written(conn, song_id).get(name)
    return None if entry is None else (entry["sha256"], entry["size"])


def _written(conn: sqlite3.Connection, song_id: int) -> dict[str, dict[str, Any]]:
    """kv ``render:files:<song id>``: {name: {"sha256", "size"}}, its odd entries left out."""
    record = kv_get_json(conn, f"{FILES_KEY}{song_id}")
    if not isinstance(record, Mapping):
        return {}
    return {
        name: entry for name, entry in record.items()
        if isinstance(entry, Mapping) and isinstance(entry.get("sha256"), str)
        and isinstance(entry.get("size"), int)
    }


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
    path = (library_dir / kept.path).with_name("sheet.json")
    try:
        doc = read_json(path)
    except (OSError, ValueError) as e:  # ValueError: not UTF-8, not JSON, or nested too deep
        raise RenderError(f"cannot read {path}: {e}") from e
    content = doc.get("content") if isinstance(doc, Mapping) else None
    if not isinstance(content, str) or not content.strip():
        raise RenderError(f"{path} holds no sheet content")
    raw = get_version(conn, kept.version_id).raw
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
    work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="render-", dir=work_dir) as tmp:
        cho, out = Path(tmp) / f"{pdf.stem}.cho", Path(tmp) / pdf.name
        cho.write_bytes(text.encode("utf-8"))
        render_pdf(cho, out, chordpro_bin=chordpro_bin, font_file=font_file, runner=runner)
        data = out.read_bytes()
        return write_atomic(pdf, data), len(data)


_INVISIBLE = frozenset({"Cc", "Cf"})  # controls, zero-width spaces, byte-order marks


def _font_need(text: str) -> Literal["letters", "symbols"] | None:
    """What ChordPro's built-in fonts would lose of ``text``.

    Invisible characters don't count, as there is nothing to lose. Lost letters
    (Chinese lyrics, say) leave a sheet unsingable; a lost symbol, such as a
    music note, only blemishes it.
    """
    lost = {unicodedata.category(ch) for ch in set(text) if needs_font_file(ch)} - _INVISIBLE
    if any(category.startswith("L") for category in lost):
        return "letters"
    return "symbols" if lost else None


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
