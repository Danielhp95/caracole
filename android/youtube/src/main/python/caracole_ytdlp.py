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
- `refusal(argv, rules)`: why the service won't run `argv`, else None; `rules` the JSON GlueRules.kt makes (the
  phone's argv templates, their placeholders and targets' rules and the count a search asks for, from youtube.json;
  the gate's `--proxy` shape and the loopback hosts from HostGate; the mode, the app's qjs, and the run's own two
  folders, its cache's and its download's, which YtDlpService checked are in the app's storage with no link). An
  allowlist: the argv is read by yt-dlp's own option parser (as `parseOpts` with arguments given: no config file
  read; an alias read as what it expands to; `--help` and `--version` noted, not printed), and runs only when it is
  one of the templates as the parser reads them: each option a template sets holding the template's own value, or,
  where the template holds a placeholder, a value that placeholder's check passes (the proxy the gate's shape, the
  qjs the app's, the cache and the output folder the run's own, exactly, the target the mode's: a YouTube search of
  the phone's own count or a watch address on the network, an http or https address of a loopback host under
  LOOPBACK), and every other option at the parser's default (so `--no-plugin-dirs`, the cookies' `--no-…` and the
  rest as the templates give them). Under LOOPBACK alone, the tests' own forms, all in `_TEST_FORMS`: `--version`
  with the gate, and beside a template `--no-check-certificates`, `-v` and KillTest's one `--exec`; under NETWORK,
  `-v` alone, where `rules` says `verbose` (the YouTube bench's request: its client redacts the secret `-v`'s proxy
  map prints). Its words never hold a value of the argv: the proxy's holds the gate's secret.

What it is not:

- Only Python's `sys.stdout` and `sys.stderr` are redirected, never file descriptors 1 and 2: a child process yt-dlp
  starts inherits the process's real ones unless yt-dlp pipes it.
- One run a process: yt-dlp keeps state in module globals, so a second `run` in the same process is unsupported (the
  service runs each in a fresh process, the design's §3.2).
- The files are line-buffered, which flushes at each newline alone: yt-dlp's progress lines, ended by `\\r`, wait;
  the product's argv has `--no-progress`.
"""

import json
import os
import platform
import re
import sys
import tempfile
import traceback
from urllib.parse import urlsplit

UNREADABLE = "yt-dlp can't read its arguments"
BAD_MODE = "the network mode isn't LOOPBACK or NETWORK"
PRINTS = "it only prints yt-dlp's help or version, which the phone never asks for"
NOT_PHONE_ARGV = "it isn't one of the phone's own argvs"
NO_GATE = "its --proxy isn't the app's gate"
NOT_QJS = "its JavaScript runtime isn't the app's qjs"
FOLDER = "it would write outside the run's folders"
NOT_LOOPBACK = "a target isn't a loopback address, and the network is loopback's"
NOT_YOUTUBE = "its target isn't a YouTube search or video address"
TEST_FORM = "a test's form that doesn't hold"

_PATH_CHARS = re.compile(r"[A-Za-z0-9_./-]+")


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
    """`argv` as yt-dlp's option parser reads it: (its options as a dict, its targets, what it would print)."""
    from yt_dlp.options import Config, create_parser

    root = Config(create_parser())
    parser = root.parser
    printed = set()

    def exit(status=0, msg=None):
        # --help and --version print, then exit 0: here they are noted and the parse goes on; an error is unreadable.
        if status or msg:
            raise _Unreadable()

    parser.exit = exit
    parser.print_help = lambda file=None: printed.add("help")
    parser.print_version = lambda file=None: printed.add("version")
    parser.print_usage = lambda file=None: None
    root.append_config(argv, label="Override")
    opts, targets = root.parse_args()
    return vars(opts), list(targets), printed


def _quietly(argv):
    saved = sys.stdout, sys.stderr
    with open(os.devnull, "w") as quiet:
        sys.stdout = sys.stderr = quiet
        try:
            return _parsed(argv)
        finally:
            sys.stdout, sys.stderr = saved


_UNSET = object()


def _set(opts, defaults):
    """The options `opts` holds otherwise than the parser's defaults."""
    return {name: value for name, value in opts.items() if defaults.get(name, _UNSET) != value}


def _match(template, given, marks, found):
    """Whether `given` is `template` with each placeholder of `marks` (name: its text) filled, every value it fills
    added to `found` (a placeholder filled twice must be filled alike)."""
    if isinstance(template, str):
        hits = [(name, mark) for name, mark in marks.items() if mark in template]
        if not hits:
            return template == given
        if len(hits) > 1 or not isinstance(given, str):
            return False
        name, mark = hits[0]
        before, after = template.split(mark, 1)
        if mark in after or len(given) < len(before) + len(after):
            return False
        if not (given.startswith(before) and given.endswith(after)):
            return False
        value = given[len(before):len(given) - len(after)]
        return found.setdefault(name, value) == value
    if isinstance(template, dict):
        return (isinstance(given, dict) and template.keys() == given.keys()
                and all(_match(template[k], given[k], marks, found) for k in template))
    if isinstance(template, (list, tuple)):
        return (type(given) is type(template) and len(given) == len(template)
                and all(_match(t, g, marks, found) for t, g in zip(template, given)))
    return template == given


def _clean(path):
    """Whether `path` is an absolute folder of no `..`, `%` or trailing oddity, as written."""
    return bool(path) and os.path.isabs(path) and "%" not in path and os.path.normpath(path) == path.rstrip("/")


def _same(path, folder):
    """Whether `path` is the run's `folder` itself (YtDlpService checked that one: in the app's storage, no link)."""
    return folder is not None and _clean(path) and os.path.realpath(path) == os.path.realpath(folder)


def _inside(path, folder):
    """Whether `path` is a folder inside the run's `folder`, or that folder itself, no link out."""
    if folder is None or not _clean(path):
        return False
    real, root = os.path.realpath(path), os.path.realpath(folder).rstrip("/")
    return real == root or real.startswith(root + "/")


def _loopback(target, hosts):
    """Whether `target` is an http or https address of a loopback host, no user in it."""
    try:
        parts = urlsplit(target)
        parts.port  # a port that isn't one raises
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and parts.hostname in hosts and "@" not in parts.netloc


def _filled(text, mark, pattern):
    """`text`, a target rule of youtube.json's ("ytsearch{n}:", "https://…?v={id}"), as a regex: `mark` the pattern."""
    head, tail = text.split(mark, 1)
    return re.escape(head) + pattern + re.escape(tail)


def _target_ok(kind, target, rules, loopback):
    if loopback:
        return _loopback(target, rules["loopback_hosts"])
    targets = rules["targets"]
    if kind == "search":
        # The count the phone asks for alone (youtube.json's search_results), never another.
        count = re.escape(str(rules["search_results"]))
        return re.fullmatch(_filled(targets["search_prefix"], "{n}", count) + ".+", target, re.S) is not None
    vid = targets["video_id"]
    pattern = _filled(targets["watch_url"], "{id}", "(?:" + vid["pattern"] + ")")
    return re.fullmatch(pattern, target, re.I if vid["ignorecase"] else 0) is not None


def _checked(name, value, kind, rules, loopback):
    """None when a placeholder's value passes its check, else the words."""
    if name == "proxy":
        return None if re.fullmatch(rules["proxy_pattern"], value) else NO_GATE
    if name == "qjs":
        return None if value == rules["qjs"] else NOT_QJS
    if name == "cache_dir":
        return None if _same(value, rules["cache_dir"]) and os.path.basename(value) == rules["cache_folder"] else FOLDER
    if name == "into":
        return None if _same(value, rules["into"]) else FOLDER
    if name == "target":
        if _target_ok(kind, value, rules, loopback):
            return None
        return NOT_LOOPBACK if loopback else NOT_YOUTUBE
    return NOT_PHONE_ARGV


def _killtest_child(value, rules):
    """KillTest's child, the one `--exec` form: before the download, the app's qjs on a script in the run's own folder,
    two words of path characters alone (no shell metacharacter, no `{}` for yt-dlp to fill)."""
    if not (isinstance(value, dict) and list(value) == ["before_dl"] and len(value["before_dl"]) == 1):
        return False
    words = value["before_dl"][0].split(" ")
    # The qjs word is the app's own path, exactly (Android's `~~…==` folder names in it, no shell expands them there).
    return (len(words) == 2 and words[0] == rules["qjs"] and _PATH_CHARS.fullmatch(words[1]) is not None
            and words[1].endswith(".js") and _inside(os.path.dirname(words[1]), rules["into"]))


# What the device tests alone may add beside a template, under LOOPBACK alone, each option with its check; and the one
# form of their own, `--version` with the gate (its options those every template gives them, plugins off).
_TEST_FORMS = {
    "no_check_certificate": lambda value, rules: value is True,
    "verbose": lambda value, rules: value is True,
    "exec_cmd": _killtest_child,
}
_VERSION_FORM = ("ignoreconfig", "plugin_dirs", "proxy")


def refusal(argv, rules):
    """Why `argv` isn't run, in words holding none of its values; None for an argv the service runs."""
    rules = json.loads(rules)
    if rules["mode"] not in ("LOOPBACK", "NETWORK"):
        return BAD_MODE
    loopback = rules["mode"] == "LOOPBACK"
    marks = rules["placeholders"]
    try:
        defaults = _quietly([])[0]
        opts, targets, printed = _quietly([str(arg) for arg in argv])
        templates = {kind: _quietly([str(arg) for arg in t]) for kind, t in rules["templates"].items()}
    except (Exception, SystemExit):
        return UNREADABLE
    given = _set(opts, defaults)

    if loopback and printed == {"version"} and not targets and set(given) == set(_VERSION_FORM):
        shared = [_set(t[0], defaults) for t in templates.values()]
        if all(given[o] == s[o] for o in ("ignoreconfig", "plugin_dirs") for s in shared):
            return _checked("proxy", given["proxy"], None, rules, loopback)
    if printed:
        return PRINTS

    if not loopback and rules.get("verbose") and given.get("verbose") is True:
        given.pop("verbose")
    if loopback:
        for name, check in _TEST_FORMS.items():
            if name in given:
                if not check(given.pop(name), rules):
                    return TEST_FORM

    why = NOT_PHONE_ARGV
    for kind, (topts, ttargets, _) in templates.items():
        wanted = _set(topts, defaults)
        if set(given) != set(wanted) or len(targets) != len(ttargets):
            continue
        found = {}
        if not all(_match(wanted[name], given[name], marks, found) for name in wanted):
            continue
        if not all(_match(t, g, marks, found) for t, g in zip(ttargets, targets)):
            continue
        if set(found) != {name for name, mark in marks.items()
                          if any(mark in arg for arg in rules["templates"][kind])}:
            continue
        failed = [w for w in (_checked(name, value, kind, rules, loopback) for name, value in found.items()) if w]
        if not failed:
            return None
        why = failed[0]
    return why


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
