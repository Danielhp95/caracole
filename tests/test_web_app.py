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


NAV = re.compile(r'<nav class="links" aria-label="Pages">(.*?)</nav>', re.S)
NAVLINK = re.compile(r'<a class="navlink" href="([^"]*)">([^<]*)')


def test_the_served_mastheads_link_neither_the_to_do_page_nor_the_lookup_page(app, conn):
    # The library page's bar does what the lookup page does: no page's masthead links /lookup, and none links
    # _todo.md, which the nightly run still writes. The lookup page answers still, for a lookup posted without
    # JavaScript and for the /lookup?q= links there are.
    add_song(conn, "Radiohead", "Creep")
    assert NAVLINK.findall(NAV.search(text(get(app, "/"))).group(1)) == [("/jobs", "Requests")]
    pages = ("/jobs", "/review?song=999", "/review?song=1", "/nothing.pdf")
    for page in (get(app, path) for path in pages):
        assert NAVLINK.findall(NAV.search(text(page)).group(1)) == [("/", "Library")], page.status
    assert get(app, "/lookup").status == 200 and get(app, "/lookup?q=creep").status == 200


def test_every_answer_keeps_the_page_to_itself(app, conn):
    for response in (get(app, "/"), get(app, "/jobs"), get(app, "/nothing.pdf")):
        assert header(response, "x-content-type-options") == "nosniff"
        assert header(response, "x-frame-options") == "DENY"
        assert "frame-ancestors 'none'" in header(response, "content-security-policy")
        assert header(response, "referrer-policy") == "same-origin"
        if header(response, "content-type").startswith("text/html"):  # and a page opened from a file says so too
            assert '<meta name="referrer" content="same-origin">' in text(response)
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


def test_the_page_keeps_its_own_timers_unless_a_test_sets_them(app, cfg, conn, queue):
    # The page's script asks /jobs.json every 1.5 s and counts Remove's five seconds (library.js); the tests that
    # drive it on real time shorten both (``WebApp(timers=...)``), which caracole serve never sets
    # (test_commands_serve.py), so the page users get carries none.
    add_song(conn, "Radiohead", "Creep")
    assert "timers" not in json.loads(JSON_BLOCK.search(text(get(app, "/"))).group(1))["server"]
    quick = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok", timers={"poll": 100, "undo": 1000})
    server = json.loads(JSON_BLOCK.search(text(get(quick, "/"))).group(1))["server"]
    assert server["timers"] == {"poll": 100, "undo": 1000}


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


def test_the_pages_remove_asks_what_goes_as_data_and_queues_nothing(app, conn, cfg, queue):
    # The library page's Remove says on the card, while it counts down to Undo, what goes: the page's script
    # posts the question (no confirm) and reads the answer as data. Nothing is queued, nothing changes.
    creep = a_kept_song(conn, cfg)
    response = post(app, "/remove", {"song": str(creep.id)}, accept=JSON)
    assert response.status == 200
    removal = answer(response)["removal"]
    assert removal["song"] == creep.id and removal["key"] == creep.key and removal["display"] == "Radiohead - Creep"
    assert removal["brief"] == ("Deletes caracole's 1 file for it, its record and its wanted.txt line; "
                                "leaves 1 other file; never touches Music/.")
    assert "its line in wanted.txt (line 1)" in removal["goes"]
    assert removal["stays"] == ["Radiohead/Creep/notes <b>.md: caracole didn't write it"]
    assert queue.snapshot() == [] and cfg.wanted_file.read_text(encoding="utf-8") == "Radiohead - Creep\n"


def test_a_removal_the_pages_script_confirms_is_answered_with_its_job(app, conn, cfg, queue):
    # Its 5 seconds over, the page sends the removal and stays where it is: the answer is the job, whose line
    # its card shows ("Queued…", "Removing from caracole…", "Removed"), never a page to go to.
    creep = a_kept_song(conn, cfg)
    response = post(app, "/remove", {"song": str(creep.id), "key": creep.key, "confirm": "1"}, accept=JSON)
    assert response.status == 200 and header(response, "location") is None
    view = answer(response)["job"]
    assert view["kind"] == "remove" and view["songId"] == creep.id and view["line"]["text"] == "Queued…"
    assert [s.args for s in queue.snapshot()[0].steps] == [("remove", "--yes", "--", "Radiohead - Creep")]
    # Sent twice, it is the same request.
    again = answer(post(app, "/remove", {"song": str(creep.id), "key": creep.key, "confirm": "1"}, accept=JSON))
    assert again["job"]["id"] == view["id"] and len(queue.snapshot()) == 1
    refused = post(app, "/remove", {"song": str(creep.id), "key": "oasis/wonderwall", "confirm": "1"}, accept=JSON)
    assert refused.status == 409 and "reload the library" in answer(refused)["error"]


@pytest.mark.parametrize("names,lines,youtube,said", [
    ((), (), (), "Deletes its record; never touches Music/."),
    (("info.json", "sheet.pdf", "sheet.txt"), (3, 7), (), "Deletes caracole's 3 files for it, its record and its "
                                                            "2 wanted.txt lines; never touches Music/."),
    (("sheet.txt",), (1,), ("Creep.m4a",), "Deletes caracole's 1 file for it, its record, its wanted.txt line and "
                                           "its audio from YouTube; never touches Music/."),
], ids=["nothing", "files-and-lines", "youtube"])
def test_what_a_removal_takes_in_one_sentence(conn, cfg, names, lines, youtube, said):
    from pathlib import PurePosixPath

    from caracole.removal import RemovalPlan, brief

    creep = add_song(conn, "Radiohead", "Creep")
    plan = RemovalPlan(creep, PurePosixPath("Radiohead/Creep"), delete=names, wanted_lines=lines,
                       youtube_audio=youtube)
    assert brief(plan) == said
    linked = RemovalPlan(creep, PurePosixPath("Radiohead/Creep"), folder_problem="Radiohead/Creep/ is a link")
    assert brief(linked) == ("Deletes its record; leaves its folder (Radiohead/Creep/ is a link); never touches "
                             "Music/.")
    unread = RemovalPlan(creep, PurePosixPath("Radiohead/Creep"), wanted_problem="a symbolic link")
    assert brief(unread).startswith("wanted.txt can't be read (a symbolic link), so nothing goes until it can")


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
    assert "Radiohead - Creep" in line and "Remove Radiohead" not in line and "Queued, next" in line
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


def test_a_requests_song_comes_with_its_identity_which_an_id_given_again_never_shares(app, conn, cfg, queue):
    # songs.id has no AUTOINCREMENT: once the newest song is removed, the next one added gets its id again. A page that
    # knew the removed song by that id tells the two apart by the identity key each view names with its song.
    creep = add_song(conn, "Radiohead", "Creep")
    fetch = answer(post(app, "/fetch", {"song": str(creep.id)}, accept=JSON))["job"]
    lookup = answer(post(app, "/request", {"artist": "Muse", "title": "Uprising", "fetch": "1"}, accept=JSON))["job"]
    removal = answer(post(app, "/remove", {"song": str(creep.id), "key": creep.key, "confirm": "1"},
                          accept=JSON))["job"]
    assert (fetch["songId"], fetch["identity"]) == (creep.id, creep.key)
    assert (lookup["songId"], "identity" in lookup) == (None, False)  # no song yet
    assert (removal["songId"], removal["identity"]) == (creep.id, creep.key)
    conn.execute("DELETE FROM songs WHERE id = ?", (creep.id,))  # removed
    uprising = add_song(conn, "Muse", "Uprising")
    assert uprising.id == creep.id
    seen = {j["id"]: (j["songId"], j.get("identity")) for j in answer(get_json(app, "/jobs.json"))["jobs"]}
    assert seen == {fetch["id"]: (None, None), lookup["id"]: (creep.id, uprising.key),
                    removal["id"]: (creep.id, creep.key)}  # a removal's song is gone: the job knows which it was


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
    # Ready, alone: the song's line opens its sheet; the list of requests opens it by the song's name (``sheet``).
    assert job["line"] == {"tone": "ready", "text": "Ready", "link": None, "details": None}
    assert job["sheet"] == "Radiohead/Creep/sheet.pdf"
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
    # On /jobs it is Failed, the error its reason, and the output right under it, behind its Output toggle: no
    # link to the same page, and Try again.
    item = dict(JOB_ITEM.findall(text(get(app, "/jobs"))))["1"]
    line = re.search(r'<p class="line">(.*?)</p>', item, re.S).group(1)
    assert '<span class="says failed">Failed</span>' in line and "<a " not in line and "Details" not in item
    assert '<p class="reason">The page under [artist_url] for Radiohead, UG answers 404 for it.</p>' in item
    assert 'action="/jobs/again"' in item and ">Try again</button>" in item


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
    assert f'href="/review?song={song.id}">Pick the match</a>' in article and "to-do" not in article
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
    assert job_id == "1" and "Queued, next" in item
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
    assert "Radiohead - Creep" in line and '<span class="says ready">Ready</span>' in line
    assert '<a class="btn act primary" href="/Radiohead/Creep/sheet.pdf">Open</a>' in newest
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
            (4172, "radiohead", "creep", "tabs"), (5001, "stone-temple-pilots", "creep", "chords"),
            (9, "oasis", "wonderwall", "chords")]
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
    # The library page's own bar searches the sites as you type: it links no other page for it, and has no button.
    library = text(get(app, "/"))
    assert 'href="/lookup"' not in library and 'id="q"' in library and 'id="all"' not in library


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
    assert first["counts"] == {"chords": 2, "tabs": 1} and first["song"] == mine.id
    assert [t["id"] for t in first["tabs"]][:2] == [4169, 4170]  # chords first
    assert first["tabs"][0] == {"id": 4169, "type": "chords", "label": None,
                                "url": "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"}
    assert (second["ug"], second["song"]) == ("stone-temple-pilots/creep", None)


def test_the_search_finds_your_songs_by_a_progression_typed_or_named(app, conn):
    from caracole.db import kv_set_json
    from caracole.progressions import KV, sheet_progressions

    verse = "{title: X}\n{comment: Verse}\n[Am]a [F]b [C]c [G]d\n"
    played = {}
    for title, key in (("In C", "C"), ("In A Minor", "Am"), ("Andalusian", "Am")):
        song = played[title] = add_song(conn, "Placeholder Band", title)
        sheet = verse if title != "Andalusian" else "{title: X}\n{comment: Verse}\n[Am]a [G]b [F]c [E]d\n"
        kv_set_json(conn, f"{KV}{song.id}", sheet_progressions(sheet, key))
    add_song(conn, "Radiohead", "Creep")
    data = as_json(get(app, "/api/search?q=" + quote("vi IV I V")))
    assert data["progression"] == {"key": "I V vi IV", "label": "I–V–vi–IV", "name": "the pop progression", "songs": 2}
    # Your songs that play it come as your songs do, read by their progression; never the row Enter acts on.
    assert {(h["id"], h["via"]) for h in data["library"]} == {(played["In C"].id, "progression"),
                                                             (played["In A Minor"].id, "progression")}
    assert data["best"] is None
    named = as_json(get(app, "/api/search?q=andalusian"))
    assert named["progression"]["name"] == named["progression"]["label"] == "the Andalusian cadence"
    assert [h["id"] for h in named["library"]] == [played["Andalusian"].id]
    assert as_json(get(app, "/api/search?q=creep"))["progression"] is None
    none = as_json(get(app, "/api/search?q=" + quote("ii V I")))
    assert none["progression"]["songs"] == 0 and none["library"] == []


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



def by_word_index(conn):
    """Lynyrd Skynyrd (five songs), Sam Grow's song Skynyrd, Metallica and La Naranja Metalica."""
    from caracole.ug.index import mark_built, upsert_rows

    rows = [(11, "lynyrd-skynyrd", "free-bird", "chords"), (12, "lynyrd-skynyrd", "free-bird", "tabs"),
            (13, "lynyrd-skynyrd", "simple-man", "chords"), (14, "lynyrd-skynyrd", "sweet-home-alabama", "chords"),
            (15, "lynyrd-skynyrd", "tuesdays-gone", "chords"), (16, "lynyrd-skynyrd", "that-smell", "chords"),
            (21, "sam-grow", "skynyrd", "chords"), (31, "metallica", "one", "tabs"), (32, "metallica", "fuel", "tabs"),
            (41, "la-naranja-metalica", "fuego", "chords")]
    upsert_rows(conn, [(t, a, s, k, f"{a}/{s}-{k}-{t}") for t, a, s, k in rows], "1", datetime(2026, 10, 19, tzinfo=UTC))
    mark_built(conn, datetime(2026, 10, 19, tzinfo=UTC))


def test_api_search_gives_an_artist_by_a_word_of_their_name_first_and_enter_takes_no_song(app, conn):
    by_word_index(conn)
    data = as_json(get(app, "/api/search?q=skynyrd"))
    [artist] = data["artists"]
    assert {k: artist[k] for k in ("artist_key", "artist", "songs", "part", "group_key")} == {
        "artist_key": "lynyrd-skynyrd", "artist": "Lynyrd Skynyrd", "songs": 5, "part": True,
        "group_key": "lynyrd-skynyrd"}
    assert [h["ug"] for h in data["index"]] == ["sam-grow/skynyrd"]  # the song titled so, still shown
    assert (data["lead"], data["best"], data["suggest"]) == ("artist", None, [])  # Enter opens their songs
    assert as_json(get(app, "/api/search?q=lynyrd%20skynyrd"))["artists"][0]["part"] is False


def test_api_search_suggests_artists_spelled_close_to_a_query_nothing_matches(app, conn):
    by_word_index(conn)
    before = as_json(get(app, "/api/search?q=lynrd"))
    assert (before["artists"], before["index"], before["best"]) == ([], [], None)
    assert before["suggest"] == [{"source": "ug", "artist": "Lynyrd Skynyrd", "artist_key": "lynyrd-skynyrd",
                                  "songs": 5, "group_key": "lynyrd-skynyrd"}]
    assert before["hint"].startswith("Nothing in the offline Ultimate Guitar index matches well.")  # as it was
    metalica = as_json(get(app, "/api/search?q=metalica"))
    assert [a["artist"] for a in metalica["artists"]] == ["La Naranja Metalica"]
    assert [s["artist"] for s in metalica["suggest"]] == ["Metallica"]
    # A song of yours by that title matches well: nothing to suggest.
    add_song(conn, "Someone", "Lynrd")
    assert as_json(get(app, "/api/search?q=lynrd"))["suggest"] == []


def test_api_search_suggests_lacuerdas_artists_by_the_slug_of_their_page(app, conn):
    from caracole import lacuerda_index as li
    from caracole.lacuerda import LCArtist

    either_index(conn)
    li.store_artists(conn, "tabs/j/index0.html", [LCArtist("joaquin_sabina", "Joaquín Sabina", 241)])
    assert as_json(get(app, "/api/search?q=sabinna"))["suggest"] == [
        {"source": "lacuerda", "artist": "Joaquín Sabina", "slug": "joaquin_sabina", "songs": 241,
         "group_key": "joaquin-sabina"}]


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
                                "why": "its index is empty: the nightly run reads its listings of every artist"},
                               {"source": "harptabs", "name": "harptabs.com",
                                "why": "its index is empty: the nightly run reads its sitemap"}]


def test_the_search_lists_harptabs_tabs_by_title_and_none_while_it_is_turned_off(app, cfg, conn):
    import dataclasses

    from caracole.config import ProviderPolicy
    from caracole.harptabs import parse_page_url

    creep_index(conn)
    conn.executemany("INSERT INTO harptabs_index (path, kind, page_id, key, sitemap) VALUES (?, ?, ?, ?, 'sitemap')",
                     [tuple(parse_page_url(f"https://www.harptabs.com/tab/{n}/creep")) for n in (7, 3)])
    conn.commit()
    data = as_json(get(app, "/api/search?q=creep"))
    assert data["harptabs"] == [
        {"source": "harptabs", "title": "Creep", "url": "https://www.harptabs.com/tab/3/creep", "score": 100.0},
        {"source": "harptabs", "title": "Creep", "url": "https://www.harptabs.com/tab/7/creep", "score": 100.0}]
    assert data["harptabs_artists"] == []
    [chip] = [s for s in data["looked"] if s["source"] == "harptabs"]
    assert (chip["state"], chip["label"]) == ("done", "harptabs.com ✓")  # no artist to read: its tabs, whole
    off = dataclasses.replace(cfg, providers={**cfg.providers, "harptabs": ProviderPolicy(20, (10.0, 20.0), False)})
    data = as_json(get(WebApp(off, JobQueue(Recorder()), allowed=ALLOWED, csrf="tok"), "/api/search?q=creep"))
    assert data["harptabs"] == [] and data["harptabs_artists"] == []
    [chip] = [s for s in data["looked"] if s["source"] == "harptabs"]
    assert (chip["state"], chip["label"]) == ("off", "harptabs.com: off")


def harptabs_index(conn) -> None:
    """harptabs.com's index as test_search.py makes it: the captured sitemap, Billy Joel's page and the Beatles'."""
    from test_search import harptabs_index as made

    made(conn)
    conn.commit()


def test_the_search_lists_harptabs_artists_and_their_songs_in_the_groups_and_lines_of_the_other_sites(app, conn):
    harptabs_index(conn)
    mine = add_song(conn, "Billy Joel", "Vienna")
    conn.commit()
    data = as_json(get(app, "/api/search?q=billy%20joel"))
    [joel] = data["harptabs_artists"]
    assert {k: joel[k] for k in ("source", "artist", "path", "url", "songs", "known", "score", "part", "group_key")} == {
        "source": "harptabs", "artist": "billy joel", "path": "artist/1178/billy-joel",
        "url": "https://www.harptabs.com/artist/1178/billy-joel", "songs": 98, "known": 7, "score": 100.0,
        "part": False, "group_key": "billy-joel"}
    assert joel["held"] == 4  # the songs those 7 tabs are of
    piano, vienna, _ = joel["top"]
    assert {k: piano[k] for k in ("source", "artist", "title", "url", "uploads", "artist_key", "title_key", "song")} == {
        "source": "harptabs", "artist": "billy joel", "title": "piano man", "url": "https://www.harptabs.com/tab/25/piano-man",
        "uploads": 4, "artist_key": "billy-joel", "title_key": "piano-man", "song": None}
    assert [t["title"] for t in piano["tabs"]][:2] == ["piano man", "Piano Man (C Harmonica)"]
    assert piano["tabs"][0] == {"title": "piano man", "url": "https://www.harptabs.com/tab/25/piano-man",
                                "views": 1_100_000, "rating": 4.0, "key": "C", "difficulty": "Beginner"}
    assert (vienna["song"], vienna["same_artist"], vienna["library"]["id"]) == (mine.id, True, mine.id)  # yours
    data = as_json(get(app, "/api/search?q=piano%20man"))
    assert [(h.get("artist"), h["url"]) for h in data["harptabs"]] == [
        ("billy joel", "https://www.harptabs.com/tab/25/piano-man"), (None, "https://www.harptabs.com/tab/29525/piano-man")]


def test_the_search_says_how_far_harptabs_coms_artist_index_has_got(app, conn):
    harptabs_index(conn)  # 2 of the sitemap's 3 artists read
    data = as_json(get(app, "/api/search?q=piano%20man"))
    [chip] = [s for s in data["looked"] if s["source"] == "harptabs"]
    assert (chip["state"], chip["label"]) == ("partial", "harptabs.com: 2 of 3 artists")
    assert chip["detail"] == ("harptabs.com's artist pages are still being read: 2 of 3 artists so far; caracole "
                              "harptabs --index reads the rest.")
    assert {"source": "harptabs", "name": "harptabs.com", "why": chip["detail"][len("harptabs.com's "):-1]} in [
        {**p, "why": p["why"].removeprefix("its ")} for p in data["partial"]]


def test_api_artist_lists_a_harptabs_artists_songs_and_yours(app, conn):
    harptabs_index(conn)
    mine = add_song(conn, "Billy Joel", "Piano Man")
    conn.commit()
    data = as_json(get(app, "/api/artist?harptabs=artist/1178/billy-joel"))
    assert {k: data[k] for k in ("source", "path", "artist", "url", "group_key", "listed", "total", "read")} == {
        "source": "harptabs", "path": "artist/1178/billy-joel", "artist": "billy joel",
        "url": "https://www.harptabs.com/artist/1178/billy-joel", "group_key": "billy-joel", "listed": 98, "total": 7,
        "read": True}
    assert [h["title"] for h in data["songs"]] == ["piano man", "Vienna!", "She's Always a Woman",
                                                    "New York State Of Mind"]
    assert data["songs"][0]["song"] == mine.id and [s["id"] for s in data["library"]] == [mine.id]
    unread = as_json(get(app, "/api/artist?harptabs=artist/7829/ritchie-valens"))
    assert (unread["artist"], unread["read"], unread["songs"], unread["listed"]) == ("Ritchie Valens", False, [], 0)
    assert get(app, "/api/artist?harptabs=artist/9/nobody").status == 404


def test_reading_a_harptabs_artists_page_is_one_command_in_the_queue(app, conn, queue):
    harptabs_index(conn)
    response = post(app, "/harptabs/artist", {"path": "artist/7829/ritchie-valens"}, accept="application/json")
    assert response.status == 202
    data = as_json(response)
    assert data["url"] == f"/api/jobs/{data['job']}"
    [job] = queue.snapshot()
    assert [s.args for s in job.steps] == [("harptabs", "--artist=artist/7829/ritchie-valens")]
    assert job.display == "Ritchie Valens on harptabs.com"
    assert job.song_key == "harptabs-artist:artist/7829/ritchie-valens"
    again = as_json(post(app, "/harptabs/artist", {"path": "artist/7829/ritchie-valens"}, accept="application/json"))
    assert again["job"] == data["job"] and len(queue.snapshot()) == 1  # asked twice, read once
    assert post(app, "/harptabs/artist", {"path": "artist/9/nobody"}).status == 404
    assert post(app, "/harptabs/artist", {"path": "tab/25/piano-man"}).status == 400
    assert post(app, "/harptabs/artist", {"path": "artist/7829/ritchie-valens"}, csrf="old").status == 403


def test_get_it_on_a_harptabs_tab_keeps_that_tab(app, cfg, queue, conn):
    url = "https://www.harptabs.com/tab/23862/piano-man-c-harmonica"
    response = lookup(app, {"artist": "billy joel", "title": "Piano Man", "harptabs": url})
    assert response.status == 202
    [job] = queue.snapshot()
    assert job.steps[0].args == ("get", "--progress", f"--harptabs={url}", "--", "billy joel", "Piano Man")
    assert lookup(app, {"artist": "Billy Joel", "title": "Piano Man",
                        "harptabs": "https://www.harptabs.com/artist/1178/billy-joel"}).status == 400


def test_a_song_of_yours_in_the_search_says_what_it_holds_for_one_instrument(app, cfg, conn):
    from caracole.library import keep_file
    from caracole.versions import upsert_version

    creep_index(conn)
    mine = add_song(conn, "Radiohead", "Creep")
    tab = upsert_version(conn, provider="harptabs", tab_id="3", song_id=mine.id, slot="guitar", kind="harmonica",
                         rating=0, votes=0, version=1, label=None, url="https://www.harptabs.com/tab/3/creep", raw={},
                         now="2026-10-19T00:00:00Z")
    keep_file(conn, cfg.library_dir, song=mine, version_id=tab, name="harmonica-1.txt", data=b"4 5\n", rank=1)
    conn.commit()
    [song] = as_json(get(app, "/api/search?q=radiohead%20creep"))["library"]
    assert song["instruments"] == ["harmonica"]


def test_every_search_row_carries_its_artist_and_title_keys(app, conn):
    from caracole.normalize import identity_key
    from caracole.ug.index import mark_built, upsert_rows

    upsert_rows(conn, [(77, "estopa", "como-camaron", "chords", "estopa/como-camaron-chords-77")], "1",
                datetime(2026, 10, 19, tzinfo=UTC))
    mark_built(conn, datetime(2026, 10, 19, tzinfo=UTC))
    lacuerda_index(conn)
    site_pages(conn, gtptabs=["https://gtptabs.com/tabs/31/estopa/como-camaron.html"])
    data = as_json(get(app, "/api/search?q=estopa%20como%20camaron"))
    want = identity_key("Estopa", "Como Camarón").split("/")
    [ug] = [h for h in data["index"] if h["ug"] == "estopa/como-camaron"]
    [lc] = [h for h in data["lacuerda"] if h["title"] == "Como Camarón"]
    [gtp] = data["gtptabs"]
    for row in (ug, lc, gtp):
        assert [row["artist_key"], row["title_key"]] == want
    assert [lc["artist_key"], lc["title_key"]] == [ug["artist_key"], ug["title_key"]]


def test_an_artist_the_search_names_and_their_songs_carry_the_keys_of_their_group(app, conn):
    # The library page puts an artist and their songs from every site under one header: the artist's ``group_key``
    # is the artist key of their songs' rows, and their most tabbed songs come as the index's songs do, with their
    # versions, their keys and the song of yours each is.
    from caracole.normalize import identity_key
    from caracole.ug.index import mark_built, upsert_rows

    upsert_rows(conn, [(77, "estopa", "como-camaron", "chords", "estopa/como-camaron-chords-77"),
                       (78, "estopa", "tu-calorro", "chords", "estopa/tu-calorro-chords-78")], "1",
                datetime(2026, 10, 19, tzinfo=UTC))
    mark_built(conn, datetime(2026, 10, 19, tzinfo=UTC))
    lacuerda_index(conn)
    mine = add_song(conn, "Estopa", "Como Camarón")
    data = as_json(get(app, "/api/search?q=estopa"))
    group, title = identity_key("Estopa", "Como Camarón").split("/")
    [ug], [lc] = data["artists"], data["lacuerda_artists"]
    assert ug["group_key"] == lc["group_key"] == group
    tops = {t["ug"]: t for t in ug["top"]}
    camaron = tops["estopa/como-camaron"]
    assert [camaron["artist_key"], camaron["title_key"], camaron["song"]] == [group, title, mine.id]
    assert camaron["tabs"][0]["id"] == 77 and camaron["counts"] == {"chords": 1}
    assert camaron["library"]["id"] == mine.id and tops["estopa/tu-calorro"]["song"] is None
    [lc_top] = lc["top"]
    assert [lc_top["artist_key"], lc_top["title_key"], lc_top["song"]] == [group, title, mine.id]
    assert lc_top["sheet"] == LC + "estopa/como_camaron-2.shtml" and lc_top["versions"] == 3
    assert as_json(get(app, "/api/artist?lacuerda=estopa"))["group_key"] == group


def test_an_artist_the_search_names_says_how_many_songs_gtptabs_com_lists_of_theirs(app, cfg, conn):
    # Their group's header on the library page: "Estopa · UG 2 · LaCuerda 159 · Guitar Pro 2", a title's uploads one
    # song; none while gtptabs.com is turned off.
    import dataclasses

    from caracole.config import ProviderPolicy
    from caracole.ug.index import mark_built, upsert_rows

    upsert_rows(conn, [(77, "estopa", "como-camaron", "chords", "estopa/como-camaron-chords-77"),
                       (78, "estopa", "tu-calorro", "chords", "estopa/tu-calorro-chords-78")], "1",
                datetime(2026, 10, 19, tzinfo=UTC))
    mark_built(conn, datetime(2026, 10, 19, tzinfo=UTC))
    lacuerda_index(conn)
    gtp = "https://gtptabs.com/tabs/31/"
    site_pages(conn, gtptabs=[gtp + "estopa/como-camaron.html", gtp + "estopa/como-camaron-2.html",
                              gtp + "estopa/la-raja-de-tu-falda.html", gtp + "estopa.html",
                              gtp + "estopa-y-amigos/vino-tinto.html"])
    data = as_json(get(app, "/api/search?q=estopa"))
    [ug], [lc] = data["artists"], data["lacuerda_artists"]
    assert ug["gtptabs"] == lc["gtptabs"] == 2
    assert as_json(get(app, "/api/artist?lacuerda=estopa"))["gtptabs"] == 2
    assert as_json(get(app, "/api/search?q=joaquin%20sabina"))["lacuerda_artists"][0]["gtptabs"] == 0
    off = dataclasses.replace(cfg, providers={**cfg.providers, "gtptabs": ProviderPolicy(20, (10.0, 20.0), False)})
    app_off = WebApp(off, JobQueue(Recorder()), allowed=ALLOWED, csrf="tok")
    data = as_json(get(app_off, "/api/search?q=estopa"))
    assert data["artists"][0]["gtptabs"] == data["lacuerda_artists"][0]["gtptabs"] == 0
    assert as_json(get(app_off, "/api/artist?lacuerda=estopa"))["gtptabs"] == 0


def test_a_row_of_a_song_of_yours_says_whether_its_artist_is_yours_by_name(app, conn):
    # The library page puts the rows of an artist under your artist's header only when they name the same artist (UG's
    # "Acdc" is your AC/DC): your cover matched to the original's tab is your song, not its artist yours.
    from caracole.ug.index import mark_built, upsert_rows

    rows = [(11, "oasis", "wonderwall", "chords"), (12, "oasis", "live-forever", "chords"), (21, "acdc", "thunderstruck", "chords")]
    upsert_rows(conn, [(t, a, s, k, f"{a}/{s}-{k}-{t}") for t, a, s, k in rows], "1", datetime(2026, 10, 19, tzinfo=UTC))
    mark_built(conn, datetime(2026, 10, 19, tzinfo=UTC))
    cover = add_song(conn, "Ryan Adams", "Wonderwall")
    update_song(conn, cover.id, match_decision="accept", match_artist_key="oasis", match_song_key="wonderwall")
    acdc = add_song(conn, "AC/DC", "Thunderstruck")
    [wonderwall] = [h for h in as_json(get(app, "/api/search?q=wonderwall"))["index"] if h["ug"] == "oasis/wonderwall"]
    assert (wonderwall["song"], wonderwall["same_artist"]) == (cover.id, False)
    [thunder] = [h for h in as_json(get(app, "/api/search?q=thunderstruck"))["index"] if h["ug"] == "acdc/thunderstruck"]
    assert (thunder["song"], thunder["same_artist"]) == (acdc.id, True)
    [live] = [h for h in as_json(get(app, "/api/search?q=live%20forever"))["index"] if h["ug"] == "oasis/live-forever"]
    assert (live["song"], live["same_artist"]) == (None, False)


def test_the_search_carries_the_removed_songs_that_match_never_as_yours_nor_best(app, conn):
    from caracole.songs import mark_removed

    creep_index(conn)
    gone = add_song(conn, "宋冬野", "斑马斑马")
    mark_removed(conn, gone, "2026-10-20T09:00:00+00:00")
    conn.execute("DELETE FROM songs WHERE id = ?", (gone.id,))
    artist_key, title_key = gone.key.split("/")
    for q in ("斑马", "斑马斑马", "banma"):
        data = as_json(get(app, "/api/search?q=" + quote(q)))
        assert data["removed"] == [{"artist": "宋冬野", "title": "斑马斑马", "key": gone.key,
                                    "removed_at": "2026-10-20T09:00:00+00:00", "artist_key": artist_key,
                                    "title_key": title_key}], q
        assert data["library"] == [] and data["best"] is None, q
    assert as_json(get(app, "/api/search?q=creep"))["removed"] == []


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
    looked = {s["source"]: (s["state"], s["label"]) for s in data["looked"]}
    assert looked["gtptabs"] == ("off", "gtptabs.com: off") and looked["musescore"] == ("off", "MuseScore: off")


def test_the_search_says_where_it_looked_a_chip_a_site_with_its_detail(app, conn):
    from caracole.health import record_block

    creep_index(conn)
    site_pages(conn, gtptabs=["https://gtptabs.com/tabs/18/radiohead/creep.html"])
    lacuerda_index(conn, letters=("_num", "a", "b", "c"))
    record_block(conn, "musescore", datetime(2026, 10, 19, tzinfo=UTC), "HTTP 403: a challenge")
    looked = as_json(get(app, "/api/search?q=lynrd"))["looked"]
    # UG, gtptabs.com, LaCuerda, MuseScore, harptabs.com: done, done, partial (the letters read whole run up to C),
    # blocked, empty.
    assert [(s["source"], s["state"], s["label"]) for s in looked] == [
        ("ug", "done", "UG ✓"), ("gtptabs", "done", "gtptabs.com ✓"), ("lacuerda", "partial", "LaCuerda: up to C"),
        ("musescore", "blocked", "MuseScore blocked"), ("harptabs", "empty", "harptabs.com: empty")]
    detail = {s["source"]: s["detail"] for s in looked}
    assert detail["lacuerda"] == ("LaCuerda's index is still being read: 2 artists so far, with #, A–C read whole; "
                                  "the nightly run reads the rest.")
    assert detail["musescore"] == "MuseScore is blocking caracole, so its index is empty."
    assert all("\n" not in d and d for d in detail.values())  # one line each, for a tooltip
    # Letters read that don't run from the start, an empty index, and one read whole.
    from caracole import lacuerda_index as li
    from caracole.db import kv_set, kv_set_json

    kv_set_json(conn, li.PAGES_KEY, {f"tabs/{x}/index0.html": {"pages": ["index0.html"]} for x in ("e", "j")})
    conn.commit()
    lc = {s["source"]: s for s in as_json(get(app, "/api/search?q=lynrdx"))["looked"]}["lacuerda"]
    assert (lc["state"], lc["label"]) == ("partial", "LaCuerda: E, J only")
    kv_set(conn, li.COMPLETE_KEY, "2026-10-19T00:00:00+00:00")
    conn.commit()
    lc = {s["source"]: s for s in as_json(get(app, "/api/search?q=lynrdy"))["looked"]}["lacuerda"]
    assert (lc["state"], lc["label"]) == ("done", "LaCuerda ✓")


def test_the_search_says_a_site_whose_index_is_empty_is_empty(app, conn):
    looked = {s["source"]: (s["state"], s["label"]) for s in as_json(get(app, "/api/search?q=creep"))["looked"]}
    assert looked == {"ug": ("empty", "UG: empty"), "gtptabs": ("empty", "gtptabs.com: empty"),
                      "lacuerda": ("empty", "LaCuerda: empty"), "musescore": ("empty", "MuseScore: empty"),
                      "harptabs": ("empty", "harptabs.com: empty")}


def test_a_search_the_ug_index_answers_badly_says_what_to_paste_for_an_artist_it_cant_see(app, conn):
    creep_index(conn)
    data = as_json(get(app, "/api/search?q=%E5%AE%8B%E5%86%AC%E9%87%8E"))  # 宋冬野
    assert data["unseen"] == {"strong": False, "entry": '[artist_url]\n"宋冬野" = "https://www.ultimate-guitar.com/artist/…"',
                              "add": 'caracole add ARTIST "宋冬野"'}
    assert as_json(get(app, "/api/search?q=radiohead%20creep"))["unseen"] is None


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
    assert {k: v for k, v in estopa.items() if k != "top"} == {
        "source": "lacuerda", "artist": "Estopa", "slug": "estopa", "url": LC + "estopa/", "songs": 159, "known": 2,
        "score": 100.0, "via": "artist", "group_key": "estopa", "gtptabs": 0}
    assert [{k: t[k] for k in ("title", "url", "sheet", "song")} for t in estopa["top"]] == [
        {"title": "Como Camarón", "url": LC + "estopa/como_camaron", "sheet": LC + "estopa/como_camaron-2.shtml",
         "song": mine.id}]
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


def test_ask_lacuerda_offers_the_artist_part_of_a_query_never_a_name_ultimate_guitar_only_holds_its_words_of(app,
                                                                                                          conn):
    from caracole.ug.index import mark_built, upsert_rows

    lacuerda_index(conn)  # E and J read whole
    when = datetime(2026, 10, 19, tzinfo=UTC)
    upsert_rows(conn, [(3401, "till-lindemann", "entre-dos-tierras", "chords", "till-lindemann/entre-dos-tierras-3401"),
                       (3402, "ana-gabriel", "rayando-el-sol", "chords", "ana-gabriel/rayando-el-sol-chords-3402"),
                       (3403, "silvio-martinez-rodriguez", "la-era", "chords",
                        "silvio-martinez-rodriguez/la-era-chords-3403"),
                       (3404, "vic-ruggiero", "sabina", "chords", "vic-ruggiero/sabina-chords-3404")], "1", when)
    mark_built(conn, when)
    conn.commit()

    def unlisted(q):
        return as_json(get(app, "/api/search?q=" + quote(q)))["lacuerda_unlisted"]

    # A title an index knows ends the query: the rest is the artist, as typed.
    assert unlisted("héroes del silencio entre dos tierras") == {"name": "héroes del silencio", "letter": "H"}
    assert unlisted("mana rayando el sol") == {"name": "mana", "letter": "M"}
    # A title of one word is no proof: "sabina" is a title, and "joaquin sabina" a name all the same.
    from caracole.db import kv_set_json
    from caracole import lacuerda_index as li

    kv_set_json(conn, li.PAGES_KEY, {"tabs/e/index0.html": {"pages": ["index0.html"]}})  # J no longer read whole
    conn.commit()
    assert unlisted("joaquin sabina") is None  # LaCuerda lists them: Joaquín Sabina's J read in part
    li.store_artists(conn, "tabs/j/index0.html", [])
    conn.commit()
    assert unlisted("joaquín sabina") == {"name": "joaquín sabina", "letter": "J"}  # an answer not kept yet
    # An artist on Ultimate Guitar whose name puts another word between the query's is someone else.
    assert unlisted("silvio rodriguez") == {"name": "silvio rodriguez", "letter": "S"}


def test_ask_lacuerda_never_offers_an_artist_lacuerda_lists_under_another_name(app, conn):
    from caracole import lacuerda_index as li
    from caracole.lacuerda import LCArtist
    from caracole.ug.index import mark_built, upsert_rows

    lacuerda_index(conn)  # E and J read whole; F and M in part
    li.store_artists(conn, "tabs/f/index0.html", [LCArtist("fito__fitipaldis", "Fito & Fitipaldis", 77)])
    li.store_artists(conn, "tabs/c/index0.html", [LCArtist("chao", "Chao", 1)])
    li.store_artists(conn, "tabs/e/index0.html", [LCArtist("estopa", "Estopa", 159),
                                                  LCArtist("enanitos", "Enanitos Verdes", 151)])
    when = datetime(2026, 10, 19, tzinfo=UTC)
    upsert_rows(conn, [(3501, "los-enanitos-verdes", "lamento-boliviano", "chords",
                        "los-enanitos-verdes/lamento-boliviano-chords-3501"),
                       (3502, "fito-fitipaldis", "por-la-boca-vive-el-pez", "chords",
                        "fito-fitipaldis/por-la-boca-vive-el-pez-chords-3502"),
                       (3503, "manu-chao", "me-gustas-tu", "chords", "manu-chao/me-gustas-tu-chords-3503")], "1", when)
    mark_built(conn, when)
    conn.commit()

    def unlisted(q):
        return as_json(get(app, "/api/search?q=" + quote(q)))["lacuerda_unlisted"]

    # Ultimate Guitar's "Los Enanitos Verdes" and "Fito Fitipaldis" are LaCuerda's Enanitos Verdes and Fito &
    # Fitipaldis, whom its listings name: no page to read under L, nor under F.
    assert unlisted("enanitos verdes lamento boliviano") is None
    assert unlisted("fito & fitipaldis por la boca vive el pez") is None
    # LaCuerda's Chao is no Manu Chao: Ultimate Guitar's artist is still the name to read.
    assert unlisted("manu chao me gustas tu") == {"name": "Manu Chao", "letter": "M"}


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


def test_when_lacuerda_leads_ultimate_guitars_artist_a_word_names_leads_nothing(app, conn):
    # "calamaro": Javier Calamaro's songs on Ultimate Guitar, Andrés Calamaro's many more on LaCuerda.
    from caracole import lacuerda_index as li
    from caracole.lacuerda import LCArtist
    from caracole.search import MOST_SONGS
    from caracole.ug.index import mark_built, upsert_rows

    when = datetime(2026, 10, 19, tzinfo=UTC)
    upsert_rows(conn, [(3300 + i, "javier-calamaro", f"song-{i}", "chords", f"javier-calamaro/song-{i}-chords-{3300 + i}")
                       for i in range(MOST_SONGS)], "1", when)
    mark_built(conn, when)
    lacuerda_index(conn)
    li.store_artists(conn, "tabs/a/index0.html", [LCArtist("andres_calamaro", "Andrés Calamaro", 325)])
    conn.commit()
    data = as_json(get(app, "/api/search?q=calamaro"))
    assert [a["artist"] for a in data["artists"]] == ["Javier Calamaro"]
    assert [a["artist"] for a in data["lacuerda_artists"]] == ["Andrés Calamaro"]
    # LaCuerda's group first, and Enter opens Andrés Calamaro's songs: Ultimate Guitar's artist leads nothing.
    assert (data["lacuerda_leads"], data["lead"], data["best"]) == (True, "song", None)


def test_api_search_looks_for_no_close_spelling_when_a_song_of_yours_is_the_query(app, conn, monkeypatch):
    def no(*args, **kwargs):
        raise AssertionError("no suggestion is looked for")

    by_word_index(conn)
    add_song(conn, "Someone", "Lynrd")
    monkeypatch.setattr("caracole.search.suggest_artists", no)
    data = as_json(get(app, "/api/search?q=lynrd"))
    assert data["suggest"] == [] and data["library"]


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


def test_a_search_asks_no_site_and_takes_no_lock(app, conn, queue, monkeypatch):
    # /api/search reads the local indexes alone: it says whether LaCuerda's own search would be sent, and sends
    # nothing; that search is a job of its own (POST /lacuerda/search), which the page sends once a query settles.
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
    lacuerda_index(conn)  # LaCuerda's index answers, and its artists' songs
    data = as_json(get(app, "/api/search?q=joaquin%20sabina"))
    assert data["lacuerda_artists"] and data["lacuerda_search"]["state"] == "auto"
    assert as_json(get(app, "/api/artist?lacuerda=estopa"))["songs"]
    assert queue.snapshot() == []  # nothing queued either: the page asks for the search, the route queues it


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
    # A song whose line you took off wanted.txt stays in the library, and stays off wanted.txt.
    creep = add_song(conn, "Radiohead", "Creep")
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


@pytest.mark.parametrize("boxes,typed_over", [(("a", "b"), False), (("a", "a"), True)])
def test_a_search_is_typed_over_only_by_its_own_box_never_by_another_pages(app, conn, monkeypatch, boxes,
                                                                             typed_over):
    # Two people search at once, each on their phone (a box each: the id its page sends): the second waits for the
    # first, which reads to its end, then reads; both are answered, and neither page has to ask again. A search
    # typed on in the same box stops the older one there at once, as ever.
    import itertools
    import threading

    import caracole.search

    creep_index(conn)
    started, second = threading.Event(), threading.Event()
    real = caracole.search.find_index
    tickets = itertools.count(1)

    class Tickets:  # the server's: says when the second search has drawn its own
        def __iter__(self):
            return self

        def __next__(self):
            n = next(tickets)
            if n == 2:
                second.set()
            return n

    def find_index(c, query, **kwargs):
        if query == "slow words":
            started.set()
            assert second.wait(10)
            # Read on, SQLite looking for a newer search every few thousand steps: none of its own box comes.
            c.execute("WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 300000) "
                      "SELECT count(*) FROM n").fetchone()
        return real(c, query, **kwargs)

    monkeypatch.setattr(app, "_tickets", Tickets())
    monkeypatch.setattr(caracole.search, "find_index", find_index)
    first: dict = {}
    other: dict = {}
    one = threading.Thread(target=lambda: first.update(as_json(get(app, f"/api/search?q=slow%20words&box={boxes[0]}"))),
                           daemon=True)
    one.start()
    assert started.wait(10)
    two = threading.Thread(target=lambda: other.update(as_json(get(app, f"/api/search?q=creep&box={boxes[1]}"))),
                           daemon=True)
    two.start()
    one.join(10)
    two.join(10)
    assert not one.is_alive() and not two.is_alive()
    assert other["index"][0]["ug"] == "radiohead/creep"
    if typed_over:
        assert first == {"query": "slow words", "superseded": True}
    else:
        assert "superseded" not in first and first["query"] == "slow words" and "index" in first


def test_a_box_id_that_isnt_one_is_no_box():
    from caracole.web.search_routes import search_box

    assert search_box({"box": ["k3j9-x_Q"]}) == "k3j9-x_Q"
    assert search_box({}) == search_box({"box": [""]}) == search_box({"box": ["a b"]}) == ""
    assert search_box({"box": ["x" * 65]}) == "" and search_box({"box": ["é"]}) == ""


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
    # No song of the library's in that folder: the file is named as it is.
    assert header(download, "content-disposition") == "attachment; filename=\"guitar-1.gp5\"; filename*=UTF-8''guitar-1.gp5"


def test_a_guitar_pro_file_is_downloaded_under_its_songs_name(app, conn, cfg):
    from urllib.parse import unquote

    names = {}
    for artist, title in (("Joaquín Sabina", "19 Días y 500 Noches"), ("宋冬野", "斑马，斑马")):
        song = add_song(conn, artist, title)
        folder = song_dir(cfg.library_dir, song)
        folder.mkdir(parents=True)
        for name in ("guitar-1.gp5", "guitar-2.ptb"):
            (folder / name).write_bytes(b"gp")
        relative = folder.relative_to(cfg.library_dir)
        for name in ("guitar-1.gp5", "guitar-2.ptb"):
            said = header(get(app, "/" + quote(f"{relative.as_posix()}/{name}")), "content-disposition")
            assert said.startswith('attachment; filename="') and said.isascii()
            names[(artist, name)] = (said.split('filename="', 1)[1].split('"', 1)[0],
                                     unquote(said.split("filename*=UTF-8''", 1)[1]))
    assert names[("Joaquín Sabina", "guitar-1.gp5")] == ("Joaquin Sabina - 19 Dias y 500 Noches.gp5",
                                                         "Joaquín Sabina - 19 Días y 500 Noches.gp5")
    assert names[("Joaquín Sabina", "guitar-2.ptb")][1] == "Joaquín Sabina - 19 Días y 500 Noches (2).ptb"
    assert names[("宋冬野", "guitar-1.gp5")][1] == "宋冬野 - 斑马，斑马.gp5"
    assert names[("宋冬野", "guitar-2.ptb")][1] == "宋冬野 - 斑马，斑马 (2).ptb"


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
        assert policies == [f"sandbox allow-scripts allow-downloads; {own}; frame-ancestors 'none'"]  # a sandbox, no framing
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
    scripts = re.findall(r"<script>(.*?)</script>", sent, re.S)
    assert f"script-src {' '.join(map(sha256_source, scripts))};" in policy
    assert f"style-src {sha256_source(re.search(r'<style>(.*?)</style>', sent, re.S).group(1))};" in policy
    assert policy.startswith("sandbox allow-scripts allow-downloads; default-src 'none'; ")
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


def test_the_database_is_never_served(app, cfg, conn):
    add_song(conn, "Radiohead", "Creep")
    (cfg.library_dir).mkdir(parents=True, exist_ok=True)
    (cfg.library_dir / "Evil").symlink_to(cfg.state_dir, target_is_directory=True)
    for path in ("/Evil/caracole.sqlite", "/../state/caracole.sqlite", "/%2e%2e/state/caracole.sqlite",
                 "/state/caracole.sqlite", "/caracole.sqlite"):
        assert get(app, path).status == 404, path


# --- no sign-in -----------------------------------------------------------------------------------


def test_there_is_no_sign_in_every_page_goes_to_whoever_reaches_the_server(app, conn):
    # caracole serve is for a network you trust: no access token, no cookie, no sign-in page.
    add_song(conn, "Radiohead", "Creep")
    response = get(app, "/")
    assert response.status == 200 and "Radiohead - Creep" in text(response)
    assert header(response, "set-cookie") is None
    assert get(app, "/login").status == 404
    assert post(app, "/login", {"token": "a-long-random-access-token"}).status == 404


def test_the_router_answers_the_routes_of_each_route_module_and_each_lists_its_own():
    # A route is a Route in its module's ROUTES and a line of its docstring: app.py gathers them, so a new
    # route, or a new module of them, changes nothing there. No address is answered twice.
    import importlib
    import pkgutil

    from caracole import web
    from caracole.web.app import route_for, routes

    names = sorted(m.name for m in pkgutil.iter_modules(web.__path__) if m.name.endswith("_routes"))
    assert names == ["export_routes", "guitar_routes", "jobs_routes", "library_routes", "offline_routes",
                     "remove_routes", "review_routes", "search_routes", "songbook_routes", "versions_routes"]
    gathered = []
    for name in names:
        module = importlib.import_module(f"caracole.web.{name}")
        # "GET  /, /index.html   what it is": each address the line starts with, to its "?" or "[".
        listed = [(method, address.split("?")[0].split("[")[0])
                  for method, addresses in re.findall(r"^\s*(GET|POST)\s+(/[^\s,]*(?:,\s*/[^\s,]*)*)", module.__doc__, re.M)
                  for address in re.split(r",\s*", addresses)]
        for route in module.ROUTES:
            gathered.append((route.method, route.path))
            path = route.path.rstrip("/") or "/"
            assert any(method == route.method and (address == path or (address.endswith("…")
                       and path.startswith(address[:-1]))) for method, address in listed), (name, route.path)
    assert sorted(gathered) == sorted(routes()) and len(set(gathered)) == len(gathered)
    assert route_for("GET", "/api/jobs/7").path == "/api/jobs/"  # under its address
    assert route_for("GET", "/api/jobsx") is None and route_for("POST", "/songbook/nothing") is None
    assert route_for("POST", "/songbook/make").page == "the library"
    assert route_for("POST", "/lookup").page == "the page" and route_for("GET", "/jobs.json").script_only
    assert route_for("GET", "/export.pdf").path == "/export.pdf" and route_for("POST", "/export") is None


# --- LaCuerda's own search -------------------------------------------------------------------------------


def lacuerda_events(conn, run_name, n):
    conn.executemany("INSERT INTO events (run, at, provider, url, decision) VALUES (?, ?, 'lacuerda', 'x', 'ok')",
                     [(run_name, datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))] * n)
    conn.commit()


def test_the_search_says_whether_lacuerdas_search_would_be_sent(app, conn):
    from caracole.db import kv_set_json
    from caracole.health import record_block

    lacuerda_index(conn)

    def said(q):
        return as_json(get(app, "/api/search?q=" + quote(q)))["lacuerda_search"]

    # A query with a word LaCuerda's search reads, whose song its index lacks: the page sends it by itself.
    assert said("Corazón de tiza") == {"state": "auto", "query": "Corazón de tiza", "key": "corazon-tiza"}
    assert said("el sol y tu") is None  # no word of four letters: LaCuerda's search reads none
    assert said("como camaron") is None  # LaCuerda's index has the song, strong
    assert said("estopa") is None  # and the artist the query names, whose page caracole read: all their songs
    assert said("joaquin sabina")["state"] == "auto"  # their page not read: the search brings some
    # Letters inside a word are no strong song: "mana" of "Mañana Clara" leaves Maná to LaCuerda's search.
    from helpers.lacuerda_site import artist_page

    from caracole import lacuerda_index as li

    li.store_artist_page(conn, "estopa", artist_page("Estopa", "estopa", ("manana_clara", "Mañana Clara", "R-1")))
    conn.commit()
    assert said("maná")["state"] == "auto"
    # Asked within 30 days: it answered, and the index holds it.
    kv_set_json(conn, "lacuerda:search:corazon-tiza", {"at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                        "songs": 2, "artists": 0, "stated": 2})
    conn.commit()
    assert said("corazon tiza")["state"] == "asked"
    # The page's own share of the hour's lookups spent: a button, which asks by hand, within the hour's lookups.
    lacuerda_events(conn, "lookup:lacuerda-search:x", 20)
    assert said("corazon de papel")["state"] == "button"
    lacuerda_events(conn, "lookup:x", 40)  # the hour's 60 lookup requests to LaCuerda
    assert said("corazon de papel")["state"] == "spent"
    conn.execute("DELETE FROM events")
    record_block(conn, "lacuerda", datetime.now(UTC), "HTTP 403")
    conn.commit()
    assert said("corazon de papel")["state"] == "spent"


class Searcher:
    """The queue's caracole: ``lacuerda --search`` as the command takes an answer in, with no request."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.calls = []

    def __call__(self, args, emit):
        from helpers.lacuerda_site import search_page

        from caracole import db
        from caracole.lacuerda import parse_search
        from caracole.lacuerda_index import store_search

        self.calls.append(tuple(args))
        c = db.connect(self.cfg.db_path)
        try:
            store_search(c, parse_search(search_page(
                ("imaginarios", "Los Imaginarios", [("corazon_de_tiza", "Corazón de Tiza", "RT-12")]))))
            c.commit()
        finally:
            c.close()
        emit("Searched: LaCuerda has 1 song for “corazon de tiza”, in the index now.")
        return 0


def test_lacuerdas_search_is_one_command_in_the_queue_and_its_rows_are_searched_at_once(cfg, conn):
    lacuerda_index(conn)
    runner = Searcher(cfg)
    queue = JobQueue(runner)
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
    assert as_json(get(app, "/api/search?q=corazon%20de%20tiza"))["lacuerda"] == []  # an answer kept a few minutes
    response = post(app, "/lacuerda/search", {"q": "  corazon de  tiza "}, accept="application/json")
    assert response.status == 202
    data = as_json(response)
    assert data["url"] == f"/api/jobs/{data['job']}"
    [job] = queue.snapshot()
    assert [s.args for s in job.steps] == [("lacuerda", "--search=corazon de tiza", "--progress", "--auto")]
    assert job.song_key == "lacuerda-search:corazon-tiza" and job.display == "“corazon de tiza” on LaCuerda"
    assert [s.name for s in job.stages] == ["search"]
    # Asked again, under any spelling LaCuerda reads the same, or by hand: that job.
    for fields in ({"q": "corazon tiza"}, {"q": "corazón de tiza", "by_hand": "1"}):
        assert as_json(post(app, "/lacuerda/search", fields, accept="application/json"))["job"] == data["job"]
    assert len(queue.snapshot()) == 1
    assert post(app, "/lacuerda/search", {"q": "corazon de tiza"}, csrf="old").status == 403
    queue.run_pending()
    after = as_json(get(app, "/api/search?q=corazon%20de%20tiza"))  # the search is over: no answer kept from before
    assert [(h["artist"], h["title"]) for h in after["lacuerda"]] == [("Los Imaginarios", "Corazón de Tiza")]
    assert as_json(get(app, data["url"]))["line"] == {
        "tone": "added", "text": "Searched: LaCuerda has 1 song for “corazon de tiza”, in the index now.",
        "link": None, "details": None}
    line = as_json(get_json(app, "/jobs.json"))["jobs"][0]["line"]
    assert line["text"].startswith("Searched: ")
    # Try again on the requests page is asked by hand: past the share of the searches the page sends by itself.
    assert post(app, "/jobs/again", {"job": str(data["job"])}).status == 303
    assert queue.snapshot()[0].steps[0].args == ("lacuerda", "--search=corazon de tiza", "--progress")


def test_lacuerdas_search_route_refuses_what_its_gates_refuse(app, conn, queue):
    from caracole.db import kv_set_json

    lacuerda_index(conn)

    def refused(fields):
        response = post(app, "/lacuerda/search", fields, accept="application/json")
        return response.status, as_json(response).get("error", "")

    assert refused({"q": "el sol"})[0] == 400  # no word LaCuerda reads
    assert refused({"q": ""})[0] == 400 and refused({"q": "x" * 201})[0] == 400
    assert refused({"q": "como camaron"})[0] == 409  # its index has the song
    kv_set_json(conn, "lacuerda:search:corazon-tiza", {"at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                        "songs": 2, "artists": 0, "stated": 2})
    conn.commit()
    status, error = refused({"q": "corazon de tiza"})
    assert status == 409 and "within 30 days" in error
    lacuerda_events(conn, "lookup:lacuerda-search:x", 20)
    status, error = refused({"q": "corazon de papel"})  # the page's share spent: not by itself
    assert status == 429 and "press Ask LaCuerda" in error
    assert queue.snapshot() == []
    response = post(app, "/lacuerda/search", {"q": "corazon de papel", "by_hand": "1"}, accept="application/json")
    assert response.status == 202  # by hand, the button: within the hour's lookups
    [job] = queue.snapshot()
    assert job.steps[0].args == ("lacuerda", "--search=corazon de papel", "--progress")
    lacuerda_events(conn, "lookup:x", 40)
    assert refused({"q": "corazon de cristal", "by_hand": "1"})[0] == 429


def test_a_search_that_failed_lately_is_offered_by_hand_and_never_sent_by_the_page(app, conn, queue):
    from datetime import timedelta

    from caracole.lacuerda_search import record_failure

    lacuerda_index(conn)
    now = datetime.now(UTC)
    record_failure(conn, "corazon-tiza", now - timedelta(minutes=3), "LaCuerda failed: HTTP 500")
    conn.commit()

    def said(q):
        return as_json(get(app, "/api/search?q=" + quote(q)))["lacuerda_search"]

    # Its words in any order are one query, as LaCuerda's search reads them.
    tiza = said("tiza corazón")
    assert (tiza["state"], tiza["key"], tiza["query"]) == ("failed", "corazon-tiza", "tiza corazón")
    assert tiza["why"].startswith("LaCuerda's search for “tiza corazón” failed less than an hour ago "
                                  "(LaCuerda failed: HTTP 500), so the page won't send it by itself before ")
    response = post(app, "/lacuerda/search", {"q": "corazon de tiza"}, accept="application/json")
    assert response.status == 429 and "press Ask LaCuerda" in as_json(response)["error"]
    assert queue.snapshot() == []
    response = post(app, "/lacuerda/search", {"q": "corazon de tiza", "by_hand": "1"}, accept="application/json")
    assert response.status == 202  # by hand: a person asks
    # Three failed in the last hour: the page sends no query by itself, and offers each by hand.
    record_failure(conn, "corazon-papel", now - timedelta(minutes=2), "LaCuerda failed: HTTP 502")
    record_failure(conn, "cristal", now - timedelta(minutes=1), "LaCuerda failed: cut short")
    conn.commit()
    miel = said("luna de miel")
    assert miel["state"] == "failed" and miel["why"].startswith(
        "3 searches of LaCuerda failed in the last hour (the last: LaCuerda failed: cut short), so the page sends "
        "none by itself before ")
    # An hour on, they are forgotten.
    from caracole.db import kv_get_json, kv_set_json

    old = (now - timedelta(minutes=61)).strftime("%Y-%m-%dT%H:%M:%SZ")
    kv_set_json(conn, "lacuerda:search-failed", {k: {**v, "at": old}
                                                 for k, v in kv_get_json(conn, "lacuerda:search-failed").items()})
    conn.commit()
    assert said("luna de miel") == {"state": "auto", "query": "luna de miel", "key": "luna-miel"}


def test_a_query_your_library_answers_well_sends_no_lacuerda_search(app, conn, queue):
    lacuerda_index(conn)
    add_song(conn, "Oasis", "Wonderwall")
    for q in ("oasis", "oasis wonderwall", "wonderwall"):  # your songs, by their artist or their title
        assert as_json(get(app, "/api/search?q=" + quote(q)))["lacuerda_search"] is None, q
    response = post(app, "/lacuerda/search", {"q": "oasis", "by_hand": "1"}, accept="application/json")
    assert response.status == 409 and queue.snapshot() == []
    assert as_json(get(app, "/api/search?q=" + quote("oasis live forever")))["lacuerda_search"]["state"] == "auto"


def test_an_artist_whose_songs_came_from_a_search_alone_still_offers_to_read_their_page(app, conn):
    from helpers.lacuerda_site import search_page

    from caracole.lacuerda import parse_search
    from caracole.lacuerda_index import store_search

    lacuerda_index(conn)
    store_search(conn, parse_search(search_page(
        ("joaquin_sabina", "Joaquín Sabina", [("y_nos_dieron_las_diez", "Y Nos Dieron Las Diez", "R-1")]))))
    conn.commit()
    [sabina] = as_json(get(app, "/api/search?q=joaquin%20sabina"))["lacuerda_artists"]
    assert (sabina["known"], [t["title"] for t in sabina["top"]]) == (0, ["Y Nos Dieron Las Diez"])
    page = as_json(get(app, "/api/artist?lacuerda=joaquin_sabina"))
    assert (page["read"], page["listed"], [h["title"] for h in page["songs"]]) == (False, 241, ["Y Nos Dieron Las Diez"])
    [song] = as_json(get(app, "/api/search?q=y%20nos%20dieron%20las%20diez"))["lacuerda"]
    assert (song["artist"], song["sheet"]) == ("Joaquín Sabina", LC + "joaquin_sabina/y_nos_dieron_las_diez.shtml")
