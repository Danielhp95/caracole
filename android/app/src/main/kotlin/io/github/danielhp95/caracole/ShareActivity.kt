package io.github.danielhp95.caracole

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.util.Log
import android.widget.Toast
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.server.lookups.InboxShare
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.io.ByteArrayOutputStream
import java.io.IOException

/**
 * Files shared to caracole: ACTION_SEND and SEND_MULTIPLE of the stream types the manifest names alone (a Guitar Pro
 * file, MusicXML, a PDF, MIDI, MuseScore; never VIEW, text/plain or any type: a music app's link is
 * ShareLinkActivity's). Each file is read from its EXTRA_STREAM (or the share's ClipData) while the activity holds the
 * share's read grant, with its display name and type, then finished; the phone stages it in `state/inbox/` and queues
 * its filing as the inbox runner's job (server's InboxShare, PhoneKinds' inbox kind), as `_inbox/` files a file on the
 * computer. Once each job is over (or [WAIT_MS] on), a toast says how each went, its line on the Requests tab: "Filed
 * as guitar-1.gp5 of Oasis - Wonderwall", "Waiting for a song that fits: …" (tried again after each sync and lookup,
 * for 30 days), "Not filed: …".
 */
class ShareActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val streams = streams(intent)
        val app = applicationContext
        if (streams.isEmpty()) {
            finish()
            tell(app, NOTHING)
            return
        }
        val type = intent?.type
        Caracole.background.launch(Dispatchers.IO) {
            val read = streams.map { read(it, type) }  // while the share's grant holds: before finish
            withContext(Dispatchers.Main) { finish() }
            val said = try {
                val phone = Caracole.phone(app)
                read.map { file ->
                    val data = file.data ?: return@map PhoneKinds.fill(PhoneKinds.INBOX.failed, "why" to file.why!!)
                    val shared = InboxShare.share(phone.parts, file.name, file.type, data)
                    val job = shared.job ?: return@map shared.said!!
                    val over = withTimeoutOrNull(WAIT_MS) { phone.queue.await(job.id) }
                    JobViews.line(over ?: phone.queue.job(job.id) ?: job).text
                }
            } catch (e: Exception) {
                Log.w(TAG, "a share not filed", e)
                listOf(PhoneKinds.fill(PhoneKinds.INBOX.failed, "why" to (e.message ?: e::class.java.simpleName)))
            }
            tell(app, said.joinToString("\n"))
        }
    }

    /** A file shared: its display name, its type, and its bytes, or why there are none. */
    private class SharedFile(val name: String?, val type: String?, val data: ByteArray?, val why: String?)

    /** The file at [uri], read whole (at most InboxShare.MAX_BYTES), its name the provider's display name, else its
     * address's last part. */
    private fun read(uri: Uri, shareType: String?): SharedFile {
        val name = runCatching {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst() && !c.isNull(0)) c.getString(0) else null
            }
        }.getOrNull() ?: uri.lastPathSegment
        val type = runCatching { contentResolver.getType(uri) }.getOrNull() ?: shareType
        return try {
            val input = contentResolver.openInputStream(uri) ?: throw IOException("its app gave nothing to read")
            val out = ByteArrayOutputStream()
            input.use {
                val buffer = ByteArray(1 shl 16)
                while (true) {
                    val n = it.read(buffer)
                    if (n < 0) break
                    out.write(buffer, 0, n)
                    if (out.size() > InboxShare.MAX_BYTES) {
                        return SharedFile(name, type, null, "${name ?: "the file"} is over ${InboxShare.MAX_BYTES shr 20} MiB")
                    }
                }
            }
            SharedFile(name, type, out.toByteArray(), null)
        } catch (e: Exception) {  // a provider's refusal (SecurityException), a file gone, a read that failed
            Log.w(TAG, "a shared file not read: $uri", e)
            SharedFile(name, type, null, "${name ?: "the file"} couldn't be read (${e.message ?: e::class.java.simpleName})")
        }
    }

    companion object {
        private const val TAG = "caracole-share"

        /** How long the toast waits for the files' jobs: a sync before them may take longer, and the Requests tab
         * says the rest. */
        const val WAIT_MS = 60_000L

        /** What a share with no file says. */
        const val NOTHING = "Nothing to file: the app shared no file"

        /** The last toast a share showed (ShareTest reads it). */
        @Volatile var told: String? = null

        /** Each file of a SEND (EXTRA_STREAM) or SEND_MULTIPLE (its EXTRA_STREAM list), else the share's ClipData. */
        fun streams(intent: Intent?): List<Uri> {
            intent ?: return emptyList()
            val found = LinkedHashSet<Uri>()
            when (intent.action) {
                Intent.ACTION_SEND -> stream(intent)?.let(found::add)
                Intent.ACTION_SEND_MULTIPLE -> found += streamList(intent)
                else -> return emptyList()
            }
            if (found.isEmpty()) {
                val clip = intent.clipData
                if (clip != null) for (i in 0 until clip.itemCount) clip.getItemAt(i).uri?.let(found::add)
            }
            return found.toList()
        }

        @Suppress("DEPRECATION")
        private fun stream(intent: Intent): Uri? =
            if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
            else intent.getParcelableExtra(Intent.EXTRA_STREAM) as? Uri

        @Suppress("DEPRECATION")
        private fun streamList(intent: Intent): List<Uri> =
            (if (Build.VERSION.SDK_INT >= 33) intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
             else intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)).orEmpty().filterNotNull()

        /** [text] as a toast, on the main thread, however the share ended. */
        private fun tell(context: Context, text: String) {
            told = text
            android.os.Handler(android.os.Looper.getMainLooper()).post {
                Toast.makeText(context, text, Toast.LENGTH_LONG).show()
            }
        }
    }
}
