package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.mirror.Mirror
import io.github.danielhp95.caracole.server.http.Inline
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assume
import java.io.File
import java.security.MessageDigest

// What the page package's tests share: the producers they wait on (lane library-page's Phase A), a mirror holding a
// library page, and songs in the phone's database.

/**
 * Phase A: the page is built with server-shell's Inline (the hashes, the JSON block) and caracole/page/icon.json (the
 * tab's icon, the bar's mark), which are the skeleton's until that lane merges. Until then a test that builds a page
 * is skipped, saying so; once they are in, it runs.
 */
internal fun waitingOnServerShell() {
    val inline = runCatching { Inline.sha256Source(""); Inline.jsonBlock("x", JsonObject(emptyMap())) }.isSuccess
    val icons = PageIcons::class.java.classLoader?.getResource(PageIcons.RESOURCE) != null
    Assume.assumeTrue("waiting on lane server-shell (Inline, ${PageIcons.RESOURCE})", inline && icons)
}

/** Phase A: a phone-only song's card, and an empty library's fold table, are normalize.py's (lane keys, on
 * py-unicode's tables): skipped until they are in. */
internal fun waitingOnKeys() {
    val keys = runCatching { Normalize.fold("a"); Normalize.slugKey("a"); PyUnicode.isAlnum('a'.code) }.isSuccess
    Assume.assumeTrue("waiting on lanes keys and py-unicode (Normalize, PyUnicode)", keys)
}

internal fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

internal fun json(value: Any?): JsonElement = when (value) {
    null -> JsonNull
    is JsonElement -> value
    is String -> JsonPrimitive(value)
    is Number -> JsonPrimitive(value)
    is Boolean -> JsonPrimitive(value)
    is Map<*, *> -> JsonObject(value.entries.associate { (k, v) -> k as String to json(v) })
    is List<*> -> JsonArray(value.map { json(it) })
    else -> error("no JSON for $value")
}

internal fun obj(vararg pairs: Pair<String, Any?>): JsonObject = JsonObject(linkedMapOf(*pairs.map { (k, v) -> k to json(v) }.toTypedArray()))

/** A card as the computer's page carries one, its fields' shapes made up, [more] after them. */
internal fun mirroredCard(id: Long, identity: String, artist: String, title: String, vararg more: Pair<String, Any?>) = obj(
    "id" to id, "artist" to artist, "artists" to listOf(artist), "title" to title, "display" to "$artist - $title",
    "status" to "found", "review" to false, "added" to "2026-10-01T00:00:00Z", "key" to "G",
    "files" to listOf(mapOf("name" to "sheet.html", "label" to "Sheet viewer", "href" to "x/sheet.html")),
    "identity" to identity, "sortArtist" to identity.substringBefore('/'), "search" to "$artist $title", *more,
)

/** The computer's library page's data, as library_page.build_library_page orders it (the file's: no server). */
internal fun mirroredData(cards: List<JsonObject>, sets: List<JsonObject> = emptyList()) = obj(
    "generated" to "2026-11-02T03:00:00Z",
    "fold" to mapOf("ø" to "o", "ß" to "ss"),
    "songs" to cards,
    "icons" to mapOf("ug" to mapOf("name" to "Ultimate Guitar", "badge" to "UG")),
    "catalogue" to mapOf("I-V-vi-IV" to mapOf("name" to "the pop progression")),
    "songbooks" to mapOf("books" to listOf(mapOf("name" to "Campfire", "set" to sets)), "error" to null),
    "sites" to listOf(mapOf("id" to "ug", "rows" to 3)),
)

/** A library page as caracole writes one into the library: its data in its block, every '<' escaped. */
internal fun libraryPage(data: JsonObject): ByteArray =
    ("<!doctype html>\n<html><head><title>caracole</title></head><body><main id=\"list\"></main>\n" +
        "<script type=\"application/json\" id=\"songs\">${data.toString().replace("<", "\\u003c")}</script>\n" +
        "<script>const x = 1 < 2;</script>\n</body></html>\n").toByteArray()

/** A mirror in [dir] that holds [page] as its list's start page, index.html, as a sync leaves it. */
internal fun mirrorOf(dir: File, page: ByteArray): Mirror {
    val mirror = Mirror(dir)
    mirror.blobs.mkdirs()
    val sha = sha256(page)
    File(mirror.blobs, sha).writeBytes(page)
    mirror.manifestFile.writeText(
        """{"format": 1, "start": "index.html", "files": [{"path": "index.html", "url": "/offline/index.html", """ +
            """"size": ${page.size}, "sha256": "$sha", "type": "text/html; charset=utf-8", "headers": {}}]}""",
    )
    mirror.reload()
    return mirror
}

/** A song in the phone's database, as a take or an add leaves one; its id. */
internal fun addSong(database: Database, key: String, artist: String, title: String, status: String = "found",
                     review: Boolean = false, added: String = "2026-10-01T00:00:00Z", artists: List<String> = listOf(artist)): Long =
    database.writeBlocking { db ->
        db.execute(
            "INSERT INTO songs (key, artist, title, artists, added_at, status, review, created_at, updated_at) " +
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            key, artist, title, JsonArray(artists.map { JsonPrimitive(it) }).toString(), added, status, review, added, added,
        )
        db.lastRowid()
    }

/** A tombstone of [key] in the phone's database, as a removal there leaves one. */
internal fun removeSong(database: Database, key: String, artist: String, title: String) = database.writeBlocking { db ->
    db.execute("INSERT INTO removed (key, artist, title, removed_at) VALUES (?, ?, ?, ?)", key, artist, title, "2026-11-01T00:00:00Z")
}
