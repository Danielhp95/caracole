package io.github.danielhp95.caracole.server.routes

import io.github.danielhp95.caracole.core.sync.Difference
import io.github.danielhp95.caracole.core.sync.SyncOutcome
import io.github.danielhp95.caracole.core.sync.SyncUnit
import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The lines a sync's or an import's job says of what it did (SyncRoutes.said: what it took and gave, then what it
 * left), against vectors/sync/said.jsonl's `said` (tests/test_conformance_sync_said.py): each outcome's lines, those of
 * commands/peer.py's done_lines and left_line, as the phone's Journal says them. */
class SyncSaidReplayTest {
    private fun text(e: JsonElement) = e.jsonPrimitive.content
    private fun unit(e: JsonElement?): SyncUnit? = e?.takeUnless { it is JsonNull }?.jsonObject?.let {
        SyncUnit(text(it.getValue("id")), text(it.getValue("label")), text(it.getValue("digest")))
    }

    @Test fun `every outcome of said jsonl is said in the job's Output as Python says it`() {
        val records = Corpus.records("sync/said.jsonl")
        assertTrue(records.size >= 10, "${records.size} records")
        for (r in records) {
            val given = r.extra.getValue("in").jsonObject
            val found = given.getValue("found").jsonArray.map { d ->
                d.jsonObject.let {
                    Difference(text(it.getValue("id")), text(it.getValue("label")), unit(it["mine"]), unit(it["theirs"]),
                               text(it.getValue("proposal")), text(it.getValue("why")))
                }
            }
            val taken = given.getValue("taken").jsonArray.map(::text)
            val gave = given.getValue("given").jsonArray.map(::text)
            val left = given.getValue("left").jsonArray.map { e -> e.jsonArray.let { text(it[0]) to text(it[1]) } }
            val ids = left.map { it.first }.toSet()
            val went = (taken + gave).toSet()
            val outcome = SyncOutcome(taken, gave, left, 0, emptyList(), null,
                                      found.filter { it.id in ids }.associate { it.id to it.label },
                                      found.filter { it.id in went })
            assertEquals(r.out!!.jsonObject.getValue("said").jsonArray.map(::text), SyncRoutes.said(outcome),
                         text(r.extra.getValue("case")))
        }
    }
}
