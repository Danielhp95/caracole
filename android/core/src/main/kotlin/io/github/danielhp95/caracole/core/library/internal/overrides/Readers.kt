package io.github.danielhp95.caracole.core.library.internal.overrides

import io.github.danielhp95.caracole.core.keys.Normalize
import io.github.danielhp95.caracole.core.library.OverridesError
import io.github.danielhp95.caracole.core.py.Py
import io.github.danielhp95.caracole.core.py.PyRe
import io.github.danielhp95.caracole.core.py.PyRegex
import io.github.danielhp95.caracole.core.py.PyText
import io.github.danielhp95.caracole.core.py.PyUrl
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * overrides.py's readers of one entry's value, each refusing what it refuses with its words, [where] naming the
 * table and the entry (`[match] 'Radiohead - Creep'`): what `Overrides.read` reads each row by, and the writers check
 * what they write by, so that what the phone writes, the computer reads back as it is.
 */
internal object Readers {
    /** overrides.VERSION_SHAPE and VERSION_MAX. */
    const val VERSION_SHAPE = "t=2&mode=dorian&capo=0"
    const val VERSION_MAX = 2000
    const val NO_VIDEO = "none"
    const val VIDEO_SHAPE = "https://www.youtube.com/watch?v=…"
    private val HARMONICA_TAB by lazy { PyRegex.compile("harmonica-[1-9][0-9]{0,3}\\.txt") }

    /** A harmonica tab's name, as inbox.py keeps it (`harmonica-1.txt`). */
    fun isHarmonicaTab(tab: String): Boolean = PyRe.fullmatch(HARMONICA_TAB, tab) != null

    /** overrides._ug_ref: the (artist key, song key) of `"ug-artist/ug-song"`. */
    fun ugRef(value: JsonElement, where: String): Pair<String, String> {
        val text = PyValues.text(value)
        if (text == null || text.count { it == '/' } != 1) {
            throw OverridesError("$where: expected \"ug-artist/ug-song\", got ${PyValues.repr(value)}")
        }
        val a = Normalize.ugSlugKey(text.substringBefore('/'))
        val s = Normalize.ugSlugKey(text.substringAfter('/'))
        if (a.isEmpty() || s.isEmpty()) {
            throw OverridesError("$where: expected \"ug-artist/ug-song\", got ${PyValues.repr(value)}")
        }
        return a to s
    }

    /** overrides._video: the id of the video at a YouTube address, or null for "none". */
    fun video(value: JsonElement, where: String): String? {
        val text = PyValues.text(value)
        if (text != null && PyText.lower(PyText.strip(text)) == NO_VIDEO) return null
        return Addresses.videoIdFromUrl(value) ?: throw OverridesError(
            "$where: expected a YouTube video's address ($VIDEO_SHAPE) or \"$NO_VIDEO\", got ${PyValues.repr(value)}",
        )
    }

    /** parse_qsl(text, errors="strict")'s values: each field with a value, its name and value unquoted strictly
     * (`+` a space); null where one escapes bytes that aren't UTF-8. */
    private fun strictValues(text: String): List<String>? {
        val values = ArrayList<String>()
        for (field in text.split('&')) {
            if (field.isEmpty()) continue
            val value = field.substringAfter('=', "")
            if (value.isEmpty()) continue
            try {
                PyUrl.unquote(field.substringBefore('=').replace('+', ' '), strict = true)
                values += PyUrl.unquote(value.replace('+', ' '), strict = true)
            } catch (e: PyUrl.Invalid) {
                return null
            }
        }
        return values
    }

    private fun control(s: String): Boolean = s.any { it.code < 32 || it.code == 127 }

    /**
     * overrides._version: a `[version]` value, stripped, a "#" or a "?" before it dropped: text of at most
     * [VERSION_MAX] characters with no control character, nor one escaped. One that names a `key` is checked by
     * [keyVersion] (viewer/version.py's `key_version`, which raises IllegalArgumentException with its words) when one
     * is given.
     */
    fun version(value: JsonElement, where: String, keyVersion: ((String) -> Any?)?): String {
        var text = PyValues.text(value)?.let(PyText::strip)
        if (text != null && (text.startsWith("#") || text.startsWith("?"))) text = text.substring(1)
        val readable = text != null && Py.len(text) <= VERSION_MAX && !control(text) &&
            strictValues(text)?.none(::control) == true
        if (!readable) {
            throw OverridesError("$where: expected a version as the sheet's viewer writes it in its address " +
                                     "(\"$VERSION_SHAPE\"), got ${PyValues.repr(value)}")
        }
        if (keyVersion != null && text!!.split('&').any { it.substringBefore('=') == "key" }) {
            try {
                keyVersion(text)
            } catch (e: IllegalArgumentException) {
                throw OverridesError("$where: ${e.message}")
            }
        }
        return text!!
    }

    /**
     * overrides._harmonica_reading: a `[harmonica]` tab's reading, its tab's name checked as Python checks it (the
     * last word of [where], its quotes off) and the reading by [checkSpec] (viewer/harptab.py's `check_spec`, which
     * raises IllegalArgumentException with its words) when one is given; a table's members as text.
     */
    fun harmonicaReading(spec: JsonElement, where: String, checkSpec: ((JsonElement) -> Unit)?): JsonElement {
        val tab = where.substringAfterLast(' ').trim('\'', '"')
        if (!isHarmonicaTab(tab)) throw OverridesError("$where: expected a harmonica tab's name, harmonica-N.txt")
        if (checkSpec != null) {
            try {
                checkSpec(spec)
            } catch (e: IllegalArgumentException) {
                throw OverridesError("$where: ${e.message}")
            }
        }
        if (spec !is JsonObject) return spec
        return JsonObject(spec.entries.associate { (k, v) -> k to JsonPrimitive(PyValues.str(v)) })
    }
}
