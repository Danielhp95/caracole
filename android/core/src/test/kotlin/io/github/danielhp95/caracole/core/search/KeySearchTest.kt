package io.github.danielhp95.caracole.core.search

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlin.test.fail

/**
 * ug/key_search.py's `rows_like` against vectors/search/query.jsonl: each record's patterns over its fixture
 * (vectors/search/fixtures/<name>.jsonl) replayed into a fresh database, as Python ran them, rows and order alike.
 */
class KeySearchTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun theRowsAPatternFindsAreThoseSearchPyFinds() {
        val records = Corpus.records(QueryTest.VECTOR).filter { it.fn == QueryTest.ROWS_LIKE }
        assertTrue(records.isNotEmpty(), "${QueryTest.VECTOR} has no rows_like record")
        val wrong = mutableListOf<String>()
        for ((fixture, group) in records.groupBy { it.extra.getValue("fixture").jsonPrimitive.content }) {
            val dir = tmp.newFolder(fixture)
            TestDb.fresh(dir).use { database ->
                database.writeBlocking { db -> Fixtures.load(db, "search/fixtures/$fixture.jsonl", File(dir, "library")) }
                for (record in group) {
                    val patterns = record.args[0].jsonArray.map { it.jsonPrimitive.content }
                    val expected = record.out!!.jsonArray.map { row ->
                        val (artist, song, count) = row.jsonArray.map { it.jsonPrimitive }
                        Triple(artist.content, song.content, count.int)
                    }
                    val actual = database.read { db -> KeySearch.rowsLike(db, patterns) }
                    if (actual != expected) wrong.add("$fixture $patterns: Python $expected, Kotlin $actual")
                }
            }
        }
        if (wrong.isNotEmpty()) fail("${wrong.size} of ${records.size} rows_like records differ:\n" + wrong.take(20).joinToString("\n"))
    }

    /** test_search.py::test_a_common_word_brings_in_its_shortest_keys_and_those_every_word_is_in, at two keys a
     * pattern: no fixture has a word in more than [KeySearch.KEYS_PER_PATTERN] keys, so the vectors never cut one. */
    @Test fun aCommonWordBringsInItsShortestKeysAndThoseEveryWordIsIn() {
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                val rows = listOf(
                    Triple(1, "x", "love"), Triple(2, "y", "lovely"), Triple(3, "z", "glove-box"),
                    Triple(4, "w", "i-love-you-baby"), Triple(5, "v", "baby"), Triple(6, "u", "babylon"),
                )
                for ((id, artist, song) in rows) {
                    db.execute(
                        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                            "VALUES (?, ?, ?, 'chords', '1', 'x', ?)",
                        id, artist, song, "$artist/$song-chords-$id",
                    )
                }
            }
            database.read { db ->
                fun songs(patterns: List<String>) = KeySearch.rowsLike(db, patterns, perPattern = 2).map { it.second }.toSet()
                assertEquals(setOf("love", "lovely"), songs(listOf("%love%")), "the two shortest")
                assertEquals(
                    setOf("love", "lovely", "baby", "babylon", "i-love-you-baby"),
                    songs(listOf("%love%", "%baby%")),
                    "and the one with both words",
                )
                assertEquals(setOf("love", "lovely", "glove-box", "i-love-you-baby"),
                             KeySearch.rowsLike(db, listOf("%love%")).map { it.second }.toSet(), "every key, uncut")
                assertEquals(0L, db.one("SELECT COUNT(*) FROM temp._ug_like") { it.long(0) })
            }
        }
    }

    @Test fun noPatternReadsNothingAndTheTempTableIsLeftEmpty() {
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                db.execute(
                    "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                        "VALUES (1, 'radiohead', 'creep', 'chords', '1', 'x', 'radiohead/creep-chords-1')",
                )
            }
            database.read { db ->
                assertEquals(emptyList(), KeySearch.rowsLike(db, emptyList()))
                assertEquals(listOf(Triple("radiohead", "creep", 1)), KeySearch.rowsLike(db, listOf("%creep%")))
                assertEquals(listOf(Triple("radiohead", "creep", 1)), KeySearch.rowsLike(db, listOf("%ra%")))
                assertEquals(0L, db.one("SELECT COUNT(*) FROM temp._ug_like") { it.long(0) })
            }
        }
    }
}
