package io.github.danielhp95.caracole.core.py

/** Python's codecs, the ones caracole reads pages with. */
object PyCodec {
    /** bytes.decode("utf-8", "replace"): each ill-formed sequence one U+FFFD, as CPython's decoder cuts them. */
    fun utf8Replace(b: ByteArray): String = PyText.utf8(b, replace = true)!!
}
