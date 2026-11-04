package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.html.Html
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.ScenarioWorld
import io.github.danielhp95.caracole.core.testing.Scenarios
import io.github.danielhp95.caracole.core.ug.FetchContext
import io.github.danielhp95.caracole.core.ug.Rank
import io.github.danielhp95.caracole.core.ug.SongFetchOutcome
import io.github.danielhp95.caracole.core.ug.UgFetch
import io.github.danielhp95.caracole.core.ug.UgPage
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long

/**
 * UG's lookup path for a matched song (vectors/lookup/ug_sheet.jsonl, ug_keep.jsonl; tests/test_conformance_ug_fetch.py)
 * replayed as Python recorded it: each record's passes of `UgFetch.processSong` (or `keepVersion`s) in its world, the
 * requests in order, the rows, kv and files written, the events and the result compared (core.testing.Scenarios).
 * UgFetchSheetTest and KeepVersionTest call each part on the JVM; CorpusOnDeviceTest runs them all under ART.
 */
object UgFetchReplay : AreaReplay {
    override val area = "ug-fetch"

    const val SHEET = "lookup/ug_sheet.jsonl"
    const val KEEP = "lookup/ug_keep.jsonl"

    /** Phase A guard: a page is read by lane ug-pages' UgPage over lane html-tree's core.html, and ranked by lane
     * rank-coverage's Rank and Coverage; until each has merged, the records wait (waiting on ug-pages, rank-coverage
     * and html-tree). */
    val ready: Boolean by lazy {
        runCatching {
            Html.parse("<p>")
            UgPage.kindOf("Chords")
            Rank.priorMean(emptyList())
        }.isSuccess
    }

    override fun replay(misses: Misses) {
        if (!ready) return  // waiting on ug-pages, rank-coverage and html-tree
        sheet(misses)
        keep(misses)
    }

    /** The records of a vector, its header left out. */
    fun records(name: String): List<JsonObject> = Corpus.lines(name).filter { it["header"] != JsonPrimitive(true) }

    /** vectors/lookup/ug_sheet.jsonl: each pass of a record, `process_song` in turn through one client. */
    fun sheet(misses: Misses) {
        for (record in records(SHEET)) {
            val kw = record.getValue("kw").jsonObject
            val song = kw.getValue("song").jsonPrimitive.long
            Scenarios.replay(record, misses) { world ->
                kw.getValue("passes").jsonArray.map { spec ->
                    val pass = spec.jsonObject
                    outcome(UgFetch.processSong(context(world, pass), Songs.byId(world.db, song)!!,
                                                guitar = pass.getValue("guitar").jsonPrimitive.boolean))
                }
            }
        }
    }

    /** vectors/lookup/ug_keep.jsonl: `keep_version` of each tab in turn, each with a context of its own. */
    fun keep(misses: Misses) {
        for (record in records(KEEP)) {
            val kw = record.getValue("kw").jsonObject
            val song = kw.getValue("song").jsonPrimitive.long
            val pass = kw.getValue("pass").jsonObject
            Scenarios.replay(record, misses) { world ->
                kw.getValue("tabs").jsonArray.map { tab ->
                    UgFetch.keepVersion(context(world, pass), Songs.byId(world.db, song)!!, tab.jsonPrimitive.long)
                }
            }
        }
    }

    /** A pass's FetchContext in the record's world: its client, the phone's overrides, the pass's rank. */
    fun context(world: ScenarioWorld, pass: JsonObject): FetchContext = FetchContext(
        world.db, world.clients.getValue("ug"), Overrides.read(world.db), rank(pass.getValue("rank").jsonObject),
        LibraryStore(world.library), world.now, maxPagesPerGroup = pass.getValue("max_pages_per_group").jsonPrimitive.int,
        guitarPagesPerGroup = pass.getValue("guitar_pages_per_group").jsonPrimitive.int,
        versions = pass.getValue("versions").jsonPrimitive.boolean,
    )

    /** config.RankPolicy's fields, by Python's names. */
    fun rank(o: JsonObject): RankPolicy = RankPolicy(
        coverageThreshold = o.getValue("coverage_threshold").jsonPrimitive.double,
        lineMatch = o.getValue("line_match").jsonPrimitive.double, priorVotes = o.getValue("prior_votes").jsonPrimitive.double,
        scoredSheets = o.getValue("scored_sheets").jsonPrimitive.int,
        labelPenalty = o.getValue("label_penalty").jsonPrimitive.double,
        variantBonus = o.getValue("variant_bonus").jsonPrimitive.double,
    )

    /** SongFetchOutcome as helpers.corpus.plain writes it. */
    fun outcome(o: SongFetchOutcome): Map<String, Any?> = linkedMapOf(
        "song_id" to o.songId, "sheet" to o.sheet, "tab" to o.tab, "requests" to o.requests, "settled" to o.settled,
        "kept_versions" to o.keptVersions,
    )
}
