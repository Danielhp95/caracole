package io.github.danielhp95.caracole.core.html

import org.junit.Test
import kotlin.test.assertEquals

/** core.html's document says its mode (lanes html-tokenizer and html-tree parse it). */
class HtmlDocTest {
    @Test fun aDocumentSaysItsMode() {
        assertEquals(true, HtmlDoc(quirks = true).quirks)
    }
}
