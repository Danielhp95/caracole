package io.github.danielhp95.caracole

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.widget.Toast
import androidx.core.content.FileProvider
import androidx.core.net.toUri
import io.github.danielhp95.caracole.mirror.Served
import java.io.File
import java.io.IOException

/** Hands what the WebView doesn't show to another app: a file of the mirror, or a page on the web. */
object Handoff {
    private const val FOLDER = "handoff"
    private const val KEEP_MS = 24 * 60 * 60 * 1000L
    private const val ANY_FILE = "application/octet-stream"

    /**
     * Opens [served] (a PDF, a Guitar Pro file, a .cho) in another app: a copy named for its path in the cache
     * ("Estopa - Tu calorro - sheet.pdf"), exposed through the FileProvider and handed over with ACTION_VIEW
     * and its type. Android asks which app when several can; a message says so when none can. A file of no
     * known type (caracole sends Guitar Pro files as application/octet-stream) always asks: the one app that
     * takes anything might be no app for it.
     */
    fun openFile(activity: Activity, served: Served) {
        val entry = served.entry
        val root = File(activity.cacheDir, FOLDER)
        root.listFiles()?.forEach { if (System.currentTimeMillis() - it.lastModified() > KEEP_MS) it.deleteRecursively() }
        val copy = File(File(root, entry.sha256), fileName(entry.path))
        try {
            if (!copy.isFile || copy.length() != entry.size) {
                copy.parentFile!!.mkdirs()
                val tmp = File(copy.parentFile, ".tmp-" + System.nanoTime())
                served.file.copyTo(tmp, overwrite = true)
                if (!tmp.renameTo(copy)) throw IOException("can't name the copy ${copy.name}")
            }
        } catch (e: IOException) {
            toast(activity, activity.getString(R.string.handoff_failed, e.message ?: e.javaClass.simpleName))
            return
        }
        val uri = FileProvider.getUriForFile(activity, "${activity.packageName}.files", copy)
        val view = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, entry.mimeType)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        val intent = if (entry.mimeType == ANY_FILE) Intent.createChooser(view, activity.getString(R.string.open_with, copy.name)) else view
        try {
            activity.startActivity(intent)
        } catch (e: ActivityNotFoundException) {
            toast(activity, activity.getString(R.string.no_app, copy.name, entry.mimeType))
        }
    }

    /** Opens [url], an address on the web, in the phone's browser. */
    fun openBrowser(activity: Activity, url: String) {
        val intent = Intent(Intent.ACTION_VIEW, url.toUri()).addCategory(Intent.CATEGORY_BROWSABLE)
        try {
            activity.startActivity(intent)
        } catch (e: ActivityNotFoundException) {
            toast(activity, activity.getString(R.string.no_browser, url))
        }
    }

    /** "Estopa - Tu calorro - sheet.pdf" for "Estopa/Tu calorro/sheet.pdf"; the file's own name if that is too long. */
    fun fileName(path: String): String {
        val joined = path.split('/').joinToString(" - ")
        val name = if (joined.toByteArray().size <= 200) joined else path.substringAfterLast('/')
        return name.replace('\u0000', '_').ifEmpty { "file" }
    }

    fun toast(activity: Activity, text: String) = Toast.makeText(activity, text, Toast.LENGTH_LONG).show()
}
