"""gametabs.net for the phone: what gametabs.py's parsers and gametabs_fetch.py's rules answer, and a lookup's pass
replayed, written for the Kotlin port's core.sites (``GameTabsPages``, ``GameTabsFetch``) to agree with
(docs/superpowers/plans/2026-11-03-android-port-m4-m6.md, lane gametabs).

A body is ``{"fixture": …}``, a file of tests/fixtures/, or ``{"text": …}``: the page as the pass hands it to the
parser, its bytes (read as UTF-8, a byte that isn't replaced). A tab page read is ``plain(GameTab)`` with ``raw``, what
a kept tab's version records of it (``GameTab.raw()``, its twelve fields in its order); a game page read
``plain(GamePage)``. A parser that raises is ``err``: ``"GameTabsParseError: <its words>"``, or Python's own
(``"ValueError: …"``, ``"OverflowError: …"``) where gametabs.py lets one through.

**Vectors**:

- sites/gametabs.jsonl:
  - ``caracole.gametabs.parse_tab_page`` and ``parse_game_page`` records, ``args`` the body and ``kw.url``, over
    tests/fixtures/gametabs, the pages helpers/gametabs_site.py makes, and an edge set (the ``data-tab`` JSON's values
    of every type, the microdata and the heading's details where it says nothing, a card's spans, the views'
    abbreviations, the page selector's numbers);
  - batches, ``args`` ``[inputs]`` and ``out`` the answer to each in turn: ``title_key`` (titles), ``game_forms``
    (names), ``song_forms`` (each input ``[artists, artist]``, the forms sorted) and ``fits`` (each input ``[[artists,
    artist, title], {title, game, composers, game_slug}]``).
- lookup/gametabs.jsonl: ``caracole.gametabs_fetch.gametabs_tabs`` scenario records (tests/helpers/scenario.py),
  ``kw`` ``{"only": [song id]}``, as a lookup asks (``refresh_index=False``): the index (gametabs_index from the
  fixture sitemaps, the game pages read into gametabs_games and gametabs_game_tabs) in the record's database, the
  overrides as ``phone_overrides`` rows (``[gametabs]``, ``ignore``), and ``agent``, the user agent every request
  carried (config.DEFAULT_USER_AGENT). ``out.result`` is the pass's stats: its fields by Python's names, ``failures``
  each ``[song key, error type, error words]``.

Stamps: songs.py's clock is the record's ``now`` while a world is made. library.keep_file stamps ``created_at`` with
SQLite's clock, which no record can fix: a ``files`` row a pass wrote is checked to hold a time of that form now, then
recorded as the record's ``now``, the time the phone's ``Kept.keepFile`` is given. ``write_info`` (info.json) is the
viewer's, milestone 5's: no pass writes it here, as the phone writes none.

Regenerate with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import base64
import html as htmllib
import json
import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

from helpers.corpus import VECTORS, check, fixture_bytes, fixture_ref, jsonl, phone_schema, plain
from helpers.gametabs_site import game_page, tab_page
from helpers.scenario import record

from caracole import config
from caracole.gametabs import (
    BASE_URL,
    GameTabsParseError,
    parse_game_page,
    parse_page_url,
    parse_tab_page,
    title_key,
)
from caracole.gametabs_fetch import fits, game_forms, song_forms

MADE_BY = "tests/test_conformance_gametabs.py"
SITES = VECTORS / "sites" / "gametabs.jsonl"
LOOKUP = VECTORS / "lookup" / "gametabs.jsonl"
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
STAMP = "2026-11-03T12:00:00Z"
STAMP_SHAPE = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
ADDED = "2026-10-01T00:00:00Z"
FILLMORE = f"{BASE_URL}/tabs/actraiser/fillmore"
RESTING = f"{BASE_URL}/tabs/hollow-knight/resting-grounds-2"
FIRST = f"{BASE_URL}/tabs/hollow-knight/resting-grounds"
HTML = [["content-type", "text/html; charset=utf-8"]]
NOT_FOUND = "<html><body>Not found</body></html>"


def fixture(name: str) -> dict[str, str]:
    return fixture_ref(f"gametabs/{name}")


def text_of(given: dict[str, str]) -> bytes:
    if "fixture" in given:
        return fixture_bytes(given)
    if "base64" in given:
        return base64.b64decode(given["base64"])
    return given["text"].encode("utf-8")


def body(page: str | dict[str, str]) -> dict[str, str]:
    return page if isinstance(page, dict) else {"text": page}


# --- the parsers ---------------------------------------------------------------------------------------------------


def _tab(tab) -> dict[str, Any]:
    return plain(tab) | {"raw": plain(tab.raw())}


def parsed(fn: str, case: str, page: str | dict[str, str], url: str | None = None) -> dict[str, Any]:
    """A parser's record: what it made of the page, or its error's words."""
    given = body(page)
    rec: dict[str, Any] = {"fn": f"caracole.gametabs.{fn}", "case": case, "args": [given], "kw": {"url": url}}
    try:
        if fn == "parse_tab_page":
            rec["out"] = _tab(parse_tab_page(text_of(given), url))
        else:
            rec["out"] = plain(parse_game_page(text_of(given), url))
    except GameTabsParseError as e:
        rec["err"] = f"GameTabsParseError: {e}"
    except (ValueError, OverflowError) as e:  # Python's own, which gametabs.py lets through
        rec["err"] = f"{type(e).__name__}: {e}"
    return rec


def data_attr(data: Any) -> str:
    return htmllib.escape(data if isinstance(data, str) else json.dumps(data), quote=True)


def tab_html(*, data: Any = None, work: tuple[str, list[str]] | None = None, album: tuple[str, str | None] | None = None,
             h1: str | None = None, details: list[str] = (), pre: str | None = "e|--0--|\n", doctype: bool = True,
             wrapper: str = 'id="tab-page-wrapper"') -> str:
    """A tab page of the captured one's shape, small: its ``data-tab`` (JSON, or a text as it is), its microdata
    (``work``: the track's name and composers; ``album``: the game's name and page), its heading, its details' lines
    and its ``<pre>`` (None: none)."""
    attr = f' data-tab="{data_attr(data)}"' if data is not None else ""
    parts = [f"<div {wrapper}{attr}>", '<div style="display: none">']
    if work is not None:
        name, composers = work
        parts.append(f'<span itemprop="recordingOf"><meta itemprop="name" content="{htmllib.escape(name)}">')
        parts += [f'<span itemprop="composer"><meta itemprop="name" content="{htmllib.escape(c)}"></span>'
                  for c in composers]
        parts.append("</span>")
    if album is not None:
        name, href = album
        parts.append(f'<span itemprop="inAlbum"><meta itemprop="name" content="{htmllib.escape(name)}">')
        if href is not None:
            parts.append(f'<link itemprop="url" href="{htmllib.escape(href)}">')
        parts.append("</span>")
    parts.append("</div>")
    if h1 is not None:
        parts.append(f'<h1 id="tab-page-tab-name">{h1}</h1>')
    if details:
        parts.append('<div class="tab-page-grid-details"><div>' + "".join(f"<p>{d}</p>" for d in details)
                     + "</div></div>")
    if pre is not None:
        parts.append(f'<pre id="tab-text-view-text">{pre}</pre>')
    parts.append("</div>")
    head = "<!DOCTYPE html>" if doctype else ""
    return f"{head}<html><body>{''.join(parts)}</body></html>"


DATA = {"user": {"display_username": "Tabber"}, "game": {"slug": "some-game", "name": "Some Game"},
        "instruments": [{"name": "Guitar"}], "styles": [{"name": "Transcription"}],
        "composers": [{"name": "A Composer"}], "views": 100, "id": 7, "name": "Some Title", "slug": "some-title",
        "created_at": "2020-01-02T03:04:05Z", "average_fun_rating": 4.5, "num_ratings_fun": 3}


def data(**changes: Any) -> dict[str, Any]:
    """DATA with ``changes``; a change of ``...`` drops that member."""
    out = dict(DATA)
    for k, v in changes.items():
        if v is ...:
            out.pop(k, None)
        else:
            out[k] = v
    return out


def tab_records() -> list[dict[str, Any]]:
    p = "parse_tab_page"
    made = tab_page("Hollow Knight", "Dirtmouth", composers=("Christopher Larkin",), instruments=("Guitar", "Bass"),
                    views=1234, body="E|--3--|\n")
    whole = fixture("tab_actraiser_fillmore.html")
    page = text_of(whole).decode("utf-8")
    start = page.index('data-tab="')
    no_data = page[:start] + page[page.index('"', start + len('data-tab="')) + 1:]
    records = [
        parsed(p, "Fillmore, as captured", whole, FILLMORE),
        parsed(p, "Fillmore, with no url", whole),
        parsed(p, "Resting Grounds 2, as captured", fixture("tab_hollow-knight_resting-grounds-2.html"), RESTING),
        parsed(p, "Resting Grounds 2, with no url", fixture("tab_hollow-knight_resting-grounds-2.html")),
        parsed(p, "a page made from Fillmore's", made, f"{BASE_URL}/tabs/hollow-knight/dirtmouth"),
        parsed(p, "a page made with no composer, and no rating", tab_page("Celeste", "Resurrections", composers=(),
                                                                          rating=None, views=0)),
        parsed(p, "Fillmore without its data: its microdata", no_data, FILLMORE),
        parsed(p, "no tab on the page", "<html><body><h1>Not found</h1></body></html>"),
        parsed(p, "an empty tab", tab_page("Actraiser", "Fillmore", body="")),
        parsed(p, "a tab of blank lines alone", tab_html(data=DATA, pre="\n  \n\t\n")),
        parsed(p, "the tab's newlines around it trimmed to one at its end",
               tab_html(data=DATA, pre="\n\n\n  e|--0--|\n\n\n")),
        parsed(p, "the tab's markup and entities: its text", tab_html(
            data=DATA, pre='<span class="tab-print-break">Title &amp; co\n</span>e|--<b>0</b>--|&lt;x&gt;\r\nB|--|')),
        parsed(p, "a tab whose text has no newline at its end", tab_html(data=DATA, pre="e|--0--|")),
        parsed(p, "no title nor game anywhere", tab_html(data={"views": 3})),
        parsed(p, "a title and no game", tab_html(data={"name": "X"})),
        parsed(p, "a game and no title", tab_html(data={"game": {"name": "G"}})),
        parsed(p, "the title from the heading", tab_html(data={"game": {"name": "G"}}, h1="  The \n Title  ")),
        parsed(p, "the title from the work's name before the heading",
               tab_html(data={"game": {"name": "G"}}, work=("Work Name", []), h1="Heading")),
        parsed(p, "the game from the album's name", tab_html(data={"name": "X"}, album=("Album  Game", None))),
        parsed(p, "the game's slug from the album's link", tab_html(
            data={"name": "X"}, album=("G", "https://gametabs.net/tabs/the-game/"))),
        parsed(p, "the game's slug from the link with no slash", tab_html(
            data={"name": "X"}, album=("G", "the-game")), f"{BASE_URL}/tabs/other/x"),
        parsed(p, "the game's slug from the url", tab_html(data={"name": "X", "game": {"name": "G"}}),
               f"{BASE_URL}/tabs/from-url/the-tab"),
        parsed(p, "a url with www and a slash at its end", tab_html(data={"name": "X", "game": {"name": "G"}}),
               "https://www.gametabs.net/tabs/from-url/the-tab/"),
        parsed(p, "a url that is no tab's", tab_html(data={"name": "X", "game": {"name": "G"}}),
               f"{BASE_URL}/tabs/from-url"),
        parsed(p, "a url in capitals is no tab's", tab_html(data={"name": "X", "game": {"name": "G"}}),
               f"{BASE_URL}/tabs/From-Url/The-Tab"),
        parsed(p, "an underscore in a url's slug", tab_html(data={"name": "X", "game": {"name": "G"}}),
               f"{BASE_URL}/tabs/exec_chronicle_key/a_b"),
        parsed(p, "the composers from the microdata", tab_html(
            data=data(composers=...), work=("Some Title", ["  One ", "", "Two  Names"]))),
        parsed(p, "the details' instruments and styles", tab_html(
            data=data(instruments=[], styles=...), details=[
                "Platform: SNES", "Instrument:\n <a>Guitar</a>, <a> Bass </a>,, ", "Style: Fingerstyle",
                "Tuning:\n <a>D#ADGBE</a>", "no colon here", "TUNING : Drop D : low", "Tuning:"])),
        parsed(p, "a tuning of nothing is none", tab_html(data=DATA, details=["Tuning:   "])),
        parsed(p, "the data-tab that won't parse: the microdata", tab_html(
            data="{not json", work=("Work", ["C"]), album=("Game", "https://gametabs.net/tabs/game"))),
        parsed(p, "a data-tab that is a list", tab_html(data=[1, 2], work=("Work", []), album=("Game", None))),
        parsed(p, "a data-tab of an empty text", tab_html(data="", work=("Work", []), album=("Game", None))),
        parsed(p, "a data-tab with a duplicate member: its last value", tab_html(
            data='{"name": "First", "game": {"name": "G"}, "name": "Last"}')),
        parsed(p, "a data-tab of NaN and Infinity", tab_html(
            data='{"name": "T", "game": {"name": "G"}, "views": Infinity, "average_fun_rating": NaN, '
                 '"num_ratings_fun": -Infinity}')),
        parsed(p, "spaces in the names collapsed", tab_html(data=data(
            name="  Some \n\t Title ", game={"name": " Some\u3000Game ", "slug": "s"},
            user={"display_username": "  A  B "}, composers=[{"name": " C  D "}, {"name": "   "}, {"x": 1}, "E", 3]))),
    ]
    values: list[tuple[str, dict[str, Any]]] = [
        ("a title of a number", {"name": 12}),
        ("a title of a float", {"name": 1.5}),
        ("a title of true", {"name": True}),
        ("a title of false: none", {"name": False}),
        ("a title of 0: none", {"name": 0}),
        ("a title of a list", {"name": ["a", 'b"c']}),
        ("a title of an object", {"name": {"k": "v", "n": None}}),
        ("a title of null: none", {"name": None}),
        ("a game that isn't an object", {"game": "Some Game"}),
        ("a game slug of a number", {"game": {"name": "G", "slug": 12}}),
        ("a game slug empty: the album's", {"game": {"name": "G", "slug": ""}}),
        ("an id of true is none", {"id": True}),
        ("an id of a float is none", {"id": 7.0}),
        ("an id of a string is none", {"id": "7"}),
        ("a big id", {"id": 123456789012345678901234567890}),
        ("a negative id", {"id": -3}),
        ("views of a float, truncated", {"views": 12.9}),
        ("views negative: none", {"views": -5}),
        ("views of minus zero", {"views": -0.0}),
        ("views of a string: none", {"views": "100"}),
        ("views of true: none", {"views": True}),
        ("views past a long", {"views": 1e19}),
        ("views of a huge float", {"views": 1.5e300}),
        ("views of an int too large for a float", {"views": 10 ** 400}),
        ("views of an int as large as a float", {"views": 2 ** 1000}),
        ("a rating of an int", {"average_fun_rating": 4}),
        ("a rating of a string: none", {"average_fun_rating": "4.5"}),
        ("a rating of false: none", {"average_fun_rating": False}),
        ("a rating of zero", {"average_fun_rating": 0}),
        ("ratings of a float", {"num_ratings_fun": 2.7}),
        ("ratings negative", {"num_ratings_fun": -1}),
        ("no user", {"user": ...}),
        ("a user that isn't an object", {"user": ["x"]}),
        ("a user's name of a number", {"user": {"display_username": 42}}),
        ("a user's name empty", {"user": {"display_username": ""}}),
        ("created of a number: none", {"created_at": 2020}),
        ("created empty: kept", {"created_at": ""}),
        ("no slug: the url's", {"slug": ...}),
        ("a slug of a number", {"slug": 5}),
        ("instruments that aren't a list", {"instruments": "Guitar"}),
        ("instruments of objects with no name", {"instruments": [{}, {"name": None}, {"name": "Bass"}]}),
        ("styles of a number's name", {"styles": [{"name": 3}, {"name": 0}, {"name": True}]}),
    ]
    for case, change in values:
        records.append(parsed(p, case, tab_html(data=data(**change), album=("Album Game", "https://gametabs.net/tabs/ag"),
                                                details=["Instrument: Ukulele", "Style: Arrangement"]),
                              f"{BASE_URL}/tabs/url-game/url-tab"))
    records += [
        parsed(p, "the wrapper's id in capitals, in quirks mode", tab_html(
            data=DATA, doctype=False, wrapper='id="TAB-PAGE-WRAPPER"')),
        parsed(p, "the wrapper's id in capitals, in standards mode", tab_html(
            data=DATA, doctype=True, wrapper='id="TAB-PAGE-WRAPPER"')),
        parsed(p, "no wrapper: the heading alone", tab_html(data=DATA, wrapper='id="elsewhere"', h1="Heading")),
        parsed(p, "a byte that isn't UTF-8", {"base64": base64.b64encode(
            tab_html(data=DATA, pre="caf\u00e9 e|--|").encode("utf-8").replace(b"caf\xc3\xa9", b"caf\xe9")).decode()}),
    ]
    return records


def card(path: str, title: str | None, spans: list[str], right: list[str] = (), *, first: str | None = None,
         left: bool = True) -> str:
    """A game page's card: its link, its title, its left spans (the first the card's name: ``first``, else the
    title) and its right column."""
    attr = f' title="{htmllib.escape(title)}"' if title is not None else ""
    inner = "".join(spans)
    name = f"<span>{htmllib.escape(first if first is not None else (title or ''))}</span>"
    left_div = f'<div class="split-row-left">{name}{inner}</div>' if left else f"<div>{name}{inner}</div>"
    return (f'<a href="{path}"{attr}><div class="results-list-item card split-row">{left_div}'
            f'<div class="split-row-right">{"".join(right)}</div></div></a>')


def game_html(name: str | None, cards: list[str], *, said: str | None = None, pages: list[str] = (),
              vocabulary: Any = None, wrapper: bool = True) -> str:
    dialog = (f'<div id="shuffle-dialog" data-prepopulated-instruments="{data_attr(vocabulary)}"></div>'
              if vocabulary is not None else "")
    heading = f"<h1>{name}</h1>" if name is not None else ""
    count = f'<p class="font-size-small">{said}</p>' if said is not None else ""
    selector = ('<div class="page-selector-wrapper">' + "".join(f'<a href="?page={n}"><button>{n}</button></a>'
                                                                 for n in pages) + "</div>") if pages else ""
    inside = f'{heading}{count}<div id="game-page-games-list">{selector}<div class="results-list">{"".join(cards)}' \
             f"</div></div>"
    return f"<!DOCTYPE html><html><body>{dialog}" + (f'<div id="game-page-wrapper">{inside}</div>' if wrapper
                                                     else inside) + "</body></html>"


def small(text: str) -> str:
    return f'<span class="font-size-small">{text}</span>'


def views(text: str) -> str:
    return f'<span class="font-size-small" style="text-align: right">{text}</span>'


def rated(title: str) -> str:
    return f'<div class="tab-rating-pips" title="{htmllib.escape(title)}"></div>'


GAME = "https://gametabs.net/tabs/g"


def game_records() -> list[dict[str, Any]]:
    p = "parse_game_page"
    records = [
        parsed(p, "Actraiser, as captured", fixture("game_actraiser.html"), "https://gametabs.net/tabs/actraiser"),
        parsed(p, "Hollow Knight, as captured", fixture("game_hollow-knight.html")),
        parsed(p, "Final Fantasy VII, as captured: its page selector", fixture("game_final-fantasy-vii.html")),
        parsed(p, "a page made from Actraiser's", game_page("Hollow Knight", [
            ("dirtmouth", "Dirtmouth", "Christopher Larkin", "Guitar, Bass", "3.4k"), ("hornet", "Hornet", "")])),
        parsed(p, "a page made with views of every size", game_page("Some Game", [
            ("a", "A", "X", "Guitar", "692"), ("b", "B", "X", "Bass", "1.1M"), ("c", "C", "X", "Guitar", "11.2k"),
            ("d", "D", "X", "Guitar", "1,234"), ("e", "E", "X", "Guitar", "0")])),
        parsed(p, "a page that says it has tabs and lists none", game_page("Actraiser", [], count=5)),
        parsed(p, "a page with no wrapper", "<html><body><p>Tabs: 3</p></body></html>"),
        parsed(p, "a game with no tab yet", game_page("Nothing Yet", [])),
        parsed(p, "no heading in the wrapper", game_html(None, [])),
        parsed(p, "an empty heading", game_html("  \n ", [])),
        parsed(p, "a heading of markup's text", game_html("The <b>Game</b>\n  Name", [])),
        parsed(p, "the heading outside the wrapper", game_html("G", [], wrapper=False)),
        parsed(p, "Tabs: 0 and no card", game_html("G", [], said="Tabs: 0")),
        parsed(p, "Tabs: with a thousands comma", game_html("G", [card(f"{GAME}/a", "A - G", [small("Guitar")])],
                                                           said="Tabs:  1,234")),
        parsed(p, "Tabs: of commas alone", game_html("G", [card(f"{GAME}/a", "A - G", [])], said="Tabs: ,")),
        parsed(p, "Tabs: in another script's digits", game_html("G", [card(f"{GAME}/a", "A - G", [])], said="Tabs: ٣")),
        parsed(p, "Tabs: with words after it isn't the count", game_html(
            "G", [card(f"{GAME}/a", "A - G", [])], said="Tabs: 3 more")),
        parsed(p, "fewer said than listed: those listed", game_html(
            "G", [card(f"{GAME}/a", "A - G", []), card(f"{GAME}/b", "B - G", [])], said="Tabs: 1")),
        parsed(p, "the page selector's numbers, the highest", game_html("G", [card(f"{GAME}/a", "A - G", [])],
                                                                       pages=["1", "3", "2", "…", "next"])),
        parsed(p, "a page number in another script's digits", game_html("G", [card(f"{GAME}/a", "A - G", [])],
                                                                        pages=["1", "٧"])),
        parsed(p, "a page number int() refuses", game_html("G", [card(f"{GAME}/a", "A - G", [])], pages=["1", "²"])),
        parsed(p, "a circled page number", game_html("G", [card(f"{GAME}/a", "A - G", [])], pages=["①"])),
        parsed(p, "a page number of 4,301 digits", game_html("G", [card(f"{GAME}/a", "A - G", [])],
                                                            pages=["1" * 4301])),
        parsed(p, "the vocabulary named by the dialog", game_html("G", [
            card(f"{GAME}/a", "A - G", [small("Kazoo"), small("Rock")]),
            card(f"{GAME}/b", "B - G", [small("Guitar"), small("Rock")])], vocabulary=[{"name": "Kazoo"}])),
        parsed(p, "a dialog that won't parse: the site's instruments", game_html("G", [
            card(f"{GAME}/a", "A - G", [small("Kazoo"), small("Bass")])], vocabulary="[{")),
        parsed(p, "a dialog of no names: the site's instruments", game_html("G", [
            card(f"{GAME}/a", "A - G", [small("Banjo, Mandolin"), small("Fingerstyle")])], vocabulary=[])),
        parsed(p, "cards that link to no tab page, and one with no left column", game_html("G", [
            card("https://gametabs.net/tabs/g", "G", []), card("https://example.com/tabs/g/a", "A - G", []),
            card(f"{GAME}/a?x=1", "A - G", []), card(f"{GAME}/b", "B - G", [], left=False),
            card(f"{GAME}/c/", "C - G", [small("Guitar")])])),
        parsed(p, "a card's title from its first span, less the game's name", game_html("G", [
            card(f"{GAME}/a", None, [], first="  A  Song - G "), card(f"{GAME}/b", "", [], first="B - G - G"),
            card(f"{GAME}/c", " - G", []), card(f"{GAME}/d", None, [], first=""),
            card(f"{GAME}/e", "E - Another Game", [])])),
        parsed(p, "a card's spans: platform, composers, tabber, instruments and styles", game_html("G", [
            card(f"{GAME}/a", "A - G", [
                '<span class="x" style="font-style: italic">  Super\nNintendo </span>',
                small("Composers: One, Two ,, Three"), small("Tabber: @@Someone"), small("Guitar, Bass"),
                small("Arrangement, Fingerstyle"), small("Natural harmonics")]),
            card(f"{GAME}/b", "B - G", [small("Composer:"), small("Tabber: @"), small("Composer : X"),
                                         small("Rock"), small("Guitar")]),
            card(f"{GAME}/c", "C - G", ['<span style="italic"></span>', small("Tabber:me"), small(",")]),
            card(f"{GAME}/d", "D - G", [small(","), small("Rock")]),
            card(f"{GAME}/e", "E - G", [small(","), small("Bass"), small(" , ")]),
            card(f"{GAME}/f", "F - G", [small("<b>Composer</b>: Inside Markup"), small("Bass, Kazoo"),
                                         small("Bass")])])),
        parsed(p, "a card's spans nested are not its own", game_html("G", [
            card(f"{GAME}/a", "A - G", ['<div><span class="font-size-small">Composer: Hidden</span></div>',
                                        small("Guitar")])])),
        parsed(p, "a card's views and rating", game_html("G", [
            card(f"{GAME}/a", "A - G", [], [rated("4.5 average fun rating"), views("Ratings 3"), views("Views 2.5k")]),
            card(f"{GAME}/b", "B - G", [], [rated("x average fun rating"), views("Views")]),
            card(f"{GAME}/c", "C - G", [], [rated("5 average quality rating"), views("Views 12 m"),
                                             views("Views 1")]),
            card(f"{GAME}/d", "D - G", [], [rated(" 4 average fun rating"), views("Views 1.5.2")]),
            card(f"{GAME}/e", "E - G", [], [rated("3 average fun rating"), views("Views ١٢k")]),
            card(f"{GAME}/f", "F - G", [], [views("Views " + "9" * 20)]),
            card(f"{GAME}/h", "H - G", [], [views("Views " + "9" * 400)]),
            card(f"{GAME}/i", "I - G", [], [views("Views 0.5"), rated("3.0 average fun rating")]),
            card(f"{GAME}/j", "J - G", [], [views("Views 2.5"), views("Views 3.5k")]),
            card(f"{GAME}/k", "K - G", [], [views("Viewsx 7")])])),
        parsed(p, "a tab listed twice: its first place, its last card", game_html("G", [
            card(f"{GAME}/a", "A - G", [small("Guitar")]), card(f"{GAME}/b", "B - G", []),
            card(f"{GAME}/a", "A Again - G", [small("Bass")])])),
    ]
    return records


def batches() -> list[dict[str, Any]]:
    titles = ["Resting Grounds", "Resting Grounds (Live)", "Main Theme 2", "  ", "", "Fillmore - Remastered 2009",
              "Aeris' Theme", "Zanarkand ~ To Zanarkand", "斑马斑马", "Ça Plane Pour Moi", "Theme (Acoustic Version)"]
    names = ["Hollow Knight", "Hollow Knight OST", "Celeste (Original Soundtrack)", "Celeste [OST]",
             "Chrono Trigger Original Game Soundtrack", "Chrono Trigger Video Game Soundtrack", "Ghost", "OST",
             "Soundtrack", " OST ", "Hollow Knight - OST", "Hollow Knight OST\n", "Hollow Knight Soundtrack OST",
             "The Ostrich", "Yuzo Koshiro", "Song Dongye (宋冬野)", "Final Fantasy VII", "", "   ",
             "Army Men: Sarge's Heroes", "Ori and the Blind Forest ſoundtrack", "Hollow Knight OSTs",
             "Undertale (Original Game Soundtrack)", "Nobuo Uematsu & Kenji Ito", "Hollow Knight ft. Someone"]
    songs = [(["Hollow Knight"], "Hollow Knight"), (["Yuzo Koshiro", "Hollow Knight OST"], "Yuzo Koshiro"),
             ([], "Celeste (Original Soundtrack)"), (["宋冬野"], "宋冬野"), (["A", "B"], "A")]
    tab = {"title": "Resting Grounds", "game": "Hollow Knight", "composers": ["Christopher Larkin"],
           "game_slug": "hollow-knight"}
    fit_cases = [
        ((["Hollow Knight"], "Hollow Knight", "Resting Grounds"), tab),
        ((["Hollow Knight OST"], "Hollow Knight OST", "Resting Grounds"), tab),
        ((["Christopher Larkin"], "Christopher Larkin", "Resting Grounds"), tab),
        ((["Someone"], "Someone", "Resting Grounds"), tab),
        ((["Hollow Knight"], "Hollow Knight", "Resting Grounds Remix"), tab),
        ((["Hollow Knight"], "Hollow Knight", "Resting Grounds (Remastered)"), tab),
        ((["Hollow Knight"], "Hollow Knight", ""), tab | {"title": ""}),
        ((["Hollow Knight"], "Hollow Knight", "Resting Grounds"), tab | {"game": "Silksong", "composers": []}),
        ((["Hollow-Knight"], "Hollow-Knight", "Resting Grounds"), tab | {"game": "Other", "composers": [],
                                                                         "game_slug": "hollow_knight"}),
        ((["Hollowknight"], "Hollowknight", "Resting Grounds"), tab | {"game": "Other", "composers": [],
                                                                       "game_slug": "hollow-knight"}),
        ((["Army Men: Sarge's Heroes"], "Army Men: Sarge's Heroes", "Main Theme"), {
            "title": "Main Theme", "game": "Army Men: Sarge's Heroes", "composers": [],
            "game_slug": "army-men-sarge039s-heroes"}),
        ((["X"], "X", "Resting Grounds"), tab | {"composers": ["Y", "X"]}),
        ((["X"], "X", "Resting Grounds"), tab | {"game_slug": ""}),
        (([], "Hollow Knight", "Resting Grounds"), tab),
    ]

    def fit(case) -> bool:
        (artists, artist, title), t = case
        from caracole.gametabs import GameTab

        song = _song(artists, artist, title)
        return fits(song, GameTab(None, t["title"], t["game"], t["game_slug"], "", "x\n",
                                  composers=tuple(t["composers"])))

    return [
        {"fn": "caracole.gametabs.title_key", "case": "titles", "args": [titles], "out": [title_key(t) for t in titles]},
        {"fn": "caracole.gametabs_fetch.game_forms", "case": "names", "args": [names],
         "out": [game_forms(n) for n in names]},
        {"fn": "caracole.gametabs_fetch.song_forms", "case": "songs", "args": [[list(s) for s in songs]],
         "out": [sorted(song_forms(_song(a, b, "T"))) for a, b in songs]},
        {"fn": "caracole.gametabs_fetch.fits", "case": "a tab page and a song",
         "args": [[[list(s), t] for s, t in fit_cases]], "out": [fit(c) for c in fit_cases]},
    ]


def _song(artists: list[str], artist: str, title: str):
    from caracole.songs import Song

    fields = {f: None for f in Song.__dataclass_fields__}
    fields.update(id=1, key="k", artist=artist, title=title, artists=list(artists))
    return Song(**fields)


def test_parser_vectors():
    check(SITES, jsonl([*tab_records(), *game_records(), *batches()], corpus="sites", made_by=MADE_BY))


# --- a lookup's pass -----------------------------------------------------------------------------------------------


@contextmanager
def clock() -> Iterator[None]:
    """songs.py's clock at the record's ``now``, and no info.json (the viewer's, milestone 5's)."""
    with mock.patch("caracole.songs.utc_now_iso", lambda: STAMP), \
            mock.patch("caracole.gametabs_fetch.write_info", lambda *a, **k: None):
        yield


def ok(page: str | dict[str, str], status: int = 200) -> dict[str, Any]:
    return {"status": status, "headers": HTML, "body": body(page)}


GONE = ok(NOT_FOUND, 404)


class World:
    """A library, its database with the phone's tables, its overrides.toml, and gametabs.net's index: the fixture
    sitemaps' rows, and the game pages named read into it."""

    def __init__(self, tmp: Path, name: str, *, games: tuple[str, ...] = (), extra: tuple[str, ...] = ()):
        from caracole import db
        from caracole.gametabs_index import store_game_page
        from caracole.ug.sitemap import iter_locs

        self.dir = tmp / name
        self.dir.mkdir(parents=True)
        self.conn = db.connect(self.dir / "caracole.sqlite")
        phone_schema(self.conn)
        self.library = self.dir / "library"
        self.library.mkdir()
        self.overrides_file = self.dir / "overrides.toml"
        self.songs: dict[str, int] = {}
        for n, sitemap in enumerate(("sitemap_1.xml", "sitemap_2.xml"), 1):
            for url in iter_locs(fixture_bytes(fixture(sitemap))):
                self.index(url, f"sitemap_{n}")
        for path in extra:
            self.index(f"{BASE_URL}/{path}", "sitemap_3")
        for path in games:
            page = parse_game_page(_game(path))
            store_game_page(self.conn, path, page, NOW - timedelta(days=1))

    def index(self, url: str, sitemap: str) -> None:
        row = parse_page_url(url)
        if row is not None:
            self.conn.execute("INSERT OR REPLACE INTO gametabs_index (path, kind, game, slug, page, key, slug_key, "
                              "sitemap) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (*row, sitemap))

    def song(self, artist: str, title: str, *, artists: list[str] | None = None, added: str = ADDED) -> int:
        from caracole.normalize import identity_key
        from caracole.songs import upsert_song

        with clock():
            song_id, _ = upsert_song(self.conn, artists=artists or [artist], title=title, album=None,
                                     duration_ms=200000, isrc=None, source="wanted",
                                     source_id=identity_key(artist, title), added_at=added)
        self.songs[f"{artist} - {title}"] = song_id
        return song_id

    def get(self, song_id: int):
        from caracole.songs import get_song

        return get_song(self.conn, song_id)

    def overrides(self):
        from caracole.overrides import load_overrides

        return load_overrides(self.overrides_file)

    def write_overrides(self, edit) -> None:
        """``edit(path)`` writes overrides.toml with overrides.py's writers; the phone's rows of it follow."""
        from caracole.canonical import dumps
        from caracole.overrides import SONG_TABLES, song_entries

        edit(self.overrides_file)
        o = self.overrides()
        self.conn.execute("DELETE FROM phone_overrides")
        keys = sorted({k for t in SONG_TABLES for k in getattr(o, t)} | set(o.ignore))
        written = {self.get(i).key: display for display, i in self.songs.items()}
        for key in keys:
            entries = song_entries(o, key)
            for table in (*SONG_TABLES, "ignore"):
                if table in entries:
                    self.conn.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)",
                                      (table, key, written.get(key, key), dumps(entries[table])))

    def keep(self, song_id: int, name: str, data: bytes, *, provider: str = "gametabs", kind: str = "gametab",
             tab_id: str = "tabs/actraiser/fillmore") -> None:
        """A file the song keeps already, under a version of its own."""
        from caracole.library import keep_file
        from caracole.versions import upsert_version

        version = upsert_version(self.conn, provider=provider, tab_id=tab_id, song_id=song_id, slot="guitar",
                                 kind=kind, rating=0.0, votes=0, version=1, label=None, url=f"{BASE_URL}/{tab_id}",
                                 raw={}, now=ADDED)
        keep_file(self.conn, self.library, song=self.get(song_id), version_id=version, name=name, data=data, rank=1)
        self.conn.execute("UPDATE files SET created_at = ?", (ADDED,))

    def run(self, case: str, song_id: int, answers: dict[str, dict[str, Any]], *, budget: int = 6,
            cache: dict[str, Any] | None = None, now: datetime = NOW) -> dict[str, Any]:
        """The lookup's pass for ``song_id``, as get.py's gametabs stage asks it."""
        from caracole.gametabs_fetch import gametabs_tabs

        overrides = self.overrides()

        def call(clients):
            stats = gametabs_tabs(self.conn, clients["gametabs"], self.library, now, overrides=overrides,
                                  only={song_id}, refresh_index=False)
            return stats_of(stats)

        with clock():
            made = record(self.conn, self.library, fn="caracole.gametabs_fetch.gametabs_tabs", case=case, call=call,
                          kw={"only": [song_id]}, now=now, clients={"gametabs": {"budget": budget, "delay": [0, 0]}},
                          answers=answers, cache=cache, cache_dir=self.dir / f"cache-{len(case)}-{id(answers)}")
        made["agent"] = config.DEFAULT_USER_AGENT
        _stamped(made, now)
        self.conn.execute("UPDATE files SET created_at = ? WHERE created_at != ?", (ADDED, ADDED))
        return made

    def close(self) -> None:
        self.conn.close()


def stats_of(s) -> dict[str, Any]:
    return {"tried": s.tried, "errors": s.errors, "budget_exhausted": s.budget_exhausted,
            "failures": [[song.key, type(e).__name__, str(e)] for song, e in s.failures],
            "sitemaps": s.sitemaps, "kept": s.kept, "missing": s.missing}


def _stamped(made: dict[str, Any], now: datetime) -> None:
    """keep_file's ``created_at``, SQLite's clock: each ``files`` row a pass wrote holds a time of that form now,
    recorded as the record's ``now``."""
    done = made.get("out") or made["after"]
    rows = done["rows"]
    if "files" not in rows:
        return
    before = {r["row"]["id"]: r["row"] for r in made["fixture"] if r.get("table") == "files"}
    for row in rows["files"]:
        was = before.get(row["id"])
        if was is not None and was["created_at"] == row["created_at"]:
            continue
        stamp = row["created_at"]
        assert STAMP_SHAPE.fullmatch(stamp), stamp
        at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        assert abs(datetime.now(UTC) - at) < timedelta(minutes=5), stamp
        row["created_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _game(path: str) -> bytes:
    """A game page the world's index has read: a fixture's, or one made."""
    made = {
        "tabs/army-men-sarge039s-heroes": game_page(
            "Army Men: Sarge's Heroes", [("main-theme-60", "Main Theme")], game_slug="army-men-sarge039s-heroes"),
        "tabs/views": game_page("Views Game", [
            ("tie-a", "Tie", "Yuzo Koshiro", "Guitar", "1k"), ("tie-b", "Tie", "Yuzo Koshiro", "Guitar", "2k"),
            ("tie-c", "Tie", "Yuzo Koshiro", "Guitar", "2k"), ("tie-d", "Tie", "Yuzo Koshiro", "Guitar", "500"),
            ("tie-e", "Tie", "Yuzo Koshiro", "Guitar", "3k")], game_slug="views"),
    }
    if path in made:
        return made[path].encode("utf-8")
    return fixture_bytes(fixture(f"game_{path.removeprefix('tabs/')}.html"))


def tab_of(game: str, title: str, *, game_slug: str | None = None, slug: str | None = None, tab_id: int = 1,
           views: int = 100, rating: float | None = 5.0, composers: tuple[str, ...] = ("Yuzo Koshiro",),
           body: str = "e|--0--2--3--|\nB|--1--1--1--|\n") -> dict[str, Any]:
    """A tab page's answer, small (``tab_html``): its ``data-tab`` names the game, the title, the composers, its views
    and fun rating, and its ``<pre>`` holds ``body``."""
    game_slug = game_slug or re.sub(r"[^a-z0-9]+", "-", game.lower()).strip("-")
    slug = slug or re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    said = {"id": tab_id, "name": title, "slug": slug, "game": {"name": game, "slug": game_slug},
            "composers": [{"name": c} for c in composers], "instruments": [{"name": "Guitar"}], "views": views,
            "average_fun_rating": rating, "num_ratings_fun": 1, "user": {"display_username": "Tabber"},
            "created_at": "2026-01-02T03:04:05Z"}
    return ok(tab_html(data=said, pre=htmllib.escape(body)))


def scenarios(tmp: Path) -> list[dict[str, Any]]:
    from caracole.overrides import add_gametabs, add_ignore

    made: list[dict[str, Any]] = []

    def world(name: str, **kw: Any) -> World:
        return World(tmp, name, **kw)

    # A song named by its game: the title's two tabs of the game, the first gone, the second kept as gametab-1.txt.
    w = world("by-game")
    song = w.song("Hollow Knight", "Resting Grounds")
    w.song("Yuzo Koshiro", "Fillmore", added="2026-10-02T00:00:00Z")  # another song: never asked about by a lookup
    made.append(w.run("a song named by its game: the first candidate gone, the second kept as gametab-1.txt", song, {
        f"GET {FIRST}": GONE, f"GET {RESTING}": ok(fixture("tab_hollow-knight_resting-grounds-2.html"))}))
    # The same song asked about again within 30 days: nothing is asked.
    w.conn.execute("DELETE FROM files")
    made.append(w.run("asked about within 30 days: nothing is asked", song, {}, now=NOW + timedelta(days=29)))
    w.close()

    # Named by its composer, once its game's page is read; the game named with OST after it.
    w = world("by-composer", games=("tabs/actraiser",))
    song = w.song("Yuzo Koshiro", "Fillmore")
    made.append(w.run("a song named by its composer, by the game page read", song, {
        f"GET {FILLMORE}": ok(fixture("tab_actraiser_fillmore.html"))}))
    w.close()
    w = world("composer-unread")
    song = w.song("Yuzo Koshiro", "Fillmore")
    made.append(w.run("a composer's song before the game's page is read: no candidate, nothing asked", song, {}))
    w.close()

    # The most viewed of the song's tabs kept: "Hollow Knight OST" is the game.
    w = world("most-viewed", games=("tabs/hollow-knight",))
    song = w.song("Hollow Knight OST", "Resting Grounds")
    made.append(w.run("the game named with OST after it; the most viewed of two that fit kept", song, {
        f"GET {FIRST}": tab_of("Hollow Knight", "Resting Grounds", tab_id=8000, views=5000, body="E|--7--|\nmine\n"),
        f"GET {RESTING}": ok(fixture("tab_hollow-knight_resting-grounds-2.html"))}))
    w.close()

    # Candidates: at most four, the most viewed first by the game pages read, ties by path; the page's views decide.
    extra = tuple(f"tabs/views/tie-{c}" for c in "abcde") + ("tabs/views",)
    w = world("candidates", games=("tabs/views",), extra=extra)
    song = w.song("Views Game", "Tie")
    answers = {f"GET {BASE_URL}/tabs/views/tie-e": tab_of("Views Game", "Tie", game_slug="views", views=10, rating=4.0),
               f"GET {BASE_URL}/tabs/views/tie-b": tab_of("Views Game", "Tie", game_slug="views", views=10, rating=4.5),
               f"GET {BASE_URL}/tabs/views/tie-c": tab_of("Views Game", "Tie", game_slug="views", views=10, rating=4.5,
                                                          body="c\n"),
               f"GET {BASE_URL}/tabs/views/tie-a": tab_of("Views Game", "Tie", game_slug="views", views=9)}
    made.append(w.run("four candidates at most, the most viewed first; a tie on views goes to the best rated, then the "
                      "first by its path", song, answers))
    w.close()
    many = tuple(f"tabs/hollow-knight/resting-grounds-{n}" for n in range(3, 12))
    w = world("too-many", extra=many)
    song = w.song("Hollow Knight", "Resting Grounds")
    answers = {f"GET {BASE_URL}/{p}": tab_of("Hollow Knight", "Another Title") for p in
               ("tabs/hollow-knight/resting-grounds", "tabs/hollow-knight/resting-grounds-10",
                "tabs/hollow-knight/resting-grounds-11", "tabs/hollow-knight/resting-grounds-2")}
    made.append(w.run("none of four candidates the song's: a miss, its kv, the rest never asked", song, answers))
    w.close()

    # A page of another title or another game is no fit: a miss, asked about again after 30 days.
    w = world("no-fit")
    song = w.song("Hollow Knight", "Resting Grounds")
    made.append(w.run("a page of another title, and one of another game: a miss", song, {
        f"GET {FIRST}": tab_of("Hollow Knight", "Resting Grounds Remix"),
        f"GET {RESTING}": tab_of("Silksong", "Resting Grounds", composers=())}))
    made.append(w.run("a miss asked about again after 30 days", song, {
        f"GET {FIRST}": tab_of("Hollow Knight", "Resting Grounds Remix"),
        f"GET {RESTING}": tab_of("Silksong", "Resting Grounds", composers=())}, now=NOW + timedelta(days=31)))
    w.close()

    # Picks.
    w = world("pick")
    song = w.song("Someone", "Something")
    w.write_overrides(lambda path: add_gametabs(path, "Someone - Something", FILLMORE))
    made.append(w.run("the tab you picked, read alone and kept whatever its page names; its :pick kv", song, {
        f"GET {FILLMORE}": ok(fixture("tab_actraiser_fillmore.html"))}))
    made.append(w.run("the pick kept: nothing more is asked", song, {}, now=NOW + timedelta(hours=1)))
    w.close()
    w = world("pick-gone")
    song = w.song("Someone", "Something")
    w.write_overrides(lambda path: add_gametabs(path, "Someone - Something", f"{BASE_URL}/tabs/actraiser/gone"))
    made.append(w.run("a pick gone: a miss, and its :pick kv", song, {
        f"GET {BASE_URL}/tabs/actraiser/gone": GONE}))
    made.append(w.run("a pick gone asked about within 30 days: nothing", song, {}, now=NOW + timedelta(days=1)))
    w.write_overrides(lambda path: add_gametabs(path, "Someone - Something", FILLMORE))
    made.append(w.run("another pick is asked for at once", song, {
        f"GET {FILLMORE}": ok(fixture("tab_actraiser_fillmore.html"))}, now=NOW + timedelta(days=1)))
    w.close()
    w = world("pick-beside")
    song = w.song("Hollow Knight", "Resting Grounds")
    w.keep(song, "gametab-1.txt", b"Resting\n", tab_id="tabs/hollow-knight/resting-grounds-2")
    w.conn.execute("INSERT INTO kv (key, value) VALUES (?, ?)", (f"gametabs:checked:{song}", "2026-11-01T00:00:00Z"))
    w.write_overrides(lambda path: add_gametabs(path, "Hollow Knight - Resting Grounds", FILLMORE))
    made.append(w.run("a pick kept beside the tab the song has, as gametab-2.txt", song, {
        f"GET {FILLMORE}": ok(fixture("tab_actraiser_fillmore.html"))}))
    w.close()
    w = world("pick-redirect")
    song = w.song("Someone", "Something")
    w.write_overrides(lambda path: add_gametabs(path, "Someone - Something", FILLMORE))
    made.append(w.run("a pick sent where robots.txt closes: no tab, a miss", song, {
        f"GET {FILLMORE}": {"status": 302, "headers": [["location", "/login?next=/tabs/actraiser/fillmore"]],
                            "body": {"text": ""}}}))
    w.close()

    # The songs that want no tab.
    w = world("has-one")
    song = w.song("Hollow Knight", "Resting Grounds")
    w.keep(song, "gametab-1.txt", b"mine\n")
    made.append(w.run("a song with a tab from there gets no other", song, {}))
    w.close()
    w = world("ignored")
    song = w.song("Hollow Knight", "Resting Grounds")
    w.write_overrides(lambda path: add_ignore(path, "Hollow Knight - Resting Grounds"))
    made.append(w.run("an ignored song is left alone", song, {}))
    w.close()
    w = world("no-candidate")
    song = w.song("Someone", "Resting Grounds")
    made.append(w.run("the title, by no game or composer of it: nothing asked", song, {}))
    w.close()

    # Numbers held, another site's tab.
    w = world("held")
    song = w.song("Hollow Knight", "Resting Grounds")
    from caracole.library import song_dir

    folder = song_dir(w.library, w.get(song))
    folder.mkdir(parents=True)
    (folder / "gametab-1.txt").write_text("my own\n", encoding="utf-8")
    made.append(w.run("a number a file in the folder holds is never reused: gametab-2.txt", song, {
        f"GET {FIRST}": GONE, f"GET {RESTING}": ok(fixture("tab_hollow-knight_resting-grounds-2.html"))}))
    w.close()
    w = world("ug-tab")
    song = w.song("Hollow Knight", "Resting Grounds")
    w.keep(song, "tab.txt", b"e|--|\n", provider="ug", kind="tabs", tab_id="1")
    made.append(w.run("a UG text tab is no tab from here: one is kept beside it", song, {
        f"GET {FIRST}": GONE, f"GET {RESTING}": ok(fixture("tab_hollow-knight_resting-grounds-2.html"))}))
    w.close()
    w = world("by-name", games=("tabs/army-men-sarge039s-heroes",),
              extra=("tabs/army-men-sarge039s-heroes", "tabs/army-men-sarge039s-heroes/main-theme-60"))
    song = w.song("Army Men: Sarge's Heroes", "Main Theme")
    made.append(w.run("a game's name from its page meets an artist its slug doesn't", song, {
        f"GET {BASE_URL}/tabs/army-men-sarge039s-heroes/main-theme-60": tab_of(
            "Army Men: Sarge's Heroes", "Main Theme", game_slug="army-men-sarge039s-heroes", slug="main-theme-60")}))
    w.close()
    w = world("two-artists")
    song = w.song("Someone & Hollow Knight", "Resting Grounds", artists=["Someone", "Hollow Knight"])
    made.append(w.run("a song of two artists, the second the game", song, {
        f"GET {FIRST}": GONE, f"GET {RESTING}": ok(fixture("tab_hollow-knight_resting-grounds-2.html"))}))
    w.close()

    # Errors are never misses.
    w = world("wont-parse")
    song = w.song("Hollow Knight", "Resting Grounds")
    made.append(w.run("a page that won't parse is an error, never a miss", song, {
        f"GET {FIRST}": GONE, f"GET {RESTING}": ok("<html><body>Something went wrong</body></html>")}))
    w.close()
    w = world("cached-wont-parse")
    song = w.song("Hollow Knight", "Resting Grounds")
    cache = {"gametabs": {f"GET {FIRST}": {"status": 404, "fetched_at": "2026-11-02T00:00:00Z",
                                           "body": {"text": NOT_FOUND}},
                          f"GET {RESTING}": {"status": 200, "fetched_at": "2026-11-02T00:00:00Z",
                                             "body": {"text": "<html><body>Something went wrong</body></html>"}}}}
    made.append(w.run("a cached page that won't parse is asked for once more, and read", song, {
        f"GET {RESTING}": ok(fixture("tab_hollow-knight_resting-grounds-2.html"))}, cache=cache))
    w.close()
    w = world("server-error")
    song = w.song("Hollow Knight", "Resting Grounds")
    made.append(w.run("a server error leaves the song for the next run", song, {
        f"GET {FIRST}": GONE, f"GET {RESTING}": ok("<html><body>Bad Gateway</body></html>", 502)}))
    w.close()
    w = world("block")
    song = w.song("Hollow Knight", "Resting Grounds")
    made.append(w.run("a block propagates and keeps nothing", song, {
        f"GET {FIRST}": {"status": 429, "headers": [["content-type", "text/plain"]],
                         "body": {"text": "Too Many Requests"}}}))
    w.close()
    w = world("budget")
    song = w.song("Hollow Knight", "Resting Grounds")
    made.append(w.run("a spent budget ends the pass, no miss", song, {f"GET {FIRST}": GONE}, budget=1))
    w.close()

    # The tabs' title keys made again after a change to caracole's keys.
    w = world("keys", games=("tabs/actraiser",))
    song = w.song("Yuzo Koshiro", "Fillmore")
    w.conn.execute("UPDATE gametabs_game_tabs SET title_key = 'stale' WHERE path = 'tabs/actraiser/fillmore'")
    w.conn.execute("DELETE FROM kv WHERE key = 'gametabs:games:keys'")
    made.append(w.run("the tabs' title keys made again from their titles first", song, {
        f"GET {FILLMORE}": ok(fixture("tab_actraiser_fillmore.html"))}))
    w.close()
    return made


def test_lookup_vectors(tmp_path):
    check(LOOKUP, jsonl(scenarios(tmp_path), corpus="lookup", made_by=MADE_BY))
