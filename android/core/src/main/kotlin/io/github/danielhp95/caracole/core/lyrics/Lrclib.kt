package io.github.danielhp95.caracole.core.lyrics

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.http.Client
import io.github.danielhp95.caracole.core.http.HttpRules
import io.github.danielhp95.caracole.core.http.LrclibParseError
import io.github.danielhp95.caracole.core.http.Response
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.PassStats
import io.github.danielhp95.caracole.core.library.Passes
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.library.internal.LibraryFiles
import io.github.danielhp95.caracole.core.library.internal.LyricsFiles
import io.github.danielhp95.caracole.core.library.internal.Rekey
import io.github.danielhp95.caracole.core.lyrics.internal.PyValues
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import java.io.File
import java.io.IOException
import java.nio.file.Files
import java.time.Duration
import java.time.Instant

/** lyrics.LyricsStats: what one `fetch_pending_lyrics` pass did (`tried`, `errors`, `budgetExhausted` and `failures`
 * as every pass counts them, Passes'), and what LRCLIB answered. */
class LyricsStats(var found: Int = 0, var missing: Int = 0, var instrumental: Int = 0) : PassStats()

/** lyrics.LyricsResult: a lookup's outcome, "found", "missing" or "instrumental"; [lyrics] for found and
 * instrumental songs. */
data class LyricsResult(val status: String, val lyrics: Lyrics?)

/**
 * lyrics.py on the phone: LRCLIB's lyrics for a lookup's song.
 *
 * [fetchLyrics] asks `/api/get` for the song's exact signature (the first artist, the cleaned title, the album and
 * the length in whole seconds, `round()`ed half to even), then on a miss `/api/search` once (the title's Han text
 * joined where punctuation splits it, [searchTitle]) and chooses among its records locally ([pickCandidate], by
 * [fits]' bands). [fetchPendingLyrics] is the pass for the lookup's song: its lyrics written as `lyrics.txt` and
 * `lyrics.lrc` ([writeLyrics]) and stored as `lyrics_json` (Lyrics.toJson), every outcome stamping `lyrics_at`; a miss
 * asked again after 30 days, past the cache.
 *
 * Errors are never misses: whatever the client raises, and any answer that isn't the JSON LRCLIB documents
 * ([LrclibParseError]), leaves the song pending (Passes' ladder), a cached one asked for once more past the cache
 * first (HttpRules.readOnceMore); LRCLIB's 503 is PoliteClient's to ask once more after its Retry-After. The songs an
 * error left are remembered for Megalobiz and AZLyrics (kv `lyrics:failed:`, [FAILED]) until LRCLIB answers about
 * them. tests/conformance/vectors/sites/lrclib.jsonl and lookup/lrclib.jsonl hold Python's answers.
 */
object Lrclib {
    const val PROVIDER = Lyrics.PROVIDER
    const val API = "https://lrclib.net/api"

    /** + song id: when LRCLIB's last lookup of the song failed, kept until LRCLIB answers about it. */
    const val FAILED = "lyrics:failed:"
    val RECHECK_MISSING_AFTER: Duration = Duration.ofDays(30)

    /** /api/get answers a miss with 404 TrackNotFound. */
    private val GET_ACCEPT = setOf(200, 404)
    private val SEARCH_ACCEPT = setOf(200)
    private const val TEXT_MATCH = 85.0 // rapidfuzz ratio, for titles and for artists
    private const val CLOSE_S = 2.0 // the tolerance LRCLIB itself applies on /api/get
    private const val TEXT_MATCH_S = 10.0 // a text match is accepted this far off; beyond it, keys must be equal

    private const val HAN = "[\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff\\U00020000-\\U0002ebef]"
    private val HAN_GAP by lazy { PyRegex.compile("(?<=$HAN)[\\W_]+(?=$HAN)") }

    /** lyrics._OTHER_VERSION: words of a title that make it another kind of version than the song's. */
    private val OTHER_VERSION by lazy {
        PyRegex.compile("\\b(cover|karaoke|instrumental|acapella|a cappella|nightcore|sped up|slowed|8d|vocals?|remix)\\b")
    }

    // --- choosing a record ------------------------------------------------------------------------------------------

    /** lyrics._key: slug_key, or the name folded and stripped where slug_key leaves nothing ("!!!", "?"). */
    private fun key(name: String): String = Normalize.slugKey(name).ifEmpty { Py.strip(Normalize.fold(name)) }

    private fun artistMatches(want: String, got: String): Boolean =
        want.isNotEmpty() && got.isNotEmpty() && (Fuzz.ratio(want, got) >= TEXT_MATCH || want in got || got in want)

    /** lyrics.another_version: whether [got]'s title names a kind of version (a cover, a karaoke track) the song's
     * title [want] doesn't. */
    fun anotherVersion(want: String, got: String): Boolean {
        val named = PyRe.findall(OTHER_VERSION, PyUnicode.lower(Normalize.fold(want))).toSet()
        return PyRe.findall(OTHER_VERSION, PyUnicode.lower(Normalize.fold(got))).any { it !in named }
    }

    /**
     * lyrics.fits: whether a record ([gotArtist], [gotTitle], [gotDuration]) is the song, by [pickCandidate]'s rules,
     * which Megalobiz's and AZLyrics' pickers keep too: null when it isn't; else its band, 0 within ±2 s of the song's
     * length, 1 within ±10 s, 2 beyond (only for a record whose title and artist keys equal the song's), and how far
     * off it is (0, 0.0 when the song's length isn't known).
     */
    fun fits(artist: String, title: String, durationS: Double?, gotArtist: String, gotTitle: String,
             gotDuration: Double?): Pair<Int, Double>? {
        val wantTitle = key(Normalize.cleanTitle(title))
        val wantArtist = key(artist)
        val gotT = key(Normalize.cleanTitle(gotTitle))
        val gotA = key(gotArtist)
        if (Fuzz.ratio(wantTitle, gotT) < TEXT_MATCH || !artistMatches(wantArtist, gotA)) return null
        if (durationS == null) return 0 to 0.0
        val delta = if (gotDuration != null) Math.abs(gotDuration - durationS) else Double.POSITIVE_INFINITY
        val band = if (delta <= CLOSE_S) 0 else if (delta <= TEXT_MATCH_S) 1 else 2
        if (band == 2 && (gotT != wantTitle || gotA != wantArtist)) return null
        return band to delta
    }

    /** lyrics._kind: how useful a record is: 0 synced, 1 plain only, 2 instrumental, null empty. */
    private fun kind(lyrics: Lyrics): Int? = when {
        !lyrics.synced.isNullOrEmpty() -> 0
        lyrics.hasLyrics -> 1
        lyrics.instrumental -> 2
        else -> null
    }

    /**
     * lyrics.pick_candidate: the `/api/search` record for a song, or null when none fits ([fits], lyrics or an
     * instrumental flag): with the song's length, its band first, then synced before plain before instrumental, then
     * the smallest difference; without it, synced first; ties keep LRCLIB's order. Anything not an object is passed
     * over.
     */
    fun pickCandidate(cands: List<JsonElement>, artist: String, title: String, durationS: Double?): JsonObject? {
        var best: JsonObject? = null
        var bestRank: List<Double>? = null
        for ((order, cand) in cands.withIndex()) {
            if (cand !is JsonObject) continue
            val lyrics = Lyrics.fromRecord(cand)
            val kind = kind(lyrics) ?: continue
            val named = if (PyValues.truthy(cand["trackName"])) cand["trackName"] else cand["name"]
            val (band, delta) = fits(artist, title, durationS, Lyrics.text(cand["artistName"]), Lyrics.text(named),
                                     lyrics.duration) ?: continue
            val rank = if (durationS == null) listOf(kind.toDouble(), order.toDouble())
                       else listOf(band.toDouble(), kind.toDouble(), delta, order.toDouble())
            if (bestRank == null || less(rank, bestRank)) {
                best = cand
                bestRank = rank
            }
        }
        return best
    }

    /** Python's `<` of two tuples of the same length: at the first place they differ (`!=`, so a NaN always does),
     * which is less. */
    internal fun less(a: List<Double>, b: List<Double>): Boolean {
        for (i in a.indices) if (!(a[i] == b[i])) return a[i] < b[i]
        return false
    }

    /** lyrics._search_title: the title `/api/search` is given, its Han text split by punctuation joined (a wanted line
     * may write 斑马，斑马 where LRCLIB lists 斑马斑马). */
    fun searchTitle(track: String): String = PyRe.sub(HAN_GAP, track) { "" }

    // --- reading LRCLIB's answers -----------------------------------------------------------------------------------

    /** lyrics._json: the JSON an answer holds, an object ([wantObject]) or a list; [LrclibParseError] otherwise. */
    private fun json(resp: Response, wantObject: Boolean): JsonElement {
        val found = try {
            resp.json()
        } catch (e: IllegalArgumentException) { // json.loads' ValueError (UnicodeDecodeError too), or nested too deep
            throw LrclibParseError(PROVIDER, resp.url, resp.status, "unreadable response: ${e.message}")
        }
        if (if (wantObject) found !is JsonObject else found !is JsonArray) {
            throw LrclibParseError(PROVIDER, resp.url, resp.status, "expected a JSON ${if (wantObject) "object" else "list"}")
        }
        return found
    }

    /** lyrics._get_record: the record `/api/get` answered; null for its miss, a 404 (whatever its body). */
    fun getRecord(resp: Response): JsonObject? = if (resp.status == 200) json(resp, wantObject = true) as JsonObject else null

    /** `/api/search`'s records: `_json(resp, list)`. */
    fun searchRecords(resp: Response): JsonArray = json(resp, wantObject = false) as JsonArray

    private fun outcome(lyrics: Lyrics): LyricsResult? = when {
        lyrics.hasLyrics -> LyricsResult("found", lyrics)
        lyrics.instrumental -> LyricsResult("instrumental", lyrics)
        else -> null
    }

    /**
     * lyrics.fetch_lyrics: `/api/get` first, then `/api/search`. A 404 from the first, or a record without lyrics,
     * falls back to the search and [pickCandidate]; only an empty or non-matching search is "missing". Errors the
     * client raises and unreadable answers ([LrclibParseError]) propagate: never a miss. [cache] goes to the first
     * request of each endpoint; the one more ask of an answer that won't read goes past the cache.
     */
    fun fetchLyrics(client: Client, artist: String, title: String, album: String?, durationS: Double?,
                    cache: Boolean = true): LyricsResult {
        val track = Normalize.cleanTitle(title)
        val params = mutableListOf("artist_name" to artist, "track_name" to track)
        if (!album.isNullOrEmpty()) params += "album_name" to album
        if (durationS != null) params += "duration" to PyFormat.roundHalfEven(durationS).toString()
        val getUrl = "$API/get"
        val resp = client.get(getUrl, params = params, accept = GET_ACCEPT, cache = cache)
        val found = HttpRules.readOnceMore(client, resp, getUrl, { it is LrclibParseError }, accept = GET_ACCEPT,
                                           params = params) { getRecord(it) }
        if (found != null) outcome(Lyrics.fromRecord(found))?.let { return it }

        val searchUrl = "$API/search"
        val query = listOf("track_name" to searchTitle(track), "artist_name" to artist)
        val answered = client.get(searchUrl, params = query, accept = SEARCH_ACCEPT, cache = cache)
        val cands = HttpRules.readOnceMore(client, answered, searchUrl, { it is LrclibParseError },
                                           accept = SEARCH_ACCEPT, params = query) { searchRecords(it) }
        val best = pickCandidate(cands, artist, title, durationS)
        return best?.let { outcome(Lyrics.fromRecord(it)) } ?: LyricsResult("missing", null)
    }

    /**
     * lyrics.write_lyrics: `lyrics.txt` and, for timed lyrics, `lyrics.lrc` in the song's folder [dir], each ending in
     * a newline and written atomically (Kept.writeAtomic, which makes the folder); a file these lyrics have no text
     * for is removed, so a stale `lyrics.lrc` never outlives a lookup. The files written; an instrumental writes
     * nothing.
     */
    fun writeLyrics(dir: File, lyrics: Lyrics): List<File> {
        val written = ArrayList<File>()
        for ((name, data) in LyricsFiles.files(lyrics.plain, lyrics.synced)) {
            val path = File(dir, name)
            if (data != null) {
                Kept.writeAtomic(path.toPath(), data)
                written += path
            } else {
                // Path.unlink(missing_ok=True): a link goes, never what it points to; a folder there is an error.
                if (LibraryFiles.entry(path.toPath())?.isDirectory == true) throw IOException("$path: is a folder")
                Files.deleteIfExists(path.toPath())
            }
        }
        return written
    }

    // --- the pass ---------------------------------------------------------------------------------------------------

    /** songs.Song.duration_s: the song's length in seconds; none for none, or 0. */
    internal fun durationS(song: SongRow): Double? = song.durationMs?.takeIf { it != 0L }?.let { it.toDouble() / 1000.0 }

    /** songs.list_songs: the songs, newest first, their keys made current first (songs.ensure_current_keys). */
    internal fun songs(db: Db, now: Instant): List<SongRow> {
        Rekey.ensure(db, Stamps.of(now))
        return Songs.list(db)
    }

    /** lyrics._songs_to_look_up: songs never looked up, newest first, then misses older than [recheckAfter]. */
    private fun songsToLookUp(db: Db, now: Instant, recheckAfter: Duration): List<SongRow> {
        val pending = ArrayList<SongRow>()
        val due = ArrayList<SongRow>()
        for (song in songs(db, now)) {
            if (song.status == "ignored") continue
            if (song.lyricsStatus == "pending") {
                pending += song
            } else if (song.lyricsStatus == "missing" && PyValues.before(song.lyricsAt, now, recheckAfter)) {
                due += song
            }
        }
        return pending + due
    }

    /**
     * lyrics.fetch_pending_lyrics for [only]'s songs (a lookup's one): a song never looked up, or a miss older than
     * [recheckMissingAfter] (asked past the cache: its cached answer is the old miss), not ignored. [durations]: a
     * length in seconds by song id, for a song with none of its own. Found lyrics written ([writeLyrics]) and stored;
     * every outcome stamps `lyrics_at` [now]. Errors are never misses (Passes' ladder); the songs an error left are
     * remembered in kv [FAILED] until LRCLIB answers about them.
     */
    fun fetchPendingLyrics(db: Db, client: Client, lib: LibraryStore, now: Instant, only: Set<Long>,
                           durations: Map<Long, Double>? = null,
                           recheckMissingAfter: Duration = RECHECK_MISSING_AFTER): LyricsStats {
        val stats = LyricsStats()
        val stamp = Stamps.of(now)
        val songs = songsToLookUp(db, now, recheckMissingAfter).asSequence().filter { it.id in only }
        val asked = Passes.eachSong(songs, stats, "LRCLIB") { song ->
            fetchLyrics(client, song.artists[0], song.title, song.album, durationS(song) ?: durations?.get(song.id),
                        cache = song.lyricsStatus != "missing")
        }
        for ((song, result) in asked) {
            record(db, lib, song, result, stamp)
            db.kvDelete("$FAILED${song.id}")
            when (result.status) {
                "found" -> stats.found++
                "instrumental" -> stats.instrumental++
                else -> stats.missing++
            }
        }
        for ((song, _) in stats.failures) db.kvSet("$FAILED${song.id}", stamp)
        return stats
    }

    /** lyrics._record: one lookup's outcome stored, the lyric files first, so a failed write leaves it pending. */
    private fun record(db: Db, lib: LibraryStore, song: SongRow, result: LyricsResult, stamp: String) {
        val lyrics = result.lyrics
        if (lyrics == null) {
            Versions.updateSong(db, song.id, linkedMapOf("lyrics_status" to result.status, "lyrics_at" to stamp), stamp)
            return
        }
        writeLyrics(lib.folderOf(song), lyrics)
        Versions.updateSong(db, song.id, linkedMapOf("lyrics_status" to result.status, "lyrics_json" to lyrics.toJson(),
                                                     "lyrics_at" to stamp), stamp)
    }
}
