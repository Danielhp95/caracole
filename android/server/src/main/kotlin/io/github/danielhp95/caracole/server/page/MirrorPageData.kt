package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.web.DownloadNames
import io.github.danielhp95.caracole.core.db.Db
import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.SongRow
import io.github.danielhp95.caracole.core.library.Songs
import io.github.danielhp95.caracole.mirror.Mirror
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.CodingErrorAction

/**
 * M2–M3's page data: the computer's, as its library page in the mirror carries it, made the phone's.
 *
 * The data is the JSON block of the mirror's `index.html` (the list's start page: library_page._DATA's block), or,
 * with no mirror or no block it can read, an empty library. Its icons, catalogue, fold table, sites and generated time
 * are taken as they are. Its songs' cards are the phone's:
 *
 * - each card is re-identified to the phone's song of its identity key (the card's `identity`, songs.key): its `id`
 *   the phone's, its `status` and `review` the phone's database's (`ignored` where the phone's overrides ignore it);
 * - a card of a song the phone hasn't got keeps the computer's, under a negative id of its own (-1, -2, … in the
 *   cards' order), which the served page makes no request of (`fetchable` false: [LibraryPage.withServer]);
 * - a card of a song the phone removed (a tombstone and no song, Songs.isRemoved) is left out, until a sync settles it;
 * - a song the computer's data has no card of, taken from a file, gets the card of the newest of the mirror's layers
 *   ([Mirror.layers]) that keeps a page of the song and whose library page (the file's start page) holds its
 *   identity, re-identified as the computer's are: its sheet's link is the file's page, which the mirror serves from
 *   that layer ([io.github.danielhp95.caracole.mirror.pageFor]). A file is anyone's to write, so its card is read as
 *   untrusted ([fromFile]): the fields library_page.py writes alone, each of the JSON type it writes it as, every
 *   address in it the library's (relative) or a site's over https, a kept file's the library's, and where its lyrics
 *   link back to the phone's own ([lyricsFrom]); a card that fails any of it is the minimal card below;
 * - any other song only the phone has gets a minimal card: library_page._song's of a song with no key, no file's origin
 *   and no site (vectors/web/library_page.json's `minimal_cards`): its names, status, the folds the page sorts and
 *   filters it by ([CardText]), where its lyrics link back to (`lyricsFrom`: Megalobiz's or AZLyrics' page, which
 *   their fair use asks for, [lyricsFrom]), and its kept files (the phone's `files`), each with the one its line
 *   opens (`primary`) and the name a Guitar Pro file or a score downloads under;
 * - each songbook's set names its songs by the same ids (by each entry's `key`), none for a song left out.
 *
 * Each parsed block (the mirror's, and each layer's) is kept until its page changes (its entry's SHA-256). Reads only:
 * every query is the caller's [Db], inside Database.read.
 */
class MirrorPageData(val mirror: Mirror?) : PageData, SongCards {
    @Volatile private var parsed: Pair<String, JsonObject>? = null

    /** Each layer's library page's cards by identity, by that page's SHA-256. */
    @Volatile private var layersParsed: Map<String, Map<String, JsonObject>> = emptyMap()

    override fun data(db: Db, now: String): JsonObject {
        val base = mirrorData() ?: emptyLibrary(now)
        val cards = (base["songs"] as? JsonArray).orEmpty().filterIsInstance<JsonObject>()
        val phone = Phone.read(db)
        val made = Remade(phone, cards)
        val layers by lazy { layerCards() }
        val songs = made.cards + phone.songs.filter { it.key !in made.identities }.map { song ->
            layerCard(layers, song)?.let { phoneCard(phone, it, song) } ?: minimalCard(db, phone, song)
        }
        return JsonObject(base.mapValues { (name, value) ->
            when (name) {
                "songs" -> JsonArray(songs)
                "songbooks" -> songbooks(value, made)
                else -> value
            }
        })
    }

    override fun cards(db: Db, songs: List<SongRow>): Map<Long, JsonObject> {
        val cards = (mirrorData()?.get("songs") as? JsonArray).orEmpty().filterIsInstance<JsonObject>()
        val byIdentity = cards.associateBy { identityOf(it) }
        val phone = Phone(songs, emptySet(), ignoredKeys(db))
        val layers by lazy { layerCards() }
        return songs.associate { song ->
            val card = byIdentity[song.key] ?: layerCard(layers, song)
            song.id to (card?.let { phoneCard(phone, it, song) } ?: minimalCard(db, phone, song))
        }
    }

    /** What the phone's database says of its songs, read once for a page: its songs (newest first), the keys it holds
     * a tombstone of and no song (Songs.isRemoved's), and those its overrides ignore. */
    private class Phone(val songs: List<SongRow>, val removed: Set<String>, val ignored: Set<String>) {
        val byKey = songs.associateBy { it.key }

        companion object {
            fun read(db: Db): Phone {
                val songs = Songs.list(db)
                val keys = songs.mapTo(HashSet()) { it.key }
                return Phone(songs, Songs.removed(db).map { it.key }.filterTo(HashSet()) { it !in keys }, ignoredKeys(db))
            }
        }
    }

    /** The mirror's cards made the phone's, in their order, and which identities they are of. */
    private inner class Remade(phone: Phone, mirrored: List<JsonObject>) {
        val cards = ArrayList<JsonObject>()
        val identities = HashSet<String>()

        /** Each identity's id on the page: the phone's song's, or the card's negative one. */
        val ids = HashMap<String, Long>()

        init {
            var unknown = 0L
            for (card in mirrored) {
                val identity = identityOf(card)
                if (identity != null && identity in phone.removed) continue
                val song = identity?.let { phone.byKey[it] }
                val remade = if (song != null) phoneCard(phone, card, song) else withId(card, --unknown)
                if (identity != null) {
                    identities.add(identity)
                    ids.putIfAbsent(identity, song?.id ?: unknown)
                }
                cards.add(remade)
            }
        }
    }

    /** The computer's [card] of a song the phone has: its id, status and review the phone's. */
    private fun phoneCard(phone: Phone, card: JsonObject, song: SongRow): JsonObject {
        val ignored = song.key in phone.ignored
        return JsonObject(LinkedHashMap(card).apply {
            put("id", JsonPrimitive(song.id))
            put("status", JsonPrimitive(if (ignored) "ignored" else song.status))
            put("review", JsonPrimitive(song.review && !ignored))
        })
    }

    private fun withId(card: JsonObject, id: Long) = JsonObject(LinkedHashMap(card).apply { put("id", JsonPrimitive(id)) })

    /** The card of a song only the phone has: library_page._song's fields the phone knows, as it writes them of a
     * song with no key, no file's origin and no site, its files its `files` rows (vectors/web/library_page.json's
     * `minimal_cards`). */
    private fun minimalCard(db: Db, phone: Phone, song: SongRow): JsonObject {
        val ignored = song.key in phone.ignored
        val title = Normalize.cleanTitle(song.title)
        val sortArtist = CardText.sortKey(song.artist)
        val sortTitle = CardText.sortKey(title)
        val artists = song.artists.ifEmpty { listOf(song.artist) }
        val kept = db.query("SELECT name, path FROM files WHERE song_id = ?", song.id) { it.text(0)!! to it.text(1)!! }.toMap()
        val ordered = CardText.inLineOrder(kept.keys)
        val primary = CardText.primary(ordered)
        val files = ordered.map { name ->
            JsonObject(buildMap {
                put("name", JsonPrimitive(name))
                put("label", JsonPrimitive(CardText.label(name)))
                put("href", JsonPrimitive(CardText.href(kept.getValue(name))))
                put("primary", JsonPrimitive(name == primary))
                put("source", JsonPrimitive(CardText.sourceOf(name)))
                if (CardText.downloads(name)) put("download", JsonPrimitive(DownloadNames.downloadName(song.artist, title, name)))
            })
        }
        val initials = CardText.initials(title)
        return JsonObject(buildMap {
            put("id", JsonPrimitive(song.id))
            put("artist", JsonPrimitive(song.artist))
            put("artists", JsonArray(artists.map { JsonPrimitive(it) }))
            put("title", JsonPrimitive(title))
            put("display", JsonPrimitive(song.display))
            put("status", JsonPrimitive(if (ignored) "ignored" else song.status))
            put("review", JsonPrimitive(song.review && !ignored))
            put("added", JsonPrimitive(song.addedAt))
            put("key", JsonNull)
            put("lyricsFrom", lyricsFrom(song))
            put("files", JsonArray(files))
            put("source", JsonPrimitive(primary?.let { CardText.sourceOf(it) }))
            put("identity", JsonPrimitive(song.key))
            put("sortArtist", JsonPrimitive(sortArtist))
            put("sortTitle", JsonPrimitive(sortTitle))
            put("artistLetter", JsonPrimitive(CardText.letter(sortArtist)))
            put("titleLetter", JsonPrimitive(CardText.letter(sortTitle)))
            put("search", JsonPrimitive(CardText.haystack(listOf(song.artist) + song.artists + listOf(title, song.display))))
            if (initials.isNotEmpty()) put("initials", JsonPrimitive(initials))
            put("sites", JsonArray(emptyList()))
        })
    }

    /**
     * library.lyrics_from: where a song's lyrics link back to, `{source, href}`, for a site of [LYRICS_PAGES] and a page
     * on it alone (its card's Lyrics tile links it); null for any other, or lyrics that can't be read. Read from the
     * stored JSON alone, as json.loads reads it.
     */
    private fun lyricsFrom(song: SongRow): JsonElement {
        val stored = song.lyricsJson?.let { runCatching { PyJson.loads(it) }.getOrNull() } as? JsonObject ?: return JsonNull
        if (song.lyricsStatus != "found") return JsonNull
        val provider = (stored["provider"] as? JsonPrimitive)?.takeIf { it.isString }?.content
        val url = (stored["url"] as? JsonPrimitive)?.takeIf { it.isString }?.content
        val site = provider?.let { LYRICS_PAGES[it] }
        if (site == null || url == null || !url.startsWith(site)) return JsonNull
        return JsonObject(linkedMapOf("source" to JsonPrimitive(provider), "href" to JsonPrimitive(url)))
    }

    /** The Songbooks tab's data with each set's songs named by the page's ids (none for a song left out). */
    private fun songbooks(value: JsonElement, made: Remade): JsonElement {
        val tab = value as? JsonObject ?: return value
        val books = tab["books"] as? JsonArray ?: return value
        return JsonObject(tab.mapValues { (name, v) ->
            if (name != "books") return@mapValues v
            JsonArray(books.map { book ->
                val set = (book as? JsonObject)?.get("set") as? JsonArray ?: return@map book
                JsonObject(book.mapValues { (field, w) ->
                    if (field != "set") return@mapValues w
                    JsonArray(set.map { entry ->
                        if (entry !is JsonObject) return@map entry
                        val id = (entry["key"] as? JsonPrimitive)?.contentOrNull?.let { made.ids[it] }
                        JsonObject(LinkedHashMap(entry).apply { put("id", id?.let { JsonPrimitive(it) } ?: JsonNull) })
                    })
                })
            })
        })
    }

    private fun identityOf(card: JsonObject): String? = (card["identity"] as? JsonPrimitive)?.takeIf { it.isString }?.content

    /** The data block of the mirror's library page, parsed, or null without one it can read. */
    private fun mirrorData(): JsonObject? {
        val mirror = mirror ?: return null
        val manifest = mirror.manifest() ?: return null
        val served = mirror.lookup(manifest.start) ?: return null
        parsed?.let { (sha, data) -> if (sha == served.entry.sha256) return data }
        val data = try {
            dataBlock(served.file.readBytes())
        } catch (e: java.io.IOException) {
            null
        } ?: return null
        parsed = served.entry.sha256 to data
        return data
    }

    /** A layer's cards by identity, and the units it keeps a page of. */
    private class LayerCards(val cards: Map<String, JsonObject>, val units: Set<String>)

    /** The card of [song] from the newest layer that keeps a page of it and whose library page holds its identity,
     * as [fromFile] reads it; null for none, or one that isn't a card the phone shows. */
    private fun layerCard(layers: List<LayerCards>, song: SongRow): JsonObject? =
        layers.firstOrNull { SONG_UNIT + song.key in it.units && song.key in it.cards }
            ?.let { fromFile(it.cards.getValue(song.key), song) }

    /** The cards of each of the mirror's layers' library pages by identity, the newest layer first, with the units
     * each keeps a page of; no card for a layer whose page can't be read. */
    private fun layerCards(): List<LayerCards> {
        val mirror = mirror ?: return emptyList()
        val known = layersParsed
        val read = LinkedHashMap<String, Map<String, JsonObject>>()
        val layers = ArrayList<LayerCards>()
        for (layer in mirror.layers()) {
            val manifest = layer.manifest() ?: continue
            val served = layer.lookup(manifest.start) ?: continue
            val sha = served.entry.sha256
            val cards = read[sha] ?: known[sha] ?: run {
                val data = try {
                    dataBlock(served.file.readBytes())
                } catch (e: java.io.IOException) {
                    null
                }
                val cards = (data?.get("songs") as? JsonArray).orEmpty().filterIsInstance<JsonObject>()
                LinkedHashMap<String, JsonObject>().apply { for (card in cards) identityOf(card)?.let { putIfAbsent(it, card) } }
            }
            read[sha] = cards
            layers.add(LayerCards(cards, manifest.entries.mapNotNullTo(HashSet()) { it.unit }))
        }
        layersParsed = read
        return layers
    }

    /**
     * A file's [card] of [song], read as untrusted (anyone can write a file's library page): the fields
     * library_page._song and the page's build write ([CARD]), each of the JSON type they write it as, any other left
     * out; its identity the song's; every `href` in it an address of the library (relative: no scheme, no host, no
     * backslash) or of a site over https, a kept file's ([FILES]: its name and label text) of the library alone; where
     * its lyrics link back to, where it says, the phone's own ([lyricsFrom] of the song, which the file gave it). Null
     * for a card
     * that fails any of it, which the minimal card replaces, so that no file's card can break the library page.
     */
    private fun fromFile(card: JsonObject, song: SongRow): JsonObject? {
        if (identityOf(card) != song.key) return null
        val kept = LinkedHashMap<String, JsonElement>()
        for ((name, value) in card) {
            val fits = CARD[name] ?: continue
            if (!fits(value)) return null
            kept[name] = value
        }
        if (REQUIRED.any { it !in kept } || !addressesFit(JsonObject(kept))) return null
        for (file in (kept["files"] as JsonArray)) {
            val f = file as JsonObject
            if (FILES.any { (name, fits) -> name in f && !fits(f.getValue(name)) } ||
                f["name"] !is JsonPrimitive || !library((f["href"] as? JsonPrimitive)?.content)) return null
        }
        if ("lyricsFrom" in kept) kept["lyricsFrom"] = lyricsFrom(song)
        return JsonObject(kept)
    }

    /** A library with no song, for a phone with no mirror: the page's data as library_page.py's build makes it of a
     * library with no song ([EMPTY]: its fold table, its sources' names and badges with no icon kept, the named
     * progressions, the Songbooks tab's menus with no songbook), in its order, and no site's (the Sites tab's data
     * is the computer's, which the phone has none of yet). */
    private fun emptyLibrary(now: String): JsonObject = JsonObject(linkedMapOf(
        "generated" to JsonPrimitive(now),
        "fold" to empty.getValue("fold"),
        "songs" to JsonArray(emptyList()),
        "icons" to empty.getValue("icons"),
        "catalogue" to empty.getValue("catalogue"),
        "songbooks" to empty.getValue("songbooks"),
        "sites" to JsonArray(emptyList()),
    ))

    companion object {
        /** library.LYRICS_PAGES: the lyrics sites whose fair use asks a link back, by provider, and where their pages
         * are. */
        val LYRICS_PAGES = mapOf("megalobiz" to "https://megalobiz.com/", "azlyrics" to "https://www.azlyrics.com/")

        /** library_page._TRANSLITERATED: the letters fold transliterates, which the page folds typed queries with. */
        const val TRANSLITERATED = "øØæÆœŒßẞđĐłŁþÞðÐıħĦ"

        /** What a library with no song holds that is no song's, on the classpath (:core's runtime data, written by
         * tests/test_conformance_library_page.py). */
        const val EMPTY = "caracole/page/empty_library.json"

        private val empty: JsonObject by lazy {
            val stream = MirrorPageData::class.java.classLoader?.getResourceAsStream(EMPTY)
                ?: throw IllegalStateException("$EMPTY isn't on the classpath")
            Json.parseToJsonElement(stream.use { it.readBytes().toString(Charsets.UTF_8) }) as JsonObject
        }

        /** The songs the phone's overrides ignore (`[ignore]`), by key: a row of phone_overrides' table "ignore", as
         * OverridesStore.songEntries reads one (`ignore: true`; putSongEntries writes no other value, and deletes
         * the row of a song no longer ignored). One query for the page, not one a song. */
        private fun ignoredKeys(db: Db): Set<String> =
            db.query("SELECT key FROM phone_overrides WHERE tbl = 'ignore'") { it.text(0)!! }.toSet()

        private const val SONG_UNIT = "song/"

        private fun isText(e: JsonElement) = e is JsonPrimitive && e.isString
        private fun isTextOrNull(e: JsonElement) = e is JsonNull || isText(e)
        private fun isBool(e: JsonElement) = e is JsonPrimitive && !e.isString && (e.content == "true" || e.content == "false")
        private fun isInt(e: JsonElement) = e is JsonPrimitive && !e.isString && INT.matches(e.content)
        private fun isTexts(e: JsonElement) = e is JsonArray && e.all(::isText)
        private fun isObjects(e: JsonElement) = e is JsonArray && e.all { it is JsonObject }
        private fun isObjectOrNull(e: JsonElement) = e is JsonNull || e is JsonObject
        private val INT = Regex("-?[0-9]{1,15}")

        /** The fields a card of library_page.py's holds (`_song`'s, and what its build adds: `progressions`, `hanzi`,
         * `candidates`, `notFound`, `sites`), each with the JSON type it writes it as. */
        private val CARD: Map<String, (JsonElement) -> Boolean> = mapOf(
            "id" to ::isInt, "artist" to ::isText, "artists" to ::isTexts, "title" to ::isText,
            "display" to ::isTextOrNull, "status" to ::isText, "review" to ::isBool, "added" to ::isTextOrNull,
            "key" to ::isTextOrNull, "key_source" to ::isTextOrNull, "transpose" to ::isInt, "lyrics" to ::isTextOrNull,
            "lyricsFrom" to ::isObjectOrNull, "auto" to ::isBool, "files" to ::isObjects, "instruments" to ::isTexts,
            "versions" to ::isObjectOrNull, "autoSheet" to ::isObjectOrNull, "source" to ::isTextOrNull,
            "museScore" to ::isObjects, "links" to ::isObjects, "buy" to ::isObjects, "youtube" to ::isObjectOrNull,
            "youtubeSheet" to ::isBool, "lacuerda" to ::isObjectOrNull, "lacuerdaVersions" to ::isObjects,
            "lacuerdaSheet" to ::isObjectOrNull, "identity" to ::isText, "sortArtist" to ::isText,
            "sortTitle" to ::isText, "artistLetter" to ::isText, "titleLetter" to ::isText, "search" to ::isText,
            "initials" to ::isText, "progressions" to ::isObjects, "hanzi" to { it is JsonObject },
            "candidates" to ::isObjects, "notFound" to ::isBool, "sites" to ::isObjects,
        )

        /** What a card is of, at least: its song's names, its identity and its files. */
        private val REQUIRED = listOf("artist", "title", "files", "identity")

        /** A kept file's fields, of library_page._files, each with its type. */
        private val FILES: Map<String, (JsonElement) -> Boolean> = mapOf(
            "name" to ::isText, "label" to ::isText, "href" to ::isText, "primary" to ::isBool,
            "source" to ::isTextOrNull, "download" to ::isText,
        )

        private val SCHEME = Regex("[A-Za-z][A-Za-z0-9+.-]*:.*", RegexOption.DOT_MATCHES_ALL)

        /** An address of the library: relative, with no scheme, no host and no backslash. */
        private fun library(href: String?): Boolean =
            href != null && href.isNotEmpty() && !SCHEME.matches(href) && !href.startsWith("/") && '\\' !in href &&
                href.none { it < ' ' || it == '\u007f' }

        /** Whether every `href` in [e], however deep, is none (empty), the library's ([library]) or a site's over
         * https. */
        private fun addressesFit(e: JsonElement): Boolean = when (e) {
            is JsonObject -> e.all { (name, value) ->
                if (name == "href" && value !is JsonNull) {
                    val href = (value as? JsonPrimitive)?.takeIf { it.isString }?.content
                    href != null && (href.isEmpty() || library(href) ||
                        (href.startsWith("https://") && href.none { it <= ' ' || it == '\\' || it == '\u007f' }))
                } else addressesFit(value)
            }
            is JsonArray -> e.all(::addressesFit)
            else -> true
        }

        private const val OPEN = "<script type=\"application/json\" id=\"songs\">"
        private const val CLOSE = "</script>"

        /** library_page._DATA's block of [page], read: the text between its opening tag and the first `</script>`
         * after it (the block writes every `<` escaped), as JSON; null when there is none, the page isn't UTF-8, or
         * the block isn't a JSON object. */
        fun dataBlock(page: ByteArray): JsonObject? {
            val text = try {
                Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(page)).toString()
            } catch (e: CharacterCodingException) {
                return null
            }
            val start = text.indexOf(OPEN).takeIf { it >= 0 }?.plus(OPEN.length) ?: return null
            val end = text.indexOf(CLOSE, start).takeIf { it >= 0 } ?: return null
            return try {
                Json.parseToJsonElement(text.substring(start, end)) as? JsonObject
            } catch (e: IllegalArgumentException) {
                null
            }
        }
    }
}
