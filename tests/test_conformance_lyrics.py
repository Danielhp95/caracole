"""LRCLIB, Megalobiz and AZLyrics for a lookup, for the phone's lane lyrics (core.lyrics' ``Lrclib``, ``Megalobiz``
and ``AzLyrics``) to replay: their parsers and pickers over tests/fixtures/{lrclib,megalobiz,azlyrics}, and their
passes for one song as scenario records (tests/helpers/scenario.py, the corpus spec's "Scenario records").

**Parsers and pickers** (``vectors/sites/``), a record a call. A float is written as its ``repr``, a text (so that
``inf`` and ``nan`` pass through JSON), a body as ``{"text"}``, ``{"base64"}`` or a ``corpus.fixture_ref``, a JSON value
a parser is given as the line holds it (its keys sorted, as every line's are), and an error as ``raises``: ``{"type",
"message"}``, the class's name and ``str(e)``.

- ``lrclib.jsonl``:
  - ``Lyrics.from_record`` (the model, skeleton-m4's): ``out`` its fields and ``to_json``'s text;
  - ``fits`` (``out`` ``[band, repr(delta)]`` or null), ``another_version``, ``_search_title`` (``_HAN_GAP``);
  - ``pick_candidate``: ``out`` the index of the record it chose, or null;
  - ``read``: ``/api/get``'s answer read (``_get_record``: null for a 404) or ``/api/search``'s (``_json(r, list)``);
  - ``fetch_lyrics``: the requests a lookup sends, over a client that answers each endpoint as the record says (a
    status it wasn't given to accept is a ``ProviderError``, as ``PoliteClient``'s): each call's URL, params (each
    value as httpx writes it), accept and cache, and what it came to (``status``, and the lyrics' ``to_json``).
- ``megalobiz.jsonl``: ``search_params`` (each value as httpx writes it), ``lrc_url``, ``parse_search`` and
  ``parse_lrc`` (``out`` each record's fields; its lines' stamps as ``f'{ms % 60000 / 1000:05.2f}'`` rounds them, half
  to even on the double), ``pick_result``.
- ``azlyrics.jsonl``: ``artist_url``, ``parse_artist`` (``out`` the name and each song's ``[title, url]``),
  ``parse_lyrics``, ``pick_song``.

**Passes** (``vectors/lookup/``): ``lyrics.fetch_pending_lyrics``, ``megalobiz_fetch.megalobiz_lyrics`` and
``azlyrics_fetch.azlyrics_lyrics`` of one song (``kw.only``, a lookup's), each in a library of its own, over a fake
site: ``out.result`` the pass's stats, ``tried``, ``errors``, ``budget_exhausted``, ``failures`` (each ``[song id, the
error's class, its message]``) and the site's own counts. A miss's 30-day record, an answer that won't read asked for
once more past the cache, LRCLIB's 503 asked once more after its ``Retry-After``, an error that puts a song LRCLIB
missed back to pending, a block (``raises``) and AZLyrics' block page, a 200 never kept in the cache (``out.result``'s
``cached``, asked of the client after the pass); lyrics.txt, lyrics.lrc (``out.library``'s digests) and
``lyrics_json`` (``out.rows.songs``) byte for byte. ``[azlyrics]`` comes to the phone as its ``phone_overrides`` row,
which ``Overrides.read`` reads.

Stamps: songs.py's clock (``utc_now_iso``) is the record's ``now`` while a world is made and a pass runs.
``write_info`` (info.json) is the viewer's, milestone 5's: no pass writes it here, as the phone writes none.

Regenerate with ``CARACOLE_CORPUS=write`` (tests/conformance/README.md).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

import httpx
import pytest

from helpers.corpus import VECTORS, check, fixture_bytes, fixture_ref, jsonl, phone_schema
from helpers.scenario import record

MADE_BY = "tests/test_conformance_lyrics.py"
SITES = VECTORS / "sites"
LOOKUP = VECTORS / "lookup"
FILES = {
    "lrclib-sites": SITES / "lrclib.jsonl",
    "megalobiz-sites": SITES / "megalobiz.jsonl",
    "azlyrics-sites": SITES / "azlyrics.jsonl",
    "lrclib-lookup": LOOKUP / "lrclib.jsonl",
    "megalobiz-lookup": LOOKUP / "megalobiz.jsonl",
    "azlyrics-lookup": LOOKUP / "azlyrics.jsonl",
}

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
STAMP = "2026-11-03T12:00:00Z"
ADDED = "2026-10-01T00:00:00Z"
LONG_AGO = "2026-09-20T12:00:00Z"  # more than 30 days before NOW
LATELY = "2026-10-20T12:00:00Z"  # less than 30 days before NOW
FETCHED = "2026-10-02T09:00:00Z"
JSON = [["content-type", "application/json"]]
HTML = [["content-type", "text/html; charset=utf-8"]]
LRCLIB_GET = "https://lrclib.net/api/get"
LRCLIB_SEARCH = "https://lrclib.net/api/search"


def fl(x: float | None) -> str | None:
    """A float as a record writes it: its repr."""
    return None if x is None else repr(float(x))


def text(s: str) -> dict[str, str]:
    return {"text": s}


def raw_body(data: bytes) -> dict[str, str]:
    import base64

    return {"base64": base64.b64encode(data).decode("ascii")}


def as_line(value: Any) -> Any:
    """A JSON value as a record's line holds it: its keys sorted, as every line's are."""
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))


def raised(e: BaseException) -> dict[str, str]:
    return {"type": type(e).__name__, "message": str(e)}


def load(name: str) -> Any:
    return json.loads(fixture_bytes(fixture_ref(name)))


def response(url: str, status: int, body: dict[str, str]):
    from caracole.http import Response
    from helpers.scenario import _body

    data, _ = _body(body)
    return Response(url=url, status=status, content=data, headers={})


# --- LRCLIB's parsers and pickers -------------------------------------------------------------------------------


def lrclib_record(**fields: Any) -> dict[str, Any]:
    """The get_hit fixture's record with some fields replaced."""
    return {**load("lrclib/get_hit.json"), **fields}


def from_record_records() -> list[dict[str, Any]]:
    from caracole.lyrics import Lyrics

    def one(case: str, given: Any, rec: Any) -> dict[str, Any]:
        lyrics = Lyrics.from_record(rec)
        return {"fn": "caracole.lyrics.Lyrics.from_record", "case": case, "record": given,
                "out": {"plain": lyrics.plain, "synced": lyrics.synced, "instrumental": lyrics.instrumental,
                        "duration": fl(lyrics.duration), "lrclib_id": lyrics.lrclib_id, "to_json": lyrics.to_json()}}

    out = []
    for name in ("lrclib/get_hit.json", "lrclib/get_instrumental.json"):
        out.append(one(f"the fixture {name}", fixture_ref(name), load(name)))
    for i, rec in enumerate(load("lrclib/search_banma.json")):
        out.append(one(f"search_banma's record {i}", as_line(rec), as_line(rec)))
    synthetic = [
        ("plain made from the synced, its stamps repeated and its word stamps gone",
         {"id": 1, "duration": 200, "plainLyrics": None,
          "syncedLyrics": "[ar:X]\r\n[00:05.00][00:20.00]Chorus <00:05.50>line\r\n[00:10.5]Two  words\n[00:12.00]\n"
                          "[00:13.00]\n[00:14.00]After a break\n[00:30.00]"}),
        ("the plain lyrics' ID tags dropped, whatever their case", {
            "plainLyrics": "[AR: Someone]\n[ti:Title]\n[length: 03:20]\nLine one\n[Chorus]\nLine two\n\n", "syncedLyrics": ""}),
        ("a bool is no number, nor no id", {"id": True, "duration": False, "instrumental": 1, "plainLyrics": "x"}),
        ("an instrumental flag of true alone", {"instrumental": True, "plainLyrics": "  ", "syncedLyrics": None}),
        ("stamps in other digits", {"syncedLyrics": "[٠١:٠٥.٥٠]Eastern digits\n"
                                                    "[０２:００]Fullwidth ones"}),
        ("a long minute", {"syncedLyrics": "[123456789012345678901:00.25]Far on"}),
        ("a record of other types", {"plainLyrics": 3, "syncedLyrics": ["[00:01.00]a"], "duration": "213"}),
        ("an int duration and a float id", {"duration": 213, "id": 7.0, "plainLyrics": "A"}),
        ("nothing at all", {}),
    ]
    for case, rec in synthetic:
        out.append(one(case, as_line(rec), as_line(rec)))
    return out


FITS = [  # (case, artist, title, duration_s, got_artist, got_title, got_duration)
    ("the same song within 2 s", "Soda Stereo", "De Música Ligera", 213.0, "Soda Stereo", "De Música Ligera", 214.5),
    ("within 10 s", "Soda Stereo", "De Música Ligera", 213.0, "Soda Stereo", "De Música Ligera", 221.0),
    ("beyond 10 s, the same keys", "Soda Stereo", "De Música Ligera", 213.0, "Soda Stereo", "De Musica Ligera",
     243.0),
    ("beyond 10 s, close names", "Soda Stereo", "De Música Ligera", 213.0, "Soda Stereo", "De Música Ligeras", 243.0),
    ("close names within 10 s", "Soda Stereo", "De Música Ligera", 213.0, "Sonda Estéreo", "La Música Ligera", 221.0),
    ("another title", "Soda Stereo", "De Música Ligera", 213.0, "Soda Stereo", "De Musica Liviana", 213.0),
    ("another artist", "Soda Stereo", "De Música Ligera", 213.0, "Sada Sterea", "De Música Ligera", 213.0),
    ("no artist", "Soda Stereo", "De Música Ligera", 213.0, "", "De Música Ligera", 213.0),
    ("one artist inside the other", "Bob Marley & The Wailers", "Song", 100.0, "Bob Marley", "Song", 100.0),
    ("a duet inside", "Soda Stereo", "Song", 100.0, "Soda Stereo & Andrea Echeverri", "Song", 100.0),
    ("no duration known", "Soda Stereo", "De Música Ligera", None, "Soda Stereo", "De Música Ligera", 999.0),
    ("no duration given, the same keys", "Soda Stereo", "De Música Ligera", 213.0, "Soda Stereo",
     "De Música Ligera", None),
    ("no duration given, close names", "Soda Stereo", "De Música Ligera", 213.0, "Soda Stereo", "De Música Ligeras",
     None),
    ("punctuation-only names as written", "!!!", "?", 213.0, "!!!", "?", 213.0),
    ("punctuation-only names that differ", "!!!", "¡!", 213.0, "!!!", "?", 213.0),
    ("a cleaned title", "Radiohead", "Creep (Remastered 2009)", 238.0, "Radiohead", "Creep", 239.0),
    ("Han split by punctuation", "宋冬野", "斑马，斑马", 253.0, "宋冬野", "斑马斑马", 253.1004),
    ("a Traditional title", "宋冬野", "斑馬斑馬", 253.0, "宋冬野", "斑马斑马", 253.1004),
    ("exactly 2 s off", "A", "Song", 200.0, "A", "Song", 202.0),
    ("exactly 10 s off", "A", "Song", 200.0, "A", "Song", 190.0),
    ("a fraction past 10 s", "A", "Song", 200.0, "A", "Song", 210.000001),
    ("a nan duration", "A", "Song", 200.0, "A", "Song", float("nan")),
    ("an infinite duration", "A", "Song", 200.0, "A", "Song", float("inf")),
    ("case and accents", "BJÖRK", "JÓGA", 300.0, "björk", "Jóga", 300.0),
]

OTHER_VERSIONS = [
    ("Song", "Song (Cover)"), ("Song", "Song - Karaoke Version"), ("Song (Instrumental)", "Song (Instrumental)"),
    ("Song", "Song (A Cappella)"), ("Song", "song acapella"), ("Song", "Nightcore - Song"), ("Song", "Song (sped up)"),
    ("Song", "Song slowed + reverb"), ("Song", "Song 8D Audio"), ("Song", "Song (vocals only)"),
    ("Song", "Song (Vocal)"), ("Song", "Song (Remix)"), ("Song Remix", "Song (Remix)"), ("Song", "Song (Live)"),
    ("Song", "Discovery"), ("Song", "Recover"), ("Song", "Song (COVER)"), ("Song", "Sóng (Cóver)"),
    ("Undertale", "Undertale - Megalovania (Original lyricsVocal cover)"), ("Song", "Song (Remixes)"),
    ("Song (Cover)", "Song (Karaoke)"), ("", ""),
]

SEARCH_TITLES = ["斑马，斑马", "斑马斑马", "너의 의미", "Persiana Americana", "一 、 二", "東京_タワー", "中a中", "中 中 中",
                 "\U00020000-\U00020001", "中!", "中　中", "A, B"]


def pick_records() -> list[dict[str, Any]]:
    from caracole.lyrics import pick_candidate

    def one(case: str, cands: Any, given: Any, *, artist: str = "Soda Stereo", title: str = "De Música Ligera",
            duration_s: float | None = 213.0) -> dict[str, Any]:
        best = pick_candidate(cands, artist=artist, title=title, duration_s=duration_s)
        index = None if best is None else next(i for i, c in enumerate(cands) if c is best)
        return {"fn": "caracole.lyrics.pick_candidate", "case": case, "cands": given,
                "kw": {"artist": artist, "title": title, "duration_s": fl(duration_s)}, "out": index}

    def inline(case: str, cands: list[Any], **kw: Any) -> dict[str, Any]:
        lined = as_line(cands)
        return one(case, lined, lined, **kw)

    rec, track = lrclib_record, lambda t, **f: lrclib_record(name=t, trackName=t, **f)
    out = [
        one("search_banma, its length known", load("lrclib/search_banma.json"), fixture_ref("lrclib/search_banma.json"),
            artist="宋冬野", title="斑马斑马", duration_s=253.0),
        one("search_banma, its title split", load("lrclib/search_banma.json"), fixture_ref("lrclib/search_banma.json"),
            artist="宋冬野", title="斑马，斑马", duration_s=253.0),
        one("search_banma, no length", load("lrclib/search_banma.json"), fixture_ref("lrclib/search_banma.json"),
            artist="宋冬野", title="斑马斑马", duration_s=None),
        one("search_empty", load("lrclib/search_empty.json"), fixture_ref("lrclib/search_empty.json")),
        inline("close length first, then synced", [rec(id=1, duration=205.0), rec(id=2, duration=201.0, syncedLyrics=None),
                                                  rec(id=3, duration=201.8), rec(id=4, duration=200.2, syncedLyrics=None)],
               duration_s=200.0),
        inline("the closest plain within 2 s", [rec(id=1, duration=205.0), rec(id=2, duration=201.0, syncedLyrics=None),
                                                rec(id=4, duration=200.2, syncedLyrics=None)], duration_s=200.0),
        inline("within 10 s before beyond", [rec(id=5, duration=207.0), rec(id=1, duration=205.0)], duration_s=200.0),
        inline("a text match within 10 s",
               [track("La Música Ligera", id=1, duration=221.0, artistName="Sonda Estéreo")]),
        inline("beyond 10 s the same keys alone", [track("De Música Ligeras", id=1, duration=243.0),
                                                   rec(id=2, duration=243.0)]),
        inline("within 10 s over synced beyond", [rec(id=2, duration=243.0), rec(id=1, duration=218.0, syncedLyrics=None)]),
        inline("no length: synced first", [rec(id=1, duration=150.0, syncedLyrics=None), rec(id=2, duration=400.0)],
               duration_s=None),
        inline("no length: LRCLIB's order among equals", [rec(id=1, duration=150.0), rec(id=2, duration=400.0)],
               duration_s=None),
        inline("other titles and artists", [track("De Musica Liviana", id=1), rec(id=2, artistName="Sada Sterea"),
                                            rec(id=3, artistName=None)]),
        inline("one artist's key inside the other", [rec(id=1, artistName="Soda Stereo & Andrea Echeverri")]),
        inline("a band inside the song's artist", [rec(id=2, artistName="Bob Marley")], artist="Bob Marley & The Wailers"),
        inline("punctuation-only names", [track("?", artistName="!!!")], artist="!!!", title="?"),
        inline("punctuation-only names that differ", [track("?", artistName="!!!")], artist="!!!", title="¡!"),
        inline("records without lyrics skipped", [rec(id=1, duration=213.0, plainLyrics=None, syncedLyrics=None),
                                                  rec(id=2, duration=214.5)]),
        inline("an instrumental after plain and synced", [
            rec(id=1, instrumental=True, plainLyrics=None, syncedLyrics=None),
            rec(id=2, syncedLyrics=None), rec(id=3)]),
        inline("an instrumental alone", [rec(id=1, instrumental=True, plainLyrics=None, syncedLyrics=None)]),
        inline("not an object, skipped", [None, "x", 3, [1], rec(id=9)]),
        inline("its name when there's no trackName", [{**rec(id=1), "trackName": None, "name": "De Música Ligera"},
                                                      {**rec(id=2), "trackName": "", "name": "Otra"}]),
        inline("no duration on a record", [{**rec(id=1), "duration": None}, {**rec(id=2), "duration": "213"}]),
        inline("a nan length is beyond any band", [{**rec(id=1), "duration": None}], duration_s=float("nan")),
        inline("ties keep the first", [rec(id=1, duration=214.0), rec(id=2, duration=212.0)]),
        inline("synced stamps only, no plain", [rec(id=1, plainLyrics="", syncedLyrics="[00:01.00]a")]),
    ]
    banma = load("lrclib/search_banma.json")
    for wanted, listed in [("斑马，斑马", "斑马斑马"), ("斑马斑马", "斑马，斑马")]:
        inline_cands = [{**c, "name": listed, "trackName": listed} for c in banma]
        out.append(inline(f"Han titles {wanted} and {listed}", inline_cands, artist="宋冬野", title=wanted,
                          duration_s=253.0))
    return out


def read_records() -> list[dict[str, Any]]:
    from caracole.lyrics import _get_record, _json

    bodies = [
        ("a record", 200, fixture_ref("lrclib/get_hit.json")),
        ("its miss", 404, text('{"code": 404, "name": "TrackNotFound"}')),
        ("a 404 that isn't JSON", 404, text("<html>Not found</html>")),
        ("a list where a record is", 200, fixture_ref("lrclib/search_banma.json")),
        ("a maintenance notice", 200, text("<html><body>Down for maintenance</body></html>")),
        ("empty", 200, text("")),
        ("a number", 200, text("3")),
        ("NaN", 200, text("NaN")),
        ("a BOM", 200, raw_body(b"\xef\xbb\xbf[]")),
        ("a byte that isn't UTF-8", 200, raw_body(b'{"a": "\xff"}')),
        ("UTF-16 by its zeros", 200, raw_body('[{"id": 1}]'.encode("utf-16-le"))),
        ("extra data", 200, text("{} {}")),
        ("a duplicate key", 200, text('{"id": 1, "id": 2}')),
        ("an empty list", 200, fixture_ref("lrclib/search_empty.json")),
        ("a search", 200, fixture_ref("lrclib/search_banma.json")),
    ]
    out = []
    for endpoint, url, read in (("get", LRCLIB_GET, _get_record), ("search", LRCLIB_SEARCH, lambda r: _json(r, list))):
        for case, status, body in bodies:
            if endpoint == "search" and status == 404:
                continue
            r = {"fn": "caracole.lyrics.read", "case": f"{endpoint}: {case}", "read": endpoint, "url": url,
                 "status": status, "body": body}
            try:
                r["out"] = read(response(url, status, body))
            except Exception as e:  # noqa: BLE001 - recorded
                r["raises"] = raised(e)
            out.append(r)
    return out


class Replies:
    """A ``caracole.http.Client`` answering each endpoint (``get``, ``search``) with ``(status, body)``, as
    ``PoliteClient`` would: a status it wasn't given to accept is a ``ProviderError``. Records each call."""

    def __init__(self, get: tuple[int, dict[str, str]] | None, search: tuple[int, dict[str, str]] | None):
        self.replies = {LRCLIB_GET: get, LRCLIB_SEARCH: search}
        self.calls: list[dict[str, Any]] = []
        self.requests_made = 0

    def get(self, url, *, params=None, cache=True, conditional=False, accept=(200,), max_age=None):
        from caracole.http import ProviderError, Response
        from helpers.scenario import _body

        rendered = [[k, str(v)] for k, v in (params or {}).items()]
        self.calls.append({"url": url, "params": rendered, "accept": sorted(accept), "cache": cache})
        reply = self.replies.get(url)
        if reply is None:
            raise AssertionError(f"unanswered: {url}")
        status, body = reply
        if status not in accept:
            raise ProviderError("lrclib", url, status, "status not accepted")
        self.requests_made += 1
        return Response(url=url, status=status, content=_body(body)[0], headers={}, from_cache=False)


def fetch_records() -> list[dict[str, Any]]:
    from caracole.lyrics import fetch_lyrics

    hit = (200, fixture_ref("lrclib/get_hit.json"))
    miss = (404, text('{"code": 404}'))
    banma = (200, fixture_ref("lrclib/search_banma.json"))
    empty = (200, fixture_ref("lrclib/search_empty.json"))
    no_lyrics = (200, text(json.dumps(lrclib_record(plainLyrics=None, syncedLyrics=None))))
    cases = [
        ("a hit on /api/get, album and length sent", hit, None,
         dict(artist="Soda Stereo", title="De Música Ligera", album="Canción Animal", duration_s=213.0)),
        ("a cleaned title, no album and no length", hit, None,
         dict(artist="Soda Stereo", title="De Música Ligera (Remastered 2007)", album=None, duration_s=None)),
        ("an empty album isn't sent", hit, None, dict(artist="Soda Stereo", title="X", album="", duration_s=0.0)),
        ("a half second rounds to the even second", hit, None,
         dict(artist="A", title="B", album=None, duration_s=212.5)),
        ("another half rounds up to the even one", hit, None, dict(artist="A", title="B", album=None, duration_s=213.5)),
        ("just under a half", hit, None, dict(artist="A", title="B", album=None, duration_s=0.49999999999999994)),
        ("a miss, then the search with the Han joined", miss, banma,
         dict(artist="宋冬野", title="斑马，斑马", album="安和桥北", duration_s=253.0)),
        ("a record with no lyrics, then the search", no_lyrics, empty,
         dict(artist="Soda Stereo", title="De Música Ligera", album=None, duration_s=213.0)),
        ("a miss, then an empty search", miss, empty, dict(artist="A", title="B", album=None, duration_s=None)),
        ("past the cache", miss, empty, dict(artist="A", title="B", album=None, duration_s=None, cache=False)),
        ("an instrumental", (200, fixture_ref("lrclib/get_instrumental.json")), None,
         dict(artist="Conjunto de Prueba", title="Interludio de Prueba", album=None, duration_s=184.0)),
        ("a status not accepted", (500, text("oops")), None, dict(artist="A", title="B", album=None, duration_s=None)),
        ("a search that isn't JSON", miss, (200, text("<html>")),
         dict(artist="A", title="B", album=None, duration_s=None)),
    ]
    out = []
    for case, get, search, kw in cases:
        client = Replies(get, search)
        r = {"fn": "caracole.lyrics.fetch_lyrics", "case": case, "get": get and {"status": get[0], "body": get[1]},
             "search": search and {"status": search[0], "body": search[1]},
             "kw": {**kw, "duration_s": fl(kw["duration_s"])}}
        try:
            result = fetch_lyrics(client, **kw)
            r["out"] = {"status": result.status, "lyrics": result.lyrics.to_json() if result.lyrics else None}
        except Exception as e:  # noqa: BLE001 - recorded
            r["raises"] = raised(e)
        r["calls"] = client.calls
        out.append(r)
    return out


def lrclib_site_records() -> list[dict[str, Any]]:
    from caracole.lyrics import _search_title, another_version, fits

    out = from_record_records()
    for case, artist, title, duration_s, got_artist, got_title, got_duration in FITS:
        fit = fits(artist=artist, title=title, duration_s=duration_s, got_artist=got_artist, got_title=got_title,
                   got_duration=got_duration)
        out.append({"fn": "caracole.lyrics.fits", "case": case,
                    "kw": {"artist": artist, "title": title, "duration_s": fl(duration_s), "got_artist": got_artist,
                           "got_title": got_title, "got_duration": fl(got_duration)},
                    "out": None if fit is None else [fit[0], fl(fit[1])]})
    for want, got in OTHER_VERSIONS:
        out.append({"fn": "caracole.lyrics.another_version", "args": [want, got], "out": another_version(want, got)})
    for title in SEARCH_TITLES:
        out.append({"fn": "caracole.lyrics._search_title", "args": [title], "out": _search_title(title)})
    return out + pick_records() + read_records() + fetch_records()


# --- Megalobiz's ------------------------------------------------------------------------------------------------


def lrc_record(**fields: Any) -> dict[str, Any]:
    return {**load("megalobiz/lrc_24519.json"), **fields}


def result_dict(r) -> dict[str, Any]:
    return {"id": str(r.id), "title": r.title, "artist": r.artist, "duration": fl(r.duration), "url": r.url}


def megalobiz_site_records() -> list[dict[str, Any]]:
    from caracole import megalobiz as m

    out: list[dict[str, Any]] = []
    for artist, title, duration in [("Eagles", "Hotel California", 391.55), ("Eagles", "Hotel California (Live)", None),
                                    ("宋冬野", "斑马，斑马", 252.5), ("A", "B", 253.5), ("A", "B", 0.0)]:
        params = m.search_params(artist, title, duration)
        out.append({"fn": "caracole.megalobiz.search_params", "args": [artist, title, fl(duration)],
                    "out": [[k, str(v)] for k, v in params.items()]})
    for lrc_id in (24519, 0, 12345678901234567890):
        out.append({"fn": "caracole.megalobiz.lrc_url", "args": [str(lrc_id)], "out": m.lrc_url(lrc_id)})

    def search(case: str, body: dict[str, str], status: int = 200) -> None:
        r = {"fn": "caracole.megalobiz.parse_search", "case": case, "url": m.SEARCH, "status": status, "body": body}
        try:
            r["out"] = [result_dict(x) for x in m.parse_search(response(m.SEARCH, status, body))]
        except Exception as e:  # noqa: BLE001 - recorded
            r["raises"] = raised(e)
        out.append(r)

    for name in ("search_hotel_california", "search_megalovania", "search_vacaciones", "search_empty"):
        search(name, fixture_ref(f"megalobiz/{name}.json"))
    page = "https://megalobiz.com/lrc/1/x"
    for case, data in [
        ("results not a list", {"results": {}}),
        ("no results", {"count": 0}),
        ("a result not an object", {"results": [1]}),
        ("an id that isn't a number", {"results": [{"id": "1", "url": page}]}),
        ("an id that is a bool", {"results": [{"id": True, "url": page}]}),
        ("an id that is a float", {"results": [{"id": 1.0, "url": page}]}),
        ("no id", {"results": [{"url": page}]}),
        ("a page elsewhere", {"results": [{"id": 1, "url": "https://example.com/lrc/1"}]}),
        ("a page that isn't text", {"results": [{"id": 1, "url": None}]}),
        ("names of other types, a length as text", {"results": [{"id": 1, "url": page, "title": 3, "artist": None,
                                                                 "duration": "200"}]}),
        ("a length that is an int", {"results": [{"id": 99999999999999999999, "url": page, "title": "T",
                                                  "artist": "A", "duration": 200}]}),
        ("a length that is a bool", {"results": [{"id": 1, "url": page, "duration": True}]}),
        ("a list, not an object", [1, 2]),
        ("a nested id in its message", {"results": [{"id": {"a": [1, None, "x'y", 1.5e-7, True]}, "url": page}]}),
    ]:
        search(case, text(json.dumps(data, ensure_ascii=False)))
    search("not JSON", text("<html>"))
    search("a byte that isn't UTF-8", raw_body(b'{"results": ["\xff"]}'))

    def lrc(case: str, body: dict[str, str], url: str = m.lrc_url(24519)) -> None:
        r = {"fn": "caracole.megalobiz.parse_lrc", "case": case, "url": url, "status": 200, "body": body}
        try:
            got = m.parse_lrc(response(url, 200, body))
            r["out"] = {**result_dict(got), "lrc": got.lrc}
        except Exception as e:  # noqa: BLE001 - recorded
            r["raises"] = raised(e)
        out.append(r)

    lrc("the record", fixture_ref("megalobiz/lrc_24519.json"))
    lines = [{"time_ms": ms, "text": f"line {ms}"} for ms in (
        0, 1, 5, 10, 15, 25, 35, 45, 125, 1005, 1015, 1025, 1035, 1045, 1055, 1065, 1075, 1085, 1095, 2675, 9995,
        59994, 59995, 59996, 59999, 60000, 60005, 600000, 3599999, 5999995, 6000000, 123456789, -1, -60000, -61005,
        10 ** 25 + 1005)]
    lines += [{"time_ms": 3.5, "text": "a float"}, {"time_ms": True, "text": "a bool"}, {"text": "no time"}, 7,
              {"time_ms": 70000, "text": None}, {"time_ms": 71000}]
    lrc("made from its lines, rounded half to even", text(json.dumps(lrc_record(lrc=None, lines=lines))))
    lrc("lrc text with no stamp: its lines", text(json.dumps(lrc_record(lrc="[ar:X]\n[ti:Y]",
                                                                        lines=[{"time_ms": 1000, "text": "a"}]))))
    lrc("lrc text with Windows line ends", text(json.dumps(lrc_record(lrc="[ar:X]\r\n[00:01.00]a\r\n[00:02.00]b"))))
    lrc("a stamp after spaces on a later line", text(json.dumps(lrc_record(lrc="[ar:X]\n  [00:01.00]a", lines=[]))))
    lrc("a stamp of Eastern digits", text(json.dumps(lrc_record(lrc="[٠٠:٠١]a", lines=[]))))
    lrc("no timed line at all", text(json.dumps(lrc_record(lrc="[ar:X]", lines=[]))))
    lrc("lrc text alone, no lines", text(json.dumps(lrc_record(lrc="[00:01.00]a", lines=None))))
    lrc("lines alone, not text", text(json.dumps(lrc_record(lrc=3, lines=[{"time_ms": 1500, "text": "b"}]))))
    lrc("lines not a list, no text", text(json.dumps(lrc_record(lrc=None, lines={"a": 1}))))
    lrc("neither", text(json.dumps({"id": 1, "url": page})))
    lrc("a page elsewhere", text(json.dumps(lrc_record(url="http://megalobiz.com/lrc/24519"))))
    lrc("not JSON", text("Bad Gateway"))
    lrc("a list", text("[]"))

    def pick(case: str, results: list[dict[str, Any]], artist: str, title: str, duration_s: float | None) -> None:
        made = [m.Result(int(r["id"]), r["title"], r["artist"], r["duration"], r["url"]) for r in results]
        best = m.pick_result(made, artist=artist, title=title, duration_s=duration_s)
        out.append({"fn": "caracole.megalobiz.pick_result", "case": case,
                    "results": [{**r, "id": str(r["id"]), "duration": fl(r["duration"])} for r in results],
                    "kw": {"artist": artist, "title": title, "duration_s": fl(duration_s)},
                    "out": None if best is None else made.index(best)})

    def result(lrc_id: int, title: str, artist: str, duration: float | None) -> dict[str, Any]:
        return {"id": lrc_id, "title": title, "artist": artist, "duration": duration,
                "url": f"https://megalobiz.com/lrc/{lrc_id}/x"}

    for name, artist, title, duration in [("search_hotel_california", "Eagles", "Hotel California", 390.0),
                                          ("search_hotel_california", "Eagles", "Hotel California", None),
                                          ("search_hotel_california", "Eagles", "Hotel California", 420.0),
                                          ("search_megalovania", "Toby Fox", "Megalovania", 214.0),
                                          ("search_vacaciones", "Estopa", "Vacaciones", 223.0)]:
        results = [{"id": r["id"], "title": r["title"], "artist": r["artist"], "duration": r["duration"],
                    "url": r["url"]} for r in load(f"megalobiz/{name}.json")["results"]]
        pick(f"{name}, {duration}", results, artist, title, duration)
    pick("the closest length", [result(1, "Song", "A", 205.0), result(2, "Song", "A", 201.0),
                                result(3, "Song", "A", 199.5)], "A", "Song", 200.0)
    pick("no length: the first that fits", [result(1, "Other", "A", 200.0), result(2, "Song", "A", 300.0),
                                            result(3, "Song", "A", 200.0)], "A", "Song", None)
    pick("beyond 10 s the same names alone", [result(1, "Songs", "A", 260.0), result(2, "Song", "A", 260.0)],
         "A", "Song", 200.0)
    pick("credited to no one", [result(1, "Song", " ", 200.0), result(2, "Song", "", 200.0)], "A", "Song", 200.0)
    pick("a cover or a remix", [result(1, "Song (Cover)", "A", 200.0), result(2, "Song - Remix", "A", 200.0),
                                result(3, "Song", "A", 230.0)], "A", "Song", 200.0)
    pick("a version the song names", [result(1, "Song (Remix)", "A", 200.0)], "A", "Song (Remix)", 200.0)
    pick("no length on a result", [result(1, "Song", "A", None)], "A", "Song", 200.0)
    pick("nothing", [], "A", "Song", 200.0)
    return out


# --- AZLyrics' --------------------------------------------------------------------------------------------------


AZ_ROW = '<div class="listalbum-item"><a href="{href}" target="_blank">{title}</a></div>'


def az_artist_page(name: str, rows: list[tuple[str, str]]) -> str:
    listed = "\n".join(AZ_ROW.format(href=h, title=t) for h, t in rows)
    return (f'<html><body><h1><strong>{name} Lyrics</strong></h1>\n<div id="listAlbum">\n{listed}\n</div>'
            "</body></html>")


def az_lyrics_page(inner: str) -> str:
    return ("<html><body><div>\n<!-- Usage of azlyrics.com content by any third-party lyrics provider is prohibited "
            f"by our licensing agreement. Sorry about that. -->{inner}</div><br></body></html>")


def azlyrics_site_records() -> list[dict[str, Any]]:
    from caracole import azlyrics as a

    out: list[dict[str, Any]] = []
    for name in ["Pomme", "The Beatles", "the  Strokes", "Theatre of Tragedy", "AC/DC", "Björk", "Sigur Rós",
                 "50 Cent", "2Pac", "宋冬野", "!!!", "", "The", "The The", "Mötley Crüe", "Ⅻ", "ﬁve", "Ǆemal",
                 "İstanbul", "The\tKillers", "Беатлз", "Sean Paul", "The 1975", "a-ha", "Ø"]:
        out.append({"fn": "caracole.azlyrics.artist_url", "args": [name], "out": a.artist_url(name)})

    def artist(case: str, body: dict[str, str], url: str = "https://www.azlyrics.com/p/pomme.html") -> None:
        r = {"fn": "caracole.azlyrics.parse_artist", "case": case, "url": url, "status": 200, "body": body}
        try:
            page = a.parse_artist(response(url, 200, body))
            r["out"] = {"name": page.name, "songs": [[s.title, s.url] for s in page.songs]}
        except Exception as e:  # noqa: BLE001 - recorded
            r["raises"] = raised(e)
        out.append(r)

    artist("Pomme's page", fixture_ref("azlyrics/artist_pomme.html"))
    artist("the site's 404 page", fixture_ref("azlyrics/not_found.html"))
    artist("the block page", fixture_ref("azlyrics/block.html"))
    artist("entities and tags in the names", text(az_artist_page(
        "Simon &amp; Garfunkel", [("/lyrics/simongarfunkel/thesoundofsilence.html", "The Sound Of <b>Silence</b>"),
                                  ("/lyrics/simongarfunkel/mrsrobinson.html", "Mrs. Robinson&#x27;s &eacute;t&eacute; "),
                                  ("/lyrics/Upper/case.html", "Upper case path, no song"),
                                  ("/lyrics/a/b.htm", "Not .html"),
                                  ("https://www.azlyrics.com/lyrics/x-y/z-1.html", "Absolute, with hyphens"),
                                  ("http://www.azlyrics.com/lyrics/x/z.html", "Plain http, no song")])))
    artist("a heading across lines", text(az_artist_page("Big\n  Thief", [("/lyrics/bigthief/x.html", "X")])))
    artist("no list of songs", text("<h1><strong>Pomme Lyrics</strong></h1>"))
    artist("no heading", text('<div id="listAlbum"></div>'))
    artist("an empty list", text(az_artist_page("Nobody", [])))
    artist("a byte that isn't UTF-8", raw_body(az_artist_page("Caf\xe9", []).encode("latin-1")))
    artist("a row whose link spans lines", text(az_artist_page("A", [("/lyrics/a/b.html", "Two\nLines")])))
    artist("an attribute before the target", text(
        '<h1><strong>A Lyrics</strong></h1><div id="listAlbum"><div class="listalbum-item"><a href="/lyrics/a/b.html"'
        ' data-x="1">Kept</a></div><div class="listalbum-item"><a class="x" href="/lyrics/a/c.html">Not kept</a>'
        "</div></div>"))

    def lyrics(case: str, body: dict[str, str], url: str = "https://www.azlyrics.com/lyrics/pomme/mononoke.html") -> None:
        r = {"fn": "caracole.azlyrics.parse_lyrics", "case": case, "url": url, "status": 200, "body": body}
        try:
            r["out"] = a.parse_lyrics(response(url, 200, body))
        except Exception as e:  # noqa: BLE001 - recorded
            r["raises"] = raised(e)
        out.append(r)

    lyrics("mononoke", fixture_ref("azlyrics/lyrics_mononoke.html"))
    lyrics("the 404 page", fixture_ref("azlyrics/not_found.html"))
    lyrics("the block page", fixture_ref("azlyrics/block.html"))
    lyrics("Windows line ends", text(az_lyrics_page("\r\nOne<br>\r\nTwo<br/>\r\n<br />\r\nThree\r\n")))
    lyrics("entities and tags", text(az_lyrics_page("<i>[Chorus:]</i><br>\nRock &amp; roll &lt;3 &nbsp;x&#8217;s<br>"
                                                    "\n<b>bold</b> &notit; &amp<br>")))
    lyrics("no text", text(az_lyrics_page("\n<br>\n<br>\n")))
    lyrics("spaces of every kind", text(az_lyrics_page("　Wide　<br> nbsp <br> sep ")))
    lyrics("a BR of capitals", text(az_lyrics_page("a<BR>b<br\t/>c")))
    lyrics("the notice without its div's end", text("<!-- Usage of azlyrics.com content, x --> words"))
    return out + az_pick_records()


def az_pick_records() -> list[dict[str, Any]]:
    from caracole import azlyrics as a

    out = []

    def pick(case: str, name: str, titles: list[str], artist: str, title: str) -> None:
        page = a.ArtistPage(name, tuple(a.SongLink(t, f"https://www.azlyrics.com/lyrics/x/{i}.html")
                                        for i, t in enumerate(titles)))
        best = a.pick_song(page, artist=artist, title=title)
        out.append({"fn": "caracole.azlyrics.pick_song", "case": case,
                    "page": {"name": page.name, "songs": [[s.title, s.url] for s in page.songs]},
                    "kw": {"artist": artist, "title": title},
                    "out": None if best is None else list(page.songs).index(best)})

    pomme = a.parse_artist(response("https://www.azlyrics.com/p/pomme.html", 200,
                                    fixture_ref("azlyrics/artist_pomme.html")))
    titles = [s.title for s in pomme.songs]
    pick("its line on Pomme's page", "Pomme", titles, "Pomme", "Mononoke")
    pick("a title spelled a little differently", "Pomme", titles, "Pomme", "Je t'emmenerai bien")
    pick("no line of the title", "Pomme", titles, "Pomme", "Grandiose")
    pick("another artist's page", "Pomme", titles, "Stromae", "Mononoke")
    pick("a remix only when it says so", "Pomme", titles, "Pomme", "Ma Meilleure Ennemie")
    pick("the remix asked for", "Pomme", titles, "Pomme", "Ma Meilleure Ennemie (Coldplay Remix)")
    pick("its own line before its live one", "A", ["Song (Live)", "Song", "Song (Acoustic)"], "A", "Song")
    pick("the first of equals", "A", ["Song (Live)", "Song (Acoustic)"], "A", "Song")
    pick("a cleaned title", "Radiohead", ["Creep", "Creep (Acoustic)"], "Radiohead", "Creep (Remastered)")
    pick("an empty page", "A", [], "A", "Song")
    pick("names in Han", "宋冬野", ["斑马斑马", "董小姐"], "宋冬野", "斑马，斑马")
    return out


# --- the passes' worlds -----------------------------------------------------------------------------------------


@contextmanager
def clock() -> Iterator[None]:
    """songs.py's clock at the record's ``now``, and no info.json (the viewer's, milestone 5's)."""
    with mock.patch("caracole.songs.utc_now_iso", lambda: STAMP), \
            mock.patch("caracole.megalobiz_fetch.write_info", lambda *a, **k: None), \
            mock.patch("caracole.azlyrics_fetch.write_info", lambda *a, **k: None):
        yield


def stats_of(s, *extra: str) -> dict[str, Any]:
    """A pass's stats as a record holds them."""
    return {"tried": s.tried, "errors": s.errors, "budget_exhausted": s.budget_exhausted,
            "failures": [[song.id, type(e).__name__, str(e)] for song, e in s.failures],
            **{name: getattr(s, name) for name in extra}}


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


class World:
    """A library of songs, its database and its overrides.toml."""

    def __init__(self, tmp: Path, name: str):
        from caracole import db

        self.dir = tmp / name
        self.dir.mkdir(parents=True)
        self.conn = db.connect(self.dir / "caracole.sqlite")
        phone_schema(self.conn)
        self.library = self.dir / "library"
        self.library.mkdir()
        self.overrides_file = self.dir / "overrides.toml"
        self.records = 0

    def song(self, artist: str, title: str, *, album: str | None = None, duration_ms: int | None = None,
             added: str = ADDED, **fields: Any) -> int:
        from caracole.normalize import identity_key
        from caracole.songs import update_song, upsert_song

        with clock():
            song_id, _ = upsert_song(self.conn, artists=[artist], title=title, album=album, duration_ms=duration_ms,
                                     isrc=None, source="wanted", source_id=identity_key(artist, title),
                                     added_at=added)
            if fields:
                update_song(self.conn, song_id, **fields)
        return song_id

    def get(self, song_id: int):
        from caracole.songs import get_song

        return get_song(self.conn, song_id)

    def file(self, song_id: int, name: str, data: str) -> None:
        from caracole.library import song_dir, write_atomic

        write_atomic(song_dir(self.library, self.get(song_id)) / name, data.encode("utf-8"))

    def kv(self, key: str, value: str) -> None:
        from caracole.db import kv_set

        kv_set(self.conn, key, value)

    def write_overrides(self, toml: str, display: str) -> None:
        from caracole.overrides import load_overrides

        self.overrides_file.write_text(toml, encoding="utf-8")
        self.conn.execute("DELETE FROM phone_overrides")
        for row in rows_of(load_overrides(self.overrides_file), display):
            self.conn.execute("INSERT INTO phone_overrides (tbl, key, written, value) VALUES (?, ?, ?, ?)",
                              (row["tbl"], row["key"], row["written"], row["value"]))

    def overrides(self):
        from caracole.overrides import Overrides, load_overrides

        return load_overrides(self.overrides_file) if self.overrides_file.exists() else Overrides()

    def record(self, provider: str, fn: str, case: str, call, kw: dict[str, Any],
               answers: dict[str, dict[str, Any]], cache: dict[str, Any] | None = None,
               budget: int = 6) -> dict[str, Any]:
        self.records += 1
        with clock():
            made = record(self.conn, self.library, fn=fn, case=case, call=call, kw=kw, now=NOW,
                          clients={provider: {"budget": budget, "delay": [0.0, 0.0]}}, answers=answers,
                          cache={provider: cache} if cache else None, cache_dir=self.dir / f"cache-{self.records}")
        done = made.get("out") or made["after"]
        made["answers"] = {r: a for r, a in made["answers"].items() if r in done["requests"]}  # what was asked alone
        return made

    def close(self) -> None:
        self.conn.close()


def ok(body: dict[str, str], headers: list[list[str]] = JSON) -> dict[str, Any]:
    return {"status": 200, "headers": headers, "body": body}


def status(code: int, body: str = "", headers: list[list[str]] | None = None) -> dict[str, Any]:
    return {"status": code, "headers": headers or [], "body": text(body)}


def held(answer: dict[str, Any], at: str = FETCHED) -> dict[str, Any]:
    """An answer as the HTTP cache holds it."""
    return {"status": answer["status"], "fetched_at": at, "body": answer["body"]}


def url_of(base: str, params: dict[str, Any]) -> str:
    return str(httpx.URL(base, params=params))


# --- LRCLIB's pass ------------------------------------------------------------------------------------------------


def lrclib_get(artist: str, title: str, album: str | None = None, duration: int | None = None) -> str:
    from caracole.normalize import clean_title

    params: dict[str, Any] = {"artist_name": artist, "track_name": clean_title(title)}
    if album:
        params["album_name"] = album
    if duration is not None:
        params["duration"] = duration
    return "GET " + url_of(LRCLIB_GET, params)


def lrclib_search(artist: str, title: str) -> str:
    from caracole.lyrics import _search_title
    from caracole.normalize import clean_title

    return "GET " + url_of(LRCLIB_SEARCH, {"track_name": _search_title(clean_title(title)), "artist_name": artist})


MISS = status(404, '{"code":404,"name":"TrackNotFound","message":"Failed to find specified track"}', JSON)
EMPTY = ok(fixture_ref("lrclib/search_empty.json"))


def lrclib_scenarios(tmp: Path) -> list[dict[str, Any]]:
    from caracole.lyrics import FAILED, fetch_pending_lyrics

    out = []

    def case(name: str, make, answers, *, cache=None, budget: int = 6, durations=None) -> None:
        w = World(tmp, f"lrclib-{len(out)}")
        try:
            song_id = make(w)
            kw: dict[str, Any] = {"only": [song_id]}
            if durations is not None:
                kw["durations"] = {str(song_id): durations}

            def call(clients):
                given = {song_id: durations} if durations is not None else None
                s = fetch_pending_lyrics(w.conn, clients["lrclib"], w.library, NOW, only={song_id}, durations=given)
                return stats_of(s, "found", "missing", "instrumental")

            out.append(w.record("lrclib", "caracole.lyrics.fetch_pending_lyrics", name, call, kw,
                                answers(w, song_id), cache(w, song_id) if cache else None, budget))
        finally:
            w.close()

    soda = ("Soda Stereo", "De Música Ligera")

    def soda_song(w: World, **fields: Any) -> int:
        return w.song(*soda, album="Canción Animal", duration_ms=213000, **fields)

    case("a hit on /api/get: lyrics.txt, lyrics.lrc and lyrics_json, the failed record gone",
         lambda w: (sid := soda_song(w), w.kv(f"{FAILED}{sid}", LATELY))[0],
         lambda w, sid: {lrclib_get(*soda, "Canción Animal", 213): ok(fixture_ref("lrclib/get_hit.json"))})
    case("a miss, then the search with the Han joined: plain lyrics alone, a stale lyrics.lrc gone",
         lambda w: (sid := w.song("宋冬野", "斑马，斑马", album="安和桥北", duration_ms=253000),
                    w.file(sid, "lyrics.lrc", "[00:01.00]old\n"))[0],
         lambda w, sid: {lrclib_get("宋冬野", "斑马，斑马", "安和桥北", 253): MISS,
                         lrclib_search("宋冬野", "斑马，斑马"): ok(fixture_ref("lrclib/search_banma.json"))})
    case("an instrumental: stored, no lyric file",
         lambda w: w.song("Conjunto de Prueba", "Interludio de Prueba", duration_ms=184000),
         lambda w, sid: {lrclib_get("Conjunto de Prueba", "Interludio de Prueba", None, 184):
                         ok(fixture_ref("lrclib/get_instrumental.json"))})
    case("a miss: missing with its time, nothing written",
         lambda w: w.song("Nadie", "Canción Inventada"),
         lambda w, sid: {lrclib_get("Nadie", "Canción Inventada"): MISS,
                         lrclib_search("Nadie", "Canción Inventada"): EMPTY})
    case("a miss asked again after 30 days, past the cache",
         lambda w: w.song("Nadie", "Canción Inventada", lyrics_status="missing", lyrics_at=LONG_AGO),
         lambda w, sid: {lrclib_get("Nadie", "Canción Inventada"): ok(fixture_ref("lrclib/get_hit.json"))},
         cache=lambda w, sid: {lrclib_get("Nadie", "Canción Inventada"): held(MISS)})
    case("a miss within 30 days: nothing asked",
         lambda w: w.song("Nadie", "Canción Inventada", lyrics_status="missing", lyrics_at=LATELY),
         lambda w, sid: {})
    case("a miss of no time is asked again",
         lambda w: w.song("Nadie", "Canción Inventada", lyrics_status="missing"),
         lambda w, sid: {lrclib_get("Nadie", "Canción Inventada"): MISS,
                         lrclib_search("Nadie", "Canción Inventada"): EMPTY})
    case("lyrics there already: nothing asked",
         lambda w: soda_song(w, lyrics_status="found", lyrics_json='{"plain": "x", "raw": {}}'),
         lambda w, sid: {})
    case("an ignored song: nothing asked",
         lambda w: (sid := soda_song(w), w.conn.execute("UPDATE songs SET status = 'ignored' WHERE id = ?", (sid,)))[0],
         lambda w, sid: {})
    case("a cached answer that isn't JSON, asked for once more",
         lambda w: soda_song(w),
         lambda w, sid: {lrclib_get(*soda, "Canción Animal", 213): ok(fixture_ref("lrclib/get_hit.json"))},
         cache=lambda w, sid: {lrclib_get(*soda, "Canción Animal", 213):
                               held(ok(text("<html>Down for maintenance</html>"), HTML))})
    case("a cached answer still not JSON when asked again: an error, the song pending and remembered as failed",
         lambda w: soda_song(w),
         lambda w, sid: {lrclib_get(*soda, "Canción Animal", 213): ok(text("<html>still down</html>"), HTML)},
         cache=lambda w, sid: {lrclib_get(*soda, "Canción Animal", 213): held(ok(text("<html>down</html>"), HTML))})
    case("a cached search that isn't JSON, asked for once more",
         lambda w: w.song("Nadie", "Canción Inventada"),
         lambda w, sid: {lrclib_search("Nadie", "Canción Inventada"): EMPTY},
         cache=lambda w, sid: {lrclib_get("Nadie", "Canción Inventada"): held(MISS),
                               lrclib_search("Nadie", "Canción Inventada"): held(ok(text("oops"), HTML))})
    case("LRCLIB's 503, asked once more after its Retry-After, then an error: never a miss",
         lambda w: soda_song(w),
         lambda w, sid: {lrclib_get(*soda, "Canción Animal", 213):
                         status(503, '{"name":"ServerOverloaded"}', [["retry-after", "5"], *JSON])})
    case("a 503 with no Retry-After: an error with no retry",
         lambda w: soda_song(w),
         lambda w, sid: {lrclib_get(*soda, "Canción Animal", 213): status(503, "busy")})
    case("an error on the search fallback: never a miss",
         lambda w: w.song("Nadie", "Canción Inventada", lyrics_status="missing", lyrics_at=LONG_AGO),
         lambda w, sid: {lrclib_get("Nadie", "Canción Inventada"): MISS,
                         lrclib_search("Nadie", "Canción Inventada"): status(500, "Internal Server Error")})
    case("a 429: a block, nothing marked",
         lambda w: soda_song(w),
         lambda w, sid: {lrclib_get(*soda, "Canción Animal", 213): status(429, "slow down", [["retry-after", "60"]])})
    case("a budget spent before the search: nothing marked",
         lambda w: w.song("Nadie", "Canción Inventada"),
         lambda w, sid: {lrclib_get("Nadie", "Canción Inventada"): MISS}, budget=1)
    case("a half second rounds to the even second, a folder's unsafe names",
         lambda w: w.song("AC/DC", "T.N.T.: Live?", duration_ms=212500),
         lambda w, sid: {lrclib_get("AC/DC", "T.N.T.: Live?", None, 212): ok(fixture_ref("lrclib/get_hit.json"))})
    case("a length given for a song with none of its own",
         lambda w: w.song("Nadie", "Canción Inventada"),
         lambda w, sid: {lrclib_get("Nadie", "Canción Inventada", None, 98): MISS,
                         lrclib_search("Nadie", "Canción Inventada"): EMPTY}, durations=97.5)
    case("a length of zero is none",
         lambda w: w.song("Nadie", "Canción Inventada", duration_ms=0),
         lambda w, sid: {lrclib_get("Nadie", "Canción Inventada"): MISS,
                         lrclib_search("Nadie", "Canción Inventada"): EMPTY})
    return out


# --- Megalobiz's pass ---------------------------------------------------------------------------------------------


def megalobiz_search(artist: str, title: str, duration: float | None) -> str:
    from caracole.megalobiz import SEARCH, search_params

    return "GET " + url_of(SEARCH, search_params(artist, title, duration))


def megalobiz_lrc(lrc_id: int) -> str:
    from caracole.megalobiz import lrc_url

    return f"GET {lrc_url(lrc_id)}"


def plain_lrclib(duration: float | None = 391.0) -> str:
    from caracole.lyrics import Lyrics

    return Lyrics(plain="Línea uno\nLínea dos", synced=None, instrumental=False, duration=duration,
                  lrclib_id=55).to_json()


def megalobiz_scenarios(tmp: Path) -> list[dict[str, Any]]:
    from caracole.lyrics import FAILED
    from caracole.megalobiz_fetch import CHECKED, megalobiz_lyrics

    out = []

    def case(name: str, make, answers, *, cache=None, budget: int = 6) -> None:
        w = World(tmp, f"megalobiz-{len(out)}")
        try:
            song_id = make(w)

            def call(clients):
                s = megalobiz_lyrics(w.conn, clients["megalobiz"], w.library, NOW, only={song_id})
                return stats_of(s, "found", "timed", "missing")

            out.append(w.record("megalobiz", "caracole.megalobiz_fetch.megalobiz_lyrics", name, call,
                                {"only": [song_id]}, answers(w, song_id), cache(w, song_id) if cache else None,
                                budget))
        finally:
            w.close()

    eagles = ("Eagles", "Hotel California")
    search = megalobiz_search(*eagles, 391.0)
    hit = {search: ok(fixture_ref("megalobiz/search_hotel_california.json")),
           megalobiz_lrc(24519): ok(fixture_ref("megalobiz/lrc_24519.json"))}

    def missed(w: World, **fields: Any) -> int:
        return w.song(*eagles, duration_ms=391000, lyrics_status="missing", lyrics_at=LATELY, **fields)

    case("a song LRCLIB missed: Megalobiz's timed lyrics, their page kept, the records gone",
         lambda w: (sid := missed(w), w.kv(f"{CHECKED}{sid}", LONG_AGO), w.kv(f"{FAILED}{sid}", LONG_AGO))[0],
         lambda w, sid: hit)
    case("plain lyrics from LRCLIB made timed, asked with their length",
         lambda w: w.song(*eagles, lyrics_status="found", lyrics_json=plain_lrclib(391.0), lyrics_at=LATELY),
         lambda w, sid: hit)
    case("a song pending LRCLIB failed on",
         lambda w: (sid := w.song(*eagles, duration_ms=391000), w.kv(f"{FAILED}{sid}", LATELY))[0],
         lambda w, sid: hit)
    case("a song pending LRCLIB wasn't asked about: nothing",
         lambda w: w.song(*eagles, duration_ms=391000), lambda w, sid: {})
    case("timed lyrics already: nothing",
         lambda w: w.song(*eagles, lyrics_status="found", lyrics_at=LATELY,
                          lyrics_json=json.dumps(load("lrclib/get_hit.json"))), lambda w, sid: {})
    case("Megalobiz's own plain lyrics: nothing",
         lambda w: w.song(*eagles, lyrics_status="found", lyrics_at=LATELY, lyrics_json=json.dumps(
             {"plain": "x", "synced": None, "raw": {}, "provider": "megalobiz"})), lambda w, sid: {})
    case("an instrumental: nothing",
         lambda w: w.song(*eagles, lyrics_status="instrumental", lyrics_at=LATELY), lambda w, sid: {})
    case("no result that fits: a miss, its time, the song still missing",
         lambda w: w.song("Toby Fox", "Megalovania", duration_ms=214000, lyrics_status="missing", lyrics_at=LATELY),
         lambda w, sid: {megalobiz_search("Toby Fox", "Megalovania", 214.0):
                         ok(fixture_ref("megalobiz/search_megalovania.json"))})
    case("an empty search: a miss",
         lambda w: w.song("宋冬野", "斑马斑马", lyrics_status="missing", lyrics_at=LATELY),
         lambda w, sid: {megalobiz_search("宋冬野", "斑马斑马", None): ok(fixture_ref("megalobiz/search_empty.json"))})
    case("a record gone: a miss",
         lambda w: missed(w),
         lambda w, sid: {search: hit[search],
                         megalobiz_lrc(24519): status(404, '{"error": "not_found"}', JSON)})
    case("a record with no timed line: a miss, plain lyrics kept",
         lambda w: w.song(*eagles, lyrics_status="found", lyrics_json=plain_lrclib(391.0), lyrics_at=LATELY),
         lambda w, sid: {search: hit[search], megalobiz_lrc(24519): ok(text(json.dumps(
             lrc_record(lrc="[ar:Eagles]", lines=[]))))})
    case("a miss within 30 days: nothing asked",
         lambda w: (sid := missed(w), w.kv(f"{CHECKED}{sid}", LATELY))[0], lambda w, sid: {})
    case("a miss after 30 days, asked again past the cache",
         lambda w: (sid := missed(w), w.kv(f"{CHECKED}{sid}", LONG_AGO))[0], lambda w, sid: hit,
         cache=lambda w, sid: {search: held(ok(fixture_ref("megalobiz/search_empty.json")))})
    case("an error on a song LRCLIB missed: back to pending",
         lambda w: missed(w), lambda w, sid: {search: status(502, "Bad Gateway")})
    case("an error on a song with plain lyrics: left as it was",
         lambda w: w.song(*eagles, lyrics_status="found", lyrics_json=plain_lrclib(391.0), lyrics_at=LATELY),
         lambda w, sid: {search: status(502, "Bad Gateway")})
    case("a cached search that isn't JSON, asked for once more",
         lambda w: missed(w), lambda w, sid: hit,
         cache=lambda w, sid: {search: held(ok(text("<html>maintenance</html>"), HTML))})
    case("a search not as documented: an error, back to pending",
         lambda w: missed(w), lambda w, sid: {search: ok(text('{"results": [{"id": "x"}]}'))})
    case("a 429: a block, nothing marked",
         lambda w: missed(w),
         lambda w, sid: {search: {"status": 429, "headers": [["retry-after", "30"], *JSON],
                                  "body": fixture_ref("megalobiz/rate_limited.json")}})
    case("a budget spent before the record: nothing marked",
         lambda w: missed(w), lambda w, sid: {search: hit[search]}, budget=1)
    case("a song with no length of its own and no lyrics' length",
         lambda w: w.song(*eagles, lyrics_status="found", lyrics_json=plain_lrclib(None), lyrics_at=LATELY),
         lambda w, sid: {megalobiz_search(*eagles, None): hit[search], megalobiz_lrc(24519): hit[megalobiz_lrc(24519)]})
    return out


# --- AZLyrics' pass -----------------------------------------------------------------------------------------------


AZ = "https://www.azlyrics.com"
POMME = f"GET {AZ}/p/pomme.html"
MONONOKE = f"GET {AZ}/lyrics/pomme/mononoke.html"
AZ_HIT = {POMME: ok(fixture_ref("azlyrics/artist_pomme.html"), HTML),
          MONONOKE: ok(fixture_ref("azlyrics/lyrics_mononoke.html"), HTML)}
AZ_404 = {"status": 404, "headers": HTML, "body": fixture_ref("azlyrics/not_found.html")}
AZ_BLOCK = {"status": 200, "headers": HTML, "body": fixture_ref("azlyrics/block.html")}


def azlyrics_scenarios(tmp: Path) -> list[dict[str, Any]]:
    from caracole.azlyrics_fetch import CHECKED, azlyrics_lyrics
    from caracole.http import ProviderBlocked
    from caracole.lyrics import FAILED

    out = []

    def case(name: str, make, answers, *, cache=None, budget: int = 6, picks: str | None = None,
             asked: str | None = None) -> None:
        w = World(tmp, f"azlyrics-{len(out)}")
        try:
            song_id = make(w)
            display = w.get(song_id).display
            if picks is not None:
                w.write_overrides(f'[azlyrics]\n"{display}" = "{picks}"\n', display)

            def call(clients):
                client = clients["azlyrics"]
                try:
                    s = azlyrics_lyrics(w.conn, client, w.library, NOW, picks=w.overrides().azlyrics,
                                        only={song_id})
                except ProviderBlocked as e:
                    if asked is None:
                        raise
                    return {"blocked": raised(e), "cached": client.has_cached(asked)}
                return stats_of(s, "found", "missing")

            out.append(w.record("azlyrics", "caracole.azlyrics_fetch.azlyrics_lyrics", name, call,
                                {"only": [song_id], **({"cached": asked} if asked else {})}, answers(w, song_id),
                                cache(w, song_id) if cache else None, budget))
        finally:
            w.close()

    def missed(w: World, artist: str = "Pomme", title: str = "mononoke", **fields: Any) -> int:
        return w.song(artist, title, **{"lyrics_status": "missing", "lyrics_at": LATELY, **fields})

    case("a song the sites before it missed: two requests, its lyrics and their page",
         lambda w: (sid := missed(w), w.kv(f"{FAILED}{sid}", LATELY), w.kv(f"{CHECKED}{sid}", LONG_AGO),
                    w.file(sid, "lyrics.lrc", "[00:01.00]old\n"))[0],
         lambda w, sid: AZ_HIT)
    case("a song pending LRCLIB failed on",
         lambda w: (sid := w.song("Pomme", "Mononoke"), w.kv(f"{FAILED}{sid}", LATELY))[0],
         lambda w, sid: AZ_HIT)
    case("a song pending LRCLIB wasn't asked about: nothing", lambda w: w.song("Pomme", "mononoke"),
         lambda w, sid: {})
    case("plain lyrics there already: nothing",
         lambda w: w.song("Pomme", "mononoke", lyrics_status="found", lyrics_json=plain_lrclib()),
         lambda w, sid: {})
    case("an instrumental: nothing", lambda w: missed(w, lyrics_status="instrumental"), lambda w, sid: {})
    case("no such artist: a miss of one request",
         lambda w: missed(w, "Nadie Conocido", "Canción"),
         lambda w, sid: {f"GET {AZ}/n/nadieconocido.html": AZ_404})
    case("a name with no address: a miss of no request", lambda w: missed(w, "宋冬野", "斑马斑马"),
         lambda w, sid: {})
    case("not on its artist's page: a miss",
         lambda w: missed(w, "Pomme", "Grandiose"), lambda w, sid: {POMME: AZ_HIT[POMME]})
    case("its lyrics page gone: a miss",
         lambda w: missed(w), lambda w, sid: {POMME: AZ_HIT[POMME], MONONOKE: AZ_404})
    case("a miss within 30 days: nothing asked",
         lambda w: (sid := missed(w), w.kv(f"{CHECKED}{sid}", LATELY))[0], lambda w, sid: {})
    case("a miss after 30 days, asked again past the cache",
         lambda w: (sid := missed(w), w.kv(f"{CHECKED}{sid}", LONG_AGO))[0], lambda w, sid: AZ_HIT,
         cache=lambda w, sid: {POMME: held(AZ_404)})
    case("a page you named: one request, whoever it credits, after a miss",
         lambda w: (sid := missed(w, "Someone Else", "Mononoke"), w.kv(f"{CHECKED}{sid}", LATELY))[0],
         lambda w, sid: {MONONOKE: AZ_HIT[MONONOKE]}, picks="azlyrics.com/lyrics/pomme/mononoke.html")
    case("a page you named, for a song LRCLIB hasn't failed on",
         lambda w: w.song("Someone Else", "Mononoke"),
         lambda w, sid: {MONONOKE: AZ_HIT[MONONOKE]}, picks="https://www.azlyrics.com/lyrics/pomme/mononoke.html")
    case("a page you named, for a song with lyrics: nothing",
         lambda w: w.song("Someone Else", "Mononoke", lyrics_status="found", lyrics_json=plain_lrclib()),
         lambda w, sid: {}, picks="azlyrics.com/lyrics/pomme/mononoke.html")
    case("an error on a song the others missed: back to pending",
         lambda w: missed(w), lambda w, sid: {POMME: status(502, "Bad Gateway")})
    case("an error on the lyrics page: back to pending",
         lambda w: missed(w), lambda w, sid: {POMME: AZ_HIT[POMME], MONONOKE: status(500, "oops")})
    case("an artist page that won't parse: an error, never a miss",
         lambda w: missed(w), lambda w, sid: {POMME: ok(fixture_ref("azlyrics/not_found.html"), HTML)})
    case("a cached page that won't parse, asked for once more",
         lambda w: missed(w), lambda w, sid: AZ_HIT,
         cache=lambda w, sid: {POMME: held(ok(text("<html>maintenance</html>"), HTML))})
    case("its block page, a 200: a block, never kept in the cache",
         lambda w: missed(w), lambda w, sid: {POMME: AZ_BLOCK}, asked=f"{AZ}/p/pomme.html")
    case("its block page on the lyrics page: a block",
         lambda w: missed(w), lambda w, sid: {POMME: AZ_HIT[POMME], MONONOKE: AZ_BLOCK},
         asked=f"{AZ}/lyrics/pomme/mononoke.html")
    case("a 403: a block, nothing marked",
         lambda w: missed(w), lambda w, sid: {POMME: status(403, "Forbidden")})
    case("a budget spent before the lyrics page: nothing marked",
         lambda w: missed(w), lambda w, sid: {POMME: AZ_HIT[POMME]}, budget=1)
    return out


# --- the tests --------------------------------------------------------------------------------------------------


def every_file(tmp: Path) -> dict[str, str]:
    return {
        "lrclib-sites": jsonl(lrclib_site_records(), corpus="sites/lrclib", made_by=MADE_BY),
        "megalobiz-sites": jsonl(megalobiz_site_records(), corpus="sites/megalobiz", made_by=MADE_BY),
        "azlyrics-sites": jsonl(azlyrics_site_records(), corpus="sites/azlyrics", made_by=MADE_BY),
        "lrclib-lookup": jsonl(lrclib_scenarios(tmp), corpus="lookup/lrclib", made_by=MADE_BY),
        "megalobiz-lookup": jsonl(megalobiz_scenarios(tmp), corpus="lookup/megalobiz", made_by=MADE_BY),
        "azlyrics-lookup": jsonl(azlyrics_scenarios(tmp), corpus="lookup/azlyrics", made_by=MADE_BY),
    }


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> dict[str, str]:
    return every_file(tmp_path_factory.mktemp("lyrics"))


@pytest.mark.parametrize("name", sorted(FILES))
def test_the_vector_is_what_the_lyrics_sites_do(made, name):
    check(FILES[name], made[name])


def test_the_vectors_are_the_same_on_another_run(made, tmp_path):
    assert every_file(tmp_path) == made


def _records(text_: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text_.splitlines()[1:]]


def _cases(made: dict[str, str], name: str) -> dict[str, dict[str, Any]]:
    return {r["case"]: r for r in _records(made[name])}


def test_every_scenario_answers_what_it_asked_and_nothing_else(made):
    for name in ("lrclib-lookup", "megalobiz-lookup", "azlyrics-lookup"):
        for r in _records(made[name]):
            done = r.get("out") or r["after"]
            assert set(r["answers"]) <= set(done["requests"]), r["case"]


def test_the_lrclib_pass_writes_its_files_and_its_json(made):
    cases = _cases(made, "lrclib-lookup")
    hit = cases["a hit on /api/get: lyrics.txt, lyrics.lrc and lyrics_json, the failed record gone"]["out"]
    assert set(hit["library"]) == {"Soda Stereo/De Música Ligera/lyrics.txt", "Soda Stereo/De Música Ligera/lyrics.lrc"}
    assert json.loads(hit["rows"]["songs"][0]["lyrics_json"])["provider"] == "lrclib"
    assert list(hit["kv"].values()) == [None]
    banma = cases["a miss, then the search with the Han joined: plain lyrics alone, a stale lyrics.lrc gone"]["out"]
    assert banma["library"]["宋冬野/斑马，斑马/lyrics.lrc"] is None
    assert "%E6%96%91%E9%A9%AC%E6%96%91%E9%A9%AC" in banma["requests"][1]


def test_errors_are_never_misses(made):
    lrclib = _cases(made, "lrclib-lookup")
    busy = lrclib["LRCLIB's 503, asked once more after its Retry-After, then an error: never a miss"]["out"]
    assert len(busy["requests"]) == 2 and busy["result"]["errors"] == 1
    assert "songs" not in busy["rows"] and list(busy["kv"]) == ["lyrics:failed:1"]  # pending, as it was
    back = _cases(made, "megalobiz-lookup")["an error on a song LRCLIB missed: back to pending"]["out"]
    assert (back["rows"]["songs"][0]["lyrics_status"], back["rows"]["songs"][0]["lyrics_at"]) == ("pending", None)
    az = _cases(made, "azlyrics-lookup")["an error on a song the others missed: back to pending"]["out"]
    assert az["rows"]["songs"][0]["lyrics_status"] == "pending"


def test_a_miss_is_remembered_thirty_days(made):
    m = _cases(made, "megalobiz-lookup")
    assert m["no result that fits: a miss, its time, the song still missing"]["out"]["kv"] == {
        "megalobiz:checked:1": STAMP}
    assert m["a miss within 30 days: nothing asked"]["out"]["requests"] == []
    az = _cases(made, "azlyrics-lookup")
    assert az["no such artist: a miss of one request"]["out"]["kv"] == {"azlyrics:checked:1": STAMP}


def test_the_block_page_is_a_block_never_kept(made):
    az = _cases(made, "azlyrics-lookup")
    for case in ("its block page, a 200: a block, never kept in the cache", "its block page on the lyrics page: a block"):
        result = az[case]["out"]["result"]
        assert result["blocked"]["type"] == "ProviderBlocked" and result["cached"] is False
    raised_ = {r["case"]: r["raises"]["type"] for name in ("lrclib-lookup", "megalobiz-lookup", "azlyrics-lookup")
               for r in _records(made[name]) if "raises" in r}
    assert set(raised_.values()) == {"ProviderBlocked"}


def test_the_parsers_round_half_to_even(made):
    lrc = next(r for r in _records(made["megalobiz-sites"]) if r.get("case") == "made from its lines, rounded half to even")
    stamps = dict(line.split("]", 1)[::-1] for line in lrc["out"]["lrc"].split("\n"))
    assert stamps["line 1005"] == "[00:01.00" and stamps["line 1015"] == "[00:01.01"  # 1.005 is just under, 1.015 over
    assert stamps["line 59995"] == "[00:59.99" and stamps["line 59996"] == "[00:60.00"
    assert stamps["line -61005"] == "[-2:58.99" and stamps["a bool"] == "[00:00.00"  # a bool is an int to Python
