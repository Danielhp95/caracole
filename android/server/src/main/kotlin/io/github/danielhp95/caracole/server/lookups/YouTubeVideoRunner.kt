package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.youtube.Records
import io.github.danielhp95.caracole.core.youtube.SearchGate
import io.github.danielhp95.caracole.core.youtube.Video
import io.github.danielhp95.caracole.core.youtube.Videos
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant

/**
 * `caracole youtube --video=URL|ID [--progress]` on the phone (commands/youtube.py's `_video` and `_thumbnail`,
 * youtube_search.py's `video_gate`, `read_video` and `fetch_thumbnail`): a video pasted into the library page's search
 * box read now, its title, channel and length, with no download, and its thumbnail, a job of no song's that the
 * library page's panel follows. Its stages `video` and `thumbnail` (with `--progress`), its words youtube.json's
 * `video_cmd` (the computer's constants), its last line beginning "Searched: ", "Nothing found: " or "Not searched: ".
 *
 * - A link that names no video exits 2 in the computer's words.
 * - The gate first ([SearchGate.videoGate], with no request): read within 30 days (`found`, or `none` for a video
 *   YouTube won't give), said with nothing asked; else not read while YouTube is off (the computer's settings: its
 *   `off_why`, the computer's own words), this phone makes no sheet from a video ([routeWhy]), YouTube cools down, the
 *   hour's 10 (shared with the searches) are spent, or it failed within the hour.
 * - One yt-dlp run ([YouTubeAsk.ask]: the runner, a budget of 1, its run named `youtube-search:video:<id>:<time>` so
 *   the hour's 10 count it, the ladder of errors the search's shares); the record kept under
 *   `youtube-search:video:<id>` (the video, or none with why YouTube won't give it), its failure of the hour forgotten.
 * - The thumbnail, right after ([YouTubeAsk.thumbnail]).
 * - A caller that gives a [routeWhy] that lets a phone with no yt-dlp through is refused, exit 1, in the sheet's words.
 *
 * It exits 0 but for a link that is no video's. vectors/youtube/video_cmd.jsonl holds it to the computer's
 * (YouTubeVideoReplay).
 */
class YouTubeVideoRunner(
    val parts: PhoneParts,
    private val engine: YouTubeEngine?,
    private val routeWhy: () -> String? = { if (engine == null) YouTubeSheetRunner.NO_YTDLP else engine.ready() },
) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        val line = LookupJobs.line(args, setOf("--video"))
        for (name in line.options.keys) {
            if (name !in KNOWN) throw CommandExit(2, "No such option: $name")
        }
        val link = line.options["--video"] ?: throw CommandExit(2, "Missing option '--video'.")
        val progress = "--progress" in line.options
        val stripped = Py.strip(link)
        val videoId = (if (PyRe.fullmatch(YouTubeData.read().videoId, stripped) != null) stripped else null)
            ?: OverrideUrls.videoIdFromUrl(link)
            ?: throw CommandExit(2, YouTubeData.fillAll(words("not_a_video"), mapOf("link" to PyStr.repr(link))))
        Job(context, progress, videoId).run()
    }

    private inner class Job(val context: JobContext, progress: Boolean, val videoId: String) {
        val key = SearchGate.videoKey(videoId)
        val asking = YouTubeAsk(parts, context, progress, LookupJobs.now(parts))
        val now: Instant = asking.now
        val stamp: String = Stamps.of(now)

        fun say(stage: String, state: String, detail: String = "") = asking.say(stage, state, detail)
        fun end(line: String, state: String = "skipped") = asking.end(line, state)

        fun run() {
            say("video", "running", words("asking"))
            val config = parts.config()
            val said = parts.database.read { db -> SearchGate.videoGate(config, db, videoId, now, routeWhy()) }
            said.asked?.let { asked ->
                val found = asked["video"] as? JsonObject
                if (found != null) end(searched(found["title"], found["channel"]), "done")
                else end(wontGive(asked["unavailable"]), "done")
                return
            }
            if (said.state != AUTO) {
                end(words("not_searched") + fill("try_later", "why" to said.why))
                return
            }
            // The gate's routeWhy says a phone with no yt-dlp makes none: a caller that gave another is refused here.
            val engine = engine ?: throw CommandExit(1, YouTubeSheetRunner.NO_SHEET.replace("{problem}", YouTubeSheetRunner.NO_YTDLP))
            val runId = SearchGate.run + key + ":" + stamp
            val found = read(engine, config.provider(YOUTUBE), runId) ?: return
            say("video", "done", fill("video_done", "title" to found.title, "channel" to found.channel))
            asking.thumbnail(videoId, key, runId)
            context.say(searched(JsonPrimitive(found.title), JsonPrimitive(found.channel)))
        }

        /** read_video through one yt-dlp run ([YouTubeAsk.ask]), its ends said: the video, or null once the job said
         * why there is none (a video YouTube won't give kept as none, with why). */
        private fun read(engine: YouTubeEngine, policy: io.github.danielhp95.caracole.core.config.ProviderPolicy,
                         runId: String): Video? {
            val asked = asking.ask(engine, policy, key, runId,
                                   outdated = { e -> YouTubeSheetRunner.noteOutdated(parts, engine, e, now) },
                                   unavailable = { e ->
                parts.database.writeBlocking { db ->
                    asking.keep(db, key, JsonObject(linkedMapOf("at" to JsonPrimitive(stamp), "video" to JsonNull,
                        "unavailable" to JsonPrimitive(Py.slice(e.msg ?: e.message.orEmpty(), 0, YouTubeAsk.ERROR_CHARS)))))
                }
            }) { runner ->
                val got = runner.video(videoId)
                parts.database.writeBlocking { db ->
                    asking.keep(db, key, JsonObject(linkedMapOf("at" to JsonPrimitive(stamp), "video" to Records.videoJson(got),
                                                                "thumb" to JsonPrimitive(false))))
                }
                got
            } ?: return null
            if (asked.value == null) {
                val record = parts.database.read { db -> SearchGate.searched(db, key, now) }
                end(wontGive(record?.get("unavailable")), "done")
            }
            return asked.value
        }

        private fun searched(title: JsonElement?, channel: JsonElement?): String =
            fill("searched_video", "id" to videoId, "title" to str(title), "channel" to str(channel))

        private fun wontGive(unavailable: JsonElement?): String =
            fill("wont_give", "id" to videoId, "unavailable" to str(unavailable))
    }

    companion object {
        const val COMMAND = "youtube"
        private const val YOUTUBE = "youtube"
        private const val AUTO = "auto"
        private val KNOWN = setOf("--video", "--progress")

        /** One of commands/youtube.py's words for `--video` and its thumbnail (youtube.json's `video_cmd`). */
        fun words(name: String): String = YouTubeAsk.words(name)

        /** [name]'s words with each `{placeholder}` filled in one pass (str.format's, a value never read again). */
        private fun fill(name: String, vararg values: Pair<String, String>): String = YouTubeAsk.fill(name, *values)

        /** Python's str() of a JSON value, "None" for none, as an f-string writes a `dict.get`. */
        private fun str(value: JsonElement?): String = Videos.shown(value)

        /** Whether a `caracole youtube` command line is `--video`'s, which this runner runs. */
        fun isVideo(args: List<String>): Boolean = args.any { it == "--video" || it.startsWith("--video=") }
    }
}

/** `caracole youtube` on the phone: `--video` [YouTubeVideoRunner]'s, `--search` [YouTubeSearchRunner]'s (never both:
 * exit 2, as the computer's), every other line [YouTubeSheetRunner]'s. */
class YouTubeRunners(private val sheet: CommandRunner, private val video: CommandRunner,
                     private val search: CommandRunner) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) = when {
        YouTubeVideoRunner.isVideo(args) && YouTubeSearchRunner.isSearch(args) ->
            throw CommandExit(2, "Invalid value for --search/--video: --search and --video go alone")
        YouTubeVideoRunner.isVideo(args) -> video.run(args, context)
        YouTubeSearchRunner.isSearch(args) -> search.run(args, context)
        else -> sheet.run(args, context)
    }
}
