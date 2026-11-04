package io.github.danielhp95.caracole.viewer.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** OpenCC, hanzi and the pages' pinyin (vectors/viewer/opencc*, hanzi*, pinyin_page*) (lane chinese). Replays nothing until its lane fills it. */
object ChineseReplay : AreaReplay {
    override val area = "chinese"

    override fun replay(misses: Misses) {}
}
