package io.github.danielhp95.caracole.ml

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException

/** What the `:ml` process says of a hearing that failed: a known cause in its words, never "a bug in caracole". */
class MlProtocolTest {
    @Test fun aFullDiskIsNoRoomOnThePhoneInWords() {
        val (kind, words) = MlProtocol.failure(IOException("write failed: ENOSPC (No space left on device)"))
        assertEquals(MlProtocol.SETUP_KIND, kind)
        assertTrue(words, words.startsWith(MlProtocol.NO_ROOM))
        assertFalse(words, "a bug" in words)
    }

    @Test fun aFileThatCantBeWrittenOrMovedSaysSo() {
        val (kind, words) = MlProtocol.failure(IOException("can't move /x/decoded.f32"))
        assertEquals(MlProtocol.SETUP_KIND, kind)
        assertEquals("${MlProtocol.CANT_WRITE}: can't move /x/decoded.f32", words)
        assertEquals("a file of the hearing's can't be read or written", MlProtocol.CANT_WRITE)
    }

    @Test fun anythingElseIsStillABug() {
        assertEquals(MlProtocol.BUG_KIND to "a bug in caracole: java.lang.IllegalStateException: x",
            MlProtocol.failure(IllegalStateException("x")))
    }
}
