package io.github.danielhp95.caracole.ml

import android.content.Context
import android.os.Debug
import android.os.PowerManager
import java.io.File
import java.util.Collections
import kotlin.concurrent.thread

/** What the bench reads of the process and the phone while a model runs: [AndroidProbe] on a phone. */
interface Probe {
    /** The process's PSS in kB, or null. */
    fun pssKb(): Long?

    /** The process's peak RSS reset (`/proc/self/clear_refs`), so that [rssPeakKb] is one run's: whether it took
     * (the peak read back no higher than the resident memory now), never assumed. */
    fun resetPeak(): Boolean

    /** The process's peak RSS in kB since [resetPeak] took, else over its life (VmHWM), or null. */
    fun rssPeakKb(): Long?

    fun heat(): Heat.Reading

    /** "on" or "off". */
    fun screen(): String
}

/** This process on this phone: [Debug.getPss], `/proc/self/status`, [Heat], the screen's state. */
class AndroidProbe(context: Context) : Probe {
    private val heat = Heat(context)
    private val power = context.applicationContext.getSystemService(PowerManager::class.java)

    override fun pssKb(): Long? = Debug.getPss().takeIf { it > 0 }

    override fun resetPeak(): Boolean {
        try {
            File("/proc/self/clear_refs").writeText("5")
        } catch (e: Exception) {
            return false
        }
        val peak = status("VmHWM") ?: return false
        val now = status("VmRSS") ?: return false
        return peak <= now + RESET_SLACK_KB
    }

    override fun rssPeakKb(): Long? = status("VmHWM")

    override fun heat(): Heat.Reading = heat.read()

    override fun screen(): String = if (power.isInteractive) "on" else "off"

    private fun status(key: String): Long? = try {
        File("/proc/self/status").readLines().firstOrNull { it.startsWith("$key:") }
            ?.substringAfter(':')?.trim()?.removeSuffix("kB")?.trim()?.toLong()
    } catch (e: Exception) {
        null
    }

    companion object {
        /** How far over the resident memory a peak read just after its reset may be (what the process touched
         * between the two reads) for the reset to have taken: a peak that isn't reset is another run's, far above. */
        const val RESET_SLACK_KB = 16L * 1024
    }
}

/**
 * The Chords bench's sessions (the design's §9.1, at B0): a session is one model ([BenchReport.BTC], beat_this fp16
 * or fp32) on one thread count and memory setting, its ONNX Runtime session loaded first and timed apart
 * ([Session.loadSeconds]), then each file in turn, `passes` times back to back. A run times the model alone (its
 * input read before), looks at the process every [SAMPLE_MS] while it runs ([Probe]: its PSS, the phone's heat) and
 * reads its true peak RSS (reset as it began, and said not to be when the reset didn't take); a file's first pass is
 * compared with the computer's outputs. Before each run the heat guard looks at the phone: at critical or worse
 * ([Heat.TOO_HOT]) the session stops, keeping what it measured, and says why. Anything thrown, an
 * [OutOfMemoryError] among them, ends the session as its failure, never losing its runs. The bench runs each session
 * in a process of its own (the app's BenchWorkerService), so that a session's memory is its own.
 *
 * BTC's features are padded to whole windows with [padding] (models.json's mean, as the graph's metadata says),
 * beat_this's mel cut into [chunk]-frame pieces with [border] (beat_this's `split_predict_aggregate`,
 * [BeatThis.logits]).
 */
class Bench(
    private val models: File, private val padding: Float, private val fps: Int, private val chunk: Int,
    private val border: Int, private val gates: Gates, private val probe: Probe, private val say: (String) -> Unit,
) {
    /** A file to run over, read when its turn comes ([read]), so that one is held at a time. */
    class Source(val name: String, val read: () -> BenchInput)

    private val runs = mutableListOf<Run>()
    private val btc = mutableListOf<BtcParity>()
    private val beats = mutableListOf<BeatParity>()
    private var peak: Long? = null

    /** One session over [sources], in the [round] ("on" or "off") the screen is meant to be; stops before the next run
     * once [stopped] says so. */
    fun session(model: String, threads: Int, arena: Boolean, round: String, passes: Int, sources: List<Source>,
                stopped: () -> Boolean): SessionResult {
        runs.clear(); btc.clear(); beats.clear()
        peak = probe.rssPeakKb()
        val start = probe.heat()
        var load: Double? = null
        var failure: String? = null
        var tooHot: String? = null
        val file = when (model) {
            BenchReport.BTC -> OrtModels.BEATS_FP16  // unused: BTC's session alone is opened
            BenchReport.BEATS_FP16 -> OrtModels.BEATS_FP16
            BenchReport.BEATS_FP32 -> OrtModels.BEATS_FP32
            else -> throw IllegalArgumentException("no model $model")
        }
        say("$model, $threads thread(s), arena ${if (arena) "on" else "off"}, screen $round")
        try {
            OrtModels(models, threads, file, arena).use { ort ->
                val began = System.nanoTime()
                ort.load(model == BenchReport.BTC)
                load = (System.nanoTime() - began) / 1e9
                say("loaded in ${"%.2f".format(load)} s")
                var cold = true
                sources@ for (source in sources) {
                    if (stopped()) break
                    val input = try {
                        source.read()
                    } catch (e: Exception) {
                        say("${source.name}: not read (${e.message ?: e.javaClass.simpleName}), passed over")
                        continue
                    }
                    for (pass in 1..passes) {
                        if (stopped()) break@sources
                        val thermal = probe.heat().thermal
                        if (thermal in Heat.TOO_HOT) {
                            tooHot = "the phone's thermal status reached $thermal"
                            say("stopped: $tooHot")
                            break@sources
                        }
                        one(ort, model, threads, arena, input, pass, cold)
                        cold = false
                    }
                }
            }
        } catch (e: Throwable) {
            failure = "${e.javaClass.simpleName}: ${e.message}"
            say("the session failed: $failure")
        }
        notePeak()
        val end = probe.heat()
        val session = Session(model, threads, arena, round, load, peak, start.chargeUah, end.chargeUah, failure,
            tooHot)
        return SessionResult(session, runs.toList(), btc.toList(), beats.toList())
    }

    /** The session's peak so far: VmHWM read before each reset, so the highest of them is its whole life's. */
    private fun notePeak() {
        val now = probe.rssPeakKb() ?: return
        peak = maxOf(peak ?: now, now)
    }

    private fun one(ort: OrtModels, model: String, threads: Int, arena: Boolean, input: BenchInput, pass: Int,
                    cold: Boolean) {
        val screen = probe.screen()
        val run: Run
        if (model == BenchReport.BTC) {
            val windows = (input.btcFrames + OrtModels.WINDOW - 1) / OrtModels.WINDOW
            val features = FloatArray(windows * OrtModels.WINDOW * OrtModels.BINS) { padding }
            System.arraycopy(input.cqt, 0, features, 0, input.cqt.size)
            val (logits, r) = measure(input, model, threads, arena, screen, pass, cold) {
                ort.chords(features, windows)
            }
            run = r
            if (pass == 1) {
                btc += BtcParity.of(input.name, threads, arena, logits, input.btcLogits, input.margins,
                    input.btcFrames)
            }
        } else {
            val (logits, r) = measure(input, model, threads, arena, screen, pass, cold) {
                BeatThis.logits(input.mel, input.melFrames, OrtModels.MELS, chunk, border) { piece, frames ->
                    ort.beats(piece, frames)
                }
            }
            run = r
            if (pass == 1) {
                beats += BeatParity.of(input.name, model, threads, arena, logits.first, logits.second, input.beat,
                    input.downbeat, input.beats, input.downbeats, fps, gates)
            }
        }
        runs += run
        say("${input.name} $model #$pass: ${"%.2f".format(run.seconds)} s, RTF ${"%.3f".format(run.rtf)}, " +
            "peak RSS ${run.truePeakKb?.let { "${it / 1024} MB" } ?: "unknown (its reset didn't take)"}, " +
            run.samples.last().thermal)
    }

    private fun <T> measure(input: BenchInput, model: String, threads: Int, arena: Boolean, screen: String,
                            pass: Int, cold: Boolean, block: () -> T): Pair<T, Run> {
        notePeak()
        val reset = probe.resetPeak()
        val samples = Collections.synchronizedList(mutableListOf<Sample>())
        fun look(): Heat.Reading = probe.heat().also { samples += Sample(probe.pssKb(), it.thermal, it.headroom) }
        val start = look()
        val sampler = thread(name = "caracole-bench-probe", isDaemon = true) {
            try {
                while (true) {
                    Thread.sleep(SAMPLE_MS)
                    look()
                }
            } catch (e: InterruptedException) {
                // the run is over
            }
        }
        val began = System.nanoTime()
        val result = try {
            block()
        } finally {
            sampler.interrupt()
        }
        val nanos = System.nanoTime() - began
        sampler.join()
        val end = look()
        return result to Run(
            file = input.name, kind = input.kind, model = model, pass = pass, threads = threads, arena = arena,
            screen = screen, cold = cold, nanos = nanos, duration = input.duration, samples = samples.toList(),
            reset = reset, rssPeakKb = probe.rssPeakKb(), batteryStartUah = start.chargeUah,
            batteryEndUah = end.chargeUah,
        )
    }

    companion object {
        /** How often the process is looked at while a model runs: PSS is a walk of its mappings, so not much more. */
        const val SAMPLE_MS = 1000L
    }
}
