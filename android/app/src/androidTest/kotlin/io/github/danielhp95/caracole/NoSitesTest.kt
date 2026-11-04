package io.github.danielhp95.caracole

import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.danielhp95.caracole.core.http.HttpRequest
import io.github.danielhp95.caracole.core.http.RealTransport
import io.github.danielhp95.caracole.core.http.TransportError
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith

/** The app under CaracoleTestRunner opens no socket to a site: its transport refuses every site's request, and
 * RealTransport itself refuses any host but loopback, before it would connect. */
@RunWith(AndroidJUnit4::class)
class NoSitesTest {
    private fun refused(send: () -> Unit): TransportError {
        try {
            send()
        } catch (e: TransportError) {
            return e
        }
        fail("the request was sent")
        throw AssertionError()
    }

    @Test fun theAppsTransportRefusesEverySite() {
        assertEquals("loopback", System.getProperty(RealTransport.NETWORK))
        assertSame(CaracoleTestRunner.REFUSING, Caracole.transport())
        assertFalse(Caracole.searchesLacuerdaForTests)
        for (url in listOf("https://tabs.ultimate-guitar.com/tab/1", "https://lrclib.net/api/get?x=1",
                           "https://acordes.lacuerda.net/", "http://192.168.1.20:8737/")) {
            assertEquals("refused", refused { Caracole.transport().send(HttpRequest("GET", url, emptyList())) }.kind)
            assertEquals("refused", refused { RealTransport.send(HttpRequest("GET", url, emptyList())) }.kind)
        }
    }
}
