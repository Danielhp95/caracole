package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.CatalogueOffer.Answer
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The first start's offer of the site catalogues as the library screen holds it (MainActivity's card): shown once the
 * opening screen is gone, Back its Not now while it shows, gone once a computer is set, answered once.
 */
class CatalogueOfferTest {
    @Test
    fun itShowsOnceTheOpeningScreenIsGone() {
        val offer = CatalogueOffer()
        assertFalse(offer.openingGone(), "nothing offered: nothing shown")
        offer.offer(thenSettings = true)
        assertTrue(offer.waiting)
        assertFalse(offer.shown, "under the opening screen: not shown, not live")
        assertTrue(offer.openingGone())
        assertTrue(offer.shown)
    }

    @Test
    fun backWhileItShowsIsItsNotNow() {
        val offer = CatalogueOffer().apply { offer(thenSettings = true) }
        assertNull(offer.back(), "under the opening screen Back isn't its: the app goes, the offer still to answer")
        assertTrue(offer.waiting)
        offer.openingGone()
        assertEquals(Answer(download = false, openSettings = true), offer.back(), "a first start with nothing set up")
        assertFalse(offer.waiting)
        assertFalse(offer.shown)
        assertNull(offer.back(), "answered once: Back is the WebView's again")
    }

    @Test
    fun notNowOpensSettingsOnlyWhereAFirstStartWouldHaveAndNotOnceItWasSeen() {
        val set = CatalogueOffer().apply { offer(thenSettings = false); openingGone() }
        assertEquals(Answer(download = false, openSettings = false), set.answer(download = false))
        val seen = CatalogueOffer().apply { offer(thenSettings = true); openingGone() }
        seen.settingsSeen()  // ⋮ › Settings while it waited
        assertEquals(Answer(download = false, openSettings = false), seen.back())
        val download = CatalogueOffer().apply { offer(thenSettings = false); openingGone() }
        assertEquals(Answer(download = true, openSettings = true), download.answer(download = true),
                     "Download opens Settings, whose row follows the job")
    }

    @Test
    fun aComputerSetMeanwhileTakesItAwayOpeningNothing() {
        val offer = CatalogueOffer().apply { offer(thenSettings = true); openingGone() }
        assertNull(offer.resumed(server = ""), "still no computer: it stays")
        assertNull(offer.resumed(server = "   "))
        assertTrue(offer.waiting)
        assertEquals(Answer(download = false, openSettings = false), offer.resumed(server = "http://192.168.1.20:8737"))
        assertFalse(offer.waiting)
        assertNull(offer.resumed(server = "http://192.168.1.20:8737"), "answered once")
        // A computer set before it showed (the opening screen still up): it never shows.
        val early = CatalogueOffer().apply { offer(thenSettings = true) }
        assertEquals(Answer(download = false, openSettings = false), early.resumed(server = "http://192.168.1.20:8737"))
        assertFalse(early.openingGone())
    }

    @Test
    fun itIsKeptAcrossARecreationUntilAnswered() {
        val offer = CatalogueOffer().apply { offer(thenSettings = true) }
        val again = CatalogueOffer().apply { restore(offer.saved()) }
        assertTrue(again.waiting)
        assertTrue(again.openingGone())
        assertEquals(Answer(download = false, openSettings = true), again.back())
        assertNull(CatalogueOffer().apply { restore(again.saved()) }.back(), "answered: nothing to keep")
        assertFalse(CatalogueOffer().apply { restore(null) }.waiting)
    }
}
