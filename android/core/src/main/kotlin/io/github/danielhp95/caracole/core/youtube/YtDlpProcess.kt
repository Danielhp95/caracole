package io.github.danielhp95.caracole.core.youtube

import java.io.IOException

/**
 * yt-dlp itself, one run at a time: the seam between the runner ([YtDlp], which decides what a run came to) and the
 * process that runs it (the app's `:youtube` process in a later task; a test's fake that replays recorded runs).
 *
 * The argv holds the gate's address, its user and secret among it: an implementation never puts it, whole or in part,
 * into an exception's message, a log line or anything it says. The runner reads every exception the process throws
 * with the secret taken out all the same, as a second guard, never as leave to.
 */
interface YtDlpProcess {
    /**
     * Runs yt-dlp once with [argv] (its arguments, no program name), stopped with whatever it started once it has run
     * [timeoutS] seconds: then [Ran.timedOut]. Each line it writes, as it comes, goes to [onLine]; [waiting] is told
     * once if the run must first wait for another run of the app's to end (one at a time). Throws [NotStarted] when
     * no process could be started at all, so nothing was sent.
     */
    fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit): Ran

    /** No yt-dlp could be started: nothing was sent. [message] says why (never the argv: the proxy's holds a secret). */
    class NotStarted(message: String) : IOException(message)
}

/** What a run gave: its exit status, its output and its error output, decoded as UTF-8 (a bad byte U+FFFD); or that it
 * was stopped at its timeout, [exit] and what it wrote then meaning nothing. */
data class Ran(val exit: Int, val stdout: String, val stderr: String, val timedOut: Boolean = false) {
    companion object {
        fun timedOut(): Ran = Ran(-1, "", "", timedOut = true)
    }
}

/**
 * The app's yt-dlp, as the phone's jobs see it (`PhoneDeps.youtube`, null in a build that carries none): what a
 * [YtDlp] runner is built of. [ready] is null when it can run here, else why not in plain words (the words a route
 * shows); [process] a yt-dlp of the app's, one run at a time across the app (the debug bench's runs among them);
 * [gate] a fresh gate for one run, opened in this, the main process, in the one mode the app decides
 * (`caracole.network`'s), its rule YOUTUBE's, which the runner closes once it has read the run's log; [qjs] the
 * JavaScript runtime the argv names; [cacheDir] the runner's folder (yt-dlp's cache under it, `runner.cache_folder`).
 */
interface YouTubeEngine {
    fun ready(): String?

    fun process(): YtDlpProcess

    fun gate(): YtDlpGate

    val qjs: java.io.File

    val cacheDir: java.io.File
}
