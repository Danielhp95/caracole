package io.github.danielhp95.caracole.core.ug

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.replays.UgPagesReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

/** ug/artist.py's artist pages against Python's answers (vectors/sites/ug_artist.jsonl), and a few by hand. */
class UgArtistTest {
    private val soda = "https://www.ultimate-guitar.com/artist/soda_stereo_2946"

    @Test fun everyRecordAnswersAsPythonDid() = UgPagesReplay.artists()

    @Test fun aListsAddressNamesItsKindAndItsPageAlone() {
        assertEquals(soda, UgArtist.pageUrl(soda))
        assertEquals("$soda?filter=chords&page=2", UgArtist.pageUrl(soda, "chords", 2))
        assertEquals("$soda?page=4", UgArtist.pageUrl(soda, null, 4))
        assertEquals("$soda?filter=chords", UgArtist.pageUrl("$soda/?filter=tabs&page=4#x", "chords"))
    }

    @Test fun aKindWithNoListOrAPageBelowOneIsRefusedInPythonsWords() {
        assertEquals("no artist-page filter for kind 'bass'",
                     assertFailsWith<IllegalArgumentException> { UgArtist.pageUrl(soda, "bass") }.message)
        assertEquals("page must be 1 or more, not 0",
                     assertFailsWith<IllegalArgumentException> { UgArtist.pageUrl(soda, null, 0) }.message)
        assertEquals("Invalid IPv6 URL", assertFailsWith<IllegalArgumentException> { UgArtist.pageUrl("http://[::1") }.message)
    }

    @Test fun theSodaStereoPageListsItsTabsItsPagesAndItsTwoLists() {
        val page = UgArtist.parse(Corpus.fixture("ug/artist.html"), soda)
        assertEquals(2946L to "Soda Stereo", page.artistId to page.name)
        assertEquals(1 to 6, page.page to page.pages)
        assertEquals(setOf("chords", "tabs"), page.filters)
        assertEquals(27, page.tabs.size)
    }
}
