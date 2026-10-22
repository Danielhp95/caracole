"""caracole serve's export page: a sheet's PDF in the version the viewer was left in."""

import re
from html import unescape
from urllib.parse import quote

import pytest

from caracole.library_page import sheet_href
from caracole.overrides import Overrides
from caracole.render import render_version
from caracole.songs import get_song
from caracole.viewer.version import version_from_query
from caracole.web.app import Request, WebApp
from caracole.web.jobs import JobQueue

from helpers.rendered import fake_chordpro, rendered_song
from test_web_app import ALLOWED, HOST, Recorder, answer, get, get_json, header, post, text

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


def test_an_exports_request_says_what_it_made_never_that_a_song_was_added(app, queue, conn, cfg):
    # An export's job has a key of its own, never the song's: its line, in the library page's list of requests and on
    # the requests page, says what it made, and it is no song's request (no songId: the song's line stays its own).
    song = rendered_song(conn, cfg)

    def runner(args, emit):  # `caracole render --song --version`: this export alone makes its PDF here
        if f"--version={QUERY}" in args and "--mine" not in args:
            render_version(conn, cfg, Overrides(), get_song(conn, song.id), version_from_query(QUERY),
                           runner=fake_chordpro)
        return 0

    queue._runner = runner
    post(app, "/export", {"sheet": SHEET, "v": QUERY})
    [queued] = answer(get_json(app, "/jobs.json"))["jobs"]
    assert (queued["kind"], queued["songId"], queued["line"]["text"]) == ("export", None, "Queued…")
    post(app, "/export", {"sheet": SHEET, "v": QUERY, "mine": "1"})
    post(app, "/export", {"sheet": SHEET, "v": "t=4&capo=0"})
    queue.run_pending()
    views = {view["id"]: view for view in answer(get_json(app, "/jobs.json?jobs=1,2,3"))["jobs"]}
    assert {(view["kind"], view["songId"]) for view in views.values()} == {("export", None)}
    pdf = "/".join(quote(part, safe="") for part in ("Soda Stereo", "De Música Ligera", "sheet (A Major, capo 0).pdf"))
    assert views[1]["line"] == {"tone": "ready", "text": "PDF made", "link": {"label": "Open the PDF", "href": pdf},
                                "details": None}
    sheet = sheet_href(cfg.library_dir, get_song(conn, song.id))
    assert views[2]["line"] == {"tone": "ready", "text": "Your version now",
                                "link": {"label": "Open sheet", "href": sheet}, "details": None}
    assert views[3]["line"]["tone"] == "failed" and views[3]["line"]["text"] == "No PDF was found: make it again."
    page = shown(get(app, "/jobs"))
    assert "Added" not in page and "nightly run" not in page
    assert "PDF made" in page and "Your version now" in page and "No PDF was found: make it again." in page
    assert f'href="/{pdf}"' in text(get(app, "/jobs"))


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


def test_the_auto_sheet_beside_a_human_one_is_not_exported(app, queue, recorder, conn, cfg):
    # An export is made from the song's human sheet: asked from the auto sheet's viewer kept beside it, whose
    # chords are another sheet's, it would be the human sheet's PDF with the auto sheet's positions and swaps on
    # its chords, and Make this my version would save them. Refused; an auto sheet alone exports itself.
    song = rendered_song(conn, cfg, "Placeholder Band", "Synthetic Song", auto=True)
    auto = "Placeholder Band/Synthetic Song/sheet (auto).html"
    page = get(app, export_url(auto))
    assert page.status == 200 and "A Major, capo 0" in shown(page)
    keep_human_sheet(conn, cfg, song)
    for form in ({"sheet": auto, "v": QUERY}, {"sheet": auto, "v": QUERY, "mine": "1"}):
        refused = post(app, "/export", form)
        assert refused.status == 409 and "sheet.html" not in shown(refused), form
        assert "auto-chords sheet" in shown(refused)
    assert get(app, export_url(auto)).status == 409
    assert get(app, export_url("Placeholder Band/Synthetic Song/sheet.html")).status == 200
    queue.run_pending()
    assert recorder.calls == []


def keep_human_sheet(conn, cfg, song):
    """Keep a UG sheet beside the song's auto sheet, as the fetch step keeps one that doesn't cover the song
    yet, and render both."""
    import json

    from caracole.library import keep_file, song_dir, write_atomic
    from caracole.render import render_all
    from caracole.ug.page import strip_markup
    from caracole.versions import upsert_version

    from helpers.rendered import FETCHED, SHEET
    from helpers.ug_pages import version_dict

    raw = version_dict(95053, song=song.title, artist=song.artist, tonality_name="G")
    vid = upsert_version(conn, provider="ug", tab_id=str(raw["id"]), song_id=song.id, slot="sheet",
                         kind="chords", rating=4.5, votes=10, version=1, label=None, url=raw["tab_url"],
                         raw=raw, now=FETCHED)
    keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
              data=strip_markup(SHEET).encode("utf-8"), rank=1)
    doc = {"version": raw, "content": SHEET, "url": raw["tab_url"], "meta": []}
    write_atomic(song_dir(cfg.library_dir, song) / "sheet.json", json.dumps(doc, ensure_ascii=False).encode())
    assert render_all(conn, cfg, Overrides(), runner=fake_chordpro).failed == 0
    assert (song_dir(cfg.library_dir, song) / "sheet (auto).html").is_file()


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


def test_a_version_kept_by_its_key_is_the_one_the_song_plays_in(app, conn, cfg):
    # Make this my version keeps the key it plays in: whatever address plays there is the song's own already
    rendered_song(conn, cfg)  # in G
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text('[version]\n"Soda Stereo - De Música Ligera" = "key=A&mode=ionian&capo=0"\n',
                                  encoding="utf-8")
    for query in ("t=2&capo=0", "t=2", "t=2&mode=ionian", "fs=20"):  # the last names no version: the song's own
        page = get(app, export_url(query=query))
        assert "A Major, capo 0" in shown(page), query
        assert "It is your version" in shown(page) and ">Make this my version<" not in text(page), query
    assert ">Make this my version<" in text(get(app, export_url(query="t=0")))
    assert ">Make this my version<" in text(get(app, export_url(query="t=2&capo=2")))  # G shapes at capo 2: A too


def test_a_version_kept_as_a_move_from_the_sheet_may_be_kept_by_its_key(app, queue, recorder, conn, cfg):
    # An entry caracole wrote before it kept a key is a move from the sheet: the page says it is the song's version,
    # and that a sheet in another key would move it, and offers to keep it in the key it plays in now
    song = rendered_song(conn, cfg)  # in G
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(f'[version]\n"{song.display}" = "t=2&capo=0"\n', encoding="utf-8")
    page = get(app, export_url(query="fs=20"))  # naming no version: the song's own
    assert "A Major, capo 0" in shown(page) and "It is your version" in shown(page)
    assert "a sheet in another key in its place would move it" in shown(page)
    assert ">Keep it in this key<" in text(page) and ">Make this my version<" not in text(page)
    made = post(app, "/export", {"sheet": SHEET, "v": QUERY, "mine": "1"})
    assert made.status == 303
    queue.run_pending()
    assert recorder.calls == [["render", f"--song={song.display}", "--version=t=2&capo=0", "--mine"]]
    # Once kept by its key, it is the song's own as it is
    cfg.overrides_file.write_text(f'[version]\n"{song.display}" = "key=A&capo=0"\n', encoding="utf-8")
    page = get(app, export_url(query="fs=20"))
    assert "It is your version" in shown(page) and ">Keep it in this key<" not in text(page)
    # A move that plays the sheet as the song plays without one has no key of its own to keep
    cfg.overrides_file.write_text(f'[version]\n"{song.display}" = "t=0"\n', encoding="utf-8")
    page = get(app, export_url(query="fs=20"))
    assert "It is your version" in shown(page) and ">Keep it in this key<" not in text(page)


def test_a_song_with_braces_in_its_name_opens_its_export_page(app, queue, recorder, conn, cfg):
    # The sheet's path is in the page's forms: a brace in it is text, never a placeholder
    for artist, title in (("Soda {Stereo}", "{Untitled}"), ("Soda}", "De {Música")):
        song = rendered_song(conn, cfg, artist, title)
        sheet = f"{artist}/{title}/sheet.html"
        page = get(app, export_url(sheet=sheet))
        assert page.status == 200, (artist, title)
        assert ">Make this my version<" in text(page)
        assert f'name="sheet" value="{sheet}"' in text(page)
        cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
        cfg.overrides_file.write_text(f'[version]\n"{song.display}" = "t=2&capo=0"\n', encoding="utf-8")
        page = get(app, export_url(sheet=sheet, query="fs=20"))  # kept as a move: the other button
        assert page.status == 200 and ">Keep it in this key<" in text(page), (artist, title)
        cfg.overrides_file.unlink()
