package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.testing.TestDb
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Duration
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** The search's and the video's gate and the YouTube record (SearchGate, Records), by hand: the corpus's gate.jsonl
 * and record.jsonl are YouTubeReplay's, which YouTubeRulesTest runs. */
class SearchGateTest {
    @get:Rule val tmp = TemporaryFolder()

    private val now = Instant.parse("2026-11-26T12:00:00Z")
    private val states = YouTubeData.read().texts("states", YouTubeData.read().json.getValue("search") as kotlinx.serialization.json.JsonObject)

    private fun <T> db(block: (Db) -> T): T = TestDb.fresh(tmp.newFolder()).use { it.writeBlocking(block) }

    @Test fun aFailureRecordedPausesItsQueryForTheHourAndThreePauseEveryQuery() = db { db ->
        val cfg = PhoneConfig.read(db)
        val q = "Radiohead Creep"
        assertEquals(states[2], SearchGate.gate(cfg, db, q, false, now)!!.state)
        SearchGate.recordFailure(db, SearchGate.queryKey(q), now, "boom")
        assertEquals(states[3], SearchGate.gate(cfg, db, q, false, now.plusSeconds(60))!!.state)
        assertEquals(states[2], SearchGate.gate(cfg, db, q, false, now.plus(Duration.ofMinutes(61)))!!.state)
        SearchGate.recordFailure(db, "a", now, "x")
        SearchGate.recordFailure(db, "b", now, "y")
        assertEquals(states[3], SearchGate.gate(cfg, db, "anything else", false, now.plusSeconds(1))!!.state)
        assertEquals(states[3], SearchGate.videoGate(cfg, db, "dQw4w9WgXcQ", now.plusSeconds(1)).state)
    }

    @Test fun thePhonesOwnReasonItMakesNoSheetFromAVideoStopsBothGates() = db { db ->
        val cfg = PhoneConfig.read(db)
        assertNull(SearchGate.gate(cfg, db, "Radiohead Creep", false, now, routeWhy = "the chord models aren't here"))
        val video = SearchGate.videoGate(cfg, db, "dQw4w9WgXcQ", now, routeWhy = "the chord models aren't here")
        assertEquals(states[5] to "the chord models aren't here", video.state to video.why)
    }

    @Test fun aBlockCoolsBothGatesUntilItsCooldownEnds() = db { db ->
        val cfg = PhoneConfig.read(db)
        Health.recordBlock(db, "youtube", now, "429")
        assertEquals(states[4], SearchGate.gate(cfg, db, "Radiohead Creep", false, now.plusSeconds(60))!!.state)
        assertEquals(states[4], SearchGate.videoGate(cfg, db, "dQw4w9WgXcQ", now.plusSeconds(60)).state)
        assertEquals(states[2], SearchGate.gate(cfg, db, "Radiohead Creep", false, now.plus(Duration.ofDays(3)))!!.state)
    }

    @Test fun aRecordWrittenIsReadBackAsItWas() = db { db ->
        val record = Record(video = Video("dQw4w9WgXcQ", "Creep", "Radiohead - Topic", 239.0), source = "search",
            missingAt = "2026-11-01T00:00:00Z", skip = listOf("AAAAAAAAAAA"))
        Records.save(db, 7, record)
        assertEquals(record, Records.load(db, 7))
        assertEquals(Record(), Records.load(db, 8))
    }
}
