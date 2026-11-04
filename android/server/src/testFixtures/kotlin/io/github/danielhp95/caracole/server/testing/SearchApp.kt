package io.github.danielhp95.caracole.server.testing

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.server.page.SongCards
import io.github.danielhp95.caracole.server.routes.SearchRoutes
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.math.BigDecimal

// What the search routes' replays and tests share (WebReplay, the tests of server.routes.search): the fixtures as the
// vectors' answers were made over, the cards' masked members, and JSON compared as the corpus compares it.

/** A song's card as the library page's data has it, with the members of it a search row reads: its files, where its
 * sheet came from, its key, what it holds for one instrument. The vectors mask them all (`"*"`). */
object PageCards : SongCards {
    override fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject> = songs.associate { s ->
        s.id to JsonObject(linkedMapOf(
            "id" to JsonPrimitive(s.id), "files" to JsonArray(emptyList()), "source" to JsonNull, "key" to JsonNull,
            "instruments" to JsonArray(emptyList()),
        ))
    }
}

/** The search routes over a fixture of the search corpus (vectors/search/fixtures/<name>.jsonl), replayed into a
 * fresh database in [dir], as test_conformance_search.py's WebApp reads it, with the sites [enabled] names on (every
 * one by default, as there); [routes] is the module made. */
class SearchApp(dir: File, fixture: String?, cards: SongCards = PageCards, enabled: Set<String>? = null) :
    AutoCloseable {
    lateinit var routes: SearchRoutes
    val app = TestApp(dir, modules = { db ->
        listOf((if (enabled == null) SearchRoutes(db, cards) else SearchRoutes(db, cards, enabled)).also { routes = it })
    })

    init {
        if (fixture != null) app.database.writeBlocking { Fixtures.load(it, "search/fixtures/$fixture.jsonl") }
    }

    override fun close() = app.close()
}

/** JSON as the web vectors compare it. */
object WebJson {
    /** test_conformance_search.masked: what a song's card says of its folder's files, `"*"` in every object with
     * `links`. */
    fun masked(value: JsonElement): JsonElement = when (value) {
        is JsonArray -> JsonArray(value.map { masked(it) })
        is JsonObject -> {
            val card = "links" in value
            JsonObject(value.mapValues { (k, v) -> if (card && k in CARD) JsonPrimitive("*") else masked(v) })
        }
        else -> value
    }

    private val CARD = setOf("links", "files", "source", "key", "instruments")

    /** Where [actual] first differs from [expected], as the corpus compares JSON: objects as maps, arrays in order, a
     * number by its kind (an int, a float) and its value; null when they agree. */
    fun difference(expected: JsonElement, actual: JsonElement, at: String = "$"): String? {
        fun said(e: JsonElement) = e.toString().let { if (it.length > 200) it.take(200) + "…" else it }
        return when {
            expected is JsonObject && actual is JsonObject -> {
                if (expected.keys != actual.keys) {
                    "$at: members ${expected.keys - actual.keys} missing, ${actual.keys - expected.keys} more"
                } else {
                    expected.keys.firstNotNullOfOrNull { difference(expected.getValue(it), actual.getValue(it), "$at.$it") }
                }
            }
            expected is JsonArray && actual is JsonArray -> {
                if (expected.size != actual.size) {
                    "$at: ${expected.size} items, not ${actual.size}: expected ${said(expected)}, got ${said(actual)}"
                } else {
                    expected.indices.firstNotNullOfOrNull { difference(expected[it], actual[it], "$at[$it]") }
                }
            }
            expected is JsonNull || actual is JsonNull ->
                if (expected is JsonNull && actual is JsonNull) null else "$at: expected ${said(expected)}, got ${said(actual)}"
            expected is JsonPrimitive && actual is JsonPrimitive -> {
                val same = when {
                    expected.isString || actual.isString -> expected.isString == actual.isString && expected.content == actual.content
                    expected.content in BOOLEANS || actual.content in BOOLEANS -> expected.content == actual.content
                    else -> integral(expected) == integral(actual) &&
                        BigDecimal(expected.content).compareTo(BigDecimal(actual.content)) == 0
                }
                if (same) null else "$at: expected ${said(expected)}, got ${said(actual)}"
            }
            else -> "$at: expected ${said(expected)}, got ${said(actual)}"
        }
    }

    private val BOOLEANS = setOf("true", "false")

    private fun integral(p: JsonPrimitive): Boolean = p.content.none { it == '.' || it == 'e' || it == 'E' }
}
