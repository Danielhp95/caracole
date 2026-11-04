package io.github.danielhp95.caracole.viewer.chinese

import io.github.danielhp95.caracole.viewer.testing.replays.ChineseReplay
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** viewer.chinese.ViewerPinyin is viewer/pinyin.py: every record of vectors/viewer/pinyin_page.jsonl (ChineseReplay),
 * and the readings test_viewer_pinyin.py names. */
class ViewerPinyinTest {
    @Test fun everyRecordIsPinyinPys() = ChineseReplay.everyPinyinPageRecordIsPinyinPys()

    private val banma = listOf("bān", "mǎ", "bān", "mǎ", "", "nǐ", "bú", "yào", "shuì", "zháo", "la")

    @Test fun aLineIsReadInContextAReadingForEachCharacter() {
        assertEquals(listOf(banma), ViewerPinyin.readings(listOf("斑马斑马 你不要睡着啦")))
        // pypinyin alone reads 著 as zhù: in a Traditional sheet it is 着.
        assertEquals(listOf(banma), ViewerPinyin.readings(listOf("斑馬斑馬 你不要睡著啦")))
        assertEquals(listOf(listOf("cháng", "chéng"), listOf("chéng", "zhǎng")),
                     ViewerPinyin.readings(listOf("長城", "成長")))
    }

    @Test fun inATraditionalSheetAZhuWordKeepsItsZhu() {
        assertEquals(listOf(
            listOf("kě", "wǒ", "làng", "fèi", "zhe", "wǒ", "hán", "lěng", "de", "nián", "huá"),
            listOf("xiǎn", "zhù", "", "zhù", "míng", "", "zháo", "jí", "", "zhí", "zhuó"),
            listOf("tā", "men", "shuì", "zháo", "le"),
        ), ViewerPinyin.readings(listOf("可我浪費著我寒冷的年華", "顯著 著名 著急 執著", "他們睡著了")))
        assertEquals(listOf(listOf("zhù", "míng", "de", "gē"), listOf("wǒ", "men", "shuì", "zháo", "le")),
                     ViewerPinyin.readings(listOf("著名的歌", "我们睡着了")))
    }

    @Test fun whatHasNoReadingIsEmptyALineWithoutChineseIsNullAndASheetWithoutAnyHasNone() {
        assertEquals(listOf(listOf("", "", "", "", "", "", "shì", "jiè", "", "", "", "", "", "")),
                     ViewerPinyin.readings(listOf("Hello 世界，ok 2!")))
        assertEquals(listOf(listOf("bān", "mǎ"), null, null), ViewerPinyin.readings(listOf("斑马", "la la", "")))
        assertNull(ViewerPinyin.readings(listOf("la la la", "Hello")))
        assertNull(ViewerPinyin.readings(emptyList()))
        // 〇 is pypinyin's Han, no Chinese character of normalize.py's: no reading shown.
        assertEquals(listOf(listOf("", "", "qī")), ViewerPinyin.readings(listOf("〇〇七")))
    }

    @Test fun aJapaneseSheetHasNone() {
        assertNull(ViewerPinyin.readings(listOf("夢を見た", "空")))
        assertFalse(ViewerPinyin.isChinese(listOf("夢を見た", "空")))
        assertTrue(ViewerPinyin.isChinese(listOf("约翰・列侬")))  // a name's dot is Chinese's too
        assertEquals(listOf(listOf("yuē", "hàn", "", "liè", "nóng")), ViewerPinyin.readings(listOf("约翰・列侬")))
    }

    @Test fun aReadingHasItsToneMarks() {
        assertEquals(listOf(listOf("lǜ", "sè", "nǚ", "ér", "zhǐ")), ViewerPinyin.readings(listOf("绿色女儿只")))
    }
}
