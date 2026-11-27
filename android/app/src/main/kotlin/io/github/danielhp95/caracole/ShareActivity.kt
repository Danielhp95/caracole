package io.github.danielhp95.caracole

import android.app.Activity
import android.content.ContentResolver
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.util.Log
import android.widget.Toast
import io.github.danielhp95.caracole.core.library.AudioStore
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.http.Refused
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.server.lookups.InboxShare
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.io.IOException

/**
 * Files shared to caracole: ACTION_SEND and SEND_MULTIPLE of the stream types the manifest names (a Guitar Pro file,
 * MusicXML, a PDF, MIDI, MuseScore; never VIEW or text/plain: a music app's link is ShareLinkActivity's). A share of
 * mixed types (any type at all, or any of `application` or `audio`) offers caracole too, as Android matches a wildcard
 * type against any type a filter names: each file of a kind caracole keeps nothing of is answered "Not filed". Each
 * file is read from its EXTRA_STREAM (or the share's ClipData), one at a time, while the activity holds the share's
 * read grant, with its display name and type, and only from a `content:` address ([refused]: a `file:` one could name
 * caracole's own files, its database among them, which its process may open); the phone stages it in `state/inbox/`
 * and queues its filing as the inbox runner's job (server's InboxShare, PhoneKinds' inbox kind), as `_inbox/` files a
 * file on the computer, while the activity is still in front (so the queue's foreground service may start); then it
 * finishes. An audio file (AudioShare.isAudio: an audio type but MIDI's, or an audio extension under a type that says
 * nothing) shared alone is staged as an upload instead, read once from its stream into `state/audio/` (never held
 * whole: AudioRoutes.stageShared), and the library screen opens its page (`/share/audio?upload=ID`: the guess, Make
 * sheet, Cancel); one of a share of several is answered [ONE_AT_A_TIME].
 * Once each job is over (or [WAIT_MS] on), a toast says how each went, its line on the Requests tab: "Filed as
 * guitar-1.gp5 of Oasis - Wonderwall", "Waiting for a song that fits: …" (tried again after each sync and lookup, for
 * 30 days), "Not filed: …", a line a file.
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
            // Read while the share's grant holds, and queued while the activity is in front, so the phone's queue
            // may start its foreground service and keep the process going: then finished. One file at a time, each
            // read, staged and queued apart: one file in memory, and one that fails says so on its own line. An
            // audio file shared alone is staged as an upload (streamed, never held whole) and its page opened.
            val queued = try {
                val phone = runCatching { Caracole.phone(app) }
                streams.map { uri ->
                    val about = about(uri, type)
                    when {
                        !AudioShare.isAudio(about.type, about.name) -> queue(uri, about, phone)
                        streams.size > 1 -> Queued(ONE_AT_A_TIME)
                        else -> audio(uri, about, phone)
                    }
                }
            } finally {
                withContext(Dispatchers.Main) { finish() }
            }
            val said = queued.mapNotNull { q ->
                val job = q.job ?: return@mapNotNull q.said
                val phone = q.phone!!
                val over = withTimeoutOrNull(WAIT_MS) { phone.queue.await(job.id) }
                JobViews.line(over ?: phone.queue.job(job.id) ?: job).text
            }
            tell(app, said.joinToString("\n"))
        }
    }

    /**
     * The audio file at [uri], shared alone: staged through the phone's audio routes (AudioRoutes.stageShared, its
     * stream read once, a chunk at a time), then the library screen opened at its page (`/share/audio?upload=ID`);
     * where the phone makes no sheet, nothing read and the page of its name, which says why; what is said of it
     * where the store refuses it (the store's words) or it can't be read.
     */
    private suspend fun audio(uri: Uri, about: About, phone: Result<Phone>): Queued {
        val name = about.name ?: "the file"
        refused(uri)?.let { return Queued(it) }
        if (about.size != null && about.size > AudioStore.AUDIO_MAX) return Queued(AudioStore.WORDS.getValue("too_big"))
        val page = try {
            val routes = phone.getOrThrow().audioRoutes
            val input = contentResolver.openInputStream(uri) ?: throw IOException("its app gave nothing to read")
            SharedLink.audioPage(input.use { routes.stageShared(it, name) }.id)
        } catch (e: Refused) {  // no sheet is made here: the page says why
            SharedLink.audioPageOf(name)
        } catch (e: AudioStore.AudioError) {
            return Queued(e.message.orEmpty())
        } catch (e: Exception) {
            Log.w(TAG, "a shared audio file not read: $uri", e)
            return Queued("$name couldn't be read (${e.message ?: e::class.java.simpleName})")
        }
        withContext(Dispatchers.Main) {
            startActivity(Intent(this@ShareActivity, MainActivity::class.java).putExtra(SharedLink.PAGE, page))
        }
        opened = page
        return Queued(null)
    }

    /** The file at [uri] read, staged and its filing queued on [phone]'s queue; what is said of it if it can't be. */
    private fun queue(uri: Uri, about: About, phone: Result<Phone>): Queued = try {
        val file = read(uri, about)
        if (file.data == null) {
            Queued(notFiled(file.why!!))
        } else {
            val shared = InboxShare.share(phone.getOrThrow().parts, file.name, file.type, file.data)
            shared.job?.let { Queued(job = it, phone = phone.getOrThrow()) } ?: Queued(shared.said!!)
        }
    } catch (e: Exception) {
        Log.w(TAG, "a shared file not filed: $uri", e)
        Queued(notFiled(e.message ?: e::class.java.simpleName))
    } catch (e: OutOfMemoryError) {  // staging it found no room: said, never a crash
        Log.w(TAG, "a shared file not filed: $uri", e)
        Queued(notFiled("no room to hold it on this phone now"))
    }

    /** A file shared, queued: its [job] on [phone]'s queue, or what is [said] of it. */
    private class Queued(val said: String? = null, val job: Job? = null, val phone: Phone? = null)

    /** A file shared: its display name, its type, and its bytes, or why there are none. */
    private class SharedFile(val name: String?, val type: String?, val data: ByteArray?, val why: String?)

    /** A file shared, before a byte of it is read: its display name (its provider's, else its address's last part),
     * its type (its provider's, else the share's) and the size its provider says, if it says one. */
    private class About(val name: String?, val type: String?, val size: Long?)

    private fun about(uri: Uri, shareType: String?): About {
        if (refused(uri) != null) return About(uri.lastPathSegment, shareType, null)
        val name = runCatching {
            contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst() && !c.isNull(0)) c.getString(0) else null
            }
        }.getOrNull() ?: uri.lastPathSegment
        val type = runCatching { contentResolver.getType(uri) }.getOrNull() ?: shareType
        val size = runCatching {
            contentResolver.query(uri, arrayOf(OpenableColumns.SIZE), null, null, null)?.use { c ->
                if (c.moveToFirst() && !c.isNull(0)) c.getLong(0) else null
            }
        }.getOrNull()
        return About(name, type, size)
    }

    /** The file at [uri], read whole (at most InboxShare.MAX_BYTES: one its provider says is larger refused unread,
     * one that proves larger refused one byte past the limit, [SharedBytes]). */
    private fun read(uri: Uri, about: About): SharedFile {
        val name = about.name
        val type = about.type
        refused(uri)?.let { return SharedFile(name, type, null, it) }
        val tooBig = "${name ?: "the file"} is over ${InboxShare.MAX_BYTES shr 20} MiB"
        if (about.size != null && about.size > InboxShare.MAX_BYTES) return SharedFile(name, type, null, tooBig)
        return try {
            val input = contentResolver.openInputStream(uri) ?: throw IOException("its app gave nothing to read")
            val data = input.use { SharedBytes.readAtMost(it, InboxShare.MAX_BYTES) }
                ?: return SharedFile(name, type, null, tooBig)
            SharedFile(name, type, data, null)
        } catch (e: Exception) {  // a provider's refusal (SecurityException), a file gone, a read that failed
            Log.w(TAG, "a shared file not read: $uri", e)
            SharedFile(name, type, null, "${name ?: "the file"} couldn't be read (${e.message ?: e::class.java.simpleName})")
        } catch (e: OutOfMemoryError) {  // no room for it beside what the app holds: said, never a crash
            Log.w(TAG, "a shared file too big to hold: $uri", e)
            SharedFile(name, type, null, "${name ?: "the file"} is too big to read on this phone now")
        }
    }

    companion object {
        private const val TAG = "caracole-share"

        /** How long the toast waits for the files' jobs: a sync before them may take longer, and the Requests tab
         * says the rest. */
        const val WAIT_MS = 60_000L

        /** What each audio file of a share of several says: one is staged at a time (§8.2). */
        const val ONE_AT_A_TIME = "Share one audio file at a time."

        /** The page the last audio file shared opened (ShareAudioTest reads it). */
        @Volatile var opened: String? = null

        /** What a share with no file says. */
        const val NOTHING = "Nothing to file: the app shared no file"

        /**
         * Why the file at [uri] is never read: an address that isn't a content provider's (a `file:` path, which
         * caracole's own process could open, its database and settings among them, whatever app named it); null for
         * a `content:` one, read with the grant its app gave. (caracole's own FileProvider shares only the cache's
         * `handoff/`, the copies of the library's files it handed to other apps.)
         */
        fun refused(uri: Uri): String? = when (val scheme = uri.scheme) {
            ContentResolver.SCHEME_CONTENT -> null
            null -> "caracole reads a shared file from the app that shares it alone, never an address with no scheme"
            else -> "caracole reads a shared file from the app that shares it alone, never a $scheme: address"
        }

        /** PhoneKinds' line for a file not filed, and [why]. */
        private fun notFiled(why: String): String = PhoneKinds.fill(PhoneKinds.INBOX.failed, "why" to why)

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
            if (text.isEmpty()) return  // an audio file's page opened: nothing else to say
            android.os.Handler(android.os.Looper.getMainLooper()).post {
                Toast.makeText(context, text, Toast.LENGTH_LONG).show()
            }
        }
    }
}
