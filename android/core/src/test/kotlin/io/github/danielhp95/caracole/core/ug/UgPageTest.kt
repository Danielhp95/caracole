package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.http.PageParseError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.testing.replays.UgPagesReplay
import io.github.danielhp95.caracole.core.ug.internal.pages.PyValues
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import java.math.BigInteger
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** ug/page.py's tab pages and ug/lookup.py's index reads against Python's answers (vectors/sites/ug_pages.jsonl and
 * ug_pages_lookup.jsonl), and the cases a corpus line can't hold. */
class UgPageTest {
    @Test fun everyRecordAnswersAsPythonDid() = UgPagesReplay.pages()

    @Test fun theIndexsReadsAnswerAsPythonsDid() = UgPagesReplay.lookup()

    @Test fun aTypesKindIsItsTypeStrippedAndLoweredAsPythonsStrDoes() {
        assertEquals("chords", UgPage.kindOf(" CHORDS "))
        assertEquals("ukulele", UgPage.kindOf("Ukulele Chords"))
        assertEquals("tabs", UgPage.kindOf("\u001ctabs\u001f"))
        assertNull(UgPage.kindOf("Pro"))
        assertNull(UgPage.kindOf("Ukulele  Chords"))
        assertNull(UgPage.kindOf(null))
    }

    @Test fun aSluggedTabsUrlIsItsPathAndABareOnesItsId() {
        assertEquals("https://tabs.ultimate-guitar.com/tab/85053", UgPage.pageUrl(85053))
        assertEquals("https://tabs.ultimate-guitar.com/tab/a/b-chords-1", UgPage.pageUrl(1, "//a/b-chords-1"))
        assertEquals("https://tabs.ultimate-guitar.com/tab/1", UgPage.pageUrl(1, ""))
        assertEquals("https://tabs.ultimate-guitar.com/tab/radiohead/creep-chords-4169",
                     IndexTab(4169, "chords", "creep", null, "radiohead/creep-chords-4169").url)
    }

    @Test fun anEntityLeftAfterOnePassIsDecodedAgainAsPythonsRegexFindsOne() {
        assertEquals("&feature", UgPage.decodeTwice("&amp;amp;feature"))
        assertEquals("&x &#١٢;", UgPage.decodeTwice("&amp;ampx &#١٢;"))  // \d: any decimal digit
        assertEquals("&x &K;", UgPage.decodeTwice("&amp;ampx &K;"))  // [a-z] under IGNORECASE: the Kelvin sign
        assertEquals("&ampx &é;", UgPage.decodeTwice("&amp;ampx &é;"))  // é is no letter of [a-z]
    }

    @Test fun aVersionsFieldsAreReadAsPythonsFloatAndStrReadThem() {
        val v = UgPage.parseVersion(PyJson.loads(
            """{"id": "٣١", "type": "Chords", "rating": " 4.5\n", "votes": true, "version": 2.0, "song_name": [1, "a", null],
               "part": " SOLO ", "recording": {"is_acoustic": "0.5"}, "tab_url": "", "version_description": 0}"""))!!
        assertEquals(31L, v.tabId)
        assertEquals(4.5, v.rating)
        assertEquals(1, v.votes)
        assertEquals(2, v.version)
        assertEquals("[1, 'a', None]", v.songName)
        assertEquals("solo", v.label)
        assertTrue(v.isAcoustic)
        assertEquals("https://tabs.ultimate-guitar.com/tab/31", v.url)
        assertEquals("0", v.description)
        assertNull(UgPage.parseVersion(PyJson.loads("""{"id": 1.5, "type": "Chords"}""")))
        assertNull(UgPage.parseVersion(PyJson.loads("""{"id": 1, "type": 0.0}""")))
        assertEquals(1L, UgPage.parseVersion(PyJson.loads("""{"id": 1, "type": NaN}"""))!!.tabId)  // NaN is true
    }

    @Test fun aNumberPastWhatThePhoneKeepsIsNone() {
        assertEquals(BigInteger.TEN.pow(20), UgPage.jsonInt(JsonPrimitive("1e20")))
        assertNull(UgPage.parseVersion(PyJson.loads("""{"id": 1e20, "type": "Chords"}""")))
        assertEquals(0, UgPage.parseVersion(PyJson.loads("""{"id": 1, "type": "Chords", "votes": 3e9}"""))!!.votes)
    }

    @Test fun aLoneSurrogateIsReplacementAndAWholePairStays() {
        val loaded = PyJson.loads("""{"\udc00": ["a\ud83d", "😀", "\ude00\ud83d"], "k\ud800": "\ud800𐀀"}""")
        val whole = PyValues.whole(loaded).jsonObject
        assertEquals(listOf("�", "k�"), whole.keys.toList())
        assertEquals("[\"a�\", \"😀\", \"��\"]", PyJson.dumps(whole.getValue("�")))
        assertEquals("�𐀀", whole.getValue("k�").jsonPrimitive.content)
        val merged = PyValues.whole(PyJson.loads("""{"\ud800": 1, "x": 2, "\udc00": 3}""")).jsonObject
        assertEquals(JsonObject(linkedMapOf("�" to JsonPrimitive(3), "x" to JsonPrimitive(2))).toString(), merged.toString())
        assertTrue(PyValues.escapesASurrogate("""x\uDBFFy"""))
        assertTrue(!PyValues.escapesASurrogate("""xé ퟿"""))
    }

    @Test fun aLoneSurrogateOnAPageIsReplacementInTheSheetTheNamesAndTheKeys() {
        val payload = """{"store":{"page":{"data":{"tab":{"id":1,"type":"Chords","song_name":"Zebra \udc00"},
            "tab_view":{"versions":[],"wiki_tab":{"content":"la \ud83d la 😀"},"meta":{"\udc00":1}}}}}}"""
        val html = "<div class=\"js-store\" data-content=\"${payload.replace("\"", "&quot;")}\"></div>"
        val page = UgPage.parseTabPage(html.toByteArray())
        assertEquals("la � la 😀", page.content)
        assertEquals("Zebra �", page.tab.songName)
        assertEquals(listOf("�"), page.meta.keys.toList())
    }

    @Test fun aPageNestedPastWhatThePhoneReadsIsAParseError() {
        val html = "<div class=\"js-store\" data-content=\"${"[".repeat(PyJson.MAX_DEPTH + 1)}\"></div>"
        val e = assertFailsWith<PageParseError> { UgPage.parseTabPage(html.toByteArray(), "https://u/x") }
        assertTrue(e.message!!.startsWith("ug: https://u/x: js-store is not valid JSON: "), e.message)
        assertTrue(e.cause is PyJson.RecursionError)
    }
}
