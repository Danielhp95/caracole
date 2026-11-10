package io.github.danielhp95.caracole

import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.core.config.PhoneConfig
import io.github.danielhp95.caracole.core.health.Health
import io.github.danielhp95.caracole.core.http.RoutedTransport
import io.github.danielhp95.caracole.server.jobs.Job
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.time.Instant

/**
 * A lookup in the app against the fake sites server, through the emulator's address of the host:
 *
 *     android/scripts/device-test.sh --sites lookups io.github.danielhp95.caracole.LookupOnDeviceTest
 *
 * The script runs tests/helpers/fake_sites.py's server on the host (`serve lookups PORT`) and names it to the test
 * (`-e sites http://10.0.2.2:PORT`), which makes [Caracole.sitesForTests] a RoutedTransport there: every request the
 * app's lookup sends a site goes to the fake server as `GET /fetch?url=…`, and RealTransport's guard (the runner's
 * `caracole.network=loopback`) lets it reach 10.0.2.2 and no other host. Without the argument the test is skipped.
 *
 * The app takes the scenario's index (the fake server's GET /index.sqlite, imported as the computer's would be), finds
 * the song it hasn't got by its /api/search row, and Get it, posted as the library page's script posts it, looks it
 * up: its sheet and LRCLIB's timed lyrics kept (lyrics.lrc), its card's sheet.txt served, each site asked at most its
 * lookup_requests, no URL robots.txt closes, every URL one the scenario answers (the fake server's `known`: no URL
 * the computer's caracole wouldn't ask, read as a miss), every request one the fake server counted, with the user
 * agent the app names. Then Get it on a song whose page answers 403 cools Ultimate Guitar down on the phone.
 */
@RunWith(AndroidJUnit4::class)
class LookupOnDeviceTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val sites: String? = InstrumentationRegistry.getArguments().getString("sites")

    @Before fun theFakeSites() {
        Assume.assumeTrue("no fake sites server: -e sites http://10.0.2.2:PORT (device-test.sh --sites lookups)",
                          sites != null)
        Caracole.sitesForTests = RoutedTransport(sites!!)
    }

    @After fun refuseAgain() {
        Caracole.sitesForTests = CaracoleTestRunner.REFUSING
    }

    @Test fun aSongLookedUpThroughTheHostsAddressKeepsItsSheetWithinItsLimitsAndA403CoolsUgDown() {
        ActivityScenario.launch(MainActivity::class.java).use {
            val phone = Caracole.phone(context)
            val scenario = JSONObject(String(read("/scenario.json"), Charsets.UTF_8))
            val songs = scenario.getJSONObject("songs")
            val limits = scenario.getJSONObject("limits")

            val index = File(context.cacheDir, "fake-sites-index.sqlite")
            index.writeBytes(read("/index.sqlite"))
            val merged = await(phone.importIndex(index).id)
            assertEquals(merged.asJson().toString(), Job.DONE, merged.state)

            // Get it on the search's row of the song new to the app.
            val getIt = songs.getJSONObject("get_it")
            val before = log().length()
            val job = getIt(getIt.getJSONObject("search"))
            assertEquals(job.asJson().toString(), Job.DONE, job.state)
            val stages = job.stages.associate { it.name to it }
            for (name in listOf("song", "match", "sheet", "lyrics")) {
                assertEquals("$name: ${job.asJson()}", "done", stages.getValue(name).state)
            }
            val key = getIt.getJSONObject("search").getString("key")
            val path = phone.parts.database.read { db ->
                db.one("SELECT files.path FROM files JOIN songs ON songs.id = files.song_id " +
                           "WHERE songs.key = ? AND files.name = 'sheet.txt'", key) { it.text(0) }
            } ?: throw AssertionError("no sheet.txt kept: ${job.asJson()}")
            val sheet = File(phone.parts.store.libraryDir, path).readText()
            assertTrue(sheet.take(500), "Made-up words of verse 1" in sheet)
            assertEquals("found", phone.parts.database.read { db ->
                db.one("SELECT lyrics_status FROM songs WHERE key = ?", key) { it.text(0) }
            })
            val lrc = File(File(phone.parts.store.libraryDir, path).parentFile, "lyrics.lrc")  // beside its sheet
            assertTrue("no $lrc: ${job.asJson()}", lrc.isFile)
            assertTrue(lrc.readText().take(300), lrc.readText().startsWith("[00:10.00]"))
            val card = card(key)
            val href = (0 until card.getJSONArray("files").length()).map { card.getJSONArray("files").getJSONObject(it) }
                .first { it.getString("name") == "sheet.txt" }.getString("href")
            val (status, served) = PhoneForms.get(Pages.origin() + "/" + href)
            assertEquals(served.take(500), 200, status)
            assertEquals("its card's sheet.txt is the one kept", sheet, served)

            val asked = log(before)
            val agent = phone.parts.database.read { db -> PhoneConfig.read(db) }.userAgent
            val sent = HashMap<String, Int>()
            for (i in 0 until asked.length()) {
                val request = asked.getJSONObject(i)
                assertTrue("a URL robots.txt closes: $request", !request.getBoolean("closed"))
                assertTrue("a URL the scenario doesn't answer: $request", request.getBoolean("known"))
                assertTrue("a host no site's: $request", request.getString("provider").isNotEmpty())
                assertEquals("its user agent: $request", agent, request.getString("user_agent"))
                sent.merge(request.getString("provider"), 1, Int::plus)
            }
            assertTrue("the sites were asked", sent.isNotEmpty())
            for ((provider, n) in sent) {
                val most = limits.getJSONObject(provider).getInt("lookup_requests")
                assertTrue("Get it sent $provider $n requests, more than $most", n <= most)
            }

            // Get it on a song whose page answers 403: Ultimate Guitar cools down on the phone.
            val blocked = songs.getJSONObject("blocked")
            val from = log().length()
            val stopped = getIt(blocked.getJSONObject("search"))
            assertEquals(stopped.asJson().toString(), Job.DONE, stopped.state)
            val answered = log(from)
            assertTrue("UG's 403: $answered", (0 until answered.length()).any { answered.getJSONObject(it).getInt("status") == 403 })
            for (i in 0 until answered.length()) {
                assertTrue("a URL the scenario doesn't answer: ${answered.getJSONObject(i)}",
                           answered.getJSONObject(i).getBoolean("known"))
            }
            assertTrue("the block is never a miss", phone.parts.database.read { db ->
                db.one("SELECT match_decision FROM songs WHERE key = ?",
                       blocked.getJSONObject("search").getString("key")) { it.text(0) }
            } != "not_found")
            assertTrue("a 403 cools Ultimate Guitar down on the phone",
                       phone.parts.database.read { db -> Health.isCooling(db, "ug", Instant.now()) })
        }
    }

    /** Get it on /api/search's row of [search]'s song (its query, its `ug`), as the library page posts it: the job,
     * once it is over. */
    private fun getIt(search: JSONObject): Job {
        val (status, body) = PhoneForms.script("/api/search?q=" + URLEncoder.encode(search.getString("query"), "UTF-8"))
        assertEquals(body, 200, status)
        val rows = JSONObject(body).getJSONArray("index")
        val row = (0 until rows.length()).map { rows.getJSONObject(it) }.firstOrNull { it.getString("ug") == search.getString("ug") }
            ?: throw AssertionError("/api/search finds no ${search.getString("ug")}: $body")
        val (posted, answer) = PhoneForms.post("/lookup", "artist" to row.getString("artist"),
                                               "title" to row.getString("title"), "ug" to row.getString("ug"))
        assertEquals(answer, 202, posted)
        return await(JSONObject(answer).getInt("job"))
    }

    private fun await(id: Int): Job = runBlocking { withTimeout(300_000) { Caracole.phone(context).queue.await(id) } }

    /** The card of the song of [key] in the library page's data (GET /'s `songs` block). */
    private fun card(key: String): JSONObject {
        val (status, page) = PhoneForms.get(Pages.origin() + "/")
        assertEquals(200, status)
        val block = Regex("""<script type="application/json" id="songs">(.*?)</script>""", RegexOption.DOT_MATCHES_ALL)
            .find(page) ?: throw AssertionError("no data on the library page")
        val songs = JSONObject(block.groupValues[1]).getJSONArray("songs")
        return (0 until songs.length()).map { songs.getJSONObject(it) }.firstOrNull { it.optString("identity") == key }
            ?: throw AssertionError("no card of $key")
    }

    /** The fake server's [path], read straight from the host. */
    private fun read(path: String): ByteArray {
        val connection = URL(sites + path).openConnection() as HttpURLConnection
        try {
            connection.connectTimeout = 30_000
            connection.readTimeout = 60_000
            assertEquals("${sites + path}", 200, connection.responseCode)
            return connection.inputStream.use { it.readBytes() }
        } finally {
            connection.disconnect()
        }
    }

    /** The requests the fake server was sent after its [since]-th. */
    private fun log(since: Int = 0): JSONArray =
        JSONObject(String(read("/log?since=$since"), Charsets.UTF_8)).getJSONArray("requests")
}
