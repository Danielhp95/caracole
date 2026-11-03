package io.github.danielhp95.caracole.server.page

import io.github.danielhp95.caracole.core.stub

/** library_assets/, from the classpath copy caracole/library_assets/ (the build's copyLibraryAssets), in the order of
 * caracole/page/library_assets.json (lane library-page). */
class LibraryAssets private constructor() {
    companion object {
        fun load(): LibraryAssets = stub("lane library-page") { LibraryAssets() }
    }

    val scripts: String get() = TODO("lane library-page")
    val styles: String get() = TODO("lane library-page")
    val scriptHash: String get() = TODO("lane library-page")
    val styleHash: String get() = TODO("lane library-page")
    fun template(name: String): String = TODO("lane library-page")
}
