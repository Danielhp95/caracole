package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.autochords.ChordsUnavailable
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/** The bench's work folder is emptied only once the `:ml` process is gone: one told to Stop stops at its next chunk
 * and may write a checkpoint after its client gave up, and after the last song nothing else would wait for it. */
class BenchHearingsTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun aCheckpointWrittenWhileTheProcessEndsIsDeletedAllTheSame() {
        val work = File(tmp.root, BenchHearings.WORK).apply { mkdirs() }
        val order = mutableListOf<String>()
        BenchHearings.leaveNothing(work) {
            order += "waited"
            File(work, "late-checkpoint").writeText("written by :ml after the Stop")
        }
        assertEquals(listOf("waited"), order)
        assertFalse(work.exists())
    }

    @Test fun aProcessStillEndingAfterTheWaitLeavesTheFolderDeletedAllTheSame() {
        val work = File(tmp.root, BenchHearings.WORK).apply { mkdirs() }
        File(work, "checkpoint").writeText("x")
        BenchHearings.leaveNothing(work) { throw ChordsUnavailable("still ending") }
        assertFalse(work.exists())
    }
}
