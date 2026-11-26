package io.github.danielhp95.caracole

import android.app.ActivityManager
import android.app.Service
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.net.Uri
import android.os.Binder
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
 * that dies first (out of memory) is that session's failure, and so is one that writes no result within its time
 * ([allowed]: a floor and a share of its planned work) or within a minute of Stop. Each session's result says its
 * process's pid and whether it was fresh: no earlier session's process still up as it began. Starting a process
 * costs a second or two a session.
 */
internal object BenchSessions {
    const val PROCESS_SUFFIX = ":benchrun"
    private const val FLOOR_MS = 15 * 60_000L
    private const val A_FILE_A_PASS_MS = 10 * 60_000L
    private const val AFTER_STOP_MS = 60_000L

    /** How long a session of [files] files may take before it is given up: 15 minutes, and 10 a file a pass (a
     * four-minute song's run at an RTF of 1 is four). */
    fun allowed(spec: SessionSpec, files: Int): Long = FLOOR_MS + A_FILE_A_PASS_MS * files * spec.passes

    /** What a session that crashed or was killed left in `no_backup/bench-sessions/` (a `.json.part`, a log), gone: the
     * bench's start, while no session runs. */
    fun sweep(context: Context) {
        File(context.applicationContext.noBackupFilesDir, "bench-sessions").listFiles()?.forEach { it.delete() }
    }

    fun run(context: Context, spec: SessionSpec, files: Int, stopped: () -> Boolean, say: (String) -> Unit,
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
        val began = System.currentTimeMillis()
        val deadline = began + allowed(spec, files)
        var stopAt: Long? = null
        var givenUp: String? = null
        try {
            while (!result.exists() && !gone.get()) {
                Thread.sleep(500)
                if (seen == null) seen = pid(app)?.also(onProcess)
                if (stopped() && stopAt == null) {
                    stop.createNewFile()
                    stopAt = System.currentTimeMillis()
                }
                said = follow(log, said, say)
                val now = System.currentTimeMillis()
                if (now > deadline) {
                    givenUp = "no result within ${allowed(spec, files) / 60_000} minutes: given up"
                    break
                }
                if (stopAt != null && now - stopAt > AFTER_STOP_MS) {
                    givenUp = "stopped: its run didn't end within a minute, given up"
                    break
                }
            }
            follow(log, said, say)
        } finally {
            app.unbindService(connection)
        }
        val gone30 = System.currentTimeMillis() + 30_000
        while (pid(app) != null && System.currentTimeMillis() < gone30) Thread.sleep(200)
        seen?.let { if (pid(app) == it) Process.killProcess(it) }  // a worker given up on, ended (one uid)
        val out = if (givenUp == null && result.exists()) BenchCodec.decode(result.readText()) else {
            val why = givenUp ?: "the session's process died before its end (out of memory?)"
            say(why)
            SessionResult(Session(spec.model, spec.threads, spec.arena, spec.round, null, null, null, null, why,
                null), emptyList(), emptyList(), emptyList())
        }
        for (f in listOf(result, stop, log, File(dir, "$id.json.part"))) f.delete()
        return out.copy(session = out.session.copy(pid = seen, fresh = fresh))
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
            val out = try {
                session(spec, say) { File(dir, "$id.stop").exists() }
            } catch (e: Throwable) {
                SessionResult(Session(spec.model, spec.threads, spec.arena, spec.round, null, null, null, null,
                    "${e.javaClass.simpleName}: ${e.message}", null), emptyList(), emptyList(), emptyList())
            }
            val part = File(dir, "$id.json.part")
            part.writeText(BenchCodec.encode(out))
            part.renameTo(File(dir, "$id.json"))
        }
        return Binder()
    }

    private fun session(spec: SessionSpec, say: (String) -> Unit, stopped: () -> Boolean): SessionResult {
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
        return bench.session(spec.model, spec.threads, spec.arena, spec.round, spec.passes, sources, stopped)
    }

    override fun onUnbind(intent: Intent?): Boolean = false

    /** The session's process ends with it: the next session's memory starts from nothing. */
    override fun onDestroy() {
        super.onDestroy()
        Process.killProcess(Process.myPid())
    }
}
