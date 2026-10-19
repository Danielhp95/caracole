import logging
import random
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from caracole.config import ProviderPolicy
from caracole.http import (
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
        user_agent="caracole/test",
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
    assert rec.requests[0].headers["user-agent"] == "caracole/test"


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


TABS = "https://tabs.ultimate-guitar.com"
WWW = "https://www.ultimate-guitar.com"
# Each closed by a Disallow line of its host's robots.txt (User-agent: *), as captured in the spike.
ROBOTS_CLOSED = [
    TABS + "/tab/print?id=1",  # /tab/print?
    TABS + "/tab/download?id=1",  # /tab/download
    TABS + "/tab/download-kids-worship/shine-your-light-chords-4818770",  # /tab/download, a prefix (real index row)
    TABS + "/tab/track/se-que-es-tarde-chords-1126580",  # /tab/track/ (real index row)
    TABS + "/tab/applicature/transpose?id=1",  # /tab/applicature/transpose
    TABS + "/download/public/1234",  # /download/public/
    WWW + "/search.php?search_type=title&value=x",  # /search.php
    WWW + "/tab-pro/download?id=1",  # /tab-pro/download
    WWW + "/artist/soda_stereo_2946?no_takeover",  # /*?no_takeover
]
READ_BY_CARACOLE = [
    TABS + "/tab/soda-stereo/persiana-americana-tabs-1081462",
    TABS + "/tab/85053",
    WWW + "/artist/soda_stereo_2946?filter=chords&page=2",
    WWW + "/sitemap_last.xml",
    "https://lrclib.net/api/search?track_name=%E6%96%91%E9%A9%AC%E6%96%91%E9%A9%AC&artist_name=x",
    "https://acordes.lacuerda.net/soda_stereo/",
]


@pytest.mark.parametrize("url", ROBOTS_CLOSED)
def test_urls_robots_txt_closes_are_never_requested(tmp_path, url):
    client, rec = make_client(tmp_path, ok())
    with pytest.raises(ProviderError) as e:
        client.get(url)
    assert not isinstance(e.value, (ProviderBlocked, ProviderUnavailable))
    assert rec.requests == [] and client.requests_made == 0


@pytest.mark.parametrize("url", READ_BY_CARACOLE)
def test_urls_caracole_reads_are_open(tmp_path, url):
    client, rec = make_client(tmp_path, ok())
    assert client.get(url).status == 200 and len(rec.requests) == 1


def test_robots_disallows_names_the_rule_for_other_modules():
    from caracole.http import robots_disallows

    assert robots_disallows(TABS + "/tab/track/ave-fenix-guitar-pro-1149792") == "/tab/track/"
    assert [u for u in READ_BY_CARACOLE if robots_disallows(u)] == []


def test_robots_refusals_are_not_provider_failures(tmp_path):
    # No request is sent, so the breaker neither counts a refusal nor resets on one.
    client, rec = make_client(tmp_path, ok(b"boom", status=502), max_consecutive_errors=3)
    refused = [f"{TABS}/tab/print?id={i}" for i in range(3)]
    for url in [TABS + "/tab/1", *refused, TABS + "/tab/2", TABS + "/tab/3"]:
        with pytest.raises(ProviderError) as e:
            client.get(url)
        assert not isinstance(e.value, ProviderUnavailable)
    with pytest.raises(ProviderUnavailable):  # /tab/1, /tab/2 and /tab/3 failed in a row
        client.get(TABS + "/tab/4")
    assert len(rec.requests) == 3


# Strings httpx refuses as URLs, as UG's JSON or a sitemap could carry them. Built with chr() so
# no editor or tool turns them into invisible literals.
NOT_URLS = {
    "control-character": TABS + "/tab/a/b" + chr(0) + "-chords-1",
    "newline": TABS + "/tab/a/b" + chr(10) + "-chords-1",
    "over-64-KiB": TABS + "/tab/a/" + "x" * 70_000 + "-chords-1",
    "lone-surrogate": TABS + "/tab/a/b" + chr(0xD800) + "-chords-1",
    "broken-host": "https://[::zz]/tab/1",
}


@pytest.mark.parametrize("url", NOT_URLS.values(), ids=NOT_URLS.keys())
def test_robots_disallows_counts_a_string_that_isnt_a_url_as_closed(url):
    # Never httpx.InvalidURL: fetch.py asks it of every candidate, index.py of indexed paths.
    from caracole.http import robots_disallows

    assert robots_disallows(url) is not None


@pytest.mark.parametrize("url", NOT_URLS.values(), ids=NOT_URLS.keys())
def test_a_string_that_isnt_a_url_is_a_provider_error_and_never_sent(tmp_path, url):
    # One song fails, not the run. Nothing is sent, so the breaker doesn't count it either.
    client, rec = make_client(tmp_path, ok(), max_consecutive_errors=1)
    with pytest.raises(ProviderError) as e:
        client.get(url)
    assert not isinstance(e.value, (ProviderBlocked, ProviderUnavailable))
    assert "not a valid URL" in str(e.value) and len(str(e.value)) < 300  # a line for the log
    assert rec.requests == [] and client.requests_made == 0
    assert client.get(TABS + "/tab/1").status == 200


OLD = TABS + "/tab/a/old-chords-1"
NEW = TABS + "/tab/a/new-chords-1"


def moved(location, *, status=301, frm=OLD):
    """A site where ``frm`` redirects to ``location`` and every other URL answers 200."""
    def handler(request):
        if str(request.url) == frm:
            return httpx.Response(status, headers={"Location": location})
        return httpx.Response(200, content=b"page")
    return handler


def test_each_redirect_hop_is_counted_and_paced(tmp_path):
    sleeps: list[float] = []
    client, rec = make_client(tmp_path, moved("/tab/a/new-chords-1"), sleeps=sleeps)
    assert client.get(OLD).content == b"page"
    assert [str(r.url) for r in rec.requests] == [OLD, NEW]
    assert client.requests_made == 2
    assert len(sleeps) == 1 and 10.0 <= sleeps[0] <= 20.0


def test_each_redirect_hop_is_an_event(tmp_path):
    events = []
    client, _ = make_client(tmp_path, moved(NEW, status=302), events=events)
    client.get(OLD)
    assert [(e.url, e.status, e.decision) for e in events] == [(OLD, 302, "redirect"), (NEW, 200, "ok")]


def test_a_redirected_answer_is_cached_under_the_url_asked(tmp_path):
    client, rec = make_client(tmp_path, moved(NEW))
    assert client.get(OLD).url == OLD
    again = client.get(OLD)
    assert again.from_cache and again.content == b"page" and len(rec.requests) == 2


def test_a_redirect_hop_needs_budget(tmp_path):
    client, rec = make_client(tmp_path, moved(NEW), budget=1)
    with pytest.raises(BudgetExhausted):
        client.get(OLD)
    assert len(rec.requests) == 1


def test_a_redirect_loop_stops_after_three_hops(tmp_path):
    # Old PHP sites (LaCuerda) can redirect to themselves; httpx alone would follow 20 hops.
    sleeps: list[float] = []
    client, rec = make_client(tmp_path, lambda r: httpx.Response(302, headers={"Location": str(r.url)}),
                              sleeps=sleeps, max_consecutive_errors=3)
    for i in range(3):
        with pytest.raises(ProviderError) as e:
            client.get(f"https://acordes.lacuerda.net/artist_{i}/")
        assert not isinstance(e.value, ProviderUnavailable)
    with pytest.raises(ProviderUnavailable):
        client.get("https://acordes.lacuerda.net/artist_9/")
    assert len(rec.requests) == client.requests_made == 12  # each: the request and 3 hops
    assert len(sleeps) == 11


def test_a_redirect_robots_txt_closes_is_not_followed(tmp_path):
    client, rec = make_client(tmp_path, moved("/tab/print?id=1", status=302))
    with pytest.raises(ProviderError) as e:
        client.get(OLD)
    assert not isinstance(e.value, ProviderBlocked)
    assert [str(r.url) for r in rec.requests] == [OLD]


def test_a_url_robots_txt_closes_is_robots_closed_asked_for_or_redirected_to(tmp_path):
    # One error for both, so a caller can treat the URL as one caracole may not read, not as a failure.
    from caracole.http import RobotsClosed

    client, _ = make_client(tmp_path, moved("/tab/print?id=1", status=302))
    for url in (TABS + "/tab/print?id=1", OLD):
        with pytest.raises(RobotsClosed) as e:
            client.get(url)
        assert isinstance(e.value, ProviderError) and "/tab/print?" in str(e.value)


def test_a_redirect_robots_txt_closes_is_no_failure_of_the_provider(tmp_path):
    # UG answered: the breaker doesn't count the hop it won't follow, and the event says redirect.
    from caracole.http import RobotsClosed

    events = []
    client, rec = make_client(tmp_path, moved("/tab/print?id=1", status=302), events=events,
                              max_consecutive_errors=1)
    with pytest.raises(RobotsClosed):
        client.get(OLD)
    assert client.get(NEW).status == 200
    assert [str(r.url) for r in rec.requests] == [OLD, NEW]
    assert [(e.url, e.status, e.decision) for e in events] == [(OLD, 302, "redirect"), (NEW, 200, "ok")]
    assert "robots.txt" in (events[0].message or "")


def test_a_redirect_to_another_site_is_not_followed(tmp_path):
    client, rec = make_client(tmp_path, moved("https://accounts.example.com/login?next=/tab/a", status=302))
    with pytest.raises(ProviderError):
        client.get(OLD)
    assert [str(r.url) for r in rec.requests] == [OLD]


def test_a_redirect_between_the_hosts_of_one_site_is_followed(tmp_path):
    client, rec = make_client(tmp_path, moved(WWW + "/artist/a_1"))
    assert client.get(OLD).status == 200
    assert [str(r.url) for r in rec.requests] == [OLD, WWW + "/artist/a_1"]


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


def test_a_404_the_caller_rejects_is_not_cached(tmp_path):
    client, rec = make_client(tmp_path, ok(b"<html>Not Found</html>", status=404))
    with pytest.raises(ProviderError):
        client.get("https://lrclib.net/api/search?track_name=x")  # accepts only 200
    assert not client.get("https://lrclib.net/api/search?track_name=x", accept=(200, 404)).from_cache
    assert len(rec.requests) == 2


def test_a_cached_answer_the_caller_rejects_is_asked_again(tmp_path):
    # A 404 stored by a caller that accepted it (or by an older caracole) is no answer
    # for one that doesn't: replaying it would fail the song every night without asking.
    statuses = iter([404, 200])
    client, rec = make_client(tmp_path, lambda r: httpx.Response(next(statuses), content=b"[]"))
    assert client.get("https://lrclib.net/api/search?track_name=x", accept=(200, 404)).status == 404
    again = client.get("https://lrclib.net/api/search?track_name=x")
    assert again.status == 200 and not again.from_cache
    assert len(rec.requests) == 2 and client.requests_made == 2
    assert client.get("https://lrclib.net/api/search?track_name=x").from_cache


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


def test_has_cached_says_whether_a_request_would_have_a_copy_to_revalidate_and_sends_nothing(tmp_path):
    # `caracole index build` says how many sitemaps it may not have to download before it asks.
    def handler(request):
        return httpx.Response(404 if request.url.path == "/gone.xml" else 200, content=b"<urlset/>")

    client, rec = make_client(tmp_path, handler)
    sitemap, gone = "https://www.ultimate-guitar.com/sitemap40.xml", "https://www.ultimate-guitar.com/gone.xml"
    assert not client.has_cached(sitemap)
    client.get(sitemap, cache=False, conditional=True)
    client.get(gone, accept=(200, 404))
    assert client.has_cached(sitemap)
    assert not client.has_cached("https://www.ultimate-guitar.com/sitemap41.xml")
    # a cached answer the caller rejects is no copy: it is asked for again, as get() does
    assert not client.has_cached(gone) and client.has_cached(gone, accept=(200, 404))
    assert len(rec.requests) == 2


def test_has_cached_is_false_when_the_body_is_gone_as_get_would_download_it(tmp_path):
    client, rec = make_client(tmp_path, ok(b"<urlset/>"))
    sitemap = "https://www.ultimate-guitar.com/sitemap40.xml"
    client.get(sitemap, cache=False, conditional=True)
    for body in (tmp_path / "cache").rglob("*.body"):
        body.unlink()
    assert not client.has_cached(sitemap)
    assert client.get(sitemap, cache=False, conditional=True).status == 200
    assert "if-none-match" not in rec.requests[-1].headers  # no copy to revalidate: a plain GET


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


def lrclib_outage(get_status):
    """LRCLIB with /api/get answering ``get_status`` and /api/search failing with 503."""
    return lambda r: httpx.Response(get_status if r.url.path == "/api/get" else 503, content=b"ServerOverloaded")


def test_an_accepted_503_does_not_reset_the_error_count(tmp_path):
    # /api/get accepts 503 (LRCLIB's answer to a miss); in an outage it must not hide
    # /api/search's errors from the breaker.
    client, rec = make_client(tmp_path, lrclib_outage(503), max_consecutive_errors=3)
    for i in range(3):
        assert client.get(f"https://lrclib.net/api/get?n={i}", accept=(200, 404, 503)).status == 503
        with pytest.raises(ProviderError):
            client.get(f"https://lrclib.net/api/search?n={i}")
    with pytest.raises(ProviderUnavailable):
        client.get("https://lrclib.net/api/get?n=3", accept=(200, 404, 503))
    assert len(rec.requests) == 6


def test_an_accepted_404_resets_the_error_count(tmp_path):
    client, rec = make_client(tmp_path, lrclib_outage(404), max_consecutive_errors=3)
    for i in range(3):
        assert client.get(f"https://lrclib.net/api/get?n={i}", accept=(200, 404, 503)).status == 404
        with pytest.raises(ProviderError) as e:
            client.get(f"https://lrclib.net/api/search?n={i}")
        assert not isinstance(e.value, ProviderUnavailable)
    assert client.get("https://lrclib.net/api/get?n=3", accept=(200, 404, 503)).status == 404
    assert len(rec.requests) == 7


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


# --- a line per request in the log, at -v -----------------------------------------------------


def request_lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "caracole.http"]


def test_each_request_is_one_line_at_info_with_its_status_time_and_budget(tmp_path, caplog, monkeypatch):
    import caracole.http as http

    ticks = iter([10.0, 10.25, 20.0, 20.5])
    monkeypatch.setattr(http, "perf_counter", lambda: next(ticks))
    client, _ = make_client(tmp_path, lambda r: httpx.Response(503 if "busy" in str(r.url) else 200), budget=60)
    with caplog.at_level(logging.INFO, logger="caracole.http"):
        client.get("https://tabs.ultimate-guitar.com/tab/1")
        with pytest.raises(ProviderError):
            client.get("https://tabs.ultimate-guitar.com/tab/busy", params={"q": "x y"})
        client.get("https://tabs.ultimate-guitar.com/tab/1")  # from the cache: no request, no budget
    assert request_lines(caplog) == [
        "Ultimate Guitar GET https://tabs.ultimate-guitar.com/tab/1 → 200 OK in 0.25 s (1 of 60 requests)",
        "Ultimate Guitar GET https://tabs.ultimate-guitar.com/tab/busy?q=x+y → 503 Service Unavailable in 0.50 s "
        "(2 of 60 requests)",
        "Ultimate Guitar GET https://tabs.ultimate-guitar.com/tab/1 → 200 OK from the cache (2 of 60 requests)",
    ]
    assert {r.levelno for r in caplog.records if r.name == "caracole.http"} == {logging.INFO}


def test_a_request_that_gets_no_answer_says_what_happened(tmp_path, caplog, monkeypatch):
    import caracole.http as http

    ticks = iter([1.0, 31.0])
    monkeypatch.setattr(http, "perf_counter", lambda: next(ticks))

    def timeout(request):
        raise httpx.ReadTimeout("timed out", request=request)

    client, _ = make_client(tmp_path, timeout)
    with caplog.at_level(logging.INFO, logger="caracole.http"), pytest.raises(ProviderError):
        client.get("https://tabs.ultimate-guitar.com/tab/1")
    assert request_lines(caplog) == [
        "Ultimate Guitar GET https://tabs.ultimate-guitar.com/tab/1 → ReadTimeout after 30.00 s (1 of 60 requests)",
    ]
