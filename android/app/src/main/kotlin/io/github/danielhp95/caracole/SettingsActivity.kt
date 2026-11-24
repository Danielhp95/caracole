package io.github.danielhp95.caracole

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
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
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.lookups.CataloguesRunner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Instant

/**
 * The settings: caracole serve's address, Test (the computer at that address asked what it holds, nothing changed:
 * SyncRoutes.tested's words, "studio answered: 96 songs, 3 songbooks, its indexes read 02/11/26"), the storage the
 * copy takes, Sync on Wi-Fi by itself (the bar's sync, unattended: [Syncs]), Export and Import a file (the library
 * page's sync sheet at that flow, MainActivity's [MainActivity.SHEET]), the text size a pinch left, with Reset, and
 * the phone's backups ([BackupsActivity]), and the site catalogues: the newest of the sites' indexes ("Of 3 Nov 2026 ·
 * 3 weeks old", "None yet") and Download the site catalogues, which asks GitHub nothing until it is tapped, then
 * queues CataloguesRunner's job and says its line as it goes ([followCatalogues]); a job a metered network stopped is
 * asked about ("52 MB over mobile data?"), Download then the owner's go-ahead. Syncing itself is the library screen's
 * bar's sync button. No item's text ends in "…".
 */
class SettingsActivity : Activity() {
    private lateinit var settings: Settings
    private lateinit var address: EditText
    private lateinit var testResult: TextView
    private lateinit var storage: TextView
    private lateinit var textSize: TextView
    private lateinit var resetTextSize: Button
    private lateinit var cataloguesDate: TextView
    private lateinit var cataloguesStatus: TextView
    private var scope: CoroutineScope = MainScope()

    /** The catalogues' job followed now, if any. */
    private var following: kotlinx.coroutines.Job? = null

    /** The question a metered network's stop asks, while it is open (a device test answers it). */
    internal var asked: AlertDialog? = null
        private set

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowCompat.getInsetsController(window, window.decorView).isAppearanceLightStatusBars = false
        setContentView(R.layout.activity_settings)
        fitInsets()
        settings = Settings(this)

        address = findViewById(R.id.address)
        testResult = findViewById(R.id.test_result)
        storage = findViewById(R.id.storage)
        textSize = findViewById(R.id.text_size)
        resetTextSize = findViewById(R.id.reset_text_size)
        cataloguesDate = findViewById(R.id.catalogues_date)
        cataloguesStatus = findViewById(R.id.catalogues_status)

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
        findViewById<Button>(R.id.open_library).setOnClickListener { finish() }

        val wifi = findViewById<Switch>(R.id.wifi)
        wifi.isChecked = settings.syncOnWifi
        wifi.setOnCheckedChangeListener { _, on ->
            settings.syncOnWifi = on
            Syncs.onWifi(this, on)
            // The notification of the conflicts it leaves, from Android 13 only once asked.
            if (on) askToNotify()
        }

        findViewById<Button>(R.id.export).setOnClickListener { sheet(EXPORT) }
        findViewById<Button>(R.id.import_file).setOnClickListener { sheet(IMPORT) }

        resetTextSize.setOnClickListener {
            settings.textZoom = TextZoom.DEFAULT
            showTextSize()
        }

        findViewById<Button>(R.id.backups).setOnClickListener { startActivity(Intent(this, BackupsActivity::class.java)) }
        findViewById<Button>(R.id.catalogues_download).setOnClickListener { downloadCatalogues(meteredOk = false) }
    }

    override fun onResume() {
        super.onResume()
        showTextSize()
        showStorage()
        showCatalogues()
        followCatalogues()
    }

    override fun onStart() {
        super.onStart()
        scope = MainScope()
    }

    override fun onStop() {
        scope.cancel()
        super.onStop()
    }

    /** The library page's sync sheet at [flow] (export, import), the address typed kept first: MainActivity, which is
     * single-task, comes to the front with it, and Settings closes. */
    private fun sheet(flow: String) {
        settings.server = address.text.toString().trim()
        startActivity(Intent(this, MainActivity::class.java).putExtra(MainActivity.SHEET, flow))
    }

    /** Android 13 and later show the notification of a sync that left conflicts only once asked. */
    private fun askToNotify() {
        if (Build.VERSION.SDK_INT < 33) return
        if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) return
        requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), NOTIFY)
    }

    /** Asks the computer what it holds, changing nothing, and says it ([Syncs.tested]). */
    private fun test() {
        settings.server = address.text.toString().trim()
        testResult.visibility = View.VISIBLE
        testResult.text = getString(R.string.testing)
        val typed = settings.server
        val app = applicationContext
        scope.launch {
            testResult.text = withContext(Dispatchers.IO) { Syncs.tested(app, typed) }
        }
    }

    /** "Storage used: 41 MB", the copy of the computer's pages; Open the library once there is one. */
    private fun showStorage() {
        val mirror = Caracole.mirror(this)
        scope.launch {
            val bytes = withContext(Dispatchers.IO) { mirror.storageBytes() }
            storage.text = getString(R.string.storage, Syncs.size(this@SettingsActivity, bytes))
        }
        findViewById<View>(R.id.open_library).visibility = if (mirror.manifest() != null) View.VISIBLE else View.GONE
    }

    /** "Of 3 Nov 2026 · 3 weeks old": the newest of the sites' indexes (IndexTransfer.newest), "None yet" without. */
    private fun showCatalogues() {
        val app = applicationContext
        scope.launch {
            val newest = withContext(Dispatchers.IO) {
                Caracole.phone(app).parts.database.read { db -> SiteCatalogues.newest(IndexTransfer.newest(db)) }
            }
            cataloguesDate.text = newest?.let { getString(R.string.catalogues_of, SiteCatalogues.day(it), ageOf(it)) }
                ?: getString(R.string.catalogues_none)
        }
    }

    /** "3 weeks old", "today". */
    private fun ageOf(at: Instant): String {
        val age = SiteCatalogues.age(at, Instant.now())
        val plural = when (age.unit) {
            SiteCatalogues.Unit.TODAY -> return getString(R.string.catalogues_today)
            SiteCatalogues.Unit.DAYS -> R.plurals.catalogues_days
            SiteCatalogues.Unit.WEEKS -> R.plurals.catalogues_weeks
            SiteCatalogues.Unit.MONTHS -> R.plurals.catalogues_months
            SiteCatalogues.Unit.YEARS -> R.plurals.catalogues_years
        }
        return resources.getQuantityString(plural, age.count, age.count)
    }

    /** The catalogues' job queued (the go-ahead with [meteredOk]) and followed. */
    private fun downloadCatalogues(meteredOk: Boolean) {
        val app = applicationContext
        scope.launch {
            val job = withContext(Dispatchers.IO) { SiteCatalogues.queue(Caracole.phone(app), meteredOk) }
            if (job == null) {
                say(getString(R.string.catalogues_queue_full))
            } else {
                follow(job.id)
            }
        }
    }

    /** The newest catalogues job's line (the first start's Download, a tap before this screen was left), followed
     * while it waits or runs, and its end said once if the app queued it and no screen has said it yet. */
    private fun followCatalogues() {
        val app = applicationContext
        scope.launch {
            val job = withContext(Dispatchers.IO) { SiteCatalogues.newestOf(Caracole.phone(app).queue.snapshot()) }
                ?: return@launch
            say(JobViews.line(job).text)
            when {
                !SiteCatalogues.over(job.state) -> follow(job.id)
                SiteCatalogues.toSay(job.id) -> follow(job.id, said = true)  // it ended before this screen showed
            }
        }
    }

    /**
     * Job [id] followed: its line ("Downloading · 31 of 52 MB") as it goes, then the date again and, when a metered
     * network stopped it and its end is still to be said ([SiteCatalogues.toSay]; [said]: already taken for it), the
     * question.
     */
    private fun follow(id: Int, said: Boolean = false) {
        following?.cancel()
        val app = applicationContext
        following = scope.launch {
            val phone = withContext(Dispatchers.IO) { Caracole.phone(app) }
            while (true) {
                val job = phone.queue.job(id) ?: return@launch
                val line = JobViews.line(job)
                say(line.text)
                if (SiteCatalogues.over(job.state)) {
                    showCatalogues()
                    if (!said && !SiteCatalogues.toSay(id)) return@launch
                    val asking = withContext(Dispatchers.IO) {
                        phone.parts.database.read { db -> SiteCatalogues.asking(db.kvGet(CataloguesRunner.ASKING)) }
                    }
                    SiteCatalogues.asks(job.state, line.tone, asking)?.let(::askMetered)
                    return@launch
                }
                delay(FOLLOW_MS)
            }
        }
    }

    /** "52 MB over mobile data?": Download, the go-ahead; Not now leaves the job's line, waiting for Wi-Fi. */
    private fun askMetered(asking: SiteCatalogues.Asking) {
        asked?.dismiss()
        asked = AlertDialog.Builder(this)
            .setTitle(getString(R.string.catalogues_asking_title, SiteCatalogues.size(asking.bytes)))
            .setMessage(R.string.catalogues_asking_message)
            .setPositiveButton(R.string.catalogues_asking_yes) { _, _ -> downloadCatalogues(meteredOk = true) }
            .setNegativeButton(R.string.catalogues_asking_no, null)
            .setOnDismissListener { asked = null }
            .show()
    }

    /** What the catalogues' job says, under its button. */
    private fun say(text: String) {
        cataloguesStatus.visibility = View.VISIBLE
        cataloguesStatus.text = text
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
        const val NOTIFY = 2
        const val FOLLOW_MS = 400L
        const val EXPORT = "export"
        const val IMPORT = "import"
    }
}
