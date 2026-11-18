"""An artist's band on index.html (library.css, library.js ``artistGroup``), in Chromium: 34 px, their name in their
colour, your count small and muted on its right; an artist of one song folded into its line, their name an overline
over its title (a search's results fold so too: test_web_page_search.py)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html import unescape

import pytest
from helpers.browser import in_chromium
from helpers.targets import FOLDED_LINE, TOKEN_PROBE, noted, noting
from test_library_page import dump_dom, put, with_script

from caracole.library_page import WebControls, build_library_page, write_library_page
from caracole.overrides import Overrides
from caracole.songs import update_song

from conftest import add_song

NOW = datetime(2026, 10, 18, 3, 41, tzinfo=UTC)

BAND = """(() => { %s
  const s = document.querySelector('#list section.artist[data-artist="oasis"]');
  const h = s.querySelector('.artist-title'), name = h.querySelector('.artist-name'), c = h.querySelector('.artist-counts');
  const css = getComputedStyle, box = (n) => n.getBoundingClientRect();
  const tokens = Object.fromEntries(["--artist", "--muted", "--text", "--accent"].map((t) => [t, token(t)]));
  document.body.setAttribute("data-band", JSON.stringify({ height: box(h).height, size: parseFloat(css(name).fontSize),
    weight: Number(css(name).fontWeight), colour: css(name).color,
    counts: [c.querySelector(':scope > span:not(.visually-hidden)').textContent, c.textContent, css(c).color,
      box(h).right - box(c).right], target: box(h.querySelector('button.artist')).height, tokens })); })();""" % TOKEN_PROBE


@in_chromium
@pytest.mark.parametrize("size,touch", [("390,844", True), ("1280,900", False)])
@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_an_artist_with_two_songs_has_a_34px_band_naming_them_in_their_colour_and_counting_yours(
        conn, cfg, tmp_path, size, touch, scheme):
    add_song(conn, "Oasis", "Wonderwall")
    add_song(conn, "Oasis", "Live Forever")
    add_song(conn, "Eagles", "Desperado")
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok"))
    path = write_library_page(cfg.library_dir, with_script(html, BAND))
    dom = dump_dom(path, tmp_path, size=size, touch=touch, media={"prefers-color-scheme": scheme})
    band = json.loads(unescape(re.search(r'<body[^>]*data-band="([^"]*)"', dom).group(1)))
    assert 33.5 <= band["height"] <= 34.5 and 14 <= band["size"] <= 15 and band["weight"] >= 700, band
    assert band["colour"] == band["tokens"]["--artist"]
    assert band["tokens"]["--artist"] not in (band["tokens"]["--text"], band["tokens"]["--accent"])
    # what shows is the visible count span's textContent (innerText would hold the hidden " · yours " too)
    assert band["counts"][:2] == ["2", " · yours 2"] and band["counts"][2] == band["tokens"]["--muted"], band
    assert band["counts"][3] <= 16  # on the band's right
    if touch:
        assert band["target"] >= 24


def with_sheet(conn, cfg, artist, title):
    """A song of yours with a sheet: its line has a button to play from."""
    song = add_song(conn, artist, title)
    put(cfg, song, "sheet.html", "sheet.pdf")
    update_song(conn, song.id, status="found")
    return song


def drawn(conn, cfg, tmp_path, script, size, touch=False, fragment=""):
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok"))
    path = write_library_page(cfg.library_dir, with_script(html, noting("data-noted", script)))
    return noted(dump_dom(path, tmp_path, fragment, size=size, touch=touch), "data-noted")


# Eagles' one song folded into its line: their band's heading, a screen reader's alone, and the line's overline, their
# name over its title; Oasis's two songs under their band, each line naming no artist; the page's outline as before.
FOLDED = """(() => { %s
  const s = document.querySelector('#list section.artist[data-artist="eagles"]');
  const line = s.querySelector('article.line'), by = line.querySelector('.line-by'), h3 = line.querySelector('h3');
  const css = getComputedStyle, box = (n) => n.getBoundingClientRect();
  return { folded: s.classList.contains('folded'), head: [box(s.querySelector('.artist-title')).width,
    s.querySelector('.artist-title').textContent], by: [by.checkVisibility(), by.textContent, css(by).textTransform,
    parseFloat(css(by).fontSize), Number(css(by).fontWeight), parseFloat(css(by).letterSpacing), css(by).color,
    box(by).bottom, box(by).height], h3top: box(h3).top, line: box(line).height,
    tokens: { "--artist": token("--artist") },
    oasis: [document.querySelector('#list section.artist[data-artist="oasis"]').classList.contains('folded'),
    [...document.querySelectorAll('#list section[data-artist="oasis"] .line-by')].some((n) => n.checkVisibility())],
    outline: [document.querySelectorAll('#list h2').length, document.querySelectorAll('#list h3').length] }; })()""" % (
    TOKEN_PROBE)


@in_chromium
@pytest.mark.parametrize("size,touch", [("390,844", True), ("320,640", True), ("1280,900", False)])
def test_a_one_song_artist_folds_into_its_line_under_their_name_as_an_overline(conn, cfg, tmp_path, size, touch):
    add_song(conn, "Oasis", "Wonderwall")
    add_song(conn, "Oasis", "Live Forever")
    with_sheet(conn, cfg, "Eagles", "Desperado")
    f = drawn(conn, cfg, tmp_path, FOLDED, size, touch)
    tokens = f["tokens"]
    assert f["folded"] and f["head"][0] <= 1 and f["head"][1] == "Eagles · yours 1", f  # a screen reader's alone
    shown, text, case, size_, weight, spacing, colour, bottom, height = f["by"]
    assert shown and text == "Eagles" and case == "uppercase" and 11 <= size_ <= 12 and weight >= 700, f
    assert spacing > 0 and colour == tokens["--artist"], f
    if touch:
        assert bottom <= f["h3top"] + 1 and FOLDED_LINE[0] <= f["line"] <= FOLDED_LINE[1] and height >= 24, f  # above the title; 64 px
    assert f["oasis"] == [False, False] and f["outline"] == [2, 3], f  # a band; an h2 an artist, an h3 a song


# Every line of a list sorted by title or by when they came: its overline and its title's top, its box, its h3's right.
FLAT = """(() => {
  const box = (n) => n.getBoundingClientRect();
  return [...document.querySelectorAll('#list section.flat article.line')].map((line) => {
    const by = line.querySelector('.line-by'), h3 = line.querySelector('h3');
    return [by.checkVisibility(), by.textContent, getComputedStyle(by).textTransform, box(by).bottom, box(h3).top,
      box(line).height, box(by).left, box(h3).right]; }); })()"""


@in_chromium
@pytest.mark.parametrize("sort", ["title", "recent"])
@pytest.mark.parametrize("size,touch", [("390,844", True), ("1280,900", False)])
def test_a_sorted_list_folds_every_line_its_artist_above_its_title(conn, cfg, tmp_path, sort, size, touch):
    for artist, title in (("Oasis", "Wonderwall"), ("Oasis", "Live Forever"), ("Eagles", "Desperado"),
                          ("宋冬野", "安和桥")):
        with_sheet(conn, cfg, artist, title)
    lines = drawn(conn, cfg, tmp_path, FLAT, size, touch, "#sort=" + sort)
    assert len(lines) == 4, lines
    for shown, text, case, by_bottom, h3_top, height, by_left, h3_right in lines:
        assert shown and text and case == "uppercase", lines  # at 1280 too: the overline's type is not media-limited
        if touch:  # over the title, the line about 64 px
            assert by_bottom <= h3_top + 1 and FOLDED_LINE[0] <= height <= FOLDED_LINE[1], lines
        else:  # in its own column
            assert by_left > h3_right, lines


# Each artist's group: whether it folded, and how tall its band shows.
SECTIONS = """[...document.querySelectorAll('#list section.artist')].map((s) => [s.dataset.artist,
  s.classList.contains('folded'), s.querySelector('.artist-title').getBoundingClientRect().height,
  s.querySelectorAll('article.line').length])"""


@in_chromium
def test_a_library_of_one_song_artists_folds_every_group_and_an_artist_of_many_is_one_band(conn, cfg, tmp_path):
    for artist, title in (("2Pac", "Changes"), ("Eagles", "Desperado"), ("Oasis", "Wonderwall"),
                          ("Radiohead", "Creep"), ("Wilco", "Jesus, Etc.")):
        with_sheet(conn, cfg, artist, title)
    groups = drawn(conn, cfg, tmp_path, SECTIONS, "390,844", touch=True)
    assert [g[0] for g in groups] == ["2pac", "eagles", "oasis", "radiohead", "wilco"], groups
    assert all(folded and band <= 1 and lines == 1 for _, folded, band, lines in groups), groups  # no band shows
    conn.execute("DELETE FROM songs")
    for n in range(12):
        with_sheet(conn, cfg, "Soda Stereo", f"Song {n:02d}")
    groups = drawn(conn, cfg, tmp_path, SECTIONS, "390,844", touch=True)
    assert len(groups) == 1 and not groups[0][1] and 33.5 <= groups[0][2] <= 34.5 and groups[0][3] == 12, groups


# Each band's height and its name's cut; each line's overline, title and buttons, where they are; the page's width.
LONG = """(() => {
  const box = (n) => n.getBoundingClientRect(), css = getComputedStyle;
  const bands = [...document.querySelectorAll('#list section.artist:not(.folded)')].map((s) => {
    const name = s.querySelector('.artist-title .artist-name');
    return { artist: s.dataset.artist, height: box(s.querySelector('.artist-title')).height,
      cut: name.scrollWidth > name.clientWidth, overflow: css(name).textOverflow, wrap: css(name).whiteSpace }; });
  const lines = [...document.querySelectorAll('#list article.line')].map((l) => {
    const plays = l.querySelector('.line-plays'), by = l.querySelector('.line-by');
    const name = by.querySelector('.artist-name');
    return { title: l.querySelector('h3').textContent, folded: Boolean(l.closest('section.folded')),
      plays: box(plays).left, h3: box(l.querySelector('h3')).right, line: box(l).height,
      by: by.checkVisibility()
        ? { right: box(by).right, height: box(by).height, cut: name.scrollWidth > name.clientWidth } : null }; });
  return { bands, lines, page: [document.documentElement.scrollWidth, innerWidth] };
})()"""
RHCP = "The Red Hot Chili Peppers and the Extremely Long Named Friends"
CADILLACS = "Los Fabulosos Cadillacs y Los Auténticos Decadentes de la Ciudad de Buenos Aires"


@in_chromium
@pytest.mark.parametrize("width", [320, 390])
def test_long_and_chinese_names_are_cut_short_never_wrapped_into_the_buttons(conn, cfg, tmp_path, width):
    for artist, title in (("周杰伦", "晴天"), ("周杰伦", "稻香"), ("宋冬野", "斑马，斑马"), (RHCP, "Under the Bridge"),
                          (CADILLACS, "Matador"), (CADILLACS, "Vasos Vacíos")):
        with_sheet(conn, cfg, artist, title)
    laid = drawn(conn, cfg, tmp_path, LONG, f"{width},800", touch=True)
    assert laid["page"][0] <= laid["page"][1], laid["page"]  # nothing sideways
    assert len(laid["bands"]) == 2 and all(33.5 <= b["height"] <= 34.5 for b in laid["bands"]), laid["bands"]
    long = next(b for b in laid["bands"] if b["artist"].startswith("los-fabulosos"))
    assert long["cut"] and long["overflow"] == "ellipsis" and long["wrap"] == "nowrap", long
    lines = {line["title"]: line for line in laid["lines"]}
    assert sorted(t for t, line in lines.items() if line["folded"]) == ["Under the Bridge", "斑马，斑马"], lines
    for title, line in lines.items():
        assert line["h3"] <= line["plays"] + 0.5, (title, line)  # the title cut short before its button
        if line["folded"]:  # the overline, one line, cut short before the button too
            by = line["by"]
            assert by and by["height"] <= 26 and by["right"] <= line["plays"] + 0.5, (title, line)
            assert FOLDED_LINE[0] <= line["line"] <= FOLDED_LINE[1], (title, line)
        else:
            assert line["by"] is None, (title, line)
    assert lines["Under the Bridge"]["by"]["cut"], lines["Under the Bridge"]



# The laptop's line, one row: the title, its artist, the play tiles, the key, the chevron (the owner's ask, 2026-11-18).
ORDER = """(() => {
  const box = (n) => n && n.getBoundingClientRect();
  return [...document.querySelectorAll('#list article.line')].map((line) => {
    const h3 = line.querySelector('h3'), by = line.querySelector('.line-by'), plays = line.querySelector('.line-plays > .play'),
      key = line.querySelector('.line-key'), more = line.querySelector('.line-more'), box0 = box(line), p = line.querySelector('.pick');
    const l = (n) => (n && n.checkVisibility() ? box(n).left : null);
    return { title: h3.textContent, h3: [box(h3).right, box(h3).top, box(h3).bottom], by: by && [box(by).left, box(by).right],
      plays: l(plays), key: l(key), more: l(more), pick: l(p), line: [box0.top, box0.bottom, box0.right],
      band: !by || !by.checkVisibility(), cut: h3.scrollWidth > h3.clientWidth }; }); })()"""
LONG_TITLE = "A very long song title that goes on and on and on past any reasonable width of a laptop's column. " * 3
LONG_TITLE = LONG_TITLE.strip()


def _on_one_row(lines, selecting=False):
    for line in lines:
        assert line["by"] and line["plays"] is not None, line
        left, right = line["by"]
        assert line["h3"][0] <= left + 0.5 and left < line["plays"], line  # title, artist, tiles
        assert right <= line["plays"] + 0.5, line  # the name never under a tile
        end = line["key"] if selecting else line["more"]  # while selecting the chevron is gone
        assert end is None or line["plays"] < end, line
        assert selecting or line["key"] is None or line["key"] < line["more"], line
        assert line["line"][0] <= line["h3"][1] and line["h3"][2] <= line["line"][1], line  # one row
        assert (line["key"] if selecting else line["more"]) is None or (
            (line["key"] if selecting else line["more"]) <= line["line"][2] + 0.5), line  # nothing pushed off it
        if selecting:
            assert line["pick"] is not None and line["pick"] < line["h3"][0], line


@in_chromium
@pytest.mark.parametrize("size", ["1280,800", "1024,900"])
@pytest.mark.parametrize("selecting", [False, True])
def test_on_a_laptop_a_line_reads_title_artist_tiles_key_chevron(conn, cfg, tmp_path, size, selecting):
    for artist, title in (("Oasis", "Wonderwall"), ("Eagles", "Desperado"), ("Queen", LONG_TITLE)):
        with_sheet(conn, cfg, artist, title)
    if selecting:  # Select on, as + New songbook turns it on: the lines get their boxes a tick later
        script = ("document.dispatchEvent(new CustomEvent('caracole:new-songbook'));\n"
                  "setTimeout(() => document.body.setAttribute('data-noted', JSON.stringify(%s)), 200);\n" % ORDER)
        html = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok"))
        path = write_library_page(cfg.library_dir, with_script(html, script))
        lines = noted(dump_dom(path, tmp_path, "#sort=title", size=size), "data-noted")
    else:
        lines = drawn(conn, cfg, tmp_path, ORDER, size, fragment="#sort=title")
    assert len(lines) == 3, lines
    _on_one_row(lines, selecting)
    assert next(line for line in lines if line["title"] == LONG_TITLE)["cut"], lines  # the title gives way, not the rest


@in_chromium
def test_a_folded_one_song_artist_reads_title_artist_tiles_and_a_band_keeps_title_then_tiles(conn, cfg, tmp_path):
    with_sheet(conn, cfg, "Eagles", "Desperado")
    with_sheet(conn, cfg, "Oasis", "Wonderwall")
    with_sheet(conn, cfg, "Oasis", "Live Forever")
    lines = drawn(conn, cfg, tmp_path, ORDER, "1280,800")
    folded = [line for line in lines if line["title"] == "Desperado"]
    _on_one_row(folded)
    for line in lines:
        if line["title"] != "Desperado":  # in a band: no artist on the line, the tiles right after the title
            assert line["band"] and line["h3"][0] <= line["plays"], line
