package io.github.danielhp95.caracole.core.match

import io.github.danielhp95.caracole.core.config.MatchPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.math.BigDecimal

/** match.MatchCandidate: a UG song a match offers, its score (none for a pin's) and the step that found it (as
 * stored: a candidate a song keeps may name none). */
data class MatchCandidate(val artistKey: String, val songKey: String, val score: Double?, val step: String?)

/** match.MatchResult: [decision] one of [Match.DECISIONS] and [step] one of [Match.STEPS] (null when not found);
 * [artistKey] and [songKey] the UG song (for a review, the best candidate); [pinned] a `[pin]`'s tab ids. */
data class MatchResult(val decision: String, val step: String?, val score: Double?, val artistKey: String?,
                       val songKey: String?, val candidates: List<MatchCandidate> = emptyList(),
                       val pinned: List<Long> = emptyList())

/** match.MatchChange: one song in a [Matcher.matchAll] run, as it was, its previous decision, and its match now. */
data class MatchChange(val song: SongRow, val old: String?, val new: MatchResult)

/**
 * match.py on the phone: your songs against the UG index, offline, each answer Python's for the same index and
 * overrides (vectors/match/, tests/test_conformance_match.py: test_match.py's cases and a seeded library).
 *
 * For each song, in order ([matchSong]):
 * 1. the overrides: `[ignore]`, then `[pin]`, then `[match]`;
 * 2. for each of its artists, the UG artist keys it may go by (its `[alias]` first, then its own key and its forms,
 *    the keys that read the same without hyphens, a Spanish article taken off or put on), an exact title accepting at
 *    once, every other title scored by `ratio` (its base key and its variants, a Chinese title's pinyin also without
 *    hyphens);
 * 3. the nearest other artist key at or above `artist_gate` (process.extract with ratio), scored as the lower of the
 *    artist and title scores;
 * 4. names that aren't quite UG's, never an accept: `word_title`, `typo_artist` (OSA distance, one edit for four to
 *    seven letters, two from eight), `catch_all` (UG's `misc-…` shows and performers);
 * 5. the title alone, across every artist, pinyin and a title's parts exactly.
 *
 * The UG songs you rejected are dropped at every step; a review keeps five candidates, the best catch_all and
 * typo_artist among them; a LaCuerda pick leaves a review of other artists' songs alone not found.
 *
 * [matchAll] stores what changed as match_all's `_save` does, through Versions (`updateSong`, `markStale`,
 * `refreshStatus`), in one savepoint; it never undoes a match the fetch made on an artist page (A6) but for your
 * overrides, and an index that isn't complete (no `ug:index:built_at`) undoes nothing the ladder found and saves no
 * miss.
 */
object Matcher {
    /** ug/index.py's BUILT_KEY: a build of the index finished. */
    const val BUILT_KEY = "ug:index:built_at"

    /**
     * match.match_all over [songs] (Python's `songs=`: a lookup's one song, or every song, newest first, as
     * Songs.list gives them), their matches stored unless [dryRun], at [now] (`matched_at` and `updated_at`). One
     * change a song; a kept song's `new` is its stored match.
     */
    fun matchAll(db: Db, overrides: Overrides, policy: MatchPolicy, songs: List<SongRow>,
                 dryRun: Boolean = false, now: String = Stamps.now()): List<MatchChange> {
        val index = IndexView(db)
        val complete = indexState(db) == "complete"
        val changes = ArrayList<MatchChange>()
        val kept = HashSet<Long>()
        for (song in songs) {
            var new = matchSong(song, index, overrides, policy)
            if (keepsStored(song, new, overrides.reject[song.key].orEmpty(), complete)) {
                new = stored(song)
                kept += song.id
            }
            changes += MatchChange(song, song.matchDecision, new)
        }
        if (!dryRun) {
            db.savepoint("match_all") {
                for (c in changes) if (c.song.id !in kept) save(db, c.song, c.new, now)
            }
        }
        return changes
    }

    /** The song's stored candidates that name a UG song (match._stored's), as `songs.match_candidates` holds them. */
    fun candidatesOf(song: SongRow): List<MatchCandidate> = stored(song).candidates

    /** match.match_song: the ladder for one song over [index]. */
    fun matchSong(song: SongRow, index: IndexView, overrides: Overrides, policy: MatchPolicy): MatchResult =
        Ladder.matchSong(song, index, overrides, policy)

    /** ug/index.py's index_state: "empty" (never built), "partial" (a build stopped part-way) or "complete". */
    fun indexState(db: Db): String {
        if (db.one("SELECT 1 FROM ug_index LIMIT 1") { true } == null) return "empty"
        return if (db.kvGet(BUILT_KEY) != null) "complete" else "partial"
    }

    // --- match_all's writes -----------------------------------------------------------------------------------

    /** match._candidate_rows: `songs.match_candidates`; a pin is one row that also lists its tabs. */
    private fun candidateRows(result: MatchResult): List<Map<String, Any?>> {
        if (result.decision == "pinned") {
            return listOf(linkedMapOf("artist_key" to result.artistKey, "song_key" to result.songKey, "score" to null,
                                      "step" to "pin", "tab_ids" to result.pinned))
        }
        return result.candidates.take(Match.MAX_CANDIDATES).map {
            linkedMapOf("artist_key" to it.artistKey, "song_key" to it.songKey, "score" to it.score, "step" to it.step)
        }
    }

    private fun json(value: Any?): JsonElement = when (value) {
        null -> JsonNull
        is String -> JsonPrimitive(value)
        is Long -> JsonPrimitive(value)
        is Double -> PyJson.float(value)
        is List<*> -> JsonArray(value.map(::json))
        is Map<*, *> -> JsonObject(value.entries.associate { (k, v) -> k as String to json(v) })
        else -> error("no JSON for $value")
    }

    /** The song's stored candidates, as Python's `song.match_candidates` (json.loads of the column). */
    private fun storedCandidates(song: SongRow): JsonElement = PyJson.loads(song.matchCandidates)

    private fun rowsOf(song: SongRow): List<JsonElement> = when (val c = storedCandidates(song)) {
        is JsonArray -> c
        is JsonNull -> emptyList()
        is JsonObject -> if (c.isEmpty()) emptyList() else throw IllegalStateException("match_candidates is no list")
        is JsonPrimitive -> if (Python.truthy(c)) throw IllegalStateException("match_candidates is no list")
                            else emptyList()
    }

    /** match._pins_of: the tab ids a stored pin lists. */
    private fun pinsOf(song: SongRow): List<Long> {
        val pin = rowsOf(song).firstOrNull { (it as? JsonObject)?.get("step") == JsonPrimitive("pin") } as? JsonObject
            ?: return emptyList()
        val ids = pin["tab_ids"] as? JsonArray ?: return emptyList()
        return ids.map { Python.int(it) }
    }

    /** match._needs_fetch: a new accept or pin, other keys, other pins. */
    private fun needsFetch(song: SongRow, new: MatchResult): Boolean {
        if ((new.decision == "accept" || new.decision == "pinned") && song.matchDecision != new.decision) return true
        if (song.matchArtistKey != new.artistKey || song.matchSongKey != new.songKey) return true
        return new.decision == "pinned" && pinsOf(song) != new.pinned
    }

    /** match._keeps_stored: your overrides always win; an artist page's match stays unless you rejected that UG
     * song; while the index isn't complete, so does what the ladder found before, and a song never matched stays
     * unmatched. */
    private fun keepsStored(song: SongRow, new: MatchResult, rejected: Set<Pair<String, String>>,
                            complete: Boolean): Boolean {
        if (new.step == "override" || new.step == "pin") return false
        if (song.matchStep == Match.ARTIST_PAGE) {
            return (song.matchArtistKey to song.matchSongKey) !in rejected
        }
        if (complete) return false
        return song.matchStep in Match.LADDER_STEPS || (song.matchStep == null && new.decision == "not_found")
    }

    /** match._stored: the song's match as stored, its candidates those that name a UG song. */
    private fun stored(song: SongRow): MatchResult {
        val cands = rowsOf(song).mapNotNull { row ->
            val c = row as? JsonObject ?: return@mapNotNull null
            val artist = Python.text(c["artist_key"])
            val songKey = Python.text(c["song_key"])
            if (artist.isNullOrEmpty() || songKey.isNullOrEmpty()) return@mapNotNull null
            MatchCandidate(artist, songKey, Python.float(c["score"]), Python.text(c["step"]))
        }
        return MatchResult(song.matchDecision.takeUnless { it.isNullOrEmpty() } ?: "not_found", song.matchStep,
                           song.matchScore, song.matchArtistKey, song.matchSongKey, candidates = cands)
    }

    /** match._save: the song's match columns where any differ (and `ug_dirty` and its UG versions marked stale when
     * the match must be fetched again), then its status for an ignore put in or taken out. */
    private fun save(db: Db, song: SongRow, new: MatchResult, now: String) {
        val rows = candidateRows(new)
        val values = linkedMapOf<String, Any?>(
            "match_decision" to new.decision, "match_step" to new.step, "match_score" to new.score,
            "match_artist_key" to new.artistKey, "match_song_key" to new.songKey, "match_candidates" to rows,
            "review" to (new.decision == "review"),
        )
        val differs = song.matchDecision != new.decision || song.matchStep != new.step ||
            !sameFloat(song.matchScore, new.score) || song.matchArtistKey != new.artistKey ||
            song.matchSongKey != new.songKey || !Python.equal(storedCandidates(song), json(rows)) ||
            song.review != (new.decision == "review")
        if (differs) {
            if (needsFetch(song, new)) {
                values["ug_dirty"] = true
                // The UG versions found so far are the old match's: none competes, or stays a pick, until the new
                // match's pages list it again.
                Versions.markStale(db, song.id, "ug")
            }
            values["matched_at"] = now
            Versions.updateSong(db, song.id, values, now)
        }
        if (new.decision == "ignored" && song.status != "ignored") {
            Versions.updateSong(db, song.id, mapOf("status" to "ignored"), now)
        } else if (new.decision != "ignored" && song.status == "ignored") {
            Versions.refreshStatus(db, song.id, ignored = false, now = now)
        }
    }

    /** Python's `!=` of two floats, None aside. */
    private fun sameFloat(a: Double?, b: Double?): Boolean = if (a == null || b == null) a == b else a == b

    /** What match_all compares and reads of a JSON value as Python holds it after json.loads. */
    private object Python {
        fun truthy(p: JsonPrimitive): Boolean = when {
            p.isString -> p.content.isNotEmpty()
            p.content == "true" -> true
            p.content == "false" -> false
            else -> number(p)?.let { it.signum() != 0 } ?: true
        }

        fun text(e: JsonElement?): String? = (e as? JsonPrimitive)?.takeIf { it.isString }?.content

        /** A stored candidate's score: its number (an integer's or a float's value), else none. */
        fun float(e: JsonElement?): Double? {
            val p = e as? JsonPrimitive ?: return null
            if (p.isString || p is JsonNull) return null
            return when (p.content) {
                "true" -> 1.0
                "false" -> 0.0
                "NaN" -> Double.NaN
                "Infinity" -> Double.POSITIVE_INFINITY
                "-Infinity" -> Double.NEGATIVE_INFINITY
                else -> p.content.toDouble()
            }
        }

        /** int(t) of a pin's stored tab id. */
        fun int(e: JsonElement): Long {
            val p = e as JsonPrimitive
            if (p.isString) return p.content.trim().replace("_", "").toLong()
            return when (p.content) {
                "true" -> 1L
                "false" -> 0L
                else -> number(p)!!.toBigInteger().toLong()
            }
        }

        /** A number's exact value: an integer's, or the double a float literal reads as. */
        private fun number(p: JsonPrimitive): BigDecimal? {
            val text = p.content
            if (text == "NaN" || text.endsWith("Infinity")) return null
            return if (text.any { it == '.' || it == 'e' || it == 'E' }) BigDecimal(text.toDouble()) else BigDecimal(text)
        }

        /** Python's `==` of two JSON values: objects by their members, lists in order, a number by its value (True
         * is 1), a string by its text. */
        fun equal(a: JsonElement, b: JsonElement): Boolean = when {
            a is JsonNull || b is JsonNull -> a is JsonNull && b is JsonNull
            a is JsonObject && b is JsonObject -> a.keys == b.keys && a.all { (k, v) -> equal(v, b.getValue(k)) }
            a is JsonArray && b is JsonArray -> a.size == b.size && a.indices.all { equal(a[it], b[it]) }
            a is JsonPrimitive && b is JsonPrimitive -> when {
                a.isString || b.isString -> a.isString && b.isString && a.content == b.content
                else -> {
                    val x = numeric(a)
                    val y = numeric(b)
                    if (x is BigDecimal && y is BigDecimal) x.compareTo(y) == 0 else x == y
                }
            }
            else -> false
        }

        /** A number or a boolean as Python compares it: its exact value, or a double for NaN and the infinities
         * (NaN equal to nothing). */
        private fun numeric(p: JsonPrimitive): Any = when (p.content) {
            "true" -> BigDecimal.ONE
            "false" -> BigDecimal.ZERO
            "NaN" -> Any()
            "Infinity" -> Double.POSITIVE_INFINITY
            "-Infinity" -> Double.NEGATIVE_INFINITY
            else -> number(p)!!
        }
    }
}
