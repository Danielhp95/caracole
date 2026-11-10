package io.github.danielhp95.caracole.core.sync.file

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.Comparison
import io.github.danielhp95.caracole.core.sync.Conflicts
import io.github.danielhp95.caracole.core.sync.KeptEntry
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.Scope
import io.github.danielhp95.caracole.core.sync.Side
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.SyncFailed
import io.github.danielhp95.caracole.core.sync.SyncOutcome
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.SyncReplay
import io.github.danielhp95.caracole.mirror.ServerAddress
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import java.time.ZoneOffset
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * An import on the phone (the sync redesign's Task 13): a `.caracole` file compared as a sync with the caracole that
 * made it, and applied in FILE_STAGES, a part it doesn't hold never read as a removal, a file refused before anything
 * changes, a "keep mine" remembered; and vectors/sync/file.jsonl's import records once sync-file's corpus is there.
 */
class ImportTest {
    @get:Rule val tmp = TemporaryFolder()

    private val opened = ArrayList<Database>()
    private val stages = CopyOnWriteArrayList<Triple<String, String, String>>()

    @After fun close() = opened.forEach { it.close() }

    /** A caracole of its own: its database, library and engine. */
    private inner class Caracole(fixture: String? = null) {
        val dir: File = tmp.newFolder()
        val database = TestDb.fresh(dir).also { opened.add(it) }
        val library = File(dir, "library").apply { mkdirs() }
        val store = LibraryStore(library)
        val pagesHanded = CopyOnWriteArrayList<Pair<SyncFile, List<String>>>()
        val engine = SyncEngine(database, store, File(dir, "state"), client = { PeerClient(ServerAddress.parse(it)) },
                                mirrorRefresh = null, pagesFromFile = { f, taken -> pagesHanded.add(f to taken) })
            .also { it.zone = ZoneOffset.UTC }

        init {
            if (fixture != null) database.writeBlocking { Fixtures.load(it, fixture, library) }
        }

        val id: String get() = database.read { Compare.ownId(it) }
        fun state() = database.read { Units.libraryState(it) }
        fun kv() = database.read { db -> db.query("SELECT key, value FROM kv ORDER BY key") { it.text(0) to it.text(1) } }

        fun add(artist: String, title: String, album: String? = null): SongRow =
            database.writeBlocking { store.add(it, artist, title, album = album, now = "2026-11-01T10:00:00Z") }

        fun export(parts: List<String> = listOf(Scope.LIBRARY, Scope.SONGBOOKS), made: String = MADE): File {
            val to = File(tmp.newFolder(), "file.caracole")
            database.writeBlocking { db -> SyncFiles.export(db, library, null, to, parts, made, Compare.ownId(db), "Desk", "0.1.0") }
            return to
        }

        fun apply(c: Comparison, choices: Map<String, Side> = emptyMap(),
                  prefer: Side? = null, parts: List<String> = Scope.PARTS,
                  conflicts: Conflicts = Conflicts.ASK): SyncOutcome = runBlocking {
            engine.apply(c, choices, prefer, parts, conflicts) { name, state, detail -> stages.add(Triple(name, state, detail)) }
        }
    }

    private fun ended(): Map<String, String> = stages.associate { (name, state, _) -> name to state }

    @Test fun everyImportRecordOfFileJsonlGivesTheSameDifferencesTakesAndBasesAsPythons() {
        val misses = Misses("${SyncReplay.FILE} import")
        SyncReplay.file(misses, only = "import")
        misses.assertNone()
    }

    @Test fun aFirstImportTakesTheFilesLibraryInFileStagesAndGivesNothing() {
        val there = Caracole("sync/fixtures/rich.jsonl")
        val here = Caracole()
        val c = here.engine.compareFile(there.export())
        assertEquals(SyncEngine.FILE, c.kind)
        assertEquals(listOf("library", "songbooks"), c.holds)
        assertNull(c.syncedBefore)
        val outcome = here.apply(c)
        assertEquals(there.state(), here.state())
        assertEquals(emptyList(), outcome.given, "a file takes nothing back")
        assertEquals(SyncEngine.FILE_STAGES.map { it.first }, stages.map { it.first }.distinct())
        assertEquals(mapOf("check" to "done", "take" to "done", "mirror" to "done", "agree" to "done", "index" to "skipped"),
                     ended())
        assertEquals(listOf(outcome.taken), here.pagesHanded.map { it.second })
        val report = outcome.report!!
        assertEquals(JsonObject(mapOf("name" to JsonPrimitive("Desk"), "kind" to JsonPrimitive("file"),
                                      "address" to JsonPrimitive(null as String?))), report["with"])
        assertEquals(JsonArray(listOf(JsonPrimitive("library"), JsonPrimitive("songbooks"))), report["parts"])
        // The agreement is the file's caracole's, at its made: on every unit the two now hold alike.
        val base = here.database.read { Compare.baseOf(it, there.id) }!!
        assertEquals(there.state().mapValues { it.value.digest to MADE }, base)
    }

    @Test fun aSongbooksOnlyFileRemovesNoSongItDoesntHold() {
        val there = Caracole("sync/fixtures/rich.jsonl")
        val here = Caracole()
        val own = here.add("Muse", "Hysteria")
        val file = there.export(parts = listOf(Scope.SONGBOOKS))
        val c = here.engine.compareFile(file)
        assertEquals(listOf("songbooks"), c.holds)
        assertTrue(c.differences.none { it.id == "song/${own.key}" }, "a song the file doesn't speak for: no difference")
        val outcome = here.apply(c, prefer = Side.THERE)
        assertTrue("songbook/campfire" in outcome.taken)
        assertTrue("song/${own.key}" in here.state(), "Hysteria stays")
        // The base of a unit the file says nothing of is never written.
        val base = here.database.read { Compare.baseOf(it, there.id) }!!
        assertTrue("song/${own.key}" !in base, "$base")
    }

    @Test fun aFilesUnitItDoesntHoldShowsNoDocumentThereNeverAnError() {
        val there = Caracole("sync/fixtures/rich.jsonl")
        val here = Caracole()
        val own = here.add("Muse", "Hysteria")
        val c = here.engine.compareFile(there.export(parts = listOf(Scope.SONGBOOKS)))
        val (mine, theirs) = here.engine.documents(c, "song/${own.key}")
        assertTrue(mine != null && theirs == null, "the file holds no library: nothing of it there")
        assertTrue(here.engine.documents(c, "songbook/campfire").second != null, "a songbook it holds is shown")
        assertEquals(null to null, here.engine.documents(c, "songbook/not-here"))
    }

    @Test fun theSameFileTwiceThePhonesOwnExportOrAnOlderFileIsRefusedAndChangesNothing() {
        val there = Caracole("sync/fixtures/rich.jsonl")
        val here = Caracole()
        val file = there.export()
        here.apply(here.engine.compareFile(file))
        val (state, kv) = here.state() to here.kv()

        val twice = assertFailsWith<FileError> { here.engine.compareFile(file) }
        assertEquals(FileError.older("Desk", "03/11/26"), twice.message)
        val older = there.export(made = "2026-11-02T08:00:00Z")
        assertEquals(FileError.older("Desk", "03/11/26"), assertFailsWith<FileError> { here.engine.compareFile(older) }.message)
        val own = here.export()
        assertEquals(FileError.OWN_EXPORT, assertFailsWith<FileError> { here.engine.compareFile(own) }.message)
        assertEquals(FileError.NOT_A_FILE,
                     assertFailsWith<FileError> { here.engine.compareFile(tmp.newFile().apply { writeText("hello") }) }.message)
        assertEquals(state, here.state())
        assertEquals(kv, here.kv())
        // A newer file of theirs is taken.
        here.engine.compareFile(there.export(made = "2026-11-04T08:00:00Z"))
    }

    @Test fun aConflictKeptHereIsRememberedWithBothDigestsAtTheFilesMade() {
        val there = Caracole()
        val here = Caracole()
        val theirs = there.add("Oasis", "Wonderwall", "(What's the Story) Morning Glory?")
        here.add("Oasis", "Wonderwall", "Morning Glory")
        val unit = "song/${theirs.key}"
        val c = here.engine.compareFile(there.export())
        assertEquals(listOf(unit to Compare.CONFLICT), c.differences.map { it.id to it.proposal })
        assertFailsWith<SyncFailed> { here.apply(c) }  // asked, not chosen: refused before any change
        stages.clear()
        val outcome = here.apply(c, mapOf(unit to Side.HERE))
        assertEquals(emptyList(), outcome.taken)
        val (mine, file) = here.state().getValue(unit).digest to there.state().getValue(unit).digest
        assertEquals(mapOf(unit to KeptEntry(mine, file, MADE)), here.database.read { Compare.keptOf(it, there.id) })
        assertTrue(stages.last { it.first == "agree" }.third.endsWith(", 1 kept here"), "${stages.last { it.first == "agree" }}")
        // Unattended, a conflict is left and nothing of it remembered.
        val other = Caracole()
        other.add("Oasis", "Wonderwall", "Morning Glory")
        val left = other.apply(other.engine.compareFile(there.export(made = "2026-11-03T22:00:00Z")), conflicts = Conflicts.LEAVE)
        assertEquals(listOf(unit to SyncEngine.UNSETTLED), left.left)
        assertEquals(emptyMap(), other.database.read { Compare.keptOf(it, there.id) })
    }

    @Test fun anIndexFileMergesItsIndexesAndRecordsNoAgreement() {
        val here = Caracole()
        val file = File(tmp.newFolder(), "upload.part").also { it.delete() }
        Fixtures.loadRaw(file, "index/fixtures/full-export.jsonl")
        val c = here.engine.compareFile(file, "indexes.sqlite")
        assertEquals(listOf("indexes"), c.holds)
        assertEquals(emptyList(), c.differences)
        val outcome = here.apply(c)
        assertEquals(mapOf("check" to "done", "take" to "skipped", "mirror" to "skipped", "agree" to "skipped", "index" to "done"),
                     ended())
        assertTrue(outcome.indexed.isNotEmpty())
        assertTrue(here.database.read { db -> db.one("SELECT COUNT(*) FROM gtptabs_index") { it.long(0) } }!! > 0)
        assertEquals(emptyList(), here.kv().filter { it.first!!.startsWith("sync:base:") })
        val entries = (outcome.report!!["indexes"] as JsonArray).map { it as JsonObject }
        assertTrue(entries.isNotEmpty() && entries.all { it["direction"] == JsonPrimitive("taken") }, "$entries")
        assertEquals(File(here.dir, "state/cache").listFiles().orEmpty().toList(), emptyList())
    }

    @Test fun theUnitsTakenFromAFileAreHandedToThePagesHookAndNoneWhenNothingWasTaken() {
        val there = Caracole()
        val song = there.add("Muse", "Hysteria")
        val here = Caracole()
        val outcome = here.apply(here.engine.compareFile(there.export()))
        assertEquals(listOf("song/${song.key}"), outcome.taken)
        assertEquals(listOf(listOf("song/${song.key}")), here.pagesHanded.map { it.second })
        assertEquals(there.id, here.pagesHanded.single().first.id)
        stages.clear()
        val again = here.apply(here.engine.compareFile(there.export(made = "2026-11-05T08:00:00Z")))
        assertEquals(emptyList(), again.taken)
        assertEquals(1, here.pagesHanded.size, "nothing taken: the hook isn't called")
        assertEquals(Triple("mirror", "skipped", "nothing taken"), stages.last { it.first == "mirror" })
    }

    @Test fun anImportComparedAgainOnceTheFileChangedUnderItIsRefusedStale() {
        val there = Caracole()
        there.add("Muse", "Hysteria")
        val here = Caracole()
        val file = there.export()
        val c = here.engine.compareFile(file)
        assertEquals(c.hash, here.engine.compareFile(file).hash, "the same file, the same comparison")
        there.add("Oasis", "Wonderwall")
        there.export(made = "2026-11-04T08:00:00Z").copyTo(file, overwrite = true)
        assertEquals(SyncEngine.STALE, assertFailsWith<SyncFailed> { here.apply(c) }.message)
        assertEquals(emptySet(), here.state().keys, "nothing taken")
        assertTrue(Instant.parse(MADE) < Instant.parse("2026-11-04T08:00:00Z"))
    }

    private companion object {
        const val MADE = "2026-11-03T21:10:00Z"
    }
}
