package io.github.danielhp95.caracole.viewer.chinese

import io.github.danielhp95.caracole.viewer.ViewerAssets
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * OpenCC as hanzi.py converts with it: `OpenCC(config, include_tofu_risk_dictionaries=False).convert(text)` for the
 * configs `t2s`, `tw2s` and `s2tw`, its algorithm ported from OpenCC's sources (Config.cpp, ConfigBasedConverter.hpp,
 * SingleStageConverter.cpp, MaxMatchSegmentation.cpp, ConversionChain.cpp, Conversion.cpp, PrefixMatch.cpp,
 * UTF8Util.hpp) over the dictionaries the dev shell's package ships, and its configs read as data
 * (tests/test_conformance_viewer_chinese.py writes both, and its docstring says each step):
 *
 * 1. A config's `normalization` chain converts the whole text, then its main stage runs: its `segmentation`, if any
 *    (`mmseg`), cuts the text, and its `conversion_chain` converts each segment, each conversion over the whole of
 *    what the one before wrote.
 * 2. A dictionary is an `ocd2` file or a `group` of them by its `match_policy`: `short_circuit` (the default), the
 *    first of its dictionaries that matches at all, or `union`, the longest match of any, the first on a tie. One
 *    marked `may_output_tofu` is left out (`TSCharactersExt`), and a group left with none is none, but in a
 *    segmentation, which Config.cpp reads with them all.
 * 3. A dictionary's match at a place is its longest key that begins there, with that key's first value.
 * 4. mmseg: where its dictionary matches, the key is a segment of its own; the characters between are one segment
 *    (an ideographic description sequence among them whole). A segment holding U+0000 ends there, as OpenCC hands
 *    each on as a C string; a text with no segmentation is whole.
 * 5. A conversion writes, from the start, the value of a key matched and passes the key; else a whole IDS that begins
 *    there as it is ([idsLength]); else one character.
 *
 * The data, caracole/hanzi/ on the classpath (a resource of :core): `opencc.json` (OpenCC's version, [VERSION], and
 * the three configs as the package ships them) and each dictionary's `<Name>.txt`, as opencc_dict writes one in text
 * (`<key>\t<value> <value> …` a line), read once on first use. Everything is on UTF-16 strings and code points, with
 * no JDK text API; a lone surrogate, which Python can't hand OpenCC, is a character of its own.
 */
object OpenCC {
    /** hanzi.py's three configs, by their file names. */
    enum class Config(val file: String) { T2S("t2s"), TW2S("tw2s"), S2TW("s2tw") }

    /** `opencc.__version__` of the OpenCC the data was dumped from (its distribution's: [PACKAGE]). */
    val VERSION: String get() = data.getValue("opencc").jsonPrimitive.content
    val PACKAGE: String get() = data.getValue("package").jsonPrimitive.content

    /** [text] as OpenCC's [config] converts it. */
    fun convert(config: Config, text: String): String = converter(config).convert(text)

    private val data: JsonObject by lazy {
        Json.parseToJsonElement(resource("opencc.json")) as? JsonObject
            ?: throw IllegalStateException("caracole/hanzi/opencc.json holds no JSON object")
    }
    private val converters = HashMap<Config, Converter>()
    private val leaves = HashMap<String, Leaf>()

    private fun converter(config: Config): Converter = synchronized(this) {
        converters.getOrPut(config) { load(data.getValue("configs").jsonObject.getValue(config.file).jsonObject) }
    }

    private fun load(config: JsonObject): Converter {
        fun chain(name: String): List<Dict> =
            config[name]?.jsonArray?.mapNotNull { dict(it.jsonObject.getValue("dict").jsonObject, tofu = false) }
                ?: emptyList()
        val segmentation = config["segmentation"]?.jsonObject?.let { spec ->
            val type = spec.getValue("type").jsonPrimitive.content
            require(type == "mmseg") { "OpenCC's $type segmentation isn't on the phone" }
            dict(spec.getValue("dict").jsonObject, tofu = true)
                ?: throw IllegalStateException("a segmentation with no dictionary")
        }
        require(config.containsKey("conversion_chain")) { "a config with no conversion_chain" }
        return Converter(chain("normalization"), config.containsKey("segmentation"), segmentation,
                         chain("conversion_chain"))
    }

    /** Config.cpp's ParseDict: a dictionary, or null for one left out ([tofu]: a tofu-risk one is kept). */
    private fun dict(spec: JsonObject, tofu: Boolean): Dict? {
        val mayOutputTofu = spec["may_output_tofu"]?.let {
            (it as? JsonPrimitive)?.booleanOrNull ?: throw IllegalStateException("may_output_tofu must be a bool")
        } ?: false
        if (mayOutputTofu && !tofu) return null
        return when (val type = spec.getValue("type").jsonPrimitive.content) {
            "group" -> {
                val children = spec.getValue("dicts").jsonArray.mapNotNull { dict(it.jsonObject, tofu) }
                if (children.isEmpty()) return null
                when (val policy = spec["match_policy"]?.jsonPrimitive?.content ?: "short_circuit") {
                    "short_circuit" -> ShortCircuit(children)
                    "union" -> Union(children)
                    else -> throw IllegalStateException("Unknown dictionary group match_policy: $policy")
                }
            }
            "ocd2" -> {
                val file = spec.getValue("file").jsonPrimitive.content
                require(file.endsWith(".ocd2") && '/' !in file) { "no dictionary of the phone's: $file" }
                leaves.getOrPut(file) { Leaf(file.removeSuffix(".ocd2")) }
            }
            else -> throw IllegalStateException("OpenCC's $type dictionaries aren't on the phone")
        }
    }

    private fun resource(name: String): String {
        val path = "caracole/hanzi/$name"
        val stream = OpenCC::class.java.classLoader?.getResourceAsStream(path)
            ?: OpenCC::class.java.getResourceAsStream("/$path")
            ?: throw IllegalStateException("$path is not on the classpath: its generator writes it (tests/conformance)")
        return ViewerAssets.strictUtf8(stream.use { it.readBytes() }, path)
    }

    /** A match: where the key ends in the text, and its value. */
    private class Match(val end: Int, val value: String)

    /** A dictionary: its longest key that begins at [at] in [text], or null. */
    private interface Dict {
        fun match(text: String, at: Int): Match?
    }

    /** An ocd2 file: its keys in UTF-16 order, each with its first value. A walk one code point at a time while
     * some key begins with what it read, as PrefixMatch's trie and marisa's common-prefix search find the longest. */
    private class Leaf(name: String) : Dict {
        private val keys: Array<String>
        private val values: Array<String>

        init {
            val text = resource("$name.txt")
            check(text.isEmpty() || text.endsWith('\n')) { "caracole/hanzi/$name.txt is not opencc_dict's" }
            val lines = if (text.isEmpty()) emptyList() else text.substring(0, text.length - 1).split('\n')
            val pairs = lines.mapIndexed { n, line ->
                val tab = line.indexOf('\t')
                check(tab > 0 && line.indexOf('\t', tab + 1) < 0) { "caracole/hanzi/$name.txt, line ${n + 1}" }
                val values = line.substring(tab + 1)
                val first = values.indexOf(' ').let { if (it < 0) values else values.substring(0, it) }
                check(first.isNotEmpty()) { "caracole/hanzi/$name.txt, line ${n + 1}" }
                line.substring(0, tab) to first
            }.sortedWith { a, b -> a.first.compareTo(b.first) }
            for (n in 1 until pairs.size) check(pairs[n].first != pairs[n - 1].first) { "$name.txt repeats a key" }
            keys = Array(pairs.size) { pairs[it].first }
            values = Array(pairs.size) { pairs[it].second }
        }

        override fun match(text: String, at: Int): Match? {
            var best: Match? = null
            var end = at
            var lo = 0
            while (end < text.length) {
                end += Character.charCount(text.codePointAt(end))
                lo = lowerBound(text, at, end, lo)
                val n = end - at
                if (lo == keys.size || keys[lo].length < n || !keys[lo].regionMatches(0, text, at, n)) break
                if (keys[lo].length == n) best = Match(end, values[lo])
            }
            return best
        }

        /** The first key not below text[at, end), from [from] on (a longer prefix sorts no earlier). */
        private fun lowerBound(text: String, at: Int, end: Int, from: Int): Int {
            var lo = from
            var hi = keys.size
            while (lo < hi) {
                val mid = (lo + hi) ushr 1
                if (compare(keys[mid], text, at, end) < 0) lo = mid + 1 else hi = mid
            }
            return lo
        }

        private fun compare(key: String, text: String, at: Int, end: Int): Int {
            val n = end - at
            for (j in 0 until minOf(key.length, n)) {
                val d = key[j] - text[at + j]
                if (d != 0) return d
            }
            return key.length - n
        }
    }

    /** A short_circuit group: the first of its dictionaries with any match, a shorter one of an earlier winning. */
    private class ShortCircuit(private val dicts: List<Dict>) : Dict {
        override fun match(text: String, at: Int): Match? {
            for (d in dicts) d.match(text, at)?.let { return it }
            return null
        }
    }

    /** A union group: the longest match of any of its dictionaries, the first of them on a tie. */
    private class Union(private val dicts: List<Dict>) : Dict {
        override fun match(text: String, at: Int): Match? {
            var best: Match? = null
            for (d in dicts) {
                val found = d.match(text, at) ?: continue
                if (best == null || found.end > best.end) best = found
            }
            return best
        }
    }

    private class Converter(
        private val normalization: List<Dict>, private val segmented: Boolean, private val segmentation: Dict?,
        private val chain: List<Dict>,
    ) {
        fun convert(text: String): String {
            val normalized = through(normalization, text)
            if (!segmented) return through(chain, normalized)
            val out = StringBuilder(normalized.length + normalized.length / 5)
            for (segment in segments(segmentation!!, normalized)) {
                val nul = segment.indexOf('\u0000')
                out.append(through(chain, if (nul < 0) segment else segment.substring(0, nul)))
            }
            return out.toString()
        }

        private fun through(dicts: List<Dict>, text: String): String {
            var converted = text
            for (d in dicts) converted = conversion(d, converted)
            return converted
        }

        /** Conversion.cpp's AppendConverted. */
        private fun conversion(d: Dict, phrase: String): String {
            val out = StringBuilder(phrase.length + phrase.length / 5)
            var at = 0
            while (at < phrase.length) {
                val found = d.match(phrase, at)
                if (found == null) {
                    val n = idsLength(phrase, at).takeIf { it > 0 } ?: Character.charCount(phrase.codePointAt(at))
                    out.append(phrase, at, at + n)
                    at += n
                } else {
                    out.append(found.value)
                    at = found.end
                }
            }
            return out.toString()
        }

        /** MaxMatchSegmentation.cpp's SegmentText. */
        private fun segments(d: Dict, text: String): List<String> {
            val out = ArrayList<String>()
            var start = 0
            var at = 0
            while (at < text.length) {
                val found = d.match(text, at)
                if (found == null) {
                    at += idsLength(text, at).takeIf { it > 0 } ?: Character.charCount(text.codePointAt(at))
                } else {
                    if (at > start) out.add(text.substring(start, at))
                    out.add(text.substring(at, found.end))
                    at = found.end
                    start = at
                }
            }
            if (at > start) out.add(text.substring(start, at))
            return out
        }
    }

    /** IDS operators (U+2FF0–2FFF) and their operands, as UTF8Util.hpp's IdeographicDescriptionOperatorArity. */
    private fun arity(cp: Int): Int = when (cp) {
        0x2FF2, 0x2FF3 -> 3
        0x2FFE, 0x2FFF -> 1
        in 0x2FF0..0x2FFD -> 2
        else -> 0
    }

    private const val IDS_DEPTH = 16
    private const val IDS_CODE_POINTS = 64

    /**
     * UTF8Util.hpp's NextIdeographicDescriptionSequenceLength: the length (UTF-16) of the whole IDS that begins at
     * [at] in [text], an operator and as many operands as it takes, each a character or an IDS, [IDS_DEPTH] deep and
     * [IDS_CODE_POINTS] code points at most; 0 for none, or one cut short.
     */
    private fun idsLength(text: String, at: Int): Int {
        if (at >= text.length || arity(text.codePointAt(at)) == 0) return 0
        var codePoints = 0
        fun consume(i: Int, depth: Int): Int {
            if (i >= text.length || depth == 0 || codePoints >= IDS_CODE_POINTS) return -1
            val cp = text.codePointAt(i)
            codePoints++
            var j = i + Character.charCount(cp)
            repeat(arity(cp)) {
                if (j >= text.length) return -1
                j = consume(j, depth - 1)
                if (j < 0) return -1
            }
            return j
        }
        val end = consume(at, IDS_DEPTH)
        return if (end < 0) 0 else end - at
    }
}
