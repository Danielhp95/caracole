package io.github.danielhp95.caracole.core.health

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Event
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.HealthReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Duration
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** health.py's cooldowns and events on the phone: vectors/health/ answered as Python answered it, and the rules
 * health.py's own tests hold. */
class HealthTest {
    @get:Rule val tmp = TemporaryFolder()

    private val t0: Instant = Instant.parse("2026-10-18T03:30:00Z")

    private fun <T> db(block: (Db) -> T): T = TestDb.fresh(tmp.newFolder()).use { it.writeBlocking(block) }

    @Test fun everyRecordIsAnsweredAsPythonAnsweredIt() {
        val misses = Misses("health/")
        HealthReplay.replay(misses)
        misses.assertNone()
        assertTrue(misses.checked > 200, "records checked: ${misses.checked}")
    }

    @Test fun theCooldownDoublesEachTwoHoursLongerAndAGoodLookupResetsIt() = db { db ->
        val first = Health.recordBlock(db, "ug", t0, "403 on /tab/1")
        assertEquals(1, first.strikes)
        assertEquals(t0.plus(Duration.ofHours(26)), first.cooldownUntil)
        assertTrue(Health.isCooling(db, "ug", t0.plus(Duration.ofHours(26)).minusSeconds(1)))
        assertFalse(Health.isCooling(db, "ug", t0.plus(Duration.ofHours(26))))
        val second = Health.recordBlock(db, "ug", t0.plus(Duration.ofDays(2)), "429")
        assertEquals(t0.plus(Duration.ofDays(2)).plus(Duration.ofHours(50)), second.cooldownUntil)
        assertEquals("""{"strikes": 2, "cooldown_until": "2026-10-22T05:30:00Z", "last_ok": null, "last_error": "429", """ +
                         """"last_error_at": "2026-10-20T03:30:00Z"}""", db.kvGet("provider:ug"))
        val ok = Health.recordOk(db, "ug", t0.plus(Duration.ofDays(10)))
        assertEquals(0, ok.strikes)
        assertNull(ok.cooldownUntil)
        assertEquals("429", ok.lastError)
    }

    @Test fun aRunningCooldownStaysAsItIsWhateverComesMeanwhile() = db { db ->
        val blocked = Health.recordBlock(db, "lacuerda", t0, "403")
        assertEquals(blocked, Health.recordBlock(db, "lacuerda", t0.plusSeconds(60), "429"))
        assertEquals(blocked, Health.recordOk(db, "lacuerda", t0.plusSeconds(120)))
        assertEquals(1, Health.state(db, "lacuerda").strikes)
    }

    @Test fun aCooldownPastTheYear9999IsPythonsOverflow() = db { db ->
        db.kvSet("provider:ug", """{"strikes": 22}""")
        assertFailsWith<ArithmeticException> { Health.recordBlock(db, "ug", t0, "403") }
        assertEquals("""{"strikes": 22}""", db.kvGet("provider:ug"))
    }

    @Test fun answeredAnyCountsTheRunsOwnFailures() = db { db ->
        val log = EventLog(db, "lookup:2026-11-03T12:00:00Z") { t0 }
        log(Event("ug", "https://tabs.ultimate-guitar.com/tab/1", 502, "error", "HTTP 502"))
        assertFalse(Health.answeredAny(db, "lookup:2026-11-03T12:00:00Z", "ug", 1))
        assertTrue(Health.answeredAny(db, "lookup:2026-11-03T12:00:00Z", "ug", 2))
        assertTrue(Health.answeredAny(db, "another run", "ug", 1))
    }

    @Test fun anEventLogWritesItsRowAloneAsPythonsDoes() = db { db ->
        EventLog(db, "lookup:x") { Instant.parse("2026-11-03T12:00:00.75Z") }(Event("ug", "u", null, "ok", null))
        assertEquals(listOf("lookup:x|2026-11-03T12:00:00Z|ug|u|null|ok|null"),
                     db.query("SELECT run, at, provider, url, status, decision, message FROM events") { r ->
                         (0..6).joinToString("|") { r.text(it) ?: "null" }
                     })
        assertNull(db.kvGet("http:last_request:ug"))  // the lookup's client writes it (Clients)
    }

    @Test fun strptimeReadsWhatPythonsReads() {
        assertEquals(Instant.parse("2026-10-19T05:03:00Z"), Strptime.parse("2026-10-19T5:3:0Z"))
        assertEquals(Instant.parse("2026-10-09T05:30:00Z"), Strptime.parse("2026-10- 9T 5:30:00z"))
        assertEquals(Instant.parse("2026-10-19T15:30:05Z"), Strptime.parse("２０２６-10-19T1٥:30:0५Z"))
        for (bad in listOf("2026-10-19T24:00:00Z", "2026-10-19 05:30:00Z", "2026-02-29T00:00:00Z", "2026-10-19T05:30:00ZZ",
                           "2026-10-19T05:30:60Z", "0000-01-01T00:00:00Z", "2026-1０-19T05:30:00Z")) {
            assertFailsWith<IllegalArgumentException>(bad) { Strptime.parse(bad) }
        }
        assertEquals("0001-01-01T00:00:00Z", Strptime.format(Instant.parse("0001-01-01T00:00:00.999Z")))
        assertEquals(3, Strptime.decimal(0x1D7D1))  // MATHEMATICAL BOLD DIGIT THREE
        assertEquals(3, Strptime.decimal(0x1D7DB))  // MATHEMATICAL DOUBLE-STRUCK DIGIT THREE, the next run's
        assertEquals(-1, Strptime.decimal('a'.code))
    }
}
