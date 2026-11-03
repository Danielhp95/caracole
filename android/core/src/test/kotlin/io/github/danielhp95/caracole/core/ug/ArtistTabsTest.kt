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
