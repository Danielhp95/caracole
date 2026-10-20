"""caracole/web/app.py: the routes of caracole serve, without a socket."""

import json
import re
from pathlib import Path
from urllib.parse import urlencode

import pytest
from typer.testing import CliRunner

from caracole.cli import build_app
from caracole.library import song_dir
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
    assert again.status == 303 and header(again, "location") == "/jobs?job=1#job-1"
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
    assert response.status == 303 and header(response, "location") == "/jobs?job=1#job-1"
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


# --- from the page's script, without leaving the page ----------------------------------------------


def test_a_request_from_the_pages_script_is_answered_with_its_job_not_a_redirect(app, queue):
    response = post(app, "/request", {"artist": " Radiohead ", "title": "Creep", "fetch": "1"}, accept=JSON)
    assert response.status == 200 and header(response, "location") is None
    assert answer(response) == {"job": {
        "id": 1, "display": "Radiohead - Creep", "songId": None, "state": "queued", "fetching": True,
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
    """The job's commands, faked: ``fetch`` looks the song up as ``how`` says, and keeps nothing."""

    def __init__(self, cfg, how):
        self.cfg = cfg
        self.how = how

    def __call__(self, args, emit):
        from caracole import db
        from caracole.overrides import override_key
        from caracole.songs import find_song

        if args[0] == "fetch":
            conn = db.connect(self.cfg.db_path)
            try:
                song = find_song(conn, override_key(args[-1].removeprefix("--song=")))
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
    # A song not found in the index, looked up on its artist's page during the request, is not found.
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
    """The job's commands: ``caracole fetch`` itself, through the CLI at -v; the others do nothing."""

    def __init__(self, config):
        self.config = config

    def __call__(self, args, emit):
        if args[0] != "fetch":
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


def real_fetch_app(cfg, tmp_path, *, budget=60):
    config = tmp_path / "caracole-cli.toml"
    config.write_text(f'library_dir = "{cfg.library_dir}"\nmusic_dir = "{cfg.music_dir}"\n'
                      f'state_dir = "{cfg.state_dir}"\ncache_dir = "{cfg.cache_dir}"\n'
                      f"[providers.ug]\nbudget = {budget}\ndelay = [0, 0]\n", encoding="utf-8")
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
    budget = 60
    fake_ug[SIGNOS] = signos_page()
    if how == "cooldown":
        record_block(conn, "ug", utcnow(), "HTTP 403")
    elif how == "budget":  # two pages to read, one request to spend
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
    app, queue = real_fetch_app(cfg, tmp_path, budget=budget)

    post(app, "/fetch", {"song": str(signos.id)})
    queue.run_pending()

    job = answer(get_json(app, "/jobs.json"))["jobs"][0]
    assert job["state"] == "done", queue.snapshot()[0].steps[1].output
    if how == "nothing kept":
        assert job["line"]["tone"] == "missing"
    else:
        assert job["line"] == {"tone": "waiting", "text": "Not fetched yet", "link": None,
                               "details": "jobs?job=1#job-1"}, queue.snapshot()[0].steps[1].output
        from caracole.songs import get_song

        assert get_song(conn, signos.id).ug_dirty is True  # so the next run fetches it: it does wait


@pytest.mark.parametrize("decision,review,error,line", [
    ("not_found", False, "Ultimate Guitar lists Obscure Band only by bare tab ids, which caracole can't see. "
                         "Find the artist's page on UG.",
     {"tone": "missing", "text": "Not found", "link": {"label": "see the to-do page", "href": "_todo.md"},
      "details": "jobs?job=1#job-1"}),
    ("review", True, '"Obscure Band - Song" needs review first: run `caracole review`.',
     {"tone": "review", "text": "Needs review", "link": {"label": "see the to-do page", "href": "_todo.md"},
      "details": "jobs?job=1#job-1"}),
])
def test_a_requested_fetch_that_fetch_refuses_says_why_as_the_card_would(cfg, conn, decision, review, error,
                                                                           line):
    # `caracole fetch --song` exits 1 on a song the match left not found (its artist unknown) or in review.
    def runner(args, emit):
        from caracole import db
        from caracole.songs import find_song
        from caracole.wanted import sync_wanted

        c = db.connect(cfg.db_path)
        try:
            if args[0] == "add":
                sync_wanted(c, cfg.wanted_file, datetime_now())
            elif args[0] == "match":
                update_song(c, find_song(c, "obscure-band/song").id, match_decision=decision, review=review)
            elif args[0] == "fetch":
                emit(f"error: {error}")
                return 1
        finally:
            c.close()
        return 0

    queue = JobQueue(runner)
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
    post(app, "/request", {"artist": "Obscure Band", "title": "Song", "fetch": "1"})
    queue.run_pending()
    job = answer(get_json(app, "/jobs.json"))["jobs"][0]
    assert job["state"] == "failed" and job["line"] == line
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
        if args[0] == "fetch":
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
    assert "Fetching from Ultimate Guitar" in newest and "<pre>ok" in newest and "Done" in newest


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
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/" in cookie
    assert "a-long-random-access-token" not in cookie
    signed_in = get(locked, "/", cookie=f"caracole_session={value}")
    assert signed_in.status == 200 and "Radiohead - Creep" in text(signed_in)
    assert get(locked, "/", cookie="caracole_session=forged").status == 401
