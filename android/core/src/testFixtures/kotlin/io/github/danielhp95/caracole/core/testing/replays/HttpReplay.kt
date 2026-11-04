package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.http.Event
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.HttpRequest
import io.github.danielhp95.caracole.core.http.HttpRules
import io.github.danielhp95.caracole.core.http.HttpxUrl
import io.github.danielhp95.caracole.core.http.PoliteClient
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.http.Response
import io.github.danielhp95.caracole.core.http.Robots
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.http.TransportError
import io.github.danielhp95.caracole.core.http.UrlError
import io.github.danielhp95.caracole.core.http.Urls
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Scenarios
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.nio.file.Files
import java.time.Duration
import java.time.Instant
import java.util.Base64
import java.util.zip.GZIPInputStream

/**
 * core.http (vectors/http/, lane http-client): httpx's URLs, robots.txt's rules, http.py's rules of an answer, every
 * scripted session of a PoliteClient, and the scenario helper's records, each answered by :core as Python answered
 * it: the JVM's tests' loops, run on the device by CorpusOnDeviceTest. tests/test_conformance_http.py says each
 * vector's form.
 */
object HttpReplay : AreaReplay {
    override val area = "http"

    override fun replay(misses: Misses) {
        urls(misses)
        robots(misses)
        rules(misses)
        sessions(misses)
        scenarioHelper(misses)
    }

    // --- how the vectors carry strings and bodies ---------------------------------------------------------

    /** A string the corpus carries: itself, or `{"parts": [...]}` (a repeat, a UTF-16 unit). */
    fun str(e: JsonElement): String {
        if (e is JsonPrimitive) return e.content
        val parts = e.jsonObject.getValue("parts").jsonArray
        return buildString {
            for (p in parts) {
                when {
                    p is JsonPrimitive -> append(p.content)
                    "repeat" in p.jsonObject -> repeat(p.jsonObject.getValue("times").jsonPrimitive.int) {
                        append(p.jsonObject.getValue("repeat").jsonPrimitive.content)
                    }
                    "utf16" in p.jsonObject -> p.jsonObject.getValue("utf16").jsonArray.forEach { append(it.jsonPrimitive.int.toChar()) }
                    else -> throw AssertionError("not a part: $p")
                }
            }
        }
    }

    /** A body the corpus carries. */
    fun body(e: JsonElement): ByteArray {
        val o = e.jsonObject
        return when {
            "text" in o -> o.getValue("text").jsonPrimitive.content.toByteArray(Charsets.UTF_8)
            "base64" in o -> Base64.getDecoder().decode(o.getValue("base64").jsonPrimitive.content)
            "repeat" in o -> {
                val unit = o.getValue("repeat").jsonPrimitive.content.toByteArray(Charsets.UTF_8)
                val times = o.getValue("times").jsonPrimitive.int
                ByteArray(unit.size * times).also { out -> for (i in 0 until times) System.arraycopy(unit, 0, out, i * unit.size, unit.size) }
            }
            "parts" in o -> o.getValue("parts").jsonArray.map { body(it) }.fold(ByteArray(0)) { a, b -> a + b }
            "fixture" in o -> Corpus.fixture(o.getValue("fixture").jsonPrimitive.content)
            else -> throw AssertionError("not a body: $e")
        }
    }

    /** A body as a session's outcome carries it: itself up to 4 KiB, else its digest and size. */
    fun bodyOut(b: ByteArray): JsonElement {
        if (b.size > 4096) return JsonObject(mapOf("sha256" to JsonPrimitive(Scenarios.sha256(b)), "size" to JsonPrimitive(b.size)))
        val text = PyText.utf8(b)
        return if (text != null) JsonObject(mapOf("text" to JsonPrimitive(text)))
               else JsonObject(mapOf("base64" to JsonPrimitive(Base64.getEncoder().encodeToString(b))))
    }

    private fun err(e: UrlError) = JsonObject(mapOf("err" to JsonPrimitive("${e.kind}: ${e.message}")))

    private fun same(got: Any?, want: JsonElement?): Boolean = when {
        want == null || want is JsonNull -> got == null
        want is JsonObject && "err" in want -> got is JsonObject && got == want
        want is JsonPrimitive && want.isString -> got is String && got == want.content
        want is JsonObject && "parts" in want -> got is String && got == str(want)
        else -> false
    }

    // --- urls.jsonl ---------------------------------------------------------------------------------------

    fun urls(misses: Misses) {
        for (r in Corpus.records("http/urls.jsonl")) {
            when (r.fn) {
                "url" -> {
                    val url = str(r.args[0])
                    val want = r.out!!.jsonObject
                    val u = try {
                        HttpxUrl.parse(url)
                    } catch (e: UrlError) {
                        misses.check(err(e) == want) { "url(${url.take(120)}) refused: ${err(e)}, Python's $want" }
                        continue
                    }
                    if ("err" in want) {
                        misses.check(false) { "url(${url.take(120)}) = $u, Python refused it: $want" }
                        continue
                    }
                    misses.check(u.toString() == str(want.getValue("str"))) { "str(${url.take(120)}) = ${u.toString().take(200)}, Python's ${want["str"]}" }
                    misses.check(u.rawPath == str(want.getValue("raw_path"))) { "raw_path(${url.take(120)}) = ${u.rawPath.take(200)}, Python's ${want["raw_path"]}" }
                    misses.check(u.netloc == want.getValue("netloc").jsonPrimitive.content) { "netloc(${url.take(120)}) = ${u.netloc}, Python's ${want["netloc"]}" }
                    misses.check(u.isAbsolute == want.getValue("absolute").jsonPrimitive.boolean) { "absolute(${url.take(120)}) = ${u.isAbsolute}" }
                    misses.check(u.scheme == want.getValue("scheme").jsonPrimitive.content) { "scheme(${url.take(120)}) = ${u.scheme}" }
                    val port = want.getValue("port")
                    misses.check((u.port?.toString()) == (if (port is JsonNull) null else port.jsonPrimitive.content)) {
                        "port(${url.take(120)}) = ${u.port}, Python's $port"
                    }
                    val host: Any = try { u.decodedHost } catch (e: UrlError) { err(e) }
                    misses.check(same(host, want["host"])) { "host(${url.take(120)}) = $host, Python's ${want["host"]}" }
                    val site: Any = try { Urls.site(url) } catch (e: UrlError) { err(e) }
                    misses.check(same(site, want["site"])) { "site(${url.take(120)}) = $site, Python's ${want["site"]}" }
                }
                "with_params" -> {
                    val url = str(r.args[0])
                    val params = r.args[1].jsonArray.map { p -> str(p.jsonArray[0]) to str(p.jsonArray[1]) }
                    val got: Any = try { Urls.withParams(url, params) } catch (e: UrlError) { err(e) }
                    misses.check(same(got, r.out)) { "with_params(${url.take(120)}, $params) = $got, Python's ${r.out}" }
                }
                "resolve" -> {
                    val base = str(r.args[0])
                    val location = str(r.args[1])
                    val got: Any = try { Urls.resolve(base, location) } catch (e: UrlError) { err(e) }
                    misses.check(same(got, r.out)) { "resolve($base, $location) = $got, Python's ${r.out}" }
                }
                else -> misses.check(false) { "urls.jsonl: no function ${r.fn}" }
            }
        }
    }

    // --- robots.jsonl -------------------------------------------------------------------------------------

    fun robots(misses: Misses) {
        for (r in Corpus.records("http/robots.jsonl")) {
            val url = str(r.args[0])
            val got = Robots.disallows(url)
            val want = r.out?.takeUnless { it is JsonNull }?.jsonPrimitive?.content
            misses.check(got == want) { "robots_disallows(${url.take(160)}) = $got, Python's $want" }
        }
    }

    // --- rules.jsonl --------------------------------------------------------------------------------------

    private fun headers(e: JsonElement): Map<String, String> =
        e.jsonArray.associateTo(LinkedHashMap()) { h -> h.jsonArray[0].jsonPrimitive.content to h.jsonArray[1].jsonPrimitive.content }

    fun rules(misses: Misses) {
        for (r in Corpus.records("http/rules.jsonl")) {
            when (r.fn) {
                "stale" -> {
                    val fetched = r.args[1].takeUnless { it is JsonNull }?.jsonPrimitive?.content
                    val resp = Response("https://x.test/page", 200, "page".toByteArray(), emptyMap(),
                                        fromCache = r.args[0].jsonPrimitive.boolean, fetchedAt = fetched)
                    val got = HttpRules.stale(resp, Instant.parse(r.args[2].jsonPrimitive.content),
                                              Duration.ofSeconds(r.args[3].jsonPrimitive.long))
                    misses.check(got == r.out!!.jsonPrimitive.boolean) { "stale${r.args} = $got, Python's ${r.out}" }
                }
                "retry_after" -> {
                    val got = HttpRules.retryAfter(headers(r.args[0]), Instant.parse(r.args[1].jsonPrimitive.content))
                    val want = r.out?.takeUnless { it is JsonNull }?.jsonPrimitive?.double
                    misses.check(got == want) { "retry_after${r.args} = $got, Python's $want" }
                }
                "is_challenge" -> {
                    val got = HttpRules.isChallenge(headers(r.args[0]), body(r.args[1]))
                    misses.check(got == r.out!!.jsonPrimitive.boolean) { "is_challenge(${r.args.toString().take(160)}) = $got, Python's ${r.out}" }
                }
                else -> misses.check(false) { "rules.jsonl: no function ${r.fn}" }
            }
        }
    }

    // --- client.jsonl: sessions ---------------------------------------------------------------------------

    /** tests/test_http.py's readers' errors. */
    class Unreadable(provider: String, url: String?, status: Int?, msg: String?) : ProviderError(provider, url, status, msg)
    class PageGone(provider: String, url: String?, status: Int?, msg: String?) : ProviderError(provider, url, status, msg)

    private val NOTICE = "<html>Maintenance</html>".toByteArray()

    private fun words(resp: Response): String? {
        if (resp.content.contentEquals(NOTICE)) throw Unreadable("ug", resp.url, resp.status, "a notice, not the page")
        return if (resp.status == 404) null else resp.text
    }

    /** The site of a session: each request answered by the next of the record's answers, in turn. */
    private class Scripted(private val answers: List<JsonObject>) : Transport {
        val sent = ArrayList<HttpRequest>()

        override fun send(request: HttpRequest): HttpAnswer {
            sent += request
            val a = answers.getOrNull(sent.size - 1) ?: throw TransportError("unanswered", "Python sent no request ${sent.size}: ${request.url}")
            a["raise"]?.let { throw TransportError(it.jsonPrimitive.content, a.getValue("message").jsonPrimitive.content) }
            return HttpAnswer(a.getValue("status").jsonPrimitive.int,
                              a.getValue("headers").jsonArray.map { h -> h.jsonArray[0].jsonPrimitive.content to h.jsonArray[1].jsonPrimitive.content },
                              body(a.getValue("body")))
        }
    }

    private class Drawn(private val us: List<Double>) : Draws {
        var taken = 0

        override fun uniform(low: Double, high: Double): Double {
            val u = us[taken % us.size]
            taken++
            return low + (high - low) * u
        }
    }

    private fun response(r: Response): JsonObject = JsonObject(mapOf(
        "url" to JsonPrimitive(r.url), "status" to JsonPrimitive(r.status), "content" to bodyOut(r.content),
        "headers" to JsonArray(r.headers.map { (k, v) -> JsonArray(listOf(JsonPrimitive(k), JsonPrimitive(v))) }),
        "from_cache" to JsonPrimitive(r.fromCache), "fetched_at" to (r.fetchedAt?.let { JsonPrimitive(it) } ?: JsonNull),
    ))

    private fun raised(e: Exception): JsonObject {
        val status = (e as? ProviderError)?.status
        val url = (e as? ProviderError)?.url
        return JsonObject(mapOf("raises" to JsonObject(mapOf(
            "type" to JsonPrimitive(e::class.simpleName), "message" to JsonPrimitive(e.message),
            "status" to (status?.let { JsonPrimitive(it) } ?: JsonNull), "url" to (url?.let { JsonPrimitive(it) } ?: JsonNull),
        ))))
    }

    /** A step's outcome as Python wrote it: its strings, a corpus string, compared as text. */
    private fun normalized(e: JsonElement?): JsonElement? = when (e) {
        null -> null
        is JsonObject -> if ("parts" in e && e.size == 1) JsonPrimitive(str(e)) else JsonObject(e.mapValues { normalized(it.value)!! })
        is JsonArray -> JsonArray(e.map { normalized(it)!! })
        else -> e
    }

    private fun accept(e: JsonElement): Set<Int> = e.jsonArray.map { it.jsonPrimitive.int }.toSet()

    private fun params(e: JsonElement?): List<Pair<String, String>>? =
        if (e == null || e is JsonNull) null else e.jsonArray.map { p -> str(p.jsonArray[0]) to str(p.jsonArray[1]) }

    fun sessions(misses: Misses) {
        for (r in Corpus.records("http/client.jsonl")) session(r.extra, r.out!!.jsonObject, misses)
    }

    private fun session(record: JsonObject, out: JsonObject, misses: Misses) {
        val case = record.getValue("case").jsonPrimitive.content
        val dir = Files.createTempDirectory("caracole-http").toFile()
        try {
            val cacheDir = File(dir, "cache")
            val transport = Scripted(record.getValue("answers").jsonArray.map { it.jsonObject })
            val draws = Drawn(record.getValue("draws").jsonArray.map { it.jsonPrimitive.double })
            val sleeps = ArrayList<Double>()
            val events = ArrayList<Event>()
            var clock = 0.0
            val advances = record.getValue("clock").jsonPrimitive.content == "sleeps"
            var wall = Instant.parse(record.getValue("wall").jsonPrimitive.content)
            val provider = record.getValue("provider").jsonPrimitive.content
            val policy = record.getValue("policy").jsonObject
            var budget = policy.getValue("budget").jsonPrimitive.long
            var delay = policy.getValue("delay").jsonArray.let { it[0].jsonPrimitive.double to it[1].jsonPrimitive.double }
            var maxErrors = record.getValue("max_errors").jsonPrimitive.int
            fun make() = PoliteClient(provider, ProviderPolicy(budget = budget, delay = delay), cacheDir,
                                      record.getValue("user_agent").jsonPrimitive.content, transport,
                                      sleep = { s -> sleeps += s; if (advances) clock += s }, draws = draws,
                                      onEvent = { events += it }, maxConsecutiveErrors = maxErrors,
                                      monotonic = { clock }, wallClock = { wall })
            var client = make()
            val results = ArrayList<JsonElement>()
            for (stepElement in record.getValue("steps").jsonArray) {
                val step = stepElement.jsonObject
                val op = step.getValue("op").jsonPrimitive.content
                fun get(s: JsonObject, url: String): Response = client.get(
                    url, params = params(s["params"]), cache = s.getValue("cache").jsonPrimitive.boolean,
                    conditional = s.getValue("conditional").jsonPrimitive.boolean, accept = accept(s.getValue("accept")),
                    maxAge = s["max_age"]?.takeUnless { it is JsonNull }?.let { Duration.ofSeconds(it.jsonPrimitive.long) })
                try {
                    results += when (op) {
                        "get" -> JsonObject(mapOf("response" to response(get(step, str(step.getValue("url"))))))
                        "has_cached" -> JsonObject(mapOf("value" to JsonPrimitive(client.hasCached(str(step.getValue("url")), accept(step.getValue("accept"))))))
                        "cached" -> JsonObject(mapOf("value" to (client.cached(str(step.getValue("url")), accept(step.getValue("accept")))?.let { response(it) } ?: JsonNull)))
                        "requests_made" -> JsonObject(mapOf("value" to JsonPrimitive(client.requestsMade)))
                        "client" -> {
                            step["budget"]?.let { budget = it.jsonPrimitive.long }
                            step["delay"]?.let { d -> delay = d.jsonArray[0].jsonPrimitive.double to d.jsonArray[1].jsonPrimitive.double }
                            step["max_errors"]?.let { maxErrors = it.jsonPrimitive.int }
                            client.close()
                            client = make()
                            JsonNull
                        }
                        "wall" -> { wall = Instant.parse(step.getValue("at").jsonPrimitive.content); JsonNull }
                        "clock" -> { clock = step.getValue("at").jsonPrimitive.double; JsonNull }
                        "unlink_bodies" -> { cacheDir.walkTopDown().filter { it.name.endsWith(".body") }.toList().forEach { it.delete() }; JsonNull }
                        "corrupt_bodies" -> { cacheDir.walkTopDown().filter { it.name.endsWith(".body") }.toList().forEach { it.writeBytes("not gzip".toByteArray()) }; JsonNull }
                        "read_once_more" -> {
                            val url = str(step.getValue("url"))
                            val fetched = step["fetched"]?.takeUnless { it is JsonNull }?.jsonArray?.map { it.jsonPrimitive.content }?.toMutableSet()
                            val kind = step.getValue("unreadable").jsonPrimitive.content
                            val again = step.getValue("again").jsonObject
                            val first = get(step.getValue("get").jsonObject, url)
                            val fetchedOut = { fetched?.sorted()?.let { JsonArray(it.map { u -> JsonPrimitive(u) }) } ?: JsonNull }
                            try {
                                val value = HttpRules.readOnceMore(client, first, url, { e -> if (kind == "Unreadable") e is Unreadable else e is PageGone },
                                                                   fetched, accept(again.getValue("accept")), params(again["params"])) { words(it) }
                                JsonObject(mapOf("value" to (value?.let { JsonPrimitive(it) } ?: JsonNull), "fetched" to fetchedOut()))
                            } catch (e: ProviderError) {
                                JsonObject(raised(e) + mapOf("fetched" to fetchedOut()))
                            }
                        }
                        else -> throw AssertionError("$case: no step $op")
                    }
                } catch (e: ProviderError) {
                    results += raised(e)
                } catch (e: BudgetExhausted) {
                    results += raised(e)
                }
            }
            client.close()
            val wantSteps = normalized(out.getValue("steps"))!!.jsonArray
            for ((i, got) in results.withIndex()) {
                misses.check(got == wantSteps.getOrNull(i)) { "$case: step $i came to $got, Python's ${wantSteps.getOrNull(i)}" }
            }
            misses.check(results.size == wantSteps.size) { "$case: ${results.size} steps, Python ${wantSteps.size}" }
            val requests = JsonArray(transport.sent.map { q ->
                JsonArray(listOf(JsonPrimitive(q.method), JsonPrimitive(q.url),
                                 JsonArray(q.headers.map { (k, v) -> JsonArray(listOf(JsonPrimitive(k), JsonPrimitive(v))) })))
            })
            misses.check(requests == normalized(out.getValue("requests"))) { "$case: sent $requests, Python ${out["requests"]}" }
            val gotEvents = JsonArray(events.map { e ->
                JsonArray(listOf(JsonPrimitive(e.provider), JsonPrimitive(e.url), e.status?.let { JsonPrimitive(it) } ?: JsonNull,
                                 JsonPrimitive(e.decision), e.message?.let { JsonPrimitive(it) } ?: JsonNull))
            })
            misses.check(gotEvents == normalized(out.getValue("events"))) { "$case: events $gotEvents, Python's ${out["events"]}" }
            val wantSleeps = out.getValue("sleeps").jsonArray.map { it.jsonPrimitive.double }
            misses.check(sleeps == wantSleeps) { "$case: slept $sleeps, Python $wantSleeps" }
            misses.check(draws.taken == out.getValue("draws_taken").jsonPrimitive.int) { "$case: ${draws.taken} draws, Python ${out["draws_taken"]}" }
            val left = cacheLeft(cacheDir)
            misses.check(left == out.getValue("cache")) { "$case: the cache holds $left, Python's ${out["cache"]}" }
        } finally {
            dir.deleteRecursively()
        }
    }

    /** What the cache holds after a session, as the generator lists it: each file by its path, sorted part by part. */
    private fun cacheLeft(cacheDir: File): JsonArray {
        if (!cacheDir.isDirectory) return JsonArray(emptyList())
        val files = cacheDir.walkTopDown().filter { it.isFile }.map { it.relativeTo(cacheDir).invariantSeparatorsPath to it }
            .sortedWith { a, b -> compareParts(a.first.split('/'), b.first.split('/')) }.toList()
        return JsonArray(files.map { (path, file) ->
            val data = file.readBytes()
            when {
                path.endsWith(".json") -> JsonObject(mapOf("path" to JsonPrimitive(path), "meta" to JsonPrimitive(String(data, Charsets.UTF_8))))
                path.endsWith(".body") -> try {
                    JsonObject(mapOf("path" to JsonPrimitive(path), "body" to bodyOut(GZIPInputStream(data.inputStream()).use { it.readBytes() })))
                } catch (e: java.io.IOException) {
                    JsonObject(mapOf("path" to JsonPrimitive(path), "raw" to bodyOut(data)))
                }
                else -> JsonObject(mapOf("path" to JsonPrimitive(path), "raw" to bodyOut(data)))
            }
        })
    }

    private fun compareParts(a: List<String>, b: List<String>): Int {
        for (i in 0 until minOf(a.size, b.size)) {
            val c = a[i].compareTo(b[i])
            if (c != 0) return c
        }
        return a.size - b.size
    }

    // --- scenario_helper.jsonl ----------------------------------------------------------------------------

    /** tests/test_scenario_helper.py's `two_gets`, replayed by core.testing.Scenarios. */
    fun scenarioHelper(misses: Misses) {
        for (line in Corpus.lines("http/scenario_helper.jsonl").filter { it["header"] != JsonPrimitive(true) }) {
            val kw = line.getValue("kw").jsonObject
            val accept = kw["accept"]?.jsonArray?.map { it.jsonPrimitive.int }?.toSet() ?: setOf(200)
            Scenarios.replay(line, misses) { world ->
                val client = world.clients.getValue("ug")
                listOf(kw.getValue("first"), kw.getValue("second")).map { url ->
                    val r = client.get(url.jsonPrimitive.content, accept = accept)
                    listOf(r.status, r.fromCache, Py.slice(r.text, null, 40))
                }
            }
        }
    }
}

/**
 * RealTransport against a site on loopback (a ServerSocket on 127.0.0.1), the same checks on the JVM
 * (core.http.RealTransportTest) and on the device (RealTransportOnDeviceTest, where HttpURLConnection is OkHttp's):
 * httpx's header set (names without case, values exact; neither platform lets their order be set), no redirect
 * followed, gzip and deflate decoded, an error answered with its body, a refused connection httpx's ConnectError,
 * RoutedTransport's URL in the query, and every site refused under `caracole.network=loopback`.
 */
object RealTransportChecks {
    /** One request a [LoopbackSite] read: its request line and its headers in order. */
    class Head(val line: String, val headers: List<Pair<String, String>>)

    /** A site on 127.0.0.1 answering each request with [respond]'s bytes, then closing the connection. */
    class LoopbackSite(private val respond: (Head) -> ByteArray) : AutoCloseable {
        private val server = java.net.ServerSocket(0, 50, java.net.InetAddress.getByName("127.0.0.1"))
        val port: Int get() = server.localPort
        val base: String get() = "http://127.0.0.1:$port"
        val heads = java.util.concurrent.CopyOnWriteArrayList<Head>()
        private val worker = Thread {
            while (!server.isClosed) {
                try {
                    server.accept().use { socket -> serve(socket) }
                } catch (e: java.io.IOException) {
                    // closed
                }
            }
        }.apply { isDaemon = true; start() }

        private fun serve(socket: java.net.Socket) {
            socket.soTimeout = 10_000
            val input = socket.getInputStream()
            val head = java.io.ByteArrayOutputStream()
            var last4 = 0
            while (true) {
                val b = input.read()
                if (b < 0) return
                head.write(b)
                last4 = (last4 shl 8) or b
                if (last4 == 0x0D0A0D0A) break
            }
            val lines = String(head.toByteArray(), Charsets.ISO_8859_1).split("\r\n").filter { it.isNotEmpty() }
            val parsed = Head(lines[0], lines.drop(1).map { it.substringBefore(':') to it.substringAfter(':').trimStart(' ') })
            heads += parsed
            socket.getOutputStream().apply { write(respond(parsed)); flush() }
        }

        override fun close() {
            server.close()
            worker.join(2_000)
        }
    }

    /** An HTTP/1.1 answer's bytes: its status line, [headers], a Content-Length, `Connection: close`, [body]. */
    fun answer(status: Int, headers: List<Pair<String, String>> = emptyList(), body: ByteArray = ByteArray(0)): ByteArray {
        val head = buildString {
            append("HTTP/1.1 $status Status\r\n")
            for ((k, v) in headers) append("$k: $v\r\n")
            append("Content-Length: ${body.size}\r\nConnection: close\r\n\r\n")
        }
        return head.toByteArray(Charsets.ISO_8859_1) + body
    }

    private fun check(ok: Boolean, said: () -> String) {
        if (!ok) throw AssertionError(said())
    }

    private fun deflate(data: ByteArray, raw: Boolean): ByteArray {
        val d = java.util.zip.Deflater(java.util.zip.Deflater.DEFAULT_COMPRESSION, raw)
        d.setInput(data)
        d.finish()
        val out = java.io.ByteArrayOutputStream()
        val buf = ByteArray(4096)
        while (!d.finished()) out.write(buf, 0, d.deflate(buf))
        d.end()
        return out.toByteArray()
    }

    private fun gzip(data: ByteArray): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        java.util.zip.GZIPOutputStream(out).use { it.write(data) }
        return out.toByteArray()
    }

    /** Every check, in turn; an AssertionError names the first that fails. */
    fun all() {
        httpxsHeaderSet()
        noRedirectIsFollowed()
        gzipAndDeflateAreDecoded()
        anErrorIsAnsweredWithItsBody()
        aRefusedConnectionIsAConnectError()
        routedRequestsCarryTheSitesUrlInTheQuery()
        everySiteIsRefusedUnderTheTests()
    }

    /** A PoliteClient over RealTransport sends httpx's header set and no other, and reads the answer. */
    fun httpxsHeaderSet() {
        LoopbackSite { answer(200, listOf("Content-Type" to "text/plain", "ETag" to "\"v1\""), "page".toByteArray()) }.use { site ->
            val dir = java.nio.file.Files.createTempDirectory("caracole-real").toFile()
            try {
                val client = PoliteClient("ug", ProviderPolicy(budget = 5, delay = 0.0 to 0.0), dir, "caracole/0.1 (test)",
                                          io.github.danielhp95.caracole.core.http.RealTransport, sleep = {},
                                          draws = { low, _ -> low }, monotonic = { 0.0 }, wallClock = { Instant.EPOCH })
                val r = client.get("${site.base}/tab/1?q=a+b")
                check(r.status == 200 && r.text == "page") { "the answer: ${r.status} ${r.text}" }
                check(r.headers == mapOf("etag" to "\"v1\"", "content-type" to "text/plain")) { "the kept headers: ${r.headers}" }
                val head = site.heads.single()
                check(head.line == "GET /tab/1?q=a+b HTTP/1.1") { "the request line: ${head.line}" }
                val got = head.headers.map { (k, v) -> Py.asciiLower(k) to v }.toSet()
                val want = setOf("host" to "127.0.0.1:${site.port}", "accept" to "*/*", "accept-encoding" to "gzip, deflate",
                                 "connection" to "keep-alive", "user-agent" to "caracole/0.1 (test)")
                check(got == want) { "the headers sent: ${head.headers}, httpx's $want" }
                check(head.headers.size == want.size) { "a header sent twice: ${head.headers}" }
            } finally {
                dir.deleteRecursively()
            }
        }
    }

    /** A redirect comes back as it is, its Location with it; nothing more is asked. */
    fun noRedirectIsFollowed() {
        LoopbackSite { answer(302, listOf("Location" to "/elsewhere")) }.use { site ->
            val r = io.github.danielhp95.caracole.core.http.RealTransport.send(HttpRequest("GET", "${site.base}/old", emptyList()))
            check(r.status == 302) { "a redirect answered ${r.status}" }
            check(r.headers.any { (k, v) -> Py.asciiLower(k) == "location" && v == "/elsewhere" }) { "its headers: ${r.headers}" }
            Thread.sleep(50)
            check(site.heads.size == 1) { "${site.heads.size} requests for one redirect" }
        }
    }

    /** gzip, zlib's deflate, a raw deflate, and two codings, each decoded as httpx decodes them. */
    fun gzipAndDeflateAreDecoded() {
        val text = "<html>${"Wonderwall ".repeat(200)}</html>".toByteArray()
        val cases = listOf(
            listOf("Content-Encoding" to "gzip") to gzip(text),
            listOf("Content-Encoding" to "deflate") to deflate(text, raw = false),
            listOf("Content-Encoding" to "deflate") to deflate(text, raw = true),
            listOf("Content-Encoding" to "gzip, deflate") to deflate(gzip(text), raw = false),
            listOf("Content-Encoding" to "identity") to text,
            listOf("Content-Encoding" to "br") to text,
        )
        for ((headers, body) in cases) {
            LoopbackSite { answer(200, headers, body) }.use { site ->
                val r = io.github.danielhp95.caracole.core.http.RealTransport.send(HttpRequest("GET", "${site.base}/", emptyList()))
                check(r.body.contentEquals(text)) { "$headers decoded to ${r.body.size} bytes, not ${text.size}" }
            }
        }
        LoopbackSite { answer(200, listOf("Content-Encoding" to "gzip"), "not gzip at all".toByteArray()) }.use { site ->
            val e = try {
                io.github.danielhp95.caracole.core.http.RealTransport.send(HttpRequest("GET", "${site.base}/", emptyList()))
                null
            } catch (e: TransportError) {
                e
            }
            check(e?.kind == "DecodingError") { "a body that isn't gzip: $e" }
        }
    }

    /** A 404's body is read, and the headers come back in order, a repeated one twice. */
    fun anErrorIsAnsweredWithItsBody() {
        LoopbackSite { answer(404, listOf("X-One" to "1", "Set-Cookie" to "a=1", "Set-Cookie" to "b=2"), "gone".toByteArray()) }.use { site ->
            val r = io.github.danielhp95.caracole.core.http.RealTransport.send(HttpRequest("GET", "${site.base}/gone", emptyList()))
            check(r.status == 404 && String(r.body) == "gone") { "a 404: ${r.status} ${String(r.body)}" }
            val names = r.headers.map { Py.asciiLower(it.first) }
            check(names.count { it == "set-cookie" } == 2) { "its headers: ${r.headers}" }
            check(names.none { it.startsWith("x-android-") }) { "the platform's own headers: ${r.headers}" }
        }
    }

    /** Nothing listening: httpx's ConnectError. */
    fun aRefusedConnectionIsAConnectError() {
        val port = java.net.ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1")).use { it.localPort }
        val e = try {
            io.github.danielhp95.caracole.core.http.RealTransport.send(HttpRequest("GET", "http://127.0.0.1:$port/", emptyList()))
            null
        } catch (e: TransportError) {
            e
        }
        check(e?.kind == "ConnectError") { "a refused connection: $e (${e?.kind})" }
    }

    /** RoutedTransport asks the fake sites server for `/fetch?url=<the site's URL>`, its Host the server's own. */
    fun routedRequestsCarryTheSitesUrlInTheQuery() {
        LoopbackSite { answer(200, body = "routed".toByteArray()) }.use { site ->
            val r = io.github.danielhp95.caracole.core.http.RoutedTransport(site.base).send(HttpRequest(
                "GET", "https://tabs.ultimate-guitar.com/tab/a b?x=1&y=2",
                listOf("Host" to "tabs.ultimate-guitar.com", "Accept" to "*/*", "User-Agent" to "caracole/test")))
            check(String(r.body) == "routed") { "the routed answer: ${String(r.body)}" }
            val head = site.heads.single()
            check(head.line == "GET /fetch?url=https%3A%2F%2Ftabs.ultimate-guitar.com%2Ftab%2Fa+b%3Fx%3D1%26y%3D2 HTTP/1.1") {
                "the routed request line: ${head.line}"
            }
            check(head.headers.filter { Py.asciiLower(it.first) == "host" }.map { it.second } == listOf("127.0.0.1:${site.port}")) {
                "the routed Host: ${head.headers}"
            }
            check(head.headers.any { it.first.equals("User-Agent") && it.second == "caracole/test" }) { "the routed headers: ${head.headers}" }
        }
    }

    /** Under the tests every host but loopback and the emulator's 10.0.2.2 is refused before a socket opens. */
    fun everySiteIsRefusedUnderTheTests() {
        check(System.getProperty(io.github.danielhp95.caracole.core.http.RealTransport.NETWORK) == "loopback") {
            "caracole.network is ${System.getProperty(io.github.danielhp95.caracole.core.http.RealTransport.NETWORK)}"
        }
        for (url in listOf("https://tabs.ultimate-guitar.com/tab/1", "https://lrclib.net/api/get?x=1", "http://192.168.1.20:8737/",
                           "http://[2001:db8::1]/", "http://127.0.0.2/", "http://localhost.example.com/", "http://10.0.2.3/")) {
            val e = try {
                io.github.danielhp95.caracole.core.http.RealTransport.send(HttpRequest("GET", url, emptyList()))
                null
            } catch (e: TransportError) {
                e
            }
            check(e?.kind == "refused") { "$url was not refused: $e" }
        }
    }
}
