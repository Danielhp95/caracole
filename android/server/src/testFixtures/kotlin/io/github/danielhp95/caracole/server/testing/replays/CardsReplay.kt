package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.page.MirrorPageData
import io.github.danielhp95.caracole.server.page.PhonePageData
import io.github.danielhp95.caracole.server.routes.SearchRoutes
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.WebJson
import io.github.danielhp95.caracole.server.testing.json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.nio.file.Files
import java.time.Instant

/**
 * The library page's cards from the phone's own library (vectors/web/cards_full.jsonl, tests/test_conformance_cards.py):
 * each library's fixture replayed into a fresh database and library folder, then
 *
 * - every `song_cards` record: PhonePageData's cards of every song (Songs.list's order) or of the songs it names, at
 *   its time, with the providers it turns off, against library_page.song_cards' whole;
 * - every `build_library_page` record: PhonePageData's page data with no mirror, but its `sites` (the mirror's);
 * - every `result_cards` record: PhonePageData's result cards of the songs it names, /api/search's rows';
 * - every `/api/search` record: the answer's `progression` and its `library` rows' id, via and score.
 *
 * Each answer is compared whole; a `song_cards` record's cards also by their members' order, which the vector says
 * apart (its `members`: a line's keys sort), `_song` field for field and every object in a card.
 */
object CardsReplay : AreaReplay {
    override val area = "cards"

    const val VECTOR = "web/cards_full.jsonl"

    const val SONG_CARDS = "caracole.library_page.song_cards"
    const val PAGE_DATA = "caracole.library_page.build_library_page"
    const val RESULT_CARDS = "caracole.library_page.result_cards"
    const val SEARCH = "caracole.web.app.WebApp.handle"

    override fun replay(misses: Misses) = replay(misses, setOf(SONG_CARDS, PAGE_DATA, RESULT_CARDS, SEARCH))

    /** The records of the functions [fns] alone (ProgressionTest's: [SEARCH]). */
    fun replay(misses: Misses, fns: Set<String>) {
        val lines = Corpus.lines(VECTOR).filter { it["header"] != JsonPrimitive(true) }
        val fixtures = lines.filter { "fixture" in it }.associate { text(it, "library") to it.getValue("fixture").jsonArray }
        val asked = lines.filter { "fn" in it && text(it, "fn") in fns }
        for ((library, records) in asked.groupBy { text(it, "library") }) {
            val dir = Files.createTempDirectory("caracole-cards-$library").toFile()
            try {
                TestApp(dir, modules = { db -> listOf(SearchRoutes(db, cards(LibraryStore(File(dir, "library"))))) }).use { app ->
                    val fixture = fixtures.getValue(library).map { it.jsonObject }
                    app.database.writeBlocking { db -> Fixtures.loadRecords(db, fixture, app.libraryDir, library) }
                    for (record in records) replay(misses, app, library, record)
                }
            } finally {
                dir.deleteRecursively()
            }
        }
    }

    private fun replay(misses: Misses, app: TestApp, library: String, record: JsonObject) {
        val fn = text(record, "fn")
        val store = LibraryStore(app.libraryDir)
        when (fn) {
            SONG_CARDS -> {
                val off = record.getValue("config").jsonObject.getValue("off").jsonArray.map { it.jsonPrimitive.content }
                val now = Instant.parse(text(record, "now"))
                val ids = (record["songs"] as? JsonArray)?.map { it.jsonPrimitive.long }
                val data = PhonePageData(MirrorPageData(null), store, { configWithout(off) }, { now })
                val made = app.database.read { db ->
                    val songs = Songs.list(db)
                    if (ids == null) {
                        JsonArray(data.data(db, text(record, "now"))["songs"] as JsonArray)
                    } else {
                        val cards = data.cards(db, ids.map { id -> songs.first { it.id == id } })
                        JsonArray(ids.map { cards.getValue(it) })
                    }
                }
                val said = "$library song_cards at ${text(record, "now")}, ${ids ?: "every song"}, off $off"
                compare(misses, said, record.getValue("out"), made, record["members"])
            }
            PAGE_DATA -> {
                val data = PhonePageData(MirrorPageData(null), store, { PhoneConfig.DEFAULTS })
                val made = app.database.read { db -> data.data(db, text(record, "now")) }
                compare(misses, "$library's page data", record.getValue("out"), JsonObject(made - "sites"))
                misses.check(made["sites"] == JsonArray(emptyList())) { "$library's page data: no mirror, no sites" }
            }
            RESULT_CARDS -> {
                val ids = record.getValue("songs").jsonArray.map { it.jsonPrimitive.long }
                val made = app.database.read { db ->
                    val songs = Songs.list(db)
                    val results = cards(store).results(db, ids.map { id -> songs.first { it.id == id } })
                    JsonArray(ids.map { results.getValue(it) })
                }
                compare(misses, "$library result_cards", record.getValue("out"), made)
            }
            SEARCH -> {
                val target = record.getValue("args").jsonArray[1].jsonPrimitive.content
                val answer = app.get(target).json.jsonObject
                val made = JsonObject(linkedMapOf(
                    "progression" to answer.getValue("progression"),
                    "library" to JsonArray(answer.getValue("library").jsonArray.map { row ->
                        val r = row.jsonObject
                        JsonArray(listOf(r.getValue("id"), r.getValue("via"), r.getValue("score")))
                    }),
                ))
                compare(misses, "$library $target", record.getValue("out"), made)
            }
            else -> misses.check(false) { "$VECTOR: no replay for $fn" }
        }
    }

    /** The phone's cards over [store], as the search's rows read them. */
    private fun cards(store: LibraryStore) = PhonePageData(MirrorPageData(null), store, { PhoneConfig.DEFAULTS })

    /** config.py's defaults with the providers [off] turned off. */
    private fun configWithout(off: List<String>): PhoneConfig = PhoneConfig.DEFAULTS.copy(
        providers = PhoneConfig.DEFAULTS.providers.mapValues { (name, p) -> if (name in off) p.copy(enabled = false) else p })

    private fun compare(misses: Misses, said: String, want: JsonElement, got: JsonElement, members: JsonElement? = null) {
        val difference = WebJson.difference(want, got) ?: members?.let { order(got, it, "") }
        misses.check(difference == null) { "$said: $difference" }
    }

    /** Where an object of [got] holds its members in another order than [members] says Python's do (the generator's
     * `_members`: an object's `[keys]` or `[keys, {key: members}]`, a list's its items', null for a value of none), or
     * null. */
    private fun order(got: JsonElement, members: JsonElement, at: String): String? = when {
        members is JsonNull -> null
        got is JsonObject -> {
            val said = members.jsonArray
            val keys = said[0].jsonArray.map { it.jsonPrimitive.content }
            if (got.keys.toList() != keys) {
                "$at: members ${got.keys.toList()}, Python's $keys"
            } else {
                (said.getOrNull(1) as? JsonObject)?.entries
                    ?.firstNotNullOfOrNull { (key, inner) -> got[key]?.let { order(it, inner, "$at.$key") } }
            }
        }
        got is JsonArray -> {
            val said = members.jsonArray
            got.indices.firstNotNullOfOrNull { i -> said.getOrNull(i)?.let { order(got[i], it, "$at[$i]") } }
        }
        else -> null
    }

    private fun text(o: JsonObject, name: String): String = o.getValue(name).jsonPrimitive.content
}
