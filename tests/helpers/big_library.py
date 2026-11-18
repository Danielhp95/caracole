"""A library of 2,000 songs, built with no request, and how index.html's list does with it on a phone (stage 1e of the
library page's redesign: docs/superpowers/specs/2026-11-17-library-page-redesign-design.md, "Measurements before
building")::

    from helpers.big_library import build, measure

    page = build(tmp_path / "big")   # DIR/computer/ (as e2e_library.py's), and its index.html, returned
    numbers = measure(page)          # the page in a phone-sized Chromium, the CPU slowed 4x: a dict of numbers

``build(folder, songs=2000, seed=7)`` makes the library as e2e_library.py makes its computer, with caracole's own
functions, no request, no chordpro and no clock (every time is ``NOW``): wanted.txt synced, each song found, with a
UG sheet kept as the fetch keeps one (``sheet.txt``, ``sheet.json``), ``sheet.html`` and ``sheet.pdf`` as stand-ins,
a key, every fifth song a Guitar Pro file and every ninth a harmonica tab, info.json, and the page written
(``todo.write_pages``). The artists: 55 % of them have one song, the others 2 to 15, one has 150 (``songs * 3 / 40``,
30 at least); 5 % of the titles and artists are Chinese; every 400th title is 120 characters long. The same ``seed``
gives the same bytes.

``measure(page, ...)`` opens ``page`` in ``Browser`` (390 x 844, touch, ``cpu`` times slower: Chromium's
``Emulation.setCPUThrottlingRate``) and answers:

- ``drawn_ms``: the navigation's start to the body losing ``drawing`` (drawn.js), ``fcp_ms``: first contentful paint;
- ``ScriptDuration``, ``LayoutDuration``, ``RecalcStyleDuration`` (ms), ``LayoutCount``, ``Nodes``, ``JSHeapUsedSize``
  (bytes): ``Performance.getMetrics`` once the page is drawn;
- ``scroll``: to the end of the list, 800 px a frame: ``frames``, the frame times' ``p50_ms``, ``p95_ms``, ``max_ms``,
  ``over_50ms`` (frames longer than that) and ``long_tasks`` (tasks over 50 ms the browser reported);
- ``open_ms``: a line's chevron in the middle of the list clicked, to the next frame;
- ``type_ms``: "a" typed in the search box, from its input event to the second frame after it.

Run from the repository's root, in ``nix develop``::

    python -m tests.helpers.big_library measure [--songs N] [--src PATH] [--runs N] [--out FILE]

builds in a temporary folder and prints the numbers as JSON, each the median of ``--runs`` (3) loads of the page.
``--src`` builds the page with another checkout's ``src/`` (the commit before a stage merged, to show what it gained).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
TESTS = REPO / "tests"

NOW = datetime(2026, 10, 22, 3, 0, tzinfo=UTC)
FETCHED = "2026-10-22T03:00:00Z"
FIRST_TAB = 7000001
KEYS = ("C", "G", "D", "A", "E", "Am", "Em", "Dm", "F", "Bm", "Bb", "F#m")
FIRST = ("Alder", "Briar", "Cedar", "Dale", "Ember", "Fern", "Garnet", "Hazel", "Indigo", "Juniper", "Kestrel", "Linden",
         "Marlow", "Nettle", "Orchid", "Pine", "Quill", "Rowan", "Sorrel", "Thistle", "Umber", "Vesper", "Willow",
         "Yarrow")
LAST = ("Ashdown", "Bellweather", "Crane", "Dunmore", "Eastley", "Fairbairn", "Gallow", "Harrow", "Ingram", "Jessop",
        "Kirkby", "Larkin", "Moorcroft", "Northam", "Oakes", "Pemberton", "Quarrell", "Radley", "Stowe", "Thorne",
        "Underhill", "Vance", "Wren", "Yeats")
ADJECTIVES = ("Quiet", "Golden", "Broken", "Slow", "Last", "Paper", "Winter", "Hollow", "Bright", "Lonely", "Silver",
              "Rusted", "Gentle", "Wild", "Distant", "Burning", "Sleepy", "Crooked", "Faded", "Open")
NOUNS = ("River", "Lantern", "Harbour", "Morning", "Train", "Orchard", "Letter", "Window", "Garden", "Storm", "Bridge",
         "Season", "Mirror", "Hotel", "Highway", "Island", "Kitchen", "Ghost", "Summer", "Road")
HAN = "月星风雨山河花梦云海夜光心爱歌故乡春秋雪火天地路桥灯影"
LONG_EVERY = 400  # a title 120 characters long
CHINESE_EVERY = 20  # 5 % of the titles are Chinese


def plan(songs: int, rng: random.Random) -> list[tuple[str, str]]:
    """The library's songs as (artist, title), in wanted.txt's order: artist sizes as the module says, every name
    unique."""
    big = max(30, songs * 3 // 40)
    artists = max(1, round((songs - big) / (0.55 + 0.45 * 8.5)))
    while True:  # ones: 55 % of the artists; the others 2 to 15 songs each, which together fill the library
        ones = round(0.55 * artists)
        many = artists - ones
        rest = songs - big - ones
        if many and 2 * many <= rest <= 15 * many:
            break
        artists += 1 if rest > 15 * many else -1
        if artists < 2:
            raise ValueError(f"{songs} songs are too few for the library's shape")
    sizes = [2] * many
    spare = rest - 2 * many
    while spare:
        n = rng.randrange(many)
        if sizes[n] < 15:
            sizes[n] += 1
            spare -= 1
    sizes = [big, *sizes, *([1] * ones)]
    names = [f"{f} {last}" for f in FIRST for last in LAST]
    rng.shuffle(names)
    if len(names) < len(sizes):
        names += [f"{n} {i}" for i, n in enumerate(names * (len(sizes) // len(names) + 1))][:len(sizes)]
    rows: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for a, size in enumerate(sizes):
        artist = names[a]
        if a and rng.random() < 0.05:
            artist = "".join(rng.choice(HAN) for _ in range(rng.choice((2, 3))))
        for _ in range(size):
            while True:
                title = f"{rng.choice(ADJECTIVES)} {rng.choice(NOUNS)}"
                if rng.random() < 0.3:
                    title += f" of the {rng.choice(NOUNS)}"
                if (artist, title) not in seen:
                    break
            seen.add((artist, title))
            rows.append((artist, title))
    rng.shuffle(rows)
    for n in range(CHINESE_EVERY - 1, songs, CHINESE_EVERY):
        title = "".join(rng.choice(HAN) for _ in range(rng.choice((2, 3, 4, 5))))
        rows[n] = (rows[n][0], title)
    for n in range(3, songs, LONG_EVERY):
        title = rows[n][1]
        while len(title) < 120:
            title += f" and the {rng.choice(ADJECTIVES)} {rng.choice(NOUNS)}"
        rows[n] = (rows[n][0], title[:120].rstrip())
    return rows


def _suite_on_the_path() -> None:
    for path in (str(TESTS), str(REPO)):
        if path not in sys.path:  # the suite's helpers, when run as python -m tests.helpers.big_library
            sys.path.insert(0, path)


def build(folder: Path, songs: int = 2000, *, seed: int = 7) -> Path:
    """Build ``songs`` songs in a library under ``folder`` (which must not exist yet: the computer is
    ``folder/computer/``, as e2e_library.py's) and return the path of its written index.html."""
    _suite_on_the_path()
    from caracole import db
    from caracole.library import keep_file, song_dir, write_info
    from caracole.normalize import identity_key
    from caracole.overrides import Overrides
    from caracole.songs import find_song, get_song, refresh_status, update_song
    from caracole.todo import write_pages
    from caracole.ug.page import strip_markup
    from caracole.versions import upsert_version
    from caracole.wanted import append_wanted, sync_wanted
    from helpers.e2e_library import Computer, chart, keep_harmonica, tab_url, write_config
    from helpers.guitar import SYNTHETIC, keep_guitar
    from helpers.ug_pages import version_dict

    rows = plan(songs, random.Random(seed))
    computer = Computer(folder)
    write_config(computer)
    cfg = computer.cfg()
    cfg.library_dir.mkdir(parents=True)
    for artist, title in rows:
        append_wanted(cfg.wanted_file, artist, title)
    conn = db.connect(cfg.db_path)
    try:
        sync_wanted(conn, cfg.wanted_file, NOW)
        for n, (artist, title) in enumerate(rows):
            song = find_song(conn, identity_key(artist, title))
            assert song is not None, f"{artist} - {title} wasn't added"
            tab, key = FIRST_TAB + n, KEYS[n % len(KEYS)]
            raw = version_dict(tab, song=title, artist=artist, version=1, rating=4.5, votes=50, tonality_name=key,
                               tab_url=tab_url(artist, title, tab))
            vid = upsert_version(conn, provider="ug", tab_id=str(tab), song_id=song.id, slot="sheet", kind="chords",
                                 rating=4.5, votes=50, version=1, label=None, url=raw["tab_url"], raw=raw, now=FETCHED)
            content = chart(title, ("Am", "G", "C", "D"))
            keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.txt",
                      data=strip_markup(content).encode("utf-8"), rank=1)
            doc = {"version": raw, "content": content, "url": raw["tab_url"], "meta": {}}
            keep_file(conn, cfg.library_dir, song=song, version_id=vid, name="sheet.json",
                      data=(json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), rank=1)
            folder_ = song_dir(cfg.library_dir, song)
            (folder_ / "sheet.html").write_bytes(f"<html>{n}</html>".encode())  # stand-ins, as library_songs.py's
            (folder_ / "sheet.pdf").write_bytes(f"%PDF-1.4 {n}".encode())
            if n % 5 == 0:
                keep_guitar(conn, cfg, song, SYNTHETIC.read_bytes(), name="guitar-1.gp", tab=str(8000000 + n))
            if n % 9 == 0:
                keep_harmonica(conn, cfg, song)
            update_song(conn, song.id, status="found", ug_checked_at=FETCHED)
            refresh_status(conn, song.id, ignored=False)
            write_info(conn, cfg.library_dir, get_song(conn, song.id))
        _, page = write_pages(conn, cfg, Overrides(), NOW)
        conn.commit()
    finally:
        conn.close()
    return page


# --- measuring it -----------------------------------------------------------------------------------------------

# Run in the page before any of its own scripts: the timings the measurement reads back from window.__m.
INJECTED = r"""
(() => {
  const m = window.__m = { drawn: null, fcp: null, long: [], typed: null, opened: null };
  const seen = () => {
    if (m.drawn === null && document.body && !document.body.classList.contains("drawing")) m.drawn = performance.now();
  };
  new MutationObserver(seen).observe(document, { subtree: true, attributes: true, childList: true });
  try {
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) if (e.name === "first-contentful-paint") m.fcp = e.startTime;
    }).observe({ type: "paint", buffered: true });
    new PerformanceObserver((list) => { for (const e of list.getEntries()) m.long.push(e.startTime); })
      .observe({ type: "longtask", buffered: true });
  } catch (e) { /* an observer the browser lacks: the numbers stay null */ }
  const after = (event, key, frames) => addEventListener(event, (e) => {
    const start = e.timeStamp;
    let left = frames;
    const frame = () => { if (--left > 0) requestAnimationFrame(frame); else m[key] = performance.now() - start; };
    requestAnimationFrame(frame);
  }, true);
  after("input", "typed", 2);
  after("click", "opened", 1);
})();
"""
SCROLL = r"""
new Promise((resolve) => {
  const times = [], long = window.__m.long.length;
  let last = null;
  const step = (now) => {
    if (last !== null) times.push(now - last);
    last = now;
    const end = document.scrollingElement.scrollHeight - innerHeight;
    if (scrollY >= end - 1 || times.length > 5000) {
      times.sort((a, b) => a - b);
      const at = (p) => times[Math.min(times.length - 1, Math.floor(times.length * p))] || 0;
      return resolve({ frames: times.length, p50_ms: at(0.5), p95_ms: at(0.95), max_ms: times[times.length - 1] || 0,
                       over_50ms: times.filter((t) => t > 50).length, long_tasks: window.__m.long.length - long });
    }
    scrollBy(0, 800);
    requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
})
"""


def measure(page: Path, *, width: int = 390, height: int = 844, mobile: bool = True, cpu: int = 4) -> dict:
    """The page's numbers in a Chromium of ``width`` x ``height`` CSS pixels, ``mobile`` (touch), the CPU ``cpu`` times
    slower (the module's docstring lists them)."""
    _suite_on_the_path()
    from helpers import browser as driven

    driven.marked = True  # a run outside pytest opens pages as @in_chromium tests do
    with driven.Browser(Path(tempfile.gettempdir()), width=width, height=height, mobile=mobile, timeout=300) as b:
        b.send("Performance.enable")
        b.send("Emulation.setCPUThrottlingRate", rate=cpu)
        b.send("Page.addScriptToEvaluateOnNewDocument", source=INJECTED)
        b.open(page.resolve().as_uri())
        if not b.wait("window.__m.drawn !== null", 300):
            raise driven.BrowserError("the page never finished drawing")
        if not b.wait("window.__m.fcp !== null", 5):
            raise driven.BrowserError("the page painted no first contentful paint")
        asked = {m["name"]: m["value"] for m in b.send("Performance.getMetrics")["metrics"]}
        out = {"drawn_ms": b.js("window.__m.drawn"), "fcp_ms": b.js("window.__m.fcp")}
        for name in ("ScriptDuration", "LayoutDuration", "RecalcStyleDuration"):
            out[name] = asked[name] * 1000
        for name in ("LayoutCount", "Nodes", "JSHeapUsedSize"):
            out[name] = asked[name]
        out["scroll"] = b.js(SCROLL)
        b.js("scrollTo(0, 0)")
        middle = b.js("""(() => { const c = document.querySelectorAll("article.line > .line-more");
                        if (!c.length) return false; c[c.length >> 1].setAttribute("data-measure", ""); return true; })()""")
        if not middle:
            raise driven.BrowserError("the page has no line with a chevron")
        b.js("document.querySelector('[data-measure]').scrollIntoView({ block: 'center' })")
        b.js("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
        b.click("[data-measure]")
        if not b.wait("window.__m.opened !== null", 30):
            raise driven.BrowserError("the chevron opened nothing")
        out["open_ms"] = b.js("window.__m.opened")
        b.js("scrollTo(0, 0); document.querySelector('#q').focus()")
        b.type("a")
        if not b.wait("window.__m.typed !== null", 60):
            raise driven.BrowserError("typing in the search box drew nothing")
        out["type_ms"] = b.js("window.__m.typed")
    return out


def median(runs: list[dict]) -> dict:
    """Each number of ``runs`` (the same shape) as the median of that number over them."""
    first = runs[0]
    return {k: median([r[k] for r in runs]) if isinstance(v, dict) else statistics.median(r[k] for r in runs)
            for k, v in first.items()} if isinstance(first, dict) else first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tests.helpers.big_library", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("measure", help="build the library and print how its page does on a phone, as JSON")
    one.add_argument("--songs", type=int, default=2000)
    one.add_argument("--src", type=Path, help="build the page with this checkout's src/")
    one.add_argument("--runs", type=int, default=3, help="loads of the page; each number is their median")
    one.add_argument("--out", type=Path, help="also write the JSON here")
    built = sub.add_parser("build", help="build the library in FOLDER and print its index.html's path")
    built.add_argument("folder", type=Path)
    built.add_argument("--songs", type=int, default=2000)
    args = parser.parse_args(argv)
    if args.command == "build":
        print(build(args.folder, args.songs))
        return 0
    with tempfile.TemporaryDirectory(prefix="big-library-") as tmp:
        folder = Path(tmp) / "lib"
        if args.src:  # the library's code is that checkout's, the measuring this one's
            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join(p for p in (str(args.src.resolve()), env.get("PYTHONPATH")) if p)
            done = subprocess.run([sys.executable, "-m", "tests.helpers.big_library", "build", str(folder), "--songs",
                                   str(args.songs)], env=env, cwd=REPO, capture_output=True, text=True, check=False)
            if done.returncode:
                raise SystemExit(f"building with {args.src} failed:\n{done.stdout}\n{done.stderr}")
            page = Path(done.stdout.strip().splitlines()[-1])
        else:
            page = build(folder, args.songs)
        numbers = median([measure(page) for _ in range(args.runs)])
    text = json.dumps(numbers, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
