package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.SyncReplay
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull

/**
 * peer_sync's comparison on the phone against vectors/sync (tests/test_conformance_sync.py): compare over every row
 * of the design's three-way table (compare.jsonl), merged_base, record_agreement (the base's kv text byte for byte),
 * decide and compared_hash, each record Python's answer to the same call (SyncReplay's, which the device runs too).
 */
class CompareTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun replayed(vector: String, replay: (Misses) -> Unit) = Misses(vector).also(replay).assertNone()

    @Test fun compareProposesWhatPythonProposes() = replayed("sync/compare.jsonl", SyncReplay::compare)

    @Test fun theMergedBaseIsPythons() = replayed("sync/merged_base.jsonl", SyncReplay::mergedBase)

    @Test fun anAgreementIsKeptAsPythonWritesItToTheByte() =
        replayed("sync/record_agreement.jsonl", SyncReplay::recordAgreement)

    @Test fun decideTakesWhatPythonTakes() = replayed("sync/decide.jsonl", SyncReplay::decide)

    @Test fun theComparedHashIsPythons() = replayed("sync/compared_hash.jsonl", SyncReplay::comparedHash)

    @Test fun theOrderIsKindThenLabelInAnyCaseThenId() {
        fun d(id: String, label: String) = Difference(id, label, null, SyncUnit(id, label, "1"), "theirs", "only in theirs")
        val found = listOf(d("other/x", "a"), d("block/1", "a"), d("song/b", "b"), d("removed/a", "a"),
                           d("song/a2", "A"), d("song/a1", "a"), d("songbook/x", "a"), d("artist_url/x", "a"),
                           d("alias/x", "a"))
        assertEquals(listOf("song/a1", "song/a2", "song/b", "removed/a", "songbook/x", "alias/x", "artist_url/x",
                            "block/1", "other/x"), Compare.order(found).map { it.id })
        // The hash is of the order, whatever order the list comes in.
        assertEquals(Compare.comparedHash(found), Compare.comparedHash(found.reversed()))
    }

    @Test fun aLabelInAnyCaseIsItsCasefoldNeverItsLowercase() {
        fun d(id: String, label: String) = Difference(id, label, null, SyncUnit(id, label, "1"), "theirs", "only in theirs")
        val found = listOf(d("song/c", "Straße"), d("song/a", "STRASSE x"), d("song/b", "strasse"), d("song/z1", "ﬁ"),
                           d("song/z0", "fj"))
        // Python: sorted(ids, key=lambda i: (label[i].casefold(), i)); by .lower() it would be z0, b, a, c, z1.
        assertEquals(listOf("song/z1", "song/z0", "song/b", "song/c", "song/a"), Compare.order(found).map { it.id })
    }

    @Test fun decideLeavesAConflictNobodyChoseAndTakesAnEmptyChoiceAsNone() {
        val conflict = Difference("song/a", "a", SyncUnit("song/a", "a", "1"), SyncUnit("song/a", "a", "2"),
                                  "conflict", "both books changed it since the last share")
        assertEquals(emptyList<Difference>() to emptyList(), Compare.decide(listOf(conflict)))
        assertEquals(listOf(conflict) to emptyList(), Compare.decide(listOf(conflict), "theirs") { "" })
        assertEquals(emptyList<Difference>() to listOf(conflict), Compare.decide(listOf(conflict), null) { "mine" })
        val odd = conflict.copy(proposal = "neither")
        assertEquals(emptyList<Difference>() to emptyList(), Compare.decide(listOf(odd), "theirs"))
    }

    @Test fun theOwnIdIsTheOneTheSchemaMade() {
        TestDb.fresh(tmp.root).use { database ->
            database.read { db ->
                val id = Compare.ownId(db)
                assertEquals(db.kvGet("sync:id"), id)
                assertEquals(16, id.length)
            }
            database.writeBlocking { db -> db.kvDelete("sync:id") }
            database.read { db -> assertFailsWith<IllegalStateException> { Compare.ownId(db) } }
        }
    }

    @Test fun aBaseIsReadOnlyWhenItIsOfThisFormat() {
        val cases = listOf(
            null to null,
            """{"format": 3, "units": {"song/a": ["1", "t1"], "song/b": [null, "t2"]}}""" to
                mapOf("song/a" to ("1" to "t1"), "song/b" to (null to "t2")),
            // 3.0 == 3 in Python; an entry that isn't [digest or null, when] is left out; the last of a key wins.
            """{"format": 3.0, "units": {"song/a": ["1"], "song/b": [1, "t"], "song/c": ["1", 2], "song/d": "x", "song/e": ["1", "t", 3], "song/f": ["0", "t0"], "song/f": ["1", "t1"]}}""" to
                mapOf("song/f" to ("1" to "t1")),
            """{"format": 3, "units": {}}""" to emptyMap(),
            """{"format": 3}""" to null,
            """{"format": 3, "units": []}""" to null,
            """{"format": "3", "units": {}}""" to null,
            """{"format": 1, "units": {}}""" to null,
            // FORMAT 2's base, whose digests hashed UG's ratings and votes, is none: the next sync is a first one.
            """{"format": 2, "units": {"song/a": ["1", "t1"]}}""" to null,
            """{"format": true, "units": {}}""" to null,
            """{"song/a": ["1", "t"]}""" to null,
            """[]""" to null,
            """{nonsense""" to null,
            """{"format": 3, "units": {}} x""" to null,
        )
        TestDb.fresh(tmp.root).use { database ->
            for ((stored, expected) in cases) {
                database.writeBlocking { db ->
                    db.kvDelete("sync:base:peer")
                    stored?.let { db.kvSet("sync:base:peer", it) }
                }
                database.read { db -> assertEquals(expected, Compare.baseOf(db, "peer"), stored) }
            }
            database.read { db -> assertNull(Compare.baseOf(db, "nobody")) }
        }
    }

    @Test fun anAgreementKeepsWhatItDoesntSettleAndForgetsNothing() {
        TestDb.fresh(tmp.root).use { database ->
            val a = SyncUnit("song/a", "a", "1")
            val b = SyncUnit("song/b", "b", "2")
            database.writeBlocking { db ->
                assertEquals(1, Compare.recordAgreement(db, "peer", mapOf("song/a" to a, "song/b" to b), mapOf("song/a" to a), "T1"))
                assertEquals("""{"format": 3, "units": {"song/a": ["1", "T1"]}}""", db.kvGet("sync:base:peer"))
                // song/a gone on both: agreed absent; song/b still only here: unsettled.
                assertEquals(0, Compare.recordAgreement(db, "peer", mapOf("song/b" to b), emptyMap(), "T2"))
                assertEquals("""{"format": 3, "units": {"song/a": [null, "T2"]}}""", db.kvGet("sync:base:peer"))
            }
            database.read { db -> assertEquals(mapOf("song/a" to (null to "T2")), Compare.baseOf(db, "peer")) }
        }
    }

    @Test fun theDifferencesOfACompareAreItsOwnUnits() {
        val mine = mapOf("song/a" to SyncUnit("song/a", "here's", "1"))
        val theirs = mapOf("song/a" to SyncUnit("song/a", "there's", "2"), "song/b" to SyncUnit("song/b", "zed", "3"))
        val found = Compare.compare(mine, theirs, emptyMap())
        assertEquals(listOf("song/a", "song/b"), found.map { it.id })
        assertEquals(mine["song/a"], found[0].mine)
        assertEquals(theirs["song/a"], found[0].theirs)
        assertEquals("here's", found[0].label)
        assertEquals(listOf("conflict", "theirs"), found.map { it.proposal })
        assertEquals(listOf("both books changed it since the last share", "new there since the last sync"), found.map { it.why })
    }
}
