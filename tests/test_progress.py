"""caracole.progress: one live line on a terminal, plain lines anywhere else, and time estimates."""

from __future__ import annotations

import io
import logging

import pytest

from caracole.progress import Console, Pace, about, duration


class Terminal(io.StringIO):
    """What a terminal is to a program: a stream that says it is one."""

    def isatty(self) -> bool:
        return True


def console(stream=None, *, env=None, **kw) -> Console:
    return Console(stream if stream is not None else io.StringIO(), environ=env or {"TERM": "xterm"},
                   width=lambda: 40, **kw)


# --- where the output goes ------------------------------------------------------------------


def test_a_terminal_gets_a_live_line_and_color():
    c = console(Terminal())
    assert c.live and c.color


def test_a_pipe_or_the_journal_gets_plain_lines_without_color():
    c = console(io.StringIO())
    assert not c.live and not c.color


@pytest.mark.parametrize("value", ["1", "yes"])
def test_no_color_keeps_the_live_line_and_drops_color(value):
    c = console(Terminal(), env={"TERM": "xterm", "NO_COLOR": value})
    assert c.live and not c.color


def test_an_empty_no_color_is_not_set():  # no-color.org: present and not empty
    assert console(Terminal(), env={"TERM": "xterm", "NO_COLOR": ""}).color


def test_a_dumb_terminal_gets_plain_lines():
    c = console(Terminal(), env={"TERM": "dumb"})
    assert not c.live and not c.color


# --- plain lines ----------------------------------------------------------------------------


def test_plain_output_has_one_line_per_step_and_no_carriage_return_or_escape():
    out = io.StringIO()
    c = console(out)
    c.note("Reading 3 sitemaps.")
    c.status("reading sitemap1.xml...")  # only a terminal shows what is under way
    c.step("[1/3] sitemap1.xml  4 tabs", "2 left, about 30 s")
    c.step("[2/3] sitemap2.xml  2 tabs", "1 left, about 15 s")
    c.say("Index built.", fg="green")
    c.close()
    assert out.getvalue() == (
        "Reading 3 sitemaps.\n"
        "[1/3] sitemap1.xml  4 tabs  2 left, about 30 s\n"
        "[2/3] sitemap2.xml  2 tabs  1 left, about 15 s\n"
        "Index built.\n"
    )


def test_quiet_keeps_only_what_is_said():
    out = io.StringIO()
    c = console(out, quiet=True)
    c.note("Reading 3 sitemaps.")
    c.step("[1/3] sitemap1.xml  4 tabs", "2 left")
    c.say("Index built.")
    assert out.getvalue() == "Index built.\n"


# --- the live line ------------------------------------------------------------------------


def test_a_terminal_rewrites_one_line_in_place_and_clears_it_for_what_is_said():
    out = Terminal()
    c = console(out, env={"TERM": "xterm", "NO_COLOR": "1"})
    c.step("[1/3] sitemap1.xml  4 tabs", "2 left")
    c.step("[2/3] sitemap2.xml", "1 left")
    c.say("Index built.")
    assert out.getvalue() == (
        "\r[1/3] sitemap1.xml  4 tabs  2 left"
        "\r[2/3] sitemap2.xml  1 left" + " " * 8  # blanks over the rest of the longer line before it
        + "\r" + " " * 26 + "\r"
        "Index built.\n"
    )


def test_the_live_line_fits_the_terminal_and_keeps_its_tail():
    # 40 columns: at most 39 characters, so the line never wraps and "\r" always reaches its start.
    # The text gives way, not the time left.
    out = Terminal()
    console(out).step("[ 7/41] sitemap7.xml  50,000 tabs: 44,120 indexed", "34 left, about 8 min")
    assert out.getvalue() == "\r[ 7/41] sitema...  34 left, about 8 min"


def test_closing_clears_a_live_line_left_on_screen():
    out = Terminal()
    c = console(out)
    c.status("reading sitemap1.xml...")
    c.close()
    assert out.getvalue() == "\rreading sitemap1.xml..." + "\r" + " " * 23 + "\r"


def test_color_only_on_a_terminal():
    out = Terminal()
    console(out).say("complete", fg="green")
    assert "\x1b[" in out.getvalue()
    plain = io.StringIO()
    console(plain).say("complete", fg="green")
    assert plain.getvalue() == "complete\n"


# --- time ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "under a second"),
        (0.4, "under a second"),
        (4.4, "about 4 s"),
        (12, "about 10 s"),
        (13, "about 15 s"),
        (58, "about 1 min"),
        (90, "about 2 min"),
        (615, "about 10 min"),
        (3600, "about 1 h"),
        (5000, "about 1 h 23 min"),
    ],
)
def test_about_rounds_a_time_to_what_matters(seconds, text):
    assert about(seconds) == text


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0.04, "0.0 s"), (4.25, "4.2 s"), (42.4, "42 s"), (632.4, "10 min 32 s"), (3725, "1 h 2 min")],
)
def test_duration_says_how_long_something_took(seconds, text):
    assert duration(seconds) == text


def test_pace_starts_from_the_pacing_and_moves_to_what_it_measures():
    now = [100.0]
    pace = Pace(15.0, clock=lambda: now[0])
    assert pace.left(40) == 600  # nothing measured yet: the pacing's mean
    for _ in range(4):
        now[0] += 20.0
        pace.step()
    # 4 steps took 80 s; the pacing still counts as 2 of them: (2 x 15 + 80) / 6 = 18.33 s a step
    assert pace.left(10) == pytest.approx(183.33, abs=0.01)
    for _ in range(96):
        now[0] += 20.0
        pace.step()
    assert pace.left(10) == pytest.approx(199.0, abs=0.5)  # almost all measured by now


# --- a ticker: what long work is doing, on a terminal and in the journal --------------------


class Clock:
    """A clock the test moves: ``clock.at`` seconds."""

    def __init__(self, at: float = 1000.0):
        self.at = at

    def __call__(self) -> float:
        return self.at


def ticker(stream=None, *, clock=None, every=60.0, width=60):
    from caracole.progress import Ticker

    stream = Terminal() if stream is None else stream
    c = Console(stream, environ={"TERM": "xterm", "NO_COLOR": "1"}, width=lambda: width)
    return Ticker(c, clock=clock or Clock(), every=every), stream


def progress_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "caracole.progress"]


def test_a_ticker_rewrites_its_live_line_on_a_terminal_and_logs_a_line_a_minute(caplog):
    clock = Clock()
    t, out = ticker(clock=clock)
    with caplog.at_level(logging.INFO, logger="caracole.progress"):
        t.begin("[6/20] lyrics")
        clock.at += 30
        t.show("LRCLIB · 12 of up to 200 requests", "up to about 2 min left")
        clock.at += 29
        t.show("LRCLIB · 37 of up to 200 requests", "up to about 1 min left")  # 59 s after the step began: no line
        clock.at += 2
        t.show("LRCLIB · 40 of up to 200 requests", "up to about 1 min left")
        clock.at += 59
        t.show("LRCLIB · 99 of up to 200 requests")  # a minute after the last line: not yet
        t.close()
    assert progress_lines(caplog) == ["[6/20] lyrics · LRCLIB · 40 of up to 200 requests  up to about 1 min left"]
    screen = out.getvalue()
    assert screen.startswith("\r[6/20] lyrics…")
    assert "\r[6/20] lyrics · LRCLIB · 37 of up to 200 requests  up to about 1 min left" not in screen  # 60 columns
    assert "\r[6/20] lyrics · LRCLIB · 37 of u...  up to about 1 min left" in screen  # the tail kept, the text cut
    assert screen.endswith("\r" + " " * len("[6/20] lyrics · LRCLIB · 99 of up to 200 requests") + "\r")


def test_off_a_terminal_a_ticker_writes_nothing_but_its_log_lines(caplog):
    clock = Clock()
    plain = io.StringIO()
    t, _ = ticker(plain, clock=clock)
    with caplog.at_level(logging.INFO, logger="caracole.progress"):
        t.show("Rendering · 3 of 200 songs")
        clock.at += 61
        t.show("Rendering · 150 of 200 songs", "about 10 s left")
        t.close()
    assert plain.getvalue() == ""  # neither a carriage return nor a line: the journal's lines are the log's
    assert progress_lines(caplog) == ["Rendering · 150 of 200 songs  about 10 s left"]


def test_a_ticker_takes_its_live_line_off_the_screen_before_the_log_writes_a_record(log_to_tty):
    from caracole import logs

    stderr = log_to_tty
    t, _ = ticker(stderr)
    t.show("PDFs · 3 of 200 songs")
    logging.getLogger("caracole.render").warning("no PDF for Epic - Song: chordpro failed")
    t.show("PDFs · 4 of 200 songs")
    t.close()
    logging.getLogger("caracole.render").warning("after it")  # closed: nothing left to clear
    assert stderr.getvalue() == (
        "\rPDFs · 3 of 200 songs" + "\r" + " " * 21 + "\r"
        "warning: no PDF for Epic - Song: chordpro failed\n"
        "\rPDFs · 4 of 200 songs" + "\r" + " " * 21 + "\r"
        "warning: after it\n"
    )
    assert logs.level() == logs.NORMAL


@pytest.fixture
def log_to_tty():
    from caracole import logs

    stream = Terminal()
    logs.setup(logs.NORMAL, stream=stream, env={"NO_COLOR": "1"})
    yield stream
    logs.teardown()


def test_a_commands_ticker_is_live_on_a_terminal_at_the_default_verbosity_alone(monkeypatch):
    import sys

    from caracole import logs
    from caracole import progress

    monkeypatch.setattr(sys, "stderr", Terminal())
    monkeypatch.setenv("TERM", "xterm")
    for level, live in ((logs.NORMAL, True), (logs.QUIET, False), (logs.VERBOSE, False), (logs.DEBUG, False)):
        logs.setup(level, stream=io.StringIO(), env={})
        try:
            assert progress.ticker().console.live is live, level
        finally:
            logs.teardown()
    assert progress.ticker().console.live is False  # no log set up: a library's caller, a test


# --- the requests a client sends, counted ---------------------------------------------------


class Ev:
    def __init__(self, decision: str, provider: str = "lrclib"):
        self.decision = decision
        self.provider = provider


def test_a_clients_requests_are_counted_against_its_budget_with_the_time_left(caplog):
    from caracole.progress import Requests

    clock = Clock()
    t, out = ticker(clock=clock, width=200)
    beat = Requests(t, "lrclib", budget=200, delay=(0.25, 0.5), clock=clock)
    t.begin("[6/20] lyrics")
    for decision in ("ok", "cached", "error", "robots", "ok", "budget"):  # cached, robots and budget send nothing
        clock.at += 0.5
        beat(Ev(decision))
    assert beat.sent == 3
    # 3 sent, 197 left: 2.5 s from the first to the third for 2, the pacing's 0.875 s counting twice: 1.06 s each
    assert out.getvalue().split("\r")[-1].rstrip() == (
        "[6/20] lyrics · LRCLIB · 3 of up to 200 requests  up to about 3 min left")
    t.close()


def test_a_client_with_no_budget_says_its_count_alone():
    from caracole.progress import Requests

    t, out = ticker(width=200)
    beat = Requests(t, "azlyrics", budget=None, delay=(0.0, 0.0))
    beat(Ev("ok", "azlyrics"))
    assert out.getvalue().split("\r")[-1].rstrip() == "AZLyrics · 1 request"
    beat(Ev("ok", "azlyrics"))
    assert out.getvalue().split("\r")[-1].rstrip() == "AZLyrics · 2 requests"
    t.close()


def test_a_clients_pace_starts_again_at_the_runs_next_step():
    from caracole.progress import Requests

    clock = Clock()
    t, out = ticker(clock=clock, width=200)
    beat = Requests(t, "ug", budget=60, delay=(2.5, 5.0), clock=clock)
    t.begin("[3/20] index")
    beat(Ev("ok", "ug"))
    clock.at += 600  # the steps between: the index's pace is no measure of the fetch's
    t.begin("[9/20] fetch")
    beat(Ev("ok", "ug"))
    # 2 sent, of the run's 60; the fetch's first request: the pacing's 3.75 s and 0.5 s of answer, 58 times
    assert out.getvalue().split("\r")[-1].rstrip() == (
        "[9/20] fetch · Ultimate Guitar · 2 of up to 60 requests  up to about 4 min left")
    t.close()


def test_yt_dlp_runs_are_counted_with_no_time_left():
    # A run is a download of minutes, never the pacing's few seconds: no estimate is better than a wrong one.
    from caracole.progress import Requests

    t, out = ticker(width=200)
    beat = Requests(t, "youtube", budget=6, delay=(3.75, 7.5), noun="yt-dlp run", estimate=False)
    beat(Ev("ok", "youtube"))
    t.close()
    assert out.getvalue().split("\r")[1].rstrip() == "YouTube · 1 of up to 6 yt-dlp runs"


def test_counted_work_says_how_far_it_is_with_the_time_left_once_measured():
    from caracole.progress import Counted

    clock = Clock()
    t, out = ticker(clock=clock, width=200)
    count = Counted(t, per_step=1.0, clock=clock)
    count("PDFs · 1 of 101 songs", 0, 101)
    assert out.getvalue().split("\r")[-1].rstrip() == "PDFs · 1 of 101 songs"  # nothing measured: no time yet
    clock.at += 2.0
    count("PDFs · 2 of 101 songs", 1, 101)
    # 1 done in 2 s, the guess of 1 s counting twice: (2 + 2) / 3 = 1.33 s, 100 left
    assert out.getvalue().split("\r")[-1].rstrip() == "PDFs · 2 of 101 songs  about 2 min left"
    count("Bare artists' pages · 0 of 10", 0, 10, kind="bare")  # another kind of step: measured again
    assert out.getvalue().split("\r")[-1].rstrip() == "Bare artists' pages · 0 of 10"
    t.close()


# --- a terminal that can't be written, and its width -----------------------------------------


class Gone(Terminal):
    """A terminal that went away (a closed pty, a hung-up ssh): every write fails."""

    def write(self, text):
        raise OSError(5, "Input/output error")


def test_a_terminal_that_cant_be_written_never_stops_the_work_and_the_live_line_stays_off(log_to_tty):
    from caracole import logs, progress

    t, _ = ticker(Gone())
    t.begin("[6/20] lyrics")  # fails: the line goes off, the work goes on
    t.show("LRCLIB · 3 of up to 200 requests")
    logging.getLogger("caracole.lyrics").warning("still logged")  # the clears-first filter raises nothing
    t.close()
    assert log_to_tty.getvalue() == "warning: still logged\n"
    assert logs._clearing == []
    assert progress.ticker().console.live is False  # for the rest of the process


def test_a_clear_that_raises_never_stops_a_record(log_to_tty):
    from caracole import logs

    def broken():
        raise ValueError("I/O operation on closed file.")

    logs.clears_first(broken)
    logging.getLogger("caracole.lyrics").warning("written all the same")
    assert log_to_tty.getvalue() == "warning: written all the same\n" and logs._clearing == []


def test_the_live_line_fits_stderrs_terminal_even_with_stdout_redirected(monkeypatch, log_to_tty):
    import os
    import sys

    from caracole import progress

    class Stderr(Terminal):
        def fileno(self):
            return 2

    def size(fd):
        if fd != 2:
            raise OSError(25, "Inappropriate ioctl for device")  # stdout: a file
        return os.terminal_size((30, 24))

    monkeypatch.delenv("COLUMNS", raising=False)
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setattr(progress.os, "get_terminal_size", size)
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    screen = Stderr()
    monkeypatch.setattr(sys, "stderr", screen)
    t = progress.ticker()
    t.show("UG's listings · 312 of about 3,480 pages", "about 48 min left")
    t.close()
    shown = screen.getvalue().split("\r")[1]
    assert shown == "UG's li...  about 48 min left" and len(shown) == 29  # 30 columns, one kept free


def test_a_wide_character_takes_two_columns_of_the_live_line():
    out = Terminal()
    c = Console(out, environ={"TERM": "xterm"}, width=lambda: 20)  # 19 columns at most
    c.status("宋冬野 - 斑马斑马斑马斑马斑马斑马")
    c.close()
    line = out.getvalue().split("\r")[1]
    assert line == "宋冬野 - 斑马斑..."  # 18 columns of 12 characters: by characters it would wrap
    out = Terminal()
    c = console(out)
    c.status("宋冬野 - 斑马斑马")  # 17 columns of 10 characters: its blanks cover 17
    c.close()
    assert out.getvalue() == "\r宋冬野 - 斑马斑马\r" + " " * 17 + "\r"


# --- systemd's status line ------------------------------------------------------------------


def test_a_ticker_tells_the_units_status_line_as_each_part_begins_and_every_few_seconds():
    clock = Clock()
    told = []
    from caracole.progress import Ticker

    t = Ticker(None, clock=clock, status=told.append)
    t.begin("[6/20] lyrics")
    clock.at += 1
    t.show("LRCLIB · 3 of up to 200 requests")  # a second on: not yet
    clock.at += 1.5
    t.show("LRCLIB · 9 of up to 200 requests", "up to about 1 min left")
    t.begin("[7/20] megalobiz")  # a new part: at once
    assert told == ["[6/20] lyrics…", "[6/20] lyrics · LRCLIB · 9 of up to 200 requests  up to about 1 min left",
                    "[7/20] megalobiz…"]


def test_a_ticker_finishes_with_a_last_status_line_and_nothing_on_the_screen_or_the_log(caplog):
    told = []
    from caracole.progress import Ticker

    t = Ticker(None, status=told.append)
    t.begin("[20/20] backup")
    with caplog.at_level(logging.INFO, logger="caracole.progress"):
        t.finish("Finished in 12 min 3 s · Songs: 3 in wanted.txt, 1 new.")
    assert told[-1] == "Finished in 12 min 3 s · Songs: 3 in wanted.txt, 1 new." and not caplog.records


def test_the_status_line_is_one_line():
    import os
    import socket

    from caracole.progress import systemd_status

    name = f"caracole-test-lines-{os.getpid()}"
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as listening:
        listening.bind("\0" + name)
        assert systemd_status("First, build the index once.\nUntil then…", environ={"NOTIFY_SOCKET": "@" + name})
        assert listening.recv(4096) == "STATUS=First, build the index once. Until then…".encode()


def test_the_status_line_goes_to_the_socket_systemd_names_and_nowhere_without_one():
    import os
    import socket

    from caracole.progress import systemd_status

    name = f"caracole-test-{os.getpid()}-{id(object())}"
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as listening:
        listening.bind("\0" + name)  # an abstract address, as systemd's "@…" names one
        assert systemd_status("[6/20] lyrics…", environ={"NOTIFY_SOCKET": "@" + name})
        assert listening.recv(4096) == "STATUS=[6/20] lyrics…".encode()
    assert not systemd_status("x", environ={})
    assert not systemd_status("x", environ={"NOTIFY_SOCKET": "@" + name})  # gone: no error, nothing told
    assert not systemd_status("x", environ={"NOTIFY_SOCKET": "vsock:2:1234"})  # a kind caracole doesn't speak


def test_a_commands_ticker_tells_systemd_only_where_the_unit_lets_it(monkeypatch):
    from caracole import progress

    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert progress.ticker()._status is None
    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
    assert progress.ticker()._status is not None
