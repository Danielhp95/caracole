package io.github.danielhp95.caracole.viewer.render

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.viewer.Viewer
import java.io.File
import java.io.IOException
import java.net.URI
import java.net.URISyntaxException
import java.util.zip.ZipFile

/**
 * The phone's build of its pages: what they are made from that changes with the app, hashed, so that pages another
 * build made are made again (kv `render:<song id>:phone`'s `build`, PhoneRender.stale): the app's version, then
 *
 * - on the phone, the APK's code and data ([packed]): each `classes*.dex` and each file under `caracole/` (viewer/'s
 *   assets, which the pages inline, and every runtime table the code reads), by its name, size and CRC-32 as the
 *   APK's directory lists them, so that an APK whose page builder, theory or tables changed makes every page again,
 *   though its versionName is the same, and no byte of them is read;
 * - elsewhere (a JVM's test, whose classes are in a folder), the SHA-256 of each file the page builder reads on the
 *   classpath, viewer/'s assets ([ASSETS]: what copyViewerAssets copies) and the runtime data its code reads ([DATA]),
 *   each listed here, since a classpath can't be listed; PhoneRenderTest holds each list to its folder.
 */
object RenderBuild {
    /** viewer/'s files on the classpath, under caracole/viewer/ (src/caracole/viewer/'s `*.js`, `*.css`,
     * `voicings*.json` and `LICENSE-chords-db`). */
    val ASSETS: List<String> = listOf(
        "LICENSE-chords-db", "book.css", "book.js", "harptab.css", "harptab.js", "instruments.js", "overlay.js",
        "strum.js", "viewer.css", "viewer.js", "voicings-ukulele.json", "voicings.json", "winds.js",
    )

    /** The folders of runtime data under caracole/ (tests/conformance/data/caracole/'s) the page builder reads whole:
     * viewer/'s modules' tables, OpenCC's dictionaries, pypinyin's readings, Python's Unicode and the keys' tables. */
    val FOLDERS: List<String> = listOf("viewer", "hanzi", "pinyin", "unicode", "keys")

    /** The runtime data the page builder reads, under caracole/: [FOLDERS]' files, and the page icon and the empty
     * library's icons (an auto sheet's YouTube mark where the mirror holds none). */
    val DATA: List<String> = listOf(
        "hanzi/CJK_Compatibility_Ideographs.txt", "hanzi/STCharacters.txt", "hanzi/STPhrases.txt",
        "hanzi/STPhrases_GeneratedFromRegionalPhrases.txt", "hanzi/TSCharacters.txt", "hanzi/TSPhrases.txt",
        "hanzi/TWVariants.txt", "hanzi/TWVariantsPhrases.txt", "hanzi/TWVariantsRev.txt",
        "hanzi/TWVariantsRevPhrases.txt", "hanzi/opencc.json",
        "keys/t2s.txt", "keys/tables.json",
        "page/empty_library.json", "page/icon.json",
        "pinyin/chars.txt", "pinyin/hans.txt", "pinyin/phrases.txt", "pinyin/symbols.txt",
        "unicode/case.txt", "unicode/category.txt", "unicode/combining.txt", "unicode/decomposition.txt",
        "unicode/east_asian_width.txt", "unicode/flags.txt", "unicode/ignorecase.txt", "unicode/title.txt",
        "viewer/harmonica_page.json", "viewer/harmony.json", "viewer/harp.json", "viewer/harptab.json",
        "viewer/instruments.json", "viewer/page.json", "viewer/pinyin.json", "viewer/sheet.json", "viewer/theory.json",
        "viewer/version.json", "viewer/winds.json",
    )

    /** The build of the app at [version], its code and data read from the APK it runs from ([apk]), else hashed. */
    fun of(version: String): String = of(version, apk())

    /** The build of the app at [version] run from [archive]: its [packed] entries when it is an APK, else the SHA-256
     * of each listed file on the classpath. */
    internal fun of(version: String, archive: File?): String {
        val lines = StringBuilder(version).append('\n')
        val packed = archive?.let(::packed)
        if (packed != null) {
            for (line in packed) lines.append(line).append('\n')
        } else {
            for (name in ASSETS) lines.append("${Viewer.ASSETS}/$name ").append(digest(Viewer.asset(name))).append('\n')
            for (name in DATA) lines.append("caracole/$name ").append(digest(resource("caracole/$name"))).append('\n')
        }
        return Canonical.sha256Hex(lines.toString().toByteArray(Charsets.UTF_8))
    }

    /** An APK's entries the pages are made by, `<name> <size> <crc32>` each, in name order: its `classes*.dex` and
     * its files under `caracole/`, as its directory lists them; null for an archive with no dex (a JVM's jar) or one
     * that can't be read. */
    internal fun packed(archive: File): List<String>? = try {
        ZipFile(archive).use { zip ->
            val lines = zip.entries().asSequence()
                .filter { !it.isDirectory && (isDex(it.name) || it.name.startsWith("caracole/")) }
                .map { "${it.name} ${it.size} ${it.crc.toString(16)}" }
                .sorted().toList()
            lines.takeIf { found -> found.any { isDex(it.substringBefore(' ')) } }
        }
    } catch (_: IOException) {
        null
    }

    private fun isDex(name: String) = '/' !in name && name.startsWith("classes") && name.endsWith(".dex")

    /** The archive the app's classes run from, by where a viewer asset is: on the phone, the APK
     * (`jar:file:/data/app/…/base.apk!/caracole/viewer/viewer.css`); null for one in a folder. */
    private fun apk(): File? {
        val url = RenderBuild::class.java.classLoader?.getResource("${Viewer.ASSETS}/viewer.css") ?: return null
        if (url.protocol != "jar") return null
        val file = url.path.substringBefore("!/")
        if (!file.startsWith("file:")) return null
        return try {
            File(URI(file))
        } catch (_: URISyntaxException) {
            null
        } catch (_: IllegalArgumentException) {
            null
        }
    }

    private fun digest(bytes: ByteArray?): String = bytes?.let(Canonical::sha256Hex) ?: "-"

    private fun resource(path: String): ByteArray? =
        (RenderBuild::class.java.classLoader?.getResourceAsStream(path) ?: RenderBuild::class.java.getResourceAsStream("/$path"))
            ?.use { it.readBytes() }
}
