package io.github.danielhp95.caracole.core.py

/** difflib, the part caracole uses. */
object PySequence {
    /** difflib.SequenceMatcher(None, a, b, autojunk=False). */
    class SequenceMatcher<T>(val a: List<T>, val b: List<T>) {
        fun ratio(): Double = TODO("lane py-format")
        fun matchingBlocks(): List<Triple<Int, Int, Int>> = TODO("lane py-format")
    }
}
