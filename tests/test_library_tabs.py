"""tabs.js and the masthead's tab row, in Chromium: a thumb's tabs on a phone, the row scrolling sideways when they
don't fit, the chosen tab brought into its view."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from helpers import browser
from helpers.browser import CHROMIUM_MARKS

from caracole.library_page import WebControls, build_library_page, write_library_page
from caracole.overrides import Overrides

pytestmark = CHROMIUM_MARKS

NOW = datetime(2026, 10, 27, 3, 0, tzinfo=UTC)
TABS = """(() => { const row = document.querySelector('.masthead .tabs');
  return { row: [row.scrollWidth, row.clientWidth, getComputedStyle(row).overflowX, row.getBoundingClientRect().left,
                 row.getBoundingClientRect().right],
    tabs: [...row.querySelectorAll('[role=tab]')].map((t) => { const r = t.getBoundingClientRect();
      return [t.id, r.height, parseFloat(getComputedStyle(t).paddingLeft), r.left, r.right, Math.round(r.top)]; }),
    page: document.documentElement.scrollWidth <= innerWidth }; })()"""


@pytest.mark.parametrize("width", [320, 390])
@pytest.mark.parametrize("sync", ["tab", None])  # five tabs (caracole serve's, Share last), or four
def test_on_a_phone_each_tab_is_48px_tall_and_a_row_too_wide_scrolls_on_its_own(conn, cfg, tmp_path, width, sync):
    served = write_library_page(cfg.library_dir, build_library_page(
        conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok", active=1, sync=sync)))
    with browser.Browser(tmp_path / "chrome", width=width, height=844, mobile=True) as phone:
        phone.open(served.as_uri())
        assert phone.js("matchMedia('(pointer: coarse)').matches")
        seen = phone.js(TABS)
        assert all(h >= 48 and pad >= 10 for _, h, pad, *_ in seen["tabs"]), seen
        assert len({top for *_, top in seen["tabs"]}) == 1 and seen["page"], seen  # one row, the page never sideways
        assert seen["row"][2] == "auto"
        if sync == "tab":
            assert seen["row"][0] > seen["row"][1]  # five don't fit: the row scrolls
            phone.js("window.caracoleTabs.show('sync')")  # the last, past the row's edge: chosen, it comes into view
            left, right = phone.js("(() => { const r = document.getElementById('tab-sync').getBoundingClientRect(); "
                                   "return [r.left, r.right]; })()")
            assert seen["row"][3] - 0.5 <= left and right <= seen["row"][4] + 0.5
