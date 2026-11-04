package io.github.danielhp95.caracole.core.lookup

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.PaceReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** commands/_common.py's lookup pace on the phone: vectors/pace/ answered as Python answered it, and its rules. */
class PaceTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now: Instant = Instant.parse("2026-11-03T12:00:00Z")

    private fun <T> db(block: (Db) -> T): T = TestDb.fresh(tmp.newFolder()).use { it.writeBlocking(block) }

    private fun sent(db: Db, provider: String, at: String, run: String = "lookup:x", decision: String = "ok", n: Int = 1) =
        repeat(n) {
            db.execute("INSERT INTO events (run, at, provider, url, status, decision) VALUES (?, ?, ?, 'u', 200, ?)",
                       run, at, provider, decision)
        }

    @Test fun everyRecordIsAnsweredAsPythonAnsweredIt() {
        val misses = Misses("pace/")
        PaceReplay.replay(misses)
        misses.assertNone()
        assertTrue(misses.checked > 120, "records checked: ${misses.checked}")
    }

    @Test fun aLookupsBudgetIsWhatTheHourLeavesNeverBelowNone() = db { db ->
        val cfg = PhoneConfig.DEFAULTS
        assertEquals(6, Pace.lookupPolicy(cfg, db, "ug", now).budget)
        assertEquals(0.125 to 0.375, Pace.lookupPolicy(cfg, db, "ug", now).delay)
        sent(db, "ug", "2026-11-03T11:30:00Z", n = 57)
        sent(db, "ug", "2026-11-03T03:30:00Z", run = "2026-11-03T03:30:00Z", n = 10)  // the nightly run's: no lookup
        sent(db, "ug", "2026-11-03T11:30:00Z", decision = "cached", n = 10)  // no request
        assertEquals(57, Pace.lookupRequestsUsed(db, "ug", now))
        assertEquals(3, Pace.lookupPolicy(cfg, db, "ug", now).budget)
        sent(db, "ug", "2026-11-03T11:31:00Z", n = 10)
        assertEquals(0, Pace.lookupPolicy(cfg, db, "ug", now).budget)
        assertEquals(6, Pace.lookupPolicy(cfg, db, "ug", Instant.parse("2026-11-03T13:00:00Z")).budget)
    }

    @Test fun megalobizsDayCapsAnyPolicy() = db { db ->
        val megalobiz = PhoneConfig.DEFAULTS.provider("megalobiz")
        sent(db, "megalobiz", "2026-11-03T04:00:00Z", run = "2026-11-03T03:30:00Z", n = 898)
        sent(db, "megalobiz", "2026-11-02T23:59:59Z", run = "2026-11-02T03:30:00Z", n = 50)  // yesterday's
        assertEquals(898, Pace.requestsToday(db, "megalobiz", now))
        assertEquals(2, Pace.withinTheDay(db, "megalobiz", megalobiz, now).budget)
        val lookup = Pace.lookupPolicy(PhoneConfig.DEFAULTS, db, "megalobiz", now)
        assertEquals(2, Pace.withinTheDay(db, "megalobiz", lookup, now).budget)
        val ug = PhoneConfig.DEFAULTS.provider("ug")
        assertEquals(ug, Pace.withinTheDay(db, "ug", ug, now))
    }

    @Test fun theLastRequestIsTheRecordElseTheEventsAndThePauseKeepsAfterIt() = db { db ->
        assertNull(Pace.lastRequest(db, "ug"))
        val slept = ArrayList<Double>()
        val half = Draws { a, b -> a + (b - a) * 0.5 }
        Pace.pauseAfterLastRequest(db, "ug", 2.5 to 5.0, half, { slept += it }, { 1000.0 })
        assertEquals(emptyList(), slept)
        sent(db, "ug", "2026-11-03T11:59:59Z")
        assertEquals(Instant.parse("2026-11-03T11:59:59Z").epochSecond.toDouble(), Pace.lastRequest(db, "ug"))
        db.kvSet(Pace.LAST_SENT + "ug", "999.000")
        assertEquals(999.0, Pace.lastRequest(db, "ug"))
        Pace.pauseAfterLastRequest(db, "ug", 2.5 to 5.0, half, { slept += it }, { 1000.0 })
        assertEquals(listOf(2.75), slept)
        Pace.pauseAfterLastRequest(db, "ug", 2.5 to 5.0, half, { slept += it }, { 900.0 })  // the clock set back
        assertEquals(listOf(2.75, 5.0), slept)
        assertEquals("lookup:2026-11-03T12:00:00Z", Pace.lookupRunId(Instant.parse("2026-11-03T12:00:00.999Z")))
    }

    @Test fun theLastRequestsTextIsReadAsPythonsFloatReadsIt() = db { db ->
        fun read(text: String): Double? = db.kvSet(Pace.LAST_SENT + "ug", text).let { Pace.lastRequest(db, "ug") }
        assertEquals(1762171199.25, read("1762171199.250"))
        assertEquals(1000.5, read(" 1_000.5\n"))
        assertEquals(123.0, read("١٢٣"))
        assertEquals(Double.NEGATIVE_INFINITY, read("-iNfInItY"))
        assertTrue(read("nan")!!.isNaN())
        for (bad in listOf("", ".", "1__0", "_1", "1_", "0x10", "1.5f", "1d", "1e", "infinityx", "7\u200b", "1\u0000",
                           "\u001c1"))
            assertNull(read(bad), bad)  // no events either: none
    }
}
