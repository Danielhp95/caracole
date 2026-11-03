package io.github.danielhp95.caracole.core.pinyin

/** pypinyin 0.55.0, Style.NORMAL (lane pinyin). */
object Pinyin {
    enum class Errors { DEFAULT, IGNORE }

    fun lazyPinyin(text: String, errors: Errors = Errors.DEFAULT): List<String> = TODO("lane pinyin")

    /** pinyin(c, style=NORMAL, heteronym=True)[0]. */
    fun heteronyms(cp: Int): List<String> = TODO("lane pinyin")
}
