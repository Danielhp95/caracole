"""youtube.py's rules for the phone: tests/conformance/data/caracole/youtube/youtube.json, and the vectors
tests/conformance/vectors/youtube/argv.jsonl, classify.jsonl, parse.jsonl and choose.jsonl (android's core.youtube
replays them: YouTubeReplay, area ``youtube``).

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
  ``{id}`` the video), and ``video_id``'s pattern (youtube_urls' ``VIDEO_ID``, with no anchors: ``video_id_matched``
  ``whole``, re.fullmatch); ``rule``: a video's or a download's target is exactly that address of such an id, else no
  run;
- ``refuse``: what else no run is made of (``rule``): a value of ``no_nul`` (youtube.py's ``NO_NUL``) that holds
  ``nul``, an empty search target (``empty_search``), a download whose ``into`` is empty once its trailing ``/`` go
  (``empty_into``);
- ``patterns``: ``blocked`` (``_BLOCKED``), ``unavailable`` (``_UNAVAILABLE``), ``status`` (``_STATUS``), ``outdated``
  (``_OUTDATED``), ``pass_over`` (``PHONE_PASS_OVER``), ``degraded`` (``_DEGRADED``: the challenge solver's warnings,
  yt-dlp 2026.08.19's words) and ``network`` (youtube_fetch.py's ``_NETWORK``), each ``{"pattern", "ignorecase"}`` as
  core.py.PyRegex reads it; ``classes``, ``RUN_CLASSES``;
- ``classify``: how a run that failed is read (classify.jsonl replays it):
  - ``order``: the gate's log first, then the exit status, then the steps;
  - ``ok_exit`` and ``ok_class``: a run that exits 0 is ``ok`` whatever its stderr says, and classify isn't asked;
  - ``lines``: stderr's lines by ``str.splitlines``, each ``str.strip``ped, the empty ones and those that begin
    ``skip_prefix`` (``[debug]``: under ``-v`` they echo the target) dropped;
  - ``error_prefix`` and ``warning_prefix``: the ERROR line is the last line that begins ``ERROR:``, that word taken
    off and stripped; the warning lines are those that begin ``WARNING:``, whole;
  - ``over``: what each step's ``over`` reads, in words;
  - ``steps`` in order, the first that matches deciding: ``{"class", "over", "pattern"}`` (``over``: ``stderr``,
    any line read; ``error_line``; ``warning_lines``, any of them), with ``and``, a second ``{"over", "pattern"}``
    that must match too (a pass-over's words after a broken solver's warning: out of date); none matching,
    ``otherwise``. Its first step, ``over`` ``gate_log``, is the phone's runner's, never classify's: a refusal of the
    app's gate (or its 407) is read from the gate's log before stderr is;
- ``reason_chars``, ``search_timeout`` and ``download_timeout`` (seconds), ``search_results``, ``max_filesize``,
  ``audio_suffixes``, ``audio_format`` and ``phone_format``;
- ``answers``: what parse_search and parse_video read and say: ``provider``, ``live_statuses`` (``LIVE_STATUSES``: a
  stream), ``shorts_path`` (``SHORTS_PATH``, in a result's url: a short), and the words of an answer that can't be
  read (``search_not_json``, ``video_not_json``, ``{}`` json's error; ``no_such_video``), a ProviderError's;
  ``search_query`` (``SEARCH_QUERY``: ``{artist}`` stripped, ``{title}`` clean_title'd, filled in one pass);
- ``choose``: choose's rules: its ``patterns`` (``_PARTS``, ``_QUOTED``, ``_UNWANTED``, ``_KARAOKE_CHANNEL``,
  ``_TOPIC``, ``_CHANNEL_SUFFIX``, ``_OFFICIAL_AUDIO``, ``_OFFICIAL_VIDEO``, ``_CJK_LETTER``, ``_SCRIPT_RUN``),
  ``variant`` (``_VARIANT``, ``{variant}`` title_variant's word), the words (``decoration``, ``cjk_decoration`` as
  compact(slug_key) makes them, ``own_channel``), ``cjk_width``, the lengths (seconds) and ``exact`` and ``alone``,
  and ``key``, in words, the order of the videos that fit;
- ``fetch``: youtube_fetch.py's ``recheck_after_days`` (``RECHECK_AFTER``) and ``give_up_after`` (``GIVE_UP_AFTER``);
- ``search``: youtube_search.py's ``searches_per_hour``, ``asked_for_days`` (``ASKED_FOR``, the 30 days),
  ``failed_for_seconds`` (``FAILED_FOR``) and ``failures_pause``;
- ``gate``: the phone's gate (``PHONE_GATE``, which the computer never reads: it has no gate): ``names``, and a name
  under one of ``suffixes``, on ``port`` by CONNECT; ``apart``, allowed and reported apart; ``refused``, by name in
  every mode; ``refusal``, a run's error when the gate refused a host (``{host}``), read from its log first;
- ``runner``: ``YtDlp``'s words and folder: ``cache_folder`` (``CACHE_FOLDER``, under the cache folder given),
  ``budget_spent`` (``{budget}``), ``blocked_earlier``, ``unavailable_said`` (``{reason}``), ``timed_out``
  (``{timeout:g}``, Python's ``format(timeout, "g")``), ``said_nothing`` (a failed run's reason when stderr has no
  line), ``reason_cut`` (what ends a reason cut to ``reason_chars``), ``no_audio_left`` (``{folder}``, the folder's
  name) and
  ``block_statuses`` (a block's status when stderr names one of them, else none).

argv.jsonl: ``{"phone": {what, target, cache_dir, qjs, proxy, into}, "argv": [...]}``, ``phone_argv``'s answer (each
also the template filled by ``fill``'s rule); ``{"phone": {...}, "refused": true}`` for a target no run is made of;
the same for a value holding a NUL, an empty search and an empty download folder;
and ``{"computer": {what, target, cache_dir, into}, "argv": [...]}``, what the computer's ``YtDlp`` gave the fake
yt-dlp (``<tmp>`` the test's folder, ``cache_dir`` the folder its runner adds ``yt-dlp`` to), no program name in any.

parse.jsonl: ``{"fn": "parse_search", "text"}`` and ``{"fn": "parse_video", "text", "id"}`` with ``videos`` or
``video`` (each ``[id, title, channel, duration as Python's repr or null, live, short]``) or ``error``
(``ProviderError`` with its ``message``, null where Python's json nests deeper than the phone's reads; or
``OverflowError``, float() of an int too big for one); ``{"fn": "search_query", "artist", "title", "query"}``.

choose.jsonl: ``{"song": [artist, title, artists], "videos": [[id, title, channel, duration, live, short]...],
"expected", "skip", "chosen", "ranked"}``: ``choose``'s video's id (or null), and ``_ranked``'s videos that fit, each
``[id, tier, -title, closeness, -official, rank]``: test_youtube.py's cases, CJK, live, short and karaoke titles, and
seeded draws of their songs and videos.

classify.jsonl: ``{"stderr", "exit", "class", "provisional"}``: ``classify(stderr)`` for a run that exited otherwise
than 0, ``ok`` for one that exited 0. ``provisional`` is null for the computer's own samples (tests/test_youtube.py)
and the rules' edges; else it says the text was composed from yt-dlp's source, not taken from a run, and Gate Y0's
logs confirm or replace it.

runs.jsonl: the computer's ``YtDlp`` over FakeYtDlp, a scenario a record (test_youtube.py's: the budget and the pace,
blocks, unavailable videos, any other error, a timeout, a download; and a pass-over and an out of date run, which the
computer reads as errors): ``{"scenario", "budget", "delay", "timeouts", "draws", "calls", "events", "slept",
"requests_made", "block"}``. ``draws`` are the policy's ``uniform`` draws in order; the clock moves only by ``slept``
and each call's ``gap`` (the caller's time before it). Each call is ``{"call", "arg", "gap", "argv", "ran",
"classify", "outcome"}``: ``argv`` the run's kind, target and ``into`` (``<into>``: the folder given) as the phone's
template fills them, null for no process; ``ran`` what the process gave (``exit``, ``stdout``, ``stderr``; or
``timed_out``) and, for a download, the file it ``writes`` in ``into``; ``classify`` youtube.classify of a failed
run's stderr (null for an ok, a timed out or no run), beside the computer's own reading; ``outcome`` what the call
returned (a search's ids, a video's or a download's ``[id, title, channel, duration]`` and its ``file``) or
``raised`` (the class, ``message`` its str()). ``events`` ``[url, status, decision, message]`` each, in order;
``block`` the computer's ``record_block`` of the first block (its message, the cooldown's hours after the run's start).
"""

from __future__ import annotations

import dataclasses
import json
import random
import re
import subprocess
from datetime import UTC, datetime

import pytest
from helpers.corpus import DATA, VECTORS, check, jsonl
from helpers.fake_ytdlp import FakeYtDlp, entry

from caracole import db, health, youtube, youtube_fetch, youtube_search
from caracole.config import ProviderPolicy
from caracole.http import BudgetExhausted, ProviderError
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
TARGET_RULE = ("a video's or a download's target is exactly watch_url of an id video_id matches whole (re.fullmatch, "
               "the pattern having no anchors), else no run is made")
REFUSE_RULE = ("no run is made of a value in no_nul that holds a NUL, of an empty search target, or of a download whose "
               "into is empty once its trailing '/' are taken off")
ORDER = ("the gate's log first (its step, the runner's), then the exit status (ok_exit is ok_class whatever stderr "
         "says), then the steps over stderr")
OVER = {"stderr": "every line read", "error_line": "the last line read that begins error_prefix, that word taken off "
        "and the rest str.strip()ped: one line or none", "warning_lines": "every line read that begins warning_prefix, "
        "whole", "gate_log": "the app's gate's log of the run, never stderr"}
CHOOSE_KEY = ("of the videos that fit, the least of (tier, -title, closeness, -official, rank): tier 1 for a version "
              "unwanted or not the song's own variant, else 0; title exact or alone; closeness 0 to 3 (3 with no "
              "length); official 3 the artist's Topic channel, 2 official audio, 1 the artist's own channel or an "
              "official video, else 0; rank the search's order")
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
                    "video_id": _pattern(VIDEO_ID), "video_id_matched": "whole",
                    "rule": TARGET_RULE},
        "refuse": {"no_nul": list(youtube.NO_NUL), "nul": "\0", "empty_search": True, "empty_into": True,
                   "rule": REFUSE_RULE},
        "patterns": {"blocked": _pattern(youtube._BLOCKED), "unavailable": _pattern(youtube._UNAVAILABLE),
                     "status": _pattern(youtube._STATUS), "outdated": _pattern(youtube._OUTDATED),
                     "pass_over": _pattern(youtube.PHONE_PASS_OVER), "degraded": _pattern(youtube._DEGRADED),
                     "network": _pattern(youtube_fetch._NETWORK)},
        "classes": list(youtube.RUN_CLASSES),
        "classify": {
            "ok_exit": 0,
            "ok_class": "ok",
            "order": ORDER,
            "lines": "str.splitlines, each str.strip()ped; empty lines and those beginning skip_prefix dropped",
            "skip_prefix": youtube.DEBUG_PREFIX,
            "error_prefix": youtube.ERROR_PREFIX,
            "warning_prefix": youtube.WARNING_PREFIX,
            "over": OVER,
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
        "answers": {"provider": youtube.PROVIDER, "live_statuses": list(youtube.LIVE_STATUSES),
                    "shorts_path": youtube.SHORTS_PATH, "search_not_json": youtube.SEARCH_NOT_JSON,
                    "video_not_json": youtube.VIDEO_NOT_JSON, "no_such_video": youtube.NO_SUCH_VIDEO},
        "search_query": youtube.SEARCH_QUERY,
        "choose": {
            "patterns": {name: _pattern(p) for name, p in (
                ("parts", youtube._PARTS), ("quoted", youtube._QUOTED), ("unwanted", youtube._UNWANTED),
                ("karaoke_channel", youtube._KARAOKE_CHANNEL), ("topic", youtube._TOPIC),
                ("channel_suffix", youtube._CHANNEL_SUFFIX), ("official_audio", youtube._OFFICIAL_AUDIO),
                ("official_video", youtube._OFFICIAL_VIDEO), ("cjk_letter", youtube._CJK_LETTER),
                ("script_run", youtube._SCRIPT_RUN))},
            "variant": youtube._VARIANT,
            "decoration": sorted(youtube._DECORATION),
            "cjk_decoration": sorted(youtube._CJK_DECORATION),
            "own_channel": list(youtube._OWN_CHANNEL),
            "cjk_width": youtube.CJK_WIDTH,
            "tolerance_s": youtube.TOLERANCE_S, "synced_s": youtube.SYNCED_S, "close_s": youtube.CLOSE_S,
            "shortest_s": youtube.SHORTEST_S, "longest_s": youtube.LONGEST_S,
            "exact": youtube.EXACT, "alone": youtube.ALONE,
            "key": CHOOSE_KEY,
        },
        "search": {"searches_per_hour": youtube_search.SEARCHES_PER_HOUR,
                   "asked_for_days": youtube_search.ASKED_FOR.days,
                   "failed_for_seconds": int(youtube_search.FAILED_FOR.total_seconds()),
                   "failures_pause": youtube_search.FAILURES_PAUSE},
        "gate": {"names": list(youtube.PHONE_GATE.names), "suffixes": list(youtube.PHONE_GATE.suffixes),
                 "port": youtube.PHONE_GATE.port, "apart": list(youtube.PHONE_GATE.apart),
                 "refused": list(youtube.PHONE_GATE.refused), "refusal": youtube.PHONE_GATE.refusal},
        "runner": {"cache_folder": youtube.CACHE_FOLDER, "budget_spent": youtube.BUDGET_SPENT,
                   "blocked_earlier": youtube.BLOCKED_EARLIER, "unavailable_said": youtube.UNAVAILABLE_SAID,
                   "timed_out": youtube.TIMED_OUT, "said_nothing": youtube.SAID_NOTHING,
                   "no_audio_left": youtube.NO_AUDIO_LEFT, "reason_cut": youtube.REASON_CUT,
                   "block_statuses": list(youtube.BLOCK_STATUSES)},
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
def _refused_values() -> list[dict]:
    """A NUL in each value phone_argv takes, an empty search, and a download into an empty folder or the root."""
    found = []
    for name in youtube.NO_NUL:
        for what in ("search", "video", "download"):
            given = {"what": what, "target": "ytsearch8:Radiohead Creep" if what == "search" else watch_url(ID),
                     "cache_dir": CACHE, "qjs": QJS, "proxy": PROXIES[1],
                     "into": "/a/b" if what == "download" else None}
            if given[name] is None:
                continue
            given[name] = given[name][:3] + "\0" + given[name][3:]
            found.append(given)
    found.append({"what": "search", "target": "", "cache_dir": CACHE, "qjs": QJS, "proxy": PROXIES[0], "into": None})
    for into in ("", "/", "///"):
        found.append({"what": "download", "target": watch_url(ID), "cache_dir": CACHE, "qjs": QJS,
                      "proxy": PROXIES[0], "into": into})
    return found


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
    for given in _refused_values():
        with pytest.raises(ValueError, match="NUL|empty"):
            youtube.phone_argv(given["what"], given["target"], cache_dir=given["cache_dir"], qjs=given["qjs"],
                               proxy=given["proxy"], into=given["into"])
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



# --- parse.jsonl --------------------------------------------------------------------------------------------------

def _video(v: youtube.Video) -> list:
    """A video as a record holds it: its duration as Python's repr (``nan``, ``inf`` too), or null."""
    return [v.id, v.title, v.channel, None if v.duration is None else repr(v.duration), v.live, v.short]


DEEPEST = 512  # the phone's json reads no deeper (core.json.PyJson.MAX_DEPTH): past it, its words are its own


def _answer(read, text: str) -> dict:
    """What a parse came to: its videos, or what it raised (a ProviderError's words, but where Python's json went
    deeper than the phone's reads)."""
    try:
        found = read()
    except youtube.ProviderError as e:
        deep = isinstance(e.__cause__, RecursionError) or text.count("[") + text.count("{") > DEEPEST
        return {"error": "ProviderError", "message": None if deep else str(e)}
    except OverflowError:  # float() of an int too big for one, as Python raises it out of the parse
        return {"error": "OverflowError"}
    return {"videos": [_video(v) for v in found]} if isinstance(found, list) else {"video": _video(found)}


# test_youtube.py's flat search, then the shapes its readers meet: no dict, entries that aren't a list, values of
# every JSON type where a text or a number is read, an id of the wrong length or letters, live and short marks.
SEARCH_TEXTS = [
    ('{"_type": "playlist", "entries": ['
     f'{{"id": "{ID}", "title": "Creep", "channel": "Radiohead - Topic", "duration": 239.0, '
     f'"url": "https://www.youtube.com/watch?v={ID}"}},'
     '{"id": "AAAAAAAAAAA", "title": "Live now", "channel": "X", "duration": null, "live_status": "is_live",'
     ' "url": "https://www.youtube.com/watch?v=AAAAAAAAAAA"},'
     '{"id": "BBBBBBBBBBB", "title": "A short", "channel": "Y", "duration": 30,'
     ' "url": "https://www.youtube.com/shorts/BBBBBBBBBBB"},'
     '{"title": "no id"}, {"id": "bad id", "title": "x"}, 7'
     ']}'),
    "not json", "", "[" * 3000, '{"entries": [', "[]", "{}", '{"entries": {}}', '{"entries": null}', "7", '"x"',
    '{"entries": []}  ', '﻿{"entries": []}', '{"entries": [], "entries": [{"id": "CCCCCCCCCCC"}]}',
    '{"entries": [{"id": "CCCCCCCCCCC", "title": 7, "channel": ["a", 1], "duration": true}]}',
    '{"entries": [{"id": "CCCCCCCCCCC", "title": 1.5, "channel": {"a": null}, "duration": "239"}]}',
    '{"entries": [{"id": "CCCCCCCCCCC", "title": false, "channel": "", "uploader": "Up", "duration": 0}]}',
    '{"entries": [{"id": "CCCCCCCCCCC", "title": "", "channel": 0, "uploader": 0.0, "duration": -1}]}',
    '{"entries": [{"id": "CCCCCCCCCCC", "title": null, "uploader": "Only", "duration": 1e400}]}',
    '{"entries": [{"id": "CCCCCCCCCCC", "duration": NaN}, {"id": "DDDDDDDDDDD", "duration": -Infinity}]}',
    '{"entries": [{"id": "CCCCCCCCCCC", "duration": 1' + "0" * 400 + '}]}',
    '{"entries": [{"id": "CCCCCCCCCCC", "duration": 12345678901234567890}]}',
    '{"entries": [{"id": "CCCCCCCCCCC", "duration": 2.5e2, "title": true}]}',
    '{"entries": [{"id": "CCCCCCCCCC"}, {"id": "CCCCCCCCCCCC"}, {"id": "CCCCCCCCCC!"}, {"id": 12345678901}]}',
    '{"entries": [{"id": "CCCCCCCCCC\\u00e9"}, {"id": "-_-_-_-_-_-"}, {"id": "CCCCCCCCCCC\\n"}]}',
    '{"entries": [{"id": "CCCCCCCCCCC", "live_status": "is_upcoming"}, {"id": "DDDDDDDDDDD", "live_status": '
    '"post_live"}, {"id": "EEEEEEEEEEE", "live_status": true}]}',
    '{"entries": [{"id": "CCCCCCCCCCC", "url": "https://www.youtube.com/SHORTS/x"}, {"id": "DDDDDDDDDDD", "url": 5},'
    ' {"id": "EEEEEEEEEEE", "url": ["/shorts/"]}, {"id": "FFFFFFFFFFF", "url": "/shorts/"}]}',
    '{"entries": [{"id": "CCCCCCCCCCC", "title": "宋冬野《斑马斑马》\\ud83c\\udfb8", "channel": "宋冬野 - Topic"}]}',
]
VIDEO_TEXTS = [
    (json.dumps({"id": ID, "title": "Creep", "channel": "Radiohead - Topic", "duration": 239}), ID),
    (json.dumps({"id": ID, "title": "Creep", "uploader": "Radiohead", "duration": 238.5, "live_status": "is_live"}),
     ID),
    (json.dumps({"id": "AAAAAAAAAAA", "title": "Another"}), ID),
    (json.dumps([{"id": ID}]), ID), ("not json", ID), ("{", ID), ("[" * 3000, ID), ('{"id": null}', ID),
    (json.dumps({"id": ID, "title": ["a"], "channel": 3, "duration": False}), ID),
    (json.dumps({"id": ID, "live_status": "is_upcoming", "url": "https://www.youtube.com/shorts/x"}), ID),
    ('{"id": "' + ID + '", "duration": 1' + "0" * 400 + '}', ID),
]
SEARCH_QUERIES = [
    ("Radiohead", "Creep - Remastered 2009"), ("Radiohead", "Creep"), ("  Radiohead　", " Creep "),
    ("The Beatles", "Hey Jude (Remastered 2015)"), ("宋冬野", "斑马，斑马"), ("Oasis", "Live Forever - Live at Knebworth"),
    ("Daft Punk", "Get Lucky (feat. Pharrell Williams)"), ("", ""), ("A", "   "), ("--exec", "rm -rf ~ {title}"),
    ("{artist}", "{title}"), ("Céline Dion", "My Heart Will Go On (Love Theme from \"Titanic\")"),
]


def _seeded_searches() -> list[str]:
    """Flat searches drawn from FakeYtDlp's entries and odd values, the same in every process."""
    import random

    rng = random.Random(1126)
    values = ["Creep", "", None, 7, 0, 1.5, True, False, [], ["x"], {}, {"a": 1}, "宋冬野", "Radiohead - Topic"]
    found = []
    for _ in range(24):
        entries = []
        for i in range(rng.randrange(0, 5)):
            vid = rng.choice([ID, "AAAAAAAAAAA", "x", f"vid{i:08d}", "bad id here"])
            e = entry(vid, rng.choice(values), rng.choice(values), rng.choice([None, 239, 239.5, 0, -3, True, "1"]))
            for key in ("uploader", "live_status", "url"):
                if rng.random() < 0.3:
                    e[key] = rng.choice(values + ["is_live", "is_upcoming", "https://www.youtube.com/shorts/x"])
            if rng.random() < 0.2:
                e.pop(rng.choice(sorted(e)))
            entries.append(e)
        found.append(json.dumps({"_type": "playlist", "entries": entries}, ensure_ascii=rng.random() < 0.5))
    return found


def test_the_parse_corpus():
    records = []
    for text in SEARCH_TEXTS + _seeded_searches():
        records.append({"fn": "parse_search", "text": text, **_answer(lambda: youtube.parse_search(text), text)})
    for text, vid in VIDEO_TEXTS:
        records.append({"fn": "parse_video", "text": text, "id": vid,
                        **_answer(lambda: youtube.parse_video(text, vid), text)})
    for artist, title in SEARCH_QUERIES + [(s.artist, s.title) for s, *_ in CHOOSE_CASES]:
        records.append({"fn": "search_query", "artist": artist, "title": title,
                        "query": youtube.search_query(_S(artist, title, []))})
    assert {r.get("error") for r in records} == {None, "ProviderError", "OverflowError"}
    check(VECTORS / "youtube" / "parse.jsonl", jsonl(records, corpus="youtube/parse", made_by=MADE_BY))


# --- choose.jsonl -------------------------------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class _S:
    artist: str
    title: str
    artists: list[str]


def _v(vid: str, title: str, channel: str, duration: float | None = 239.0, **marks) -> youtube.Video:
    return youtube.Video(vid.ljust(11, "x")[:11], title, channel, duration, **marks)


CREEP = _S("Radiohead", "Creep", [])
_SONGS = {
    "creep": CREEP, "help": _S("The Beach Boys", "Help", []), "live": _S("Radiohead", "Creep - Live", []),
    "acoustic": _S("Radiohead", "Creep (Acoustic)", []), "lightning": _S("Live", "Lightning Crashes", []),
    "banma": _S("宋冬野", "斑马，斑马", []), "rain": _S("周杰伦", "雨", []), "sunny": _S("周杰伦", "晴天", []),
    "music": _S("周杰伦", "我的音乐", []), "k": _S("陈奕迅", "K歌之王", []),
    "duet": _S("Simon & Garfunkel", "The Boxer", ["Simon & Garfunkel", "Paul Simon"]),
    "lemon": _S("米津玄師", "Lemon", []), "iu": _S("아이유", "좋은 날", []), "yoasobi": _S("YOASOBI", "夜に駆ける", []),
    "astral": _S("𠮷田", "𠮷野家の歌", []), "trad": _S("周杰倫", "晴天", ["周杰倫", "Jay Chou"]),
    "blank": _S("  ", "Creep", ["", "  "]), "dashed": _S("Guns N' Roses", "Sweet Child O' Mine", []),
}
# Each of test_youtube.py's cases (song, its videos in the search's order, the length to fit, the skipped ids), and
# Japanese, Korean, a letter past the BMP, Traditional characters, blank artists and apostrophes.
_TOPIC = _v("topic", "Creep", "Radiohead - Topic")
_LYRICS = _v("lyrics", "Radiohead - Creep (Lyrics)", "a lyrics channel")
CHOOSE_CASES = [
    (CREEP, [_v("lyrics", "Radiohead - Creep (Lyrics)", "7clouds"), _v("video", "Radiohead - Creep (Official Video)",
     "Radiohead"), _v("audio", "Radiohead - Creep (Official Audio)", "Radiohead"), _TOPIC], None, []),
    (CREEP, [_v("lyrics", "Radiohead - Creep (Lyrics)", "7clouds"), _v("video", "Radiohead - Creep (Official Video)",
     "Radiohead"), _v("audio", "Radiohead - Creep (Official Audio)", "Radiohead")], None, []),
    (CREEP, [_v("other", "Radiohead - Creep", "Music Channel 24"), _v("vevo", "Radiohead - Creep", "RadioheadVEVO")],
     None, []),
    (_SONGS["help"], [_v("rhonda", "The Beach Boys - Help Me Rhonda", "The Beach Boys")], None, []),
    (_SONGS["help"], [_v("help", "The Beach Boys - Help!", "The Beach Boys")], None, []),
    (CREEP, [_v("quoted", "Radiohead 'Creep' official video", "Radiohead")], None, []),
    (CREEP, [_v("plain", "Radiohead Creep Official Music Video HD", "Radiohead")], None, []),
    (CREEP, [_v("other", "Creep", "Stone Temple Pilots - Topic")], None, []),
    (CREEP, [_v("anyone", "Creep (Official Audio)", "Someone Else")], None, []),
    (CREEP, [_v("fan", "Creep - Radiohead | lyrics", "lyricsfan")], None, []),
    (CREEP, [_v("off", "Creep", "Radiohead - Topic", 270.0)], 239.0, []),
    (CREEP, [_v("near", "Radiohead - Creep (Lyrics)", "lyricsfan", 243.0), _v("off", "Creep", "Radiohead - Topic",
     270.0)], 239.0, []),
    (CREEP, [_v("near", "Radiohead - Creep (Lyrics)", "lyricsfan", 243.0), _v("exact", "Radiohead - Creep [Lyrics]",
     "other lyrics", 238.5)], 239.0, []),
    (CREEP, [_v("off", "Creep", "Radiohead - Topic", 270.0)], None, []),
    (CREEP, [_v("clip", "Radiohead - Creep", "Radiohead", 20.0)], None, []),
    (CREEP, [_v("hour", "Radiohead - Creep", "Radiohead", 3600.0)], None, []),
    *[(CREEP, videos, None, []) for title in (
        "Creep - Radiohead (Acoustic Cover)", "Radiohead - Creep (Live at Glastonbury 1997)",
        "Radiohead - Creep (Karaoke Version)", "Radiohead - Creep (Instrumental)",
        "How to play Creep by Radiohead - Guitar Lesson", "Radiohead - Creep guitar tutorial (chords)",
        "Radiohead - Creep (slowed + reverb)", "Radiohead - Creep (sped up)", "Radiohead - Creep (Nightcore)",
        "Radiohead - Creep (8D Audio)", "Radiohead - Creep (Remix)", "Reacting to Radiohead - Creep (reaction)")
      for videos in ([_v("worse", title, "Radiohead"), _LYRICS], [_v("worse", title, "Radiohead")])],
    *[(CREEP, videos, None, []) for karaoke in (
        _v("style", "Creep - in the style of Radiohead", "KaraFun"),
        _v("famous", "Creep (Made Famous by Radiohead)", "Sing King"), _v("channel", "Radiohead - Creep", "Sing King"),
        _v("karaoke", "Radiohead - Creep", "Zoom Karaoke Official"),
        _v("nightcore", "Radiohead - Creep", "Nightcore Hits"))
      for videos in ([karaoke, _LYRICS], [karaoke])],
    (_SONGS["lightning"], [_v("own", "Live - Lightning Crashes", "LiveVEVO"),
                           _v("lyrics", "Live - Lightning Crashes (Lyrics)", "lyrics")], None, []),
    (_SONGS["live"], [_v("concert", "Radiohead - Creep (Live)", "Radiohead"), _TOPIC], None, []),
    (_SONGS["acoustic"], [_v("acoustic", "Radiohead - Creep (Acoustic)", "Radiohead"), _TOPIC], None, []),
    (CREEP, [_v("live", "Radiohead - Creep", "Radiohead", None, live=True),
             _v("short", "Radiohead - Creep", "Radiohead", 239.0, short=True)], None, []),
    (CREEP, [_v("gone", "Creep", "Radiohead - Topic")], None, ["gonexxxxxxx"]),
    (CREEP, [_v("gone", "Creep", "Radiohead - Topic"), _v("next", "Radiohead - Creep", "Radiohead")], None,
     ["gonexxxxxxx", "elsewhere00"]),
    (_SONGS["banma"], [_v("hanzi", "宋冬野 - 斑马，斑马 (Official Audio)", "宋冬野")], None, []),
    (_SONGS["banma"], [_v("brackets", "宋冬野《斑马斑马》", "Song Dongye")], None, []),
    (_SONGS["banma"], [_v("pinyin", "Song Dongye - Banma Banma", "Song Dongye - Topic")], None, []),
    (_SONGS["banma"], [_v("twice", "Song Dongye 宋冬野 - Banma Banma 斑马斑马", "Modern Sky")], None, []),
    (_SONGS["banma"], [_v("other", "赵雷 - 成都", "赵雷")], None, []),
    (_SONGS["rain"], [_v("longer", "周杰伦 - 雨下一整晚", "周杰伦")], None, []),
    (_SONGS["sunny"], [_v("doll", "周杰伦 晴天娃娃", "someone", 240.0), _v("topic", "晴天", "周杰伦 - Topic", 243.0)],
     239.0, []),
    (_SONGS["sunny"], [_v("doll", "周杰伦 晴天娃娃", "someone", 240.0)], 239.0, []),
    (_SONGS["sunny"], [_v("cover", "林俊杰 晴天", "周杰伦")], None, []),
    *[(_SONGS["sunny"], [_v("glued", title, "someone")], None, []) for title in (
        "周杰伦晴天", "周杰伦 晴天 官方MV", "【动态歌词】周杰伦 晴天", "晴天周杰伦完整版", "周杰倫晴天 高清")],
    (_SONGS["music"], [_v("music", "周杰伦 我的音乐 MV", "someone")], None, []),
    (_SONGS["k"], [_v("k", "陈奕迅K歌之王官方MV", "someone")], None, []),
    (_SONGS["banma"], [_v("live", "宋冬野 斑马斑马 现场版", "someone"), _v("studio", "宋冬野 斑马斑马", "someone")], None, []),
    (_SONGS["banma"], [_v("live", "宋冬野 斑马斑马 现场版", "someone")], None, []),
    (_SONGS["sunny"], [_v("alone", "周杰伦 Jay Chou 晴天 Sunny Day", "someone", 239.0)], 239.0, []),
    (_SONGS["sunny"], [_v("alone", "周杰伦 Jay Chou 晴天 Sunny Day", "someone", 239.0),
                       _v("exact", "周杰伦 - 晴天", "someone", 230.0)], 239.0, []),
    (_SONGS["sunny"], [_v("alone", "周杰伦 Jay Chou 晴天 Sunny Day", "someone", 239.0),
                       _v("topic", "晴天", "周杰伦 - Topic", 239.0)], 239.0, []),
    (_SONGS["duet"], [_v("paul", "Paul Simon - The Boxer (Official Audio)", "Paul Simon")], None, []),
    (_SONGS["lemon"], [_v("mv", "米津玄師 MV「Lemon」", "米津玄師"), _v("cover", "Lemon / 米津玄師 (Cover)", "someone"),
                       _v("karaoke", "【カラオケ】Lemon / 米津玄師", "JOYSOUND")], None, []),
    (_SONGS["lemon"], [_v("karaoke", "【カラオケ】Lemon / 米津玄師", "JOYSOUND"), _v("lemonade", "米津玄師 Lemonade", "x")],
     None, []),
    (_SONGS["iu"], [_v("live", "아이유 좋은 날 라이브", "x"), _v("mv", "[MV] IU(아이유) _ Good Day(좋은 날)", "1theK (원더케이)"),
                    _v("noraebang", "[노래방] 아이유 - 좋은 날", "TJ")], None, []),
    (_SONGS["yoasobi"], [_v("mv", "YOASOBI「夜に駆ける」 Official Music Video", "Ayase / YOASOBI"),
                         _v("topic", "夜に駆ける", "YOASOBI - Topic", 261.0)], 261.0, []),
    (_SONGS["astral"], [_v("glued", "𠮷田𠮷野家の歌", "x"), _v("longer", "𠮷田 𠮷野家の歌ですね", "x")], None, []),
    (_SONGS["astral"], [_v("longer", "𠮷田 𠮷野家の歌ですね", "x"), _v("topic", "𠮷野家の歌", "𠮷田 - Topic")], None, []),
    (_SONGS["trad"], [_v("simplified", "周杰伦 晴天", "x"), _v("jay", "Jay Chou - Sunny Day 晴天", "JVR Music")], None, []),
    (_SONGS["blank"], [_v("creep", "Creep", "  - Topic"), _v("plain", "Creep", "")], None, []),
    (_SONGS["dashed"], [_v("gnr", "Guns N' Roses - Sweet Child O' Mine (Official Music Video)", "GunsNRosesVEVO"),
                        _v("gnr2", "Sweet Child O Mine", "Guns N Roses - Topic")], None, []),
    (CREEP, [_v("nolength", "Radiohead - Creep", "Radiohead", None), _v("close", "Radiohead - Creep", "Radiohead",
     241.0), _v("far", "Radiohead - Creep", "Radiohead", 258.0), _v("edge", "Radiohead - Creep", "x", 259.0)], 239.0,
     []),
    (CREEP, [_v("short45", "Radiohead - Creep", "Radiohead", 45.0), _v("long900", "Radiohead - Creep", "Radiohead",
     900.0), _v("over", "Radiohead - Creep", "Radiohead", 900.5)], None, []),
    (CREEP, [], None, []),
]


def _seeded_choices() -> list[tuple]:
    """Songs and videos of the cases above drawn together, the same in every process."""
    import random

    rng = random.Random(2611)
    pool = sorted({v for _, videos, _, _ in CHOOSE_CASES for v in videos}, key=lambda v: (v.id, v.title, v.channel, v.duration or -1.0, v.live, v.short))
    songs = [_SONGS[k] for k in sorted(_SONGS)]
    found = []
    for _ in range(140):
        videos = rng.sample(pool, rng.randrange(1, 6))
        skip = [rng.choice(videos).id] if rng.random() < 0.1 else []
        found.append((rng.choice(songs), videos, rng.choice([None, None, 239.0, 230.0, 243.0, 261.0, 30.0]), skip))
    return found


def test_the_choose_corpus():
    records = []
    for song, videos, expected, skip in CHOOSE_CASES + _seeded_choices():
        chosen = youtube.choose(song, videos, expected, skip=skip)
        ranked = youtube._ranked(song, videos, expected, skip=skip)
        records.append({"song": [song.artist, song.title, song.artists],
                        "videos": [[v.id, v.title, v.channel, v.duration, v.live, v.short] for v in videos],
                        "expected": expected, "skip": skip, "chosen": chosen.id if chosen else None,
                        "ranked": [[v.id, *key] for key, v in ranked]})
    assert len({r["chosen"] for r in records}) > 30 and sum(r["chosen"] is None for r in records) > 10
    check(VECTORS / "youtube" / "choose.jsonl", jsonl(records, corpus="youtube/choose", made_by=MADE_BY))


# --- runs.jsonl ---------------------------------------------------------------------------------------------------

class _Clock:
    """test_youtube.py's: it moves only when slept, or by a call's gap."""

    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


class _Draws:
    """random.Random's uniform, each draw kept, its bounds the policy's."""

    def __init__(self, seed: int, delay: tuple[float, float]):
        self.rng, self.delay, self.drawn = random.Random(seed), delay, []

    def uniform(self, low: float, high: float) -> float:
        assert (low, high) == self.delay
        x = self.rng.uniform(low, high)
        self.drawn.append(x)
        return x


B = "ERROR: [youtube] dQw4w9WgXcQ: "
LONG = "ERROR: Unable to download API page: " + "a reason that goes on and on, " * 15
# (name, the plan, the calls: (call, arg, gap), budget, timeouts)
RUN_SCENARIOS = [
    ("paced", {"searches": {"a": [entry(ID, "Creep", "Radiohead - Topic", 239)], "b": []},
               "videos": {ID: {}}},
     [("search", "a", 0.0), ("search", "b", 1.5), ("video", ID, 10.0), ("search", "c", 0.0), ("search", "d", 0.0)],
     3, None),
    *[(f"blocked-{i}", {"videos": {ID: {"stderr": e, "exit": 1}}},
       [("download", ID, 0.0), ("search", "anything", 0.0), ("video", ID, 0.0)], 6, None)
      for i, e in enumerate([
          B + "Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies for the authentication.",
          "ERROR: unable to download video data: HTTP Error 429: Too Many Requests",
          "ERROR: unable to download video data: HTTP Error 403: Forbidden",
          B + "This content isn't available, try again later. The current session has been rate-limited by YouTube.",
      ])],
    *[(f"unavailable-{i}", {"videos": {ID: {"stderr": e, "exit": 1}}, "searches": {"next": []}},
       [("download", ID, 0.0), ("search", "next", 2.0)], 6, None)
      for i, e in enumerate([B + "Video unavailable", B + "Private video. Sign in if you've been granted access",
                             B + "This video is DRM protected"])],
    ("error", {"searches": {"q": {"stderr": "WARNING: something\nERROR: Unable to download API page: [Errno -3] "
                                            "Temporary failure in name resolution", "exit": 1}}},
     [("search", "q", 0.0), ("search", "q", 0.0)], 6, None),
    ("said-nothing", {"searches": {"q": {"exit": 1}}}, [("search", "q", 0.0)], 6, None),
    ("long-reason", {"searches": {"q": {"stderr": LONG, "exit": 2}}}, [("search", "q", 0.0)], 6, None),
    ("pass-over", {"videos": {ID: {"stderr": NO_FORMAT, "exit": 1}}, "searches": {"next": []}},
     [("download", ID, 0.0), ("search", "next", 0.0)], 6, None),
    ("outdated", {"videos": {ID: {"stderr": B + "Unable to extract player version", "exit": 1},
                             "AAAAAAAAAAA": {"stderr": "ERROR: [youtube] AAAAAAAAAAA: Precondition check failed.",
                                             "exit": 1}}},
     [("download", ID, 0.0), ("video", "AAAAAAAAAAA", 0.0)], 6, None),
    ("timeout", {"searches": {"slow": {"sleep": 5}}}, [("search", "slow", 0.0), ("search", "slow", 0.0)], 1,
     (0.5, 0.5)),
    ("download", {"videos": {ID: {"title": "Creep", "channel": "Radiohead - Topic", "duration": 238.5,
                                  "data": "AAC bytes"}}},
     [("download", ID, 0.0)], 6, None),
]


def _plan(fake: FakeYtDlp, plan: dict) -> None:
    for query, spec in plan.get("searches", {}).items():
        if isinstance(spec, list):
            fake.search(query, *spec)
        else:
            fake.search(query, **spec)
    for vid, spec in plan.get("videos", {}).items():
        fake.video(vid, **spec)


def _kind(argv: list[str], into: str) -> dict:
    """The run's kind, target and folder, from the computer's argv."""
    what = "download" if "-o" in argv else "video" if "--skip-download" in argv else "search"
    given = {"what": what, "target": argv[-1]}
    if what == "download":
        assert argv[argv.index("-o") + 1] == f"{into}/{youtube.OUTPUT_NAME}"
        given["into"] = "<into>"
    return given


def _outcome(call: str, got, into) -> dict:
    if call == "search":
        return {"videos": [v.id for v in got]}
    if call == "video":
        return {"video": [got.id, got.title, got.channel, got.duration]}
    v = got.video
    return {"video": [v.id, v.title, v.channel, v.duration], "file": got.path.relative_to(into).as_posix()}


@pytest.mark.slow
def test_the_runs_corpus(tmp_path, monkeypatch):
    ran: list[dict] = []
    real = subprocess.Popen

    class Recorded(real):
        noted = False

        def communicate(self, *args, **kwargs):
            try:
                out, err = super().communicate(*args, **kwargs)
            except subprocess.TimeoutExpired:
                if not self.noted:
                    self.noted = True
                    ran.append({"timed_out": True})
                raise
            if not self.noted:
                self.noted = True
                ran.append({"exit": self.returncode, "stdout": out.decode(), "stderr": err.decode()})
            return out, err

    monkeypatch.setattr(subprocess, "Popen", Recorded)
    records = []
    for n, (name, plan, calls, budget, timeouts) in enumerate(RUN_SCENARIOS):
        here = tmp_path / name
        fake = FakeYtDlp(here / "bin")
        _plan(fake, plan)
        into = here / "into"
        into.mkdir()
        delay = (3.75, 7.5)
        clock, draws, events = _Clock(), _Draws(n, delay), []
        yt = youtube.YtDlp(fake.bin, ProviderPolicy(budget=budget, delay=delay), here / "cache",
                           on_event=events.append, sleep=clock.sleep, clock=clock, rng=draws,
                           **({"timeouts": timeouts} if timeouts else {}))
        conn = db.connect(here / "caracole.sqlite")
        started = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
        block = None
        said = []
        ran.clear()
        for call, arg, gap in calls:
            clock.t += gap
            before = len(ran)
            try:
                got = getattr(yt, call)(*((arg, into) if call == "download" else (arg,)))
                outcome = _outcome(call, got, into)
            except (ProviderError, BudgetExhausted) as e:
                outcome = {"raised": type(e).__name__, "message": str(e)}
                if isinstance(e, youtube.ProviderBlocked) and block is None and len(ran) > before:
                    state = health.record_block(conn, youtube.PROVIDER, started, str(e))
                    block = {"message": str(e),
                             "cooldown_hours": (state.cooldown_until - started).total_seconds() / 3600}
            process = ran[before] if len(ran) > before else None
            said.append({"call": call, "arg": arg, "gap": gap, "process": process, "outcome": outcome})
        conn.close()
        argvs = fake.argvs()
        assert len(argvs) == sum(c["process"] is not None for c in said)
        runs, i = [], 0
        for c in said:
            p = c.pop("process")
            c["argv"], c["ran"], c["classify"] = None, None, None
            if p is not None:
                c["argv"] = _kind(argvs[i], str(into))
                i += 1
                if "stdout" in p:
                    p["stdout"] = p["stdout"].replace(str(into), "<into>")
                    if c["call"] == "download" and p["exit"] == 0:
                        p["writes"] = {"name": "audio.m4a", "data": (into / "audio.m4a").read_text()}
                    if p["exit"] != 0:
                        c["classify"] = youtube.classify(p["stderr"])
                c["ran"] = p
            # The phone's reading agrees with the computer's where the computer has one.
            raised = c["outcome"].get("raised")
            if c["classify"] == "blocked":
                assert raised == "ProviderBlocked"
            elif c["classify"] == "unavailable":
                assert raised == "VideoUnavailable"
            elif c["classify"] is not None:
                assert raised == "ProviderError"
            runs.append(c)
        assert all(str(tmp_path) not in json.dumps(c) for c in runs)
        records.append({"scenario": name, "budget": budget, "delay": list(delay),
                        "timeouts": list(timeouts) if timeouts else [youtube.SEARCH_TIMEOUT, youtube.DOWNLOAD_TIMEOUT],
                        "draws": draws.drawn, "calls": runs,
                        "events": [[e.url, e.status, e.decision, e.message] for e in events],
                        "slept": clock.slept, "requests_made": yt.requests_made, "block": block})
    assert {c["classify"] for r in records for c in r["calls"]} >= {*youtube.RUN_CLASSES}
    check(VECTORS / "youtube" / "runs.jsonl", jsonl(records, corpus="youtube/runs", made_by=MADE_BY))
