package io.github.danielhp95.caracole.server.routes.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.server.http.Body
import io.github.danielhp95.caracole.server.http.LibraryName
import io.github.danielhp95.caracole.server.http.MessagePage
import io.github.danielhp95.caracole.server.http.Response
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * What removing a song from the phone takes and leaves, as removal.brief and removal.describe say it on the computer:
 * the files the phone keeps for it and its entry go; nothing stays, since every file in its folder on the phone is
 * one a sync or an add wrote. The removal leaves a tombstone, so the song stays removed until it is asked for again.
 */
internal object RemovalQuestion {
    const val AFTER = "It stays gone from the phone until you ask again (the request form, or Fetch on a search's " +
        "line). The next share removes it from the computer's book too, unless you keep theirs."

    /** The question's data, `{removal: {song, key, display, brief, goes, stays, notes}}`, as remove_routes gives it. */
    fun data(db: Db, song: SongRow): JsonObject {
        val files = db.query("SELECT name FROM files WHERE song_id = ? ORDER BY name", song.id) { it.text(0)!! }
        val versions = db.one("SELECT COUNT(*) FROM versions WHERE song_id = ?", song.id) { it.long(0) } ?: 0L
        val goes = buildList {
            if (files.isNotEmpty()) add("${plural(files.size, "file")} the phone keeps for it: ${files.joinToString(", ")}")
            add("its entry on the phone: match, lyrics" +
                if (versions > 0) " and ${plural(versions.toInt(), "version")} seen" else "")
        }
        val brief = buildList {
            if (files.isNotEmpty()) add("the phone's ${plural(files.size, "file")} for it")
            add("its entry")
        }.let { "Deletes " + if (it.size > 1) it.dropLast(1).joinToString(", ") + " and " + it.last() + "." else it[0] + "." }
        return JsonObject(mapOf("removal" to JsonObject(linkedMapOf(
            "song" to JsonPrimitive(song.id), "key" to JsonPrimitive(song.key), "display" to JsonPrimitive(song.display),
            "brief" to JsonPrimitive(brief), "goes" to JsonArray(goes.map(::JsonPrimitive)),
            "stays" to JsonArray(emptyList()), "notes" to JsonArray(listOf(JsonPrimitive(AFTER))),
        ))))
    }

    /**
     * The question as a page, for a form posted with no script (the Journal's Try again of a removal): pages.remove_page
     * in the message page's frame, what goes, the notes, and its form, which confirms it (the form token [csrf], the
     * song, its key, `confirm`, and [back], the library page's address after #, when there is one), beside Keep, back
     * to [library]; its data the question's ([question], what the page's script reads instead).
     */
    fun page(song: SongRow, question: JsonObject, csrf: String, back: String, library: String): Response {
        val removal = question.getValue("removal") as JsonObject
        fun texts(name: String) = (removal.getValue(name) as JsonArray).map { (it as JsonPrimitive).content }
        val goes = texts("goes")
        val items = if (goes.isEmpty()) "" else "<h2 class=\"sub\">Removes</h2>\n<ul class=\"plan\">" +
            goes.joinToString("") { "<li>${PyText.escape(it)}</li>" } + "</ul>\n"
        val said = texts("notes").joinToString("") { "<p class=\"message\">${PyText.escape(it)}</p>\n" }
        val fields = listOf("csrf" to csrf, "song" to song.id.toString(), "key" to song.key, "confirm" to "1") +
            (if (back.isNotEmpty()) listOf("back" to back) else emptyList())
        val form = "<form class=\"confirm\" method=\"post\" action=\"/remove\">\n" +
            fields.joinToString("") { (name, value) ->
                "  <input type=\"hidden\" name=\"$name\" value=\"${PyText.escape(value)}\">\n"
            } +
            "  <button class=\"btn danger\" type=\"submit\">Remove</button>\n" +
            "  <a class=\"btn\" href=\"${PyText.escape(library)}\">Keep</a>\n</form>"
        val lede = "<p class=\"lede\">${PyText.escape((removal.getValue("brief") as JsonPrimitive).content)}</p>\n"
        val html = MessagePage.html("Remove ${song.display}?", lede + items + said + form, LibraryName.phone(null))
        return Response(200, Body.Bytes(html.toByteArray()),
                        mutableListOf("Content-Type" to MessagePage.HTML, "Content-Security-Policy" to MessagePage.csp),
                        question)
    }

    private fun plural(n: Int, word: String) = "$n ${if (n == 1) word else word + "s"}"
}
