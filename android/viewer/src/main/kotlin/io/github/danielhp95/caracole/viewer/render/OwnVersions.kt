package io.github.danielhp95.caracole.viewer.render

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.library.Kept
import io.github.danielhp95.caracole.core.library.OverrideWriters
import io.github.danielhp95.caracole.core.library.Overrides
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyUrl
import io.github.danielhp95.caracole.viewer.render.internal.Sources
import io.github.danielhp95.caracole.viewer.sheet.MusicKeys
import io.github.danielhp95.caracole.viewer.sheet.SheetView
import io.github.danielhp95.caracole.viewer.sheet.Sheets
import io.github.danielhp95.caracole.viewer.theory.Key
import io.github.danielhp95.caracole.viewer.theory.Theory
import io.github.danielhp95.caracole.viewer.version.Version
import io.github.danielhp95.caracole.viewer.version.Versions
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.io.File

/**
 * render.own_versions_upgraded on the phone: once, the `[version]` entries kept by a major key named by its letter
 * alone (`key=B&capo=2`), made while caracole read such a sheet as major, rewritten in the minor key that plays the
 * sheet where they did (`key=Bm&capo=2`), through OverrideWriters.addVersion, the rest of each entry as it was; kv
 * `keys:own_versions` records what was rewritten, `{"rewritten": {song key: [entry, new entry]}}`, so overrides read
 * before (a caller's) are played as they are now. Called before every song's pages, which play each song in its own
 * version, and before the songbooks.
 */
object OwnVersions {
    /** own_versions_upgraded: [overrides] with the songs' own versions as they play now. */
    fun upgraded(db: Db, libraryDir: File, overrides: Overrides): Overrides {
        var record = db.kvGet(RenderNames.OWN_VERSIONS_KEY)?.let(::loads)
        if (record !is JsonObject) {
            val rewritten = rewrite(db, libraryDir) ?: return overrides
            record = JsonObject(mapOf("rewritten" to JsonObject(rewritten.mapValues { (_, pair) ->
                JsonArray(listOf(JsonPrimitive(pair.first), JsonPrimitive(pair.second)))
            })))
            db.kvSetJson(RenderNames.OWN_VERSIONS_KEY, record)
        }
        val rewritten = record["rewritten"] as? JsonObject ?: return overrides
        val version = LinkedHashMap(overrides.version)
        for ((key, pair) in rewritten) {
            if (pair !is JsonArray || pair.size != 2) continue
            val (was, now) = pair.map { (it as? JsonPrimitive)?.takeIf { p -> p.isString }?.content }
            if (was != null && version[key] == was && now != null) version[key] = now
        }
        return if (version == overrides.version) overrides else overrides.copy(version = version)
    }

    /** _rewrite_own_versions: the entries rewritten in the phone's overrides as they are now, or null when they can't
     * be read or written. */
    private fun rewrite(db: Db, libraryDir: File): Map<String, Pair<String, String>>? {
        val current = try {
            Overrides.read(db)
        } catch (_: OverridesError) {
            return null
        }
        val songs = if (current.version.isNotEmpty()) Songs.list(db).associateBy { it.key } else emptyMap()
        val rewritten = LinkedHashMap<String, Pair<String, String>>()
        for ((key, entry) in current.version) {
            val song = songs[key] ?: continue
            val new = minorEntry(db, libraryDir, song, entry) ?: continue
            try {
                OverrideWriters.addVersion(db, song.display, new) { Versions.keyVersion(it) }
            } catch (_: OverridesError) {
                return null
            } catch (_: IllegalArgumentException) {
                return null
            }
            rewritten[key] = entry to new
        }
        return rewritten
    }

    /** _minor_entry: the song's `[version]` [entry] in the minor key that plays its human sheet where it played while
     * caracole read the tab's letter alone as major, or null for one to leave as it is. */
    internal fun minorEntry(db: Db, libraryDir: File, song: SongRow, entry: String): String? {
        val parts = entry.split("&").toMutableList()
        val at = parts.indexOfFirst { it.substringBefore("=") == "key" }
        if (at < 0 || parts.any { it.substringBefore("=") == "t" }) return null
        val named = parts[at].substringAfter("=", "")
        return try {
            val kept = Versions.keyVersion(entry)
            if (kept == null || PyRe.fullmatch(RenderNames.LETTER_RE, PyUrl.unquote(named, strict = true)) == null) {
                return null // a key named with its mode: as named
            }
            val letter = MusicKeys.letterAlone(db, libraryDir, song.id)
            val human = Kept.keptFiles(db, song.id).firstOrNull { it.name == RenderNames.HUMAN_SHEET }
            if (letter == null || human == null) return null
            val text = Sources.cho(song, Sources.human(db, libraryDir, human))
            val found = MusicKeys.sheetKeys(db, libraryDir, song.id).first
            val before = SheetView.viewerKey(text, letter, "tab")
            val now = SheetView.viewerKey(text, found?.key, found?.source)
            if (before == null || now == null || before.mode != "ionian" || now.mode != "aeolian") return null
            val capo = Sheets.parse(text).capo
            val was = Versions.inKey(kept, text, before, capo)
            if (where(Versions.inKey(kept, text, now, capo)) == where(was)) return null
            val tonic = Math.floorMod(kept.key.tonic + now.tonic - before.tonic, 12)
            parts[at] = if (tonic == kept.key.tonic) "key=${named}m" else "key=${Theory.keyName(Key(tonic, "aeolian"))}"
            val new = parts.joinToString("&")
            val moved = Versions.keyVersion(new)
            if (moved == null || where(Versions.inKey(moved, text, now, capo)) != where(was)) null else new
        } catch (_: Exception) {
            // a sheet that can't be read (RenderError), an entry or a key that isn't one (Python's ValueError and
            // UnicodeDecodeError), or a sheet the viewer's code can't read (a bug): the entry stays as it is
            null
        } catch (_: StackOverflowError) { // Python's RecursionError is an Exception
            null
        }
    }

    /** _where: where a version plays the sheet: its move, its mode, its capo and its instrument. */
    private fun where(v: Version) = listOf(v.t, v.mode, v.capo, v.inst)

    private fun loads(text: String): JsonElement? = try {
        PyJson.loads(text)
    } catch (_: IllegalArgumentException) {
        null
    }
}
