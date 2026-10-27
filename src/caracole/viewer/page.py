"""sheet.html: one sheet as a page for a phone, written beside its PDF.

The page is one self-contained file. It opens from the synced library folder with
no server: it loads nothing (a Content-Security-Policy with the hashes of its five
scripts, strum.js, overlay.js, instruments.js, winds.js and viewer.js, and its stylesheet makes the browser enforce
that)
and links only to the PDF beside it and to the library's index.html two folders up: its ‹ Library, and the
artist's name under the title, to the library page on their songs (``artist_line``).
A server may serve it too, only while it is the page caracole wrote, with
``viewer_csp(page)`` as its header.

The sheet itself is static HTML, so it reads without the script, and prints. What a tab
says before its first section or riff (its tabber's notes, a link, a chord legend) is
folded after two lines, in a ``<details>`` that opens without the script too. Every
text from the sheet is escaped. The script (viewer.js) relabels the chords from the
song data in a ``<script type="application/json">`` block, whose every ``<`` is
written ``\\u003c``:

- ``chords``: each chord of the sheet (by its ``data-c`` index) as
  ``[root, suffix, bass, fingerings, nearest, slash fingerings]`` (pitch classes,
  the suffix as written, ``voicings.voicing_keys``), or null when caracole can't
  read it: it then stays as written;
- ``key``: ``{"tonic", "mode", "from"}`` (where the key came from, in words), or
  null for a sheet without chords; ``transpose``: where the viewer starts (the
  song's ``[transpose]``, as the PDF, or its own version's); ``start``: the song's
  own version (overrides.toml's ``[version]``, "Make this my version"), as the
  viewer's address writes it (viewer/version.py), or null for none: the script starts
  there when its address names no version (``t``, ``mode``, ``capo``, ``alt``, ``at``);
  ``capoSheet``: the sheet's own capo;
- for each mode of the key's tonic: ``mapped`` chords (``theory.map_chord``),
  their ``alts`` (``theory.alternatives``), ``names`` (each pitch class's name in
  that mode on each tonic, ``theory.spelling``), ``keyNames``, and ``capo`` hints
  for each transposition (``theory.capo_hints``: the fret the capo goes on, 0 for
  none, which may be below the sheet's own, and the shapes' key);
- ``voicings``: the fingerings of every chord the page can show, on every root: the guitar's by
  ``voicings.voicing_keys``, and each instrument's under its prefix (instruments.py ``page_voicings``:
  "ukulele:m7", "piano:m7|");
- ``instruments``: the instruments the viewer offers, in its menu's order (instruments.py ``entries``: each one's
  ``id``, ``name``, ``kind``, ``tuning``, whether it takes a ``capo``, where its ``shapes`` are, its ``offset``, its
  ``easy`` keys' table, its ``voice``, ``sounds``, ``about``, its ``tab`` (its name on the overlay's tab, in short),
  and a ukulele's ``near``); ``easy``, for a sheet with a
  key, each table's easy keys in every mode (``instruments.easy_keys``: ``[tonic, name]``), which the settings' Easy
  keys row offers on an instrument that has one;
- the harmonica's (harp.py ``tables``: ``harpKeys``, ``harps``, the harps for the song in each mode, ``harpForms``,
  ``harpChords``, ``harpAlts``, what each chord plays on each harp; and the overlay's Harmonica tab's, ``harpRing``,
  ``harpHoles``, ``harpScales``, ``harpOutside``, ``harpNotes``, ``harpAltNotes``) for a sheet with a key, with
  ``harpTabs``, the harps the song's harmonica tabs play on (each one's ``harp``, as harpfit.py chose it), as semitones
  above the key the sheet sounds in (its key, the capo added), and the flute's and the
  recorder's (winds.py ``tables``: ``windForms``, ``windChords``, ``windAlts``, each chord's notes), for winds.js;
  ``winds``, the same on every page: the fingerings (winds.py ``fingering_data``) and each harp's notes (``harps``,
  harp.py ``layouts``);
- ``shapes``: the fingerings the sheet gives its chords (its chord legend, its ``{define}``),
  first, before chords-db's (``voicings.sheet_shapes``: ``{"mine": how many are the sheet's,
  "list": positions}``), by the chord as shown: the script shows them for that very chord
  alone, not once it is transposed into another;
- what each chord is in the key, by mode (``numerals``, ``families``, ``relations``, ``explains``,
  ``places``, ``altNumerals``), each chord's notes (``tones``) and its scale for a solo
  (``solo``, ``altSolo``, ``scaleWords``, ``scales``), the key's scale (``keyScale``, ``pentatonic``) and
  each section's progression (``progressions``): harmony_tables.py says how;
- ``library``: the library's index.html, relative to the page;
- ``versions``: UG's chords versions of the song, for the switcher under the key line and the list it
  opens (``_VERSIONS``, ``_VERSION_LIST``), or null for none: ``sheet_versions.as_data``'s ``{"total",
  "list"}``, each entry's ``this`` saying whether it is this page's, ``sheet``, the provider of the
  sheet the title opens ("ug", "lacuerda", "auto"), and ``pinned``, whether a ``[pin]`` of yours chooses it:
  render.py's ``_versions_data``;
- ``guitar``: the names of the song's Guitar Pro files beside the page that caracole serve shows in the browser
  (render.py, ``inbox.guitar_files``), for the settings' Guitar Pro row (``_GUITAR_ROW``): served, each a link to
  caracole serve's Guitar Pro page; or none, and no row. ``guitarDownload``, beside it: the name each saves under,
  from a file (``download_names.download_name``, the title clean as caracole serve names it: "Eagles - Hotel California
  (2).gp5"), its link's ``download``;
- ``harmonicaTabs``: the song's harmonica tabs beside the page (render.py, ``inbox.harmonica_files``: kept from
  harptabs.com), each ``{"name": "harmonica-1.txt", "href": "harmonica-1.txt", "page": "harmonica-1.html"}`` (its
  text, and its page beside it: harptab_page.py), with the ``key`` its page's Key chip named ("C": the song's on
  some tabs, the harp's on others), if any, for the harmonica's panel; a song with none has none;
- ``pinyin``, for a sheet whose song holds Chinese: each line of its sections as the page draws it (``#sheet
  section.sec > p.l``, in order: ``_drawn_lines``), the reading of each of its characters (pinyin.py: "" for a
  letter, a space or punctuation), or null for a line with none, for the settings' Pinyin row, which the script
  shows for such a sheet alone; a sheet with none has none;
- ``hanzi``, beside it: every text the sheet writes in its words (``_written_texts``: each line's words whole, the
  notes' before the song too, each section's label, each tab, each line of the notes' peek) in Simplified
  characters (``simplified``) and in Traditional ones (``traditional``), by the text, where that isn't the text as
  written (hanzi.py: as long as it, a character for a character), for the settings' Chinese characters, which the
  script shows where it shows Pinyin's row.
"""

from __future__ import annotations

import hashlib
import re
import sys
import unicodedata
from functools import lru_cache
from html import escape, unescape
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from caracole.download_names import download_name
from caracole.inline import json_block, sha256_source
from caracole.normalize import clean_title, has_han
from caracole.page_icon import LINK as PAGE_ICON
from caracole.viewer import hanzi, harmony_tables, harp, instruments, pinyin, winds
from caracole.viewer.sheet import (
    Blank,
    ChordRow,
    Line,
    Lyrics,
    Section,
    Sheet,
    Tab,
    Text,
    is_legend,
    parse_sheet,
    preamble_section,
    written,
)
from caracole.viewer.theory import (
    DISPLAY,
    MODES,
    Chord,
    Key,
    alternatives,
    capo_hints,
    estimate_key,
    key_name,
    map_chord,
    named_key,
    parse_chord,
    parse_key,
    shapes_key,
    sounding,
    spelling,
)
from caracole.viewer.voicings import (
    LICENSE_FILE,
    Position,
    chord_legend,
    page_voicings,
    parse_define,
    sheet_shapes,
    voicing_keys,
)

HERE = Path(__file__).parent
# Library/<artist>/<title>/sheet.html and Library/_songbooks/<name>/songbook.html -> Library/index.html
LIBRARY_PAGE = "../../index.html"
CREDIT_URL = "https://github.com/tombatossals/chords-db"

# Where a key came from (``keys.SongKey.source``), in words for the page: keys.SOURCES, copied, since
# importing keys.py would bring db.py, songs.py and the rest into BUILD_FILES (test_viewer.py checks
# that the two agree).
_SOURCES = {"tab": "from the tab", "chords": "estimated from the chords", "audio": "from the audio"}
# Those whose key is the key of the chords as the sheet writes them, the shapes played (keys.py): estimated from
# them, or heard in the chords an auto sheet writes. Never one that may name the sound, as a tab's own word may.
_OF_THE_SHAPES = frozenset({"chords", "audio"})


# What a page is made from besides its song: this module, those it imports and the files they read.
# A module the viewer comes to import goes here too (test_viewer_book.py checks).
BUILD_FILES = (
    *(HERE / name for name in ("page.py", "sheet.py", "theory.py", "harmony.py", "harmony_tables.py",
                               "voicings.py", "voicings.json", "voicings-ukulele.json", "instruments.py",
                               "version.py", "pinyin.py", "hanzi.py", "viewer.js", "viewer.css",
                               "LICENSE-chords-db")),
    HERE / "strum.js",  # hearing a chord: the synthesis, its own script before viewer.js
    HERE / "instruments.js",  # a chord's box and keyboard, and the instruments a script registers, before viewer.js
    HERE / "harp.py", HERE / "winds.py", HERE / "winds.js",  # the harmonica, the flute and the recorder
    HERE / "overlay.js",  # the rail on a wide screen, Guitar and Harmonica, on a sheet and a harmonica tab's page
    # A harmonica tab's page, harmonica-N.html: the tab read, the harp it plays on, the page, its script and style
    *(HERE / name for name in ("harptab.py", "harpfit.py", "harptab_page.py", "harptab.js", "harptab.css")),
    HERE.parent / "inline.py",  # sha256_source, json_block
    HERE.parent / "download_names.py",  # download_name, a Guitar Pro link's download attribute
    HERE.parent / "normalize.py",  # has_han, clean_title
    HERE.parent / "page_icon.py",  # the icon in the page's head
    HERE.parent / "autochords" / "merge.py",  # AUTO_MARKER, which sheet.py reads
)


@lru_cache(maxsize=1)
def build_version() -> str:
    """What this caracole's viewer is, as a SHA-256 of the Python running it (``sys.version``:
    unicodedata, html.escape and json.dumps go with it) and of every file in ``BUILD_FILES``, in
    their order, and of pypinyin's version, whose dictionaries read a Chinese sheet's pinyin, and OpenCC's, whose
    dictionaries write it in either script. An upgrade that could change a page changes it: a page made with
    another one is made again (songbook.html, through ``book.assets_version``)."""
    digest = hashlib.sha256(sys.version.encode("utf-8"))
    for path in BUILD_FILES:
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    digest.update(_pypinyin_version().encode("utf-8"))
    digest.update(b"\0" + _opencc_version().encode("utf-8"))
    return digest.hexdigest()


def _pypinyin_version() -> str:
    """pypinyin's version, read from its metadata without importing it (pinyin.py imports it to read)."""
    return _installed("pypinyin")


def _opencc_version() -> str:
    """OpenCC's version, read from its metadata without importing it (hanzi.py imports it to convert)."""
    return _installed("opencc")


def _installed(distribution: str) -> str:
    """The version of ``distribution`` installed, or "" for none."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(distribution)
    except PackageNotFoundError:
        return ""


@lru_cache(maxsize=1)
def _assets() -> tuple[str, str]:
    return (HERE / "viewer.css").read_text(encoding="utf-8"), (HERE / "viewer.js").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _sound() -> str:
    """strum.js: a chord's shape strummed in Web Audio (``window.caracoleSound``), inlined before viewer.js,
    which calls it, in a sheet.html and a songbook.html alike."""
    return (HERE / "strum.js").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _winds() -> str:
    """winds.js: the harmonica, the flute and the recorder, registered with instruments.js (their header line,
    their chords' pictures, their settings row and their notes), inlined after instruments.js and before viewer.js,
    in a sheet.html and a songbook.html alike."""
    return (HERE / "winds.js").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _overlay() -> str:
    """overlay.js: the rail of a wide screen, its Guitar and Harmonica tabs (``window.caracoleOverlay``), inlined
    after strum.js and before the rest, before viewer.js, which draws it, in a sheet.html and a songbook.html alike,
    and before harptab.js in a harmonica tab's page (harptab_page.py)."""
    return (HERE / "overlay.js").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _instruments() -> str:
    """instruments.js: a chord's box on any fretted instrument and a piano's keyboard, and the instruments another
    script registers (``window.caracoleInstruments``), inlined after strum.js and before viewer.js, which calls it,
    in a sheet.html and a songbook.html alike."""
    return (HERE / "instruments.js").read_text(encoding="utf-8")


def build_viewer(
    cho: str,
    *,
    key: str | None = None,
    key_source: str | None = None,
    transpose: int = 0,
    start: str | None = None,
    pdf: str | None = None,
    export: bool = True,
    versions: dict[str, Any] | None = None,
    guitar: tuple[str, ...] | list[str] = (),
    harmonica: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] = (),
) -> str:
    """The page for a ChordPro sheet (as caracole writes it).

    The key comes from ``key`` (the song's, ``keys.sheet_keys``, with ``key_source``, one
    of ``keys.SOURCES``), else from the sheet's own ``{key}``, else it is estimated from
    the chords. ``transpose`` is where the viewer starts, and ``start`` the song's own version
    (``t=2&mode=dorian&capo=0``), in which it starts when its address names none; ``pdf`` names
    the PDF beside the page, linked when given. Without ``export``, its settings offer no Export PDF of
    this version (an auto sheet kept beside a human one, or a version's page, whose exports are the
    sheet's: render.py ``export_viewer``). ``versions``, the song's UG chords versions (render.py ``_versions_data``:
    ``sheet_versions.as_data`` with ``sheet``, the provider of the one, and ``this`` on each entry,
    true on the page's own), goes in the page's data as ``versions``; without it, the data has none. ``guitar``, the
    names of the song's Guitar Pro files beside the page that caracole serve shows in the browser (render.py), goes
    in its data as ``guitar``, and its settings get a Guitar Pro row (``_GUITAR_ROW``); without any, neither.
    ``harmonica``, the song's harmonica tabs beside the page (render.py, ``inbox.harmonica_files``: ``{"name",
    "href", "page"}`` and the ``key`` its page named, if any), goes in its data as ``harmonicaTabs``; without any,
    the data has none. A tab's ``harp``, the pitch class of the harp it plays on (render.py, harpfit.py), is the
    data's ``harpTabs`` instead, by the sheet's key.
    """
    sheet, song_key, origin, data = _read_song(cho, key, key_source, transpose)
    data["start"] = start
    if versions is not None:
        data["versions"] = versions
    if harmonica:
        data["harmonicaTabs"] = [{k: v for k, v in tab.items() if k != "harp"} for tab in harmonica]
        harps = [tab["harp"] for tab in harmonica if isinstance(tab.get("harp"), int)]
        if song_key is not None and harps:
            sounds = song_key.tonic + (sheet.capo or 0)  # a harmonica takes no capo: the key the song sounds in
            data["harpTabs"] = list(dict.fromkeys((h - sounds) % 12 for h in harps))
    if guitar:
        data["guitar"] = list(guitar)
        clean = clean_title(sheet.title or "")
        data["guitarDownload"] = [download_name(sheet.artist or "", clean, name) for name in guitar]
    style, script = _assets()
    title = sheet.title or "Untitled"
    return _page(
        f"{title} · {sheet.artist}" if sheet.artist else title,
        _body(sheet, title, song_key, origin, pdf, export=export, guitar=bool(guitar)) + json_block("song", data),
        styles=(style,),
        scripts=(_sound(), _overlay(), _instruments(), _winds(), script),
    )


def viewer_csp(page: bytes) -> str:
    """The Content-Security-Policy header a server sends with ``page``, a viewer caracole wrote:
    a sheet.html, or a songbook.html (``book.songbook_csp`` is this function).

    It is the page's own policy, as its ``<meta>`` tag holds it (its scripts and stylesheets,
    by their hashes, and nothing else to load, no form to send, no base to change), with a
    sandbox, which a ``<meta>`` policy can't set: the page then runs in an origin of its own,
    with no cookie and no way to ask the server for anything. Its scripts still run; they have
    no storage there, and keep the transposition, the mode, the capo, the text size and the
    scroll speed in the address (``#t=2&mode=aeolian&fs=20&speed=8``; a songbook's song too,
    ``#song-3``) alone, as they do everywhere besides their storage. It may download what a
    link it follows answers as an attachment (``allow-downloads``): Export PDF's link is the
    download itself (web/export_routes.py), and the page stays where it is.

    The policy is the page's, not this caracole's: a page written before an upgrade carries
    the hashes of the scripts and styles it was written with, and keeps them until the next
    render writes it again. A page whose policy can't be read, or would not fit in a header,
    gets a sandbox that runs and loads nothing (``_NOTHING``).

    Serve only a page still as caracole wrote it (``render.written_file``, ``library.holds``;
    ``songbook.pages_written``): anyone with a synced device can put a page of their own in the
    library, and its policy too.
    """
    found = _META_POLICY.search(page)
    try:
        policy = unescape(found.group(1).decode("utf-8")) if found else ""
    except UnicodeDecodeError:
        policy = ""
    return "sandbox allow-scripts allow-downloads; " + policy if _HEADER_TEXT.fullmatch(policy) else _NOTHING


# The page's own policy, as ``_page`` writes it; what a header may hold (no line break);
# and the header for a page whose policy can't be read: a sandbox that runs and loads nothing.
_META_POLICY = re.compile(rb'<meta http-equiv="Content-Security-Policy" content="([^"<>]*)">')
_HEADER_TEXT = re.compile(r"[ -~]+")
_NOTHING = "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'"


def _page(title: str, body: str, *, styles: tuple[str, ...], scripts: tuple[str, ...]) -> str:
    """A whole page, sheet.html or songbook.html: its head (``title``, the icon, the stylesheets, and the
    policy that allows exactly them and the scripts, an image from a data: URI, the icon, and nothing to
    load, no form to send, no base to change), ``body``, then the scripts, which run once the page is
    read, in their order."""
    policy = (
        f"default-src 'none'; script-src {' '.join(map(sha256_source, scripts))}; "
        f"style-src {' '.join(map(sha256_source, styles))}; img-src data:; base-uri 'none'; form-action 'none'"
    )
    # One join, so the page is copied once: its script and stylesheet alone are some 66 kB.
    return "".join((
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="color-scheme" content="light dark">\n<meta name="referrer" content="same-origin">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{policy}">\n',
        PAGE_ICON,
        f"<title>{escape(title)}</title>\n",
        *(f"<style>{style}</style>\n" for style in styles),
        "</head>\n<body>\n",
        body,
        *(f"<script>{script}</script>\n" for script in scripts),
        "</body>\n</html>\n",
    ))


# --- the key and the data ------------------------------------------------------------------------


def _read_song(cho: str, key: str | None, key_source: str | None,
               transpose: int) -> tuple[Sheet, Key | None, str | None, dict[str, Any]]:
    """A ChordPro sheet as its page shows it: the sheet read, the key of its shapes and where that came
    from in words (``_song_key``), and the data its block gives the script (``_data``)."""
    sheet = parse_sheet(cho)
    chords = [parse_chord(name, strict=False) for name in sheet.chords]
    song_key, origin = _song_key(sheet, chords, key, key_source)
    return sheet, song_key, origin, _data(sheet, chords, song_key, origin, transpose)


def viewer_key(cho: str, key: str | None = None, key_source: str | None = None) -> Key | None:
    """The key of a ChordPro sheet's shapes as its page names it (``build_viewer`` given ``key`` and
    ``key_source``), for what says the same beside the page: the PDF's key line (``key_line_text``)."""
    sheet = parse_sheet(cho)
    return _song_key(sheet, [parse_chord(name, strict=False) for name in sheet.chords], key, key_source)[0]


def _song_key(sheet: Sheet, chords: list[Chord | None], key: str | None,
              source: str | None) -> tuple[Key | None, str | None]:
    """The key of the shapes the sheet's chords are, and where it came from in words. A key named
    for a sheet with a capo may be the one the song sounds in (``theory.shapes_key``); one the chords
    gave (``_OF_THE_SHAPES``) is their shapes', whatever the capo. A letter alone, the sheet's ``{key}`` or
    one from no source keys.py names, is its parallel minor where the chords say so (``theory.named_key``);
    keys.py has read a tab's so already (``keys.sheet_key``), and its "A" is A major, as "A major" is."""
    played = [chords[i] for i in _played(sheet) if chords[i] is not None]
    capo = sheet.capo or 0
    if (found := parse_key(key)) is not None:
        if source in _OF_THE_SHAPES:
            return found, _origin(source)
        if source not in _SOURCES:
            found = named_key(key, capo, played) or found
        return shapes_key(found, capo, played), _origin(source)
    if (found := named_key(sheet.key, capo, played)) is not None:
        return shapes_key(found, capo, played), "from the sheet"
    found = estimate_key(played)
    return found, "estimated from the chords" if found else None


def _origin(source: str | None) -> str:
    if source is None:
        return "from info.json"
    words = " ".join(str(source).split())[:40]
    return _SOURCES.get(words.lower(), f"from {words}")


def _played(sheet: Sheet) -> list[int]:
    """The sheet's chords in the order they are played, repeats and all."""
    return [c for section in sheet.sections for c in _chords_in(section)]


def _data(sheet: Sheet, chords: list[Chord | None], key: Key | None, origin: str | None,
          transpose: int) -> dict[str, Any]:
    needed: set[str] = set()
    kinds: dict[str, Chord] = {}  # each kind of chord the page shows, by its piano key: the piano's positions

    def rep(chord: Chord | None) -> list[Any] | None:
        if chord is None:
            return None
        kinds.setdefault(instruments.piano_key(chord), chord)
        fingering, nearest, slash = voicing_keys(chord)
        needed.add(fingering)
        if slash:
            needed.add(slash)
        return [chord.root, chord.suffix, chord.bass, fingering, int(nearest), slash]

    data: dict[str, Any] = {
        "chords": [rep(c) for c in chords],
        "key": None if key is None else {"tonic": key.tonic, "mode": key.mode, "from": origin},
        "transpose": transpose,
        "capoSheet": sheet.capo,
        "modes": [],
        "mapped": {},
        "alts": {},
        "names": {"": " ".join(spelling(None))},
        "keyNames": {},
        "capo": {},
        "qualities": DISPLAY,
    }
    mapped_by_mode: dict[str, list[Chord | None]] = {}
    alts_by_mode: dict[str, list[list[Chord]]] = {}
    if key is not None:
        data["modes"] = list(MODES)
        data["names"] = {}
        for mode in MODES:
            in_mode = Key(key.tonic, mode)
            mapped = mapped_by_mode[mode] = [None if c is None else map_chord(c, key, mode) for c in chords]
            alts_by_mode[mode] = [[] if c is None else alternatives(c, in_mode) for c in mapped]
            data["mapped"][mode] = [rep(c) for c in mapped]
            data["alts"][mode] = [[rep(a) for a in options] for options in alts_by_mode[mode]]
            data["names"][mode] = [" ".join(spelling(Key(t, mode))) for t in range(12)]
            data["keyNames"][mode] = [key_name(Key(t, mode)) for t in range(12)]
            data["capo"][mode] = [
                [[fret, key_name(shapes)]
                 for fret, shapes in capo_hints(Key((key.tonic + t) % 12, mode), capo=sheet.capo or 0)]
                for t in range(12)
            ]
    data["voicings"] = page_voicings(needed) | instruments.page_voicings(needed, list(kinds.values()))
    data["instruments"] = instruments.entries(needed)
    if key is not None:
        data["easy"] = {table: instruments.easy_keys(table) for table in instruments.EASY}
    data["shapes"] = shapes_of(sheet)
    data.update(harmony_tables.tables(chords, key, _places(sheet), mapped_by_mode, alts_by_mode))
    data.update(harp.tables(key, mapped_by_mode, alts_by_mode))
    data.update(winds.tables(chords, key, mapped_by_mode, alts_by_mode))
    data["winds"] = {**winds.fingering_data(), "harps": harp.layouts()}
    data["library"] = LIBRARY_PAGE
    if (readings := pinyin.readings(_drawn_lines(sheet))) is not None:
        data["pinyin"] = readings
        data["hanzi"] = hanzi.scripts(_written_texts(sheet))
    return data


def _drawn_lines(sheet: Sheet) -> list[str]:
    """The text of each line of the song's sections as the page draws one (a ``p.l``: a sung line's words, none
    for a line of chords alone, a line of text's), in the page's order: the lines the data's ``pinyin`` reads.
    The notes before the song are none of them."""
    return [_words_of(line) for section in _shown(sheet)[1] for line in section.lines
            if isinstance(line, (Lyrics, ChordRow, Text))]


def _words_of(line: Line) -> str:
    """A line's words as its page writes them (a ``p.l``'s, its chords left out; a tab whole), "" for a line of
    chords alone or a blank one."""
    if isinstance(line, Lyrics):
        return "".join(text for _, text in line.parts)
    if isinstance(line, Text):
        return line.text
    if isinstance(line, Tab):
        return "\n".join(line.lines)
    return ""


def _written_texts(sheet: Sheet) -> list[str]:
    """Every text the sheet's page writes in its words, which the data's ``hanzi`` gives in either script: the
    notes before the song (each line of their peek, and each line), then each section's label and each line's
    words, a tab's whole."""
    pre, sections = _shown(sheet)
    out = [*_peek(pre, sheet.chords), *(_words_of(line) for line in pre.lines)] if pre else []
    for section in sections:
        out += [section.label] if section.label else []
        out += [_words_of(line) for line in section.lines]
    return out


def _peek(section: Section, names: list[str]) -> list[str]:
    """The lines the folded notes before the song show in their summary: their first two, chords and all, for
    notes of more than two lines; none for fewer, which aren't folded."""
    lines = [line for line in section.lines if not isinstance(line, Blank)]
    return [written(line, names).strip() for line in lines[:2]] if len(lines) > 2 else []


def _shown(sheet: Sheet) -> tuple[Section | None, list[Section]]:
    """The sheet as its page shows it: the notes before the song (``preamble_section``), or None, and the
    song's sections, each a ``section.sec`` on the page (what follows the notes in their section, a riff
    and on, stays a section of the song)."""
    sections = list(sheet.sections)
    pre = preamble_section(sheet)
    if pre is not None:
        rest = sections[0].lines[len(pre.lines):]
        while rest and isinstance(rest[0], Blank):
            rest = rest[1:]
        sections[:1] = [Section(None, lines=rest)] if rest else []
    return pre, sections


def _chords_in(section: Section) -> list[int]:
    order: list[int] = []
    for line in section.lines:
        if isinstance(line, Lyrics):
            order += [c for c, _ in line.parts if isinstance(c, int)]
        elif isinstance(line, ChordRow):
            order += [c for c in line.items if isinstance(c, int)]
    return order


def _places(sheet: Sheet) -> list[tuple[int, int]]:
    """Each chord's place on the page, in the page's order (the script's ``#sheet .c``): (its index, its
    section among the song's ``section.sec``, -1 in the notes before the song)."""
    pre, sections = _shown(sheet)
    places = [(c, -1) for c in _chords_in(pre)] if pre else []
    for n, section in enumerate(sections):
        places += [(c, n) for c in _chords_in(section)]
    return places


def shapes_of(sheet: Sheet) -> dict[str, dict[str, Any]]:
    """The shapes the sheet's page shows for its chords (its data's ``shapes``: ``voicings.sheet_shapes``,
    by ``voicings.shape_key``), for what shows the same beside the page: the PDF's chord diagrams."""
    return sheet_shapes(_given_shapes(sheet))


def _given_shapes(sheet: Sheet) -> list[tuple[Chord, Position]]:
    """The fingerings the sheet gives its chords, in order: its ``{define}``s, then its chord
    legend's lines, wherever they are (a legend's line in a tab too)."""
    given = [found for value in sheet.defines if (found := parse_define(value))]
    for section in sheet.sections:
        for line in section.lines:
            if isinstance(line, Tab):
                given += [entry for text in line.lines for entry in chord_legend(text)]
            elif not isinstance(line, Blank):
                given += chord_legend(written(line, sheet.chords))
    return given


# --- the page ------------------------------------------------------------------------------------


def _facts(key: Key | None, origin: str | None, capo: int) -> str:
    """The key line under the title, as HTML, as viewer.js writes it for the sheet as written.

    With a capo it says the key of the shapes played, the capo and the key the song sounds in,
    as Cifra Club's key line does ("Em shapes · capo 2 · sounds F#m"): "Key Em" alone would read
    as the song's key. Without one, the key ("Key Em"). Each says where the key came from.
    """
    source = escape(origin or "")
    if key is None:
        return f"Capo <b>{capo}</b>" if capo else ""
    if not capo:
        return f"Key <b>{escape(key_name(key))}</b>" + (f' <span class="from">{source}</span>' if source else "")
    return (
        f"<b>{escape(key_name(key))}</b> shapes · capo <b>{capo}</b> · sounds <b>{escape(key_name(sounding(key, capo)))}</b>"
        + (f' · <span class="from">key {source}</span>' if source else "")
    )


def key_line_text(key: Key | None, capo: int | None) -> str:
    """The key line in words, as ``_facts`` writes it without its markup and where the key came from:
    "Em shapes · capo 2 · sounds F#m", "Key Em", "Capo 2" for a sheet with no key, else ""."""
    capo = capo or 0
    if key is None:
        return f"Capo {capo}" if capo else ""
    if not capo:
        return f"Key {key_name(key)}"
    return f"{key_name(key)} shapes · capo {capo} · sounds {key_name(sounding(key, capo))}"


def _body(sheet: Sheet, title: str, key: Key | None, origin: str | None, pdf: str | None, *,
          export: bool = True, guitar: bool = False) -> str:
    pdf_link = f'<a class="pdf" href="{escape(quote(pdf))}">PDF</a>\n' if pdf else ""
    return (
        '<div class="page">\n<header class="head">\n'
        f'<a class="back" href="{LIBRARY_PAGE}">‹ Library</a>\n'
        f"<h1>{escape(title)}</h1>\n"
        + artist_line(sheet.artist)
        + f'<p class="facts" id="facts">{_facts(key, origin, sheet.capo or 0)}</p>\n'
        + _VERSIONS
        + "</header>\n"
        + _song_html(sheet)
        + _footer(pdf_link)
        + "</div>\n"
        + _with_guitar(_SHEET_CONTROLS if export else _CONTROLS, guitar)
        + _VERSION_LIST
    )


def artist_line(artist: str) -> str:
    """The artist's line under a song's title, on sheet.html, a kept version's page and a songbook's song alike, as
    HTML: their name, a link to the library page on their songs (``LIBRARY_PAGE``, with ``#by=`` and the name, every
    character of it but a letter, a digit and -._~ percent-encoded), as pressing their name there does: served by
    caracole serve, the search for them, which asks no site; from a file and in the Android app's copy, their songs
    alone (library.js reads ``by``). A plain link, which a sandbox, a file and the app follow with no script; the name
    in a span of its own, which the focus ring goes round (viewer.css). None for a sheet that names no artist."""
    if not artist:
        return ""
    href = f"{LIBRARY_PAGE}#by={quote(artist, safe='')}"
    return (f'<p class="artist"><a href="{escape(href)}" title="{escape(f"Songs by {artist}")}">'
            f"<span>{escape(artist)}</span></a></p>\n")


def _song_html(sheet: Sheet, suffix: str = "", named: str = "") -> str:
    """What follows a song's header, on sheet.html and in a songbook alike: an auto sheet's notice, the
    rail of necks (a wide screen's: a neck per chord) and the strip of chord shapes the script fills in,
    and the sheet, marked Chinese when its words or names are (``named``: what a songbook calls the
    song). ``suffix`` tells a songbook's songs apart ("-3")."""
    lang = ' lang="zh"' if has_han(named + sheet.title + "".join(_texts(sheet))) else ""
    return (
        (_NOTICE if sheet.auto else "")
        + f'<aside class="necks" id="necks{suffix}" hidden aria-label="Chord necks"></aside>\n'
        + f'<div class="strip" id="strip{suffix}" hidden></div>\n'
        + f'<article class="sheet" id="sheet{suffix}"{lang}>\n{_sheet_html(sheet)}</article>\n'
    )


_NOTICE = '<p class="notice">Auto-generated, unverified: caracole heard these chords in the recording.</p>\n'


def _footer(links: str) -> str:
    """The foot of a page: ``links`` to the files beside it, chords-db's credit and licence (MIT: it
    goes with every copy of its fingerings), and a word on keeping the page private."""
    return (
        '<footer class="foot">\n'
        + links
        + f'<p>Chord shapes from <a href="{CREDIT_URL}">chords-db</a>, © 2016 David Rubert, MIT licence.</p>\n'
        + f'<details class="licence"><summary>The chords-db licence</summary><pre>{escape(_credit_notice())}</pre></details>\n'
        + "<p>Keep this page private: the lyrics and chords are other people's work.</p>\n"
        + "</footer>\n"
    )


@lru_cache(maxsize=1)
def _credit_notice() -> str:
    """chords-db's copyright and permission notice (MIT): it goes with every copy of its
    fingerings, and each page holds some."""
    text = LICENSE_FILE.read_text(encoding="utf-8")
    return text[text.index("MIT License"):].strip()


def _texts(sheet: Sheet) -> list[str]:
    out = []
    for section in sheet.sections:
        for line in section.lines:
            if isinstance(line, Lyrics):
                out += [text for _, text in line.parts]
            elif isinstance(line, Text):
                out.append(line.text)
    return out


def _sheet_html(sheet: Sheet) -> str:
    pre, sections = _shown(sheet)
    return ((_preamble_html(pre, sheet.chords) if pre else "")
            + "".join(_section_html(s, sheet.chords) for s in sections))


def _preamble_html(section: Section, names: list[str]) -> str:
    """The preamble in small, muted type, folded after its first two lines: those two as plain text
    in the summary of a ``<details>``, to read at a glance, and every line inside; open, the summary
    names it, beside Less. A preamble of two lines has nothing more to show, and isn't folded."""
    body = "\n".join(_line_html(line, names) for line in section.lines)
    if not (lines := _peek(section, names)):
        return f'<div class="pre">\n{body}\n</div>\n'
    peek = "<br>".join(escape(line) for line in lines)
    return (
        f'<details class="pre">\n<summary><span class="peek">{peek}</span><span class="named">Notes</span>'
        '<span class="more">More</span><span class="less">Less</span></summary>\n'
        f'<div class="pre-body">\n{body}\n</div>\n</details>\n'
    )


def _section_html(section: Section, names: list[str]) -> str:
    cls = "sec chorus" if section.chorus else "sec"
    out = [f'<section class="{cls}">']
    if section.label:
        out.append(f'<h2 class="lbl">{escape(section.label)}</h2>')
    out += [_line_html(line, names) for line in section.lines]
    out.append("</section>\n")
    return "\n".join(out)


def _chord_html(index: int, names: list[str]) -> str:
    return f'<b class="c" data-c="{index}" tabindex="0" role="button">{escape(names[index])}</b>'


def _mark_html(mark: str) -> str:
    return f'<i class="m">{escape(mark)}</i>'


def _line_html(line, names: list[str]) -> str:
    """A line of the sheet as HTML: a chord legend's line (``sheet.is_legend``) is a ``legend``, whose chords
    viewer.js leaves as written, whatever the version."""
    legend = " legend" if is_legend(line, names) else ""
    if isinstance(line, Lyrics):
        out = []
        for head, text in line.parts:
            words = _words(text)
            if head is not None:
                top = _chord_html(head, names) if isinstance(head, int) else _mark_html(head)
                first = escape(words.pop(0)) if words else ""
                out.append(f'<span class="s">{top}<span class="y">{first}</span></span>')
            out += [f'<span class="w">{escape(w)}</span>' for w in words]
        return f'<p class="l{legend}">{"".join(out)}</p>'
    if isinstance(line, ChordRow):
        items = [_chord_html(i, names) if isinstance(i, int) else _mark_html(i) for i in line.items]
        return f'<p class="l chords{legend}">{" ".join(items)}</p>'
    if isinstance(line, Text):
        return f'<p class="l">{escape(line.text)}</p>'
    if isinstance(line, Tab):
        return f'<pre class="tab">{escape(chr(10).join(line.lines))}</pre>'
    assert isinstance(line, Blank)
    return '<div class="gap"></div>'


def _wide(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


def _words(text: str) -> list[str]:
    """``text`` cut where a line may wrap: after each word's trailing spaces, and around each
    wide (CJK) character, which wraps on its own."""
    words: list[str] = []
    word = ""
    for ch in text:
        if not ch.isspace() and word and (_wide(ch) or word[-1].isspace() or _wide(word[-1])):
            words.append(word)
            word = ""
        word += ch
    if word:
        words.append(word)
    return words


# The bar at the foot of the page, the settings and the chord card the script fills in; hidden
# until it runs. The bar, in the order a keyboard reaches it: the rail of necks shown or hidden (from 1200 px,
# where there is a rail: pressed while it shows, as the settings' Chord necks row says; a sidebar, drawn as a
# path); the song a semitone down or up, its key in short between them (for the eye; whole for a screen
# reader); a guitar, the strip of the song's chord
# shapes shown or hidden (a toggle, pressed while it shows, as the settings' All chord shapes switch is, the two
# always in step; the body with its waist and sound hole, the neck and the headstock, drawn as paths);
# Aa, the text size in a box beside it; ▶, scrolling by itself; ⋯, the rest of the settings. The pill steers the scroll once it starts,
# above the bar's place, the bar out of the way while the song moves: its first button counts down (a
# ring and the seconds), pauses (❚❚) and resumes (▶); the status line says so to a screen reader. The settings and the card are dialogs that are not
# modal: nothing dims the song or takes it out of reach while they are open (viewer.js).
#
# The settings, top to bottom, grouped by space rather than headings: "Settings" and a line of what is set (the key
# and mode played, the capo, the instrument: viewer.js); Transpose and Capo side by side, each labelled over its
# stepper, with a Reset by its label while its value differs; the easier capos and an instrument's easy keys; Mode,
# what the mode played sounds like, and a pill a mode, the song's own marked; after a rule, the chord names (Chords,
# + Numerals, Numerals), why there are no numerals for a song with no key, and a switch for each thing on or off (a
# toggle button, pressed while it is on): Role colours, All chord shapes (as the bar's guitar), Chord necks (where the
# rail shows), and on a sheet with Chinese its characters, Simplified or Traditional (a segmented control, each named
# in its own characters too), then Pinyin; the instrument, a menu, and the strum's loudness, four speakers, on
# one line, and the instrument's own rows (instruments.js) under it; after a rule, the places to go, a row each (›
# opens something here, ↗ leaves the page): Harmony, the song's Guitar Pro files (``_GUITAR_ROW``) and Export PDF
# (``_EXPORT_ROW``, a sheet's alone); and after another, Reset everything, quiet.
# Each kind of control has one look: a stepper for a number, a segmented control for one of a few, pills for one of
# many, a switch for on or off, a row with › or ↗ for a place to go.
#
# A chord's card heads with the chord, Circle & keyboard (the chord's notes in a numeral's tooltip, which the card
# closes for; viewer.js shows it where the tooltip has notes to draw) and ×.
#
# A numeral's tooltip, top to bottom: the chord as the sheet names it, its numeral and its role in words; the
# numeral's line and the key it is read in; the chord's notes (viewer.js draws them: a twelve-note circle beside
# their list, or tiles over a keyboard), and a line naming a note from outside the key; the button to the other
# view, its two dots beside it marking the one shown, and ▶ Hear it after them, on the same row.
_UNDO = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12a9 9 0 1 0 2.6-6.4L3 8"/>'
         '<path d="M3 3v5h5"/></svg>')  # ↺, a Reset's: an arc and its arrowhead
_GO = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>'  # ›, a place here
_HARMONY_ROW = ('<div id="harmony-row" hidden><button type="button" class="goto" id="harmony-open" aria-haspopup="dialog" '
                'aria-controls="harmony"><span class="goto-lab">Harmony</span><span class="goto-v">progressions, scale'
                + _GO + '</span></button></div>\n')
# Export PDF of this version, in words at its right: served, a link to the PDF itself, caracole serve's download
# (viewer.js); from a file, a row that unfolds the command that makes it, with Copy.
_EXPORT_ROW = ("""<div id="export-row"><a class="goto" id="export"><span class="goto-lab">Export PDF</span>"""
               """<span class="goto-v"><span class="export-v"></span>""" + _GO + """</span></a>
<button type="button" class="goto" id="export-fold" hidden aria-expanded="false" aria-controls="export-file"><span class="goto-lab">Export PDF</span><span class="goto-v"><span class="export-v"></span>""" + _GO + """</span></button>
<div class="export-file" id="export-file" hidden><p class="hint" id="export-hint"></p>
<code class="cmd" id="export-cmd" hidden></code><button type="button" class="chip" id="export-copy" hidden>Copy</button></div></div>
""")


_CONTROLS = """<div class="bar" id="bar" hidden role="region" aria-label="Controls">
<div class="bar-in">
<button type="button" class="tool necks-toggle" id="necks-toggle" hidden aria-label="Chord necks" aria-pressed="true" aria-controls="necks"><svg viewBox="0 0 16 16" aria-hidden="true"><path fill-rule="evenodd" d="M3 2h10a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm0 1.5a.5.5 0 0 0-.5.5v8a.5.5 0 0 0 .5.5h10a.5.5 0 0 0 .5-.5V4a.5.5 0 0 0-.5-.5zM3.5 4.5h3v7h-3z"/></svg></button>
<span class="keys" id="keys" role="group" aria-label="Transpose">
<button type="button" class="step" id="t-down" aria-label="Transpose down a semitone">−</button>
<output class="now" id="key-now" for="t-down t-up"><span class="k" aria-hidden="true"></span><span class="d" aria-hidden="true"></span><span class="vh" id="key-full"></span></output>
<button type="button" class="step" id="t-up" aria-label="Transpose up a semitone">+</button>
</span>
<button type="button" class="tool shapes" id="shapes" aria-label="Chord shapes" aria-pressed="false" aria-controls="strip"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6.67 12.95A3.2 3.2 0 1 1 3.05 9.33A1.42 1.42 0 0 0 4.07 8.64A2.4 2.4 0 1 1 7.36 11.93A1.42 1.42 0 0 0 6.67 12.95ZM6.77 9.23A1.07 1.07 0 1 0 5.26 10.74A1.07 1.07 0 1 0 6.77 9.23Z"/><path d="M8.03 9.23L12.68 4.58L12.87 4.76L15.7 2.82L13.18 0.3L11.24 3.13L11.42 3.32L6.77 7.97Z"/></svg></button>
<span class="size-box" id="size-box">
<button type="button" class="tool" id="size" aria-label="Text size" aria-expanded="false" aria-controls="sizes">Aa</button>
<span class="sizes" id="sizes" role="group" aria-label="Text size" hidden>
<button type="button" id="smaller" aria-label="Smaller text" aria-disabled="false">A−</button>
<output id="fs-now">18 px</output>
<button type="button" id="bigger" aria-label="Bigger text" aria-disabled="false">A+</button>
</span>
</span>
<button type="button" class="tool play" id="scroll" aria-label="Scroll by itself"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 2.4v11.2c0 .6.7 1 1.2.6l8.8-5.6a.7.7 0 0 0 0-1.2L5.7 1.8c-.5-.4-1.2 0-1.2.6z"/></svg></button>
<button type="button" class="tool" id="more" aria-label="More settings" aria-haspopup="dialog" aria-controls="panel" aria-expanded="false"><svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="2.5" cy="8" r="1.6"/><circle cx="8" cy="8" r="1.6"/><circle cx="13.5" cy="8" r="1.6"/></svg></button>
</div>
</div>
<div class="pill" id="pill" role="group" aria-label="Scrolling by itself" hidden>
<button type="button" class="go" id="go" aria-label="Pause"><svg class="ring" viewBox="0 0 44 44" aria-hidden="true"><circle class="track" cx="22" cy="22" r="19"/><circle class="arc" cx="22" cy="22" r="19" pathLength="100"/></svg><svg class="i-pause" viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="2" width="3.6" height="12" rx="1"/><rect x="9.4" y="2" width="3.6" height="12" rx="1"/></svg><svg class="i-play" viewBox="0 0 16 16" aria-hidden="true"><path d="M4.5 2.4v11.2c0 .6.7 1 1.2.6l8.8-5.6a.7.7 0 0 0 0-1.2L5.7 1.8c-.5-.4-1.2 0-1.2.6z"/></svg><span class="tick" id="tick"></span></button>
<button type="button" class="step" id="pill-slower" data-speed="-1" aria-label="Slower">−</button>
<output id="pill-speed">6</output>
<button type="button" class="step" id="pill-faster" data-speed="1" aria-label="Faster">+</button>
<button type="button" class="end" id="pill-end" aria-label="Stop scrolling">×</button>
</div>
<p class="vh" id="scroll-status" role="status"></p>
<section class="sheet-ui panel" id="panel" hidden role="dialog" aria-labelledby="panel-title" aria-describedby="panel-sum">
<header class="ui-head"><div class="ui-title"><h2 id="panel-title" tabindex="-1">Settings</h2>
<p class="sum" id="panel-sum"></p></div>
<button type="button" class="x" data-close aria-label="Close">×</button></header>
<div class="pair">
<div class="num" id="t-row"><div class="num-top"><span id="t-lab">Transpose</span>
<button type="button" class="undo" id="reset-t" hidden aria-label="Reset the transposition">""" + _UNDO + """Reset</button></div>
<span class="stepper" role="group" aria-labelledby="t-lab"><button type="button" id="down" aria-label="Down a semitone">−</button>
<output id="shift">0</output><button type="button" id="up" aria-label="Up a semitone">+</button></span></div>
<div class="num" id="capo-row"><div class="num-top"><span id="capo-lab">Capo</span>
<button type="button" class="undo" id="reset-capo" hidden aria-label="Reset the capo">""" + _UNDO + """Reset</button></div>
<span class="stepper" role="group" aria-labelledby="capo-lab"><button type="button" id="capo-down" aria-label="Capo down a fret">−</button>
<output id="capo-at">0</output><button type="button" id="capo-up" aria-label="Capo up a fret">+</button></span></div>
</div>
<div class="opts" id="capo-opts" hidden><span class="opts-lab">Easier shapes</span><span class="chips" id="capo"></span></div>
<div class="opts" id="easy-row" hidden><span class="opts-lab">Easy keys</span><span class="chips" id="easy"></span>
<p class="hint" id="easy-hint"></p></div>
<div class="modes" id="mode-row" hidden><p class="modeline"><span class="lab">Mode</span><span class="what" id="mode-hint"></span></p>
<span class="chips" id="modes"></span></div>
<div class="chords ruled" id="names-row"><div class="seg" id="names" role="group" aria-label="Chord names"></div>
<p class="hint" id="names-hint"></p>
<button type="button" class="switch" id="roles" aria-pressed="true">Role colours<span class="roles" aria-hidden="true"><span class="r-h">home</span> <span class="r-a">away</span> <span class="r-p">pull</span></span></button>
<button type="button" class="switch" id="strip-toggle" aria-pressed="false" aria-controls="strip">All chord shapes</button>
<div id="necks-row" hidden><button type="button" class="switch" id="necks-chip" aria-pressed="true" aria-controls="necks">Chord necks</button></div>
<div id="hanzi-row" hidden><div class="seg" id="hanzi" role="group" aria-label="Chinese characters"><button type="button" id="hanzi-s" aria-pressed="true" aria-controls="sheet"><span>Simplified <span class="zh" lang="zh-Hans">简体</span></span></button>
<button type="button" id="hanzi-t" aria-pressed="false" aria-controls="sheet"><span>Traditional <span class="zh" lang="zh-Hant">繁體</span></span></button></div></div>
<div id="pinyin-row" hidden><button type="button" class="switch" id="pinyin-chip" aria-pressed="false" aria-controls="sheet" aria-describedby="pinyin-hint">Pinyin</button>
<p class="hint" id="pinyin-hint">Each Chinese character's reading, over it.</p></div>
<div class="duo" id="inst-line"><span class="inst-pick" id="inst-row" hidden><select id="insts" aria-label="Instrument"></select></span>
<span id="sound-row" hidden><span class="seg icons" id="volumes" role="group" aria-label="Strum" aria-describedby="strum-hint"></span>
<span class="vh" id="strum-hint">Tap a chord, or its shape on its card, to hear it strummed.</span></span></div>
<div class="inst-panel" id="inst-panel" hidden></div></div>
<div class="places ruled" id="places">
""" + _HARMONY_ROW + """</div>
<div class="panel-end ruled"><button type="button" class="quiet" id="reset-all">Reset everything</button></div>
</section>
<section class="sheet-ui card" id="card" hidden role="dialog" aria-labelledby="card-name">
<header class="ui-head"><h2 id="card-name" tabindex="-1"></h2>
<button type="button" class="tip-btn card-tip" id="card-tip" hidden>Circle &amp; keyboard</button>
<button type="button" class="x" data-close aria-label="Close">×</button></header>
<div class="shape"><button type="button" class="round" id="prev" aria-label="Previous shape">‹</button>
<div class="diagram" id="diagram"></div>
<button type="button" class="round" id="next" aria-label="Next shape">›</button></div>
<p class="hint center" id="shape-note"></p>
<h3 class="sub" id="alts-title">Chord alternatives</h3>
<div class="chips" id="alts"></div>
<div class="actions"><button type="button" class="btn primary" id="use" hidden></button></div>
<div class="info"><p class="tones" id="card-tones"></p><p class="solo" id="card-scale"></p></div>
</section>
<section class="sheet-ui panel harmony" id="harmony" hidden role="dialog" aria-labelledby="harmony-title">
<header class="ui-head"><h2 id="harmony-title" tabindex="-1">Harmony</h2>
<button type="button" class="x" data-close aria-label="Close">×</button></header>
<p class="hint" id="harmony-key"></p>
<div id="harmony-neck"></div>
<div class="row" id="tempo-row" hidden><span class="lab">Tempo</span>
<span class="stepper"><button type="button" id="bpm-down" aria-label="Slower">−</button>
<output id="bpm">80</output><button type="button" id="bpm-up" aria-label="Faster">+</button></span>
<span class="hint-inline">bpm, a chord a bar</span></div>
<ol class="progs" id="progs"></ol>
<p class="hint" id="progs-none" hidden>No chords here caracole can read.</p>
</section>
<div class="tip" id="tip" role="tooltip" hidden>
<div class="tip-head"><span class="tip-chord" id="tip-chord"></span><span class="tip-nm" id="tip-nm"></span><span class="tip-role" id="tip-role"></span></div>
<p class="tip-line" id="tip-line"></p><p class="tip-key" id="tip-key"></p>
<div class="tip-pic" id="tip-pic"><div class="tip-circle" id="tip-circle"><div class="tip-clock" id="tip-clock" aria-hidden="true"></div><ul class="tip-notes" id="tip-notes"></ul></div>
<div class="tip-keys" id="tip-keys" hidden><ul class="tip-tiles" id="tip-tiles"></ul><div class="tip-kb" id="tip-kb" aria-hidden="true"></div></div></div>
<p class="tip-off" id="tip-off" hidden></p>
<div class="tip-switch" id="tip-switch"><span class="tip-dots" id="tip-dots" aria-hidden="true"><span></span><span></span></span><button type="button" class="tip-btn tip-view" id="tip-view"></button>
<button type="button" class="tip-btn tip-hear" id="tip-hear"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4.5v15l12-7.5z"/></svg>Hear it</button></div></div>
<noscript><p class="noscript">Turn on JavaScript to transpose, change the mode and see chord shapes.</p></noscript>
"""

# A sheet viewer's versions (its data's ``versions``), hidden until the script fills them in: under the key
# line, ‹ and › open the version kept before or after this one, in rank order, and between them the line
# that says which this is ("Ver 3 of 13 · 4.86★ (408) · the one") opens the list of every version UG has, a
# dialog that is not modal, like the settings (a rail beside the song from 900 px wide, where it takes the
# settings' place). An end ‹ or › has no address. The songbook has neither: its songs have no versions.
_VERSIONS = """<nav class="versions" id="versions" hidden aria-label="Versions of this sheet">
<a class="vstep" id="ver-prev" aria-label="The version kept before this one">‹</a>
<button type="button" class="vnow" id="ver-now" aria-haspopup="dialog" aria-controls="version-list" aria-expanded="false"><span id="ver-line"></span><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.6 5.6 8 11l5.4-5.4-1.2-1.2L8 8.6 3.8 4.4z"/></svg></button>
<a class="vstep" id="ver-next" aria-label="The version kept after this one">›</a>
</nav>
"""

_VERSION_LIST = """<section class="sheet-ui panel vlist" id="version-list" hidden role="dialog" aria-labelledby="version-list-title">
<header class="ui-head"><h2 id="version-list-title" tabindex="-1">Versions</h2>
<button type="button" class="x" data-close aria-label="Close">×</button></header>
<div class="row vrow" id="ver-acts" hidden></div>
<ol class="vers" id="ver-items"></ol>
</section>
"""

# A sheet viewer's Guitar Pro files, in its settings, for a song that has some: the script fills in a row for each
# (viewer.js: caracole serve's Guitar Pro page, served; the file itself, from a file).
_GUITAR_ROW = '<div id="guitar-row" hidden><div id="guitar-links"></div></div>\n'
_PLACES_END = '</div>\n<div class="panel-end ruled">'  # where the places to go end, before Reset everything


def _with_guitar(controls: str, guitar: bool) -> str:
    """``controls`` with the Guitar Pro row after Harmony's, when the song has Guitar Pro files."""
    return controls.replace(_HARMONY_ROW, _HARMONY_ROW + _GUITAR_ROW, 1) if guitar else controls


# Export PDF's question, served, pressed on a version other than the song's own (viewer.js fills it in and opens it): a
# modal dialog, its focus kept inside, Escape, × and Cancel closing it, that asks whether to make this version the
# song's own ("Make this your version of <title>?", the version in words, what that does), with Download and make it
# mine (the download's link with mine=1), Just download (the link) and Cancel. Its content in a box of its own, so
# that a tap on the dialog itself is a tap beside it, on the backdrop.
_EXPORT_ASK = """<dialog class="ask" id="export-ask" aria-labelledby="ask-title" aria-describedby="ask-version ask-what">
<div class="ask-in"><header class="ui-head"><h2 id="ask-title" tabindex="-1"></h2>
<button type="button" class="x" id="ask-x" aria-label="Close">×</button></header>
<p class="ask-v" id="ask-version"></p>
<p class="hint" id="ask-what">Its PDF, its viewer and your songbooks will start there.</p>
<div class="ask-acts"><a class="btn primary" id="ask-mine">Download and make it mine</a>
<a class="btn" id="ask-just">Just download</a>
<button type="button" class="btn" id="ask-cancel">Cancel</button></div></div>
</dialog>
"""


# The sheet viewer's controls: the shared ones, the export row, the last place to go, and its question. The songbook
# has none: no song owns it.
_SHEET_CONTROLS = _CONTROLS.replace(_PLACES_END, _EXPORT_ROW + _PLACES_END, 1) + _EXPORT_ASK
