package io.github.danielhp95.caracole.core.keys

/** normalize.py on the phone: identity keys, folds and name forms (lane keys). */
object Normalize {
    /** normalize.KEY_VERSION: a bump re-keys the phone's songs too (LibraryStore.ensureCurrentKeys). */
    const val KEY_VERSION = 2

    fun fold(s: String): String = TODO("lane keys")
    fun nameWords(s: String): List<String> = TODO("lane keys")
    fun holdsRun(words: List<String>, run: String): Boolean = TODO("lane keys")
    fun cleanTitle(t: String): String = TODO("lane keys")
    fun titleVariant(t: String): String? = TODO("lane keys")
    fun canonicalVariant(v: String): String = TODO("lane keys")
    fun slugKey(s: String): String = TODO("lane keys")
    fun ugSlugKey(slug: String): String = TODO("lane keys")
    fun compact(key: String): String = TODO("lane keys")
    fun splitVariant(key: String): Pair<String, String?> = TODO("lane keys")
    fun identityKey(artist: String, title: String): String = TODO("lane keys")
    fun simplified(s: String): String = TODO("lane keys")
    fun hasHan(s: String): Boolean = TODO("lane keys")
    fun hasOtherScript(s: String): Boolean = TODO("lane keys")
    fun romanize(s: String): String = TODO("lane keys")
    fun withoutFeaturing(s: String): String = TODO("lane keys")
    fun placeholderArtist(name: String): Boolean = TODO("lane keys")
    fun displayKey(artist: String, title: String): String = TODO("lane keys")
    fun nameForms(name: String): List<String> = TODO("lane keys")
    fun listingForms(title: String): List<String> = TODO("lane keys")
    fun originalPart(name: String): String = TODO("lane keys")

    /** lacuerda_index.name_key: identity_key(romanize(name), "")'s artist side. */
    fun lacuerdaNameKey(name: String): String = TODO("lane keys")

    /** lacuerda_index.title_key. */
    fun lacuerdaTitleKey(title: String): String = TODO("lane keys")
}
