package io.github.danielhp95.caracole.core.py

/**
 * Fragments for java.util.regex that mean what Python's mean, in \x{…} ranges (lane py-unicode): never the JDK's
 * own \w or \s, whose Unicode differs from Python's (and is ICU's on Android).
 */
object PyRegex {
    /** [...] class bodies. */
    val WORD: String get() = TODO("lane py-unicode")
    val NOT_WORD: String get() = TODO("lane py-unicode")
    val SPACE: String get() = TODO("lane py-unicode")
    val DIGIT: String get() = TODO("lane py-unicode")

    /** [pattern] with \w \W \s \S \d \D \b \B expanded into the classes above; no flags. */
    fun compile(pattern: String): Regex = TODO("lane py-unicode")

    /** A length-preserving map to [PyUnicode.ignoreCaseKey], for IGNORECASE patterns. */
    fun ignoreCase(s: String): String = TODO("lane py-unicode")
}
