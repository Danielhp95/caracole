from datetime import UTC, datetime, timedelta

import httpx

from tabarr.db import kv_get_json
from tabarr.health import get_state, is_cooling, record_block
from tabarr.http import BudgetExhausted, ProviderBlocked, ProviderError
from tabarr.notify import Notifier
from tabarr.pipeline import RunReport, Services, Step, run_pipeline

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
    return Services(
        clients={p: FakeClient(requests.get(p, 0)) for p in ("ug", "lrclib", "lacuerda")},
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
    assert out.sent and out.sent[-1][0] == "tabarr run"
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
    assert titles.count("tabarr: ug blocked") == 1


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
    assert report.steps["fetch"].startswith("skipped: ug cooling down until 2026-10-19 01:30 UTC")


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
    assert report.requests == {"ug": 7, "lrclib": 3, "lacuerda": 0}
    assert "ug 7" in report.summary() and "lrclib 3" in report.summary()


def test_default_steps_are_in_plan_order():
    from tabarr.pipeline import default_steps

    assert [s.name for s in default_steps()] == [
        "sync", "index", "match", "lyrics", "fetch", "lacuerda", "scan", "render", "todo",
    ]
    assert {s.name: s.provider for s in default_steps()}["fetch"] == "ug"


def test_unreadable_overrides_stop_the_run_with_an_alert(conn, cfg):
    cfg.overrides_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.overrides_file.write_text("[pins]\n", encoding="utf-8")
    calls, out = [], Outbox()
    report = run_pipeline(cfg, conn=conn, services=services(out), steps=[step("todo", calls=calls)], now=NOW)
    assert not report.ok and calls == []
    assert out.sent[-1][0] == "tabarr run failed" and "pins" in out.sent[-1][1]


def test_run_command_exit_codes(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    import tabarr.pipeline as pipeline
    from tabarr.cli import build_app

    cfgfile = tmp_path / "tabarr.toml"
    cfgfile.write_text(f'state_dir = "{tmp_path / "state"}"\ncache_dir = "{tmp_path / "cache"}"\n'
                       f'library_dir = "{tmp_path / "lib"}"\n', encoding="utf-8")
    results = iter([RunReport(run_id="r", started="r", steps={"todo": "ok"}),
                    RunReport(run_id="r", started="r", steps={"match": "failed: boom"}, errors=["match: boom"])])
    monkeypatch.setattr(pipeline, "run_pipeline", lambda cfg, **kw: next(results))
    ok = CliRunner().invoke(build_app(), ["--config", str(cfgfile), "run"])
    assert ok.exit_code == 0 and "todo: ok" in ok.output
    bad = CliRunner().invoke(build_app(), ["--config", str(cfgfile), "run"])
    assert bad.exit_code == 1 and "match: failed: boom" in bad.output


def test_default_match_step_skips_while_the_index_is_empty(conn, cfg):
    from tabarr.pipeline import _match, StepContext
    from tabarr.overrides import Overrides
    from conftest import add_song

    add_song(conn, "Radiohead", "Creep")
    out = Outbox()
    ctx = StepContext(cfg=cfg, conn=conn, overrides=Overrides(), now=NOW, run_id="r", services=services(out),
                      report=RunReport(run_id="r", started="r"))
    assert _match(ctx).startswith("skipped: the index is empty")
    assert conn.execute("SELECT match_decision FROM songs").fetchone()[0] is None


def keep_sheet_before_lyrics(conn, cfg, song, content):
    """A UG sheet kept while the song's lyrics were pending: sheet.txt and sheet.json, no coverage."""
    import json

    from tabarr.library import keep_file
    from tabarr.ug.page import strip_markup
    from tabarr.versions import upsert_version

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

    from tabarr.lyrics import Lyrics
    from tabarr.pipeline import default_steps
    from tabarr.songs import update_song
    from tabarr.versions import get_version

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
    import tabarr.lacuerda_fetch as lf
    from tabarr.overrides import Overrides
    from tabarr.pipeline import StepContext, _lacuerda

    seen = {}

    def fake(conn_, client, library_dir, rank, now, *, overrides=None):
        seen["overrides"] = overrides
        return lf.LaCuerdaStats(tried=2, kept=1, missing=0, errors=1, budget_exhausted=False)

    monkeypatch.setattr(lf, "lacuerda_sheets", fake)
    o = Overrides(block=frozenset({1}))
    out = Outbox()
    ctx = StepContext(cfg=cfg, conn=conn, overrides=o, now=NOW, run_id="r", services=services(out),
                      report=RunReport(run_id="r", started="r"))
    summary = _lacuerda(ctx)
    assert seen["overrides"] is o
    assert "1 error" in summary
    assert get_state(conn, "lacuerda").last_error is not None


def test_fetch_summary_counts_settled_sheets(conn, cfg, monkeypatch):
    import tabarr.ug.fetch as fetch
    from tabarr.overrides import Overrides
    from tabarr.pipeline import StepContext, _fetch

    monkeypatch.setattr(fetch, "songs_to_fetch", lambda *a, **k: [])
    monkeypatch.setattr(fetch, "rescore_kept_sheets", lambda *a, **k: 0)
    monkeypatch.setattr(fetch, "fetch_songs", lambda *a, **k: fetch.FetchStats(
        songs_done=1, songs_failed=0, budget_exhausted=True, sheets_done=2))
    ctx = StepContext(cfg=cfg, conn=conn, overrides=Overrides(), now=NOW, run_id="r", services=services(Outbox()),
                      report=RunReport(run_id="r", started="r"))
    assert _fetch(ctx) == "2 sheets settled, 1 song done, 0 failed (budget spent)"


# --- provider health on the to-do page ------------------------------------------------------


def todo_page(cfg):
    return (cfg.library_dir / "_todo.md").read_text(encoding="utf-8")


def todo_step():
    from tabarr.pipeline import default_steps

    return [s for s in default_steps() if s.name == "todo"]


def test_todo_page_counts_this_runs_requests_as_the_last_success(conn, cfg):
    # The page is written before the run ends; a first run must not say "never" after 75 good requests.
    run_pipeline(cfg, conn=conn, services=services(Outbox(), ug=60, lrclib=10, lacuerda=5), steps=todo_step(),
                 now=NOW)
    page = todo_page(cfg)
    assert "| ug | OK | 2026-10-18 03:30 UTC |  | 60 |" in page
    assert "| lrclib | OK | 2026-10-18 03:30 UTC |  | 10 |" in page
    assert "never" not in page.split("## Provider health", 1)[1]
