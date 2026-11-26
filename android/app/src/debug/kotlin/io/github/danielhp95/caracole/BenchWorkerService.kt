package io.github.danielhp95.caracole

import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.app.Service
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.net.Uri
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.os.Process
import io.github.danielhp95.caracole.ml.AndroidProbe
import io.github.danielhp95.caracole.ml.Bench
import io.github.danielhp95.caracole.ml.BenchCodec
import io.github.danielhp95.caracole.ml.BenchInputs
import io.github.danielhp95.caracole.ml.Session
import io.github.danielhp95.caracole.ml.SessionResult
import java.io.File
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/** One session of the Chords bench, as the bench hands it to its process: the model, the setting, the screen round,
 * the passes, the models' folder, and the files to run over (the clips; the references of the owner's folder). */
internal class SessionSpec(
    val model: String, val threads: Int, val arena: Boolean, val round: String, val passes: Int,
    val models: String, val folder: String?, val clips: Boolean, val references: Boolean,
) {
    fun into(intent: Intent): Intent = intent.apply {
        putExtra("model", model); putExtra("threads", threads); putExtra("arena", arena); putExtra("round", round)
        putExtra("passes", passes); putExtra("models", models); putExtra("folder", folder); putExtra("clips", clips)
        putExtra("references", references)
    }

    companion object {
        fun of(intent: Intent) = SessionSpec(
            intent.getStringExtra("model")!!, intent.getIntExtra("threads", 1), intent.getBooleanExtra("arena", false),
            intent.getStringExtra("round")!!, intent.getIntExtra("passes", 1), intent.getStringExtra("models")!!,
            intent.getStringExtra("folder"), intent.getBooleanExtra("clips", true),
            intent.getBooleanExtra("references", true),
        )
    }
}

/**
 * The Chords bench's sessions, each in a fresh process (`:benchrun`, [BenchWorkerService]), so that a session's
 * memory is its own: nothing an earlier session's allocator kept, and its peak RSS its life's. [run] binds the
 * service for one session (a new address each time), follows its lines and waits for its result file, then unbinds,
 * which ends that process ([BenchWorkerService.onDestroy]), and waits for it to be gone before the next. A process
 * that dies first is that session's failure (Android's own word on why, for memory, kept); one that writes nothing
 * for longer than a run of its could take ([quiet]) is given up, and so is one whose run in flight doesn't end within
 * a minute of Stop: either way its last write, every run it finished, is kept, and the session says why it ended. Each session's result says its
 * process's pid and whether it was fresh: no earlier session's process still up as it began. Starting a process
 * costs a second or two a session.
 */
internal object BenchSessions {
    const val PROCESS_SUFFIX = ":benchrun"
    private const val FLOOR_MS = 5 * 60_000L
    private const val RUNS_OF_AN_RTF = 4
    private const val AFTER_STOP_MS = 60_000L

    /** How long the bench waits for a session's next write before it gives the session up: its runs write as they
     * end, so the bound is one run's, four times the audio of the run in flight (an RTF of 4), 5 minutes at least
     * (the model's load, a short file). */
    fun quiet(nextSeconds: Double?): Long = maxOf(FLOOR_MS, ((nextSeconds ?: 0.0) * 1000 * RUNS_OF_AN_RTF).toLong())

    /** What a session that crashed or was killed left in `no_backup/bench-sessions/` (a `.json.part`, a log), gone: the
     * bench's start, while no session runs. */
    fun sweep(context: Context) {
        File(context.applicationContext.noBackupFilesDir, "bench-sessions").listFiles()?.forEach { it.delete() }
    }

    fun run(context: Context, spec: SessionSpec, stopped: () -> Boolean, say: (String) -> Unit,
            onProcess: (Int) -> Unit = {}): SessionResult {
        val app = context.applicationContext
        val dir = File(app.noBackupFilesDir, "bench-sessions").apply { mkdirs() }
        // Fresh only once no earlier session's process is up.
        val before = System.currentTimeMillis() + 30_000
        while (pid(app) != null && System.currentTimeMillis() < before) Thread.sleep(200)
        val fresh = pid(app) == null
        if (!fresh) say("an earlier session's process is still up: this session's whole-life peak isn't its own")
        val id = UUID.randomUUID().toString()
        val result = File(dir, "$id.json")
        val stop = File(dir, "$id.stop")
        val log = File(dir, "$id.log")
        val gone = AtomicBoolean(false)
        val connection = object : ServiceConnection {
            override fun onServiceConnected(name: ComponentName?, service: IBinder?) {}
            override fun onServiceDisconnected(name: ComponentName?) = gone.set(true)
            override fun onBindingDied(name: ComponentName?) = gone.set(true)
        }
        val intent = spec.into(Intent(app, BenchWorkerService::class.java)
            .setData(Uri.parse("caracole-bench://session/$id")))
        check(app.bindService(intent, connection, Context.BIND_AUTO_CREATE or Context.BIND_IMPORTANT)) {
            "the bench's session service won't bind"
        }
        var said = 0L
        var seen: Int? = null
        var last: SessionResult? = null
        var lastStamp = -1L
        var lastWrite = System.currentTimeMillis()
        var stopAt: Long? = null
        var cut: String? = null  // why the bench ended the session itself
        fun read() {
            val stamp = result.lastModified()
            if (stamp == 0L || stamp == lastStamp) return
            last = try {
                BenchCodec.decode(result.readText()).also { lastStamp = stamp; lastWrite = System.currentTimeMillis() }
            } catch (e: Exception) {
                last  // mid-rename: the next poll reads it
            }
        }
        try {
            while (last?.ended != true && !gone.get()) {
                Thread.sleep(500)
                if (seen == null) seen = pid(app)?.also(onProcess)
                if (stopped() && stopAt == null) {
                    stop.createNewFile()
                    stopAt = System.currentTimeMillis()
                }
                said = follow(log, said, say)
                read()
                val now = System.currentTimeMillis()
                val bound = quiet(last?.nextSeconds)
                if (now - lastWrite > bound) {
                    cut = "no word from the session for ${bound / 60_000} minutes: given up, its run in flight left out"
                    break
                }
                if (stopAt != null && now - stopAt > AFTER_STOP_MS) {
                    cut = "${Bench.STOPPED}: its run in flight didn't end within a minute and is left out"
                    break
                }
            }
            read()
            follow(log, said, say)
        } finally {
            app.unbindService(connection)
        }
        val gone30 = System.currentTimeMillis() + 30_000
        while (pid(app) != null && System.currentTimeMillis() < gone30) Thread.sleep(200)
        seen?.let { if (pid(app) == it) Process.killProcess(it) }  // a worker given up on, ended (one uid)
        val got = last
        val out = when {
            got != null && got.ended -> got
            else -> {
                // What it last wrote, every run it finished; why it ended, the bench's word.
                val died = cut == null
                val oom = died && seen?.let { killedForMemory(app, it) } == true
                val why = cut ?: ("the session's process died before its end" +
                    if (oom) ": Android killed it for memory" else "")
                say(why)
                val partial = got?.session ?: Session(spec.model, spec.threads, spec.arena, spec.round, null, null,
                    null, null, null, null)
                SessionResult(partial.copy(
                    failure = if (died) why else partial.failure,
                    stopped = if (died) partial.stopped else why,
                    complete = false, outOfMemory = partial.outOfMemory || oom,
                ), got?.runs.orEmpty(), got?.btc.orEmpty(), got?.beats.orEmpty())
            }
        }
        for (f in listOf(result, stop, log, File(dir, "$id.json.part"))) f.delete()
        return out.copy(session = out.session.copy(pid = seen, fresh = fresh))
    }

    /** Whether Android says it ended the process [pid] for want of memory (its exit reasons, from Android 11; before
     * that, unknown: false). */
    private fun killedForMemory(context: Context, pid: Int): Boolean {
        if (Build.VERSION.SDK_INT < 30) return false
        return try {
            context.getSystemService(ActivityManager::class.java)
                .getHistoricalProcessExitReasons(context.packageName, pid, 1)
                .any { it.reason == ApplicationExitInfo.REASON_LOW_MEMORY }
        } catch (e: Exception) {
            false
        }
    }

    /** The session process's pid, while it runs. */
    private fun pid(context: Context): Int? = context.getSystemService(ActivityManager::class.java)
        .runningAppProcesses.orEmpty().firstOrNull { it.processName == context.packageName + PROCESS_SUFFIX }?.pid

    /** The lines the session wrote after [from], said; where it got to. */
    private fun follow(log: File, from: Long, say: (String) -> Unit): Long {
        if (!log.exists() || log.length() <= from) return from
        val text = log.inputStream().use { it.skip(from); it.readBytes() }.toString(Charsets.UTF_8)
        val whole = text.substringBeforeLast('\n', "")
        if (whole.isEmpty()) return from
        whole.split('\n').forEach(say)
        return from + whole.toByteArray(Charsets.UTF_8).size + 1
    }
}

/**
 * One session of the Chords bench, in its process of its own (`:benchrun`): bound by [BenchSessions.run] with a
 * [SessionSpec], it runs [Bench.session] on a thread, writes its lines to `<id>.log` and its [SessionResult] to
 * `<id>.json` (whole, by a rename) in `no_backup/bench-sessions/`, stops when `<id>.stop` appears, and ends its
 * process once unbound, so that the next session starts in a fresh one.
 */
class BenchWorkerService : Service() {
    override fun onBind(intent: Intent): IBinder {
        val id = intent.data!!.lastPathSegment!!
        val spec = SessionSpec.of(intent)
        val dir = File(noBackupFilesDir, "bench-sessions")
        val log = File(dir, "$id.log")
        thread(name = "caracole-bench-session") {
            val say: (String) -> Unit = { line -> synchronized(log) { log.appendText(line + "\n") } }
            // The session whole after each run, and as it ends: a Stop, a crash, a kill or a hang loses the run in
            // flight alone.
            val write: (SessionResult) -> Unit = { now ->
                val part = File(dir, "$id.json.part")
                part.writeText(BenchCodec.encode(now))
                part.renameTo(File(dir, "$id.json"))
            }
            val out = try {
                session(spec, say, { File(dir, "$id.stop").exists() }, write)
            } catch (e: Throwable) {
                SessionResult(Session(spec.model, spec.threads, spec.arena, spec.round, null, null, null, null,
                    "${e.javaClass.simpleName}: ${e.message}", null, outOfMemory = Bench.outOfMemory(e)),
                    emptyList(), emptyList(), emptyList())
            }
            write(out)
        }
        return Binder()
    }

    private fun session(spec: SessionSpec, say: (String) -> Unit, stopped: () -> Boolean,
                        progress: (SessionResult) -> Unit): SessionResult {
        val clips = BenchClips.read(this)
        val pins = BenchModels.pins()
        val beats = pins.getJSONObject("beats")
        val fps = beats.getInt("fps")
        val sources = buildList {
            if (spec.clips) clips.inputs.forEach { clip -> add(Bench.Source(clip.name) { clip }) }
            if (spec.references && spec.folder != null) {
                val folder = BenchFolder(contentResolver, Uri.parse(spec.folder))
                for (entry in folder.entries()) {
                    if (!entry.name.endsWith(".json") || entry.name.startsWith(BenchService.REPORT_PREFIX)) continue
                    add(Bench.Source(entry.name) {
                        folder.open(entry).use { BenchInputs.reference(entry.name, it, fps) }
                    })
                }
            }
        }
        val bench = Bench(File(spec.models), pins.getJSONObject("btc").getDouble("mean").toFloat(), fps,
            beats.getInt("chunk"), beats.getInt("border"), clips.gates, AndroidProbe(this), say)
        return bench.session(spec.model, spec.threads, spec.arena, spec.round, spec.passes, sources, stopped, progress)
    }

    override fun onUnbind(intent: Intent?): Boolean = false

    /** The session's process ends with it: the next session's memory starts from nothing. */
    override fun onDestroy() {
        super.onDestroy()
        Process.killProcess(Process.myPid())
    }
}
