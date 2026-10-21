"""caracole/web/app.py: the routes of caracole serve, without a socket."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlencode

import pytest
from typer.testing import CliRunner

from caracole.cli import build_app
from caracole.library import song_dir
from caracole.songs import update_song
from caracole.web.app import Request, WebApp
from caracole.web.jobs import JobQueue
from caracole.web.security import session_value

from conftest import add_song
from helpers.rendered import rendered_song

HOST = "localhost:8737"
ALLOWED = frozenset({"localhost", "127.0.0.1", "::1"})
BEYOND_SQLITE = "99999999999999999999999"  # a song id larger than any SQLite integer
JSON_BLOCK = re.compile(r'<script type="application/json" id="songs">(.*?)</script>', re.S)
META_POLICY = re.compile(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">')


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


JSON = "application/json"


def get_json(app, path, *, token="tok", **headers):
    """A request from the page's script: JSON, the page's form token in a header, from its own origin."""
    sent = {"accept": JSON, "sec-fetch-site": "same-origin"} | (
        {"x-caracole-form-token": token} if token is not None else {}) | headers
    return get(app, path, **sent)


def answer(response):
    assert header(response, "content-type") == "application/json; charset=utf-8", response.body[:300]
    return json.loads(response.body)


def shown(response):
    """The page's text as a reader sees it, entities decoded."""
    import html

    return html.unescape(text(response))


def shown_text(html_text: str) -> str:
    """A piece of a page as a reader reads it: no tags, entities decoded, spaces folded."""
    import html

    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", html_text)).split())


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
    # The requests waiting or running, each with its line, so the cards show it at once.
    server = json.loads(JSON_BLOCK.search(body).group(1))["server"]
    assert [(j["id"], j["songId"], j["line"]["text"]) for j in server["jobs"]] == [(1, creep.id, "Queued…")]


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
    assert response.status == 303 and header(response, "location") == "/jobs?job=1#job-1"

    other = tmp_path / "other"
    result = CliRunner().invoke(build_app(), ["--config", str(config_file(other)), "-v", "add", "  Soda   Stereo ",
                                              "De Música | Ligera #1", "--album", "Canción Animal",
                                              "--duration", "3:33"])
    assert result.exit_code == 0, result.output
    assert cfg.wanted_file.read_text(encoding="utf-8") == (other / "lib" / "wanted.txt").read_text(encoding="utf-8")

    job = queue.snapshot()[0]
    assert job.title == "Fetch Soda Stereo - De Música | Ligera #1" and job.fetching
    line_no = re.search(r"wanted\.txt line (\d+)", result.output).group(1)
    assert job.note == f"Added to wanted.txt, line {line_no}."
    # One `caracole get`, which adds the song itself: the sheet first, at the lookup pace.
    assert [s.args for s in job.steps] == [
        ("get", "--progress", "--album=Canción Animal", "--duration=3:33", "--", "Soda Stereo",
         "De Música | Ligera #1"),
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
    assert again.status == 303 and header(again, "location") == "/jobs?job=1#job-1"
    job = queue.snapshot()[0]
    assert job.fetching and job.title == "Fetch Radiohead - Creep"
    queue.run_pending()
    assert queue._runner.calls == [["get", "--progress", "--", "Radiohead", "Creep"]]  # it adds the song too


def test_the_cards_fetch_now_on_a_song_whose_add_still_waits_fetches_it_too(app, conn, queue):
    creep = add_song(conn, "Radiohead", "Creep")
    post(app, "/request", {"artist": "Radiohead", "title": "Creep"})
    assert post(app, "/fetch", {"song": str(creep.id)}).status == 303
    queue.run_pending()
    assert [c[0] for c in queue._runner.calls] == ["get"]


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


def test_fetch_now_looks_that_song_up_now(app, conn, queue):
    creep = add_song(conn, "Radiohead", "Creep")
    response = post(app, "/fetch", {"song": str(creep.id)})
    assert response.status == 303 and header(response, "location") == "/jobs?job=1#job-1"
    job = queue.snapshot()[0]
    assert [s.args for s in job.steps] == [("get", "--progress", "--", "Radiohead", "Creep")]
    assert job.fetching and job.song_key == creep.key


def test_fetch_now_needs_a_song_of_the_library(app, conn, cfg):
    ignored = add_song(conn, "Queen", "Don't Stop Me Now")
    update_song(conn, ignored.id, status="ignored")
    assert post(app, "/fetch", {"song": "999"}).status == 404
    for huge in (BEYOND_SQLITE, f"-{BEYOND_SQLITE}"):  # no SQLite integer: no song either
        assert post(app, "/fetch", {"song": huge}).status == 404
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


# --- removing a song -----------------------------------------------------------------------------


def a_kept_song(conn, cfg):
    from caracole.library import keep_file, song_dir
    from caracole.versions import upsert_version

    cfg.wanted_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.wanted_file.write_text("Radiohead - Creep\n", encoding="utf-8")
    creep = add_song(conn, "Radiohead", "Creep", source="wanted", source_id="radiohead/creep")
    vid = upsert_version(conn, provider="ug", tab_id="101", song_id=creep.id, slot="sheet", kind="chords",
                         rating=4.5, votes=10, version=1, label=None, url="https://u/101", raw={},
                         now="2026-10-01T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=creep, version_id=vid, name="sheet.txt", data=b"[Am]", rank=1)
    (song_dir(cfg.library_dir, creep) / "notes <b>.md").write_text("capo 2", encoding="utf-8")
    return creep


def test_remove_asks_first_on_a_page_that_says_what_goes_and_what_stays(app, conn, cfg, queue):
    creep = a_kept_song(conn, cfg)
    response = post(app, "/remove", {"song": str(creep.id)})
    assert response.status == 200 and queue.snapshot() == []
    page = shown(response)
    assert "Remove Radiohead - Creep?" in page
    assert "its line in wanted.txt (line 1)" in page and "1 file caracole wrote in Radiohead/Creep/: sheet.txt" in page
    assert "Radiohead/Creep/notes <b>.md: caracole didn't write it" in page and "<b>" not in text(response)
    assert "until you ask for it again" in page
    form = re.search(r'<form[^>]*action="/remove"[^>]*>(.*?)</form>', text(response), re.S)
    assert form and 'method="post"' in form.group(0)
    for name, value in (("csrf", "tok"), ("song", str(creep.id)), ("key", creep.key), ("confirm", "1")):
        assert f'name="{name}" value="{value}"' in form.group(1), name
    assert 'href="/"' in text(response)  # keep it
    assert header(response, "content-security-policy").startswith("default-src 'none'")
    assert cfg.wanted_file.read_text(encoding="utf-8") == "Radiohead - Creep\n"


def test_confirming_queues_caracole_remove_for_that_song(app, conn, cfg, queue):
    creep = a_kept_song(conn, cfg)
    response = post(app, "/remove", {"song": str(creep.id), "key": creep.key, "confirm": "1"})
    # Back to the library, at the song's card, which says how its removal goes.
    assert response.status == 303 and header(response, "location") == f"/#song={creep.id}"
    job = queue.snapshot()[0]
    assert job.title == "Remove Radiohead - Creep" and not job.fetching
    assert [s.args for s in job.steps] == [("remove", "--yes", "--", "Radiohead - Creep")]
    assert f'"removing":[{creep.id}]' in text(get(app, "/"))
    # Asked again while it waits, it is the same request.
    assert post(app, "/remove", {"song": str(creep.id), "key": creep.key, "confirm": "1"}).status == 303
    assert [j.title for j in queue.snapshot()] == ["Remove Radiohead - Creep"]
    queue.run_pending()
    assert queue.snapshot()[0].state == "done"


def test_a_removal_confirmed_for_another_song_than_the_id_now_names_is_refused(app, conn, cfg, queue):
    creep = a_kept_song(conn, cfg)
    response = post(app, "/remove", {"song": str(creep.id), "key": "oasis/wonderwall", "confirm": "1"})
    assert response.status == 409 and queue.snapshot() == []
    assert post(app, "/remove", {"song": "999"}).status == 404
    for huge in (BEYOND_SQLITE, f"-{BEYOND_SQLITE}"):  # no SQLite integer: no song, asked or confirmed
        assert post(app, "/remove", {"song": huge}).status == 404
        assert post(app, "/remove", {"song": huge, "key": creep.key, "confirm": "1"}).status == 404
    assert post(app, "/remove", {"song": "x"}).status == 400


def test_a_removal_says_how_it_goes_on_jobs_and_on_the_songs_own_card(app, conn, cfg, queue):
    creep = a_kept_song(conn, cfg)
    post(app, "/remove", {"song": str(creep.id), "key": creep.key, "confirm": "1"})
    # The page's script follows it on the song's card: a removal, of that song, never a song just requested.
    server = json.loads(JSON_BLOCK.search(text(get(app, "/"))).group(1))["server"]
    assert server["removing"] == [creep.id]
    [view] = server["jobs"]
    assert view["kind"] == "remove" and view["songId"] == creep.id and view["line"]["text"] == "Queued…"
    (job_id, item), = JOB_ITEM.findall(text(get(app, "/jobs")))
    line = re.search(r'<p class="line">(.*?)</p>', item, re.S).group(1)
    assert "Radiohead - Creep" in line and "Remove Radiohead" not in line and "Queued…" in line
    queue.run_pending()
    conn.execute("DELETE FROM songs WHERE id = ?", (creep.id,))  # as caracole remove does
    (job_id, item), = JOB_ITEM.findall(text(get(app, "/jobs")))
    line = re.search(r'<p class="line">(.*?)</p>', item, re.S).group(1)
    assert "Removed" in line and "Added" not in line  # not a request that added a song
    [view] = answer(get_json(app, f"/jobs.json?jobs={job_id}"))["jobs"]
    assert view["line"]["text"] == "Removed" and view["display"] == "Radiohead - Creep"
    # Its song is gone, and the view still names it: the page knows which card says Removed.
    assert view["songId"] == creep.id and view["kind"] == "remove" and "card" not in view


@pytest.mark.parametrize("back,address", [
    ("", "/#song={id}"),
    ("view=rows&q=creep+radio&show=found", "/#view=rows&q=creep+radio&show=found&song={id}"),
    ("q=m%C3%BAsica&artist=soda+stereo&sort=recent&key=A+minor", "/#q=m%C3%BAsica&artist=soda+stereo&sort=recent"
                                                                  "&key=A+minor&song={id}"),
    ("#view=rows", "/#view=rows&song={id}"),  # location.hash, as it is
    ("view=rows\r\nSet-Cookie: x=1", "/#song={id}"),  # anything else is no address of the library's
    ('view="><script>', "/#song={id}"),
    ("q=" + "a" * 600, "/#song={id}"),
])
def test_removing_goes_back_to_the_library_as_you_left_it(app, conn, cfg, queue, back, address):
    # The card's Remove… sends the library's address (its search, filters and view: the part after #) along;
    # the question's Keep it, and Remove it, go back there, to the song's card.
    creep = a_kept_song(conn, cfg)
    want = address.format(id=creep.id)
    asked = text(post(app, "/remove", {"song": str(creep.id), "back": back}))
    form = re.search(r'<form[^>]*action="/remove"[^>]*>(.*?)</form>', asked, re.S).group(1)
    keep = re.search(r'<a class="btn" href="([^"]*)">Keep it</a>', form).group(1)
    assert keep.replace("&amp;", "&") == want
    kept = re.search(r'name="back" value="([^"]*)"', form)
    assert (kept.group(1).replace("&amp;", "&") if kept else "") == want.removeprefix("/#").removesuffix(
        f"song={creep.id}").removesuffix("&")
    response = post(app, "/remove", {"song": str(creep.id), "key": creep.key, "confirm": "1", "back": back})
    assert response.status == 303 and header(response, "location") == want


@pytest.mark.parametrize("csrf,headers", [(None, {}), ("tok", {"sec-fetch-site": "cross-site"})])
def test_a_removal_from_anywhere_but_the_page_is_refused(app, conn, cfg, queue, csrf, headers):
    creep = a_kept_song(conn, cfg)
    fields = {"song": str(creep.id), "key": creep.key, "confirm": "1"}
    assert post(app, "/remove", fields, csrf=csrf, **headers).status == 403
    assert queue.snapshot() == []


# --- from the page's script, without leaving the page ----------------------------------------------


def test_a_request_from_the_pages_script_is_answered_with_its_job_not_a_redirect(app, queue):
    response = post(app, "/request", {"artist": " Radiohead ", "title": "Creep", "fetch": "1"}, accept=JSON)
    assert response.status == 200 and header(response, "location") is None
    assert answer(response) == {"job": {
        "id": 1, "display": "Radiohead - Creep", "songId": None, "kind": "song", "state": "queued", "fetching": True,
        "line": {"tone": "queued", "text": "Queued…", "link": None, "details": None}, "details": "jobs?job=1#job-1"}}
    assert queue.snapshot()[0].display == "Radiohead - Creep"


def test_a_fetch_from_the_pages_script_names_its_song_and_its_place_in_the_queue(app, conn, queue):
    creep = add_song(conn, "Radiohead", "Creep")
    oasis = add_song(conn, "Oasis", "Wonderwall")
    post(app, "/fetch", {"song": str(oasis.id)})
    job = answer(post(app, "/fetch", {"song": str(creep.id)}, accept=JSON))["job"]
    assert (job["id"], job["songId"], job["display"]) == (2, creep.id, "Radiohead - Creep")
    assert job["line"]["text"] == "Queued behind 1 request…"


def test_a_refusal_to_the_pages_script_is_one_sentence_of_json(app, conn, queue):
    response = post(app, "/request", {"artist": "", "title": "Creep"}, accept=JSON)
    assert response.status == 400 and answer(response) == {"error": "A song needs an artist and a title."}
    response = post(app, "/request", {"artist": "Radiohead", "title": "Creep"}, csrf="old", accept=JSON)
    assert response.status == 403 and "reload the library" in answer(response)["error"]
    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="review", match_candidates=REVIEW, review=True)
    response = post(app, "/fetch", {"song": str(creep.id)}, accept=JSON)
    assert response.status == 409 and "caracole review" in answer(response)["error"]
    assert queue.snapshot() == []


def test_the_status_endpoint_gives_each_requests_line_newest_first(app, conn, queue):
    creep = add_song(conn, "Radiohead", "Creep")
    post(app, "/fetch", {"song": str(creep.id)})
    post(app, "/request", {"artist": "Oasis", "title": "Wonderwall", "fetch": "1"})
    response = get_json(app, "/jobs.json")
    assert response.status == 200
    data = answer(response)
    assert data["active"] == 2
    assert [(j["id"], j["display"], j["songId"], j["line"]["text"]) for j in data["jobs"]] == [
        (2, "Oasis - Wonderwall", None, "Queued behind 1 request…"), (1, "Radiohead - Creep", creep.id, "Queued…")]
    assert all("card" not in j for j in data["jobs"])


def test_a_done_requests_line_and_card_say_what_the_library_has_now(app, conn, cfg, queue):
    creep = add_song(conn, "Radiohead", "Creep")
    post(app, "/fetch", {"song": str(creep.id)})
    queue.run_pending()
    # What the fetch did: a sheet in the song's folder.
    folder = song_dir(cfg.library_dir, creep)
    folder.mkdir(parents=True)
    (folder / "sheet.pdf").write_bytes(b"%PDF")
    update_song(conn, creep.id, status="found", ug_dirty=False)
    job = answer(get_json(app, "/jobs.json?jobs=1,x,99"))["jobs"][0]
    assert job["state"] == "done"
    assert job["line"] == {"tone": "ready", "text": "Ready",
                           "link": {"label": "Open sheet", "href": "Radiohead/Creep/sheet.pdf"}, "details": None}
    # Asked for, the card its song has now, as the page would draw it.
    card = job["card"]
    assert (card["id"], card["status"], card["fetchable"]) == (creep.id, "found", True)
    assert [f["href"] for f in card["files"]] == ["Radiohead/Creep/sheet.pdf"]
    assert "card" not in answer(get_json(app, "/jobs.json"))["jobs"][0]


class LooksUp:
    """The job's commands, faked: ``fetch``, or a lookup's ``get``, looks the song up as ``how`` says, and
    keeps nothing."""

    def __init__(self, cfg, how):
        self.cfg = cfg
        self.how = how

    def __call__(self, args, emit):
        from caracole import db
        from caracole.overrides import override_key
        from caracole.songs import find_song

        if args[0] in ("fetch", "get"):
            display = args[-1].removeprefix("--song=") if args[0] == "fetch" else f"{args[-2]} - {args[-1]}"
            conn = db.connect(self.cfg.db_path)
            try:
                song = find_song(conn, override_key(display))
                if self.how == "finished":  # every slot done, nothing kept (ug.fetch._finish)
                    update_song(conn, song.id, ug_dirty=False, ug_checked_at=_iso_now())
                elif self.how == "artist page":  # read for the song, which isn't there (_not_on_artist_page)
                    db.kv_set(conn, f"ug:artist_page_checked:{song.id}", _iso_now())
            finally:
                conn.close()
        emit("ok")
        return 0


def _iso_now():
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_a_done_fetch_without_a_sheet_is_not_found_only_when_it_looked_the_song_up(cfg, conn):
    creep = add_song(conn, "Radiohead", "Creep")
    update_song(conn, creep.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep",
                ug_dirty=False, ug_checked_at="2026-10-01T00:00:00Z")  # fetched before, and clean
    for how, line in [
        ("nothing", {"tone": "waiting", "text": "Not fetched yet", "link": None, "details": "jobs?job=1#job-1"}),
        ("finished", {"tone": "missing", "text": "Not found",
                      "link": {"label": "see the to-do page", "href": "_todo.md"}, "details": None}),
    ]:
        queue = JobQueue(LooksUp(cfg, how))
        app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
        post(app, "/fetch", {"song": str(creep.id)})
        queue.run_pending()
        assert answer(get_json(app, "/jobs.json"))["jobs"][0]["line"] == line, how
    # A song not found in the index, looked up on its artist's page during the request, is not found. (Its
    # artist's page is known: one that isn't can't be looked up at all, and that alone is Not found.)
    from caracole.ug.lookup import remember_artist_url

    remember_artist_url(conn, "radiohead", "https://www.ultimate-guitar.com/artist/radiohead_1")
    update_song(conn, creep.id, match_decision="not_found", match_artist_key=None, match_song_key=None,
                ug_checked_at="2026-10-01T00:00:00Z")
    for how, tone in (("nothing", "waiting"), ("artist page", "missing")):
        queue = JobQueue(LooksUp(cfg, how))
        app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
        post(app, "/fetch", {"song": str(creep.id)})
        queue.run_pending()
        assert answer(get_json(app, "/jobs.json"))["jobs"][0]["line"]["tone"] == tone, how


# --- with the real `caracole fetch`, against a fake Ultimate Guitar ---------------------------

SIGNOS = "https://tabs.ultimate-guitar.com/tab/soda-stereo/signos-chords-201"


class RealFetch:
    """The job's commands: ``caracole fetch`` and a lookup's ``caracole get`` themselves, through the CLI at -v;
    the others do nothing."""

    def __init__(self, config):
        self.config = config

    def __call__(self, args, emit):
        if args[0] not in ("fetch", "get"):
            emit("ok")
            return 0
        result = CliRunner().invoke(build_app(), ["--config", str(self.config), "-v", *args])
        for line in result.output.splitlines():
            emit(line)
        return result.exit_code


@pytest.fixture
def fake_ug(monkeypatch):
    """UG's pages by URL, anything else its 404 page, through the CLI's transport: no request leaves."""
    import httpx

    pages = {}

    def handler(request):
        status, body = pages.get(str(request.url), (404, "<html><title>Oops!</title></html>"))
        return httpx.Response(status, text=body)

    monkeypatch.setattr("caracole.commands._common.transport_for", lambda provider: httpx.MockTransport(handler))
    return pages


def signos_page(tab_id=201, url=SIGNOS):
    from helpers.ug_pages import make_tab_page_html, version_dict

    tab = version_dict(tab_id, song="Signos", artist="Soda Stereo", tab_url=url)
    return 200, make_tab_page_html(tab, [], content="[tab][ch]Am[/ch]\r\nla la la[/tab]",
                                   artist_url="https://www.ultimate-guitar.com/artist/soda_stereo_2946")


def real_fetch_app(cfg, tmp_path, *, budget=60, lookup_requests=6):
    config = tmp_path / "caracole-cli.toml"
    quick = "".join(f"[providers.{p}]\nlookup_delay = [0, 0]\n" for p in ("lrclib", "lacuerda", "gtptabs"))
    config.write_text(f'library_dir = "{cfg.library_dir}"\nmusic_dir = "{cfg.music_dir}"\n'
                      f'state_dir = "{cfg.state_dir}"\ncache_dir = "{cfg.cache_dir}"\n'
                      f"[providers.ug]\nbudget = {budget}\ndelay = [0, 0]\nlookup_delay = [0, 0]\n"
                      f"lookup_requests = {lookup_requests}\n{quick}", encoding="utf-8")
    queue = JobQueue(RealFetch(config))
    return WebApp(cfg, queue, allowed=ALLOWED, csrf="tok"), queue


@pytest.mark.parametrize("how", ["cooldown", "budget", "error", "nothing kept"])
def test_a_clean_song_fetched_now_is_missing_only_when_ug_answered(cfg, conn, tmp_path, fake_ug, how):
    # Fetched before and clean (ug_dirty off), so the nightly run wouldn't fetch it on its own.
    from caracole.commands._common import utcnow
    from caracole.health import record_block

    signos = add_song(conn, "Soda Stereo", "Signos")
    update_song(conn, signos.id, match_decision="accept", match_step="exact", match_artist_key="soda-stereo",
                match_song_key="signos", ug_dirty=False, ug_checked_at="2026-10-01T00:00:00Z")
    conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
                 "VALUES (201, 'soda-stereo', 'signos', 'chords', 'last', '2026-10-01T00:00:00Z', ?)",
                 ("soda-stereo/signos-chords-201",))
    budget, lookup_requests = 60, 6
    fake_ug[SIGNOS] = signos_page()
    if how == "cooldown":
        record_block(conn, "ug", utcnow(), "HTTP 403")
    elif how == "budget":  # two pages to read, one request to spend at night, and none for a lookup
        lookup_requests = 0
        conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
                     "VALUES (202, 'soda-stereo', 'signos', 'chords', 'last', '2026-10-01T00:00:00Z', ?)",
                     ("soda-stereo/signos-chords-202",))
        other = "https://tabs.ultimate-guitar.com/tab/soda-stereo/signos-chords-202"
        fake_ug[other] = signos_page(202, other)
        budget = 1
    elif how == "error":
        fake_ug[SIGNOS] = (200, "<html><body>maintenance</body></html>")  # no js-store: it won't parse
    else:
        del fake_ug[SIGNOS]  # gone: UG answers 404, and the fetch keeps nothing
    app, queue = real_fetch_app(cfg, tmp_path, budget=budget, lookup_requests=lookup_requests)

    post(app, "/fetch", {"song": str(signos.id)})
    queue.run_pending()

    job = answer(get_json(app, "/jobs.json"))["jobs"][0]
    assert job["state"] == "done", queue.snapshot()[0].steps[-1].output
    if how == "nothing kept":
        assert job["line"]["tone"] == "missing"
    else:
        assert job["line"] == {"tone": "waiting", "text": "Not fetched yet", "link": None,
                               "details": "jobs?job=1#job-1"}, queue.snapshot()[0].steps[-1].output
        from caracole.songs import get_song

        assert get_song(conn, signos.id).ug_dirty is True  # so the next run fetches it: it does wait


@pytest.mark.parametrize("decision,review,error,line", [
    ("not_found", False, "Ultimate Guitar lists Obscure Band only by bare tab ids, which caracole can't see. "
                         "Find the artist's page on UG.",
     {"tone": "missing", "text": "Not found", "link": {"label": "see the to-do page", "href": "_todo.md"},
      "details": None}),
    ("review", True, '"Obscure Band - Song" needs review first: run `caracole review`.',
     {"tone": "review", "text": "Needs review", "link": {"label": "see the to-do page", "href": "_todo.md"},
      "details": None}),
])
def test_a_requested_fetch_that_fetch_refuses_says_why_as_the_card_would(cfg, conn, decision, review, error,
                                                                           line):
    # A song the match leaves not found (its artist unknown) or in review has no Ultimate Guitar sheet to
    # fetch: Fetch it now's `caracole get` skips its sheet stage, saying why, and goes on (exit 0), where
    # `caracole fetch --song` refused it (exit 1). The card says why, the same either way.
    from caracole.get import PROGRESS_PREFIX

    def runner(args, emit):
        from caracole import db
        from caracole.songs import find_song
        from caracole.wanted import sync_wanted

        c = db.connect(cfg.db_path)
        try:
            if args[0] == "get":
                sync_wanted(c, cfg.wanted_file, datetime_now())
                update_song(c, find_song(c, "obscure-band/song").id, match_decision=decision, review=review)
                emit(PROGRESS_PREFIX + json.dumps({"stage": "sheet", "state": "skipped", "detail": error}))
        finally:
            c.close()
        return 0

    queue = JobQueue(runner)
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
    post(app, "/request", {"artist": "Obscure Band", "title": "Song", "fetch": "1"})
    queue.run_pending()
    job = answer(get_json(app, "/jobs.json"))["jobs"][0]
    assert job["state"] == "done" and job["line"] == line
    assert "caracole review" not in json.dumps(job["line"])  # nothing to type on a phone


def datetime_now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


def test_the_status_endpoint_gives_only_the_jobs_the_page_asks_about(app, conn, queue, monkeypatch):
    import caracole.songs

    creep = add_song(conn, "Radiohead", "Creep")
    oasis = add_song(conn, "Oasis", "Wonderwall")
    post(app, "/fetch", {"song": str(creep.id)})
    queue.run_pending()
    post(app, "/fetch", {"song": str(oasis.id)})
    looked_up = []
    real = caracole.songs.find_song
    monkeypatch.setattr(caracole.songs, "find_song", lambda c, key: looked_up.append(key) or real(c, key))

    data = answer(get_json(app, "/jobs.json?jobs=2"))
    assert [j["id"] for j in data["jobs"]] == [2] and data["active"] == 1
    assert looked_up == [oasis.key]  # the other job's song isn't looked up
    # A finished job's song is looked up once: its line can't change any more.
    looked_up.clear()
    for _ in range(3):
        assert answer(get_json(app, "/jobs.json?jobs=1"))["jobs"][0]["line"]["tone"] == "waiting"
    assert looked_up.count(creep.key) == 1


def test_the_status_endpoint_reads_only_plain_digits(app, conn, queue):
    creep = add_song(conn, "Radiohead", "Creep")
    post(app, "/fetch", {"song": str(creep.id)})
    response = get_json(app, "/jobs.json?jobs=%C2%B2,1,%EF%BC%91,-1, 1 ")  # "²", a full-width "1"
    assert response.status == 200
    assert [j["id"] for j in answer(response)["jobs"]] == [1]


def test_a_failed_requests_line_is_its_error_with_a_link_to_its_output(cfg, conn):
    def runner(args, emit):
        if args[0] in ("fetch", "get"):  # Fetch now is a lookup
            emit("Ultimate Guitar GET https://tabs.ultimate-guitar.com/tab/1 → 200 OK in 0.40 s (1 of 60 requests)")
            emit("error: The page under [artist_url] for Radiohead, UG answers 404 for it. Put another there.")
            return 1
        return 0

    queue = JobQueue(runner)
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
    creep = add_song(conn, "Radiohead", "Creep")
    post(app, "/fetch", {"song": str(creep.id)})
    queue.run_pending()
    job = answer(get_json(app, "/jobs.json"))["jobs"][0]
    assert job["state"] == "failed" and job["line"] == {
        "tone": "failed", "text": "The page under [artist_url] for Radiohead, UG answers 404 for it.",
        "link": None, "details": "jobs?job=1#job-1"}
    # On /jobs the output is right under the line, behind its Output toggle: no link to the same page.
    item = dict(JOB_ITEM.findall(text(get(app, "/jobs"))))["1"]
    line = re.search(r'<p class="line">(.*?)</p>', item, re.S).group(1)
    assert "UG answers 404 for it." in line and "<a " not in line and "Details" not in line


@pytest.mark.parametrize("token,headers", [
    (None, {"sec-fetch-site": "same-origin"}),  # no form token
    ("wrong", {"sec-fetch-site": "same-origin"}),
    ("tok", {"sec-fetch-site": "cross-site"}),
    ("tok", {"origin": "http://evil.example"}),
])
def test_the_status_endpoint_answers_only_the_pages_own_script(app, token, headers):
    sent = {"host": HOST, "accept": JSON} | ({"x-caracole-form-token": token} if token else {}) | headers
    response = app.handle(Request("GET", "/jobs.json", sent))
    assert response.status == 403 and "error" in answer(response)


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
        ("render", "--song=Radiohead - Creep"),
    ]
    assert job.fetching and job.song_key == creep.key
    assert job.title == "Pick radiohead/creep for Radiohead - Creep, and fetch it"


def test_a_pick_from_the_pages_script_is_answered_with_its_job_and_names_its_song(app, conn, queue):
    # The card's picker posts as the page's script, which stays on the page and shows the pick on the card's
    # line, as Fetch now does; a form without the script still goes to the request on /jobs.
    creep = in_review(conn)
    fields = {"song": str(creep.id), "pick": "radiohead/creep", "shown": SHOWN, "fetch": "1"}
    response = post(app, "/review", fields, accept=JSON)
    assert response.status == 200 and header(response, "location") is None
    job = answer(response)["job"]
    assert (job["id"], job["songId"], job["display"], job["fetching"]) == (1, creep.id, "Radiohead - Creep", True)
    assert job["line"] == {"tone": "queued", "text": "Queued…", "link": None, "details": None}
    # Like every request, it is the song's on /jobs and in the page's list of requests; its title says the pick.
    [queued] = queue.snapshot()
    assert queued.display == "Radiohead - Creep"
    assert queued.title == "Pick radiohead/creep for Radiohead - Creep, and fetch it"
    item = job_item(text(get(app, "/jobs")), 1)
    assert '<span class="song">Radiohead - Creep</span>' in item and "Pick radiohead/creep for" in item
    # A refusal is one sentence, as the card's line says it.
    again = post(app, "/review", fields, accept=JSON)
    assert again.status == 409 and answer(again) == {
        "error": "A request for Radiohead - Creep is waiting or running: pick once it ends."}


def test_a_pick_says_on_the_cards_line_that_it_writes_the_answer(app, conn, queue):
    # A step's label is what the card says while it runs (status.py): "Writing the answer to overrides.toml…".
    from caracole.web.jobs import review_steps

    assert review_steps("Radiohead - Creep", pick="radiohead/creep") == [
        ("Writing the answer to overrides.toml", ("review", "--song=Radiohead - Creep", "--pick=radiohead/creep"))]
    assert review_steps("Radiohead - Creep", seen=["a/b"])[0][0] == "Writing the answer to overrides.toml"


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
    ({"song": BEYOND_SQLITE, "pick": "radiohead/creep", "shown": SHOWN}, 404, "isn't in the library"),
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


def test_a_request_that_comes_in_while_a_pick_is_checked_is_never_joined_by_it(app, conn, queue, monkeypatch):
    # The server answers each request in a thread of its own: the song's request may be queued
    # between the pick's checks and its submit. The pick is refused, and the request is left as it is.
    creep = in_review(conn)
    submit = queue.submit

    def request_first(*args, **kwargs):
        if not queue.snapshot():
            submit("Add Radiohead - Creep", creep.key, [("Add to the library", ("add", "--", "Radiohead", "Creep"))])
        return submit(*args, **kwargs)

    monkeypatch.setattr(queue, "submit", request_first)
    response = post(app, "/review", {"song": str(creep.id), "pick": "radiohead/creep", "shown": SHOWN, "fetch": "1"})
    assert response.status == 409 and "waiting or running" in shown(response)
    [job] = queue.snapshot()
    assert [s.args[0] for s in job.steps] == ["add"] and not job.fetching


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


def job_item(body: str, job_id: int) -> str:
    """A request on /jobs: its line, its folded output and what waits under it (JOB_ITEM)."""
    items = dict(JOB_ITEM.findall(body))
    assert str(job_id) in items, body[-2000:]
    return items[str(job_id)]


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


@pytest.mark.parametrize("path,status", [("/review", 400), ("/review?song=x", 400), ("/review?song=999", 404),
                                         (f"/review?song={BEYOND_SQLITE}", 404)])
def test_the_pickers_page_needs_a_song_of_the_library(app, conn, path, status):
    assert get(app, path).status == status


def test_the_pickers_page_of_a_song_that_needs_no_review_says_so(app, conn):
    settled = add_song(conn, "Oasis", "Wonderwall")
    update_song(conn, settled.id, match_decision="accept")
    response = get(app, f"/review?song={settled.id}")
    assert response.status == 409 and "doesn't need review" in shown(response)
    assert 'action="/review"' not in text(response)


def test_the_pickers_page_says_why_a_song_in_review_has_nothing_to_pick(app, conn, cfg):
    from caracole.overrides import add_ignore

    bare = add_song(conn, "Queen", "Bohemian Rhapsody")  # in review with no candidate
    update_song(conn, bare.id, match_decision="review", review=True)
    response = get(app, f"/review?song={bare.id}")
    assert response.status == 409 and 'action="/review"' not in text(response)
    assert "has no candidates to pick: caracole review offers a pin or an ignore" in shown(response)
    assert "doesn't need review" not in shown(response)
    creep = in_review(conn)
    add_ignore(cfg.overrides_file, creep.display)
    response = get(app, f"/review?song={creep.id}")
    assert response.status == 409 and "Radiohead - Creep is ignored in overrides.toml" in shown(response)


def test_a_request_that_ends_in_a_review_shows_its_picker_on_the_requests_page(app, conn, queue):
    post(app, "/request", {"artist": "Radiohead", "title": "Creep", "fetch": "1"})
    creep = in_review(conn)  # what its `caracole add` found
    assert 'action="/review"' not in text(get(app, "/jobs"))  # not while it runs
    queue.run_pending()
    body = text(get(app, "/jobs"))
    job = job_item(body, 1)
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
    job = job_item(body, 1)
    assert 'action="/review"' not in job and f'href="/review?song={creep.id}"' in job
    still = text(get(app, "/jobs?refresh=0"))
    assert 'action="/review"' in job_item(still, 1)


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
        ("render", "--song=Radio Head - Crep"),
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
    job = job_item(text(get(app, "/jobs")), 1)
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


def cli_config(cfg, tmp_path: Path) -> Path:
    """A caracole.toml for the command line, with ``cfg``'s folders."""
    config = tmp_path / "caracole.toml"
    config.write_text(f'library_dir = "{cfg.library_dir}"\nstate_dir = "{cfg.state_dir}"\n'
                      f'cache_dir = "{cfg.cache_dir}"\nmusic_dir = "{cfg.music_dir}"\n', encoding="utf-8")
    return config


def test_a_request_that_ends_in_a_review_waits_for_a_pick_rather_than_failing(cfg, conn, tmp_path, monkeypatch):
    # Fetch it now is ticked by default; its `caracole get` matches the song to candidates only, so it has
    # no Ultimate Guitar sheet to fetch. The request waits for the pick its picker, right under it, gives.
    from datetime import UTC, datetime

    import httpx

    from caracole.ug.index import mark_built

    def refuse(request):
        if request.url.host == "lrclib.net":  # the lyrics come all the same
            return httpx.Response(404, json={"name": "TrackNotFound"})
        raise AssertionError(f"a request to {request.url}")

    monkeypatch.setattr("caracole.commands._common.transport_for", lambda provider: httpx.MockTransport(refuse))
    conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) VALUES "
                 "(1, 'oasis', 'champagne-supernova', 'chords', '1', 'x', 'oasis/champagne-supernova-chords-1')")
    mark_built(conn, datetime(2026, 10, 18, 3, 30, tzinfo=UTC))
    runner = CliRunnerJobs(cli_config(cfg, tmp_path))
    queue = JobQueue(runner)
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
    fields = {"artist": "Oasis", "title": "Champagne Super", "fetch": "1"}  # a title spelled differently
    assert post(app, "/request", fields).status == 303
    queue.run_pending()
    [job] = queue.snapshot()
    assert [s.state for s in job.steps] == ["done"], runner.outputs
    assert "isn't sure which Ultimate Guitar song" in runner.outputs[0]
    article = job_item(text(get(app, "/jobs")), 1)
    # Its line, the one its card shows (status.py), says the song needs review and sends you to its picker,
    # not to the to-do page: no failure.
    from caracole.songs import list_songs

    [song] = list_songs(conn)
    line = re.search(r'<p class="line">(.*?)</p>', article, re.S).group(0)
    assert '<span class="says review">Needs review' in line and "Failed" not in line and "error" not in line
    assert f'<a href="review?song={song.id}">Pick the match</a>' in line and "to-do" not in line
    view = answer(get_json(app, "/jobs.json?jobs=1"))["jobs"][0]
    assert view["line"]["link"] == {"label": "Pick the match", "href": f"review?song={song.id}"}
    assert view["card"]["candidates"]  # the card it is drawn again as has the picker the line names
    fetch = re.search(r'<li class="step [^"]*"><div class="step-head"><span>The sheet</span>.*?</li>',
                      article, re.S).group(0)
    assert '<span class="badge review">Waits for a pick</span>' in fetch and "Failed" not in fetch
    assert "Pick it below" in shown_text(fetch)
    # The lookup's own words are there, folded away with the request's output; the picker is below it.
    assert "isn&#x27;t sure which Ultimate Guitar song" in fetch and '<details class="output">' in article
    assert article.index('<form class="pick-form"') > article.index("</details>")
    assert picker_of(article)


def test_a_request_whose_fetch_failed_otherwise_still_shows_failed(cfg, conn):
    def down(args, emit):
        if args[0] not in ("fetch", "get"):  # Fetch it now is a lookup
            return 0
        emit("error: the network is down")
        return 1

    queue = JobQueue(down)
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
    post(app, "/request", {"artist": "Radiohead", "title": "Creep", "fetch": "1"})
    creep = in_review(conn)
    queue.run_pending()
    article = job_item(text(get(app, "/jobs")), 1)
    assert '<span class="badge failed">Failed</span>' in article and "Waits for a pick" not in article
    assert f'name="song" value="{creep.id}"' in picker_of(article)


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


JOB_ITEM = re.compile(r'<li class="job[^"]*" id="job-(\d+)">(.*?)</li>\n', re.S)


def test_the_requests_page_has_one_line_per_request_its_output_collapsed(app, conn, cfg, queue):
    post(app, "/request", {"artist": "Evil", "title": "<script>alert(1)</script>", "fetch": "1"})
    body = text(get(app, "/jobs"))
    assert '<meta http-equiv="refresh" content="10">' in body  # while one waits or runs
    assert "<script>alert" not in body and "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    (job_id, item), = JOB_ITEM.findall(body)
    assert job_id == "1" and "Queued…" in item
    queue.run_pending()
    creep = add_song(conn, "Radiohead", "Creep")
    post(app, "/fetch", {"song": str(creep.id)})
    queue.run_pending()
    folder = song_dir(cfg.library_dir, creep)
    folder.mkdir(parents=True)
    (folder / "sheet.pdf").write_bytes(b"%PDF")
    body = text(get(app, "/jobs"))
    assert 'http-equiv="refresh"' not in body
    items = dict(JOB_ITEM.findall(body))
    assert list(items) == ["2", "1"]  # newest first
    newest = items["2"]
    line = re.search(r'<p class="line">(.*?)</p>', newest, re.S).group(1)
    assert "Radiohead - Creep" in line and "Ready" in line and 'href="Radiohead/Creep/sheet.pdf"' in line
    # The commands and what each printed are there, folded away.
    assert '<details class="output">' in newest and "<details open" not in body
    # A fetch now is one `caracole get`, its stages listed each with its state.
    assert "Look it up now" in newest and "The sheet" in newest and "<pre>ok" in newest and "Done" in newest


def test_a_requests_output_opens_when_its_details_link_asks_for_it(app, queue):
    post(app, "/request", {"artist": "Radiohead", "title": "Creep"})
    post(app, "/request", {"artist": "Oasis", "title": "Wonderwall"})
    queue.run_pending()
    items = dict(JOB_ITEM.findall(text(get(app, "/jobs?job=1"))))
    assert '<details class="output" open>' in items["1"] and "<details class=\"output\" open>" not in items["2"]
    assert '<details class="output" open>' not in text(get(app, "/jobs?job=x"))


def test_the_requests_page_can_stop_refreshing_so_an_output_can_be_read(app, queue):
    post(app, "/request", {"artist": "Radiohead", "title": "Creep"})
    body = text(get(app, "/jobs"))
    assert 'href="/jobs?refresh=0"' in body and "Stop refreshing" in body
    still = text(get(app, "/jobs?refresh=0"))
    assert 'http-equiv="refresh"' not in still and 'href="/jobs"' in still
    assert 'href="/jobs?refresh=0"' not in still
    # A request's output stays open either way.
    assert 'href="/jobs?job=1&amp;refresh=0"' in text(get(app, "/jobs?job=1"))
    assert 'href="/jobs?job=1"' in text(get(app, "/jobs?job=1&refresh=0"))


def test_the_requests_page_with_nothing_queued(app):
    body = text(get(app, "/jobs"))
    assert "No requests yet" in body


# --- looking a song up as you type ---------------------------------------------------------------


def as_json(response):
    import json

    assert header(response, "content-type") == "application/json; charset=utf-8"
    return json.loads(response.body)


def creep_index(conn):
    from caracole.ug.index import mark_built, upsert_rows

    rows = [(4169, "radiohead", "creep", "chords"), (4170, "radiohead", "creep", "chords"),
            (4172, "radiohead", "creep", "tabs"), (4174, "radiohead", "creep-acoustic", "guitar-pro"),
            (5001, "stone-temple-pilots", "creep", "chords"), (9, "oasis", "wonderwall", "chords")]
    upsert_rows(conn, [(t, a, s, k, f"{a}/{s}-{k}-{t}") for t, a, s, k in rows], "1",
                datetime(2026, 10, 19, tzinfo=UTC))
    mark_built(conn, datetime(2026, 10, 19, tzinfo=UTC))


def test_the_lookup_page_is_served_with_its_script(app):
    response = get(app, "/lookup")
    assert response.status == 200 and header(response, "content-type") == "text/html; charset=utf-8"
    body = text(response)
    assert 'id="q"' in body and 'data-csrf="tok"' in body
    csp = header(response, "content-security-policy")
    assert "connect-src 'self'" in csp and "script-src 'sha256-" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp and "innerHTML" not in body
    # The library page's own bar searches the sites now: it links no other page for it.
    library = text(get(app, "/"))
    assert 'href="/lookup"' not in library and 'id="all"' in library


def test_the_search_answers_json_from_your_library_and_the_offline_index(app, conn):
    creep_index(conn)
    mine = add_song(conn, "Radiohead", "Creep")
    update_song(conn, mine.id, match_decision="accept", match_artist_key="radiohead", match_song_key="creep")
    data = as_json(get(app, "/api/search?q=creep"))
    assert data["query"] == "creep"
    assert [h["display"] for h in data["library"]] == ["Radiohead - Creep"]
    assert data["library"][0]["id"] == mine.id and data["library"][0]["status"] == "wanted"
    first, second = data["index"][:2]
    assert (first["artist"], first["title"], first["ug"]) == ("Radiohead", "Creep", "radiohead/creep")
    assert first["counts"] == {"chords": 2, "tabs": 1, "guitar-pro": 1} and first["song"] == mine.id
    assert [t["id"] for t in first["tabs"]][:2] == [4169, 4170]  # chords first
    assert first["tabs"][0] == {"id": 4169, "type": "chords", "label": None,
                                "url": "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"}
    assert (second["ug"], second["song"]) == ("stone-temple-pilots/creep", None)


def test_a_library_song_found_comes_as_its_card_has_it_its_viewer_first(app, cfg, conn):
    # The lookup page draws it as index.html's row does: its viewer opens it, and every file says where it
    # came from. Its links are the card's, relative to the library, as the server serves them.
    from helpers.rendered import rendered_song

    from caracole.ug.index import mark_built, upsert_rows

    song = rendered_song(conn, cfg)  # Soda Stereo - De Música Ligera, a UG sheet in G, rendered
    upsert_rows(conn, [(85053, "soda-stereo", "de-musica-ligera", "chords", "soda-stereo/de-musica-ligera-chords-1")],
                "1", datetime(2026, 10, 19, tzinfo=UTC))
    mark_built(conn, datetime(2026, 10, 19, tzinfo=UTC))
    data = as_json(get(app, "/api/search?q=musica%20ligera"))
    [mine] = data["library"]
    assert (mine["id"], mine["source"], mine["key"]) == (song.id, "ug", "G")
    [primary] = [f for f in mine["links"] if f["primary"]]
    assert (primary["name"], primary["href"]) == ("sheet.html", "Soda%20Stereo/De%20M%C3%BAsica%20Ligera/sheet.html")
    assert {"sheet.pdf", "sheet.txt"} <= {f["name"] for f in mine["links"]}
    assert mine["files"]["viewer"] == "Soda Stereo/De Música Ligera/sheet.html"  # the page's reader, as before
    # Its Ultimate Guitar song names it, with its links too.
    [hit] = [h for h in data["index"] if h["song"] == song.id]
    assert [f["href"] for f in hit["library"]["links"] if f["primary"]] == [primary["href"]]
    assert get(app, "/" + primary["href"]).status == 200  # the viewer caracole wrote, served


def either_index(conn):
    """Oasis, a band called Wonderwall, and songs titled Wonderwall and Oasis by others."""
    from caracole.ug.index import mark_built, upsert_rows

    rows = [(11, "oasis", "wonderwall", "chords"), (12, "oasis", "wonderwall", "tabs"), (13, "oasis", "wonderwall", "tabs"),
            (14, "oasis", "live-forever", "chords"), (21, "ryan-adams", "wonderwall", "chords"),
            (31, "wonderwall", "in-april", "chords"), (41, "a-great-big-world", "oasis", "chords")]
    upsert_rows(conn, [(t, a, s, k, f"{a}/{s}-{k}-{t}") for t, a, s, k in rows], "1", datetime(2026, 10, 19, tzinfo=UTC))
    mark_built(conn, datetime(2026, 10, 19, tzinfo=UTC))


def test_api_search_gives_artists_readings_and_what_enter_takes(app, conn):
    either_index(conn)
    data = as_json(get(app, "/api/search?q=wonderwall"))
    assert [(h["ug"], h["via"]) for h in data["index"]] == [("oasis/wonderwall", "title"), ("ryan-adams/wonderwall", "title")]
    [band] = data["artists"]
    assert {k: band[k] for k in ("artist_key", "artist", "songs", "tabs")} == {
        "artist_key": "wonderwall", "artist": "Wonderwall", "songs": 1, "tabs": 1}
    assert [t["title"] for t in band["top"]] == ["In April"] and band["top"][0]["ug"] == "wonderwall/in-april"
    assert (data["lead"], data["best"]) == ("song", {"ug": "oasis/wonderwall"})
    # An artist alone: it leads, and Enter has no song to take.
    oasis = as_json(get(app, "/api/search?q=oasis"))
    assert (oasis["lead"], oasis["best"]) == ("artist", None)
    assert oasis["artists"][0]["artist_key"] == "oasis" and [h["ug"] for h in oasis["index"]] == ["a-great-big-world/oasis"]
    # A song of yours read by its title is what Enter takes: it costs no request.
    mine = add_song(conn, "Oasis", "Wonderwall")
    again = as_json(get(app, "/api/search?q=wonderwall"))
    assert [(h["id"], h["via"]) for h in again["library"]] == [(mine.id, "title")]
    assert again["best"] == {"library": mine.id}
    assert as_json(get(app, "/api/search?q=oasis"))["library"][0]["via"] == "artist"
    # Nothing strong: Enter takes nothing.
    weak = as_json(get(app, "/api/search?q=live%20foreve%20zzz"))
    assert weak["best"] is None



def test_api_search_says_a_hit_under_a_misc_artist_is_no_ones(app, conn):
    from caracole.ug.index import mark_built, upsert_rows

    rows = [(11, "oasis", "wonderwall", "chords"), (31, "misc-mashups", "oasis-wonderwall", "chords")]
    upsert_rows(conn, [(t, a, s, k, f"{a}/{s}-{k}-{t}") for t, a, s, k in rows], "1", datetime(2026, 10, 19, tzinfo=UTC))
    mark_built(conn, datetime(2026, 10, 19, tzinfo=UTC))
    data = as_json(get(app, "/api/search?q=oasis%20wonderwall"))
    assert {h["ug"]: h["no_ones"] for h in data["index"]} == {
        "oasis/wonderwall": False, "misc-mashups/oasis-wonderwall": True}  # added under UG's names, it'd be no one's


def test_api_artist_lists_an_artists_songs_and_yours(app, conn):
    either_index(conn)
    mine = add_song(conn, "Oasis", "Wonderwall")
    add_song(conn, "Radiohead", "Creep")
    data = as_json(get(app, "/api/artist?key=oasis"))
    assert (data["artist_key"], data["artist"], data["total"], data["offset"]) == ("oasis", "Oasis", 2, 0)
    assert [h["ug"] for h in data["songs"]] == ["oasis/wonderwall", "oasis/live-forever"]  # the most tabbed first
    first = data["songs"][0]
    assert first["counts"] == {"chords": 1, "tabs": 2} and first["song"] == mine.id and first["tabs"][0]["id"] == 11
    assert [s["id"] for s in data["library"]] == [mine.id]  # yours by them, as the search gives them
    assert "links" in data["library"][0] and data["library"][0]["via"] == "artist"
    paged = as_json(get(app, "/api/artist?key=oasis&offset=1"))
    assert [h["ug"] for h in paged["songs"]] == ["oasis/live-forever"] and paged["offset"] == 1
    assert get(app, "/api/artist?key=nobody-at-all").status == 404
    assert get(app, "/api/artist").status == 400 and get(app, "/api/artist?key=oasis&offset=x").status == 400


def site_pages(conn, gtptabs=(), musescore=()):
    """gtptabs.com's and MuseScore's song pages, as their sitemaps list them."""
    from caracole.gtptabs import parse_page_url
    from caracole.musescore import parse_song_url

    conn.executemany("INSERT INTO gtptabs_index (path, artist_path, artist_key, title_key, base_key, sitemap) "
                     "VALUES (?, ?, ?, ?, ?, '1')", [tuple(parse_page_url(u)) for u in gtptabs])
    conn.executemany("INSERT INTO musescore_index (page_id, path, title_key, sitemap) VALUES (?, ?, ?, '1')",
                     [tuple(parse_song_url(u)) for u in musescore])


def test_the_search_lists_gtptabs_and_musescore_pages_each_capped(app, conn):
    creep_index(conn)
    mine = add_song(conn, "Radiohead", "Creep")
    site_pages(conn, gtptabs=[f"https://gtptabs.com/tabs/{n}/band-{n}/creep.html" for n in range(1, 8)]
               + ["https://gtptabs.com/tabs/18/radiohead/creep.html"],
               musescore=[f"https://musescore.com/song/creep-{n}" for n in range(1, 8)])
    assert len(as_json(get(app, "/api/search?q=creep"))["gtptabs"]) == 5
    data = as_json(get(app, "/api/search?q=radiohead%20creep"))
    gtp = data["gtptabs"]
    assert gtp[0]["artist"] == "Radiohead" and gtp[0]["title"] == "Creep" and gtp[0]["source"] == "gtptabs"
    assert gtp[0]["url"] == "https://gtptabs.com/tabs/18/radiohead/creep.html" and gtp[0]["uploads"] == 1
    assert gtp[0]["song"] == mine.id and gtp[0]["library"]["id"] == mine.id  # yours: Get it looks it up as yours
    assert all(h["song"] is None and h["library"] is None for h in gtp[1:])
    ms = data["musescore"]
    assert len(ms) == 5 and {h["title"] for h in ms} == {"Creep"}
    assert ms[0]["url"] == "https://musescore.com/song/creep-1" and "artist" not in ms[0]  # a title alone
    assert data["skipped"] == [{"source": "lacuerda", "name": "LaCuerda",
                                "why": "its index is empty: the nightly run reads its listings of every artist"}]


def test_the_search_says_which_sites_it_left_out_and_why(app, cfg, conn):
    import dataclasses

    from caracole.config import ProviderPolicy
    from caracole.health import record_block

    creep_index(conn)
    skipped = {s["source"]: s["why"] for s in as_json(get(app, "/api/search?q=creep"))["skipped"]}
    assert "index is empty" in skipped["gtptabs"] and "index is empty" in skipped["musescore"]
    record_block(conn, "musescore", datetime(2026, 10, 19, tzinfo=UTC), "HTTP 403: a challenge")
    assert "blocking caracole" in {s["source"]: s["why"] for s in as_json(
        get(app, "/api/search?q=creeps"))["skipped"]}["musescore"]
    off = dataclasses.replace(cfg, providers={**cfg.providers,
                                              "gtptabs": ProviderPolicy(20, (10.0, 20.0), False),
                                              "musescore": ProviderPolicy(10, (10.0, 20.0), False)})
    site_pages(conn, gtptabs=["https://gtptabs.com/tabs/18/radiohead/creep.html"],
               musescore=["https://musescore.com/song/creep-1"])
    data = as_json(get(WebApp(off, JobQueue(Recorder()), allowed=ALLOWED, csrf="tok"), "/api/search?q=creep"))
    assert data["gtptabs"] == [] and data["musescore"] == []
    reasons = {s["source"]: s["why"] for s in data["skipped"]}
    assert reasons["gtptabs"] == reasons["musescore"] == "turned off in caracole.toml"


LC = "https://acordes.lacuerda.net/"


def lacuerda_index(conn, *, letters=("e", "j")):
    """LaCuerda's index: Estopa and Joaquín Sabina from E's and J's listings, which are all read, and Estopa's page."""
    from helpers.lacuerda_site import artist_page

    from caracole import lacuerda_index as li
    from caracole.db import kv_set_json
    from caracole.lacuerda import LCArtist

    li.store_artists(conn, "tabs/e/index0.html", [LCArtist("estopa", "Estopa", 159)])
    li.store_artists(conn, "tabs/j/index0.html", [LCArtist("joaquin_sabina", "Joaquín Sabina", 241)])
    li.store_artist_page(conn, "estopa", artist_page(
        "Estopa", "estopa", ("como_camaron", "Como Camarón", "RRT-213"), ("vino_tinto", "Vino Tinto", "T-1")))
    kv_set_json(conn, li.PAGES_KEY, {f"tabs/{x}/index0.html": {"pages": ["index0.html"]} for x in letters})
    conn.commit()


def test_the_search_lists_lacuerdas_artists_and_songs_from_its_index(app, conn):
    lacuerda_index(conn)
    mine = add_song(conn, "Estopa", "Como Camarón")
    data = as_json(get(app, "/api/search?q=estopa"))
    [estopa] = data["lacuerda_artists"]
    assert estopa == {"source": "lacuerda", "artist": "Estopa", "slug": "estopa", "url": LC + "estopa/",
                      "songs": 159, "known": 2, "score": 100.0, "via": "artist",
                      "top": [{"title": "Como Camarón", "url": LC + "estopa/como_camaron",
                               "sheet": LC + "estopa/como_camaron-2.shtml"}]}
    assert data["lacuerda"] == []  # its songs are in its row
    songs = as_json(get(app, "/api/search?q=como%20camaron"))["lacuerda"]
    assert [{k: h[k] for k in ("source", "artist", "title", "url", "sheet", "versions", "via", "song")}
            for h in songs] == [{"source": "lacuerda", "artist": "Estopa", "title": "Como Camarón",
                                 "url": LC + "estopa/como_camaron", "sheet": LC + "estopa/como_camaron-2.shtml",
                                 "versions": 3, "via": "title", "song": mine.id}]
    assert songs[0]["library"]["id"] == mine.id  # yours: Get it looks it up as yours
    [vino] = as_json(get(app, "/api/search?q=vino%20tinto"))["lacuerda"]
    assert vino["sheet"] is None and vino["song"] is None
    # E and J are read whole, the other letters not yet: LaCuerda is searched, and the answer says what it lacks.
    data = as_json(get(app, "/api/search?q=estopa"))
    assert "lacuerda" not in {s["source"] for s in data["skipped"]}
    assert data["partial"] == [{"source": "lacuerda", "name": "LaCuerda", "why": (
        "its index is still being read: 2 artists so far, with E, J read whole; the nightly run reads the rest")}]


def test_a_complete_lacuerda_index_is_searched_with_nothing_said(app, conn):
    from caracole import lacuerda_index as li
    from caracole.db import kv_set

    lacuerda_index(conn)
    kv_set(conn, li.COMPLETE_KEY, "2026-10-19T03:00:00Z")
    conn.commit()
    data = as_json(get(app, "/api/search?q=joaquin%20sabina"))
    assert data["partial"] == [] and data["lacuerda_artists"][0]["known"] == 0


def test_api_artist_lists_a_lacuerda_artists_songs_and_yours(app, conn):
    lacuerda_index(conn)
    mine = add_song(conn, "Estopa", "Como Camarón")
    data = as_json(get(app, "/api/artist?lacuerda=estopa"))
    assert {k: data[k] for k in ("source", "slug", "artist", "url", "listed", "total", "read")} == {
        "source": "lacuerda", "slug": "estopa", "artist": "Estopa", "url": LC + "estopa/", "listed": 159,
        "total": 2, "read": True}
    assert sorted(h["title"] for h in data["songs"]) == ["Como Camarón", "Vino Tinto"]
    assert [s["id"] for s in data["library"]] == [mine.id]
    unread = as_json(get(app, "/api/artist?lacuerda=joaquin_sabina"))
    assert (unread["read"], unread["songs"], unread["listed"]) == (False, [], 241)
    assert get(app, "/api/artist?lacuerda=nobody").status == 404


def test_reading_a_lacuerda_artists_page_is_one_command_in_the_queue(app, conn, queue):
    lacuerda_index(conn)
    response = post(app, "/lacuerda/artist", {"slug": "joaquin_sabina"}, accept="application/json")
    assert response.status == 202
    data = as_json(response)
    assert data["url"] == f"/api/jobs/{data['job']}"
    [job] = queue.snapshot()
    assert [s.args for s in job.steps] == [("lacuerda", "--artist=joaquin_sabina")]
    assert job.display == "Joaquín Sabina on LaCuerda" and job.song_key == "lacuerda-artist:joaquin_sabina"
    again = as_json(post(app, "/lacuerda/artist", {"slug": "joaquin_sabina"}, accept="application/json"))
    assert again["job"] == data["job"] and len(queue.snapshot()) == 1  # asked twice, read once
    assert post(app, "/lacuerda/artist", {"slug": "nobody"}).status == 404
    assert post(app, "/lacuerda/artist", {"slug": "joaquin_sabina"}, csrf="old").status == 403
    queue.run_pending()
    line = as_json(get_json(app, "/jobs.json"))["jobs"][0]["line"]
    assert line["text"] == "Done" and line["details"]  # what LaCuerda answered is in its output


def test_the_search_offers_to_read_the_page_of_a_name_lacuerda_hasnt_listed_yet(app, conn):
    # The owner's "estopa", with E not read yet: no artist of theirs in the index is no sign LaCuerda lacks them.
    lacuerda_index(conn)  # E and J read whole
    data = as_json(get(app, "/api/search?q=caifanes"))
    assert data["lacuerda_artists"] == [] and data["lacuerda_unlisted"] == {"name": "caifanes", "letter": "C"}
    assert as_json(get(app, "/api/search?q=estopa"))["lacuerda_unlisted"] is None  # listed: their row says it
    assert as_json(get(app, "/api/search?q=enrique%20bunbury"))["lacuerda_unlisted"] is None  # E is read whole
    # A title on Ultimate Guitar is no name to read; the artist the query names there is the one.
    from caracole.ug.index import upsert_rows

    creep_index(conn)
    upsert_rows(conn, [(3003, "caifanes", "afuera", "chords", "caifanes/afuera-chords-3003")], "1",
                datetime(2026, 10, 19, tzinfo=UTC))
    conn.commit()
    assert as_json(get(app, "/api/search?q=creep"))["lacuerda_unlisted"] is None
    assert as_json(get(app, "/api/search?q=caifanes%20afuera"))["lacuerda_unlisted"] == {
        "name": "Caifanes", "letter": "C"}
    # An artist only near the name is no answer: Bomba Estereo, for "soda stereo".
    from caracole import lacuerda_index as li
    from caracole.lacuerda import LCArtist

    li.store_artists(conn, "tabs/b/index0.html", [LCArtist("bomba_estereo", "Bomba Estereo", 5)])
    conn.commit()
    data = as_json(get(app, "/api/search?q=soda%20stereo"))
    assert [a["artist"] for a in data["lacuerda_artists"]] == ["Bomba Estereo"]
    assert data["lacuerda_unlisted"] == {"name": "soda stereo", "letter": "S"}


def test_the_search_offers_no_page_lacuerdas_own_answer_already_names(app, conn):
    # E's listing not read whole, Estopa's page read: LaCuerda's strong songs say who the query names, and no page
    # that can't exist ("estopa_como_camaron", "como_camaron") is offered.
    from caracole.ug.index import mark_built, upsert_rows

    lacuerda_index(conn, letters=("j",))
    for q in ("estopa%20como%20camaron", "como%20camaron"):
        data = as_json(get(app, f"/api/search?q={q}"))
        assert [h["title"] for h in data["lacuerda"]][:1] == ["Como Camarón"], q
        assert data["lacuerda_unlisted"] is None, q
    # Ultimate Guitar's songs by part of an artist's name name them: Enrique Bunbury's E, for "bunbury".
    when = datetime(2026, 10, 19, tzinfo=UTC)
    upsert_rows(conn, [(3101, "enrique-bunbury", "lady-blue", "chords", "enrique-bunbury/lady-blue-chords-3101")],
                "1", when)
    mark_built(conn, when)
    conn.commit()
    assert as_json(get(app, "/api/search?q=bunbury"))["lacuerda_unlisted"] == {"name": "Enrique Bunbury", "letter": "E"}


def test_lacuerda_leads_with_the_artist_the_query_names_when_ultimate_guitar_has_nothing_strong(app, conn):
    # "andres calamaro": Ultimate Guitar's index has Javier Calamaro alone, LaCuerda's has Andrés Calamaro.
    from caracole import lacuerda_index as li
    from caracole.lacuerda import LCArtist
    from caracole.ug.index import mark_built, upsert_rows

    when = datetime(2026, 10, 19, tzinfo=UTC)
    upsert_rows(conn, [(3201, "javier-calamaro", "amapolas", "chords", "javier-calamaro/amapolas-chords-3201"),
                       (3202, "estopa", "la-raja-de-tu-falda", "chords", "estopa/la-raja-de-tu-falda-chords-3202")],
                "1", when)
    mark_built(conn, when)
    lacuerda_index(conn)
    li.store_artists(conn, "tabs/a/index0.html", [LCArtist("andres_calamaro", "Andrés Calamaro", 325)])
    conn.commit()
    data = as_json(get(app, "/api/search?q=andres%20calamaro"))
    assert [a["artist"] for a in data["lacuerda_artists"]] == ["Andrés Calamaro"]
    assert data["lacuerda_leads"] is True and data["best"] is None  # Enter opens their Songs, which asks nothing
    estopa = as_json(get(app, "/api/search?q=estopa"))  # Ultimate Guitar names them too: its rows come first
    assert estopa["artists"] and estopa["lacuerda_artists"] and estopa["lacuerda_leads"] is False


def test_a_page_read_by_name_is_searched_at_once_and_its_request_says_what_lacuerda_answered(cfg, conn):
    from helpers.lacuerda_site import artist_page

    from caracole import db
    from caracole import lacuerda_index as li

    lacuerda_index(conn)  # E and J read whole: C, Caifanes', isn't

    def read(args, emit):  # caracole lacuerda --artist, as it takes the page in
        c = db.connect(cfg.db_path)
        try:
            li.store_artist_page(c, "caifanes", artist_page("Caifanes", "caifanes", ("afuera", "Afuera", "R-1")))
            c.commit()
        finally:
            c.close()
        emit("Read: LaCuerda's page of Caifanes lists 1 song, in the index now.")
        return 0

    queue = JobQueue(read)
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
    assert as_json(get(app, "/api/search?q=caifanes"))["lacuerda_artists"] == []  # an answer kept a few minutes
    data = as_json(post(app, "/lacuerda/artist", {"name": "  caifanes "}, accept="application/json"))
    [job] = queue.snapshot()
    assert job.steps[0].args == ("lacuerda", "--artist=caifanes") and job.display == "caifanes on LaCuerda"
    queue.run_pending()
    after = as_json(get(app, "/api/search?q=caifanes"))  # the read's over: no answer kept from before it
    assert [a["artist"] for a in after["lacuerda_artists"]] == ["Caifanes"] and after["lacuerda_unlisted"] is None
    page = as_json(get(app, "/api/artist?lacuerda_name=caifanes"))
    assert (page["slug"], page["read"], [h["title"] for h in page["songs"]]) == ("caifanes", True, ["Afuera"])
    assert as_json(get(app, data["url"]))["line"] == {
        "tone": "added", "text": "Read: LaCuerda's page of Caifanes lists 1 song, in the index now.", "link": None,
        "details": None}
    assert get(app, "/api/artist?lacuerda_name=nobody%20at%20all").status == 404
    for name in ("!!!", "", "x" * 201):
        assert post(app, "/lacuerda/artist", {"name": name}).status == 400, name
    assert len(queue.snapshot()) == 1


def test_get_it_on_a_lacuerda_song_keeps_that_sheet(app, cfg, queue, conn):
    url = LC + "estopa/como_camaron"
    response = lookup(app, {"artist": "Estopa", "title": "Como Camarón", "lacuerda": url})
    assert response.status == 202
    [job] = queue.snapshot()
    assert job.steps[0].args == ("get", "--progress", f"--lacuerda={url}", "--", "Estopa", "Como Camarón")
    assert "Estopa - Como Camarón" in cfg.wanted_file.read_text(encoding="utf-8")
    assert lookup(app, {"artist": "Estopa", "title": "Como Camarón", "lacuerda": "https://example.com/x"}).status == 400


def test_add_for_tonights_run_on_a_lacuerda_song_records_the_pick_with_its_add(app, cfg, queue):
    url = LC + "estopa/como_camaron"
    response = post(app, "/request", {"artist": "Estopa", "title": "Como Camarón", "lacuerda": url},
                    accept="application/json")
    assert response.status == 200
    [job] = queue.snapshot()
    assert job.steps[0].args == ("add", f"--lacuerda={url}", "--", "Estopa", "Como Camarón")
    fetched = post(app, "/request", {"artist": "Estopa", "title": "Tu Calorro", "lacuerda": LC + "estopa/tu_calorro",
                                     "fetch": "1"}, accept="application/json")
    assert fetched.status == 200
    assert queue.snapshot()[0].steps[0].args == (
        "get", "--progress", f"--lacuerda={LC}estopa/tu_calorro", "--", "Estopa", "Tu Calorro")
    assert post(app, "/request", {"artist": "Estopa", "title": "X", "lacuerda": "estopa"}).status == 400


def test_a_search_asks_no_site_and_takes_no_lock(app, conn, monkeypatch):
    from caracole.commands import _common

    def never(*args, **kwargs):
        raise AssertionError("a search asked a site, or took the lock")

    monkeypatch.setattr(_common, "make_client", never)
    monkeypatch.setattr(_common, "exclusive", never)
    creep_index(conn)
    site_pages(conn, gtptabs=["https://gtptabs.com/tabs/18/radiohead/creep.html"],
               musescore=["https://musescore.com/song/creep-1"])
    response = get(app, "/api/search?q=creep")
    assert response.status == 200 and as_json(response)["gtptabs"] and as_json(response)["musescore"]
    lacuerda_index(conn)  # LaCuerda has no search caracole uses: its index answers, and its artists' songs
    assert as_json(get(app, "/api/search?q=estopa"))["lacuerda_artists"]
    assert as_json(get(app, "/api/artist?lacuerda=estopa"))["songs"]


def test_a_search_of_fewer_than_three_letters_looks_nowhere(app, conn):
    creep_index(conn)
    assert as_json(get(app, "/api/search?q=cr")) == {"query": "cr", "library": [], "index": [], "short": True}
    assert as_json(get(app, "/api/search"))["short"] is True


def test_a_search_with_an_empty_index_says_so(app, conn):
    data = as_json(get(app, "/api/search?q=creep"))
    assert data["index"] == [] and "caracole index build" in data["hint"]


def test_the_search_answers_only_to_the_servers_names(app, conn):
    assert app.handle(Request("GET", "/api/search?q=creep", {"host": "evil.example"})).status == 421


def lookup(app, fields, **headers):
    return post(app, "/lookup", fields, accept="application/json", **headers)


def test_the_ug_song_you_pick_is_looked_up_now(app, cfg, queue, conn):
    response = lookup(app, {"artist": "Stone Temple Pilots", "title": "Creep", "ug": "stone-temple-pilots/creep"})
    assert response.status == 202
    data = as_json(response)
    assert (data["job"], data["url"]) == (1, "/api/jobs/1")
    # The library page follows it as it follows a request: the job as /jobs.json gives it.
    assert data["view"]["id"] == 1 and data["view"]["display"] == "Stone Temple Pilots - Creep"
    assert data["view"]["line"]["text"].startswith("Queued") and data["view"]["fetching"] is True
    assert "Stone Temple Pilots - Creep" in cfg.wanted_file.read_text(encoding="utf-8")  # at once, as a request
    job = queue.snapshot()[0]
    assert [s.args for s in job.steps] == [
        ("get", "--progress", "--ug=stone-temple-pilots/creep", "--", "Stone Temple Pilots", "Creep")]
    assert job.fetching and job.title == "Fetch Stone Temple Pilots - Creep"


def test_the_tab_you_pick_is_looked_up_now(app, queue):
    tab = "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4170"
    assert lookup(app, {"artist": "Radiohead", "title": "Creep", "ug": "radiohead/creep", "tab": tab}).status == 202
    assert queue.snapshot()[0].steps[0].args == (
        "get", "--progress", "--ug=radiohead/creep", f"--tab={tab}", "--", "Radiohead", "Creep")


def acdc_index(conn):
    from caracole.ug.index import mark_built, upsert_rows

    rows = [(11, "acdc", "back-in-black", "chords"), (12, "acdc", "back-in-black", "tabs"),
            (21, "song-dongye", "banma-banma", "chords"), (31, "r-e-m", "losing-my-religion", "chords")]
    upsert_rows(conn, [(t, a, s, k, f"{a}/{s}-{k}-{t}") for t, a, s, k in rows], "1",
                datetime(2026, 10, 19, tzinfo=UTC))
    mark_built(conn, datetime(2026, 10, 19, tzinfo=UTC))


def test_a_ug_hit_your_library_has_under_another_name_is_that_song(app, conn):
    # UG's slugs make "Acdc", "Song Dongye" and "R E M": your library's names are the song's.
    acdc_index(conn)
    acdc = add_song(conn, "AC/DC", "Back In Black")
    update_song(conn, acdc.id, match_decision="accept", match_artist_key="acdc", match_song_key="back-in-black")
    banma = add_song(conn, "宋冬野", "斑马斑马")  # not matched yet: its names still meet UG's
    rem = add_song(conn, "R.E.M.", "Losing My Religion")
    for query, song in (("back in black", acdc), ("banma banma", banma), ("losing my religion", rem)):
        [hit] = [h for h in as_json(get(app, "/api/search?q=" + query.replace(" ", "%20")))["index"]
                 if h["song"] is not None]
        assert hit["song"] == song.id, query
        assert (hit["library"]["artist"], hit["library"]["title"]) == (song.artist, song.title)


def test_getting_a_ug_hit_your_library_has_under_another_name_adds_no_second_song(app, cfg, conn, queue):
    acdc_index(conn)
    cfg.wanted_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.wanted_file.write_text("AC/DC - Back In Black\n", encoding="utf-8")
    acdc = add_song(conn, "AC/DC", "Back In Black")
    update_song(conn, acdc.id, match_decision="accept", match_artist_key="acdc", match_song_key="back-in-black")
    # The page's names for the hit, from UG's slugs, and its pick: the server finds the song it is.
    response = lookup(app, {"artist": "Acdc", "title": "Back In Black", "ug": "acdc/back-in-black"})
    assert response.status == 202
    assert cfg.wanted_file.read_text(encoding="utf-8") == "AC/DC - Back In Black\n"
    [job] = queue.snapshot()
    assert job.steps[0].args == ("get", "--progress", "--ug=acdc/back-in-black", "--", "AC/DC", "Back In Black")
    assert job.song_key == acdc.key and "AC/DC - Back In Black" in job.title


def test_get_it_now_on_a_song_of_your_library_adds_it_to_no_source(app, cfg, conn, queue):
    # A song from Spotify alone stays Spotify's: once unliked, it is no longer wanted.
    creep = add_song(conn, "Radiohead", "Creep", source="spotify", source_id="spotify:track:1")
    response = lookup(app, {"song": str(creep.id)})
    assert response.status == 202 and not cfg.wanted_file.exists()
    [job] = queue.snapshot()
    assert job.steps[0].args == ("get", "--progress", "--", "Radiohead", "Creep")
    assert lookup(app, {"song": "999"}).status == 404
    for huge in (BEYOND_SQLITE, f"-{BEYOND_SQLITE}"):  # no SQLite integer: no song either
        assert lookup(app, {"song": huge}).status == 404
    assert lookup(app, {"song": "x"}).status == 400


def test_a_song_you_removed_and_look_up_again_is_asked_for_again(app, cfg, conn, queue):
    # caracole remove left its tombstone; picking it on the lookup page is asking for it again, as a
    # wanted.txt line always is, and its lookup syncs that line back in. Its UG song is no song of yours.
    from caracole.removal import plan_removal, remove_song
    from caracole.songs import find_song

    creep_index(conn)
    creep = add_song(conn, "Radiohead", "Creep")
    remove_song(conn, cfg, plan_removal(conn, cfg, creep))
    assert find_song(conn, creep.key) is None
    [hit] = [h for h in as_json(get(app, "/api/search?q=creep"))["index"] if h["ug"] == "radiohead/creep"]
    assert hit["song"] is None and hit["library"] is None
    assert lookup(app, {"artist": "Radiohead", "title": "Creep", "ug": "radiohead/creep"}).status == 202
    assert "Radiohead - Creep" in cfg.wanted_file.read_text(encoding="utf-8")
    [job] = queue.snapshot()
    assert job.steps[0].args == ("get", "--progress", "--ug=radiohead/creep", "--", "Radiohead", "Creep")


def test_a_version_picked_while_the_first_lookup_runs_is_looked_up_too(cfg):
    import threading

    started, release = threading.Event(), threading.Event()
    ran = []

    def runner(args, emit):
        ran.append(list(args))
        started.set()
        release.wait(10)
        return 0

    queue = JobQueue(runner)
    queue.start()
    try:
        app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
        tab = "https://tabs.ultimate-guitar.com/tab/oasis/wonderwall-chords-6789"
        first = as_json(lookup(app, {"artist": "Oasis", "title": "Wonderwall", "ug": "oasis/wonderwall"}))
        assert started.wait(5)  # it runs now, and its sheet is on the screen
        pick = lookup(app, {"artist": "Oasis", "title": "Wonderwall", "ug": "oasis/wonderwall", "tab": tab})
        assert pick.status == 202 and as_json(pick)["job"] != first["job"]
        release.set()
        for _ in range(100):
            if len(ran) == 2 and not queue.active_count():
                break
            threading.Event().wait(0.05)
    finally:
        release.set()
        queue.stop()
    assert [a for a in ran[1] if a.startswith("--tab")] == [f"--tab={tab}"]


@pytest.mark.parametrize("fields,said", [
    ({"artist": "Radiohead", "title": "Creep", "ug": "radiohead"}, "Ultimate Guitar song"),
    ({"artist": "Radiohead", "title": "Creep", "tab": "https://example.com/tab/1"}, "tab"),
    ({"artist": "", "title": "Creep"}, "artist and a title"),
])
def test_a_pick_that_isnt_one_is_refused(app, cfg, queue, fields, said):
    response = lookup(app, fields)
    assert response.status == 400 and said in as_json(response)["error"]
    assert queue.snapshot() == [] and not cfg.wanted_file.exists()


def test_a_lookup_without_the_pages_script_lands_on_the_lookup_page(app, queue):
    response = post(app, "/lookup", {"artist": "Radiohead", "title": "Creep"})
    assert response.status == 303 and header(response, "location") == "/lookup?job=1"


def test_a_lookup_needs_the_form_token_like_every_write(app, queue):
    assert lookup(app, {"artist": "Radiohead", "title": "Creep"}, csrf="wrong").status == 403
    assert queue.snapshot() == []


def test_the_lookup_pages_script_hears_a_refusal_as_data_and_is_told_to_reload(app, queue):
    # A phone left open across a restart of the server sends the old form token.
    stale = lookup(app, {"artist": "Radiohead", "title": "Creep"}, csrf="older")
    assert stale.status == 403 and as_json(stale)["reload"] is True and "reload" in as_json(stale)["error"]
    elsewhere = lookup(app, {"artist": "Radiohead", "title": "Creep"}, **{"sec-fetch-site": "cross-site"})
    assert elsewhere.status == 403 and "another site" in as_json(elsewhere)["error"]
    not_a_form = post(app, "/lookup", {"artist": "A", "title": "B"}, accept="application/json",
                      **{"content-type": "text/plain"})
    assert not_a_form.status == 415 and "error" in as_json(not_a_form)
    assert queue.snapshot() == []


def test_before_signing_in_the_api_and_the_lookups_answer_data(locked, conn):
    response = get(locked, "/api/search?q=creep")
    assert response.status == 401 and as_json(response)["reload"] is True
    refused = lookup(locked, {"artist": "Radiohead", "title": "Creep"})
    assert refused.status == 401 and "Sign in" in as_json(refused)["error"]
    assert get(locked, "/lookup").status == 401 and 'action="/login"' in text(get(locked, "/lookup"))


def test_a_job_is_served_as_data_with_each_step_and_its_state(app, queue):
    lookup(app, {"artist": "Radiohead", "title": "Creep"})
    data = as_json(get(app, "/api/jobs/1"))
    assert data["id"] == 1 and data["state"] == "queued"
    assert [s["name"] for s in data["steps"]][:3] == ["song", "match", "sheet"]
    assert all(s["state"] == "waiting" for s in data["steps"])
    assert [j["id"] for j in as_json(get(app, "/api/jobs"))["jobs"]] == [1]
    assert get(app, "/api/jobs/9").status == 404 and get(app, "/api/jobs/x").status == 404


@pytest.mark.parametrize("number", ["%C2%B2", "%D9%A1", "%EF%BC%91"])  # ², Arabic-Indic 1, fullwidth 1
def test_a_request_number_of_other_digits_than_0_to_9_is_no_request(app, queue, number):
    lookup(app, {"artist": "Radiohead", "title": "Creep"})
    response = get(app, f"/api/jobs/{number}")
    assert response.status == 404 and as_json(response) == {"error": "no such request"}


@pytest.mark.parametrize("path", ["/api/search?q=creep", "/api/artist?key=radiohead", "/api/jobs", "/api/jobs/1"])
def test_the_api_answers_its_own_pages_and_no_other_site(app, conn, queue, path):
    # Another site can't read the answers, but it could make the server search for it: refused.
    creep_index(conn)
    lookup(app, {"artist": "Radiohead", "title": "Creep"})
    for site in ("cross-site", "same-site"):
        response = get(app, path, **{"sec-fetch-site": site})
        assert response.status == 403 and "another site" in as_json(response)["error"], site
    assert get(app, path, **{"sec-fetch-site": "same-origin"}).status == 200
    assert get(app, path, **{"sec-fetch-site": "none"}).status == 200  # typed into the address bar
    assert get(app, path).status == 200  # no browser: curl, a script on this machine


def test_a_search_typed_over_lets_go_of_the_database_at_once(app, conn, monkeypatch):
    # A query of one very common word reads tens of thousands of rows: the next one typed doesn't wait for it.
    import threading
    import time

    import caracole.search

    creep_index(conn)
    started = threading.Event()
    real = caracole.search.find_index

    def find_index(c, query, **kwargs):
        if query != "slow words":
            return real(c, query, **kwargs)
        started.set()
        c.execute("WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 300000000) "
                  "SELECT count(*) FROM n").fetchone()  # half a minute or more, unless interrupted
        return caracole.search.IndexFound()

    monkeypatch.setattr(caracole.search, "find_index", find_index)
    first: dict = {}
    newer: dict = {}
    older = threading.Thread(target=lambda: first.update(as_json(get(app, "/api/search?q=slow%20words"))),
                             daemon=True)
    older.start()
    assert started.wait(10)
    begun = time.monotonic()
    typed = threading.Thread(target=lambda: newer.update(as_json(get(app, "/api/search?q=creep"))), daemon=True)
    typed.start()
    typed.join(5)
    assert not typed.is_alive(), "the newer search waited for the older one"
    older.join(5)
    assert not older.is_alive() and time.monotonic() - begun < 5
    assert first == {"query": "slow words", "superseded": True}
    assert newer["index"][0]["ug"] == "radiohead/creep"
    assert "slow words" not in app._found  # an interrupted search is no answer to keep


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


def links_on_the_page(app):
    """Each file link on the library page, by the file's name: its address on the server."""
    import json

    songs = json.loads(JSON_BLOCK.search(text(get(app, "/"))).group(1))
    return {f["name"]: "/" + f["href"] for song in songs["songs"] for f in song["files"]}


def test_the_viewer_caracole_wrote_is_served_in_a_sandbox(app, conn, cfg):
    song = rendered_song(conn, cfg)
    auto = rendered_song(conn, cfg, "Placeholder Band", "Synthetic Song", auto=True)
    links = links_on_the_page(app)
    for one, name in ((song, "sheet.html"), (auto, "sheet (auto).html")):
        response = get(app, links[name])
        assert response.status == 200, name
        assert response.body == (song_dir(cfg.library_dir, one) / name).read_bytes()
        assert header(response, "content-type") == "text/html; charset=utf-8"
        policies = [v for k, v in response.headers if k.lower() == "content-security-policy"]
        own = META_POLICY.search(text(response)).group(1)
        assert policies == [f"sandbox allow-scripts; {own}; frame-ancestors 'none'"]  # a sandbox, no framing
        assert header(response, "x-frame-options") == "DENY" and header(response, "cache-control") == "no-store"
        assert header(response, "x-content-type-options") == "nosniff"
        assert header(response, "content-disposition") is None
        assert app.handle(Request("HEAD", links[name], {"host": HOST})).status == 200


def test_a_viewer_written_before_an_upgrade_goes_out_with_its_own_policy(app, conn, cfg, monkeypatch):
    # The viewer on disk carries the hashes of the script and style it was written with; a newer
    # caracole's would make the browser refuse them, until the next render writes it again.
    from caracole.library_page import sha256_source
    from caracole.viewer import page

    rendered_song(conn, cfg)
    style, script = page._assets()
    monkeypatch.setattr(page, "_assets", lambda: (style + "\n.new {}", script + "\n// a new release"))
    response = get(app, "/" + quote("Soda Stereo/De Música Ligera/sheet.html"))
    assert response.status == 200
    sent = text(response)
    policy = header(response, "content-security-policy")
    assert f"script-src {sha256_source(re.search(r'<script>(.*?)</script>', sent, re.S).group(1))};" in policy
    assert f"style-src {sha256_source(re.search(r'<style>(.*?)</style>', sent, re.S).group(1))};" in policy
    assert policy.startswith("sandbox allow-scripts; default-src 'none'; ")
    assert policy.endswith("; frame-ancestors 'none'")


def test_a_planted_page_is_not_served(app, conn, cfg):
    song = rendered_song(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    page = (folder / "sheet.html").read_bytes()
    (folder / "notes.html").write_bytes(page)  # caracole's own bytes, at a name it never writes
    (folder / "sheet (auto).html").write_bytes(page)  # at a name it writes, but not in this folder
    (folder / "index.html").write_bytes(page)
    (cfg.library_dir / "Soda Stereo" / "sheet.html").write_bytes(page)
    stranger = cfg.library_dir / "Unknown Artist" / "Unknown Song"  # a song the database doesn't know
    stranger.mkdir(parents=True)
    (stranger / "sheet.html").write_bytes(page)
    for path in ("Soda Stereo/De Música Ligera/notes.html", "Soda Stereo/De Música Ligera/sheet (auto).html",
                 "Soda Stereo/De Música Ligera/index.html", "Soda Stereo/sheet.html", "sheet.html",
                 "Unknown Artist/Unknown Song/sheet.html", "Soda Stereo/De Música Ligera/SHEET.HTML",
                 "Soda Stereo/De Música Ligera/sheet.htm"):
        response = get(app, "/" + quote(path))
        assert response.status == 404, path
        assert b"<script" not in response.body
    assert get(app, "/" + quote("Soda Stereo/De Música Ligera/sheet.html")).status == 200


@pytest.mark.parametrize("edit", [
    lambda page: page + b"<script>fetch('/caracole.sqlite')</script>",
    lambda page: page.replace(b"<body", b"<BODY", 1),  # the same length
])
def test_an_edited_viewer_is_not_served(app, conn, cfg, edit):
    song = rendered_song(conn, cfg)
    viewer = song_dir(cfg.library_dir, song) / "sheet.html"
    viewer.write_bytes(edit(viewer.read_bytes()))
    assert get(app, "/" + quote("Soda Stereo/De Música Ligera/sheet.html")).status == 404


def test_a_viewer_not_served_says_why_and_what_to_do(app, conn, cfg):
    # index.html lists the file whatever it holds, as the card's first link: the 404 says what happened.
    song = rendered_song(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    (folder / "sheet.html").write_bytes((folder / "sheet.html").read_bytes() + b"<!-- edited -->")
    response = get(app, "/" + quote("Soda Stereo/De Música Ligera/sheet.html"))
    assert response.status == 404
    said = shown(response)
    assert "This sheet viewer isn't the page caracole last wrote here" in said
    assert "the next caracole render writes it again" in said and "The PDF is beside it" in said
    assert "no such page or file" not in said
    other = shown(get(app, "/" + quote("Soda Stereo/De Música Ligera/notes.txt")))
    assert "no such page or file" in other and "sheet viewer" not in other


def test_a_viewer_that_cant_be_read_doesnt_blame_the_database(app, conn, cfg, monkeypatch):
    import errno

    from caracole.web import files

    rendered_song(conn, cfg)

    def fails(fd):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(files.os, "fstat", fails)
    response = get(app, "/" + quote("Soda Stereo/De Música Ligera/sheet.html"))
    assert response.status == 404 and "database" not in shown(response)


def test_a_link_in_a_viewers_place_is_not_followed(app, conn, cfg, tmp_path):
    song = rendered_song(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    copy = tmp_path / "elsewhere" / "sheet.html"
    copy.parent.mkdir()
    copy.write_bytes((folder / "sheet.html").read_bytes())  # the very bytes caracole wrote
    (folder / "sheet.html").unlink()
    (folder / "sheet.html").symlink_to(copy)
    assert get(app, "/" + quote("Soda Stereo/De Música Ligera/sheet.html")).status == 404


def test_a_viewer_of_a_song_the_database_no_longer_holds_is_not_served(app, conn, cfg):
    song = rendered_song(conn, cfg)
    for table in ("files", "versions"):
        conn.execute(f"DELETE FROM {table} WHERE song_id = ?", (song.id,))
    conn.execute("DELETE FROM songs WHERE id = ?", (song.id,))
    assert (song_dir(cfg.library_dir, song) / "sheet.html").is_file()
    assert get(app, "/" + quote("Soda Stereo/De Música Ligera/sheet.html")).status == 404


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
    # The page's script is told to sign in again, in JSON.
    response = get_json(locked, "/jobs.json")
    assert response.status == 401 and "Sign in" in answer(response)["error"]
    response = post(locked, "/request", {"artist": "A", "title": "B"}, accept=JSON)
    assert response.status == 401 and "Sign in" in answer(response)["error"]


def test_signing_in_sets_a_cookie_that_opens_the_library(locked, conn):
    add_song(conn, "Radiohead", "Creep")
    assert post(locked, "/login", {"token": "wrong"}).status == 401
    assert post(locked, "/login", {"token": "a-long-random-access-token"}, csrf="bad").status == 403
    response = post(locked, "/login", {"token": "a-long-random-access-token"})
    assert response.status == 303 and header(response, "location") == "/"
    cookie = header(response, "set-cookie")
    value = session_value("a-long-random-access-token")
    assert cookie.startswith(f"caracole_session={value};")
    # Lax, not Strict: the sandboxed viewer's links are navigations from another origin (its own),
    # which a Strict cookie doesn't go with. Writes keep the form token and the cross-origin check.
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie and "Path=/" in cookie
    assert "a-long-random-access-token" not in cookie
    signed_in = get(locked, "/", cookie=f"caracole_session={value}")
    assert signed_in.status == 200 and "Radiohead - Creep" in text(signed_in)
    assert get(locked, "/", cookie="caracole_session=forged").status == 401


def test_a_viewer_waits_for_signing_in_like_any_file(locked, conn, cfg):
    rendered_song(conn, cfg)
    viewer = "/" + quote("Soda Stereo/De Música Ligera/sheet.html")
    response = get(locked, viewer)
    assert response.status == 401 and b"Palabras" not in response.body
    signed_in = get(locked, viewer, cookie=f"caracole_session={session_value('a-long-random-access-token')}")
    assert signed_in.status == 200 and b"Palabras" in signed_in.body
