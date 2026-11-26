package io.github.danielhp95.caracole.core.lyrics

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.LyricsPick
import io.github.danielhp95.caracole.core.library.LyricsRecord
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.internal.LyricsFiles
import io.github.danielhp95.caracole.core.lyrics.internal.PyValues
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.longOrNull
import java.time.Duration
import java.time.Instant

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

        /** lyrics._float: a JSON number (never a bool) as a float, as the sites' readers take one (PyValues.number:
         * an int too big for a float Python's OverflowError, an ArithmeticException). */
        internal fun number(value: JsonElement?): Double? = PyValues.number(value)

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

        // --- [lyrics]: the name asked under, the record picked --------------------------------------------------

        /** lyrics.ASKED_MOST: characters of each part of `[lyrics]`' `as` the sites are asked. */
        const val ASKED_MOST = 200
        private const val INVISIBLE = "\u200b\u200e\u200f\ufeff" // wanted.py's: zero-width characters at a name's ends

        /** lyrics._asked_part: a part of `as` as the sites are asked it: NFC, any control character that is no space
         * dropped, its spaces folded into one, no zero-width character at its ends, at most [ASKED_MOST] characters
         * (code points); "" for one of none of these. */
        internal fun askedPart(text: String): String {
            val nfc = PyUnicode.nfc(text)
            val kept = StringBuilder()
            var i = 0
            while (i < nfc.length) {
                val cp = nfc.codePointAt(i)
                if (PyUnicode.isSpace(cp) || PyUnicode.category(cp) != "Cc") kept.appendCodePoint(cp)
                i += Character.charCount(cp)
            }
            val name = Py.strip(PyText.strip(Py.split(kept.toString()).joinToString(" "), INVISIBLE))
            return Py.strip(Py.slice(name, 0, ASKED_MOST))
        }

        private fun pick(song: SongRow, picks: Map<String, LyricsPick>?): LyricsPick? =
            if (picks.isNullOrEmpty()) null else picks[OverrideUrls.overrideKey(song.display)]

        /** lyrics.asked_as: the artist, title and album the lyrics sites are asked under: the song's `[lyrics]` `as`
         * in [picks] (Overrides.lyrics), cleaned ([askedPart]), with no album; else, or for one that cleans to
         * nothing, the song's own first artist, title and album. */
        fun askedAs(song: SongRow, picks: Map<String, LyricsPick>?): Triple<String, String, String?> {
            val asked = pick(song, picks)?.asked
            if (asked != null) {
                val artist = askedPart(asked.first)
                val title = askedPart(asked.second)
                if (artist.isNotEmpty() && title.isNotEmpty()) return Triple(artist, title, null)
            }
            return Triple(song.artists[0], song.title, song.album)
        }

        /** lyrics.asked_name: "Artist - Title", the name [askedAs] gives when it isn't the song's own (`[lyrics]`'
         * `as`), else null. */
        fun askedName(song: SongRow, picks: Map<String, LyricsPick>?): String? {
            val asked = askedAs(song, picks)
            return if (asked == Triple(song.artists[0], song.title, song.album)) null else "${asked.first} - ${asked.second}"
        }

        /** lyrics.said_under: a lookup's lyrics stage in its words, the name its sites were asked under said once,
         * first, when it isn't the song's own ([askedName]) and a site was asked under it: "under “A - T”: …". */
        fun saidUnder(said: String, name: String?): String = if (name == null) said else "under “$name”: $said"

        /** lyrics.PAGE_NAMED: after AZLyrics' words, for a page `[azlyrics]` names while a `[lyrics]` name holds. */
        const val PAGE_NAMED = " (the page you named)"

        /** lyrics.picked_said: what a lookup says of the record you picked, its site's pass done: kept, gone, or not
         * asked now (within 30 days of its miss, or its site off). */
        fun pickedSaid(record: LyricsRecord, kept: Boolean, gone: Boolean): String {
            val said = "${record.site} ${record.id}"
            return when {
                kept -> "the record you picked: $said"
                gone -> "the record you picked is gone: $said"
                else -> "the record you picked isn't asked now: $said"
            }
        }

        /** lyrics.picked_record: the record you picked for the song (`[lyrics]`' `record`), or null. */
        fun pickedRecord(song: SongRow, picks: Map<String, LyricsPick>?): LyricsRecord? = pick(song, picks)?.record

        /** lyrics.picked_due: whether a song with a picked record is asked for it, by its site alone: while it has no
         * lyrics, pending, or missing (the record gone) for [recheckAfter]; never an ignored song. */
        fun pickedDue(song: SongRow, now: Instant, recheckAfter: Duration): Boolean =
            song.status != "ignored" && (song.lyricsStatus == "pending" ||
                (song.lyricsStatus == "missing" && PyValues.before(song.lyricsAt, now, recheckAfter)))
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
