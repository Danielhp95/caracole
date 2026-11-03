package io.github.danielhp95.caracole

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.widget.Toast
import androidx.core.content.FileProvider
import androidx.core.net.toUri
import java.io.File
import java.io.IOException
import java.security.MessageDigest

/** Hands what the WebView doesn't show to another app: a file of the library, or a page on the web. */
object Handoff {
    const val FOLDER = "handoff"
    private const val KEEP_MS = 24 * 60 * 60 * 1000L
    private const val ANY_FILE = "application/octet-stream"
    private const val TMP = ".tmp-"

    /**
     * Opens [copy], the copy of the library's file at [path] ([copyInto]: a PDF, a Guitar Pro file, a .cho), in
     * another app: exposed through the FileProvider and handed over with ACTION_VIEW and its [type]. Android asks which
     * app when several can; a message says so when none can. A file of no known type (caracole sends Guitar Pro files
     * as application/octet-stream) always asks: the one app that takes anything might be no app for it.
     */
    fun openFile(activity: Activity, copy: File, type: String) {
        val uri = FileProvider.getUriForFile(activity, "${activity.packageName}.files", copy)
        val view = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, type)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        val intent = if (type == ANY_FILE) Intent.createChooser(view, activity.getString(R.string.open_with, copy.name)) else view
        try {
            activity.startActivity(intent)
        } catch (e: ActivityNotFoundException) {
            toast(activity, activity.getString(R.string.no_app, copy.name, type))
        }
    }

    /**
     * The copy another app reads of [fetched], the file the phone's server answered for [path]: under [root] (the
     * cache's handoff/), in a folder named for its bytes' SHA-256, named for its path ("Estopa - Tu calorro -
     * sheet.pdf"). The same bytes again are the copy there is. A copy is written under a temporary name and renamed
     * whole, so one cut short leaves nothing; copies a day old go first ([now]).
     */
    fun copyInto(root: File, path: String, fetched: Fetched.File, now: Long = System.currentTimeMillis()): File {
        root.mkdirs()
        root.listFiles()?.forEach { if (now - it.lastModified() > KEEP_MS) it.deleteRecursively() }
        val tmp = File(root, TMP + System.nanoTime())
        try {
            val digest = MessageDigest.getInstance("SHA-256")
            fetched.open().use { input ->
                tmp.outputStream().use { output ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val n = input.read(buffer)
                        if (n < 0) break
                        digest.update(buffer, 0, n)
                        output.write(buffer, 0, n)
                    }
                }
            }
            val folder = File(root, digest.digest().joinToString("") { "%02x".format(it) })
            val copy = File(folder, fileName(path))
            if (copy.isFile && copy.length() == tmp.length()) {
                folder.setLastModified(now)
                return copy
            }
            folder.mkdirs()
            if (!tmp.renameTo(copy)) throw IOException("can't name the copy ${copy.name}")
            folder.setLastModified(now)
            return copy
        } finally {
            tmp.delete()
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
