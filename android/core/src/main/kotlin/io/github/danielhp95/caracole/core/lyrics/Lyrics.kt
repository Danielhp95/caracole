package io.github.danielhp95.caracole.core.lyrics

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.internal.LyricsFiles
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull

/**
 * lyrics.py's Lyrics: a song's lyrics, from one record of one provider. [plain] is "" when there are none, [synced]
 * LRC text or null, [duration] the record's in seconds, [raw] the record as the provider sent it, [provider] who
 * answered (lrclib, megalobiz, azlyrics), [url] the record's page, which caracole links to wherever it credits them.
 */
data class Lyrics(val plain: String, val synced: String?, val instrumental: Boolean, val duration: Double?,
                  val lrclibId: Long?, val raw: JsonObject = JsonObject(emptyMap()), val provider: String = PROVIDER,
                  val url: String? = null) {
    /** Whether there is any lyric text at all. */
    val hasLyrics: Boolean get() = Py.strip(plain).isNotEmpty()

    /** Lyrics.to_json: the `songs.lyrics_json` column's text, json.dumps(…, ensure_ascii=False). */
    fun toJson(): String = PyJson.dumps(JsonObject(linkedMapOf(
        "plain" to JsonPrimitive(plain), "synced" to (synced?.let(::JsonPrimitive) ?: JsonNull),
        "instrumental" to JsonPrimitive(instrumental), "duration" to (duration?.let { PyJson.float(it) } ?: JsonNull),
        "lrclib_id" to (lrclibId?.let(::JsonPrimitive) ?: JsonNull), "raw" to raw, "provider" to JsonPrimitive(provider),
        "url" to (url?.let(::JsonPrimitive) ?: JsonNull),
    )))

    companion object {
        const val PROVIDER = "lrclib"

        /** Lyrics.from_record: an LRCLIB record read; plain lyrics lose their LRC ID tags and come from the synced
         * ones when missing. */
        fun fromRecord(raw: JsonObject): Lyrics {
            val synced = text(raw["syncedLyrics"])
            val fromSynced = plainFromSynced(synced)
            val plain = withoutIdTags(text(raw["plainLyrics"]))
            return Lyrics(
                plain = if (Py.strip(plain).isNotEmpty()) plain else fromSynced,
                synced = if (fromSynced.isNotEmpty()) synced else null,
                instrumental = (raw["instrumental"] as? JsonPrimitive)?.let { !it.isString && it.booleanOrNull == true } == true,
                duration = number(raw["duration"]), lrclibId = integer(raw["id"]), raw = raw,
            )
        }

        private val ID_TAG = PyRegex.compile("""(?i)\[(?:ar|al|ti|au|by|re|ve|la|id|length|offset|tool|#):[^\]]*\]""")

        /** lyrics._text: a string's text with its line ends made LF; "" for anything else. */
        internal fun text(value: JsonElement?): String =
            if (value is JsonPrimitive && value.isString) value.content.replace("\r\n", "\n").replace("\r", "\n") else ""

        /** lyrics._float: a JSON number (never a bool) as a float. */
        internal fun number(value: JsonElement?): Double? =
            if (value is JsonPrimitive && !value.isString && value.booleanOrNull == null) value.doubleOrNull else null

        /** lyrics._int: a JSON integer (never a bool). */
        internal fun integer(value: JsonElement?): Long? =
            if (value is JsonPrimitive && !value.isString && value.booleanOrNull == null) value.longOrNull else null

        private fun withoutIdTags(plain: String): String =
            plain.split("\n").filter { PyRe.fullmatch(ID_TAG, Py.strip(it)) == null }.joinToString("\n").trim('\n')

        /** lyrics.synced_lines: LRC text's timed lines as (seconds, text), in time order: library.internal.LyricsFiles',
         * the one reading of LRC's stamps (any Unicode decimal digits, a minute of any length, as Python's `\d`,
         * `int()` and `float()` read them). */
        fun syncedLines(synced: String): List<Pair<Double, String>> = LyricsFiles.syncedLines(synced)

        /** lyrics.plain_from_synced: plain lyrics from LRC text; an empty timed line a break between stanzas. */
        fun plainFromSynced(synced: String): String = LyricsFiles.plainFromSynced(synced)
    }
}

/** lyrics.lyrics_from_json: stored lyrics read back (a bare LRCLIB record read as one); null when none is stored.
 * [IllegalArgumentException] for a value that is no JSON object, as Python's TypeError. */
fun lyricsFromJson(text: String?): Lyrics? {
    if (text == null || Py.strip(text).isEmpty()) return null
    val value = Json.parseToJsonElement(text)
    if (value is JsonNull) return null
    val obj = value as? JsonObject ?: throw IllegalArgumentException("stored lyrics must be a JSON object")
    if ("raw" !in obj || "plain" !in obj) return Lyrics.fromRecord(obj)
    fun str(name: String) = (obj[name] as? JsonPrimitive)?.takeIf { it.isString }?.content
    return Lyrics(
        plain = str("plain") ?: "", synced = str("synced"),
        instrumental = (obj["instrumental"] as? JsonPrimitive)?.let { !it.isString && it.booleanOrNull == true } == true,
        duration = Lyrics.number(obj["duration"]), lrclibId = Lyrics.integer(obj["lrclib_id"]),
        raw = obj["raw"] as? JsonObject ?: JsonObject(emptyMap()),
        provider = str("provider")?.takeIf { it.isNotEmpty() } ?: Lyrics.PROVIDER,
        url = str("url")?.takeIf { it.isNotEmpty() },
    )
}

/** lyrics.song_lyrics: a song's stored lyrics; null when there are none, or no such song. */
fun songLyrics(db: Db, songId: Long): Lyrics? = lyricsFromJson(Songs.byId(db, songId)?.lyricsJson)
