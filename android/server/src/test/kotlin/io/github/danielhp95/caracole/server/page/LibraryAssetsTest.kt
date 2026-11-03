package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.testing.Corpus
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** library_assets/ as the phone's page inlines them: caracole's files, in library_page.py's order. */
class LibraryAssetsTest {
    private val assets = LibraryAssets.load()

    /** caracole's library_assets/, beside the conformance vectors in the checkout. */
    private val source = File(System.getProperty("caracole.conformance")).resolve("../../../src/caracole/library_assets")

    private val order = Json.parseToJsonElement(
        javaClass.classLoader.getResourceAsStream(LibraryAssets.ORDER)!!.use { it.readBytes().toString(Charsets.UTF_8) },
    ).jsonObject

    private fun names(list: String) = order.getValue(list).jsonArray.map { it.jsonPrimitive.content }

    @Test
    fun `the order is library_assets_json's, which is library_page_py's`() {
        assertEquals(names("SCRIPTS"), assets.scriptNames)
        assertEquals(names("STYLESHEETS"), assets.styleNames)
        assertEquals(names("TEMPLATES"), assets.templateNames)
        assertEquals("drawn.js", assets.scriptNames.last(), "drawn.js comes last")
        assertTrue(assets.styleNames.indexOf("sync.css") == assets.styleNames.indexOf("sites.css") + 1)
        assertTrue(assets.scriptNames.indexOf("sync.js") == assets.scriptNames.indexOf("sites.js") + 1)
        assertEquals(listOf("sync-tab.html", "sync-panel.html"), assets.templateNames.takeLast(2))
    }

    @Test
    fun `the script and the style are caracole's files concatenated, as their bytes say`() {
        assertEquals(assets.scriptNames.joinToString("") { File(source, it).readText(Charsets.UTF_8) }, assets.scripts)
        assertEquals(assets.styleNames.joinToString("") { File(source, it).readText(Charsets.UTF_8) }, assets.styles)
        for (name in assets.templateNames) assertEquals(File(source, name).readText(Charsets.UTF_8), assets.template(name), name)
        assertTrue("__CSP__" in assets.template("head.html") && "__REQUESTED__" in assets.template("body.html"))
    }

    @Test
    fun `a name the page has no template of is refused`() {
        assertFailsWith<IllegalArgumentException> { assets.template("library.js") }
        assertFailsWith<IllegalArgumentException> { assets.template("nothing.html") }
    }

    @Test
    fun `the hashes the page's policy allows its script and its style by are Python's`() {
        waitingOnServerShell()
        val vector = Corpus.json("web/library_page.json")
        assertEquals(vector.getValue("script_hash").jsonPrimitive.content, assets.scriptHash)
        assertEquals(vector.getValue("style_hash").jsonPrimitive.content, assets.styleHash)
    }
}
