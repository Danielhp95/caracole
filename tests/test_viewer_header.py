"""The title block's ‹ (viewer.css `.back`): a back arrow alone, its words in aria-label and title, a thumb's target."""

from __future__ import annotations

from caracole.viewer import build_viewer
from caracole.viewer.harptab_page import build_harmonica_viewer

from helpers.browser import in_chromium
from helpers.viewer_pages import viewer as open_viewer, written


def test_the_title_block_opens_with_a_back_arrow_alone():
    html = build_viewer("{title: T}\n[Am]la la\n")
    assert '<a class="back" href="../../index.html" aria-label="Library" title="Library">‹</a>' in html
    harp = build_harmonica_viewer("4 5 6\n", title="T", tab_file="harmonica-1.txt", back="sheet.html")
    assert '<a class="back" href="sheet.html" data-sheet aria-label="Chord sheet" title="Chord sheet">‹</a>' in harp
    assert ">‹ Library</a>" not in html and ">‹ Chord sheet</a>" not in harp


@in_chromium
def test_the_back_arrow_is_48_px(tmp_path):
    url = written(tmp_path, "{title: T}\n[Am]la la\n")
    for width in (320, 390):
        with open_viewer(tmp_path, url, width=width) as b:
            box = b.js("(() => { const r = document.querySelector('.head .back').getBoundingClientRect();"
                       " return [r.width, r.height, r.left]; })()")
            assert box[0] == 48 and box[1] == 48 and box[2] >= 0, (width, box)
