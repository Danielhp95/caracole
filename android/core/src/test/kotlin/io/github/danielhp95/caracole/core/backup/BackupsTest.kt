package io.github.danielhp95.caracole.core.backup

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.sync.Take
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.After
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayOutputStream
import java.io.File
import java.time.Instant
import java.util.zip.ZipInputStream
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The phone's backups (core.backup): the library's tables and its kept files by SHA-256, labelled, three of each
 * label; a copy checked before it takes an old one's place and none made without twice the room; a backup exported
 * as one file; a restore that puts the tables and the files back and keeps this side's own records (its cooldowns,
 * pace, gating records, settings and sync records) as they are now.
 */
class BackupsTest {
    @get:Rule val tmp = TemporaryFolder()

    private val opened = mutableListOf<Database>()

    @After fun close() = opened.forEach { it.close() }

    private class Phone(val database: Database, val library: File, val state: File) {
        val store = LibraryStore(library)
        fun <T> write(block: (Db) -> T): T = database.writeBlocking(block)
        fun <T> read(block: (Db) -> T): T = database.read(block)
    }

    /** A phone of the rich fixture: four songs, five kept files on disk, songbooks and overrides. */
    private fun phone(fixture: String = "sync/fixtures/rich.jsonl"): Phone {
        val dir = tmp.newFolder()
        val phone = Phone(TestDb.fresh(dir).also { opened += it }, File(dir, "library"), File(dir, "state"))
        phone.write { Fixtures.load(it, fixture, phone.library) }
        return phone
    }

    private fun at(day: Int, hour: Int = 8) = Instant.parse("2026-11-%02dT%02d:00:00Z".format(day, hour))

    private fun make(phone: Phone, at: Instant, label: String = Backups.BY_HAND): File =
        assertNotNull(phone.write { db -> Backups.make(db, phone.store, phone.state, at, label) })

    private fun backups(phone: Phone) = File(phone.state, Backups.FOLDER)

    private fun blobs(phone: Phone): Set<String> =
        File(backups(phone), Backups.BLOBS).list()?.toSet() ?: emptySet()

    /** Every row of the library's tables, sorted, as SQLite quotes them; kv's without the records this side keeps as
     * they are (OwnRecords: its own, and each song's that gate a request). */
    private fun library(db: Db): Map<String, List<String>> = TABLES.associateWith { table ->
        val columns = db.query("SELECT name FROM pragma_table_info(?)", table) { it.text(0)!! }
        val row = columns.joinToString(" || ',' || ") { "quote(\"$it\")" }
        val key = if (table == "kv") "key" else "NULL"
        db.query("SELECT $key, $row FROM $table") { it.text(0) to it.text(1)!! }
            .filter { (k, _) -> k == null || !(OwnRecords.isOwn(k) || OwnRecords.isSongsOwn(k)) }
            .map { it.second }.sorted()
    }

    private fun kv(db: Db, key: String): String? = db.kvGet(key)

    /** The kept files whose row names bytes other than their file holds. */
    private fun filesNotHoldingTheirRows(phone: Phone): List<String> = phone.read { db ->
        db.query("SELECT path, sha256 FROM files") { it.text(0)!! to it.text(1)!! }
    }.filter { (path, sha) -> !Kept.holds(File(phone.library, path).toPath(), sha) }.map { it.first }

    // --- make, the labels, the room ---------------------------------------------------------------------------------

    @Test fun aBackupIsNamedByItsLabelAndTimeAndListedNewestFirst() {
        val phone = phone()
        val first = make(phone, at(1), Backups.DAILY)
        val second = make(phone, at(2), Backups.BY_HAND)
        assertEquals(File(backups(phone), "daily-2026-11-01T080000Z.sqlite"), first)
        assertEquals(File(backups(phone), "by-hand-2026-11-02T080000Z.sqlite"), second)
        val listed = Backups.list(phone.state)
        assertEquals(listOf(second, first), listed.map { it.file })
        assertEquals(listOf(Backups.BY_HAND, Backups.DAILY), listed.map { it.label })
        assertEquals(listOf(at(2), at(1)), listed.map { it.at })
        // Its size is the copy's and the bytes it keeps of the library's files.
        val kept = phone.read { db -> db.query("SELECT DISTINCT sha256 FROM files") { it.text(0)!! } }
        val bytes = kept.sumOf { File(File(backups(phone), Backups.BLOBS), it).length() }
        assertEquals(second.length() + bytes, listed.first().size)
        assertFailsWith<IllegalArgumentException> { make(phone, at(3), "weekly") }
    }

    @Test fun eachLabelKeepsItsNewestThreeTheBeforeSyncBackupTheTakesOwn() {
        val phone = phone()
        val hand = (1..5).map { make(phone, at(it), Backups.BY_HAND) }
        val daily = (1..4).map { make(phone, at(it, 3), Backups.DAILY) }
        val sync = (1..2).map { day ->
            assertNotNull(phone.write { db -> Take.backupBeforeSync(db, phone.state, "2026-11-0${day}T09:00:00Z", phone.store) })
        }
        assertEquals((hand.takeLast(3) + daily.takeLast(3) + sync).map { it.name }.sorted(),
                     backups(phone).list()!!.filter { it.endsWith(".sqlite") }.sorted())
        assertEquals(sync.reversed(), Backups.list(phone.state).filter { it.label == Backups.BEFORE_SYNC }.map { it.file })
    }

    @Test fun noBackupIsMadeWithoutTwiceTheRoomItNeeds() {
        val phone = phone()
        val made = make(phone, at(1))
        val room = Backups.freeSpace
        try {
            Backups.freeSpace = { 1024L }
            assertNull(phone.write { db -> Backups.make(db, phone.store, phone.state, at(2), Backups.BY_HAND) })
        } finally {
            Backups.freeSpace = room
        }
        assertEquals(listOf(made.name), backups(phone).list()!!.filter { it.endsWith(".sqlite") })
        assertTrue(backups(phone).list()!!.none { it.endsWith(".part") })
    }

    @Test fun aCopyThatFailsItsCheckTakesNoOldOnesPlace() {
        val phone = phone()
        val made = (1..3).map { make(phone, at(it)) }
        val check = Backups.check
        try {
            Backups.check = { throw IllegalStateException("the copy failed its check: page 3 is never used") }
            assertFailsWith<IllegalStateException> { make(phone, at(4)) }
        } finally {
            Backups.check = check
        }
        assertEquals(made.map { it.name }, backups(phone).list()!!.filter { it.endsWith(".sqlite") }.sorted())
        assertTrue(backups(phone).list()!!.none { it.endsWith(".part") })
    }

    // --- the kept files ---------------------------------------------------------------------------------------------

    @Test fun theKeptFilesAreKeptOnceBySha256SharedBetweenBackupsAndGoWithTheirLast() {
        val phone = phone()
        val shas = phone.read { db -> db.query("SELECT sha256 FROM files") { it.text(0)!! } }.toSet()
        make(phone, at(1))
        make(phone, at(2))
        assertEquals(shas, blobs(phone))
        for (sha in shas) assertEquals(sha, Canonical.sha256Hex(File(File(backups(phone), Backups.BLOBS), sha).readBytes()))
        // A sheet kept again with other bytes: the next backups keep those; once the last backup of the old bytes
        // goes, so does its blob.
        val creep = phone.read { db -> Songs.byKey(db, "radiohead/creep")!! }
        val old = phone.read { db -> Kept.keptFiles(db, creep.id).first { it.name == "sheet.txt" } }
        phone.write { db -> Kept.keepFile(db, phone.store, creep, old.versionId, "sheet.txt", "[G]new".toByteArray(), 0, "2026-11-02T10:00:00Z") }
        val new = Canonical.sha256Hex("[G]new".toByteArray())
        make(phone, at(3))
        assertEquals(shas + new, blobs(phone))
        make(phone, at(4))
        make(phone, at(5))
        assertEquals(shas - old.sha256 + new, blobs(phone))
    }

    @Test fun aFileThatNoLongerHoldsItsRowsBytesIsNeverKeptAsThemAndItsBackupIsNeverRestoredWithout() {
        val phone = phone()
        val creep = phone.read { db -> Songs.byKey(db, "radiohead/creep")!! }
        val tab = phone.read { db -> Kept.keptFiles(db, creep.id).first { it.name == "tab.txt" } }
        val tabBytes = File(phone.library, tab.path).readBytes()
        File(phone.library, tab.path).writeText("changed by hand")
        val made = make(phone, at(1))
        assertFalse(tab.sha256 in blobs(phone))
        assertEquals(1, Backups.of(made)!!.missing, "the backup says it doesn't hold that file")
        // Restored with the file holding other bytes, or gone: refused, nothing changed, never written as other bytes.
        val before = phone.read { db -> library(db) }
        for (gone in listOf(false, true)) {
            if (gone) File(phone.library, tab.path).delete()
            val refused = assertFailsWith<NotRestorable> { Backups.restore(phone.database, phone.store, made) }
            assertEquals(listOf(tab.path), refused.paths)
            assertEquals("the backup doesn't hold 1 of its files, and the library no longer does: ${tab.path}", refused.message)
            assertEquals(before, phone.read { db -> library(db) })
            assertEquals(gone, !File(phone.library, tab.path).exists())
        }
        // Its bytes back where they were: the backup is whole again.
        File(phone.library, tab.path).writeBytes(tabBytes)
        Backups.restore(phone.database, phone.store, made)
        assertEquals(emptyList(), filesNotHoldingTheirRows(phone))
    }

    @Test fun aBackupOfTheTablesAloneIsRestoredOnlyWhileTheLibrarysFilesStillHoldItsBytes() {
        // A copy of the tables alone, as M1–3's take made before a sync: no blob of any kept file.
        val phone = phone()
        val made = make(phone, at(1), Backups.BEFORE_SYNC)
        File(backups(phone), Backups.BLOBS).deleteRecursively()
        val shas = phone.read { db -> db.query("SELECT DISTINCT sha256 FROM files") { it.text(0)!! } }
        assertEquals(shas.size, Backups.of(made)!!.missing)
        val out = ByteArrayOutputStream()
        val notExported = assertFailsWith<java.io.IOException> { Backups.exportTo(made, out) }
        assertTrue(notExported.message!!.startsWith("the backup doesn't hold ${shas.size} of its files: "), notExported.message)
        assertEquals(0, out.size(), "nothing written")
        // Every file still its bytes: restored.
        val before = phone.read { db -> library(db) }
        phone.write { db -> db.execute("UPDATE versions SET label = 'since'") }
        Backups.restore(phone.database, phone.store, made)
        assertEquals(before, phone.read { db -> library(db) })
        // A sheet kept again since with other bytes: refused, the tables and the sheet as they are.
        val creep = phone.read { db -> Songs.byKey(db, "radiohead/creep")!! }
        val sheet = phone.read { db -> Kept.keptFiles(db, creep.id).first { it.name == "sheet.txt" } }
        phone.write { db -> Kept.keepFile(db, phone.store, creep, sheet.versionId, "sheet.txt", "[G]since".toByteArray(), 0, "2026-11-05T08:00:00Z") }
        val since = phone.read { db -> library(db) }
        val refused = assertFailsWith<NotRestorable> { Backups.restore(phone.database, phone.store, made) }
        assertEquals(listOf(sheet.path), refused.paths)
        assertEquals(since, phone.read { db -> library(db) })
        assertEquals("[G]since", File(phone.library, sheet.path).readText())
    }

    @Test fun aRestoreWhoseBlobIsGoneOrNoLongerItsBytesChangesNothing() {
        val phone = phone()
        val made = make(phone, at(1))
        val creep = phone.read { db -> Songs.byKey(db, "radiohead/creep")!! }
        val sheet = phone.read { db -> Kept.keptFiles(db, creep.id).first { it.name == "sheet.txt" } }
        phone.write { db ->
            Kept.keepFile(db, phone.store, creep, sheet.versionId, "sheet.txt", "[G]since".toByteArray(), 0, "2026-11-05T08:00:00Z")
            Health.recordBlock(db, "ug", at(5), "403")
            db.kvDelete("provider:lrclib")
        }
        val since = phone.read { db -> library(db) }
        val own = phone.read { db -> OwnRecords.document(db) }
        val blob = File(File(backups(phone), Backups.BLOBS), sheet.sha256)
        for (broken in listOf({ blob.writeText("other bytes") }, { blob.delete() })) {
            broken()
            assertFailsWith<NotRestorable> { Backups.restore(phone.database, phone.store, made) }
            assertEquals(since, phone.read { db -> library(db) })
            assertEquals(own, phone.read { db -> OwnRecords.document(db) })
            assertEquals("[G]since", File(phone.library, sheet.path).readText())
        }
    }

    @Test fun aRestoreWhoseFilesFailAfterItsTablesCameBackSaysSoAndAgainFinishesIt() {
        val phone = phone()
        val made = make(phone, at(1))
        val creep = phone.read { db -> Songs.byKey(db, "radiohead/creep")!! }
        val sheet = phone.read { db -> Kept.keptFiles(db, creep.id).first { it.name == "sheet.txt" } }
        val before = phone.read { db -> library(db) }
        phone.write { db -> Kept.keepFile(db, phone.store, creep, sheet.versionId, "sheet.txt", "[G]since".toByteArray(), 0, "2026-11-05T08:00:00Z") }
        val folder = File(phone.library, sheet.path).parentFile
        assumeTrue("a folder this process can't write to (not root)", folder.setWritable(false) && !folder.canWrite())
        try {
            val partly = assertFailsWith<PartlyRestored> { Backups.restore(phone.database, phone.store, made) }
            assertTrue(partly.message!!.startsWith("its tables came back but not all its files ("), partly.message)
            assertTrue(partly.message!!.endsWith("): restore it again"), partly.message)
            assertEquals(before, phone.read { db -> library(db) }, "the tables came back")
        } finally {
            folder.setWritable(true)
        }
        assertTrue(Backups.restore(phone.database, phone.store, made).written >= 1, "the sheet written at last")
        assertEquals(emptyList(), filesNotHoldingTheirRows(phone))
    }

    @Test fun aBlobThatCantBeWrittenMakesNoBackup() {
        val phone = phone()
        backups(phone).mkdirs()
        File(backups(phone), Backups.BLOBS).writeText("a file where the blobs' folder goes")
        assertFailsWith<java.io.IOException> { phone.write { db -> Backups.make(db, phone.store, phone.state, at(1), Backups.BY_HAND) } }
        assertEquals(emptyList(), Backups.list(phone.state))
        assertTrue(backups(phone).list()!!.none { it.endsWith(".part") })
    }

    // --- export -----------------------------------------------------------------------------------------------------

    @Test fun aBackupBeingExportedIsNeverRotatedOutNorItsBlobsSwept() {
        val phone = phone()
        val exported = make(phone, at(1))
        val creep = phone.read { db -> Songs.byKey(db, "radiohead/creep")!! }
        val sheet = phone.read { db -> Kept.keptFiles(db, creep.id).first { it.name == "sheet.txt" } }
        // While its zip is written, the sheet changes and three more backups of its label are made (the queue's, say).
        var made = false
        fun meanwhile() {
            if (made) return
            made = true
            phone.write { db -> Kept.keepFile(db, phone.store, creep, sheet.versionId, "sheet.txt", "[G]since".toByteArray(), 0, "2026-11-05T08:00:00Z") }
            for (day in 2..4) make(phone, at(day))
        }
        val out = object : ByteArrayOutputStream() {
            override fun write(b: ByteArray, off: Int, len: Int) {
                meanwhile()
                super.write(b, off, len)
            }

            override fun write(b: Int) {
                meanwhile()
                super.write(b)
            }
        }
        Backups.exportTo(exported, out)
        assertTrue(exported.isFile, "kept while it was exported")
        val entries = LinkedHashMap<String, ByteArray>()
        ZipInputStream(out.toByteArray().inputStream()).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                entries[entry.name] = zip.readBytes()
            }
        }
        assertTrue("blobs/${sheet.sha256}" in entries, entries.keys.toString())
        assertEquals(sheet.sha256, Canonical.sha256Hex(entries.getValue("blobs/${sheet.sha256}")))
        // Once the export is over, the next backup rotates it out, and its old sheet's blob with it.
        make(phone, at(5))
        assertFalse(exported.exists())
        assertFalse(sheet.sha256 in blobs(phone))
    }

    @Test fun aBackupIsExportedAsOneZipOfItsCopyAndTheFilesItKeeps() {
        val phone = phone()
        val made = make(phone, at(1))
        val out = ByteArrayOutputStream()
        Backups.exportTo(made, out)
        val entries = LinkedHashMap<String, ByteArray>()
        ZipInputStream(out.toByteArray().inputStream()).use { zip ->
            while (true) {
                val entry = zip.nextEntry ?: break
                entries[entry.name] = zip.readBytes()
            }
        }
        val shas = phone.read { db -> db.query("SELECT DISTINCT sha256 FROM files ORDER BY sha256") { it.text(0)!! } }
        assertEquals(listOf(made.name) + shas.map { "blobs/$it" }, entries.keys.toList())
        assertTrue(entries.getValue(made.name).contentEquals(made.readBytes()))
        for (sha in shas) assertEquals(sha, Canonical.sha256Hex(entries.getValue("blobs/$sha")))
        assertEquals("caracole-by-hand-2026-11-01T080000Z.zip", Backups.exportName(Backups.of(made)!!))
    }

    // --- restore ----------------------------------------------------------------------------------------------------

    @Test fun aRestorePutsTheTablesAndFilesBackAndKeepsThisSidesOwnRecords() {
        val phone = phone()
        val now = at(1)
        phone.write { db ->
            Health.recordBlock(db, "lrclib", now, "429")
            db.kvSet("http:last_request:lrclib", "1793520000.250")
            db.kvSet("lacuerda:search:musica-ligera", "{\"at\": \"2026-11-01T08:00:00Z\"}")
            db.kvSet("sync:id", "phone-one")
            db.kvSet("sync:base:computer", "{\"format\": 2, \"units\": {}}")
            db.kvSet("phone:settings", "{\"name\": \"Before\"}")
            db.kvSet("megalobiz:checked:2", "2026-11-01T08:00:00Z")
        }
        val backup = make(phone, now)
        val before = phone.read { db -> library(db) }
        val yours = phone.read { db -> assertNotNull(kv(db, "sheet_versions:yours:1")) }
        val creep = phone.read { db -> Songs.byKey(db, "radiohead/creep")!! }
        val sheet = phone.read { db -> Kept.keptFiles(db, creep.id).first { it.name == "sheet.txt" } }

        // Since: the library changed (a sheet kept again, a file added, a version renamed, a song removed and asked
        // for again under a new id), and so did this side's own records.
        val later = at(5)
        phone.write { db ->
            Kept.keepFile(db, phone.store, creep, sheet.versionId, "sheet.txt", "[G]since".toByteArray(), 0, "2026-11-05T08:00:00Z")
            Kept.keepFile(db, phone.store, creep, sheet.versionId, "notes.txt", "added since".toByteArray(), 1, "2026-11-05T08:00:00Z")
            db.execute("UPDATE versions SET label = 'renamed since'")
            db.kvDelete("sheet_versions:yours:1")
            Health.recordBlock(db, "ug", later, "403")
            db.kvSet("http:last_request:lrclib", "1793866000.500")
            db.kvDelete("lacuerda:search:musica-ligera")
            db.kvSet("lacuerda:search:de-musica-ligera", "{\"at\": \"2026-11-05T08:00:00Z\"}")
            db.kvSet("sync:base:computer", "{\"format\": 2, \"units\": {\"song/x\": null}}")
            db.kvSet("phone:settings", "{\"name\": \"Since\"}")
            db.kvDelete("megalobiz:checked:2")
        }
        val karma = phone.read { db -> Songs.byKey(db, "radiohead/karma-police")!! }
        phone.write { db -> phone.store.remove(db, karma.key, "2026-11-05T08:00:00Z") }
        val again = phone.write { db -> phone.store.add(db, "Radiohead", "Karma Police", now = "2026-11-05T09:00:00Z") }
        assertTrue(again.id != karma.id)
        phone.write { db -> db.kvSet("azlyrics:checked:${again.id}", "2026-11-05T09:00:00Z") }
        val own = phone.read { db -> OwnRecords.document(db) }

        val restored = Backups.restore(phone.database, phone.store, backup)

        assertEquals(before, phone.read { db -> library(db) }, "the library's tables as backed up")
        assertEquals(emptyList(), filesNotHoldingTheirRows(phone), "every kept file holds its row's bytes")
        assertEquals(sheet.sha256, Canonical.sha256Hex(File(phone.library, sheet.path).readBytes()), "the sheet as it was")
        assertFalse(File(phone.library, "Radiohead/Creep/notes.txt").exists(), "a file kept since is gone")
        assertTrue(restored.written >= 1 && restored.removed >= 1, restored.toString())
        phone.read { db ->
            assertEquals(own, OwnRecords.document(db), "this side's own records as they were before the restore")
            assertTrue(Health.isCooling(db, "ug", later), "a cooldown met since is never forgotten")
            assertTrue(Health.isCooling(db, "lrclib", now))
            assertEquals("1793866000.500", kv(db, "http:last_request:lrclib"))
            assertNull(kv(db, "lacuerda:search:musica-ligera"))
            assertEquals("{\"at\": \"2026-11-05T08:00:00Z\"}", kv(db, "lacuerda:search:de-musica-ligera"))
            assertEquals("phone-one", kv(db, "sync:id"))
            assertEquals("{\"format\": 2, \"units\": {\"song/x\": null}}", kv(db, "sync:base:computer"))
            assertEquals("{\"name\": \"Since\"}", kv(db, "phone:settings"))
            assertEquals(yours, kv(db, "sheet_versions:yours:1"), "the library's own records come back")
            // A song's records that gate a request follow it by its identity key: Karma Police is song 2 again.
            assertEquals(karma.id, Songs.byKey(db, karma.key)!!.id)
            assertNull(kv(db, "megalobiz:checked:${karma.id}"))
            assertEquals("2026-11-05T09:00:00Z", kv(db, "azlyrics:checked:${karma.id}"))
            assertNull(kv(db, "azlyrics:checked:${again.id}"))
        }
    }

    @Test fun aRestoreTwiceIsTheSameAndANonBackupIsRefusedChangingNothing() {
        val phone = phone()
        val backup = make(phone, at(1))
        val before = phone.read { db -> library(db) }
        Backups.restore(phone.database, phone.store, backup)
        val again = Backups.restore(phone.database, phone.store, backup)
        assertEquals(0, again.written)
        assertEquals(0, again.removed)
        assertEquals(before, phone.read { db -> library(db) })
        val junk = tmp.newFile("junk.sqlite").also { it.writeText("not a database at all, at all, at all......") }
        assertFailsWith<Exception> { Backups.restore(phone.database, phone.store, junk) }
        assertFailsWith<IllegalArgumentException> { Backups.restore(phone.database, phone.store, File(tmp.root, "none")) }
        assertEquals(before, phone.read { db -> library(db) })
    }

    @Test fun theRecordsThisSideKeepsAreItsPolitenessItsIdentityAndItsIndexesProgress() {
        for (key in listOf("provider:ug", "http:last_request:ug", "sync:id", "sync:base:abc", "phone:settings",
                           "lacuerda:search:x", "lacuerda:search-failed", "gtptabs:unusable:12", "ug:artist_url:x",
                           "ug:pasted_tab:1", "ug:unreadable:1", "ug:index:built_at", "ug:sitemaps",
                           "lacuerda:index:pages", "harptabs:artists:keys", "phone:read:ug", "phone:pushed:ug")) {
            assertTrue(OwnRecords.isOwn(key), key)
        }
        for (key in listOf("songs:key_version", "wanted:first_seen:x", "render:1:phone", "render:files:1",
                           "sheet_versions:yours:1", "keys:own_versions", "lookup:songs", "megalobiz:checked:1",
                           "phone:render-build", "songbook:Book")) {
            assertFalse(OwnRecords.isOwn(key), key)
        }
        for (key in listOf("megalobiz:checked:1", "azlyrics:checked:2", "gtptabs:checked:3", "harptabs:checked:4",
                           "harptabs:checked:4:pick", "gametabs:checked:5", "ug:artist_page_checked:6")) {
            assertTrue(OwnRecords.isSongsOwn(key), key)
        }
        for (key in listOf("megalobiz:checked:", "lyrics:failed:1", "ug:blocked:1", "render:1", "megalobiz:checked:x")) {
            assertFalse(OwnRecords.isSongsOwn(key), key)
        }
    }

    private companion object {
        /** The library's tables (Take's backup's). */
        val TABLES = listOf("songs", "versions", "files", "removed", "kv", "phone_overrides", "phone_songbooks")
    }
}
