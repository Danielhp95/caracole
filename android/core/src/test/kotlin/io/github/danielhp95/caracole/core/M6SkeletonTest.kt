package io.github.danielhp95.caracole.core

import io.github.danielhp95.caracole.core.backup.Backup
import io.github.danielhp95.caracole.core.inbox.Filed
import io.github.danielhp95.caracole.core.inbox.GuitarFile
import io.github.danielhp95.caracole.core.inbox.GuitarFiles
import io.github.danielhp95.caracole.core.inbox.HarmonicaFile
import io.github.danielhp95.caracole.core.songbooks.Setting
import io.github.danielhp95.caracole.core.songbooks.Songbook
import io.github.danielhp95.caracole.core.songbooks.SongbookError
import io.github.danielhp95.caracole.core.songbooks.SongbookSong
import io.github.danielhp95.caracole.core.testing.Replays
import org.junit.Test
import java.io.File
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** :core's milestone-6 declarations (skeleton-m5m6's): songbooks, the inbox, the kept Guitar Pro and harmonica files
 * and backups are values, and their corpus areas are registered. What each answers is its lane's tests'. */
class M6SkeletonTest {
    @Test fun aSongbookIsItsSongsInOrder() {
        val book = Songbook("Campfire", listOf(SongbookSong("Estopa - Tu calorro"),
                                                SongbookSong("Oasis - Wonderwall", Setting(key = "G", capo = 2))))
        assertEquals(listOf("Estopa - Tu calorro", "Oasis - Wonderwall"), book.texts)
        assertNull(book.songs[0].setting)
        assertEquals("No songbook called Campfire.", SongbookError("No songbook called Campfire.").message)
    }

    @Test fun whatFilingAFileComesTo() {
        val outcomes: List<Filed> = listOf(Filed.Kept(1, "guitar-1.gp5"), Filed.PutBack(listOf("a.gp5")), Filed.Duplicate,
                                           Filed.Unmatched)
        assertEquals(4, outcomes.toSet().size)
    }

    @Test fun aKeptGuitarProOrHarmonicaFileIsAValueAndThePageDrawsGuitarProAlone() {
        assertTrue(GuitarFile(1, "guitar-1.GP5", "A/T/guitar-1.GP5", 1).inBrowser)
        assertFalse(GuitarFile(1, "guitar-2.ptb", "A/T/guitar-2.ptb", 2).inBrowser)  // a Power Tab file
        assertEquals(listOf("guitar-pro", "power"), GuitarFiles.KINDS)
        assertNull(HarmonicaFile(1, "harmonica-1.txt", "A/T/harmonica-1.txt", 1).harp)
    }

    @Test fun aBackupIsItsFileTimeLabelAndSize() {
        val at = Instant.parse("2026-11-04T00:00:00Z")
        assertEquals(Backup(File("b"), at, "daily", 10), Backup(File("b"), at, "daily", 10))
    }

    @Test fun theSongbookAndInboxAreasAreRegistered() {
        assertEquals(listOf("songbook", "inbox"), Replays.named(listOf("songbook", "inbox")).map { it.area })
        assertEquals(listOf("library-writes"), Replays.named(listOf("library_writes")).map { it.area })
    }
}
