package io.github.danielhp95.caracole.core.index

import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.sqlite.execSQL
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals

/**
 * How long a merge of a big UG index takes on the JVM: 200,000 generated ug_index rows in one sitemap of an export,
 * merged into a new phone seeded as an app's is, and into one with matched songs whose new tabs mark them, each time
 * printed (no assertion on it: a figure for the plan's risks).
 */
class MergeSpeedBench {
    @get:Rule val tmp = TemporaryFolder()

    private val rows = 200_000
    private val now = "2026-11-03T12:00:00Z"

    private fun artist(i: Int) = "artist-${i % 9973}"
    private fun song(i: Int) = "song-${i / 7}"

    @Test fun twoHundredThousandUgRowsMerged() {
        val export = bigExport()
        TestDb.fresh(tmp.newFolder()).use { database ->
            database.writeBlocking { IndexTransfer.seedFresh(it) }
            val started = System.nanoTime()
            val merged = database.writeBlocking { IndexTransfer.merge(it, export, now) }
            val took = (System.nanoTime() - started) / 1_000_000
            assertEquals(mapOf("sitemap" to 1), merged.sites["ug"])
            val count = database.read { db -> db.one("SELECT COUNT(*) FROM ug_index") { it.long(0)!! } }
            assertEquals(rows.toLong(), count)
            println("MergeSpeedTest: $rows ug_index rows merged in $took ms into a new phone")
        }
    }

    @Test fun twoHundredThousandUgRowsMergedIntoAPhoneWithSongs() {
        val export = bigExport()
        TestDb.fresh(tmp.newFolder()).use { database ->
            val matched = (1..rows step 1000).map { artist(it) to song(it) }.distinct()
            database.writeBlocking { db ->
                IndexTransfer.seedFresh(db)
                matched.forEachIndexed { n, (artist, song) ->
                    db.execute(
                        "INSERT INTO songs (key, artist, title, artists, source_ids, status, match_decision, " +
                            "match_artist_key, match_song_key, added_at, created_at, updated_at) VALUES " +
                            "(?, ?, ?, '[]', '{}', 'wanted', 'accept', ?, ?, ?, ?, ?)",
                        "$artist/$song", artist, song, artist, song, now, now, "2026-11-01T00:00:00Z",
                    )
                    // One more of each, in review: never marked.
                    db.execute(
                        "INSERT INTO songs (key, artist, title, artists, source_ids, status, match_decision, " +
                            "match_artist_key, match_song_key, added_at, created_at, updated_at) VALUES " +
                            "(?, ?, ?, '[]', '{}', 'wanted', 'review', ?, ?, ?, ?, ?)",
                        "$artist/$song-$n", artist, "$song $n", artist, song, now, now, "2026-11-01T00:00:00Z",
                    )
                }
            }
            val started = System.nanoTime()
            database.writeBlocking { IndexTransfer.merge(it, export, now) }
            val took = (System.nanoTime() - started) / 1_000_000
            val marked = database.read { db ->
                db.query("SELECT match_decision, COUNT(*) FROM songs WHERE ug_dirty = 1 AND updated_at = ? " +
                             "GROUP BY match_decision", now) { it.text(0)!! to it.long(1)!! }
            }
            assertEquals(listOf("accept" to matched.size.toLong()), marked)
            println("MergeSpeedTest: $rows ug_index rows merged in $took ms into a phone of ${2 * matched.size} " +
                        "songs, ${matched.size} of them marked")
        }
    }

    /** An export of [rows] UG tabs in one sitemap, beside partial-export's gtptabs.com and MuseScore. */
    private fun bigExport(): File {
        val export = File(tmp.newFolder(), "export.sqlite")
        Fixtures.loadRaw(export, "index/fixtures/partial-export.jsonl")
        val made = System.nanoTime()
        BundledSQLiteDriver().open(export.path).let { c ->
            try {
                c.execSQL("BEGIN")
                c.execSQL(
                    "CREATE TABLE ug_index (tab_id INTEGER PRIMARY KEY, artist_key TEXT NOT NULL, " +
                        "song_key TEXT NOT NULL, type TEXT NOT NULL, sitemap TEXT NOT NULL, " +
                        "first_seen TEXT NOT NULL, path TEXT NOT NULL DEFAULT '')",
                )
                c.execSQL(
                    "CREATE TABLE ug_artist_tabs (page TEXT NOT NULL, tab_id INTEGER NOT NULL, type TEXT NOT NULL, " +
                        "artist TEXT NOT NULL, title TEXT NOT NULL, label TEXT, rating REAL NOT NULL DEFAULT 0, " +
                        "votes INTEGER NOT NULL DEFAULT 0, url TEXT NOT NULL, artist_key TEXT NOT NULL, " +
                        "song_key TEXT NOT NULL, artist_forms TEXT NOT NULL, title_forms TEXT NOT NULL, " +
                        "forms TEXT NOT NULL, read_at TEXT NOT NULL, PRIMARY KEY (page, tab_id))",
                )
                c.prepare(
                    "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                        "VALUES (?, ?, ?, 'chords', 'big', '2026-10-28T03:30:00Z', ?)",
                ).use { st ->
                    for (i in 1..rows) {
                        val artist = artist(i)
                        val song = song(i)
                        st.bindLong(1, i.toLong())
                        st.bindText(2, artist)
                        st.bindText(3, song)
                        st.bindText(4, "$artist/$song-chords-$i")
                        st.step()
                        st.reset()
                    }
                }
                val record = "{\"big\": {\"etag\": null, \"last_modified\": null, " +
                    "\"indexed_at\": \"2026-10-28T03:30:00Z\", \"rows\": $rows}}"
                c.execSQL("INSERT INTO kv (key, value) VALUES ('ug:sitemaps', '$record'), ('ug:artist_tabs:keys', '2')")
                c.execSQL("UPDATE caracole_export SET value = '[\"ug\", \"gtptabs\", \"musescore\"]' " +
                              "WHERE key = 'sites'")
                c.execSQL("COMMIT")
            } finally {
                c.close()
            }
        }
        val took = (System.nanoTime() - made) / 1_000_000
        println("MergeSpeedTest: an export of $rows ug_index rows generated in $took ms")
        return export
    }
}
