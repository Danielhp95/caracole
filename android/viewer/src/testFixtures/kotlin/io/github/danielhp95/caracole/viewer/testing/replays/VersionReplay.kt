package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.core.testing.replays.LibraryWritesReplay
import io.github.danielhp95.caracole.viewer.progressions.Progressions
import io.github.danielhp95.caracole.viewer.sheet.Sheets
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.version.KeyVersion
import io.github.danielhp95.caracole.viewer.version.Setting
import io.github.danielhp95.caracole.viewer.version.Version
import io.github.danielhp95.caracole.viewer.version.Versions
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import java.nio.file.Files

/**
 * viewer/version.py's page side and progressions.py (vectors/viewer/version.jsonl and progressions.jsonl), every
 * record answered by :viewer's Versions and Progressions as Python answered it: VersionsTest's and ProgressionsTest's
 * record loops, run on the device by CorpusOnDeviceTest. tests/test_conformance_viewer_version.py's docstring says each
 * record's shape: a key `[tonic, mode]`, a version its address (`Versions.query`) or its row, a setting `[key, mode,
 * capo, instrument]`, a sheet `[cho, key, capo]` (its cho a text or a fixture's reference), raised `{"error": its
 * words}`, a batch's answers by the first 16 hex digits of the SHA-256 of their compact JSON.
 */
object VersionReplay : AreaReplay {
    override val area = "version"

    private const val HELPER = "test_conformance_viewer_version."
    private const val VERSION = "viewer/version.jsonl"
    private const val PROGRESSIONS = "viewer/progressions.jsonl"

    override fun replay(misses: Misses) {
        versions(misses)
        progressions(misses)
    }

    // --- version.jsonl -------------------------------------------------------------------------------------------

    fun versions(misses: Misses) {
        val counts = HashMap<String, Int>()
        for (record in Corpus.records(VERSION)) {
            val fn = record.fn.removePrefix(HELPER)
            counts.merge(fn, 1, Int::plus)
            val args = record.args
            val out = record.out!!
            when (fn) {
                "from_query_of" -> each(misses, fn, args[0], out) { q ->
                    val v = Versions.fromQuery(q.jsonPrimitive.content)
                    if (q.jsonPrimitive.content in TEST_QUERIES) JsonArray(listOf(versionRow(v), JsonPrimitive(Versions.query(v))))
                    else JsonPrimitive(Versions.query(v))
                }
                "instruments_of" -> {
                    val names = args[0].jsonArray.map { text(it) }
                    val rows = JsonArray(names.map { name ->
                        val on = Versions.playedOn(Version(inst = name))
                        JsonArray(listOf(json(Versions.instrumentOf(name)?.id), json(Versions.instOf(name)), json(on.id),
                                         json(Versions.instrumentWords(on)),
                                         json(Versions.query(Versions.forInstrument(Version(t = 1, capo = 3, inst = name), on)))))
                    })
                    val got = JsonObject(mapOf("ids" to strings(Versions.instrumentIds()), "rows" to rows))
                    misses.check(got == out) { "instruments: $got, Python's $out" }
                }
                "labels_of" -> each(misses, fn, args[0], out) { item ->
                    val (q, k, c) = item.jsonArray
                    labelAnswer(q.jsonPrimitive.content, key(k), int(c))
                }
                "labels_product" -> product(misses, fn, args[0], out) { q ->
                    val keys = args[1].jsonArray.map(::key)
                    val capos = args[2].jsonArray.map(::int)
                    JsonArray(keys.flatMap { k -> capos.map { c -> labelAnswer(q.jsonPrimitive.content, k, c) } })
                }
                "setting_problems_of" -> each(misses, fn, args[0], out) { item ->
                    val (k, m, c, i) = item.jsonArray
                    json(Versions.settingProblem(k, m, c, i))
                }
                "in_setting_of" -> each(misses, fn, args[0], out) { item ->
                    val (own, s, k, c) = item.jsonArray
                    JsonPrimitive(inSetting(own.jsonPrimitive.content, s, k, c))
                }
                "in_setting_product" -> product(misses, fn, args[0], out) { own ->
                    JsonArray(args[1].jsonArray.flatMap { s ->
                        args[2].jsonArray.flatMap { k ->
                            args[3].jsonArray.map { c -> JsonPrimitive(inSetting(own.jsonPrimitive.content, s, k, c)) }
                        }
                    })
                }
                "key_versions_of" -> each(misses, fn, args[0], out) { t -> keyVersionAnswer(t.jsonPrimitive.content) }
                "kept_of" -> kept(misses, args[0].jsonArray.map(::sheet), args[1].jsonObject, out.jsonObject)
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertTrue("records of every kind: $counts", counts.keys == setOf(
            "from_query_of", "instruments_of", "labels_of", "labels_product", "setting_problems_of", "in_setting_of",
            "in_setting_product", "key_versions_of", "kept_of"))
    }

    /** tests/test_conformance_viewer_version.py's TEST_QUERIES, whose answers hold the version's row too: the
     * record's queries before its EDGE_QUERIES ("?" and the round trip), as many as its rows. */
    private val TEST_QUERIES: Set<String> by lazy {
        val record = Corpus.records(VERSION).first { it.fn == HELPER + "from_query_of" }
        record.args[0].jsonArray.zip(record.out!!.jsonArray).filter { it.second is JsonArray }
            .map { it.first.jsonPrimitive.content }.toSet()
    }

    private fun labelAnswer(q: String, k: Key?, c: Int?): JsonArray {
        val v = Versions.fromQuery(q)
        val (played, capo) = Versions.playedKey(v, k, c)
        return JsonArray(listOf(TheoryReplay.key(played), JsonPrimitive(capo), JsonPrimitive(Versions.label(v, k, c)),
                                JsonPrimitive(Versions.playedLabel(v, k, c))))
    }

    private fun inSetting(own: String, s: JsonElement, k: JsonElement, c: JsonElement): String =
        Versions.query(Versions.inSetting(Versions.fromQuery(own), setting(s), key(k), int(c)))

    private fun setting(e: JsonElement): Setting? {
        if (e is JsonNull) return null
        val (k, m, c, i) = e.jsonArray
        return Setting(text(k), text(m), int(c), text(i))
    }

    private fun keyVersionAnswer(text: String): JsonElement {
        val kept = try {
            Versions.keyVersion(text)
        } catch (e: IllegalArgumentException) {
            return raised(e)
        } ?: return JsonNull
        return JsonObject(mapOf("kept" to keptRow(kept), "query" to JsonPrimitive(kept.query()),
                                "label" to JsonPrimitive(kept.label())))
    }

    /** A sheet of the record: its text, its key and its capo as its viewer reads them. */
    class Sheet(val cho: String, val key: Key?, val capo: Int?)

    private fun sheet(e: JsonElement): Sheet {
        val (cho, k, c) = e.jsonArray
        val text = if (cho is JsonObject) Corpus.fixture(cho.getValue("fixture").jsonPrimitive.content).toString(Charsets.UTF_8)
                   else cho.jsonPrimitive.content
        return Sheet(text, key(k), int(c))
    }

    private fun kept(misses: Misses, sheets: List<Sheet>, inputs: JsonObject, out: JsonObject) {
        // the key and capo each sheet's viewer reads, as the record gives them
        for ((i, s) in sheets.withIndex()) {
            misses.check(Sheets.parse(s.cho).capo == s.capo) { "kept_of: sheet $i's capo ${Sheets.parse(s.cho).capo}, Python's ${s.capo}" }
        }
        fun entry(q: String, s: Sheet): JsonElement = json(Versions.entry(Versions.fromQuery(q), s.cho, s.key, s.capo))
        fun inKey(e: String, s: Sheet): JsonElement =
            JsonPrimitive(Versions.query(Versions.inKey(Versions.keyVersion(e)!!, s.cho, s.key, s.capo)))

        val versions = strings(inputs.getValue("entry_versions"))
        val own = inputs.getValue("own").jsonArray.map(::strings)
        expectEach(misses, "entries_hand", inputs.getValue("entries_hand"), out.getValue("entries_hand")) { item ->
            val (q, i) = item.jsonArray
            entry(q.jsonPrimitive.content, sheets[i.jsonPrimitive.int])
        }
        val entries = out.getValue("entries").jsonArray
        for ((i, s) in sheets.withIndex()) {
            val got = JsonArray((versions + own[i]).map { safely { entry(it, s) } })
            misses.check(digest(got) == entries[i].jsonPrimitive.content) { "version_entry on sheet $i: $got" }
        }
        expectEach(misses, "in_key_hand", inputs.getValue("in_key_hand"), out.getValue("in_key_hand")) { item ->
            val (e, i) = item.jsonArray
            inKey(e.jsonPrimitive.content, sheets[i.jsonPrimitive.int])
        }
        val kept = strings(inputs.getValue("in_key"))
        val inKeys = out.getValue("in_key").jsonArray
        for ((i, s) in sheets.withIndex()) {
            val got = JsonArray(kept.map { safely { inKey(it, s) } })
            misses.check(digest(got) == inKeys[i].jsonPrimitive.content) { "in_key on sheet $i: ${got.toString().take(600)}" }
        }
        expectEach(misses, "own_versions", inputs.getValue("own_versions"), out.getValue("own_versions")) { item ->
            val (entry, transpose, i, songKey, source) = item.jsonArray
            val song = LibraryWritesReplay.stub("artist - title")
            val overrides = Overrides(
                version = text(entry)?.let { mapOf(song.key to it) } ?: emptyMap(),
                transpose = int(transpose)?.let { mapOf(song.key to it) } ?: emptyMap(),
            )
            try {
                JsonPrimitive(Versions.query(Versions.ownVersion(overrides, song, sheets[i.jsonPrimitive.int].cho,
                                                                  text(songKey), text(source))))
            } catch (e: IllegalArgumentException) {
                raised(e)
            }
        }
    }

    fun versionRow(v: Version): JsonArray = JsonArray(listOf(
        JsonPrimitive(v.t), json(v.mode), v.capo?.let(::JsonPrimitive) ?: JsonNull,
        JsonArray(v.at.map { (i, n) -> JsonArray(listOf(JsonPrimitive(i), JsonPrimitive(n))) }),
        JsonArray(v.alt.map { (mode, swaps) ->
            JsonArray(listOf(JsonPrimitive(mode), JsonArray(swaps.map { (i, s) ->
                JsonArray(listOf(JsonPrimitive(i), JsonPrimitive(s.root), JsonPrimitive(s.suffix), s.bass?.let(::JsonPrimitive) ?: JsonNull))
            })))
        }),
        json(v.inst),
    ))

    fun keptRow(k: KeyVersion): JsonArray = JsonArray(listOf(
        TheoryReplay.key(k.key), json(k.mode), k.capo?.let(::JsonPrimitive) ?: JsonNull,
        JsonArray(k.alt.map { (a, b) -> strings(listOf(a, b)) }),
        JsonArray(k.at.map { (name, frets) -> JsonArray(listOf(JsonPrimitive(name), JsonArray(frets.map { f -> f?.let(::JsonPrimitive) ?: JsonNull }))) }),
        json(k.inst),
    ))

    // --- progressions.jsonl --------------------------------------------------------------------------------------

    fun progressions(misses: Misses) = withDb { recording -> progressions(misses, recording) }

    private fun progressions(misses: Misses, recording: Db) {
        val counts = HashMap<String, Int>()
        for (record in Corpus.records(PROGRESSIONS)) {
            val fn = record.fn.removePrefix(HELPER)
            counts.merge(fn, 1, Int::plus)
            val args = record.args
            val out = record.out!!
            when (fn) {
                "sheet_progressions_of" -> {
                    val want = out.jsonObject
                    expectEach(misses, fn, args[0], want.getValue("whole")) { item -> progressionText(misses, recording, item) }
                    val more = args[1].jsonArray
                    val digests = want.getValue("digests").jsonArray
                    for ((i, item) in more.withIndex()) {
                        val got = safely { progressionText(misses, recording, item) }
                        misses.check(digest(got) == digests[i].jsonPrimitive.content) { "sheet_progressions($item): $got" }
                    }
                }
                "sheet_progressions_digests" -> product(misses, fn, args[0], out) { cho ->
                    JsonArray(args[1].jsonArray.map { v ->
                        val (k, source) = v.jsonArray
                        progressionText(misses, recording, JsonArray(listOf(cho, k, source)))
                    })
                }
                "library_of" -> {
                    val got = withDb { db ->
                        Fixtures.loadRecords(db, args[0].jsonArray.map { row ->
                            val (k, v) = row.jsonArray
                            JsonObject(mapOf("kv" to k, "value" to v))
                        })
                        JsonArray(Progressions.library(db).map { (id, entries) -> JsonArray(listOf(JsonPrimitive(id), entries)) })
                    }
                    misses.check(got == out) { "library_progressions: $got, Python's $out" }
                }
                "catalogue_of" -> {
                    val pairs = JsonArray(Progressions.catalogue().map { (k, v) -> strings(listOf(k, v)) })
                    val want = out.jsonObject
                    misses.check(pairs.size == want.getValue("count").jsonPrimitive.int && sha(pairs) == want.getValue("sha256").jsonPrimitive.content) {
                        "catalogue(): ${pairs.size} keys, ${pairs.toString().take(400)}"
                    }
                }
                "label_of" -> each(misses, fn, args[0], out) { k -> JsonPrimitive(Progressions.label(k.jsonPrimitive.content)) }
                "key_words_of" -> each(misses, fn, args[0], out) { k -> JsonPrimitive(Progressions.keyWords(key(k)!!)) }
                "read_progression_of" -> each(misses, fn, args[0], out) { t -> readAnswer(t.jsonPrimitive.content) }
                "read_progression_digests" -> product(misses, fn, args[0], out) { batch ->
                    JsonArray(batch.jsonArray.map { readAnswer(it.jsonPrimitive.content) })
                }
                "songs_with_of" -> {
                    val got = withDb { db ->
                        Fixtures.loadRecords(db, args[0].jsonArray.map { it.jsonObject })
                        JsonArray(args[1].jsonArray.map { t ->
                            val wanted = Progressions.read(t.jsonPrimitive.content)
                            JsonArray((if (wanted == null) emptyList() else Progressions.songsWith(db, wanted)).map { p ->
                                JsonArray(listOf(JsonPrimitive(p.song.key), strings(p.sections), JsonPrimitive(p.key)))
                            })
                        })
                    }
                    misses.check(got == out) { "songs_with: $got, Python's $out" }
                }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertTrue("records of every kind: $counts", counts.keys == setOf(
            "sheet_progressions_of", "sheet_progressions_digests", "library_of", "catalogue_of", "label_of",
            "key_words_of", "read_progression_of", "read_progression_digests", "songs_with_of"))
    }

    /** The kv text record writes for a sheet `[cho, key, key source]`, and that record writes it so, into
     * [recording] (one database for them all: a record written again only when it changed). */
    private fun progressionText(misses: Misses, recording: Db, item: JsonElement): JsonElement {
        val (cho, k, source) = item.jsonArray
        val text = if (cho is JsonObject) Corpus.fixture(cho.getValue("fixture").jsonPrimitive.content).toString(Charsets.UTF_8)
                   else cho.jsonPrimitive.content
        val found = Progressions.sheetProgressions(text, text(k), text(source))?.let { PyJson.dumps(it) }
        Progressions.record(recording, 7, text, text(k), text(source))
        val written = recording.kvGet("${Progressions.KV}7")
        misses.check(written == found) { "record($item) wrote $written, sheet_progressions said $found" }
        return json(found)
    }

    private fun readAnswer(text: String): JsonElement {
        val w = Progressions.read(text) ?: return JsonNull
        return JsonArray(listOf(JsonPrimitive(w.key), strings(w.keys.sortedWith(io.github.danielhp95.caracole.core.py.Py.CODE_POINT_ORDER)),
                                json(w.name), JsonPrimitive(w.label)))
    }

    // --- helpers -------------------------------------------------------------------------------------------------

    private fun <T> withDb(block: (Db) -> T): T {
        val dir = Files.createTempDirectory("caracole-version").toFile()
        try {
            return TestDb.fresh(dir).use { database -> database.writeBlocking(block) }
        } finally {
            dir.deleteRecursively()
        }
    }

    /** Each item of [items], its answer and Python's ([want], whole). */
    private fun each(misses: Misses, fn: String, items: JsonElement, want: JsonElement, got: (JsonElement) -> JsonElement) =
        expectEach(misses, fn, items, want, got)

    private fun expectEach(misses: Misses, fn: String, items: JsonElement, want: JsonElement, got: (JsonElement) -> JsonElement) {
        val xs = items.jsonArray
        val answers = want.jsonArray
        misses.check(xs.size == answers.size) { "$fn: ${xs.size} items, ${answers.size} answers" }
        for ((i, item) in xs.withIndex()) {
            val answer = safely { got(item) }
            misses.check(answer == answers.getOrNull(i)) { "$fn($item): $answer, Python's ${answers.getOrNull(i)}" }
        }
    }

    /** Each item of [items], the digest of its answers and Python's ([want], a digest an item). */
    private fun product(misses: Misses, fn: String, items: JsonElement, want: JsonElement, got: (JsonElement) -> JsonElement) {
        val xs = items.jsonArray
        val digests = want.jsonArray
        misses.check(xs.size == digests.size) { "$fn: ${xs.size} items, ${digests.size} digests" }
        for ((i, item) in xs.withIndex()) {
            val answer = safely { got(item) }
            misses.check(digest(answer) == digests.getOrNull(i)?.jsonPrimitive?.content) {
                "$fn($item): its answers differ from Python's: ${answer.toString().take(600)}"
            }
        }
    }

    private fun safely(got: () -> JsonElement): JsonElement = try {
        got()
    } catch (e: Exception) {
        JsonPrimitive("raised ${e.javaClass.simpleName}: ${e.message}")
    }

    private fun raised(e: Exception): JsonObject = JsonObject(mapOf("error" to JsonPrimitive(e.message)))

    /** The SHA-256 of [value]'s compact JSON, as Python's `sha256`. */
    fun sha(value: JsonElement): String = Canonical.sha256Hex(PyJson.dumps(value, compact = true).toByteArray(Charsets.UTF_8))

    /** Its first 16 hex digits, as Python's `digest`. */
    fun digest(value: JsonElement): String = sha(value).take(16)

    private fun key(e: JsonElement): Key? = TheoryReplay.key(e)
    private fun int(e: JsonElement): Int? = if (e is JsonNull) null else e.jsonPrimitive.int
    private fun text(e: JsonElement): String? = if (e is JsonNull) null else e.jsonPrimitive.content
    private fun json(s: String?): JsonElement = s?.let(::JsonPrimitive) ?: JsonNull
    private fun strings(e: JsonElement): List<String> = e.jsonArray.map { it.jsonPrimitive.content }
    private fun strings(xs: Collection<String>): JsonArray = JsonArray(xs.map(::JsonPrimitive))
}
