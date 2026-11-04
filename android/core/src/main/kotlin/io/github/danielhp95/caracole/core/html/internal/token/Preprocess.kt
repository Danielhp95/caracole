package io.github.danielhp95.caracole.core.html.internal.token

import io.github.danielhp95.caracole.core.py.PyCodec

/**
 * The input stream as the tokenizer reads it (WHATWG HTML §13.2.3.5), as lexbor makes it: every CRLF and every lone
 * CR a LF (lexbor does it state by state, to the same text). Nothing else changes: a U+0000 is each state's to
 * handle, a byte-order mark stays a character (selectolax hands lexbor text, which it never sniffs), and a
 * noncharacter or a control is only a parse error.
 */
object Preprocess {
    /** [text] with its newlines normalized. */
    fun text(text: String): String {
        val cr = text.indexOf('\r')
        if (cr < 0) return text
        val out = StringBuilder(text.length)
        out.append(text, 0, cr)
        var i = cr
        while (i < text.length) {
            val c = text[i]
            if (c == '\r') {
                out.append('\n')
                if (i + 1 < text.length && text[i + 1] == '\n') i++
            } else {
                out.append(c)
            }
            i++
        }
        return out.toString()
    }

    /** A page's bytes as caracole's parsers hand them to selectolax: decoded as UTF-8 with replacement
     * (`bytes.decode("utf-8", "replace")`), never by a `<meta charset>`, then [text]. */
    fun bytes(bytes: ByteArray): String = text(PyCodec.utf8Replace(bytes))
}
