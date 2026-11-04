package io.github.danielhp95.caracole.core.testing.replays

import io.github.danielhp95.caracole.core.testing.AreaReplay
import io.github.danielhp95.caracole.core.testing.Misses

/** core.html's tokens and trees (vectors/html/) (lane html-tokenizer). Replays nothing until its lane fills it. */
object HtmlReplay : AreaReplay {
    override val area = "html"

    override fun replay(misses: Misses) {}
}
