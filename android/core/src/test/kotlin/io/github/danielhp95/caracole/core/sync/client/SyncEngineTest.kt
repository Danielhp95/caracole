package io.github.danielhp95.caracole.core.sync.client

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.Comparison
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.Side
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.SyncFailed
import io.github.danielhp95.caracole.core.sync.SyncOutcome
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.sync.FakeComputer
import io.github.danielhp95.caracole.mirror.ServerAddress
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.io.IOException
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
        Landed.assume()
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

    private fun engine(mirror: (suspend (String) -> Unit)? = null) =
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
                      on: SyncEngine = engine): SyncOutcome = runBlocking {
        on.apply(c, choices, prefer) { name, state, detail -> stages.add(Triple(name, state, detail)) }
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
        assertFalse(c.syncedBefore)
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
        assertTrue(again.syncedBefore)
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
        assertEquals(listOf(unitOf(song) to "skipped"), outcome.left)
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
        assertEquals(listOf(unitOf(creep) to "changed there since the comparison"), outcome.left)
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
        assertEquals(SyncEngine.CHANGED_SINCE, refused.message)
        assertEquals("failed", ended()["compare"])
        assertEquals(setOf("compare"), ended().keys)
        assertEquals(emptyMap(), phoneState())
    }

    @Test fun `a push the computer fails to take leaves what was given, and neither base moves`() {
        val hysteria = onPhone("Muse", "Hysteria")
        val creep = onComputer("Radiohead", "Creep")
        computer.takeFails = "database is locked"
        val failed = assertFailsWith<SyncFailed> { apply(engine.compare(computer.address.toString())) }
        assertTrue("database is locked" in failed.message!!, failed.message)
        val outcome = assertNotNull(failed.outcome)
        assertEquals(listOf(unitOf(creep)), outcome.taken)
        assertEquals(emptyList(), outcome.given)
        assertEquals(listOf(unitOf(hysteria)), outcome.left.map { it.first })
        assertTrue(outcome.left.single().second.startsWith("not given: "), outcome.left.toString())
        assertEquals("failed", ended()["give"])
        assertNull(ended()["agree"])
        assertNull(phone.read { Compare.baseOf(it, computer.id) })
        assertNull(computer.database.read { Compare.baseOf(it, phoneId) })
        assertNull(phone.read { it.kvGet(SyncEngine.PEER_KEY + computer.id) })
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
                                 "gtptabs" to "2026-10-01T00:00:00Z")
        computer.index = { "not an index export".toByteArray() }
        val outcome = apply(engine.compare(computer.address.toString()))
        assertEquals(listOf<List<String>?>(listOf("gtptabs", "ug")), computer.indexAsked)
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
    }

    @Test fun `the mirror is brought up to date after the give, and its failure stops nothing`() {
        onComputer("Radiohead", "Creep")
        val asked = CopyOnWriteArrayList<String>()
        val mirrored = engine { address -> asked.add(address); throw IOException("no space left") }
        val outcome = apply(mirrored.compare(computer.address.toString()), on = mirrored)
        assertEquals(listOf(computer.address.toString()), asked)
        assertEquals("failed", ended()["mirror"])
        assertTrue(stages.any { it.first == "mirror" && "no space left" in it.third })
        assertEquals("done", ended()["agree"])
        assertEquals(1, outcome.agreed)
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
        val refused = assertFailsWith<io.github.danielhp95.caracole.core.sync.PeerError> {
            engine.compare(computer.address.toString())
        }
        assertTrue("this phone's own" in refused.message!!, refused.message)
    }

    private companion object {
        const val NOW = "2026-11-03T10:00:00Z"
        const val RICH = "sync/fixtures/rich.jsonl"
    }
}
