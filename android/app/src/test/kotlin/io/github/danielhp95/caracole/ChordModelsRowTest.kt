package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.ChordModelsRow.Last
import io.github.danielhp95.caracole.ChordModelsRow.Line
import io.github.danielhp95.caracole.ChordModelsRow.Row
import io.github.danielhp95.caracole.server.jobs.Job
import io.github.danielhp95.caracole.server.lookups.ModelsRunner
import org.junit.Test
import kotlin.test.assertEquals

/** Settings' "Chords from audio" row (the chords-on-the-phone design's §8.3): its line for each state, and what it
 * offers, from the models' size, ModelsRunner.ready, what keeps the phone from chords, and the newest models job. */
class ChordModelsRowTest {
    private val size = 54_000_000L  // the design's 54 MB (this build's pins are 56,312,162 bytes: "56 MB")
    private val missing = "The chord models aren't on the phone."

    @Test fun `not downloaded says the size and offers Download`() {
        assertEquals(Row(Line.NOT_DOWNLOADED, "54 MB", download = true, remove = false),
                     ChordModelsRow.of(size, missing, null, null))
        // a job over that installed nothing more (a Remove since): as none
        assertEquals(Line.NOT_DOWNLOADED, ChordModelsRow.of(size, missing, null, Last(Job.DONE, "Chord models ready · 54 MB")).line)
    }

    @Test fun `a download on its way says how far, and offers nothing`() {
        assertEquals(Row(Line.DOWNLOADING, "21 of 54 MB", download = false, remove = false),
                     ChordModelsRow.of(size, missing, null, Last(Job.RUNNING, "Downloading the chord models · 21 of 54 MB",
                                                                 21_000_000, size)))
        assertEquals("0 of 54 MB", ChordModelsRow.of(size, missing, null, Last(Job.QUEUED, "")).text)
    }

    @Test fun `ready says what the phone holds, and offers Remove`() {
        assertEquals(Row(Line.READY, "54 MB", download = false, remove = true), ChordModelsRow.of(size, null, null, null))
    }

    @Test fun `a phone that can't make chords says why, and offers no download`() {
        assertEquals(Row(Line.CANT, "chords from audio need Android 13 or later", download = false, remove = false),
                     ChordModelsRow.of(size, missing, "chords from audio need Android 13 or later", null))
        assertEquals(Row(Line.CANT, ModelsRunner.NOT_CARRIED, download = false, remove = false),
                     ChordModelsRow.of(null, ModelsRunner.NOT_CARRIED, "auto-chords isn't on the phone", null))
    }

    @Test fun `a metered network's stop waits for the go-ahead, which Download gives`() {
        val waiting = Last(Job.DONE, "54 MB to download: waiting for your go-ahead in Settings (a metered network)")
        assertEquals(Row(Line.WAITING, "54 MB", download = true, remove = false), ChordModelsRow.of(size, missing, null, waiting))
    }

    @Test fun `a download that failed says why, and offers Download again`() {
        assertEquals(Row(Line.CANT, "No room for the chord models.", download = true, remove = false),
                     ChordModelsRow.of(size, missing, null, Last(Job.FAILED, "Not downloaded: No room for the chord models.")))
        // GitHub's hour spent: a wait in its own words
        val limited = "GitHub asks caracole to wait until 13:00 (its hour's requests are spent)."
        assertEquals(Row(Line.CANT, limited, download = true, remove = false),
                     ChordModelsRow.of(size, missing, null, Last(Job.DONE, limited)))
    }
}
