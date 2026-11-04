package io.github.danielhp95.caracole.core.ug

import kotlinx.serialization.json.JsonObject

/** ug/page.py's UGVersion: one version a tab page or an artist page lists. */
data class UgVersion(val tabId: Long, val songId: Long?, val songName: String, val artistName: String,
                     val type: String, val part: String, val version: Int, val rating: Double, val votes: Int,
                     val access: String, val url: String, val description: String?, val isAcoustic: Boolean,
                     val raw: JsonObject)

/** ug/page.py's UGTabPage: a tab page read. */
data class UgTabPage(val tab: UgVersion, val versions: List<UgVersion>, val content: String?, val meta: JsonObject,
                     val raw: JsonObject, val artistUrl: String? = null)

/** ug/page.py: UG's tab pages. */
object UgPage {
    /** KINDS: the types caracole uses, by UG's type: chords, tabs, ukulele. */
    fun kindOf(type: String?): String? = TODO("lane ug-pages")
    fun pageUrl(tabId: Long, path: String? = null): String = TODO("lane ug-pages")
    fun stripMarkup(s: String): String = TODO("lane ug-pages")
    fun decodeTwice(s: String): String = TODO("lane ug-pages")
    fun parseTabPage(html: ByteArray, url: String? = null): UgTabPage = TODO("lane ug-pages")
}
