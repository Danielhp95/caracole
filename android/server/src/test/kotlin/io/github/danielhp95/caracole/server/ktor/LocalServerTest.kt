package io.github.danielhp95.caracole.server.ktor

import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.PostAnswer
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.testing.TestApp
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.ConnectException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

/** The phone's server on a real socket: Ktor CIO at 127.0.0.1 alone, every request handed whole to the App. */
class LocalServerTest {
    @get:Rule val tmp = TemporaryFolder()

    /** A route that says what it was asked: the target as the App got it, the headers, the body. */
    private val echo = object : RouteModule {
        override val routes = listOf(
            Route("GET", "/echo/", "what it was asked", under = true, get = GetAnswer { request ->
                val said = "target=${request.target}\nhost=${request.headers["host"]}\nx-a=${request.headers["x-a"]}\n" +
                    "cookie=${request.headers["cookie"]}\n"
                Response(200, Body.Bytes(said.toByteArray()), mutableListOf("Content-Type" to "text/plain; charset=utf-8"))
            }),
            Route("POST", "/echo/form", "a form", post = PostAnswer { _, form ->
                Response(200, Body.Bytes(form.toString().toByteArray()), mutableListOf("Content-Type" to "text/plain; charset=utf-8"))
            }),
            Route("POST", "/echo/big", "a long body", limit = 100_000, post = PostAnswer { _, form ->
                Response(200, Body.Bytes("${form["pad"]?.length}".toByteArray()), mutableListOf("Content-Type" to "text/plain"))
            }),
            Route("GET", "/file", "a file streamed", get = GetAnswer {
                val file = File(tmp.root, "big.bin")
                Response(200, Body.FromFile(file, file.length()), mutableListOf("Content-Type" to "application/octet-stream"))
            }),
            Route("GET", "/bug", "a bug", get = GetAnswer { error("a bug") }),
        )
    }

    private class Answer(val status: Int, val headers: List<Pair<String, String>>, val body: ByteArray) {
        val text get() = body.toString(Charsets.UTF_8)
        fun header(name: String) = headers.firstOrNull { it.first.equals(name, ignoreCase = true) }?.second
    }

    /** One request as raw bytes over a socket, and the answer as it came (Connection: close). */
    private fun raw(port: Int, request: ByteArray, host: String = "127.0.0.1"): Answer =
        Socket(InetAddress.getByName(host), port).use { socket ->
            socket.soTimeout = 10_000
            socket.getOutputStream().apply { write(request); flush() }
            val out = ByteArrayOutputStream()
            socket.getInputStream().copyTo(out)
            val bytes = out.toByteArray()
            val end = (0 until bytes.size - 3).first { bytes[it] == '\r'.code.toByte() && bytes[it + 1] == '\n'.code.toByte() &&
                                                    bytes[it + 2] == '\r'.code.toByte() && bytes[it + 3] == '\n'.code.toByte() }
            val head = bytes.copyOfRange(0, end).toString(Charsets.ISO_8859_1).split("\r\n")
            val headers = head.drop(1).map { it.substringBefore(':') to it.substringAfter(':').trim() }
            var body = bytes.copyOfRange(end + 4, bytes.size)
            if (headers.any { it.first.equals("Transfer-Encoding", true) && it.second.equals("chunked", true) }) {
                body = dechunk(body)
            }
            Answer(head[0].split(' ')[1].toInt(), headers, body)
        }

    private fun dechunk(data: ByteArray): ByteArray {
        val out = ByteArrayOutputStream()
        var at = 0
        while (true) {
            val line = (at until data.size).first { data[it] == '\r'.code.toByte() }
            val size = data.copyOfRange(at, line).toString(Charsets.ISO_8859_1).substringBefore(';').trim().toInt(16)
            if (size == 0) return out.toByteArray()
            out.write(data, line + 2, size)
            at = line + 2 + size + 2
        }
    }

    private fun get(port: Int, target: String, vararg headers: String, cookie: String? = null,
                    host: String = "127.0.0.1:$port"): Answer {
        val lines = listOf("GET $target HTTP/1.1", "Host: $host") + headers +
            listOfNotNull(cookie?.let { "Cookie: $it" }) + "Connection: close"
        return raw(port, (lines.joinToString("\r\n") + "\r\n\r\n").toByteArray(Charsets.ISO_8859_1))
    }

    private fun post(port: Int, target: String, body: String, cookie: String): Answer {
        val bytes = body.toByteArray()
        val head = "POST $target HTTP/1.1\r\nHost: 127.0.0.1:$port\r\nCookie: $cookie\r\n" +
            "Content-Type: application/x-www-form-urlencoded\r\nOrigin: http://127.0.0.1:$port\r\n" +
            "Content-Length: ${bytes.size}\r\nConnection: close\r\n\r\n"
        return raw(port, head.toByteArray() + bytes)
    }

    private fun server(test: TestApp, preferred: Int = 0): Pair<LocalServer, Int> {
        val server = LocalServer(test.app)
        return server to server.start(preferred)
    }

    @Test fun noCookieIsRefusedAndTheCookieReachesTheRoute() {
        TestApp(tmp.root, { listOf(echo) }).use { test ->
            val (server, port) = server(test)
            server.use {
                assertEquals("http://127.0.0.1:$port", server.origin)
                val none = get(port, "/echo/x")
                assertEquals(403, none.status)
                assertEquals("Not this app's caracole.\n", none.text)
                assertEquals("nosniff", none.header("X-Content-Type-Options"))
                assertEquals(403, get(port, "/echo/x", cookie = "caracole-launch=wrong").status)
                val cookie = "theme=dark; caracole-launch=${test.secret}"
                val answer = get(port, "/echo/x", "X-A: one", cookie = cookie)
                assertEquals(200, answer.status, answer.text)
                assertEquals("target=/echo/x\nhost=127.0.0.1:$port\nx-a=one\ncookie=$cookie\n", answer.text)
                assertEquals("text/plain; charset=utf-8", answer.header("Content-Type"))
                assertEquals("DENY", answer.header("X-Frame-Options"))
                assertEquals("no-store", answer.header("Cache-Control"))
                assertEquals("frame-ancestors 'none'", answer.header("Content-Security-Policy"))
            }
        }
    }

    @Test fun theTargetReachesTheAppAsSentWithItsEscapes() {
        TestApp(tmp.root, { listOf(echo) }).use { test ->
            val (server, port) = server(test)
            server.use {
                val cookie = "caracole-launch=${test.secret}"
                val target = "/echo/Estopa/Tu%20calorro/a%2Fb%3F.html?q=caf%C3%A9&a=1"
                assertEquals("target=$target", get(port, target, cookie = cookie).text.lines().first())
                assertEquals("target=/echo/a%2F%2E%2E%2Fb", get(port, "/echo/a%2F%2E%2E%2Fb", cookie = cookie).text.lines().first())
                assertEquals(400, get(port, "/echo/%ff", cookie = cookie).status, "the App unquotes it strictly")
                assertEquals(421, get(port, "/echo/x", cookie = cookie, host = "evil.example").status)
                assertEquals(400, get(port, "/echo/x", "Host: evil.example", cookie = cookie).status, "Ktor's: two Hosts")
            }
        }
    }

    @Test fun aFormIsReadUpToItsRoutesLimit() {
        TestApp(tmp.root, { listOf(echo) }).use { test ->
            val (server, port) = server(test)
            server.use {
                val cookie = "caracole-launch=${test.secret}"
                val answer = post(port, "/echo/form", "csrf=${test.csrf}&a=caf%C3%A9+x", cookie)
                assertEquals(200, answer.status, answer.text)
                assertEquals("{csrf=${test.csrf}, a=café x}", answer.text)
                assertEquals(403, post(port, "/echo/form", "csrf=old", cookie).status)
                val pad = "x".repeat(50_000)
                assertEquals("50000", post(port, "/echo/big", "csrf=${test.csrf}&pad=$pad", cookie).text)
                assertEquals(413, post(port, "/echo/form", "csrf=${test.csrf}&pad=$pad", cookie).status)
            }
        }
    }

    /** Everything the server sends on one connection kept alive, until it closes it or goes quiet for [quiet] ms. */
    private fun conversation(port: Int, vararg sent: ByteArray, quiet: Int = 3_000): Pair<String, Boolean> =
        Socket(InetAddress.getByName("127.0.0.1"), port).use { socket ->
            socket.soTimeout = quiet
            val output = socket.getOutputStream()
            try {
                for (part in sent) output.write(part)
                output.flush()
            } catch (e: SocketException) {
                // the server may close before taking it all: what it answered is still there to read
            }
            val out = ByteArrayOutputStream()
            val buffer = ByteArray(8192)
            val closed = try {
                while (true) {
                    val n = socket.getInputStream().read(buffer)
                    if (n < 0) break
                    out.write(buffer, 0, n)
                }
                true
            } catch (e: java.net.SocketTimeoutException) {
                false
            } catch (e: SocketException) {
                true // reset: the server closed with the rest of the body unread
            }
            out.toByteArray().toString(Charsets.ISO_8859_1) to closed
        }

    @Test fun nothingInTheRestOfAFormTooLongIsReadAsARequest() {
        TestApp(tmp.root, { listOf(echo) }).use { test ->
            val (server, port) = server(test)
            server.use {
                val cookie = "caracole-launch=${test.secret}"
                val smuggled = "GET /echo/smuggled HTTP/1.1\r\nHost: 127.0.0.1:$port\r\nCookie: $cookie\r\n\r\n"
                val body = ("csrf=${test.csrf}&pad=" + "x".repeat(40_000) + "\r\n\r\n" + smuggled).toByteArray()
                val head = "POST /echo/form HTTP/1.1\r\nHost: 127.0.0.1:$port\r\nCookie: $cookie\r\n" +
                    "Content-Type: application/x-www-form-urlencoded\r\nOrigin: http://127.0.0.1:$port\r\n" +
                    "Content-Length: ${body.size}\r\n\r\n"
                val next = "GET /echo/next HTTP/1.1\r\nHost: 127.0.0.1:$port\r\nCookie: $cookie\r\nConnection: close\r\n\r\n"
                val (said, _) = conversation(port, head.toByteArray(), body, next.toByteArray())
                assertTrue(said.startsWith("HTTP/1.1 413 "), said.take(200))
                assertTrue("smuggled" !in said, "the rest of the body is dropped, never read as a request")
                // the request after the body is the next one answered, on the same connection
                assertEquals(2, Regex("^HTTP/1\\.1 ", RegexOption.MULTILINE).findAll(said).count(), said.takeLast(400))
                assertTrue("\r\n\r\ntarget=/echo/next\n" in said, said.takeLast(400))
                // a form within its limit keeps the connection for the next request too
                val small = "csrf=${test.csrf}&a=1".toByteArray()
                val first = "POST /echo/form HTTP/1.1\r\nHost: 127.0.0.1:$port\r\nCookie: $cookie\r\n" +
                    "Content-Type: application/x-www-form-urlencoded\r\nOrigin: http://127.0.0.1:$port\r\n" +
                    "Content-Length: ${small.size}\r\n\r\n"
                val last = "GET /echo/next HTTP/1.1\r\nHost: 127.0.0.1:$port\r\nCookie: $cookie\r\nConnection: close\r\n\r\n"
                val (both, _) = conversation(port, first.toByteArray() + small, last.toByteArray())
                assertTrue(both.startsWith("HTTP/1.1 200 "), both.take(200))
                assertTrue("target=/echo/next" in both, both)
                assertTrue("Connection: close" !in both.substringBefore("\r\n\r\n"), both.substringBefore("\r\n\r\n"))
            }
        }
    }

    @Test fun aFileIsStreamedAndAHeadHasNoBody() {
        val big = ByteArray(3_000_000) { (it % 251).toByte() }
        File(tmp.root, "big.bin").writeBytes(big)
        TestApp(tmp.newFolder(), { listOf(echo) }).use { test ->
            val (server, port) = server(test)
            server.use {
                val cookie = "caracole-launch=${test.secret}"
                val file = get(port, "/file", cookie = cookie)
                assertEquals(200, file.status)
                assertTrue(big.contentEquals(file.body), "${file.body.size} bytes")
                assertEquals("application/octet-stream", file.header("Content-Type"))
                val lines = "HEAD /echo/x HTTP/1.1\r\nHost: 127.0.0.1:$port\r\nCookie: $cookie\r\nConnection: close\r\n\r\n"
                val head = raw(port, lines.toByteArray())
                assertEquals(200, head.status)
                assertEquals(0, head.body.size)
                assertEquals("${get(port, "/echo/x", cookie = cookie).body.size}", head.header("Content-Length"))
                val bug = get(port, "/bug", cookie = cookie)
                assertEquals(500, bug.status)
                assertEquals("caracole hit a bug; its log says where.\n", bug.text)
                assertEquals("DENY", bug.header("X-Frame-Options"))
            }
        }
    }

    @Test fun itListensOn127001Alone() {
        TestApp(tmp.root, { listOf(echo) }).use { test ->
            val (server, port) = server(test)
            server.use {
                assertEquals(403, get(port, "/echo/x").status)
                // Linux routes all of 127.0.0.0/8 to the loopback: a socket bound to 0.0.0.0 would answer there too.
                assertFailsWith<ConnectException> { Socket().use { it.connect(InetSocketAddress("127.0.0.2", port), 2_000) } }
                assertFailsWith<SocketException> { Socket().use { it.connect(InetSocketAddress("::1", port), 2_000) } }
            }
        }
    }

    @Test fun itTakesThePreferredPortElseAnyFreeOne() {
        TestApp(tmp.root, { listOf(echo) }).use { test ->
            val taken = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"))
            taken.use {
                val (server, port) = server(test, preferred = taken.localPort)
                server.use {
                    assertNotEquals(taken.localPort, port)
                    assertEquals(403, get(port, "/echo/x").status)
                }
            }
            val free = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1")).use { it.localPort }
            val (again, port) = server(test, preferred = free)
            again.use { assertEquals(free, port) }
        }
    }
}
