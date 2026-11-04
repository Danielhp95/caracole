package io.github.danielhp95.caracole.core.http

import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.PyCodec
import kotlinx.serialization.json.JsonElement
import java.io.File
import java.time.Duration

/** http.py's Response: what a get answered, sent or read from the cache ([fromCache], [fetchedAt]). */
class Response(val url: String, val status: Int, val content: ByteArray, val headers: Map<String, String>,
               val fromCache: Boolean = false, val fetchedAt: String? = null) {
    /** The body as text: bytes.decode("utf-8", "replace"). */
    val text: String get() = PyCodec.utf8Replace(content)

    /** json.loads of [text]. */
    fun json(): JsonElement = PyJson.loads(text)
}

/** http.py's Event: one request's row of `events` (decision ok, not_modified, redirect, blocked, error, budget). */
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

/** http.py's CachedAnswers: one provider's answers in the HTTP cache (`cacheDir/http/<provider>/`), read alone, with
 * no way to send a request, so no budget, no lock and no cooldown of its own. */
class CachedAnswers(val provider: String, val cacheDir: File) {
    private val cache = HttpCache(File(File(cacheDir, "http"), provider))

    fun cached(url: String, accept: Set<Int> = setOf(200)): Response? = cache.answer(url, accept)
}
