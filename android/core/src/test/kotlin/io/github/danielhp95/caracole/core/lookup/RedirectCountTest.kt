package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.http.HttpAnswer
import io.github.danielhp95.caracole.core.http.RobotsClosed
import io.github.danielhp95.caracole.core.testing.FakeTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull

/**
 * A request a site answers with a redirect reached the site: its `events` row, `redirect`, is one of [Pace.SENT], so
 * the hour's `lookup_per_hour`, the day's `per_day` and kv `http:last_request:<provider>` count it, as
 * commands/_common.py's `_SENT` does.
 */
class RedirectCountTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now: Instant = Instant.parse("2026-11-10T18:00:00Z")
    private val slept = ArrayList<Double>()
    private val pacing = Pacing(sleep = { slept += it }, draws = Draws { a, _ -> a },
                                wallSeconds = { now.epochSecond.toDouble() }, monotonic = { 0.0 }, clock = { now })

    private fun db(block: (Db, File) -> Unit): Unit = TestDb.fresh(tmp.newFolder()).use { database ->
        val cache = tmp.newFolder("cache")
        database.writeBlocking { block(it, cache) }
    }

    private fun events(db: Db): List<String> = db.query("SELECT decision FROM events ORDER BY id") { it.text(0)!! }

    @Test fun `a followed redirect is two requests counted in the hour and the day`() = db { db, cache ->
        val old = "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"
        val new = "$old-v2"
        val site = FakeTransport(mapOf(
            "GET $old" to HttpAnswer(301, listOf("Location" to new), ByteArray(0)),
            "GET $new" to FakeTransport.answer(200, "<html>a page</html>"),
        ))
        val client = Clients(PhoneConfig.DEFAULTS, cache, { site }, pacing).interactive(db, "ug", Pace.lookupRunId(now))
        client.get(old)
        assertEquals(2, client.requestsMade)
        assertEquals(listOf("redirect", "ok"), events(db))
        assertEquals(2, Pace.lookupRequestsUsed(db, "ug", now))
        assertEquals(2, Pace.requestsToday(db, "ug", now))
    }

    @Test fun `a redirect not followed is a request the hour, the day and the pace count`() = db { db, cache ->
        // gametabs.net answers a tab page with a redirect to its login, which robots.txt closes.
        val page = "https://gametabs.net/hollow-knight/main-theme-108"
        val site = FakeTransport(mapOf(
            "GET $page" to HttpAnswer(302, listOf("Location" to "/login?next=%2Fhollow-knight%2Fmain-theme-108"), ByteArray(0)),
        ))
        val clients = Clients(PhoneConfig.DEFAULTS, cache, { site }, pacing)
        repeat(3) {
            val client = clients.interactive(db, "gametabs", Pace.lookupRunId(now))
            assertFailsWith<RobotsClosed> { client.get(page) }
        }
        assertEquals(3, site.said.size)
        assertEquals(3, Pace.lookupRequestsUsed(db, "gametabs", now))
        assertEquals(3, Pace.requestsToday(db, "gametabs", now))
        assertNotNull(db.kvGet(Pace.LAST_SENT + "gametabs"))
        assertEquals(2, slept.size)  // the second and the third lookup each waited the gap after the one before
    }

    @Test fun `a redirect that spends the budget is the one request counted`() = db { db, cache ->
        val old = "https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169"
        val site = FakeTransport(mapOf("GET $old" to HttpAnswer(301, listOf("Location" to "$old-v2"), ByteArray(0))))
        val policy = Pace.lookupPolicy(PhoneConfig.DEFAULTS, db, "ug", now).copy(budget = 1)
        val client = Clients(PhoneConfig.DEFAULTS, cache, { site }, pacing).interactive(db, "ug", Pace.lookupRunId(now), policy)
        assertFailsWith<BudgetExhausted> { client.get(old) }
        assertEquals(listOf("redirect", "budget"), events(db))
        assertEquals(1, Pace.lookupRequestsUsed(db, "ug", now))
    }
}
