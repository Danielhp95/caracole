package io.github.danielhp95.caracole.core.web

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assume.assumeTrue
import java.text.Normalizer
import org.junit.Test
import kotlin.test.assertEquals

/** web/files.py's kinds of file and download_names.py's names: vectors/web/downloads.jsonl. */
class DownloadNamesTest {
    private val records = Corpus.records("web/downloads.jsonl")

    /** Whether lanes py-unicode and keys have landed: a download's name is read with their Unicode and clean_title. */
    private fun landed(): Boolean = try {
        PyUnicode.nfc("a")
        Normalize.cleanTitle("a")
        true
    } catch (e: NotImplementedError) {
        false
    }

    private fun misnamed(name: (String, String, String) -> String, disposition: (String) -> String): List<String> =
        records.filter { it.fn.startsWith("caracole.download_names.") }.mapNotNull { r ->
            val args = r.args.map { it.jsonPrimitive.content }
            val got = when (r.fn.substringAfterLast('.')) {
                "download_name" -> name(args[0], args[1], args[2])
                else -> disposition(args[0])
            }
            if (got == r.out!!.jsonPrimitive.content) null else "${r.fn}$args → $got, Python ${r.out}"
        }

    @Test fun everyDownloadIsNamedAsDownloadNamesPyNamesIt() {
        assumeTrue("waits for lanes py-unicode and keys", landed())
        assertEquals(emptyList(), misnamed(DownloadNames::downloadName, DownloadNames::contentDisposition).take(10))
    }

    /** The JDK's Unicode, which agrees with Python's on every character the vectors name (none newer than Unicode 13,
     * no mark with a combining class of 0): the rules alone, before core.py lands. */
    private object JdkText : NameText {
        override fun nfc(s: String): String = Normalizer.normalize(s, Normalizer.Form.NFC)
        override fun nfkd(s: String): String = Normalizer.normalize(s, Normalizer.Form.NFKD)
        override fun combining(cp: Int): Int = if (Character.getType(cp) == Character.NON_SPACING_MARK.toInt()) 230 else 0
        override fun isSpace(cp: Int): Boolean = cp in listOf(0x9, 0xA, 0xB, 0xC, 0xD, 0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x85, 0xA0) ||
            Character.getType(cp) in listOf(Character.SPACE_SEPARATOR, Character.LINE_SEPARATOR, Character.PARAGRAPH_SEPARATOR).map { it.toInt() }
        override fun isDecimal(cp: Int): Boolean = Character.getType(cp) == Character.DECIMAL_DIGIT_NUMBER.toInt()
        override fun lower(s: String): String = s.lowercase()
        override fun category(cp: Int): String = when (Character.getType(cp).toByte()) {
            Character.UPPERCASE_LETTER -> "Lu"; Character.LOWERCASE_LETTER -> "Ll"; Character.TITLECASE_LETTER -> "Lt"
            Character.MODIFIER_LETTER -> "Lm"; Character.OTHER_LETTER -> "Lo"; Character.NON_SPACING_MARK -> "Mn"
            Character.ENCLOSING_MARK -> "Me"; Character.COMBINING_SPACING_MARK -> "Mc"; Character.DECIMAL_DIGIT_NUMBER -> "Nd"
            Character.LETTER_NUMBER -> "Nl"; Character.OTHER_NUMBER -> "No"; Character.SPACE_SEPARATOR -> "Zs"
            Character.LINE_SEPARATOR -> "Zl"; Character.PARAGRAPH_SEPARATOR -> "Zp"; Character.CONTROL -> "Cc"
            Character.FORMAT -> "Cf"; Character.PRIVATE_USE -> "Co"; Character.SURROGATE -> "Cs"
            Character.UNASSIGNED -> "Cn"; Character.DASH_PUNCTUATION -> "Pd"; Character.START_PUNCTUATION -> "Ps"
            Character.END_PUNCTUATION -> "Pe"; Character.CONNECTOR_PUNCTUATION -> "Pc"; Character.OTHER_PUNCTUATION -> "Po"
            Character.MATH_SYMBOL -> "Sm"; Character.CURRENCY_SYMBOL -> "Sc"; Character.MODIFIER_SYMBOL -> "Sk"
            Character.OTHER_SYMBOL -> "So"; Character.INITIAL_QUOTE_PUNCTUATION -> "Pi"
            Character.FINAL_QUOTE_PUNCTUATION -> "Pf"
            else -> error("no category for U+%04X".format(cp))
        }
    }

    @Test fun theRulesAreDownloadNamesPysOnTheJdksUnicodeToo() {
        val namer = DownloadNamer(JdkText)
        assertEquals(emptyList(), misnamed(namer::downloadName, namer::contentDisposition).take(10))
    }
}
