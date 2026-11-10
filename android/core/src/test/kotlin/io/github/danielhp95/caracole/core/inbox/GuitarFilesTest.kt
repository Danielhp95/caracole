package io.github.danielhp95.caracole.core.inbox

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/** inbox.guitar_files on the phone: the Guitar Pro and Power Tab files a song keeps, as test_inbox.py has them. */
class GuitarFilesTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun song(db: Db, title: String): Long {
        db.execute("INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) " +
                       "VALUES (?, 'Eagles', ?, '[\"Eagles\"]', '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z', " +
                       "'2026-11-01T00:00:00Z')", "eagles/$title", title)
        return db.lastRowid()
    }

    private fun keep(db: Db, songId: Long, name: String, kind: String) {
        db.execute("INSERT INTO versions (provider, tab_id, song_id, slot, kind, rating, votes, version, url, raw, " +
                       "fetched_at) VALUES ('inbox', ?, ?, 'guitar', ?, 0, 0, 1, '', '{}', '2026-11-01T00:00:00Z')",
                   "$songId/$name", songId, kind)
        val version = db.lastRowid()
        db.execute("INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) " +
                       "VALUES (?, ?, ?, ?, 'x', 1, '2026-11-01T00:00:00Z')", version, songId, name, "Eagles/$songId/$name")
    }

    @Test
    fun aSongsGuitarProFilesAreItsKeptOnesOfEitherKindBySongThenNumber() = TestDb.fresh(tmp.root).use { database ->
        database.writeBlocking { db ->
            val one = song(db, "one")
            val two = song(db, "two")
            keep(db, one, "guitar-10.gp5", "guitar-pro")
            keep(db, one, "guitar-2.GPX", "guitar-pro")
            keep(db, one, "guitar-3.ptb", "power")
            keep(db, one, "guitar-4.txt", "guitar-pro") // no Guitar Pro file's extension
            keep(db, one, "guitar-5.gp5", "tab") // another kind's
            keep(db, one, "guitar.gp5", "guitar-pro") // no number
            keep(db, two, "guitar-1.gp", "guitar-pro")
            val files = GuitarFiles.of(db, one)
            assertEquals(listOf("guitar-2.GPX", "guitar-3.ptb", "guitar-10.gp5"), files.map { it.name })
            assertEquals(listOf(2, 3, 10), files.map { it.number })
            assertEquals(listOf(true, false, true), files.map { it.inBrowser })
            assertEquals(listOf(one, one, one, two), GuitarFiles.of(db).map { it.songId })
            assertEquals(listOf("guitar-1.gp"), GuitarFiles.of(db, path = "Eagles/$two/guitar-1.gp").map { it.name })
            assertEquals(emptyList<GuitarFile>(), GuitarFiles.of(db, one, path = "Eagles/$two/guitar-1.gp"))
        }
    }
}
