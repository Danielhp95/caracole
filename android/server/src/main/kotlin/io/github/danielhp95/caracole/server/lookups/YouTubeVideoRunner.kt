package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.ug.UgLinks
import io.github.danielhp95.caracole.core.youtube.NotSent
import io.github.danielhp95.caracole.core.youtube.Records
import io.github.danielhp95.caracole.core.youtube.SearchGate
import io.github.danielhp95.caracole.core.youtube.Thumbs
import io.github.danielhp95.caracole.core.youtube.Video
import io.github.danielhp95.caracole.core.youtube.VideoUnavailable
import io.github.danielhp95.caracole.core.youtube.Videos
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.core.youtube.YtDlp
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.Closeable
import java.io.File
import java.time.Instant
import java.util.concurrent.CancellationException

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
 * - One yt-dlp run (the runner [YtDlp] over the engine's process, a budget of 1, its pauses, its run named
 *   `youtube-search:video:<id>:<time>` so the hour's 10 count it, its database a write a touch), the job's thread let
 *   free meanwhile ([YouTubeSheetRunner.Yielding]); the record kept under `youtube-search:video:<id>` (the video, or
 *   none with why YouTube won't give it), its failure of the hour forgotten. A block was recorded by the runner: the
 *   job sends its alert; a spent budget, a run never started ([NotSent], the bench's run going: counted against
 *   nothing) and any other error (`Health.recordError`, and the failure that pauses it for the hour) are said, never
 *   a miss. A good run recorded as the computer's (`Health.answeredAny`).
 * - The thumbnail, right after: none while the image host (`ytimg`) is off or cools down; else one request through a
 *   PoliteClient of its own policy ([io.github.danielhp95.caracole.core.lookup.Clients.named], the same run, robots'
 *   rules, the cache forever), kept when a JPEG ([Thumbs]); a block of its own recorded here (its cooldown, never
 *   YouTube's) and told; an error recorded; none is no failure.
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
            ?: throw CommandExit(2, words("not_a_video").replace("{link}", PyStr.repr(link)))
        Job(context, progress, videoId).run()
    }

    private inner class Job(val context: JobContext, val progress: Boolean, val videoId: String) {
        val key = SearchGate.videoKey(videoId)
        val now: Instant = LookupJobs.now(parts)
        val stamp: String = Stamps.of(now)

        fun say(stage: String, state: String, detail: String = "") {
            if (context.isCancelled) throw CancellationException("the queue stopped")
            if (progress) context.stage(stage, state, detail)
        }

        fun end(line: String, state: String = "skipped") {
            say("video", state, line)
            context.say(line)
        }

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
                end(words("not_searched") + words("try_later").replace("{why}", said.why))
                return
            }
            val runId = SearchGate.run + key + ":" + stamp
            val found = read(config.provider(YOUTUBE), runId) ?: return
            say("video", "done", words("video_done").replace("{title}", found.title).replace("{channel}", found.channel))
            thumbnail(runId)
            context.say(searched(JsonPrimitive(found.title), JsonPrimitive(found.channel)))
        }

        /** read_video through one yt-dlp run, its ends said; the video, or null once the job said why there is none. */
        private fun read(policy: io.github.danielhp95.caracole.core.config.ProviderPolicy, runId: String): Video? {
            val engine = engine!!  // routeWhy said none is missing
            val process = engine.process()
            val runner = YtDlp(YouTubeSheetRunner.Yielding(process, context), policy, engine.cacheDir, engine.qjs.path,
                               engine::gate, writes, pacing(), budget = 1, runId = runId)
            val video = try {
                val got = runner.video(videoId)
                parts.database.writeBlocking { db ->
                    keep(db, JsonObject(linkedMapOf("at" to JsonPrimitive(stamp), "video" to Records.videoJson(got),
                                                    "thumb" to JsonPrimitive(false))))
                }
                got
            } catch (e: ProviderBlocked) {  // the runner recorded it (one strike): its alert is the job's
                val until = parts.database.writeBlocking { db ->
                    val state = Health.state(db, YOUTUBE)
                    parts.alerts.blocked(YOUTUBE, state.cooldownUntil, words("runs_alert")
                        .replace("{error}", e.message.orEmpty()).replace("{until}", UgLinks.shown(state.cooldownUntil))
                        .replace("{strikes}", state.strikes.toString()))
                    UgLinks.shown(state.cooldownUntil)
                }
                end(words("not_searched") + words("turned_back").replace("{error}", e.message.orEmpty())
                    .replace("{until}", until))
                return null
            } catch (e: VideoUnavailable) {
                parts.database.writeBlocking { db ->
                    keep(db, JsonObject(linkedMapOf("at" to JsonPrimitive(stamp), "video" to JsonNull,
                        "unavailable" to JsonPrimitive(Py.slice(e.msg ?: e.message.orEmpty(), 0, ERROR_CHARS)))))
                }
                null
            } catch (e: BudgetExhausted) {
                end(words("not_searched") + words("no_runs"))
                return null
            } catch (e: NotSent) {  // nothing reached yt-dlp: no error of the video's, nothing remembered
                end(words("not_searched") + YouTubeSheetRunner.NOT_STARTED.replace("{why}", e.msg.orEmpty()) + ".")
                return null
            } catch (e: ProviderError) {
                val why = e.msg ?: e.message.orEmpty()
                parts.database.writeBlocking { db ->
                    Health.recordError(db, YOUTUBE, now, e.message.orEmpty())
                    SearchGate.recordFailure(db, key, now, why)
                }
                end(words("not_searched") + words("ytdlp_failed").replace("{error}", why))
                return null
            } finally {
                (process as? Closeable)?.close()
            }
            parts.database.writeBlocking { db ->
                if (Health.answeredAny(db, runId, YOUTUBE, runner.requestsMade)) Health.recordOk(db, YOUTUBE, now)
            }
            if (video == null) {
                val asked = parts.database.read { db -> SearchGate.searched(db, key, now) }
                end(wontGive(asked?.get("unavailable")), "done")
            }
            return video
        }

        /** The record of the read (`youtube-search:video:<id>`), and its failure of the hour forgotten. */
        private fun keep(db: Db, said: JsonObject) {
            db.kvSetJson(SearchGate.kvKey(key), said)
            SearchGate.forgetFailure(db, key, now)
        }

        /** `_thumbnail`: the video's thumbnail, right after its read, from YouTube's image host. */
        private fun thumbnail(runId: String) {
            val config = parts.config()
            if (!config.provider(Thumbs.PROVIDER).enabled) {
                say("thumbnail", "skipped", words("thumb_off"))
                return
            }
            val cooling = parts.database.read { db ->
                if (Health.isCooling(db, Thumbs.PROVIDER, now)) UgLinks.shown(Health.state(db, Thumbs.PROVIDER).cooldownUntil)
                else null
            }
            if (cooling != null) {
                say("thumbnail", "skipped", words("thumb_cooling").replace("{until}", cooling))
                return
            }
            say("thumbnail", "running", "")
            val thumbs = Thumbs(File(parts.stateDir, CACHE))
            // One request at most, so its write is held for it, as a lookup's are.
            parts.database.writeBlocking { db ->
                val client = parts.clients().named(db, Thumbs.PROVIDER, runId)
                try {
                    val kept = thumbs.fetch(db, client, videoId, key, now)
                    say("thumbnail", if (kept) "done" else "skipped", words(if (kept) "thumb_kept" else "thumb_none"))
                } catch (e: ProviderBlocked) {
                    val state = Health.recordBlock(db, Thumbs.PROVIDER, now, e.message.orEmpty())
                    val until = UgLinks.shown(state.cooldownUntil)
                    parts.alerts.blocked(Thumbs.PROVIDER, state.cooldownUntil, words("thumbs_alert")
                        .replace("{error}", e.message.orEmpty()).replace("{until}", until)
                        .replace("{strikes}", state.strikes.toString()))
                    say("thumbnail", "skipped", words("thumb_blocked").replace("{until}", until))
                    return@writeBlocking
                } catch (e: BudgetExhausted) {
                    say("thumbnail", "skipped", words("thumb_spent"))
                    return@writeBlocking
                } catch (e: ProviderError) {
                    Health.recordError(db, Thumbs.PROVIDER, now, e.message.orEmpty())
                    say("thumbnail", "skipped", words("thumb_failed"))
                    return@writeBlocking
                } finally {
                    client.close()
                }
                if (Health.answeredAny(db, runId, Thumbs.PROVIDER, client.requestsMade)) {
                    Health.recordOk(db, Thumbs.PROVIDER, now)
                }
            }
        }

        private fun searched(title: JsonElement?, channel: JsonElement?): String = words("searched_video")
            .replace("{id}", videoId).replace("{title}", str(title)).replace("{channel}", str(channel))

        private fun wontGive(unavailable: JsonElement?): String = words("wont_give")
            .replace("{id}", videoId).replace("{unavailable}", str(unavailable))

        /** The database for the runner, a write a touch: none held across a run or a pause. */
        private val writes = object : YtDlp.Writes {
            override fun <T> use(block: (Db) -> T): T = parts.database.writeBlocking(block)
        }

        /** The job's pace, its sleeps a second at a time with the queued lookups let go first between them. */
        private fun pacing(): Pacing {
            val p = parts.pacing
            return p.copy(sleep = { seconds ->
                var left = seconds
                while (left > 0) {
                    val step = if (left < 1.0) left else 1.0
                    p.sleep(step)
                    left -= step
                    if (context.isCancelled) throw CancellationException("the queue stopped")
                    context.yieldToQueued()
                }
            })
        }
    }

    companion object {
        const val COMMAND = "youtube"
        private const val YOUTUBE = "youtube"
        private const val AUTO = "auto"
        private const val CACHE = "cache"
        private val KNOWN = setOf("--video", "--progress")

        /** youtube_search.ERROR_CHARS, the data's `search.error_chars`. */
        private val ERROR_CHARS: Int by lazy {
            YouTubeData.read().json.getValue("search").jsonObject.getValue("error_chars").jsonPrimitive.content.toInt()
        }

        private val data: JsonObject by lazy { YouTubeData.read().json.getValue("video_cmd").jsonObject }

        /** One of commands/youtube.py's words for `--video` and its thumbnail (youtube.json's `video_cmd`). */
        fun words(name: String): String = data.getValue(name).jsonPrimitive.content

        /** Python's str() of a JSON value, "None" for none, as an f-string writes a `dict.get`. */
        private fun str(value: JsonElement?): String = Videos.shown(value)

        /** Whether a `caracole youtube` command line is `--video`'s, which this runner runs. */
        fun isVideo(args: List<String>): Boolean = args.any { it == "--video" || it.startsWith("--video=") }
    }
}

/** `caracole youtube` on the phone: `--video` [YouTubeVideoRunner]'s, every other line [YouTubeSheetRunner]'s. */
class YouTubeRunners(private val sheet: CommandRunner, private val video: CommandRunner) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) =
        if (YouTubeVideoRunner.isVideo(args)) video.run(args, context) else sheet.run(args, context)
}
