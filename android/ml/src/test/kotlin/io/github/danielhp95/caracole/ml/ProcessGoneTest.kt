package io.github.danielhp95.caracole.ml

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import io.github.danielhp95.caracole.autochords.ChordsUnavailable

/** A hearing waits for the last hearing's `:ml` process to be gone before it binds, and refuses in words where it
 * outlives the wait, never binding a process on its way out. */
class ProcessGoneTest {
    private class Clock {
        var now = 0L
        fun sleep(ms: Long) { now += ms }
    }

    @Test fun aProcessThatGoesWithinTheWaitIsWaitedFor() {
        val c = Clock()
        var waited = 0
        MlChordModels.awaitGone({ if (c.now < 3_000) 42 else null }, { c.now }, c::sleep) { waited++ }
        assertEquals(3_000L, c.now)
        assertEquals(30, waited)
    }

    @Test fun aProcessStillThereAfterTheWaitIsRefusedInWords() {
        val c = Clock()
        val e = assertThrows(ChordsUnavailable::class.java) {
            MlChordModels.awaitGone({ 42 }, { c.now }, c::sleep) {}
        }
        assertEquals(MlChordModels.STILL_ENDING, e.message)
        assertEquals(MlChordModels.PROCESS_GONE_MS, c.now)
    }
}
