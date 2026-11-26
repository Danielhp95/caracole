package io.github.danielhp95.caracole.core.sync.internal.client

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.core.sync.SyncUnit
import io.github.danielhp95.caracole.core.sync.Units
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.IOException

/** The push the phone sends the computer (the plan's §5.3, peer_push.read_push_document's document). */
internal object Give {
    /** A unit the computer takes: its digest there as compared ([expected]), the phone's now ([digest]) and its
     * document ([unit]), both null for a unit the phone hasn't got (the computer removes it). */
    class Entry(val id: String, val expected: String?, val digest: String?, val unit: JsonObject?)

    /** The SHA-256 of every file a song document of [entries] keeps, each once, in order. */
    fun files(entries: List<Entry>): List<String> {
        val found = LinkedHashSet<String>()
        for (entry in entries) {
            val unit = entry.unit ?: continue
            if (entry.id.substringBefore('/') != "song") continue
            for (version in unit["versions"] as? JsonArray ?: continue) {
                for (file in (version as? JsonObject)?.get("files") as? JsonArray ?: continue) {
                    Documents.text((file as? JsonObject)?.get("sha256"))?.let(found::add)
                }
            }
        }
        return found.toList()
    }

    /** What the computer takes of a push at most, as its routes declare it (peer_push.py's constants, which
     * vectors/sync/push.jsonl holds PeerClient's to): `POST /peer/push/new`'s document ([new]), `POST /peer/push`'s
     * ([document]), and a push's files' bytes ([files]). A test's own, smaller. */
    data class Limits(val new: Long = PeerClient.PUSH_NEW_MAX, val document: Long = PeerClient.PUSH_DOCUMENT_MAX,
                      val files: Long = PeerClient.PUSH_MAX)

    /** A unit that alone passes what one push carries: its document ([TOO_LONG]) or its files ([TOO_HEAVY]),
     * peer_push's words. */
    const val TOO_LONG = "its document is longer than a push carries (16 MiB)"
    const val TOO_HEAVY = "its files are more than a push carries (2 GiB)"

    /** A SHA-256 in `push/new`'s `files`, as it is sent: 64 hex, its quotes and a comma (peer_push._NAMED). */
    private const val NAMED = 67

    /** [entries] cut into pushes within [limits], in order (peer_push._cut): each push's document ([document] of
     * them) within its limit, its `push/new` within its own and its files' bytes ([sizes], by SHA-256) within theirs,
     * a song and its tombstone (`song/K`, `removed/K`) in the same push; and the units that alone pass one of them,
     * each with why ([TOO_LONG], [TOO_HEAVY]). Lengths are those of the bytes PeerClient sends (PyJson's compact
     * text, as UTF-8). */
    fun cut(entries: List<Entry>, sizes: Map<String, Long>, limits: Limits, from: String,
            document: (List<Entry>) -> JsonObject): Pair<List<List<Entry>>, List<Pair<String, String>>> {
        val base = bytes(document(emptyList()))  // its "take": [] counted
        val newBase = bytes(JsonObject(linkedMapOf("format" to JsonPrimitive(Units.FORMAT),
                                                    "from" to JsonPrimitive(from), "files" to JsonArray(emptyList()))))
        val groups = LinkedHashMap<String, MutableList<Entry>>()
        for (entry in entries) {
            val kind = entry.id.substringBefore('/')
            val key = if (kind == "song" || kind == "removed") "song/" + entry.id.substringAfter('/') else entry.id
            groups.getOrPut(key) { ArrayList() }.add(entry)
        }
        val pushes = ArrayList<List<Entry>>()
        val tooMuch = ArrayList<Pair<String, String>>()
        var batch = ArrayList<Entry>()
        var length = 0L
        var named = HashSet<String>()
        var weight = 0L
        for (group in groups.values) {
            val more = group.sumOf { bytes(entryJson(it)) + 1 }  // each entry and its comma
            val files = files(group).toSet()
            if (base + more - 1 > limits.document) {
                group.mapTo(tooMuch) { it.id to TOO_LONG }
                continue
            }
            if (newBase + NAMED.toLong() * files.size - 1 > limits.new || files.sumOf { sizes[it] ?: 0L } > limits.files) {
                group.mapTo(tooMuch) { it.id to TOO_HEAVY }
                continue
            }
            var new = files - named
            if (batch.isNotEmpty() && (base + length + more - 1 > limits.document ||
                    newBase + NAMED.toLong() * (named.size + new.size) - 1 > limits.new ||
                    weight + new.sumOf { sizes[it] ?: 0L } > limits.files)) {
                pushes.add(batch)
                batch = ArrayList()
                length = 0L
                named = HashSet()
                weight = 0L
                new = files
            }
            batch.addAll(group)
            length += more
            named.addAll(new)
            weight += new.sumOf { sizes[it] ?: 0L }
        }
        if (batch.isNotEmpty()) pushes.add(batch)
        return pushes to tooMuch
    }

    private fun bytes(doc: JsonObject): Long = PyJson.dumps(doc, compact = true).toByteArray(Charsets.UTF_8).size.toLong()

    /** The size of the largest regular file under [libraryDir] the phone keeps of SHA-256 [sha256] (as [read] finds
     * one, never through a link); 0 for none, which its push then finds changed. */
    fun size(database: Database, libraryDir: File, sha256: String): Long {
        val paths = database.read { db -> db.query("SELECT path FROM files WHERE sha256 = ? ORDER BY id", sha256) { it.text(0) } }
        val root = libraryDir.canonicalFile
        var found = 0L
        for (path in paths.filterNotNull()) {
            val file = File(root, path)
            try {
                val real = file.canonicalFile
                if (!real.path.startsWith(root.path + File.separator) || real.path != file.absoluteFile.normalize().path ||
                    !real.isFile) continue
                found = maxOf(found, real.length())
            } catch (e: IOException) {
                continue
            }
        }
        return found
    }

    /** The bytes of a file the phone keeps whose SHA-256 is [sha256], read from its library folder (a regular file
     * under it, never through a link), as peer_push.kept_copy reads one; null when none is as recorded any more. */
    fun read(database: Database, libraryDir: File, sha256: String): ByteArray? {
        val paths = database.read { db -> db.query("SELECT path FROM files WHERE sha256 = ? ORDER BY id", sha256) { it.text(0) } }
        val root = libraryDir.canonicalFile
        for (path in paths.filterNotNull()) {
            val file = File(root, path)
            val bytes = try {
                val real = file.canonicalFile
                if (!real.path.startsWith(root.path + File.separator) || real.path != file.absoluteFile.normalize().path ||
                    !real.isFile) continue
                real.readBytes()
            } catch (e: IOException) {
                continue
            }
            if (Canonical.sha256Hex(bytes) == sha256) return bytes
        }
        return null
    }

    /** The push document: who pushes, the rules its songs are keyed by (Normalize.KEY_VERSION), its state after its
     * own take ([state]), and the units the computer takes. */
    fun document(from: String, name: String, caracole: String, at: String, state: Map<String, SyncUnit>,
                 entries: List<Entry>): JsonObject = JsonObject(linkedMapOf(
        "format" to JsonPrimitive(Units.FORMAT),
        "from" to JsonPrimitive(from),
        "name" to JsonPrimitive(name),
        "caracole" to JsonPrimitive(caracole),
        "key_version" to JsonPrimitive(Normalize.KEY_VERSION),
        "at" to JsonPrimitive(at),
        "units" to JsonObject(state.values.associate { unit ->
            unit.id to JsonObject(linkedMapOf("label" to JsonPrimitive(unit.label), "digest" to JsonPrimitive(unit.digest)))
        }),
        "take" to JsonArray(entries.map(::entryJson)),
    ))

    /** A unit of a push document's `take`. */
    private fun entryJson(entry: Entry): JsonObject = JsonObject(linkedMapOf(
        "id" to JsonPrimitive(entry.id),
        "expected" to text(entry.expected),
        "digest" to text(entry.digest),
        "unit" to (entry.unit ?: JsonNull),
    ))

    /** What the computer's request said of each unit as it took the push (Job.as_json's `units`: [id, outcome, why]
     * each, outcome "taken", "given" or "left"), by its id; its odd entries left out. */
    fun units(job: JsonObject): Map<String, Pair<String, String>> {
        val found = LinkedHashMap<String, Pair<String, String>>()
        for (entry in job["units"] as? JsonArray ?: return found) {
            val parts = entry as? JsonArray ?: continue
            val id = Documents.text(parts.getOrNull(0)) ?: continue
            val outcome = Documents.text(parts.getOrNull(1)) ?: continue
            found[id] = outcome to (Documents.text(parts.getOrNull(2)) ?: "")
        }
        return found
    }

    /** A text value, or null for anything else. */
    fun text(e: JsonElement?): String? = Documents.text(e)

    private fun text(value: String?): JsonElement = value?.let(::JsonPrimitive) ?: JsonNull
}
