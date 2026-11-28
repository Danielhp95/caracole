package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.EventLog
import io.github.danielhp95.caracole.core.http.Event
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Duration
import java.time.Instant
import kotlin.test.assertEquals

/** The phone's day of yt-dlp runs (DayBudget): the youtube policy's budget less the runs of the 24 hours before. */
class DayBudgetTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now = Instant.parse("2026-11-26T12:00:00Z")

    private fun <T> db(block: (Db) -> T): T = TestDb.fresh(tmp.newFolder()).use { it.writeBlocking(block) }

    private fun run(db: Db, at: Instant, decision: String, runId: String = "youtube-auto:x:1", provider: String = "youtube") =
        EventLog(db, runId) { at }(Event(provider, "https://example.invalid/", null, decision, null))

    @Test fun theDayIsThePolicysBudgetLessTheRunsSentInTheLast24Hours() = db { db ->
        val cfg = PhoneConfig.read(db)
        val budget = cfg.provider("youtube").budget.toInt()
        assertEquals(budget, DayBudget.left(db, cfg, now), "no run yet")
        run(db, now.minusSeconds(60), "ok")
        run(db, now.minusSeconds(120), "error")
        run(db, now.minusSeconds(180), "blocked")
        assertEquals(3, DayBudget.runs(db, now))
        assertEquals(budget - 3, DayBudget.left(db, cfg, now))
    }

    @Test fun anAskedNowRunCountsAsAnAutomaticOneDoes() = db { db ->
        val cfg = PhoneConfig.read(db)
        val budget = cfg.provider("youtube").budget.toInt()
        run(db, now.minusSeconds(60), "ok", runId = "youtube-search:radiohead creep:2026-11-26T11:59:00Z")
        run(db, now.minusSeconds(30), "ok", runId = "lookup:2026-11-26T11:59:30Z:youtube-sheet")
        run(db, now.minusSeconds(10), "ok", runId = "youtube-auto:2026-11-26T11:59:50Z:7")
        assertEquals(budget - 3, DayBudget.left(db, cfg, now))
    }

    @Test fun aBudgetRowRanNothingAndAnotherProvidersRowIsNoRun() = db { db ->
        val cfg = PhoneConfig.read(db)
        val budget = cfg.provider("youtube").budget.toInt()
        run(db, now.minusSeconds(60), "budget")
        run(db, now.minusSeconds(60), "ok", provider = "ytimg")
        run(db, now.minusSeconds(60), "ok", provider = "lrclib")
        assertEquals(budget, DayBudget.left(db, cfg, now))
    }

    @Test fun aRunFreesItsSlot24HoursAfterIt() = db { db ->
        val cfg = PhoneConfig.read(db)
        val budget = cfg.provider("youtube").budget.toInt()
        val at = now.minus(Duration.ofHours(3))
        run(db, at, "ok")
        assertEquals(budget - 1, DayBudget.left(db, cfg, at.plus(Duration.ofHours(24))), "24 hours after: still counted")
        assertEquals(budget, DayBudget.left(db, cfg, at.plus(Duration.ofHours(24)).plusSeconds(1)), "then freed")
    }

    @Test fun aDayRunPastItsBudgetLeavesNoneNeverFewer() = db { db ->
        val cfg = PhoneConfig.read(db)
        val budget = cfg.provider("youtube").budget.toInt()
        repeat(budget + 2) { run(db, now.minusSeconds(it + 1L), "ok") }
        assertEquals(budget + 2, DayBudget.runs(db, now))
        assertEquals(0, DayBudget.left(db, cfg, now))
    }

    /** The bench's stamps (kv `ytbench:runs`) and the product's reservations (kv `youtube-runs`) counted with `events`
     * as one set: a stamp its run's row follows is that one run; a stamp no row follows (a run in flight, or one whose
     * process died before its row) is one more. */
    @Test fun theDayIsTheUnionOfTheRowsAndTheReservationsNoRowFollowed() = db { db ->
        val cfg = PhoneConfig.read(db)
        val budget = cfg.provider("youtube").budget.toInt()
        db.kvSet(DayBudget.BENCH, """["2026-11-26T11:00:00Z", "2026-11-26T11:30:00Z"]""")
        run(db, Instant.parse("2026-11-26T11:00:40Z"), "ok", runId = "ytbench:x")  // the first stamp's row
        val stamp = DayBudget.reserve(db, Instant.parse("2026-11-26T11:50:00Z"))
        run(db, Instant.parse("2026-11-26T11:50:30Z"), "ok")  // the reservation's row
        DayBudget.reserve(db, Instant.parse("2026-11-26T11:58:00Z"))  // in flight: no row yet
        run(db, Instant.parse("2026-11-26T09:00:00Z"), "error")  // a row of no reservation (an older app's)
        assertEquals("2026-11-26T11:50:00Z", stamp)
        // rows 11:00:40, 11:50:30, 09:00 = 3; the unmatched stamps 11:30 (the bench's, its process died) and 11:58
        assertEquals(5, DayBudget.runs(db, now))
        assertEquals(budget - 5, DayBudget.left(db, cfg, now))
    }

    @Test fun aReservationReleasedGivesItsSlotBackAndOnesOlderThanADayAreDropped() = db { db ->
        DayBudget.reserve(db, now.minus(Duration.ofHours(30)))
        val stamp = DayBudget.reserve(db, now.minusSeconds(5))
        assertEquals(1, DayBudget.runs(db, now))
        assertEquals("[\"${now.minusSeconds(5)}\"]", db.kvGet(DayBudget.RESERVED))
        DayBudget.release(db, stamp)
        assertEquals(0, DayBudget.runs(db, now))
    }

    /** When the day leaves [least] runs again: now when it does; else 24 hours (and a second: a run exactly 24 hours
     * old still counts) after the run whose slot frees the last of them; none for a budget under [least]. */
    @Test fun twoRunsAreFreeAgainOnceEnoughOfTheOldestRunsLeaveTheDay() = db { db ->
        val cfg = PhoneConfig.read(db)
        val budget = cfg.provider("youtube").budget.toInt()
        assertEquals(now, DayBudget.freesAt(db, cfg, now, 2), "no run yet: free now")
        val oldest = now.minus(Duration.ofHours(20))
        run(db, oldest, "ok")
        repeat(budget - 2) { run(db, now.minus(Duration.ofHours(1)), "ok") }
        assertEquals(1, DayBudget.left(db, cfg, now))
        assertEquals(oldest.plus(Duration.ofHours(24)).plusSeconds(1), DayBudget.freesAt(db, cfg, now, 2),
                     "one run left: two once the oldest leaves the day")
        assertEquals(null, DayBudget.freesAt(db, cfg, now, budget + 1), "a budget under least never leaves them")
    }
}
