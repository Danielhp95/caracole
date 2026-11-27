package io.github.danielhp95.caracole.youtube

import java.io.File
import java.util.concurrent.TimeUnit
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * caracole_ytdlp.py's `refusal(argv, loopback, qjs)`, the check YtDlpService makes of every argv before yt-dlp runs it,
 * and `environ(names, values)`, the environment it runs in, by the shell's python3.13 over the pinned wheels (as
 * GlueTest): the argv read by yt-dlp's own option parser, nothing run, nothing asked. Its words never hold a value of
 * the argv (the proxy's holds the gate's secret).
 */
class GlueRefusalTest {
    private val python = requireNotNull(System.getProperty("caracole.youtube.python"))
    private val glue = requireNotNull(System.getProperty("caracole.youtube.glue"))
    private val wheels = File(requireNotNull(System.getProperty("caracole.youtube.wheels")))
        .listFiles().orEmpty().map { it.path }.sorted()

    private val gate = "http://u5er:s3cret@127.0.0.1:40123"
    private val qjs = "/data/app/x/lib/x86_64/libqjs.so"

    /** What `script` prints, run with the glue and the wheels on its path and [args] as sys.argv[2:]. */
    private fun python(script: String, args: List<String>): String {
        val process = ProcessBuilder(
            listOf(python, "-I", "-B", "-c", "import sys\nsys.path[:0] = sys.argv[1].split('\\n')\n$script",
                   (listOf(glue) + wheels).joinToString("\n")) + args
        ).redirectErrorStream(true).start()
        val said = process.inputStream.readBytes().decodeToString()
        assertTrue(process.waitFor(60, TimeUnit.SECONDS), "python3.13 didn't end")
        assertEquals(0, process.exitValue(), said)
        return said
    }

    /** refusal's answer for [argv] (`None` printed as the empty line), and whatever else it wrote (nothing). */
    private fun refusal(argv: List<String>, loopback: Boolean): String? {
        val said = python(
            "import caracole_ytdlp\nwhy = caracole_ytdlp.refusal(sys.argv[4:], sys.argv[2] == '1', sys.argv[3])\n" +
                "print('NONE' if why is None else 'WHY ' + why)",
            listOf(if (loopback) "1" else "0", qjs) + argv,
        )
        val last = said.trimEnd().lines().last()
        assertEquals(1, said.trimEnd().lines().size, "refusal wrote more than its answer: $said")
        return if (last == "NONE") null else last.removePrefix("WHY ")
    }

    private fun refused(argv: List<String>, loopback: Boolean = true): String {
        val why = refusal(argv, loopback)
        assertTrue(why != null, "not refused: $argv")
        assertFalse(why.contains("s3cret") || why.contains("u5er"), why)
        return why
    }

    private val base = listOf("--ignore-config", "--proxy", gate)

    @Test
    fun `the gate's proxy and a loopback target run`() {
        assertEquals(null, refusal(base + listOf("--", "http://127.0.0.1:8080/clip.m4a"), loopback = true))
        assertEquals(null, refusal(base + listOf("--", "https://10.0.2.2:8443/clip.m4a"), loopback = true))
        assertEquals(null, refusal(base + "--version", loopback = true))
    }

    @Test
    fun `no proxy, another proxy, or the gate's shape at another host is refused`() {
        refused(listOf("--ignore-config", "--", "http://127.0.0.1:8080/clip.m4a"))
        refused(listOf("--ignore-config", "--proxy", "http://10.0.2.2:3128", "--version"))
        refused(listOf("--ignore-config", "--proxy", "http://u5er:s3cret@127.0.0.2:40123", "--version"))
        refused(listOf("--ignore-config", "--proxy", "socks5://u5er:s3cret@127.0.0.1:40123", "--version"))
        refused(listOf("--ignore-config", "--proxy", "", "--version"))
        // The last --proxy is the one yt-dlp takes.
        refused(base + listOf("--proxy", "http://10.0.2.2:3128", "--version"))
        refused(base + listOf("--geo-verification-proxy", "http://10.0.2.2:3128", "--version"))
    }

    @Test
    fun `a target that isn't a loopback address is refused under loopback, not otherwise`() {
        refused(base + listOf("--", "ytsearch1:anything"))
        refused(base + listOf("--", "https://www.youtube.com/watch?v=aaaaaaaaaaa"))
        refused(base + listOf("--", "http://127.0.0.1:8080/a", "https://example.org/b"))
        refused(base + listOf("--", "http://u@127.0.0.1.example.org/a"))
        assertEquals(null, refusal(base + listOf("--", "ytsearch1:anything"), loopback = false))
    }

    @Test
    fun `what would reach around the gate is refused in every mode`() {
        for (loopback in listOf(true, false)) {
            refused(base + listOf("-a", "/tmp/urls", "--version"), loopback)
            refused(base + listOf("--load-info-json", "/tmp/info.json"), loopback)
            refused(base + listOf("--config-locations", "/tmp/yt-dlp.conf", "--version"), loopback)
            refused(base + listOf("-U"), loopback)
            refused(base + listOf("--downloader", "aria2c", "--", "http://127.0.0.1:8080/a"), loopback)
            refused(base + listOf("--exec", "curl https://example.org", "--", "http://127.0.0.1:8080/a"), loopback)
        }
        // A test's own qjs, before the download and under loopback alone (KillTest's child).
        val child = listOf("--exec", "before_dl:$qjs -e 'while (true);'", "--", "http://127.0.0.1:8080/a")
        assertEquals(null, refusal(base + child, loopback = true))
        refused(base + child, loopback = false)
    }

    @Test
    fun `an argv yt-dlp can't read is refused, and nothing is printed`() {
        refused(base + "--no-such-option")
        refused(base + listOf("--alias", "get", "--proxy http://10.0.2.2:3128", "--get", "--version"))
        // --help and --version print and exit, with no request: read through, the gate's proxy still asked of them.
        assertEquals(null, refusal(base + "--help", loopback = true))
        refused(listOf("--ignore-config", "--help"))
    }

    @Test
    fun `environ replaces the whole environment, and tempfile follows its TMPDIR`() {
        val said = python(
            "import os, tempfile, caracole_ytdlp\n" +
                "os.environ['http_proxy'] = 'http://10.0.2.2:3128'\n" +
                "tempfile.gettempdir()\n" +
                "caracole_ytdlp.environ(['HOME', 'TMPDIR'], ['/h', sys.argv[2]])\n" +
                "print(sorted(os.environ.items()), tempfile.gettempdir())",
            listOf("/tmp"),
        )
        assertEquals("[('HOME', '/h'), ('TMPDIR', '/tmp')] /tmp", said.trim())
    }
}
