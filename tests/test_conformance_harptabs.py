"""harptabs.com for a lookup, for the phone's lane harptabs (core.sites' ``HarpTabsPages`` and ``HarpTabsFetch``, the
lookup's harptabs stage and ``HarpTabsCommands.artist``) to replay: harptabs.py's pages read, harptabs_fetch.py's pass
for one song, harptabs_index.py's artist page read now, get.py's harptabs stage and ``caracole harptabs --artist``.

**Pages** (``vectors/sites/harptabs.jsonl``), a record a call, over tests/fixtures/harptabs and the pages
helpers/harptabs_site.py makes of them: ``page_url``, ``parse_page_url`` (``out`` the ``IndexRow``'s fields, or null),
``joined``, ``title_key``, ``title_keys``, ``song_title``, ``song_key``, ``_views``, ``_rating``,
``parse_tab_page`` (``out`` the ``HarpTab``'s fields) and ``parse_artist_page`` (``out`` the ``ArtistPage``'s, each
listed tab's fields). A page is ``html``, a ``corpus.fixture_ref`` or ``{"text"}``; a parse that raises records
``raises``: ``{"type", "message"}``, the class's name and ``str(e)``.

**Lookups** (``vectors/lookup/``), scenario records (tests/helpers/scenario.py, the corpus spec's "Scenario records"),
each in a world of its own: harptabs.com's index as the computer's sitemap read left it (``site_index.refresh`` over the
fixture sitemap, with more pages where a case says), the songs, files and kv the case needs, ``[harptabs]`` and
``ignore`` as the phone holds overrides.toml (``phone_overrides``, as ``overrides.song_entries`` yields them), a client
of provider ``harptabs`` and the site's answers, every request with caracole's own user agent (each record's
``agent``, ``config.DEFAULT_USER_AGENT``, which the phone's requests must carry).

- ``harptabs.jsonl``: ``harptabs_fetch.harptabs_tabs`` for one song as a lookup asks it (``only`` its id,
  ``refresh_index=False``: the phone reads no sitemap): ``out.result`` the stats (``tried``, ``errors``,
  ``budget_exhausted``, ``failures`` each ``[song id, the error's class, its message]``, ``sitemaps``, ``kept``,
  ``missing``); and get.py's harptabs stage (``fn`` ``caracole.get._Lookup.harptabs``: ``out.result`` its
  ``[state, detail]``, a detail alone being ``done``'s), its envelope's words for a block, a spent budget, an error
  and a cooldown among them, with what each records (kv ``provider:harptabs``).
- ``harptabs_artist.jsonl``: ``harptabs_index.read_artist`` (``out.result`` the ``ArtistPage``, or null for a page
  gone), its rows (``store_artist_page``, ``store_gone``) and ``reads``, the pages the phone notes for its next push to
  the computer (core.index.Reads, kv ``phone:read:harptabs:<path>`` = the stamp, which Python doesn't write: the replay
  checks them and leaves them out of the kv compared); and ``artist_paths`` over one index (``cases``, each a name and
  the paths).
- ``commands_harptabs.jsonl``: ``caracole harptabs --artist`` (commands/lyrics.py ``_harptabs_artist``, ``kw.artist``
  its argument with its whitespace folded): ``out.result`` the lines it printed, its last the line caracole serve's
  request line shows, and what it read and recorded (record_block, record_error, record_ok). The site turned off
  comes to the phone as its settings (kv ``phone:settings``, ``politeness.settings_document``).

Stamps: songs.py's clock (``utc_now_iso``) is ``ADDED`` while a world is made; keep_file's ``created_at``, SQLite's
clock, is the record's ``now`` once checked to be a time of that form now (what the phone's ``Kept.keepFile`` is
given); a file kept before a record is stamped ``ADDED``. ``write_info`` (info.json) is the viewer's, milestone 5's:
no pass writes it here, as the phone writes none.

Regenerate with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import base64
import json
import re
from html import escape
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

import pytest

from helpers.corpus import VECTORS, check, fixture_bytes, fixture_ref, jsonl, phone_schema
from helpers.harptabs_site import BASE, SITEMAP, FakeHarpTabs, artist_page, fixture, tab_page
from helpers.scenario import record

MADE_BY = "tests/test_conformance_harptabs.py"
SITES_FILE = VECTORS / "sites" / "harptabs.jsonl"
LOOKUP_FILE = VECTORS / "lookup" / "harptabs.jsonl"
ARTIST_FILE = VECTORS / "lookup" / "harptabs_artist.jsonl"
COMMANDS_FILE = VECTORS / "lookup" / "commands_harptabs.jsonl"

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
STAMP = "2026-11-03T12:00:00Z"
ADDED = "2026-10-01T00:00:00Z"
SITEMAP_READ = datetime(2026, 10, 27, 3, 30, tzinfo=UTC)  # when the computer's nightly run read the sitemap
LONG_AGO = "2026-09-20T12:00:00Z"  # more than 30 days before NOW
LATELY = "2026-10-20T12:00:00Z"  # less than 30 days before NOW
FETCHED = "2026-10-24T09:00:00Z"  # a page the cache holds from within 30 days
OLD_FETCH = "2026-09-01T09:00:00Z"  # a page the cache holds from before them
HTML = [["content-type", "text/html; charset=utf-8"]]
NOT_FOUND = "<html><body>Not found</body></html>"
_STAMPED = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def url(path: str) -> str:
    return f"{BASE}/{path}"


def text(s: str) -> dict[str, str]:
    return {"text": s}


def page(name_or_html: str) -> dict[str, str]:
    """A fixture page of tests/fixtures/harptabs by its name, else the text given."""
    return fixture_ref(f"harptabs/{name_or_html}") if name_or_html.endswith(".html") and "<" not in name_or_html \
        else text(name_or_html)


def ok(body: str) -> dict[str, Any]:
    return {"status": 200, "headers": HTML, "body": page(body)}


def status(code: int, body: str = NOT_FOUND) -> dict[str, Any]:
    return {"status": code, "headers": HTML, "body": text(body)}


def held(answer: dict[str, Any], at: str = FETCHED) -> dict[str, Any]:
    """An answer as the HTTP cache holds it."""
    return {"status": answer["status"], "fetched_at": at, "headers": {"content-type": HTML[0][1]},
            "body": answer["body"]}


def raised(e: BaseException) -> dict[str, str]:
    return {"type": type(e).__name__, "message": str(e)}


# --- the pages ----------------------------------------------------------------------------------------------------


def _calls(fn: str, f, inputs: list[Any]) -> list[dict[str, Any]]:
    return [{"fn": f"caracole.harptabs.{fn}", "args": [x], "out": f(x)} for x in inputs]


def _row(row) -> dict[str, Any] | None:
    return None if row is None else {"path": row.path, "kind": row.kind, "page_id": row.page_id, "key": row.key}


URLS = [
    *(f"{BASE}/{p}" for p in (
        "", "browse", "terms", "genre/blues", "artist/4", "artist/50/the-beatles", "artist/1178/billy-joel",
        "artist/7829/ritchie-valens", "tab/6/silent-night", "tab/25/piano-man", "tab/89/la-bamba",
        "tab/29525/piano-man", "tab/1/can-t-help-falling-in-love", "tab/1/cant-help-falling-in-love",
        "tab/2/knockin-on-heaven-s-door", "tab/3/i-m-confessin", "tab/4/you-ain-t-goin-nowhere",
        "tab/5/rock-n-roll-ain-t-noise-pollution", "tab/6/we-ll-meet-again", "tab/7/they-re-red-hot",
        "tab/8/i-ve-been-loving-you-too-long", "tab/9/you-d-be-so-nice", "tab/10/t-for-texas", "tab/11/s",
        "artist/5/guns-n-roses", "artist/6/t-rex", "tab/123456789/x", "tab/1234567890/x", "tab/12/Piano-Man",
        "tab/12/piano_man", "tab/12/piano-man/", "tab/12/", "tab/0/zero", "tab/007/bond", "tab/12/---",
        "tab/١٢/piano-man", "artist/12/" + "a" * 200, "artist/12/" + "a" * 201, "search/12/piano-man",
    )),
    "https://harptabs.com/tab/89/la-bamba", "http://www.harptabs.com/tab/89/la-bamba",
    "https://www.harptabs.com.evil.example/tab/89/la-bamba", "https://www.harptabs.com/tab/89/la-bamba?x=1",
    "https://m.harptabs.com/tab/89/la-bamba", "tab/89/la-bamba", "",
]

TITLES = [
    "Piano Man", "Piano Man (Live)", "Don't Stop", "Can't Help Falling in Love", "Knockin' on Heaven's Door",
    "You Ain't Goin' Nowhere", "O'Brien's Lament", "Rock 'n' Roll", "I'm Confessin'", "She's Always a Woman",
    "Piano Man (C Harmonica)", "((((Piano Man (Harmonica Intro)", "(harmonica riff) piano man", "Piano Man [Intro]",
    "Piano Man (Harp Intro", "(Intro)", "((()))", "Vienna!", "斑马斑马", "Für Elise", "Ça plane pour moi", "",
    "   ", "Yesterday (Remastered 2009)", "Hey Jude - Remastered", "L.A. Woman", "99 Luftballons",
    "Mr. Tambourine Man (harp part only) [solo]", "Isn’t She Lovely", "Rock ʼn Roll",
]

# HUGE: a finite count past SQLite's integers (and a Long's), which Python's int keeps whole: only SQLite refuses it,
# where it is written (OverflowError), never a page passed over
HUGE = "9" * 30 + "M"
VIEWS = [None, "", "1.1M", "57k", "974", "2.5K", "1,234", "1,1M", " 12k ", "12 k", "0", "0.5k", "1.", ".5k", "1e3",
         "M", "12x", "١٢k", "9" * 400, "3.3333333m", "２０k", HUGE, "9223372036854775807", "9223372036854775k"]
RATINGS = [None, "", "4.0", "5", "5.0001", "0", "-0.0", "-1", " 3.5 ", "nan", "inf", "1e0", "4,5", "x", "١"]


def _given(html: Any) -> tuple[dict[str, str], str | bytes]:
    """How a record carries a page (a fixture's reference, its bytes, its text), and what the parser is given."""
    if isinstance(html, bytes):
        return {"base64": base64.b64encode(html).decode("ascii")}, html
    if isinstance(html, dict):
        return html, fixture_bytes(html)
    return text(html), html


def _tab(html: Any, url: str | None = None) -> dict[str, Any]:
    from caracole.harptabs import HarpTabsParseError, parse_tab_page

    data, body = _given(html)
    rec: dict[str, Any] = {"fn": "caracole.harptabs.parse_tab_page", "html": data, "url": url}
    try:
        tab = parse_tab_page(body, url)
    except HarpTabsParseError as e:
        rec["raises"] = raised(e)
    else:
        rec["out"] = {"title": tab.title, "artist": tab.artist, "body": tab.body, "key": tab.key, "harp": tab.harp,
                      "difficulty": tab.difficulty, "views": tab.views, "rating": tab.rating, "raw": tab.raw()}
    return rec


def _artist(html: Any, url: str | None = None) -> dict[str, Any]:
    from caracole.harptabs import HarpTabsParseError, parse_artist_page

    data, body = _given(html)
    rec: dict[str, Any] = {"fn": "caracole.harptabs.parse_artist_page", "html": data, "url": url}
    try:
        rec["out"] = parse_artist_page(body, url)
    except (HarpTabsParseError, ValueError) as e:
        rec["raises"] = raised(e)
    return rec


_WORK = object()  # mini_tab's JSON-LD by default: the title and the artist, as the site writes them


def mini_tab(title: str = "Yesterday", artist: str | None = "The Beatles", *, views: str | None = "1.1M",
             key: str | None = "C", body: str = "4 5 6\nsynthetic words\n", artist_path: str = "artist/1/someone",
             rating: str | None = None, harp: str | None = None, difficulty: str | None = "Beginner",
             work: Any = _WORK) -> str:
    """A tab page in the captured ones' markup, its classes and the rest of the page left out (what the parser
    reads alone: helpers/harptabs_site.tab_page's page, in a tenth of its bytes): its JSON-LD (``work``; None for
    none), its header (the title, the line "by" the artist's link), its chips and its ``<pre>`` (``body``, as
    HTML)."""
    if work is _WORK:
        work = {"@context": "https://schema.org", "@type": "MusicComposition", "name": title,
                "composer": {"@type": "MusicGroup", "name": artist}}
    ld = "" if work is None else (
        '<script type="application/ld+json">' + json.dumps(work, ensure_ascii=False) + "</script>")
    by = "" if artist is None else (
        f'<p>by<!-- --> <a href="/{artist_path}">{escape(artist)}</a> · posted by <a href="/u/norm">norm</a></p>')
    chips = "".join(chip for chip in (
        "" if views is None else f'<li><span><svg class="lucide lucide-eye"></svg>{views}</span></li>',
        "" if key is None else f'<li><a href="/search?key=5">Key <!-- -->{escape(key)}</a></li>',
        "" if harp is None else f'<li><a href="/search?harp=1">{escape(harp)}</a></li>',
        "" if difficulty is None else f'<li><a href="/search?difficulty=1">{escape(difficulty)}</a></li>',
        "" if rating is None else f'<li><span><svg class="lucide lucide-star text-accent-text"></svg>{rating}</span></li>',
    ))
    return (f"<!DOCTYPE html><html><head>{ld}</head><body><main><header><h1>{escape(title)}</h1>{by}</header>"
            f'<ul>{chips}</ul><div role="region" aria-label="Harmonica tab notation"><pre><code>{body}</code></pre>'
            "</div></main></body></html>")


def card(tab_id: int, slug: str, title: str, *, views: str | None = "1.1M", said: tuple[str, ...] = ("Key <!-- -->C",),
         rating: str | None = "4.0", difficulty: str | None = "Beginner", href: str | None = None) -> str:
    """An artist page's card in the captured one's markup, its classes but the ones read left out."""
    spans = "".join(f"<span>{s}</span>" for s in said)
    return ('<div class="group relative block"><div><h3><a href="' + (href or f"/tab/{tab_id}/{slug}") + f'">'
            f'{escape(title)}</a></h3><p>someone<span aria-hidden="true"> · </span>{spans}</p></div><div>'
            + ("" if views is None else f'<span><svg class="lucide lucide-eye"></svg>{views}</span>')
            + ("" if rating is None else f'<span><svg class="lucide lucide-star fill-accent-text"></svg>{rating}</span>')
            + '<button type="button"><svg class="lucide lucide-heart"></svg>974</button>'
            + ("" if difficulty is None else f'<span class="rounded-full text-diff-1 ml-auto">{difficulty}</span>')
            + "</div></div>")


def mini_artist(name: str, cards: list[str], *, said: str | None = None) -> str:
    """An artist page in the captured one's markup, its classes but the ones read left out: its header (the name,
    and ``said``, how many tabs it says they have: the cards', by default) and its cards."""
    n = len(cards)
    said = f"{n} tab{'' if n == 1 else 's'}" if said is None else said
    return (f"<!DOCTYPE html><html><body><main><div><header><h1>{escape(name)}</h1><p>{said}</p></header>"
            f'<div class="grid">{"".join(cards)}</div></div></main></body></html>')


def tab_records() -> list[dict[str, Any]]:
    out = [_tab(fixture_ref(f"harptabs/{name}"), url(path)) for name, path in (
        ("tab_25_piano-man.html", "tab/25/piano-man"), ("tab_89_la-bamba.html", "tab/89/la-bamba"),
        ("tab_29910_knockin-on-heavens-door.html", "tab/29910/knockin-on-heavens-door"))]
    out += [  # the captured markup whole, made by helpers/harptabs_site.py as the Python tests make it
        _tab(tab_page("Piano Man (C Harmonica)", "Pharm Gal", views="2.5M", body="6 6 6\npick\n")),
        _tab(tab_page("Yesterday", "Unknown", artist_path="artist/4")),
    ]
    out += [_tab(mini_tab(views=v)) for v in ("1.1M", "57k", "974", "2,345", "", None, "12x", HUGE)]
    out += [_tab(mini_tab(artist=a, artist_path=p)) for a, p in (
        ("Unknown", "artist/4"), ("?", "artist/4"), ("unknown", "artist/4"), ("Various Artists", "artist/9/various"),
        ("Traditional", "artist/10/traditional"), ("Anonymous", "artist/11/anonymous"), ("Billy Joel", "artist/1/b"))]
    out += [
        _tab(mini_tab(key="")),
        _tab(mini_tab(key=None)),
        _tab(mini_tab(key="E (I use an A harp)")),
        _tab(mini_tab(harp="Diatonic", difficulty="Advanced", rating="4.5")),
        _tab(mini_tab(rating="9", difficulty=None)),
        _tab(mini_tab(rating="-0.0")),
        _tab(mini_tab(work={"@type": "MusicComposition", "name": "Yesterday"})),  # no composer: the header's link
        _tab(mini_tab(work={"@type": "MusicComposition", "name": "Yesterday", "composer": "The Beatles"})),
        _tab(mini_tab(work={"@type": "MusicComposition", "name": "  Yesterday  ", "composer": {"name": " Beatles "}})),
        _tab(mini_tab(work={"@type": "MusicComposition", "name": 1999, "composer": {"name": 1.5}})),
        _tab(mini_tab(work={"@type": "MusicComposition", "name": 1e16, "composer": {"name": 12345678901234567890}})),
        _tab(mini_tab(work={"@type": "MusicComposition", "name": ["a", 'b"c', "d'e"], "composer": {"name": True}})),
        _tab(mini_tab(work={"@type": "MusicComposition", "name": {"x": None}, "composer": {"name": [1, 2.0, False]}})),
        _tab(mini_tab(work={"@type": "MusicComposition", "name": 0, "composer": {"name": ""}})),
        _tab(mini_tab(work={"@type": "MusicComposition", "name": float("nan"), "composer": {"name": float("-inf")}})),
        _tab(mini_tab(work={"@type": "MusicComposition", "name": -0.0, "composer": {"name": 0.5e-400}})),
        _tab(mini_tab().replace('"name": "Yesterday"', '"name": 1e400')),
        # literals json.loads reads as 0.0, falsy (the header's title and link then), and one that stays a subnormal
        _tab(mini_tab().replace('"name": "The Beatles"', '"name": 1e-400').replace('"name": "Yesterday"',
                                                                                    '"name": -4e-325')),
        _tab(mini_tab().replace('"name": "The Beatles"', '"name": 5e-324').replace('"name": "Yesterday"',
                                                                                    '"name": 0e7')),
        _tab(mini_tab(work={"@type": "MusicComposition", "name": "", "composer": None})),
        _tab(mini_tab(work={"@type": "MusicRecording", "name": "Other", "composer": {"name": "Other One"}})),
        _tab(mini_tab(work={"@type": ["MusicComposition"], "name": "Other"})),
        _tab(mini_tab(work=[{"@type": "MusicComposition", "name": "Other"}])),
        _tab(mini_tab(work="MusicComposition")),
        _tab(mini_tab(work=None)),
        _tab(mini_tab(work=None).replace('href="/artist/1/someone"', 'href="/somewhere"')),
        _tab(mini_tab(work=None, artist=None)),
        _tab(mini_tab(work=None).replace('<a href="/artist/1/someone">The Beatles</a>', "<span>Unknown</span>")),
        _tab(mini_tab().replace("</head>", '<script type="application/ld+json">{"@type": "MusicComposition", '
                                           '"name": "Second"}</script></head>')),
        _tab(mini_tab().replace('<script type="application/ld+json">', '<script type="application/ld+json">{bad'
                                                                        '</script><script type="application/ld+json">')),
        _tab(mini_tab(work=None).replace("<head>", '<head><script type="application/ld+json">{not json</script>')),
        _tab(mini_tab(work=None).replace("<head>", '<head><script type="application/ld+json">[1, 2]</script>')),
        _tab(mini_tab(work=None).replace("<head>", '<head><script type="application/ld+json">' + "[" * 2000
                                         + "</script>")),
        _tab(mini_tab(work=None).replace("<head>", '<head><script type="application/ld+json"></script>')),
        _tab(mini_tab(work=None).replace("<head>", '<head><script type="application/json">{"@type": '
                                                   '"MusicComposition", "name": "No"}</script>')),
        _tab(mini_tab(body="<p>Tabbed by someone<br>-4 -4 5<br/>Love, love me</p><p>4 5</p><p>do</p>\n<p>4</p>")),
        _tab(mini_tab(body="<div>-4 5</div><div>words</div>\n\n<div>6</div>tail")),
        _tab(mini_tab(body="<p>a<p>b</p></p>c<div><p>d</p></div>e")),
        _tab(mini_tab(body="<div><div>a</div>\nb</div><p></p><p></p>c")),
        _tab(mini_tab(body="\n\n4 5 6\nwords\n\n")),
        _tab(mini_tab(body="<b>-4</b> <i>5</i>\n&lt;6&gt; &amp; &#x2019;s\r\nline")),
        _tab(mini_tab(body="4<br><br>5<br>\n6")),
        _tab(mini_tab(body="<p>x</p><!-- c -->y")),
        _tab(mini_tab(body="<p>x</p>\ny<p>z</p> \nw")),
        _tab(mini_tab(body="  ")),
        _tab(mini_tab(body="")),
        _tab(mini_tab(body="\n")),
        _tab(mini_tab().replace("<pre", "<div").replace("</pre>", "</div>")),
        _tab(mini_tab().replace('aria-label="Harmonica tab notation"', 'aria-label="Other"')
             .replace("<main>", "<main><pre>decoy</pre>")),
        _tab(mini_tab().replace("<main>", "<main><pre>decoy</pre>")),
        _tab(mini_tab().replace("<main>", "<main><pre> </pre>")),
        _tab("<html><body>Something went wrong</body></html>", url("tab/1/x")),
        _tab("<html><body><pre>4 5 6</pre></body></html>", url("tab/1/x")),
        _tab("<html><body><header><h1>Song</h1></header><pre>4 5 6</pre></body></html>", url("tab/1/x")),
        _tab("<html><body><header><h1>Song</h1><p>by <a>Someone</a> · posted</p></header><pre>4</pre></body></html>"),
        _tab("<html><body><header><h1>Song</h1><p>by <span>Unknown</span></p></header><pre>4</pre></body></html>"),
        _tab("<html><body><header><h1>Song</h1><p>posted by <a>Someone</a></p></header><pre>4</pre></body></html>"),
        _tab("<html><body><header><h1>Song</h1><p>by <b>Bold</b><a>Linked</a></p></header><pre>4</pre></body></html>"),
        _tab("<html><body><header><h1>Song</h1><p>by <b><a>Deep</a></b></p></header><pre>4</pre></body></html>"),
        _tab("<html><body><header><h1>Song</h1><p>by Someone</p></header><pre>4</pre></body></html>"),
        _tab("<html><body><header><h1>Song</h1><div></div><p>by <a>Not next</a></p></header><pre>4</pre></body></html>"),
        _tab("<html><body><header><h1></h1><a href=\"/artist/1/a\">A</a></header><pre>4</pre></body></html>"),
        _tab("<html><body><header><h1>  Song\n  Two </h1><a href=\"/artist/1/a\">  A\tB </a></header>"
             "<ul><li><span><svg class=\"lucide lucide-eye\"></svg>12k</span></li>"
             "<li><span><svg class=\"lucide-star x\"></svg>4.5</span></li></ul>"
             "<a href=\"/search?harp=chromatic\">Chromatic</a><a href=\"/search?difficulty=hard\">Hard</a>"
             "<a href=\"/search?key=x\">Key</a><pre>4</pre></body></html>"),
        _tab("<html><body><header><h1>S</h1><a href=\"/artist/1/a\">A</a></header>"
             "<ul><li><span><svg class=\"lucide-eye-off\"></svg>12k</span></li><li><span><svg></svg>1</span></li>"
             "<li><span><svg class></svg>2</span></li><li><span>3</span></li>"
             "<li><b><span><svg class=\"lucide-star\"></svg>9</span></b></li></ul><pre>4</pre></body></html>"),
        _tab("<html><body><header><h1>S</h1><a href=\"/artist/1/a\">A</a></header><ul>"
             "<li><span><svg class=\"lucide-eye\"></svg>1k</span></li><li><span><svg class=\"lucide-eye\"></svg>"
             "2k</span></li><li><span><b><svg class=\"lucide-star\"></svg></b>3</span></li></ul><pre>4</pre>"
             "</body></html>"),
        _tab(b"<html><body><header><h1>Caf\xc3\xa9 \xff</h1><a href=\"/artist/1/a\">A\xc3</a></header>"
             b"<pre>4 \xe2\x80</pre></body></html>"),
    ]
    return out


def artist_records() -> list[dict[str, Any]]:
    catch_all = fixture("artist_4.html")
    head, _, rest = catch_all.partition('<div class="grid')
    empty = head + rest[rest.index("</main>"):]
    piano = card(25, "piano-man", "piano man")
    out = [_artist(fixture_ref(f"harptabs/{name}"), url(path)) for name, path in (
        ("artist_1178_billy-joel.html", "artist/1178/billy-joel"), ("artist_4.html", "artist/4"))]
    out += [
        _artist(empty),
        _artist(artist_page("billy joel", [(25, "piano-man", "piano man"), (9, "nine", "Nine", "57k")])),
        _artist(mini_artist("billy joel", [piano, card(9, "nine", "Nine", views="57k", rating=None)])),
        _artist(mini_artist("billy joel", [piano], said="1 tab")),
        _artist(mini_artist("billy joel", [piano], said="1234 tabs")),
        _artist(mini_artist("billy joel", [piano], said="1,234 tabs")),
        _artist(mini_artist("billy joel", [piano], said="99,999,999,999,999,999,999 tabs")),
        _artist(mini_artist("billy joel", [piano, card(9, "nine", "Nine", views=HUGE)])),
        _artist(mini_artist("billy joel", [piano], said="no count")),
        _artist(mini_artist("billy joel", [piano], said="٣ tabs")),
        _artist(mini_artist("billy joel", [piano], said="3 tab")),
        _artist(mini_artist("billy joel", [piano], said="about 3\ntabs and more")),
        _artist(mini_artist("billy joel", [piano], said=", tabs")),
        _artist(mini_artist("billy joel", [piano, card(25, "piano-man", "Again", views="9")])),
        _artist(mini_artist("billy joel", [piano, card(7, "x", "X"), card(25, "piano-man", "Again", views="9")],
                            said="2 tabs")),
        _artist(mini_artist("billy joel", [], said="98 tabs"), url("artist/1178/billy-joel")),
        _artist(mini_artist("billy joel", [], said="0 tabs")),
        _artist(mini_artist("billy joel", [])),
        _artist(mini_artist("a & b <c>", [card(1, "x", "Tab & <one>")])),
        _artist(mini_artist("billy joel", [card(25, "piano-man", "piano man", href="/x/25/piano-man")]),
                url("artist/1178/billy-joel")),
        _artist(mini_artist("billy joel", [card(1, "a", "A", href="/tab/1/Piano"),
                                           card(2, "b", "B", href="https://www.harptabs.com/tab/2/b"),
                                           card(3, "c", "C", href="/tab/1234567890/c"), card(4, "d", " "),
                                           card(5, "e", "E", href="/tab/5/e?x=1"), card(6, "f", "F")])),
        _artist(mini_artist("billy joel", [card(1, "a", "A", said=("Key <!-- --> ",)),
                                           card(2, "b", "B", said=("Rock", "Key D")),
                                           card(3, "c", "C", said=("Keys G",)), card(4, "d", "D", said=()),
                                           card(5, "e", "E", said=("Key  Bb", "Key E")),
                                           card(6, "f", "F", views=None, rating="5.5", difficulty=None),
                                           card(7, "g", "G", views="2,5k", rating="x", difficulty="")])),
        _artist("<html><body><main><p>98 tabs</p></main></body></html>", url("artist/1/x")),
        _artist("<html><body><main><header><h1> </h1></header></main></body></html>", url("artist/1/x")),
        _artist("<html><body><header><h1>Outside main</h1></header></body></html>", url("artist/1/x")),
        _artist("<html><body><main><header><h1>Somebody</h1><p>3 tabs</p></header>"
                "<div class=\"group\"><h3><a href=\"/tab/1/a\">A</a></h3><p><span>Key G</span><span>Blues</span></p>"
                "<span class=\"text-diff-easy\">Easy</span><span><svg class=\"lucide-eye\"></svg>3</span></div>"
                "<div class=\"group\"><h3><a href=\"/tab/2/b\"> </a></h3></div>"
                "<div class=\"group\"><h3><a href=\"/tab/3/c\">C</a></h3><p>Key A</p>"
                "<span><svg class=\"lucide-star\"></svg>4.25</span></div>"
                "<div class=\"groups\"><h3><a href=\"/tab/4/d\">D</a></h3></div></main></body></html>"),
    ]
    return out


def sites_records() -> list[dict[str, Any]]:
    from caracole import harptabs as h

    out = _calls("page_url", h.page_url, ["tab/25/piano-man", "artist/4", ""])
    out += _calls("parse_page_url", lambda u: _row(h.parse_page_url(u)), URLS)
    out += _calls("joined", h.joined, ["can-t-help", "i-m", "s", "t-rex", "rock-n-roll-ain-t", "a--t", "", "ll-ll"])
    for fn in ("title_key", "title_keys", "song_title", "song_key"):
        out += _calls(fn, getattr(h, fn), TITLES)
    out += _calls("_views", h._views, VIEWS)
    out += _calls("_rating", h._rating, RATINGS)
    return out + tab_records() + artist_records()


def test_harptabs_sites_jsonl():
    check(SITES_FILE, jsonl(sites_records(), corpus="sites/harptabs", made_by=MADE_BY))


def test_the_pages_cover_each_outcome():
    records = sites_records()
    tabs = [r for r in records if r["fn"].endswith("parse_tab_page")]
    artists = [r for r in records if r["fn"].endswith("parse_artist_page")]
    assert any(r.get("out") and r["out"]["artist"] is None for r in tabs)  # a tab of no artist
    assert {r["raises"]["message"].split(": ")[-1] for r in tabs if "raises" in r} == {
        "no tab (<pre>) on the page", "no title or artist on the page"}
    assert any(r.get("out") and r["out"]["rating"] is not None for r in tabs)
    assert {r["raises"]["type"] for r in artists if "raises" in r} == {"HarpTabsParseError", "ValueError"}
    assert any(r.get("out") and r["out"].listed == () for r in artists)


# --- the worlds ---------------------------------------------------------------------------------------------------


@contextmanager
def clock() -> Iterator[None]:
    """songs.py's clock at ``ADDED``, and no info.json (the viewer's, milestone 5's)."""
    with mock.patch("caracole.songs.utc_now_iso", lambda: ADDED), \
            mock.patch("caracole.harptabs_fetch.write_info", lambda *a, **k: None):
        yield


def rows_of(o, display: str) -> list[dict[str, str]]:
    """The phone's ``phone_overrides`` rows of ``o``, as the phone holds overrides.toml (phone.sql)."""
    from caracole import canonical as c
    from caracole.overrides import SONG_TABLES, song_entries

    rows = []
    keys = sorted({k for t in SONG_TABLES for k in getattr(o, t)} | set(o.ignore))
    for key in keys:
        entries = song_entries(o, key)
        for table in (*SONG_TABLES, "ignore"):
            if table in entries:
                rows.append({"tbl": table, "key": key, "written": display, "value": c.dumps(entries[table])})
    return sorted(rows, key=lambda r: (r["tbl"], r["key"]))


def _stamped(done: dict[str, Any], before: list[dict[str, Any]]) -> None:
    """keep_file's ``created_at``, SQLite's clock: each files row it wrote holds a time of that form now, recorded as
    ``STAMP``, the time the phone's writer is given."""
    old = {r["row"]["id"]: r["row"]["created_at"] for r in before if r.get("table") == "files"}
    for row in done["rows"].get("files", []):
        if old.get(row["id"]) == row["created_at"]:
            continue
        stamp = row["created_at"]
        assert _STAMPED.fullmatch(stamp), stamp
        at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        assert abs(datetime.now(UTC) - at) < timedelta(minutes=5), stamp
        row["created_at"] = STAMP


class _Kept:
    """A connection whose close() is a command's ``closing(open_db(cfg))``'s alone: the world keeps it open."""

    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name: str):
        return getattr(self.conn, name)

    def close(self) -> None:
        pass


class World:
    """A phone's library: its database (harptabs.com's index as the computer's sitemap read left it), its library
    folder, its config and its overrides."""

    def __init__(self, tmp: Path, name: str, *, toml: str = "", extra: tuple[str, ...] = (), index: bool = True):
        from caracole import db
        from caracole.config import load_config

        self.dir = tmp / name
        self.dir.mkdir(parents=True)
        self.library = self.dir / "library"
        self.library.mkdir()
        (self.dir / "caracole.toml").write_text(
            f'library_dir = "{self.library}"\nstate_dir = "{self.dir / "state"}"\n'
            f'cache_dir = "{self.dir / "cache"}"\n{toml}', encoding="utf-8")
        self.cfg = load_config(self.dir / "caracole.toml", env={"HOME": str(self.dir / "home")})
        self.conn = db.connect(self.dir / "caracole.sqlite")
        phone_schema(self.conn)
        self.records = 0
        self.overrides = None
        if index:
            self.sitemap(extra)

    def sitemap(self, extra: tuple[str, ...]) -> None:
        """harptabs.com's index as the computer's nightly run reads it, the fixture sitemap with ``extra`` pages."""
        from caracole import site_index
        from caracole.harptabs_fetch import SITE, ensure_current_keys

        site = FakeHarpTabs()
        if extra:
            locs = "".join(f"<url><loc>{BASE}/{p}</loc></url>" for p in extra)
            site.pages[SITEMAP] = (200, fixture("sitemap.xml").replace("</urlset>", locs + "</urlset>"),
                                   {"Content-Type": "application/xml"})
        client = site.client(self.dir / "sitemap-cache", now=SITEMAP_READ)
        try:
            ensure_current_keys(self.conn)
            site_index.refresh(self.conn, client, SITE, SITEMAP_READ)
        finally:
            client.close()

    def song(self, artist: str, title: str, *, artists: list[str] | None = None, added: str = ADDED):
        from caracole.normalize import identity_key
        from caracole.songs import get_song, upsert_song

        with clock():
            song_id, _ = upsert_song(self.conn, artists=artists or [artist], title=title, album=None,
                                     duration_ms=None, isrc=None, source="wanted",
                                     source_id=identity_key(artist, title), added_at=added)
        return get_song(self.conn, song_id)

    def kv(self, key: str, value: str) -> None:
        from caracole.db import kv_set

        kv_set(self.conn, key, value)

    def keep(self, song, tab_id: str, name: str, data: bytes) -> None:
        """A harmonica tab the song keeps already, as a pass kept it."""
        from caracole.library import keep_file
        from caracole.versions import upsert_version

        version = upsert_version(self.conn, provider="harptabs", tab_id=tab_id, song_id=song.id, slot="guitar",
                                 kind="harmonica", rating=0.0, votes=0, version=1, label=None,
                                 url=url(f"tab/{tab_id}/x"), raw={}, now=ADDED)
        keep_file(self.conn, self.library, song=song, version_id=version, name=name, data=data, rank=1)
        self.conn.execute("UPDATE files SET created_at = ?", (ADDED,))

    def file(self, song, name: str, data: str) -> None:
        """A file of the song's folder caracole doesn't keep (put there by hand)."""
        from caracole.library import song_dir, write_atomic

        write_atomic(song_dir(self.library, song) / name, data.encode("utf-8"))

    def write_overrides(self, toml: str, display: str) -> None:
        from caracole.overrides import load_overrides

        path = self.dir / "overrides.toml"
        path.write_text(toml, encoding="utf-8")
        self.overrides = load_overrides(path)
        self.conn.execute("DELETE FROM phone_overrides")
        for row in rows_of(self.overrides, display):
            self.conn.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)",
                              (row["tbl"], row["key"], row["written"], row["value"]))

    def settings(self) -> None:
        """The config's settings as the phone keeps them (kv ``phone:settings``)."""
        from caracole.politeness import settings_document

        self.kv("phone:settings", json.dumps(settings_document(self.cfg)))

    def record(self, fn: str, case: str, call, kw: dict[str, Any], answers: dict[str, dict[str, Any]],
               cache: dict[str, Any] | None = None, budget: int = 6) -> dict[str, Any]:
        from caracole.config import DEFAULT_USER_AGENT

        self.records += 1
        with clock():
            made = record(self.conn, self.library, fn=fn, case=case, call=call, kw=kw, now=NOW,
                          clients={"harptabs": {"budget": budget, "delay": [0.0, 0.0]}}, answers=answers,
                          cache={"harptabs": cache} if cache else None, cache_dir=self.dir / f"cache-{self.records}")
        done = made.get("out") or made["after"]
        _stamped(done, made["fixture"])
        made["answers"] = {r: a for r, a in made["answers"].items() if r in done["requests"]}  # what was asked alone
        made["agent"] = DEFAULT_USER_AGENT
        return made

    def close(self) -> None:
        self.conn.close()


def stats_of(s) -> dict[str, Any]:
    """A pass's stats as a record holds them."""
    return {"tried": s.tried, "errors": s.errors, "budget_exhausted": s.budget_exhausted,
            "failures": [[song.id, type(e).__name__, str(e)] for song, e in s.failures],
            "sitemaps": s.sitemaps, "kept": s.kept, "missing": s.missing}


# --- harptabs_fetch.harptabs_tabs for one song, and get.py's stage ------------------------------------------------


KNOCKIN = ("artist/1283/bob-dylan", "tab/1247/knockin-on-heavens-door", "tab/29910/knockin-on-heavens-door")
# A title longer than a folder's name holds (library.MAX_NAME_BYTES): two songs of it make one folder.
LONG = ("Concierto de Aranjuez para guitarra y orquesta, segundo movimiento, adagio, en la versión que tocaba la "
        "banda en sus conciertos de mil novecientos ochenta y siete")


class Lookups:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.n = 0
        self.records: list[dict[str, Any]] = []

    def world(self, **kw: Any) -> World:
        self.n += 1
        return World(self.tmp, f"lookup-{self.n}", **kw)

    def tabs(self, w: World, case: str, song, answers: dict[str, dict[str, Any]], *, cache=None, budget: int = 6):
        from caracole.harptabs_fetch import harptabs_tabs

        def call(made):
            return stats_of(harptabs_tabs(w.conn, made["harptabs"], w.library, NOW, overrides=w.overrides,
                                          only={song.id}, refresh_index=False))

        rec = w.record("caracole.harptabs_fetch.harptabs_tabs", case, call, {"only": [song.id]},
                       {f"GET {u}": a for u, a in answers.items()}, cache=cache, budget=budget)
        self.records.append(rec)
        return rec

    def stage(self, w: World, case: str, song, answers: dict[str, dict[str, Any]], *, cache=None, budget: int = 6):
        from caracole.get import LookupRequest, Progress, _Lookup
        from caracole.overrides import Overrides
        from caracole.songs import get_song

        def call(made):
            lk = _Lookup(w.cfg, LookupRequest(song.artist, song.title), Progress(), runner=None, now=NOW,
                         clock=lambda: 0.0)
            lk.conn, lk.song, lk.overrides = w.conn, get_song(w.conn, song.id), w.overrides or Overrides()
            lk.clients = dict(made)
            out = lk.harptabs()
            return list(out) if isinstance(out, tuple) else ["done", out]

        rec = w.record("caracole.get._Lookup.harptabs", case, call, {"only": [song.id]},
                       {f"GET {u}": a for u, a in answers.items()}, cache=cache, budget=budget)
        self.records.append(rec)
        return rec

    def build(self) -> list[dict[str, Any]]:  # noqa: PLR0915 (one case after another)
        bamba, piano = url("tab/89/la-bamba"), url("tab/25/piano-man")
        other_piano = url("tab/29525/piano-man")

        w = self.world()
        self.tabs(w, "a song gets the tab by its artist, kept as harmonica-1.txt",
                  w.song("Ritchie Valens", "La Bamba"), {bamba: ok("tab_89_la-bamba.html")})

        w = self.world()
        self.tabs(w, "the most viewed of the artist's tabs is kept, another artist's never",
                  w.song("Billy Joel", "Piano Man"),
                  {piano: ok("tab_25_piano-man.html"),
                   other_piano: ok(mini_tab("Piano Man", "Billy Joel", views="2.5M", body="6 6 6\nmine\n"))})

        w = self.world()
        self.tabs(w, "a title by other artists alone is a miss, asked again after 30 days",
                  w.song("Billy Joel", "Piano Man"),
                  {piano: ok(mini_tab("piano man", "Someone Else")),
                   other_piano: ok(mini_tab("piano man", "Another One"))})

        w = self.world()
        song = w.song("Billy Joel", "Piano Man")
        w.kv(f"harptabs:checked:{song.id}", LATELY)
        self.tabs(w, "a miss within 30 days asks nothing", song, {})
        w = self.world()
        song = w.song("Billy Joel", "Piano Man")
        w.kv(f"harptabs:checked:{song.id}", LONG_AGO)
        self.tabs(w, "a miss over 30 days ago is asked again", song,
                  {piano: ok("tab_25_piano-man.html"), other_piano: status(404)})
        w = self.world()
        song = w.song("Billy Joel", "Piano Man")
        w.kv(f"harptabs:checked:{song.id}", "not a time")
        self.tabs(w, "a checked record that is no time is older than any", song,
                  {piano: ok("tab_25_piano-man.html"), other_piano: status(404)})

        knockin, unknowns = url(KNOCKIN[1]), url(KNOCKIN[2])
        dylans = ok(mini_tab("Knockin' On Heaven's Door", "Bob Dylan", views="57k", body="-4 -4 4\nmine\n"))
        w = self.world(extra=KNOCKIN)
        self.tabs(w, "a tab page of no artist is passed over as another artist's is",
                  w.song("Bob Dylan", "Knockin' on Heaven's Door"),
                  {knockin: dylans, unknowns: ok("tab_29910_knockin-on-heavens-door.html")})
        w = self.world(extra=KNOCKIN)
        self.tabs(w, "a title whose one tab is of no artist is a miss", w.song("Bob Dylan", "Knockin' on Heaven's Door"),
                  {knockin: status(404), unknowns: ok("tab_29910_knockin-on-heavens-door.html")})
        w = self.world(extra=KNOCKIN)
        song = w.song("Bob Dylan", "Knockin' on Heaven's Door")
        w.write_overrides(f'[harptabs]\n"{song.display}" = "{unknowns}"\n', song.display)
        self.tabs(w, "a tab of no artist you picked is kept", song,
                  {unknowns: ok("tab_29910_knockin-on-heavens-door.html")})

        nowhere = ("artist/1283/bob-dylan", "tab/1690/you-ain-t-goin-nowhere")
        w = self.world(extra=nowhere)
        self.tabs(w, "a title with an apostrophe meets the slug that writes it as a hyphen",
                  w.song("Bob Dylan", "You Ain't Goin' Nowhere"),
                  {url(nowhere[1]): ok(mini_tab("You Ain't Goin' Nowhere", "Bob Dylan", body="4 5\nmine\n"))})
        w = self.world(extra=nowhere)
        w.conn.execute("UPDATE harptabs_index SET key = 'you-ain-t-goin-nowhere' WHERE path = ?", (nowhere[1],))
        w.kv("harptabs:index:keys", "0")
        self.tabs(w, "a lookup keys a table keyed before again from its paths and meets the tab",
                  w.song("Bob Dylan", "You Ain't Goin' Nowhere"),
                  {url(nowhere[1]): ok(mini_tab("You Ain't Goin' Nowhere", "Bob Dylan", body="4 5\nmine\n"))})
        w = self.world(extra=("tab/77/o-brien-s-lament", "artist/91/the-dubliners"))
        self.tabs(w, "an apostrophe that ends no contraction meets its slug as a hyphen",
                  w.song("The Dubliners", "O'Brien's Lament"),
                  {url("tab/77/o-brien-s-lament"): ok(mini_tab("O'Brien's Lament", "The Dubliners"))})

        w = self.world()
        self._joel_page(w)
        c_harp = url("tab/23862/piano-man-c-harmonica")
        self.tabs(w, "the tabs of the title the artist's page lists are tried first, the most viewed first",
                  w.song("Billy Joel", "Piano Man"),
                  {piano: ok("tab_25_piano-man.html"),
                   c_harp: ok(mini_tab("Piano Man (C Harmonica)", "billy joel", views="2.5M", body="6 6 6\nin C\n")),
                   url("tab/9925/piano-man-harmonica-intro"): status(404),
                   url("tab/1256/piano-man-harp-intro"): status(404), other_piano: status(404)}, budget=8)

        w = self.world()
        self.tabs(w, "a song whose artist the sitemap doesn't list costs no page", w.song("Mariah Carey", "Silent Night"),
                  {})
        w = self.world(index=False)
        self.tabs(w, "an empty index asks nothing", w.song("Ritchie Valens", "La Bamba"), {})
        w = self.world()
        self.tabs(w, "a title with no key has no candidate", w.song("Ritchie Valens", "!!!"), {})

        w = self.world()
        song = w.song("Ritchie Valens", "La Bamba")
        w.keep(song, "1", "harmonica-1.txt", b"mine")
        self.tabs(w, "a song with a harmonica tab gets no other", song, {})
        w = self.world()
        song = w.song("Ritchie Valens", "La Bamba")
        w.file(song, "harmonica-1.txt", "put there by hand")
        self.tabs(w, "a number a file of the folder holds is never reused", song, {bamba: ok("tab_89_la-bamba.html")})
        w = self.world()
        song = w.song("Ritchie Valens", "La Bamba")
        w.file(song, "harmonica-1.html", "my own notes")
        self.tabs(w, "a page of yours by a tab's page name holds its number too", song,
                  {bamba: ok("tab_89_la-bamba.html")})

        broken = "<html><body>Something went wrong</body></html>"
        w = self.world()
        self.tabs(w, "a page that won't parse is an error, never a miss", w.song("Ritchie Valens", "La Bamba"),
                  {bamba: ok(broken)})
        w = self.world()
        self.tabs(w, "a cached page that won't parse is asked for once more, and read", w.song("Ritchie Valens", "La Bamba"),
                  {bamba: ok("tab_89_la-bamba.html")}, cache={f"GET {bamba}": held(ok(broken))})
        w = self.world()
        self.tabs(w, "a cached page that won't parse, asked again, is an error", w.song("Ritchie Valens", "La Bamba"),
                  {bamba: ok(broken)}, cache={f"GET {bamba}": held(ok(broken))})
        w = self.world()
        self.tabs(w, "a page the cache holds is read from it", w.song("Ritchie Valens", "La Bamba"), {},
                  cache={f"GET {bamba}": held(ok("tab_89_la-bamba.html"), OLD_FETCH)})
        w = self.world()
        self.tabs(w, "a server error leaves the song for the next run", w.song("Ritchie Valens", "La Bamba"),
                  {bamba: status(530, "<title>Connection Error - Harptabs.com</title>")})
        w = self.world()
        self.tabs(w, "a count past SQLite's integers on another artist's page is passed over as any",
                  w.song("Billy Joel", "Piano Man"),
                  {piano: ok("tab_25_piano-man.html"), other_piano: ok(mini_tab("Piano Man", "Someone Else", views=HUGE))})
        w = self.world()
        self.tabs(w, "a tab kept whose count is past SQLite's integers is its OverflowError, nothing kept",
                  w.song("Ritchie Valens", "La Bamba"), {bamba: ok(mini_tab("La Bamba", "Ritchie Valens", views=HUGE))})
        w = self.world()
        self.tabs(w, "a tab gone since the sitemap listed it is passed over", w.song("Billy Joel", "Piano Man"),
                  {piano: status(404), other_piano: ok(mini_tab("Piano Man", "Billy Joel"))})
        w = self.world()
        self.tabs(w, "a block propagates and keeps nothing", w.song("Ritchie Valens", "La Bamba"),
                  {bamba: status(403, "Forbidden")})
        w = self.world()
        self.tabs(w, "a 429 is a block too", w.song("Ritchie Valens", "La Bamba"), {bamba: status(429, "Slow down")})
        w = self.world()
        self.tabs(w, "a spent budget ends the pass, the song checked never", w.song("Billy Joel", "Piano Man"),
                  {piano: ok("tab_25_piano-man.html"),
                   other_piano: ok(mini_tab("Piano Man", "Billy Joel", views="2.5M"))}, budget=1)
        w = self.world()
        self.tabs(w, "a pass the budget cut short resumes from the cache", w.song("Billy Joel", "Piano Man"),
                  {other_piano: ok(mini_tab("Piano Man", "Billy Joel", views="2.5M"))}, budget=1,
                  cache={f"GET {piano}": held(ok("tab_25_piano-man.html"))})
        w = self.world()
        bamba_song = w.song("Ritchie Valens", "La Bamba")
        w.write_overrides(f'[ignore]\nsongs = ["{bamba_song.display}"]\n', bamba_song.display)
        self.tabs(w, "an ignored song is left alone", bamba_song, {})

        many = tuple(f"tab/{n}/piano-man" for n in range(100, 120))
        w = self.world(extra=many)
        self.tabs(w, "at most a handful of candidates are read for one title, lowest id first",
                  w.song("Billy Joel", "Piano Man"),
                  {piano: ok(mini_tab("piano man", "Someone Else")),
                   **{url(p): status(404) for p in many}, other_piano: status(404)}, budget=10)

        ties = ("tab/40/piano-man", "tab/41/piano-man", "tab/42/piano-man")
        w = self.world(extra=ties)
        self.tabs(w, "of equal views the best rated is kept, then the first posted", w.song("Billy Joel", "Piano Man"),
                  {piano: ok(mini_tab("Piano Man", "Billy Joel", views="3M", body="25\n")),
                   url(ties[0]): ok(mini_tab("Piano Man", "Billy Joel", views="3M", body="40\n")),
                   url(ties[1]): ok(mini_tab("Piano Man", "Billy Joel", views="3M", body="41\n", rating="4.5")),
                   url(ties[2]): ok(mini_tab("Piano Man", "Billy Joel", views="3M", body="42\n", rating="4.5")),
                   other_piano: status(404)})

        w = self.world(extra=("artist/60/art-garfunkel", "tab/61/the-boxer"))
        self.tabs(w, "a tab by the song's second artist is the song's", w.song(
            "Simon & Garfunkel", "The Boxer", artists=["Paul Simon", "Art Garfunkel"]),
            {url("tab/61/the-boxer"): ok(mini_tab("The Boxer", "Art Garfunkel"))})
        w = self.world(extra=("artist/70/song-dong-ye", "tab/71/ban-ma"))
        self.tabs(w, "an artist in Chinese meets their slug in pinyin", w.song("宋冬野", "Ban Ma"),
                  {url("tab/71/ban-ma"): ok(mini_tab("Ban Ma", "Song Dongye"))})
        w = self.world(extra=("artist/70/song-dong-ye",))
        self.tabs(w, "a title in Chinese meets no slug", w.song("宋冬野", "斑马斑马"), {})
        w = self.world(extra=("artist/80/guns-n-roses", "tab/81/patience"))
        self.tabs(w, "an artist's name compared hyphens aside", w.song("Guns N' Roses", "Patience"),
                  {url("tab/81/patience"): ok(mini_tab("Patience", "Guns N Roses"))})

        c_harp_page = ok(mini_tab("Piano Man (C Harmonica)", "Pharm Gal", body="6 6 6\npick\n"))
        w = self.world()
        song = w.song("Billy Joel", "Piano Man")
        w.write_overrides(f'[harptabs]\n"{song.display}" = "{c_harp}"\n', song.display)
        self.tabs(w, "the tab you picked is kept whoever its page names", song, {c_harp: c_harp_page})
        w = self.world()
        song = w.song("Billy Joel", "Piano Man")
        w.keep(song, "25", "harmonica-1.txt", b"25")
        w.kv(f"harptabs:checked:{song.id}", LATELY)
        w.write_overrides(f'[harptabs]\n"{song.display}" = "{c_harp}"\n', song.display)
        self.tabs(w, "a pick is kept beside the tab the song has, at once", song, {c_harp: c_harp_page})
        w = self.world()
        song = w.song("Billy Joel", "Piano Man")
        w.keep(song, "23862", "harmonica-1.txt", b"pick")
        w.kv(f"harptabs:checked:{song.id}", LONG_AGO)
        w.kv(f"harptabs:checked:{song.id}:pick", "23862")
        w.write_overrides(f'[harptabs]\n"{song.display}" = "{c_harp}"\n', song.display)
        self.tabs(w, "a pick kept is asked for no more", song, {})
        w = self.world()
        song = w.song("Billy Joel", "Piano Man")
        w.kv(f"harptabs:checked:{song.id}", LATELY)
        w.kv(f"harptabs:checked:{song.id}:pick", "404")
        w.write_overrides(f'[harptabs]\n"{song.display}" = "{url("tab/404/gone")}"\n', song.display)
        self.tabs(w, "a pick gone asked for this month waits", song, {})
        w = self.world()
        song = w.song("Billy Joel", "Piano Man")
        w.write_overrides(f'[harptabs]\n"{song.display}" = "{url("tab/404/gone")}"\n', song.display)
        self.tabs(w, "a pick gone is a miss, asked about again after 30 days", song,
                  {url("tab/404/gone"): status(404)})

        # get.py's harptabs stage: its own words, and its envelope's
        w = self.world()
        self.stage(w, "the stage: a tab kept", w.song("Ritchie Valens", "La Bamba"), {bamba: ok("tab_89_la-bamba.html")})
        w = self.world()
        self.stage(w, "the stage: no tab there by the artist", w.song("Billy Joel", "Piano Man"),
                   {piano: ok(mini_tab("piano man", "Someone Else")), other_piano: status(404)})
        w = self.world()
        self.stage(w, "the stage: no candidate", w.song("Mariah Carey", "Silent Night"), {})
        w = self.world()
        self.stage(w, "the stage: a page that won't parse", w.song("Ritchie Valens", "La Bamba"), {bamba: ok(broken)})
        w = self.world()
        self.stage(w, "the stage: a block", w.song("Ritchie Valens", "La Bamba"), {bamba: status(403, "Forbidden")})
        w = self.world(extra=many)
        self.stage(w, "the stage: the lookup's requests spent", w.song("Billy Joel", "Piano Man"),
                   {piano: ok(mini_tab("piano man", "Someone Else")), **{url(p): status(404) for p in many}})
        w = self.world()
        self.stage(w, "the stage: the hour's lookup requests spent", w.song("Billy Joel", "Piano Man"),
                   {piano: ok(mini_tab("piano man", "Someone Else"))}, budget=1)
        w = self.world()
        w.kv("provider:harptabs", json.dumps({"strikes": 1, "cooldown_until": "2026-11-04T14:00:00Z", "last_ok": None,
                                              "last_error": "403", "last_error_at": "2026-11-03T10:00:00Z"}))
        self.stage(w, "the stage: cooling down after a block", w.song("Ritchie Valens", "La Bamba"), {})
        w = self.world()
        w.kv("provider:harptabs", json.dumps({"strikes": 1, "cooldown_until": "2026-11-03T11:00:00Z", "last_ok": None,
                                              "last_error": "403", "last_error_at": "2026-11-01T09:00:00Z"}))
        self.stage(w, "the stage: a cooldown over asks again", w.song("Ritchie Valens", "La Bamba"),
                   {bamba: ok("tab_89_la-bamba.html")})
        self._shared_folder()
        return self.records

    def _shared_folder(self) -> None:
        """Two songs whose titles agree up to a folder name's length (library.MAX_NAME_BYTES) make one folder, where
        the first keeps harmonica-1.txt: the second's tab is harmonica-2.txt (harmonica_number takes no number another
        song keeps there), so keep_file meets no SharedFolder."""
        from caracole.harptabs import title_keys
        from caracole.library import song_dir

        first, second = f"{LONG}, part one", f"{LONG}, part two"
        tab = f"tab/4242/{title_keys(second)[0]}"
        w = self.world(extra=("artist/4241/joaquin-rodrigo", tab))
        one = w.song("Joaquín Rodrigo", first)
        two = w.song("Joaquín Rodrigo", second)
        assert one.id != two.id and song_dir(w.library, one) == song_dir(w.library, two)
        w.keep(one, "4240", "harmonica-1.txt", b"part one")
        self.stage(w, "the stage: a number another song keeps in the folder they share is never taken", two,
                   {url(tab): ok(mini_tab(second, "Joaquín Rodrigo", body="-4 5\nadagio\n"))})

    @staticmethod
    def _joel_page(w: World) -> None:
        from caracole.harptabs import parse_artist_page
        from caracole.harptabs_index import store_artist_page

        store_artist_page(w.conn, "artist/1178/billy-joel", parse_artist_page(fixture("artist_1178_billy-joel.html")),
                          SITEMAP_READ)


@pytest.fixture(scope="module")
def lookups(tmp_path_factory) -> list[dict[str, Any]]:
    return Lookups(tmp_path_factory.mktemp("harptabs-lookups")).build()


def test_harptabs_lookup_jsonl(lookups):
    check(LOOKUP_FILE, jsonl(lookups, corpus="lookup/harptabs", made_by=MADE_BY))


def _done(rec: dict[str, Any]) -> dict[str, Any]:
    return rec.get("out") or rec["after"]


def test_the_lookups_cover_each_outcome(lookups):
    passes = {r["case"]: r for r in lookups if r["fn"].endswith("harptabs_tabs")}
    results = [r["out"]["result"] for r in passes.values() if "out" in r]
    assert any(s["kept"] for s in results) and any(s["missing"] for s in results)
    assert any(s["failures"] for s in results) and any(s["budget_exhausted"] for s in results)
    assert any(s["tried"] == 0 for s in results)
    assert {r["raises"]["type"] for r in passes.values() if "raises" in r} == {"ProviderBlocked", "OverflowError"}
    kept = passes["a song gets the tab by its artist, kept as harmonica-1.txt"]["out"]
    assert [row["name"] for row in kept["rows"]["files"]] == ["harmonica-1.txt"]
    assert kept["requests"] == [f"GET {url('tab/89/la-bamba')}"]
    assert passes["at most a handful of candidates are read for one title, lowest id first"]["out"]["requests"][:2] == [
        f"GET {url('tab/25/piano-man')}", f"GET {url('tab/100/piano-man')}"]
    assert len(passes["at most a handful of candidates are read for one title, lowest id first"]["out"]["requests"]) \
        == 8
    stages = {r["case"]: _done(r).get("result") for r in lookups if r["fn"].endswith("_Lookup.harptabs")}
    assert stages["the stage: a tab kept"] == ["done", "harmonica tab kept"]
    shared = next(r for r in lookups if r["case"].startswith("the stage: a number another song keeps"))["out"]
    assert shared["result"] == ["done", "harmonica tab kept"]
    assert [row["name"] for row in shared["rows"]["files"]] == ["harmonica-1.txt", "harmonica-2.txt"]
    assert {s[0] for s in stages.values()} == {"done", "skipped", "failed"}


# --- harptabs_index.read_artist, and artist_paths -----------------------------------------------------------------


class Artists:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.n = 0
        self.records: list[dict[str, Any]] = []

    def world(self, **kw: Any) -> World:
        self.n += 1
        return World(self.tmp, f"artist-{self.n}", **kw)

    def read(self, w: World, case: str, path: str, answers: dict[str, dict[str, Any]], *, cache=None, budget: int = 6):
        from caracole.harptabs_index import read_artist

        def call(made):
            return read_artist(w.conn, made["harptabs"], path, NOW)

        rec = w.record("caracole.harptabs_index.read_artist", case, call, {"path": path},
                       {f"GET {u}": a for u, a in answers.items()}, cache=cache, budget=budget)
        done = _done(rec)
        rec["reads"] = sorted(r["path"] for r in done["rows"].get("harptabs_artists", []) if r["read_at"] == STAMP)
        self.records.append(rec)
        return rec

    def build(self) -> list[dict[str, Any]]:
        joel = url("artist/1178/billy-joel")
        w = self.world()
        self.read(w, "an artist's page read into the index now", "artist/1178/billy-joel",
                  {joel: ok("artist_1178_billy-joel.html")})
        w = self.world()
        self.read(w, "a page the cache holds from within 30 days is read again with no request",
                  "artist/1178/billy-joel", {}, cache={f"GET {joel}": held(ok("artist_1178_billy-joel.html"))})
        w = self.world()
        self.read(w, "a page the cache holds from before them is asked for again", "artist/1178/billy-joel",
                  {joel: ok("artist_1178_billy-joel.html")},
                  cache={f"GET {joel}": held(ok("artist_1178_billy-joel.html"), OLD_FETCH)})
        w = self.world()
        self.read(w, "an old copy with the budget spent is no answer for today", "artist/1178/billy-joel", {},
                  cache={f"GET {joel}": held(ok("artist_1178_billy-joel.html"), OLD_FETCH)}, budget=0)
        w = self.world()
        self.read(w, "no copy and the budget spent", "artist/1178/billy-joel", {}, budget=0)
        w = self.world()
        self.read(w, "an artist's page gone keeps no tab", "artist/50/the-beatles",
                  {url("artist/50/the-beatles"): status(404)})
        w = self.world()
        self.read(w, "a page that won't parse is an error and stores nothing", "artist/1178/billy-joel",
                  {joel: ok("<html><body><main><p>98 tabs</p></main></body></html>")})
        w = self.world()
        self.read(w, "a cached page that won't parse is asked for once more", "artist/1178/billy-joel",
                  {joel: ok("artist_1178_billy-joel.html")},
                  cache={f"GET {joel}": held(ok("<html><body>maintenance</body></html>"))})
        w = self.world()
        self.read(w, "a block propagates", "artist/1178/billy-joel", {joel: status(403, "Forbidden")})
        w = self.world()
        self.read(w, "a server error propagates", "artist/1178/billy-joel", {joel: status(500, "oops")})
        w = self.world()
        self.read(w, "the site's catch-all, a path of no slug", "artist/4", {url("artist/4"): ok("artist_4.html")})
        w = self.world()
        Lookups._joel_page(w)
        w.conn.execute("UPDATE harptabs_artist_tabs SET song_key = 'stale'")
        w.kv("harptabs:artists:keys", "0")
        self.read(w, "a page read again replaces its tabs, the songs' keys made current first",
                  "artist/1178/billy-joel",
                  {joel: ok(mini_artist("billy joel", [card(25, "piano-man", "piano man"), card(77, "new-one", "New One")]))})
        w = self.world()
        Lookups._joel_page(w)
        self.read(w, "a page gone since it was read forgets its tabs", "artist/1178/billy-joel", {joel: status(404)})
        w = self.world()
        Lookups._joel_page(w)
        self.read(w, "a tab's count past SQLite's integers is its OverflowError, the tabs read before kept",
                  "artist/1178/billy-joel",
                  {joel: ok(mini_artist("billy joel", [card(25, "piano-man", "piano man"),
                                                       card(77, "new-one", "New One", views=HUGE)]))})
        w = self.world()
        self.read(w, "a count of tabs past SQLite's integers is its OverflowError", "artist/1178/billy-joel",
                  {joel: ok(mini_artist("billy joel", [card(25, "piano-man", "piano man")],
                                        said="99999999999999999999 tabs"))})
        self.records.append(self.paths())
        return self.records

    def paths(self) -> dict[str, Any]:
        from caracole.harptabs_index import artist_paths
        from helpers.corpus import dump_fixture

        w = self.world(extra=("artist/60/the-beatles", "artist/80/guns-n-roses", "artist/70/song-dong-ye",
                              "artist/90/a-b"))
        names = ["Billy Joel", "billy joel", "  Billy   Joel ", "The Beatles", "beatles", "Beatles, The",
                 "artist/7829/ritchie-valens", f"{BASE}/artist/7829/ritchie-valens", "harptabs.com/artist/7829/ritchie-valens",
                 "http://harptabs.com/artist/7829/ritchie-valens/", "www.harptabs.com/artist/1178/billy-joel",
                 "artist/9/nobody", "Nobody", "", "   ", "Guns N' Roses", "Guns N Roses", "宋冬野", "A-B", "a b",
                 "artist/4", f"{BASE}/artist/4", "tab/25/piano-man", "artist/1178/Billy-Joel"]
        return {"fn": "caracole.harptabs_index.artist_paths", "case": "an artist's pages by name, path or address",
                "fixture": dump_fixture(w.conn), "cases": [[n, artist_paths(w.conn, n)] for n in names]}


@pytest.fixture(scope="module")
def artists(tmp_path_factory) -> list[dict[str, Any]]:
    return Artists(tmp_path_factory.mktemp("harptabs-artists")).build()


def test_harptabs_artist_jsonl(artists):
    check(ARTIST_FILE, jsonl(artists, corpus="lookup/harptabs_artist", made_by=MADE_BY))


def test_the_artist_reads_cover_each_outcome(artists):
    reads = {r["case"]: r for r in artists if r["fn"].endswith("read_artist")}
    assert reads["an artist's page read into the index now"]["reads"] == ["artist/1178/billy-joel"]
    assert reads["an artist's page gone keeps no tab"]["out"]["result"] is None
    assert reads["an artist's page gone keeps no tab"]["reads"] == ["artist/50/the-beatles"]
    assert reads["a page the cache holds from within 30 days is read again with no request"]["out"]["requests"] == []
    assert {r["raises"]["type"] for r in reads.values() if "raises" in r} == {
        "BudgetExhausted", "HarpTabsParseError", "ProviderBlocked", "ProviderError", "OverflowError"}
    [paths] = [r for r in artists if r["fn"].endswith("artist_paths")]
    assert dict(map(tuple, paths["cases"]))["Billy Joel"] == ["artist/1178/billy-joel"]
    assert dict(map(tuple, paths["cases"]))["The Beatles"] == ["artist/50/the-beatles", "artist/60/the-beatles"]


# --- caracole harptabs --artist ------------------------------------------------------------------------------------


class Commands:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.n = 0
        self.records: list[dict[str, Any]] = []

    def world(self, **kw: Any) -> World:
        self.n += 1
        return World(self.tmp, f"command-{self.n}", **kw)

    def run(self, w: World, case: str, artist: str, answers: dict[str, dict[str, Any]], *, cache=None,
            budget: int = 6):
        from caracole.commands import lyrics

        def call(made):
            lines: list[str] = []
            with mock.patch.object(lyrics, "make_client", lambda *a, **k: made["harptabs"]), \
                    mock.patch.object(lyrics, "open_db", lambda cfg: _Kept(w.conn)), \
                    mock.patch.object(lyrics, "utcnow", lambda: NOW), \
                    mock.patch("typer.echo", lambda message="", **k: lines.append(str(message))):
                lyrics._harptabs_artist(w.cfg, " ".join(artist.split()))
            return lines

        rec = w.record("caracole.commands.lyrics._harptabs_artist", case, call, {"artist": " ".join(artist.split())},
                       {f"GET {u}": a for u, a in answers.items()}, cache=cache, budget=budget)
        done = _done(rec)
        rec["reads"] = sorted(r["path"] for r in done["rows"].get("harptabs_artists", []) if r["read_at"] == STAMP)
        self.records.append(rec)
        return rec

    def build(self) -> list[dict[str, Any]]:
        joel = url("artist/1178/billy-joel")
        w = self.world()
        self.run(w, "an artist's page read now, by their name", "Billy Joel", {joel: ok("artist_1178_billy-joel.html")})
        w = self.world()
        self.run(w, "by its page, read within 30 days: no request", "artist/1178/billy-joel", {},
                 cache={f"GET {joel}": held(ok("artist_1178_billy-joel.html"))})
        w = self.world()
        self.run(w, "by its address", f"{BASE}/artist/7829/ritchie-valens",
                 {url("artist/7829/ritchie-valens"): ok(mini_artist("ritchie valens", [card(89, "la-bamba", "La Bamba")]))})
        w = self.world()
        self.run(w, "an artist with no tab", "Ritchie Valens",
                 {url("artist/7829/ritchie-valens"): ok(mini_artist("ritchie valens", []))})
        w = self.world()
        self.run(w, "their tabs, all listed", "Ritchie Valens",
                 {url("artist/7829/ritchie-valens"): ok(mini_artist("ritchie valens", [card(89, "la-bamba", "La Bamba"),
                                                                            card(90, "donna", "Donna")]))})
        w = self.world()
        self.run(w, "the sitemap lists no page of the name", "Nobody Known", {})
        w = self.world(index=False)
        self.run(w, "the index empty", "Billy Joel", {})
        w = self.world()
        self.run(w, "a page gone", "The Beatles", {url("artist/50/the-beatles"): status(404)})
        w = self.world()
        self.run(w, "a block", "Ritchie Valens", {url("artist/7829/ritchie-valens"): status(403, "Forbidden")})
        w = self.world()
        self.run(w, "an error", "Ritchie Valens", {url("artist/7829/ritchie-valens"): status(500, "oops")})
        w = self.world()
        self.run(w, "a page that won't parse", "Billy Joel", {joel: ok("<html><body>gone wrong</body></html>")})
        w = self.world()
        self.run(w, "the hour's lookup requests spent", "Billy Joel", {}, budget=0)
        w = self.world()
        w.kv("provider:harptabs", json.dumps({"strikes": 1, "cooldown_until": "2026-11-04T14:00:00Z", "last_ok": None,
                                              "last_error": "403", "last_error_at": "2026-11-03T10:00:00Z"}))
        self.run(w, "cooling down after a block", "Billy Joel", {})
        w = self.world()
        w.kv("provider:harptabs", json.dumps({"strikes": 2, "cooldown_until": "2026-11-02T14:00:00Z", "last_ok": None,
                                              "last_error": "403", "last_error_at": "2026-11-01T10:00:00Z"}))
        self.run(w, "a cooldown over, a good read clears the strikes", "Billy Joel",
                 {joel: ok("artist_1178_billy-joel.html")})
        w = self.world(toml="[providers.harptabs]\nenabled = false\n")
        w.settings()
        self.run(w, "harptabs.com turned off", "Billy Joel", {})
        return self.records


@pytest.fixture(scope="module")
def commands(tmp_path_factory) -> list[dict[str, Any]]:
    return Commands(tmp_path_factory.mktemp("harptabs-commands")).build()


def test_commands_harptabs_jsonl(commands):
    check(COMMANDS_FILE, jsonl(commands, corpus="lookup/commands_harptabs", made_by=MADE_BY))


def test_the_commands_end_as_caracole_serve_reads_them(commands):
    lines = {r["case"]: _done(r)["result"] for r in commands}
    assert all(len(said) == 1 for said in lines.values())
    assert {said[0].split(": ")[0] for said in lines.values()} == {"Read", "Not found", "Not read"}
    assert lines["an artist's page read now, by their name"] == [
        "Read: harptabs.com's page of billy joel lists 7 of their 98 tabs, in the index now."]
