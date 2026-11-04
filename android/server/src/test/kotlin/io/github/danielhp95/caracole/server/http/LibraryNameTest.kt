package io.github.danielhp95.caracole.server.http

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.server.routes.Stubs
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.replays.LibraryNameReplay
import io.github.danielhp95.caracole.server.testing.text
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** library_name.LibraryName on the phone (vectors/web/library_name.jsonl), and the name the phone's pages give: the
 * computer's, read for each page, with the phone's badge; caracole and the badge alone before a sync gives one. */
class LibraryNameTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun everyRecordIsAnsweredAsLibraryNameAnswersIt() {
        val misses = Misses("web/library_name.jsonl")
        LibraryNameReplay.replay(misses)
        misses.assertNone()
    }

    @Test fun thePhoneWithNoNameSaysCaracoleAndItsBadgeOnce() {
        val phone = LibraryName.phone(null)
        assertEquals(LibraryName("", "Phone"), phone)
        assertEquals("Phone · caracole", phone.title())
        assertEquals("Phone · Not found · caracole", phone.title("Not found"))
        assertEquals("<p class=\"libname\"><span class=\"name\"></span> " +
                         "<span class=\"scratch\" title=\"Not your usual library\">Phone</span></p>", phone.markup("p"))
        assertEquals("Phone · caracole · Music", LibraryName.phone("Music").title())
    }

    @Test fun theAppsPagesNameTheLibraryItsConfigGivesNow() {
        var name = ""
        TestApp(File(tmp.root, "files")).use { test ->
            val app = App(AppConfig("tok", "secret", libraryName = { name }), emptyList(), Stubs(), test.files)
            val before = app.message(404, "Not found", "Nothing here.").text
            assertTrue("<title>Phone · Not found · caracole</title>" in before, before)
            assertFalse("Phone · caracole · Phone" in before)
            assertTrue("<span class=\"libname\"><span class=\"name\"></span> <span class=\"scratch\"" in before)

            name = "Dani's <songs>"
            val after = app.message(404, "Not found", "Nothing here.").text
            assertTrue("<title>Phone · Not found · caracole · Dani&#x27;s &lt;songs&gt;</title>" in after, after)
            assertTrue("<span class=\"name\">Dani&#x27;s &lt;songs&gt;</span>" in after)
            assertEquals("Phone · Gone · caracole · Dani's <songs>", test.files.name().title("Gone"))
        }
    }
}
