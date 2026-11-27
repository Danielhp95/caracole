package io.github.danielhp95.caracole.ml

import android.app.ActivityManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Message
import android.os.Messenger
import android.os.PowerManager
import android.os.RemoteException
import io.github.danielhp95.caracole.autochords.AudioUnreadable
import io.github.danielhp95.caracole.autochords.Checkpoints
import io.github.danielhp95.caracole.autochords.ChordModels
import io.github.danielhp95.caracole.autochords.ChordsUnavailable
import io.github.danielhp95.caracole.autochords.Heard
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * The chord models as the app's main process asks them ([ChordModels]): each [hear] binds [MlService] in its process,
 * `:ml` (`BIND_AUTO_CREATE | BIND_IMPORTANT`, so it takes the job's foreground importance), sends it the paths
 * ([MlProtocol]: the audio, [models], the checkpoints' folder [work] (`stateDir/cache/autochords/`), [threads]) and
 * blocks the job's thread on its replies, a poll a second, calling `waiting` at each; a partial wake lock
 * (`caracole:chords`) held meanwhile, its [WAKE_MS] begun again at each step and each minute (a hearing whose client
 * stops answering loses it 10 minutes on). The process dead before it answered (the low-memory killer's doing, on a
 * phone) is [ChordsUnavailable] in [DIED]'s words, the main process untouched, and the next [hear] goes on from the
 * last checkpoint whole; its planned end after an answer (one hearing a process, MlService) is never read so. A
 * [hear] stopped before its answer (`waiting` throwing, its thread interrupted) sends [MlProtocol.CANCEL] and lets
 * go. A bug of caracole's in the process is an IllegalStateException in its words.
 *
 * [ready]: the three files the hearing runs on ([OrtModels.BTC_GRAPH], [OrtModels.BTC_WEIGHTS] beside it,
 * [OrtModels.BEATS_FP16]) in [models], each of the size and SHA-256 models.json pins (`:ml`'s resource), each file's
 * answer kept while its size and time stay; else why not, in words. Where the files come from is a later task's (the
 * models' download); on the emulator they are pushed to `/data/local/tmp/caracole-models` (device-test.sh `--ml`).
 */
class MlChordModels(
    context: Context, private val models: File, private val work: File, private val threads: Int = 0,
) : ChordModels {
    private val app = context.applicationContext

    /** The `:ml` process's peak RSS, in kB, while it heard the last song (`VmHWM`); null before one was heard. */
    @Volatile var lastPeakKb: Long? = null
        private set

    /** What the `:ml` process's RSS was made of at its highest while it heard the last song: `RssAnon` and `RssFile`,
     * in kB (null where the process gave none). */
    @Volatile var lastPeakSplitKb: Pair<Long, Long>? = null
        private set

    /** The last song's stages that ran, each with its time in ns, in their order (Pipeline's [Pipeline.STAGES]). */
    @Volatile var lastStagesNanos: Map<String, Long> = emptyMap()
        private set

    override fun ready(): String? = synchronized(checked) {
        val doc = Json.parseToJsonElement(pins()).jsonObject
        val btc = doc["btc"]!!.jsonObject
        val pins = listOf(btc["graph"]!!, btc["weights"]!!, doc["beats"]!!.jsonObject["fp16"]!!).map { it.jsonObject }
        for (pin in pins) {
            val name = pin["name"]!!.jsonPrimitive.content
            val file = File(models, name)
            if (!file.isFile) return "the chord models aren't on the phone: no $name in $models"
            if (file.length() != pin["bytes"]!!.jsonPrimitive.long) {
                return "$name in $models isn't the file caracole's chords are made with (its size differs)"
            }
            val known = checked[file.path]?.takeIf { it.length == file.length() && it.modified == file.lastModified() }
            val sha = known?.sha256 ?: sha256(file).also {
                checked[file.path] = Checked(file.length(), file.lastModified(), it)
            }
            if (sha != pin["sha256"]!!.jsonPrimitive.content) {
                return "$name in $models isn't the file caracole's chords are made with (its SHA-256 differs)"
            }
        }
        null
    }

    override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard {
        lastPeakKb = null
        lastPeakSplitKb = null
        lastStagesNanos = emptyMap()
        ready()?.let { throw ChordsUnavailable(it) }
        // The process of an earlier hearing ends once its client let go of it: a bind meanwhile could reach it as
        // it goes, so it is let finish first, or the hearing refused in words.
        awaitGone(::mlPid, System::currentTimeMillis, Thread::sleep, waiting)
        val replies = LinkedBlockingQueue<Message>()
        val looper = HandlerThread("caracole-chords-replies").apply { start() }
        val inbox = Messenger(Handler(looper.looper) { m -> replies.put(Message.obtain(m)); true })
        val connected = LinkedBlockingQueue<IBinder>()
        val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName?, service: IBinder?) {
                service?.let(connected::put)
            }
            override fun onServiceDisconnected(name: ComponentName?) = died(replies)
            override fun onBindingDied(name: ComponentName?) = died(replies)
            override fun onNullBinding(name: ComponentName?) = died(replies)
        }
        val lock = app.getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, WAKE_TAG).apply { setReferenceCounted(false) }
        lock.acquire(WAKE_MS)
        var bound = false
        var service: Messenger? = null
        var answered = false
        try {
            bound = app.bindService(Intent(app, MlService::class.java), connection,
                Context.BIND_AUTO_CREATE or Context.BIND_IMPORTANT)
            if (!bound) throw ChordsUnavailable("the chord models' process won't start")
            var binder: IBinder? = null
            for (second in 0 until CONNECT_SECONDS) {
                binder = connected.poll(1, TimeUnit.SECONDS)
                if (binder != null) break
                if (replies.peek()?.what == GONE) throw ChordsUnavailable(DIED)
                waiting()
            }
            binder ?: throw ChordsUnavailable("the chord models' process didn't answer")
            try {
                binder.linkToDeath({ died(replies) }, 0)
                service = Messenger(binder)
                service.send(Message.obtain(null, MlProtocol.HEAR).apply {
                    data = Bundle().apply {
                        putString(MlProtocol.AUDIO, audio.path)
                        putString(MlProtocol.MODELS, models.path)
                        putString(MlProtocol.WORK, work.path)
                        putInt(MlProtocol.THREADS, threads)
                    }
                    replyTo = inbox
                })
            } catch (e: RemoteException) {
                throw ChordsUnavailable(DIED, e)
            }
            var quiet = 0
            while (true) {
                val m = replies.poll(1, TimeUnit.SECONDS)
                if (m == null) {
                    // The wake lock's 10 minutes begin again each minute the models work, and at each step.
                    if (++quiet % 60 == 0) lock.acquire(WAKE_MS)
                    waiting()
                    continue
                }
                when (m.what) {
                    MlProtocol.STEP -> {
                        lock.acquire(WAKE_MS)
                        onStep(m.data.getString(MlProtocol.WORDS)!!)
                    }
                    MlProtocol.DONE -> {
                        answered = true
                        lastPeakKb = m.data.getLong(MlProtocol.PEAK_KB).takeIf { it >= 0 }
                        if (m.data.containsKey(MlProtocol.PEAK_ANON_KB)) lastPeakSplitKb =
                            m.data.getLong(MlProtocol.PEAK_ANON_KB) to m.data.getLong(MlProtocol.PEAK_FILE_KB)
                        val names = m.data.getStringArray(MlProtocol.STAGES).orEmpty()
                        val nanos = m.data.getLongArray(MlProtocol.STAGE_NANOS) ?: LongArray(0)
                        lastStagesNanos = names.zip(nanos.toList()).toMap()
                        return Heard.read(File(m.data.getString(MlProtocol.HEARD)!!).readText(Charsets.UTF_8))
                    }
                    MlProtocol.FAILED -> {
                        answered = true
                        val words = m.data.getString(MlProtocol.WORDS)!!
                        when (m.data.getString(MlProtocol.KIND)) {
                            MlProtocol.AUDIO_KIND -> throw AudioUnreadable(words)
                            MlProtocol.BUG_KIND -> throw IllegalStateException(words)
                            else -> throw ChordsUnavailable(words)
                        }
                    }
                    GONE -> {
                        answered = true
                        throw ChordsUnavailable(DIED)
                    }
                }
            }
        } finally {
            // Stopped before its answer (the job cancelled, its thread interrupted, waiting throwing): the hearing
            // stopped there too, at its next chunk (and by the unbind below, which ends the process once it stops).
            if (!answered) try {
                service?.send(Message.obtain(null, MlProtocol.CANCEL))
            } catch (e: RemoteException) {
                // Gone already.
            }
            if (bound) app.unbindService(connection)
            looper.quitSafely()
            if (lock.isHeld) lock.release()
        }
    }

    /** Waits, as a hearing does before it binds ([awaitGone], bounded by [PROCESS_GONE_MS]), for the `:ml` process of
     * the last hearing to be gone, so that nothing writes to [work] after this returns; [ChordsUnavailable] in
     * [STILL_ENDING]'s words when it outlives the wait. */
    fun awaitEnded() = awaitGone(::mlPid, System::currentTimeMillis, Thread::sleep) {}

    /** Where a hearing of [audio] keeps its checkpoints (its audio hashed: the tests'). */
    fun checkpoints(audio: File): Checkpoints = Checkpoints.of(work, audio)

    private fun died(replies: LinkedBlockingQueue<Message>) = replies.put(Message.obtain(null, GONE))

    private fun pins(): String = MlChordModels::class.java.classLoader!!
        .getResourceAsStream("caracole/autochords/models.json")!!.use { it.readBytes().toString(Charsets.UTF_8) }

    /** The `:ml` process's pid, while one runs. */
    private fun mlPid(): Int? = app.getSystemService(ActivityManager::class.java).runningAppProcesses.orEmpty()
        .firstOrNull { it.processName == app.packageName + MlProtocol.PROCESS_SUFFIX }?.pid

    companion object {
        const val DIED = "the chord models stopped (the phone may have run out of memory); try again"

        /** How long a hearing waits for the process of the one before it to end. */
        const val PROCESS_GONE_MS = 10_000L

        const val STILL_ENDING = "the chord models' process of the last hearing is still ending; try again"

        /** Waits, polling [pid] every 100 ms of [clock] (`waiting` at each), for the last hearing's process to be gone;
         * still there after [PROCESS_GONE_MS], [ChordsUnavailable] in [STILL_ENDING]'s words: a bind then could reach
         * that process as it dies, read as this hearing's death. */
        internal fun awaitGone(pid: () -> Int?, clock: () -> Long, sleep: (Long) -> Unit, waiting: () -> Unit) {
            val gone = clock() + PROCESS_GONE_MS
            while (pid() != null) {
                if (clock() >= gone) throw ChordsUnavailable(STILL_ENDING)
                waiting()
                sleep(100)
            }
        }

        private data class Checked(val length: Long, val modified: Long, val sha256: String)

        /** Each model file's SHA-256 by its path, kept while its size and time stay: every client of the process
         * shares it, so a file is hashed once a process. */
        private val checked = HashMap<String, Checked>()
        const val WAKE_TAG = "caracole:chords"
        const val WAKE_MS = 10 * 60_000L

        /** How long the service may take to bind, in seconds. */
        private const val CONNECT_SECONDS = 30

        /** The client's own word, beside [MlProtocol]'s: the process is gone. */
        private const val GONE = -1

        fun sha256(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val chunk = ByteArray(1 shl 20)
                while (true) {
                    val n = input.read(chunk)
                    if (n < 0) break
                    digest.update(chunk, 0, n)
                }
            }
            return digest.digest().joinToString("") { "%02x".format(it.toInt() and 0xFF) }
        }
    }
}
