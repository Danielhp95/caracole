package io.github.danielhp95.caracole.core.py

import io.github.danielhp95.caracole.core.testing.replays.PyReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** PyUrl's urljoin, urlunsplit and urlencode against urllib.parse's (vectors/py/sites_url.jsonl: RFC 3986's examples,
 * caracole's own calls, random paths). */
class PyUrlTest {
    @Test fun everyRecordAnswersAsUrllibDid() = PyReplay.urls()

    @Test fun ultimateGuitarsArtistLinksJoinAsUgFetchJoinsThem() {
        assertEquals("https://www.ultimate-guitar.com/artist/soda_stereo_2946",
                     PyUrl.urljoin("https://www.ultimate-guitar.com/", "/artist/soda_stereo_2946"))
        assertEquals("https://www.ultimate-guitar.com/artist/x",
                     PyUrl.urljoin("https://www.ultimate-guitar.com/", "//www.ultimate-guitar.com/artist/x"))
        assertEquals("http://a/b/c/g", PyUrl.urljoin("http://a/b/c/d;p?q", "../c/g"))
        assertEquals("http://a/g", PyUrl.urljoin("http://a/b/c/d;p?q", "../../../g"))
    }

    @Test fun anArtistPagesAddressIsPutBackAsUgArtistPutsIt() {
        val query = PyUrl.urlencode(listOf("filter" to "chords", "page" to "2"))
        assertEquals("https://www.ultimate-guitar.com/artist/soda_stereo_2946?filter=chords&page=2",
                     PyUrl.urlunsplit(PyUrl.Split("https", "www.ultimate-guitar.com", "/artist/soda_stereo_2946", query, "")))
        assertEquals("http:///x", PyUrl.urlunsplit(PyUrl.Split("http", "", "/x", "", "")))
    }

    @Test fun urlencodeQuotesAsQuotePlus() {
        assertEquals("q=Soda+Stereo&a%2Bb=%C3%A9%F0%9F%98%80~-_.", PyUrl.urlencode(listOf("q" to "Soda Stereo", "a+b" to "é\uD83D\uDE00~-_.")))
        assertEquals("k=a&k=b&j=x", PyUrl.urlencodeDoseq(listOf("k" to listOf("a", "b"), "j" to listOf("x"), "e" to emptyList())))
        assertFailsWith<IllegalArgumentException> { PyUrl.urlencode(listOf("k" to "\uD800")) }
    }
}
