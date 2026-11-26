package io.github.danielhp95.caracole

import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import io.github.danielhp95.caracole.ml.AndroidProbe
import io.github.danielhp95.caracole.ml.Bench
import io.github.danielhp95.caracole.ml.BenchInputs
import io.github.danielhp95.caracole.ml.BenchReport
import io.github.danielhp95.caracole.ml.Device
import io.github.danielhp95.caracole.ml.OrtModels
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import kotlin.concurrent.thread
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

/** What the bench says as it goes, and what the screen asks of it, shared by [BenchService] and
 * [ChordsBenchActivity] in their one process (":bench"). */
internal object BenchSession {
    @Volatile var running = false
    @Volatile var stopAsked = false

    /** Whether the screen is kept on: the first round's, never the second's. */
    @Volatile var keepScreenOn = false

    private val lines = ArrayDeque<String>()

    fun say(line: String) = synchronized(lines) {
        lines.addLast(line)
        while (lines.size > 500) lines.removeFirst()
    }

    fun text(): String = synchronized(lines) { lines.joinToString("\n") }
}

/** The committed clips (tests/conformance/vectors/autochords/models.jsonl and frontend.jsonl, the debug build's
 * assets, app/build.gradle.kts) and B0's gates their records state. */
internal object BenchClips {
    fun read(context: Context): BenchInputs.Clips {
        fun open(name: String) = context.assets.open("autochords/$name").reader(Charsets.UTF_8)
        return open("models.jsonl").use { models -> open("frontend.jsonl").use { BenchInputs.clips(models, it) } }
    }
}

/**
 * The Chords bench's runs, in the foreground (a special use, the debug build's alone) with a partial wake lock, so
 * that they go on with the screen off: the models chosen over the committed clips and the folder's references, once
 * with the screen kept on, then, if asked, again once the owner has turned it off. The report,
 * `caracole-bench-<UTC>.json`, is written into the folder after each model's session and at the end.
 */
class BenchService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForeground()
        if (BenchSession.running) return START_NOT_STICKY
        if (intent == null) {
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
            stopSelf(startId)
            return START_NOT_STICKY
        }
        BenchSession.running = true
        BenchSession.stopAsked = false
        thread(name = "caracole-bench") {
            val lock = getSystemService(PowerManager::class.java)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "caracole:bench")
            lock.acquire(12 * 60 * 60 * 1000L)
            try {
                work(intent)
            } catch (e: Exception) {
                BenchSession.say("stopped by a bug: $e")
            } finally {
                lock.release()
                BenchSession.keepScreenOn = false
                BenchSession.running = false
                ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
        return START_NOT_STICKY
    }

    private fun work(intent: Intent) {
        val say = BenchSession::say
        val folder = BenchFolder(contentResolver, Uri.parse(intent.getStringExtra(FOLDER)))
        val chosen = intent.getStringArrayExtra(MODELS).orEmpty().toList()
        val needed = buildSet {
            if (BenchReport.BTC in chosen) { add(OrtModels.BTC_GRAPH); add(OrtModels.BTC_WEIGHTS) }
            if (BenchReport.BEATS_FP16 in chosen) add(OrtModels.BEATS_FP16)
            if (BenchReport.BEATS_FP32 in chosen) add(OrtModels.BEATS_FP32)
        }
        val (models, ready) = BenchModels.prepare(this, folder, needed, say)
        val plan = Bench.Plan(
            models = chosen.filter { m ->
                when (m) {
                    BenchReport.BTC -> OrtModels.BTC_GRAPH in ready && OrtModels.BTC_WEIGHTS in ready
                    BenchReport.BEATS_FP16 -> OrtModels.BEATS_FP16 in ready
                    else -> OrtModels.BEATS_FP32 in ready
                }
            },
            threads = intent.getIntArrayExtra(THREADS)!!.toList(),
            arenas = intent.getBooleanArrayExtra(ARENAS)!!.toList(),
            passes = intent.getIntExtra(PASSES, 5),
        )
        val clips = BenchClips.read(this)
        val pins = BenchModels.pins()
        val beats = pins.getJSONObject("beats")
        val fps = beats.getInt("fps")
        val sources = buildList {
            if (intent.getBooleanExtra(CLIPS, true)) {
                clips.inputs.forEach { clip -> add(Bench.Source(clip.name) { clip }) }
            }
            if (intent.getBooleanExtra(REFERENCES, true)) {
                for (entry in folder.entries()) {
                    if (!entry.name.endsWith(".json") || entry.name.startsWith(REPORT_PREFIX)) continue
                    add(Bench.Source(entry.name) {
                        folder.open(entry).use { BenchInputs.reference(entry.name, it, fps) }
                    })
                }
            }
        }
        if (plan.models.isEmpty() || sources.isEmpty() || plan.threads.isEmpty() || plan.arenas.isEmpty()) {
            say("nothing to run: a model, a thread count, an arena setting and a file are needed")
            return
        }
        val made = Instant.now().truncatedTo(ChronoUnit.SECONDS)
        val name = REPORT_PREFIX + DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss'Z'").withZone(ZoneOffset.UTC)
            .format(made) + ".json"
        val report = folder.create(name, "application/json")
        val device = Device.here(BuildConfig.VERSION_NAME)
        val probe = AndroidProbe(this)
        val bench = Bench(models, pins.getJSONObject("btc").getDouble("mean").toFloat(), fps, beats.getInt("chunk"),
            beats.getInt("border"), clips.gates, probe, say)
        fun save() = folder.write(report, (JSON.encodeToString(JsonObject.serializer(),
            bench.report(device, made.toString())) + "\n").toByteArray(Charsets.UTF_8))

        val start = probe.heat()
        say("${sources.size} file(s), ${plan.models.joinToString()}; threads ${plan.threads}; " +
            "arena ${plan.arenas.map { if (it) "on" else "off" }}; ${plan.passes} pass(es) each")
        say("battery ${start.percent ?: "?"} %, " + when (start.plugged) {
            true -> "plugged in: unplug it for the battery's numbers"
            false -> "unplugged"
            null -> "plugged in or not: unknown"
        } + if (start.powerSave == true) ", Battery Saver on" else "")
        BenchSession.keepScreenOn = true
        say("— with the screen on")
        bench.run(plan, sources, { BenchSession.stopAsked }, ::save)
        if (intent.getBooleanExtra(SCREEN_OFF, true) && !BenchSession.stopAsked) {
            BenchSession.keepScreenOn = false
            say("— turn the screen off now (the power button): the same runs again with it off")
            val asked = System.nanoTime()
            while (probe.screen() == "on" && !BenchSession.stopAsked && System.nanoTime() - asked < WAIT_NANOS) {
                Thread.sleep(1000)
            }
            bench.run(plan, sources, { BenchSession.stopAsked }, ::save)
        }
        save()
        say(if (BenchSession.stopAsked) "stopped; the report so far: $name" else "done: $name, in the folder")
    }

    private fun startForeground() {
        Notifications.channel(this)
        val open = PendingIntent.getActivity(this, 0, Intent(this, ChordsBenchActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val notification: Notification = NotificationCompat.Builder(this, Notifications.JOBS)
            .setSmallIcon(R.drawable.ic_notify)
            .setContentTitle("Chords bench")
            .setContentText("Running the chord and beat models")
            .setOngoing(true)
            .setSilent(true)
            .setContentIntent(open)
            .build()
        val type = if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
        ServiceCompat.startForeground(this, NOTIFICATION, notification, type)
    }

    companion object {
        const val FOLDER = "folder"
        const val MODELS = "models"
        const val THREADS = "threads"
        const val ARENAS = "arenas"
        const val PASSES = "passes"
        const val SCREEN_OFF = "screen_off"
        const val CLIPS = "clips"
        const val REFERENCES = "references"

        /** The report's name begins so; a reference is any other `.json` of the folder. */
        const val REPORT_PREFIX = "caracole-bench-"

        private const val NOTIFICATION = 7
        private const val WAIT_NANOS = 10 * 60 * 1_000_000_000L
        private val JSON = Json { prettyPrint = true }
    }
}
