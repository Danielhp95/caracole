package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.json
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlin.test.fail

/**
 * /api/search and /api/artist on the phone answer as caracole serve does: every record of vectors/web/api_search.jsonl
 * (test_conformance_search.py: a real WebApp over each search fixture, with LaCuerda's search and YouTube off, the
 * progression and LaCuerda's unlisted page answered null as the phone answers them), each fixture replayed into the
 * phone's own database and asked through the App, in the vectors' order; what a song's card says of its folder's
 * files masked on both sides.
 */
class ApiSearchTest {
    @get:Rule val tmp = TemporaryFolder()

    private val records = Corpus.records("web/api_search.jsonl")

    @Test
    fun every_record_is_what_caracole_serve_answers_over_its_fixture() {
        assertTrue(records.size > 800, "the vectors hold ${records.size} records")
        val failures = ArrayList<String>()
        var answered = 0
        for ((fixture, asked) in records.groupBy { it.extra.getValue("fixture").jsonPrimitive.content }) {
            SearchApp(tmp.newFolder(fixture), fixture).use { search ->
                for (record in asked) {
                    assertEquals("caracole.web.app.WebApp.handle", record.fn)
                    val target = record.args[1].jsonPrimitive.content
                    val out = record.out!!.jsonObject
                    val response = search.app.get(target)
                    answered++
                    val status = out.getValue("status").jsonPrimitive.int
                    if (response.status != status) {
                        failures += "$fixture $target: status ${response.status}, not $status"
                        continue
                    }
                    assertEquals("application/json; charset=utf-8", response.header("Content-Type"), target)
                    difference(out.getValue("json"), masked(response.json))?.let { failures += "$fixture $target: $it" }
                }
            }
        }
        if (failures.isNotEmpty()) {
            fail("${failures.size} of $answered answers differ from caracole serve's:\n" + failures.take(40).joinToString("\n"))
        }
        assertEquals(records.size, answered)
    }

    @Test
    fun the_vectors_were_made_with_what_the_phone_answers_null() {
        // progression and YouTube: null in every full answer; LaCuerda's own search too, as WebApp(searches_lacuerda=
        // False) answers it (its gate is vectors/web/api_search_gate.jsonl's); LaCuerda's unlisted page the phone's.
        val full = records.map { it.out!!.jsonObject.getValue("json").jsonObject }.filter { "looked" in it }
        assertTrue(full.isNotEmpty())
        for (answer in full) {
            for (name in listOf("progression", "lacuerda_search", "youtube")) {
                assertEquals("null", answer.getValue(name).toString(), "$name of ${answer["query"]}")
            }
        }
        assertTrue(full.any { it.getValue("lacuerda_unlisted").toString() != "null" }, "a LaCuerda page offered")
        assertEquals(KEYS.sorted(), full.first().keys.toList().sorted())
    }

    @Test
    fun an_answer_has_its_members_in_caracole_serves_order() {
        // The vectors are written with sorted keys; the phone's answer is in the order _found_for makes it.
        SearchApp(tmp.newFolder("ug"), "ug").use { search ->
            val answer = search.app.get("/api/search?q=creep&box=b").json.jsonObject
            assertEquals(KEYS, answer.keys.toList())
            val row = answer.getValue("library").jsonArray.first().jsonObject
            assertEquals(LIBRARY_ROW, row.keys.toList())
            val hit = answer.getValue("index").jsonArray.first().jsonObject
            assertEquals(INDEX_ROW, hit.keys.toList())
        }
    }

    private companion object {
        /** search_routes._found_for's members. */
        val KEYS = listOf(
            "query", "library", "index", "artists", "lead", "best", "hint", "progression", "unseen", "names", "removed",
            "gtptabs", "musescore", "harptabs", "harptabs_artists", "gametabs", "lacuerda", "lacuerda_artists",
            "lacuerda_unlisted", "lacuerda_leads", "lacuerda_search", "youtube", "suggest", "skipped", "partial", "looked",
        )

        /** search_routes._rows' row of your song: its own members, where its sheet can be read, then its card's. */
        val LIBRARY_ROW = listOf("id", "display", "artist", "title", "status", "review", "score", "via", "files", "links",
                                 "source", "key", "instruments")

        /** _hit_json's members, then _rows'. */
        val INDEX_ROW = listOf("artist", "title", "ug", "counts", "score", "url", "labels", "via", "no_ones", "tabs",
                               "artist_key", "title_key", "song", "same_artist", "library")
    }
}
