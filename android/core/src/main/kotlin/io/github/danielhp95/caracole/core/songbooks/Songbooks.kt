package io.github.danielhp95.caracole.core.songbooks

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.index.Stamps
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.keys.SafeName
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.SongbookStore
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.library.StoredSongbook
import io.github.danielhp95.caracole.core.library.internal.Rekey
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyStr
import io.github.danielhp95.caracole.core.py.PyUnicode
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import java.util.TreeSet

/** songbook.SongbookError: songbooks.toml (phone_songbooks) can't be read, or a change to it can't be made; the
 * message says why, in songbook.py's words. */
class SongbookError(message: String) : Exception(message)

/** version.Setting: a songbook's setting for a song, its parts as songbook.check_setting keeps them. :core's, so the
 * songbooks and the viewer (viewer.version.Setting) share one type. */
data class Setting(val key: String? = null, val mode: String? = null, val capo: Int? = null,
                   val instrument: String? = null)

/** songbook.SongbookSong: a songbook's entry, its "Artist - Title" and the setting it carries, if any. */
data class SongbookSong(val text: String, val setting: Setting? = null)

/** songbook.Songbook: a songbook, its name and its songs in order. */
data class Songbook(val name: String, val songs: List<SongbookSong> = emptyList()) {
    /** Its songs' "Artist - Title", in order. */
    val texts: List<String> get() = songs.map { it.text }
}

/**
 * songbook.py's names, entries and writers on the phone, over phone_songbooks (SongbookStore): each writer is called
 * inside Database.write, refuses with songbook.py's words ([SongbookError]) before it writes anything, and writes in
 * a savepoint of its own (lane songbook-writers; [set]'s check of a setting and [listing], lane songbook-entries).
 *
 * - **Names** ([checkName]): NFC, no control or format character (Cc, Cf) but a space or a tab, whitespace (Python's)
 *   collapsed, 80 characters (code points) at most, no leading dot, and a letter or a digit in its folder's name. A
 *   name is found in any case ([nameKey]), and two songbooks never share a name's key nor a folder, `_songbooks/<safe
 *   name>` in any case ([folderKey], [checkFree]): a phone's file system may not tell them apart.
 * - **Entries** ([entryKeys]): an "Artist - Title" stands for the identity key of each cut at " - " whose two sides
 *   aren't empty, as an artist's name may hold one ("Earth - Wind - Fire - September"), so two entries name one song
 *   when their keys meet ([sameEntry]: accents, case, Traditional or Simplified characters and a version suffix don't
 *   count), and the library's song of an entry is the first of its keys, in Python's order, the library has
 *   ([findEntrySong]), never a song a search finds.
 * - **Writers**: [make] after the others, a song named twice in it once, where it is first named; [add] the songs it
 *   hasn't got, in order; [remove] every song it names, every time; [move] to a place counted from 1 (past the end:
 *   last); [rename] in its place; [delete]. Each finds the songbook by its name in any case, and keeps each song's
 *   setting as it is. What a sync takes is SongbookStore.put, songbook.put_songbook's rules.
 *
 * The words are songbook.py's, for its file and its commands ("in songbooks.toml", "caracole songbook list shows
 * them"), so that a refusal reads the same on both sides.
 */
object Songbooks {
    /** songbook.FILE_NAME: what the words call the songbooks. */
    const val FILE_NAME = "songbooks.toml"

    /** songbook.FOLDER: where a songbook's files go, a folder a songbook, `_songbooks/<safe name>`. */
    const val FOLDER = "_songbooks"

    /** songbook.MAX_NAME: a name's characters (code points) at most. */
    const val MAX_NAME = 80

    // --- names ---------------------------------------------------------------------------------------------------

    /** songbook.check_name: a songbook's name as kept, its whitespace trimmed and collapsed; SongbookError for one
     * that can't name a folder in the library: empty, too long, hidden (a leading dot), with a line break or another
     * control character, or with no letter or digit. */
    fun checkName(name: String): String {
        val nfc = PyUnicode.nfc(name)
        if (Py.codePoints(nfc).any { it != ' '.code && it != '\t'.code && PyUnicode.category(it) in CONTROLS }) {
            throw SongbookError("A songbook's name can't hold a line break or a control character: ${PyStr.repr(name)}")
        }
        val text = Py.split(nfc).joinToString(" ")
        if (text.isEmpty()) throw SongbookError("A songbook needs a name")
        if (Py.len(text) > MAX_NAME) {
            throw SongbookError("A songbook's name is $MAX_NAME characters at most: " +
                                "${PyStr.repr(Py.slice(text, 0, MAX_NAME))}…")
        }
        if (text.startsWith(".")) {
            throw SongbookError("A songbook's name can't start with a dot (its folder would be hidden): ${PyStr.repr(text)}")
        }
        if (Py.codePoints(SafeName.safeName(text)).none(PyUnicode::isAlnum)) {
            throw SongbookError("A songbook's name needs a letter or a digit: ${PyStr.repr(text)}")
        }
        return text
    }

    /** songbook.name_key: how names are compared, "campfire" finding "Campfire" (NFC, whitespace collapsed,
     * casefold). */
    fun nameKey(name: String): String = SongbookStore.nameKey(name)

    /** songbook._folder_key: how folders are compared, a songbook's safe name casefolded. */
    fun folderKey(name: String): String = PyUnicode.casefold(SafeName.safeName(name))

    /** songbook.check_free: refuse a name another songbook of [books] has, or whose folder another's would be; [but]
     * (the very object of [books]: the songbook renamed or replaced) aside. The first songbook that clashes is
     * named, by its name before its folder. */
    fun checkFree(books: List<Songbook>, name: String, but: Songbook? = null) =
        checkFreeOf(books.map { it.name }, name, books.indexOfFirst { it === but })

    internal fun checkFreeOf(names: List<String>, name: String, skip: Int) {
        val key = nameKey(name)
        val folder = folderKey(name)
        for ((i, other) in names.withIndex()) {
            if (i == skip) continue
            if (nameKey(other) == key) {
                throw SongbookError("A songbook named \"$other\" is there already: pick another name, or add songs " +
                                    "to it with caracole songbook add")
            }
            if (folderKey(other) == folder) {
                throw SongbookError("\"$name\" would share the folder $FOLDER/${SafeName.safeName(name)} with the " +
                                    "songbook \"$other\": pick another name")
            }
        }
    }

    // --- entries -------------------------------------------------------------------------------------------------

    /** songbook.entry_keys: the identity keys an "Artist - Title" may stand for, one for each " - " it could be cut
     * at whose artist and title, stripped, aren't empty; in Python's order (by code point), as find_entry_song tries
     * them. */
    fun entryKeys(text: String): Set<String> {
        val parts = text.split(" - ")
        val keys = TreeSet(Py.CODE_POINT_ORDER)
        for (i in 1 until parts.size) {
            val artist = Py.strip(parts.subList(0, i).joinToString(" - "))
            val title = Py.strip(parts.subList(i, parts.size).joinToString(" - "))
            if (artist.isNotEmpty() && title.isNotEmpty()) keys += Normalize.identityKey(artist, title)
        }
        return keys
    }

    /** songbook.same_entry: whether two "Artist - Title" name one song, their identity keys meeting. */
    fun sameEntry(a: String, b: String): Boolean = meet(entryKeys(a), entryKeys(b))

    /** songbook.find_entry_song: the library's song an entry names, by its "Artist - Title" alone (the first of
     * [entryKeys] a song has), or null; never by a search, so an entry whose song is gone (or typed with a typo) is
     * missing, not another song with a title like it. The songs' keys are read as stored: after a KEY_VERSION change
     * the caller re-keys first (LibraryStore.ensureCurrentKeys), as find_song does. */
    fun findEntrySong(db: Db, text: String): SongRow? {
        for (key in entryKeys(text)) Songs.byKey(db, key)?.let { return it }
        return null
    }

    // --- reading -------------------------------------------------------------------------------------------------

    /** songbook.load_songbooks: every songbook, in its place, each song with its setting (none when it says
     * nothing). */
    fun all(db: Db): List<Songbook> = SongbookStore.all(db).map(::book)

    /** songbook.find_songbook: the songbook of this name, in any case. */
    fun find(books: List<Songbook>, name: String): Songbook? {
        val key = nameKey(name)
        return books.firstOrNull { nameKey(it.name) == key }
    }

    /** peer_sync.songbook_value: a songbook's name and its songs in order, each `[entry, parts]`, its setting's parts
     * that say something (what a songbook unit is, and what the vectors write). */
    fun value(book: Songbook): JsonObject = JsonObject(linkedMapOf(
        "name" to JsonPrimitive(book.name),
        "songs" to JsonArray(book.songs.map { stored(it) }),
    ))

    // --- writing -------------------------------------------------------------------------------------------------

    /** songbook.make_songbook: a songbook of these songs, in this order, after the others; a song named twice
     * ([sameEntry]) is in it once, where it is first named. Its name checked ([checkName]), then each song, then
     * that no other songbook has its name or its folder. */
    fun make(db: Db, name: String, entries: List<String>): Songbook {
        val clean = checkName(name)
        val songs = ArrayList<String>()
        val keys = ArrayList<Set<String>>()
        for (text in entries) {
            val entry = entry(text, "[${quoted(clean)}]")
            val mine = entryKeys(entry)
            if (keys.none { meet(it, mine) }) {
                songs += entry
                keys += mine
            }
        }
        return db.savepoint(SAVEPOINT) {
            checkFreeOf(SongbookStore.all(db).map { it.name }, clean, -1)
            SongbookStore.put(db, clean, JsonArray(songs.map { stored(SongbookSong(it)) }))
            Songbook(clean, songs.map { SongbookSong(it) })
        }
    }

    /** songbook.add_to_songbook: append the songs the songbook hasn't got ([sameEntry]), in order, each with no
     * setting; those added. Each song is checked before the songbook is looked for. */
    fun add(db: Db, name: String, entries: List<String>): List<String> {
        val wanted = entries.map { entry(it, "a song") }
        return db.savepoint(SAVEPOINT) {
            val held = header(db, name)
            val have = held.songs.mapTo(ArrayList()) { entryKeys(textOf(it)) }
            val added = ArrayList<String>()
            for (entry in wanted) {
                val mine = entryKeys(entry)
                if (have.none { meet(it, mine) }) {
                    added += entry
                    have += mine
                }
            }
            if (added.isNotEmpty()) {
                SongbookStore.replace(db, held, JsonArray(held.songs + added.map { stored(SongbookSong(it)) }))
            }
            added
        }
    }

    /** songbook.remove_from_songbook: take these songs out of the songbook, every time it names them ([sameEntry]);
     * those taken out, in order, as it wrote them. */
    fun remove(db: Db, name: String, entries: List<String>): List<String> = db.savepoint(SAVEPOINT) {
        val held = header(db, name)
        val gone = entries.map(::entryKeys)
        val kept = ArrayList<JsonElement>()
        val removed = ArrayList<String>()
        for (song in held.songs) {
            val keys = entryKeys(textOf(song))
            if (gone.any { meet(it, keys) }) removed += textOf(song) else kept += song
        }
        if (removed.isNotEmpty()) SongbookStore.replace(db, held, JsonArray(kept))
        removed
    }

    /** songbook.move_in_songbook: put the song (the first the songbook names as [entry], [sameEntry]) at [position],
     * counted from 1, past the end last, with its setting; where it went. A position below 1 is refused first. */
    fun move(db: Db, name: String, entry: String, position: Int): Int {
        if (position < 1) throw SongbookError("A position counts from 1, the songbook's first song: got $position")
        return db.savepoint(SAVEPOINT) {
            val held = header(db, name)
            val keys = entryKeys(entry)
            val songs = held.songs.toMutableList()
            val at = songs.indexOfFirst { meet(entryKeys(textOf(it)), keys) }
            if (at < 0) {
                throw SongbookError("\"$entry\" isn't in the songbook \"${held.name}\": caracole songbook show lists " +
                                    "its songs")
            }
            val to = minOf(position, songs.size) - 1
            if (to != at) {
                songs.add(to, songs.removeAt(at))
                SongbookStore.replace(db, held, JsonArray(songs))
            }
            to + 1
        }
    }

    /**
     * songbook.set_song_setting: give the first song of the songbook that [entry] names ([sameEntry]) its [setting],
     * in its place; null, or a setting that says nothing, takes it off, and the song says nothing again. The setting
     * is checked first, before the songbook is looked for (songbook.check_setting: [problem] is the viewer's
     * Versions.settingProblem of its parts, which :core can't see), refused as "a setting: <why>"; then the
     * songbook, by its name in any case; then the song. The other songs, and the songbook's place, stay as they are.
     */
    fun set(db: Db, name: String, entry: String, setting: Setting?, problem: (Setting) -> String?) {
        val given = setting?.takeUnless { it == Setting() }
        given?.let(problem)?.let { throw SongbookError("a setting: $it") }
        db.savepoint(SAVEPOINT) {
            val held = header(db, name)
            val songs = held.songs.toMutableList()
            val at = songs.indexOfFirst { sameEntry(textOf(it), entry) }
            if (at < 0) {
                throw SongbookError("\"$entry\" isn't in the songbook \"${held.name}\": caracole songbook show lists " +
                                    "its songs")
            }
            val now = stored(SongbookSong(textOf(songs[at]), given))
            if (now != songs[at]) {
                songs[at] = now
                SongbookStore.replace(db, held, JsonArray(songs))
            }
        }
    }

    /** songbook.songbooks_listing: the songbooks of [books] whose entries name [song], each found as
     * [findEntrySong] finds it, never by a search (get.py's songbooks stage; SongbookEntries' songs_to_get).
     * find_song re-keys the library on every call (ensure_current_keys) and [findEntrySong] doesn't, so this re-keys
     * it first (LibraryStore.ensureCurrentKeys's, in the caller's write), as SongbookEntries.entries does. */
    fun listing(db: Db, books: List<Songbook>, song: SongRow): List<Songbook> {
        Rekey.ensure(db, Stamps.now())
        return books.filter { book -> book.songs.any { findEntrySong(db, it.text)?.id == song.id } }
    }

    /** songbook.rename_songbook: give the songbook another name ([checkName]'s, checked first), in its place, its
     * songs as they are; the songbook renamed. Its own name and folder are its to take again (a case, a slash for a
     * dash); another's are refused. */
    fun rename(db: Db, name: String, new: String): Songbook {
        val clean = checkName(new)
        return db.savepoint(SAVEPOINT) {
            val held = header(db, name)
            val stored = SongbookStore.all(db)
            checkFreeOf(stored.map { it.name }, clean, stored.indexOfFirst { it.key == held.key })
            if (held.name != clean) SongbookStore.rename(db, held, clean)
            Songbook(clean, book(held).songs)
        }
    }

    /** songbook.delete_songbook: take the songbook out; the songbook, with its songs and their settings. */
    fun delete(db: Db, name: String): Songbook = db.savepoint(SAVEPOINT) {
        val held = header(db, name)
        SongbookStore.drop(db, held)
        book(held)
    }

    // --- the pieces ----------------------------------------------------------------------------------------------

    /** The categories a name holds none of but a space and a tab: control and format characters. */
    private val CONTROLS = setOf("Cc", "Cf")

    private const val SAVEPOINT = "songbook"

    /** songbook._header: the songbook held under this name, in any case; SongbookError if none. */
    private fun header(db: Db, name: String): StoredSongbook {
        val key = nameKey(name)
        return SongbookStore.all(db).firstOrNull { nameKey(it.name) == key }
            ?: throw SongbookError("No songbook named \"${Py.split(name).joinToString(" ")}\" in $FILE_NAME: " +
                                   "caracole songbook list shows them")
    }

    /** songbook._entry: an entry as kept, its whitespace collapsed; SongbookError naming [where] for one that isn't
     * "Artist - Title". */
    private fun entry(value: String, where: String): String {
        val text = Py.split(value).joinToString(" ")
        if (entryKeys(text).isEmpty()) throw SongbookError("$where: expected \"Artist - Title\", got ${PyStr.repr(value)}")
        return text
    }

    /** songbook._quoted: a name as a TOML header quotes it. */
    private fun quoted(name: String): String = "\"" + name.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

    private fun meet(a: Set<String>, b: Set<String>): Boolean = a.any { it in b }

    /** A stored song's entry, `[entry, parts]`'s first. */
    private fun textOf(song: JsonElement): String = ((song as JsonArray)[0] as JsonPrimitive).content

    /** A song as phone_songbooks holds it: `[entry, parts]`, its setting's parts that say something, in
     * songbook_value's order. */
    private fun stored(song: SongbookSong): JsonArray {
        val parts = LinkedHashMap<String, JsonElement>()
        song.setting?.let { s ->
            s.key?.let { parts["key"] = JsonPrimitive(it) }
            s.mode?.let { parts["mode"] = JsonPrimitive(it) }
            s.capo?.let { parts["capo"] = JsonPrimitive(it) }
            s.instrument?.let { parts["instrument"] = JsonPrimitive(it) }
        }
        return JsonArray(listOf(JsonPrimitive(song.text), JsonObject(parts)))
    }

    private fun book(held: StoredSongbook): Songbook = Songbook(held.name, held.songs.map { song ->
        val parts = (song as JsonArray)[1] as JsonObject
        fun part(name: String) = (parts[name] as? JsonPrimitive)?.takeUnless { it is JsonNull }
        val setting = Setting(part("key")?.content, part("mode")?.content, part("capo")?.intOrNull,
                              part("instrument")?.content)
        SongbookSong(textOf(song), setting.takeUnless { it == Setting() })
    })
}
