from caracole.http import BudgetExhausted, Client, Event, ProviderBlocked, ProviderError, ProviderUnavailable, Response


def test_response_text_and_json():
    r = Response(url="https://x/y", status=200, content='{"a": "é"}'.encode(), headers={}, from_cache=False)
    assert r.text == '{"a": "é"}'
    assert r.json() == {"a": "é"}


def test_error_hierarchy_and_message():
    e = ProviderBlocked("ug", "https://tabs.ultimate-guitar.com/tab/1", 403, "forbidden")
    assert isinstance(e, ProviderError)
    assert issubclass(ProviderUnavailable, ProviderError)
    assert (e.provider, e.url, e.status) == ("ug", "https://tabs.ultimate-guitar.com/tab/1", 403)
    assert "ug" in str(e) and "403" in str(e) and "forbidden" in str(e)
    assert not issubclass(BudgetExhausted, ProviderError)
    assert BudgetExhausted("ug").provider == "ug"


def test_event_fields():
    ev = Event(provider="lrclib", url="https://lrclib.net/api/get", status=200, decision="ok", message=None)
    assert ev.decision == "ok"


def test_fake_client_satisfies_protocol():
    class Fake:
        requests_made = 0

        def get(self, url, *, params=None, cache=True, conditional=False, accept=(200,)):
            return Response(url=url, status=200, content=b"", headers={}, from_cache=False)

    assert isinstance(Fake(), Client)
