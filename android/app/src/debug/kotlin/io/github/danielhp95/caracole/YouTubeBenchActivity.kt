package io.github.danielhp95.caracole

import android.app.Activity
import android.content.Context
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
import io.github.danielhp95.caracole.youtube.DbLedger
import io.github.danielhp95.caracole.youtube.GateService
import io.github.danielhp95.caracole.youtube.Qjs
import io.github.danielhp95.caracole.youtube.RunFolders
import io.github.danielhp95.caracole.youtube.Stamped
import io.github.danielhp95.caracole.youtube.YtDlpClient
import io.github.danielhp95.caracole.youtube.utc
import java.io.File
import java.security.SecureRandom
import java.time.Instant
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

/**
 * The debug build's YouTube bench (the phone-youtube design's §4.2), from Settings' YouTube bench row, in a process of
 * its own (`:ytbench`), which never starts Python: its runs are `:youtube`'s ([YtDlpClient]), its gates the main
 * process's ([GateService]), its record of runs the main process's database ([YouTubeBenchLedger]). Up to three
 * queries, Start (the gate enforcing YouTube's hosts), Start, observing every host (the button alone: never an
 * intent), and what the runs say; then the report, `getExternalFilesDir("ytbench")/caracole-ytbench-<UTC>.json`.
 *
 * On the real network a session starts by a tap on Start alone: an intent's `go` is honoured under the tests'
 * loopback only ([BenchRun.startsByIntent]), consumed as it is read (so a recreated screen starts nothing), and
 * passed over on a relaunch from Recents; an intent may still fill the queries (`queries`), and a `gate` of `observe`
 * is said and passed over. One session a process ([Bench]): a second Start while one runs is refused in words, and a
 * screen made again (a rotation, a new start) shows the running session's lines. What it shows and writes is what
 * came back from the client (redacted), never the argv.
 */
class YouTubeBenchActivity : Activity() {
    private lateinit var queries: EditText
    private lateinit var left: TextView
    private lateinit var log: TextView
    private lateinit var scroll: ScrollView
    private lateinit var start: Button
    private lateinit var observe: Button

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(16), 0, dp(16), 0) }
        TextView(this).apply {
            text = "Up to 3 lines: “Artist - Title” or a YouTube video id. A song is a search and a download: " +
                (if (DbLedger.DAY_CAP_LIFTED) "every yt-dlp run of the phone's counted, no daily limit while this " +
                    "is developed." else "at most 6 yt-dlp runs in any 24 hours, every run of the phone's counted.")
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
        Bench.screen = this
        show()
        if (savedInstanceState == null) asked(intent) else showLeft()
    }

    override fun onDestroy() {
        if (Bench.screen === this) Bench.screen = null
        super.onDestroy()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        asked(intent)
    }

    /** An intent's extras: its queries in the box; a `gate` of `observe` said and passed over; `go` consumed, and a
     * start only where [BenchRun.startsByIntent] says (the tests' loopback, not from Recents). */
    private fun asked(intent: Intent) {
        intent.getStringExtra(QUERIES)?.let { queries.setText(it.replace("\\n", "\n")) }
        if (intent.getStringExtra(GATE) == BenchRun.OBSERVE) Bench.say(INTENT_NEVER_OBSERVES)
        val go = intent.getBooleanExtra(GO, false)
        intent.removeExtra(GO)
        val fromHistory = intent.flags and Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY != 0
        if (!go) return showLeft()
        val app = applicationContext
        Thread {
            val mode = try {
                GateService.Client(app).use { it.mode() }
            } catch (e: Exception) {
                null
            }
            runOnUiThread {
                if (mode != null && BenchRun.startsByIntent(mode, true, fromHistory)) begin(observing = false)
                else {
                    Bench.say(if (fromHistory) GO_FROM_HISTORY else GO_NOT_HERE)
                    showLeft()
                }
            }
        }.start()
    }

    private fun showLeft() {
        val app = applicationContext
        Thread {
            val words = try {
                YouTubeBenchLedger.Client(app).use { ledger ->
                    BenchRun.runsWords(ledger.state())
                }
            } catch (e: Exception) {
                "the phone's record of runs: ${e.message}"
            }
            runOnUiThread { left.text = words }
        }.start()
    }

    private fun begin(observing: Boolean) {
        if (!Bench.running.compareAndSet(false, true)) {
            Bench.say(ALREADY)
            return
        }
        show()
        val asked = queries.text.toString().lines()
        val app = applicationContext
        Thread({ Bench.session(app, asked, observing) }, "ytbench-session").start()
    }

    /** The process's session as it stands: its lines, the buttons off and the screen kept on while it runs. */
    internal fun show() {
        val running = Bench.running.get()
        start.isEnabled = !running
        observe.isEnabled = !running
        if (running) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        log.text = Bench.text()
        scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
        if (!running) showLeft()
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    /** The bench's one session of this process, and its lines, whatever screen shows them. */
    internal object Bench {
        val running = AtomicBoolean(false)
        private val lines = mutableListOf<String>()
        @Volatile var screen: YouTubeBenchActivity? = null

        fun text(): String = synchronized(lines) { lines.joinToString("\n") }

        fun say(line: String) {
            synchronized(lines) { lines += BenchReport.scrub(line) }
            redraw()
        }

        private fun redraw() {
            val shown = screen ?: return
            shown.runOnUiThread { if (!shown.isDestroyed) shown.show() }
        }

        /** The session on [app]: every client made inside the `try` whose `finally` clears [running], so a session
         * whose clients won't build never leaves Start refused for the process's life. */
        fun session(app: Context, asked: List<String>, observing: Boolean) {
            var gates: GateService.Client? = null
            var ledger: YouTubeBenchLedger.Client? = null
            try {
                gates = GateService.Client(app)
                ledger = YouTubeBenchLedger.Client(app)
                val mode = gates.mode()
                val client = YtDlpClient(app, mode)
                val loopback = YtDlpClient(app, HostGate.Mode.LOOPBACK)
                val bench = BenchRun(runner(client), runner(loopback), gates(gates, mode), ledger, YouTubeBenchProbe(app),
                                     clock(), BenchRun.Folders(File(app.cacheDir, FOLDER)), Qjs.path(app).path, ::say)
                val session = try {
                    bench.session(asked, observing)
                } catch (e: BenchRun.Refused) {
                    say("refused: ${e.words}")
                    return
                } finally {
                    client.close()
                    loopback.close()
                }
                val probe = YouTubeBenchProbe(app)
                val report = BenchReport.of(probe.device(), probe.network(), session.gate, session.mode.name,
                    utc(session.startedAt), session.idle, session.budgetBefore to session.budgetAfter,
                    session.budgetOf, session.capLifted, session.runs, session.killCheck, session.firstStart,
                    session.stopped)
                val name = "caracole-ytbench-${utc(session.startedAt).replace(":", "")}.json"
                val file = File(app.getExternalFilesDir(FOLDER), name)
                file.writeText(PRETTY.encodeToString(JsonObject.serializer(), report) + "\n")
                for (line in BenchReport.said(report)) say(line)
                say("$DONE ${file.path}")
            } catch (e: Exception) {
                say("the bench failed: ${BenchReport.scrub(e.message ?: e.javaClass.simpleName)}")
            } finally {
                try {
                    ledger?.close()
                } finally {
                    gates?.close()
                    running.set(false)
                }
                redraw()
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

            override fun open(observe: Boolean) = wrap(if (observe) client.openObserving() else client.open())

            override fun openLoopback() = wrap(client.openLoopback())

            private fun wrap(gate: GateService.Gate) = object : BenchRun.Gate {
                override val proxyArg = gate.proxyArg
                override fun log() = gate.log()
                override fun close() = gate.close()
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
    }

    companion object {
        const val QUERIES = "queries"
        const val GO = "go"
        const val GATE = "gate"
        const val FOLDER = "ytbench"
        const val START = "Start"
        const val START_OBSERVING = "Start, observing every host"
        const val DONE = "report:"
        const val ALREADY = "A session is running already: one at a time."
        const val INTENT_NEVER_OBSERVES = "An intent never observes every host: this session enforces YouTube's."
        const val GO_NOT_HERE = "An intent starts no session on the real network: press Start."
        const val GO_FROM_HISTORY = "A relaunch from Recents starts no session: press Start."
        private val PRETTY = Json { prettyPrint = true }
    }
}
