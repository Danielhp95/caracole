package io.github.danielhp95.caracole.ml

import android.app.Service
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Message
import android.os.Messenger
import android.os.Process
import android.os.RemoteException
import android.system.ErrnoException
import android.system.Os
import android.system.OsConstants
import io.github.danielhp95.caracole.autochords.AudioUnreadable
import io.github.danielhp95.caracole.autochords.Checkpoints
import io.github.danielhp95.caracole.autochords.ChordsUnavailable
import java.io.File
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * What [MlService] and [MlChordModels] say to each other (the design's §3.3), over a [Messenger]: a request
 * [HEAR] (`replyTo` its client's messenger) of paths in the app's own storage, which both processes read ([AUDIO],
 * [MODELS], [WORK], and [THREADS], at most so many, 0 for the heat's choice), or [CANCEL] of the hearing under way;
 * then the replies [STEP] (a step's or a wait's words, [WORDS]), and one of [DONE] (the heard file's path, [HEARD],
 * the process's peak RSS while it heard, [PEAK_KB], its anonymous and file-backed parts at the highest RSS a look
 * every 200 ms saw ([PEAK_ANON_KB], [PEAK_FILE_KB]: `RssAnon`, `RssFile`), and each stage that ran with its time,
 * [STAGES] and [STAGE_NANOS], Pipeline's) or [FAILED] ([KIND]: [AUDIO_KIND], [SETUP_KIND] or
 * [BUG_KIND]; and [WORDS]). The binder never carries the audio, nor what was heard.
 */
object MlProtocol {
    const val HEAR = 1
    const val STEP = 2
    const val DONE = 3
    const val FAILED = 4
    const val CANCEL = 5

    const val AUDIO = "audio"
    const val MODELS = "models"
    const val WORK = "work"
    const val THREADS = "threads"
    const val WORDS = "words"
    const val HEARD = "heard"
    const val PEAK_KB = "peak_kb"
    const val PEAK_ANON_KB = "peak_anon_kb"
    const val PEAK_FILE_KB = "peak_file_kb"
    const val STAGES = "stages"
    const val STAGE_NANOS = "stage_nanos"
    const val KIND = "kind"
    const val AUDIO_KIND = "audio"
    const val SETUP_KIND = "setup"
    const val BUG_KIND = "bug"

    /** The `:ml` process's name's end, as the manifest declares it (`android:process`): Caracole.MODELS_PROCESS's,
     * which the app's MlProcessTest holds them to. */
    const val PROCESS_SUFFIX = ":ml"

    /** A failure's kind and words, as the client says them: the known causes in their own words, an out of memory
     * named as such, a full disk ([NO_ROOM]: 30 minutes of 48 kHz stereo decode to about 690 MB) and a file of the
     * hearing's that can't be read, written or moved ([CANT_WRITE]) too, anything else caracole's own bug ("a bug in
     * caracole: …", the computer's staged jobs' words). */
    fun failure(e: Throwable): Pair<String, String> = when (e) {
        is AudioUnreadable -> AUDIO_KIND to (e.message ?: "the audio can't be read")
        is ChordsUnavailable -> SETUP_KIND to (e.message ?: "the chord models can't hear it now")
        is TooHot -> SETUP_KIND to (e.message ?: HeatRules.TOO_HOT)
        is Pipeline.Cancelled -> SETUP_KIND to (e.message ?: "the hearing was stopped")
        is OutOfMemoryError -> SETUP_KIND to OUT_OF_MEMORY
        is IOException -> SETUP_KIND to if (noRoom(e)) "$NO_ROOM (${e.message})" else "$CANT_WRITE: ${e.message}"
        else -> BUG_KIND to "a bug in caracole: $e"
    }

    /** ENOSPC, by its name or its words, in [e] or what caused it. */
    private fun noRoom(e: Throwable): Boolean = generateSequence(e) { it.cause }.take(8)
        .any { "ENOSPC" in it.message.orEmpty() || "No space left" in it.message.orEmpty() }

    const val OUT_OF_MEMORY = "the chord models ran out of memory (OutOfMemoryError); try again"
    const val NO_ROOM = "no room on the phone for the hearing's files: free some space and try again"
    const val CANT_WRITE = "a file of the hearing's can't be read or written"
}

/**
 * The chord models' process, `:ml` (its manifest's `android:process`, not exported, in the release as in debug
 * builds): bound by [MlChordModels], it hears one song ([Pipeline], on a thread of its own), so the models' memory, and a crash or the
 * low-memory killer's end of them, never touch the app's server in the main process, where nothing of this runs. One
 * hearing a process: a second request while one goes on is refused in words, and once its client unbinds (after its
 * answer, or to stop it: a [MlProtocol.CANCEL] too stops it at its next chunk) the process ends as soon as no hearing
 * runs, giving the models' memory back to the phone. Before the hearing the process's peak RSS is reset
 * (`/proc/self/clear_refs`), and its peak said with what was heard.
 */
class MlService : Service() {
    private lateinit var looper: HandlerThread
    private val busy = AtomicBoolean(false)
    private val cancelled = AtomicBoolean(false)
    private val leaving = AtomicBoolean(false)

    override fun onCreate() {
        super.onCreate()
        looper = HandlerThread("caracole-ml").apply { start() }
    }

    override fun onBind(intent: Intent?): IBinder = Messenger(Handler(looper.looper) { message ->
        when (message.what) {
            MlProtocol.HEAR -> hear(Bundle(message.data), message.replyTo)
            MlProtocol.CANCEL -> cancelled.set(true)
        }
        true
    }).binder

    /** Its client gone: the hearing stopped, and the process ended once none runs. */
    override fun onUnbind(intent: Intent?): Boolean {
        cancelled.set(true)
        leaving.set(true)
        if (!busy.get()) end()
        return false
    }

    override fun onDestroy() {
        looper.quitSafely()
        super.onDestroy()
    }

    private fun end() = Process.killProcess(Process.myPid())

    private fun hear(request: Bundle, client: Messenger?) {
        if (client == null) return
        if (!busy.compareAndSet(false, true)) {
            failed(client, MlProtocol.SETUP_KIND, "the chord models are hearing another song")
            return
        }
        // A new hearing's own stop flag; a client that unbound meanwhile (onUnbind, on the main thread, between the
        // compareAndSet and this) set `leaving` too, which this clear never erases: the process ends with no hearing.
        cancelled.set(false)
        if (leaving.get()) {
            busy.set(false)
            end()
            return
        }
        thread(name = "caracole-ml-hearing") {
            try {
                resetPeak()
                val split = RssSplit().apply { start() }
                val work = File(request.getString(MlProtocol.WORK)!!)
                val audio = File(request.getString(MlProtocol.AUDIO)!!)
                val pipeline = Pipeline(File(request.getString(MlProtocol.MODELS)!!), Heat(this),
                    request.getInt(MlProtocol.THREADS, 0), cancelled = cancelled::get, syncFolder = ::syncFolder)
                val stages = mutableListOf<Pair<String, Long>>()
                val result = pipeline.hear(audio, work, { stage, ns -> stages += stage to ns }) { words ->
                    send(client, MlProtocol.STEP, Bundle().apply { putString(MlProtocol.WORDS, words) })
                }
                send(client, MlProtocol.DONE, Bundle().apply {
                    putString(MlProtocol.HEARD, result.points.file(Checkpoints.HEARD).path)
                    putLong(MlProtocol.PEAK_KB, peakKb())
                    split.stop()?.let { (anon, file) ->
                        putLong(MlProtocol.PEAK_ANON_KB, anon)
                        putLong(MlProtocol.PEAK_FILE_KB, file)
                    }
                    putStringArray(MlProtocol.STAGES, stages.map { it.first }.toTypedArray())
                    putLongArray(MlProtocol.STAGE_NANOS, stages.map { it.second }.toLongArray())
                })
            } catch (e: Throwable) {
                val (kind, words) = MlProtocol.failure(e)
                failed(client, kind, words)
            } finally {
                busy.set(false)
                if (leaving.get()) end()
            }
        }
    }

    private fun failed(client: Messenger, kind: String, words: String) =
        send(client, MlProtocol.FAILED, Bundle().apply {
            putString(MlProtocol.KIND, kind)
            putString(MlProtocol.WORDS, words)
        })

    private fun send(client: Messenger, what: Int, data: Bundle) {
        try {
            client.send(Message.obtain(null, what).apply { this.data = data })
        } catch (e: RemoteException) {
            // The client is gone: nothing to tell.
        }
    }

    /** [folder] forced to the disk: Android's FileChannel won't open a folder, its `Os` will (an error quiet). */
    private fun syncFolder(folder: File) {
        try {
            val fd = Os.open(folder.path, OsConstants.O_RDONLY, 0)
            try {
                Os.fsync(fd)
            } finally {
                Os.close(fd)
            }
        } catch (e: ErrnoException) {
            // Not this folder, not here: the rename stands, forced or not.
        }
    }

    /** `RssAnon` and `RssFile` at the highest `VmRSS` seen, a look every 200 ms while the hearing runs: what the peak
     * is made of (the heap's and the models' pages, or the memory-mapped pcm's, file-backed). */
    private class RssSplit {
        @Volatile private var running = true
        private var best: Triple<Long, Long, Long>? = null
        private lateinit var looker: Thread

        fun start() {
            looker = thread(name = "caracole-ml-rss", isDaemon = true) {
                while (running) {
                    take()
                    Thread.sleep(200)
                }
            }
        }

        fun stop(): Pair<Long, Long>? {
            running = false
            take()
            return synchronized(this) { best?.let { it.second to it.third } }
        }

        private fun take() {
            val now = look() ?: return
            synchronized(this) { if (best.let { it == null || now.first > it.first }) best = now }
        }

        private fun look(): Triple<Long, Long, Long>? = try {
            val lines = File("/proc/self/status").readLines()
            fun kb(key: String) = lines.first { it.startsWith("$key:") }.substringAfter(':').trim()
                .removeSuffix("kB").trim().toLong()
            Triple(kb("VmRSS"), kb("RssAnon"), kb("RssFile"))
        } catch (e: Exception) {
            null
        }
    }

    private fun resetPeak() = try {
        File("/proc/self/clear_refs").writeText("5")
    } catch (e: Exception) {
        // A kernel that refuses it: the peak is then the process's whole life's.
    }

    private fun peakKb(): Long = try {
        File("/proc/self/status").readLines().first { it.startsWith("VmHWM:") }.substringAfter(':').trim()
            .removeSuffix("kB").trim().toLong()
    } catch (e: Exception) {
        -1
    }
}
