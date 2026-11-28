package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Duration
import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * yt-dlp out of date on the phone (the phone-youtube design's §7, the phone's alone: the computer's runner counts an
 * extraction error against the video): two runs classified `outdated` ([ExtractorOutdated]) on two different videos
 * within 24 hours set kv [KEY] `{version, at, reason}` for the app's yt-dlp version; the automatic pass then stops
 * until that version changes or [CLEARED_AFTER] passes ([state]); asked-now jobs still run, the audio stage warning
 * first (their words server.jobs' Outcomes.outdated). A pass-over ([PassedOver]) or any other error never notes one. The videos seen are kv [HITS]
 * (`[{video, version, at}]`, the last 24 hours'); both are the phone's own (OwnRecords), never synced. A version
 * unknown (null) notes nothing.
 */
object Outdated {
    const val KEY = "youtube-outdated"
    const val HITS = "youtube-outdated:hits"
    val CLEARED_AFTER: Duration = Duration.ofDays(7)
    private val WITHIN: Duration = Duration.ofHours(24)

    /** A run of [videoId] (or a search's target) yt-dlp [version] couldn't read, at [now]; true when this sets the state
     * (a second video within 24 hours, the state not set already for this version): the caller's one alert. */
    fun note(db: Db, version: String?, videoId: String, reason: String, now: Instant): Boolean {
        if (version == null) return false
        val at = stamp(now)
        val since = stamp(now.minus(WITHIN))
        val hits = hits(db).filter { it.third >= since && it.second == version && it.first != videoId } +
            Triple(videoId, version, at)
        db.kvSet(HITS, JsonArray(hits.map { (video, v, t) ->
            JsonObject(linkedMapOf("video" to JsonPrimitive(video), "version" to JsonPrimitive(v), "at" to JsonPrimitive(t)))
        }).toString())
        if (hits.map { it.first }.toSet().size < 2 || state(db, version, now) != null) return false
        db.kvSet(KEY, JsonObject(linkedMapOf("version" to JsonPrimitive(version), "at" to JsonPrimitive(at),
                                             "reason" to JsonPrimitive(reason))).toString())
        return true
    }

    /** The reason yt-dlp [version] is out of date at [now], or null: set for this very version, within 7 days. */
    fun state(db: Db, version: String?, now: Instant): String? {
        if (version == null) return null
        val o = db.kvGet(KEY)?.let { runCatching { PyJson.loads(it) }.getOrNull() } as? JsonObject ?: return null
        fun text(name: String) = (o[name] as? JsonPrimitive)?.takeIf { it.isString }?.content
        if (text("version") != version) return null
        val at = text("at")?.let { runCatching { Instant.parse(it) }.getOrNull() } ?: return null
        if (!now.isBefore(at.plus(CLEARED_AFTER))) return null
        return text("reason").orEmpty()
    }

    private fun hits(db: Db): List<Triple<String, String, String>> = db.kvGet(HITS)?.let { text ->
        (runCatching { PyJson.loads(text) }.getOrNull() as? JsonArray)?.mapNotNull { e ->
            val o = e as? JsonObject ?: return@mapNotNull null
            fun text(name: String) = (o[name] as? JsonPrimitive)?.takeIf { it.isString }?.content
            Triple(text("video") ?: return@mapNotNull null, text("version") ?: return@mapNotNull null,
                   text("at") ?: return@mapNotNull null)
        }
    }.orEmpty()

    private fun stamp(at: Instant): String = at.truncatedTo(ChronoUnit.SECONDS).toString()
}
