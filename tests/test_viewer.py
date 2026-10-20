"""caracole.viewer: sheet.html, the phone-friendly page beside each sheet's PDF."""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from caracole.chordpro import to_chordpro
from caracole.viewer import build_viewer, info_key, key_heard, viewer_csp
from caracole.viewer.voicings import load_voicings

FIXTURES = Path(__file__).parent / "fixtures" / "chordpro"
UG_CHO = (FIXTURES / "ug_sheet.cho").read_text(encoding="utf-8")
MINOR = to_chordpro(
    "[ch]Cm[/ch]      [ch]Ab[/ch]\nTiny minor words\n[ch]Bb[/ch]     [ch]G7[/ch]\nand back home",
    title="Minor", artist="Placeholders", key="Cm",
)


def data_of(html: str) -> dict:
    found = re.search(r'<script type="application/json" id="song">(.*?)</script>', html, re.S)
    assert found, "no song data"
    return json.loads(found.group(1))


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

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
in_chromium = pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")


def dump_dom(html: str, tmp_path: Path, fragment: str = "") -> str:
    """The page's DOM after its script ran; skips the test when this machine can't run Chromium.

    Each call has a profile of its own, so nothing a page kept in localStorage carries over."""
    page = tmp_path / "Artist" / "Title" / "sheet.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(html, encoding="utf-8")
    return dump_url(page.as_uri() + fragment, tmp_path)


def dump_url(url: str, tmp_path: Path) -> str:
    """The DOM of the page at ``url`` after its script ran, in Chromium (see dump_dom)."""
    profile = tmp_path / f"chrome-{len(list(tmp_path.glob('chrome-*')))}"
    try:
        result = subprocess.run(
            [CHROMIUM, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={profile}", "--window-size=390,844", "--virtual-time-budget=3000",
             "--dump-dom", url],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        pytest.skip(f"chromium couldn't run: {e}")
    if result.returncode != 0 or "<html" not in result.stdout:
        pytest.skip(f"chromium couldn't run: {result.stderr[-500:]}")
    return result.stdout


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
    assert re.search(r'id="fab"[^>]*>Key G</button>', dom)


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
    threading.Thread(target=server.serve_forever, daemon=True).start()
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
    assert "Key <b>A</b> (+2)" in dom
    dom = dump_dom(build_viewer(UG_CHO), tmp_path, "#t=-4")  # down to Eb: flats
    assert chord_texts(dom)["2"] == "Cm" and chord_texts(dom)["0"] == "Eb"


@in_chromium
def test_a_capo_shows_the_shapes_to_play(tmp_path):
    dom = dump_dom(build_viewer(UG_CHO), tmp_path, "#t=3&capo=3")  # Bb shapes; capo 3: A shapes
    assert chord_texts(dom)["0"] == "A"
    assert "Capo <b>3</b>, A shapes" in dom


@in_chromium
def test_a_capo_may_come_off(tmp_path):
    out = run_in_page(build_viewer(UG_CHO), tmp_path, """
      const chips = [...document.querySelectorAll("#capo .chip")].map((b) => b.textContent);
      [...document.querySelectorAll("#capo .chip")][0].click();
      out = [chips, q('#sheet .c[data-c="0"]').textContent, q("#facts").textContent];
    """, "#t=-2")  # G shapes with capo 2, down two: F shapes, sounding G
    chips, chord, facts = out
    assert chips == ["No capoG shapes", "Capo 3E shapes"]
    assert chord == "G" and "No capo, G shapes" in facts


@in_chromium
def test_a_mode_change_moves_the_chords(tmp_path):
    dom = dump_dom(build_viewer(MINOR), tmp_path, "#mode=ionian")
    assert chord_texts(dom) == {"0": "C", "1": "Am", "2": "Bdim", "3": "G7"}


@in_chromium
def test_tapping_a_chord_shows_its_shapes_and_alternatives(tmp_path):
    dom = dump_dom(build_viewer(UG_CHO), tmp_path, "#chord=0")
    card = re.search(r'<section class="sheet-ui card" id="card"([^>]*)>(.*?)</section>', dom, re.S)
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
  q("#scrim").click();
  q("#fab").click();
  q("#up").click();
  q("#up").click();
  out.push(q('#sheet .c[data-c="1"]').textContent, g.textContent, q("#fab").textContent);
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
      q("#fab").click();
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
def test_the_card_and_the_settings_take_the_focus_and_give_it_back(tmp_path):
    card, panel = run_in_page(build_viewer(UG_CHO), tmp_path, """
      const press = (el, key) => el.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
      const visit = (opener, dialog, how) => {
        opener.focus();
        how();
        const seen = [q(dialog).contains(document.activeElement), q(".page").inert, q("#fab").inert,
                      q(dialog).getAttribute("aria-modal")];
        press(document.activeElement, "Escape");
        return seen.concat([q(dialog).hidden, document.activeElement === opener, q(".page").inert]);
      };
      const chord = q('#sheet .c[data-c="1"]');
      out = [visit(chord, "#card", () => press(chord, "Enter")),
             visit(q("#fab"), "#panel", () => q("#fab").click())];
    """)
    # focus inside, the page behind out of reach, a modal dialog; then closed, focus back, page back
    assert card == [True, True, True, "true", True, True, False]
    assert panel == [True, True, True, "true", True, True, False]


@in_chromium
def test_a_chord_is_easy_to_tap(tmp_path):
    # WCAG 2.5.8: a target of 24 by 24 CSS px at least; a one-letter chord is about 12 by 20.
    size, box, own, fits = run_in_page(build_viewer(UG_CHO), tmp_path, """
      const tapped = (x, y) => { const t = document.elementFromPoint(x, y); return t && t.closest(".c"); };
      const el = document.querySelectorAll('#sheet .c[data-c="0"]')[1];  // the G over "Tiny"
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const box = [[cx - 12, cy], [cx + 12, cy], [cx, cy - 12], [cx, cy + 12]].map(([x, y]) => tapped(x, y) === el);
      const fab = q("#fab").getBoundingClientRect();
      const inView = [...document.querySelectorAll("#sheet .c")].filter((c) => {
        const b = c.getBoundingClientRect();
        return b.top > 0 && b.bottom < innerHeight && !(b.right > fab.left && b.bottom > fab.top);
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
def test_a_capo_no_longer_on_offer_goes_before_the_chords_are_named(tmp_path):
    out = run_in_page(build_viewer(UG_CHO), tmp_path, """
      q("#up").click();  // Bb to B: capo 3, with A shapes, is no longer offered
      out = [q('#sheet .c[data-c="0"]').textContent, q("#facts").textContent, q("#fab").textContent];
    """, "#t=3&capo=3")
    chord, facts, fab = out
    assert chord == "B" and "A shapes" not in facts and fab == "Key B · +4"


@in_chromium
def test_tapping_through_the_controls(tmp_path):
    html = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>\n', "", build_viewer(UG_CHO))
    dom = dump_dom(html.replace("</body>", HARNESS + "</body>"), tmp_path)
    result = json.loads(re.search(r'data-result="([^"]*)"', dom).group(1).replace("&quot;", '"'))
    assert result == [
        "G", False,  # the card opens on the chord
        "Em", "Play Em for every G",  # an alternative, tried
        "Em", True,  # and played everywhere, marked as changed
        "E", "F#m", "Key A · +2",  # up two semitones, the alternative too
        "Em", "Am",  # G minor: D becomes Dm, G Gm; still up two
        "G", "D",  # all back as written
    ]


@in_chromium
def test_a_sheet_without_chords_has_no_key_button(tmp_path):
    dom = dump_dom(build_viewer("{title: T}\n{artist: A}\nOnly words\n"), tmp_path)
    assert 'data-ready="1"' in dom and re.search(r'id="fab"[^>]*hidden', dom)


@in_chromium
def test_a_chord_caracole_cant_read_is_left_as_written(tmp_path):
    dom = dump_dom(build_viewer("{title: T}\n{artist: A}\n[G]la [(G)]lo\n"), tmp_path, "#t=2")
    assert chord_texts(dom) == {"0": "A", "1": "(G)"}
