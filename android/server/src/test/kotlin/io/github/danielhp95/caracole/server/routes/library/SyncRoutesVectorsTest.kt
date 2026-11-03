package io.github.danielhp95.caracole.server.routes.library

import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.SyncEngine
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.sync.FakeComputer
import io.github.danielhp95.caracole.server.jobs.JobQueue
import io.github.danielhp95.caracole.server.routes.SyncRoutes
import io.github.danielhp95.caracole.server.routes.SyncSettings
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.json
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * Every record of vectors/web/sync_routes.jsonl, caracole serve's Sync tab routes over a fixture of the sync corpus and
 * another caracole's state, asked of the phone's SyncRoutes over the same: here, the fixture loaded into the phone's
 * database with its id and kv, its library's name; there, a computer answering its state as the record's
 * `peer_state` (then `peer_state_then`, for the Sync that follows a comparison) gives it. The phone answers what
 * Python answered, the comparison's id masked, its status and its words alike; a Sync queued is the computer's view
 * of the same job but for the stages the phone's sync has and the computer's hasn't (mirror and index, §5.3), and its
 * comparison the one the computer's queued command names (`--compared=<hash>`).
 */
class SyncRoutesVectorsTest {
    @get:Rule val tmp = TemporaryFolder()

    private val masked = "<comparison>"

    /** The phone's answer to one record, over its own sides. */
    private fun replay(record: Record, n: Int) {
        val here = record.extra.getValue("here").jsonObject
        val note = "${record.fn}: ${record.extra["note"]?.jsonPrimitive?.content}"
        val dir = tmp.newFolder("record-$n")
        val computer = FakeComputer(File(dir, "computer"))
        val asked = AtomicInteger()
        val first = record.extra["peer_state"] as? JsonObject
        val then = record.extra["peer_state_then"] as? JsonObject
        computer.answers["GET /api/peer/state"] = { exchange ->
            val state = if (asked.getAndIncrement() == 0 || then == null) first else then
            FakeComputer.json(exchange, 200, assertNotNull(state, "$note: no state to answer"))
        }
        val scope = CoroutineScope(Job().apply { cancel() })  // a Sync queued stays so: the record is its answer
        val queue = JobQueue(scope)
        val settings = object : SyncSettings {
            override var address: String? = null
            override fun remember(address: String) {}
        }
        lateinit var engine: SyncEngine
        val app = TestApp(dir, modules = { database ->
            engine = SyncEngine(database, LibraryStore(File(dir, "library")), File(dir, "state"),
                                client = { PeerClient(computer.address) }, mirrorRefresh = null)
            listOf(SyncRoutes(engine, queue, settings, database, afterSync = {}, name = here.getValue("name").jsonPrimitive.content))
        })
        try {
            app.database.writeBlocking { db ->
                Fixtures.load(db, here.getValue("fixture").jsonPrimitive.content + ".jsonl", app.libraryDir)
                db.kvSet("sync:id", here.getValue("id").jsonPrimitive.content)
                for ((key, value) in here.getValue("kv").jsonObject) db.kvSet(key, value.jsonPrimitive.content)
            }
            val form = (record.extra["form"] as? JsonObject).orEmpty().mapValues { it.value.jsonPrimitive.content }
            val answer = when (record.fn) {
                "GET /api/sync" -> app.script("/api/sync")
                "POST /sync/compare" -> app.postScript("/sync/compare", form.toList())
                "POST /sync/apply" -> {
                    val compare = record.extra.getValue("compare").jsonObject.mapValues { it.value.jsonPrimitive.content }
                    val compared = app.postScript("/sync/compare", compare.toList())
                    assertEquals(200, compared.status, "$note: its comparison ${compared.json}")
                    val id = compared.json.jsonObject.getValue("comparison").jsonPrimitive.content
                    val hash = assertNotNull(engine.comparison(id)).hash
                    val queued = record.extra.getValue("queued").jsonArray
                    if (queued.isNotEmpty()) {
                        assertTrue("--compared=$hash" in queued.single().jsonArray.map { it.jsonPrimitive.content },
                                   "$note: the comparison the computer's command names is the phone's")
                    }
                    app.postScript("/sync/apply", form.map { (k, v) -> k to if (k == "comparison" && v == masked) id else v })
                }
                else -> throw AssertionError("$note: no such route")
            }
            assertEquals(record.extra.getValue("status").jsonPrimitive.int, answer.status, "$note: ${answer.json}")
            assertEquals(record.out, shown(record.fn, answer.json), note)
        } finally {
            app.close()
            computer.close()
            scope.cancel()
        }
    }

    /** The phone's answer as the record keeps Python's: a comparison's id masked, and a Sync's stages the
     * computer's sync has alone. */
    private fun shown(fn: String, answer: JsonElement): JsonElement {
        val data = answer.jsonObject
        if (fn == "POST /sync/compare" && "comparison" in data) {
            return JsonObject(data + ("comparison" to JsonPrimitive(masked)))
        }
        val job = data["job"] as? JsonObject ?: return answer
        val steps = job.getValue("steps").jsonArray.filter {
            it.jsonObject.getValue("name").jsonPrimitive.content !in PHONE_ALONE
        }
        return JsonObject(mapOf("job" to JsonObject(job + ("steps" to JsonArray(steps)))))
    }

    @Test fun everyRecordIsThePhonesAnswerOverTheSameSides() {
        val records = Corpus.records("web/sync_routes.jsonl")
        assertEquals(setOf("GET /api/sync", "POST /sync/compare", "POST /sync/apply"), records.map { it.fn }.toSet())
        records.forEachIndexed { n, record -> replay(record, n) }
        assertTrue(records.size >= 15)
        assertTrue(records.any { it.out is JsonObject && (it.out as JsonObject)["job"] is JsonObject })
        assertTrue(records.any { (it.out as? JsonObject)?.get("synced_before").let { at -> at is JsonPrimitive && at !is JsonNull } })
    }

    private companion object {
        /** The phone's sync's stages the computer's hasn't (§5.3). */
        val PHONE_ALONE = setOf("mirror", "index")
    }
}
