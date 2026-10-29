"""index.html's songbooks: the Songbooks tab's data, and the Select mode that makes one."""

from __future__ import annotations

import base64
import hashlib
import html as html_module
import json
import re
import shlex
from datetime import UTC, datetime
from pathlib import Path

import pytest

from caracole.library_page import WebControls, build_library_page, write_library_page
from caracole.overrides import Overrides
from caracole.songbook import make_songbook, render_songbooks, songbooks_file
from conftest import add_song
from helpers import browser
from helpers.browser import in_chromium
from helpers.songbooks import FakeChordPro, keep_sheet, render_sheets

NOW = datetime(2026, 10, 18, 3, 41, tzinfo=UTC)


def page(conn, cfg, controls=None) -> str:
    return build_library_page(conn, cfg, Overrides(), NOW, controls=controls)


def data_of(html: str) -> dict:
    return json.loads(re.search(r'<script type="application/json" id="songs">(.*?)</script>', html, re.S).group(1))


@pytest.fixture
def library(conn, cfg):
    """Three songs (two with sheets) and a songbook of them, rendered: Creep, Hysteria, De Música Ligera."""
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    keep_sheet(conn, cfg, soda, tab_id=1)
    creep = add_song(conn, "Radiohead", "Creep")
    keep_sheet(conn, cfg, creep, tab_id=2)
    add_song(conn, "Muse", "Hysteria")
    render_sheets(conn, cfg)
    make_songbook(songbooks_file(cfg.library_dir), "Campfire",
                  ["Radiohead - Creep", "Muse - Hysteria", "Soda Stereo - De Música Ligera"])
    render_songbooks(conn, cfg, Overrides(), runner=FakeChordPro())
    return conn, cfg


# --- the Songbooks tab's data ---------------------------------------------------------------------


def books_of(html: str) -> list[dict]:
    return data_of(html)["songbooks"]["books"]


def test_each_songbook_is_data_with_its_songs_and_its_files(library):
    conn, cfg = library
    [book] = books_of(page(conn, cfg))
    assert (book["name"], book["songs"], book["missing"]) == ("Campfire", 3, 1)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", book["changed"])  # the day caracole last made its files
    assert [(f["label"], f["href"]) for f in book["files"]] == [
        ("PDF", "_songbooks/Campfire/songbook.pdf"), ("Phone page", "_songbooks/Campfire/songbook.html"),
        ("ChordPro", "_songbooks/Campfire/songbook.cho")]
    songs = book["set"]
    assert [(s["n"], s["title"], s["artist"], s["entry"]) for s in songs] == [
        (1, "Creep", "Radiohead", "Radiohead - Creep"), (2, "Hysteria", "Muse", "Muse - Hysteria"),
        (3, "De Música Ligera", "Soda Stereo", "Soda Stereo - De Música Ligera")]
    creep, hysteria, _ = songs
    assert creep["plays"] == "A Minor" and creep["own"] and creep["missing"] is None  # no capo: none said
    assert creep["at"] == {"tonic": 9, "mode": "aeolian", "capo": 0, "sounds": 9, "inst": "guitar"}  # the theory's
    assert creep["href"] == "Radiohead/Creep/sheet.html" and creep["get"] is False
    assert creep["key"] == "radiohead/creep"  # its identity key: a search's result is known in it by it
    assert (hysteria["missing"], hysteria["plays"], hysteria["at"], hysteria["href"]) == ("no sheet yet", None, None,
                                                                                         None)
    assert hysteria["get"] is True and isinstance(hysteria["id"], int)  # a lookup could get its sheet now


def test_a_songs_setting_says_where_the_songbook_plays_it(library):
    from caracole.songbook import Setting, set_song_setting

    conn, cfg = library
    set_song_setting(songbooks_file(cfg.library_dir), "Campfire", "Radiohead - Creep", Setting("G", "dorian", 0))
    creep = books_of(page(conn, cfg))[0]["set"][0]
    assert creep["plays"] == "G Dorian" and not creep["own"]  # never "G Dorian, capo 0"
    assert creep["at"] == {"tonic": 7, "mode": "dorian", "capo": 0, "sounds": 7, "inst": "guitar"}
    set_song_setting(songbooks_file(cfg.library_dir), "Campfire", "Radiohead - Creep", Setting("G", "dorian", 2))
    creep = books_of(page(conn, cfg))[0]["set"][0]
    assert creep["plays"] == "G Dorian, capo 2"
    assert creep["at"] == {"tonic": 7, "mode": "dorian", "capo": 2, "sounds": 9, "inst": "guitar"}  # sounds A
    # on an instrument with no capo: the key it sounds in, no capo
    set_song_setting(songbooks_file(cfg.library_dir), "Campfire", "Radiohead - Creep",
                     Setting(mode="dorian", capo=2, instrument="piano"))
    creep = books_of(page(conn, cfg))[0]["set"][0]
    assert creep["plays"] == "A Dorian, piano"
    assert creep["at"] == {"tonic": 9, "mode": "dorian", "capo": 0, "sounds": 9, "inst": "piano"}


def test_the_data_offers_the_keys_modes_and_capos_a_setting_takes(library):
    conn, cfg = library
    shown = data_of(page(conn, cfg))["songbooks"]
    assert shown["keys"] == ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
    assert shown["modes"][:2] == [["ionian", "Major"], ["dorian", "Dorian"]] and len(shown["modes"]) == 7
    assert shown["capoMax"] == 11 and shown["error"] is None
    assert shown["instruments"][:2] == [["guitar", "Guitar", True], ["ukulele", "Ukulele", True]]
    assert ["piano", "Piano", False] in shown["instruments"] and ["harmonica", "Harmonica", False] in shown["instruments"]


def test_a_song_gone_from_the_library_is_missing_with_no_id(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    make_songbook(songbooks_file(cfg.library_dir), "Gig", ["Radiohead - Creep", "Pixies - Debaser"])
    debaser = books_of(page(conn, cfg))[0]["set"][1]
    assert (debaser["title"], debaser["artist"], debaser["id"], debaser["missing"], debaser["get"]) == (
        "Debaser", "Pixies", None, "not in the library", False)
    assert debaser["key"] == "pixies/debaser"  # its entry's


def test_the_page_has_no_songbooks_without_songbooks(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    html = page(conn, cfg)
    assert books_of(html) == [] and 'id="songbooks"' in html  # the tab is there, for the first one


def test_a_songbook_not_made_yet_has_no_files(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    make_songbook(songbooks_file(cfg.library_dir), "Campfire", ["Radiohead - Creep"])
    [book] = books_of(page(conn, cfg))
    assert book["files"] == [] and book["changed"] is None


def test_a_broken_songbooks_file_is_said_and_the_page_is_made_all_the_same(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    songbooks_file(cfg.library_dir).parent.mkdir(parents=True, exist_ok=True)
    songbooks_file(cfg.library_dir).write_text("[Campfire\n", encoding="utf-8")
    html = page(conn, cfg)
    said = data_of(html)["songbooks"]
    assert said["books"] == [] and "songbooks.toml can't be read" in said["error"] and "line 1" in said["error"]
    assert len(data_of(html)["songs"]) == 1


def test_names_are_data_and_links_are_percent_encoded(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    make_songbook(songbooks_file(cfg.library_dir), "<b>Camp</b> & fire?", ["Radiohead - Creep"])
    render_songbooks(conn, cfg, Overrides(), runner=FakeChordPro())
    html = page(conn, cfg)
    assert "<b>Camp</b>" not in html.split('<script type="application/json"')[1]  # each < escaped in the JSON
    [book] = books_of(html)
    assert book["name"] == "<b>Camp</b> & fire?"
    hrefs = {f["label"]: f["href"] for f in book["files"]}  # (no sheet in it yet: its phone page alone)
    assert hrefs["Phone page"] == "_songbooks/bCamp-b%20%26%20fire/songbook.html"  # its folder: safe_name


def test_the_page_writes_no_songbook_of_its_own(library):
    # The tab is the script's, drawn from the data: no songbook's markup, and no form, in the page caracole wrote.
    conn, cfg = library
    for controls in (None, WebControls(csrf="tok")):
        html = page(conn, cfg, controls).split("<script")[0]
        assert "sb-card" not in html and 'action="/songbook' not in html


def test_each_line_carries_its_songs_id(library):
    from caracole.library_page import _SCRIPT

    assert "line.dataset.id = String(s.id);" in _SCRIPT  # the Select mode finds the lines by it


# --- a song's Guitar Pro mark ---------------------------------------------------------------------------


def by_title(html: str) -> dict[str, dict]:
    return {s["title"]: s for s in books_of(html)[0]["set"]}


def test_a_song_with_a_guitar_pro_file_carries_its_mark_and_one_without_none(library):
    from caracole.songs import find_song
    from helpers.guitar import keep_guitar

    conn, cfg = library
    creep = find_song(conn, "radiohead/creep")
    keep_guitar(conn, cfg, creep, b"FICHIER GUITAR PRO 5", name="guitar-1.gp5")
    songs = by_title(page(conn, cfg))
    # A file caracole keeps: the file, the name it downloads under, and caracole serve's Guitar Pro page of it.
    assert songs["Creep"]["guitar"] == {
        "kind": "file", "href": "Radiohead/Creep/guitar-1.gp5", "download": "Radiohead - Creep.gp5",
        "page": "guitar?file=Radiohead%2FCreep%2Fguitar-1.gp5"}
    assert songs["De Música Ligera"]["guitar"] is None
    assert songs["Hysteria"]["guitar"] is None


def test_a_file_the_browser_shows_wins_over_a_power_tab_file(library):
    from caracole.songs import find_song
    from helpers.guitar import keep_guitar

    conn, cfg = library
    creep, soda = find_song(conn, "radiohead/creep"), find_song(conn, "soda-stereo/de-musica-ligera")
    keep_guitar(conn, cfg, creep, b"ptab", name="guitar-1.ptb", tab="1")
    keep_guitar(conn, cfg, creep, b"FICHIER GUITAR PRO 5", name="guitar-2.gp5", tab="2")
    keep_guitar(conn, cfg, soda, b"ptab", name="guitar-1.ptb")  # a Power Tab file alone: a download, no page
    songs = by_title(page(conn, cfg))
    assert songs["Creep"]["guitar"] == {
        "kind": "file", "href": "Radiohead/Creep/guitar-2.gp5", "download": "Radiohead - Creep (2).gp5",
        "page": "guitar?file=Radiohead%2FCreep%2Fguitar-2.gp5"}
    assert songs["De Música Ligera"]["guitar"] == {
        "kind": "file", "href": "Soda%20Stereo/De%20M%C3%BAsica%20Ligera/guitar-1.ptb",
        "download": "Soda Stereo - De Música Ligera.ptb", "page": None}


def test_a_file_gone_from_the_folder_is_no_mark(library):
    from caracole.library import song_dir
    from caracole.songs import find_song
    from helpers.guitar import keep_guitar

    conn, cfg = library
    creep = find_song(conn, "radiohead/creep")
    keep_guitar(conn, cfg, creep, b"FICHIER GUITAR PRO 5", name="guitar-1.gp5")
    (song_dir(cfg.library_dir, creep) / "guitar-1.gp5").unlink()  # deleted on a device: Syncthing took it away
    songs = by_title(page(conn, cfg))
    assert songs["Creep"]["guitar"] is None


def test_a_song_not_in_the_library_has_no_guitar_pro_mark(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    make_songbook(songbooks_file(cfg.library_dir), "Gig", ["Radiohead - Creep", "Pixies - Debaser"])
    assert [s["guitar"] for s in books_of(page(conn, cfg))[0]["set"]] == [None, None]


def test_a_guitar_pro_file_changes_nothing_of_the_songbooks_files(library):
    # The mark is the tab's alone: the songbook's PDF, ChordPro file and phone page are made from its sheets.
    from caracole.songs import find_song
    from helpers.guitar import keep_guitar

    conn, cfg = library
    folder = cfg.library_dir / "_songbooks" / "Campfire"
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    keep_guitar(conn, cfg, find_song(conn, "radiohead/creep"), b"FICHIER GUITAR PRO 5", name="guitar-1.gp5")
    stats = render_songbooks(conn, cfg, Overrides(), runner=FakeChordPro())
    assert (stats.rendered, stats.skipped) == (0, 1)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


# --- the Select mode, in a real browser ---------------------------------------------------------------


def sha(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


def run_in_page(html: str, cfg, tmp_path: Path, body: str, *, size: str = "1280,900", fragment: str = ""):
    """What ``body`` (JavaScript, run once the page's scripts ran) sets as ``out``, in Chromium."""
    script = ("window.addEventListener(\"load\", () => { setTimeout(async () => {\n"
              "const q = (s) => document.querySelector(s);\nconst qa = (s) => Array.from(document.querySelectorAll(s));\n"
              "let out;\ntry {\n" + body + "\n} catch (err) { out = {error: String(err && err.stack || err)}; }\n"
              "document.body.dataset.result = JSON.stringify(out === undefined ? null : out);\n"
              "}, 30); });")
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html).group(1)
    html = html.replace(csp, csp.replace("script-src ", f"script-src {sha(script)} "))
    html = html.replace("</body>", f"<script>{script}</script>\n</body>")
    path = write_library_page(cfg.library_dir, html)
    width, height = (int(n) for n in size.split(","))
    # A phone's width, narrower than any window, laid out as a phone's screen (test_library_page.py).
    dom = browser.dump_dom(path.as_uri() + fragment, (width, height), hide_scrollbars=True, mobile=width < 500)
    found = re.search(r'data-result="([^"]*)"', dom)
    assert found, dom[-3000:]
    out = json.loads(html_module.unescape(found.group(1)))
    assert not (isinstance(out, dict) and "error" in out), out["error"]
    return out


PICK = """
  const card = (title) => qa("#list article").find((a) => a.querySelector("h3").textContent === title);
  const pick = (title) => { const box = card(title).querySelector(".pick input"); box.click(); };
  q(".pick-toggle").click();
"""


@in_chromium
def test_select_mode_shows_the_command_to_make_the_songbook_on_the_page_on_disk(library, tmp_path):
    conn, cfg = library
    out = run_in_page(page(conn, cfg), cfg, tmp_path, PICK + """
      const before = [q(".pickbar").hidden, qa("#list .pick").filter((p) => p.offsetParent).length];
      pick("Hysteria"); pick("De Música Ligera"); pick("Creep"); pick("De Música Ligera"); pick("De Música Ligera");
      const numbers = ["Hysteria", "Creep", "De Música Ligera"].map((t) => card(t).querySelector(".pick-n").textContent);
      const count = q(".pick-count").textContent;
      q(".pick-name").value = "  Beach  nights ";
      q(".pickbar-form button[type=submit]").click();
      out = {before, numbers, count, command: q(".pick-command code").textContent, shown: !q(".pick-command").hidden};
    """)
    assert out["before"] == [False, 3]  # the bar, and a box on each line
    assert out["numbers"] == ["1", "2", "3"]  # in the order picked: the songbook's
    assert out["count"] == "3 selected"
    assert out["shown"]
    assert out["command"] == ("caracole songbook make 'Beach nights' 'Muse - Hysteria' 'Radiohead - Creep' "
                              "'Soda Stereo - De Música Ligera'")


@in_chromium
def test_the_command_to_copy_quotes_each_word_so_no_shell_expands_it(conn, cfg, tmp_path):
    title = 'Wow!Wow $HOME `id` "x"'  # bash and zsh expand ! even inside double quotes
    add_song(conn, "Rock'n Band", title)
    out = run_in_page(page(conn, cfg), cfg, tmp_path, """
      q(".pick-toggle").click();
      qa("#list article")[0].querySelector(".pick input").click();
      q(".pick-name").value = "It's $5!";
      q(".pickbar-form button[type=submit]").click();
      out = q(".pick-command code").textContent;
    """)
    assert out == "caracole songbook make 'It'\\''s $5!' 'Rock'\\''n Band - Wow!Wow $HOME `id` \"x\"'"
    assert shlex.split(out) == ["caracole", "songbook", "make", "It's $5!", f"Rock'n Band - {title}"]


@in_chromium
@pytest.mark.parametrize("name,artist", [("Camp", "-M-"), ("-30- live", "Radiohead")])
def test_the_command_to_copy_runs_for_a_name_that_starts_with_a_dash(conn, cfg, tmp_path, name, artist):
    # -M- is a French artist: run as shown, a name that starts with "-" must not be taken for an option ("No such
    # option: -M"), as caracole serve's own command lines have it.
    from helpers.cli_lines import parsed

    add_song(conn, artist, "Je dis aime")
    out = run_in_page(page(conn, cfg), cfg, tmp_path, f"""
      q(".pick-toggle").click();
      qa("#list article")[0].querySelector(".pick input").click();
      q(".pick-name").value = {json.dumps(name)};
      q(".pickbar-form button[type=submit]").click();
      out = q(".pick-command code").textContent;
    """)
    assert parsed(out) == (("songbook", "make"), {"name": name, "songs": (f"{artist} - Je dis aime",)}), out


@in_chromium
def test_select_mode_can_add_to_a_songbook_there_is(library, tmp_path):
    conn, cfg = library
    out = run_in_page(page(conn, cfg), cfg, tmp_path, PICK + """
      pick("Creep");
      const into = q(".pick-into");
      into.value = "Campfire";
      into.dispatchEvent(new Event("change"));
      const nameShown = !q(".pick-name").closest("label").hidden;
      const label = q(".pickbar-form button[type=submit]").textContent;
      q(".pickbar-form button[type=submit]").click();
      out = {nameShown, label, command: q(".pick-command code").textContent};
    """)
    assert out == {"nameShown": False, "label": "Add to Campfire",
                   "command": "caracole songbook add 'Campfire' 'Radiohead - Creep'"}


@in_chromium
def test_select_mode_posts_the_songbook_on_the_served_page(library, tmp_path):
    conn, cfg = library
    html = page(conn, cfg, WebControls(csrf="tok"))
    out = run_in_page(html, cfg, tmp_path, PICK + """
      pick("De Música Ligera"); pick("Creep");
      const form = q(".pickbar-form");
      let sent = null;
      form.addEventListener("submit", (e) => {
        sent = {action: form.getAttribute("action"), method: form.method,
                fields: Array.from(new FormData(form).entries())};
        e.preventDefault();
      });
      q(".pick-name").value = "Campfire 2";
      q(".pickbar-form button[type=submit]").click();
      out = sent;
    """)
    ids = {s["display"]: s["id"] for s in data_of(html)["songs"]}
    assert out["action"] == "/songbook/make" and out["method"] == "post"
    assert dict(out["fields"]) == {"csrf": "tok", "name": "Campfire 2",
                                   "songs": f"{ids['Soda Stereo - De Música Ligera']},{ids['Radiohead - Creep']}"}


@in_chromium
def test_select_mode_says_its_state_and_each_picks_place_to_a_screen_reader(library, tmp_path):
    conn, cfg = library
    out = run_in_page(page(conn, cfg), cfg, tmp_path, PICK + """
      pick("Hysteria"); pick("Creep");
      const toggle = q(".pick-toggle");
      const name = (title) => Array.from(card(title).querySelector(".pick").childNodes)  // its label, read aloud
        .filter((n) => !(n.getAttribute && n.getAttribute("aria-hidden") === "true")).map((n) => n.textContent).join("");
      out = {on: [toggle.textContent, toggle.getAttribute("aria-pressed")],
             names: ["Hysteria", "Creep", "De Música Ligera"].map(name),
             option: q(".pick-into option").textContent};
      toggle.click();
      out.off = [toggle.textContent, toggle.getAttribute("aria-pressed")];
    """)
    assert out["on"] == ["Select", "true"] and out["off"] == ["Select", "false"]  # pressed, never "Done, pressed"
    assert out["names"] == ["Pick Hysteria by Muse, 1st", "Pick Creep by Radiohead, 2nd",
                            "Pick De Música Ligera by Soda Stereo"]
    assert out["option"] == "New songbook"  # fits the bar at 360 px


@in_chromium
def test_select_mode_needs_a_name_and_a_song(library, tmp_path):
    conn, cfg = library
    out = run_in_page(page(conn, cfg), cfg, tmp_path, PICK + """
      const disabled = q(".pickbar-form button[type=submit]").disabled;
      pick("Creep");
      q(".pick-name").value = "   ";
      q(".pickbar-form button[type=submit]").click();
      out = {disabled, shown: !q(".pick-command").hidden, said: q(".pick-error").textContent};
    """)
    assert out["disabled"] and not out["shown"] and "name" in out["said"]


@in_chromium
def test_picks_survive_a_search_and_select_mode_works_on_a_phone(library, tmp_path):
    conn, cfg = library
    out = run_in_page(page(conn, cfg), cfg, tmp_path, PICK + """
      pick("Creep");
      const input = q("#q");
      input.value = "musica";
      input.dispatchEvent(new Event("input"));
      q("[data-show=all]").click();  // the list, drawn at once (typing draws it at the next frame)
      pick("De Música Ligera");
      q("#clear").click();  // the box empties, and the list is drawn at once
      const box = q("#list .pick").getBoundingClientRect();
      const bar = q(".pickbar").getBoundingClientRect();
      out = {count: q(".pick-count").textContent, creep: card("Creep").classList.contains("picked"),
             target: [Math.round(box.width), Math.round(box.height)], scroll: document.documentElement.scrollWidth,
             page: window.innerWidth, bar: [Math.round(bar.left), Math.round(bar.right), Math.round(bar.bottom)],
             height: window.innerHeight};
    """, size="360,740")
    assert out["count"] == "2 selected" and out["creep"]
    assert out["target"][0] >= 44 and out["target"][1] >= 44  # a thumb's target
    assert out["scroll"] <= out["page"]  # nothing wider than the phone
    assert out["bar"][0] == 0 and out["bar"][1] == out["page"] and out["bar"][2] == out["height"]


LINES_PICK = """
  const line = (title) => qa("#list .line").find((a) => a.querySelector("h3").textContent === title);
  const pickLine = (title) => { line(title).querySelector(".pick input").click(); };
  q(".pick-toggle").click();
"""


@in_chromium
@pytest.mark.parametrize("size", ["390,844", "1280,900"])
def test_select_mode_puts_a_box_on_each_line_and_keeps_the_picks_when_the_list_is_drawn_again(library, tmp_path,
                                                                                               size):
    conn, cfg = library
    html = page(conn, cfg, WebControls(csrf="tok"))
    out = run_in_page(html, cfg, tmp_path, LINES_PICK + """
      const boxes = qa("#list .line .pick").filter((p) => p.offsetParent).length;
      pickLine("Hysteria"); pickLine("Creep");
      const numbers = ["Hysteria", "Creep", "De Música Ligera"].map((t) => line(t).querySelector(".pick-n").textContent);
      const picked = qa("#list .line.picked").map((r) => r.querySelector("h3").textContent);
      const box = line("Creep").querySelector(".pick").getBoundingClientRect();
      const title = line("Creep").querySelector(".line-title").getBoundingClientRect();
      const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
      const scroll = document.documentElement.scrollWidth;
      const sort = q("#sort");
      sort.value = "title";  // the list drawn again, in another order: the same picks, in the same order
      sort.dispatchEvent(new Event("change"));
      await Promise.resolve();  // the boxes come with the list's observer, once the lines are in
      const again = ["Hysteria", "Creep"].map((t) => line(t).querySelector(".pick-n").textContent);
      pickLine("De Música Ligera");
      const third = line("De Música Ligera").querySelector(".pick-n").textContent;
      out = {boxes, numbers, picked, again, third, count: q(".pick-count").textContent,
             box: [Math.round(box.width), Math.round(box.height)], apart: !overlaps(box, title),
             scroll, page: window.innerWidth};
    """, size=size)
    assert out["boxes"] == 3  # a box on each line
    assert out["numbers"] == ["1", "2", ""] and out["picked"] == ["Hysteria", "Creep"]  # by artist: Muse, Radiohead
    assert out["again"] == ["1", "2"] and out["third"] == "3" and out["count"] == "3 selected"
    assert out["box"] == [44, 44] and out["apart"]  # a thumb's target, beside the title
    assert out["scroll"] <= out["page"]


@in_chromium
def test_the_select_bars_style_leaves_a_reviews_picker_as_it_is(library, tmp_path):
    # The Select bar's form and a review's picker are two forms of the page: neither's style is the other's.
    from caracole.songs import update_song

    conn, cfg = library
    crep = add_song(conn, "Radio Head", "Crep")
    update_song(conn, crep.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "radiohead", "song_key": "creep", "score": 89.4, "step": "fuzzy_artist"}])
    out = run_in_page(page(conn, cfg, WebControls(csrf="tok")), cfg, tmp_path, """
      const card = qa("#list article").find((a) => a.querySelector("h3").textContent === "Crep");
      card.querySelector(".line-more").click();
      card.querySelector("details.picker").open = true;
      const form = card.querySelector("details.picker form");
      const radio = form.querySelector("input[type=radio]");
      const box = form.querySelector("input[type=checkbox][name=fetch]");
      out = {form: getComputedStyle(form).display, radio: Math.round(radio.getBoundingClientRect().width),
             box: Math.round(box.getBoundingClientRect().width)};
      q(".pick-toggle").click();
      q(".pick-open").click();  // on a phone the bar's fields show once asked for
      const bar = q(".pickbar form");
      Object.assign(out, {bar: getComputedStyle(bar).display,
                          name: Math.round(bar.querySelector("input[type=text]").getBoundingClientRect().height)});
    """, size="390,844")
    assert out["form"] == "grid" and out["radio"] < 40 and out["box"] < 40  # the picker's own look
    assert out["bar"] == "flex" and out["name"] == 44  # and the bar's


# --- the Select mode for the thumb: a line that is one target, and a one-line bar ----------------------------


# Each line's controls that show, but for its box; and what a tap at the middle of its title, its status and its
# title's box lands on.
LINE_TARGETS = """
  const landsOn = (line, n) => {
    if (!n) return null;
    n.scrollIntoView({block: "center"});
    const r = n.getBoundingClientRect();
    const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    return hit === line ? "line" : hit ? hit.className || hit.tagName : null;
  };
  const targets = (line) => ({
    controls: qa("a, button, summary, select, input").filter((n) => line.contains(n) && !n.closest(".pick")
      && n.checkVisibility()).map((n) => n.className),
    funnel: line.querySelector(".filter-mark").checkVisibility(),
    taps: [line.querySelector("h3"), line.querySelector(".line-status .badge"), line.querySelector(".line-title")]
      .map((n) => landsOn(line, n)),
  });
"""


@in_chromium
@pytest.mark.parametrize("size", ["390,844", "1280,800"])
def test_while_selecting_a_line_shows_no_file_or_action_and_a_tap_anywhere_lands_on_it(library, tmp_path, size):
    from caracole.songs import update_song

    conn, cfg = library
    crep = add_song(conn, "Radio Head", "Crep")
    update_song(conn, crep.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "radiohead", "song_key": "creep", "score": 89.4, "step": "fuzzy_artist"}])
    karma = add_song(conn, "Radiohead", "Karma Police")  # in review, no candidates: a note says what to do
    update_song(conn, karma.id, review=True, match_decision="review")
    # Hysteria's fetch runs: its line links its details, which a tap would no more reach than a file.
    hysteria = next(s for s in data_of(page(conn, cfg))["songs"] if s["title"] == "Hysteria")
    running = {"id": 7, "kind": "song", "songId": hysteria["id"], "state": "running", "display": "Muse - Hysteria",
               "line": {"tone": "running", "text": "Fetching from Ultimate Guitar…", "details": "#tab=requests&job=7"}}
    controls = WebControls(csrf="tok", busy=frozenset({hysteria["id"]}), active=1, jobs=(running,))
    out = run_in_page(page(conn, cfg, controls), cfg, tmp_path, LINE_TARGETS + """
      const byTitle = (title) => qa("#list [data-id]").find((a) => a.querySelector("h3").textContent === title);
      const titles = ["Creep", "Hysteria", "Crep", "Karma Police"];
      for (const t of titles) byTitle(t).querySelector(".line-more").click();  // every "⋯" open
      const before = titles.map((t) => targets(byTitle(t)).controls.length);
      const note = byTitle("Karma Police").querySelector(".note").checkVisibility();
      const details = byTitle("Hysteria").querySelector(".progress a").checkVisibility();
      q(".pick-toggle").click();
      await Promise.resolve();  // the boxes come with the list's observer
      const lines = Object.fromEntries(titles.map((t) => [t, targets(byTitle(t))]));
      const hidden = [byTitle("Karma Police").querySelector(".note").checkVisibility(),
                      byTitle("Hysteria").querySelector(".progress a").checkVisibility()];
      q(".pick-toggle").click();
      const after = titles.map((t) => targets(byTitle(t)).controls.length);
      out = {before, note, details, lines, hidden, after};
    """, size=size)
    # Before: Open, "⋯" and all it holds (files, Fetch now, the picker, the note's link to the to-do page, Add to a
    # songbook…, Remove…), a request's Details. Selecting: the title alone (a link to the sheet, or none), which a tap
    # no more reaches than the rest; a request's line says how it goes, without its links; a tap anywhere lands on
    # the line, which picks it.
    assert min(out["before"]) >= 3 and out["note"] and out["details"], out["before"]
    shown = out["lines"]
    assert shown["Creep"]["controls"] == ["line-title"], shown
    for title in ("Hysteria", "Crep", "Karma Police"):
        assert shown[title]["controls"] == [], (title, shown[title])
    for title, seen in shown.items():
        assert seen["taps"] == ["line", "line", "line"] and not seen["funnel"], (title, seen)
    assert out["hidden"] == [False, False]
    assert out["after"] == out["before"]  # out of the mode, all back


@in_chromium
def test_on_a_phone_a_tap_on_a_line_picks_it_and_opens_nothing(library, tmp_path):
    from helpers.browser import Browser, BrowserError

    conn, cfg = library
    ids = {s["display"]: s["id"] for s in data_of(page(conn, cfg))["songs"]}
    path = write_library_page(cfg.library_dir, page(conn, cfg, WebControls(csrf="tok")))
    try:
        phone = Browser(tmp_path / "chrome", width=390, height=844, mobile=True)
    except BrowserError as e:
        pytest.skip(f"chromium couldn't run: {e}")
    creep = f'#list [data-id="{ids["Radiohead - Creep"]}"]'
    hysteria = f'#list [data-id="{ids["Muse - Hysteria"]}"]'
    picked = (f"[{json.dumps(creep)}, {json.dumps(hysteria)}].map((s) => "
              "document.querySelector(s).classList.contains('picked'))")
    with phone:
        phone.open(path.as_uri())
        assert phone.wait(f"document.querySelector({json.dumps(creep)}) !== null")
        phone.click(".pick-toggle")
        phone.click(creep + " .line-title")  # the title opens the sheet, but not while selecting
        assert phone.js(picked) == [True, False]
        phone.click(creep + " .line-status")  # nor does its status do anything but untick it
        assert phone.js(picked) == [False, False]
        phone.click(creep + " .line-meta")
        phone.click(hysteria + " h3")
        assert phone.js(picked) == [True, True]
        assert phone.js("document.querySelector('.pick-count').textContent") == "2 selected"
        size = phone.js(f"(() => {{ const r = document.querySelector({json.dumps(creep + ' .pick')})"
                        ".getBoundingClientRect(); return [r.width, r.height]; })()")
        assert size == [44, 44]  # each box a thumb's size
        assert phone.js("location.pathname").endswith("/index.html")  # nothing opened
        assert phone.js("document.querySelectorAll('#list [data-id]').length") == 3  # nor filtered


# Where each of the bar's parts is, and whether it shows.
BAR = """
  const shown = (n) => Boolean(n && n.checkVisibility());
  const box = (n) => n.getBoundingClientRect();
  const middle = (n) => Math.round(box(n).top + box(n).height / 2);
  const bar = () => ({
    height: Math.round(box(q(".pickbar")).height),
    fields: [q(".pick-into"), q(".pick-name"), q(".pickbar-form button[type=submit]")].map(shown),
    toggle: shown(q(".pick-open")), expanded: q(".pick-open").getAttribute("aria-expanded"),
    primary: qa(".pickbar .btn.primary").filter(shown).map((b) => b.textContent),
  });
"""


@in_chromium
def test_on_a_phone_the_select_bar_is_one_line_that_opens_its_name_field_and_its_menu(library, tmp_path):
    conn, cfg = library
    out = run_in_page(page(conn, cfg), cfg, tmp_path, PICK + BAR + """
      pick("Creep"); pick("Hysteria");
      const open = q(".pick-open"), done = q(".pick-done"), count = q(".pick-count");
      const folded = Object.assign(bar(), {
        line: [done, count, open].map(middle), said: [count.textContent, open.textContent],
        names: [done.getAttribute("aria-label"), open.getAttribute("aria-controls") === q(".pickbar-form").id],
        targets: [open, done].map((n) => [Math.round(box(n).width), Math.round(box(n).height)])});
      open.click();
      const opened = Object.assign(bar(), {focus: document.activeElement === q(".pick-name"),
        caret: [Math.round(box(open).width), open.textContent]});
      // A name may hold a slash ("AC/DC nights"): the page's "/", which goes to the search box, leaves it be.
      const slash = new KeyboardEvent("keydown", {key: "/", bubbles: true, cancelable: true});
      q(".pick-name").dispatchEvent(slash);
      opened.slash = [document.activeElement === q(".pick-name"), slash.defaultPrevented];
      document.activeElement.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape", bubbles: true}));
      const back = Object.assign(bar(), {focus: document.activeElement === open});
      const into = q(".pick-into");
      into.value = "Campfire";
      into.dispatchEvent(new Event("change"));
      out = {folded, opened, back, adds: open.textContent, scroll: document.documentElement.scrollWidth,
             page: innerWidth};
    """, size="390,844")
    folded, opened, back = out["folded"], out["opened"], out["back"]
    # One line: the way out, the count and the button that names the songbook, each a thumb's target.
    assert folded["said"] == ["2 selected", "Make songbook…"]
    assert max(folded["line"]) - min(folded["line"]) <= 2 and folded["height"] <= 66, folded
    assert all(w >= 44 and h >= 44 for w, h in folded["targets"]), folded["targets"]
    assert folded["names"] == ["Leave Select", True]
    assert folded["fields"] == [False, False, False] and folded["expanded"] == "false"
    assert folded["primary"] == ["Make songbook…"]
    # Tapped, it opens the songbook menu and the name field, ready to type in; its own button folds to a caret,
    # so the bar's one primary button is the one that makes the songbook.
    assert opened["fields"] == [True, True, True] and opened["expanded"] == "true" and opened["focus"]
    assert opened["primary"] == ["Make songbook"] and opened["caret"] == [44, "Make songbook…"]
    assert opened["height"] > folded["height"]
    assert opened["slash"] == [True, False]
    # Escape folds it back, and the focus goes back to the button.
    assert back["fields"] == [False, False, False] and back["expanded"] == "false" and back["focus"]
    assert back["height"] == folded["height"]
    assert out["adds"] == "Add to Campfire…"  # it says what it will do
    assert out["scroll"] <= out["page"]


@in_chromium
def test_on_a_desktop_the_select_bar_keeps_everything_on_one_line(library, tmp_path):
    conn, cfg = library
    out = run_in_page(page(conn, cfg), cfg, tmp_path, PICK + BAR + """
      pick("Creep");
      const parts = [q(".pick-done"), q(".pick-count"), q(".pick-into"), q(".pick-name"),
                     q(".pickbar-form button[type=submit]"), q(".pickbar-form button[type=button]")];
      out = Object.assign(bar(), {line: parts.map(middle), shown: parts.map(shown)});
    """, size="1280,800")
    assert out["shown"] == [True] * 6 and out["fields"] == [True, True, True]
    assert max(out["line"]) - min(out["line"]) <= 2 and out["height"] <= 66, out
    assert not out["toggle"] and out["primary"] == ["Make songbook"]  # nothing to open: it is all there


@in_chromium
def test_the_cross_leaves_select_mode_and_keeps_the_picks(library, tmp_path):
    conn, cfg = library
    out = run_in_page(page(conn, cfg), cfg, tmp_path, PICK + """
      pick("Creep");
      q(".pick-open").click();
      q(".pick-done").focus();
      q(".pick-done").click();
      // Out of the mode a picked song looks like any other (where the picks show again).
      const look = (n) => { const c = getComputedStyle(n); return [c.borderLeftColor, c.boxShadow, c.backgroundColor]; };
      const same = () => JSON.stringify(look(card("Creep"))) === JSON.stringify(look(card("Hysteria")));
      const left = {bar: q(".pickbar").hidden, pressed: q(".pick-toggle").getAttribute("aria-pressed"),
                    focus: document.activeElement === q(".pick-toggle"),
                    open: card("Creep").querySelector("a.btn.primary").checkVisibility(), same: same()};
      q(".pick-toggle").click();
      out = {left, count: q(".pick-count").textContent, creep: card("Creep").classList.contains("picked"),
             fields: q(".pick-name").checkVisibility()};
    """, size="390,844")
    assert out["left"] == {"bar": True, "pressed": "false", "focus": True, "open": True, "same": True}
    assert out["count"] == "1 selected" and out["creep"]  # back in, the picks are as they were
    assert not out["fields"]  # and the bar is one line again


@in_chromium
@pytest.mark.parametrize("size", ["390,844", "1280,800"])
def test_on_the_file_the_command_to_run_folds_away_beside_copy(library, tmp_path, size):
    from caracole.songs import update_song

    conn, cfg = library
    hysteria = next(s for s in data_of(page(conn, cfg))["songs"] if s["title"] == "Hysteria")
    update_song(conn, hysteria["id"], match_decision="not_found")  # its line says what to run to find it
    out = run_in_page(page(conn, cfg), cfg, tmp_path, PICK + BAR + """
      const hint = card("Hysteria").querySelector(".pick-hint").checkVisibility();
      pick("Creep"); pick("Hysteria");
      if (q(".pick-open").checkVisibility()) q(".pick-open").click();
      const before = bar().height;
      q(".pick-name").value = "Friday set";
      q(".pickbar-form button[type=submit]").click();
      const fold = q(".pick-command details");
      const copy = q(".pick-command button");
      const made = {height: bar().height, open: fold.open, code: q(".pick-command code").checkVisibility(),
                    copy: [copy.textContent, copy.checkVisibility(), copy.getAttribute("aria-label")],
                    summary: fold.querySelector("summary").textContent,
                    lines: Math.round(box(fold.querySelector("summary")).height),
                    command: q(".pick-command code").textContent};
      fold.querySelector("summary").click();
      out = {before, made, hint, opened: {code: q(".pick-command code").checkVisibility(), height: bar().height,
                                          where: fold.querySelector(".hint").textContent},
             page: innerHeight, scroll: document.documentElement.scrollWidth, width: innerWidth};
    """, size=size)
    made = out["made"]
    assert made["command"] == "caracole songbook make 'Friday set' 'Radiohead - Creep' 'Muse - Hysteria'"
    # Folded, under the fields: one line, Copy beside it.
    assert not made["open"] and not made["code"]
    assert made["copy"] == ["Copy", True, "Copy the command"]
    assert made["summary"] == "The command to run" and made["lines"] <= 44
    assert made["height"] - out["before"] <= 56, out
    # Unfolded, the command shows, where to run it, and the bar still leaves most of the screen to the songs.
    assert out["opened"]["code"] and out["opened"]["height"] <= out["page"] * 0.6
    assert out["opened"]["where"] == "Run it where caracole runs:"
    assert not out["hint"]  # the not-found song's own command is put away while picking
    assert out["scroll"] <= out["width"]
