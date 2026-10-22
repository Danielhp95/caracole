"""Headless Chromium driven over the DevTools protocol, for a page whose own policy refuses any
script a test would add to it (a sheet viewer served in its sandbox, say).

Chromium speaks the protocol over a pipe (``--remote-debugging-pipe``): it reads
commands from its file descriptor 3 and answers on 4, one JSON message per
NUL-terminated chunk. So the standard library is enough, and nothing listens on
a port. Clicks are real mouse events, at the element's place on the screen::

    from helpers.chromium import CHROMIUM, Chromium

    with Chromium(tmp_path / "profile") as browser:
        tab = browser.open("http://127.0.0.1:8737/Artist/Title/sheet.html")
        tab.wait_for("document.documentElement.dataset.ready === '1'")
        tab.click("#more")
        tab.eval("document.querySelector('#panel').hidden")  # False

``Chromium`` skips the test when this machine can't run Chromium. Like helpers/browser.py's, it
resolves no host name and starts without the desktop's environment; its tests are ``@in_chromium``.
"""

from __future__ import annotations

import fcntl
import json
import os
import select
import shutil
import subprocess
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from helpers.browser import headless_env, no_lookups, require_in_chromium

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
TIMEOUT = 30  # seconds, for any one answer


class Chromium:
    """A headless Chromium with a profile of its own, closed on leaving the ``with``."""

    def __init__(self, profile: Path, *, size: str = "390,844", local: Iterable[str] = ()):
        """``local``: names that resolve to this machine without being local to the browser (helpers.browser.no_lookups)."""
        require_in_chromium()
        if CHROMIUM is None:
            pytest.skip("chromium not found on PATH")
        commands, self._commands = os.pipe()  # Chromium reads its commands from fd 3
        self._answers, answers = os.pipe()  # and writes its answers to fd 4
        # Above 9, so that neither end sits on 3 or 4 when the shell moves them there.
        theirs = [fcntl.fcntl(fd, fcntl.F_DUPFD, 10) for fd in (commands, answers)]
        os.close(commands)
        os.close(answers)
        cmd = [CHROMIUM, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               f"--user-data-dir={profile}", no_lookups(local), f"--window-size={size}", "--remote-debugging-pipe",
               "about:blank"]
        script = f'exec "$@" 3<&{theirs[0]} 4>&{theirs[1]} {theirs[0]}<&- {theirs[1]}>&-'
        try:
            self._process = subprocess.Popen(["sh", "-c", script, "sh", *cmd], pass_fds=theirs,
                                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL, env=headless_env())
        except OSError as e:
            pytest.skip(f"chromium couldn't run: {e}")
        finally:
            for fd in theirs:
                os.close(fd)
        self._buffer = b""
        self._last_id = 0
        try:
            self.send("Browser.getVersion")
        except (EOFError, TimeoutError, OSError) as e:
            self.close()
            pytest.skip(f"chromium couldn't run: {e!r}")

    def __enter__(self) -> Chromium:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def send(self, method: str, session: str | None = None, **params: Any) -> dict[str, Any]:
        """Send one command (to the page attached as ``session``, if given) and return its result."""
        self._last_id += 1
        message: dict[str, Any] = {"id": self._last_id, "method": method, "params": params}
        if session is not None:
            message["sessionId"] = session
        os.write(self._commands, json.dumps(message).encode("utf-8") + b"\0")
        while True:
            answer = self._next()
            if answer.get("id") == self._last_id:
                if "error" in answer:
                    raise RuntimeError(f"{method}: {answer['error']}")
                return answer["result"]

    def open(self, url: str) -> Tab:
        """A new tab, at ``url``."""
        target = self.send("Target.createTarget", url="about:blank")["targetId"]
        session = self.send("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
        tab = Tab(self, session)
        self.send("Page.navigate", session, url=url)
        return tab

    def close(self) -> None:
        if self._process.poll() is None:
            try:
                self.send("Browser.close")
            except (EOFError, TimeoutError, OSError, RuntimeError):
                pass
            try:
                self._process.wait(10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        for fd in (self._commands, self._answers):
            try:
                os.close(fd)
            except OSError:
                pass

    def _next(self) -> dict[str, Any]:
        """The next message Chromium sends: an answer or an event."""
        deadline = time.monotonic() + TIMEOUT
        while b"\0" not in self._buffer:
            ready, _, _ = select.select([self._answers], [], [], max(0.0, deadline - time.monotonic()))
            if not ready:
                raise TimeoutError("chromium didn't answer")
            chunk = os.read(self._answers, 1 << 16)
            if not chunk:
                raise EOFError("chromium closed its pipe")
            self._buffer += chunk
        raw, self._buffer = self._buffer.split(b"\0", 1)
        return json.loads(raw)


class Tab:
    """One page of a ``Chromium``."""

    def __init__(self, browser: Chromium, session: str):
        self._browser = browser
        self._session = session

    def eval(self, expression: str) -> Any:
        """The value of a JavaScript expression in the page, a promise's once it settles (DevTools
        runs it, whatever the page's own policy allows; what it does then, the policy governs)."""
        result = self._browser.send("Runtime.evaluate", self._session, expression=expression,
                                    returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in result:
            raise RuntimeError(f"{expression}: {result['exceptionDetails']}")
        return result["result"].get("value")

    def wait_for(self, expression: str, timeout: float = 15) -> None:
        """Wait until ``expression`` is true in the page; AssertionError if it never is."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                if self.eval(expression):
                    return
            except RuntimeError:  # the page isn't there yet
                pass
            if time.monotonic() > deadline:
                raise AssertionError(f"never true in the page: {expression}")
            time.sleep(0.05)

    def click(self, selector: str) -> None:
        """Click the middle of the element ``selector`` names with the mouse, as a person would."""
        box = self.eval(f"(() => {{ const r = document.querySelector({json.dumps(selector)})"
                        ".getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()")
        x, y = box
        for kind in ("mousePressed", "mouseReleased"):
            self._browser.send("Input.dispatchMouseEvent", self._session, type=kind, x=x, y=y,
                               button="left", clickCount=1)
