package io.github.danielhp95.caracole.core.inbox

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.InboxReplay
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.file.Files
import java.nio.file.attribute.FileTime
import java.time.Duration
import java.time.Instant
import java.util.Base64
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * inbox.py's filing of one entry on the phone: Python's answers (vectors/inbox/), and what no record shows: that
 * [Inbox.fits] says what [Inbox.file] does (with the songs' names made once too), that [Inbox.changed] names the copy
 * a file is left waiting for, that a score is placed by its name alone, and the folder the shared files wait in
 * ([InboxFolder]), with the failures it remembers.
 */
class InboxTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun downloadNamesAreReadAsInboxPyReadsThem() {
        val misses = Misses("inbox: names")
        InboxReplay.names(misses)
        misses.assertNone()
    }

    @Test fun aDownloadIsOfTheSongInboxPyFinds() {
        val misses = Misses("inbox: match")
        InboxReplay.match(misses)
        misses.assertNone()
    }

    @Test fun aFileIsFiledAsFileInboxFilesIt() {
        val misses = Misses("inbox: file")
        InboxReplay.file(misses)
        misses.assertNone()
    }

    private fun <T> library(block: (Db, LibraryStore) -> T): T {
        val dir = tmp.newFolder()
        val library = File(dir, "library")
        return TestDb.fresh(dir).use { database ->
            database.writeBlocking { db ->
                Fixtures.load(db, "inbox/file_fixture_library.jsonl", library)
                block(db, LibraryStore(library))
            }
        }
    }

    @Test fun fitsSaysWhetherFilingWouldDoAnythingForEveryRecord() {
        for (record in Corpus.records(InboxReplay.FILE)) {
            library { db, lib ->
                val case = record.extra["case"]!!.jsonPrimitive.content
                for ((path, change) in (record.extra["changes"] as? JsonObject).orEmpty()) {
                    val file = File(lib.libraryDir, path)
                    if (change is JsonNull) file.delete()
                    else file.writeBytes(Base64.getDecoder().decode(change.jsonObject.getValue("base64").jsonPrimitive.content))
                }
                val name = record.kw.getValue("name").jsonPrimitive.content
                val data = Base64.getDecoder().decode(record.kw.getValue("data").jsonObject.getValue("base64").jsonPrimitive.content)
                val filed = record.out!!.jsonObject.getValue("filed").jsonPrimitive.content
                assertEquals(filed != "unmatched", Inbox.fits(db, lib, name, data), case)
                assertEquals(filed != "unmatched", Inbox.fits(db, lib, name, data, Inbox.Candidates.of(db)), case)
                // Left waiting for a copy whose place holds other bytes now: that copy is named, for no other record.
                val changed = Inbox.changed(db, lib, name, data)
                if (case.startsWith("bytes of a kept file whose place holds other bytes now")) {
                    assertEquals("guitar-1.gp5" to "blur/song-2",
                                 changed?.let { it.name to Songs.byId(db, it.songId)!!.key }, case)
                    assertEquals(Filed.Unmatched, Inbox.file(db, lib, name, data, "2026-11-10T00:00:00Z"), case)
                    assertEquals(changed, Inbox.changed(db, lib, name, data), case)
                } else {
                    assertNull(changed, case)
                }
            }
        }
    }

    @Test fun aScoreIsPlacedByItsNameAloneNeverByItsMusicXmlHeader() {
        val score = """<?xml version="1.0"?><score-partwise><work><work-title>Wonderwall</work-title></work>
            <identification><creator type="composer">Oasis</creator></identification></score-partwise>"""
        library { db, lib ->
            assertEquals(Filed.Unmatched, Inbox.file(db, lib, "score.musicxml", score.toByteArray(), "2026-11-10T00:00:00Z"))
            assertEquals(Filed.Kept(Songs.byKey(db, "oasis/wonderwall")!!.id, "score-1.musicxml"),
                         Inbox.file(db, lib, "Oasis - Wonderwall.musicxml", score.toByteArray(), "2026-11-10T00:00:00Z"))
        }
    }

    @Test fun aFileOfAnExtensionInboxPyFilesNothingOfFitsNoSong() {
        library { db, lib ->
            assertFalse(Inbox.keeps("Oasis - Wonderwall.txt"))
            assertFalse(Inbox.fits(db, lib, "Oasis - Wonderwall.txt", "x".toByteArray()))
            assertTrue(Inbox.fits(db, lib, "Oasis - Wonderwall.GP5", "x".toByteArray()))
        }
    }

    // --- the folder the shared files wait in ------------------------------------------------------------------

    private val now = Instant.parse("2026-11-10T12:00:00Z")

    @Test fun aSharedFileWaitsUnderItsNameAndASecondOfThatNameUnderOneOfItsOwn() {
        val folder = InboxFolder(tmp.newFolder("inbox"))
        assertEquals("Oasis - Wonderwall.gp5", folder.stage("Oasis - Wonderwall.gp5", "one".toByteArray(), now))
        assertEquals("Oasis - Wonderwall (2).gp5", folder.stage("Oasis - Wonderwall.gp5", "two".toByteArray(), now))
        assertEquals("Oasis - Wonderwall (3).gp5", folder.stage("Oasis - Wonderwall.gp5", "three".toByteArray(), now))
        assertEquals(listOf("Oasis - Wonderwall (2).gp5", "Oasis - Wonderwall (3).gp5", "Oasis - Wonderwall.gp5"),
                     folder.waiting())
        assertEquals("two", folder.read("Oasis - Wonderwall (2).gp5")!!.decodeToString())
        assertEquals(now, folder.stagedAt("Oasis - Wonderwall.gp5"))
        // The name a browser gives a second download names the same song.
        assertEquals(Triple("Oasis", "Wonderwall", null), Inbox.parseDownloadName("Oasis - Wonderwall (2).gp5"))
        folder.drop("Oasis - Wonderwall (2).gp5")
        assertNull(folder.read("Oasis - Wonderwall (2).gp5"))
        assertEquals(listOf("Oasis - Wonderwall (3).gp5", "Oasis - Wonderwall.gp5"), folder.waiting())
    }

    @Test fun onlyRegularFilesWaitAndALinkIsNeverRead() {
        val dir = tmp.newFolder("inbox")
        val folder = InboxFolder(dir)
        val secret = tmp.newFile("secret").apply { writeText("private") }
        Files.createSymbolicLink(File(dir, "Oasis - Wonderwall.gp5").toPath(), secret.toPath())
        File(dir, "a folder.gp5").mkdir()
        File(dir, ".staging.0123.tmp").writeText("half")
        assertEquals(emptyList(), folder.waiting())
        assertNull(folder.read("Oasis - Wonderwall.gp5"))
        assertNull(folder.read("../secret"))
        assertNull(folder.read(".staging.0123.tmp"))
        // A link at a name is a name taken: the file staged takes another, and the link's target is untouched.
        assertEquals("Oasis - Wonderwall (2).gp5", folder.stage("Oasis - Wonderwall.gp5", "mine".toByteArray(), now))
        assertEquals("private", secret.readText())
    }

    @Test fun aFileWaitsThirtyDaysThenIsDropped() {
        val dir = tmp.newFolder("inbox")
        val folder = InboxFolder(dir)
        folder.stage("old.gp5", "old".toByteArray(), now.minus(Duration.ofDays(30)))
        folder.stage("young.gp5", "young".toByteArray(), now.minus(Duration.ofDays(29)))
        val staging = File(dir, ".staging.ffff.tmp").apply { writeText("left") }
        Files.setLastModifiedTime(staging.toPath(), FileTime.from(now.minus(Duration.ofDays(2))))
        assertEquals(listOf("old.gp5"), folder.sweep(now))
        assertEquals(listOf("young.gp5"), folder.waiting())
        assertFalse(staging.exists())
        assertEquals(emptyList(), InboxFolder(File(dir, "none")).sweep(now))
    }

    @Test fun aFailureIsRememberedUntilTheFileIsFiledDroppedOrStagedAgain() {
        val dir = tmp.newFolder("inbox")
        val folder = InboxFolder(dir)
        folder.stage("Oasis - Wonderwall.gp5", "one".toByteArray(), now)
        assertNull(folder.failedAt("Oasis - Wonderwall.gp5"))
        folder.failed("Oasis - Wonderwall.gp5", now)
        assertEquals(now, folder.failedAt("Oasis - Wonderwall.gp5"))
        assertEquals(listOf("Oasis - Wonderwall.gp5"), folder.waiting())  // the failures' folder waits for nothing
        folder.failed("Oasis - Wonderwall.gp5", now.plusSeconds(60))
        assertEquals(now.plusSeconds(60), folder.failedAt("Oasis - Wonderwall.gp5"))
        folder.failed("nobody.gp5", now)  // no file waits under that name: nothing to remember
        assertNull(folder.failedAt("nobody.gp5"))
        assertEquals(listOf(), folder.sweep(now))
        assertEquals(now.plusSeconds(60), folder.failedAt("Oasis - Wonderwall.gp5"))  // a day or a month on
        folder.drop("Oasis - Wonderwall.gp5")
        assertNull(folder.failedAt("Oasis - Wonderwall.gp5"))
        // A failure whose file went otherwise is forgotten by the sweep, and is none of a file staged later.
        folder.stage("Blur - Song 2.gp5", "two".toByteArray(), now)
        folder.failed("Blur - Song 2.gp5", now)
        assertTrue(File(dir, "Blur - Song 2.gp5").delete())
        assertEquals("Blur - Song 2.gp5", folder.stage("Blur - Song 2.gp5", "three".toByteArray(), now))
        assertNull(folder.failedAt("Blur - Song 2.gp5"))
        folder.failed("Blur - Song 2.gp5", now)
        assertTrue(File(dir, "Blur - Song 2.gp5").delete())
        folder.sweep(now)
        assertFalse(File(File(dir, InboxFolder.FAILED), "Blur - Song 2.gp5").exists())
        // A link in the failures' folder's place is never followed: nothing remembered there, nothing swept there.
        val elsewhere = tmp.newFolder("elsewhere").apply { File(this, "keep.gp5").writeText("mine") }
        assertTrue(File(dir, InboxFolder.FAILED).deleteRecursively())
        Files.createSymbolicLink(File(dir, InboxFolder.FAILED).toPath(), elsewhere.toPath())
        folder.stage("Radiohead - Creep.gp5", "four".toByteArray(), now)
        folder.failed("Radiohead - Creep.gp5", now)
        assertNull(folder.failedAt("Radiohead - Creep.gp5"))
        folder.sweep(now)
        folder.drop("keep.gp5")
        assertEquals(listOf("keep.gp5"), elsewhere.list()!!.toList())
        assertEquals(listOf("Radiohead - Creep.gp5"), folder.waiting())
    }

    @Test fun aSharedFileIsNamedByItsNameItsBytesOrItsType() {
        val gp5 = byteArrayOf(24) + "FICHIER GUITAR PRO v5.00".toByteArray() + ByteArray(10)
        assertEquals("Oasis - Wonderwall.gp5", InboxFolder.nameFor("Oasis - Wonderwall.gp5", null, ByteArray(0)))
        assertEquals("Oasis - Wonderwall.gp5", InboxFolder.nameFor("Oasis - Wonderwall", "application/octet-stream", gp5))
        assertEquals("Oasis - Wonderwall.pdf", InboxFolder.nameFor("Oasis - Wonderwall", "application/PDF; x=1", ByteArray(0)))
        assertEquals("Mr. Brightside.mxl", InboxFolder.nameFor("Mr. Brightside", "application/vnd.recordare.musicxml", ByteArray(0)))
        assertEquals("tab.gp5", InboxFolder.nameFor("/storage/emulated/0/Download/tab.gp5", null, ByteArray(0)))
        assertEquals("hidden.gp5", InboxFolder.nameFor("..hidden.gp5", null, ByteArray(0)))
        assertEquals("shared file.gp5", InboxFolder.nameFor(null, null, gp5))
        assertEquals("notes.txt", InboxFolder.nameFor("notes.txt", "text/plain", ByteArray(0)))
        assertFalse(Inbox.keeps(InboxFolder.nameFor("notes.txt", "text/plain", ByteArray(0))))
        val long = InboxFolder.nameFor("斑".repeat(200) + ".gp5", null, ByteArray(0))
        assertTrue(long.toByteArray().size <= InboxFolder.MAX_NAME_BYTES && long.endsWith("斑.gp5"), long)
    }
}
