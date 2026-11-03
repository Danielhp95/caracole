package io.github.danielhp95.caracole

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.ForegroundInfo
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import io.github.danielhp95.caracole.core.sync.PeerClient
import io.github.danielhp95.caracole.mirror.Http
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.mirror.SyncError
import io.github.danielhp95.caracole.server.jobs.Job
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runInterruptible
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.security.SecureRandom

/** Why an index can't be imported: said as it is, on the Settings screen. */
class IndexImportError(message: String) : Exception(message)

/**
 * The computer's site indexes brought to the phone, so its search works with the computer off: a `caracole index
 * export` file, fetched from caracole serve (`GET /api/peer/index`, [fromComputer]) or picked among the phone's files
 * ([fromFile]), copied into `files/state/cache/` and merged by the phone's caracole as a job of its queue
 * (`Phone.importIndex`), so the merge never writes beside a sync. An [IndexImportWorker] does it, in the foreground,
 * its notification saying how far it is; the Settings screen shows [running], then the outcome kept in [Settings].
 */
object IndexImports {
    private const val WORK = "caracole-index-import"
    internal const val SOURCE = "source"
    internal const val COMPUTER = "computer"
    internal const val PICKED = "picked"
    private const val INDEX = "/api/peer/index"
    private val SQLITE = "SQLite format 3\u0000".toByteArray(Charsets.US_ASCII)
    private val random = SecureRandom()

    /** What an import under way is doing ("Downloading the index: 12 MB of 400 MB"), or null when none is. */
    val running = MutableStateFlow<String?>(null)

    /** One import asked for at a time: the check that none is under way, and the work queued, together. */
    private val starting = Mutex()

    /** Imports the index of the computer at the address in Settings; false while an import is under way already. */
    suspend fun fromComputer(context: Context): Boolean = enqueue(context, workDataOf(SOURCE to COMPUTER))

    /** Imports the export the user picked ([uri], a document whose read permission the app keeps until then); false
     * while an import is under way already, the caller then giving that permission back. */
    suspend fun fromFile(context: Context, uri: Uri): Boolean =
        enqueue(context, workDataOf(SOURCE to PICKED, PICKED to uri.toString()))

    /** The import queued, unless one is under way already (unfinished work of [WORK], which KEEP would leave as it is
     * and drop this one without a word). */
    private suspend fun enqueue(context: Context, input: androidx.work.Data): Boolean = withContext(Dispatchers.IO) {
        starting.withLock {
            val work = WorkManager.getInstance(context)
            if (work.getWorkInfosForUniqueWork(WORK).get().any { !it.state.isFinished }) return@withLock false
            val said = context.getString(R.string.import_starting)
            running.compareAndSet(null, said)
            try {
                work.enqueueUniqueWork(WORK, ExistingWorkPolicy.KEEP,
                    OneTimeWorkRequestBuilder<IndexImportWorker>().setInputData(input).build()).result.get()
            } catch (e: Throwable) {
                running.compareAndSet(said, null)
                throw e
            }
            true
        }
    }

    /**
     * The index of the computer at [address] into a file of its own in [dir]: written under a temporary name and given
     * its own once whole and an SQLite file, so nothing is left of one that failed. The computer makes its export
     * whole before it sends a byte, so a read waits as long as the sync's own fetch of it does
     * ([PeerClient.INDEX_TIMEOUT_MS]); a refusal says the computer's own words. [progress] hears the bytes so far and
     * the length the computer said (-1 when it said none); [stopped] is asked after each chunk.
     */
    fun download(http: Http, address: ServerAddress, dir: File, stopped: () -> Boolean = { false },
                 progress: (Long, Long) -> Unit = { _, _ -> }): File =
        http.get(address, address.resolve(INDEX), readTimeoutMs = PeerClient.INDEX_TIMEOUT_MS) { answer ->
            when {
                answer.status == 404 -> throw IndexImportError(
                    "caracole at $address gives no index ($INDEX): the phone needs a newer caracole there.")
                answer.status != 200 -> throw IndexImportError(
                    "caracole at $address answered HTTP ${answer.status} for its index" +
                        (refusal(answer.body)?.let { ": $it" } ?: "."))
            }
            write(answer.body, dir, "$address", stopped) { done -> progress(done, answer.contentLength) }
        }

    /** The export in [input], picked among the phone's files, into a file of its own in [dir], as [download] does. */
    fun copy(input: InputStream, dir: File, stopped: () -> Boolean = { false }): File =
        write(input, dir, "That file", stopped) {}

    /** The computer's own words for a refusal: its JSON answer's `error` (peer_routes.py's), read from at most
     * [REFUSAL_MAX] bytes; null for none. */
    private fun refusal(body: InputStream): String? {
        val out = ByteArrayOutputStream()
        val buffer = ByteArray(8 * 1024)
        while (out.size() <= REFUSAL_MAX) {
            val n = try {
                body.read(buffer)
            } catch (e: IOException) {
                break
            }
            if (n < 0) break
            out.write(buffer, 0, n)
        }
        if (out.size() > REFUSAL_MAX) return null
        return try {
            val said = (Json.parseToJsonElement(out.toString(Charsets.UTF_8.name())) as? JsonObject)?.get("error")
            (said as? JsonPrimitive)?.takeIf { it.isString }?.content?.trim()?.ifEmpty { null }
        } catch (e: IllegalArgumentException) {
            null
        }
    }

    private fun write(input: InputStream, dir: File, what: String, stopped: () -> Boolean, progress: (Long) -> Unit): File {
        dir.mkdirs()
        // An import stopped between its file and its merge left that file: gone a day later.
        val stale = System.currentTimeMillis() - DAY_MS
        dir.listFiles()?.forEach { if (it.name.startsWith("index-") && it.lastModified() < stale) it.delete() }
        val name = "index-" + System.currentTimeMillis() + "-" + token()
        val part = File(dir, "$name.part")
        try {
            var done = 0L
            var told = 0L
            part.outputStream().use { out ->
                val buffer = ByteArray(256 * 1024)
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    out.write(buffer, 0, n)
                    done += n
                    if (stopped()) throw CancellationException("The import was stopped.")
                    val now = System.nanoTime()
                    if (now - told > TELL_NS) {
                        progress(done)
                        told = now
                    }
                }
                out.fd.sync()
            }
            progress(done)
            if (!isSqlite(part)) throw IndexImportError("$what sent something that isn't an index export (caracole index export's file).")
            val file = File(dir, "$name.sqlite")
            if (!part.renameTo(file)) throw IOException("can't name the index ${file.name}")
            return file
        } finally {
            part.delete()
        }
    }

    private fun isSqlite(file: File): Boolean {
        val head = ByteArray(SQLITE.size)
        val read = file.inputStream().use { input ->
            var at = 0
            while (at < head.size) {
                val n = input.read(head, at, head.size - at)
                if (n < 0) break
                at += n
            }
            at
        }
        return read == head.size && head.contentEquals(SQLITE)
    }

    /**
     * How the merge's [job] ended, [at] a time, in the words Settings shows: the sites it merged (its outcome), else
     * what its stage said; or why it failed, as the queue kept it (its last `error: …` line, else its failed stage's
     * words), the export's own path ([file]) said as "the file".
     */
    fun describe(job: Job, at: Long, file: File? = null): Outcome {
        if (job.state == Job.DONE) {
            val outcome = job.outcome
            val changed = (outcome?.get("changed") as? JsonPrimitive)?.booleanOrNull
            val sites = (outcome?.get("sites") as? JsonArray)?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }.orEmpty()
            val said = if (changed == true && sites.isNotEmpty()) sites.joinToString(", ")
                       else job.stages.firstOrNull { it.name == MERGE }?.detail.orEmpty()
            return Outcome(at, true, if (said.isEmpty()) "Indexes imported" else "Indexes imported: $said")
        }
        val said = job.output.lastOrNull { it.startsWith(ERROR_LINE) }?.removePrefix(ERROR_LINE)
            ?: job.stages.firstOrNull { it.state == Job.FAILED }?.detail
        val why = said?.trim()?.ifEmpty { null }?.let { text -> file?.let { text.replace(it.path, "the file") } ?: text }
        return Outcome(at, false, "The import failed: " + (why ?: job.state))
    }

    /** "Indexes imported: merged (3 min ago)", or what the last import said, or that none ran yet. */
    fun line(context: Context, outcome: Outcome?, now: Long = System.currentTimeMillis()): String =
        if (outcome == null) context.getString(R.string.never_imported) else "${outcome.text} (${Syncs.ago(now - outcome.at)})"

    private fun token(): String = ByteArray(4).also { random.nextBytes(it) }.joinToString("") { "%02x".format(it) }

    private const val TELL_NS = 500_000_000L
    private const val DAY_MS = 24 * 60 * 60 * 1000L
    private const val REFUSAL_MAX = 64 * 1024
    private const val MERGE = "merge"
    /** How the phone's queue says what a failed job threw: its last line of output (JobQueue). */
    private const val ERROR_LINE = "error: "
}

/**
 * An index import ([IndexImports]): the file fetched from the computer or copied from the one picked, then
 * `Phone.importIndex` and its job awaited, in the foreground (a data sync, its notification saying how far it is).
 * The outcome is kept in [Settings.lastImport]; a failed import waits to be asked again.
 */
class IndexImportWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val context = applicationContext
        val settings = Settings(context)
        val outcome = try {
            say(context.getString(R.string.import_starting))
            // Interruptible, and asked after each chunk: a stopped worker stops its download or its copy.
            val file = runInterruptible(Dispatchers.IO) { fetch(settings) }
            say(context.getString(R.string.import_merging))
            val phone = withContext(Dispatchers.IO) { Caracole.phone(context) }
            val job = try {
                phone.importIndex(file)
            } catch (e: Throwable) {
                file.delete()
                throw e
            }
            val done = phone.queue.await(job.id)
            IndexImports.describe(done, System.currentTimeMillis(), file)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Throwable) {
            // Anything, an Error among them (a native library that won't load, say): a failed outcome kept and
            // shown, never a worker that dies with nothing said.
            Outcome(System.currentTimeMillis(), false, "The import failed: " + said(e))
        } finally {
            IndexImports.running.value = null
        }
        settings.lastImport = outcome
        return Result.success()
    }

    override suspend fun getForegroundInfo(): ForegroundInfo =
        foreground(notification(applicationContext.getString(R.string.import_starting), null))

    /** The export to merge, in the cache: downloaded from the computer, or copied from the document picked. */
    private fun fetch(settings: Settings): File {
        val cache = Caracole.cacheDir(applicationContext)
        return when (inputData.getString(IndexImports.SOURCE)) {
            IndexImports.COMPUTER -> {
                val address = ServerAddress.parse(settings.server)
                IndexImports.download(Caracole.http(), address, cache, stopped = { isStopped }) { done, total ->
                    val text = if (total > 0) applicationContext.getString(R.string.import_downloading_of,
                        Syncs.size(applicationContext, done), Syncs.size(applicationContext, total))
                    else applicationContext.getString(R.string.import_downloading, Syncs.size(applicationContext, done))
                    update(text, if (total > 0) (done * 100 / total).toInt() else null)
                }
            }
            IndexImports.PICKED -> {
                val uri = Uri.parse(inputData.getString(IndexImports.PICKED) ?: throw IndexImportError("No file was picked."))
                val resolver = applicationContext.contentResolver
                try {
                    val input = resolver.openInputStream(uri) ?: throw IndexImportError("That file can't be read.")
                    update(applicationContext.getString(R.string.import_copying), null)
                    input.use { IndexImports.copy(it, cache) { isStopped } }
                } finally {
                    try {
                        resolver.releasePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    } catch (e: SecurityException) {
                        // It wasn't kept: nothing to give back.
                    }
                }
            }
            else -> throw IndexImportError("Nothing to import.")
        }
    }

    private suspend fun say(text: String) {
        IndexImports.running.value = text
        try {
            setForeground(foreground(notification(text, null)))
        } catch (e: IllegalStateException) {
            // Android refused a foreground service just now (the app went to the background): the import goes on
            // as plain work, which WorkManager may stop and run again later.
        }
    }

    /** The notification again, as the download goes on (Settings' line too). */
    private fun update(text: String, percent: Int?) {
        IndexImports.running.value = text
        applicationContext.getSystemService(NotificationManager::class.java)?.notify(NOTIFICATION, notification(text, percent))
    }

    private fun foreground(notification: android.app.Notification): ForegroundInfo =
        if (Build.VERSION.SDK_INT >= 29) ForegroundInfo(NOTIFICATION, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC)
        else ForegroundInfo(NOTIFICATION, notification)

    private fun notification(text: String, percent: Int?): android.app.Notification {
        val context = applicationContext
        Notifications.channel(context)
        val settings = PendingIntent.getActivity(context, 0, Intent(context, SettingsActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return NotificationCompat.Builder(context, Notifications.JOBS)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle(context.getString(R.string.import_title))
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(settings)
            .setProgress(100, percent ?: 0, percent == null)
            .build()
    }

    private fun said(e: Throwable): String = when (e) {
        is IndexImportError -> e.message.orEmpty()
        else -> SyncError.of(e).let { it.message ?: it.javaClass.simpleName }
    }

    private companion object {
        const val NOTIFICATION = 2
    }
}

/** The app's notifications: one channel, for the work it does in the foreground (an index import). */
object Notifications {
    const val JOBS = "jobs"

    fun channel(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(JOBS) != null) return
        manager.createNotificationChannel(
            NotificationChannel(JOBS, context.getString(R.string.jobs_channel), NotificationManager.IMPORTANCE_LOW))
    }
}
