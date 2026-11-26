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
 * that dies first (out of memory) is that session's failure. Starting a process costs a second or two a session.
 */
internal object BenchSessions {
    const val PROCESS_SUFFIX = ":benchrun"

    fun run(context: Context, spec: SessionSpec, stopped: () -> Boolean, say: (String) -> Unit,
            onProcess: (Int) -> Unit = {}): SessionResult {
        val app = context.applicationContext
        val dir = File(app.noBackupFilesDir, "bench-sessions").apply { mkdirs() }
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
        try {
            while (!result.exists() && !gone.get()) {
                Thread.sleep(500)
                if (seen == null) seen = pid(app)?.also(onProcess)
                if (stopped()) stop.createNewFile()
                said = follow(log, said, say)
            }
            follow(log, said, say)
        } finally {
            app.unbindService(connection)
        }
        val deadline = System.currentTimeMillis() + 30_000
        while (pid(app) != null && System.currentTimeMillis() < deadline) Thread.sleep(200)
        val out = if (result.exists()) BenchCodec.decode(result.readText()) else SessionResult(
            Session(spec.model, spec.threads, spec.arena, spec.round, null, null, null, null,
                "the session's process died before its end (out of memory?)", null),
            emptyList(), emptyList(), emptyList())
        if (out.session.failure != null && !result.exists()) say(out.session.failure!!)
        for (f in listOf(result, stop, log)) f.delete()
        return out
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
