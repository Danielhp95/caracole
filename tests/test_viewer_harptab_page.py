"""caracole.viewer.harptab_page: harmonica-N.html, a harmonica tab as a page in the viewer's look: what it holds, its
policy and its data (the browser's tests are test_viewer_harptab_browser.py's)."""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path

from caracole.inline import sha256_source
from caracole.viewer import harp, viewer_csp
from caracole.viewer.harptab_page import build_harmonica_viewer
from caracole.viewer.page import HERE
from caracole.viewer.theory import Key, spelling

from test_viewer_harpfit import a_sheet, a_tab

TABS = Path(__file__).parent / "fixtures" / "harptabs" / "tabs"
HOTEL = (TABS / "588_hotel-california.txt").read_text(encoding="utf-8")
KNOCKIN = (TABS / "29910_knockin-on-heavens-door.txt").read_text(encoding="utf-8")
JUKE = (TABS / "1882_juke.txt").read_text(encoding="utf-8")
FACTS = {"title": "hotel california", "artist": "The Eagles", "key": None, "difficulty": "Beginner", "views": 224000,
         "rating": 3.3}


def page(text: str = HOTEL, **given) -> str:
    return build_harmonica_viewer(text, **({"title": "Synthetic Song", "artist": "Placeholder Band",
                                            "tab_file": "harmonica-1.txt"} | given))


def data_of(html: str) -> dict:
    found = re.search(r'<script type="application/json" id="harp-data">(.*?)</script>', html, re.S)
    assert found
    return json.loads(found.group(1))


def text_of(html: str, cls: str) -> str:
    found = re.search(rf'<p class="{cls}"[^>]*>(.*?)</p>', html, re.S)
    return unescape(re.sub(r"<[^>]+>", "", found.group(1))) if found else ""


def test_it_loads_nothing_and_allows_exactly_its_scripts_and_styles():
    html = page()
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    styles = re.findall(r"<style>(.*?)</style>", html, re.S)
    assert scripts == [(HERE / "strum.js").read_text("utf-8"), (HERE / "harptab.js").read_text("utf-8")]
    assert styles == [(HERE / "viewer.css").read_text("utf-8"), (HERE / "harptab.css").read_text("utf-8")]
    policy = unescape(re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', html).group(1))
    assert policy == (f"default-src 'none'; script-src {' '.join(map(sha256_source, scripts))}; "
                      f"style-src {' '.join(map(sha256_source, styles))}; img-src data:; base-uri 'none'; "
                      "form-action 'none'")
    assert "<script src" not in html and "<link rel=\"stylesheet\"" not in html
    served = viewer_csp(html.encode("utf-8"))
    assert served.startswith("sandbox allow-scripts allow-downloads; default-src 'none'")


def test_its_script_builds_every_element_and_writes_no_markup():
    script = (HERE / "harptab.js").read_text("utf-8")
    assert "innerHTML" not in script and "outerHTML" not in script and "insertAdjacentHTML" not in script
    assert "fetch(" not in script and "XMLHttpRequest" not in script


def test_each_hole_over_the_syllable_it_is_blown_on_in_the_sheets_columns():
    html = page()
    first = re.search(r'<p class="l hl">(.*?)<button', html, re.S).group(1)
    columns = re.findall(r'<span class="s"><span class="hg">(.*?)</span><span class="y">(.*?)</span></span>', first)
    shown = [(unescape(re.sub(r"<[^>]+>", "", holes)), unescape(word)) for holes, word in columns]
    assert shown[:6] == [("8", "At "), ("8", "e "), ("8", "nirs "), ("−8", "lom-"), ("−8", "udb "), ("−8", "pavf-")]
    # blow and draw told apart for the stylesheet, and for a screen reader
    assert '<b class="h" data-i="3" tabindex="0" role="button" aria-label="draw 8"><span class="d">' in html


def test_its_data_holds_every_group_and_row_the_page_shows():
    html = page()
    data = data_of(html)
    shown = re.findall(r'<b class="h" data-i="(\d+)"', html)
    assert [int(i) for i in shown] == list(range(len(data["groups"])))
    assert data["groups"][0] == ["note", [[8, "b", 0, 0]]] and data["groups"][3] == ["note", [[8, "d", 0, 0]]]
    played = re.findall(r'<button type="button" class="rp" data-row="(\d+)"', html)
    assert [int(r) for r in played] == list(range(len(data["rows"])))
    assert [i for row in data["rows"] for i in row] == list(range(len(data["groups"])))


def test_its_note_tables_are_harp_pys_and_its_names_each_harps_keys():
    data = data_of(page())
    assert data["harpKeys"] == list(harp.HARP_KEYS)
    assert data["holes"] == harp.hole_tables()
    assert data["names"] == [spelling(Key(h, "ionian")) for h in range(12)]
    assert data["names"][2][6] == "F#" and data["names"][5][10] == "Bb"


def test_the_harp_with_the_record_in_the_header_and_the_bar():
    html = page(a_tab(), cho=a_sheet("D", key="Bm"), page_key="C", facts=FACTS)
    assert text_of(html, "facts") == "Harmonica tab · D harp with the record (4th position, aeolian)"
    assert text_of(html, "why") == "100% of the sung notes fall on the sheet's chords on a D harp, 33% on an F harp"
    data = data_of(html)
    assert data["start"] == 2
    assert data["why"] == {"2": "with the record", "0": "harptabs.com's key"}
    assert data["positions"][2] == "4th position, aeolian" and data["positions"][11] == "1st position"


def test_the_harp_as_the_tab_says_or_its_key_or_the_songs_or_the_usual():
    assert text_of(page(JUKE, page_key="E"), "facts") == "Harmonica tab · A harp, as the tab says"
    assert data_of(page(JUKE, page_key="E"))["why"] == {"9": "as the tab says", "4": "harptabs.com's key"}
    assert text_of(page(HOTEL, page_key="Bb"), "facts") == "Harmonica tab · Bb harp, as harptabs.com's key says"
    other = a_sheet("G", key="G", lines=("other words", "than the tab"))
    assert text_of(page(HOTEL, cho=other), "facts") == "Harmonica tab · G harp for the song's key (1st position)"
    assert text_of(page(HOTEL), "facts") == "Harmonica tab · C harp, as tabs are written when they name none"
    assert data_of(page(HOTEL))["positions"] is None and data_of(page(HOTEL))["why"] == {}


def test_how_to_read_the_holes_and_what_harptabs_com_says_of_the_tab():
    assert text_of(page(facts=FACTS), "legend") == "4 blow −4 draw −3′ bent (4 5) together · Beginner · 224k views · 3.3★"
    assert text_of(page(facts={"views": 1_100_000, "rating": None}), "legend").endswith("together · 1.1M views")
    assert text_of(page(facts={"views": "lots", "rating": True}), "legend").endswith("together")


def test_back_to_the_songs_sheet_or_the_library():
    assert '<a class="back" href="sheet.html">‹ Chord sheet</a>' in page(back="sheet.html")
    assert '<a class="back" href="sheet%20%28auto%29.html">‹ Chord sheet</a>' in page(back="sheet (auto).html")
    assert '<a class="back" href="../../index.html">‹ Library</a>' in page()
    assert 'href="../../index.html#by=Placeholder%20Band"' in page()  # the artist's songs, as a sheet's line


def test_its_foot_links_the_tabs_text_and_its_page_on_harptabs_com_alone():
    html = page(url="https://www.harptabs.com/tab/588/hotel-california")
    assert '<a class="pdf" href="harmonica-1.txt">The tab as text</a>' in html
    assert '<a href="https://www.harptabs.com/tab/588/hotel-california">harptabs.com</a>' in html
    assert '<a href="https://www.harptabs.com/">harptabs.com</a>' in page(url="javascript:alert(1)")


def test_a_tab_it_cant_read_is_its_text_as_written_never_an_error():
    html = page(KNOCKIN, page_key="C")
    assert '<pre class="tab">' in html and "(3)mua (3)do" in html
    assert text_of(html, "facts") == "Harmonica tab, as its tabber wrote it: caracole can't read its notation."
    assert 'class="h"' not in html and 'class="rp"' not in html
    assert 'id="h-up"' not in html and 'id="notes"' not in html and 'id="size"' in html and 'id="scroll"' in html
    data = data_of(html)
    assert "groups" not in data and "rows" not in data
    assert "as its tabber wrote it.</p>" in html and "placed each hole" not in html


def test_everything_it_was_given_is_escaped():
    html = page("4 5\n<b>la</b> & <script>\n", title="<i>Song</i>", artist="A & B")
    assert "<b>la</b>" not in html and "&lt;b&gt;la&lt;/b&gt;" in html
    assert "<h1>&lt;i&gt;Song&lt;/i&gt;</h1>" in html and "A &amp; B" in html
    assert page("4 5\n</script><script>x</script>\n").count("</script>") == 3  # data, strum.js, harptab.js


def test_the_pages_title():
    assert "<title>Synthetic Song · harmonica tab</title>" in page()
