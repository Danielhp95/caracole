"""Megalobiz's public API, read: its search, a record's timed lyrics, and the result a song takes.

Fixtures in ``tests/fixtures/megalobiz/``: the searches caracole's own user agent got on 2026-10-30 (Eagles – Hotel
California, Toby Fox – Megalovania and Estopa – Vacaciones trimmed to three results each; 宋冬野 – 斑马斑马 found
nothing), whose results hold names alone; one ``/lrc/{id}`` record in the live one's shape (its keys, its LRC's
tags) with invented words; and its 404 and 429 bodies, synthetic, from its docs. The robots.txt of megalobiz.com, and
the API host's 404 for one, are the live files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caracole.http import ROBOTS_DISALLOW, Response, robots_disallows
from caracole.megalobiz import (
    API,
    MegalobizParseError,
    Result,
    lrc_url,
    parse_lrc,
    parse_search,
    pick_result,
    search_params,
)

FIXTURES = Path(__file__).parent / "fixtures" / "megalobiz"


def answer(name: str, url: str = f"{API}/search", status: int = 200) -> Response:
    return Response(url=url, status=status, content=(FIXTURES / name).read_bytes())


def body(data, url: str = f"{API}/search") -> Response:
    return Response(url=url, status=200, content=json.dumps(data).encode())


def results(name: str) -> list[Result]:
    return parse_search(answer(name))


# --- addresses ---------------------------------------------------------------------------------------------------


def test_the_search_asks_by_title_and_artist_and_whole_seconds_when_known():
    assert search_params("Eagles", "Hotel California", 391.4) == {
        "title": "Hotel California", "artist": "Eagles", "duration": 391, "limit": 10}
    assert search_params("Eagles", "Hotel California - 2013 Remaster", None) == {
        "title": "Hotel California", "artist": "Eagles", "limit": 10}


def test_a_records_address_is_its_id_under_the_api():
    assert lrc_url(24519) == "https://api.megalobiz.com/api/public/v1/lrc/24519"


def test_its_robots_rules_are_megalobiz_coms_and_the_api_host_has_none():
    # megalobiz.com's robots.txt allows all but its accounts and editors; the API host answers 404 for one.
    rules = [line.split(":", 1)[1].strip() for line in (FIXTURES / "robots.txt").read_text().splitlines()
             if line.startswith("Disallow:")]
    star = rules[: rules.index("/")] if "/" in rules else rules  # the BitChord group's "/" is not caracole's
    assert list(ROBOTS_DISALLOW["megalobiz.com"]) == star
    assert all(robots_disallows(f"https://megalobiz.com{rule}x") for rule in star)
    assert robots_disallows("https://megalobiz.com/lrc/24519/hotel-california") is None
    assert robots_disallows(lrc_url(24519)) is None
    assert "Cannot GET /robots.txt" in (FIXTURES / "api_robots_404.html").read_text()


# --- the search ----------------------------------------------------------------------------------------------------


def test_a_search_reads_each_result():
    first, *_ = results("search_hotel_california.json")
    assert first == Result(id=24519, title="Hotel California", artist="Eagles", duration=391.55,
                           url="https://megalobiz.com/lrc/24519/hotel-california")
    assert len(results("search_hotel_california.json")) == 3


def test_a_search_that_found_nothing_has_no_result():
    assert results("search_empty.json") == []


@pytest.mark.parametrize("data", [
    [], {"count": 0}, {"results": {}}, {"results": [{"id": "x", "title": "T", "artist": "A", "url": "u"}]},
    {"results": [{"id": 1, "title": "T", "artist": "A", "url": "https://elsewhere.example/lrc/1"}]},
], ids=["a list", "no results", "results not a list", "an id not a number", "a link off the site"])
def test_a_search_answer_not_as_documented_is_a_parse_error_never_no_result(data):
    with pytest.raises(MegalobizParseError):
        parse_search(body(data))


def test_an_answer_that_isnt_json_is_a_parse_error():
    with pytest.raises(MegalobizParseError):
        parse_search(Response(url=f"{API}/search", status=200, content=b"<html>Maintenance</html>"))


# --- a record -------------------------------------------------------------------------------------------------------


def test_a_record_gives_its_timed_lyrics_and_where_it_is_on_the_site():
    lrc = parse_lrc(answer("lrc_24519.json", lrc_url(24519)))
    assert (lrc.id, lrc.title, lrc.artist, lrc.duration) == (24519, "Hotel California", "Eagles", 391.55)
    assert lrc.url == "https://megalobiz.com/lrc/24519/hotel-california"
    assert lrc.lrc.startswith("[ar:Eagles]\n[ti:Hotel California]\n")
    assert "[00:23.62]Línea uno de prueba en el desierto" in lrc.lrc


def test_a_record_with_lines_and_no_lrc_text_is_read_from_its_lines():
    data = json.loads((FIXTURES / "lrc_24519.json").read_text())
    data["lrc"] = ""
    lrc = parse_lrc(body(data, lrc_url(24519)))
    assert lrc.lrc.splitlines()[0] == "[00:23.62]Línea uno de prueba en el desierto"


def test_a_record_with_no_timed_line_has_no_lyrics():
    data = json.loads((FIXTURES / "lrc_24519.json").read_text())
    data["lrc"], data["lines"] = "[ar:Eagles]\n[ti:Hotel California]", []
    assert parse_lrc(body(data, lrc_url(24519))).lrc == ""


@pytest.mark.parametrize("change", [{"lrc": None, "lines": None}, {"id": None}, {"url": None}],
                         ids=["no lyrics fields", "no id", "no link"])
def test_a_record_not_as_documented_is_a_parse_error(change):
    data = {**json.loads((FIXTURES / "lrc_24519.json").read_text()), **change}
    with pytest.raises(MegalobizParseError):
        parse_lrc(body(data, lrc_url(24519)))


# --- the result a song takes ---------------------------------------------------------------------------------------


def test_the_song_takes_the_result_closest_to_its_length():
    found = pick_result(results("search_hotel_california.json"), artist="Eagles", title="Hotel California",
                        duration_s=373.0)
    assert found is not None and found.id == 23812


def test_without_a_length_the_first_result_that_fits_wins():
    found = pick_result(results("search_hotel_california.json"), artist="Eagles", title="Hotel California",
                        duration_s=None)
    assert found is not None and found.id == 24519


def test_a_result_more_than_10_s_off_needs_the_same_names():
    near = Result(id=1, title="Hotel Californias", artist="Eagles", duration=420.0, url="https://megalobiz.com/lrc/1/x")
    same = Result(id=2, title="Hotel California", artist="Eagles", duration=420.0, url="https://megalobiz.com/lrc/2/x")
    assert pick_result([near], artist="Eagles", title="Hotel California", duration_s=391.0) is None
    assert pick_result([near, same], artist="Eagles", title="Hotel California", duration_s=391.0).id == 2


def test_another_songs_results_are_no_fit():
    # Estopa's other songs, and another artist's "Vacaciones": the search's own ranking matches neither.
    assert pick_result(results("search_vacaciones.json"), artist="Estopa", title="Vacaciones",
                       duration_s=None) is None


def test_a_fans_vocal_cover_with_no_artist_is_no_fit():
    # Live: Megalovania's search led with another of Toby Fox's titles and a "Vocal cover" credited to no one.
    assert pick_result(results("search_megalovania.json"), artist="Toby Fox", title="Megalovania",
                       duration_s=None) is None


@pytest.mark.parametrize("title", ["Hotel California (Cover)", "Hotel California (Karaoke Version)",
                                   "Hotel California - Instrumental", "Hotel California (Nightcore)",
                                   "Hotel California [Vocal Version]"])
def test_a_cover_or_another_kind_of_version_is_no_fit(title):
    cover = Result(id=1, title=title, artist="Eagles", duration=391.0, url="https://megalobiz.com/lrc/1/x")
    assert pick_result([cover], artist="Eagles", title="Hotel California", duration_s=391.0) is None


def test_a_version_the_song_itself_names_still_fits():
    live = Result(id=1, title="Hotel California (Acoustic Cover)", artist="Eagles", duration=391.0,
                  url="https://megalobiz.com/lrc/1/x")
    assert pick_result([live], artist="Eagles", title="Hotel California (Acoustic Cover)", duration_s=391.0) == live


def test_a_result_credited_to_no_one_is_no_fit_even_with_the_title():
    nobody = Result(id=1, title="Hotel California", artist="", duration=391.0, url="https://megalobiz.com/lrc/1/x")
    assert pick_result([nobody], artist="Eagles", title="Hotel California", duration_s=391.0) is None
