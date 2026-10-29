"""The library page's Sites tab (sites.js, sites.css), drawn from sites.py's data: in the file and served."""

from __future__ import annotations

import dataclasses
import html as html_module
import json
import re
from datetime import UTC, datetime

import pytest
from helpers import browser
from helpers.browser import Browser, in_chromium
from helpers.songbooks import keep_sheet

from caracole.config import ProviderPolicy
from caracole.db import kv_set, kv_set_json
from caracole.library_page import WebControls, build_library_page, write_library_page
from caracole.overrides import Overrides
from conftest import add_song
from test_library_page_songbooks import sha

NOW = datetime(2026, 10, 29, 3, 41, tzinfo=UTC)
ORDER = ["ug", "lacuerda", "lrclib", "gtptabs", "musescore", "harptabs", "gametabs", "youtube"]


def figures(conn, cfg):
    """Two songs, one with UG's sheet, UG's index of two songs, and last night's run."""
    keep_sheet(conn, cfg, add_song(conn, "Eagles", "Hotel California"), tab_id=1)
    add_song(conn, "Eagles", "Desperado")
    conn.executemany("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
                     "VALUES (?, 'eagles', ?, 'Chords', 'tabs1.xml', '2026-10-01T00:00:00Z', '')",
                     [(1, "hotel california"), (2, "hotel california"), (3, "desperado")])
    kv_set(conn, "ug:index:built_at", "2026-10-28T03:00:00Z")
    kv_set_json(conn, "run:last", {"run_id": "2026-10-29T07:00:00Z", "started": "2026-10-29T07:00:00Z",
                                   "finished": "2026-10-29T07:41:00Z", "requests": {"ug": 58}, "budgets": {"ug": 60}})


def tab_ids(html: str) -> list[str]:
    return re.findall(r'role="tab" id="tab-([a-z]+)"', html)


def test_the_sites_tab_sits_before_requests(conn, cfg):
    served = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok"))
    assert tab_ids(served) == ["library", "songbooks", "sites", "requests"]
    assert tab_ids(build_library_page(conn, cfg, Overrides(), NOW)) == ["library", "songbooks", "sites"]


def run_in_page(html: str, cfg, body: str, *, size=(1280, 900), fragment="#tab=sites", scheme="light"):
    """What ``body`` (JavaScript, run once the page's scripts ran) sets as ``out``, in Chromium."""
    script = ("window.addEventListener(\"load\", () => { setTimeout(() => {\n"
              "const q = (s) => document.querySelector(s);\nconst qa = (s) => Array.from(document.querySelectorAll(s));\n"
              "let out;\ntry {\n" + body + "\n} catch (err) { out = {error: String(err && err.stack || err)}; }\n"
              "document.body.dataset.result = JSON.stringify(out === undefined ? null : out);\n"
              "}, 30); });")
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html).group(1)
    html = html.replace(csp, csp.replace("script-src ", f"script-src {sha(script)} "))
    html = html.replace("</body>", f"<script>{script}</script>\n</body>")
    path = write_library_page(cfg.library_dir, html)
    dom = browser.dump_dom(path.as_uri() + fragment, size, hide_scrollbars=True, mobile=size[0] < 500,
                           media={"prefers-color-scheme": scheme})
    found = re.search(r'data-result="([^"]*)"', dom)
    assert found, dom[-3000:]
    out = json.loads(html_module.unescape(found.group(1)))
    assert not (isinstance(out, dict) and "error" in out), out["error"]
    return out


@in_chromium
def test_the_written_file_draws_the_ledger(conn, cfg):
    figures(conn, cfg)
    out = run_in_page(build_library_page(conn, cfg, Overrides(), NOW), cfg, """
      const ug = q('.site-line[data-site="ug"]');
      out = {shown: !q('#sites').hidden, sites: qa('.site-line').map((b) => b.dataset.site),
             ug: ug.textContent, head: q('.sites-head').textContent, icon: !!ug.querySelector('img, .letters')};
    """)
    assert out["shown"] is True
    assert out["sites"] == ORDER
    assert "2 songs" in out["ug"] and "1 sheet" in out["ug"] and "58 / 60" in out["ug"] and "OK" in out["ug"]
    assert out["icon"] is True
    assert "8 sites" in out["head"] and "58 requests" in out["head"]


@in_chromium
def test_a_line_opens_by_click_and_by_keyboard(conn, cfg, tmp_path):
    figures(conn, cfg)
    path = write_library_page(cfg.library_dir, build_library_page(conn, cfg, Overrides(), NOW))
    line = "document.querySelector('.site-line[data-site=\"ug\"]')"
    more = f"document.getElementById({line}.getAttribute('aria-controls'))"
    with Browser(tmp_path / "chrome", width=1280, height=900) as page:
        page.open(path.as_uri() + "#tab=sites")
        assert page.wait(f"{line} !== null")
        assert page.js(f"{line}.getAttribute('aria-expanded')") == "false" and page.js(f"{more}.hidden") is True
        page.click('.site-line[data-site="ug"]')
        assert page.wait(f"{line}.getAttribute('aria-expanded') === 'true'")
        assert page.js(f"{more}.hidden") is False
        assert "Closes its search" in page.js(f"{more}.textContent")
        assert page.js(f"{more}.querySelectorAll('code').length") == 4
        page.js(f"{line}.focus()")
        page.press("Enter")
        assert page.wait(f"{line}.getAttribute('aria-expanded') === 'false'")
        assert page.js(f"{more}.hidden") is True


FIT = """
  const r = (e) => e.getBoundingClientRect();
  out = {tabs: qa('.masthead [role=tab]').map((t) => [t.id, Math.round(r(t).top), Math.round(r(t).right)]),
         wide: document.documentElement.scrollWidth, page: window.innerWidth};
"""


@pytest.mark.parametrize("scheme", ["light", "dark"])
@in_chromium
def test_four_tabs_fit_one_line_at_390_px_in_light_and_dark(conn, cfg, scheme):
    figures(conn, cfg)
    html = build_library_page(conn, cfg, Overrides(), NOW, controls=WebControls(csrf="tok"))
    out = run_in_page(html, cfg, FIT, size=(390, 844), scheme=scheme)
    assert [t[0] for t in out["tabs"]] == ["tab-library", "tab-songbooks", "tab-sites", "tab-requests"]
    assert len({top for _, top, _ in out["tabs"]}) == 1, out["tabs"]
    assert out["tabs"][-1][2] <= out["page"], out
    assert out["wide"] <= out["page"], out


@in_chromium
def test_on_a_phone_a_line_keeps_site_status_and_chevron(conn, cfg):
    figures(conn, cfg)
    out = run_in_page(build_library_page(conn, cfg, Overrides(), NOW), cfg, """
      const line = q('.site-line[data-site="ug"]');
      const seen = (e) => !!e && getComputedStyle(e).display !== 'none' && e.getClientRects().length > 0;
      line.click();
      const more = document.getElementById(line.getAttribute('aria-controls'));
      out = {cells: qa('.site-line[data-site="ug"] .site-cell').map(seen),
             site: seen(line.querySelector('.site-name')), status: seen(line.querySelector('.badge')),
             chevron: seen(line.querySelector('.chev')), moreFigures: seen(more.querySelector('.more-figures')),
             wide: document.documentElement.scrollWidth, page: window.innerWidth};
    """, size=(390, 844))
    assert out["cells"] and not any(out["cells"]), out
    assert out["site"] and out["status"] and out["chevron"], out
    assert out["moreFigures"] is True
    assert out["wide"] <= out["page"]


@in_chromium
def test_an_off_site_is_dimmed_and_says_off(conn, cfg):
    off = dataclasses.replace(cfg, providers={**cfg.providers, "gtptabs": ProviderPolicy(20, (10.0, 20.0), False)})
    out = run_in_page(build_library_page(conn, off, Overrides(), NOW), off, """
      const g = q('.site-line[data-site="gtptabs"]');
      out = {off: g.closest('.site').classList.contains('is-off'), badge: g.querySelector('.badge').textContent,
             state: g.querySelector('.badge').className};
    """)
    assert out == {"off": True, "badge": "Off", "state": "badge off"}


@in_chromium
def test_on_a_phone_an_opened_lines_figures_keep_their_lines_apart(conn, cfg):
    figures(conn, cfg)
    out = run_in_page(build_library_page(conn, cfg, Overrides(), NOW), cfg, """
      const line = q('.site-line[data-site="ug"]');
      line.click();
      const more = document.getElementById(line.getAttribute('aria-controls'));
      const kept = more.querySelectorAll('.more-figures dd')[1];
      out = {text: kept.innerText, small: getComputedStyle(kept.querySelector('small')).display};
    """, size=(390, 844))
    assert out["small"] == "block", out
    assert "\n" in out["text"], out  # "1 sheet" over "50% of your songs", never "1 sheet50% of your songs"
