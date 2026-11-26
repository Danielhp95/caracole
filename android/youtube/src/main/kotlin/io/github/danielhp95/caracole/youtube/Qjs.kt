package io.github.danielhp95.caracole.youtube

import android.content.Context
import java.io.File

/**
 * QuickJS-NG's qjs, yt-dlp's JavaScript runtime on the phone (the phone-youtube design's §3.1): `libqjs.so`, an
 * executable built by native/CMakeLists.txt, which the package manager extracts into the app's native library folder
 * (useLegacyPackaging), the one place Android lets an app run a program of its own. yt-dlp is told of it alone:
 * `--no-js-runtimes --js-runtimes quickjs:<path>`.
 */
object Qjs {
    /** Where qjs is in this app, executable. */
    fun path(context: Context): File = File(context.applicationInfo.nativeLibraryDir, "libqjs.so")
}
