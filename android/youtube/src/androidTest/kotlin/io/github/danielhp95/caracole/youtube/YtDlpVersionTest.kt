package io.github.danielhp95.caracole.youtube

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/**
 * Chaquopy's Python starts in the app's process and runs the yt-dlp and yt-dlp-ejs that android/youtube/pins.json pins
 * (its asset copy, youtube/pins.json): `caracole_ytdlp.version()`, and yt-dlp's own `--version`, the one run with no
 * network to it (no URL, no search: yt-dlp prints its version and exits). Run by
 * `android/scripts/device-test.sh --youtube`, on the emulator alone.
 */
@RunWith(AndroidJUnit4::class)
class YtDlpVersionTest {
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val pins = JSONObject(
        InstrumentationRegistry.getInstrumentation().context.assets.open("youtube/pins.json")
            .use { it.readBytes().decodeToString() }
    )

    @Before
    fun start() {
        if (!Python.isStarted()) Python.start(AndroidPlatform(context))
    }

    @Test
    fun theVersionsAreThePinsOnes() {
        val said = Python.getInstance().getModule("caracole_ytdlp").callAttr("version").asMap()
            .entries.associate { (k, v) -> k.toString() to v.toString() }
        assertEquals(setOf("python", "ytdlp", "ejs"), said.keys)
        assertEquals(pins.getString("python"), said.getValue("python").split('.').take(2).joinToString("."))
        assertEquals(pins.getJSONObject("ytdlp").getString("version"), said["ytdlp"])
        assertEquals(pins.getJSONObject("ejs").getString("version"), said["ejs"])
    }

    /** The design's §3.4: the standard library's modules yt-dlp never imports are left out of the APK. */
    @Test
    fun theStandardLibraryHoldsNoneOfTheModulesLeftOut() {
        val util = Python.getInstance().getModule("importlib.util")
        for (name in listOf("tkinter", "idlelib", "test", "ensurepip", "lib2to3", "pydoc_data")) {
            assertNull(name, util.callAttr("find_spec", name))
        }
        assertNotNull(util.callAttr("find_spec", "json"))
    }

    @Test
    fun ytDlpsOwnVersionIsThePinnedOne() {
        val dir = File(context.cacheDir, "youtube-version-test").apply { deleteRecursively(); mkdirs() }
        val out = File(dir, "stdout")
        val err = File(dir, "stderr")
        val status = Python.getInstance().getModule("caracole_ytdlp")
            .callAttr("run", arrayOf("--version"), out.path, err.path).toInt()
        assertEquals(err.readText(), 0, status)
        assertEquals(pins.getJSONObject("ytdlp").getString("version") + "\n", out.readText())
    }
}
