package io.github.danielhp95.caracole.server.http

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.testing.replays.WebReplay
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** web/security.py on the phone: every answer of vectors/web/security.jsonl, and the launch's secret cookie. */
class SecurityTest {
    private val records = Corpus.records("web/security.jsonl")

    /** Every answer of the vector, and `str.isdigit` and `str.isspace` for every code point: WebReplay.security's,
     * which the device runs too. */
    @Test fun everySecurityAnswerIsPythons() =
        Misses("web/security.jsonl").also { WebReplay.security(it) }.assertNone()

    private fun cookie(value: String) = mapOf("cookie" to value)

    @Test fun theSecretIsTheLaunchCookieExactly() {
        val secret = "a".repeat(64)
        assertTrue(Security.hasSecret(cookie("caracole-launch=$secret"), secret))
        assertTrue(Security.hasSecret(cookie("other=1; caracole-launch=$secret; more=2"), secret))
        assertTrue(Security.hasSecret(cookie("caracole-launch=old;caracole-launch=$secret"), secret))
        assertTrue(Security.hasSecret(cookie("  caracole-launch=$secret  "), secret))
        assertFalse(Security.hasSecret(emptyMap(), secret))
        assertFalse(Security.hasSecret(cookie(""), secret))
        assertFalse(Security.hasSecret(cookie("caracole-launch="), secret))
        assertFalse(Security.hasSecret(cookie("caracole-launch=${secret}x"), secret))
        assertFalse(Security.hasSecret(cookie("caracole-launch=${secret.dropLast(1)}"), secret))
        assertFalse(Security.hasSecret(cookie("Caracole-Launch=$secret"), secret))
        assertFalse(Security.hasSecret(cookie("xcaracole-launch=$secret"), secret))
        assertFalse(Security.hasSecret(cookie("caracole-launch=\"$secret\""), secret))
        assertFalse(Security.hasSecret(mapOf("x-caracole-launch" to secret), secret))
        assertFalse(Security.hasSecret(cookie("caracole-launch="), ""), "no secret is never one")
        assertEquals("caracole-launch", Security.SECRET_COOKIE)
    }

    @Test fun aTokenIsComparedWholeAndNothingNeverMatches() {
        assertTrue(Security.sameToken("tok", "tok"))
        assertFalse(Security.sameToken("to", "tok"))
        assertFalse(Security.sameToken(null, ""))
        assertFalse(Security.sameToken("", ""))
    }

    @Test fun theVectorsSayWhatTheyAre() {
        val header = Corpus.header("web/security.jsonl")
        assertEquals("web/security", header["corpus"]!!.jsonPrimitive.content)
        assertTrue(header["header"]!!.jsonPrimitive.boolean)
        assertTrue((header["versions"] as JsonObject).isNotEmpty())
        assertTrue(records.none { it.err != null }, "security.py raises for none of them")
    }
}
