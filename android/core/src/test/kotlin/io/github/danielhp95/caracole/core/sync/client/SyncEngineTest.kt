package io.github.danielhp95.caracole.core.sync.client

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Have
import io.github.danielhp95.caracole.core.index.Merge
import io.github.danielhp95.caracole.core.index.MergeProgress
import io.github.danielhp95.caracole.core.index.MergedIndexes
import io.github.danielhp95.caracole.core.index.Reads
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.index.Sizes as CataloguesSizes
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.Comparison
import io.github.danielhp95.caracole.core.sync.Conflicts
import io.github.danielhp95.caracole.core.sync.IndexWaiting
import io.github.danielhp95.caracole.core.sync.KeptPair
import io.github.danielhp95.caracole.core.sync.Scope
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.PeerError
import io.github.danielhp95.caracole.core.sync.Side
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.SyncFailed
import io.github.danielhp95.caracole.core.sync.SyncOutcome
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.sync.file.IndexFile
import io.github.danielhp95.caracole.core.sync.file.SyncFiles
import io.github.danielhp95.caracole.core.testing.Dumps
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.sync.FakeComputer
import io.github.danielhp95.caracole.mirror.ServerAddress
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.time.Duration
import java.time.Instant
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * A whole sync the phone starts, against FakeComputer: the computer's peer routes over a library of its own, taken
 * from and pushed to as caracole serve does. Each side's library is made through LibraryStore, as songs are added.
 */
class SyncEngineTest {
    @get:Rule val tmp = TemporaryFolder()

    private lateinit var phone: Database
    private lateinit var phoneLibrary: File
    private lateinit var phoneStore: LibraryStore
    private lateinit var stateDir: File
    private lateinit var computer: FakeComputer
    private lateinit var engine: SyncEngine
    private val stages = CopyOnWriteArrayList<Triple<String, String, String>>()

    @Before fun up() {
        val dir = tmp.newFolder("phone")
        phone = TestDb.fresh(dir)
        phoneLibrary = File(dir, "library").apply { mkdirs() }
        phoneStore = LibraryStore(phoneLibrary)
        stateDir = tmp.newFolder("state")
        computer = FakeComputer(tmp.newFolder("computer"))
        engine = engine()
    }

    @After fun down() {
        if (::computer.isInitialized) computer.close()
        if (::phone.isInitialized) phone.close()
    }

    private fun engine(mirror: (suspend (String, (String) -> Unit) -> Unit)? = null) =
        SyncEngine(phone, phoneStore, stateDir, client = { PeerClient(ServerAddress.parse(it)) }, mirrorRefresh = mirror)
            .also { it.pollEveryMs = 10 }

    private fun add(database: Database, store: LibraryStore, artist: String, title: String, album: String? = null): SongRow =
        database.writeBlocking { store.add(it, artist, title, album = album, now = NOW) }

    private fun onPhone(artist: String, title: String, album: String? = null) = add(phone, phoneStore, artist, title, album)
    private fun onComputer(artist: String, title: String, album: String? = null) =
        add(computer.database, computer.store, artist, title, album)

    private fun phoneState() = phone.read { Units.libraryState(it) }
    private val phoneId: String get() = phone.read { Compare.ownId(it) }

    private fun apply(c: Comparison, choices: Map<String, Side> = emptyMap(), prefer: Side? = null,
                      on: SyncEngine = engine, parts: List<String> = Scope.PARTS,
                      conflicts: Conflicts = Conflicts.ASK): SyncOutcome = runBlocking {
        on.apply(c, choices, prefer, parts, conflicts) { name, state, detail -> stages.add(Triple(name, state, detail)) }
    }

    /** Each stage's last state. */
    private fun ended(): Map<String, String> = stages.associate { (name, state, _) -> name to state }

    private fun unitOf(song: SongRow) = "song/${song.key}"

    @Test fun `a first sync both ways, a conflict chosen, ends with the two alike and both bases agreeing`() {
        val hysteria = onPhone("Muse", "Hysteria")
        val wonderwall = onPhone("Oasis", "Wonderwall", album = "Morning Glory")
        val creep = onComputer("Radiohead", "Creep")
        onComputer("Oasis", "Wonderwall", album = "(What's the Story) Morning Glory?")

        val c = engine.compare(computer.address.toString())
        assertNull(c.syncedBefore)
        assertEquals("Desk", c.peer.name)
        assertEquals(computer.id, c.peer.server)
        assertEquals(mapOf(unitOf(hysteria) to "mine", unitOf(wonderwall) to "conflict", unitOf(creep) to "theirs"),
                     c.differences.associate { it.id to it.proposal })
        assertEquals(Compare.comparedHash(c.differences), c.hash)
        assertEquals(c, engine.comparison(c.id))

        val outcome = apply(c, mapOf(unitOf(wonderwall) to Side.THERE))
        assertEquals(setOf(unitOf(creep), unitOf(wonderwall)), outcome.taken.toSet())
        assertEquals(listOf(unitOf(hysteria)), outcome.given)
        assertEquals(emptyList(), outcome.left)
        assertEquals(3, outcome.agreed)
        assertEquals(emptyList(), outcome.indexed)

        val phoneNow = phoneState()
        assertEquals(computer.state(), phoneNow)
        val phoneBase = assertNotNull(phone.read { Compare.baseOf(it, computer.id) })
        val computerBase = assertNotNull(computer.database.read { Compare.baseOf(it, phoneId) })
        for ((id, unit) in phoneNow) {
            assertEquals(unit.digest, phoneBase[id]?.first, "the phone's base of $id")
            assertEquals(unit.digest, computerBase[id]?.first, "the computer's base of $id")
        }
        assertEquals(mapOf("compare" to "done", "take" to "done", "give" to "done", "mirror" to "skipped",
                           "agree" to "done", "index" to "skipped"), ended())
        assertEquals(SyncEngine.STAGES.map { it.first }, stages.map { it.first }.distinct())

        // GET /api/sync's record of the computer, and a comparison again finds nothing.
        val peer = assertNotNull(phone.read { it.kvGetJson(SyncEngine.PEER_KEY + computer.id) } as? JsonObject)
        assertEquals(listOf("address", "name", "synced_at"), peer.keys.toList())
        assertEquals(JsonPrimitive(computer.address.toString()), peer["address"])
        assertEquals(JsonPrimitive("Desk"), peer["name"])
        assertEquals(JsonPrimitive(computer.now), peer["synced_at"])
        val again = engine.compare(computer.address.toString())
        assertEquals(computer.now, again.syncedBefore, "when the two last agreed")
        assertEquals(emptyList(), again.differences)
    }

    @Test fun `an empty phone takes the computer's whole library from the sync fixture, files and all`() {
        computer.load(RICH)
        val c = engine.compare(computer.address.toString())
        assertTrue(c.differences.all { it.proposal == "theirs" }, c.differences.toString())
        val outcome = apply(c)
        assertEquals(c.differences.map { it.id }.toSet(), outcome.taken.toSet())
        assertEquals(emptyList(), outcome.left)
        assertEquals(computer.state(), phoneState())
        val files = phone.read { db -> db.query("SELECT path, sha256 FROM files ORDER BY path") { it.text(0)!! to it.text(1)!! } }
        assertTrue(files.isNotEmpty())
        for ((path, sha) in files) assertEquals(sha, Canonical.sha256Hex(File(phoneLibrary, path).readBytes()), path)
        assertEquals(files.size, computer.asked("GET", "/api/peer/file").size)
    }

    @Test fun `an empty computer takes the phone's whole library from the sync fixture, each file sent once`() {
        phone.writeBlocking { io.github.danielhp95.caracole.core.testing.Fixtures.load(it, RICH, phoneLibrary) }
        val c = engine.compare(computer.address.toString())
        assertTrue(c.differences.all { it.proposal == "mine" }, c.differences.toString())
        val outcome = apply(c)
        assertEquals(c.differences.map { it.id }.toSet(), outcome.given.toSet())
        assertEquals(computer.state(), phoneState())
        val shas = phone.read { db -> db.query("SELECT DISTINCT sha256 FROM files") { it.text(0)!! } }
        assertEquals(shas.size, computer.asked("POST", "/peer/push/file").size)
        val base = assertNotNull(computer.database.read { Compare.baseOf(it, phoneId) })
        assertEquals(phoneState().mapValues { it.value.digest }, base.filterValues { it.first != null }.mapValues { it.value.first })
    }

    @Test fun `the push carries the phone's state after its take, and a file only once the computer needs it`() {
        val song = onPhone("Estopa", "Tu Calorro")
        val bytes = "a Guitar Pro file".toByteArray()
        val sha = Canonical.sha256Hex(bytes)
        val folder = phoneStore.folderOf(song)
        val path = folder.relativeTo(phoneLibrary).path + "/guitar-1.gp5"
        File(phoneLibrary, path).apply { parentFile.mkdirs(); writeBytes(bytes) }
        phone.writeBlocking { db ->
            db.execute("INSERT INTO versions (provider, tab_id, song_id, slot, kind, url, fetched_at) " +
                       "VALUES ('inbox', 'guitar-1', ?, 'guitar', 'guitar', '', ?)", song.id, NOW)
            db.execute("INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) " +
                       "VALUES (?, ?, 'guitar-1.gp5', ?, ?, 0, ?)", db.lastRowid(), song.id, path, sha, NOW)
        }
        onComputer("Soda Stereo", "Persiana Americana")

        val outcome = apply(engine.compare(computer.address.toString()))
        assertEquals(listOf(unitOf(song)), outcome.given)
        assertEquals(1, computer.asked("POST", "/peer/push/file").size)
        // Each file sent counted as "N of M files", a count the notification's bar fills by (Working.counted).
        assertTrue(Triple("give", "running", "1 of 1 file") in stages, stages.joinToString("\n"))
        val push = computer.pushes.single()
        assertEquals(phoneId, (push["from"] as JsonPrimitive).content)
        assertEquals(JsonPrimitive(computer.now), push["at"])
        assertEquals(phoneState().keys, (push["units"] as JsonObject).keys, "the phone's whole state, after its take")
        assertEquals(computer.state(), phoneState())
        val kept = computer.database.read { db -> db.one("SELECT path FROM files WHERE sha256 = ?", sha) { it.text(0) } }
        assertEquals(bytes.toList(), File(computer.libraryDir, assertNotNull(kept)).readBytes().toList())
    }

    @Test fun `a conflict with neither a choice nor a side preferred is refused before anything changes`() {
        onPhone("Oasis", "Wonderwall", album = "A")
        onComputer("Oasis", "Wonderwall", album = "B")
        val c = engine.compare(computer.address.toString())
        computer.requests.clear()
        val before = phoneState()
        val refused = assertFailsWith<SyncFailed> { apply(c) }
        assertTrue("every conflict" in refused.message!!, refused.message)
        assertNull(refused.outcome)
        assertEquals(emptyList(), computer.requests)
        assertEquals(before, phoneState())
        assertEquals(emptyList(), stages)

        // prefer settles every conflict at once.
        val outcome = apply(c, prefer = Side.HERE)
        assertEquals(c.differences.map { it.id }, outcome.given)
        assertEquals(computer.state(), phoneState())
    }

    @Test fun `a skipped difference is left, and neither side takes it`() {
        val song = onComputer("Radiohead", "Creep")
        val outcome = apply(engine.compare(computer.address.toString()), mapOf(unitOf(song) to Side.SKIP))
        assertEquals(listOf(unitOf(song) to "skipped, as you chose"), outcome.left)
        assertEquals(emptyMap(), phoneState())
        assertEquals("skipped", ended()["take"])
        assertEquals("skipped", ended()["give"])
    }

    @Test fun `a proposal flipped goes the other way`() {
        val song = onComputer("Radiohead", "Creep")
        val c = engine.compare(computer.address.toString())
        assertEquals("theirs", c.differences.single().proposal)
        val outcome = apply(c, mapOf(unitOf(song) to Side.HERE))  // here's: none, so the computer removes it
        assertEquals(listOf(unitOf(song)), outcome.given)
        assertEquals(emptyMap(), computer.state().filterKeys { it.startsWith("song/") })
    }

    @Test fun `a form token the computer changed mid-sync is read again, and the push goes through`() {
        onPhone("Muse", "Hysteria")
        onComputer("Radiohead", "Creep")
        val c = engine.compare(computer.address.toString())
        // caracole serve restarts as the phone takes, after the state the sync's compare read.
        computer.onUnit = { computer.token = "computer-token-2" }
        val outcome = apply(c)
        assertEquals(1, outcome.taken.size)
        assertEquals(1, outcome.given.size)
        assertEquals(2, computer.asked("POST", "/peer/push/new").size)
        assertEquals(1, computer.asked("POST", "/peer/push").size)
        assertEquals(computer.state(), phoneState())
    }

    @Test fun `a unit the computer changed between the comparison and its take is left, and the rest taken`() {
        val creep = onComputer("Radiohead", "Creep")
        val karma = onComputer("Radiohead", "Karma Police")
        val c = engine.compare(computer.address.toString())
        computer.onUnit = { id ->
            if (id == unitOf(creep)) {
                computer.database.writeBlocking { it.execute("UPDATE songs SET album = 'Pablo Honey' WHERE key = ?", creep.key) }
            }
        }
        val outcome = apply(c)
        assertEquals(listOf(unitOf(karma)), outcome.taken)
        assertEquals(listOf(unitOf(creep) to "changed there since compared"), outcome.left)
        assertEquals(setOf(unitOf(karma)), phoneState().keys)
        // The base records what the two hold alike alone.
        val base = assertNotNull(phone.read { Compare.baseOf(it, computer.id) })
        assertNull(base[unitOf(creep)]?.first)
    }

    @Test fun `two libraries changed since the comparison are refused at its stage, before any change`() {
        onComputer("Radiohead", "Creep")
        val c = engine.compare(computer.address.toString())
        onComputer("Radiohead", "Karma Police")
        val refused = assertFailsWith<SyncFailed> { apply(c) }
        assertEquals("Both books changed since that comparison. Compare again, then choose again.", refused.message)
        assertEquals(SyncEngine.STALE, stages.last().third)
        assertEquals("failed", ended()["compare"])
        assertEquals(setOf("compare"), ended().keys)
        assertEquals(emptyMap(), phoneState())
    }

    @Test fun `a push the computer fails to take leaves what was given, its base as it was, and the sync goes on`() {
        val hysteria = onPhone("Muse", "Hysteria")
        val creep = onComputer("Radiohead", "Creep")
        computer.takeFails = "database is locked"
        val outcome = apply(engine.compare(computer.address.toString()))
        assertEquals(listOf(unitOf(creep)), outcome.taken)
        assertEquals(emptyList(), outcome.given)
        assertEquals(listOf(unitOf(hysteria) to "their Journal entry 1: failed"), outcome.left, "as peer sync --push says it")
        assertEquals("done", ended()["give"])
        assertEquals("done", ended()["agree"])
        assertEquals(1, outcome.agreed)
        val base = assertNotNull(phone.read { Compare.baseOf(it, computer.id) })
        assertEquals(setOf(unitOf(creep)), base.keys, "what the two hold alike alone")
        assertNull(computer.database.read { Compare.baseOf(it, phoneId) }, "the computer's take recorded nothing")
        assertEquals(0, computer.pushesHere, "the push is gone once its take is over")
        // The next sync gives it again.
        computer.takeFails = null
        val again = apply(engine.compare(computer.address.toString()))
        assertEquals(listOf(unitOf(hysteria)), again.given)
        assertEquals(computer.state(), phoneState())
    }

    @Test fun `each unit the computer's take leaves is left on the phone too, in its words`() {
        val hysteria = onPhone("Muse", "Hysteria")
        val karma = onPhone("Radiohead", "Karma Police")
        val c = engine.compare(computer.address.toString())
        // The computer gets a Karma Police of its own after the phone compared, before its push is taken.
        computer.holdTakes = java.util.concurrent.CountDownLatch(1)
        computer.onPoll = {
            if (computer.holdTakes != null) {
                onComputer("Radiohead", "Karma Police", album = "OK Computer")
                computer.holdTakes!!.countDown()
                computer.holdTakes = null
            }
        }
        val outcome = apply(c)
        assertEquals(listOf(unitOf(hysteria)), outcome.given)
        assertEquals(listOf(unitOf(karma) to "changed here since compared"), outcome.left)
    }

    @Test fun `the computer's request is followed with no lock held on the phone's database`() {
        onPhone("Muse", "Hysteria")
        computer.runningPolls = 3
        val locked = CopyOnWriteArrayList<Boolean>()
        computer.onPoll = { locked.add(phone.writes.isLocked) }
        val outcome = apply(engine.compare(computer.address.toString()))
        assertEquals(1, outcome.given.size)
        assertEquals(List(4) { false }, locked)
    }

    @Test fun `the index stage fetches only the sites newer there, and a merge that fails leaves the agreement`() {
        onComputer("Radiohead", "Creep")
        phone.writeBlocking { db ->
            db.kvSetJson(SyncEngine.INDEX_KEY + computer.id, JsonObject(mapOf(
                "lacuerda" to JsonPrimitive("2026-11-03T00:00:00Z"), "ug" to JsonPrimitive("2026-11-02T00:00:00Z"))))
        }
        computer.indexes = mapOf("ug" to "2026-11-03T10:00:00Z", "lacuerda" to "2026-11-03T00:00:00Z",
                                 "gtptabs" to "2026-10-01T00:00:00Z", "spotify" to "2026-11-03T10:00:00Z")
        computer.index = { "not an index export".toByteArray() }
        val outcome = apply(engine.compare(computer.address.toString()))
        assertEquals(listOf<List<String>?>(listOf("ug", "gtptabs")), computer.indexAsked,
                     "the sites the phone knows, newer there, in caracole's order")
        assertEquals(emptyList(), outcome.indexed)
        assertEquals("failed", ended()["index"])
        assertEquals(1, outcome.agreed)
        assertNotNull(phone.read { Compare.baseOf(it, computer.id) })
        assertEquals("""{"lacuerda": "2026-11-03T00:00:00Z", "ug": "2026-11-02T00:00:00Z"}""",
                     phone.read { it.kvGet(SyncEngine.INDEX_KEY + computer.id) })
        assertEquals(emptyList(), File(stateDir, "cache").listFiles().orEmpty().toList(), "the file fetched is gone")
    }

    @Test fun `with no index newer there, the index stage asks for none`() {
        onComputer("Radiohead", "Creep")
        computer.indexes = mapOf("ug" to "2026-11-03T10:00:00Z")
        phone.writeBlocking { it.kvSetJson(SyncEngine.INDEX_KEY + computer.id, JsonObject(mapOf("ug" to JsonPrimitive("2026-11-03T10:00:00Z")))) }
        apply(engine.compare(computer.address.toString()))
        assertEquals(emptyList(), computer.indexAsked)
        assertEquals("skipped", ended()["index"])
        assertEquals(SyncEngine.NOTHING_TO_INDEX, stages.last { it.first == "index" }.third)
        assertEquals(emptyList(), computer.asked("POST", "/peer/index"), "no page read here: nothing sent")
    }

    // --- the index stage's push: the pages the phone's lookups read --------------------------------------------------

    /** A harptabs.com artist page a lookup stored on the phone at [at], noted as its store notes it (Reads.note with
     * the path harptabs_artists holds). */
    private fun readHere(path: String, titles: List<String>, at: String) = phone.writeBlocking { db ->
        db.execute("INSERT OR REPLACE INTO harptabs_artists (path, page_id, key, name, tabs, read_at) VALUES " +
                       "(?, ?, ?, ?, ?, ?)", path, path.split('/')[1].toLong(), path.substringAfterLast('/'),
                   path.substringAfterLast('/'), titles.size.toLong(), at)
        titles.forEachIndexed { n, title ->
            db.execute("INSERT OR REPLACE INTO harptabs_artist_tabs (artist, tab_id, path, title, song_key, place) " +
                           "VALUES (?, ?, ?, ?, ?, ?)", path, 100L + n, "tab/${100 + n}/x", title, title.lowercase(),
                       n.toLong())
        }
        Reads.note(db, "harptabs", path, at)
    }

    private fun computerTabs(): Map<String, Long> = computer.database.read { db ->
        db.query("SELECT artist, COUNT(*) FROM harptabs_artist_tabs GROUP BY artist ORDER BY artist") {
            it.text(0)!! to it.long(1)!!
        }.toMap()
    }

    private fun noted(): Map<String, List<String>> = phone.read { Reads.since(it, computer.id) }

    /** kv `sync:index:<computer id>`: what the phone holds of the computer's indexes. */
    private fun held(): String? = phone.read { it.kvGet(SyncEngine.INDEX_KEY + computer.id) }

    /** The phone holds the computer's harptabs.com index as of [at], as an earlier sync took it. */
    private fun holdingHarptabs(at: String) = phone.writeBlocking { db ->
        db.kvSetJson(SyncEngine.INDEX_KEY + computer.id, JsonObject(mapOf("harptabs" to JsonPrimitive(at))))
    }

    @Test fun `the pages read here are pushed though nothing is newer there, and forgotten once their merge is done`() {
        onComputer("Radiohead", "Creep")
        readHere("artist/1178/billy-joel", listOf("Piano Man", "Honesty"), "2026-11-03T09:00:00Z")
        readHere("artist/50/the-beatles", listOf("Yesterday"), "2026-11-03T09:30:00Z")

        val outcome = apply(engine.compare(computer.address.toString()))

        assertEquals(emptyList(), computer.indexAsked, "nothing newer there: no index fetched")
        assertEquals(emptyList(), outcome.indexed)
        assertEquals("done", ended()["index"])
        val detail = stages.last { it.first == "index" }.third
        assertTrue(detail.startsWith("sent 2 pages read here · its request "), detail)
        assertTrue(detail.endsWith(" merged them"), detail)
        assertEquals(1, computer.indexPushes.size)
        assertEquals(mapOf("artist/1178/billy-joel" to 2L, "artist/50/the-beatles" to 1L), computerTabs())
        assertEquals("done", computer.jobs().last()["state"].let { (it as JsonPrimitive).content })
        assertEquals(emptyMap(), noted(), "forgotten once the computer merged them")
        assertEquals("""{"harptabs": "2026-11-03T09:30:00Z"}""", held(),
                     "the computer's harptabs.com index is the phone's own pages: held here as it is there")
        assertEquals(emptyList(), File(stateDir, "cache").listFiles().orEmpty().toList(), "the export is gone")

        // The next sync, with nothing read since, sends nothing and asks for no index; a page read since goes alone.
        stages.clear()
        apply(engine.compare(computer.address.toString()))
        assertEquals("skipped", ended()["index"])
        assertEquals(emptyList(), computer.indexAsked, "the computer's newest read of harptabs.com is the phone's page")
        assertEquals(1, computer.indexPushes.size)
        readHere("artist/7/bob-dylan", listOf("Blowin' in the Wind"), "2026-11-03T11:00:00Z")
        stages.clear()
        apply(engine.compare(computer.address.toString()))
        assertEquals(2, computer.indexPushes.size)
        computer.awaitTakes()
        assertEquals(mapOf("artist/1178/billy-joel" to 2L, "artist/50/the-beatles" to 1L, "artist/7/bob-dylan" to 1L),
                     computerTabs())
    }

    @Test fun `the pages read here are pushed after a newer index there is merged`() {
        onComputer("Radiohead", "Creep")
        val export = tmp.newFile("export.sqlite").also { it.delete() }
        io.github.danielhp95.caracole.core.testing.Fixtures.loadRaw(export, "index/fixtures/full-export.jsonl")
        computer.index = { export.readBytes() }
        computer.indexes = mapOf("gtptabs" to "2026-11-03T10:00:00Z")
        readHere("artist/50/the-beatles", listOf("Yesterday"), "2026-11-03T09:30:00Z")

        val outcome = apply(engine.compare(computer.address.toString()))

        assertEquals(listOf("gtptabs"), outcome.indexed)
        assertEquals("done", ended()["index"])
        val detail = stages.last { it.first == "index" }.third
        assertTrue(detail.startsWith("merged gtptabs; sent 1 page read here · its request "), detail)
        val asked = computer.requests.filter { it.startsWith("GET /api/peer/index") || it == "POST /peer/index" }
        assertEquals(listOf("GET /api/peer/index?sites=gtptabs", "POST /peer/index"), asked,
                     "the computer's index merged first, then the phone's pushed")
        assertEquals(emptyMap(), noted())
    }

    @Test fun `a merge that fails there pushes the pages read here all the same`() {
        onComputer("Radiohead", "Creep")
        computer.indexes = mapOf("gtptabs" to "2026-11-03T10:00:00Z")
        computer.index = { "not an index export".toByteArray() }
        readHere("artist/50/the-beatles", listOf("Yesterday"), "2026-11-03T09:30:00Z")

        val outcome = apply(engine.compare(computer.address.toString()))

        assertEquals(emptyList(), outcome.indexed)
        assertEquals("failed", ended()["index"], "the merge's failure is said")
        val detail = stages.last { it.first == "index" }.third
        assertTrue(";" in detail && "sent 1 page read here" in detail.substringAfter("; "), detail)
        assertEquals(1, computer.indexPushes.size)
        assertEquals(emptyMap(), noted())
        assertEquals(1, outcome.agreed, "the agreement stays")
    }

    @Test fun `a push the computer refuses keeps the pages read here for the next sync, in its words`() {
        onComputer("Radiohead", "Creep")
        readHere("artist/50/the-beatles", listOf("Yesterday"), "2026-11-03T09:30:00Z")
        computer.answers["POST /peer/index"] = { exchange ->
            exchange.requestBody.readBytes()
            FakeComputer.json(exchange, 409, FakeComputer.obj("error" to JsonPrimitive(
                "The index export was exported at schema version 16, and this caracole's database is at 15.")))
        }

        val outcome = apply(engine.compare(computer.address.toString()))

        assertEquals("failed", ended()["index"])
        assertEquals("1 page read here kept for the next share · ${computer.address} answered 409: " +
                         "The index export was exported at schema version 16, and this caracole's database is at 15.",
                     stages.last { it.first == "index" }.third)
        assertEquals(mapOf("harptabs" to listOf("artist/50/the-beatles")), noted())
        assertEquals(1, outcome.agreed, "a push that fails stops nothing")
        assertEquals(emptyList(), File(stateDir, "cache").listFiles().orEmpty().toList())

        // Taken the next time, as the two agree.
        computer.answers.remove("POST /peer/index")
        stages.clear()
        apply(engine.compare(computer.address.toString()))
        assertEquals("done", ended()["index"])
        assertEquals(emptyMap(), noted())
    }

    @Test fun `a computer older than the push keeps the pages read here and says so`() {
        onComputer("Radiohead", "Creep")
        readHere("artist/50/the-beatles", listOf("Yesterday"), "2026-11-03T09:30:00Z")
        computer.answers["POST /peer/index"] = { exchange ->
            exchange.requestBody.readBytes()
            FakeComputer.json(exchange, 404, FakeComputer.obj("error" to JsonPrimitive("Not found")))
        }
        apply(engine.compare(computer.address.toString()))
        assertEquals("1 page read here kept for the next share · ${computer.address} takes no index " +
                         "pages: its caracole may be older than the app.", stages.last { it.first == "index" }.third)
        assertEquals(mapOf("harptabs" to listOf("artist/50/the-beatles")), noted())
    }

    @Test fun `a merge that fails there keeps the pages read here for the next sync, and the stage says so`() {
        onComputer("Radiohead", "Creep")
        readHere("artist/50/the-beatles", listOf("Yesterday"), "2026-11-03T09:30:00Z")
        computer.mergeFails = "Nothing merged: no backup first (not enough room)."

        val outcome = apply(engine.compare(computer.address.toString()))

        assertEquals("failed", ended()["index"])
        assertEquals("1 page read here kept for the next share · ${computer.address} didn't merge it: its " +
                         "Journal entry 1 ended failed.", stages.last { it.first == "index" }.third)
        assertEquals(mapOf("harptabs" to listOf("artist/50/the-beatles")), noted(), "never merged there: kept here")
        assertNull(held())
        assertEquals(1, outcome.agreed, "a merge that fails there stops nothing")

        // Merged the next time.
        computer.mergeFails = null
        stages.clear()
        apply(engine.compare(computer.address.toString()))
        assertEquals("done", ended()["index"])
        assertEquals(emptyMap(), noted())
        assertEquals(mapOf("artist/50/the-beatles" to 1L), computerTabs())
    }

    @Test fun `a merge still going there at the wait's end keeps the pages read here, sent again the next time`() {
        onComputer("Radiohead", "Creep")
        readHere("artist/50/the-beatles", listOf("Yesterday"), "2026-11-03T09:30:00Z")
        val slow = java.util.concurrent.CountDownLatch(1)
        computer.holdTakes = slow
        val waiting = engine().also { it.pollEveryMs = 5; it.polls = 3 }

        apply(waiting.compare(computer.address.toString()), on = waiting)

        assertEquals("failed", ended()["index"])
        assertEquals("1 page read here kept for the next share · ${computer.address} hasn't merged it yet: its " +
                         "Journal entry 1 goes on.", stages.last { it.first == "index" }.third)
        assertEquals(mapOf("harptabs" to listOf("artist/50/the-beatles")), noted())
        assertNull(held(), "nothing of the computer's held")

        slow.countDown()
        computer.holdTakes = null
        computer.awaitTakes()
        computer.index = { computersExport() }
        stages.clear()
        apply(engine.compare(computer.address.toString()))
        assertEquals("done", ended()["index"])
        assertEquals(listOf<List<String>?>(listOf("harptabs")), computer.indexAsked,
                     "a stamp moved by a merge the phone never saw done is taken: it may be the computer's own")
        assertEquals(2, computer.indexPushes.size, "sent again, merged again there to the same rows")
        assertEquals(mapOf("artist/50/the-beatles" to 1L), computerTabs())
        assertEquals(emptyMap(), noted())
    }

    // --- what the computer's stamps say once it merged the pages read here (sync hunt 2026-11-25) -------------------

    @Test fun `a page read here comes back with no whole index downloaded at the next sync`() {
        onComputer("Radiohead", "Creep")
        readThere("artist/1178/billy-joel", "Piano Man", "2026-11-03T03:00:00Z")
        computer.index = { computersExport() }
        readHere("artist/50/the-beatles", listOf("Yesterday"), "2026-11-03T09:30:00Z")

        apply(engine.compare(computer.address.toString()))

        assertEquals(listOf<List<String>?>(listOf("harptabs")), computer.indexAsked,
                     "the first sync takes the computer's harptabs.com index")
        assertEquals("2026-11-03T09:30:00Z", computer.database.read { IndexTransfer.newest(it) }["harptabs"],
                     "the computer's newest read of it is the phone's own page now")
        assertEquals("""{"harptabs": "2026-11-03T09:30:00Z"}""", held())

        // Nothing read anywhere since; the owner syncs again, or Sync on Wi-Fi does.
        stages.clear()
        val again = engine.compare(computer.address.toString())
        assertEquals(emptyList(), again.indexes, "no Site index waits")
        apply(again)
        assertEquals(1, computer.indexAsked.size,
                     "nothing read there but the phone's own page: no whole index downloaded again")
        assertEquals(Triple("index", "skipped", SyncEngine.NOTHING_TO_INDEX), stages.last { it.first == "index" })
    }

    @Test fun `the pages read here, pushed, never make the next sync download the index the phone took last time`() {
        onComputer("Radiohead", "Creep")
        readThere("artist/1178/billy-joel", "Piano Man", "2026-11-03T00:00:00Z")
        holdingHarptabs("2026-11-03T00:00:00Z")
        readHere("artist/50/the-beatles", listOf("Yesterday"), "2026-11-03T09:30:00Z")

        apply(engine.compare(computer.address.toString()))
        assertEquals(1, computer.indexPushes.size, "the page read here was pushed")
        assertEquals(emptyList(), computer.indexAsked)

        stages.clear()
        apply(engine.compare(computer.address.toString()))
        assertEquals(emptyList(), computer.indexAsked, "the computer's harptabs.com index holds nothing the phone " +
                         "lacks: " + stages.filter { it.first == "index" })
    }

    @Test fun `a page the computer read itself as it merged those read here is taken at the next sync`() {
        onComputer("Radiohead", "Creep")
        readThere("artist/1178/billy-joel", "Piano Man", "2026-11-03T03:00:00Z")
        computer.index = { computersExport() }
        readHere("artist/50/the-beatles", listOf("Yesterday"), "2026-11-03T09:30:00Z")
        // Its nightly pass reads another artist's page while the phone waits for the merge of those it pushed.
        val once = java.util.concurrent.atomic.AtomicBoolean(false)
        computer.onPoll = {
            if (once.compareAndSet(false, true)) {
                readThere("artist/7/bob-dylan", "Blowin' in the Wind", "2026-11-03T10:00:00Z")
            }
        }

        apply(engine.compare(computer.address.toString()))

        assertEquals(emptyMap(), noted(), "the pages read here merged there")
        assertEquals("""{"harptabs": "2026-11-03T03:00:00Z"}""", held(),
                     "a stamp later than the pages pushed is the computer's own news: never held here")
        stages.clear()
        val again = engine.compare(computer.address.toString())
        assertEquals(listOf("harptabs"), again.indexes.filter { it.newer == "there" }.map { it.site })
        apply(again)
        assertEquals(listOf<List<String>?>(listOf("harptabs"), listOf("harptabs")), computer.indexAsked)
        assertEquals(1L, phone.read { db ->
            db.one("SELECT COUNT(*) FROM harptabs_artist_tabs WHERE artist = 'artist/7/bob-dylan'") { it.long(0) }
        }, "the computer's own page taken")
    }

    @Test fun `a computer's index the phone failed to take is asked for again after the pages read here are pushed`() {
        onComputer("Radiohead", "Creep")
        readThere("artist/1178/billy-joel", "Piano Man", "2026-11-03T03:00:00Z")
        holdingHarptabs("2026-11-03T03:00:00Z")
        // Read there since the phone took it last; its download fails this time.
        readThere("artist/7/bob-dylan", "Blowin' in the Wind", "2026-11-03T09:00:00Z")
        computer.index = { "not an index export".toByteArray() }
        readHere("artist/50/the-beatles", listOf("Yesterday"), "2026-11-03T09:30:00Z")

        apply(engine.compare(computer.address.toString()))

        assertEquals("failed", ended()["index"], "the computer's index wasn't taken")
        assertEquals(emptyMap(), noted(), "the pages read here pushed and merged all the same")
        assertEquals("2026-11-03T09:30:00Z", computer.database.read { IndexTransfer.newest(it) }["harptabs"],
                     "the computer's newest read is the phone's page, later than its own")
        assertEquals("""{"harptabs": "2026-11-03T03:00:00Z"}""", held(),
                     "yet the phone lacks the computer's page of 09:00: what it holds of it stays as it was")

        computer.index = { computersExport() }
        stages.clear()
        apply(engine.compare(computer.address.toString()))
        assertEquals(listOf<List<String>?>(listOf("harptabs"), listOf("harptabs")), computer.indexAsked)
        assertEquals(1L, phone.read { db ->
            db.one("SELECT COUNT(*) FROM harptabs_artist_tabs WHERE artist = 'artist/7/bob-dylan'") { it.long(0) }
        })
    }

    @Test fun `pushIndex sends the export's bytes with the form token, and the computer's request is its answer`() {
        readHere("artist/50/the-beatles", listOf("Yesterday"), "2026-11-03T09:30:00Z")
        val file = File(tmp.newFolder(), "reads.sqlite")
        phone.writeBlocking { db ->
            io.github.danielhp95.caracole.core.index.IndexExport.export(db, file, Reads.since(db, "pc"), NOW)
        }
        val client = PeerClient(computer.address)

        val job = client.pushIndex(computer.token, file)

        assertTrue(job > 0)
        assertTrue(computer.indexPushes.single().contentEquals(file.readBytes()))
        assertEquals(listOf("POST /peer/index"), computer.asked("POST", "/peer/index"))

        // A token older than the server (it restarted since): its state read again, and the push sent with its own.
        computer.requests.clear()
        val again = client.pushIndex("an-older-token", file)
        assertTrue(again > job)
        assertEquals(listOf("POST /peer/index", "GET /api/peer/state", "POST /peer/index"), computer.requests.toList())
        assertEquals(2, computer.indexPushes.size)
    }

    @Test fun `an export past what the computer takes is never sent`() {
        val file = File(tmp.newFolder(), "huge.sqlite")
        RandomAccessFile(file, "rw").use { it.setLength(PeerClient.INDEX_MAX + 1) }
        val refused = assertFailsWith<PeerError> { PeerClient(computer.address).pushIndex(computer.token, file) }
        assertEquals("The pages read here make 65 MiB; the computer takes 64 MiB at most. " +
                         "They stay here.", refused.message)
        assertEquals(emptyList(), computer.asked("POST", "/peer/index"))
    }

    @Test fun `the mirror is brought up to date after the give, and its failure stops nothing`() {
        onComputer("Radiohead", "Creep")
        val asked = CopyOnWriteArrayList<String>()
        val mirrored = engine { address, _ -> asked.add(address); throw IOException("no space left") }
        val outcome = apply(mirrored.compare(computer.address.toString()), on = mirrored)
        assertEquals(listOf(computer.address.toString()), asked)
        assertEquals("failed", ended()["mirror"])
        assertTrue(stages.any { it.first == "mirror" && "no space left" in it.third })
        assertEquals("done", ended()["agree"])
        assertEquals(1, outcome.agreed)
    }

    // --- the computer's settings (docs/superpowers/specs/2026-11-03-politeness-crossing.md, "Settings") ---------

    private fun settingsHeld(): String? = phone.read { it.kvGet(PhoneConfig.SETTINGS_KV) }

    @Test fun `the agree stage takes the computer's settings as its state gave them there, and adds no stage`() {
        onComputer("Radiohead", "Creep")
        computer.settings = JsonObject(mapOf("user_agent" to JsonPrimitive("caracole/0.1 (at the comparison)")))
        val c = engine.compare(computer.address.toString())
        assertEquals(computer.settings, c.peer.settings)
        assertNull(settingsHeld(), "a comparison takes nothing")

        // The state agree reads is the one whose settings are taken: the computer's latest, never the comparison's
        // nor the one stage 1 reads again (the settings change on the computer while the phone takes its unit).
        computer.settings = JsonObject(mapOf("user_agent" to JsonPrimitive("caracole/0.1 (as the sync began)")))
        computer.onUnit = { computer.settings = FakeComputer.SETTINGS }
        val outcome = apply(c)
        assertEquals(listOf(c.differences.single().id), outcome.taken)
        assertEquals(1, outcome.agreed)
        assertEquals(PyJson.dumps(FakeComputer.SETTINGS), settingsHeld())
        assertEquals(SyncEngine.STAGES.map { it.first }, stages.map { it.first }.distinct())
        assertEquals("1 unit the books agree on", stages.last { it.first == "agree" }.third)
        assertEquals(emptyList(), engine.compare(computer.address.toString()).differences, "settings are no unit")
    }

    @Test fun `with nothing to take or give, the settings are taken all the same`() {
        computer.settings = FakeComputer.SETTINGS
        val outcome = apply(engine.compare(computer.address.toString()))
        assertEquals(SyncOutcome(emptyList(), emptyList(), emptyList(), 0, emptyList()), outcome.copy(report = null))
        assertEquals(mapOf("compare" to "done", "take" to "skipped", "give" to "skipped", "mirror" to "skipped",
                           "agree" to "done", "index" to "skipped"), ended())
        assertEquals(PyJson.dumps(FakeComputer.SETTINGS), settingsHeld())
    }

    @Test fun `a computer that gives no settings leaves the phone's as they were`() {
        phone.writeBlocking { PhoneConfig.take(it, FakeComputer.SETTINGS) }
        computer.settings = null
        onComputer("Radiohead", "Creep")
        apply(engine.compare(computer.address.toString()))
        assertEquals("done", ended()["agree"])
        assertEquals(PyJson.dumps(FakeComputer.SETTINGS), settingsHeld())
    }

    @Test fun `a sync that stops before it agrees takes no settings`() {
        computer.settings = FakeComputer.SETTINGS
        val c = engine.compare(computer.address.toString())
        onComputer("Radiohead", "Creep")
        assertFailsWith<SyncFailed> { apply(c) }
        assertEquals("failed", ended()["compare"])
        assertNull(settingsHeld())

        stages.clear()
        onPhone("Muse", "Hysteria")
        computer.answers["POST /peer/push/new"] = { exchange ->
            FakeComputer.json(exchange, 503, FakeComputer.obj("error" to JsonPrimitive("Busy.")))
        }
        assertFailsWith<SyncFailed> { apply(engine.compare(computer.address.toString())) }
        assertEquals("failed", ended()["give"])
        assertNull(ended()["agree"])
        assertNull(settingsHeld())
    }

    @Test fun `a comparison is kept by its id for 10 minutes`() {
        var now = Instant.parse("2026-11-03T12:00:00Z")
        engine.clock = { now }
        val c = engine.compare(computer.address.toString())
        now = now.plusSeconds(599)
        assertEquals(c, engine.comparison(c.id))
        now = now.plusSeconds(1)
        assertNull(engine.comparison(c.id))
        assertNull(engine.comparison("0123456789abcdef"))
    }

    @Test fun `a computer that is this phone's own database is refused`() {
        computer.answers["GET /api/peer/state"] = { exchange ->
            val doc = computer.stateDocument(phoneId).toMutableMap()
            doc["server"] = JsonPrimitive(phoneId)
            FakeComputer.json(exchange, 200, JsonObject(doc))
        }
        val refused = assertFailsWith<io.github.danielhp95.caracole.core.sync.SameCaracole> {
            engine.compare(computer.address.toString())
        }
        assertEquals("The scribe at ${computer.address} is this one (same id, $phoneId): its database is a " +
                     "copy of ours. Give one a new id: caracole peer new-id.", refused.message)
    }

    /** A song of the phone's with a kept file, its bytes in its folder. */
    private fun withFile(artist: String, title: String, bytes: ByteArray): SongRow {
        val song = onPhone(artist, title)
        val path = phoneStore.folderOf(song).relativeTo(phoneLibrary).path + "/guitar-1.gp5"
        File(phoneLibrary, path).apply { parentFile.mkdirs(); writeBytes(bytes) }
        phone.writeBlocking { db ->
            db.execute("INSERT INTO versions (provider, tab_id, song_id, slot, kind, url, fetched_at) " +
                       "VALUES ('inbox', 'guitar-1', ?, 'guitar', 'guitar', '', ?)", song.id, NOW)
            db.execute("INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) " +
                       "VALUES (?, ?, 'guitar-1.gp5', ?, ?, 0, ?)", db.lastRowid(), song.id, path,
                       Canonical.sha256Hex(bytes), NOW)
        }
        return song
    }

    @Test fun `a song whose file the phone can no longer read as kept is left out, and the rest is pushed all the same`() {
        val changed = withFile("Estopa", "Tu Calorro", "a Guitar Pro file".toByteArray())
        val hysteria = onPhone("Muse", "Hysteria")
        val c = engine.compare(computer.address.toString())
        File(phoneLibrary, phone.read { db -> db.one("SELECT path FROM files") { it.text(0)!! } }!!).writeText("edited")
        val outcome = apply(c)
        assertEquals(listOf(unitOf(hysteria)), outcome.given)
        assertEquals(listOf(unitOf(changed) to SyncEngine.FILE_CHANGED), outcome.left)
        assertEquals(emptyList(), computer.asked("POST", "/peer/push/file"))
        assertEquals(listOf(unitOf(hysteria)), (computer.pushes.single()["take"] as kotlinx.serialization.json.JsonArray)
            .map { ((it as JsonObject)["id"] as JsonPrimitive).content }, "the push sent, never left open")
        assertEquals(0, computer.pushesHere)
    }

    @Test fun `the computer refuses a push that keeps a file neither sent nor kept there, in peer_push's words`() {
        val song = withFile("Estopa", "Tu Calorro", "a Guitar Pro file".toByteArray())
        val sha = Canonical.sha256Hex("a Guitar Pro file".toByteArray())
        val client = PeerClient(computer.address)
        val state = client.state(phoneId)
        val (push, need) = client.pushNew(state.token, phoneId, listOf(sha))
        assertEquals(listOf(sha), need)
        val units = phoneState()
        val unit = phone.read { Units.document(it, phoneLibrary, unitOf(song)) }
        val doc = JsonObject(linkedMapOf(
            "format" to JsonPrimitive(Units.FORMAT), "from" to JsonPrimitive(phoneId), "name" to JsonPrimitive("Phone"),
            "caracole" to JsonPrimitive("0.1.0"), "at" to JsonPrimitive(state.now),
            "units" to JsonObject(units.mapValues { (_, u) ->
                JsonObject(linkedMapOf("label" to JsonPrimitive(u.label), "digest" to JsonPrimitive(u.digest)))
            }),
            "take" to kotlinx.serialization.json.JsonArray(listOf(JsonObject(linkedMapOf(
                "id" to JsonPrimitive(unitOf(song)), "expected" to kotlinx.serialization.json.JsonNull,
                "digest" to JsonPrimitive(units.getValue(unitOf(song)).digest), "unit" to unit!!,
            )))),
        ))
        val refused = assertFailsWith<io.github.danielhp95.caracole.core.sync.PeerError> { client.push(state.token, push, doc) }
        assertEquals("${computer.address} answered 400: 1 file the push keeps was never sent, nor kept " +
                     "here: $sha.", refused.message)
        assertEquals(400, refused.status)
    }

    @Test fun `two pushes left open make the computer refuse a third, and the give says why`() {
        withFile("Estopa", "Tu Calorro", "a Guitar Pro file".toByteArray())
        computer.answers["POST /peer/push/file"] = { exchange ->
            FakeComputer.json(exchange, 503, FakeComputer.obj("error" to JsonPrimitive("The file couldn't be kept: disk full.")))
        }
        repeat(2) {
            val failed = assertFailsWith<SyncFailed> { apply(engine.compare(computer.address.toString())) }
            assertEquals("Couldn't give them 1: ${computer.address} answered 503: The file " +
                         "couldn't be kept: disk full.", failed.message)
            assertEquals("failed", ended()["give"])
            assertNull(ended()["agree"], "no agreement recorded")
            stages.clear()
        }
        assertEquals(2, computer.pushesHere)
        val third = assertFailsWith<SyncFailed> { apply(engine.compare(computer.address.toString())) }
        assertEquals("Couldn't give them 1: ${computer.address} answered 409: Two pushes are " +
                     "here already, waiting to be taken: try again once one is, or in an hour.", third.message)
        assertEquals(emptyList(), assertNotNull(third.outcome).given, "as peer sync --push fails, nothing given")
        assertNull(phone.read { Compare.baseOf(it, computer.id) })
    }

    @Test fun `a take that outlasts the wait fails the give, and the computer refuses the next while it still runs`() {
        val hysteria = onPhone("Muse", "Hysteria")
        val held = java.util.concurrent.CountDownLatch(1)
        computer.holdTakes = held
        val waiting = engine().also { it.pollEveryMs = 5; it.polls = 3 }
        val gaveUp = assertFailsWith<SyncFailed> { apply(waiting.compare(computer.address.toString()), on = waiting) }
        assertEquals("Couldn't give them 1: ${computer.address} hasn't taken the push yet: its Journal entry 1 " +
                     "goes on.", gaveUp.message)
        assertEquals(3, computer.asked("GET", "/api/jobs/1").size)

        val refused = assertFailsWith<SyncFailed> { apply(waiting.compare(computer.address.toString()), on = waiting) }
        assertEquals("Couldn't give them 1: ${computer.address} answered 409: Changes from " +
                     "Phone are being taken already (request 1): send them again once that is over.", refused.message)
        assertEquals(2, computer.pushesHere, "the push refused stays open, to send again")

        held.countDown()
        computer.holdTakes = null
        computer.awaitTakes()
        val again = apply(engine.compare(computer.address.toString()))
        assertEquals(emptyList(), again.given, "taken by the first push already")
        assertEquals(computer.state(), phoneState())
        assertTrue(unitOf(hysteria) in computer.state())
    }

    @Test fun `the mirror stage says how many of the computer's pages are copied`() {
        onComputer("Radiohead", "Creep")
        val mirrored = engine { _, say -> say("0 of 7 pages"); say("3 of 7 pages"); say("7 of 7 pages") }
        var tick = 0L
        mirrored.ticks = { tick.also { tick += 2_000_000_000L } }  // two seconds a reading: every count is said
        apply(mirrored.compare(computer.address.toString()), on = mirrored)
        val said = stages.filter { it.first == "mirror" && it.second == "running" }.map { it.third }
        assertEquals(listOf("", "0 of 7 pages", "3 of 7 pages", "7 of 7 pages"), said)
        assertEquals("done", ended()["mirror"])
    }

    @Test fun `the index stage says each step of the computer's indexes coming, and how far`() {
        onComputer("Radiohead", "Creep")
        val export = tmp.newFile("export.sqlite").also { it.delete() }
        io.github.danielhp95.caracole.core.testing.Fixtures.loadRaw(export, "index/fixtures/full-export.jsonl")
        computer.index = { export.readBytes() }
        computer.indexes = mapOf("gtptabs" to "2026-11-03T10:00:00Z", "musescore" to "2026-11-03T11:00:00Z")
        var tick = 0L
        engine.ticks = { tick.also { tick += 2_000_000_000L } }  // two seconds a reading: every count is said
        apply(engine.compare(computer.address.toString()))
        val said = stages.filter { it.first == "index" && it.second == "running" }.map { it.third }
        val bytes = export.length()
        // Each step's words as the stage's detail, one "…" at their end left off: its line puts its own after them
        // (Status.stageLine, "Updating the indexes · Tidying the database…").
        val steps = listOf("gtptabs, musescore", "The computer is copying its indexes",
                           "Downloading the computer's indexes · ${CataloguesSizes.of(0, bytes)}",
                           "Comparing with the phone's index",
                           "Importing · gtptabs.com", "Importing · MuseScore", "Tidying the database")
        var at = 0
        for (line in said) if (at < steps.size && line == steps[at]) at++
        assertEquals(steps.size, at, said.joinToString("\n"))
        assertTrue(said.none { it.endsWith("…") }, said.joinToString("\n"))
        assertTrue(said.any { it == "Downloading the computer's indexes · ${CataloguesSizes.of(bytes, bytes)}" },
                   said.joinToString("\n"))
        assertEquals("0.0 of 0.1 MB", CataloguesSizes.of(0, 100_000))
        // An answer of no Content-Length: the bytes come so far, no total, no 0.1 MB floor.
        assertEquals("Downloading the computer's indexes · 0.0 MB so far", SyncEngine.downloading(40_000, -1))
        assertEquals("Downloading the computer's indexes · 3.4 MB so far", SyncEngine.downloading(3_400_000, -1))
        assertEquals("Downloading the computer's indexes · 120 MB so far", SyncEngine.downloading(120_000_000, -1))
        assertEquals("merged gtptabs, musescore", stages.last { it.first == "index" }.third)
    }

    @Test fun `a newer index merged takes its sites into the phone's tables, and the stamps are kept`() {
        onComputer("Radiohead", "Creep")
        val export = tmp.newFile("export.sqlite").also { it.delete() }
        io.github.danielhp95.caracole.core.testing.Fixtures.loadRaw(export, "index/fixtures/full-export.jsonl")
        computer.index = { export.readBytes() }
        computer.indexes = mapOf("gtptabs" to "2026-11-03T10:00:00Z", "musescore" to "2026-11-03T11:00:00Z")
        val outcome = apply(engine.compare(computer.address.toString()))
        assertEquals(listOf("gtptabs", "musescore"), outcome.indexed)
        assertEquals("done", ended()["index"])
        assertEquals("""{"gtptabs": "2026-11-03T10:00:00Z", "musescore": "2026-11-03T11:00:00Z"}""",
                     phone.read { it.kvGet(SyncEngine.INDEX_KEY + computer.id) })
        assertEquals(phone.read { IndexTransfer.newest(it) }.filterKeys { it == "gtptabs" || it == "musescore" },
                     phone.read { MergedIndexes.of(it) }, "and what the file merged read, of the sites merged")
        assertTrue(phone.read { db -> db.one("SELECT COUNT(*) FROM gtptabs_index") { it.long(0) } }!! > 0)
        assertEquals(0L, phone.read { db -> db.one("SELECT COUNT(*) FROM ug_index") { it.long(0) } },
                     "a site not newer there is not merged")
        assertEquals(emptyList(), File(stateDir, "cache").listFiles().orEmpty().toList())

        // Nothing newer the next time: nothing asked.
        computer.indexAsked.clear()
        stages.clear()
        apply(engine.compare(computer.address.toString()))
        assertEquals(emptyList(), computer.indexAsked)
        assertEquals("skipped", ended()["index"])
    }

    // --- a sync's parts, the comparison's new members, the unattended sync (the sync redesign's Task 12) -------------

    @Test fun `songbooks alone take the songbook and the songs it lists and nothing else`() {
        computer.load(RICH)
        val c = engine.compare(computer.address.toString())
        assertEquals(listOf("song/radiohead/creep", "song/radiohead/karma-police"),
                     c.listed.keys.toList(), "the songs Campfire lists")
        val outcome = apply(c, parts = listOf(Scope.SONGBOOKS))
        assertEquals(setOf("song/radiohead/creep", "song/radiohead/karma-police", "songbook/campfire"),
                     outcome.taken.toSet())
        assertEquals(setOf("song/radiohead/creep", "song/radiohead/karma-police", "songbook/campfire"),
                     phoneState().keys, "no other song, tombstone, alias, artist's page or blocked tab")
        assertEquals(emptyList(), outcome.left, "a part left out is never said")
        assertEquals(mapOf("mirror" to "skipped", "index" to "skipped"),
                     ended().filterKeys { it == "mirror" || it == "index" })
    }

    @Test fun `the unattended sync takes and gives every one-sided change and leaves each conflict, never refusing`() {
        val hysteria = onPhone("Muse", "Hysteria")
        val wonderwall = onPhone("Oasis", "Wonderwall", album = "Morning Glory")
        val creep = onComputer("Radiohead", "Creep")
        onComputer("Oasis", "Wonderwall", album = "(What's the Story) Morning Glory?")
        val c = engine.compare(computer.address.toString())
        val before = computer.state().getValue(unitOf(wonderwall)) to phoneState().getValue(unitOf(wonderwall))

        val outcome = apply(c, conflicts = Conflicts.LEAVE)

        assertEquals(listOf(unitOf(creep)), outcome.taken)
        assertEquals(listOf(unitOf(hysteria)), outcome.given)
        assertEquals(listOf(unitOf(wonderwall) to SyncEngine.UNSETTLED), outcome.left)
        assertEquals(before, computer.state().getValue(unitOf(wonderwall)) to phoneState().getValue(unitOf(wonderwall)),
                     "the conflict as it was on both sides")
        assertEquals("done", ended()["agree"])
        // Asked of the owner, the same comparison is refused before any change.
        assertFailsWith<SyncFailed> { apply(engine.compare(computer.address.toString())) }
    }

    @Test fun `a unit kept at an import is given at the next sync without asking`() {
        val here = onPhone("Oasis", "Wonderwall", album = "Morning Glory")
        onComputer("Oasis", "Wonderwall", album = "(What's the Story) Morning Glory?")
        val unit = unitOf(here)
        val (mine, theirs) = phoneState().getValue(unit).digest to computer.state().getValue(unit).digest
        // An import of the computer's file answered "keep mine" for it.
        phone.writeBlocking { db -> Compare.recordKept(db, computer.id, mapOf(unit to (mine to theirs)), "2026-11-02T09:00:00Z") }

        val c = engine.compare(computer.address.toString())
        assertEquals(mapOf(unit to KeptPair(mine, theirs, Compare.MINE)), c.kept)
        assertEquals(listOf(Triple(unit, Compare.MINE, Compare.KEPT_HERE)), c.differences.map { Triple(it.id, it.proposal, it.why) })
        val outcome = apply(c)
        assertEquals(listOf(unit), outcome.given)
        assertEquals(mine, computer.state().getValue(unit).digest, "the computer took the phone's version")
        assertEquals(emptyMap(), phone.read { Compare.keptOf(it, computer.id) }, "the kept answer dropped once agreed")
        assertEquals(emptyList(), engine.compare(computer.address.toString()).differences)
    }

    @Test fun `the comparison carries each difference's names, change, part and songbooks, and the indexes waiting`() {
        computer.load(RICH)
        val gone = onPhone("Oasis", "Wonderwall")
        computer.indexes = mapOf("ug" to "2026-11-03T10:00:00Z")
        val c = engine.compare(computer.address.toString())
        assertEquals(SyncEngine.COMPUTER, c.kind)
        assertEquals(Scope.PARTS, c.holds)
        assertNull(c.base, "never synced")
        val creep = c.differences.single { it.id == "song/radiohead/creep" }
        assertEquals("Radiohead" to "Creep", Scope.namesOf(creep.id, creep.label))
        assertEquals(null to "new", Scope.changeOf(creep, c.base, c.kept))
        assertEquals("new" to null, Scope.changeOf(c.differences.single { it.id == unitOf(gone) }, c.base, c.kept))
        assertEquals(listOf("library", "songbooks"), c.differences.map { Scope.partOf(it.id) }.distinct())
        assertEquals(setOf("songbook/campfire"), c.songbooks.keys)
        val (onPhone, onComputer) = c.songbooks.getValue("songbook/campfire")
        assertNull(onPhone)
        assertEquals(JsonPrimitive("Campfire"), onComputer!!["name"])
        assertEquals(listOf(IndexWaiting("ug", "Ultimate Guitar", null, "2026-11-03T10:00:00Z", "there")), c.indexes)
        assertEquals(mapOf("song/radiohead/creep" to listOf("songbook/campfire"),
                           "song/radiohead/karma-police" to listOf("songbook/campfire")), c.listed)
    }

    @Test fun `library unticked skips the mirror, and indexes unticked skips the index stage`() {
        onComputer("Radiohead", "Creep")
        computer.indexes = mapOf("gtptabs" to "2026-11-03T10:00:00Z")
        var refreshed = 0
        val mirrored = engine { _, _ -> refreshed++ }
        val outcome = apply(engine.compare(computer.address.toString()), on = mirrored, parts = listOf(Scope.SONGBOOKS))
        assertEquals(emptyList(), outcome.taken, "a song comes with the songbooks only when one lists it")
        assertEquals(0, refreshed)
        assertEquals(Triple("mirror", "skipped", SyncEngine.LIBRARY_LEFT_OUT), stages.last { it.first == "mirror" })
        assertEquals(Triple("index", "skipped", SyncEngine.INDEXES_LEFT_OUT), stages.last { it.first == "index" })
        assertEquals(emptyList(), computer.indexAsked, "no index asked for")
        assertEquals(listOf("songbooks"), (outcome.report!!["parts"] as JsonArray).map { (it as JsonPrimitive).content })
        assertFailsWith<IllegalArgumentException> { apply(engine.compare(computer.address.toString()), parts = listOf("pages")) }
    }

    @Test fun `tested says the computer's songs, songbooks, newest index and the last sync, and changes nothing`() {
        computer.load(RICH)
        computer.indexes = mapOf("ug" to "2026-11-03T10:00:00Z", "lacuerda" to "2026-11-03T11:00:00Z")
        val before = phone.read { db -> db.query("SELECT key, value FROM kv ORDER BY key") { it.text(0) to it.text(1) } }
        val tested = engine.tested(computer.address.toString())
        assertEquals(4, tested.songs)
        assertEquals(1, tested.songbooks)
        assertEquals("2026-11-03T11:00:00Z", tested.indexes)
        assertNull(tested.syncedAt)
        assertEquals("Desk", tested.peer.name)
        assertEquals(before, phone.read { db -> db.query("SELECT key, value FROM kv ORDER BY key") { it.text(0) to it.text(1) } })
        assertEquals(emptyList(), computer.requests.filter { !it.startsWith("GET /api/peer/state") })
        apply(engine.compare(computer.address.toString()))
        assertEquals(computer.now, engine.tested(computer.address.toString()).syncedAt)
    }

    // --- the report (Task 14) -----------------------------------------------------------------------------------------

    @Test fun `a sync's report counts each index taken before and after its merge`() {
        onComputer("Radiohead", "Creep")
        val export = tmp.newFile("export.sqlite").also { it.delete() }
        io.github.danielhp95.caracole.core.testing.Fixtures.loadRaw(export, "index/fixtures/full-export.jsonl")
        computer.index = { export.readBytes() }
        computer.indexes = mapOf("gtptabs" to "2026-11-03T10:00:00Z")
        val outcome = apply(engine.compare(computer.address.toString()))
        val report = outcome.report!!
        assertEquals(JsonObject(mapOf("name" to JsonPrimitive("Desk"), "kind" to JsonPrimitive("computer"),
                                      "address" to JsonPrimitive(computer.address.toString()))), report["with"])
        assertEquals(JsonPrimitive(computer.now), report["at"])
        assertEquals(Scope.PARTS.map(::JsonPrimitive), (report["parts"] as JsonArray).toList())
        val gtptabs = phone.read { db -> db.one("SELECT COUNT(*) FROM gtptabs_index") { it.long(0)!! } }!!
        assertTrue(gtptabs > 0)
        assertEquals(listOf(JsonObject(linkedMapOf(
            "site" to JsonPrimitive("gtptabs"), "title" to JsonPrimitive("gtptabs.com"), "direction" to JsonPrimitive("taken"),
            "before" to JsonPrimitive(0L), "after" to JsonPrimitive(gtptabs), "new" to JsonPrimitive(gtptabs),
            "checked" to JsonPrimitive(gtptabs), "read" to JsonPrimitive("2026-11-03T10:00:00Z"),
        ))), (report["indexes"] as JsonArray).toList())
    }

    @Test fun `an index given is counted on the computer before the push and after its merge job`() {
        computer.database.writeBlocking { IndexTransfer.seedFresh(it) }
        phone.writeBlocking { db ->
            io.github.danielhp95.caracole.core.testing.Fixtures.load(db, "index/fixtures/reads-before.jsonl")
            db.execute("DELETE FROM kv WHERE key LIKE 'phone:read%'")
            Reads.note(db, "lacuerda", "estopa/", "2026-11-03T09:00:00Z")
        }
        val before = computer.database.read { db -> db.one("SELECT COUNT(*) FROM lacuerda_index") { it.long(0)!! } }!!
        val outcome = apply(engine.compare(computer.address.toString()))
        computer.awaitTakes()
        val after = computer.database.read { db -> db.one("SELECT COUNT(*) FROM lacuerda_index") { it.long(0)!! } }!!
        assertTrue(after > before, "the computer merged the page")
        val given = (outcome.report!!["indexes"] as JsonArray).map { it as JsonObject }.single()
        assertEquals(linkedMapOf("site" to JsonPrimitive("lacuerda"), "title" to JsonPrimitive("LaCuerda"),
                                 "direction" to JsonPrimitive("given"), "before" to JsonPrimitive(before),
                                 "after" to JsonPrimitive(after), "new" to JsonPrimitive(after - before),
                                 // how many rows its merge read there, the computer's answer doesn't say
                                 "checked" to JsonNull, "read" to JsonPrimitive("2026-11-03T09:00:00Z")),
                     given.toMap())
        assertTrue(computer.requests.count { it == "GET /api/sync/indexes" } == 2, "${computer.requests}")

        // A computer older than the route: the pages go all the same, and the report counts none.
        stages.clear()
        computer.countsIndexes = false
        phone.writeBlocking { db -> Reads.note(db, "lacuerda", "busca.php", "2026-11-03T09:30:00Z") }
        val older = apply(engine.compare(computer.address.toString()))
        assertEquals("done", ended()["index"])
        assertEquals(JsonArray(emptyList()), older.report!!["indexes"])
    }

    // --- after the site catalogues or a file's indexes: the sites asked for, and those the sheet lists -------------

    /** A UG sitemap read at [at], as ug/index.py `_store` leaves it: its rows (a row kept keeps its sitemap) and its
     * record in kv `ug:sitemaps`. */
    private fun sitemap(db: Db, name: String, ids: LongRange, at: String) {
        for (i in ids) {
            db.execute("INSERT INTO ug_index (tab_id, artist_key, song_key, type, sitemap, first_seen, path) " +
                           "VALUES (?, ?, ?, 'chords', ?, ?, ?) ON CONFLICT (tab_id) DO NOTHING",
                       i, "artist-${i % 97}", "song-$i", name, at, "artist-${i % 97}/song-$i-chords-$i")
        }
        val records = LinkedHashMap(Merge.records(db, "main", Merge.UG_SITEMAPS))
        records[name] = JsonObject(linkedMapOf("etag" to JsonPrimitive("\"$name-$at\""), "last_modified" to JsonNull,
                                               "indexed_at" to JsonPrimitive(at),
                                               "rows" to JsonPrimitive(ids.count())))
        db.kvSetJson(Merge.UG_SITEMAPS, JsonObject(records))
    }

    /** The computer's index export, as `GET /api/peer/index` sends it (index_transfer.export of its database). */
    private fun computersExport(): ByteArray {
        val file = File(tmp.root, "export-${System.nanoTime()}.sqlite")
        computer.database.writeBlocking { db -> IndexFile.export(db, file, CATALOGUES_AT, "0.1.0") }
        return file.readBytes().also { file.delete() }
    }

    /** The computer's index as its nightly runs left it (UG's and gtptabs.com's), published as the site catalogues,
     * which the phone imports as CataloguesRunner does (its merge, bounded by its clock and a day, then what it read
     * recorded); the computer answering its state with its indexes' newest reads, as the real one does. */
    private fun catalogued() {
        engine.clock = { Instant.parse(SYNCED_AT) }
        computer.database.writeBlocking { db ->
            sitemap(db, "1", 1L..400L, EARLY)
            sitemap(db, "2", 401L..800L, EARLY)
            sitemap(db, "last", 801L..810L, EARLY)
            db.kvSetJson(Merge.UG_LISTED, JsonArray(listOf("1", "2", "last").map(::JsonPrimitive)))
            db.kvSet(Merge.UG_REFRESHED, EARLY)
            db.kvSet(Merge.UG_BUILT, EARLY)
            for (i in 1..50) {
                db.execute("INSERT INTO gtptabs_index (path, artist_path, artist_key, title_key, base_key, sitemap) " +
                               "VALUES (?, 'tabs/2/blur.html', 'blur', ?, ?, 'sitemap-tabs-1.xml')",
                           "tabs/2/blur/song-$i.html", "song-$i", "song-$i")
            }
            db.kvSetJson(Merge.sitemapsKey("gtptabs"), JsonObject(mapOf("sitemap-tabs-1.xml" to JsonObject(mapOf(
                "etag" to JsonPrimitive("\"1\""), "last_modified" to JsonNull, "checked_at" to JsonPrimitive(EARLY),
                "rows" to JsonPrimitive(50))))))
            db.kvSet(Merge.completeKey("gtptabs"), EARLY)
        }
        val catalogue = File(tmp.root, "catalogue.sqlite").apply { writeBytes(computersExport()) }
        phone.writeBlocking { db ->
            val bound = Stamps.micros(Instant.parse(CATALOGUES_AT).plus(Duration.ofDays(1)))
            MergedIndexes.record(db, IndexTransfer.merge(db, catalogue, CATALOGUES_AT, notAfter = bound))
        }
        computer.index = { computersExport() }
    }

    private fun computerAnswersAsItIs() {
        computer.indexes = computer.database.read { IndexTransfer.newest(it) }
    }

    @Test fun `after the site catalogues, a sync asks the computer only for the sites newer there`() {
        catalogued()
        // A week of nightly refreshes there: sitemap "last" read with 5 tabs more, sitemap "2" read again.
        computer.database.writeBlocking { db ->
            sitemap(db, "last", 801L..815L, LATE)
            sitemap(db, "2", 401L..800L, LATE)
            db.kvSet(Merge.UG_REFRESHED, LATE)
        }
        computerAnswersAsItIs()
        val c = engine.compare(computer.address.toString())
        assertEquals(listOf("ug"), c.indexes.filter { it.newer == "there" }.map { it.site })
        val outcome = apply(c)
        assertEquals(listOf<List<String>?>(listOf("ug")), computer.indexAsked,
                     "gtptabs.com, as the catalogues gave it, is never downloaded again")
        val ug = (outcome.report!!["indexes"] as JsonArray).map { it as JsonObject }.single()
        assertEquals(JsonPrimitive("ug"), ug["site"])
        assertEquals(JsonPrimitive(810L) to JsonPrimitive(815L), ug["before"] to ug["after"])
        // The owner's report: the tabs really new here, and the rows of the two sitemaps checked, never 815 new.
        assertEquals(JsonPrimitive(5L) to JsonPrimitive(415L), ug["new"] to ug["checked"])
        val said = stages.filter { it.first == "index" && it.second == "running" }.map { it.third }
        assertTrue("Ultimate Guitar · 2 sitemaps newer on the computer · 415 of 415 tabs checked" in said,
                   said.joinToString("\n"))
        assertTrue(said.none { it.startsWith(MergeProgress.IMPORTING) }, said.joinToString("\n"))
        assertEquals(mapOf("gtptabs" to EARLY, "ug" to LATE), phone.read { MergedIndexes.of(it) },
                     "the sync's own merge recorded what its file read")
    }

    @Test fun `after the site catalogues, a computer no newer is asked for no index, and the sheet lists none`() {
        catalogued()
        computerAnswersAsItIs()
        assertEquals(computer.database.read { IndexTransfer.newest(it) }, phone.read { IndexTransfer.newest(it) })
        val c = engine.compare(computer.address.toString())
        assertEquals(emptyList(), c.indexes, "no Site index waits")
        apply(c)
        assertEquals(emptyList(), computer.indexAsked)
        assertEquals(Triple("index", "skipped", SyncEngine.NOTHING_TO_INDEX), stages.last { it.first == "index" })
    }

    /** A harptabs.com artist page the computer's nightly pass read at [at]. */
    private fun readThere(path: String, title: String, at: String) = computer.database.writeBlocking { db ->
        db.execute("INSERT OR REPLACE INTO harptabs_artists (path, page_id, key, name, tabs, read_at) VALUES " +
                       "(?, ?, ?, ?, 1, ?)", path, path.split('/')[1].toLong(), path.substringAfterLast('/'),
                   path.substringAfterLast('/'), at)
        db.execute("INSERT OR REPLACE INTO harptabs_artist_tabs (artist, tab_id, path, title, song_key, place) " +
                       "VALUES (?, ?, ?, ?, ?, 0)", path, path.split('/')[1].toLong() * 10, "tab/1/x", title,
                   title.lowercase())
    }

    @Test fun `the sheet lists the indexes the sync takes and those it gives, and those alone`() {
        engine.clock = { Instant.parse(NOW) }
        readThere("artist/1178/billy-joel", "Piano Man", "2026-11-03T03:00:00Z")
        val catalogue = File(tmp.root, "catalogue.sqlite").apply { writeBytes(computersExport()) }
        phone.writeBlocking { db -> MergedIndexes.record(db, IndexTransfer.merge(db, catalogue, CATALOGUES_AT)) }
        computer.index = { computersExport() }
        // A page the phone's lookup read since, later than any of the computer's, and one the computer read since.
        readHere("artist/50/the-beatles", listOf("Yesterday"), "2026-11-03T09:30:00Z")
        readThere("artist/7/bob-dylan", "Blowin' in the Wind", "2026-11-03T08:00:00Z")
        computerAnswersAsItIs()

        val c = engine.compare(computer.address.toString())
        val harptabs = { newer: String ->
            IndexWaiting("harptabs", "harptabs.com", "2026-11-03T09:30:00Z", "2026-11-03T08:00:00Z", newer)
        }
        assertEquals(listOf(harptabs("there"), harptabs("here")), c.indexes,
                     "taken from the computer, its pages read here given")
        apply(c)
        assertEquals(c.indexes.filter { it.newer == "there" }.map { it.site },
                     computer.indexAsked.flatMap { it.orEmpty() },
                     "the sync takes the indexes the sheet said it would, and those alone")
        assertEquals(1, computer.indexPushes.size, "and gives the pages it said it would")
        assertEquals(emptyMap(), noted())
    }

    @Test fun `indexes taken from the computer's file are never asked for again at the next sync`() {
        onComputer("Radiohead", "Creep")
        readThere("artist/50/the-beatles", "Yesterday", "2026-11-03T08:00:00Z")
        computerAnswersAsItIs()
        val file = File(tmp.newFolder(), "file.caracole")
        computer.database.writeBlocking { db ->
            SyncFiles.export(db, computer.libraryDir, null, file, listOf(Scope.LIBRARY, Scope.INDEXES), NOW,
                             Compare.ownId(db), "Desk", "0.1.0")
        }
        apply(engine.compareFile(file))
        assertEquals(computer.database.read { IndexTransfer.newest(it) }["harptabs"],
                     phone.read { IndexTransfer.newest(it) }["harptabs"], "the file's index merged here")

        stages.clear()
        val c = engine.compare(computer.address.toString())
        assertEquals(emptyList(), c.indexes)
        apply(c)
        assertEquals(emptyList(), computer.indexAsked, "the phone holds the computer's harptabs.com index as it is")
        assertEquals("skipped", ended()["index"])
    }

    // --- a computer of another schema (sync hunt 2026-11-25) --------------------------------------------------------

    /** The computer's index export as a caracole whose database is at [schema] sends it. */
    private fun computersExportAt(schema: Int): ByteArray {
        val file = File(tmp.root, "export-${System.nanoTime()}.sqlite")
        computer.database.writeBlocking { db -> IndexFile.export(db, file, CATALOGUES_AT, "0.1.0") }
        val c = androidx.sqlite.driver.bundled.BundledSQLiteDriver().open(file.path)
        try {
            c.prepare("UPDATE ${IndexTransfer.META} SET value = '$schema' WHERE key = 'schema'").use { it.step() }
        } finally {
            c.close()
        }
        return file.readBytes().also { file.delete() }
    }

    /** The computer updated to a caracole of [schema] (its state says it, its index export is of it), harptabs.com
     * read there and a page of it read here: an index newer on either side. */
    private fun computerAt(schema: Int) {
        onComputer("Radiohead", "Creep")
        readThere("artist/1178/billy-joel", "Piano Man", "2026-11-03T03:00:00Z")
        readHere("artist/50/the-beatles", listOf("Yesterday"), "2026-11-03T09:30:00Z")
        computer.schema = schema
        computer.index = { computersExportAt(schema) }
        computerAnswersAsItIs()
    }

    @Test fun `a computer of a newer schema is asked for no index at any sync, and the stage says why`() {
        computerAt(Database.SCHEMA_VERSION + 1)  // the computer updated; the phone's app not yet
        repeat(3) {
            stages.clear()
            val c = engine.compare(computer.address.toString())
            assertEquals(emptyList(), c.indexes, "the sheet lists no index waiting")
            assertEquals(SyncEngine.INDEXES_NEWER, c.indexesSkipped, "and says why")
            val outcome = apply(c)
            assertEquals(Triple("index", "skipped", SyncEngine.INDEXES_NEWER), stages.last { it.first == "index" })
            assertEquals(1, outcome.agreed, "the units sync as ever")
            assertEquals(JsonArray(emptyList()), outcome.report!!["indexes"])
            assertEquals(JsonPrimitive(SyncEngine.INDEXES_NEWER), outcome.report!!["indexes_skipped"],
                         "the report says why, for the sheet's summary once it is over")
        }
        assertEquals(emptyList(), computer.indexAsked, "no index downloaded, at any sync")
        assertEquals(emptyList(), computer.indexPushes, "nor the pages read here given: its merge refuses them")
        assertEquals(mapOf("harptabs" to listOf("artist/50/the-beatles")), noted(), "kept for once the two agree")
        assertNull(held())
        assertTrue(stages.none { stateDir.path in it.third || "Error" in it.third }, stages.toString())
    }

    @Test fun `a computer of an older schema is asked for no index either, in the mirror image's words`() {
        computerAt(Database.SCHEMA_VERSION - 1)
        val c = engine.compare(computer.address.toString())
        assertEquals(emptyList(), c.indexes)
        assertEquals(SyncEngine.INDEXES_OLDER, c.indexesSkipped)
        apply(c)
        assertEquals(Triple("index", "skipped", SyncEngine.INDEXES_OLDER), stages.last { it.first == "index" })
        assertEquals(emptyList(), computer.indexAsked)
        assertEquals(emptyList(), computer.indexPushes)
    }

    @Test fun `a computer that says no schema is asked as before, and its refusal names no path and no class`() {
        computerAt(Database.SCHEMA_VERSION + 1)
        computer.schema = null  // a caracole older than the member says none
        val c = engine.compare(computer.address.toString())
        assertNull(c.indexesSkipped)
        assertEquals(listOf("there", "here"), c.indexes.map { it.newer }, "listed as before")
        val outcome = apply(c)
        assertNull(outcome.report!!["indexes_skipped"], "no why where none was skipped")
        assertEquals(listOf<List<String>?>(listOf("harptabs")), computer.indexAsked, "downloaded as before")
        val (_, state, detail) = stages.last { it.first == "index" }
        assertEquals("failed", state)
        assertTrue(detail.startsWith("The computer's index export was exported at schema version " +
                                         "${Database.SCHEMA_VERSION + 1}, and this caracole's database is at " +
                                         "${Database.SCHEMA_VERSION}"), detail)
        assertFalse(stateDir.path in detail || "TransferError" in detail, detail)
        assertEquals(emptyList(), File(stateDir, "cache").listFiles().orEmpty().toList(), "the file fetched is gone")
    }

    // --- the part of the computer's indexes the phone doesn't hold (POST /peer/index/newer) -------------------------

    private val indexTables = listOf("ug_index", "ug_artist_tabs", "ug_directory", "lacuerda_index", "gtptabs_index",
                                     "musescore_index", "harptabs_index", "harptabs_artists", "harptabs_artist_tabs",
                                     "gametabs_index", "gametabs_games", "gametabs_game_tabs")

    /** A dump's lines of the index tables' rows, in order (Dumps' lines). */
    private fun indexRows(lines: List<String>): List<String> =
        lines.filter { line -> indexTables.any { line.endsWith("\"table\":\"$it\"}") } }

    private fun corpusExport(name: String): ByteArray {
        val file = File(tmp.root, "$name-${System.nanoTime()}.sqlite")
        io.github.danielhp95.caracole.core.testing.Fixtures.loadRaw(file, "index/fixtures/$name-export.jsonl")
        return file.readBytes().also { file.delete() }
    }

    /** The phone that merged the computer's whole export of the corpus (index/fixtures/phone-after), the computer a
     * night on (tonight-export, newer-export: test_conformance_index.py's night) answering its state with stamps later
     * than any the phone holds; [cut], the phone's record of that whole export's time, as a sync that took it keeps. */
    private fun aNightOn(cut: Boolean) {
        engine.clock = { Instant.parse("2026-11-05T10:00:00Z") }
        phone.writeBlocking { db ->
            io.github.danielhp95.caracole.core.testing.Fixtures.load(db, "index/fixtures/phone-after.jsonl")
            if (cut) {
                db.kvSetJson(Have.CUT_KEY + computer.id, JsonObject(IndexTransfer.SITES.associateWith {
                    JsonPrimitive("2026-11-03T12:00:00Z")  // full-export's exported_at
                }))
            }
        }
        computer.indexes = IndexTransfer.SITES.associateWith { "2026-11-04T03:30:00Z" }
        computer.index = { corpusExport("tonight") }
    }

    @Test fun `a computer one night newer is asked for the part the phone doesn't hold, and the phone ends with the computer's rows`() {
        aNightOn(cut = true)
        computer.newer = { corpusExport("newer") }
        val outcome = apply(engine.compare(computer.address.toString()))
        assertEquals("done", ended()["index"], stages.joinToString("\n"))
        assertEquals(IndexTransfer.SITES, outcome.indexed)
        assertEquals(emptyList(), computer.indexAsked, "never the whole export")
        val asked = computer.newerAsked.single()
        assertEquals(JsonArray(IndexTransfer.SITES.map(::JsonPrimitive)), asked["sites"])
        val ug = (asked["have"] as JsonObject)["ug"] as JsonObject
        assertEquals(JsonPrimitive("2026-11-03T12:00:00Z"), ug["since"], "the time of the export it took last")
        val records = ug["sitemaps"] as JsonObject
        assertEquals(setOf("1", "2", "3", "4"), records.keys, "its own record of each sitemap it holds")
        assertTrue(records.values.none { "checked_at" in (it as JsonObject) }, "never a re-check's time")
        // As the computer's whole export of that night would leave it (the corpus holds the two alike).
        assertEquals(indexRows(Dumps.fixture("tonight-after")), indexRows(phone.read { Dumps.lines(it) }))
        assertEquals(IndexTransfer.SITES.associateWith { "2026-11-04T12:00:00Z" },
                     phone.read { Have.cuts(it, computer.id) }, "the cut moved on to the part's own time")
        assertEquals(emptyList(), File(stateDir, "cache").listFiles().orEmpty().toList())
    }

    @Test fun `after the site catalogues, the part asked for sends every page read a page at a time, and its cut is kept`() {
        aNightOn(cut = false)  // a phone that took the computer's index as the catalogues: no export of its own merged
        computer.newer = { corpusExport("uncut") }
        apply(engine.compare(computer.address.toString()))
        assertEquals("done", ended()["index"], stages.joinToString("\n"))
        val have = computer.newerAsked.single()["have"] as JsonObject
        assertTrue(IndexTransfer.SITES.all { (have[it] as JsonObject)["since"] == JsonNull }, have.toString())
        assertEquals(indexRows(Dumps.fixture("tonight-after")), indexRows(phone.read { Dumps.lines(it) }))
        assertEquals(IndexTransfer.SITES.associateWith { "2026-11-04T12:00:00Z" }, phone.read { Have.cuts(it, computer.id) })
    }

    @Test fun `a computer older than the part's route is asked for the whole export, as before`() {
        aNightOn(cut = true)  // newer unset: the route answers 404
        apply(engine.compare(computer.address.toString()))
        assertEquals("done", ended()["index"], stages.joinToString("\n"))
        assertTrue("POST /peer/index/newer" in computer.requests.map { it.substringBefore('?') }, computer.requests.toString())
        assertEquals(listOf<List<String>?>(IndexTransfer.SITES), computer.indexAsked)
        assertEquals(indexRows(Dumps.fixture("tonight-after")), indexRows(phone.read { Dumps.lines(it) }))
        assertEquals(IndexTransfer.SITES.associateWith { "2026-11-03T12:00:00Z" }, phone.read { Have.cuts(it, computer.id) },
                     "a whole export is no cut: an older computer notes no arrivals")
    }

    @Test fun `after a whole export from an older computer, the first part asked of it once updated is uncut`() {
        aNightOn(cut = false)  // the route answers 404: an older caracole serve
        apply(engine.compare(computer.address.toString()))
        assertEquals("done", ended()["index"], stages.joinToString("\n"))
        assertEquals(listOf<List<String>?>(IndexTransfer.SITES), computer.indexAsked)
        assertEquals(emptyMap(), phone.read { Have.cuts(it, computer.id) }, "no cut taken from a whole export")
        // The computer updated, a night on: it answers the route.
        computer.newer = { corpusExport("uncut") }
        computer.indexes = IndexTransfer.SITES.associateWith { "2026-11-05T03:30:00Z" }
        stages.clear()
        apply(engine.compare(computer.address.toString()))
        assertEquals("done", ended()["index"], stages.joinToString("\n"))
        val have = computer.newerAsked.single()["have"] as JsonObject
        assertTrue(IndexTransfer.SITES.all { (have[it] as JsonObject)["since"] == JsonNull }, have.toString())
        assertEquals(IndexTransfer.SITES.associateWith { "2026-11-04T12:00:00Z" }, phone.read { Have.cuts(it, computer.id) })
    }

    @Test fun `a document too large for the computer, or a computer that allows no POST there, gets the whole export`() {
        for (status in listOf(413, 405)) {
            aNightOnAgain()
            computer.newer = { corpusExport("newer") }
            computer.newerRefusal = status
            apply(engine.compare(computer.address.toString()))
            assertEquals("done", ended()["index"], "$status: " + stages.joinToString("\n"))
            assertEquals(listOf<List<String>?>(IndexTransfer.SITES), computer.indexAsked, "$status")
            assertEquals(indexRows(Dumps.fixture("tonight-after")), indexRows(phone.read { Dumps.lines(it) }), "$status")
        }
    }

    @Test fun `a 400 from the part's route fails the index stage, a bug that shows, never the whole in its place`() {
        aNightOn(cut = true)
        computer.newer = { corpusExport("newer") }
        computer.newerRefusal = 400
        apply(engine.compare(computer.address.toString()))
        assertEquals("failed", stages.last { it.first == "index" }.second)
        assertEquals(emptyList(), computer.indexAsked)
    }

    @Test fun `a part whose time is past the merge's clock bound is merged but cuts nothing`() {
        aNightOn(cut = true)
        // The phone's clock: two days before the computer made the part (2026-11-04T12:00Z), a day's bound short of it.
        engine.clock = { Instant.parse("2026-11-02T10:00:00Z") }
        computer.newer = { corpusExport("newer") }
        apply(engine.compare(computer.address.toString()))
        assertEquals("done", ended()["index"], stages.joinToString("\n"))
        assertEquals(1, computer.newerAsked.size)
        assertEquals(IndexTransfer.SITES.associateWith { "2026-11-03T12:00:00Z" }, phone.read { Have.cuts(it, computer.id) },
                     "rows dated after the bound were passed over: the cut stays")
    }

    /** [aNightOn] again, with the phone and the computer as they were: a fresh phone and FakeComputer. */
    private fun aNightOnAgain() {
        computer.close()
        phone.close()
        val dir = tmp.newFolder()
        phone = TestDb.fresh(dir)
        phoneLibrary = File(dir, "library").apply { mkdirs() }
        phoneStore = LibraryStore(phoneLibrary)
        stateDir = tmp.newFolder()
        computer = FakeComputer(tmp.newFolder())
        engine = engine()
        stages.clear()
        aNightOn(cut = true)
    }

    @Test fun `any other refusal of the part fails the index stage, and the whole is never asked for in its place`() {
        aNightOn(cut = true)
        computer.newer = { corpusExport("newer") }
        computer.newerRefusal = 503
        val before = phone.read { Dumps.lines(it) }
        apply(engine.compare(computer.address.toString()))
        val (_, state, detail) = stages.last { it.first == "index" }
        assertEquals("failed", state)
        assertTrue("503" in detail && "the disk is full" in detail, detail)
        assertEquals(emptyList(), computer.indexAsked)
        assertEquals(indexRows(before), indexRows(phone.read { Dumps.lines(it) }))
    }

    @Test fun `a part that left out a sitemap the phone holds otherwise loses no row and notes nothing as taken`() {
        aNightOn(cut = true)
        computer.newer = { corpusExport("lying") }
        val cut = phone.read { Have.cuts(it, computer.id) }
        apply(engine.compare(computer.address.toString()))
        val (_, state, detail) = stages.last { it.first == "index" }
        assertEquals("failed", state, stages.joinToString("\n"))
        assertTrue("isn't the part asked for" in detail && "holds otherwise" in detail, detail)
        // The merge read neither as gone (the corpus's lying-after), and nothing says the phone holds them.
        assertEquals(indexRows(Dumps.fixture("lying-after")), indexRows(phone.read { Dumps.lines(it) }))
        assertEquals(cut, phone.read { Have.cuts(it, computer.id) })
        assertNull(phone.read { it.kvGet(SyncEngine.INDEX_KEY + computer.id) })
        assertEquals(emptyMap(), phone.read { MergedIndexes.of(it) })
    }

    private companion object {
        const val NOW = "2026-11-03T10:00:00Z"
        const val RICH = "sync/fixtures/rich.jsonl"

        /** The catalogues' story: the computer's index read, published, read again a week on, and the sync. */
        const val EARLY = "2026-11-17T03:30:00Z"
        const val CATALOGUES_AT = "2026-11-18T04:00:00Z"
        const val LATE = "2026-11-24T03:30:00Z"
        const val SYNCED_AT = "2026-11-25T10:00:00Z"
    }
}
