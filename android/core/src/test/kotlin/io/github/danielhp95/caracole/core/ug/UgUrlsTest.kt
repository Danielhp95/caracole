package io.github.danielhp95.caracole.core.ug

import org.junit.Test
import kotlin.test.assertEquals

/** ug_urls.read_link on the phone: a text pasted into the search box read as the UG link it is, or as words, over
 * tests/helpers/ug_links.py's shapes (vectors/web/ug_link.jsonl holds every one to Python's answers too). */
class UgUrlsTest {
    private val shapes: List<Pair<String, UgLink?>> = listOf(
        "https://tabs.ultimate-guitar.com/tab/4180894" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/4180894", 4180894L, null),
        "tabs.ultimate-guitar.com/tab/4180894" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/4180894", 4180894L, null),
        "http://tabs.ultimate-guitar.com/tab/4180894" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/4180894", 4180894L, null),
        "HTTPS://TABS.ULTIMATE-GUITAR.COM/tab/4180894" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/4180894", 4180894L, null),
        "https://tabs.ultimate-guitar.com/tab/4180894?ref=share&utm_source=app#comments" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/4180894", 4180894L, null),
        "https://tabs.ultimate-guitar.com/tab/4180894/" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/4180894", 4180894L, null),
        "  https://tabs.ultimate-guitar.com/tab/4180894\u3000" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/4180894", 4180894L, null),
        "\u0009https://tabs.ultimate-guitar.com/tab/4180894\u000a" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/4180894", 4180894L, null),
        "https://ultimate-guitar.com/tab/4180894" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/4180894", 4180894L, null),
        "https://www.ultimate-guitar.com/tab/4180894" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/4180894", 4180894L, null),
        "https://es.ultimate-guitar.com/tab/4180894" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/4180894", 4180894L, null),
        "https://tabs.ultimate-guitar.com/tab/soda-stereo/de-musica-ligera-chords-85053" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/soda-stereo/de-musica-ligera-chords-85053", 85053L, "chords"),
        "ultimate-guitar.com/tab/soda-stereo/de-musica-ligera-chords-85053?app=1" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/soda-stereo/de-musica-ligera-chords-85053", 85053L, "chords"),
        "https://tabs.ultimate-guitar.com/tab/radiohead/creep-tabs-4169" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/radiohead/creep-tabs-4169", 4169L, "tabs"),
        "https://tabs.ultimate-guitar.com/tab/vance-joy/riptide-ukulele-1237247" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/vance-joy/riptide-ukulele-1237247", 1237247L, "ukulele"),
        "https://tabs.ultimate-guitar.com/tab/metallica/one-guitar-pro-225441" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/metallica/one-guitar-pro-225441", 225441L, "guitar-pro"),
        "https://tabs.ultimate-guitar.com/tab/metallica/one-power-71542" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/metallica/one-power-71542", 71542L, "power"),
        "https://tabs.ultimate-guitar.com/tab/oasis/wonderwall-official-1956589" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/oasis/wonderwall-official-1956589", 1956589L, "official"),
        "https://tabs.ultimate-guitar.com/tab/muse/hysteria-bass-91003" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/muse/hysteria-bass-91003", 91003L, "bass"),
        "https://tabs.ultimate-guitar.com/tab/toto/rosanna-drums-850391" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/toto/rosanna-drums-850391", 850391L, "drums"),
        "https://tabs.ultimate-guitar.com/tab/a/song-2-tabs-chords-77" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/a/song-2-tabs-chords-77", 77L, "chords"),
        "https://tabs.ultimate-guitar.com/tab/a/b-77" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/a/b-77", 77L, null),
        "https://tabs.ultimate-guitar.com/tab/a/77" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/a/77", 77L, null),
        "https://tabs.ultimate-guitar.com/tab/b-chords-77" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/b-chords-77", 77L, null),
        "https://tabs.ultimate-guitar.com/tab/%E5%AE%8B/%E6%96%91-chords-77" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/%E5%AE%8B/%E6%96%91-chords-77", 77L, "chords"),
        "https://tabs.ultimate-guitar.com/tab/宋冬野/斑马-chords-77" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/宋冬野/斑马-chords-77", 77L, "chords"),
        "https://tabs.ultimate-guitar.com/tab/٣٤" to UgLink("tab", "https://tabs.ultimate-guitar.com/tab/٣٤", 34L, null),
        "https://www.ultimate-guitar.com/artist/634073" to UgLink("artist", "https://www.ultimate-guitar.com/artist/634073", null, null),
        "https://www.ultimate-guitar.com/artist/634073?filter=chords&page=2" to UgLink("artist", "https://www.ultimate-guitar.com/artist/634073", null, null),
        "ultimate-guitar.com/artist/soda_stereo_2946" to UgLink("artist", "https://www.ultimate-guitar.com/artist/soda_stereo_2946", null, null),
        "https://tabs.ultimate-guitar.com/artist/soda_stereo_2946/" to UgLink("artist", "https://www.ultimate-guitar.com/artist/soda_stereo_2946", null, null),
        "https://www.ultimate-guitar.com/artist/٣" to UgLink("artist", "https://www.ultimate-guitar.com/artist/٣", null, null),
        "https://www.ultimate-guitar.com/artist/soda_stereo" to null,
        "https://www.ultimate-guitar.com" to null,
        "https://www.ultimate-guitar.com/" to null,
        "https://www.ultimate-guitar.com/explore?type[]=Chords" to null,
        "https://www.ultimate-guitar.com/search.php?search_type=title&value=banma" to null,
        "https://www.ultimate-guitar.com/forum/showthread.php?t=1" to null,
        "https://tabs.ultimate-guitar.com/tab/download?id=4180894" to null,
        "https://tabs.ultimate-guitar.com/tab/print?id=4180894" to null,
        "https://tabs.ultimate-guitar.com/tab/" to null,
        "https://tabs.ultimate-guitar.com/tab/4180894x" to null,
        "https://tabs.ultimate-guitar.com/tab/4180894;x" to null,
        "宋冬野 https://tabs.ultimate-guitar.com/tab/4180894" to null,
        "https://tabs.ultimate-guitar.com/tab/4180894 chords" to null,
        "https://tabs.ultimate-guitar.com/tab/4180894\u00a0x" to null,
        "https://tabs.ultimate-guitar.com/tab/4180894\u001cx" to null,
        "4180894" to null,
        "ultimate guitar banma" to null,
        "song dongye 斑马斑马" to null,
        "https://ultimate-guitar.com.evil.example/tab/4180894" to null,
        "https://evil.example/tabs.ultimate-guitar.com/tab/4180894" to null,
        "https://m.ultimate-guitar.com/tab/4180894" to null,
        "ftp://tabs.ultimate-guitar.com/tab/4180894" to null,
        "https:/tabs.ultimate-guitar.com/tab/4180894" to null,
        "https:///tabs.ultimate-guitar.com/tab/4180894" to null,
        "//tabs.ultimate-guitar.com/tab/4180894" to null,
        "https://tabs.ultimate-guitar.com:443/tab/4180894" to null,
        "tabs.ultimate-guitar.com:443/tab/4180894" to null,
        "https://user@tabs.ultimate-guitar.com/tab/4180894" to null,
        "https://[tabs.ultimate-guitar.com/tab/4180894" to null,
        "mailto:tabs.ultimate-guitar.com/tab/4180894" to null,
        "httpſ://tabs.ultimate-guitar.com/tab/4180894" to null,
        "https://tabs.ultimate-guitar.com?x=/tab/4180894" to null,
        "https://tabs.ultimate-guitar.com#/tab/4180894" to null,
        "https://www.youtube.com/watch?v=lzN7Thn3FV4" to null,
        "" to null,
        "   " to null,
    )

    @Test fun everyShapeIsReadAsPythonReadsIt() {
        for ((text, want) in shapes) assertEquals(want, UgUrls.readLink(text), text)
    }

    @Test fun anIdPastALongIsNoLinkThePhoneReads() {
        assertEquals(null, UgUrls.readLink("https://tabs.ultimate-guitar.com/tab/99999999999999999999"))
    }
}
