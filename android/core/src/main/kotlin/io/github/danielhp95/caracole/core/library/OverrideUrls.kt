package io.github.danielhp95.caracole.core.library

/** overrides.py's and ug/sitemap.py's readings of an address a user pasted. */
object OverrideUrls {
    fun overrideKey(display: String): String = TODO("lane overrides-model")
    fun tabIdFromUrl(s: String): Long = TODO("lane overrides-model")
    fun pinUrl(s: String): String = TODO("lane overrides-model")
    fun artistPageAddress(url: String): String? = TODO("lane overrides-model")
    fun pastedTabId(url: String): Long? = TODO("lane overrides-model")

    /** ug/sitemap.classify_tab_url. */
    fun classifyTabUrl(url: String): String? = TODO("lane overrides-model")
    fun lacuerdaPickFromUrl(s: String): LaCuerdaPick = TODO("lane overrides-model")
    fun harptabsPickFromUrl(s: String): HarpTabsPick = TODO("lane overrides-model")
    fun gametabsPickFromUrl(s: String): GameTabsPick = TODO("lane overrides-model")
}
