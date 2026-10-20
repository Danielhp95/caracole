"""caracole serve's songbooks: the forms that queue caracole songbook, and songbook.html, served only
while it is the page caracole wrote."""

from __future__ import annotations

import re
import shutil
import struct
import subprocess
import threading
from urllib.parse import urlencode

import pytest
from conftest import add_song
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
CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")


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


# --- the forms -------------------------------------------------------------------------------------


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


def test_a_song_gone_from_the_library_can_still_be_moved_or_taken_out(app, setup, queue, campfire):
    cfg = setup[1]
    make_songbook(cfg.library_dir / FILE_NAME, "Picnic", ["Radiohead - Creep", "Pixies - Where Is My Mind"])
    assert post(app, "/songbook/remove", {"name": "Picnic", "song": "Pixies - Where Is My Mind"}).status == 303
    queue.run_pending()
    assert books(setup)[1] == Songbook("Picnic", ("Radiohead - Creep",))


def test_a_song_gone_from_the_library_goes_alone_never_with_the_song_whose_title_its_own_holds(app, setup, queue):
    _, cfg, conn, _ = setup
    police = add_song(conn, "Radiohead", "Karma Police")
    keep_sheet(conn, cfg, police, tab_id=3)
    live = add_song(conn, "Radiohead", "Karma Police Live")
    render_sheets(conn, cfg)
    make_songbook(cfg.library_dir / FILE_NAME, "Gig",
                  ["Radiohead - Karma Police", "Muse - Hysteria", "Radiohead - Karma Police Live"])
    conn.execute("DELETE FROM songs WHERE id = ?", (live.id,))
    page = get(app, "/").body.decode("utf-8")
    assert re.search(r'<li class="missing">.*?Karma Police Live.*?missing: not in the library', page)

    assert post(app, "/songbook/move", {"name": "Gig", "song": "Radiohead - Karma Police Live",
                                        "position": "2"}).status == 303
    queue.run_pending()
    assert books(setup) == [Songbook("Gig", ("Radiohead - Karma Police", "Radiohead - Karma Police Live",
                                             "Muse - Hysteria"))]
    assert post(app, "/songbook/remove", {"name": "Gig", "song": "Radiohead - Karma Police Live"}).status == 303
    queue.run_pending()
    assert all(job.state == "done" for job in queue.snapshot())
    assert books(setup) == [Songbook("Gig", ("Radiohead - Karma Police", "Muse - Hysteria"))]


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


@pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")
def test_the_served_songbook_works_in_its_sandbox_in_a_real_browser(setup, campfire, tmp_path):
    from caracole.web.server import make_server

    cfg = setup[1]
    app = WebApp(cfg, JobQueue(lambda args, emit: 0), allowed=ALLOWED, csrf="tok")
    server = make_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}{PAGE}#song-1"
    try:
        result = subprocess.run(
            [CHROMIUM, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={tmp_path / 'chrome'}", "--window-size=390,844", "--virtual-time-budget=4000",
             "--dump-dom", url],
            capture_output=True, text=True, timeout=90, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        pytest.skip(f"chromium couldn't run: {e}")
    finally:
        server.shutdown()
        server.server_close()
    if result.returncode != 0 or "<html" not in result.stdout:
        pytest.skip(f"chromium couldn't run: {result.stderr[-500:]}")
    dom = result.stdout
    assert 'data-view="song"' in dom and 'data-ready="1"' in dom  # both scripts ran, under the header's policy
    sheet = re.search(r'<article[^>]*id="sheet"[^>]*>(.*?)</article>', dom, re.DOTALL).group(1)
    chords = re.findall(r'<b class="c[^"]*" data-c="\d+"[^>]*>([^<]*)</b>', sheet)
    assert chords[:4] == ["Bm", "G", "D", "A"]  # Creep's Am, F, C, G, up 2: its [transpose]
    assert re.search(r'id="fab"[^>]*>Key Bm · \+2</button>', dom)


def test_the_served_library_page_links_the_songbook_page(app, campfire):
    body = get(app, "/").body.decode("utf-8")
    assert 'href="_songbooks/Campfire/songbook.html"' in body
    assert 'action="/songbook/move"' in body and '<input type="hidden" name="csrf" value="tok">' in body

