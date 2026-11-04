package io.github.danielhp95.caracole.core.http

import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyStr
import java.io.File
import java.math.BigDecimal
import java.math.RoundingMode
import java.time.Duration
import java.time.Instant

/**
 * http.py's PoliteClient on the phone: one provider's HTTP client, cache-first, budgeted, paced, never escalating,
 * as tests/conformance/vectors/http/client.jsonl holds it to Python's.
 *
 * - A cached 200 or 404 is served without a request when the caller accepts its status; only accepted answers are
 *   cached, forever, under `cacheDir/http/<provider>/` ([HttpCache]).
 * - `conditional` revalidates a cached copy (If-None-Match, If-Modified-Since); a 304 returns it, as old as the 304.
 * - Before every request but the first, a pause of `policy.delay` (a [draws] draw), less the time since the last one
 *   ([monotonic]); `policy.budget` requests, then [BudgetExhausted].
 * - A URL robots.txt closes is never asked for: [RobotsClosed]; a string httpx can't take as a URL a ProviderError.
 * - Redirects followed one hop at a time, at most three, each a request like any other and on the site asked for.
 * - A 403, a 429 or a challenge page: [ProviderBlocked], and nothing more is sent.
 * - LRCLIB's 503 with a Retry-After it can wait asked once more after it and a jitter under a second.
 * - [maxConsecutiveErrors] other errors in a row: [ProviderUnavailable].
 *
 * Every request goes through [transport], with httpx's headers and [userAgent]; each is an [Event] for [onEvent].
 */
class PoliteClient(override val provider: String, override var policy: ProviderPolicy, val cacheDir: File,
                   val userAgent: String, val transport: Transport, val sleep: (Double) -> Unit, val draws: Draws,
                   val onEvent: ((Event) -> Unit)? = null, val maxConsecutiveErrors: Int = 3,
                   val monotonic: () -> Double, val wallClock: () -> Instant) : Client, AutoCloseable {
    private val cache = HttpCache(File(File(cacheDir, "http"), provider))
    private var made = 0
    private var lastRequest: Double? = null
    private var errorsInARow = 0
    private var blocked: ProviderBlocked? = null
    private var unavailable = false
    private var budgetReported = false

    override val requestsMade: Int get() = synchronized(this) { made }

    /** One request as httpx sends it, and what answered: its URL parsed, and the redirect it makes, if any. */
    private class Sent(val url: HttpxUrl, val request: HttpRequest)

    private class Answer(val status: Int, raw: List<Pair<String, String>>, val body: ByteArray, val next: Sent?) {
        /** httpx's Headers.items(): each name lowercased once, its values joined by ", ". */
        val headers: Map<String, String> = LinkedHashMap<String, String>().also { merged ->
            for ((name, value) in raw) {
                val key = Py.asciiLower(name)
                merged[key] = merged[key]?.let { "$it, $value" } ?: value
            }
        }
    }

    override fun get(url: String, params: List<Pair<String, String>>?, cache: Boolean, conditional: Boolean,
                     accept: Set<Int>, maxAge: Duration?): Response = synchronized(this) {
        val full = if (!params.isNullOrEmpty()) {
            try {
                Urls.withParams(url, params)
            } catch (e: UrlError) {
                throw notAUrl(url)
            }
        } else {
            url
        }
        val rule = Robots.disallows(full)
        if (rule == Robots.NOT_A_URL) throw notAUrl(full)
        val key = this.cache.key(full)
        var cached = if (cache || conditional) this.cache.read(key) else null
        if (cached != null && cached.status !in accept) cached = null
        val expired = cached != null && maxAge != null && HttpRules.stale(cached, wallClock(), maxAge)
        if ((cache && cached != null && !conditional && !expired) || (expired && made >= policy.budget)) return cached!!

        if (rule != null) throw RobotsClosed(provider, full, null, "robots.txt disallows it ($rule)")
        val extra = ArrayList<Pair<String, String>>()
        if (conditional && cached != null) {
            HttpRules.header(cached.headers, "etag")?.takeIf { it.isNotEmpty() }?.let { extra += "If-None-Match" to it }
            HttpRules.header(cached.headers, "last-modified")?.takeIf { it.isNotEmpty() }
                ?.let { extra += "If-Modified-Since" to it }
        }

        var (at, resp) = answer(full, extra)
        val wait = retryWait(at, resp, accept)
        if (wait != null) {
            val said = HttpRules.header(resp.headers, "retry-after")
            event(at, resp.status, "error", "HTTP ${resp.status}, asked again in ${oneDecimal(wait)} s (Retry-After: $said)")
            sleep(wait)
            val again = answer(full, extra)
            at = again.first
            resp = again.second
        }

        val status = resp.status
        if (status == 304 && cached != null) {
            errorsInARow = 0
            event(at, status, "not_modified", null)
            val stamp = Stamp.format(wallClock())
            this.cache.writeMeta(key, cached.url, cached.status, cached.headers, stamp)
            return Response(full, 304, cached.content, cached.headers, fromCache = true, fetchedAt = stamp)
        }
        if (status in accept) {
            val kept = LinkedHashMap<String, String>()
            for (h in HttpData.keptHeaders) resp.headers[h]?.let { kept[h] = it }
            if (status in HttpData.cachedStatuses) {
                this.cache.write(key, full, status, kept, resp.body, Stamp.format(wallClock()))
            }
            if (status < 500) errorsInARow = 0
            event(at, status, "ok", null)
            return Response(full, status, resp.body, kept, fromCache = false)
        }
        throw fail(at, status, "HTTP $status")
    }

    override fun hasCached(url: String, accept: Set<Int>): Boolean = cache.has(url, accept)

    override fun cached(url: String, accept: Set<Int>): Response? = cache.answer(url, accept)

    override fun close() {}

    /** GET [full] with [extra] headers, its redirects followed one checked hop at a time: the URL that answered (the
     * one asked for, or the last hop) and its answer. */
    private fun answer(full: String, extra: List<Pair<String, String>>): Pair<String, Answer> {
        val first = HttpxUrl.parse(full)
        val headers = listOf("Host" to first.netloc, "Accept" to "*/*", "Accept-Encoding" to "gzip, deflate",
                             "Connection" to "keep-alive", "User-Agent" to userAgent) + extra
        var at = full
        var resp = send(at, Sent(first, HttpRequest("GET", first.toString(), headers)))
        var hops = 0
        while (true) {
            val next = resp.next ?: break
            hops++
            val target = next.request.url
            val problem = when {
                hops > HttpData.maxRedirects -> "more than ${HttpData.maxRedirects} redirects"
                Urls.site(target) != Urls.site(full) -> "redirect to another site: $target"
                else -> null
            }
            if (problem != null) throw fail(at, resp.status, problem)
            val closed = Robots.disallows(target)
            if (closed != null) {
                val message = "redirect to $target, which robots.txt disallows ($closed)"
                event(at, resp.status, "redirect", "not followed: $message")
                throw RobotsClosed(provider, at, resp.status, message)
            }
            event(at, resp.status, "redirect", target)
            at = target
            resp = send(target, next)
        }
        return at to resp
    }

    /** How long to wait before asking once more: a 503 the caller rejects, from a host of RETRY_AFTER_503, whose
     * Retry-After is no longer than the host's most, when the budget can pay for the retry. */
    private fun retryWait(at: String, resp: Answer, accept: Set<Int>): Double? {
        if (resp.status != 503 || 503 in accept || made >= policy.budget) return null
        val most = HttpData.retryAfter503[Urls.host(at)] ?: return null
        val said = HttpRules.retryAfter(resp.headers, wallClock()) ?: return null
        if (said > most) return null
        return said + draws.uniform(0.0, HttpData.retryJitter)
    }

    /** One network request, a redirect hop included: within the budget, after the pause. */
    private fun send(url: String, sent: Sent): Answer {
        blocked?.let { throw ProviderBlocked(provider, url, it.status, "blocked earlier this run") }
        if (unavailable) throw ProviderUnavailable(provider, url, null, "too many errors this run")
        if (made >= policy.budget) {
            if (!budgetReported) {
                budgetReported = true
                event(url, null, "budget", "budget of ${policy.budget} requests spent")
            }
            throw BudgetExhausted(provider)
        }
        pause()
        made++
        lastRequest = monotonic()
        val got = try {
            transport.send(sent.request)
        } catch (e: TransportError) {
            throw fail(url, null, "${e.kind}: ${e.message}")
        }
        val next = try {
            redirect(sent, got)
        } catch (e: UrlError) {
            if (e.kind != "RemoteProtocolError") throw e
            throw fail(url, null, "${e.kind}: ${e.message}")
        }
        val answer = Answer(got.status, got.headers, got.body, next)
        val challenge = HttpRules.isChallenge(answer.headers, got.body)
        if (got.status == 403 || got.status == 429 || challenge) {
            val reason = if (challenge) "challenge page" else "HTTP ${got.status}"
            val block = ProviderBlocked(provider, url, got.status, reason)
            blocked = block
            event(url, got.status, "blocked", reason)
            throw block
        }
        return answer
    }

    /** httpx's next request for a redirect: its URL (`_redirect_url`) and the headers it carries on, its Host the new
     * one's when it leaves the origin. */
    private fun redirect(sent: Sent, got: HttpAnswer): Sent? {
        if (got.status !in REDIRECTS) return null
        val locations = got.headers.filter { Py.asciiLower(it.first) == "location" }.map { it.second }
        if (locations.isEmpty()) return null
        val url = Urls.resolved(sent.url, locations.joinToString(", "))
        var headers = sent.request.headers
        val sameOrigin = url.scheme == sent.url.scheme && url.decodedHost == sent.url.decodedHost &&
            url.portOrDefault == sent.url.portOrDefault
        if (!sameOrigin) {
            val at = headers.indexOfFirst { Py.asciiLower(it.first) == "host" }
            headers = if (at < 0) headers + ("Host" to url.netloc)
                      else headers.filterIndexed { i, h -> i == at || Py.asciiLower(h.first) != "host" }
                          .map { if (Py.asciiLower(it.first) == "host") "Host" to url.netloc else it }
        }
        return Sent(url, HttpRequest("GET", url.toString(), headers))
    }

    private fun pause() {
        val last = lastRequest ?: return
        val target = draws.uniform(policy.delay.first, policy.delay.second)
        val remaining = target - (monotonic() - last)
        if (remaining > 0) sleep(remaining)
    }

    private fun fail(url: String, status: Int?, message: String): ProviderError {
        errorsInARow++
        if (errorsInARow >= maxConsecutiveErrors) unavailable = true
        event(url, status, "error", message)
        return ProviderError(provider, url, status, message)
    }

    private fun event(url: String, status: Int?, decision: String, message: String?) {
        onEvent?.invoke(Event(provider, url, status, decision, message))
    }

    /** The error for a string httpx can't take as a URL: its start, escaped, for the log. */
    private fun notAUrl(url: String): ProviderError {
        val shown = if (Py.len(url) <= 120) url else Py.slice(url, null, 120) + "..."
        return ProviderError(provider, null, null, "${Robots.NOT_A_URL}: ${PyStr.repr(shown)}")
    }

    private companion object {
        val REDIRECTS = setOf(301, 302, 303, 307, 308)

        /** f"{x:.1f}": the double's exact value rounded half to even, as Python formats one. */
        fun oneDecimal(x: Double): String = BigDecimal(x).setScale(1, RoundingMode.HALF_EVEN).toPlainString()
    }
}
