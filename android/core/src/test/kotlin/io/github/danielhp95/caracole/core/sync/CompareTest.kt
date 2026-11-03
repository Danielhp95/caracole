package io.github.danielhp95.caracole.core.sync

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlin.test.fail

/**
 * peer_sync's comparison on the phone against vectors/sync (tests/test_conformance_sync.py): compare over every row
 * of the design's three-way table (compare.jsonl), merged_base, record_agreement (the base's kv text byte for byte),
 * decide and compared_hash, each record Python's answer to the same call.
 */
class CompareTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun text(e: JsonElement): String = e.jsonPrimitive.content
    private fun textOrNull(e: JsonElement?): String? = e?.takeUnless { it is JsonNull }?.jsonPrimitive?.content

    private fun unit(e: JsonElement?): SyncUnit? = e?.takeUnless { it is JsonNull }?.jsonObject?.let {
        SyncUnit(text(it.getValue("id")), text(it.getValue("label")), text(it.getValue("digest")))
    }

    private fun units(e: JsonElement): Map<String, SyncUnit> =
        e.jsonObject.mapValues { (_, u) -> unit(u)!! }

    private fun base(e: JsonElement?): Base? = e?.takeUnless { it is JsonNull }?.jsonObject?.mapValues { (_, entry) ->
        val pair = entry.jsonArray
        textOrNull(pair[0]) to text(pair[1])
    }

    private fun merged(e: JsonElement?): Map<String, String?>? =
        e?.takeUnless { it is JsonNull }?.jsonObject?.mapValues { (_, d) -> textOrNull(d) }

    private fun difference(e: JsonElement): Difference = e.jsonObject.let {
        Difference(text(it.getValue("id")), text(it.getValue("label")), unit(it["mine"]), unit(it["theirs"]),
                   text(it.getValue("proposal")), text(it.getValue("why")))
    }

    private fun records(name: String, fn: String): List<Record> = Corpus.records(name).also { all ->
        assertEquals(setOf(fn), all.map { it.fn }.toSet(), "$name's functions")
        assertTrue(all.isNotEmpty(), "$name has no records")
    }

    private fun check(records: List<Record>, compare: (Record) -> String?) {
        val wrong = records.mapNotNull { record ->
            assertEquals(null, record.err, "Python raised on $record")
            try {
                compare(record)
            } catch (e: Throwable) {
                "${record.extra["case"] ?: record.args}: ${e::class.simpleName}: ${e.message}"
            }
        }
        if (wrong.isNotEmpty()) fail("${wrong.size} of ${records.size} records differ:\n" + wrong.joinToString("\n"))
    }

    private fun differs(record: Record, expected: Any?, actual: Any?): String? =
        if (expected == actual) null else "${record.extra["case"] ?: record.args}:\n  Python $expected\n  Kotlin $actual"

    @Test fun compareProposesWhatPythonProposes() = check(records("sync/compare.jsonl", "caracole.peer_sync.compare")) { r ->
        val found = Compare.compare(units(r.args[0]), units(r.args[1]), merged(r.args[2]))
        differs(r, r.out!!.jsonArray.map(::difference), found)
    }

    @Test fun theMergedBaseIsPythons() = check(records("sync/merged_base.jsonl", "caracole.peer_sync.merged_base")) { r ->
        val got = Compare.mergedBase(base(r.args[0]), base(r.args[1]))
        differs(r, merged(r.out), got)
            ?: differs(r, merged(r.out)?.keys?.toList(), got?.keys?.toList())
    }

    @Test fun anAgreementIsKeptAsPythonWritesItToTheByte() {
        val records = records("sync/record_agreement.jsonl", "caracole.peer_sync.record_agreement")
        TestDb.fresh(tmp.root).use { database ->
            check(records) { r ->
                val peer = text(r.args[0])
                val key = "sync:base:$peer"
                val out = r.out!!.jsonObject
                database.writeBlocking { db ->
                    db.kvDelete(key)
                    textOrNull(r.extra["before"])?.let { db.kvSet(key, it) }
                    val agreed = Compare.recordAgreement(db, peer, units(r.args[1]), units(r.args[2]), text(r.args[3]))
                    differs(r, text(out.getValue("after")), db.kvGet(key))
                        ?: differs(r, out.getValue("agreed").jsonPrimitive.content.toInt(), agreed)
                }
            }
        }
    }

    @Test fun decideTakesWhatPythonTakes() = check(records("sync/decide.jsonl", "caracole.peer_sync.decide")) { r ->
        val found = r.args[0].jsonArray.map(::difference)
        val chosen = r.kw.getValue("choose").jsonObject.mapValues { (_, side) -> text(side) }
        val (here, there) = Compare.decide(found, textOrNull(r.args.getOrNull(1))) { chosen[it.id] }
        val out = r.out!!.jsonObject
        differs(r, out.getValue("here").jsonArray.map(::text), here.map { it.id })
            ?: differs(r, out.getValue("there").jsonArray.map(::text), there.map { it.id })
    }

    @Test fun theComparedHashIsPythons() = check(records("sync/compared_hash.jsonl", "caracole.peer_sync.compared_hash")) { r ->
        differs(r, text(r.out!!), Compare.comparedHash(r.args[0].jsonArray.map(::difference)))
    }

    @Test fun theOrderIsKindThenLabelInAnyCaseThenId() {
        fun d(id: String, label: String) = Difference(id, label, null, SyncUnit(id, label, "1"), "theirs", "only there")
        val found = listOf(d("other/x", "a"), d("block/1", "a"), d("song/b", "b"), d("removed/a", "a"),
                           d("song/a2", "A"), d("song/a1", "a"), d("songbook/x", "a"), d("artist_url/x", "a"),
                           d("alias/x", "a"))
        assertEquals(listOf("song/a1", "song/a2", "song/b", "removed/a", "songbook/x", "alias/x", "artist_url/x",
                            "block/1", "other/x"), Compare.order(found).map { it.id })
        // The hash is of the order, whatever order the list comes in.
        assertEquals(Compare.comparedHash(found), Compare.comparedHash(found.reversed()))
    }

    @Test fun decideLeavesAConflictNobodyChoseAndTakesAnEmptyChoiceAsNone() {
        val conflict = Difference("song/a", "a", SyncUnit("song/a", "a", "1"), SyncUnit("song/a", "a", "2"),
                                  "conflict", "changed on both sides since the last sync")
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
            """{"format": 2, "units": {"song/a": ["1", "t1"], "song/b": [null, "t2"]}}""" to
                mapOf("song/a" to ("1" to "t1"), "song/b" to (null to "t2")),
            // 2.0 == 2 in Python; an entry that isn't [digest or null, when] is left out; the last of a key wins.
            """{"format": 2.0, "units": {"song/a": ["1"], "song/b": [1, "t"], "song/c": ["1", 2], "song/d": "x", "song/e": ["1", "t", 3], "song/f": ["0", "t0"], "song/f": ["1", "t1"]}}""" to
                mapOf("song/f" to ("1" to "t1")),
            """{"format": 2, "units": {}}""" to emptyMap(),
            """{"format": 2}""" to null,
            """{"format": 2, "units": []}""" to null,
            """{"format": "2", "units": {}}""" to null,
            """{"format": 1, "units": {}}""" to null,
            """{"format": true, "units": {}}""" to null,
            """{"song/a": ["1", "t"]}""" to null,
            """[]""" to null,
            """{nonsense""" to null,
            """{"format": 2, "units": {}} x""" to null,
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
                assertEquals("""{"format": 2, "units": {"song/a": ["1", "T1"]}}""", db.kvGet("sync:base:peer"))
                // song/a gone on both: agreed absent; song/b still only here: unsettled.
                assertEquals(0, Compare.recordAgreement(db, "peer", mapOf("song/b" to b), emptyMap(), "T2"))
                assertEquals("""{"format": 2, "units": {"song/a": [null, "T2"]}}""", db.kvGet("sync:base:peer"))
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
        assertEquals(listOf("changed on both sides since the last sync", "new there since the last sync"), found.map { it.why })
    }
}
