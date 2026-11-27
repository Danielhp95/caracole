package io.github.danielhp95.caracole.server.lookups

import io.github.danielhp95.caracole.core.catalogues.CatalogueError
import io.github.danielhp95.caracole.core.catalogues.Catalogues
import io.github.danielhp95.caracole.core.catalogues.Limited
import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.index.Paced
import io.github.danielhp95.caracole.core.index.Sizes
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.models.ModelFiles
import io.github.danielhp95.caracole.core.models.ModelsSource
import io.github.danielhp95.caracole.core.models.Pins
import io.github.danielhp95.caracole.mirror.Http
import io.github.danielhp95.caracole.server.PhoneParts
import io.github.danielhp95.caracole.server.jobs.CommandExit
import io.github.danielhp95.caracole.server.jobs.CommandRunner
import io.github.danielhp95.caracole.server.jobs.JobCommands
import io.github.danielhp95.caracole.server.jobs.JobContext
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.IOException
import java.nio.file.FileVisitResult
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.Path
import java.nio.file.SimpleFileVisitor
import java.nio.file.attribute.BasicFileAttributes
import java.time.Instant
import java.util.concurrent.locks.ReentrantReadWriteLock
import kotlin.concurrent.read

/**
 * `caracole models [--metered-ok]` (the phone's own command, PhoneKinds' models kind): the chord models downloaded
 * at a tap (the design's §6, core.models' [ModelsSource]), on the queue's one worker, so never beside a lookup's
 * write or any other job's, and never two fetches at once: its key (`models:`, a request while one waits or runs
 * answered by that one) and the queue's one worker are the guarantee [ModelsSource.fetch] asks of its caller, and
 * nothing else calls it. Its one stage, `models`, says:
 *
 * 1. a build that carries no models ([source] null: ModelFiles.carried() found no models.json, a build without
 *    `:ml`): "Not downloaded: This build carries no chord models.", no request, nothing written;
 * 2. the folder already installed whole ([ModelFiles.installed], the judge: the files, never the record): "Chord models
 *    ready · 55 MB", no request (kv [INSTALLED] written where it was lost);
 * 3. a time GitHub said to ask again after (kv [NOT_BEFORE]) still to come, up to [Catalogues.MOST_AHEAD]
 *    ahead (further, a clock that was wrong, passed over): its [Limited]'s words, a wait (the kind's
 *    [PhoneKinds.Kind.pauses]), no request;
 * 4. on a metered network ([metered]) with no `--metered-ok`: "55 MB to download: waiting for your go-ahead in
 *    Settings (a metered network)", the catalogues' stop and words (the kind's [PhoneKinds.Kind.otherwise], a wait:
 *    nothing starts it again on Wi-Fi by itself); asked again with `--metered-ok` (the go-ahead, a job of its own
 *    key, [GO]), downloaded whatever the network;
 * 5. the lookups queued meanwhile let go first (JobContext.yieldToQueued, holding no write: the download takes a
 *    minute), then [ModelsSource.fetch], saying "Asking GitHub for the chord models…", "Downloading the chord models ·
 *    21 of 55 MB" (its done and total as the stage's progress too) and, its last byte in, "Checking the chord
 *    models…", at most once a second of [ticks] within a step (Paced); then the lookups queued as it came let go
 *    first again (never between its requests: a connection held open while a lookup runs);
 * 6. the folder judged again ([ModelFiles.installed]), then kv [INSTALLED] written, and "Chord models ready · 55 MB".
 *
 * A [Limited] anywhere keeps its time in kv [NOT_BEFORE] (a database that fails there passed over, as the catalogues'
 * do: the wait is said all the same) and ends the job as a wait in its own words (where the catalogues' job fails). Any other
 * refusal (a [CatalogueError] or core.models' ModelsError: no release, no room, a digest that differs, the storage)
 * fails it "Not downloaded: WHY", the command's exit 1. Each run asks GitHub with caracole's user agent as the phone's
 * settings say it then (PhoneConfig.read). [clock], [metered] and [ticks] are the app's (a test's).
 */
class ModelsRunner(
    val parts: PhoneParts,
    private val source: ModelsSource?,
    private val clock: () -> Instant = Instant::now,
    private val metered: () -> Boolean = { false },
    private val ticks: () -> Long = System::nanoTime,
) : CommandRunner {
    /** This build's pins, or null for one that carries no models (the release's). */
    private val pins: Pins? by lazy { source?.pins?.invoke() }

    /** Held by a run and by [remove], so that the files are never deleted under a download. */
    private val busy = Mutex()

    /** Read by each hearing ([holding]), written by [remove]: the files are never deleted under a hearing. */
    private val files = ReentrantReadWriteLock()

    /** [block] (a hearing: the audio job's `ChordModels.hear`, which asks [ready] again first) run with the models'
     * files held, so that [remove] is refused while it runs: the audio job's key ([USES]) covers the job while the
     * queue lists it, this the hearing itself, whatever remove looked at before (a job queued as it looked). */
    fun <T> holding(block: () -> T): T = files.read(block)

    /** The names the models go by in an auto sheet's `raw["models"]` (models.json's), none in a build that carries
     * none: a sheet's maker (AudioRunner). */
    fun names(): Map<String, String> = pins?.models.orEmpty()

    /** The bytes a download of this build's models asks for (Pins.downloaded: what Settings' row and its question
     * say, "Not downloaded · 55 MB", "Ready · 55 MB on the phone"; BTC's graph, the app's own, never counted), none in
     * a build that carries none. */
    fun bytes(): Long? = pins?.downloaded

    /** The bytes a download would ask for now (ModelsSource.toDownload: a file a failed fetch kept whole, and the
     * app's own graph, never counted), what the metered wait and Settings' questions say; none in a build that
     * carries none. It hashes the files it finds: never on the main thread. */
    fun toDownload(): Long? {
        val pins = pins ?: return null
        return source?.toDownload(pins.folder(parts.stateDir))
    }

    /** The folder the models are installed in, `stateDir/models/c<contract>/`; null in a build that carries none. */
    fun folder(): File? = pins?.folder(parts.stateDir)

    /** Null when the models are installed whole, else why not, in words: the one answer to "are the chord models
     * here" (the files judge, by their manifest and a stat of each, never kv [INSTALLED], which a restore keeps and
     * which may outlive them). */
    fun ready(): String? {
        val pins = pins ?: return NOT_CARRIED
        return ModelFiles.installed(pins.folder(parts.stateDir), pins)
    }

    /** What a download killed in its middle left beside the folder (ModelFiles.sweep), deleted: called as the phone
     * starts, while no job runs. With no folder there, nothing: an install a kill left aside between its two renames
     * (`.old`) is the next download's to put back, never 55 MB to download again. */
    fun sweep() {
        val folder = folder() ?: return
        if (folder.isDirectory) ModelFiles.sweep(folder)
    }

    /**
     * The chord models removed (Settings' Remove): `stateDir/models/` whole (every contract's folder, the files kept
     * for a next try, what a fetch cut off left), no link followed, then kv [INSTALLED]; kv [NOT_BEFORE], GitHub's
     * time, kept. Null once removed (or nothing there); [IN_USE] while a job that uses the models ([USES]: their
     * download, a sheet from an audio file) waits or runs, or a hearing holds them ([holding]), nothing deleted;
     * [NOT_CARRIED] in a build that carries none; the storage's failure in words (what is left, and the record,
     * kept).
     */
    fun remove(): String? {
        if (pins == null) return NOT_CARRIED
        if (inUse()) return IN_USE
        if (!busy.tryLock()) return IN_USE
        val write = files.writeLock()
        if (!write.tryLock()) {
            busy.unlock()
            return IN_USE  // a hearing holds them
        }
        try {
            if (inUse()) return IN_USE
            try {
                deleteTree(File(parts.stateDir, ModelFiles.FOLDER).toPath())
            } catch (e: IOException) {
                return "The phone's storage failed: ${e.message ?: e.javaClass.simpleName}."  // the record left
            }
            parts.database.writeBlocking { db -> db.kvDelete(INSTALLED) }
            return null
        } finally {
            write.unlock()
            busy.unlock()
        }
    }

    private fun inUse(): Boolean = parts.queue.snapshot().any { job -> job.active && USES.any { job.key.startsWith(it) } }

    /** The job the app queues (Settings' Download): one at a time; with [meteredOk], the owner's go-ahead to download on
     * a metered network, a job of its own key ([GO]), so that a plain job waiting never answers it. */
    fun spec(meteredOk: Boolean = false): JobSpec {
        val kind = PhoneKinds.MODELS
        val args = if (meteredOk) listOf(COMMAND, METERED_OK) else listOf(COMMAND)
        return JobSpec(title = kind.title, key = kind.key + (if (meteredOk) GO else ""), kind = kind.kind,
                       stages = listOf(kind.stage), display = kind.display, join = false,
                       run = { context -> run(args, context) })
    }

    override suspend fun run(args: List<String>, context: JobContext) {
        val meteredOk = when (args) {
            listOf(COMMAND) -> false
            listOf(COMMAND, METERED_OK) -> true
            else -> throw CommandExit(2, "Usage: caracole models [$METERED_OK]")
        }
        val pins = pins
        if (pins == null || source == null) fail(context, NOT_CARRIED)
        withContext(Dispatchers.IO) {
            busy.withLock {
                try {
                    download(pins, source, meteredOk, context)
                } catch (e: Limited) {
                    quietly { parts.database.write { db -> db.kvSet(NOT_BEFORE, Stamps.of(e.until)) } }
                    context.stage(STAGE, "done", e.message.orEmpty())
                } catch (e: CatalogueError) {
                    fail(context, e.message.orEmpty())
                }
            }
        }
    }

    private suspend fun download(pins: Pins, source: ModelsSource, meteredOk: Boolean, context: JobContext) {
        val kind = PhoneKinds.MODELS
        val folder = pins.folder(parts.stateDir)
        val paced = Paced({ words -> context.stage(STAGE, "running", PhoneKinds.fill(kind.running, "doing" to words)) },
                          ticks = ticks)
        context.stage(STAGE, "running")
        if (ModelFiles.installed(folder, pins) == null) return installed(pins, context)
        val (until, agent) = parts.database.read { db ->
            Catalogues.notBefore(db, NOT_BEFORE) to PhoneConfig.read(db).userAgent
        }
        Catalogues.holdBack(until, clock())
        if (metered() && !meteredOk) {
            val asked = source.toDownload(folder)  // what is left: a file a failed fetch kept whole is no download
            context.stage(STAGE, "done", PhoneKinds.fill(kind.otherwise!!, "size" to Sizes.size(asked)))
            return
        }
        context.yieldToQueued()  // the lookups queued as the job began go first: the download takes a minute
        paced.say(ASKING)
        source.fetch(Http(userAgent = agent), folder) { got, total ->
            context.progress(STAGE, got, total)
            if (got >= total) paced.say(CHECKING) else paced.say(downloading(got, total), DOWNLOADING)
        }
        paced.flush()
        context.progress(STAGE, null, null)
        context.yieldToQueued()  // and those queued as it came
        ModelFiles.installed(folder, pins)?.let { why -> fail(context, why) }
        installed(pins, context)
    }

    /** kv [INSTALLED] written where it is lost or another install's, and the kind's done line. */
    private suspend fun installed(pins: Pins, context: JobContext) {
        val names = JsonArray(pins.files.map { JsonPrimitive(it.name) })
        parts.database.write { db ->
            val record = db.kvGet(INSTALLED)?.let { runCatching { PyJson.loads(it) as? JsonObject }.getOrNull() }
            val same = record != null && record["contract"] == JsonPrimitive(pins.contract) &&
                record["files"] == names && record["bytes"] == JsonPrimitive(pins.bytes)
            if (!same) {
                db.kvSetJson(INSTALLED, JsonObject(linkedMapOf(
                    "contract" to JsonPrimitive(pins.contract), "files" to names,
                    "bytes" to JsonPrimitive(pins.bytes), "when" to JsonPrimitive(Stamps.of(clock())),
                )))
            }
        }
        context.stage(STAGE, "done", PhoneKinds.fill(PhoneKinds.MODELS.done, "size" to Sizes.size(pins.downloaded)))
    }

    /** [block] run, a failure of it passed over, but a cancellation's (CataloguesRunner's). */
    private inline fun quietly(block: () -> Unit) {
        try {
            block()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            // nothing more to do: the record keeps a request from being sent too soon, the wait is said all the same
        }
    }

    /** The job's stage failed with the kind's words for [why], and the command with them. */
    private fun fail(context: JobContext, why: String): Nothing {
        val line = PhoneKinds.fill(PhoneKinds.MODELS.failed, "why" to why)
        context.stage(STAGE, "failed", line)
        throw CommandExit(1, line)
    }

    companion object {
        const val COMMAND = "models"
        const val METERED_OK = "--metered-ok"

        /** The go-ahead's key after the kind's (`models:go`). */
        const val GO = "go"

        /** kv: what was installed and when, `{"contract": 1, "files": [names], "bytes": N, "when": "…Z"}` (kv_set_json's
         * text), written once the folder is judged whole; a note (a restore keeps it, as the phone's own), never the
         * judge of whether the models are here: [ready]. */
        const val INSTALLED = "models:installed"

        /** kv: when GitHub said to ask again (its `x-ratelimit-reset`), so the job doesn't ask before. */
        const val NOT_BEFORE = "models:not-before"

        /** The keys of the jobs that use the models, while one of which waits or runs [remove] is refused: their
         * download, and a sheet from an audio file (AudioRunner's, `audio:<song key>`). A remove between a job's
         * queueing and its hearing is closed by [holding]: the hearing holds the files and asks [ready] again under
         * them (the job then fails "the chord models aren't downloaded …", nothing kept but its audio). */
        val USES: List<String> = listOf(PhoneKinds.MODELS.key, JobCommands.AUDIO_SHEET)

        /** This build's words for a build with no models (core.models' ModelsNotCarried's): asked of [ModelFiles.carried]
         * where the phone is assembled, never caught. */
        const val NOT_CARRIED = "This build carries no chord models."

        /** [remove] while a job that uses the models waits or runs. */
        const val IN_USE = "The chord models are in use now (their download, or a sheet being made from them): " +
            "remove them once that's done."

        private const val STAGE = "models"
        private const val ASKING = "Asking GitHub for the chord models…"
        private const val CHECKING = "Checking the chord models…"

        /** The download's step, whatever its count says (Paced). */
        private const val DOWNLOADING = "downloading"

        /** "Downloading the chord models · 21 of 55 MB". */
        fun downloading(got: Long, total: Long): String = "Downloading the chord models · " + Sizes.of(got, total)

        /** [root] and everything under it deleted, no link followed (a link deleted as itself); nothing for no
         * [root]. */
        internal fun deleteTree(root: Path) {
            if (!Files.exists(root, LinkOption.NOFOLLOW_LINKS)) return
            Files.walkFileTree(root, object : SimpleFileVisitor<Path>() {
                override fun visitFile(file: Path, attrs: BasicFileAttributes): FileVisitResult {
                    Files.delete(file)
                    return FileVisitResult.CONTINUE
                }

                override fun postVisitDirectory(dir: Path, exc: IOException?): FileVisitResult {
                    if (exc != null) throw exc
                    Files.delete(dir)
                    return FileVisitResult.CONTINUE
                }
            })
        }
    }
}
