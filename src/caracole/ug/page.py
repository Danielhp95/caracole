"""Ultimate Guitar tab pages, read from the JSON that UG embeds in them.

Every page keeps its data in ``div.js-store[data-content]``, under
``store.page.data``:

- ``data.tab`` is the page's own tab;
- ``data.tab_view.versions`` lists the song's other versions of the same type
  and part. The page's own tab is not among them; UG's Official version is;
- ``data.tab_view.wiki_tab.content`` is the sheet in UG markup. A page of a type
  caracole doesn't use, a Guitar Pro or Power Tab file's, has none;
- ``data.tab_view.meta`` is what UG says of the tab beside it (a sheet's capo, say).
  UG writes an empty one as ``[]``.

A page that can't be read raises ``PageParseError``, which is a provider
error: callers must never take it to mean "this song has no versions".
"""

from __future__ import annotations


import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from html import unescape
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from caracole.http import ProviderError

TAB_BASE_URL = "https://tabs.ultimate-guitar.com/tab/"

# UG's tab types that caracole uses: its chords, for the sheet, and its text tabs. Everything else (Pro and
# Power, a Guitar Pro or Power Tab file, which caracole never picks there; Official, Bass Tabs, Ukulele Chords,
# Drum Tabs, Video…) has no kind, and every page of a kind carries its text.
_KINDS = {"chords": "chords", "tabs": "tabs"}
KINDS = tuple(_KINDS.values())  # caracole's kinds of UG's tabs: chords, tabs
_MARKUP = re.compile(r"\[/?(?:ch|tab)\]")


class PageParseError(ProviderError):
    """A UG page whose embedded data can't be read: a provider error, never a miss."""


def kind_of(ug_type: str | None) -> str | None:
    """caracole's kind for a UG tab type.

    Chords → chords, Tabs → tabs. Any other type has no kind (None): ``Official``,
    and ``Pro`` and ``Power``, a Guitar Pro or Power Tab file, which caracole
    doesn't use (gtptabs.com's files are downloaded for you, gtptabs_fetch.py, and
    you file your own from the inbox, inbox.py).
    """
    if not isinstance(ug_type, str):
        return None
    return _KINDS.get(ug_type.strip().lower())


@dataclass(frozen=True)
class UGVersion:
    """One version of a song, as a tab page, a versions list or an artist page lists it.

    ``access`` is UG's ``tab_access_type`` (only ``public`` is usable), ``url``
    its ``tab_url``, ``description`` its ``version_description``. A null rating
    or vote count is 0. ``raw`` is UG's dict, unchanged.
    """

    tab_id: int
    song_id: int | None
    song_name: str
    artist_name: str
    type: str
    part: str
    version: int
    rating: float
    votes: int
    access: str
    url: str
    description: str | None
    is_acoustic: bool
    raw: Mapping[str, Any] = field(repr=False, compare=False)

    @property
    def kind(self) -> str | None:
        """chords or tabs; None for every type caracole doesn't use."""
        return kind_of(self.type)

    @property
    def label(self) -> str | None:
        """The part ("intro", "solo"…), else "acoustic" for an acoustic recording, else None."""
        part = self.part.strip().lower()
        if part:
            return part
        return "acoustic" if self.is_acoustic else None


@dataclass(frozen=True)
class UGTabPage:
    """A parsed tab page: its own tab, the other versions UG lists, and the sheet text.

    ``content`` is ``wiki_tab.content`` in UG markup, or None on the page of a
    type caracole doesn't use. ``meta`` is ``tab_view.meta`` ({} when empty). ``raw`` is
    ``store.page.data``. ``artist_url`` is the artist page UG links the tab to.
    """

    tab: UGVersion
    versions: tuple[UGVersion, ...]
    content: str | None
    meta: Mapping[str, Any]
    raw: Mapping[str, Any] = field(repr=False, compare=False)
    artist_url: str | None = None


def page_url(tab_id: int, path: str | None = None) -> str:
    """The URL of a tab page.

    With the sitemap ``path`` (``artist/song-type-id``) it is the slugged URL,
    which is the only one UG serves for slugged tabs: the bare ``/tab/{id}``
    answers 404 for them (checked live on 1081462). Without a path it is the
    bare URL, which is what UG lists for tabs that have no slugs.
    """
    if path:
        return f"https://tabs.ultimate-guitar.com/tab/{path.lstrip('/')}"
    return f"https://tabs.ultimate-guitar.com/tab/{tab_id}"



def strip_markup(content: str) -> str:
    """The sheet as plain text: UG's ``[ch]``, ``[/ch]``, ``[tab]`` and ``[/tab]`` tags removed."""
    return _MARKUP.sub("", content)


def _number(value: Any) -> float | None:
    """A number from UG's JSON, which writes numbers, digit strings or null."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def json_int(value: Any) -> int | None:
    """A whole number from UG's JSON (a number or a digit string), else None."""
    n = _number(value)
    return int(n) if n is not None and n.is_integer() else None


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def parse_version(d: Any) -> UGVersion | None:
    """A ``UGVersion`` from one of UG's tab dicts, or None when it isn't a usable tab.

    A usable tab has a ``type`` and a whole-number ``id``. Artist pages mix in
    links to UG's paid app as entries without a ``type``; they are not tabs.
    """
    if not isinstance(d, Mapping) or not d.get("type"):
        return None
    tab_id = json_int(d.get("id"))
    if tab_id is None:
        return None
    recording = d.get("recording")
    acoustic = recording.get("is_acoustic") if isinstance(recording, Mapping) else None
    return UGVersion(
        tab_id=tab_id,
        song_id=json_int(d.get("song_id")),
        song_name=_text(d.get("song_name")),
        artist_name=_text(d.get("artist_name")),
        type=_text(d.get("type")),
        part=_text(d.get("part")),
        version=json_int(d.get("version")) or 0,
        rating=_number(d.get("rating")) or 0.0,
        votes=json_int(d.get("votes")) or 0,
        access=_text(d.get("tab_access_type")),
        url=_text(d.get("tab_url")) or page_url(tab_id),
        description=_text(d.get("version_description")) or None,
        is_acoustic=bool(_number(acoustic)),
        raw=d,
    )


def read_page_data(html: str | bytes, *, url: str | None = None) -> dict[str, Any]:
    """The ``store.page.data`` object of any UG page, or ``PageParseError``."""
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    node = LexborHTMLParser(html).css_first("div.js-store")
    payload = node.attributes.get("data-content") if node is not None else None
    if not payload:
        raise PageParseError("ug", url, None, "no div.js-store data on the page")
    try:
        store = json.loads(payload)
    except (ValueError, RecursionError) as e:  # or nested deeper than the parser goes
        raise PageParseError("ug", url, None, f"js-store is not valid JSON: {e}") from e
    data = store
    for key in ("store", "page", "data"):
        data = data.get(key) if isinstance(data, dict) else None
    if not isinstance(data, dict):
        raise PageParseError("ug", url, None, "js-store has no store.page.data")
    return data


def read_versions(
    data: Mapping[str, Any], key: str, *, url: str | None = None
) -> tuple[UGVersion, ...]:
    """The usable tabs in the list ``data[key]``.

    A missing key or a value that isn't a list is a ``PageParseError``; null is
    no tabs. Entries that aren't usable tabs (see ``parse_version``) are skipped.
    """
    if key not in data:
        raise PageParseError("ug", url, None, f"no {key} on the page")
    items = data[key]
    if items is None:
        return ()
    if not isinstance(items, list):
        raise PageParseError("ug", url, None, f"{key} is not a list")
    return tuple(v for v in map(parse_version, items) if v is not None)


_ENTITY = re.compile(r"&(#\d+|#x[0-9a-f]+|[a-z]+);", re.I)


def decode_twice(text: str) -> str:
    """Decode HTML entities, and once more when the result still holds one.

    UG escapes a sheet's text inside its JSON ("&amp;"), and some sheets were escaped twice
    on its side ("&amp;amp;feature"). A sheet kept before this pass still holds either."""
    text = unescape(text)
    return unescape(text) if _ENTITY.search(text) else text


def parse_tab_page(html: str | bytes, *, url: str | None = None) -> UGTabPage:
    """Parse a tab page. ``url`` is only used in error messages."""
    data = read_page_data(html, url=url)
    tab = parse_version(data.get("tab"))
    if tab is None:
        raise PageParseError("ug", url, None, "no usable data.tab")
    view = data.get("tab_view")
    if not isinstance(view, dict):
        raise PageParseError("ug", url, None, "no data.tab_view")
    versions = read_versions(view, "versions", url=url)
    wiki = view.get("wiki_tab")
    content = wiki.get("content") if isinstance(wiki, dict) else None
    if not isinstance(content, str):
        content = None
        if tab.kind is not None:
            raise PageParseError("ug", url, None, f"{tab.type} page without wiki_tab.content")
    else:
        # UG keeps the sheet text HTML-escaped inside its JSON ("&amp;"), on top of the
        # attribute's own escaping, so it needs one more decoding pass (two for some).
        content = decode_twice(content)
    meta = view.get("meta")
    return UGTabPage(
        tab=tab,
        versions=versions,
        content=content,
        meta=meta if isinstance(meta, dict) else {},
        raw=data,
        artist_url=_text(tab.raw.get("artist_url")) or None,
    )
