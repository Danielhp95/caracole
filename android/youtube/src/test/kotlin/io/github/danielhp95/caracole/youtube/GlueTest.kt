package io.github.danielhp95.caracole.youtube

import java.io.File
import java.nio.file.Files
import java.util.concurrent.TimeUnit
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * caracole_ytdlp.py run by the shell's python3.13 (Chaquopy's buildPython, the app's minor version: youtube/
 * build.gradle.kts hands it as `caracole.youtube.python`), the glue and the pinned wheels on its path: `run` never
 * raises, whatever goes wrong under it, as the computer's yt-dlp process says a traceback on stderr and exits 1. No
 * argv here asks a site: `--version`, or a `main` replaced by one that raises.
 */
class GlueTest {
    private val python = requireNotNull(System.getProperty("caracole.youtube.python"))
    private val glue = requireNotNull(System.getProperty("caracole.youtube.glue"))
    private val wheels = File(requireNotNull(System.getProperty("caracole.youtube.wheels")))
        .listFiles().orEmpty().map { it.path }.sorted()

    private class Ran(val status: String, val out: String, val err: String)

    /** `run(argv)` in a fresh python3.13 -I -B (no `__pycache__` written into the glue's folder, Chaquopy's source set
     * and this task's input), with [paths] first on sys.path and [before] run after the glue's import. */
    private fun run(paths: List<String>, argv: List<String>, before: String = ""): Ran {
        val dir = Files.createTempDirectory("caracole-glue-").toFile()
        try {
            val out = File(dir, "stdout")
            val err = File(dir, "stderr")
            val script = """
                |import sys
                |sys.path[:0] = sys.argv[1].split("\n")
                |import caracole_ytdlp
                |$before
                |print(caracole_ytdlp.run(sys.argv[4:], sys.argv[2], sys.argv[3]))
            """.trimMargin()
            val process = ProcessBuilder(
                listOf(python, "-I", "-B", "-c", script, paths.joinToString("\n"), out.path, err.path) + argv
            ).redirectErrorStream(true).start()
            val said = process.inputStream.readBytes().decodeToString()
            assertTrue(process.waitFor(60, TimeUnit.SECONDS), "python3.13 didn't end")
            assertEquals(0, process.exitValue(), said)
            return Ran(said.trim(), out.readText(), err.readText())
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test
    fun `yt-dlp's own --version, from the pinned wheels`() {
        val ran = run(listOf(glue) + wheels, listOf("--version"))
        assertEquals("0", ran.status, ran.err)
        assertTrue(Regex("""\d{4}\.\d+\.\d+\n""").matches(ran.out), ran.out)
    }

    @Test
    fun `no yt-dlp to import is a traceback in the err file and status 1, never raised`() {
        val ran = run(listOf(glue), listOf("--version"))
        assertEquals("1", ran.status)
        assertTrue(ran.err.startsWith("Traceback (most recent call last):"), ran.err)
        assertTrue(ran.err.trimEnd().endsWith("ModuleNotFoundError: No module named 'yt_dlp'"), ran.err)
    }

    @Test
    fun `an exception out of yt-dlp's main is a traceback in the err file and status 1, never raised`() {
        val boom = "import yt_dlp\ndef boom(argv):\n    raise RuntimeError('boom')\nyt_dlp.main = boom"
        val ran = run(listOf(glue) + wheels, listOf("--version"), boom)
        assertEquals("1", ran.status)
        assertTrue(ran.err.startsWith("Traceback (most recent call last):"), ran.err)
        assertTrue(ran.err.trimEnd().endsWith("RuntimeError: boom"), ran.err)
    }

    @Test
    fun `a SystemExit's message is written to the err file and its status is 1`() {
        val stop = "import yt_dlp\ndef stop(argv):\n    raise SystemExit('stopped')\nyt_dlp.main = stop"
        val ran = run(listOf(glue) + wheels, listOf("--version"), stop)
        assertEquals("1", ran.status)
        assertEquals("stopped\n", ran.err)
    }
}
