"""gametabs.py: the sitemaps' pages as index rows, a tab page and a game page read, from what the site answered."""

from __future__ import annotations

import pytest
from helpers.gametabs_site import BASE, fixture, game_page, tab_page

from caracole.gametabs import (
    GAME,
    TAB,
    GamePage,
    GameTab,
    GameTabsParseError,
    IndexRow,
    page_url,
    parse_game_page,
    parse_page_url,
    parse_tab_page,
    sitemap_child,
    title_key,
)
from caracole.http import crawl_delay, robots_disallows
from caracole.ug.sitemap import iter_locs

# --- the sitemaps -----------------------------------------------------------------------------------------------------


def test_the_index_reads_its_numbered_sitemaps_and_never_the_static_one():
    children = list(iter_locs(fixture("sitemap.xml").encode()))
    assert len(children) == 7
    assert [sitemap_child(url) for url in children] == [None, *(f"sitemap_{n}" for n in range(1, 7))]
    assert sitemap_child(f"{BASE}/sitemap_static.xml.gz") is None
    assert sitemap_child("https://example.com/sitemap_1.xml.gz") is None


def test_a_sitemap_gives_its_games_and_tabs_and_nothing_else():
    rows = [r for r in map(parse_page_url, iter_locs(fixture("sitemap_1.xml").encode())) if r is not None]
    # The top tabs, the A-Z lists of games: no rows. A game's pages after the first are rows of their own.
    assert [r.path for r in rows if r.kind == GAME] == [
        "tabs/actraiser", "tabs/age-of-empires-ii", "tabs/army-men-sarge039s-heroes", "tabs/final-fantasy-vii",
        "tabs/final-fantasy-vii?page=2", "tabs/game-of-thrones", "tabs/hollow-knight"]
    assert parse_page_url(f"{BASE}/tabs/final-fantasy-vii?page=2") == IndexRow(
        "tabs/final-fantasy-vii?page=2", GAME, "final-fantasy-vii", "", 2, "final-fantasy-vii", "final-fantasy-vii")
    assert parse_page_url(f"{BASE}/tabs/actraiser/fillmore") == IndexRow(
        "tabs/actraiser/fillmore", TAB, "actraiser", "fillmore", 0, "fillmore", "fillmore")
    assert len([r for r in rows if r.kind == TAB]) == 9
    for url in (f"{BASE}/top-tabs", f"{BASE}/games?starts_with=a", f"{BASE}/tabs?composers=12",
                f"{BASE}/tabs/actraiser/fillmore/edit", "https://example.com/tabs/actraiser"):
        assert parse_page_url(url) is None, url


def test_a_slugs_number_is_one_more_tab_of_the_title_never_part_of_it():
    # The site numbers a slug that repeats ("main-theme-108": the 108th "Main Theme"), across games; a title that
    # ends in a number keeps it in its whole slug's key, which a song of that title meets.
    row = parse_page_url(f"{BASE}/tabs/game-of-thrones/main-theme-108")
    assert (row.key, row.slug_key) == ("main-theme", "main-theme-108")
    row = parse_page_url(f"{BASE}/tabs/hollow-knight/resting-grounds-2")
    assert (row.key, row.slug_key) == ("resting-grounds", "resting-grounds-2")
    row = parse_page_url(f"{BASE}/tabs/sonic-the-hedgehog/green-hill-zone-act-2")
    assert title_key("Green Hill Zone Act 2") == row.slug_key


def test_a_page_url_is_its_path_on_the_site():
    assert page_url("tabs/actraiser/fillmore") == f"{BASE}/tabs/actraiser/fillmore"
    assert page_url("tabs/final-fantasy-vii?page=2") == f"{BASE}/tabs/final-fantasy-vii?page=2"


# --- robots.txt -------------------------------------------------------------------------------------------------------


def _star_group() -> tuple[list[str], list[str]]:
    disallow, delay, agent = [], [], None
    for line in fixture("robots.txt").splitlines():
        field, _, value = line.partition(":")
        name = field.strip().lower()
        if name == "user-agent":
            agent = value.strip()
        elif agent == "*" and name == "disallow":
            disallow.append(value.strip())
        elif agent == "*" and name == "crawl-delay":
            delay.append(value.strip())
    return disallow, delay


def test_robots_rules_are_the_user_agent_star_group_of_the_live_file():
    from caracole.http import ROBOTS_CRAWL_DELAY, ROBOTS_DISALLOW

    lines, delay = _star_group()
    assert list(ROBOTS_DISALLOW["gametabs.net"]) == lines == list(ROBOTS_DISALLOW["www.gametabs.net"])
    assert delay == ["5"]
    assert ROBOTS_CRAWL_DELAY["gametabs.net"] == ROBOTS_CRAWL_DELAY["www.gametabs.net"] == 5.0
    assert crawl_delay(f"{BASE}/tabs/actraiser/fillmore") == 5.0


def test_robots_closes_the_api_the_filters_the_logins_and_every_download():
    for path in ("/api/tabs/484", "/tabs?composers=12", "/tabs?instruments=1", "/preparing-tab-file-download",
                 "/preparing-tab-file-download?file=1", "/settings", "/my-tabs", "/admin/", "/login?next=/",
                 "/index.php", "/error.log", "/composer/12"):
        assert robots_disallows(f"{BASE}{path}") is not None, path
    # "$" ends a rule: a path that only holds ".php" or ".log" is open.
    for path in ("/robots.txt", "/sitemap.xml", "/sitemap_1.xml.gz", "/tabs/actraiser", "/tabs/actraiser/fillmore",
                 "/tabs/final-fantasy-vii?page=2", "/games?starts_with=a", "/tabs/php-games/a.php-tune",
                 "/tabs/logs/a.log-song"):
        assert robots_disallows(f"{BASE}{path}") is None, path


# --- a tab page -------------------------------------------------------------------------------------------------------


def test_a_tab_page_gives_its_tab_and_what_its_data_says_of_it():
    tab = parse_tab_page(fixture("tab_actraiser_fillmore.html"), f"{BASE}/tabs/actraiser/fillmore")
    assert isinstance(tab, GameTab)
    assert (tab.tab_id, tab.title, tab.game, tab.game_slug, tab.slug) == (
        484, "Fillmore", "Actraiser", "actraiser", "fillmore")
    assert (tab.composers, tab.instruments, tab.styles, tab.tuning) == (
        ("Yuzo Koshiro",), ("Guitar",), ("Transcription",), "EADGBE")
    assert (tab.tabber, tab.views, tab.rating, tab.ratings) == ("BacardiBreezer", 16409, 5.0, 2)
    assert tab.body.startswith("Fillmore\nActraiser\nComposer: Yuzo Koshiro\nTabbed by: Bacardibreezer\n12/16/10\n")
    assert tab.body.endswith("|\n") and "e|---" in tab.body and "<span" not in tab.body
    assert tab.raw() == {"id": 484, "title": "Fillmore", "game": "Actraiser", "composers": ["Yuzo Koshiro"],
                         "instruments": ["Guitar"], "styles": ["Transcription"], "tuning": "EADGBE",
                         "tabber": "BacardiBreezer", "views": 16409, "rating": 5.0, "ratings": 2,
                         "created": "2010-12-19T00:00:00Z"}


def test_a_second_tab_of_a_title_is_its_own_page_with_its_own_data():
    tab = parse_tab_page(fixture("tab_hollow-knight_resting-grounds-2.html"))
    assert (tab.tab_id, tab.title, tab.game, tab.slug, tab.tabber, tab.tuning) == (
        9026, "Resting Grounds", "Hollow Knight", "resting-grounds-2", "Emi", "D#ADGBE")
    assert tab.styles == ("Arrangement", "Fingerstyle") and tab.composers == ("Christopher Larkin",)
    assert tab.body.startswith("Title: Resting Grounds\nSubTitle: Hollow Knight\n")


def test_a_tab_page_without_its_data_is_read_from_its_microdata():
    page = fixture("tab_actraiser_fillmore.html")
    start = page.index('data-tab="')
    page = page[:start] + page[page.index('"', start + len('data-tab="')) + 1:]
    tab = parse_tab_page(page)
    assert (tab.title, tab.game, tab.composers, tab.instruments, tab.tab_id) == (
        "Fillmore", "Actraiser", ("Yuzo Koshiro",), ("Guitar",), None)


def test_a_tab_page_with_no_tab_or_no_title_wont_parse():
    with pytest.raises(GameTabsParseError):
        parse_tab_page("<html><body><h1>Not found</h1></body></html>")
    page = tab_page("Actraiser", "Fillmore", body="")
    with pytest.raises(GameTabsParseError):
        parse_tab_page(page)


def test_a_made_tab_page_reads_as_made():
    tab = parse_tab_page(tab_page("Hollow Knight", "Dirtmouth", composers=("Christopher Larkin",),
                                  instruments=("Guitar", "Bass"), views=1234, body="E|--3--|\n"))
    assert (tab.title, tab.game, tab.game_slug, tab.slug, tab.composers, tab.instruments, tab.views, tab.body) == (
        "Dirtmouth", "Hollow Knight", "hollow-knight", "dirtmouth", ("Christopher Larkin",), ("Guitar", "Bass"), 1234,
        "E|--3--|\n")


# --- a game page ------------------------------------------------------------------------------------------------------


def test_a_game_page_lists_each_tab_with_its_composer_and_instrument():
    page = parse_game_page(fixture("game_actraiser.html"))
    assert isinstance(page, GamePage)
    assert (page.name, page.tabs) == ("Actraiser", 5)
    assert [(t.path, t.title) for t in page.listed] == [
        ("tabs/actraiser/all-over-the-world", "All Over the World"), ("tabs/actraiser/birth-of-people", "Birth of People"),
        ("tabs/actraiser/birth-of-the-people", "Birth of the People"), ("tabs/actraiser/fillmore", "Fillmore"),
        ("tabs/actraiser/sacrifices", "Sacrifices")]
    fillmore = page.listed[3]
    assert (fillmore.composers, fillmore.instruments, fillmore.styles, fillmore.platform, fillmore.tabber) == (
        ("Yuzo Koshiro",), ("Guitar",), ("Transcription",), "Super Nintendo", "BacardiBreezer")
    assert (fillmore.views, fillmore.rating) == (16400, 5.0)


def test_a_card_may_name_no_composer_and_no_style():
    page = parse_game_page(fixture("game_hollow-knight.html"))
    assert page.name == "Hollow Knight" and page.tabs == 6
    titles = {t.path.rsplit("/", 1)[1]: t for t in page.listed}
    assert titles["resting-grounds-2"].title == titles["resting-grounds"].title == "Resting Grounds"
    title_theme = titles["title-theme-8"]
    assert (title_theme.title, title_theme.composers, title_theme.styles, title_theme.instruments) == (
        "Title Theme", (), (), ("Guitar",))
    assert titles["hollow-knight-main-menu"].title == "Hollow Knight (Main Menu)"
    assert titles["the-white-lady"].styles == ("Arrangement", "Fingerstyle", "Natural harmonics")


def test_a_game_of_many_tabs_lists_fifty_a_page_and_its_instruments_by_the_sites_own_names():
    page = parse_game_page(fixture("game_final-fantasy-vii.html"))
    assert (page.name, page.tabs, page.pages) == ("Final Fantasy VII", 240, 5)
    by_title = {t.title: t for t in page.listed}
    assert "Aeris' Theme" in by_title  # its apostrophe, as the page escapes it
    assert {t.instruments for t in page.listed} >= {("Guitar", "Bass"), ("Ukulele",), ("Mandolin",), ("Bass",)}


def test_a_game_page_that_says_it_has_tabs_and_lists_none_wont_parse():
    with pytest.raises(GameTabsParseError):
        parse_game_page(game_page("Actraiser", [], count=5))
    with pytest.raises(GameTabsParseError):
        parse_game_page("<html><body><p>Tabs: 3</p></body></html>")
    assert parse_game_page(game_page("Nothing Yet", [])).listed == ()


def test_a_made_game_page_reads_as_made():
    page = parse_game_page(game_page("Hollow Knight", [("dirtmouth", "Dirtmouth", "Christopher Larkin", "Guitar, Bass",
                                                          "3.4k"), ("hornet", "Hornet", "")]))
    assert [(t.path, t.title, t.composers, t.instruments, t.views) for t in page.listed] == [
        ("tabs/hollow-knight/dirtmouth", "Dirtmouth", ("Christopher Larkin",), ("Guitar", "Bass"), 3400),
        ("tabs/hollow-knight/hornet", "Hornet", (), ("Guitar",), 1200)]
