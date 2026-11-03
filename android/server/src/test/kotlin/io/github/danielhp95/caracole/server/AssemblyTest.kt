package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.routes.SyncSettings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

/** The phone assembles with every lane's part still neutral, and its build carries caracole's own page assets. */
class AssemblyTest {
    @get:Rule val tmp = TemporaryFolder()

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    @Test fun thePhoneAssemblesAndItsNeutralRoutesAnswer() {
        val scope = CoroutineScope(SupervisorJob())
        TestDb.fresh(tmp.root).use { database ->
            val phone = Phone(PhoneDeps(database, tmp.newFolder("library"), tmp.newFolder("state"), null, scope,
                                        NoAddress, secret = "s".repeat(64), csrf = "tok"))
            val search = phone.search.routes.single { it.path == "/api/search" }
            val answer = search.get!!.answer(Request("GET", "/api/search?q=caf%C3%A9", emptyMap(), ByteArray(0)))
            assertEquals(200, answer.status)
            assertEquals("""{"query":"café","library":[],"index":[],"short":true}""",
                         String((answer.body as Body.Bytes).bytes))
            assertEquals(emptyList(), phone.queue.snapshot())
        }
        scope.cancel()
    }

    @Test fun theLibraryAssetsAreOnTheClasspathByteForByte() {
        val source = File(System.getProperty("caracole.conformance")).resolve("../../../src/caracole/library_assets")
        val names = source.listFiles()!!.map { it.name }.filter { it.substringAfterLast('.') in setOf("js", "css", "html") }
        assert(names.isNotEmpty())
        for (name in names) {
            val copied = javaClass.getResourceAsStream("/caracole/library_assets/$name")
            assertNotNull(copied, name)
            assertContentEquals(File(source, name).readBytes(), copied.use { it.readBytes() }, name)
        }
    }
}
