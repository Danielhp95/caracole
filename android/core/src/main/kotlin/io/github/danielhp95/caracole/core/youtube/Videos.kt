package io.github.danielhp95.caracole.core.youtube

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.lyrics.internal.PyValues
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/** youtube.py's Video: a video as a search lists it or yt-dlp reports it. */
data class Video(
    val id: String,
    val title: String = "",
    val channel: String = "",
    val duration: Double? = null,
    val live: Boolean = false,
    val short: Boolean = false,
) {
    val url: String get() = YouTubeData.read().watchUrl(id)
}

/** youtube.py's ProviderError of an answer yt-dlp gave that can't be read: [message] is its `str()`, Python's. */
class AnswerError(message: String, cause: Throwable? = null) : IllegalStateException(message, cause)

/**
 * yt-dlp's JSON answers read as youtube.py reads them (`parse_search`, `parse_video`), and what a search asks
 * (`search_query`). JSON as json.loads reads it (PyJson.loads), each value as Python's `str()`, truth and `float()`
 * take it (an int too big for a float is Python's OverflowError, an ArithmeticException, as there); the words of an
 * answer that can't be read are the data's (`answers`).
 */
object Videos {
    private val answers: JsonObject by lazy { YouTubeData.read().json.getValue("answers").jsonObject }
    private val provider: String by lazy { answers.getValue("provider").jsonPrimitive.content }
    private val liveStatuses: Set<String> by lazy {
        answers.getValue("live_statuses").jsonArray.map { it.jsonPrimitive.content }.toSet()
    }
    private val shortsPath: String by lazy { answers.getValue("shorts_path").jsonPrimitive.content }

    private fun words(name: String, error: String? = null): String {
        val text = answers.getValue(name).jsonPrimitive.content
        return if (error == null) text else YouTubeData.fillOnce(text, "{}", error)
    }

    /** ProviderError(PROVIDER, url, None, message)'s str(). */
    private fun said(url: String?, message: String): String = listOfNotNull(provider, url, message).joinToString(": ")

    /** parse_search: the videos of yt-dlp's flat search (`--flat-playlist --dump-single-json`), in its order. */
    fun parseSearch(text: String): List<Video> {
        val data = loads(text) { AnswerError(said(null, words("search_not_json", it.message)), it) }
        val entries = (data as? JsonObject)?.get("entries") as? JsonArray ?: return emptyList()
        val rules = YouTubeData.read()
        val videos = ArrayList<Video>()
        for (e in entries) {
            if (e !is JsonObject) continue
            val id = PyValues.string(e["id"]) ?: continue
            if (PyRe.fullmatch(rules.videoId, id) == null) continue
            videos += Video(
                id, str(e["title"]), str(or(e["channel"], e["uploader"])), PyValues.number(e["duration"]),
                live = PyValues.string(e["live_status"]) in liveStatuses,
                short = shortsPath in str(e["url"]),
            )
        }
        return videos
    }

    /** parse_video: a video's fields from yt-dlp's `--dump-single-json` of it; an answer of another video, or none, is
     * an [AnswerError]. */
    fun parseVideo(text: String, videoId: String): Video {
        val url = YouTubeData.read().watchUrl(videoId)
        val data = loads(text) { AnswerError(said(url, words("video_not_json", it.message)), it) }
        if (data !is JsonObject || PyValues.string(data["id"]) != videoId) throw AnswerError(said(url, words("no_such_video")))
        return Video(videoId, str(data["title"]), str(or(data["channel"], data["uploader"])),
            PyValues.number(data["duration"]), live = PyValues.string(data["live_status"]) in liveStatuses)
    }

    /** search_query: the artist, stripped, and the title without its version suffix (normalize.clean_title). */
    fun searchQuery(artist: String, title: String): String =
        YouTubeData.fillAll(YouTubeData.read().json.getValue("search_query").jsonPrimitive.content,
            linkedMapOf("artist" to Py.strip(artist), "title" to Normalize.cleanTitle(title)))

    private inline fun loads(text: String, error: (IllegalArgumentException) -> AnswerError): JsonElement = try {
        PyJson.loads(text)
    } catch (e: IllegalArgumentException) { // json.JSONDecodeError, a ValueError, or nested deeper than it reads
        throw error(e)
    }

    /** Python's `a or b`. */
    internal fun or(a: JsonElement?, b: JsonElement?): JsonElement? = if (PyValues.truthy(a)) a else b

    /** Python's `str(v or "")`. */
    internal fun str(v: JsonElement?): String = when {
        !PyValues.truthy(v) -> ""
        v is JsonPrimitive && v.isString -> v.content
        else -> PyValues.repr(v)
    }
}
