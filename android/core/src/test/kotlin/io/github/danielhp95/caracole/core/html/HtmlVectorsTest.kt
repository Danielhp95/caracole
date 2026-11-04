package io.github.danielhp95.caracole.core.html

import io.github.danielhp95.caracole.core.testing.Misses
import io.github.danielhp95.caracole.core.testing.replays.HtmlReplay
import org.junit.Test

/** core.html against lexbor, every record of vectors/html/ (HtmlReplay: the tokens through the replay's small tree and
 * through core.html's, then the trees, the selectors and the mutations), as CorpusOnDeviceTest runs it on the device. */
class HtmlVectorsTest {
    @Test fun everyTokenTreeSelectorAndMutationIsLexbors() {
        HtmlReplay.replay(Misses("html"))
    }
}
