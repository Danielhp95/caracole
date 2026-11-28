package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.youtube.Records
import io.github.danielhp95.caracole.core.youtube.SearchGate
import io.github.danielhp95.caracole.core.youtube.Videos
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * `caracole youtube --search=QUERY [--progress]` on the phone (commands/youtube.py's `_search` and `_thumbnail`,
 * youtube_search.py's `gate`, `search` and `fetch_thumbnail`): YouTube's first video for a query the library page's
 * search found no sheet for, and its thumbnail, a job of no song's the page follows, then searches again (its row fills
 * the request form and sends nothing). Its stages `video` and `thumbnail` (with `--progress`), its words youtube.json's
 * `search_cmd` and `video_cmd` (the computer's constants), its last line beginning "Searched: ", "Nothing found: " or
 * "Not searched: ".
 *
 * - The query's words joined by one space; one of no word, or a phone that makes no sheet from a video ([routeWhy]:
 *   Phone.youtubeProblem, its own words), is not searched, nothing asked.
 * - The gate first ([SearchGate.gate], with no request): searched within 30 days (`found`, or `none`), said with
 *   nothing asked; else not searched while YouTube cools down, the hour's 10 (shared with the pasted videos' reads)
 *   are spent, it or three searches failed within the hour, or, the phone's own, the network is metered ([metered]:
 *   the gate's `off`, [METERED]'s words: a suggestion goes on an unmetered network alone).
 * - One yt-dlp run ([YouTubeAsk.ask]: `ytsearch1:`, a budget of 1, its run named `youtube-search:<time>` so the hour's
 *   10 count it, the network checked again just before it ([METERED], a run held back: counted against nothing), the
 *   ladder of errors `--video`'s shares): its first video that isn't live, recorded under `youtube-search:<key>` with
 *   the query (or with none: nothing found), the key's failure of the hour forgotten.
 * - The thumbnail, right after ([YouTubeAsk.thumbnail]), noted on the query's record.
 *
 * It exits 0 but for a caller that lets a phone with no yt-dlp through (exit 1, the sheet's words).
 * vectors/youtube/search_cmd.jsonl holds it to the computer's (YouTubeSearchReplay).
 */
class YouTubeSearchRunner(
    val parts: PhoneParts,
    private val engine: YouTubeEngine?,
    private val routeWhy: () -> String? = { if (engine == null) YouTubeSheetRunner.NO_YTDLP else engine.ready() },
    private val metered: () -> Boolean = { false },
) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        val line = LookupJobs.line(args, setOf("--search"))
        for (name in line.options.keys) {
            if (name !in KNOWN) throw CommandExit(2, "No such option: $name")
        }
        val query = line.options["--search"] ?: throw CommandExit(2, "Missing option '--search'.")
        Job(context, "--progress" in line.options, Py.split(query).joinToString(" ")).run()
    }

    private inner class Job(val context: JobContext, progress: Boolean, val query: String) {
        val key = SearchGate.queryKey(query)
        val held: () -> String? = { if (metered()) METERED else null }
        val asking = YouTubeAsk(parts, context, progress, LookupJobs.now(parts), beforeRun = held)
        val shown = YouTubeData.fillAll(words("quoted"), mapOf("query" to query))

        fun run() {
            if (key.isEmpty()) return asking.end(NOT_SEARCHED + fill("no_word", "query" to shown))
            routeWhy()?.let { return asking.end(NOT_SEARCHED + fill("no_sheets_here", "problem" to it)) }
            asking.say(YouTubeAsk.VIDEO_STAGE, "running", YouTubeAsk.words("asking"))
            val config = parts.config()
            val now = asking.now
            val said = parts.database.read { db -> SearchGate.gate(config, db, query, false, now, heldBack = held()) }
            said?.asked?.let { asked ->
                val video = asked["video"] as? JsonObject
                if (video != null) asking.end(searched(Videos.shown(video["title"]), Videos.shown(video["channel"]),
                                                       Videos.shown(video["url"])), "done")
                else asking.end(fill("none_lately", "query" to shown), "done")
                return
            }
            if (said == null || said.state != AUTO) {
                return asking.end(NOT_SEARCHED + YouTubeAsk.fill("try_later", "why" to (said?.why ?: words("nothing_to_search"))))
            }
            // The gate's routeWhy says a phone with no yt-dlp makes none: a caller that gave another is refused here.
            val engine = engine ?: throw CommandExit(1, YouTubeSheetRunner.NO_SHEET.replace("{problem}", YouTubeSheetRunner.NO_YTDLP))
            val runId = SearchGate.run + Stamps.of(now)
            val asked = asking.ask(engine, config.provider(YOUTUBE), key, runId) { runner ->
                val video = runner.search(query, 1).firstOrNull { !it.live }
                parts.database.writeBlocking { db ->
                    asking.keep(db, key, JsonObject(linkedMapOf("at" to JsonPrimitive(Stamps.of(now)), "query" to JsonPrimitive(query),
                        "video" to (video?.let(Records::videoJson) ?: JsonNull), "thumb" to JsonPrimitive(false))))
                }
                video
            } ?: return
            val found = asked.value ?: return asking.end(fill("none_now", "query" to shown), "done")
            asking.say(YouTubeAsk.VIDEO_STAGE, "done", YouTubeAsk.fill("video_done", "title" to found.title, "channel" to found.channel))
            asking.thumbnail(found.id, key, runId)
            context.say(searched(found.title, found.channel, found.url))
        }

        private fun searched(title: String, channel: String, url: String): String =
            fill("searched", "query" to shown, "title" to title, "channel" to channel, "url" to url)
    }

    companion object {
        private const val YOUTUBE = "youtube"
        private const val AUTO = "auto"
        private val KNOWN = setOf("--search", "--progress")

        /** The phone's own: why no search of YouTube goes on a metered network (the phone-youtube design's words, an
         * automatic job's too): the gate's `off` while metered, and a run held back when it became so meanwhile. */
        const val METERED = "waiting for Wi-Fi"

        private val NOT_SEARCHED: String get() = YouTubeAsk.words("not_searched")

        private val data: JsonObject by lazy { YouTubeData.read().json.getValue("search_cmd").jsonObject }

        /** One of commands/youtube.py's words for `--search` (youtube.json's `search_cmd`). */
        private fun words(name: String): String = data.getValue(name).jsonPrimitive.content

        /** [name]'s words with each `{placeholder}` filled in one pass. */
        private fun fill(name: String, vararg values: Pair<String, String>): String =
            YouTubeData.fillAll(words(name), mapOf(*values))

        /** Whether a `caracole youtube` command line is `--search`'s, which this runner runs. */
        fun isSearch(args: List<String>): Boolean = args.any { it == "--search" || it.startsWith("--search=") }
    }
}
