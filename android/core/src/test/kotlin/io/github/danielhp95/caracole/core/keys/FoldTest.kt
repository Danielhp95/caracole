package io.github.danielhp95.caracole.core.keys

import io.github.danielhp95.caracole.core.keys.KeyVectors.Companion.str
import io.github.danielhp95.caracole.core.testing.Corpus
import org.junit.Test
import java.security.MessageDigest
import kotlin.test.assertEquals
import kotlin.test.fail

/** normalize.fold, of every code point whose fold differs from itself, of every code point by a digest, and of random
 * strings (vectors/keys/fold.jsonl). */
class FoldTest {
    @Test fun foldIsPythonsForEveryCodePointItChangesAndForRandomStrings() {
        val vectors = KeyVectors("keys/fold.jsonl")
        var digests = 0
        for (record in Corpus.records("keys/fold.jsonl")) {
            when (record.fn) {
                "test_conformance_keys.fold_each" -> {
                    val text = record.args[0].str()
                    val each = codePointStrings(text)
                    vectors.expect(record) { each.map { Normalize.fold(it) } }
                }
                "test_conformance_keys.fold_digest" -> {
                    digests++
                    vectors.expect(record) { foldDigest() }
                }
                "caracole.normalize.fold" -> vectors.expect(record) { Normalize.fold(record.args[0].str()) }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        vectors.assertNoMiss()
        assertEquals(1, digests, "fold.jsonl's digest records")
    }

    @Test fun asciiFoldsByItsLetterAlone() {
        assertEquals("ac/dc i'll the-rifles", Normalize.fold("AC/DC I'll The-Rifles"))
    }

    /** test_conformance_keys.fold_digest: the SHA-256 of every code point's fold (the surrogates left out, in code
     * point order) joined by NUL, in UTF-8, so a fold that changes a code point Python leaves alone is caught. */
    private fun foldDigest(): String {
        val sha = MessageDigest.getInstance("SHA-256")
        val nul = byteArrayOf(0)
        for (cp in 0 until 0x110000) {
            if (cp in 0xD800..0xDFFF) continue
            if (cp != 0) sha.update(nul)
            sha.update(Normalize.fold(String(Character.toChars(cp))).toByteArray(Charsets.UTF_8))
        }
        val hex = "0123456789abcdef"
        return sha.digest().joinToString("") { b -> "${hex[b.toInt() shr 4 and 15]}${hex[b.toInt() and 15]}" }
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
