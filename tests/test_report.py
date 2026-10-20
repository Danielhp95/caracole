"""caracole.report: the words of ``caracole run``'s summary, for stdout and for ntfy."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from caracole.http import ProviderError, ProviderUnavailable, RobotsClosed
from caracole.pipeline import RunReport
from caracole.report import (
    BUILD_INDEX,
    JOURNAL,
    PLAIN,
    Action,
    Failure,
    NeedsYou,
    Problem,
    StepResult,
    Style,
    blocked,
    cooling,
    duration,
    plural,
    provider_name,
    render,
    sentence,
    song_name,
    style_for,
    summary_text,
    todo_count,
    why,
)

PAGE = Path("/srv/lib/_todo.md")


def report(*results: StepResult, requests=None, budgets=None, seconds=None) -> RunReport:
    return RunReport(
        run_id="r", started="r", results={f"step{i}": r for i, r in enumerate(results)},
        requests=dict(requests or {}), budgets=dict(budgets or {}), seconds=seconds,
    )


def lyrics(*failures: Failure, **kw) -> StepResult:
    return StepResult(title="Lyrics", failures=list(failures),
                      retry="the lyrics of {songs} will be tried again on the next run", **kw)


def http_error(status: int, provider: str = "lrclib") -> ProviderError:
    return ProviderError(provider, "https://lrclib.net/api/search?track_name=x", status, f"HTTP {status}")


def network_error(exc: httpx.HTTPError) -> ProviderError:
    """A ProviderError as PoliteClient raises it for a network error: inside the except block."""
    try:
        raise exc
    except httpx.HTTPError as e:
        try:
            raise ProviderError("lrclib", "https://lrclib.net/api/get", None, f"{type(e).__name__}: {e}")
        except ProviderError as wrapped:
            return wrapped


def lines(r: RunReport, **kw) -> list[str]:
    return summary_text(r, **kw).splitlines()


# --- the words ---------------------------------------------------------------------------


def test_providers_go_by_their_own_names():
    assert [provider_name(p) for p in ("ug", "lrclib", "lacuerda", "gtptabs", "musescore", "spotify")] == [
        "Ultimate Guitar", "LRCLIB", "LaCuerda", "gtptabs.com", "MuseScore", "Spotify",
    ]
    assert provider_name("newsite") == "newsite"  # a provider the report doesn't know yet


def test_a_song_is_artist_en_dash_clean_title():
    class Song:
        artist, title = "Soda Stereo ", "De Música Ligera - Remastered 2007"

    assert song_name(Song()) == "Soda Stereo – De Música Ligera"


def test_plural():
    assert (plural(1, "song"), plural(2, "song"), plural(0, "song")) == ("1 song", "2 songs", "0 songs")
    assert plural(2, "Guitar Pro file") == "2 Guitar Pro files"


@pytest.mark.parametrize(
    "error, said",
    [
        (http_error(503), "didn't answer (HTTP 503)"),
        (http_error(502), "didn't answer (HTTP 502)"),
        (http_error(504), "didn't answer (HTTP 504)"),
        (http_error(500), "had an error (HTTP 500)"),
        (http_error(410), "refused the request (HTTP 410)"),
        (http_error(301), "redirected caracole somewhere it doesn't follow"),
        (network_error(httpx.ReadTimeout("timed out")), "didn't answer in time"),
        (network_error(httpx.ConnectError("Name or service not known")), "couldn't be reached"),
        (ProviderError("lacuerda", "https://acordes.lacuerda.net/x/", None, "no song list (ul#b_main)"),
         "sent an answer caracole couldn't read"),
        (ProviderError("lrclib", "https://lrclib.net/api/get", 200, "unreadable response: Expecting value"),
         "sent an answer caracole couldn't read"),
        (ProviderUnavailable("lrclib", "https://lrclib.net/api/get", None, "too many errors this run"),
         "kept failing and caracole stopped asking it"),
        (RobotsClosed("ug", "https://tabs.ultimate-guitar.com/tab/download", None, "robots.txt disallows it"),
         "closes that page to bots (robots.txt)"),
    ],
    ids=["503", "502", "504", "500", "410", "redirect", "timeout", "unreachable", "parse", "bad-json",
         "unavailable", "robots"],
)
def test_why_says_what_the_provider_did_without_its_url(error, said):
    assert why(error) == said
    assert "http" not in why(error)


def test_why_says_a_program_that_took_too_long_didnt_answer_in_time():
    # yt-dlp, stopped after its timeout (youtube.py): no httpx error, but the same answer.
    try:
        raise ProviderError("youtube", "ytsearch8:Radiohead Creep", None, "yt-dlp took longer than 120 s") \
            from TimeoutError("yt-dlp took longer than 120 s")
    except ProviderError as e:
        assert why(e) == "didn't answer in time"


def test_a_duration_reads_in_seconds_minutes_or_hours():
    assert [duration(s) for s in (0.4, 3.2, 59.6, 125, 3600 + 4 * 60 + 9)] == [
        "less than a second", "3 s", "1 min", "2 min 5 s", "1 h 4 min",
    ]


def test_the_to_do_page_counts_the_items_of_its_counted_sections():
    page = ("# caracole to-do\n\n_Updated 2026-10-18 03:30 UTC · 3 songs_\n\n2 songs waiting for the nightly fetch.\n\n"
            "## Setup problems (1)\n\n- **The Ultimate Guitar index isn't built**\n\n"
            "## Review (2)\n\n### A - B\n\n- 90 · `a/b` (fuzzy) (3)\n\n"
            "## Guitar Pro pages to click (4)\n\n- **A - B**: [x](u)\n\n"
            "## PDFs\n\n- Last render never\n\n## Provider health\n\n| ug | OK |\n")
    assert todo_count(page) == 7
    assert todo_count("# caracole to-do\n\n## Sources\n") == 0


def test_what_the_to_do_page_only_tells_you_needs_nothing_from_you():
    page = ("## Review (2)\n\n## Partial sheets (5)\n\n## Missing lyrics (30)\n\n"
            "## Suggestions from your Spotify top tracks (10)\n\n## Buy list (1)\n")
    assert todo_count(page) == 3


def test_an_action_reads_as_a_sentence_of_its_own():
    # As the summary ends with it, and as an ntfy alert says it.
    assert sentence(Action("authorize Spotify again: caracole auth spotify", "wanted.txt keeps working.")) == (
        "Authorize Spotify again: caracole auth spotify. wanted.txt keeps working.")
    assert sentence(Action("build the index once")) == "Build the index once."


# --- the summary -------------------------------------------------------------------------


def test_repeated_errors_of_one_cause_collapse_into_one_line_with_a_count():
    failures = [Failure("lrclib", f"Artist – Song {n}", "didn't answer (HTTP 503)") for n in range(3)]
    text = summary_text(report(lyrics(*failures)))
    assert "LRCLIB didn't answer (HTTP 503), so the lyrics of 3 songs will be tried again on the next run." in text
    assert text.count("HTTP 503") == 1 and "Song 1" not in text


def test_errors_of_two_causes_get_a_line_each_in_the_order_they_came():
    text = summary_text(report(lyrics(
        Failure("lrclib", "A – One", "had an error (HTTP 500)"),
        Failure("lrclib", "A – Two", "didn't answer (HTTP 503)"),
        Failure("lrclib", "A – Three", "had an error (HTTP 500)"),
    )))
    assert text.splitlines() == [
        "LRCLIB had an error (HTTP 500), so the lyrics of 2 songs will be tried again on the next run.",
        "LRCLIB didn't answer (HTTP 503), so the lyrics of 1 song will be tried again on the next run.",
    ]


def test_the_songs_left_once_caracole_stops_asking_share_the_line_of_the_errors_that_stopped_it():
    # One cause: LRCLIB is down. Three songs failed, then caracole stopped asking, and 40 more wait.
    down = [Failure("lrclib", f"A – {n}", "didn't answer (HTTP 503)") for n in range(3)]
    left = [Failure("lrclib", f"B – {n}", "kept failing and caracole stopped asking it") for n in range(40)]
    assert lines(report(lyrics(*down, *left))) == [
        "LRCLIB didn't answer (HTTP 503) and caracole stopped asking it, so the lyrics of 43 songs will be tried "
        "again on the next run.",
    ]
    # Stopped by an earlier step's errors, the songs left have a line of their own.
    assert lines(report(lyrics(*left[:2]))) == [
        "LRCLIB kept failing and caracole stopped asking it, so the lyrics of 2 songs will be tried again on the "
        "next run.",
    ]


def test_one_line_per_step_that_did_something_and_none_for_the_others():
    r = report(StepResult(title="Songs", done=["40 in wanted.txt", "2 new"]),
               StepResult(title="Matching"),  # nothing changed
               StepResult(title="Lyrics", done=["3 found", "1 missing"]),
               StepResult(title="PDFs"))
    assert lines(r) == ["Songs: 40 in wanted.txt, 2 new.", "Lyrics: 3 found, 1 missing."]


def test_the_most_pressing_action_leads_once_however_many_steps_wait_for_it():
    spotify = Action("authorize Spotify again: caracole auth spotify", "wanted.txt keeps working meanwhile.", rank=30)
    r = report(StepResult(title="Songs", done=["1 in wanted.txt"], actions=[spotify]),
               StepResult(title="Index refresh", actions=[BUILD_INDEX]),
               StepResult(title="Matching", actions=[BUILD_INDEX]))
    assert lines(r) == [
        "First, build the index once: caracole index build (about 10 minutes).",
        "Until then, no song is matched or looked for on Ultimate Guitar.",
        "",
        "Songs: 1 in wanted.txt.",
        "",
        "Authorize Spotify again: caracole auth spotify. wanted.txt keeps working meanwhile.",
    ]


def test_it_ends_with_what_needs_you_the_problems_the_requests_and_the_time():
    r = report(
        StepResult(title="Lyrics", done=["3 found"], spent=["lrclib"],
                   failures=[Failure("lrclib", "A – B", "didn't answer (HTTP 503)")],
                   retry="the lyrics of {songs} will be tried again on the next run"),
        StepResult(title="PDFs", problems=[Problem("The render step failed: KeyError: 'x'.", logging.ERROR)]),
        StepResult(todo=NeedsYou(4, PAGE)),
        requests={"ug": 0, "lrclib": 200, "lacuerda": 3}, budgets={"ug": 60, "lrclib": 200, "lacuerda": 30},
        seconds=125,
    )
    assert lines(r) == [
        "Lyrics: 3 found.",
        "",
        "4 things on your to-do page need you: /srv/lib/_todo.md",
        "The render step failed: KeyError: 'x'.",  # a bug before the providers' errors
        "LRCLIB didn't answer (HTTP 503), so the lyrics of 1 song will be tried again on the next run.",
        "Requests: Ultimate Guitar 0 of 60, LRCLIB 200 of 200 (used up: the rest waits for the next run), "
        "LaCuerda 3 of 30.",
        "Took 2 min 5 s.",
    ]


def test_needs_you_counts_one_thing_and_nothing():
    assert lines(report(StepResult(todo=NeedsYou(1, PAGE)))) == ["1 thing on your to-do page needs you: /srv/lib/_todo.md"]
    assert lines(report(StepResult(todo=NeedsYou(0, PAGE)))) == ["Nothing on your to-do page needs you."]


def test_a_provider_without_a_known_budget_shows_its_requests_alone():
    assert lines(report(requests={"lrclib": 3})) == ["Requests: LRCLIB 3."]


def test_problems_said_by_several_steps_are_said_once():
    until = cooling("ug", datetime(2026, 10, 20, 5, 30))
    r = report(StepResult(problems=[until]), StepResult(problems=[until]))
    assert lines(r) == [
        "Ultimate Guitar is cooling down after a block until 2026-10-20 05:30 UTC, so caracole leaves it "
        "alone this run.",
    ]


def test_a_block_says_until_when_and_that_nothing_was_marked_not_found():
    from caracole.http import ProviderBlocked

    e = ProviderBlocked("ug", "https://tabs.ultimate-guitar.com/tab/1", 429, "HTTP 429")
    assert blocked(e, "fetch", datetime(2026, 10, 19, 5, 30), strikes=1).text == (
        "Ultimate Guitar blocked caracole (HTTP 429) during the fetch step, so caracole leaves it alone "
        "until 2026-10-19 05:30 UTC. Nothing was marked not found.")
    assert "until 2026-10-21 05:30 UTC (2 blocks in a row)." in blocked(e, "fetch", datetime(2026, 10, 21, 5, 30), strikes=2).text


def test_quiet_keeps_only_what_needs_you_and_the_problems():
    r = report(StepResult(title="Songs", done=["1 in wanted.txt"], actions=[BUILD_INDEX]),
               lyrics(Failure("lrclib", "A – B", "didn't answer (HTTP 503)"), done=["2 found"]),
               StepResult(todo=NeedsYou(3, PAGE)), requests={"lrclib": 2}, seconds=3)
    assert lines(r, quiet=True) == [
        "First, build the index once: caracole index build (about 10 minutes).",
        "Until then, no song is matched or looked for on Ultimate Guitar.",
        "",
        "LRCLIB didn't answer (HTTP 503), so the lyrics of 1 song will be tried again on the next run.",
    ]
    assert summary_text(report(StepResult(title="Songs", done=["1 in wanted.txt"])), quiet=True) == ""


# --- how it is written out -----------------------------------------------------------------


def test_plain_text_has_no_escape_codes_and_colour_marks_the_problems():
    r = report(StepResult(title="Songs", done=["1 in wanted.txt"], actions=[BUILD_INDEX]),
               lyrics(Failure("lrclib", "A – B", "didn't answer (HTTP 503)")))
    assert "\x1b[" not in summary_text(r, style=PLAIN)
    coloured = summary_text(r, style=Style(colour=True)).splitlines()
    assert coloured[0].startswith("\x1b[") and coloured[0].endswith("\x1b[0m")  # the action
    assert coloured[3] == "Songs: 1 in wanted.txt."  # what happened stays plain
    assert coloured[-1].startswith("\x1b[33m")  # a problem, in yellow


def test_for_the_journal_each_line_carries_its_priority_and_blank_lines_go():
    r = report(StepResult(title="Songs", done=["1 in wanted.txt"], actions=[BUILD_INDEX]),
               StepResult(problems=[Problem("The match step failed: RuntimeError: boom.", logging.ERROR)]),
               requests={"lrclib": 2})
    assert summary_text(r, style=JOURNAL).splitlines() == [
        "<4>First, build the index once: caracole index build (about 10 minutes).",
        "<4>Until then, no song is matched or looked for on Ultimate Guitar.",
        "<6>Songs: 1 in wanted.txt.",
        "<3>The match step failed: RuntimeError: boom.",
        "<6>Requests: LRCLIB 2.",
    ]


def test_the_style_follows_where_the_summary_goes(tmp_path):
    import io
    import os

    class TTY(io.StringIO):
        def isatty(self):
            return True

    assert style_for(io.StringIO(), {}) == PLAIN  # a pipe, a file, ntfy
    assert style_for(TTY(), {}) == Style(colour=True)
    assert style_for(TTY(), {"NO_COLOR": "1"}) == PLAIN
    with open(tmp_path / "journal", "w") as f:
        st = os.fstat(f.fileno())
        assert style_for(f, {"JOURNAL_STREAM": f"{st.st_dev}:{st.st_ino}"}) == JOURNAL


def test_an_empty_summary_renders_as_nothing():
    assert render([], PLAIN) == ""
    assert summary_text(report()) == ""
