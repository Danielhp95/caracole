package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.http.Event
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertSame

/** A lookup's clients as `_common.make_client(..., interactive=True)` makes them: the lookup's policy within the day,
 * the pause after this side's last request, each request logged, and kv `http:last_request:` after each one sent. */
class ClientsTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now: Instant = Instant.parse("2026-11-03T12:00:00Z")
    private var wall = 1793707200.0  // now
    private val slept = ArrayList<Double>()
    private val half = Draws { a, b -> a + (b - a) * 0.5 }
    private val pacing = Pacing(sleep = { slept += it }, draws = half, wallSeconds = { wall }, monotonic = { 0.0 },
                                clock = { now })
    private val transports = HashMap<String, Transport>()
    private lateinit var cache: File

    private fun clients(cfg: PhoneConfig = PhoneConfig.DEFAULTS) =
        Clients(cfg, cache, { provider -> transports.getOrPut(provider) { RefusingTransport } }, pacing)

    private fun <T> db(block: (Db) -> T): T {
        cache = tmp.newFolder("cache")
        return TestDb.fresh(tmp.newFolder()).use { it.writeBlocking(block) }
    }

    private fun sent(db: Db, provider: String, at: String, run: String, n: Int) = repeat(n) {
        db.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES (?, ?, ?, 'u', 200, 'ok')",
                   run, at, provider)
    }

    @Test fun aClientKeepsTheLookupsPolicyAndItsSettings() = db { db ->
        val cfg = PhoneConfig.DEFAULTS.copy(userAgent = "caracole/0.1 (the computer's)")
        sent(db, "ug", "2026-11-03T11:30:00Z", "lookup:2026-11-03T11:30:00Z", 57)
        val client = clients(cfg).interactive(db, "ug", "2026-11-03T12:00:00Z")
        assertEquals(Pace.lookupPolicy(cfg, db, "ug", now), client.policy)
        assertEquals(3, client.policy.budget)
        assertEquals(0.125 to 0.375, client.policy.delay)
        assertEquals("caracole/0.1 (the computer's)", client.userAgent)
        assertSame(cache, client.cacheDir)
        assertSame(transports.getValue("ug"), client.transport)
        assertEquals(emptyList(), slept)  // no request yet: no pause
    }

    @Test fun aSiteWithADaysCapGetsWhatTheDayLeavesOfItWhateverThePolicy() = db { db ->
        sent(db, "megalobiz", "2026-11-03T04:00:00Z", "2026-11-03T03:30:00Z", 898)
        assertEquals(2, clients().interactive(db, "megalobiz", "x").policy.budget)
        val given = PhoneConfig.DEFAULTS.provider("megalobiz").copy(budget = 1)
        assertEquals(given, clients().interactive(db, "megalobiz", "x", policy = given).policy)
        assertEquals(6, clients().interactive(db, "lrclib", "x", policy = given.copy(perDay = null, budget = 6)).policy.budget)
    }

    @Test fun theFirstRequestWaitsThePauseAfterThisSidesLast() = db { db ->
        db.kvSet(Pace.LAST_SENT + "ug", "1793707199.900")
        clients().interactive(db, "ug", "x")
        assertEquals(listOf(0.25 - (wall - 1793707199.9)), slept)
    }

    @Test fun eachEventIsLoggedUnderTheLookupsRunAndASentOneMarksTheLastRequest() = db { db ->
        val heard = ArrayList<Event>()
        val client = clients().interactive(db, "lrclib", "2026-11-03T12:00:00Z", onEvent = { heard += it })
        val logged = client.onEvent!!
        wall = 1.0005
        logged(Event("lrclib", "https://lrclib.net/api/get?x=1", 200, "ok", null))
        assertEquals("1.000", db.kvGet(Pace.LAST_SENT + "lrclib"))  // f"{1.0005:.3f}", half to even on the exact double
        wall = 1762171300.25
        logged(Event("lrclib", "https://lrclib.net/api/get?x=2", null, "cached", null))
        assertEquals("1.000", db.kvGet(Pace.LAST_SENT + "lrclib"))  // nothing sent
        logged(Event("lrclib", "https://lrclib.net/api/get?x=3", 503, "error", "HTTP 503"))
        assertEquals("1762171300.250", db.kvGet(Pace.LAST_SENT + "lrclib"))
        assertEquals(listOf("lookup:2026-11-03T12:00:00Z ok", "lookup:2026-11-03T12:00:00Z cached",
                            "lookup:2026-11-03T12:00:00Z error"),
                     db.query("SELECT run, decision FROM events ORDER BY id") { "${it.text(0)} ${it.text(1)}" })
        assertEquals(3, heard.size)
        assertNull(db.kvGet(Pace.LAST_SENT + "ug"))
    }

    @Test fun theLastRequestsTextIsPythonsThreeDecimals() = db { db ->
        val logged = clients().interactive(db, "lrclib", "x").onEvent!!
        for ((at, text) in listOf(2.0625 to "2.062", 2.0635 to "2.063", -0.0001 to "-0.000", 1e17 to "100000000000000000.000")) {
            wall = at
            logged(Event("lrclib", "u", 200, "ok", null))
            assertEquals(text, db.kvGet(Pace.LAST_SENT + "lrclib"), "f'{$at:.3f}'")
        }
    }

    @Test fun aRequestTheClientSendsIsLoggedAndMarked() = db { db ->
        val url = "https://lrclib.net/api/get?artist_name=Soda+Stereo"
        transports["lrclib"] = FakeTransport(mapOf("GET $url" to FakeTransport.answer(200, "{}")))
        val client = clients().interactive(db, "lrclib", "x")
        wall = 1793707200.0625
        client.get(url)
        assertEquals(listOf("lookup:x|2026-11-03T12:00:00Z|lrclib|$url|200|ok"),
                     db.query("SELECT run, at, provider, url, status, decision FROM events") { r ->
                         (0..5).joinToString("|") { r.text(it) ?: "null" }
                     })
        assertEquals("1793707200.062", db.kvGet(Pace.LAST_SENT + "lrclib"))
        assertEquals(PyFormat.fixed(wall, 3), db.kvGet(Pace.LAST_SENT + "lrclib"))
        assertEquals(java.io.File(java.io.File(cache, "http"), "lrclib"), client.cacheRoot)
        assertEquals(emptyList(), slept)  // no request before it: no pause, the client's first goes at once
    }

    /** _pause_after_last_request draws first, as make_client calls it before the client exists; the client draws
     * only before its second request (http.py's _pause), the time since its first by its own clock. */
    @Test fun thePauseAfterTheLastRequestDrawsBeforeTheClientsOwn() = db { db ->
        val us = ArrayDeque(listOf(0.0, 1.0))
        val drawn = ArrayList<Pair<Double, Double>>()
        val ordered = pacing.copy(draws = Draws { a, b -> drawn += a to b; a + (b - a) * us.removeFirst() })
        val first = "https://lrclib.net/api/get?q=1"
        val second = "https://lrclib.net/api/get?q=2"
        transports["lrclib"] = FakeTransport(mapOf("GET $first" to FakeTransport.answer(200, "{}"),
                                                   "GET $second" to FakeTransport.answer(200, "{}")))
        db.kvSet(Pace.LAST_SENT + "lrclib", "1793707199.950")  // 0.05 s ago
        val client = Clients(PhoneConfig.DEFAULTS, cache, { transports.getValue(it) }, ordered)
            .interactive(db, "lrclib", "x")
        assertEquals(1, drawn.size)
        client.get(first)
        assertEquals(1, drawn.size)
        client.get(second)
        assertEquals(listOf(0.125 to 0.375, 0.125 to 0.375), drawn)
        // 0.125 less the 0.05 s since this side's last; then 0.375, its monotonic clock standing still.
        assertEquals(2, slept.size)
        assertEquals(0.125 - (wall - 1793707199.95), slept[0])
        assertEquals(0.375, slept[1])
    }
}
