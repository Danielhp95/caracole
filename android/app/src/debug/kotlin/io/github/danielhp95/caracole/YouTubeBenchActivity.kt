package io.github.danielhp95.caracole

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.text.InputType
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import io.github.danielhp95.caracole.core.http.Draws
import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.youtube.BenchRan
import io.github.danielhp95.caracole.youtube.BenchReport
import io.github.danielhp95.caracole.youtube.BenchRun
import io.github.danielhp95.caracole.youtube.GateService
import io.github.danielhp95.caracole.youtube.Qjs
import io.github.danielhp95.caracole.youtube.RunFolders
import io.github.danielhp95.caracole.youtube.Stamped
import io.github.danielhp95.caracole.youtube.YtDlpClient
import io.github.danielhp95.caracole.youtube.utc
import java.io.File
import java.security.SecureRandom
import java.time.Instant
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

/**
 * The debug build's YouTube bench (the phone-youtube design's §4.2), from Settings' YouTube bench row, in a process of
 * its own (`:ytbench`), which never starts Python: its runs are `:youtube`'s ([YtDlpClient]), its gates the main
 * process's ([GateService]), its record of runs the main process's database ([YouTubeBenchLedger]). Up to three
 * queries, Start (the gate enforcing YouTube's hosts), Start, observing every host (the button alone: never an
 * intent), and what the runs say; then the report, `getExternalFilesDir("ytbench")/caracole-ytbench-<UTC>.json`.
 *
 * By intent (the owner's word over adb): `queries` (lines) and `go`; a `gate` of `observe` from an intent runs
 * `enforce`, and says so. What it shows and writes is what came back from the client (redacted), never the argv.
 */
class YouTubeBenchActivity : Activity() {
    private lateinit var queries: EditText
    private lateinit var left: TextView
    private lateinit var log: TextView
    private lateinit var scroll: ScrollView
    private lateinit var start: Button
    private lateinit var observe: Button
    private val lines = mutableListOf<String>()
    @Volatile private var running = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(16), 0, dp(16), 0) }
        TextView(this).apply {
            text = "Up to 3 lines: “Artist - Title” or a YouTube video id. A song is a search and a download: " +
                "at most 6 yt-dlp runs in any 24 hours, every run of the phone's counted."
            setPadding(0, dp(12), 0, dp(4))
        }.also(root::addView)
        queries = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE
            minLines = 3
        }.also(root::addView)
        left = TextView(this).also(root::addView)
        start = Button(this).apply { text = START; setOnClickListener { begin(observing = false) } }.also(root::addView)
        // Observing every host: this button's own click alone, never an intent.
        observe = Button(this).apply { text = START_OBSERVING; setOnClickListener { begin(observing = true) } }
            .also(root::addView)
        log = TextView(this).apply { setTextIsSelectable(true); typeface = android.graphics.Typeface.MONOSPACE }
            .also(root::addView)
        scroll = ScrollView(this).apply { addView(root) }
        setContentView(scroll)
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { view, insets ->
            val sys = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            view.setPadding(sys.left, sys.top, sys.right, sys.bottom)
            WindowInsetsCompat.CONSUMED
        }
        if (savedInstanceState == null) asked(intent) else showLeft()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        asked(intent)
    }

    /** An intent's extras: its queries in the box, a `gate` of `observe` said and passed over, `go` a start
     * (enforcing). */
    private fun asked(intent: Intent) {
        intent.getStringExtra(QUERIES)?.let { queries.setText(it.replace("\\n", "\n")) }
        if (intent.getStringExtra(GATE) == BenchRun.OBSERVE) say(INTENT_NEVER_OBSERVES)
        if (intent.getBooleanExtra(GO, false)) begin(observing = false) else showLeft()
    }

    private fun showLeft() = Thread {
        val words = try {
            YouTubeBenchLedger.Client(this).use { ledger ->
                val s = ledger.state()
                "${maxOf(s.budget - s.runs, 0)} of ${s.budget} runs left in the last 24 hours"
            }
        } catch (e: Exception) {
            "the phone's record of runs: ${e.message}"
        }
        runOnUiThread { left.text = words }
    }.start()

    private fun begin(observing: Boolean) {
        if (running) return
        running = true
        start.isEnabled = false
        observe.isEnabled = false
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val asked = queries.text.toString().lines()
        Thread({ session(asked, observing) }, "ytbench-session").start()
    }

    private fun session(asked: List<String>, observing: Boolean) {
        val gates = GateService.Client(this)
        val ledger = YouTubeBenchLedger.Client(this)
        try {
            val mode = gates.mode()
            val client = YtDlpClient(this, mode)
            val bench = BenchRun(runner(client), gates(gates, mode), ledger, YouTubeBenchProbe(this), clock(),
                                 BenchRun.Folders(File(cacheDir, "ytbench")), Qjs.path(this).path, ::say)
            val session = try {
                bench.session(asked, observing)
            } catch (e: BenchRun.Refused) {
                say("refused: ${e.words}")
                return
            } finally {
                client.close()
            }
            val probe = YouTubeBenchProbe(this)
            val report = BenchReport.of(probe.device(), probe.network(), session.gate, session.mode.name,
                utc(session.startedAt), session.idle, session.budgetBefore to session.budgetAfter,
                session.budgetOf, session.runs, session.killCheck, session.firstStart, session.stopped)
            val name = "caracole-ytbench-${utc(session.startedAt).replace(":", "")}.json"
            val file = File(getExternalFilesDir(FOLDER), name)
            file.writeText(PRETTY.encodeToString(JsonObject.serializer(), report) + "\n")
            for (line in BenchReport.said(report)) say(line)
            say("$DONE ${file.path}")
        } catch (e: Exception) {
            say("the bench failed: ${BenchReport.scrub(e.message ?: e.javaClass.simpleName)}")
        } finally {
            ledger.close()
            gates.close()
            running = false
            runOnUiThread {
                start.isEnabled = true
                observe.isEnabled = true
                window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
            showLeft()
        }
    }

    private fun runner(client: YtDlpClient) = object : BenchRun.Runner {
        override fun run(argv: List<String>, folders: RunFolders, timeoutS: Double, verbose: Boolean): BenchRan {
            val stamped = mutableListOf<Stamped>()
            val ran = client.run(argv, timeoutS, { ms, line -> synchronized(stamped) { stamped += Stamped(ms, line) } },
                                 { say("waiting for another run of the app's to end…") }, folders, verbose)
            return BenchRan(ran, synchronized(stamped) { stamped.toList() })
        }

        override fun cancel() = client.cancel()
    }

    private fun gates(client: GateService.Client, mode: HostGate.Mode) = object : BenchRun.Gates {
        override val mode = mode

        override fun open(observe: Boolean): BenchRun.Gate {
            val gate = if (observe) client.openObserving() else client.open()
            return object : BenchRun.Gate {
                override val proxyArg = gate.proxyArg
                override fun log() = gate.log()
                override fun close() = gate.close()
            }
        }
    }

    private fun clock(): BenchRun.Clock {
        val random = SecureRandom()
        return BenchRun.Clock(
            now = { Instant.now() },
            wall = { System.currentTimeMillis() / 1000.0 },
            monotonic = { SystemClock.elapsedRealtime() / 1000.0 },
            sleep = { s -> SystemClock.sleep((s * 1000).toLong()) },
            draws = Draws { low, high -> low + (high - low) * random.nextDouble() },
        )
    }

    private fun say(line: String) {
        val clean = BenchReport.scrub(line)
        synchronized(lines) { lines += clean }
        runOnUiThread {
            log.text = synchronized(lines) { lines.joinToString("\n") }
            scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
        }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    companion object {
        const val QUERIES = "queries"
        const val GO = "go"
        const val GATE = "gate"
        const val FOLDER = "ytbench"
        const val START = "Start"
        const val START_OBSERVING = "Start, observing every host"
        const val DONE = "report:"
        const val INTENT_NEVER_OBSERVES = "An intent never observes every host: this session enforces YouTube's."
        private val PRETTY = Json { prettyPrint = true }
    }
}
