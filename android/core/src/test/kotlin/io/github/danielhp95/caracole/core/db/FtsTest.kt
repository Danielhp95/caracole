package io.github.danielhp95.caracole.core.db

import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The three FTS5 indexes caracole's search reads, in the bundled SQLite, as search.py and ug/key_search.py ask
 * them: the keys' trigrams (a LIKE), the artists' words (unicode61, MATCH) and their vocabulary (fts5vocab). */
class FtsTest {
    @get:Rule val tmp = TemporaryFolder()

    private val tabs = listOf(
        Triple(10, "radiohead", "creep"), Triple(11, "radiohead", "karma-police"), Triple(12, "song-dongye", "an-he-qiao"),
        Triple(13, "song-dongye", "ban-ma-ban-ma"), Triple(14, "police", "roxanne"), Triple(15, "the-police", "message-in-a-bottle"),
        Triple(16, "bjork", "joga"), Triple(17, "sigur-ros", "hoppipolla"),
    )

    private fun indexed(): Database = TestDb.fresh(tmp.root).also { database ->
        database.writeBlocking { db ->
            db.savepoint("tabs") {
                for ((id, artist, song) in tabs) {
                    db.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                        "VALUES (?, ?, ?, 'Chords', 'tabs1.xml', 'x', ?)", id, artist, song, "tab/$artist/$song-chords-$id")
                }
            }
        }
    }

    @Test fun aTrigramLikeGoesThroughTheKeysIndex() {
        indexed().use { database ->
            database.read { db ->
                val sql = "SELECT key FROM ug_keys WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE key LIKE ?) ORDER BY key"
                val plan = db.query("EXPLAIN QUERY PLAN $sql", "%police%") { it.text("detail")!! }
                assertTrue(plan.any { "VIRTUAL TABLE INDEX" in it && "ug_keys_fts" in it }, "the plan: $plan")
                assertEquals(listOf("karma-police", "police", "the-police"), db.query(sql, "%police%") { it.text(0) })
                // As ug/key_search.py asks: several patterns at once, a key holding all.
                assertEquals(listOf("ban-ma-ban-ma"), db.query(
                    "SELECT key FROM ug_keys WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE key LIKE ? AND key LIKE ?)",
                    "%ban%", "%-ma%") { it.text(0) })
                // The trigram tokenizer folds case and finds what a scan finds.
                assertEquals(db.query("SELECT key FROM ug_keys WHERE key LIKE '%PPIPO%'") { it.text(0) },
                    db.query("SELECT key FROM ug_keys WHERE id IN (SELECT rowid FROM ug_keys_fts WHERE key LIKE '%PPIPO%')") { it.text(0) })
            }
        }
    }

    @Test fun anArtistIsFoundByAWordOfTheirKey() {
        indexed().use { database ->
            database.read { db ->
                val sql = "SELECT artist_key FROM ug_artists WHERE id IN " +
                    "(SELECT rowid FROM ug_artists_fts WHERE ug_artists_fts MATCH ?) ORDER BY artist_key LIMIT ?"
                assertEquals(listOf("police", "the-police"), db.query(sql, "\"police\"", 100) { it.text(0) })
                assertEquals(listOf("song-dongye"), db.query(sql, "\"song\" AND \"dongye\"", 100) { it.text(0) })
                assertEquals(listOf("bjork", "sigur-ros"), db.query(sql, "\"bjork\" OR \"ros\"", 100) { it.text(0) })
                // A title's words, from the index of every row (ug_index_fts).
                assertEquals(listOf(13L), db.query("SELECT tab_id FROM ug_index WHERE tab_id IN " +
                    "(SELECT rowid FROM ug_index_fts WHERE ug_index_fts MATCH ? LIMIT ?)", "(\"ban\") AND (\"ma\")", 5001) { it.long(0) })
            }
        }
    }

    @Test fun theArtistsWordsAreCountedByTheVocabulary() {
        indexed().use { database ->
            database.read { db ->
                val words = db.query("SELECT term, doc FROM ug_artist_words ORDER BY term") { it.text(0) to it.long(1) }
                assertEquals(listOf("bjork" to 1L, "dongye" to 1L, "police" to 2L, "radiohead" to 1L, "ros" to 1L,
                    "sigur" to 1L, "song" to 1L, "the" to 1L), words)
                // As search.py's _close_words reads it: the words of one first letter.
                assertEquals(listOf("sigur", "song"), db.query("SELECT term FROM ug_artist_words WHERE term >= ? AND term < ?",
                    "s", "t") { it.text(0) })
            }
        }
    }
}
