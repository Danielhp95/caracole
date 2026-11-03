package io.github.danielhp95.caracole.mirror

import com.sun.net.httpserver.HttpExchange
import org.junit.After
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Http asks caracole serve and nothing else: a GET or a POST, its headers as given, no redirect followed, no
 * cookie kept, and a read timeout a call may set for itself. */
class HttpTest {
    private val server = FakeCaracole()
    private val http = Http(readTimeoutMs = 2_000)

    @After fun stop() = server.close()

    /** What the server got: the method, the headers it was sent (lowercase names) and the body. */
    private class Asked(val method: String, val headers: Map<String, String>, val body: ByteArray)

    private fun recording(status: Int = 200, reply: ByteArray = "{}".toByteArray(), extra: (HttpExchange) -> Unit = {},
                          into: MutableList<Asked>): (HttpExchange) -> Unit = { exchange ->
        val body = exchange.requestBody.readBytes()
        val headers = exchange.requestHeaders.entries.associate { (k, v) -> k.lowercase() to v.joinToString(",") }
        into.add(Asked(exchange.requestMethod, headers, body))
        extra(exchange)
        FakeCaracole.send(exchange, status, reply, "application/json")
    }

    @Test fun `a GET as before still reads the answer and its length`() {
        server.answers["/a"] = { FakeCaracole.send(it, 200, "hello".toByteArray(), "text/plain") }
        val (status, length, text) = http.get(server.address, server.address.resolve("/a")) { answer ->
            Triple(answer.status, answer.contentLength, answer.body.readBytes().toString(Charsets.UTF_8))
        }
        assertEquals(200, status)
        assertEquals(5L, length)
        assertEquals("hello", text)
    }

    @Test fun `a GET sends the headers it is given, beside its own`() {
        val asked = mutableListOf<Asked>()
        server.answers["/b"] = recording(into = asked)
        http.get(server.address, server.address.resolve("/b"), headers = mapOf("Accept" to "application/json")) { }
        val headers = asked.single().headers
        assertEquals("application/json", headers["accept"])
        assertEquals("caracole-android", headers["user-agent"])
        assertEquals("identity", headers["accept-encoding"])
        assertNull(headers["cookie"])
    }

    @Test fun `an answer's headers can be read`() {
        server.answers["/h"] = { exchange ->
            exchange.responseHeaders.add("X-Thing", "yes")
            FakeCaracole.send(exchange, 200, "x".toByteArray(), "text/plain")
        }
        val (thing, type) = http.get(server.address, server.address.resolve("/h")) { it.header("x-thing") to it.header("Content-Type") }
        assertEquals("yes", thing)
        assertEquals("text/plain", type)
    }

    @Test fun `a POST sends its body, its type and its headers, and reads an error's body`() {
        val asked = mutableListOf<Asked>()
        server.answers["/peer/push/new"] = recording(status = 403, reply = """{"error":"no","reload":true}""".toByteArray(),
                                                     into = asked)
        val body = """{"format":2}""".toByteArray()
        val (status, text) = http.post(server.address, server.address.resolve("/peer/push/new"), "application/json",
                                       mapOf("X-Caracole-Form-Token" to "tok", "Accept" to "application/json"), body) {
            it.status to it.body.readBytes().toString(Charsets.UTF_8)
        }
        assertEquals(403, status)
        assertEquals("""{"error":"no","reload":true}""", text)
        val got = asked.single()
        assertEquals("POST", got.method)
        assertContentEquals(body, got.body)
        assertEquals("application/json", got.headers["content-type"])
        assertEquals("tok", got.headers["x-caracole-form-token"])
        assertEquals("application/json", got.headers["accept"])
        assertEquals(body.size.toString(), got.headers["content-length"])
        // A non-browser: no Origin and no Sec-Fetch-Site, so caracole serve's cross-origin check lets it through.
        assertNull(got.headers["origin"])
        assertNull(got.headers["sec-fetch-site"])
    }

    @Test fun `a POST may write its body as it goes`() {
        val asked = mutableListOf<Asked>()
        server.answers["/peer/push/file"] = recording(into = asked)
        val bytes = ByteArray(300_000) { (it % 251).toByte() }
        http.post(server.address, server.address.resolve("/peer/push/file"), "application/octet-stream", emptyMap(),
                  bytes.size.toLong(), { out -> bytes.inputStream().copyTo(out, 4096) }) { it.status }
        assertContentEquals(bytes, asked.single().body)
        assertEquals("application/octet-stream", asked.single().headers["content-type"])
    }

    @Test fun `a redirect is an answer, never followed, a GET's or a POST's`() {
        server.answers["/moved"] = { exchange ->
            exchange.responseHeaders.add("Location", "http://example.invalid/elsewhere")
            FakeCaracole.send(exchange, 303, ByteArray(0), "text/plain")
        }
        assertEquals(303, http.get(server.address, server.address.resolve("/moved")) { it.status })
        assertEquals(303, http.post(server.address, server.address.resolve("/moved"), "application/json", emptyMap(),
                                    "{}".toByteArray()) { it.status })
        assertEquals(listOf("/moved", "/moved"), server.requests)
    }

    @Test fun `a cookie the server sets is never sent back`() {
        val asked = mutableListOf<Asked>()
        server.answers["/c"] = recording(into = asked, extra = { it.responseHeaders.add("Set-Cookie", "a=b; Path=/") })
        repeat(2) { http.get(server.address, server.address.resolve("/c")) { } }
        assertTrue(asked.all { it.headers["cookie"] == null })
    }

    @Test fun `a call's own read timeout is kept, longer or shorter than the client's`() {
        val release = CountDownLatch(1)
        server.answers["/slow"] = { exchange ->
            release.await(5, TimeUnit.SECONDS)
            FakeCaracole.send(exchange, 200, "late".toByteArray(), "text/plain")
        }
        try {
            val e = assertFailsWith<SyncError.NoAnswer> {
                http.get(server.address, server.address.resolve("/slow"), readTimeoutMs = 200) { }
            }
            assertTrue("took too long" in e.message!!, e.message)
        } finally {
            release.countDown()
        }

        val later = CountDownLatch(1)
        server.answers["/slower"] = { exchange ->
            later.await(800, TimeUnit.MILLISECONDS)
            FakeCaracole.send(exchange, 200, "late".toByteArray(), "text/plain")
        }
        val quick = Http(readTimeoutMs = 100)
        // No read timeout at all (0): it waits for as long as the answer takes.
        assertEquals("late", quick.get(server.address, server.address.resolve("/slower"), readTimeoutMs = 0) {
            it.body.readBytes().toString(Charsets.UTF_8)
        })
    }

    @Test fun `nothing listening is NoAnswer, for a POST too`() {
        val port = java.net.ServerSocket(0, 1, java.net.InetAddress.getLoopbackAddress()).use { it.localPort }
        val address = ServerAddress.parse("127.0.0.1:$port")
        assertFailsWith<SyncError.NoAnswer> {
            http.post(address, address.resolve("/peer/push"), "application/json", emptyMap(), "{}".toByteArray()) { }
        }
    }

    @Test fun `a body the server stops reading breaks as NoAnswer, never as another error`() {
        server.answers["/cut"] = { exchange -> FakeCaracole.send(exchange, 413, "too long".toByteArray(), "text/plain") }
        val result = runCatching {
            http.post(server.address, server.address.resolve("/cut"), "application/octet-stream", emptyMap(),
                      64L * 1024 * 1024, { out ->
                          val chunk = ByteArray(1 shl 16)
                          repeat(1024) { out.write(chunk) }
                      }) { it.status }
        }
        // Either the server's answer came first, or the connection broke as it stopped reading.
        val e = result.exceptionOrNull()
        assertTrue(result.getOrNull() == 413 || e is SyncError.NoAnswer, "$result")
    }
}
