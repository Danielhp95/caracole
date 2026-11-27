package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
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
 * audio_store.py's answers (vectors/library/audio_store.jsonl, tests/test_conformance_audio_store.py) from
 * core.library.AudioStore: sniff and its two tests over every head, the shown name, the store's name patterns, the
 * kept file's name, a staged upload's record and a marker written and read, given_file over a tree made as the record
 * says, and songs._merge's given audio (`merge`: two songs an older normalizer kept apart, re-keyed into one).
 */
object AudioStoreReplay : AreaReplay {
    override val area = "audio-store"

    const val VECTOR = "library/audio_store.jsonl"

    override fun replay(misses: Misses) {
        val records = Corpus.records(VECTOR)
        check(records.isNotEmpty()) { "$VECTOR has no record" }
        val work = Files.createTempDirectory("audio-store").toFile()
        try {
            for ((n, record) in records.withIndex()) {
                when (record.fn) {
                    "sniff", "_mpeg_frame", "_mp4_audio" -> misses.expect(record) {
                        val head = Base64.getDecoder().decode(record.args[0].jsonPrimitive.content)
                        when (record.fn) {
                            "sniff" -> AudioStore.sniff(head)
                            "_mpeg_frame" -> AudioStore.mpegFrame(head)
                            else -> AudioStore.mp4Audio(head)
                        }
                    }
                    "_display_name" -> misses.expect(record) { AudioStore.displayName(record.args[0].jsonPrimitive.content) }
                    "names" -> misses.expect(record) { names(record.args[0].jsonPrimitive.content) }
                    "kept_name" -> misses.expect(record) {
                        AudioStore.keptName(record.kw.getValue("song").jsonPrimitive.long, text(record.kw, "sha256"),
                                            text(record.kw, "format"))
                    }
                    "record" -> misses.expect(record) {
                        val kw = record.kw
                        val tags = kw.getValue("tags").jsonObject.mapValues { (it.value as? JsonPrimitive)?.takeIf { p -> p.isString }?.content }
                        AudioStore.recordText(text(kw, "name"), kw.getValue("size").jsonPrimitive.long, text(kw, "sha256"),
                                              text(kw, "format"), number(kw, "duration"), tags, number(kw, "at"))
                    }
                    "_read_record" -> misses.expect(record) {
                        AudioStore.recordOf(record.args[0].jsonPrimitive.content.toByteArray(Charsets.UTF_8)) != null
                    }
                    "marker" -> misses.expect(record) {
                        AudioStore.markerText(text(record.kw, "kept"), record.kw.getValue("song").jsonPrimitive.long,
                                              number(record.kw, "at"))
                    }
                    "_read_marker" -> {
                        val got = AudioStore.markerOf(record.args[0].jsonPrimitive.content.toByteArray(Charsets.UTF_8))
                        val want = record.out as? JsonObject
                        misses.check((got == null) == (want == null) && (want == null || (got!!.first == text(want, "kept") &&
                            got.second == want.getValue("song").jsonPrimitive.long && got.third == number(want, "at")))) {
                            "_read_marker(${record.args[0]}) = $got, Python's $want"
                        }
                    }
                    "given_file" -> misses.expect(record) { givenFile(File(work, "given-$n"), record.kw) }
                    "merge" -> merge(misses, record.extra.getValue("case").jsonPrimitive.content, record.kw,
                                     record.out!!.jsonObject, File(work, "merge-$n"))
                    else -> misses.check(false) { "$VECTOR: no replay of ${record.fn}" }
                }
            }
        } finally {
            work.deleteRecursively()
        }
    }

    private fun names(name: String): JsonObject {
        fun id(m: MatchResult?) = m?.groups?.get("id")?.value?.let(::JsonPrimitive) ?: JsonNull
        val piece = AudioStore.PIECE.matchEntire(name)
        return JsonObject(mapOf(
            "id" to JsonPrimitive(AudioStore.ID.matches(name)),
            "piece" to (piece?.let { JsonArray(listOf(JsonPrimitive(it.groups["id"]!!.value), JsonPrimitive(it.groups["ext"]!!.value))) } ?: JsonNull),
            "staged_audio" to id(AudioStore.STAGED_AUDIO.matchEntire(name)),
            "marker" to id(AudioStore.MARKER.matchEntire(name)),
            "kept" to JsonPrimitive(AudioStore.KEPT.matches(name)),
            "part" to JsonPrimitive(AudioStore.PART.matches(name)),
        ))
    }

    /** The record's tree made under [root] (a file, a link to the first file, a folder), then given_file of its path. */
    private fun givenFile(root: File, kw: JsonObject): Boolean {
        var first: File? = null
        for (entry in kw.getValue("entries").jsonArray) {
            val (rel, kind) = entry.jsonArray.map { it.jsonPrimitive.content }
            val at = File(root, rel)
            at.parentFile.mkdirs()
            when (kind) {
                "file" -> at.writeBytes("audio".toByteArray()).also { if (first == null) first = at }
                "link" -> Files.createSymbolicLink(at.toPath(), first!!.toPath())
                else -> at.mkdir()
            }
        }
        val path = (kw.getValue("path") as? JsonPrimitive)?.takeIf { it.isString }?.content
        return AudioStore.givenFile(path?.let { File(root, it).path })
    }

    /** songs._merge's given audio: the songs' rows (their `{state}` the record's own folder) and files, the kv, then
     * ensure_current_keys; the songs' audio and the `audio:name:` records as Python left them. */
    private fun merge(misses: Misses, case: String, kw: JsonObject, out: JsonObject, dir: File) {
        val state = File(dir, "state")
        fun real(path: JsonElement?) = (path as? JsonPrimitive)?.takeIf { it.isString }?.content?.replace("{state}", state.path)
        fun spelled(path: String?) = path?.let { if (it.startsWith(state.path + "/")) "{state}/" + it.substring(state.path.length + 1) else it }
        for (file in kw.getValue("files").jsonArray) {
            File(state, file.jsonPrimitive.content).apply { parentFile.mkdirs(); writeBytes(ByteArray(16)) }
        }
        val rows = kw.getValue("songs").jsonArray.map { row ->
            val fields = row.jsonObject.toMutableMap()
            fields["audio_path"] = real(fields["audio_path"])?.let(::JsonPrimitive) ?: JsonNull
            JsonObject(mapOf("table" to JsonPrimitive("songs"), "row" to JsonObject(fields)))
        }
        val kv = kw.getValue("kv").jsonObject.map { (key, value) -> JsonObject(mapOf("kv" to JsonPrimitive(key), "value" to value)) }
        TestDb.fresh(dir).use { database ->
            database.writeBlocking { db ->
                Fixtures.loadRecords(db, rows + kv)
                db.kvDelete("songs:key_version") // as an older caracole stored them
                LibraryStore(File(dir, "library")).ensureCurrentKeys(db)
            }
            database.read { db ->
                val got = Songs.list(db).sortedBy { it.id }.map {
                    JsonObject(mapOf("audio_mtime" to (it.audioMtime?.let { m -> JsonPrimitive(m) } ?: JsonNull),
                                     "audio_path" to (spelled(it.audioPath)?.let(::JsonPrimitive) ?: JsonNull),
                                     "id" to JsonPrimitive(it.id)))
                }
                val want = out.getValue("songs").jsonArray.map { song ->
                    val o = song.jsonObject
                    JsonObject(mapOf("audio_mtime" to ((o["audio_mtime"] as? JsonPrimitive)?.takeIf { it !is JsonNull }
                        ?.content?.toDouble()?.let(::JsonPrimitive) ?: JsonNull),
                                     "audio_path" to (o["audio_path"] ?: JsonNull),
                                     "id" to JsonPrimitive(o.getValue("id").jsonPrimitive.long)))
                }
                misses.check(got == want) { "merge $case: songs $got, Python's $want" }
                val names = db.query("SELECT key, value FROM kv WHERE key LIKE 'audio:name:%' ORDER BY key") {
                    it.text(0)!! to it.text(1)!!
                }.toMap()
                val wantNames = out.getValue("kv").jsonObject.mapValues { it.value.jsonPrimitive.content }
                misses.check(names == wantNames) { "merge $case: kv $names, Python's $wantNames" }
            }
        }
    }

    private fun text(o: JsonObject, name: String) = o.getValue(name).jsonPrimitive.content
    private fun number(o: JsonObject, name: String) = o.getValue(name).jsonPrimitive.content.toDouble()
}
