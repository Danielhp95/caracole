package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.BudgetExhausted
import io.github.danielhp95.caracole.core.http.ProviderBlocked
import io.github.danielhp95.caracole.core.http.ProviderError
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.OverrideUrls
import io.github.danielhp95.caracole.core.library.OverrideWriters
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.core.lookup.Pacing
import io.github.danielhp95.caracole.core.lookup.SiteStages
import io.github.danielhp95.caracole.core.lyrics.lyricsFromJson
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyFormat
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.youtube.Choose
import io.github.danielhp95.caracole.core.youtube.DayBudget
import io.github.danielhp95.caracole.core.youtube.ExtractorOutdated
import io.github.danielhp95.caracole.core.youtube.GateRefused
import io.github.danielhp95.caracole.core.youtube.NotSent
import io.github.danielhp95.caracole.core.youtube.Outdated
import io.github.danielhp95.caracole.core.youtube.Ran
import io.github.danielhp95.caracole.core.youtube.Record
import io.github.danielhp95.caracole.core.youtube.Records
import io.github.danielhp95.caracole.core.youtube.RunHeldBack
import io.github.danielhp95.caracole.core.youtube.Video
import io.github.danielhp95.caracole.core.youtube.VideoUnavailable
import io.github.danielhp95.caracole.core.youtube.Videos
import io.github.danielhp95.caracole.core.youtube.YouTubeAudio
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.core.youtube.YtDlp
import io.github.danielhp95.caracole.core.youtube.YtDlpProcess
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.http.caracoleResource
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.Outcomes
import io.github.danielhp95.caracole.viewer.autochords.AutoSheet
import io.github.danielhp95.caracole.viewer.autochords.ChordModels
import io.github.danielhp95.caracole.viewer.autochords.Heard
import io.github.danielhp95.caracole.viewer.autochords.Maker
import io.github.danielhp95.caracole.viewer.autochords.Relay
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.Closeable
import java.io.File
import java.math.BigInteger
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.concurrent.CancellationException
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ExecutionException
import java.util.concurrent.TimeUnit
import java.util.concurrent.TimeoutException
import java.util.logging.Logger

/**
 * `caracole youtube --sheet --progress --url=URL --song="ARTIST - TITLE"` on the phone (youtube_sheet.py, commands/
 * youtube.py's `--sheet`): one song's auto sheet from a YouTube video now, a job of the queue's worker, its stages
 * youtube_sheet.py's (song, audio, lyrics, vocals, words, chords, pdf, pages), each said as it starts and ends, so
 * that its line, steps and outcome are the computer's for the same request (Status, Outcomes' YOUTUBE_STEPS). Every
 * stage but the audio is [AudioRunner]'s ([StagedSheet]); `--url` is optional, as the computer's (the song's
 * `[youtube]` video, else its search's pick).
 *
 * Before any stage, in the command's words ("caracole makes no sheet from YouTube here: …", exit 1): YouTube off in
 * the computer's settings, no way to hear or the chord models not downloaded ([AudioRunner.problemOf]), no yt-dlp
 * ([engine] null) or one that can't run here ([YouTubeEngine.ready]); a name that isn't "Artist - Title" exits 2.
 *
 * - `song`: as [AudioRunner]'s (found or added), and refused where the song has audio of its own (an upload in
 *   [store], or an `audio_path` that isn't its `youtube:` record's: youtube_sheet.py `_still_ours`), or `[youtube]`
 *   says "none" with no video given; the video given is written under `[youtube]` ([OverrideWriters.addYoutube]) and
 *   said ("; noted under [youtube]: URL").
 * - `audio`: [YouTubeAudio.sweep] first; the song's video's audio kept already, "has the audio of URL already";
 *   YouTube cooling down, skipped in the runner's words; else youtube_fetch.py's `_one` for this song through the app's
 *   yt-dlp ([engine], the runner [YtDlp]: its budget PhoneConfig's `youtube`, its pauses, one run at a time, a block
 *   recorded by it and its cooldown), the pasted video, else the search's pick ([Choose.choose], its `skip` passed
 *   over), downloaded into a folder of its own under `cache/youtube/`, then moved to `<song id>-<video id>.m4a` and
 *   linked as the song's audio; the record (kv `youtube:<id>`) as `_one` keeps it. No write is held while yt-dlp runs
 *   or pauses: the lookups queued meanwhile go first, each second ([Yielding]). A block sends its alert
 *   ([io.github.danielhp95.caracole.core.health.Alerts.blocked]; the runner recorded it) and is a wait, as is a spent
 *   budget; a video that can't be had (unavailable, or no m4a stream: [io.github.danielhp95.caracole.core.youtube
 *   .PassedOver]) is unusable when pasted and passed over into `skip` when searched, and the stage fails; a run that
 *   never started (another of the app's going, the debug bench's) is a wait counted against nothing ([NOT_STARTED]);
 *   any other error is counted against the video (the network's aside: the data's `network` pattern) and given up at
 *   `give_up_after`. A stop of the queue mid-download stops yt-dlp ([ProcessYtDlp][Closeable.close]) and keeps nothing.
 * - `chords`: [AudioRunner]'s over the video's audio, the sheet credited to the video (AutoSheet.youtubeCredit) and
 *   its version's raw the video's (`youtube`), its maker the phone's with no `audio_name`; the decoded length said
 *   beside yt-dlp's for the video (the job's output and the log), so a real phone shows any priming or edit list.
 * - `pages`: then, with the sheet kept, the audio let go ([YouTubeAudio.letGo]): a re-lay needs none. Kept otherwise,
 *   for Try again, [YouTubeAudio.KEPT_FOR].
 */
class YouTubeSheetRunner(
    val parts: PhoneParts,
    private val engine: YouTubeEngine?,
    private val chords: ChordModels?,
    private val store: AudioStore,
    private val problem: () -> String? = { problemOf(parts.config(), engine, chords, null) },
    private val names: () -> Map<String, String> = { emptyMap() },
    private val readOverrides: (Db) -> Overrides = Overrides::read,
    private val stages: SiteStages = SiteStages.ALL,
    private val hold: (() -> Heard) -> Heard = { it() },
    private val chordsProblem: () -> String? = { AudioRunner.problemOf(chords, null) },
    private val metered: () -> Boolean = { false },
) : CommandRunner {
    override suspend fun run(args: List<String>, context: JobContext) {
        val line = LookupJobs.line(args, setOf("--song", "--url"))
        for (name in line.options.keys) {
            if (name !in KNOWN) throw CommandExit(2, "No such option: $name")
        }
        if (line.words.isNotEmpty() || "--sheet" !in line.options) throw CommandExit(2, ON_THE_PHONE)
        val display = line.options["--song"] ?: throw CommandExit(2, ON_THE_PHONE)
        try {
            OverrideUrls.overrideKey(display)
        } catch (e: OverridesError) {
            throw CommandExit(2, e.message.orEmpty())
        }
        problem()?.let { throw CommandExit(1, NO_SHEET.replace("{problem}", it)) }
        val artist = Py.strip(display.substringBefore(" - "))
        val title = Py.strip(display.substringAfter(" - ", ""))
        val process = engine!!.process()
        try {
            Job(parts, engine, process, store, chords!!, context, artist, title, line.options["--url"], names,
                readOverrides, stages, hold, chordsProblem, metered).run()
        } finally {
            (process as? Closeable)?.close()
        }
    }

    /** One run of the job: youtube_sheet.py's `_Sheet` (StagedSheet's stages, the audio YouTube's). */
    private class Job(
        parts: PhoneParts, val engine: YouTubeEngine, val process: YtDlpProcess, val store: AudioStore,
        chords: ChordModels, context: JobContext, artist: String, title: String, val url: String?,
        names: () -> Map<String, String>, readOverrides: (Db) -> Overrides, stages: SiteStages,
        hold: (() -> Heard) -> Heard, problem: () -> String?, val metered: () -> Boolean,
    ) : StagedSheet(parts, chords, context, artist, title, names, readOverrides, stages, hold, problem) {
        private val folder = YouTubeAudio.folder(File(parts.stateDir, CACHE))
        private var video: Video? = null
        private var sheetOfVideo = false  // the song's auto sheet is of the video asked for, made here: no audio needed

        /** The song its request named, should the job add it (JobContext.adds: a sheet from a video asked for by
         * name), its album and length as wanted.txt's line keeps them on the computer: `_the_song(album=,
         * duration_ms=)`, so LRCLIB is asked with the length typed. None for a request of another song's. */
        private val adds = context.adds?.takeIf { it.key == Normalize.identityKey(artist, title) }
        override val album: String? get() = adds?.album
        override val duration: Double? get() = adds?.durationMs?.let { it / 1000.0 }

        override val stageNames: List<String> get() = Words.stages.map { it.first }

        override fun found(db: Db, s: SongRow, said: String): String {
            if (url == null && s.key in overrides.youtube && overrides.youtube[s.key] == null) {
                throw Stop(Words.text("declined").replace("{display}", s.display))
            }
            if (url == null) return said
            try {
                OverrideWriters.addYoutube(db, s.display, url)
                overrides = readOverrides(db)
            } catch (e: OverridesError) {
                throw Stop(Words.text("cant_note").replace("{error}", e.message.orEmpty()))
            }
            return said + Words.text("noted").replace("{url}", watch(overrides.youtube[s.key] ?: ""))
        }

        /** youtube_sheet.py `_still_ours`, after `_unsheeted`: no audio of its own, an upload or a purchase's. */
        override fun stillOursHere(db: Db, s: SongRow) {
            if (store.uploaded(s) != null || (!s.audioPath.isNullOrEmpty() && YouTubeAudio.youtubeAudio(db, s) == null)) {
                throw Stop(Words.text("own_audio").replace("{display}", s.display))
            }
        }

        override fun madeOfThisAudio(s: SongRow): Boolean = sheetOfVideo || super.madeOfThisAudio(s)

        override fun maker(db: Db, s: SongRow, audio: File): Maker = AudioRunner.videoMaker(chords, names, db, audio)

        override fun source(): String? = video?.let { AutoSheet.youtubeCredit(it.title, it.channel, it.id) }
        override fun video(): JsonObject? = video?.let(Records::videoJson)
        override fun versionUrl(audio: File): String = video?.url ?: super.versionUrl(audio)

        /** commands/youtube.py's `sent_words`: yt-dlp's runs by their name, every other provider's as LRCLIB
         * requests, as the computer's done line says them. */
        override fun sent(provider: String, n: Int): String =
            "$n " + (if (provider == PROVIDER) "yt-dlp run" else "LRCLIB request") + (if (n == 1) "" else "s")

        override fun heard(heard: Heard) {
            val stated = video?.duration?.let { "${PyFormat.fixed(it, 2)} s" } ?: "no length"
            val decoded = heard.duration?.let { "${PyFormat.fixed(it, 2)} s" } ?: "no length"
            val said = "decoded $decoded of audio; yt-dlp said the video is $stated"
            log.info("caracole youtube --sheet $display: $said")
            context.say(said)
        }

        /** The sheet kept: the video's audio goes (the design's §5.4), the song's link and its record's with it. */
        override fun afterPages() {
            if (!sheetKept) return
            parts.database.writeBlocking { db -> YouTubeAudio.letGo(db, folder, again(db), stamp) }
            kept = null
        }

        // --- the audio ------------------------------------------------------------------------------------------------

        /** youtube_sheet.py `audio`, over youtube_fetch.py's pass for this song alone (`_one`). */
        override fun audio(): Pair<String, String> {
            val (have, pasted, cooling) = parts.database.writeBlocking { db ->
                YouTubeAudio.sweep(db, folder, now, stamp)
                val s = again(db)
                Triple(YouTubeAudio.youtubeAudio(db, s), overrides.youtube[s.key],
                       if (Health.isCooling(db, PROVIDER, now)) YtDlp.coolingWords(db) else null)
            }
            if (have != null && (pasted == null || pasted == have.id)) {
                video = have
                kept = File(song!!.audioPath!!)
                keptLength = have.duration
                return "done" to Words.text("audio_already").replace("{url}", have.url)
            }
            // Its sheet made here of the very video asked for, whose audio the phone let go once it was kept (the
            // design's §5.4): asked again, the job answers as Python's second run (its audio "already"), and the
            // chords stage finds the sheet up to date or lays it out again over new words, neither needing the audio
            // (the controller's ruling of 2026-11-27): no yt-dlp, no model.
            parts.database.read { db -> sheetVideo(db, song!!, pasted) }?.let { made ->
                video = made
                sheetOfVideo = true
                keptLength = made.duration
                return "done" to Words.text("audio_already").replace("{url}", made.url)
            }
            cooling?.let { return "skipped" to it }
            // yt-dlp out of date (Outdated): an automatic job never comes here (YouTubeAuto stops first); one asked for
            // now runs, saying so first.
            parts.database.read { db -> Outdated.state(db, engine.version, now) }?.let {
                val warning = Outcomes.outdated(engine.version!!)
                context.say(warning)
                doing("audio", warning)
            }
            doing("audio", Words.text(if (pasted != null) "downloading" else "looking"))
            val config = parts.config()
            val policy = config.provider(PROVIDER)
            // An automatic job (the design's §5.3): the day's runs left its budget, and no run on a metered network,
            // checked again before each (a job queued on Wi-Fi may run after the phone left it).
            val automatic = context.automatic
            val budget = if (automatic) parts.database.read { db -> DayBudget.left(db, config, now) }
                         else policy.budget.toInt()
            val runner = YtDlp(Yielding(process, context), policy, engine.cacheDir, engine.qjs.path, engine::gate,
                               writes, pacing(), budget = budget, runId = stamp,
                               beforeRun = { if (automatic && metered()) YouTubeSearchRunner.METERED else null })
            val outcome = try {
                one(runner, pasted)
            } catch (e: ProviderBlocked) {
                val until = parts.database.writeBlocking { db ->
                    parts.alerts.blocked(PROVIDER, Health.state(db, PROVIDER).cooldownUntil, e.message.orEmpty())
                    YtDlp.coolingUntil(db)
                }
                return "skipped" to Words.text("turned_back").replace("{until}", until)
            } catch (e: BudgetExhausted) {
                Outcome.SPENT
            } catch (e: NotSent) {  // nothing was sent: no error of the video's, no record of it
                return "failed" to NOT_STARTED.replace("{why}", e.msg.orEmpty())
            } catch (e: RunHeldBack) {  // the phone's own: no run, no error of the video's or the song's, still noted
                return "failed" to (e.msg ?: YouTubeSearchRunner.METERED)
            } catch (e: ExtractorOutdated) {  // yt-dlp's, never the video's: counted against nothing
                failed(e)
                val reason = e.msg ?: e.message.orEmpty()
                val words = noteOutdated(parts, engine, e, now) ?: return "failed" to reason  // no version: yt-dlp's
                context.say(reason)
                return "failed" to words
            } catch (e: GateRefused) {
                failed(e)
                return "failed" to (e.msg ?: e.message.orEmpty())
            } catch (e: GaveUp) {
                failed(e.cause as ProviderError)
                Outcome.GAVE_UP
            } catch (e: ProviderError) {
                failed(e)
                Outcome.ERROR
            } finally {
                requests[PROVIDER] = runner.requestsMade
            }
            parts.database.writeBlocking { db ->
                if (Health.answeredAny(db, stamp, PROVIDER, runner.requestsMade)) Health.recordOk(db, PROVIDER, now)
                again(db)
            }
            return when (outcome) {
                Outcome.SPENT -> "skipped" to Words.text("no_runs_left").replace("{budget}", policy.budget.toString())
                Outcome.DOWNLOADED -> {
                    val got = video!!
                    val named = if (got.channel.isNotEmpty()) "${got.title} (${got.channel})" else got.title.ifEmpty { got.id }
                    "done" to Words.text("downloaded").replace("{named}", named).replace("{url}", got.url)
                }
                Outcome.MISSED -> fail(Words.text("no_video_fits"))
                Outcome.PASSED_OVER, Outcome.GAVE_UP -> fail(Words.text("cant_download"))
                Outcome.ERROR -> "failed" to Words.text("download_failed")
            }
        }

        /** The video the song's auto sheet was made from, where this phone made it and it is the video asked for:
         * [pasted], else the record's pick once downloaded. Null otherwise: then the audio is downloaded. */
        private fun sheetVideo(db: Db, s: SongRow, pasted: String?): Video? {
            val record = Records.load(db, s.id)
            val wanted = pasted ?: record.video?.id?.takeIf { record.downloadedAt != null } ?: return null
            val auto = Kept.keptFiles(db, s.id).firstOrNull { it.name == Versions.SHEET_FILE_NAMES[1] } ?: return null
            val raw = Versions.get(db, auto.versionId)?.raw ?: return null
            if (Relay.madeElsewhere(db, raw)) return null
            val made = Records.videoOf(raw["youtube"]) ?: return null
            return made.takeIf { it.id == wanted }
        }

        private enum class Outcome { DOWNLOADED, MISSED, PASSED_OVER, GAVE_UP, ERROR, SPENT }

        /** youtube_fetch._count_failure's give-up: the video given up, the error that says so. */
        private class GaveUp(cause: ProviderError) : Exception(cause)

        /** youtube_fetch.py `_one` for the job's song: the video, its download, the song linked to its audio. */
        private fun one(runner: YtDlp, pasted: String?): Outcome {
            val s = song!!
            var record = parts.database.read { db -> Records.load(db, s.id) }
            val chosen: Video
            val source: String
            if (pasted != null) {
                chosen = record.video?.takeIf { it.id == pasted } ?: Video(pasted)
                source = PASTED
            } else if (record.video != null && record.source == SEARCH && !YouTubeAudio.ownAudio(s, record) &&
                       record.video!!.id !in record.skip) {
                chosen = record.video!!  // picked before a spent budget stopped its download
                source = SEARCH
            } else {
                val query = Videos.searchQuery(s.artist, s.title)
                val picked = Choose.choose(s, runner.search(query), expected(s), record.skip.toSet())
                record = record.copy(query = query, error = null, errorAt = null)
                if (picked == null) {
                    save(record.copy(missingAt = stamp))
                    return Outcome.MISSED
                }
                chosen = picked
                source = SEARCH
                record = record.copy(video = picked, source = SEARCH, missingAt = null)
                save(record)
            }
            doing("audio", Words.text("downloading"))
            val (path, got) = try {
                download(runner, s, chosen)
            } catch (e: VideoUnavailable) {
                record = if (source == PASTED) record.copy(unusable = chosen.id, unusableReason = e.msg ?: e.message)
                         else record.copy(skip = record.skip + chosen.id, video = null, source = null)
                save(record.copy(error = null, errorAt = null, failures = record.failures - chosen.id))
                return Outcome.PASSED_OVER
            } catch (e: ProviderBlocked) {
                throw e
            } catch (e: NotSent) {
                throw e
            } catch (e: RunHeldBack) {
                throw e
            } catch (e: ExtractorOutdated) {  // a host's problem, not the video's (YtDlp's KDoc): not counted
                throw e
            } catch (e: GateRefused) {
                throw e
            } catch (e: ProviderError) {
                val (counted, givenUp) = counted(record, chosen, source, e)
                save(counted)
                if (givenUp != null) throw GaveUp(givenUp)
                throw e
            }
            parts.database.writeBlocking { db ->
                val current = again(db)
                val now = Records.load(db, s.id)
                val old = if (YouTubeAudio.ownAudio(current, now)) now.audio else null
                Versions.updateSong(db, s.id, mapOf("audio_path" to path.path,
                    "audio_mtime" to AudioStore.seconds(Files.getLastModifiedTime(path.toPath()))), stamp)
                val v = Video(chosen.id, got.title.ifEmpty { chosen.title }, got.channel.ifEmpty { chosen.channel },
                              got.duration ?: chosen.duration)
                Records.save(db, s.id, now.copy(video = v, source = source, audio = path.path, downloadedAt = stamp,
                                                error = null, errorAt = null, unusable = null, unusableReason = null,
                                                failures = now.failures - chosen.id))
                if (old != null && old != path.path) YouTubeAudio.inFolder(folder, old)?.delete()
                video = v
                kept = path
                keptLength = s.durationMs?.let { it / 1000.0 } ?: v.duration ?: length(path)
                again(db)
            }
            return Outcome.DOWNLOADED
        }

        /** youtube_fetch._download: the video's audio, in place as `<song id>-<video id><ext>`, through a folder of
         * its own, so a download cut short is never anybody's audio. */
        private fun download(runner: YtDlp, s: SongRow, video: Video): Pair<File, Video> {
            folder.mkdirs()
            val part = Files.createTempDirectory(folder.toPath(), YouTubeAudio.partPrefix(s.id)).toFile()
            try {
                val got = runner.download(video.id, part)
                val path = File(folder, YouTubeAudio.name(s.id, video.id, suffix(got.path.name)))
                Files.move(got.path.toPath(), path.toPath(), StandardCopyOption.REPLACE_EXISTING)
                return path to got.video
            } finally {
                part.deleteRecursively()
            }
        }

        /** youtube_fetch._count_failure: [error] counted against the video, unless the network failed; at
         * `give_up_after` the video given up (a searched one into `skip`, a pasted one unusable) and the error that
         * says so. */
        private fun counted(record: Record, video: Video, source: String, error: ProviderError): Pair<Record, ProviderError?> {
            val reason = error.msg ?: error.message.orEmpty()
            if (PyRe.search(YouTubeData.read().pattern("network"), reason) != null) return record to null
            val failed = (record.failures[video.id]?.let(::pyInt) ?: BigInteger.ZERO) + BigInteger.ONE
            if (failed < BigInteger.valueOf(giveUpAfter.toLong())) {
                return record.copy(failures = record.failures + (video.id to JsonPrimitive(failed))) to null
            }
            val rest = record.failures - video.id
            val (given, then) = if (source == PASTED) {
                record.copy(failures = rest, unusable = video.id,
                            unusableReason = "its download failed $failed times: $reason") to GAVE_UP_PASTED
            } else {
                record.copy(failures = rest, skip = record.skip + video.id, video = null, source = null) to GAVE_UP_SEARCHED
            }
            return given to ProviderError(PROVIDER, error.url, error.status, "$reason (${video.url} failed $failed times: $then)")
        }

        /** provider_pass's error: the song's record says the last error and when. */
        private fun failed(e: ProviderError) {
            parts.database.writeBlocking { db ->
                val record = Records.load(db, song!!.id)
                Records.save(db, song!!.id, record.copy(error = e.msg ?: e.message, errorAt = stamp))
            }
        }

        private fun save(record: Record) = parts.database.writeBlocking { db -> Records.save(db, song!!.id, record) }

        /** lyrics.expected_seconds: the song's own length, else LRCLIB's. */
        private fun expected(s: SongRow): Double? = s.durationMs?.let { it / 1000.0 } ?: try {
            lyricsFromJson(s.lyricsJson)?.duration?.takeIf { it != 0.0 }
        } catch (_: IllegalArgumentException) {
            null
        }

        /** The file's length as the examiner reads it, else none. */
        private fun length(file: File): Double? = try {
            store.formatAndLength(file).second
        } catch (_: Exception) {
            null
        }

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

    /**
     * yt-dlp's run with the job's thread free: the run on a thread of its own, the job's waiting a second at a time,
     * letting the lookups queued meanwhile go first ([JobContext.yieldToQueued], with no write held). A stop of the
     * queue ([JobContext.isCancelled], or the yield's CancellationException) or an interrupt stops the run (the
     * process's [Closeable.close]: ProcessYtDlp kills yt-dlp and its qjs) and is rethrown once it ended.
     */
    internal class Yielding(private val real: YtDlpProcess, private val context: JobContext) : YtDlpProcess {
        private companion object {
            /** How long a stopped run is waited for before the job goes on without it (the process killed by then). */
            const val STOP_WAIT_MS = 30_000L
            val log: Logger = Logger.getLogger("caracole.youtube")
        }

        override fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit): Ran {
            val result = CompletableFuture<Ran>()
            val thread = Thread({
                try {
                    result.complete(real.run(argv, timeoutS, onLine, waiting))
                } catch (e: Throwable) {
                    result.completeExceptionally(e)
                }
            }, "caracole-ytdlp-run").apply { isDaemon = true; start() }
            try {
                while (true) {
                    try {
                        return result.get(1, TimeUnit.SECONDS)
                    } catch (_: TimeoutException) {
                    } catch (e: ExecutionException) {
                        throw e.cause ?: e
                    }
                    if (context.isCancelled) throw CancellationException("the queue stopped")
                    context.yieldToQueued()
                }
            } catch (e: Throwable) {
                if (!result.isDone) {
                    (real as? Closeable)?.close()
                    thread.join(STOP_WAIT_MS)
                    if (thread.isAlive) log.warning("yt-dlp's run didn't end within ${STOP_WAIT_MS / 1000} s of its stop")
                }
                throw e
            }
        }
    }

    /** youtube_sheet.py's words, from data/caracole/library/youtube_sheet.json (tests/test_conformance_youtube_sheet.py
     * writes it from the module); the rest are AudioRunner.Words'. */
    internal object Words {
        private val data: JsonObject by lazy { Json.parseToJsonElement(caracoleResource(DATA)).jsonObject }
        private val words: JsonObject by lazy { data.getValue("words").jsonObject }

        val stages: List<Pair<String, String>> by lazy {
            data.getValue("stages").jsonArray.map { it.jsonArray[0].jsonPrimitive.content to it.jsonArray[1].jsonPrimitive.content }
        }

        fun text(name: String): String = words.getValue(name).jsonPrimitive.content
    }

    companion object {
        const val COMMAND = "youtube"
        const val DATA = "caracole/library/youtube_sheet.json"
        private const val PROVIDER = "youtube"
        private const val CACHE = "cache"
        private const val PASTED = "pasted"
        private const val SEARCH = "search"
        private const val SYNC_ID = StagedSheet.SYNC_ID
        private val KNOWN = setOf("--song", "--url", "--sheet", "--progress")
        private val log: Logger = Logger.getLogger("caracole.youtube")

        private val giveUpAfter: Int by lazy {
            (YouTubeData.read().json.getValue("fetch") as JsonObject).getValue("give_up_after").jsonPrimitive.int
        }

        /** An [ExtractorOutdated] run of the app's yt-dlp noted (Outdated.note, by the run's target: the video's address,
         * or the search's), its alert sent once when it set out of date (two videos within 24 hours, once a version);
         * the phone's words for it ([Outcomes.outdated]), or null with no version known (nothing noted). */
        internal fun noteOutdated(parts: PhoneParts, engine: YouTubeEngine, e: ExtractorOutdated,
                                  now: java.time.Instant): String? {
            val version = engine.version ?: return null
            val reason = e.msg ?: e.message.orEmpty()
            if (parts.database.writeBlocking { db -> Outdated.note(db, version, e.url ?: SEARCH, reason, now) }) {
                parts.alerts.outdated(version, Outcomes.outdated(version))
            }
            return Outcomes.outdated(version)
        }

        /** commands/youtube.py's words for a caracole that makes no sheet from YouTube. */
        const val NO_SHEET = "caracole makes no sheet from YouTube here: {problem}"

        /** The phone's own words, where the computer's have no case. */
        const val ON_THE_PHONE = "caracole youtube on the phone takes --sheet, --song=\"ARTIST - TITLE\" and --url=URL"
        const val OFF = "YouTube is off (the computer's settings)"
        const val NO_YTDLP = "this phone's caracole has no yt-dlp"
        const val NOT_STARTED = "yt-dlp didn't start ({why}); try again in a moment"
        const val GAVE_UP_PASTED = "it waits for another video under [youtube]"
        const val GAVE_UP_SEARCHED = "the next run picks another"

        /** Why this phone makes no sheet from a YouTube video now, or null, the design's §5.6 in order: YouTube off in
         * the computer's settings, the chords' reasons ([AudioRunner.problemOf]), no yt-dlp, one that can't run. */
        fun problemOf(config: PhoneConfig, engine: YouTubeEngine?, chords: ChordModels?, modelsReady: String?): String? =
            when {
                !config.provider(PROVIDER).enabled -> OFF
                else -> AudioRunner.problemOf(chords, modelsReady) ?: if (engine == null) NO_YTDLP else engine.ready()
            }

        private fun watch(id: String): String = YouTubeData.read().watchUrl(id)

        /** PurePath.suffix, lowercased: the name's last dotted part, none for a name only starting or ending so. */
        private fun suffix(name: String): String {
            val dot = name.lastIndexOf('.')
            return if (dot <= 0 || dot == name.length - 1) "" else PyText.lower(name.substring(dot))
        }

        /** A failure count as Python's int reads it (a bool 1 or 0). */
        private fun pyInt(v: JsonPrimitive): BigInteger = when (v.content) {
            "true" -> BigInteger.ONE
            "false" -> BigInteger.ZERO
            else -> v.content.toBigIntegerOrNull() ?: BigInteger.ZERO
        }
    }
}
