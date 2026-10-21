"""caracole.viewer.book: songbook.html, a songbook as one page for the phone, in the sheet viewer."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from conftest import subprocess_pythonpath
from helpers import browser
from helpers.browser import Browser, in_chromium

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


def test_each_song_says_what_its_capo_means_as_its_sheet_html_does():
    html = page()
    first = re.search(r'<p class="facts" id="facts-1">(.*?)</p>', html).group(1)
    minor = re.search(r'<p class="facts" id="facts-3">(.*?)</p>', html).group(1)
    assert first == '<b>G</b> shapes · capo <b>2</b> · sounds <b>A</b> · <span class="from">key from the sheet</span>'
    assert minor == 'Key <b>Am</b> <span class="from">from the tab</span>'


def test_the_pager_is_above_each_sheet_and_after_it_too():
    songs = re.finditer(r'<section class="song" id="song-(\d+)".*?<script type="application/json" id="data-\1">',
                        page(), re.DOTALL)  # a sheet's parts are sections too: up to the song's data
    sections = [m.group(0) for m in songs]
    assert len(sections) == 3
    for section in sections:
        pagers = re.findall(r'<nav class="pager" aria-label="([^"]+)">', section)
        assert len(pagers) == 2 and len(set(pagers)) == 2  # each named, for a screen reader
        assert re.search(r'</article>\n<nav class="pager"', section)  # the end of a long sheet: no scrolling back


def section(html: str, n: int) -> str:
    found = re.search(rf'<section class="song" id="song-{n}".*?<script type="application/json" id="data-{n}">',
                      html, re.DOTALL)
    assert found, f"no section for song {n}"
    return found.group(0)


def seen(markup: str) -> str:
    """The text a reader sees: without what only a screen reader hears (``.vh``)."""
    return re.sub(r"<[^>]+>", "", re.sub(r'<span class="vh">[^<]*</span>', "", markup))


def heard(markup: str) -> str:
    """The text a screen reader reads out: without what is hidden from it (``aria-hidden``)."""
    return re.sub(r"<[^>]+>", "", re.sub(r'<span[^>]*aria-hidden="true"[^>]*>[^<]*</span>', "", markup))


def pager_links(pager: str) -> dict[str, str]:
    return dict((rel, inner) for rel, inner in re.findall(r'<a href="#song-\d+" rel="(prev|next)"[^>]*>(.*?)</a>', pager))


def test_the_pager_names_the_song_before_and_the_song_after():
    html = page()
    for n, before, after in ((1, None, "Minor Song"), (3, "Synthetic Test Song", "斑马斑马"), (5, "Minor Song", None)):
        pagers = re.findall(r'<nav class="pager"[^>]*>.*?</nav>', section(html, n), re.DOTALL)
        assert len(pagers) == 2
        for pager in pagers:  # above the sheet and after it, the same
            links = pager_links(pager)
            if before is None:
                assert "prev" not in links
            else:  # missing songs skipped
                assert seen(links["prev"]) == f"‹ {before}" and heard(links["prev"]) == f"Previous: {before}"
            if after is None:
                assert "next" not in links
            else:
                assert seen(links["next"]) == f"Next: {after} ›" and heard(links["next"]) == f"Next: {after}"
            assert seen(re.search(r'<a href="#contents"[^>]*>(.*?)</a>', pager).group(1)) == "Contents"


def toc_rows(html: str) -> list[str]:
    """Each row of the contents as a reader sees it, its parts apart: number, title, the line under it."""
    rows = re.findall(r"<li[^>]*>(.*?)</li>", contents(html), re.DOTALL)
    return [" | ".join(seen(part) for part in re.findall(r'<span class="(?:n|t|a|why)">(.*?)</span>(?=<span|</a>|</span>)',
                                                       row)) for row in rows]


def test_the_contents_give_each_songs_key_and_capo_under_its_title():
    html = page()
    assert toc_rows(html) == [
        "1 | Synthetic Test Song | The Placeholders · G · capo 2",  # its sheet's key and capo
        "2 | Hysteria | Muse | Missing: no sheet yet",
        "3 | Minor Song | Others · Bm",  # in Am, up 2: its [transpose], the key the viewer opens it in
        "4 | Removed Song | Gone Band | Missing: not in the library",
        "5 | 斑马斑马 | 宋冬野 · C",  # estimated from its chords
    ]
    first = re.search(r'<span class="a">(.*?)</span>(?=</a>)', contents(html)).group(1)
    assert heard(first) == "The Placeholders · key G · capo 2"  # what "G" is, for a screen reader
    alone = build_songbook("Campfire", [BookSong("Untitled", "", cho=MINOR, key="Am", key_source="tab", id="a")])
    assert toc_rows(alone) == ["1 | Untitled | Am"]  # no artist: the key alone


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


def test_the_assets_version_changes_with_the_scripts(monkeypatch, tmp_path):
    from caracole.viewer import book, page

    version = assets_version()
    assert re.fullmatch(r"[0-9a-f]{64}", version)
    copies = []
    for path in book.BOOK_FILES:
        copies.append(tmp_path / path.name)
        copies[-1].write_bytes(path.read_bytes())
    monkeypatch.setattr(book, "BOOK_FILES", tuple(copies))
    assert assets_version() == version
    seen = {version}
    for copy in copies:  # book.py, its script, its stylesheet
        copy.write_bytes(copy.read_bytes() + b"\n")
        seen.add(assets_version())
    monkeypatch.setattr(page, "build_version", lambda: "a newer viewer")  # the sheet viewer's own
    seen.add(assets_version())
    assert len(seen) == len(copies) + 2


@pytest.mark.slow
def test_the_assets_version_covers_every_module_and_file_the_pages_are_made_from():
    # A module the pages come to import, or a file of the viewer's they come to read, that the
    # versions leave out would leave every songbook.html as an older caracole made it.
    code = textwrap.dedent("""\
        import json, sys
        from caracole.viewer import book, build_viewer, page

        cho = "{title: 斑马}\\n{artist: A}\\n{key: Am}\\n[Am]la la [F]la\\n"
        build_viewer(cho, key="Am", key_source="tab", pdf="sheet.pdf")
        songs = [book.BookSong("斑马", "A", cho=cho, key="Am", key_source="tab"),
                 book.BookSong("Gone", "A", missing="no sheet yet")]
        book.build_songbook("B", songs, pdf="b.pdf", cho="b.cho")
        loaded = [m.__file__ for name, m in list(sys.modules.items())
                  if name.partition(".")[0] == "caracole" and getattr(m, "__file__", None)]
        hashed = [str(p) for p in (*page.BUILD_FILES, *book.BOOK_FILES)]
        print(json.dumps({"loaded": loaded, "hashed": hashed, "viewer": str(page.HERE)}))
    """)
    src = Path(__file__).resolve().parents[1] / "src"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": subprocess_pythonpath(src)})
    found = json.loads(out.stdout)
    hashed = {Path(p).resolve() for p in found["hashed"]}
    modules = {Path(f).resolve() for f in found["loaded"] if Path(f).name != "__init__.py"}
    viewer = {p.resolve() for p in Path(found["viewer"]).iterdir()
              if p.is_file() and p.name != "__init__.py" and p.suffix != ".pyc"}
    assert modules - hashed == set()
    assert viewer - hashed == set()
    assert len(hashed) == len(found["hashed"])  # each once


# --- in a real browser ---------------------------------------------------------------------------

def open_page(html: str, tmp_path: Path, fragment: str = "", *, harness: str = "", size: str = "390,844",
              budget: int = 4000) -> str:
    """The DOM of songbook.html in Chromium after its scripts ran, in a browser context of its own
    (helpers/browser.py). ``harness`` is JavaScript that runs on every load, after the page's
    scripts; ``out`` set there is in the DOM as data-result."""
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
    width, height = (int(n) for n in size.split(","))
    return browser.dump_dom(path.as_uri() + fragment, (width, height), budget_ms=budget)


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
def test_the_address_keeps_a_songs_text_size(tmp_path):
    # Served, the page has no storage: the song's text size is in its address, as its key is.
    harness = 'out = [getComputedStyle(q("#sheet")).fontSize, location.hash];'
    assert result_of(open_page(page(), tmp_path, "#song-3=&fs=22", harness=harness)) == ["22px", "#song-3=&fs=22"]


@in_chromium
def test_a_song_opens_alone_in_the_viewer_in_its_own_key(tmp_path):
    dom = open_page(page(), tmp_path, "#song-3")
    assert 'data-view="song"' in dom and 'data-ready="1"' in dom  # the viewer ran, on this song
    assert visible_songs(dom) == ["3"]
    assert re.search(r'<nav class="toc" id="contents"[^>]*hidden', dom)
    assert chords_of(dom)[:4] == ["Bm", "G", "D", "A"]  # Am, F, C, G up 2: its [transpose]
    assert '<span class="vh" id="key-full">Key Bm · +2</span>' in dom
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
      q("#more").click();
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
      const said = () => q("#key-full") ? q("#key-full").textContent : "";
      const log = (value) => {
        const seen = JSON.parse(sessionStorage.getItem("seen") || "[]");
        seen.push(value);
        sessionStorage.setItem("seen", JSON.stringify(seen));
      };
      if (step === 0) {  // song 3: up a semitone more, then song 1
        q("#t-up").click();
        log(said());
        location.hash = "song-1";
      } else if (step === 1) {  // song 1 keeps its own settings; back to song 3
        log(said());
        location.hash = "song-3";
      } else if (step === 2) {  // song 3 as you left it; then the contents
        log(said());
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
    assert three == "Key Cm · +3" and one == "G shapes · capo 2 · sounds A" and again == "Key Cm · +3"
    assert "Minor Song" in here
    assert shown == ["song-3"]


@in_chromium
def test_each_song_keeps_its_own_text_size_and_scroll_speed(tmp_path):
    harness = """
      const step = Number(sessionStorage.getItem("step") || "0");
      sessionStorage.setItem("step", String(step + 1));
      const log = (value) => {
        const seen = JSON.parse(sessionStorage.getItem("seen") || "[]");
        seen.push(value);
        sessionStorage.setItem("seen", JSON.stringify(seen));
      };
      const now = () => [q("#pill-speed").textContent, getComputedStyle(q("#sheet")).fontSize, location.hash];
      if (step === 0) {  // song 3: bigger, and faster; then song 1
        q("#size").click();
        q("#bigger").click();
        q("#scroll").click();
        q("#pill-faster").click();
        q("#pill-end").click();
        log(now());
        location.hash = "song-1";
      } else if (step === 1) {  // song 1 as it was; back to song 3
        log(now());
        location.hash = "song-3";
      } else {
        log(now());
        out = JSON.parse(sessionStorage.getItem("seen"));
      }
    """
    dom = open_page(page(), tmp_path, "#song-3", harness=harness, budget=12000)
    three, one, again = result_of(dom)
    assert three == ["7", "20px", "#song-3=&fs=20&speed=7"]
    assert one[:2] == ["6", "18px"] and "fs=" not in one[2] and "speed=" not in one[2]
    assert again == three


@in_chromium
def test_a_song_in_the_songbook_scrolls_by_itself_too(tmp_path):
    path = tmp_path / "Library" / "_songbooks" / "Campfire" / "songbook.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page(), encoding="utf-8")
    with Browser(tmp_path / "profile", width=390, height=640, mobile=True) as b:
        b.open(path.as_uri() + "#song-1&speed=20")
        assert b.wait("document.documentElement.dataset.ready === '1'")
        b.click("#scroll")
        b.click("#go")
        label = b.js("document.querySelector('#go').getAttribute('aria-label')")
        assert b.wait("scrollY > 20", 5)
        shown = b.js("location.hash.startsWith('#song-1') && !document.querySelector('#pill').hidden")
    assert label == "Pause" and shown


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
        log([shown(), q("#key-full") ? q("#key-full").textContent : ""]);
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


LONG = [
    BookSong("A Synthetic Song Whose Title Goes On and On", "The Placeholders", cho=MINOR, id="aaaa"),
    BookSong("Short", "Others", cho=MINOR, id="bbbb"),
    BookSong("Another Made-up Song With a Very Long Name", "Others", cho=MINOR, id="cccc"),
]
MEDIUM = [BookSong("A Synthetic Song With a Long Name", "The Placeholders", cho=MINOR, id="aaaa"), LONG[1],
          BookSong("A Song of Some Length", "Others", cho=MINOR, id="dddd")]
# Where each part of the song's two pagers is (above the sheet, then after it): the links, their names and arrows.
PAGERS = """
  const box = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return [r.left, r.top, r.right, r.bottom];
  };
  const vis = (el) => {  // what a reader sees: not what a screen reader alone hears
    const copy = el.cloneNode(true);
    copy.querySelectorAll(".vh").forEach((v) => v.remove());
    return copy.textContent.replace(/\\s+/g, " ").trim();
  };
  out = {
    window: innerWidth, page: document.documentElement.scrollWidth,
    pagers: [...document.querySelectorAll("section.song:not([hidden]) nav.pager")].map((nav) => {
      const link = (sel) => {
        const a = nav.querySelector(sel);
        if (!a) return null;
        const name = a.querySelector(".name");
        return {box: box(a), text: vis(a), arrow: box(a.querySelector('[aria-hidden="true"]')),
                name: name ? name.clientWidth : null, cut: name ? name.scrollWidth > name.clientWidth : null,
                ellipsis: name ? getComputedStyle(name).textOverflow : null};
      };
      return {box: box(nav), prev: link('a[rel="prev"]'), toc: link('a[href="#contents"]'), next: link('a[rel="next"]')};
    }),
  };
"""


def inside(inner, outer) -> bool:
    return inner[0] >= outer[0] - 0.5 and inner[2] <= outer[2] + 0.5


def a_tap(link) -> bool:
    return link["box"][3] - link["box"][1] >= 44 and link["box"][2] - link["box"][0] >= 44


@in_chromium
def test_on_a_phone_the_pager_names_fit_cut_short_and_next_has_a_row_after_the_sheet(tmp_path):
    phone = result_of(open_page(page(LONG), tmp_path, "#song-2", harness=PAGERS, size="390,844"))
    assert phone["page"] <= phone["window"], phone  # no sideways scroll
    top, end = phone["pagers"]
    for pager in (top, end):
        prev, toc, nxt = pager["prev"], pager["toc"], pager["next"]
        assert all(a_tap(link) for link in (prev, toc, nxt)), pager
        assert prev["box"][0] >= 0 and nxt["box"][2] <= phone["window"], pager
        for link in (prev, nxt):
            assert link["cut"] and link["ellipsis"] == "ellipsis", link  # the title shortened, with "…"
            assert inside(link["arrow"], link["box"]), link  # and its arrow in sight
        assert prev["text"].startswith("‹ A Synthetic") and nxt["text"].startswith("Next: Another"), pager
        assert prev["box"][2] <= toc["box"][0], pager  # side by side, apart
    # Above the sheet, one row: "Next:" over the title, which keeps its side's width.
    assert top["toc"]["box"][2] <= top["next"]["box"][0] and top["next"]["box"][1] < top["toc"]["box"][3], top
    assert top["next"]["name"] >= 80, top
    # After it, the next song on a row of its own, as wide as the page.
    assert end["next"]["box"][1] >= max(end["prev"]["box"][3], end["toc"]["box"][3]), end
    assert end["next"]["box"][2] - end["next"]["box"][0] >= 0.95 * (end["box"][2] - end["box"][0]), end
    medium = result_of(open_page(page(MEDIUM), tmp_path, "#song-2", harness=PAGERS, size="390,844"))
    assert medium["pagers"][1]["next"]["text"] == "Next: A Song of Some Length ›", medium
    assert not medium["pagers"][1]["next"]["cut"], medium  # whole there


EDGES = [LONG[1], LONG[2], LONG[0]]  # "Short", then two long titles: the first song's Next and the last's Previous


@in_chromium
def test_on_a_phone_the_first_songs_next_and_the_last_songs_previous_take_the_empty_side(tmp_path):
    first = result_of(open_page(page(EDGES), tmp_path, "#song-1", harness=PAGERS, size="390,844"))
    last = result_of(open_page(page(EDGES), tmp_path, "#song-3", harness=PAGERS, size="390,844"))
    for seen, there, gone in ((first, "next", "prev"), (last, "prev", "next")):
        assert seen["page"] <= seen["window"], seen  # no sideways scroll
        top = seen["pagers"][0]
        link, toc = top[there], top["toc"]
        assert top[gone] is None and a_tap(link) and a_tap(toc), top
        assert inside(link["box"], top["box"]) and inside(toc["box"], top["box"]), top
        # side by side, the link with the room the song it hasn't would have had: some 25 characters of a title
        assert (toc["box"][2] <= link["box"][0]) if there == "next" else (link["box"][2] <= toc["box"][0]), top
        assert link["name"] >= 180 and inside(link["arrow"], link["box"]), top


@in_chromium
def test_on_a_desktop_the_pager_names_show_whole_in_one_row(tmp_path):
    desk = result_of(open_page(page(MEDIUM), tmp_path, "#song-2", harness=PAGERS, size="1280,800"))
    assert len(desk["pagers"]) == 2
    for pager in desk["pagers"]:
        prev, toc, nxt = pager["prev"], pager["toc"], pager["next"]
        assert prev["text"] == "‹ A Synthetic Song With a Long Name" and not prev["cut"], pager
        assert nxt["text"] == "Next: A Song of Some Length ›" and not nxt["cut"], pager
        assert prev["box"][2] <= toc["box"][0] and toc["box"][2] <= nxt["box"][0], pager  # one row
        assert abs((toc["box"][0] + toc["box"][2]) / 2 - (pager["box"][0] + pager["box"][2]) / 2) <= 1, pager  # centred


@in_chromium
def test_the_contents_line_under_each_title_gives_its_key_and_capo(tmp_path):
    harness = """
      const vis = (el) => {
        const copy = el.cloneNode(true);
        copy.querySelectorAll(".vh").forEach((v) => v.remove());
        return copy.textContent;
      };
      out = [...document.querySelectorAll(".toc li")].map((li) => {
        const top = (sel) => li.querySelector(sel).getBoundingClientRect();
        return {t: [top(".t").top, top(".t").bottom], a: [top(".a").top, top(".a").bottom],
                row: top(".row").height, text: vis(li.querySelector(".a"))};
      }).concat([document.documentElement.scrollWidth <= innerWidth]);
    """
    *rows, fits = result_of(open_page(page(), tmp_path, harness=harness, size="390,844"))
    assert fits
    assert [r["text"] for r in rows] == ["The Placeholders · G · capo 2", "Muse", "Others · Bm", "Gone Band", "宋冬野 · C"]
    for row in rows:
        assert row["a"][0] >= row["t"][1] - 1, row  # a line of its own, under the title
        assert row["row"] >= 44, row


@in_chromium
def test_the_page_fits_a_phone(tmp_path):
    harness = "out = [document.documentElement.scrollWidth, window.innerWidth];"
    for fragment in ("", "#song-1", "#song-5"):
        width, screen = result_of(open_page(page(), tmp_path, fragment, harness=harness, size="360,740"))
        assert width <= screen, fragment
