"""caracole serve's versions page: Make this the one, Keep it and back to caracole's pick, each a command queued;
and a kept version's page, served as a sheet viewer is."""

import re
from html import unescape
from urllib.parse import quote, urlencode

import pytest

from caracole.library import keep_file, song_dir
from caracole.render import _note_written
from caracole.sheet_versions import version_names
from caracole.versions import mark_gone, set_coverage, upsert_version
from caracole.viewer import build_viewer
from caracole.web.status import details_href

from helpers.rendered import FETCHED, fake_chordpro, rendered_song
from test_web_app import ALLOWED, HOST, JSON, META_POLICY, Recorder, get, header, post, text

FOLDER = "Soda Stereo/De Música Ligera"
SHEET = f"{FOLDER}/sheet.html"
DISPLAY = "Soda Stereo - De Música Ligera"
NAMES = ["Soda Stereo", "De Música Ligera"]  # as two words: a " - " in a name stays its own
KEPT, OTHER, GONE = "39144", "1064463", "777"  # a version kept beside the sheet, one not kept, one UG lost
SLUGGED = "https://tabs.ultimate-guitar.com/tab/soda-stereo/de-musica-ligera-chords-{}"


@pytest.fixture
def recorder():
    return Recorder()


@pytest.fixture
def queue(recorder):
    from caracole.web.jobs import JobQueue

    return JobQueue(recorder, limit=5)


@pytest.fixture
def app(cfg, queue):
    from caracole.web.app import WebApp

    return WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")


def shown(response):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", text(response))).split())


def chords(conn, song, tab, *, rating, votes, number, coverage=None, note=None):
    raw = {"id": int(tab), "version_description": note} if note else {"id": int(tab)}
    vid = upsert_version(conn, provider="ug", tab_id=tab, song_id=song.id, slot="sheet", kind="chords",
                         rating=rating, votes=votes, version=number, label=None, url=SLUGGED.format(tab), raw=raw,
                         now=FETCHED)
    if coverage is not None:
        set_coverage(conn, vid, coverage)
    return vid


def keep_version(conn, cfg, song, vid, tab, *, rank=2):
    """Keep a version beside the sheet as the fetch step does (its text and JSON), and its viewer page as render.py
    writes and records it."""
    folder = song_dir(cfg.library_dir, song)
    txt, data, page = version_names(tab)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name=txt, data=f"[G]Otra {tab}\n".encode(), rank=rank)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name=data, data=b"{}", rank=rank)
    html = build_viewer(f"{{title: De Música Ligera}}\n{{artist: Soda Stereo}}\n[G]Otra versión {tab}\n")
    (folder / page).write_text(html, encoding="utf-8")
    _note_written(conn, song.id, page, html.encode("utf-8"))


def versioned_song(conn, cfg):
    """De Música Ligera, its sheet (Ver 1) and three more of UG's chords versions: Ver 2, kept beside it; Ver 3,
    not kept; Ver 4, gone from UG."""
    song = rendered_song(conn, cfg)
    sheet_vid = conn.execute("SELECT version_id FROM files WHERE song_id = ? AND name = 'sheet.txt'",
                             (song.id,)).fetchone()[0]
    set_coverage(conn, sheet_vid, 0.95)
    kept = chords(conn, song, KEPT, rating=4.85, votes=12629, number=2, coverage=0.9,
                  note="the version they play\n  live in 2007")
    chords(conn, song, OTHER, rating=4.86, votes=408, number=3)
    mark_gone(conn, chords(conn, song, GONE, rating=4.0, votes=3, number=4))
    keep_version(conn, cfg, song, kept, KEPT)
    return song


def versions_url(tab=KEPT, do="choose", sheet=SHEET, extra=""):
    return "/versions?" + urlencode([("sheet", sheet), ("tab", tab), ("do", do)]) + extra


# --- a kept version's page -------------------------------------------------------------------


def test_a_kept_versions_page_is_served_as_a_viewer_in_its_sandbox(app, conn, cfg):
    song = versioned_song(conn, cfg)
    address = "/" + quote(f"{FOLDER}/version-{KEPT}.html")
    response = get(app, address)
    assert response.status == 200
    assert response.body == (song_dir(cfg.library_dir, song) / f"version-{KEPT}.html").read_bytes()
    own = META_POLICY.search(text(response)).group(1)
    assert [v for k, v in response.headers if k.lower() == "content-security-policy"] == [
        f"sandbox allow-scripts allow-downloads; {own}; frame-ancestors 'none'"]
    assert header(response, "content-type") == "text/html; charset=utf-8"
    assert header(response, "x-frame-options") == "DENY"


def test_a_version_page_is_served_only_while_it_holds_what_caracole_wrote(app, conn, cfg):
    song = versioned_song(conn, cfg)
    folder = song_dir(cfg.library_dir, song)
    page = (folder / f"version-{KEPT}.html").read_bytes()
    # caracole's own bytes, at names it never wrote here or never writes at all
    for name in (f"version-{OTHER}.html", "version-.html", f"version-{KEPT}.htm", f"Version-{KEPT}.html",
                 f"version-{KEPT}.txt.html", "version-1a.html"):
        (folder / name).write_bytes(page)
        response = get(app, "/" + quote(f"{FOLDER}/{name}"))
        assert response.status == 404 and b"<script" not in response.body, name
    (folder / f"version-{KEPT}.html").write_bytes(page + b"<script>fetch('/caracole.sqlite')</script>")
    edited = get(app, "/" + quote(f"{FOLDER}/version-{KEPT}.html"))
    assert edited.status == 404 and b"<script" not in edited.body
    assert "This version's viewer isn't the page caracole last wrote here" in shown(edited)
    assert "the next caracole render writes it again" in shown(edited)
    assert get(app, "/" + quote(SHEET)).status == 200


def test_a_version_page_of_a_folder_no_song_has_is_not_served(app, conn, cfg):
    song = versioned_song(conn, cfg)
    page = (song_dir(cfg.library_dir, song) / f"version-{KEPT}.html").read_bytes()
    stranger = cfg.library_dir / "Unknown Artist" / "Unknown Song"
    stranger.mkdir(parents=True)
    (stranger / f"version-{KEPT}.html").write_bytes(page)
    assert get(app, "/" + quote(f"Unknown Artist/Unknown Song/version-{KEPT}.html")).status == 404


# --- the versions page -----------------------------------------------------------------------


def test_the_versions_page_names_the_version_and_offers_the_one_form(app, conn, cfg):
    versioned_song(conn, cfg)
    page = get(app, versions_url(OTHER, "choose"))
    assert page.status == 200
    body = shown(page)
    assert DISPLAY in body and "Ver 3 of 4 · 4.86★ (408)" in body
    assert "The one now: Ver 1 · 4.5★ (10)" in body
    assert text(page).count("<form") == 1 and 'action="/versions/choose"' in text(page)
    assert ">Make this the one<" in text(page)
    for name, value in (("csrf", "tok"), ("sheet", SHEET), ("tab", OTHER)):
        assert f'name="{name}" value="{value}"' in text(page), name
    assert f'href="/{quote(SHEET)}"' in text(page)  # back to the sheet it came from
    csp = header(page, "content-security-policy")
    assert "default-src 'none'" in csp and "script-src" not in csp and "sandbox" not in csp
    assert "<script" not in text(page)


def test_the_tabbers_note_shows_with_its_version(app, conn, cfg):
    versioned_song(conn, cfg)
    body = shown(get(app, versions_url(KEPT, "choose")))
    assert "Ver 2 of 4 · 4.85★ (12,629)" in body and "the version they play live in 2007" in body


def test_the_page_may_come_from_a_kept_versions_own_page(app, conn, cfg):
    versioned_song(conn, cfg)
    page = get(app, versions_url(KEPT, "choose", sheet=f"{FOLDER}/version-{KEPT}.html"))
    assert page.status == 200 and 'action="/versions/choose"' in text(page)
    assert f'href="/{quote(f"{FOLDER}/version-{KEPT}.html")}"' in text(page)


def test_make_this_the_one_looks_the_song_up_with_that_tab(app, queue, recorder, conn, cfg):
    versioned_song(conn, cfg)
    made = post(app, "/versions/choose", {"sheet": SHEET, "tab": KEPT})
    assert made.status == 303
    where = header(made, "location")
    assert where.startswith("/versions?") and "job=" in where and "do=choose" in where
    assert "Queued" in shown(get(app, where))
    assert 'http-equiv="refresh"' in text(get(app, where))
    from caracole.get import STAGES

    assert [stage.name for stage in queue.job(1).stages] == [name for name, _ in STAGES]  # it runs a lookup
    queue.run_pending()
    # caracole versions --choose: caracole get --tab with the tab's own page, recorded under [pin]
    assert recorder.calls == [["versions", f"--choose={KEPT}", "--progress", "--", "Soda Stereo",
                               "De Música Ligera"]]
    done = get(app, where)
    assert 'http-equiv="refresh"' not in text(done)
    assert "it is the one now" not in shown(done)  # the fake command changed nothing: the page says so
    assert "Done, but it isn't the one" in shown(done) and 'href="/#tab=requests&amp;job=1"' in text(done)


def test_make_this_the_one_says_its_the_one_only_once_the_sheet_is_that_version(app, queue, recorder, conn, cfg):
    # caracole get exits 0 on a block, a spent budget or the hour's cap: the job is done, the sheet as it was. The
    # page reads the song's state, never the command's exit: the pin recorded but not fetched yet, then fetched.
    from caracole.overrides import add_pin

    song = versioned_song(conn, cfg)
    where = header(post(app, "/versions/choose", {"sheet": SHEET, "tab": OTHER}), "location")
    queue.run_pending()
    add_pin(cfg.overrides_file, DISPLAY, [SLUGGED.format(OTHER)])  # what get --tab writes before it fetches
    waits = shown(get(app, where))
    assert "it is the one now" not in waits and "The one now: Ver 1 · 4.5★ (10)" in waits
    assert "recorded under [pin] in overrides.toml" in waits and "the nightly run" in waits
    assert 'href="/#tab=requests&amp;job=1"' in text(get(app, where))
    other = chords(conn, song, OTHER, rating=4.86, votes=408, number=3)
    keep_file(conn, cfg.library_dir, song=song, version_id=other, name="sheet.txt", data=b"[G]Otra\n", rank=1)
    done = get(app, where)
    assert "Done: it is the one now." in shown(done) and "The one now: Ver 3 · 4.86★ (408)" in shown(done)
    assert f'href="/{quote(SHEET)}"' in text(done) and "Open the sheet" in shown(done)
    assert "<form" not in text(done)


def test_keep_it_fetches_that_version_and_keeps_it_beside_the_sheet(app, queue, recorder, conn, cfg):
    song = versioned_song(conn, cfg)
    page = get(app, versions_url(OTHER, "keep"))
    assert page.status == 200 and 'action="/versions/keep"' in text(page) and ">Keep it<" in text(page)
    where = header(post(app, "/versions/keep", {"sheet": SHEET, "tab": OTHER}), "location")
    queue.run_pending()
    assert recorder.calls == [["versions", f"--keep={OTHER}", "--progress", "--", *NAMES]]
    done = get(app, where)
    assert "Done, but it wasn't kept" in shown(done)  # the fake command kept nothing
    keep_version(conn, cfg, song, chords(conn, song, OTHER, rating=4.86, votes=408, number=3), OTHER, rank=3)
    done = get(app, where)
    assert f'href="/{quote(f"{FOLDER}/version-{OTHER}.html")}"' in text(done) and "Open it" in shown(done)


@pytest.mark.parametrize("do,form", [("keep", {"tab": OTHER}), ("choose", {"tab": KEPT}), ("clear", {})])
def test_a_version_cancelled_on_the_requests_page_says_so_and_waits_no_more(app, queue, recorder, conn, cfg, do,
                                                                             form):
    versioned_song(conn, cfg)
    if do == "clear":
        cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
        cfg.overrides_file.write_text(f'[pin]\n"{DISPLAY}" = ["{SLUGGED.format(KEPT)}"]\n', encoding="utf-8")
    where = header(post(app, f"/versions/{do}", {"sheet": SHEET} | form), "location")
    job = re.search(r"job=(\d+)", where).group(1)
    ran = list(recorder.calls)
    assert post(app, "/jobs/cancel", {"job": job}).status == 303
    page = get(app, where)
    assert "Cancelled before it ran." in shown(page), shown(page)
    assert 'http-equiv="refresh"' not in text(page)
    assert not any(running in shown(page) for running in ("Making it the one", "Fetching the version", "Going back"))
    queue.run_pending()
    assert recorder.calls == ran


def test_back_to_caracoles_pick_takes_the_pin_out(app, queue, recorder, conn, cfg):
    versioned_song(conn, cfg)
    page = get(app, versions_url("", "clear"))
    assert page.status == 200 and "<form" not in text(page)  # no pin: caracole picks the sheet already
    assert "caracole picks" in shown(page)
    assert post(app, "/versions/clear", {"sheet": SHEET}).status == 409
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(f'[pin]\n"{DISPLAY}" = ["{SLUGGED.format(KEPT)}"]\n', encoding="utf-8")
    page = get(app, versions_url("", "clear"))
    assert 'action="/versions/clear"' in text(page) and ">Back to caracole's pick<" in text(page)
    where = header(post(app, "/versions/clear", {"sheet": SHEET}), "location")
    queue.run_pending()
    assert recorder.calls == [["versions", "--clear", "--progress", "--", *NAMES]]
    # the fake command took nothing out: the pin is still there, and the page says so
    assert "caracole picks the sheet again" not in shown(get(app, where))
    assert "Done, but the [pin] is still there" in shown(get(app, where))
    cfg.overrides_file.write_text("", encoding="utf-8")
    assert "Done: caracole picks the sheet again." in shown(get(app, where))


def test_only_a_chords_pin_is_one_to_go_back_from(app, conn, cfg):
    # A text tab pinned chooses no sheet: caracole versions --clear leaves it, so the page offers nothing.
    song = versioned_song(conn, cfg)
    upsert_version(conn, provider="ug", tab_id="301", song_id=song.id, slot="guitar", kind="tabs", rating=4.0,
                   votes=9, version=1, label=None, url=SLUGGED.format(301).replace("chords", "tabs"),
                   raw={"id": 301}, now=FETCHED)
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(f'[pin]\n"{DISPLAY}" = ["{SLUGGED.format(301).replace("chords", "tabs")}"]\n',
                                  encoding="utf-8")
    page = get(app, versions_url("", "clear"))
    assert "<form" not in text(page) and "caracole picks" in shown(page)
    assert post(app, "/versions/clear", {"sheet": SHEET}).status == 409


def test_a_blocked_version_is_neither_made_the_one_nor_kept(app, queue, conn, cfg):
    from caracole.overrides import add_block

    versioned_song(conn, cfg)
    add_block(cfg.overrides_file, int(OTHER))
    for do in ("choose", "keep"):
        page = get(app, versions_url(OTHER, do))
        assert page.status == 200 and "<form" not in text(page) and "[block]" in shown(page), do
        assert post(app, f"/versions/{do}", {"sheet": SHEET, "tab": OTHER}).status == 409, do
    assert queue.active_count() == 0


def test_a_post_from_the_pages_script_is_answered_with_its_job(app, queue, conn, cfg):
    versioned_song(conn, cfg)
    response = post(app, "/versions/keep", {"sheet": SHEET, "tab": OTHER}, accept=JSON)
    assert response.status == 200
    import json

    job = json.loads(response.body)["job"]
    assert job["display"] == DISPLAY and job["state"] == "queued"


@pytest.mark.parametrize("path", ["/versions/choose", "/versions/keep", "/versions/clear"])
def test_each_post_needs_the_form_token_and_the_same_origin(app, queue, recorder, conn, cfg, path):
    from caracole.web.app import Request

    versioned_song(conn, cfg)
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(f'[pin]\n"{DISPLAY}" = ["{SLUGGED.format(KEPT)}"]\n', encoding="utf-8")
    form = {"sheet": SHEET, "tab": OTHER}
    assert post(app, path, form, csrf="wrong").status == 403
    assert post(app, path, form, csrf=None).status == 403
    assert post(app, path, form, **{"sec-fetch-site": "cross-site", "origin": "http://evil.example"}).status == 403
    sent = {"host": HOST, "content-type": "text/plain", "sec-fetch-site": "same-origin", "origin": f"http://{HOST}"}
    assert app.handle(Request("POST", path, sent, b"csrf=tok")).status == 415
    queue.run_pending()
    assert recorder.calls == []


def test_what_cant_be_done_is_refused_before_anything_is_queued(app, queue, recorder, conn, cfg):
    versioned_song(conn, cfg)
    sheet_tab = conn.execute("SELECT v.tab_id FROM files f JOIN versions v ON v.id = f.version_id "
                             "WHERE f.name = 'sheet.txt'").fetchone()[0]
    cases = [
        ("choose", sheet_tab, 409),  # the one already
        ("keep", sheet_tab, 409),
        ("keep", KEPT, 409),  # kept already
        ("choose", GONE, 409), ("keep", GONE, 409),  # UG no longer has it
        ("choose", "424242", 404),  # not one of the song's versions
        ("choose", "", 400), ("keep", "12a", 400),
    ]
    for do, tab, status in cases:
        assert post(app, f"/versions/{do}", {"sheet": SHEET, "tab": tab}).status == status, (do, tab)
        assert get(app, versions_url(tab, do)).status == (status if status != 409 else 200), (do, tab)
    assert get(app, versions_url(KEPT, "nothing")).status == 400
    for sheet in ("Nobody/Nothing/sheet.html", f"{FOLDER}/sheet.pdf", "../sheet.html", "", f"{FOLDER}/notes.html",
                  f"{FOLDER}/version-{OTHER}.html"):
        assert post(app, "/versions/choose", {"sheet": sheet, "tab": OTHER}).status == 404, sheet
        assert get(app, versions_url(OTHER, "choose", sheet=sheet)).status == 404, sheet
    assert get(app, versions_url(extra="&job=abc")).status == 400
    queue.run_pending()
    assert recorder.calls == []


def test_the_page_of_a_version_that_cant_be_done_says_why_and_offers_no_form(app, conn, cfg):
    versioned_song(conn, cfg)
    kept = get(app, versions_url(KEPT, "keep"))
    assert "<form" not in text(kept) and "kept already" in shown(kept)
    assert f'href="/{quote(f"{FOLDER}/version-{KEPT}.html")}"' in text(kept)
    gone = get(app, versions_url(GONE, "choose"))
    assert "<form" not in text(gone) and "no longer has" in shown(gone)


def test_an_ignored_song_has_nothing_to_choose(app, queue, conn, cfg):
    from caracole.overrides import add_ignore

    versioned_song(conn, cfg)
    add_ignore(cfg.overrides_file, DISPLAY)
    assert post(app, "/versions/choose", {"sheet": SHEET, "tab": OTHER}).status == 409
    assert queue.active_count() == 0


def test_a_job_of_another_version_is_not_shown_here(app, conn, cfg):
    versioned_song(conn, cfg)
    where = header(post(app, "/versions/keep", {"sheet": SHEET, "tab": OTHER}), "location")
    job = re.search(r"job=(\d+)", where).group(1)
    other = get(app, versions_url(KEPT, "choose", extra=f"&job={job}"))
    assert other.status == 200 and "Queued" not in shown(other)


# --- the song's jobs ---------------------------------------------------------------------------


def test_two_versions_kept_are_two_commands_and_the_same_one_twice_is_one(app, queue, recorder, conn, cfg):
    song = versioned_song(conn, cfg)
    third = "5555"
    chords(conn, song, third, rating=3.0, votes=2, number=5)
    first = post(app, "/versions/keep", {"sheet": SHEET, "tab": OTHER})
    again = post(app, "/versions/keep", {"sheet": SHEET, "tab": OTHER})
    assert header(first, "location") == header(again, "location")  # the same job
    post(app, "/versions/keep", {"sheet": SHEET, "tab": third})
    queue.run_pending()
    assert recorder.calls == [["versions", f"--keep={OTHER}", "--progress", "--", *NAMES],
                              ["versions", f"--keep={third}", "--progress", "--", *NAMES]]


def test_a_version_asked_for_while_the_songs_lookup_waits_joins_it(app, queue, recorder, conn, cfg):
    # The song's own job, as a lookup's: Keep it goes after the lookup waiting, and Make this the one, which runs a
    # lookup with that tab, takes the lookup's place, as a tab picked on the lookup page does.
    song = versioned_song(conn, cfg)
    assert post(app, "/fetch", {"song": str(song.id)}).status == 303  # the card's Fetch now: a lookup waits
    keep = header(post(app, "/versions/keep", {"sheet": SHEET, "tab": OTHER}), "location")
    choose = header(post(app, "/versions/choose", {"sheet": SHEET, "tab": KEPT}), "location")
    assert re.search(r"job=(\d+)", keep).group(1) == re.search(r"job=(\d+)", choose).group(1) == "1"
    assert queue.active_count() == 1
    queue.run_pending()
    assert [call[:3] for call in recorder.calls] == [["versions", f"--keep={OTHER}", "--progress"],
                                                     ["versions", f"--choose={KEPT}", "--progress"]]


def test_fetch_now_asked_for_while_keep_it_waits_still_looks_the_song_up(app, queue, recorder, conn, cfg):
    # Keep it asks UG for one tab page, and never looks the song up: a Fetch now joins it, never vanishes into it.
    song = versioned_song(conn, cfg)
    keep = header(post(app, "/versions/keep", {"sheet": SHEET, "tab": OTHER}), "location")
    fetch = header(post(app, "/fetch", {"song": str(song.id)}), "location")
    assert re.search(r"job=(\d+)", keep).group(1) == re.search(r"job=(\d+)", fetch).group(1) == "1"
    queue.run_pending()
    assert recorder.calls == [["versions", f"--keep={OTHER}", "--progress", "--", *NAMES],
                              ["get", "--progress", "--", *NAMES]]


def test_a_versions_progress_is_its_jobs_stages_as_a_lookups_is(conn, cfg):
    # caracole versions --progress writes caracole get's lines: Keep it's stages (the song, the version, its page,
    # the library page) and Back to caracole's pick's, a lookup's, are the job's, and stay out of its output.
    from caracole.get import progress_line
    from caracole.web.jobs import JobQueue
    from caracole.web.status import job_line

    seen = {}

    def runner(args, emit):
        if args[0] == "versions" and args[1].startswith("--keep="):
            emit(progress_line({"stage": "song", "state": "done", "detail": "in the library"}))
            emit(progress_line({"stage": "version", "state": "running", "detail": ""}))
            seen["keep"] = (queue.job(1).stages, job_line(queue.job(1), None))
            emit(progress_line({"stage": "version", "state": "skipped", "detail": "budget spent; nothing kept"}))
        else:
            emit(progress_line({"stage": "sheet", "state": "running", "detail": ""}))
            seen["clear"] = job_line(queue.job(2), None)
        emit("Took tab 1 out of [pin]")
        return 0

    from caracole.web.app import WebApp

    queue = JobQueue(runner, limit=5)
    app = WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")
    song = versioned_song(conn, cfg)
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(f'[pin]\n"{DISPLAY}" = ["{SLUGGED.format(KEPT)}"]\n', encoding="utf-8")
    where = header(post(app, "/versions/keep", {"sheet": SHEET, "tab": OTHER}), "location")
    assert song.key in queue.fetching_keys()  # it asks Ultimate Guitar for a page
    queue.run_pending()
    post(app, "/versions/clear", {"sheet": SHEET})
    queue.run_pending()
    stages, line = seen["keep"]
    assert [(s.name, s.state) for s in stages][:2] == [("song", "done"), ("version", "running")]
    assert line.text == "Fetching the version from Ultimate Guitar…"
    assert seen["clear"].text == "Fetching from Ultimate Guitar…"
    kept = queue.job(1)
    assert next(s for s in kept.stages if s.name == "version").detail == "budget spent; nothing kept"
    assert kept.steps[0].output == ["Took tab 1 out of [pin]"]  # progress lines are data, not output
    assert "Done, but it wasn't kept: budget spent; nothing kept. See the request's output" in shown(get(app, where))


# --- posts by song, from the library page's card -----------------------------------------------


def test_keep_more_queues_one_job_under_the_songs_key(app, queue, recorder, conn, cfg):
    song = versioned_song(conn, cfg)
    first = post(app, "/versions/keep-more", {"song": str(song.id)})
    again = post(app, "/versions/keep-more", {"song": str(song.id)})
    assert first.status == again.status == 303
    assert header(first, "location") == header(again, "location") == f"/{details_href(1)}" == "/#tab=requests&job=1"  # one job
    assert queue.active_count() == 1 and song.key in queue.fetching_keys()  # it asks Ultimate Guitar for pages
    job = queue.job(1)
    assert job.song_key == song.key and job.title == f"Fetch the other versions of {DISPLAY}"
    assert [step.label for step in job.steps] == ["Fetching versions from Ultimate Guitar"]
    assert [stage.name for stage in job.stages] == ["song", "version", "pdf", "pages"]
    queue.run_pending()
    assert recorder.calls == [["versions", "--keep-more", "--progress", "--", *NAMES]]


def test_keep_more_is_answered_to_the_pages_script_with_its_job(app, queue, conn, cfg):
    import json

    song = versioned_song(conn, cfg)
    response = post(app, "/versions/keep-more", {"song": str(song.id)}, accept=JSON)
    assert response.status == 200
    job = json.loads(response.body)["job"]
    assert job["display"] == DISPLAY and job["state"] == "queued"


def test_keep_more_is_refused_with_nothing_left_to_keep(app, queue, conn, cfg):
    from caracole.sheet_versions import note_unkeepable

    song = versioned_song(conn, cfg)
    note_unkeepable(conn, song.id, OTHER)  # the one left: a keep found it can't keep it
    refused = post(app, "/versions/keep-more", {"song": str(song.id)})
    assert refused.status == 409 and "Nothing is left to keep" in shown(refused)
    assert queue.active_count() == 0


def test_keep_more_is_refused_for_an_ignored_song(app, queue, conn, cfg):
    from caracole.overrides import add_ignore

    song = versioned_song(conn, cfg)
    add_ignore(cfg.overrides_file, DISPLAY)
    assert post(app, "/versions/keep-more", {"song": str(song.id)}).status == 409
    assert queue.active_count() == 0


def test_keep_more_joins_a_waiting_lookup_and_a_lookup_joins_it(app, queue, recorder, conn, cfg):
    # It never looks the song up, as Keep it never does: neither vanishes into the other.
    song = versioned_song(conn, cfg)
    assert post(app, "/fetch", {"song": str(song.id)}).status == 303
    post(app, "/versions/keep-more", {"song": str(song.id)})
    assert queue.active_count() == 1
    queue.run_pending()
    assert recorder.calls == [["get", "--progress", "--", *NAMES], ["versions", "--keep-more", "--progress", "--",
                                                                    *NAMES]]
    recorder.calls.clear()
    post(app, "/versions/keep-more", {"song": str(song.id)})
    post(app, "/fetch", {"song": str(song.id)})
    queue.run_pending()
    assert recorder.calls == [["versions", "--keep-more", "--progress", "--", *NAMES],
                              ["get", "--progress", "--", *NAMES]]


@pytest.mark.parametrize("do,fields", [("choose", {"tab": OTHER}), ("keep", {"tab": OTHER}), ("clear", {})])
def test_a_post_by_song_id_queues_what_the_post_by_sheet_does(app, queue, recorder, conn, cfg, do, fields):
    song = versioned_song(conn, cfg)
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(f'[pin]\n"{DISPLAY}" = ["{SLUGGED.format(KEPT)}"]\n', encoding="utf-8")
    by_sheet = post(app, f"/versions/{do}", {"sheet": SHEET} | fields)
    queue.run_pending()
    by_song = post(app, f"/versions/{do}", {"song": str(song.id)} | fields)
    assert by_song.status == 303 and header(by_song, "location") == f"/{details_href(2)}"
    assert header(by_sheet, "location").startswith("/versions?")  # the versions page, as before
    queue.run_pending()
    assert len(recorder.calls) == 2 and recorder.calls[0] == recorder.calls[1]
    assert queue.job(2).title == queue.job(1).title


def test_a_post_by_song_id_is_refused_as_one_by_sheet_is(app, queue, conn, cfg):
    song = versioned_song(conn, cfg)
    sheet_tab = conn.execute("SELECT v.tab_id FROM files f JOIN versions v ON v.id = f.version_id "
                             "WHERE f.name = 'sheet.txt'").fetchone()[0]
    cases = [
        ("choose", {"song": str(song.id), "tab": sheet_tab}, 409),  # the one already
        ("keep", {"song": str(song.id), "tab": KEPT}, 409),  # kept already
        ("choose", {"song": str(song.id), "tab": GONE}, 409),
        ("clear", {"song": str(song.id)}, 409),  # no pin
        ("choose", {"song": str(song.id), "tab": "424242"}, 404),
        ("choose", {"song": str(song.id), "tab": ""}, 400),
        ("choose", {"song": "999", "tab": OTHER}, 404),  # no such song
        ("keep-more", {"song": "999"}, 404),
        ("keep-more", {"song": "one"}, 400),
        ("keep-more", {}, 404),  # names no song, nor a sheet
    ]
    for do, fields, status in cases:
        assert post(app, f"/versions/{do}", fields).status == status, (do, fields)
    assert queue.active_count() == 0


@pytest.mark.parametrize("path", ["/versions/choose", "/versions/keep", "/versions/clear", "/versions/keep-more"])
def test_a_post_by_song_id_needs_the_form_token_and_the_same_origin(app, queue, recorder, conn, cfg, path):
    from caracole.web.app import Request

    song = versioned_song(conn, cfg)
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(f'[pin]\n"{DISPLAY}" = ["{SLUGGED.format(KEPT)}"]\n', encoding="utf-8")
    form = {"song": str(song.id), "tab": OTHER}
    assert post(app, path, form, csrf="wrong").status == 403
    assert post(app, path, form, csrf=None).status == 403
    assert post(app, path, form, **{"sec-fetch-site": "cross-site", "origin": "http://evil.example"}).status == 403
    sent = {"host": HOST, "content-type": "text/plain", "sec-fetch-site": "same-origin", "origin": f"http://{HOST}"}
    assert app.handle(Request("POST", path, sent, f"csrf=tok&song={song.id}".encode())).status == 415
    queue.run_pending()
    assert recorder.calls == []


def test_keep_more_has_no_page_of_its_own(app, conn, cfg):
    # The library page's card posts it: the viewer's versions page offers the three it always did.
    versioned_song(conn, cfg)
    assert get(app, versions_url(OTHER, "keep-more")).status == 400


# --- an export from a version page -------------------------------------------------------------


def test_an_export_from_a_kept_versions_page_is_refused_and_says_what_to_do(app, queue, conn, cfg, monkeypatch):
    from caracole import render

    real = render.version_pdf
    monkeypatch.setattr(render, "version_pdf", lambda *a, **k: real(*a, runner=fake_chordpro, **k))
    versioned_song(conn, cfg)
    page = f"{FOLDER}/version-{KEPT}.html"
    refused = get(app, f"/export.pdf?sheet={quote(page)}&t=2")
    assert refused.status == 409 and "make this version the one first" in shown(refused)
    assert get(app, f"/export.pdf?sheet={quote(page)}&t=2&mine=1").status == 409
    assert get(app, f"/export.pdf?sheet={quote(SHEET)}&t=2").status == 200
    assert queue.active_count() == 0


def test_the_commands_queued_are_ones_caracole_versions_reads(app, queue, recorder, conn, cfg, monkeypatch, tmp_path):
    # The queue runs them as typed: the real command line must read each as the version kept, or the pin taken out.
    from typer.testing import CliRunner

    from caracole import versions_cmd
    from caracole.cli import build_app
    from caracole.overrides import add_pin

    song = versioned_song(conn, cfg)
    add_pin(cfg.overrides_file, DISPLAY, [SLUGGED.format(KEPT)])
    post(app, "/versions/keep", {"sheet": SHEET, "tab": OTHER})
    post(app, "/versions/clear", {"sheet": SHEET})
    queue.run_pending()
    post(app, "/versions/keep-more", {"song": str(song.id)})
    queue.run_pending()
    heard = []
    monkeypatch.setattr(versions_cmd, "keep", lambda cfg, display, tab, *, progress: heard.append(("keep", display, tab, progress)))
    monkeypatch.setattr(versions_cmd, "clear", lambda cfg, display, *, progress: heard.append(("clear", display, progress)))
    monkeypatch.setattr(versions_cmd, "keep_more",
                        lambda cfg, display, *, progress: heard.append(("keep-more", display, progress)))
    config = tmp_path / "caracole.toml"
    config.write_text(f'library_dir = "{cfg.library_dir}"\n', encoding="utf-8")
    for args in recorder.calls:
        result = CliRunner().invoke(build_app(), ["--config", str(config), *args])
        assert result.exit_code == 0, (args, result.output)
    assert heard == [("keep", DISPLAY, int(OTHER), True), ("clear", DISPLAY, True), ("keep-more", DISPLAY, True)]
