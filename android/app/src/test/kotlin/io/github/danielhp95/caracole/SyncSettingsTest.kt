package io.github.danielhp95.caracole

import org.junit.Test
import org.w3c.dom.Element
import java.io.File
import javax.xml.parsers.DocumentBuilderFactory
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Settings' sync rows (the sync redesign's Task 37): the computer's address with Test, Export, Import a file and Sync
 * on Wi-Fi by itself, Sync now and Import indexes gone, and no item's text ending in "…"; the address the sheet offers
 * and remembers is the one Settings keeps.
 */
class SyncSettingsTest {
    private val res: File = listOf(File("src/main/res"), File("app/src/main/res")).first { it.isDirectory }
    private val android = "http://schemas.android.com/apk/res/android"

    /** strings.xml's strings by name, as Android reads them (`\'` an apostrophe). */
    private val strings: Map<String, String> by lazy {
        val doc = parse(File(res, "values/strings.xml"))
        val found = HashMap<String, String>()
        val list = doc.getElementsByTagName("string")
        for (i in 0 until list.length) {
            val e = list.item(i) as Element
            found[e.getAttribute("name")] = e.textContent.replace("\\'", "'").replace("\\\"", "\"")
        }
        found
    }

    private fun parse(file: File) = DocumentBuilderFactory.newInstance().apply { isNamespaceAware = true }
        .newDocumentBuilder().parse(file)

    /** Every element's [attribute] (android:text, android:title) in [file], resolved: `@string/x` as strings.xml has it. */
    private fun texts(file: File, attribute: String): List<String> {
        val doc = parse(file)
        val all = doc.getElementsByTagName("*")
        return (0 until all.length).mapNotNull { i ->
            val value = (all.item(i) as Element).getAttributeNS(android, attribute).ifEmpty { null } ?: return@mapNotNull null
            if (value.startsWith("@string/")) {
                strings[value.removePrefix("@string/")] ?: error("${file.name}: no string ${value.removePrefix("@string/")}")
            } else value
        }
    }

    /** Every element's android:id in [file] ("address", "test"...). */
    private fun ids(file: File): Set<String> {
        val doc = parse(file)
        val all = doc.getElementsByTagName("*")
        return (0 until all.length).mapNotNull { i ->
            (all.item(i) as Element).getAttributeNS(android, "id").ifEmpty { null }?.substringAfter('/')
        }.toSet()
    }

    @Test
    fun `no settings item text ends in an ellipsis`() {
        val settings = texts(File(res, "layout/activity_settings.xml"), "text")
        val menu = texts(File(res, "menu/main.xml"), "title")
        assertTrue(settings.isNotEmpty() && menu.isNotEmpty())
        for (text in settings + menu) {
            assertTrue(!text.trimEnd().endsWith("…") && !text.trimEnd().endsWith("..."), "ends in an ellipsis: $text")
        }
        assertEquals(listOf("Library", "Settings"), menu, "the menu keeps Library and Settings")
    }

    @Test
    fun `settings keep the address and Test, and gain Export and Import a file`() {
        val layout = File(res, "layout/activity_settings.xml")
        val rows = ids(layout)
        for (kept in listOf("address", "test", "test_result", "wifi", "export", "import_file", "backups")) {
            assertTrue(kept in rows, "Settings has $kept")
        }
        for (gone in listOf("sync", "last_sync", "import_computer", "last_import")) {
            assertTrue(gone !in rows, "Settings' $gone is gone")
        }
        val texts = texts(layout, "text")
        assertTrue("Export" in texts && "Import a file" in texts, "$texts")
        assertTrue("Sync on Wi-Fi by itself" in texts)
        for (gone in listOf("sync_now", "sync_with_computer", "import_label", "import_computer", "never_imported",
                            "last_sync", "never_synced")) {
            assertNull(strings[gone], "the string $gone is gone")
        }
    }

    @Test
    fun `the sheet offers the address Settings keeps, and none while none is typed`() {
        val prefs = MemoryPreferences()
        val sync = SavedAddress(Settings(prefs))
        assertNull(sync.address)
        Settings(prefs).server = "   "
        assertNull(sync.address, "blank is none")
        Settings(prefs).server = "192.168.1.20:8737"
        assertEquals("192.168.1.20:8737", sync.address, "as typed: the sheet reads it as the computer does")
    }

    @Test
    fun `the address the sheet compared with is the one Settings keeps, so Test and Sync on Wi-Fi use it too`() {
        val prefs = MemoryPreferences()
        val settings = Settings(prefs)
        settings.server = "http://192.168.1.5:8737"
        settings.syncOnWifi = true
        SavedAddress(settings).remember("http://192.168.1.20:8737")
        assertEquals("http://192.168.1.20:8737", Settings(prefs).server)
        assertEquals("http://192.168.1.20:8737", SavedAddress(Settings(prefs)).address)
        assertEquals(true, Settings(prefs).syncOnWifi, "the other settings as they were")
    }
}
