package io.github.danielhp95.caracole

import android.content.Context
import io.github.danielhp95.caracole.core.youtube.YouTubeEngine
import io.github.danielhp95.caracole.youtube.YtDlpEngine
import java.io.File

/** The debug build's yt-dlp for the phone's jobs (:youtube's [YtDlpEngine]), which the main source set reaches by this
 * class's name alone ([Caracole.youtube]): a release, which carries no `:youtube`, has neither. */
object DebugYouTube {
    @JvmStatic
    fun engine(context: Context, cacheDir: File): YouTubeEngine =
        YtDlpEngine(context, cacheDir, BuildConfig.YTDLP_VERSION)
}
