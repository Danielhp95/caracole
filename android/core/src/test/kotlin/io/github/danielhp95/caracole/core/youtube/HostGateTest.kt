package io.github.danielhp95.caracole.core.youtube

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.ConnectException
import java.net.InetAddress
import java.net.Inet6Address
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.util.Base64
import java.util.Collections
import java.util.concurrent.atomic.AtomicBoolean
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

    /**
     * A resolver that answers every name with a public address (203.0.113.7, TEST-NET-3, at the port asked), and the
     * connector that dials that address on loopback's [port] instead: what the gate was asked to look up is [asked],
     * what it dialled [dialled].
     */
    private class ToLoopback(val port: Int, val address: InetAddress = PUBLIC) : HostGate.Resolver, HostGate.Connector {
        val asked: MutableList<String> = Collections.synchronizedList(mutableListOf())
        val dialled: MutableList<InetSocketAddress> = Collections.synchronizedList(mutableListOf())
        override fun resolve(host: String, port: Int): List<InetSocketAddress> {
            asked += "$host:$port"
            return listOf(InetSocketAddress(address, port))
        }
        override fun connect(socket: Socket, address: InetSocketAddress, timeoutMs: Int) {
            dialled += address
            socket.connect(InetSocketAddress(InetAddress.getByAddress(byteArrayOf(127, 0, 0, 1)), port), timeoutMs)
        }

        companion object {
            val PUBLIC: InetAddress = InetAddress.getByAddress(byteArrayOf(203.toByte(), 0, 113, 7))
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
        val gate = HostGate(mode, rule, resolver, maxConnections, HostGate.CONNECT_TIMEOUT_MS, idleTimeoutMs, headTimeoutMs,
                            connector = resolver as? HostGate.Connector ?: HostGate.Connector.DIRECT)
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

    /** The kill check's gate, LOOPBACK with its hosts narrowed to [HostGate.KILL_CHECK_HOSTS]: 127.0.0.1 tunnelled,
     * 10.0.2.2 (the emulator's host, a routable private address on some real networks) refused and never dialled;
     * the tests' LOOPBACK gate keeps both, and a host outside LOOPBACK_NAMES can't be named. */
    @Test
    fun theKillChecksGateReaches127001Alone() {
        assertEquals(listOf("127.0.0.1"), HostGate.KILL_CHECK_HOSTS)
        val server = upstream(0, "ok".toByteArray())
        val gate = HostGate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE, never,
                            loopbackHosts = HostGate.KILL_CHECK_HOSTS).also { gates += it }
        val opened = gate.start()
        assertEquals(403, status(ask(opened, connectLine("10.0.2.2:${server.port}", auth(opened)))))
        assertEquals(403, status(ask(opened, "GET http://10.0.2.2:${server.port}/clip.m4a HTTP/1.1\r\n" +
            "Host: 10.0.2.2:${server.port}\r\nProxy-Authorization: ${auth(opened)}\r\n\r\n")))
        assertEquals(HostGate.HostUse(refused = 2, why = "not 127.0.0.1"), gate.log()["10.0.2.2"])
        connect(opened).use { s ->
            s.getOutputStream().write(connectLine("127.0.0.1:${server.port}", auth(opened)).toByteArray())
            assertEquals(200, status(head(s.getInputStream())))
            assertEquals("ok", s.getInputStream().readAllBytes().toString(Charsets.US_ASCII))
        }
        server.done.join(5_000)
        assertEquals(1, gate.log()["127.0.0.1"]?.connects)
        // The tests' LOOPBACK gate keeps both hosts (not dialled here: 10.0.2.2 is no host of this machine's).
        assertEquals(listOf("127.0.0.1", "10.0.2.2"), HostGate.LOOPBACK_NAMES)
        assertFailsWith<IllegalArgumentException> {
            HostGate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE, never, loopbackHosts = listOf("192.168.1.1"))
        }
        assertFailsWith<IllegalArgumentException> {
            HostGate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE, never, loopbackHosts = emptyList())
        }
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
        assertEquals(listOf(InetSocketAddress(ToLoopback.PUBLIC, 443)), resolver.dialled.toList(),
                     "the address checked is the one dialled, with no second lookup")
        eventually("logged ${gate.log()}") {
            gate.log()["rr3---sn-abc.googlevideo.com"] ==
                HostGate.HostUse(connects = 1, bytesUp = 5, bytesDown = 5, refused = 1, why = HostGate.WHY_OFF_RULE)
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
        assertEquals(HostGate.HostUse(refused = 1, why = HostGate.WHY_OFF_RULE), gate.log()["example.com"])
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
            assertEquals(HostGate.HostUse(refused = 2, why = HostGate.WHY_BY_NAME), gate.log()["jnn-pa.googleapis.com"])
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
        assertEquals(HostGate.HostUse(refused = 1, why = HostGate.WHY_OFF_RULE), gate.log()["www.youtube.com"])
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

    /** PROXY_PATTERN, the shape `:youtube`'s glue holds a `--proxy` to (a Python regex; this one reads the same in
     * Java's), matches every proxyArg whole, and nothing of another host, scheme or token. */
    @Test
    fun theProxyPatternIsProxyArgsShape() {
        val pattern = Regex(HostGate.PROXY_PATTERN)
        repeat(3) {
            val (_, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
            assertTrue(pattern.matches(opened.proxyArg), opened.proxyArg)
            assertFalse(pattern.matches(opened.proxyArg.replace("127.0.0.1", "127.0.0.2")))
            assertFalse(pattern.matches(opened.proxyArg.replace("http://", "socks5://")))
            assertFalse(pattern.matches(opened.proxyArg.replace("@", "0@")))
        }
        assertEquals(listOf("127.0.0.1", "10.0.2.2"), HostGate.LOOPBACK_NAMES)
    }

    /** The log's names that are no host's are youtube.json's (`gate`: youtube.py's PHONE_GATE), which the bench's
     * checker reads too. */
    @Test
    fun theLogsOwnNamesAreTheDatas() {
        val data = YouTubeData.read()
        assertEquals(data.text("malformed", data.gate), HostGate.MALFORMED)
        assertEquals(data.text("other_hosts", data.gate), HostGate.OTHER_HOSTS)
        assertEquals(data.text("stopped", data.gate), HostGate.STOPPED)
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
        assertEquals(HostGate.HostUse(refused = 20, why = HostGate.WHY_OFF_RULE), log["(other hosts)"])
        assertEquals(names, log.values.sumOf { it.refused })
    }

    @Test
    fun theModeIsReadFromTheValueGiven() {
        assertEquals(HostGate.Mode.LOOPBACK, HostGate.Mode.of("loopback"))
        assertEquals(HostGate.Mode.NETWORK, HostGate.Mode.of(null))
        assertEquals(HostGate.Mode.NETWORK, HostGate.Mode.of("anything"))
    }

    // Fix round 1.

    /** A client that writes [text] a byte every [everyMs] until the gate closes it; the thread ends then. */
    private fun trickle(opened: HostGate.Opened, text: String, everyMs: Long): Pair<Socket, Thread> {
        val s = connect(opened)
        val t = thread(isDaemon = true) {
            try {
                var i = 0
                while (true) {
                    s.getOutputStream().write(text[i % text.length].code)
                    s.getOutputStream().flush()
                    i++
                    Thread.sleep(everyMs)
                }
            } catch (_: Exception) {
            }
        }
        return s to t
    }

    /** -1, or the reset a closed connection may give. */
    private fun endOf(s: Socket): Int = try {
        s.getInputStream().read()
    } catch (_: SocketException) {
        -1
    }

    private fun gateThreads(opened: HostGate.Opened) =
        Thread.getAllStackTraces().keys.filter { it.isAlive && it.name.startsWith("caracole-gate-${opened.port}-") }

    @Test
    fun aClientThatTricklesItsHeadIsCutAtTheHeadDeadline() {
        val (_, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE, headTimeoutMs = 400)
        val start = System.nanoTime()
        val (s, t) = trickle(opened, "CONNECT 127.0.0.1:1 HTTP/1.1\r\nX-Slow: " + "a".repeat(10_000), everyMs = 40)
        s.use { assertEquals(-1, endOf(it)) }
        val took = (System.nanoTime() - start) / 1_000_000
        assertTrue(took in 350..3_000, "cut after $took ms")
        t.join(5_000)
    }

    @Test
    fun sixteenTricklingClientsKeepAnAuthenticatedConnectOutNoLongerThanTheHeadDeadline() {
        val server = upstream(0, ByteArray(0))
        val (_, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE, headTimeoutMs = 500)
        val start = System.nanoTime()
        val slow = (1..HostGate.MAX_CONNECTIONS).map { trickle(opened, "GET / HTTP/1.1\r\nX: " + "a".repeat(100_000), 50) }
        Thread.sleep(100)
        assertEquals(503, status(ask(opened, connectLine("127.0.0.1:${server.port}", auth(opened)))),
                     "the tricklers hold every connection at first")
        var answer: Int
        do {
            answer = status(ask(opened, connectLine("127.0.0.1:${server.port}", auth(opened))))
            if (answer == 503) Thread.sleep(20)
        } while (answer == 503 && System.nanoTime() - start < 10_000_000_000L)
        val took = (System.nanoTime() - start) / 1_000_000
        assertEquals(200, answer)
        assertTrue(took < 2_000, "the CONNECT waited $took ms")
        slow.forEach { (s, t) -> s.close(); t.join(5_000) }
    }

    @Test
    fun aTunnelWhoseClientHalfClosedAndStopsReadingIsClosedAtTheIdleTimeout() {
        val server = ServerSocket(0, 50, loopback).also { servers += it }
        val ended = AtomicBoolean(false)
        val writer = thread(isDaemon = true) {
            server.accept().use { s ->
                try {
                    while (true) s.getOutputStream().write(ByteArray(64 * 1024))
                } catch (_: IOException) {
                    ended.set(true)
                }
            }
        }
        val (gate, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE, idleTimeoutMs = 300)
        val client = connect(opened)
        client.receiveBufferSize = 4096
        client.getOutputStream().write(connectLine("127.0.0.1:${server.localPort}", auth(opened)).toByteArray())
        assertEquals(200, status(head(client.getInputStream())))
        client.shutdownOutput()
        writer.join(10_000)
        assertTrue(ended.get(), "the upstream's writes failed once the gate closed it")
        client.close()
        gate.close()
        assertEquals(emptyList(), gateThreads(opened).map { it.name })
    }

    @Test
    fun aRelayWhoseClientStopsReadingIsClosedAtTheIdleTimeout() {
        val server = ServerSocket(0, 50, loopback).also { servers += it }
        val ended = AtomicBoolean(false)
        val writer = thread(isDaemon = true) {
            server.accept().use { s ->
                head(s.getInputStream())
                try {
                    s.getOutputStream().write("HTTP/1.1 200 OK\r\n\r\n".toByteArray())
                    while (true) s.getOutputStream().write(ByteArray(64 * 1024))
                } catch (_: IOException) {
                    ended.set(true)
                }
            }
        }
        val (gate, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE, idleTimeoutMs = 300)
        val client = connect(opened)
        client.receiveBufferSize = 4096
        client.getOutputStream().write(("GET http://127.0.0.1:${server.localPort}/ HTTP/1.1\r\n" +
            "Proxy-Authorization: ${auth(opened)}\r\n\r\n").toByteArray())
        writer.join(10_000)
        assertTrue(ended.get(), "the upstream's writes failed once the gate closed it")
        client.close()
        gate.close()
        assertEquals(emptyList(), gateThreads(opened).map { it.name })
    }

    /** What an upstream HTTP server was asked, for each of [answers] in turn. */
    private fun httpUpstream(vararg answers: String): Pair<Int, MutableList<String>> {
        val server = ServerSocket(0, 50, loopback).also { servers += it }
        val asked = Collections.synchronizedList(mutableListOf<String>())
        thread(isDaemon = true) {
            for (answer in answers) {
                try {
                    server.accept().use { s ->
                        asked += head(s.getInputStream())
                        s.getOutputStream().write(answer.toByteArray(Charsets.ISO_8859_1))
                    }
                } catch (_: IOException) {
                    return@thread
                }
            }
        }
        return server.localPort to asked
    }

    @Test
    fun theRelaySendsTheUrlsAuthorityAsItsHost() {
        val ok = "HTTP/1.1 204 No Content\r\n\r\n"
        val (port, asked) = httpUpstream(ok, ok)
        val (_, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
        assertEquals(204, status(ask(opened, "GET http://127.0.0.1:$port/a HTTP/1.1\r\nHost: evil.example\r\n" +
            "Accept: */*\r\nProxy-Authorization: ${auth(opened)}\r\n\r\n")))
        assertEquals(204, status(ask(opened, "GET http://127.0.0.1:$port/b HTTP/1.1\r\n" +
            "Proxy-Authorization: ${auth(opened)}\r\n\r\n")))
        eventually("both asked") { asked.size == 2 }
        assertEquals("GET /a HTTP/1.1\r\nHost: 127.0.0.1:$port\r\nAccept: */*\r\nConnection: close\r\n\r\n", asked[0])
        assertEquals("GET /b HTTP/1.1\r\nHost: 127.0.0.1:$port\r\nConnection: close\r\n\r\n", asked[1])
    }

    @Test
    fun aHeaderLineWithABareCrOrAControlCharacterIs400() {
        val (gate, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
        for (bad in listOf("X-A: a\rb", "X-A: a\u0001b", "X-A: a\u007fb", "X-A: a\u0000b")) {
            assertEquals(400, status(ask(opened, "CONNECT 127.0.0.1:1 HTTP/1.1\r\n$bad\r\n" +
                "Proxy-Authorization: ${auth(opened)}\r\n\r\n")), bad)
        }
        assertEquals(407, status(ask(opened, "CONNECT 127.0.0.1:1 HTTP/1.1\r\nX-A: a\tb\r\n\r\n")), "a tab is allowed")
        assertEquals(emptyMap(), gate.log())
    }

    @Test
    fun anUpstreamThatClosesBeforeAnsweringOrAnswersPastTheCapIs502() {
        val (port, _) = httpUpstream("", "HTTP/1.1 200 OK\r\nX: " + "a".repeat(HostGate.HEAD_MAX + 10) + "\r\n\r\n")
        val (_, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
        val get = "GET http://127.0.0.1:$port/ HTTP/1.1\r\nProxy-Authorization: ${auth(opened)}\r\n\r\n"
        assertEquals(502, status(ask(opened, get)), "closed before answering")
        assertEquals(502, status(ask(opened, get)), "a head past the cap")
    }

    @Test
    fun underTheYouTubeRuleANameThatResolvesToALocalAddressIsRefused() {
        fun v6(vararg bytes: Int): InetAddress = Inet6Address.getByAddress(null, ByteArray(16) { bytes[it].toByte() }, -1)
        val mapped = IntArray(16).also { it[10] = 0xff; it[11] = 0xff; it[12] = 10; it[15] = 1 }
        val local = listOf(
            InetAddress.getByAddress(byteArrayOf(127, 0, 0, 1)),
            InetAddress.getByAddress(byteArrayOf(127, 9, 9, 9)),
            InetAddress.getByAddress(byteArrayOf(10, 1, 2, 3)),
            InetAddress.getByAddress(byteArrayOf(172.toByte(), 16, 0, 1)),
            InetAddress.getByAddress(byteArrayOf(192.toByte(), 168.toByte(), 1, 1)),
            InetAddress.getByAddress(byteArrayOf(169.toByte(), 254.toByte(), 1, 1)),
            InetAddress.getByAddress(byteArrayOf(0, 0, 0, 0)),
            InetAddress.getByAddress(byteArrayOf(0, 1, 2, 3)),
            InetAddress.getByAddress(byteArrayOf(224.toByte(), 0, 0, 1)),
            InetAddress.getByAddress(byteArrayOf(100, 64, 0, 1)),
            InetAddress.getByAddress(byteArrayOf(100, 127, 255.toByte(), 254.toByte())),
            InetAddress.getByAddress(byteArrayOf(255.toByte(), 255.toByte(), 255.toByte(), 255.toByte())),
            v6(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1),
            v6(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            v6(0xfe, 0x80, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1),
            v6(0xfc, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1),
            v6(0xfd, 0x12, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1),
            v6(0xff, 0x02, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1),
            v6(*mapped),
        )
        for (address in local) {
            val net = ToLoopback(1, address)
            val (gate, opened) = gate(HostGate.Mode.NETWORK, HostGate.HostRule.YOUTUBE, net)
            assertEquals(403, status(ask(opened, connectLine("www.youtube.com:443", auth(opened)))), "$address")
            val use = gate.log()["www.youtube.com"]
            assertEquals(1, use?.refused, "$address")
            assertTrue(use?.why?.startsWith("resolves to ") == true, "${use?.why}")
            assertEquals(emptyList(), net.dialled.toList(), "$address")
        }
        // One local address among public ones is enough.
        val both = object : HostGate.Resolver {
            override fun resolve(host: String, port: Int) =
                listOf(InetSocketAddress(ToLoopback.PUBLIC, port), InetSocketAddress(local[2], port))
        }
        val (_, opened) = gate(HostGate.Mode.NETWORK, HostGate.HostRule.YOUTUBE, both)
        assertEquals(403, status(ask(opened, connectLine("www.youtube.com:443", auth(opened)))))
    }

    /** OBSERVE logs every host but reaches no address that isn't public, as YOUTUBE: a name that resolves to one, or
     * an IP literal of one (loopback, site-local, link-local), is refused and logged; the LAN and another app's local
     * service stay out of an observed session's reach, a redirect's too. */
    @Test
    fun observeRefusesANameThatResolvesToALocalAddressAndLogsIt() {
        val server = upstream(0, ByteArray(0))
        val ten = InetAddress.getByAddress(byteArrayOf(10, 0, 0, 1))
        val net = ToLoopback(server.port, ten)
        val (gate, opened) = gate(HostGate.Mode.NETWORK, HostGate.HostRule.OBSERVE, net)
        assertEquals(403, status(ask(opened, connectLine("example.com:443", auth(opened)))))
        assertEquals(emptyList(), net.dialled.toList())
        assertEquals(1, gate.log()["example.com"]?.refused, gate.log().toString())
    }

    @Test
    fun observeRefusesAnIpLiteralThatIsntPublicAndTakesAPublicOne() {
        val server = upstream(0, ByteArray(0))
        val net = ToLoopback(server.port)
        val (gate, opened) = gate(HostGate.Mode.NETWORK, HostGate.HostRule.OBSERVE, net)
        for (target in listOf("127.0.0.1:80", "10.0.2.2:80", "192.168.1.1:443", "169.254.1.1:80", "[::1]:80",
                              "[fe80::1]:80")) {
            assertEquals(403, status(ask(opened, connectLine(target, auth(opened)))), target)
        }
        assertEquals(emptyList(), net.dialled.toList())
        assertEquals(6, gate.log().values.sumOf { it.refused }, gate.log().toString())
        assertEquals(200, status(ask(opened, connectLine("203.0.113.7:443", auth(opened)))))
        assertEquals(1, net.dialled.size)
        // YOUTUBE takes no literal at all, as before.
        val (_, youtube) = gate(HostGate.Mode.NETWORK, HostGate.HostRule.YOUTUBE, net)
        assertEquals(403, status(ask(youtube, connectLine("203.0.113.7:443", auth(youtube)))))
    }

    @Test
    fun noGateThreadIsLeftWhateverCloseRacesWith() {
        repeat(30) { round ->
            val gate = HostGate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE, never)
            val opened = gate.start()
            val hammers = (1..4).map {
                thread(isDaemon = true) {
                    try {
                        while (true) Socket(loopback, opened.port).use { it.getOutputStream().write("CONN".toByteArray()) }
                    } catch (_: IOException) {
                    }
                }
            }
            Thread.sleep((round % 5).toLong())
            gate.close()
            hammers.forEach { it.join(5_000) }
            assertEquals(emptyList(), gateThreads(opened).map { it.name }, "round $round")
        }
    }

    @Test
    fun aHeadPastTheCapIs400() {
        val (_, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
        val start = "GET http://127.0.0.1:1/ HTTP/1.1\r\nX: "
        assertEquals(400, status(ask(opened, start + "a".repeat(HostGate.HEAD_MAX + 1 - start.length))))
    }

    @Test
    fun theEdgesOfATargetAreRefused() {
        val (_, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE, never)
        val a = "Proxy-Authorization: ${auth(opened)}\r\n"
        fun get(target: String, more: String = "") = status(ask(opened, "GET $target HTTP/1.1\r\n$more$a\r\n"))
        assertEquals(400, get("http://127.0.0.1:1/", "Transfer-Encoding: chunked\r\n"))
        assertEquals(400, get("http://127.0.0.1:1/", "Content-Length: 5\r\n"))
        assertEquals(400, get("http://u:p@127.0.0.1:1/"))
        assertEquals(400, get("http://127.0.0.1%2e:1/"))
        assertEquals(400, status(ask(opened, connectLine("www.youtube.com%2e:443", auth(opened)))))
        assertEquals(400, status(ask(opened, connectLine("[fe80::1%25en0]:443", auth(opened)))))
        assertEquals(400, status(ask(opened, connectLine("127.0.0.1\u0000:443", auth(opened)))))
        assertEquals(400, status(ask(opened, connectLine("127.1:80", auth(opened)))))
        assertEquals(400, status(ask(opened, connectLine("0x7f.0.0.1:80", auth(opened)))))
        assertEquals(403, status(ask(opened, connectLine("[::ffff:127.0.0.1]:80", auth(opened)))))
        assertEquals(403, status(ask(opened, connectLine("localhost:80", auth(opened)))))
    }

    @Test
    fun underObserveJnnPaIsRefusedUnderItAndByGet() {
        val (gate, opened) = gate(HostGate.Mode.NETWORK, HostGate.HostRule.OBSERVE, never)
        assertEquals(403, status(ask(opened, connectLine("x.jnn-pa.googleapis.com:443", auth(opened)))))
        assertEquals(403, status(ask(opened, "GET http://jnn-pa.googleapis.com/ HTTP/1.1\r\n" +
            "Proxy-Authorization: ${auth(opened)}\r\n\r\n")))
        assertEquals(mapOf("x.jnn-pa.googleapis.com" to HostGate.HostUse(refused = 1, why = HostGate.WHY_BY_NAME),
                           "jnn-pa.googleapis.com" to HostGate.HostUse(refused = 1, why = HostGate.WHY_BY_NAME)),
                     gate.log())
    }

    // Fix round 2 (the gate's last re-review).

    @Test
    fun anIpv4CompatibleAddressWhoseLastByteIsPast127IsReadAsItsIpv4() {
        fun compatible(last: Int): InetAddress =
            Inet6Address.getByAddress(null, ByteArray(16) { if (it == 15) last.toByte() else 0 }, -1)
        for (last in listOf(0x80, 0xc8, 0xff)) {
            assertFalse(HostGate.isPublic(compatible(last)), "::0.0.0.$last is 0.0.0.$last, not public")
        }
        assertFalse(HostGate.isPublic(compatible(0)), "::")
        assertFalse(HostGate.isPublic(compatible(1)), "::1")
    }

    @Test
    fun aTunnelBothOfWhosePumpsAreStuckInWritesIsClosedAtTheIdleTimeout() {
        val server = ServerSocket().also { servers += it }
        server.receiveBufferSize = 4096
        server.bind(InetSocketAddress(loopback, 0))
        val upstreamEnded = AtomicBoolean(false)
        val upstreamWriter = thread(isDaemon = true) {
            server.accept().use { s ->
                try {
                    while (true) s.getOutputStream().write(ByteArray(64 * 1024))
                } catch (_: IOException) {
                    upstreamEnded.set(true)
                }
            }
        }
        val (gate, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE, idleTimeoutMs = 300)
        val client = Socket()
        client.receiveBufferSize = 4096
        client.connect(InetSocketAddress(loopback, opened.port))
        client.soTimeout = 10_000
        client.getOutputStream().write(connectLine("127.0.0.1:${server.localPort}", auth(opened)).toByteArray())
        assertEquals(200, status(head(client.getInputStream())))
        val clientEnded = AtomicBoolean(false)
        val clientWriter = thread(isDaemon = true) {
            try {
                while (true) client.getOutputStream().write(ByteArray(64 * 1024))
            } catch (_: IOException) {
                clientEnded.set(true)
            }
        }
        upstreamWriter.join(10_000)
        clientWriter.join(10_000)
        assertTrue(upstreamEnded.get(), "the upstream's writes failed once the gate closed the tunnel")
        assertTrue(clientEnded.get(), "the client's writes failed once the gate closed the tunnel")
        client.close()
        gate.close()
        assertEquals(emptyList(), gateThreads(opened).map { it.name })
    }

    @Test
    fun aRelayedAnswerWhoseHeadHasABareCrOrAControlCharacterIs502() {
        val bad = listOf("HTTP/1.1 200 OK\r\nX-A: a\rb\r\n\r\n", "HTTP/1.1 200 OK\r\nX-A: a\u0001b\r\n\r\n",
                         "HTTP/1.1 200 OK\r\nX-A: a\u007fb\r\n\r\n", "HTTP/1.1 200 O\u0000K\r\n\r\n")
        val (port, _) = httpUpstream(*bad.toTypedArray(), "HTTP/1.1 200 OK\r\nX-A: a\tb\r\n\r\n")
        val (_, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
        val get = "GET http://127.0.0.1:$port/ HTTP/1.1\r\nProxy-Authorization: ${auth(opened)}\r\n\r\n"
        for (answer in bad) assertEquals(502, status(ask(opened, get)), answer)
        assertEquals(200, status(ask(opened, get)), "a tab is allowed")
    }

    @Test
    fun theYouTubeRulesHostsAreTheDatas() {
        val data = YouTubeData.read()
        val gate = data.gate
        val names = data.texts("names", gate)
        val port = data.number("port", gate).toInt()
        val rule = HostGate.HostRule.YOUTUBE
        assertEquals(listOf("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "consent.youtube.com"),
                     names)
        for (name in names) {
            assertTrue(rule.allows(name, port, connect = true), name)
            assertFalse(rule.allows(name, port + 1, connect = true), name)
            assertFalse(rule.allows(name, port, connect = false), name)
        }
        for (suffix in data.texts("suffixes", gate)) {
            assertTrue(rule.allows("rr3---sn-abc$suffix", port, connect = true), suffix)
            assertFalse(rule.allows(suffix.removePrefix("."), port, connect = true) && suffix.removePrefix(".") !in names)
        }
        assertFalse(rule.allows("youtubei.googleapis.com", port, connect = true))
        assertEquals(data.texts("refused", gate), HostGate.HostRule.REFUSED)
        for (name in data.texts("refused", gate)) {
            assertFalse(rule.allows(name, port, connect = true))
            assertFalse(HostGate.HostRule.OBSERVE.allows("x.$name", port, connect = true))
        }
        for (name in data.texts("apart", gate)) assertTrue(rule.reportsApart(name), name)
        assertFalse(rule.reportsApart("www.youtube.com"))
    }

    // Fix round 1 of Y1.3's review.

    @Test
    fun aConnectionThreadThatThrowsLeavesTheGateServingAndTheProcessAlone() {
        val uncaught = Collections.synchronizedList(mutableListOf<Throwable>())
        val was = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { _, e -> uncaught += e }
        try {
            val (gate, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
            val throwing = AtomicBoolean(true)
            gate.beforeServing = { if (throwing.getAndSet(false)) throw NoSuchElementException("a bug in a connection") }
            connect(opened).use { s ->
                s.getOutputStream().write(connectLine("127.0.0.1:1", auth(opened)).toByteArray())
                assertEquals(-1, s.getInputStream().read(), "the broken connection is closed")
            }
            assertEquals(407, status(ask(opened, connectLine("127.0.0.1:1", null))), "the gate still serves")
            eventually("the broken connection's thread ended") {
                Thread.getAllStackTraces().keys.none { it.isAlive && it.name == "caracole-gate-${opened.port}-1" }
            }
            assertEquals(emptyList(), uncaught.toList())
        } finally {
            Thread.setDefaultUncaughtExceptionHandler(was)
        }
    }

    @Test
    fun aTunnelWhosePumpsEndTogetherIsWaitedForWithoutABug() {
        val uncaught = Collections.synchronizedList(mutableListOf<Throwable>())
        val was = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { _, e -> uncaught += e }
        try {
            repeat(40) { round ->
                val server = upstream(0, bytes(64, round))
                val (_, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
                connect(opened).use { s ->
                    s.getOutputStream().write(connectLine("127.0.0.1:${server.port}", auth(opened)).toByteArray())
                    assertEquals(200, status(head(s.getInputStream())))
                    s.shutdownOutput()
                    s.getInputStream().readAllBytes()
                }
            }
            assertEquals(emptyList(), uncaught.toList())
        } finally {
            Thread.setDefaultUncaughtExceptionHandler(was)
        }
    }

    // The runner's re-review.

    @Test
    fun aCloseUnderAnInterruptReturnsClosesEverythingAndKeepsTheInterrupt() {
        val (gate, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE, headTimeoutMs = 60_000)
        val (s, t) = trickle(opened, "CONNECT 127.0.0.1:1 HTTP/1.1\r\nX-Slow: " + "a".repeat(100), everyMs = 200)
        eventually("the slow client is served") { gateThreads(opened).any { it.name != "caracole-gate-${opened.port}-accept" } }
        Thread.currentThread().interrupt()
        try {
            gate.close()
            assertTrue(Thread.interrupted(), "the interrupt is kept (and cleared here)")
        } finally {
            Thread.interrupted()
        }
        s.use { assertEquals(-1, endOf(it), "its client's socket is closed") }
        t.join(5_000)
        assertEquals(emptyList(), gateThreads(opened).map { it.name }, "no thread of the gate is left")
        assertFailsWith<java.net.ConnectException> { connect(opened).close() }
    }

    @Test
    fun anAcceptorThatThrowsStopsTheGateSaysSoInItsLogAndLeavesTheProcessAlone() {
        val uncaught = Collections.synchronizedList(mutableListOf<Throwable>())
        val was = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { _, e -> uncaught += e }
        try {
            val (gate, opened) = gate(HostGate.Mode.LOOPBACK, HostGate.HostRule.YOUTUBE)
            gate.afterAccepting = { throw NoSuchElementException("a bug in the acceptor") }
            connect(opened).use { s -> assertEquals(-1, s.getInputStream().read(), "the client it took is closed") }
            eventually("the acceptor ended") { gateThreads(opened).isEmpty() }
            val stopped = YouTubeData.read().text("stopped", YouTubeData.read().gate)
            assertEquals(listOf(stopped), gate.log().keys.toList(), "the log says the gate stopped, and nothing else")
            assertTrue(stopped == HostGate.STOPPED && !gate.refusedAny())
            assertFailsWith<java.net.ConnectException> { connect(opened).close() }
            assertEquals(emptyList(), uncaught.toList())
        } finally {
            Thread.setDefaultUncaughtExceptionHandler(was)
        }
    }
}
