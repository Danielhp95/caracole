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

    @Test fun `the address is read before anything, as peer_address reads one`() {
        val answer = app.postScript("/sync/compare", listOf("address" to "ftp://laptop"))
        assertEquals(400, answer.status)
        assertEquals("'ftp://laptop' isn't the address of a caracole serve (http://HOST:PORT)",
                     answer.json.jsonObject.getValue("error").jsonPrimitive.content)
        for ((typed, said) in listOf(
            "desk:80x" to "'desk:80x' isn't an address caracole can ask: Port could not be cast to integer value as '80x'",
            "desk:99999" to "'desk:99999' isn't an address caracole can ask: Port out of range 0-65535",
            "http://desk:8737/peer" to "'http://desk:8737/peer' isn't the address of a caracole serve (http://HOST:PORT)",
            "http://[::1:8737" to "'http://[::1:8737' isn't an address caracole can ask: Invalid IPv6 URL",
        )) {
            val refused = app.postScript("/sync/compare", listOf("address" to typed))
            assertEquals(400, refused.status, typed)
            assertEquals(said, refused.json.jsonObject.getValue("error").jsonPrimitive.content)
        }
        assertNull(settings.address)
        assertEquals(emptyList(), computer.requests)
    }

    @Test fun `a comparison it doesn't keep is refused, 409, saying to compare again`() {
        val answer = app.postScript("/sync/apply", listOf("comparison" to "0123456789abcdef", "prefer" to "",
                                                          "choices" to ""))
        assertEquals(409, answer.status)
        assertEquals(SyncRoutes.GONE, answer.json.jsonObject.getValue("error").jsonPrimitive.content)
    }

    @Test fun `the apply form may be a megabyte long`() {
        assertEquals(SyncRoutes.APPLY_LIMIT, app.app.bodyLimit("POST", "/sync/apply"))
        val long = "x".repeat(100_000)
        val answer = app.postScript("/sync/apply", listOf("comparison" to "0123456789abcdef", "choices" to long))
        assertEquals(409, answer.status, "read whole, then refused for its comparison, not for its length")
    }

    @Test fun `GET api sync says this phone, the address remembered and the computers synced with, the last first`() {
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
        val creep = onComputer("Radiohead", "Creep")
        val compared = compare()
        assertEquals(listOf("comparison", "peer", "synced_before", "differences"), compared.keys.toList())
        assertEquals(JsonObject(linkedMapOf(
            "address" to JsonPrimitive(computer.address.toString()), "server" to JsonPrimitive(computer.id),
            "caracole" to JsonPrimitive("0.1.0"), "name" to JsonPrimitive("Desk"),
        )), compared["peer"])
        assertEquals(JsonNull, compared["synced_before"])
        val digest = computer.state().getValue("song/${creep.key}").digest
        assertEquals(JsonArray(listOf(JsonObject(linkedMapOf(
            "id" to JsonPrimitive("song/${creep.key}"), "label" to JsonPrimitive("Radiohead - Creep"),
            "kind" to JsonPrimitive("song"), "proposal" to JsonPrimitive("theirs"), "why" to JsonPrimitive("only there"),
            "here" to JsonNull, "there" to JsonPrimitive(digest),
        )))), compared["differences"])
        assertEquals(computer.address.toString(), settings.address)
    }

    @Test fun `compare with a computer that answers nothing is refused, 502, in the mirror's words`() {
        val address = computer.address.toString()
        computer.close()
        val answer = app.postScript("/sync/compare", listOf("address" to address))
        assertEquals(502, answer.status)
        assertTrue("No answer from" in answer.json.jsonObject.getValue("error").jsonPrimitive.content)
        assertEquals(address, settings.address)
    }

    @Test fun `compare then apply ends with the job done and the two libraries alike`() {
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
        assertEquals(JsonPrimitive(computer.now), again["synced_before"])
        assertEquals(JsonArray(emptyList()), again["differences"])
    }

    @Test fun `a conflict without a choice is refused, 409, and nothing is queued`() {
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
        onPhone("Muse", "Hysteria")
        onComputer("Radiohead", "Creep")
        computer.answers["POST /peer/push/new"] = { exchange ->
            FakeComputer.json(exchange, 503, FakeComputer.obj("error" to JsonPrimitive("The push couldn't be opened: disk full.")))
        }
        val compared = compare()
        val answer = app.postScript("/sync/apply", listOf("comparison" to compared.getValue("comparison").jsonPrimitive.content))
        val job = waitFor(answer.json.jsonObject.getValue("job").jsonObject)
        assertEquals("failed", job.state)
        assertEquals(1, synced.get())
        val view = io.github.danielhp95.caracole.server.jobs.JobViews.view(job, queue)
        val outcome = view.getValue("outcome").jsonObject
        assertEquals(1, outcome.getValue("taken").jsonArray.size)
        assertEquals(0, outcome.getValue("given").jsonArray.size)
        assertEquals(mapOf("compare" to "done", "take" to "done", "give" to "failed", "mirror" to "skipped",
                           "agree" to "skipped", "index" to "skipped"),
                     view.getValue("steps").jsonArray.associate {
                         it.jsonObject.getValue("name").jsonPrimitive.content to it.jsonObject.getValue("state").jsonPrimitive.content
                     })
        assertEquals("The caracole at ${computer.address} answered 503: The push couldn't be opened: disk full.",
                     view.getValue("line").jsonObject.getValue("text").jsonPrimitive.content.removePrefix("There couldn't be given its 1: "))
    }

    @Test fun `a push the computer can't take leaves the unit, and the sync is done, its line saying what was left`() {
        onPhone("Muse", "Hysteria")
        computer.takeFails = "database is locked"
        val compared = compare()
        val answer = app.postScript("/sync/apply", listOf("comparison" to compared.getValue("comparison").jsonPrimitive.content))
        val job = waitFor(answer.json.jsonObject.getValue("job").jsonObject)
        assertEquals("done", job.state)
        val view = io.github.danielhp95.caracole.server.jobs.JobViews.view(job, queue)
        assertEquals("Synced: 1 change left as it was", view.getValue("line").jsonObject.getValue("text").jsonPrimitive.content)
        assertEquals(JsonArray(listOf(JsonArray(listOf(JsonPrimitive("song/muse/hysteria"),
                                                       JsonPrimitive("its request 1 there failed"))))),
                     view.getValue("outcome").jsonObject["left"])
    }

    @Test fun `a sync with the computer that waits or runs refuses another, 409, and a comparison it queued is gone`() {
        onPhone("Muse", "Hysteria")
        computer.holdTakes = java.util.concurrent.CountDownLatch(1)
        val first = compare().getValue("comparison").jsonPrimitive.content
        val second = compare().getValue("comparison").jsonPrimitive.content
        val answer = app.postScript("/sync/apply", listOf("comparison" to first))
        assertEquals(200, answer.status)
        assertEquals(409, app.post("/sync/apply", listOf("comparison" to second)).status, "the browser's, refused so too")
        assertEquals(SyncRoutes.GONE, app.postScript("/sync/apply", listOf("comparison" to first)).json.jsonObject
            .getValue("error").jsonPrimitive.content, "a comparison queued is kept no more")
        val refused = app.postScript("/sync/apply", listOf("comparison" to second))
        assertEquals(409, refused.status)
        assertEquals("A sync with ${computer.address} is on its way already (request 1): compare again once it is over.",
                     refused.json.jsonObject.getValue("error").jsonPrimitive.content)
        computer.holdTakes!!.countDown()
        computer.holdTakes = null
        assertEquals("done", waitFor(answer.json.jsonObject.getValue("job").jsonObject).state)
    }

    @Test fun `a comparison the two have moved past is refused before anything is queued, and forgotten`() {
        onComputer("Radiohead", "Creep")
        val id = compare().getValue("comparison").jsonPrimitive.content
        onComputer("Radiohead", "Karma Police")
        val refused = app.postScript("/sync/apply", listOf("comparison" to id))
        assertEquals(409, refused.status)
        assertEquals(SyncEngine.STALE, refused.json.jsonObject.getValue("error").jsonPrimitive.content)
        assertEquals(emptyList(), queue.snapshot())
        assertEquals(SyncRoutes.GONE, app.postScript("/sync/apply", listOf("comparison" to id)).json.jsonObject
            .getValue("error").jsonPrimitive.content)
    }

    @Test fun `GET api sync names the library as the app names it, and the computer synced with last when none was typed`() {
        val named = TestApp(tmp.newFolder("named"), modules = { database ->
            listOf(SyncRoutes(engine, queue, object : SyncSettings {
                override val address: String? = null
                override fun remember(address: String) {}
            }, database, afterSync = {}, name = "lib"))
        })
        named.use {
            it.database.writeBlocking { db ->
                db.kvSet("sync:peer:0f1e2d3c4b5a6978", """{"address": "http://192.168.1.20:8737", "name": "Desk", "synced_at": "2026-11-02T21:04:00Z"}""")
            }
            val answer = it.script("/api/sync").json.jsonObject
            assertEquals(JsonPrimitive("lib"), answer["name"])
            assertEquals(JsonPrimitive("http://192.168.1.20:8737"), answer["address"])
        }
    }

    private companion object {
        const val NOW = "2026-11-03T10:00:00Z"
    }
}
