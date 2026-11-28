package io.github.danielhp95.caracole

import android.content.Context
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.youtube.YtDlpEngine
import java.io.File

/** The app's yt-dlp for the phone's jobs (:youtube's [YtDlpEngine]), in both builds: Python and qjs for the ABIs of
 * [ABIS] (BuildConfig.YOUTUBE_ABIS: arm64-v8a alone in the release, both in a debug build, app/build.gradle.kts). */
internal object PhoneYouTube {
    /** The ABIs this APK carries Python and qjs for. */
    val ABIS: Set<String> = BuildConfig.YOUTUBE_ABIS.split(",").filter { it.isNotEmpty() }.toSet()

    /** Whether a phone of [abis] (Build.SUPPORTED_ABIS, its primary first) runs this APK's yt-dlp: its primary ABI, the
     * one its native libraries are installed for, is one [carried] has; an x86_64 phone that translates arm64 runs the
     * APK's x86_64 libraries, of which a release has no Python. */
    fun carries(abis: List<String>, carried: Set<String> = ABIS): Boolean = abis.firstOrNull() in carried

    /** The engine, its runner's folder [cacheDir]; null on a phone [carries] says no to (Caracole.youtube), which then
     * says "this phone's caracole has no yt-dlp". */
    fun engine(context: Context, cacheDir: File, abis: List<String>): YouTubeEngine? =
        if (carries(abis)) YtDlpEngine(context, cacheDir, BuildConfig.YTDLP_VERSION) else null
}
