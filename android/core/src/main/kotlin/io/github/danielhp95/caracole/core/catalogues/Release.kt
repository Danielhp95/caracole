package io.github.danielhp95.caracole.core.catalogues

import io.github.danielhp95.caracole.core.json.PyJson
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.mirror.Http
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import java.net.URI
import java.time.ZoneOffset

/**
 * A file the release holds: its [name], its `.gz` size ([bytes]), the SHA-256 GitHub gives of it ([sha256], hex, ""
 * for none), whether it is whole ([uploaded]: GitHub's `state` is `uploaded` and it gave a digest; a file a failed
 * run left half uploaded is not), and the address its bytes are asked at ([url], which [download] follows).
 */
data class Listed(val name: String, val bytes: Long, val sha256: String, val uploaded: Boolean, val url: String)

/**
 * Where the phone lists the release: [Api], GitHub's REST API's release by its tag (the owner's choice, for
 * good). It asks GitHub alone, every URI it builds from its [base] and checked by `RealTransport.refuseUnderTests`
 * before it is asked, and its files' bytes are followed only to one of its [redirects], once.
 */
sealed interface CatalogueSource {
    val base: URI

    /** The hosts this source's answers may redirect to: [download]'s `hosts` for its files. */
    val redirects: Set<String>

    /** The release's files; [NoRelease], [Limited] or another [CatalogueError] when it can't be read. */
    fun list(): List<Listed>

    /**
     * `GET /repos/{REPO}/releases/tags/{tag}` (the catalogues' [Catalogues.TAG], the chord models' `models`;
     * `Accept: application/vnd.github+json`, no redirect followed): its `assets`, each its API `url` (under [base]
     * alone; asked with `Accept: application/octet-stream` for its bytes), `uploaded` only for `state: uploaded` with
     * a `digest` (`sha256:` stripped). 404 is [NoRelease]; a 403 or 429 with `x-ratelimit-remaining: 0` [Limited].
     */
    class Api(private val http: Http, override val base: URI = URI("https://api.github.com"),
              override val redirects: Set<String> = Catalogues.API_REDIRECTS,
              private val tag: String = Catalogues.TAG) : CatalogueSource {
        override fun list(): List<Listed> {
            val uri = URI(root(base) + "/repos/${Catalogues.REPO}/releases/tags/$tag")
            val doc = ask(http, uri, "application/vnd.github+json", emptySet()) { answer ->
                if (answer.status == 404) throw NoRelease()
                if (answer.status != 200) throw refusal(answer)
                readJson(answer)
            }
            val assets = (doc as? JsonObject)?.get("assets") as? JsonArray ?: throw unreadable()
            return assets.map { item ->
                val asset = item as? JsonObject ?: throw unreadable()
                val name = text(asset["name"]) ?: throw unreadable()
                // Its bytes are asked of this source's own host alone, at the address GitHub's API gives an asset.
                val url = text(asset["url"])?.takeIf { isAssetUrl(it) } ?: throw unreadable()
                val size = number(asset["size"]) ?: throw unreadable()
                val digest = text(asset["digest"])?.takeIf { it.startsWith("sha256:") }?.removePrefix("sha256:")
                Listed(name, size, digest ?: "", text(asset["state"]) == "uploaded" && !digest.isNullOrEmpty(), url)
            }
        }

        /** GitHub's address of one of [Catalogues.REPO]'s assets, on [base]: the owner's name in any ASCII case, as
         * GitHub writes its canonical login. */
        private fun isAssetUrl(url: String): Boolean {
            val prefix = Py.asciiLower(root(base) + "/repos/${Catalogues.REPO}/releases/assets/")
            if (!Py.asciiLower(url).startsWith(prefix)) return false
            val id = url.substring(prefix.length)
            return id.isNotEmpty() && id.all { it in '0'..'9' }
        }
    }
}

/** What to do with the release: [Take] its file, or nothing, and why. */
sealed interface Choice {
    /** This schema's newest file, not yet imported. */
    data class Take(val file: Listed, val named: Named) : Choice

    /** This schema's newest file is the one imported last. */
    data class UpToDate(val name: String) : Choice

    /** No file of this schema; one of a newer schema, [schema] the newest. */
    data class Newer(val schema: Int) : Choice

    /** No file of this schema nor a newer one; [schema] the newest of the older ones. */
    data class Older(val schema: Int) : Choice

    /** No catalogue file at all. */
    data object None : Choice
}

/**
 * Of [listed]'s `uploaded` files whose name [Names] reads, [schema]'s newest by its name's stamp (never the list's
 * order nor GitHub's times): [Choice.UpToDate] when it is [imported] (kv [Catalogues.IMPORTED]), else
 * [Choice.Take]. With none of this schema: [Choice.Newer] when any is newer (update the app wins over "on their
 * way"), else [Choice.Older], else [Choice.None].
 */
fun choose(listed: List<Listed>, schema: Int, imported: String?): Choice {
    val named = listed.filter { it.uploaded }.mapNotNull { file -> Names.read(file.name)?.let { file to it } }
    val mine = named.filter { it.second.schema == schema }.maxByOrNull { it.second.at }
    if (mine != null) return if (mine.first.name == imported) Choice.UpToDate(mine.first.name) else Choice.Take(mine.first, mine.second)
    named.map { it.second.schema }.filter { it > schema }.maxOrNull()?.let { return Choice.Newer(it) }
    named.map { it.second.schema }.maxOrNull()?.let { return Choice.Older(it) }
    return Choice.None
}

/** What the app says of [choice] (the spec's sentences, each one sentence, so that a line that keeps only a failure's
 * first sentence keeps what to do too); null for [Choice.Take] and [Choice.UpToDate], which the job words itself. */
fun words(choice: Choice): String? = when (choice) {
    is Choice.Take, is Choice.UpToDate -> null
    is Choice.Newer -> "The published catalogues are for a newer caracole (schema ${choice.schema}): update the app."
    is Choice.Older ->
        "The published catalogues are for an older caracole (schema ${choice.schema}): new ones are on their way."
    Choice.None -> NoRelease().message
}

private val MONTHS = listOf("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

/** [named]'s day in UTC as "24 Nov 2026" (`d MMM yyyy`, English months from a table, never a locale's). */
fun date(named: Named): String {
    val day = named.at.atOffset(ZoneOffset.UTC).toLocalDate()
    return "${day.dayOfMonth} ${MONTHS[day.monthValue - 1]} ${day.year}"
}

// --- reading GitHub's JSON ------------------------------------------------------------------------------------------

/** The most an answer of JSON is read: a release lists a few files. */
private const val MAX_JSON = 4 * 1024 * 1024

/** [base] as the start of an address, with no slash at its end. */
private fun root(base: URI): String = base.toString().removeSuffix("/")

private fun unreadable() = CatalogueError("GitHub answered with something the phone can't read.")

private fun readJson(answer: Http.Answer): JsonElement {
    val bytes = answer.body.readNBytes(MAX_JSON + 1)
    if (bytes.size > MAX_JSON) throw unreadable()
    return try {
        PyJson.loads(bytes)
    } catch (e: IllegalArgumentException) {
        throw unreadable()
    }
}

private fun text(value: JsonElement?): String? =
    (value as? JsonPrimitive)?.takeIf { it.isString && value !is JsonNull }?.contentOrNull

private fun number(value: JsonElement?): Long? =
    (value as? JsonPrimitive)?.takeIf { !it.isString && value !is JsonNull }?.contentOrNull?.toLongOrNull()
