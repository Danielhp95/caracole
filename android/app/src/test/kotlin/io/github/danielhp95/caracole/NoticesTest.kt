package io.github.danielhp95.caracole

import org.junit.Assume.assumeTrue
import java.io.File
import java.util.zip.ZipFile
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * The notices of what the app's yt-dlp ships (the phone-youtube design's §3.6), `assets/licenses/youtube/` in the APK:
 *
 * - in every `gradle test`, the folder `:youtube`'s copyLicences makes (`caracole.youtube.licenses`) holds each of
 *   [NOTICES], every one its source's bytes: android/youtube/licenses/'s own texts, yt-dlp's and yt-dlp-ejs's LICENSE
 *   from the pinned wheels, the notice yt-dlp-ejs's lib.min.js begins with (its bundled meriyah's and astring's), and
 *   QuickJS-NG's LICENSE from its pinned source; and nothing else;
 * - by `gradle :app:apkScan` (release-check.sh), the release and debug APKs carry that folder byte for byte.
 *
 * [NOTICES] is the one list: release-check.sh counts the release's notices against copyLicences' folder, never a
 * number of its own.
 */
class NoticesTest {
    private val folder = File(System.getProperty("caracole.youtube.licenses").orEmpty())
    private val committed = File(System.getProperty("caracole.youtube.committed").orEmpty())
    private val wheels = File(System.getProperty("caracole.youtube.wheels").orEmpty())
    private val quickjs = File(System.getProperty("caracole.youtube.quickjs").orEmpty())

    @Test fun theFolderHoldsEachNoticeAndNothingElse() {
        assertEquals(NOTICES.sorted(), folder.list().orEmpty().sorted(), "$folder")
        for (name in NOTICES) assertTrue(File(folder, name).length() > 0, "$name is empty")
    }

    @Test fun eachNoticeIsItsSourcesBytes() {
        for (name in COMMITTED) assertContentEquals(File(committed, name).readBytes(), notice(name), name)
        assertContentEquals(fromWheel("yt_dlp-", LICENSE), notice("yt-dlp-LICENSE"))
        assertContentEquals(fromWheel("yt_dlp_ejs-", LICENSE), notice("yt-dlp-ejs-LICENSE"))
        assertContentEquals(File(quickjs, "LICENSE").readBytes(), notice("quickjs-ng-LICENSE"))
    }

    @Test fun theBundledNoticeIsTheOneLibMinJsBeginsWith() {
        val js = String(fromWheel("yt_dlp_ejs-", "yt_dlp_ejs/yt/solver/lib.min.js"), Charsets.UTF_8)
        val bundled = String(notice("yt-dlp-ejs-BUNDLED"), Charsets.UTF_8)
        assertTrue(bundled.startsWith("/*!") && bundled.endsWith("*/\n"), bundled.take(80))
        assertTrue(js.contains(bundled.removeSuffix("\n")), "lib.min.js holds it verbatim")
        for (named in listOf("Name: meriyah", "License: ISC", "Name: astring", "License: MIT")) {
            assertTrue(named in bundled, named)
        }
    }

    @Test fun theApksCarryTheNotices() {
        val apks = System.getProperty("caracole.apks").orEmpty()
        // The APKs are apkScan's alone (it builds them: release-check.sh runs it); `gradle test` builds none.
        assumeTrue("no APKs given: gradle :app:apkScan", apks.isNotEmpty())
        for (dir in apks.split(File.pathSeparator)) {
            val apk = File(dir).listFiles().orEmpty().single { it.name.endsWith(".apk") }
            ZipFile(apk).use { zip ->
                val held = zip.entries().toList().map { it.name }.filter { it.startsWith(ASSETS) }
                assertEquals(NOTICES.map { ASSETS + it }.sorted(), held.sorted(), "$apk")
                for (name in NOTICES) {
                    assertContentEquals(notice(name), zip.getInputStream(zip.getEntry(ASSETS + name)).readBytes(),
                                        "$apk: $name")
                }
            }
        }
    }

    private fun notice(name: String): ByteArray = File(folder, name).readBytes()

    /** [entry] of the pinned wheel whose name begins [prefix] (yt-dlp's `yt_dlp-`, not yt-dlp-ejs's `yt_dlp_ejs-`); an
     * entry beginning with `*` is the one entry ending with the rest (its dist-info's, of any version). */
    private fun fromWheel(prefix: String, entry: String): ByteArray {
        val wheel = wheels.listFiles().orEmpty().single { it.name.endsWith(".whl") && it.name.startsWith(prefix) &&
            it.name.removePrefix(prefix).first().isDigit() }
        return ZipFile(wheel).use { zip ->
            val found = if (entry.startsWith("*")) zip.entries().toList().single { it.name.endsWith(entry.drop(1)) }
                else zip.getEntry(entry)
            zip.getInputStream(found).readBytes()
        }
    }

    private companion object {
        const val ASSETS = "assets/licenses/youtube/"
        const val LICENSE = "*.dist-info/licenses/LICENSE"
        val COMMITTED = listOf("README", "cpython-LICENSE", "cpython-license.rst", "chaquopy-LICENSE.txt",
                               "openssl-LICENSE.txt", "libffi-LICENSE", "bzip2-LICENSE", "xz-COPYING",
                               "certifi-LICENSE")
        val NOTICES = COMMITTED + listOf("yt-dlp-LICENSE", "yt-dlp-ejs-LICENSE", "yt-dlp-ejs-BUNDLED",
                                         "quickjs-ng-LICENSE")
    }
}
