package io.github.danielhp95.caracole

import io.github.danielhp95.caracole.autochords.ChordsUnavailable
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.concurrent.CancellationException

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

    @Test fun anyOtherFailureOfTheWaitLeavesTheFolderDeletedAndThrowsNothing() {
        val work = File(tmp.root, BenchHearings.WORK).apply { mkdirs() }
        File(work, "checkpoint").writeText("x")
        BenchHearings.leaveNothing(work) { throw SecurityException("the running processes can't be read") }
        assertFalse(work.exists())
    }

    @Test fun aStopThatInterruptsTheWaitDeletesTheFolderAndKeepsTheInterrupt() {
        val work = File(tmp.root, BenchHearings.WORK).apply { mkdirs() }
        File(work, "checkpoint").writeText("x")
        try {
            // InterruptedException is thrown with the thread's flag already cleared: the Stop must not be lost.
            BenchHearings.leaveNothing(work) { throw InterruptedException("stopped") }
            assertFalse(work.exists())
            assertTrue("the interrupt is set again", Thread.currentThread().isInterrupted)
        } finally {
            Thread.interrupted()
        }
    }

    @Test fun aCancelledWaitDeletesTheFolderThenGoesOnBeingCancelled() {
        val work = File(tmp.root, BenchHearings.WORK).apply { mkdirs() }
        File(work, "checkpoint").writeText("x")
        val cancelled = CancellationException("the bench's job was cancelled")
        try {
            BenchHearings.leaveNothing(work) { throw cancelled }
            fail("a cancellation is never swallowed")
        } catch (e: CancellationException) {
            assertSame(cancelled, e)
        }
        assertFalse(work.exists())
    }
}
