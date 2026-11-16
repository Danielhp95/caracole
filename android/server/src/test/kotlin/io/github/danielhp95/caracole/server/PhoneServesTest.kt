package io.github.danielhp95.caracole.server

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.testing.RefusingTransport
import io.github.danielhp95.caracole.core.testing.TestDb
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.Request
import io.github.danielhp95.caracole.server.http.Security
import io.github.danielhp95.caracole.server.routes.SyncSettings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.net.InetAddress
import java.net.Socket
import java.net.SocketTimeoutException
import java.security.MessageDigest
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/** What the phone serves as Assembly wires it: the files its cards link, what its page offers, and a request
 * refused before its body is read. */
class PhoneServesTest {
    @get:Rule val tmp = TemporaryFolder()

    private object NoAddress : SyncSettings {
        override val address: String? = null
        override fun remember(address: String) = Unit
    }

    private val secret = "s".repeat(64)

    private fun <T> phone(database: Database, library: File, state: File, block: (Phone) -> T): T {
        val scope = CoroutineScope(SupervisorJob())
        try {
            val deps = PhoneDeps(database, library, state, null, scope, NoAddress, secret = secret, csrf = "tok",
                                 transport = { RefusingTransport })
            return block(Phone(deps))
        } finally {
            scope.cancel()
        }
    }

    private fun get(phone: Phone, target: String) = phone.app.handle(Request(
        "GET", target, mapOf("cookie" to "${Security.SECRET_COOKIE}=$secret", "host" to "127.0.0.1:8738",
                             "sec-fetch-site" to "same-origin"), ByteArray(0)))

    /**
     * A song looked up on the phone alone: its card links the lyrics.txt, lyrics.lrc and info.json of its folder
     * (Cards.folderNames: every file there), which no `files` row records: each is served all the same.
     */
    @Test fun everyFileASongsCardLinksIsServed() {
        val library = tmp.newFolder("library")
        val state = File(tmp.root, "state").apply { mkdirs() }
        TestDb.fresh(tmp.newFolder("db")).use { database ->
            phone(database, library, state) { phone ->
                val artist = "Estopa"
                val title = "Tu Calorro"
                val key = Normalize.identityKey(artist, title)
                val id = database.writeBlocking { db ->
                    db.execute("INSERT INTO songs (key, artist, title, artists, added_at, created_at, updated_at) " +
                               "VALUES (?, ?, ?, ?, '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z')",
                               key, artist, title, "[\"$artist\"]")
                    db.lastRowid()
                }
                val folder = File(library, "$artist/$title").apply { mkdirs() }
                // what a lookup on the phone leaves in the folder: the sheet kept (a `files` row), the lyrics' files
                // (LyricsFiles) and info.json (InfoJson), neither a kept file
                val sheet = "[ch]Am[/ch] Fui a la orilla del rio\n"
                File(folder, "sheet.txt").writeText(sheet)
                File(folder, "lyrics.txt").writeText("Fui a la orilla del rio\n")
                File(folder, "lyrics.lrc").writeText("[00:01.00]Fui a la orilla del rio\n")
                File(folder, "info.json").writeText("{}\n")
                database.writeBlocking { db ->
                    db.execute("INSERT INTO versions (provider, tab_id, song_id, slot, kind, url, fetched_at) " +
                               "VALUES ('ug', '1', ?, 'sheet', 'chords', '', '2026-11-01T00:00:00Z')", id)
                    val version = db.one("SELECT id FROM versions WHERE song_id = ?", id) { it.long(0)!! }!!
                    val sha = MessageDigest.getInstance("SHA-256").digest(sheet.toByteArray()).joinToString("") { "%02x".format(it) }
                    db.execute("INSERT INTO files (version_id, song_id, name, path, sha256, kept_rank, created_at) " +
                               "VALUES (?, ?, 'sheet.txt', ?, ?, 0, '2026-11-01T00:00:00Z')",
                               version, id, "$artist/$title/sheet.txt", sha)
                }
                val card = database.read { db -> phone.parts.cards.cards(db, listOf(Songs.byId(db, id)!!)) }.getValue(id)
                val linked = (card.getValue("files") as JsonArray).map { it as JsonObject }
                    .associate { (it.getValue("name") as JsonPrimitive).content to (it.getValue("href") as JsonPrimitive).content }
                assertTrue("lyrics.txt" in linked && "sheet.txt" in linked, "the card links its folder's files: $linked")
                val answered = linked.mapValues { (_, href) -> get(phone, "/$href").status }
                assertEquals(linked.mapValues { 200 }, answered, "every file the card links is served")
            }
        }
    }
}
