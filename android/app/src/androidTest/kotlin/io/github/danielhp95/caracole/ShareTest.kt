package io.github.danielhp95.caracole

import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import androidx.core.content.FileProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.server.Phone
import io.github.danielhp95.caracole.server.jobs.JobSpec
import io.github.danielhp95.caracole.server.lookups.InboxShare
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * Files shared to caracole, in the app (no computer; CaracoleTestRunner: every site refused):
 *
 *     android/scripts/device-test.sh io.github.danielhp95.caracole.ShareTest
 *
 * A share as Android's share sheet sends it to ShareActivity (SEND or SEND_MULTIPLE of a stream, the file behind a
 * content URI of the app's own FileProvider): each file is filed as `_inbox/` files one, for the song its name is of,
 * and the toast says so in the Requests tab's words; one no song fits waits in `state/inbox/` and is filed once a song
 * that fits is added (the phone's afterJob); a file of a kind caracole keeps nothing of is never staged; and the
 * share filters offer caracole for files alone, never for a text, a VIEW or any type.
 */
@RunWith(AndroidJUnit4::class)
class ShareTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private lateinit var phone: Phone

    @Before fun thePhone() {
        phone = Caracole.phone(context)
    }

    private fun add(artist: String, title: String): SongRow =
        phone.parts.database.writeBlocking { db -> phone.parts.store.add(db, artist, title, now = "2026-11-10T00:00:00Z") }

    /** [name] with [data] behind a content URI of the app's FileProvider, as a file manager or a browser shares one. */
    private fun uri(name: String, data: ByteArray): Uri {
        val file = File(File(context.cacheDir, "handoff/share-test"), name).apply {
            parentFile!!.mkdirs()
            writeBytes(data)
        }
        return FileProvider.getUriForFile(context, "${context.packageName}.files", file)
    }

    /** A share of [uris] to ShareActivity, and the toast it ends with. */
    private fun share(type: String, vararg uris: Uri): String {
        ShareActivity.told = null
        val intent = if (uris.size == 1) {
            Intent(Intent.ACTION_SEND).putExtra(Intent.EXTRA_STREAM, uris[0])
        } else {
            Intent(Intent.ACTION_SEND_MULTIPLE).putParcelableArrayListExtra(Intent.EXTRA_STREAM, ArrayList(uris.toList()))
        }
        context.startActivity(intent.setClass(context, ShareActivity::class.java).setType(type)
                                  .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION))
        return waitFor("the share's toast") { ShareActivity.told }
    }

    private fun <T : Any> waitFor(what: String, seconds: Int = 60, value: () -> T?): T {
        val until = System.nanoTime() + seconds * 1_000_000_000L
        while (System.nanoTime() < until) {
            value()?.let { return it }
            Thread.sleep(50)
        }
        throw AssertionError("no $what in ${seconds}s")
    }

    private fun kept(song: SongRow): List<String> =
        phone.parts.database.read { db -> Kept.keptFiles(db, song.id) }.map { it.name }

    private fun waiting(): List<String> = InboxShare.folder(phone.parts).waiting()

    private val gp5 = byteArrayOf(24) + "FICHIER GUITAR PRO v5.00".toByteArray() + ByteArray(16)

    @Test fun aGuitarProFileSharedIsFiledForItsSong() {
        val song = add("Share Test", "A Song Filed")
        val said = share("application/octet-stream", uri("Share Test - A Song Filed.gp5", gp5))
        assertEquals("Filed as guitar-1.gp5 of Share Test - A Song Filed", said)
        assertEquals(listOf("guitar-1.gp5"), kept(song))
        assertTrue(File(phone.parts.store.folderOf(song), "guitar-1.gp5").readBytes().contentEquals(gp5))
        assertFalse("Share Test - A Song Filed.gp5" in waiting())
        val job = phone.queue.snapshot().first { it.key == "inbox:Share Test - A Song Filed.gp5" }
        assertEquals(song.id, job.songId)
    }

    @Test fun filesSharedTogetherAreEachFiledOrWaitForASongThatFits() {
        val song = add("Share Test", "Two At Once")
        val said = share("*/*", uri("Share Test - Two At Once.pdf", "%PDF-1.4 score".toByteArray()),
                         uri("Share Test - Not Yet.mscz", "PK-mscz".toByteArray()))
        assertEquals("Filed as score-1.pdf of Share Test - Two At Once\n" +
                         "Waiting for a song that fits: Share Test - Not Yet.mscz", said)
        assertEquals(listOf("score-1.pdf"), kept(song))
        assertEquals(listOf("Share Test - Not Yet.mscz"), waiting())
        // The song it is of added (an add, as the request form queues one): the file that waited is filed.
        val later = phone.queue.submit(JobSpec("Add Share Test - Not Yet", "share-test/not-yet", "add", emptyList(),
                                               run = {
            phone.parts.database.write { db -> phone.parts.store.add(db, "Share Test", "Not Yet", now = "2026-11-10T00:00:00Z") }
        })).first
        runBlocking { withTimeout(30_000) { phone.queue.await(later.id) } }
        val filed = waitFor("the waiting file filed") {
            phone.queue.snapshot().firstOrNull { it.spec.kind == "inbox" && it.key.endsWith("Not Yet.mscz") &&
                                                     it.state == "done" && it.songId != null }
        }
        val notYet = phone.parts.database.read { db -> Songs.byId(db, filed.songId!!)!! }
        assertEquals(listOf("score-1.mscz"), kept(notYet))
        assertEquals(emptyList<String>(), waiting())
    }

    @Test fun aFileOfAKindCaracoleKeepsNothingOfIsNeverStaged() {
        val said = share("application/octet-stream", uri("notes.txt", "just words".toByteArray()))
        assertEquals("Not filed: caracole keeps Guitar Pro files and scores, and notes.txt is neither", said)
        assertFalse("notes.txt" in waiting())
    }

    @Test fun aShareWithNoFileSaysSo() {
        ShareActivity.told = null
        context.startActivity(Intent(Intent.ACTION_SEND).setClass(context, ShareActivity::class.java)
                                  .setType("application/pdf").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        assertEquals(ShareActivity.NOTHING, waitFor("the share's toast") { ShareActivity.told })
    }

    @Test fun caracoleIsOfferedForFilesAloneNeverForATextAViewOrAnyType() {
        val share = ComponentName(context, ShareActivity::class.java)
        fun offered(intent: Intent): Boolean = context.packageManager
            .queryIntentActivities(intent.setPackage(context.packageName), PackageManager.MATCH_DEFAULT_ONLY)
            .any { it.activityInfo.name == share.className }
        for (type in listOf("application/x-guitar-pro", "application/octet-stream", "application/pdf", "audio/midi",
                            "application/vnd.recordare.musicxml", "application/x-musescore")) {
            assertTrue(type, offered(Intent(Intent.ACTION_SEND).setType(type)))
            assertTrue(type, offered(Intent(Intent.ACTION_SEND_MULTIPLE).setType(type)))
            assertFalse(type, offered(Intent(Intent.ACTION_VIEW).setDataAndType(Uri.parse("content://x/y"), type)))
        }
        assertFalse(offered(Intent(Intent.ACTION_SEND).setType("text/plain")))
        assertFalse(offered(Intent(Intent.ACTION_SEND).setType("image/png")))
    }
}
