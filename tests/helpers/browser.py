"""A headless Chromium driven over the DevTools protocol, for tests that type, press keys and click.

``--dump-dom`` shows a page once its scripts settle; a page you type into needs
more: keys pressed at a given moment, a click, the layout read back. Chromium
speaks the DevTools protocol over two pipes (``--remote-debugging-pipe``: it
reads commands on fd 3 and answers on fd 4), so no port is opened and nothing
but the standard library is needed. Tests skip when no Chromium runs here.
"""

from __future__ import annotations

import fcntl
import json
import os
import select
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

CHROMIUM = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")


class BrowserError(Exception):
    """Chromium couldn't start, stopped answering, or a command failed."""


class Browser:
    """One headless Chromium with one page, ``width`` × ``height`` CSS pixels (``mobile``: a phone's)."""

    def __init__(self, profile: Path, *, width: int = 1280, height: int = 900, mobile: bool = False,
                 timeout: float = 30.0):
        if CHROMIUM is None:
            raise BrowserError("chromium not found on PATH")
        self.timeout = timeout
        to_child, self._to_child = os.pipe()
        self._from_child, from_child = os.pipe()
        # Above 4, so the shell can put them on 3 and 4 without clobbering either.
        high_in, high_out = fcntl.fcntl(to_child, fcntl.F_DUPFD, 10), fcntl.fcntl(from_child, fcntl.F_DUPFD, 10)
        os.close(to_child)
        os.close(from_child)
        command = [CHROMIUM, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                   "--no-proxy-server", "--disable-extensions", f"--user-data-dir={profile}",
                   f"--window-size={width},{height}", "--remote-debugging-pipe", "about:blank"]
        try:
            self._process = subprocess.Popen(
                ["sh", "-c", f'exec "$@" 3<&{high_in} 4>&{high_out} {high_in}<&- {high_out}>&-', "sh", *command],
                pass_fds=(high_in, high_out), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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

    def js(self, expression: str) -> Any:
        """The value of a JavaScript expression in the page (a promise's, once settled)."""
        result = self.send("Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in result:
            raise BrowserError(f"{expression[:80]}: {json.dumps(result['exceptionDetails'])[:400]}")
        return result.get("result", {}).get("value")

    def open(self, url: str) -> None:
        self.send("Page.navigate", url=url)
        if not self.wait("document.readyState === 'complete' && location.href !== 'about:blank'"):
            raise BrowserError(f"{url} didn't load")

    def wait(self, expression: str, timeout: float = 10.0) -> bool:
        """Whether the expression became true within ``timeout`` seconds."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.js(expression):
                return True
            time.sleep(0.03)
        return False

    def type(self, text: str) -> None:
        """Text typed into the focused field, a character at a time, as fast as a key repeat."""
        for character in text:
            self.send("Input.insertText", text=character)

    def press(self, key: str = "Enter") -> None:
        codes = {"Enter": 13, "Escape": 27, "Tab": 9}
        for kind in ("keyDown", "keyUp"):
            self.send("Input.dispatchKeyEvent", type=kind, key=key, code=key, windowsVirtualKeyCode=codes[key],
                      **({"text": "\r"} if key == "Enter" and kind == "keyDown" else {}))

    def click(self, selector: str) -> None:
        """A real click (the mouse, pressed and let go) in the middle of the element ``selector`` finds."""
        box = self.js(f"(() => {{ const e = document.querySelector({json.dumps(selector)}); if (!e) return null; "
                      "e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); "
                      "return [r.x + r.width / 2, r.y + r.height / 2]; })()")
        if not box:
            raise BrowserError(f"nothing on the page is {selector}")
        for kind in ("mousePressed", "mouseReleased"):
            self.send("Input.dispatchMouseEvent", type=kind, x=box[0], y=box[1], button="left", clickCount=1)

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
