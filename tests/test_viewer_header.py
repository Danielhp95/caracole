"""The song's header: the title block's ‹ (viewer.css `.back`), a back arrow alone, its words in aria-label and title, a
thumb's target; and the song's facts on three lines, Tuning, Capo and Key (page.py ``facts_html``, ``dl.facts``)."""

from __future__ import annotations

import json
import re

from caracole.viewer import build_viewer
from caracole.viewer.harptab_page import build_harmonica_viewer
from caracole.viewer.theory import Key

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


# --- the song's facts: Tuning, Capo and Key (page.py facts_html) ------------------------------------------------------

TUNED = ("{title: Tuned}\n{artist: The Placeholders}\n{key: Dm}\nTuning: Drop D\n\n"
         "{comment: Verse}\n[Dm]Words to sing\n{comment: Chorus}\n[F]More words\n")


def _data(html: str) -> dict:
    return json.loads(re.search(r'<script type="application/json" id="song">(.*?)</script>', html, re.S).group(1))


def test_the_facts_are_tuning_capo_and_key():
    from caracole.viewer.page import GUITAR_STRINGS, facts_html

    assert GUITAR_STRINGS == "E A D G B E"
    assert facts_html(Key(9, "aeolian"), "from the tab", 0, None, chords=True) == (
        '<dl class="facts" id="facts">\n<div class="fact" data-fact="tuning"><dt>Tuning</dt><dd>E A D G B E</dd></div>\n'
        '<div class="fact" data-fact="capo"><dt>Capo</dt><dd>none</dd></div>\n<div class="fact" data-fact="key"><dt>Key'
        '</dt><dd><b>Am</b> · <span class="from">from the tab</span></dd></div>\n</dl>\n')
    # where the key came from unknown: the key alone; a value escaped
    plain = facts_html(Key(9, "aeolian"), None, 0, 'Open <G> & "low"', chords=True)
    assert '<dd>Open &lt;G&gt; &amp; &quot;low&quot;</dd>' in plain and "<dd><b>Am</b></dd>" in plain


def test_with_a_capo_the_key_says_the_shapes_and_the_sound():
    from caracole.viewer.page import facts_html

    html = facts_html(Key(4, "aeolian"), "from the tab", 2, None, chords=True)
    assert '<div class="fact" data-fact="capo"><dt>Capo</dt><dd>2</dd></div>' in html
    assert ('<div class="fact" data-fact="key"><dt>Key</dt>'
            '<dd><b>Em</b> shapes · sounds <b>F#m</b> · <span class="from">key from the tab</span></dd></div>') in html
    assert "Key <b>" not in html and "capo <b>" not in html  # "Key Em" never alone; the Capo row says the capo


def test_a_tuning_the_sheet_names_is_its_tuning_line():
    html = build_viewer(TUNED)
    assert '<div class="fact" data-fact="tuning"><dt>Tuning</dt><dd>Drop D</dd></div>' in html
    assert _data(html)["tuningName"] == "Drop D"
    plain = build_viewer(TUNED.replace("Tuning: Drop D\n\n", ""))
    assert "tuningName" not in _data(plain) and "<dd>E A D G B E</dd>" in plain
    assert '<dl class="facts" id="facts">' in html and '<p class="facts"' not in html


def test_no_key_no_key_line_and_no_chords_no_facts():
    from caracole.viewer.page import facts_html

    html = facts_html(None, None, 3, None, chords=True)
    assert re.findall(r'data-fact="(\w+)"', html) == ["tuning", "capo"] and "<dd>3</dd>" in html
    assert facts_html(Key(0, "ionian"), "from the sheet", 2, "Drop D", chords=False) == ""
    assert facts_html(None, None, 0, None, chords=False, suffix="-3") == ""
    assert 'id="facts"' not in build_viewer("{title: T}\n{artist: A}\n{capo: 3}\nOnly words\n")


def test_a_songbook_song_has_the_three_lines():
    from caracole.viewer.book import BookSong, build_songbook

    html = build_songbook("Campfire", [BookSong("Minor Song", "Placeholders", cho="{title: Minor Song}\n[Am]la [E]la\n",
                                                key="Am", key_source="tab"),
                                       BookSong("Tuned", "The Placeholders", cho=TUNED, id="b")])
    song = re.search(r'<section class="song" id="song-2".*?</header>', html, re.S).group(0)
    assert ('<dl class="facts" id="facts-2">\n<div class="fact" data-fact="tuning"><dt>Tuning</dt><dd>Drop D</dd></div>\n'
            '<div class="fact" data-fact="capo"><dt>Capo</dt><dd>none</dd></div>\n<div class="fact" data-fact="key">'
            '<dt>Key</dt><dd><b>Dm</b> · <span class="from">from the sheet</span></dd></div>\n</dl>\n</header>') in song
    assert '<dl class="facts" id="facts-1">' in html and '<p class="facts"' not in html
