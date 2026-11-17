"""The nightly run's ug-directory step (pipeline.py): UG's artist directory with its own client, through fakes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from caracole.config import ProviderPolicy
from caracole.health import get_state, is_cooling
from caracole.http import ParallelClient
from caracole.pipeline import Services, default_steps, run_pipeline
from caracole.ug.bands import LETTERS, listing_url
from caracole.ug.directory import index_state
from helpers.ug_bands import FakeDirectory, fillers
from test_pipeline import FakeClient, Outbox

NOW = datetime(2026, 11, 17, 3, 30, tzinfo=UTC)
STEP = [s for s in default_steps() if s.name == "ug-directory"]


def _services(tmp_path, site, out, *, budget=10_000):
    client = ParallelClient("ug", ProviderPolicy(budget=budget, delay=(0.0, 0.0)), tmp_path / "cache",
                            user_agent="caracole-test", transport=httpx.MockTransport(site.handler), workers=3,
                            sleep=lambda s: None, wall_clock=lambda: NOW)
    return Services(clients={"ug": FakeClient(4)}, notifier=out.notifier(), directory=client)


def _indexed(conn):
    conn.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen) "
                 "VALUES (1, 'soda-stereo', 'de-musica-ligera', 'chords', 'tabs1', '2026-10-18T00:00:00Z')")


def test_the_step_reads_the_directory_with_its_own_client_and_budget(conn, cfg, tmp_path):
    _indexed(conn)
    site = FakeDirectory({"s": fillers("s", 70, start=50_000)})
    out = Outbox()
    report = run_pipeline(cfg, conn=conn, services=_services(tmp_path, site, out), steps=STEP, now=NOW)
    assert report.ok and index_state(conn).complete
    assert report.steps["ug-directory"].startswith("28 listing pages, 96 artists (96 new)")
    assert report.requests == {"ug": 4 + 28} and report.budgets["ug"] == 10_000
    assert "UG's artist directory: 28 listing pages read, 96 new artists." in report.summary()


def test_the_step_waits_for_the_index(conn, cfg, tmp_path):
    site = FakeDirectory()
    report = run_pipeline(cfg, conn=conn, services=_services(tmp_path, site, Outbox()), steps=STEP, now=NOW)
    assert report.steps["ug-directory"].startswith("skipped: the index is empty") and not site.requests


def test_a_block_in_the_step_cools_ug_for_everything_and_alerts_once(conn, cfg, tmp_path):
    _indexed(conn)
    site = FakeDirectory()
    site.status[listing_url("m")] = 429
    out = Outbox()
    report = run_pipeline(cfg, conn=conn, services=_services(tmp_path, site, out), steps=STEP, now=NOW)
    assert report.blocked == ["ug"] and report.ok
    assert is_cooling(conn, "ug", NOW + timedelta(hours=20)) and get_state(conn, "ug").strikes == 1
    assert [t for t, _ in out.sent].count("caracole: Ultimate Guitar blocked") == 1
    assert len([u for u in site.requests if "/bands/" in u]) < len(LETTERS)  # nothing begun after it
