"""yt-dlp in the app's Python (Chaquopy, the :youtube module): the versions it runs, and one run of yt-dlp.

`version()` says what the app carries, which YtDlpVersionTest holds to android/youtube/pins.json. `run(argv, out_path,
err_path)` is one yt-dlp run, as the computer's `yt-dlp ARGV…` is one process: `yt_dlp.main` under `sys.argv`, its
output into the two files, its exit status returned, never raised (opening the two files is the caller's concern: a path
that can't be written raises). As the computer's process does, anything that goes wrong under it (yt-dlp that won't
import, a bug out of `main` or out of yt-dlp-ejs) is its traceback in the err file and status 1; only a
KeyboardInterrupt (or another BaseException that isn't SystemExit) goes through, as it would stop the computer's process
too. Nothing here asks a site: what yt-dlp asks is its argv's, and the caller's to gate.

What it is not:

- Only Python's `sys.stdout` and `sys.stderr` are redirected, never file descriptors 1 and 2: a child process yt-dlp
  starts inherits the process's real ones unless yt-dlp pipes it.
- One run a process: yt-dlp keeps state in module globals, so a second `run` in the same process is unsupported (the
  service runs each in a fresh process, the design's §3.2).
- The files are line-buffered, which flushes at each newline alone: yt-dlp's progress lines, ended by `\\r`, wait;
  the product's argv has `--no-progress`.
"""

import platform
import sys
import traceback


def version():
    """The Python, yt-dlp and yt-dlp-ejs this app runs, as `{"python", "ytdlp", "ejs"}`."""
    from yt_dlp.version import __version__ as ytdlp
    from yt_dlp_ejs import version as ejs

    return {"python": platform.python_version(), "ytdlp": ytdlp, "ejs": ejs}


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
