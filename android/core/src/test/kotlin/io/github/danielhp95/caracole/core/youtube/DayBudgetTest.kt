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
}
