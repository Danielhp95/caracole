package io.github.danielhp95.caracole.server.testing.replays

import io.github.danielhp95.caracole.core.inbox.GuitarFiles
import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Corpus
import io.github.danielhp95.caracole.core.testing.Fixtures
import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.web.Inline
import io.github.danielhp95.caracole.server.guitar.AlphaTab
import io.github.danielhp95.caracole.server.guitar.AlphaTabBundle
import io.github.danielhp95.caracole.server.guitar.GuitarPage
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.routes.GuitarRoutes
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.TestParts
import io.github.danielhp95.caracole.server.testing.bytes
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import kotlinx.serialization.json.longOrNull
import java.io.File
import java.io.RandomAccessFile
import java.nio.file.Files
import java.security.MessageDigest
import java.util.Base64

/**
 * The Guitar Pro page and alphaTab's bundle (vectors/web/guitar.jsonl; tests/test_conformance_guitar.py's docstring
 * has the records' shapes), replayed against the phone's port:
 *
 * - alphatab.bundle, font_face and load: AlphaTabBundle's, over the stand-ins' bytes; alphaTab 1.8.4's own bundle over
 *   `CARACOLE_ALPHATAB_DIR`'s files when the environment names them (the JVM's tests, in `nix develop ./android`), their
 *   SHA-256 Python's first: on the device the APK's bundle is GuitarPageTest's to check;
 * - guitar_page's style, script, policy and build_page: GuitarPage's, the page by its digest (one whole);
 * - inbox.guitar_files: GuitarFiles.of over the vector's library;
 * - each GET: the phone's App with GuitarRoutes alone (the stand-ins' bundle, or none), over that library, its status,
 *   headers in order and body's digest caracole serve's, and a refusal's message its data's.
 */
object GuitarReplay : AreaReplay {
    override val area = "guitar"
    const val VECTOR = "web/guitar.jsonl"

    /** alphaTab's own files, where the environment names them (nix/alphatab.nix's, through the dev shell). */
    var alphaTabDir: () -> File? = { System.getenv("CARACOLE_ALPHATAB_DIR")?.let(::File)?.takeIf { it.isDirectory } }

    override fun replay(misses: Misses) {
        val lines = Corpus.lines(VECTOR).filter { it["header"] != JsonPrimitive(true) }
        var standins: AlphaTab? = null
        var library: JsonObject? = null
        val routes = ArrayList<JsonObject>()
        val found = ArrayList<JsonObject>()
        for (r in lines) {
            val fn = r.getValue("fn").jsonPrimitive.content
            when (fn) {
                "caracole.web.alphatab.bundle" -> {
                    val (library_, fontUri, soundFont) = r.getValue("args").jsonArray.map { it.jsonPrimitive.content }
                    misses.expect(fn, fontUri.take(40), r["out"]) { AlphaTabBundle.bundle(library_, fontUri, soundFont) }
                }
                "caracole.web.alphatab.font_face" -> {
                    val fontUri = r.getValue("args").jsonArray[0].jsonPrimitive.content
                    misses.expect(fn, fontUri.take(40), r["out"]) { AlphaTabBundle.fontFace(fontUri) }
                }
                "caracole.web.alphatab.load" -> load(misses, r)?.let { standins = it }
                "caracole.web.guitar_page.style" -> misses.expect(fn, "", r["out"]) { digested(GuitarPage.style()) }
                "caracole.web.guitar_page.script" -> misses.expect(fn, "", r["out"]) { digested(GuitarPage.script()) }
                "caracole.web.guitar_page.policy" -> {
                    val at = standins ?: return misses.check(false) { "$fn: no stand-ins' bundle before it" }
                    misses.expect(fn, "", r["out"]) { GuitarPage.policy(at) }
                }
                "caracole.web.guitar_page.build_page" -> {
                    val at = standins ?: return misses.check(false) { "$fn: no stand-ins' bundle before it" }
                    page(misses, r, at)
                }
                "library" -> library = r
                "caracole.inbox.guitar_files" -> found += r
                "GET" -> routes += r
                else -> misses.check(false) { "$VECTOR: a record of $fn, which the replay doesn't know" }
            }
        }
        val lib = library ?: return misses.check(false) { "$VECTOR has no library" }
        val at = standins ?: return misses.check(false) { "$VECTOR has no stand-ins' bundle" }
        inLibrary(lib) { test, scopeOf ->
            for (r in found) guitarFiles(misses, test, r)
            val name = lib.getValue("library_name").jsonArray.let { LibraryName(it[0].jsonPrimitive.content, it[1].jsonPrimitive.contentOrNull) }
            for (withBundle in listOf(true, false)) {
                val asked = routes.filter { it.getValue("alphatab").jsonPrimitive.boolean == withBundle }
                if (asked.isEmpty()) continue
                val app = TestApp(test.dir, modules = { db ->
                    listOf(GuitarRoutes(TestParts.of(db, test.dir, scopeOf()), alphaTab = { if (withBundle) at else null },
                                        libraryName = { name }))
                }, libraryName = name.name, open = { test.database })
                for (r in asked) get(misses, app, r)
            }
        }
    }

    // --- the bundle ---------------------------------------------------------------------------------------------------

    /** A load record replayed; the stand-ins' bundle it made, for the records after it. */
    private fun load(misses: Misses, r: JsonObject): AlphaTab? {
        val case = r.getValue("case").jsonPrimitive.content
        val fn = "alphatab.load ($case)"
        if (case == "nix/alphatab.nix") {
            val dir = alphaTabDir() ?: return null
            for ((name, sha) in r.getValue("files").jsonObject) {
                val got = sha256(File(dir, name).readBytes())
                misses.check(got == sha.jsonPrimitive.content) {
                    "$fn: $dir/$name's SHA-256 is $got, the corpus's ${sha.jsonPrimitive.content}: regenerate the corpus " +
                        "with this shell's alphaTab, or this shell's is another"
                }
            }
            for ((name, sha) in r.getValue("licenses").jsonObject) {
                val file = File(File(dir, "licenses"), name)
                misses.check(file.isFile && sha256(file.readBytes()) == sha.jsonPrimitive.content) { "$fn: licenses/$name" }
            }
            misses.expect(fn, dir, r["out"]) { described(AlphaTabBundle.load(dir), body = false) }
            return null
        }
        val files = r.getValue("files").jsonObject.mapValues { Base64.getDecoder().decode(it.value.jsonPrimitive.content) }
        if (r["err"] != null) {
            misses.check(runCatching { AlphaTabBundle.load(files) }.exceptionOrNull() is AlphaTabBundle.Missing) {
                "$fn: made a bundle, Python's alphatab.load raised Missing"
            }
            return null
        }
        val at = try {
            AlphaTabBundle.load(files)
        } catch (e: AlphaTabBundle.Missing) {
            misses.check(false) { "$fn raised $e" }
            return null
        }
        misses.expect(fn, "", r["out"]) { described(at, body = true) }
        return at
    }

    private fun described(at: AlphaTab, body: Boolean): JsonObject = JsonObject(buildMap {
        put("name", JsonPrimitive(at.name))
        put("href", JsonPrimitive(at.href))
        put("integrity", JsonPrimitive(at.integrity))
        put("script_source", JsonPrimitive(at.scriptSource))
        put("font_face", JsonPrimitive(at.fontFace))
        put("sha256", JsonPrimitive(sha256(at.body)))
        put("length", JsonPrimitive(at.body.size))
        if (body) put("body", JsonPrimitive(at.body.toString(Charsets.UTF_8)))
    })

    // --- the page -----------------------------------------------------------------------------------------------------

    private fun page(misses: Misses, r: JsonObject, at: AlphaTab) {
        val kw = r.getValue("kw").jsonObject
        fun text(name: String) = kw.getValue(name).jsonPrimitive.content
        val data = kw.getValue("data").jsonObject.let { d ->
            d["fixture"]?.jsonPrimitive?.content?.let { Corpus.fixture(it) }
                ?: Base64.getDecoder().decode(d.getValue("base64").jsonPrimitive.content)
        }
        val name = (kw["library_name"] as? JsonArray)?.let { LibraryName(it[0].jsonPrimitive.content, it[1].jsonPrimitive.contentOrNull) }
        val page = GuitarPage.build(
            title = text("title"), artist = text("artist"), songId = kw.getValue("song_id").jsonPrimitive.long,
            path = text("path"), label = text("label"), data = data, at = at,
            sheet = (kw["sheet"] as? JsonPrimitive)?.contentOrNull, libraryName = name,
        )
        val bytes = page.toByteArray(Charsets.UTF_8)
        val case = "build_page(${text("path")})"
        misses.expect(case, "", r["out"]) {
            JsonObject(mapOf("sha256" to JsonPrimitive(sha256(bytes)), "length" to JsonPrimitive(bytes.size)))
        }
        r["page"]?.jsonPrimitive?.content?.let { whole ->
            misses.check(whole == page) { "$case whole: first differs at ${whole.zip(page).indexOfFirst { (a, b) -> a != b }}" }
        }
    }

    private fun digested(text: String): JsonObject = JsonObject(mapOf(
        "sha256_source" to JsonPrimitive(Inline.sha256Source(text)),
        "length" to JsonPrimitive(text.codePointCount(0, text.length)),
    ))

    // --- the library and the routes -----------------------------------------------------------------------------------

    /** The library a test of [body] reads: a fresh database in a folder of its own with the vector's records, its
     * files, those out of it, and what it makes ([make]); a scope for each App's parts, cancelled after. */
    private class Library(val dir: File, val database: io.github.danielhp95.caracole.core.db.Database)

    private fun inLibrary(record: JsonObject, body: (Library, () -> CoroutineScope) -> Unit) {
        val dir = Files.createTempDirectory("caracole-guitar").toFile()
        val scope = CoroutineScope(SupervisorJob())
        val database = io.github.danielhp95.caracole.core.testing.TestDb.fresh(dir)
        try {
            val libraryDir = File(dir, "library").apply { mkdirs() }
            File(dir, "state").mkdirs()
            database.writeBlocking { db ->
                Fixtures.loadRecords(db, record.getValue("records").jsonArray.map { it.jsonObject }, libraryDir)
            }
            val outside = File(dir, "outside")
            for (o in record.getValue("outside").jsonArray.map { it.jsonObject }) {
                val file = File(outside, o.getValue("path").jsonPrimitive.content)
                file.parentFile.mkdirs()
                file.writeBytes(Base64.getDecoder().decode(o.getValue("base64").jsonPrimitive.content))
            }
            make(record.getValue("make").jsonArray.map { it.jsonObject }, libraryDir, outside)
            body(Library(dir, database)) { scope }
        } finally {
            scope.cancel()
            database.close()
            unlink(dir)
            dir.deleteRecursively()
        }
    }

    /** The vector's files made after its fixture: a file of zeros (sparse), or a symbolic link in a file's or a
     * folder's place, to a file or a folder out of the library. */
    private fun make(actions: List<JsonObject>, libraryDir: File, outside: File) {
        for (m in actions) {
            val zeros = m["zeros"]?.jsonPrimitive?.content
            if (zeros != null) {
                val file = File(libraryDir, zeros)
                file.parentFile.mkdirs()
                RandomAccessFile(file, "rw").use { it.setLength(m.getValue("size").jsonPrimitive.long) }
                continue
            }
            val at = File(libraryDir, m.getValue("link").jsonPrimitive.content)
            at.parentFile.mkdirs()
            if (at.isDirectory) at.deleteRecursively() else at.delete()
            Files.createSymbolicLink(at.toPath(), File(outside, m.getValue("to").jsonPrimitive.content).toPath())
        }
    }

    /** The symbolic links under [dir], deleted before the folder is: never a walk through one. */
    private fun unlink(dir: File) {
        val entries = dir.listFiles() ?: return
        for (entry in entries) {
            if (Files.isSymbolicLink(entry.toPath())) entry.delete() else if (entry.isDirectory) unlink(entry)
        }
    }

    private fun guitarFiles(misses: Misses, test: Library, r: JsonObject) {
        val kw = r.getValue("kw").jsonObject
        val songId = kw["song_id"]?.jsonPrimitive?.longOrNull
        val path = kw["path"]?.jsonPrimitive?.content
        misses.expect("guitar_files", kw, r["out"]) {
            JsonArray(test.database.read { db -> GuitarFiles.of(db, songId, path) }.map { f ->
                JsonArray(listOf(JsonPrimitive(f.songId), JsonPrimitive(f.name), JsonPrimitive(f.path),
                                 JsonPrimitive(f.number), JsonPrimitive(f.inBrowser)))
            })
        }
    }

    private fun get(misses: Misses, app: TestApp, r: JsonObject) {
        val target = r.getValue("target").jsonPrimitive.content
        val case = "GET ${target.take(100)} (alphaTab ${r["alphatab"]})"
        val out = r.getValue("out").jsonObject
        val answer = app.get(target)
        misses.check(answer.status == out.getValue("status").jsonPrimitive.int) {
            "$case: ${answer.status}, caracole serve's ${out["status"]}"
        }
        val headers = JsonArray(answer.headers.map { (n, v) -> JsonArray(listOf(JsonPrimitive(n), JsonPrimitive(v))) })
        misses.check(headers == out.getValue("headers")) { "$case: headers $headers, caracole serve's ${out["headers"]}" }
        val bytes = answer.bytes
        misses.check(sha256(bytes) == out.getValue("sha256").jsonPrimitive.content &&
                     bytes.size == out.getValue("length").jsonPrimitive.int) {
            "$case: a body of ${bytes.size} bytes, caracole serve's ${out["length"]}"
        }
        val message: JsonElement = out["message"] ?: return
        val said = answer.data?.get("error") ?: JsonNull
        misses.check(said == message) { "$case: said $said, caracole serve $message" }
    }

    private fun sha256(bytes: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 0xff) }
}
