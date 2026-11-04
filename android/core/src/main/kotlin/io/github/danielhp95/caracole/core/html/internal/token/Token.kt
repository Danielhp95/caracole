package io.github.danielhp95.caracole.core.html.internal.token

/**
 * A token of core.html's tokenizer: the WHATWG tokenizer's (HTML §13.2.5) as lexbor makes them, the one selectolax
 * reads pages with (docs/superpowers/specs/2026-11-03-html-parsing.md, "The tokenizer").
 */
sealed class Token {
    /** `<!DOCTYPE name PUBLIC "…" "…">`: [name] ASCII-lowercased, null when none was written; [publicId] and
     * [systemId] null when missing; [mode] the document's mode it sets in the initial insertion mode. */
    class Doctype(val name: String?, val publicId: String?, val systemId: String?, val forceQuirks: Boolean) : Token() {
        val mode: CompatMode get() = CompatMode.of(this)
        override fun toString() = "Doctype($name, $publicId, $systemId, forceQuirks=$forceQuirks)"
    }

    /** A start tag: its name ASCII-lowercased, its [attributes] in source order (the first of duplicates kept), and
     * whether it ended with `/>`. */
    class StartTag(val name: String, val attributes: List<Attribute>, val selfClosing: Boolean) : Token() {
        override fun toString() = "StartTag($name, $attributes${if (selfClosing) ", /" else ""})"
    }

    /** An end tag: its name ASCII-lowercased (the attributes an end tag is written with are dropped). */
    class EndTag(val name: String) : Token() {
        override fun toString() = "EndTag($name)"
    }

    /** A comment, or a bogus one (`<!x>`, `</ x>`, `<?xml …?>`): its data as the tokenizer collected it. */
    class Comment(val data: String) : Token() {
        override fun toString() = "Comment($data)"
    }

    /** `<?target data?>` (or `<?target data>`), as lexbor reads it: [target] as written, [data] after the whitespace
     * that follows it, up to `?>`, a U+0000 in it kept. A target `xml` or `xml-stylesheet` (in any case), or one with
     * a character that is no ASCII alphanumeric, `-` or `_`, makes a bogus comment instead. */
    class ProcessingInstruction(val target: String, val data: String) : Token() {
        override fun toString() = "ProcessingInstruction($target, $data)"
    }

    /** A run of characters between two other tokens, cut where it changes between ASCII whitespace, U+0000 and
     * anything else ([kind]), so that each insertion mode's rule for whitespace and for NUL applies to a whole token.
     * A U+0000 reaches the tree only from the data state and a CDATA section: the other states replace it. */
    class Characters(val data: String, val kind: CharKind) : Token() {
        override fun toString() = "Characters($kind, ${data.length})"
    }

    object EndOfFile : Token() {
        override fun toString() = "EndOfFile"
    }
}

/** An attribute of a start tag: its name ASCII-lowercased, and its value, null where none was written (`<a href>`,
 * and `<a href=>`, whose `=` meets no value), as lexbor keeps it; `<a href="">`'s is "". */
data class Attribute(val name: String, val value: String?)

/** What a [Token.Characters] holds: ASCII whitespace (tab, LF, FF, CR and space), U+0000, or anything else. */
enum class CharKind { WHITESPACE, NULL, OTHER }

/** The content the tree builder switches the tokenizer to after a start tag (WHATWG HTML §13.2.6.2). */
enum class Content { DATA, RCDATA, RAWTEXT, SCRIPT_DATA, PLAINTEXT }

/** A document's mode, from its doctype (WHATWG HTML §13.2.6.4.1, the initial insertion mode), as lexbor decides it. */
enum class CompatMode {
    NO_QUIRKS, LIMITED_QUIRKS, QUIRKS;

    companion object {
        /**
         * The mode [doctype] sets. As lexbor (tree/insertion_mode/initial.c) does, an empty public or system
         * identifier counts as a missing one: `PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" ""` is quirks mode,
         * where the spec makes it limited quirks.
         */
        fun of(doctype: Token.Doctype): CompatMode {
            if (doctype.forceQuirks || doctype.name != "html") return QUIRKS
            val public = doctype.publicId.orEmpty()
            val system = doctype.systemId.orEmpty()
            if (public.isNotEmpty()) {
                if (PUBLIC_IS.any { asciiEqualsIgnoringCase(public, it) }) return QUIRKS
                if (PUBLIC_STARTS.any { asciiStartsIgnoringCase(public, it) }) return QUIRKS
            }
            if (system.isNotEmpty() && SYSTEM_IS.any { asciiEqualsIgnoringCase(system, it) }) return QUIRKS
            if (public.isNotEmpty() && system.isEmpty() && NO_SYSTEM_STARTS.any { asciiStartsIgnoringCase(public, it) }) {
                return QUIRKS
            }
            if (public.isNotEmpty()) {
                if (system.isNotEmpty() && NO_SYSTEM_STARTS.any { asciiStartsIgnoringCase(public, it) }) {
                    return LIMITED_QUIRKS
                }
                if (LIMITED_STARTS.any { asciiStartsIgnoringCase(public, it) }) return LIMITED_QUIRKS
            }
            return NO_QUIRKS
        }

        private val PUBLIC_IS = listOf("-//W3O//DTD W3 HTML Strict 3.0//EN//", "-/W3C/DTD HTML 4.0 Transitional/EN", "HTML")
        private val SYSTEM_IS = listOf("http://www.ibm.com/data/dtd/v11/ibmxhtml1-transitional.dtd")
        private val PUBLIC_STARTS = listOf(
            "+//Silmaril//dtd html Pro v0r11 19970101//", "-//AS//DTD HTML 3.0 asWedit + extensions//",
            "-//AdvaSoft Ltd//DTD HTML 3.0 asWedit + extensions//", "-//IETF//DTD HTML 2.0 Level 1//",
            "-//IETF//DTD HTML 2.0 Level 2//", "-//IETF//DTD HTML 2.0 Strict Level 1//",
            "-//IETF//DTD HTML 2.0 Strict Level 2//", "-//IETF//DTD HTML 2.0 Strict//", "-//IETF//DTD HTML 2.0//",
            "-//IETF//DTD HTML 2.1E//", "-//IETF//DTD HTML 3.0//", "-//IETF//DTD HTML 3.2 Final//",
            "-//IETF//DTD HTML 3.2//", "-//IETF//DTD HTML 3//", "-//IETF//DTD HTML Level 0//",
            "-//IETF//DTD HTML Level 1//", "-//IETF//DTD HTML Level 2//", "-//IETF//DTD HTML Level 3//",
            "-//IETF//DTD HTML Strict Level 0//", "-//IETF//DTD HTML Strict Level 1//",
            "-//IETF//DTD HTML Strict Level 2//", "-//IETF//DTD HTML Strict Level 3//", "-//IETF//DTD HTML Strict//",
            "-//IETF//DTD HTML//", "-//Metrius//DTD Metrius Presentational//",
            "-//Microsoft//DTD Internet Explorer 2.0 HTML Strict//", "-//Microsoft//DTD Internet Explorer 2.0 HTML//",
            "-//Microsoft//DTD Internet Explorer 2.0 Tables//", "-//Microsoft//DTD Internet Explorer 3.0 HTML Strict//",
            "-//Microsoft//DTD Internet Explorer 3.0 HTML//", "-//Microsoft//DTD Internet Explorer 3.0 Tables//",
            "-//Netscape Comm. Corp.//DTD HTML//", "-//Netscape Comm. Corp.//DTD Strict HTML//",
            "-//O'Reilly and Associates//DTD HTML 2.0//", "-//O'Reilly and Associates//DTD HTML Extended 1.0//",
            "-//O'Reilly and Associates//DTD HTML Extended Relaxed 1.0//", "-//SQ//DTD HTML 2.0 HoTMetaL + extensions//",
            "-//SoftQuad Software//DTD HoTMetaL PRO 6.0::19990601::extensions to HTML 4.0//",
            "-//SoftQuad//DTD HoTMetaL PRO 4.0::19971010::extensions to HTML 4.0//",
            "-//Spyglass//DTD HTML 2.0 Extended//", "-//Sun Microsystems Corp.//DTD HotJava HTML//",
            "-//Sun Microsystems Corp.//DTD HotJava Strict HTML//", "-//W3C//DTD HTML 3 1995-03-24//",
            "-//W3C//DTD HTML 3.2 Draft//", "-//W3C//DTD HTML 3.2 Final//", "-//W3C//DTD HTML 3.2//",
            "-//W3C//DTD HTML 3.2S Draft//", "-//W3C//DTD HTML 4.0 Frameset//", "-//W3C//DTD HTML 4.0 Transitional//",
            "-//W3C//DTD HTML Experimental 19960712//", "-//W3C//DTD HTML Experimental 970421//",
            "-//W3C//DTD W3 HTML//", "-//W3O//DTD W3 HTML 3.0//", "-//WebTechs//DTD Mozilla HTML 2.0//",
            "-//WebTechs//DTD Mozilla HTML//",
        )
        private val NO_SYSTEM_STARTS = listOf("-//W3C//DTD HTML 4.01 Frameset//", "-//W3C//DTD HTML 4.01 Transitional//")
        private val LIMITED_STARTS = listOf("-//W3C//DTD XHTML 1.0 Frameset//", "-//W3C//DTD XHTML 1.0 Transitional//")
    }
}

internal fun asciiLowerChar(c: Char): Char = if (c in 'A'..'Z') c + 32 else c

internal fun asciiEqualsIgnoringCase(a: String, b: String): Boolean =
    a.length == b.length && a.indices.all { asciiLowerChar(a[it]) == asciiLowerChar(b[it]) }

internal fun asciiStartsIgnoringCase(s: String, prefix: String): Boolean =
    s.length >= prefix.length && prefix.indices.all { asciiLowerChar(s[it]) == asciiLowerChar(prefix[it]) }
