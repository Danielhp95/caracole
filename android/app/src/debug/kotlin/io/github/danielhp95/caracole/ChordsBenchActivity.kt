package io.github.danielhp95.caracole

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.DocumentsContract
import android.text.InputType
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import io.github.danielhp95.caracole.ml.BenchReport

/**
 * The debug build's Chords bench (the chords-on-the-phone design's §9.1), from Settings' Chords bench row: the folder
 * picked (`ACTION_OPEN_DOCUMENT_TREE`, its grant kept for the next time), what to run (the models, the thread counts,
 * ONNX Runtime's arena off and on, how many passes, the screen-off round, the clips and the references), Start and
 * Stop, [HEAR_SONGS] (the whole-pipeline mode, Gate B1: BenchService's `hearings`), and what the runs say. The runs
 * are [BenchService]'s, in this process (":bench"); this screen keeps the screen on for the first round alone.
 */
class ChordsBenchActivity : Activity() {
    private val prefs by lazy { getSharedPreferences("bench", MODE_PRIVATE) }
    private val ticker = Handler(Looper.getMainLooper())
    private lateinit var folderLine: TextView
    private lateinit var log: TextView
    private lateinit var scroll: ScrollView
    private lateinit var start: Button
    private lateinit var stop: Button
    private lateinit var hear: Button
    private lateinit var passes: EditText
    private val models = mutableMapOf<String, CheckBox>()
    private val threads = mutableMapOf<Int, CheckBox>()
    private val arenas = mutableMapOf<Boolean, CheckBox>()
    private lateinit var screenOff: CheckBox
    private lateinit var clips: CheckBox
    private lateinit var references: CheckBox

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(16), 0, dp(16), 0) }
        fun label(text: String) = TextView(this).apply { this.text = text; setPadding(0, dp(12), 0, dp(4)) }
            .also(root::addView)
        fun box(text: String, on: Boolean) = CheckBox(this).apply { this.text = text; isChecked = on }
            .also(root::addView)

        folderLine = label("")
        Button(this).apply { text = "Pick the folder"; setOnClickListener { pick() } }.also(root::addView)
        label("Models")
        models[BenchReport.BTC] = box("BTC (chords)", true)
        models[BenchReport.BEATS_FP16] = box("beat_this, fp16-stored (43 MB)", true)
        models[BenchReport.BEATS_FP32] = box("beat_this, fp32 (83 MB)", true)
        label("Threads")
        for ((n, on) in listOf(1 to false, 2 to true, 4 to true, 8 to false)) threads[n] = box("$n", on)
        label("ONNX Runtime's memory")
        arenas[false] = box("arena and memory patterns off (the app's)", true)
        arenas[true] = box("arena and memory patterns on (the runtime's default)", true)
        label("Passes of each file, back to back")
        passes = EditText(this).apply { inputType = InputType.TYPE_CLASS_NUMBER; setText("5") }.also(root::addView)
        screenOff = box("then the same runs again with the screen off", true)
        clips = box("the committed clips", true)
        references = box("the folder's references (.json)", true)
        val buttons = LinearLayout(this).also(root::addView)
        start = Button(this).apply { text = "Start"; setOnClickListener { begin() } }.also(buttons::addView)
        stop = Button(this).apply { text = "Stop"; setOnClickListener { BenchSession.stopAsked = true } }
            .also(buttons::addView)
        label("The whole pipeline (Gate B1): each song of the folder heard whole, against the computer's hearing " +
            "of it in its folder ${BenchHearings.FOLDER}")
        hear = Button(this).apply { text = HEAR_SONGS; setOnClickListener { hearSongs() } }.also(root::addView)
        log = TextView(this).apply { setTextIsSelectable(true); typeface = android.graphics.Typeface.MONOSPACE }
            .also(root::addView)
        scroll = ScrollView(this).apply { addView(root) }
        setContentView(scroll)
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { view, insets ->
            val sys = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            view.setPadding(sys.left, sys.top, sys.right, sys.bottom)
            WindowInsetsCompat.CONSUMED
        }
        showFolder()
    }

    override fun onResume() {
        super.onResume()
        tick()
    }

    override fun onPause() {
        ticker.removeCallbacksAndMessages(null)
        super.onPause()
    }

    private fun tick() {
        val running = BenchSession.running
        start.isEnabled = !running && folder() != null
        hear.isEnabled = start.isEnabled
        stop.isEnabled = running
        val text = BenchSession.text()
        if (log.text.toString() != text) {
            log.text = text
            scroll.post { scroll.fullScroll(View.FOCUS_DOWN) }
        }
        if (running && BenchSession.keepScreenOn) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        ticker.postDelayed(::tick, 1000)
    }

    private fun pick() {
        @Suppress("DEPRECATION")
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE), PICK)
    }

    @Deprecated("Activity's own")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
        val uri = data?.data
        if (requestCode != PICK || resultCode != RESULT_OK || uri == null) return
        contentResolver.takePersistableUriPermission(uri,
            Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        prefs.edit().putString(FOLDER, uri.toString()).apply()
        showFolder()
    }

    /** The folder picked before, while its grant holds. */
    private fun folder(): Uri? {
        val uri = prefs.getString(FOLDER, null)?.let(Uri::parse) ?: return null
        return uri.takeIf { contentResolver.persistedUriPermissions.any { it.uri == uri && it.isWritePermission } }
    }

    private fun showFolder() {
        val uri = folder()
        folderLine.text = if (uri == null) "No folder picked: pick the one with the models and the references"
        else "Folder: " + (DocumentsContract.getTreeDocumentId(uri).substringAfter(':').ifEmpty { "(its root)" })
    }

    private fun begin() {
        val uri = folder() ?: return
        BenchSession.say("starting…")
        ContextCompat.startForegroundService(this, Intent(this, BenchService::class.java).apply {
            putExtra(BenchService.FOLDER, uri.toString())
            putExtra(BenchService.MODELS, models.filterValues { it.isChecked }.keys.toTypedArray())
            putExtra(BenchService.THREADS, threads.filterValues { it.isChecked }.keys.toIntArray())
            putExtra(BenchService.ARENAS, arenas.filterValues { it.isChecked }.keys.toBooleanArray())
            putExtra(BenchService.PASSES, passes.text.toString().toIntOrNull()?.coerceIn(1, 50) ?: 5)
            putExtra(BenchService.SCREEN_OFF, screenOff.isChecked)
            putExtra(BenchService.CLIPS, clips.isChecked)
            putExtra(BenchService.REFERENCES, references.isChecked)
        })
    }

    private fun hearSongs() {
        val uri = folder() ?: return
        BenchSession.say("starting the whole pipeline…")
        ContextCompat.startForegroundService(this, Intent(this, BenchService::class.java).apply {
            putExtra(BenchService.FOLDER, uri.toString())
            putExtra(BenchService.HEARINGS, true)
        })
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    companion object {
        private const val PICK = 1
        private const val FOLDER = "folder"
        const val HEAR_SONGS = "Hear the songs (B1)"
    }
}
