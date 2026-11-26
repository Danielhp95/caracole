package io.github.danielhp95.caracole.core.youtube

import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.net.ConnectException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.util.Base64
import java.util.Collections
import kotlin.concurrent.thread
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue
import kotlin.test.fail

/**
 * HostGate on the JVM, every upstream a ServerSocket on 127.0.0.1 and every name resolved by a resolver of the
 * test's own (to loopback, or one that fails the test if it is asked at all): no test reaches a real host.
 */
class HostGateTest {
    private val gates = mutableListOf<HostGate>()
    private val servers = mutableListOf<ServerSocket>()

    @AfterTest
    fun closeAll() {
        gates.forEach { it.close() }
        servers.forEach { it.close() }
    }

    private val loopback: InetAddress = InetAddress.getByAddress(byteArrayOf(127, 0, 0, 1))

    /** The names a resolver was asked, and every one sent to [port] on loopback. */
    private class ToLoopback(val port: Int) : HostGate.Resolver {
        val asked: MutableList<String> = Collections.synchronizedList(mutableListOf())
        override fun resolve(host: String, port: Int): List<InetSocketAddress> {
            asked += "$host:$port"
            return listOf(InetSocketAddress(InetAddress.getByAddress(byteArrayOf(127, 0, 0, 1)), this.port))
        }
    }

    private val never = HostGate.Resolver { host, port -> fail("the gate looked up $host:$port") }

    private fun gate(
        mode: HostGate.Mode,
        rule: HostGate.HostRule,
        resolver: HostGate.Resolver = never,
        maxConnections: Int = HostGate.MAX_CONNECTIONS,
        idleTimeoutMs: Int = HostGate.IDLE_TIMEOUT_MS,
        headTimeoutMs: Int = HostGate.HEAD_TIMEOUT_MS,
    ): Pair<HostGate, HostGate.Opened> {
        val gate = HostGate(mode, rule, resolver, maxConnections, HostGate.CONNECT_TIMEOUT_MS, idleTimeoutMs, headTimeoutMs)
        gates += gate
        return gate to gate.start()
    }

    /** The user and the secret proxyArg names. */
    private fun credentials(opened: HostGate.Opened): Pair<String, String> {
        val m = Regex("""^http://([0-9a-f]{32}):([0-9a-f]{32})@127\.0\.0\.1:(\d+)$""").find(opened.proxyArg)
            ?: fail("proxyArg ${opened.proxyArg}")
        assertEquals(opened.port, m.groupValues[3].toInt())
        return m.groupValues[1] to m.groupValues[2]
    }

    private fun basic(user: String, secret: String) =
        "Basic " + Base64.getEncoder().encodeToString("$user:$secret".toByteArray())

    private fun auth(opened: HostGate.Opened): String = credentials(opened).let { basic(it.first, it.second) }

    /** An upstream that reads [expectUp] bytes, answers [down], then closes; what it read is [got]. */
    private class Upstream(val server: ServerSocket, expectUp: Int, down: ByteArray) {
        @Volatile var got: ByteArray = ByteArray(0)
        val port get() = server.localPort
        val done = thread(isDaemon = true) {
            server.accept().use { s ->
                got = s.getInputStream().readNBytes(expectUp)
                s.getOutputStream().write(down)
                s.getOutputStream().flush()
            }
        }
    }

    private fun upstream(expectUp: Int, down: ByteArray): Upstream {
        val server = ServerSocket(0, 50, loopback)
        servers += server
        return Upstream(server, expectUp, down)
    }

    private fun connect(opened: HostGate.Opened): Socket =
        Socket(loopback, opened.port).also { it.soTimeout = 10_000 }

    /** The answer's head, read to its blank line. */
    private fun head(input: InputStream): String {
        val out = ByteArrayOutputStream()
        while (true) {
            val b = input.read()
            if (b < 0) break
            out.write(b)
            val s = out.toString(Charsets.ISO_8859_1)
            if (s.endsWith("\r\n\r\n")) break
        }
        return out.toString(Charsets.ISO_8859_1)
    }

    private fun ask(opened: HostGate.Opened, request: String): String =
        connect(opened).use { s ->
            s.getOutputStream().write(request.toByteArray(Charsets.ISO_8859_1))
            head(s.getInputStream())
        }

    private fun connectLine(target: String, authorization: String?) =
        "CONNECT $target HTTP/1.1\r\nHost: $target\r\n" +
            (if (authorization != null) "Proxy-Authorization: $authorization\r\n" else "") + "\r\n"

    private fun status(head: String): Int = head.substringAfter(' ').substringBefore(' ').toInt()

    private fun eventually(what: String, check: () -> Boolean) {
        val until = System.nanoTime() + 5_000_000_000L
        while (!check()) {
            if (System.nanoTime() > until) fail(what)
            Thread.sleep(10)
        }
    }

    private fun bytes(n: Int, seed: Int) = ByteArray(n) { ((it * 31 + seed) and 0xff).toByte() }

    @Test
    fun anAllowedConnectIsTunnelledBothWaysAndTheBytesCountedAreThoseSent() {
        val up = bytes(1000, 1)
        val down = bytes(23_456, 7)
        val server = upstream(up.size, down)
        val (gate, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
        connect(opened).use { s ->
            s.getOutputStream().write(connectLine("127.0.0.1:${server.port}", auth(opened)).toByteArray())
            assertEquals("HTTP/1.1 200 Connection established\r\n\r\n", head(s.getInputStream()))
            s.getOutputStream().write(up)
            assertTrue(down.contentEquals(s.getInputStream().readAllBytes()))
        }
        server.done.join(5_000)
        assertTrue(up.contentEquals(server.got))
        eventually("the bytes counted: ${gate.log()}") {
            gate.log()["127.0.0.1"] == HostGate.HostUse(connects = 1, bytesUp = 1000, bytesDown = 23_456, refused = 0)
        }
        assertFalse(gate.refusedAny())
    }

    @Test
    fun bytesTheClientSendsRightAfterItsConnectAreTunnelledToo() {
        val up = bytes(300, 3)
        val server = upstream(up.size, "ok".toByteArray())
        val (gate, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
        connect(opened).use { s ->
            s.getOutputStream().write(connectLine("127.0.0.1:${server.port}", auth(opened)).toByteArray() + up)
            assertEquals(200, status(head(s.getInputStream())))
            assertEquals("ok", s.getInputStream().readAllBytes().toString(Charsets.US_ASCII))
        }
        server.done.join(5_000)
        assertTrue(up.contentEquals(server.got))
        eventually("counted ${gate.log()}") { gate.log()["127.0.0.1"]?.bytesUp == 300L }
    }

    @Test
    fun aGoogleVideoHostIsAllowedOn443AndRefusedOn80() {
        val server = upstream(5, "world".toByteArray())
        val resolver = ToLoopback(server.port)
        val (gate, opened) = gate(HostGate.Mode.NETWORK, HostGate.HostRule.YOUTUBE, resolver)
        assertEquals(403, status(ask(opened, connectLine("rr3---sn-abc.googlevideo.com:80", auth(opened)))))
        assertEquals(emptyList(), resolver.asked.toList(), "a refused host is never looked up")
        connect(opened).use { s ->
            s.getOutputStream().write(connectLine("rr3---sn-abc.googlevideo.com:443", auth(opened)).toByteArray())
            assertEquals(200, status(head(s.getInputStream())))
            s.getOutputStream().write("hello".toByteArray())
            assertEquals("world", s.getInputStream().readAllBytes().toString(Charsets.US_ASCII))
        }
        assertEquals(listOf("rr3---sn-abc.googlevideo.com:443"), resolver.asked.toList())
        eventually("logged ${gate.log()}") {
            gate.log()["rr3---sn-abc.googlevideo.com"] ==
                HostGate.HostUse(connects = 1, bytesUp = 5, bytesDown = 5, refused = 1)
        }
        assertTrue(gate.refusedAny())
    }

    @Test
    fun aNameIsMatchedAsAsciiWhateverItsCaseAndATrailingDotAndLoggedLowercased() {
        val server = upstream(0, ByteArray(0))
        val (gate, opened) = gate(HostGate.Mode.NETWORK, HostGate.HostRule.YOUTUBE, ToLoopback(server.port))
        connect(opened).use { s ->
            s.getOutputStream().write(connectLine("WWW.YouTube.COM.:443", auth(opened)).toByteArray())
            assertEquals(200, status(head(s.getInputStream())))
        }
        eventually("logged ${gate.log()}") { gate.log()["www.youtube.com"]?.connects == 1 }
        assertEquals(setOf("www.youtube.com"), gate.log().keys)
    }

    @Test
    fun everyHostOfTheYouTubeRuleIsAllowedAndConsentAndTheRedirectorAreReportedApart() {
        val rule = HostGate.HostRule.YOUTUBE
        for (host in listOf("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
                            "consent.youtube.com", "redirector.googlevideo.com", "rr1---sn-x.googlevideo.com")) {
            assertTrue(rule.allows(host, 443, connect = true), host)
            assertFalse(rule.allows(host, 80, connect = true), "$host:80")
            assertFalse(rule.allows(host, 443, connect = false), "a plain GET of $host")
        }
        for (host in listOf("googlevideo.com", "youtube.com.evil.example", "evilyoutube.com", "xgooglevideo.com",
                            "i.ytimg.com", "youtubei.googleapis.com", "accounts.google.com")) {
            assertFalse(rule.allows(host, 443, connect = true), host)
        }
        assertEquals(setOf("consent.youtube.com", "redirector.googlevideo.com"),
                     listOf("consent.youtube.com", "redirector.googlevideo.com", "www.youtube.com",
                            "rr1---sn-x.googlevideo.com").filter { rule.reportsApart(it) }.toSet())

        val server = upstream(0, ByteArray(0))
        val (gate, opened) = gate(HostGate.Mode.NETWORK, rule, ToLoopback(server.port))
        connect(opened).use { s ->
            s.getOutputStream().write(connectLine("consent.youtube.com:443", auth(opened)).toByteArray())
            assertEquals(200, status(head(s.getInputStream())))
        }
        eventually("logged ${gate.log()}") {
            gate.log()["consent.youtube.com"] == HostGate.HostUse(connects = 1, apart = true)
        }
    }

    @Test
    fun aHostOffTheRuleGets403AndIsLoggedRefused() {
        val resolver = ToLoopback(1)
        val (gate, opened) = gate(HostGate.Mode.NETWORK, HostGate.HostRule.YOUTUBE, resolver)
        val answer = ask(opened, connectLine("example.com:443", auth(opened)))
        assertEquals(403, status(answer))
        assertEquals(HostGate.HostUse(refused = 1), gate.log()["example.com"])
        assertTrue(gate.refusedAny())
        assertEquals(emptyList(), resolver.asked.toList())
    }

    @Test
    fun anIpLiteralNeverMatchesANameRule() {
        val (gate, opened) = gate(HostGate.Mode.NETWORK, HostGate.HostRule.YOUTUBE)
        assertEquals(403, status(ask(opened, connectLine("142.250.1.1:443", auth(opened)))))
        assertEquals(403, status(ask(opened, connectLine("[2607:f8b0:4004::200e]:443", auth(opened)))))
        assertEquals(setOf("142.250.1.1", "[2607:f8b0:4004::200e]"), gate.log().keys)
        assertTrue(gate.log().values.all { it.refused == 1 })
    }

    @Test
    fun jnnPaIsRefusedByNameUnderObserveAndYouTubeAlike() {
        for (rule in listOf(HostGate.HostRule.OBSERVE, HostGate.HostRule.YOUTUBE)) {
            val resolver = ToLoopback(1)
            val (gate, opened) = gate(HostGate.Mode.NETWORK, rule, resolver)
            assertEquals(403, status(ask(opened, connectLine("jnn-pa.googleapis.com:443", auth(opened)))))
            assertEquals(403, status(ask(opened, connectLine("JNN-PA.googleapis.com.:443", auth(opened)))))
            assertEquals(HostGate.HostUse(refused = 2), gate.log()["jnn-pa.googleapis.com"])
            assertEquals(emptyList(), resolver.asked.toList())
        }
    }

    @Test
    fun observeAllowsAnyOtherHostAndLogsIt() {
        val server = upstream(0, "x".toByteArray())
        val (gate, opened) = gate(HostGate.Mode.NETWORK, HostGate.HostRule.OBSERVE, ToLoopback(server.port))
        connect(opened).use { s ->
            s.getOutputStream().write(connectLine("youtubei.googleapis.com:8443", auth(opened)).toByteArray())
            assertEquals(200, status(head(s.getInputStream())))
            assertEquals("x", s.getInputStream().readAllBytes().toString(Charsets.US_ASCII))
        }
        eventually("logged ${gate.log()}") {
            gate.log()["youtubei.googleapis.com"] == HostGate.HostUse(connects = 1, bytesDown = 1)
        }
        assertFalse(gate.refusedAny())
    }

    @Test
    fun aWrongOrMissingCredentialGets407AndNothingIsLogged() {
        val (gate, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
        val (user, secret) = credentials(opened)
        val wrong = listOf(
            null,
            basic(user, secret.reversed()),
            basic(user.reversed(), secret),
            basic(user, secret + "0"),
            "Bearer $secret",
            "Basic not-base64!",
        )
        for (authorization in wrong) {
            val answer = ask(opened, connectLine("127.0.0.1:9", authorization))
            assertEquals(407, status(answer), "$authorization")
            assertTrue("\r\nProxy-Authenticate: Basic realm=\"caracole\"\r\n" in answer, answer)
        }
        assertEquals(emptyMap(), gate.log())
        assertFalse(gate.refusedAny())
        // The scheme is read without case, as RFC 7235 says.
        val server = upstream(0, ByteArray(0))
        val lower = "basic " + Base64.getEncoder().encodeToString("$user:$secret".toByteArray())
        assertEquals(200, status(ask(opened, connectLine("127.0.0.1:${server.port}", lower))))
    }

    @Test
    fun eachStartMakesAFreshUserAndSecretAndNoneOfThemIsEverWrittenOut() {
        val (gate1, opened1) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
        val (gate2, opened2) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
        val (user1, secret1) = credentials(opened1)
        val (user2, secret2) = credentials(opened2)
        assertNotEquals(user1, user2)
        assertNotEquals(secret1, secret2)
        assertNotEquals(user1, secret1)
        ask(opened1, connectLine("example.com:443", null))
        ask(opened1, connectLine("example.com:443", auth(opened1)))
        val again = assertFailsWith<IllegalStateException> { gate1.start() }
        val written = listOf(gate1.toString(), opened1.toString(), gate1.log().toString(), again.message ?: "",
                             gate2.toString(), opened2.toString())
        for (text in written) {
            for (secret in listOf(secret1, secret2, user1, user2)) assertFalse(secret in text, text)
        }
    }

    @Test
    fun loopbackRefusesAPublicHostWhateverTheRuleBeforeAnyLookup() {
        for (rule in listOf(HostGate.HostRule.YOUTUBE, HostGate.HostRule.OBSERVE)) {
            val (gate, opened) = gate(HostGate.Mode.LOOPBACK, rule, never)
            for (target in listOf("www.youtube.com:443", "rr3---sn-abc.googlevideo.com:443", "localhost:80",
                                  "example.com:80", "[::1]:80", "10.0.2.3:80", "8.8.8.8:53")) {
                assertEquals(403, status(ask(opened, connectLine(target, auth(opened)))), target)
            }
            assertEquals(7, gate.log().values.sumOf { it.refused })
            assertEquals(403, status(ask(opened, "GET http://www.youtube.com/ HTTP/1.1\r\nHost: www.youtube.com\r\n" +
                "Proxy-Authorization: ${auth(opened)}\r\n\r\n")))
        }
    }

    @Test
    fun malformedTargetsGet400() {
        val (gate, opened) = gate(HostGate.Mode.NETWORK, HostGate.HostRule.OBSERVE, never)
        val targets = listOf("user@www.youtube.com:443", "www.youtube.com", "www.youtube.com:", "www.youtube.com:0",
                             "www.youtube.com:65536", "www.youtube.com:44x", "www.you\u0001tube.com:443",
                             "www..youtube.com:443", ".youtube.com:443", "www.youtübe.com:443", "[zz::1]:443",
                             "[::1:443", "[1::2::3]:443", "1.2.3:443", "256.1.1.1:443", ":443")
        for (target in targets) {
            assertEquals(400, status(ask(opened, connectLine(target, auth(opened)))), target)
        }
        assertEquals(400, status(ask(opened, "CONNECT a b HTTP/1.1\r\nProxy-Authorization: ${auth(opened)}\r\n\r\n")))
        assertEquals(400, status(ask(opened, "garbage\r\n\r\n")))
        assertEquals(setOf("(malformed)"), gate.log().keys)
        assertTrue(gate.refusedAny())
    }

    @Test
    fun aPlainGetIsRelayedWithoutTheProxysHeadersInLoopback() {
        val server = ServerSocket(0, 50, loopback).also { servers += it }
        var asked = ""
        val upstream = thread(isDaemon = true) {
            server.accept().use { s ->
                asked = head(s.getInputStream())
                s.getOutputStream().write(("HTTP/1.1 200 OK\r\nContent-Type: audio/mp4\r\nContent-Length: 5\r\n" +
                    "Connection: keep-alive\r\nKeep-Alive: timeout=5\r\n\r\nhello").toByteArray())
            }
        }
        val (gate, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
        val request = "GET http://127.0.0.1:${server.localPort}/clip.m4a?x=1 HTTP/1.1\r\n" +
            "Host: 127.0.0.1:${server.localPort}\r\nUser-Agent: test\r\nProxy-Authorization: ${auth(opened)}\r\n" +
            "Proxy-Connection: keep-alive\r\nConnection: keep-alive\r\n\r\n"
        val answer = connect(opened).use { s ->
            s.getOutputStream().write(request.toByteArray())
            s.getInputStream().readAllBytes().toString(Charsets.ISO_8859_1)
        }
        upstream.join(5_000)
        assertEquals("GET /clip.m4a?x=1 HTTP/1.1\r\nHost: 127.0.0.1:${server.localPort}\r\nUser-Agent: test\r\n" +
                     "Connection: close\r\n\r\n", asked)
        assertEquals("HTTP/1.1 200 OK\r\nContent-Type: audio/mp4\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello",
                     answer)
        eventually("logged ${gate.log()}") {
            gate.log()["127.0.0.1"] == HostGate.HostUse(connects = 1, bytesUp = asked.length.toLong(),
                                                         bytesDown = answer.length.toLong())
        }
    }

    @Test
    fun aPlainGetIsRefusedUnderTheYouTubeRule() {
        val (gate, opened) = gate(HostGate.Mode.NETWORK, HostGate.HostRule.YOUTUBE)
        val answer = ask(opened, "GET http://www.youtube.com/watch?v=x HTTP/1.1\r\nHost: www.youtube.com\r\n" +
            "Proxy-Authorization: ${auth(opened)}\r\n\r\n")
        assertEquals(403, status(answer))
        assertEquals(HostGate.HostUse(refused = 1), gate.log()["www.youtube.com"])
        assertEquals(405, status(ask(opened, "POST http://www.youtube.com/ HTTP/1.1\r\n" +
            "Proxy-Authorization: ${auth(opened)}\r\n\r\n")))
        assertEquals(400, status(ask(opened, "GET https://www.youtube.com/ HTTP/1.1\r\n" +
            "Proxy-Authorization: ${auth(opened)}\r\n\r\n")))
    }

    @Test
    fun anUpstreamThatRefusesIs502AndNoConnect() {
        val closed = ServerSocket(0, 50, loopback)
        val port = closed.localPort
        closed.close()
        val (gate, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
        assertEquals(502, status(ask(opened, connectLine("127.0.0.1:$port", auth(opened)))))
        assertEquals(HostGate.HostUse(), gate.log()["127.0.0.1"])
        assertFalse(gate.refusedAny())
    }

    @Test
    fun itListensOnLoopbackAlone() {
        val (gate, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
        assertEquals(loopback, gate.boundAddress)
        assertTrue(opened.proxyArg.endsWith("@127.0.0.1:${opened.port}"))
    }

    @Test
    fun closeStopsAcceptingClosesEveryTunnelAndLeavesNoThread() {
        val server = ServerSocket(0, 50, loopback).also { servers += it }
        val held = mutableListOf<Socket>()
        val upstream = thread(isDaemon = true) { held += server.accept() }
        val (gate, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
        val client = connect(opened)
        client.getOutputStream().write(connectLine("127.0.0.1:${server.localPort}", auth(opened)).toByteArray())
        assertEquals(200, status(head(client.getInputStream())))
        upstream.join(5_000)
        assertTrue(Thread.getAllStackTraces().keys.any { it.name.startsWith("caracole-gate") })
        gate.close()
        assertEquals(-1, client.getInputStream().read(), "the open tunnel is closed")
        client.close()
        held.forEach { it.close() }
        assertEquals(emptyList(), Thread.getAllStackTraces().keys.filter { it.isAlive && it.name.startsWith("caracole-gate") }.map { it.name })
        assertFailsWith<ConnectException> { Socket(loopback, opened.port).close() }
        gate.close()
    }

    @Test
    fun beyondItsConnectionsAtOnceItAnswers503() {
        val server = ServerSocket(0, 50, loopback).also { servers += it }
        val held = mutableListOf<Socket>()
        val upstream = thread(isDaemon = true) { held += server.accept() }
        val (_, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE, maxConnections = 1)
        connect(opened).use { first ->
            first.getOutputStream().write(connectLine("127.0.0.1:${server.localPort}", auth(opened)).toByteArray())
            assertEquals(200, status(head(first.getInputStream())))
            upstream.join(5_000)
            assertEquals(503, status(ask(opened, connectLine("127.0.0.1:${server.localPort}", auth(opened)))))
        }
        held.forEach { it.close() }
    }

    @Test
    fun anIdleTunnelAndASilentClientAreClosed() {
        val server = ServerSocket(0, 50, loopback).also { servers += it }
        val held = mutableListOf<Socket>()
        val upstream = thread(isDaemon = true) { held += server.accept() }
        val (_, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE, idleTimeoutMs = 300,
                               headTimeoutMs = 300)
        connect(opened).use { s ->
            s.getOutputStream().write(connectLine("127.0.0.1:${server.localPort}", auth(opened)).toByteArray())
            assertEquals(200, status(head(s.getInputStream())))
            upstream.join(5_000)
            val start = System.nanoTime()
            assertEquals(-1, s.getInputStream().read())
            assertTrue(System.nanoTime() - start < 5_000_000_000L)
        }
        held.forEach { it.close() }
        connect(opened).use { s -> assertEquals(-1, s.getInputStream().read(), "a client that never asks") }
    }

    @Test
    fun theLogIsBoundedWhateverAClientNames() {
        val (gate, opened) = gate(HostGate.Mode.NETWORK, HostGate.HostRule.YOUTUBE)
        val names = HostGate.LOG_HOSTS + 20
        for (i in 0 until names) ask(opened, connectLine("h$i.example.com:443", auth(opened)))
        val log = gate.log()
        assertEquals(HostGate.LOG_HOSTS + 1, log.size)
        assertEquals(HostGate.HostUse(refused = 20), log["(other hosts)"])
        assertEquals(names, log.values.sumOf { it.refused })
    }

    @Test
    fun theModeIsReadFromTheValueGiven() {
        assertEquals(HostGate.Mode.LOOPBACK, HostGate.Mode.of("loopback"))
        assertEquals(HostGate.Mode.NETWORK, HostGate.Mode.of(null))
        assertEquals(HostGate.Mode.NETWORK, HostGate.Mode.of("anything"))
    }
}
