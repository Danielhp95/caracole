"""caracole/web/app.py: the routes of caracole serve, without a socket."""

import re
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


def shown(response):
    """The page's text as a reader sees it, entities decoded."""
    import html

    return html.unescape(text(response))


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


def test_fetch_now_of_a_song_ignored_in_overrides_toml_is_refused(app, conn, cfg, queue):
    from caracole.overrides import add_ignore

    creep = add_song(conn, "Radiohead", "Creep")
    add_ignore(cfg.overrides_file, creep.display)
    response = post(app, "/fetch", {"song": str(creep.id)})
    assert response.status == 409 and "ignored" in text(response)
    assert queue.snapshot() == []


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
