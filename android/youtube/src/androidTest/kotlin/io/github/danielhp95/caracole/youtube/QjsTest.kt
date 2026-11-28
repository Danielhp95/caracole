package io.github.danielhp95.caracole.youtube

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * QuickJS-NG's qjs, built from android/youtube/pins.json's tag (native/CMakeLists.txt) and packaged as `libqjs.so`,
 * runs from this APK's native library folder ([Qjs.path]): executable there, the pinned version, a script's output; and
 * yt-dlp, told of it alone (`--no-js-runtimes --js-runtimes quickjs:<path>`), finds it and names it among its runtimes.
 * Nothing asks a site: yt-dlp's `-v` with no URL says its debug header (the runtimes among it) and exits 2. Run by
 * `android/scripts/device-test.sh --youtube`, on the emulator alone.
 */
@RunWith(AndroidJUnit4::class)
class QjsTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val tag = JSONObject(
        InstrumentationRegistry.getInstrumentation().context.assets.open("youtube/pins.json")
            .use { it.readBytes().decodeToString() }
    ).getJSONObject("quickjs").getString("tag")

    /** qjs run with [args], its stdout and stderr together, and its exit status. */
    private fun qjs(vararg args: String): Pair<Int, String> {
        val process = ProcessBuilder(listOf(Qjs.path(context).path) + args).redirectErrorStream(true).start()
        val said = process.inputStream.readBytes().decodeToString()
        assertTrue("qjs didn't end", process.waitFor(30, TimeUnit.SECONDS))
        return process.exitValue() to said
    }

    @Test
    fun theFileIsAnExecutableInTheNativeLibraryFolder() {
        val file = Qjs.path(context)
        assertEquals(File(context.applicationInfo.nativeLibraryDir, "libqjs.so"), file)
        assertTrue(file.path, file.isFile && file.canExecute())
    }

    @Test
    fun itsVersionIsThePinnedTags() {
        assertEquals(0 to tag.removePrefix("v") + "\n", qjs("--version"))
    }

    @Test
    fun itRunsAScript() {
        assertEquals(0 to "42\n", qjs("-e", "print(6*7)"))
    }

    @Test
    fun ytDlpNamesItAmongItsRuntimes() {
        if (!Python.isStarted()) Python.start(AndroidPlatform(context))
        val dir = File(context.cacheDir, "youtube-qjs-test").apply { deleteRecursively(); mkdirs() }
        val out = File(dir, "stdout")
        val err = File(dir, "stderr")
        val argv = arrayOf("-v", "--ignore-config", "--no-js-runtimes", "--js-runtimes", "quickjs:${Qjs.path(context)}")
        val status = Python.getInstance().getModule("caracole_ytdlp").callAttr("run", argv, out.path, err.path).toInt()
        val said = err.readText()
        // No URL: yt-dlp's usage error, after the header.
        assertEquals(said, 2, status)
        // Its name and version as yt-dlp joins them (join_nonempty's "-"), read from qjs's `--help`.
        assertTrue(said, said.lines().contains("[debug] JS runtimes: quickjs-ng-${tag.removePrefix("v")}"))
    }
}
