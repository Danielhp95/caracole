package io.github.danielhp95.caracole.core.http

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.HttpReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** URLs as httpx renders them: vectors/http/urls.jsonl, and the cases caracole leans on most. */
class UrlsTest {
    @Test fun everyUrlIsHttpxs() {
        val misses = Misses("http/urls.jsonl")
        HttpReplay.urls(misses)
        misses.assertNone()
    }

    @Test fun paramsReplaceTheQueryWithSpacesAsPlus() {
        assertEquals("https://lrclib.net/api/search?track_name=x+y&artist_name=a%2Bb",
                     Urls.withParams("https://lrclib.net/api/search?old=1", listOf("track_name" to "x y", "artist_name" to "a+b")))
        assertEquals("https://x.test/p?a=1&a=3&b=2", Urls.withParams("https://x.test/p", listOf("a" to "1", "b" to "2", "a" to "3")))
    }

    @Test fun theTargetIsThePathAndQueryAsHttpxEncodesThem() {
        assertEquals("/caf%C3%A9%20au%20lait?q=ni%C3%B1o", Urls.target("https://x.test/café au lait?q=niño#top"))
        assertEquals("/", Urls.target("https://x.test"))
    }

    @Test fun theSiteIsTheHostsLastTwoLabels() {
        assertEquals("ultimate-guitar.com", Urls.site("https://tabs.ultimate-guitar.com/tab/1"))
        assertEquals("müller.de", Urls.host("https://xn--mller-kva.de/").let { Urls.site("https://$it/") })
    }

    @Test fun aRelativeLocationIsJoinedToTheUrlItAnswered() {
        assertEquals("https://tabs.ultimate-guitar.com/tab/a/new-chords-1",
                     Urls.resolve("https://tabs.ultimate-guitar.com/tab/a/old-chords-1", "new-chords-1"))
        val bad = assertFailsWith<UrlError> { Urls.resolve("https://x.test/a", "https://[::zz]/") }
        assertEquals("RemoteProtocolError", bad.kind)
    }
}
