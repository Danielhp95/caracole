import random
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from tabarr.config import ProviderPolicy
from tabarr.http import (
    BudgetExhausted,
    PoliteClient,
    ProviderBlocked,
    ProviderError,
    ProviderUnavailable,
    is_challenge,
)

NORMAL_PAGE = (
    b"<html><head><title>DE MUSICA LIGERA CHORDS</title></head><body>"
    b'<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script></body></html>'
)
CHALLENGE = (
    b"<!DOCTYPE html><html><head><title>Just a moment...</title></head><body>"
    b"<script>window._cf_chl_opt={cvId: '3'};</script>"
    b'<script src="/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1"></script></body></html>'
)


class Recorder:
    def __init__(self, handler):
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)


def make_client(tmp_path, handler, *, budget=60, delay=(10.0, 20.0), sleeps=None, events=None, **kw):
    rec = Recorder(handler)
    client = PoliteClient(
        "ug",
        ProviderPolicy(budget=budget, delay=delay),
        tmp_path / "cache",
        user_agent="tabarr/test",
        transport=httpx.MockTransport(rec),
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
        rng=random.Random(1),
        on_event=(events.append if events is not None else None),
        clock=lambda: 0.0,
        **kw,
    )
    return client, rec


def ok(body=b"hello", status=200, headers=None):
    return lambda request: httpx.Response(status, content=body, headers=headers or {})


def test_cache_hit_makes_no_request(tmp_path):
    client, rec = make_client(tmp_path, ok(b"page"))
    first = client.get("https://tabs.ultimate-guitar.com/tab/1")
    second = client.get("https://tabs.ultimate-guitar.com/tab/1")
    assert first.content == second.content == b"page"
    assert (first.from_cache, second.from_cache) == (False, True)
    assert len(rec.requests) == 1 and client.requests_made == 1


def test_cache_survives_a_new_client(tmp_path):
    client, _ = make_client(tmp_path, ok(b"page"))
    client.get("https://tabs.ultimate-guitar.com/tab/1")
    client2, rec2 = make_client(tmp_path, ok(b"other"))
    assert client2.get("https://tabs.ultimate-guitar.com/tab/1").content == b"page"
    assert rec2.requests == []


def test_params_are_part_of_the_cache_key(tmp_path):
    client, rec = make_client(tmp_path, lambda r: httpx.Response(200, content=r.url.query))
    a = client.get("https://lrclib.net/api/get", params={"track_name": "斑马斑马", "duration": 253})
    b = client.get("https://lrclib.net/api/get", params={"track_name": "Other"})
    assert a.content != b.content and len(rec.requests) == 2
    assert rec.requests[0].url.params["track_name"] == "斑马斑马"
    assert rec.requests[0].url.params["duration"] == "253"


def test_user_agent_sent(tmp_path):
    client, rec = make_client(tmp_path, ok())
    client.get("https://tabs.ultimate-guitar.com/tab/1")
    assert rec.requests[0].headers["user-agent"] == "tabarr/test"


def test_pause_before_every_network_request_but_the_first(tmp_path):
    sleeps: list[float] = []
    client, _ = make_client(tmp_path, ok(), sleeps=sleeps)
    client.get("https://tabs.ultimate-guitar.com/tab/1")
    client.get("https://tabs.ultimate-guitar.com/tab/1")  # cache hit: no pause
    client.get("https://tabs.ultimate-guitar.com/tab/2")
    assert len(sleeps) == 1
    assert 10.0 <= sleeps[0] <= 20.0


def test_pause_counts_time_already_elapsed(tmp_path):
    sleeps: list[float] = []
    now = [0.0]
    rec = Recorder(ok())
    client = PoliteClient(
        "ug", ProviderPolicy(budget=10, delay=(10.0, 10.0)), tmp_path / "c", user_agent="t",
        transport=httpx.MockTransport(rec), sleep=sleeps.append, rng=random.Random(1), clock=lambda: now[0],
    )
    client.get("https://x.test/1")
    now[0] = 4.0
    client.get("https://x.test/2")
    now[0] = 30.0
    client.get("https://x.test/3")
    assert sleeps == [6.0]


def test_budget_exhausted_before_request(tmp_path):
    events = []
    client, rec = make_client(tmp_path, ok(), budget=2, events=events)
    client.get("https://x.test/1")
    client.get("https://x.test/2")
    with pytest.raises(BudgetExhausted):
        client.get("https://x.test/3")
    assert len(rec.requests) == 2
    assert events[-1].decision == "budget"
    # Cached pages are still served once the budget is spent.
    assert client.get("https://x.test/1").from_cache


@pytest.mark.parametrize("status", [403, 429])
def test_403_and_429_are_blocks(tmp_path, status):
    client, _ = make_client(tmp_path, ok(b"no", status=status))
    with pytest.raises(ProviderBlocked) as e:
        client.get("https://x.test/1")
    assert e.value.status == status


def test_challenge_page_with_200_is_a_block(tmp_path):
    client, _ = make_client(tmp_path, ok(CHALLENGE))
    with pytest.raises(ProviderBlocked):
        client.get("https://tabs.ultimate-guitar.com/tab/1")


def test_cf_mitigated_header_is_a_block(tmp_path):
    client, _ = make_client(tmp_path, ok(b"x", status=403, headers={"cf-mitigated": "challenge"}))
    with pytest.raises(ProviderBlocked):
        client.get("https://x.test/1")


def test_normal_page_with_cloudflare_script_is_not_a_block(tmp_path):
    client, _ = make_client(tmp_path, ok(NORMAL_PAGE))
    assert client.get("https://tabs.ultimate-guitar.com/tab/1").status == 200
    assert not is_challenge(200, {}, NORMAL_PAGE)
    assert is_challenge(200, {}, CHALLENGE)


def test_after_a_block_no_more_requests_this_run(tmp_path):
    client, rec = make_client(tmp_path, ok(b"no", status=429))
    with pytest.raises(ProviderBlocked):
        client.get("https://x.test/1")
    with pytest.raises(ProviderBlocked):
        client.get("https://x.test/2")
    assert len(rec.requests) == 1


def test_500_is_error_and_not_cached(tmp_path):
    client, rec = make_client(tmp_path, ok(b"boom", status=500))
    with pytest.raises(ProviderError) as e:
        client.get("https://x.test/1")
    assert not isinstance(e.value, ProviderBlocked)
    assert e.value.status == 500
    with pytest.raises(ProviderError):
        client.get("https://x.test/1")
    assert len(rec.requests) == 2


def test_network_error_is_provider_error(tmp_path):
    def boom(request):
        raise httpx.ConnectError("refused", request=request)

    client, _ = make_client(tmp_path, boom)
    with pytest.raises(ProviderError):
        client.get("https://x.test/1")


def test_404_is_cached_when_accepted(tmp_path):
    client, rec = make_client(tmp_path, ok(b"gone", status=404))
    assert client.get("https://x.test/1", accept=(200, 404)).status == 404
    assert client.get("https://x.test/1", accept=(200, 404)).from_cache
    assert len(rec.requests) == 1


def test_unaccepted_404_raises_provider_error(tmp_path):
    client, _ = make_client(tmp_path, ok(b"gone", status=404))
    with pytest.raises(ProviderError) as e:
        client.get("https://x.test/1")
    assert e.value.status == 404


def test_accepted_503_is_returned_not_cached(tmp_path):
    client, rec = make_client(tmp_path, ok(b'{"name": "ServerOverloaded"}', status=503))
    assert client.get("https://lrclib.net/api/get", accept=(200, 404, 503)).status == 503
    assert client.get("https://lrclib.net/api/get", accept=(200, 404, 503)).status == 503
    assert len(rec.requests) == 2


def test_conditional_get_sends_validators_and_reuses_body_on_304(tmp_path):
    def handler(request):
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=b"<urlset/>", headers={"etag": '"v1"', "last-modified": "Sun, 18 Oct 2026 13:09:36 GMT"})

    client, rec = make_client(tmp_path, handler)
    first = client.get("https://www.ultimate-guitar.com/sitemap40.xml", cache=False, conditional=True)
    second = client.get("https://www.ultimate-guitar.com/sitemap40.xml", cache=False, conditional=True)
    assert first.status == 200 and not first.from_cache
    assert second.status == 304 and second.from_cache and second.content == b"<urlset/>"
    assert rec.requests[1].headers["if-modified-since"] == "Sun, 18 Oct 2026 13:09:36 GMT"
    assert client.requests_made == 2


def test_uncached_conditional_get_is_plain(tmp_path):
    client, rec = make_client(tmp_path, ok(b"x"))
    client.get("https://x.test/s.xml", cache=False, conditional=True)
    assert "if-none-match" not in rec.requests[0].headers


def test_consecutive_errors_make_provider_unavailable(tmp_path):
    client, rec = make_client(tmp_path, ok(b"boom", status=502), max_consecutive_errors=3)
    for i in range(3):
        with pytest.raises(ProviderError):
            client.get(f"https://x.test/{i}")
    with pytest.raises(ProviderUnavailable):
        client.get("https://x.test/9")
    assert len(rec.requests) == 3


def test_success_resets_error_count(tmp_path):
    statuses = iter([502, 502, 200, 502, 502, 200])
    client, rec = make_client(tmp_path, lambda r: httpx.Response(next(statuses), content=b"x"), max_consecutive_errors=3)
    results = []
    for i in range(6):
        try:
            results.append(client.get(f"https://x.test/{i}").status)
        except ProviderError as e:
            results.append(type(e).__name__)
    assert results == ["ProviderError", "ProviderError", 200, "ProviderError", "ProviderError", 200]


def test_events_reported(tmp_path):
    events = []
    client, _ = make_client(tmp_path, ok(), events=events)
    client.get("https://x.test/1")
    client.get("https://x.test/1")
    assert [(e.provider, e.url, e.status, e.decision) for e in events] == [("ug", "https://x.test/1", 200, "ok")]


def test_large_bodies_round_trip_through_the_compressed_cache(tmp_path):
    body = ("<url><loc>https://tabs.ultimate-guitar.com/tab/a/b-chords-1</loc></url>" * 20000).encode()
    client, _ = make_client(tmp_path, ok(body))
    client.get("https://x.test/big")
    files = list((tmp_path / "cache").rglob("*.body"))
    assert files and files[0].stat().st_size < len(body) / 10
    assert client.get("https://x.test/big").content == body


def test_max_age_refetches_stale_copies_and_falls_back_when_budget_is_spent(tmp_path):
    clock = [datetime(2026, 10, 18, tzinfo=UTC)]
    bodies = iter([b"v1", b"v2"])
    rec = Recorder(lambda r: httpx.Response(200, content=next(bodies)))
    client = PoliteClient(
        "ug", ProviderPolicy(budget=2, delay=(0.0, 0.0)), tmp_path / "c", user_agent="t",
        transport=httpx.MockTransport(rec), sleep=lambda s: None, rng=random.Random(1), clock=lambda: 0.0,
        wall_clock=lambda: clock[0],
    )
    url = "https://www.ultimate-guitar.com/artist/soda_stereo_2946?filter=chords"
    assert client.get(url, max_age=timedelta(days=30)).content == b"v1"
    clock[0] += timedelta(days=10)
    fresh = client.get(url, max_age=timedelta(days=30))
    assert fresh.from_cache and fresh.content == b"v1" and len(rec.requests) == 1
    clock[0] += timedelta(days=25)
    assert client.get(url, max_age=timedelta(days=30)).content == b"v2"
    assert len(rec.requests) == 2
    clock[0] += timedelta(days=40)
    stale = client.get(url, max_age=timedelta(days=30))  # budget spent: the stale copy beats nothing
    assert stale.from_cache and stale.content == b"v2" and len(rec.requests) == 2
