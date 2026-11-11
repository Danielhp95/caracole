package io.github.danielhp95.caracole

import android.graphics.pdf.PdfRenderer
import android.os.Build
import android.os.ParcelFileDescriptor
import android.print.PrintAttributes
import android.print.PrintDocumentInfo
import android.print.PrintJob
import android.print.PrintManager
import android.print.PrintedPdf
import android.webkit.WebView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.OverrideWriters
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Versions
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.viewer.render.WrittenPages
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.net.URI
import java.net.URLEncoder
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * Export PDF on a device or an emulator (lane export-print), the phone's caracole in the app's own process:
 *
 *     android/scripts/device-test.sh io.github.danielhp95.caracole.PrintTest
 *
 * The viewer's `/export.pdf?…` link is named by the phone's server (the download name caracole serve gives the PDF)
 * and the screen's WebView printed through Android's print framework: a print job of that name, its page A4, for this
 * app, and nothing written into the library; a link the page follows reaches it through the screen's own hook
 * (MainActivity's `follow`, Links.Route.Print). With `mine=1` Make this my version is queued too, and its run makes
 * the version the song's own and the song's pages again (the phone's own render). A refusal prints nothing. The
 * system's print dialog can't be driven from a test, so what it would print is the WebView's own print adapter run as
 * the spooler runs it ([PrintedPdf]): an A4 PDF of the page.
 *
 * On an emulator alone: it opens the system's print dialog, and after each test cancels this app's print jobs and
 * stops the print spooler, which on a phone of the owner's would be their spooler and their jobs (skipped there).
 * The phone's own jobs (its render job at its start) are waited for before any snapshot of the library or the queue.
 */
@RunWith(AndroidJUnit4::class)
class PrintTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val jobs = ArrayList<PrintJob>()

    @Before
    fun anEmulatorWithAComputerNamed() {
        assumeTrue("an emulator's print spooler alone", onAnEmulator())
        // A first start with no computer named opens Settings over the library screen: name one, never asked here.
        Settings(context).server = "http://10.0.2.2:9"
    }

    @After
    fun noPrintLeft() {
        if (!onAnEmulator()) return
        instrumentation.runOnMainSync {
            val left = jobs + context.getSystemService(PrintManager::class.java).printJobs
            for (job in left) if (!job.isCancelled && !job.isCompleted) job.cancel()
        }
        instrumentation.uiAutomation.executeShellCommand("am force-stop com.android.printspooler").close()
    }

    @Test
    fun exportPdfPrintsTheViewerShownNamedForTheVersion() {
        song()
        idle()
        val before = libraryFiles()
        val queued = jobIds()
        launched { main ->
            val job = printed(main, export("t=2&capo=0&fs=20"))
            assertNotNull("a print job", job)
            job!!
            assertEquals(NAME, job.info.label)
            assertEquals(PrintAttributes.MediaSize.ISO_A4.id, job.info.attributes.mediaSize?.id)
            var listed = false
            main.onActivity { listed = it.getSystemService(PrintManager::class.java).printJobs.any { j -> j.id == job.id } }
            assertTrue("the job is this app's", listed)
        }
        assertEquals("nothing is kept in the library", before, libraryFiles())
        assertEquals("no job queued", queued, jobIds())
    }

    @Test
    fun aLinkThePageFollowsPrintsThroughTheScreensHook() {
        song()
        idle()
        val queued = jobIds()
        launched { main ->
            val url = export("t=2&capo=0")
            val clicked = Pages.evaluate(main, "(function () { const a = document.createElement('a'); " +
                "a.href = ${org.json.JSONObject.quote(url)}; document.body.appendChild(a); a.click(); " +
                "return 'clicked'; })()")
            assertEquals("clicked", clicked)
            var job: PrintJob? = null
            Pages.waitUntil("a print job named for the version", 30_000) {
                main.onActivity { activity ->
                    job = activity.getSystemService(PrintManager::class.java).printJobs
                        .firstOrNull { it.info.label == NAME && !it.isCancelled }
                }
                job != null
            }
            jobs += job!!
            assertEquals(PrintAttributes.MediaSize.ISO_A4.id, job!!.info.attributes.mediaSize?.id)
            assertTrue("the screen stays where it was", Pages.url(main).startsWith(Pages.address("")))
        }
        assertEquals("no job queued", queued, jobIds())
    }

    @Test
    fun mineQueuesMakeThisMyVersionAndStillPrints() {
        val song = song()
        idle()
        val queued = jobIds()
        launched { main ->
            assertNotNull(printed(main, export("t=2&capo=0&mine=1")))
        }
        val job = phone().queue.snapshot().single { it.id !in queued }
        assertEquals("export:${song.key}:t=2&capo=0:mine", job.key)
        val ended = runBlocking { withTimeout(60_000) { phone().queue.await(job.id) } }
        assertEquals(ended.output.toString(), Job.DONE, ended.state)
        assertEquals("key=A&capo=0", phone().parts.database.read { db -> Overrides.read(db).version[song.key] })
        // the song's viewer made again by the phone's own render, starting where the song plays now
        val viewer = phone().parts.database.read { db -> WrittenPages.written(db, song.id, "sheet.html") }
        assertNotNull("the phone's own viewer", viewer)
        assertTrue("made again", viewer!!.sha256 != viewerBefore)
    }

    @Test
    fun aRefusalPrintsNothing() {
        song()
        idle()
        val queued = jobIds()
        launched { main ->
            assertNull(printed(main, Pages.origin() + "/export.pdf?sheet=Nobody/Nothing/sheet.html&t=2"))
        }
        val phone = phone()
        val said = Printer.ask(phone.app::handle, URI(phone.server.origin), Caracole.secret,
                               phone.server.origin + "/export.pdf?sheet=Nobody/Nothing/sheet.html&t=2")
        assertEquals(Printer.Named.Refused(404, "No such sheet in the book."), said)
        assertEquals(queued, jobIds())
    }

    @Test
    fun theViewersPrintAdapterWritesThePageShownAsAnA4Pdf() {
        val file = File(context.cacheDir, "print-test.pdf").apply { delete() }
        launched { main ->
            val latch = CountDownLatch(1)
            var info: PrintDocumentInfo? = null
            var why: String? = "not run"
            main.onActivity { activity ->
                val adapter = activity.findViewById<WebView>(R.id.web).createPrintDocumentAdapter(NAME)
                val attributes = PrintAttributes.Builder().setMediaSize(PrintAttributes.MediaSize.ISO_A4)
                    .setResolution(PrintAttributes.Resolution("pdf", "pdf", 300, 300))
                    .setMinMargins(PrintAttributes.Margins.NO_MARGINS)
                    .setColorMode(PrintAttributes.COLOR_MODE_COLOR).build()
                PrintedPdf.write(adapter, attributes, file) { i, w ->
                    info = i
                    why = w
                    latch.countDown()
                }
            }
            assertTrue("the adapter wrote", latch.await(60, TimeUnit.SECONDS))
            assertNull(why, why)
            assertEquals(NAME, info?.name)
        }
        assertEquals("%PDF", file.readBytes().copyOf(4).toString(Charsets.US_ASCII))
        PdfRenderer(ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)).use { pdf ->
            assertTrue("pages: ${pdf.pageCount}", pdf.pageCount >= 1)
            pdf.openPage(0).use { page ->
                // A4 in points: 210 × 297 mm
                assertEquals(595.0, page.width.toDouble(), 2.0)
                assertEquals(842.0, page.height.toDouble(), 2.0)
            }
        }
        file.delete()
    }

    // --- helpers ------------------------------------------------------------------------------------------------

    private fun phone() = Caracole.phone(context)

    /** The jobs the phone's queue holds: the class's tests share its process, and so its queue. */
    private fun jobIds(): Set<Int> = phone().queue.snapshot().map { it.id }.toSet()

    /** Every job that waits or runs over, the phone's own among them (the render job Phone.start queues when pages
     * are owed, which would make the test's song's pages beside it). */
    private fun idle() {
        val active = phone().queue.snapshot().filter { it.state == "queued" || it.state == "running" }
        runBlocking { withTimeout(120_000) { for (job in active) phone().queue.await(job.id) } }
    }

    /** Whether this runs on an emulator (its virtual hardware), never a phone adb also lists. */
    private fun onAnEmulator(): Boolean = Build.HARDWARE in setOf("ranchu", "goldfish") ||
        Build.PRODUCT.startsWith("sdk_gphone") || Build.FINGERPRINT.startsWith("generic")

    /** The song's viewer as [song] last made it, to tell it made again. */
    private var viewerBefore: String? = null

    /** The viewer's Export PDF link for the song's sheet, its version [query]. */
    private fun export(query: String): String = Pages.origin() + "/export.pdf?sheet=" +
        URLEncoder.encode(SHEET, "UTF-8").replace("+", "%20") + "&" + query

    /** The library screen, its library page loaded. */
    private fun launched(body: (ActivityScenario<MainActivity>) -> Unit) {
        ActivityScenario.launch(MainActivity::class.java).use { main ->
            Pages.waitUntil("the library page", 60_000) {
                Pages.url(main).startsWith(Pages.address("")) &&
                    Pages.evaluate(main, "document.readyState") == "complete"
            }
            body(main)
        }
    }

    /** Printer.print of [url] on the screen's WebView: the print job it made, or null. */
    private fun printed(main: ActivityScenario<MainActivity>, url: String): PrintJob? {
        val latch = CountDownLatch(1)
        var job: PrintJob? = null
        main.onActivity { activity ->
            Printer.print(activity, activity.findViewById(R.id.web), url) {
                job = it
                latch.countDown()
            }
        }
        assertTrue("Printer answered", latch.await(30, TimeUnit.SECONDS))
        job?.let { jobs += it }
        return job
    }

    /** A song in G, its UG sheet kept as the fetch keeps one, played as written (no `[version]`), its pages made by
     * the phone's own render (PhoneRender: its viewer recorded as the phone records one). */
    private fun song(): SongRow {
        val phone = phone()
        val library = phone.parts.store.libraryDir
        return phone.parts.database.writeBlocking { db ->
            val song = LibraryStore(library).add(db, ARTIST, TITLE, now = NOW)
            val raw = buildJsonObject { put("id", 85001); put("tonality_name", "G") }
            val version = Versions.upsert(db, "ug", "85001", song.id, "sheet", "chords", 4.5, 10, 1, null,
                                          "https://tabs.ultimate-guitar.com/tab/x/y-chords-85001", raw, NOW)
            Kept.keepFile(db, LibraryStore(library), song, version, "sheet.txt", "G D\nPalabras\n".toByteArray(), 1, NOW)
            val folder = SafeName.songFolder(ARTIST, TITLE)
            File(library, "${folder.first}/${folder.second}/sheet.json").writeText(
                """{"content": "[tab][ch]G[/ch]           [ch]D[/ch]\r\nPalabras de prueba[/tab]\r\n", "meta": []}""")
            OverrideWriters.addVersion(db, song.display, null) { null }  // as written, whatever a test before made it
            val made = phone.render.render(db, listOf(song.id), null)
            assertTrue("its pages made: ${made.failed}", made.failed.isEmpty())
            viewerBefore = WrittenPages.written(db, song.id, "sheet.html")?.sha256
            assertNotNull("its viewer recorded", viewerBefore)
            song
        }
    }

    private fun libraryFiles(): Map<String, Long> {
        val library = phone().parts.store.libraryDir
        return library.walkTopDown().filter { it.isFile }.associate { it.relativeTo(library).path to it.length() }
    }

    private companion object {
        const val ARTIST = "Soda Stereo"
        const val TITLE = "De Música Ligera"
        const val SHEET = "Soda Stereo/De Música Ligera/sheet.html"
        const val NAME = "Soda Stereo - De Música Ligera (A Major, capo 0).pdf"
        const val NOW = "2026-11-03T10:00:00Z"
    }
}
