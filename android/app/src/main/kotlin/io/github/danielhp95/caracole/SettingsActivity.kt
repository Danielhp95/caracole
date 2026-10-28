package io.github.danielhp95.caracole

import android.app.Activity
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.Switch
import android.widget.TextView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import io.github.danielhp95.caracole.mirror.ServerAddress
import io.github.danielhp95.caracole.mirror.SyncEngine
import io.github.danielhp95.caracole.mirror.SyncError
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * The settings: caracole serve's address, Test (the list fetched and counted, nothing downloaded), Sync now,
 * the last sync's time and outcome, the storage the copy takes, the sync on Wi-Fi by itself, and the text size a
 * pinch left, with Reset.
 */
class SettingsActivity : Activity() {
    private lateinit var settings: Settings
    private lateinit var address: EditText
    private lateinit var testResult: TextView
    private lateinit var lastSync: TextView
    private lateinit var storage: TextView
    private lateinit var textSize: TextView
    private lateinit var resetTextSize: Button
    private var scope: CoroutineScope = MainScope()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowCompat.getInsetsController(window, window.decorView).isAppearanceLightStatusBars = false
        setContentView(R.layout.activity_settings)
        fitInsets()
        settings = Settings(this)

        address = findViewById(R.id.address)
        testResult = findViewById(R.id.test_result)
        lastSync = findViewById(R.id.last_sync)
        storage = findViewById(R.id.storage)
        textSize = findViewById(R.id.text_size)
        resetTextSize = findViewById(R.id.reset_text_size)

        address.setText(settings.server)
        address.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                settings.server = s?.toString().orEmpty().trim()
            }
        })
        address.setOnEditorActionListener { _, action, _ ->
            if (action == EditorInfo.IME_ACTION_DONE) test()
            false
        }

        findViewById<Button>(R.id.test).setOnClickListener { test() }
        findViewById<Button>(R.id.sync).setOnClickListener { Syncs.now(this) }
        findViewById<Button>(R.id.open_library).setOnClickListener { finish() }

        val wifi = findViewById<Switch>(R.id.wifi)
        wifi.isChecked = settings.syncOnWifi
        wifi.setOnCheckedChangeListener { _, on ->
            settings.syncOnWifi = on
            Syncs.onWifi(this, on)
        }

        resetTextSize.setOnClickListener {
            settings.textZoom = TextZoom.DEFAULT
            showTextSize()
        }
    }

    override fun onResume() {
        super.onResume()
        showTextSize()
    }

    override fun onStart() {
        super.onStart()
        scope = MainScope()
        scope.launch { Caracole.status.collect { show(it) } }
    }

    override fun onStop() {
        scope.cancel()
        super.onStop()
    }

    /** Asks caracole for its list, and says what it holds: "caracole answered: 312 files, 41 MB". */
    private fun test() {
        settings.server = address.text.toString().trim()
        testResult.visibility = View.VISIBLE
        testResult.text = getString(R.string.testing)
        val typed = settings.server
        scope.launch {
            val said = withContext(Dispatchers.IO) {
                try {
                    val fetched = SyncEngine(Caracole.mirror(this@SettingsActivity), Caracole.http())
                        .fetchManifest(ServerAddress.parse(typed))
                    val manifest = fetched.manifest
                    val size = Syncs.size(this@SettingsActivity, manifest.bytes)
                    if (manifest.skipped.isEmpty()) getString(R.string.answered, manifest.entries.size, size)
                    else getString(R.string.answered_skipped, manifest.entries.size, size, manifest.skipped.size)
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    // Anything, the unexpected too: said on the screen, never a crash.
                    SyncError.of(e).let { it.message ?: it.javaClass.simpleName }
                }
            }
            testResult.text = said
        }
    }

    /** The last sync's line: how far a running one is, else when the last ended and how. */
    private fun show(state: SyncState) {
        lastSync.text = when (state) {
            is SyncState.Running -> state.progress?.let { getString(R.string.syncing, it.done, it.total) }
                ?: getString(R.string.syncing_asking)
            else -> Syncs.describe(settings.lastOutcome) ?: getString(R.string.never_synced)
        }
        val mirror = Caracole.mirror(this)
        scope.launch {
            val bytes = withContext(Dispatchers.IO) { mirror.storageBytes() }
            storage.text = getString(R.string.storage, Syncs.size(this@SettingsActivity, bytes))
        }
        findViewById<View>(R.id.open_library).visibility = if (mirror.manifest() != null) View.VISIBLE else View.GONE
    }

    /** "Text size: 120%", as the last pinch left it; Reset only when it isn't the pages' own. */
    private fun showTextSize() {
        val zoom = settings.textZoom
        textSize.text = getString(R.string.text_size, zoom)
        resetTextSize.isEnabled = zoom != TextZoom.DEFAULT
    }

    private fun fitInsets() {
        val bar = findViewById<View>(R.id.bar)
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.root)) { root, insets ->
            val sys = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            bar.setPadding(bar.paddingLeft, sys.top + dp(10), bar.paddingRight, bar.paddingBottom)
            root.setPadding(sys.left, 0, sys.right, maxOf(sys.bottom, ime.bottom))
            WindowInsetsCompat.CONSUMED
        }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
