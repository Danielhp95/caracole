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

    /** The run's own folders, as its argv names them (its `--cache-dir`, and its `-o`'s folder): what the client sends
     * with the request, which the service checks and the glue holds the argv to. */
    fun folders(argv: List<String>): RunFolders {
        fun after(name: String) = argv.indexOf(name).takeIf { it >= 0 }?.let { argv.getOrNull(it + 1) }
        return RunFolders(after("--cache-dir")?.let(::File)?.apply { mkdirs() }, after("-o")?.let { File(it).parentFile })
    }

    /** youtube.json's search argv, filled. */
    fun search(proxy: String): List<String> {
        val data = YouTubeData.read()
        return data.argv("search", data.searchTarget("anything"), File(context.cacheDir, "yt-dlp").path,
                         Qjs.path(context).path, proxy)
    }

    /** `--version` through [proxy]: the tests' own form, which the service runs under LOOPBACK alone. */
    fun version(proxy: String) = listOf("--ignore-config", "--no-plugin-dirs", "--proxy", proxy, "--version")

    /** KillTest's child, the glue's one `--exec` form: the app's qjs on a script of an endless loop in the run's own
     * folder [into]. */
    fun child(into: File): List<String> {
        val script = File(into, "loop.js").apply { writeText("while (true);\n") }
        return listOf("--exec", "before_dl:${Qjs.path(context).path} ${script.path}")
    }

    /** The app's `:youtube` process's pid, or null: from /proc, by its command line. */
    fun youtube(): Int? = others().entries.firstOrNull { it.value.endsWith(YtDlpClient.PROCESS) }?.key

    /** Waits until no process of this uid but this one is left, at most [ms]; what is left then. */
    fun settle(ms: Long): Map<Int, String> {
        val until = android.os.SystemClock.elapsedRealtime() + ms
        while (others().isNotEmpty() && android.os.SystemClock.elapsedRealtime() < until) {
            android.os.SystemClock.sleep(50)
        }
        return others()
    }

    /** The app's logcat lines (this uid reads its own processes' alone, the :youtube process's among them). */
    fun logcat(): String = ProcessBuilder("logcat", "-d", "-v", "brief").redirectErrorStream(true).start().let {
        val text = it.inputStream.readBytes().decodeToString()
        it.waitFor()
        text
    }

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
