package io.github.danielhp95.caracole.core.sync.client

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
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
        assertEquals(listOf(unitOf(song) to "skipped, as chosen"), outcome.left)
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
        assertEquals("The two changed since that comparison: compare them again, and choose again.", refused.message)
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
        assertEquals(listOf(unitOf(hysteria) to "its request 1 there failed"), outcome.left, "as peer sync --push says it")
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
        assertEquals(listOf(unitOf(karma) to "changed here since the comparison"), outcome.left)
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
        assertEquals("1 unit the two agree on", stages.last { it.first == "agree" }.third)
        assertEquals(emptyList(), engine.compare(computer.address.toString()).differences, "settings are no unit")
    }

    @Test fun `with nothing to take or give, the settings are taken all the same`() {
        computer.settings = FakeComputer.SETTINGS
        val outcome = apply(engine.compare(computer.address.toString()))
        assertEquals(SyncOutcome(emptyList(), emptyList(), emptyList(), 0, emptyList()), outcome)
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
        assertEquals("The caracole at ${computer.address} is this one (the same id, $phoneId): its database is a " +
                     "copy of this one's. Give one of them another: caracole peer new-id.", refused.message)
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
            "format" to JsonPrimitive(2), "from" to JsonPrimitive(phoneId), "name" to JsonPrimitive("Phone"),
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
        assertEquals("The caracole at ${computer.address} answered 400: 1 file the push keeps was never sent, nor kept " +
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
            assertEquals("There couldn't be given its 1: The caracole at ${computer.address} answered 503: The file " +
                         "couldn't be kept: disk full.", failed.message)
            assertEquals("failed", ended()["give"])
            assertNull(ended()["agree"], "no agreement recorded")
            stages.clear()
        }
        assertEquals(2, computer.pushesHere)
        val third = assertFailsWith<SyncFailed> { apply(engine.compare(computer.address.toString())) }
        assertEquals("There couldn't be given its 1: The caracole at ${computer.address} answered 409: Two pushes are " +
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
        assertEquals("There couldn't be given its 1: The caracole at ${computer.address} hasn't taken the push yet: its " +
                     "request 1, in its Requests tab, goes on.", gaveUp.message)
        assertEquals(3, computer.asked("GET", "/api/jobs/1").size)

        val refused = assertFailsWith<SyncFailed> { apply(waiting.compare(computer.address.toString()), on = waiting) }
        assertEquals("There couldn't be given its 1: The caracole at ${computer.address} answered 409: Changes from " +
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

    private companion object {
        const val NOW = "2026-11-03T10:00:00Z"
        const val RICH = "sync/fixtures/rich.jsonl"
    }
}
