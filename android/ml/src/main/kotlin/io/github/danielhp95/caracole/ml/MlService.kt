package io.github.danielhp95.caracole.ml

import android.app.Service
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.Message
import android.os.Messenger
import android.os.RemoteException
import io.github.danielhp95.caracole.autochords.AudioUnreadable
import io.github.danielhp95.caracole.autochords.Checkpoints
import io.github.danielhp95.caracole.autochords.ChordsUnavailable
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * What [MlService] and [MlChordModels] say to each other (the design's §3.3), over a [Messenger]: a request
 * [HEAR] (`replyTo` its client's messenger) of paths in the app's own storage, which both processes read ([AUDIO],
 * [MODELS], [WORK], and [THREADS], at most so many, 0 for the heat's choice); then the replies [STEP] (a step's or
 * a wait's words, [WORDS]), and one of [DONE] (the heard file's path, [HEARD], and the process's peak RSS while it
 * heard, [PEAK_KB]) or [FAILED] ([KIND], [AUDIO_KIND] or [SETUP_KIND], and [WORDS]). The binder never carries the
 * audio, nor what was heard.
 */
object MlProtocol {
    const val HEAR = 1
    const val STEP = 2
    const val DONE = 3
    const val FAILED = 4

    const val AUDIO = "audio"
    const val MODELS = "models"
    const val WORK = "work"
    const val THREADS = "threads"
    const val WORDS = "words"
    const val HEARD = "heard"
    const val PEAK_KB = "peak_kb"
    const val KIND = "kind"
    const val AUDIO_KIND = "audio"
    const val SETUP_KIND = "setup"

    /** The `:ml` process's name's end, as the manifest declares it (`android:process`). */
    const val PROCESS_SUFFIX = ":ml"
}

/**
 * The chord models' process, `:ml` (its manifest's `android:process`, debug builds alone, not exported): bound by
 * [MlChordModels], it hears one song at a time ([Pipeline], on a thread of its own), so the models' memory, and a
 * crash or the low-memory killer's end of them, never touch the app's server in the main process, where nothing of
 * this runs. A request while a hearing goes on is refused in words. Before each hearing the process's peak RSS is
 * reset (`/proc/self/clear_refs`), and its peak said with what was heard.
 */
class MlService : Service() {
    private lateinit var looper: HandlerThread
    private val busy = AtomicBoolean(false)

    override fun onCreate() {
        super.onCreate()
        looper = HandlerThread("caracole-ml").apply { start() }
    }

    override fun onBind(intent: Intent?): IBinder = Messenger(Handler(looper.looper) { message ->
        if (message.what == MlProtocol.HEAR) hear(Bundle(message.data), message.replyTo)
        true
    }).binder

    override fun onDestroy() {
        looper.quitSafely()
        super.onDestroy()
    }

    private fun hear(request: Bundle, client: Messenger?) {
        if (client == null) return
        if (!busy.compareAndSet(false, true)) {
            failed(client, MlProtocol.SETUP_KIND, "the chord models are hearing another song")
            return
        }
        thread(name = "caracole-ml-hearing") {
            try {
                resetPeak()
                val work = File(request.getString(MlProtocol.WORK)!!)
                val audio = File(request.getString(MlProtocol.AUDIO)!!)
                val pipeline = Pipeline(File(request.getString(MlProtocol.MODELS)!!), Heat(this),
                    request.getInt(MlProtocol.THREADS, 0))
                pipeline.hear(audio, work) { words -> send(client, MlProtocol.STEP, Bundle().apply {
                    putString(MlProtocol.WORDS, words)
                }) }
                send(client, MlProtocol.DONE, Bundle().apply {
                    putString(MlProtocol.HEARD, Checkpoints.of(work, audio).file(Checkpoints.HEARD).path)
                    putLong(MlProtocol.PEAK_KB, peakKb())
                })
            } catch (e: AudioUnreadable) {
                failed(client, MlProtocol.AUDIO_KIND, e.message ?: "the audio can't be read")
            } catch (e: ChordsUnavailable) {
                failed(client, MlProtocol.SETUP_KIND, e.message ?: "the chord models can't hear it now")
            } catch (e: TooHot) {
                failed(client, MlProtocol.SETUP_KIND, e.message ?: HeatRules.TOO_HOT)
            } catch (e: Throwable) {
                failed(client, MlProtocol.SETUP_KIND, "the chord models failed: $e")
            } finally {
                busy.set(false)
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
