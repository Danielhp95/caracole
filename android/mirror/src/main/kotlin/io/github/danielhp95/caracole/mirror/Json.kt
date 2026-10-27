package io.github.danielhp95.caracole.mirror

/**
 * Reads the JSON of caracole's manifest (RFC 8259): an object is a Map, an array a List, a string a String,
 * an integer a Long (a Double when it has a fraction, an exponent or doesn't fit), true and false Booleans,
 * null null. Nothing more is needed, and org.json is Android's alone, so the tests couldn't run it on a JVM.
 */
internal object Json {
    class Malformed(message: String) : Exception(message)

    private const val MAX_DEPTH = 32

    fun parse(text: String): Any? {
        val reader = Reader(text)
        reader.space()
        val value = reader.value(0)
        reader.space()
        if (reader.pos != text.length) throw Malformed("more after the value, at ${reader.pos}")
        return value
    }

    private class Reader(val s: String) {
        var pos = 0

        fun space() {
            while (pos < s.length && (s[pos] == ' ' || s[pos] == '\t' || s[pos] == '\n' || s[pos] == '\r')) pos++
        }

        fun value(depth: Int): Any? {
            if (depth > MAX_DEPTH) throw Malformed("nested too deep")
            if (pos >= s.length) throw Malformed("the text ends early")
            return when (val c = s[pos]) {
                '{' -> obj(depth)
                '[' -> array(depth)
                '"' -> string()
                't' -> word("true", true)
                'f' -> word("false", false)
                'n' -> word("null", null)
                else -> if (c == '-' || c in '0'..'9') number() else throw Malformed("'$c' at $pos")
            }
        }

        private fun obj(depth: Int): Map<String, Any?> {
            pos++
            val map = LinkedHashMap<String, Any?>()
            space()
            if (peek() == '}') { pos++; return map }
            while (true) {
                space()
                if (peek() != '"') throw Malformed("a name expected at $pos")
                val name = string()
                space()
                expect(':')
                space()
                map[name] = value(depth + 1)
                space()
                when (peek()) {
                    ',' -> pos++
                    '}' -> { pos++; return map }
                    else -> throw Malformed("',' or '}' expected at $pos")
                }
            }
        }

        private fun array(depth: Int): List<Any?> {
            pos++
            val list = ArrayList<Any?>()
            space()
            if (peek() == ']') { pos++; return list }
            while (true) {
                space()
                list.add(value(depth + 1))
                space()
                when (peek()) {
                    ',' -> pos++
                    ']' -> { pos++; return list }
                    else -> throw Malformed("',' or ']' expected at $pos")
                }
            }
        }

        private fun string(): String {
            expect('"')
            val out = StringBuilder()
            while (true) {
                if (pos >= s.length) throw Malformed("a string isn't closed")
                val c = s[pos++]
                when {
                    c == '"' -> return out.toString()
                    c == '\\' -> {
                        if (pos >= s.length) throw Malformed("a string isn't closed")
                        when (val e = s[pos++]) {
                            '"', '\\', '/' -> out.append(e)
                            'b' -> out.append('\b')
                            'f' -> out.append('\u000C')
                            'n' -> out.append('\n')
                            'r' -> out.append('\r')
                            't' -> out.append('\t')
                            'u' -> {
                                if (pos + 4 > s.length) throw Malformed("a \\u escape is cut short")
                                val hex = s.substring(pos, pos + 4)
                                val code = hex.toIntOrNull(16) ?: throw Malformed("\\u$hex")
                                if (hex.any { it == '+' || it == '-' }) throw Malformed("\\u$hex")
                                out.append(code.toChar())
                                pos += 4
                            }
                            else -> throw Malformed("the escape \\$e")
                        }
                    }
                    c < ' ' -> throw Malformed("a control character in a string at ${pos - 1}")
                    else -> out.append(c)
                }
            }
        }

        private fun number(): Any {
            val match = NUMBER.matchAt(s, pos) ?: throw Malformed("a number at $pos")
            pos = match.range.last + 1
            val text = match.value
            if (match.groups[1] == null && match.groups[2] == null) text.toLongOrNull()?.let { return it }
            return text.toDouble()
        }

        private fun word(text: String, value: Any?): Any? {
            if (!s.startsWith(text, pos)) throw Malformed("'${s[pos]}' at $pos")
            pos += text.length
            return value
        }

        private fun peek(): Char = if (pos < s.length) s[pos] else throw Malformed("the text ends early")

        private fun expect(c: Char) {
            if (peek() != c) throw Malformed("'$c' expected at $pos")
            pos++
        }
    }

    private val NUMBER = Regex("""-?(?:0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?""")
}
