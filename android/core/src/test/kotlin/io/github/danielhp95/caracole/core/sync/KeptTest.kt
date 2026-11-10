package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.SyncReplay
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals

/**
 * The remembered answer on the phone (the sync redesign's §3.1) against vectors/sync/kept.jsonl
 * (tests/test_conformance_sync_kept.py): merged_kept, compare with kept answers, record_kept and record_agreement to
 * the kv's byte, kept_of and a state document's kept, each record Python's answer to the same call (SyncReplay's,
 * which the device runs too).
 */
class KeptTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun everyRecordOfKeptJsonlReplays() = Misses(SyncReplay.KEPT).also(SyncReplay::kept).assertNone()

    @Test fun anAgreementDropsTheKeptAnswerOfEachUnitItAgreesOnAndKeepsTheOthers() {
        fun u(id: String, digest: String) = SyncUnit(id, id, digest)
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                assertEquals(0, Compare.recordKept(db, "peer", emptyMap(), "T1"))
                assertEquals(null, db.kvGet("sync:base:peer"))  // none answered writes nothing
                assertEquals(3, Compare.recordKept(db, "peer", mapOf("song/a" to ("ah" to "at"), "song/b" to ("bh" to null),
                                                                     "song/c" to (null to "ct")), "T1"))
                assertEquals("""{"format": 3, "units": {}, "kept": {"song/a": ["ah", "at", "T1"], "song/b": ["bh", null, "T1"], """ +
                             """"song/c": [null, "ct", "T1"]}}""", db.kvGet("sync:base:peer"))
                // song/a agreed (both took this side's), song/b both lack now; song/c still differs: kept.
                val agreed = Compare.recordAgreement(db, "peer", mapOf("song/a" to u("song/a", "ah"), "song/c" to u("song/c", "x")),
                                                     mapOf("song/a" to u("song/a", "ah"), "song/c" to u("song/c", "y")), "T2")
                assertEquals(1, agreed)
                assertEquals(mapOf("song/c" to KeptEntry(null, "ct", "T1")), Compare.keptOf(db, "peer"))
                assertEquals(mapOf("song/a" to ("ah" to "T2"), "song/b" to (null to "T2")), Compare.baseOf(db, "peer"))
                // The last one agreed, the others gone on both: the base is written as before, with no "kept".
                Compare.recordAgreement(db, "peer", mapOf("song/c" to u("song/c", "y")), mapOf("song/c" to u("song/c", "y")), "T3")
                assertEquals("""{"format": 3, "units": {"song/a": [null, "T3"], "song/b": [null, "T3"], "song/c": ["y", "T3"]}}""",
                             db.kvGet("sync:base:peer"))
                assertEquals(emptyMap(), Compare.keptOf(db, "peer"))
            }
        }
    }

    @Test fun aKeptAnswerReadsOnlyFromABaseOfThisFormatItsOddEntriesLeftOut() {
        TestDb.fresh(tmp.root).use { database ->
            database.writeBlocking { db ->
                for ((stored, want) in listOf(
                    """{"format": 2, "units": {}, "kept": {"song/a": ["h", "t", "T"]}}""" to emptyMap(),
                    """{"format": 3, "units": {}, "kept": {"song/a": ["h", "t", "T"], "song/b": ["h", "t"], "song/c": [1, "t", "T"], """ +
                        """"song/d": ["h", "t", 3], "song/e": "x"}}""" to mapOf("song/a" to KeptEntry("h", "t", "T")),
                    """{"format": 3, "units": {}, "kept": []}""" to emptyMap(),
                    "{nonsense" to emptyMap(),
                )) {
                    db.kvSet("sync:base:peer", stored)
                    assertEquals(want, Compare.keptOf(db, "peer"), stored)
                }
            }
        }
        val state = JsonObject(mapOf("format" to JsonPrimitive(3), "server" to JsonNull, "units" to JsonObject(emptyMap()),
                                     "kept" to JsonObject(mapOf("song/a" to JsonArray(listOf(JsonPrimitive("h"), JsonNull,
                                                                                             JsonPrimitive("T")))))))
        assertEquals(mapOf("song/a" to KeptEntry("h", null, "T")), PeerState.read(state).kept)
    }
}
