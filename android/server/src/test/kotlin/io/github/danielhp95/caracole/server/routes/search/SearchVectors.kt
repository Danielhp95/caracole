package io.github.danielhp95.caracole.server.routes.search

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.server.page.SongCards
import io.github.danielhp95.caracole.server.routes.SearchRoutes
import io.github.danielhp95.caracole.server.testing.TestApp
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assume
import java.io.File
import java.math.BigDecimal

// What the search routes' tests share: the fixtures as the vectors' answers were made over, the cards' masked members,
// and JSON compared as the corpus compares it.

/** A song's card as the library page's data has it, with the members of it a search row reads: its files, where its
 * sheet came from, its key, what it holds for one instrument. The vectors mask them all (`"*"`). */
internal object PageCards : SongCards {
    override fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject> = songs.associate { s ->
        s.id to obj("id" to s.id, "files" to emptyList<Any>(), "source" to null, "key" to null,
                    "instruments" to emptyList<Any>())
    }
}

/** The search routes over a fixture of the search corpus (vectors/search/fixtures/<name>.jsonl), replayed into a
 * fresh database in [dir], as test_conformance_search.py's WebApp reads it; [routes] is the module made. */
internal class SearchApp(dir: File, fixture: String?, cards: SongCards = PageCards) : AutoCloseable {
    lateinit var routes: SearchRoutes
    val app = TestApp(dir, modules = { db -> listOf(SearchRoutes(db, cards).also { routes = it }) })

    init {
        if (fixture != null) app.database.writeBlocking { Fixtures.load(it, "search/fixtures/$fixture.jsonl") }
    }

    override fun close() = app.close()
}

/** test_conformance_search.masked: what a song's card says of its folder's files, `"*"` in every object with
 * `links`. */
internal fun masked(value: JsonElement): JsonElement = when (value) {
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
internal fun difference(expected: JsonElement, actual: JsonElement, at: String = "$"): String? {
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

/**
 * The lanes the search routes' answers are made by, and theirs (the plan's §7.0, Phase A): while one of them hasn't
 * landed, its `TODO("lane …")` is no failure of this port, and a test that meets one is skipped, naming it. Once they
 * all have, none is left to meet, and every test runs whole; a TODO of any other lane fails.
 */
internal object Producers {
    val LANES = setOf(
        "search-ug", "search-suggest", "search-sites", "search-lacuerda", "song-names", "library-page", "search-query",
        "keys", "py-unicode", "pinyin", "fuzz",
    )

    /** The lane a TODO names, else null. */
    fun laneOf(e: Throwable): String? =
        (e as? NotImplementedError)?.let { Regex("lane ([a-z0-9-]+)").find(it.message ?: "")?.groupValues?.get(1) }

    /** Skips the test (JUnit's Assume) when [lanes] are all of [LANES]; fails it for any other. */
    fun waitOn(lanes: Collection<String>) {
        if (lanes.isEmpty()) return
        val others = lanes.filter { it !in LANES }
        check(others.isEmpty()) { "a TODO of lanes $others, which the search routes don't wait on" }
        Assume.assumeTrue("waiting on lanes ${lanes.sorted()}", false)
    }

    /** [block], or the test skipped where it meets a TODO of one of [LANES]. */
    fun <T> needs(block: () -> T): T = try {
        block()
    } catch (e: NotImplementedError) {
        waitOn(listOfNotNull(laneOf(e)).ifEmpty { throw e })
        throw e
    }
}
