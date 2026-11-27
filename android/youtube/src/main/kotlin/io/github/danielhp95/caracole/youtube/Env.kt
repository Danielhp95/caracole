package io.github.danielhp95.caracole.youtube

import android.content.Context
import java.io.File

/**
 * The environment of a yt-dlp run in `:youtube` (the phone-youtube design's §3.2), built from nothing, never the
 * Android process's: the glue's `environ` makes Python's `os.environ` these alone before yt-dlp is imported, so qjs and
 * any child yt-dlp starts inherit them too (a service can't exec itself again with another environment).
 *
 * - `HOME`, `filesDir/youtube-home`, empty: yt-dlp's user configuration would be read under it (the argv's
 *   `--ignore-config` reads none), and `XDG_CONFIG_HOME`, `XDG_DATA_HOME` there too.
 * - `TMPDIR`, `cacheDir/youtube-tmp`, swept before and after each run ([prepare], [sweep]): yt-dlp writes each player
 *   challenge there as a NamedTemporaryFile and runs `qjs --script FILE` on it; unset, Python's tempfile would try
 *   places an app can't write. `XDG_CACHE_HOME` under it (the argv's `--cache-dir` is yt-dlp's cache).
 * - `LANG` `C.UTF-8`, and `PATH` the native library folder ([Qjs.path]'s), then `/system/bin`.
 * - No proxy variable (`http_proxy`, `https_proxy`, `ALL_PROXY`, `NO_PROXY`, any case): the argv's `--proxy` alone
 *   decides, and yt-dlp, given one, reads none of the environment's (its `proxies = {"all": proxy}`: no `no` key, so
 *   no `NO_PROXY` bypass); Android's proxy setting is never read.
 *
 * And where a run's two streams go: [out] and [err], in `cacheDir/youtube-run/`, the service's to write, the client's
 * to read (both processes are the app's).
 */
object Env {
    fun home(context: Context): File = File(context.filesDir, "youtube-home")

    fun tmp(context: Context): File = File(context.cacheDir, "youtube-tmp")

    /** The run's files: yt-dlp's stdout and stderr, written by the service, read by the client. */
    fun runs(context: Context): File = File(context.cacheDir, "youtube-run")

    fun out(context: Context): File = File(runs(context), "stdout")

    fun err(context: Context): File = File(runs(context), "stderr")

    /** The environment, every variable of it, in order. */
    fun of(context: Context): Map<String, String> {
        val home = home(context)
        val tmp = tmp(context)
        return linkedMapOf(
            "HOME" to home.path,
            "TMPDIR" to tmp.path,
            "XDG_CONFIG_HOME" to File(home, ".config").path,
            "XDG_DATA_HOME" to File(home, ".local/share").path,
            "XDG_CACHE_HOME" to File(tmp, "cache").path,
            "LANG" to "C.UTF-8",
            "PATH" to "${context.applicationInfo.nativeLibraryDir}:/system/bin",
        )
    }

    /** [TMPDIR][tmp] emptied and made again, `HOME` made: then the environment. */
    fun prepare(context: Context): Map<String, String> {
        sweep(context)
        home(context).mkdirs()
        tmp(context).mkdirs()
        return of(context)
    }

    /** What a run left in [TMPDIR][tmp] (a challenge's script) deleted. */
    fun sweep(context: Context) {
        tmp(context).deleteRecursively()
    }
}
