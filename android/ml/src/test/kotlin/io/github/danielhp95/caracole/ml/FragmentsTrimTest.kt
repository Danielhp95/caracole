package io.github.danielhp95.caracole.ml

import io.github.danielhp95.caracole.autochords.frontend.Mp4
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** How [Decoder] ends a fragmented MP4 ([fragmentsKeep]): at its fragments' length where it is read; refused in
 * words where it isn't, never decoded to a length of 0 or cut to nothing; any other MP4 not by its fragments. */
class FragmentsTrimTest {
    private fun track(fragmented: Boolean, fragments: Long?, edits: List<Mp4.Edit> = emptyList()) =
        Mp4.Track(44100, 0, 44100, edits, null, fragmented, fragments)

    @Test fun aFragmentedTrackIsEndedAtItsFragmentsLength() {
        assertEquals(265_624L, fragmentsKeep(track(true, 265_624)))
    }

    @Test fun aFragmentedTrackWhoseFragmentsCantBeReadIsRefusedInWords() {
        val e = assertFailsWith<UndecodableAudio> { fragmentsKeep(track(true, null)) }
        assertTrue(e.message!!.contains("its fragments can't be read"), e.message)
    }

    @Test fun anyOtherTrackIsNotEndedByItsFragments() {
        assertNull(fragmentsKeep(null))
        assertNull(fragmentsKeep(track(false, null)))
        assertNull(fragmentsKeep(track(true, null, listOf(Mp4.Edit(1000, 1024)))))  // its edit list decides
    }
}
