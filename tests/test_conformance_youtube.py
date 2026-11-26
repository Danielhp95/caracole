"""youtube.py's rules for the phone: tests/conformance/data/caracole/youtube/youtube.json, and the vectors
tests/conformance/vectors/youtube/argv.jsonl and classify.jsonl.

youtube.json (no budget, pause or switch: config/config.json holds ``youtube``'s and ``ytimg``'s):

- ``args``: youtube.py's arguments, each a list: ``base`` (``_BASE_ARGS``), ``search`` (``SEARCH_ARGS``), ``video``
  (``VIDEO_ARGS``), ``download`` (the computer's, ``_DOWNLOAD_ARGS``) and ``phone_download`` (``PHONE_DOWNLOAD_ARGS``);
  ``output_name`` (``OUTPUT_NAME``, a download's ``-o`` in its folder);
- ``phone_argv``: for each of ``PHONE_KINDS``, ``phone_argv``'s answer with each argument given as its
  ``placeholders`` name (``<target>``, ``<cache_dir>``, ``<qjs>``, ``<proxy>``, ``<into>``): the phone's argv is that
  list with each placeholder replaced where it stands, so the app holds no flag of its own;
- ``patterns``: ``blocked`` (``_BLOCKED``), ``unavailable`` (``_UNAVAILABLE``), ``status`` (``_STATUS``), ``outdated``
  (``_OUTDATED``), ``pass_over`` (``PHONE_PASS_OVER``) and ``network`` (youtube_fetch.py's ``_NETWORK``), each
  ``{"pattern", "ignorecase"}`` as core.py.PyRegex reads it; ``classes``, ``RUN_CLASSES`` in classify's order;
- ``reason_chars``, ``search_timeout`` and ``download_timeout`` (seconds), ``search_results``, ``max_filesize``,
  ``audio_suffixes``, ``audio_format`` and ``phone_format``;
- ``fetch``: youtube_fetch.py's ``recheck_after_days`` (``RECHECK_AFTER``) and ``give_up_after`` (``GIVE_UP_AFTER``);
- ``search``: youtube_search.py's ``searches_per_hour``, ``asked_for_days`` (``ASKED_FOR``, the 30 days),
  ``failed_for_seconds`` (``FAILED_FOR``) and ``failures_pause``.

How classify reads a run's stderr (classify.jsonl replays it): its lines are ``str.splitlines``, each ``str.strip``ped,
the empty ones dropped; the ERROR line is the last that begins ``ERROR:``, less that word, stripped; ``blocked`` and
``unavailable`` are searched over the whole of stderr, ``pass_over`` and then ``outdated`` over the ERROR line alone.

argv.jsonl: ``{"phone": {what, target, cache_dir, qjs, proxy, into}, "argv": [...]}``, ``phone_argv``'s answer; and
``{"computer": {what, target, cache_dir, into}, "argv": [...]}``, what the computer's ``YtDlp`` gave the fake yt-dlp
(``<tmp>`` the test's folder), no program name in either.

classify.jsonl: ``{"stderr", "exit", "class"}``: ``classify(stderr)`` for a run that exited otherwise than 0; a run
that exited 0 is ``ok`` whatever its stderr says (a ``-v`` log is full of ``[jsc:`` lines), and classify isn't asked.
"""

from __future__ import annotations

import json
import re

import pytest
from helpers.corpus import DATA, VECTORS, check, jsonl
from helpers.fake_ytdlp import FakeYtDlp, entry

from caracole import youtube, youtube_fetch, youtube_search
from caracole.config import ProviderPolicy
from caracole.youtube_urls import watch_url

MADE_BY = "tests/test_conformance_youtube.py"
YOUTUBE_JSON = DATA / "youtube" / "youtube.json"
PLACEHOLDERS = {"target": "<target>", "cache_dir": "<cache_dir>", "qjs": "<qjs>", "proxy": "<proxy>",
                "into": "<into>"}
ID = "dQw4w9WgXcQ"


def _pattern(p: re.Pattern[str]) -> dict:
    assert p.flags & ~(re.UNICODE | re.IGNORECASE) == 0, f"{p.pattern!r}: a flag the phone doesn't read"
    return {"pattern": p.pattern, "ignorecase": bool(p.flags & re.IGNORECASE)}


def _template(what: str) -> list[str]:
    into = PLACEHOLDERS["into"] if what == "download" else None
    return youtube.phone_argv(what, PLACEHOLDERS["target"], cache_dir=PLACEHOLDERS["cache_dir"],
                              qjs=PLACEHOLDERS["qjs"], proxy=PLACEHOLDERS["proxy"], into=into)


def youtube_json() -> str:
    data = {
        "args": {"base": list(youtube._BASE_ARGS), "search": list(youtube.SEARCH_ARGS),
                 "video": list(youtube.VIDEO_ARGS), "download": list(youtube._DOWNLOAD_ARGS),
                 "phone_download": list(youtube.PHONE_DOWNLOAD_ARGS)},
        "output_name": youtube.OUTPUT_NAME,
        "phone_argv": {what: _template(what) for what in youtube.PHONE_KINDS},
        "placeholders": PLACEHOLDERS,
        "patterns": {"blocked": _pattern(youtube._BLOCKED), "unavailable": _pattern(youtube._UNAVAILABLE),
                     "status": _pattern(youtube._STATUS), "outdated": _pattern(youtube._OUTDATED),
                     "pass_over": _pattern(youtube.PHONE_PASS_OVER), "network": _pattern(youtube_fetch._NETWORK)},
        "classes": list(youtube.RUN_CLASSES),
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


def test_the_placeholders_stand_alone_in_the_templates():
    # Each placeholder is in its template exactly where phone_argv puts its argument, and nowhere a flag holds one.
    for what, template in json.loads(youtube_json())["phone_argv"].items():
        given = {"target": "T", "cache_dir": "C", "qjs": "Q", "proxy": "P", "into": "I" if what == "download" else None}
        filled = [_fill(a, given) for a in template]
        assert filled == youtube.phone_argv(what, "T", cache_dir="C", qjs="Q", proxy="P", into=given["into"])


def _fill(arg: str, given: dict) -> str:
    for name, mark in PLACEHOLDERS.items():
        if given[name] is not None:
            arg = arg.replace(mark, given[name])
    return arg


# --- argv.jsonl ---------------------------------------------------------------------------------------------------

PHONE_CASES = [
    ("search", "ytsearch8:Radiohead Creep", None),
    ("search", "ytsearch1:--exec rm -rf ~ Creep", None),  # the query is never an option
    ("search", "ytsearch8:宋冬野 斑马斑马", None),
    ("video", watch_url(ID), None),
    ("download", watch_url(ID), "/data/user/0/io.github.danielhp95.caracole/cache/youtube/.part-12-abc"),
]
QJS = "/data/app/~~x==/io.github.danielhp95.caracole-y==/lib/arm64/libqjs.so"
PROXY = "http://127.0.0.1:40123"
CACHE = "/data/user/0/io.github.danielhp95.caracole/cache/yt-dlp"


@pytest.mark.slow
def test_the_argv_corpus(tmp_path):
    records = []
    for what, target, into in PHONE_CASES:
        given = {"what": what, "target": target, "cache_dir": CACHE, "qjs": QJS, "proxy": PROXY, "into": into}
        records.append({"phone": given, "argv": youtube.phone_argv(what, target, cache_dir=CACHE, qjs=QJS,
                                                                   proxy=PROXY, into=into)})
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
            [("search", f"ytsearch{youtube.SEARCH_RESULTS}:Radiohead Creep", None), ("video", watch_url(ID), None),
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

FAILED = [
    # The computer's own (tests/test_youtube.py): blocked, unavailable, and any other error.
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
    # Passed over: the phone's format, which this video hasn't.
    E + "Requested format is not available. Use --list-formats for a list of available formats",
    "WARNING: [youtube] nsig extraction failed: Some formats may be missing\n"
    + E + "Requested format is not available",
    # Out of date: yt-dlp can't read the page.
    E + "Unable to extract yt initial data; please report this issue on  https://github.com/yt-dlp/yt-dlp/issues",
    E + "Unable to extract player version",
    E + "nsig extraction failed: You may experience throttling for some formats",
    E + "Signature extraction failed: Some formats may be missing",
    E + "Failed to extract any player response; please report this issue on https://github.com/yt-dlp/yt-dlp/issues",
    E + "Precondition check failed.",
    E + "n challenge solving failed: Some formats may be missing",
    "  ERROR:   [youtube] Unable to extract  \n\n",  # spaces around: stripped
    # Words of being out of date off the ERROR line: a warning, a -v line, or no ERROR line at all.
    "WARNING: [youtube] Signature extraction failed: Some formats may be missing\n"
    "ERROR: Unable to download API page: [Errno -3] Temporary failure in name resolution",
    "Unable to extract yt initial data",
    "ERROR: [youtube] Unable to extract player version\nERROR: [youtube] the connection was reset",
    VERBOSE,
    VERBOSE + "\n" + E + "Unable to extract player version",
    VERBOSE + "\n" + E + "Requested format is not available. Use --list-formats for a list of available formats",
    VERBOSE + "\nERROR: unable to download video data: <urlopen error [Errno 104] Connection reset by peer>",
    # Blocked and unavailable come first, anywhere in stderr.
    E + "Unable to extract yt initial data: HTTP Error 429: Too Many Requests",
    "WARNING: [youtube] HTTP Error 403: Forbidden\n" + E + "Requested format is not available",
    E + "Video unavailable\nERROR: Requested format is not available",
    E + "Precondition check failed. This video is not available",
    # The app's gate as the proxy: a refusal (403) and an authentication it asks (407) are errors, never a block or an
    # unavailable video; the phone's runner reads the gate's log first.
    E + ("Unable to download API page: <urlopen error Tunnel connection failed: 403 Forbidden> (caused by "
         "TransportError('<urlopen error Tunnel connection failed: 403 Forbidden>'))"),
    E + ("Unable to download API page: <urlopen error Tunnel connection failed: 407 Proxy Authentication Required> "
         "(caused by TransportError('<urlopen error Tunnel connection failed: 407 Proxy Authentication Required>'))"),
    "ERROR: unable to download video data: <urlopen error Tunnel connection failed: 403 Forbidden>",
    "ERROR: unable to download video data: <urlopen error Tunnel connection failed: 407 Proxy Authentication Required>",
    # Python's own lines and spaces: a line separator, a form feed, a no-break space; and nothing said at all.
    E + "Unable to extract player version " + E + "Requested format is not available",
    "ERROR: first\x0cERROR: Unable to extract player version ",
    "ERROR:",
    "",
    "WARNING: ERROR: Unable to extract player version",
    "error: Unable to extract player version",
    "ERROR: " + "Unable to extract player version " * 20,
]
OK = [VERBOSE, "", "WARNING: [youtube] nsig extraction failed: Some formats may be missing"]


def test_the_classify_corpus():
    records = [{"stderr": s, "exit": 1, "class": youtube.classify(s)} for s in FAILED]
    records += [{"stderr": s, "exit": 0, "class": "ok"} for s in OK]
    assert {r["class"] for r in records} == {*youtube.RUN_CLASSES, "ok"}
    check(VECTORS / "youtube" / "classify.jsonl", jsonl(records, corpus="youtube/classify", made_by=MADE_BY))

