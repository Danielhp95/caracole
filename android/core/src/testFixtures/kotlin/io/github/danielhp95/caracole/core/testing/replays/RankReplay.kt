package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.RankPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.VersionRow
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.ug.Candidate
import io.github.danielhp95.caracole.core.ug.Coverage
import io.github.danielhp95.caracole.core.ug.Rank
import io.github.danielhp95.caracole.core.ug.SheetVersion
import io.github.danielhp95.caracole.core.ug.SheetVersions
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.nio.file.Files

/**
 * Ranking, coverage and sheet versions (tests/test_conformance_rank.py), each record answered as Python answered it,
 * every float as Python's repr:
 * - [rank]: vectors/sites/ug_rank.jsonl, rank.py's and versions.py's `complete` and `replaces_sheet`, a ranking's
 *   answer each candidate's index and score in its order; its first record RankPolicy's defaults, which [policy]
 *   builds every record's policy on (the fields a record names, the rest RankPolicy()'s, so Kotlin's defaults are
 *   checked once, there);
 * - [coverage]: vectors/sites/ug_coverage.jsonl over ug_coverage_texts.jsonl's texts (a fixture file's bytes as
 *   UTF-8, or a text read out of one), a coverage's `scores`, where the record has them, each lyric line's match too;
 * - [sheetVersions]: vectors/sites/ug_sheet_versions.jsonl over its fixture library
 *   (ug_sheet_versions_fixture_library.jsonl), loaded once for the readers and afresh for each writer, whose kv
 *   records after it must be Python's text; a record's `dumps` (as_data's, same_pages') the answer's json.dumps
 *   text, its members in Python's order, which [PyJson.dumps] of Kotlin's must be byte for byte.
 */
object RankReplay : AreaReplay {
    override val area = "rank"

    const val RANK = "sites/ug_rank.jsonl"
    const val COVERAGE = "sites/ug_coverage.jsonl"
    const val TEXTS = "sites/ug_coverage_texts.jsonl"
    const val SHEET_VERSIONS = "sites/ug_sheet_versions.jsonl"
    const val FIXTURE = "sites/ug_sheet_versions_fixture_library.jsonl"

    override fun replay(misses: Misses) {
        rank(misses)
        coverage(misses)
        sheetVersions(misses)
    }

    // --- rank.py ------------------------------------------------------------------------------------------------

    fun rank(misses: Misses) {
        for (record in Corpus.records(RANK)) {
            answer(misses, record) {
                val kw = record.kw
                val a = record.args
                when (val fn = record.fn.removePrefix("caracole.")) {
                    "config.RankPolicy" -> defaults(record.out!!.jsonObject)
                    "rank.bayes" -> PyJson.float(Rank.bayes(double(a[0])!!, a[1].jsonPrimitive.int, double(a[2])!!,
                                                            double(a[3])!!))
                    "rank.prior_mean" -> PyJson.float(Rank.priorMean(candidates(kw)))
                    "rank.is_complete" -> JsonPrimitive(Rank.isComplete(candidate(kw.getValue("cand").jsonObject),
                                                                        policy(kw)))
                    "versions.complete" -> JsonPrimitive(Rank.complete(double(a[0]), double(a[1])!!))
                    "versions.replaces_sheet" -> JsonPrimitive(Rank.replacesSheet(double(a[0]), double(a[1]),
                                                                                  double(a[2])!!))
                    "rank.rank_by_rating", "rank.rank_sheets", "rank.rank_guitar" -> {
                        val cands = candidates(kw)
                        val variant = text(kw["variant"])
                        val ranked = when (fn) {
                            "rank.rank_by_rating" -> Rank.rankByRating(cands, policy(kw), variant)
                            "rank.rank_sheets" -> Rank.rankSheets(cands, policy(kw), variant)
                            else -> Rank.rankGuitar(cands, policy(kw), variant)
                        }
                        JsonArray(ranked.map { c ->
                            JsonArray(listOf(JsonPrimitive(cands.indexOfFirst { it === c }), PyJson.float(c.score)))
                        })
                    }
                    else -> throw AssertionError("no replay of ${record.fn}")
                }
            }
        }
    }

    // --- coverage.py --------------------------------------------------------------------------------------------

    fun coverage(misses: Misses) {
        val texts = Corpus.lines(TEXTS).filter { it["header"] != JsonPrimitive(true) }.associate { t ->
            val name = t.getValue("name").jsonPrimitive.content
            name to (t["fixture"]?.let { Corpus.fixture(it.jsonPrimitive.content).toString(Charsets.UTF_8) }
                ?: t.getValue("text").jsonPrimitive.content)
        }
        fun text(e: JsonElement): String =
            if (e is JsonObject) texts[e.getValue("name").jsonPrimitive.content] ?: error("no text $e")
            else e.jsonPrimitive.content
        for (record in Corpus.records(COVERAGE)) {
            val arg = record.args.firstOrNull()?.let(::text)
            when (record.fn.removePrefix("caracole.coverage.")) {
                "coverage" -> {
                    val sheet = text(record.kw.getValue("sheet"))
                    val lines = Coverage.lyricLines(text(record.kw.getValue("lyrics")))
                    val lineMatch = double(record.kw.getValue("line_match"))!!
                    answer(misses, record) { Coverage.coverage(sheet, lines, lineMatch)?.let(PyJson::float) ?: JsonNull }
                    val scores = try {
                        val lyricText = Coverage.comparable(Coverage.sheetLyricText(sheet))
                        JsonArray(if (lyricText.isEmpty()) emptyList()
                                  else lines.map { PyJson.float(Coverage.match(Coverage.comparable(it), lyricText)) })
                    } catch (e: Exception) {
                        JsonPrimitive("threw $e")
                    }
                    val want = record.extra["scores"] ?: continue
                    misses.check(dumps(scores) == dumps(want)) { "${case(record)}: scored ${dumps(scores)}, Python ${dumps(want)}" }
                }
                else -> answer(misses, record) {
                    when (val fn = record.fn.removePrefix("caracole.coverage.")) {
                        "normalize_line" -> JsonPrimitive(Coverage.normalizeLine(arg!!))
                        "lyric_lines" -> JsonArray(Coverage.lyricLines(arg!!).map(::JsonPrimitive))
                        "sheet_lyric_text" -> JsonPrimitive(Coverage.sheetLyricText(arg!!))
                        "_is_plain_chord_line" -> JsonPrimitive(Coverage.isPlainChordLine(arg!!))
                        "_comparable" -> JsonPrimitive(Coverage.comparable(arg!!))
                        "_match" -> PyJson.float(Coverage.match(arg!!, text(record.args[1])))
                        else -> throw AssertionError("no replay of caracole.coverage.$fn")
                    }
                }
            }
        }
    }

    // --- sheet_versions.py --------------------------------------------------------------------------------------

    fun sheetVersions(misses: Misses) {
        val records = Corpus.records(SHEET_VERSIONS)
        val work = Files.createTempDirectory("rank").toFile()
        try {
            TestDb.fresh(File(work, "readers").apply { mkdirs() }).use { database ->
                database.writeBlocking { db ->
                    Fixtures.load(db, FIXTURE)
                    for (record in records.filter { "after" !in it.extra }) {
                        answer(misses, record) { sheetVersionsCall(db, record) }
                        inPythonsOrder(misses, record) { sheetVersionsCall(db, record) }
                    }
                }
            }
            records.filter { "after" in it.extra }.forEachIndexed { i, record ->
                TestDb.fresh(File(work, "writer-$i").apply { mkdirs() }).use { database ->
                    database.writeBlocking { db ->
                        Fixtures.load(db, FIXTURE)
                        answer(misses, record) { sheetVersionsCall(db, record) }
                        for ((key, value) in record.extra.getValue("after").jsonObject.getValue("kv").jsonObject) {
                            val have = db.kvGet(key)
                            val want = text(value)
                            misses.check(have == want) { "${case(record)}: left $key = $have, Python $want" }
                        }
                    }
                }
            }
        } finally {
            work.deleteRecursively()
        }
    }

    private fun sheetVersionsCall(db: Db, record: Record): JsonElement {
        val kw = record.kw
        fun song(): Long = kw.getValue("song_id").jsonPrimitive.long
        fun listed(): List<SheetVersion> = SheetVersions.inLibrary(db, song(), policy(kw))
        fun strings(e: JsonElement?): List<String> = (e as? JsonArray)?.map { it.jsonPrimitive.content }.orEmpty()
        fun longs(e: JsonElement?): List<Long> = (e as? JsonArray)?.map { it.jsonPrimitive.long }.orEmpty()
        fun tab(): JsonPrimitive = kw.getValue("tab_id").jsonPrimitive
        return when (val fn = record.fn.removePrefix("caracole.sheet_versions.")) {
            "version_names" -> SheetVersions.versionNames(record.args[0].jsonPrimitive.content).let {
                JsonArray(listOf(it.first, it.second, it.third).map(::JsonPrimitive))
            }
            "tab_of" -> SheetVersions.tabOf(record.args[0].jsonPrimitive.content).json()
            "group_of" -> JsonPrimitive(SheetVersions.groupOf(kw.getValue("rows").jsonArray.mapIndexed { i, r ->
                val o = r.jsonObject
                VersionRow(id = i + 1L, provider = "ug", tabId = o.getValue("tab_id").jsonPrimitive.content, songId = 1,
                           slot = "sheet", kind = o.getValue("kind").jsonPrimitive.content, rating = 0.0, votes = 0,
                           version = 1, label = null, coverage = null, url = "", raw = JsonObject(emptyMap()),
                           fetchedAt = "", pickRank = null, gone = o.getValue("gone").jsonPrimitive.content == "true")
            }, text(kw["chosen_tab"])))
            "library_state" -> SheetVersions.libraryState(db, song()).let { (chosen, kept) ->
                JsonArray(listOf(chosen.json(), JsonArray(kept.map(::JsonPrimitive))))
            }
            "same_pages" -> JsonObject(SheetVersions.samePages(db, song()).mapValues { JsonPrimitive(it.value) })
            "sheet_kind" -> JsonPrimitive(SheetVersions.sheetKind(db, song()))
            "kept_by_you" -> JsonArray(SheetVersions.keptByYou(db, song()).map(::JsonPrimitive))
            "unkeepable" -> JsonArray(SheetVersions.unkeepable(db, song()).map(::JsonPrimitive))
            "note_kept_by_you" -> JsonNull.also {
                if (tab().isString) SheetVersions.noteKeptByYou(db, song(), tab().content)
                else SheetVersions.noteKeptByYou(db, song(), tab().long)
            }
            "note_unkeepable" -> JsonNull.also {
                if (tab().isString) SheetVersions.noteUnkeepable(db, song(), tab().content)
                else SheetVersions.noteUnkeepable(db, song(), tab().long)
            }
            "in_library" -> versions(listed())
            "as_data" -> SheetVersions.asData(listed(), kw.getValue("total").jsonPrimitive.int)
            "may_keep" -> versions(SheetVersions.mayKeep(db, song(), listed(), longs(kw["block"])))
            "in_library_of" -> JsonArray(SheetVersions.inLibraryOf(db, longs(kw["song_ids"]), policy(kw)).map {
                JsonArray(listOf(JsonPrimitive(it.key), versions(it.value)))
            })
            "song_sheet_versions" -> versions(SheetVersions.songSheetVersions(
                db, song(), policy(kw), text(kw["chosen_tab"]), strings(kw["kept_tabs"]),
                (kw["same_as"] as? JsonObject)?.mapValues { it.value.jsonPrimitive.content },
            ))
            "sheet_pins" -> JsonArray(SheetVersions.sheetPins(db, song(), longs(kw["pins"])).map(::JsonPrimitive))
            else -> throw AssertionError("no replay of caracole.sheet_versions.$fn")
        }
    }

    /** A SheetVersion as Python's corpus writes the dataclass: an object of its fields. */
    fun versionJson(v: SheetVersion): JsonObject = JsonObject(linkedMapOf(
        "version_id" to JsonPrimitive(v.versionId), "tab_id" to JsonPrimitive(v.tabId),
        "number" to (v.number?.let(::JsonPrimitive) ?: JsonNull), "rating" to (v.rating?.let(PyJson::float) ?: JsonNull),
        "votes" to (v.votes?.let(::JsonPrimitive) ?: JsonNull), "label" to v.label.json(), "note" to v.note.json(),
        "coverage" to (v.coverage?.let(PyJson::float) ?: JsonNull),
        "complete" to (v.complete?.let(::JsonPrimitive) ?: JsonNull), "rank" to JsonPrimitive(v.rank),
        "kept" to JsonPrimitive(v.kept), "chosen" to JsonPrimitive(v.chosen), "gone" to JsonPrimitive(v.gone),
        "page" to v.page.json(), "url" to JsonPrimitive(v.url),
    ))

    private fun versions(listed: List<SheetVersion>): JsonArray = JsonArray(listed.map(::versionJson))

    // --- shared -------------------------------------------------------------------------------------------------

    /** A record's `dumps`, json.dumps of Python's answer, against [PyJson.dumps] of [got]'s: the members in
     * Python's order, which [answer]'s sorted comparison can't see. */
    private fun inPythonsOrder(misses: Misses, record: Record, got: () -> JsonElement) {
        val want = record.extra["dumps"]?.jsonPrimitive?.content ?: return
        val have = try {
            PyJson.dumps(got())
        } catch (e: Exception) {
            "threw $e"
        }
        misses.check(have == want) { "${case(record)}: dumps ${have.take(600)}, Python ${want.take(600)}" }
    }

    /** RankPolicy() against the defaults Python's record gives, each field compared as the number it is. */
    private fun defaults(python: JsonObject): JsonElement {
        val kotlin = RankPolicy()
        val fields = mapOf<String, Double>(
            "coverage_threshold" to kotlin.coverageThreshold, "line_match" to kotlin.lineMatch,
            "prior_votes" to kotlin.priorVotes, "scored_sheets" to kotlin.scoredSheets.toDouble(),
            "label_penalty" to kotlin.labelPenalty, "variant_bonus" to kotlin.variantBonus,
        )
        if (fields.keys != python.keys) throw AssertionError("RankPolicy's fields ${python.keys}, Kotlin's ${fields.keys}")
        // Python's own numbers where Kotlin's are equal, so the comparison names the field that differs
        return JsonObject(python.mapValues { (name, value) ->
            if (double(value) == fields.getValue(name)) value else PyJson.float(fields.getValue(name))
        })
    }

    /** [got]'s answer against the record's, compared as Python's JSON text with sorted keys; a throw is a miss. */
    private fun answer(misses: Misses, record: Record, got: () -> JsonElement) {
        val answer = try {
            got()
        } catch (e: Exception) {
            misses.check(false) { "${case(record)}: threw $e, Python answered ${record.out?.let(::dumps)}" }
            return
        }
        val want = record.out ?: JsonNull
        misses.check(dumps(answer) == dumps(want)) {
            "${case(record)}: answered ${dumps(answer).take(600)}, Python ${dumps(want).take(600)}"
        }
    }

    private fun case(record: Record): String =
        "${record.fn.substringAfterLast('.')} (${text(record.extra["case"])}; ${record.args.toString().take(80)}" +
            "${record.kw.toString().take(160)})"

    private fun dumps(e: JsonElement): String = PyJson.dumps(e, sortKeys = true)

    /** A record's policy, `RankPolicy(**policy)`: the fields it names, the rest RankPolicy()'s defaults. */
    fun policy(kw: JsonObject): RankPolicy = kw.getValue("policy").jsonObject.let { p ->
        val d = RankPolicy()
        val known = setOf("coverage_threshold", "line_match", "prior_votes", "scored_sheets", "label_penalty",
                          "variant_bonus")
        (p.keys - known).firstOrNull()?.let { throw AssertionError("RankPolicy has no field $it") }
        RankPolicy(coverageThreshold = double(p["coverage_threshold"]) ?: d.coverageThreshold,
                   lineMatch = double(p["line_match"]) ?: d.lineMatch,
                   priorVotes = double(p["prior_votes"]) ?: d.priorVotes,
                   scoredSheets = p["scored_sheets"]?.jsonPrimitive?.int ?: d.scoredSheets,
                   labelPenalty = double(p["label_penalty"]) ?: d.labelPenalty,
                   variantBonus = double(p["variant_bonus"]) ?: d.variantBonus)
    }

    private fun candidates(kw: JsonObject): List<Candidate> = kw.getValue("cands").jsonArray.map { candidate(it.jsonObject) }

    /** A record's candidate: the fields ranking reads, its provider `ug` and its kind `chords`, as the generator's
     * `_candidate` makes it. */
    fun candidate(c: JsonObject): Candidate = Candidate(
        provider = "ug", tabId = c.getValue("tab_id").jsonPrimitive.content, kind = "chords",
        rating = double(c.getValue("rating"))!!,
        votes = c.getValue("votes").jsonPrimitive.int, version = c.getValue("version").jsonPrimitive.int,
        label = text(c["label"]), coverage = double(c["coverage"]),
    )

    /** A number of the record as the double Python held (an int's literal too); null for none. */
    private fun double(e: JsonElement?): Double? = (e as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content?.toDouble()

    private fun text(e: JsonElement?): String? = (e as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content

    private fun String?.json(): JsonElement = this?.let(::JsonPrimitive) ?: JsonNull
}
