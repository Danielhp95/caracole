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
  slugged tab only at its slugged URL.
- ``[transpose]``: "Artist - Title" → semitones, applied when sheets are rendered.
- ``[ignore] songs``: songs to skip.
- ``[block] tab_ids``: tabs never to use.
- ``[reject]``: "Artist - Title" → "ug-artist/ug-song"s that are not the song
  (``caracole review``'s "none of these"): the matcher never offers them again,
  and goes on looking for the song.
- ``[youtube]``: "Artist - Title" → the YouTube video caracole takes the song's
  audio from, in place of the one its search picks (youtube_fetch.py), or "none":
  never take this song's audio from YouTube.

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
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

import tomlkit
from tomlkit.exceptions import TOMLKitError

from caracole.library import NotRegularFile, read_regular, write_atomic
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
_TABLES = {"alias", "match", "artist_url", "pin", "transpose", "ignore", "block", "reject", "youtube"}
# How messages and the to-do page write a YouTube video's address, and the value that says "no video".
VIDEO_SHAPE = "https://www.youtube.com/watch?v=…"
NO_VIDEO = "none"
_TWICE = re.compile(r"Cannot declare (\(.*\)) twice")  # tomllib's words for a table declared twice


class OverridesError(Exception):
    pass


@dataclass(frozen=True)
class Overrides:
    """overrides.toml, canonicalized. ``pin_urls`` holds each pin's address, in ``pin``'s order;
    ``reject`` holds each song's rejected (artist key, song key) pairs, every entry of the song's;
    ``artist_url_names`` the name each ``[artist_url]`` entry is written under, by its key;
    ``youtube`` each song's video id, or None for "none"."""

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


def _pin_url(value: str) -> str:
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
    tab pages, written as a pin's is (``_pin_url``), which caracole reads once for the artist's page
    it links to. None for anything else, a bare number included: it could be either page's."""
    page = artist_page_address(url)
    if page is not None or not isinstance(url, str) or url.strip().isdigit():
        return page
    try:
        tab_id_from_url(url)
    except OverridesError:
        return None
    return _pin_url(url)


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


def _read(path: Path) -> str | None:
    """The file's text, None when there is none; anything but a regular file is refused unread.

    A file that can't be read, or isn't UTF-8, is an OverridesError too: every caller reports one.
    """
    try:
        data = read_regular(path)
    except FileNotFoundError:
        return None
    except NotRegularFile as e:
        raise OverridesError(f"{path}: {e.strerror}; put the file itself there") from e
    except OSError as e:  # no permission to read it, say
        raise OverridesError(f"{path}: can't read it: {e.strerror or e}") from e
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        line = data[: e.start].count(b"\n") + 1
        raise OverridesError(f"{path}: line {line} is not valid UTF-8 (save the file as UTF-8)") from e


def _declared_twice(e: tomllib.TOMLDecodeError) -> str:
    """What to do about a table declared twice, as pasting two blocks with the same header makes one."""
    m = _TWICE.match(str(e))
    try:
        keys = ast.literal_eval(m.group(1)) if m else None
        return f"; merge the two [{'.'.join(keys)}] sections into one" if keys else ""
    except (ValueError, SyntaxError, TypeError):
        return ""


def load_overrides(path: Path) -> Overrides:
    """Read overrides.toml; a missing file means no overrides. Every error names the file."""
    text = _read(path)
    if text is None:
        return Overrides()
    try:
        return _parse(tomllib.loads(text))
    except tomllib.TOMLDecodeError as e:
        raise OverridesError(f"{path}: {e}{_declared_twice(e)}") from e
    except OverridesError as e:
        raise OverridesError(f"{path}: {e}") from e


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
            pin_urls[ident] = tuple(_pin_url(u) for u in pasted)
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

    return Overrides(
        alias=alias, match=match, artist_url=artist_url, pin=pin, transpose=transpose,
        ignore=ignore, block=frozenset(tab_ids), pin_urls=pin_urls, reject=reject,
        artist_url_names=artist_url_names, youtube=youtube,
    )


def _video(value: Any, where: str) -> str | None:
    """A ``[youtube]`` value: the id of the video at a YouTube address, or None for "none"."""
    if isinstance(value, str) and value.strip().lower() == NO_VIDEO:
        return None
    video = video_id_from_url(value)
    if video is None:
        raise OverridesError(f"{where}: expected a YouTube video's address ({VIDEO_SHAPE}) or \"{NO_VIDEO}\", "
                             f"got {value!r}")
    return video


def _edit(path: Path, change) -> None:
    old = _read(path)
    try:
        doc = tomlkit.document() if old is None else tomlkit.parse(old)
    except TOMLKitError as e:
        raise OverridesError(f"{path}: {e}") from e
    change(doc)
    text = tomlkit.dumps(doc)
    if text == old:
        return  # nothing changed: the file is left alone
    write_atomic(path, text.encode("utf-8"))


def _table_of(doc, name: str):
    if name not in doc:
        doc[name] = tomlkit.table()
    return doc[name]


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

    def same_song(key: str) -> bool:
        try:
            return override_key(key) == wanted
        except OverridesError:
            return False

    def change(doc) -> None:
        t = _table_of(doc, "reject")
        key = next((k for k in reversed(list(t)) if same_song(k)), None)
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

    def same_song(key: str) -> bool:
        try:
            return override_key(key) == wanted
        except OverridesError:
            return False

    def change(doc) -> None:
        t = _table_of(doc, "youtube")
        key = next((k for k in reversed(list(t)) if same_song(k)), None)
        if key is None:
            t[display] = value
        elif _video(t[key], f"[youtube] {key!r}") != video:
            t[key] = value

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


def _append_unique(doc, table: str, key: str, value: Any, same) -> None:
    t = _table_of(doc, table)
    if key not in t:
        t[key] = tomlkit.array()
    if not any(same(existing, value) for existing in t[key]):
        t[key].append(value)


def add_ignore(path: Path, display: str) -> None:
    wanted = override_key(display)

    def same(existing: Any, _value: Any) -> bool:
        try:
            return override_key(str(existing)) == wanted
        except OverridesError:
            return False

    _edit(path, lambda doc: _append_unique(doc, "ignore", "songs", display, same))


def add_block(path: Path, tab_id: int) -> None:
    _edit(path, lambda doc: _append_unique(doc, "block", "tab_ids", int(tab_id), lambda a, b: int(a) == b))
