"""canonical.py: a value's canonical JSON, its digest, the hash of a stored JSON text, as the spec's vectors and
properties say (docs/superpowers/specs/2026-11-03-canonical-json.md)."""

import hashlib
import inspect
import json
import random
import re
from decimal import Decimal
from pathlib import Path

import pytest
import test_peer_sync

from caracole import canonical, peer_sync

SPEC = Path(__file__).resolve().parents[1] / "docs" / "superpowers" / "specs" / "2026-11-03-canonical-json.md"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# The package's own build runs the suite on a source tree without docs/: there the spec's rows are none.
HAS_SPEC = SPEC.is_file()
needs_the_spec = pytest.mark.skipif(not HAS_SPEC, reason="docs/ is not in this tree")


def spec_rows():
    """The spec's table of vectors: (row, stored text, C or None, why there is none, H); none without the spec."""
    rows = []
    if not HAS_SPEC:
        return rows
    cell = r"`((?:[^`]|``)*)`"
    for line in SPEC.read_text("utf-8").splitlines():
        m = re.fullmatch(r"\| (\d+) \| (.+?) \| (.+?) \| `([0-9a-f]{64})` \|", line)
        if not m:
            continue
        number, text, c, h = m.groups()
        repeat = re.fullmatch(r'`("[^"]*")` × (\d+) .*', text)
        text = json.loads(repeat[1]) * int(repeat[2]) if repeat else json.loads(re.fullmatch(cell, text)[1])
        if c.startswith("`"):
            rows.append((int(number), text, json.loads(re.fullmatch(cell, c)[1]), None, h))
        else:
            rows.append((int(number), text, None, c, h))
    return rows


ROWS = spec_rows()


@needs_the_spec
def test_the_spec_has_its_vectors():
    assert [r[0] for r in ROWS] == list(range(1, 42))
    assert {r[3] for r in ROWS} == {None, "not JSON", "not canonicalizable"}


@pytest.mark.parametrize(("number", "text", "c", "why", "h"), ROWS, ids=[f"row{r[0]}" for r in ROWS])
def test_each_vector_of_the_spec(number, text, c, why, h):
    assert canonical.stored_hash(text) == h
    if why == "not JSON":
        with pytest.raises(ValueError):
            canonical.read(text)
        assert h == sha(text.encode("utf-8"))
        return
    value = canonical.read(text)
    if why == "not canonicalizable":
        with pytest.raises(canonical.NotCanonical):
            canonical.dumps(value)
        assert h == sha(text.encode("utf-8", "surrogatepass"))
        return
    assert canonical.dumps(value) == c
    assert canonical.digest(value) == h == sha(c.encode("utf-8"))


def test_the_exponent_rules_boundary_is_a_thousand():
    assert canonical.dumps(canonical.read("1e1000")) == "1" + "0" * 1000
    assert canonical.stored_hash("1e1000") == "4d20ea8840f0be06124aa54cac837707b5259196832785a09391d1f15fda98f9"
    assert canonical.dumps(canonical.read("1e-1000")) == "0." + "0" * 999 + "1"
    assert canonical.dumps(canonical.read("0.001e+0001000")) == "1" + "0" * 997  # the exponent as written
    for beyond in ("1e1001", "1e-1001", "1000e-1001", "1e+00001001", "1e" + "9" * 5000):
        with pytest.raises(canonical.NotCanonical):
            canonical.dumps(canonical.read(beyond))
        assert canonical.stored_hash(beyond) == sha(beyond.encode("utf-8"))


def test_238_point_0_and_238_hash_equal_as_text_and_as_value():
    assert canonical.stored_hash("238.0") == canonical.stored_hash("238") == canonical.digest(238)
    assert canonical.digest(238.0) == canonical.digest(238)
    assert canonical.stored_hash('{"duration": 213.0}') == canonical.digest({"duration": 213})


def test_a_float_is_written_by_the_decimal_rule_from_its_repr():
    assert canonical.dumps([238.0, 1e-07, 1e16, 0.1, -0.0, 5e-324]) == (
        "[238,0.0000001,10000000000000000,0.1,0," + "0." + "0" * 323 + "5]")
    assert canonical.dumps([float("nan"), float("inf"), float("-inf")]) == "[NaN,Infinity,-Infinity]"
    # A float and the text it was stored as have one digest.
    for x in (4.54038, 253.1004, 1e300, 2.5e-10):
        assert canonical.digest(x) == canonical.stored_hash(json.dumps(x))


def test_keys_sort_by_code_point_not_by_utf16():
    value = {"\U0001F600": 1, "\uff61": 2, "a": 3}
    assert canonical.dumps(value) == '{"a":3,"\uff61":2,"\U0001F600":1}'
    utf16 = sorted(value, key=lambda k: k.encode("utf-16-be"))
    assert utf16 == ["a", "\U0001F600", "\uff61"]  # the order the rule is not


def test_a_number_of_more_digits_than_a_float_holds_is_kept_whole():
    for literal in ("0.12345678901234567890123456789012345", "-98765432109876543210.123456789012345678901"):
        assert canonical.dumps(canonical.read(literal)) == literal
        assert canonical.stored_hash(literal) == sha(literal.encode())


def literals(seed: int, count: int):
    rng = random.Random(seed)
    for _ in range(count):
        whole = rng.choice(["0", str(rng.randrange(1, 10)) + "".join(rng.choices("0123456789", k=rng.randrange(8)))])
        fraction = "." + "".join(rng.choices("0123456789", k=rng.randrange(1, 12))) if rng.random() < 0.8 else ""
        exponent = ""
        if not fraction or rng.random() < 0.6:
            exponent = rng.choice("eE") + rng.choice(["", "+", "-"]) + str(rng.randrange(0, 40))
        yield rng.choice(["", "-"]) + whole + fraction + exponent


def test_the_decimal_rule_is_decimals_exact_value_written_plain():
    for literal in literals(20261103, 3000):
        exact = format(Decimal(literal), "f")
        if "." in exact:
            exact = exact.rstrip("0").rstrip(".")
        if exact in ("-0", "0", ""):
            exact = "0"
        assert canonical.decimal(literal) == exact, literal


def test_an_integer_of_more_than_4300_digits_is_not_json():
    assert canonical.dumps(canonical.read("7" * 4300)) == "7" * 4300
    assert canonical.dumps(canonical.read("-" + "7" * 4300)) == "-" + "7" * 4300
    for text in ("7" * 4301, "[" + "7" * 4301 + "]"):
        with pytest.raises(ValueError):
            canonical.read(text)
        assert canonical.stored_hash(text) == sha(text.encode())
    # A literal with a fraction is no int: its digits stay.
    assert canonical.dumps(canonical.read("7" * 5000 + ".50")) == "7" * 5000 + ".5"


def test_a_lone_surrogate_is_an_error_in_a_value_and_its_texts_own_bytes_in_a_stored_text():
    for value in ("a\ud800", {"\udfff": 1}, ["\ud83c", "x"]):
        with pytest.raises(ValueError):
            canonical.dumps(value)
    for text in ('"\\ud800"', '"\\udfb8\\ud83c"', '"a\ud800b"', '"\ud83c\\udfb8"', '"\\ud83c\udfb8"',
                 '{"\\ud800": 1}'):
        assert canonical.stored_hash(text) == sha(text.encode("utf-8", "surrogatepass")), ascii(text)
    # An escaped pair is one code point.
    assert canonical.stored_hash('"\\ud83c\\udfb8"') == canonical.digest("\U0001F3B8")


def test_only_space_tab_newline_and_return_are_whitespace():
    record = {"b": [1, 2.50], "a": "x"}
    one = canonical.digest({"a": "x", "b": [1, 2.5]})
    for text in (json.dumps(record), json.dumps(record, indent=1), json.dumps(record, indent="\t"),
                 json.dumps(record, indent=2).replace("\n", "\r\n"), " \t\r\n" + json.dumps(record) + "\n\n"):
        assert canonical.stored_hash(text) == one
    for space in ("\u00a0", "\x0b", "\x0c", "\u2028", "\u3000", "\ufeff", "\x85"):
        text = json.dumps(record) + space
        assert canonical.stored_hash(text) == sha(text.encode()), ascii(space)


def nested(depth: int) -> str:
    return "[" * depth + "]" * depth


def test_nesting_deeper_than_max_depth_is_not_canonicalizable():
    assert canonical.MAX_DEPTH == 512
    assert canonical.dumps(canonical.read(nested(512))) == nested(512)
    deep = canonical.read(nested(513))  # json.loads reads it
    with pytest.raises(canonical.NotCanonical):
        canonical.dumps(deep)
    for text in (nested(513), '{"a":' * 513 + "1" + "}" * 513, nested(300_000)):  # json.loads can't read the last
        assert canonical.stored_hash(text) == sha(text.encode())


def test_null_stays_null():
    assert canonical.stored_hash(None) is None
    assert canonical.stored_hash(None, without=("rating",)) is None


def test_a_stored_hash_without_some_members_is_of_the_object_they_are_taken_out_of():
    drop = ("rating", "votes")
    assert canonical.stored_hash('{"rating": 4.50, "votes": 3, "a": 1}', without=drop) == canonical.digest({"a": 1})
    assert canonical.stored_hash('{"a": 1}', without=drop) == canonical.stored_hash('{"a": 1}')
    # An object's own members alone: never one within it, nor anything of a text that holds no object.
    assert canonical.stored_hash('{"a": {"rating": 1}}', without=drop) == canonical.digest({"a": {"rating": 1}})
    for text in ('[{"rating": 1}]', '"rating"', "not json", nested(513), '{"a": "\\ud800", "rating": 1}'):
        assert canonical.stored_hash(text, without=drop) == canonical.stored_hash(text), ascii(text)
    # A member taken out is no part of the text's hash, whether it could be canonical or not.
    assert canonical.stored_hash('{"rating": 1e1001, "a": 1}', without=drop) == canonical.digest({"a": 1})
    assert canonical.stored_hash('{"votes": "\\ud800", "a": 1}', without=drop) == canonical.digest({"a": 1})


def values(seed: int, count: int):
    """Float-free values of every shape JSON has: what peer_sync's units are made of."""
    rng = random.Random(seed)
    alphabet = ["a", "Z", "é", "宋", "冬", "\uff61", "\U0001F3B8", "\U0001F600", "\x00", "\x1f", "\x7f", "\u2028",
                '"', "\\", "/", "\n", "\t", " "]

    def text():
        return "".join(rng.choices(alphabet, k=rng.randrange(6)))

    def value(depth):
        kind = rng.randrange(8 if depth < 4 else 5)
        if kind == 0:
            return None
        if kind == 1:
            return rng.random() < 0.5
        if kind == 2:
            return rng.choice([0, -1, 7, 2 ** 64, -(10 ** 40), rng.randrange(-10 ** 6, 10 ** 6)])
        if kind in (3, 4):
            return text()
        if kind == 5:
            return [value(depth + 1) for _ in range(rng.randrange(4))]
        return {text(): value(depth + 1) for _ in range(rng.randrange(4))}

    return [value(0) for _ in range(count)]


def test_format_1s_digests_are_unchanged_for_every_float_free_value():
    for value in values(31, 2000):
        assert canonical.dumps(value) == json.dumps(value, sort_keys=True, separators=(",", ":"),
                                                    ensure_ascii=False)
        assert canonical.digest(value) == peer_sync.digest_of(value)


def test_dumps_takes_what_json_dumps_takes():
    assert canonical.dumps((1, "a", [True, False, None])) == '[1,"a",[true,false,null]]'
    assert canonical.dumps({}) == "{}" and canonical.dumps([]) == "[]"
    with pytest.raises(TypeError):
        canonical.dumps({1, 2})
    with pytest.raises(TypeError):
        canonical.dumps(object())


def floats_in(value) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(floats_in(v) for v in value.values())
    return isinstance(value, (list, tuple)) and any(floats_in(v) for v in value)


# test_peer_sync.py's tests that build a library: each run again here, with every value peer_sync digests checked.
LIBRARIES = sorted(
    name for name, fn in vars(test_peer_sync).items()
    if name.startswith("test_") and inspect.isfunction(fn) and not hasattr(fn, "pytestmark")
    and set(inspect.signature(fn).parameters) <= {"tmp_path", "conn"})


BUILT = ("test_a_library_is_its_songs_removals_songbooks_and_the_entries_about_artists_and_tabs",
         "test_a_songs_digest_moves_with_its_chords_its_kept_files_and_its_own_version_and_nothing_else",
         "test_a_songbooks_digest_is_its_songs_in_order_with_their_settings")


def test_the_libraries_are_test_peer_syncs():
    assert set(BUILT) <= set(LIBRARIES)


@pytest.mark.parametrize("name", LIBRARIES)
def test_digest_is_peer_syncs_digest_of_for_every_unit_value_of_test_peer_syncs_libraries(name, tmp_path, conn,
                                                                                          monkeypatch):
    digest_of = peer_sync.digest_of
    seen = []

    def checked(value):
        seen.append(value)
        assert canonical.digest(value) == digest_of(value), value
        # FORMAT 1's text itself, so the check keeps its meaning once digest_of is canonical.digest (peer-format2).
        if not floats_in(value):
            assert canonical.digest(value) == sha(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                                             ensure_ascii=False).encode("utf-8")), value
        return digest_of(value)

    monkeypatch.setattr(peer_sync, "digest_of", checked)
    fn = getattr(test_peer_sync, name)
    given = {"tmp_path": tmp_path, "conn": conn}
    fn(**{p: given[p] for p in inspect.signature(fn).parameters})
    if name in BUILT:
        assert any(not floats_in(value) for value in seen)
