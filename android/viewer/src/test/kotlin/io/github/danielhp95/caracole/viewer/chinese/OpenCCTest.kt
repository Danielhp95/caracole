package io.github.danielhp95.caracole.viewer.chinese

import io.github.danielhp95.caracole.viewer.chinese.OpenCC.Config
import io.github.danielhp95.caracole.viewer.testing.replays.ChineseReplay
import org.junit.Test
import kotlin.test.assertEquals

/** viewer.chinese.OpenCC converts as OpenCC 1.4 does for hanzi.py: every record of vectors/viewer/opencc.jsonl
 * (ChineseReplay), and its rules by name. */
class OpenCCTest {
    @Test fun theDataIsOfTheOpenCCThisPorts() {
        // OpenCC.kt ports OpenCC 1.4's config, segmentation and conversion: read a new version's before changing this.
        assertEquals("1.4.0", OpenCC.VERSION)
        assertEquals("1.4.1", OpenCC.PACKAGE)
    }

    @Test fun everyRecordIsOpenCCs() = ChineseReplay.everyOpenCCRecordIsOpenCCs()

    @Test fun simplifiedIntoTraditionalIsOneToManyWordByWord() {
        assertEquals("我的頭髮 發現", OpenCC.convert(Config.S2TW, "我的头发 发现"))
        assertEquals("後來 皇后 乾淨 幹活 干涉", OpenCC.convert(Config.S2TW, "后来 皇后 干净 干活 干涉"))
        assertEquals("你不要睡著啦", OpenCC.convert(Config.S2TW, "你不要睡着啦"))  // Taiwan's standard writes 著
    }

    @Test fun traditionalIntoSimplifiedReadsEachWordToo() {
        assertEquals("斑马斑马 你不要睡着啦", OpenCC.convert(Config.TW2S, "斑馬斑馬 你不要睡著啦"))
        assertEquals("著名 干净 乾坤", OpenCC.convert(Config.T2S, "著名 乾淨 乾坤"))
        assertEquals("为 里", OpenCC.convert(Config.TW2S, "爲 裏"))  // the OpenCC standard's variants, read too
    }

    @Test fun aCompatibilityIdeographIsNormalizedFirst() {
        assertEquals("岂", OpenCC.convert(Config.T2S, "\uF900"))
        assertEquals("豈", OpenCC.convert(Config.S2TW, "\uF900"))
    }

    @Test fun anIdeographicDescriptionSequenceIsWrittenWholeAsItIs() {
        assertEquals("⿰氵發后", OpenCC.convert(Config.T2S, "⿰氵發後"))
        assertEquals("⿰氵後", OpenCC.convert(Config.T2S, "⿰氵後"))  // 後 is an operand: the IDS is whole
        assertEquals("⿰发", OpenCC.convert(Config.T2S, "⿰發"))  // cut short: no IDS, each character its own
        assertEquals("⿲木木木", OpenCC.convert(Config.S2TW, "⿲木木木"))
    }

    @Test fun aSegmentHoldingANulEndsThereWhereTheConfigSegments() {
        assertEquals("头发\u0000头发", OpenCC.convert(Config.T2S, "头发\u0000头发"))
        assertEquals("头发", OpenCC.convert(Config.TW2S, "头发\u0000头发"))
        assertEquals("頭髮頭髮", OpenCC.convert(Config.S2TW, "头发\u0000头发"))
        assertEquals("", OpenCC.convert(Config.TW2S, "\u0000头发"))
        assertEquals("a", OpenCC.convert(Config.S2TW, "a\u0000b"))
    }

    @Test fun whateverElseATextHoldsStaysAsItIs() {
        for (config in Config.entries) {
            assertEquals("", OpenCC.convert(config, ""))
            assertEquals("Hello, world! 😀 가 か", OpenCC.convert(config, "Hello, world! 😀 가 か"))
        }
    }
}
