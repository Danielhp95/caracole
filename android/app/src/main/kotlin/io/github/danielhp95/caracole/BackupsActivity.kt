package io.github.danielhp95.caracole

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import io.github.danielhp95.caracole.core.backup.Backup
import io.github.danielhp95.caracole.core.backup.Backups
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.QueueFull
import io.github.danielhp95.caracole.server.lookups.BackupRunner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.MainScope
import kotlinx.coroutines.async
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

/**
 * The phone's backups, from Settings' Backups row: each listed, newest first (its label, when, its size, and how many
 * of its kept files it doesn't hold: a copy of the tables alone, say), Back up now (a backup by hand), each one's
 * Export (the document picker's ACTION_CREATE_DOCUMENT, a zip of the copy and the files it keeps: Backups.exportTo,
 * which refuses one that doesn't hold them all) and Restore (asked first; refused, nothing changed, when it can't put
 * every kept file's bytes back). A backup and a restore are the phone's queued jobs
 * (BackupRunner's), never run beside a lookup's write, each said on the Requests tab too; once a restore is done, the
 * copy of the computer's library is read again, the search's answers forgotten and the phone's pages made again by
 * the render job ([afterRestore]).
 */
class BackupsActivity : Activity() {
    private lateinit var list: LinearLayout
    private lateinit var none: TextView
    private lateinit var status: TextView
    private lateinit var backupNow: Button
    private var scope: CoroutineScope = MainScope()

    /** The backup an export is under way for, while the picker is open (its file's name). */
    private var exporting: String? = null

    /** The question a Restore asks first, while it is open (a device test answers it). */
    internal var asked: AlertDialog? = null
        private set

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        WindowCompat.getInsetsController(window, window.decorView).isAppearanceLightStatusBars = false
        setContentView(R.layout.activity_backups)
        fitInsets()
        list = findViewById(R.id.backups_list)
        none = findViewById(R.id.backups_none)
        status = findViewById(R.id.backups_status)
        backupNow = findViewById(R.id.backup_now)
        exporting = savedInstanceState?.getString(EXPORTING)
        backupNow.setOnClickListener { backUp() }
        refresh()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        exporting?.let { outState.putString(EXPORTING, it) }
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    /** The backups listed again. */
    private fun refresh() {
        scope.launch {
            val backups = withContext(Dispatchers.IO) { Backups.list(phone().parts.stateDir) }
            show(backups)
        }
    }

    private fun show(backups: List<Backup>) {
        list.removeAllViews()
        none.visibility = if (backups.isEmpty()) View.VISIBLE else View.GONE
        for (backup in backups) list.addView(row(backup))
    }

    /** A backup's row: what it is, then its Export and Restore. */
    private fun row(backup: Backup): View {
        val name = backup.file.name
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            tag = name
            setPadding(0, dp(8), 0, dp(8))
        }
        row.addView(TextView(this).apply {
            val said = getString(R.string.backup_row, labelOf(this@BackupsActivity, backup.label),
                                 BackupRunner.date(backup.at), Syncs.size(this@BackupsActivity, backup.size))
            text = if (backup.missing == 0) said else getString(R.string.backup_row_missing, said, backup.missing)
            setTextColor(getColor(R.color.text))
            textSize = 15f
        })
        val buttons = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        buttons.addView(Button(this).apply {
            text = getString(R.string.backup_export)
            tag = EXPORT_TAG + name
            setOnClickListener { export(backup) }
        })
        buttons.addView(Button(this).apply {
            text = getString(R.string.backup_restore)
            tag = RESTORE_TAG + name
            setOnClickListener { askToRestore(backup) }
        })
        row.addView(buttons)
        return row
    }

    /** A backup made by hand, as a queued job; the list again once it is over. */
    private fun backUp() {
        status.text = getString(R.string.backup_working)
        backupNow.isEnabled = false
        scope.launch {
            val over = queued { phone -> BackupRunner(phone.parts).backup(Backups.BY_HAND) }
            backupNow.isEnabled = true
            status.text = over?.let { JobViews.line(it).text } ?: getString(R.string.backup_queue_full)
            refresh()
        }
    }

    /** The document picker asked for where [backup]'s export goes. */
    private fun export(backup: Backup) {
        exporting = backup.file.name
        val intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
            .addCategory(Intent.CATEGORY_OPENABLE)
            .setType(ZIP)
            .putExtra(Intent.EXTRA_TITLE, Backups.exportName(backup))
        try {
            startActivityForResult(intent, EXPORT)
        } catch (e: android.content.ActivityNotFoundException) {
            exporting = null
            status.text = getString(R.string.backup_no_picker)
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != EXPORT) return
        val name = exporting
        exporting = null
        val uri = data?.data
        if (resultCode != RESULT_OK || uri == null || name == null) return
        status.text = getString(R.string.backup_exporting)
        scope.launch {
            status.text = try {
                withContext(Dispatchers.IO) { exportTo(this@BackupsActivity, phone(), name, uri) }
                getString(R.string.backup_exported)
            } catch (e: Exception) {
                getString(R.string.backup_export_failed, e.message ?: e.javaClass.simpleName)
            }
        }
    }

    private fun askToRestore(backup: Backup) {
        val date = BackupRunner.date(backup.at)
        asked = AlertDialog.Builder(this)
            .setTitle(getString(R.string.backup_restore_title, date))
            .setMessage(R.string.backup_restore_message)
            .setPositiveButton(R.string.backup_restore_yes) { _, _ -> restore(backup) }
            .setNegativeButton(android.R.string.cancel, null)
            .setOnDismissListener { asked = null }
            .show()
    }

    /** [backup] restored as a queued job, then [afterRestore]. */
    private fun restore(backup: Backup) {
        status.text = getString(R.string.backup_restoring)
        scope.launch {
            val over = queued { phone -> BackupRunner(phone.parts).restore(backup) }
            status.text = over?.let { JobViews.line(it).text } ?: getString(R.string.backup_queue_full)
            refresh()
        }
    }

    /** [spec] of the phone queued and awaited in the process's own scope, with what follows a restore done there, so
     * both outlive this screen; null when the queue is full. */
    private suspend fun queued(spec: (Phone) -> JobSpec): Job? {
        val context = applicationContext
        return Caracole.background.async(Dispatchers.IO) {
            val phone = Caracole.phone(context)
            val job = try {
                phone.queue.submit(spec(phone)).first
            } catch (_: QueueFull) {
                return@async null
            }
            val over = phone.queue.await(job.id)
            if (over.spec.kind == RESTORE_KIND && over.state == Job.DONE) afterRestore(context, phone)
            over
        }.await()
    }

    private fun phone(): Phone = Caracole.phone(this)

    private fun fitInsets() {
        val bar = findViewById<View>(R.id.bar)
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.root)) { root, insets ->
            val sys = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            bar.setPadding(bar.paddingLeft, sys.top + dp(10), bar.paddingRight, bar.paddingBottom)
            root.setPadding(sys.left, 0, sys.right, sys.bottom)
            WindowInsetsCompat.CONSUMED
        }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()

    companion object {
        const val EXPORT = 1
        const val ZIP = "application/zip"
        const val EXPORT_TAG = "export:"
        const val RESTORE_TAG = "restore:"
        private const val EXPORTING = "exporting"
        private const val RESTORE_KIND = "restore"

        /** A backup's label as the list says it. */
        fun labelOf(context: Context, label: String?): String = context.getString(when (label) {
            Backups.BY_HAND -> R.string.backup_by_hand
            Backups.DAILY -> R.string.backup_daily
            Backups.BEFORE_SYNC -> R.string.backup_before_sync
            else -> R.string.backup_other
        })

        /** The backup named [name] exported, as one zip, to [uri] (the document the picker made). */
        fun exportTo(context: Context, phone: Phone, name: String, uri: Uri) {
            val file = File(File(phone.parts.stateDir, Backups.FOLDER), name)
            val out = context.contentResolver.openOutputStream(uri, "wt") ?: error("the document can't be written")
            out.use { Backups.exportTo(file, it) }
        }

        /**
         * What follows a restore: the copy of the computer's library read again, the search's answers forgotten, and
         * the phone's pages made again by the render job (the restore owed them all), queued after it; a full queue
         * leaves them owed, for the next start's render job.
         */
        fun afterRestore(context: Context, phone: Phone) {
            Caracole.mirror(context).reload()
            phone.search.invalidate()
            if (phone.render.stale()) {
                try {
                    phone.renderAgain()
                } catch (_: QueueFull) {
                }
            }
        }
    }
}
