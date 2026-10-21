"""caracole serve's songbooks: the forms that queue caracole songbook, and songbook.html, served only
while it is the page caracole wrote."""

from __future__ import annotations

import json
import re
import shutil
import struct
import threading
from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest
from conftest import add_song
from helpers import browser
from helpers.browser import in_chromium
from helpers.songbooks import FakeChordPro, fake_chordpro_program, keep_sheet, render_sheets
from typer.testing import CliRunner

from caracole import db
from caracole.cli import build_app
from caracole.config import load_config
from caracole.overrides import Overrides
from caracole.songbook import FILE_NAME, Songbook, load_songbooks, make_songbook, render_songbooks
from caracole.viewer.book import songbook_csp
from caracole.web.app import Request, WebApp
from caracole.web.jobs import JobQueue

HOST = "127.0.0.1:8737"
ALLOWED = frozenset({"localhost", "127.0.0.1", "::1"})
PAGE = "/_songbooks/Campfire/songbook.html"


class InProcess:
    """Runs each step's caracole command here, as the server's child process would."""

    def __init__(self, toml):
        self.toml = toml
        self.calls: list[list[str]] = []

    def __call__(self, args, emit):
        self.calls.append(list(args))
        result = CliRunner().invoke(build_app(), ["--config", str(self.toml), *args], env={"CARACOLE_CJK_FONT": None})
        for line in result.output.splitlines():
            emit(line)
        return result.exit_code


@pytest.fixture
def setup(tmp_path):
    """Three songs, two with sheets (Creep transposed up 2), rendered; the config file and the database."""
    chordpro = fake_chordpro_program(tmp_path)
    font = tmp_path / "Kai.otf"  # just enough of an OpenType (CFF) font to pass render.py's checks
    font.write_bytes(b"OTTO" + struct.pack(">HHHH", 1, 0, 0, 0) + struct.pack(">4sIII", b"CFF ", 0, 28, 4) + bytes(4))
    toml = tmp_path / "caracole.toml"
    toml.write_text(
        f'library_dir = "{tmp_path / "lib"}"\nstate_dir = "{tmp_path / "state"}"\n'
        f'cache_dir = "{tmp_path / "cache"}"\nmusic_dir = "{tmp_path / "music"}"\nchordpro_bin = "{chordpro}"\n'
        f'cjk_font = "{font}"\n',
        encoding="utf-8",
    )
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "overrides.toml").write_text('[transpose]\n"Radiohead - Creep" = 2\n', encoding="utf-8")
    cfg = load_config(toml, env={})
    conn = db.connect(cfg.db_path)
    soda = add_song(conn, "Soda Stereo", "De Música Ligera")
    keep_sheet(conn, cfg, soda, tab_id=1)
    creep = add_song(conn, "Radiohead", "Creep")
    keep_sheet(conn, cfg, creep, tab_id=2)
    hysteria = add_song(conn, "Muse", "Hysteria")
    render_sheets(conn, cfg)
    songs = {"soda": soda, "creep": creep, "hysteria": hysteria}
    yield toml, cfg, conn, songs
    conn.close()


@pytest.fixture
def queue(setup):
    return JobQueue(InProcess(setup[0]), limit=3)


@pytest.fixture
def app(setup, queue):
    return WebApp(setup[1], queue, allowed=ALLOWED, csrf="tok")


@pytest.fixture
def campfire(setup):
    """The songbook Campfire, of Creep, Hysteria and De Música Ligera, and its files."""
    _, cfg, conn, songs = setup
    make_songbook(cfg.library_dir / FILE_NAME, "Campfire",
                  ["Radiohead - Creep", "Muse - Hysteria", "Soda Stereo - De Música Ligera"])
    render_songbooks(conn, cfg, Overrides(transpose={songs["creep"].key: 2}), runner=FakeChordPro())
    return cfg.library_dir / "_songbooks" / "Campfire"


def header(response, name):
    values = [v for k, v in response.headers if k.lower() == name.lower()]
    return values[0] if values else None


def get(app, path):
    return app.handle(Request("GET", path, {"host": HOST}))


def post(app, path, fields, *, csrf="tok", **headers):
    form = ({"csrf": csrf} if csrf is not None else {}) | fields
    sent = {"host": HOST, "content-type": "application/x-www-form-urlencoded", "sec-fetch-site": "same-origin",
            "origin": f"http://{HOST}"} | headers
    return app.handle(Request("POST", path, sent, urlencode(form).encode("utf-8")))


def books(setup) -> list[Songbook]:
    return load_songbooks(setup[1].library_dir / FILE_NAME)


def steps(queue):
    return [[s.args for s in job.steps] for job in queue.snapshot()[::-1]]


def data_in(page: str) -> dict:
    return json.loads(re.search(r'<script type="application/json" id="songs">(.*?)</script>', page, re.S).group(1))


def page_data(app) -> dict:
    """The served library page's data, as its script reads it."""
    return data_in(get(app, "/").body.decode("utf-8"))


def page_books(app) -> list[dict]:
    """The songbooks of the served page's Songbooks tab, as data."""
    return page_data(app)["songbooks"]["books"]


# --- the forms -------------------------------------------------------------------------------------


@pytest.mark.slow
def test_the_select_bar_makes_a_songbook_of_the_songs_in_the_order_picked(app, setup, queue):
    songs = setup[3]
    response = post(app, "/songbook/make", {"name": "  Beach   nights ",
                                            "songs": f"{songs['hysteria'].id},{songs['soda'].id}"})
    assert response.status == 303 and header(response, "location") == "/jobs#job-1"
    job = queue.snapshot()[0]
    assert job.title == 'Make the songbook "Beach nights" (2 songs)'
    assert steps(queue) == [[("songbook", "make", "--", "Beach nights", "Muse - Hysteria",
                              "Soda Stereo - De Música Ligera")]]
    assert books(setup) == []  # the server writes no songbook: the command does, under caracole's lock
    queue.run_pending()
    assert queue.snapshot()[0].state == "done", queue.snapshot()[0].steps[0].output
    assert books(setup) == [Songbook("Beach nights", ("Muse - Hysteria", "Soda Stereo - De Música Ligera"))]
    assert (setup[1].library_dir / "_songbooks" / "Beach nights" / "songbook.html").is_file()


@pytest.mark.slow
def test_a_songbook_whose_files_cant_be_made_is_a_failed_request(app, setup, queue):
    songs = setup[3]
    (setup[1].library_dir / "_songbooks" / "Trip" / "songbook.pdf").mkdir(parents=True)
    assert post(app, "/songbook/make", {"name": "Trip", "songs": str(songs["creep"].id)}).status == 303
    queue.run_pending()
    job = queue.snapshot()[0]
    assert job.state == "failed"  # the requests page says so, not "Done"
    assert "couldn't be made" in "\n".join(job.steps[0].output)
    assert books(setup) == [Songbook("Trip", ("Radiohead - Creep",))]


@pytest.mark.slow
def test_a_name_starting_with_a_dash_is_a_name_not_an_option(app, setup, queue):
    songs = setup[3]
    assert post(app, "/songbook/make", {"name": "-Encore", "songs": str(songs["creep"].id)}).status == 303
    queue.run_pending()
    assert books(setup) == [Songbook("-Encore", ("Radiohead - Creep",))]


def test_the_select_bar_adds_to_a_songbook_there_is(app, setup, queue, campfire):
    songs = setup[3]
    assert post(app, "/songbook/add", {"name": "campfire", "songs": str(songs["soda"].id)}).status == 303
    assert queue.snapshot()[0].title == 'Add 1 song to "Campfire"'
    assert steps(queue) == [[("songbook", "add", "--", "Campfire", "Soda Stereo - De Música Ligera")]]


@pytest.mark.slow
def test_the_songbook_forms_queue_move_remove_rename_and_delete(app, setup, queue, campfire):
    for path, fields in [
        ("/songbook/move", {"name": "Campfire", "song": "Muse - Hysteria", "position": "1"}),
        ("/songbook/remove", {"name": "Campfire", "song": "Radiohead - Creep"}),
        ("/songbook/rename", {"name": "Campfire", "new": " Beach "}),
        ("/songbook/delete", {"name": "Beach"}),
    ]:
        assert post(app, path, fields).status == 303, path
        queue.run_pending()
        if path == "/songbook/rename":
            assert books(setup) == [Songbook("Beach", ("Muse - Hysteria", "Soda Stereo - De Música Ligera"))]
    assert [job.title for job in queue.snapshot()[::-1]] == [
        'Move Muse - Hysteria to 1 in "Campfire"', 'Take Radiohead - Creep out of "Campfire"',
        'Rename "Campfire" to "Beach"', 'Delete the songbook "Beach"']
    assert steps(queue) == [
        [("songbook", "move", "--", "Campfire", "Muse - Hysteria", "1")],
        [("songbook", "remove", "--", "Campfire", "Radiohead - Creep")],
        [("songbook", "rename", "--", "Campfire", "Beach")],
        [("songbook", "delete", "--", "Beach")],
    ]
    assert all(job.state == "done" for job in queue.snapshot())
    assert books(setup) == [] and not campfire.exists()


@pytest.mark.slow
def test_a_song_gone_from_the_library_can_still_be_moved_or_taken_out(app, setup, queue, campfire):
    cfg = setup[1]
    make_songbook(cfg.library_dir / FILE_NAME, "Picnic", ["Radiohead - Creep", "Pixies - Where Is My Mind"])
    assert post(app, "/songbook/remove", {"name": "Picnic", "song": "Pixies - Where Is My Mind"}).status == 303
    queue.run_pending()
    assert books(setup)[1] == Songbook("Picnic", ("Radiohead - Creep",))


@pytest.mark.slow
def test_a_song_gone_from_the_library_goes_alone_never_with_the_song_whose_title_its_own_holds(app, setup, queue):
    _, cfg, conn, _ = setup
    police = add_song(conn, "Radiohead", "Karma Police")
    keep_sheet(conn, cfg, police, tab_id=3)
    live = add_song(conn, "Radiohead", "Karma Police Live")
    render_sheets(conn, cfg)
    make_songbook(cfg.library_dir / FILE_NAME, "Gig",
                  ["Radiohead - Karma Police", "Muse - Hysteria", "Radiohead - Karma Police Live"])
    conn.execute("DELETE FROM songs WHERE id = ?", (live.id,))
    gone = page_books(app)[0]["set"][2]
    assert (gone["entry"], gone["missing"], gone["id"]) == ("Radiohead - Karma Police Live", "not in the library", None)

    assert post(app, "/songbook/move", {"name": "Gig", "song": "Radiohead - Karma Police Live",
                                        "position": "2"}).status == 303
    queue.run_pending()
    assert books(setup) == [Songbook("Gig", ("Radiohead - Karma Police", "Radiohead - Karma Police Live",
                                             "Muse - Hysteria"))]
    assert post(app, "/songbook/remove", {"name": "Gig", "song": "Radiohead - Karma Police Live"}).status == 303
    queue.run_pending()
    assert all(job.state == "done" for job in queue.snapshot())
    assert books(setup) == [Songbook("Gig", ("Radiohead - Karma Police", "Muse - Hysteria"))]


@pytest.mark.slow
def test_a_song_the_page_removes_from_the_library_stays_in_its_songbook_as_missing(app, setup, queue, campfire):
    # The page's Remove runs caracole remove, which leaves songbooks.toml alone: the songbook lists the song
    # as missing, its page is still served, and its × takes the song out.
    _, cfg, conn, songs = setup
    creep = songs["creep"]
    assert post(app, "/remove", {"song": str(creep.id), "key": creep.key, "confirm": "1"}).status == 303
    queue.run_pending()
    assert [job.state for job in queue.snapshot()] == ["done"]
    assert conn.execute("SELECT count(*) FROM songs WHERE id = ?", (creep.id,)).fetchone()[0] == 0
    first = page_books(app)[0]["set"][0]
    assert (first["n"], first["title"], first["entry"], first["missing"]) == (1, "Creep", "Radiohead - Creep",
                                                                            "not in the library")
    assert get(app, PAGE).status == 200  # the page caracole wrote, until the next render writes it again

    assert post(app, "/songbook/remove", {"name": "Campfire", "song": "Radiohead - Creep"}).status == 303
    queue.run_pending()
    assert all(job.state == "done" for job in queue.snapshot())
    assert books(setup) == [Songbook("Campfire", ("Muse - Hysteria", "Soda Stereo - De Música Ligera"))]
    assert get(app, PAGE).status == 200  # written again, without it


def test_the_same_change_sent_twice_is_queued_once(app, setup, queue, campfire):
    fields = {"name": "Campfire", "song": "Muse - Hysteria", "position": "1"}
    post(app, "/songbook/move", fields)
    post(app, "/songbook/move", fields)
    post(app, "/songbook/move", fields | {"position": "3"})
    assert len(queue.snapshot()) == 2


@pytest.mark.parametrize("path,fields,status,said", [
    ("/songbook/make", {"name": "Beach", "songs": ""}, 400, "Pick a song"),
    ("/songbook/make", {"name": "Beach", "songs": "1,x"}, 400, "Which songs"),
    ("/songbook/make", {"name": "Beach", "songs": "999"}, 404, "isn't in the library"),
    ("/songbook/make", {"name": "Beach", "songs": "99999999999999999999999"}, 404, "isn't in the library"),
    ("/songbook/make", {"name": "Beach", "songs": "-99999999999999999999999"}, 404, "isn't in the library"),
    ("/songbook/add", {"name": "Campfire", "songs": "1,99999999999999999999999"}, 404, "isn't in the library"),
    ("/songbook/make", {"name": "   ", "songs": "1"}, 400, "needs a name"),
    ("/songbook/make", {"name": ".hidden", "songs": "1"}, 400, "dot"),
    ("/songbook/make", {"name": "x" * 81, "songs": "1"}, 400, "80 characters"),
    ("/songbook/make", {"name": "CAMPFIRE", "songs": "1"}, 409, "is there already"),
    ("/songbook/add", {"name": "Picnic", "songs": "1"}, 404, 'No songbook named "Picnic"'),
    ("/songbook/move", {"name": "Campfire", "song": "Muse - Hysteria", "position": "0"}, 400, "position"),
    ("/songbook/move", {"name": "Campfire", "song": "Muse - Hysteria", "position": "first"}, 400, "position"),
    ("/songbook/move", {"name": "Campfire", "song": "Pixies - Debaser", "position": "1"}, 404, "isn't in"),
    ("/songbook/remove", {"name": "Campfire", "song": ""}, 400, "Which song"),
    ("/songbook/rename", {"name": "Campfire", "new": ""}, 400, "needs a name"),
    ("/songbook/rename", {"name": "Campfire", "new": "campfire"}, 303, ""),  # another case is the same name
    ("/songbook/delete", {"name": ""}, 400, "needs a name"),
])
def test_a_form_that_cant_be_done_is_refused_before_anything_is_queued(app, setup, queue, campfire,
                                                                        path, fields, status, said):
    songs = setup[3]
    fields = {k: v.replace("1", str(songs["creep"].id)) if k == "songs" else v for k, v in fields.items()}
    response = post(app, path, fields)
    assert response.status == status
    assert said in response.body.decode("utf-8").replace("&quot;", '"').replace("&#x27;", "'")
    assert len(queue.snapshot()) == (1 if status == 303 else 0)


def test_a_songbooks_file_that_cant_be_read_is_said_and_nothing_is_queued(app, setup, queue):
    (setup[1].library_dir / FILE_NAME).write_text("[Campfire\n", encoding="utf-8")
    response = post(app, "/songbook/make", {"name": "Beach", "songs": str(setup[3]["creep"].id)})
    assert response.status == 503 and "songbooks.toml can" in response.body.decode("utf-8")
    assert queue.snapshot() == []


@pytest.mark.parametrize("csrf,headers", [
    ("nope", {}),
    (None, {}),
    ("tok", {"sec-fetch-site": "cross-site", "origin": "https://evil.example"}),
])
def test_a_songbook_form_from_anywhere_but_the_page_is_refused(app, setup, queue, campfire, csrf, headers):
    response = post(app, "/songbook/delete", {"name": "Campfire"}, csrf=csrf, **headers)
    assert response.status == 403 and queue.snapshot() == []


def test_a_full_queue_says_so(app, setup, queue, campfire):
    for n in range(3):
        post(app, "/songbook/move", {"name": "Campfire", "song": "Muse - Hysteria", "position": str(n + 1)})
    response = post(app, "/songbook/delete", {"name": "Campfire"})
    assert response.status == 503 and "queue is full" in response.body.decode("utf-8")


# --- the forms, posted by the library page's script ---------------------------------------------


class Edits:
    """``caracole songbook``, done here on songbooks.toml as the command does it, without making files."""

    def __init__(self, library_dir):
        self.toml = library_dir / FILE_NAME

    def __call__(self, args, emit):
        from caracole import songbook

        _, action, _, name, *rest = args
        if action == "make":
            songbook.make_songbook(self.toml, name, rest)
        elif action == "add":
            songbook.add_to_songbook(self.toml, name, rest)
        elif action == "move":
            songbook.move_in_songbook(self.toml, name, rest[0], int(rest[1]))
        elif action == "remove":
            songbook.remove_from_songbook(self.toml, name, rest)
        elif action == "rename":
            songbook.rename_songbook(self.toml, name, rest[0])
        else:
            songbook.delete_songbook(self.toml, name)
        return 0


JSON = "application/json"


def jobs_json(app, ids):
    """/jobs.json, as the page's script asks it: the form token in a header, from the page's own origin."""
    sent = {"host": HOST, "accept": JSON, "sec-fetch-site": "same-origin", "x-caracole-form-token": "tok"}
    response = app.handle(Request("GET", f"/jobs.json?jobs={ids}", sent))
    assert response.status == 200, response.body[:300]
    return json.loads(response.body)


def test_a_songbook_form_from_the_pages_script_is_answered_with_its_job(app, setup, queue, campfire):
    # The page stays where it is: the answer is the job, which says what it is about, never a page.
    response = post(app, "/songbook/move", {"name": "campfire", "song": "Muse - Hysteria", "position": "1"},
                    accept=JSON)
    assert response.status == 200 and header(response, "content-type") == "application/json; charset=utf-8"
    view = json.loads(response.body)["job"]
    assert view["kind"] == "songbook" and view["songId"] is None and view["state"] == "queued"
    assert view["songbook"] == {"action": "move", "name": "Campfire", "after": "Campfire"}  # as songbooks.toml has it
    assert view["line"]["text"] == "Queued…" and view["display"] == 'Move Muse - Hysteria to 1 in "Campfire"'
    # A refusal is a sentence, as data.
    refused = post(app, "/songbook/rename", {"name": "Campfire", "new": ".hidden"}, accept=JSON)
    assert refused.status == 400 and "dot" in json.loads(refused.body)["error"]


@pytest.mark.parametrize("path,fields,said", [
    ("/songbook/make", {"name": " Beach  nights", "songs": "creep"}, {"action": "make", "after": "Beach nights"}),
    ("/songbook/add", {"name": "Campfire", "songs": "soda"}, {"action": "add", "after": "Campfire"}),
    ("/songbook/remove", {"name": "Campfire", "song": "Radiohead - Creep"}, {"action": "remove", "after": "Campfire"}),
    ("/songbook/rename", {"name": "Campfire", "new": " Beach "}, {"action": "rename", "after": "Beach"}),
    ("/songbook/delete", {"name": "CAMPFIRE"}, {"action": "delete", "after": None}),
])
def test_a_songbook_job_names_its_songbook_before_and_after(app, setup, queue, campfire, path, fields, said):
    songs = setup[3]
    fields = {k: str(songs[v].id) if k == "songs" else v for k, v in fields.items()}
    view = json.loads(post(app, path, fields, accept=JSON).body)["job"]
    name = "Beach nights" if said["action"] == "make" else "Campfire"
    assert view["songbook"] == {"name": name, **said}


def test_a_songbook_change_says_what_runs_then_what_it_did(setup, campfire):
    from caracole.web.status import job_line

    songs = setup[3]
    app = WebApp(setup[1], JobQueue(lambda args, emit: 0), allowed=ALLOWED, csrf="tok")
    for path, fields, running, done in [
        ("/songbook/make", {"name": "Picnic", "songs": str(songs["creep"].id)}, "Making the songbook…", "Made"),
        ("/songbook/add", {"name": "Campfire", "songs": str(songs["soda"].id)}, "Adding to the songbook…", "Added"),
        ("/songbook/move", {"name": "Campfire", "song": "Muse - Hysteria", "position": "1"}, "Moving the song…",
         "Moved"),
        ("/songbook/remove", {"name": "Campfire", "song": "Muse - Hysteria"}, "Taking the song out…", "Taken out"),
        ("/songbook/rename", {"name": "Campfire", "new": "Beach"}, "Renaming the songbook…", "Renamed"),
        ("/songbook/delete", {"name": "Campfire"}, "Deleting the songbook…", "Deleted"),
    ]:
        assert post(app, path, fields).status == 303, path
        job = app.queue.snapshot()[0]
        job.state, job.steps[0].state = "running", "running"
        assert job_line(job, None).text == running
        job.state, job.steps[0].state = "done", "done"
        tone = "removed" if done == "Deleted" else "ready"  # as a song's removal says Removed
        assert (job_line(job, None).tone, job_line(job, None).text) == (tone, done)  # not a song "Added"


@pytest.mark.slow
def test_a_songbook_made_says_made_with_its_page_to_open_and_never_that_the_nightly_run_looks(app, setup, queue):
    songs = setup[3]
    post(app, "/songbook/make", {"name": "Beach nights", "songs": f"{songs['hysteria'].id},{songs['soda'].id}"},
         accept=JSON)
    queue.run_pending()
    line = jobs_json(app, "1")["jobs"][0]["line"]
    assert (line["tone"], line["text"]) == ("ready", "Made"), line
    assert line["link"] == {"label": "Open songbook", "href": "_songbooks/Beach%20nights/songbook.html"}
    assert get(app, "/" + line["link"]["href"]).status == 200  # the page caracole wrote, which it serves
    jobs = get(app, "/jobs").body.decode("utf-8")
    assert 'Made · <a href="_songbooks/Beach%20nights/songbook.html">Open songbook</a>' in jobs
    assert "nightly run" not in jobs  # a song's line, "Added: the nightly run looks for it", misleads here
    # Added to: its page again. Renamed, its card is beside the line: no link. Deleted: no page to open, nor
    # the older lines.
    for n, path, fields, done, page in [
        (2, "/songbook/add", {"name": "Beach nights", "songs": str(songs["creep"].id)}, "Added",
         "_songbooks/Beach%20nights/songbook.html"),
        (3, "/songbook/rename", {"name": "Beach nights", "new": "Picnic"}, "Renamed", None),
        (4, "/songbook/delete", {"name": "Picnic"}, "Deleted", None),
    ]:
        post(app, path, fields, accept=JSON)
        queue.run_pending()
        line = jobs_json(app, str(n))["jobs"][0]["line"]
        assert (line["text"], line["link"] and line["link"]["href"]) == (done, page), line
    assert [view["line"]["link"] for view in jobs_json(app, "1,2,3")["jobs"]] == [None, None, None]


def test_once_its_job_is_over_the_songbooks_come_with_it_as_the_tab_draws_them(setup, campfire):
    _, cfg, _, songs = setup
    queue = JobQueue(Edits(cfg.library_dir))
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
    post(app, "/songbook/move", {"name": "Campfire", "song": "Radiohead - Creep", "position": "2"}, accept=JSON)
    waiting = jobs_json(app, "1")["jobs"][0]
    assert waiting["state"] == "queued" and "songbooks" not in waiting  # only once it is over
    queue.run_pending()
    view = jobs_json(app, "1")["jobs"][0]
    assert view["state"] == "done" and view["line"]["text"] == "Moved"
    [book] = view["songbooks"]["books"]  # the tab's data, and the Select bar's menu's
    assert book["name"] == "Campfire" and [s["title"] for s in book["set"]] == ["Hysteria", "Creep", "De Música Ligera"]
    assert view["songbooks"] == page_data(app)["songbooks"]  # as the page has them now
    # Asked about in general (/jobs.json without ?jobs=), no songbooks: the page asks for its own jobs.
    assert "songbooks" not in jobs_json(app, "")["jobs"][0]

    post(app, "/songbook/delete", {"name": "Campfire"}, accept=JSON)
    queue.run_pending()
    none = jobs_json(app, "2")["jobs"][0]["songbooks"]  # none left: the tab says so, and offers a new one
    assert none["books"] == [] and none["error"] is None


def test_a_songbook_change_on_its_way_is_on_the_page_as_a_songbooks_not_a_songs(app, setup, queue, campfire):
    post(app, "/songbook/rename", {"name": "Campfire", "new": "Beach"})
    page = get(app, "/").body.decode("utf-8")
    data = json.loads(re.search(r'<script type="application/json" id="songs">(.*?)</script>', page, re.S).group(1))
    [view] = data["server"]["jobs"]
    assert view["kind"] == "songbook" and view["songbook"] == {"action": "rename", "name": "Campfire",
                                                                 "after": "Beach"}


# --- a song's setting, and a song added from the tab's search ------------------------------------------


def test_a_songs_setting_is_queued_as_caracole_songbook_set_with_its_capo(app, setup, queue, campfire):
    # The tab's chip always sends the capo with the key and the mode, so a sheet that takes the song's place
    # keeps the key the songbook sounds in.
    response = post(app, "/songbook/set", {"name": "campfire", "song": "Radiohead - Creep", "key": "G",
                                           "mode": "dorian", "capo": "0"}, accept=JSON)
    view = json.loads(response.body)["job"]
    assert view["kind"] == "songbook" and view["songbook"] == {"action": "set", "name": "Campfire", "after": "Campfire"}
    assert view["display"] == 'Play Radiohead - Creep in G dorian, capo 0, in "Campfire"'
    assert steps(queue) == [[("songbook", "set", "--key", "G", "--mode", "dorian", "--capo", "0", "--", "Campfire",
                              "Radiohead - Creep")]]
    post(app, "/songbook/set", {"name": "Campfire", "song": "Radiohead - Creep", "clear": "1"})
    assert steps(queue)[1] == [("songbook", "set", "--clear", "--", "Campfire", "Radiohead - Creep")]
    assert queue.snapshot()[0].title == 'Play Radiohead - Creep in its own version in "Campfire"'


@pytest.mark.slow
def test_the_setting_queued_is_written_in_songbooks_toml(app, setup, queue, campfire):
    post(app, "/songbook/set", {"name": "Campfire", "song": "Radiohead - Creep", "key": "G", "mode": "dorian",
                                "capo": "2"})
    queue.run_pending()
    assert queue.snapshot()[0].state == "done", queue.snapshot()[0].steps[0].output
    from caracole.songbook import Setting

    assert books(setup)[0].songs[0].setting == Setting("G", "dorian", 2)
    assert 'song = "Radiohead - Creep", key = "G", mode = "dorian", capo = 2' in (
        setup[1].library_dir / FILE_NAME).read_text(encoding="utf-8")
    assert page_books(app)[0]["set"][0]["plays"] == "G Dorian, capo 2"


def test_a_setting_change_says_what_runs_then_what_it_did(setup, campfire):
    from caracole.web.status import job_line

    app = WebApp(setup[1], JobQueue(lambda args, emit: 0), allowed=ALLOWED, csrf="tok")
    post(app, "/songbook/set", {"name": "Campfire", "song": "Muse - Hysteria", "capo": "3"})
    job = app.queue.snapshot()[0]
    job.state, job.steps[0].state = "running", "running"
    assert job_line(job, None).text == "Changing where it plays…"
    job.state, job.steps[0].state = "done", "done"
    assert (job_line(job, None).tone, job_line(job, None).text, job_line(job, None).link) == ("ready", "Changed", None)


@pytest.mark.parametrize("fields,status,said", [
    ({"song": "Radiohead - Creep"}, 400, "a key, a mode or a capo"),
    ({"song": "Radiohead - Creep", "key": "H"}, 400, "key must be a tonic"),
    ({"song": "Radiohead - Creep", "mode": "major"}, 400, "mode must be one of"),
    ({"song": "Radiohead - Creep", "capo": "12"}, 400, "capo must be a fret"),
    ({"song": "Radiohead - Creep", "capo": "two"}, 400, "capo must be a fret"),
    ({"song": "Pixies - Debaser", "capo": "1"}, 404, "isn't in"),
    ({"song": "", "capo": "1"}, 400, "Which song"),
])
def test_a_setting_that_cant_be_one_is_refused_before_anything_is_queued(app, setup, queue, campfire, fields, status,
                                                                         said):
    response = post(app, "/songbook/set", {"name": "Campfire", **fields}, accept=JSON)
    assert response.status == status and said in json.loads(response.body)["error"]
    assert queue.snapshot() == []


def test_add_a_song_of_the_library_queues_songbook_add(app, setup, queue, campfire):
    hysteria = setup[3]["hysteria"]
    make_songbook(setup[1].library_dir / FILE_NAME, "Picnic", ["Radiohead - Creep"])
    data = json.loads(post(app, "/songbook/add-song", {"name": "picnic", "song": str(hysteria.id)}, accept=JSON).body)
    assert data["job"]["songbook"] == {"action": "add", "name": "Picnic", "after": "Picnic"} and data["jobs"] == []
    assert steps(queue) == [[("songbook", "add", "--", "Picnic", "Muse - Hysteria")]]


def test_add_a_song_from_an_index_looks_it_up_then_adds_it(app, setup, queue, campfire):
    # A song you don't have: in wanted.txt at once (as Get it writes it), looked up now, then put in the songbook.
    cfg = setup[1]
    data = json.loads(post(app, "/songbook/add-song", {"name": "Campfire", "artist": "Oasis", "title": "Wonderwall",
                                                       "ug": "oasis/wonderwall"}, accept=JSON).body)
    assert steps(queue) == [[("get", "--progress", "--ug=oasis/wonderwall", "--", "Oasis", "Wonderwall")],
                            [("songbook", "add", "--", "Campfire", "Oasis - Wonderwall")]]
    assert "Oasis - Wonderwall" in cfg.wanted_file.read_text(encoding="utf-8")
    assert [(v["kind"], v["display"]) for v in data["jobs"]] == [("song", "Oasis - Wonderwall")]
    assert data["job"]["display"] == 'Add Oasis - Wonderwall to "Campfire"'


def test_add_a_song_your_library_has_by_its_names_needs_no_lookup(app, setup, queue, campfire):
    make_songbook(setup[1].library_dir / FILE_NAME, "Picnic", ["Muse - Hysteria"])
    post(app, "/songbook/add-song", {"name": "Picnic", "artist": "Radiohead", "title": "Creep", "ug": "radiohead/creep"})
    assert steps(queue) == [[("songbook", "add", "--", "Picnic", "Radiohead - Creep")]]
    assert not setup[1].wanted_file.exists() or "Creep" not in setup[1].wanted_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("fields,status,said", [
    ({"name": "Picnic", "song": "1"}, 404, 'No songbook named "Picnic"'),
    ({"name": "Campfire", "song": "999"}, 404, "isn't in the library"),
    ({"name": "Campfire"}, 400, "Which song"),
])
def test_add_a_song_that_cant_be_added_is_refused_before_anything_is_queued(app, setup, queue, campfire, fields,
                                                                          status, said):
    response = post(app, "/songbook/add-song", fields, accept=JSON)
    assert response.status == status and said in json.loads(response.body)["error"], response.body
    assert queue.snapshot() == []


def test_a_full_queue_adds_no_song_it_couldnt_look_up(app, setup, queue, campfire):
    for n in range(2):  # room for one job more: not for the lookup and the songbook's change
        post(app, "/songbook/move", {"name": "Campfire", "song": "Muse - Hysteria", "position": str(n + 1)})
    response = post(app, "/songbook/add-song", {"name": "Campfire", "artist": "Oasis", "title": "Wonderwall"},
                    accept=JSON)
    assert response.status == 503 and "queue is full" in json.loads(response.body)["error"]
    assert len(queue.snapshot()) == 2


# --- the songs a songbook lacks, got now ----------------------------------------------------------


@pytest.fixture
def gig(setup):
    """The songbook Gig: Hysteria (no sheet), Debaser (not in the library), Creep (a sheet), Uprising (no sheet)
    and Wonderwall (no sheet, ignored in overrides.toml)."""
    from caracole.overrides import add_ignore

    _, cfg, conn, songs = setup
    songs["uprising"] = add_song(conn, "Muse", "Uprising")
    songs["wonderwall"] = add_song(conn, "Oasis", "Wonderwall")
    add_ignore(cfg.overrides_file, "Oasis - Wonderwall")
    make_songbook(cfg.library_dir / FILE_NAME, "Gig", ["Muse - Hysteria", "Pixies - Debaser", "Radiohead - Creep",
                                                        "Muse - Uprising", "Oasis - Wonderwall"])
    return songs


def test_the_songbooks_data_says_which_songs_a_lookup_could_get_now(app, setup, gig):
    # Hysteria and Uprising: not Debaser, which isn't in the library, nor Wonderwall, ignored. Each song the library
    # has is named by its id, for the page to show its lookup's line there.
    [book] = page_books(app)
    assert [(s["title"], s["id"], s["get"]) for s in book["set"]] == [
        ("Hysteria", gig["hysteria"].id, True), ("Debaser", None, False), ("Creep", gig["creep"].id, False),
        ("Uprising", gig["uprising"].id, True), ("Wonderwall", gig["wonderwall"].id, False)]
    # The file on disk can't look anything up: it has no server to ask (the page's script offers the commands).
    from caracole.library_page import build_library_page
    from caracole.overrides import load_overrides

    _, cfg, conn, _ = setup
    on_disk = build_library_page(conn, cfg, load_overrides(cfg.overrides_file), datetime.now(UTC))
    assert "server" not in data_in(on_disk)


def test_a_songbook_with_every_sheet_offers_nothing_to_get(app, setup, campfire):
    keep_sheet(setup[2], setup[1], setup[3]["hysteria"], tab_id=3)
    render_sheets(setup[2], setup[1])
    assert 'action="/songbook/get"' not in get(app, "/").body.decode("utf-8")


def test_get_the_missing_songs_queues_a_lookup_of_each_in_order_then_the_songbook_again(app, setup, queue, gig):
    queue._limit = 10
    response = post(app, "/songbook/get", {"name": "gig"})
    assert response.status == 303 and header(response, "location") == "/jobs#job-3"
    assert steps(queue) == [
        [("get", "--progress", "--", "Muse", "Hysteria")],
        [("get", "--progress", "--", "Muse", "Uprising")],
        [("songbook", "render", "--", "Gig")],  # once they are done: the songbook made again with their sheets
    ]
    assert [job.title for job in queue.snapshot()[::-1]] == [
        "Fetch Muse - Hysteria", "Fetch Muse - Uprising", 'Make "Gig" again, with the songs it got']
    # Asked again while they wait, nothing new is queued.
    post(app, "/songbook/get", {"name": "Gig"})
    assert len(queue.snapshot()) == 3


def test_the_pages_script_gets_the_songbooks_job_and_each_lookup(app, setup, queue, gig):
    queue._limit = 10
    data = json.loads(post(app, "/songbook/get", {"name": "Gig"}, accept=JSON).body)
    assert data["job"]["kind"] == "songbook" and data["job"]["line"]["text"] == "Queued behind 2 requests…"
    assert data["job"]["songbook"] == {"action": "render", "name": "Gig", "after": "Gig"}
    assert [(v["kind"], v["songId"], v["display"], v["line"]["text"]) for v in data["jobs"]] == [
        ("song", gig["hysteria"].id, "Muse - Hysteria", "Queued…"),
        ("song", gig["uprising"].id, "Muse - Uprising", "Queued behind 1 request…")]
    assert data["left"] == 0


def test_a_queue_with_less_room_gets_the_first_missing_songs_and_says_how_many_wait(app, setup, queue, gig):
    # The queue holds 3 here: the first two lookups, then the songbook; a tap once it empties gets the rest.
    add_song(setup[2], "Muse", "Starlight")
    make_songbook(setup[1].library_dir / FILE_NAME, "Late", ["Muse - Hysteria", "Muse - Uprising", "Muse - Starlight"])
    data = json.loads(post(app, "/songbook/get", {"name": "Late"}, accept=JSON).body)
    assert [v["display"] for v in data["jobs"]] == ["Muse - Hysteria", "Muse - Uprising"] and data["left"] == 1
    assert steps(queue)[-1] == [("songbook", "render", "--", "Late")]
    full = post(app, "/songbook/get", {"name": "Gig"}, accept=JSON)
    assert full.status == 503 and "queue is full" in json.loads(full.body)["error"]


def test_get_one_missing_song_now_looks_it_up_then_makes_the_songbook_again(app, setup, queue, gig):
    # A set list's Get it: that song alone, as Get the missing songs now gets each.
    queue._limit = 10
    data = json.loads(post(app, "/songbook/get", {"name": "Gig", "song": str(gig["uprising"].id)}, accept=JSON).body)
    assert steps(queue) == [[("get", "--progress", "--", "Muse", "Uprising")], [("songbook", "render", "--", "Gig")]]
    assert [v["display"] for v in data["jobs"]] == ["Muse - Uprising"] and data["left"] == 0
    refused = post(app, "/songbook/get", {"name": "Gig", "song": str(gig["creep"].id)}, accept=JSON)
    assert refused.status == 409 and "has a sheet" in json.loads(refused.body)["error"]


@pytest.mark.parametrize("fields,status,said", [
    ({"name": "Picnic"}, 404, 'No songbook named "Picnic"'),
    ({"name": "Campfire"}, 409, "has a sheet"),
    ({"name": ""}, 400, "needs a name"),
])
def test_get_the_missing_songs_is_refused_before_anything_is_queued(app, setup, queue, gig, fields, status, said):
    _, cfg, conn, songs = setup
    make_songbook(cfg.library_dir / FILE_NAME, "Campfire", ["Radiohead - Creep", "Pixies - Debaser",
                                                             "Oasis - Wonderwall"])  # nothing it can get
    response = post(app, "/songbook/get", fields)
    assert response.status == status
    assert said in response.body.decode("utf-8").replace("&quot;", '"')
    assert queue.snapshot() == []


class GetsAndRenders(InProcess):
    """``caracole get`` faked (a sheet kept and rendered, as its stages would, no request), and every other
    command run here, as the server's child process would: ``caracole songbook render`` makes the files."""

    def __init__(self, toml, cfg):
        super().__init__(toml)
        self.cfg = cfg

    def __call__(self, args, emit):
        if args[0] != "get":
            return super().__call__(args, emit)
        from caracole.songs import find_song

        self.calls.append(list(args))
        conn = db.connect(self.cfg.db_path)
        try:
            from caracole.normalize import identity_key

            song = find_song(conn, identity_key(args[-2], args[-1]))
            keep_sheet(conn, self.cfg, song, tab_id=500 + song.id)
            render_sheets(conn, self.cfg)
        finally:
            conn.close()
        return 0


@pytest.mark.slow
def test_once_the_lookups_are_done_the_songbook_holds_their_sheets(setup, gig):
    toml, cfg, conn, songs = setup
    queue = JobQueue(GetsAndRenders(toml, cfg), limit=10)
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
    render_songbooks(conn, cfg, Overrides(), runner=FakeChordPro())
    assert "Hysteria" not in (cfg.library_dir / "_songbooks" / "Gig" / "songbook.cho").read_text(encoding="utf-8")
    post(app, "/songbook/get", {"name": "Gig"}, accept=JSON)
    queue.run_pending()
    assert [job.state for job in queue.snapshot()] == ["done"] * 3, [j.steps[0].output for j in queue.snapshot()]
    made = (cfg.library_dir / "_songbooks" / "Gig" / "songbook.cho").read_text(encoding="utf-8")
    assert "Hysteria" in made and "Uprising" in made  # their sheets, in it now
    line = jobs_json(app, "3")["jobs"][0]["line"]
    assert (line["text"], line["link"]) == ("Made", {"label": "Open songbook", "href": "_songbooks/Gig/songbook.html"})
    # Debaser isn't in the library, Wonderwall is ignored: nothing to get.
    assert not any(s["get"] for s in page_books(app)[0]["set"])


# --- the songbook's files ------------------------------------------------------------------------


def test_the_songbook_page_caracole_wrote_is_served_in_its_sandbox(app, campfire):
    page = (campfire / "songbook.html").read_bytes()
    response = get(app, PAGE)
    assert response.status == 200 and response.body == page
    assert header(response, "content-type") == "text/html; charset=utf-8"
    csp = header(response, "content-security-policy")
    assert csp == songbook_csp(page) + "; frame-ancestors 'none'"
    assert csp.startswith("sandbox allow-scripts; default-src 'none'; ")
    assert header(response, "x-content-type-options") == "nosniff" and header(response, "cache-control") == "no-store"
    assert get(app, "/_songbooks/Campfire/songbook%2Ehtml").status == 200  # an address is decoded first


def test_its_pdf_and_chordpro_file_are_served_as_any_file(app, campfire):
    assert header(get(app, "/_songbooks/Campfire/songbook.pdf"), "content-type") == "application/pdf"
    assert header(get(app, "/_songbooks/Campfire/songbook.cho"), "content-type") == "text/plain; charset=utf-8"


def test_a_songbook_page_that_isnt_caracoles_is_never_served(app, setup, campfire, tmp_path):
    cfg = setup[1]
    page = (campfire / "songbook.html").read_bytes()
    planted = cfg.library_dir / "_songbooks" / "Planted"
    planted.mkdir()
    (planted / "songbook.html").write_bytes(page)  # caracole's bytes, but no record of writing them there
    (cfg.library_dir / "Soda Stereo" / "songbook.html").write_bytes(page)
    (campfire / "other.html").write_bytes(page)
    for path in ("/_songbooks/Planted/songbook.html", "/Soda Stereo/songbook.html", "/_songbooks/Campfire/other.html",
                 "/_songbooks/songbook.html", "/_songbooks/Campfire/../Campfire/songbook.html",
                 "/_songbooks/.Campfire/songbook.html"):
        assert get(app, path).status == 404, path
    refused = get(app, "/_songbooks/Planted/songbook.html").body.decode("utf-8")
    assert "caracole songbook render" in refused  # why, and what to do

    (campfire / "songbook.html").write_bytes(page.replace(b"Creep", b"Creeq"))  # a device edited it
    assert get(app, PAGE).status == 404
    (campfire / "songbook.html").unlink()
    (campfire / "songbook.html").symlink_to(planted / "songbook.html")  # the very bytes, through a link
    assert get(app, PAGE).status == 404


def test_no_folder_on_the_way_is_followed_through_a_link(app, setup, campfire, tmp_path):
    cfg = setup[1]
    elsewhere = tmp_path / "elsewhere"
    shutil.move(campfire, elsewhere)  # caracole's very page, the record matching it
    campfire.symlink_to(elsewhere, target_is_directory=True)
    assert get(app, PAGE).status == 404
    campfire.unlink()
    shutil.move(elsewhere, campfire)
    assert get(app, PAGE).status == 200
    books_dir = cfg.library_dir / "_songbooks"
    shutil.move(books_dir, tmp_path / "books")
    books_dir.symlink_to(tmp_path / "books", target_is_directory=True)
    assert get(app, PAGE).status == 404


def test_a_page_whose_policy_cant_be_read_runs_nothing():
    assert songbook_csp(b"<!doctype html><title>x</title>") == (
        "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'")
    bad = b'<meta http-equiv="Content-Security-Policy" content="default-src \xc3\xa9">'
    assert songbook_csp(bad).startswith("sandbox; default-src 'none'")


@in_chromium
def test_the_served_songbook_works_in_its_sandbox_in_a_real_browser(setup, campfire, tmp_path):
    from caracole.web.server import make_server

    cfg = setup[1]
    app = WebApp(cfg, JobQueue(lambda args, emit: 0), allowed=ALLOWED, csrf="tok")
    server = make_server(app, "127.0.0.1", 0)
    # shutdown() returns at the next poll: every 10 ms, not every 500
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}{PAGE}#song-1"
    try:
        dom = browser.dump_dom(url, (390, 844), budget_ms=4000)
    finally:
        server.shutdown()
        server.server_close()
    assert 'data-view="song"' in dom and 'data-ready="1"' in dom  # both scripts ran, under the header's policy
    sheet = re.search(r'<article[^>]*id="sheet"[^>]*>(.*?)</article>', dom, re.DOTALL).group(1)
    chords = re.findall(r'<b class="c[^"]*" data-c="\d+"[^>]*>([^<]*)</b>', sheet)
    assert chords[:4] == ["Bm", "G", "D", "A"]  # Creep's Am, F, C, G, up 2: its [transpose]
    assert '<span class="vh" id="key-full">Key Bm · +2</span>' in dom


def test_the_songbook_page_is_one_of_the_pages_caracole_writes():
    # Served as the sheet viewers are (files.read_written_page), by its own record and policy.
    from caracole import songbook
    from caracole.web.app import written_pages

    page = written_pages()[songbook.HTML_NAME]
    assert page.written is songbook.pages_written and page.csp is songbook_csp
    assert page.refused == songbook.PAGE_REFUSED


@in_chromium
def test_a_served_songbook_keeps_a_songs_transposition_in_its_address_across_a_reload(setup, campfire, tmp_path):
    # The sandbox has no storage: the viewer keeps a song's settings in the address, beside the song
    # book.js opens ("#song-1=&t=3"), so a reload, and Back from the next song, find them again.
    from helpers.chromium import Chromium

    from caracole.web.server import make_server

    app = WebApp(setup[1], JobQueue(lambda args, emit: 0), allowed=ALLOWED, csrf="tok")
    server = make_server(app, "127.0.0.1", 0)
    # shutdown() returns at the next poll: every 10 ms, not every 500
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}{PAGE}"
    chords = ("Array.from(document.querySelectorAll('#sheet .c[data-c]')).slice(0, 4)"
              ".map((c) => c.textContent).join(' ')")
    key = "document.querySelector('#key-full').textContent"
    afresh = "window.before === undefined && document.documentElement.dataset.ready === '1'"  # a new page
    try:
        with Chromium(tmp_path / "profile") as browser:
            tab = browser.open(url)
            tab.wait_for("document.documentElement.dataset.view === 'contents'")
            assert tab.eval("origin") == "null"  # in its sandbox
            tab.eval("window.before = true; document.querySelector('#contents a[href=\"#song-1\"]').click()")
            tab.wait_for(afresh)
            assert tab.eval("location.hash") == "#song-1="  # as the viewer writes the address back
            assert tab.eval(chords) == "Bm G D A" and tab.eval(key) == "Key Bm · +2"  # Creep's [transpose]
            tab.click("#t-up")  # a semitone more, from the bar
            assert tab.eval(chords) == "Cm Ab Eb Bb" and tab.eval(key) == "Key Cm · +3"
            assert tab.eval("location.hash") == "#song-1=&t=3"
            tab.eval("window.before = true; setTimeout(() => location.reload(), 0)")
            tab.wait_for(afresh)
            assert tab.eval("document.documentElement.dataset.view") == "song"
            assert tab.eval(chords) == "Cm Ab Eb Bb" and tab.eval(key) == "Key Cm · +3"
            tab.eval("window.before = true; document.querySelector('#song-1 a[rel=\"next\"]').click()")
            tab.wait_for(afresh)
            assert tab.eval("location.hash") == "#song-3="  # Hysteria has no sheet: De Música Ligera
            assert "+" not in tab.eval(key)  # in its own key: the settings were song 1's
            tab.eval("history.back()")  # loaded again, or as it was left (the back-forward cache)
            tab.wait_for("location.hash === '#song-1=&t=3' && document.documentElement.dataset.ready === '1' && "
                         "document.documentElement.dataset.view === 'song'")
            assert tab.eval(chords) == "Cm Ab Eb Bb" and tab.eval(key) == "Key Cm · +3"
    finally:
        server.shutdown()
        server.server_close()


def test_the_served_library_page_links_the_songbook_page(app, campfire):
    files = {f["label"]: f["href"] for f in page_books(app)[0]["files"]}
    assert files["Phone page"] == "_songbooks/Campfire/songbook.html"
    assert get(app, "/" + files["Phone page"]).status == 200

