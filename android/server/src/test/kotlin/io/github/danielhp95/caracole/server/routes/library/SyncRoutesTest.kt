package io.github.danielhp95.caracole.server.routes.library

import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.sync.Compare
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.core.testing.sync.FakeComputer
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.routes.SyncRoutes
import io.github.danielhp95.caracole.server.routes.SyncSettings
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.text
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
import java.time.ZoneOffset
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
    private lateinit var routes: SyncRoutes
    private lateinit var app: TestApp

    @Before fun up() {
        val phone = tmp.newFolder("phone")
        val state = tmp.newFolder("state")
        computer = FakeComputer(tmp.newFolder("computer"))
        queue = JobQueue(scope)
        app = TestApp(phone, modules = { database ->
            engine = SyncEngine(database, LibraryStore(File(phone, "library")), state,
                                client = { PeerClient(ServerAddress.parse(it)) }, mirrorRefresh = null)
            routes = SyncRoutes(engine, queue, settings, database, afterSync = { synced.incrementAndGet() },
                                zone = { ZoneOffset.UTC })
            listOf(routes)
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
        assertEquals("'ftp://laptop' isn't a caracole serve address (http://HOST:PORT).",
                     answer.json.jsonObject.getValue("error").jsonPrimitive.content)
        for ((typed, said) in listOf(
            "desk:80x" to "'desk:80x' isn't an address we can ask: Port could not be cast to integer value as '80x'",
            "desk:99999" to "'desk:99999' isn't an address we can ask: Port out of range 0-65535",
            "http://desk:8737/peer" to "'http://desk:8737/peer' isn't a caracole serve address (http://HOST:PORT).",
            "http://[::1:8737" to "'http://[::1:8737' isn't an address we can ask: Invalid IPv6 URL",
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
        onPhone("Muse", "Hysteria")
        val answer = app.script("/api/sync")
        assertEquals(200, answer.status)
        val me = app.database.read { Compare.ownId(it) }
        assertEquals(JsonObject(linkedMapOf(
            "server" to JsonPrimitive(me), "name" to JsonPrimitive("Phone"), "device" to JsonPrimitive("phone"),
            "address" to JsonPrimitive("http://192.168.1.20:8737"),
            "peers" to JsonArray(listOf(
                peer("http://10.0.0.7:8737", "9a8b7c6d5e4f3021", "Studio", "2026-11-03T08:00:00Z"),
                peer("http://192.168.1.20:8737", "0f1e2d3c4b5a6978", "Desk", "2026-11-02T21:04:00Z"),
            )),
            "songs" to JsonPrimitive(1), "songbooks" to JsonPrimitive(0),
        )), answer.json)
        assertEquals(listOf("server", "name", "device", "address", "peers", "songs", "songbooks"),
                     answer.json.jsonObject.keys.toList())
    }

    private fun peer(address: String, server: String, name: String, at: String) = JsonObject(linkedMapOf(
        "address" to JsonPrimitive(address), "server" to JsonPrimitive(server), "name" to JsonPrimitive(name),
        "synced_at" to JsonPrimitive(at),
    ))

    @Test fun `compare answers the comparison the tab draws, and remembers the address`() {
        val creep = onComputer("Radiohead", "Creep")
        val compared = compare()
        assertEquals(listOf("comparison", "peer", "synced_before", "holds", "differences", "songbooks", "indexes"),
                     compared.keys.toList())
        assertEquals(JsonObject(linkedMapOf(
            "address" to JsonPrimitive(computer.address.toString()), "server" to JsonPrimitive(computer.id),
            "caracole" to JsonPrimitive("0.1.0"), "name" to JsonPrimitive("Desk"), "kind" to JsonPrimitive("computer"),
            "made" to JsonNull,
        )), compared["peer"])
        assertEquals(JsonNull, compared["synced_before"])
        val digest = computer.state().getValue("song/${creep.key}").digest
        assertEquals(JsonArray(listOf(JsonObject(linkedMapOf(
            "id" to JsonPrimitive("song/${creep.key}"), "label" to JsonPrimitive("Radiohead - Creep"),
            "kind" to JsonPrimitive("song"), "proposal" to JsonPrimitive("theirs"), "why" to JsonPrimitive("only in theirs"),
            "here" to JsonNull, "there" to JsonPrimitive(digest),
            "names" to JsonObject(linkedMapOf("artist" to JsonPrimitive("Radiohead"), "title" to JsonPrimitive("Creep"))),
            "change" to JsonArray(listOf(JsonNull, JsonPrimitive("new"))), "part" to JsonPrimitive("library"),
            "with" to JsonArray(emptyList()),
        )))), compared["differences"])
        assertEquals(JsonObject(emptyMap()), compared["songbooks"])
        assertEquals(JsonArray(emptyList()), compared["indexes"])
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
        assertEquals("${computer.address} answered 503: The push couldn't be opened: disk full.",
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
        assertEquals("Shared · 1 change left as it was", view.getValue("line").jsonObject.getValue("text").jsonPrimitive.content)
        assertEquals(JsonArray(listOf(JsonArray(listOf(JsonPrimitive("song/muse/hysteria"),
                                                       JsonPrimitive("their Journal entry 1: failed"))))),
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
        assertEquals("Already sharing with ${computer.address} (request 1). Compare again once it's done.",
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


    // --- the sync redesign's routes (Task 18) -------------------------------------------------------------------------

    private fun kvRows() = app.database.read { db -> db.query("SELECT key, value FROM kv ORDER BY key") { it.text(0) to it.text(1) } }

    @Test fun `test says the computer's counts in Python's words, and changes nothing`() {
        computer.load(RICH)
        computer.indexes = mapOf("ug" to "2026-11-01T03:30:00Z", "lacuerda" to "2026-11-02T23:30:00-01:00",
                                 "gtptabs" to "not a time")
        val before = kvRows()
        val answer = app.postScript("/sync/test", listOf("address" to computer.address.toString()))
        assertEquals(200, answer.status, answer.text)
        val tested = answer.json.jsonObject
        assertEquals(listOf("peer", "songs", "songbooks", "indexes", "synced_at", "said"), tested.keys.toList())
        assertEquals(JsonObject(linkedMapOf(
            "address" to JsonPrimitive(computer.address.toString()), "server" to JsonPrimitive(computer.id),
            "caracole" to JsonPrimitive("0.1.0"), "name" to JsonPrimitive("Desk"),
        )), tested["peer"])
        assertEquals(JsonPrimitive(4), tested["songs"])
        assertEquals(JsonPrimitive(1), tested["songbooks"])
        assertEquals(JsonPrimitive("2026-11-02T23:30:00-01:00"), tested["indexes"],
                     "the newest read that is a time, as the computer wrote it, by its instant (00:30 UTC on the 3rd)")
        assertEquals(JsonNull, tested["synced_at"])
        assertEquals(JsonPrimitive("Desk answered: 4 songs, 1 songbook, its indexes read 03/11/26"), tested["said"])
        assertEquals(before, kvRows(), "nothing written")
        assertNull(settings.address, "nothing remembered either")
        assertEquals(listOf("/api/peer/state"), computer.requests.map { it.substringAfter(' ').substringBefore('?') }.distinct())
        assertEquals(tested, routes.tested(computer.address.toString()), "Settings' Test is the route's")

        computer.indexes = mapOf("gtptabs" to "not a time")
        assertEquals("Desk answered: 4 songs, 1 songbook, no indexes", routes.tested(computer.address.toString())
            .getValue("said").jsonPrimitive.content)
        assertEquals("Studio answered: 1 song, 0 songbooks, its indexes read 02/11/26",
                     routes.testedWords("Studio", 1, 0, "2026-11-02T03:30:00Z"))
    }

    @Test fun `test refuses as a comparison does`() {
        assertEquals(400, app.postScript("/sync/test", listOf("address" to "ftp://laptop")).status)
        val address = computer.address.toString()
        val me = app.database.read { Compare.ownId(it) }
        computer.database.writeBlocking { it.kvSet("sync:id", me) }
        val same = app.postScript("/sync/test", listOf("address" to address))
        assertEquals(409, same.status)
        assertEquals("The scribe at $address is this one (same id, $me): its database is a copy of ours. " +
                     "Give one a new id: caracole peer new-id.", same.json.jsonObject.getValue("error").jsonPrimitive.content)
        computer.close()
        assertEquals(502, app.postScript("/sync/test", listOf("address" to address)).status)
    }

    @Test fun `the comparison's new members are Python's, and a unit's two documents and the indexes are answered`() {
        computer.load(RICH)
        val wonderwall = onPhone("Oasis", "Wonderwall")
        computer.indexes = mapOf("ug" to "2026-11-03T10:00:00Z")
        val compared = compare()
        assertEquals(JsonArray(listOf(JsonPrimitive("library"), JsonPrimitive("songbooks"), JsonPrimitive("indexes"))),
                     compared["holds"])
        val differences = compared.getValue("differences").jsonArray.associateBy { it.jsonObject.getValue("id").jsonPrimitive.content }
        val creep = differences.getValue("song/radiohead/creep").jsonObject
        assertEquals(JsonArray(listOf(JsonPrimitive("songbook/campfire"))), creep["with"])
        assertEquals(JsonPrimitive("library"), creep["part"])
        val campfire = differences.getValue("songbook/campfire").jsonObject
        assertEquals(JsonNull, campfire["names"])
        assertEquals(JsonPrimitive("songbooks"), campfire["part"])
        assertEquals(JsonArray(listOf(JsonNull, JsonPrimitive("new"))), campfire["change"])
        val mine = differences.getValue("song/${wonderwall.key}").jsonObject
        assertEquals(JsonArray(listOf(JsonPrimitive("new"), JsonNull)), mine["change"])
        assertEquals(JsonArray(emptyList()), mine["with"])
        val book = compared.getValue("songbooks").jsonObject.getValue("songbook/campfire").jsonObject
        assertEquals(JsonNull, book["here"])
        assertEquals(JsonPrimitive("Campfire"), book.getValue("there").jsonObject["name"])
        assertEquals(JsonArray(listOf(JsonObject(linkedMapOf(
            "site" to JsonPrimitive("ug"), "title" to JsonPrimitive("Ultimate Guitar"), "here" to JsonNull,
            "there" to JsonPrimitive("2026-11-03T10:00:00Z"), "newer" to JsonPrimitive("there"),
        )))), compared["indexes"])

        val id = compared.getValue("comparison").jsonPrimitive.content
        val unit = app.script("/api/sync/unit?comparison=$id&id=songbook%2Fcampfire")
        assertEquals(200, unit.status, unit.text)
        assertEquals(JsonObject(linkedMapOf("id" to JsonPrimitive("songbook/campfire"), "here" to JsonNull,
                                            "there" to book.getValue("there"))), unit.json)
        val ours = app.script("/api/sync/unit?comparison=$id&id=song%2F${wonderwall.key.replace("/", "%2F")}").json.jsonObject
        assertEquals(JsonNull, ours["there"])
        assertEquals(JsonPrimitive("Wonderwall"), ours.getValue("here").jsonObject.getValue("names").jsonObject["title"])
        val notFound = app.script("/api/sync/unit?comparison=$id&id=song%2Fnobody%2Fnothing")
        assertEquals(404, notFound.status)
        assertEquals("'song/nobody/nothing' isn't one that comparison found: it is no unit the two hold differently.",
                     notFound.json.jsonObject.getValue("error").jsonPrimitive.content)
        assertEquals(409, app.script("/api/sync/unit?comparison=0123456789abcdef&id=songbook%2Fcampfire").status)
        assertEquals(403, app.get("/api/sync/unit?comparison=$id&id=songbook%2Fcampfire").status,
                     "the page's script alone asks it, with the form token")

        val indexes = app.script("/api/sync/indexes")
        assertEquals(200, indexes.status)
        val sites = indexes.json.jsonObject.getValue("indexes").jsonObject
        assertEquals(listOf("ug", "lacuerda", "gtptabs", "musescore", "harptabs", "gametabs"), sites.keys.toList())
        assertEquals(JsonObject(linkedMapOf("read" to JsonNull, "tabs" to JsonPrimitive(0))), sites["ug"])
    }

    @Test fun `apply sends the parts to the engine`() {
        computer.load(RICH)
        val hysteria = onPhone("Muse", "Hysteria")
        val id = compare().getValue("comparison").jsonPrimitive.content
        for (parts in listOf("library,lyrics", "", " , ")) {
            val refused = app.postScript("/sync/apply", listOf("comparison" to id, "parts" to parts))
            assertEquals(400, refused.status, parts)
            assertEquals(SyncRoutes.NOT_A_PART, refused.json.jsonObject.getValue("error").jsonPrimitive.content)
        }
        assertEquals(emptyList(), queue.snapshot())
        val answer = app.postScript("/sync/apply", listOf("comparison" to id, "parts" to " songbooks"))
        assertEquals(200, answer.status, answer.text)
        val job = waitFor(answer.json.jsonObject.getValue("job").jsonObject)
        assertEquals("done", job.state)
        assertEquals(setOf("song/radiohead/creep", "song/radiohead/karma-police", "songbook/campfire",
                           "song/${hysteria.key}"),
                     app.database.read { Units.libraryState(it) }.keys, "the songbook and the songs it lists alone")
        assertTrue("song/${hysteria.key}" !in computer.state(), "nothing of the library given")
        val steps = job.asJson().getValue("steps").jsonArray.associate {
            it.jsonObject.getValue("name").jsonPrimitive.content to it.jsonObject.getValue("state").jsonPrimitive.content
        }
        assertEquals("skipped", steps["mirror"])
        assertEquals("skipped", steps["index"])
        val report = JobViews.view(job, queue).getValue("outcome").jsonObject.getValue("report").jsonObject
        assertEquals(JsonArray(listOf(JsonPrimitive("songbooks"))), report["parts"])
    }

    @Test fun `alone queues one sync that leaves conflicts and refuses a second while it runs`() {
        val hysteria = onPhone("Muse", "Hysteria")
        val wonderwall = onPhone("Oasis", "Wonderwall", album = "Morning Glory")
        val creep = onComputer("Radiohead", "Creep")
        onComputer("Oasis", "Wonderwall", album = "(What's the Story) Morning Glory?")
        val unit = "song/${wonderwall.key}"
        val before = computer.state().getValue(unit) to app.database.read { Units.libraryState(it) }.getValue(unit)
        computer.holdTakes = java.util.concurrent.CountDownLatch(1)
        val address = computer.address.toString()

        val job = routes.alone(address)
        assertTrue(job != null)
        assertEquals("sync", job.spec.kind)
        assertNull(routes.alone(address), "one sync with that computer at a time")
        computer.holdTakes!!.countDown()
        computer.holdTakes = null
        val ended = runBlocking { withTimeout(20_000) { queue.await(job.id) } }
        assertEquals("done", ended.state)
        val outcome = JobViews.view(ended, queue).getValue("outcome").jsonObject
        assertEquals(JsonArray(listOf(JsonPrimitive("song/${creep.key}"))), outcome["taken"])
        assertEquals(JsonArray(listOf(JsonPrimitive("song/${hysteria.key}"))), outcome["given"])
        assertEquals(JsonArray(listOf(JsonArray(listOf(JsonPrimitive(unit), JsonPrimitive(SyncEngine.UNSETTLED))))),
                     outcome["left"])
        assertEquals(before, computer.state().getValue(unit) to app.database.read { Units.libraryState(it) }.getValue(unit),
                     "the conflict as it was on both sides")
        assertEquals(1, synced.get())
        assertTrue(routes.alone(address) != null, "once over, another may be queued")
    }

    @Test fun `alone with nothing answering fails its compare stage in its words and skips the rest`() {
        val address = computer.address.toString()
        computer.close()
        val job = routes.alone(address)!!
        val ended = runBlocking { withTimeout(20_000) { queue.await(job.id) } }
        assertEquals("failed", ended.state)
        val steps = ended.asJson().getValue("steps").jsonArray.associate {
            it.jsonObject.getValue("name").jsonPrimitive.content to it.jsonObject.getValue("state").jsonPrimitive.content
        }
        assertEquals(mapOf("compare" to "failed", "take" to "skipped", "give" to "skipped", "mirror" to "skipped",
                           "agree" to "skipped", "index" to "skipped"), steps)
    }

    private companion object {
        const val NOW = "2026-11-03T10:00:00Z"
        const val RICH = "sync/fixtures/rich.jsonl"
    }
}
