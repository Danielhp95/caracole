package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.UgPagesReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** ug/artist_tabs.py's writers against Python's rows (vectors/sites/ug_artist_tabs.jsonl), and what the phone adds:
 * each page a store keeps tabs of noted for the next push to the computer. */
class ArtistTabsStoreTest {
    @get:Rule val tmp = TemporaryFolder()

    private val page = "https://www.ultimate-guitar.com/artist/a_8"

    private fun db(block: (Db) -> Unit) = TestDb.fresh(tmp.newFolder()).use { database: Database ->
        database.writeBlocking { block(it) }
    }

    private fun tab(id: Long, more: String = ""): UgVersion = UgPage.parseVersion(PyJson.loads(
        """{"id": $id, "type": "Chords", "song_name": "Song $id", "artist_name": "A", "tab_access_type": "public",
           "tab_url": "https://tabs.ultimate-guitar.com/tab/$id"$more}"""))!!

    @Test fun everyRecordAnswersAsPythonDid() = UgPagesReplay.artistTabs()

    @Test fun aTabAtATabPageOfAKindCaracoleUsesIsKeptAndNoOther() {
        assertTrue(ArtistTabs.kept(tab(1)))
        assertTrue(ArtistTabs.kept(tab(2, """, "tab_url": "HTTP://tabs.ultimate-guitar.com/tab/2"""")))
        assertFalse(ArtistTabs.kept(tab(3, """, "tab_access_type": "pro"""")))
        assertFalse(ArtistTabs.kept(tab(4, """, "type": "Pro"""")))
        assertFalse(ArtistTabs.kept(tab(5, """, "tab_url": "https://www.ultimate-guitar.com/pro/5"""")))
        assertFalse(ArtistTabs.kept(tab(6, """, "tab_url": "http://[::1/tab/6"""")))
    }

    @Test fun aPageIsNotedAtItsNewestReadAndAnOlderOneNeverMovesItBack() = db { db ->
        assertEquals(listOf(1L), ArtistTabs.store(db, page, "A", listOf(tab(1)), "2026-10-19T00:00:00Z"))
        assertEquals("2026-10-19T00:00:00Z", db.kvGet("${Reads.READ}ug:$page"))
        ArtistTabs.store(db, page, "A", listOf(tab(2)), "2026-10-18T00:00:00Z")  // another list, from the cache
        assertEquals("2026-10-19T00:00:00Z", db.kvGet("${Reads.READ}ug:$page"))
        ArtistTabs.store(db, page, "A", listOf(tab(3)), "2026-10-20T00:00:00Z")
        assertEquals(mapOf("ug" to listOf(page)), Reads.since(db, "computer"))
        assertEquals("2026-10-20T00:00:00Z", db.kvGet("${Reads.READ}ug:$page"))
    }

    @Test fun aStoreThatKeepsNothingNotesNothing() = db { db ->
        assertEquals(emptyList(), ArtistTabs.store(db, page, "A", listOf(tab(4, """, "type": "Pro"""")), "2026-10-19T00:00:00Z"))
        assertEquals(emptyMap(), Reads.since(db, "computer"))
    }

    @Test fun aListReadWholeKeepsWhatItListsAndOlderReadsOfItAlone() = db { db ->
        ArtistTabs.store(db, page, "A", listOf(tab(1), tab(2), tab(3)), "2026-10-18T00:00:00Z")
        ArtistTabs.store(db, page, "A", listOf(tab(4)), "2026-10-20T00:00:00Z")
        assertEquals(1, ArtistTabs.keepOnly(db, page, "chords", listOf(1, 3, 3), "2026-10-19T00:00:00Z"))
        val ids = db.query("SELECT tab_id FROM ug_artist_tabs ORDER BY tab_id") { it.long(0)!! }
        assertEquals(listOf(1L, 3L, 4L), ids)  // 4 came of a later read
        ArtistTabs.forget(db, page)
        assertEquals(0, db.one("SELECT COUNT(*) FROM ug_artist_tabs") { it.long(0)!!.toInt() })
    }
}
