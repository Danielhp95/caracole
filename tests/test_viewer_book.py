"""caracole.viewer.book: songbook.html, a songbook as one page for the phone, in the sheet viewer."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from caracole.chordpro import to_chordpro
from caracole.viewer.book import BookSong, assets_version, build_songbook, songbook_csp

FIXTURES = Path(__file__).parent / "fixtures" / "chordpro"
UG_CHO = (FIXTURES / "ug_sheet.cho").read_text(encoding="utf-8")  # key G, capo 2
MINOR = to_chordpro("[ch]Am[/ch]        [ch]F[/ch]\nTiny minor words\n[ch]C[/ch]       [ch]G[/ch]\nand back home",
                    title="Minor Song", artist="Others", key="Am")
ZH = to_chordpro("[ch]C[/ch]       [ch]G[/ch]\n这是一个合成的例子", title="斑马斑马", artist="宋冬野")

SONGS = [
    BookSong("Synthetic Test Song", "The Placeholders", cho=UG_CHO, id="aaaa"),
    BookSong("Hysteria", "Muse", missing="no sheet yet", id="bbbb"),
    BookSong("Minor Song", "Others", cho=MINOR, key="Am", key_source="tab", transpose=2, id="cccc"),
    BookSong("Removed Song", "Gone Band", missing="not in the library", id="dddd"),
    BookSong("斑马斑马", "宋冬野", cho=ZH, id="eeee"),
]


def page(songs=SONGS, **kwargs) -> str:
    kwargs.setdefault("pdf", "songbook.pdf")
    kwargs.setdefault("cho", "songbook.cho")
    return build_songbook("Campfire", songs, **kwargs)


def data(html: str, n: int) -> dict:
    found = re.search(rf'<script type="application/json" id="data-{n}">(.*?)</script>', html, re.DOTALL)
    assert found, f"no data for song {n}"
    return json.loads(found.group(1))


def contents(html: str) -> str:
    found = re.search(r'<nav class="toc" id="contents"[^>]*>(.*?)</nav>', html, re.DOTALL)
    assert found
    return found.group(1)


def sha(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


# --- the static page -----------------------------------------------------------------------------


def test_the_contents_list_every_song_in_order_and_name_the_missing_ones():
    html = page()
    toc = contents(html)
    titles = re.findall(r'<span class="t">([^<]*)</span>', toc)
    assert titles == ["Synthetic Test Song", "Hysteria", "Minor Song", "Removed Song", "斑马斑马"]
    assert re.findall(r'<a class="row" href="#song-(\d+)"', toc) == ["1", "3", "5"]
    missing = re.findall(r'<li class="missing">(.*?)</li>', toc, re.DOTALL)
    assert len(missing) == 2 and "Missing: no sheet yet" in missing[0] and "Missing: not in the library" in missing[1]
    assert "href" not in "".join(missing)  # nothing to open


def test_each_song_with_a_sheet_has_a_section_and_its_own_data():
    html = page()
    assert re.findall(r'<section class="song" id="song-(\d+)"', html) == ["1", "3", "5"]
    first, minor = data(html, 1), data(html, 3)
    assert first["key"]["tonic"] == 7 and first["capoSheet"] == 2  # G, from the sheet
    assert minor["transpose"] == 2 and minor["key"] == {"tonic": 9, "mode": "aeolian", "from": "from the tab"}
    assert "voicings" not in first  # shared by every song: one copy for the page
    shared = json.loads(re.search(r'<script type="application/json" id="voicings">(.*?)</script>', html, re.DOTALL).group(1))
    assert {"", "m"} <= set(shared)  # major and minor shapes, for every song's chords


def test_each_song_says_where_it_is_and_links_its_neighbours():
    html = page()
    first = re.search(r'<section class="song" id="song-1".*?</section>', html, re.DOTALL).group(0)
    minor = re.search(r'<section class="song" id="song-3".*?</section>', html, re.DOTALL).group(0)
    last = re.search(r'<section class="song" id="song-5".*?</section>', html, re.DOTALL).group(0)
    assert "Song 1 of 5" in first and 'href="#song-3" rel="next"' in first and 'rel="prev"' not in first
    assert 'href="#song-1" rel="prev"' in minor and 'href="#song-5" rel="next"' in minor  # missing ones skipped
    assert 'rel="next"' not in last and 'href="#contents"' in last
    assert 'id="sheet-3"' in minor and 'id="facts-3"' in minor and 'id="strip-3"' in minor
    assert 'lang="zh"' in last


def test_the_pager_is_above_each_sheet_and_after_it_too():
    songs = re.finditer(r'<section class="song" id="song-(\d+)".*?<script type="application/json" id="data-\1">',
                        page(), re.DOTALL)  # a sheet's parts are sections too: up to the song's data
    sections = [m.group(0) for m in songs]
    assert len(sections) == 3
    for section in sections:
        pagers = re.findall(r'<nav class="pager" aria-label="([^"]+)">', section)
        assert len(pagers) == 2 and len(set(pagers)) == 2  # each named, for a screen reader
        assert re.search(r'</article>\n<nav class="pager"', section)  # the end of a long sheet: no scrolling back


def test_the_page_links_the_pdf_and_the_chordpro_file_when_there_are_some():
    html = page()
    assert 'href="songbook.pdf"' in html and 'href="songbook.cho"' in html
    html = page(pdf=None, cho=None)
    assert "songbook.pdf" not in html and "songbook.cho" not in html
    assert 'href="../../index.html"' in html


def test_what_the_songs_say_is_text_never_markup():
    evil = "</script><script>alert(1)</script>"
    cho = to_chordpro("[ch]G[/ch]\n" + evil, title=evil, artist="<b>x</b>")
    html = build_songbook(evil, [BookSong(evil, "<b>x</b>", cho=cho, id="x"), BookSong(evil, "<i>", missing="no sheet yet")])
    assert "<script>alert" not in html and "<b>x</b>" not in html
    for block in re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL):
        assert "<" not in block


def test_the_policy_allows_exactly_its_scripts_and_styles():
    html = page()
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html).group(1)
    scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    styles = re.findall(r"<style>(.*?)</style>", html, re.DOTALL)
    assert len(scripts) == 2 and len(styles) == 2
    assert csp.startswith("default-src 'none'; ") and "unsafe" not in csp
    assert all(sha(s) in csp for s in scripts + styles)
    assert "form-action 'none'" in csp and "base-uri 'none'" in csp
    assert songbook_csp(html.encode("utf-8")) == "sandbox allow-scripts; " + csp  # the policy of those bytes


def test_the_page_loads_nothing_and_credits_the_fingerings():
    html = page()
    shell = re.sub(r'<script type="application/json".*?</script>', "", html, flags=re.DOTALL)
    assert not re.search(r"<(link|img|iframe|object|embed)\b|\bsrc=|@import|url\(", shell, re.IGNORECASE)
    hrefs = re.findall(r'href="([^"]*)"', shell)
    assert [h for h in hrefs if "://" in h] == ["https://github.com/tombatossals/chords-db"]
    assert "MIT License" in html and "Keep this page private" in html


def test_a_songbook_without_a_sheet_is_its_contents():
    html = build_songbook("Campfire", [BookSong("Hysteria", "Muse", missing="no sheet yet")])
    assert '<section class="song"' not in html and "Hysteria" in contents(html)


def test_the_assets_version_changes_with_the_scripts():
    assert re.fullmatch(r"[0-9a-f]{64}", assets_version())


# --- in a real browser ---------------------------------------------------------------------------

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
in_chromium = pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")


def open_page(html: str, tmp_path: Path, fragment: str = "", *, harness: str = "", size: str = "390,844",
              budget: int = 4000) -> str:
    """The DOM of songbook.html in Chromium after its scripts ran. ``harness`` is JavaScript that runs
    on every load, after the page's scripts; ``out`` set there is in the DOM as data-result."""
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    if harness:
        html = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>\n', "", html)
        script = ("<script>\nwindow.addEventListener(\"load\", () => { setTimeout(() => {\n"
                  "const q = (s) => document.querySelector(s);\nlet out;\n" + harness
                  + "\nif (out !== undefined) document.body.dataset.result = JSON.stringify(out);\n}, 50); });\n"
                  "</script>\n")
        html = html.replace("</body>", script + "</body>")
    path.write_text(html, encoding="utf-8")
    profile = tmp_path / f"chrome-{len(list(tmp_path.glob('chrome-*')))}"
    try:
        result = subprocess.run(
            [CHROMIUM, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={profile}", f"--window-size={size}", f"--virtual-time-budget={budget}",
             "--dump-dom", path.as_uri() + fragment],
            capture_output=True, text=True, timeout=90, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        pytest.skip(f"chromium couldn't run: {e}")
    if result.returncode != 0 or "<html" not in result.stdout:
        pytest.skip(f"chromium couldn't run: {result.stderr[-500:]}")
    return result.stdout


def result_of(dom: str):
    found = re.search(r'data-result="([^"]*)"', dom)
    assert found, "the harness didn't run"
    return json.loads(found.group(1).replace("&quot;", '"').replace("&amp;", "&"))


def visible_songs(dom: str) -> list[str]:
    return re.findall(r'<section class="song" id="song-(\d+)"(?![^>]*hidden)[^>]*>', dom)


def chords_of(dom: str) -> list[str]:
    sheet = re.search(r'<article[^>]*id="sheet"[^>]*>(.*?)</article>', dom, re.DOTALL)
    assert sheet, "no song open"
    return re.findall(r'<b class="c[^"]*" data-c="\d+"[^>]*>([^<]*)</b>', sheet.group(1))


@in_chromium
def test_the_page_opens_on_its_contents(tmp_path):
    dom = open_page(page(), tmp_path)
    assert 'data-view="contents"' in dom
    assert visible_songs(dom) == []
    assert re.search(r'<nav class="toc" id="contents"(?![^>]*hidden)', dom)


@in_chromium
def test_the_song_in_the_address_opens_whatever_else_the_address_keeps(tmp_path):
    # The viewer may keep its settings in the address as parameters (#song-3=&t=1, as URLSearchParams
    # writes a song's name back), where a sandbox gives it no storage.
    for fragment in ("#song-3=&t=1", "#song-3&mode=dorian"):
        dom = open_page(page(), tmp_path, fragment)
        assert 'data-view="song"' in dom and visible_songs(dom) == ["3"], fragment


@in_chromium
def test_a_song_opens_alone_in_the_viewer_in_its_own_key(tmp_path):
    dom = open_page(page(), tmp_path, "#song-3")
    assert 'data-view="song"' in dom and 'data-ready="1"' in dom  # the viewer ran, on this song
    assert visible_songs(dom) == ["3"]
    assert re.search(r'<nav class="toc" id="contents"[^>]*hidden', dom)
    assert chords_of(dom)[:4] == ["Bm", "G", "D", "A"]  # Am, F, C, G up 2: its [transpose]
    assert re.search(r'id="fab"[^>]*>Key Bm · \+2</button>', dom)
    assert "<title>Minor Song · Campfire</title>" in dom


@in_chromium
def test_a_songs_made_up_flat_five_chord_is_written_as_its_viewer_writes_it(tmp_path):
    # C minor's G in phrygian is G, B and D-flat: "G(b5)" in the songbook as in sheet.html, never "Gb5".
    dark = to_chordpro("[ch]Cm[/ch]        [ch]G[/ch]\nSynthetic dark words", title="Dark Song", artist="Others",
                       key="Cm")
    harness = """
      const chip = (box, text) => [...document.querySelectorAll(box + " .chip")]
        .find((b) => b.firstChild.textContent === text);
      const g = () => q('#sheet .c[data-c="1"]').textContent;
      const before = g();
      q("#fab").click();
      chip("#modes", "Phrygian").click();
      const shown = g();
      q('#sheet .c[data-c="1"]').click();  // its chord box
      out = [before, shown, q("#card-name").textContent];
    """
    dom = open_page(page([BookSong("Dark Song", "Others", cho=dark, key="Cm", key_source="tab", id="ffff")]),
                    tmp_path, "#song-1", harness=harness)
    assert result_of(dom) == ["G", "G(b5)", "G(b5)"]  # on the sheet, then in its chord box


@in_chromium
def test_next_and_swipes_go_from_song_to_song_skipping_the_missing(tmp_path):
    harness = """
      const step = Number(sessionStorage.getItem("step") || "0");
      sessionStorage.setItem("step", String(step + 1));
      const swipe = (dx) => {
        const at = (x) => [new Touch({identifier: 1, target: document.body, clientX: x, clientY: 300})];
        document.body.dispatchEvent(new TouchEvent("touchstart", {touches: at(300), changedTouches: at(300), bubbles: true}));
        document.body.dispatchEvent(new TouchEvent("touchend", {touches: [], changedTouches: at(300 + dx), bubbles: true}));
      };
      const shown = Array.from(document.querySelectorAll("section.song")).filter((s) => !s.hidden).map((s) => s.id);
      const seen = JSON.parse(sessionStorage.getItem("seen") || "[]");
      seen.push(shown.join(","));
      sessionStorage.setItem("seen", JSON.stringify(seen));
      if (step === 0) q('#song-1 a[rel="next"]').click();
      else if (step === 1) swipe(-160);
      else if (step === 2) swipe(160);
      else if (step === 3) document.dispatchEvent(new KeyboardEvent("keydown", {key: "ArrowLeft", bubbles: true}));
      else out = seen;
    """
    dom = open_page(page(), tmp_path, "#song-1", harness=harness, budget=12000)
    assert result_of(dom) == ["song-1", "song-3", "song-5", "song-3", "song-1"]


@in_chromium
def test_the_page_remembers_the_song_and_each_songs_own_settings(tmp_path):
    harness = """
      const step = Number(sessionStorage.getItem("step") || "0");
      sessionStorage.setItem("step", String(step + 1));
      const fab = () => q("#fab") ? q("#fab").textContent : "";
      const log = (value) => {
        const seen = JSON.parse(sessionStorage.getItem("seen") || "[]");
        seen.push(value);
        sessionStorage.setItem("seen", JSON.stringify(seen));
      };
      if (step === 0) {  // song 3: up a semitone more, then song 1
        q("#up").click();
        log(fab());
        location.hash = "song-1";
      } else if (step === 1) {  // song 1 keeps its own settings; back to song 3
        log(fab());
        location.hash = "song-3";
      } else if (step === 2) {  // song 3 as you left it; then the contents
        log(fab());
        location.hash = "contents";
      } else if (step === 3) {  // the contents show where you were; then the page with no address
        log(q(".toc .here") ? q(".toc .here").textContent : "");
        location.hash = "";
      } else {
        log(Array.from(document.querySelectorAll("section.song")).filter((s) => !s.hidden).map((s) => s.id));
        out = JSON.parse(sessionStorage.getItem("seen"));
      }
    """
    dom = open_page(page(), tmp_path, "#song-3", harness=harness, budget=15000)
    three, one, again, here, shown = result_of(dom)
    assert three == "Key Cm · +3" and one == "Key G" and again == "Key Cm · +3"
    assert "Minor Song" in here
    assert shown == ["song-3"]


@in_chromium
def test_the_song_the_page_reopens_is_in_its_address_so_a_reload_keeps_it(tmp_path):
    # Opened with no address, the page reopens the song you had open; the viewer then keeps that song's
    # settings in the address as well as in storage, so the address must name the song, or a reload
    # after a change finds only the settings ("#t=3") and opens the contents.
    harness = """
      const step = Number(sessionStorage.getItem("step") || "0");
      sessionStorage.setItem("step", String(step + 1));
      const log = (value) => {
        const seen = JSON.parse(sessionStorage.getItem("seen") || "[]");
        seen.push(value);
        sessionStorage.setItem("seen", JSON.stringify(seen));
      };
      const shown = () => Array.from(document.querySelectorAll("section.song")).filter((s) => !s.hidden)
        .map((s) => s.id).join(",");
      if (step === 0) {  // song 3; then the page with no address
        location.hash = "";
      } else if (step === 1) {  // song 3 again, named in the address; up a semitone, and reload
        log([shown(), location.hash]);
        q("#up").click();
        log(location.hash);
        location.reload();
      } else {
        log([shown(), q("#fab") ? q("#fab").textContent : ""]);
        out = JSON.parse(sessionStorage.getItem("seen"));
      }
    """
    dom = open_page(page(), tmp_path, "#song-3", harness=harness, budget=12000)
    reopened, changed, reloaded = result_of(dom)
    assert reopened[0] == "song-3" and reopened[1].startswith("#song-3")
    assert changed == "#song-3=&t=3"
    assert reloaded == ["song-3", "Key Cm · +3"]


@in_chromium
def test_the_files_are_linked_once_wherever_you_are(tmp_path):
    harness = """
      const shown = (s) => Array.from(document.querySelectorAll(s)).filter((el) => el.offsetParent !== null).length;
      out = [shown(".toc .files a"), shown(".foot a.pdf"), shown("section.song nav.pager")];
    """
    assert result_of(open_page(page(), tmp_path, harness=harness)) == [2, 0, 0]  # the contents' own, alone
    assert result_of(open_page(page(), tmp_path, "#song-3", harness=harness)) == [0, 2, 2]  # at the sheet's end


@in_chromium
def test_the_page_fits_a_phone(tmp_path):
    harness = "out = [document.documentElement.scrollWidth, window.innerWidth];"
    for fragment in ("", "#song-1", "#song-5"):
        width, screen = result_of(open_page(page(), tmp_path, fragment, harness=harness, size="360,740"))
        assert width <= screen, fragment
