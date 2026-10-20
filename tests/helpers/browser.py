"""One headless Chromium per test process, driven over the DevTools protocol, for the tests that
look at a page after its script ran.

``chromium --dump-dom`` starts a browser for every page, about half a second each. Here one
browser starts the first time a test asks, and each page gets a browser context of its own, as
fresh as a new profile: nothing one page kept (localStorage, cookies, the cache) is there for the
next. A page loads the way ``--virtual-time-budget=3000 --dump-dom`` loads it: its timers run on
virtual time for up to three seconds, network fetches pending pause the clock, and then the DOM is
read back. A window is the size asked for, even narrower than the 500 pixels ``--window-size``
gives at the least.

The browser speaks the protocol over two pipes (``--remote-debugging-pipe``: it reads fd 3, writes
fd 4), so the tests need no WebSocket library and open no port.
"""

from __future__ import annotations

import fcntl
import json
import os
import select
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
# What --dump-dom prints: the doctype, then the document's markup.
DUMP = ("(document.doctype ? new XMLSerializer().serializeToString(document.doctype) + '\\n' : '')"
        " + document.documentElement.outerHTML")
TIMEOUT = 60.0  # seconds a page may take, as the tests gave chromium --dump-dom
# The pages come from file:// and 127.0.0.1 alone. Left to itself, Chromium looks up and calls
# Google's update and account servers, and every lookup goes through nscd: a dozen browsers
# starting at once kept it busy for seconds, and with it everything else that asks it for a user
# or a host (chordpro does). No name resolves here, so no page reaches beyond this machine.
NO_LOOKUPS = "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"
# Nor does a headless browser need the desktop's display or session bus.
DESKTOP = ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS")


def in_chromium(test):
    """For a test that opens pages in Chromium: marked slow, and skipped without Chromium."""
    test = pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH")(test)
    return pytest.mark.slow(test)


class BrowserError(RuntimeError):
    """The browser answered a command with an error, died, or said nothing in time."""


class Browser:
    """A headless Chromium, and the protocol messages to and from it."""

    def __init__(self, binary: str, profile: Path):
        to_browser, from_us = os.pipe()
        to_us, from_browser = os.pipe()
        # Above 9, so that dup2 onto 3 and 4 in the child never overwrites the other one.
        theirs = [fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 10) for fd in (to_browser, from_browser)]
        for fd in (to_browser, from_browser):
            os.close(fd)

        def pipes_on_3_and_4():
            os.dup2(theirs[0], 3)
            os.dup2(theirs[1], 4)

        self.log = profile / "stderr.log"
        try:
            with open(self.log, "wb") as log:
                self.process = subprocess.Popen(
                    [binary, "--headless=new", "--disable-gpu", "--no-first-run",
                     "--no-default-browser-check", f"--user-data-dir={profile}", NO_LOOKUPS,
                     "--remote-debugging-pipe", "about:blank"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log,
                    pass_fds=(3, 4), preexec_fn=pipes_on_3_and_4,
                    env={k: v for k, v in os.environ.items() if k not in DESKTOP},
                )
        except BaseException:
            os.close(from_us)
            os.close(to_us)
            raise
        finally:
            for fd in theirs:
                os.close(fd)
        self._out, self._in = from_us, to_us
        self._next_id = 0
        self._buffer = b""
        self._events: list[dict] = []

    # --- the protocol ----------------------------------------------------------------------

    def call(self, method: str, session: str | None = None, **params) -> dict:
        """Send a command and return its result."""
        self._next_id += 1
        message = {"id": self._next_id, "method": method, "params": params}
        if session:
            message["sessionId"] = session
        data = json.dumps(message).encode() + b"\0"
        while data:
            data = data[os.write(self._out, data):]
        deadline = time.monotonic() + TIMEOUT
        while True:
            reply = self._receive(deadline)
            if reply.get("id") == self._next_id:
                if "error" in reply:
                    raise BrowserError(f"{method}: {reply['error']}")
                return reply.get("result", {})
            if "method" in reply:
                self._events.append(reply)

    def wait_for(self, method: str, session: str) -> dict:
        """The next event ``method`` from ``session``."""
        deadline = time.monotonic() + TIMEOUT
        while True:
            for i, event in enumerate(self._events):
                if event["method"] == method and event.get("sessionId") == session:
                    return self._events.pop(i)
            self._events.append(self._receive(deadline))

    def _receive(self, deadline: float) -> dict:
        while b"\0" not in self._buffer:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([self._in], [], [], left)[0]:
                raise BrowserError(f"chromium said nothing for {TIMEOUT:.0f} s")
            chunk = os.read(self._in, 1 << 20)
            if not chunk:
                raise BrowserError(f"chromium exited: {self.stderr()}")
            self._buffer += chunk
        message, _, self._buffer = self._buffer.partition(b"\0")
        return json.loads(message)

    def stderr(self) -> str:
        try:
            return self.log.read_text(errors="replace")[-500:]
        except OSError:
            return ""

    # --- pages -----------------------------------------------------------------------------

    def dump_dom(self, url: str, size: tuple[int, int], *, hide_scrollbars: bool = False,
                 budget_ms: int = 3000) -> str:
        """The DOM of the page at ``url`` after its script ran, as ``--dump-dom`` prints it."""
        self._events.clear()  # the pages before this one's
        context = self.call("Target.createBrowserContext")["browserContextId"]
        try:
            width, height = size
            target = self.call("Target.createTarget", url="about:blank", browserContextId=context,
                               width=width, height=height, newWindow=True)["targetId"]
            session = self.call("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
            if hide_scrollbars:
                self.call("Emulation.setScrollbarsHidden", session, hidden=True)
            # The clock stands still while the page loads, so the budget is the page's alone.
            self.call("Emulation.setVirtualTimePolicy", session, policy="pause")
            self.call("Page.navigate", session, url=url)
            self.call("Emulation.setVirtualTimePolicy", session,
                      policy="pauseIfNetworkFetchesPending", budget=budget_ms)
            self.wait_for("Emulation.virtualTimeBudgetExpired", session)
            result = self.call("Runtime.evaluate", session, expression=DUMP, returnByValue=True)
            if "exceptionDetails" in result:
                raise BrowserError(f"reading the DOM: {result['exceptionDetails']}")
        except BaseException:
            try:
                self.call("Target.disposeBrowserContext", browserContextId=context)
            except (BrowserError, OSError):
                pass  # the error that brought us here says more
            raise
        self.call("Target.disposeBrowserContext", browserContextId=context)
        return result["result"]["value"]

    def close(self) -> None:
        """Close the pipes, which the browser takes as the end (sooner than Browser.close)."""
        for fd in (self._out, self._in):
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            self.process.wait(10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


_browser: Browser | None = None
_profile: Path | None = None


def browser() -> Browser:
    """This process's browser, started on first use; skips the test when Chromium can't run here.

    conftest.py closes it when the session ends; a browser whose pipes close (its test process
    killed, say) quits by itself."""
    global _browser, _profile
    if _browser is not None and _browser.process.poll() is None:
        return _browser
    if CHROMIUM is None:
        pytest.skip("chromium not found on PATH")
    close()
    _profile = Path(tempfile.mkdtemp(prefix="caracole-chromium-",
                                     dir=os.environ.get("PYTEST_DEBUG_TEMPROOT")))
    try:
        _browser = Browser(CHROMIUM, _profile)
        _browser.call("Browser.getVersion")
    except (OSError, BrowserError) as e:
        close()
        pytest.skip(f"chromium couldn't run: {e}")
    return _browser


def close() -> None:
    """Quit this process's browser, if it started, and remove its profile."""
    global _browser, _profile
    if _browser is not None:
        _browser.close()
        _browser = None
    if _profile is not None:
        shutil.rmtree(_profile, ignore_errors=True)
        _profile = None


def dump_dom(url: str, size: tuple[int, int], *, hide_scrollbars: bool = False) -> str:
    """The DOM of the page at ``url`` after its script ran, in this process's Chromium. A browser
    that failed is closed, so the next test starts another."""
    try:
        return browser().dump_dom(url, size, hide_scrollbars=hide_scrollbars)
    except BrowserError:
        close()
        raise
