"""caracole/web/ug_link_routes.py: an Ultimate Guitar link pasted into the library page's search box.

``GET /api/ug/link`` reads the database and the HTTP cache alone; ``POST /ug/link`` queues ``caracole ug --link``,
which a ``Recorder`` queue records and never runs. Where a test needs a page read, it reads it through the command
(tests/test_commands_ug.py's), Ultimate Guitar being ``FakeUG`` (helpers/ug_pages.py: 宋冬野's pages as UG answered
them on 2026-10-19), behind ``_common.transport_for``: no request reaches the network.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
import pytest
from conftest import add_song
from helpers.ug_pages import (
    BANMA_UG,
    SONG_DONGYE_URL,
    FakeUG,
    make_tab_page_html,
    song_dongye_chords,
    version_dict,
)

from caracole.commands import _common
from caracole.health import record_block
from caracole.ug import artist_tabs
from caracole.ug.page import read_versions
from caracole.ug_urls import read_link
from caracole.versions import upsert_version
from caracole.web.app import Request, WebApp
from caracole.web.jobs import UG_LINK, JobQueue

HOST = "localhost:8737"
ALLOWED = frozenset({"localhost", "127.0.0.1", "::1"})
TAB = "https://tabs.ultimate-guitar.com/tab/"
FOUND = f"{TAB}4180894"
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, args, emit):
        self.calls.append(list(args))
        return 0


@pytest.fixture
def queue():
    return JobQueue(Recorder(), limit=3)


@pytest.fixture
def ug(monkeypatch):
    site = FakeUG()
    monkeypatch.setattr(_common, "transport_for", lambda provider: httpx.MockTransport(site.handler))
    monkeypatch.setattr(_common, "sleep", lambda seconds: None)
    return site


def app_for(cfg, queue):
    return WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")


def get(app, url):
    response = app.handle(Request("GET", "/api/ug/link?" + urlencode({"url": url}),
                                  {"host": HOST, "sec-fetch-site": "same-origin", "accept": "application/json"}))
    return response.status, json.loads(response.body)


def post(app, url, **headers):
    sent = {"host": HOST, "content-type": "application/x-www-form-urlencoded", "sec-fetch-site": "same-origin",
            "origin": f"http://{HOST}", "accept": "application/json"} | headers
    response = app.handle(Request("POST", "/ug/link", sent, urlencode({"csrf": "tok", "url": url}).encode("utf-8")))
    return response.status, json.loads(response.body) if response.body.startswith(b"{") else response.body


def read(cfg, url):
    """The link's page read as ``caracole ug --link`` reads it (the queue's job, run here)."""
    from caracole.commands.ug import _read

    _read(cfg, read_link(url), progress=False)


def test_a_tab_caracole_never_read_may_be_read_now_and_post_queues_one_job_of_no_songs(cfg, queue, conn):
    app = app_for(cfg, queue)

    status, said = get(app, "tabs.ultimate-guitar.com/tab/4180894?ref=share")
    assert status == 200
    assert said == {"kind": "tab", "url": FOUND, "tab_id": 4180894, "type": None, "state": "auto", "tab": None,
                    "artist_page": None, "guess": {"artist": "", "title": ""}, "song": None, "hits": []}
    status, queued = post(app, FOUND)
    assert status == 202 and queued == {"job": 1, "url": "/api/jobs/1"}
    job = queue.job(1)
    assert job.song_key == UG_LINK + FOUND and job.display == "A tab on Ultimate Guitar"
    assert [s.args for s in job.steps] == [("ug", f"--link={FOUND}", "--progress")]
    assert [s.name for s in job.stages] == ["tab", "artist"]
    assert post(app, FOUND)[1]["job"] == 1  # asked again while it waits: that job
    assert 1 in app._reads  # its end drops the searches' answers kept


def test_an_artist_links_job_has_its_lists_stage_alone(cfg, queue, conn):
    app = app_for(cfg, queue)
    status, said = get(app, f"{SONG_DONGYE_URL}?filter=chords")
    assert (status, said["kind"], said["url"], said["state"]) == (200, "artist", SONG_DONGYE_URL, "auto")
    assert said["artist_page"] == {"url": SONG_DONGYE_URL, "read": False, "read_at": None}
    assert post(app, SONG_DONGYE_URL)[0] == 202
    job = queue.job(1)
    assert job.display == "An artist on Ultimate Guitar" and [s.name for s in job.stages] == ["artist"]


def test_a_tab_read_names_it_its_artists_page_and_its_song_and_post_is_refused(cfg, queue, conn, ug):
    read(cfg, FOUND)
    app = app_for(cfg, queue)

    status, said = get(app, FOUND)
    assert status == 200 and said["state"] == "found" and "why" not in said
    assert said["tab"] == {"artist": "Song Dongye (宋冬野)", "title": BANMA_UG, "type": "chords", "version": 1,
                           "rating": 4.8, "votes": 120}
    assert said["artist_page"]["url"] == SONG_DONGYE_URL and said["artist_page"]["read"] is True
    assert said["guess"] == {"artist": "宋冬野", "title": "斑马斑马"}  # as a search names it
    assert said["song"] is None
    [hit] = said["hits"]
    assert (hit["artist"], hit["title"], hit["counts"], hit["url"]) == ("宋冬野", "斑马斑马", {"chords": 2}, FOUND)
    assert (hit["artist_key"], hit["title_key"], hit["song"]) == ("宋冬野", "斑马斑马", None)
    assert post(app, FOUND) == (409, {"error": "Read already: caracole knows this page."})


def test_an_artist_link_read_gives_their_songs_as_search_rows(cfg, queue, conn, ug):
    read(cfg, SONG_DONGYE_URL)
    app = app_for(cfg, queue)

    status, said = get(app, SONG_DONGYE_URL)
    assert said["state"] == "found" and said["guess"] == {"artist": "宋冬野", "title": ""}
    assert said["tab"] is None and said["song"] is None
    titles = [h["title"] for h in said["hits"]]
    assert titles[:2] == ["斑马斑马", "董小姐"] and len(titles) == 6  # most tabbed first, as /api/artist
    assert all(h["artist"] == "宋冬野" for h in said["hits"])


def test_a_tab_only_an_artist_page_names_is_found_with_its_names_and_no_version(cfg, queue, conn):
    tabs = read_versions({"other_tabs": song_dongye_chords(t4180894=(4.8, 120))}, "other_tabs", url=SONG_DONGYE_URL)
    artist_tabs.store(conn, SONG_DONGYE_URL, "Song Dongye (宋冬野)", tabs, read_at="2026-11-01T03:30:00Z")
    app = app_for(cfg, queue)

    said = get(app, FOUND)[1]
    assert said["state"] == "found"
    assert said["tab"] == {"artist": "Song Dongye (宋冬野)", "title": BANMA_UG, "type": "chords", "version": None,
                           "rating": 4.8, "votes": 120}
    assert said["artist_page"] == {"url": SONG_DONGYE_URL, "read": True, "read_at": "2026-11-01T03:30:00Z"}


def test_a_slugged_tab_of_the_index_is_found_by_its_slugs_with_no_request(cfg, queue, conn):
    conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) VALUES "
                 "(85053, 'soda-stereo', 'de-musica-ligera', 'chords', 'last', '2026-10-01T00:00:00Z', "
                 "'soda-stereo/de-musica-ligera-chords-85053')")
    app = app_for(cfg, queue)
    said = get(app, f"{TAB}soda-stereo/de-musica-ligera-chords-85053")[1]
    assert said["state"] == "found" and said["tab"] is None and said["type"] == "chords"
    assert said["guess"] == {"artist": "Soda Stereo", "title": "De Musica Ligera"}
    assert [h["ug"] for h in said["hits"]] == ["soda-stereo/de-musica-ligera"]
    # The bare /tab/{id} of the same tab is that tab too.
    assert get(app, f"{TAB}85053")[1]["state"] == "found"


def test_a_song_of_the_library_holding_the_tab_names_it_and_says_whether_it_is_its_sheet(cfg, queue, conn):
    from caracole.library import keep_file

    song = add_song(conn, "宋冬野", "斑马，斑马")
    tabs = read_versions({"other_tabs": song_dongye_chords()}, "other_tabs", url=SONG_DONGYE_URL)
    artist_tabs.store(conn, SONG_DONGYE_URL, "Song Dongye (宋冬野)", tabs, read_at="2026-11-01T03:30:00Z")
    version = upsert_version(conn, provider="ug", tab_id="4180894", song_id=song.id, slot="sheet", kind="chords",
                             rating=4.8, votes=120, version=1, label=None, url=FOUND, raw={},
                             now="2026-11-01T03:30:00Z")
    app = app_for(cfg, queue)
    said = get(app, FOUND)[1]
    assert said["song"] == {"id": song.id, "identity": song.key, "display": "宋冬野 - 斑马，斑马", "has_sheet": False,
                            "sheet": None, "this_tab": False}
    assert said["guess"] == {"artist": "宋冬野", "title": "斑马，斑马"}  # its own names
    keep_file(conn, cfg.library_dir, song=song, version_id=version, name="sheet.txt", data=b"[ch]C[/ch]", rank=1)
    said = get(app, FOUND)[1]
    assert said["song"]["has_sheet"] is True and said["song"]["this_tab"] is True
    assert said["song"]["sheet"]
    # Its other version: the song of its names, whose sheet is another tab.
    other = get(app, f"{TAB}4689017")[1]["song"]
    assert (other["id"], other["has_sheet"], other["this_tab"]) == (song.id, True, False)


def test_a_cached_404_is_gone_and_a_slug_of_a_type_caracole_keeps_nothing_of_is_other(cfg, queue, conn, ug):
    read(cfg, f"{TAB}999")
    app = app_for(cfg, queue)
    assert get(app, f"{TAB}999")[1] | {"artist_page": None} == {
        "kind": "tab", "url": f"{TAB}999", "tab_id": 999, "type": None, "state": "gone", "why": "UG answers 404 for it",
        "tab": None, "artist_page": None, "guess": {"artist": "", "title": ""}, "song": None, "hits": []}
    assert post(app, f"{TAB}999") == (409, {"error": "Nothing to read: UG answers 404 for it."})
    said = get(app, f"{TAB}metallica/one-guitar-pro-225441")[1]
    assert (said["state"], said["type"]) == ("other", "guitar-pro")
    assert said["why"] == "it is a Guitar Pro file: caracole keeps UG's chords, tabs and ukulele chords alone"
    assert post(app, f"{TAB}metallica/one-guitar-pro-225441")[0] == 409
    pro = version_dict(7001, type="Pro", song="One", artist="Metallica")
    ug.pages[f"{TAB}7001"] = make_tab_page_html(pro, [], meta={"fileExtension": ".gp5"})
    read(cfg, f"{TAB}7001")
    said = get(app, f"{TAB}7001")[1]
    assert said["state"] == "other" and said["why"].startswith("it is a Guitar Pro file")
    assert queue.snapshot() == []


def test_no_read_goes_while_ug_cools_down_or_the_hours_lookups_are_spent(cfg, queue, conn):
    app = app_for(cfg, queue)
    record_block(conn, "ug", datetime.now(UTC), "403")
    said = get(app, FOUND)[1]
    assert said["state"] == "cooling" and said["why"].startswith("UG turned us back; no asks until ")
    assert post(app, FOUND)[0] == 429
    conn.execute("DELETE FROM kv WHERE key = 'provider:ug'")
    spent = replace(cfg, providers={**cfg.providers, "ug": replace(cfg.provider("ug"), lookup_requests=0)})
    app = app_for(spent, queue)
    said = get(app, FOUND)[1]
    assert (said["state"], said["why"]) == ("spent", "no more asks of UG this hour (60 spent)")
    status, refused = post(app, FOUND)
    assert status == 429 and refused == {"error": "Not now: no more asks of UG this hour (60 spent)."}
    assert queue.snapshot() == []


def test_a_read_that_failed_within_the_hour_is_not_sent_again(cfg, queue, conn, ug):
    ug.status[FOUND] = 500
    read(cfg, FOUND)
    app = app_for(cfg, queue)
    said = get(app, FOUND)[1]
    assert said["state"] == "failed" and said["why"].startswith("reading it failed within the hour (")
    assert post(app, FOUND)[0] == 429 and queue.snapshot() == []


def test_a_text_that_is_no_ug_link_is_refused(cfg, queue, conn):
    app = app_for(cfg, queue)
    for text in ("", "banma", "https://www.ultimate-guitar.com/explore", "https://www.youtube.com/watch?v=lzN7Thn3FV4",
                 FOUND + "x" * 600):
        status, said = get(app, text)
        assert status == 400 and said == {"error": "Not an Ultimate Guitar tab's page or artist's page."}, text
        assert post(app, text)[0] == 400
    assert queue.snapshot() == []


def test_post_needs_the_form_token(cfg, queue, conn):
    app = app_for(cfg, queue)
    sent = {"host": HOST, "content-type": "application/x-www-form-urlencoded", "sec-fetch-site": "same-origin",
            "origin": f"http://{HOST}"}
    response = app.handle(Request("POST", "/ug/link", sent, urlencode({"url": FOUND}).encode("utf-8")))
    assert response.status == 403 and queue.snapshot() == []


def test_another_sites_page_cant_read_it(cfg, queue, conn):
    app = app_for(cfg, queue)
    response = app.handle(Request("GET", "/api/ug/link?" + urlencode({"url": FOUND}),
                                  {"host": HOST, "sec-fetch-site": "cross-site"}))
    assert response.status == 403


# --- /api/search given a link ----------------------------------------------------------------------------------


@pytest.mark.parametrize("link", [FOUND, f"{SONG_DONGYE_URL}?filter=chords", "https://youtu.be/lzN7Thn3FV4"])
def test_a_search_for_a_link_sends_no_site_search_and_gives_no_hint(cfg, queue, conn, link):
    conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) VALUES "
                 "(1, 'radiohead', 'creep', 'chords', 'last', '2026-10-01T00:00:00Z', 'radiohead/creep-chords-1')")
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")  # LaCuerda's search on, as caracole serve has it
    response = app.handle(Request("GET", "/api/search?" + urlencode({"q": link}), {"host": HOST}))
    said = json.loads(response.body)
    assert response.status == 200
    assert (said["hint"], said["unseen"], said["lacuerda_search"], said["youtube"]) == (None, None, None, None)
