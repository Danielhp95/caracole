package io.github.danielhp95.caracole.viewer

import io.github.danielhp95.caracole.core.testing.ForbiddenApis
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import java.io.File
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertSame
import kotlin.test.assertTrue

/** :viewer's build carries viewer/'s assets byte for byte, none with a CR; ViewerAssets reads them as Python's
 * read_text does and names each page's; ViewerData reads each module's data; and :viewer's code asks the JDK nothing
 * about text. */
class ViewerAssetsTest {
    private val source = File(System.getProperty("caracole.conformance")).resolve("../../../src/caracole/viewer")
    private val names = source.listFiles()!!.map { it.name }.filter {
        it.endsWith(".js") || it.endsWith(".css") || (it.startsWith("voicings") && it.endsWith(".json")) ||
            it == "LICENSE-chords-db"
    }.sorted()

    @Test fun everyAssetIsOnTheClasspathByteForByteAndNoneHoldsACr() {
        assertTrue("viewer.js" in names && "voicings.json" in names, names.toString())
        for (name in names) {
            val copied = assertNotNull(Viewer.asset(name), name)
            assertContentEquals(File(source, name).readBytes(), copied, name)
            assertEquals(-1, copied.indexOf('\r'.code.toByte()), "$name holds a CR")
        }
        assertEquals(null, Viewer.asset("viewer.py"))
    }

    @Test fun anAssetsTextIsItsFileReadAsUtf8AndKept() {
        for (name in names) {
            assertTrue(ViewerAssets.isAsset(name), name)
            assertEquals(File(source, name).readText(Charsets.UTF_8), ViewerAssets.text(name), name)
        }
        assertSame(ViewerAssets.text("viewer.js"), ViewerAssets.text("viewer.js"))
        for (name in listOf("viewer.py", "theory.json", "../viewer.js", "a/viewer.js", "", ".js", "harmony.json")) {
            assertFalse(ViewerAssets.isAsset(name), name)
            assertFailsWith<IllegalArgumentException>(name) { ViewerAssets.text(name) }
        }
        assertFailsWith<IllegalStateException> { ViewerAssets.text("nothing-here.js") }
    }

    @Test fun eachPageInlinesFilesViewerHas() {
        for (page in ViewerAssets.Page.entries) {
            assertTrue(page.styles.isNotEmpty() && page.scripts.isNotEmpty(), page.name)
            assertTrue((page.styles + page.scripts).all { it in names }, page.name)
            assertEquals(page.styles.map(ViewerAssets::text), ViewerAssets.styles(page))
            assertEquals(page.scripts.map(ViewerAssets::text), ViewerAssets.scripts(page))
        }
        assertEquals("viewer.js", ViewerAssets.Page.SHEET.scripts.last())
        assertEquals("harptab.js", ViewerAssets.Page.HARMONICA.scripts.last())
    }

    @Test fun textIsStrictUtf8WithPythonsNewlines() {
        assertEquals("a﻿é😀", ViewerAssets.strictUtf8("a﻿é😀".toByteArray(Charsets.UTF_8), "x"))
        for (bytes in listOf(byteArrayOf(0xC3.toByte()), byteArrayOf(0xED.toByte(), 0xA0.toByte(), 0x80.toByte()),
                             byteArrayOf(0xC0.toByte(), 0xAF.toByte()), byteArrayOf(0xFF.toByte()))) {
            assertFailsWith<IllegalStateException> { ViewerAssets.strictUtf8(bytes, "x") }
        }
        assertEquals("a\nb\nc\n\nd", ViewerAssets.universalNewlines("a\r\nb\rc\n\r\nd"))
    }

    @Test fun aModulesDataIsReadOnceFromTheClasspath() {
        val theory = ViewerData.table("theory")
        assertSame(theory, ViewerData.table("theory"))
        assertEquals(listOf("ionian", "dorian", "phrygian", "lydian", "mixolydian", "aeolian", "locrian"),
                     theory.getValue("MODES").jsonArray.map { it.jsonPrimitive.content })
        for (name in listOf("", "../theory", "Theory", "theory.json", "a/b", "voicings", "voicings_ukulele")) {
            assertFailsWith<IllegalArgumentException>(name) { ViewerData.table(name) }
        }
        assertFailsWith<IllegalStateException> { ViewerData.table("no_module_here") }
    }

    @Test fun viewerNeverAsksTheJdkOrIcuAboutText() {
        val found = ForbiddenApis.check(File("src/main/kotlin"))
        assertTrue(found.isEmpty(), "forbidden in :viewer:\n" + found.joinToString("\n"))
    }
}
