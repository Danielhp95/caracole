package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.py.Py
import java.io.BufferedInputStream
import java.io.ByteArrayOutputStream
import java.io.Closeable
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketTimeoutException
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong

/**
 * The proxy yt-dlp is given on the phone (docs: the phone-YouTube design's §3.3): an HTTP proxy on 127.0.0.1 at an
 * ephemeral port, with a fresh user and secret each [start], that tunnels a CONNECT (and relays a plain GET where
 * the mode allows one) to the hosts its [mode] and [rule] allow and to no other, and logs each host asked for: its
 * connects, the bytes each way, the refusals. It is a check and a measurement: only the argv routes yt-dlp through it.
 *
 * - [Mode.LOOPBACK] (tests and instrumentation): `127.0.0.1` and `10.0.2.2` alone, any port, CONNECT and GET; nothing
 *   is looked up, the rule unused. [Mode.NETWORK]: the [rule], each name looked up by [resolver] only once allowed.
 * - `jnn-pa.googleapis.com` (and any name under it) is refused in every mode and by every rule.
 * - A refused host: 403, logged `refused`. A wrong or missing `Proxy-Authorization`: 407 with `Proxy-Authenticate`,
 *   nothing logged. A target that isn't `host:port` (an `@`, a control character, a byte past ASCII, a bad port or IP
 *   literal): 400, logged under [MALFORMED]. A method but CONNECT and GET: 405. An upstream that won't connect: 502, or
 *   504 past [connectTimeoutMs]. More than [maxConnections] at once: 503.
 * - The gate reads no property: the main process passes the mode ([Mode.of] `caracole.network`'s value).
 * - The secret is kept as a digest; only [Opened.proxyArg] holds it, and no `toString`, log or message here names it.
 */
class HostGate(
    private val mode: Mode,
    private val rule: HostRule,
    private val resolver: Resolver = Resolver.SYSTEM,
    private val maxConnections: Int = MAX_CONNECTIONS,
    private val connectTimeoutMs: Int = CONNECT_TIMEOUT_MS,
    private val idleTimeoutMs: Int = IDLE_TIMEOUT_MS,
    private val headTimeoutMs: Int = HEAD_TIMEOUT_MS,
) : Closeable {
    enum class Mode {
        LOOPBACK, NETWORK;

        companion object {
            /** `loopback` (CaracoleTestRunner's and every Gradle test task's `caracole.network`) or the network. */
            fun of(network: String?): Mode = if (network == "loopback") LOOPBACK else NETWORK
        }
    }

    /**
     * Which hosts a [Mode.NETWORK] gate allows: [YOUTUBE] (the design's §3.3 list, CONNECT on 443 alone) or [OBSERVE]
     * (the bench's, set by a button press alone: every host and port, CONNECT and GET, logged). Names are compared
     * lowercased as ASCII with no trailing dot; an IP literal never matches a name. Kotlin data in this one place.
     */
    class HostRule private constructor(
        private val label: String,
        private val names: Set<String>,
        private val suffixes: List<String>,
        private val port: Int?,
        private val plainGet: Boolean,
        private val apart: Set<String>,
    ) {
        /** Whether [host] (lowercased, no trailing dot, not an IP literal) at [port] is allowed, by CONNECT or by GET. */
        fun allows(host: String, port: Int, connect: Boolean): Boolean {
            if (refusedByName(host)) return false
            if (!connect && !plainGet) return false
            if (this.port != null && port != this.port) return false
            if (this === OBSERVE) return true
            return host in names || suffixes.any { host.endsWith(it) && host.length > it.length }
        }

        /** The hosts allowed and reported apart (the owner is in the EU: consent, and the redirector). */
        fun reportsApart(host: String): Boolean = host in apart

        override fun toString() = "HostRule.$label"

        companion object {
            /** Refused by name whatever the rule: Google's attestation (BotGuard's `Waa`). A CONNECT hides the path. */
            val REFUSED: List<String> = listOf("jnn-pa.googleapis.com")

            private val APART = setOf("consent.youtube.com", "redirector.googlevideo.com")

            val YOUTUBE = HostRule(
                "YOUTUBE",
                setOf("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "consent.youtube.com"),
                listOf(".googlevideo.com"),
                port = 443,
                plainGet = false,
                apart = APART,
            )
            val OBSERVE = HostRule("OBSERVE", emptySet(), emptyList(), port = null, plainGet = true, apart = APART)

            fun refusedByName(host: String): Boolean = REFUSED.any { host == it || host.endsWith(".$it") }
        }
    }

    /** A name's addresses at a port, asked only after the rule allowed the name. */
    fun interface Resolver {
        fun resolve(host: String, port: Int): List<InetSocketAddress>

        companion object {
            val SYSTEM = Resolver { host, port -> InetAddress.getAllByName(host).map { InetSocketAddress(it, port) } }
        }
    }

    /** One host's use, keyed in [log] by its name as asked, lowercased; [apart] for a host [HostRule.reportsApart]. */
    data class HostUse(
        val connects: Int = 0,
        val bytesUp: Long = 0,
        val bytesDown: Long = 0,
        val refused: Int = 0,
        val apart: Boolean = false,
    )

    /** A started gate: its port, and the `--proxy` value yt-dlp is given, which holds the user and the secret. */
    class Opened internal constructor(val port: Int, val proxyArg: String) {
        override fun toString() = "HostGate.Opened(127.0.0.1:$port)"
    }

    private class Use(val apart: Boolean) {
        val connects = AtomicInteger()
        val up = AtomicLong()
        val down = AtomicLong()
        val refused = AtomicInteger()
        fun snapshot() = HostUse(connects.get(), up.get(), down.get(), refused.get(), apart)
    }

    /** A target as asked: [key] the log's name for it, [address] an IP literal's bytes (none for a name). */
    private class Authority(val key: String, val port: Int, val address: ByteArray?)

    private class Refusal(val status: Int, val key: String?) : Exception(null, null, false, false)

    private val uses = LinkedHashMap<String, Use>()
    private val sockets: MutableSet<Socket> = ConcurrentHashMap.newKeySet()
    private val threads: MutableSet<Thread> = ConcurrentHashMap.newKeySet()
    private val active = AtomicInteger()
    private val serial = AtomicInteger()
    @Volatile private var closed = false
    private var server: ServerSocket? = null
    private var acceptor: Thread? = null
    private var expected: ByteArray? = null

    /** The address it listens on: 127.0.0.1, never another. */
    internal val boundAddress: InetAddress? get() = server?.inetAddress

    /** Listens on 127.0.0.1 at an ephemeral port with a fresh user and secret. Once a gate. */
    @Synchronized
    fun start(): Opened {
        check(server == null && !closed) { "a HostGate starts once" }
        val user = token()
        val secret = token()
        expected = digest("$user:$secret".toByteArray(Charsets.US_ASCII))
        val socket = ServerSocket(0, 50, LOOPBACK_ADDRESS)
        server = socket
        val port = socket.localPort
        acceptor = spawn("caracole-gate-$port-accept") { accept(socket) }
        return Opened(port, "http://$user:$secret@127.0.0.1:$port")
    }

    /** Each host asked for, in the order first asked; at most [LOG_HOSTS] names, the rest under [OTHER_HOSTS]. */
    fun log(): Map<String, HostUse> = synchronized(uses) { uses.mapValuesTo(LinkedHashMap()) { it.value.snapshot() } }

    /** Whether any request was refused (a host off the rule, or a malformed one). */
    fun refusedAny(): Boolean = synchronized(uses) { uses.values.any { it.refused.get() > 0 } }

    /** Stops accepting, closes every open connection and tunnel, and waits for every thread of the gate to end. */
    override fun close() {
        val toJoin: List<Thread>
        synchronized(this) {
            closed = true
            try {
                server?.close()
            } catch (_: IOException) {
            }
            toJoin = listOfNotNull(acceptor)
        }
        sockets.forEach { quietly(it) }
        for (t in toJoin + threads.toList()) t.join(JOIN_MS)
        threads.removeIf { !it.isAlive }
    }

    override fun toString() = "HostGate($mode, $rule, ${server?.localPort ?: "not started"})"

    private fun accept(socket: ServerSocket) {
        while (!closed) {
            val client = try {
                socket.accept()
            } catch (_: IOException) {
                break
            }
            if (closed) {
                quietly(client)
                break
            }
            if (active.incrementAndGet() > maxConnections) {
                active.decrementAndGet()
                try {
                    client.soTimeout = headTimeoutMs
                    reply(client.getOutputStream(), 503)
                } catch (_: IOException) {
                }
                quietly(client)
                continue
            }
            sockets += client
            spawn("caracole-gate-${socket.localPort}-${serial.incrementAndGet()}") {
                try {
                    serve(client)
                } finally {
                    quietly(client)
                    sockets -= client
                    active.decrementAndGet()
                }
            }
        }
    }

    private fun serve(client: Socket) {
        client.soTimeout = headTimeoutMs
        val input = BufferedInputStream(client.getInputStream())
        val output = client.getOutputStream()
        try {
            val head = try {
                readHead(input) ?: return
            } catch (_: SocketTimeoutException) {
                return
            }
            val lines = head.split('\n').map { it.removeSuffix("\r") }.dropLast(2)
            val parts = lines.firstOrNull()?.split(' ') ?: throw Refusal(400, null)
            if (parts.size != 3 || parts[2] !in VERSIONS) throw Refusal(400, null)
            val headers = lines.drop(1).map { line ->
                val colon = line.indexOf(':')
                if (colon <= 0 || line[0] == ' ' || line[0] == '\t' || ' ' in line.substring(0, colon)) throw Refusal(400, null)
                line.substring(0, colon) to spaced(line.substring(colon + 1))
            }
            if (!authorized(headers)) throw Refusal(407, null)
            val (method, target) = parts
            if (target.any { it.code < 0x21 || it.code > 0x7e }) throw Refusal(400, MALFORMED)
            when (method) {
                "CONNECT" -> tunnel(client, input, output, authority(target, defaultPort = null) ?: throw Refusal(400, MALFORMED))
                "GET" -> relay(client, input, output, target, headers)
                else -> throw Refusal(405, MALFORMED)
            }
        } catch (r: Refusal) {
            if (r.key != null) use(r.key).refused.incrementAndGet()
            try {
                reply(output, r.status)
            } catch (_: IOException) {
            }
        } catch (_: IOException) {
        }
    }

    private fun tunnel(client: Socket, input: InputStream, output: OutputStream, at: Authority) {
        val use = allowed(at, connect = true)
        val upstream = open(at)
        try {
            use.connects.incrementAndGet()
            output.write(ESTABLISHED)
            output.flush()
            pumpBoth(client, input, upstream, use)
        } finally {
            quietly(upstream)
            sockets -= upstream
        }
    }

    private fun relay(client: Socket, input: InputStream, output: OutputStream, target: String, headers: List<Pair<String, String>>) {
        if (target.length < 7 || Py.asciiLower(target.substring(0, 7)) != "http://") throw Refusal(400, MALFORMED)
        val rest = target.substring(7)
        val end = rest.indexOfFirst { it == '/' || it == '?' }.let { if (it < 0) rest.length else it }
        if ('#' in rest) throw Refusal(400, MALFORMED)
        val at = authority(rest.substring(0, end), defaultPort = 80) ?: throw Refusal(400, MALFORMED)
        val path = rest.substring(end).let { if (it.isEmpty() || it[0] == '?') "/$it" else it }
        for ((name, value) in headers) {
            val lower = Py.asciiLower(name)
            if (lower == "transfer-encoding" || (lower == "content-length" && value != "0")) throw Refusal(400, at.key)
        }
        val use = allowed(at, connect = false)
        val upstream = open(at)
        try {
            use.connects.incrementAndGet()
            val sent = buildString {
                append("GET ").append(path).append(' ').append("HTTP/1.1\r\n")
                for ((name, value) in withoutHopByHop(headers)) append(name).append(": ").append(value).append("\r\n")
                append("Connection: close\r\n\r\n")
            }.toByteArray(Charsets.ISO_8859_1)
            upstream.getOutputStream().write(sent)
            upstream.getOutputStream().flush()
            use.up.addAndGet(sent.size.toLong())
            upstream.soTimeout = idleTimeoutMs
            val fromUpstream = BufferedInputStream(upstream.getInputStream())
            val answer = readHead(fromUpstream) ?: return
            val lines = answer.split('\n').map { it.removeSuffix("\r") }.dropLast(2)
            val answerHeaders = lines.drop(1).mapNotNull { line ->
                val colon = line.indexOf(':')
                if (colon <= 0) null else line.substring(0, colon) to spaced(line.substring(colon + 1))
            }
            val back = buildString {
                append(lines.first()).append("\r\n")
                for ((name, value) in withoutHopByHop(answerHeaders)) append(name).append(": ").append(value).append("\r\n")
                append("Connection: close\r\n\r\n")
            }.toByteArray(Charsets.ISO_8859_1)
            output.write(back)
            output.flush()
            use.down.addAndGet(back.size.toLong())
            val activity = AtomicLong(System.nanoTime())
            pump(fromUpstream, output, upstream, use.down, activity) { quietly(client); quietly(upstream) }
            client.shutdownOutput()
        } finally {
            quietly(upstream)
            sockets -= upstream
        }
    }

    /** The log's entry for [at] once the mode and the rule allow it, else a 403 refusal. */
    private fun allowed(at: Authority, connect: Boolean): Use {
        val ok = when {
            HostRule.refusedByName(at.key) -> false
            mode == Mode.LOOPBACK -> at.address != null && LOOPBACK_HOSTS.any { it.contentEquals(at.address) }
            at.address != null -> rule === HostRule.OBSERVE && rule.allows(at.key, at.port, connect)
            else -> rule.allows(at.key, at.port, connect)
        }
        if (!ok) throw Refusal(403, at.key)
        return use(at.key)
    }

    /** The upstream, connected: an IP literal as given, a name through [resolver] (in [Mode.NETWORK] alone). */
    private fun open(at: Authority): Socket {
        val addresses = if (at.address != null) {
            listOf(InetSocketAddress(InetAddress.getByAddress(at.address), at.port))
        } else {
            check(mode == Mode.NETWORK)
            try {
                resolver.resolve(at.key, at.port)
            } catch (_: IOException) {
                throw Refusal(502, null)
            }
        }
        var timedOut = false
        for (address in addresses) {
            val socket = Socket()
            sockets += socket
            if (closed) quietly(socket)
            try {
                socket.connect(address, connectTimeoutMs)
                return socket
            } catch (_: SocketTimeoutException) {
                timedOut = true
            } catch (_: IOException) {
            }
            quietly(socket)
            sockets -= socket
        }
        throw Refusal(if (timedOut) 504 else 502, null)
    }

    /** Client to upstream here, upstream to client on a thread of its own, until either ends or both are idle. */
    private fun pumpBoth(client: Socket, input: InputStream, upstream: Socket, use: Use) {
        val activity = AtomicLong(System.nanoTime())
        val stop = { quietly(client); quietly(upstream) }
        val down = spawn("caracole-gate-${server?.localPort}-${serial.incrementAndGet()}-down") {
            try {
                pump(upstream.getInputStream(), client.getOutputStream(), upstream, use.down, activity, stop)
            } catch (_: IOException) {
            }
            stop()
        }
        try {
            pump(input, upstream.getOutputStream(), client, use.up, activity, stop)
            upstream.shutdownOutput()
        } catch (_: IOException) {
            stop()
        }
        down.join()
    }

    /** Copies [from] to [to] until its end, counting into [count]; idle past [idleTimeoutMs] both ways, [stop]. */
    private fun pump(from: InputStream, to: OutputStream, reading: Socket, count: AtomicLong, activity: AtomicLong, stop: () -> Unit) {
        reading.soTimeout = minOf(idleTimeoutMs, TICK_MS)
        val buffer = ByteArray(BUFFER)
        while (true) {
            val n = try {
                from.read(buffer)
            } catch (_: SocketTimeoutException) {
                if (System.nanoTime() - activity.get() > idleTimeoutMs * 1_000_000L) {
                    stop()
                    return
                }
                continue
            }
            if (n < 0) return
            activity.set(System.nanoTime())
            to.write(buffer, 0, n)
            to.flush()
            count.addAndGet(n.toLong())
            activity.set(System.nanoTime())
        }
    }

    private fun authorized(headers: List<Pair<String, String>>): Boolean {
        val want = expected ?: return false
        val value = headers.firstOrNull { Py.asciiLower(it.first) == "proxy-authorization" }?.second ?: return false
        val space = value.indexOf(' ')
        if (space < 0 || Py.asciiLower(value.substring(0, space)) != "basic") return false
        val given = try {
            Base64.getDecoder().decode(spaced(value.substring(space + 1)))
        } catch (_: IllegalArgumentException) {
            return false
        }
        return MessageDigest.isEqual(digest(given), want)
    }

    private fun use(key: String): Use = synchronized(uses) {
        uses[key] ?: run {
            val named = uses.keys.count { it != OTHER_HOSTS && it != MALFORMED }
            if (key != MALFORMED && named >= LOG_HOSTS) uses.getOrPut(OTHER_HOSTS) { Use(apart = false) }
            else Use(rule.reportsApart(key)).also { uses[key] = it }
        }
    }

    private fun spawn(name: String, body: () -> Unit): Thread {
        threads.removeIf { !it.isAlive }
        val t = Thread(body, name)
        t.isDaemon = true
        threads += t
        t.start()
        return t
    }

    companion object {
        /** Connections served at once (yt-dlp opens a handful); past them, 503. */
        const val MAX_CONNECTIONS = 16
        /** To connect to an upstream; past it, 504. */
        const val CONNECT_TIMEOUT_MS = 15_000
        /** A tunnel or a relay with no byte either way this long is closed. */
        const val IDLE_TIMEOUT_MS = 120_000
        /** For a client's request head, from its connection. */
        const val HEAD_TIMEOUT_MS = 15_000
        /** A request head's bytes at most; past them, 400. */
        const val HEAD_MAX = 16 * 1024
        /** Hosts named in the log at most; any other is counted under [OTHER_HOSTS]. */
        const val LOG_HOSTS = 256
        const val OTHER_HOSTS = "(other hosts)"
        const val MALFORMED = "(malformed)"

        private const val TICK_MS = 1_000
        private const val JOIN_MS = 2_000L
        private const val BUFFER = 16 * 1024
        private val VERSIONS = setOf("HTTP/1.0", "HTTP/1.1")
        private val LOOPBACK_ADDRESS: InetAddress = InetAddress.getByAddress(byteArrayOf(127, 0, 0, 1))
        private val LOOPBACK_HOSTS = listOf(byteArrayOf(127, 0, 0, 1), byteArrayOf(10, 0, 2, 2))
        private val ESTABLISHED = "HTTP/1.1 200 Connection established\r\n\r\n".toByteArray(Charsets.US_ASCII)
        private val HOP_BY_HOP = setOf("connection", "keep-alive", "proxy-authorization", "proxy-authenticate",
                                       "proxy-connection", "te", "trailer", "upgrade")
        private val REASONS = mapOf(400 to "Bad Request", 403 to "Forbidden", 405 to "Method Not Allowed",
                                    407 to "Proxy Authentication Required", 502 to "Bad Gateway",
                                    503 to "Service Unavailable", 504 to "Gateway Timeout")
        private val random = SecureRandom()

        private fun token(): String {
            val bytes = ByteArray(16)
            random.nextBytes(bytes)
            return buildString { for (b in bytes) append(HEX[(b.toInt() shr 4) and 15]).append(HEX[b.toInt() and 15]) }
        }

        private const val HEX = "0123456789abcdef"

        private fun digest(bytes: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(bytes)

        private fun quietly(socket: Socket) {
            try {
                socket.close()
            } catch (_: IOException) {
            }
        }

        private fun reply(output: OutputStream, status: Int) {
            val extra = if (status == 407) "Proxy-Authenticate: Basic realm=\"caracole\"\r\n" else ""
            output.write("HTTP/1.1 $status ${REASONS[status]}\r\n${extra}Content-Length: 0\r\nConnection: close\r\n\r\n"
                .toByteArray(Charsets.US_ASCII))
            output.flush()
        }

        /** [value] less its leading and trailing spaces and tabs (a header's optional whitespace). */
        private fun spaced(value: String): String {
            var start = 0
            var end = value.length
            while (start < end && (value[start] == ' ' || value[start] == '\t')) start++
            while (end > start && (value[end - 1] == ' ' || value[end - 1] == '\t')) end--
            return value.substring(start, end)
        }

        /** [headers] less the hop-by-hop ones and those their Connection names. */
        private fun withoutHopByHop(headers: List<Pair<String, String>>): List<Pair<String, String>> {
            val named = headers.filter { Py.asciiLower(it.first) == "connection" }
                .flatMap { it.second.split(',') }.map { Py.asciiLower(spaced(it)) }.toSet()
            return headers.filter { Py.asciiLower(it.first).let { n -> n !in HOP_BY_HOP && n !in named } }
        }

        /** A head to its blank line, as Latin-1 (each byte one char); none at an end before it; 400 past [HEAD_MAX]. */
        private fun readHead(input: InputStream): String? {
            val out = ByteArrayOutputStream()
            var last = -1
            var beforeLast = -1
            while (true) {
                val b = input.read()
                if (b < 0) return null
                out.write(b)
                if (out.size() > HEAD_MAX) throw Refusal(400, null)
                if (b == '\n'.code && (last == '\n'.code || (last == '\r'.code && beforeLast == '\n'.code))) break
                beforeLast = last
                last = b
            }
            return out.toString(Charsets.ISO_8859_1)
        }

        /**
         * `host:port` (or `[v6]:port`) as a CONNECT or an absolute URL names it, [defaultPort] when it names none (a
         * CONNECT must): a name of ASCII letters, digits, `-`, `_` and dots, lowercased, one trailing dot dropped; a
         * last label of digits alone an IPv4 literal (four of them, each to 255); none for anything else.
         */
        private fun authority(text: String, defaultPort: Int?): Authority? {
            val host: String
            val portText: String?
            if (text.startsWith("[")) {
                val close = text.indexOf(']')
                if (close < 0) return null
                host = text.substring(0, close + 1)
                val after = text.substring(close + 1)
                portText = if (after.isEmpty()) null else if (after[0] == ':') after.substring(1) else return null
            } else {
                val colon = text.lastIndexOf(':')
                host = if (colon < 0) text else text.substring(0, colon)
                portText = if (colon < 0) null else text.substring(colon + 1)
            }
            val port = if (portText == null) defaultPort ?: return null else portOf(portText) ?: return null
            if (host.startsWith("[")) {
                val inner = host.substring(1, host.length - 1)
                val address = ipv6(inner) ?: return null
                return Authority("[" + Py.asciiLower(inner) + "]", port, address)
            }
            if (host.length > 254 || host.any { !(it in 'a'..'z' || it in 'A'..'Z' || it in '0'..'9' || it == '-' || it == '_' || it == '.') }) return null
            val name = Py.asciiLower(host.removeSuffix("."))
            val labels = name.split('.')
            if (labels.any { it.isEmpty() || it.length > 63 }) return null
            if (labels.last().all { it in '0'..'9' }) {
                if (labels.size != 4 || labels.any { it.length > 3 || !it.all { c -> c in '0'..'9' } || it.toInt() > 255 }) return null
                val address = ByteArray(4) { labels[it].toInt().toByte() }
                return Authority(labels.joinToString(".") { it.toInt().toString() }, port, address)
            }
            return Authority(name, port, null)
        }

        private fun portOf(text: String): Int? {
            if (text.isEmpty() || text.length > 5 || !text.all { it in '0'..'9' }) return null
            return text.toInt().takeIf { it in 1..65535 }
        }

        /** An IPv6 literal's 16 bytes (hex groups, one `::`, a dotted IPv4 tail), none for anything else. */
        private fun ipv6(s: String): ByteArray? {
            if (s.isEmpty() || s.any { !(it in '0'..'9' || it in 'a'..'f' || it in 'A'..'F' || it == ':' || it == '.') }) return null
            val double = s.indexOf("::")
            if (double >= 0 && s.indexOf("::", double + 1) >= 0) return null
            fun groups(part: String): List<String>? =
                if (part.isEmpty()) emptyList() else part.split(':').takeIf { g -> g.none { it.isEmpty() } }
            val head = groups(if (double >= 0) s.substring(0, double) else s) ?: return null
            val tail = if (double >= 0) groups(s.substring(double + 2)) ?: return null else emptyList()
            fun words(groups: List<String>, last: Boolean): List<Int>? {
                val out = mutableListOf<Int>()
                for ((i, g) in groups.withIndex()) {
                    if ('.' in g) {
                        if (!last || i != groups.size - 1) return null
                        val v4 = authority("$g:1", null)?.address?.takeIf { it.size == 4 } ?: return null
                        out += ((v4[0].toInt() and 255) shl 8) or (v4[1].toInt() and 255)
                        out += ((v4[2].toInt() and 255) shl 8) or (v4[3].toInt() and 255)
                    } else {
                        if (g.length > 4) return null
                        out += g.toInt(16)
                    }
                }
                return out
            }
            val first = words(head, last = double < 0) ?: return null
            val second = words(tail, last = true) ?: return null
            val missing = 8 - first.size - second.size
            if ((double < 0 && missing != 0) || (double >= 0 && missing < 1)) return null
            val all = first + List(if (double >= 0) missing else 0) { 0 } + second
            return ByteArray(16) { i -> (all[i / 2] shr (if (i % 2 == 0) 8 else 0)).toByte() }
        }
    }
}
