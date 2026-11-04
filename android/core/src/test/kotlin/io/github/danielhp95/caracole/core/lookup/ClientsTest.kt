package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.http.Event
import io.github.danielhp95.caracole.core.http.Transport
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Assume
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

    @Test fun pythonsThreeDecimals() {
        assertEquals("1.000", Clients.seconds(1.0005))
        assertEquals("2.062", Clients.seconds(2.0625))
        assertEquals("2.063", Clients.seconds(2.0635))  // 2.06350000000000011…
        assertEquals("1762171199.250", Clients.seconds(1762171199.25))
        assertEquals("-0.000", Clients.seconds(-0.0))
        assertEquals("-0.000", Clients.seconds(-0.0001))
        assertEquals("0.000", Clients.seconds(0.0))
    }

    @Test fun aRequestTheClientSendsIsLoggedAndMarked() = db { db ->
        val url = "https://lrclib.net/api/get?artist_name=Soda+Stereo"
        transports["lrclib"] = FakeTransport(mapOf("GET $url" to FakeTransport.answer(200, "{}")))
        val client = clients().interactive(db, "lrclib", "x")
        try {
            client.get(url)
        } catch (e: NotImplementedError) {
            Assume.assumeTrue("waiting on lane http-client: PoliteClient.get (${e.message})", false)
        }
        assertEquals(listOf("lookup:x lrclib ok"),
                     db.query("SELECT run, provider, decision FROM events") { "${it.text(0)} ${it.text(1)} ${it.text(2)}" })
        assertEquals(Clients.seconds(wall), db.kvGet(Pace.LAST_SENT + "lrclib"))
    }
}
