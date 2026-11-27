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
 * - [Mode.LOOPBACK] (tests and instrumentation): [loopbackHosts] alone (`127.0.0.1` and `10.0.2.2`, [LOOPBACK_NAMES];
 *   the kill check's gate [KILL_CHECK_HOSTS], 127.0.0.1 alone), any port, CONNECT and GET; nothing is looked up, the
 *   rule unused. [Mode.NETWORK]: the [rule], each name looked up by [resolver] only once allowed;
 *   under YOUTUBE a name that resolves to an address that isn't public ([isPublic]) is refused, and the socket is
 *   connected ([connector]) to the very address checked.
 * - `jnn-pa.googleapis.com` (and any name under it) is refused in every mode and by every rule.
 * - A refused host: 403, logged `refused` with [HostUse.why]. A wrong or missing `Proxy-Authorization`: 407 with
 *   `Proxy-Authenticate`, nothing logged. A target that isn't `host:port` (an `@`, a control character, a byte past
 *   ASCII, a bad port or IP literal): 400, logged under [MALFORMED]; a head line with a bare CR or a control character
 *   but a tab: 400. A method but CONNECT and GET: 405. An upstream that won't connect: 502, or 504 past
 *   [connectTimeoutMs]. More than [maxConnections] at once: 503.
 * - Time: a client's whole head by [headTimeoutMs] from its accept (a deadline: closed at it, with no answer); a
 *   tunnel or a relay in which nothing moves either way for [idleTimeoutMs] (a read or a write, both pumps stuck in
 *   writes too) is closed.
 * - A relayed answer's head is checked as a request's is: a control character but a tab, or a bare CR, is 502.
 * - The gate never takes its mode from a property: the main process passes it ([Mode.of] `caracole.network`'s value).
 *   The property is a guard alone: while it is `loopback` (every test, JVM or device), a [Mode.NETWORK] gate, of any
 *   rule, OBSERVE's too, is refused ([NETWORK_UNDER_LOOPBACK]) unless it names a resolver and a connector of its own
 *   (a test's, which reach loopback or nothing), never [Resolver.SYSTEM] or [Connector.DIRECT].
 * - The gates this process has open, by port and user ([isOpen]): a client hands yt-dlp no `--proxy` of a gate-shaped
 *   address that isn't one of them (another app's proxy on 127.0.0.1 never takes yt-dlp's traffic).
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
    private val connector: Connector = Connector.DIRECT,
    private val loopbackHosts: List<String> = LOOPBACK_NAMES,
) : Closeable {
    init {
        require(loopbackHosts.isNotEmpty() && loopbackHosts.all { it in LOOPBACK_NAMES }) {
            "a gate's loopback hosts are some of ${LOOPBACK_NAMES.joinToString(", ")}"
        }
        if (mode == Mode.NETWORK && System.getProperty(io.github.danielhp95.caracole.core.http.RealTransport.NETWORK) ==
            LOOPBACK_PROPERTY) {
            require(resolver !== Resolver.SYSTEM && connector !== Connector.DIRECT) { NETWORK_UNDER_LOOPBACK }
        }
    }

    /** The bytes of the hosts a [Mode.LOOPBACK] gate allows, and why another is refused. */
    private val loopbackAddresses = loopbackHosts.map { LOOPBACK_HOSTS[LOOPBACK_NAMES.indexOf(it)] }
    private val whyNotLoopback =
        if (loopbackHosts == LOOPBACK_NAMES) WHY_NOT_LOOPBACK else "not " + loopbackHosts.joinToString(" or ")

    enum class Mode {
        LOOPBACK, NETWORK;

        companion object {
            /** `loopback` (CaracoleTestRunner's and every Gradle test task's `caracole.network`) or the network. */
            fun of(network: String?): Mode = if (network == "loopback") LOOPBACK else NETWORK
        }
    }

    /**
     * Which hosts a [Mode.NETWORK] gate allows: [YOUTUBE] (the design's §3.3 list, CONNECT on 443 alone) or [OBSERVE]
     * (the bench's, set by a button press alone: every host and port, CONNECT and GET, logged, but no address that
     * isn't public, a name's or a literal's). Names are compared lowercased as ASCII with no trailing dot; an IP literal
     * never matches a name. The names, the suffixes, the port,
     * the hosts reported apart and those refused by name are youtube.py's PHONE_GATE (youtube.json's `gate`).
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
            private val data = YouTubeData.read()

            /** Refused by name whatever the rule: Google's attestation (BotGuard's `Waa`). A CONNECT hides the path. */
            val REFUSED: List<String> = data.texts("refused", data.gate)

            private val APART = data.texts("apart", data.gate).toSet()

            val YOUTUBE = HostRule(
                "YOUTUBE",
                data.texts("names", data.gate).toSet(),
                data.texts("suffixes", data.gate),
                port = data.number("port", data.gate).toInt(),
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

    /** Connects a fresh socket to an address the gate checked (tests dial loopback in its place). */
    fun interface Connector {
        fun connect(socket: Socket, address: InetSocketAddress, timeoutMs: Int)

        companion object {
            val DIRECT = Connector { socket, address, timeoutMs -> socket.connect(address, timeoutMs) }
        }
    }

    /** One host's use, keyed in [log] by its name as asked, lowercased; [apart] for a host [HostRule.reportsApart]. */
    data class HostUse(
        val connects: Int = 0,
        val bytesUp: Long = 0,
        val bytesDown: Long = 0,
        val refused: Int = 0,
        val apart: Boolean = false,
        val why: String? = null,
    )

    /**
     * A started gate: its port, and the `--proxy` value yt-dlp is given, which holds the user and the secret; and its
     * gate's [log] and [refusedAny], which a run reads before anything else (YtDlp); [close] closes its gate.
     */
    class Opened internal constructor(val port: Int, override val proxyArg: String, private val gate: HostGate) : YtDlpGate {
        override fun log(): Map<String, HostUse> = gate.log()

        fun refusedAny(): Boolean = gate.refusedAny()

        override fun close() = gate.close()

        override fun toString() = "HostGate.Opened(127.0.0.1:$port)"
    }

    private class Use(val apart: Boolean) {
        val connects = AtomicInteger()
        val up = AtomicLong()
        val down = AtomicLong()
        val refused = AtomicInteger()
        @Volatile var why: String? = null
        fun snapshot() = HostUse(connects.get(), up.get(), down.get(), refused.get(), apart, why)
    }

    /** A target as asked: [key] the log's name for it, [address] an IP literal's bytes (none for a name). */
    private class Authority(val key: String, val port: Int, val address: ByteArray?)

    private class Refusal(val status: Int, val key: String?, val why: String? = null) : Exception(null, null, false, false)

    private val uses = LinkedHashMap<String, Use>()
    private val sockets: MutableSet<Socket> = ConcurrentHashMap.newKeySet()
    private val threads: MutableSet<Thread> = ConcurrentHashMap.newKeySet()
    private val active = AtomicInteger()
    private val serial = AtomicInteger()
    @Volatile private var closed = false
    private var server: ServerSocket? = null
    private var acceptor: Thread? = null
    private var expected: ByteArray? = null
    /** This gate's key in [OPEN] while it is started and not closed. */
    private var registered: String? = null

    /** A test's seam: run first on each connection's thread (a handler that throws stands for a bug there). */
    @Volatile internal var beforeServing: (() -> Unit)? = null

    /** A test's seam: run on the acceptor's thread after each accept (a handler that throws stands for a bug there). */
    @Volatile internal var afterAccepting: (() -> Unit)? = null

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
        registered = key(port, user).also { OPEN += it }
        acceptor = spawn("caracole-gate-$port-accept") {
            try {
                accept(socket)
            } catch (t: Throwable) {
                stopped(socket)
                throw t // ends this thread alone (spawn), said nowhere
            }
        }!!
        return Opened(port, "$PROXY_SCHEME://$user:$secret@$PROXY_HOST:$port", this)
    }

    /** Each host asked for, in the order first asked; at most [LOG_HOSTS] names, the rest under [OTHER_HOSTS]. */
    fun log(): Map<String, HostUse> = synchronized(uses) { uses.mapValuesTo(LinkedHashMap()) { it.value.snapshot() } }

    /** Whether any request was refused (a host off the rule, or a malformed one). */
    fun refusedAny(): Boolean = synchronized(uses) { uses.values.any { it.refused.get() > 0 } }

    /**
     * Stops accepting, closes every open connection and tunnel, and waits for every thread of the gate to end, each
     * [JOIN_MS] at most. It never throws: an interrupt of the calling thread (set before, or coming while it waits) is
     * kept, the flag set again once every thread was waited for, so that a run already over isn't made an interrupt
     * and one whose exception is on its way keeps its interrupt too.
     */
    override fun close() {
        val toJoin: List<Thread>
        synchronized(this) {
            closed = true
            registered?.let { OPEN -= it }
            try {
                server?.close()
            } catch (_: IOException) {
            }
            toJoin = listOfNotNull(acceptor)
        }
        // No thread is spawned and no client registered once closed is set (both under this lock): the snapshot is all.
        sockets.forEach { quietly(it) }
        var interrupted = Thread.interrupted()
        for (t in toJoin + threads.toList()) {
            val until = System.nanoTime() + JOIN_MS * 1_000_000L
            while (t.isAlive) {
                val left = (until - System.nanoTime()) / 1_000_000L
                if (left <= 0) break
                try {
                    t.join(left)
                } catch (_: InterruptedException) {
                    interrupted = true
                }
            }
        }
        threads.removeIf { !it.isAlive }
        if (interrupted) Thread.currentThread().interrupt()
    }

    /** The acceptor's body threw (a bug of the gate's own): it accepts nothing more, its socket is closed so that a
     * client is refused at once rather than left waiting, and its log lists `gate.stopped` (no secret, no request's
     * words), which a run reads first ([YtDlp]). */
    private fun stopped(socket: ServerSocket) {
        if (closed) return
        synchronized(uses) { uses.getOrPut(STOPPED) { Use(apart = false) } }
        try {
            socket.close()
        } catch (_: IOException) {
        }
    }

    override fun toString() = "HostGate($mode, $rule, ${server?.localPort ?: "not started"})"

    private fun accept(socket: ServerSocket) {
        while (!closed) {
            val client = try {
                socket.accept()
            } catch (_: IOException) {
                break
            }
            val acceptedAt = System.nanoTime()
            try {
                afterAccepting?.invoke()
            } catch (t: Throwable) {
                quietly(client)
                throw t
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
            val started = synchronized(this) {
                if (closed) return@synchronized false
                sockets += client
                spawn("caracole-gate-${socket.localPort}-${serial.incrementAndGet()}") {
                    try {
                        serve(client, acceptedAt)
                    } finally {
                        quietly(client)
                        sockets -= client
                        active.decrementAndGet()
                    }
                } != null
            }
            if (!started) {
                quietly(client)
                active.decrementAndGet()
                break
            }
        }
    }

    /**
     * One client: its head read by [headTimeoutMs] from [acceptedAt] (a deadline, not a timeout a read: a client that
     * trickles is closed at it, with no answer), then its request.
     */
    private fun serve(client: Socket, acceptedAt: Long) {
        beforeServing?.invoke()
        val (input, output) = try {
            BufferedInputStream(client.getInputStream()) to client.getOutputStream()
        } catch (_: IOException) {
            return // closed by close() before it began
        }
        try {
            val head = try {
                readHead(input, client, acceptedAt + headTimeoutMs * 1_000_000L, overflow = 400) ?: return
            } catch (_: SocketTimeoutException) {
                return
            }
            if (badHead(head)) throw Refusal(400, null)
            val lines = head.split('\n').map { it.removeSuffix("\r") }.dropLast(2)
            if (lines.any { '\r' in it }) throw Refusal(400, null)
            val parts = lines.firstOrNull()?.split(' ') ?: throw Refusal(400, null)
            if (parts.size != 3 || parts[2] !in VERSIONS) throw Refusal(400, null)
            val headers = lines.drop(1).map { line ->
                val colon = line.indexOf(':')
                if (colon <= 0 || line[0] == ' ' || line[0] == '\t' || ' ' in line.substring(0, colon)) throw Refusal(400, null)
                line.substring(0, colon) to spaced(line.substring(colon + 1))
            }
            if (!authorized(headers)) throw Refusal(407, null)
            val (method, target) = parts
            if (target.any { it.code < 0x21 || it.code > 0x7e }) throw Refusal(400, MALFORMED, WHY_MALFORMED)
            when (method) {
                "CONNECT" -> tunnel(client, input, output,
                                    authority(target, defaultPort = null) ?: throw Refusal(400, MALFORMED, WHY_MALFORMED))
                "GET" -> relay(client, output, target, headers)
                else -> throw Refusal(405, MALFORMED, WHY_METHOD)
            }
        } catch (r: Refusal) {
            if (r.key != null) use(r.key).let { it.refused.incrementAndGet(); if (r.why != null) it.why = r.why }
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

    /**
     * A plain GET in origin-form, its Host the URL's authority (RFC 9112 §3.2.2), the hop-by-hop headers dropped and
     * `Connection: close`; the answer relayed as it comes, less the same. An upstream that closes before its head, or
     * sends one past [HEAD_MAX], is 502; one silent past [idleTimeoutMs] before its head, 504.
     */
    private fun relay(client: Socket, output: OutputStream, target: String, headers: List<Pair<String, String>>) {
        if (target.length < 7 || Py.asciiLower(target.substring(0, 7)) != "http://") throw Refusal(400, MALFORMED, WHY_MALFORMED)
        val rest = target.substring(7)
        val end = rest.indexOfFirst { it == '/' || it == '?' }.let { if (it < 0) rest.length else it }
        if ('#' in rest) throw Refusal(400, MALFORMED, WHY_MALFORMED)
        val authorityText = rest.substring(0, end)
        val at = authority(authorityText, defaultPort = 80) ?: throw Refusal(400, MALFORMED, WHY_MALFORMED)
        val path = rest.substring(end).let { if (it.isEmpty() || it[0] == '?') "/$it" else it }
        for ((name, value) in headers) {
            val lower = Py.asciiLower(name)
            if (lower == "transfer-encoding" || (lower == "content-length" && value != "0")) {
                throw Refusal(400, at.key, "a GET with a body")
            }
        }
        val use = allowed(at, connect = false)
        val upstream = open(at)
        try {
            use.connects.incrementAndGet()
            val sent = buildString {
                append("GET ").append(path).append(' ').append("HTTP/1.1\r\n")
                append("Host: ").append(authorityText).append("\r\n")
                for ((name, value) in withoutHopByHop(headers)) {
                    if (Py.asciiLower(name) != "host") append(name).append(": ").append(value).append("\r\n")
                }
                append("Connection: close\r\n\r\n")
            }.toByteArray(Charsets.ISO_8859_1)
            upstream.getOutputStream().write(sent)
            upstream.getOutputStream().flush()
            use.up.addAndGet(sent.size.toLong())
            val fromUpstream = BufferedInputStream(upstream.getInputStream())
            val answer = try {
                readHead(fromUpstream, upstream, System.nanoTime() + idleTimeoutMs * 1_000_000L, overflow = 502)
            } catch (_: SocketTimeoutException) {
                throw Refusal(504, null)
            } ?: throw Refusal(502, null)
            if (badHead(answer)) throw Refusal(502, null)
            val lines = answer.split('\n').map { it.removeSuffix("\r") }.dropLast(2)
            if (lines.any { '\r' in it }) throw Refusal(502, null)
            val answerHeaders = lines.drop(1).mapNotNull { line ->
                val colon = line.indexOf(':')
                if (colon <= 0) null else line.substring(0, colon) to spaced(line.substring(colon + 1))
            }
            val back = buildString {
                append(lines.first()).append("\r\n")
                for ((name, value) in withoutHopByHop(answerHeaders)) append(name).append(": ").append(value).append("\r\n")
                append("Connection: close\r\n\r\n")
            }.toByteArray(Charsets.ISO_8859_1)
            val activity = AtomicLong(System.nanoTime())
            val stop = { quietly(client); quietly(upstream) }
            val down = spawn("caracole-gate-${server?.localPort}-${serial.incrementAndGet()}-down") {
                try {
                    output.write(back)
                    output.flush()
                    use.down.addAndGet(back.size.toLong())
                    activity.set(System.nanoTime())
                    pump(fromUpstream, output, upstream, use.down, activity, stop)
                    client.shutdownOutput()
                } catch (_: IOException) {
                }
            } ?: throw IOException("closed")
            awaitOrStop(listOf(down), activity, stop)
        } finally {
            quietly(upstream)
            sockets -= upstream
        }
    }

    /** The log's entry for [at] once the mode and the rule allow it, else a 403 refusal. */
    private fun allowed(at: Authority, connect: Boolean): Use {
        val why = when {
            HostRule.refusedByName(at.key) -> WHY_BY_NAME
            mode == Mode.LOOPBACK ->
                if (at.address != null && loopbackAddresses.any { it.contentEquals(at.address) }) null else whyNotLoopback
            at.address != null ->
                if (rule !== HostRule.OBSERVE) WHY_LITERAL
                else if (isPublic(InetAddress.getByAddress(at.address))) null else WHY_NOT_PUBLIC
            else -> if (rule.allows(at.key, at.port, connect)) null else WHY_OFF_RULE
        }
        if (why != null) throw Refusal(403, at.key, why)
        return use(at.key)
    }

    /**
     * The upstream, connected: an IP literal as given, a name through [resolver] (in [Mode.NETWORK] alone). Under
     * every rule, OBSERVE's too, a name that resolves to an address that isn't public ([isPublic]) is refused, every
     * address checked (an observed session reaches no LAN or local service either); the socket is connected to the very
     * address checked, never looked up again.
     */
    private fun open(at: Authority): Socket {
        val addresses = if (at.address != null) {
            listOf(InetSocketAddress(InetAddress.getByAddress(at.address), at.port))
        } else {
            check(mode == Mode.NETWORK)
            val resolved = try {
                resolver.resolve(at.key, at.port)
            } catch (_: IOException) {
                throw Refusal(502, null)
            }
            for (address in resolved) {
                val ip = address.address
                if (ip == null || !isPublic(ip)) {
                    throw Refusal(403, at.key, "resolves to ${ip?.hostAddress ?: "an unresolved address"}, not a public address")
                }
            }
            resolved
        }
        var timedOut = false
        for (address in addresses) {
            val socket = Socket()
            sockets += socket
            if (closed) quietly(socket)
            if (address.isUnresolved) {
                quietly(socket)
                sockets -= socket
                continue
            }
            try {
                connector.connect(socket, address, connectTimeoutMs)
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

    /**
     * Client to upstream and upstream to client, each on a thread of its own, watched from here from the start, until
     * either ends or nothing moves either way: both pumps stuck in writes at once are cut too.
     */
    private fun pumpBoth(client: Socket, input: InputStream, upstream: Socket, use: Use) {
        val activity = AtomicLong(System.nanoTime())
        val stop = { quietly(client); quietly(upstream) }
        val down = spawn("caracole-gate-${server?.localPort}-${serial.incrementAndGet()}-down") {
            try {
                pump(upstream.getInputStream(), client.getOutputStream(), upstream, use.down, activity, stop)
            } catch (_: IOException) {
            } finally {
                stop()
            }
        } ?: throw IOException("closed")
        val up = spawn("caracole-gate-${server?.localPort}-${serial.incrementAndGet()}-up") {
            var ended = false
            try {
                pump(input, upstream.getOutputStream(), client, use.up, activity, stop)
                upstream.shutdownOutput()
                ended = true
            } catch (_: IOException) {
            } finally {
                if (!ended) stop()
            }
        }
        if (up == null) {
            stop()
            down.join(JOIN_MS)
            throw IOException("closed")
        }
        awaitOrStop(listOf(up, down), activity, stop)
    }

    /**
     * Waits for every one of [pumping] to end, and [stop]s them once nothing moved either way for [idleTimeoutMs]: a
     * pump blocked in a write (a peer that half-closed and stopped reading) is cut so, as a write has no timeout of
     * its own.
     */
    private fun awaitOrStop(pumping: List<Thread>, activity: AtomicLong, stop: () -> Unit) {
        val tick = minOf(idleTimeoutMs, TICK_MS).toLong()
        while (true) {
            val alive = pumping.firstOrNull { it.isAlive } ?: break // one snapshot: none alive between two reads is the end
            alive.join(tick)
            if (pumping.any { it.isAlive } && System.nanoTime() - activity.get() > idleTimeoutMs * 1_000_000L) stop()
        }
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
            val named = uses.keys.count { it != OTHER_HOSTS && it != MALFORMED && it != STOPPED }
            if (key != MALFORMED && named >= LOG_HOSTS) uses.getOrPut(OTHER_HOSTS) { Use(apart = false) }
            else Use(rule.reportsApart(key)).also { uses[key] = it }
        }
    }

    /**
     * A daemon thread of the gate, or none once closed (under the lock [close] sets `closed` under). Whatever its
     * [body] throws ends that thread alone, said nowhere (it may hold a request's words): no bug on a connection's
     * thread reaches the default handler, which on Android ends the app's main process, where the gate runs. Each body
     * closes its own sockets in its `finally` (serve's client, a pump's [stop]).
     */
    @Synchronized
    private fun spawn(name: String, body: () -> Unit): Thread? {
        if (closed) return null
        threads.removeIf { !it.isAlive }
        val t = Thread({
            try {
                body()
            } catch (_: Throwable) {
            }
        }, name)
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
        /** The log's names that are no host's: youtube.json's `gate.other_hosts` and `gate.malformed`. */
        val OTHER_HOSTS: String by lazy { YouTubeData.read().text("other_hosts", YouTubeData.read().gate) }
        val MALFORMED: String by lazy { YouTubeData.read().text("malformed", YouTubeData.read().gate) }
        /** Listed once the acceptor stopped by a bug of the gate's own: youtube.json's `gate.stopped`. */
        val STOPPED: String by lazy { YouTubeData.read().text("stopped", YouTubeData.read().gate) }

        /** Why a host was refused, its log's [HostUse.why] (the last refusal's). */
        const val WHY_BY_NAME = "refused by name"
        const val WHY_OFF_RULE = "off the rule"
        const val WHY_NOT_LOOPBACK = "not 127.0.0.1 or 10.0.2.2"
        const val WHY_LITERAL = "an IP literal"
        const val WHY_NOT_PUBLIC = "an IP literal that isn't a public address"
        const val WHY_MALFORMED = "malformed"
        const val WHY_METHOD = "not CONNECT or GET"

        /** The scheme and host of every [Opened.proxyArg]: the gate listens on 127.0.0.1 alone. */
        const val PROXY_SCHEME = "http"
        const val PROXY_HOST = "127.0.0.1"

        /** The hosts a [Mode.LOOPBACK] gate allows, as a target names them (LOOPBACK_HOSTS's bytes). */
        val LOOPBACK_NAMES: List<String> = listOf("127.0.0.1", "10.0.2.2")

        /** The kill check's gate's hosts (on the owner's phone too): 127.0.0.1 alone, never 10.0.2.2, the emulator's
         * host, which is a routable private address on some real networks. */
        val KILL_CHECK_HOSTS: List<String> = listOf("127.0.0.1")

        /** [Opened.proxyArg]'s shape, a Python regex matched whole (`re.fullmatch`): the gate's scheme, a user and a
         * secret of [TOKEN_BYTES] random bytes in lowercase hex each, its host and a port. What `:youtube`'s glue holds
         * a `--proxy` to. */
        val PROXY_PATTERN: String = "$PROXY_SCHEME://[0-9a-f]{${2 * TOKEN_BYTES}}:[0-9a-f]{${2 * TOKEN_BYTES}}@" +
            PROXY_HOST.replace(".", "\\.") + ":[0-9]{1,5}"

        /** The user's and the secret's random bytes. */
        const val TOKEN_BYTES = 16

        /** `caracole.network`'s value under every test runner and Gradle test task. */
        const val LOOPBACK_PROPERTY = "loopback"

        /** Why a [Mode.NETWORK] gate isn't made while `caracole.network` is `loopback`. */
        const val NETWORK_UNDER_LOOPBACK = "no gate to the network while caracole.network is loopback (a test's gate " +
            "names a resolver and a connector of its own)"

        /** The open gates of this process, each by its port and user: started, not yet closed. */
        private val OPEN: MutableSet<String> = ConcurrentHashMap.newKeySet()

        private fun key(port: Int, user: String) = "$port:$user"

        /** Whether [port] and [user] are those of a gate of this process that is open now. */
        fun isOpen(port: Int, user: String): Boolean = key(port, user) in OPEN

        /** [proxy]'s port and user, for an address of [PROXY_PATTERN]'s shape whole; else null. */
        fun portAndUser(proxy: String): Pair<Int, String>? {
            if (!Regex(PROXY_PATTERN).matches(proxy)) return null
            val port = proxy.substringAfterLast(':').toIntOrNull() ?: return null
            return port to proxy.substringAfter("://").substringBefore(':')
        }

        /** Whether [proxy] is the `--proxy` of a gate of this process that is open now ([Opened.proxyArg]'s shape, its
         * port and user an open gate's). The secret isn't compared: a gate keeps only its digest. */
        fun isOpen(proxy: String): Boolean = portAndUser(proxy)?.let { (port, user) -> isOpen(port, user) } ?: false

        /**
         * Whether [ip] is a public address: not loopback, any-local, link-local, site-local or multicast (the JDK's
         * checks), nor 0.0.0.0/8, 100.64.0.0/10 (shared, CGNAT), 255.255.255.255, fc00::/7 (unique local), nor an
         * IPv4-mapped (::ffff:0:0/96) or IPv4-compatible (::/96) IPv6 address of one of those.
         */
        fun isPublic(ip: InetAddress): Boolean {
            val b = ip.address
            if (b.size == 16) {
                val v4Tail = (0 until 10).all { b[it] == 0.toByte() } &&
                    ((b[10] == 0xff.toByte() && b[11] == 0xff.toByte()) || (b[10] == 0.toByte() && b[11] == 0.toByte()))
                if (v4Tail && !(b[10] == 0.toByte() && (12 until 15).all { b[it] == 0.toByte() } && (b[15].toInt() and 0xff) < 2)) {
                    return isPublic(InetAddress.getByAddress(b.copyOfRange(12, 16)))
                }
                if ((b[0].toInt() and 0xfe) == 0xfc) return false
            } else {
                val first = b[0].toInt() and 0xff
                val second = b[1].toInt() and 0xff
                if (first == 0 || (first == 100 && second in 64..127) || b.all { it == 0xff.toByte() }) return false
            }
            return !(ip.isLoopbackAddress || ip.isAnyLocalAddress || ip.isLinkLocalAddress || ip.isSiteLocalAddress ||
                ip.isMulticastAddress)
        }

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
            val bytes = ByteArray(TOKEN_BYTES)
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

        /** Whether a head holds a control character but a tab, a CR and an LF (a bare CR is the line check's). */
        private fun badHead(head: String): Boolean =
            head.any { (it.code < 0x20 && it != '\t' && it != '\r' && it != '\n') || it.code == 0x7f }

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

        /**
         * A head to its blank line, as Latin-1 (each byte one char); none at an end before it; [overflow] past
         * [HEAD_MAX]; SocketTimeoutException at [deadline] (System.nanoTime), each read given the time left.
         */
        private fun readHead(input: InputStream, socket: Socket, deadline: Long, overflow: Int): String? {
            val out = ByteArrayOutputStream()
            var last = -1
            var beforeLast = -1
            while (true) {
                val left = (deadline - System.nanoTime()) / 1_000_000L
                if (left <= 0) throw SocketTimeoutException("past the head's deadline")
                socket.soTimeout = minOf(left, Int.MAX_VALUE.toLong()).toInt()
                val b = input.read()
                if (b < 0) return null
                out.write(b)
                if (out.size() > HEAD_MAX) throw Refusal(overflow, null)
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
