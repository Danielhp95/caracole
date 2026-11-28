package io.github.danielhp95.caracole.ml

import io.github.danielhp95.caracole.autochords.ChordsUnavailable
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.util.concurrent.CancellationException

/** What a hearing holds around the `:ml` process's work (MlChordModels.guarded), with no device: the battery floor
 * before anything is taken, one hearing at a time across the app's processes (the app's jobs and the debug build's
 * bench), a partial wake lock held only while it runs and let go on every path, what the hearing throws as itself;
 * the device's own reasons not to hear (design §8.1); and the start's sweep of checkpoints a killed app left. */
class HearingGuardTest {
    @get:Rule val tmp = TemporaryFolder()

    private class Wake : MlChordModels.Wake {
        var held = false
        var holds = 0
        override fun hold(ms: Long) {
            assertEquals(MlChordModels.WAKE_MS, ms)
            held = true
            holds++
        }
        override fun release() {
            held = false
        }
    }

    private fun gauge(percent: Int?, plugged: Boolean?) = HeatGauge { Heat.Reading("none", null, null, percent, plugged, false) }

    private val charged = gauge(80, false)

    @Test fun theWakeLockIsHeldWhileTheHearingRunsAndLetGoAfter() {
        val wake = Wake()
        val turn = tmp.newFile("turn")
        val answer = MlChordModels.guarded(charged, { MlChordModels.turn(turn) }, wake) { w ->
            assertSame(wake, w)
            assertTrue("held while it runs", wake.held)
            "heard"
        }
        assertEquals("heard", answer)
        assertFalse(wake.held)
        assertNotNull("the turn given back", MlChordModels.turn(turn)?.also { it.close() })
    }

    /** Whatever the hearing throws propagates as itself (a queue's stop is never a setup's failure), the wake lock let
     * go and the turn given back on every path. */
    @Test fun whatTheHearingThrowsPropagatesAsItselfAndLetsGoOfEverything() {
        val turn = tmp.newFile("turn")
        for (thrown in listOf(CancellationException("the queue stopped"), ChordsUnavailable(MlChordModels.DIED),
                              IllegalStateException("a bug in caracole: …"), InterruptedException())) {
            val wake = Wake()
            val e = assertThrows(Throwable::class.java) {
                MlChordModels.guarded(charged, { MlChordModels.turn(turn) }, wake) { throw thrown }
            }
            assertSame(thrown, e)
            assertFalse("$thrown: the wake lock let go", wake.held)
            assertNotNull("$thrown: the turn given back", MlChordModels.turn(turn)?.also { it.close() })
        }
    }

    /** Below 15 % and not charging (or not known to be), refused before the process is started, nothing taken. */
    @Test fun aLowBatteryNotChargingRefusesBeforeAnythingIsTaken() {
        for (low in listOf(gauge(14, false), gauge(3, null))) {
            val wake = Wake()
            var taken = false
            val e = assertThrows(ChordsUnavailable::class.java) {
                MlChordModels.guarded(low, { taken = true; null }, wake) { error("heard") }
            }
            assertEquals(HeatRules.CHARGE_FIRST, e.message)
            assertFalse(taken)
            assertEquals(0, wake.holds)
        }
        // Charging, or a battery it can't read: it goes.
        for (ok in listOf(gauge(5, true), gauge(null, null), gauge(15, false))) {
            assertEquals("heard", MlChordModels.guarded(ok, { MlChordModels.turn(tmp.newFile()) }, Wake()) { "heard" })
        }
    }

    /** One hearing at a time: the turn another hearing holds (the bench's, in its own process, or another of this
     * one's) refuses this one in words, before any wake lock or bind. */
    @Test fun anotherHearingUnderWayIsRefusedPlainly() {
        val turn = tmp.newFile("turn")
        val other = MlChordModels.turn(turn)!!
        try {
            assertNull("taken already", MlChordModels.turn(turn))
            val wake = Wake()
            val e = assertThrows(ChordsUnavailable::class.java) {
                MlChordModels.guarded(charged, { MlChordModels.turn(turn) }, wake) { error("heard") }
            }
            assertEquals(MlChordModels.BUSY, e.message)
            assertEquals(0, wake.holds)
        } finally {
            other.close()
        }
        assertEquals("heard", MlChordModels.guarded(charged, { MlChordModels.turn(turn) }, Wake()) { "heard" })
    }

    @Test fun thePhonesOwnReasonsNotToHearAreTheDesignsWords() {
        val big = 8L shl 30
        assertNull(MlChordModels.deviceProblem(33, big, listOf("arm64-v8a")))
        assertNull(MlChordModels.deviceProblem(36, MlChordModels.LEAST_MEMORY, listOf("x86_64", "arm64-v8a")))
        assertEquals("chords from audio need Android 13 or later",
                     MlChordModels.deviceProblem(32, big, listOf("arm64-v8a")))
        assertEquals("no chord models for this phone's processor",
                     MlChordModels.deviceProblem(34, big, listOf("armeabi-v7a", "armeabi")))
        assertEquals("chords from audio need 6 GB of memory or more",
                     MlChordModels.deviceProblem(34, MlChordModels.LEAST_MEMORY - 1, listOf("arm64-v8a")))
        // The release carries the libraries for arm64-v8a alone (app/build.gradle.kts): an x86_64 phone has none.
        val release = setOf("arm64-v8a")
        assertEquals("no chord models for this phone's processor",
                     MlChordModels.deviceProblem(34, big, listOf("x86_64"), carried = release))
        assertNull(MlChordModels.deviceProblem(34, big, listOf("arm64-v8a", "armeabi-v7a"), carried = release))
        // An x86_64 phone that translates arm64 installs the APK's x86_64 libraries, its primary ABI's (the first of
        // SUPPORTED_ABIS), as PhoneYouTube.carries says: a release has no chord models there.
        assertEquals("no chord models for this phone's processor",
                     MlChordModels.deviceProblem(34, big, listOf("x86_64", "arm64-v8a"), carried = release))
        // A phone that tells no ABI has none of them.
        assertEquals("no chord models for this phone's processor",
                     MlChordModels.deviceProblem(34, big, emptyList(), carried = release))
        // Android's version first, then the processor, then the memory.
        assertEquals("chords from audio need Android 13 or later",
                     MlChordModels.deviceProblem(30, 1L shl 30, listOf("armeabi-v7a")))
    }

    /** At the phone's start: a song's checkpoints a hearing left a day or more ago (a killed app's) go; a newer one
     * stays, for its Try again to go on from. */
    @Test fun theStartSweepsCheckpointsADayOld() {
        val work = tmp.newFolder("autochords")
        val now = 10L * MlChordModels.DAY_MS
        fun folder(name: String, age: Long): File = File(work, name).apply {
            mkdirs()
            File(this, "chords.json").apply { writeText("{}"); setLastModified(now - age) }
            setLastModified(now - age)
        }
        folder("0123456789abcdef-c1", MlChordModels.DAY_MS + 1)
        folder("fedcba9876543210-c1", MlChordModels.DAY_MS - 60_000)
        val newer = folder("00112233445566aa-c1", 2 * MlChordModels.DAY_MS)
        File(newer, "beats.json").apply { writeText("{}"); setLastModified(now - 1_000) }  // a step written lately
        val turn = tmp.newFile("turn")
        // A hearing under way (its turn held) may be resuming a day-old folder: the sweep takes nothing then.
        MlChordModels.turn(turn)!!.use { assertEquals(emptyList<String>(), MlChordModels.sweepOld(work, now, turn)) }
        assertEquals(3, work.list()!!.size)
        assertEquals(listOf("0123456789abcdef-c1"), MlChordModels.sweepOld(work, now, turn))
        assertEquals(setOf("fedcba9876543210-c1", "00112233445566aa-c1"), work.list()!!.toSet())
        assertEquals(emptyList<String>(), MlChordModels.sweepOld(File(work, "none"), now, turn))
        assertNotNull("the turn given back", MlChordModels.turn(turn)?.also { it.close() })
    }

    /** A song's checkpoints go once its process is gone; kept while it is still ending, or when the wait is
     * interrupted (the flag set again, never swallowed), and never a folder outside the checkpoints' own. */
    @Test fun aSongsCheckpointsGoOnlyOnceItsProcessIsGone() {
        val work = tmp.newFolder("autochords")
        fun folder() = File(work, "0123456789abcdef-c1").apply { mkdirs(); File(this, "heard.json").writeText("{}") }
        assertTrue(MlChordModels.forgotten(folder(), work) {})
        assertFalse(File(work, "0123456789abcdef-c1").exists())
        assertFalse(MlChordModels.forgotten(folder(), work) { throw ChordsUnavailable(MlChordModels.STILL_ENDING) })
        assertTrue(File(work, "0123456789abcdef-c1/heard.json").isFile)
        try {
            assertFalse(MlChordModels.forgotten(folder(), work) { throw InterruptedException() })
            assertTrue("the interrupt kept", Thread.currentThread().isInterrupted)
        } finally {
            Thread.interrupted()
        }
        assertTrue(File(work, "0123456789abcdef-c1/heard.json").isFile)
        val elsewhere = tmp.newFolder("elsewhere")
        assertFalse(MlChordModels.forgotten(elsewhere, work) {})
        assertTrue(elsewhere.isDirectory)
    }

    /** [MlChordModels.forget] runs in the chords stage's `finally`: whatever letting the checkpoints go throws (a
     * bug in the wait, a path that won't resolve) is told and kept there, never thrown over the stage's own result. */
    @Test fun lettingTheCheckpointsGoNeverThrows() {
        val work = tmp.newFolder("autochords")
        val folder = File(work, "0123456789abcdef-c1").apply { mkdirs(); File(this, "heard.json").writeText("{}") }
        val told = mutableListOf<Throwable>()
        assertFalse(MlChordModels.forgotten(folder, work, { told += it }) { throw IllegalStateException("a bug") })
        assertEquals(listOf("a bug"), told.map { it.message })
        assertTrue(File(folder, "heard.json").isFile)
    }

    /** The turn is the app's processes' one: a turn another PROCESS holds (a record lock of its
     * file: the bench's, or the app's jobs while the bench asks) refuses a hearing here in [MlChordModels.BUSY]'s
     * words, and is free once it ends. */
    @Test fun aTurnAnotherProcessHoldsRefusesAHearingHere() {
        val turn = tmp.newFile("turn")
        val java = File(System.getProperty("java.home"), "bin/java").path
        val child = ProcessBuilder(java, "-cp", System.getProperty("java.class.path"), HoldsTheTurn::class.java.name,
                                   turn.path).redirectErrorStream(true).start()
        try {
            assertEquals("held", child.inputStream.bufferedReader().readLine())
            val wake = Wake()
            val e = assertThrows(ChordsUnavailable::class.java) {
                MlChordModels.guarded(charged, { MlChordModels.turn(turn) }, wake) { error("heard") }
            }
            assertEquals(MlChordModels.BUSY, e.message)
            assertEquals(0, wake.holds)
        } finally {
            child.outputStream.close()  // its stdin closed: it lets go and ends
            assertEquals(0, child.waitFor())
        }
        assertEquals("heard", MlChordModels.guarded(charged, { MlChordModels.turn(turn) }, Wake()) { "heard" })
    }
}

/** The child process of [HearingGuardTest.aTurnAnotherProcessHoldsRefusesAHearingHere]: the turn of its argument's
 * file taken, "held" said, then held until its stdin ends. */
object HoldsTheTurn {
    @JvmStatic fun main(args: Array<String>) {
        val held = MlChordModels.turn(File(args[0])) ?: error("not free")
        println("held")
        System.out.flush()
        while (System.`in`.read() >= 0) Unit
        held.close()
    }
}
