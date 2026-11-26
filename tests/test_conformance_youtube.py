"""youtube.py's rules for the phone: tests/conformance/data/caracole/youtube/youtube.json, and the vectors
tests/conformance/vectors/youtube/argv.jsonl and classify.jsonl.

youtube.json (no budget, pause or switch: config/config.json holds ``youtube``'s and ``ytimg``'s):

- ``args``: youtube.py's arguments, each a list: ``base`` (``_BASE_ARGS``), ``search`` (``SEARCH_ARGS``), ``video``
  (``VIDEO_ARGS``), ``download`` (the computer's, ``_DOWNLOAD_ARGS``) and ``phone_download`` (``PHONE_DOWNLOAD_ARGS``);
  ``output_name`` (``OUTPUT_NAME``, a download's ``-o`` in its folder);
- ``phone_argv``: for each of ``PHONE_KINDS``, ``phone_argv``'s answer with each argument given as its
  ``placeholders`` name (``<target>``, ``<cache_dir>``, ``<qjs>``, ``<proxy>``, ``<into>``), and ``fill``, how the
  phone fills one: each element of a template holds at most one placeholder, alone or after a fixed prefix
  (``quickjs:<qjs>``) or before a fixed suffix (``<into>/audio.%(ext)s``), and it is filled in one pass, its text
  before the placeholder, the value, its text after it: a value is never read again for another placeholder (a target
  that says ``<proxy>`` goes to YouTube as it is, never the gate's address and secret). ``into`` loses its trailing
  ``/`` first; ``cache_dir`` is given as it is (the computer's runner adds ``yt-dlp`` to its own);
- ``targets``: ``search_prefix`` (``SEARCH_PREFIX``, ``{n}`` the results), ``watch_url`` (youtube_urls' ``watch_url``,
  ``{id}`` the video), and ``video_id``'s pattern (youtube_urls' ``VIDEO_ID``, matched whole): a video's or a
  download's target is that address of such an id, else no run;
- ``patterns``: ``blocked`` (``_BLOCKED``), ``unavailable`` (``_UNAVAILABLE``), ``status`` (``_STATUS``), ``outdated``
  (``_OUTDATED``), ``pass_over`` (``PHONE_PASS_OVER``), ``degraded`` (``_DEGRADED``: the challenge solver's warnings,
  yt-dlp 2026.08.19's words) and ``network`` (youtube_fetch.py's ``_NETWORK``), each ``{"pattern", "ignorecase"}`` as
  core.py.PyRegex reads it; ``classes``, ``RUN_CLASSES``;
- ``classify``: how a run that failed is read (classify.jsonl replays it):
  - ``ok_exit``: a run that exits 0 is ``ok`` whatever its stderr says, and classify isn't asked;
  - ``lines``: stderr's lines by ``str.splitlines``, each ``str.strip``ped, the empty ones and those that begin
    ``skip_prefix`` (``[debug]``: under ``-v`` they echo the target) dropped;
  - ``error_prefix`` and ``warning_prefix``: the ERROR line is the last line that begins ``ERROR:``, that word taken
    off and stripped; the warning lines are those that begin ``WARNING:``, whole;
  - ``steps`` in order, the first that matches deciding: ``{"class", "over", "pattern"}`` (``over``: ``stderr``,
    any line read; ``error_line``; ``warning_lines``, any of them), with ``and``, a second ``{"over", "pattern"}``
    that must match too (a pass-over's words after a broken solver's warning: out of date); none matching,
    ``otherwise``. Its first step, ``over`` ``gate_log``, is the phone's runner's, never classify's: a refusal of the
    app's gate (or its 407) is read from the gate's log before stderr is;
- ``reason_chars``, ``search_timeout`` and ``download_timeout`` (seconds), ``search_results``, ``max_filesize``,
  ``audio_suffixes``, ``audio_format`` and ``phone_format``;
- ``fetch``: youtube_fetch.py's ``recheck_after_days`` (``RECHECK_AFTER``) and ``give_up_after`` (``GIVE_UP_AFTER``);
- ``search``: youtube_search.py's ``searches_per_hour``, ``asked_for_days`` (``ASKED_FOR``, the 30 days),
  ``failed_for_seconds`` (``FAILED_FOR``) and ``failures_pause``.

argv.jsonl: ``{"phone": {what, target, cache_dir, qjs, proxy, into}, "argv": [...]}``, ``phone_argv``'s answer (each
also the template filled by ``fill``'s rule); ``{"phone": {...}, "refused": true}`` for a target no run is made of;
and ``{"computer": {what, target, cache_dir, into}, "argv": [...]}``, what the computer's ``YtDlp`` gave the fake
yt-dlp (``<tmp>`` the test's folder, ``cache_dir`` the folder its runner adds ``yt-dlp`` to), no program name in any.

classify.jsonl: ``{"stderr", "exit", "class", "provisional"}``: ``classify(stderr)`` for a run that exited otherwise
than 0, ``ok`` for one that exited 0. ``provisional`` is null for the computer's own samples (tests/test_youtube.py)
and the rules' edges; else it says the text was composed from yt-dlp's source, not taken from a run, and Gate Y0's
logs confirm or replace it.
"""

from __future__ import annotations

import json
import re

import pytest
from helpers.corpus import DATA, VECTORS, check, jsonl
from helpers.fake_ytdlp import FakeYtDlp, entry

from caracole import youtube, youtube_fetch, youtube_search
from caracole.config import ProviderPolicy
from caracole.youtube_urls import VIDEO_ID, watch_url

MADE_BY = "tests/test_conformance_youtube.py"
YOUTUBE_JSON = DATA / "youtube" / "youtube.json"
PLACEHOLDERS = {"target": "<target>", "cache_dir": "<cache_dir>", "qjs": "<qjs>", "proxy": "<proxy>",
                "into": "<into>"}
ID = "dQw4w9WgXcQ"
PROVISIONAL = "composed from yt-dlp's source, not from a run; Gate Y0's logs confirm or replace it"
FILL = ("each element holds at most one placeholder, alone, after a fixed prefix or before a fixed suffix; it is "
        "filled in one pass (before + value + after) and a value is never read again; into loses its trailing '/' "
        "first; cache_dir is given as it is")
GATE_STEP = {"class": "gate", "over": "gate_log",
             "note": "the phone's runner's, before stderr is read: a refusal of the app's gate, or its 407, is "
                     "decided from the gate's log; classify never sees it"}


def _pattern(p: re.Pattern[str]) -> dict:
    assert p.flags & ~(re.UNICODE | re.IGNORECASE) == 0, f"{p.pattern!r}: a flag the phone doesn't read"
    return {"pattern": p.pattern, "ignorecase": bool(p.flags & re.IGNORECASE)}


def _template(what: str) -> list[str]:
    into = PLACEHOLDERS["into"] if what == "download" else None
    return youtube._phone_args(what, PLACEHOLDERS["target"], cache_dir=PLACEHOLDERS["cache_dir"],
                               qjs=PLACEHOLDERS["qjs"], proxy=PLACEHOLDERS["proxy"], into=into)


def youtube_json() -> str:
    data = {
        "args": {"base": list(youtube._BASE_ARGS), "search": list(youtube.SEARCH_ARGS),
                 "video": list(youtube.VIDEO_ARGS), "download": list(youtube._DOWNLOAD_ARGS),
                 "phone_download": list(youtube.PHONE_DOWNLOAD_ARGS)},
        "output_name": youtube.OUTPUT_NAME,
        "phone_argv": {what: _template(what) for what in youtube.PHONE_KINDS},
        "placeholders": PLACEHOLDERS,
        "fill": FILL,
        "targets": {"search_prefix": youtube.SEARCH_PREFIX, "watch_url": watch_url("{id}"),
                    "video_id": _pattern(VIDEO_ID)},
        "patterns": {"blocked": _pattern(youtube._BLOCKED), "unavailable": _pattern(youtube._UNAVAILABLE),
                     "status": _pattern(youtube._STATUS), "outdated": _pattern(youtube._OUTDATED),
                     "pass_over": _pattern(youtube.PHONE_PASS_OVER), "degraded": _pattern(youtube._DEGRADED),
                     "network": _pattern(youtube_fetch._NETWORK)},
        "classes": list(youtube.RUN_CLASSES),
        "classify": {
            "ok_exit": 0,
            "lines": "str.splitlines, each str.strip()ped; empty lines and those beginning skip_prefix dropped",
            "skip_prefix": youtube.DEBUG_PREFIX,
            "error_prefix": youtube.ERROR_PREFIX,
            "warning_prefix": youtube.WARNING_PREFIX,
            "steps": [GATE_STEP, *({"class": cls, "over": over, "pattern": pattern,
                                    **({"and": {"over": also[0], "pattern": also[1]}} if also else {})}
                                   for cls, over, pattern, also in youtube.CLASSIFY_STEPS)],
            "otherwise": "error",
        },
        "reason_chars": youtube.REASON_CHARS,
        "search_timeout": youtube.SEARCH_TIMEOUT,
        "download_timeout": youtube.DOWNLOAD_TIMEOUT,
        "search_results": youtube.SEARCH_RESULTS,
        "max_filesize": youtube.MAX_FILESIZE,
        "audio_suffixes": list(youtube.AUDIO_SUFFIXES),
        "audio_format": youtube.AUDIO_FORMAT,
        "phone_format": youtube.PHONE_FORMAT,
        "fetch": {"recheck_after_days": youtube_fetch.RECHECK_AFTER.days,
                  "give_up_after": youtube_fetch.GIVE_UP_AFTER},
        "search": {"searches_per_hour": youtube_search.SEARCHES_PER_HOUR,
                   "asked_for_days": youtube_search.ASKED_FOR.days,
                   "failed_for_seconds": int(youtube_search.FAILED_FOR.total_seconds()),
                   "failures_pause": youtube_search.FAILURES_PAUSE},
    }
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def test_youtube_json_is_youtube_pys_rules():
    check(YOUTUBE_JSON, youtube_json())


def test_the_whole_days_and_seconds_are_whole():
    assert youtube_fetch.RECHECK_AFTER.total_seconds() == youtube_fetch.RECHECK_AFTER.days * 86400
    assert youtube_search.ASKED_FOR.total_seconds() == youtube_search.ASKED_FOR.days * 86400
    assert youtube_search.FAILED_FOR.total_seconds() == int(youtube_search.FAILED_FOR.total_seconds())


def test_each_element_of_a_template_holds_one_placeholder_at_most():
    for template in json.loads(youtube_json())["phone_argv"].values():
        for arg in template:
            assert sum(arg.count(mark) for mark in PLACEHOLDERS.values()) <= 1, arg


def fill(template: list[str], given: dict) -> list[str]:
    """The phone's argv from a template, by youtube.json's ``fill``: each element in one pass."""
    out = []
    for arg in template:
        for name, mark in PLACEHOLDERS.items():
            if mark in arg:
                before, after = arg.split(mark, 1)
                value = given[name].rstrip("/") if name == "into" else given[name]
                arg = before + value + after
                break
        out.append(arg)
    return out


# --- argv.jsonl ---------------------------------------------------------------------------------------------------

PHONE_CASES = [
    ("search", "ytsearch8:Radiohead Creep", None),
    ("search", "ytsearch1:--exec rm -rf ~ Creep", None),  # the query is never an option
    ("search", "ytsearch8:宋冬野 斑马斑马", None),
    ("video", watch_url(ID), None),
    ("download", watch_url(ID), "/data/user/0/io.github.danielhp95.caracole/cache/youtube/.part-12-abc"),
    ("download", watch_url(ID), "/data/user/0/io.github.danielhp95.caracole/cache/youtube/.part-12-abc/"),
    ("download", watch_url(ID), "/data/x//y///"),
    # Placeholders in what a song's name gives: sent as they are, never filled.
    ("search", "ytsearch1:<proxy> <into> <qjs> <cache_dir> <target>", None),
    ("search", "ytsearch1:<proxy><proxy>", None),
]
REFUSED = [
    ("video", "https://www.youtube.com/watch?v=short", None),
    ("video", "https://youtu.be/dQw4w9WgXcQ", None),
    ("download", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL1", "/a"),
    ("download", "dQw4w9WgXcQ", "/a"),
    ("download", "https://www.youtube.com/watch?v=dQw4w9WgXc!", "/a"),
]
QJS = "/data/app/~~x==/io.github.danielhp95.caracole-y==/lib/arm64/libqjs.so"
# The gate's address, as the phone gives it: its user and secret in it.
PROXIES = ["http://127.0.0.1:40123", "http://caracole:Zm9v-YmFy_<qjs>@127.0.0.1:40123"]
CACHE = "/data/user/0/io.github.danielhp95.caracole/cache/yt-dlp"


@pytest.mark.slow
def test_the_argv_corpus(tmp_path):
    records = []
    templates = json.loads(youtube_json())["phone_argv"]
    for proxy in PROXIES:
        for what, target, into in PHONE_CASES:
            given = {"what": what, "target": target, "cache_dir": CACHE, "qjs": QJS, "proxy": proxy, "into": into}
            argv = youtube.phone_argv(what, target, cache_dir=CACHE, qjs=QJS, proxy=proxy, into=into)
            assert fill(templates[what], given) == argv
            assert argv[-1] == target and argv.count(proxy) == 1
            records.append({"phone": given, "argv": argv})
    for what, target, into in REFUSED:
        with pytest.raises(ValueError, match="not a YouTube video"):
            youtube.phone_argv(what, target, cache_dir=CACHE, qjs=QJS, proxy=PROXIES[0], into=into)
        given = {"what": what, "target": target, "cache_dir": CACHE, "qjs": QJS, "proxy": PROXIES[0], "into": into}
        records.append({"phone": given, "refused": True})
    fake = FakeYtDlp(tmp_path / "bin")
    fake.search("Radiohead Creep", entry(ID, "Creep", "Radiohead - Topic", 239))
    fake.video(ID, "Creep", "Radiohead - Topic", 239)
    into = tmp_path / "into"
    into.mkdir()
    yt = youtube.YtDlp(fake.bin, ProviderPolicy(budget=6, delay=(0, 0)), tmp_path / "cache", sleep=lambda s: None)
    yt.search("Radiohead Creep")
    yt.video(ID)
    yt.download(ID, into)
    shown = str(tmp_path)
    for (what, target, folder), argv in zip(
            [("search", youtube.SEARCH_PREFIX.format(n=youtube.SEARCH_RESULTS) + "Radiohead Creep", None),
             ("video", watch_url(ID), None),
             ("download", watch_url(ID), "<tmp>/into")], fake.argvs()):
        given = {"what": what, "target": target, "cache_dir": "<tmp>/cache", "into": folder}
        records.append({"computer": given, "argv": [a.replace(shown, "<tmp>") for a in argv]})
    check(VECTORS / "youtube" / "argv.jsonl", jsonl(records, corpus="youtube/argv", made_by=MADE_BY))


# --- classify.jsonl -----------------------------------------------------------------------------------------------

E = f"ERROR: [youtube] {ID}: "
VERBOSE = "\n".join([
    "[debug] Command-line config: ['-v', '--ignore-config', '--no-js-runtimes', '--js-runtimes', "
    "'quickjs:/data/app/lib/arm64/libqjs.so', '--proxy', 'http://127.0.0.1:40123', '--', "
    "'https://www.youtube.com/watch?v=dQw4w9WgXcQ']",
    "[debug] Encodings: locale utf-8, fs utf-8, pref utf-8, out utf-8, error utf-8, screen utf-8",
    "[debug] yt-dlp version stable@2026.11.23 from yt-dlp/yt-dlp [abc123] (pip)",
    "[debug] Python 3.13.9 (CPython aarch64 64bit) - Linux-6.1.75-android14-aarch64-with-libc",
    "[debug] exe versions: none",
    "[debug] Optional libraries: certifi-2026.10.23, sqlite3-3.49.1, ssl-OpenSSL 3.0.15, yt_dlp_ejs-0.3.1",
    "[debug] JS runtimes: quickjs-2025-04-26",
    "[debug] Proxy map: {'all': 'http://127.0.0.1:40123'}",
    "[debug] Request Handlers: urllib",
    "[debug] Loaded 1867 extractors",
    f"[youtube] Extracting URL: https://www.youtube.com/watch?v={ID}",
    f"[youtube] {ID}: Downloading webpage",
    f"[youtube] {ID}: Downloading tv client config",
    f"[youtube] {ID}: Downloading player 1a2b3c4d-main",
    f"[youtube] {ID}: Downloading tv player API JSON",
    "[debug] [youtube] [jsc:quickjs] Solving JS challenges using quickjs",
    "[youtube] [jsc:quickjs] Solving JS challenges using quickjs",
    "[debug] [jsc:quickjs] Using challenge solver lib script from yt_dlp_ejs (version 0.3.1)",
    "[debug] [jsc:quickjs] Using challenge solver core script from yt_dlp_ejs (version 0.3.1)",
    f"[debug] [youtube] {ID}: n challenge solved: 'AbCdEfGh' -> 'XyZ12'",
    "[info] Testing format 140",
    f"[info] {ID}: Downloading 1 format(s): 140",
    "[debug] Invoking http downloader on \"https://rr3---sn-abc.googlevideo.com/videoplayback?...\"",
    "[download] Destination: /data/user/0/io.github.danielhp95.caracole/cache/youtube/.part-12-abc/audio.m4a",
    "[download] 100% of    3.43MiB in 00:00:04 at 805.12KiB/s",
    "WARNING: [youtube] Possible MPEG-TS in MP4 container or malformed AAC timestamps. Install ffmpeg to fix this",
])

# The computer's own samples (tests/test_youtube.py): blocked, unavailable, and any other error.
COMPUTERS = [
    E + "Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies for the authentication.",
    E + "Sign in to confirm you're not a bot. This helps protect our community.",
    "ERROR: unable to download video data: HTTP Error 429: Too Many Requests",
    "ERROR: unable to download video data: HTTP Error 403: Forbidden",
    E + ("This content isn't available, try again later. The current session has been rate-limited by YouTube for up "
         "to an hour."),
    E + "Video unavailable",
    E + "Video unavailable. This video has been removed by the uploader",
    E + "Private video. Sign in if you've been granted access to this video",
    E + "Sign in to confirm your age. This video may be inappropriate for some users.",
    E + "The uploader has not made this video available in your country",
    E + "Join this channel to get access to members-only content like this video",
    E + "This video is DRM protected",
    E + "This video is not available",
    E + "This video is unavailable",
    "WARNING: something\nERROR: Unable to download API page: [Errno -3] Temporary failure in name resolution",
]
NO_FORMAT = E + "Requested format is not available. Use --list-formats for a list of available formats"
HELP = ("Ensure you have a supported JavaScript runtime and challenge solver script distribution installed. Review any "
        "warnings presented before this message. For more details, refer to  https://github.com/yt-dlp/yt-dlp/wiki/EJS")
# PROVISIONAL: every text below is composed from yt-dlp's source (2026.08.19, the flake's), not taken from a run.
SOLVER_BROKE = [  # its warnings, then no m4a left: out of date, never this video's pass-over
    f"WARNING: [youtube] {ID}: n challenge solving failed: Some formats may be missing. {HELP}",
    f"WARNING: [youtube] {ID}: Signature solving failed: Some formats may be missing. {HELP}",
    'WARNING: [youtube] [jsc] Error solving n challenge request using "quickjs" provider: Exit code 1.',
    'WARNING: [youtube] [jsc] Error solving 2 challenge requests using "quickjs" provider: timed out.',
    ("WARNING: [youtube] No supported JavaScript runtime could be found. Only deno is enabled by default; to use "
     "another runtime add  --js-runtimes RUNTIME[:PATH]  to your command/config."),
    ("WARNING: [youtube] [jsc] Challenge solver lib script version 0.2.0 is not supported (source: python package, "
     "variant: minified, supported version: 0.3.1)"),
    ("WARNING: [youtube] [jsc] Hash mismatch on challenge solver core script (source: cache, variant: minified, "
     "hash: x)!"),
    "WARNING: [youtube] [jsc] Failed to load challenge solver lib script from python package: No module named x",
    "WARNING: [youtube] [jsc] Failed to read builtin challenge solver core script",
    "WARNING: [youtube] nsig extraction failed: Some formats may be missing",  # earlier yt-dlp's words
]
PASSED_OVER = [  # the phone's format, which this video hasn't
    NO_FORMAT,
    "WARNING: [youtube] Some web client https formats have been skipped as they are missing a url.\n" + NO_FORMAT,
    f"[debug] WARNING: [youtube] {ID}: n challenge solving failed: Some formats may be missing.\n" + NO_FORMAT,
    f"[youtube] {ID}: n challenge solving failed\n" + NO_FORMAT,  # no WARNING line: nothing said of the solver
]
OUTDATED = [  # yt-dlp can't read the page
    E + "Unable to extract yt initial data; please report this issue on  https://github.com/yt-dlp/yt-dlp/issues",
    E + "Unable to extract player version",
    E + "nsig extraction failed: You may experience throttling for some formats",
    E + "Signature extraction failed: Some formats may be missing",
    E + "Failed to extract any player response; please report this issue on https://github.com/yt-dlp/yt-dlp/issues",
    E + "Precondition check failed.",
    E + "n challenge solving failed: Some formats may be missing",
]
OFF_THE_LINE = [  # an out of date's words off the ERROR line: a warning, a -v line, or no ERROR line at all
    "WARNING: [youtube] Signature extraction failed: Some formats may be missing\n"
    "ERROR: Unable to download API page: [Errno -3] Temporary failure in name resolution",
    f"WARNING: [youtube] {ID}: n challenge solving failed: Some formats may be missing.\n"
    "ERROR: unable to download video data: HTTP Error 503: Service Unavailable",
    "Unable to extract yt initial data",
    "ERROR: [youtube] Unable to extract player version\nERROR: [youtube] the connection was reset",
    VERBOSE,
    VERBOSE + "\n" + E + "Unable to extract player version",
    VERBOSE + "\n" + NO_FORMAT,
    VERBOSE + "\nERROR: unable to download video data: <urlopen error [Errno 104] Connection reset by peer>",
    # -v echoes the command line, the target in it: no [debug] line is read.
    "[debug] Command-line config: ['-v', '--', 'ytsearch1:captcha not a bot Video unavailable']\n"
    "ERROR: Unable to download API page: [Errno -3] Temporary failure in name resolution",
]
FIRST = [  # blocked and unavailable come first, anywhere in stderr
    E + "Unable to extract yt initial data: HTTP Error 429: Too Many Requests",
    "WARNING: [youtube] HTTP Error 403: Forbidden\n" + NO_FORMAT,
    f"WARNING: [youtube] {ID}: n challenge solving failed: Some formats may be missing.\n"
    + E + "Video unavailable",
    E + "Video unavailable\nERROR: Requested format is not available",
    E + "Precondition check failed. This video is not available",
]
GATE = [  # the app's gate as the proxy: a refusal (403) and an authentication it asks (407) are errors
    E + ("Unable to download API page: <urlopen error Tunnel connection failed: 403 Forbidden> (caused by "
         "TransportError('<urlopen error Tunnel connection failed: 403 Forbidden>'))"),
    E + ("Unable to download API page: <urlopen error Tunnel connection failed: 407 Proxy Authentication Required> "
         "(caused by TransportError('<urlopen error Tunnel connection failed: 407 Proxy Authentication Required>'))"),
    "ERROR: unable to download video data: <urlopen error Tunnel connection failed: 403 Forbidden>",
    "ERROR: unable to download video data: <urlopen error Tunnel connection failed: 407 Proxy Authentication Required>",
]
# The rules' edges, no wording of yt-dlp's: Python's lines and spaces (a line separator, a form feed, a no-break
# space), spaces around, nothing said at all, and what is no ERROR line.
EDGES = [
    "  ERROR:   [youtube] Unable to extract  \n\n",
    E + "Unable to extract player version\u2028" + NO_FORMAT,
    "ERROR: first\x0cERROR:\u00a0Unable to extract player version\u00a0",
    "ERROR:",
    "",
    "WARNING: ERROR: Unable to extract player version",
    "error: Unable to extract player version",
    "ERROR: " + "Unable to extract player version " * 20,
    "  WARNING:  [youtube] n challenge solving failed\n" + NO_FORMAT,
]
OK = [VERBOSE, "", f"WARNING: [youtube] {ID}: n challenge solving failed: Some formats may be missing."]


def test_the_classify_corpus():
    records = [{"stderr": s, "exit": 1, "class": youtube.classify(s), "provisional": None} for s in COMPUTERS]
    records += [{"stderr": f"{w}\n{NO_FORMAT}", "exit": 1, "class": youtube.classify(f"{w}\n{NO_FORMAT}"),
                 "provisional": PROVISIONAL} for w in SOLVER_BROKE]
    for texts in (PASSED_OVER, OUTDATED, OFF_THE_LINE, FIRST, GATE):
        records += [{"stderr": s, "exit": 1, "class": youtube.classify(s), "provisional": PROVISIONAL} for s in texts]
    records += [{"stderr": s, "exit": 1, "class": youtube.classify(s), "provisional": None} for s in EDGES]
    records += [{"stderr": s, "exit": 0, "class": "ok", "provisional": PROVISIONAL if s else None} for s in OK]
    assert all(r["class"] == "outdated" for r in records[len(COMPUTERS):len(COMPUTERS) + len(SOLVER_BROKE)])
    assert {youtube.classify(s) for s in PASSED_OVER} == {"pass_over"}
    assert {youtube.classify(s) for s in GATE} == {"error"}
    assert {r["class"] for r in records} == {*youtube.RUN_CLASSES, "ok"}
    check(VECTORS / "youtube" / "classify.jsonl", jsonl(records, corpus="youtube/classify", made_by=MADE_BY))

