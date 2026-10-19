"""``WebApp`` on a socket: ``http.server``'s threading server, a thread per connection.

A connection serves one request (HTTP/1.0) and times out after 30 seconds. A
POST must say how long it is, and is refused unread beyond ``MAX_BODY``. The
queue's worker starts with the server and stops with it, ending the command it
was running: on Ctrl-C, and on SIGTERM, which is how systemd stops the unit.
"""

from __future__ import annotations

import logging
import signal
import socket
import threading
import traceback
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from caracole.web.app import MAX_BODY, Request, Response, WebApp

log = logging.getLogger(__name__)


class _Handler(BaseHTTPRequestHandler):
    server_version = "caracole"
    sys_version = ""
    timeout = 30
    server: _Server

    def do_GET(self) -> None:
        self._answer()

    do_HEAD = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_GET

    def _answer(self) -> None:
        app = self.server.app
        body = b""
        if self.command == "POST":
            length = self.headers.get("Content-Length")
            if length is None:
                self._send(app.finish(Response(411, b"A form must say how long it is.\n")))
                return
            try:
                size = int(length)
                if size < 0:
                    raise ValueError(length)
            except ValueError:
                self._send(app.finish(Response(400, b"That Content-Length isn't a length.\n")))
                return
            if size > MAX_BODY:
                self.close_connection = True
                self._send(app.finish(Response(413, b"That form is too long.\n")))
                return
            body = self.rfile.read(size)
        headers = {name.lower(): value for name, value in self.headers.items()}
        try:
            response = app.handle(Request(self.command, self.path, headers, body))
        except Exception:  # noqa: BLE001 (a bug: say so, keep serving)
            log.error("caracole serve: %s %s failed:\n%s", self.command, self.path, traceback.format_exc())
            response = app.finish(Response(500, b"caracole serve hit a bug; its log says where.\n"))
        self._send(response)

    def _send(self, response: Response) -> None:
        self.send_response(response.status)
        for name, value in response.headers:
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response.body)

    def log_message(self, format: str, *args: object) -> None:
        log.info("%s %s", self.address_string(), format % args)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, app: WebApp, address: str, port: int):
        host = address.strip("[]")
        self.address_family = socket.AF_INET6 if ":" in host else socket.AF_INET
        self.app = app
        super().__init__((host, port), _Handler)


def make_server(app: WebApp, address: str, port: int) -> ThreadingHTTPServer:
    """A server for ``app`` listening on ``address:port`` (port 0: any free one); OSError if it can't."""
    return _Server(app, address, port)


def url_for(address: str, port: int) -> str:
    host = address.strip("[]")
    if host in ("", "0.0.0.0", "::"):
        host = socket.gethostname()
    return f"http://[{host}]:{port}/" if ":" in host else f"http://{host}:{port}/"


def serve(app: WebApp, address: str, port: int, *, announce: Callable[[str], None] = print) -> None:
    """Serve until Ctrl-C or SIGTERM, then stop the queue; OSError when it can't listen."""
    server = make_server(app, address, port)
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _interrupt)
    app.queue.start()
    try:
        announce(f"caracole serve: {url_for(address, server.server_address[1])} (Ctrl-C stops it)")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.queue.stop()


def _interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt
