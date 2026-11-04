package io.github.danielhp95.caracole.core.testing.replays

import androidx.sqlite.SQLITE_DATA_FLOAT
import androidx.sqlite.SQLITE_DATA_INTEGER
import androidx.sqlite.SQLITE_DATA_NULL
import androidx.sqlite.SQLITE_DATA_TEXT
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.PagesNotFiles
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.http.ProviderUnavailable
import io.github.danielhp95.caracole.core.http.RobotsClosed
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.KeptFile
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Numbering
import io.github.danielhp95.caracole.core.library.PassStats
import io.github.danielhp95.caracole.core.library.Passes
import io.github.danielhp95.caracole.core.library.SharedFolder
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.VersionRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.sync.Units
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
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.security.MessageDigest
import java.util.Base64
import kotlin.reflect.KClass

/**
 * Kept files, versions, numbering and the pass ladder (vectors/library/writes.jsonl, tests/test_conformance_library
 * _writes.py), each record replayed as Python made it: its fixture (vectors/library/writes_fixture_<name>.jsonl) into
 * a fresh database and library folder, its changes to the folder, the call; then what it returned (or raised), each
 * row of `songs`, `versions` and `files` and each file of the library as the record says the call left them (every
 * other as before it), and Units.libraryState's digests, Python's peer_sync.library_state's.
 */
object LibraryWritesReplay : AreaReplay {
    override val area = "library-writes"

    const val VECTOR = "library/writes.jsonl"
    private val TABLES = listOf("songs", "versions", "files")

    override fun replay(misses: Misses) = replay(misses) { true }

    /** The records whose `fn` [which] keeps (each lane test replays its own: `caracole.library.`, …). */
    fun replay(misses: Misses, which: (String) -> Boolean) {
        val records = Corpus.records(VECTOR).filter { which(it.fn) }
        check(records.isNotEmpty()) { "no record of $VECTOR is the test's" }
        val work = Files.createTempDirectory("library-writes").toFile()
        try {
            records.forEachIndexed { i, record ->
                val case = "${record.fn.substringAfterLast('.')}: ${text(record.extra["case"])}"
                try {
                    if (record.extra["fixture"] is JsonNull) eachSong(misses, case, record)
                    else written(misses, case, record, File(work, "$i"))
                } catch (e: Exception) {
                    misses.check(false) { "$case: the replay threw $e" }
                }
            }
        } finally {
            work.deleteRecursively()
        }
    }

    // --- a call over a fixture --------------------------------------------------------------------------------------

    private fun written(misses: Misses, case: String, record: Record, dir: File) {
        dir.mkdirs()
        val library = File(dir, "library")
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { db ->
                Fixtures.load(db, "library/writes_fixture_${text(record.extra["fixture"])}.jsonl", library)
                val lib = LibraryStore(library)
                for ((path, change) in (record.extra["changes"] as? JsonObject).orEmpty()) {
                    val file = File(library, path)
                    if (change is JsonNull) check(file.delete()) { "$case: no $path to delete" }
                    else {
                        file.parentFile.mkdirs()
                        file.writeBytes(bytes(change))
                    }
                }
                val rowsBefore = TABLES.associateWith { rows(db, it) }
                val filesBefore = files(library)
                val (got, raised) = try {
                    call(db, lib, record.fn, record.kw) to null
                } catch (e: Exception) {
                    null to e
                }
                when {
                    record.err == null && raised != null ->
                        misses.check(false) { "$case: threw $raised, Python answered ${record.out}" }
                    record.err == null -> misses.check(dumps(got) == dumps(record.out)) {
                        "$case: answered ${dumps(got)}, Python ${dumps(record.out)}"
                    }
                    record.err == "KeyError" -> misses.check(raised == null && got == JsonNull) {
                        "$case: answered $got ($raised), Python raised KeyError (the phone's null)"
                    }
                    else -> {
                        val want = mapOf("SharedFolder" to SharedFolder::class,
                                         "ValueError" to IllegalArgumentException::class)[record.err]
                        misses.check(want != null && want.isInstance(raised)) {
                            "$case: ${raised ?: "answered $got"}, Python raised ${record.err}"
                        }
                        val message = text(record.extra["message"])
                        misses.check(message == null || raised?.message == message) {
                            "$case: said ${raised?.message}, Python $message"
                        }
                    }
                }
                val after = record.extra.getValue("after").jsonObject
                for (table in TABLES) {
                    val want = expected(rowsBefore.getValue(table), after["rows"]?.jsonObject?.get(table),
                                        after["gone"]?.jsonObject?.get(table))
                    val have = rows(db, table)
                    misses.check(dumps(JsonArray(have)) == dumps(JsonArray(want))) {
                        "$case: $table is ${firstDifference(have, want)}"
                    }
                }
                val wantFiles = filesBefore.toMutableMap()
                for ((path, sha) in after.getValue("library").jsonObject) {
                    if (sha is JsonNull) wantFiles.remove(path) else wantFiles[path] = sha.jsonPrimitive.content
                }
                val haveFiles = files(library)
                misses.check(haveFiles == wantFiles) { "$case: the library holds $haveFiles, Python's $wantFiles" }
                val units = Units.libraryState(db).mapValues { it.value.digest }
                val wantUnits = after.getValue("units").jsonObject.mapValues { it.value.jsonPrimitive.content }
                misses.check(units == wantUnits) { "$case: the units are $units, Python's $wantUnits" }
            }
        }
    }

    /** What the record's call answers, as JSON the way Python's corpus writes it (a song as its key, a version or a
     * kept file as an object of its fields). */
    private fun call(db: Db, lib: LibraryStore, fn: String, kw: JsonObject): JsonElement {
        fun song(): SongRow = Songs.byKey(db, text(kw["song"])!!) ?: error("no song ${kw["song"]}")
        fun long(name: String): Long = kw.getValue(name).jsonPrimitive.long
        fun str(name: String): String = text(kw[name])!!
        fun raw(): JsonObject = PyJson.loads(str("raw")).jsonObject
        fun kinds(name: String): List<String>? = (kw[name] as? JsonArray)?.map { it.jsonPrimitive.content }
        return when (fn.removePrefix("caracole.")) {
            "library.keep_file" -> JsonPrimitive(Kept.keepFile(db, lib, song(), long("version_id"), str("name"),
                                                               bytes(kw.getValue("data")), long("rank").toInt(),
                                                               str("now")))
            "library.kept_already" -> JsonPrimitive(Kept.keptAlready(db, lib, song(), long("version_id"), str("name"),
                                                                     bytes(kw.getValue("data"))))
            "library.kept_files" -> JsonArray(Kept.keptFiles(db, song().id).map(::keptJson))
            "library.keeper_of" -> Kept.keeperOf(db, lib, song(), str("name"))?.let { JsonPrimitive(it.key) } ?: JsonNull
            "library.holds" -> JsonPrimitive(Kept.holds(lib.libraryDir.toPath().resolve(str("path")), str("sha256"),
                                                        (kw["size"] as? JsonPrimitive)?.takeIf { it !is JsonNull }
                                                            ?.long))
            "library.drop_file" -> JsonNull.also { Kept.dropFile(db, lib, song(), str("name")) }
            "library.write_atomic" -> JsonPrimitive(Kept.writeAtomic(lib.libraryDir.toPath().resolve(str("path")),
                                                                     bytes(kw.getValue("data"))))
            "versions.upsert_version" -> JsonPrimitive(Versions.upsert(
                db, str("provider"), str("tab_id"), song().id, str("slot"), str("kind"),
                kw.getValue("rating").jsonPrimitive.content.toDouble(), long("votes").toInt(), long("version").toInt(),
                text(kw["label"]), str("url"), raw(), str("now"),
            ))
            "versions.song_versions" -> JsonArray(Versions.songVersions(
                db, song().id, text(kw["slot"]), kinds("kinds"), kw.getValue("include_gone").jsonPrimitive.content == "true",
            ).map(::versionJson))
            "versions.get_version" -> Versions.get(db, long("version_id"))?.let(::versionJson) ?: JsonNull
            "versions.set_raw" -> JsonNull.also { Versions.setRaw(db, long("version_id"), raw()) }
            "versions.set_coverage" -> JsonNull.also {
                Versions.setCoverage(db, long("version_id"), (kw["value"] as? JsonPrimitive)
                    ?.takeIf { it !is JsonNull }?.content?.toDouble())
            }
            "versions.mark_gone" -> JsonNull.also { Versions.markGone(db, long("version_id")) }
            "versions.mark_stale" -> JsonPrimitive(Versions.markStale(db, song().id, str("provider")))
            "versions.set_picks" -> JsonNull.also {
                Versions.setPicks(db, song().id, kinds("kinds")!!,
                                  kw.getValue("version_ids").jsonArray.map { it.jsonPrimitive.long })
            }
            "versions.picks" -> JsonArray(Versions.picks(db, song().id, kinds("kinds")!!).map(::versionJson))
            "songs.update_song" -> JsonNull.also {
                Versions.updateSong(db, song().id, kw.getValue("fields").jsonObject.mapValues { value(it.value) },
                                    str("now"))
            }
            "songs.refresh_status" -> JsonPrimitive(Versions.refreshStatus(
                db, song().id, kw.getValue("ignored").jsonPrimitive.content == "true", str("now"),
            ))
            "inbox.guitar_number" -> JsonPrimitive(Numbering.guitar(db, lib, song()))
            "inbox.harmonica_number" -> JsonPrimitive(Numbering.harmonica(db, lib, song()))
            "inbox.gametab_number" -> JsonPrimitive(Numbering.gametab(db, lib, song()))
            "inbox.score_number" -> JsonPrimitive(Numbering.score(db, lib, song(), str("ext")))
            else -> throw AssertionError("no replay of $fn")
        }
    }

    /** A JSON value of the record as a caller of updateSong gives it: a text, a whole number as a Long, any other
     * number as a Double, a boolean, null; a list or an object as JSON. */
    private fun value(e: JsonElement): Any? = when {
        e is JsonNull -> null
        e is JsonPrimitive && e.isString -> e.content
        e is JsonPrimitive && (e.content == "true" || e.content == "false") -> e.content == "true"
        e is JsonPrimitive -> e.content.toLongOrNull() ?: e.content.toDouble()
        else -> e
    }

    fun versionJson(v: VersionRow): JsonObject = JsonObject(mapOf(
        "id" to JsonPrimitive(v.id), "provider" to JsonPrimitive(v.provider), "tab_id" to JsonPrimitive(v.tabId),
        "song_id" to JsonPrimitive(v.songId), "slot" to JsonPrimitive(v.slot), "kind" to JsonPrimitive(v.kind),
        "rating" to PyJson.float(v.rating), "votes" to JsonPrimitive(v.votes), "version" to JsonPrimitive(v.version),
        "label" to (v.label?.let(::JsonPrimitive) ?: JsonNull),
        "coverage" to (v.coverage?.let(PyJson::float) ?: JsonNull), "url" to JsonPrimitive(v.url), "raw" to v.raw,
        "fetched_at" to JsonPrimitive(v.fetchedAt), "pick_rank" to (v.pickRank?.let(::JsonPrimitive) ?: JsonNull),
        "gone" to JsonPrimitive(v.gone), "stale" to JsonPrimitive(v.stale),
    ))

    private fun keptJson(f: KeptFile): JsonObject = JsonObject(mapOf(
        "id" to JsonPrimitive(f.id), "version_id" to JsonPrimitive(f.versionId), "song_id" to JsonPrimitive(f.songId),
        "name" to JsonPrimitive(f.name), "path" to JsonPrimitive(f.path), "sha256" to JsonPrimitive(f.sha256),
        "kept_rank" to JsonPrimitive(f.keptRank),
    ))

    // --- provider_pass.each_song ------------------------------------------------------------------------------------

    private fun eachSong(misses: Misses, case: String, record: Record) {
        val kw = record.kw
        val names = kw.getValue("songs").jsonArray.map { it.jsonPrimitive.content }
        val turns = kw.getValue("turns").jsonObject.mapValues { it.value.jsonPrimitive.content }
        val stop: Map<String, KClass<out ProviderError>> =
            mapOf("error" to ProviderError::class, "robots" to RobotsClosed::class, "pages" to PagesNotFiles::class)
        val stopOn = kw.getValue("stop_on").jsonArray.map { stop.getValue(it.jsonPrimitive.content) }.toSet()
        val events = mutableListOf<String>()
        val stats = PassStats()
        val songs = names.asSequence().map { events += "read $it"; stub(it) }
        val raised = try {
            for ((song, outcome) in Passes.eachSong(songs, stats, "site", stopOn,
                                                    { s, e -> events += "error ${s.key} ${e::class.simpleName}" }) {
                events += "turn ${it.key}"
                val word = turns[it.key] ?: "ok"
                if (word != "ok") throw raised(word, it.key)
                "${it.key} done"
            }) events += "got ${song.key} $outcome"
            null
        } catch (e: Exception) {
            e::class.simpleName
        }
        val got = JsonObject(mapOf(
            "events" to JsonArray(events.map(::JsonPrimitive)), "raised" to (raised?.let(::JsonPrimitive) ?: JsonNull),
            "stats" to statsJson(stats),
        ))
        misses.check(dumps(got) == dumps(record.out)) { "$case: ${dumps(got)}, Python ${dumps(record.out)}" }
        // The list's overload: the same stats, every turn's work inside it.
        val listed = PassStats()
        val again = try {
            Passes.eachSong(names.map(::stub), listed, "site", stopOn) { if ((turns[it.key] ?: "ok") != "ok") throw raised(turns.getValue(it.key), it.key) }
            null
        } catch (e: Exception) {
            e::class.simpleName
        }
        misses.check(again == raised && dumps(statsJson(listed)) == dumps(statsJson(stats))) {
            "$case: over a list, ${dumps(statsJson(listed))} ($again)"
        }
    }

    private fun statsJson(stats: PassStats): JsonObject = JsonObject(mapOf(
        "tried" to JsonPrimitive(stats.tried), "errors" to JsonPrimitive(stats.errors),
        "budget_exhausted" to JsonPrimitive(stats.budgetExhausted),
        "failures" to JsonArray(stats.failures.map { (s, e) ->
            JsonArray(listOf(JsonPrimitive(s.key), JsonPrimitive(e::class.simpleName), JsonPrimitive(e.message)))
        }),
    ))

    private fun raised(word: String, name: String): Exception = when (word) {
        "budget" -> BudgetExhausted("site")
        "error" -> ProviderError("site", "https://s/$name", 500, "busy")
        "robots" -> RobotsClosed("site", "https://s/$name", 500, "busy")
        "pages" -> PagesNotFiles("site", "https://s/$name", 500, "busy")
        "blocked" -> ProviderBlocked("site", "https://s/$name", 500, "busy")
        "unavailable" -> ProviderUnavailable("site", "https://s/$name", 500, "busy")
        else -> throw AssertionError("no turn $word")
    }

    /** A song as each_song reads one, by its name alone. */
    fun stub(name: String): SongRow = SongRow(
        id = 0, key = name, artist = name, title = name, artists = listOf(name), album = null, durationMs = null,
        isrc = null, sourceIds = "{}", addedAt = "", variant = null, status = "wanted", review = false,
        matchDecision = null, matchStep = null, matchScore = null, matchArtistKey = null, matchSongKey = null,
        matchCandidates = "[]", matchedAt = null, ugDirty = true, ugCheckedAt = null, lyricsStatus = "pending",
        lyricsJson = null, lyricsAt = null, lacuerdaCheckedAt = null, createdAt = "",
    )

    // --- reading the database and the library -----------------------------------------------------------------------

    /** The table's rows in rowid order, each cell as Python's sqlite3 reads it and its json writes it. */
    fun rows(db: Db, table: String): List<JsonObject> = db.raw.prepare("SELECT * FROM $table ORDER BY rowid").use { st ->
        val names = (0 until st.getColumnCount()).map { st.getColumnName(it) }
        val out = ArrayList<JsonObject>()
        while (st.step()) {
            out += JsonObject(names.withIndex().associate { (i, name) ->
                name to when (st.getColumnType(i)) {
                    SQLITE_DATA_NULL -> JsonNull
                    SQLITE_DATA_INTEGER -> JsonPrimitive(st.getLong(i))
                    SQLITE_DATA_FLOAT -> PyJson.float(st.getDouble(i))
                    SQLITE_DATA_TEXT -> JsonPrimitive(st.getText(i))
                    else -> throw AssertionError("$table.$name holds a blob")
                }
            })
        }
        out
    }

    /** The rows [before] the call, those the record says it wrote in their place (or added), those it deleted gone,
     * in rowid (id) order. */
    private fun expected(before: List<JsonObject>, wrote: JsonElement?, gone: JsonElement?): List<JsonObject> {
        val byId = LinkedHashMap<Long, JsonObject>()
        for (row in before) byId[row.getValue("id").jsonPrimitive.long] = row
        for (row in (wrote as? JsonArray).orEmpty()) byId[row.jsonObject.getValue("id").jsonPrimitive.long] = row.jsonObject
        for (id in (gone as? JsonArray).orEmpty()) byId.remove(id.jsonPrimitive.long)
        return byId.entries.sortedBy { it.key }.map { it.value }
    }

    private fun firstDifference(have: List<JsonObject>, want: List<JsonObject>): String {
        val i = (0 until maxOf(have.size, want.size)).firstOrNull { have.getOrNull(it) != want.getOrNull(it) }
            ?: return "the same row by row, written otherwise"
        return "${have.getOrNull(i)?.let(::dumps)} at row $i, Python's ${want.getOrNull(i)?.let(::dumps)}"
    }

    /** Every regular file under [root], by its path relative to it, with its SHA-256. */
    fun files(root: File): Map<String, String> {
        if (!root.isDirectory) return emptyMap()
        val base = root.toPath()
        val found = ArrayList<Path>()
        Files.walk(base).use { paths -> paths.forEach { if (Files.isRegularFile(it, LinkOption.NOFOLLOW_LINKS)) found.add(it) } }
        return found.associate { p -> base.relativize(p).joinToString("/") to sha256(Files.readAllBytes(p)) }
    }

    private fun sha256(data: ByteArray): String {
        val digits = "0123456789abcdef"
        val out = StringBuilder(64)
        for (b in MessageDigest.getInstance("SHA-256").digest(data)) {
            out.append(digits[(b.toInt() shr 4) and 15]).append(digits[b.toInt() and 15])
        }
        return out.toString()
    }

    private fun bytes(e: JsonElement): ByteArray = Base64.getDecoder().decode(e.jsonObject.getValue("base64").jsonPrimitive.content)

    private fun text(e: JsonElement?): String? = if (e == null || e is JsonNull) null else e.jsonPrimitive.content

    /** JSON as the corpus writes it: members sorted, every literal as written. */
    private fun dumps(e: JsonElement?): String = PyJson.dumps(e ?: JsonNull, sortKeys = true)
}
