package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ug/artist_tabs.py's keys against the rows Python filed: the search fixture `ug` holds the tabs of the artist pages
 * of 宋冬野 and Soda Stereo as artist_tabs.store filed them (their keys, forms and the index's keys of their songs), so
 * making them again here must give each row as it is, and a row filed wrong must come back as Python filed it.
 */
class ArtistTabsTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun ug(block: (Database) -> Unit) {
        val dir = tmp.newFolder()
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { db -> Fixtures.load(db, "search/fixtures/ug.jsonl", File(dir, "library")) }
            block(database)
        }
    }

    private fun rows(db: Db): Map<Pair<String, Long>, List<String?>> =
        db.query("SELECT page, tab_id, artist_key, song_key, artist_forms, title_forms, forms, label FROM ug_artist_tabs") { r ->
            (r.text(0)!! to r.long(1)!!) to (2..7).map { r.text(it) }
        }.toMap()

    @Test fun theFixtureHoldsTabsOfArtistPagesBothFiledByTheIndexAndByTheirNames() = ug { database ->
        database.read { db ->
            val keys = rows(db).values.map { it[0] }.toSet()
            assertTrue(keys.size >= 2, "the fixture's artist pages file under ${keys.size} artist keys")
            assertEquals(Normalize.KEY_VERSION.toString(), db.kvGet(ArtistTabs.KEYS_KEY))
        }
    }

    @Test fun keysMadeAgainAreTheKeysPythonMadeEveryRowAsItIs() = ug { database ->
        database.writeBlocking { db ->
            val before = rows(db)
            assertEquals(0, ArtistTabs.ensureCurrentKeys(db), "the keys record is current: nothing to do")
            db.kvDelete(ArtistTabs.KEYS_KEY)
            assertEquals(0, ArtistTabs.ensureCurrentKeys(db))
            assertEquals(before, rows(db))
            assertEquals(Normalize.KEY_VERSION.toString(), db.kvGet(ArtistTabs.KEYS_KEY))
        }
    }

    @Test fun rowsKeyedBeforeAreKeyedAgainOnceAndCounted() = ug { database ->
        database.writeBlocking { db ->
            val before = rows(db)
            db.execute("UPDATE ug_artist_tabs SET artist_key = 'x', song_key = 'y', artist_forms = '', title_forms = '', forms = ''")
            db.kvSet(ArtistTabs.KEYS_KEY, "1")
            assertEquals(before.size, ArtistTabs.ensureCurrentKeys(db))
            assertEquals(before, rows(db))
            assertEquals(0, ArtistTabs.ensureCurrentKeys(db))
        }
    }

    @Test fun refilingAPageFilesItsTabsUnderTheIndexsKeysAgain() = ug { database ->
        database.writeBlocking { db ->
            val before = rows(db)
            val pages = before.keys.map { it.first }.distinct()
            db.execute("UPDATE ug_artist_tabs SET artist_key = 'x', song_key = 'y'")
            assertEquals(0, ArtistTabs.refile(db, emptyList()))
            assertEquals(before.size, ArtistTabs.refile(db, pages.take(1)) + ArtistTabs.refile(db, pages.drop(1)))
            assertEquals(before, rows(db))
            db.execute("UPDATE ug_artist_tabs SET artist_key = 'x', song_key = 'y'")
            assertEquals(before.size, ArtistTabs.refile(db))
            assertEquals(before, rows(db))
            assertEquals(0, ArtistTabs.refile(db, listOf("https://www.ultimate-guitar.com/artist/0")))
        }
    }

    /**
     * _file's two order rules, which the fixture's pages never tie: Counter.most_common(1) gives a tie to the artist
     * key counted first (the index's tabs in tab_id order, else the page's own), and songs.setdefault keeps the first
     * indexed tab's key of a song the index files under two. The expected keys are what Python's
     * `artist_tabs.refile(conn, [P, Q])` filed these very rows under (run once on a fresh database, pasted here).
     */
    @Test fun aTieGoesToTheArtistKeyCountedFirstAndASongToItsFirstIndexedTabsKey() {
        val p = "https://www.ultimate-guitar.com/artist/ties_1"
        val q = "https://www.ultimate-guitar.com/artist/own_2"
        val tabs = listOf(
            Triple(p, 1L, "Ties" to "Creep"), Triple(p, 2L, "Ties" to "Creep"), Triple(p, 3L, "Ties" to "Creep"),
            Triple(p, 4L, "Ties" to "Other Song"), Triple(p, 5L, "Ties" to "Lullaby"), Triple(p, 6L, "Ties" to "Lullaby"),
            Triple(q, 10L, "Beta Band" to "One"), Triple(q, 11L, "Alpha Band" to "Two"),
            Triple(q, 12L, "Alpha Band" to "Three"), Triple(q, 13L, "Beta Band" to "Four"),
        )
        // The index lists four of P's tabs: two under zeta, two under alpha (zeta's first), and Creep under two keys.
        val index = listOf(Triple(2L, "zeta", "kreep"), Triple(3L, "alpha", "creeep"),
                           Triple(5L, "alpha", "lullaby-acoustic"), Triple(6L, "zeta", "lulaby"))
        val dir = tmp.newFolder()
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { db ->
                for ((page, tabId, names) in tabs) {
                    db.execute(
                        "INSERT INTO ug_artist_tabs (page, tab_id, type, artist, title, label, rating, votes, url, " +
                            "artist_key, song_key, artist_forms, title_forms, forms, read_at) VALUES (?, ?, 'Chords', ?, ?, " +
                            "NULL, 0, 0, ?, 'x', 'y', '', '', '', '2026-11-01T00:00:00Z')",
                        page, tabId, names.first, names.second, "https://tabs.ultimate-guitar.com/tab/$tabId",
                    )
                }
                for ((tabId, artistKey, songKey) in index) {
                    db.execute(
                        "INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                            "VALUES (?, ?, ?, 'chords', 's', '2026-11-01T00:00:00Z', '')",
                        tabId, artistKey, songKey,
                    )
                }
                assertEquals(tabs.size, ArtistTabs.refile(db, listOf(p, q)))
                val filed = db.query("SELECT page, tab_id, artist_key, song_key FROM ug_artist_tabs ORDER BY page, tab_id") {
                    listOf(it.text(0)!!, it.long(1)!!.toString(), it.text(2)!!, it.text(3)!!)
                }
                assertEquals(
                    listOf(
                        listOf(q, "10", "beta-band", "one"), listOf(q, "11", "beta-band", "two"),
                        listOf(q, "12", "beta-band", "three"), listOf(q, "13", "beta-band", "four"),
                        listOf(p, "1", "zeta", "kreep"), listOf(p, "2", "zeta", "kreep"), listOf(p, "3", "zeta", "kreep"),
                        listOf(p, "4", "zeta", "other-song"), listOf(p, "5", "zeta", "lullaby"),
                        listOf(p, "6", "zeta", "lullaby"),
                    ),
                    filed,
                )
            }
        }
    }

    @Test fun aTabsNamesAreItsSlugKeysAndEveryFormHyphenatedAndTogether() {
        val n = ArtistTabs.names("Song Dongye (宋冬野)", "斑马 斑马 Banma Banma Zebra Zebra")
        assertEquals("song-dongye-宋冬野", n.artistKey)
        assertEquals("斑马斑马-banma-banma-zebra-zebra", n.songKey)
        assertEquals(null, n.variant)
        assertEquals("song-dongye-宋冬野 song-dongye-song-dong-ye song-dongye 宋冬野 song-dong-ye", n.artistForms)
        assertTrue(n.forms.split(" ").containsAll(listOf("banma-banma", "banmabanma", "songdongye")), n.forms)
        // As ug/artist_tabs.py's _names has them: a title's brackets are cleaned off, a variant's last word is not.
        assertEquals(ArtistTabs.Names("radiohead", "creep", null, "radiohead", "creep", "radiohead creep"),
                     ArtistTabs.names("Radiohead", "Creep (Acoustic)"))
        assertEquals(ArtistTabs.Names("radiohead", "creep", "acoustic", "radiohead", "creep-acoustic",
                                      "radiohead creep-acoustic creepacoustic"),
                     ArtistTabs.names("Radiohead", "Creep Acoustic"))
    }
}
