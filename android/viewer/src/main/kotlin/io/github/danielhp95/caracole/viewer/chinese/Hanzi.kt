package io.github.danielhp95.caracole.viewer.chinese

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.viewer.chinese.OpenCC.Config

/**
 * viewer/hanzi.py: a sheet's Chinese in Simplified characters and in Traditional ones, for the viewer's Chinese
 * characters (page.py's data `hanzi`), each text converted whole, word by word, by [OpenCC].
 *
 * A sheet is written in Traditional characters when more of its characters are Traditional's alone (OpenCC's `t2s`
 * changes each, on its own) than Simplified's alone (`s2tw` changes it) ([writtenInTraditional]). Its Simplified is
 * `tw2s`'s for a Traditional sheet, `t2s`'s for a Simplified one; a Simplified sheet's Traditional is `s2tw`'s, and a
 * Traditional sheet's is as written ([converter]). A text the same in either script, or with no Chinese, has none; a
 * song's title and its artist's name are each judged alone ([names]). Only Chinese characters change, a character for
 * a character, and a conversion of another length is made again a character at a time ([converted]). Lengths are in
 * code points, as Python's; a Chinese character is normalize.py's `has_han`'s ([Normalize.hasHan]).
 *
 * hanzi.py's `chordpro` is for the computer's PDFs alone, and has no port.
 */
object Hanzi {
    /** The two scripts, as the data names them, in its order. */
    const val SIMPLIFIED = "simplified"
    const val TRADITIONAL = "traditional"

    /** `names`: [scripts] of each of [texts] alone (a song's title, its artist's name, the page's title). */
    fun names(texts: List<String>): Map<String, Map<String, String>> {
        val shown = empty()
        for (text in LinkedHashSet(texts)) {
            for ((script, table) in scripts(listOf(text))) shown.getValue(script).putAll(table)
        }
        return shown
    }

    /** `scripts`: each of [texts] with Chinese in Simplified characters and in Traditional ones, where that isn't
     * the text as written, each as long as its text; the texts each once, in their order. */
    fun scripts(texts: List<String>): Map<String, Map<String, String>> {
        val chinese = LinkedHashSet(texts).filter(Normalize::hasHan)
        val traditional = writtenInTraditional(chinese)
        val shown = empty()
        for ((script, table) in shown) {
            val convert = converter(script, traditional) ?: continue
            for (text in chinese) {
                val after = convert(text)
                if (after != text) table[text] = after
            }
        }
        return shown
    }

    /** `converter`: what writes a sheet's texts in [script] ([SIMPLIFIED], [TRADITIONAL]), the sheet written in
     * Traditional characters or not ([traditional]); null where they show as written. */
    fun converter(script: String, traditional: Boolean): ((String) -> String)? {
        val config = when {
            script == SIMPLIFIED -> if (traditional) Config.TW2S else Config.T2S
            traditional -> null
            else -> Config.S2TW
        }
        return config?.let { c -> { text: String -> converted(c, text) } }
    }

    /** `written_in_traditional`: whether more of [texts]' Chinese characters are Traditional's alone than
     * Simplified's alone, each read on its own, each text counted once. */
    fun writtenInTraditional(texts: List<String>): Boolean {
        val characters = ArrayList<String>()
        for (text in LinkedHashSet(texts)) forEach(text) { c -> if (Normalize.hasHan(c)) characters.add(c) }
        val alone = HashMap<String, Pair<Boolean, Boolean>>()
        var traditional = 0
        var simplified = 0
        for (c in characters) {
            val (t, s) = alone.getOrPut(c) { (converted(Config.T2S, c) != c) to (converted(Config.S2TW, c) != c) }
            if (t) traditional++
            if (s) simplified++
        }
        return traditional > simplified
    }

    /**
     * `_converted`: [text] as OpenCC's [config] converts it, as long as it is, its Chinese characters alone: whatever
     * else it holds stays as written. A conversion of another length is made again a character at a time, a character
     * whose conversion isn't one character staying as written.
     */
    fun converted(config: Config, text: String): String {
        val before = characters(text)
        var whole = characters(OpenCC.convert(config, text))
        if (whole.size != before.size) {
            whole = before.map { c -> OpenCC.convert(config, c).takeIf { characters(it).size == 1 } ?: c }
        }
        val out = StringBuilder(text.length)
        for (i in 0 until minOf(before.size, whole.size)) {
            out.append(if (Normalize.hasHan(before[i])) whole[i] else before[i])
        }
        return out.toString()
    }

    private fun empty(): Map<String, MutableMap<String, String>> =
        linkedMapOf(SIMPLIFIED to LinkedHashMap(), TRADITIONAL to LinkedHashMap())

    /** Each code point of [text] as a string of its own. */
    private fun characters(text: String): List<String> {
        val out = ArrayList<String>(text.length)
        forEach(text) { out.add(it) }
        return out
    }

    private inline fun forEach(text: String, each: (String) -> Unit) {
        var i = 0
        while (i < text.length) {
            val next = i + Character.charCount(text.codePointAt(i))
            each(text.substring(i, next))
            i = next
        }
    }
}
