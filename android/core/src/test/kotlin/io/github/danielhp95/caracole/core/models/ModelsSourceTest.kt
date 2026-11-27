package io.github.danielhp95.caracole.core.models

import io.github.danielhp95.caracole.core.catalogues.CatalogueError
import io.github.danielhp95.caracole.core.catalogues.Catalogues
import io.github.danielhp95.caracole.core.catalogues.FakeGitHub
import io.github.danielhp95.caracole.core.catalogues.FakeGitHub.Reply
import io.github.danielhp95.caracole.core.catalogues.Limited
import io.github.danielhp95.caracole.core.http.Robots
import io.github.danielhp95.caracole.mirror.Http
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant
import kotlin.random.Random
import kotlin.test.assertFailsWith

class ModelsSourceTest {
    @get:Rule val tmp = TemporaryFolder()
    private val github = FakeGitHub()
    private val http = Http(userAgent = "caracole/0.1.0 (test)")

    @After fun close() = github.close()

    private val graph = Random(1).nextBytes(3_000)
    private val weights = Random(2).nextBytes(300_000)
    private val beats = Random(3).nextBytes(500_000)
    private val blob = "11c6edbaaaee33737aa7a41dcb9044191630326f"

    private val pins = Pins(1, "models", listOf(
        pin("btc-graph.onnx", graph, From.App),
        pin("btc_model_large_voca.pt", weights,
            From.Blob("jayg996/BTC-ISMIR19", "2682317be668032e6e4b269ded36adaa2ad57df0", "test/btc_model_large_voca.pt",
                      blob)),
        pin("beat_this-final0-fp16.onnx", beats, From.Release("beat_this-final0-fp16.onnx")),
    ))

    private fun pin(name: String, bytes: ByteArray, from: From) =
        Pin(name, bytes.size.toLong(), FakeGitHub.sha256(bytes), from)

    private val listPath = "/repos/Danielhp95/caracole/releases/tags/models"
    private val assetPath = "/repos/Danielhp95/caracole/releases/assets/9"
    private val blobPath = "/repos/jayg996/BTC-ISMIR19/git/blobs/$blob"

    private val listLine = "GET $listPath · application/vnd.github+json"
    private val assetLine = "GET $assetPath · application/octet-stream"
    private val hopLine = "GET /assets/9 · application/octet-stream"
    private val blobLine = "GET $blobPath · application/vnd.github.raw+json"

    private fun asset(size: Int = beats.size, digest: String? = FakeGitHub.sha256(beats), state: String = "uploaded",
                      name: String = "beat_this-final0-fp16.onnx"): String =
        """{"name":"$name","url":"${github.base}$assetPath","size":$size,"state":"$state"""" +
            (if (digest == null) "" else ""","digest":"sha256:$digest"""") + "}"

    private fun release(vararg assets: String = arrayOf(asset())) =
        github.route(listPath, Reply(200, """{"tag_name":"models","assets":[${assets.joinToString(",")}]}""".toByteArray()))

    private fun served(asset: ByteArray = beats, btc: ByteArray = weights) {
        release()
        github.route(assetPath, Reply(302, headers = mapOf("Location" to "${github.base}/assets/9?sig=x")))
        github.route("/assets/9", Reply(200, asset))
        github.route(blobPath, Reply(200, btc))
    }

    private var room = 1L shl 40

    private fun source(redirects: Set<String> = setOf("127.0.0.1")) = ModelsSource(
        base = github.base, redirects = redirects, pins = { pins }, free = { room },
        app = { name -> if (name == "btc-graph.onnx") graph.inputStream() else null },
    )

    private val into: File get() = pins.folder(File(tmp.root, "state"))

    /** Every name beside [into] and in it, the kept files' folder's too, with its bytes' SHA-256. */
    /** beat_this's file, downloaded and checked before BTC's failed: kept for the next try. */
    private val BEAT = listOf("beat_this-final0-fp16.onnx")

    private fun state(): Map<String, String> {
        val parent = into.parentFile
        if (!parent.isDirectory) return emptyMap()
        return parent.walkTopDown().filter { it.isFile }
            .associate { it.relativeTo(parent).path to ModelFiles.sha256(it) } +
            parent.walkTopDown().filter { it.isDirectory && it != parent }
                .associate { it.relativeTo(parent).path + "/" to "" }
    }

    /** [call] refused, leaving everything beside [into] and in it as it was, but the files of [kept] (downloaded and
     * checked before the refusal) now in the kept files' folder, with their pinned bytes. */
    private fun refused(kept: List<String> = emptyList(), call: () -> Any?): CatalogueError {
        val before = state()
        val e = assertFailsWith<CatalogueError> { call() }
        val bytes = mapOf(graph to "btc-graph.onnx", weights to "btc_model_large_voca.pt",
                          beats to "beat_this-final0-fp16.onnx").entries.associate { (b, name) -> name to b }
        val folder = ".c1" + ModelFiles.KEPT
        val expected = before + kept.associate { "$folder/$it" to FakeGitHub.sha256(bytes.getValue(it)) } +
            (if (kept.isEmpty()) emptyMap() else mapOf("$folder/" to ""))
        assertEquals("nothing installed or left but what was kept: ${e.message}", expected, state())
        return e
    }

    // --- a download --------------------------------------------------------------------------------------------------

    @Test fun threeRequestsInstallEveryFileWholeAndTheAssetsHopIsItsOneRedirect() {
        served()
        val seen = mutableListOf<Pair<Long, Long>>()
        val done = source().fetch(http, into) { got, of -> seen += got to of }
        assertEquals(listOf(listLine, assetLine, hopLine, blobLine), github.asked)
        assertEquals(List(4) { "caracole/0.1.0 (test)" }, github.agents)
        assertArrayEquals(graph, File(into, "btc-graph.onnx").readBytes())
        assertArrayEquals(weights, File(into, "btc_model_large_voca.pt").readBytes())
        assertArrayEquals(beats, File(into, "beat_this-final0-fp16.onnx").readBytes())
        assertNull(ModelFiles.installed(into, pins))
        assertNull(ModelFiles.verify(into, pins))
        assertEquals(listOf("beat_this-final0-fp16.onnx", "btc_model_large_voca.pt"), done.fetched)
        assertEquals((weights.size + beats.size).toLong(), done.bytes)
        assertEquals((weights.size + beats.size).toLong() to (weights.size + beats.size).toLong(), seen.last())
        assertEquals(seen.sortedBy { it.first }, seen)
        // Nothing beside the folder: the one being written is the folder now.
        assertEquals(listOf("c1"), into.parentFile.list()!!.toList())
    }

    @Test fun aFolderInstalledWholeAsksNothing() {
        served()
        source().fetch(http, into) { _, _ -> }
        github.asked.clear()
        val again = source().fetch(http, into) { _, _ -> }
        assertEquals(emptyList<String>(), github.asked)
        assertEquals(emptyList<String>(), again.fetched)
    }

    @Test fun aFileMissingIsTheOneAskedForTheOthersKept() {
        served()
        source().fetch(http, into) { _, _ -> }
        File(into, "beat_this-final0-fp16.onnx").delete()
        github.asked.clear()
        assertEquals(listOf("beat_this-final0-fp16.onnx"), source().fetch(http, into) { _, _ -> }.fetched)
        assertEquals(listOf(listLine, assetLine, hopLine), github.asked)  // two requests and the asset's hop
        File(into, "btc_model_large_voca.pt").delete()
        File(into, "btc-graph.onnx").delete()  // the app's: copied again, no request
        github.asked.clear()
        assertEquals(listOf("btc_model_large_voca.pt"), source().fetch(http, into) { _, _ -> }.fetched)
        assertEquals(listOf(blobLine), github.asked)
        assertNull(ModelFiles.verify(into, pins))
        assertEquals(listOf("c1"), into.parentFile.list()!!.toList())
    }

    @Test fun aFileChangedSinceItsCheckIsDownloadedAgain() {
        served()
        source().fetch(http, into) { _, _ -> }
        val pt = File(into, "btc_model_large_voca.pt")
        pt.writeBytes(Random(9).nextBytes(weights.size))
        github.asked.clear()
        assertEquals(listOf("btc_model_large_voca.pt"), source().fetch(http, into) { _, _ -> }.fetched)
        assertEquals(listOf(blobLine), github.asked)
        assertArrayEquals(weights, pt.readBytes())
    }

    @Test fun whatACutOffFetchLeftIsSweptFirst() {
        served()
        val left = File(into.parentFile, ".c1-0123456789abcdef.part").apply { mkdirs() }
        File(left, "beat_this-final0-fp16.onnx").writeBytes(beats.copyOf(1000))
        source().fetch(http, into) { _, _ -> }
        assertFalse(left.exists())
        assertEquals(listOf("c1"), into.parentFile.list()!!.toList())
    }

    // --- refusals ----------------------------------------------------------------------------------------------------

    @Test fun noReleaseIsSaid() {
        github.route(blobPath, Reply(200, weights))
        assertEquals("The chord models aren't published yet: caracole's GitHub release “models” isn't there.",
                     refused { source().fetch(http, into) { _, _ -> } }.message)
    }

    @Test fun anAssetNotListedNotWholeOrNotThePinnedOneIsRefusedBeforeItIsAsked() {
        served()
        release(asset(name = "beat_this-final0.onnx"))
        assertEquals("The chord models aren't published yet: caracole's GitHub release “models” has no " +
                         "beat_this-final0-fp16.onnx.", refused { source().fetch(http, into) { _, _ -> } }.message)
        val notWhole = "beat_this's file on caracole's GitHub release “models” isn't whole yet; nothing was downloaded. " +
            "Try again later."
        release(asset(state = "open"))
        assertEquals(notWhole, refused { source().fetch(http, into) { _, _ -> } }.message)
        release(asset(digest = null))
        assertEquals(notWhole, refused { source().fetch(http, into) { _, _ -> } }.message)
        val other = "beat_this's file on caracole's GitHub release “models” isn't the one this caracole works with; " +
            "nothing was downloaded. Update the app."
        release(asset(size = beats.size + 1))
        assertEquals(other, refused { source().fetch(http, into) { _, _ -> } }.message)
        release(asset(digest = "ab".repeat(32)))
        assertEquals(other, refused { source().fetch(http, into) { _, _ -> } }.message)
        assertFalse(github.asked.any { it.startsWith("GET $assetPath") || it.startsWith("GET /assets/") })
    }

    @Test fun aRedirectToAnyOtherHostIsRefusedNotFollowed() {
        served()
        github.route(assetPath, Reply(302, headers = mapOf("Location" to "https://evil.example/beats.onnx")))
        assertEquals("GitHub sent the download to evil.example; nothing was downloaded.",
                     refused { source().fetch(http, into) { _, _ -> } }.message)
        // The source's own hosts, release-assets.githubusercontent.com alone: loopback is none of them.
        served()
        github.asked.clear()
        assertEquals("GitHub sent the download to 127.0.0.1; nothing was downloaded.",
                     refused { source(Catalogues.API_REDIRECTS).fetch(http, into) { _, _ -> } }.message)
        assertFalse(github.asked.contains(hopLine))
        assertEquals(setOf("release-assets.githubusercontent.com"), Catalogues.API_REDIRECTS)
    }

    @Test fun githubsHourSpentIsALimitedWithItsTimeForTheCaller() {
        val limited = Reply(403, headers = mapOf("x-ratelimit-remaining" to "0", "x-ratelimit-reset" to "1795000000"))
        served()
        github.route(listPath, limited)
        val e = refused { source().fetch(http, into) { _, _ -> } }
        assertEquals(Instant.ofEpochSecond(1_795_000_000), (e as Limited).until)
        served()
        github.route(blobPath, Reply(429, headers = limited.headers))
        assertEquals(Instant.ofEpochSecond(1_795_000_000),
                     (refused(BEAT) { source().fetch(http, into) { _, _ -> } } as Limited).until)
    }

    @Test fun btcsAuthorsRepositoryGoneOrRenamedSaysWhatTheOwnerCanDo() {
        for ((status, headers) in listOf(404 to emptyMap(),
                                          301 to mapOf("Location" to "${github.base}/repositories/1/git/blobs/$blob"))) {
            served()
            github.route(blobPath, Reply(status, headers = headers))
            github.asked.clear()
            assertEquals("BTC's weights aren't in their authors' repository on GitHub any more (jayg996/BTC-ISMIR19 " +
                             "answered HTTP $status); nothing was downloaded. Update the app; if it still says so, " +
                             "tell caracole's author.", refused(BEAT) { source().fetch(http, into) { _, _ -> } }.message)
            assertEquals(blobLine, github.asked.last())  // a redirect never followed
        }
    }

    @Test fun aPlain403IsABlockToTryAgainNeverAFileGone() {
        // No x-ratelimit-remaining: 0: GitHub's secondary limit or an abuse block, which passes; never "gone".
        val again = "GitHub answered HTTP 403. Try again later."
        served()
        github.route(blobPath, Reply(403))
        assertEquals(again, refused(BEAT) { source().fetch(http, into) { _, _ -> } }.message)
        File(tmp.root, "state").deleteRecursively()  // beat_this's file, which the failed fetch kept, gone too
        served()
        github.route(listPath, Reply(403))
        assertEquals(again, refused { source().fetch(http, into) { _, _ -> } }.message)
        served()
        github.route(assetPath, Reply(403))
        assertEquals(again, refused { source().fetch(http, into) { _, _ -> } }.message)
    }

    @Test fun anAssetListedOnAnotherHostIsNeverAsked() {
        served()
        github.route(listPath, Reply(200, ("""{"assets":[{"name":"beat_this-final0-fp16.onnx",""" +
            """"url":"https://evil.example/repos/Danielhp95/caracole/releases/assets/9","size":${beats.size},""" +
            """"state":"uploaded","digest":"sha256:${FakeGitHub.sha256(beats)}"}]}""").toByteArray()))
        assertEquals("GitHub answered with something the phone can't read.",
                     refused { source().fetch(http, into) { _, _ -> } }.message)
        assertEquals(listOf(listLine), github.asked)
    }

    @Test fun githubsDigestIsReadInAnyCase() {
        served()
        release(asset(digest = FakeGitHub.sha256(beats).uppercase()))
        source().fetch(http, into) { _, _ -> }
        assertNull(ModelFiles.verify(into, pins))
    }

    @Test fun anInstallPutAsideByAKillBetweenItsRenamesIsPutBackNotDownloadedAgain() {
        served()
        source().fetch(http, into) { _, _ -> }
        val aside = File(into.parentFile, ".c1-0123456789abcdef.old")
        check(into.renameTo(aside))
        File(into.parentFile, ".c1-fedcba9876543210.part").mkdirs()  // the new folder it was about to rename in
        github.asked.clear()
        assertEquals(emptyList<String>(), source().fetch(http, into) { _, _ -> }.fetched)
        assertEquals(emptyList<String>(), github.asked)
        assertNull(ModelFiles.verify(into, pins))
        assertEquals(listOf("c1"), into.parentFile.list()!!.toList())
    }

    @Test fun aFileDownloadedAndCheckedIsKeptForTheNextTryWhenAnotherFails() {
        served()
        github.route(blobPath, Reply(404))
        refused(BEAT) { source().fetch(http, into) { _, _ -> } }
        github.asked.clear()
        served()
        assertEquals(listOf("btc_model_large_voca.pt"), source().fetch(http, into) { _, _ -> }.fetched)
        assertEquals(listOf(blobLine), github.asked)  // beat_this's 42 MB not asked again
        assertNull(ModelFiles.verify(into, pins))
        assertEquals(listOf("c1"), into.parentFile.list()!!.toList())  // nothing kept beside it once installed
    }

    @Test fun aFileKeptForTheNextTryIsHashedAgainNeverTrusted() {
        served()
        github.route(blobPath, Reply(404))
        refused(BEAT) { source().fetch(http, into) { _, _ -> } }
        val kept = File(into.parentFile, ".c1" + ModelFiles.KEPT)
        File(kept, "beat_this-final0-fp16.onnx").writeBytes(Random(8).nextBytes(beats.size))
        served()
        github.asked.clear()
        assertEquals(listOf("beat_this-final0-fp16.onnx", "btc_model_large_voca.pt"),
                     source().fetch(http, into) { _, _ -> }.fetched)
        assertNull(ModelFiles.verify(into, pins))
    }

    @Test fun theStorageFailingMidWriteIsSaidAndLeavesNothingButTheFileCheckedBeforeIt() {
        served()
        // Once beat_this's file is in, the place BTC's is written to is taken by a folder: its write fails.
        val e = refused(BEAT) {
            source().fetch(http, into) { got, _ ->
                if (got == beats.size.toLong()) {
                    into.parentFile.listFiles()!!.single { it.name.endsWith(".part") }
                        .resolve("btc_model_large_voca.pt").mkdirs()
                }
            }
        }
        assertTrue(e.message!!, e.message!!.startsWith("The phone's storage failed: "))
    }

    @Test fun aWrongSha256OfEitherFileInstallsNothing() {
        val mismatch = "The download isn't the file GitHub listed. Try again."
        served(asset = Random(4).nextBytes(beats.size))
        assertEquals(mismatch, refused { source().fetch(http, into) { _, _ -> } }.message)
        served(btc = Random(5).nextBytes(weights.size))
        assertEquals(mismatch, refused(BEAT) { source().fetch(http, into) { _, _ -> } }.message)
        // An install there before, one file of it missing: left exactly as it was.
        served()
        source().fetch(http, into) { _, _ -> }
        File(into, "btc_model_large_voca.pt").delete()
        served(btc = Random(5).nextBytes(weights.size))
        assertEquals(mismatch, refused { source().fetch(http, into) { _, _ -> } }.message)
    }

    @Test fun aContentLengthOtherThanThePinsIsRefusedBeforeTheBodyIsRead() {
        val other = "GitHub is sending a file of another size than the one listed; nothing was downloaded. Try again."
        served(btc = weights + byteArrayOf(0))
        assertEquals(other, refused(BEAT) { source().fetch(http, into) { _, _ -> } }.message)
        served(btc = weights.copyOf(weights.size - 1))
        assertEquals(other, refused(BEAT) { source().fetch(http, into) { _, _ -> } }.message)
    }

    @Test fun aBodyOfNoLengthLongerOrShorterThanItsPinIsRefusedAsItComes() {
        served()
        github.route(blobPath, Reply(200, weights + byteArrayOf(0), chunked = true))
        assertEquals("The download isn't the file GitHub listed. Try again.",
                     refused(BEAT) { source().fetch(http, into) { _, _ -> } }.message)
        github.route(blobPath, Reply(200, weights.copyOf(weights.size - 1), chunked = true))
        assertEquals("The download was cut short. Try again.", refused(BEAT) { source().fetch(http, into) { _, _ -> } }.message)
    }

    @Test fun tooLittleRoomAsksNothing() {
        served()
        room = 2L * (weights.size + beats.size) + ModelsSource.MARGIN - 1
        val e = refused { source().fetch(http, into) { _, _ -> } }
        assertTrue(e.message!!, e.message!!.startsWith("The chord models need about "))
        assertTrue(e.message!!, e.message!!.contains("free; the phone has "))
        assertEquals(emptyList<String>(), github.asked)
        room += 1
        source().fetch(http, into) { _, _ -> }
        assertNull(ModelFiles.installed(into, pins))
    }

    @Test fun theStorageFailingIsSaid() {
        served()
        val state = File(tmp.root, "state")
        state.writeText("not a folder")
        val e = assertFailsWith<ModelsError> { source().fetch(http, into) { _, _ -> } }
        assertTrue(e.message!!, e.message!!.startsWith("The phone's storage failed: "))
        assertEquals(emptyList<String>(), github.asked)
    }

    // --- robots.txt --------------------------------------------------------------------------------------------------

    /** Neither api.github.com nor release-assets.githubusercontent.com publishes a robots.txt (both 404, checked by
     * hand on 2026-11-27: tests/fixtures/github/), so the phone's rules (robots.json, http.py's ROBOTS_DISALLOW)
     * close none of the download's paths. */
    @Test fun noRobotsRuleClosesAnyPathTheDownloadAsks() {
        val fixtures = File(System.getProperty("caracole.fixtures"), "github")
        for (name in listOf("api-robots.txt", "release-assets-robots.txt")) {
            assertTrue(name, File(fixtures, name).readText().contains("404"))
        }
        for (url in listOf(
            "https://api.github.com/repos/Danielhp95/caracole/releases/tags/models",
            "https://api.github.com/repos/Danielhp95/caracole/releases/assets/312345678",
            "https://api.github.com/repos/jayg996/BTC-ISMIR19/git/blobs/$blob",
            "https://release-assets.githubusercontent.com/github-production-release-asset/1/9?sp=r&sv=2018-11-09",
        )) {
            assertNull(url, Robots.disallows(url))
        }
    }
}
