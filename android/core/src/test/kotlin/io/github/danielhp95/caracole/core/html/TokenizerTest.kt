package io.github.danielhp95.caracole.core.html

import io.github.danielhp95.caracole.core.html.internal.token.Attribute
import io.github.danielhp95.caracole.core.html.internal.token.CharKind
import io.github.danielhp95.caracole.core.html.internal.token.CompatMode
import io.github.danielhp95.caracole.core.html.internal.token.Content
import io.github.danielhp95.caracole.core.html.internal.token.Preprocess
import io.github.danielhp95.caracole.core.html.internal.token.Token
import io.github.danielhp95.caracole.core.html.internal.token.Tokenizer
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.HtmlReplay
import io.github.danielhp95.caracole.core.testing.replays.TokensTree
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** core.html's preprocessing and tokenizer: lexbor's tokens (docs/superpowers/specs/2026-11-03-html-parsing.md). */
class TokenizerTest {
    /** Every token as a short text: the characters joined between two other tokens. */
    private fun tokens(html: String, foreign: Boolean = false): List<String> {
        val tokenizer = Tokenizer(html)
        tokenizer.foreignContent = { foreign }
        val out = ArrayList<String>()
        val text = StringBuilder()
        while (true) {
            val token = tokenizer.next()
            if (token is Token.Characters) { text.append(token.data); continue }
            if (text.isNotEmpty()) { out += "#" + text; text.setLength(0) }
            when (token) {
                is Token.StartTag -> {
                    out += "<" + token.name + token.attributes.joinToString("") { " ${it.name}=${it.value}" } +
                        (if (token.selfClosing) " /" else "") + ">"
                    Tokenizer.contentFor(token.name)?.let { if (!foreign) tokenizer.switchTo(it) }
                }
                is Token.EndTag -> out += "</" + token.name + ">"
                is Token.Comment -> out += "!" + token.data
                is Token.ProcessingInstruction -> out += "?" + token.target + "|" + token.data
                is Token.Doctype -> out += "D" + token.name + "|" + token.publicId + "|" + token.systemId +
                    (if (token.forceQuirks) "|quirks" else "")
                else -> { out += "EOF"; return out }
            }
        }
    }

    @Test fun newlinesAreLineFeedsBeforeTokenizing() {
        assertEquals("a\nb\nc\n\nd", Preprocess.text("a\r\nb\rc\r\r\nd"))
        assertEquals("x", Preprocess.text("x"))
        assertEquals("�b", Preprocess.bytes(byteArrayOf(0xFF.toByte(), 'b'.code.toByte())))
        assertEquals(listOf("<pre>", "#\nA\nB\nC", "</pre>", "EOF"), tokens("<pre>\nA\r\nB\rC</pre>"))
    }

    @Test fun charactersAreCutByKind() {
        val kinds = ArrayList<Pair<CharKind, String>>()
        val tokenizer = Tokenizer(" a\u0000b \n<p>")
        while (true) {
            val token = tokenizer.next()
            if (token is Token.Characters) kinds += token.kind to token.data else break
        }
        assertEquals(listOf(CharKind.WHITESPACE to " ", CharKind.OTHER to "a", CharKind.NULL to "\u0000",
                            CharKind.OTHER to "b", CharKind.WHITESPACE to " \n"), kinds)
    }

    @Test fun referencesInTextTakeTheLongestName() {
        assertEquals(listOf("<p>", "#&頭 &x ¬it; € � a b", "</p>", "EOF"),
                     tokens("<p>&amp頭 &ampx &notit; &#x80; &#0; a&nbsp;b</p>"))
        assertEquals(listOf("#&&&& ¬in ∉ & &# &#x &#; A A", "EOF"), tokens("&amp;&AMP;&AMP&amp &notin &notin; & &# &#x &#; &#65 &#x41;"))
        assertEquals(listOf("#≂̸ &hellip …", "EOF"), tokens("&NotEqualTilde; &hellip &hellip;"))
    }

    @Test fun referencesInAttributesKeepTheHistoricalRule() {
        assertEquals(listOf("<a title=&ampx &amp=y &頭>", "#x", "</a>", "EOF"), tokens("<a title='&ampx &amp=y &amp頭'>x</a>"))
        assertEquals(listOf("<a href=?a=1&copy=2®=3&para4>", "EOF"), tokens("<a href=?a=1&copy=2&reg;=3&para4>"))
    }

    @Test fun numericReferencesFollowTheSpecsTable() {
        assertEquals(listOf("#€‚ƒ\u0081Ÿ���﷐\r\u001F", "EOF"),
                     tokens("&#x80;&#x82;&#x83;&#x81;&#x9F;&#xD800;&#x110000;&#99999999999;&#xFDD0;&#13;&#x1F;"))
        assertEquals(listOf("#𝄞", "EOF"), tokens("&#x1D11E;"))
    }

    @Test fun attributesKeepTheFirstOfDuplicatesAndANullForNoValue() {
        val tag = Tokenizer("<a HREF=X Href=y href title='' b= c=>").next() as Token.StartTag
        assertEquals(listOf(Attribute("href", "X"), Attribute("title", ""), Attribute("b", "c=")), tag.attributes)
        val bare = Tokenizer("<a b c=>").next() as Token.StartTag
        assertEquals(listOf(Attribute("b", null), Attribute("c", null)), bare.attributes)
        assertEquals(listOf("<a \"x\"=1 'y'=2 <z=3 =w=null>", "EOF"), tokens("<a \"x\"=1 'y'=2 <z=3 =w>"))
        assertEquals(listOf("<a b=null c=d />", "EOF"), tokens("<a/b/c=d />"))
        assertEquals(listOf("<br />", "<p>", "</p>", "EOF"), tokens("<br/><p></p x=y>"))
    }

    @Test fun tagNamesAreFoldedByAsciiAlone() {
        assertEquals(listOf("<div class=A>", "#<ÄB>", "</div>", "EOF"), tokens("<DIV CLASS=A><ÄB></DiV>"))
        assertEquals(listOf("<p�q a�b=c�>", "EOF"), tokens("<p\u0000q a\u0000b=c\u0000>"))
    }

    @Test fun commentsAndBogusComments() {
        assertEquals(listOf("!a", "!", "!", "!", "! a -- b ", "!a", "#b-->", "EOF"),
                     tokens("<!--a--><!----><!---><!--><!-- a -- b --><!--a--!>b-->"))
        assertEquals(listOf("!x", "!-x", "! x", "#y", "!", "EOF"), tokens("<!x><!-x></ x>y</><!><?php x ?"))
        assertEquals(listOf("!<!--x", "!a--!->", "EOF"), tokens("<!--<!--x--><!--a--!->"))
        assertEquals(listOf("!x", "EOF"), tokens("<!--x--"))
        assertEquals(listOf("!", "EOF"), tokens("<![CD"))
        assertEquals(listOf("!DOCT", "EOF"), tokens("<!DOCT"))
    }

    @Test fun processingInstructionsAsLexborReadsThem() {
        assertEquals(listOf("?x|y", "?x|", "?x|y z ", "?x|y? z", "?_a-b|c", "EOF"),
                     tokens("<?x y?><?x?><?x  y z ?><?x y? z?><?_a-b c>"))
        assertEquals(listOf("!?xml version='1.0'?", "!?XML-stylesheet x?", "!?x.y?", "!?1?", "!? x?", "EOF"),
                     tokens("<?xml version='1.0'?><?XML-stylesheet x?><?x.y?><?1?><? x?>"))
        assertEquals(listOf("#a", "EOF"), tokens("a<?x y"))
        assertEquals(listOf("#a", "EOF"), tokens("a<?"))
        assertEquals(listOf("?x|a\u0000b", "EOF"), tokens("<?x a\u0000b?>"))
    }

    @Test fun cdataIsASectionOnlyInForeignContent() {
        assertEquals(listOf("![CDATA[x]]", "EOF"), tokens("<![CDATA[x]]>"))
        assertEquals(listOf("#x<ya]b]]c]", "EOF"), tokens("<![CDATA[x<y]]><![CDATA[a]b]]c]]]>", foreign = true))
        assertEquals(listOf("#x", "EOF"), tokens("<![CDATA[x", foreign = true))
    }

    @Test fun rcdataRawtextScriptAndPlaintext() {
        assertEquals(listOf("<title>", "#a&b<i>c</i>", "</title>", "<p>", "EOF"), tokens("<title>a&amp;b<i>c</i></title><p>"))
        assertEquals(listOf("<title>", "#a</titlex>b", "</title>", "EOF"), tokens("<title>a</titlex>b</TITLE y=z>"))
        assertEquals(listOf("<style>", "#a&amp;<b>", "</style>", "EOF"), tokens("<style>a&amp;<b></style>"))
        assertEquals(listOf("<script>", "#a<!--b<script>c</script>d", "</script>", "#e", "EOF"),
                     tokens("<script>a<!--b<script>c</script>d</script>e"))
        assertEquals(listOf("<script>", "#<!--x-->", "</script>", "EOF"), tokens("<script><!--x--></script>"))
        assertEquals(listOf("<plaintext>", "#</plaintext>x&amp;", "EOF"), tokens("<plaintext></plaintext>x&amp;"))
        assertEquals(listOf("<textarea>", "#�", "</textarea>", "EOF"), tokens("<textarea>\u0000</textarea>"))
        assertNull(Tokenizer.contentFor("noscript"))
        assertEquals(Content.RAWTEXT, Tokenizer.contentFor("noscript", scripting = true))
    }

    @Test fun aTagTheInputEndsInIsDropped() {
        assertEquals(listOf("#a", "EOF"), tokens("a<b c='d"))
        assertEquals(listOf("#a<", "EOF"), tokens("a<"))
        assertEquals(listOf("#a</", "EOF"), tokens("a</"))
    }

    @Test fun doctypesAndTheirModes() {
        fun doctype(html: String) = Tokenizer(html).next() as Token.Doctype
        assertEquals(listOf("Dhtml|null|null", "EOF"), tokens("<!DOCTYPE HTML>"))
        assertEquals(CompatMode.NO_QUIRKS, doctype("<!doctype html>").mode)
        assertEquals(CompatMode.QUIRKS, doctype("<!DOCTYPE html5>").mode)
        assertEquals(CompatMode.QUIRKS, doctype("<!DOCTYPE>").mode)
        assertEquals(CompatMode.QUIRKS, doctype("<!DOCTYPE html PUBLIC \"-//W3C//DTD HTML 4.01 Transitional//EN\">").mode)
        assertEquals(CompatMode.LIMITED_QUIRKS,
                     doctype("<!DOCTYPE html PUBLIC \"-//W3C//DTD HTML 4.01 Transitional//EN\" \"http://x\">").mode)
        // lexbor reads an empty system identifier as a missing one
        assertEquals(CompatMode.QUIRKS, doctype("<!DOCTYPE html PUBLIC \"-//W3C//DTD HTML 4.01 Transitional//EN\" \"\">").mode)
        assertEquals(CompatMode.LIMITED_QUIRKS, doctype("<!DOCTYPE html PUBLIC '-//W3C//DTD XHTML 1.0 Transitional//EN'>").mode)
        assertEquals(CompatMode.QUIRKS, doctype("<!DOCTYPE html SYSTEM 'HTTP://WWW.IBM.COM/DATA/DTD/V11/IBMXHTML1-TRANSITIONAL.DTD'>").mode)
        assertEquals(CompatMode.NO_QUIRKS, doctype("<!DOCTYPE html PUBLIC 'x' 'y' z>").mode)
        assertTrue(doctype("<!DOCTYPE html PUBLIC 'a>b'>").forceQuirks)
        assertEquals("h�tml", doctype("<!DOCTYPE h\u0000tml>").name)
    }

    @Test fun theTokensTreeReadsTheProbesPages() {
        val pre = TokensTree.read("<div id=t_body><pre>\nA\r\nB\rC</pre></div>")
        assertEquals("A\nB\nC", pre.text)
        assertTrue(pre.quirks)
        val script = TokensTree.read("<pre><script>var x='<b>';</script>T<br>U<!--c-->V</pre>")
        assertEquals("var x='<b>';TUV", script.text)
        assertEquals(listOf("c"), script.comments)
        val body = TokensTree.read("<!doctype html><html a=1><body b=2><html a=3 c=4><body b=5 d=6><p>x")
        assertEquals(listOf("html" to listOf(Attribute("a", "1"), Attribute("c", "4")),
                            "body" to listOf(Attribute("b", "2"), Attribute("d", "6"))), body.attrs)
        assertEquals(false, body.quirks)
    }

    @Test fun everyRecordOfTheTokensVectorsIsLexbors() {
        HtmlReplay.replay(Misses("html"))
    }
}
