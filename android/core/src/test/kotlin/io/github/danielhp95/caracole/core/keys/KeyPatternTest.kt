package io.github.danielhp95.caracole.core.keys

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** How normalize.py's patterns are rewritten for java.util.regex ([KeyPattern.translate]), with a stand-in for
 * sre's case classes (ASCII letters by their capital, ı and ſ with i and s) so it needs no Unicode table. */
class KeyPatternTest {
    private val key: (Int) -> Int = { cp ->
        when (cp) {
            in 'a'.code..'z'.code -> cp - 32
            0x131 -> 'I'.code
            0x17F -> 'S'.code
            0xFA -> 0xDA
            else -> cp
        }
    }

    private fun java(pattern: String, ignoreCase: Boolean = false) = KeyPattern.translate(pattern, ignoreCase, key).pattern

    @Test fun dotAndDollarMeanWhatTheyMeanInPython() {
        assertEquals("a[^\\n]b(?=\\n?\\z)", java("a.b$"))
        assertEquals("[\\.\\$]", java("[.$]"))  // escaped, as both read them
        assertEquals("\\x0B\\n\\t", java("\\v\\n\\t"))
    }

    @Test fun classEscapesAreLeftToPyRegex() {
        assertEquals("[\\W\\_]+\\s\\d{4}\\b", java("[\\W_]+\\s\\d{4}\\b"))
        assertFailsWith<IllegalArgumentException> { java("[\\b]") }
    }

    @Test fun whatJavaReadsOtherwiseIsWrittenAsPythonReadsIt() {
        assertEquals("[\\[\\&\\&\\]]", java("[[&&\\]]"))
        assertEquals("[\\]a]", java("[]a]"))
        assertEquals("[\\]-a]", java("[]-a]"))
        assertEquals("[\\-a\\-]", java("[-a-]"))
        assertEquals("[^\\-–]", java("[^-–]"))
        assertEquals("a{0,3}b\\{c\\}", java("a{,3}b{c}"))
        assertEquals("a{2}b{2,}", java("a{2}b{2,}"))
        assertEquals("[\\x00-\\x1f]", java("[\\x00-\\x1f]"))
    }

    @Test fun ignoreCaseWritesEachLiteralAsItsClassesRepresentative() {
        val t = KeyPattern.translate("(?:ac[uú]stic[oa])\\s+(?=x)", true, key)
        assertEquals("(?:AC[UÚ]STIC[OA])\\s+(?=X)", t.pattern)
        assertTrue(setOf('A'.code, 'C'.code, 'U'.code, 0xDA, 'X'.code).all { it in t.keys })
    }

    @Test fun whatTheRewriteDoesntCarryIsRefused() {
        for (pattern in listOf("(?i)a", "(?P<x>a)", "\\N{DASH}", "\\u00e9", "(?#c)", "[a", "a\\")) {
            assertFailsWith<IllegalArgumentException>(pattern) { java(pattern) }
        }
        assertFailsWith<IllegalArgumentException> { KeyPattern.translate("[a-z]", true, key) }
        assertFailsWith<IllegalArgumentException> { KeyPattern.translate("(a)\\1", true, key) }
    }

    @Test fun everyPatternOfNormalizeRewritesAndCompilesAsJava() {
        val patterns = Json.parseToJsonElement(KeyTables.text("tables.json")).jsonObject.getValue("patterns").jsonObject
        assertEquals(setOf("_DASH_SUFFIX", "_PAREN_FEAT", "_PAREN_SUFFIX", "_ACOUSTIC_WORD", "_LIVE_WORD", "_PART_BREAK",
            "_FEATURING", "_BRACKETED", "_MORA", "_RESERVED"), patterns.keys)
        for ((name, spec) in patterns) {
            val o = spec.jsonObject
            val t = KeyPattern.translate(o.getValue("pattern").jsonPrimitive.content, o.getValue("ignorecase").jsonPrimitive.boolean, key)
            // With \s \d \w \b as the JDK's, only for the syntax: PyRegex gives them Python's meaning.
            java.util.regex.Pattern.compile(t.pattern)
            assertTrue(t.pattern.isNotEmpty(), name)
        }
    }
}
