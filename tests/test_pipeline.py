import logging
from datetime import UTC, datetime, timedelta

import httpx

from caracole.db import kv_get_json
from caracole.health import get_state, is_cooling, record_block
from caracole.http import BudgetExhausted, ProviderBlocked, ProviderError
from caracole.notify import Notifier
from caracole.pipeline import PROVIDERS, RunReport, Services, Step, run_pipeline

NOW = datetime(2026, 10, 18, 3, 30, tzinfo=UTC)


class FakeClient:
    def __init__(self, requests_made=0):
        self.requests_made = requests_made

    def close(self):
        pass


class Outbox:
    def __init__(self):
        self.sent = []

    def notifier(self):
        def handler(request):
            self.sent.append((request.headers.get("title"), request.content.decode()))
            return httpx.Response(200)

        return Notifier("https://ntfy.sh/t", None, transport=httpx.MockTransport(handler))


def services(outbox, **requests):
    """A client for every provider, as ``make_services`` makes them, each having made ``requests[p]``."""
    return Services(
        clients={p: FakeClient(requests.get(p, 0)) for p in PROVIDERS},
        spotify=None,
        notifier=outbox.notifier(),
    )


def step(name, provider=None, result="ok", calls=None):
    def run(ctx):
        if calls is not None:
            calls.append(name)
        if isinstance(result, BaseException):
            raise result
        return result

    return Step(name=name, provider=provider, run=run)


def test_runs_steps_in_order_and_reports(conn, cfg):
    calls, out = [], Outbox()
    steps = [step("sync", calls=calls, result="2 new songs"), step("match", calls=calls), step("todo", calls=calls)]
    report = run_pipeline(cfg, conn=conn, services=services(out), steps=steps, now=NOW)
    assert calls == ["sync", "match", "todo"]
    assert report.steps == {"sync": "2 new songs", "match": "ok", "todo": "ok"}
    assert report.ok and not report.errors
    assert out.sent and out.sent[-1][0] == "caracole run"
    assert "sync: 2 new songs" in out.sent[-1][1]
    last = kv_get_json(conn, "run:last")
    assert last["run_id"] == "2026-10-18T03:30:00Z" and last["steps"]["sync"] == "2 new songs"


def test_ug_block_cools_down_and_never_marks_not_found(conn, cfg):
    calls, out = [], Outbox()
    blocked = ProviderBlocked("ug", "https://tabs.ultimate-guitar.com/tab/1", 403, "HTTP 403")
    steps = [
        step("index", provider="ug", calls=calls),
        step("fetch", provider="ug", result=blocked, calls=calls),
        step("lacuerda", provider="lacuerda", calls=calls),
        step("todo", calls=calls),
    ]
    report = run_pipeline(cfg, conn=conn, services=services(out, ug=12), steps=steps, now=NOW)
    assert report.blocked == ["ug"]
    assert report.steps["fetch"].startswith("blocked")
    assert calls == ["index", "fetch", "lacuerda", "todo"]
    assert is_cooling(conn, "ug", NOW + timedelta(hours=23))
    assert report.ok  # a block is expected behaviour, not a failure
    titles = [t for t, _ in out.sent]
    assert titles.count("caracole: Ultimate Guitar blocked") == 1
    # The alert and the run's summary say it in the same words.
    [alert] = [body for t, body in out.sent if t == "caracole: Ultimate Guitar blocked"]
    assert alert == ("Ultimate Guitar blocked caracole (HTTP 403) during the fetch step, so caracole leaves it "
                     "alone until 2026-10-19 05:30 UTC. Nothing was marked not found.")
    assert alert in report.summary().splitlines()


def test_later_steps_of_a_blocked_provider_are_skipped(conn, cfg):
    calls, out = [], Outbox()
    blocked = ProviderBlocked("ug", "u", 429, "HTTP 429")
    steps = [step("index", provider="ug", result=blocked, calls=calls), step("fetch", provider="ug", calls=calls)]
    report = run_pipeline(cfg, conn=conn, services=services(out), steps=steps, now=NOW)
    assert calls == ["index"]
    assert report.steps["fetch"] == "skipped: ug blocked this run"


def test_cooling_provider_skipped_next_run(conn, cfg):
    record_block(conn, "ug", NOW - timedelta(hours=2), "HTTP 403")
    calls, out = [], Outbox()
    steps = [step("fetch", provider="ug", calls=calls), step("lyrics", provider="lrclib", calls=calls)]
    report = run_pipeline(cfg, conn=conn, services=services(out), steps=steps, now=NOW)
    assert calls == ["lyrics"]
    assert report.steps["fetch"].startswith("skipped: ug cooling down until 2026-10-19 03:30 UTC")


def test_successful_use_resets_cooldown_strikes(conn, cfg):
    record_block(conn, "ug", NOW - timedelta(days=3), "HTTP 403")
    out = Outbox()
    run_pipeline(cfg, conn=conn, services=services(out, ug=5), steps=[step("fetch", provider="ug")], now=NOW)
    assert get_state(conn, "ug").strikes == 0


def test_budget_and_provider_errors_are_not_failures(conn, cfg):
    out = Outbox()
    steps = [
        step("fetch", provider="ug", result=BudgetExhausted("ug")),
        step("lyrics", provider="lrclib", result=ProviderError("lrclib", "u", 502, "HTTP 502")),
        step("todo"),
    ]
    report = run_pipeline(cfg, conn=conn, services=services(out), steps=steps, now=NOW)
    assert report.ok
    assert report.steps["fetch"] == "budget spent (ug)"
    assert report.steps["lyrics"].startswith("error:")
    assert get_state(conn, "lrclib").last_error.endswith("HTTP 502")


def test_unexpected_error_marks_the_run_failed_but_later_steps_still_run(conn, cfg):
    calls, out = [], Outbox()
    steps = [step("match", result=RuntimeError("boom"), calls=calls), step("todo", calls=calls)]
    report = run_pipeline(cfg, conn=conn, services=services(out), steps=steps, now=NOW)
    assert calls == ["match", "todo"]
    assert not report.ok
    assert report.steps["match"] == "failed: RuntimeError: boom"
    assert any("boom" in e for e in report.errors)


def test_report_summary_mentions_requests(conn, cfg):
    out = Outbox()
    report = run_pipeline(cfg, conn=conn, services=services(out, ug=7, lrclib=3), steps=[step("todo")], now=NOW)
    assert report.requests == {"ug": 7, "lrclib": 3, "lacuerda": 0, "gtptabs": 0, "musescore": 0}
    assert ("Requests: Ultimate Guitar 7, LRCLIB 3, LaCuerda 0, gtptabs.com 0, MuseScore 0."
            in report.summary().splitlines())


def test_requests_are_counted_against_each_clients_budget(conn, cfg):
    from caracole.config import ProviderPolicy
    from caracole.http import PoliteClient

    lrclib = PoliteClient("lrclib", ProviderPolicy(budget=200, delay=(0.0, 0.0)), cfg.cache_dir,
                          user_agent="caracole-test", transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    svc = Services(clients={"lrclib": lrclib}, spotify=None, notifier=Outbox().notifier())
    report = run_pipeline(cfg, conn=conn, services=svc, steps=[step("todo")], now=NOW)
    assert report.budgets == {"lrclib": 200}
    assert "Requests: LRCLIB 0 of 200." in report.summary().splitlines()


def test_a_step_plugs_into_the_summary_by_returning_a_result(conn, cfg):
    # A new provider's step: what it did, and the songs an error left, in the run's words.
    from caracole.report import Failure, StepResult

    def gtptabs(ctx):
        return StepResult(title="GtpTabs", done=["2 sheets kept"], status="2 kept, 1 error",
                          failures=[Failure("gtptabs", "A – B", "didn't answer (HTTP 503)")])

    out = Outbox()
    report = run_pipeline(cfg, conn=conn, services=services(out), steps=[Step("gtptabs", gtptabs)], now=NOW)
    assert report.steps == {"gtptabs": "2 kept, 1 error"}
    lines = report.summary().splitlines()
    assert "GtpTabs: 2 sheets kept." in lines
    assert "gtptabs.com didn't answer (HTTP 503), so 1 song will be tried again on the next run." in lines
    assert out.sent[-1] == ("caracole run", report.summary())  # ntfy gets the same words


def test_a_step_that_returns_a_line_of_text_still_shows_it(conn, cfg):
    out = Outbox()
    report = run_pipeline(cfg, conn=conn, services=services(out), steps=[step("gtptabs", result="2 kept")],
                          now=NOW)
    assert report.steps == {"gtptabs": "2 kept"}
    assert "gtptabs: 2 kept." in report.summary().splitlines()


def test_a_cooldown_that_skips_two_steps_is_said_once(conn, cfg):
    record_block(conn, "ug", NOW - timedelta(hours=2), "HTTP 403")
    steps = [step("index", provider="ug"), step("fetch", provider="ug")]
    report = run_pipeline(cfg, conn=conn, services=services(Outbox()), steps=steps, now=NOW)
    said = [line for line in report.summary().splitlines() if "cooling down" in line]
    assert said == ["Ultimate Guitar is cooling down after a block until 2026-10-19 03:30 UTC, so caracole "
                    "leaves it alone this run."]


def test_the_run_is_timed_on_its_own_clock(conn, cfg, monkeypatch):
    import caracole.pipeline as pipeline

    readings = iter([100.0])
    monkeypatch.setattr(pipeline, "clock", lambda: next(readings, 225.0))
    report = run_pipeline(cfg, conn=conn, services=services(Outbox()), steps=[step("todo")], now=NOW)
    assert report.seconds == 125.0
    assert report.summary().splitlines()[-1] == "Took 2 min 5 s."


def test_a_bug_is_logged_with_its_traceback_behind_one_line(conn, cfg, caplog):
    out = Outbox()
    steps = [step("match", result=RuntimeError("boom")), step("todo")]
    with caplog.at_level(logging.ERROR, logger="caracole.pipeline"):
        report = run_pipeline(cfg, conn=conn, services=services(out), steps=steps, now=NOW)
    [record] = caplog.records
    assert record.getMessage().startswith("The match step failed: RuntimeError: boom.")
    assert "\n" not in record.getMessage() and record.exc_info is not None  # the traceback follows it
    assert ("The match step failed: RuntimeError: boom. That's a bug in caracole: its traceback is in the log, "
            "and the run exits 1.") in report.summary().splitlines()
    assert out.sent[-1][0] == "caracole run failed"


def test_default_steps_are_in_plan_order():
    # gtptabs after the scan: a Guitar Pro file you dropped into _inbox/ is filed first, and the
    # song then gets no second one.
    from caracole.pipeline import default_steps

    assert [s.name for s in default_steps()] == [
        "sync", "icons", "index", "match", "lyrics", "fetch", "lacuerda", "scan", "gtptabs", "musescore", "youtube",
        "render", "todo",
    ]
    providers = {s.name: s.provider for s in default_steps()}
    assert providers["fetch"] == "ug" and providers["gtptabs"] == "gtptabs" and providers["musescore"] == "musescore"


def gtptabs_context(conn, cfg, client=None, overrides=None):
    from caracole.overrides import Overrides
    from caracole.pipeline import StepContext

    svc = Services(clients={"gtptabs": client or FakeClient()}, spotify=None, notifier=Outbox().notifier())
    return StepContext(cfg=cfg, conn=conn, overrides=overrides or Overrides(), now=NOW, run_id="r", services=svc,
                       report=RunReport(run_id="r", started="r"))


def test_default_gtptabs_step_passes_overrides_and_reports_errors(conn, cfg, monkeypatch):
    import caracole.gtptabs_fetch as gf
    from caracole.overrides import Overrides
    from caracole.pipeline import _gtptabs

    seen = {}

    def fake(conn_, client, library_dir, now, *, overrides=None):
        seen.update(overrides=overrides, library_dir=library_dir)
        return gf.GtpTabsStats(sitemaps=2, tried=3, kept=1, missing=1, errors=1)

    monkeypatch.setattr(gf, "gtptabs_files", fake)
    o = Overrides(ignore=frozenset({"blur/song-2"}))
    result = _gtptabs(gtptabs_context(conn, cfg, overrides=o))
    assert seen == {"overrides": o, "library_dir": cfg.library_dir}
    assert result.status == "2 sitemaps indexed, 3 tried, 1 Guitar Pro file kept, 1 not on gtptabs.com, 1 error"
    assert result.title == "gtptabs.com" and result.done == ["1 Guitar Pro file downloaded", "1 song not there"]
    assert [p.text for p in result.problems] == [
        "gtptabs.com failed 1 time this run; those songs are tried again on the next run, and the log says why."]
    assert get_state(conn, "gtptabs").last_error == "1 error this run"


def test_the_gtptabs_step_says_when_its_budget_is_spent(conn, cfg, monkeypatch):
    import caracole.gtptabs_fetch as gf
    from caracole.pipeline import _gtptabs

    monkeypatch.setattr(gf, "gtptabs_files", lambda *a, **k: gf.GtpTabsStats(tried=2, kept=2, budget_exhausted=True))
    result = _gtptabs(gtptabs_context(conn, cfg))
    assert result.status == "2 tried, 2 Guitar Pro files kept, 0 not on gtptabs.com, 0 errors (budget spent)"
    assert result.done == ["2 Guitar Pro files downloaded"] and result.spent == ["gtptabs"]


def test_a_new_sites_steps_say_what_they_did_in_the_runs_summary(conn, cfg, monkeypatch):
    import caracole.gtptabs_fetch as gf
    import caracole.musescore_fetch as mf
    from caracole.pipeline import default_steps

    monkeypatch.setattr(gf, "gtptabs_files", lambda *a, **k: gf.GtpTabsStats(tried=3, kept=2, missing=1))
    monkeypatch.setattr(mf, "musescore_index", lambda *a, **k: mf.MuseScoreStats(sitemaps=2))
    steps = [s for s in default_steps() if s.name in ("gtptabs", "musescore")]
    lines = run_pipeline(cfg, conn=conn, services=services(Outbox()), steps=steps, now=NOW).summary().splitlines()
    assert "gtptabs.com: 2 Guitar Pro files downloaded, 1 song not there." in lines
    assert "MuseScore: 2 song sitemaps read." in lines


def test_a_new_sites_steps_say_nothing_when_they_did_nothing(conn, cfg, monkeypatch):
    import caracole.gtptabs_fetch as gf
    import caracole.musescore_fetch as mf
    from caracole.pipeline import default_steps

    monkeypatch.setattr(gf, "gtptabs_files", lambda *a, **k: gf.GtpTabsStats())
    monkeypatch.setattr(mf, "musescore_index", lambda *a, **k: mf.MuseScoreStats())
    steps = [s for s in default_steps() if s.name in ("gtptabs", "musescore")]
    summary = run_pipeline(cfg, conn=conn, services=services(Outbox()), steps=steps, now=NOW).summary()
    assert "gtptabs.com:" not in summary and "MuseScore:" not in summary


def test_gtptabs_turned_off_is_skipped_and_gets_no_client(conn, cfg, tmp_path):
    import dataclasses

    from caracole.config import ProviderPolicy
    from caracole.pipeline import default_steps, make_services

    off = dataclasses.replace(cfg, providers={**cfg.providers, "gtptabs": ProviderPolicy(20, (10.0, 20.0), False)})
    made = make_services(off, conn, "2026-10-19T03:30:00Z")
    try:
        assert set(made.clients) == {"ug", "lrclib", "lacuerda", "musescore"}
    finally:
        made.close()
    steps = [s for s in default_steps() if s.name == "gtptabs"]
    report = run_pipeline(off, conn=conn, services=services(Outbox()), steps=steps, now=NOW)
    assert report.ok and report.steps["gtptabs"] == "skipped: gtptabs is off ([providers.gtptabs] enabled = false)"


def test_the_run_makes_a_client_for_every_provider_turned_on(conn, cfg):
    from caracole.pipeline import make_services

    made = make_services(cfg, conn, "2026-10-19T03:30:00Z")
    try:
        assert set(made.clients) == {"ug", "lrclib", "lacuerda", "gtptabs", "musescore"}
    finally:
        made.close()


def test_a_gtptabs_block_cools_it_down_and_marks_no_song(conn, cfg, tmp_path):
    from conftest import add_song
    from helpers.gtptabs_site import HTML, FakeGtpTabs

    from caracole.pipeline import default_steps

    song = add_song(conn, "Blur", "Beetlebum")
    site = FakeGtpTabs(pages={"https://gtptabs.com/sitemapGoogle.xml": (403, "Forbidden", HTML)})
    client = site.client(cfg.cache_dir, now=NOW)
    svc = Services(clients={"gtptabs": client}, spotify=None, notifier=Outbox().notifier())
    steps = [s for s in default_steps() if s.name == "gtptabs"]
    report = run_pipeline(cfg, conn=conn, services=svc, steps=steps, now=NOW)
    assert report.ok and report.blocked == ["gtptabs"]
    assert report.steps["gtptabs"].startswith("blocked")
    assert is_cooling(conn, "gtptabs", NOW + timedelta(hours=25))
    assert kv_get_json(conn, f"gtptabs:checked:{song.id}") is None


def musescore_run(conn, cfg, site, *, budget=10, now=NOW, config=None):
    """One run of the musescore step alone, against a fake MuseScore."""
    from caracole.pipeline import default_steps

    client = site.client(cfg.cache_dir, budget=budget, now=now)
    svc = Services(clients={"musescore": client}, spotify=None, notifier=Outbox().notifier())
    steps = [s for s in default_steps() if s.name == "musescore"]
    return run_pipeline(config or cfg, conn=conn, services=svc, steps=steps, now=now)


def test_the_musescore_step_says_what_it_read_and_what_the_index_holds(conn, cfg):
    from conftest import add_song
    from helpers.musescore_site import FakeMuseScore

    add_song(conn, "Oasis", "Wonderwall")
    site = FakeMuseScore()
    report = musescore_run(conn, cfg, site)
    assert report.ok and report.steps["musescore"] == "2 sitemaps indexed, 19 song pages in the index"
    again = musescore_run(conn, cfg, site, now=NOW + timedelta(days=1))
    assert again.steps["musescore"] == "19 song pages in the index"


def test_the_musescore_step_says_when_its_budget_is_spent(conn, cfg):
    from conftest import add_song
    from helpers.musescore_site import FakeMuseScore

    add_song(conn, "Oasis", "Wonderwall")
    report = musescore_run(conn, cfg, FakeMuseScore(), budget=2)
    assert report.ok and report.steps["musescore"] == "1 sitemap indexed, 12 song pages in the index (budget spent)"


def test_musescore_errors_reach_provider_health_and_are_no_failure(conn, cfg):
    from conftest import add_song
    from helpers.musescore_site import INDEX, FakeMuseScore

    add_song(conn, "Oasis", "Wonderwall")
    site = FakeMuseScore(pages={INDEX: (502, "Bad gateway", {"Content-Type": "text/html"})})
    report = musescore_run(conn, cfg, site)
    assert report.ok and report.steps["musescore"] == "0 song pages in the index, 1 error"
    assert get_state(conn, "musescore").last_error == "1 error this run"


def test_a_musescore_challenge_cools_it_down_and_keeps_the_index(conn, cfg):
    # What Cloudflare answers caracole: a block like any other, with one ntfy message.
    from conftest import add_song
    from helpers.musescore_site import INDEX, FakeMuseScore, challenge

    add_song(conn, "Oasis", "Wonderwall")
    site = FakeMuseScore()
    musescore_run(conn, cfg, site)
    site.pages[INDEX] = challenge()
    report = musescore_run(conn, cfg, site, now=NOW + timedelta(days=31))
    assert report.ok and report.blocked == ["musescore"]
    assert report.steps["musescore"].startswith("blocked")
    assert is_cooling(conn, "musescore", NOW + timedelta(days=31, hours=25))
    assert conn.execute("SELECT COUNT(*) FROM musescore_index").fetchone()[0] == 19


def test_musescore_turned_off_is_skipped(conn, cfg):
    import dataclasses

    from helpers.musescore_site import FakeMuseScore

    from caracole.config import ProviderPolicy

    off = dataclasses.replace(cfg, providers={**cfg.providers, "musescore": ProviderPolicy(10, (10.0, 20.0), False)})
    site = FakeMuseScore()
    report = musescore_run(conn, cfg, site, config=off)
    assert report.steps["musescore"] == "skipped: musescore is off ([providers.musescore] enabled = false)"
    assert site.requests == []


def test_unreadable_overrides_stop_the_run_with_an_alert(conn, cfg):
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text("[pins]\n", encoding="utf-8")
    calls, out = [], Outbox()
    report = run_pipeline(cfg, conn=conn, services=services(out), steps=[step("todo", calls=calls)], now=NOW)
    assert not report.ok and calls == []
    assert out.sent[-1][0] == "caracole run failed" and "pins" in out.sent[-1][1]


def test_unreadable_overrides_still_rewrite_the_todo_page_with_the_error_first(conn, cfg):
    # Two [artist_url] blocks pasted one after the other, as the page used to show them.
    from caracole.pipeline import default_steps

    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text(
        '[artist_url]\n"Joaquín Sabina" = "https://www.ultimate-guitar.com/artist/joaquin_sabina_1"\n\n'
        '[artist_url]\n"宋冬野" = "https://www.ultimate-guitar.com/artist/song_dongye_2"\n', encoding="utf-8")
    (cfg.library_dir / "_todo.md").write_text("# caracole to-do\n\n_Updated 2026-10-17 03:30 UTC_\n", encoding="utf-8")
    report = run_pipeline(cfg, conn=conn, services=services(Outbox()), steps=default_steps(), now=NOW)
    assert not report.ok and list(report.steps) == ["overrides"]
    page = todo_page(cfg)
    assert "_Updated 2026-10-18 03:30 UTC" in page
    setup = page.split("\n## ", 1)[1].split("\n## ", 1)[0]
    assert setup.startswith("Setup problems") and "Cannot declare ('artist_url',) twice" in setup


def test_an_overrides_file_that_isnt_utf8_stops_the_run_like_any_unreadable_one(conn, cfg):
    # Saved as Latin-1, it used to raise UnicodeDecodeError out of the run: no page, no alert.
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_bytes('[ignore]\nsongs = ["Maná - Rayando el Sol"]\n'.encode("latin-1"))
    calls, out = [], Outbox()
    report = run_pipeline(cfg, conn=conn, services=services(out), steps=[step("todo", calls=calls)], now=NOW)
    assert not report.ok and calls == [] and list(report.steps) == ["overrides"]
    assert out.sent[-1][0] == "caracole run failed" and "line 2 is not valid UTF-8" in out.sent[-1][1]
    setup = todo_page(cfg).split("\n## ", 1)[1].split("\n## ", 1)[0]
    assert setup.startswith("Setup problems") and "line 2 is not valid UTF-8 (save the file as UTF-8)" in setup


def test_run_command_exit_codes(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    import caracole.pipeline as pipeline
    from caracole.cli import build_app

    cfgfile = tmp_path / "caracole.toml"
    cfgfile.write_text(f'state_dir = "{tmp_path / "state"}"\ncache_dir = "{tmp_path / "cache"}"\n'
                       f'library_dir = "{tmp_path / "lib"}"\n', encoding="utf-8")
    from caracole.report import Problem, StepResult, bug

    blocked = Problem("Ultimate Guitar blocked caracole (HTTP 429) during the fetch step, …")
    results = iter([
        RunReport(run_id="r", started="r", steps={"fetch": "blocked: ug: 429"}, blocked=["ug"],
                  results={"fetch": StepResult(problems=[blocked])}),
        RunReport(run_id="r", started="r", steps={"lyrics": "budget spent (lrclib)"},
                  results={"lyrics": StepResult(spent=["lrclib"])}),
        RunReport(run_id="r", started="r", steps={"match": "failed: RuntimeError: boom"}, errors=["match: boom"],
                  results={"match": StepResult(problems=[bug(RuntimeError("boom"), "match")])}),
    ])
    monkeypatch.setattr(pipeline, "run_pipeline", lambda cfg, **kw: next(results))
    block = CliRunner().invoke(build_app(), ["--config", str(cfgfile), "run"])
    assert block.exit_code == 0 and blocked.text in block.stdout  # a block is no failure
    spent = CliRunner().invoke(build_app(), ["--config", str(cfgfile), "run"])
    assert spent.exit_code == 0  # nor is a spent budget
    bad = CliRunner().invoke(build_app(), ["--config", str(cfgfile), "run"])
    assert bad.exit_code == 1 and "The match step failed: RuntimeError: boom." in bad.stdout  # a bug is


def test_a_run_re_keys_the_songs_before_the_sync_reads_wanted_txt(conn, cfg):
    # After an upgrade that changed a line's key, the sync must find its first-seen time under
    # the new key; read under none, it would be the run's, and the song would jump the queue.
    import json

    from caracole.db import kv_delete, kv_set
    from caracole.pipeline import default_steps
    from caracole.songs import KEY_VERSION_KV, list_songs
    from caracole.wanted import FIRST_SEEN_KEY

    old_key, september = "soda-stereo/persiana-americana-en-vivo", "2026-09-01T00:00:00Z"
    conn.execute(
        "INSERT INTO songs (key, artist, title, artists, source_ids, added_at, created_at, "
        "updated_at) VALUES (?, 'Soda Stereo', 'Persiana Americana - En Vivo', ?, ?, ?, ?, ?)",
        (old_key, json.dumps(["Soda Stereo"]), json.dumps({"wanted": [old_key]}), september,
         september, september),
    )
    kv_set(conn, FIRST_SEEN_KEY + old_key, september)
    kv_delete(conn, KEY_VERSION_KV)
    cfg.wanted_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.wanted_file.write_text("Soda Stereo - Persiana Americana - En Vivo\n", encoding="utf-8")
    sync = [s for s in default_steps() if s.name == "sync"]

    run_pipeline(cfg, conn=conn, services=services(Outbox()), steps=sync, now=NOW)

    [song] = list_songs(conn)
    assert (song.key, song.added_at) == ("soda-stereo/persiana-americana", september)


# --- one caracole at a time ---------------------------------------------------------------


def lock_is_free(cfg) -> bool:
    """Whether another process could take caracole's lock now."""
    import fcntl
    import os

    path = cfg.state_dir / "caracole.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        os.close(fd)
    return True


def test_the_runs_clients_keep_the_pause_after_another_caracoles_last_request(conn, cfg, monkeypatch):
    # A `caracole-admin fetch` asked UG 3 s ago: the run's first UG request waits out UG's pause.
    from caracole.commands import _common
    from caracole.pipeline import make_services

    slept = []
    monkeypatch.setattr(_common, "sleep", slept.append)
    at = (datetime.now(UTC) - timedelta(seconds=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO events (run, at, provider, url, status, decision) VALUES (?, ?, ?, ?, ?, ?)",
        ("earlier", at, "ug", "https://tabs.ultimate-guitar.com/tab/1", 200, "ok"),
    )
    made = make_services(cfg, conn, "2026-10-18T03:30:00Z")
    for client in made.clients.values():
        client.close()
    [pause] = slept
    low, high = cfg.provider("ug").delay
    assert low - 4 <= pause <= high - 3


def test_a_run_lets_go_of_the_lock_its_clients_held(conn, cfg):
    # Its own clients hold caracole's lock; once the run is over, another caracole may go on.
    report = run_pipeline(cfg, conn=conn, steps=[step("todo")], now=NOW)
    assert report.ok
    assert lock_is_free(cfg)


def test_default_match_step_skips_while_the_index_is_empty(conn, cfg):
    from caracole.pipeline import _match, StepContext
    from caracole.overrides import Overrides
    from conftest import add_song

    add_song(conn, "Radiohead", "Creep")
    out = Outbox()
    ctx = StepContext(cfg=cfg, conn=conn, overrides=Overrides(), now=NOW, run_id="r", services=services(out),
                      report=RunReport(run_id="r", started="r"))
    assert _match(ctx).status.startswith("skipped: the index is empty")
    assert conn.execute("SELECT match_decision FROM songs").fetchone()[0] is None


def test_default_match_step_waits_for_an_index_a_build_left_half_done(conn, cfg):
    # A build stopped part-way (a block, the budget, Ctrl-C) indexed one sitemap: Radiohead's tabs are in
    # one it never read. Creep must not become not_found, and the stored decision stays as it is.
    from conftest import add_song

    from caracole.overrides import Overrides
    from caracole.pipeline import StepContext, _match
    from caracole.songs import get_song, update_song
    from caracole.ug.index import upsert_rows

    upsert_rows(conn, [(1001, "oasis", "wonderwall", "chords", "oasis/wonderwall-chords-1001")], "1", NOW)
    creep = add_song(conn, "Radiohead", "Creep")
    wall = add_song(conn, "Oasis", "Wonderwall")
    update_song(conn, wall.id, match_decision="accept", match_step="exact", match_artist_key="oasis",
                match_song_key="wonderwall", match_score=100.0)
    ctx = StepContext(cfg=cfg, conn=conn, overrides=Overrides(), now=NOW, run_id="r", services=services(Outbox()),
                      report=RunReport(run_id="r", started="r"))
    summary = _match(ctx).status
    assert get_song(conn, creep.id).match_decision is None, summary
    assert summary.startswith("skipped: the index is incomplete")
    assert get_song(conn, wall.id).match_decision == "accept"


def keep_sheet_before_lyrics(conn, cfg, song, content):
    """A UG sheet kept while the song's lyrics were pending: sheet.txt and sheet.json, no coverage."""
    import json

    from caracole.library import keep_file
    from caracole.ug.page import strip_markup
    from caracole.versions import upsert_version

    url = "https://tabs.ultimate-guitar.com/tab/soda-stereo/persiana-americana-chords-101"
    vid = upsert_version(conn, provider="ug", tab_id="101", song_id=song.id, slot="sheet", kind="chords",
                         rating=4.5, votes=20, version=1, label=None, url=url, raw={"id": 101},
                         now="2026-10-01T00:00:00Z")
    files = {"sheet.txt": strip_markup(content), "sheet.json": json.dumps({"content": content, "url": url})}
    for name, text in files.items():
        keep_file(conn, cfg.library_dir, song=song, version_id=vid, name=name, data=text.encode(), rank=1)
    return vid


def test_default_fetch_step_scores_sheets_kept_before_their_lyrics(conn, cfg):
    # The lyrics step has since found the song's lyrics: the sheet covers half of them.
    from conftest import add_song

    from caracole.lyrics import Lyrics
    from caracole.pipeline import default_steps
    from caracole.songs import update_song
    from caracole.versions import get_version

    song = add_song(conn, "Soda Stereo", "Persiana Americana")
    content = "[Verso]\n[ch]Am[/ch]      [ch]F[/ch]\nwalking down the river road tonight\n"
    vid = keep_sheet_before_lyrics(conn, cfg, song, content)
    plain = "walking down the river road tonight\ncounting every lantern on the shore\n"
    lyrics = Lyrics(plain=plain, synced=None, instrumental=False, duration=None, lrclib_id=1)
    update_song(conn, song.id, status="found", lyrics_status="found", lyrics_json=lyrics.to_json())
    out = Outbox()
    steps = [s for s in default_steps() if s.name in ("fetch", "todo")]

    report = run_pipeline(cfg, conn=conn, services=services(out), steps=steps, now=NOW)

    assert report.steps["fetch"] == "0 songs done, 0 failed, 1 kept sheet rescored"
    assert get_version(conn, vid).coverage == 0.5
    todo = (cfg.library_dir / "_todo.md").read_text(encoding="utf-8")
    assert "**Soda Stereo - Persiana Americana**: 50% of the lyrics" in todo


def test_default_lacuerda_step_passes_overrides_and_reports_errors(conn, cfg, monkeypatch):
    import caracole.lacuerda_fetch as lf
    from caracole.overrides import Overrides
    from caracole.pipeline import StepContext, _lacuerda

    seen = {}

    def fake(conn_, client, library_dir, rank, now, *, overrides=None):
        seen["overrides"] = overrides
        return lf.LaCuerdaStats(tried=2, kept=1, missing=0, errors=1, budget_exhausted=False)

    monkeypatch.setattr(lf, "lacuerda_sheets", fake)
    o = Overrides(block=frozenset({1}))
    out = Outbox()
    ctx = StepContext(cfg=cfg, conn=conn, overrides=o, now=NOW, run_id="r", services=services(out),
                      report=RunReport(run_id="r", started="r"))
    summary = _lacuerda(ctx).status
    assert seen["overrides"] is o
    assert "1 error" in summary
    assert get_state(conn, "lacuerda").last_error is not None


def test_default_scan_step_says_how_many_links_the_inbox_refused(conn, cfg, tmp_path):
    # As `caracole scan` does: a link in place of _inbox/, or in it, is never read, and the run says so.
    from caracole.overrides import Overrides
    from caracole.pipeline import StepContext, _scan

    ctx = StepContext(cfg=cfg, conn=conn, overrides=Overrides(), now=NOW, run_id="r", services=services(Outbox()),
                      report=RunReport(run_id="r", started="r"))
    assert _scan(ctx).status == "0 purchases linked, 0 Guitar Pro files filed"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "Soda Stereo - Signos.gp5").write_bytes(b"GP")
    cfg.library_dir.mkdir(parents=True)
    (cfg.library_dir / "_inbox").symlink_to(elsewhere)
    assert _scan(ctx).status == "0 purchases linked, 0 Guitar Pro files filed, 1 symbolic link refused"
    (cfg.library_dir / "_inbox").unlink()
    (cfg.library_dir / "_inbox").mkdir()
    for name in ("a.gp5", "b.gp5"):
        (cfg.library_dir / "_inbox" / name).symlink_to(elsewhere / "Soda Stereo - Signos.gp5")
    assert _scan(ctx).status == "0 purchases linked, 0 Guitar Pro files filed, 2 symbolic links refused"


def test_fetch_summary_counts_settled_sheets(conn, cfg, monkeypatch):
    import caracole.ug.fetch as fetch
    from caracole.overrides import Overrides
    from caracole.pipeline import StepContext, _fetch

    monkeypatch.setattr(fetch, "songs_to_fetch", lambda *a, **k: [])
    monkeypatch.setattr(fetch, "rescore_kept_sheets", lambda *a, **k: 0)
    monkeypatch.setattr(fetch, "fetch_songs", lambda *a, **k: fetch.FetchStats(
        songs_done=1, songs_failed=0, budget_exhausted=True, sheets_done=2))
    ctx = StepContext(cfg=cfg, conn=conn, overrides=Overrides(), now=NOW, run_id="r", services=services(Outbox()),
                      report=RunReport(run_id="r", started="r"))
    result = _fetch(ctx)
    assert result.status == "2 sheets settled, 1 song done, 0 failed (budget spent)"
    assert (result.title, result.done, result.spent) == ("Ultimate Guitar", ["2 sheets settled", "1 song done"],
                                                         ["ug"])


def test_the_default_steps_say_in_the_summary_what_they_did_and_leave_out_the_zeros(conn, cfg):
    from conftest import add_song

    from caracole.pipeline import default_steps

    cfg.library_dir.mkdir(parents=True, exist_ok=True)
    cfg.wanted_file.write_text("Soda Stereo - Persiana Americana\n", encoding="utf-8")
    add_song(conn, "Radiohead", "Creep")
    steps = [s for s in default_steps() if s.name in ("sync", "index", "match", "scan", "render", "todo")]
    report = run_pipeline(cfg, conn=conn, services=services(Outbox()), steps=steps, now=NOW)
    lines = report.summary().splitlines()
    assert lines[:2] == ["First, build the index once: caracole index build (about 10 minutes).",
                         "Until then, no song is matched or looked for on Ultimate Guitar."]
    assert "Songs: 1 in wanted.txt, 1 new." in lines
    assert not [line for line in lines if " 0 " in line or line.startswith(("Matching", "PDFs", "Music"))]
    assert sum("caracole index build" in line for line in lines) == 1  # said once, though two steps wait for it
    assert f"1 thing on your to-do page needs you: {cfg.library_dir / '_todo.md'}" in lines


def test_spotify_needing_you_is_said_in_the_summarys_words_and_alerted_once(conn, cfg, monkeypatch):
    import caracole.sources as sources
    from caracole.pipeline import default_steps

    monkeypatch.setattr(sources, "sync_sources", lambda *a, **k: sources.SourcesReport(
        wanted=sources.SyncStats(seen=2), spotify_state="auth_needed", spotify_message="The token was revoked."))
    out = Outbox()
    sync = [s for s in default_steps() if s.name == "sync"]
    report = run_pipeline(cfg, conn=conn, services=services(out), steps=sync, now=NOW)
    said = ("Authorize Spotify again: caracole auth spotify. The token was revoked. wanted.txt keeps working "
            "meanwhile.")
    assert ("caracole: Spotify needs you", said) in out.sent
    assert report.summary().splitlines()[0] == "First, authorize Spotify again: caracole auth spotify."


# --- provider health on the to-do page ------------------------------------------------------


def todo_page(cfg):
    return (cfg.library_dir / "_todo.md").read_text(encoding="utf-8")


def todo_step():
    from caracole.pipeline import default_steps

    return [s for s in default_steps() if s.name == "todo"]


def test_todo_page_counts_this_runs_requests_as_the_last_success(conn, cfg):
    # The page is written before the run ends; a first run must not say "never" after 80 good requests.
    run_pipeline(cfg, conn=conn, services=services(Outbox(), ug=60, lrclib=10, lacuerda=5, gtptabs=3, musescore=2),
                 steps=todo_step(), now=NOW)
    page = todo_page(cfg)
    assert "| ug | OK | 2026-10-18 03:30 UTC |  | 60 |" in page
    assert "| lrclib | OK | 2026-10-18 03:30 UTC |  | 10 |" in page
    assert "| gtptabs | OK | 2026-10-18 03:30 UTC |  | 3 |" in page
    assert "| musescore | OK | 2026-10-18 03:30 UTC |  | 2 |" in page
    rows = [line for line in page.split("## Provider health", 1)[1].splitlines() if line.startswith("| ")]
    # Every provider this run asked; YouTube, which needs auto-chords and its models, is off here, never used.
    assert [row for row in rows if "never" in row] == [next(row for row in rows if row.startswith("| youtube |"))]
    assert "| youtube | off: " in page


def health_row(cfg, provider):
    return next(line for line in todo_page(cfg).splitlines() if line.startswith(f"| {provider} |"))


def test_ug_fetch_errors_reach_provider_health_and_an_all_error_run_is_no_success(conn, cfg):
    # Every UG request answers 502, so the fetch fails every song: an error for the page, and no success.
    from conftest import add_song

    from caracole.config import ProviderPolicy
    from caracole.health import EventLog
    from caracole.http import PoliteClient
    from caracole.pipeline import default_steps
    from caracole.songs import update_song

    for n in range(5):
        conn.execute(
            "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) "
            "VALUES (?, 'radiohead', ?, 'chords', '1', 'x', ?)",
            (100 + n, f"song-{n}", f"radiohead/song-{n}-chords-{100 + n}"),
        )
        s = add_song(conn, "Radiohead", f"Song {n}")
        update_song(conn, s.id, match_decision="accept", match_step="exact", match_artist_key="radiohead",
                    match_song_key=f"song-{n}")
    ug = PoliteClient("ug", ProviderPolicy(budget=60, delay=(0.0, 0.0)), cfg.cache_dir, user_agent="caracole-test",
                      transport=httpx.MockTransport(lambda request: httpx.Response(502, text="bad gateway")),
                      sleep=lambda s: None, on_event=EventLog(conn, "2026-10-18T03:30:00Z"))
    svc = Services(clients={"ug": ug, "lrclib": FakeClient(), "lacuerda": FakeClient()}, spotify=None,
                   notifier=Outbox().notifier())
    steps = [s for s in default_steps() if s.name in ("fetch", "todo")]

    report = run_pipeline(cfg, conn=conn, services=svc, steps=steps, now=NOW)

    assert report.steps["fetch"] == "0 songs done, 5 failed"
    state = get_state(conn, "ug")
    assert state.last_error == "5 songs failed this run" and state.last_error_at == NOW
    assert state.last_ok is None
    row = health_row(cfg, "ug")
    assert row.startswith("| ug | errors | never | 5 songs failed this run (2026-10-18 03:30 UTC) |"), row


def test_a_run_with_some_good_answers_still_counts_as_a_success(conn, cfg):
    # One 502 among good answers: the provider works, and its error is shown beside the success.
    from caracole.health import EventLog
    from caracole.http import Event

    log = EventLog(conn, "2026-10-18T03:30:00Z")
    log(Event("ug", "https://tabs.ultimate-guitar.com/tab/1", 200, "ok"))
    log(Event("ug", "https://tabs.ultimate-guitar.com/tab/2", 502, "error", "HTTP 502"))
    steps = [step("fetch", provider="ug", result=ProviderError("ug", "u", 502, "HTTP 502")), *todo_step()]
    run_pipeline(cfg, conn=conn, services=services(Outbox(), ug=2), steps=steps, now=NOW)
    assert get_state(conn, "ug").last_ok == NOW
    row = health_row(cfg, "ug")
    assert row.startswith("| ug | OK | 2026-10-18 03:30 UTC | ug: 502: u: HTTP 502"), row


# --- the youtube step ---------------------------------------------------------------------------


def youtube_cfg(cfg, tmp_path, monkeypatch):
    """A caracole with auto-chords (its packages taken to be there), its model files and a fake yt-dlp."""
    from helpers.fake_ytdlp import route_on

    return route_on(cfg, tmp_path, monkeypatch)


def youtube_step():
    from caracole.pipeline import default_steps

    return [s for s in default_steps() if s.name == "youtube"]


def test_the_youtube_step_comes_after_the_sites_and_before_the_pdfs():
    from caracole.pipeline import default_steps

    names = [s.name for s in default_steps()]
    assert names.index("musescore") < names.index("youtube") < names.index("render")
    assert {s.name: s.provider for s in default_steps()}["youtube"] == "youtube"


def test_without_auto_chords_the_youtube_step_asks_nothing_and_gets_no_runner(conn, cfg, tmp_path, monkeypatch):
    # The default package has no torch: a download nothing can make chords of is no use.
    import dataclasses

    from helpers.fake_ytdlp import route_on

    import caracole.youtube_fetch as yf
    from caracole.pipeline import make_services

    plain, fake = route_on(cfg, tmp_path, monkeypatch)
    monkeypatch.setattr(yf, "autochords_missing", lambda: ["torch", "librosa", "beat_this"])
    plain = dataclasses.replace(plain, ytdlp_bin=fake.bin)
    made = make_services(plain, conn, "2026-10-19T03:30:00Z")
    try:
        assert "youtube" not in made.clients
    finally:
        made.close()
    report = run_pipeline(plain, conn=conn, services=services(Outbox()), steps=youtube_step(), now=NOW)
    assert report.ok and report.steps["youtube"].startswith("skipped: this caracole was built without auto-chords")
    assert fake.argvs() == [] and "YouTube" not in report.summary()


def test_with_auto_chords_the_run_makes_a_yt_dlp_runner_that_holds_the_lock(conn, cfg, tmp_path, monkeypatch):
    from caracole.commands import _common
    from caracole.pipeline import make_services

    ycfg, _ = youtube_cfg(cfg, tmp_path, monkeypatch)
    made = make_services(ycfg, conn, "2026-10-19T03:30:00Z")
    lock = ycfg.state_dir / _common.LOCK_NAME
    try:
        assert set(made.clients) == {"ug", "lrclib", "lacuerda", "gtptabs", "musescore", "youtube"}
        assert made.clients["youtube"].policy.budget == 6
        assert lock in _common._held
    finally:
        made.close()
    assert lock not in _common._held


def test_youtube_turned_off_is_skipped(conn, cfg, tmp_path, monkeypatch):
    import dataclasses

    from caracole.config import ProviderPolicy

    ycfg, fake = youtube_cfg(cfg, tmp_path, monkeypatch)
    off = dataclasses.replace(ycfg, providers={**ycfg.providers, "youtube": ProviderPolicy(6, (15.0, 30.0), False)})
    report = run_pipeline(off, conn=conn, services=services(Outbox()), steps=youtube_step(), now=NOW)
    assert report.steps["youtube"] == "skipped: youtube is off ([providers.youtube] enabled = false)"
    assert fake.argvs() == []


def youtube_run(conn, ycfg, fake, *, budget=6, notifier=None):
    from caracole.config import ProviderPolicy
    from caracole.health import EventLog
    from caracole.youtube import YtDlp

    yt = YtDlp(fake.bin, ProviderPolicy(budget, (0.0, 0.0)), ycfg.cache_dir, sleep=lambda s: None,
               on_event=EventLog(conn, "2026-10-18T03:30:00Z"))
    svc = Services(clients={"youtube": yt}, spotify=None, notifier=notifier or Outbox().notifier())
    return run_pipeline(ycfg, conn=conn, services=svc, steps=youtube_step(), now=NOW)


def test_the_youtube_step_says_what_it_downloaded_and_counts_its_runs(conn, cfg, tmp_path, monkeypatch):
    from conftest import add_song
    from helpers.fake_ytdlp import entry

    from caracole.songs import update_song

    ycfg, fake = youtube_cfg(cfg, tmp_path, monkeypatch)
    for title in ("Creep", "Airbag"):
        update_song(conn, add_song(conn, "Radiohead", title, duration_ms=239000).id, match_decision="not_found")
    fake.search("Radiohead Creep", entry("XFkzRNyygfk", "Creep", "Radiohead - Topic", 239))
    fake.video("XFkzRNyygfk", "Creep", "Radiohead - Topic", 239)
    report = youtube_run(conn, ycfg, fake)
    assert report.ok and report.steps["youtube"] == "2 tried, 1 downloaded, 1 not on YouTube, 0 unavailable, 0 errors"
    lines = report.summary().splitlines()
    assert "YouTube: 1 song downloaded, 1 song not there." in lines
    assert any("YouTube 3 of 6" in line for line in lines)
    assert get_state(conn, "youtube").last_ok == NOW


def test_youtube_errors_leave_their_songs_for_the_next_run(conn, cfg, tmp_path, monkeypatch):
    from conftest import add_song

    from caracole.songs import update_song

    ycfg, fake = youtube_cfg(cfg, tmp_path, monkeypatch)
    update_song(conn, add_song(conn, "Radiohead", "Creep").id, match_decision="not_found")
    fake.search("Radiohead Creep", stderr="ERROR: Unable to download API page: HTTP Error 503: Service Unavailable",
                exit=1)
    report = youtube_run(conn, ycfg, fake)
    assert report.ok and report.steps["youtube"].endswith("1 error")
    assert ("YouTube didn't answer (HTTP 503), so 1 song will be looked for on YouTube again on the next run."
            in report.summary().splitlines())
    assert get_state(conn, "youtube").last_error == "1 song failed this run"


def test_a_youtube_bot_check_cools_it_down_with_one_alert_and_marks_no_song(conn, cfg, tmp_path, monkeypatch):
    from conftest import add_song

    from caracole.songs import update_song

    ycfg, fake = youtube_cfg(cfg, tmp_path, monkeypatch)
    song = add_song(conn, "Radiohead", "Creep")
    update_song(conn, song.id, match_decision="not_found")
    fake.search("Radiohead Creep", stderr="ERROR: [youtube] Sign in to confirm you’re not a bot.", exit=1)
    out = Outbox()
    report = youtube_run(conn, ycfg, fake, notifier=out.notifier())
    assert report.ok and report.blocked == ["youtube"] and report.steps["youtube"].startswith("blocked")
    assert is_cooling(conn, "youtube", NOW + timedelta(hours=25))
    assert [title for title, _ in out.sent].count("caracole: YouTube blocked") == 1
    assert kv_get_json(conn, f"youtube:{song.id}") is None
    again = youtube_run(conn, ycfg, fake)
    assert again.steps["youtube"].startswith("skipped: youtube cooling down until")
    assert len(fake.argvs()) == 1
