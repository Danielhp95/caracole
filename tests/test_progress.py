"""caracole.progress: one live line on a terminal, plain lines anywhere else, and time estimates."""

from __future__ import annotations

import io

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
