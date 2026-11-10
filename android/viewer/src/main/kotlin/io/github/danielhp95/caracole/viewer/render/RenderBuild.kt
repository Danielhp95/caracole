package io.github.danielhp95.caracole.viewer.render

import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.viewer.Viewer

/**
 * The phone's build of its pages: what they are made from that changes with the app, hashed, so that pages another
 * build made are made again (kv `render:<song id>:phone`'s `build`, PhoneRender.stale): the app's version, and the
 * SHA-256 of each file the page builder reads on the classpath, viewer/'s assets ([ASSETS]: what copyViewerAssets
 * copies, which the pages inline) and the runtime data its code reads ([DATA]: viewer/'s modules' tables, OpenCC's
 * dictionaries and pypinyin's readings). Every name is listed here, since an APK's classpath can't be listed;
 * RenderBuildTest holds each list to its folder, so a file added there is added here.
 */
object RenderBuild {
    /** viewer/'s files on the classpath, under caracole/viewer/ (src/caracole/viewer/'s `*.js`, `*.css`,
     * `voicings*.json` and `LICENSE-chords-db`). */
    val ASSETS: List<String> = listOf(
        "LICENSE-chords-db", "book.css", "book.js", "harptab.css", "harptab.js", "instruments.js", "overlay.js",
        "strum.js", "viewer.css", "viewer.js", "voicings-ukulele.json", "voicings.json", "winds.js",
    )

    /** The runtime data the page builder reads, under caracole/ (tests/conformance/data/caracole/'s viewer/, hanzi/
     * and pinyin/). */
    val DATA: List<String> = listOf(
        "hanzi/CJK_Compatibility_Ideographs.txt", "hanzi/STCharacters.txt", "hanzi/STPhrases.txt",
        "hanzi/STPhrases_GeneratedFromRegionalPhrases.txt", "hanzi/TSCharacters.txt", "hanzi/TSPhrases.txt",
        "hanzi/TWVariants.txt", "hanzi/TWVariantsPhrases.txt", "hanzi/TWVariantsRev.txt",
        "hanzi/TWVariantsRevPhrases.txt", "hanzi/opencc.json",
        "pinyin/chars.txt", "pinyin/hans.txt", "pinyin/phrases.txt", "pinyin/symbols.txt",
        "viewer/harmony.json", "viewer/harp.json", "viewer/harptab.json", "viewer/instruments.json",
        "viewer/pinyin.json", "viewer/sheet.json", "viewer/theory.json", "viewer/winds.json",
    )

    /** The build of the app at [version]: `<version>` then each file's line, `<path> <sha256>` (`-` for a file the
     * classpath lacks), hashed. */
    fun of(version: String): String {
        val lines = StringBuilder(version).append('\n')
        for (name in ASSETS) lines.append("${Viewer.ASSETS}/$name ").append(digest(Viewer.asset(name))).append('\n')
        for (name in DATA) lines.append("caracole/$name ").append(digest(resource("caracole/$name"))).append('\n')
        return Canonical.sha256Hex(lines.toString().toByteArray(Charsets.UTF_8))
    }

    private fun digest(bytes: ByteArray?): String = bytes?.let(Canonical::sha256Hex) ?: "-"

    private fun resource(path: String): ByteArray? =
        (RenderBuild::class.java.classLoader?.getResourceAsStream(path) ?: RenderBuild::class.java.getResourceAsStream("/$path"))
            ?.use { it.readBytes() }
}
