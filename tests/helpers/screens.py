"""A terminal for progress.py's live line: what a command shows on stderr while it works, read back by a test.

``Terminal`` is a stream that says it is a terminal; ``shown()`` gives each live line written, in turn (each carriage
return a rewrite), blank ones left out. ``on_screen(monkeypatch)`` makes every command's ``progress.ticker()`` a live
one on such a terminal, 200 columns wide, so a test run through ``CliRunner`` (whose stderr is no terminal) sees what a
person at one would, and returns it::

    screen = on_screen(monkeypatch)
    CliRunner().invoke(build_app(), [...])
    assert screen.shown()[-1].startswith("UG's listings · ")
"""

from __future__ import annotations

import io


class Terminal(io.StringIO):
    """What a terminal is to a program: a stream that says it is one."""

    def isatty(self) -> bool:
        return True

    def shown(self) -> list[str]:
        return [part.rstrip() for part in self.getvalue().split("\r") if part.strip()]


def on_screen(monkeypatch, *, width: int = 200) -> Terminal:
    from caracole import progress

    screen = Terminal()
    monkeypatch.setattr(progress, "ticker", lambda: progress.Ticker(
        progress.Console(screen, environ={"TERM": "xterm", "NO_COLOR": "1"}, width=lambda: width)))
    return screen
