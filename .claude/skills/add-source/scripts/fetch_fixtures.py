#!/usr/bin/env python3
"""Fetch a few pages of a source once, politely, as test fixtures.

    python3 fetch_fixtures.py https://example.com tests/fixtures/<site>/ /robots.txt /sitemap.xml /a/page [...]

Each path is asked with caracole's own user agent, robots.txt checked first (robots.txt itself is always fetched and
saved), at least 6 s apart or the site's Crawl-delay, and saved under the folder by its path (`/a/page` →
`a_page.html`; a gzipped sitemap is saved unzipped, `.xml`). Stops at the first 403, 429 or challenge page.

Fixtures are trimmed and scrambled after this (scramble_fixture.py): keep the markup the parser reads, cut
repeated cards to a few, and never commit a whole tab, lyric or prose text verbatim.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _polite import Blocked, Polite, gunzip_if_needed  # noqa: E402


def file_name(path: str, body: bytes) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", path.strip("/")) or "index"
    name = re.sub(r"\.gz$", "", name)
    if "." not in name.rsplit("_", 1)[-1]:
        name += ".xml" if body.lstrip()[:5] == b"<?xml" else ".html"
    return name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site")
    parser.add_argument("out", type=Path)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--max-requests", type=int, default=12)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    site = Polite(args.site, max_requests=args.max_requests)
    if site.robots_answer.status == 200:
        (args.out / "robots.txt").write_bytes(site.robots_answer.body)
        print(f"saved robots.txt (Crawl-delay {site.robots.crawl_delay}, pace {site.delay:g} s)")
    for path in args.paths:
        if path.strip("/") == "robots.txt":
            continue
        try:
            answer = site.get(path)
        except PermissionError as closed:
            print(f"skipped: {closed}")
            continue
        except Blocked as blocked:
            print(f"BLOCKED: {blocked}. Nothing more asked.")
            return 1
        body = gunzip_if_needed(answer.body)
        name = file_name(path, body)
        (args.out / name).write_bytes(body)
        print(f"saved {name}: {answer.status}, {len(body):,} bytes")
    print(f"{site.made} requests made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
