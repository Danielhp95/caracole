package io.github.danielhp95.caracole.core.html.internal.token

/**
 * The WHATWG HTML tokenizer (§13.2.5), as lexbor tokenizes for selectolax 1.0.0 (lexbor 3.1.0, 2026-09-28): every
 * state, the character references by the HTML5 table, and lexbor's own readings where they part from the spec's text
 * (docs/superpowers/specs/2026-11-03-html-parsing.md, "The tokenizer"):
 *
 * - `<?target data?>` is a processing instruction (lexbor's §13.2.5.72–76: the target ASCII alphanumerics, `-` and
 *   `_`; `xml` and `xml-stylesheet` in any case, a target cut by any other character, or a `<?` followed by neither a
 *   letter nor `_`, a bogus comment that starts with `?`; one cut short by the end of the input dropped whole);
 * - an attribute written with no value (`<a href>`, or `<a href=>`) has a null one, where the spec's is "";
 * - a part of `<![CDATA[` the input ends in (`<![CD`) is an empty comment, where the spec's keeps what was written;
 * - `<!` the input ends in is a comment of the text since the token before it (`a<!` the text `a`, then the comment
 *   `a`), where the spec's is empty: lexbor's buffer, not emptied at the end of the input.
 *
 * The tree builder drives it: it reads each token with [next] and, after a start tag, says what follows with
 * [switchTo] (RCDATA after `<title>`, as [contentFor] says), and [foreignContent] answers whether the adjusted current
 * node is outside the HTML namespace, where `<![CDATA[` opens a CDATA section (elsewhere it is a bogus comment).
 * The input is preprocessed first ([Preprocess.text]); a caller that did it passes `preprocessed = true`.
 */
class Tokenizer(input: String, preprocessed: Boolean = false) {
    private val s: String = if (preprocessed) input else Preprocess.text(input)
    private val n = s.length
    private var p = 0
    private var state = State.DATA

    /** Whether the tree builder's adjusted current node is in a namespace other than HTML's. */
    var foreignContent: () -> Boolean = { false }

    private val out = ArrayDeque<Token>()
    private val text = StringBuilder()

    private val tagName = StringBuilder()
    private var endTag = false
    private var selfClosing = false
    private var attributes = ArrayList<Attribute>()
    private val attrName = StringBuilder()
    private val attrValue = StringBuilder()
    private var inAttribute = false
    private var attrHasValue = false
    private var lastStartTag: String? = null
    private val buffer = StringBuilder()

    private val comment = StringBuilder()
    private var doctypeName: StringBuilder? = null
    private var doctypePublic: StringBuilder? = null
    private var doctypeSystem: StringBuilder? = null
    private var forceQuirks = false
    private val piTarget = StringBuilder()
    private val piData = StringBuilder()

    /** The next token; [Token.EndOfFile] once the input is over, and ever after. */
    fun next(): Token {
        while (out.isEmpty()) step()
        return out.removeFirst()
    }

    /** Every token to the end, the tree builder's part played by [contentFor] alone (no foreign content). */
    fun all(): List<Token> {
        val tokens = ArrayList<Token>()
        while (true) {
            val token = next()
            tokens += token
            if (token is Token.StartTag) contentFor(token.name)?.let { switchTo(it) }
            if (token === Token.EndOfFile) return tokens
        }
    }

    /** What follows the start tag just read, as the tree builder says (§13.2.6): only right after a start tag. */
    fun switchTo(content: Content) {
        state = when (content) {
            Content.DATA -> State.DATA
            Content.RCDATA -> State.RCDATA
            Content.RAWTEXT -> State.RAWTEXT
            Content.SCRIPT_DATA -> State.SCRIPT_DATA
            Content.PLAINTEXT -> State.PLAINTEXT
        }
    }

    companion object {
        /** The content an HTML element's start tag switches the tokenizer to, as lexbor's
         * `lxb_html_tokenizer_set_state_by_tag` says (a `<noscript>`'s is RAWTEXT only with scripting, which
         * selectolax parses without); null for the others, and for every element of another namespace. */
        fun contentFor(tag: String, scripting: Boolean = false): Content? = when (tag) {
            "title", "textarea" -> Content.RCDATA
            "style", "xmp", "iframe", "noembed", "noframes" -> Content.RAWTEXT
            "script" -> Content.SCRIPT_DATA
            "noscript" -> if (scripting) Content.RAWTEXT else null
            "plaintext" -> Content.PLAINTEXT
            else -> null
        }

        private const val REPLACEMENT = '�'
    }

    private enum class State {
        DATA, RCDATA, RAWTEXT, SCRIPT_DATA, PLAINTEXT, TAG_OPEN, END_TAG_OPEN, TAG_NAME,
        RCDATA_LT, RCDATA_END_TAG_OPEN, RCDATA_END_TAG_NAME,
        RAWTEXT_LT, RAWTEXT_END_TAG_OPEN, RAWTEXT_END_TAG_NAME,
        SCRIPT_LT, SCRIPT_END_TAG_OPEN, SCRIPT_END_TAG_NAME, SCRIPT_ESCAPE_START, SCRIPT_ESCAPE_START_DASH,
        SCRIPT_ESCAPED, SCRIPT_ESCAPED_DASH, SCRIPT_ESCAPED_DASH_DASH, SCRIPT_ESCAPED_LT, SCRIPT_ESCAPED_END_TAG_OPEN,
        SCRIPT_ESCAPED_END_TAG_NAME, SCRIPT_DOUBLE_ESCAPE_START, SCRIPT_DOUBLE_ESCAPED, SCRIPT_DOUBLE_ESCAPED_DASH,
        SCRIPT_DOUBLE_ESCAPED_DASH_DASH, SCRIPT_DOUBLE_ESCAPED_LT, SCRIPT_DOUBLE_ESCAPE_END,
        BEFORE_ATTR_NAME, ATTR_NAME, AFTER_ATTR_NAME, BEFORE_ATTR_VALUE, ATTR_VALUE_DOUBLE, ATTR_VALUE_SINGLE,
        ATTR_VALUE_UNQUOTED, AFTER_ATTR_VALUE_QUOTED, SELF_CLOSING,
        BOGUS_COMMENT, MARKUP_DECLARATION,
        COMMENT_START, COMMENT_START_DASH, COMMENT, COMMENT_LT, COMMENT_LT_BANG, COMMENT_LT_BANG_DASH,
        COMMENT_LT_BANG_DASH_DASH, COMMENT_END_DASH, COMMENT_END, COMMENT_END_BANG,
        DOCTYPE, BEFORE_DOCTYPE_NAME, DOCTYPE_NAME, AFTER_DOCTYPE_NAME, AFTER_PUBLIC_KEYWORD, BEFORE_PUBLIC_ID,
        PUBLIC_ID_DOUBLE, PUBLIC_ID_SINGLE, AFTER_PUBLIC_ID, BETWEEN_PUBLIC_AND_SYSTEM, AFTER_SYSTEM_KEYWORD,
        BEFORE_SYSTEM_ID, SYSTEM_ID_DOUBLE, SYSTEM_ID_SINGLE, AFTER_SYSTEM_ID, BOGUS_DOCTYPE,
        CDATA, CDATA_BRACKET, CDATA_END,
        PI_OPEN, PI_TARGET, AFTER_PI_TARGET, PI_DATA, PI_QUESTION,
        END,
    }

    private fun step() {
        when (state) {
            State.DATA -> data()
            State.RCDATA -> rcdata()
            State.RAWTEXT -> rawtext()
            State.SCRIPT_DATA -> scriptData()
            State.PLAINTEXT -> plaintext()
            State.TAG_OPEN -> tagOpen()
            State.END_TAG_OPEN -> endTagOpen()
            State.TAG_NAME -> tagNameState()
            State.RCDATA_LT -> lessThan(State.RCDATA_END_TAG_OPEN, State.RCDATA)
            State.RCDATA_END_TAG_OPEN -> endTagOpenIn(State.RCDATA_END_TAG_NAME, State.RCDATA)
            State.RCDATA_END_TAG_NAME -> endTagNameIn(State.RCDATA)
            State.RAWTEXT_LT -> lessThan(State.RAWTEXT_END_TAG_OPEN, State.RAWTEXT)
            State.RAWTEXT_END_TAG_OPEN -> endTagOpenIn(State.RAWTEXT_END_TAG_NAME, State.RAWTEXT)
            State.RAWTEXT_END_TAG_NAME -> endTagNameIn(State.RAWTEXT)
            State.SCRIPT_LT -> scriptLessThan()
            State.SCRIPT_END_TAG_OPEN -> endTagOpenIn(State.SCRIPT_END_TAG_NAME, State.SCRIPT_DATA)
            State.SCRIPT_END_TAG_NAME -> endTagNameIn(State.SCRIPT_DATA)
            State.SCRIPT_ESCAPE_START -> dashOr(State.SCRIPT_ESCAPE_START_DASH, State.SCRIPT_DATA)
            State.SCRIPT_ESCAPE_START_DASH -> dashOr(State.SCRIPT_ESCAPED_DASH_DASH, State.SCRIPT_DATA)
            State.SCRIPT_ESCAPED -> scriptEscaped(double = false)
            State.SCRIPT_ESCAPED_DASH -> scriptEscapedDash(double = false)
            State.SCRIPT_ESCAPED_DASH_DASH -> scriptEscapedDashDash(double = false)
            State.SCRIPT_ESCAPED_LT -> scriptEscapedLessThan()
            State.SCRIPT_ESCAPED_END_TAG_OPEN -> endTagOpenIn(State.SCRIPT_ESCAPED_END_TAG_NAME, State.SCRIPT_ESCAPED)
            State.SCRIPT_ESCAPED_END_TAG_NAME -> endTagNameIn(State.SCRIPT_ESCAPED)
            State.SCRIPT_DOUBLE_ESCAPE_START ->
                doubleEscapeEdge(State.SCRIPT_DOUBLE_ESCAPED, State.SCRIPT_ESCAPED)
            State.SCRIPT_DOUBLE_ESCAPED -> scriptEscaped(double = true)
            State.SCRIPT_DOUBLE_ESCAPED_DASH -> scriptEscapedDash(double = true)
            State.SCRIPT_DOUBLE_ESCAPED_DASH_DASH -> scriptEscapedDashDash(double = true)
            State.SCRIPT_DOUBLE_ESCAPED_LT -> scriptDoubleEscapedLessThan()
            State.SCRIPT_DOUBLE_ESCAPE_END ->
                doubleEscapeEdge(State.SCRIPT_ESCAPED, State.SCRIPT_DOUBLE_ESCAPED)
            State.BEFORE_ATTR_NAME -> beforeAttrName()
            State.ATTR_NAME -> attrNameState()
            State.AFTER_ATTR_NAME -> afterAttrName()
            State.BEFORE_ATTR_VALUE -> beforeAttrValue()
            State.ATTR_VALUE_DOUBLE -> attrValueQuoted('"')
            State.ATTR_VALUE_SINGLE -> attrValueQuoted('\'')
            State.ATTR_VALUE_UNQUOTED -> attrValueUnquoted()
            State.AFTER_ATTR_VALUE_QUOTED -> afterAttrValueQuoted()
            State.SELF_CLOSING -> selfClosingStartTag()
            State.BOGUS_COMMENT -> bogusComment()
            State.MARKUP_DECLARATION -> markupDeclaration()
            State.COMMENT_START -> commentStart()
            State.COMMENT_START_DASH -> commentStartDash()
            State.COMMENT -> commentState()
            State.COMMENT_LT -> commentLessThan()
            State.COMMENT_LT_BANG -> {
                if (p < n && s[p] == '-') { p++; state = State.COMMENT_LT_BANG_DASH } else state = State.COMMENT
            }
            State.COMMENT_LT_BANG_DASH -> {
                if (p < n && s[p] == '-') { p++; state = State.COMMENT_LT_BANG_DASH_DASH }
                else state = State.COMMENT_END_DASH
            }
            State.COMMENT_LT_BANG_DASH_DASH -> state = State.COMMENT_END // '>' and EOF too: nested-comment otherwise
            State.COMMENT_END_DASH -> commentEndDash()
            State.COMMENT_END -> commentEnd()
            State.COMMENT_END_BANG -> commentEndBang()
            State.DOCTYPE -> doctype()
            State.BEFORE_DOCTYPE_NAME -> beforeDoctypeName()
            State.DOCTYPE_NAME -> doctypeNameState()
            State.AFTER_DOCTYPE_NAME -> afterDoctypeName()
            State.AFTER_PUBLIC_KEYWORD -> afterKeyword(State.BEFORE_PUBLIC_ID, public = true)
            State.BEFORE_PUBLIC_ID -> beforeIdentifier(public = true)
            State.PUBLIC_ID_DOUBLE -> identifier('"', public = true)
            State.PUBLIC_ID_SINGLE -> identifier('\'', public = true)
            State.AFTER_PUBLIC_ID -> afterPublicId()
            State.BETWEEN_PUBLIC_AND_SYSTEM -> betweenPublicAndSystem()
            State.AFTER_SYSTEM_KEYWORD -> afterKeyword(State.BEFORE_SYSTEM_ID, public = false)
            State.BEFORE_SYSTEM_ID -> beforeIdentifier(public = false)
            State.SYSTEM_ID_DOUBLE -> identifier('"', public = false)
            State.SYSTEM_ID_SINGLE -> identifier('\'', public = false)
            State.AFTER_SYSTEM_ID -> afterSystemId()
            State.BOGUS_DOCTYPE -> bogusDoctype()
            State.CDATA -> cdata()
            State.CDATA_BRACKET -> {
                if (p < n && s[p] == ']') { p++; state = State.CDATA_END } else { text.append(']'); state = State.CDATA }
            }
            State.CDATA_END -> cdataEnd()
            State.PI_OPEN -> piOpen()
            State.PI_TARGET -> piTargetState()
            State.AFTER_PI_TARGET -> {
                while (p < n && isHtmlWhitespace(s[p])) p++
                if (p >= n) eof() else state = State.PI_DATA
            }
            State.PI_DATA -> piDataState()
            State.PI_QUESTION -> piQuestion()
            State.END -> out.addLast(Token.EndOfFile)
        }
    }

    // --- emitting ----------------------------------------------------------------------------------------------

    private fun flushText() {
        if (text.isEmpty()) return
        var start = 0
        var kind = kindOf(text[0])
        for (i in 1 until text.length) {
            val k = kindOf(text[i])
            if (k != kind) {
                out.addLast(Token.Characters(text.substring(start, i), kind))
                start = i
                kind = k
            }
        }
        out.addLast(Token.Characters(text.substring(start), kind))
        text.setLength(0)
    }

    private fun kindOf(c: Char): CharKind = when {
        isHtmlWhitespace(c) -> CharKind.WHITESPACE
        c == '\u0000' -> CharKind.NULL
        else -> CharKind.OTHER
    }

    private fun eof() {
        flushText()
        out.addLast(Token.EndOfFile)
        state = State.END
    }

    private fun startTag(end: Boolean) {
        tagName.setLength(0)
        endTag = end
        selfClosing = false
        attributes = ArrayList()
        inAttribute = false
    }

    private fun newAttribute() {
        finishAttribute()
        attrName.setLength(0)
        attrValue.setLength(0)
        attrHasValue = false
        inAttribute = true
    }

    /** The attribute just read joins the tag unless one of its name came before: the first of duplicates wins. */
    private fun finishAttribute() {
        if (!inAttribute) return
        inAttribute = false
        val name = attrName.toString()
        if (attributes.none { it.name == name }) {
            attributes += Attribute(name, if (attrHasValue) attrValue.toString() else null)
        }
    }

    private fun emitTag() {
        finishAttribute()
        flushText()
        val name = tagName.toString()
        if (endTag) {
            out.addLast(Token.EndTag(name))
        } else {
            out.addLast(Token.StartTag(name, attributes, selfClosing))
            lastStartTag = name
        }
        attributes = ArrayList()
        state = State.DATA
    }

    private fun emitComment() {
        flushText()
        out.addLast(Token.Comment(comment.toString()))
    }

    private fun emitDoctype() {
        flushText()
        out.addLast(Token.Doctype(doctypeName?.toString(), doctypePublic?.toString(), doctypeSystem?.toString(),
                                  forceQuirks))
    }

    // --- text --------------------------------------------------------------------------------------------------

    private fun data() {
        while (p < n) {
            when (val c = s[p++]) {
                '<' -> { state = State.TAG_OPEN; return }
                '&' -> charRef(text, inAttributeValue = false)
                else -> text.append(c) // a U+0000 too, the tree builder's to drop or replace
            }
        }
        eof()
    }

    private fun rcdata() {
        while (p < n) {
            when (val c = s[p++]) {
                '<' -> { state = State.RCDATA_LT; return }
                '&' -> charRef(text, inAttributeValue = false)
                '\u0000' -> text.append(REPLACEMENT)
                else -> text.append(c)
            }
        }
        eof()
    }

    private fun rawtext() {
        while (p < n) {
            when (val c = s[p++]) {
                '<' -> { state = State.RAWTEXT_LT; return }
                '\u0000' -> text.append(REPLACEMENT)
                else -> text.append(c)
            }
        }
        eof()
    }

    private fun scriptData() {
        while (p < n) {
            when (val c = s[p++]) {
                '<' -> { state = State.SCRIPT_LT; return }
                '\u0000' -> text.append(REPLACEMENT)
                else -> text.append(c)
            }
        }
        eof()
    }

    private fun plaintext() {
        while (p < n) {
            val c = s[p++]
            text.append(if (c == '\u0000') REPLACEMENT else c)
        }
        eof()
    }

    /** RCDATA's and RAWTEXT's less-than sign state. */
    private fun lessThan(endTagOpen: State, back: State) {
        if (p < n && s[p] == '/') {
            p++
            buffer.setLength(0)
            state = endTagOpen
        } else {
            text.append('<')
            state = back
        }
    }

    private fun endTagOpenIn(endTagName: State, back: State) {
        if (p < n && isAsciiAlpha(s[p])) {
            startTag(end = true)
            state = endTagName
        } else {
            text.append("</")
            state = back
        }
    }

    /** An end tag in RCDATA, RAWTEXT or script data: a tag only when it is the appropriate end tag (the last start
     * tag's), else text, read on in [back]. */
    private fun endTagNameIn(back: State) {
        while (p < n) {
            val c = s[p]
            val appropriate = lastStartTag != null && lastStartTag == tagName.toString()
            when {
                isHtmlWhitespace(c) -> if (appropriate) { p++; state = State.BEFORE_ATTR_NAME; return } else break
                c == '/' -> if (appropriate) { p++; state = State.SELF_CLOSING; return } else break
                c == '>' -> if (appropriate) { p++; emitTag(); return } else break
                isAsciiAlpha(c) -> { tagName.append(asciiLowerChar(c)); buffer.append(c); p++ }
                else -> break
            }
        }
        text.append("</").append(buffer)
        state = back
    }

    private fun scriptLessThan() {
        when (if (p < n) s[p] else null) {
            '/' -> { p++; buffer.setLength(0); state = State.SCRIPT_END_TAG_OPEN }
            '!' -> { p++; text.append("<!"); state = State.SCRIPT_ESCAPE_START }
            else -> { text.append('<'); state = State.SCRIPT_DATA }
        }
    }

    /** Script data escape start and its dash state: a `-` goes to [dash], anything else back to script data. */
    private fun dashOr(dash: State, back: State) {
        if (p < n && s[p] == '-') {
            p++
            text.append('-')
            state = dash
        } else {
            state = back
        }
    }

    private fun scriptEscaped(double: Boolean) {
        while (p < n) {
            when (val c = s[p++]) {
                '-' -> {
                    text.append('-')
                    state = if (double) State.SCRIPT_DOUBLE_ESCAPED_DASH else State.SCRIPT_ESCAPED_DASH
                    return
                }
                '<' -> {
                    if (double) { text.append('<'); state = State.SCRIPT_DOUBLE_ESCAPED_LT } else state = State.SCRIPT_ESCAPED_LT
                    return
                }
                '\u0000' -> text.append(REPLACEMENT)
                else -> text.append(c)
            }
        }
        eof()
    }

    private fun scriptEscapedDash(double: Boolean) {
        val escaped = if (double) State.SCRIPT_DOUBLE_ESCAPED else State.SCRIPT_ESCAPED
        if (p >= n) { eof(); return }
        when (val c = s[p++]) {
            '-' -> {
                text.append('-')
                state = if (double) State.SCRIPT_DOUBLE_ESCAPED_DASH_DASH else State.SCRIPT_ESCAPED_DASH_DASH
            }
            '<' -> if (double) { text.append('<'); state = State.SCRIPT_DOUBLE_ESCAPED_LT } else state = State.SCRIPT_ESCAPED_LT
            '\u0000' -> { text.append(REPLACEMENT); state = escaped }
            else -> { text.append(c); state = escaped }
        }
    }

    private fun scriptEscapedDashDash(double: Boolean) {
        val escaped = if (double) State.SCRIPT_DOUBLE_ESCAPED else State.SCRIPT_ESCAPED
        if (p >= n) { eof(); return }
        when (val c = s[p++]) {
            '-' -> text.append('-')
            '<' -> if (double) { text.append('<'); state = State.SCRIPT_DOUBLE_ESCAPED_LT } else state = State.SCRIPT_ESCAPED_LT
            '>' -> { text.append('>'); state = State.SCRIPT_DATA }
            '\u0000' -> { text.append(REPLACEMENT); state = escaped }
            else -> { text.append(c); state = escaped }
        }
    }

    private fun scriptEscapedLessThan() {
        val c = if (p < n) s[p] else null
        when {
            c == '/' -> { p++; buffer.setLength(0); state = State.SCRIPT_ESCAPED_END_TAG_OPEN }
            c != null && isAsciiAlpha(c) -> {
                buffer.setLength(0)
                text.append('<')
                state = State.SCRIPT_DOUBLE_ESCAPE_START
            }
            else -> { text.append('<'); state = State.SCRIPT_ESCAPED }
        }
    }

    private fun scriptDoubleEscapedLessThan() {
        if (p < n && s[p] == '/') {
            p++
            buffer.setLength(0)
            text.append('/')
            state = State.SCRIPT_DOUBLE_ESCAPE_END
        } else {
            state = State.SCRIPT_DOUBLE_ESCAPED
        }
    }

    /** Script data double escape start and end: the letters after `<` (or `</`) gathered, lower-case, in the
     * buffer, and at their end [ifScript] when they spell `script`, else [otherwise]. */
    private fun doubleEscapeEdge(ifScript: State, otherwise: State) {
        while (p < n) {
            val c = s[p]
            when {
                isHtmlWhitespace(c) || c == '/' || c == '>' -> {
                    p++
                    text.append(c)
                    state = if (buffer.toString() == "script") ifScript else otherwise
                    return
                }
                isAsciiAlpha(c) -> { p++; buffer.append(asciiLowerChar(c)); text.append(c) }
                else -> { state = otherwise; return }
            }
        }
        state = otherwise
    }

    // --- tags --------------------------------------------------------------------------------------------------

    private fun tagOpen() {
        if (p >= n) { text.append('<'); eof(); return }
        val c = s[p]
        when {
            isAsciiAlpha(c) -> { startTag(end = false); state = State.TAG_NAME }
            c == '/' -> { p++; state = State.END_TAG_OPEN }
            c == '!' -> { p++; state = State.MARKUP_DECLARATION }
            c == '?' -> { p++; state = State.PI_OPEN }
            else -> { text.append('<'); state = State.DATA }
        }
    }

    private fun endTagOpen() {
        if (p >= n) { text.append("</"); eof(); return }
        val c = s[p]
        when {
            isAsciiAlpha(c) -> { startTag(end = true); state = State.TAG_NAME }
            c == '>' -> { p++; state = State.DATA }
            else -> { comment.setLength(0); state = State.BOGUS_COMMENT }
        }
    }

    private fun tagNameState() {
        while (p < n) {
            val c = s[p++]
            when {
                isHtmlWhitespace(c) -> { state = State.BEFORE_ATTR_NAME; return }
                c == '/' -> { state = State.SELF_CLOSING; return }
                c == '>' -> { emitTag(); return }
                c == '\u0000' -> tagName.append(REPLACEMENT)
                else -> tagName.append(asciiLowerChar(c))
            }
        }
        eof() // a tag the input ends in is dropped
    }

    private fun beforeAttrName() {
        while (p < n) {
            val c = s[p]
            when {
                isHtmlWhitespace(c) -> p++
                c == '/' || c == '>' -> { state = State.AFTER_ATTR_NAME; return }
                c == '=' -> { newAttribute(); attrName.append('='); p++; state = State.ATTR_NAME; return }
                else -> { newAttribute(); state = State.ATTR_NAME; return }
            }
        }
        eof()
    }

    private fun attrNameState() {
        while (p < n) {
            val c = s[p]
            when {
                isHtmlWhitespace(c) || c == '/' || c == '>' -> { state = State.AFTER_ATTR_NAME; return }
                c == '=' -> { p++; state = State.BEFORE_ATTR_VALUE; return }
                c == '\u0000' -> { p++; attrName.append(REPLACEMENT) }
                else -> { p++; attrName.append(asciiLowerChar(c)) }
            }
        }
        eof()
    }

    private fun afterAttrName() {
        while (p < n) {
            val c = s[p]
            when {
                isHtmlWhitespace(c) -> p++
                c == '/' -> { p++; state = State.SELF_CLOSING; return }
                c == '=' -> { p++; state = State.BEFORE_ATTR_VALUE; return }
                c == '>' -> { p++; emitTag(); return }
                else -> { newAttribute(); state = State.ATTR_NAME; return }
            }
        }
        eof()
    }

    private fun beforeAttrValue() {
        while (p < n) {
            when (s[p]) {
                '\t', '\n', '\u000C', '\r', ' ' -> p++
                '"' -> { p++; attrHasValue = true; state = State.ATTR_VALUE_DOUBLE; return }
                '\'' -> { p++; attrHasValue = true; state = State.ATTR_VALUE_SINGLE; return }
                '>' -> { p++; emitTag(); return } // a missing value: null, as lexbor keeps it
                else -> { attrHasValue = true; state = State.ATTR_VALUE_UNQUOTED; return }
            }
        }
        eof()
    }

    private fun attrValueQuoted(quote: Char) {
        while (p < n) {
            val c = s[p++]
            when {
                c == quote -> { state = State.AFTER_ATTR_VALUE_QUOTED; return }
                c == '&' -> charRef(attrValue, inAttributeValue = true)
                c == '\u0000' -> attrValue.append(REPLACEMENT)
                else -> attrValue.append(c)
            }
        }
        eof()
    }

    private fun attrValueUnquoted() {
        while (p < n) {
            val c = s[p++]
            when {
                isHtmlWhitespace(c) -> { state = State.BEFORE_ATTR_NAME; return }
                c == '&' -> charRef(attrValue, inAttributeValue = true)
                c == '>' -> { emitTag(); return }
                c == '\u0000' -> attrValue.append(REPLACEMENT)
                else -> attrValue.append(c)
            }
        }
        eof()
    }

    private fun afterAttrValueQuoted() {
        if (p >= n) { eof(); return }
        val c = s[p]
        when {
            isHtmlWhitespace(c) -> { p++; state = State.BEFORE_ATTR_NAME }
            c == '/' -> { p++; state = State.SELF_CLOSING }
            c == '>' -> { p++; emitTag() }
            else -> state = State.BEFORE_ATTR_NAME
        }
    }

    private fun selfClosingStartTag() {
        if (p >= n) { eof(); return }
        if (s[p] == '>') {
            p++
            selfClosing = true
            emitTag()
        } else {
            state = State.BEFORE_ATTR_NAME
        }
    }

    // --- character references ----------------------------------------------------------------------------------

    /** A character reference, its `&` just read, appended to [sink] (the text, or the attribute's value). */
    private fun charRef(sink: StringBuilder, inAttributeValue: Boolean) {
        if (p >= n) { sink.append('&'); return }
        val c = s[p]
        when {
            isAsciiAlnum(c) -> namedRef(sink, inAttributeValue)
            c == '#' -> numericRef(sink)
            else -> sink.append('&')
        }
    }

    /** The longest name of the table the input starts with, read as lexbor's trie of the names reads it. */
    private fun namedRef(sink: StringBuilder, inAttributeValue: Boolean) {
        var node = CharRefs.root
        var i = p
        var value: String? = null
        var matchEnd = -1
        while (i < n) {
            node = node.children[s[i]] ?: break
            i++
            val v = node.value
            if (v != null) { value = v; matchEnd = i }
        }
        if (value == null) { // the ambiguous ampersand state: the ASCII alphanumerics as written
            var j = i
            while (j < n && isAsciiAlnum(s[j])) j++
            sink.append('&').append(s, p, j)
            p = j
            return
        }
        if (inAttributeValue && s[matchEnd - 1] != ';' && matchEnd < n && (s[matchEnd] == '=' || isAsciiAlnum(s[matchEnd]))) {
            sink.append('&').append(s, p, i) // the historical rule: `&ampx` and `&amp=y` as written in a value
            p = i
            return
        }
        sink.append(value).append(s, matchEnd, i)
        p = i
    }

    private fun numericRef(sink: StringBuilder) {
        var i = p + 1
        val hex = i < n && (s[i] == 'x' || s[i] == 'X')
        if (hex) i++
        val digits = i
        var number = 0L
        while (i < n && (if (hex) isAsciiHex(s[i]) else isAsciiDigit(s[i]))) {
            if (number <= 0x10FFFF) number = if (hex) number * 16 + hexValue(s[i]) else number * 10 + (s[i] - '0')
            i++
        }
        if (i == digits) { // no digit: `&#` or `&#x` as written
            sink.append('&').append(s, p, digits)
            p = digits
            return
        }
        if (i < n && s[i] == ';') i++
        val cp = CharRefs.numeric(number)
        if (cp < 0x10000) sink.append(cp.toChar()) else sink.append(Character.toChars(cp))
        p = i
    }

    // --- comments ----------------------------------------------------------------------------------------------

    private fun markupDeclaration() {
        val rest = n - p
        if (rest >= 2 && s[p] == '-' && s[p + 1] == '-') {
            p += 2
            comment.setLength(0)
            state = State.COMMENT_START
            return
        }
        comment.setLength(0)
        if (rest >= 7 && regionIgnoringCase("doctype")) {
            p += 7
            doctypeName = null
            doctypePublic = null
            doctypeSystem = null
            forceQuirks = false
            state = State.DOCTYPE
            return
        }
        if (rest >= 7 && s.startsWith("[CDATA[", p)) {
            if (foreignContent()) { p += 7; state = State.CDATA; return }
            state = State.BOGUS_COMMENT // "[CDATA[…" the comment's data
            return
        }
        if (rest in 1..6 && s[p] == '[' && asciiStartsIgnoringCase("[CDATA[", s.substring(p))) {
            p = n // lexbor: the part of <![CDATA[ the input ends in is no comment's data
        }
        if (rest == 0) comment.append(text) // lexbor: `<!` the input ends in holds the text before it, again
        state = State.BOGUS_COMMENT
    }

    private fun regionIgnoringCase(word: String): Boolean =
        word.indices.all { p + it < n && asciiLowerChar(s[p + it]) == word[it] }

    private fun bogusComment() {
        while (p < n) {
            when (val c = s[p++]) {
                '>' -> { emitComment(); state = State.DATA; return }
                '\u0000' -> comment.append(REPLACEMENT)
                else -> comment.append(c)
            }
        }
        emitComment()
        eof()
    }

    private fun commentStart() {
        when (if (p < n) s[p] else null) {
            '-' -> { p++; state = State.COMMENT_START_DASH }
            '>' -> { p++; emitComment(); state = State.DATA }
            else -> state = State.COMMENT
        }
    }

    private fun commentStartDash() {
        if (p >= n) { emitComment(); eof(); return }
        when (s[p]) {
            '-' -> { p++; state = State.COMMENT_END }
            '>' -> { p++; emitComment(); state = State.DATA }
            else -> { comment.append('-'); state = State.COMMENT }
        }
    }

    private fun commentState() {
        while (p < n) {
            when (val c = s[p++]) {
                '<' -> { comment.append('<'); state = State.COMMENT_LT; return }
                '-' -> { state = State.COMMENT_END_DASH; return }
                '\u0000' -> comment.append(REPLACEMENT)
                else -> comment.append(c)
            }
        }
        emitComment()
        eof()
    }

    private fun commentLessThan() {
        when (if (p < n) s[p] else null) {
            '!' -> { p++; comment.append('!'); state = State.COMMENT_LT_BANG }
            '<' -> { p++; comment.append('<') }
            else -> state = State.COMMENT
        }
    }

    private fun commentEndDash() {
        if (p >= n) { emitComment(); eof(); return }
        if (s[p] == '-') {
            p++
            state = State.COMMENT_END
        } else {
            comment.append('-')
            state = State.COMMENT
        }
    }

    private fun commentEnd() {
        if (p >= n) { emitComment(); eof(); return }
        when (s[p]) {
            '>' -> { p++; emitComment(); state = State.DATA }
            '!' -> { p++; state = State.COMMENT_END_BANG }
            '-' -> { p++; comment.append('-') }
            else -> { comment.append("--"); state = State.COMMENT }
        }
    }

    private fun commentEndBang() {
        if (p >= n) { emitComment(); eof(); return }
        when (s[p]) {
            '-' -> { p++; comment.append("--!"); state = State.COMMENT_END_DASH }
            '>' -> { p++; emitComment(); state = State.DATA }
            else -> { comment.append("--!"); state = State.COMMENT }
        }
    }

    // --- doctypes ----------------------------------------------------------------------------------------------

    private fun doctypeAtEnd() {
        forceQuirks = true
        emitDoctype()
        eof()
    }

    private fun doctype() {
        if (p >= n) { doctypeAtEnd(); return }
        if (isHtmlWhitespace(s[p])) p++
        state = State.BEFORE_DOCTYPE_NAME
    }

    private fun beforeDoctypeName() {
        while (p < n) {
            val c = s[p++]
            when {
                isHtmlWhitespace(c) -> {}
                c == '>' -> { forceQuirks = true; emitDoctype(); state = State.DATA; return }
                else -> {
                    doctypeName = StringBuilder().append(if (c == '\u0000') REPLACEMENT else asciiLowerChar(c))
                    state = State.DOCTYPE_NAME
                    return
                }
            }
        }
        doctypeAtEnd()
    }

    private fun doctypeNameState() {
        val name = doctypeName!!
        while (p < n) {
            val c = s[p++]
            when {
                isHtmlWhitespace(c) -> { state = State.AFTER_DOCTYPE_NAME; return }
                c == '>' -> { emitDoctype(); state = State.DATA; return }
                c == '\u0000' -> name.append(REPLACEMENT)
                else -> name.append(asciiLowerChar(c))
            }
        }
        doctypeAtEnd()
    }

    private fun afterDoctypeName() {
        while (p < n) {
            val c = s[p]
            when {
                isHtmlWhitespace(c) -> p++
                c == '>' -> { p++; emitDoctype(); state = State.DATA; return }
                n - p >= 6 && regionIgnoringCase("public") -> { p += 6; state = State.AFTER_PUBLIC_KEYWORD; return }
                n - p >= 6 && regionIgnoringCase("system") -> { p += 6; state = State.AFTER_SYSTEM_KEYWORD; return }
                else -> { forceQuirks = true; state = State.BOGUS_DOCTYPE; return }
            }
        }
        doctypeAtEnd()
    }

    private fun openIdentifier(quote: Char, public: Boolean) {
        if (public) {
            doctypePublic = StringBuilder()
            state = if (quote == '"') State.PUBLIC_ID_DOUBLE else State.PUBLIC_ID_SINGLE
        } else {
            doctypeSystem = StringBuilder()
            state = if (quote == '"') State.SYSTEM_ID_DOUBLE else State.SYSTEM_ID_SINGLE
        }
    }

    /** After the PUBLIC or SYSTEM keyword. */
    private fun afterKeyword(before: State, public: Boolean) {
        if (p >= n) { doctypeAtEnd(); return }
        val c = s[p]
        when {
            isHtmlWhitespace(c) -> { p++; state = before }
            c == '"' || c == '\'' -> { p++; openIdentifier(c, public) }
            c == '>' -> { p++; forceQuirks = true; emitDoctype(); state = State.DATA }
            else -> { forceQuirks = true; state = State.BOGUS_DOCTYPE }
        }
    }

    private fun beforeIdentifier(public: Boolean) {
        while (p < n) {
            val c = s[p]
            when {
                isHtmlWhitespace(c) -> p++
                c == '"' || c == '\'' -> { p++; openIdentifier(c, public); return }
                c == '>' -> { p++; forceQuirks = true; emitDoctype(); state = State.DATA; return }
                else -> { forceQuirks = true; state = State.BOGUS_DOCTYPE; return }
            }
        }
        doctypeAtEnd()
    }

    private fun identifier(quote: Char, public: Boolean) {
        val id = (if (public) doctypePublic else doctypeSystem)!!
        while (p < n) {
            val c = s[p++]
            when {
                c == quote -> { state = if (public) State.AFTER_PUBLIC_ID else State.AFTER_SYSTEM_ID; return }
                c == '>' -> { forceQuirks = true; emitDoctype(); state = State.DATA; return }
                c == '\u0000' -> id.append(REPLACEMENT)
                else -> id.append(c)
            }
        }
        doctypeAtEnd()
    }

    private fun afterPublicId() {
        if (p >= n) { doctypeAtEnd(); return }
        val c = s[p]
        when {
            isHtmlWhitespace(c) -> { p++; state = State.BETWEEN_PUBLIC_AND_SYSTEM }
            c == '>' -> { p++; emitDoctype(); state = State.DATA }
            c == '"' || c == '\'' -> { p++; openIdentifier(c, public = false) }
            else -> { forceQuirks = true; state = State.BOGUS_DOCTYPE }
        }
    }

    private fun betweenPublicAndSystem() {
        while (p < n) {
            val c = s[p]
            when {
                isHtmlWhitespace(c) -> p++
                c == '>' -> { p++; emitDoctype(); state = State.DATA; return }
                c == '"' || c == '\'' -> { p++; openIdentifier(c, public = false); return }
                else -> { forceQuirks = true; state = State.BOGUS_DOCTYPE; return }
            }
        }
        doctypeAtEnd()
    }

    private fun afterSystemId() {
        while (p < n) {
            val c = s[p]
            when {
                isHtmlWhitespace(c) -> p++
                c == '>' -> { p++; emitDoctype(); state = State.DATA; return }
                else -> { state = State.BOGUS_DOCTYPE; return } // no force-quirks here
            }
        }
        doctypeAtEnd()
    }

    private fun bogusDoctype() {
        while (p < n) {
            if (s[p++] == '>') { emitDoctype(); state = State.DATA; return }
        }
        emitDoctype()
        eof()
    }

    // --- CDATA sections and processing instructions ------------------------------------------------------------

    private fun cdata() {
        while (p < n) {
            val c = s[p++]
            if (c == ']') { state = State.CDATA_BRACKET; return }
            text.append(c) // a U+0000 kept: the tree builder replaces it in foreign content
        }
        eof()
    }

    private fun cdataEnd() {
        when (if (p < n) s[p] else null) {
            ']' -> { p++; text.append(']') }
            '>' -> { p++; flushText(); state = State.DATA } // its text a token of its own, as lexbor's
            else -> { text.append("]]"); state = State.CDATA }
        }
    }

    private fun piOpen() {
        if (p >= n) { eof(); return } // `<?` the input ends in is dropped
        val c = s[p]
        if (isAsciiAlpha(c) || c == '_') {
            piTarget.setLength(0)
            piData.setLength(0)
            state = State.PI_TARGET
        } else {
            comment.setLength(0)
            comment.append('?')
            state = State.BOGUS_COMMENT
        }
    }

    private fun piTargetState() {
        while (p < n) {
            val c = s[p]
            when {
                isHtmlWhitespace(c) || c == '?' || c == '>' -> {
                    val target = piTarget.toString()
                    if (asciiEqualsIgnoringCase(target, "xml") || asciiEqualsIgnoringCase(target, "xml-stylesheet")) {
                        toBogusComment()
                    } else {
                        state = State.AFTER_PI_TARGET
                    }
                    return
                }
                isAsciiAlnum(c) || c == '-' || c == '_' -> { piTarget.append(c); p++ }
                else -> { toBogusComment(); return }
            }
        }
        eof() // a processing instruction the input ends in is dropped
    }

    /** A processing instruction made a bogus comment: `?`, its target so far, then the rest of a bogus comment. */
    private fun toBogusComment() {
        comment.setLength(0)
        comment.append('?').append(piTarget)
        state = State.BOGUS_COMMENT
    }

    private fun piDataState() {
        while (p < n) {
            when (val c = s[p++]) {
                '?' -> { state = State.PI_QUESTION; return }
                '>' -> { emitPi(); state = State.DATA; return }
                else -> piData.append(c) // a U+0000 kept, as lexbor keeps it
            }
        }
        eof()
    }

    private fun piQuestion() {
        if (p >= n) { eof(); return }
        if (s[p] == '>') {
            p++
            emitPi()
            state = State.DATA
        } else {
            piData.append('?')
            state = State.PI_DATA
        }
    }

    private fun emitPi() {
        flushText()
        out.addLast(Token.ProcessingInstruction(piTarget.toString(), piData.toString()))
    }
}
