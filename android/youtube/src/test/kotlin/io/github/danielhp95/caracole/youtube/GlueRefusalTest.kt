package io.github.danielhp95.caracole.youtube

import io.github.danielhp95.caracole.core.youtube.HostGate
import io.github.danielhp95.caracole.core.youtube.YouTubeData
import java.io.File
import java.nio.file.Files
import java.util.concurrent.TimeUnit
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * caracole_ytdlp.py's `refusal(argv, rules)`, the check YtDlpService makes of every argv before yt-dlp runs it, and
 * `environ(names, values)`, the environment it runs in, by the shell's python3.13 over the pinned wheels (as GlueTest):
 * the argv read by yt-dlp's own option parser, nothing run, nothing asked. An argv runs only as one of the phone's own
 * templates (youtube.json's, [GlueRules]) holds it: each option the template sets with its value or a value its
 * placeholder's check passes, every other at the parser's default; under LOOPBACK, the tests' own forms too. Its
 * words never hold a value of the argv (the proxy's holds the gate's secret).
 */
class GlueRefusalTest {
    private val python = requireNotNull(System.getProperty("caracole.youtube.python"))
    private val glue = requireNotNull(System.getProperty("caracole.youtube.glue"))
    private val wheels = File(requireNotNull(System.getProperty("caracole.youtube.wheels")))
        .listFiles().orEmpty().map { it.path }.sorted()

    private val data = YouTubeData.read()
    private val root: File = Files.createTempDirectory("caracole-glue-root-").toFile().canonicalFile
    private val user = "0123456789abcdef0123456789abcdef"
    private val secret = "fedcba9876543210fedcba9876543210"
    private val gate = "http://$user:$secret@127.0.0.1:40123"
    private val qjs = "/data/app/x/lib/x86_64/libqjs.so"
    private val cache = File(root, "cache/yt-dlp").apply { mkdirs() }.path
    private val into = File(root, "cache/into").apply { mkdirs() }.path
    private val video = data.watchUrl("aaaaaaaaaaa")
    private val clip = "http://127.0.0.1:8080/clip.m4a"
    private val script = File(into, "loop.js").path

    @AfterTest
    fun clean() {
        root.deleteRecursively()
    }

    private val NOT_YOUTUBE = "its target isn't a YouTube search or video address"
    private val FOLDER = "it would write outside the run's folders"

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

    private fun rules(mode: HostGate.Mode, folders: RunFolders = RunFolders(File(cache), File(into))) =
        GlueRules.of(mode, qjs, folders)

    /** refusal's answer for [argv] (null for none), checking it printed nothing else. */
    private fun refusal(argv: List<String>, mode: HostGate.Mode, rules: String = rules(mode)): String? {
        val said = python(
            "import caracole_ytdlp\nwhy = caracole_ytdlp.refusal(sys.argv[3:], sys.argv[2])\n" +
                "print('NONE' if why is None else 'WHY ' + why)",
            listOf(rules) + argv,
        )
        val lines = said.trimEnd().lines()
        assertEquals(1, lines.size, "refusal wrote more than its answer: $said")
        return if (lines[0] == "NONE") null else lines[0].removePrefix("WHY ")
    }

    private fun runs(argv: List<String>, mode: HostGate.Mode) = assertEquals(null, refusal(argv, mode), "$argv")

    private fun refused(argv: List<String>, mode: HostGate.Mode = HostGate.Mode.LOOPBACK): String {
        val why = refusal(argv, mode)
        assertTrue(why != null, "not refused under $mode: $argv")
        assertFalse(why.contains(secret) || why.contains(user), why)
        return why
    }

    private fun refusedInBoth(argv: List<String>) {
        refused(argv, HostGate.Mode.LOOPBACK)
        refused(argv, HostGate.Mode.NETWORK)
    }

    private fun search(target: String = data.searchTarget("anything")) =
        data.argv("search", target, cache, qjs, gate)

    private fun download(target: String = video) = data.argv("download", video, cache, qjs, gate, into).let {
        it.dropLast(1) + target
    }

    /** [argv] with [extra] before its `--`. */
    private fun with(argv: List<String>, vararg extra: String): List<String> {
        val dash = argv.lastIndexOf("--")
        return argv.subList(0, dash) + extra + argv.subList(dash, argv.size)
    }

    @Test
    fun `each template filled runs in network mode`() {
        runs(search(), HostGate.Mode.NETWORK)
        runs(data.argv("video", video, cache, qjs, gate), HostGate.Mode.NETWORK)
        runs(download(), HostGate.Mode.NETWORK)
    }

    @Test
    fun `the tests' own forms run under loopback alone`() {
        val forms = listOf(
            download(clip),
            with(download("https://127.0.0.1:8443/clip.m4a"), "--no-check-certificates"),
            with(download(clip), "-v"),
            with(download(clip), "--exec", "before_dl:$qjs $script"),
            listOf("--ignore-config", "--no-plugin-dirs", "--proxy", gate, "--version"),
        )
        for (argv in forms) {
            runs(argv, HostGate.Mode.LOOPBACK)
            refused(argv, HostGate.Mode.NETWORK)
        }
        runs(download("http://10.0.2.2:8080/clip.m4a"), HostGate.Mode.LOOPBACK)
    }

    @Test
    fun `a proxy that isn't the gate's is refused`() {
        for (proxy in listOf("http://10.0.2.2:3128", "http://u5er:s3cret@127.0.0.1:40123",
                             "http://$user:$secret@127.0.0.2:40123", "socks5://$user:$secret@127.0.0.1:40123", "")) {
            refusedInBoth(data.argv("download", video, cache, qjs, proxy, into))
        }
        // The last --proxy is the one yt-dlp takes.
        refusedInBoth(with(download(), "--proxy", "http://10.0.2.2:3128"))
        refusedInBoth(with(download(), "--geo-verification-proxy", "http://10.0.2.2:3128"))
        val argv = download()
        val at = argv.indexOf("--proxy")
        refusedInBoth(argv.subList(0, at) + argv.subList(at + 2, argv.size))
    }

    @Test
    fun `a target the mode doesn't take is refused`() {
        refused(search(), HostGate.Mode.LOOPBACK)
        refused(download("https://www.youtube.com/watch?v=aaaaaaaaaaa"), HostGate.Mode.LOOPBACK)
        refused(download("http://u@127.0.0.1.example.org/a"), HostGate.Mode.LOOPBACK)
        refused(download(clip), HostGate.Mode.NETWORK)
        refused(download("https://www.youtube.com/watch?v=aaaaaaaaaaa&list=x"), HostGate.Mode.NETWORK)
        refused(search("https://example.org/"), HostGate.Mode.NETWORK)
        refused(download() + clip, HostGate.Mode.NETWORK)
        refused(with(download("file:///etc/hosts"), "--enable-file-urls"), HostGate.Mode.NETWORK)
    }

    @Test
    fun `a command run, Python loaded or a program named is refused in every mode`() {
        refusedInBoth(with(download(), "--use-postprocessor", "Exec:exec_cmd=id;when=pre_process"))
        refusedInBoth(with(download(), "--netrc-cmd", "id"))
        refusedInBoth(with(download(), "--exec", "curl https://example.org"))
        refusedInBoth(with(download(), "--plugin-dirs", root.path))
        refusedInBoth(with(download(), "-x", "--ffmpeg-location", "/system/bin/sh"))
        refusedInBoth(with(download(), "--downloader", "aria2c"))
        refusedInBoth(with(download(), "-U"))
        // Without --no-plugin-dirs yt-dlp scans HOME and sys.path for plugins.
        refusedInBoth(download().filter { it != "--no-plugin-dirs" })
        refusedInBoth(listOf("--ignore-config", "--proxy", gate, "--version"))
        // The one exec form, and nothing that chains a shell.
        refused(with(download(clip), "--exec", "before_dl:$qjs $script; id"))
        refused(with(download(clip), "--exec", "before_dl:$qjs -e x"))
        refused(with(download(clip), "--exec", "before_dl:/system/bin/sh $script"))
        refused(with(download(clip), "--exec", "before_dl:$qjs /etc/loop.js"))
        refused(with(download(clip), "--exec", "after_move:$qjs $script"))
    }

    @Test
    fun `a file read or written outside the run's folders is refused in every mode`() {
        refusedInBoth(with(download(), "--cookies", File(root, "jar").path))
        refusedInBoth(with(download(), "--cookies-from-browser", "firefox"))
        refusedInBoth(with(download(), "-o", "/sdcard/x.%(ext)s"))
        refusedInBoth(with(download(), "--download-archive", File(root, "a").path))
        refusedInBoth(with(download(), "--print-to-file", "%(id)s", File(root, "f").path))
        refusedInBoth(with(download(), "--cache-dir", "/sdcard/cache"))
        refusedInBoth(with(download(), "-a", File(root, "urls").path))
        refusedInBoth(with(download(), "--load-info-json", File(root, "info.json").path))
        refusedInBoth(with(download(), "--config-locations", File(root, "yt-dlp.conf").path))
        for (folder in listOf("/sdcard/into", "$root/../into", "$root/cache/%(id)s")) {
            refusedInBoth(data.argv("download", video, cache, qjs, gate, folder))
        }
        refusedInBoth(data.argv("download", video, "/sdcard/yt-dlp", qjs, gate, into))
        refusedInBoth(data.argv("download", video, cache, "/system/bin/sh", gate, into))
    }

    @Test
    fun `a search asks for the phone's own count of results, never another`() {
        runs(search(data.searchTarget("anything", data.searchResults)), HostGate.Mode.NETWORK)
        for (n in listOf(1, data.searchResults + 1, 99999)) {
            val why = refused(search(data.searchTarget("anything", n)), HostGate.Mode.NETWORK)
            assertEquals(NOT_YOUTUBE, why)
        }
        refused(search("ytsearch:anything"), HostGate.Mode.NETWORK)
        refused(search("ytsearch08:anything"), HostGate.Mode.NETWORK)
    }

    @Test
    fun `a run names its own two folders alone, never another of the app's storage`() {
        val other = File(root, "cache/other").apply { mkdirs() }.path
        val otherCache = File(root, "cache/other/yt-dlp").apply { mkdirs() }.path
        refusedInBoth(data.argv("download", video, cache, qjs, gate, other))
        refusedInBoth(data.argv("download", video, otherCache, qjs, gate, into))
        refusedInBoth(data.argv("download", video, cache, qjs, gate, "$into/deeper"))
        // A folder given its run's folders by a link to it: the same folder, so it runs; a link out of it is refused.
        val link = File(root, "cache/link")
        Files.createSymbolicLink(link.toPath(), File(into).toPath())
        runs(data.argv("download", video, cache, qjs, gate, link.path), HostGate.Mode.NETWORK)
        // No folders given at all (a run whose request named none): every template refused.
        val none = rules(HostGate.Mode.NETWORK, RunFolders())
        assertEquals(FOLDER, refusal(download(), HostGate.Mode.NETWORK, none))
        assertEquals(FOLDER, refusal(search(), HostGate.Mode.NETWORK, none))
        // KillTest's script outside the run's into folder.
        val outside = File(root, "cache/loop.js").path
        refused(with(download(clip), "--exec", "before_dl:$qjs $outside"))
    }

    @Test
    fun `an argv yt-dlp can't read, or one that prints and exits, is refused`() {
        refusedInBoth(with(download(), "--no-such-option"))
        refusedInBoth(with(download(), "--help"))
        // An alias is read as what it expands to: here another proxy, and the alias's own option.
        refusedInBoth(with(download(), "--alias", "get", "--proxy http://10.0.2.2:3128", "--get"))
    }

    @Test
    fun `a mode but LOOPBACK or NETWORK is refused`() {
        val rules = rules(HostGate.Mode.NETWORK).replace("\"NETWORK\"", "\"loopback\"")
        assertTrue(refusal(download(), HostGate.Mode.NETWORK, rules) != null)
    }

    @Test
    fun `environ replaces the whole environment, and tempfile follows its TMPDIR`() {
        val said = python(
            "import os, tempfile, caracole_ytdlp\n" +
                "os.environ['http_proxy'] = 'http://10.0.2.2:3128'\n" +
                "tempfile.gettempdir()\n" +
                "had = caracole_ytdlp.environ(['HOME', 'TMPDIR'], ['/h', sys.argv[2]])\n" +
                "print(sorted(os.environ.items()), tempfile.gettempdir(), 'http_proxy' in had)",
            listOf("/tmp"),
        )
        assertEquals("[('HOME', '/h'), ('TMPDIR', '/tmp')] /tmp True", said.trim())
    }
}
