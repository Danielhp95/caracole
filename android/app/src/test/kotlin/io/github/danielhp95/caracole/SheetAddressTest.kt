package io.github.danielhp95.caracole

import org.junit.Test
import kotlin.test.assertEquals

/** The sync sheet's addresses (the sync redesign's §3.6): the library page's, with the word of the flow it opens at. */
class SheetAddressTest {
    @Test
    fun `each sheet's address is the library page's with its word`() {
        val library = "http://127.0.0.1:8738/"
        assertEquals("http://127.0.0.1:8738/#sheet=sync", SheetAddress.of(library, "sync"))
        assertEquals("http://127.0.0.1:8738/#sheet=export", SheetAddress.of(library, "export"))
        assertEquals("http://127.0.0.1:8738/#sheet=import", SheetAddress.of(library, "import"))
        assertEquals(listOf("sync", "export", "import"), SheetAddress.SHEETS)
    }

    @Test
    fun `an unknown word gives the library page alone`() {
        val library = "http://127.0.0.1:8738/"
        assertEquals(library, SheetAddress.of(library, "compare"))
        assertEquals(library, SheetAddress.of(library, ""))
        assertEquals(library, SheetAddress.of(library, "sync&tab=sites"), "a word is the whole of it")
        assertEquals(library, SheetAddress.of(library, null))
    }

    @Test
    fun `the library page's own address keeps no fragment of its own`() {
        assertEquals("http://127.0.0.1:8738/#sheet=sync", SheetAddress.of("http://127.0.0.1:8738/#tab=songbooks", "sync"))
        assertEquals("http://127.0.0.1:8738/", SheetAddress.of("http://127.0.0.1:8738/#tab=songbooks", "nothing"))
    }
}
