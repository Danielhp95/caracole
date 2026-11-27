"""yt-dlp in the app's Python (Chaquopy, the :youtube module): the versions it runs, and one run of yt-dlp.

`version()` says what the app carries, which YtDlpVersionTest holds to android/youtube/pins.json. `run(argv, out_path,
err_path)` is one yt-dlp run, as the computer's `yt-dlp ARGV…` is one process: `yt_dlp.main` under `sys.argv`, its
output into the two files, its exit status returned, never raised (opening the two files is the caller's concern: a path
that can't be written raises). As the computer's process does, anything that goes wrong under it (yt-dlp that won't
import, a bug out of `main` or out of yt-dlp-ejs) is its traceback in the err file and status 1; only a
KeyboardInterrupt (or another BaseException that isn't SystemExit) goes through, as it would stop the computer's process
too. Nothing here asks a site: what yt-dlp asks is its argv's, and the caller's to gate.

Before a run, YtDlpService (its own process, one run each) asks two more:

- `environ(names, values)`: `os.environ` replaced by those alone (Env.kt's, built from nothing: no proxy variable, no
  variable of the Android process's), and `tempfile` made to read its `TMPDIR` again, where yt-dlp writes each
  challenge script for qjs. The process's own environment, so qjs and any child yt-dlp starts inherit it too.
- `refusal(argv, loopback, qjs)`: why the service won't run `argv`, else None. The argv is read by yt-dlp's own option
  parser (`--help` and `--version` read through, nothing printed, no config file read, as `parseOpts` with arguments
  given reads none), and refused: when its `--proxy`, the last as yt-dlp takes it, isn't a gate's
  (`http://user:secret@127.0.0.1:port`) or it names another proxy (`--geo-verification-proxy`); when it would read its
  targets or its options from a file (`--batch-file`, `--load-info-json`, `--config-locations`), update yt-dlp, hand
  a download to another program (`--downloader`) or run a command (`--exec`: under `loopback` a test's own qjs
  alone, `before_dl:`, KillTest's child); and under `loopback`, any target but an http or https address of
  127.0.0.1 or 10.0.2.2 (no `ytsearch1:`, no youtube.com). Its words never hold a value of the argv: the proxy's holds
  the gate's secret. An argv the parser can't read is refused too, in those words.

What it is not:

- Only Python's `sys.stdout` and `sys.stderr` are redirected, never file descriptors 1 and 2: a child process yt-dlp
  starts inherits the process's real ones unless yt-dlp pipes it.
- One run a process: yt-dlp keeps state in module globals, so a second `run` in the same process is unsupported (the
  service runs each in a fresh process, the design's §3.2).
- The files are line-buffered, which flushes at each newline alone: yt-dlp's progress lines, ended by `\\r`, wait;
  the product's argv has `--no-progress`.
"""

import os
import platform
import re
import shlex
import sys
import tempfile
import traceback
from urllib.parse import urlsplit

# A gate's --proxy: HostGate's Opened.proxyArg, a user and a secret at 127.0.0.1.
_GATE = re.compile(r"http://[^:@/\s]+:[^:@/\s]+@127\.0\.0\.1:[0-9]{1,5}")
# The hosts a target may name under loopback (HostGate's LOOPBACK mode).
_LOOPBACK = ("127.0.0.1", "10.0.2.2")

UNREADABLE = "yt-dlp can't read its arguments"
NO_GATE = "its --proxy isn't the app's gate"
OTHER_PROXY = "it names a proxy beside the gate's"
FROM_A_FILE = "it would read targets or options from a file"
UPDATE = "it would update yt-dlp"
DOWNLOADER = "it would hand a download to another program"
COMMAND = "it would run a command"
NOT_LOOPBACK = "a target isn't a loopback address, and the network is loopback's"


class _Unreadable(Exception):
    pass


def version():
    """The Python, yt-dlp and yt-dlp-ejs this app runs, as `{"python", "ytdlp", "ejs"}`."""
    from yt_dlp.version import __version__ as ytdlp
    from yt_dlp_ejs import version as ejs

    return {"python": platform.python_version(), "ytdlp": ytdlp, "ejs": ejs}


def environ(names, values):
    """`os.environ` made exactly `names` to `values` (two lists), and tempfile's folder read again from it; the names
    of the variables the process had (never their values), for its log."""
    had = sorted(os.environ)
    os.environ.clear()
    os.environ.update({str(name): str(value) for name, value in zip(names, values, strict=True)})
    tempfile.tempdir = None
    return had


def _parsed(argv):
    """`argv` as yt-dlp's option parser reads it: (opts, targets). Nothing printed, no file read, no exit."""
    from yt_dlp.options import Config, create_parser

    root = Config(create_parser())
    parser = root.parser

    def exit(status=0, msg=None):
        # --help and --version print, then exit 0: here they do neither and the parse goes on; an error is unreadable.
        if status or msg:
            raise _Unreadable()

    parser.exit = exit
    parser.print_help = parser.print_version = parser.print_usage = lambda file=None: None
    root.append_config(argv, label="Override")
    return root.parse_args()


def _loopback(target):
    """Whether `target` is an http or https address of a loopback host, no user in it."""
    try:
        parts = urlsplit(target)
        parts.port  # a port that isn't one raises
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and parts.hostname in _LOOPBACK and "@" not in parts.netloc


def refusal(argv, loopback, qjs):
    """Why `argv` isn't run, in words holding none of its values; None for an argv the service runs."""
    argv = [str(arg) for arg in argv]
    saved = sys.stdout, sys.stderr
    with open(os.devnull, "w") as quiet:
        sys.stdout = sys.stderr = quiet
        try:
            opts, targets = _parsed(argv)
        except (Exception, SystemExit):
            return UNREADABLE
        finally:
            sys.stdout, sys.stderr = saved
    if opts.proxy is None or not _GATE.fullmatch(opts.proxy):
        return NO_GATE
    if opts.geo_verification_proxy is not None:
        return OTHER_PROXY
    if opts.batchfile is not None or opts.load_info_filename is not None or opts.config_locations:
        return FROM_A_FILE
    if opts.update_self:
        return UPDATE
    if opts.external_downloader:
        return DOWNLOADER
    for when, commands in (opts.exec_cmd or {}).items():
        for command in commands:
            if not (loopback and when == "before_dl" and _first_word(command) == qjs):
                return COMMAND
    if loopback and not all(_loopback(target) for target in targets):
        return NOT_LOOPBACK
    return None


def _first_word(command):
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    return words[0] if words else None


def run(argv, out_path, err_path):
    """yt-dlp run once over `argv` (its arguments, no program name), its output into `out_path` and `err_path`; its
    exit status, never an exception but a BaseException that isn't SystemExit."""
    argv = [str(arg) for arg in argv]
    saved = sys.argv, sys.stdout, sys.stderr
    with open(out_path, "w", encoding="utf-8", errors="replace", buffering=1) as out, \
            open(err_path, "w", encoding="utf-8", errors="replace", buffering=1) as err:
        sys.argv, sys.stdout, sys.stderr = ["yt-dlp", *argv], out, err
        try:
            import yt_dlp

            yt_dlp.main(argv)
            return 0
        except SystemExit as stop:
            return _status(stop.code, err)
        except Exception:
            traceback.print_exc(file=err)
            err.flush()
            return 1
        finally:
            sys.argv, sys.stdout, sys.stderr = saved


def _status(code, err):
    """A `SystemExit`'s code as a process's exit status: None is 0, an int itself, anything else written out and 1."""
    if code is None:
        return 0
    if isinstance(code, int):
        return code
    print(code, file=err)
    return 1
