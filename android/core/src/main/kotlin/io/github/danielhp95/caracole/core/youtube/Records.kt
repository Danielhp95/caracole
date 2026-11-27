package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.lyrics.internal.PyValues
import io.github.danielhp95.caracole.core.py.PyRe
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive

/**
 * youtube_fetch.Record: kv `youtube:<song id>`, a song's YouTube record: the video picked or pasted ([source]), the
 * file its audio went to, when its search last found nothing ([missingAt]), the videos passed over ([skip]), the
 * last error, a pasted video that can't be had ([unusable]), and how many downloads of each video failed since it
 * last came ([failures]: each a Python int as json.loads read it, a bool among them, as `isinstance(n, int)` takes
 * it, kept as it was read so that it is written back as it was).
 */
data class Record(
    val video: Video? = null,
    val source: String? = null,
    val audio: String? = null,
    val downloadedAt: String? = null,
    val missingAt: String? = null,
    val query: String? = null,
    val skip: List<String> = emptyList(),
    val error: String? = null,
    val errorAt: String? = null,
    val unusable: String? = null,
    val unusableReason: String? = null,
    val failures: Map<String, JsonPrimitive> = emptyMap(),
)

/**
 * The record's read and write, `load_record` and `_save`, as the data's `record` says: [load] reads what json.loads
 * makes of the kv text (a record that isn't an object is none), [save] writes [asJson] as json.dumps writes it, the
 * fields in Python's order, `missing_at` last and only when set. vectors/youtube/record.jsonl holds both to Python's
 * bytes (YouTubeReplay).
 */
object Records {
    private val record: JsonObject get() = YouTubeData.read().json.getValue("record") as JsonObject
    private val prefix: String get() = record.getValue("prefix").jsonPrimitive.content
    private val fields: List<String> get() = YouTubeData.read().texts("fields", record)

    /** The record's kv key. */
    fun key(songId: Long): String = prefix + songId

    /** load_record: the song's record, or an empty one. */
    fun load(db: Db, songId: Long): Record {
        val raw = db.kvGet(key(songId))?.let { PyJson.loads(it) } as? JsonObject ?: return Record()
        fun text(name: String): String? = PyValues.string(raw[name])?.takeIf { it.isNotEmpty() }
        val skip = (raw["skip"] as? JsonArray)?.mapNotNull { PyValues.string(it) }.orEmpty()
        val failures = (raw["failures"] as? JsonObject)?.entries
            ?.mapNotNull { (k, n) -> (n as? JsonPrimitive)?.takeIf { PyValues.intOrBool(it) != null }?.let { k to it } }
            ?.toMap(LinkedHashMap()).orEmpty()
        return Record(
            video = videoOf(raw["video"]), source = text("source"), audio = text("audio"),
            downloadedAt = text("downloaded_at"), missingAt = text("missing_at"), query = text("query"), skip = skip,
            error = text("error"), errorAt = text("error_at"), unusable = text("unusable"),
            unusableReason = text("unusable_reason"), failures = failures,
        )
    }

    /** _save. */
    fun save(db: Db, songId: Long, record: Record) = db.kvSetJson(key(songId), asJson(record))

    /** Record.as_json. */
    fun asJson(r: Record): JsonObject {
        fun t(v: String?): JsonElement = v?.let { JsonPrimitive(it) } ?: JsonNull
        val values = mapOf(
            "video" to (r.video?.let(::videoJson) ?: JsonNull), "source" to t(r.source), "audio" to t(r.audio),
            "downloaded_at" to t(r.downloadedAt), "query" to t(r.query), "skip" to JsonArray(r.skip.map(::JsonPrimitive)),
            "error" to t(r.error), "error_at" to t(r.errorAt), "unusable" to t(r.unusable),
            "unusable_reason" to t(r.unusableReason), "failures" to JsonObject(r.failures),
        )
        check(values.keys == fields.toSet()) { "youtube.json's record fields aren't the record's" }
        val out = LinkedHashMap<String, JsonElement>()
        for (name in fields) out[name] = values.getValue(name)
        if (!r.missingAt.isNullOrEmpty()) out[MISSING_AT] = JsonPrimitive(r.missingAt)
        return JsonObject(out)
    }

    /** Video.as_json. */
    fun videoJson(v: Video): JsonObject = JsonObject(linkedMapOf(
        "id" to JsonPrimitive(v.id), "title" to JsonPrimitive(v.title), "channel" to JsonPrimitive(v.channel),
        "duration" to (v.duration?.let { PyJson.float(it) } ?: JsonNull), "url" to JsonPrimitive(v.url),
    ))

    /** Video.from_json: an id the data's video_id matches whole, `str(title or "")`, `str(channel or "")`, and a
     * number's float duration (an int too big for a float is Python's OverflowError, an ArithmeticException). */
    fun videoOf(data: JsonElement?): Video? {
        if (data !is JsonObject) return null
        val id = PyValues.string(data["id"]) ?: return null
        if (PyRe.fullmatch(YouTubeData.read().videoId, id) == null) return null
        return Video(id, Videos.str(data["title"]), Videos.str(data["channel"]), PyValues.number(data["duration"]))
    }

    /** The one field written only when set. */
    private const val MISSING_AT = "missing_at"
}
