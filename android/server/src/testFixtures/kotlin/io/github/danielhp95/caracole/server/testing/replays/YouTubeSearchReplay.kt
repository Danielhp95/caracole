package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.lookups.YouTubeSearchRunner
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * `caracole youtube --search=QUERY --progress` replayed from the computer's records (vectors/youtube/search_cmd.jsonl,
 * written by tests/test_conformance_youtube.py, whose comment over its records says what each holds), area
 * `youtube-search`, as [YouTubeVideoReplay] replays `--video` ([YouTubeVideoReplay.command]: the scene's kv texts,
 * events, settings and kept thumbnail, every clock at its `now`, the image host a FakeTransport of its answer): the
 * phone's own [YouTubeSearchRunner] given the command line as the queue's job passes it, its yt-dlp FakeYtDlp's
 * answer for the search (its query's words joined by one space, as the command reads them), its reason for no sheet
 * from a video the record's `problem` (the computer's words: the phone's are its own, Phone.youtubeProblem).
 * Compared as YouTubeVideoReplay compares.
 */
object YouTubeSearchReplay : AreaReplay {
    override val area = "youtube-search"
    const val VECTOR = "youtube/search_cmd.jsonl"

    override fun replay(misses: Misses) {
        for (record in cases()) {
            for (f in one(record)) misses.check(false) { f }
            misses.check(true) { "" }
        }
    }

    fun cases(): List<JsonObject> = Corpus.lines(VECTOR).filter { "case" in it }

    /** The differences of [record] replayed, each "case: what differs". */
    fun one(record: JsonObject): List<String> {
        val kw = record.getValue("kw").jsonObject
        val query = kw.getValue("query").jsonPrimitive.content
        val problem = kw["problem"]?.takeIf { it !is JsonNull }?.jsonPrimitive?.content
        val search = kw["search"]?.takeIf { it !is JsonNull }?.jsonObject
        val searches = if (search == null) JsonObject(emptyMap())
        else JsonObject(mapOf(Py.split(query).joinToString(" ") to search))
        val plan = JsonObject(mapOf("searches" to searches, "videos" to JsonObject(emptyMap())))
        return YouTubeVideoReplay.command(record, listOf("youtube", "--search=$query", "--progress"), plan) { parts, engine ->
            YouTubeSearchRunner(parts, engine, routeWhy = { problem })
        }
    }
}
