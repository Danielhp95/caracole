package io.github.danielhp95.caracole

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
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
 * the last sync's time and outcome, the storage the copy takes, the sync on Wi-Fi by itself, the computer's indexes
 * imported (from caracole serve, or from a file: [IndexImports]) with the last import's outcome, the text size a
 * pinch left, with Reset, and the phone's backups ([BackupsActivity]).
 */
class SettingsActivity : Activity() {
    private lateinit var settings: Settings
    private lateinit var address: EditText
    private lateinit var testResult: TextView
    private lateinit var lastSync: TextView
    private lateinit var storage: TextView
    private lateinit var lastImport: TextView
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
        lastImport = findViewById(R.id.last_import)
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

        findViewById<Button>(R.id.import_computer).setOnClickListener {
            settings.server = address.text.toString().trim()
            askToNotify()
            importing { IndexImports.fromComputer(it) }
        }
        findViewById<Button>(R.id.import_file).setOnClickListener { pickIndex() }

        resetTextSize.setOnClickListener {
            settings.textZoom = TextZoom.DEFAULT
            showTextSize()
        }

        findViewById<Button>(R.id.backups).setOnClickListener { startActivity(Intent(this, BackupsActivity::class.java)) }
    }

    override fun onResume() {
        super.onResume()
        showTextSize()
    }

    override fun onStart() {
        super.onStart()
        scope = MainScope()
        scope.launch { Caracole.status.collect { show(it) } }
        scope.launch { IndexImports.running.collect { showImport(it) } }
    }

    /** The file to import: any document (an export has no type Android knows); the app keeps the right to read it
     * until the import has copied it. */
    private fun pickIndex() {
        val pick = Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*")
        try {
            startActivityForResult(pick, PICK_INDEX)
        } catch (e: ActivityNotFoundException) {
            Handoff.toast(this, getString(R.string.import_no_picker))
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != PICK_INDEX || resultCode != RESULT_OK) return
        val uri = data?.data ?: return
        try {
            contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
        } catch (e: SecurityException) {
            // A document that can't be kept: the import reads it while the grant lasts.
        }
        askToNotify()
        importing(refused = {
            // Another import is under way: the right to read this one is given back now, never kept for nothing
            // (Android keeps only so many).
            try {
                it.contentResolver.releasePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
            } catch (e: SecurityException) {
                // It wasn't kept: nothing to give back.
            }
        }) { IndexImports.fromFile(it, uri) }
    }

    /**
     * An import asked for ([start]: false while another is under way), in the app's own scope, so leaving the screen
     * at once still starts it; one refused gives back what it holds ([refused]) and says so.
     */
    private fun importing(refused: (Context) -> Unit = {}, start: suspend (Context) -> Boolean) {
        val app = applicationContext
        Caracole.background.launch {
            val said = try {
                if (start(app)) return@launch
                app.getString(R.string.import_under_way)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                // WorkManager couldn't take it: said, never a crash.
                app.getString(R.string.import_not_started, e.message ?: e.javaClass.simpleName)
            }
            refused(app)
            withContext(Dispatchers.Main) { Toast.makeText(app, said, Toast.LENGTH_LONG).show() }
        }
    }

    /** Android 13 and later show the import's notification only once asked; it runs either way. */
    private fun askToNotify() {
        if (Build.VERSION.SDK_INT < 33) return
        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) return
        requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), NOTIFY)
    }

    /** The import's line: what one under way does, else how the last ended. */
    private fun showImport(running: String?) {
        lastImport.text = running ?: IndexImports.line(this, settings.lastImport)
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

    private companion object {
        const val PICK_INDEX = 1
        const val NOTIFY = 2
    }
}
