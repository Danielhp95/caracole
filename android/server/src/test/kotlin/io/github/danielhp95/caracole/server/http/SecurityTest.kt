package io.github.danielhp95.caracole.server.http

import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Record
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlin.test.fail

/** web/security.py on the phone: every answer of vectors/web/security.jsonl, and the launch's secret cookie. */
class SecurityTest {
    private val records = Corpus.records("web/security.jsonl")

    private fun text(e: JsonElement): String? = if (e is JsonNull) null else e.jsonPrimitive.content

    private fun headers(e: JsonElement): Map<String, String> = e.jsonObject.mapValues { it.value.jsonPrimitive.content }

    private fun answered(r: Record): JsonElement = when (r.fn.substringAfterLast('.')) {
        "host_name" -> Security.hostName(text(r.args[0]))?.let(::JsonPrimitive) ?: JsonNull
        "answers_to" -> JsonPrimitive(Security.answersTo(text(r.args[0]),
                                                         r.args[1].jsonArray.map { it.jsonPrimitive.content }.toSet()))
        "cross_origin_ok" -> JsonPrimitive(Security.crossOriginOk(r.args[0].jsonPrimitive.content, headers(r.args[1]),
                                                                  text(r.args[2])))
        "own_page_read" -> JsonPrimitive(Security.ownPageRead(headers(r.args[0])))
        "same_token" -> JsonPrimitive(Security.sameToken(text(r.args[0]), r.args[1].jsonPrimitive.content))
        else -> fail("no Kotlin for ${r.fn}")
    }

    @Test fun everySecurityAnswerIsPythons() {
        val calls = records.filter { it.fn.startsWith("caracole.web.security.") }
        assertTrue(calls.size > 1000, "the matrix is there: ${calls.size}")
        val wrong = calls.filter { answered(it) != it.out }
        assertEquals(emptyList(), wrong.take(20).map { "${it.fn}${it.args} → ${answered(it)}, Python ${it.out}" },
                     "${wrong.size} of ${calls.size} differ")
    }

    private fun ranges(fn: String): List<IntRange> = records.single { it.fn == fn }.out!!.jsonArray.map {
        val (first, last) = it.jsonArray.map { n -> n.jsonPrimitive.int }
        first..last
    }

    @Test fun theDigitsAndTheWhitespaceArePythonsStrMethods() {
        val digits = ranges("str.isdigit")
        val spaces = ranges("str.isspace")
        for (cp in 0..0x10FFFF) {
            assertEquals(digits.any { cp in it }, PyText.isDigit(cp), "isdigit U+%04X".format(cp))
            assertEquals(spaces.any { cp in it }, PyText.isSpace(cp), "isspace U+%04X".format(cp))
        }
    }

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
