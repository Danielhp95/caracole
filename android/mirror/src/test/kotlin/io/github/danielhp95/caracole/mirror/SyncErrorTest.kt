package io.github.danielhp95.caracole.mirror

import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertSame

/** How the app says what went wrong: every failure as a [SyncError], one sentence. */
class SyncErrorTest {
    @Test
    fun `a failure the app didn't expect is a sync error too, said with what it was`() {
        val known = SyncError.NoAddress()
        assertSame(known, SyncError.of(known))

        // What the JVM's HttpURLConnection throws for a port past 65535: no IOException, so no NoAnswer.
        val odd = RuntimeException(IllegalArgumentException("port out of range:99999"))
        val error = assertIs<SyncError.Unexpected>(SyncError.of(odd))
        assertSame(odd, error.cause)
        assertEquals("Something went wrong that the app didn't expect " +
            "(RuntimeException: java.lang.IllegalArgumentException: port out of range:99999).", error.message)
        assertEquals("Something went wrong that the app didn't expect (IllegalStateException).",
            SyncError.of(IllegalStateException()).message)
    }
}
