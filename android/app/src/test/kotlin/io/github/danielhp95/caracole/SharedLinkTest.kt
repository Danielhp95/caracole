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

    @Test
    fun `an audio file's page is a share page the screen shows, its Cancel stepping back over it`() {
        assertEquals("/share/audio?upload=0123456789abcdef", SharedLink.audioPage("0123456789abcdef"))
        assertEquals("/share/audio?name=River%20Road%20%26%20Co.mp3", SharedLink.audioPageOf("River Road & Co.mp3"))
        assertEquals("/share/audio?upload=0123456789abcdef", SharedLink.shown("/share/audio?upload=0123456789abcdef"))
        assertNull(SharedLink.shown("/share/audio/cancel"))
        assertTrue(SharedLink.isSharePage("$origin/share/audio?upload=0123456789abcdef", origin))
        assertFalse(SharedLink.isSharePage("$origin/share/audio/cancel", origin))
    }

    @Test
    fun `audio is told from the inbox's files by type, then by name, MIDI being a score's`() {
        for ((type, name) in listOf("audio/mpeg" to "x.bin", "audio/x-m4a" to null, "audio/flac" to "a.flac",
                                    "audio/opus" to "a.opus", "audio/x-aiff" to "a.aif", "audio/webm" to "a.weba",
                                    "application/octet-stream" to "Song.MP3", null to "song.m4a", "*/*" to "a.wav",
                                    "audio/*" to "a.ogg")) {
            assertTrue(AudioShare.isAudio(type, name), "$type $name")
        }
        for ((type, name) in listOf("audio/midi" to "a.mid", "audio/x-midi" to "a.mp3", "application/pdf" to "a.mp3",
                                    "application/x-guitar-pro" to "a.gp5", "application/octet-stream" to "a.gp5",
                                    null to null, "*/*" to "a.mscz", "audio/*" to "a.mid")) {
            assertFalse(AudioShare.isAudio(type, name), "$type $name")
        }
        assertEquals(13, AudioShare.TYPES.size)
    }

    @Test
    fun `the picker takes the audio types for an input that asks for audio, any file else`() {
        assertEquals(AudioShare.TYPES,
                     AudioShare.chooser(arrayOf("audio/*", ".mp3", ".m4a", ".flac", ".wav", ".ogg", ".aif", ".aiff")))
        assertNull(AudioShare.chooser(arrayOf(".caracole", ".sqlite")))
        assertNull(AudioShare.chooser(arrayOf("")))
        assertNull(AudioShare.chooser(null))
    }
}
