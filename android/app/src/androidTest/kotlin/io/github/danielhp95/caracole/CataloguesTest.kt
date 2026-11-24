package io.github.danielhp95.caracole

import android.app.Activity
import android.app.AlertDialog
import android.view.View
import android.widget.TextView
import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import io.github.danielhp95.caracole.core.catalogues.Catalogues
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.index.IndexTransfer
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.index.TabCounts
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.server.jobs.JobViews
import io.github.danielhp95.caracole.server.jobs.PhoneKinds
import io.github.danielhp95.caracole.server.lookups.CataloguesRunner
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.FixMethodOrder
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.MethodSorters
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.URI
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import java.util.zip.GZIPOutputStream
import kotlin.concurrent.thread
import kotlin.random.Random

/**
 * The site catalogues in the app, on the device:
 *
 *     android/scripts/device-test.sh io.github.danielhp95.caracole.CataloguesTest
 *
 * GitHub is this test's own server on the device's loopback ([GitHub]: its API's release by its tag and an asset's
 * bytes, as CatalogueSource.Api asks them), which [Caracole.cataloguesForTests] points the job at. On a first start
 * (the app's data cleared, as device-test.sh clears it before each class) with no computer set and no index, the
 * library screen offers the catalogues; Download imports them, and Settings, opened after it, says their date (the
 * file's); a second Download is Up to date. On a metered network the job stops before downloading and Settings asks
 * "… on a metered network?", asked again by the screen a rotation makes; Download there is the go-ahead, which
 * imports. A job queued by no screen of the app's (the Journal's Try again) that stops so is asked about too, once.
 */
@RunWith(AndroidJUnit4::class)
@FixMethodOrder(MethodSorters.NAME_ASCENDING)
class CataloguesTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val github = GitHub()

    @Before fun pointAtTheTestsGitHub() {
        Corpus.open = { name -> runCatching { instrumentation.context.assets.open("conformance/$name") }.getOrNull() }
        Caracole.cataloguesForTests = github.base
        Caracole.meteredForTests = false
    }

    @After fun close() {
        Caracole.cataloguesForTests = null
        Caracole.meteredForTests = null
        github.close()
    }

    private fun kv(key: String): String? = Caracole.phone(context).parts.database.read { it.kvGet(key) }

    private val first = "indexes-s${Database.SCHEMA_VERSION}-20261124T0312Z.sqlite.gz"
    private val second = "indexes-s${Database.SCHEMA_VERSION}-20261201T0312Z.sqlite.gz"
    private val third = "indexes-s${Database.SCHEMA_VERSION}-20261208T0312Z.sqlite.gz"

    @Test fun a_theFirstStartOffersThemAndSettingsSaysTheirDate() {
        github.publish(first)
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            waitUntil("the first start's offer", 60_000) { onMain { find(scenario).findViewById<View>(R.id.catalogue_offer).isShown } }
            // Shown once the opening screen is gone: never over the logo, nor live under it.
            assertEquals(View.GONE, onMain { find(scenario).findViewById<View>(R.id.loading).visibility })
            assertEquals(listOf<String>(), github.asked)  // no request until Download is tapped
            onMain { find(scenario).findViewById<View>(R.id.offer_download).performClick() }
            waitUntil("offered once: its answer recorded") { kv(SiteCatalogues.OFFERED) != null }

            val settings = resumed<SettingsActivity>()
            waitUntil("the catalogues imported", 60_000) { kv(Catalogues.IMPORTED) == first }
            assertTrue(Caracole.phone(context).parts.database.read { TabCounts.of(it) }.values.any { it > 0 })
            // The file's own date (its name's minute), never the newest read the phone's indexes hold.
            waitUntil("their date in Settings") { text(settings, R.id.catalogues_date).startsWith("Of 24 Nov 2026 · ") }
            waitUntil("the job's line") { text(settings, R.id.catalogues_status) == "Catalogues of 24 Nov 2026" }

            onMain { settings.findViewById<View>(R.id.catalogues_download).performClick() }
            waitUntil("a second tap: up to date") {
                text(settings, R.id.catalogues_status) == "Up to date: the catalogues of 24 Nov 2026"
            }
            onMain { settings.finish() }
        }
        // No catalogue imported (the record gone, as on a phone whose indexes came from a .caracole file), yet tabs
        // there: the newest sitemap read the indexes hold (gtptabs.com's and MuseScore's: no page of theirs the phone
        // reads itself), as IndexTransfer.newest has it.
        val database = Caracole.phone(context).parts.database
        val sitemaps = database.read { IndexTransfer.newest(it) }.values.mapNotNull { Stamps.parse(it)?.let(Stamps::instant) }.max()
        database.writeBlocking { it.kvDelete(Catalogues.IMPORTED) }
        ActivityScenario.launch(SettingsActivity::class.java).use { scenario ->
            waitUntil("the indexes' date") {
                text(find(scenario), R.id.catalogues_date).startsWith("Of ${SiteCatalogues.day(sitemaps)} · ")
            }
        }
        database.writeBlocking { it.kvSet(Catalogues.IMPORTED, first) }
        // Offered once: the next start, still with nothing set up, opens Settings as ever and offers nothing.
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            resumed<SettingsActivity>().let { onMain { it.finish() } }
            assertFalse(onMain { find(scenario).findViewById<View>(R.id.catalogue_offer).visibility == View.VISIBLE })
        }
    }

    @Test fun b_onMobileDataSettingsAsksFirst() {
        github.publish(second)
        Caracole.meteredForTests = true
        ActivityScenario.launch(SettingsActivity::class.java).use { scenario ->
            val settings = find(scenario)
            onMain { settings.findViewById<View>(R.id.catalogues_download).performClick() }
            var asked: AlertDialog? = null
            waitUntil("the question", 60_000) { onMain { settings.asked }.also { asked = it } != null }
            assertFalse("waiting for the go-ahead, nothing imported", kv(Catalogues.IMPORTED) == second)
            // The kind's wait, in whatever words it has (PhoneKinds' otherwise, its size filled in).
            assertTrue(PhoneKinds.fits(text(settings, R.id.catalogues_status), PhoneKinds.CATALOGUES.otherwise!!))
            assertNotNull(kv(CataloguesRunner.ASKING))
            // A rotation: the question goes with its window, unanswered and leaking nothing, and the new screen asks it.
            scenario.recreate()
            val again = find(scenario)
            waitUntil("the question again, after a rotation") { onMain { again.asked }.also { asked = it } != null }
            onMain { asked!!.getButton(AlertDialog.BUTTON_POSITIVE).performClick() }
            waitUntil("the go-ahead imports", 60_000) { kv(Catalogues.IMPORTED) == second }
            waitUntil("its line") { text(again, R.id.catalogues_status) == "Catalogues of 1 Dec 2026" }
        }
    }

    @Test fun c_aStopTheAppDidntQueueIsAskedAboutOnce() {
        github.publish(third)
        Caracole.meteredForTests = true
        // The Journal's Try again: the plain job queued again, by no screen of the app's.
        val phone = Caracole.phone(context)
        val tried = phone.queue.submit(phone.catalogues.spec(meteredOk = false)).first
        waitUntil("the job stopped for the go-ahead", 60_000) { phone.queue.job(tried.id)?.state == "done" }
        ActivityScenario.launch(SettingsActivity::class.java).use { scenario ->
            val settings = find(scenario)
            var asked: AlertDialog? = null
            waitUntil("the question") { onMain { settings.asked }.also { asked = it } != null }
            onMain { asked!!.getButton(AlertDialog.BUTTON_NEGATIVE).performClick() }
        }
        // Answered: the next screen says the job's line and asks nothing.
        ActivityScenario.launch(SettingsActivity::class.java).use { scenario ->
            val settings = find(scenario)
            waitUntil("its line") {
                PhoneKinds.fits(text(settings, R.id.catalogues_status), PhoneKinds.CATALOGUES.otherwise!!)
            }
            Thread.sleep(1_000)  // the question, were it asked, comes with the line
            assertEquals(null, onMain { settings.asked })
        }
    }

    // --- the screens ------------------------------------------------------------------------------------------------

    /** Pages.waitUntil, its failure saying where the catalogues stand. */
    private fun waitUntil(what: String, timeoutMs: Long = 30_000, condition: () -> Boolean) = try {
        Pages.waitUntil(what, timeoutMs, condition)
    } catch (e: AssertionError) {
        throw AssertionError("${e.message}; ${standing()}", e)
    }

    /** The catalogues jobs, the kv records, the screens and what GitHub was asked. */
    private fun standing(): String = runCatching {
        val phone = Caracole.phone(context)
        val jobs = phone.queue.snapshot().joinToString(" | ") { job ->
            "${job.id} ${job.spec.kind} ${job.state} «${JobViews.line(job).text}» " +
                job.stages.joinToString(",") { "${it.name}:${it.state}:${it.detail}" } + " " + job.steps.joinToString { it.output.joinToString("/") }
        }
        val kv = phone.parts.database.read { db ->
            listOf(SiteCatalogues.OFFERED, Catalogues.IMPORTED, CataloguesRunner.ASKING).associateWith { db.kvGet(it) } to
                TabCounts.of(db)
        }
        var screens = ""
        instrumentation.runOnMainSync {
            screens = ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED)
                .joinToString { it.javaClass.simpleName }
        }
        "jobs: $jobs; kv: ${kv.first}; tabs: ${kv.second}; resumed: $screens; asked: ${github.asked}; " +
            "server: «${Settings(context).server}»"
    }.getOrElse { "(${it})" }

    private fun <T> onMain(block: () -> T): T {
        var out: Result<T>? = null
        instrumentation.runOnMainSync { out = runCatching(block) }
        return out!!.getOrThrow()
    }

    private fun <A : Activity> find(scenario: ActivityScenario<A>): A {
        var found: A? = null
        scenario.onActivity { found = it }
        return found!!
    }

    private inline fun <reified A : Activity> resumed(): A {
        var shown: A? = null
        waitUntil("${A::class.java.simpleName} shown") {
            onMain {
                shown = ActivityLifecycleMonitorRegistry.getInstance().getActivitiesInStage(Stage.RESUMED)
                    .filterIsInstance<A>().firstOrNull()
            }
            shown != null
        }
        return shown!!
    }

    private fun text(activity: Activity, id: Int): String = onMain { activity.findViewById<TextView>(id).text.toString() }

    // --- GitHub -----------------------------------------------------------------------------------------------------

    /** An index export of gtptabs.com's and MuseScore's indexes (the corpus's partial export), at this schema, with
     * bytes that don't compress (as CataloguesRunnerTest's), gzipped. */
    private fun export(): ByteArray {
        val file = File(context.cacheDir, "catalogue-export-${System.nanoTime()}.sqlite")
        try {
            Fixtures.loadRaw(file, "index/fixtures/partial-export.jsonl")
            val c = BundledSQLiteDriver().open(file.path)
            try {
                c.prepare("UPDATE caracole_export SET value = ? WHERE key = 'schema'").use {
                    it.bindText(1, "${Database.SCHEMA_VERSION}")
                    it.step()
                }
                // Bytes that don't compress, in a table no merge reads, as a real index's mostly don't.
                c.prepare("CREATE TABLE padding (bytes BLOB NOT NULL)").use { it.step() }
                c.prepare("INSERT INTO padding (bytes) VALUES (?)").use {
                    it.bindBlob(1, Random(17).nextBytes(40_000))
                    it.step()
                }
            } finally {
                c.close()
            }
            val out = ByteArrayOutputStream()
            GZIPOutputStream(out).use { it.write(file.readBytes()) }
            return out.toByteArray()
        } finally {
            file.delete()
            File(file.path + "-journal").delete()
        }
    }

    /**
     * GitHub's API on the device's loopback, as CatalogueSource.Api asks it: `/repos/{REPO}/releases/tags/{TAG}`, the
     * release whose assets [publish] lists, and each asset's bytes at its API address. Plain HTTP/1.1, one request a
     * connection; [asked] each request's path.
     */
    private inner class GitHub : AutoCloseable {
        private val socket = ServerSocket(0, 16, InetAddress.getByName("127.0.0.1"))
        val base: URI = URI("http://127.0.0.1:${socket.localPort}")
        val asked = CopyOnWriteArrayList<String>()
        private val routes = ConcurrentHashMap<String, ByteArray>()
        private val assets = mutableListOf<String>()

        init {
            thread(isDaemon = true, name = "test-github") {
                while (!socket.isClosed) {
                    val client = try {
                        socket.accept()
                    } catch (e: java.io.IOException) {
                        break
                    }
                    thread(isDaemon = true) { answer(client) }
                }
            }
        }

        /** The release lists [name] among the files published so far, with its bytes. */
        fun publish(name: String) {
            val gz = export()
            assets += name
            val path = "/repos/${Catalogues.REPO}/releases/assets/${assets.size}"
            routes[path] = gz
            val listed = assets.mapIndexed { i, each ->
                val bytes = routes.getValue("/repos/${Catalogues.REPO}/releases/assets/${i + 1}")
                """{"name": "$each", "url": "$base/repos/${Catalogues.REPO}/releases/assets/${i + 1}", """ +
                    """"size": ${bytes.size}, "digest": "sha256:${sha256(bytes)}", "state": "uploaded"}"""
            }
            routes["/repos/${Catalogues.REPO}/releases/tags/${Catalogues.TAG}"] =
                """{"tag_name": "${Catalogues.TAG}", "assets": [${listed.joinToString(", ")}]}""".toByteArray()
        }

        private fun answer(client: Socket) = client.use {
            val input = client.getInputStream()
            val head = StringBuilder()
            while (!head.endsWith("\r\n\r\n")) {
                val b = input.read()
                if (b < 0) return
                head.append(b.toChar())
            }
            val path = head.lineSequence().first().split(" ").getOrElse(1) { "" }.substringBefore('?')
            asked += path
            val body = routes[path]
            val status = if (body == null) "404 Not Found" else "200 OK"
            val bytes = body ?: """{"message": "Not Found"}""".toByteArray()
            val out = client.getOutputStream()
            out.write(("HTTP/1.1 $status\r\nContent-Length: ${bytes.size}\r\nContent-Type: application/octet-stream\r\n" +
                "Connection: close\r\n\r\n").toByteArray(Charsets.ISO_8859_1))
            out.write(bytes)
            out.flush()
        }

        override fun close() = socket.close()
    }

    private fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
}
