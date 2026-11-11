package io.github.danielhp95.caracole.core.sync.client

import com.sun.net.httpserver.HttpExchange
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.PeerError
import io.github.danielhp95.caracole.core.sync.SyncUnit
import io.github.danielhp95.caracole.core.testing.sync.FakeComputer
import io.github.danielhp95.caracole.mirror.Http
import io.github.danielhp95.caracole.mirror.SyncError
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** PeerClient speaks the computer's peer routes as peer_sync.Peer reads them, and pushes as peer_push.py takes a push,
 * against FakeComputer's routes answered by hand ([FakeComputer.answers]): no lane but this one's needed. */
class PeerClientTest {
    @get:Rule val tmp = TemporaryFolder()

    private val computer by lazy { FakeComputer(tmp.newFolder("computer")) }
    private val client by lazy { PeerClient(computer.address) }

    @After fun stop() = computer.close()

    /** What a route got: its query, headers by lowercase name, and its body. */
    private class Got(val query: String?, val headers: Map<String, String>, val body: ByteArray)

    private fun answer(route: String, status: Int, body: String, got: MutableList<Got>? = null,
                       type: String = "application/json; charset=utf-8") {
        computer.answers[route] = { exchange: HttpExchange ->
            got?.add(Got(exchange.requestURI.rawQuery,
                         exchange.requestHeaders.entries.associate { (k, v) -> k.lowercase() to v.joinToString(",") },
                         exchange.requestBody.readBytes()))
            FakeComputer.send(exchange, status, body.toByteArray(), type)
        }
    }

    private val sha = "ab".repeat(32)
    private val state = """{"format":3,"server":"0f1e2d3c4b5a6978","caracole":"0.1.0","name":"Desk",""" +
        """"now":"2026-11-03T12:00:00Z","indexes":{"lacuerda":"2026-11-02T00:00:00Z","ug":"2026-11-03T01:00:00Z"},""" +
        """"units":{"song/soda-stereo/de-musica-ligera":{"label":"Soda Stereo - De Música Ligera","digest":"$sha"},""" +
        """"removed/oasis/wonderwall":{"label":"Oasis - Wonderwall (removed)","digest":"${"cd".repeat(32)}"}},""" +
        """"base":{"song/soda-stereo/de-musica-ligera":["$sha","2026-11-01T00:00:00Z"],""" +
        """"songbook/campfire":[null,"2026-11-01T00:00:00Z"],"odd":["x"]},"token":"tok-1"}"""

    @Test fun `the state is read whole, for the phone that asks`() {
        val got = mutableListOf<Got>()
        answer("GET /api/peer/state", 200, state, got)
        val peer = client.state("a1b2c3d4e5f60718")
        assertEquals("peer=a1b2c3d4e5f60718", got.single().query)
        assertEquals("application/json", got.single().headers["accept"])
        assertEquals(3, peer.format)
        assertEquals("0f1e2d3c4b5a6978", peer.server)
        assertEquals("0.1.0", peer.caracole)
        assertEquals("Desk", peer.name)
        assertEquals("2026-11-03T12:00:00Z", peer.now)
        assertEquals("tok-1", peer.token)
        assertEquals(mapOf("lacuerda" to "2026-11-02T00:00:00Z", "ug" to "2026-11-03T01:00:00Z"), peer.indexes)
        assertEquals(listOf("song/soda-stereo/de-musica-ligera", "removed/oasis/wonderwall"), peer.units.keys.toList())
        assertEquals(SyncUnit("song/soda-stereo/de-musica-ligera", "Soda Stereo - De Música Ligera", sha),
                     peer.units["song/soda-stereo/de-musica-ligera"])
        // _read_units: its odd entries left out
        assertEquals(mapOf("song/soda-stereo/de-musica-ligera" to (sha to "2026-11-01T00:00:00Z"),
                           "songbook/campfire" to (null to "2026-11-01T00:00:00Z")), peer.base)
    }

    @Test fun `a state asked by no one has no peer, and one never synced has no base`() {
        val got = mutableListOf<Got>()
        answer("GET /api/peer/state", 200, state.replace(Regex(""""base":\{.*?\]\},"""), """"base":null,"""), got)
        assertNull(client.state(null).base)
        assertNull(got.single().query)
    }

    @Test fun `a state of another format, or none, is refused in peer_sync's words`() {
        answer("GET /api/peer/state", 200, state.replace("\"format\":3", "\"format\":2"))
        val other = assertFailsWith<PeerError> { client.state("me") }
        assertTrue("not a caracole sync state of format 3" in other.message!!, other.message)
        answer("GET /api/peer/state", 404, """{"error":"no"}""")
        val none = assertFailsWith<PeerError> { client.state("me") }
        assertTrue("not as a caracole that shares" in none.message!!, none.message)
        answer("GET /api/peer/state", 503, """{"error":"songbooks.toml can't be read: line 3."}""")
        assertEquals("${computer.address} answered 503: songbooks.toml can't be read: line 3.",
                     assertFailsWith<PeerError> { client.state("me") }.message)
        answer("GET /api/peer/state", 200, state.replace("\"label\":\"Oasis - Wonderwall (removed)\",", ""))
        assertTrue("a unit that can't be read" in assertFailsWith<PeerError> { client.state("me") }.message!!)
        answer("GET /api/peer/state", 200, "<html>a Wi-Fi login</html>", type = "text/html")
        assertTrue("isn't JSON" in assertFailsWith<PeerError> { client.state("me") }.message!!)
    }

    @Test fun `the state takes as long as a minute, where another read gives up sooner`() {
        val impatient = PeerClient(computer.address, Http(readTimeoutMs = 150))
        computer.answers["GET /api/peer/state"] = { exchange ->
            Thread.sleep(400)
            FakeComputer.send(exchange, 200, state.toByteArray(), "application/json")
        }
        computer.answers["GET /api/peer/unit"] = { exchange ->
            Thread.sleep(400)
            FakeComputer.send(exchange, 404, "{}".toByteArray(), "application/json")
        }
        assertEquals("Desk", impatient.state("me").name)
        assertFailsWith<SyncError.NoAnswer> { impatient.unit("song/a/b") }
    }

    @Test fun `a unit is its document's unit, of format 3 and of the id asked, and none is null`() {
        val got = mutableListOf<Got>()
        answer("GET /api/peer/unit", 200,
               """{"format":3,"id":"artist_url/宋冬野","digest":"$sha","unit":{"name":"宋冬野","page":"https://x"}}""", got)
        assertEquals(JsonObject(mapOf("name" to JsonPrimitive("宋冬野"), "page" to JsonPrimitive("https://x"))),
                     client.unit("artist_url/宋冬野"))
        assertEquals("id=artist_url%2F%E5%AE%8B%E5%86%AC%E9%87%8E", got.single().query)

        answer("GET /api/peer/unit", 404, """{"error":"no unit here"}""")
        assertNull(client.unit("song/a/b"))
        answer("GET /api/peer/unit", 200, """{"format":2,"id":"song/a/b","digest":"$sha","unit":{}}""")
        assertTrue("can't read" in assertFailsWith<PeerError> { client.unit("song/a/b") }.message!!)
        answer("GET /api/peer/unit", 200, """{"format":3,"id":"song/a/c","digest":"$sha","unit":{}}""")
        assertFailsWith<PeerError> { client.unit("song/a/b") }
    }

    @Test fun `a file is its bytes, checked against the SHA-256 the unit gives`() {
        val bytes = "%PDF-1.7 a sheet".toByteArray()
        val got = mutableListOf<Got>()
        computer.answers["GET /api/peer/file"] = { exchange ->
            got.add(Got(exchange.requestURI.rawQuery, emptyMap(), ByteArray(0)))
            FakeComputer.send(exchange, 200, bytes, "application/octet-stream")
        }
        assertContentEquals(bytes, client.file("soda stereo/de música", "sheet.pdf", Canonical.sha256Hex(bytes)))
        assertEquals("song=soda%20stereo%2Fde%20m%C3%BAsica&name=sheet.pdf", got.single().query)
        val other = assertFailsWith<PeerError> { client.file("a/b", "sheet.pdf", sha) }
        assertTrue("changed since compared" in other.message!!, other.message)
        answer("GET /api/peer/file", 404, """{"error":"no such file kept, or it changed since caracole kept it"}""")
        assertTrue("404" in assertFailsWith<PeerError> { client.file("a/b", "x", sha) }.message!!)
    }

    @Test fun `a push is opened, its files sent and its document posted, each with the form token in its header`() {
        val opened = mutableListOf<Got>()
        val sent = mutableListOf<Got>()
        val posted = mutableListOf<Got>()
        answer("POST /peer/push/new", 200, """{"push":"0123456789abcdef","need":["$sha"]}""", opened)
        answer("POST /peer/push/file", 200, """{"ok":true}""", sent)
        answer("POST /peer/push", 200, """{"job":{"id":7,"kind":"peer-push","state":"queued"}}""", posted)

        assertEquals("0123456789abcdef" to listOf(sha), client.pushNew("tok-1", "a1b2c3d4e5f60718", listOf(sha, sha)))
        val new = opened.single()
        assertEquals("""{"format":3,"from":"a1b2c3d4e5f60718","files":["$sha"]}""", new.body.toString(Charsets.UTF_8))
        assertEquals("application/json", new.headers["content-type"])

        val bytes = ByteArray(1000) { it.toByte() }
        client.pushFile("tok-1", "0123456789abcdef", sha, bytes)
        assertEquals("push=0123456789abcdef&sha256=$sha", sent.single().query)
        assertEquals("application/octet-stream", sent.single().headers["content-type"])
        assertContentEquals(bytes, sent.single().body)

        val doc = JsonObject(mapOf("format" to JsonPrimitive(3), "take" to JsonArray(emptyList())))
        assertEquals(7, client.push("tok-1", "0123456789abcdef", doc))
        assertEquals("push=0123456789abcdef", posted.single().query)
        assertEquals(doc, Canonical.parse(posted.single().body.toString(Charsets.UTF_8)).jsonObject)

        for (got in opened + sent + posted) {
            assertEquals("tok-1", got.headers["x-caracole-form-token"])
            assertEquals("application/json", got.headers["accept"])
            assertNull(got.headers["origin"])
            assertNull(got.headers["sec-fetch-site"])
        }
    }

    @Test fun `a 403 that says reload reads the state again once, and its fresh token goes on being sent`() {
        answer("GET /api/peer/state", 200, state.replace("tok-1", "tok-2"))
        val tokens = CopyOnWriteArrayList<String?>()
        computer.answers["POST /peer/push/new"] = { exchange ->
            val given = exchange.requestHeaders.getFirst("X-Caracole-Form-Token")
            tokens.add(given)
            if (given == "tok-2") FakeComputer.send(exchange, 200, """{"push":"0123456789abcdef","need":[]}""".toByteArray(), "application/json")
            else FakeComputer.send(exchange, 403, """{"error":"older than the server","reload":true}""".toByteArray(), "application/json")
        }
        client.state("a1b2c3d4e5f60718")
        assertEquals("0123456789abcdef" to emptyList(), client.pushNew("tok-1", "a1b2c3d4e5f60718", emptyList()))
        assertEquals(listOf<String?>("tok-1", "tok-2"), tokens.toList())
        assertEquals(listOf("GET /api/peer/state?peer=a1b2c3d4e5f60718", "GET /api/peer/state?peer=a1b2c3d4e5f60718"),
                     computer.requests.filter { it.startsWith("GET") })
        // The token of the page it read before stands for the fresh one from now on.
        client.pushNew("tok-1", "a1b2c3d4e5f60718", emptyList())
        assertEquals(listOf<String?>("tok-1", "tok-2", "tok-2"), tokens.toList())
    }

    @Test fun `a 403 again after the state read again is refused, once, not retried for ever`() {
        answer("GET /api/peer/state", 200, state)
        answer("POST /peer/push", 403, """{"error":"older than the server","reload":true}""")
        val e = assertFailsWith<PeerError> { client.push("tok-1", "0123456789abcdef", JsonObject(emptyMap())) }
        assertEquals(403, e.status)
        assertEquals(2, computer.asked("POST", "/peer/push").size)
        // A 403 that doesn't say reload is refused at once.
        answer("POST /peer/push/file", 403, """{"error":"This came from another site, so caracole refused it."}""")
        assertTrue("another site" in assertFailsWith<PeerError> { client.pushFile("tok-1", "0123456789abcdef", sha, ByteArray(1)) }.message!!)
        assertEquals(1, computer.asked("POST", "/peer/push/file").size)
    }

    @Test fun `a push answered with something else is refused`() {
        answer("POST /peer/push/new", 200, """{"push":"not hex","need":[]}""")
        assertFailsWith<PeerError> { client.pushNew("t", "a1b2c3d4e5f60718", emptyList()) }
        answer("POST /peer/push/new", 200, """{"push":"0123456789abcdef","need":["${"ef".repeat(32)}"]}""")
        assertFailsWith<PeerError> { client.pushNew("t", "a1b2c3d4e5f60718", listOf(sha)) }
        answer("POST /peer/push", 400, """{"error":"song/a/b: given other than its state says."}""")
        assertEquals("${computer.address} answered 400: song/a/b: given other than its state says.",
                     assertFailsWith<PeerError> { client.push("t", "0123456789abcdef", JsonObject(emptyMap())) }.message)
    }

    @Test fun `a job is the computer's request as it is now`() {
        answer("GET /api/jobs/7", 200, """{"id":7,"state":"running","steps":[]}""")
        assertEquals(JsonPrimitive("running"), client.job(7)["state"])
        assertEquals(listOf("GET /api/jobs/7"), computer.requests)
        computer.answers.clear()
        assertTrue("answered 404" in assertFailsWith<PeerError> { client.job(8) }.message!!)
        answer("GET /api/jobs/9", 200, """{"id":9,"state":null}""")
        assertEquals("${computer.address} answered about entry 9 in a form we can't read.",
                     assertFailsWith<PeerError> { client.job(9) }.message)
    }

    @Test fun `the index streams into a file, the sites asked, with a read timeout of its own`() {
        val impatient = PeerClient(computer.address, Http(readTimeoutMs = 150))
        val bytes = ByteArray(3_000_000) { (it % 253).toByte() }
        computer.index = { bytes }
        computer.answers["GET /api/peer/index"] = { exchange ->
            Thread.sleep(400)
            FakeComputer.send(exchange, 200, bytes, "application/vnd.sqlite3")
        }
        val to = tmp.newFile("index.sqlite")
        impatient.index(to, listOf("ug", "lacuerda"))
        assertContentEquals(bytes, to.readBytes())
        assertEquals(listOf("GET /api/peer/index?sites=ug%2Clacuerda"), computer.requests)

        computer.answers.remove("GET /api/peer/index")
        client.index(to)
        assertEquals(listOf<List<String>?>(null), computer.indexAsked)
        answer("GET /api/peer/index", 400, """{"error":"no site named nope"}""")
        assertTrue("no site named nope" in assertFailsWith<PeerError> { client.index(to, listOf("nope")) }.message!!)
    }

    @Test fun `nothing answering is mirror's NoAnswer, as the mirror's sync says it`() {
        val address = computer.address
        computer.close()
        assertFailsWith<SyncError.NoAnswer> { PeerClient(address).state("me") }
    }
}
