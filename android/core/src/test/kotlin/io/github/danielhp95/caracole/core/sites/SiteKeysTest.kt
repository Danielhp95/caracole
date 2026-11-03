package io.github.danielhp95.caracole.core.sites

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals

/**
 * harptabs_fetch.ensure_current_keys, harptabs_index.ensure_current_keys and gametabs_index.ensure_current_keys on
 * the phone: a search fixture as Python keyed it (vectors/search/fixtures: Python's keys are in its rows), its keys
 * made stale and its keys records taken out, is keyed again by SiteKeys into exactly the rows Python wrote. And each
 * index's state, as harptabs_index.index_state and gametabs_index.index_state count it.
 */
class SiteKeysTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun loaded(fixture: String, block: (Database) -> Unit) {
        val dir = tmp.newFolder(fixture)
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { db -> Fixtures.load(db, "search/fixtures/$fixture.jsonl", File(dir, "library")) }
            block(database)
        }
    }

    private fun harpRows(db: Db): List<List<String?>> =
        db.query("SELECT path, key FROM harptabs_index ORDER BY path") { listOf(it.text(0), it.text(1)) } +
            db.query("SELECT artist, tab_id, song_key FROM harptabs_artist_tabs ORDER BY artist, tab_id") {
                listOf(it.text(0), it.long(1).toString(), it.text(2))
            }

    private fun gameRows(db: Db): List<List<String?>> =
        db.query("SELECT page, path, title_key FROM gametabs_game_tabs ORDER BY page, path") {
            listOf(it.text(0), it.text(1), it.text(2))
        }

    private fun count(db: Db, table: String): Int = db.one("SELECT COUNT(*) FROM $table") { it.long(0)!!.toInt() }!!

    @Test fun harptabsKeysAreMadeAgainFromThePathsAndTitlesAsPythonMadeThem() {
        for (fixture in listOf("sites", "titles", "names")) loaded(fixture) { database ->
            val python = database.read { harpRows(it) }
            val rows = database.read { count(it, "harptabs_index") + count(it, "harptabs_artist_tabs") }
            database.writeBlocking { db ->
                db.execute("UPDATE harptabs_index SET key = 'stale-' || key")
                db.execute("UPDATE harptabs_artist_tabs SET song_key = 'stale-' || song_key")
                db.kvDelete(SiteKeys.HARPTABS_ROW_KEYS)
                db.kvDelete(SiteKeys.HARPTABS_SONG_KEYS)
            }
            assertNotEquals(python, database.read { harpRows(it) })
            assertEquals(rows, database.writeBlocking { SiteKeys.harptabsEnsureCurrentKeys(it) }, fixture)
            assertEquals(python, database.read { harpRows(it) }, fixture)
            assertEquals(SiteKeys.HARPTABS_ROWS, database.read { it.kvGet(SiteKeys.HARPTABS_ROW_KEYS) })
            assertEquals(Normalize.KEY_VERSION.toString(), database.read { it.kvGet(SiteKeys.HARPTABS_SONG_KEYS) })
            assertEquals(0, database.writeBlocking { SiteKeys.harptabsEnsureCurrentKeys(it) }, "once only")
        }
    }

    @Test fun aRowKeyedBeforeTheContractionsWereJoinedIsKeyedAgain() = loaded("sites") { database ->
        database.writeBlocking { db ->
            db.execute("UPDATE harptabs_index SET key = 'can-t-help-falling-in-love' " +
                           "WHERE path = 'tab/30906/can-t-help-falling-in-love'")
            db.kvDelete(SiteKeys.HARPTABS_ROW_KEYS)
        }
        assertEquals(1, database.writeBlocking { SiteKeys.harptabsEnsureCurrentKeys(it) })
        assertEquals("cant-help-falling-in-love", database.read { db ->
            db.one("SELECT key FROM harptabs_index WHERE page_id = 30906") { it.text(0) }
        })
    }

    @Test fun currentKeysRecordsReKeyNothing() = loaded("sites") { database ->
        database.writeBlocking { db ->
            db.kvSet(SiteKeys.HARPTABS_ROW_KEYS, "1")
            db.execute("UPDATE harptabs_index SET key = 'stale'")
            db.execute("UPDATE gametabs_game_tabs SET title_key = 'stale'")
        }
        assertEquals(0, database.writeBlocking { SiteKeys.harptabsEnsureCurrentKeys(it) })
        assertEquals(0, database.writeBlocking { SiteKeys.gametabsEnsureCurrentKeys(it) })
        assertEquals(listOf("stale"), database.read { db ->
            db.query("SELECT DISTINCT key FROM harptabs_index") { it.text(0) }
        })
        assertEquals(listOf("stale"), database.read { db ->
            db.query("SELECT DISTINCT title_key FROM gametabs_game_tabs") { it.text(0) }
        })
    }

    @Test fun gametabsTitleKeysAreMadeAgainFromTheTitlesAsPythonMadeThem() = loaded("sites") { database ->
        val python = database.read { gameRows(it) }
        val rows = database.read { count(it, "gametabs_game_tabs") }
        database.writeBlocking { db ->
            db.execute("UPDATE gametabs_game_tabs SET title_key = 'stale-' || title_key")
            db.kvDelete(SiteKeys.GAMETABS_TITLE_KEYS)
        }
        assertEquals(rows, database.writeBlocking { SiteKeys.gametabsEnsureCurrentKeys(it) })
        assertEquals(python, database.read { gameRows(it) })
        assertEquals(Normalize.KEY_VERSION.toString(), database.read { it.kvGet(SiteKeys.GAMETABS_TITLE_KEYS) })
        assertEquals(0, database.writeBlocking { SiteKeys.gametabsEnsureCurrentKeys(it) })
    }

    @Test fun eachIndexSaysHowFarItHasGot() = loaded("sites") { database ->
        // The fixture's sitemap lists 3 artists and 7 game pages; caracole read 2 of each, which listed 9 and 11 tabs.
        // Python's harptabs_index.index_state and gametabs_index.index_state of the same fixture, asked of it, before
        // and after the deletes (no corpus record holds them yet).
        assertEquals(state("artists" to 3, "read" to 2, "tabs" to 9), database.read { SiteKeys.harptabsIndexState(it) })
        assertEquals(state("pages" to 7, "read" to 2, "tabs" to 11), database.read { SiteKeys.gametabsIndexState(it) })
        database.writeBlocking { db ->
            db.execute("DELETE FROM harptabs_index WHERE path = 'artist/50/the-beatles'") // a page the sitemap dropped
            db.execute("DELETE FROM gametabs_index WHERE path = 'tabs/actraiser'")
        }
        assertEquals(state("artists" to 2, "read" to 1, "tabs" to 7), database.read { SiteKeys.harptabsIndexState(it) })
        assertEquals(state("pages" to 6, "read" to 1, "tabs" to 6), database.read { SiteKeys.gametabsIndexState(it) })
    }

    @Test fun anEmptyIndexHasGotNowhere() = loaded("empty") { database ->
        assertEquals(state("artists" to 0, "read" to 0, "tabs" to 0), database.read { SiteKeys.harptabsIndexState(it) })
        assertEquals(state("pages" to 0, "read" to 0, "tabs" to 0), database.read { SiteKeys.gametabsIndexState(it) })
        assertEquals(0, database.writeBlocking { SiteKeys.harptabsEnsureCurrentKeys(it) })
        assertEquals(0, database.writeBlocking { SiteKeys.gametabsEnsureCurrentKeys(it) })
    }

    private fun state(vararg fields: Pair<String, Int>) =
        JsonObject(linkedMapOf(*fields).mapValues { JsonPrimitive(it.value) })
}
