package io.github.danielhp95.caracole.ml

import android.app.ActivityManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Message
import android.os.Messenger
import android.os.PowerManager
import android.os.RemoteException
import android.util.Log
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
import java.io.IOException
import java.io.RandomAccessFile
import java.nio.channels.OverlappingFileLockException
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap
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
 * Around it ([guarded]): the battery floor first (under [HeatRules.LOW_BATTERY] % and not charging, refused in
 * [HeatRules.CHARGE_FIRST]'s words before any process starts), then the one turn of the app's processes ([turn], a
 * lock on `files/chords.lock`: the app's jobs and the debug build's Chords bench bind the same `:ml`, so a hearing
 * while another goes on is refused in [BUSY]'s words), and the wake lock only while the hearing runs, let go on
 * every path; whatever the hearing throws (`waiting`'s own exception among it) goes on as itself.
 *
 * [ready]: the phone's own reasons first ([device]: the app's [deviceProblem], the design's §8.1; none by default, the
 * bench's and the tests'), then the models' files: [installed], the app's judge (ModelFiles.installed of the folder
 * the models' job installs, `stateDir/models/c<contract>/`, ModelsRunner.ready's one answer), or with none the three
 * files the hearing runs on ([OrtModels.BTC_GRAPH], [OrtModels.BTC_WEIGHTS] beside it, [OrtModels.BEATS_FP16]) in
 * [models], each of the size and SHA-256 models.json pins (`:ml`'s resource), each file's answer kept while its size
 * and time stay (the bench's folder, and `/data/local/tmp/caracole-models` that device-test.sh `--ml` pushes). [hear]
 * asks it first. [forgetHeard] (the app's): the song's checkpoints removed by [forget], once the job kept the sheet
 * heard of it, the process gone; a hearing that fails, or a keep after it, keeps them, for Try again to go on from, and
 * [sweepOld] takes those a day old at the app's start. [gauge] reads the battery ([Heat]).
 */
class MlChordModels(
    context: Context, private val models: File, private val work: File, private val threads: Int = 0,
    private val installed: (() -> String?)? = null, private val device: () -> String? = { null },
    private val forgetHeard: Boolean = false, private val gauge: HeatGauge = Heat(context),
) : ChordModels {
    private val app = context.applicationContext

    override val runtime: String get() = OrtModels.RUNTIME

    /** The `:ml` process's peak RSS, in kB, while it heard the last song (`VmHWM`); null before one was heard. */
    @Volatile var lastPeakKb: Long? = null
        private set

    /** What the `:ml` process's RSS was made of at its highest while it heard the last song: `RssAnon` and `RssFile`,
     * in kB (null where the process gave none). */
    @Volatile var lastPeakSplitKb: Pair<Long, Long>? = null
        private set

    /** The checkpoints' folder of each audio file heard whole here, by its path, until [forget] lets it go (a job
     * refused after its hearing never does: its entry stays for the process's life). */
    private val heardIn = ConcurrentHashMap<String, File>()

    /** The last song's stages that ran, each with its time in ns, in their order (Pipeline's [Pipeline.STAGES]). */
    @Volatile var lastStagesNanos: Map<String, Long> = emptyMap()
        private set

    override fun phoneProblem(): String? = device()

    override fun ready(): String? {
        device()?.let { return it }
        val judge = installed ?: return pinned()
        return judge()
    }

    /** The three files in [models] as models.json pins them, each hashed once a process while its size and time
     * stay. */
    private fun pinned(): String? = synchronized(checked) {
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
        return guarded(gauge, { turn(File(app.filesDir, TURN)) }, AndroidWake(app)) { wake ->
            heard(audio, onStep, waiting, wake)
        }
    }

    private fun heard(audio: File, onStep: (String) -> Unit, waiting: () -> Unit, lock: Wake): Heard {
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
                    if (++quiet % 60 == 0) lock.hold(WAKE_MS)
                    waiting()
                    continue
                }
                when (m.what) {
                    MlProtocol.STEP -> {
                        lock.hold(WAKE_MS)
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
                        val file = File(m.data.getString(MlProtocol.HEARD)!!)
                        return Heard.read(file.readText(Charsets.UTF_8)).also {
                            file.parentFile?.let { folder -> heardIn[audio.path] = folder }
                        }
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
        }
    }

    /** [audio]'s checkpoints, heard whole here, deleted (the app's: [forgetHeard]) once the job kept its sheet and the
     * process is gone, so nothing writes there after ([forgotten]). Never throws, as ChordModels says: it runs in the
     * chords stage's `finally`, and what letting go throws is logged, the folder left for [sweepOld]. A job refused
     * after a whole hearing (the song got a human sheet meanwhile) keeps no sheet and never calls it: its folder waits
     * for the day-old sweep, and its entry in [heardIn] stays for the process's life. */
    override fun forget(audio: File) {
        val folder = heardIn.remove(audio.path) ?: return
        if (forgetHeard) forgotten(folder, work, { Log.w(TAG, "checkpoints of ${audio.name} kept", it) }, ::awaitEnded)
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

    /** A partial wake lock, as a hearing holds it ([guarded]); Android's is [AndroidWake]. */
    interface Wake {
        /** Held, for [ms] from now (again: [ms] from now). */
        fun hold(ms: Long)

        fun release()
    }

    /** PowerManager's partial wake lock [WAKE_TAG], not reference counted. */
    private class AndroidWake(context: Context) : Wake {
        private val lock = context.getSystemService(PowerManager::class.java)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, WAKE_TAG).apply { setReferenceCounted(false) }

        override fun hold(ms: Long) = lock.acquire(ms)

        override fun release() {
            if (lock.isHeld) lock.release()
        }
    }

    companion object {
        /** The one turn of the app's processes to hear a song (the app's jobs, the debug build's bench), its lock's
         * file in the app's files. */
        const val TURN = "chords.lock"

        /** Another hearing holds the turn: a sheet being made, or (a debug build's) the Chords bench's, which the
         * words leave out, as the release has no bench. */
        const val BUSY = "the chord models are hearing another song; try again once it's done"

        /**
         * [block], the hearing, run: refused first under the battery floor ([HeatRules.start] over [gauge]: nothing
         * taken), then once another holds the turn ([take] null: [BUSY]); else with the turn held and [wake] held for
         * [WAKE_MS] (the hearing holds it again at each step and each minute), both let go however [block] ends, and
         * whatever it throws thrown as itself.
         */
        internal fun <T> guarded(gauge: HeatGauge, take: () -> AutoCloseable?, wake: Wake, block: (Wake) -> T): T {
            HeatRules.start(gauge.read())?.let { throw ChordsUnavailable(it) }
            val turn = take() ?: throw ChordsUnavailable(BUSY)
            try {
                wake.hold(WAKE_MS)
                try {
                    return block(wake)
                } finally {
                    wake.release()
                }
            } finally {
                turn.close()
            }
        }

        /** The turn of [file]'s lock, taken (closed to give it back), or null while another holds it: another process
         * (an flock, which its end gives back), or another hearing of this process. */
        internal fun turn(file: File): AutoCloseable? {
            val channel = try {
                file.parentFile?.mkdirs()
                RandomAccessFile(file, "rw").channel
            } catch (e: IOException) {
                throw ChordsUnavailable("$CANT_TAKE_TURN (${e.message})", e)
            }
            val lock = try {
                channel.tryLock()
            } catch (e: OverlappingFileLockException) {
                null
            } catch (e: IOException) {
                channel.close()
                throw ChordsUnavailable("$CANT_TAKE_TURN (${e.message})", e)
            }
            if (lock == null) {
                channel.close()
                return null
            }
            return AutoCloseable {
                try {
                    lock.release()
                } finally {
                    channel.close()
                }
            }
        }

        private const val CANT_TAKE_TURN = "the chord models' turn can't be taken"

        /** The phone's reasons not to hear here (the design's §8.1), the first that holds: Android before 13 (API 33),
         * no processor the app carries the libraries of ([carried]: [ABIS] in a debug build, arm64-v8a alone in the
         * release), under [LEAST_MEMORY] of memory; null for none. */
        fun deviceProblem(sdk: Int, totalMem: Long, abis: List<String>, carried: Set<String> = ABIS): String? = when {
            sdk < LEAST_SDK -> "chords from audio need Android 13 or later"
            abis.none { it in carried } -> "no chord models for this phone's processor"
            totalMem < LEAST_MEMORY -> "chords from audio need 6 GB of memory or more"
            else -> null
        }

        /** [deviceProblem] of this phone: its Android, its ABIs against those the app [carried] the libraries of, its
         * memory as ActivityManager tells it. */
        fun deviceProblem(context: Context, carried: Set<String> = ABIS): String? {
            val memory = ActivityManager.MemoryInfo()
            context.getSystemService(ActivityManager::class.java).getMemoryInfo(memory)
            return deviceProblem(Build.VERSION.SDK_INT, memory.totalMem, Build.SUPPORTED_ABIS.toList(), carried)
        }

        const val LEAST_SDK = 33

        /** "6 GB of memory": a phone sold with 6 GB tells about 5.5 GB (`MemoryInfo.totalMem`, the kernel's and the
         * modem's carve-outs left out), so the floor is 5 GiB. */
        const val LEAST_MEMORY = 5L shl 30

        /** The ABIs a debug build carries the libraries of (app/build.gradle.kts's abiFilters); the release's are
         * arm64-v8a alone (BuildConfig.ML_ABIS). */
        val ABIS = setOf("arm64-v8a", "x86_64")

        const val DAY_MS = 24 * 60 * 60_000L

        /** The log's tag of what [forget] tells. */
        const val TAG = "caracole-ml"

        /** [folder], a song's checkpoints in [work], deleted once [ended] says the process is gone; kept for the
         * start's sweep while it is still ending ([ChordsUnavailable]) or when the wait is interrupted (the thread's
         * flag set again). Whether it went. Anything else it throws (a path that won't resolve, a bug in the wait)
         * is [told] and kept, the folder left: it never throws. */
        internal fun forgotten(folder: File, work: File, told: (Exception) -> Unit = {}, ended: () -> Unit): Boolean =
            try {
                folder.parentFile?.canonicalFile == work.canonicalFile && run {
                    ended()
                    folder.deleteRecursively()
                }
            } catch (e: ChordsUnavailable) {
                false
            } catch (e: InterruptedException) {
                Thread.currentThread().interrupt()
                false
            } catch (e: Exception) {
                told(e)
                false
            }

        /** The songs' checkpoint folders in [work] a hearing last wrote to a day or more before [now] (a killed app's,
         * or one whose job failed and was never tried again), deleted under the hearings' one turn ([turn] of
         * [turnFile], so that no hearing of another process resumes one as it goes); none while a hearing holds it:
         * called at the app's start. Their names. */
        fun sweepOld(work: File, now: Long, turnFile: File): List<String> {
            val held = turn(turnFile) ?: return emptyList()
            held.use {
                val old = work.listFiles().orEmpty().filter { it.isDirectory && now - newest(it) >= DAY_MS }
                    .sortedBy { it.name }
                for (folder in old) folder.deleteRecursively()
                return old.map { it.name }
            }
        }

        /** The newest time of [folder] and its files. */
        private fun newest(folder: File): Long =
            (listOf(folder.lastModified()) + folder.listFiles().orEmpty().map { it.lastModified() }).max()

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
