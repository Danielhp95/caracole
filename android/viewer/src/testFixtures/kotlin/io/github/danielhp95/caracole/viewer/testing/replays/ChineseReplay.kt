package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.viewer.chinese.Hanzi
import io.github.danielhp95.caracole.viewer.chinese.OpenCC
import io.github.danielhp95.caracole.viewer.chinese.ViewerPinyin
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertTrue
import org.junit.Assert.fail

/**
 * OpenCC (vectors/viewer/opencc.jsonl), hanzi.py (hanzi.jsonl) and the pages' pinyin (pinyin_page.jsonl), every
 * record answered by :viewer's viewer.chinese as Python answered it: OpenCCTest's, HanziTest's and ViewerPinyinTest's
 * record loops, run on the device by CorpusOnDeviceTest. tests/test_conformance_viewer_chinese.py's docstring says
 * each record's shape.
 */
object ChineseReplay : AreaReplay {
    override val area = "chinese"

    private const val HELPER = "test_conformance_viewer_chinese."
    private val CONFIGS = OpenCC.Config.entries

    override fun replay(misses: Misses) {
        everyOpenCCRecordIsOpenCCs()
        everyHanziRecordIsHanziPys()
        everyPinyinPageRecordIsPinyinPys()
    }

    fun everyOpenCCRecordIsOpenCCs() {
        val misses = Misses("viewer/opencc.jsonl")
        val counts = HashMap<String, Int>()
        for (record in Corpus.records("viewer/opencc.jsonl")) {
            counts.merge(record.fn, 1, Int::plus)
            when (record.fn) {
                HELPER + "convert" -> {
                    val config = config(record.args[0].jsonPrimitive.content)
                    val text = record.args[1].jsonPrimitive.content
                    val got = OpenCC.convert(config, text)
                    val want = record.out!!.jsonPrimitive.content
                    misses.check(got == want) {
                        "convert($config, ${quoted(text)}): ${quoted(got)}, OpenCC's ${quoted(want)}"
                    }
                }
                HELPER + "converted" -> {
                    val text = record.args[0].jsonPrimitive.content
                    val got = byConfig { OpenCC.convert(it, text) }
                    misses.check(got == record.out) { "converted(${quoted(text)}): $got, OpenCC's ${record.out}" }
                }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertTrue("records of both kinds: $counts", counts.size == 2 && counts.getValue(HELPER + "convert") > 300)
        misses.assertNone()
    }

    fun everyHanziRecordIsHanziPys() {
        val misses = Misses("viewer/hanzi.jsonl")
        val counts = HashMap<String, Int>()
        for (record in Corpus.records("viewer/hanzi.jsonl")) {
            counts.merge(record.fn, 1, Int::plus)
            when (record.fn) {
                HELPER + "page_converted" -> {
                    val text = record.args[0].jsonPrimitive.content
                    val got = byConfig { Hanzi.converted(it, text) }
                    misses.check(got == record.out) { "page_converted(${quoted(text)}): $got, Python's ${record.out}" }
                }
                HELPER + "sheet_hanzi" -> {
                    val texts = strings(record.args[0])
                    val names = strings(record.args[1])
                    val got = JsonObject(mapOf(
                        "scripts" to items(Hanzi.scripts(texts)),
                        "traditional" to JsonPrimitive(Hanzi.writtenInTraditional(texts)),
                        "names" to items(Hanzi.names(names)),
                    ))
                    misses.check(got == record.out) { "sheet_hanzi($texts, $names): $got, Python's ${record.out}" }
                }
                else -> fail("an unknown record: ${record.fn}")
            }
        }
        assertTrue("records of both kinds: $counts", counts.size == 2 && counts.getValue(HELPER + "sheet_hanzi") > 200)
        misses.assertNone()
    }

    fun everyPinyinPageRecordIsPinyinPys() {
        val misses = Misses("viewer/pinyin_page.jsonl")
        var count = 0
        for (record in Corpus.records("viewer/pinyin_page.jsonl")) {
            if (record.fn != HELPER + "page_pinyin") fail("an unknown record: ${record.fn}")
            count++
            val lines = strings(record.args[0])
            val readings = ViewerPinyin.readings(lines)
            val got = JsonObject(mapOf(
                "is_chinese" to JsonPrimitive(ViewerPinyin.isChinese(lines)),
                "readings" to (readings?.let { r -> JsonArray(r.map { it?.let(::array) ?: JsonNull }) } ?: JsonNull),
            ))
            misses.check(got == record.out) { "page_pinyin($lines): $got, Python's ${record.out}" }
        }
        assertTrue("$count records", count > 300)
        misses.assertNone()
    }

    private fun config(name: String): OpenCC.Config =
        CONFIGS.firstOrNull { it.file == name } ?: throw AssertionError("no config $name")

    private fun byConfig(convert: (OpenCC.Config) -> String): JsonObject =
        JsonObject(CONFIGS.associate { it.file to JsonPrimitive(convert(it)) })

    /** A table of scripts' or names' answer as the record writes it: each script's items in their order. */
    private fun items(shown: Map<String, Map<String, String>>): JsonObject {
        if (shown.keys.toList() != listOf(Hanzi.SIMPLIFIED, Hanzi.TRADITIONAL)) fail("its scripts: ${shown.keys}")
        return JsonObject(shown.mapValues { (_, table) ->
            JsonArray(table.map { (before, after) -> JsonArray(listOf(JsonPrimitive(before), JsonPrimitive(after))) })
        })
    }

    private fun strings(e: JsonElement): List<String> = e.jsonArray.map { it.jsonPrimitive.content }

    private fun array(strings: List<String>): JsonArray = JsonArray(strings.map(::JsonPrimitive))

    private fun quoted(s: String): String = JsonPrimitive(s.take(160)).toString()
}
