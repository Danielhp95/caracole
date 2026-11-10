package io.github.danielhp95.caracole.server.songbooks

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.Canonical
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.LibraryStore
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.songbooks.Setting
import io.github.danielhp95.caracole.core.songbooks.Songbook
import io.github.danielhp95.caracole.core.songbooks.SongbookSong
import io.github.danielhp95.caracole.core.songbooks.Songbooks
import io.github.danielhp95.caracole.viewer.sheet.MusicKeys
import io.github.danielhp95.caracole.viewer.sheet.SheetView
import io.github.danielhp95.caracole.viewer.sheet.Sheets
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import io.github.danielhp95.caracole.viewer.version.Version
import io.github.danielhp95.caracole.viewer.version.Versions
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction
import java.nio.file.Files
import java.nio.file.LinkOption
import java.nio.file.NoSuchFileException
import java.nio.file.attribute.BasicFileAttributes

/** songbook.Entry: one song of a songbook as it is rendered: its sheet's ChordPro ([cho]) as caracole wrote it beside
 * the song's pages, or why it has none ([missing]); [setting] the songbook's for it, [version] where the songbook plays
 * it (in that setting, else in the song's own version on that sheet), [transpose] that version's `t`; [keepsKey]
 * whether the song's own version is kept by its key, which a sheet with no key can't take. */
data class Entry(val text: String, val title: String, val artist: String, val song: SongRow? = null,
                 val cho: String? = null, val missing: String? = null, val transpose: Int = 0,
                 val version: Version = Version(), val key: String? = null, val keySource: String? = null,
                 val setting: Setting? = null, val keepsKey: Boolean = false)

/**
 * songbook.py's entries and where each plays, on the phone (lane songbook-entries), function for function, each
 * named after Python's; the songbooks that list a song are :core's Songbooks.listing, which the lookup calls too.
 * Every answer is held by vectors/songbook/entries.jsonl (SongbookTabReplay).
 *
 * - A song is found by its entry's "Artist - Title" alone (Songbooks.findEntrySong), the library re-keyed first, as
 *   find_song re-keys it ([entries] writes then, in the caller's write, when the keys are a KEY_VERSION behind).
 * - Its sheet ([sheetOf]) is the .cho of its human sheet, else of its auto sheet, while it is the bytes caracole
 *   recorded for it (kv `render:files:<song id>`, render.written_file's record, which the phone's render writes as the
 *   computer's does), read as a regular file only; one changed on disk counts as none.
 * - Where it plays: [entries]'s version, then [playsIn] and [wherePlayed] in words and as a key and a capo; and the
 *   setting `caracole songbook set` comes to ([withCapo], [onInstrument]).
 *
 * A sheet the viewer's code can't read (a bug) plays in its own version and costs the songbook nothing, as Python's
 * `except Exception` has it (its warning is the computer's log; the phone has none).
 */
object SongbookEntries {
    /** songbook.MISSING_SHEET: a song the library has, with no sheet yet. */
    const val MISSING_SHEET = "no sheet yet"

    /** songbook.MISSING_SONG: an entry the library has no song of. */
    const val MISSING_SONG = "not in the library"

    /** songbook.KEY_UNKNOWN: what [playsIn] says of a setting or a key a sheet with no key can't take. */
    const val KEY_UNKNOWN = "key unknown, as written"

    /** render.HUMAN_SHEET, AUTO_SHEET and their .cho (HUMAN_OUTPUTS[0], AUTO_OUTPUTS[0]), in the order tried. */
    private val SHEETS = listOf("sheet.txt" to "sheet.cho", "sheet (auto).txt" to "sheet (auto).cho")
    private const val AUTO_CHO = "sheet (auto).cho"

    /** render.FILES_KEY: kv `render:files:<song id>`, what caracole wrote in the song's folder. */
    private const val FILES_KEY = "render:files:"

    /** songbook.songbook_entries: the songbook's songs, in order, each with its sheet or why it has none: a song the
     * library hasn't got (removed since, say) or one without a sheet is missing, never an error. The library is
     * re-keyed first, as find_song re-keys it, unless [rekey] is false: a read (the Songbooks tab's data in
     * `/jobs.json`), which takes the keys as every write that adds or looks songs up leaves them. */
    fun entries(db: Db, libraryDir: File, overrides: Overrides, book: Songbook, rekey: Boolean = true): List<Entry> {
        if (rekey) LibraryStore(libraryDir).ensureCurrentKeys(db)
        return book.songs.map { entryOf(db, libraryDir, overrides, it) }
    }

    /** songbook.songs_to_get: the songs of [entries] a lookup could get a sheet for now (Get the missing songs now):
     * those the library has with no sheet yet, in the songbook's order, once each, but those overrides.toml ignores
     * or ignored by their status. A song "not in the library" is no one's to look up. */
    fun songsToGet(entries: List<Entry>, overrides: Overrides): List<SongRow> {
        val songs = LinkedHashMap<Long, SongRow>()
        for (e in entries) {
            val song = e.song ?: continue
            if (e.missing == MISSING_SHEET && song.status != "ignored" && song.key !in overrides.ignore) {
                songs.putIfAbsent(song.id, song)
            }
        }
        return songs.values.toList()
    }

    /** songbook._entry_of. */
    private fun entryOf(db: Db, libraryDir: File, overrides: Overrides, entry: SongbookSong): Entry {
        val text = entry.text
        val setting = entry.setting
        val song = Songbooks.findEntrySong(db, text)
        if (song == null) {
            val cut = text.indexOf(" - ")
            val artist = if (cut < 0) text else text.substring(0, cut)
            val title = if (cut < 0) "" else text.substring(cut + 3)
            return Entry(text, Py.strip(title).ifEmpty { text }, Py.strip(artist), missing = MISSING_SONG,
                         setting = setting)
        }
        val title = Normalize.cleanTitle(song.title)
        val (name, cho) = sheetOf(db, libraryDir, song)
            ?: return Entry(text, title, song.artist, song, missing = MISSING_SHEET, setting = setting)
        val (human, auto) = MusicKeys.sheetKeys(db, libraryDir, song.id)
        val found = if (name == AUTO_CHO) auto else human
        val key = found?.key
        val source = found?.source
        val version = playedIn(cho, key, source, Versions.ownVersion(overrides, song, cho, key, source), setting)
        return Entry(text, title, song.artist, song, cho = cho, transpose = version.t, version = version, key = key,
                     keySource = source, setting = setting, keepsKey = keepsKey(overrides, song))
    }

    /** songbook._played_in: where the songbook plays the song ([Versions.inSetting]), [key] being its sheet's and
     * [keySource] where it came from; [own] for no setting, or a sheet the viewer's code can't read. */
    private fun playedIn(cho: String, key: String?, keySource: String?, own: Version, setting: Setting?): Version {
        if (setting == null || setting == Setting()) return own
        return guarded(own) { Versions.inSetting(own, setting, SheetView.viewerKey(cho, key, keySource), Sheets.parse(cho).capo) }
    }

    /** render.keeps_key: whether the song's own version is kept by its key (a `[version]` with one). */
    private fun keepsKey(overrides: Overrides, song: SongRow): Boolean =
        overrides.version[song.key]?.let { Versions.keyVersion(it) != null } ?: false

    /**
     * songbook.with_capo: [setting] for the song of [entry] with the capo it plays at now on its sheet, where the
     * setting names a key or a mode and no capo (`caracole songbook set`): a setting's key is the key of the shapes
     * played, so a sheet in place of this one, with another capo, keeps the key it sounds in. As given for a song
     * without a sheet, a sheet the viewer's code can't read, a setting naming its capo, or one played on an
     * instrument with no capo, whose key is the key it sounds in.
     */
    fun withCapo(entry: Entry, setting: Setting, overrides: Overrides): Setting {
        val song = entry.song
        val cho = entry.cho
        if (setting.capo != null || !Versions.places(setting) || cho == null || song == null) return setting
        val capo = guarded<Int?>(null) {
            val own = Versions.ownVersion(overrides, song, cho, entry.key, entry.keySource)
            val version = playedIn(cho, entry.key, entry.keySource, own, setting)
            if (!Versions.playedOn(version).capo) {
                null
            } else {
                Versions.playedKey(version, SheetView.viewerKey(cho, entry.key, entry.keySource), Sheets.parse(cho).capo).second
            }
        } ?: return setting
        return if (capo <= Versions.CAPO_MAX) setting.copy(capo = capo) else setting
    }

    /**
     * songbook.on_instrument: [setting], which moves the song of [entry] to its instrument (`--instrument`), with the
     * key and the capo that keep the song at the pitch it plays at now ([entry] where the songbook plays it now), as
     * the Songbooks tab's menus set them: from an instrument that takes a capo to one that takes none, or the other
     * way, the key is the key it sounds in now, and the capo none on the one that takes a capo. A key or a capo given
     * stays as given. As given for a setting with no key, between two instruments alike in their capo, and for a
     * song without a sheet, or with one that has no key caracole can read.
     */
    fun onInstrument(entry: Entry, setting: Setting, keyGiven: Boolean = false, capoGiven: Boolean = false): Setting {
        if (keyGiven || setting.key == null || setting.instrument == null || entry.cho == null) return setting
        val now = Versions.playedOn(entry.version)
        val then = Versions.instrumentOf(setting.instrument) ?: return setting
        if (now.capo == then.capo) return setting
        val (key, capo) = wherePlayed(entry).second ?: return setting
        if (key == null) return setting
        val sounds = Theory.spelling(null)[Math.floorMod(key.tonic + capo, 12)]
        return setting.copy(key = sounds, capo = if (capoGiven || !then.capo) setting.capo else 0)
    }

    /** songbook.plays_in: where the songbook plays the song, in words, for its set list ("G Dorian", "E Minor,
     * capo 2", "Transposed +2" for a sheet with no key), or [KEY_UNKNOWN]; null for a song without a sheet. */
    fun playsIn(entry: Entry): String? = wherePlayed(entry).first

    /** songbook.where_played: [playsIn]'s words and, for the set list's menus, the key of the shapes played (null for
     * a sheet with no key) and the capo, from one reading of the sheet; both null for a song without a sheet, or one
     * the viewer's code can't read. */
    fun wherePlayed(entry: Entry): Pair<String?, Pair<Key?, Int>?> {
        val cho = entry.cho ?: return null to null
        return guarded(null to null) {
            val shapes = SheetView.viewerKey(cho, entry.key, entry.keySource)
            val capo = Sheets.parse(cho).capo
            val played = Versions.playedKey(entry.version, shapes, capo)
            if (shapes == null && (Versions.places(entry.setting) || entry.keepsKey)) {
                KEY_UNKNOWN to played
            } else {
                Versions.playedLabel(entry.version, shapes, capo) to played
            }
        }
    }

    /** songbook._sheet_of: the .cho of the song's human sheet, else of its auto sheet, as caracole last wrote it
     * (render.written_file): (its name, its text). One that is no longer those bytes (changed on a device, a link in
     * its place) or isn't UTF-8 counts as none: only caracole's sheets go into a songbook. */
    fun sheetOf(db: Db, libraryDir: File, song: SongRow): Pair<String, String>? {
        val kept = Kept.keptFiles(db, song.id).mapTo(HashSet()) { it.name }
        val folder = LibraryStore(libraryDir).folderOf(song)
        for ((sheet, cho) in SHEETS) {
            if (sheet !in kept) continue
            val (sha, size) = writtenFile(db, song.id, cho) ?: continue
            val data = regularBytes(File(folder, cho)) ?: continue
            if (data.size.toLong() == size && Canonical.sha256Hex(data) == sha) {
                return cho to (strictUtf8(data) ?: continue)
            }
        }
        return null
    }

    /** render.written_file: the SHA-256 and the length of the file [name] caracole last wrote in the song's folder, as
     * kv `render:files:<song id>` records it (render.written_entry: a string and an int that is no bool), or null. */
    internal fun writtenFile(db: Db, songId: Long, name: String): Pair<String, Long>? {
        val text = db.kvGet("$FILES_KEY$songId") ?: return null
        val record = try {
            PyJson.loads(text)
        } catch (e: Exception) {  // kv_get_json's json.loads would raise: a record no writer made, read as none
            return null
        } as? JsonObject ?: return null
        return writtenEntry(record[name])
    }

    /** render.written_entry: the SHA-256 and the length an entry of a record says, or null for one that says
     * neither. */
    internal fun writtenEntry(entry: Any?): Pair<String, Long>? {
        if (entry !is JsonObject) return null
        val sha = (entry["sha256"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null
        val size = (entry["size"] as? JsonPrimitive)?.takeIf { !it.isString }?.content
            ?.takeIf { c -> c.isNotEmpty() && c.trimStart('-').let { d -> d.isNotEmpty() && d.all { it in '0'..'9' } } }
            ?.toLongOrNull() ?: return null
        return sha to size
    }

    /** library.read_regular: the bytes of the regular file at [file], never read through a link in its place; null
     * for nothing there, anything else, or a file that can't be read. */
    internal fun regularBytes(file: File): ByteArray? {
        val path = file.toPath()
        val attrs = try {
            Files.readAttributes(path, BasicFileAttributes::class.java, LinkOption.NOFOLLOW_LINKS)
        } catch (e: NoSuchFileException) {
            return null
        } catch (e: IOException) {
            return null
        }
        if (!attrs.isRegularFile) return null
        return try {
            Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS).use { it.readBytes() }
        } catch (e: IOException) {
            null
        }
    }

    /** bytes.decode("utf-8"): strict, a byte order mark kept as U+FEFF; null for bytes that aren't UTF-8. */
    private fun strictUtf8(data: ByteArray): String? = try {
        Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
            .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(data)).toString()
    } catch (e: CharacterCodingException) {
        null
    }

    /** What Python's `except Exception` around the viewer's code holds, a stack overflow (its RecursionError) too:
     * [otherwise] in its place. */
    private inline fun <T> guarded(otherwise: T, block: () -> T): T = try {
        block()
    } catch (e: Exception) {
        otherwise
    } catch (e: StackOverflowError) {
        otherwise
    }
}
