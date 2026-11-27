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
import io.github.danielhp95.caracole.ml.Battery
import io.github.danielhp95.caracole.ml.Bench
import io.github.danielhp95.caracole.ml.BenchInputs
import io.github.danielhp95.caracole.ml.BenchReport
import io.github.danielhp95.caracole.ml.Device
import io.github.danielhp95.caracole.ml.OrtModels
import io.github.danielhp95.caracole.ml.Session
import io.github.danielhp95.caracole.ml.SessionResult
import java.io.File
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import kotlin.concurrent.thread
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonPrimitive

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
 * The Chords bench, in the foreground (a special use, the debug build's alone) with a partial wake lock, so that it
 * goes on with the screen off: a session a model, thread count and arena setting, each in a fresh process
 * ([BenchSessions]), over the committed clips and the folder's references, once with the screen kept on, then, if
 * asked, again once the owner has turned it off. Only the owner's Stop and a session the heat guard stopped end the
 * bench; a session given up for a hang, or whose process died, is its failure, and the next one runs. The report,
 * `caracole-bench-<UTC>.json`, is written into the folder after each session and at the end, with the battery over
 * the whole bench.
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
            } catch (e: Throwable) {
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
        val tree = intent.getStringExtra(FOLDER)!!
        val folder = BenchFolder(contentResolver, Uri.parse(tree))
        if (intent.getBooleanExtra(HEARINGS, false)) return hearings(folder)
        val chosen = intent.getStringArrayExtra(MODELS).orEmpty().toList()
        val needed = buildSet {
            if (BenchReport.BTC in chosen) { add(OrtModels.BTC_GRAPH); add(OrtModels.BTC_WEIGHTS) }
            if (BenchReport.BEATS_FP16 in chosen) add(OrtModels.BEATS_FP16)
            if (BenchReport.BEATS_FP32 in chosen) add(OrtModels.BEATS_FP32)
        }
        val (models, ready) = BenchModels.prepare(this, folder, needed, say)
        val runnable = chosen.filter { m ->
            when (m) {
                BenchReport.BTC -> OrtModels.BTC_GRAPH in ready && OrtModels.BTC_WEIGHTS in ready
                BenchReport.BEATS_FP16 -> OrtModels.BEATS_FP16 in ready
                else -> OrtModels.BEATS_FP32 in ready
            }
        }
        val threads = intent.getIntArrayExtra(THREADS)!!.toList()
        val arenas = intent.getBooleanArrayExtra(ARENAS)!!.toList()
        val passes = intent.getIntExtra(PASSES, 5)
        val clips = intent.getBooleanExtra(CLIPS, true)
        val referenceCount = if (!intent.getBooleanExtra(REFERENCES, true)) 0
        else folder.entries().count { it.name.endsWith(".json") && !it.name.startsWith(REPORT_PREFIX) }
        val references = referenceCount > 0
        if (runnable.isEmpty() || threads.isEmpty() || arenas.isEmpty() || !(clips || references)) {
            say("nothing to run: a model, a thread count, an arena setting and a file are needed")
            return
        }
        val rounds = if (intent.getBooleanExtra(SCREEN_OFF, true)) listOf("on", "off") else listOf("on")
        val sessions = rounds.flatMap { round ->
            runnable.flatMap { m -> threads.flatMap { t -> arenas.map { a -> SessionSpec(m, t, a, round, passes,
                models.path, tree, clips, references) } } }
        }
        val made = Instant.now().truncatedTo(ChronoUnit.SECONDS)
        val name = REPORT_PREFIX + DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss'Z'").withZone(ZoneOffset.UTC)
            .format(made) + ".json"
        val report = folder.create(name, "application/json")
        val device = Device.here(BuildConfig.VERSION_NAME)
        val probe = AndroidProbe(this)
        val clipInputs = BenchClips.read(this)
        val gates = clipInputs.gates
        BenchSessions.sweep(this)
        val start = probe.heat()
        val results = mutableListOf<SessionResult>()
        fun save() {
            val now = probe.heat()
            val battery = Battery(start.chargeUah, now.chargeUah, start.percent, now.percent, start.plugged)
            val text = JSON.encodeToString(JsonObject.serializer(),
                BenchReport.ofSessions(results, gates, device, made.toString(), battery)) + "\n"
            folder.write(report, text.toByteArray(Charsets.UTF_8))
        }

        say("${sessions.size} session(s), each in a fresh process: ${runnable.joinToString()}; threads $threads; " +
            "arena ${arenas.map { if (it) "on" else "off" }}; ${passes} pass(es) of each file; " +
            (if (clips) "the clips" else "") + (if (clips && references) " and " else "") +
            (if (references) "the folder's references" else ""))
        say("battery ${start.percent ?: "?"} %, " + when (start.plugged) {
            true -> "plugged in: unplug it for the battery's numbers"
            false -> "unplugged"
            null -> "plugged in or not: unknown"
        } + if (start.powerSave == true) ", Battery Saver on" else "")
        var round = ""
        // Only the owner's Stop and the heat guard end the bench (Bench.endsTheBench); a session given up for a hang,
        // or whose process died, is that session's failure, and the next one runs.
        Bench.runSessions(sessions, stopAsked = { BenchSession.stopAsked }) { spec ->
            if (spec.round != round) {
                round = spec.round
                if (round == "on") {
                    BenchSession.keepScreenOn = true
                    say("— with the screen on")
                } else {
                    BenchSession.keepScreenOn = false
                    say("— turn the screen off now (the power button): the same runs again with it off")
                    val asked = System.nanoTime()
                    while (probe.screen() == "on" && !BenchSession.stopAsked &&
                        System.nanoTime() - asked < WAIT_NANOS) Thread.sleep(1000)
                }
            }
            val result = try {
                BenchSessions.run(this, spec, { BenchSession.stopAsked }, say)
            } catch (e: Throwable) {
                SessionResult(Session(spec.model, spec.threads, spec.arena, spec.round, null, null, null, null,
                    "${e.javaClass.simpleName}: ${e.message}", null), emptyList(), emptyList(), emptyList())
            }
            results += result
            save()
            if (result.session.stopped?.startsWith(Bench.TOO_HOT) == true) {
                say("the bench stops: ${result.session.stopped}; let the phone cool before another")
            }
            result
        }
        save()
        say(if (BenchSession.stopAsked) "stopped; the report so far: $name" else "done: $name, in the folder")
    }

    /**
     * The whole-pipeline mode (Gate B1): the folder's songs and its `hearings` folder copied into the app's own storage
     * (`no_backup/bench-hearings/`, emptied first and after), the three model files the hearing runs on prepared as the
     * sessions' are, every song heard whole ([BenchHearings]) with the screen kept on, and the report written into the
     * folder with its `hearings` member, the battery over the whole.
     */
    private fun hearings(folder: BenchFolder) {
        val say = BenchSession::say
        val (models, ready) = BenchModels.prepare(this, folder,
            setOf(OrtModels.BTC_GRAPH, OrtModels.BTC_WEIGHTS, OrtModels.BEATS_FP16), say)
        if (ready.size < 3) {
            say("nothing to hear: the whole pipeline needs BTC's weights and beat_this's fp16 file in the folder")
            return
        }
        val hearings = folder.folder(BenchHearings.FOLDER)
        if (hearings == null) {
            say("no folder ${BenchHearings.FOLDER} in the folder: put the computer's hearings of the songs there")
            return
        }
        val local = File(noBackupFilesDir, "bench-hearings")
        local.deleteRecursively()
        local.mkdirs()
        try {
            val songs = folder.entries().filter { BenchHearings.isAudio(it.name) }
            val records = hearings.entries().filter {
                it.name == BenchHearings.META || it.name.endsWith(BenchHearings.HEARING)
            }
            if (songs.isEmpty() || records.none { it.name == BenchHearings.META }) {
                say("nothing to hear: the folder needs the songs and ${BenchHearings.FOLDER}/${BenchHearings.META}")
                return
            }
            for (entry in songs + records) {
                say("copying ${entry.name}…")
                folder.open(entry).use { input -> File(local, entry.name).outputStream().use { input.copyTo(it) } }
            }
            val made = Instant.now().truncatedTo(ChronoUnit.SECONDS)
            val name = REPORT_PREFIX + DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss'Z'").withZone(ZoneOffset.UTC)
                .format(made) + ".json"
            val report = folder.create(name, "application/json")
            val probe = AndroidProbe(this)
            val start = probe.heat()
            BenchSession.keepScreenOn = true
            say("${songs.size} song(s), each heard whole in a fresh :ml process")
            val heard = BenchHearings.run(this, models, local, say) { BenchSession.stopAsked }
            val now = probe.heat()
            val battery = Battery(start.chargeUah, now.chargeUah, start.percent, now.percent, start.plugged)
            val text = JSON.encodeToString(JsonObject.serializer(), BenchReport.ofSessions(emptyList(),
                BenchClips.read(this).gates, Device.here(BuildConfig.VERSION_NAME), made.toString(), battery,
                heard)) + "\n"
            folder.write(report, text.toByteArray(Charsets.UTF_8))
            val pass = heard.getValue("pass").jsonPrimitive.boolean
            say("done: $name, in the folder: B1 ${if (pass) "passes" else "fails"} over all")
        } finally {
            local.deleteRecursively()
        }
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

        /** The whole-pipeline mode: the folder's songs heard whole against their hearings (Gate B1). */
        const val HEARINGS = "hearings"

        /** The report's name begins so; a reference is any other `.json` of the folder. */
        const val REPORT_PREFIX = "caracole-bench-"

        private const val NOTIFICATION = 7
        private const val WAIT_NANOS = 10 * 60 * 1_000_000_000L
        private val JSON = Json { prettyPrint = true }
    }
}
