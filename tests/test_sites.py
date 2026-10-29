"""sites.py: the Sites tab's data, each site's words and figures, read with no request."""

from __future__ import annotations

from caracole import icons
from caracole.http import ROBOTS_DISALLOW
from caracole.sites import SITES, more_paths


def site(key):
    return next(s for s in SITES if s.key == key)


def test_the_sites_are_icons_sources_less_the_two_that_are_no_site():
    assert [s.key for s in SITES] == [k for k in icons.SOURCES if k not in ("auto", "inbox")]


def test_every_path_named_is_one_caracole_keeps_out_of():
    for s in SITES:
        if s.key == "youtube":
            continue
        for path, words in s.paths:
            assert words
            assert any(path in ROBOTS_DISALLOW.get(host, ()) for host in s.hosts), (s.key, path)


def test_youtubes_paths_are_named_from_its_robots_txt_and_said_to_be_gone_against():
    youtube = site("youtube")
    assert [path for path, _ in youtube.paths] == ["/results", "/youtubei/"]
    assert not any(path in rules for path, _ in youtube.paths for rules in ROBOTS_DISALLOW.values())
    assert "caracole goes against" in youtube.robots


def test_the_three_sites_of_the_owners_exceptions_carry_their_terms():
    assert {s.key for s in SITES if s.terms} == {"harptabs", "gametabs", "youtube"}


def test_gametabs_says_it_asks_five_seconds_and_caracole_asks_once_a_second():
    assert "5 s" in site("gametabs").robots
    assert "once a second" in site("gametabs").robots


def test_lacuerda_closes_nothing():
    assert site("lacuerda").paths == ()
    assert more_paths(site("lacuerda")) == 0


def test_the_rest_of_a_sites_closed_paths_are_counted():
    ug = site("ug")
    every = set(ROBOTS_DISALLOW["www.ultimate-guitar.com"]) | set(ROBOTS_DISALLOW["tabs.ultimate-guitar.com"])
    assert more_paths(ug) == len(every) - len(ug.paths)
    assert more_paths(site("youtube")) == 0


def test_only_the_sites_with_no_index_say_how_they_are_asked():
    assert {s.key: s.asked for s in SITES if s.asked} == {
        "lrclib": "Asked song by song", "youtube": "Searched song by song"}
