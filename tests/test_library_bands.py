"""An artist's band on index.html (library.css, library.js ``artistGroup``), in Chromium: 34 px, their name in their
colour, your count small and muted on its right."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html import unescape

import pytest
from helpers.browser import in_chromium
from helpers.targets import TOKEN_PROBE
from test_library_page import dump_dom, with_script

from caracole.library_page import WebControls, build_library_page, write_library_page
from caracole.overrides import Overrides

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
