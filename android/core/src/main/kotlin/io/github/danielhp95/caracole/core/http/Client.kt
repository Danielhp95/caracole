package io.github.danielhp95.caracole.core.http

import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.PyCodec
import kotlinx.serialization.json.JsonElement
import java.io.File
import java.time.Duration
import java.time.Instant

/** http.py's Response: what a get answered, sent or read from the cache ([fromCache], [fetchedAt]). */
class Response(val url: String, val status: Int, val content: ByteArray, val headers: Map<String, String>,
               val fromCache: Boolean = false, val fetchedAt: String? = null) {
    /** The body as text: bytes.decode("utf-8", "replace"). */
    val text: String get() = PyCodec.utf8Replace(content)

    /** json.loads of [text]. */
    fun json(): JsonElement = PyJson.loads(text)
}

/** http.py's Event: one request's row of `events` (decision ok, not_modified, error, blocked, cached…). */
data class Event(val provider: String, val url: String, val status: Int?, val decision: String, val message: String?)

/** What a site's pass asks through: http.py's Client protocol. */
interface Client {
    val provider: String
    val requestsMade: Int
    var policy: ProviderPolicy

    fun get(url: String, params: List<Pair<String, String>>? = null, cache: Boolean = true,
            conditional: Boolean = false, accept: Set<Int> = setOf(200), maxAge: Duration? = null): Response

    fun cached(url: String, accept: Set<Int> = setOf(200)): Response?

    fun hasCached(url: String, accept: Set<Int> = setOf(200)): Boolean
}

/**
 * http.py's PoliteClient on the phone: one request at a time, a pause from the policy's delay between two, the budget,
 * robots.txt's closed paths, redirects followed by hand, every accepted 200 and 404 cached forever under
 * `cacheDir/http/<provider>/` as http.py lays it out, a 403, a 429 or a challenge a [ProviderBlocked].
 */
class PoliteClient(override val provider: String, override var policy: ProviderPolicy, val cacheDir: File,
                   val userAgent: String, val transport: Transport, val sleep: (Double) -> Unit, val draws: Draws,
                   val onEvent: ((Event) -> Unit)? = null, val maxConsecutiveErrors: Int = 3,
                   val monotonic: () -> Double, val wallClock: () -> Instant) : Client, AutoCloseable {
    override val requestsMade: Int get() = TODO("lane http-client")

    override fun get(url: String, params: List<Pair<String, String>>?, cache: Boolean, conditional: Boolean,
                     accept: Set<Int>, maxAge: Duration?): Response = TODO("lane http-client")

    override fun cached(url: String, accept: Set<Int>): Response? = TODO("lane http-client")

    override fun hasCached(url: String, accept: Set<Int>): Boolean = TODO("lane http-client")

    override fun close() {}
}

/** http.py's CachedAnswers: the cache alone, read with no request. */
class CachedAnswers(val provider: String, val cacheDir: File) {
    fun cached(url: String, accept: Set<Int> = setOf(200)): Response? = TODO("lane http-client")
}

/** http.py's robots rules (ROBOTS_DISALLOW), as data: data/caracole/http/robots.json. */
object Robots {
    const val NOT_A_URL = "not a valid URL"

    /** The rule that closes [url], or null for a URL caracole may ask for. */
    fun disallows(url: String): String? = TODO("lane http-client")
}

/** URLs as httpx renders them. */
object Urls {
    fun withParams(url: String, params: List<Pair<String, String>>): String = TODO("lane http-client")
    fun target(url: String): String = TODO("lane http-client")
    fun host(url: String): String = TODO("lane http-client")
    fun site(url: String): String = TODO("lane http-client")
    fun resolve(base: String, location: String): String = TODO("lane http-client")
}

/** http.py's rules about an answer: stale, Retry-After, a challenge page, read once more past the cache. */
object HttpRules {
    fun stale(r: Response, now: Instant, maxAge: Duration): Boolean = TODO("lane http-client")
    fun retryAfter(headers: Map<String, String>, now: Instant): Double? = TODO("lane http-client")
    fun isChallenge(headers: Map<String, String>, body: ByteArray): Boolean = TODO("lane http-client")
    fun <T> readOnceMore(client: Client, resp: Response, url: String, unreadable: (Throwable) -> Boolean,
                         fetched: MutableSet<String>? = null, accept: Set<Int> = setOf(200),
                         params: List<Pair<String, String>>? = null, read: (Response) -> T): T =
        TODO("lane http-client")
}
