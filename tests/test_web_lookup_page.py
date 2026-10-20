"""caracole/web/lookup_page.py: the page that searches as you type and shows a sheet the moment it's kept.

The page is served by a real ``caracole serve`` app on a socket and run in a headless
Chromium, when this machine has one. The queue's runner stands in for ``caracole get``:
it writes the sheet into the library and prints the progress the real one prints.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from datetime import UTC, datetime
from urllib.parse import quote

import pytest

from caracole import db
from caracole.get import PROGRESS_PREFIX
from caracole.ug.index import mark_built, upsert_rows
from caracole.web.app import WebApp
from caracole.web.jobs import JobQueue, lookup_steps
from caracole.web.lookup_page import LOOKUP_CSP, SCRIPT, STYLE, lookup_page
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
SHEET = "[Intro]\nAm   F   C   G\nwalking down the river road tonight\n"


def test_the_page_carries_its_token_and_allows_its_own_script_and_style_alone():
    page = lookup_page('to"k<')
    assert 'data-csrf="to&quot;k&lt;"' in page and 'value="to&quot;k&lt;"' in page
    assert f"<script>{SCRIPT}</script>" in page and f"<style>{STYLE}</style>" in page
    assert "default-src 'none'" in LOOKUP_CSP and "connect-src 'self'" in LOOKUP_CSP
    assert "innerHTML" not in SCRIPT and "eval(" not in SCRIPT


class FakeGet:
    """``caracole get``: keeps the sheet in the library, and says so as the real one does."""

    def __init__(self, cfg):
        self.cfg = cfg

    def __call__(self, args, emit):
        folder = self.cfg.library_dir / "Radiohead" / "Creep"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "sheet.txt").write_text(SHEET + "<b>not markup</b>\n", encoding="utf-8")
        for event in ({"stage": "song", "state": "done", "detail": "added to wanted.txt, line 1"},
                      {"song": {"id": 1, "display": "Radiohead - Creep"}},
                      {"stage": "sheet", "state": "done", "detail": "tab 4169 from Ultimate Guitar"},
                      {"files": {"sheet": "Radiohead/Creep/sheet.txt"}, "seconds": 1.8}):
            emit(PROGRESS_PREFIX + json.dumps(event))
        return 0


@pytest.fixture
def served(cfg):
    queue = JobQueue(FakeGet(cfg))
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok")
    server = make_server(app, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, queue
    server.shutdown()
    server.server_close()


def dump_dom(url: str, tmp_path) -> str:
    try:
        result = subprocess.run(
            [CHROMIUM, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={tmp_path / 'chrome'}", "--window-size=1000,900", "--virtual-time-budget=5000",
             "--dump-dom", url],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        pytest.skip(f"chromium couldn't run: {e}")
    if result.returncode != 0 or "<html" not in result.stdout:
        pytest.skip(f"chromium couldn't run: {result.stderr[-500:]}")
    return result.stdout


def shown(dom: str, element: str, until: str | None = None) -> str:
    """What the browser shows in an element (up to ``until``, for one that holds others of its kind)."""
    end = re.escape(until) if until else f"</{element.split()[0]}>"
    found = re.search(rf'<{element}[^>]*>(.*?){end}', dom, re.S)
    assert found, dom[-3000:]
    return found.group(1)


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
def test_a_lookup_shows_its_stages_and_the_sheet_in_a_real_browser(cfg, served, tmp_path):
    server, queue = served
    queue.submit("Fetch Radiohead - Creep", "radiohead/creep", lookup_steps("Radiohead", "Creep"), fetching=True)
    queue.run_pending()

    dom = dump_dom(f"http://127.0.0.1:{server.server_address[1]}/lookup?job=1", tmp_path)

    reader = shown(dom, 'section class="reader"')
    assert "Radiohead - Creep" in reader and "Done." in reader
    assert "walking down the river road tonight" in shown(dom, 'pre class="sheet"')
    assert "&lt;b&gt;not markup&lt;/b&gt;" in reader and "<b>not markup</b>" not in reader  # text, never markup
    assert re.search(r'class="stage done"[^>]*>The sheet<', reader)
    assert 'href="/Radiohead/Creep/sheet.txt"' in reader


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
def test_the_search_lists_the_offline_index_as_you_type_in_a_real_browser(cfg, served, tmp_path):
    server, _ = served
    conn = db.connect(cfg.db_path)
    when = datetime(2026, 10, 19, tzinfo=UTC)
    upsert_rows(conn, [(4169, "radiohead", "creep", "chords", "radiohead/creep-chords-4169"),
                       (5001, "stone-temple-pilots", "creep", "chords", "stone-temple-pilots/creep-chords-5001")],
                "1", when)
    mark_built(conn, when)
    conn.close()

    dom = dump_dom(f"http://127.0.0.1:{server.server_address[1]}/lookup?q={quote('creep')}", tmp_path)

    results = shown(dom, 'div id="results"', until='<details class="by-name"')
    assert "On Ultimate Guitar" in results
    assert results.index("Radiohead") < results.index("Stone Temple Pilots")
    assert results.count(">Get it<") == 2 and "1 chords" in results
