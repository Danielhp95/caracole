"""overrides.toml: your decisions, kept in a file you can edit and keep in git.

Tables:

- ``[alias]``: source artist → UG artist slug(s), which fixes every song by
  that artist at once.
- ``[match]``: "Artist - Title" → "ug-artist/ug-song", for a title-level
  correction that still picks up new tabs.
- ``[artist_url]``: artist → UG artist page, for artists UG's sitemaps list
  only by bare ids (accented names, Chinese names).
- ``[pin]``: "Artist - Title" → tab page URLs to always use. Each pin keeps its
  tab id (``pin``) and the address you pasted (``pin_urls``): UG serves a
  slugged tab only at its slugged URL.
- ``[transpose]``: "Artist - Title" → semitones, applied when sheets are rendered.
- ``[ignore] songs``: songs to skip.
- ``[block] tab_ids``: tabs never to use.

Keys are canonicalized when loaded, so they're matched the same way songs are.
Writers use tomlkit, so your comments and layout survive.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

import tomlkit

from tabarr.normalize import identity_key, slug_key, ug_slug_key

_TAB_URL = re.compile(r"^https?://tabs\.ultimate-guitar\.com/tab/(?:[^/?#]+/)?(?:[^/?#]*-)?(\d+)/?$")
_TAB_HOST = "https://tabs.ultimate-guitar.com"
_ARTIST_URL = re.compile(r"^https://www\.ultimate-guitar\.com/artist/[^/?#]+_\d+/?$")
_TABLES = {"alias", "match", "artist_url", "pin", "transpose", "ignore", "block"}


class OverridesError(Exception):
    pass


@dataclass(frozen=True)
class Overrides:
    """overrides.toml, canonicalized. ``pin_urls`` holds each pin's address, in ``pin``'s order."""

    alias: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    match: Mapping[str, tuple[str, str]] = field(default_factory=dict)
    artist_url: Mapping[str, str] = field(default_factory=dict)
    pin: Mapping[str, tuple[int, ...]] = field(default_factory=dict)
    transpose: Mapping[str, int] = field(default_factory=dict)
    ignore: frozenset[str] = frozenset()
    block: frozenset[int] = frozenset()
    pin_urls: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


def override_key(display: str) -> str:
    """The song identity for an "Artist - Title" key."""
    artist, sep, title = display.partition(" - ")
    if not sep or not artist.strip() or not title.strip():
        raise OverridesError(f"expected \"Artist - Title\", got {display!r}")
    return identity_key(artist.strip(), title.strip())


def tab_id_from_url(url: str | int) -> int:
    """The tab id of a UG tab page URL (``/tab/85053`` or ``/tab/a/b-chords-85053``)."""
    if isinstance(url, int) or (isinstance(url, str) and url.strip().isdigit()):
        return int(url)
    m = _TAB_URL.match(url.strip())
    if not m:
        raise OverridesError(f"not an Ultimate Guitar tab URL: {url!r}")
    return int(m.group(1))


def _pin_url(value: str) -> str:
    """A pinned page's address: the URL as pasted, over https and without a trailing slash;
    for a bare tab id, the bare ``/tab/{id}`` page. ``value`` passed ``tab_id_from_url``."""
    text = value.strip()
    if text.isdigit():
        return f"{_TAB_HOST}/tab/{int(text)}"
    return _TAB_HOST + urlsplit(text).path.rstrip("/")


def _ug_ref(value: Any, where: str) -> tuple[str, str]:
    if not isinstance(value, str) or value.count("/") != 1:
        raise OverridesError(f"[match] {where}: expected \"ug-artist/ug-song\", got {value!r}")
    artist, song = value.split("/")
    a, s = ug_slug_key(artist), ug_slug_key(song)
    if not a or not s:
        raise OverridesError(f"[match] {where}: expected \"ug-artist/ug-song\", got {value!r}")
    return a, s


def _strings(value: Any, where: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    raise OverridesError(f"{where}: expected a string or a list of strings")


def load_overrides(path: Path) -> Overrides:
    """Read overrides.toml; a missing file means no overrides."""
    if not path.is_file():
        return Overrides()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise OverridesError(f"{path}: {e}") from e
    unknown = sorted(set(data) - _TABLES)
    if unknown:
        raise OverridesError(f"{path}: unknown table(s): {', '.join(unknown)}")

    def table(name: str) -> Mapping[str, Any]:
        value = data.get(name, {})
        if not isinstance(value, Mapping):
            raise OverridesError(f"[{name}] must be a table")
        return value

    alias = {
        slug_key(artist): tuple(ug_slug_key(s) for s in _strings(v, f"[alias] {artist!r}"))
        for artist, v in table("alias").items()
    }
    match = {override_key(k): _ug_ref(v, repr(k)) for k, v in table("match").items()}

    artist_url: dict[str, str] = {}
    for artist, url in table("artist_url").items():
        if not isinstance(url, str) or not _ARTIST_URL.match(url.strip()):
            raise OverridesError(
                f"[artist_url] {artist!r}: expected https://www.ultimate-guitar.com/artist/<name>_<id>"
            )
        artist_url[slug_key(artist)] = url.strip().rstrip("/")

    pin: dict[str, tuple[int, ...]] = {}
    pin_urls: dict[str, tuple[str, ...]] = {}
    for k, v in table("pin").items():
        try:
            pasted = _strings(v, f"[pin] {k!r}")
            ident = override_key(k)
            pin[ident] = tuple(tab_id_from_url(u) for u in pasted)
            pin_urls[ident] = tuple(_pin_url(u) for u in pasted)
        except OverridesError as e:
            raise OverridesError(f"[pin] {k!r}: {e}") from e

    transpose: dict[str, int] = {}
    for k, v in table("transpose").items():
        if not isinstance(v, int) or isinstance(v, bool) or not -11 <= v <= 11:
            raise OverridesError(f"[transpose] {k!r}: expected semitones between -11 and 11")
        transpose[override_key(k)] = v

    ignore_t = table("ignore")
    ignore = frozenset(override_key(s) for s in _strings(ignore_t.get("songs", []), "[ignore] songs"))

    block_t = table("block")
    tab_ids = block_t.get("tab_ids", [])
    if not isinstance(tab_ids, list) or not all(isinstance(t, int) for t in tab_ids):
        raise OverridesError("[block] tab_ids must be a list of integers")

    return Overrides(
        alias=alias, match=match, artist_url=artist_url, pin=pin, transpose=transpose,
        ignore=ignore, block=frozenset(tab_ids), pin_urls=pin_urls,
    )


def _edit(path: Path, change) -> None:
    doc = tomlkit.parse(path.read_text(encoding="utf-8")) if path.is_file() else tomlkit.document()
    change(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(tomlkit.dumps(doc), encoding="utf-8")
    os.replace(tmp, path)


def _table_of(doc, name: str):
    if name not in doc:
        doc[name] = tomlkit.table()
    return doc[name]


def add_alias(path: Path, source_artist: str, ug_artist: str) -> None:
    _edit(path, lambda doc: _table_of(doc, "alias").__setitem__(source_artist, ug_artist))


def add_match(path: Path, display: str, ug_ref: str) -> None:
    override_key(display)
    _ug_ref(ug_ref, repr(display))
    _edit(path, lambda doc: _table_of(doc, "match").__setitem__(display, ug_ref))


def add_artist_url(path: Path, artist: str, url: str) -> None:
    if not _ARTIST_URL.match(url.strip()):
        raise OverridesError(f"[artist_url] {artist!r}: not a UG artist page URL: {url!r}")
    _edit(path, lambda doc: _table_of(doc, "artist_url").__setitem__(artist, url.strip()))


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
