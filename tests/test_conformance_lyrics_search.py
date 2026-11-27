"""``caracole lyrics --song X --as "A - T"`` for the phone: whole searches recorded, for core's
``LyricsSearchCommands`` (the chords-on-the-phone design's §8.5, the plan's E29) to agree with.

**Vectors** (``vectors/lookup/lyrics_search.jsonl``), a header, then a record a line, each a scenario record
(helpers/scenario.py ``record_lookup``) of a world of test_conformance_lookup_scenarios.py's (``World``, the fake
lyrics sites by address: LRCLIB's ``/api/search`` and ``/api/get``, Megalobiz's ``/search``, AZLyrics' pages), each
with:

- ``fn``: ``caracole.commands.lyrics._lyrics_as``, as caracole serve queues it (``kw``: ``song``, the song's
  "Artist - Title"; ``as``, the name typed; ``providers``, the caracole.toml fields of the world's providers);
- ``out.result``: ``{result: {lines}, progress: []}``, every line the command prints, its last ``last_line``'s, the one
  the Journal reads;
- the requests in order (2 to 4: LRCLIB's search, its get only where no record of the search fits, Megalobiz's search,
  AZLyrics' artist page where one can be named), the rows it changed (``phone_overrides``: ``[lyrics]``' ``as``;
  ``songs``: a question asked anew), the kv it changed (``lyrics-search:<id>``, the search kept; the misses
  ``ask_anew`` forgets; a block's or an error's ``provider:``), the events and the pauses.

The cases: three sites listing records, the best fit first then those that fit then the rest, an instrumental record
counted and a song missing asked anew; no record of LRCLIB's search fitting, its get asked; AZLyrics' page of the typed
artist listing the title, under the song's own name (no ``as`` kept); a name with no Latin letter (AZLyrics not asked);
Megalobiz off and LRCLIB cooling down; Megalobiz blocking caracole and LRCLIB's get failing after its search answered;
nothing found anywhere; the hour's asks of LRCLIB spent; the same name again within the week (every answer from the
cache, no request) and past it (asked again); a song with lyrics found given another name (its lyrics as they are);
and back to the song's own name (its ``as`` taken out, its record kept).

Regenerate with ``CARACOLE_CORPUS=write nix develop -c pytest -q -n 0 tests/test_conformance_lyrics_search.py``.
"""

from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from helpers.corpus import VECTORS, check, fixture_ref, jsonl
from helpers.scenario import record_lookup
from test_conformance_lookup_scenarios import AZLYRICS, JSON, NOW, STAMP, Sites, World

MADE_BY = "tests/test_conformance_lyrics_search.py"
VECTOR = VECTORS / "lookup" / "lyrics_search.jsonl"
HTML = [["content-type", "text/html; charset=utf-8"]]

SONG = ("Nick Cani", "Vikingos veganos (Video Oficial)")
NAME = "Nick Cani - Vikingos veganos"
NICK_PAGE = f"{AZLYRICS}n/nickcani.html"
POMME_PAGE = f"{AZLYRICS}p/pomme.html"
SYNCED = "[00:24.80]Somos vikingos de prueba\n[00:30.10]comemos lechuga de prueba"
PLAIN = "Somos vikingos de prueba\ncomemos lechuga de prueba"
EARLIER = "2026-11-01T00:00:00Z"


def lrc(lrclib_id: int, *, track: str = "Vikingos veganos", artist: str = "Nick Cani", album: str | None = "Pruebas",
        duration: float = 200.0, timed: bool = True, instrumental: bool = False) -> dict[str, Any]:
    return {"id": lrclib_id, "name": track, "trackName": track, "artistName": artist, "albumName": album,
            "duration": duration, "instrumental": instrumental, "plainLyrics": None if instrumental else PLAIN,
            "syncedLyrics": SYNCED if timed and not instrumental else None}


def answered(body: Any, status: int = 200) -> dict[str, Any]:
    return {"status": status, "headers": JSON, "body": json.dumps(body, ensure_ascii=False)}


def mz(*records: tuple[int, str, str, float | None]) -> dict[str, Any]:
    """Megalobiz's search answering ``records`` (id, title, artist, length), in its shape."""
    results = [{"id": i, "title": t, "artist": a, "duration": d, "sync": "manual", "score": 1,
                "url": f"https://megalobiz.com/lrc/{i}/{'-'.join(t.lower().split())}"} for i, t, a, d in records]
    return answered({"query": {}, "count": len(results), "results": results})


NOT_FOUND = {"status": 404, "headers": HTML, "body": fixture_ref("azlyrics/not_found.html")}
GET_MISS = answered({"code": 404, "name": "TrackNotFound", "message": "Failed to find specified track"}, 404)
POMME = {"status": 200, "headers": HTML, "body": fixture_ref("azlyrics/artist_pomme.html")}


def sites(search: list[Any] | None = None, *, got: dict[str, Any] | None = None, megalobiz: dict[str, Any] | None = None,
          pages: dict[str, dict[str, Any]] | None = None) -> Sites:
    return Sites(lrclib_search=answered(search if search is not None else []),
                 lrclib_get=got if got is not None else GET_MISS,
                 megalobiz_search=megalobiz if megalobiz is not None else mz(),
                 pages={NICK_PAGE: NOT_FOUND, **(pages or {})})


def world(tmp: Path, name: str, **kw: Any) -> World:
    return World(tmp, name, **kw)


def missing_song(w: World, artist: str = SONG[0], title: str = SONG[1], **fields: Any) -> int:
    """The song, missing its lyrics since an earlier night, LRCLIB's failure and Megalobiz's miss noted."""
    from caracole import db

    song_id = w.song(artist, title, duration_ms=200000, lyrics_status="missing", lyrics_at=EARLIER, **fields)
    db.kv_set(w.conn, f"lyrics:failed:{song_id}", EARLIER)
    db.kv_set(w.conn, f"megalobiz:checked:{song_id}", EARLIER)
    return song_id


def search(w: World, case: str, display: str, typed: str, answers: Sites, *, cache: dict[str, Any] | None = None,
           now=NOW) -> dict[str, Any]:
    """``caracole lyrics --song DISPLAY --as TYPED`` at ``now``, recorded."""
    from caracole.commands import lyrics as cmd

    def call() -> dict[str, Any]:
        lines: list[str] = []
        with mock.patch.object(cmd, "exclusive", lambda *a, **k: nullcontext()), \
                mock.patch("typer.echo", lines.append):
            cmd._lyrics_as(w.cfg, display, typed)
        return {"result": {"lines": lines}, "progress": []}

    return record_lookup(w.cfg, fn="caracole.commands.lyrics._lyrics_as", call=call, answers=answers, now=now,
                         case=case, kw={"song": display, "as": typed, "providers": w.providers}, cache=cache,
                         settle=w.settled(now))


def _cached(made: dict[str, Any], fetched_at: str) -> dict[str, Any]:
    """The answers a record was given, as a cache of them fetched at ``fetched_at``, by provider."""
    by_host = {"lrclib.net": "lrclib", "api.megalobiz.com": "megalobiz", "www.azlyrics.com": "azlyrics"}
    cache: dict[str, dict[str, Any]] = {}
    for said, answer in made["answers"].items():
        provider = by_host[said.split("/")[2]]
        headers = {k: v for k, v in answer["headers"]}
        cache.setdefault(provider, {})[said] = {"status": answer["status"], "fetched_at": fetched_at,
                                                "headers": headers, "body": answer["body"]}
    return cache


def records(tmp: Path) -> list[dict[str, Any]]:
    from caracole.health import record_block
    from caracole.overrides import set_lyrics_name, set_lyrics_record

    made: list[dict[str, Any]] = []
    display = f"{SONG[0]} - {SONG[1]}"
    listing = sites([lrc(78, artist="Somebody Else"), lrc(77), lrc(90, instrumental=True),
                     lrc(79, track="Vikingos veganos", duration=260.0, timed=False, album=None)],
                    megalobiz=mz((5001, "Vikingos veganos", "Nick Cani", 201.5), (5002, "Otra cosa", "Nadie", None)))

    w = world(tmp, "listing")
    missing_song(w)
    made.append(search(w, "three sites list records: the best fit first, then those that fit, then the rest; an "
                          "instrumental record counted; the song missing asked anew", display, NAME, listing))

    w = world(tmp, "get")
    missing_song(w)
    made.append(search(w, "no record of LRCLIB's search fits: its get asked, its record the best", display, NAME,
                       sites([lrc(78, artist="Somebody Else")], got=answered(lrc(80, album=None)))))

    w = world(tmp, "own")
    w.song("Pomme", "Mononoké", duration_ms=None)
    made.append(search(w, "AZLyrics' page of the typed artist lists the title, under the song's own name: no as kept",
                       "Pomme - Mononoké", "Pomme - Mononoke", sites(pages={POMME_PAGE: POMME})))

    w = world(tmp, "han")
    w.song("孟维来", "野人『动态歌词MV』", duration_ms=None)
    made.append(search(w, "a name with no Latin letter: AZLyrics isn't asked", "孟维来 - 野人『动态歌词MV』",
                       "孟维来 - 野人", sites([lrc(81, track="野人", artist="孟维来", album=None)])))

    w = world(tmp, "off", providers={"megalobiz": {"enabled": False}})
    missing_song(w)
    record_block(w.conn, "lrclib", NOW - timedelta(hours=1), "429 Too Many Requests")
    made.append(search(w, "Megalobiz off and LRCLIB cooling down: AZLyrics alone asked", display, NAME, sites()))

    w = world(tmp, "stopped")
    missing_song(w)
    made.append(search(w, "Megalobiz blocks caracole and LRCLIB's get fails after its search answered: its rows stay",
                       display, NAME, sites([lrc(78, artist="Somebody Else")],
                                            got={"status": 502, "headers": HTML, "body": "Bad Gateway"},
                                            megalobiz={"status": 429, "headers": JSON, "body": "{}"})))

    w = world(tmp, "nothing")
    missing_song(w)
    made.append(search(w, "nothing found anywhere", display, NAME, sites()))

    w = world(tmp, "spent", providers={"lrclib": {"lookup_per_hour": 2}})
    missing_song(w)
    w.lookups("lrclib", 2)
    made.append(search(w, "the hour's asks of LRCLIB spent", display, NAME,
                       sites(megalobiz=mz((5001, "Vikingos veganos", "Nick Cani", 201.5)))))

    w = world(tmp, "cached")
    missing_song(w)
    first = made[0]
    made.append(search(w, "the same name again within the week: every answer from the cache, no request", display,
                       NAME, sites(), cache=_cached(first, "2026-10-30T12:00:00Z")))

    w = world(tmp, "stale")
    missing_song(w)
    made.append(search(w, "the same name again past the week: every site asked again", display, NAME, listing,
                       cache=_cached(first, "2026-10-20T12:00:00Z")))

    w = world(tmp, "found")
    song_id = w.song(*SONG, duration_ms=200000, lyrics_status="found", lyrics_at=EARLIER)
    w.overrides(lambda path: set_lyrics_name(path, display, "Nick Cani - Vikingos"))
    made.append(search(w, "a song with lyrics found given another name: its lyrics as they are", display, NAME,
                       listing))
    assert song_id

    w = world(tmp, "back")
    missing_song(w, title="Vikingos veganos")
    w.overrides(lambda path: (set_lyrics_name(path, NAME, "Nick Cani - Vikingos"),
                              set_lyrics_record(path, NAME, "lrclib:77")))
    made.append(search(w, "back to the song's own name: its as taken out, its record kept", NAME, NAME, listing))
    return made


@pytest.fixture(scope="module")
def made(tmp_path_factory) -> list[dict[str, Any]]:
    return records(tmp_path_factory.mktemp("lyrics-search"))


def test_the_vector_is_what_caracole_lyrics_as_does(made):
    check(VECTOR, jsonl(made, corpus="lookup", made_by=MADE_BY))


def test_the_vector_is_the_same_on_another_run(made, tmp_path):
    assert jsonl(records(tmp_path), corpus="lookup", made_by=MADE_BY) == jsonl(made, corpus="lookup",
                                                                               made_by=MADE_BY)


def _last(record: dict[str, Any]) -> str:
    return record["out"]["result"]["result"]["lines"][-1]


def test_the_cases_come_to_what_they_say(made):
    from caracole.lyrics_search import KV

    by = {r["case"].split(":")[0]: r for r in made}
    for record in made:
        assert 0 <= len(record["out"]["requests"]) <= 4, record["case"]
    listing = by["three sites list records"]
    assert len(listing["out"]["requests"]) == 3 and _last(listing).startswith("Searched: ")
    kept = json.loads(next(v for k, v in listing["out"]["kv"].items() if k.startswith(KV)))
    assert [r["record"] for r in kept["rows"]][:3] == ["lrclib:77", "lrclib:79", "megalobiz:5001"]
    assert kept["rows"][0]["best"] and kept["instrumental"] == 1
    assert any(k.startswith("lyrics:failed:") and v is None for k, v in listing["out"]["kv"].items())
    assert len(by["no record of LRCLIB's search fits"]["out"]["requests"]) == 4
    own = by["AZLyrics' page of the typed artist lists the title, under the song's own name"]
    assert "phone_overrides" not in own["out"]["rows"] and "AZLyrics lists 1 record" in _last(own)
    assert len(by["a name with no Latin letter"]["out"]["requests"]) == 2
    assert _last(by["Megalobiz off and LRCLIB cooling down"]).startswith("Not searched: waiting out LRCLIB")
    stopped = json.loads(next(v for k, v in by["Megalobiz blocks caracole and LRCLIB's get fails after its search "
                                                 "answered"]["out"]["kv"].items() if k.startswith(KV)))
    assert stopped["state"] == {"lrclib": "rows", "megalobiz": "blocked", "azlyrics": "none"}
    assert _last(by["nothing found anywhere"]).startswith("Nothing found: ")
    assert "this hour" in json.loads(next(v for k, v in by["the hour's asks of LRCLIB spent"]["out"]["kv"].items()
                                          if k.startswith(KV)))["said"]["lrclib"]
    assert by["the same name again within the week"]["out"]["requests"] == []
    assert len(by["the same name again past the week"]["out"]["requests"]) == 3
    assert "songs" not in by["a song with lyrics found given another name"]["out"]["rows"]
    back = by["back to the song's own name"]["out"]["rows"]["phone_overrides"]
    assert [json.loads(r["value"]) for r in back if r["tbl"] == "lyrics"] == [{"record": "lrclib:77"}]
    assert STAMP
