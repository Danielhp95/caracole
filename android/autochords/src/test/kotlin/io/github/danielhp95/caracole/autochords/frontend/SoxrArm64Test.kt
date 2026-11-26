package io.github.danielhp95.caracole.autochords.frontend

import io.github.danielhp95.caracole.autochords.frontend.SoxrRecords.TOLERANCE
import org.junit.Assume.assumeTrue
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * The phone's arm64 libsoxr, run on this machine: caracole_soxr_driver (native/soxr_driver.c over the JNI's
 * caracole_soxr_resample, built static by the NDK for arm64-v8a from the same sources and flags: build.gradle.kts's
 * arm64SoxrDriver) under qemu-aarch64 (android/flake.nix's shell), over every record of soxr.jsonl: python-soxr's
 * answers, made on x86_64 by its SIMD engine (cr32s, SSE), within [TOLERANCE], each length equal; by the patched NEON
 * engine (cr32s, soxr/aarch64.patch) and by the scalar one (cr32, SOXR_USE_SIMD=0). Skipped, saying why, where the
 * driver (no NDK) or qemu-aarch64 is missing; no device is involved.
 */
class SoxrArm64Test {
    private val driver = System.getProperty("caracole.soxr.arm64")?.let(::File)
    private val qemu = System.getenv("PATH").orEmpty().split(File.pathSeparator).map { File(it, "qemu-aarch64") }
        .firstOrNull { it.canExecute() }

    @Test
    fun `the NEON engine is python-soxr's to within 1e-6`() = engine("NEON (cr32s)", simd = true)

    @Test
    fun `the scalar engine is python-soxr's to within 1e-6`() = engine("scalar (cr32)", simd = false)

    private fun engine(name: String, simd: Boolean) {
        assumeTrue("no arm64 driver: the NDK r28c isn't under ANDROID_HOME (nix develop ./android)",
                   driver?.canExecute() == true)
        assumeTrue("no qemu-aarch64 on PATH (nix develop ./android)", qemu != null)
        val worst = linkedMapOf<String, Double>()
        for (c in SoxrRecords.conversions) {
            val got = run(c.x, c.from, c.to, simd)
            assertEquals(c.y.size, got.size, "$name, ${c.what}: the length")
            val d = SoxrRecords.worst(got, c.y)
            worst[c.family] = maxOf(worst[c.family] ?: 0.0, d)
            assertTrue(d <= TOLERANCE, "$name, ${c.what}: a sample differs by $d")
        }
        println("arm64 $name: the largest difference from python-soxr, by family: $worst")
    }

    private fun run(x: FloatArray, from: Double, to: Double, simd: Boolean): FloatArray {
        val input = ByteBuffer.allocate(4 * x.size).order(ByteOrder.LITTLE_ENDIAN)
        x.forEach { input.putFloat(it) }
        val process = ProcessBuilder(qemu!!.path, driver!!.path, from.toString(), to.toString()).apply {
            environment()["SOXR_USE_SIMD"] = if (simd) "1" else "0"
        }.start()
        val writer = Thread { process.outputStream.use { it.write(input.array()) } }.apply { start() }
        val errors = Thread { process.errorStream.readBytes() }.apply { start() }
        val out = process.inputStream.readBytes()
        writer.join()
        errors.join()
        assertEquals(0, process.waitFor(), "the driver at $from to $to")
        val b = ByteBuffer.wrap(out).order(ByteOrder.LITTLE_ENDIAN)
        return FloatArray(out.size / 4) { b.float }
    }
}
