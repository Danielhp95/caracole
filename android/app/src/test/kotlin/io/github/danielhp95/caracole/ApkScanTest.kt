package io.github.danielhp95.caracole

import org.junit.Assume.assumeTrue
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.zip.ZipEntry
import java.util.zip.ZipInputStream
import java.util.zip.ZipOutputStream
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * Gate R's string scan (the chords-on-the-phone design's §3.5): nothing of what made ONNX Runtime's Maven AAR phone
 * home is in what ships. [NEEDLES] are its host (Microsoft's 1DS, `mobile.events.data.microsoft.com`), the provider
 * that started it (`ai.onnxruntime.TelemetryInitializer`) and its Java client (`ai/onnxruntime/telemetry/`), looked for
 * in every entry of a zip and of the zips inside it (an AAR's classes.jar), in ASCII and in UTF-16LE (a binary
 * manifest's string pool).
 *
 * - the runtime built from its source (nix/onnxruntime-android.nix: the AAR in `$CARACOLE_ONNXRUNTIME`, Gradle's
 *   `caracole.onnxruntime`), in every `gradle test` of flake.nix's ml shell (elsewhere no runtime is built in: skipped,
 *   saying so);
 * - the release APK and the debug one, which carries the runtime, by `gradle :app:apkScan` alone (it builds both:
 *   release-check.sh runs it), each read by the name its output-metadata.json gives.
 */
class ApkScanTest {
    @Test fun theScanFindsEachNeedleWhereItWouldBe() {
        val manifest = "<provider android:name=\"ai.onnxruntime.TelemetryInitializer\"/>".toByteArray(Charsets.UTF_16LE)
        val classes = zip("ai/onnxruntime/telemetry/HttpClient.class" to
            "\u00ca\u00feLai/onnxruntime/telemetry/HttpClient;".toByteArray(Charsets.ISO_8859_1))
        val apk = zip(
            "AndroidManifest.xml" to manifest,
            "lib/arm64-v8a/libonnxruntime.so" to "\u0000https://mobile.events.data.microsoft.com/OneCollector\u0000"
                .toByteArray(Charsets.US_ASCII),
            "classes.jar" to classes,
            "clean.txt" to "nothing here".toByteArray(),
        )
        assertEquals(
            setOf("AndroidManifest.xml" to "TelemetryInitializer",
                  "lib/arm64-v8a/libonnxruntime.so" to "events.data.microsoft.com",
                  // The jar names its class (an entry's name), and the class itself names its package.
                  "classes.jar" to "ai/onnxruntime/telemetry/",
                  "classes.jar!ai/onnxruntime/telemetry/HttpClient.class" to "ai/onnxruntime/telemetry/"),
            found(apk).toSet())
    }

    @Test fun theRuntimeBuiltFromSourceHoldsNoTelemetry() {
        val given = System.getProperty("caracole.onnxruntime").orEmpty()
        // Outside flake.nix's ml shell there is no runtime in the build (no :ml), so none to scan.
        assumeTrue("CARACOLE_ONNXRUNTIME is unset: no ONNX Runtime in this build (the ml shell's: " +
            "nix develop ./android#ml)", given.isNotEmpty())
        val folder = File(given)
        val aars = folder.walk().filter { it.isFile && it.name.endsWith(".aar") }.toList()
        assertEquals(1, aars.size, "one AAR in $folder: $aars")
        val bytes = aars.single().readBytes()
        // It holds the runtime for both ABIs and its classes, or the scan would pass for nothing.
        val names = entries(bytes)
        for (abi in listOf("arm64-v8a", "x86_64")) for (lib in listOf("libonnxruntime.so", "libonnxruntime4j_jni.so"))
            assertTrue("jni/$abi/$lib" in names, "jni/$abi/$lib in $names")
        assertTrue("classes.jar" in names)
        assertEquals(emptyList(), found(bytes))
    }

    @Test fun theApksHoldNoTelemetry() {
        val variants = (System.getProperty("caracole.apks") ?: error("no caracole.apks: run gradle :app:apkScan"))
            .split(File.pathSeparator)
        assertEquals(2, variants.size)
        for (dir in variants.map(::File)) {
            val apk = apkIn(dir)
            assertTrue(entries(apk.readBytes()).any { it.startsWith("classes") && it.endsWith(".dex") }, "$apk")
            assertEquals(emptyList(), found(apk.readBytes()), "$apk")
        }
    }

    private companion object {
        val NEEDLES = listOf("events.data.microsoft.com", "TelemetryInitializer", "ai/onnxruntime/telemetry/")

        /** Each (entry, needle) a zip's entries hold, an entry of a zip inside it named `outer!inner`. */
        fun found(zip: ByteArray, prefix: String = ""): List<Pair<String, String>> = buildList {
            ZipInputStream(ByteArrayInputStream(zip)).use { input ->
                while (true) {
                    val entry = input.nextEntry ?: break
                    if (entry.isDirectory) continue
                    val bytes = input.readBytes()
                    val name = prefix + entry.name
                    for (needle in NEEDLES)
                        if (holds(bytes, needle.toByteArray(Charsets.US_ASCII)) ||
                            holds(bytes, needle.toByteArray(Charsets.UTF_16LE))) add(name to needle)
                    if (isZip(bytes)) addAll(found(bytes, "$name!"))
                }
            }
        }

        fun entries(zip: ByteArray): List<String> = buildList {
            ZipInputStream(ByteArrayInputStream(zip)).use { input ->
                while (true) add((input.nextEntry ?: break).name)
            }
        }

        fun isZip(bytes: ByteArray) = bytes.size > 4 && bytes[0] == 'P'.code.toByte() &&
            bytes[1] == 'K'.code.toByte() && bytes[2] == 3.toByte() && bytes[3] == 4.toByte()

        fun holds(haystack: ByteArray, needle: ByteArray): Boolean {
            outer@ for (i in 0..haystack.size - needle.size) {
                for (j in needle.indices) if (haystack[i + j] != needle[j]) continue@outer
                return true
            }
            return false
        }

        /** The APK a variant's output folder names in its output-metadata.json, never a stale one beside it. */
        fun apkIn(dir: File): File {
            val metadata = File(dir, "output-metadata.json").readText()
            val name = Regex("\"outputFile\"\\s*:\\s*\"([^\"]+)\"").find(metadata)?.groupValues?.get(1)
                ?: error("no outputFile in $dir/output-metadata.json")
            return File(dir, name).also { assertTrue(it.isFile, "$it") }
        }

        fun zip(vararg files: Pair<String, ByteArray>): ByteArray = ByteArrayOutputStream().also { out ->
            ZipOutputStream(out).use { z ->
                for ((name, bytes) in files) {
                    z.putNextEntry(ZipEntry(name))
                    z.write(bytes)
                    z.closeEntry()
                }
            }
        }.toByteArray()
    }
}
