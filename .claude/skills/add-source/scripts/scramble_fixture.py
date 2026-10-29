#!/usr/bin/env python3
"""Scramble the prose of a fixture so no tab, lyric or note is committed verbatim, keeping what the parser reads.

    python3 scramble_fixture.py IN [-o OUT] [--keep REGEX ...] [--keep-first N] [--digits] [--scripts]

Markup is never touched: every tag stays as written, even one spread over several lines, and so does the content of
`<script>` and `<style>` (a page's JSON data, which a parser reads; pass `--scripts` to scramble those too, then check
the JSON still parses). Between tags, a line stays as written when it matches a `--keep` pattern (a line of holes, a
section's name, a legend line) or is among the first `--keep-first`; on every other line each letter becomes another
of the same case, and with `--digits` each digit another digit. Lengths, spacing and punctuation stay, so columns
still line up and a parser sees the same shapes. The result is the same every run (a line's letters are scrambled
by a seed of its number), so a fixture's diff stays quiet.

This is the rule caracole's fixtures already follow (tests/test_viewer_harptab.py's docstring, tests/fixtures/).
Read the result once: a word the parser keys on ("Composer:", a heading) may need a `--keep`.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path

LOWER, UPPER, DIGITS = "abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "0123456789"
SEGMENT = re.compile(r"(<script\b.*?</script>|<style\b.*?</style>|<[^>]*>)", re.S | re.I)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("-o", "--out", type=Path)
    parser.add_argument("--keep", action="append", default=[], help="a regex: lines it matches stay as written")
    parser.add_argument("--keep-first", type=int, default=0)
    parser.add_argument("--digits", action="store_true", help="scramble digits too")
    parser.add_argument("--scripts", action="store_true", help="scramble <script> and <style> contents too")
    args = parser.parse_args()
    keeps = [re.compile(k) for k in args.keep]
    text = args.source.read_text(encoding="utf-8")
    lines = text.split("\n")
    kept = {n for n, line in enumerate(lines)
            if n < args.keep_first or not line.strip() or any(k.search(line) for k in keeps)}
    rngs: dict[int, random.Random] = {}

    def swap(ch: str, line: int) -> str:
        rng = rngs.setdefault(line, random.Random(line))
        if ch.isalpha():
            return rng.choice(UPPER if ch.isupper() else LOWER)
        if args.digits and ch.isdigit():
            return rng.choice(DIGITS)
        return ch

    out: list[str] = []
    line = 0
    for part in SEGMENT.split(text):
        is_markup = part.startswith("<") and part.endswith(">")
        is_code = is_markup and re.match(r"<(script|style)\b", part, re.I) is not None
        if is_markup and not (is_code and args.scripts):
            out.append(part)
            line += part.count("\n")
            continue
        chars = []
        for ch in part:
            if ch == "\n":
                line += 1
                chars.append(ch)
            elif line in kept or (is_code and ch in "<>/"):
                chars.append(ch)
            else:
                chars.append(swap(ch, line))
        out.append("".join(chars))
    result = "".join(out)
    if args.out:
        args.out.write_text(result, encoding="utf-8")
    else:
        sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
