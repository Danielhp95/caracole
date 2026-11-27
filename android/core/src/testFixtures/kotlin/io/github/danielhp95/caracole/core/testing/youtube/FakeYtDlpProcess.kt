package io.github.danielhp95.caracole.core.testing.youtube

import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.youtube.Ran
import io.github.danielhp95.caracole.core.youtube.YtDlpProcess

/**
 * A yt-dlp that replays recorded runs, in order (tests/helpers/fake_ytdlp.py's FakeYtDlp, as the phone's seam sees
 * it): each [Planned] run's [Planned.during] is done with its argv (a file written, the gate asked), its lines given to
 * `onLine` (stdout's, then stderr's), and its [Ran] answered. A run nobody planned fails the test; nothing reaches a
 * real host. [argvs] and [timeouts] are what it was given.
 */
class FakeYtDlpProcess(planned: List<Planned>) : YtDlpProcess {
    class Planned(val ran: Ran, val during: (List<String>) -> Unit = {}, val notStarted: String? = null)

    private val left = ArrayDeque(planned)
    val argvs: MutableList<List<String>> = mutableListOf()
    val timeouts: MutableList<Double> = mutableListOf()
    val lines: MutableList<String> = mutableListOf()

    /** The runs not made yet. */
    val unmade: Int get() = left.size

    override fun run(argv: List<String>, timeoutS: Double, onLine: (String) -> Unit, waiting: () -> Unit): Ran {
        val next = left.removeFirstOrNull() ?: throw AssertionError("a yt-dlp run nobody planned: ${argv.size} arguments")
        next.notStarted?.let { throw YtDlpProcess.NotStarted(it) }
        argvs += argv
        timeouts += timeoutS
        next.during(argv)
        for (line in PyStr.splitlines(next.ran.stdout) + PyStr.splitlines(next.ran.stderr)) onLine(line)
        return next.ran
    }

    companion object {
        fun of(vararg runs: Ran): FakeYtDlpProcess = FakeYtDlpProcess(runs.map { Planned(it) })
    }
}
