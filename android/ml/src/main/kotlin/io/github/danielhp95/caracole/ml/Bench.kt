package io.github.danielhp95.caracole.ml

import android.content.Context
import android.os.Debug
import android.os.PowerManager
import java.io.File
import java.util.Collections
import kotlin.concurrent.thread
import kotlinx.serialization.json.JsonObject

/** What the bench reads of the process and the phone while a model runs: [AndroidProbe] on a phone. */
interface Probe {
    /** The process's PSS in kB, or null. */
    fun pssKb(): Long?

    /** The process's peak RSS reset (`/proc/self/clear_refs`), so that [rssPeakKb] is one run's. */
    fun resetPeak()

    /** The process's peak RSS in kB since [resetPeak] (VmHWM), or null. */
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

    override fun resetPeak() {
        try {
            File("/proc/self/clear_refs").writeText("5")
        } catch (e: Exception) {
            // A kernel that refuses it: the peak is the process's whole life's, which the report can't tell apart.
        }
    }

    override fun rssPeakKb(): Long? = try {
        File("/proc/self/status").readLines().firstOrNull { it.startsWith("VmHWM:") }
            ?.substringAfter(':')?.trim()?.removeSuffix("kB")?.trim()?.toLong()
    } catch (e: Exception) {
        null
    }

    override fun heat(): Heat.Reading = heat.read()

    override fun screen(): String = if (power.isInteractive) "on" else "off"
}

/**
 * The Chords bench's runs (the design's §9.1, at B0): each model chosen ([Plan.models]: BTC, beat_this fp16, fp32)
 * on each thread count and memory setting chosen ([Plan.threads], [Plan.arenas]), one session loaded at a time,
 * over each file in turn, [Plan.passes] times back to back. A run times the model alone (its input read before),
 * looks at the process every [SAMPLE_MS] while it runs ([Probe]), and the first pass of each file and setting is
 * compared with the computer's outputs ([Parity]), once however often [run] is called (the screen-off round runs
 * the same plan again). BTC's features are padded to whole windows with [padding]
 * (models.json's mean, as the graph's metadata says), beat_this's mel cut into [chunk]-frame pieces with [border]
 * (beat_this's `split_predict_aggregate`, [BeatThis.logits]).
 */
class Bench(
    private val models: File, private val padding: Float, private val fps: Int, private val chunk: Int,
    private val border: Int, private val gates: Gates, private val probe: Probe, private val say: (String) -> Unit,
) {
    class Plan(val models: List<String>, val threads: List<Int>, val arenas: List<Boolean>, val passes: Int)

    /** A file to run over, read when its turn comes ([read]), so that one is held at a time. */
    class Source(val name: String, val read: () -> BenchInput)

    private val runs = mutableListOf<Run>()
    private val btc = mutableListOf<BtcParity>()
    private val beats = mutableListOf<BeatParity>()

    /** Every model chosen over every source; stops before the next run once [stopped] says so, [saved] called after
     * each session's runs, so that a report is written as they go. */
    fun run(plan: Plan, sources: List<Source>, stopped: () -> Boolean, saved: () -> Unit) {
        for (model in plan.models) for (threads in plan.threads) for (arena in plan.arenas) {
            if (stopped()) return
            val file = when (model) {
                BenchReport.BTC -> OrtModels.BEATS_FP16  // unused: BTC's session alone is opened
                BenchReport.BEATS_FP16 -> OrtModels.BEATS_FP16
                BenchReport.BEATS_FP32 -> OrtModels.BEATS_FP32
                else -> throw IllegalArgumentException("no model $model")
            }
            say("$model, $threads thread(s), arena ${if (arena) "on" else "off"}")
            OrtModels(models, threads, file, arena).use { ort ->
                var cold = true
                for (source in sources) {
                    if (stopped()) return
                    val input = try {
                        source.read()
                    } catch (e: Exception) {
                        say("${source.name}: not read (${e.message ?: e.javaClass.simpleName}), passed over")
                        continue
                    }
                    for (pass in 1..plan.passes) {
                        if (stopped()) return
                        one(ort, model, threads, arena, input, pass, cold)
                        cold = false
                    }
                }
            }
            saved()
        }
    }

    fun report(device: Device, made: String): JsonObject = synchronized(this) {
        BenchReport.of(runs.toList(), Parity(gates, btc.toList(), beats.toList()), device, made)
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
            if (pass == 1) synchronized(this) {
                if (btc.none { it.file == input.name && it.threads == threads && it.arena == arena }) {
                    btc += BtcParity.of(input.name, threads, arena, logits, input.btcLogits, input.margins,
                        input.btcFrames)
                }
            }
        } else {
            val (logits, r) = measure(input, model, threads, arena, screen, pass, cold) {
                BeatThis.logits(input.mel, input.melFrames, OrtModels.MELS, chunk, border) { piece, frames ->
                    ort.beats(piece, frames)
                }
            }
            run = r
            if (pass == 1) synchronized(this) {
                val known = beats.any {
                    it.file == input.name && it.model == model && it.threads == threads && it.arena == arena
                }
                if (!known) {
                    beats += BeatParity.of(input.name, model, threads, arena, logits.first, logits.second,
                        input.beat, input.downbeat, input.beats, input.downbeats, fps, gates)
                }
            }
        }
        synchronized(this) { runs += run }
        say("${input.name} $model #$pass: ${"%.2f".format(run.seconds)} s, RTF ${"%.3f".format(run.rtf)}, " +
            "peak PSS ${run.pssPeakKb?.let { "${it / 1024} MB" } ?: "unknown"}, ${run.samples.last().thermal}" +
            if (cold) " (with the load)" else "")
    }

    private fun <T> measure(input: BenchInput, model: String, threads: Int, arena: Boolean, screen: String,
                            pass: Int, cold: Boolean, block: () -> T): Pair<T, Run> {
        probe.resetPeak()
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
            file = input.name, model = model, pass = pass, threads = threads, arena = arena, screen = screen,
            cold = cold, nanos = nanos, duration = input.duration, samples = samples.toList(),
            rssPeakKb = probe.rssPeakKb(), batteryStartUah = start.chargeUah, batteryEndUah = end.chargeUah,
        )
    }

    companion object {
        /** How often the process is looked at while a model runs: PSS is a walk of its mappings, so not much more. */
        const val SAMPLE_MS = 1000L
    }
}
