"""caracole/web/pages.py: the pages caracole serve writes itself (Requests, a song's pick, a removal), in
Chromium: on a touch screen every control is a thumb's size, and every field has an edge an
eye can find, in light and dark (index.html's BASE_STYLE and PICKER_STYLE, which they share)."""

from __future__ import annotations

import re

import pytest
from helpers import browser
from helpers.browser import in_chromium
from helpers.targets import UNFOLD, noted, noting, small_targets, weak_edges

from caracole.web.jobs import Job, Step
from caracole.web.pages import Pick, jobs_page, remove_page, review_page
from caracole.web.status import Line

CHOICES = ({"n": 1, "ref": "radiohead/creep", "artist": "Radiohead", "title": "Creep", "score": 89,
            "why": "artist spelled differently", "tabs": "Chords ×2",
            "href": "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-1"},)
PICK = Pick(song_id=1, display="Radio Head - Crep", title="Crep", artist="Radio Head", choices=CHOICES)


def pages() -> dict[str, str]:
    """A page of each kind: Requests with a finished request that waits for a pick, under its own line."""
    job = Job(id=1, title="Fetch Radio Head - Crep", song_key="radio head/crep", display="Radio Head - Crep",
              state="failed", steps=[Step("Fetch the sheet", ("fetch", "--song", "1"), state="failed",
                                          output=["Radio Head - Crep: needs review first"])])
    lines = {1: Line("review", "Needs a pick", link=("Pick the match", "/review?song=1"))}
    return {
        "requests": jobs_page([job], lines, picks={"radio head/crep": PICK}, csrf="tok"),
        "pick": review_page(PICK, "tok"),
        "remove": remove_page("Radiohead - Creep", 1, "radiohead/creep", "tok", ["sheet.pdf"], ["Music/"], []),
    }


@pytest.mark.parametrize("name", ["requests", "pick", "remove"])
@in_chromium
def test_on_a_touch_screen_every_control_is_a_thumbs_size_and_every_field_has_an_edge(tmp_path, name):
    # The mark and name that lead home, before the title, are a thumb's size like the Library link beside it.
    script = UNFOLD + noting("data-short", small_targets()) + noting("data-weak", weak_edges())
    path = tmp_path / f"{name}.html"
    path.write_text(pages()[name].replace("</body>", f"<script>{script}</script>\n</body>"), encoding="utf-8")
    for scheme in ("light", "dark"):
        dom = browser.dump_dom(path.as_uri(), (390, 844), mobile=True, touch=True,
                               media={"prefers-color-scheme": scheme})
        short, weak = noted(dom, "data-short"), noted(dom, "data-weak")
        assert short == [] and weak == [], (scheme, short, weak)


def test_a_page_of_caracole_serves_own_opens_with_one_line_the_mark_the_title_and_its_links():
    from caracole.web.pages import page

    html = page("Requests", "<p>Body</p>")
    header = re.search(r'<header class="top">(.*?)</header>', html, re.S).group(1)
    assert re.search(r'<a class="app" href="/"><svg class="mark"[^>]*>.*?</svg><span class="word">caracole</span></a>',
                     header, re.S)  # the "¿" and the name lead home
    assert "<h1>Requests</h1>" in header
    assert '<nav class="links" aria-label="Pages"><a class="navlink" href="/">Library</a></nav>' in header
    assert 'class="masthead"' not in html and '<p class="app">' not in html
    assert html.split("</header>", 1)[1].lstrip().startswith("<p>Body</p>")


def test_the_requests_page_explains_nothing_before_its_requests_but_how_it_refreshes():
    empty = jobs_page([], {})
    assert "under its lock" not in empty and "caracole get" not in empty
    assert "No requests yet. Request a song from" in empty
    running = Job(id=1, title="Fetch Radiohead - Creep", song_key="radiohead/creep", display="Radiohead - Creep",
                  state="running", steps=[Step("Fetch the sheet", ("fetch", "--song", "1"), state="running")])
    body = jobs_page([running], {1: Line("running", "Fetching…")})
    assert "under its lock" not in body and 'href="/jobs?refresh=0"' in body and "Stop refreshing" in body


HEADER = """
(() => {
  const mid = (s) => { const r = document.querySelector(s).getBoundingClientRect(); return Math.round(r.top + r.height / 2); };
  document.body.setAttribute("data-top", JSON.stringify({
    app: mid("header.top .app"), title: mid("header.top h1"), links: mid("header.top .links"),
    word: document.querySelector("header.top .app .word").getBoundingClientRect().width,
    mark: document.querySelector("header.top .app svg.mark").getBoundingClientRect().height,
    first: Math.round(document.querySelector("section.requests").getBoundingClientRect().top),
    fits: document.documentElement.scrollWidth <= innerWidth }));
})();
"""


@pytest.mark.parametrize("size,phone", [((1280, 800), False), ((390, 844), True)])
@in_chromium
def test_the_header_is_one_line_and_on_a_phone_the_mark_alone_leads_home(tmp_path, size, phone):
    path = tmp_path / "requests.html"
    path.write_text(pages()["requests"].replace("</body>", f"<script>{HEADER}</script>\n</body>"), encoding="utf-8")
    dom = browser.dump_dom(path.as_uri(), size, mobile=phone, touch=phone)
    top = noted(dom, "data-top")
    assert abs(top["app"] - top["title"]) < 12 and abs(top["app"] - top["links"]) < 12, top  # one line
    assert top["mark"] >= 16 and top["fits"] and top["first"] < 140, top
    assert (top["word"] <= 1) is phone, top  # the name beside the mark, but on a phone
