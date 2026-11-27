package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.lacuerda.internal.pages.PyBits
import io.github.danielhp95.caracole.core.lyrics.internal.PyValues
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.search.IndexFound
import io.github.danielhp95.caracole.core.search.LibraryHit
import io.github.danielhp95.caracole.core.search.SiteArtist
import io.github.danielhp95.caracole.core.search.SearchLimits
import io.github.danielhp95.caracole.core.search.SiteHit
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import java.time.Duration
import java.time.Instant

/**
 * youtube_search.py's gates on the phone: whether a search of YouTube for a query (`gate`), or the metadata of a
 * pasted video (`video_gate`), may be asked for now, with no request, as /api/search's `youtube` says it
 * ([suggestion]); and the failures that pause them ([recordFailure]).
 *
 * A query is its words' key ([queryKey], their names' words in code point order, hyphenated), a pasted video
 * `video_key` + its id ([videoKey]). A search goes none for a query with no word, a sheet already on the screen
 * ([sheetOnScreen]) or YouTube off (the phone's settings' switch, or [gate]'s `routeWhy`, the phone's own reason it
 * can't make a sheet from a video); then the first of: what the search of that key found within `asked_for_days`
 * (kv `youtube-search:<key>`, [searched]: `found`, its video an object, else `none`), `spent` while YouTube cools down
 * or once `searches_per_hour` runs named `youtube-search:…` are in `events` of the last hour ([searchesUsed]),
 * `failed` while its own search or `failures_pause` of them failed within `failed_for_seconds` (kv
 * `youtube-search:failed`, [failed]), else `auto`. A video's gate is the same of its key, `off` with its why where
 * YouTube is off.
 *
 * Every number, state and word is the data's (youtube.json's `search`), never typed here; times are read as
 * stamps.parse reads them and compared as Python compares them. vectors/youtube/gate.jsonl holds it to Python's
 * answers (YouTubeReplay); every count is this side's own.
 */
object SearchGate {
    /** youtube_search.Gate: a search's [state] (`states`), its [key], what it found within the 30 days ([asked]),
     * and why none goes ([why], "" for none). */
    data class Gate(val state: String, val key: String, val asked: JsonObject? = null, val why: String = "")

    private val data: YouTubeData get() = YouTubeData.read()
    private val search: JsonObject get() = data.json.getValue("search") as JsonObject
    private fun text(name: String): String = search.getValue(name).jsonPrimitive.content
    private fun number(name: String): Int = search.getValue(name).jsonPrimitive.int

    /** The provider whose cooldown and switch hold (youtube.py's PROVIDER). */
    private val provider: String get() = data.text("provider", data.json.getValue("answers") as JsonObject)

    /** The states the gates answer, by name: each one the data's `states` (STATES) holds, checked as they are read. */
    private val NAMES: List<String> get() = listOf(FOUND, NONE, AUTO, FAILED, SPENT, OFF)
    private val states: Set<String> by lazy {
        data.texts("states", search).toSet().also { held ->
            check(held.containsAll(NAMES)) { "youtube.json's search states lack ${NAMES - held}" }
        }
    }

    private fun state(name: String): String = name.also { check(it in states) { "youtube.json has no state $it" } }
    private const val FOUND = "found"
    private const val NONE = "none"
    private const val AUTO = "auto"
    private const val FAILED = "failed"
    private const val SPENT = "spent"
    private const val OFF = "off"

    private const val SECOND_US = 1_000_000L
    private const val DAY_US = 86_400L * SECOND_US

    /** query_key: the query's words, in code point order, hyphenated; "" for none. */
    fun queryKey(query: String): String = Normalize.nameWords(query).sortedWith(Py.CODE_POINT_ORDER).joinToString("-")

    /** video_key: a pasted video's key, beside the queries'. */
    fun videoKey(videoId: String): String = text("video_key") + videoId

    /** searched: what the search of [key] found when it was made within the 30 days, as json.loads reads it; null
     * when it wasn't (no record, one that is no object, or one older or of no time). */
    fun searched(db: Db, key: String, now: Instant): JsonObject? {
        if (key.isEmpty()) return null
        val said = db.kvGet(text("kv_prefix") + key)?.let { PyJson.loads(it) } as? JsonObject ?: return null
        return if (before(said["at"], Stamps.micros(now) - number("asked_for_days") * DAY_US)) null else said
    }

    /** _failures: the searches that failed within the hour, by key, each its `at` and `error` as str() reads them. */
    private fun failures(db: Db, now: Instant): LinkedHashMap<String, Pair<String, String>> {
        val out = LinkedHashMap<String, Pair<String, String>>()
        val said = db.kvGet(text("failed_key"))?.let { PyJson.loads(it) } as? JsonObject ?: return out
        val since = Stamps.micros(now) - number("failed_for_seconds") * SECOND_US
        for ((k, v) in said) {
            if (v !is JsonObject || before(v["at"], since)) continue
            val at = v["at"]?.let { PyBits.str(it) } ?: "None"
            val error = v["error"]?.takeIf { PyValues.truthy(it) }?.let { PyBits.str(it) } ?: ""
            out[k] = at to error
        }
        return out
    }

    /** failed: why no search of [key] goes now, its own or `failures_pause` failing within the hour; null for
     * neither. */
    fun failed(db: Db, key: String, now: Instant): String? {
        val failures = failures(db, now)
        failures[key]?.let { return YouTubeData.fillAll(text("own_failed_why"), mapOf("error" to it.second)) }
        if (failures.size >= number("failures_pause")) {
            return YouTubeData.fillAll(text("failures_why"), mapOf("n" to failures.size.toString()))
        }
        return null
    }

    /** record_failure: the search of [key] failed now, saying [error] (its spaces collapsed, `error_chars` kept);
     * failures older than the hour go. */
    fun recordFailure(db: Db, key: String, now: Instant, error: String) {
        val kept = failures(db, now)
        kept[key] = Stamps.of(now) to Py.slice(PyBits.collapsed(error), 0, number("error_chars"))
        db.kvSetJson(text("failed_key"), JsonObject(kept.mapValuesTo(LinkedHashMap()) { (_, v) ->
            JsonObject(linkedMapOf("at" to JsonPrimitive(v.first), "error" to JsonPrimitive(v.second)))
        }))
    }

    /** searches_used: the searches of YouTube made in the last hour, each run named `run`… in `events`. */
    fun searchesUsed(db: Db, now: Instant): Int {
        val since = Stamps.of(now.minus(Duration.ofHours(1)))
        return db.one("SELECT COUNT(DISTINCT run) FROM events WHERE provider = ? AND run LIKE ? AND at >= ?",
                      provider, text("run") + "%", since) { it.long(0) }!!.toInt()
    }

    /**
     * gate: what a search of [query] is now, with no request; null when none is for it: no word, a sheet on the
     * screen already ([onScreen], [sheetOnScreen]'s), YouTube turned off in [cfg], or [routeWhy], the reason this
     * phone makes no sheet from a video (youtube_fetch.route_problem's, the phone's own).
     */
    fun gate(cfg: PhoneConfig, db: Db, query: String, onScreen: Boolean, now: Instant, routeWhy: String? = null): Gate? {
        val key = queryKey(query)
        if (key.isEmpty() || onScreen || !cfg.provider(provider).enabled || routeWhy != null) return null
        return gateOf(db, key, now)
    }

    /** video_gate: what reading a pasted video's metadata is now, as a search's; `off` where YouTube is turned off
     * (`off_why`) or this phone makes no sheet from a video ([routeWhy]). */
    fun videoGate(cfg: PhoneConfig, db: Db, videoId: String, now: Instant, routeWhy: String? = null): Gate {
        val key = videoKey(videoId)
        if (!cfg.provider(provider).enabled) return Gate(state(OFF), key, why = text("off_why"))
        if (routeWhy != null) return Gate(state(OFF), key, why = routeWhy)
        return gateOf(db, key, now)
    }

    private fun gateOf(db: Db, key: String, now: Instant): Gate {
        searched(db, key, now)?.let { return Gate(state(if (it["video"] is JsonObject) FOUND else NONE), key, it) }
        if (Health.isCooling(db, provider, now)) return Gate(state(SPENT), key, why = text("cooling_why"))
        if (searchesUsed(db, now) >= number("searches_per_hour")) {
            return Gate(state(SPENT), key, why = YouTubeData.fillAll(text("spent_why"),
                mapOf("n" to number("searches_per_hour").toString())))
        }
        failed(db, key, now)?.let { return Gate(state(FAILED), key, why = it) }
        return Gate(state(AUTO), key)
    }

    /**
     * suggestion: the gate as /api/search's `youtube` gives it: null, or its `state`, the `query` and its `key`; when
     * found, the `video` (`id`, `title`, `channel`, `duration`, `url`, and `thumb`: where the phone sends its kept
     * thumbnail, `thumb_route`, or null); and `why` when there is one.
     */
    fun suggestion(gate: Gate?, query: String): JsonObject? {
        if (gate == null) return null
        val said = linkedMapOf<String, JsonElement>("state" to JsonPrimitive(gate.state), "query" to JsonPrimitive(query),
            "key" to JsonPrimitive(gate.key))
        val asked = gate.asked
        if (gate.state == state(FOUND) && asked != null) {
            val v = asked.getValue("video") as JsonObject
            fun or(name: String): JsonElement = v[name]?.takeIf { PyValues.truthy(it) } ?: JsonPrimitive("")
            val thumb = if (PyValues.truthy(asked["thumb"])) {
                JsonPrimitive(YouTubeData.fillAll(text("thumb_route"), mapOf("id" to (v["id"]?.let { PyBits.str(it) } ?: "None"))))
            } else JsonNull
            said["video"] = JsonObject(linkedMapOf("id" to (v["id"] ?: JsonNull), "title" to or("title"),
                "channel" to or("channel"), "duration" to (v["duration"] ?: JsonNull), "url" to (v["url"] ?: JsonNull),
                "thumb" to thumb))
        }
        if (gate.why.isNotEmpty()) said["why"] = JsonPrimitive(gate.why)
        return JsonObject(said)
    }

    /**
     * sheet_on_screen: whether a search's answer has a sheet for the query already, or names an artist rather than a
     * song, so that no video is suggested: a song of your library scored `strong` or more not by its artist alone, a
     * song of UG's index or an artist it names whole, an artist LaCuerda's names whole, or a LaCuerda song with chords.
     */
    fun sheetOnScreen(mine: List<LibraryHit>, index: IndexFound, lcArtists: List<SiteArtist>, lcSongs: List<SiteHit>): Boolean {
        val strong = number("strong").toDouble()
        return mine.any { it.score >= strong && it.via != SearchLimits.VIA_ARTIST } ||
            index.songs.any { it.score >= strong } ||
            index.artists.any { it.score >= strong && !it.part } ||
            lcSongs.any { it.score >= strong && !it.sheet.isNullOrEmpty() } ||
            lcArtists.any { it.score >= strong && !it.part }
    }

    /** stamps.before: a stored time older than [cutoff], or missing or unreadable. */
    private fun before(value: JsonElement?, cutoff: Long): Boolean {
        val at = Stamps.parse(value) ?: return true
        return at < cutoff
    }
}
