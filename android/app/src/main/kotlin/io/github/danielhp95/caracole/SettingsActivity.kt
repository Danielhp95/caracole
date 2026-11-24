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
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.lookups.CataloguesRunner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.async
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
 * the phone's backups ([BackupsActivity]), and the site catalogues: the date of the ones imported last ("Of 24 Nov
 * 2026 · 3 weeks old"), or of the computer's indexes a sync merged ("The computer's indexes, of 3 Nov 2026 · …"),
 * "None yet" for neither (SiteCatalogues.fresh), and Download the site catalogues, which asks GitHub nothing until it
 * is tapped, then queues CataloguesRunner's job and says its line as it goes ([followCatalogues]); a job a metered
 * network stopped is asked about ("52 MB on a metered network?"), whoever queued it (the Journal's Try again too),
 * Download then the owner's go-ahead, the question kept for the next screen until it is answered (a rotation's). A
 * phone's caracole that can't start is said under the catalogues' button ("Couldn't start · …"), never a crash, and
 * its start tried again as the screen comes back. Syncing itself is the library screen's bar's sync button.
 * No item's text ends in "…".
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

    /** The job [asked] is about (SiteCatalogues.keyOf). */
    private var askedFor: String? = null

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
        if (startFailed) starting = null  // a start that failed is tried again as the screen comes back, once
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

    override fun onDestroy() {
        // A rotation, say: the question goes with its window, unanswered (Settings.cataloguesAnswered not written), so
        // the next screen asks it again, and no window is leaked.
        asked?.let { it.setOnDismissListener(null); it.dismiss() }
        asked = null
        askedFor = null
        super.onDestroy()
    }

    /** The phone's caracole asked for, should the library screen's start have failed, once each time the screen comes
     * back (onResume), never once a row: an update's migration that ran out of room is long. In the process's scope. */
    private var starting: Deferred<Result<Phone>>? = null
    private var startFailed = false

    /** The phone's caracole, or null once why it can't start is said ([cantStart]). */
    private suspend fun phone(): Phone? {
        val app = applicationContext
        val asked = starting ?: Caracole.background.async(Dispatchers.IO) { guarded { Caracole.phone(app) } }
            .also { starting = it }
        val started = asked.await()
        startFailed = started.isFailure
        return started.onFailure(::cantStart).getOrNull()
    }

    /** "Couldn't start · database or disk is full", under the catalogues' button: the library screen's words. */
    private fun cantStart(e: Throwable) = say(getString(R.string.no_server, why(e)))

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

    /** "Of 24 Nov 2026 · 3 weeks old", the catalogues imported last; "The computer's indexes, of …", a sync's; "None
     * yet" (SiteCatalogues.fresh). */
    private fun showCatalogues() {
        scope.launch {
            val phone = phone() ?: return@launch
            val fresh = withContext(Dispatchers.IO) {
                guarded { phone.parts.database.read { db -> SiteCatalogues.read(db) } }
            }.onFailure(::cantStart).getOrElse { return@launch }
            cataloguesDate.text = when (fresh?.source) {
                null -> getString(R.string.catalogues_none)
                SiteCatalogues.Source.CATALOGUES -> getString(R.string.catalogues_of, SiteCatalogues.day(fresh.at), ageOf(fresh.at))
                SiteCatalogues.Source.COMPUTER ->
                    getString(R.string.catalogues_of_computer, SiteCatalogues.day(fresh.at), ageOf(fresh.at))
            }
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
        scope.launch {
            val phone = phone() ?: return@launch
            val job = withContext(Dispatchers.IO) { SiteCatalogues.queue(phone, meteredOk) }
            if (job == null) {
                say(getString(R.string.catalogues_queue_full))
            } else {
                follow(job.id)
            }
        }
    }

    /** The newest catalogues job's line (the first start's Download, the Journal's Try again, a tap before this screen
     * was left), followed while it waits or runs, then its end ([ended]). */
    private fun followCatalogues() {
        scope.launch {
            val phone = phone() ?: return@launch
            val job = SiteCatalogues.newestOf(phone.queue.snapshot()) ?: return@launch
            say(JobViews.line(job).text)
            if (!SiteCatalogues.over(job.state)) follow(job.id) else ended(phone, job)
        }
    }

    /** Job [id] followed: its line ("Downloading · 31 of 52 MB") as it goes, then the date again and its end. */
    private fun follow(id: Int) {
        following?.cancel()
        following = scope.launch {
            val phone = phone() ?: return@launch
            while (true) {
                val job = phone.queue.job(id) ?: return@launch
                say(JobViews.line(job).text)
                if (SiteCatalogues.over(job.state)) {
                    showCatalogues()
                    ended(phone, job)
                    return@launch
                }
                delay(FOLLOW_MS)
            }
        }
    }

    /**
     * [job] over: when it is the newest catalogues job and stopped at the metered step, its file named in kv
     * `catalogues:asking`, the question, whoever queued it (SiteCatalogues.question), until it is answered.
     */
    private suspend fun ended(phone: Phone, job: Job) {
        if (SiteCatalogues.newestOf(phone.queue.snapshot())?.id != job.id) return
        val asking = withContext(Dispatchers.IO) {
            guarded { phone.parts.database.read { db -> SiteCatalogues.asking(db.kvGet(CataloguesRunner.ASKING)) } }
                .getOrNull()
        }
        val key = SiteCatalogues.keyOf(job.id, job.queuedAt)
        SiteCatalogues.question(job.state, JobViews.line(job).tone, asking, key, settings.cataloguesAnswered)
            ?.let { askMetered(key, it) }
    }

    /** "52 MB on a metered network?": Download, the go-ahead; Not now (or Back) leaves the job's line, waiting for it.
     * Either answer is kept ([Settings.cataloguesAnswered]) for job [key]; the window going without one (a rotation)
     * leaves it to ask again. */
    private fun askMetered(key: String, asking: SiteCatalogues.Asking) {
        if (askedFor == key && asked?.isShowing == true) return
        asked?.let { it.setOnDismissListener(null); it.dismiss() }
        askedFor = key
        asked = AlertDialog.Builder(this)
            .setTitle(getString(R.string.catalogues_asking_title, SiteCatalogues.size(asking.bytes)))
            .setMessage(R.string.catalogues_asking_message)
            .setPositiveButton(R.string.catalogues_asking_yes) { _, _ ->
                settings.cataloguesAnswered = key
                downloadCatalogues(meteredOk = true)
            }
            .setNegativeButton(R.string.catalogues_asking_no) { _, _ -> settings.cataloguesAnswered = key }
            .setOnCancelListener { settings.cataloguesAnswered = key }
            .setOnDismissListener {
                asked = null
                askedFor = null
            }
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
