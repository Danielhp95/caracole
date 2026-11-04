package io.github.danielhp95.caracole.core.html.internal.token

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * Character references (WHATWG HTML §13.2.5.72–80), as lexbor's tokenizer decodes them: the named ones by the HTML5
 * table, Python's `html.entities.html5` as data (data/caracole/html/entities.json, the legacy names listed bare beside
 * their `;` form), the numeric ones by the spec's rules.
 */
internal object CharRefs {
    /** One node of the table's trie: [value] where the path to it is a name. */
    class Node {
        val children = HashMap<Char, Node>(4)
        var value: String? = null
    }

    val root: Node by lazy { load() }

    private fun load(): Node {
        val path = "caracole/html/entities.json"
        val stream = CharRefs::class.java.classLoader?.getResourceAsStream(path)
            ?: CharRefs::class.java.getResourceAsStream("/$path")
            ?: throw IllegalStateException("$path is missing from the classpath")
        val text = stream.use { it.readBytes().toString(Charsets.UTF_8) }
        val root = Node()
        for (pair in Json.parseToJsonElement(text).jsonObject.getValue("entities").jsonArray) {
            val (name, value) = pair.jsonArray.map { it.jsonPrimitive.content }
            var node = root
            for (c in name) node = node.children.getOrPut(c) { Node() }
            node.value = value
        }
        return root
    }

    /** Windows-1252's characters, where a numeric reference names a C1 control (the spec's table, lexbor's). */
    private val C1 = intArrayOf(
        0x20AC, 0x81, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021, 0x02C6, 0x2030, 0x0160, 0x2039, 0x0152, 0x8D,
        0x017D, 0x8F, 0x90, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014, 0x02DC, 0x2122, 0x0161, 0x203A,
        0x0153, 0x9D, 0x017E, 0x0178,
    )

    /** The code point a numeric reference to [number] stands for: U+FFFD for 0, a surrogate or past U+10FFFF, the
     * C1 table's, else the number itself (a noncharacter or a control kept, a parse error only). */
    fun numeric(number: Long): Int = when {
        number == 0L || number > 0x10FFFF || number in 0xD800..0xDFFF -> 0xFFFD
        number in 0x80..0x9F -> C1[(number - 0x80).toInt()]
        else -> number.toInt()
    }
}

internal fun isAsciiAlpha(c: Char) = c in 'a'..'z' || c in 'A'..'Z'
internal fun isAsciiDigit(c: Char) = c in '0'..'9'
internal fun isAsciiAlnum(c: Char) = isAsciiAlpha(c) || isAsciiDigit(c)
internal fun isAsciiHex(c: Char) = isAsciiDigit(c) || c in 'a'..'f' || c in 'A'..'F'
internal fun hexValue(c: Char): Int = when (c) {
    in '0'..'9' -> c - '0'
    in 'a'..'f' -> c - 'a' + 10
    else -> c - 'A' + 10
}

/** Tab, LF, FF, CR and space: the tokenizer's whitespace. */
internal fun isHtmlWhitespace(c: Char) = c == '\t' || c == '\n' || c == '\u000C' || c == '\r' || c == ' '
