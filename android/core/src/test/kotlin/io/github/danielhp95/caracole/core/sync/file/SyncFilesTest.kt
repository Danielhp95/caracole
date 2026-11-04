package io.github.danielhp95.caracole.core.sync.file

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.PeerError
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.SyncReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.After
import org.junit.Assume
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayOutputStream
import java.io.File
import java.time.Instant
import java.time.ZoneOffset
import java.util.zip.ZipEntry
import java.util.zip.ZipFile
import java.util.zip.ZipOutputStream
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The `.caracole` file on the phone (the sync redesign's §3.3): written, read back, refused whole, and its replay of
 * vectors/sync/file.jsonl (tests/test_conformance_sync_file.py) once sync-file's corpus is there.
 */
class SyncFilesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val opened = ArrayList<Database>()

    @After fun close() = opened.forEach { it.close() }

    /** A library of its own, the sync corpus's [fixture] loaded into it. */
    private fun library(fixture: String?): Pair<Database, File> {
        val dir = tmp.newFolder()
        val database = TestDb.fresh(dir).also { opened.add(it) }
        val library = File(dir, "library").apply { mkdirs() }
        if (fixture != null) database.writeBlocking { Fixtures.load(it, fixture, library) }
        return database to library
    }

    private fun export(database: Database, library: File, parts: List<String> = listOf("library", "songbooks"),
                       name: String = "Desk"): File {
        val to = File(tmp.newFolder(), "desk.caracole")
        database.writeBlocking { db ->
            SyncFiles.export(db, library, null, to, parts, MADE, Compare.ownId(db), name, "0.1.0")
        }
        return to
    }

    private fun members(file: File): List<Pair<ZipEntry, ByteArray>> =
        ZipFile(file).use { z -> z.entries().toList().map { it to z.getInputStream(it).readBytes() } }

    /** A zip of [members], in order, each deflated (as the corpus's _zip writes one). */
    private fun zip(members: List<Pair<String, ByteArray>>): ByteArray = ByteArrayOutputStream().also { out ->
        ZipOutputStream(out).use { z ->
            for ((name, data) in members) {
                z.putNextEntry(ZipEntry(name))
                z.write(data)
                z.closeEntry()
            }
        }
    }.toByteArray()

    private fun refused(data: ByteArray): String {
        val file = tmp.newFile().apply { writeBytes(data) }
        return assertFailsWith<FileError> { SyncFiles.checkWhole(SyncFiles.read(file)) }.message!!
    }

    @Test fun everyRecordOfFileJsonlReplays() {
        Assume.assumeTrue("waiting on sync-file: vectors/sync/file.jsonl", SyncReplay.fileVectors())
        Misses(SyncReplay.FILE).also(SyncReplay::file).assertNone()
    }

    @Test fun thePhonesOwnExportReadsBackWhole() {
        val (database, library) = library("sync/fixtures/rich.jsonl")
        val file = export(database, library)
        val names = members(file).map { it.first.name }
        assertEquals(listOf("caracole.json", "state.json", "bases.json", "units.jsonl"), names.take(4))
        assertTrue(names.drop(4).all { it.startsWith("files/") }, "$names")
        val read = SyncFiles.read(file)
        SyncFiles.checkWhole(read)
        val state = database.read { Units.libraryState(it) }
        assertEquals(database.read { Compare.ownId(it) }, read.id)
        assertEquals("Desk", read.name)
        assertEquals(MADE, read.made)
        assertEquals(listOf("library", "songbooks"), read.holds)
        assertEquals(state.mapValues { it.value.digest }, read.state!!.units.mapValues { it.value.digest })
        val manifest = read.manifest
        assertEquals(JsonPrimitive(Units.FORMAT), manifest["sync"])
        assertEquals(JsonPrimitive(state.keys.count { it.startsWith("song/") }), manifest["songs"])
        assertEquals(JsonArray(emptyList()), manifest["indexes"])
        FileSource(read, null, library).use { source ->
            assertEquals(state.keys.sortedWith(Canonical.KEY_ORDER), source.documents().keys.sortedWith(Canonical.KEY_ORDER))
            for (id in state.keys) {
                assertEquals(state.getValue(id).digest, Canonical.digest(Units.valueOfDocument(id, source.unit(id))!!), id)
            }
            assertNull(source.unit("song/not/here"), "a song of the library its caracole hasn't got")
            assertNull(source.pages())
            val creep = source.unit("song/radiohead/creep")!!
            val kept = ((creep["versions"] as JsonArray).first() as JsonObject)["files"] as JsonArray
            val tab = kept.map { it as JsonObject }.first()
            val sha = (tab["sha256"] as JsonPrimitive).content
            assertEquals(sha, Canonical.sha256Hex(source.file("radiohead/creep", (tab["name"] as JsonPrimitive).content, sha)))
            assertFailsWith<PeerError> { source.file("radiohead/creep", "x", "0".repeat(64)) }
        }
        // The file takes its name, and a second export over it is refused.
        assertFailsWith<FileError> { database.writeBlocking { db ->
            SyncFiles.export(db, library, null, file, listOf("library"), MADE, Compare.ownId(db), "Desk", "0.1.0")
        } }
        assertEquals(listOf(file.name), file.parentFile.list()!!.toList(), "nothing left beside it")
        assertFailsWith<FileError> { database.writeBlocking { db ->
            SyncFiles.export(db, library, null, File(file.parentFile, "x.caracole"), listOf("indexes"), MADE, "x", "D", "0.1.0")
        } }
    }

    @Test fun aMemberOutsideTheLayoutABlobOver64MiBOrAFileCutShortIsRefusedWhole() {
        val (database, library) = library("sync/fixtures/rich.jsonl")
        val file = export(database, library)
        val whole = file.readBytes()
        val members = members(file).map { it.first.name to it.second }
        fun unreadable(why: String) = FileError.unreadable(why)

        assertEquals(unreadable("a member outside its layout: ../evil"), refused(zip(members + ("../evil" to byteArrayOf(1)))))
        assertEquals(unreadable("a member outside its layout: files/${"A".repeat(64)}"),
                     refused(zip(members + ("files/${"A".repeat(64)}" to byteArrayOf(1)))))
        val blob = "files/" + Canonical.sha256Hex("x".toByteArray())
        assertEquals(unreadable("$blob is bigger than it may be"),
                     refused(declaring(zip(members + (blob to "x".toByteArray())), blob, SyncFiles.FILE_MAX + 1)))
        assertEquals(unreadable("it is cut short, or no whole zip"), refused(whole.copyOf(whole.size - 200)))
        assertEquals(FileError.NOT_A_FILE, refused("hello, this is no file of caracole's\n".toByteArray()))
        assertEquals(FileError.NOT_A_FILE, refused(zip(listOf("photo.jpg" to byteArrayOf(1)) + members)))
        // A blob's bytes damaged where they lie: read whole, its CRC says so.
        val (stored, data) = members(file).first { it.first.name.startsWith("files/") }
        val damaged = whole.copyOf()
        val at = indexOf(damaged, data)
        damaged[at] = (damaged[at].toInt() xor 0xFF).toByte()
        assertEquals(unreadable("${stored.name} is damaged or cut short"), refused(damaged))
        // A blob whose bytes aren't its name, a kept file it lacks.
        assertEquals(unreadable("${stored.name} isn't the file its name says"),
                     refused(zip(members.map { (n, b) -> n to if (n == stored.name) "other".toByteArray() else b })))
        assertTrue(refused(zip(members.filter { it.first != stored.name })).endsWith("keeps a file it doesn't hold): export it again."))
        // Another format, or another sync's.
        val manifest = members[0].second.toString(Charsets.UTF_8)
        assertEquals(FileError.otherFormat("2"),
                     refused(zip(listOf("caracole.json" to manifest.replace("\"format\":1", "\"format\":2").toByteArray()) + members.drop(1))))
        assertEquals(FileError.otherFormat("1, its sync's 2"),
                     refused(zip(listOf("caracole.json" to manifest.replace("\"sync\":${Units.FORMAT}", "\"sync\":2").toByteArray()) + members.drop(1))))
    }

    /** The zip [data] with its central directory declaring the member [name] [size] bytes (the corpus's _declaring). */
    private fun declaring(data: ByteArray, name: String, size: Long): ByteArray {
        val out = data.copyOf()
        fun u16(at: Int) = (out[at].toInt() and 0xFF) or ((out[at + 1].toInt() and 0xFF) shl 8)
        fun u32(at: Int) = u16(at).toLong() or (u16(at + 2).toLong() shl 16)
        var end = out.size - 22
        while (u32(end) != 0x06054b50L) end--
        var at = u32(end + 16).toInt()
        repeat(u16(end + 10)) {
            val n = u16(at + 28)
            if (String(out, at + 46, n, Charsets.UTF_8) == name) {
                for (i in 0 until 4) out[at + 24 + i] = (size shr (8 * i)).toByte()
            }
            at += 46 + n + u16(at + 30) + u16(at + 32)
        }
        return out
    }

    private fun indexOf(data: ByteArray, part: ByteArray): Int =
        (0..data.size - part.size).first { i -> part.indices.all { data[i + it] == part[it] } }

    @Test fun anIndexExportIsAFileOfIndexesAlone() {
        val file = File(tmp.newFolder(), "upload.part").also { it.delete() }
        Fixtures.loadRaw(file, "index/fixtures/full-export.jsonl")
        val read = SyncFiles.read(file, "indexes.sqlite")
        assertTrue(read.indexOnly)
        assertNull(read.id)
        assertNull(read.state)
        assertEquals("indexes.sqlite", read.name)
        assertEquals(listOf("indexes"), read.holds)
        SyncFiles.checkWhole(read)
        FileSource(read, null, file.parentFile).use { source ->
            assertEquals(emptyMap(), source.documents())
            assertEquals("the file doesn't hold that part of its library, so it says nothing of it",
                         assertFailsWith<PeerError> { source.unit("song/a/b") }.message)
            val copy = File(file.parentFile, "copy.sqlite")
            assertTrue(source.indexes(copy))
            assertTrue(copy.readBytes().contentEquals(file.readBytes()))
        }
        assertEquals(SyncFiles.read(file).name, file.name, "named by its own name, else")
        val (database, _) = library(null)
        database.read { db -> SyncFiles.checkImportable(read, db, "0123456789abcdef", ZoneOffset.UTC) }
    }

    @Test fun theFilesNameIsTheLibrarysNameAndTheDay() {
        val at = Instant.parse("2026-11-03T21:10:00Z")
        assertEquals("horde_logbook-03-11-26.caracole", SyncFiles.fileName("horde_logbook", at, ZoneOffset.UTC))
        assertEquals("caracole-03-11-26.caracole", SyncFiles.fileName(null, at, ZoneOffset.UTC))
        assertEquals("caracole-03-11-26.caracole", SyncFiles.fileName(" ... ", at, ZoneOffset.UTC))
        assertEquals("a_b_ c_-03-11-26.caracole", SyncFiles.fileName("a/b: c?", at, ZoneOffset.UTC))
        assertEquals("Desk-04-11-26.caracole", SyncFiles.fileName("Desk", at, ZoneOffset.ofHours(5)))
        assertEquals(150, SyncFiles.fileName("斑".repeat(100), at, ZoneOffset.UTC).removeSuffix("-03-11-26.caracole")
            .toByteArray().size)
    }

    private companion object {
        const val MADE = "2026-11-03T21:10:00Z"
    }
}
