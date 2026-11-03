package io.github.danielhp95.caracole.server.routes.library

import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.testing.sync.FakeComputer
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.routes.SyncRoutes
import io.github.danielhp95.caracole.server.routes.SyncSettings
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.json
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** The Sync tab's routes on the phone, through TestApp, against FakeComputer. */
class SyncRoutesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val settings = object : SyncSettings {
        override var address: String? = null
        override fun remember(address: String) { this.address = address }
    }
    private val synced = AtomicInteger()
    private lateinit var computer: FakeComputer
    private lateinit var queue: JobQueue
    private lateinit var engine: SyncEngine
    private lateinit var app: TestApp

    @Before fun up() {
        val phone = tmp.newFolder("phone")
        val state = tmp.newFolder("state")
        computer = FakeComputer(tmp.newFolder("computer"))
        queue = JobQueue(scope)
        app = TestApp(phone, modules = { database ->
            engine = SyncEngine(database, LibraryStore(File(phone, "library")), state,
                                client = { PeerClient(ServerAddress.parse(it)) }, mirrorRefresh = null)
            listOf(SyncRoutes(engine, queue, settings, database, afterSync = { synced.incrementAndGet() }))
        })
    }

    @After fun down() {
        scope.cancel()
        if (::app.isInitialized) app.close()
        if (::computer.isInitialized) computer.close()
    }

    private val phoneStore get() = LibraryStore(app.libraryDir)
    private fun onComputer(artist: String, title: String, album: String? = null) =
        computer.database.writeBlocking { computer.store.add(it, artist, title, album = album, now = NOW) }
    private fun onPhone(artist: String, title: String, album: String? = null) =
        app.database.writeBlocking { phoneStore.add(it, artist, title, album = album, now = NOW) }

    private fun compare(): JsonObject {
        val answer = app.postScript("/sync/compare", listOf("address" to computer.address.toString()))
        assertEquals(200, answer.status, answer.json.toString())
        return answer.json.jsonObject
    }

    private fun waitFor(view: JsonObject) = runBlocking {
        withTimeout(20_000) { queue.await(view.getValue("id").jsonPrimitive.int) }
    }

    @Test fun `the address is read before anything, as the mirror reads one`() {
        val answer = app.postScript("/sync/compare", listOf("address" to "ftp://laptop"))
        assertEquals(400, answer.status)
        assertTrue("isn't an address the app can use" in answer.json.jsonObject.getValue("error").jsonPrimitive.content)
        assertNull(settings.address)
        assertEquals(emptyList(), computer.requests)
    }

    @Test fun `a comparison it doesn't keep is refused, 409, saying to compare again`() {
        val answer = app.postScript("/sync/apply", listOf("comparison" to "0123456789abcdef", "prefer" to "",
                                                          "choices" to ""))
        assertEquals(409, answer.status)
        assertTrue("compare again" in answer.json.jsonObject.getValue("error").jsonPrimitive.content)
    }

    @Test fun `the apply form may be a megabyte long`() {
        assertEquals(SyncRoutes.APPLY_LIMIT, app.app.bodyLimit("POST", "/sync/apply"))
        val long = "x".repeat(100_000)
        val answer = app.postScript("/sync/apply", listOf("comparison" to "0123456789abcdef", "choices" to long))
        assertEquals(409, answer.status, "read whole, then refused for its comparison, not for its length")
    }

    @Test fun `GET api sync says this phone, the address remembered and the computers synced with, the last first`() {
        Landed.assume()
        settings.address = "http://192.168.1.20:8737"
        app.database.writeBlocking { db ->
            db.kvSet("sync:peer:0f1e2d3c4b5a6978", """{"address": "http://192.168.1.20:8737", "name": "Desk", "synced_at": "2026-11-02T21:04:00Z"}""")
            db.kvSet("sync:peer:9a8b7c6d5e4f3021", """{"address": "http://10.0.0.7:8737", "name": "Studio", "synced_at": "2026-11-03T08:00:00Z"}""")
            db.kvSet("sync:peer:ffffffffffffffff", """not JSON""")
        }
        val answer = app.script("/api/sync")
        assertEquals(200, answer.status)
        val me = app.database.read { Compare.ownId(it) }
        assertEquals(JsonObject(linkedMapOf(
            "server" to JsonPrimitive(me), "name" to JsonPrimitive("Phone"),
            "address" to JsonPrimitive("http://192.168.1.20:8737"),
            "peers" to JsonArray(listOf(
                peer("http://10.0.0.7:8737", "9a8b7c6d5e4f3021", "Studio", "2026-11-03T08:00:00Z"),
                peer("http://192.168.1.20:8737", "0f1e2d3c4b5a6978", "Desk", "2026-11-02T21:04:00Z"),
            )),
        )), answer.json)
        assertEquals(listOf("server", "name", "address", "peers"), answer.json.jsonObject.keys.toList())
    }

    private fun peer(address: String, server: String, name: String, at: String) = JsonObject(linkedMapOf(
        "address" to JsonPrimitive(address), "server" to JsonPrimitive(server), "name" to JsonPrimitive(name),
        "synced_at" to JsonPrimitive(at),
    ))

    @Test fun `compare answers the comparison the tab draws, and remembers the address`() {
        Landed.assume()
        val creep = onComputer("Radiohead", "Creep")
        val compared = compare()
        assertEquals(listOf("comparison", "peer", "synced_before", "differences"), compared.keys.toList())
        assertEquals(JsonObject(linkedMapOf(
            "address" to JsonPrimitive(computer.address.toString()), "server" to JsonPrimitive(computer.id),
            "caracole" to JsonPrimitive("0.1.0"), "name" to JsonPrimitive("Desk"),
        )), compared["peer"])
        assertEquals(JsonPrimitive(false), compared["synced_before"])
        val digest = computer.state().getValue("song/${creep.key}").digest
        assertEquals(JsonArray(listOf(JsonObject(linkedMapOf(
            "id" to JsonPrimitive("song/${creep.key}"), "label" to JsonPrimitive("Radiohead - Creep"),
            "kind" to JsonPrimitive("song"), "proposal" to JsonPrimitive("theirs"), "why" to JsonPrimitive("only there"),
            "here" to JsonNull, "there" to JsonPrimitive(digest),
        )))), compared["differences"])
        assertEquals(computer.address.toString(), settings.address)
    }

    @Test fun `compare with a computer that answers nothing is refused, 409, in the mirror's words`() {
        Landed.assume()
        val address = computer.address.toString()
        computer.close()
        val answer = app.postScript("/sync/compare", listOf("address" to address))
        assertEquals(409, answer.status)
        assertTrue("No answer from" in answer.json.jsonObject.getValue("error").jsonPrimitive.content)
        assertEquals(address, settings.address)
    }

    @Test fun `compare then apply ends with the job done and the two libraries alike`() {
        Landed.assume()
        val wonderwall = onPhone("Oasis", "Wonderwall", album = "Morning Glory")
        onPhone("Muse", "Hysteria")
        onComputer("Oasis", "Wonderwall", album = "(What's the Story) Morning Glory?")
        onComputer("Radiohead", "Creep")
        val compared = compare()
        val answer = app.postScript("/sync/apply", listOf(
            "comparison" to compared.getValue("comparison").jsonPrimitive.content, "prefer" to "",
            "choices" to "there\tsong/${wonderwall.key}",
        ))
        assertEquals(200, answer.status, answer.json.toString())
        val view = answer.json.jsonObject.getValue("job").jsonObject
        assertEquals(JsonPrimitive("sync"), view["kind"])
        val job = waitFor(view)
        assertEquals("done", job.state)
        assertEquals(listOf("compare", "take", "give", "mirror", "agree", "index"),
                     job.asJson().getValue("steps").jsonArray.map { it.jsonObject.getValue("name").jsonPrimitive.content })
        assertEquals(computer.state(), app.database.read { Units.libraryState(it) })
        assertEquals(1, synced.get())
        val again = compare()
        assertEquals(JsonPrimitive(true), again["synced_before"])
        assertEquals(JsonArray(emptyList()), again["differences"])
    }

    @Test fun `a conflict without a choice is refused, 409, and nothing is queued`() {
        Landed.assume()
        onPhone("Oasis", "Wonderwall", album = "A")
        onComputer("Oasis", "Wonderwall", album = "B")
        val compared = compare()
        val answer = app.postScript("/sync/apply", listOf(
            "comparison" to compared.getValue("comparison").jsonPrimitive.content, "prefer" to "", "choices" to ""))
        assertEquals(409, answer.status)
        assertTrue("every conflict" in answer.json.jsonObject.getValue("error").jsonPrimitive.content)
        assertEquals(emptyList(), queue.snapshot())
        // prefer settles it.
        val preferred = app.postScript("/sync/apply", listOf(
            "comparison" to compared.getValue("comparison").jsonPrimitive.content, "prefer" to "here", "choices" to ""))
        assertEquals(200, preferred.status)
        assertEquals("done", waitFor(preferred.json.jsonObject.getValue("job").jsonObject).state)
    }

    @Test fun `a choice that names no difference, or no side, is refused, 400`() {
        Landed.assume()
        onComputer("Radiohead", "Creep")
        val id = compare().getValue("comparison").jsonPrimitive.content
        for (choice in listOf("there\tsong/nobody/nothing", "sideways\tsong/radiohead/creep", "song/radiohead/creep")) {
            val answer = app.postScript("/sync/apply", listOf("comparison" to id, "choices" to choice))
            assertEquals(400, answer.status, choice)
        }
        val answer = app.postScript("/sync/apply", listOf("comparison" to id, "prefer" to "both"))
        assertEquals(400, answer.status)
    }

    @Test fun `a sync that fails says what it did in its outcome, and the page's data is read again all the same`() {
        Landed.assume()
        onPhone("Muse", "Hysteria")
        onComputer("Radiohead", "Creep")
        computer.takeFails = "database is locked"
        val compared = compare()
        val answer = app.postScript("/sync/apply", listOf("comparison" to compared.getValue("comparison").jsonPrimitive.content))
        val job = waitFor(answer.json.jsonObject.getValue("job").jsonObject)
        assertEquals("failed", job.state)
        assertEquals(1, synced.get())
        val view = io.github.danielhp95.caracole.server.jobs.JobViews.view(job, queue)
        val outcome = view.getValue("outcome").jsonObject
        assertEquals(1, outcome.getValue("taken").jsonArray.size)
        assertEquals(0, outcome.getValue("given").jsonArray.size)
        assertEquals(1, outcome.getValue("left").jsonArray.size)
    }

    private companion object {
        const val NOW = "2026-11-03T10:00:00Z"
    }
}
