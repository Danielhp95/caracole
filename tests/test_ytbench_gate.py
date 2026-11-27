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
    assert set(report) == set(yg.REPORT_MEMBERS)
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
    assert "2 session(s) on 2 UTC day(s)" in verdicts["Y0-W"].why


def test_without_the_apks_growth_size_and_so_the_whole_gate_are_undecided():
    verdicts = gate(pair())
    assert verdicts["Y0-S"].passed is None and "--apk-growth-mb" in verdicts["Y0-S"].why
    assert whole(verdicts) is None


# -- each gate: pass, fail, undecided -----------------------------------------------------------------------------


def test_works_fails_on_a_wifi_block_and_says_run_again_another_day():
    wifi, mobile = pair()
    run_of(wifi, 2, "download")["outcome"] = "blocked"
    v = gate([wifi, mobile])["Y0-W"]
    assert v.passed is False and "run again another day" in v.why


def test_works_on_two_failing_wifi_days_names_the_fallbacks_trigger():
    one = session("2026-11-28", "wifi", "observe")
    two = session("2026-11-30", "wifi", "observe")
    for r in (one, two):
        run_of(r, 2, "download")["outcome"] = "error"
        run_of(r, 1, "download")["outcome"] = "error"
    v = gate([one, two])["Y0-W"]
    assert v.passed is False and "§3.8's trigger (Y0.7)" in v.why


def test_works_is_undecided_with_fewer_than_three_songs_or_no_wifi_session():
    wifi, mobile = pair()
    wifi["runs"] = wifi["runs"][:4]
    assert gate([wifi, mobile])["Y0-W"].passed is None
    assert gate([mobile])["Y0-W"].passed is None


def test_mobile_data_failing_is_no_stop_the_route_is_wifi_only():
    wifi, mobile = pair()
    for song in (1, 2):
        run_of(mobile, song, "download")["outcome"] = "error"
    v = gate([wifi, mobile])["Y0-W"]
    assert v.passed is True and "the route is Wi-Fi only" in v.why
    assert v.numbers["mobile"][0]["ok"] == 1


def test_works_passes_with_a_song_unavailable_and_two_decoded():
    wifi, mobile = pair()
    d = run_of(wifi, 2, "download")
    d.update(outcome="unavailable", file=None, decoded=None)
    assert gate([wifi, mobile])["Y0-W"].passed is True


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


@pytest.mark.parametrize(("youtube", "passed"), [(400.0, True), (600.0, None), (900.0, False)])
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


def test_more_than_six_runs_in_any_24_hours_across_the_reports_fails_the_terms():
    one = session("2026-11-28", "wifi", "observe")
    two = session("2026-11-28", "cellular", "enforce")
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


@pytest.mark.parametrize(("transport", "mode", "words"), [
    ("cellular", "observe", "observed every host on mobile data"),
    ("wifi", "enforce", "enforced on Wi-Fi"),
])
def test_a_session_of_the_other_gate_mode_than_its_day_asks_fails_the_terms(transport, mode, words):
    v = gate([session("2026-11-28", transport, mode)])["terms"]
    assert v.passed is False and words in v.why


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

