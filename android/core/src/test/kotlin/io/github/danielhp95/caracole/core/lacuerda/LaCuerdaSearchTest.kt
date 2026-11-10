package io.github.danielhp95.caracole.core.lacuerda

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.LaCuerdaReplay
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Instant
import kotlin.test.assertEquals
import kotlin.test.assertNull

/** lacuerda_search.py's gate, its failures and its search against Python's answers (vectors/lookup/
 * lacuerda_gate.jsonl and lacuerda_search.jsonl), and the cases a corpus line can't hold. */
class LaCuerdaSearchTest {
    @get:Rule val folder = TemporaryFolder()

    private val now = Instant.parse("2026-11-03T12:00:00Z")

    @Test fun everyGateFailureAndCountAnswersAsPythonDid() = Misses("lookup/lacuerda_gate.jsonl").also { LaCuerdaReplay.gate(it) }.assertNone()

    /** The one request, the answer stored with its kv in one savepoint, the cache's copy within 30 days, one that
     * won't parse asked once more, errors that record nothing; those that parse a page wait on html-tree. */
    @Test fun everySearchScenarioReplays() = Misses("lookup/lacuerda_search.jsonl").also { LaCuerdaReplay.search(it) }.assertNone()

    @Test fun aQuerysKeyIsItsWordsInAlphabeticalOrder() {
        assertEquals("corazon-tiza", LaCuerdaSearch.queryKey("Tiza, corazón de"))
        assertEquals("", LaCuerdaSearch.queryKey("sol y luz"))
    }

    @Test fun aFailureIsSaidAsTheRouteSaysItWithItsFullStop() {
        val failure = LaCuerdaSearch.Failure(true, 1, "a page cut short", Stamps.micros(Instant.parse("2026-11-03T12:55:00Z")))
        assertEquals(SearchGate("failed", "la flaca", "flaca",
                                "LaCuerda's search for “la flaca” failed less than an hour ago (a page cut short), so the " +
                                    "page won't send it by itself before 2026-11-03 12:55 UTC."),
                     SearchGate.of("la flaca", LaCuerdaSearch.Gate("failed", "flaca", failure = failure)))
        assertNull(SearchGate.of("la flaca", null))
    }

    @Test fun aFailuresWordsAreCollapsedAndCutAt200CodePoints() {
        TestDb.fresh(folder.root).use { database ->
            database.writeBlocking { db ->
                LaCuerdaSearch.recordFailure(db, "boca", now, " uno\n\tdos ")
                LaCuerdaSearch.recordFailure(db, "flaca", now, "😀".repeat(250))
                val failures = db.kvGet(LaCuerdaSearch.FAILED_KEY)!!
                assertEquals("{\"boca\": {\"at\": \"2026-11-03T12:00:00Z\", \"error\": \"uno dos\"}, \"flaca\": {\"at\": " +
                                 "\"2026-11-03T12:00:00Z\", \"error\": \"${"😀".repeat(200)}\"}}", failures)
                val failed = LaCuerdaSearch.failed(db, "boca", now.plusSeconds(3599))!!
                assertEquals(true to "uno dos", failed.own to failed.error)
                assertNull(LaCuerdaSearch.failed(db, "boca", now.plusSeconds(3601)))
            }
        }
    }

    @Test fun theGateSaysAutoThenAskedOnceASearchIsRecorded() {
        TestDb.fresh(folder.root).use { database ->
            database.writeBlocking { db ->
                val cfg = PhoneConfig.DEFAULTS
                assertEquals("auto", LaCuerdaSearch.gate(cfg, db, "corazón de tiza", strong = false, now = now)?.state)
                assertNull(LaCuerdaSearch.gate(cfg, db, "corazón de tiza", strong = true, now = now))
                db.kvSetJson(LaCuerdaSearch.KV_PREFIX + "corazon-tiza", JsonObject(mapOf("at" to JsonPrimitive("2026-11-02T12:00:00Z"))))
                assertEquals(SearchGate("asked", "tiza corazón", "corazon-tiza", null),
                             LaCuerdaSearch.gate(cfg, db, "tiza corazón", now))
            }
        }
    }
}
