package io.github.danielhp95.caracole.core.keys

import io.github.danielhp95.caracole.core.keys.KeyVectors.Companion.str
import io.github.danielhp95.caracole.core.testing.Corpus
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.fail

/** normalize.fold, of every code point whose fold differs from itself and of random strings (vectors/keys/fold.jsonl). */
class FoldTest {
    @Test fun foldIsPythonsForEveryCodePointItChangesAndForRandomStrings() {
        val vectors = KeyVectors("keys/fold.jsonl")
        for (record in Corpus.records("keys/fold.jsonl")) {
            when (record.fn) {
                "test_conformance_keys.fold_each" -> {
                    val text = record.args[0].str()
                    val each = codePointStrings(text)
                    vectors.expect(record) { each.map { Normalize.fold(it) } }
                }
                "caracole.normalize.fold" -> vectors.expect(record) { Normalize.fold(record.args[0].str()) }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        vectors.assertNoMiss()
    }

    @Test fun asciiFoldsByItsLetterAlone() {
        assertEquals("ac/dc i'll the-rifles", Normalize.fold("AC/DC I'll The-Rifles"))
    }

    private fun codePointStrings(s: String): List<String> {
        val out = ArrayList<String>()
        var i = 0
        while (i < s.length) {
            val n = Character.charCount(s.codePointAt(i))
            out += s.substring(i, i + n)
            i += n
        }
        return out
    }
}
