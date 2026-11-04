package io.github.danielhp95.caracole.core.http

import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.HttpReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** http.py's PoliteClient: every session of vectors/http/client.jsonl (each case of tests/test_http.py), and what a
 * site lane leans on. */
class PoliteClientTest {
    @get:Rule val tmp = TemporaryFolder()

    private val events = ArrayList<Event>()

    private fun client(transport: Transport, budget: Long = 6) =
        PoliteClient("ug", ProviderPolicy(budget = budget, delay = 0.0 to 0.0), tmp.root, "caracole/test", transport,
                     sleep = {}, draws = { low, _ -> low }, onEvent = { events += it }, monotonic = { 0.0 },
                     wallClock = { Instant.parse("2026-11-03T12:00:00Z") })

    @Test fun everySessionIsPythons() {
        val misses = Misses("http/client.jsonl")
        HttpReplay.sessions(misses)
        misses.assertNone()
    }

    @Test fun aRefusedRequestIsAProviderErrorAndNeverAMiss() {
        val c = client(io.github.danielhp95.caracole.core.testing.RefusingTransport)
        val e = assertFailsWith<ProviderError> { c.get("https://tabs.ultimate-guitar.com/tab/1") }
        assertTrue(e !is ProviderBlocked && e !is ProviderUnavailable)
        assertEquals("ug: https://tabs.ultimate-guitar.com/tab/1: refused: no site from a test: " +
                         "https://tabs.ultimate-guitar.com/tab/1", e.message)
        assertEquals(listOf("error"), events.map { it.decision })
    }

    @Test fun anAnswerIsCachedForeverAndCachedAnswersReadsItWithNoClient() {
        val url = "https://tabs.ultimate-guitar.com/tab/1"
        val site = FakeTransport(mapOf("GET $url" to FakeTransport.answer(200, "<html>page</html>", listOf("Content-Type" to "text/html"))))
        assertEquals("<html>page</html>", client(site).get(url).text)
        val kept = CachedAnswers("ug", tmp.root).cached(url)!!
        assertEquals(listOf(200, true), listOf(kept.status, kept.fromCache))
        assertEquals(mapOf("content-type" to "text/html"), kept.headers)
        assertEquals("2026-11-03T12:00:00Z", kept.fetchedAt)
        assertEquals(null, CachedAnswers("lrclib", tmp.root).cached(url))
        assertEquals(1, site.requests.size)
    }

    @Test fun theCacheRootHoldsEachAnswersMetaAndBodyAsHttpPyLaysThemOut() {
        val url = "https://tabs.ultimate-guitar.com/tab/1"
        val c = client(FakeTransport(mapOf("GET $url" to FakeTransport.answer(200, "page"))))
        c.get(url)
        val root = java.io.File(java.io.File(tmp.root, "http"), "ug")
        assertEquals(root, c.cacheRoot)
        assertEquals(root, CachedAnswers("ug", tmp.root).cacheRoot)
        val key = java.security.MessageDigest.getInstance("SHA-256").digest(url.toByteArray())
            .joinToString("") { "%02x".format(it) }
        assertEquals(listOf("${key.take(2)}/$key.body", "${key.take(2)}/$key.json"),
                     root.walkTopDown().filter { it.isFile }.map { it.relativeTo(root).invariantSeparatorsPath }.sorted().toList())
        assertEquals(null, object : Client {
            override val provider = "fake"
            override val requestsMade = 0
            override var policy = ProviderPolicy(budget = 0, delay = 0.0 to 0.0)
            override fun get(url: String, params: List<Pair<String, String>>?, cache: Boolean, conditional: Boolean,
                             accept: Set<Int>, maxAge: java.time.Duration?) = throw AssertionError()
            override fun cached(url: String, accept: Set<Int>): Response? = null
            override fun hasCached(url: String, accept: Set<Int>) = false
        }.cacheRoot)
    }

    @Test fun readOnceMoreAsksPastTheCacheForACopyThatWontRead() {
        val url = "https://x.test/page"
        val first = FakeTransport(mapOf("GET $url" to FakeTransport.answer(200, "<html>Maintenance</html>")))
        client(first).get(url)
        val second = FakeTransport(mapOf("GET $url" to FakeTransport.answer(200, "the page")))
        val c = client(second)
        val read = HttpRules.readOnceMore(c, c.get(url), url, { it is IllegalStateException }) { r ->
            check(r.text != "<html>Maintenance</html>") { "a notice" }
            r.text
        }
        assertEquals("the page", read)
        assertEquals(1, second.requests.size)
    }
}
