package io.github.danielhp95.caracole.youtube

import android.content.Context
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.core.youtube.YtDlpGate
import io.github.danielhp95.caracole.core.youtube.YtDlpProcess
import java.io.File
import java.io.IOException

/**
 * The app's yt-dlp for its jobs (`PhoneDeps.youtube`; the debug build's alone until the release carries `:youtube`):
 * [process] a [ProcessYtDlp] (a job's own, which it closes), [gate] a [GateService.gate] opened in this, the main
 * process, in the app's one mode ([GateService.gatesMode]: `caracole.network`'s, loopback under the tests), its rule
 * YOUTUBE's, [qjs] QuickJS-NG's ([Qjs.path]), [cacheDir] the folder the runner is given (yt-dlp's cache under it),
 * [version] the packaged yt-dlp's (the app's BuildConfig, pins.json's), which out of date goes by.
 *
 * [ready] is null when yt-dlp can run here, else why not, the first that holds of: a 32-bit process (Chaquopy's
 * Python is 64-bit alone), no Python packaged ([PYTHON]: Chaquopy's `chaquopy/` assets), no qjs or one that can't be
 * run.
 */
class YtDlpEngine(context: Context, override val cacheDir: File,
                  override val version: String? = null) : YouTubeEngine {
    private val context = context.applicationContext

    override val qjs: File get() = Qjs.path(context)

    override fun ready(): String? = when {
        !android.os.Process.is64Bit() -> NOT_64_BIT
        !python() -> NO_PYTHON
        !qjs.isFile -> NO_QJS
        !qjs.canExecute() -> QJS_NOT_EXECUTABLE
        else -> null
    }

    override fun process(): YtDlpProcess = ProcessYtDlp(context)

    override fun gate(): YtDlpGate = GateService.gate()

    private fun python(): Boolean = try {
        !context.assets.list(PYTHON).isNullOrEmpty()
    } catch (_: IOException) {
        false
    }

    companion object {
        /** Chaquopy's assets: Python's standard library, yt-dlp and the glue. */
        const val PYTHON = "chaquopy"

        const val NOT_64_BIT = "yt-dlp's Python runs in a 64-bit app alone, and this one runs 32-bit"
        const val NO_PYTHON = "this caracole carries no Python for yt-dlp"
        const val NO_QJS = "this caracole carries no QuickJS for yt-dlp's challenges"
        const val QJS_NOT_EXECUTABLE = "QuickJS can't be run on this phone"
    }
}
