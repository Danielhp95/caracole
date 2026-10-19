"""Fake Ultimate Guitar pages, built the way UG builds the real ones.

Every UG tab page and artist page is a React app whose data sits in a single
attribute::

    <div class="js-store" data-content="{&quot;store&quot;:{&quot;page&quot;:{...}}}"></div>

The JSON is compact UTF-8, and UG escapes it like PHP's
``htmlentities($json, ENT_QUOTES)``: ``"`` becomes ``&quot;``, ``'`` becomes
``&#039;``, ``&``, ``<`` and ``>`` become ``&amp;``, ``&lt;`` and ``&gt;``,
letters with an HTML 4 entity become named entities (``ú`` → ``&uacute;``),
and everything else, Chinese included, stays raw. ``escape_attr`` reproduces
UG's attribute byte for byte (checked on real pages captured on 2026-10-18).

Import from a test module (pytest puts ``tests/`` on ``sys.path``)::

    from helpers.ug_pages import make_artist_page_html, make_tab_page_html, version_dict

A tab page, as ``caracole.ug.page.parse_tab_page`` reads it::

    song = {"song": "De Música Ligera", "artist": "Soda Stereo"}
    tab = version_dict(85053, version=2, rating=4.54, votes=7, **song)
    others = [
        version_dict(85042, rating=4.83, votes=277, **song),
        version_dict(2528571, type="Official", **song),
    ]
    html = make_tab_page_html(
        tab, others,
        content="[Verse 1]\\r\\n[tab][ch]Bm[/ch]    [ch]G[/ch]\\r\\nla la la[/tab]",
        artist_url="https://www.ultimate-guitar.com/artist/soda_stereo_2946",
    )

Serve it to code under test with ``httpx.MockTransport``::

    pages = {"https://tabs.ultimate-guitar.com/tab/85053": html}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text=pages[str(req.url)]))

An artist page, as ``caracole.ug.artist.parse_artist_page`` reads it, for the URL
``artist_page_url("https://www.ultimate-guitar.com/artist/soda_stereo_2946", kind="chords")``::

    html = make_artist_page_html(2946, "Soda Stereo", [tab, *others], page=1, pages=1)

A page whose shape has drifted, which the parsers must report as
``PageParseError`` rather than as "no versions"::

    html = store_page_html({"tab": version_dict(1, type="Pro")})  # no tab_view

Shapes to keep in mind (they are UG's, not choices made here):

- A tab page's ``tab_view.versions`` leaves out the page's own tab, which is
  ``data.tab``; pass the page's tab as ``tab`` and only the *other* versions
  of the same type and part in ``versions``. UG includes the Official version.
- A Guitar Pro or Power Tab page has no ``wiki_tab.content`` (``content=None``)
  and carries the file's details in ``tab_view.meta``, e.g.
  ``{"fileExtension": ".gp5", "duration": 14}``. UG writes an empty meta as ``[]``.
- ``version_dict`` writes ``tab_url`` in its bare form,
  ``https://tabs.ultimate-guitar.com/tab/{id}`` (``caracole.ug.page.page_url``),
  so tests can route on it. On UG that is the ``tab_url`` of tabs without
  slugs; slugged tabs carry their slugged URL.
"""

from __future__ import annotations

import html
import json
import re
from html.entities import codepoint2name
from typing import Any

from caracole.normalize import fold

TAB_BASE = "https://tabs.ultimate-guitar.com/tab/"
WWW = "https://www.ultimate-guitar.com"

# UG's ``type`` → ``type_name``, as the real pages show them.
TYPE_NAMES = {
    "Chords": "Chords",
    "Tabs": "Tab",
    "Pro": "Guitar Pro",
    "Power": "Power",
    "Official": "Official",
    "Bass Tabs": "Bass",
    "Ukulele Chords": "Ukulele",
    "Drum Tabs": "Drums",
    "Video": "Video",
}

# The artist page's type filters, in UG's order: ``type`` → (display name, ``filter=`` value).
ARTIST_FILTERS = {
    "Official": ("official tab", "official"),
    "Chords": ("chords", "chords"),
    "Tabs": ("tab", "tabs"),
    "Pro": ("guitar pro tab", "guitar_pro"),
    "Power": ("power tab", "power"),
    "Bass Tabs": ("bass tab", "bass"),
    "Drum Tabs": ("drum tab", "drums"),
    "Video": ("video tab", "video"),
    "Ukulele Chords": ("ukulele chords", "ukulele"),
}


def escape_attr(text: str) -> str:
    """Escape text for ``data-content`` as UG does: PHP ``htmlentities`` with ``ENT_QUOTES``."""
    out = []
    for ch in text:
        if ch == "'":
            out.append("&#039;")
        elif (name := codepoint2name.get(ord(ch))) is not None:
            out.append(f"&{name};")
        else:
            out.append(ch)
    return "".join(out)


def store_page_html(data: dict[str, Any], *, title: str = "Ultimate-Guitar.Com") -> str:
    """A whole HTML page whose ``div.js-store`` holds ``{"store": {"page": {"data": data}}}``.

    Use it directly for pages with an unusual shape, such as a page missing
    ``tab_view``; ``make_tab_page_html`` and ``make_artist_page_html`` build on it.
    """
    store = {"store": {"page": {"data": data}}}
    payload = escape_attr(json.dumps(store, ensure_ascii=False, separators=(",", ":")))
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '    <meta content="text/html; charset=utf-8" http-equiv="Content-Type">\n'
        f"    <title>{html.escape(title, quote=False)}</title>\n"
        "</head>\n"
        "<body>\n"
        '    <div class="js-page js-global-wrapper ug-page">\n'
        "        </div>\n\n"
        f'    <div class="js-store" data-content="{payload}"></div>\n'
        "</body>\n"
        "</html>\n"
    )


def version_dict(
    tab_id: int,
    *,
    type: str = "Chords",
    version: int = 1,
    rating: float | None = 4.5,
    votes: int | None = 10,
    part: str = "",
    access: str = "public",
    song: str = "Song",
    artist: str = "Artist",
    is_acoustic: bool = False,
    song_id: int = 1,
    **extra: Any,
) -> dict[str, Any]:
    """One tab as UG lists it: ``data.tab``, an entry of ``tab_view.versions`` or of ``other_tabs``.

    ``type`` is UG's type: ``Chords``, ``Tabs``, ``Pro`` (a public Guitar Pro
    file), ``Power``, ``Official``, ``Bass Tabs``, ``Ukulele Chords``,
    ``Drum Tabs`` or ``Video``. ``access`` becomes ``tab_access_type``.
    ``rating=None`` and ``votes=None`` write JSON nulls, as UG sometimes does.
    ``extra`` adds or replaces raw keys, e.g. ``artist_url=...`` or
    ``version_description="Capo 2"``.
    """
    d: dict[str, Any] = {
        "id": tab_id,
        "song_id": song_id,
        "song_name": song,
        "artist_id": 1,
        "artist_name": artist,
        "type": type,
        "part": part,
        "version": version,
        "votes": votes,
        "rating": rating,
        "date": "1700000000",
        "status": "approved",
        "tab_access_type": access,
        "version_description": None,
        "recording": {
            "is_acoustic": int(is_acoustic),
            "tonality_name": "",
            "performance": None,
            "recording_artists": [],
            "video_urls": None,
            "album_id": 0,
        },
        "tab_url": f"{TAB_BASE}{tab_id}",
        "type_name": TYPE_NAMES.get(type, type),
    }
    d.update(extra)
    return d


def make_tab_page_html(
    tab: dict[str, Any],
    versions: list[dict[str, Any]],
    *,
    content: str | None = None,
    meta: dict[str, Any] | None = None,
    artist_url: str | None = None,
) -> str:
    """A tab page: ``tab`` is the page's own tab, ``versions`` the other versions UG lists.

    ``content`` is the sheet in UG markup (``[ch]G[/ch]``, ``[tab]…[/tab]``);
    leave it None for a Guitar Pro or Power Tab page, which has none. ``meta``
    is ``tab_view.meta``; None writes UG's empty ``[]``. ``artist_url`` sets
    ``data.tab.artist_url``, such as ``https://www.ultimate-guitar.com/artist/soda_stereo_2946``,
    which is how caracole learns an artist page's address.
    """
    tab = dict(tab)
    if artist_url is not None:
        tab["artist_url"] = artist_url
    wiki_tab: dict[str, Any] = {"revision_id": 1, "date": 1700000000}
    if content is not None:
        wiki_tab = {"content": content, **wiki_tab}
    data = {
        "tab": tab,
        "tab_view": {
            "versions": list(versions),
            "wiki_tab": wiki_tab,
            "meta": meta if meta is not None else [],
        },
    }
    song = str(tab.get("song_name", "")).upper()
    kind = str(tab.get("type_name") or tab.get("type") or "").upper()
    title = f"{song} {kind} by {tab.get('artist_name', '')} @ Ultimate-Guitar.Com"
    return store_page_html(data, title=title)


def name_stripped(name: str) -> str:
    """UG's ``name_stripped`` of an artist: "Soda Stereo" → ``soda_stereo``."""
    return re.sub(r"[\W_]+", "_", fold(name)).strip("_")


def artist_path(artist_id: int, name: str) -> str:
    """The path of an artist page as UG writes it: ``/artist/soda_stereo_2946``."""
    return f"/artist/{name_stripped(name)}_{artist_id}"


def make_artist_page_html(
    artist_id: int,
    name: str,
    tabs: list[dict[str, Any]],
    *,
    page: int = 1,
    pages: int = 1,
    path: str | None = None,
    stripped: str | None = None,
    types: list[str] | None = None,
) -> str:
    """One page of an artist's tab list: ``tabs`` become ``data.other_tabs``, in the order given.

    Build the tabs with ``version_dict``. UG mixes in links to its paid "Pro"
    app as entries without a ``type`` key; append raw dicts such as
    ``{"id": 1806686, "song_name": "X", "marketing_type": "TabPro", "rating": 4.8, "votes": 21}``
    to test that they are skipped. ``page`` and ``pages`` fill ``data.pagination``,
    and ``data.filters.types`` lists ``all`` plus one filter per type present in ``tabs``,
    or per UG type in ``types``: a filtered list's bar still offers every type the artist has.

    ``path`` is the page's own path, which every link on it uses: by default
    ``artist_path`` (``/artist/soda_stereo_2946``). UG addresses some artists by
    their number alone, as ``/artist/634073`` (Song Dongye (宋冬野), checked live):
    pass that ``path``, and ``stripped`` for ``name_stripped`` (by default made
    from ``name``).
    """
    path = path or artist_path(artist_id, name)
    stripped = name_stripped(name) if stripped is None else stripped
    typed = [t for t in tabs if "type" in t]
    filters = [{"name": "all", "url": path, "count": len(typed)}]
    for ug_type, (label, value) in ARTIST_FILTERS.items():
        count = sum(1 for t in typed if t["type"] == ug_type)
        if count or (types is not None and ug_type in types):
            filters.append({"name": label, "url": f"{path}?filter={value}", "count": count})
    data = {
        "artist": {"id": artist_id, "name": name, "name_stripped": stripped},
        "other_tabs": list(tabs),
        "current_page": page,
        "pagination": {
            "pages": [
                {"page": n, "url": path if n == 1 else f"{path}?page={n}"}
                for n in range(1, pages + 1)
            ],
            "current": page,
        },
        "filters": {"types": filters, "current_filters": {"types": "new_tab_type"}},
    }
    return store_page_html(
        data, title=f"{name} Chords & Tabs for Guitar, Ukulele, Bass, Drums at Ultimate-Guitar"
    )


# --- the live case: 宋冬野 - 斑马斑马 ------------------------------------------------------------
#
# What two polite requests through caracole's own client read from UG on 2026-10-19: the tab page
# /tab/4180894 and the artist page /artist/634073?filter=chords. The fakes below keep their JSON
# fields and values. UG names the song and the artist in two scripts, links every tab of the artist
# as a bare /tab/<id>, and addresses the artist page by its number alone. Ratings, votes, the tabs
# list and every sheet line are made up: none of the song's lyrics are in the repository.

SONG_DONGYE_ID = 634073
SONG_DONGYE = "Song Dongye (宋冬野)"
SONG_DONGYE_URL = f"{WWW}/artist/{SONG_DONGYE_ID}"
BANMA_UG = "斑马 斑马 Banma Banma Zebra Zebra"
# 宋冬野's chords list, in UG's order: (tab id, song_name, version).
SONG_DONGYE_CHORDS = (
    (6613886, "与我交谈 Speak With Me", 1),
    (4180894, BANMA_UG, 1),
    (4689017, BANMA_UG, 2),
    (4041916, "莉莉安 Lilian", 1),
    (3016223, "董小姐", 1),
    (3204647, "董小姐", 2),
    (3392735, "郭源潮", 1),
)
# Made-up lines, in Traditional characters as the live sheet (and LRCLIB's records) write them.
BANMA_TRADITIONAL_LINES = ("河邊的小路通向遠方", "我在窗前數星星", "秋天的風吹過山崗",
                           "舊信封裡有一個夏天", "火車開往沒有名字的城", "燈光照亮回家的橋")
DONG_XIAOJIE_LINES = ("黃昏的站台空無一人", "她把吉他放在窗邊", "風裡還有昨天的歌",
                      "我們在沙漠裡等雨", "誰也沒有說再見")


def song_dongye_tab(tab_id: int, song: str, *, version: int = 1, type: str = "Chords",
                    **extra: Any) -> dict[str, Any]:
    """A tab of 宋冬野's as UG lists it: names in two scripts, at the bare /tab/{id}, of artist 634073."""
    extra.setdefault("artist_url", SONG_DONGYE_URL)
    return version_dict(tab_id, type=type, version=version, song=song, artist=SONG_DONGYE,
                        artist_id=SONG_DONGYE_ID, **extra)


def song_dongye_chords(**ratings: tuple[float, int]) -> list[dict[str, Any]]:
    """宋冬野's chords list as UG showed it; ``ratings`` give a tab (``t4180894=(4.8, 120)``) a rating
    and a vote count."""
    return [song_dongye_tab(t, song, version=n, **_rated(ratings.get(f"t{t}")))
            for t, song, n in SONG_DONGYE_CHORDS]


def _rated(rating: tuple[float, int] | None) -> dict[str, Any]:
    return {} if rating is None else {"rating": rating[0], "votes": rating[1]}


def song_dongye_page_html(tabs: list[dict[str, Any]]) -> str:
    """One list of 宋冬野's artist page, at /artist/634073: one page, with filters for chords and tabs."""
    return make_artist_page_html(SONG_DONGYE_ID, SONG_DONGYE, tabs, path=f"/artist/{SONG_DONGYE_ID}",
                                 stripped="", types=["Chords", "Tabs"])


def song_dongye_sheet(lines: tuple[str, ...]) -> str:
    """A chords-over-lyrics sheet in UG markup, laid out as the live one: chords, then a line."""
    return "\n".join(f"[tab][ch]C[/ch] [ch]D[/ch] [ch]Bm[/ch] [ch]Em[/ch]\n{line}[/tab]" for line in lines)
