"""caracole/web/security.py: which hosts the server answers to, cross-origin writes, tokens."""

import pytest

from caracole.web.security import (
    allowed_hosts,
    cross_origin_ok,
    host_name,
    same_token,
    session_cookie,
    session_value,
)


@pytest.mark.parametrize("header,name", [
    ("localhost:8737", "localhost"),
    ("LOCALHOST", "localhost"),
    ("127.0.0.1:8737", "127.0.0.1"),
    ("[::1]:8737", "::1"),
    ("[::1]", "::1"),
    ("nuc.example.ts.net.:8737", "nuc.example.ts.net"),
    ("nuc", "nuc"),
])
def test_host_name_is_the_lowercase_name_without_its_port(header, name):
    assert host_name(header) == name


@pytest.mark.parametrize("header", [None, "", "localhost:80a", "[::1", "[::1]x", "a b", "evil.example:8737/x"])
def test_a_host_header_that_isnt_one_has_no_name(header):
    assert host_name(header) is None


def test_the_server_answers_to_its_own_names_and_those_you_add():
    hosts = allowed_hosts("127.0.0.1", hostname="NUC", extra=["nuc.example.ts.net", "Music.Lan."])
    assert {"localhost", "127.0.0.1", "::1", "nuc", "nuc.example.ts.net", "music.lan"} == hosts


def test_a_name_given_with_a_port_is_the_name_and_a_name_that_isnt_one_is_refused():
    assert "nuc" in allowed_hosts("127.0.0.1", extra=["nuc:8737"])
    assert "fd7a::7" in allowed_hosts("127.0.0.1", extra=["[fd7a::7]"])
    with pytest.raises(ValueError, match="'my nuc' isn't a host name"):
        allowed_hosts("127.0.0.1", extra=["my nuc"])


def test_a_specific_address_is_a_name_and_a_wildcard_is_not():
    assert "100.64.0.7" in allowed_hosts("100.64.0.7", hostname="nuc")
    assert "fd7a::7" in allowed_hosts("[fd7a::7]", hostname="nuc")
    assert "0.0.0.0" not in allowed_hosts("0.0.0.0", hostname="nuc")
    assert "::" not in allowed_hosts("::", hostname="nuc")


# Filippo Valsorda's algorithm, as Go's net/http CrossOriginProtection runs it.
@pytest.mark.parametrize("headers,ok", [
    ({"sec-fetch-site": "same-origin"}, True),
    ({"sec-fetch-site": "none"}, True),  # typed or bookmarked
    ({"sec-fetch-site": "cross-site", "origin": "http://localhost:8737"}, False),
    ({"sec-fetch-site": "same-site"}, False),
    ({}, True),  # not a browser: no cross-site request to forge
    ({"origin": "http://localhost:8737"}, True),  # plain HTTP over a LAN: no Sec-Fetch-Site
    ({"origin": "http://evil.example"}, False),
    ({"origin": "null"}, False),
    ({"origin": "http://localhost:9999"}, False),
])
def test_writes_must_come_from_the_page_itself(headers, ok):
    assert cross_origin_ok("POST", headers, "localhost:8737") is ok


def test_reads_are_never_refused_as_cross_origin():
    for method in ("GET", "HEAD", "OPTIONS"):
        assert cross_origin_ok(method, {"sec-fetch-site": "cross-site"}, "localhost:8737")


def test_tokens_compare_in_constant_time_and_never_match_nothing():
    assert same_token("abc", "abc")
    assert not same_token("abd", "abc")
    assert not same_token(None, "abc")
    assert not same_token("", "")


def test_the_session_cookie_holds_a_digest_of_the_token_never_the_token():
    value = session_value("correct horse battery staple")
    assert value != "correct horse battery staple" and len(value) == 64
    assert session_value("another token") != value
    header = "theme=dark; caracole_session=" + value
    assert session_cookie(header) == value
    assert session_cookie("theme=dark") is None
    assert session_cookie('broken="') is None
    assert session_cookie(None) is None
