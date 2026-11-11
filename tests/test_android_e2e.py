"""The goal end to end (docs/android_port.md, the Android plan's §9): 20 songs changed on the computer reach the phone;
with the computer off the phone searches and changes things; a sync lists the differences, the owner's choices apply,
and both libraries end unit for unit equal.

The computer is tests/helpers/e2e_library.py's (``build``, and real ``caracole serve`` processes over it); the phone is
the Kotlin side's ``server.Phone`` over ``DIR/phone/``, kept between its phases, each a run of android/e2e's
PhoneScenarioTest on the JVM::

    nix develop ./android -c gradle -p android :e2e:test --rerun -Pcaracole.e2e.phase=N \\
        -Pcaracole.e2e.server=http://127.0.0.1:P -Pcaracole.e2e.dir=DIR

which drives the phone's App as its WebView would and writes ``DIR/phone/phase-N.json`` as it ends (what it counted,
and what the next step needs of it). The steps, as the plan numbers them:

1. Computer: the library built with no request, its index exported, ``caracole serve`` on 127.0.0.1:P.
2. Phone, phase 1: the index imported (``GET /api/peer/index``), the mirror synced, the Sync tab's compare and apply:
   the computer's 20 songs on the phone, with their digests, the goal's changes in ``phone_overrides``, each mirrored
   sheet served, and an indexed song found that the library hasn't got; here, every table of the index export holding
   on the phone what it holds in the file, and every file the computer keeps (each sheet's ``sheet.txt`` and
   ``sheet.json``, the Guitar Pro file, the harmonica tab) and its lyrics on the phone byte for byte.
3. Computer off: serve stopped.
4. Phone, phase 2: songs searched, added (Get it, Request with Fetch now and without) and removed (R and C1), and not
   one request sent: the computer's port refuses. The song Get it added is the one search.py finds for the query,
   under the identity key caracole gives its names.
5. Computer: serve again; ``caracole add`` adds three songs, and C1's and C2's ``[transpose]`` change.
6. Phone, phase 3: the comparison lists each side's adds, C2 theirs, C1 a conflict and R's units the phone's; applied
   with C1 kept as the phone has it (removed), nothing left.
7. Both: the phone's units (``DIR/phone/phone-state.json``) are the computer's, unit by unit; the computer lacks C1
   and R, and its wanted.txt holds the phone's adds; phase 4 compares once more and finds no difference.
8. Computer off; the fake sites server up (tests/helpers/fake_sites.py, scenario ``lookups``, on 127.0.0.1, in this
   process). Phone, phase 5 (``-Pcaracole.e2e.sites``): the lookups phase, §9's M4 goal: Get it, Fetch now and Fetch
   them look songs up against the fake sites, each request routed there by RoutedTransport; the song new to both sides
   keeps its sheet, its timed lyrics and its card's sheet.txt, served; a bare tab comes from its artist's page; each
   lookup within lookup_requests, every lookup within lookup_per_hour; no URL robots.txt closes asked, nor a redirect
   to one followed (an error, never a miss); every URL asked one the scenario answers (``known``); no request but to
   the fake server, which counted every one the phone sent, each with the user agent the computer gave it; a 403
   cools Ultimate Guitar down on the phone, the song never not found. Among them the pages phase's (milestone 5's
   check): Get it on a song whose charts sing Chinese words (its other version kept beside its sheet) and on one with
   a harmonica tab on harptabs.com, whose pages the phone makes itself (the sheets' viewers and .cho, the kept
   version's page, the tab's page, info.json), each recorded and served as it wrote it, the Chinese sheet's with each
   character's reading; and /api/search's progression finds that song by what it plays.
9. Computer: the first of those songs looked up there too, against the same sites (``Computer.against``): it asks
   the very URLs the phone's Get it asked, in the same order; and its caracole.toml changed (``change_settings``).
10. Computer: serve again. Phone, phase 6: the next sync lists the phone's lookups as its own and the song looked up
   on both sides a conflict (how many, and where the two differ, reported in DIR/lookups-report.json and on stdout:
   the plan's §11 Q2), takes that one from the computer and gives the rest; the units equal on both sides; the phone
   takes the computer's settings (its kv ``phone:settings`` is politeness.py's ``settings_document`` of the
   computer's config); nothing of either side's politeness crosses (the owner's choice: Ultimate Guitar cools on the
   phone alone, and the computer's events and the kv records of its pace, health and lookups are as they were); and
   the index pages the phone read (its artist page of the bare tab) reach the computer's index, merged by the job its
   ``POST /peer/index`` queued; the pages the phone made of the songs it gave are still its own, and those of the
   song it took (looked up and rendered again on the computer) forgotten, the mirror's serving at its unit's digest.
11. The pages phase's end: the computer, which took those songs, copied, and Python's build of the phone's pages of
   them run on the copy (tests/helpers/phone_render.py, ``Computer.phone_pages``): the phone wrote the same pages,
   each byte for byte, info.json too, and recorded them as Python does (each page's SHA-256, size and unit, the
   song's unit and script, and what its sheet plays: kv ``render:files:``, ``render:<id>:phone`` and
   ``render:progressions:``).
12. Phone, phase 7, the computer off: a new build of the app (PhoneRender's build stamp another) makes the pages
   owed again over the scenario's library, a lookup queued as the render job starts runs between two songs, before
   the job ends, and the phone's own pages of step 11's songs, which the mirror holds the computer's of now, are
   forgotten for the mirror's; its time over the library, printed (the plan's §9, the M5 check), with a pass's that
   makes every song's pages itself, as a phone holding none of the computer's (no mirror).
13. Computer: serve again, the fake sites up. Phone, phase 8: milestone 6's changes, each made on the phone through its
   own route (the plan's §9, the M6 check): a songbook made, a song's key set in it, a song moved and the songbook
   renamed, its songbook.html the phone's own and served; a song matched only uncertainly, its review answered with
   a candidate; a version kept beside a sheet (one tab page from the fake sites); a version made a song's own (Export
   PDF's ``mine=1``); a Guitar Pro file shared to the app, filed for its song. The next sync lists each change's unit
   as the phone's and nothing else, and gives them all; the units equal on both sides; and the computer's readers read
   each back (``made_on_the_phone_read_back``): songbooks.toml's songbook under its new name, in the order the phone
   moved its songs to, with the key it set, and its page rendered; overrides.toml's ``[match]`` of the pick and the
   song matched by it; the kept version's file; overrides.toml's ``[version]`` as the phone wrote it; the Guitar Pro
   file filed, its bytes the phone's.

Beside the scenario, the computer's own library is checked: the goal's changes and no request sent; the Chinese
sheet's page carries each character's reading and its words in either script, and Oh! Susanna's harmonica tab its
page; and the phone's reference pages are made on a copy of the computer, which stays as it was.

The module also checks ``python -m tests.helpers.e2e_library serve DIR PORT``, which the device tests run.

Slow (a library rendered by the real chordpro, Gradle runs) and skipped unless ``CARACOLE_ANDROID_E2E=1``; run it in
nix develop, in one process: ``CARACOLE_ANDROID_E2E=1 nix develop -c pytest -q -n 0 tests/test_android_e2e.py``. On a
pytest-xdist worker it skips itself, so that its library and its Gradle runs are never made once a worker.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from helpers.e2e_library import (
    ADDS,
    CHANGED,
    CHINESE,
    CHOSEN,
    HARMONICA,
    LABEL,
    LOOKUPS,
    LYRICS,
    REMOVED,
    REPO,
    SONGS,
    Computer,
    Pages,
    build,
    free_port,
    stop,
    wait_until_answering,
)
from helpers.fake_sites import FakeSites

pytestmark = [
    pytest.mark.slow,
    pytest.mark.android_e2e,
    pytest.mark.skipif(os.environ.get("CARACOLE_ANDROID_E2E") != "1",
                       reason="the phone end to end: CARACOLE_ANDROID_E2E=1, in nix develop, with -n 0"),
    pytest.mark.skipif("PYTEST_XDIST_WORKER" in os.environ,
                       reason="the phone end to end runs in one process: pytest -n 0 tests/test_android_e2e.py"),
]

PHASE_TIMEOUT = 1800  # s: a Gradle run, its first one compiling the phone


@pytest.fixture(autouse=True)
def _chordpro():
    if shutil.which("chordpro") is None:
        pytest.skip("no chordpro on PATH: run it in nix develop")


def read(url: str) -> dict:
    """``url``'s JSON, asked straight (no proxy), as the phone asks: no browser's headers."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=60) as answer:
        assert answer.status == 200
        return json.load(answer)


def kept(database: Path) -> dict[str, str]:
    """The files a caracole database records as kept, the computer's or the phone's: each one's SHA-256 by its path
    in the library."""
    conn = sqlite3.connect(database)
    try:
        return dict(conn.execute("SELECT path, sha256 FROM files"))
    finally:
        conn.close()


def counts(database: Path, tables: list[str]) -> dict[str, int]:
    conn = sqlite3.connect(database)
    try:
        return {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
    finally:
        conn.close()


def refused(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=5):
            return False
    except ConnectionRefusedError:
        return True


# --- the serve command, for the device tests --------------------------------------------------------------------


def _serve_command(dir: Path, port: int, log: Path) -> subprocess.Popen:
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in (str(REPO / "src"), os.environ.get("PYTHONPATH"))
                                                       if p))
    with log.open("ab") as out:
        return subprocess.Popen([sys.executable, "-m", "tests.helpers.e2e_library", "serve", str(dir), str(port)],
                                cwd=REPO, env=env, stdout=out, stderr=subprocess.STDOUT)


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """``python -m tests.helpers.e2e_library serve DIR PORT`` on a DIR that holds nothing: the library built, its
    index exported, caracole serve answering; its Computer and its port."""
    dir = tmp_path_factory.mktemp("served") / "e2e"
    port = free_port()
    log = dir.parent / "serve.log"
    server = _serve_command(dir, port, log)
    try:
        wait_until_answering(f"http://127.0.0.1:{port}", server, log, timeout=600)
        yield Computer(dir), port, log
    finally:
        stop(server)


def test_serve_builds_the_library_exports_its_index_and_serves_it_on_every_address(served):
    computer, port, log = served
    state = read(f"http://127.0.0.1:{port}/api/peer/state")
    assert state["format"] == 3 and state["name"] == "Computer"
    assert sum(unit.startswith("song/") for unit in state["units"]) == len(SONGS) == 20
    # 0.0.0.0, for an emulator: another address of this machine's than 127.0.0.1 answers too.
    assert read(f"http://127.0.0.2:{port}/api/peer/state")["units"] == state["units"]
    offline = read(f"http://127.0.0.1:{port}/api/offline")
    assert {e["path"] for e in offline["files"] if e["path"].endswith("/sheet.html")} == {
        f"{artist}/{title}/sheet.html" for artist, title, _, _ in SONGS}
    with sqlite3.connect(computer.index) as index:  # caracole index export's file
        assert index.execute("SELECT COUNT(*) FROM caracole_export").fetchone()[0] >= 1
        assert index.execute("SELECT COUNT(*) FROM ug_index").fetchone()[0] > 20
    said = log.read_text()
    assert f"building the library in {computer.root}" in said and f"{LABEL} beside the library's name" in said


def test_serve_serves_a_library_built_before_as_it_is(served, tmp_path):
    computer, port, _ = served
    other = free_port()
    log = tmp_path / "again.log"
    server = _serve_command(computer.dir, other, log)
    try:
        wait_until_answering(f"http://127.0.0.1:{other}", server, log, timeout=120)
        again = read(f"http://127.0.0.1:{other}/api/peer/state")
    finally:
        stop(server)
    first = read(f"http://127.0.0.1:{port}/api/peer/state")
    assert (again["server"], again["units"]) == (first["server"], first["units"])  # the same database, not built
    assert "as built before" in log.read_text()


def test_the_library_holds_the_goals_changes_and_asked_no_site(served):
    from caracole import db
    from caracole.normalize import identity_key
    from caracole.overrides import load_overrides

    computer = served[0]
    cfg = computer.cfg()
    overrides = load_overrides(cfg.overrides_file)
    changed = {identity_key(*song) for song in CHANGED}
    assert set(overrides.version) == set(overrides.transpose) == changed
    assert set(overrides.pin) == {identity_key(*song) for song in CHOSEN}
    conn = db.connect(cfg.db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 20
        for artist, title, _, _ in SONGS:  # each song's sheet kept, and its pages rendered by chordpro
            folder = cfg.library_dir / artist / title
            assert {"sheet.txt", "sheet.json", "sheet.html", "sheet.pdf"} <= {p.name for p in folder.iterdir()}
        # sheet.txt and sheet.json kept, each a file of the sheet's version, as a UG fetch keeps them.
        pairs = conn.execute("SELECT COUNT(DISTINCT version_id), COUNT(*) FROM files "
                             "WHERE name IN ('sheet.txt', 'sheet.json')").fetchone()
        assert tuple(pairs) == (20, 40)
        for artist, title in LYRICS:
            assert (cfg.library_dir / artist / title / "lyrics.txt").read_text(encoding="utf-8").startswith("Made-up")
        for table in ("ug_index", "gtptabs_index", "lacuerda_index"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0, table
        for record in ("ug:sitemaps", "gtptabs:sitemaps", "lacuerda:index:pages"):  # what an index merge compares
            assert db.kv_get(conn, record), record
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0  # no request counted
        assert conn.execute("SELECT COUNT(*) FROM kv WHERE key LIKE 'http:last_request:%'").fetchone()[0] == 0
    finally:
        conn.close()
    assert not (cfg.cache_dir / "http").exists()  # every answer caracole got would be cached there
    assert (cfg.library_dir / "_songbooks" / "Campfire" / "songbook.pdf").is_file()
    assert (cfg.library_dir / "index.html").is_file()


def data_block(page: Path, name: str) -> dict:
    """A page's JSON data block ``name`` (``<script type="application/json" id="NAME">``)."""
    found = re.search(rf'<script type="application/json" id="{name}">(.*?)</script>', page.read_text("utf-8"),
                      re.DOTALL)
    assert found, f"no {name} data in {page}"
    return json.loads(found.group(1))


def test_the_chinese_sheet_carries_its_readings_and_a_harmonica_tab_its_page(served):
    from caracole import db
    from caracole.normalize import identity_key
    from caracole.render import FILES_KEY
    from caracole.songs import find_song

    cfg = served[0].cfg()
    # The Chinese song sings Chinese words: its page has each character's reading, its words in either script, and
    # its names; and the computer prints it in Traditional characters too.
    folder = cfg.library_dir / CHINESE[0] / CHINESE[1]
    song = data_block(folder / "sheet.html", "song")
    readings = [r for line in song["pinyin"] for r in (line or []) if r]
    assert readings and all(r.isalpha() for r in readings), song["pinyin"]
    assert "這是為測試編的歌詞" in json.dumps(song["hanzi"], ensure_ascii=False)
    assert (folder / "sheet (Traditional).pdf").is_file()
    # The harmonica tab: its page beside it, recorded as render.py records a viewer, and linked from the sheet's.
    folder = cfg.library_dir / HARMONICA[0] / HARMONICA[1]
    assert (folder / "harmonica-1.txt").is_file() and (folder / "harmonica-1.html").is_file()
    assert [t["page"] for t in data_block(folder / "sheet.html", "song")["harmonicaTabs"]] == ["harmonica-1.html"]
    conn = db.connect(cfg.db_path)
    try:
        tabbed = find_song(conn, identity_key(*HARMONICA))
        assert "harmonica-1.html" in db.kv_get_json(conn, f"{FILES_KEY}{tabbed.id}")
    finally:
        conn.close()


def test_the_phones_reference_pages_are_made_on_a_copy_of_the_computer(served, tmp_path):
    from caracole.normalize import identity_key

    computer = served[0]
    library = computer.cfg().library_dir
    before = {p: p.read_bytes() for p in library.rglob("*") if p.is_file()}
    units = computer.units()
    keys = [identity_key(*CHINESE), identity_key(*HARMONICA)]
    made = computer.phone_pages(keys, tmp_path / "reference")
    pages = made.pages
    assert set(made.records) == set(keys)
    for key in keys:  # what the phone records of a song it rendered: each page at the song unit's digest now
        record = made.records[key]
        assert {entry["unit"] for entry in record["files"].values()} == {record["phone"]["unit"]}
        assert record["phone"]["unit"] == units[f"song/{key}"][1] and record["progressions"]
    assert made.records[keys[0]]["phone"]["script"] and "script" not in made.records[keys[1]]["phone"]
    chinese, tabbed = (f"{a}/{t}" for a, t in (CHINESE, HARMONICA))
    assert {f"{chinese}/sheet.html", f"{chinese}/sheet.cho", f"{chinese}/info.json"} <= set(pages)
    assert {f"{tabbed}/sheet.html", f"{tabbed}/harmonica-1.html", f"{tabbed}/info.json"} <= set(pages)
    assert not any(path.endswith(".pdf") for path in pages)  # the phone makes none
    for path in (f"{chinese}/sheet.html", f"{tabbed}/sheet.html"):
        page = pages[path].decode("utf-8")
        assert ".pdf" not in page.split('id="song">', 1)[1].split("</script>", 1)[0], path  # no PDF linked
    assert b'"pinyin":' in pages[f"{chinese}/sheet.html"]
    # The computer itself untouched, file for file and unit for unit.
    assert {p: p.read_bytes() for p in library.rglob("*") if p.is_file()} == before
    assert computer.units() == units


# --- the scenario -------------------------------------------------------------------------------------------------


def phone(phase: int, server: str, dir: Path, sites: str | None = None) -> dict:
    """The phone's phase ``phase`` (PhoneScenarioTest on the JVM, one Gradle run), against the computer at
    ``server``, its sites the fake sites at ``sites`` (every site refusing with none); what it wrote as it ended,
    DIR/phone/phase-N.json."""
    logs = dir / "logs"
    logs.mkdir(exist_ok=True)
    log = logs / f"phone-{phase}.log"
    command = ["nix", "develop", "./android", "-c", "gradle", "-p", "android", "--console=plain", ":e2e:test",
               "--rerun", f"-Pcaracole.e2e.phase={phase}", f"-Pcaracole.e2e.server={server}",
               f"-Pcaracole.e2e.dir={dir}", *([f"-Pcaracole.e2e.sites={sites}"] if sites else [])]
    with log.open("w") as out:
        done = subprocess.run(command, cwd=REPO, stdout=out, stderr=subprocess.STDOUT, timeout=PHASE_TIMEOUT,
                              check=False)
    said = log.read_text(errors="replace")
    assert done.returncode == 0, f"the phone's phase {phase} failed:\n{said[-8000:]}"
    result = dir / "phone" / f"phase-{phase}.json"
    assert result.is_file(), f"the phone ran no phase {phase} (no {result}):\n{said[-4000:]}"
    return json.loads(result.read_text(encoding="utf-8"))


def test_the_phone_and_the_computer_sync_end_to_end(tmp_path):
    from caracole.normalize import identity_key

    # 1. The computer, its index exported, and serve.
    computer = build(tmp_path / "e2e")
    dir = computer.dir
    with sqlite3.connect(computer.export_index()) as index:
        assert index.execute("SELECT COUNT(*) FROM ug_index").fetchone()[0] > 20
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    with computer.serving(port):
        # 2. The phone takes the computer's library and index.
        first = phone(1, url, dir)
    assert first["songs"] == 20 and first["requests"] > 0  # what it counted is the requests it sent
    scenario = computer.scenario()
    tables = scenario["index_tables"]
    with sqlite3.connect(computer.index) as index:
        exported = {name for (name,) in index.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert set(tables) == exported - {"caracole_export", "kv"}
    assert first["indexes"] == counts(computer.index, tables)  # each site's rows, imported whole
    computers, phones = kept(computer.cfg().db_path), kept(dir / "phone" / "caracole.sqlite")
    assert phones == computers  # every kept file, at its path, with its bytes' hash
    assert {Path(path).name for path in computers} == {"sheet.txt", "sheet.json", "guitar-1.gp", "harmonica-1.txt"}
    for path, sha in phones.items():
        assert hashlib.sha256((dir / "phone" / "library" / path).read_bytes()).hexdigest() == sha, path
    for artist, title in LYRICS:
        words = Path(artist, title, "lyrics.txt")
        assert (dir / "phone" / "library" / words).read_bytes() == (computer.cfg().library_dir / words).read_bytes()

    # 3. The computer off; 4. the phone on its own.
    assert refused(port)
    away = phone(2, url, dir)
    assert away["requests"] == 0
    added = {song["key"]: song for song in away["added"]}
    assert len(added) == 3
    # Get it's song, under the key caracole gives search.py's names of it; and the two asked for by name.
    assert scenario["index"]["key"] in added
    assert {identity_key(s["artist"], s["title"]) for s in scenario["requests"]} < set(added)

    # 5. The computer changes things meanwhile; 6. the phone syncs with it.
    with computer.serving(port):
        computer.after_the_phone_left()
        phone(3, url, dir)

        # 7. Both libraries, unit by unit.
        state = json.loads((dir / "phone" / "phone-state.json").read_text(encoding="utf-8"))
        theirs = {unit: (u["label"], u["digest"]) for unit, u in state["units"].items()}
        assert theirs == computer.units()
        songs = computer.songs()
        assert not {identity_key(*song) for song in REMOVED.values()} & set(songs)  # C1 and R, gone
        assert {identity_key(*song) for song in ADDS} | set(added) <= set(songs)
        lines = computer.cfg().wanted_file.read_text(encoding="utf-8").splitlines()
        for song in added.values():
            assert any(line.startswith(f"{song['artist']} - {song['title']}") for line in lines), song

        last = phone(4, url, dir)
    assert last["differences"] == []  # nothing more: the phone and the computer agree

    # 8. The computer off, the phone looks songs up against the fake sites; 9. the computer too, and its settings.
    assert refused(port)
    lookups = scenario["lookups"]
    events = computer.events()
    with FakeSites(LOOKUPS) as fake:
        five = phone(5, url, dir, sites=fake.url)
        both = lookups["songs"]["get_it"]["search"]  # as the phone's Get it asked for it: its row's pick
        computer.against(fake.url, "get", "--ug", both["ug"], f"{both['artist']} - {both['title']}")
        asked = fake.requests
        computer.change_settings()
    looked_up(five, asked, lookups, computer)
    assert computer.events()[:len(events)] == events
    politeness = computer.politeness()  # the computer's own, its lookup's included: no sync may change it

    # 10. The next sync.
    with computer.serving(port):
        six = phone(6, url, dir)
        state = json.loads((dir / "phone" / "phone-state.json").read_text(encoding="utf-8"))
        assert {unit: (u["label"], u["digest"]) for unit, u in state["units"].items()} == computer.units()
        merges = merged(computer)  # the phone's index pages, merged before the server stops
    assert computer.politeness() == politeness  # nothing of the phone's politeness crossed, nor changed the computer's
    synced_after_the_lookups(five, six, merges, lookups, computer, dir)

    # 11. The pages the phone made of its lookups, held to Python's for the same inputs.
    pages_as_python_makes_them(five, computer, dir, tmp_path / "reference")

    # 12. A new build: the render job makes the pages again, a lookup queued meanwhile running between two songs.
    seven = phone(7, url, dir)
    assert seven["songs"] >= 20 and seven["requests"] == 0, seven
    print("the re-render at a new build:", json.dumps({k: seven[k] for k in ("seconds", "songs", "detail", "alone")},
                                                      ensure_ascii=False))

    # 13. Milestone 6's changes, made on the phone, given at the next sync and read back on the computer.
    with FakeSites(LOOKUPS) as fake, computer.serving(port):
        eight = phone(8, url, dir, sites=fake.url)
        state = json.loads((dir / "phone" / "phone-state.json").read_text(encoding="utf-8"))
        assert {unit: (u["label"], u["digest"]) for unit, u in state["units"].items()} == computer.units()
    made_on_the_phone_read_back(eight, computer)


def phone_made(dir: Path, keys: list[str]) -> Pages:
    """The pages the phone made of the songs of identity keys ``keys`` and what it recorded of them, read from
    DIR/phone/ as ``Computer.phone_pages`` reads the reference's: each page its kv ``render:files:<id>`` names and each
    song's info.json, by its path in the library (the song's folder, where its kept files are), and its records."""
    from caracole.progressions import KV as PROGRESSIONS
    from caracole.render import FILES_KEY
    from helpers.phone_render import phone_key

    home = dir / "phone"
    conn = sqlite3.connect(home / "caracole.sqlite")
    try:
        def kv(key: str):
            row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
            return None if row is None else json.loads(row[0])

        pages, records, folders = {}, {}, {}
        for key in keys:
            (song_id,) = conn.execute("SELECT id FROM songs WHERE key = ?", (key,)).fetchone()
            (kept,) = conn.execute("SELECT path FROM files WHERE song_id = ? AND name = 'sheet.txt'",
                                   (song_id,)).fetchone()
            folder = Path(kept).parent
            folders[key] = folder.as_posix()
            files = kv(f"{FILES_KEY}{song_id}") or {}
            for name in [*sorted(files), "info.json"]:
                pages[(folder / name).as_posix()] = (home / "library" / folder / name).read_bytes()
            records[key] = {"files": files, "phone": kv(phone_key(song_id)),
                            "progressions": kv(f"{PROGRESSIONS}{song_id}")}
    finally:
        conn.close()
    return Pages(pages, records, folders)


def first_difference(mine: bytes, theirs: bytes) -> str:
    """Where two pages part, in words: the offset and a little of each from there."""
    at = next((i for i, (a, b) in enumerate(zip(mine, theirs)) if a != b), min(len(mine), len(theirs)))
    return (f"{len(mine)} and {len(theirs)} bytes, parting at {at}: the phone's {mine[max(0, at - 80):at + 160]!r}, "
            f"Python's {theirs[max(0, at - 80):at + 160]!r}")


def pages_as_python_makes_them(five: dict, computer: Computer, dir: Path, into: Path) -> None:
    """Step 11: the pages the phone made of the pages phase's songs (phase 5's ``pages``), and the records it kept of
    them, as tests/helpers/phone_render.py makes them on a copy of the computer once it took those songs: the same
    pages, each byte for byte (info.json too), recorded alike, the song's unit and script alike (never the build, the
    app's own), and what its sheet plays alike."""
    made = five["pages"]
    keys = [song["key"] for song in made.values()]
    theirs = computer.phone_pages(keys, into)
    mine = phone_made(dir, keys)
    assert sorted(mine.pages) == sorted(theirs.pages)  # every page the phone made, and none Python wouldn't make
    for path, page in mine.pages.items():
        assert page == theirs.pages[path], f"{path}: {first_difference(page, theirs.pages[path])}"
    for key in keys:
        phone, python = mine.records[key], theirs.records[key]
        assert phone["files"] == python["files"], key
        assert {k: phone["phone"].get(k) for k in ("unit", "script")} == \
            {k: python["phone"].get(k) for k in ("unit", "script")}, key
        assert phone["progressions"] == python["progressions"], key
    # The pages the phase was for: the Chinese sheet's with its readings and its kept version's, the tab's page.
    chinese, tabbed = (made[role] for role in ("chinese", "harmonica"))
    assert {"sheet.html", "sheet.cho"} | {n for n in chinese["files"] if n.startswith("version-")} <= \
        set(mine.records[chinese["key"]]["files"]) and any(n.startswith("version-") for n in chinese["files"])
    assert {"sheet.html", "sheet.cho", "harmonica-1.html"} <= set(mine.records[tabbed["key"]]["files"])
    assert mine.folders == theirs.folders
    sheet = mine.pages[f"{mine.folders[chinese['key']]}/sheet.html"]
    readings = json.loads(re.search(rb'<script type="application/json" id="song">(.*?)</script>', sheet,
                                    re.DOTALL).group(1))["pinyin"]
    assert any(r for line in readings for r in (line or [])), "the Chinese sheet's readings"
    assert mine.records[chinese["key"]]["phone"].get("script")  # its sheet's words Chinese, for the cards' names
    assert five["progression"]["record"] == mine.records[chinese["key"]]["progressions"]
    print("the pages phase:", json.dumps({path: hashlib.sha256(page).hexdigest() for path, page in mine.pages.items()},
                                         ensure_ascii=False, indent=1))


def made_on_the_phone_read_back(eight: dict, computer: Computer) -> None:
    """Step 13: what phase 8 made on the phone, as the computer's readers read it once ``caracole peer take`` took
    its units (peer_sync.apply_units: songbook.put_songbook, overrides.put_song_entries, each kept file checked by
    its SHA-256): the songbook under its new name, its songs in the order the phone moved them to and the key it set;
    the review's pick as the song's ``[match]``, and the song matched by it; the version kept beside its sheet; the
    version made the song's own, its ``[version]`` as the phone wrote it; and the Guitar Pro file shared to the phone,
    filed for its song, its bytes the phone's."""
    from caracole import db
    from caracole.inbox import guitar_files
    from caracole.overrides import load_overrides, song_entries
    from caracole.songbook import load_songbooks, songbooks_file
    from caracole.songs import find_song

    cfg = computer.cfg()
    overrides = load_overrides(cfg.overrides_file)
    said = eight["songbook"]
    books = {book.name: book for book in load_songbooks(songbooks_file(cfg.library_dir))}
    assert said["name"] in books and "From the phone" not in books, list(books)
    book = books[said["name"]]
    assert list(book.texts) == said["songs"], book
    setting = {song.text: song.setting for song in book.songs}[said["set"]]
    assert setting is not None and setting.key == said["key"], book
    assert (cfg.library_dir / "_songbooks" / said["name"] / "songbook.html").is_file()  # rendered there too

    conn = db.connect(cfg.db_path)
    try:
        review = eight["review"]
        assert song_entries(overrides, review["key"]).get("match") == review["pick"], song_entries(overrides,
                                                                                                    review["key"])
        song = find_song(conn, review["key"])
        assert song is not None and f"{song.match_artist_key}/{song.match_song_key}" == review["pick"], song
        assert not song.review, song

        kept = eight["kept"]
        song = find_song(conn, kept["key"])
        (path,) = conn.execute("SELECT path FROM files WHERE song_id = ? AND name = ?",
                               (song.id, f"version-{kept['tab']}.txt")).fetchone()
        assert (cfg.library_dir / path).is_file(), path

        mine = eight["mine"]
        assert song_entries(overrides, mine["key"]).get("version") == mine["version"], song_entries(overrides,
                                                                                                    mine["key"])

        shared = eight["guitar"]
        song = find_song(conn, shared["key"])
        files = guitar_files(conn, song.id)
        assert [f.name for f in files] == [shared["name"]], files
        assert hashlib.sha256((cfg.library_dir / files[0].path).read_bytes()).hexdigest() == shared["sha256"]
    finally:
        conn.close()
    print("milestone 6's changes:", json.dumps({k: eight[k] for k in ("songbook", "review", "kept", "mine", "guitar")},
                                               ensure_ascii=False))


def merged(computer: Computer, timeout: float = 300) -> dict[int, str]:
    """The index merges the computer's caracole serve queued for the phone's pushes (``POST /peer/index``), once each
    is over: their states by id. The phone's sync waits for its push's merge already when the computer counts its
    indexes; this waits too, so that no merge is cut short by the server stopping (INTERRUPTED)."""
    import time

    end = time.monotonic() + timeout
    while True:
        states = computer.index_merges()
        if states and all(state not in ("queued", "running") for state in states.values()):
            return states
        assert time.monotonic() < end, f"the computer's index merges, still: {states}"
        time.sleep(0.5)


def looked_up(five: dict, asked: list[dict], lookups: dict, computer: Computer) -> None:
    """Phase 5's lookups, as the fake sites saw them: ``asked``, every request they answered the phone, then the
    computer's own lookup of the Get it song, which asks what the phone's Get it asked."""
    from caracole.config import DEFAULT_PROVIDERS

    mine, theirs = asked[:five["sites"]], asked[five["sites"]:]  # the phone's; the computer's lookup came after
    assert five["sites"] == five["requests"] > 0  # every request the phone sent, and each one the fake sites'
    assert not [r for r in mine if r["closed"]]
    assert not [r for r in mine if not r["known"]]  # no URL the computer's caracole wouldn't ask, read as a miss
    assert {r["user_agent"] for r in mine} == {computer.cfg().user_agent}  # the computer's, taken at a sync
    for name, sent in five["asked"].items():
        assert sent, f"{name} asked no site"
        for provider, n in sent.items():
            assert n <= DEFAULT_PROVIDERS[provider].lookup_requests, (name, provider, n)
    blocked = lookups["songs"]["blocked"]["tabs"]
    assert [r["status"] for r in mine if r["url"] in blocked] == [403]
    closed = lookups["songs"]["closed"]
    assert {r["status"] for r in mine if r["url"] in closed["tabs"]} == {301}
    assert not [r for r in asked if r["url"] in closed["closed"]]  # the redirect robots.txt closes, never followed
    assert len(five["added"]) == len(lookups["songs"]) == 7  # each of the scenario's songs looked up once
    harmonica = lookups["songs"]["harmonica"]["harp"]
    assert [r["status"] for r in mine if r["url"] == harmonica] == [200]  # the tab's page, read once on harptabs.com
    # The computer, its cache as empty of these pages as the phone's was, asks the very URLs the phone's Get it did.
    assert [r["url"] for r in theirs] == five["urls"]["get it"]


def synced_after_the_lookups(five: dict, six: dict, merges: dict[int, str], lookups: dict, computer: Computer,
                             dir: Path) -> None:
    """Phase 6's sync, as the computer has it after: the phone's lookups its, its settings the phone's, the phone's
    block its own, the phone's index reads merged into the computer's index; the conflicts reported."""
    from caracole import db
    from caracole.index_transfer import PAGES
    from caracole.politeness import settings_document

    songs = computer.songs()
    assert {song["key"] for song in five["added"]} <= set(songs)
    assert six["settings"] == settings_document(computer.cfg())  # the computer's settings, the phone's now
    ug = computer.provider("ug")
    assert ug is None or ug.get("cooldown_until") is None, ug  # the phone's block stayed the phone's
    assert not set(lookups["songs"]["blocked"]["tabs"]) & {url for _, url in computer.events()}
    # The pages the phone's lookups stored (the bare tab's artist page), pushed and merged by the queued job.
    artist = urlsplit(lookups["songs"]["artist_page"]["artist_page"]).path  # /artist/thomas_moore_70001
    assert any(read.startswith("ug:") and urlsplit(read[3:]).path == artist for read in five["reads"]), five["reads"]
    assert list(merges.values()) == ["done"], merges  # one push, its merge over: Merged
    conn = db.connect(computer.cfg().db_path)
    try:
        for read in five["reads"]:
            site, _, page = read.partition(":")  # Reads' site:page, index_transfer.PAGES' rows of it
            table, column = PAGES[site].tables[0]
            assert conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (page,)).fetchone()[0], read
    finally:
        conn.close()
    report = {"conflicts": six["conflicts"], "differ": six["differ"], "reads": five["reads"],
              "asked": five["asked"]}
    (dir / "lookups-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                                             encoding="utf-8")
    print("the lookups phase:", json.dumps(report, ensure_ascii=False, indent=1))
    assert six["conflicts"] == 1  # the song looked up on both sides between two syncs
