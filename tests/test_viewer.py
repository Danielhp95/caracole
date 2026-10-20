"""caracole.viewer: sheet.html, the phone-friendly page beside each sheet's PDF."""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import re
import threading
from html import unescape
from pathlib import Path

import pytest
from helpers import browser
from helpers.browser import in_chromium

from caracole.chordpro import to_chordpro
from caracole.viewer import build_viewer, info_key, key_heard, viewer_csp
from caracole.viewer.voicings import load_voicings

FIXTURES = Path(__file__).parent / "fixtures" / "chordpro"
UG_CHO = (FIXTURES / "ug_sheet.cho").read_text(encoding="utf-8")
MINOR = to_chordpro(
    "[ch]Cm[/ch]      [ch]Ab[/ch]\nTiny minor words\n[ch]Bb[/ch]     [ch]G7[/ch]\nand back home",
    title="Minor", artist="Placeholders", key="Cm",
)
WALL = to_chordpro(
    "[ch]Em7[/ch]      [ch]G[/ch]\nSynthetic words go here\n[ch]Dsus4[/ch]     [ch]A7sus4[/ch]\nmade up for the test\n"
    "[ch]Cadd9[/ch]  [ch]D[/ch]  [ch]Em7[/ch]\nand home",
    title="Wall", artist="Synthetic", capo=2,
)  # Em shapes with capo 2, as Wonderwall is played: open shapes already, so no capo hint


def data_of(html: str) -> dict:
    found = re.search(r'<script type="application/json" id="song">(.*?)</script>', html, re.S)
    assert found, "no song data"
    return json.loads(found.group(1))


def facts_of(html: str) -> str:
    found = re.search(r'<p class="facts" id="facts">(.*?)</p>', html, re.S)
    assert found, "no key line"
    return found.group(1)


def sheet_of(html: str) -> str:
    found = re.search(r'<article[^>]*id="sheet"[^>]*>(.*?)</article>', html, re.S)
    assert found, "no sheet"
    return found.group(1)


# --- the static page --------------------------------------------------------------------------


def test_the_page_shows_the_sheet_with_its_chords_marked():
    html = build_viewer(UG_CHO)
    assert "<title>Synthetic Test Song · The Placeholders</title>" in html
    sheet = sheet_of(html)
    assert re.search(r'<b class="c" data-c="0"[^>]*>G</b>', sheet)
    assert re.search(r'<b class="c" data-c="4"[^>]*>G/B</b>', sheet)
    assert ">Verse 1</h2>" in sheet and "Tiny " in sheet
    assert '<pre class="tab">e|-----0---0---|' in sheet
    assert '<i class="m">x2</i>' in sheet


def test_words_after_a_chord_wrap_one_by_one():
    sheet = sheet_of(build_viewer(UG_CHO))
    # the first word rides with its chord; the rest are words of their own, so a narrow
    # screen wraps the line between words and never between a chord and its syllable
    assert re.search(r'<span class="s"><b class="c" data-c="0"[^>]*>G</b><span class="y">Tiny </span></span>'
                     r'<span class="w">test </span>', sheet)


def test_chinese_words_wrap_by_character():
    zh = to_chordpro((FIXTURES / "zh_sheet.txt").read_text(encoding="utf-8"), title="斑马斑马", artist="宋冬野")
    sheet = sheet_of(build_viewer(zh))
    assert '<span class="y">合</span></span><span class="w">成</span><span class="w">的</span>' in sheet


def test_what_the_sheet_says_is_text_never_markup():
    cho = "{title: Creep</script><b>x</b>}\n{artist: A & B}\n{comment: <i>Verse</i>}\n[G]<img src=x> \"words\"\n"
    html = build_viewer(cho)
    assert "<b>x</b>" not in html and "<img" not in html and "<i>Verse" not in html
    assert "Creep&lt;/script&gt;&lt;b&gt;x&lt;/b&gt;" in html
    assert "A &amp; B" in html
    payload = re.search(r'id="song">(.*?)</script>', html, re.S).group(1)
    assert "<" not in payload


def test_the_content_security_policy_allows_exactly_the_inline_script_and_style():
    html = build_viewer(UG_CHO)
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html).group(1)
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    style = re.search(r"<style>(.*?)</style>", html, re.S).group(1)

    def sha(text: str) -> str:
        return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"

    assert "default-src 'none'" in csp
    assert f"script-src {sha(script)}" in csp
    assert f"style-src {sha(style)}" in csp
    assert "base-uri 'none'" in csp and "form-action 'none'" in csp


def test_a_server_sends_the_pages_own_policy_in_a_sandbox():
    # A <meta> policy can't sandbox the page; a server's header can: the page then has an
    # origin of its own, with no cookie and no way to ask the server for anything.
    html = build_viewer(UG_CHO)
    meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html).group(1)
    assert viewer_csp(html.encode("utf-8")) == "sandbox allow-scripts; " + meta


def test_a_page_goes_out_with_the_policy_it_was_written_with(monkeypatch):
    # A newer caracole's script and style have other hashes; the page holds its own.
    from caracole.viewer import page

    written = build_viewer(UG_CHO)
    meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', written).group(1)
    style, script = page._assets()
    monkeypatch.setattr(page, "_assets", lambda: (style + "\n.new {}", script + "\n// a new release"))
    assert build_viewer(UG_CHO) != written
    assert viewer_csp(written.encode("utf-8")) == "sandbox allow-scripts; " + meta


@pytest.mark.parametrize("written", [
    b"<!doctype html><title>No policy</title><script>alert(1)</script>",
    b'<meta http-equiv="Content-Security-Policy" content="default-src *&#13;&#10;X-Evil: 1">',  # no header split
    b'<meta http-equiv="Content-Security-Policy" content="">',
    b"\xff\xfe not even text",
])
def test_a_page_without_a_policy_to_send_runs_nothing(written):
    assert viewer_csp(written) == "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'"


def test_the_page_loads_nothing_and_links_only_beside_itself():
    html = build_viewer(UG_CHO, pdf="sheet.pdf")
    assert "<link" not in html and "@import" not in html and "url(" not in html
    assert not re.search(r"\ssrc=", html)
    hrefs = re.findall(r'href="([^"]*)"', html)
    assert "sheet.pdf" in hrefs and "../../index.html" in hrefs
    assert [h for h in hrefs if "://" in h] == ["https://github.com/tombatossals/chords-db"]


def test_the_pdf_is_linked_only_when_there_is_one():
    assert 'href="sheet%20%28auto%29.pdf"' in build_viewer(UG_CHO, pdf="sheet (auto).pdf")
    assert not re.search(r'href="[^"]*\.pdf"', build_viewer(UG_CHO))


def test_the_page_credits_the_fingerings():
    html = build_viewer(UG_CHO)
    foot = re.search(r'<footer class="foot">(.*?)</footer>', html, re.S).group(1)
    assert "chords-db" in foot and "© 2016 David Rubert" in foot and "MIT" in foot
    # MIT: the copyright and permission notice go with every copy of the fingerings
    assert "Copyright (c) 2016 David Rubert" in foot
    assert "Permission is hereby granted, free of charge" in foot
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in foot.replace("&quot;", '"')


def test_an_auto_sheet_says_it_is_unverified():
    html = build_viewer(to_chordpro("[ch]Am[/ch]\nla", title="T", artist="A", auto=True))
    assert "auto-generated, unverified" in html.lower() or "Auto-generated, unverified" in html


# --- the key ------------------------------------------------------------------------------------


def test_the_key_from_info_json_comes_first():
    data = data_of(build_viewer(UG_CHO, key="Em", key_source="tab"))
    assert data["key"] == {"tonic": 4, "mode": "aeolian", "from": "from the tab"}


def test_then_the_key_the_sheet_gives():
    data = data_of(build_viewer(UG_CHO))
    assert data["key"] == {"tonic": 7, "mode": "ionian", "from": "from the sheet"}


def test_then_a_key_estimated_from_the_chords():
    cho = UG_CHO.replace("{key: G}\n", "")
    data = data_of(build_viewer(cho, key="soda stereo|de musica ligera", key_source=None))
    assert data["key"] == {"tonic": 7, "mode": "ionian", "from": "estimated from the chords"}


def test_with_a_capo_the_key_line_says_the_shapes_the_capo_and_the_key_it_sounds_in():
    # "Key Em · Capo 2" read as the song's key; Em is the shapes', and the song sounds in F#m.
    assert facts_of(build_viewer(WALL)) == (
        '<b>Em</b> shapes · capo <b>2</b> · sounds <b>F#m</b> · <span class="from">key estimated from the chords</span>'
    )
    assert facts_of(build_viewer(UG_CHO)) == (
        '<b>G</b> shapes · capo <b>2</b> · sounds <b>A</b> · <span class="from">key from the sheet</span>'
    )


def test_a_tabs_key_that_names_the_sound_is_not_taken_for_the_shapes():
    # UG names the key of some tabs with a capo as the song sounds: "F#" for C shapes with capo 6.
    sheet = to_chordpro("[ch]C[/ch]      [ch]Em[/ch]\nSynthetic words here\n[ch]F[/ch]     [ch]G[/ch]  [ch]C[/ch]\nand home",
                        title="River", artist="Synthetic", key="F#", capo=6)
    for html in (build_viewer(sheet), build_viewer(sheet, key="F#", key_source="tab")):
        assert data_of(html)["key"]["tonic"] == 0  # C shapes
        assert facts_of(html).startswith("<b>C</b> shapes · capo <b>6</b> · sounds <b>F#</b>")
    assert data_of(build_viewer(UG_CHO))["key"]["tonic"] == 7  # G with capo 2, its chords in G: the shapes


def test_without_a_capo_the_key_line_names_the_key():
    assert facts_of(build_viewer(MINOR)) == 'Key <b>Cm</b> <span class="from">from the sheet</span>'
    assert facts_of(build_viewer("{title: T}\n{artist: A}\n{capo: 3}\nOnly words\n")) == "Capo <b>3</b>"
    assert facts_of(build_viewer("{title: T}\n{artist: A}\nOnly words\n")) == ""


def test_a_sheet_without_chords_has_no_key():
    data = data_of(build_viewer("{title: T}\n{artist: A}\nOnly words\n"))
    assert data["key"] is None


@pytest.mark.parametrize(
    ("source", "label"),
    [("tab", "from the tab"), ("model", "from the audio"), ("autochords", "from the audio"),
     ("estimate", "estimated from the chords"), ("chords", "estimated from the chords"),
     ("Musicbrainz", "from Musicbrainz"), (None, "from info.json")],
)
def test_where_the_key_came_from_is_said_in_words(source, label):
    assert data_of(build_viewer(UG_CHO, key="G", key_source=source))["key"]["from"] == label


@pytest.mark.parametrize(
    ("info", "found"),
    [
        ({"key": "Am", "key_source": "tab"}, ("Am", "tab")),
        ({"key": "C dorian"}, ("C dorian", None)),
        ({"key": "radiohead|creep"}, (None, None)),  # the song's identity key, not a musical one
        ({"key": 5, "key_source": "tab"}, (None, None)),
        ({}, (None, None)),
        (["not", "a", "dict"], (None, None)),
    ],
)
def test_info_json_gives_a_musical_key_or_none(info, found):
    assert info_key(info) == found


@pytest.mark.parametrize(
    ("source", "heard"),
    [("audio", True), ("model", True), ("autochords", True), (" Audio ", True),
     ("tab", False), ("chords", False), ("estimate", False), (None, False), (5, False)],
)
def test_a_key_heard_in_the_audio_is_told_apart(source, heard):
    assert key_heard(source) is heard


# --- what the script works from ------------------------------------------------------------------


def test_the_viewer_starts_at_the_transposition_the_pdf_has():
    assert data_of(build_viewer(UG_CHO, transpose=3))["transpose"] == 3
    assert data_of(build_viewer(UG_CHO))["transpose"] == 0


def test_chords_are_given_as_root_suffix_and_bass():
    chords = data_of(build_viewer(UG_CHO))["chords"]
    assert chords[0][:3] == [7, "", None]  # G
    assert chords[4][:3] == [7, "", 11]  # G/B
    assert chords[2][:3] == [4, "m", None]  # Em


def test_a_chord_caracole_cant_read_is_shown_as_written():
    html = build_viewer("{title: T}\n{artist: A}\n[G]la [(G)]lo [H7]li\n")
    assert data_of(html)["chords"][1:] == [None, None]
    assert ">(G)</b>" in sheet_of(html) and ">H7</b>" in sheet_of(html)


def test_every_chord_shown_has_fingerings_on_every_root():
    data = data_of(build_viewer(MINOR))
    reps = [r for r in data["chords"] if r]
    reps += [r for mode in data["mapped"].values() for r in mode if r]
    reps += [r for mode in data["alts"].values() for alts in mode for r in alts]
    for rep in reps:
        assert len(data["voicings"][rep[3]]) == 12, rep
        if rep[5]:
            assert len(data["voicings"][rep[5]]) == 12, rep
    assert data["voicings"]["m"] == load_voicings()["m"]


def test_each_mode_maps_the_chords_by_scale_degree():
    data = data_of(build_viewer(MINOR))
    assert data["modes"] == ["ionian", "dorian", "phrygian", "lydian", "mixolydian", "aeolian", "locrian"]
    major = data["mapped"]["ionian"]
    assert [r[:3] for r in major] == [[0, "", None], [9, "m", None], [11, "dim", None], [7, "7", None]]
    assert data["mapped"]["aeolian"] == data["chords"]  # the key's own mode: as written


def test_alternatives_are_given_for_each_chord_in_each_mode():
    data = data_of(build_viewer(MINOR))
    assert set(data["alts"]) == set(data["modes"])
    assert all(len(alts) == len(data["chords"]) for alts in data["alts"].values())
    tonic = data["alts"]["aeolian"][0]  # Cm's, in C minor
    assert [0, "m7", None] in [r[:3] for r in tonic]


def test_names_spell_every_key_of_every_mode():
    data = data_of(build_viewer(MINOR))
    assert data["names"]["ionian"][5] == "C Db D Eb E F Gb G Ab A Bb B"
    assert data["names"]["aeolian"][9] == "C C# D Eb E F F# G G# A Bb B"
    assert data["keyNames"]["aeolian"][0] == "Cm" and data["keyNames"]["dorian"][2] == "D dorian"


def test_without_a_key_one_spelling_serves_every_transposition():
    data = data_of(build_viewer("{title: T}\n{artist: A}\nOnly words\n"))
    assert data["names"] == {"": "C C# D Eb E F F# G Ab A Bb B"}
    assert data["mapped"] == {} and data["capo"] == {}


def test_capo_hints_are_given_for_each_transposition():
    data = data_of(build_viewer(UG_CHO))  # G shapes, capo 2
    assert data["capoSheet"] == 2
    assert data["capo"]["ionian"][0] == []  # G: open chords already
    # each hint is the fret the capo goes on, 0 for none, and the shapes then played
    assert data["capo"]["ionian"][3] == [[0, "C"], [3, "A"]]  # up three: Bb shapes, sounding C
    assert data["capo"]["ionian"][10] == [[0, "G"], [3, "E"]]  # down two: F shapes, sounding G


# --- in a real browser ---------------------------------------------------------------------------

def dump_dom(html: str, tmp_path: Path, fragment: str = "") -> str:
    """The page's DOM after its script ran; skips the test when this machine can't run Chromium.

    Each call has a browser context of its own (helpers/browser.py), as fresh as a new profile, so
    nothing a page kept in localStorage carries over."""
    page = tmp_path / "Artist" / "Title" / "sheet.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(html, encoding="utf-8")
    return dump_url(page.as_uri() + fragment, tmp_path)


def dump_url(url: str, tmp_path: Path) -> str:
    """The DOM of the page at ``url`` after its script ran, in Chromium (see dump_dom)."""
    return browser.dump_dom(url, (390, 844))


def chord_texts(dom: str) -> dict[str, str]:
    """Each chord's label in the sheet, by its index (the first of its places)."""
    found: dict[str, str] = {}
    for index, text in re.findall(r'<b class="c[^"]*" data-c="(\d+)"[^>]*>([^<]*)</b>', sheet_of(dom)):
        found.setdefault(index, text)
    return found


@in_chromium
def test_the_script_runs_and_leaves_the_sheet_as_written(tmp_path):
    dom = dump_dom(build_viewer(UG_CHO), tmp_path)
    assert 'data-ready="1"' in dom
    assert chord_texts(dom) == {"0": "G", "1": "D", "2": "Em", "3": "C", "4": "G/B", "5": "Am", "6": "F"}
    assert '<span class="vh" id="key-full">G shapes · capo 2 · sounds A</span>' in dom


@in_chromium
@pytest.mark.parametrize(
    ("cho", "label"),
    [(UG_CHO, "G shapes · capo 2 · sounds A"), (WALL, "Em shapes · capo 2 · sounds F#m"), (MINOR, "Key Cm")],
    ids=["capo", "capo-on-open-shapes", "no-capo"],
)
def test_the_bar_and_the_settings_say_what_the_key_line_says(tmp_path, cho, label):
    # The script writes the line the page came with, so nothing moves as it runs; the bar (to a
    # screen reader, whole) and the settings' heading say the same: the shapes, the capo and the
    # key the song sounds in.
    html = build_viewer(cho)
    facts, said, heading = run_in_page(html, tmp_path, """
      out = [q("#facts").textContent, q("#key-full").textContent, q("#panel-title").textContent];
    """)
    assert facts == unescape(re.sub(r"<[^>]+>", "", facts_of(html)))
    assert said == label and heading == label


@in_chromium
def test_the_page_works_served_in_a_sandbox(tmp_path):
    page = build_viewer(UG_CHO).encode("utf-8")

    class Server(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", viewer_csp(page))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Server)
    # shutdown() returns at the next poll: every 10 ms, not every 500
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    try:
        dom = dump_url(f"http://127.0.0.1:{server.server_port}/Artist/Title/sheet.html#t=2", tmp_path)
    finally:
        server.shutdown()
        server.server_close()
    assert 'data-ready="1"' in dom  # its script ran, under the header's hashes
    assert chord_texts(dom)["0"] == "A"  # and without storage, which a sandbox refuses


@in_chromium
def test_transposing_renames_every_chord(tmp_path):
    dom = dump_dom(build_viewer(UG_CHO), tmp_path, "#t=2")
    assert chord_texts(dom) == {"0": "A", "1": "E", "2": "F#m", "3": "D", "4": "A/C#", "5": "Bm", "6": "G"}
    assert "<b>A</b> shapes · capo <b>2</b> · sounds <b>B</b> (+2)" in dom  # the sheet has capo 2
    dom = dump_dom(build_viewer(UG_CHO), tmp_path, "#t=-4")  # down to Eb: flats
    assert chord_texts(dom)["2"] == "Cm" and chord_texts(dom)["0"] == "Eb"


@in_chromium
def test_a_capo_shows_the_shapes_to_play(tmp_path):
    dom = dump_dom(build_viewer(UG_CHO), tmp_path, "#t=3&capo=3")  # Bb shapes; capo 3: A shapes
    assert chord_texts(dom)["0"] == "A"
    assert "<b>A</b> shapes · capo <b>3</b> · sounds <b>C</b> (+3)" in dom


@in_chromium
def test_a_capo_may_come_off(tmp_path):
    out = run_in_page(build_viewer(UG_CHO), tmp_path, """
      const chips = [...document.querySelectorAll("#capo .chip")].map((b) => b.textContent);
      [...document.querySelectorAll("#capo .chip")][0].click();
      out = [chips, q('#sheet .c[data-c="0"]').textContent, q("#facts").textContent];
    """, "#t=-2")  # G shapes with capo 2, down two: F shapes, sounding G
    chips, chord, facts = out
    assert chips == ["No capoG shapes", "Capo 3E shapes"]
    assert chord == "G" and facts == "Key G (−2) from the sheet · no capo"


@in_chromium
def test_every_song_has_a_capo_to_move(tmp_path):
    # Em shapes are open already, so no fret is suggested; the capo moves all the same, the chords
    # show the shapes to play with it, and the song keeps sounding in F#m.
    shown, offered, off, four, back = run_in_page(build_viewer(WALL), tmp_path, """
      const look = () => [q('#sheet .c[data-c="0"]').textContent, q("#key-full").textContent,
                          q("#capo-at").textContent, location.hash];
      q("#more").click();
      const shown = q("#capo-row").getBoundingClientRect().height > 0 && q("#capo-up").offsetParent !== null;
      const offered = document.querySelectorAll("#capo .chip").length;
      q("#capo-down").click();
      q("#capo-down").click();
      q("#capo-down").click();  // no lower than none
      const off = look().concat([q("#facts").textContent]);
      for (let i = 0; i < 4; i++) q("#capo-up").click();
      const four = look().concat([q("#mode-hint").textContent]);
      q("#reset-capo").click();
      out = [shown, offered, off, four, look()];
    """)
    assert shown and offered == 0
    assert off == ["F#m7", "Key F#m · no capo", "0", "#capo=0", "Key F#m estimated from the chords · no capo"]
    assert four == ["Dm7", "Dm shapes · capo 4 · sounds F#m", "4", "#capo=4", "F#m: the natural minor."]
    assert back == ["Em7", "Em shapes · capo 2 · sounds F#m", "2", ""]


@in_chromium
def test_a_sheet_with_no_key_moves_its_capo_too(tmp_path):
    before, after = run_in_page(build_viewer("{title: T}\n{artist: A}\n{capo: 1}\n[(G)]la [H7]lo\n"), tmp_path, """
      const before = [q("#facts").textContent, q("#key-full").textContent];
      q("#more").click();
      q("#capo-down").click();
      out = [before, [q("#facts").textContent, q("#key-full").textContent, location.hash]];
    """)
    assert before == ["Capo 1", "Transpose · capo 1"]
    assert after == ["No capo", "Transpose · no capo", "#capo=0"]


def phone_tab(browser, url: str, width: int = 390, height: int = 844):
    """A tab of ``browser`` (helpers.chromium) as wide as a phone's screen, at ``url``, once the
    viewer's script ran: headless Chromium's own window is never narrower than 500 px."""
    from helpers.chromium import Tab

    target = browser.send("Target.createTarget", url="about:blank")["targetId"]
    session = browser.send("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
    browser.send("Emulation.setDeviceMetricsOverride", session, width=width, height=height, deviceScaleFactor=2,
                 mobile=True)
    browser.send("Page.navigate", session, url=url)
    tab = Tab(browser, session)
    tab.wait_for("document.documentElement.dataset.ready === '1'")
    return tab


@in_chromium
def test_the_capo_control_fits_a_phone_and_holds_still(tmp_path):
    # On a phone: the capo's buttons never move under a thumb that taps them again, though the
    # heading above them names other shapes at each fret, on one line or two; they are big enough
    # to tap; and with the longest key line, the bar still fits, with nothing scrolling sideways.
    from helpers.chromium import Chromium

    def written(name: str, cho: str) -> str:
        page = tmp_path / "Artist" / name / "sheet.html"
        page.parent.mkdir(parents=True)
        page.write_text(build_viewer(cho), encoding="utf-8")
        return page.as_uri()

    box = "(() => { const r = document.querySelector('%s').getBoundingClientRect(); return [r.top, r.width, r.height]; })()"
    text = ("(() => { const r = document.createRange(); r.selectNodeContents(document.querySelector('#panel-title'));"
            " return r.getBoundingClientRect().height; })()")
    with Chromium(tmp_path / "profile") as browser:
        tab = phone_tab(browser, written("Wall", WALL))
        tab.click("#more")
        heights, tops = set(), set()
        for button in ["#capo-up"] * 4 + ["#capo-down"] * 6:  # capo 2 up to 6, then down to none
            heights.add(round(tab.eval(text)))
            tops.add(round(tab.eval(box % "#capo-up")[0]))
            tab.click(button)
        sizes = [min(tab.eval(box % s)[1:]) for s in ("#capo-down", "#capo-up", "#reset-capo")]
        assert len(heights) > 1  # the heading wrapped at some frets and not at others...
        assert len(tops) == 1  # ...and the buttons stayed where they were
        assert min(sizes) >= 44

        tab = phone_tab(browser, written("Long", UG_CHO) + "#mode=mixolydian&t=1")
        assert tab.eval("document.querySelector('#key-full').textContent") == (
            "Ab mixolydian shapes · capo 2 · sounds Bb mixolydian · +1")
        bar = tab.eval("(() => { const r = document.querySelector('#bar').getBoundingClientRect(); "
                       "return [r.left, r.right, innerWidth, document.documentElement.scrollWidth]; })()")
        assert bar[0] >= 0 and bar[1] <= bar[2] == 390 and bar[3] <= bar[2]


@in_chromium
def test_a_mode_change_moves_the_chords(tmp_path):
    dom = dump_dom(build_viewer(MINOR), tmp_path, "#mode=ionian")
    assert chord_texts(dom) == {"0": "C", "1": "Am", "2": "Bdim", "3": "G7"}


@in_chromium
def test_tapping_a_chord_shows_its_shapes_and_alternatives(tmp_path):
    dom = dump_dom(build_viewer(UG_CHO), tmp_path, "#chord=0")
    card = re.search(r'<section class="sheet-ui card[^"]*" id="card"([^>]*)>(.*?)</section>', dom, re.S)
    assert "hidden" not in card.group(1)
    assert '<h2 id="card-name" tabindex="-1">G</h2>' in card.group(2)
    assert "<svg" in card.group(2) and card.group(2).count('class="dg-dot"') == 3  # 320003
    assert ">Gmaj7</button>" in card.group(2) and ">Em</button>" in card.group(2)


# Taps through the page as a guitarist would; run after the page's own script.
HARNESS = """<script>
window.addEventListener("load", () => {
  const out = [];
  const q = (s) => document.querySelector(s);
  const chip = (box, text) => [...document.querySelectorAll(box + " .chip")]
    .find((b) => b.firstChild.textContent === text);
  q('#sheet .c[data-c="0"]').click();
  out.push(q("#card-name").textContent, q("#card").hidden);
  chip("#alts", "Em").click();
  out.push(q("#card-name").textContent, q("#use").textContent);
  q("#use").click();
  const g = q('#sheet .c[data-c="0"]');
  out.push(g.textContent, g.classList.contains("changed"));
  q("#card .x").click();
  q("#more").click();
  q("#up").click();
  q("#up").click();
  out.push(q('#sheet .c[data-c="1"]').textContent, g.textContent, q("#key-full").textContent);
  chip("#modes", "Minor").click();
  out.push(q('#sheet .c[data-c="1"]').textContent, g.textContent);
  q("#reset-all").click();
  out.push(g.textContent, q('#sheet .c[data-c="1"]').textContent);
  document.body.dataset.result = JSON.stringify(out);
});
</script>
"""


def run_in_page(html: str, tmp_path: Path, body: str, fragment: str = "", before: str = ""):
    """What ``body`` (JavaScript, after the page's own script ran) gives as ``out``, in Chromium.

    ``before`` runs before the page's script, once the sheet is there."""
    script = ("<script>\nwindow.addEventListener(\"load\", () => {\n"
              "const q = (s) => document.querySelector(s);\nlet out;\n" + body
              + "\ndocument.body.dataset.result = JSON.stringify(out);\n});\n</script>\n")
    html = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>\n', "", html)
    if before:
        data = '<script type="application/json" id="song">'
        html = html.replace(data, f"<script>\n{before}\n</script>\n{data}")
    dom = dump_dom(html.replace("</body>", script + "</body>"), tmp_path, fragment)
    found = re.search(r'data-result="([^"]*)"', dom)
    assert found, "the harness didn't run"
    return json.loads(found.group(1).replace("&quot;", '"').replace("&amp;", "&"))


SAVED_ALTERNATIVES = """
  const written = {};
  for (const el of document.querySelectorAll("#sheet .c")) if (!(el.dataset.c in written)) written[el.dataset.c] = el.textContent;
  const chords = Object.keys(written).map((i) => written[i]).join("|");
  localStorage.setItem("caracole-viewer:" + location.pathname, JSON.stringify({
    base: 0, chords,
    alt: { ionian: {
      "0": [4, "m", null],  // Em for G: still offered
      "1": [1, "dim", null],  // C#dim for D: not offered (any more)
      "2": 0,  // what an older viewer kept: an index into a list that may have changed since
    } },
  }));
"""


@in_chromium
def test_the_address_keeps_where_the_song_is_played(tmp_path):
    # Read back as #t=, #mode= and #capo=, so a reload keeps them where the page has no storage.
    hashes = run_in_page(build_viewer(UG_CHO), tmp_path, """
      const before = location.hash;
      q("#more").click();
      q("#up").click();
      q("#up").click();
      const up = location.hash;
      [...document.querySelectorAll("#modes .chip")].find((b) => b.firstChild.textContent === "Minor").click();
      const minor = location.hash;
      q("#reset-all").click();
      out = [before, up, minor, location.hash];
    """, "#panel=1")
    assert hashes == ["#panel=1", "#panel=1&t=2", "#panel=1&t=2&mode=aeolian", "#panel=1"]


@in_chromium
def test_the_address_keeps_the_text_size(tmp_path):
    # As fs=, read back on a reload, so the page keeps it where it has no storage (a server's
    # sandbox); the usual size leaves the address alone.
    hashes = run_in_page(build_viewer(UG_CHO), tmp_path, """
      q("#size").click();
      q("#bigger").click();
      const bigger = [location.hash, getComputedStyle(q("#sheet")).fontSize];
      q("#smaller").click();
      out = [bigger, [location.hash, getComputedStyle(q("#sheet")).fontSize]];
    """, "#t=1")
    assert hashes == [["#t=1&fs=20", "20px"], ["#t=1", "18px"]]
    read = run_in_page(build_viewer(UG_CHO), tmp_path, 'out = [getComputedStyle(q("#sheet")).fontSize, location.hash];',
                       "#fs=24")
    assert read == ["24px", "#fs=24"]
    odd = run_in_page(build_viewer(UG_CHO), tmp_path, 'out = [getComputedStyle(q("#sheet")).fontSize, location.hash];',
                      "#fs=99")
    assert odd == ["18px", ""]  # a size the page can't show is its own


@in_chromium
def test_served_in_a_sandbox_a_reload_keeps_the_text_size(tmp_path):
    page = build_viewer(UG_CHO).encode("utf-8")

    class Server(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Security-Policy", viewer_csp(page))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    try:
        dom = dump_url(f"http://127.0.0.1:{server.server_port}/Artist/Title/sheet.html#fs=22", tmp_path)
    finally:
        server.shutdown()
        server.server_close()
    assert 'data-ready="1"' in dom  # its script ran, without storage
    assert re.search(r'<html[^>]*style="--fs: 22px;"', dom)


@in_chromium
def test_a_chosen_chord_is_kept_as_itself_not_as_its_place_in_a_list(tmp_path):
    shown, changed, saved = run_in_page(build_viewer(UG_CHO), tmp_path, """
      const sheet = (i) => q('#sheet .c[data-c="' + i + '"]');
      const shown = [0, 1, 2].map((i) => sheet(i).textContent);
      const changed = [0, 1, 2].map((i) => sheet(i).classList.contains("changed"));
      sheet(3).click();  // C: play its first alternative everywhere
      [...document.querySelectorAll("#alts .chip")][1].click();
      q("#use").click();
      const kept = JSON.parse(localStorage.getItem("caracole-viewer:" + location.pathname));
      out = [shown, changed, kept.alt.ionian["3"]];
    """, before=SAVED_ALTERNATIVES)
    assert shown == ["Em", "D", "Em"] and changed == [True, False, False]
    assert isinstance(saved, list) and len(saved) == 3 and saved[0] in range(12)  # root, suffix, bass


@in_chromium
def test_the_card_and_the_settings_take_the_focus_and_give_it_back_and_leave_the_page_in_reach(tmp_path):
    card, panel = run_in_page(build_viewer(UG_CHO), tmp_path, """
      const press = (el, key) => el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
      const visit = (opener, dialog, how) => {
        opener.focus();
        how();
        const seen = [q(dialog).contains(document.activeElement), q(".page").inert, q("#bar").inert,
                      q(dialog).getAttribute("aria-modal")];
        press(document.activeElement, "Escape");
        return seen.concat([q(dialog).hidden, document.activeElement === opener, q(".page").inert]);
      };
      const chord = q('#sheet .c[data-c="1"]');
      out = [visit(chord, "#card", () => press(chord, "Enter")),
             visit(q("#more"), "#panel", () => q("#more").click())];
    """)
    # focus inside, and the page behind within reach: not modal; then closed, focus back
    assert card == [True, False, False, None, True, True, False]
    assert panel == [True, False, False, None, True, True, False]


@in_chromium
def test_a_chord_is_easy_to_tap(tmp_path):
    # WCAG 2.5.8: a target of 24 by 24 CSS px at least; a one-letter chord is about 12 by 20.
    size, box, own, fits = run_in_page(build_viewer(UG_CHO), tmp_path, """
      const tapped = (x, y) => { const t = document.elementFromPoint(x, y); return t && t.closest(".c"); };
      const el = document.querySelectorAll('#sheet .c[data-c="0"]')[1];  // the G over "Tiny"
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const box = [[cx - 12, cy], [cx + 12, cy], [cx, cy - 12], [cx, cy + 12]].map(([x, y]) => tapped(x, y) === el);
      const bar = q("#bar").getBoundingClientRect();
      const inView = [...document.querySelectorAll("#sheet .c")].filter((c) => {
        const b = c.getBoundingClientRect();
        return b.top > 0 && b.bottom < bar.top;
      });
      // a neighbour's larger target never covers a chord's own name
      const own = inView.length > 5 && inView.every((c) => {
        const b = c.getBoundingClientRect();
        return tapped(b.left + b.width / 2, b.top + b.height / 2) === c;
      });
      out = [[Math.round(r.width), Math.round(r.height)], box, own,
             document.documentElement.scrollWidth <= innerWidth];
    """)
    assert size[0] < 24  # the name alone is too small a target...
    assert box == [True] * 4  # ...but a tap 12 px from its centre still reaches it
    assert own and fits  # and the larger targets make the page no wider


@in_chromium
def test_a_capo_stays_on_its_fret_when_the_song_is_transposed(tmp_path):
    # As on a guitar: a semitone up with the capo where it is, and every shape goes up a semitone.
    out = run_in_page(build_viewer(UG_CHO), tmp_path, """
      q("#up").click();
      out = [q('#sheet .c[data-c="0"]').textContent, q("#key-full").textContent, location.hash];
    """, "#t=3&capo=3")  # A shapes with the capo on fret 3, sounding C
    assert out == ["Bb", "Bb shapes · capo 3 · sounds Db · +4", "#t=4&capo=3"]


@in_chromium
def test_tapping_through_the_controls(tmp_path):
    html = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>\n', "", build_viewer(UG_CHO))
    dom = dump_dom(html.replace("</body>", HARNESS + "</body>"), tmp_path)
    result = json.loads(re.search(r'data-result="([^"]*)"', dom).group(1).replace("&quot;", '"'))
    assert result == [
        "G", False,  # the card opens on the chord
        "Em", "Play Em for every G",  # an alternative, tried
        "Em", True,  # and played everywhere, marked as changed
        "E", "F#m", "A shapes · capo 2 · sounds B · +2",  # up two semitones, the alternative too
        "Em", "Am",  # G minor: D becomes Dm, G Gm; still up two
        "G", "D",  # all back as written
    ]


@in_chromium
def test_a_chord_caracole_cant_read_is_left_as_written(tmp_path):
    dom = dump_dom(build_viewer("{title: T}\n{artist: A}\n[G]la [(G)]lo\n"), tmp_path, "#t=2")
    assert chord_texts(dom) == {"0": "A", "1": "(G)"}
