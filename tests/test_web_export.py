"""caracole serve's Export PDF: ``GET /export.pdf``, a sheet's PDF in the version the viewer was left in, downloaded
at once, and with ``mine=1`` Make this my version too."""

import subprocess
import threading
from pathlib import Path
from urllib.parse import quote, unquote

import pytest

from caracole import render
from caracole.library_page import sheet_href
from caracole.web.app import Request, WebApp
from caracole.web.jobs import JobQueue

from helpers.rendered import fake_chordpro, rendered_song
from test_web_app import ALLOWED, HOST, Recorder, answer, get, get_json, header, post, text

SHEET = "Soda Stereo/De Música Ligera/sheet.html"
QUERY = "t=2&capo=0"
NAME = "Soda Stereo - De Música Ligera (A Major, capo 0).pdf"  # the song in G, two up: A shapes, no capo


@pytest.fixture
def recorder():
    return Recorder()


@pytest.fixture
def queue(recorder):
    return JobQueue(recorder, limit=3)


@pytest.fixture
def app(cfg, queue):
    return WebApp(cfg, queue, allowed=ALLOWED, csrf="tok")


@pytest.fixture
def printed(monkeypatch):
    """chordpro, faked: each sheet text it was given, in the order asked, and the folder it was run in."""
    real = render.version_pdf
    seen = []

    def runner(cmd, **kwargs):
        out = Path(next(a.split("=", 1)[1] for a in cmd if a.startswith("--output=")))
        seen.append((Path(cmd[-1]).read_text(encoding="utf-8"), out.parent))
        return fake_chordpro(cmd, **kwargs)

    monkeypatch.setattr(render, "version_pdf", lambda *a, **k: real(*a, **{"runner": runner, **k}))
    return seen


def pdf_url(sheet=SHEET, query=QUERY, extra=""):
    return f"/export.pdf?sheet={quote(sheet)}&{query}{extra}"


def library_files(cfg):
    return {p.relative_to(cfg.library_dir): p.read_bytes() for p in cfg.library_dir.rglob("*") if p.is_file()}


def kv(conn):
    return conn.execute("SELECT key, value FROM kv ORDER BY key").fetchall()


def test_the_pdf_downloads_at_once_named_for_the_song_in_its_version(app, queue, conn, cfg, printed):
    rendered_song(conn, cfg)  # in G
    files, records = library_files(cfg), kv(conn)
    answered = get(app, pdf_url(extra="&fs=20&necks=0"))  # the viewer's address, its reading settings and all
    assert answered.status == 200 and answered.body.startswith(b"%PDF")
    assert header(answered, "content-type") == "application/pdf"
    disposition = header(answered, "content-disposition")
    assert disposition.startswith('attachment; filename="Soda Stereo - De Musica Ligera (A Major, capo 0).pdf"')
    assert unquote(disposition.split("filename*=UTF-8''")[1]) == NAME
    assert header(answered, "cache-control") == "no-store"
    [(cho, folder)] = printed
    assert "[A]" in cho and "[G]" not in cho  # the version, as its export prints it
    assert folder.parent == cfg.cache_dir and not folder.exists()  # a private folder, gone once done
    # Nothing written into the library, nothing recorded, nothing queued, no lock
    assert library_files(cfg) == files and kv(conn) == records
    assert queue.active_count() == 0 and not (cfg.state_dir / "caracole.lock").exists()


def test_an_address_naming_no_version_is_the_songs_own(app, conn, cfg, printed):
    song = rendered_song(conn, cfg)
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(f'[version]\n"{song.display}" = "key=A&capo=0"\n', encoding="utf-8")
    answered = get(app, pdf_url(query="fs=20"))
    assert answered.status == 200 and unquote(header(answered, "content-disposition").split("''")[1]) == NAME
    piano = get(app, pdf_url(query="t=2&capo=0&inst=piano"))  # on the viewer's instrument, named by it
    assert unquote(header(piano, "content-disposition").split("''")[1]) == (
        "Soda Stereo - De Música Ligera (A Major, piano).pdf")


def test_mine_queues_make_this_my_version_and_still_answers_the_pdf(app, queue, recorder, conn, cfg, printed):
    song = rendered_song(conn, cfg)
    answered = get(app, pdf_url(extra="&mine=1"))
    assert answered.status == 200 and answered.body.startswith(b"%PDF")
    assert unquote(header(answered, "content-disposition").split("''")[1]) == NAME
    [queued] = answer(get_json(app, "/jobs.json"))["jobs"]
    assert (queued["kind"], queued["songId"], queued["line"]["text"]) == ("export", None, "Queued…")
    assert not cfg.overrides_file.exists()  # written by the command, under caracole's lock: never by the server
    queue.run_pending()
    assert recorder.calls == [["render", f"--song={song.display}", "--version=t=2&capo=0", "--mine"]]
    [done] = answer(get_json(app, "/jobs.json?jobs=1"))["jobs"]
    assert done["line"] == {"tone": "ready", "text": "Your version now",
                            "link": {"label": "Open sheet", "href": sheet_href(cfg.library_dir, song)}, "details": None}
    assert "Your version now" in text(get(app, "/jobs")) and "Added" not in text(get(app, "/jobs"))


def test_mine_is_a_plain_link_with_no_token_but_the_host_check_still_holds(app, queue, recorder, conn, cfg, printed):
    # The owner's choice: Make this my version is a link a sandboxed viewer follows, so no form token and no
    # cross-origin check (a site could change a song's saved version; nothing is lost, and Reset undoes it). A name
    # the server doesn't answer to (DNS rebinding) is refused as ever.
    rendered_song(conn, cfg)
    elsewhere = get(app, pdf_url(extra="&mine=1"), **{"sec-fetch-site": "cross-site", "origin": "http://evil.example"})
    assert elsewhere.status == 200 and queue.active_count() == 1
    rebound = app.handle(Request("GET", pdf_url(extra="&mine=1"), {"host": "evil.example"}))
    assert rebound.status == 421 and queue.active_count() == 1
    head = app.handle(Request("HEAD", pdf_url(extra="&mine=1"), {"host": HOST}))  # a HEAD changes nothing
    assert head.status == 200 and queue.active_count() == 1


def test_the_export_page_is_gone(app, conn, cfg):
    rendered_song(conn, cfg)
    assert get(app, f"/export?sheet={quote(SHEET)}&{QUERY}").status == 404
    assert post(app, "/export", {"sheet": SHEET, "v": QUERY}).status == 404
    assert post(app, "/export", {"sheet": SHEET, "v": QUERY, "mine": "1"}).status == 404


def test_an_unknown_sheet_or_a_bad_version_is_refused(app, queue, conn, cfg, printed):
    rendered_song(conn, cfg)
    for sheet in ("Nobody/Nothing/sheet.html", "Soda Stereo/De Música Ligera/sheet.pdf", "../sheet.html", "",
                  "Soda Stereo/De Música Ligera/harmonica-1.html"):
        assert get(app, pdf_url(sheet)).status == 404, sheet
        assert get(app, pdf_url(sheet, extra="&mine=1")).status == 404, sheet
    assert get(app, "/export.pdf?t=2").status == 404  # no sheet at all
    for bad in ("t=2&" + "x" * 5000, "t=2\x00", "t=%ff%fe"):
        assert get(app, pdf_url(query=quote(bad, safe="=&%"))).status == 400, bad
    assert printed == [] and queue.active_count() == 0


def test_the_auto_sheet_beside_a_human_one_is_not_exported(app, queue, recorder, conn, cfg, printed):
    # An export is made from the song's human sheet: asked from the auto sheet's viewer kept beside it, whose
    # chords are another sheet's, it would be the human sheet's PDF with the auto sheet's positions and swaps on
    # its chords, and Make this my version would save them. Refused; an auto sheet alone exports itself.
    song = rendered_song(conn, cfg, "Placeholder Band", "Synthetic Song", auto=True)
    auto = "Placeholder Band/Synthetic Song/sheet (auto).html"
    assert get(app, pdf_url(auto)).status == 200
    keep_human_sheet(conn, cfg, song)
    for extra in ("", "&mine=1"):
        refused = get(app, pdf_url(auto, extra=extra))
        assert refused.status == 409 and "auto-chords sheet" in text(refused), extra
    assert get(app, pdf_url("Placeholder Band/Synthetic Song/sheet.html")).status == 200
    queue.run_pending()
    assert recorder.calls == []


def keep_human_sheet(conn, cfg, song):
    """Keep a UG sheet beside the song's auto sheet, as the fetch step keeps one that doesn't cover the song
    yet, and render both."""
    import json

    from caracole.library import keep_file, song_dir, write_atomic
    from caracole.overrides import Overrides
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


def test_a_pdf_that_cant_be_made_says_why_and_makes_nothing_yours(app, queue, conn, cfg, monkeypatch):
    rendered_song(conn, cfg)
    real = render.version_pdf

    def failing(cmd, **kwargs):
        return subprocess.CompletedProcess(list(cmd), 2, stdout="", stderr="Unhandled fonts detected -- aborted\n")

    monkeypatch.setattr(render, "version_pdf", lambda *a, **k: real(*a, runner=failing, **k))
    for extra in ("", "&mine=1"):
        refused = get(app, pdf_url(extra=extra))
        assert refused.status == 500 and "chordpro failed" in text(refused), extra
        assert header(refused, "content-type").startswith("text/html") and not refused.body.startswith(b"%PDF")
    assert queue.active_count() == 0
    def no_font(*args, **kwargs):
        raise render.RenderError("sheet (A Major, capo 0).pdf needs a CJK font: set cjk_font or CARACOLE_CJK_FONT")

    monkeypatch.setattr(render, "version_pdf", no_font)
    refused = get(app, pdf_url())
    assert refused.status == 500 and "needs a CJK font" in text(refused)


def test_two_downloads_at_once_each_render_in_a_folder_of_its_own(app, conn, cfg, monkeypatch):
    rendered_song(conn, cfg)
    real = render.version_pdf
    both = threading.Barrier(2, timeout=10)
    folders = []

    def runner(cmd, **kwargs):  # each waits for the other: both run at once
        out = Path(next(a.split("=", 1)[1] for a in cmd if a.startswith("--output=")))
        folders.append(out.parent)
        both.wait()
        return fake_chordpro(cmd, **kwargs)

    monkeypatch.setattr(render, "version_pdf", lambda *a, **k: real(*a, runner=runner, **k))
    answers = []
    asks = [threading.Thread(target=lambda q=q: answers.append(get(app, pdf_url(query=q))))
            for q in (QUERY, "t=4&capo=0")]
    for ask in asks:
        ask.start()
    for ask in asks:
        ask.join(20)
    assert sorted(a.status for a in answers) == [200, 200] and len(set(folders)) == 2
    assert not any(folder.exists() for folder in folders)


def test_the_pdf_is_in_the_characters_the_viewer_shows_the_chinese_in(app, queue, conn, cfg, printed, tmp_path):
    # The viewer's address says trad=1 while its Chinese is in Traditional characters: the PDF is in them, and named
    # so; without it, in Simplified ones, as the viewer starts. A sheet in no Chinese is the same PDF either way.
    from dataclasses import replace

    from test_render_all import fake_font
    from test_render_hanzi import TRADITIONAL

    zh = replace(cfg, cjk_font=fake_font(tmp_path / "Kai.otf"))
    app = WebApp(zh, queue, allowed=ALLOWED, csrf="tok")
    rendered_song(conn, zh, "宋冬野", "斑馬斑馬", content=TRADITIONAL)
    sheet = "宋冬野/斑馬斑馬/sheet.html"
    traditional = get(app, pdf_url(sheet, "t=2&trad=1"))
    simplified = get(app, pdf_url(sheet, "t=2"))
    assert traditional.status == simplified.status == 200
    names = [unquote(header(r, "content-disposition").split("filename*=UTF-8''")[1]) for r in (traditional, simplified)]
    assert names[0].endswith(", Traditional).pdf") and names[1] == names[0].replace(", Traditional", "")
    assert "斑馬斑馬" in printed[0][0] and "斑马斑马" in printed[1][0] and "斑馬" not in printed[1][0]
    rendered_song(conn, cfg)  # in Spanish
    latin = get(app, pdf_url(query="t=2&capo=0&trad=1"))
    assert unquote(header(latin, "content-disposition").split("filename*=UTF-8''")[1]) == NAME
