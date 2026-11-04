package io.github.danielhp95.caracole

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.core.http.RealTransport
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.server.jobs.Job
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.IOException
import java.net.Proxy
import java.net.ProxySelector
import java.net.SocketAddress
import java.net.URI
import java.util.Collections

/**
 * With no sites set (`Caracole.sitesForTests` null: the app's own transport, RealTransport, as the app ships it), a
 * lookup in the app under CaracoleTestRunner opens no socket to a site: RealTransport refuses any host but loopback
 * before it connects (`caracole.network=loopback`).
 *
 *     android/scripts/device-test.sh io.github.danielhp95.caracole.NoNetworkTest
 *
 * Every connection java.net's HttpURLConnection opens asks the default ProxySelector first, so one installed here
 * hears each, whatever its host: the test's own posts to the app's server on 127.0.0.1 are heard (so a count of none
 * means something), a site never. The lookup still ends as one with no network does: its song added, its sites'
 * stages failed ("refused") or skipped, none a miss, its line "Not fetched yet".
 */
@RunWith(AndroidJUnit4::class)
class NoNetworkTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val before: ProxySelector? = ProxySelector.getDefault()

    /** Each http and https address a connection was opened for, answered with no proxy. */
    private val heard: MutableList<URI> = Collections.synchronizedList(ArrayList())

    private val counting = object : ProxySelector() {
        override fun select(uri: URI): List<Proxy> {
            if (uri.scheme?.lowercase() in setOf("http", "https")) heard.add(uri)
            return before?.select(uri) ?: listOf(Proxy.NO_PROXY)
        }

        override fun connectFailed(uri: URI?, address: SocketAddress?, e: IOException?) {
            before?.connectFailed(uri, address, e)
        }
    }

    @Before fun count() {
        ProxySelector.setDefault(counting)
        Caracole.sitesForTests = null
    }

    @After fun stop() {
        ProxySelector.setDefault(before)
        Caracole.sitesForTests = CaracoleTestRunner.REFUSING
    }

    @Test fun aLookupWithNoSitesSetOpensNoSocketToASite() {
        assertEquals("loopback", System.getProperty(RealTransport.NETWORK))
        assertTrue("the app's own transport", Caracole.transport() === RealTransport)
        val phone = Caracole.phone(context)
        val (status, body) = PhoneForms.post("/lookup", "artist" to ARTIST, "title" to TITLE)
        assertEquals(body, 202, status)
        val id = JSONObject(body).getInt("job")
        val job = runBlocking { withTimeout(120_000) { phone.queue.await(id) } }
        assertEquals(job.asJson().toString(), Job.DONE, job.state)
        // the line the library page shows, read from the app's own server as its script reads it
        assertEquals("Not fetched yet", PhoneForms.line(id).getString("text"))

        val hosts = synchronized(heard) { heard.map { it.host } }
        assertTrue("the test's own posts to the app's server were heard: $hosts", "127.0.0.1" in hosts)
        assertEquals("no connection but to the app's own server", emptyList<String>(), hosts.filter { it != "127.0.0.1" })

        val stages = job.stages.associate { it.name to it }
        assertEquals("done", stages.getValue("song").state)
        assertEquals("failed", stages.getValue("lyrics").state)
        assertTrue(stages.getValue("lyrics").detail, "refused" in stages.getValue("lyrics").detail)
        for (site in listOf("ug", "lacuerda", "gtptabs", "harptabs", "gametabs")) {
            assertTrue("$site: ${job.asJson()}", stages.getValue(site).state in setOf("failed", "skipped"))
        }
        val song = phone.parts.database.read { Songs.byKey(it, Normalize.identityKey(ARTIST, TITLE)) }
        assertNotNull("the song added", song)
        assertTrue("a refused site is never a miss: ${song!!.lyricsStatus}", song.lyricsStatus != "missing")
    }

    private companion object {
        const val ARTIST = "Café Tacvba"
        const val TITLE = "Eres"
    }
}
