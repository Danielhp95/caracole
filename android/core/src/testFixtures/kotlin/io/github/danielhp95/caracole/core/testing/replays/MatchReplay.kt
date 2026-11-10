package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.config.MatchPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LaCuerdaPick
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.lookup.sites.MatchStage
import io.github.danielhp95.caracole.core.match.IndexView
import io.github.danielhp95.caracole.core.match.MatchResult
import io.github.danielhp95.caracole.core.match.Matcher
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.Record
import io.github.danielhp95.caracole.core.testing.TestDb
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.nio.file.Files

/**
 * The matcher (tests/test_conformance_match.py's vectors/match/), every record answered as Python answered it, and
 * the distances it and the inbox score names by (vectors/fuzz/osa*.jsonl and token_set.jsonl, lane matcher's):
 *
 * - [ladder]: match.match_song over each record's database (its fixture, inline), its overrides and policy, on a
 *   fresh IndexView: the MatchResult's every field;
 * - [views]: one IndexView's calls in order, each answer;
 * - [matchAll]: match.match_all over test_match.py's databases and the seeded library (match/fixtures/seeded.jsonl),
 *   after `before`'s changes (kv dropped, the index cleared), with the songs given or all of them: each change, and
 *   every songs and versions row as Python left it, byte for byte as a fixture dumps it (stamps `now`);
 * - [stage]: the lookup's match stage's words (MatchStage.matched), after Python's backfill (nothing to the matcher);
 * - [fuzzDistances]: OSA's distance, its extract, and token_set_ratio, each to the integer or the double.
 *
 * Each record runs in a savepoint of one database that is then undone, so the next starts as freshly migrated.
 */
object MatchReplay : AreaReplay {
    override val area = "match"

    override fun replay(misses: Misses) {
        fuzzDistances(misses)
        withDatabase { db ->
            ladder(misses, db)
            views(misses, db)
            matchAll(misses, db)
            stage(misses, db)
        }
    }

    // --- the matcher ------------------------------------------------------------------------------------------

    fun ladder(misses: Misses, db: Db) {
        val records = Corpus.records("match/ladder.jsonl")
        check(records.size > 80) { "match/ladder.jsonl holds ${records.size} records" }
        for (r in records) {
            undone(db) {
                load(db, r)
                val song = Songs.byId(db, r.extra.getValue("song").jsonPrimitive.long)!!
                val got = Matcher.matchSong(song, IndexView(db), overrides(r), policy(r))
                same(misses, r, "match_song", resultJson(got), r.out!!)
            }
        }
    }

    fun views(misses: Misses, db: Db) {
        for (r in Corpus.records("match/view.jsonl")) {
            undone(db) {
                load(db, r)
                val view = IndexView(db)
                for (call in r.extra.getValue("calls").jsonArray.map { it.jsonObject }) {
                    val method = call.getValue("method").jsonPrimitive.content
                    val args = call.getValue("args").jsonArray
                    val got = try {
                        viewCall(view, method, args)
                    } catch (e: Exception) {
                        JsonPrimitive("threw $e")
                    }
                    same(misses, r, "$method$args", got, call.getValue("out"))
                }
            }
        }
    }

    private fun viewCall(view: IndexView, method: String, args: JsonArray): JsonElement {
        fun arg(i: Int) = args[i].jsonPrimitive.content
        fun strings(xs: List<String>) = JsonArray(xs.map(::JsonPrimitive))
        return when (method) {
            "titles_for_artist" -> JsonArray(view.titlesForArtist(arg(0)).map {
                JsonObject(mapOf("base_key" to JsonPrimitive(it.baseKey), "song_keys" to strings(it.songKeys),
                                 "tabs" to JsonPrimitive(it.tabs)))
            })
            "artist_keys" -> strings(view.artistKeys())
            "compact_artist_keys" -> strings(view.compactArtistKeys())
            "title_keys" -> strings(view.titleKeys())
            "compact_title_keys" -> strings(view.compactTitleKeys())
            "titles_reading" -> strings(view.titlesReading(arg(0)))
            "artists_for_title" -> JsonObject(view.artistsForTitle(arg(0)).mapValues { JsonPrimitive(it.value) })
            "compact_artists" -> strings(view.compactArtists(arg(0)))
            "has_artist" -> JsonPrimitive(view.hasArtist(arg(0)))
            "artist_tabs" -> JsonPrimitive(view.artistTabs(arg(0)))
            "catch_all_songs" -> catchAll(view.catchAllSongs())
            "catch_all_holding" -> catchAll(view.catchAllHolding(args[0].jsonArray.map { it.jsonPrimitive.content }))
            "tab_keys" -> view.tabKeys(args[0].jsonPrimitive.long)?.let { strings(listOf(it.first, it.second)) }
                ?: JsonNull
            else -> throw AssertionError("no replay of IndexView.$method")
        }
    }

    private fun catchAll(songs: List<io.github.danielhp95.caracole.core.match.CatchAllSong>) = JsonArray(songs.map {
        JsonArray(listOf(JsonPrimitive(it.artistKey), JsonPrimitive(it.baseKey), JsonPrimitive(it.tabs)))
    })

    fun matchAll(misses: Misses, db: Db) {
        val records = Corpus.records("match/match_all.jsonl") + Corpus.records("match/seeded.jsonl")
        check(records.size > 50) { "match/ holds ${records.size} match_all records" }
        for (r in records) {
            undone(db) {
                load(db, r)
                val before = r.extra.getValue("before").jsonObject
                for (key in before["drop_kv"]?.jsonArray.orEmpty()) db.kvDelete(key.jsonPrimitive.content)
                if (before["clear_index"]?.jsonPrimitive?.boolean == true) db.execute("DELETE FROM ug_index")
                val kw = r.kw
                val all = Songs.list(db)
                val songs = when {
                    kw["songs"] !is JsonNull -> kw.getValue("songs").jsonArray.map { id ->
                        all.single { it.id == id.jsonPrimitive.long }
                    }
                    kw["song_ids"] !is JsonNull -> kw.getValue("song_ids").jsonArray.map { it.jsonPrimitive.long }.toSet()
                        .let { ids -> all.filter { it.id in ids } }
                    else -> all
                }
                val rowsBefore = TABLES.associateWith { rows(db, it) }
                val changes = Matcher.matchAll(db, overrides(r), policy(r), songs,
                                               dryRun = kw.getValue("dry_run").jsonPrimitive.boolean,
                                               now = r.extra.getValue("now").jsonPrimitive.content)
                val out = r.out!!.jsonObject
                val gotChanges = JsonArray(changes.map {
                    JsonObject(mapOf("song" to JsonPrimitive(it.song.id), "old" to (it.old?.let(::JsonPrimitive) ?: JsonNull),
                                     "new" to resultJson(it.new)))
                })
                same(misses, r, "changes", gotChanges, out.getValue("changes"))
                for (table in TABLES) {
                    val wrote = out.getValue("rows").jsonObject.getValue(table).jsonArray.associate {
                        it.jsonObject.getValue("id").jsonPrimitive.long to line(it.jsonObject)
                    }
                    val want = rowsBefore.getValue(table) + wrote
                    val have = rows(db, table)
                    for (id in (want.keys + have.keys).sorted()) {
                        misses.check(want[id] == have[id]) {
                            "${case(r)}: $table row $id is ${have[id]?.take(700)}, Python's ${want[id]?.take(700)}"
                        }
                    }
                }
            }
        }
    }

    fun stage(misses: Misses, db: Db) {
        for (r in Corpus.records("match/stage.jsonl")) {
            undone(db) {
                load(db, r)
                val song = Songs.byId(db, r.extra.getValue("song").jsonPrimitive.long)!!
                val said = MatchStage.matched(db, song, overrides(r), policy(r), r.extra.getValue("now").jsonPrimitive.content)
                misses.check(said == r.out!!.jsonPrimitive.content) { "${case(r)}: said '$said', Python '${r.out}'" }
            }
        }
    }

    // --- the distances ----------------------------------------------------------------------------------------

    fun fuzzDistances(misses: Misses) {
        val osa = Corpus.records("fuzz/osa.jsonl")
        check(osa.size > 1000) { "fuzz/osa.jsonl holds ${osa.size} records" }
        for (r in osa) {
            val cutoff = r.kw["score_cutoff"]?.jsonPrimitive?.int
            val got = Fuzz.osaDistance(text(r.args[0]), text(r.args[1]), cutoff)
            misses.check(got == r.out!!.jsonPrimitive.int) { "OSA ${r.args} ${r.kw}: rapidfuzz ${r.out}, Fuzz $got" }
        }
        for (r in Corpus.records("fuzz/osa_extract.jsonl")) {
            val want = r.out!!.jsonArray.map { row ->
                val (choice, distance, index) = row.jsonArray
                Fuzz.ExtractedDistance(choice.jsonPrimitive.content, distance.jsonPrimitive.int, index.jsonPrimitive.int)
            }
            val got = Fuzz.extractDistance(text(r.args[0]), r.args[1].jsonArray.map(::text),
                                           r.kw.getValue("score_cutoff").jsonPrimitive.int)
            misses.check(got == want) { "OSA extract ${r.args} ${r.kw}: rapidfuzz $want, Fuzz $got" }
        }
        val sets = Corpus.records("fuzz/token_set.jsonl")
        check(sets.size > 2000) { "fuzz/token_set.jsonl holds ${sets.size} records" }
        for (r in sets) {
            val got = Fuzz.tokenSetRatio(text(r.args[0]), text(r.args[1]))
            misses.check(got == r.out!!.jsonPrimitive.double) {
                "token_set ${r.args.map { show(text(it)) }}: rapidfuzz ${r.out}, Fuzz $got"
            }
        }
    }

    // --- a record's parts -------------------------------------------------------------------------------------

    private val TABLES = listOf("songs", "versions")

    /** A fresh database, each record's writes undone after it. */
    fun withDatabase(block: (Db) -> Unit) {
        val dir: File = Files.createTempDirectory("caracole-match").toFile()
        try {
            TestDb.fresh(dir).use { database -> database.writeBlocking(block) }
        } finally {
            dir.deleteRecursively()
        }
    }

    private class Undo : RuntimeException()

    private fun undone(db: Db, block: () -> Unit) {
        try {
            db.savepoint("match_record") {
                block()
                throw Undo()
            }
        } catch (_: Undo) {
        }
    }

    private fun load(db: Db, r: Record) {
        when (val fixture = r.extra.getValue("fixture")) {
            is JsonPrimitive -> Fixtures.load(db, fixture.content)
            else -> Fixtures.loadRecords(db, fixture.jsonArray.map { it.jsonObject })
        }
    }

    fun overrides(r: Record): Overrides {
        val o = r.extra.getValue("overrides").jsonObject
        fun strings(e: JsonElement) = e.jsonArray.map { it.jsonPrimitive.content }
        return Overrides(
            alias = o["alias"]?.jsonObject?.mapValues { strings(it.value) }.orEmpty(),
            match = o["match"]?.jsonObject?.mapValues { strings(it.value).let { (a, s) -> a to s } }.orEmpty(),
            pin = o["pin"]?.jsonObject?.mapValues { e -> e.value.jsonArray.map { it.jsonPrimitive.long } }.orEmpty(),
            ignore = o["ignore"]?.let(::strings)?.toSet().orEmpty(),
            reject = o["reject"]?.jsonObject?.mapValues { e ->
                e.value.jsonArray.map { strings(it).let { (a, s) -> a to s } }.toSet()
            }.orEmpty(),
            lacuerda = o["lacuerda"]?.jsonObject?.mapValues { e ->
                val p = e.value.jsonObject
                LaCuerdaPick(p.getValue("artist").jsonPrimitive.content, p.getValue("song").jsonPrimitive.content,
                             p["version"]?.takeUnless { it is JsonNull }?.jsonPrimitive?.int)
            }.orEmpty(),
        )
    }

    fun policy(r: Record): MatchPolicy {
        val p = r.extra.getValue("policy").jsonObject
        return MatchPolicy(accept = p.getValue("accept").jsonPrimitive.double, margin = p.getValue("margin").jsonPrimitive.double,
                           review = p.getValue("review").jsonPrimitive.double,
                           artistGate = p.getValue("artist_gate").jsonPrimitive.double)
    }

    /** A MatchResult as Python's corpus writes the dataclass. */
    fun resultJson(m: MatchResult): JsonObject {
        fun str(s: String?) = s?.let(::JsonPrimitive) ?: JsonNull
        fun num(d: Double?) = d?.let(PyJson::float) ?: JsonNull
        return JsonObject(mapOf(
            "decision" to JsonPrimitive(m.decision), "step" to str(m.step), "score" to num(m.score),
            "artist_key" to str(m.artistKey), "song_key" to str(m.songKey),
            "candidates" to JsonArray(m.candidates.map {
                JsonObject(mapOf("artist_key" to JsonPrimitive(it.artistKey), "song_key" to JsonPrimitive(it.songKey),
                                 "score" to num(it.score), "step" to str(it.step)))
            }),
            "pinned" to JsonArray(m.pinned.map(::JsonPrimitive)),
        ))
    }

    private fun line(o: JsonObject): String = PyJson.dumps(o, sortKeys = true, compact = true)

    /** A table's rows by id, each as a fixture dumps it (helpers.corpus.dump_fixture's values, Dumps' types). */
    private fun rows(db: Db, table: String): Map<Long, String> {
        val columns = db.query("PRAGMA main.table_info(\"$table\")") { it.text(1)!! }
        val select = columns.joinToString(", ") { "typeof(\"$it\"), \"$it\"" }
        val out = LinkedHashMap<Long, String>()
        db.query("SELECT $select FROM \"$table\" ORDER BY rowid") { row ->
            val values = LinkedHashMap<String, JsonElement>()
            columns.forEachIndexed { i, column ->
                values[column] = when (val type = row.text(2 * i)) {
                    "null" -> JsonNull
                    "integer" -> JsonPrimitive(row.long(2 * i + 1)!!)
                    "real" -> PyJson.float(row.double(2 * i + 1)!!)
                    "text" -> JsonPrimitive(row.text(2 * i + 1)!!)
                    else -> error("$table holds a $type")
                }
            }
            out[(values.getValue("id") as JsonPrimitive).long] = line(JsonObject(values))
        }
        return out
    }

    private fun same(misses: Misses, r: Record, what: String, got: JsonElement, want: JsonElement) {
        val have = PyJson.dumps(got, sortKeys = true, compact = true)
        val python = PyJson.dumps(want, sortKeys = true, compact = true)
        misses.check(have == python) { "${case(r)} $what: ${have.take(900)}, Python's ${python.take(900)}" }
    }

    private fun case(r: Record): String = r.extra["case"]?.jsonPrimitive?.content ?: r.fn
}
