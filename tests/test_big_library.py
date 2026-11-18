"""tests/helpers/big_library.py: a library of many songs built with no request, and its measurement on a phone
(stage 1e of the library page's redesign)."""

from __future__ import annotations

import json
import re
from collections import Counter

import pytest
from helpers.browser import in_chromium

pytestmark = pytest.mark.slow  # a library of hundreds of songs, a page of them in a browser

DATA = re.compile(r'<script type="application/json" id="songs">(.*?)</script>', re.S)


def songs_of(page):
    return json.loads(DATA.search(page.read_text(encoding="utf-8")).group(1))["songs"]


def test_the_big_library_has_every_shape(tmp_path):
    from helpers.big_library import build

    page = build(tmp_path / "lib", 400)
    songs = songs_of(page)
    assert len(songs) == 400
    by_artist = Counter(s["artist"] for s in songs)
    ones = sum(1 for n in by_artist.values() if n == 1)
    assert 0.50 <= ones / len(by_artist) <= 0.60
    assert max(by_artist.values()) >= 30
    assert all(2 <= n <= 15 for n in by_artist.values() if n > 1 and n != max(by_artist.values()))
    assert any(re.search(r"[一-鿿]", s["title"]) for s in songs)
    assert any(len(s["title"]) >= 100 for s in songs)
    assert all(s["key"] for s in songs)
    named = Counter(f["name"] for s in songs for f in s["files"])
    assert {named["sheet.txt"], named["sheet.html"], named["sheet.pdf"]} == {400}
    assert named["guitar-1.gp"] == 80  # every fifth
    assert sum("harmonica" in s["instruments"] for s in songs) == 45  # every ninth


def test_the_big_library_is_the_same_every_time(tmp_path):
    from helpers.big_library import build

    first = build(tmp_path / "a", 60).read_bytes()
    second = build(tmp_path / "b", 60).read_bytes()
    assert first == second


@in_chromium
def test_measure_answers_every_number(tmp_path):
    from helpers.big_library import build, measure

    done = measure(build(tmp_path / "lib", 200))
    for key in ("drawn_ms", "fcp_ms", "ScriptDuration", "LayoutDuration", "RecalcStyleDuration", "LayoutCount",
                "Nodes", "JSHeapUsedSize", "type_ms", "open_ms"):
        assert done[key] >= 0, key
    scroll = done["scroll"]
    for key in ("frames", "p50_ms", "p95_ms", "max_ms", "over_50ms", "long_tasks"):
        assert scroll[key] >= 0, key
    assert scroll["frames"] > 0
