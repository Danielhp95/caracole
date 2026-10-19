import email.header

import httpx

from tabarr.notify import Notifier


def capture():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "x"})

    return seen, httpx.MockTransport(handler)


def test_send_posts_with_headers():
    seen, transport = capture()
    n = Notifier("https://ntfy.sh/tabarr-test", "tk_1", transport=transport)
    assert n.send("tabarr run", "3 new sheets", priority="high", tags=["guitar", "white_check_mark"])
    r = seen[0]
    assert r.method == "POST" and str(r.url) == "https://ntfy.sh/tabarr-test"
    assert r.content == "3 new sheets".encode()
    assert r.headers["title"] == "tabarr run"
    assert r.headers["priority"] == "high"
    assert r.headers["tags"] == "guitar,white_check_mark"
    assert r.headers["authorization"] == "Bearer tk_1"


def test_non_ascii_title_is_rfc2047_encoded_and_body_is_utf8():
    seen, transport = capture()
    Notifier("https://ntfy.sh/t", None, transport=transport).send("新谱: 斑马斑马", "宋冬野 – 斑马斑马 ✓")
    r = seen[0]
    decoded = "".join(
        part.decode(enc or "ascii") if isinstance(part, bytes) else part
        for part, enc in email.header.decode_header(r.headers["title"])
    )
    assert decoded == "新谱: 斑马斑马"
    assert r.content.decode("utf-8") == "宋冬野 – 斑马斑马 ✓"
    assert "authorization" not in r.headers


def test_send_swallows_errors():
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    assert Notifier("https://ntfy.sh/t", None, transport=httpx.MockTransport(boom)).send("a", "b") is False
    assert Notifier("https://ntfy.sh/t", None,
                    transport=httpx.MockTransport(lambda r: httpx.Response(500))).send("a", "b") is False


def test_unconfigured_notifier_is_a_no_op():
    seen, transport = capture()
    assert Notifier(None, None, transport=transport).send("a", "b") is False
    assert seen == []
