package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.config.ProviderPolicy
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.lookup.Clients
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.ug.UgLinks
import io.github.danielhp95.caracole.core.youtube.ExtractorOutdated
import io.github.danielhp95.caracole.core.youtube.GateRefused
import io.github.danielhp95.caracole.core.youtube.NotSent
import io.github.danielhp95.caracole.core.youtube.RunHeldBack
import io.github.danielhp95.caracole.core.youtube.SearchGate
import io.github.danielhp95.caracole.core.youtube.Thumbs
import io.github.danielhp95.caracole.core.youtube.VideoUnavailable
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.core.youtube.YtDlp
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.JobContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.Closeable
import java.io.File
import java.time.Instant
import java.util.concurrent.CancellationException

/**
 * What `caracole youtube --video` and `--search` share on the phone (commands/youtube.py's `_video`, `_search` and
 * `_thumbnail`): one job's stages said ([say], [end]: the stage's detail and the job's line), its one yt-dlp run asked
 * through the ladder of errors both commands keep ([ask]), and the video's thumbnail right after ([thumbnail]). Their
 * words are youtube.json's `video_cmd` (the computer's constants, [words]).
 *
 * - [ask]: one run through the runner [YtDlp] over the engine's process (a budget of 1, its pauses, its run named
 *   [ask]'s `runId` so the hour's 10 count it, [beforeRun] its last word before the run, its database a write a
 *   touch: [writes]), the job's thread let free meanwhile ([YouTubeSheetRunner.Yielding]). A block was recorded by the
 *   runner: the job sends its alert; a spent budget, a run never started ([NotSent]: counted against nothing), the
 *   phone's own host problems (yt-dlp out of date, the gate's refusal, a run held back: said in their words, counted
 *   against neither the key nor the hour), and any other error ([Health.recordError], and the failure that pauses the
 *   key for the hour) are said, never a miss. A good run recorded as the computer's ([Health.answeredAny]).
 * - [thumbnail]: none while the image host (`ytimg`) is off or cools down; else one request through a PoliteClient of
 *   its own policy ([Clients.named], the same run, robots' rules, the cache forever; no write held while it goes),
 *   kept when a JPEG ([Thumbs.keep], then [Thumbs.note] on the key's record); a block of its own recorded here (its
 *   cooldown, never YouTube's) and told outside any write; an error recorded; none is no failure.
 */
internal class YouTubeAsk(
    private val parts: PhoneParts,
    private val context: JobContext,
    private val progress: Boolean,
    val now: Instant,
    private val beforeRun: () -> String? = { null },
) {
    /** The stage [stage] is at, told with `--progress`; a queue that stopped stops the job here. */
    fun say(stage: String, state: String, detail: String = "") {
        if (context.isCancelled) throw CancellationException("the queue stopped")
        if (progress) context.stage(stage, state, detail)
    }

    /** The job ends with [line]: the `video` stage's last detail and the job's line. */
    fun end(line: String, state: String = "skipped") {
        say(VIDEO_STAGE, state, line)
        context.say(line)
    }

    /** The answer [run] gave, null for none (a video YouTube won't give, a search that found none). */
    class Asked<T>(val value: T?)

    /**
     * [run] over one yt-dlp run for [key] under [runId], its ends said: what it came to ([Asked]), or null once the job
     * said why there is none. [unavailable] answers a video YouTube won't give (a `--video`'s); left null, that is an
     * error as any other (a `--search`'s). [outdated] notes yt-dlp out of date and gives the phone's words for it (a
     * `--video`'s, YouTubeSheetRunner.noteOutdated; the search's suggestion notes none).
     */
    fun <T> ask(engine: YouTubeEngine, policy: ProviderPolicy, key: String, runId: String,
                unavailable: ((VideoUnavailable) -> Unit)? = null,
                outdated: ((ExtractorOutdated) -> String?)? = null,
                run: (YtDlp) -> T?): Asked<T>? {
        val process = engine.process()
        val runner = YtDlp(YouTubeSheetRunner.Yielding(process, context), policy, engine.cacheDir, engine.qjs.path,
                           engine::gate, writes, pacing(), budget = 1, runId = runId, beforeRun = beforeRun)
        val value: T? = try {
            run(runner)
        } catch (e: ProviderBlocked) {  // the runner recorded it (one strike): its alert is the job's
            val state = parts.database.read { db -> Health.state(db, YOUTUBE) }
            val until = UgLinks.shown(state.cooldownUntil)
            parts.alerts.blocked(YOUTUBE, state.cooldownUntil, fill("runs_alert", "error" to e.message.orEmpty(),
                                                                     "until" to until, "strikes" to state.strikes.toString()))
            end(words("not_searched") + fill("turned_back", "error" to e.message.orEmpty(), "until" to until))
            return null
        } catch (e: BudgetExhausted) {
            end(words("not_searched") + words("no_runs"))
            return null
        } catch (e: NotSent) {  // nothing reached yt-dlp: no error of the key's, nothing remembered
            end(words("not_searched") + YouTubeSheetRunner.NOT_STARTED.replace("{why}", e.msg.orEmpty()) + ".")
            return null
        } catch (e: ProviderError) {
            if (unavailable != null && e is VideoUnavailable) {
                unavailable(e)
                null
            } else {
                val why = e.msg ?: e.message.orEmpty()
                if (e is ExtractorOutdated || e is GateRefused || e is RunHeldBack) {
                    // the phone's own, a host's problem and never the key's (as YouTubeSheetRunner rules them): said
                    // in their words (yt-dlp out of date in the phone's, noted, where [outdated] notes it), nothing
                    // recorded against the key or the hour
                    val said = (e as? ExtractorOutdated)?.let { outdated?.invoke(it) } ?: why
                    end(words("not_searched") + said + ".")
                    return null
                }
                parts.database.writeBlocking { db ->
                    Health.recordError(db, YOUTUBE, now, e.message.orEmpty())
                    SearchGate.recordFailure(db, key, now, why)
                }
                end(words("not_searched") + fill("ytdlp_failed", "error" to why))
                return null
            }
        } finally {
            (process as? Closeable)?.close()
        }
        parts.database.writeBlocking { db ->
            if (Health.answeredAny(db, runId, YOUTUBE, runner.requestsMade)) Health.recordOk(db, YOUTUBE, now)
        }
        return Asked(value)
    }

    /** The record of [key] (`youtube-search:<key>`), and its failure of the hour forgotten. */
    fun keep(db: Db, key: String, said: JsonObject) {
        db.kvSetJson(SearchGate.kvKey(key), said)
        SearchGate.forgetFailure(db, key, now)
    }

    /** `_thumbnail`: [videoId]'s thumbnail, right after its run, from YouTube's image host, noted on [key]'s record:
     * its request in no write (its client's events each a write of their own), what came of it recorded after. */
    fun thumbnail(videoId: String, key: String, runId: String) {
        val config = parts.config()
        if (!config.provider(Thumbs.PROVIDER).enabled) {
            say(THUMB_STAGE, "skipped", words("thumb_off"))
            return
        }
        val cooling = parts.database.read { db ->
            if (Health.isCooling(db, Thumbs.PROVIDER, now)) UgLinks.shown(Health.state(db, Thumbs.PROVIDER).cooldownUntil)
            else null
        }
        if (cooling != null) {
            say(THUMB_STAGE, "skipped", fill("thumb_cooling", "until" to cooling))
            return
        }
        say(THUMB_STAGE, "running", "")
        val thumbs = Thumbs(File(parts.stateDir, CACHE))
        val client = parts.clients().named(writes, Thumbs.PROVIDER, runId)
        try {
            val kept = thumbs.keep(client, videoId)
            if (kept) parts.database.writeBlocking { db -> thumbs.note(db, videoId, key, now) }
            say(THUMB_STAGE, if (kept) "done" else "skipped", words(if (kept) "thumb_kept" else "thumb_none"))
        } catch (e: ProviderBlocked) {
            val state = parts.database.writeBlocking { db -> Health.recordBlock(db, Thumbs.PROVIDER, now, e.message.orEmpty()) }
            val until = UgLinks.shown(state.cooldownUntil)
            parts.alerts.blocked(Thumbs.PROVIDER, state.cooldownUntil, fill("thumbs_alert", "error" to e.message.orEmpty(),
                                                                             "until" to until, "strikes" to state.strikes.toString()))
            say(THUMB_STAGE, "skipped", fill("thumb_blocked", "until" to until))
            return
        } catch (e: BudgetExhausted) {
            say(THUMB_STAGE, "skipped", words("thumb_spent"))
            return
        } catch (e: ProviderError) {
            parts.database.writeBlocking { db -> Health.recordError(db, Thumbs.PROVIDER, now, e.message.orEmpty()) }
            say(THUMB_STAGE, "skipped", words("thumb_failed"))
            return
        } finally {
            client.close()
        }
        parts.database.writeBlocking { db ->
            if (Health.answeredAny(db, runId, Thumbs.PROVIDER, client.requestsMade)) Health.recordOk(db, Thumbs.PROVIDER, now)
        }
    }

    /** The database for the runner and the image host's client, a write a touch: none held across a run, a request
     * or a pause. */
    private val writes = object : YtDlp.Writes, Clients.Writes {
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

    companion object {
        private const val YOUTUBE = "youtube"
        private const val CACHE = "cache"
        const val VIDEO_STAGE = "video"
        const val THUMB_STAGE = "thumbnail"

        /** youtube_search.ERROR_CHARS, the data's `search.error_chars`. */
        val ERROR_CHARS: Int by lazy {
            YouTubeData.read().json.getValue("search").jsonObject.getValue("error_chars").jsonPrimitive.content.toInt()
        }

        private val video: JsonObject by lazy { YouTubeData.read().json.getValue("video_cmd").jsonObject }

        /** One of commands/youtube.py's words for `--video`, `--search` and the thumbnail (youtube.json's
         * `video_cmd`). */
        fun words(name: String): String = video.getValue(name).jsonPrimitive.content

        /** [name]'s words with each `{placeholder}` filled in one pass (str.format's, a value never read again). */
        fun fill(name: String, vararg values: Pair<String, String>): String =
            YouTubeData.fillAll(words(name), mapOf(*values))
    }
}
