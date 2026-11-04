package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.LibraryWritesReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFails
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Versions and a song's columns as versions.py and songs.py write them (vectors/library/writes.jsonl), and what no
 * record shows: set_picks all or nothing, and undone with a caller's savepoint (tests/test_versions.py); a caller's
 * Kotlin values stored as Python's.
 */
class VersionsTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun versionsAreWrittenAsVersionsPyWritesThem() {
        val misses = Misses("library-writes: versions.py")
        LibraryWritesReplay.replay(misses) { it.startsWith("caracole.versions.") }
        misses.assertNone()
    }

    @Test fun aSongsColumnsAreWrittenAsSongsPyWritesThem() {
        val misses = Misses("library-writes: songs.py")
        LibraryWritesReplay.replay(misses) { it.startsWith("caracole.songs.") }
        misses.assertNone()
    }

    private fun <T> library(block: (Db, LibraryStore) -> T): T {
        val dir = tmp.newFolder()
        val library = File(dir, "library")
        return TestDb.fresh(dir).use { database ->
            database.writeBlocking { db ->
                Fixtures.load(db, "library/writes_fixture_library.jsonl", library)
                block(db, LibraryStore(library))
            }
        }
    }

    private fun ranks(db: Db, songId: Long) =
        db.query("SELECT id, pick_rank FROM versions WHERE song_id = ? AND kind = 'chords' ORDER BY id", songId) {
            it.long(0)!! to it.long(1)
        }

    @Test fun setPicksIsAllOrNothing() {
        library { db, _ ->
            val creep = Songs.byKey(db, "radiohead/creep")!!
            val (first, second) = Versions.songVersions(db, creep.id, kinds = listOf("chords")).map { it.id }
            Versions.setPicks(db, creep.id, listOf("chords"), listOf(first, second))
            db.execute("CREATE TEMP TRIGGER no_first_pick BEFORE UPDATE OF pick_rank ON versions " +
                           "WHEN NEW.pick_rank = 1 BEGIN SELECT RAISE(ABORT, 'no first pick'); END")
            assertFails { Versions.setPicks(db, creep.id, listOf("chords"), listOf(second, first)) }
            assertEquals(listOf(first to 1L, second to 2L), ranks(db, creep.id))
        }
    }

    @Test fun setPicksInsideACallersSavepointIsUndoneWithIt() {
        library { db, _ ->
            val creep = Songs.byKey(db, "radiohead/creep")!!
            val before = ranks(db, creep.id)
            assertFailsWith<IllegalStateException> {
                db.savepoint("outer") {
                    Versions.setPicks(db, creep.id, listOf("chords"), emptyList())
                    assertTrue(ranks(db, creep.id).all { it.second == null })
                    throw IllegalStateException("undone")
                }
            }
            assertEquals(before, ranks(db, creep.id))
        }
    }

    @Test fun aStaleVersionCompetesForNothingUntilItIsRecordedAgain() {
        library { db, _ ->
            val creep = Songs.byKey(db, "radiohead/creep")!!
            assertEquals(3, Versions.markStale(db, creep.id, "ug"))
            val stale = Versions.songVersions(db, creep.id, includeGone = true).filter { it.stale }
            assertEquals(listOf("101", "202", "303"), stale.map { it.tabId })
            assertTrue(stale.all { it.gone.not() && it.pickRank == null })
            assertEquals(listOf("55"), Versions.songVersions(db, creep.id).map { it.tabId })
            val again = Versions.upsert(db, "ug", "101", creep.id, "sheet", "chords", 4.5, 10, 1, null, "https://ug/101",
                                        JsonObject(emptyMap()), "2026-11-03T12:00:00Z")
            assertEquals(listOf("101", "55"), Versions.songVersions(db, creep.id).map { it.tabId }.sorted())
            assertEquals(false, Versions.get(db, again)!!.stale)
            assertNull(Versions.get(db, 9999))
        }
    }

    @Test fun aCallersKotlinValuesAreStoredAsPythonsAre() {
        library { db, _ ->
            val creep = Songs.byKey(db, "radiohead/creep")!!
            Versions.updateSong(db, creep.id, mapOf(
                "match_candidates" to listOf(mapOf("z" to 1, "a" to "é"), 2.5, null, true),
                "artists" to JsonArray(listOf(JsonPrimitive("Radiohead"))),
                "review" to listOf(0), "ug_dirty" to "", "match_score" to 1L,
            ), now = "2026-11-03T12:00:00Z")
            val row = db.one("SELECT match_candidates, artists, review, ug_dirty, typeof(match_score), updated_at " +
                                 "FROM songs WHERE id = ?", creep.id) {
                listOf(it.text(0), it.text(1), it.long(2), it.long(3), it.text(4), it.text(5))
            }
            assertEquals<List<Any?>?>(listOf("[{\"z\": 1, \"a\": \"é\"}, 2.5, null, true]", "[\"Radiohead\"]", 1L, 0L, "real",
                                      "2026-11-03T12:00:00Z"), row)
            assertEquals("unknown or read-only song field(s): id",
                         assertFailsWith<IllegalArgumentException> { Versions.updateSong(db, creep.id, mapOf("id" to 1)) }
                             .message)
        }
    }

    @Test fun refreshStatusStampsTheClocksTimeByDefault() {
        library { db, _ ->
            val wall = Songs.byKey(db, "oasis/wonderwall")!!
            assertEquals("wanted", Versions.refreshStatus(db, wall.id, ignored = false))
            val stamp = db.one("SELECT updated_at FROM songs WHERE id = ?", wall.id) { it.text(0)!! }!!
            assertTrue(Regex("""\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ""").matches(stamp) && stamp > "2026-11-01", stamp)
        }
    }
}
