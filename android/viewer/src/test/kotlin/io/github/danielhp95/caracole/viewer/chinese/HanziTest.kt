package io.github.danielhp95.caracole.viewer.chinese

import io.github.danielhp95.caracole.viewer.chinese.OpenCC.Config
import io.github.danielhp95.caracole.viewer.testing.replays.ChineseReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** viewer.chinese.Hanzi is viewer/hanzi.py: every record of vectors/viewer/hanzi.jsonl (ChineseReplay), and the rules
 * test_viewer_hanzi.py names. */
class HanziTest {
    @Test fun everyRecordIsHanziPys() = ChineseReplay.everyHanziRecordIsHanziPys()

    private val traditional = listOf("斑馬斑馬 你不要睡著啦", "我只想掀起你的頭髮")
    private val simplified = listOf("斑马斑马 你不要睡着啦", "我只想掀起你的头发")

    @Test fun aTraditionalSheetIsShownInSimplifiedAndInTraditionalAsWritten() {
        val shown = Hanzi.scripts(traditional)
        assertEquals(listOf("simplified", "traditional"), shown.keys.toList())
        assertEquals(traditional.zip(simplified).toMap(), shown.getValue("simplified"))
        assertEquals(emptyMap(), shown.getValue("traditional"))
        assertTrue(Hanzi.writtenInTraditional(traditional))
    }

    @Test fun aSimplifiedSheetIsShownInTraditionalInTaiwansStandard() {
        val shown = Hanzi.scripts(simplified)
        assertEquals(emptyMap(), shown.getValue("simplified"))
        assertEquals(simplified.zip(traditional).toMap(), shown.getValue("traditional"))
        assertFalse(Hanzi.writtenInTraditional(simplified))
    }

    @Test fun theScriptIsTheOneMostOfItsOwnCharactersAre() {
        val shown = Hanzi.scripts(listOf("我的头发", "你回来了", "这是個例子"))
        assertEquals(mapOf("我的头发" to "我的頭髮", "你回来了" to "你回來了", "这是個例子" to "這是個例子"), shown.getValue("traditional"))
        assertEquals(mapOf("这是個例子" to "这是个例子"), shown.getValue("simplified"))
        // Each table keeps the texts' order, as the page writes it.
        assertEquals(listOf("我的头发", "你回来了", "这是個例子"), shown.getValue("traditional").keys.toList())
    }

    @Test fun aTextTheSameInEitherScriptOrWithoutChineseHasNone() {
        val none = mapOf("simplified" to emptyMap<String, String>(), "traditional" to emptyMap())
        assertEquals(none, Hanzi.scripts(listOf("你好", "la la la", "", "Hello 世界，ok 2!")))
        assertEquals(none, Hanzi.scripts(emptyList()))
    }

    @Test fun onlyChineseCharactersChangeAndATextKeepsItsLength() {
        assertEquals("Hello 頭髮，ok 2! [x]", Hanzi.converted(Config.S2TW, "Hello 头发，ok 2! [x]"))
        // OpenCC's answer of another length (a NUL ends a segment) is made again a character at a time.
        assertEquals("頭發\u0000頭發", Hanzi.converted(Config.S2TW, "头发\u0000头发"))
        assertEquals("岂", Hanzi.converted(Config.T2S, "\uF900"))
        assertEquals("𠀀頭髮", Hanzi.converted(Config.S2TW, "𠀀头发"))
    }

    @Test fun aNameIsJudgedAlone() {
        val names = Hanzi.names(listOf("斑馬", "张学友", "斑馬 · 张学友"))
        assertEquals(mapOf("斑馬" to "斑马", "斑馬 · 张学友" to "斑马 · 张学友"), names.getValue("simplified"))
        assertEquals(mapOf("张学友" to "張學友", "斑馬 · 张学友" to "斑馬 · 張學友"), names.getValue("traditional"))
    }

    @Test fun aConverterIsNoneWhereTheSheetShowsAsWritten() {
        assertNull(Hanzi.converter("traditional", traditional = true))
        assertEquals("头发", Hanzi.converter("simplified", traditional = true)!!("頭髮"))
        assertEquals("头发", Hanzi.converter("simplified", traditional = false)!!("頭髮"))
        assertEquals("頭髮", Hanzi.converter("traditional", traditional = false)!!("头发"))
    }
}
