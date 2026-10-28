"""Migrations apply whole or not at all, after a backup; a newer database is refused."""

import sqlite3

import pytest

from caracole import db

NOW = db.SCHEMA_VERSION  # the schema this caracole makes
NEXT = NOW + 1


@pytest.fixture
def current(tmp_path):
    """A database at this caracole's schema version, holding one kv row."""
    path = tmp_path / "state" / "caracole.sqlite"
    c = db.connect(path)
    db.kv_set(c, "run:last", "[]")
    c.close()
    return path


@pytest.fixture
def newer(monkeypatch):
    """Pretend this caracole knows one schema version more; returns a setter for its migration script."""
    monkeypatch.setattr(db, "SCHEMA_VERSION", NEXT)

    def script(sql: str) -> None:
        monkeypatch.setitem(db._MIGRATIONS, NEXT, sql)

    return script


def columns(path, table):
    """The table's column names and the database's user_version."""
    c = sqlite3.connect(path)
    try:
        names = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
        return names, c.execute("PRAGMA user_version").fetchone()[0]
    finally:
        c.close()


def test_a_migration_that_fails_midway_changes_nothing(current, newer):
    newer("ALTER TABLE songs ADD COLUMN capo INTEGER;\nALTER TABLE songs ADD COLUMN capo INTEGER;")
    with pytest.raises(sqlite3.OperationalError, match="duplicate column"):
        db.connect(current)
    cols, version = columns(current, "songs")
    assert "capo" not in cols and version == NOW
    # Fixed, the migration then applies on the next start, and nothing still holds the database.
    newer("ALTER TABLE songs ADD COLUMN capo INTEGER;")
    db.connect(current).close()
    cols, version = columns(current, "songs")
    assert "capo" in cols and version == NEXT


def test_the_database_is_backed_up_before_a_migration(current, newer):
    newer("ALTER TABLE kv ADD COLUMN at TEXT;")
    db.connect(current).close()
    backup = current.with_name(f"caracole.sqlite.v{NOW}.bak")
    cols, version = columns(backup, "kv")
    assert version == NOW and cols == ["key", "value"]
    b = sqlite3.connect(backup)
    assert b.execute("SELECT value FROM kv WHERE key = 'run:last'").fetchone()[0] == "[]"
    b.close()


# A migration long enough for every other connection opened with it to read the version before it: a column added
# (twice, it fails), and a table of a million rows.
SLOW = ("ALTER TABLE kv ADD COLUMN at TEXT;\n"
        "CREATE TABLE pad AS WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 1000000) "
        "SELECT x FROM n;")


def migrated_once(path):
    """The database is at the next version, migrated once, its backup whole and alone."""
    cols, version = columns(path, "kv")
    assert cols == ["key", "value", "at"] and version == NEXT
    backup = path.with_name(f"caracole.sqlite.v{NOW}.bak")
    cols, version = columns(backup, "kv")
    assert cols == ["key", "value"] and version == NOW
    b = sqlite3.connect(backup)
    assert b.execute("SELECT value FROM kv WHERE key = 'run:last'").fetchone()[0] == "[]"
    b.close()
    assert sorted(p.name for p in path.parent.iterdir() if p.name.endswith(".bak") or ".bak." in p.name) == [
        backup.name]  # nothing half-written left beside it


def test_connections_opened_at_once_migrate_once_and_each_opens_the_database(current, newer):
    # caracole serve opens a connection a request, in threads of its own: after an upgrade, a page and its first
    # poll, or two devices, open the database at the same moment. One migrates; the others wait for it, then open it.
    import threading

    newer(SLOW)
    start = threading.Barrier(6)
    said = []

    def opens():
        start.wait()
        try:
            db.connect(current).close()
            said.append("ok")
        except Exception as e:  # noqa: BLE001 (what each said is the test)
            said.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=opens) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert said == ["ok"] * 6, said
    migrated_once(current)


CHILD = """
import sys, time
from pathlib import Path
from caracole import db
db.SCHEMA_VERSION = int(sys.argv[2])
db._MIGRATIONS[db.SCHEMA_VERSION] = sys.argv[3]
while time.time() < float(sys.argv[4]):  # both processes start at the same moment
    pass
try:
    db.connect(Path(sys.argv[1])).close()
    print("ok")
except Exception as e:
    print(type(e).__name__, e)
"""


@pytest.mark.slow
def test_two_caracoles_starting_at_once_migrate_once(current):
    # The nightly run starts as caracole serve opens the database, right after an upgrade: one migrates, the other
    # waits for it, and neither fails.
    import os
    import subprocess
    import sys
    import time
    from pathlib import Path

    from conftest import subprocess_pythonpath

    env = {"HOME": str(current.parent), "PATH": os.environ.get("PATH", ""),
           "PYTHONPATH": subprocess_pythonpath(Path(__file__).resolve().parents[1] / "src")}
    start = str(time.time() + 1.5)
    children = [subprocess.Popen([sys.executable, "-c", CHILD, str(current), str(NEXT), SLOW, start], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) for _ in range(2)]
    said = [child.communicate(timeout=120)[0].strip() for child in children]
    assert said == ["ok", "ok"], said
    migrated_once(current)


def test_a_new_database_needs_no_backup(tmp_path):
    db.connect(tmp_path / "caracole.sqlite").close()
    assert not list(tmp_path.glob("*.bak"))


def test_a_database_newer_than_this_caracole_is_refused(current):
    c = sqlite3.connect(current)
    c.execute(f"PRAGMA user_version = {NEXT}")
    c.close()
    with pytest.raises(db.DatabaseTooNew, match=rf"schema version {NEXT}.*caracole knows up to {NOW}") as e:
        db.connect(current)
    # A DatabaseError: `caracole add` reports it and keeps the line in wanted.txt.
    assert isinstance(e.value, sqlite3.DatabaseError)
    assert columns(current, "kv")[1] == NEXT


def test_after_a_rollback_the_refusal_names_the_copy_saved_before(current, newer, monkeypatch):
    newer("ALTER TABLE kv ADD COLUMN at TEXT;")
    db.connect(current).close()
    monkeypatch.setattr(db, "SCHEMA_VERSION", NOW)  # the older caracole runs again
    with pytest.raises(db.DatabaseTooNew, match=rf"restore caracole\.sqlite\.v{NOW}\.bak"):
        db.connect(current)


def test_a_version_1_database_gains_the_gtptabs_index_and_keeps_its_songs(tmp_path):
    # As caracole 0.1 left it before gtptabs.com: schema 1, with a song in it.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript(db._MIGRATIONS[1] + "\nPRAGMA user_version = 1;")
    old.execute(
        "INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) "
        "VALUES ('blur/song-2', 'Blur', 'Song 2', '[\"Blur\"]', 'x', 'x', 'x')"
    )
    old.commit()
    old.close()

    db.connect(path).close()

    cols, version = columns(path, "gtptabs_index")
    assert version == NOW
    assert cols == ["path", "artist_path", "artist_key", "title_key", "base_key", "sitemap"]
    c = sqlite3.connect(path)
    assert c.execute("SELECT key FROM songs").fetchall() == [("blur/song-2",)]
    c.close()
    assert columns(path.with_name("caracole.sqlite.v1.bak"), "gtptabs_index") == ([], 1)


def test_a_version_2_database_gains_the_musescore_index_and_keeps_its_gtptabs_rows(tmp_path):
    # As the gtptabs.com caracole left it: schema 2, with a row of gtptabs.com's index.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript(db._MIGRATIONS[1] + db._MIGRATIONS[2] + "\nPRAGMA user_version = 2;")
    old.execute("INSERT INTO gtptabs_index VALUES ('tabs/2/blur.html', 'tabs/2/blur.html', 'blur', '', '', '1')")
    old.commit()
    old.close()

    db.connect(path).close()

    cols, version = columns(path, "musescore_index")
    assert version == NOW
    assert cols == ["page_id", "path", "title_key", "sitemap"]
    c = sqlite3.connect(path)
    assert c.execute("SELECT artist_key FROM gtptabs_index").fetchall() == [("blur",)]
    c.close()
    assert columns(path.with_name("caracole.sqlite.v2.bak"), "musescore_index") == ([], 2)


def test_a_version_3_database_gains_the_removed_songs_and_keeps_its_songs(tmp_path):
    # As the MuseScore caracole left it: schema 3, with a song in it.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript(db._MIGRATIONS[1] + db._MIGRATIONS[2] + db._MIGRATIONS[3] + "\nPRAGMA user_version = 3;")
    old.execute(
        "INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) "
        "VALUES ('blur/song-2', 'Blur', 'Song 2', '[\"Blur\"]', 'x', 'x', 'x')"
    )
    old.commit()
    old.close()

    db.connect(path).close()

    cols, version = columns(path, "removed")
    assert version == NOW
    assert cols == ["key", "artist", "title", "source_ids", "removed_at"]
    c = sqlite3.connect(path)
    assert c.execute("SELECT key FROM songs").fetchall() == [("blur/song-2",)]
    c.close()
    assert columns(path.with_name("caracole.sqlite.v3.bak"), "removed") == ([], 3)


def test_a_version_3_database_gains_a_substring_index_of_its_ug_keys(tmp_path):
    # Typing into caracole serve's lookup searches 1.6 million index rows: a LIKE '%…%' scan of
    # both key columns took 0.4 s a pattern; the trigram index over the distinct keys answers in ms.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript(db._MIGRATIONS[1] + db._MIGRATIONS[2] + db._MIGRATIONS[3] + "\nPRAGMA user_version = 3;")
    old.executemany("INSERT INTO ug_index VALUES (?, ?, ?, 'chords', '1', 'x', '')",
                    [(1, "oasis", "wonderwall"), (2, "oasis", "wonderwall-acoustic"), (3, "radiohead", "creep")])
    old.commit()
    old.close()

    c = db.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] >= 4
    assert sorted(r[0] for r in c.execute("SELECT key FROM ug_keys")) == [
        "creep", "oasis", "radiohead", "wonderwall", "wonderwall-acoustic"]
    found = c.execute("SELECT key FROM ug_keys WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE key LIKE '%derwa%')")
    assert sorted(r[0] for r in found) == ["wonderwall", "wonderwall-acoustic"]
    c.close()


def test_a_version_4_database_gains_the_substring_index_and_keeps_its_removed_songs(tmp_path):
    # As the remove caracole left it: schema 4, with an index row and a removed song.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript("".join(db._MIGRATIONS[n] for n in (1, 2, 3, 4)) + "\nPRAGMA user_version = 4;")
    old.execute("INSERT INTO ug_index VALUES (1, 'oasis', 'wonderwall', 'chords', '1', 'x', '')")
    old.execute("INSERT INTO removed VALUES ('blur/song-2', 'Blur', 'Song 2', '{}', 'x')")
    old.commit()
    old.close()

    c = db.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == NOW
    assert sorted(r[0] for r in c.execute("SELECT key FROM ug_keys")) == ["oasis", "wonderwall"]
    found = c.execute("SELECT key FROM ug_keys WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE key LIKE '%derwa%')")
    assert [r[0] for r in found] == ["wonderwall"]
    assert [tuple(r) for r in c.execute("SELECT key, artist, title FROM removed")] == [("blur/song-2", "Blur", "Song 2")]
    c.close()
    assert columns(path.with_name("caracole.sqlite.v4.bak"), "ug_keys") == ([], 4)


def test_a_version_5_database_gains_the_lacuerda_index_and_keeps_its_ug_keys(tmp_path):
    # As the fast-lookup caracole left it: schema 5, with a song and an index row.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript("".join(db._MIGRATIONS[n] for n in (1, 2, 3, 4, 5)) + "\nPRAGMA user_version = 5;")
    old.execute("INSERT INTO ug_index VALUES (1, 'estopa', 'como-camaron', 'chords', '1', 'x', '')")
    old.execute(
        "INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) "
        "VALUES ('estopa/como-camaron', 'Estopa', 'Como Camarón', '[\"Estopa\"]', 'x', 'x', 'x')"
    )
    old.commit()
    old.close()

    c = db.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == NOW
    c.execute("INSERT INTO lacuerda_index (path, artist_slug, artist, artist_key, page) "
              "VALUES ('estopa/', 'estopa', 'Estopa', 'estopa', 'tabs/e/index0.html')")
    row = c.execute("SELECT title, title_key, songs, versions, acordes, popular FROM lacuerda_index").fetchone()
    assert tuple(row) == ("", "", 0, "", 0, None)
    assert [r[0] for r in c.execute("SELECT key FROM songs")] == ["estopa/como-camaron"]
    assert sorted(r[0] for r in c.execute("SELECT key FROM ug_keys")) == ["como-camaron", "estopa"]
    c.close()
    cols, _ = columns(path, "lacuerda_index")
    assert cols == ["path", "artist_slug", "artist", "artist_key", "title", "title_key", "songs", "versions",
                    "acordes", "popular", "page"]
    assert columns(path.with_name("caracole.sqlite.v5.bak"), "lacuerda_index") == ([], 5)


def test_a_version_6_database_gains_the_artist_pages_tabs_and_keeps_every_row(tmp_path):
    # As the LaCuerda-index caracole left it: schema 6, with a row in each table that holds the user's state.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript("".join(db._MIGRATIONS[n] for n in range(1, 7)) + "\nPRAGMA user_version = 6;")
    old.execute("INSERT INTO ug_index VALUES (1, 'oasis', 'wonderwall', 'chords', '1', 'x', 'oasis/wonderwall-chords-1')")
    old.execute(
        "INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) "
        "VALUES ('宋冬野/董小姐', '宋冬野', '董小姐', '[\"宋冬野\"]', 'x', 'x', 'x')"
    )
    old.execute("INSERT INTO removed VALUES ('宋冬野/斑马斑马', '宋冬野', '斑马斑马', '{}', '2026-10-20T00:00:00Z')")
    old.execute("INSERT INTO lacuerda_index (path, artist_slug, artist, artist_key, page) "
                "VALUES ('estopa/', 'estopa', 'Estopa', 'estopa', 'tabs/e/index0.html')")
    old.execute("INSERT INTO kv VALUES ('ug:artist_url:宋冬野', 'https://www.ultimate-guitar.com/artist/634073')")
    old.commit()
    tables = {t: old.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
              for t in ("songs", "ug_index", "ug_keys", "removed", "lacuerda_index", "kv")}
    old.close()

    c = db.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == NOW
    for table, rows in tables.items():
        assert [tuple(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY 1")] == rows, table
    assert c.execute("SELECT COUNT(*) FROM ug_artist_tabs").fetchone()[0] == 0
    c.close()
    cols, _ = columns(path, "ug_artist_tabs")
    assert cols == ["page", "tab_id", "type", "artist", "title", "label", "rating", "votes", "url", "artist_key",
                    "song_key", "artist_forms", "title_forms", "forms", "read_at"]
    assert columns(path.with_name("caracole.sqlite.v6.bak"), "ug_artist_tabs") == ([], 6)


def test_the_journal_trades_the_last_writes_before_a_power_cut_for_speed(conn):
    # WAL with synchronous NORMAL: a crash of the machine may lose the last commits, never the database.
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL


def test_a_savepoint_undoes_its_whole_block_and_nests(conn):
    def kv(key):
        return db.kv_get(conn, key)

    with db.savepoint(conn, "outer"):
        db.kv_set(conn, "a", "1")
        with pytest.raises(KeyboardInterrupt):  # any exception, a Ctrl-C too
            with db.savepoint(conn, "inner"):
                db.kv_set(conn, "b", "2")
                db.kv_set(conn, "a", "changed")
                raise KeyboardInterrupt
        assert conn.in_transaction and (kv("a"), kv("b")) == ("1", None)
        with db.savepoint(conn, "inner"):
            db.kv_set(conn, "c", "3")
    assert not conn.in_transaction
    assert (kv("a"), kv("b"), kv("c")) == ("1", None, "3")

    with pytest.raises(ValueError):
        with db.savepoint(conn, "outer"):
            db.kv_set(conn, "d", "4")
            db.kv_delete(conn, "a")
            raise ValueError
    assert not conn.in_transaction
    assert (kv("a"), kv("d")) == ("1", None)


def test_the_substring_index_follows_the_rows_a_sitemap_adds_or_renames(conn):
    from datetime import UTC, datetime

    from caracole.ug.index import upsert_rows

    when = datetime(2026, 10, 19, tzinfo=UTC)
    upsert_rows(conn, [(1, "oasis", "wonderwall", "chords", "oasis/wonderwall-chords-1")], "1", when)
    upsert_rows(conn, [(1, "oasis", "wonderwal", "chords", "oasis/wonderwal-chords-1"),
                       (2, "blur", "song-2", "chords", "blur/song-2-chords-2")], "1", when)

    def like(pattern):
        return sorted(r[0] for r in conn.execute(
            "SELECT key FROM ug_keys WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE key LIKE ?)", (pattern,)))

    assert like("%wonderwal%") == ["wonderwal", "wonderwall"]  # an old key stays: it matches no row
    assert like("%song-2%") == ["song-2"] and like("%blur%") == ["blur"]


def test_a_version_7_database_gains_its_artists_by_word_and_keeps_every_row(tmp_path):
    # As the artist-pages caracole left it: schema 7, with index rows and a song.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript("".join(db._MIGRATIONS[n] for n in range(1, 8)) + "\nPRAGMA user_version = 7;")
    old.executemany("INSERT INTO ug_index VALUES (?, ?, ?, 'chords', '1', 'x', '')",
                    [(1, "lynyrd-skynyrd", "free-bird"), (2, "lynyrd-skynyrd", "simple-man"), (3, "sam-grow", "skynyrd")])
    old.execute(
        "INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) "
        "VALUES ('oasis/wonderwall', 'Oasis', 'Wonderwall', '[\"Oasis\"]', 'x', 'x', 'x')"
    )
    old.commit()
    tables = {t: old.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in ("songs", "ug_index", "ug_keys")}
    old.close()

    c = db.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == NOW
    for table, rows in tables.items():
        assert [tuple(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY 1")] == rows, table

    def by_word(word):
        return [r[0] for r in c.execute("SELECT artist_key FROM ug_artists WHERE id IN "
                                        "(SELECT rowid FROM ug_artists_fts WHERE ug_artists_fts MATCH ?) "
                                        "ORDER BY artist_key", (f'"{word}"',))]

    assert by_word("skynyrd") == ["lynyrd-skynyrd"] and by_word("grow") == ["sam-grow"]
    # Every row added or re-keyed since files its artist too, and the words count the artists that hold them.
    c.execute("INSERT INTO ug_index VALUES (4, 'skynyrd-tribute', 'free-bird', 'chords', '1', 'x', '')")
    c.execute("UPDATE ug_index SET artist_key = 'sam-grow-band' WHERE tab_id = 3")
    assert by_word("skynyrd") == ["lynyrd-skynyrd", "skynyrd-tribute"] and by_word("band") == ["sam-grow-band"]
    words = dict(c.execute("SELECT term, doc FROM ug_artist_words WHERE term IN ('skynyrd', 'grow', 'lynyrd')"))
    assert words == {"skynyrd": 2, "grow": 1, "lynyrd": 1}  # sam-grow went with its one row, re-keyed
    c.close()
    assert columns(path.with_name("caracole.sqlite.v7.bak"), "ug_artists") == ([], 7)


def test_a_version_8_database_loses_everything_of_ultimate_guitars_guitar_pro_and_power_tab_files(tmp_path):
    # caracole uses no Guitar Pro or Power Tab file of Ultimate Guitar's: their versions go (a file filed for one is
    # the inbox's now: test_a_file_filed_from_the_inbox_for_a_pick_on_ultimate_guitar_stays_the_songs), the artist
    # pages' tabs of those types, and the index's rows of them, an artist with no other row too.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript("".join(db._MIGRATIONS[n] for n in range(1, 9)) + "\nPRAGMA user_version = 8;")
    old.execute(
        "INSERT INTO songs (id, key, artist, title, artists, added_at, created_at, updated_at) "
        "VALUES (1, 'oasis/wonderwall', 'Oasis', 'Wonderwall', '[\"Oasis\"]', 'x', 'x', 'x')"
    )
    old.executemany(
        "INSERT INTO versions (id, provider, tab_id, song_id, slot, kind, url, fetched_at, pick_rank, gone) "
        "VALUES (?, ?, ?, 1, ?, ?, '', 'x', ?, ?)",
        [(1, "ug", "101", "sheet", "chords", 1, 0),
         (2, "ug", "301", "guitar", "guitar-pro", 1, 0),
         (3, "ug", "303", "guitar", "power", 2, 0),
         (4, "ug", "302", "guitar", "guitar-pro", None, 1),
         (5, "ug", "305", "guitar", "guitar-pro", 3, 0),
         (6, "gtptabs", "9", "guitar", "guitar-pro", None, 0),
         (7, "inbox", "guitar-pro", "guitar", "guitar-pro", None, 0),
         (8, "ug", "401", "guitar", "tabs", 1, 0)],
    )
    old.executemany(
        "INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) "
        "VALUES (?, 1, ?, 'Oasis/Wonderwall/' || ?2, ?, 1, 'x')",
        [(1, "sheet.txt", "a"), (6, "guitar-1.gp5", "c"), (7, "guitar-2.gp", "d"), (8, "tab.txt", "e")],
    )
    old.executemany(
        "INSERT INTO ug_artist_tabs (page, tab_id, type, artist, title, url, artist_key, song_key, artist_forms, "
        "title_forms, forms, read_at) VALUES ('https://www.ultimate-guitar.com/artist/oasis_1', ?, ?, 'Oasis', "
        "'Wonderwall', '', 'oasis', 'wonderwall', 'oasis', 'wonderwall', 'oasis wonderwall', 'x')",
        [(101, "chords"), (305, "guitar-pro"), (303, "power"), (401, "tabs")],
    )
    old.executemany("INSERT INTO ug_index VALUES (?, ?, ?, ?, '1', 'x', '')",
                    [(101, "oasis", "wonderwall", "chords"), (305, "oasis", "wonderwall", "guitar-pro"),
                     (303, "oasis", "wonderwall", "power"), (601, "metallica", "one", "guitar-pro")])
    old.commit()
    files = old.execute("SELECT * FROM files ORDER BY id").fetchall()
    old.close()

    c = db.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == NOW >= 9
    assert [tuple(r) for r in c.execute("SELECT id, provider, kind, pick_rank FROM versions ORDER BY id")] == [
        (1, "ug", "chords", 1), (6, "gtptabs", "guitar-pro", None), (7, "inbox", "guitar-pro", None),
        (8, "ug", "tabs", 1)]
    assert [tuple(r) for r in c.execute("SELECT * FROM files ORDER BY id")] == [tuple(r) for r in files]
    assert [r[0] for r in c.execute("SELECT type FROM ug_artist_tabs ORDER BY tab_id")] == ["chords", "tabs"]
    assert [tuple(r) for r in c.execute("SELECT tab_id, type FROM ug_index ORDER BY tab_id")] == [(101, "chords")]
    assert [r[0] for r in c.execute("SELECT artist_key FROM ug_artists ORDER BY artist_key")] == ["oasis"]
    # The substring index keeps no key those rows alone had: a common word's keys are the rows'.
    assert [r[0] for r in c.execute("SELECT key FROM ug_keys ORDER BY key")] == ["oasis", "wonderwall"]
    assert c.execute("SELECT rowid FROM ug_keys_fts WHERE key LIKE '%etallic%'").fetchall() == []
    c.execute("INSERT INTO ug_keys_fts(ug_keys_fts) VALUES ('integrity-check')")
    c.close()
    assert columns(path.with_name("caracole.sqlite.v8.bak"), "versions")[1] == 8


def test_a_file_filed_from_the_inbox_for_a_pick_on_ultimate_guitar_stays_the_songs(tmp_path):
    # An older caracole filed a file dropped into _inbox/ under the song's pick on Ultimate Guitar: the pick goes,
    # and the file is the song's inbox file of its kind, as inbox.py files one now, joining the song's own when it
    # has one. Its Guitar Pro page, its mark and gtptabs.com's "one file a song" all read it still.
    from caracole.inbox import guitar_files

    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript("".join(db._MIGRATIONS[n] for n in range(1, 9)) + "\nPRAGMA user_version = 8;")
    old.executemany(
        "INSERT INTO songs (id, key, artist, title, artists, added_at, created_at, updated_at) "
        "VALUES (?, ?, 'A', ?, '[]', 'x', 'x', 'x')", [(1, "a/one", "One"), (2, "a/two", "Two")])
    old.executemany(
        "INSERT INTO versions (id, provider, tab_id, song_id, slot, kind, url, fetched_at, pick_rank) "
        "VALUES (?, ?, ?, ?, 'guitar', ?, '', 'x', ?)",
        [(1, "ug", "301", 1, "guitar-pro", 1), (2, "ug", "302", 1, "power", 2),
         (3, "inbox", "guitar-pro", 1, "guitar-pro", None), (4, "ug", "401", 2, "guitar-pro", 1)])
    old.executemany(
        "INSERT INTO files (id, version_id, song_id, name, path, sha256, kept_rank, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 1, 'x')",
        [(1, 1, 1, "guitar-1.gp5", "A/One/guitar-1.gp5", "a"),
         (2, 1, 1, "guitar-3.PTB", "A/One/guitar-3.PTB", "b"),  # a Power Tab file filed for a Guitar Pro pick
         (3, 2, 1, "guitar-2.ptb", "A/One/guitar-2.ptb", "c"),
         (4, 3, 1, "guitar-4.gp", "A/One/guitar-4.gp", "d"),
         (5, 4, 2, "guitar-1.gpx", "A/Two/guitar-1.gpx", "e")])
    old.commit()
    old.close()

    c = db.connect(path)
    inbox = {(r[0], r[1]): r[2] for r in c.execute(
        "SELECT song_id, kind, id FROM versions WHERE provider = 'inbox' AND tab_id = kind AND slot = 'guitar'")}
    assert sorted(inbox) == [(1, "guitar-pro"), (1, "power"), (2, "guitar-pro")] and inbox[1, "guitar-pro"] == 3
    assert c.execute("SELECT COUNT(*) FROM versions WHERE provider = 'ug'").fetchone()[0] == 0
    assert {r[0]: r[1] for r in c.execute("SELECT id, version_id FROM files")} == {
        1: inbox[1, "guitar-pro"], 2: inbox[1, "power"], 3: inbox[1, "power"], 4: inbox[1, "guitar-pro"],
        5: inbox[2, "guitar-pro"]}
    assert [f.name for f in guitar_files(c)] == [
        "guitar-1.gp5", "guitar-2.ptb", "guitar-3.PTB", "guitar-4.gp", "guitar-1.gpx"]
    c.close()


def test_a_version_8_database_made_before_its_artists_followed_deleted_rows_has_them_follow_now(tmp_path):
    # Schema 8 as its first caracole made it (e91ef66) had no trigger taking out the artist of a deleted or
    # re-keyed row: a database migrated then leaves an artist behind for each, and would for every Guitar Pro row
    # schema 9 deletes. Schema 9 makes the triggers again first, and takes out the artists no row has.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript("".join(db._MIGRATIONS[n] for n in range(1, 9)) + """
DROP TRIGGER ug_artists_unindexed;
DROP TRIGGER ug_index_artist_gone;
DROP TRIGGER ug_index_artist_changed;
CREATE TRIGGER ug_index_artist_changed AFTER UPDATE OF artist_key ON ug_index
WHEN new.artist_key IS NOT old.artist_key BEGIN
  INSERT INTO ug_artists(artist_key) SELECT new.artist_key
  WHERE NOT EXISTS (SELECT 1 FROM ug_artists WHERE artist_key = new.artist_key);
END;
PRAGMA user_version = 8;""")
    old.executemany("INSERT INTO ug_index VALUES (?, ?, ?, ?, '1', 'x', '')",
                    [(1, "van-morrison", "moondance", "chords"), (2, "van-halen", "jump", "guitar-pro"),
                     (3, "van-halen", "panama", "chords"), (4, "van-der-graaf", "refugees", "power"),
                     (5, "vann-closed", "x", "chords"), (6, "van-old-key", "y", "tabs")])
    old.execute("DELETE FROM ug_index WHERE tab_id = 5")  # a tab closed: its artist stayed
    old.execute("UPDATE ug_index SET artist_key = 'van-new-key' WHERE tab_id = 6")  # re-keyed: the old key stayed
    old.commit()
    assert old.execute("SELECT COUNT(*) FROM ug_artists").fetchone()[0] == 6
    old.close()

    c = db.connect(path)

    def artists():
        return [r[0] for r in c.execute("SELECT artist_key FROM ug_artists ORDER BY artist_key")]

    def by_word(word):
        return sorted(r[0] for r in c.execute(
            "SELECT artist_key FROM ug_artists WHERE id IN "
            "(SELECT rowid FROM ug_artists_fts WHERE ug_artists_fts MATCH ?)", (f'"{word}"',)))

    def doc(word):
        row = c.execute("SELECT doc FROM ug_artist_words WHERE term = ?", (word,)).fetchone()
        return row[0] if row else 0

    assert artists() == ["van-halen", "van-morrison", "van-new-key"]
    assert by_word("van") == artists() and doc("van") == 3 and doc("closed") == doc("graaf") == doc("old") == 0
    c.execute("INSERT INTO ug_artists_fts(ug_artists_fts) VALUES ('integrity-check')")
    # And the triggers follow every row deleted or re-keyed from now on.
    c.execute("DELETE FROM ug_index WHERE tab_id = 1")
    c.execute("UPDATE ug_index SET artist_key = 'van-halen-band' WHERE tab_id = 3")
    assert artists() == ["van-halen-band", "van-new-key"] and doc("van") == 2 and doc("morrison") == 0
    c.close()


def test_a_version_8_database_loses_what_each_line_said_beside_its_song(tmp_path):
    # A song's record is its wanted.txt line's word, kept nowhere else: the copies an older caracole kept in kv go.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript("".join(db._MIGRATIONS[n] for n in range(1, 9)) + "\nPRAGMA user_version = 8;")
    old.executemany("INSERT INTO kv VALUES (?, ?)", [
        ("songs:fields:wanted:oasis/wonderwall", '{"album": "Morning Glory"}'),
        ("songs:key_version", "3"), ("wanted:first_seen:oasis/wonderwall", "2026-10-01T00:00:00Z")])
    old.commit()
    old.close()

    c = db.connect(path)
    assert [r[0] for r in c.execute("SELECT key FROM kv ORDER BY key")] == [
        "songs:key_version", "wanted:first_seen:oasis/wonderwall"]
    c.close()


def test_a_version_8_database_loses_what_spotify_left(tmp_path):
    # Spotify is no source any more: its ids among a song's or a removed song's sources go, and so do its rows in kv;
    # the songs it brought stay, and so does every other source id. Every info.json, which writes out a song's
    # sources and its picks (a Guitar Pro pick on UG among them), is written again once (keys.refresh_info_keys).
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript("".join(db._MIGRATIONS[n] for n in range(1, 9)) + "\nPRAGMA user_version = 8;")
    old.executemany(
        "INSERT INTO songs (id, key, artist, title, artists, source_ids, added_at, created_at, updated_at) "
        "VALUES (?, ?, 'Oasis', ?, '[]', ?, 'x', 'x', 'x')",
        [(1, "oasis/wonderwall", "Wonderwall", '{"wanted": ["oasis/wonderwall"], "spotify": ["3ZOEytg"]}'),
         (2, "oasis/live-forever", "Live Forever", '{"spotify": ["1Rq2pX"]}'),
         (3, "oasis/whatever", "Whatever", '{"wanted": ["oasis/whatever"]}')])
    old.execute("INSERT INTO removed VALUES ('blur/song-2', 'Blur', 'Song 2', '{\"spotify\": [\"9x\"]}', 'x')")
    old.executemany("INSERT INTO kv VALUES (?, ?)", [
        ("source:spotify", "{}"), ("source:wanted", "{}"), ("spotify:top_tracks", "[]"),
        ("spotify:retry_after_until", "2026-10-01T00:00:00Z"), ("keys:info_version", "1")])
    old.commit()
    old.close()

    c = db.connect(path)
    assert [tuple(r) for r in c.execute("SELECT id, source_ids FROM songs ORDER BY id")] == [
        (1, '{"wanted":["oasis/wonderwall"]}'), (2, "{}"), (3, '{"wanted": ["oasis/whatever"]}')]
    assert c.execute("SELECT source_ids FROM removed").fetchone()[0] == "{}"
    assert [r[0] for r in c.execute("SELECT key FROM kv ORDER BY key")] == ["source:wanted"]
    c.close()


def test_an_artist_no_row_has_any_longer_leaves_the_index_of_their_words(conn):
    def by_word(word):
        return [r[0] for r in conn.execute("SELECT artist_key FROM ug_artists WHERE id IN "
                                           "(SELECT rowid FROM ug_artists_fts WHERE ug_artists_fts MATCH ?) "
                                           "ORDER BY artist_key", (f'"{word}"',))]

    def doc(word):
        row = conn.execute("SELECT doc FROM ug_artist_words WHERE term = ?", (word,)).fetchone()
        return row[0] if row else 0

    conn.executemany("INSERT INTO ug_index VALUES (?, ?, ?, 'chords', '1', 'x', '')",
                     [(1, "lynyrd-skynyrd", "free-bird"), (2, "lynyrd-skynyrd", "simple-man"),
                      (3, "skynyrd-tribute", "free-bird"), (4, "sam-grow", "skynyrd")])
    assert by_word("skynyrd") == ["lynyrd-skynyrd", "skynyrd-tribute"] and doc("skynyrd") == 2
    # A tab closed (ug/index.py deletes its row): the artist stays while another row has them.
    conn.execute("DELETE FROM ug_index WHERE tab_id = 1")
    assert by_word("skynyrd") == ["lynyrd-skynyrd", "skynyrd-tribute"]
    conn.execute("DELETE FROM ug_index WHERE tab_id = 3")
    assert by_word("skynyrd") == ["lynyrd-skynyrd"] and doc("skynyrd") == 1 and doc("tribute") == 0
    # Re-keyed (a sitemap parsed again under new keys): the old key goes with its last row.
    conn.execute("UPDATE ug_index SET artist_key = 'lynyrd-skynyrd-band' WHERE tab_id = 2")
    assert by_word("skynyrd") == ["lynyrd-skynyrd-band"] and doc("lynyrd") == 1
    assert conn.execute("SELECT COUNT(*) FROM ug_artists").fetchone()[0] == 2  # Sam Grow's and the band's
    assert conn.execute("INSERT INTO ug_artists_fts(ug_artists_fts) VALUES ('integrity-check')") is not None


def by_words(c, match):
    """The rows of ug_index whose keys hold the FTS5 query ``match`` (each word in quotes) by word, by tab id."""
    return [tuple(r) for r in c.execute(
        "SELECT tab_id, artist_key, song_key FROM ug_index WHERE tab_id IN "
        "(SELECT rowid FROM ug_index_fts WHERE ug_index_fts MATCH ?) ORDER BY tab_id", (match,))]


def key_words(c):
    return sorted(r[0] for r in c.execute("SELECT term FROM ug_key_words"))


def test_a_version_11_database_gains_its_rows_by_word_and_the_words_of_its_keys(tmp_path):
    # As harptabs.com's artist pages left it: schema 11, with index rows.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript("".join(db._MIGRATIONS[n] for n in range(1, 12)) + "\nPRAGMA user_version = 11;")
    old.executemany("INSERT INTO ug_index VALUES (?, ?, ?, 'chords', '1', 'x', '')",
                    [(1, "eagles", "hotel-california"), (2, "eagles", "hotel-california-live"),
                     (3, "led-zeppelin", "stairway-to-heaven"), (4, "oasis", "wonderwall")])
    old.commit()
    tables = {t: old.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() for t in ("ug_index", "ug_keys", "ug_artists")}
    old.close()

    c = db.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == NOW
    for table, rows in tables.items():
        assert [tuple(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY 1")] == rows, table
    # Every row by the words of its artist and its title, together: a title's word and its artist's in one query.
    assert by_words(c, '"hotel" AND "california"') == [(1, "eagles", "hotel-california"),
                                                      (2, "eagles", "hotel-california-live")]
    assert by_words(c, '"wonderwall" AND "oasis"') == [(4, "oasis", "wonderwall")]
    assert by_words(c, '"heaven" AND "oasis"') == []
    # And the words of every key, once each: what a close spelling is looked for among.
    assert key_words(c) == ["california", "eagles", "heaven", "hotel", "led", "live", "oasis", "stairway", "to",
                            "wonderwall", "zeppelin"]
    assert c.execute("INSERT INTO ug_index_fts(ug_index_fts) VALUES ('integrity-check')") is not None
    c.close()
    assert columns(path.with_name("caracole.sqlite.v11.bak"), "ug_key_words") == ([], 11)


def test_the_rows_by_word_follow_every_row_a_sitemap_adds_renames_or_closes(conn):
    from datetime import UTC, datetime

    from caracole.ug.index import upsert_rows

    when = datetime(2026, 10, 27, tzinfo=UTC)
    upsert_rows(conn, [(1, "oasis", "wonderwal", "chords", "oasis/wonderwal-chords-1"),
                       (2, "eagles", "hotel-california", "chords", "eagles/hotel-california-chords-2")], "1", when)
    assert by_words(conn, '"wonderwal"') == [(1, "oasis", "wonderwal")]
    # Parsed again under new keys: the row is found by its new words alone.
    upsert_rows(conn, [(1, "oasis", "wonderwall", "chords", "oasis/wonderwall-chords-1")], "1", when)
    assert by_words(conn, '"wonderwal"') == [] and by_words(conn, '"wonderwall"') == [(1, "oasis", "wonderwall")]
    conn.execute("UPDATE ug_index SET artist_key = 'the-eagles' WHERE tab_id = 2")
    assert by_words(conn, '"eagles" AND "hotel"') == [(2, "the-eagles", "hotel-california")]
    # A tab closed (ug/index.py deletes its row): found by no word.
    conn.execute("DELETE FROM ug_index WHERE tab_id = 2")
    assert by_words(conn, '"hotel"') == []
    assert conn.execute("INSERT INTO ug_index_fts(ug_index_fts) VALUES ('integrity-check')") is not None
    # The words of every key a row ever had, the old ones too: a word no row holds any longer matches nothing.
    assert {"wonderwal", "wonderwall", "eagles", "hotel", "california", "the", "oasis"} <= set(key_words(conn))
    assert conn.execute("SELECT COUNT(*) FROM ug_key_words").fetchone()[0] == len(key_words(conn))


def test_a_version_12_database_gains_gametabs_tables_and_keeps_its_rows(tmp_path):
    # As the close spellings of a title left it: schema 12, with a song and a harptabs.com row.
    path = tmp_path / "state" / "caracole.sqlite"
    path.parent.mkdir()
    old = sqlite3.connect(path)
    old.executescript("".join(db._MIGRATIONS[n] for n in range(1, 13)) + "\nPRAGMA user_version = 12;")
    old.execute("INSERT INTO harptabs_index VALUES ('tab/25/piano-man', 'tab', 25, 'piano-man', 'sitemap')")
    old.commit()
    old.close()

    c = db.connect(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == NOW
    assert [tuple(r) for r in c.execute("SELECT * FROM harptabs_index")] == [
        ("tab/25/piano-man", "tab", 25, "piano-man", "sitemap")]
    assert columns(path, "gametabs_index")[0] == ["path", "kind", "game", "slug", "page", "key", "slug_key", "sitemap"]
    assert columns(path, "gametabs_games")[0] == ["path", "game", "name", "tabs", "read_at"]
    assert columns(path, "gametabs_game_tabs")[0] == [
        "page", "path", "game", "title", "title_key", "instruments", "composers", "views", "rating", "place"]
    for table in ("gametabs_index", "gametabs_games", "gametabs_game_tabs"):
        assert c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    c.close()
    assert columns(path.with_name("caracole.sqlite.v12.bak"), "gametabs_index") == ([], 12)
