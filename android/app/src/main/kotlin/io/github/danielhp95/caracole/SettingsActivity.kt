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
import android.util.Log
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
import io.github.danielhp95.caracole.server.YouTubeRow
import io.github.danielhp95.caracole.server.lookups.YouTubeAuto
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.QueueFull
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
 * copy takes, Sync beside Test (the library page's sync sheet at its sync flow, for the address typed; a blank one
 * is said as Test says it, and nothing opens), Sync on Wi-Fi by itself (the bar's sync, unattended: [Syncs]), Export and Import a file (the library
 * page's sync sheet at that flow, MainActivity's [MainActivity.SHEET]), the text size a pinch left, with Reset, and
 * the phone's backups ([BackupsActivity]), and the site catalogues: the date of the ones imported last ("Of 24 Nov
 * 2026 · 3 weeks old"), or of the computer's indexes a sync merged ("From the computer · 3 Nov 2026 · …"), else of
 * the indexes the phone holds, "None yet" for none (SiteCatalogues.fresh), and Download the site catalogues, which asks GitHub nothing until it
 * is tapped, then queues CataloguesRunner's job and says its line as it goes ([followCatalogues]); a job a metered
 * network stopped is asked about ("52 MB on a metered network?") while the network is still metered, whoever queued
 * it (the Journal's Try again too), Download then the owner's go-ahead, the question kept for the next screen until it
 * is answered (a rotation's). Download asks to show notifications first, the download's own with its bar. A
 * Chords from audio (ChordModelsRow): the models' line ("Not downloaded · 55 MB", "Downloading · 21 of 55 MB",
 * "Ready · 55 MB on the phone", "Not downloaded: {why}", "Waiting for your go-ahead (a metered network)"), Download
 * (§6's question, then a metered network's, then ModelsRunner's job queued, its line followed) and Remove (its
 * question, then ModelsRunner.remove, its refusal said); in the debug build, the Chords bench after it. A
 * phone's caracole that can't start is said under the catalogues' button ("Couldn't start · …"), never a crash, and
 * its start tried again as the screen comes back. YouTube audio ([YouTubeRow], the phone-youtube design's §7) says
 * what a sheet from a YouTube video stands on now ("On · yt-dlp 2026.11.23 · 2 of 50 runs in the last 24 hours",
 * off, the chord models needed, a cooldown, out of date), none in a build without yt-dlp; in the debug build, the
 * YouTube bench after it. The library screen's bar has the same sync button.
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
    private lateinit var chordsLine: TextView
    private lateinit var chordsDownload: Button
    private lateinit var chordsRemove: Button
    private lateinit var chordsStatus: TextView
    private var scope: CoroutineScope = MainScope()

    /** The catalogues' job followed now, if any. */
    private var following: kotlinx.coroutines.Job? = null

    /** The question a metered network's stop asks, while it is open (a device test answers it). */
    internal var asked: AlertDialog? = null
        private set

    /** The job [asked] is about (SiteCatalogues.keyOf). */
    private var askedFor: String? = null

    /** The chord models' job followed now, if any. */
    private var followingChords: kotlinx.coroutines.Job? = null

    /** The chords row's question open now (Download's, the metered network's, Remove's; a device test answers it). */
    internal var chordsAsked: AlertDialog? = null
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
        chordsLine = findViewById(R.id.chords_line)
        chordsDownload = findViewById(R.id.chords_download)
        chordsRemove = findViewById(R.id.chords_remove)
        chordsStatus = findViewById(R.id.chords_status)

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

        findViewById<Button>(R.id.open_sync).setOnClickListener { openSync() }
        findViewById<Button>(R.id.export).setOnClickListener { sheet(EXPORT) }
        findViewById<Button>(R.id.import_file).setOnClickListener { sheet(IMPORT) }

        resetTextSize.setOnClickListener {
            settings.textZoom = TextZoom.DEFAULT
            showTextSize()
        }

        findViewById<Button>(R.id.backups).setOnClickListener { startActivity(Intent(this, BackupsActivity::class.java)) }
        if (BuildConfig.CHORDS_BENCH) addChordsBench()
        if (BuildConfig.DEBUG) addYouTubeBench()
        findViewById<Button>(R.id.catalogues_download).setOnClickListener { downloadCatalogues(meteredOk = false) }
        chordsDownload.setOnClickListener { askToDownloadChords() }
        chordsRemove.setOnClickListener { askToRemoveChords() }
        // The first start's Download (MainActivity), which queued the job and opened this screen: asked here, on top.
        if (savedInstanceState == null && intent.getBooleanExtra(ASK_TO_NOTIFY, false)) askToNotify()
    }

    override fun onResume() {
        super.onResume()
        if (startFailed) starting = null  // a start that failed is tried again as the screen comes back, once
        showTextSize()
        showStorage()
        showCatalogues()
        followCatalogues()
        followChords()
        showYouTube()
    }

    /** Settings' YouTube audio row (YouTubeRow): its line read off the main thread, as the screen comes back; no row in
     * a build that carries no yt-dlp (the phone's engine decides, before its problem is read), and none while the
     * phone's caracole can't start (said under the catalogues' button). A read that fails is said in the row, and
     * logged, as the catalogues' date says its failure. */
    private fun showYouTube() {
        scope.launch {
            val phone = phone() ?: return@launch
            val row = findViewById<View>(R.id.youtube_row)
            if (phone.youtube == null) {
                row.visibility = View.GONE
                return@launch
            }
            val read = withContext(Dispatchers.IO) {
                runCatching {
                    val problem = phone.youtubeProblem()
                    phone.parts.database.read { db ->
                        YouTubeRow.line(YouTubeRow.of(db, engine = true, problem = problem,
                                                      version = BuildConfig.YTDLP_VERSION, now = Instant.now())) to
                            YouTubeAuto.on(db)
                    }
                }
            }
            // The automatic pass's switch: as the phone holds it; a read that failed leaves it unknown (off, and not to
            // be pressed), a write that fails puts it back and says so.
            val auto = findViewById<Switch>(R.id.youtube_auto)
            auto.setOnCheckedChangeListener(null)
            val known = read.getOrNull()?.second
            auto.isChecked = known == true
            auto.isEnabled = known != null
            var reverting = false
            auto.setOnCheckedChangeListener { button, on ->
                if (reverting) return@setOnCheckedChangeListener
                scope.launch {
                    val kept = withContext(Dispatchers.IO) {
                        runCatching { phone.parts.database.writeBlocking { db -> YouTubeAuto.set(db, on) } }
                    }
                    kept.onFailure { e ->  // not kept: the switch back as it was, and said
                        Log.w("caracole", "the automatic YouTube pass's switch couldn't be kept", e)
                        reverting = true
                        button.isChecked = !on
                        reverting = false
                        findViewById<TextView>(R.id.youtube_line).text = getString(R.string.youtube_auto_failed, why(e))
                        return@launch
                    }
                    val scheduled = withContext(Dispatchers.IO) {
                        runCatching { YouTubeWorker.schedule(this@SettingsActivity, phone) }
                    }
                    scheduled.onFailure { e ->  // kept as written; its work not (re)scheduled, said
                        Log.w("caracole", "the automatic YouTube pass's work couldn't be scheduled", e)
                        findViewById<TextView>(R.id.youtube_line).text =
                            getString(R.string.youtube_auto_unscheduled, why(e))
                    }
                }
            }
            val line = read.map { it.first }.getOrElse { e ->
                Log.w("caracole", "Settings' YouTube audio row couldn't be read", e)
                getString(R.string.youtube_failed, why(e))
            }
            row.visibility = if (line == null) View.GONE else View.VISIBLE
            findViewById<TextView>(R.id.youtube_line).text = line.orEmpty()
        }
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
        chordsAsked?.let { it.setOnDismissListener(null); it.dismiss() }
        chordsAsked = null
        super.onDestroy()
    }

    /** The phone's caracole asked for, should the library screen's start have failed, once each time the screen comes
     * back (onResume), never once a row: an update's migration that ran out of room is long. In the process's scope. */
    private var starting: Deferred<Result<Phone>>? = null
    private var startFailed = false

    /** The phone's caracole, or null once why it can't start is said ([cantStart]). */
    private suspend fun phone(): Phone? {
        val app = applicationContext
        val asked = starting ?: Caracole.background.async(Dispatchers.IO) { guarded("the phone's caracole didn't start") { Caracole.phone(app) } }
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

    /** Sync: the sheet at its sync flow for the address typed; with none, Test's own words for it, in place. */
    private fun openSync() {
        if (address.text.toString().isBlank()) test() else sheet(MainActivity.SYNC)
    }

    /** Android 13 and later show the notification of a sync that left conflicts, and the site catalogues' download's
     * (SyncService, its bar), only once asked. */
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

    /** "Of 24 Nov 2026 · 3 weeks old", the catalogues imported last (or, neither imported nor synced, the newest
     * sitemap or listing read the phone's indexes hold); "From the computer · …", a sync's; "None yet"
     * (SiteCatalogues.fresh). */
    private fun showCatalogues() {
        scope.launch {
            val phone = phone() ?: return@launch
            val fresh = withContext(Dispatchers.IO) {
                guarded("the site indexes' date couldn't be read") { phone.parts.database.read { db -> SiteCatalogues.read(db) } }
            }.getOrElse {
                say(getString(R.string.catalogues_date_failed, why(it)))
                return@launch
            }
            cataloguesDate.text = when (fresh?.source) {
                null -> getString(R.string.catalogues_none)
                SiteCatalogues.Source.CATALOGUES, SiteCatalogues.Source.INDEXES ->
                    getString(R.string.catalogues_of, SiteCatalogues.day(fresh.at), ageOf(fresh.at))
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

    /** The catalogues' job queued (the go-ahead with [meteredOk]) and followed, asking first to show notifications
     * (the download's, with its bar). */
    private fun downloadCatalogues(meteredOk: Boolean) {
        askToNotify()
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
            say(lineOf(phone, job))
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
                say(lineOf(phone, job))
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
     * `catalogues:asking`, the question, whoever queued it (SiteCatalogues.question), until it is answered, and only
     * while the network is metered now (Caracole.metered: back on Wi-Fi, the next tap downloads).
     */
    private suspend fun ended(phone: Phone, job: Job) {
        if (SiteCatalogues.newestOf(phone.queue.snapshot())?.id != job.id) return
        val app = applicationContext
        val (asking, metered) = withContext(Dispatchers.IO) {
            guarded("the catalogues' question couldn't be read") {
                phone.parts.database.read { db -> SiteCatalogues.asking(db.kvGet(CataloguesRunner.ASKING)) }
            }
                .getOrNull() to Caracole.metered(app)
        }
        val key = SiteCatalogues.keyOf(job.id, job.queuedAt)
        SiteCatalogues.question(job.state, JobViews.line(job).tone, asking, key, settings.cataloguesAnswered, metered)
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

    /** [job]'s line as the Journal says it: queued, the jobs before it and the long job of the phone's own it waits
     * behind ("Queued · after the sync (Updating the indexes · …)", JobViews.behind). */
    private fun lineOf(phone: Phone, job: Job): String {
        val jobs = phone.queue.snapshot()
        val ahead = if (job.state == Job.QUEUED) jobs.count { it.active && it.id < job.id } else 0
        return JobViews.line(job, ahead, behind = JobViews.behind(job, jobs)).text
    }

    /** What the catalogues' job says, under its button. */
    private fun say(text: String) {
        cataloguesStatus.visibility = View.VISIBLE
        cataloguesStatus.text = text
    }

    // --- Chords from audio (ChordModelsRow) --------------------------------------------------------------------------

    /** The row as the phone has it now: the models' size, whether they are here (ModelsRunner.ready, the files'
     * answer), what keeps this phone from chords whatever the models (Phone.chordsProblem), the newest models job. */
    private suspend fun chordsRow(phone: Phone): ChordModelsRow.Row = withContext(Dispatchers.IO) {
        ChordModelsRow.of(phone.models.bytes(), phone.models.ready(), phone.chordsProblem(),
                          ChordModelsRow.lastOf(phone.queue.snapshot()))
    }

    /** The row drawn: its line, Download (with the models' size) and Remove where it offers them. */
    private fun showChords(row: ChordModelsRow.Row, bytes: Long?) {
        chordsLine.text = when (row.line) {
            ChordModelsRow.Line.NOT_DOWNLOADED -> getString(R.string.chords_not_downloaded, row.text)
            ChordModelsRow.Line.DOWNLOADING -> getString(R.string.chords_downloading, row.text)
            ChordModelsRow.Line.READY -> getString(R.string.chords_ready, row.text)
            ChordModelsRow.Line.CANT -> getString(R.string.chords_cant, row.text)
            ChordModelsRow.Line.WAITING -> getString(R.string.chords_waiting)
        }
        chordsDownload.visibility = if (row.download) View.VISIBLE else View.GONE
        bytes?.let { chordsDownload.text = getString(R.string.chords_download, SiteCatalogues.size(it)) }
        chordsRemove.visibility = if (row.remove) View.VISIBLE else View.GONE
    }

    /** The row drawn now, then followed while the newest models job waits or runs ("Downloading · 21 of 55 MB"). */
    private fun followChords() {
        followingChords?.cancel()
        followingChords = scope.launch {
            val phone = phone() ?: return@launch
            while (true) {
                val row = chordsRow(phone)
                showChords(row, phone.models.bytes())
                if (row.line != ChordModelsRow.Line.DOWNLOADING) return@launch
                delay(FOLLOW_MS)
            }
        }
    }

    /** Download: §6's question with what a download would ask for now (ModelsRunner.toDownload: a file a failed
     * download kept is no download), then, on a metered network, its own; then the `models` job queued, the second
     * answer its go-ahead (ModelsRunner.spec(meteredOk)). */
    private fun askToDownloadChords() {
        scope.launch {
            val phone = phone() ?: return@launch
            val app = applicationContext
            val (left, metered) = withContext(Dispatchers.IO) { phone.models.toDownload() to Caracole.metered(app) }
            val size = SiteCatalogues.size(left ?: phone.models.bytes() ?: 0)
            askChords(AlertDialog.Builder(this@SettingsActivity)
                .setTitle(R.string.chords_ask_title)
                .setMessage(getString(R.string.chords_ask_message, size))
                .setPositiveButton(R.string.chords_ask_yes) { _, _ ->
                    if (metered) askMetered(size) else downloadChords(meteredOk = false)
                }
                .setNegativeButton(R.string.chords_ask_no, null))
        }
    }

    /** "You're on a metered network. Download 55 MB anyway?": Download, the go-ahead; Not now queues nothing. */
    private fun askMetered(size: String) {
        askChords(AlertDialog.Builder(this)
            .setMessage(getString(R.string.chords_metered, size))
            .setPositiveButton(R.string.chords_ask_yes) { _, _ -> downloadChords(meteredOk = true) }
            .setNegativeButton(R.string.chords_ask_no, null))
    }

    /** The `models` job queued and followed; the queue full said. */
    private fun downloadChords(meteredOk: Boolean) {
        askToNotify()
        scope.launch {
            val phone = phone() ?: return@launch
            val queued = withContext(Dispatchers.IO) {
                try {
                    phone.queue.submit(phone.models.spec(meteredOk)).first
                } catch (_: QueueFull) {
                    null
                }
            }
            if (queued == null) sayChords(getString(R.string.chords_queue_full)) else chordsStatus.visibility = View.GONE
            followChords()
        }
    }

    /** Remove: its question, then ModelsRunner.remove (refused while a job uses the models, said in its words). */
    private fun askToRemoveChords() {
        askChords(AlertDialog.Builder(this)
            .setTitle(R.string.chords_remove_title)
            .setMessage(R.string.chords_remove_message)
            .setPositiveButton(R.string.chords_remove_yes) { _, _ -> removeChords() }
            .setNegativeButton(R.string.chords_remove_no, null))
    }

    private fun removeChords() {
        scope.launch {
            val phone = phone() ?: return@launch
            val refused = withContext(Dispatchers.IO) { phone.models.remove() }
            if (refused != null) sayChords(refused) else chordsStatus.visibility = View.GONE
            followChords()
        }
    }

    private fun askChords(builder: AlertDialog.Builder) {
        chordsAsked?.let { it.setOnDismissListener(null); it.dismiss() }
        chordsAsked = builder.setOnDismissListener { chordsAsked = null }.show()
    }

    /** What the chords row's actions say, under its buttons. */
    private fun sayChords(text: String) {
        chordsStatus.visibility = View.VISIBLE
        chordsStatus.text = text
    }

    /** "Text size: 120%", as the last pinch left it; Reset only when it isn't the pages' own. */
    private fun showTextSize() {
        val zoom = settings.textZoom
        textSize.text = getString(R.string.text_size, zoom)
        resetTextSize.isEnabled = zoom != TextZoom.DEFAULT
    }

    /** The debug build's Chords bench (src/debugMl's ChordsBenchActivity, the chords-on-the-phone design's §9.1), a
     * button in the Chords from audio section, after its hint: a debug build with :ml alone (BuildConfig.CHORDS_BENCH,
     * false in a release and in a debug build of another shell, and R8 drops this). */
    private fun addChordsBench() {
        val backups = findViewById<Button>(R.id.backups)
        val rows = backups.parent as android.view.ViewGroup
        val button = Button(this).apply {
            text = CHORDS_BENCH
            setOnClickListener {
                startActivity(Intent().setClassName(this@SettingsActivity, "$PACKAGE.ChordsBenchActivity"))
            }
        }
        rows.addView(button, rows.indexOfChild(findViewById(R.id.chords_hint)) + 1)  // in the Chords from audio section
    }

    /** The debug build's YouTube bench (src/debug's YouTubeBenchActivity, the phone-youtube design's §4.2), a button
     * right after the YouTube audio row, by its class's name alone (a main source names no debug class); a release has
     * none (BuildConfig.DEBUG is false there, and R8 drops this). */
    private fun addYouTubeBench() {
        val youtube = findViewById<View>(R.id.youtube_row)
        val rows = youtube.parent as android.view.ViewGroup
        val button = Button(this).apply {
            text = YOUTUBE_BENCH
            setOnClickListener {
                startActivity(Intent().setClassName(this@SettingsActivity, "$PACKAGE.YouTubeBenchActivity"))
            }
        }
        rows.addView(button, rows.indexOfChild(youtube) + 1)  // in the YouTube audio section
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

    companion object {
        /** The debug build's Chords bench row's words (ChordsBenchTest finds it by them). */
        const val CHORDS_BENCH = "Chords bench"

        /** The debug build's YouTube bench row's words (YouTubeBenchTest finds it by them). */
        const val YOUTUBE_BENCH = "YouTube bench"
        private const val PACKAGE = "io.github.danielhp95.caracole"

        /** An extra: ask to show notifications as the screen opens (the first start's Download of the catalogues). */
        const val ASK_TO_NOTIFY = "io.github.danielhp95.caracole.ASK_TO_NOTIFY"

        private const val NOTIFY = 2
        private const val FOLLOW_MS = 400L
        private const val EXPORT = "export"
        private const val IMPORT = "import"
    }
}
