package io.github.danielhp95.caracole

import kotlinx.coroutines.CancellationException
import org.junit.After
import org.junit.Before
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertTrue

/**
 * What a screen other than the library's (Settings, Backups) does when the phone's caracole, or a read of it, fails:
 * it logs it and says what failed, never a crash: an Error caught too (the bundled SQLite's native library that won't
 * load), but never the VM's own (out of memory, a stack overflow), nor a cancellation (the screen left: its work
 * stops).
 */
class GuardedTest {
    private val logged = mutableListOf<Pair<String, Throwable>>()
    private val was = Guards.log

    @Before fun capture() {
        Guards.log = { what, e -> logged += what to e }
    }

    @After fun restore() {
        Guards.log = was
    }

    @Test
    fun anythingABlockThrowsIsAFailureToSayAndIsLogged() {
        val full = IllegalStateException("database or disk is full")
        assertEquals(full, guarded<Int>("the phone's caracole didn't start") { throw full }.exceptionOrNull())
        assertIs<UnsatisfiedLinkError>(guarded<Int>("the backups couldn't be listed") {
            throw UnsatisfiedLinkError("no sqliteJni")
        }.exceptionOrNull())
        assertEquals(listOf("the phone's caracole didn't start", "the backups couldn't be listed"), logged.map { it.first })
        assertEquals(full, logged.first().second, "the throwable logged with what failed")
        assertEquals(3, guarded("nothing") { 3 }.getOrNull())
        assertEquals(2, logged.size, "a block that succeeds logs nothing")
    }

    @Test
    fun theVirtualMachinesOwnErrorsAndACancellationGoOn() {
        assertFailsWith<OutOfMemoryError> { guarded<Int>("x") { throw OutOfMemoryError() } }
        assertFailsWith<StackOverflowError> { guarded<Int>("x") { throw StackOverflowError() } }
        assertFailsWith<CancellationException> { guarded<Int>("x") { throw CancellationException("the screen left") } }
        assertEquals(emptyList(), logged, "none of them logged here: they are someone else's")
    }

    @Test
    fun theFailureIsSaidInItsOwnWordsElseByItsName() {
        assertEquals("database or disk is full", why(IllegalStateException("database or disk is full")))
        assertEquals("UnsatisfiedLinkError", why(UnsatisfiedLinkError()))
        assertTrue(why(RuntimeException("")).isNotEmpty())
    }
}
