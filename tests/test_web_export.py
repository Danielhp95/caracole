"""caracole serve's export page: a sheet's PDF in the version the viewer was left in."""

import re
from html import unescape
from urllib.parse import quote

import pytest

from caracole.overrides import Overrides
from caracole.render import render_version
from caracole.songs import get_song
from caracole.viewer.version import version_from_query
from caracole.web.app import Request, WebApp
from caracole.web.jobs import JobQueue

from helpers.rendered import fake_chordpro, rendered_song
from test_web_app import ALLOWED, HOST, Recorder, get, header, post, text

SHEET = "Soda Stereo/De Música Ligera/sheet.html"
QUERY = "t=2&capo=0"


@pytest.fixture
def recorder():
    return Recorder()


@pytest.fixture
def queue(recorder):
    return JobQueue(recorder, limit=3)


@pytest.fixture
def app(cfg, queue):
    return WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")


def export_url(sheet=SHEET, query=QUERY, extra=""):
    return f"/export?sheet={quote(sheet)}&{query}{extra}"


def shown(response):
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", text(response))).split())


def test_the_export_page_names_the_version_and_makes_its_pdf(app, queue, recorder, conn, cfg):
    song = rendered_song(conn, cfg)
    page = get(app, export_url())
    assert page.status == 200
    body = shown(page)
    assert "Soda Stereo - De Música Ligera" in body and "A Major, capo 0" in body
    assert 'action="/export"' in text(page) and ">Make PDF<" in text(page)
    assert "Open the PDF" not in body  # nothing made yet
    # "Back to the sheet" is the viewer's address with the same hash.
    assert f'href="/{quote(SHEET)}#{QUERY.replace("&", "&amp;")}"' in text(page)

    made = post(app, "/export", {"sheet": SHEET, "v": QUERY})
    assert made.status == 303
    where = header(made, "location")
    assert where.startswith("/export?sheet=") and "job=" in where
    assert "Queued" in shown(get(app, where))
    queue.run_pending()
    assert recorder.calls == [["render", f"--song={song.display}", "--version=t=2&capo=0"]]

    done = get(app, where)  # the job ran, but the fake command made no PDF
    assert "Done" in shown(done) and "Open the PDF" not in shown(done)
    render_version(conn, cfg, Overrides(), get_song(conn, song.id), version_from_query(QUERY), runner=fake_chordpro)
    done = get(app, where)
    name = "sheet (A Major, capo 0).pdf"
    assert f'href="/{quote("Soda Stereo/De Música Ligera/" + name)}"' in text(done)
    assert "Open the PDF" in shown(done) and "Back to the sheet" in shown(done)
    assert get(app, "/" + quote("Soda Stereo/De Música Ligera/" + name)).status == 200


def test_a_failed_job_says_so_and_a_running_one_refreshes_the_page(app, queue, conn, cfg):
    rendered_song(conn, cfg)
    where = header(post(app, "/export", {"sheet": SHEET, "v": QUERY}), "location")
    assert 'http-equiv="refresh"' in text(get(app, where))
    queue._runner = lambda args, emit: (emit("no export: no font"), 1)[1]
    queue.run_pending()
    page = get(app, where)
    assert "Failed" in shown(page) and "no export: no font" in shown(page)
    assert 'http-equiv="refresh"' not in text(page)


def test_the_export_post_needs_the_form_token_and_the_same_origin(app, queue, recorder, conn, cfg):
    rendered_song(conn, cfg)
    form = {"sheet": SHEET, "v": QUERY}
    assert post(app, "/export", form, csrf="wrong").status == 403
    assert post(app, "/export", form, csrf=None).status == 403
    assert post(app, "/export", form, **{"sec-fetch-site": "cross-site", "origin": "http://evil.example"}).status == 403
    sent = {"host": HOST, "content-type": "text/plain", "sec-fetch-site": "same-origin", "origin": f"http://{HOST}"}
    assert app.handle(Request("POST", "/export", sent, b"csrf=tok")).status == 415
    queue.run_pending()
    assert recorder.calls == []


def test_an_unknown_sheet_or_a_bad_version_is_refused(app, queue, conn, cfg):
    rendered_song(conn, cfg)
    for sheet in ("Nobody/Nothing/sheet.html", "Soda Stereo/De Música Ligera/sheet.pdf", "../sheet.html", ""):
        assert get(app, export_url(sheet)).status == 404, sheet
        assert post(app, "/export", {"sheet": sheet, "v": QUERY}).status == 404, sheet
    assert get(app, "/export?t=2").status == 404  # no sheet at all
    for bad in ("t=2&" + "x" * 5000, "t=2\x00", "t=%ff%fe"):
        assert get(app, export_url(query=quote(bad, safe="=&%"))).status == 400, bad
        assert post(app, "/export", {"sheet": SHEET, "v": bad}).status == 400, bad
    assert get(app, export_url(extra="&job=abc")).status == 400
    assert queue.active_count() == 0


def test_a_job_of_another_export_is_not_shown_here(app, conn, cfg):
    rendered_song(conn, cfg)
    where = header(post(app, "/export", {"sheet": SHEET, "v": QUERY}), "location")
    job = re.search(r"job=(\d+)", where).group(1)
    other = get(app, export_url(query="t=3&capo=0", extra=f"&job={job}"))
    assert other.status == 200 and "Queued" not in shown(other)


def test_the_export_page_is_served_in_a_sandbox_free_page_of_its_own(app, conn, cfg):
    rendered_song(conn, cfg)
    page = get(app, export_url())
    csp = header(page, "content-security-policy")
    assert "default-src 'none'" in csp and "script-src" not in csp and "sandbox" not in csp


def test_make_this_my_version_saves_it_and_renders_the_song(app, queue, recorder, conn, cfg):
    song = rendered_song(conn, cfg)
    page = text(get(app, export_url()))
    assert ">Make this my version<" in page  # a form of its own, the same version, the same token
    assert "It is your version" in shown(get(app, export_url(query="t=0")))  # as written: where it plays now
    made = post(app, "/export", {"sheet": SHEET, "v": QUERY, "mine": "1"})
    assert made.status == 303
    where = header(made, "location")
    assert "Queued" in shown(get(app, where))
    queue.run_pending()
    # overrides.toml is written by the command, which holds caracole's lock: never by the server
    assert recorder.calls == [["render", f"--song={song.display}", "--version=t=2&capo=0", "--mine"]]
    assert not cfg.overrides_file.exists()
    done = get(app, where)
    assert "Done" in shown(done) and "your version" in shown(done)
    assert f'href="/{quote("Soda Stereo/De Música Ligera/sheet.pdf")}"' in text(done)  # the song's own PDF

    # Once it is the song's version, its page says so and offers no other; the sheet's address naming
    # no version is that one too, as the viewer starts in it.
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(f'[version]\n"{song.display}" = "t=2&capo=0"\n', encoding="utf-8")
    page = get(app, export_url())
    assert "It is your version" in shown(page) and ">Make this my version<" not in text(page)
    assert "A Major, capo 0" in shown(get(app, export_url(query="fs=20")))
    assert ">Make this my version<" in text(get(app, export_url(query="t=0")))
