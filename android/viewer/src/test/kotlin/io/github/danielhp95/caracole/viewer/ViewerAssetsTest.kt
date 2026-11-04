package io.github.danielhp95.caracole.viewer

import io.github.danielhp95.caracole.core.testing.ForbiddenApis
import org.junit.Test
import java.io.File
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/** :viewer's build carries viewer/'s assets byte for byte, none with a CR, and its code asks the JDK nothing about
 * text. */
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

    @Test fun viewerNeverAsksTheJdkOrIcuAboutText() {
        val found = ForbiddenApis.check(File("src/main/kotlin"))
        assertTrue(found.isEmpty(), "forbidden in :viewer:\n" + found.joinToString("\n"))
    }
}
