"""ug/bands.py: UG's letter listings of artists, read from real pages (tests/fixtures/ug/bands/, 2026-11-17)."""

from __future__ import annotations

from pathlib import Path

import pytest

from caracole.ug.bands import LETTERS, ListingParseError, listing_url, parse_listing
from helpers.ug_pages import store_page_html

BANDS = Path(__file__).parent / "fixtures" / "ug" / "bands"


def _page(name: str) -> str:
    return (BANDS / name).read_text(encoding="utf-8")


def test_the_27_listings_and_their_addresses():
    assert len(LETTERS) == 27 and LETTERS[0] == "0-9" and LETTERS[-1] == "z"
    assert listing_url("s") == "https://www.ultimate-guitar.com/bands/s.htm"
    assert listing_url("s", 2) == "https://www.ultimate-guitar.com/bands/s2.htm"
    assert listing_url("0-9", 3) == "https://www.ultimate-guitar.com/bands/0-93.htm"
    with pytest.raises(ValueError):
        listing_url("ñ")


def test_a_first_page_names_its_listing_and_its_artists_most_popular_first():
    page = parse_listing(_page("s.html"), "s", 1)
    assert (page.letter, page.page, page.pages, page.count) == ("s", 1, 293, 14625)
    assert len(page.artists) == 50 and not page.last
    first = page.artists[0]
    assert (first.artist_id, first.name, first.slug, first.tabs) == (274, "Simon & Garfunkel", "simon_garfunkel", 673)
    assert first.url == "https://www.ultimate-guitar.com/artist/simon_garfunkel_274"
    assert first.updated == 1790085971 and not first.bare


def test_a_bare_address_is_an_artist_with_a_letter_outside_ascii():
    page = parse_listing(_page("0-9.html"), "0-9", 1)
    kino = next(a for a in page.artists if a.name == "Кино")
    assert (kino.artist_id, kino.slug, kino.url) == (13472, "", "https://www.ultimate-guitar.com/artist/13472")
    assert kino.bare
    assert all(a.bare != a.name.isascii() for a in page.artists if a.name.isascii() or a.bare)


def test_the_last_page_holds_fewer():
    page = parse_listing(_page("s293.html"), "s", 293)
    assert page.last and len(page.artists) == 23
    assert any(a.name == "Sŵnami" and a.bare for a in page.artists)


def test_another_listing_or_page_than_the_one_asked_for_is_an_error():
    with pytest.raises(ListingParseError, match="not of 't'"):
        parse_listing(_page("s.html"), "t", 1)
    with pytest.raises(ListingParseError, match="not page 2"):
        parse_listing(_page("s.html"), "s", 2)


def _data(**changes):
    data = {"alpha": "S", "current_page": 1, "page_count": 3, "artists_count": 150, "tabs_per_page": 50,
            "artists": [{"id": n, "name": f"Artist {n}", "tabscount": 3, "artist_url": f"/artist/artist_{n}_{n}",
                         "tabs_last_update_timestamp": 1790000000, "localized_name": f"Artist {n}"}
                        for n in range(1, 51)]}
    data.update(changes)
    return store_page_html(data)


def test_a_page_cut_short_before_the_last_is_an_error_never_fewer_artists():
    with pytest.raises(ListingParseError, match="cut short"):
        parse_listing(_data(artists=[]), "s", 1)
    with pytest.raises(ListingParseError, match="no list"):
        parse_listing(_data(artists=None), "s", 1)
    with pytest.raises(ListingParseError):
        parse_listing("<html><body>Maintenance</body></html>", "s", 1)
    assert len(parse_listing(_data(), "s", 1).artists) == 50


def test_an_entry_that_names_no_artist_is_passed_over():
    entries = [{"id": None, "name": "x", "artist_url": "/artist/x_1"}, {"id": 2, "name": " ", "artist_url": "/artist/2"},
               {"id": 3, "name": "Three", "artist_url": "/tab/3"}, "junk",
               {"id": 4, "name": "Four", "artist_url": "/artist/4", "tabscount": None}]
    page = parse_listing(_data(page_count=1, artists=entries), "s", 1)
    assert [(a.artist_id, a.tabs, a.updated) for a in page.artists] == [(4, 0, None)]
