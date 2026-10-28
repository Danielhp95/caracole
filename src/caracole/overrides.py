"""overrides.toml: your decisions, kept in a file you can edit and keep in git.

Tables:

- ``[alias]``: source artist → UG artist slug(s), which fixes every song by
  that artist at once.
- ``[match]``: "Artist - Title" → "ug-artist/ug-song", for a title-level
  correction that still picks up new tabs.
- ``[artist_url]``: artist → UG artist page, for artists UG's sitemaps list
  only by bare ids (accented names, Chinese names), or one of the artist's tab
  pages, which the fetch reads once for the artist page it links to.
- ``[pin]``: "Artist - Title" → tab page URLs to always use. Each pin keeps its
  tab id (``pin``) and the address you pasted (``pin_urls``): UG serves a
  slugged tab only at its slugged URL. ``remove_pin`` takes a song's pins out
  (``caracole versions --clear``).
- ``[transpose]``: "Artist - Title" → semitones, applied when sheets are rendered.
- ``[version]``: "Artist - Title" → where you play the song, as "Make this my version" saves it
  (``add_version``): the key it plays in, as the sheet reads its chords, a mode chosen and its capo,
  and the chords played instead and the shapes chosen, by their names
  (``key=Gm&mode=dorian&capo=0&alt=F.Fmaj7&at=Gm.x-x-5-7-8-6``,
  viewer/version.py ``KeyVersion``), so that a sheet in another key in its sheet's place plays
  there too; or, as caracole wrote it before, the viewer's address (``t=2&mode=dorian&capo=0``),
  a move from the sheet. Its PDF, its viewer and its songbooks start there (render.py
  ``own_version``). It wins over the song's ``[transpose]``.
- ``[ignore] songs``: songs to skip.
- ``[block] tab_ids``: tabs never to use.
- ``[reject]``: "Artist - Title" → "ug-artist/ug-song"s that are not the song
  (``caracole review``'s "none of these"): the matcher never offers them again,
  and goes on looking for the song.
- ``[youtube]``: "Artist - Title" → the YouTube video caracole takes the song's
  audio from, in place of the one its search picks (youtube_fetch.py), or "none":
  never take this song's audio from YouTube.
- ``[lacuerda]``: "Artist - Title" → the LaCuerda song (its page) or version (its
  sheet's page) you picked (``LaCuerdaPick``): lacuerda_fetch.py keeps that sheet,
  whatever its coverage, and Ultimate Guitar's fetch never replaces it.
- ``[harptabs]``: "Artist - Title" → the harptabs.com tab (its page) you picked
  (``HarpTabsPick``): harptabs_fetch.py keeps that tab for the song, as its next
  ``harmonica-N.txt`` beside any it has, whoever the page names as its artist.
- ``[gametabs]``: "Artist - Title" → the gametabs.net tab (its page) you picked
  (``GameTabsPick``): gametabs_fetch.py keeps that tab for the song, as its next
  ``gametab-N.txt`` beside any it has, whatever game or composer its page names.
- ``[harmonica]``: "Artist - Title" → a table of the song's harmonica tabs (``harmonica-1.txt``) and how
  each is read, whatever caracole guesses (``add_harmonica``, caracole serve's page of readings, ``caracole
  harmonica``): a notation's name ("signs", "brackets", "letters", "signs after", "barrett"), "legend" (the
  tab's own), or a table, a notation (``as``) and what its symbols mean (``{as = "signs", "*" = "bend"}``):
  viewer/harptab.py ``check_spec`` and ``pinned``. render.py reads each tab's page by it.

Keys are canonicalized when loaded, so they're matched the same way songs are.
Writers use tomlkit, so your comments and layout survive.

The file usually sits in the library, which every synced device can write to,
so it is read only when it is a regular file: a symbolic link there could point
at caracole's private files. Writers replace it through a temporary file of a
name of its own (``library.write_atomic``).
"""

from __future__ import annotations

import ast
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Collection, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlsplit

import tomlkit
from tomlkit.exceptions import TOMLKitError

from caracole.library import read_text, write_atomic
from caracole.normalize import compact, identity_key, name_forms, slug_key, ug_slug_key
from caracole.youtube_urls import video_id_from_url, watch_url

# UG's hosts as an address bar shows them, in any case: www and tabs, the bare domain, and a language
# edition's (UG's tab pages link to es.ultimate-guitar.com as their Spanish edition). Whichever host it
# was pasted from, caracole asks for a tab page on tabs and an artist page on www.
_UG_HOST = re.compile(r"(?:(?:www|tabs|[a-z]{2})\.)?ultimate-guitar\.com")
_SCHEME = re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE)
# A tab page is /tab/<id> or /tab/<artist>/<song>-<type>-<id>.
_TAB_PATH = re.compile(r"/tab/(?:[^/]+/)?(?:[^/]*-)?(\d+)")
_TAB_HOST = "https://tabs.ultimate-guitar.com"
# An artist page is /artist/<name>_<id> (/artist/soda_stereo_2946) or, for some artists, /artist/<id>
# alone (宋冬野's /artist/634073); /artist/<name> without the number answers 404.
_ARTIST_PATH = re.compile(r"/artist/(?:[^/?#]+_)?\d+")
_ARTIST_HOST = "https://www.ultimate-guitar.com"
# How messages and the to-do page write an artist page's address and a tab page's.
ARTIST_PAGE_SHAPE = f"{_ARTIST_HOST}/artist/…"
TAB_PAGE_SHAPE = f"{_TAB_HOST}/tab/…"
_TABLES = {"alias", "match", "artist_url", "pin", "transpose", "ignore", "block", "reject", "youtube", "lacuerda",
           "harptabs", "gametabs", "version", "harmonica"}
_HARMONICA_TAB = re.compile(r"harmonica-[1-9][0-9]{0,3}\.txt")  # a harmonica tab's name, as inbox.py keeps it
# How messages and the to-do page write a YouTube video's address, and the value that says "no video".
VIDEO_SHAPE = "https://www.youtube.com/watch?v=…"
NO_VIDEO = "none"
# LaCuerda's hosts as an address bar shows them; caracole asks acordes.lacuerda.net. A song's page is
# /<artist>/<song>, a version's /<artist>/<song>.shtml (version 1) or /<artist>/<song>-<n>.shtml (lacuerda.py).
_LACUERDA_HOST = re.compile(r"(?:(?:acordes|www)\.)?lacuerda\.net")
_LACUERDA_PATH = re.compile(r"/([a-z0-9_]+)/([a-z0-9_]+?)(?:(?:-([1-9][0-9]*))?(\.shtml))?")
LACUERDA_BASE = "https://acordes.lacuerda.net"
LACUERDA_PAGE_SHAPE = f"{LACUERDA_BASE}/<artist>/<song>"
_HARPTABS_HOST = re.compile(r"(?:www\.)?harptabs\.com")
_HARPTABS_PATH = re.compile(r"/tab/([1-9][0-9]{0,8})/([a-z0-9-]{1,200})")
HARPTABS_BASE = "https://www.harptabs.com"
HARPTABS_PAGE_SHAPE = f"{HARPTABS_BASE}/tab/<id>/<slug>"
_GAMETABS_HOST = re.compile(r"(?:www\.)?gametabs\.net")
_GAMETABS_PATH = re.compile(r"/tabs/([a-z0-9_-]{1,200})/([a-z0-9_-]{1,200})")
GAMETABS_BASE = "https://gametabs.net"
GAMETABS_PAGE_SHAPE = f"{GAMETABS_BASE}/tabs/<game>/<tab>"
_TWICE = re.compile(r"Cannot declare (\(.*\)) twice")  # tomllib's words for a table declared twice
# A version as a viewer's address writes it, and how long one may be: every chord's shape and swap is a few hundred.
VERSION_SHAPE = "t=2&mode=dorian&capo=0"
VERSION_MAX = 2000


class OverridesError(Exception):
    pass


@dataclass(frozen=True)
class Overrides:
    """overrides.toml, canonicalized. ``pin_urls`` holds each pin's address, in ``pin``'s order;
    ``reject`` holds each song's rejected (artist key, song key) pairs, every entry of the song's;
    ``artist_url_names`` the name each ``[artist_url]`` entry is written under, by its key;
    ``youtube`` each song's video id, or None for "none"; ``version`` each song's own version, as the
    entry writes it (without a "#"): kept by its key, or a viewer's address; ``tables`` every table the file
    declares, even one with no entry left in it (``has_table``)."""

    alias: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    match: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    artist_url: Mapping[str, str] = field(default_factory=dict)
    pin: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    transpose: Mapping[str, int] = field(default_factory=dict)
    ignore: frozenset[str] = frozenset()
    block: frozenset[int] = frozenset()
    pin_urls: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    reject: Mapping[str, frozenset[tuple[str, str]]] = field(default_factory=dict)
    artist_url_names: Mapping[str, str] = field(default_factory=dict)
    youtube: Mapping[str, str | None] = field(default_factory=dict)
    lacuerda: Mapping[str, LaCuerdaPick] = field(default_factory=dict)
    harptabs: Mapping[str, HarpTabsPick] = field(default_factory=dict)
    gametabs: Mapping[str, GameTabsPick] = field(default_factory=dict)
    version: Mapping[str, str] = field(default_factory=dict)
    harmonica: Mapping[str, Mapping[str, str | Mapping[str, str]]] = field(default_factory=dict)
    tables: frozenset[str] = frozenset()

    def has_table(self, name: str) -> bool:
        """Whether the file has the table ``name``, with entries or none (its only line commented out, or the
        header kept from the docs' sample): lines to paste then come without its header, as a table declared
        twice makes the whole file unreadable."""
        return name in self.tables or bool(getattr(self, name, None))


@dataclass(frozen=True)
class LaCuerdaPick:
    """A LaCuerda song you picked (``[lacuerda]``): its artist's slug and its own, and the version whose
    sheet you picked, or None for the song's best Letra y Acordes version."""

    artist: str
    song: str
    version: int | None = None

    @property
    def url(self) -> str:
        """The song's page, or the version's: as caracole writes the pick and asks for it."""
        if self.version is None:
            return f"{LACUERDA_BASE}/{self.artist}/{self.song}"
        return f"{LACUERDA_BASE}/{self.artist}/{self.song}{'' if self.version == 1 else f'-{self.version}'}.shtml"

    def holds(self, tab_id: str) -> bool:
        """Whether a LaCuerda version, by its tab id (``artist/song-N``, as lacuerda_fetch.py records it),
        is the one picked: that version, or for a song, any of its versions."""
        artist, _, rest = tab_id.partition("/")
        song, dash, n = rest.rpartition("-")
        return (dash == "-" and artist == self.artist and song == self.song
                and (self.version is None or n == str(self.version)))


@dataclass(frozen=True)
class HarpTabsPick:
    """A harptabs.com tab you picked (``[harptabs]``): the site's id of it and its page's slug."""

    tab_id: int
    slug: str

    @property
    def path(self) -> str:
        """Its page's path, as harptabs.com's index keeps it (``tab/25/piano-man``)."""
        return f"tab/{self.tab_id}/{self.slug}"

    @property
    def url(self) -> str:
        """Its page: as caracole writes the pick and asks for it."""
        return f"{HARPTABS_BASE}/{self.path}"


@dataclass(frozen=True)
class GameTabsPick:
    """A gametabs.net tab you picked (``[gametabs]``): its game's slug and its own."""

    game: str
    slug: str

    @property
    def path(self) -> str:
        """Its page's path, as gametabs.net's index keeps it (``tabs/actraiser/fillmore``)."""
        return f"tabs/{self.game}/{self.slug}"

    @property
    def url(self) -> str:
        """Its page: as caracole writes the pick and asks for it."""
        return f"{GAMETABS_BASE}/{self.path}"


def gametabs_pick_from_url(url: Any) -> GameTabsPick:
    """The gametabs.net tab a page's address names (``GameTabsPick``), written as an address bar shows it:
    without ``https://``, with ``www.``, with a query or a trailing slash."""
    text = url.strip() if isinstance(url, str) else ""
    if text and not _SCHEME.match(text):
        text = f"https://{text}"
    try:
        parts = urlsplit(text)
    except ValueError:
        parts = None
    found = None
    if parts is not None and parts.scheme in ("http", "https") and _GAMETABS_HOST.fullmatch(parts.netloc.lower()):
        found = _GAMETABS_PATH.fullmatch(parts.path.rstrip("/"))
    if found is None:
        raise OverridesError(f"expected a gametabs.net tab's page ({GAMETABS_PAGE_SHAPE}), got {url!r}")
    return GameTabsPick(found.group(1), found.group(2))


def harptabs_pick_from_url(url: Any) -> HarpTabsPick:
    """The harptabs.com tab a page's address names (``HarpTabsPick``), written as an address bar shows it:
    without ``https://``, without ``www.``, with a query or a trailing slash."""
    text = url.strip() if isinstance(url, str) else ""
    if text and not _SCHEME.match(text):
        text = f"https://{text}"
    try:
        parts = urlsplit(text)
    except ValueError:
        parts = None
    found = None
    if parts is not None and parts.scheme in ("http", "https") and _HARPTABS_HOST.fullmatch(parts.netloc.lower()):
        found = _HARPTABS_PATH.fullmatch(parts.path.rstrip("/"))
    if found is None:
        raise OverridesError(f"expected a harptabs.com tab's page ({HARPTABS_PAGE_SHAPE}), got {url!r}")
    return HarpTabsPick(int(found.group(1)), found.group(2))


def lacuerda_pick_from_url(url: Any) -> LaCuerdaPick:
    """The LaCuerda song or version a page's address names (``LaCuerdaPick``), written as an address bar
    shows it: without ``https://``, on lacuerda.net, with a query or a trailing slash."""
    text = url.strip() if isinstance(url, str) else ""
    if text and not _SCHEME.match(text):
        text = f"https://{text}"
    try:
        parts = urlsplit(text)
    except ValueError:
        parts = None
    found = None
    if parts is not None and parts.scheme in ("http", "https") and _LACUERDA_HOST.fullmatch(parts.netloc.lower()):
        path = parts.path if parts.path.endswith(".shtml") else parts.path.rstrip("/")
        found = _LACUERDA_PATH.fullmatch(path)
    if found is None or found.group(1) == "tabs":
        raise OverridesError(f"expected a LaCuerda song's page ({LACUERDA_PAGE_SHAPE}) or one of its versions' "
                             f"(…/<song>-2.shtml), got {url!r}")
    artist, song, n, shtml = found.groups()
    return LaCuerdaPick(artist, song, int(n) if n else (1 if shtml else None))


def override_key(display: str) -> str:
    """The song identity for an "Artist - Title" key."""
    artist, sep, title = display.partition(" - ")
    if not sep or not artist.strip() or not title.strip():
        raise OverridesError(f"expected \"Artist - Title\", got {display!r}")
    return identity_key(artist.strip(), title.strip())


def _ug_path(url: Any) -> str | None:
    """The path of an address on one of UG's hosts (``_UG_HOST``), without its query, fragment and
    trailing slash; None for anything else.

    It is taken as an address bar shows it: without ``https://``, without ``www.``, with capitals
    in the host, on a language edition's host. The query and fragment of a link (``?ref=``, the
    artist page's own ``?filter=chords``, ``?page=2``, ``#…``) go: caracole asks for the bare page.
    """
    if not isinstance(url, str):
        return None
    text = url.strip()
    if not _SCHEME.match(text):
        text = f"https://{text}"
    try:
        parts = urlsplit(text)
    except ValueError:  # a link urllib can't parse ("Invalid IPv6 URL"): no UG page
        return None
    if parts.scheme not in ("http", "https") or not _UG_HOST.fullmatch(parts.netloc.lower()):
        return None
    return parts.path.rstrip("/")


def tab_id_from_url(url: str | int) -> int:
    """The tab id of a UG tab page URL (``/tab/85053`` or ``/tab/a/b-chords-85053``), written as an
    address bar shows it (``_ug_path``)."""
    if isinstance(url, int) or (isinstance(url, str) and url.strip().isdigit()):
        return int(url)
    path = _ug_path(url)
    m = _TAB_PATH.fullmatch(path) if path is not None else None
    if not m:
        raise OverridesError(f"not an Ultimate Guitar tab URL: {url!r}")
    return int(m.group(1))


def pin_url(value: str) -> str:
    """A pinned page's address: the URL as pasted, on the tabs host, over https and without its query,
    fragment and trailing slash; for a bare tab id, the bare ``/tab/{id}`` page. ``value`` passed
    ``tab_id_from_url``."""
    text = value.strip()
    if text.isdigit():
        return f"{_TAB_HOST}/tab/{int(text)}"
    return _TAB_HOST + (_ug_path(text) or "")


def artist_page_address(url: Any) -> str | None:
    """A UG artist page's address, on the www host, over https and without its query, fragment and
    trailing slash; None if ``url`` isn't one.

    Both of UG's shapes are artist pages: ``/artist/<name>_<id>`` and ``/artist/<id>``. It may be
    written as an address bar shows it (``_ug_path``).
    """
    path = _ug_path(url)
    return _ARTIST_HOST + path if path is not None and _ARTIST_PATH.fullmatch(path) else None


def _artist_url_value(url: Any) -> str | None:
    """An ``[artist_url]`` value: the artist's page (``artist_page_address``), or one of the artist's
    tab pages, written as a pin's is (``pin_url``), which caracole reads once for the artist's page
    it links to. None for anything else, a bare number included: it could be either page's."""
    page = artist_page_address(url)
    if page is not None or not isinstance(url, str) or url.strip().isdigit():
        return page
    try:
        tab_id_from_url(url)
    except OverridesError:
        return None
    return pin_url(url)


def pasted_tab_id(url: str) -> int | None:
    """The tab id when an ``[artist_url]`` value is a tab page; None when it is the artist's page."""
    if not url.startswith(f"{_TAB_HOST}/tab/"):
        return None
    try:
        return tab_id_from_url(url)
    except OverridesError:
        return None


def artist_url_entry(overrides: Overrides, keys: Iterable[str]) -> tuple[str, str] | None:
    """Your ``[artist_url]`` entry for an artist known by these keys, as (its key, its address).

    The entry under one of the keys comes first, else one whose name shares a form with them
    (``normalize.name_forms``), hyphens aside: an entry written "Song Dongye (宋冬野)", as UG
    names the artist, or "Song Dongye" serves 宋冬野's songs. The name is the one the entry is
    written under: its key has lost the brackets that tell its parts.
    """
    keys = [k for k in keys if k]
    for key in keys:
        if key in overrides.artist_url:
            return key, overrides.artist_url[key]
    wanted = {compact(k) for k in keys}
    for key, url in overrides.artist_url.items():
        if not wanted.isdisjoint(compact(f) for f in name_forms(overrides.artist_url_names.get(key, key))):
            return key, url
    return None


def _ug_ref(value: Any, where: str) -> tuple[str, str]:
    """The (artist key, song key) of ``"ug-artist/ug-song"``; ``where`` names the table and entry."""
    if not isinstance(value, str) or value.count("/") != 1:
        raise OverridesError(f"{where}: expected \"ug-artist/ug-song\", got {value!r}")
    artist, song = value.split("/")
    a, s = ug_slug_key(artist), ug_slug_key(song)
    if not a or not s:
        raise OverridesError(f"{where}: expected \"ug-artist/ug-song\", got {value!r}")
    return a, s


def _strings(value: Any, where: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    raise OverridesError(f"{where}: expected a string or a list of strings")


def _song_key(display: str, where: str) -> str:
    """``override_key`` for an entry of a table, whose error names the entry."""
    try:
        return override_key(display)
    except OverridesError as e:
        raise OverridesError(f"{where}: {e}") from e


def _only_key(t: Mapping[str, Any], name: str, key: str, shape: str) -> None:
    """``[ignore]`` and ``[block]`` hold one list each: any other key is a typo, never dropped."""
    unknown = [k for k in t if k != key]
    if unknown:
        listed = ", ".join(map(repr, unknown))
        raise OverridesError(f"unknown key(s) in [{name}]: {listed}; expected {key} = {shape}")


def _declared_twice(e: tomllib.TOMLDecodeError) -> str:
    """What to do about a table declared twice, as pasting two blocks with the same header makes one."""
    m = _TWICE.match(str(e))
    try:
        keys = ast.literal_eval(m.group(1)) if m else None
        return f"; merge the two [{'.'.join(keys)}] sections into one" if keys else ""
    except (ValueError, SyntaxError, TypeError):
        return ""


TOO_DEEP = "nested too deep for the TOML parser"  # tomllib and tomlkit raise RecursionError then


def load_overrides(path: Path) -> Overrides:
    """Read overrides.toml; a missing file means no overrides. Every error names the file."""
    text = read_text(path, OverridesError)
    if text is None:
        return Overrides()
    try:
        return _parse(tomllib.loads(text))
    except tomllib.TOMLDecodeError as e:
        raise OverridesError(f"{path}: {e}{_declared_twice(e)}") from e
    except RecursionError:  # any synced device can write the file: an OverridesError at worst
        raise OverridesError(f"{path}: {TOO_DEEP}") from None
    except OverridesError as e:
        raise OverridesError(f"{path}: {e}") from e


def load_overrides_or_none(path: Path) -> Overrides | None:
    """overrides.toml for a reader that does without it: None when it can't be read (``load_overrides``)."""
    try:
        return load_overrides(path)
    except OverridesError:
        return None


def _parse(data: Mapping[str, Any]) -> Overrides:
    unknown = sorted(set(data) - _TABLES)
    if unknown:
        raise OverridesError(f"unknown table(s): {', '.join(unknown)}")

    def table(name: str) -> Mapping[str, Any]:
        value = data.get(name, {})
        if not isinstance(value, Mapping):
            raise OverridesError(f"[{name}] must be a table")
        return value

    alias = {
        slug_key(artist): tuple(ug_slug_key(s) for s in _strings(v, f"[alias] {artist!r}"))
        for artist, v in table("alias").items()
    }
    match = {_song_key(k, f"[match] {k!r}"): _ug_ref(v, f"[match] {k!r}") for k, v in table("match").items()}

    artist_url: dict[str, str] = {}
    artist_url_names: dict[str, str] = {}
    for artist, url in table("artist_url").items():
        page = _artist_url_value(url)
        if page is None:
            raise OverridesError(
                f"[artist_url] {artist!r}: expected the artist's page ({ARTIST_PAGE_SHAPE}) or one of their "
                f"tab pages ({TAB_PAGE_SHAPE}), as your browser shows it, got {url!r}"
            )
        artist_url[slug_key(artist)] = page
        artist_url_names[slug_key(artist)] = artist

    pin: dict[str, tuple[int, ...]] = {}
    pin_urls: dict[str, tuple[str, ...]] = {}
    for k, v in table("pin").items():
        pasted = _strings(v, f"[pin] {k!r}")
        try:
            ident = override_key(k)
            pin[ident] = tuple(tab_id_from_url(u) for u in pasted)
            pin_urls[ident] = tuple(pin_url(u) for u in pasted)
        except OverridesError as e:
            raise OverridesError(f"[pin] {k!r}: {e}") from e

    transpose: dict[str, int] = {}
    for k, v in table("transpose").items():
        if not isinstance(v, int) or isinstance(v, bool) or not -11 <= v <= 11:
            raise OverridesError(f"[transpose] {k!r}: expected semitones between -11 and 11")
        transpose[_song_key(k, f"[transpose] {k!r}")] = v

    ignore_t = table("ignore")
    _only_key(ignore_t, "ignore", "songs", '["Artist - Title", ...]')
    songs = _strings(ignore_t.get("songs", []), "[ignore] songs")
    ignore = frozenset(_song_key(s, "[ignore] songs") for s in songs)

    block_t = table("block")
    _only_key(block_t, "block", "tab_ids", "[<tab id>, ...]")
    tab_ids = block_t.get("tab_ids", [])
    if not isinstance(tab_ids, list) or not all(isinstance(t, int) for t in tab_ids):
        raise OverridesError("[block] tab_ids must be a list of integers")

    reject: dict[str, frozenset[tuple[str, str]]] = {}
    for k, v in table("reject").items():
        where = f"[reject] {k!r}"
        ident = _song_key(k, where)
        refs = frozenset(_ug_ref(r, where) for r in _strings(v, where))
        reject[ident] = reject.get(ident, frozenset()) | refs  # the song written two ways: both count

    youtube = {_song_key(k, f"[youtube] {k!r}"): _video(v, f"[youtube] {k!r}") for k, v in table("youtube").items()}

    lacuerda: dict[str, LaCuerdaPick] = {}
    for k, v in table("lacuerda").items():
        where = f"[lacuerda] {k!r}"
        if not isinstance(v, str):
            raise OverridesError(f"{where}: expected a string, the address of a LaCuerda song's page")
        try:
            lacuerda[_song_key(k, where)] = lacuerda_pick_from_url(v)
        except OverridesError as e:
            raise OverridesError(f"{where}: {e}") from e

    harptabs: dict[str, HarpTabsPick] = {}
    for k, v in table("harptabs").items():
        where = f"[harptabs] {k!r}"
        if not isinstance(v, str):
            raise OverridesError(f"{where}: expected a string, the address of a harptabs.com tab's page")
        try:
            harptabs[_song_key(k, where)] = harptabs_pick_from_url(v)
        except OverridesError as e:
            raise OverridesError(f"{where}: {e}") from e

    gametabs: dict[str, GameTabsPick] = {}
    for k, v in table("gametabs").items():
        where = f"[gametabs] {k!r}"
        if not isinstance(v, str):
            raise OverridesError(f"{where}: expected a string, the address of a gametabs.net tab's page")
        try:
            gametabs[_song_key(k, where)] = gametabs_pick_from_url(v)
        except OverridesError as e:
            raise OverridesError(f"{where}: {e}") from e

    version = {_song_key(k, f"[version] {k!r}"): _version(v, f"[version] {k!r}") for k, v in table("version").items()}

    harmonica: dict[str, dict[str, str | Mapping[str, str]]] = {}
    for k, v in table("harmonica").items():
        where = f"[harmonica] {k!r}"
        key = _song_key(k, where)
        if not isinstance(v, Mapping):
            raise OverridesError(f"{where}: expected a table of its harmonica tabs, each \"harmonica-1.txt\" = how "
                                 "it is read")
        harmonica.setdefault(key, {}).update((tab, _harmonica_reading(spec, f"{where} {tab!r}"))
                                             for tab, spec in v.items())

    return Overrides(
        alias=alias, match=match, artist_url=artist_url, pin=pin, transpose=transpose,
        ignore=ignore, block=frozenset(tab_ids), pin_urls=pin_urls, reject=reject,
        artist_url_names=artist_url_names, youtube=youtube, lacuerda=lacuerda, harptabs=harptabs, gametabs=gametabs,
        version=version,
        harmonica=harmonica, tables=frozenset(data),
    )


def _harmonica_reading(spec: Any, where: str) -> str | dict[str, str]:
    """A ``[harmonica]`` tab's entry, its name checked (``harmonica-N.txt``) and how it is read (viewer/harptab.py
    ``check_spec``, imported for an entry alone: the viewer's notations)."""
    tab = where.rsplit(" ", 1)[-1].strip("'\"")
    if not _HARMONICA_TAB.fullmatch(tab):
        raise OverridesError(f"{where}: expected a harmonica tab's name, harmonica-N.txt")
    from caracole.viewer.harptab import check_spec

    try:
        check_spec(spec)
    except ValueError as e:
        raise OverridesError(f"{where}: {e}") from e
    return spec if isinstance(spec, str) else {str(k): str(v) for k, v in spec.items()}


def _video(value: Any, where: str) -> str | None:
    """A ``[youtube]`` value: the id of the video at a YouTube address, or None for "none"."""
    if isinstance(value, str) and value.strip().lower() == NO_VIDEO:
        return None
    video = video_id_from_url(value)
    if video is None:
        raise OverridesError(f"{where}: expected a YouTube video's address ({VIDEO_SHAPE}) or \"{NO_VIDEO}\", "
                             f"got {value!r}")
    return video


def _version(value: Any, where: str) -> str:
    """A ``[version]`` value: text, with no control character or escape that isn't UTF-8. Either a version kept
    by the key it plays in, as Make this my version writes it (``key=Gm&mode=dorian&capo=0``, read by
    viewer/version.py's ``key_version``, which refuses a key, a mode or a capo that can't be one), or a viewer's
    address after its "#" (or a "?"), as caracole wrote one before, which viewer/version.py reads as its viewer
    does (``version_from_query``): a move from the sheet."""
    text = value.strip() if isinstance(value, str) else None
    if text is not None and text[:1] in ("#", "?"):
        text = text[1:]
    try:
        readable = (text is not None and len(text) <= VERSION_MAX
                    and not any(ord(c) < 32 or ord(c) == 127 for c in text)
                    and not any(ord(c) < 32 or ord(c) == 127 for _, v in parse_qsl(text, errors="strict") for c in v))
    except (UnicodeDecodeError, ValueError):
        readable = False
    if not readable:
        raise OverridesError(f"{where}: expected a version as the sheet's viewer writes it in its address "
                             f"(\"{VERSION_SHAPE}\"), got {value!r}")
    if any(part.partition("=")[0] == "key" for part in text.split("&")):
        from caracole.viewer.version import key_version  # the viewer's theory, for an entry kept by its key alone

        try:
            key_version(text)
        except ValueError as e:
            raise OverridesError(f"{where}: {e}") from e
    return text


def _edit(path: Path, change) -> None:
    old = read_text(path, OverridesError)
    try:
        doc = tomlkit.document() if old is None else tomlkit.parse(old)
    except TOMLKitError as e:
        raise OverridesError(f"{path}: {e}") from e
    except RecursionError:
        raise OverridesError(f"{path}: {TOO_DEEP}") from None
    change(doc)
    text = tomlkit.dumps(doc)
    if text == old:
        return  # nothing changed: the file is left alone
    write_atomic(path, text.encode("utf-8"))


def _table_of(doc, name: str):
    if name not in doc:
        doc[name] = tomlkit.table()
    return doc[name]


def _names_song(key: Any, wanted: str) -> bool:
    """Whether an entry's key (or ``[ignore]``'s value) is the song whose key is ``wanted``, as it is read."""
    try:
        return override_key(str(key)) == wanted
    except OverridesError:
        return False


def add_alias(path: Path, source_artist: str, ug_artist: str) -> None:
    """Add ``ug_artist`` to the artist's aliases, keeping the ones already there.

    The artist's entry is found by its key, as aliases are matched, so the same artist
    written another way grows its own entry. A slug already among them changes nothing.
    """
    artist, slug = slug_key(source_artist), ug_slug_key(ug_artist)

    def change(doc) -> None:
        t = _table_of(doc, "alias")
        key = next((k for k in reversed(list(t)) if slug_key(k) == artist), None)  # the last one counts
        if key is None:
            t[source_artist] = ug_artist
            return
        current = t[key]
        if any(ug_slug_key(s) == slug for s in _strings(current, f"[alias] {key!r}")):
            return
        if isinstance(current, str):
            t[key] = [str(current), ug_artist]
        else:
            current.append(ug_artist)

    _edit(path, change)


def add_match(path: Path, display: str, ug_ref: str) -> None:
    override_key(display)
    _ug_ref(ug_ref, f"[match] {display!r}")
    _edit(path, lambda doc: _table_of(doc, "match").__setitem__(display, ug_ref))


def add_reject(path: Path, display: str, ug_refs: Sequence[str]) -> None:
    """Add UG songs (``"ug-artist/ug-song"``) to the song's ``[reject]`` list, keeping the ones there.

    The song's entry is found by its key, as rejections are matched, so the same song written
    another way adds to the entry it has. A UG song rejected already isn't added again.
    """
    wanted = override_key(display)
    refs = {_ug_ref(r, f"[reject] {display!r}"): r for r in ug_refs}

    def change(doc) -> None:
        t = _table_of(doc, "reject")
        key = next((k for k in reversed(list(t)) if _names_song(k, wanted)), None)  # the last one counts
        if key is None:
            t[display] = list(refs.values())
            return
        current, where = t[key], f"[reject] {key!r}"
        have = {_ug_ref(r, where) for r in _strings(current, where)}
        new = [r for ref, r in refs.items() if ref not in have]
        if new and isinstance(current, str):
            t[key] = [str(current), *new]
        else:
            for r in new:
                current.append(r)

    if refs:
        _edit(path, change)


def add_youtube(path: Path, display: str, url: str) -> None:
    """Set the song's ``[youtube]`` entry: the video at ``url``, written as its plain address, or "none".

    The song's entry is found by its key, as the table is read, so the song written another
    way changes the entry it has. The same video, or "none" again, writes nothing.
    """
    wanted = override_key(display)
    video = _video(url, f"[youtube] {display!r}")
    value = NO_VIDEO if video is None else watch_url(video)

    def change(doc) -> None:
        t = _table_of(doc, "youtube")
        key = next((k for k in reversed(list(t)) if _names_song(k, wanted)), None)  # the last one counts
        if key is None:
            t[display] = value
        elif _video(t[key], f"[youtube] {key!r}") != video:
            t[key] = value

    _edit(path, change)


def add_lacuerda(path: Path, display: str, url: str) -> None:
    """Set the song's ``[lacuerda]`` entry: the LaCuerda song or version at ``url``, written as caracole
    asks for it (``LaCuerdaPick.url``). The song's entry is found by its key, as the table is read, so
    the song written another way changes the entry it has; the same pick again writes nothing."""
    wanted = override_key(display)
    pick = lacuerda_pick_from_url(url)

    def same_song(key: str) -> bool:
        try:
            return override_key(key) == wanted
        except OverridesError:
            return False

    def change(doc) -> None:
        t = _table_of(doc, "lacuerda")
        key = next((k for k in reversed(list(t)) if same_song(k)), None)
        if key is None:
            t[display] = pick.url
        elif t[key] != pick.url:
            t[key] = pick.url

    _edit(path, change)


def add_harptabs(path: Path, display: str, url: str) -> None:
    """Set the song's ``[harptabs]`` entry: the harptabs.com tab at ``url``, written as caracole asks for it
    (``HarpTabsPick.url``). The song's entry is found by its key, as the table is read, so the song written
    another way changes the entry it has; the same pick again writes nothing."""
    wanted = override_key(display)
    pick = harptabs_pick_from_url(url)

    def same_song(key: str) -> bool:
        try:
            return override_key(key) == wanted
        except OverridesError:
            return False

    def change(doc) -> None:
        t = _table_of(doc, "harptabs")
        key = next((k for k in reversed(list(t)) if same_song(k)), None)
        if key is None:
            t[display] = pick.url
        elif t[key] != pick.url:
            t[key] = pick.url

    _edit(path, change)


def add_gametabs(path: Path, display: str, url: str) -> None:
    """Set the song's ``[gametabs]`` entry: the gametabs.net tab at ``url``, written as caracole asks for it
    (``GameTabsPick.url``). The song's entry is found by its key, as the table is read, so the song written
    another way changes the entry it has; the same pick again writes nothing."""
    wanted = override_key(display)
    pick = gametabs_pick_from_url(url)

    def same_song(key: str) -> bool:
        try:
            return override_key(key) == wanted
        except OverridesError:
            return False

    def change(doc) -> None:
        t = _table_of(doc, "gametabs")
        key = next((k for k in reversed(list(t)) if same_song(k)), None)
        if key is None:
            t[display] = pick.url
        elif t[key] != pick.url:
            t[key] = pick.url

    _edit(path, change)


def add_version(path: Path, display: str, query: str | None) -> None:
    """Set the song's ``[version]`` entry to ``query`` (a viewer's address, its "#" left out), or with None
    take the song's entries out: the song then plays as its ``[transpose]``, else as written.

    The song's entry is found by its key, as the table is read, so the song written another way changes
    the entry it has; the same version again, or nothing to take out, writes nothing."""
    wanted = override_key(display)
    value = None if query is None else _version(query, f"[version] {display!r}")

    def change(doc) -> None:
        if value is None and "version" not in doc:
            return
        t = _table_of(doc, "version")
        keys = [k for k in t if _names_song(k, wanted)]
        if value is None:
            for k in keys:
                del t[k]
        elif not keys:
            t[display] = value
        elif t[keys[-1]] != value:  # the last one counts
            t[keys[-1]] = value

    _edit(path, change)


def add_harmonica(path: Path, display: str, tab: str, reading: str | Mapping[str, str] | None) -> None:
    """Set how the song's harmonica tab ``tab`` (``harmonica-1.txt``) is read in ``[harmonica]``: a notation's name,
    "legend", or a table (an inline one, ``{as = "signs", "*" = "bend"}``); with None, take it out, and the song's
    entry with its last tab. The song's entry is found by its key, as the table is read (the last one counts), so
    the song written another way changes the entry it has, a hand-written ``[harmonica."Artist - Title"]`` too; the
    same reading again, or nothing to take out, writes nothing."""
    wanted = override_key(display)
    if reading is not None:
        reading = _harmonica_reading(reading, f"[harmonica] {display!r} {tab!r}")
    elif not _HARMONICA_TAB.fullmatch(tab):
        raise OverridesError(f"[harmonica] {display!r} {tab!r}: expected a harmonica tab's name, harmonica-N.txt")

    def inline(entries: Mapping[str, Any]) -> Any:
        """An inline table of ``entries``, a table among them inline too: written afresh, as tomlkit spaces the
        entries of one it made itself."""
        made = tomlkit.inline_table()
        for k, v in entries.items():
            made[k] = inline(v) if isinstance(v, Mapping) else v
        return made

    def change(doc) -> None:
        if reading is None and "harmonica" not in doc:
            return
        t = _table_of(doc, "harmonica")
        key = next((k for k in reversed(list(t)) if _names_song(k, wanted)), None)  # the last one counts
        current = t[key] if key is not None else None
        if current is not None and not isinstance(current, Mapping):
            raise OverridesError(f"[harmonica] {key!r}: expected a table of its harmonica tabs")
        if reading is None and (current is None or tab not in current):
            return
        if reading is not None and current is not None and current.get(tab) == reading:
            return
        entries = {k: (v.unwrap() if hasattr(v, "unwrap") else v) for k, v in (current or {}).items()}
        if reading is None:
            del entries[tab]
        else:
            entries[tab] = reading
        if not entries:
            del t[key]
        elif current is not None and not isinstance(current, tomlkit.items.InlineTable):
            if reading is None:  # [harmonica."Artist - Title"], written by hand: its lines and comments stay
                del current[tab]
            else:
                current[tab] = inline(reading) if isinstance(reading, Mapping) else reading
        else:
            t[key if key is not None else display] = inline(entries)

    _edit(path, change)


def add_artist_url(path: Path, artist: str, url: str) -> None:
    page = _artist_url_value(url)
    if page is None:
        raise OverridesError(f"[artist_url] {artist!r}: not a UG artist page or tab page URL: {url!r}")
    _edit(path, lambda doc: _table_of(doc, "artist_url").__setitem__(artist, page))


def add_pin(path: Path, display: str, urls: Sequence[str]) -> None:
    override_key(display)
    for u in urls:
        tab_id_from_url(u)
    _edit(path, lambda doc: _table_of(doc, "pin").__setitem__(display, list(urls)))


def remove_pin(path: Path, display: str, tabs: Collection[int] | None = None) -> bool:
    """Take the song's pins of ``tabs`` (every pin, with None) out of ``[pin]``, and an entry left empty with
    them; whether one was there. The song's entries are found by its key, as the table is read (as
    ``add_version`` finds them); the rest of the file, comments included, stays as it was."""
    wanted = override_key(display)
    removed = False
    if read_text(path, OverridesError) is None:
        return False  # no file, no pin: none is written

    def change(doc) -> None:
        nonlocal removed
        if "pin" not in doc:
            return
        t = doc["pin"]
        def goes(value: Any) -> bool:
            try:
                return tabs is None or tab_id_from_url(str(value)) in tabs
            except OverridesError:
                return False

        for k in [k for k in t if _names_song(k, wanted)]:
            values = t[k]
            if isinstance(values, str):  # one pin, written as a string
                if goes(values):
                    del t[k]
                    removed = True
                continue
            if not isinstance(values, list):
                continue
            for i in reversed(range(len(values))):
                if goes(values[i]):
                    del values[i]
                    removed = True
            if not len(values):
                del t[k]

    _edit(path, change)
    return removed


def _append_unique(doc, table: str, key: str, value: Any, same) -> None:
    """Add ``value`` to the list at ``table.key`` unless one there is the ``same``; a single value written as
    a string (``[ignore] songs = "A - B"``, which the reader takes) becomes a list of it and ``value``."""
    t = _table_of(doc, table)
    if key not in t:
        t[key] = tomlkit.array()
    current = t[key]
    if any(same(existing, value) for existing in ([current] if isinstance(current, str) else current)):
        return
    if isinstance(current, str):
        t[key] = [str(current), value]
    else:
        current.append(value)


def add_ignore(path: Path, display: str) -> None:
    wanted = override_key(display)
    _edit(path, lambda doc: _append_unique(doc, "ignore", "songs", display, lambda s, _: _names_song(s, wanted)))


def add_block(path: Path, tab_id: int) -> None:
    _edit(path, lambda doc: _append_unique(doc, "block", "tab_ids", int(tab_id), lambda a, b: int(a) == b))
