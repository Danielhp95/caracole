"""index.html's songbooks: the Songbooks section, and the Select mode that makes one."""

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


def section(html: str) -> str:
    found = re.search(r'<section class="songbooks" id="songbooks"[^>]*>(.*?)</section>', html, re.S)
    assert found, "no Songbooks section"
    return found.group(1)


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


# --- the Songbooks section ------------------------------------------------------------------------


def test_each_songbook_is_listed_with_its_songs_and_its_files(library):
    conn, cfg = library
    shown = section(page(conn, cfg))
    assert "<h2>Campfire</h2>" in shown and "3 songs, 1 without a sheet" in shown
    hrefs = re.findall(r'<a class="btn[^"]*" href="([^"]*)"', shown)
    assert hrefs == ["_songbooks/Campfire/songbook.html", "_songbooks/Campfire/songbook.pdf",
                     "_songbooks/Campfire/songbook.cho"]
    titles = re.findall(r'<span class="t">([^<]*)</span>', shown)
    assert titles == ["Creep", "Hysteria", "De Música Ligera"]
    assert re.search(r'<li class="missing">.*?Hysteria.*?missing: no sheet yet', shown, re.S)


def test_the_page_lists_no_songbooks_section_without_songbooks(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    html = page(conn, cfg)
    assert 'id="songbooks"' not in html and data_of(html)["songbooks"] == []


def test_a_songbook_not_made_yet_says_so(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    make_songbook(songbooks_file(cfg.library_dir), "Campfire", ["Radiohead - Creep"])
    shown = section(page(conn, cfg))
    assert "Not made yet" in shown and "songbook.html" not in shown


def test_a_broken_songbooks_file_is_said_and_the_page_is_made_all_the_same(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    songbooks_file(cfg.library_dir).parent.mkdir(parents=True, exist_ok=True)
    songbooks_file(cfg.library_dir).write_text("[Campfire\n", encoding="utf-8")
    html = page(conn, cfg)
    assert "songbooks.toml can't be read" in section(html) and "line 1" in section(html)
    assert len(data_of(html)["songs"]) == 1


def test_names_are_text_and_links_are_percent_encoded(conn, cfg):
    add_song(conn, "Radiohead", "Creep")
    make_songbook(songbooks_file(cfg.library_dir), "<b>Camp</b> & fire?", ["Radiohead - Creep"])
    render_songbooks(conn, cfg, Overrides(), runner=FakeChordPro())
    shown = section(page(conn, cfg))
    assert "<b>Camp</b>" not in shown and "&lt;b&gt;Camp&lt;/b&gt; &amp; fire?" in shown
    assert 'href="_songbooks/bCamp-b%20%26%20fire/songbook.html"' in shown  # its folder: library.safe_name


def test_the_page_on_disk_has_no_songbook_forms(library):
    conn, cfg = library
    shown = section(page(conn, cfg))
    assert "<form" not in shown
    assert "caracole songbook" in shown  # what to run instead


def test_the_served_page_reorders_takes_out_renames_and_deletes(library):
    conn, cfg = library
    shown = section(page(conn, cfg, WebControls(csrf="tok&en")))
    forms = re.findall(r'<form method="post" action="(/songbook/[a-z]+)"[^>]*>(.*?)</form>', shown, re.S)
    actions = [a for a, _ in forms]
    assert actions.count("/songbook/move") == 4  # up for the 2nd and 3rd song, down for the 1st and 2nd
    assert actions.count("/songbook/remove") == 3
    assert actions.count("/songbook/rename") == 1 and actions.count("/songbook/delete") == 1
    for _, body in forms:
        assert '<input type="hidden" name="csrf" value="tok&amp;en">' in body
        assert '<input type="hidden" name="name" value="Campfire">' in body
    moves = [body for a, body in forms if a == "/songbook/move"]
    assert 'name="song" value="Radiohead - Creep"' in moves[0] and 'name="position" value="2"' in moves[0]
    assert "Move Creep down" in moves[0]
    assert 'name="song" value="Muse - Hysteria"' in moves[1] and 'name="position" value="1"' in moves[1]
    rename = next(body for a, body in forms if a == "/songbook/rename")
    assert re.search(r'<input name="new" required maxlength="80"', rename)
    delete = next(body for a, body in forms if a == "/songbook/delete")
    assert '<input type="checkbox" required>' in delete  # a tap alone deletes nothing


def test_the_data_names_the_songbooks_for_the_select_bar(library):
    conn, cfg = library
    assert data_of(page(conn, cfg))["songbooks"] == [{"name": "Campfire", "songs": 3}]


def test_each_card_carries_its_songs_id(library):
    conn, cfg = library
    from caracole.library_page import _SCRIPT

    assert "card.dataset.id = String(s.id);" in _SCRIPT  # the Select mode finds the cards by it


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
  const card = (title) => qa("#list article").find((a) => a.querySelector("h2").textContent === title);
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
    assert out["before"] == [False, 3]  # the bar, and a box on each card
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
      q(".chip[data-show=all]").click();  // the list, drawn at once (typing draws it at the next frame)
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


ROWS_PICK = """
  const row = (title) => qa("#list .row").find((a) => a.querySelector(".row-title").textContent === title);
  const pickRow = (title) => { row(title).querySelector(".pick input").click(); };
  q(".pick-toggle").click();
"""


@in_chromium
@pytest.mark.parametrize("size", ["390,844", "1280,900"])
def test_select_mode_picks_rows_too_and_keeps_the_picks_across_the_views(library, tmp_path, size):
    conn, cfg = library
    html = page(conn, cfg, WebControls(csrf="tok"))
    out = run_in_page(html, cfg, tmp_path, ROWS_PICK + """
      const boxes = qa("#list .row .pick").filter((p) => p.offsetParent).length;
      pickRow("Hysteria"); pickRow("Creep");
      const numbers = ["Hysteria", "Creep", "De Música Ligera"].map((t) => row(t).querySelector(".pick-n").textContent);
      const picked = qa("#list .row.picked").map((r) => r.querySelector(".row-title").textContent);
      const box = row("Creep").querySelector(".pick").getBoundingClientRect();
      const title = row("Creep").querySelector(".row-title").getBoundingClientRect();
      const mark = row("Creep").querySelector(".source");
      const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
      const scroll = document.documentElement.scrollWidth;
      q('button[data-view="cards"]').click();  // the cards show the same picks, in the same order
      await Promise.resolve();  // the boxes come with the list's observer, once the cards are in
      const card = (title) => qa("#list article.card").find((a) => a.querySelector("h2").textContent === title);
      const cards = ["Hysteria", "Creep"].map((t) => card(t).querySelector(".pick-n").textContent);
      card("De Música Ligera").querySelector(".pick input").click();
      q('button[data-view="rows"]').click();
      await Promise.resolve();
      const third = row("De Música Ligera").querySelector(".pick-n").textContent;
      out = {boxes, numbers, picked, cards, third, count: q(".pick-count").textContent,
             box: [Math.round(box.width), Math.round(box.height)], apart: !overlaps(box, title),
             mark: mark ? mark.offsetParent === null : true, scroll, page: window.innerWidth};
    """, size=size, fragment="#view=rows")
    assert out["boxes"] == 3  # a box on each row
    assert out["numbers"] == ["1", "2", ""] and out["picked"] == ["Hysteria", "Creep"]  # by artist: Muse, Radiohead
    assert out["cards"] == ["1", "2"] and out["third"] == "3" and out["count"] == "3 selected"
    assert out["box"][0] >= 34 and out["box"][1] >= 34 and out["apart"]  # a target of its own, beside the title
    assert out["mark"]  # the box stands where the source's mark was
    assert out["scroll"] <= out["page"]


def test_each_row_carries_its_songs_id():
    from caracole.library_page import _SCRIPT

    assert "row.dataset.id = String(s.id);" in _SCRIPT  # the Select mode finds the rows by it


@in_chromium
def test_the_select_bars_style_leaves_a_reviews_picker_as_it_is(library, tmp_path):
    # The Select bar's form and a review's picker are two forms of the page: neither's style is the other's.
    from caracole.songs import update_song

    conn, cfg = library
    crep = add_song(conn, "Radio Head", "Crep")
    update_song(conn, crep.id, review=True, match_decision="review", match_candidates=[
        {"artist_key": "radiohead", "song_key": "creep", "score": 89.4, "step": "fuzzy_artist"}])
    out = run_in_page(page(conn, cfg, WebControls(csrf="tok")), cfg, tmp_path, """
      const card = qa("#list article").find((a) => a.querySelector("h2").textContent === "Crep");
      card.querySelector("details.picker").open = true;
      const form = card.querySelector("details.picker form");
      const radio = form.querySelector("input[type=radio]");
      const box = form.querySelector("input[type=checkbox][name=fetch]");
      q(".pick-toggle").click();
      const bar = q(".pickbar form");
      out = {form: getComputedStyle(form).display, radio: Math.round(radio.getBoundingClientRect().width),
             box: Math.round(box.getBoundingClientRect().width), bar: getComputedStyle(bar).display,
             name: Math.round(bar.querySelector("input[type=text]").getBoundingClientRect().height)};
    """, size="390,844")
    assert out["form"] == "grid" and out["radio"] < 40 and out["box"] < 40  # the picker's own look
    assert out["bar"] == "flex" and out["name"] == 44  # and the bar's
