package io.github.danielhp95.caracole.youtube

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

/**
 * [YtDlpClient.Redact], the one place the gate's address is taken out of what yt-dlp wrote: by the address's shape
 * ([io.github.danielhp95.caracole.core.youtube.HostGate.PROXY_PATTERN]), whatever option of the argv spelled it
 * (yt-dlp's parser takes any unique prefix, `--prox` too) and wherever the text shows it, then its user and secret
 * apart.
 */
class RedactTest {
    private val user = "0123456789abcdef0123456789abcdef"
    private val secret = "fedcba9876543210fedcba9876543210"
    private val gate = "http://$user:$secret@127.0.0.1:40123"

    private fun clean(text: String) {
        assertFalse(user in text || secret in text, text)
    }

    @Test
    fun `the gate's address is redacted whatever option spelled it`() {
        for (argv in listOf(listOf("--proxy", gate), listOf("--proxy=$gate"), listOf("--prox", gate),
                            listOf("--prox=$gate"), listOf("--pro", gate))) {
            val redact = YtDlpClient.Redact(argv + listOf("--", "http://127.0.0.1:8080/clip.m4a"))
            val said = redact("[debug] Proxy map: {'all': '$gate'}")
            assertEquals("[debug] Proxy map: {'all': '${YtDlpClient.PROXY_SAID}'}", said)
            assertEquals("user ${YtDlpClient.SECRET_SAID}", redact("user $user"))
            assertEquals("secret ${YtDlpClient.SECRET_SAID}", redact("secret $secret"))
        }
    }

    @Test
    fun `an address the argv never named is redacted as the text shows it, and its parts from then on`() {
        val other = "http://${"a".repeat(32)}:${"b".repeat(32)}@127.0.0.1:1"
        val redact = YtDlpClient.Redact(listOf("--version"))
        assertEquals("via ${YtDlpClient.PROXY_SAID}", redact("via $other"))
        val later = redact("the secret ${"b".repeat(32)} alone")
        clean(later)
        assertEquals("the secret ${YtDlpClient.SECRET_SAID} alone", later)
    }

    @Test
    fun `a text with no gate's address is left as it is`() {
        val redact = YtDlpClient.Redact(listOf("--proxy", gate))
        val text = "[download] Destination: /data/user/0/x/cache/into/audio.m4a"
        assertEquals(text, redact(text))
    }
}
