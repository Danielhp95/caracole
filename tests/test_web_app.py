"""caracole/web/app.py: the routes of caracole serve, without a socket."""

import re
from pathlib import Path
from urllib.parse import urlencode

import pytest
from typer.testing import CliRunner

from caracole.cli import build_app
from caracole.songs import update_song
from caracole.web.app import Request, WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import session_value

from conftest import add_song

HOST = "localhost:8737"
ALLOWED = frozenset({"localhost", "127.0.0.1", "::1"})
JSON_BLOCK = re.compile(r'<script type="application/json" id="songs">(.*?)</script>', re.S)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, args, emit):
        self.calls.append(list(args))
        emit("ok")
        return 0


@pytest.fixture
def queue():
    return JobQueue(Recorder(), limit=3)


@pytest.fixture
def app(cfg, queue):
    return WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")


def header(response, name):
    values = [v for k, v in response.headers if k.lower() == name.lower()]
    return values[0] if values else None


def get(app, path, **headers):
    return app.handle(Request("GET", path, {"host": HOST, **headers}))


def post(app, path, fields, *, csrf="tok", **headers):
    form = ({"csrf": csrf} if csrf is not None else {}) | fields
    sent = {"host": HOST, "content-type": "application/x-www-form-urlencoded", "sec-fetch-site": "same-origin",
            "origin": f"http://{HOST}"} | headers
    return app.handle(Request("POST", path, sent, urlencode(form).encode("utf-8")))


def text(response):
    return response.body.decode("utf-8")


def shown(response):
    """The page's text as a reader sees it, entities decoded."""
    import html

    return html.unescape(text(response))


def card_data(response, song_id: int) -> dict:
    """A song's entry in the library page's data, by its id."""
    import json

    data = json.loads(JSON_BLOCK.search(text(response)).group(1))
    return next(song for song in data["songs"] if song["id"] == song_id)


# --- the library page ------------------------------------------------------------------------


def test_the_library_page_is_served_with_its_forms(app, conn):
    add_song(conn, "Radiohead", "Creep")
    response = get(app, "/")
    assert response.status == 200
    assert header(response, "content-type") == "text/html; charset=utf-8"
    body = text(response)
    assert "Radiohead - Creep" in JSON_BLOCK.search(body).group(1)
    assert '<input type="hidden" name="csrf" value="tok">' in body and 'action="/request"' in body
    assert get(app, "/index.html").status == 200


def test_every_answer_keeps_the_page_to_itself(app, conn):
    for response in (get(app, "/"), get(app, "/jobs"), get(app, "/nothing.pdf")):
        assert header(response, "x-content-type-options") == "nosniff"
        assert header(response, "x-frame-options") == "DENY"
        assert "frame-ancestors 'none'" in header(response, "content-security-policy")
        assert header(response, "referrer-policy") == "no-referrer"
        assert header(response, "cross-origin-resource-policy") == "same-origin"
        assert header(response, "cache-control") == "no-store"


def test_the_busy_songs_and_the_queue_show_on_the_page(app, conn, queue):
    creep = add_song(conn, "Radiohead", "Creep")
    add_song(conn, "Oasis", "Wonderwall")
    assert post(app, "/fetch", {"song": str(creep.id)}).status == 303
    body = text(get(app, "/"))
    assert f'"busy":[{creep.id}]' in body and '"active":1' in body
    assert 'Requests<span class="n">1</span>' in body


def test_a_name_the_server_doesnt_answer_to_is_refused(app, conn):
    # DNS rebinding: another site's name pointed at 127.0.0.1.
    for host in ("evil.example", "evil.example:8737", "", "localhost:8737/x"):
        response = app.handle(Request("GET", "/", {"host": host}))
        assert response.status == 421, host
        assert b"Radiohead" not in response.body
    assert app.handle(Request("GET", "/", {})).status == 421


def test_a_phone_on_the_lan_may_name_the_server_by_its_address(app, conn):
    # caracole serve --address 0.0.0.0, opened as http://192.168.1.20:8737/ or http://[fd7a::7]:8737/
    for host in ("192.168.1.20:8737", "[fd7a::7]:8737"):
        assert app.handle(Request("GET", "/", {"host": host})).status == 200, host


def test_the_page_says_what_is_wrong_with_overrides_toml(app, cfg):
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text("[ignore\n", encoding="utf-8")
    response = get(app, "/")
    assert response.status == 503 and "overrides.toml" in text(response)


# --- requesting a song -------------------------------------------------------------------------


def config_file(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "caracole.toml"
    path.write_text(f'library_dir = "{tmp_path / "lib"}"\nstate_dir = "{tmp_path / "state"}"\n'
                    f'cache_dir = "{tmp_path / "cache"}"\nmusic_dir = "{tmp_path / "music"}"\n', encoding="utf-8")
    return path


def test_a_request_is_written_to_wanted_txt_exactly_as_caracole_add_writes_it(app, cfg, queue, tmp_path):
    fields = {"artist": "  Soda   Stereo ", "title": "De Música | Ligera #1", "album": "Canción Animal",
              "duration": "3:33", "fetch": "1"}
    response = post(app, "/request", fields)
    assert response.status == 303 and header(response, "location") == "/jobs#job-1"

    other = tmp_path / "other"
    result = CliRunner().invoke(build_app(), ["--config", str(config_file(other)), "add", "  Soda   Stereo ",
                                              "De Música | Ligera #1", "--album", "Canción Animal",
                                              "--duration", "3:33"])
    assert result.exit_code == 0, result.output
    assert cfg.wanted_file.read_text(encoding="utf-8") == (other / "lib" / "wanted.txt").read_text(encoding="utf-8")

    job = queue.snapshot()[0]
    assert job.title == "Fetch Soda Stereo - De Música | Ligera #1" and job.fetching
    line_no = re.search(r"Added to .*, line (\d+):", result.output).group(1)
    assert job.note == f"Added to wanted.txt, line {line_no}."
    assert [s.args for s in job.steps] == [
        ("add", "--album=Canción Animal", "--duration=3:33", "--", "Soda Stereo", "De Música | Ligera #1"),
        ("match",),
        ("fetch", "--song=Soda Stereo - De Música | Ligera #1"),
        ("render",),
    ]


def test_a_request_without_fetch_only_adds(app, queue):
    assert post(app, "/request", {"artist": "Radiohead", "title": "Creep"}).status == 303
    job = queue.snapshot()[0]
    assert [s.args for s in job.steps] == [("add", "--", "Radiohead", "Creep")] and not job.fetching
    assert job.title == "Add Radiohead - Creep"


def test_fetch_it_now_on_a_song_whose_add_still_waits_fetches_it_too(app, queue):
    # The queue is busy (another song's fetch, a nightly run holding the lock): the add waits.
    assert post(app, "/request", {"artist": "Radiohead", "title": "Creep"}).status == 303
    again = post(app, "/request", {"artist": "Radiohead", "title": "Creep", "fetch": "1"})
    assert again.status == 303 and header(again, "location") == "/jobs#job-1"
    job = queue.snapshot()[0]
    assert job.fetching and job.title == "Fetch Radiohead - Creep"
    queue.run_pending()
    assert queue._runner.calls == [["add", "--", "Radiohead", "Creep"], ["match"],
                                   ["fetch", "--song=Radiohead - Creep"], ["render"]]


def test_the_cards_fetch_now_on_a_song_whose_add_still_waits_fetches_it_too(app, conn, queue):
    creep = add_song(conn, "Radiohead", "Creep")
    post(app, "/request", {"artist": "Radiohead", "title": "Creep"})
    assert post(app, "/fetch", {"song": str(creep.id)}).status == 303
    queue.run_pending()
    assert [c[0] for c in queue._runner.calls] == ["add", "match", "fetch", "render"]


def test_a_song_listed_already_is_left_as_it_is(app, cfg, queue):
    post(app, "/request", {"artist": "Radiohead", "title": "Creep"})
    queue.run_pending()
    before = cfg.wanted_file.read_text(encoding="utf-8")
    assert post(app, "/request", {"artist": "radiohead", "title": "CREEP", "fetch": "1"}).status == 303
    assert cfg.wanted_file.read_text(encoding="utf-8") == before
    assert queue.snapshot()[0].note.startswith("Already in wanted.txt, line ")


@pytest.mark.parametrize("fields,message", [
    ({"artist": "", "title": "Creep"}, "artist and a title"),
    ({"artist": "Radiohead", "title": "   "}, "artist and a title"),
    ({"artist": "Simon - Garfunkel", "title": "Mrs Robinson"}, "' - '"),
    ({"artist": "Radiohead", "title": "Creep", "duration": "soon"}, "duration"),
    ({"artist": "Radiohead", "title": "Creep", "duration": "0:00"}, "duration"),
    ({"artist": "R" * 201, "title": "Creep"}, "too long"),
    ({"artist": "Radiohead", "title": "Creep", "album": "A" * 301}, "too long"),
])
def test_a_request_the_file_cant_hold_is_refused_and_nothing_is_written(app, cfg, queue, fields, message):
    response = post(app, "/request", fields)
    assert response.status == 400
    assert message in shown(response)
    assert not cfg.wanted_file.exists() and queue.snapshot() == []


def test_a_line_break_cant_add_a_second_song(app, cfg, queue):
    assert post(app, "/request", {"artist": "Radiohead", "title": "Creep\nOasis - Wonderwall"}).status == 303
    from caracole.wanted import parse_wanted

    lines, errors = parse_wanted(cfg.wanted_file.read_text(encoding="utf-8"))
    assert [(line.artist, line.title) for line in lines] == [("Radiohead", "Creep Oasis - Wonderwall")]
    assert errors == []


def test_a_full_queue_still_keeps_the_song_in_wanted_txt(app, cfg, queue):
    for n in range(3):
        assert post(app, "/request", {"artist": "A", "title": f"Song {n}"}).status == 303
    response = post(app, "/request", {"artist": "A", "title": "Song 3", "fetch": "1"})
    assert response.status == 503
    assert "wanted.txt" in text(response) and "A - Song 3" in cfg.wanted_file.read_text(encoding="utf-8")


# --- fetching a song now ------------------------------------------------------------------------


def test_fetch_now_queues_match_fetch_and_render_for_that_song(app, conn, queue):
    creep = add_song(conn, "Radiohead", "Creep")
    response = post(app, "/fetch", {"song": str(creep.id)})
    assert response.status == 303 and header(response, "location") == "/jobs#job-1"
    job = queue.snapshot()[0]
    assert [s.args for s in job.steps] == [("match",), ("fetch", "--song=Radiohead - Creep"), ("render",)]
    assert job.fetching and job.song_key == creep.key


def test_fetch_now_needs_a_song_of_the_library(app, conn, cfg):
    ignored = add_song(conn, "Queen", "Don't Stop Me Now")
    update_song(conn, ignored.id, status="ignored")
    assert post(app, "/fetch", {"song": "999"}).status == 404
    assert post(app, "/fetch", {"song": "x"}).status == 400
    assert post(app, "/fetch", {"song": str(ignored.id)}).status == 409


REVIEW = [{"artist_key": "radiohead", "song_key": "creep", "score": 88, "step": "fuzzy"},
          {"artist_key": "radiohead", "song_key": "creep-acoustic", "score": 86, "step": "fuzzy"}]


def test_fetch_now_of_a_song_that_needs_review_is_refused_before_anything_is_queued(app, conn, queue):
    # `caracole fetch --song` would only fail with "needs review first".
    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="review", match_candidates=REVIEW, review=True)
    response = post(app, "/fetch", {"song": str(creep.id)})
    assert response.status == 409 and "caracole review" in text(response)
    assert queue.snapshot() == []
    assert '"fetchable":false' in text(get(app, "/"))


def test_a_review_that_overrides_toml_settles_or_an_artist_page_answers_can_be_fetched(app, conn, cfg, queue):
    from caracole.overrides import add_match

    settled = add_song(conn, "Radiohead", "Creep")
    update_song(conn, settled.id, match_decision="review", match_candidates=REVIEW, review=True)
    add_match(cfg.overrides_file, settled.display, "radiohead/creep")  # by hand: `caracole match` comes first
    covers = add_song(conn, "Soda Stereo", "De Música Ligera")  # only other artists' songs of its title
    update_song(conn, covers.id, match_decision="review", review=True, match_candidates=[
        {"artist_key": "ana-carolina", "song_key": "de-musica-ligera", "score": 90, "step": "title_only"}])
    assert post(app, "/fetch", {"song": str(settled.id)}).status == 303
    assert post(app, "/fetch", {"song": str(covers.id)}).status == 303
    assert '"fetchable":false' not in text(get(app, "/"))


def test_a_reject_settles_a_review_only_when_it_names_every_candidate(app, conn, cfg, queue):
    # None of these, then the rematch: the song may be in review again, with the candidates it
    # hadn't shown. Its [reject] names none of those, so `caracole fetch --song` would still refuse it.
    from caracole.overrides import add_reject

    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="review", match_candidates=REVIEW, review=True)
    add_reject(cfg.overrides_file, creep.display, ["radiohead/creep-live", "radiohead/creep"])
    response = post(app, "/fetch", {"song": str(creep.id)})
    assert response.status == 409 and "Review it first" in shown(response) and queue.snapshot() == []
    card = card_data(get(app, "/"), creep.id)
    # Held (WebControls.held): the card shows its picker, and no Fetch now that could only fail.
    assert card["fetchable"] is False and [c["ref"] for c in card["candidates"]] == SHOWN.split()
    # Every candidate rejected: the job's `caracole match` reads that before the fetch.
    add_reject(cfg.overrides_file, creep.display, ["radiohead/creep-acoustic"])
    assert card_data(get(app, "/"), creep.id)["fetchable"] is True
    assert post(app, "/fetch", {"song": str(creep.id)}).status == 303


def test_fetch_now_of_a_song_ignored_in_overrides_toml_is_refused(app, conn, cfg, queue):
    from caracole.overrides import add_ignore

    creep = add_song(conn, "Radiohead", "Creep")
    add_ignore(cfg.overrides_file, creep.display)
    response = post(app, "/fetch", {"song": str(creep.id)})
    assert response.status == 409 and "ignored" in text(response)
    assert queue.snapshot() == []


# --- picking a review's candidate ---------------------------------------------------------------

SHOWN = "radiohead/creep radiohead/creep-acoustic"


def in_review(conn, cands=REVIEW):
    song = add_song(conn, "Radiohead", "Creep")
    update_song(conn, song.id, match_decision="review", match_candidates=cands, review=True)
    return song


def test_a_pick_queues_caracole_review_then_the_fetch(app, conn, queue):
    creep = in_review(conn)
    response = post(app, "/review", {"song": str(creep.id), "pick": "radiohead/creep", "shown": SHOWN, "fetch": "1"})
    assert response.status == 303 and header(response, "location") == "/jobs#job-1"
    job = queue.snapshot()[0]
    # caracole review --song matches again and rewrites the pages itself: no `caracole match` step.
    assert [s.args for s in job.steps] == [
        ("review", "--song=Radiohead - Creep", "--pick=radiohead/creep"),
        ("fetch", "--song=Radiohead - Creep"),
        ("render",),
    ]
    assert job.fetching and job.song_key == creep.key
    assert job.title == "Pick radiohead/creep for Radiohead - Creep, and fetch it"


def test_a_pick_without_fetch_only_answers(app, conn, queue):
    creep = in_review(conn)
    assert post(app, "/review", {"song": str(creep.id), "pick": "radiohead/creep-acoustic",
                                 "shown": SHOWN}).status == 303
    job = queue.snapshot()[0]
    assert [s.args for s in job.steps] == [("review", "--song=Radiohead - Creep", "--pick=radiohead/creep-acoustic")]
    assert not job.fetching and job.title == "Pick radiohead/creep-acoustic for Radiohead - Creep"


def test_none_of_these_rejects_the_candidates_shown_and_fetches_nothing(app, conn, queue):
    creep = in_review(conn)
    assert post(app, "/review", {"song": str(creep.id), "pick": "none", "shown": SHOWN, "fetch": "1"}).status == 303
    job = queue.snapshot()[0]
    assert [s.args for s in job.steps] == [("review", "--song=Radiohead - Creep", "--none",
                                            "--seen=radiohead/creep", "--seen=radiohead/creep-acoustic")]
    assert not job.fetching and job.title == "None of these for Radiohead - Creep"


@pytest.mark.parametrize("fields,status,message", [
    ({"song": "x", "pick": "radiohead/creep", "shown": SHOWN}, 400, "Which song?"),
    ({"song": "999", "pick": "radiohead/creep", "shown": SHOWN}, 404, "isn't in the library"),
    ({"pick": "", "shown": SHOWN}, 400, "Pick a candidate, or None of these"),
    ({"pick": "radiohead/high-and-dry", "shown": SHOWN}, 400, "isn't one of its candidates"),
    # The nightly run matched it again since the page was loaded: it may show other candidates now.
    ({"pick": "radiohead/creep", "shown": "radiohead/creep"}, 409, "reload the library"),
    ({"pick": "none", "shown": ""}, 409, "reload the library"),
])
def test_an_answer_that_cant_be_given_is_refused_before_anything_is_queued(app, conn, queue, fields, status,
                                                                             message):
    creep = in_review(conn)
    response = post(app, "/review", {"song": str(creep.id)} | fields)
    assert response.status == status
    assert message in shown(response)
    assert queue.snapshot() == []


def test_a_song_that_needs_no_review_or_is_ignored_has_nothing_to_pick(app, conn, cfg, queue):
    from caracole.overrides import add_ignore

    settled = add_song(conn, "Oasis", "Wonderwall")
    update_song(conn, settled.id, match_decision="accept", match_candidates=REVIEW)
    response = post(app, "/review", {"song": str(settled.id), "pick": "radiohead/creep", "shown": SHOWN})
    assert response.status == 409 and "doesn't need review" in shown(response)
    creep = in_review(conn)
    add_ignore(cfg.overrides_file, creep.display)
    response = post(app, "/review", {"song": str(creep.id), "pick": "radiohead/creep", "shown": SHOWN})
    assert response.status == 409 and "ignored" in shown(response)
    assert queue.snapshot() == []


def test_a_pick_waits_for_the_songs_request_to_end(app, conn, queue):
    # Its add, say: the pick's `caracole review` must come after it, never be dropped into it.
    creep = in_review(conn)
    post(app, "/request", {"artist": "Radiohead", "title": "Creep"})
    response = post(app, "/review", {"song": str(creep.id), "pick": "radiohead/creep", "shown": SHOWN})
    assert response.status == 409 and "waiting or running" in shown(response)
    assert len(queue.snapshot()) == 1
    queue.run_pending()
    assert post(app, "/review", {"song": str(creep.id), "pick": "radiohead/creep", "shown": SHOWN}).status == 303


@pytest.mark.parametrize("csrf,headers", [
    (None, {}),
    ("wrong", {}),
    ("tok", {"sec-fetch-site": "cross-site", "origin": "http://evil.example"}),
])
def test_a_pick_from_anywhere_but_the_page_is_refused(app, conn, queue, csrf, headers):
    creep = in_review(conn)
    response = post(app, "/review", {"song": str(creep.id), "pick": "radiohead/creep", "shown": SHOWN},
                    csrf=csrf, **headers)
    assert response.status == 403 and queue.snapshot() == []


def picker_of(body: str) -> str:
    found = re.search(r'<form class="pick-form" method="post" action="/review">(.*?)</form>', body, re.S)
    assert found, body[-2000:]
    return found.group(1)


def test_the_picker_has_a_page_of_its_own_with_no_script(app, conn):
    conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) VALUES "
                 "(7, 'radiohead', 'creep', 'chords', '1', 'x', 'radiohead/creep-chords-7')")
    creep = in_review(conn)
    response = get(app, f"/review?song={creep.id}")
    assert response.status == 200
    body = text(response)
    assert "<script" not in body and "form-action 'self'" in header(response, "content-security-policy")
    form = picker_of(body)
    assert '<input type="hidden" name="csrf" value="tok">' in form
    assert f'<input type="hidden" name="song" value="{creep.id}">' in form
    assert f'<input type="hidden" name="shown" value="{SHOWN}">' in form
    radios = re.findall(r'<input type="radio" name="pick" value="([^"]*)" required', form)
    assert radios == ["radiohead/creep", "radiohead/creep-acoustic", "none"]
    assert re.search(r'value="radiohead/creep" required autofocus>', form)  # the page is for this alone
    assert "<legend>Which Ultimate Guitar song is “Creep” by Radiohead?</legend>" in shown(response)
    assert '<span class="choice-name">1. Radiohead – Creep</span>' in form
    assert 'href="https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-7"' in form
    assert '<input type="checkbox" name="fetch" value="1" checked>' in form and ">Pick</button>" in form


def test_the_pickers_page_escapes_every_name(app, conn):
    evil = add_song(conn, "<b>Evil</b>", 'Song "<script>alert(1)</script>"')
    update_song(conn, evil.id, match_decision="review", review=True, match_candidates=[
        {"artist_key": "evil", "song_key": "song", "score": 80, "step": "fuzzy_title"}])
    body = text(get(app, f"/review?song={evil.id}"))
    assert "<script>alert" not in body and "<b>Evil" not in body
    assert "&lt;b&gt;Evil&lt;/b&gt;" in body


@pytest.mark.parametrize("path,status", [("/review", 400), ("/review?song=x", 400), ("/review?song=999", 404)])
def test_the_pickers_page_needs_a_song_of_the_library(app, conn, path, status):
    assert get(app, path).status == status


def test_the_pickers_page_of_a_song_that_needs_no_review_says_so(app, conn):
    settled = add_song(conn, "Oasis", "Wonderwall")
    update_song(conn, settled.id, match_decision="accept")
    response = get(app, f"/review?song={settled.id}")
    assert response.status == 409 and "doesn't need review" in shown(response)
    assert 'action="/review"' not in text(response)


def test_a_request_that_ends_in_a_review_shows_its_picker_on_the_requests_page(app, conn, queue):
    post(app, "/request", {"artist": "Radiohead", "title": "Creep", "fetch": "1"})
    creep = in_review(conn)  # what its `caracole add` found
    assert 'action="/review"' not in text(get(app, "/jobs"))  # not while it runs
    queue.run_pending()
    body = text(get(app, "/jobs"))
    job = re.search(r'<article class="job" id="job-1">.*?</article>', body, re.S).group(0)
    assert "isn't sure which Ultimate Guitar song" in job
    form = picker_of(job)
    assert f'name="song" value="{creep.id}"' in form and 'value="radiohead/creep" required' in form
    assert "autofocus" not in form  # the page has other things to read


def test_while_the_requests_page_refreshes_it_links_to_the_picker_instead(app, conn, queue):
    # A reload every 10 seconds would undo a choice half made.
    post(app, "/request", {"artist": "Radiohead", "title": "Creep"})
    creep = in_review(conn)
    queue.run_pending()
    post(app, "/request", {"artist": "Oasis", "title": "Wonderwall"})  # waits: the page refreshes
    body = text(get(app, "/jobs"))
    job = re.search(r'<article class="job" id="job-1">.*?</article>', body, re.S).group(0)
    assert 'action="/review"' not in job and f'href="/review?song={creep.id}"' in job
    still = text(get(app, "/jobs?refresh=0"))
    assert 'action="/review"' in re.search(r'<article class="job" id="job-1">.*?</article>', still, re.S).group(0)


def test_a_request_whose_song_was_picked_since_shows_no_picker(app, conn, queue):
    post(app, "/request", {"artist": "Radiohead", "title": "Creep"})
    creep = in_review(conn)
    queue.run_pending()
    update_song(conn, creep.id, review=False, match_decision="accept")
    assert "/review" not in text(get(app, "/jobs"))


# --- a song not found: caracole search's hits ---------------------------------------------------


def not_found(conn):
    conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) VALUES "
                 "(1, 'radiohead', 'creep', 'chords', '1', 'x', 'radiohead/creep-chords-1'), "
                 "(2, 'radiohead', 'high-and-dry', 'chords', '1', 'x', 'radiohead/high-and-dry-chords-2')")
    song = add_song(conn, "Radio Head", "Crep")
    update_song(conn, song.id, match_decision="not_found")
    return song


HITS = "radiohead/creep radiohead/high-and-dry"


def test_the_pickers_page_of_a_song_not_found_offers_caracole_searchs_hits(app, conn):
    crep = not_found(conn)
    response = get(app, f"/review?song={crep.id}")
    assert response.status == 200
    body = shown(response)
    assert "caracole search" in body and "[match]" in body
    form = picker_of(text(response))
    radios = re.findall(r'<input type="radio" name="pick" value="([^"]*)" required', form)
    assert radios == ["radiohead/creep", "radiohead/high-and-dry"]  # and no "None of these": nothing to reject
    assert f'name="shown" value="{HITS}"' in form
    assert "a caracole search hit for its artist and title" in form


def test_a_song_not_found_with_no_search_hit_has_nothing_to_pick(app, conn):
    song = add_song(conn, "Nobody", "Nothing Like It")
    update_song(conn, song.id, match_decision="not_found")
    response = get(app, f"/review?song={song.id}")
    assert response.status == 409 and "caracole search finds nothing" in shown(response)


def test_a_pick_of_a_search_hit_queues_caracole_review_then_the_fetch(app, conn, queue):
    crep = not_found(conn)
    fields = {"song": str(crep.id), "pick": "radiohead/creep", "shown": HITS, "fetch": "1"}
    assert post(app, "/review", fields).status == 303
    assert [s.args for s in queue.snapshot()[0].steps] == [
        ("review", "--song=Radio Head - Crep", "--pick=radiohead/creep"),
        ("fetch", "--song=Radio Head - Crep"),
        ("render",),
    ]


@pytest.mark.parametrize("fields,status", [
    ({"pick": "none", "shown": HITS}, 400),
    ({"pick": "radiohead/creep", "shown": "radiohead/creep"}, 409),
])
def test_a_song_not_found_takes_a_search_hit_alone(app, conn, queue, fields, status):
    crep = not_found(conn)
    assert post(app, "/review", {"song": str(crep.id)} | fields).status == status
    assert queue.snapshot() == []


def test_a_request_that_ends_not_found_links_to_its_search_hits(app, conn, queue):
    post(app, "/request", {"artist": "Radio Head", "title": "Crep"})
    crep = not_found(conn)
    queue.run_pending()
    job = re.search(r'<article class="job" id="job-1">.*?</article>', text(get(app, "/jobs")), re.S).group(0)
    assert f'href="/review?song={crep.id}"' in job and 'action="/review"' not in job


class CliRunnerJobs:
    """Runs each step as the `caracole` command line, in this process, against ``config``."""

    def __init__(self, config: Path):
        self.config = config
        self.outputs = []

    def __call__(self, args, emit):
        result = CliRunner().invoke(build_app(), ["--config", str(self.config), *args])
        for line in result.output.splitlines():
            emit(line)
        self.outputs.append(result.output)
        return result.exit_code


def test_a_pick_writes_what_caracole_review_writes(cfg, conn, tmp_path):
    from datetime import UTC, datetime

    from caracole.overrides import load_overrides
    from caracole.songs import get_song
    from caracole.ug.index import mark_built

    config = tmp_path / "caracole.toml"
    config.write_text(f'library_dir = "{cfg.library_dir}"\nstate_dir = "{cfg.state_dir}"\n'
                      f'cache_dir = "{cfg.cache_dir}"\nmusic_dir = "{cfg.music_dir}"\n', encoding="utf-8")
    conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) VALUES "
                 "(1, 'radiohead', 'creep', 'chords', '1', 'x', 'radiohead/creep-chords-1')")
    mark_built(conn, datetime(2026, 10, 18, 3, 30, tzinfo=UTC))
    song = add_song(conn, "Radio Head", "Crep")
    update_song(conn, song.id, match_decision="review", review=True, match_candidates=[
        {"artist_key": "radiohead", "song_key": "creep", "score": 89, "step": "fuzzy_artist"}])
    runner = CliRunnerJobs(config)
    queue = JobQueue(runner)
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
    assert post(app, "/review", {"song": str(song.id), "pick": "radiohead/creep", "shown": "radiohead/creep"}).status == 303
    queue.run_pending()
    assert queue.snapshot()[0].state == "done", runner.outputs
    o = load_overrides(cfg.overrides_file)
    assert o.match[song.key] == ("radiohead", "creep") and o.alias["radio-head"] == ("radiohead",)
    assert get_song(conn, song.id).match_decision == "accept"
    assert "Now matched to radiohead/creep" in runner.outputs[0]


# --- what every write must carry --------------------------------------------------------------


@pytest.mark.parametrize("csrf,headers", [
    (None, {}),  # no token
    ("wrong", {}),
    ("tok", {"sec-fetch-site": "cross-site", "origin": "http://evil.example"}),
    ("tok", {"sec-fetch-site": "same-site"}),
])
def test_a_write_from_anywhere_but_the_page_is_refused(app, cfg, queue, csrf, headers):
    response = post(app, "/request", {"artist": "Radiohead", "title": "Creep"}, csrf=csrf, **headers)
    assert response.status == 403
    assert not cfg.wanted_file.exists() and queue.snapshot() == []


def test_a_plain_http_origin_is_compared_with_the_host(app, cfg):
    sent = {"host": HOST, "content-type": "application/x-www-form-urlencoded", "origin": "http://evil.example"}
    body = urlencode({"csrf": "tok", "artist": "Radiohead", "title": "Creep"}).encode()
    assert app.handle(Request("POST", "/request", sent, body)).status == 403
    sent["origin"] = f"http://{HOST}"
    assert app.handle(Request("POST", "/request", sent, body)).status == 303


def test_only_forms_are_read(app, cfg):
    sent = {"host": HOST, "content-type": "application/json", "sec-fetch-site": "same-origin"}
    assert app.handle(Request("POST", "/request", sent, b'{"artist": "A"}')).status == 415


def test_other_methods_and_paths_are_refused(app):
    assert app.handle(Request("PUT", "/", {"host": HOST})).status == 405
    assert app.handle(Request("DELETE", "/jobs", {"host": HOST})).status == 405
    assert post(app, "/elsewhere", {}).status == 404


# --- the requests page ---------------------------------------------------------------------------


def test_the_requests_page_lists_each_job_and_its_output(app, queue):
    post(app, "/request", {"artist": "Evil", "title": "<script>alert(1)</script>", "fetch": "1"})
    body = text(get(app, "/jobs"))
    assert '<meta http-equiv="refresh" content="10">' in body  # while one waits or runs
    assert 'id="job-1"' in body and "Queued" in body
    assert "<script>alert" not in body and "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    queue.run_pending()
    body = text(get(app, "/jobs"))
    assert 'http-equiv="refresh"' not in body
    assert "Done" in body and "Fetch from Ultimate Guitar" in body and "<pre>ok" in body


def test_the_requests_page_can_stop_refreshing_so_an_output_can_be_read(app, queue):
    post(app, "/request", {"artist": "Radiohead", "title": "Creep"})
    body = text(get(app, "/jobs"))
    assert 'href="/jobs?refresh=0"' in body and "Stop refreshing" in body
    still = text(get(app, "/jobs?refresh=0"))
    assert 'http-equiv="refresh"' not in still and 'href="/jobs"' in still
    assert 'href="/jobs?refresh=0"' not in still


def test_the_newest_requests_output_is_open_and_the_older_ones_closed(app, queue):
    post(app, "/request", {"artist": "Radiohead", "title": "Creep"})
    queue.run_pending()
    post(app, "/request", {"artist": "Oasis", "title": "Wonderwall"})
    queue.run_pending()
    body = text(get(app, "/jobs"))
    newest, older = re.findall(r'<article class="job" id="job-\d+">.*?</article>', body, re.S)
    assert "Oasis" in newest and "<details open>" in newest
    assert "Radiohead" in older and "<details>" in older and "<details open>" not in older


def test_the_requests_page_with_nothing_queued(app):
    body = text(get(app, "/jobs"))
    assert "No requests yet" in body


# --- the library's files ----------------------------------------------------------------------


def test_the_cards_links_open_the_songs_files(app, cfg):
    folder = cfg.library_dir / "Soda Stereo" / "De Música Ligera"
    folder.mkdir(parents=True)
    (folder / "sheet.pdf").write_bytes(b"%PDF")
    (folder / "guitar-1.gp5").write_bytes(b"gp")
    response = get(app, "/Soda%20Stereo/De%20M%C3%BAsica%20Ligera/sheet.pdf?x=1")
    assert response.status == 200 and response.body == b"%PDF"
    assert header(response, "content-type") == "application/pdf"
    download = get(app, "/Soda%20Stereo/De%20M%C3%BAsica%20Ligera/guitar-1.gp5")
    assert header(download, "content-disposition") == "attachment"


def test_no_page_shows_a_secret(tmp_path, queue, conn):
    from caracole.config import load_config

    secret_cfg = load_config(None, env={
        "HOME": str(tmp_path / "home"), "STATE_DIRECTORY": str(tmp_path / "state"),
        "CACHE_DIRECTORY": str(tmp_path / "cache"), "CARACOLE_NTFY_TOKEN": "ntfy-secret-token",
        "CARACOLE_SPOTIFY_CLIENT_SECRET": "spotify-secret",
    })
    app = WebApp(secret_cfg, queue, allowed=ALLOWED, csrf="tok")
    add_song(conn, "Radiohead", "Creep")
    post(app, "/request", {"artist": "Oasis", "title": "Wonderwall", "fetch": "1"})
    queue.run_pending()
    for path in ("/", "/jobs"):
        body = get(app, path).body
        assert b"ntfy-secret-token" not in body and b"spotify-secret" not in body, path


def test_the_database_and_secrets_are_never_served(app, cfg, conn):
    add_song(conn, "Radiohead", "Creep")
    (cfg.library_dir).mkdir(parents=True, exist_ok=True)
    (cfg.library_dir / "Evil").symlink_to(cfg.state_dir, target_is_directory=True)
    for path in ("/Evil/caracole.sqlite", "/../state/caracole.sqlite", "/%2e%2e/state/caracole.sqlite",
                 "/state/caracole.sqlite", "/caracole.sqlite"):
        assert get(app, path).status == 404, path


# --- an access token ------------------------------------------------------------------------------


@pytest.fixture
def locked(cfg, queue):
    return WebApp(cfg, queue, allowed=ALLOWED, csrf="tok", access_token="a-long-random-access-token")


def test_with_an_access_token_nothing_is_shown_before_signing_in(locked, conn):
    add_song(conn, "Radiohead", "Creep")
    for path in ("/", "/jobs", "/_todo.md"):
        response = get(locked, path)
        assert response.status == 401 and b"Radiohead" not in response.body
        assert 'action="/login"' in text(response)
    assert post(locked, "/request", {"artist": "A", "title": "B"}).status == 401


def test_signing_in_sets_a_cookie_that_opens_the_library(locked, conn):
    add_song(conn, "Radiohead", "Creep")
    assert post(locked, "/login", {"token": "wrong"}).status == 401
    assert post(locked, "/login", {"token": "a-long-random-access-token"}, csrf="bad").status == 403
    response = post(locked, "/login", {"token": "a-long-random-access-token"})
    assert response.status == 303 and header(response, "location") == "/"
    cookie = header(response, "set-cookie")
    value = session_value("a-long-random-access-token")
    assert cookie.startswith(f"caracole_session={value};")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/" in cookie
    assert "a-long-random-access-token" not in cookie
    signed_in = get(locked, "/", cookie=f"caracole_session={value}")
    assert signed_in.status == 200 and "Radiohead - Creep" in text(signed_in)
    assert get(locked, "/", cookie="caracole_session=forged").status == 401
