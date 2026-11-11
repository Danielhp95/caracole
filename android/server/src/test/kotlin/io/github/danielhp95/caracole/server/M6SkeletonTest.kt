package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.lookup.SongbookPages
import io.github.danielhp95.caracole.core.lookup.SongbookStats
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.server.page.SongbookSection
import io.github.danielhp95.caracole.server.songbooks.Entry
import io.github.danielhp95.caracole.server.songbooks.SongbookPagesImpl
import io.github.danielhp95.caracole.server.testing.ServerReplays
import io.github.danielhp95.caracole.viewer.version.Version
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlinx.serialization.json.JsonArray
import kotlin.test.assertEquals
import kotlin.test.assertSame

/** :server's milestone-5 and 6 declarations (skeleton-m5m6's): the phone's own job kinds and their words, the neutral
 * songbooks seams, and the corpus areas. What each answers is its lane's tests'. */
class M6SkeletonTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun thePhonesOwnKindsAreWordedAsThePlanSays() {
        assertEquals(listOf("render", "inbox", "backup", "restore"), PhoneKinds.ALL.keys.toList())
        val render = PhoneKinds.RENDER
        assertEquals("render" to "Making the pages", render.stage)
        assertEquals("Remake the pages" to "The phone's pages", render.title to render.display)
        assertEquals("File a.gp5", PhoneKinds.fill(PhoneKinds.INBOX.title, "name" to "a.gp5"))
        assertEquals("The book of 2026-11-04", PhoneKinds.fill(PhoneKinds.RESTORE.display, "date" to "2026-11-04"))
        assertEquals("Making the pages again: 2 of 5", PhoneKinds.fill(render.running, "done" to 2, "total" to 5))
        assertEquals("Pages remade · 3 songs", PhoneKinds.fill(render.done, "n" to 3))
        assertEquals("Waiting for its song: a.gp5", PhoneKinds.fill(PhoneKinds.INBOX.otherwise!!, "name" to "a.gp5"))
        assertEquals("Backed up (daily)", PhoneKinds.fill(PhoneKinds.BACKUP.done, "label" to "daily"))
        assertEquals("Not restored: {why}", PhoneKinds.RESTORE.failed, "a blank no value names stays")
        for (kind in PhoneKinds.ALL.values) assertEquals(kind.kind + ":", kind.key)
    }

    @Test fun theSongbooksSeamsAreTheirLanesOnceTheyLand() {
        TestDb.fresh(tmp.root).use { database ->
            val store = LibraryStore(File(tmp.root, "library"))
            database.writeBlocking { db ->
                val pages = SongbookPagesImpl(database, store, null) { "build" }
                assertEquals(SongbookStats(), pages.render(db, null))
                // The lookup's songbooks stage makes the songbooks' pages (songbook-entries).
                assertSame<SongbookPages>(pages, pages.seam)
                assertEquals(JsonArray(emptyList()), SongbookSection.data(db, store, null, null)!!["books"])
            }
        }
        assertEquals(Version(), Entry("A - T", "T", "A").version)
    }

    @Test fun theServersCorpusAreasAreRegisteredOnceEach() {
        val areas = ServerReplays.all.map { it.area }
        assertEquals(areas.distinct(), areas)
        assertEquals(listOf("cards", "songbook-tab", "choices", "guitar", "export", "review"), areas.takeLast(6))
    }
}
