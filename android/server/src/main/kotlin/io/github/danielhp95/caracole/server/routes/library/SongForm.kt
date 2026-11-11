package io.github.danielhp95.caracole.server.routes.library

import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.db.Database
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.names.SongNames
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyUnicode
import io.github.danielhp95.caracole.server.http.Refused

/** A song a form names, as library_routes.py reads one (`named_form`, `wanted_line`) and the phone adds it: its
 * names as wanted.txt's line writes them (wanted._clean: NFC, single spaces, no stray zero-width characters at the
 * ends), its album so too, its length in milliseconds, and its identity key, the job's key. */
internal data class NamedSong(val artist: String, val title: String, val album: String?, val durationMs: Long?) {
    val display: String get() = "$artist - $title"
    val key: String get() = Normalize.identityKey(artist, title)
}

/** library_routes.py's reading of a request's form, on the phone (no wanted.txt: the song goes to the database). */
internal object SongForm {
    /** library_routes.LIMITS, in characters (code points). */
    val LIMITS = linkedMapOf("artist" to 200, "title" to 300, "album" to 300, "duration" to 12)

    /** library_routes.TEXT_LIMIT: a request's one text, `q`. */
    const val TEXT_LIMIT = 500

    /** library_routes.PICK_LIMITS: the longest pick of each site a form may carry. */
    val PICK_LIMITS = linkedMapOf("ug" to 300, "tab" to 600, "lacuerda" to 600, "harptabs" to 600, "gametabs" to 600)

    private val DURATION_SHAPE = PyRegex.compile("""\d+(?::\d+){0,2}""")
    private val SEPARATOR = PyRegex.compile("""\s+[-–—]\s+""")
    private const val INVISIBLE = "​‎‏﻿"

    /** named_form: [form] with the artist and the title its one text `q` names (SongNames.readNames, as the pages fill
     * their forms from a query), when it gives neither; as it is otherwise. Refused for a text too long, or one that
     * doesn't say who its artist is. */
    fun named(database: Database, form: Map<String, String>): Map<String, String> {
        val text = Py.split(form["q"].orEmpty()).joinToString(" ")
        if (text.isEmpty() || Py.strip(form["artist"].orEmpty()).isNotEmpty() || Py.strip(form["title"].orEmpty()).isNotEmpty()) {
            return form
        }
        if (Py.len(text) > TEXT_LIMIT) throw Refused(400, "Too long", "Too long: $TEXT_LIMIT characters at most.")
        val named = database.read { db -> SongNames.readNames(db, text, Songs.list(db)) }
        if (named == null || named.first.isEmpty() || named.second.isEmpty()) {
            throw Refused(400, "Not a song", "“$text” names no artist. Write “Artist - Title”, or fill in both.")
        }
        return form + mapOf("artist" to named.first, "title" to named.second)
    }

    /** wanted_line's checks, short of wanted.txt: each field within its limit, an artist and a title, a length that
     * reads as one, and names the computer's wanted.txt can hold (an artist with " - " in it it can't, nor one or a
     * title that is nothing once cleaned); the names cleaned as its line writes them (format_line). [picks]: each
     * site's pick within its length too (a lookup's `_pick`, which a request never reads). */
    fun song(form: Map<String, String>, picks: Boolean = true): NamedSong {
        val values = LIMITS.keys.associateWith { Py.strip(form[it].orEmpty()) }
        for ((name, value) in values) {
            if (Py.len(value) > LIMITS.getValue(name)) {
                throw Refused(400, "Too long", "The $name is too long: ${LIMITS.getValue(name)} characters at most.")
            }
        }
        val artist = values.getValue("artist")
        val title = values.getValue("title")
        if (artist.isEmpty() || title.isEmpty()) throw Refused(400, "Not a song", "A song needs an artist and a title.")
        val duration = values.getValue("duration")
        val durationMs = if (duration.isEmpty()) null else {
            try {
                parseDuration(duration)
            } catch (e: IllegalArgumentException) {
                throw Refused(400, "Not a length", "The length is a ${e.message}.")
            } ?: throw Refused(400, "Not a length", "The length '$duration' isn't a duration. Write m:ss, h:mm:ss or " +
                                                     "seconds.")
        }
        if (SEPARATOR.containsMatchIn(clean(artist))) {
            throw Refused(400, "Not added", "Can't add this song: an artist name can't hold ' - ': " +
                                            PyStr.repr(artist))
        }
        val written = clean(artist) to clean(title)
        if (written.first.isEmpty() || written.second.isEmpty()) {
            throw Refused(400, "Not added", "Can't add this song: it needs an artist and a title")
        }
        if (picks) checkPicks(form)
        val album = values.getValue("album").takeIf { it.isNotEmpty() }?.let(::clean)?.ifEmpty { null }
        return NamedSong(written.first, written.second, album, durationMs)
    }

    /** search_routes._pick's limits: each site's pick a form carries within its length (what the phone takes no
     * further), else refused. */
    fun checkPicks(form: Map<String, String>) {
        for ((name, limit) in PICK_LIMITS) {
            if (Py.len(Py.strip(form[name].orEmpty())) > limit) {
                throw Refused(400, "Too long", "The $name is too long: $limit characters at most.")
            }
        }
    }

    /** wanted.parse_duration: milliseconds for m:ss, h:mm:ss or whole seconds; null for a text that isn't one;
     * IllegalArgumentException (its words) for one shaped like a duration that isn't a valid one ("4:75", "0:00"). */
    fun parseDuration(text: String): Long? {
        val s = Py.strip(PyUnicode.nfkc(text))
        if (!DURATION_SHAPE.matches(s) || s.any { it != ':' && it !in '0'..'9' }) return null
        val parts = s.split(':')
        val last = parts.last()
        val head = parts.dropLast(1)
        val bad = "bad duration '${Py.strip(text)}': write m:ss, h:mm:ss or whole seconds"
        val seconds = when (head.size) {
            0 -> last.toBigInteger()
            else -> {
                if (last.length != 2 || last.toInt() >= 60) throw IllegalArgumentException(bad)
                if (head.size == 2) {
                    val (hours, minutes) = head
                    if (minutes.length != 2 || minutes.toInt() >= 60) throw IllegalArgumentException(bad)
                    hours.toBigInteger() * 3600.toBigInteger() + minutes.toBigInteger() * 60.toBigInteger() + last.toBigInteger()
                } else {
                    head[0].toBigInteger() * 60.toBigInteger() + last.toBigInteger()
                }
            }
        }
        if (seconds.signum() <= 0) throw IllegalArgumentException("bad duration '${Py.strip(text)}': it must be longer than zero")
        if (seconds > (Long.MAX_VALUE / 1000).toBigInteger()) throw IllegalArgumentException(bad)
        return seconds.toLong() * 1000
    }

    /** wanted._clean: NFC, single spaces, no stray zero-width characters at the ends. */
    fun clean(s: String): String = Py.strip(Py.split(PyUnicode.nfc(s)).joinToString(" ").trim { it in INVISIBLE })
}
