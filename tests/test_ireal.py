"""ireal.py: the forum's sitemaps as index rows, a chart link decoded, its chart as a sheet, a thread page and the
jazz forum's page read, from what the site answered on 18 November 2026."""

from __future__ import annotations

import pytest
from helpers.ireal_site import BASE, encode, fixture, link, thread_page

from caracole.http import robots_disallows
from caracole.ireal import (
    JAZZ_1460,
    IndexRow,
    MAGIC,
    IRealParseError,
    Tune,
    begins_with,
    chord_name,
    composer_name,
    composer_words,
    page_url,
    parse_forum_page,
    parse_link,
    parse_page_url,
    parse_thread_page,
    sitemap_child,
    title_key,
    unscramble,
)
from caracole.ug.sitemap import iter_locs
from caracole.viewer.theory import parse_chord

# --- the sitemaps -----------------------------------------------------------------------------------------------------


def test_the_index_reads_each_numbered_sitemap():
    children = list(iter_locs(fixture("sitemap.xml").encode()))
    assert [sitemap_child(url) for url in children] == [f"sitemap-{n}" for n in range(1, 7)]
    assert sitemap_child(f"{BASE}/sitemap.php") is None
    assert sitemap_child("https://example.com/sitemap-1.xml") is None


def test_a_sitemap_gives_its_threads_and_nothing_else():
    rows = [r for r in map(parse_page_url, iter_locs(fixture("sitemap-1.xml").encode())) if r is not None]
    # The home page, the forums, a tag and two members: no rows (members/ is closed by robots.txt anyway).
    assert len(rows) == 17
    assert parse_page_url(f"{BASE}/threads/groove-merchant-thad-jones.9518/") == IndexRow(
        "threads/groove-merchant-thad-jones.9518/", 9518, "groove-merchant-thad-jones", "groove-merchant-thad-jones")
    for url in (f"{BASE}/", f"{BASE}/forums/jazz.6/", f"{BASE}/tags/terms/", f"{BASE}/members/orrpa.8006/",
                f"{BASE}/threads/groove-merchant-thad-jones.9518/page-2", "https://example.com/threads/a.1/"):
        assert parse_page_url(url) is None, url


def test_a_slug_is_keyed_as_a_title_is_an_underscore_a_hyphen_a_leading_article_dropped():
    assert parse_page_url(f"{BASE}/threads/truman_clark-charts.35241/").key == "truman-clark-charts"
    the = parse_page_url(f"{BASE}/threads/the-girl-from-ipanema-garota-de-ipanema-jobim-de-moraes-gimbel.8724/")
    assert begins_with(the.key, title_key("Girl From Ipanema, The"))
    a = parse_page_url(f"{BASE}/threads/a-night-in-tunisia-dizzy-gillepsie.2950/")
    assert begins_with(a.key, title_key("Night in Tunisia")) and begins_with(a.key, title_key("A Night In Tunisia"))


def test_a_title_meets_the_slugs_that_begin_with_its_words_alone():
    misty = title_key("Misty")
    assert begins_with("misty-erroll-garner", misty) and begins_with("misty", misty)
    assert begins_with("misty-roses-tim-hardin", misty)  # a title the slug can't tell from a composer: read to know
    assert not begins_with("mistyc-dreams", misty) and not begins_with("on-a-misty-night-tadd-dameron", misty)
    assert not begins_with("groove-merchant", "") and not begins_with("", misty)


def test_a_title_key_folds_the_trailing_article_irealpro_writes():
    assert title_key("Girl From Ipanema, The") == title_key("The Girl from Ipanema") == "girl-from-ipanema"
    assert title_key("Night In Tunisia, A") == title_key("A Night in Tunisia") == title_key("Night in Tunisia")
    assert title_key("Autumn Leaves (Remastered 2008)") == "autumn-leaves"  # a streaming service's suffix goes too
    assert title_key("A") == "a"


def test_a_page_url_is_its_path_on_the_site():
    assert page_url(JAZZ_1460) == f"{BASE}/threads/jazz-1460-standards.12753/"


# --- robots.txt -------------------------------------------------------------------------------------------------------


def test_robots_rules_are_the_user_agent_star_group_of_the_live_file():
    from caracole.http import ROBOTS_DISALLOW

    lines = [line.partition(":")[2].strip() for line in fixture("robots.txt").splitlines()
             if line.lower().startswith("disallow:")]
    assert list(ROBOTS_DISALLOW["forums.irealpro.com"]) == lines


def test_robots_closes_the_search_the_logins_and_the_members():
    for path in ("/search/", "/search/123/?q=misty", "/login/", "/register/", "/members/orrpa.8006/",
                 "/whats-new/", "/misc/style", "/find-new/", "/account/"):
        assert robots_disallows(f"{BASE}{path}") is not None, path
    for path in ("/robots.txt", "/sitemap.php", "/sitemap-1.xml", "/forums/jazz.6/",
                 "/threads/groove-merchant-thad-jones.9518/"):
        assert robots_disallows(f"{BASE}{path}") is None, path


# --- a chart link -----------------------------------------------------------------------------------------------------


def test_the_scramble_is_the_documented_one_and_its_own_inverse():
    text = "".join(chr(ord("a") + n % 26) for n in range(130))
    once = unscramble(text)
    assert once != text and unscramble(once) == text
    # Blocks of 50 are swapped end for end in two runs (0-4 and 10-23); a last block, or one with fewer than two
    # characters after it, is left as it is.
    assert once[:5] == text[45:50][::-1] and once[5:10] == text[5:10] and once[10:24] == text[26:40][::-1]
    assert once[100:] == text[100:] and unscramble(text[:51]) == text[:51]


def test_a_playlist_link_gives_its_tunes_and_its_name():
    page = parse_thread_page(fixture("thread_jazz-1460-standards.12753.html"))
    playlist = page.posts[0].tunes
    assert [t.title for t in playlist] == [
        "500 Miles High", "A Night In Tunisia", "A Wonderful Day Like Today", "All The Things You Are",
        "Autumn Leaves", "Blue Bossa", "Girl From Ipanema, The", "Misty", "Smile", "Take The A Train"]
    leaves = playlist[4]
    assert (leaves.composer, leaves.style, leaves.key, leaves.playlist, leaves.scheme) == (
        "Kosma Joseph", "Medium Swing", "G-", "Jazz 1460", "irealb")
    assert leaves.music.startswith("1r34LbKcu7")  # as the link gave it, scrambled


def test_a_link_of_one_tune_and_an_old_unscrambled_one():
    page = parse_thread_page(fixture("thread_groove-merchant-jerome-richardson.14294.html"))
    old, new = page.posts[0].tunes[0], page.posts[1].tunes[0]
    assert (old.scheme, old.title, old.composer, old.style, old.key, old.playlist) == (
        "irealbook", "Groove Merchant", "Richardson Jerome", "Medium Swing", "C", "")
    assert old.music.startswith("|T44Bb7")  # irealbook:// is the music as it is
    assert (new.scheme, new.key, new.tempo) == ("irealb", "Ab", 140)


def test_a_link_that_holds_no_tune_gives_none():
    assert parse_link("irealb://") == ()
    assert parse_link("irealb://just%20a%20name") == ()
    assert parse_link("https://forums.irealpro.com/") == ()


# --- a chart as a sheet -----------------------------------------------------------------------------------------------


def test_a_chart_is_its_bars_four_a_line_each_section_ending_and_coda_on_a_line_of_its_own():
    page = parse_thread_page(fixture("thread_groove-merchant-thad-jones.9518.html"))
    first = page.posts[0].tunes[0]
    assert first.chart() == "\n".join([
        "Thad Jones · Medium Swing · 4/4",
        "",
        "| [ch]Bb7[/ch] | [ch]Eb7[/ch] | [ch]Bb7[/ch] | [ch]Bb7[/ch] [ch]F7[/ch] |",
        "[B]",
        "| [ch]Bb7[/ch] | [ch]Bb7[/ch] |",  # its "x" is the bar before it again
        "[Ending 1]",
        "| [ch]Gm7[/ch] [ch]Eb7[/ch] | [ch]Cm7[/ch] [ch]F7[/ch] | [ch]Bb[/ch] :|",
        "[Ending 2]",
        "| [ch]Gm7[/ch] [ch]Eb7[/ch] | [ch]Bb[/ch] N.C. ||",
    ]) + "\n"


def test_a_charts_marks_are_notes_under_their_line_and_its_coda_a_section():
    page = parse_thread_page(fixture("thread_groove-merchant-thad-jones.9518.html"))
    reposted = page.posts[-1].tunes[0]
    assert reposted.chart().splitlines()[2:] == [
        "| [ch]Bb7[/ch] | [ch]Eb7[/ch] | [ch]Bb7[/ch] | [ch]Bb7[/ch] [ch]F7[/ch] |",
        "| [ch]Bb[/ch] [ch]Bb/Ab[/ch] ||",
        "[B]",
        "|| [ch]Bb7[/ch] | [ch]Bb7[/ch] | [ch]Eb7[/ch] | [ch]Edim[/ch] |",
        "| [ch]Gm7[/ch] [ch]Eb7[/ch] | [ch]Bb[/ch] N.C. ||",
        "",
        "To Coda",
        "[Coda]",
        "|| [ch]Cm7[/ch] | [ch]F7[/ch] | [ch]Bb7[/ch] ||",
        "",
        "FINE",
    ]


def test_an_old_charts_empty_bar_and_its_comments():
    page = parse_thread_page(fixture("thread_groove-merchant-jerome-richardson.14294.html"))
    assert page.posts[0].tunes[0].chart().splitlines()[2:] == [
        "| [ch]Bb7[/ch] | [ch]Eb7[/ch] | [ch]Bb7[/ch] | [ch]Bb7[/ch] [ch]F7[/ch] |",
        "| [ch]Bb[/ch] [ch]Bb/Ab[/ch] ||",
        "|| [ch]Bb7[/ch] | [ch]Bb7[/ch] |",  # an empty bar holds on to the bar before it
        "[Ending 1]",
        "| [ch]Gm7[/ch] [ch]Eb7[/ch] | [ch]Cm7[/ch] [ch]F7[/ch] :|",
        "",
        "Solos over first time",
        "[Ending 2]",
        "|| [ch]Gm7[/ch] [ch]Eb7[/ch] | [ch]Bb7[/ch] ||",
    ]


def test_two_bars_repeated_are_the_two_bars_before_them_again():
    tune = next(t for t in parse_thread_page(fixture("thread_jazz-1460-standards.12753.html")).posts[0].tunes
                if t.title == "A Wonderful Day Like Today")
    assert tune.chart().splitlines()[2:] == [
        "[A]",
        "|: [ch]Ebmaj7[/ch] | [ch]Eb6[/ch] | [ch]Ebmaj7[/ch] | [ch]Eb6[/ch] |",
        "| [ch]Ebmaj7[/ch] ||",
    ]


def test_a_chart_in_another_time_says_so():
    tune = Tune("Waltz", "Someone", "Waltz", "F", "{*AT34F^7   |G-7   |T44C7   |F   Z ", scheme="irealbook")
    assert tune.chart().splitlines() == [
        "Someone · Waltz · 3/4", "", "[A]", "|: [ch]Fmaj7[/ch] | [ch]Gm7[/ch] | [ch]C7[/ch] | [ch]F[/ch] ||", "",
        "4/4"]
    assert tune.time == "3/4"


def test_a_chart_with_no_chords_wont_read():
    # No chord read is no chart: a parse error for the tune, never a song that has none.
    for music in ("[T44   |   Z", "n   |n   Z", "", "<only words>"):
        with pytest.raises(IRealParseError, match="no chord"):
            Tune("Silence", "", "", "C", music or " ", scheme="irealbook").chart()


@pytest.mark.parametrize("music", ["T4", "[T4", "C7 T4", "| T4", "T", "TT44", "N", "*", "<abc", "(C7", "W/C", "r|",
                                   "1XGS*|58TyUBbfl911x7/[)S9F)B#^Y{F9[cGUY{]DZ}xXG2 DCc)Y3T7"])
@pytest.mark.parametrize("scheme", ["irealb", "irealbook"])
def test_any_music_reads_or_is_a_parse_error_never_another_error(music, scheme):
    # "T4", a time of one digit at the music's end, once read past the end of the string (IndexError).
    tune = Tune("X", "Y Z", "Swing", "C", (MAGIC + music) if scheme == "irealb" else music, scheme)
    try:
        tune.chart()
        tune.time
    except IRealParseError:
        pass


def test_a_time_of_one_digit_is_no_time():
    tune = Tune("Cut", "", "", "C", MAGIC + "[T44C7 |F7   T4", scheme="irealb")
    assert tune.time == "4/4" and "[ch]F7[/ch]" in tune.chart()
    assert parse_link("irealb://t=c==s=k==" + MAGIC + "T4")[0].music == MAGIC + "T4"
    with pytest.raises(IRealParseError):
        parse_link("irealb://t=c==s=k==" + MAGIC + "T4")[0].chart()


def test_a_tune_cut_short_inside_a_block_is_garbled_a_parse_error():
    # A link cut short leaves its last block scrambled: what reads as no chord or mark is the sign.
    music = "[*AT44" + "C^7   |A-7   |D-7   |G7   |" * 6 + "C^7   Z "
    tune = Tune("Long", "Someone", "Swing", "C", encode(music))
    body = tune.music[len(MAGIC):]
    assert len(body) > 150 and "[ch]Cmaj7[/ch]" in tune.chart()  # the whole one reads
    cut = Tune("Long", "Someone", "Swing", "C", MAGIC + body[:145])
    with pytest.raises(IRealParseError, match="garbled"):
        cut.chart()


def test_an_empty_bar_holds_on_to_the_last_chord_before_it():
    def bars(music):
        return Tune("E", "", "", "C", music, scheme="irealbook").chart().splitlines()[2:]

    assert bars("[T44Bb7 F7 |   |C7   Z") == [
        "|| [ch]Bb7[/ch] [ch]F7[/ch] | [ch]F7[/ch] | [ch]C7[/ch] ||"]
    # After a section's opening bar line, it opens the section, on the chord held on.
    assert bars("[T44C7   |F7   ][*B   |G^7   Z") == [
        "|| [ch]C7[/ch] | [ch]F7[/ch] ||", "[B]", "|| [ch]F7[/ch] | [ch]Gmaj7[/ch] ||"]
    # Before a closing one, it ends the section; between a closing and an opening one is no bar.
    assert bars("{C7   |   } [D-7   |   Z") == [
        "|: [ch]C7[/ch] | [ch]C7[/ch] :|", "|| [ch]Dm7[/ch] | [ch]Dm7[/ch] ||"]
    # The bar after two bars repeated is that repeat's second, and a later empty bar is a bar again.
    assert bars("[T44C7   |F7   |r|   |G7   |   Z") == [
        "|| [ch]C7[/ch] | [ch]F7[/ch] | [ch]C7[/ch] | [ch]F7[/ch] |", "| [ch]G7[/ch] | [ch]G7[/ch] ||"]


def test_the_chart_is_a_sheet_the_viewer_draws_as_bars():
    from caracole.chordpro import to_chordpro
    from caracole.viewer.sheet import ChordRow, bars, parse_sheet

    tune = parse_thread_page(fixture("thread_groove-merchant-thad-jones.9518.html")).posts[0].tunes[0]
    sheet = parse_sheet(to_chordpro(tune.chart(), title=tune.title, artist="Thad Jones"))
    rows = [line for s in sheet.sections for line in s.lines if isinstance(line, ChordRow)]
    drawn = [bars(row) for row in rows]
    assert all(b is not None for b in drawn)
    assert [len(b.cells) for b in drawn] == [4, 2, 3, 2]
    assert [s.label for s in sheet.sections] == [None, "B", "Ending 1", "Ending 2"]
    # A mark after a line's last chord is its tail, never a beat of its bar (viewer/sheet.py ``bars``).
    assert drawn[-1].cells[-1] == ((sheet.chords.index("Bb"), 4),) and drawn[-1].tail == ("N.C.",)


@pytest.mark.parametrize("written, named", [
    ("C", "C"), ("C^7", "Cmaj7"), ("C^", "Cmaj7"), ("D-7", "Dm7"), ("D-", "Dm"), ("Bh7", "Bm7b5"), ("Bh", "Bm7b5"),
    ("Eo7", "Edim7"), ("Eo", "Edim"), ("C+", "Caug"), ("C-^7", "Cmmaj7"), ("F#h9", "F#m9b5"), ("Ab-6", "Abm6"),
    ("G7b9", "G7b9"), ("C69", "C69"), ("D7sus", "D7sus"), ("Bb^7#11", "Bbmaj7#11"), ("Eb-7b5", "Ebm7b5"),
    ("Bb/Ab", "Bb/Ab"), ("Eb-^9", "Ebmmaj9"), ("C13#11", "C13#11"), ("Co^7", "Cdimmaj7"), ("C-^", "Cmmaj7"),
    ("C*-^*", "Cmmaj7"), ("F*7b9*/A", "F7b9/A"),
])
def test_a_chord_is_named_as_sheets_name_it(written, named):
    assert chord_name(written) == named
    assert parse_chord(named) is not None


def test_every_quality_the_playlist_writes_is_a_chord_the_viewer_reads():
    # The 60 qualities the Jazz 1460 playlist wrote on 18 November 2026, its commonest first.
    for quality in ("7", "-7", "", "^7", "6", "7b9", "h7", "o7", "-", "-6", "7sus", "7#11", "7#9", "7#5", "7b13",
                    "^7#11", "13", "9", "-9", "-^7", "-11", "7alt", "69", "h", "^9", "7#9#5", "9sus", "7b5", "^",
                    "13b9", "o", "9#11", "-b6", "+", "7b9#5", "add9", "sus", "13sus", "^7#5", "13#11", "7b9sus",
                    "7b9b5", "9#5", "7b9b13", "-69", "7b9#11", "9b5", "7#9b5", "7#9#11", "-#5", "^9#11", "h9",
                    "7b9#9", "7susadd3", "2", "o^7", "^13", "13#9", "7b13sus", "-^9"):
        assert parse_chord(chord_name("C" + quality), strict=False) is not None, quality


def test_a_composer_irealpro_writes_last_name_first_is_named_first_name_first():
    assert composer_name("Jones Thad") == "Thad Jones"
    assert composer_name("Jobim Antonio-Carlos") == "Antonio-Carlos Jobim"
    assert composer_name("Herbie Hancock - Stevie Wonder") == "Herbie Hancock - Stevie Wonder"
    assert composer_name("Fain-Webster") == "Fain-Webster" and composer_name("") == ""
    assert composer_words("Jones Thad") == {"jones", "thad"}
    assert composer_words("Pat Metheny - Lyle Mays") == {"pat", "metheny", "lyle", "mays"}


# --- a thread page ----------------------------------------------------------------------------------------------------


def test_a_thread_page_gives_its_title_its_forum_and_each_posts_charts():
    page = parse_thread_page(fixture("thread_groove-merchant-thad-jones.9518.html"))
    assert (page.path, page.thread, page.title, page.forum) == (
        "threads/groove-merchant-thad-jones.9518/", 9518, "Groove Merchant - Thad Jones", "forums/jazz.6/")
    assert [(p.post, len(p.tunes)) for p in page.posts] == [(23346, 1), (23470, 0), (38106, 1)]
    assert [(post.post, place, tune.title) for post, place, tune in page.charts()] == [
        (23346, 1, "Groove Merchant"), (38106, 1, "Groove Merchant")]


def test_the_jazz_1460_thread_holds_its_playlist_and_more():
    page = parse_thread_page(fixture("thread_jazz-1460-standards.12753.html"))
    assert page.path == JAZZ_1460 and page.title == "Jazz 1460 Standards"
    assert [len(p.tunes) for p in page.posts] == [10, 0, 4]
    assert [t.playlist for t in page.posts[2].tunes] == ["Jazz New 50", "Jazz New 50", "", ""]


def test_a_chart_quoted_in_a_reply_is_the_posts_it_quotes_never_the_replys():
    quoted = thread_page("Misty - Erroll Garner", [
        (100, [link([("Misty", "Garner Erroll", "Ballad", "Eb", "[T44Eb^7   |Bb-7 Eb7 Z ")])]),
        (101, [], [link([("Misty", "Garner Erroll", "Ballad", "Eb", "[T44Eb^7   Z ")])]),
    ], path="threads/misty-erroll-garner.3861/")
    page = parse_thread_page(quoted)
    assert [(p.post, len(p.tunes)) for p in page.posts] == [(100, 1), (101, 0)]


def test_a_page_that_is_no_thread_wont_parse():
    with pytest.raises(IRealParseError):
        parse_thread_page("<html><body><h1>Oops! We ran into some problems.</h1></body></html>",
                          f"{BASE}/threads/misty-erroll-garner.3861/")
    page = fixture("thread_groove-merchant-thad-jones.9518.html")
    with pytest.raises(IRealParseError):  # its posts gone (a page cut short, say)
        parse_thread_page(page[:page.index("<article")])


def test_a_made_thread_page_reads_as_made():
    page = parse_thread_page(thread_page("Smile - Charlie Chaplin", [
        (7, [link([("Smile", "Chaplin Charles", "Ballad", "F", "[*AT44F^7   |D-7 Z ")], playlist="Mine")]),
    ], path="threads/smile-charlie-chaplin.77/"))
    assert (page.thread, page.title, page.posts[0].tunes[0].title, page.posts[0].tunes[0].playlist) == (
        77, "Smile - Charlie Chaplin", "Smile", "Mine")


# --- the jazz forum's page --------------------------------------------------------------------------------------------


def test_the_forums_page_gives_its_sticky_threads_the_playlists():
    page = parse_forum_page(fixture("forum_jazz.6.html"))
    assert page.sticky == (
        "threads/jazz-1460-standards.12753/", "threads/fusion-and-smooth-jazz.210/",
        "threads/jazz-practice-exercises.992/", "threads/gypsy-jazz.215/", "threads/contemporary-jazz.204/",
        "threads/dixieland-trad-playlists.10591/", "threads/jazz-1460-standards-individual-songs.27435/")
    assert page.threads[len(page.sticky):] == (
        "threads/blue-waltz-eddie-daniels.36010/", "threads/liebestraume-no-3-franz-liszt.36004/")


def test_a_page_that_is_no_forum_wont_parse():
    with pytest.raises(IRealParseError):
        parse_forum_page("<html><body><p>Maintenance</p></body></html>")
