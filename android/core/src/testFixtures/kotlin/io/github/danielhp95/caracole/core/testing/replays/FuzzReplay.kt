package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.fuzz.Fuzz
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.CanonicalError
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.pinyin.Pinyin
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Record
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import java.security.MessageDigest
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** The fuzz: rapidfuzz's ratios, alignments and extracts, to the double (vectors/fuzz/), every record answered by :core as Python answered it: the JVM's
 * tests' record loops, run on the device by CorpusOnDeviceTest. */
object FuzzReplay : AreaReplay {
    override val area = "fuzz"

    override fun replay(misses: Misses) {
        everyFuzzRecordIsRapidfuzzsToTheDouble()
    }

    private fun everyFuzzRecordIsRapidfuzzsToTheDouble() {
        val misses = Misses("fuzz/")
        fun arg(r: Record, i: Int) = text(r.args[i])
        for (r in Corpus.records("fuzz/ratio.jsonl")) {
            val got = Fuzz.ratio(arg(r, 0), arg(r, 1))
            misses.check(got == r.out!!.jsonPrimitive.double) { "ratio ${r.args}: rapidfuzz ${r.out}, Fuzz $got" }
        }
        for (r in Corpus.records("fuzz/token_sort.jsonl")) {
            val got = Fuzz.tokenSortRatio(arg(r, 0), arg(r, 1))
            misses.check(got == r.out!!.jsonPrimitive.double) { "token_sort ${r.args}: rapidfuzz ${r.out}, Fuzz $got" }
        }
        for (r in Corpus.records("fuzz/partial_alignment.jsonl")) {
            val o = r.out!!.jsonObject
            val want = Fuzz.Alignment(o["score"]!!.jsonPrimitive.double, o["src_start"]!!.jsonPrimitive.int,
                o["src_end"]!!.jsonPrimitive.int, o["dest_start"]!!.jsonPrimitive.int, o["dest_end"]!!.jsonPrimitive.int)
            val got = Fuzz.partialRatioAlignment(arg(r, 0), arg(r, 1))
            misses.check(got == want) { "partial_alignment ${r.args}: rapidfuzz $want, Fuzz $got" }
        }
        val extracts = Corpus.records("fuzz/extract.jsonl")
        assertTrue(extracts.size > 800)
        for (r in extracts) {
            val want = r.out!!.jsonArray.map { row ->
                val (choice, score, index) = row.jsonArray
                Fuzz.Extracted(choice.jsonPrimitive.content, score.jsonPrimitive.double, index.jsonPrimitive.int)
            }
            val limit = r.kw["limit"].takeUnless { it == null || it is JsonNull }?.jsonPrimitive?.int
            val got = Fuzz.extract(arg(r, 0), r.args[1].jsonArray.map(::text), r.kw["score_cutoff"]!!.jsonPrimitive.double, limit)
            misses.check(got == want) { "extract ${r.args} ${r.kw}: rapidfuzz $want, Fuzz $got" }
        }
        assertTrue("records checked: ${misses.checked}", misses.checked > 18_000)
        misses.assertNone()
    }
}
