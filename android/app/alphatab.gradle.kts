// alphaTab's bundle as the APK's assets, for the Guitar Pro page (lane guitar-alphatab's).
//
// nix/alphatab.nix's three files (alphaTab 1.8.4's browser build, MPL-2.0; the Bravura font, SIL OFL 1.1; the Sonivox
// SoundFont, Apache-2.0), read from CARACOLE_ALPHATAB_DIR (android/flake.nix sets it), made into the one script the
// page loads exactly as caracole's web/alphatab.py `bundle` makes it, and written as the asset
// `alphatab/<its name>` beside their licences (`alphatab/licenses/`). Its name, SRI string and CSP sources go in the
// app's Java resource `caracole/web/alphatab.json`, which server.guitar.AlphaTabBundle.installed reads: the phone's
// Guitar Pro page names the bundle by it, and the app's AlphaTabAssets answers the page's request for it from the
// assets. GuitarPageTest (androidTest) holds the APK's bytes to Python's (tests/conformance/vectors/web/guitar.jsonl),
// AlphaTabAssetsTest (test) the resource to the Kotlin port's.
//
// Without CARACOLE_ALPHATAB_DIR the build fails, naming it: never an APK without the bundle.
import java.nio.charset.CodingErrorAction
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.util.Base64

abstract class AlphaTabBundleTask : DefaultTask() {
    /** CARACOLE_ALPHATAB_DIR: alphaTab.min.js, Bravura.woff2, sonivox.sf3 and licenses/. */
    @get:InputFiles
    @get:Optional
    @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val source: DirectoryProperty

    @get:OutputDirectory
    abstract val assets: DirectoryProperty

    @get:OutputDirectory
    abstract val resources: DirectoryProperty

    @TaskAction
    fun bundle() {
        val dir = source.orNull?.asFile ?: throw GradleException(
            "CARACOLE_ALPHATAB_DIR is not set: the app's Guitar Pro page needs alphaTab's files (nix/alphatab.nix). " +
                "Build in nix develop ./android, which sets it.")
        fun read(name: String): ByteArray {
            val file = File(dir, name)
            if (!file.isFile) throw GradleException("CARACOLE_ALPHATAB_DIR ($dir) has no $name")
            if (file.length() > MAX_BYTES) throw GradleException("$file is larger than $MAX_BYTES bytes")
            return file.readBytes()
        }
        val library = read("alphaTab.min.js")
        val font = read("Bravura.woff2")
        val soundFont = read("sonivox.sf3")
        val text = try {
            Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(library)).toString()
        } catch (e: java.nio.charset.CharacterCodingException) {
            throw GradleException("$dir/alphaTab.min.js isn't UTF-8")
        }
        val b64 = Base64.getEncoder()
        val fontUri = "data:font/woff2;base64," + b64.encodeToString(font)
        // web/alphatab.py's bundle, line for line; json.dumps of an ASCII text with no quote or backslash is the text
        // in quotes.
        val body = ("/* alphaTab $VERSION (MPL-2.0), the Bravura font (SIL OFL 1.1) and the Sonivox SoundFont (Apache-2.0),\n" +
            "   for caracole serve's Guitar Pro page: their licences are beside the files caracole read. */\n" +
            "window.caracoleAlphaTab = {\n" +
            "font: ${quoted(fontUri)},\n" +
            "soundFont: ${quoted(b64.encodeToString(soundFont))},\n" +
            "library: function () {\n" +
            "$text\n" +
            "}\n" +
            "};\n" +
            "window.caracoleAlphaTab.library();\n").toByteArray(Charsets.UTF_8)
        val digest = sha256(body)
        val name = "alphatab-$VERSION-${hex(digest).take(16)}.js"
        val integrity = "sha256-" + b64.encodeToString(digest)
        val fontFace = "'sha256-" + b64.encodeToString(sha256(fontFace(fontUri).toByteArray(Charsets.UTF_8))) + "'"

        val out = assets.get().asFile.resolve("alphatab")
        out.deleteRecursively()
        out.mkdirs()
        out.resolve(name).writeBytes(body)
        val licences = dir.resolve("licenses").listFiles()?.filter { it.isFile }?.sortedBy { it.name }.orEmpty()
        if (licences.isEmpty()) throw GradleException("CARACOLE_ALPHATAB_DIR ($dir) has no licenses/")
        val notices = out.resolve("licenses").apply { mkdirs() }
        for (licence in licences) notices.resolve(licence.name).writeBytes(licence.readBytes())

        val resource = resources.get().asFile.resolve("caracole/web")
        resource.deleteRecursively()
        resource.mkdirs()
        resource.resolve("alphatab.json").writeText(
            "{\"version\": ${quoted(VERSION)}, \"name\": ${quoted(name)}, \"integrity\": ${quoted(integrity)}, " +
                "\"script_source\": ${quoted("'$integrity'")}, \"font_face\": ${quoted(fontFace)}, " +
                "\"sha256\": ${quoted(hex(digest))}, \"length\": ${body.size}, " +
                "\"licenses\": [${licences.joinToString(", ") { quoted(it.name) }}]}\n",
            Charsets.UTF_8,
        )
    }

    /** web/alphatab.py's font_face: the stylesheet alphaTab adds for its music font. */
    private fun fontFace(fontUri: String): String =
        "\n            @font-face {\n" +
            "                font-display: block;\n" +
            "                font-family: 'alphaTab';\n" +
            "                src: url(${quoted(fontUri)}) format('woff2');\n" +
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
            "                font-size: 36px;\n" +
            "                overflow: visible !important;\n" +
            "            }"

    /** json.dumps of [text], which must be printable ASCII with no quote or backslash (a base64 data URI is). */
    private fun quoted(text: String): String {
        require(text.all { it in ' '..'~' && it != '"' && it != '\\' }) { "not a plain ASCII text: $text" }
        return "\"$text\""
    }

    private fun sha256(bytes: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(bytes)

    private fun hex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it.toInt() and 0xff) }

    private companion object {
        const val VERSION = "1.8.4"
        const val MAX_BYTES = 16L * 1024 * 1024
    }
}

// One task a variant (alphaTabBundleDebug, alphaTabBundleRelease), each wired into its variant's assets and Java
// resources (androidComponents' Sources.addGeneratedSourceDirectory), which every task that reads them then depends
// on. A script plugin is compiled without the Android Gradle plugin's classes, so its API is reached dynamically.
val alphaTabDir = providers.environmentVariable("CARACOLE_ALPHATAB_DIR").map { File(it) }
val components = extensions.getByName("androidComponents")
val everyVariant = components.withGroovyBuilder { "selector"() }!!.withGroovyBuilder { "all"() }!!
components.withGroovyBuilder {
    "onVariants"(everyVariant, Action<Any> {
        val variant = this
        val name = variant.withGroovyBuilder { getProperty("name") } as String
        val bundle = tasks.register<AlphaTabBundleTask>("alphaTabBundle" + name.replaceFirstChar { it.uppercase() }) {
            description = "alphaTab's bundle and licences as the APK's assets, from CARACOLE_ALPHATAB_DIR"
            source.fileProvider(alphaTabDir)
        }
        val sources = variant.withGroovyBuilder { getProperty("sources") }!!
        val assets: (AlphaTabBundleTask) -> DirectoryProperty = { it.assets }
        val resources: (AlphaTabBundleTask) -> DirectoryProperty = { it.resources }
        sources.withGroovyBuilder { getProperty("assets") }!!.withGroovyBuilder { "addGeneratedSourceDirectory"(bundle, assets) }
        sources.withGroovyBuilder { getProperty("resources") }!!.withGroovyBuilder { "addGeneratedSourceDirectory"(bundle, resources) }
    })
}
