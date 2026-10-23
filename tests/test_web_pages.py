"""caracole/web/pages.py: the pages caracole serve writes itself (Requests, a song's pick, a removal), in
Chromium: on a touch screen every control is a thumb's size, and every field has an edge an
eye can find, in light and dark (index.html's BASE_STYLE and PICKER_STYLE, which they share)."""

from __future__ import annotations

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
    # The brand above the title goes where the Library link beside it goes, which is a thumb's size.
    script = UNFOLD + noting("data-short", small_targets(".app a")) + noting("data-weak", weak_edges())
    path = tmp_path / f"{name}.html"
    path.write_text(pages()[name].replace("</body>", f"<script>{script}</script>\n</body>"), encoding="utf-8")
    for scheme in ("light", "dark"):
        dom = browser.dump_dom(path.as_uri(), (390, 844), mobile=True, touch=True,
                               media={"prefers-color-scheme": scheme})
        short, weak = noted(dom, "data-short"), noted(dom, "data-weak")
        assert short == [] and weak == [], (scheme, short, weak)
