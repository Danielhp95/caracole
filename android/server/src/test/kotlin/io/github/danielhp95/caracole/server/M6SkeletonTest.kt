package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.lookup.RenderStats
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.guitar.GuitarFile
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
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** :server's milestone-5 and 6 declarations (skeleton-m5m6's): the phone's own job kinds and their words, the neutral
 * songbooks seams, and the corpus areas. What each answers is its lane's tests'. */
class M6SkeletonTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun thePhonesOwnKindsAreWordedAsThePlanSays() {
        assertEquals(listOf("render", "inbox", "backup", "restore"), PhoneKinds.ALL.keys.toList())
        val render = PhoneKinds.RENDER
        assertEquals("render" to "Making the pages", render.stage)
        assertEquals("Making the pages again: 2 of 5", PhoneKinds.fill(render.running, "done" to 2, "total" to 5))
        assertEquals("Pages made again for 3 songs", PhoneKinds.fill(render.done, "n" to 3))
        assertEquals("Waiting for a song that fits: a.gp5", PhoneKinds.fill(PhoneKinds.INBOX.otherwise!!, "name" to "a.gp5"))
        assertEquals("Backed up (daily)", PhoneKinds.fill(PhoneKinds.BACKUP.done, "label" to "daily"))
        assertEquals("Not restored: {why}", PhoneKinds.RESTORE.failed, "a blank no value names stays")
        for (kind in PhoneKinds.ALL.values) assertEquals(kind.kind + ":", kind.key)
    }

    @Test fun theSongbooksSeamsAreNeutralUntilTheirLanesLand() {
        TestDb.fresh(tmp.root).use { database ->
            val store = LibraryStore(File(tmp.root, "library"))
            database.read { db ->
                assertEquals(RenderStats(), SongbookPagesImpl(database, store).render(db, null))
                assertNull(SongbookSection.data(db, store))
            }
        }
        assertEquals(Version(), Entry("A - T", "T", "A").version)
        assertEquals(1, GuitarFile(1, "guitar-1.gp5", "A/T/guitar-1.gp5", 1).number)
    }

    @Test fun theServersCorpusAreasAreRegisteredOnceEach() {
        val areas = ServerReplays.all.map { it.area }
        assertEquals(areas.distinct(), areas)
        assertEquals(listOf("cards", "songbook-tab", "choices", "guitar", "export", "review"), areas.takeLast(6))
    }
}
