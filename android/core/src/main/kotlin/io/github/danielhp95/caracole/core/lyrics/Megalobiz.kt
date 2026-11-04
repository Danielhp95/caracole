package io.github.danielhp95.caracole.core.lyrics

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.HttpRules
import io.github.danielhp95.caracole.core.http.MegalobizParseError
import io.github.danielhp95.caracole.core.http.Response
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.PassStats
import io.github.danielhp95.caracole.core.library.Passes
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.library.internal.LyricsFiles
import io.github.danielhp95.caracole.core.lyrics.internal.PyValues
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigInteger
import java.time.Duration
import java.time.Instant

/** megalobiz_fetch.MegalobizStats: `tried`, `errors`, `budgetExhausted` and `failures` as every pass counts them;
 * [found], songs that had no lyrics and now have Megalobiz's; [timed], songs whose plain lyrics are now its timed
 * ones; [missing], songs it has nothing that fits for. */
class MegalobizStats(var found: Int = 0, var timed: Int = 0, var missing: Int = 0) : PassStats()

/**
 * megalobiz.py and megalobiz_fetch.py on the phone: Megalobiz's public API, timed lyrics for a song LRCLIB left
 * without them, and its pass for a lookup's song.
 *
 * - `/search?title=&artist=&duration=&limit=` answers `{query, count, results}` ([parseSearch]); the song takes the
 *   result that is it ([pickResult], [Lrclib.fits]' rules, credited to someone, no other kind of version), then that
 *   record, `/lrc/{id}` ([parseLrc]: its `lrc` text, else made from its `lines`, each `[mm:ss.xx]` as Python's
 *   `f'{ms // 60000:02d}:{ms % 60000 / 1000:05.2f}'` writes it), 404 for one gone: two requests at most.
 * - The songs asked ([songsToAsk]): those LRCLIB missed, failed on (kv `lyrics:failed:`) or has plain lyrics alone
 *   for, none Megalobiz answered a miss about in the last 30 days (kv `megalobiz:checked:`, [CHECKED]).
 * - Found: the song's lyrics are Megalobiz's, written as LRCLIB's are and stored with their provider and their page,
 *   which caracole links back to wherever it credits them. A miss: [CHECKED] now, the song as it was. An error: never
 *   a miss; a song LRCLIB missed goes back to pending.
 *
 * Its per-day limit is the lookup's client's (Pace.withinTheDay). tests/conformance/vectors/sites/megalobiz.jsonl
 * and lookup/megalobiz.jsonl hold Python's answers.
 */
object Megalobiz {
    const val PROVIDER = "megalobiz"
    const val API = "https://api.megalobiz.com/api/public/v1"
    const val SEARCH = "$API/search"

    /** Where every record's page is, which caracole links back to. */
    const val SITE = "https://megalobiz.com/"
    const val LIMIT = 10

    /** + song id: when Megalobiz last answered a miss about the song. */
    const val CHECKED = "megalobiz:checked:"
    val RECHECK_AFTER: Duration = Duration.ofDays(30)
    private val LRC_ACCEPT = setOf(200, 404)

    private val STAMPED by lazy { PyRegex.compile("(?m)^\\s*\\[\\d+:\\d{2}(?:\\.\\d+)?\\]") }

    /** megalobiz.Result: one result of a search, its length in seconds (null when not given) and its page. */
    data class Result(val id: BigInteger, val title: String, val artist: String, val duration: Double?, val url: String)

    /** megalobiz.Lrc: a record's timed lyrics, [lrc] its LRC text ("" for a record with no timed line). */
    data class Lrc(val id: BigInteger, val title: String, val artist: String, val duration: Double?, val url: String,
                   val lrc: String)

    /** megalobiz.search_params: the cleaned title, the artist as written, the length in whole seconds when known
     * (`round()`, half to even), the limit; each value as httpx writes it. */
    fun searchParams(artist: String, title: String, durationS: Double?): List<Pair<String, String>> {
        val params = mutableListOf("title" to Normalize.cleanTitle(title), "artist" to artist)
        if (durationS != null) params += "duration" to PyFormat.roundHalfEven(durationS).toString()
        params += "limit" to LIMIT.toString()
        return params
    }

    /** megalobiz.lrc_url: a record's address under the API. */
    fun lrcUrl(id: BigInteger): String = "$API/lrc/$id"

    private fun error(resp: Response, words: String) = MegalobizParseError(PROVIDER, resp.url, resp.status, words)

    private fun obj(resp: Response): JsonObject {
        val found = try {
            resp.json()
        } catch (e: IllegalArgumentException) { // json.loads' ValueError (UnicodeDecodeError too), or nested too deep
            throw error(resp, "unreadable response: ${e.message}")
        }
        return found as? JsonObject ?: throw error(resp, "expected a JSON object")
    }

    private class Record(val id: BigInteger, val title: String, val artist: String, val duration: Double?, val url: String)

    /** megalobiz._record: a record's id, names, length and page, as a search's result or `/lrc/` gives them. */
    private fun record(resp: Response, data: JsonObject): Record {
        val id = PyValues.bigInt(data["id"]) ?: throw error(resp, "a record without a numeric id: ${PyValues.repr(data["id"])}")
        val url = PyValues.string(data["url"])
        if (url == null || !url.startsWith(SITE)) {
            throw error(resp, "record $id's page isn't on $SITE: ${PyValues.repr(data["url"])}")
        }
        return Record(id, PyValues.string(data["title"]) ?: "", PyValues.string(data["artist"]) ?: "",
                      PyValues.number(data["duration"]), url)
    }

    /** megalobiz.parse_search: a search's results, in its order. */
    fun parseSearch(resp: Response): List<Result> {
        val data = obj(resp)
        val found = data["results"] as? JsonArray ?: throw error(resp, "a search without a list of results")
        return found.map { item ->
            val r = record(resp, item as? JsonObject ?: throw error(resp, "a result that isn't an object"))
            Result(r.id, r.title, r.artist, r.duration, r.url)
        }
    }

    /** `f'{n:02d}'`: at least two wide, zeros after the sign. */
    private fun twoDigits(n: BigInteger): String {
        val digits = n.abs().toString()
        val sign = if (n.signum() < 0) "-" else ""
        return sign + "0".repeat(maxOf(0, 2 - sign.length - digits.length)) + digits
    }

    private val MINUTE = BigInteger.valueOf(60_000)

    /** megalobiz._from_lines: LRC text from a record's lines, `[mm:ss.xx]` before each line's text; a line with no
     * int `time_ms` (a bool is one, as `isinstance(…, int)` reads it) passed over. */
    private fun fromLines(lines: JsonArray): String {
        val out = ArrayList<String>()
        for (line in lines) {
            if (line !is JsonObject) continue
            val ms = PyValues.intOrBool(line["time_ms"]) ?: continue
            val rest = ms.mod(MINUTE) // Python's %: never negative for a positive divisor
            val minutes = ms.subtract(rest).divide(MINUTE) // and its //: the floor
            val text = PyValues.string(line["text"]) ?: ""
            out += "[" + twoDigits(minutes) + ":" + PyFormat.fixed(rest.toDouble() / 1000.0, 2, width = 5, zero = true) +
                "]" + text
        }
        return out.joinToString("\n")
    }

    /** megalobiz.parse_lrc: a record's timed lyrics, its `lrc` text, else made from its `lines`; "" when it has no
     * timed line. */
    fun parseLrc(resp: Response): Lrc {
        val data = obj(resp)
        val text = PyValues.string(data["lrc"])
        val lines = data["lines"] as? JsonArray
        if (text == null && lines == null) throw error(resp, "a record with neither lrc text nor lines")
        var lrc = text?.replace("\r\n", "\n") ?: ""
        if (PyRe.search(STAMPED, lrc) == null) lrc = lines?.let(::fromLines) ?: ""
        val r = record(resp, data)
        return Lrc(r.id, r.title, r.artist, r.duration, r.url, if (PyRe.search(STAMPED, lrc) != null) lrc else "")
    }

    /** megalobiz.pick_result: the result that is the song, or null: [Lrclib.fits]' rules (the closest length first
     * within ±2 s, then ±10 s, beyond that only the same names), credited to someone, no other kind of version than
     * the song ([Lrclib.anotherVersion]); without the song's length, the first that fits. */
    fun pickResult(results: List<Result>, artist: String, title: String, durationS: Double?): Result? {
        var best: Result? = null
        var bestRank: List<Double>? = null
        for ((order, result) in results.withIndex()) {
            if (Py.strip(result.artist).isEmpty() || Lrclib.anotherVersion(title, result.title)) continue
            val (band, delta) = Lrclib.fits(artist, title, durationS, result.artist, result.title, result.duration)
                ?: continue
            val rank = listOf(band.toDouble(), delta, order.toDouble())
            if (bestRank == null || Lrclib.less(rank, bestRank)) {
                best = result
                bestRank = rank
            }
        }
        return best
    }

    /** megalobiz.record_json: what caracole stores of a record, as Lyrics.raw: its names, length and page, never its
     * lyrics twice. */
    fun recordJson(lrc: Lrc): JsonObject = JsonObject(linkedMapOf(
        "id" to JsonPrimitive(lrc.id), "title" to JsonPrimitive(lrc.title), "artist" to JsonPrimitive(lrc.artist),
        "duration" to (lrc.duration?.let(PyJson::float) ?: JsonNull), "url" to JsonPrimitive(lrc.url),
    ))

    // --- the pass ---------------------------------------------------------------------------------------------------

    /** megalobiz_fetch._lyrics: a song's stored lyrics; none for lyrics that can't be read. */
    internal fun lyricsOf(song: SongRow): Lyrics? = try {
        lyricsFromJson(song.lyricsJson)
    } catch (_: IllegalArgumentException) {
        null
    }

    /** megalobiz_fetch._wants: whether LRCLIB left the song for Megalobiz: missing, failed on and pending, or plain
     * lyrics not Megalobiz's own. */
    private fun wants(db: Db, song: SongRow): Boolean = when (song.lyricsStatus) {
        "missing" -> true
        "pending" -> db.kvGet("${Lrclib.FAILED}${song.id}") != null
        "found" -> lyricsOf(song).let { it != null && it.provider != PROVIDER && it.hasLyrics && it.synced.isNullOrEmpty() }
        else -> false
    }

    /** megalobiz_fetch.songs_to_ask: the songs LRCLIB left for Megalobiz that it hasn't answered a miss about since
     * [recheckAfter] (of [only]'s ids, when given), those with no lyrics first, then those with plain ones, newest
     * first within each. */
    fun songsToAsk(db: Db, now: Instant, recheckAfter: Duration = RECHECK_AFTER, only: Set<Long>? = null): List<SongRow> {
        val none = ArrayList<SongRow>()
        val plain = ArrayList<SongRow>()
        for (song in Lrclib.songs(db, now)) {
            if (song.status == "ignored" || (only != null && song.id !in only) || !wants(db, song)) continue
            val checked = db.kvGet("$CHECKED${song.id}")
            if (checked != null && !PyValues.before(checked, now, recheckAfter)) continue
            (if (song.lyricsStatus == "found") plain else none) += song
        }
        return none + plain
    }

    /** megalobiz_fetch.fetch_megalobiz: a song's timed lyrics, or null when Megalobiz has none that fit: the search,
     * then the record of the result that is the song. Errors propagate (an answer that won't read asked for once more
     * first, past the cache); [cache] goes to each first request. */
    fun fetchMegalobiz(client: Client, artist: String, title: String, durationS: Double?, cache: Boolean = true): Lyrics? {
        val params = searchParams(artist, title, durationS)
        val resp = client.get(SEARCH, params = params, cache = cache)
        val results = HttpRules.readOnceMore(client, resp, SEARCH, { it is MegalobizParseError }, params = params) {
            parseSearch(it)
        }
        val found = pickResult(results, artist, title, durationS) ?: return null
        val url = lrcUrl(found.id)
        val answered = client.get(url, accept = LRC_ACCEPT, cache = cache)
        if (answered.status == 404) return null
        val lrc = HttpRules.readOnceMore(client, answered, url, { it is MegalobizParseError }, accept = LRC_ACCEPT) {
            parseLrc(it)
        }
        if (lrc.lrc.isEmpty()) return null
        return Lyrics(plain = LyricsFiles.plainFromSynced(lrc.lrc), synced = lrc.lrc, instrumental = false,
                      duration = lrc.duration, lrclibId = null, raw = recordJson(lrc), provider = PROVIDER, url = lrc.url)
    }

    /**
     * megalobiz_fetch.megalobiz_lyrics for [only]'s songs (a lookup's one, [songsToAsk]): its length its own, else
     * [durations]', else LRCLIB's lyrics'; a miss asked again goes past the cache. Found lyrics written as LRCLIB's
     * and stored with their page (the link back, `Lyrics.url`); info.json is the viewer's, the phone's pages' (M5).
     */
    fun megalobizLyrics(db: Db, client: Client, lib: LibraryStore, now: Instant, only: Set<Long>,
                        durations: Map<Long, Double>? = null, recheckAfter: Duration = RECHECK_AFTER): MegalobizStats {
        val stats = MegalobizStats()
        val stamp = Stamps.of(now)

        fun length(song: SongRow): Double? =
            Lrclib.durationS(song) ?: durations?.get(song.id) ?: lyricsOf(song)?.duration?.takeIf { it != 0.0 }

        val backToPending = { song: SongRow, _: Exception ->
            if (song.lyricsStatus == "missing") { // a song is missing only once every site asked answered a miss
                Versions.updateSong(db, song.id, linkedMapOf("lyrics_status" to "pending", "lyrics_at" to null), stamp)
            }
        }
        val songs = songsToAsk(db, now, recheckAfter, only).asSequence()
        val asked = Passes.eachSong(songs, stats, "Megalobiz", onError = backToPending) { song ->
            val cache = db.kvGet("$CHECKED${song.id}") == null // a miss asked again goes past the cache
            fetchMegalobiz(client, song.artists[0], song.title, length(song), cache)
        }
        for ((song, lyrics) in asked) {
            if (lyrics == null) {
                db.kvSet("$CHECKED${song.id}", stamp)
                stats.missing++
                continue
            }
            Lrclib.writeLyrics(lib.folderOf(song), lyrics)
            Versions.updateSong(db, song.id, linkedMapOf("lyrics_status" to "found", "lyrics_json" to lyrics.toJson(),
                                                         "lyrics_at" to stamp), stamp)
            db.kvDelete("$CHECKED${song.id}")
            db.kvDelete("${Lrclib.FAILED}${song.id}")
            if (song.lyricsStatus == "found") stats.timed++ else stats.found++
        }
        return stats
    }
}
