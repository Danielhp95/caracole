package io.github.danielhp95.caracole

import kotlinx.coroutines.CancellationException
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertTrue

/**
 * What a screen other than the library's (Settings, Backups) does when the phone's caracole can't start: it says why,
 * as the library screen does ("Couldn't start · database or disk is full"), never a crash: an Error caught too (the
 * bundled SQLite's native library that won't load), a cancellation never (the screen left: its work stops).
 */
class GuardedTest {
    @Test
    fun anythingTheStartThrowsIsAFailureToSay() {
        val full = guarded<Int> { throw IllegalStateException("database or disk is full") }
        assertEquals("database or disk is full", full.exceptionOrNull()?.message)
        assertIs<UnsatisfiedLinkError>(guarded<Int> { throw UnsatisfiedLinkError("no sqliteJni") }.exceptionOrNull())
        assertIs<OutOfMemoryError>(guarded<Int> { throw OutOfMemoryError() }.exceptionOrNull())
        assertEquals(3, guarded { 3 }.getOrNull())
    }

    @Test
    fun aCancellationGoesOn() {
        assertFailsWith<CancellationException> { guarded<Int> { throw CancellationException("the screen left") } }
    }

    @Test
    fun theFailureIsSaidInItsOwnWordsElseByItsName() {
        assertEquals("database or disk is full", why(IllegalStateException("database or disk is full")))
        assertEquals("UnsatisfiedLinkError", why(UnsatisfiedLinkError()))
        assertTrue(why(RuntimeException("")).isNotEmpty())
    }
}
