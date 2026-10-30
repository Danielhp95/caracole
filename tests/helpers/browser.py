"""Headless Chromium driven over the DevTools protocol: one per test process for the tests that
look at a page after its script ran (``dump_dom``), and ``Browser``, one of its own, for the
tests that type, press keys and click.

``chromium --dump-dom`` starts a browser for every page, about half a second each. Here one
browser starts the first time a test asks, and each page gets a browser context of its own, as
fresh as a new profile: nothing one page kept (localStorage, cookies, the cache) is there for the
next. A page loads the way ``--virtual-time-budget=3000 --dump-dom`` loads it: its timers run on
virtual time for up to three seconds, network fetches pending pause the clock, and then the DOM is
read back. A window is the size asked for, even narrower than the 500 pixels ``--window-size``
gives at the least.

A page you type into needs more: keys pressed at a given moment, a click, the layout read back.
``Browser`` is a Chromium of its own with one page for that, its timers on real time.

Chromium speaks the protocol over two pipes (``--remote-debugging-pipe``: it reads fd 3, writes
fd 4), so the tests need no WebSocket library and open no port. Tests skip when no Chromium runs
here.
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
from collections.abc import Iterable
from typing import Any

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


def no_lookups(local: Iterable[str] = ()) -> str:
    """NO_LOOKUPS, but each name of ``local`` resolves to 127.0.0.1: a server on this machine under a name no
    browser trusts as local, so its pages are no secure context (no ``Sec-Fetch-*`` headers), as a phone sees
    a server at a LAN or tailnet address over plain HTTP."""
    return "--host-resolver-rules=" + "".join(f"MAP {name} 127.0.0.1, " for name in local) + NO_LOOKUPS.split("=", 1)[1]
# Browser.wait's expression, evaluated as one step with the page's readiness: what it throws while the
# document is still parsed is "not yet" (``loading``), what it throws once the page has loaded is thrown.
WAIT_PROBE = """(async () => {
  const loading = document.readyState !== "complete";
  try {
    return { value: await (
EXPRESSION
    ) };
  } catch (e) {
    if (loading) return { loading: String((e && e.stack) || e) };
    throw e;
  }
})()"""
# What the protocol answers an evaluation whose document a navigation took away.
NAVIGATING = ("Inspected target navigated or closed", "Execution context was destroyed",
              "Cannot find context with specified id")
# Nor does a headless browser need the desktop's display or session bus.
DESKTOP = ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS")


def headless_env() -> dict[str, str]:
    """The environment a test's Chromium starts with: this one, without the desktop's."""
    return {k: v for k, v in os.environ.items() if k not in DESKTOP}


# What @in_chromium gives a test; a module whose every test opens pages has it as its pytestmark.
CHROMIUM_MARKS = [pytest.mark.skipif(CHROMIUM is None, reason="chromium not found on PATH"), pytest.mark.slow,
                  pytest.mark.usefixtures("_chromium")]


def in_chromium(test):
    """For a test that opens pages in Chromium: marked slow, skipped without Chromium, and given
    conftest.py's ``_chromium``, which keeps the browser's profile in the run's basetemp and lets
    the test open pages at all (``require_in_chromium``)."""
    for mark in CHROMIUM_MARKS:
        test = mark(test)
    return test


class BrowserError(RuntimeError):
    """Chromium couldn't start, answered a command with an error, died, or said nothing in time."""


class PageError(BrowserError):
    """The page's JavaScript threw, evaluating what a test asked (``Browser.js``)."""


class SharedBrowser:
    """This process's headless Chromium (``browser()``), and the protocol messages to and from it."""

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
                    [binary, "--headless=new", "--mute-audio", "--disable-gpu", "--no-first-run",
                     "--no-default-browser-check", f"--user-data-dir={profile}", NO_LOOKUPS,
                     "--remote-debugging-pipe", "about:blank"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log,
                    pass_fds=(3, 4), preexec_fn=pipes_on_3_and_4, env=headless_env(),
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
                 mobile: bool = False, touch: bool = False, media: dict[str, str] | None = None,
                 budget_ms: int = 3000) -> str:
        """The DOM of the page at ``url`` after its script ran, as ``--dump-dom`` prints it;
        ``mobile``: laid out on a phone's screen of ``size`` (``Emulation.setDeviceMetricsOverride``);
        ``touch``: a touch screen, where ``(pointer: coarse)`` matches; ``media``: media features as
        ``{"prefers-color-scheme": "dark"}`` (``Emulation.setEmulatedMedia``)."""
        self._events.clear()  # the pages before this one's
        context = self.call("Target.createBrowserContext")["browserContextId"]
        try:
            width, height = size
            target = self.call("Target.createTarget", url="about:blank", browserContextId=context,
                               width=width, height=height, newWindow=True)["targetId"]
            session = self.call("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
            if hide_scrollbars:
                self.call("Emulation.setScrollbarsHidden", session, hidden=True)
            if mobile:
                self.call("Emulation.setDeviceMetricsOverride", session, width=width, height=height,
                          deviceScaleFactor=1, mobile=True)
            if touch:
                self.call("Emulation.setTouchEmulationEnabled", session, enabled=True, maxTouchPoints=5)
            if media:
                self.call("Emulation.setEmulatedMedia", session,
                          features=[{"name": k, "value": v} for k, v in media.items()])
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
        """Close the pipes, which the browser takes as the end (sooner than the protocol's
        Browser.close)."""
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


# Where the profiles go: a folder in the run's basetemp, from conftest.py's _chromium_profiles, so
# that pytest clears a profile with the run's other folders, even one a killed test process left.
profiles: Path | None = None
_browser: SharedBrowser | None = None
_profile: Path | None = None
# Whether the running test is marked @in_chromium: conftest.py's _chromium says so while it runs.
marked = False


def require_in_chromium() -> None:
    """Fail a test that opens pages in Chromium without @in_chromium, whichever browser it starts
    (``dump_dom``, ``Browser``, helpers/chromium.py's ``Chromium``) and whatever ran before it:
    unmarked, it would run in the quick loop, and fail rather than skip where no Chromium runs."""
    if not marked:
        pytest.fail("a test that opens pages in Chromium is marked @in_chromium", pytrace=False)


def browser() -> SharedBrowser:
    """This process's browser, started on first use; skips the test when Chromium can't run here.

    conftest.py's _chromium_profiles closes it when the session ends; a browser whose pipes close
    (its test process killed, say) quits by itself."""
    global _browser, _profile
    require_in_chromium()
    if _browser is not None and _browser.process.poll() is None:
        return _browser
    if CHROMIUM is None:
        pytest.skip("chromium not found on PATH")
    close()
    _profile = Path(tempfile.mkdtemp(prefix="profile-", dir=profiles))
    try:
        _browser = SharedBrowser(CHROMIUM, _profile)
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


def dump_dom(url: str, size: tuple[int, int], *, hide_scrollbars: bool = False, mobile: bool = False,
             touch: bool = False, media: dict[str, str] | None = None, budget_ms: int = 3000) -> str:
    """The DOM of the page at ``url`` after its script ran, in this process's Chromium, its timers
    run for ``budget_ms`` of virtual time (``SharedBrowser.dump_dom`` says what the rest does). A
    browser that failed is closed, so the next test starts another."""
    try:
        return browser().dump_dom(url, size, hide_scrollbars=hide_scrollbars, mobile=mobile, touch=touch,
                                  media=media, budget_ms=budget_ms)
    except BrowserError:
        close()
        raise


# --- a page driven as you would: typing, Enter, clicks --------------------------------------------


class Browser:
    """One headless Chromium with one page, ``width`` × ``height`` CSS pixels (``mobile``: a phone's); ``args``, more
    of Chromium's switches (``--blink-settings=minimumFontSize=40``: every text drawn at least that large)."""

    def __init__(self, profile: Path, *, width: int = 1280, height: int = 900, mobile: bool = False,
                 timeout: float = 30.0, args: Iterable[str] = ()):
        require_in_chromium()
        if CHROMIUM is None:
            raise BrowserError("chromium not found on PATH")
        self.timeout = timeout
        to_child, self._to_child = os.pipe()
        self._from_child, from_child = os.pipe()
        # Above 4, so the shell can put them on 3 and 4 without clobbering either.
        high_in, high_out = fcntl.fcntl(to_child, fcntl.F_DUPFD, 10), fcntl.fcntl(from_child, fcntl.F_DUPFD, 10)
        os.close(to_child)
        os.close(from_child)
        command = [CHROMIUM, "--headless=new", "--mute-audio", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                   "--no-proxy-server", "--disable-extensions", f"--user-data-dir={profile}", NO_LOOKUPS,
                   f"--window-size={width},{height}", *args, "--remote-debugging-pipe", "about:blank"]
        try:
            self._process = subprocess.Popen(
                ["sh", "-c", f'exec "$@" 3<&{high_in} 4>&{high_out} {high_in}<&- {high_out}>&-', "sh", *command],
                pass_fds=(high_in, high_out), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=headless_env())
        finally:
            os.close(high_in)
            os.close(high_out)
        self._buffer = b""
        self._id = 0
        self.events: list[dict[str, Any]] = []
        try:
            target = self._send("Target.createTarget", url="about:blank")["targetId"]
            self._session = self._send("Target.attachToTarget", targetId=target, flatten=True)["sessionId"]
            self.send("Page.enable")
            self.send("Runtime.enable")
            self.send("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1,
                      mobile=mobile)
            if mobile:
                self.send("Emulation.setTouchEmulationEnabled", enabled=True)
        except BaseException:
            self.close()
            raise

    # --- the protocol ------------------------------------------------------------------------------

    def send(self, method: str, **params: Any) -> dict[str, Any]:
        """A command to the page; its result."""
        return self._send(method, session=self._session, **params)

    def _send(self, method: str, *, session: str | None = None, **params: Any) -> dict[str, Any]:
        self._id += 1
        message: dict[str, Any] = {"id": self._id, "method": method, "params": params}
        if session:
            message["sessionId"] = session
        try:
            os.write(self._to_child, json.dumps(message).encode() + b"\0")
        except OSError as e:
            raise BrowserError(f"chromium stopped: {e}") from e
        while True:
            answer = self._next()
            if answer.get("id") == self._id:
                if "error" in answer:
                    raise BrowserError(f"{method}: {answer['error']}")
                return answer.get("result", {})
            self.events.append(answer)

    def _next(self) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        while b"\0" not in self._buffer:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([self._from_child], [], [], left)[0]:
                raise BrowserError("chromium didn't answer in time")
            chunk = os.read(self._from_child, 1 << 20)
            if not chunk:
                raise BrowserError("chromium stopped")
            self._buffer += chunk
        raw, self._buffer = self._buffer.split(b"\0", 1)
        return json.loads(raw)

    # --- what a test does ------------------------------------------------------------------------------

    def js(self, expression: str, *, said: str | None = None) -> Any:
        """The value of a JavaScript expression in the page (a promise's, once settled); ``said``, how an
        error names it, if not by itself."""
        result = self.send("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in result:
            raise PageError(f"{(said or expression)[:80]}: {json.dumps(result['exceptionDetails'])[:400]}")
        return result.get("result", {}).get("value")

    def open(self, url: str) -> None:
        """The page at ``url``, once loaded: a document of its own, not the one before it (but for a change of
        the address's fragment alone, which loads none)."""
        self.js("window.caracoleLeft = true")
        went = self.send("Page.navigate", url=url)
        fresh = "window.caracoleLeft === undefined && " if went.get("loaderId") else ""
        if not self.wait(fresh + "document.readyState === 'complete' && location.href !== 'about:blank'"):
            raise BrowserError(f"{url} didn't load")

    def wait(self, expression: str, timeout: float = 10.0) -> bool:
        """Whether the expression became true within ``timeout`` seconds. While the page loads (its document
        still parsed, or a navigation under way), one that throws is not true yet: a page loading has no
        document element for a moment. On a page that has loaded, one that throws raises at once (a typo, a
        node the page lacks), as does one that throws while the page loads to the end of the time."""
        probe = WAIT_PROBE.replace("EXPRESSION", expression)
        deadline = time.monotonic() + timeout
        loading = None
        while time.monotonic() < deadline:
            try:
                answer = self.js(probe, said=expression)
            except PageError:
                raise
            except BrowserError as e:  # the evaluation's document went away under it: a navigation
                if not any(words in str(e) for words in NAVIGATING):
                    raise
                answer = {"loading": str(e)}
            if isinstance(answer, dict) and "value" in answer:
                if answer["value"]:
                    return True
                loading = None
            else:
                loading = answer.get("loading") if isinstance(answer, dict) else repr(answer)
            time.sleep(0.03)
        if loading is not None:
            raise PageError(f"{expression[:80]}: threw while the page loaded: {loading[:400]}")
        return False

    def type(self, text: str) -> None:
        """Text typed into the focused field, a character at a time, as fast as a key repeat."""
        for character in text:
            self.send("Input.insertText", text=character)

    def press(self, key: str = "Enter", modifiers: int = 0) -> None:
        """The key ``key`` pressed and let go (" " is Space), with ``modifiers`` held: DevTools' bits, Alt 1, Ctrl 2,
        Meta 4, Shift 8."""
        codes = {"Enter": 13, "Escape": 27, "Tab": 9, "Home": 36, "End": 35, "ArrowLeft": 37, "ArrowUp": 38,
                 "ArrowRight": 39, "ArrowDown": 40, " ": 32}
        code = "Space" if key == " " else key
        text = {"Enter": "\r", " ": " "}.get(key) if not modifiers & 7 else None
        for kind in ("keyDown", "keyUp"):
            self.send("Input.dispatchKeyEvent", type=kind, key=key, code=code, windowsVirtualKeyCode=codes[key],
                      modifiers=modifiers, **({"text": text} if text and kind == "keyDown" else {}))

    def click(self, selector: str) -> None:
        """A real click (the mouse, pressed and let go) in the middle of the element ``selector`` finds."""
        box = self.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return null; "
                      "e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); "
                      "return [r.x + r.width / 2, r.y + r.height / 2]; })()")
        if not box:
            raise BrowserError(f"nothing on the page is {selector}")
        for kind in ("mousePressed", "mouseReleased"):
            self.send("Input.dispatchMouseEvent", type=kind, x=box[0], y=box[1], button="left", clickCount=1)

    def event(self, method: str, timeout: float = 10.0) -> dict[str, Any] | None:
        """The params of the first ``method`` event in ``events`` (clear it first for a new one), waited for
        ``timeout`` seconds at most; None when none came. It asks the browser, not the page, for them: a navigation
        ``Fetch`` holds (``Fetch.requestPaused``) leaves the page's evaluations waiting."""
        deadline = time.monotonic() + timeout
        while True:
            found = next((e for e in self.events if e.get("method") == method), None)
            if found is not None:
                return found.get("params", {})
            if time.monotonic() >= deadline:
                return None
            self._send("Browser.getVersion")  # what the browser sent meanwhile comes in with its answer
            time.sleep(0.03)

    def close(self) -> None:
        try:
            self._send("Browser.close")
        except (BrowserError, OSError, ValueError):
            pass
        try:
            self._process.wait(10)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(5)
        for fd in (self._to_child, self._from_child):
            try:
                os.close(fd)
            except OSError:
                pass

    def __enter__(self) -> Browser:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
