package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.inbox.Filed
import io.github.danielhp95.caracole.core.inbox.Inbox
import io.github.danielhp95.caracole.core.inbox.MusicNames
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
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
import java.util.Base64

/**
 * A file shared to the app, filed as inbox.py files an `_inbox/` entry (vectors/inbox/, tests/test_conformance_inbox
 * .py): parse_download_name and music.Names over download names (names.jsonl), the song a download is of
 * (match.jsonl), and one file filed over the fixture library (file.jsonl: the fixture into a fresh database and
 * library folder, its changes to the folder, Inbox.file; what it came to, each row of `songs`, `versions` and `files`
 * and each file of the library as the record says the filing left them, every other as before).
 */
object InboxReplay : AreaReplay {
    override val area = "inbox"

    const val NAMES = "inbox/names.jsonl"
    const val MATCH = "inbox/match.jsonl"
    const val FILE = "inbox/file.jsonl"
    private const val FIXTURE = "inbox/file_fixture_library.jsonl"
    private val TABLES = listOf("songs", "versions", "files")

    override fun replay(misses: Misses) {
        names(misses)
        match(misses)
        file(misses)
    }

    /** parse_download_name's answers and music.Names' forms and scores. */
    fun names(misses: Misses) {
        for (record in Corpus.records(NAMES)) {
            when (record.fn) {
                "caracole.inbox.parse_download_name" -> {
                    val name = record.args[0].jsonPrimitive.content
                    misses.expect(record) {
                        val (artist, title, version) = Inbox.parseDownloadName(name)
                        // A version is Python's int, of any size: the JSON number as Python wrote it.
                        JsonArray(listOf(artist?.let(::JsonPrimitive) ?: JsonNull, JsonPrimitive(title),
                                         version?.let { JsonPrimitive(it) } ?: JsonNull))
                    }
                }
                "caracole.music.Names" -> {
                    val (a, b) = listOf("a", "b").map { side ->
                        record.kw.getValue(side).jsonArray.map { it.jsonPrimitive.content }
                    }
                    val own = MusicNames.of(a[0], a[1])
                    val other = MusicNames.of(b[0], b[1])
                    val want = record.out!!.jsonObject
                    misses.check(own.artists == strings(want["artists"]) && own.titles == strings(want["titles"])) {
                        "Names.of($a): ${own.artists} ${own.titles}, Python's ${want["artists"]} ${want["titles"]}"
                    }
                    for ((field, got) in listOf("title_score" to own.titleScore(other),
                                                "artist_score" to own.artistScore(other), "score" to own.score(other))) {
                        val python = want.getValue(field).jsonPrimitive.content.toDouble()
                        misses.check(got == python) { "Names.of($a).$field(Names.of($b)) = $got, Python's $python" }
                    }
                }
                else -> misses.check(false) { "no replay of ${record.fn}" }
            }
        }
    }

    /** _match's song, by its index in the record's songs. */
    fun match(misses: Misses) {
        for (record in Corpus.records(MATCH)) {
            val kw = record.kw
            val songs = kw.getValue("songs").jsonArray.mapIndexed { i, s ->
                val (artist, title, key) = s.jsonArray.map { it.jsonPrimitive.content }
                LibraryWritesReplay.stub(key).copy(id = i.toLong() + 1, artist = artist, title = title)
            }
            val artist = (kw["artist"] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content
            val title = kw.getValue("title").jsonPrimitive.content
            val got = Inbox.match(artist, title, songs)?.let { songs.indexOf(it) }
            val want = (record.out as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content?.toInt()
            misses.check(got == want) { "_match: ${text(record.extra["case"])}: song $got, Python's $want" }
        }
    }

    /** Each file filed over the fixture library. */
    fun file(misses: Misses) {
        val records = Corpus.records(FILE)
        check(records.isNotEmpty()) { "no record of $FILE" }
        val work = Files.createTempDirectory("inbox").toFile()
        try {
            records.forEachIndexed { i, record ->
                val case = "file: ${text(record.extra["case"])}"
                try {
                    filed(misses, case, record, File(work, "$i"))
                } catch (e: Exception) {
                    misses.check(false) { "$case: the replay threw $e" }
                }
            }
        } finally {
            work.deleteRecursively()
        }
    }

    private fun filed(misses: Misses, case: String, record: Record, dir: File) {
        dir.mkdirs()
        val library = File(dir, "library")
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { db ->
                Fixtures.load(db, FIXTURE, library)
                val lib = LibraryStore(library)
                for ((path, change) in (record.extra["changes"] as? JsonObject).orEmpty()) {
                    val file = File(library, path)
                    if (change is JsonNull) check(file.delete()) { "$case: no $path to delete" }
                    else file.writeBytes(bytes(change))
                }
                val rowsBefore = TABLES.associateWith { LibraryWritesReplay.rows(db, it) }
                val filesBefore = LibraryWritesReplay.files(library)
                val kw = record.kw
                val name = kw.getValue("name").jsonPrimitive.content
                val data = bytes(kw.getValue("data"))
                val got = try {
                    out(db, Inbox.file(db, lib, name, data, kw.getValue("now").jsonPrimitive.content)) {
                        Inbox.held(db, lib, name, data)?.let { it.songId to it.name }
                    }
                } catch (e: Exception) {
                    misses.check(false) { "$case: threw $e, Python answered ${record.out}" }
                    return@writeBlocking
                }
                misses.check(dumps(got) == dumps(record.out)) { "$case: ${dumps(got)}, Python's ${dumps(record.out)}" }
                val after = record.extra.getValue("after").jsonObject
                for (table in TABLES) {
                    val want = expected(rowsBefore.getValue(table), after["rows"]?.jsonObject?.get(table),
                                        after["gone"]?.jsonObject?.get(table))
                    val have = LibraryWritesReplay.rows(db, table)
                    misses.check(dumps(JsonArray(have)) == dumps(JsonArray(want))) {
                        "$case: $table is ${have.map(::dumps).minus(want.map(::dumps).toSet())}, Python's " +
                            "${want.map(::dumps).minus(have.map(::dumps).toSet())}"
                    }
                }
                val wantFiles = filesBefore.toMutableMap()
                for ((path, sha) in after.getValue("library").jsonObject) {
                    if (sha is JsonNull) wantFiles.remove(path) else wantFiles[path] = sha.jsonPrimitive.content
                }
                val haveFiles = LibraryWritesReplay.files(library)
                misses.check(haveFiles == wantFiles) { "$case: the library holds $haveFiles, Python's $wantFiles" }
            }
        }
    }

    /** What filing came to, as the record writes it (a song by its key; a duplicate's copy, Inbox.held's). */
    private fun out(db: Db, filed: Filed, held: () -> Pair<Long, String>?): JsonObject {
        fun key(id: Long): JsonPrimitive = JsonPrimitive(Songs.byId(db, id)?.key ?: "song $id")
        return when (filed) {
            is Filed.Kept -> JsonObject(mapOf("filed" to JsonPrimitive("kept"), "song" to key(filed.songId),
                                              "name" to JsonPrimitive(filed.name)))
            is Filed.PutBack -> JsonObject(mapOf("filed" to JsonPrimitive("put_back"),
                                                 "paths" to JsonArray(filed.paths.map(::JsonPrimitive))))
            Filed.Duplicate -> held()?.let { (song, name) ->
                JsonObject(mapOf("filed" to JsonPrimitive("duplicate"), "song" to key(song), "name" to JsonPrimitive(name)))
            } ?: JsonObject(mapOf("filed" to JsonPrimitive("duplicate"), "held" to JsonPrimitive("none")))
            Filed.Unmatched -> JsonObject(mapOf("filed" to JsonPrimitive("unmatched")))
        }
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

    private fun strings(e: JsonElement?): List<String> = (e as? JsonArray).orEmpty().map { it.jsonPrimitive.content }

    private fun bytes(e: JsonElement): ByteArray = Base64.getDecoder().decode(e.jsonObject.getValue("base64").jsonPrimitive.content)

    private fun text(e: JsonElement?): String? = if (e == null || e is JsonNull) null else e.jsonPrimitive.content

    /** JSON as the corpus writes it: members sorted, every literal as written. */
    private fun dumps(e: JsonElement?): String = PyJson.dumps(e ?: JsonNull, sortKeys = true)
}
