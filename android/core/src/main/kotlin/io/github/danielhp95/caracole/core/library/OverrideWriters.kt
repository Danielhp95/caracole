package io.github.danielhp95.caracole.core.library

import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.internal.overrides.Addresses
import io.github.danielhp95.caracole.core.library.internal.overrides.PyValues
import io.github.danielhp95.caracole.core.library.internal.overrides.Readers
import io.github.danielhp95.caracole.core.library.internal.overrides.Rows
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyStr
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * overrides.py's add_* writers on the phone: each leaves `phone_overrides` exactly as overrides.song_entries reads
 * overrides.toml after the same add on the computer (vectors/library/overrides_writes.jsonl): a row a song a table,
 * its value in the form song_entries yields (a pin's address through pin_url, a rejection's `"a/s"` keyed and sorted
 * by code point, a version stripped of a leading "#" or "?"), so that the computer's put_song_entries reads what the
 * phone wrote back as it is, and the unit agrees at the next sync.
 *
 * The song's entry is found by its key, as the table is read: the song written another way changes the entry it has,
 * which keeps the name it is written under, but where Python writes a new entry under the name given ([addMatch],
 * [addPin]: the last entry counts), and the same value again writes nothing. A refusal is [OverridesError] with
 * overrides.py's words (a digit int() can't read, [IllegalArgumentException]), and writes nothing. Each runs in a
 * savepoint of its own, inside the caller's Database.write.
 */
object OverrideWriters {
    /** overrides.add_match: the song's `[match]`, the UG song `"ug-artist/ug-song"` it is, written under [display]. */
    fun addMatch(db: Db, display: String, ugRef: String) {
        val key = Addresses.overrideKey(display)
        val (artist, song) = Readers.ugRef(JsonPrimitive(ugRef), "[match] ${PyStr.repr(display)}")
        db.savepoint("add_match") { Rows.put(db, "match", key, display, JsonPrimitive("$artist/$song")) }
    }

    /** overrides.add_pin: the song's `[pin]`, the tab pages [urls] in their order (each as pin_url writes it),
     * written under [display]. */
    fun addPin(db: Db, display: String, urls: List<String>) {
        val key = Addresses.overrideKey(display)
        for (u in urls) Addresses.tabIdFromUrl(u)
        db.savepoint("add_pin") { Rows.put(db, "pin", key, display, JsonArray(urls.map { JsonPrimitive(Addresses.pinUrl(it)) })) }
    }

    /** overrides.remove_pin: the song's pins of [tabs] (every one, with null) taken out, and its entry with its last
     * pin; whether one was there. */
    fun removePin(db: Db, display: String, tabs: Set<Long>?): Boolean {
        val key = Addresses.overrideKey(display)
        return db.savepoint("remove_pin") {
            val entry = Rows.get(db, "pin", key) ?: return@savepoint false
            fun goes(value: JsonElement): Boolean = try {
                tabs == null || Addresses.tabIdFromUrl(PyValues.str(value)) in tabs
            } catch (e: OverridesError) {
                false
            }
            when (val values = entry.value) {
                is JsonArray -> {
                    val kept = values.filterNot(::goes)
                    when {
                        kept.size == values.size -> false
                        kept.isEmpty() -> true.also { Rows.delete(db, "pin", key) }
                        else -> true.also { Rows.setValue(db, "pin", key, JsonArray(kept)) }
                    }
                }
                is JsonPrimitive -> (values.isString && goes(values)).also { if (it) Rows.delete(db, "pin", key) }
                else -> false
            }
        }
    }

    /** overrides.add_lacuerda: the song's `[lacuerda]`, the song or version at [url], as caracole asks for it. */
    fun addLacuerda(db: Db, display: String, url: String) {
        val key = Addresses.overrideKey(display)
        setEntry(db, "lacuerda", key, display, JsonPrimitive(Addresses.lacuerdaPickFromUrl(JsonPrimitive(url)).url))
    }

    /** overrides.add_harptabs: the song's `[harptabs]`, the tab at [url], as caracole asks for it. */
    fun addHarptabs(db: Db, display: String, url: String) {
        val key = Addresses.overrideKey(display)
        setEntry(db, "harptabs", key, display, JsonPrimitive(Addresses.harptabsPickFromUrl(JsonPrimitive(url)).url))
    }

    /** overrides.add_gametabs: the song's `[gametabs]`, the tab at [url], as caracole asks for it. */
    fun addGametabs(db: Db, display: String, url: String) {
        val key = Addresses.overrideKey(display)
        setEntry(db, "gametabs", key, display, JsonPrimitive(Addresses.gametabsPickFromUrl(JsonPrimitive(url)).url))
    }

    /** overrides.add_reject: the UG songs [refs] (`"ug-artist/ug-song"`) added to the song's `[reject]`, keeping
     * those there; one rejected already isn't added again, and none writes nothing. */
    fun addReject(db: Db, display: String, refs: List<String>) {
        val key = Addresses.overrideKey(display)
        val where = "[reject] ${PyStr.repr(display)}"
        val given = LinkedHashSet<Pair<String, String>>()
        for (r in refs) given += Readers.ugRef(JsonPrimitive(r), where)
        if (given.isEmpty()) return
        db.savepoint("add_reject") {
            val entry = Rows.get(db, "reject", key)
            val rejected = LinkedHashSet<Pair<String, String>>()
            entry?.let { e ->
                val there = "[reject] ${PyStr.repr(e.written)}"
                PyValues.strings(e.value, there).mapTo(rejected) { Readers.ugRef(JsonPrimitive(it), there) }
            }
            rejected += given
            // song_entries' sorted(): by code point, never String.compareTo's UTF-16 units.
            val value = JsonArray(rejected.map { (a, s) -> "$a/$s" }.sortedWith(Py.CODE_POINT_ORDER).map(::JsonPrimitive))
            when {
                entry == null -> Rows.put(db, "reject", key, display, value)
                value != entry.value -> Rows.setValue(db, "reject", key, value)
            }
        }
    }

    /** overrides.add_alias: [ugArtist] added to the artist's `[alias]`, keeping the slugs there; one there already,
     * by its key, changes nothing. */
    fun addAlias(db: Db, sourceArtist: String, ugArtist: String) {
        val artist = Normalize.slugKey(sourceArtist)
        val slug = Normalize.ugSlugKey(ugArtist)
        db.savepoint("add_alias") {
            val entry = Rows.get(db, "alias", artist)
            if (entry == null) {
                Rows.put(db, "alias", artist, sourceArtist, JsonArray(listOf(JsonPrimitive(slug))))
                return@savepoint
            }
            val current = PyValues.strings(entry.value, "[alias] ${PyStr.repr(entry.written)}").map(Normalize::ugSlugKey)
            if (slug !in current) Rows.setValue(db, "alias", artist, JsonArray((current + slug).map(::JsonPrimitive)))
        }
    }

    /** overrides.add_ignore: the song in `[ignore] songs`, once. */
    fun addIgnore(db: Db, display: String) {
        val key = Addresses.overrideKey(display)
        db.savepoint("add_ignore") {
            if (Rows.get(db, "ignore", key) == null) Rows.put(db, "ignore", key, display, JsonPrimitive(true))
        }
    }

    /**
     * overrides.add_version: the song's `[version]` made [query] (a viewer's address, its "#" or "?" left out, or a
     * version kept by its key), or with null taken out. A version kept by its key is checked by [keyVersion],
     * viewer/version.py's `key_version` (M5's `Versions.keyVersion`, which raises IllegalArgumentException with its
     * words), as Python checks it.
     */
    fun addVersion(db: Db, display: String, query: String?, keyVersion: (String) -> Any?) {
        val key = Addresses.overrideKey(display)
        val value = query?.let { Readers.version(JsonPrimitive(it), "[version] ${PyStr.repr(display)}", keyVersion) }
        db.savepoint("add_version") {
            if (value == null) Rows.delete(db, "version", key) else setEntry(db, "version", key, display, JsonPrimitive(value))
        }
    }

    /**
     * overrides.add_harmonica: how the song's harmonica tab [tab] (`harmonica-1.txt`) is read, [reading] a notation's
     * name, "legend" or a table of what its symbols mean; with null the tab taken out, and the song's entry with its
     * last tab. The reading is checked by [checkSpec], viewer/harptab.py's `check_spec` (M5's `HarpTabs.checkSpec`,
     * which raises IllegalArgumentException with its words), as Python checks it.
     */
    fun addHarmonica(db: Db, display: String, tab: String, reading: JsonElement?, checkSpec: (JsonElement) -> Unit) {
        val key = Addresses.overrideKey(display)
        val where = "[harmonica] ${PyStr.repr(display)} ${PyStr.repr(tab)}"
        val read = reading?.takeIf { it !is JsonNull }?.let { Readers.harmonicaReading(it, where, checkSpec) }
        if (read == null && !Readers.isHarmonicaTab(tab)) {
            throw OverridesError("$where: expected a harmonica tab's name, harmonica-N.txt")
        }
        db.savepoint("add_harmonica") {
            val entry = Rows.get(db, "harmonica", key)
            val current = entry?.value
            if (current != null && current !is JsonObject) {
                throw OverridesError("[harmonica] ${PyStr.repr(entry.written)}: expected a table of its harmonica tabs")
            }
            current as JsonObject?
            if (read == null && (current == null || tab !in current)) return@savepoint
            if (read != null && current != null && current[tab] == read) return@savepoint
            val tabs = LinkedHashMap(current.orEmpty())
            if (read == null) tabs.remove(tab) else tabs[tab] = read
            when {
                tabs.isEmpty() -> Rows.delete(db, "harmonica", key)
                entry != null -> Rows.setValue(db, "harmonica", key, JsonObject(tabs))
                else -> Rows.put(db, "harmonica", key, display, JsonObject(tabs))
            }
        }
    }

    /** overrides._set_entry: the song's entry of [table] made [value], under the name it is written under, or under
     * [display] for a song with none; the same value again writes nothing. */
    private fun setEntry(db: Db, table: String, key: String, display: String, value: JsonElement) {
        db.savepoint("set_entry") {
            val entry = Rows.get(db, table, key)
            when {
                entry == null -> Rows.put(db, table, key, display, value)
                entry.value != value -> Rows.setValue(db, table, key, value)
            }
        }
    }
}
