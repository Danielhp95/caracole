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
   ``sheet.json``, the Guitar Pro file) and its lyrics on the phone byte for byte.
3. Computer off: serve stopped.
4. Phone, phase 2: songs searched, added (Get it, Request with Fetch now and without) and removed (R and C1), and not
   one request sent: the computer's port refuses. The song Get it added is the one search.py finds for the query,
   under the identity key caracole gives its names.
5. Computer: serve again; ``caracole add`` adds three songs, and C1's and C2's ``[transpose]`` change.
6. Phone, phase 3: the comparison lists each side's adds, C2 theirs, C1 a conflict and R's units the phone's; applied
   with C1 kept as the phone has it (removed), nothing left.
7. Both: the phone's units (``DIR/phone/phone-state.json``) are the computer's, unit by unit; the computer lacks C1
   and R, and its wanted.txt holds the phone's adds; phase 4 compares once more and finds no difference.

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

import pytest
from helpers.e2e_library import (
    ADDS,
    CHANGED,
    CHINESE,
    CHOSEN,
    HARMONICA,
    LABEL,
    LYRICS,
    REMOVED,
    REPO,
    SONGS,
    Computer,
    build,
    free_port,
    stop,
    wait_until_answering,
)

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
    pytest.importorskip("helpers.phone_render", reason="waiting on phone-render: tests/helpers/phone_render.py")
    from caracole.normalize import identity_key

    computer = served[0]
    library = computer.cfg().library_dir
    before = {p: p.read_bytes() for p in library.rglob("*") if p.is_file()}
    units = computer.units()
    pages = computer.phone_pages([identity_key(*CHINESE), identity_key(*HARMONICA)], tmp_path / "reference")
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


def phone(phase: int, server: str, dir: Path) -> dict:
    """The phone's phase ``phase`` (PhoneScenarioTest on the JVM, one Gradle run), against the computer at
    ``server``; what it wrote as it ended, DIR/phone/phase-N.json."""
    logs = dir / "logs"
    logs.mkdir(exist_ok=True)
    log = logs / f"phone-{phase}.log"
    command = ["nix", "develop", "./android", "-c", "gradle", "-p", "android", "--console=plain", ":e2e:test",
               "--rerun", f"-Pcaracole.e2e.phase={phase}", f"-Pcaracole.e2e.server={server}",
               f"-Pcaracole.e2e.dir={dir}"]
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
