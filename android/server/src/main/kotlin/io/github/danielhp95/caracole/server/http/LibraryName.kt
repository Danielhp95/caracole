package io.github.danielhp95.caracole.server.http

import io.github.danielhp95.caracole.core.py.PyText

/**
 * library_name.py's LibraryName: what a page says of the library it shows, [name], after caracole's, and [badge]
 * beside it for one that isn't the usual library (vectors/web/library_name.jsonl).
 *
 * Every page the phone writes itself carries the badge "Phone" ([phone]): the library's name is the computer's, as a
 * sync gave it (kv `phone:settings`' `name`, PhoneConfig.libraryName), and none before the first, when the header
 * says caracole and the badge alone, and the title "Phone · caracole".
 */
data class LibraryName(val name: String, val badge: String? = null) {
    /** A browser tab's title: "caracole · Tabs", the page's own before it ("Look up · caracole · Tabs"), and the
     * badge first ("Phone · caracole · Tabs"), each part there only when it isn't empty. */
    fun title(page: String = ""): String =
        listOf(badge.orEmpty(), page, "caracole", name).filter { it.isNotEmpty() }.joinToString(" · ")

    /** The name, and the badge after it, for a page's header (base.css's `.libname`), escaped. */
    fun markup(tag: String = "span"): String {
        val shown = if (!badge.isNullOrEmpty()) {
            " <span class=\"scratch\" title=\"$BADGE_TITLE\">${PyText.escape(badge)}</span>"
        } else {
            ""
        }
        return "<$tag class=\"libname\"><span class=\"name\">${PyText.escape(name)}</span>$shown</$tag>"
    }

    /** The page's icon, for its head: caracole's, or with a badge the same "¿" in the badge's colour. */
    fun icon(): String = if (!badge.isNullOrEmpty()) PageIcon.scratchLink else PageIcon.link

    companion object {
        /** library_name.BADGE_TITLE: the badge's tooltip. */
        const val BADGE_TITLE = "Not your usual library"

        /** The badge every page the phone writes itself shows beside the library's name. */
        const val PHONE_BADGE = "Phone"

        /** The library as the phone's pages name it: the computer's [name] (none before a sync gave one), with the
         * phone's badge. */
        fun phone(name: String?): LibraryName = LibraryName(name.orEmpty(), PHONE_BADGE)
    }
}
