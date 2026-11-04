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

    /**
     * `json.loads(self.content)`: the bytes, never [text]. Python decodes them as `json.detect_encoding` says (a BOM's
     * UTF-32 or UTF-16, UTF-8 with its BOM dropped, else by where the first bytes' zeros are), strictly with lone
     * surrogates passed, so a byte that isn't the text's encoding is a ValueError (UnicodeDecodeError), which
     * lyrics.py's and megalobiz.py's readers turn into their parse errors, where [text]'s U+FFFD would read as data.
     * That reading is `PyJson.loads(ByteArray)` (vectors/py/sites_json.jsonl's `json.loads(bytes)`).
     */
    fun json(): JsonElement = PyJson.loads(content)
}

/** http.py's Event: one request's row of `events` (decision ok, not_modified, redirect, blocked, error, budget). */
data class Event(val provider: String, val url: String, val status: Int?, val decision: String, val message: String?)

/** What a site's pass asks through: http.py's Client protocol. */
interface Client {
    val provider: String
    val requestsMade: Int
    var policy: ProviderPolicy

    /** http.py's `cache_root`: the folder of this provider's cached answers (`cacheDir/http/<provider>/`, each a
     * `<2 hex>/<sha256>.json` meta and its `.body`), which lacuerda_index's backfill_cached lists; null for a client
     * with none (a test's fake), as `getattr(client, "cache_root", None)` reads it. */
    val cacheRoot: File? get() = null

    fun get(url: String, params: List<Pair<String, String>>? = null, cache: Boolean = true,
            conditional: Boolean = false, accept: Set<Int> = setOf(200), maxAge: Duration? = null): Response

    fun cached(url: String, accept: Set<Int> = setOf(200)): Response?

    fun hasCached(url: String, accept: Set<Int> = setOf(200)): Boolean
}

/** http.py's CachedAnswers: one provider's answers in the HTTP cache (`cacheDir/http/<provider>/`), read alone, with
 * no way to send a request, so no budget, no lock and no cooldown of its own. */
class CachedAnswers(val provider: String, val cacheDir: File) {
    /** http.py's `cache_root`, as [Client.cacheRoot]. */
    val cacheRoot: File = File(File(cacheDir, "http"), provider)
    private val cache = HttpCache(cacheRoot)

    fun cached(url: String, accept: Set<Int> = setOf(200)): Response? = cache.answer(url, accept)
}
