#!/usr/bin/env python3
"""Every place the newest source plugs into caracole, from the code itself: what a new source mirrors.

    python3 touchpoints.py [MODEL] [--repo PATH] [--ref REF] [--tests]

MODEL is a source already built, `gametabs` by default (then `harptabs`). Greps the repo at REF (default
`origin/main`, so a dirty checkout doesn't mislead) for the name, case-insensitively, and prints each file with its
first matching lines, grouped by area in the order a build goes. Files named after the model (gametabs.py, …) are the
modules to write anew; the rest are shared modules to extend. With `--tests`, the tests too.

The list is always as current as the code: when a new touch point appears (a new page, a new manifest), the next
run shows it, which a hand-kept checklist can't.
"""

from __future__ import annotations

import argparse
import collections
import subprocess
import sys

AREAS = [
    ("The rules (read first)", ("AGENTS.md",)),
    ("The provider's own modules (write anew)", ("src/caracole/{m}",)),
    ("Settings, robots and politeness", ("src/caracole/config.py", "src/caracole/http.py", "src/caracole/logs.py",
                                         "src/caracole/health.py")),
    ("Schema and per-song state", ("src/caracole/db.py", "src/caracole/songs.py", "src/caracole/site_index.py")),
    ("The nightly step", ("src/caracole/pipeline.py", "src/caracole/report.py")),
    ("Files kept, picks, removal", ("src/caracole/inbox.py", "src/caracole/overrides.py", "src/caracole/removal.py",
                                    "src/caracole/files.py")),
    ("A lookup (caracole get)", ("src/caracole/get.py", "src/caracole/commands/get.py")),
    ("Commands", ("src/caracole/commands/",)),
    ("Search", ("src/caracole/search.py",)),
    ("Marks and the library page", ("src/caracole/icons.py", "src/caracole/library_page.py",
                                    "src/caracole/library_assets/")),
    ("caracole serve", ("src/caracole/web/",)),
    ("Viewer and render", ("src/caracole/viewer/", "src/caracole/render.py")),
    ("Nix and deployment", ("nix/", "flake.nix")),
    ("Docs", ("docs/", "README.md")),
    ("Tests", ("tests/",)),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model", nargs="?", default="gametabs")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--ref", default="origin/main")
    parser.add_argument("--tests", action="store_true")
    parser.add_argument("--lines", type=int, default=3, help="matching lines shown per file")
    args = parser.parse_args()
    grep = subprocess.run(["git", "-C", args.repo, "grep", "-n", "-i", "-I", args.model, args.ref, "--"],
                          capture_output=True, text=True)
    if grep.returncode not in (0, 1):
        print(grep.stderr, file=sys.stderr)
        return 2
    hits: dict[str, list[str]] = collections.defaultdict(list)
    prefix = f"{args.ref}:"
    for line in grep.stdout.splitlines():
        line = line.removeprefix(prefix)
        path, number, text = line.split(":", 2)
        hits[path].append(f"{number}: {text.strip()[:150]}")
    shown: set[str] = set()
    for title, roots in AREAS:
        if title == "Tests" and not args.tests:
            continue
        roots = tuple(r.format(m=args.model) for r in roots)
        files = sorted(p for p in hits if p not in shown and any(p == r or p.startswith(r) for r in roots))
        if not files:
            continue
        print(f"\n## {title}")
        for path in files:
            shown.add(path)
            new = args.model in path.rsplit("/", 1)[-1]
            mark = "  ← the model's own module" if new else ""
            print(f"- {path}  ({len(hits[path])} lines){mark}")
            for hit in hits[path][:args.lines]:
                print(f"    {hit}")
    rest = sorted(p for p in hits if p not in shown and (args.tests or not p.startswith("tests/")))
    if rest:
        print("\n## Elsewhere")
        for path in rest:
            print(f"- {path}  ({len(hits[path])} lines)")
    print(f"\n{len(hits)} files name {args.model} at {args.ref}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
