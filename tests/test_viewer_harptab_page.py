"""caracole.viewer.harptab_page: harmonica-N.html, a harmonica tab as a page in the viewer's look: what it holds, its
policy and its data (the browser's tests are test_viewer_harptab_browser.py's)."""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path

from caracole.inline import sha256_source
from caracole.viewer import build_viewer, harp, viewer_csp
from caracole.viewer.harptab_page import build_harmonica_viewer
from caracole.viewer.instruments import GUITAR, chord_shapes
from caracole.viewer.page import HERE
from caracole.viewer.theory import Key, parse_chord, spelling

from test_viewer_harpfit import LINES, a_sheet, a_tab

TABS = Path(__file__).parent / "fixtures" / "harptabs" / "tabs"
SPOKEY = (TABS.parent / "legends" / "693_spokey-dokey.txt").read_text(encoding="utf-8")
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
    assert scripts == [(HERE / name).read_text("utf-8") for name in ("strum.js", "overlay.js", "harptab.js")]
    assert styles == [(HERE / "viewer.css").read_text("utf-8"), (HERE / "harptab.css").read_text("utf-8")]
    policy = unescape(re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', html).group(1))
    assert policy == (f"default-src 'none'; script-src {' '.join(map(sha256_source, scripts))}; "
                      f"style-src {' '.join(map(sha256_source, styles))}; img-src data:; base-uri 'none'; "
                      "form-action 'none'")
    assert "<script src" not in html and "<link rel=\"stylesheet\"" not in html
    served = viewer_csp(html.encode("utf-8"))
    assert served.startswith("sandbox allow-scripts allow-downloads; default-src 'none'")


def test_its_script_builds_every_element_and_writes_no_markup():
    for name in ("harptab.js", "overlay.js"):
        script = (HERE / name).read_text("utf-8")
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


def test_a_tab_in_harptabs_coms_own_notation_has_its_legend_and_what_harptabs_com_says_of_it():
    # Read by the site's own key, guessed (Tab.reading.standard): the familiar legend says enough, the owner's choice
    assert text_of(page(facts=FACTS), "legend") == "4 blow −4 draw −3′ bent (4 5) together · Beginner · 224k views · 3.3★"
    assert text_of(page(facts={"views": 1_100_000, "rating": None}), "legend").endswith("together · 1.1M views")
    # as harptabs.com writes a count under a thousand: 400, never "0k"
    assert text_of(page(facts={"views": 400}), "legend").endswith("together · 400 views")
    assert text_of(page(facts={"views": "lots", "rating": True}), "legend").endswith("together")
    assert "Read as" not in page() and 'id="reading-src"' not in page()
    # served, a link at the foot changes how it is read (harptab.js shows it): from a file, none
    assert ('<p class="reading" id="reading-foot" hidden><a href="#">Change how it\'s read</a></p>' in page())


def test_another_notation_says_how_it_was_read_and_its_source_is_what_changes_it():
    html = page(TABS.joinpath("124_heart-of-gold.txt").read_text("utf-8"), facts={"views": 400})
    assert text_of(html, "legend") == "Read as: B blow · D draw · , together, guessed (1.00) · 400 views"
    assert '<code class="sy">B</code> blow' in html  # each symbol as the tab writes it
    # served, its source is a link to the page that changes it (harptab.js)
    assert '<span class="src" id="reading-src">guessed (1.00)</span>' in html and 'id="reading-foot"' not in html
    pinned = page(HOTEL, pin="signs")
    assert text_of(pinned, "legend") == "Read as: 4 blow · - draw, as you set it"
    assert '<span class="src" id="reading-src">as you set it</span>' in pinned
    assert data_of(pinned)["reading"]["source"] == "pinned"


def test_a_tab_shown_as_written_can_still_be_read_another_way():
    html = page(KNOCKIN)
    assert '<pre class="tab">' in html and 'id="reading-foot" hidden' in html
    read = page(KNOCKIN, pin="brackets")  # a pin is read as it says, the score never asked
    assert data_of(read)["reading"] == {"name": "brackets", "source": "pinned", "q": 0.63, "margin": 0.63,
                                        "said": "4 blow · (4) draw · - joins"}


def test_spokey_dokey_says_it_was_read_by_its_own_legend():
    html = page(SPOKEY, facts={"difficulty": "Expert", "views": 23000})
    assert text_of(html, "legend") == ("Read as: b blow · d draw · * bend · - joins · (h) hold · (w) wah, from the "
                                       "tab's own legend · Expert · 23k views")
    guessed = page("\n".join(line for line in SPOKEY.split("\n") if " = " not in line and "= " not in line))
    assert re.fullmatch(r"Read as: b blow · d draw · \* bend · - joins, guessed \(0\.8\d\)", text_of(guessed, "legend"))
    data = data_of(html)
    assert data["reading"] == {"name": "letters", "source": "legend", "q": 0.96, "margin": 0.87,
                               "said": "b blow · d draw · * bend · - joins · (h) hold · (w) wah"}


def test_its_data_carries_each_holes_effects_and_runs_for_the_script_to_draw_again():
    data = data_of(page(SPOKEY))
    groups = data["groups"]
    assert groups[0] == ["note", [[3, "d", 1, 0]]]  # 3*d: nothing more, nothing more carried
    wah = [g for g in groups if len(g) > 2 and g[2].get("fx")]
    assert len(wah) == 11 and all(g[2]["fx"] == ["wah"] for g in wah)
    assert ["note", [[3, "d", 2, 0]], {"join": 1}] in groups  # 3**d-, run into the next
    shown = re.findall(r'<b class="h" data-i="(\d+)"', page(SPOKEY))
    assert [int(i) for i in shown] == list(range(len(groups)))


def test_what_the_tab_couldnt_read_is_shown_in_place_as_written():
    html = page(SPOKEY)
    rows = re.findall(r'<p class="l holes">(.*?)<button', html, re.S)
    seventh = unescape(re.sub(r"<[^>]+>", "", rows[6]))
    assert seventh.startswith("−3′‿−3 3 2 3 −3′‿−3 4 −4‿$‿−5 −4‿$‿−5 4‿5 4‿5")
    assert '<span class="u">$</span>' in rows[6] and '<span class="u">(DV)</span>' in html
    assert re.search(r'<span class="cell"><span class="u">3</span><span class="jn" aria-hidden="true">‿</span></span>'
                     r'<span class="cell"><b class="h"', rows[1])  # each with its tie, which a line never parts
    # an effect a label on its hole, a hold the page's own
    assert '<small class="fx">wah</small></b>' in html and '<span class="hold" aria-hidden="true">…</span>' in html
    assert 'aria-label="draw 3 bent 1, wah"' in html


def test_the_tabs_legend_is_its_own_block_never_words():
    html = page(SPOKEY)
    block = re.search(r'<div class="tab-legend">(.*?)</div>', html, re.S).group(1)
    assert re.findall(r'<p class="l">(.*?)</p>', block) == ["(w) = Wah effect", "(h) = Hold", "* = bend", "D= draw",
                                                           "b= blow"]
    assert 'class="l words"' not in html


def test_a_row_read_with_low_confidence_is_its_text_as_written():
    html = page("4 -4 5 -5 6\nla la la la la\n\n3b 3b 2b 2b\nlo lo lo lo\n\n-4 -5 6\nli li li\n")
    assert '<pre class="tab asw">3b 3b 2b 2b\nlo lo lo lo</pre>' in html
    data = data_of(html)
    assert len(data["rows"]) == 2 and len(re.findall(r'class="rp"', html)) == 2  # its holes neither drawn nor played


def test_the_foot_says_the_holes_were_placed_only_where_a_row_has_words():
    assert "caracole placed each hole over its syllable" in page()
    assert "placed each hole" not in page(SPOKEY) and "as its tabber wrote it.</p>" in page(SPOKEY)


def test_back_to_the_songs_sheet_or_the_library():
    # the sheet's (data-sheet): harptab.js takes the screen's choices back to it
    assert '<a class="back" href="sheet.html" data-sheet>‹ Chord sheet</a>' in page(back="sheet.html")
    assert '<a class="back" href="sheet%20%28auto%29.html" data-sheet>‹ Chord sheet</a>' in page(back="sheet (auto).html")
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
    assert 'id="necks-toggle"' in html and 'id="necks-open"' in html  # the overlay's, the rail's and the sheet's
    data = data_of(html)
    assert "groups" not in data and "rows" not in data
    assert "as its tabber wrote it.</p>" in html and "placed each hole" not in html


def test_the_harp_harptabs_com_names_reaches_the_reading():
    # A tab its page calls Chromatic is its text as written, a slide pressed or not; Diatonic, a "*" is a bend
    chromatic = page(HOTEL, harp="Chromatic")
    assert '<pre class="tab">' in chromatic and 'class="h"' not in chromatic
    assert text_of(chromatic, "facts") == "Harmonica tab, as its tabber wrote it: caracole can't read its notation."
    assert '<pre class="tab">' not in page(HOTEL, harp="Diatonic")
    starred = "-1 -2 -3* -3**\nla la la la\n"
    assert '<pre class="tab">' in page(starred)  # no chip: "*" is a chromatic's slide
    data = data_of(page(starred, harp="Diatonic"))
    assert [hole for kind, hole in data["groups"]] == [[[1, "d", 0, 0]], [[2, "d", 0, 0]], [[3, "d", 1, 0]],
                                                        [[3, "d", 2, 0]]]


def test_everything_it_was_given_is_escaped():
    html = page("4 5\n<b>la</b> & <script>\n", title="<i>Song</i>", artist="A & B")
    assert "<b>la</b>" not in html and "&lt;b&gt;la&lt;/b&gt;" in html
    assert "<h1>&lt;i&gt;Song&lt;/i&gt;</h1>" in html and "A &amp; B" in html
    assert page("4 5\n</script><script>x</script>\n").count("</script>") == 4  # data, strum.js, overlay.js, harptab.js


def test_the_pages_title():
    assert "<title>Synthetic Song · harmonica tab</title>" in page()


# --- the overlay: Harmonica first, then Guitar (overlay.js) --------------------------------------------------------

SHAPES = ("Am", "E7", "G", "D", "F", "C", "Dm", "E")
SOUNDS = ("Bm", "F#7", "A", "E", "G", "D", "Em", "F#")  # with the capo on 2


def a_song(chords: tuple[str, ...] = SHAPES, *, key: str = "Am", capo: int = 2) -> str:
    """A ChordPro sheet, as caracole writes one, over the tab's lines (``a_tab``), two chords a line."""
    lines = []
    for n, line in enumerate(LINES[:4]):
        words = line.split(" ")
        lines.append(f"[{chords[2 * n]}]{' '.join(words[:3])} [{chords[2 * n + 1]}]{' '.join(words[3:])}\n")
    return (f"{{title: Synthetic}}\n{{artist: Placeholder Band}}\n{{key: {key}}}\n"
            + (f"{{capo: {capo}}}\n" if capo else "") + "".join(lines))


TAB_D = a_tab(3, before="We play it, so I use a D harp\n\n")  # too few notes for the record: its words name the harp


def test_the_overlays_harmonica_is_the_songs_key_as_it_sounds_with_the_viewers_tables():
    data = data_of(page(TAB_D, cho=a_song(), key="Am", key_source="tab"))
    assert data["start"] == 2  # a D harp, as the tab says
    part = data["overlay"]["harp"]
    sheet = re.search(r'<script type="application/json" id="song">(.*?)</script>',
                      build_viewer(a_song(), key="Am", key_source="tab"), re.S)
    viewer = json.loads(sheet.group(1))
    assert (part["key"], part["tonic"], part["names"]) == ("Bm", 11, spelling(Key(11, "aeolian")))
    assert part["tabs"] == [3]  # the D harp, three above B: the tab's
    assert part["choices"] == viewer["harps"]["aeolian"]  # the harps the sheet's viewer offers, as it sounds
    for name in ("ring", "holes"):
        assert part[name] == viewer["harp" + name.capitalize()]
    assert part["scales"] == viewer["harpScales"]["aeolian"] and part["outside"] == viewer["harpOutside"]["aeolian"]
    assert [c["name"] for c in part["chords"]] == list(SOUNDS)
    assert [c["shape"] for c in part["chords"]] == list(SHAPES)
    assert [c["root"] for c in part["chords"]] == ["B", "F#", "A", "E", "G", "D", "E", "F#"]
    for i, chord in enumerate(part["chords"]):
        assert chord["entries"] == viewer["harpForms"][viewer["harpChords"]["aeolian"][i]]
        assert chord["notes"] == viewer["harpNotes"]["aeolian"][i]
    by_name = {c["name"]: c["entries"][3] for c in part["chords"]}  # on the D harp
    assert by_name["A"] == ["yes", "draw", 2, 4] and by_name["E"] == ["minor", "draw", 4, 6, "m"]
    assert by_name["Bm"] is None


def test_the_overlays_guitar_is_the_sheet_as_written():
    guitar = data_of(page(TAB_D, cho=a_song(), key="Am", key_source="tab"))["overlay"]["guitar"]
    assert guitar["name"] == "Guitar" and guitar["strings"] == 6
    assert [c["name"] for c in guitar["chords"]] == list(SHAPES)
    assert guitar["chords"][1]["list"] == chord_shapes(GUITAR, parse_chord("E7"))
    assert all(c["mine"] == 0 for c in guitar["chords"])
    assert guitar["key"] == {"name": "Am", "tonic": 9, "tonicName": "A", "scale": [0, 2, 3, 5, 7, 8, 10],
                             "pentatonic": [0, 3, 5, 7, 10], "pentaName": "minor pentatonic",
                             "tuning": [40, 45, 50, 55, 59, 64]}


def test_with_no_sheet_the_overlay_has_no_guitar_and_no_key_for_the_harps():
    overlay = data_of(page(TAB_D))["overlay"]
    assert overlay["guitar"] is None
    assert overlay["harp"]["key"] is None and "chord sheet" in overlay["harp"]["none"]
    assert overlay["harp"]["holes"] == [harp.holes(o) for o in range(12)]


def test_a_sheet_with_no_key_has_its_guitar_tab_and_says_so_of_the_harps():
    # A chord sheet with no chord caracole can read: its Guitar tab is there, so the line never says there is no sheet
    keyless = "{title: Synthetic Song}\n{artist: Placeholder Band}\n[N.C.]la la [Hm]lo lo\n"
    overlay = data_of(page(TAB_D, cho=keyless))["overlay"]
    assert overlay["guitar"] is not None and overlay["harp"]["key"] is None
    assert overlay["harp"]["none"] == "With no key in its chord sheet, caracole can't tell which harp plays the song."


def test_a_harp_its_page_guesses_is_no_tabs():
    # harptabs.com's key, with no record and no word of the tab's: the page starts there, but no harp is the tab's.
    part = data_of(page(a_tab(3), cho=a_song(), key="Am", key_source="tab", page_key="C"))["overlay"]["harp"]
    assert part["tabs"] == []


def test_the_page_has_the_overlays_rail_and_its_bars_button():
    html = page(TAB_D, cho=a_song(), key="Am", key_source="tab")
    assert '<aside class="necks" id="necks" hidden aria-label="Chord necks"></aside>' in html
    assert re.search(r'<div class="bar-in">\n<button type="button" class="tool necks-toggle" id="necks-toggle" hidden',
                     html)
