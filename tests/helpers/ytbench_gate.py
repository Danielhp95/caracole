"""Gate Y0's verdict from the YouTube bench's reports (the phone-youtube design's §4.4), for the owner's sessions.

- ``read(path) -> dict``: one report, ``caracole-ytbench-<UTC>.json``, as android/'s ``BenchReport.of`` writes it, or
  ``ReportError`` in words naming the file and what is wrong: not JSON, another format, a member missing, of another
  type, or one the bench doesn't write. ``tests/fixtures/ytbench/sample.json`` is the bench's shape: the Kotlin side's
  BenchReportTest asserts that ``BenchReport.of`` writes it for fixed inputs, and test_ytbench_gate.py builds every
  report it checks from it, so the two sides read one shape.
- ``gate(reports, *, apk_growth_mb=None) -> dict[str, Verdict]``: a verdict for each row of §4.4, by the row's name
  (``Y0-W`` … ``Y0-C``), as the controller ruled on 2026-11-27 (the owner runs by hand, several short sessions a day):
  ``sessions``, the sessions and days given, reported, one on mobile data with Start (enforce) needed, an observed one
  wanted but not needed, two days not needed; ``Y0-W`` three songs downloaded on mobile data with Start over the
  sessions after the last bad one (a block or a failing song, which holds the gate until a later day's clean session
  on mobile data clears it: ``_Standing``); a session the network lost (every run an error of a timeout's or a
  transport's) and a song it failed counted for nothing, and listed; and
  ``terms``, the owner's terms as the sessions kept them (the six runs of any 24 hours by the runs' own stamps, for the
  runs of a report without ``lifted``: one whose budget says it, the owner's word of 2026-11-27, has its busiest 24
  hours said, never failed for them; nothing after a block, no session observing every host but on Wi-Fi, a kill
  check that spent none, no host reached outside YouTube's under enforce, no gate-shaped proxy address or bare
  user:secret pair anywhere). A run's ``uid_bytes`` count loopback too (``uid_counts``; a report without it counted
  so): Y0-H holds them to what the gate's bytes explain over three legs (``H_UID_LEGS``' comment). ``Verdict(passed,
  numbers, why)``: ``passed`` True, False, or None for undecided (what is missing and what to run next, or the owner's
  word), ``numbers`` what it was decided on, ``why`` in words. A handful of runs shows no rate: where §4.4 asks for
  what they can't show, the verdict is undecided, never a pass.
- ``youtubei(reports)``: how often an observed session's gate log shows ``youtubei.googleapis.com`` asked for, and
  whether the enforced runs went without it: numbers for the controller, who decides (Y0.4's rule).
- ``python -m tests.helpers.ytbench_gate REPORT… [--apk-growth-mb N]`` (the option anywhere; a negative or non-finite
  growth refused): a line a gate (its name, PASS, FAIL or
  UNDECIDED, the numbers, the why), the youtubei note, and a last line with the whole verdict; exit 0 only when every
  gate passed, 1 for a fail, 2 for undecided or a report that won't read (said which).

YouTube's hosts are youtube.json's (``gate``, youtube.py's ``PHONE_GATE``: what the phone's HostGate allows), read
from the conformance corpus. The standard library alone.
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

YOUTUBE_JSON = Path(__file__).resolve().parents[1] / "conformance" / "data" / "caracole" / "youtube" / "youtube.json"

FORMAT = 1  # BenchReport.FORMAT

# The owner's terms (AGENTS.md, "The one exception is YouTube"; the plan's Global Constraints).
RUNS_A_DAY = 6  # yt-dlp runs in any 24 hours on the phone, every session counted
# The owner's word of 2026-11-27, "ignore the run limits while developing this feature. as connection is patchy": the
# debug bench's six lifted while the feature is developed, its runs still counted. A report says it in its budget's
# ``lifted`` (DbLedger.DAY_CAP_LIFTED); one without it (the bench before that day) is bound by the six as ever.
CAP_LIFTED_ON = "2026-11-27"
DAY = timedelta(hours=24)

# §4.4, row by row.
# Y0-W, the controller's ruling of 2026-11-27 (the owner runs by hand, several short sessions a day): on mobile data
# with Start (enforce), at least 3 songs downloaded ok over any number of sessions, no song failing, no block.
W_SONGS = 3
T_COLD_CHALLENGE_S = 20.0  # Y0-T: the cold download's challenge
T_COLD_WHOLE_S = 30.0  # Y0-T: cold search + download, yt-dlp's sleeps and caracole's pauses left out
T_WARM_S = 15.0  # Y0-T: each warm download (a ~4-minute song)
T_FALLBACK_CHALLENGE_S = 60.0  # Y0-T fail (§3.8): the cold challenge over this in both Wi-Fi sessions
T_FALLBACK_WHOLE_S = 120.0  # Y0-T fail (§3.8): the cold whole, sleeps included, over this in both Wi-Fi sessions
S_PASS_MB = 35.0  # Y0-S: release-equivalent arm64 APK growth
S_FAIL_MB = 45.0  # Y0-S: over this after trimming, §3.8; between the two, the owner is asked
# Y0-H: a run's uid_bytes explained by the gate's bytes. TrafficStats counts the app's uid on every interface,
# loopback too (``uid_counts`` "loopback too", every report so far): a byte through the gate is yt-dlp's to the gate on
# 127.0.0.1, sent and received (2 x), and the gate's on the network (1 x), each with its packets' headers. The owner's
# phone counted 3.07-3.11 x the gate's bytes a run, the emulator 3.2-3.35 x (YouTubeBenchTest measures a loopback byte
# counted twice). So uid_bytes <= 3 legs x (1 + 8 % for headers and retransmits) of the gate's + 64 KB a run (a
# handshake's packets: the phone's Wi-Fi run that timed out counted 14 KB for the gate's 3 KB). A bypass, bytes yt-dlp
# sends the network outside the gate, is counted once: under the bound slips at most about 0.16 x the gate's bytes +
# 64 KB a run (some 700 KB of a 4.4 MB download, 120 KB of a search), never a song's audio.
H_UID_LEGS = 3
H_UID_HEADERS = 0.08
H_UID_SLACK = 64 * 1024
UID_COUNTS = ("loopback too",)  # BenchReport.UID_COUNTS_LOOPBACK; a report without the member counted so too
F_WITHIN_S = 1.0  # Y0-F: decoded frames / rate within 1 s of yt-dlp's duration
M_PASS_MB = 500.0  # Y0-M: peak PSS of :youtube + qjs
M_ASK_MB = 800.0  # Y0-M: over this, "the owner is asked" (the row's words: no fail; phones of 6 GB are the floor)
C_MORE_MS = 20_000  # Y0-C: the first run after install at most 20 s more than a warm run
C_WARM_START_MS = 3_000  # Y0-C: a warm start over this is no fail (one process per job, §3.2), only said

# What classify answers (Y1.1's), and ok.
CLASSES = ("ok", "blocked", "unavailable", "outdated", "pass_over", "gate_refused", "error")
SONG_ENDS_WELL = ("ok", "pass_over", "unavailable")

YOUTUBEI = "youtubei.googleapis.com"

# HostGate.PROXY_PATTERN's user and secret: HostGate.TOKEN_BYTES (16) random bytes each, in lowercase hex, so 32 hex
# digits each. A gate's `--proxy` holds them, and no report may: the bare pair anywhere in a text (with or without its
# `@`, its scheme or its host around it), or any `://user:secret@127.0.0.1`.
TOKEN_HEX = 2 * 16
_SECRET = re.compile(rf"[0-9a-f]{{{TOKEN_HEX}}}:[0-9a-f]{{{TOKEN_HEX}}}|://[^\s/@:'\"]+:[^\s/@'\"]+@127\.0\.0\.1")

GATES = {
    "sessions": "the sessions",
    "terms": "the owner's terms",
    "Y0-W": "Y0-W works",
    "Y0-T": "Y0-T time",
    "Y0-S": "Y0-S size",
    "Y0-H": "Y0-H hosts",
    "Y0-B": "Y0-B blocks",
    "Y0-F": "Y0-F file",
    "Y0-K": "Y0-K kill",
    "Y0-M": "Y0-M memory",
    "Y0-C": "Y0-C start",
}

# The bench's shape (BenchReport.of, BenchRun's kill check, YouTubeBenchProbe's device and network): each member and
# the JSON types it may take ("null" where the bench writes null for none).
_NUM = ("int", "float")
REPORT_MEMBERS: dict[str, tuple[str, ...]] = {
    "format": ("int",), "started_at": ("str",), "gate": ("str",), "mode": ("str",),
    "device": ("str",), "soc": ("str",), "android": ("str",), "app": ("str",), "apk_bytes": ("int",),
    "installed_bytes": ("int",), "abi": ("str",),
    "pins": ("dict",), "network": ("dict",), "idle": ("bool",), "idle_detail": ("dict",), "budget": ("dict",),
    "runs": ("list",), "after_block_requests": ("int",), "kill_check": ("dict",), "first_start": ("dict",),
    "stopped": ("str", "null"), "summary": ("dict",),
}
RUN_MEMBERS: dict[str, tuple[str, ...]] = {
    "song": ("str",), "kind": ("str",), "cache": ("str", "null"), "chosen_by": ("str", "null"),
    "started_at": ("str",), "process_start_ms": ("int",), "python_ready_ms": ("int",), "seconds": _NUM,
    "challenge": ("dict", "null"), "sleeps_seconds": _NUM, "pause_seconds": _NUM, "clients": ("list",),
    "outcome": ("str",), "reason": ("str", "null"), "said": ("list",), "hosts": ("dict",),
    "uid_bytes": ("int", "null"), "pss_peak_mb": ("dict",), "file": ("dict", "null"), "decoded": ("dict", "null"),
}
HOST_MEMBERS: dict[str, tuple[str, ...]] = {
    "connects": ("int",), "bytes_up": ("int",), "bytes_down": ("int",), "refused": ("int",), "apart": ("bool",),
}
PINS_MEMBERS = {"ytdlp": ("str", "null"), "python": ("str", "null"), "js_runtimes": ("str", "null")}
NETWORK_MEMBERS = {"transport": ("str", "null"), "metered": ("bool",), "validated": ("bool",)}
IDLE_MEMBERS = {"served_before": ("int",), "served_after": ("int",), "jobs_before": ("int",), "jobs_after": ("int",),
                "running_before": ("bool",), "running_after": ("bool",)}
BUDGET_MEMBERS = {"before": ("int",), "after": ("int",), "of": ("int",)}
BUDGET_LIFTED = {"lifted": ("bool",)}  # written from 2026-11-27 on; a report of before it has none
UID_COUNTS_MEMBER = {"uid_counts": ("str",)}  # the same: what a run's uid_bytes counts
# A run's error the network made (no answer, a connection cut, a handshake that timed out): no block, no song's fault.
_NETWORK = re.compile(r"timed? ?out|TransportError|Connection (?:reset|aborted|refused|closed)|Network is unreachable|"
                      r"No route to host|Temporary failure in name resolution|Name or service not known|"
                      r"EOF occurred in violation of protocol|IncompleteRead|RemoteDisconnected", re.IGNORECASE)
FIRST_START_MEMBERS = {"first_after_install": ("bool",), "process_start_ms": ("int",), "python_ready_ms": ("int",)}
CHALLENGE_MEMBERS = {"seconds": _NUM, "runtime": ("str",)}
FILE_MEMBERS = {"ext": ("str",), "bytes": ("int",), "duration": ("int", "float", "null")}
DECODED_MEMBERS = {"mime": ("str",), "rate": ("int",), "channels": ("int",), "frames": ("int",)}
KILL_RAN_MEMBERS = {"run": ("bool",), "spends": ("int",), "killed": ("bool",), "qjs_seen": ("bool",),
                    "left": ("list",), "next_run_ok": ("bool",)}
KILL_NOT_RUN_MEMBERS = {"run": ("bool",), "why": ("str",)}
SUMMARY_GATES = ("W", "T", "H", "B", "F", "K", "M", "C")


class ReportError(ValueError):
    """A report that won't read as the bench's, in words naming its file and what is wrong."""


@dataclass(frozen=True)
class Verdict:
    passed: bool | None
    numbers: dict[str, Any] = field(default_factory=dict)
    why: str = ""

    @property
    def said(self) -> str:
        return {True: "PASS", False: "FAIL", None: "UNDECIDED"}[self.passed]


# -- reading -----------------------------------------------------------------------------------------------------------


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    return {float: "float", str: "str", list: "list", dict: "dict"}.get(type(value), type(value).__name__)


def _check(obj: Any, members: dict[str, tuple[str, ...]], where: str) -> None:
    if not isinstance(obj, dict):
        raise ReportError(f"{where} is a {_kind(obj)}, not an object")
    for name, kinds in members.items():
        if name not in obj:
            raise ReportError(f"{where} has no member {name!r}")
        if _kind(obj[name]) not in kinds:
            raise ReportError(f"{where}'s {name!r} is a {_kind(obj[name])}, not {' or '.join(kinds)}")
    extra = sorted(set(obj) - set(members))
    if extra:
        raise ReportError(f"{where} has {', '.join(map(repr, extra))}, which the bench doesn't write")


def _stamp(text: str, where: str) -> datetime:
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise ReportError(f"{where} {text!r} isn't a UTC stamp as the bench writes one") from None


def check_shape(report: Any, name: str = "the report") -> None:
    """Raises ReportError unless ``report`` has the bench's shape, every member there with its type and none other."""
    _check(report, {**REPORT_MEMBERS, **(UID_COUNTS_MEMBER if isinstance(report, dict) and "uid_counts" in report
                                          else {})}, name)
    if "uid_counts" in report and report["uid_counts"] not in UID_COUNTS:
        raise ReportError(f"{name}'s uid_counts is {report['uid_counts']!r}, not the bench's: {', '.join(UID_COUNTS)}")
    if report["format"] != FORMAT:
        raise ReportError(f"{name} is of format {report['format']}, not the bench's {FORMAT}")
    _stamp(report["started_at"], f"{name}'s started_at")
    _check(report["pins"], PINS_MEMBERS, f"{name}'s pins")
    _check(report["network"], NETWORK_MEMBERS, f"{name}'s network")
    _check(report["idle_detail"], IDLE_MEMBERS, f"{name}'s idle_detail")
    budget = report["budget"]
    said_lifted = BUDGET_LIFTED if isinstance(budget, dict) and "lifted" in budget else {}
    _check(budget, {**BUDGET_MEMBERS, **said_lifted}, f"{name}'s budget")
    _check(report["first_start"], FIRST_START_MEMBERS, f"{name}'s first_start")
    kill = report["kill_check"]
    _check(kill, KILL_RAN_MEMBERS if kill.get("run") is True else KILL_NOT_RUN_MEMBERS, f"{name}'s kill_check")
    summary = report["summary"]
    if not isinstance(summary, dict) or sorted(summary) != sorted(SUMMARY_GATES):
        raise ReportError(f"{name}'s summary isn't the bench's: {', '.join(SUMMARY_GATES)}")
    for i, run in enumerate(report["runs"]):
        where = f"{name}'s run {i + 1}"
        _check(run, RUN_MEMBERS, where)
        _stamp(run["started_at"], f"{where}'s started_at")
        for host, use in run["hosts"].items():
            _check(use, HOST_MEMBERS, f"{where}'s host {host!r}")
        if run["challenge"] is not None:
            _check(run["challenge"], CHALLENGE_MEMBERS, f"{where}'s challenge")
        if run["file"] is not None:
            _check(run["file"], FILE_MEMBERS, f"{where}'s file")
        if run["decoded"] is not None:
            _check(run["decoded"], DECODED_MEMBERS, f"{where}'s decoded")
        if any(_kind(v) not in _NUM for v in run["pss_peak_mb"].values()):
            raise ReportError(f"{where}'s pss_peak_mb isn't numbers")
        if any(not isinstance(s, str) for s in run["said"] + run["clients"]):
            raise ReportError(f"{where}'s said and clients aren't texts")


def read(path: Path | str) -> dict[str, Any]:
    """The report at ``path``, checked to be the bench's (``check_shape``), or ReportError in words."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ReportError(f"{path} won't read: {e}") from None
    try:
        report = json.loads(text)
    except ValueError as e:
        raise ReportError(f"{path} isn't JSON: {e}") from None
    check_shape(report, str(path))
    return report


# -- what the reports hold -----------------------------------------------------------------------------------------


def _youtube_gate() -> dict[str, Any]:
    return json.loads(YOUTUBE_JSON.read_text(encoding="utf-8"))["gate"]


def is_youtubes(host: str, gate: dict[str, Any] | None = None) -> bool:
    """Whether ``host`` is one the phone's gate allows under enforce (youtube.json's names and suffixes)."""
    gate = gate or _youtube_gate()
    host = host.lower().rstrip(".")
    return host in gate["names"] or any(host.endswith(s) and len(host) > len(s) for s in gate["suffixes"])


def _refused_by_name(host: str, gate: dict[str, Any]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == r or host.endswith("." + r) for r in gate["refused"])


def _label(report: dict[str, Any]) -> str:
    return f"{report['started_at']} ({report['network']['transport'] or 'no network'}, {report['gate']})"


def _day(report: dict[str, Any]) -> str:
    return report["started_at"][:10]


def _songs(report: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    order: dict[str, list[dict[str, Any]]] = {}
    for run in report["runs"]:
        order.setdefault(run["song"], []).append(run)
    return list(order.items())


def uid_counts(report: dict[str, Any]) -> str:
    """What the report's uid_bytes count: its ``uid_counts``, else "loopback too" (TrafficStats' uid counter, which the
    bench read from the start)."""
    return report.get("uid_counts", UID_COUNTS[0])


def network_error(run: dict[str, Any]) -> bool:
    """Whether ``run`` failed for the network's sake: an error whose words are a timeout's or a transport's."""
    return run["outcome"] == "error" and bool(_NETWORK.search(run["reason"] or ""))


def lost_to_the_network(report: dict[str, Any]) -> bool:
    """A session the network lost: runs, every one an error of the network's, none blocked. It counts for nothing."""
    return bool(report["runs"]) and all(network_error(run) for run in report["runs"])


def _song_end(runs: list[dict[str, Any]]) -> str:
    """What a song came to: blocked if any run was, "network" if its last run failed for the network's sake, else its
    download's outcome, else "no fit" for a search that found nothing to choose, else the search's outcome."""
    if any(r["outcome"] == "blocked" for r in runs):
        return "blocked"
    if network_error(runs[-1]):
        return "network"
    downloads = [r for r in runs if r["kind"] == "download"]
    if downloads:
        return downloads[-1]["outcome"]
    return "no fit" if runs[-1]["outcome"] == "ok" else runs[-1]["outcome"]


def _ok_downloads(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in report["runs"] if r["kind"] == "download" and r["outcome"] == "ok"]


def _less_sleeps(run: dict[str, Any]) -> float:
    return run["seconds"] - run["sleeps_seconds"]


def _transport(reports: Iterable[dict[str, Any]], transport: str) -> list[dict[str, Any]]:
    return [r for r in reports if r["network"]["transport"] == transport]


def _days_said(reports: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    days = [_day(r) for r in reports]
    if len(set(days)) == len(days):
        return {"days": days}, f"{len(days)} session(s) on {len(days)} UTC day(s)" if days else "no session"
    return {"days": days}, f"{len(days)} sessions on {len(set(days))} UTC day(s): two sessions share a day"


# -- the gates ---------------------------------------------------------------------------------------------------------


def lifted(report: dict[str, Any]) -> bool:
    """Whether the bench that wrote ``report`` had the six-run cap lifted (the owner's word of 2026-11-27)."""
    return report["budget"].get("lifted") is True


def _terms(reports: Sequence[dict[str, Any]], gate: dict[str, Any]) -> Verdict:
    broken: list[str] = []
    runs = sorted((_stamp(run["started_at"], "a run"), lifted(r)) for r in reports for run in r["runs"])
    stamps = [at for at, _ in runs]
    most = 0
    for i, at in enumerate(stamps):
        most = max(most, sum(1 for later in stamps[i:] if later - at < DAY))
    # The cap binds each run a capped bench sent: with the runs of the 24 hours up to it, every report's, no more than
    # six (the capped bench counted them all before it ran one). A lifted bench's runs are bound by none.
    # Every run at or before it counts, whatever sorts first at one stamp: a run of the same second is in its window.
    for at, its_cap_lifted in runs:
        if its_cap_lifted:
            continue
        window = [earlier for earlier in stamps if earlier <= at and at - earlier < DAY]
        within = len(window)
        if within > RUNS_A_DAY:
            first = window[0]
            broken.append(f"{within} runs within 24 hours from {first:%Y-%m-%dT%H:%M:%SZ}: the day's runs are "
                          f"{RUNS_A_DAY}")
            break
    for r in reports:
        label = _label(r)
        if r["mode"] != "NETWORK":
            broken.append(f"{label}: mode {r['mode']}, the emulator's test session, not one of the owner's")
        outcomes = [run["outcome"] for run in r["runs"]]
        if "blocked" in outcomes and outcomes.index("blocked") < len(outcomes) - 1:
            broken.append(f"{label}: {len(outcomes) - 1 - outcomes.index('blocked')} run(s) after a block")
        if r["after_block_requests"] != 0:
            broken.append(f"{label}: after_block_requests is {r['after_block_requests']}, not 0")
        if r["kill_check"]["run"] and r["kill_check"]["spends"] != 0:
            broken.append(f"{label}: the kill check spent {r['kill_check']['spends']} of the day's runs, not 0")
        if not lifted(r) and r["budget"]["after"] > r["budget"]["of"]:
            broken.append(f"{label}: {r['budget']['after']} runs in 24 hours after it, of {r['budget']['of']}")
        # Observing every host is Wi-Fi's alone; enforcing, the stricter mode, is never a breach anywhere.
        if r["network"]["transport"] != "wifi" and r["gate"] == "observe":
            on = {"cellular": "mobile data"}.get(r["network"]["transport"], r["network"]["transport"] or "no network")
            broken.append(f"{label}: observed every host on {on}, where only Wi-Fi may observe")
        if r["gate"] not in ("enforce", "observe"):
            broken.append(f"{label}: gate {r['gate']!r}, neither enforce nor observe")
        if r["gate"] == "enforce":
            for i, run in enumerate(r["runs"]):
                for host, use in run["hosts"].items():
                    if not is_youtubes(host, gate) and (use["connects"] or use["bytes_up"] or use["bytes_down"]):
                        broken.append(f"{label}: run {i + 1} reached {host} under enforce, which the gate refuses: "
                                      "a bug of the gate's")
        for where in _secrets(r):
            broken.append(f"{label}: a gate-shaped proxy address (its secret) at {where}")
    n_lifted = sum(1 for r in reports if lifted(r))
    numbers = {"runs": len(stamps), "most_in_24h": most, "sessions": len(reports), "lifted": n_lifted}
    if broken:
        return Verdict(False, numbers, "; ".join(broken))
    count = (f"{most} runs in the busiest 24 hours, the six-run cap lifted at the owner's word ({CAP_LIFTED_ON}) "
             f"for {n_lifted} of {len(reports)} session(s), the capped ones' runs within it" if n_lifted else
             f"at most {most} runs in any 24 hours")
    return Verdict(True, numbers, f"{count}, nothing after a block, no observing but on Wi-Fi, "
                                  "kill checks that spent none, "
                                  "no host reached outside YouTube's under enforce, no proxy secret")


def _secrets(value: Any, where: str = "$") -> list[str]:
    if isinstance(value, dict):
        return [w for k, v in value.items() for w in _secrets(k, f"{where} (a key)") + _secrets(v, f"{where}.{k}")]
    if isinstance(value, list):
        return [w for i, v in enumerate(value) for w in _secrets(v, f"{where}[{i}]")]
    if isinstance(value, str) and _SECRET.search(value):
        return [where]
    return []


def _failing(r: dict[str, Any]) -> list[str]:
    """The songs of ``r`` that failed, not for the network's sake and not blocked, each with its last run's reason."""
    return [f"“{song}” {end}" + "".join(f" ({run['reason']})" for run in runs[-1:] if run["reason"])
            for song, runs in _songs(r)
            if (end := _song_end(runs)) not in SONG_ENDS_WELL and end not in ("no fit", "network", "blocked")]


def _network_songs(r: dict[str, Any]) -> list[tuple[str, str]]:
    """The songs of ``r`` its network failed (their last run an error of a timeout's or a transport's), with why."""
    return [(f"{_label(r)} “{song}”", runs[-1]["reason"] or "") for song, runs in _songs(r)
            if _song_end(runs) == "network"]


def _mobile_enforced(r: dict[str, Any]) -> bool:
    return r["network"]["transport"] == "cellular" and r["gate"] == "enforce" and not lost_to_the_network(r)


def _bad(r: dict[str, Any]) -> str | None:
    """Why ``r`` holds the gate (a block, or a song failing), else None; a session the network lost holds nothing."""
    if lost_to_the_network(r):
        return None
    blocked = [run for run in r["runs"] if run["outcome"] == "blocked"]
    if blocked:
        songs = len(_songs(r))
        return f"blocked after {songs} song(s)" + (f" ({blocked[0]['reason']})" if blocked[0]["reason"] else "")
    failing = _failing(r)
    return f"failing: {', '.join(failing)}" if failing else None


def _clean(r: dict[str, Any]) -> bool:
    """A session that clears an earlier bad one: on mobile data with Start, a song downloaded, no block, none failing."""
    return _mobile_enforced(r) and bool(_ok_downloads(r)) and _bad(r) is None


@dataclass(frozen=True)
class _Standing:
    """The controller's ruling of 2026-11-27 on bad sessions: one holds the gate until a later session, on a later UTC
    day (so after any cooldown), is clean; then it is cleared, and the songs and the warm download are counted from
    the sessions after the last bad one (``since``, an index in the sorted reports)."""
    cleared: list[tuple[dict[str, Any], str]]
    uncleared: list[tuple[dict[str, Any], str]]
    since: int
    last_bad: dict[str, Any] | None


def _standing(reports: Sequence[dict[str, Any]]) -> _Standing:
    cleared, uncleared = [], []
    last = None
    for i, r in enumerate(reports):
        why = _bad(r)
        if why is None:
            continue
        last = i
        later = any(_clean(after) and _day(after) > _day(r) for after in reports[i + 1:])
        (cleared if later else uncleared).append((r, why))
    return _Standing(cleared, uncleared, 0 if last is None else last + 1,
                     None if last is None else reports[last])


def _works(reports: Sequence[dict[str, Any]]) -> Verdict:
    """Y0-W, the controller's ruling of 2026-11-27: on mobile data with Start (enforce), at least ``W_SONGS`` songs
    downloaded ok, over any number of sessions after the last bad one; a block or a song failing (not for the network's
    sake) holds the gate until a later day's clean session on mobile data clears it; on Wi-Fi on two days uncleared it
    is §3.8's trigger; a session the network lost, and a song it failed, count for nothing."""
    def session(r: dict[str, Any]) -> dict[str, Any]:
        ends = {song: _song_end(runs) for song, runs in _songs(r)}
        decoded = sum(1 for run in _ok_downloads(r) if run["decoded"] is not None)
        errors = [f"{run['kind']} of “{run['song']}”: error: {run['reason'] or 'no reason given'}"
                  for run in r["runs"] if run["outcome"] == "error"]
        return {"session": _label(r), "day": _day(r), "songs": len(ends), "ends": list(ends.values()), "errors": errors,
                "failing": _failing(r), "decoded": decoded, "ok": sum(1 for e in ends.values() if e == "ok"),
                "downloads_ok": len(_ok_downloads(r)),
                "blocked": sum(1 for run in r["runs"] if run["outcome"] == "blocked"), "stopped": r["stopped"],
                "lost": lost_to_the_network(r)}

    every = [session(r) for r in reports]
    standing = _standing(reports)
    counted = [w for w in every if not w["lost"]]
    enforced = [w for i, (w, r) in enumerate(zip(every, reports)) if i >= standing.since and _mobile_enforced(r)]
    lost = [w["session"] for w in every if w["lost"]]
    network = [song for r in reports if not lost_to_the_network(r) for song in _network_songs(r)]
    numbers: dict[str, Any] = {
        "wifi": [w for w, r in zip(every, reports) if r["network"]["transport"] == "wifi"],
        "mobile": [w for w, r in zip(every, reports) if r["network"]["transport"] == "cellular"],
        "lost": lost, "network_songs": [name for name, _ in network], "days": [w["day"] for w in every],
        "cleared": [_label(r) for r, _ in standing.cleared], "uncleared": [_label(r) for r, _ in standing.uncleared],
        "mobile_downloads_ok": sum(w["ok"] for w in enforced)}
    notes = []
    if lost:
        notes.append("lost to the network, counted for nothing: " + "; ".join(
            f"{w['session']} ({'; '.join(w['errors'])})" for w in every if w["lost"]))
    if network:
        notes.append("songs the network failed, counted for nothing: " + "; ".join(
            f"{name} ({why})" for name, why in network))
    unfit = [f"{w['session']} {n} song(s)" for w in counted if (n := w["ends"].count("no fit"))]
    if unfit:
        notes.append(f"a search no video fitted ({', '.join(unfit)}): type “Artist - Title”, the artist first")
    other = [f"{w['session']} {w['ends'].count(e)} {e}" for w in counted for e in ("unavailable", "pass_over")
             if e in w["ends"]]
    if other:
        notes.append(f"songs YouTube has no download of, counted as none ({', '.join(other)})")
    notes += [f"{w['session']} stopped: {w['stopped']}" for w in counted if w["stopped"] and not w["blocked"]]
    if standing.cleared:
        notes.append("cleared by a later day's clean session on mobile data: " + "; ".join(
            f"cleared: {_label(r)} ({why})" for r, why in standing.cleared))
    note = "".join(f"; {n}" for n in notes)

    if standing.uncleared:
        said = "; ".join(f"{_label(r)}: {why}" for r, why in standing.uncleared)
        wifi_days = {_day(r) for r, _ in standing.uncleared if r["network"]["transport"] == "wifi"}
        if len(wifi_days) >= 2:
            return Verdict(False, numbers, f"{said}: blocked or failing on Wi-Fi on two days, after any cooldown, with "
                                           "no clean day after: §3.8's trigger (Y0.7), if the computer's yt-dlp "
                                           "worked on the same Wi-Fi the same hour (no report says: check it before "
                                           f"NewPipe is taken){note}")
        return Verdict(None, numbers, f"Gate Y0 waits: {said}: run a session on mobile data with Start on a later day, "
                                      "after any cooldown: its songs downloaded with no block and none failing clear "
                                      f"it{note}")
    since = (f", counted from the sessions after {_label(standing.last_bad)}" if standing.last_bad is not None
             else "")
    ok = numbers["mobile_downloads_ok"]
    if ok >= W_SONGS:
        return Verdict(True, numbers, f"{ok} songs downloaded on mobile data with Start over {len(enforced)} "
                                      f"session(s){since}, none failing, none blocked{note}")
    more = W_SONGS - ok
    return Verdict(None, numbers, f"{ok} of {W_SONGS} songs downloaded on mobile data with Start{since}: run {more} "
                                  f"more on mobile data with Start, two or three songs in one session{note}")


def _time(reports: Sequence[dict[str, Any]]) -> Verdict:
    """Y0-T: each cold and warm limit wherever measured; the warm download it needs is one ended ok in an enforced
    mobile-data session after the last bad one (``_Standing``)."""
    sessions = []
    since = _standing(reports).since
    for i, r in enumerate(reports):
        if lost_to_the_network(r):
            continue
        downloads = [run for run in r["runs"] if run["kind"] == "download"]
        cold = next((run for run in downloads if run["cache"] == "cold" and run["outcome"] == "ok"), None)
        if cold is None:
            continue
        song = [run for run in r["runs"] if run["song"] == cold["song"]]
        warm = [run for run in downloads if run["cache"] == "warm" and run["outcome"] == "ok"]
        sessions.append({
            "session": _label(r), "wifi": r["network"]["transport"] == "wifi", "day": _day(r),
            "counts_warm": i >= since and _mobile_enforced(r),
            "cold_challenge_s": cold["challenge"]["seconds"] if cold["challenge"] else None,
            "cold_whole_s_less_sleeps": round(sum(_less_sleeps(run) for run in song), 3),
            "cold_whole_s": round(sum(run["seconds"] for run in song), 3),
            "warm_s_less_sleeps": [round(_less_sleeps(run), 3) for run in warm],
            "warm_s": [run["seconds"] for run in warm],
            "durations_s": [run["file"]["duration"] if run["file"] else None for run in [cold, *warm]],
        })
    numbers = {"sessions": sessions}
    if not sessions:
        return Verdict(None, numbers, "no cold download ended ok: run two or three songs in one session on mobile "
                                      "data with Start")
    unread = [s["session"] for s in sessions if s["cold_challenge_s"] is None]
    if unread:
        return Verdict(None, numbers, f"{', '.join(unread)}: no JS challenge read in the cold download (yt-dlp's "
                                      "words may have changed: BenchReport's pattern): read its log")
    over = []
    for s in sessions:
        if s["cold_challenge_s"] > T_COLD_CHALLENGE_S:
            over.append(f"{s['session']}: the cold challenge {s['cold_challenge_s']} s > {T_COLD_CHALLENGE_S:g} s")
        if s["cold_whole_s_less_sleeps"] > T_COLD_WHOLE_S:
            over.append(f"{s['session']}: the cold song {s['cold_whole_s_less_sleeps']} s less sleeps "
                        f"> {T_COLD_WHOLE_S:g} s")
        for w in s["warm_s_less_sleeps"]:
            if w > T_WARM_S:
                over.append(f"{s['session']}: a warm download {w} s less sleeps > {T_WARM_S:g} s")
    if not over and not any(s["warm_s_less_sleeps"] for s in sessions if s["counts_warm"]):
        return Verdict(None, numbers, "no warm download ended ok on mobile data with Start, so each warm download <= "
                                      f"{T_WARM_S:g} s is unmeasured: run two or three songs in one session on mobile "
                                      "data with Start (the second song's download is the warm one)")
    if not over:
        warm_said = "each warm download"
        return Verdict(True, numbers, f"over {len(sessions)} session(s), each cold challenge <= "
                                      f"{T_COLD_CHALLENGE_S:g} s, each cold song <= {T_COLD_WHOLE_S:g} s less "
                                      f"yt-dlp's sleeps, {warm_said} <= {T_WARM_S:g} s less sleeps")
    slow_wifi = [s for s in sessions if s["wifi"] and (s["cold_challenge_s"] > T_FALLBACK_CHALLENGE_S
                                                       or s["cold_whole_s"] > T_FALLBACK_WHOLE_S)]
    if len({s["day"] for s in slow_wifi}) >= 2:
        return Verdict(False, numbers, f"{'; '.join(over)}; over §3.8's {T_FALLBACK_CHALLENGE_S:g} s challenge or "
                                       f"{T_FALLBACK_WHOLE_S:g} s whole in two Wi-Fi sessions: §3.8 (Y0.7), after "
                                       "Y0's mitigations")
    return Verdict(None, numbers, f"{'; '.join(over)}: over the pass, short of §3.8's trigger (over "
                                  f"{T_FALLBACK_CHALLENGE_S:g} s or {T_FALLBACK_WHOLE_S:g} s in both Wi-Fi sessions): "
                                  "Y0's mitigations (QuickJS-NG's newest tag, the standard library trimmed), then "
                                  "again")


def _size(reports: Sequence[dict[str, Any]], growth_mb: float | None) -> Verdict:
    numbers = {"apk_growth_mb": growth_mb, "debug_apk_bytes": sorted({r["apk_bytes"] for r in reports})}
    if growth_mb is None:
        return Verdict(None, numbers, "a report holds the debug APK's size, not the release-equivalent arm64 APK's "
                                      "growth (assembleRelease with :youtube as implementation): give it, "
                                      "--apk-growth-mb")
    if growth_mb <= S_PASS_MB:
        return Verdict(True, numbers, f"{growth_mb:g} MB <= {S_PASS_MB:g} MB")
    if growth_mb > S_FAIL_MB:
        return Verdict(False, numbers, f"{growth_mb:g} MB > {S_FAIL_MB:g} MB: after trimming, §3.8 (Y0.7)")
    return Verdict(None, numbers, f"{growth_mb:g} MB, between {S_PASS_MB:g} and {S_FAIL_MB:g} MB: the owner is asked")


def youtubei(reports: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """``youtubei.googleapis.com`` in the gates' logs: under observe the asks (connects and refusals) and the runs that
    asked it; under enforce the runs that ended ok and how many of them asked it (and were refused). Numbers alone."""
    observed = [run for r in reports if r["gate"] == "observe" for run in r["runs"]]
    enforced = [run for r in reports if r["gate"] == "enforce" for run in r["runs"]]
    asked = [run for run in observed if YOUTUBEI in run["hosts"]]
    ok = [run for run in enforced if run["outcome"] == "ok"]
    return {
        "observed_runs": len(observed),
        "observed_runs_asking": len(asked),
        "observed_connects": sum(run["hosts"][YOUTUBEI]["connects"] for run in asked),
        "observed_runs_asking_ok": sum(1 for run in asked if run["outcome"] == "ok"),
        "enforced_runs": len(enforced),
        "enforced_ok": len(ok),
        "enforced_ok_asking_refused": sum(1 for run in ok if YOUTUBEI in run["hosts"]),
        "enforced_refused_asks": sum(run["hosts"][YOUTUBEI]["refused"] for run in enforced if YOUTUBEI in run["hosts"]),
    }


def _hosts(reports: Sequence[dict[str, Any]], gate: dict[str, Any]) -> Verdict:
    outside: dict[str, int] = {}
    by_name: set[str] = set()
    hosts: set[str] = set()
    bytes_over, unmeasured, per_run = [], [], []
    # The controller's ruling of 2026-11-27: the uid's bytes are judged over the idle sessions alone (a session not
    # idle counts another job's bytes too); one not idle is set aside from them, named, and counts everywhere else.
    not_idle = [_label(r) for r in reports if not r["idle"]]
    idle = [r for r in reports if r["idle"]]
    for r in reports:
        for i, run in enumerate(r["runs"]):
            gate_bytes = sum(u["bytes_up"] + u["bytes_down"] for u in run["hosts"].values())
            per_run.append({"uid": run["uid_bytes"], "gate": gate_bytes})
            for host, use in run["hosts"].items():
                hosts.add(host)
                if _refused_by_name(host, gate):
                    by_name.add(host)
                elif not is_youtubes(host, gate):
                    outside[host] = outside.get(host, 0) + use["connects"] + use["refused"]
            if not r["idle"]:
                continue
            if run["uid_bytes"] is None:
                unmeasured.append(f"{_label(r)} run {i + 1}")
            elif run["uid_bytes"] > _uid_bound(gate_bytes):
                bytes_over.append(f"{_label(r)} run {i + 1}: uid {run['uid_bytes']} B > {_uid_bound(gate_bytes)} B, "
                                  f"{H_UID_LEGS} legs x (1 + {H_UID_HEADERS:g}) of the gate's {gate_bytes} B + "
                                  f"{H_UID_SLACK} B")
    numbers = {"hosts": sorted(hosts), "outside_youtubes": outside, "refused_by_name_asked": sorted(by_name),
               "bytes": per_run, "idle": [r["idle"] for r in reports],
               "uid_over": bytes_over, "uid_unmeasured": unmeasured, "not_idle": not_idle, "set_aside": not_idle,
               "judged": [_label(r) for r in idle],
               "uid_counts": sorted({uid_counts(r) for r in reports}),
               "youtubei": youtubei(reports)}
    if not reports or not any(r["runs"] for r in reports):
        return Verdict(None, numbers, "no run")
    fails = []
    if by_name:
        fails.append(f"asked for what is refused by name: {', '.join(sorted(by_name))}")
    own = {gate["stopped"]: "the gate stopped taking connections: a bug of the gate's",
           gate["malformed"]: "requests the gate couldn't read (no host, a bad method or target)",
           gate["other_hosts"]: "more hosts than the gate's log names, counted together"}
    for key, words in own.items():
        if key in outside:
            fails.append(f"{key}: {words}")
    others = sorted(h for h in outside if h != YOUTUBEI and h not in own)
    if others:
        fails.append(f"hosts outside YouTube's: {', '.join(others)} (a flag or a client to change, or a stop)")
    if bytes_over:
        fails.append("the uid's bytes past the gate's three legs (a bypass of the gate?): " + "; ".join(bytes_over))
    if fails:
        return Verdict(False, numbers, "; ".join(fails))
    if YOUTUBEI in outside:
        return Verdict(None, numbers, f"{YOUTUBEI} asked for, whose use isn't decided: the controller's (Y0.4's "
                                      "rule, by a named commit), from the youtubei numbers")
    aside = (f"; set aside from the bytes, not idle: {', '.join(not_idle)} (its hosts still judged)"
             if not_idle else "")
    held = [r for r in idle if r["network"]["transport"] == "cellular" and r["gate"] == "enforce" and _ok_downloads(r)]
    if not held:
        return Verdict(None, numbers, "no idle session on mobile data with Start held a download, so the uid's bytes "
                                      "of a download are unjudged: run one with the app idle (no sync, no library "
                                      f"page open){aside}")
    if unmeasured:
        return Verdict(None, numbers, f"the uid's bytes unmeasured: {', '.join(unmeasured)}{aside}")
    observed = sum(1 for r in reports if r["gate"] == "observe")
    return Verdict(True, numbers, "only YouTube's hosts asked, nothing refused by name asked for, each run's uid bytes "
                                  f"(loopback too) explained by the gate's: <= {H_UID_LEGS} legs x "
                                  f"(1 + {H_UID_HEADERS:g}) + {H_UID_SLACK} B, over {len(idle)} idle session(s) "
                                  f"judged{aside}"
                                  + ("" if observed else "; no observed session: the enforcing gates' logs of every "
                                                         "host asked and refused answer it"))


def _uid_bound(gate_bytes: int) -> int:
    """The most uid bytes a run's gate bytes explain (H_UID_LEGS' comment)."""
    return round(H_UID_LEGS * (1 + H_UID_HEADERS) * gate_bytes) + H_UID_SLACK


def _blocks(reports: Sequence[dict[str, Any]]) -> Verdict:
    unclassified = [f"{_label(r)} run {i + 1}: {run['outcome']!r}" for r in reports
                    for i, run in enumerate(r["runs"]) if run["outcome"] not in CLASSES]
    after = {_label(r): r["after_block_requests"] for r in reports}
    blocked = sum(1 for r in reports for run in r["runs"] if run["outcome"] == "blocked")
    numbers = {"unclassified": unclassified, "after_block_requests": after, "blocked_runs": blocked}
    sent_after = {label: n for label, n in after.items() if n}
    if unclassified or sent_after:
        return Verdict(False, numbers, "; ".join(
            ([f"unclassified: {', '.join(unclassified)}"] if unclassified else []) +
            ([f"requests after a block: {sent_after}"] if sent_after else [])) + ": fix, run again")
    return Verdict(True, numbers, "every run classified, nothing sent after a block (a gate refusal and a proxy 407 "
                                  "told apart is Y1.1's vectors', not a report's)")


def _file(reports: Sequence[dict[str, Any]]) -> Verdict:
    rows, fails, unknown = [], [], []
    for r in reports:
        for run in _ok_downloads(r):
            where = f"{_label(r)} “{run['song']}”"
            d, f = run["decoded"], run["file"]
            if d is None:
                fails.append(f"{where}: not decoded")
                continue
            if f is None or f["duration"] is None or d["rate"] <= 0:
                unknown.append(f"{where}: no duration from yt-dlp")
                continue
            gap = round(abs(d["frames"] / d["rate"] - f["duration"]), 3)
            rows.append({"song": where, "decoded_s": round(d["frames"] / d["rate"], 3), "duration_s": f["duration"],
                         "gap_s": gap})
            if gap > F_WITHIN_S:
                fails.append(f"{where}: decoded {gap} s off yt-dlp's duration")
    numbers = {"downloads": rows, "unknown": unknown}
    if fails:
        return Verdict(False, numbers, "; ".join(fails) + ": remux to plain MP4 with MediaMuxer before decoding, then "
                                                          "again; else a stop")
    if unknown or not rows:
        return Verdict(None, numbers, "; ".join(unknown) if unknown else "no download ended ok")
    return Verdict(True, numbers, f"{len(rows)} download(s) decoded, each within {F_WITHIN_S:g} s of yt-dlp's "
                                  "duration")


def _kill(reports: Sequence[dict[str, Any]]) -> Verdict:
    rows = [dict(r["kill_check"], session=_label(r)) for r in reports]
    numbers = {"checks": rows}
    fails = [f"{k['session']}: left {', '.join(k['left'])}" for k in rows if k["run"] and k["left"]]
    fails += [f"{k['session']}: the run wasn't killed" for k in rows if k["run"] and not k["killed"]]
    fails += [f"{k['session']}: the next run failed" for k in rows if k["run"] and not k["next_run_ok"]]
    if fails:
        return Verdict(False, numbers, "; ".join(fails) + ": fix (a process group of its own), run again")
    unproven = [f"{k['session']}: not run ({k['why']})" for k in rows if not k["run"]]
    unproven += [f"{k['session']}: no qjs seen running, so it shows nothing of qjs" for k in rows
                 if k["run"] and not k["qjs_seen"]]
    if unproven or not rows:
        return Verdict(None, numbers, "; ".join(unproven) or "no report")
    return Verdict(True, numbers, f"{len(rows)} kill check(s): no :youtube or qjs process left 2 s after, the next "
                                  "run ok")


def _memory(reports: Sequence[dict[str, Any]]) -> Verdict:
    peaks = [sum(run["pss_peak_mb"].values()) for r in reports for run in r["runs"] if run["pss_peak_mb"]]
    peak = round(max(peaks), 1) if peaks else None
    numbers = {"pss_peak_mb": peak, "runs_sampled": len(peaks),
               "how": "each run's peaks of :youtube and qjs added (at most what they held together)"}
    if peak is None:
        return Verdict(None, numbers, "no run's PSS sampled")
    if peak <= M_PASS_MB:
        return Verdict(True, numbers, f"{peak} MB <= {M_PASS_MB:g} MB")
    if peak > M_ASK_MB:
        return Verdict(None, numbers, f"{peak} MB > {M_ASK_MB:g} MB: the owner is asked (phones of 6 GB are the "
                                      "floor)")
    return Verdict(None, numbers, f"{peak} MB, over the pass's {M_PASS_MB:g} MB, short of the row's {M_ASK_MB:g} MB: "
                                  "the owner's word")


def _start(reports: Sequence[dict[str, Any]]) -> Verdict:
    firsts = [r for r in reports if r["first_start"]["first_after_install"]]
    warm_ms = [run["python_ready_ms"] for r in reports for run in r["runs"][1:] if run["python_ready_ms"] >= 0]
    warm_ms += [run["python_ready_ms"] for r in reports if not r["first_start"]["first_after_install"]
                for run in r["runs"][:1] if run["python_ready_ms"] >= 0]
    first = firsts[0]["first_start"]["python_ready_ms"] if firsts else None
    least = min(warm_ms) if warm_ms else None
    numbers = {"first_after_install_python_ready_ms": first, "least_warm_python_ready_ms": least,
               "sessions_first_after_install": len(firsts)}
    if first is None or first < 0:
        return Verdict(None, numbers, "no session began with the first run after install: install again (Chaquopy's "
                                      "files not extracted yet) before one")
    if least is None:
        return Verdict(None, numbers, "no warm run to compare with")
    slow = f"; a warm start of {least} ms, over {C_WARM_START_MS} ms, is no fail (§3.2)" if least > C_WARM_START_MS else ""
    if first - least <= C_MORE_MS:
        return Verdict(True, numbers, f"the first run's Python {first - least} ms after a warm run's, <= {C_MORE_MS} "
                                      f"ms{slow}")
    return Verdict(False, numbers, f"the first run's Python {first - least} ms after a warm run's, > {C_MORE_MS} ms: "
                                   f"Chaquopy's extractPackages narrowed, then again{slow}")


def _sessions(reports: Sequence[dict[str, Any]]) -> Verdict:
    """The sessions given and their days, reported (the controller's ruling of 2026-11-27: neither two days nor an
    observed session is required); what the gate needs is one session on mobile data with Start the network didn't
    lose."""
    observed = [r for r in reports if r["gate"] == "observe"]
    enforced = [r for r in reports if r["network"]["transport"] == "cellular" and r["gate"] == "enforce"
                and not lost_to_the_network(r)]
    lost = [r for r in reports if lost_to_the_network(r)]
    days = sorted({_day(r) for r in reports})
    numbers = {"observed": [_label(r) for r in observed], "enforced_mobile": [_label(r) for r in enforced],
               "lost_to_the_network": [_label(r) for r in lost], "days": days}
    said = (f"{len(reports)} session(s) on {len(days)} UTC day(s): {len(enforced)} on mobile data with Start, "
            f"{len(observed)} observed, {len(lost)} lost to the network")
    said += ("; " + ("no observed session: wanted, not needed (an enforcing gate logs every host asked and refused)"
                     if not observed else "the observed ones' hosts judged in Y0-H"))
    if len(days) < 2:
        said += "; what one day can't show: what YouTube does after days of a phone asking"
    if not enforced:
        return Verdict(None, numbers, f"no session on mobile data with Start that reached YouTube: run one; {said}")
    return Verdict(True, numbers, said)


def gate(reports: Sequence[dict[str, Any]], *, apk_growth_mb: float | None = None) -> dict[str, Verdict]:
    """Each of §4.4's gates (and ``terms``) over ``reports``, each checked to be the bench's (``check_shape``): a
    session given twice (one ``started_at``) is ReportError, as it would count its runs twice."""
    for i, r in enumerate(reports):
        check_shape(r, f"report {i + 1}")
    starts = [r["started_at"] for r in reports]
    twice = sorted({s for s in starts if starts.count(s) > 1})
    if twice:
        raise ReportError(f"the session of {', '.join(twice)} given twice")
    reports = sorted(reports, key=lambda r: r["started_at"])
    youtube = _youtube_gate()
    return {
        "sessions": _sessions(reports),
        "terms": _terms(reports, youtube),
        "Y0-W": _works(reports),
        "Y0-T": _time(reports),
        "Y0-S": _size(reports, apk_growth_mb),
        "Y0-H": _hosts(reports, youtube),
        "Y0-B": _blocks(reports),
        "Y0-F": _file(reports),
        "Y0-K": _kill(reports),
        "Y0-M": _memory(reports),
        "Y0-C": _start(reports),
    }


def whole(verdicts: dict[str, Verdict]) -> bool | None:
    """Gate Y0 whole: passed when every gate did, False when one failed, else undecided."""
    said = [v.passed for v in verdicts.values()]
    if False in said:
        return False
    return True if all(said) else None


def main(argv: list[str]) -> int:
    args = list(argv)
    growth = None
    while "--apk-growth-mb" in args:
        at = args.index("--apk-growth-mb")
        if at + 1 >= len(args):
            print("--apk-growth-mb needs a number of MB", file=sys.stderr)
            return 2
        try:
            growth = float(args[at + 1])
        except ValueError:
            growth = math.nan
        if not math.isfinite(growth) or growth < 0:
            print(f"--apk-growth-mb {args[at + 1]!r} isn't a number of MB, 0 or more", file=sys.stderr)
            return 2
        del args[at:at + 2]
    if not args:
        print("usage: python -m tests.helpers.ytbench_gate [--apk-growth-mb N] REPORT…", file=sys.stderr)
        return 2
    try:
        reports = [read(path) for path in args]
        verdicts = gate(reports, apk_growth_mb=growth)
    except ReportError as e:
        print(f"UNREADABLE: {e}", file=sys.stderr)
        return 2
    for name, v in verdicts.items():
        print(f"{GATES[name]}: {v.said} · {json.dumps(v.numbers, ensure_ascii=False)} · {v.why}")
    print(f"note: {YOUTUBEI}: {json.dumps(youtubei(reports))} (the controller decides)")
    result = whole(verdicts)
    print(f"Gate Y0: {Verdict(result).said}")
    return {True: 0, False: 1, None: 2}[result]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
