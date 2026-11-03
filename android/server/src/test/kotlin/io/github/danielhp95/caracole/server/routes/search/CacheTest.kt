package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.server.testing.json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The offline indexes' answers are kept a while (search_routes._index_answers, WebApp's `_found`): 300 s, the 128
 * queries made last, by query; dropped by SearchRoutes.invalidate, after an index import or a sync.
 */
class CacheTest {
    @get:Rule val tmp = TemporaryFolder()

    private class Clock(var seconds: Double = 1000.0)

    @Test
    fun an_answer_is_kept_300_seconds() {
        val clock = Clock()
        val cache = AnswerCache<String>(now = { clock.seconds })
        cache.put("creep", "answer")
        clock.seconds += 299.9
        assertEquals("answer", cache.get("creep"))
        clock.seconds += 0.1
        assertNull(cache.get("creep"), "300 s old: made again")
        assertNull(cache.get("oasis"))
    }

    @Test
    fun the_128_made_last_are_kept_the_oldest_going_first() {
        val cache = AnswerCache<Int>()
        for (n in 0 until AnswerCache.SIZE) cache.put("q$n", n)
        cache.put("q0", -1)  // made again: in its place, as a dict keeps a key
        cache.put("new", 128)
        assertEquals(AnswerCache.SIZE, cache.count)
        assertNull(cache.get("q0"), "the first made goes first, made again or not")
        assertEquals(1, cache.get("q1"))
        assertEquals(128, cache.get("new"))
    }

    @Test
    fun clear_drops_them_all() {
        val cache = AnswerCache<String>()
        cache.put("creep", "answer")
        cache.clear()
        assertNull(cache.get("creep"))
        assertEquals(0, cache.count)
    }

    @Test
    fun an_answer_begun_before_a_clear_is_not_kept() {
        // An import's end drops the answers while a search reads the indexes as they were: its answer isn't kept.
        val cache = AnswerCache<String>()
        val since = cache.era
        cache.clear()
        cache.put("creep", "read before the import", since)
        assertNull(cache.get("creep"))
        cache.put("creep", "read after it", cache.era)
        assertEquals("read after it", cache.get("creep"))
    }

    // --- through the route, over the ug fixture ---------------------------------------------------------------------

    private val creep = "/api/search?q=creep&box=b"

    private fun ugSongs(search: SearchApp) = search.app.get(creep).json.jsonObject.getValue("index") as JsonArray

    @Test
    fun a_search_reads_the_index_kept_until_the_routes_are_invalidated() {
        SearchApp(tmp.newFolder("ug"), "ug").use { search ->
            val before = ugSongs(search)
            assertTrue(before.isNotEmpty())
            search.app.database.writeBlocking { it.execute("DELETE FROM ug_index") }
            assertEquals(before, ugSongs(search), "the answer kept")
            search.routes.invalidate()
            assertEquals(JsonArray(emptyList()), ugSongs(search), "read again: the index is empty now")
            val hint = search.app.get(creep).json.jsonObject.getValue("hint").jsonPrimitive.content
            assertEquals(Looked.UG_EMPTY, hint)
        }
    }

    @Test
    fun a_search_reads_the_index_again_once_its_answer_is_300_seconds_old() {
        SearchApp(tmp.newFolder("ug"), "ug").use { search ->
            val clock = Clock()
            search.routes.answers.now = { clock.seconds }
            val before = ugSongs(search)
            search.app.database.writeBlocking { it.execute("DELETE FROM ug_index") }
            clock.seconds += 299.0
            assertEquals(before, ugSongs(search))
            clock.seconds += 1.0
            assertEquals(JsonArray(emptyList()), ugSongs(search))
        }
    }
}
