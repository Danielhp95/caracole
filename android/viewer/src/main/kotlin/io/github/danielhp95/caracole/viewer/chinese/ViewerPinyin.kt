package io.github.danielhp95.caracole.viewer.chinese

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.pinyin.Pinyin
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.viewer.ViewerData
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive

/**
 * viewer/pinyin.py: each Chinese character's reading in pinyin, with its tone marks, for the viewer's Pinyin
 * (page.py's data `pinyin`). Each line is read whole, in context, by [Pinyin] in Style.TONE ("" for what it reads no
 * pinyin in), in Simplified characters ([Normalize.simplified], a character for a character, so each reading stays
 * with the character shown); in a sheet in Traditional characters (one Simplified would write otherwise), a 著 is read
 * as 着 unless it is in a word Simplified writes with 著: pypinyin's phrase dictionary's ([Pinyin.isPhrase]) or
 * `_ZHU_WORDS`. A sheet with kana is Japanese and has none.
 *
 * Its constants are pinyin.py's own, read from data/caracole/viewer/pinyin.json (`_KANA`'s pattern, through
 * core.py's PyRegex, `_ZHU_WORDS`, `_LONGEST`), which tests/test_conformance_viewer_chinese.py writes from the
 * module. Lengths and places are in code points, as Python's.
 */
object ViewerPinyin {
    /** `readings`: for each of a sheet's [lines], each character's reading, "" for one with none, or null for a line
     * with no Chinese; null for a sheet whose lines have none at all, or have kana. */
    fun readings(lines: List<String>): List<List<String>?>? {
        if (!isChinese(lines)) return null
        val traditional = lines.any { Normalize.simplified(it) != it }
        return lines.map { line -> if (Normalize.hasHan(line)) read(line, traditional) else null }
    }

    /** `is_chinese`: whether some of [lines] have Chinese characters and none has kana (Japanese). */
    fun isChinese(lines: List<String>): Boolean =
        lines.any(Normalize::hasHan) && lines.none { PyRe.search(kana, it) != null }

    private val data by lazy { ViewerData.table("pinyin") }
    private val kana by lazy { PyRegex.compile(data.getValue("_KANA").jsonPrimitive.content) }
    private val zhuWords by lazy { data.getValue("_ZHU_WORDS").jsonArray.map { it.jsonPrimitive.content }.toSet() }
    private val longest by lazy { data.getValue("_LONGEST").jsonPrimitive.int }

    /** `_read`: each character of [line]'s reading, in context. */
    private fun read(line: String, traditional: Boolean): List<String> {
        val text = asRead(line, traditional)
        var found = Pinyin.lazyPinyin(text, Pinyin.Errors.EMPTY_EACH, Pinyin.Style.TONE)
        val chars = codePoints(text)
        if (found.size != chars.size) {  // never seen: each character on its own, then
            found = chars.map { Pinyin.lazyPinyin(it, Pinyin.Errors.EMPTY_EACH, Pinyin.Style.TONE).firstOrNull() ?: "" }
        }
        val shown = codePoints(line)
        return List(minOf(shown.size, found.size)) { i -> if (Normalize.hasHan(shown[i])) found[i] else "" }
    }

    /** `_as_read`: [line] in Simplified characters and, from a Traditional sheet, each 著 that is no word's of its
     * own as 着. */
    private fun asRead(line: String, traditional: Boolean): String {
        val text = Normalize.simplified(line)
        if (!traditional || ZHU !in text) return text
        val chars = codePoints(text)
        return chars.indices.joinToString("") { i -> if (chars[i] == ZHU && !zhu(chars, i)) ZHE else chars[i] }
    }

    /** `_zhu`: whether the 著 at [i] is in a word Simplified writes with 著 (`_ZHU_WORDS`, pypinyin's phrases). */
    private fun zhu(chars: List<String>, i: Int): Boolean {
        for (start in maxOf(0, i - longest + 1)..i) {
            for (end in maxOf(i + 1, start + 2)..minOf(chars.size, start + longest)) {
                val word = chars.subList(start, end).joinToString("")
                if (word in zhuWords || Pinyin.isPhrase(word)) return true
            }
        }
        return false
    }

    private const val ZHU = "著"
    private const val ZHE = "着"

    private fun codePoints(text: String): List<String> {
        val out = ArrayList<String>(text.length)
        var i = 0
        while (i < text.length) {
            val next = i + Character.charCount(text.codePointAt(i))
            out.add(text.substring(i, next))
            i = next
        }
        return out
    }
}
