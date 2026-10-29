"""caracole/web/server.py: the app on a real socket, a request run by the real command line, and a
sheet viewer it serves, in Chromium."""

import http.client
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlencode

import pytest

from caracole import db
from caracole.config import load_config
from caracole.web.app import WebApp
from caracole.web.jobs import CaracoleRunner, JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

from conftest import subprocess_pythonpath
from helpers.browser import in_chromium
from helpers.chromium import Chromium
from helpers.rendered import rendered_song


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, args, emit):
        self.calls.append(list(args))
        return 0


def running(app):
    server = make_server(app, "127.0.0.1", 0)
    # shutdown() returns at the next poll: every 10 ms, not every 500
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    return server


@pytest.fixture
def served(cfg):
    app = WebApp(cfg, JobQueue(Recorder()), allowed=allowed_hosts("127.0.0.1"), csrf="tok")
    server = running(app)
    yield server
    server.shutdown()
    server.server_close()


def ask(server, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def test_the_page_answers_on_the_socket(served):
    status, headers, body = ask(served, "GET", "/")
    assert status == 200 and b'action="/request"' in body
    assert headers["X-Content-Type-Options"] == "nosniff" and int(headers["Content-Length"]) == len(body)
    status, headers, body = ask(served, "HEAD", "/")
    assert status == 200 and body == b"" and int(headers["Content-Length"]) > 0


def test_another_host_name_is_refused_on_the_socket(served):
    status, _, _ = ask(served, "GET", "/", headers={"Host": "evil.example"})
    assert status == 421


def test_a_long_or_unsized_form_is_refused_unread(served):
    form = {"Content-Type": "application/x-www-form-urlencoded", "Sec-Fetch-Site": "same-origin"}
    status, _, _ = ask(served, "POST", "/request", body=b"x" * (17 * 1024), headers=form)
    assert status == 413
    conn = http.client.HTTPConnection("127.0.0.1", served.server_address[1], timeout=10)
    try:
        conn.putrequest("POST", "/request")
        conn.putheader("Content-Type", "application/x-www-form-urlencoded")
        conn.endheaders()
        assert conn.getresponse().status == 411
    finally:
        conn.close()


@pytest.mark.slow
def test_sigterm_stops_caracole_serve_cleanly(tmp_path):
    """How systemd stops the unit: the server closes, the queue stops, and it exits 0."""
    import signal
    import socket
    import subprocess

    src = Path(__file__).resolve().parents[1] / "src"
    config = tmp_path / "caracole.toml"
    config.write_text(f'library_dir = "{tmp_path / "lib"}"\nstate_dir = "{tmp_path / "state"}"\n'
                      f'cache_dir = "{tmp_path / "cache"}"\n', encoding="utf-8")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {"PYTHONPATH": subprocess_pythonpath(src), "HOME": str(tmp_path)}
    process = subprocess.Popen([sys.executable, "-m", "caracole", "--config", str(config), "serve", "--port",
                                str(port)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        # An answer, not just a connection: the socket listens before serve() is ready for a
        # SIGTERM, a gap a loaded machine (the suite on every core) can make wide enough to hit.
        for _ in range(200):
            try:
                served = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    served.request("GET", "/")
                    served.getresponse().read()
                finally:
                    served.close()
                break
            except (OSError, http.client.HTTPException):
                time.sleep(0.05)
        process.send_signal(signal.SIGTERM)
        out, _ = process.communicate(timeout=15)
    finally:
        process.kill()
    assert process.returncode == 0, out
    assert f"http://127.0.0.1:{port}/" in out


@pytest.mark.slow
def test_a_request_runs_caracole_add_for_real(tmp_path, monkeypatch):
    src = Path(__file__).resolve().parents[1] / "src"
    monkeypatch.setenv("PYTHONPATH", subprocess_pythonpath(src))
    config = tmp_path / "caracole.toml"
    config.write_text(f'library_dir = "{tmp_path / "lib"}"\nstate_dir = "{tmp_path / "state"}"\n'
                      f'cache_dir = "{tmp_path / "cache"}"\nmusic_dir = "{tmp_path / "music"}"\n', encoding="utf-8")
    cfg = load_config(config, env={"HOME": str(tmp_path / "home")})
    queue = JobQueue(CaracoleRunner(config, python=sys.executable))
    app = WebApp(cfg, queue, allowed=allowed_hosts("127.0.0.1"), csrf="tok")
    server = running(app)
    queue.start()
    try:
        body = urlencode({"csrf": "tok", "artist": "Radiohead", "title": "Creep"}).encode()
        status, headers, _ = ask(server, "POST", "/request", body=body, headers={
            "Content-Type": "application/x-www-form-urlencoded", "Sec-Fetch-Site": "same-origin"})
        assert status == 303 and headers["Location"] == "/#tab=requests&job=1"
        assert "Radiohead - Creep" in (tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8")
        for _ in range(200):
            job = queue.snapshot()[0]
            if not job.active:
                break
            time.sleep(0.05)
        assert job.state == "done", [s.output for s in job.steps]
        # The server wrote the line; caracole add found it there and synced it into the database. It ran
        # at -v, so the Requests tab has the detail too.
        output = job.steps[0].output
        assert "Radiohead - Creep is in wanted.txt already; the next `caracole run` looks for it." in output, output
        assert any(line.startswith("wanted.txt line ") for line in output), output
        conn = db.connect(cfg.db_path)
        try:
            assert [tuple(r) for r in conn.execute("SELECT artist, title FROM songs")] == [("Radiohead", "Creep")]
        finally:
            conn.close()
        status, _, page = ask(server, "GET", "/jobs")
        assert status == 404  # no page of their own: the library page's Requests tab
    finally:
        queue.stop()
        server.shutdown()
        server.server_close()


@in_chromium
def test_a_served_viewer_works_in_its_sandbox(cfg, conn, tmp_path):
    # The server sends viewer_csp() with the page: its own script and style by their hashes, in a
    # sandbox, so no other script runs there, a test's included; Chromium is driven from outside.
    rendered_song(conn, cfg)  # a sheet in G, its viewer as caracole wrote it
    server = running(WebApp(cfg, JobQueue(Recorder()), allowed=allowed_hosts("127.0.0.1"), csrf="tok"))
    url = f"http://127.0.0.1:{server.server_address[1]}/" + quote("Soda Stereo/De Música Ligera/sheet.html")
    chord = "document.querySelector('#sheet .c[data-c=\"0\"]').textContent"
    try:
        with Chromium(tmp_path / "profile") as browser:
            tab = browser.open(url)
            tab.wait_for("document.documentElement.dataset.ready === '1'")  # its script ran
            assert tab.eval("origin") == "null"  # in an origin of its own: the sandbox
            asked = "fetch('/', {mode: 'no-cors'}).then(() => 'reached', () => 'refused')"
            assert tab.eval(asked) == "refused"  # no way to ask the server for anything
            assert tab.eval("(() => { try { return document.cookie; } catch { return 'none'; } })()") == "none"
            assert tab.eval("document.querySelector('#panel').hidden") is True
            assert tab.eval(chord) == "G"
            tab.click("#more")  # ⋯ in the bar
            assert tab.eval("document.querySelector('#panel').hidden") is False  # opens the settings
            tab.click("#up")  # Transpose: up a semitone, twice
            tab.click("#up")
            assert tab.eval(chord) == "A"
            assert tab.eval("document.querySelector('#key-full').textContent") == "Key A · +2"
    finally:
        server.shutdown()
        server.server_close()


@in_chromium
def test_a_served_viewer_keeps_its_settings_in_its_address(cfg, conn, tmp_path):
    # The sandbox has no storage, so the transposition, the mode and the capo go in the page's
    # address: a reload and Back keep them.
    rendered_song(conn, cfg)
    server = running(WebApp(cfg, JobQueue(Recorder()), allowed=allowed_hosts("127.0.0.1"), csrf="tok"))
    url = f"http://127.0.0.1:{server.server_address[1]}/" + quote("Soda Stereo/De Música Ligera/sheet.html")
    chord = "document.querySelector('#sheet .c[data-c=\"0\"]').textContent"
    key = "document.querySelector('#key-full').textContent"
    afresh = "window.before === undefined && document.documentElement.dataset.ready === '1'"  # a new page
    try:
        with Chromium(tmp_path / "profile") as browser:
            tab = browser.open(url)
            tab.wait_for("document.documentElement.dataset.ready === '1'")
            assert tab.eval("location.hash") == ""  # nothing changed yet
            entries = tab.eval("history.length")
            tab.click("#t-up")  # + in the bar, twice
            tab.click("#t-up")
            tab.click("#more")
            tab.eval("[...document.querySelectorAll('#modes .chip')].find((b) => "
                     "b.firstChild.textContent === 'Minor').click()")
            assert tab.eval("location.hash") == "#t=2&mode=aeolian"
            assert tab.eval("history.length") == entries  # replaced, not an entry per tap
            tab.eval("window.before = true; setTimeout(() => location.reload(), 0)")
            tab.wait_for(afresh)
            assert tab.eval(chord) == "Am" and tab.eval(key) == "Key Am · +2"
            tab.eval("document.querySelector('a.back').click()")  # to the library, and Back
            tab.wait_for("document.title === 'caracole library'")
            tab.eval("history.back()")
            tab.wait_for(afresh)
            assert tab.eval(chord) == "Am" and tab.eval(key) == "Key Am · +2"
            tab.eval("document.querySelector('#reset-all').click()")
            assert tab.eval("location.hash") == "" and tab.eval(chord) == "G"
    finally:
        server.shutdown()
        server.server_close()


@in_chromium
def test_a_viewer_written_before_an_upgrade_still_works_served(cfg, conn, tmp_path, monkeypatch):
    # The server is a newer caracole than the one that wrote the viewer: the page's own hashes
    # must go out with it, or the browser refuses its script until the next render.
    from caracole.viewer import page

    rendered_song(conn, cfg)
    style, script = page._assets()
    monkeypatch.setattr(page, "_assets", lambda: (style + "\n.new {}", script + "\n// a new release"))
    server = running(WebApp(cfg, JobQueue(Recorder()), allowed=allowed_hosts("127.0.0.1"), csrf="tok"))
    url = f"http://127.0.0.1:{server.server_address[1]}/" + quote("Soda Stereo/De Música Ligera/sheet.html")
    try:
        with Chromium(tmp_path / "profile") as browser:
            tab = browser.open(url)
            tab.wait_for("document.documentElement.dataset.ready === '1'")  # its script ran
            assert tab.eval("getComputedStyle(document.querySelector('#bar')).position") == "fixed"  # its style
            tab.click("#more")
            assert tab.eval("document.querySelector('#panel').hidden") is False
    finally:
        server.shutdown()
        server.server_close()


@in_chromium
def test_a_phone_on_the_lan_cancels_a_request(cfg, conn, tmp_path):
    # Over plain HTTP to a LAN or tailnet address a page is no secure context: the browser sends no
    # Sec-Fetch-Site, and the server compares the form's Origin with Host. Under Referrer-Policy no-referrer a
    # form posted from the server's own page says Origin "null", so every form from a phone was refused;
    # same-origin names the page's origin to its own server, and nothing to another site. The library page's
    # Requests tab posts its Cancel with fetch(), which carries that Origin as a form does.
    from caracole.web.jobs import add_steps

    lan = "caracole.test"
    app = WebApp(cfg, JobQueue(Recorder()), allowed=allowed_hosts("127.0.0.1", extra=[lan]), csrf="tok")
    job, _ = app.submit("Add Radiohead - Creep", "radiohead/creep", add_steps("Radiohead", "Creep"))
    server = running(app)  # its queue never started: the request waits
    try:
        with Chromium(tmp_path / "profile", local=[lan]) as browser:
            tab = browser.open(f"http://{lan}:{server.server_address[1]}/#tab=requests")
            tab.wait_for("document.readyState === 'complete' && "
                         "document.querySelector('#req-1 form[action=\"/jobs/cancel\"] button') !== null")
            assert tab.eval("window.isSecureContext") is False  # as a phone on the LAN sees it
            tab.eval("window.before = true")
            tab.click('#req-1 form[action="/jobs/cancel"] button')
            tab.wait_for("document.querySelector('#req-1 .req-says').textContent === 'Cancelled'")
            assert tab.eval("window.before") is True  # the page stayed where it was
        assert [j.state for j in app.queue.snapshot() if j.id == job.id] == ["cancelled"]
    finally:
        server.shutdown()
        server.server_close()


def downloaded(folder: Path, n: int, timeout: float = 15) -> list[str]:
    """The names of the files a browser saved into ``folder``, once there are ``n`` (none half written)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        names = sorted(p.name for p in folder.iterdir() if not p.name.endswith(".crdownload"))
        if len(names) >= n:
            return names
        time.sleep(0.05)
    raise AssertionError(f"no {n} downloads in {folder}: {sorted(p.name for p in folder.iterdir())}")


@in_chromium
def test_the_served_viewer_downloads_its_pdf_and_asks_before_making_a_version_yours(cfg, conn, tmp_path, monkeypatch):
    # The viewer is sandboxed (no popups, no forms): its Export PDF is a plain link to the PDF, which the sandbox lets
    # it download, the page staying where it is. On a version other than the song's own it asks first, and Download
    # and make it mine queues Make this my version too.
    from caracole import render
    from helpers.rendered import fake_chordpro

    real = render.version_pdf
    monkeypatch.setattr(render, "version_pdf", lambda *a, **k: real(*a, runner=fake_chordpro, **k))
    rendered_song(conn, cfg)  # in G
    app = WebApp(cfg, JobQueue(Recorder()), allowed=allowed_hosts("127.0.0.1"), csrf="tok")
    server = running(app)
    url = f"http://127.0.0.1:{server.server_address[1]}/" + quote("Soda Stereo/De Música Ligera/sheet.html") + "#fs=20"
    saved = tmp_path / "downloads"
    saved.mkdir()
    try:
        with Chromium(tmp_path / "profile") as browser:
            browser.send("Browser.setDownloadBehavior", behavior="allow", downloadPath=str(saved))
            tab = browser.open(url)
            tab.wait_for("document.documentElement.dataset.ready === '1'")
            tab.eval("window.before = true")
            tab.click("#more")
            tab.eval("document.querySelector('#export').scrollIntoView({block: 'center'})")
            tab.click("#export")  # the song's own: at once
            assert downloaded(saved, 1) == ["Soda Stereo - De Música Ligera (G Major, capo 0).pdf"]
            assert tab.eval("window.before === true && !document.getElementById('export-ask').open")
            tab.eval("document.getElementById('up').click()")  # a semitone up: another version
            tab.click("#export")
            tab.wait_for("document.getElementById('export-ask').open")
            assert tab.eval("document.getElementById('ask-version').textContent") == "Ab Major"
            tab.click("#ask-mine")
            assert "Soda Stereo - De Música Ligera (Ab Major, capo 0).pdf" in downloaded(saved, 2)
            assert tab.eval("window.before === true && !document.getElementById('export-ask').open")
        [job] = app.queue.snapshot()
        assert [list(step.args) for step in job.steps] == [
            ["render", "--song=Soda Stereo - De Música Ligera", "--version=t=1", "--mine"]]
    finally:
        server.shutdown()
        server.server_close()
