package io.github.danielhp95.caracole.server.files

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.core.sync.Units
import io.github.danielhp95.caracole.mirror.Entry
import io.github.danielhp95.caracole.mirror.Gate
import io.github.danielhp95.caracole.mirror.Manifest
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.mirror.UnitGate
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.GetAnswer
import io.github.danielhp95.caracole.server.http.Response
import io.github.danielhp95.caracole.server.http.Route
import io.github.danielhp95.caracole.server.http.RouteModule
import io.github.danielhp95.caracole.server.testing.TestApp
import io.github.danielhp95.caracole.server.testing.bytes
import io.github.danielhp95.caracole.server.testing.header
import io.github.danielhp95.caracole.server.testing.json
import io.github.danielhp95.caracole.server.testing.text
import io.github.danielhp95.caracole.viewer.render.Written
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.file.Files
import java.security.MessageDigest
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** A library file on the phone: its own folder first (the files it records), then the mirror's page, gated by its
 * unit; a route's path is never a file. */
class LibraryFilesTest {
    @get:Rule val tmp = TemporaryFolder()

    private val viewerCsp = "default-src 'none'; script-src 'sha256-x'; sandbox allow-scripts; frame-ancestors 'none'"
    private val key = "soda stereo|de musica ligera"

    private fun sha(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    /** A mirror holding [files] (path, content, unit), as a sync leaves one: its blobs and its manifest.json. */
    private fun mirror(vararg files: Triple<String, String, String?>, start: String = "index.html",
                       digests: Map<String, String> = emptyMap(), into: Mirror = Mirror(tmp.newFolder())): Mirror {
        val mirror = into
        mirror.blobs.mkdirs()
        val all = files.toList() + Triple(start, "<!doctype html>start", null)
        val entries = all.map { (path, content, unit) ->
            val bytes = content.toByteArray()
            File(mirror.blobs, sha(bytes)).writeBytes(bytes)
            val page = path.endsWith(".html")
            Entry(path, "/" + path, bytes.size.toLong(), sha(bytes),
                  if (page) "text/html; charset=utf-8" else "application/pdf",
                  if (page) linkedMapOf("Content-Security-Policy" to viewerCsp, "Referrer-Policy" to "no-referrer") else emptyMap(),
                  unit = unit, digest = unit?.let { digests[it] ?: "digest-of-$it" })
        }
        mirror.manifestFile.writeText(JsonObject(mapOf(
            "format" to JsonPrimitive(1), "start" to JsonPrimitive(start),
            "files" to JsonArray(entries.map { e ->
                JsonObject(buildMap {
                    put("path", JsonPrimitive(e.path)); put("url", JsonPrimitive(e.url)); put("size", JsonPrimitive(e.size))
                    put("sha256", JsonPrimitive(e.sha256)); put("type", JsonPrimitive(e.type))
                    put("headers", JsonObject(e.headers.mapValues { JsonPrimitive(it.value) }))
                    e.unit?.let { put("unit", JsonPrimitive(it)) }
                    e.digest?.let { put("digest", JsonPrimitive(it)) }
                })
            }),
        )).toString())
        if (mirror.reload()!!.entries.map { it.unit } != entries.map { it.unit }) {
            // Until lane offline-units reads each entry's unit from manifest.json, the list is set as it will read it.
            Mirror::class.java.getDeclaredField("current").apply { isAccessible = true }
                .set(mirror, Manifest(start, entries, emptyList()))
        }
        return mirror
    }

    private fun song(database: Database, artist: String, title: String, key: String): Long = database.writeBlocking { db ->
        db.execute("INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) " +
                   "VALUES (?, ?, ?, ?, '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z')",
                   key, artist, title, "[\"$artist\"]")
        db.lastRowid()
    }

    /** A file the phone keeps: written into its library folder and recorded in `files`. */
    private fun keep(test: TestApp, songId: Long, path: String, content: String) {
        File(test.libraryDir, path).apply { parentFile.mkdirs() }.writeText(content)
        test.database.writeBlocking { db ->
            db.execute("INSERT OR IGNORE INTO versions (provider, tab_id, song_id, slot, kind, url, fetched_at) " +
                       "VALUES ('inbox', 'sheet', ?, 'sheet', 'chords', '', '2026-11-01T00:00:00Z')", songId)
            val version = db.one("SELECT id FROM versions WHERE song_id = ?", songId) { it.long(0)!! }!!
            db.execute("INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) " +
                       "VALUES (?, ?, ?, ?, ?, 0, '2026-11-01T00:00:00Z')",
                       version, songId, path.substringAfterLast('/'), path, sha(content.toByteArray()))
        }
    }

    private fun tombstone(database: Database, key: String) = database.writeBlocking { db ->
        db.execute("INSERT INTO removed (key, artist, title, removed_at) VALUES (?, 'Soda Stereo', 'De Música Ligera', " +
                   "'2026-11-02T00:00:00Z')", key)
    }

    private val finished = listOf("X-Content-Type-Options" to "nosniff", "X-Frame-Options" to "DENY",
                                  "Cross-Origin-Resource-Policy" to "same-origin",
                                  "Cross-Origin-Opener-Policy" to "same-origin", "Cache-Control" to "no-store")

    @Test fun aMirroredPageIsServedWithTheManifestsHeadersExactly() {
        val mirror = mirror(Triple("Soda Stereo/De Música Ligera/sheet.html", "<!doctype html>sheet", "song/$key"),
                            Triple("Soda Stereo/De Música Ligera/sheet.pdf", "%PDF-1.7", null))
        TestApp(tmp.root, mirror = mirror).use { test ->
            val page = test.get("/Soda%20Stereo/De%20M%C3%BAsica%20Ligera/sheet.html")
            assertEquals(200, page.status)
            assertEquals("<!doctype html>sheet", page.text)
            assertIs<Body.FromFile>(page.body)
            assertEquals(listOf("Content-Type" to "text/html; charset=utf-8", "Content-Security-Policy" to viewerCsp,
                                "Referrer-Policy" to "no-referrer") + finished.filter { it.first != "Referrer-Policy" },
                         page.headers)
            val pdf = test.get("/Soda Stereo/De Música Ligera/sheet.pdf")
            assertEquals("%PDF-1.7", pdf.text)
            assertEquals("application/pdf", pdf.header("Content-Type"))
            assertEquals("frame-ancestors 'none'", pdf.header("Content-Security-Policy"))
            assertEquals(404, test.get("/Soda Stereo/De Música Ligera/sheet.txt").status)
            assertEquals(404, test.get("/Soda Stereo/De Música Ligera").status)
        }
    }

    @Test fun aSongRemovedOnThePhoneHasItsPagesAnswerSo() {
        val mirror = mirror(Triple("Soda Stereo/De Música Ligera/sheet.html", "<!doctype html>sheet", "song/$key"))
        TestApp(tmp.root, mirror = mirror).use { test ->
            tombstone(test.database, key)
            val gone = test.get("/Soda Stereo/De Música Ligera/sheet.html")
            assertEquals(410, gone.status)
            assertTrue("<p class=\"message\">This song was removed on the phone.</p>" in gone.text, gone.text)
            assertTrue("<h1>Removed on the phone</h1>" in gone.text)
            assertEquals("This song was removed on the phone.",
                         test.script("/Soda Stereo/De Música Ligera/sheet.html").json.jsonObject["error"]!!.jsonPrimitive.content)
            assertEquals(200, test.get("/index.html").status, "a file of no unit is served whatever the gate")
        }
    }

    @Test fun aSongChangedOnThePhoneHasItsPagesSaySoAndLinkItsSheet() {
        val changed = UnitGate { _, _ -> Gate.CHANGED }
        val mirror = mirror(Triple("Soda Stereo/De Música Ligera/sheet.html", "<!doctype html>sheet", "song/$key"),
                            Triple("Eagles/Hotel California/sheet.html", "<!doctype html>other", "song/eagles|hotel california"))
        TestApp(tmp.root, mirror = mirror, gate = { changed }).use { test ->
            val id = song(test.database, "Soda Stereo", "De Música Ligera", key)
            keep(test, id, "Soda Stereo/De Música Ligera/sheet.txt", "[C]Ella durmió")
            val page = test.get("/Soda Stereo/De Música Ligera/sheet.html")
            assertEquals(409, page.status)
            assertTrue("<p class=\"message\">This song changed on the phone since the computer made its page.</p>" in page.text,
                       page.text)
            assertTrue("<a class=\"btn\" href=\"/Soda%20Stereo/De%20M%C3%BAsica%20Ligera/sheet.txt\">" in page.text, page.text)
            assertEquals("[C]Ella durmió", test.get("/Soda%20Stereo/De%20M%C3%BAsica%20Ligera/sheet.txt").text)
            val other = test.get("/Eagles/Hotel California/sheet.html")
            assertEquals(409, other.status)
            assertFalse("sheet.txt" in other.text, "no sheet on the phone, no link")
            File(test.libraryDir, "Soda Stereo/De Música Ligera/sheet.txt").delete()
            val gone = test.get("/Soda Stereo/De Música Ligera/sheet.html")
            assertEquals(409, gone.status)
            assertFalse("sheet.txt" in gone.text, "a sheet recorded but not on disk: no link to a 404")
        }
    }

    @Test fun thePhoneGateServesWhatThePhoneHoldsAsTheComputerListedIt() {
        TestApp(tmp.root).use { test ->
            val gate = PhoneGate(test.database)
            assertEquals(Gate.SERVE, gate.check("song/$key", "anything"), "a song the phone hasn't got has no digest")
            tombstone(test.database, key)
            assertEquals(Gate.REMOVED, gate.check("song/$key", "anything"))
            assertEquals(Gate.REMOVED, gate.check("song/$key", null))
            song(test.database, "Soda Stereo", "De Música Ligera", key)
            val digest = test.database.read { Units.digestOf(it, "song/$key") }
            assertNotNull(digest)
            assertEquals(Gate.SERVE, gate.check("song/$key", digest), "a song taken again stands as the computer listed it")
            assertEquals(Gate.CHANGED, gate.check("song/$key", "anything"), "a song the phone holds otherwise changed")
            assertEquals(Gate.CHANGED, gate.check("song/$key", null))
            assertEquals(Gate.SERVE, gate.check("songbook/campfire", "anything"), "a unit the phone hasn't got")
            val stone = test.database.read { Units.digestOf(it, "removed/$key") }
            assertEquals(Gate.SERVE, gate.check("removed/$key", stone))
            assertEquals(Gate.CHANGED, gate.check("removed/$key", null))
        }
    }

    @Test fun thePhonesOwnFileComesFirstAndOnlyWhatItRecords() {
        val mirror = mirror(Triple("Soda Stereo/De Música Ligera/sheet.pdf", "%PDF the computer's", null),
                            Triple("Soda Stereo/De Música Ligera/notes.txt", "the computer's notes", null))
        TestApp(tmp.root, mirror = mirror).use { test ->
            val id = song(test.database, "Soda Stereo", "De Música Ligera", key)
            keep(test, id, "Soda Stereo/De Música Ligera/sheet.pdf", "%PDF the phone's")
            File(test.libraryDir, "Soda Stereo/De Música Ligera/notes.txt").writeText("not recorded")
            File(test.libraryDir, "Soda Stereo/De Música Ligera/other.txt").writeText("not recorded")
            val pdf = test.get("/Soda Stereo/De Música Ligera/sheet.pdf")
            assertEquals("%PDF the phone's", pdf.text)
            assertEquals("application/pdf", pdf.header("Content-Type"))
            assertNull(pdf.header("Content-Disposition"), "a PDF opens; only a download is named")
            assertEquals("the computer's notes", test.get("/Soda Stereo/De Música Ligera/notes.txt").text)
            assertEquals(404, test.get("/Soda Stereo/De Música Ligera/other.txt").status)
            keep(test, id, "Soda Stereo/De Música Ligera/page.html", "<script>")
            assertEquals(404, test.get("/Soda Stereo/De Música Ligera/page.html").status, "never a page of the phone's")
            keep(test, id, "Soda Stereo/De Música Ligera/lyrics.json", "{}")
            assertEquals("application/json; charset=utf-8", test.get("/Soda Stereo/De Música Ligera/lyrics.json").header("Content-Type"))
        }
    }

    @Test fun noLinkIsFollowedAndNothingOutsideTheLibraryIsServed() {
        TestApp(tmp.root).use { test ->
            val id = song(test.database, "Soda Stereo", "De Música Ligera", key)
            val outside = tmp.newFolder("outside")
            File(outside, "secret.txt").writeText("caracole.sqlite's neighbour")
            Files.createSymbolicLink(File(test.libraryDir, "Linked").toPath(), outside.toPath())
            keep(test, id, "Soda Stereo/De Música Ligera/ok.txt", "ok")
            test.database.writeBlocking { db ->
                db.execute("UPDATE files SET path = 'Linked/secret.txt' WHERE name = 'ok.txt'")
            }
            assertEquals(404, test.get("/Linked/secret.txt").status, "a recorded path through a link")
            keep(test, id, "Soda Stereo/De Música Ligera/sheet.txt", "sheet")
            val sheet = File(test.libraryDir, "Soda Stereo/De Música Ligera/sheet.txt")
            sheet.delete()
            Files.createSymbolicLink(sheet.toPath(), File(outside, "secret.txt").toPath())
            assertEquals(404, test.get("/Soda Stereo/De Música Ligera/sheet.txt").status, "the file a link")
            test.database.writeBlocking { db -> db.execute("UPDATE files SET path = '../outside/secret.txt' WHERE name = 'sheet.txt'") }
            assertEquals(404, test.get("/../outside/secret.txt").status)
            assertEquals(404, test.get("/%2E%2E/outside/secret.txt").status)
            for (hidden in listOf("/.stfolder/x.txt", "/a/./b.txt", "/a//b.txt", "/a/b.txt/", "/", "//")) {
                assertEquals(404, test.get(hidden).status, hidden)
            }
        }
    }

    @Test fun aRoutesPathIsNeverAFile() {
        val routes = object : RouteModule {
            override val routes = listOf(
                Route("GET", "/index.html", "the page", get = GetAnswer { Response(200, Body.Bytes("the route".toByteArray())) }),
                Route("GET", "/api/jobs/", "a job", under = true, get = GetAnswer { Response(200, Body.Bytes("a job".toByteArray())) }),
            )
        }
        val mirror = mirror(Triple("api/jobs/1.json", "{}", null), Triple("lookup.pdf", "%PDF", null),
                            Triple("lookup", "%PDF", null))
        TestApp(tmp.root, { listOf(routes) }, mirror = mirror).use { test ->
            val id = song(test.database, "Soda Stereo", "De Música Ligera", key)
            keep(test, id, "api/jobs/2.json", "{}")
            assertEquals("the route", test.get("/index.html").text)
            assertEquals("a job", test.script("/api/jobs/1.json").text)
            assertEquals("a job", test.script("/api/jobs/2.json").text)
            assertEquals(409, test.get("/lookup").status, "the stub's, never the mirror's file of that path")
            assertEquals("%PDF", test.get("/lookup.pdf").text)
            assertTrue(test.files.serve("/index.html") != null, "the file is there, and the route answers first")
        }
    }

    @Test fun aHeadIsAnsweredAsItsGet() {
        TestApp(tmp.root, mirror = mirror(Triple("a.pdf", "%PDF", null))).use { test ->
            val head = test.handle(test.request("HEAD", "/a.pdf"))
            assertEquals(200, head.status)
            assertContentEquals("%PDF".toByteArray(), head.bytes, "the socket drops it, as server.py does")
        }
    }

    // --- the phone's written pages --------------------------------------------------------------------------------

    /** WrittenPages' records as a test sets them: each page's record by song and name, those whose unit is still at
     * the digest it was made at, the songbooks' files, and the viewer's policy of a page's bytes. */
    private class Pages : PhonePages {
        val records = HashMap<Pair<Long, String>, Written>()
        val current = HashSet<Pair<Long, String>>()
        val songbooks = HashMap<String, Map<String, Pair<String, Long>>>()
        override fun written(db: Db, songId: Long, name: String): Written? = records[songId to name]
        override fun current(db: Db, songId: Long, name: String): Boolean = (songId to name) in current
        override fun songbook(db: Db, folder: String): Map<String, Pair<String, Long>> = songbooks[folder].orEmpty()
        override fun csp(page: ByteArray): String =
            "sandbox allow-scripts allow-downloads; default-src 'none'; script-src 'sha256-${page.size}'"
    }

    /** The phone's page [name] of [songId] written at [path] and recorded, at a unit [current] or moved since. */
    private fun written(test: TestApp, pages: Pages, songId: Long, path: String, content: String, current: Boolean = true) {
        val bytes = content.toByteArray()
        File(test.libraryDir, path).apply { parentFile.mkdirs() }.writeBytes(bytes)
        val name = path.substringAfterLast('/')
        pages.records[songId to name] = Written(sha(bytes), bytes.size.toLong(), "the unit's digest")
        if (current) pages.current += songId to name else pages.current -= songId to name
    }

    private fun policyOf(content: String) =
        "sandbox allow-scripts allow-downloads; default-src 'none'; script-src 'sha256-${content.toByteArray().size}'; " +
            "frame-ancestors 'none'"

    @Test fun thePhonesPageIsServedWhileItIsTheRecordsAtItsUnitsDigestBeforeTheMirrors() {
        val folder = "Soda Stereo/De Música Ligera"
        val mirror = mirror(Triple("$folder/sheet.html", "<!doctype html>the computer's", "song/$key"),
                            Triple("$folder/version-39144.html", "<!doctype html>the computer's version", "song/$key"))
        TestApp(tmp.root, mirror = mirror, gate = { UnitGate { _, _ -> Gate.SERVE } }).use { test ->
            val pages = Pages().also { test.files.pages = it }
            val id = song(test.database, "Soda Stereo", "De Música Ligera", key)
            for (name in listOf("sheet.html", "sheet (auto).html", "version-39144.html", "harmonica-2.html")) {
                written(test, pages, id, "$folder/$name", "<!doctype html>the phone's $name")
                val page = test.get("/" + "$folder/$name".split('/').joinToString("/") { PyUrl.quote(it, safe = "") })
                assertEquals(200, page.status, name)
                assertEquals("<!doctype html>the phone's $name", page.text)
                assertEquals(listOf("Content-Type" to "text/html; charset=utf-8",
                                    "Content-Security-Policy" to policyOf("<!doctype html>the phone's $name")) + finished,
                             page.headers.filter { it.first != "Referrer-Policy" }, name)
                assertEquals("same-origin", page.header("Referrer-Policy"))
            }
        }
    }

    @Test fun aPageChangedOnDiskIsRefusedForTheMirrorsOrSaysSo() {
        val folder = "Soda Stereo/De Música Ligera"
        val mirror = mirror(Triple("$folder/sheet.html", "<!doctype html>the computer's", "song/$key"))
        TestApp(tmp.root, mirror = mirror, gate = { UnitGate { _, _ -> Gate.SERVE } }).use { test ->
            val pages = Pages().also { test.files.pages = it }
            val id = song(test.database, "Soda Stereo", "De Música Ligera", key)
            written(test, pages, id, "$folder/sheet.html", "<!doctype html>the phone's")
            written(test, pages, id, "$folder/harmonica-2.html", "<!doctype html>the phone's tab")
            File(test.libraryDir, "$folder/sheet.html").writeText("<!doctype html>THE phone's") // its length kept
            assertEquals("<!doctype html>the computer's", test.get("/$folder/sheet.html").text,
                         "the mirror's page, its unit as the computer listed it")
            File(test.libraryDir, "$folder/harmonica-2.html").appendText("<script>")
            val refused = test.get("/$folder/harmonica-2.html")
            assertEquals(404, refused.status, "no mirror's page to stand for it")
            assertTrue("<h1>Not sent</h1>" in refused.text, refused.text)
            assertTrue("isn&#x27;t the one the phone made here" in refused.text, refused.text)
            // A link in its place, to the very bytes recorded: never followed.
            val outside = File(tmp.newFolder("outside"), "page.html").apply { writeText("<!doctype html>the phone's tab") }
            File(test.libraryDir, "$folder/harmonica-2.html").delete()
            Files.createSymbolicLink(File(test.libraryDir, "$folder/harmonica-2.html").toPath(), outside.toPath())
            assertEquals(404, test.get("/$folder/harmonica-2.html").status)
            File(test.libraryDir, "$folder/harmonica-2.html").delete()
            assertEquals(404, test.get("/$folder/harmonica-2.html").status, "a page gone")
        }
    }

    @Test fun onceItsUnitMovesTheMirrorsPageServesWhenItsGateSaysSo() {
        val folder = "Soda Stereo/De Música Ligera"
        val mirror = Mirror(tmp.newFolder())
        TestApp(tmp.root, mirror = mirror).use { test ->
            val pages = Pages().also { test.files.pages = it }
            val id = song(test.database, "Soda Stereo", "De Música Ligera", key)
            keep(test, id, "$folder/sheet.txt", "[C]Ella durmió")
            written(test, pages, id, "$folder/sheet.html", "<!doctype html>the phone's", current = false)
            // The computer rendered the song again at the unit the phone holds now (a take moved it there).
            val now = test.database.read { Units.digestOf(it, "song/$key") }!!
            mirror(Triple("$folder/sheet.html", "<!doctype html>the computer's", "song/$key"),
                   digests = mapOf("song/$key" to now), into = mirror)
            assertEquals("<!doctype html>the computer's", test.get("/$folder/sheet.html").text)
            // The computer's of an older unit: kept back, as the phone's of a moved one is.
            mirror(Triple("$folder/sheet.html", "<!doctype html>the computer's", "song/$key"), into = mirror)
            val changed = test.get("/$folder/sheet.html")
            assertEquals(409, changed.status)
            assertTrue("since the computer made its page" in changed.text, changed.text)
            // No page of the computer's at all: the phone's of a moved unit is never served either.
            mirror(into = mirror)
            val stale = test.get("/$folder/sheet.html")
            assertEquals(409, stale.status)
            assertTrue("<h1>Changed on the phone</h1>" in stale.text, stale.text)
            assertTrue("since its page was made" in stale.text, stale.text)
            assertTrue("href=\"/Soda%20Stereo/De%20M%C3%BAsica%20Ligera/sheet.txt\"" in stale.text, stale.text)
            pages.current += id to "sheet.html"
            assertEquals("<!doctype html>the phone's", test.get("/$folder/sheet.html").text, "its unit back where it was")
        }
    }

    @Test fun theMirrorsPageServesWhereThePhoneWroteNone() {
        val folder = "Soda Stereo/De Música Ligera"
        val mirror = mirror(Triple("$folder/sheet.html", "<!doctype html>the computer's", "song/$key"))
        TestApp(tmp.root, mirror = mirror, gate = { UnitGate { _, _ -> Gate.SERVE } }).use { test ->
            val pages = Pages().also { test.files.pages = it }
            val id = song(test.database, "Soda Stereo", "De Música Ligera", key)
            File(test.libraryDir, folder).mkdirs()
            File(test.libraryDir, "$folder/sheet.html").writeText("<!doctype html>no record of it")
            File(test.libraryDir, "$folder/version-1.html").writeText("<!doctype html>no record of it")
            assertEquals("<!doctype html>the computer's", test.get("/$folder/sheet.html").text)
            assertEquals(404, test.get("/$folder/version-1.html").status)
            // A record of another song's: none of this one's folder.
            val unrecorded = "<!doctype html>no record of it".toByteArray()
            val record = Written(sha(unrecorded), unrecorded.size.toLong(), "d")
            val other = song(test.database, "Eagles", "Hotel California", "eagles|hotel california")
            pages.records[other to "version-1.html"] = record
            pages.current += other to "version-1.html"
            assertEquals(404, test.get("/$folder/version-1.html").status)
            assertEquals(404, test.get("/$folder/sheet.cho").status, "no page: the phone's own files' rules")
            pages.records[id to "version-1.html"] = record
            pages.current += id to "version-1.html"
            assertEquals("<!doctype html>no record of it", test.get("/$folder/version-1.html").text)
        }
    }

    @Test fun aChordProThePhoneWroteIsServedAsItsPagesAreAsText() {
        val folder = "Soda Stereo/De Música Ligera"
        val mirror = mirror(Triple("$folder/sheet (auto).cho", "{title: the computer's}", "song/$key"))
        TestApp(tmp.root, mirror = mirror, gate = { UnitGate { _, _ -> Gate.SERVE } }).use { test ->
            val pages = Pages().also { test.files.pages = it }
            val id = song(test.database, "Soda Stereo", "De Música Ligera", key)
            written(test, pages, id, "$folder/sheet.cho", "{title: the phone's}")
            val cho = test.get("/$folder/sheet.cho")
            assertEquals("{title: the phone's}", cho.text)
            assertEquals("text/plain; charset=utf-8", cho.header("Content-Type"))
            assertEquals("frame-ancestors 'none'", cho.header("Content-Security-Policy"))
            written(test, pages, id, "$folder/sheet (auto).cho", "{title: the phone's auto}", current = false)
            assertEquals("{title: the computer's}", test.get("/$folder/sheet (auto).cho").text, "a unit moved since")
            File(test.libraryDir, "$folder/sheet.cho").writeText("{title: THE phone's}")
            assertEquals(404, test.get("/$folder/sheet.cho").status, "changed on disk, and no mirror's")
            written(test, pages, id, "$folder/song.gp5", "GP5")
            assertEquals(404, test.get("/$folder/song.gp5").status, "a download is a kept file's alone")
        }
    }

    @Test fun eitherSongOfAFolderTwoSongsShareServesItsRecord() {
        val folder = "Soda Stereo/De Música Ligera"
        TestApp(tmp.root).use { test ->
            val pages = Pages().also { test.files.pages = it }
            song(test.database, "Soda Stereo", "De Música Ligera", key)
            val other = song(test.database, "Soda Stereo", "De Música Ligera", "$key (2)")
            written(test, pages, other, "$folder/sheet.html", "<!doctype html>the other's")
            assertEquals("<!doctype html>the other's", test.get("/$folder/sheet.html").text)
        }
    }

    @Test fun aSongbooksPageIsServedByItsRecordTheSameWay() {
        val path = "_songbooks/Campfire/songbook.html"
        val mirror = mirror(Triple(path, "<!doctype html>the computer's book", "songbook/campfire"))
        TestApp(tmp.root, mirror = mirror).use { test ->
            val pages = Pages().also { test.files.pages = it }
            assertEquals("<!doctype html>the computer's book", test.get("/$path").text, "the phone wrote none")
            val bytes = "<!doctype html>the phone's book".toByteArray()
            File(test.libraryDir, path).apply { parentFile.mkdirs() }.writeBytes(bytes)
            pages.songbooks["Campfire"] = mapOf("songbook.html" to (sha(bytes) to bytes.size.toLong()),
                                                "songbook.cho" to ("ab" to 2L))
            val page = test.get("/$path")
            assertEquals("<!doctype html>the phone's book", page.text)
            assertEquals(policyOf("<!doctype html>the phone's book"), page.header("Content-Security-Policy"))
            File(test.libraryDir, path).writeText("<!doctype html>THE phone's book")
            assertEquals("<!doctype html>the computer's book", test.get("/$path").text, "changed on disk: the mirror's")
            pages.songbooks["Other"] = pages.songbooks.getValue("Campfire")
            File(test.libraryDir, "_songbooks/Other/songbook.html").apply { parentFile.mkdirs() }.writeBytes(bytes)
            File(test.libraryDir, "_songbooks/Other/x/songbook.html").apply { parentFile.mkdirs() }.writeBytes(bytes)
            assertEquals("<!doctype html>the phone's book", test.get("/_songbooks/Other/songbook.html").text)
            assertEquals(404, test.get("/_songbooks/Other/x/songbook.html").status, "a songbook's folder alone")
            assertEquals(404, test.get("/Campfire/songbook.html").status)
        }
    }

    /** Phase A guard, waiting on: phone-render (its WrittenPages records the pages; until it merges, none). */
    @Test fun untilItsRecordsLandThePhoneServesNoPageOfItsOwn() {
        TestApp(tmp.root).use { test ->
            song(test.database, "Soda Stereo", "De Música Ligera", key)
            File(test.libraryDir, "Soda Stereo/De Música Ligera").mkdirs()
            File(test.libraryDir, "Soda Stereo/De Música Ligera/sheet.html").writeText("<!doctype html>the phone's")
            assertEquals(PhonePages.NONE, test.files.pages)
            assertEquals(404, test.get("/Soda Stereo/De Música Ligera/sheet.html").status)
        }
    }
}
