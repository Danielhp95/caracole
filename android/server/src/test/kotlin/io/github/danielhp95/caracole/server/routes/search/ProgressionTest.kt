package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.routes.SearchRoutes
import io.github.danielhp95.caracole.server.testing.PageCards
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.replays.CardsReplay
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** /api/search's `progression` on the phone, as caracole serve's: the progression a query types or names, how many of
 * your songs play it (their progressions' records, kv `render:progressions:<id>`), and those songs among your rows. */
class ProgressionTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test
    fun `every search of the cards' library says the progression caracole serve says`() {
        val misses = Misses("${CardsReplay.VECTOR}'s searches")
        CardsReplay.replay(misses, setOf(CardsReplay.SEARCH))
        assertTrue(misses.checked >= 9, "${misses.checked} searches checked")
        misses.assertNone()
    }

    @Test
    fun `a progression's songs come after those its words found, five at most, each once`() {
        TestApp(tmp.newFolder(), modules = { db -> listOf(SearchRoutes(db, PageCards)) }).use { app ->
            val keys = app.database.writeBlocking { db ->
                (1..7).map { n ->
                    db.execute("INSERT INTO songs (key, artist, title, artists, added_at, status, created_at, updated_at) " +
                                   "VALUES (?, ?, ?, ?, ?, 'found', ?, ?)",
                               "band/song-$n", "Band", "Song $n", """["Band"]""", "2026-10-0${n}T00:00:00Z", "x", "x")
                    val id = db.lastRowid()
                    db.kvSet("render:progressions:$id", RECORD)
                    id
                }
            }
            val pop = app.get("/api/search?q=I+V+vi+IV&box=b").json.jsonObject
            val said = pop.getValue("progression").jsonObject
            assertEquals(7, said.getValue("songs").jsonPrimitive.int)
            assertEquals("the pop progression", said.getValue("name").jsonPrimitive.content)
            val rows = pop.getValue("library").jsonArray.map { it.jsonObject }
            assertEquals(5, rows.size, "LIBRARY_HITS of them")
            assertTrue(rows.all { it.getValue("via").jsonPrimitive.content == "progression" })
            assertEquals(rows.size, rows.map { it.getValue("id") }.toSet().size)
            assertTrue(rows.all { it.getValue("id").jsonPrimitive.content.toLong() in keys })

            val words = app.get("/api/search?q=Song+3&box=b").json.jsonObject
            assertEquals(JsonNull, words.getValue("progression"), "words are no progression")
        }
    }

    private companion object {
        /** A sheet that plays the pop progression in C, as progressions.record keeps it. */
        const val RECORD = """{"key": "C major", "sections": [{"section": null, "numerals": ["I", "V", "vi", "IV"], """ +
            """"repeats": 2, "name": "the pop progression", "ending": null, "key": "I V vi IV", "contains": []}]}"""
    }
}
