package io.github.danielhp95.caracole.core.sync.client

import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.file.FileError
import io.github.danielhp95.caracole.core.sync.internal.client.Give
import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** The phone's give within what the computer takes of a push, held to peer_push.py by vectors/sync/push.jsonl
 * (tests/test_conformance_sync_push.py): its limits, the words of a unit left, and a give cut into pushes. */
class GiveTest {
    private val records = Corpus.records("sync/push.jsonl")

    @Test fun `the phone's limits are those the computer's push routes declare`() {
        val limits = records.single { it.fn == "limits" }.out!!.jsonObject
        assertEquals(limits.getValue("POST /peer/push/new").jsonPrimitive.long, PeerClient.PUSH_NEW_MAX)
        assertEquals(limits.getValue("POST /peer/push").jsonPrimitive.long, PeerClient.PUSH_DOCUMENT_MAX)
        assertEquals(limits.getValue("POST /peer/push/file").jsonPrimitive.long, PeerClient.MAX_FILE.toLong())
        assertEquals(limits.getValue("push").jsonPrimitive.long, PeerClient.PUSH_MAX)
        assertEquals(Give.Limits(), Give.Limits(PeerClient.PUSH_NEW_MAX, PeerClient.PUSH_DOCUMENT_MAX, PeerClient.PUSH_MAX))
    }

    @Test fun `a unit left out of a give is said in peer_push's words`() {
        val words = records.single { it.fn == "words" }.out!!.jsonObject
        assertEquals(words.getValue("TOO_LONG").jsonPrimitive.content, Give.TOO_LONG)
        assertEquals(words.getValue("TOO_HEAVY").jsonPrimitive.content, Give.TOO_HEAVY)
        assertEquals(words.getValue("TOO_BIG").jsonPrimitive.content, FileError.TOO_BIG)
    }

    @Test fun `a give is cut into pushes as peer_push cuts it`() {
        val cases = records.filter { it.fn == "cut" }
        assertTrue(cases.size >= 9, "the cases")
        for (record in cases) {
            val case = record.extra["case"]!!.jsonPrimitive.content
            val kw = record.kw
            val header = kw.getValue("header").jsonObject
            val take = kw.getValue("take").jsonArray.map { it.jsonObject }
            val byId = take.associateBy { it.getValue("id").jsonPrimitive.content }
            val entries = take.map { e ->
                Give.Entry(e.getValue("id").jsonPrimitive.content, text(e["expected"]), text(e["digest"]),
                           e["unit"] as? JsonObject)
            }
            val sizes = kw.getValue("sizes").jsonObject.mapValues { it.value.jsonPrimitive.long }
            val limits = kw.getValue("limits").jsonObject.let { l ->
                Give.Limits(l.getValue("new").jsonPrimitive.long, l.getValue("document").jsonPrimitive.long,
                            l.getValue("files").jsonPrimitive.long)
            }
            val (pushes, left) = Give.cut(entries, sizes, limits, kw.getValue("from").jsonPrimitive.content) { es ->
                JsonObject(header + ("take" to JsonArray(es.map { byId.getValue(it.id) })))
            }
            val out = record.out!!.jsonObject
            assertEquals(out.getValue("pushes").jsonArray.map { p -> p.jsonArray.map { it.jsonPrimitive.content } },
                         pushes.map { p -> p.map { it.id } }, case)
            assertEquals(out.getValue("left").jsonArray.map { l ->
                l.jsonArray[0].jsonPrimitive.content to l.jsonArray[1].jsonPrimitive.content
            }, left, case)
        }
    }

    private fun text(e: kotlinx.serialization.json.JsonElement?): String? = (e as? JsonPrimitive)?.takeIf { it.isString }?.content
}
