package io.github.danielhp95.caracole.youtube

import android.os.Process
import android.util.Log
import androidx.test.platform.app.InstrumentationRegistry
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import java.io.File

/** What YtDlpServiceTest and KillTest share: the context, the argv, the clip, and this uid's processes. */
object Runs {
    const val TAG = "caracole-ytdlp-test"

    val context = InstrumentationRegistry.getInstrumentation().targetContext!!
    private val assets = InstrumentationRegistry.getInstrumentation().context.assets

    /** The 6 s clip of the androidTest assets (youtube/clip.m4a: its README). */
    val clip: ByteArray by lazy { assets.open("youtube/clip.m4a").use { it.readBytes() } }

    fun certificate() = assets.open("youtube/loopback.p12")

    /** A fresh folder for a download, in the cache. */
    fun into(name: String): File = File(context.cacheDir, "youtube-test-$name").apply { deleteRecursively(); mkdirs() }

    /**
     * youtube.json's download argv (phone_argv's, `-f bestaudio[ext=m4a]` and all), filled for a YouTube address, with
     * the test's own [target] in its place (phone_argv takes a YouTube video's address alone), and [extra] before `--`.
     */
    fun download(proxy: String, target: String, into: File, extra: List<String> = emptyList()): List<String> {
        val data = YouTubeData.read()
        val argv = data.argv(
            "download", data.watchUrl("aaaaaaaaaaa"), File(context.cacheDir, "yt-dlp").path, Qjs.path(context).path,
            proxy, into.path,
        )
        val dash = argv.lastIndexOf("--")
        check(dash == argv.size - 2) { "the download template's target is no longer last, after --" }
        return argv.subList(0, dash) + extra + listOf("--", target)
    }

    /** `--version` through [proxy]. */
    fun version(proxy: String) = listOf("--ignore-config", "--proxy", proxy, "--version")

    /** Every process of this app's uid but this one: pid to its command line (an app's /proc shows its own uid's). */
    fun others(): Map<Int, String> {
        val mine = Process.myUid()
        val me = Process.myPid()
        val found = sortedMapOf<Int, String>()
        for (dir in File("/proc").listFiles().orEmpty()) {
            val pid = dir.name.toIntOrNull() ?: continue
            if (pid == me) continue
            val uid = try {
                File(dir, "status").readLines().firstOrNull { it.startsWith("Uid:") }?.split(Regex("\\s+"))?.get(1)
            } catch (_: Exception) {
                null
            }
            if (uid?.toIntOrNull() != mine) continue
            val cmd = try {
                File(dir, "cmdline").readBytes().decodeToString().replace('\u0000', ' ').trim()
            } catch (_: Exception) {
                ""
            }
            found[pid] = cmd
        }
        return found
    }

    /** A process's group, from /proc/PID/stat (its fifth field), or -1. */
    fun group(pid: Int): Int = try {
        File("/proc/$pid/stat").readText().substringAfterLast(')').trim().split(' ')[2].toInt()
    } catch (_: Exception) {
        -1
    }

    fun said(line: String) {
        Log.i(TAG, line)
    }
}
