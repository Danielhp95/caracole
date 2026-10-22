"""caracole.logs: the log on stderr, set up once for every command by the CLI's root callback."""

from __future__ import annotations

import io
import logging
import os
import sys

import pytest

from caracole import logs

SECRETS = ("client-s3cret-value", "tk_ntfy-s3cret-token")


class TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def log_to():
    """Set the log up as a command does, on a stream of the test's (a fresh one by default)."""

    def setup(verbosity: int = logs.NORMAL, stream=None, env=None):
        stream = io.StringIO() if stream is None else stream
        logs.setup(verbosity, stream=stream, env={} if env is None else env)
        return stream

    yield setup
    logs.teardown()


def say_everything() -> None:
    """A record at each level from caracole, and from the third-party libraries it uses."""
    for name in ("caracole.lyrics", "httpx", "httpcore.http11", "urllib3.connectionpool", "librosa.core",
                 "numba.core", "torch"):
        log = logging.getLogger(name)
        log.debug("%s debug", name)
        log.info("%s info", name)
        log.warning("%s warning", name)


def test_verbosity_from_the_flags():
    assert logs.verbosity(0, False) == logs.NORMAL
    assert logs.verbosity(1, False) == logs.VERBOSE
    assert logs.verbosity(2, False) == logs.DEBUG == logs.verbosity(5, False)
    assert logs.verbosity(0, True) == logs.QUIET


def test_priorities_are_sd_daemons():
    assert [logs.priority(level) for level in (logging.CRITICAL, logging.ERROR, logging.WARNING, logging.INFO,
                                               logging.DEBUG)] == [2, 3, 4, 6, 7]


def test_by_default_only_problems_show_and_no_logger_names(log_to):
    out = log_to(logs.NORMAL)
    say_everything()
    shown = out.getvalue().splitlines()
    assert "warning: caracole.lyrics warning" in shown
    assert "warning: httpx warning" in shown  # a library's problem is still a problem
    assert not [line for line in shown if "info" in line or "debug" in line]


def test_quiet_shows_the_problems_too(log_to):
    out = log_to(logs.QUIET)
    say_everything()
    assert "warning: caracole.lyrics warning" in out.getvalue().splitlines()
    assert "info" not in out.getvalue()


def test_verbose_shows_caracoles_own_info_but_libraries_stay_quiet(log_to):
    out = log_to(logs.VERBOSE)
    say_everything()
    shown = out.getvalue().splitlines()
    assert "caracole.lyrics info" in shown  # no label for information, and no logger name
    assert [line for line in shown if "info" in line] == ["caracole.lyrics info"]
    assert not [line for line in shown if "debug" in line]


def test_very_verbose_adds_debug_and_the_libraries_with_logger_names(log_to):
    out = log_to(logs.DEBUG)
    say_everything()
    shown = out.getvalue().splitlines()
    assert "debug: caracole.lyrics: caracole.lyrics debug" in shown
    assert "httpx: httpx info" in shown
    assert "debug: librosa.core: librosa.core debug" in shown


def test_a_library_that_sets_its_own_level_still_stays_quiet(log_to):
    out = log_to(logs.VERBOSE)
    logging.getLogger("numba").setLevel(logging.DEBUG)  # as a library may when it is imported
    try:
        logging.getLogger("numba.core.ssa").debug("ssa debug")
        logging.getLogger("numba.core.ssa").info("ssa info")
    finally:
        logging.getLogger("numba").setLevel(logging.NOTSET)
    assert out.getvalue() == ""


def test_a_traceback_follows_its_one_line_summary(log_to):
    out = log_to(logs.NORMAL)
    try:
        raise KeyError("x")
    except KeyError:
        logging.getLogger("caracole.pipeline").error("The match step failed: KeyError: 'x'.", exc_info=True)
    first, *rest = out.getvalue().splitlines()
    assert first == "error: The match step failed: KeyError: 'x'."
    assert rest[0] == "Traceback (most recent call last):" and rest[-1] == "KeyError: 'x'"


# --- the journal and the terminal ------------------------------------------------------------


def journal_stream(tmp_path):
    """A file, and the JOURNAL_STREAM systemd would set for it (its device and inode)."""
    f = open(tmp_path / "journal", "w+", encoding="utf-8")  # noqa: SIM115 - closed by the test
    st = os.fstat(f.fileno())
    return f, {"JOURNAL_STREAM": f"{st.st_dev}:{st.st_ino}"}


def test_under_systemd_each_line_carries_its_priority_and_no_timestamp(tmp_path, log_to):
    f, env = journal_stream(tmp_path)
    with f:
        log_to(logs.NORMAL, stream=f, env=env)
        log = logging.getLogger("caracole.pipeline")
        log.warning("LRCLIB is slow tonight")
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            log.error("The match step failed: RuntimeError: boom.", exc_info=True)
        f.seek(0)
        lines = f.read().splitlines()
    assert lines[0] == "<4>LRCLIB is slow tonight"
    assert lines[1] == "<3>The match step failed: RuntimeError: boom."
    assert lines[2] == "<3>Traceback (most recent call last):"
    assert all(line.startswith("<3>") for line in lines[1:])  # every line of the traceback


def test_a_journal_stream_that_isnt_this_stream_changes_nothing(tmp_path, log_to):
    f, env = journal_stream(tmp_path)
    with f:
        out = log_to(logs.NORMAL, stream=io.StringIO(), env=env)  # stderr is somewhere else
        logging.getLogger("caracole").warning("w")
    assert out.getvalue() == "warning: w\n"
    assert not logs.is_journal(sys.stderr, {"JOURNAL_STREAM": "not:numbers"})


def test_colour_on_a_terminal_only_and_never_with_no_color(log_to):
    tty = log_to(logs.NORMAL, stream=TTY())
    logging.getLogger("caracole").warning("w")
    assert tty.getvalue().startswith("\x1b[")
    logs.teardown()
    plain = log_to(logs.NORMAL, stream=TTY(), env={"NO_COLOR": "1"})
    logging.getLogger("caracole").warning("w")
    assert plain.getvalue() == "warning: w\n"
    assert not logs.wants_colour(io.StringIO(), {})
    assert not logs.wants_colour(TTY(), {"TERM": "dumb"})
    assert logs.wants_colour(TTY(), {"NO_COLOR": ""})  # NO_COLOR counts only when it says something


# --- secrets -------------------------------------------------------------------------------


@pytest.mark.parametrize("verbosity", [logs.QUIET, logs.NORMAL, logs.VERBOSE, logs.DEBUG])
def test_no_secret_reaches_the_log_at_any_level(log_to, verbosity):
    out = log_to(verbosity)
    logs.add_secrets(*SECRETS, None, "")
    caracole, client = (logging.getLogger(n) for n in ("caracole.x", "httpx"))
    for level in (logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR):
        caracole.log(level, "config: secret %s, token %s", *SECRETS)
        # a client's debug line, with the ntfy token's header and a basic one
        client.log(level, "Sending %s to %s with Headers: %s", "POST", "https://ntfy.example/t",
                   {"Authorization": "Bearer tk_ntfy-bearer-value", "Proxy-Authorization": "Basic Y2xpZW50OnNlY3JldA=="})
        caracole.log(level, "sign-in form: {'token': 'serve-access-token', 'csrf': 'x'}")
        caracole.log(level, 'token JSON {"access_token": "json-access-value", "expires_in": 3600}')
        caracole.log(level, "Authorization: tk_bare-header-token")
    try:
        raise ValueError(f"ntfy said: invalid token {SECRETS[1]}")
    except ValueError:
        caracole.exception("ntfy failed")
    text = out.getvalue()
    for secret in (*SECRETS, "tk_ntfy-bearer-value", "Y2xpZW50OnNlY3JldA==", "serve-access-token",
                   "json-access-value", "tk_bare-header-token"):
        assert secret not in text
    assert "[redacted]" in text  # the errors still show, without what they would leak


def test_redaction_leaves_ordinary_words_alone():
    for text in ("the token is in /run/credentials/caracole.service/web_token",
                 "token_file = /run/agenix/ntfy", "LRCLIB GET https://lrclib.net/api/get?track_name=x → 503",
                 "ntfy's token expired. Give caracole another", "basic chords only, token refresh failed"):
        assert logs.redact(text) == text


# --- one place, undone after ---------------------------------------------------------------


def test_setup_twice_keeps_one_handler_and_teardown_restores_what_it_found():
    root = logging.getLogger()
    before = (list(root.handlers), root.level, logging.getLogger("caracole").level, logging.getLogger("httpx").level)
    logs.setup(logs.VERBOSE, stream=io.StringIO(), env={})
    logs.setup(logs.DEBUG, stream=io.StringIO(), env={})
    try:
        assert len(root.handlers) == len(before[0]) + 1
    finally:
        logs.teardown()
    after = (list(root.handlers), root.level, logging.getLogger("caracole").level, logging.getLogger("httpx").level)
    assert after == before


def test_the_handler_writes_to_the_stderr_of_the_moment(monkeypatch):
    logs.setup(logs.NORMAL, env={})
    try:
        later = io.StringIO()
        monkeypatch.setattr(sys, "stderr", later)
        logging.getLogger("caracole").warning("w")
    finally:
        logs.teardown()
    assert later.getvalue() == "warning: w\n"


def test_say_writes_one_line_the_way_the_log_would(tmp_path, monkeypatch):
    # For a command's last word on stderr (commands._common.fail), outside the logging machinery.
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    logs.add_secrets(SECRETS[0])  # secrets stay known for the life of the process
    logs.say(logging.ERROR, f"config: can't read {SECRETS[0]}", env={})
    assert err.getvalue() == "error: config: can't read [redacted]\n"
    f, env = journal_stream(tmp_path)
    with f:
        monkeypatch.setattr(sys, "stderr", f)
        logs.say(logging.ERROR, "can't open the database", env=env)
        f.seek(0)
        assert f.read() == "<3>can't open the database\n"


def test_a_command_whose_progress_is_its_report_can_ask_for_at_least_verbose(log_to):
    # caracole autochords: a line per song, minutes apart, unless -q asked for problems only.
    out = log_to(logs.NORMAL)
    logs.at_least(logs.VERBOSE)
    logging.getLogger("caracole.autochords.run").info("A – B: auto sheet written")
    logging.getLogger("httpx").info("still quiet")
    assert out.getvalue() == "A – B: auto sheet written\n"
    quiet = log_to(logs.QUIET)
    logs.at_least(logs.VERBOSE)
    logging.getLogger("caracole.autochords.run").info("A – B: auto sheet written")
    assert quiet.getvalue() == ""
    debug = log_to(logs.DEBUG)
    logs.at_least(logs.VERBOSE)  # never lowers it
    logging.getLogger("caracole.autochords.run").debug("details")
    assert "details" in debug.getvalue()
