package io.github.danielhp95.caracole.server.guitar

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.web.Inline
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.Base64

/**
 * web/alphatab.py on the phone: alphaTab 1.8.4 (MPL-2.0), the Bravura font (SIL OFL 1.1) and the Sonivox SoundFont
 * (Apache-2.0), nix/alphatab.nix's three files, as the one script the Guitar Pro page loads ([bundle]), named by its
 * hash, with its SRI string and the CSP sources that allow it and the stylesheet alphaTab adds ([load]): Python's
 * answers for the same files (vectors/web/guitar.jsonl).
 *
 * On the phone the bundle is the APK's asset: app/alphatab.gradle.kts builds it from `CARACOLE_ALPHATAB_DIR` at build
 * time exactly as [bundle] does, and writes what the page needs of it (its name, integrity and sources) as the app's
 * resource [INSTALLED], which [installed] reads; the app's WebView answers the page's request for it from the assets
 * (AlphaTabAssets), as the sandboxed page's request carries no launch cookie the server would take.
 */
object AlphaTabBundle {
    const val VERSION = "1.8.4"
    const val LIBRARY = "alphaTab.min.js"
    const val FONT = "Bravura.woff2"
    const val SOUND_FONT = "sonivox.sf3"
    val FILES: List<String> = listOf(LIBRARY, FONT, SOUND_FONT)

    /** Where the page loads the bundle from (guitar_routes.ASSETS). */
    const val ASSETS = "/assets/alphatab/"

    /** alphaTab's engraving settings' musicFontSize, which its @font-face style names (px). */
    const val MUSIC_FONT_SIZE = 36

    /** Each file at most: alphaTab's is about 1.1 MB, the SoundFont 1 MB. */
    const val MAX_BYTES = 16 * 1024 * 1024

    /** The app's resource that names the bundle its assets hold (app/alphatab.gradle.kts writes it). */
    const val INSTALLED = "caracole/web/alphatab.json"

    /** alphatab.Missing: alphaTab's files aren't there, or one of them can't be read or is past [MAX_BYTES]. */
    class Missing(message: String) : Exception(message)

    /** alphatab.bundle: the font and the SoundFont as data, the library in a function the page's worker is made from
     * (its text), called at once. */
    fun bundle(library: String, fontUri: String, soundFont: String): String =
        "/* alphaTab $VERSION (MPL-2.0), the Bravura font (SIL OFL 1.1) and the Sonivox SoundFont (Apache-2.0),\n" +
            "   for caracole serve's Guitar Pro page: their licences are beside the files caracole read. */\n" +
            "window.caracoleAlphaTab = {\n" +
            "font: ${dumps(fontUri)},\n" +
            "soundFont: ${dumps(soundFont)},\n" +
            "library: function () {\n" +
            "$library\n" +
            "}\n" +
            "};\n" +
            "window.caracoleAlphaTab.library();\n"

    /** alphatab.font_face: the stylesheet alphaTab 1.8.4 adds for its music font, given the font's one source. */
    fun fontFace(fontUri: String): String =
        "\n            @font-face {\n" +
            "                font-display: block;\n" +
            "                font-family: 'alphaTab';\n" +
            "                src: url(${dumps(fontUri)}) format('woff2');\n" +
            "                font-weight: normal;\n" +
            "                font-style: normal;\n" +
            "            }\n" +
            "            .at-surface.at .at {\n" +
            "                font-family: 'alphaTab';\n" +
            "                speak: none;\n" +
            "                font-style: normal;\n" +
            "                font-weight: normal;\n" +
            "                font-variant: normal;\n" +
            "                text-transform: none;\n" +
            "                line-height: 1;\n" +
            "                line-height: 1;\n" +
            "                -webkit-font-smoothing: antialiased;\n" +
            "                -moz-osx-font-smoothing: grayscale;\n" +
            "                font-size: ${MUSIC_FONT_SIZE}px;\n" +
            "                overflow: visible !important;\n" +
            "            }"

    /** alphatab.load over the three files' bytes by name ([FILES]); [Missing] without one, past [MAX_BYTES], or for a
     * library that isn't UTF-8. */
    fun load(files: Map<String, ByteArray>): AlphaTab {
        val (library, font, soundFont) = FILES.map { name ->
            val data = files[name] ?: throw Missing("alphaTab's files can't be read: $name is missing")
            if (data.size > MAX_BYTES) throw Missing("alphaTab's files can't be read: $name is larger than $MAX_BYTES bytes")
            data
        }
        val text = PyText.utf8(library) ?: throw Missing("$LIBRARY isn't UTF-8")
        val fontUri = "data:font/woff2;base64," + Base64.getEncoder().encodeToString(font)
        val body = bundle(text, fontUri, Base64.getEncoder().encodeToString(soundFont)).toByteArray(Charsets.UTF_8)
        val digest = MessageDigest.getInstance("SHA-256").digest(body)
        val b64 = Base64.getEncoder().encodeToString(digest)
        return AlphaTab(
            name = "alphatab-$VERSION-${hex(digest).take(16)}.js",
            body = body,
            integrity = "sha256-$b64",
            scriptSource = "'sha256-$b64'",
            fontFace = Inline.sha256Source(fontFace(fontUri)),
        )
    }

    /** alphatab.load over the folder [dir] (`CARACOLE_ALPHATAB_DIR`'s); [Missing] without its files. */
    fun load(dir: File): AlphaTab = load(FILES.associateWith { name ->
        try {
            val file = File(dir, name)
            if (file.length() > MAX_BYTES) throw Missing("alphaTab's files can't be read in $dir: $name is too large")
            file.readBytes()
        } catch (e: IOException) {
            throw Missing("alphaTab's files can't be read in $dir: $e")
        }
    })

    /** The bundle the APK holds, as the app's build named it ([INSTALLED]): its body the asset the app answers (none
     * here); null where there is none (the JVM's tests, which give GuitarRoutes their own). Read once. */
    fun installed(): AlphaTab? = installedBundle

    private val installedBundle: AlphaTab? by lazy {
        val stream = AlphaTabBundle::class.java.classLoader?.getResourceAsStream(INSTALLED) ?: return@lazy null
        val doc = Json.parseToJsonElement(stream.use { it.readBytes().toString(Charsets.UTF_8) }).jsonObject
        fromRecord(doc)
    }

    /** A bundle named by [doc] (`name`, `integrity`, `script_source`, `font_face`), its body none. */
    fun fromRecord(doc: JsonObject): AlphaTab {
        fun text(name: String) = doc[name]?.jsonPrimitive?.content ?: throw IllegalStateException("$INSTALLED has no $name")
        return AlphaTab(text("name"), ByteArray(0), text("integrity"), text("script_source"), text("font_face"))
    }

    /** json.dumps(text): ensure_ascii, as Python's default (a base64 data URI is ASCII, quoted). */
    private fun dumps(text: String): String = PyJson.dumps(JsonPrimitive(text), indent = null, ensureAscii = true)

    private fun hex(bytes: ByteArray): String = buildString(bytes.size * 2) {
        for (b in bytes) {
            val v = b.toInt() and 0xff
            append(HEX[v shr 4])
            append(HEX[v and 0xf])
        }
    }

    private const val HEX = "0123456789abcdef"
}
