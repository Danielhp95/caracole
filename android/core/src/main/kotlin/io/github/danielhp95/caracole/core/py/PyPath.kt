package io.github.danielhp95.caracole.core.py

/** pathlib's PurePosixPath, the little caracole reads of it. */
object PyPath {
    /** PurePosixPath(name).suffix, Python 3.14's: from the last dot of the name, its leading dots left out. */
    fun suffix(name: String): String {
        val last = name.split('/').lastOrNull { it.isNotEmpty() && it != "." } ?: return ""
        val bare = last.trimStart('.')
        val dot = bare.lastIndexOf('.')
        return if (dot >= 0) bare.substring(dot) else ""
    }
}
