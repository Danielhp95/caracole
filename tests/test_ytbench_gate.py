"""tests/helpers/ytbench_gate.py, Gate Y0's checker, over synthetic reports.

Every report here is made from tests/fixtures/ytbench/sample.json, which the Kotlin side's BenchReportTest holds to
what ``BenchReport.of`` writes for fixed inputs: one shape on both sides. A session is that sample moved to a day, a
network and a gate mode, then changed where a test needs it. Its songs and hosts are made up.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from helpers import ytbench_gate as yg
from helpers.ytbench_gate import ReportError, gate, main, read, whole, youtubei

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "ytbench" / "sample.json"


def session(day: str = "2026-11-28", transport: str = "cellular", mode: str = "enforce",
            first_after_install: bool = False) -> dict:
    """The sample as a session of ``day`` (its UTC date), on ``transport``, its gate ``mode``."""
    report = json.loads(SAMPLE.read_text(encoding="utf-8"))
    report = json.loads(json.dumps(report).replace("2026-11-28T", f"{day}T"))
    report["network"] = {"transport": transport, "metered": transport == "cellular", "validated": True}
    report["gate"] = mode
    report["first_start"]["first_after_install"] = first_after_install
    return report


def pair() -> list[dict]:
    """Day 1 on Wi-Fi, observed; day 2 on mobile data, enforced: the brief's two sessions."""
    return [session("2026-11-28", "wifi", "observe", first_after_install=True),
            session("2026-11-29", "cellular", "enforce")]


def said(reports, **kw) -> dict:
    return {name: v.passed for name, v in gate(reports, **kw).items()}


def run_of(report: dict, song: int, kind: str) -> dict:
    """The ``kind`` run of the ``song``-th song (from 0)."""
    names = list(dict.fromkeys(r["song"] for r in report["runs"]))
    return next(r for r in report["runs"] if r["song"] == names[song] and r["kind"] == kind)


# -- the sample and the shape --------------------------------------------------------------------------------------


def test_the_sample_is_the_benchs_shape_member_for_member():
    report = read(SAMPLE)
    assert report["format"] == yg.FORMAT
    assert set(report) == set(yg.REPORT_MEMBERS) | set(yg.UID_COUNTS_MEMBER)
    assert all(set(run) == set(yg.RUN_MEMBERS) for run in report["runs"])
    assert set(report["kill_check"]) == set(yg.KILL_RAN_MEMBERS)
    # Its hosts are YouTube-shaped, and youtube.json's gate allows them.
    hosts = {h for run in report["runs"] for h in run["hosts"]}
    assert hosts and all(yg.is_youtubes(h) for h in hosts)


@pytest.mark.parametrize(("change", "words"), [
    (lambda r: r.pop("kill_check"), "has no member 'kill_check'"),
    (lambda r: r["runs"][0].pop("hosts"), "run 1 has no member 'hosts'"),
    (lambda r: r.update(extra=1), "'extra', which the bench doesn't write"),
    (lambda r: r.update(format=2), "of format 2"),
    (lambda r: r["runs"][1]["hosts"]["www.youtube.com"].pop("bytes_down"), "has no member 'bytes_down'"),
    (lambda r: r["runs"][0].update(seconds="6.5"), "'seconds' is a str"),
    (lambda r: r.update(started_at="yesterday"), "isn't a UTC stamp"),
    (lambda r: r["summary"].pop("K"), "summary isn't the bench's"),
])
def test_a_report_not_of_the_benchs_shape_is_unreadable_in_words(change, words, tmp_path):
    report = session()
    change(report)
    path = tmp_path / "caracole-ytbench-x.json"
    path.write_text(json.dumps(report))
    with pytest.raises(ReportError) as e:
        read(path)
    assert words in str(e.value) and str(path) in str(e.value)


def test_a_file_that_isnt_json_is_unreadable(tmp_path):
    path = tmp_path / "r.json"
    path.write_text("{not json")
    with pytest.raises(ReportError, match="isn't JSON"):
        read(path)


def test_the_same_session_given_twice_is_refused_as_it_would_count_its_runs_twice():
    with pytest.raises(ReportError, match="given twice"):
        gate([session(), session()])


# -- the whole gate ------------------------------------------------------------------------------------------------


def test_the_two_sessions_pass_every_gate_with_the_apks_growth_given():
    verdicts = gate(pair(), apk_growth_mb=30)
    assert {n: v.passed for n, v in verdicts.items()} == dict.fromkeys(yg.GATES, True), \
        {n: v.why for n, v in verdicts.items() if not v.passed}
    assert whole(verdicts) is True
    assert "2 session(s) on 2 UTC day(s)" in verdicts["sessions"].why


def test_one_enforced_mobile_session_of_three_songs_passes_every_gate_with_no_observed_one():
    mobile = session("2026-11-28", "cellular", "enforce", first_after_install=True)
    verdicts = gate([mobile], apk_growth_mb=30)
    assert {n: v.passed for n, v in verdicts.items()} == dict.fromkeys(yg.GATES, True), \
        {n: v.why for n, v in verdicts.items() if not v.passed}
    assert "what one day can't show" in verdicts["sessions"].why
    assert "no observed session" in verdicts["sessions"].why


def test_without_the_apks_growth_size_and_so_the_whole_gate_are_undecided():
    verdicts = gate(pair())
    assert verdicts["Y0-S"].passed is None and "--apk-growth-mb" in verdicts["Y0-S"].why
    assert whole(verdicts) is None


# -- each gate: pass, fail, undecided -----------------------------------------------------------------------------


def test_works_waits_on_one_block_and_says_run_again_another_day():
    wifi, mobile = pair()
    run_of(wifi, 2, "download")["outcome"] = "blocked"
    v = gate([wifi, mobile])["Y0-W"]
    assert v.passed is None and "Gate Y0 waits" in v.why and "run again another day" in v.why


def test_works_on_songs_failing_two_days_names_the_fallbacks_trigger():
    one = session("2026-11-28", "cellular", "enforce")
    two = session("2026-11-30", "cellular", "enforce")
    for r in (one, two):
        run_of(r, 2, "download").update(outcome="error", reason="ERROR: [youtube] x: Requested format is not available")
        run_of(r, 1, "download")["outcome"] = "gate_refused"
    v = gate([one, two])["Y0-W"]
    assert v.passed is False and "§3.8's trigger (Y0.7)" in v.why
    assert "Requested format is not available" in v.why


def test_works_waits_on_songs_failing_one_day_saying_why():
    mobile = session("2026-11-28", "cellular", "enforce")
    run_of(mobile, 2, "download").update(outcome="error", reason="ERROR: [youtube] x: Requested format is not available")
    v = gate([mobile])["Y0-W"]
    assert v.passed is None and "Gate Y0 waits" in v.why and "Requested format is not available" in v.why


def test_works_needs_three_songs_downloaded_on_mobile_data_over_any_sessions():
    wifi, mobile = pair()
    mobile["runs"] = mobile["runs"][:4]
    v = gate([wifi, mobile])["Y0-W"]
    assert v.passed is None
    assert "2 of 3 songs downloaded on mobile data with Start" in v.why and "1 more" in v.why
    v = gate([session("2026-11-28", "wifi", "observe")])["Y0-W"]
    assert v.passed is None and "0 of 3 songs downloaded on mobile data" in v.why
    # Over two sessions: two songs one day and one the next are three.
    one = session("2026-11-28", "cellular", "enforce")
    one["runs"] = one["runs"][:4]
    two = session("2026-11-29", "cellular", "enforce")
    two["runs"] = two["runs"][:2]
    assert gate([one, two])["Y0-W"].passed is True


def test_works_counts_a_song_unavailable_as_no_download_and_no_failure():
    mobile = session("2026-11-28", "cellular", "enforce")
    run_of(mobile, 2, "download").update(outcome="unavailable", file=None, decoded=None)
    v = gate([mobile])["Y0-W"]
    assert v.passed is None and "2 of 3 songs downloaded" in v.why and "unavailable" in v.why


def test_time_over_the_pass_in_one_wifi_session_is_undecided_and_over_the_fallback_in_two_fails():
    wifi, mobile = pair()
    run_of(wifi, 0, "download")["challenge"]["seconds"] = 70.0
    v = gate([wifi, mobile])["Y0-T"]
    assert v.passed is None and "short of §3.8's trigger" in v.why
    other = session("2026-11-30", "wifi", "observe")
    run_of(other, 0, "download")["seconds"] = 125.0
    v = gate([wifi, mobile, other])["Y0-T"]
    assert v.passed is False and "§3.8 (Y0.7)" in v.why


def test_time_counts_the_cold_song_less_yt_dlps_sleeps_and_says_so():
    wifi, mobile = pair()
    v = gate([wifi, mobile])["Y0-T"]
    assert v.passed is True
    assert v.numbers["sessions"][0]["cold_whole_s_less_sleeps"] == 22.5
    assert v.numbers["sessions"][0]["cold_whole_s"] == 26.0
    run_of(wifi, 1, "download")["seconds"] = 19.0  # 15.5 less its 3.5 s sleep
    assert gate([wifi, mobile])["Y0-T"].passed is None


def test_time_without_a_warm_download_says_run_two_or_three_songs_in_one_session():
    mobile = session("2026-11-28", "cellular", "enforce")
    mobile["runs"] = mobile["runs"][:2]
    v = gate([mobile])["Y0-T"]
    assert v.passed is None and "run two or three songs in one session" in v.why


def test_time_is_undecided_with_no_challenge_read_or_no_cold_download():
    wifi, mobile = pair()
    run_of(wifi, 0, "download")["challenge"] = None
    assert "no JS challenge read" in gate([wifi, mobile])["Y0-T"].why
    for r in (wifi, mobile):
        run_of(r, 0, "download")["outcome"] = "error"
    assert gate([wifi, mobile])["Y0-T"].passed is None


@pytest.mark.parametrize(("growth", "passed"), [(30, True), (35, True), (40, None), (46, False), (None, None)])
def test_size_by_the_growth_given(growth, passed):
    assert gate(pair(), apk_growth_mb=growth)["Y0-S"].passed is passed


def test_hosts_fail_on_a_host_outside_youtubes_or_one_refused_by_name():
    wifi, mobile = pair()
    run_of(wifi, 1, "download")["hosts"]["i.ytimg.com"] = {"connects": 1, "bytes_up": 1, "bytes_down": 2,
                                                          "refused": 0, "apart": False}
    v = gate([wifi, mobile])["Y0-H"]
    assert v.passed is False and "i.ytimg.com" in v.why
    wifi, mobile = pair()
    run_of(mobile, 1, "download")["hosts"]["jnn-pa.googleapis.com"] = {"connects": 0, "bytes_up": 0,
                                                                      "bytes_down": 0, "refused": 1, "apart": False}
    v = gate([wifi, mobile])["Y0-H"]
    assert v.passed is False and "refused by name" in v.why


def test_hosts_fail_when_the_uids_bytes_pass_the_gates():
    wifi, mobile = pair()
    run_of(mobile, 0, "search")["uid_bytes"] = 2_000_000
    assert gate([wifi, mobile])["Y0-H"].passed is False


def test_hosts_are_undecided_while_youtubei_is_undecided_the_app_wasnt_idle_or_the_uids_bytes_unmeasured():
    wifi, mobile = pair()
    run_of(wifi, 1, "download")["hosts"][yg.YOUTUBEI] = {"connects": 2, "bytes_up": 10, "bytes_down": 20,
                                                        "refused": 0, "apart": False}
    v = gate([wifi, mobile])["Y0-H"]
    assert v.passed is None and "the controller's" in v.why
    wifi, mobile = pair()
    mobile["idle"] = False
    assert "not idle" in gate([wifi, mobile])["Y0-H"].why
    wifi, mobile = pair()
    run_of(wifi, 0, "search")["uid_bytes"] = None
    assert gate([wifi, mobile])["Y0-H"].passed is None


def test_youtubei_gives_the_numbers_for_the_controller():
    wifi, mobile = pair()
    for song in (0, 1):
        run_of(wifi, song, "download")["hosts"][yg.YOUTUBEI] = {"connects": 3, "bytes_up": 1, "bytes_down": 1,
                                                               "refused": 0, "apart": False}
    run_of(mobile, 0, "download")["hosts"][yg.YOUTUBEI] = {"connects": 0, "bytes_up": 0, "bytes_down": 0,
                                                          "refused": 2, "apart": False}
    n = youtubei([wifi, mobile])
    assert n == {"observed_runs": 6, "observed_runs_asking": 2, "observed_connects": 6, "observed_runs_asking_ok": 2,
                 "enforced_runs": 6, "enforced_ok": 6, "enforced_ok_asking_refused": 1, "enforced_refused_asks": 2}


def test_blocks_fail_on_an_unclassified_run():
    wifi, mobile = pair()
    run_of(mobile, 1, "search")["outcome"] = "strange"
    v = gate([wifi, mobile])["Y0-B"]
    assert v.passed is False and "'strange'" in v.why


def test_file_fails_off_by_more_than_a_second_or_undecoded_and_is_undecided_with_no_duration():
    wifi, mobile = pair()
    run_of(mobile, 1, "download")["file"]["duration"] = 202.5
    assert gate([wifi, mobile])["Y0-F"].passed is False
    wifi, mobile = pair()
    run_of(mobile, 1, "download")["decoded"] = None
    assert "not decoded" in gate([wifi, mobile])["Y0-F"].why
    wifi, mobile = pair()
    run_of(mobile, 1, "download")["file"]["duration"] = None
    assert gate([wifi, mobile])["Y0-F"].passed is None


def test_kill_fails_on_a_process_left_and_is_undecided_unrun_or_with_no_qjs_seen():
    wifi, mobile = pair()
    mobile["kill_check"]["left"] = ["io.github.danielhp95.caracole.debug:youtube"]
    assert gate([wifi, mobile])["Y0-K"].passed is False
    wifi, mobile = pair()
    mobile["kill_check"] = {"run": False, "why": "its gate: the gate couldn't start"}
    assert gate([wifi, mobile])["Y0-K"].passed is None
    wifi, mobile = pair()
    wifi["kill_check"]["qjs_seen"] = False
    assert "no qjs seen" in gate([wifi, mobile])["Y0-K"].why


@pytest.mark.parametrize(("youtube", "passed"), [(400.0, True), (600.0, None), (900.0, None)])
def test_memory_by_the_peak_of_youtube_and_qjs_together(youtube, passed):
    wifi, mobile = pair()
    run_of(mobile, 2, "download")["pss_peak_mb"]["youtube"] = youtube
    v = gate([wifi, mobile])["Y0-M"]
    assert v.passed is passed
    assert v.numbers["pss_peak_mb"] == max(324.5, youtube + 88.5)


def test_start_fails_past_twenty_seconds_more_and_is_undecided_with_no_first_run_after_install():
    wifi, mobile = pair()
    wifi["first_start"]["python_ready_ms"] = 25_000
    assert gate([wifi, mobile])["Y0-C"].passed is False
    wifi["first_start"]["first_after_install"] = False
    assert gate([wifi, mobile])["Y0-C"].passed is None


# -- the owner's terms: refused, loudly ----------------------------------------------------------------------------


def capped(report: dict) -> dict:
    """The report as a bench of the six-run cap wrote it, before the owner lifted it: no ``lifted`` in its budget."""
    report["budget"].pop("lifted", None)
    return report


def test_more_than_six_runs_in_any_24_hours_across_the_reports_fails_the_terms():
    one = capped(session("2026-11-28", "wifi", "observe"))
    two = capped(session("2026-11-28", "cellular", "enforce"))
    two = json.loads(json.dumps(two).replace("2026-11-28T18:", "2026-11-28T23:"))
    v = gate([one, two])["terms"]
    assert v.passed is False and "runs within 24 hours" in v.why
    assert v.numbers["most_in_24h"] == 12
    # A day later, to the second: never more than six within 24 hours, the terms kept.
    two = json.loads(json.dumps(two).replace("2026-11-28T23:", "2026-11-29T18:"))
    assert gate([one, two])["terms"].passed is True


def test_a_run_after_a_block_or_requests_after_one_fail_the_terms():
    wifi, mobile = pair()
    run_of(mobile, 1, "download")["outcome"] = "blocked"
    v = gate([wifi, mobile])["terms"]
    assert v.passed is False and "2 run(s) after a block" in v.why
    wifi, mobile = pair()
    mobile["after_block_requests"] = 3
    assert "after_block_requests is 3" in gate([wifi, mobile])["terms"].why
    assert gate([wifi, mobile])["Y0-B"].passed is False


def test_observing_on_mobile_data_fails_the_terms_and_enforcing_on_wifi_never_does():
    v = gate([session("2026-11-28", "cellular", "observe")])["terms"]
    assert v.passed is False and "observed every host on mobile data" in v.why
    assert gate([session("2026-11-28", "wifi", "enforce")])["terms"].passed is True


def test_a_loopback_report_is_the_emulators_not_a_session():
    report = session()
    report["mode"] = "LOOPBACK"
    assert "the emulator's test session" in gate([report])["terms"].why


def test_a_host_reached_outside_youtubes_under_enforce_is_a_bug_of_the_gates():
    wifi, mobile = pair()
    run_of(mobile, 0, "search")["hosts"]["example.com"] = {"connects": 1, "bytes_up": 5, "bytes_down": 5,
                                                          "refused": 0, "apart": False}
    v = gate([wifi, mobile])["terms"]
    assert v.passed is False and "reached example.com under enforce" in v.why and "a bug" in v.why
    # Asked and refused under enforce is no bug (a gate_refused run): it fails the hosts, not the terms.
    run_of(mobile, 0, "search")["hosts"]["example.com"] = {"connects": 0, "bytes_up": 0, "bytes_down": 0,
                                                          "refused": 1, "apart": False}
    assert gate([wifi, mobile])["terms"].passed is True
    assert gate([wifi, mobile])["Y0-H"].passed is False


@pytest.mark.parametrize("where", ["said", "reason", "stopped"])
def test_a_gate_shaped_proxy_address_anywhere_fails_and_says_where(where):
    wifi, mobile = pair()
    secret = f"http://{'a' * 32}:{'b' * 32}@127.0.0.1:41234"
    run = run_of(mobile, 1, "download")
    if where == "said":
        run["said"].append(f"WARNING: via {secret}")
    elif where == "reason":
        run["reason"] = f"Unable to connect to proxy {secret}"
    else:
        mobile["stopped"] = secret
    v = gate([wifi, mobile])["terms"]
    assert v.passed is False and "a gate-shaped proxy address" in v.why
    assert {"said": "$.runs[3].said[1]", "reason": "$.runs[3].reason", "stopped": "$.stopped"}[where] in v.why


# -- the command ---------------------------------------------------------------------------------------------------


def write(tmp_path: Path, reports: list[dict]) -> list[str]:
    paths = []
    for i, r in enumerate(reports):
        path = tmp_path / f"caracole-ytbench-{i}.json"
        path.write_text(json.dumps(r))
        paths.append(str(path))
    return paths


def test_the_command_says_a_line_a_gate_and_exits_0_when_every_gate_passed(tmp_path, capsys):
    assert main(["--apk-growth-mb", "30", *write(tmp_path, pair())]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split(":")[0] for line in lines[:len(yg.GATES)]] == list(yg.GATES.values())
    assert all(": PASS · " in line for line in lines[:len(yg.GATES)])
    assert lines[-2].startswith(f"note: {yg.YOUTUBEI}: ")
    assert lines[-1] == "Gate Y0: PASS"


def test_the_command_exits_1_for_a_fail_and_2_for_undecided(tmp_path, capsys):
    wifi, mobile = pair()
    mobile["after_block_requests"] = 1
    assert main(["--apk-growth-mb", "30", *write(tmp_path, [wifi, mobile])]) == 1
    assert capsys.readouterr().out.splitlines()[-1] == "Gate Y0: FAIL"
    assert main(write(tmp_path, pair())) == 2
    out = capsys.readouterr().out
    assert "Y0-S size: UNDECIDED" in out and out.splitlines()[-1] == "Gate Y0: UNDECIDED"


def test_the_command_exits_2_for_a_report_that_wont_read_and_says_which(tmp_path, capsys):
    broken = session()
    del broken["runs"][0]["outcome"]
    paths = write(tmp_path, [session("2026-11-27", "wifi", "observe"), broken])
    assert main(paths) == 2
    err = capsys.readouterr().err
    assert err.startswith("UNREADABLE: ") and paths[1] in err and "'outcome'" in err
    assert main([]) == 2
    assert main(["--apk-growth-mb", "many", paths[0]]) == 2


@pytest.mark.slow
def test_python_dash_m_runs_it(tmp_path):
    done = subprocess.run([sys.executable, "-m", "tests.helpers.ytbench_gate", "--apk-growth-mb", "30",
                           *write(tmp_path, pair())], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines()[-1] == "Gate Y0: PASS"



# -- fix round 1 ---------------------------------------------------------------------------------------------------


def _same_day() -> list[dict]:
    """One of each on one UTC day, two songs' worth of runs each (four in all: the day's six kept)."""
    wifi = session("2026-11-28", "wifi", "observe", first_after_install=True)
    mobile = json.loads(json.dumps(session("2026-11-28", "cellular", "enforce"))
                        .replace("2026-11-28T18:0", "2026-11-28T20:0"))
    for r in (wifi, mobile):
        r["runs"] = r["runs"][:2]
    return [wifi, mobile]


def test_the_sessions_need_one_on_mobile_data_with_start_and_report_the_days():
    verdicts = gate([session("2026-11-28", "wifi", "observe", first_after_install=True)], apk_growth_mb=30)
    v = verdicts["sessions"]
    assert v.passed is None and "no session on mobile data with Start" in v.why
    assert whole(verdicts) is None
    v = gate(_same_day(), apk_growth_mb=30)["sessions"]
    assert v.passed is True and "2 session(s) on 1 UTC day(s)" in v.why and "what one day can't show" in v.why
    v = gate(pair(), apk_growth_mb=30)["sessions"]
    assert v.passed is True and "1 observed" in v.why


def test_works_with_wifi_alone_is_undecided_it_needs_songs_on_mobile_data():
    v = gate([session("2026-11-28", "wifi", "observe")])["Y0-W"]
    assert v.passed is None and "on mobile data with Start" in v.why


def _blocked_at(report: dict, run: int) -> dict:
    """The session as the bench leaves it when run ``run`` (from 0) is blocked: no run after it, its stop said."""
    report["runs"] = report["runs"][:run + 1]
    report["runs"][run].update(outcome="blocked", file=None, decoded=None, reason="Sign in to confirm")
    report["stopped"] = "YouTube blocked a run: the session stops, and no run starts until its cooldown ends."
    return report


@pytest.mark.parametrize("run", [0, 1, 3])
def test_one_wifi_session_a_block_cut_short_leaves_gate_y0_waiting_never_too_few_songs(run):
    wifi, mobile = pair()
    verdicts = gate([_blocked_at(wifi, run), mobile], apk_growth_mb=30)
    v = verdicts["Y0-W"]
    assert v.passed is None and "Gate Y0 waits" in v.why
    assert "run again another day after any cooldown" in v.why and "not 3" not in v.why
    assert whole(verdicts) is None


def test_the_command_waits_on_one_blocked_wifi_day_and_fails_on_two(tmp_path, capsys):
    wifi, mobile = pair()
    assert main([*write(tmp_path, [_blocked_at(wifi, 0), mobile]), "--apk-growth-mb", "30"]) == 2
    assert capsys.readouterr().out.splitlines()[-1] == "Gate Y0: UNDECIDED"
    one = _blocked_at(session("2026-11-28", "wifi", "observe", first_after_install=True), 0)
    two = _blocked_at(session("2026-11-30", "wifi", "observe"), 1)
    other = tmp_path / "two"
    other.mkdir()
    assert main([*write(other, [one, two, session("2026-11-29", "cellular", "enforce")]),
                 "--apk-growth-mb", "30"]) == 1
    out = capsys.readouterr().out
    assert "§3.8's trigger (Y0.7)" in out and out.splitlines()[-1] == "Gate Y0: FAIL"


def test_two_wifi_days_cut_short_by_a_block_name_the_fallbacks_trigger():
    one = _blocked_at(session("2026-11-28", "wifi", "observe"), 0)
    two = _blocked_at(session("2026-11-30", "wifi", "observe"), 1)
    v = gate([one, two, session("2026-11-29", "cellular", "enforce")])["Y0-W"]
    assert v.passed is False and "§3.8's trigger (Y0.7)" in v.why


def test_a_session_stopped_without_a_block_is_undecided_in_its_stops_words():
    wifi, mobile = pair()
    mobile["runs"] = mobile["runs"][:2]
    mobile["stopped"] = "YouTube is cooling down after a block: no run."
    v = gate([wifi, mobile])["Y0-W"]
    assert v.passed is None and "cooling down" in v.why


@pytest.mark.parametrize("text", [f"{'a' * 32}:{'b' * 32}", f"x{'c' * 32}:{'d' * 32}y"])
def test_a_bare_user_and_secret_pair_fails_the_terms(text):
    wifi, mobile = pair()
    run_of(mobile, 0, "search")["said"].append(f"WARNING: {text}")
    assert gate([wifi, mobile])["terms"].passed is False


def test_a_kill_check_that_spent_runs_fails_the_terms():
    wifi, mobile = pair()
    mobile["kill_check"]["spends"] = 1
    v = gate([wifi, mobile])["terms"]
    assert v.passed is False and "kill check spent 1" in v.why


@pytest.mark.parametrize(("member", "words"), [
    ("stopped", "the gate stopped taking connections: a bug of the gate's"),
    ("malformed", "requests the gate couldn't read"),
    ("other_hosts", "more hosts than the gate's log names"),
])
def test_the_gates_own_log_keys_fail_hosts_saying_what_they_are(member, words):
    key = json.loads(yg.YOUTUBE_JSON.read_text())["gate"][member]
    wifi, mobile = pair()
    run_of(wifi, 0, "download")["hosts"][key] = {"connects": 0, "bytes_up": 0, "bytes_down": 0, "refused": 1,
                                                "apart": False}
    v = gate([wifi, mobile])["Y0-H"]
    assert v.passed is False and words in v.why and "a flag or a client" not in v.why


def test_time_with_no_warm_download_is_undecided():
    wifi, mobile = pair()
    for r in (wifi, mobile):
        for song in (1, 2):
            run_of(r, song, "download")["outcome"] = "error"
    v = gate([wifi, mobile])["Y0-T"]
    assert v.passed is None and "no warm download" in v.why


def test_the_checkers_numbers_are_the_benchs_summary_for_every_gate_both_compute():
    report = read(SAMPLE)
    s, v = report["summary"], gate([report])
    w = v["Y0-W"].numbers["mobile"][0]
    assert (w["songs"], w["downloads_ok"], w["decoded"], w["blocked"]) == \
        (s["W"]["songs"], s["W"]["downloads_ok"], s["W"]["decoded"], s["W"]["blocked"])
    t = v["Y0-T"].numbers["sessions"][0]
    assert t["cold_challenge_s"] == s["T"]["cold_challenge_s"]
    assert t["cold_whole_s_less_sleeps"] == s["T"]["cold_whole_s_less_sleeps"]
    assert t["cold_whole_s"] == s["T"]["cold_whole_s_with_sleeps"]
    assert t["warm_s_less_sleeps"] == s["T"]["warm_downloads_s_less_sleeps"]
    assert t["warm_s"] == s["T"]["warm_downloads_s_with_sleeps"]
    assert set(v["Y0-H"].numbers["hosts"]) == set(s["H"]["hosts"])
    assert v["Y0-H"].numbers["refused_by_name_asked"] == s["H"]["refused_by_name_asked"]
    assert len(v["Y0-B"].numbers["unclassified"]) == s["B"]["unclassified"]
    assert [d["gap_s"] for d in v["Y0-F"].numbers["downloads"]] == s["F"]["decoded_vs_duration_s"]
    assert len(v["Y0-K"].numbers["checks"][0]["left"]) == s["K"]["left"]
    assert v["Y0-M"].numbers["pss_peak_mb"] == s["M"]["pss_peak_mb"]
    assert v["Y0-C"].numbers["first_after_install_python_ready_ms"] == s["C"]["first_python_ready_ms"]
    assert v["Y0-C"].numbers["least_warm_python_ready_ms"] == s["C"]["least_later_python_ready_ms"]
    assert v["Y0-H"].numbers["bytes"] == s["H"]["bytes"]
    assert v["Y0-H"].numbers["idle"] == [s["H"]["idle"]]
    assert list(v["Y0-B"].numbers["after_block_requests"].values()) == [s["B"]["after_block_requests"]]


def test_a_runs_seconds_are_never_null_as_the_bench_writes_them_a_null_is_unreadable(tmp_path):
    # BenchRunRecord.seconds is a Double, written always: a warm download with null seconds is no report of the bench's.
    report = session()
    run_of(report, 1, "download")["seconds"] = None
    path = tmp_path / "r.json"
    path.write_text(json.dumps(report))
    with pytest.raises(ReportError, match="'seconds' is a null"):
        read(path)


def test_the_apks_growth_is_taken_anywhere_and_a_negative_or_nan_one_refused(tmp_path, capsys):
    paths = write(tmp_path, pair())
    assert main([*paths, "--apk-growth-mb", "30"]) == 0
    capsys.readouterr()
    for bad in ("-1", "nan", "inf"):
        assert main([paths[0], "--apk-growth-mb", bad, paths[1]]) == 2
        assert "--apk-growth-mb" in capsys.readouterr().err


# -- the day's cap, lifted at the owner's word of 2026-11-27 ----------------------------------------------------------


def test_the_sample_says_the_cap_was_lifted_and_an_old_report_without_it_reads():
    assert read(SAMPLE)["budget"]["lifted"] is True
    report = capped(session())
    report["budget"] = {"before": 0, "after": 1, "of": 6}
    report["runs"] = report["runs"][:1]
    yg.check_shape(report)


def test_a_lifted_member_that_isnt_a_bool_is_unreadable(tmp_path):
    report = session()
    report["budget"]["lifted"] = "yes"
    path = tmp_path / "r.json"
    path.write_text(json.dumps(report))
    with pytest.raises(ReportError, match="'lifted' is a str"):
        read(path)


def test_lifted_sessions_past_six_runs_in_24_hours_keep_the_terms_and_say_the_count():
    one = session("2026-11-28", "wifi", "observe")
    two = session("2026-11-28", "cellular", "enforce")
    two = json.loads(json.dumps(two).replace("2026-11-28T18:", "2026-11-28T23:"))
    two["budget"].update(before=6, after=12)
    v = gate([one, two])["terms"]
    assert v.passed is True, v.why
    assert v.numbers["most_in_24h"] == 12 and v.numbers["lifted"] == 2
    assert "12 runs in the busiest 24 hours" in v.why
    assert "the six-run cap lifted at the owner's word (2026-11-27)" in v.why


def test_a_capped_report_is_still_bound_by_the_six_even_beside_a_lifted_one():
    lifted = session("2026-11-28", "wifi", "observe")
    old = capped(session("2026-11-28", "cellular", "enforce"))
    old = json.loads(json.dumps(old).replace("2026-11-28T18:", "2026-11-28T23:"))
    v = gate([lifted, old])["terms"]
    assert v.passed is False and "runs within 24 hours" in v.why and "the day's runs are 6" in v.why
    # A capped session's runs before a lifted one's: the cap bound the capped runs alone, which kept it.
    early = capped(session("2026-11-28", "wifi", "observe"))
    late = json.loads(json.dumps(session("2026-11-28", "cellular", "enforce")).replace("2026-11-28T18:",
                                                                                      "2026-11-28T23:"))
    assert gate([early, late])["terms"].passed is True


def test_a_lifted_reports_count_past_its_of_is_no_fail_a_capped_ones_is():
    wifi, mobile = pair()
    mobile["budget"].update(before=7, after=13)
    assert gate([wifi, mobile])["terms"].passed is True
    capped(mobile)
    v = gate([wifi, mobile])["terms"]
    assert v.passed is False and "13 runs in 24 hours after it, of 6" in v.why


TIMEOUT = "ERROR: [youtube:search] x: Unable to download API page: _ssl.c:983: The handshake operation timed out"


def test_a_session_the_network_failed_says_its_error_and_no_block():
    report = session("2026-11-28", "wifi", "observe")
    report["runs"] = report["runs"][:1]
    report["runs"][0].update(outcome="error", reason=TIMEOUT)
    report["budget"].update(before=0, after=1)
    verdicts = gate([report])
    w = verdicts["Y0-W"]
    assert w.passed is None
    assert "lost to the network" in w.why and TIMEOUT in w.why
    assert w.numbers["lost"] == [yg._label(report)]
    assert w.numbers["wifi"][0]["blocked"] == 0
    assert verdicts["Y0-B"].passed is True and verdicts["Y0-B"].numbers["blocked_runs"] == 0
    assert verdicts["terms"].passed is True



# -- the phone's reports of 2026-11-27, their shape --------------------------------------------------------------------


def phone_session(at: str, transport: str, songs: int) -> dict:
    """A session shaped as the owner's phone wrote them on 2026-11-27: enforced, the bench before ``lifted`` and
    ``uid_counts``, ``songs`` songs (search and download each), the uid's bytes about 3.1 x the gate's (TrafficStats
    counts the loopback legs too: the phone's numbers)."""
    report = json.loads(json.dumps(session("2026-11-27", transport, "enforce")).replace("2026-11-27T18:0", f"{at}"))
    report["budget"] = {"before": 0, "after": 2 * songs, "of": 6}
    del report["uid_counts"]
    report["runs"] = report["runs"][:2 * songs]
    for run in report["runs"]:
        g = sum(u["bytes_up"] + u["bytes_down"] for u in run["hosts"].values())
        run["uid_bytes"] = round(g * (3.11 if run["kind"] == "search" else 3.08))
    return report


def wifi_lost(at: str = "2026-11-27T14:5") -> dict:
    """The Wi-Fi session the network lost: its one search's TLS handshake timed out, nothing else ran."""
    report = phone_session(at, "wifi", 1)
    report["runs"] = report["runs"][:1]
    report["runs"][0].update(outcome="error", reason=TIMEOUT, uid_bytes=14_041,
                             hosts={"www.youtube.com": {"connects": 1, "bytes_up": 2_000, "bytes_down": 1_074,
                                                        "refused": 0, "apart": False}})
    return report


def the_phones_day() -> list[dict]:
    return [wifi_lost(), phone_session("2026-11-27T15:1", "cellular", 1),
            phone_session("2026-11-27T15:3", "cellular", 1)]


def test_the_phones_day_is_undecided_saying_one_more_song_and_a_warm_download():
    verdicts = gate(the_phones_day(), apk_growth_mb=0)
    said = {n: v.passed for n, v in verdicts.items()}
    assert said["terms"] is True, verdicts["terms"].why
    assert said["Y0-H"] is True, verdicts["Y0-H"].why
    assert said["sessions"] is True
    w, t = verdicts["Y0-W"], verdicts["Y0-T"]
    assert w.passed is None and "2 of 3 songs downloaded on mobile data with Start" in w.why and "1 more" in w.why
    assert "lost to the network" in w.why
    assert t.passed is None and "run two or three songs in one session" in t.why
    assert whole(verdicts) is None


def test_a_session_lost_to_the_network_counts_for_nothing_either_way():
    alone = gate([wifi_lost()])
    assert alone["Y0-W"].passed is None and "lost to the network" in alone["Y0-W"].why
    assert alone["sessions"].passed is None
    two = gate([wifi_lost("2026-11-27T14:5"), wifi_lost("2026-11-29T14:5"),
                phone_session("2026-11-28T15:1", "cellular", 3)])
    assert two["Y0-W"].passed is True, two["Y0-W"].why
    assert len(two["Y0-W"].numbers["lost"]) == 2
    # Two lost Wi-Fi days are no two failing days: no §3.8.
    assert "§3.8" not in two["Y0-W"].why


def test_the_uids_bytes_are_explained_by_the_gates_three_legs_and_a_leak_past_them_fails():
    mobile = phone_session("2026-11-27T15:1", "cellular", 3)
    assert gate([mobile])["Y0-H"].passed is True
    download = run_of(mobile, 0, "download")
    g = sum(u["bytes_up"] + u["bytes_down"] for u in download["hosts"].values())
    # A bypass: bytes yt-dlp sent the network outside the gate, counted once, a fifth of the gate's on top.
    download["uid_bytes"] = round(3.08 * g + 0.25 * g)
    v = gate([mobile])["Y0-H"]
    assert v.passed is False and "the uid's bytes past the gate's three legs" in v.why
    assert v.numbers["uid_counts"] == ["loopback too"]


def test_a_report_without_uid_counts_is_read_as_its_counter_was_loopback_too_and_another_unreadable(tmp_path):
    report = session()
    assert report["uid_counts"] == "loopback too"
    del report["uid_counts"]
    yg.check_shape(report)
    assert yg.uid_counts(report) == "loopback too"
    report["uid_counts"] = "the network alone"
    path = tmp_path / "r.json"
    path.write_text(json.dumps(report))
    with pytest.raises(ReportError, match="uid_counts"):
        read(path)


def test_a_capped_run_is_bound_by_every_run_of_its_second_even_a_lifted_one():
    capped_six = capped(session("2026-11-28", "cellular", "enforce"))
    for run in capped_six["runs"]:
        run["started_at"] = "2026-11-28T18:00:05Z"
    capped_six["started_at"] = "2026-11-28T18:00:00Z"
    other = session("2026-11-28", "wifi", "observe")
    other["started_at"] = "2026-11-28T17:00:00Z"
    other["runs"] = other["runs"][:1]
    other["runs"][0]["started_at"] = "2026-11-28T18:00:05Z"
    v = gate([capped_six, other])["terms"]
    assert v.passed is False and "7 runs within 24 hours" in v.why
