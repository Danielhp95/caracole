package io.github.danielhp95.caracole.ml

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
 * (`caracole:chords`, [WAKE_MS] at most) held meanwhile. The process dead before it answered (the low-memory killer's
 * doing, on a phone) is [ChordsUnavailable] in [DIED]'s words, the main process untouched, and the next [hear] goes on
 * from the last checkpoint whole.
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

    private data class Checked(val length: Long, val modified: Long, val sha256: String)
    private val checked = HashMap<String, Checked>()

    @Synchronized override fun ready(): String? {
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
        return null
    }

    override fun hear(audio: File, onStep: (String) -> Unit, waiting: () -> Unit): Heard {
        ready()?.let { throw ChordsUnavailable(it) }
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
                Messenger(binder).send(Message.obtain(null, MlProtocol.HEAR).apply {
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
            while (true) {
                val m = replies.poll(1, TimeUnit.SECONDS)
                if (m == null) {
                    waiting()
                    continue
                }
                when (m.what) {
                    MlProtocol.STEP -> onStep(m.data.getString(MlProtocol.WORDS)!!)
                    MlProtocol.DONE -> {
                        lastPeakKb = m.data.getLong(MlProtocol.PEAK_KB).takeIf { it >= 0 }
                        return Heard.read(File(m.data.getString(MlProtocol.HEARD)!!).readText(Charsets.UTF_8))
                    }
                    MlProtocol.FAILED -> {
                        val words = m.data.getString(MlProtocol.WORDS)!!
                        if (m.data.getString(MlProtocol.KIND) == MlProtocol.AUDIO_KIND) throw AudioUnreadable(words)
                        throw ChordsUnavailable(words)
                    }
                    GONE -> throw ChordsUnavailable(DIED)
                }
            }
        } finally {
            if (bound) app.unbindService(connection)
            looper.quitSafely()
            if (lock.isHeld) lock.release()
        }
    }

    /** Where a hearing of [audio] keeps its checkpoints. */
    fun checkpoints(audio: File): Checkpoints = Checkpoints.of(work, audio)

    private fun died(replies: LinkedBlockingQueue<Message>) = replies.put(Message.obtain(null, GONE))

    private fun pins(): String = MlChordModels::class.java.classLoader!!
        .getResourceAsStream("caracole/autochords/models.json")!!.use { it.readBytes().toString(Charsets.UTF_8) }

    companion object {
        const val DIED = "the chord models stopped (the phone may have run out of memory); try again"
        const val WAKE_TAG = "caracole:chords"
        const val WAKE_MS = 10 * 60_000L

        /** How long the service may take to bind, in seconds. */
        private const val CONNECT_SECONDS = 30

        /** The client's own word, beside [MlProtocol]'s: the process is gone. */
        private const val GONE = -1

        internal fun sha256(file: File): String {
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
