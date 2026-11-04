package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.OverridesReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull

/**
 * The addresses a user pastes, read as overrides.py, youtube_urls.py and ug/sitemap.py read them: every reader over
 * the texts of tests/test_overrides.py, test_get.py and test_sitemap.py (vectors/library/override_urls.jsonl), and
 * what no record shows: the numbers past what the phone holds, the picks' addresses.
 */
class OverrideUrlsTest {
    @Test fun everyAddressIsReadAsPythonReadsIt() =
        Misses(OverridesReplay.URLS).also { OverridesReplay.urls(it) }.assertNone()

    @Test fun aTabIdPastALongIsNoTabPage() {
        // Python's int has no end; a tab id that long is no UG tab's.
        val e = assertFailsWith<OverridesError> { OverrideUrls.tabIdFromUrl("99999999999999999999") }
        assertEquals("not an Ultimate Guitar tab URL: '99999999999999999999'", e.message)
        assertFailsWith<OverridesError> {
            OverrideUrls.tabIdFromUrl("https://tabs.ultimate-guitar.com/tab/a/b-chords-99999999999999999999")
        }
        assertEquals(OverrideUrls.UNRECOGNIZED,
                     OverrideUrls.classifyTabUrl("https://tabs.ultimate-guitar.com/tab/a/b-chords-99999999999999999999"))
    }

    @Test fun aLaCuerdaVersionPastAnIntIsNoPage() {
        assertFailsWith<OverridesError> {
            OverrideUrls.lacuerdaPickFromUrl("https://acordes.lacuerda.net/estopa/como_camaron-9999999999.shtml")
        }
    }

    @Test fun eachPickIsAskedForAtItsOwnAddress() {
        assertEquals("https://acordes.lacuerda.net/estopa/como_camaron", LaCuerdaPick("estopa", "como_camaron").url)
        assertEquals("https://acordes.lacuerda.net/estopa/como_camaron.shtml", LaCuerdaPick("estopa", "como_camaron", 1).url)
        assertEquals("https://acordes.lacuerda.net/estopa/como_camaron-2.shtml",
                     LaCuerdaPick("estopa", "como_camaron", 2).url)
        assertEquals("tab/25/piano-man", HarpTabsPick(25, "piano-man").path)
        assertEquals("https://www.harptabs.com/tab/25/piano-man", HarpTabsPick(25, "piano-man").url)
        assertEquals("https://gametabs.net/tabs/actraiser/fillmore", GameTabsPick("actraiser", "fillmore").url)
    }

    @Test fun aTabPageOfAKeptTypeHasARowAndNoReason() {
        val url = "https://tabs.ultimate-guitar.com/tab/the-rifles/the-general-chords-6228251"
        assertNull(OverrideUrls.classifyTabUrl(url))
        assertEquals(TabUrlRow(6228251, "rifles", "general", "chords", "the-rifles/the-general-chords-6228251"),
                     OverrideUrls.parseTabUrl(url))
        assertEquals("guitar-pro", OverrideUrls.classifyTabUrl("https://tabs.ultimate-guitar.com/tab/a/b-guitar-pro-1"))
        assertNull(OverrideUrls.parseTabUrl("https://tabs.ultimate-guitar.com/tab/1"))
    }
}
