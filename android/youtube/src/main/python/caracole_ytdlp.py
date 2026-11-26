"""yt-dlp in the app's Python (Chaquopy, the :youtube module): the versions it runs, and one run of yt-dlp.

`version()` says what the app carries, which YtDlpVersionTest holds to android/youtube/pins.json. `run(argv, out_path,
err_path)` is one yt-dlp run, as the computer's `yt-dlp ARGV…` is one process: `yt_dlp.main` under `sys.argv`, its
standard output and error line-buffered into the two files (so a reader follows them as yt-dlp writes), its exit
status returned, never raised. Nothing here asks a site: what yt-dlp asks is its argv's, and the caller's to gate.
"""

import platform
import sys


def version():
    """The Python, yt-dlp and yt-dlp-ejs this app runs, as `{"python", "ytdlp", "ejs"}`."""
    from yt_dlp.version import __version__ as ytdlp
    from yt_dlp_ejs import version as ejs

    return {"python": platform.python_version(), "ytdlp": ytdlp, "ejs": ejs}


def run(argv, out_path, err_path):
    """yt-dlp run once over `argv` (its arguments, no program name), its output into `out_path` and `err_path`; its
    exit status."""
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
