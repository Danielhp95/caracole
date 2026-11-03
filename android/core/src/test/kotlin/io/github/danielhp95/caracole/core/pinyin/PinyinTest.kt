package io.github.danielhp95.caracole.core.pinyin

import io.github.danielhp95.caracole.core.pinyin.Pinyin.Errors
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Record
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue
import kotlin.test.fail

/** Pinyin reads what pypinyin 0.55.0 reads, record for record of tests/test_conformance_pinyin.py's vectors. */
class PinyinTest {
    private fun strings(element: kotlinx.serialization.json.JsonElement?): List<String> =
        element!!.jsonArray.map { it.jsonPrimitive.content }

    private fun text(record: Record): String = record.args.single().jsonPrimitive.content

    /** Fails naming the first few records that disagree, and how many do. */
    private fun agree(name: String, records: List<Record>, wrong: (Record) -> String?) {
        val found = records.mapNotNull(wrong)
        if (found.isNotEmpty()) fail("${found.size} of ${records.size} records of $name disagree:\n" + found.take(8).joinToString("\n"))
    }

    @Test fun theVectorsAreOfThePypinyinThisPorts() {
        for (name in listOf("pinyin/lazy.jsonl", "pinyin/heteronyms.jsonl")) {
            val versions = Corpus.header(name).getValue("versions").jsonObject
            // Pinyin.kt ports pypinyin 0.55.0's converter, core and seg: read the new version's before changing this.
            assertEquals(JsonPrimitive("0.55.0"), versions["pypinyin"], name)
        }
    }

    @Test fun everyLazyRecordReadsAsPypinyinReadsIt() {
        val records = Corpus.records("pinyin/lazy.jsonl")
        assertTrue(records.size > 8000, "${records.size} records")
        agree("pinyin/lazy.jsonl", records) { record ->
            assertEquals("pypinyin.lazy_pinyin", record.fn)
            val errors = when (val e = record.kw.getValue("errors").jsonPrimitive.content) {
                "default" -> Errors.DEFAULT
                "ignore" -> Errors.IGNORE
                else -> fail("errors=$e")
            }
            val got = Pinyin.lazyPinyin(text(record), errors)
            val want = strings(record.out)
            if (got == want) null else "lazy_pinyin(${JsonPrimitive(text(record))}, $errors): $got, pypinyin $want"
        }
    }

    @Test fun everyCharacterOfTheHeteronymRecordsReadsAsPypinyinReadsIt() {
        val records = Corpus.records("pinyin/heteronyms.jsonl")
        var chars = 0
        agree("pinyin/heteronyms.jsonl", records) { record ->
            assertEquals("test_conformance_pinyin.heteronyms", record.fn)
            val text = text(record)
            val want = record.out!!.jsonArray.map { strings(it) }
            val got = ArrayList<List<String>>()
            var i = 0
            while (i < text.length) {
                val cp = text.codePointAt(i)
                got.add(Pinyin.heteronyms(cp))
                i += Character.charCount(cp)
            }
            chars += got.size
            if (got == want) null
            else got.indices.first { got[it] != want.getOrNull(it) }.let { at ->
                "heteronyms(U+${Integer.toHexString(text.codePointAt(text.offsetByCodePoints(0, at)))}): " +
                    "${got[at]}, pypinyin ${want.getOrNull(at)}"
            }
        }
        assertTrue(chars > 41_000, "$chars characters")
    }

    @Test fun whatCaracoleReadsInPinyin() {
        assertEquals(listOf("lv", "se"), Pinyin.lazyPinyin("绿色"))
        assertEquals(listOf("chao"), Pinyin.lazyPinyin("朝"))
        assertEquals(listOf("zhao", "yang"), Pinyin.lazyPinyin("朝阳"))  // the phrase's reading, not 朝's first
        assertEquals(listOf("chong", "qing"), Pinyin.lazyPinyin("重庆"))
        assertEquals(listOf("long", "zhong", "qing", "zhu"), Pinyin.lazyPinyin("隆重庆祝"))
        // 隆重庆 begins 隆重庆祝 and none of its prefixes is a phrase: mmseg reads each character alone, and stops.
        assertEquals(listOf("long", "zhong", "qing"), Pinyin.lazyPinyin("隆重庆"))
        assertEquals(listOf("song", "dong", "ye"), Pinyin.lazyPinyin("宋冬野"))
        assertEquals(listOf("Song ", "dong", "ye", " (", "an", "he", "qiao", ")"), Pinyin.lazyPinyin("Song 冬野 (安和桥)"))
        assertEquals(listOf("dong", "ye", "an", "he", "qiao"), Pinyin.lazyPinyin("Song 冬野 (安和桥)", Errors.IGNORE))
        assertEquals(emptyList(), Pinyin.lazyPinyin(""))
        assertEquals(emptyList(), Pinyin.lazyPinyin("abc", Errors.IGNORE))
        // A Han character with no reading is itself, or nothing; a supplementary one is one code point.
        assertEquals(listOf("\u3402"), Pinyin.lazyPinyin("\u3402"))
        assertEquals(emptyList(), Pinyin.lazyPinyin("\u3402", Errors.IGNORE))
        assertEquals(listOf("he"), Pinyin.lazyPinyin("\uD840\uDC00"))
        assertEquals(listOf("he", "\uD840\uDC02"), Pinyin.lazyPinyin("\uD840\uDC00\uD840\uDC02"))
        assertEquals(listOf("he"), Pinyin.lazyPinyin("\uD840\uDC00\uD840\uDC02", Errors.IGNORE))
    }

    @Test fun aCharactersReadingsAreEachOfItsReadingsOnce() {
        assertEquals(listOf("zhong"), Pinyin.heteronyms('中'.code))  // zhōng and zhòng
        assertEquals(listOf("xing", "hang", "heng"), Pinyin.heteronyms('行'.code))
        assertEquals(listOf("ling", "yuan", "xing"), Pinyin.heteronyms(0x3007))
        assertEquals(listOf("a"), Pinyin.heteronyms('a'.code))
        assertEquals(listOf("\u3402"), Pinyin.heteronyms(0x3402))
        assertFailsWith<IllegalArgumentException> { Pinyin.heteronyms(0x110000) }
    }
}
