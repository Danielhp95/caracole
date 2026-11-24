package io.github.danielhp95.caracole.core.catalogues

import io.github.danielhp95.caracole.core.catalogues.FakeGitHub.Reply
import io.github.danielhp95.caracole.core.http.TransportError
import io.github.danielhp95.caracole.mirror.Http
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.time.Instant
import kotlin.random.Random
import kotlin.test.assertFailsWith

class DownloadTest {
    @get:Rule val tmp = TemporaryFolder()
    private val github = FakeGitHub()
    private val http = Http()
    private val loopback = setOf("127.0.0.1")

    @After fun close() = github.close()

    /** An export's stand-in: bytes that don't compress to nothing. */
    private val export: ByteArray = Random(17).nextBytes(40_000)
    private val gz = FakeGitHub.gzip(export)

    private val assetPath = "/repos/Danielhp95/caracole/releases/assets/7"

    private fun listed(bytes: Long = gz.size.toLong(), sha256: String = FakeGitHub.sha256(gz)) =
        Listed("indexes-s17-20261124T0312Z.sqlite.gz", bytes, sha256, true, "${github.base}$assetPath")

    private fun redirectedTo(blob: ByteArray) {
        github.route(assetPath, Reply(302, headers = mapOf("Location" to "${github.base}/blob/7?sig=x")))
        github.route("/blob/7", Reply(200, blob))
    }

    @Test fun aGoodFileIsUnpackedAndChecked() {
        redirectedTo(gz)
        val to = tmp.root.resolve("indexes.sqlite")
        val seen = mutableListOf<Long>()
        val fetched = download(http, listed(), to, loopback) { seen += it }
        assertEquals(to, fetched.file)
        assertEquals(export.size.toLong(), fetched.raw)
        assertArrayEquals(export, to.readBytes())
        assertEquals(gz.size.toLong(), seen.last())
        assertEquals(seen.sorted(), seen)
        // The asset asked for as its bytes, the redirect followed once.
        assertEquals(listOf("GET $assetPath · application/octet-stream", "GET /blob/7 · application/octet-stream"),
                     github.asked)
    }

    @Test fun aFileServedWithNoRedirectIsTakenToo() {
        github.route(assetPath, Reply(200, gz))
        val to = tmp.root.resolve("indexes.sqlite")
        assertEquals(export.size.toLong(), download(http, listed(), to, loopback) {}.raw)
    }

    @Test fun aRedirectElsewhereIsRefusedBeforeAnythingIsAsked() {
        github.route(assetPath, Reply(302, headers = mapOf("Location" to "https://evil.example/indexes.gz")))
        val to = tmp.root.resolve("indexes.sqlite")
        val e = assertFailsWith<CatalogueError> { download(http, listed(), to, loopback) {} }
        assertEquals("GitHub sent the download to evil.example; nothing was downloaded.", e.message)
        assertFalse(to.exists())
        // GitHub's own hosts, the API source's: loopback is none of them.
        redirectedTo(gz)
        val again = assertFailsWith<CatalogueError> { download(http, listed(), to, Catalogues.API_REDIRECTS) {} }
        assertEquals("GitHub sent the download to 127.0.0.1; nothing was downloaded.", again.message)
        assertFalse(to.exists())
    }

    @Test fun aSecondRedirectIsNotFollowed() {
        github.route(assetPath, Reply(302, headers = mapOf("Location" to "${github.base}/blob/7")))
        github.route("/blob/7", Reply(302, headers = mapOf("Location" to "${github.base}/blob/8")))
        github.route("/blob/8", Reply(200, gz))
        val to = tmp.root.resolve("indexes.sqlite")
        assertFailsWith<CatalogueError> { download(http, listed(), to, loopback) {} }
        assertFalse(to.exists())
        assertEquals(2, github.asked.size)
    }

    @Test fun aRedirectFromHttpsToHttpIsRefused() {
        // A downgrade is refused whatever the host: the original here is http, so check the rule on its own.
        assertFalse(redirectAllowed(java.net.URI("https://api.github.com/x"),
                                    java.net.URI("http://release-assets.githubusercontent.com/y"),
                                    Catalogues.API_REDIRECTS))
        assertTrue(redirectAllowed(java.net.URI("https://api.github.com/x"),
                                   java.net.URI("https://Release-Assets.githubusercontent.com/y"),
                                   Catalogues.API_REDIRECTS))
        assertFalse(redirectAllowed(java.net.URI("https://api.github.com/x"),
                                    java.net.URI("https://objects.githubusercontent.com/y"),
                                    Catalogues.API_REDIRECTS))
    }

    @Test fun aWrongDigestIsRefusedAndNothingIsLeft() {
        redirectedTo(gz)
        val to = tmp.root.resolve("indexes.sqlite")
        val e = assertFailsWith<CatalogueError> { download(http, listed(sha256 = "00".repeat(32)), to, loopback) {} }
        assertEquals("The download isn't the file GitHub listed. Try again.", e.message)
        assertFalse(to.exists())
    }

    @Test fun moreBytesThanListedAreRefused() {
        redirectedTo(gz)
        val to = tmp.root.resolve("indexes.sqlite")
        val e = assertFailsWith<CatalogueError> { download(http, listed(bytes = gz.size - 10L), to, loopback) {} }
        assertEquals("The download isn't the file GitHub listed. Try again.", e.message)
        assertFalse(to.exists())
    }

    @Test fun aGzipCutShortIsAnErrorAndNothingIsLeft() {
        val cut = gz.copyOf(gz.size / 2)
        redirectedTo(cut)
        val to = tmp.root.resolve("indexes.sqlite")
        val e = assertFailsWith<CatalogueError> {
            download(http, listed(bytes = cut.size.toLong(), sha256 = FakeGitHub.sha256(cut)), to, loopback) {}
        }
        assertEquals("The download was cut short. Try again.", e.message)
        assertFalse(to.exists())
    }

    @Test fun bytesThatArentGzipAreRefused() {
        redirectedTo(export)
        val to = tmp.root.resolve("indexes.sqlite")
        val e = assertFailsWith<CatalogueError> {
            download(http, listed(bytes = export.size.toLong(), sha256 = FakeGitHub.sha256(export)), to, loopback) {}
        }
        assertEquals("The download isn't the file GitHub listed. Try again.", e.message)
        assertFalse(to.exists())
    }

    @Test fun aFileThatUnpacksPastItsCapIsStopped() {
        // About 65 KB of gzip that unpacks to 65 MiB of zeros: past 20 times its size and past the 64 MiB floor.
        val bomb = zeros(65L shl 20)
        redirectedTo(bomb)
        val to = tmp.root.resolve("indexes.sqlite")
        val e = assertFailsWith<CatalogueError> {
            download(http, listed(bytes = bomb.size.toLong(), sha256 = FakeGitHub.sha256(bomb)), to, loopback) {}
        }
        assertEquals("The file unpacks to more than it should; nothing was imported.", e.message)
        assertFalse(to.exists())
    }

    @Test fun aSmallFileThatCompressesWellIsWithinTheFloor() {
        // 30 KB of zeros in about a hundred bytes: past 20 times its size, under 64 MiB.
        val small = FakeGitHub.gzip(ByteArray(30_000))
        redirectedTo(small)
        val to = tmp.root.resolve("indexes.sqlite")
        val got = download(http, listed(bytes = small.size.toLong(), sha256 = FakeGitHub.sha256(small)), to, loopback) {}
        assertEquals(30_000L, got.raw)
    }

    @Test fun theCapIsTwentyTimesTheGzipOr64MiB() {
        assertEquals(64L shl 20, capFor(1_000))
        assertEquals(20L * (10L shl 20), capFor(10L shl 20))
    }

    /** [n] zero bytes gzipped, written a MiB at a time. */
    private fun zeros(n: Long): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        java.util.zip.GZIPOutputStream(out).use { gz ->
            val chunk = ByteArray(1 shl 20)
            var left = n
            while (left > 0) {
                val k = minOf(left, chunk.size.toLong()).toInt()
                gz.write(chunk, 0, k)
                left -= k
            }
        }
        return out.toByteArray()
    }

    @Test fun aGoneFileIsAnError() {
        val to = tmp.root.resolve("indexes.sqlite")
        assertFailsWith<CatalogueError> { download(http, listed(), to, loopback) {} }
        assertFalse(to.exists())
    }

    @Test fun aRateLimitOnTheDownloadIsLimited() {
        github.route(assetPath, Reply(403, headers = mapOf("x-ratelimit-remaining" to "0", "x-ratelimit-reset" to "1795537517")))
        val e = assertFailsWith<Limited> { download(http, listed(), tmp.root.resolve("x"), loopback) {} }
        assertEquals(Instant.ofEpochSecond(1795537517), e.until)
    }

    @Test fun aFileLeftBeforeIsReplacedOrDeleted() {
        val to = tmp.root.resolve("indexes.sqlite").apply { writeText("an old download") }
        github.route(assetPath, Reply(404))
        assertFailsWith<CatalogueError> { download(http, listed(), to, loopback) {} }
        assertFalse(to.exists())
    }

    @Test fun aDownloadNeverReachesGitHubFromATest() {
        val file = Listed("indexes-s17-20261124T0312Z.sqlite.gz", 1, "00", true,
                          "https://api.github.com/repos/Danielhp95/caracole/releases/assets/7")
        assertFailsWith<TransportError> { download(http, file, tmp.root.resolve("x"), Catalogues.API_REDIRECTS) {} }
    }
}
