"""caracole/web/server.py: the app on a real socket, and a request run by the real command line."""

import http.client
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest

from caracole import db
from caracole.config import load_config
from caracole.web.app import WebApp
from caracole.web.jobs import CaracoleRunner, JobQueue
from caracole.web.security import allowed_hosts
from caracole.web.server import make_server

from conftest import subprocess_pythonpath


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
        assert status == 303 and headers["Location"] == "/jobs#job-1"
        assert "Radiohead - Creep" in (tmp_path / "lib" / "wanted.txt").read_text(encoding="utf-8")
        for _ in range(200):
            job = queue.snapshot()[0]
            if not job.active:
                break
            time.sleep(0.05)
        assert job.state == "done", [s.output for s in job.steps]
        # The server wrote the line; caracole add found it there and synced it into the database.
        assert job.steps[0].output[0].startswith("Already in "), job.steps[0].output
        conn = db.connect(cfg.db_path)
        try:
            assert [tuple(r) for r in conn.execute("SELECT artist, title FROM songs")] == [("Radiohead", "Creep")]
        finally:
            conn.close()
        status, _, page = ask(server, "GET", "/jobs")
        assert status == 200 and b"Add Radiohead - Creep" in page and b"Done" in page
    finally:
        queue.stop()
        server.shutdown()
        server.server_close()
