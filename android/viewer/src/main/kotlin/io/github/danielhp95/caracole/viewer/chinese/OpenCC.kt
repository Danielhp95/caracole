package io.github.danielhp95.caracole.viewer.chinese

/** OpenCC's algorithm, as the dev shell's OpenCC runs t2s, tw2s and s2tw without its tofu-risk dictionaries (lane
 * chinese). */
object OpenCC {
    enum class Config { T2S, TW2S, S2TW }

    fun convert(config: Config, text: String): String = TODO("lane chinese")
}
