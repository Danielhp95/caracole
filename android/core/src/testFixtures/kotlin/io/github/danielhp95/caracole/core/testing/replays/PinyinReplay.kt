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

/** The pinyin: lazy_pinyin in Style.NORMAL and TONE and each character's heteronyms (vectors/pinyin/), every record
 * answered by :core as Python answered it: the JVM's tests' record loops, run on the device by CorpusOnDeviceTest. */
object PinyinReplay : AreaReplay {
    override val area = "pinyin"

    override fun replay(misses: Misses) {
        everyPinyinRecordReadsAsPypinyinReadsIt()
    }

    private fun everyPinyinRecordReadsAsPypinyinReadsIt() {
        val lazy = Misses("pinyin/lazy.jsonl")
        val records = Corpus.records("pinyin/lazy.jsonl")
        assertTrue(records.size > 8000)
        for (record in records) {
            val errors = when (val e = record.kw.getValue("errors").jsonPrimitive.content) {
                "default" -> Pinyin.Errors.DEFAULT
                "ignore" -> Pinyin.Errors.IGNORE
                else -> throw AssertionError("errors=$e")
            }
            val s = text(record.args.single())
            val got = Pinyin.lazyPinyin(s, errors)
            val want = record.out!!.jsonArray.map(::text)
            lazy.check(got == want) { "lazy_pinyin(${JsonPrimitive(s)}, $errors): $got, pypinyin $want" }
        }
        lazy.assertNone()

        val tone = Misses("pinyin/tone.jsonl")
        val toneRecords = Corpus.records("pinyin/tone.jsonl")
        assertTrue(toneRecords.size > 2000)
        for (record in toneRecords) {
            val s = text(record.args[0])
            val errors = when (val e = text(record.args[1])) {
                "default" -> Pinyin.Errors.DEFAULT
                "empty_each" -> Pinyin.Errors.EMPTY_EACH
                else -> throw AssertionError("errors=$e")
            }
            val got = Pinyin.lazyPinyin(s, errors, Pinyin.Style.TONE)
            val want = record.out!!.jsonArray.map(::text)
            tone.check(got == want) { "lazy_tone(${JsonPrimitive(s)}, $errors): $got, pypinyin $want" }
        }
        tone.assertNone()

        val heteronyms = Misses("pinyin/heteronyms.jsonl")
        var chars = 0
        for (record in Corpus.records("pinyin/heteronyms.jsonl")) {
            val s = text(record.args.single())
            val want = record.out!!.jsonArray.map { cp -> cp.jsonArray.map(::text) }
            val cps = Py.codePoints(s)
            chars += cps.size
            for ((i, cp) in cps.withIndex()) {
                val got = Pinyin.heteronyms(cp)
                heteronyms.check(got == want.getOrNull(i)) { "heteronyms(U+%04X): %s, pypinyin %s".format(cp, got, want.getOrNull(i)) }
            }
        }
        assertTrue("$chars characters", chars > 41_000)
        heteronyms.assertNone()
    }
}
