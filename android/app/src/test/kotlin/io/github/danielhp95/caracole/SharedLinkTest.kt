package io.github.danielhp95.caracole

import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** A song's link shared to the app: the page of the phone's server that shows it, the one page the library screen
 * takes from an intent, its Cancel, and the line logcat says of what the app sent. */
class SharedLinkTest {
    private val origin = "http://127.0.0.1:8738"

    @Test
    fun `the share page carries every extra the app sent, encoded, and none it didn't`() {
        assertEquals(
            "/share?text=Listen%20to%20Creep%20by%20Radiohead%20on%20Deezer%20https%3A%2F%2Flink.deezer.com%2Fs%2Fx" +
                "&subject=Creep&from=deezer.android.app",
            SharedLink.page("Listen to Creep by Radiohead on Deezer https://link.deezer.com/s/x", "Creep", null,
                            "deezer.android.app"),
        )
        assertEquals("/share?text=%E5%AE%8B%E5%86%AC%E9%87%8E%20%26%20%3D%2B", SharedLink.page("宋冬野 & =+", "", null, null))
        assertEquals("/share", SharedLink.page(null, null, null, null))
    }

    @Test
    fun `the screen shows a share page from an intent and no other`() {
        assertEquals("/share?text=x", SharedLink.shown("/share?text=x"))
        assertEquals("/share", SharedLink.shown("/share"))
        for (other in listOf(null, "", "/", "/sharex", "/share/cancel", "https://evil.example/share?text=x", "/#tab=sync")) {
            assertNull(SharedLink.shown(other), "$other")
        }
    }

    @Test
    fun `Cancel and the share pages are the phone's server's alone`() {
        assertTrue(SharedLink.isCancel("$origin/share/cancel", origin))
        assertFalse(SharedLink.isCancel("http://127.0.0.1:8737/share/cancel", origin), "another port's")
        assertFalse(SharedLink.isCancel("$origin/share?text=x", origin))
        assertFalse(SharedLink.isCancel("$origin/share/cancel", null), "no server yet")
        assertTrue(SharedLink.isSharePage("$origin/share?artist=A&title=B", origin))
        assertFalse(SharedLink.isSharePage("$origin/#tab=requests&job=3", origin))
        assertFalse(SharedLink.isSharePage("not a url at all ::", origin))
    }

    @Test
    fun `logcat says each extra as it came, quoted, and the sender`() {
        assertEquals(
            "from=com.spotify.music type=text/plain text=\"https://open.spotify.com/track/1\" subject=\"Say \\\"hi\\\"\\n\" " +
                "title=null",
            SharedLink.said("https://open.spotify.com/track/1", "Say \"hi\"\n", null, "com.spotify.music", "text/plain"),
        )
        assertEquals("from=? type=? text=null subject=null title=null", SharedLink.said(null, null, null, null, null))
    }
}
