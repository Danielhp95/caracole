package io.github.danielhp95.caracole.mirror

import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class ServerAddressTest {
    @Test
    fun `a missing scheme means http, and a path typed after the address is dropped`() {
        assertEquals("http://192.168.1.20:8737", ServerAddress.parse("192.168.1.20:8737").toString())
        assertEquals("http://192.168.1.20:8737", ServerAddress.parse("  http://192.168.1.20:8737/  ").toString())
        assertEquals("http://my-server:8737", ServerAddress.parse("HTTP://my-server:8737/index.html?x=1#y").toString())
        assertEquals("https://music.tail1234.ts.net", ServerAddress.parse("https://music.tail1234.ts.net").toString())
        assertEquals("http://[fd7a:115c::1]:8737", ServerAddress.parse("[fd7a:115c::1]:8737").toString())
    }

    @Test
    fun `an address the app can't use is refused in words`() {
        assertFailsWith<SyncError.NoAddress> { ServerAddress.parse("   ") }
        for (text in listOf("ftp://server", "http://", "http://user:pw@server:8737", "server name with spaces")) {
            assertFailsWith<SyncError.BadAddress>(text) { ServerAddress.parse(text) }
        }
    }

    @Test
    fun `a path resolves on the server alone`() {
        val address = ServerAddress.parse("192.168.1.20:8737")
        assertEquals("http://192.168.1.20:8737/api/offline", address.manifest.toString())
        assertEquals("http://192.168.1.20:8737/Estopa/Tu%20calorro/sheet.pdf", address.resolve("/Estopa/Tu%20calorro/sheet.pdf").toString())
        for (path in listOf("//evil.example/x", "http://evil.example/x", "x")) {
            assertFailsWith<IllegalArgumentException>(path) { address.resolve(path) }
        }
    }
}
