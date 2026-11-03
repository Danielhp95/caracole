"""Canonical JSON: one text for a value, so that two languages serializing one record get one digest
(docs/superpowers/specs/2026-11-03-canonical-json.md, the contract; Kotlin's is ``core.json.Canonical``, held to this
module by tests/conformance/vectors/canonical/).

- ``dumps(value)``, C(v): ``json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)``, keys in
  code-point order, every character raw but ``"``, ``\\`` and those below U+0020; but a non-integral number is
  written as its exact decimal value (``decimal``), a float from its repr (238.0 as ``238``, 1e-07 as
  ``0.0000001``), so a value and a text it was stored as have one digest. For a value with no non-integral number it
  is exactly ``json.dumps``'s text, which keeps FORMAT 1's unit digests. A lone surrogate, an exponent beyond
  ±``MAX_EXPONENT`` or containers nested deeper than ``MAX_DEPTH`` make it ``NotCanonical`` (a ValueError).
  C is the text a digest is taken of, not a way to store a value: 238.0 and 1e16 read back from it as integers.
  Store a value as ``json.dumps`` writes it, which keeps each float a float.
- ``digest(value)``, D(v): the lowercase hex SHA-256 of C(v)'s UTF-8, a sync unit's digest.
- ``read(text)``: what ``json.loads(text)`` reads with its defaults (``strict``: whitespace is space, tab, newline
  and return alone; no raw control character in a string; no ``01``, ``+1``, ``.5``, ``1.`` or BOM; no integer of
  more than 4300 digits; NaN and the infinities read; the last of a repeated key wins), but a non-integral number
  kept as its literal (``Literal``), never a float; a ValueError when the text isn't JSON.
- ``stored_hash(text)``, H(text), for ``versions.raw`` and ``songs.lyrics_json``: None for None; D of what ``read``
  reads; else (not JSON, or not canonicalizable) the SHA-256 of the text's own bytes,
  ``text.encode("utf-8", "surrogatepass")``.

The standard library alone.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from json.encoder import encode_basestring
from typing import Any

MAX_EXPONENT = 1000  # a literal's written exponent beyond ±this: not canonicalizable
MAX_DEPTH = 512  # arrays and objects nested deeper: not canonicalizable (json.loads's own limit is its C stack)

_NUMBER = re.compile(r"(-?)(0|[1-9][0-9]*)(?:\.([0-9]+))?(?:[eE]([-+]?)([0-9]+))?")
_SURROGATE = re.compile("[\ud800-\udfff]")


class NotCanonical(ValueError):
    """A value, or a stored text read, that has no canonical text: a lone surrogate, an exponent beyond
    ±``MAX_EXPONENT``, or nesting deeper than ``MAX_DEPTH``."""


class Literal(str):
    """A non-integral number as a text wrote it (``"238.0"``, ``"1E2"``), which ``read`` keeps and ``dumps`` writes
    by the decimal rule."""


def decimal(literal: str) -> str:
    """The exact decimal value of a JSON number literal, plain: no exponent, trailing fractional zeros dropped, then
    a trailing ``.``, ``-0`` written ``0``; computed on its digits, never through a float or a bounded precision
    (``1E2`` → ``100``, ``1e-7`` → ``0.0000001``, ``-0.0`` → ``0``). ``NotCanonical`` when its exponent is beyond
    ±``MAX_EXPONENT``; a ValueError when it is no JSON number."""
    m = _NUMBER.fullmatch(literal)
    if not m:
        raise ValueError(f"not a JSON number: {literal!r}")
    sign, whole, fraction, exponent_sign, exponent = m.groups()
    fraction = fraction or ""
    shift = 0
    if exponent is not None:
        written = exponent.lstrip("0")
        if len(written) > len(str(MAX_EXPONENT)) or int(written or "0") > MAX_EXPONENT:
            raise NotCanonical(f"an exponent beyond ±{MAX_EXPONENT}: {literal[:40]!r}")
        shift = -int(written or "0") if exponent_sign == "-" else int(written or "0")
    digits = whole + fraction
    point = len(whole) + shift  # where the decimal point falls among the digits
    if point <= 0:
        digits, point = "0" * (1 - point) + digits, 1
    elif point > len(digits):
        digits += "0" * (point - len(digits))
    integer = digits[:point].lstrip("0") or "0"
    fraction = digits[point:].rstrip("0")
    text = integer + "." + fraction if fraction else integer
    return "0" if text == "0" else sign + text


def _float(x: float) -> str:
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    return decimal(float.__repr__(x))


def _string(s: str) -> str:
    if _SURROGATE.search(s):
        raise NotCanonical(f"a lone surrogate: {ascii(s)[:40]}")
    return encode_basestring(s)


def _key(key: Any) -> str:
    """A key as ``json.dumps`` writes one that isn't a string."""
    if isinstance(key, str):
        return key
    if key is True:
        return "true"
    if key is False:
        return "false"
    if key is None:
        return "null"
    if isinstance(key, float):
        return json.dumps(key)
    if isinstance(key, int):
        return int.__repr__(key)
    raise TypeError(f"keys must be str, int, float, bool or None, not {type(key).__name__}")


def _write(value: Any, out: list[str], depth: int) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, Literal):
        out.append(decimal(value))
    elif isinstance(value, str):
        out.append(_string(value))
    elif isinstance(value, int):
        out.append(int.__repr__(value))
    elif isinstance(value, float):
        out.append(_float(value))
    elif isinstance(value, (list, tuple, dict)):
        if depth >= MAX_DEPTH:
            raise NotCanonical(f"nested deeper than {MAX_DEPTH}")
        if isinstance(value, dict):
            out.append("{")
            for i, (key, item) in enumerate(sorted(value.items(), key=lambda kv: kv[0])):
                if i:
                    out.append(",")
                out.append(_string(_key(key)))
                out.append(":")
                _write(item, out, depth + 1)
            out.append("}")
        else:
            out.append("[")
            for i, item in enumerate(value):
                if i:
                    out.append(",")
                _write(item, out, depth + 1)
            out.append("]")
    else:
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def dumps(value: Any) -> str:
    """C(value): see the module's docstring."""
    out: list[str] = []
    _write(value, out, 0)
    return "".join(out)


def digest(value: Any) -> str:
    """D(value): the lowercase hex SHA-256 of C(value)'s UTF-8."""
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def read(text: str) -> Any:
    """``json.loads(text)``, its non-integral numbers kept as their ``Literal``s; a ValueError when it isn't JSON."""
    return json.loads(text, parse_float=Literal)


def stored_hash(text: str | None) -> str | None:
    """H(text): D of the JSON ``text`` holds, else the SHA-256 of its own bytes; None for None."""
    if text is None:
        return None
    try:
        return digest(read(text))
    except (ValueError, RecursionError):  # not JSON (NotCanonical among them), or deeper than json.loads reads
        return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()
