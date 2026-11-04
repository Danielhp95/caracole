/*
 * Ported to Kotlin from lexbor 3.1.0's lexbor/html/tag_res.h and lexbor/html/tree_res.h and changed for caracole.
 * Copyright (C) 2018-2026 Alexander Borisov. Licensed under the Apache License, Version 2.0:
 * ../LICENSE-lexbor, with lexbor's NOTICE.
 */
package io.github.danielhp95.caracole.core.html.internal.tree

/**
 * What the tree builder knows of each tag, as lexbor 3.1.0 has it (lexbor/html/tag_res.h and tree_res.h, generated
 * there from the WHATWG lists): each tag's categories in each namespace, an SVG element's name in its own case and
 * the foreign attributes' adjusted names.
 *
 * lexbor makes `<select>` a scope like `<table>` (the customizable select's parsing, which has no "in select"
 * insertion mode): a button or a `<p>` outside a select is not in scope inside it.
 */
internal object Tags {
    const val SPECIAL = 1
    const val FORMATTING = 2
    const val SCOPE = 4
    const val SCOPE_LIST_ITEM = 8
    const val SCOPE_BUTTON = 16
    const val SCOPE_TABLE = 32

    private val HTML = table(
        "a:F address:S applet:BCLS area:S article:S aside:S b:F base:S basefont:S bgsound:S big:F blockquote:S " +
            "body:S br:S button:BS caption:BCLS center:S code:F col:S colgroup:S dd:S details:S dir:S div:S dl:S " +
            "dt:S em:F embed:S fieldset:S figcaption:S figure:S font:F footer:S form:S frame:S frameset:S h1:S h2:S " +
            "h3:S h4:S h5:S h6:S head:S header:S hgroup:S hr:S html:BCLST i:F iframe:S image:S img:S input:S " +
            "keygen:S li:S link:S listing:S main:S marquee:BCLS menu:S meta:S nav:S nobr:F noembed:S noframes:S " +
            "noscript:S object:BCLS ol:LS p:S param:S plaintext:S pre:S s:F script:S search:S section:S " +
            "select:BCLS small:F source:S strike:F strong:F style:S summary:S table:BCLST tbody:S td:BCLS " +
            "template:BCLST textarea:S tfoot:S th:BCLS thead:S title:S tr:S track:S tt:F u:F ul:LS wbr:S xmp:S",
    )
    private val MATH = table("annotation-xml:BCLS mi:BCLS mn:BCLS mo:BCLS ms:BCLS mtext:BCLS")
    private val SVG = table("desc:BCLS foreignobject:BCLS title:BCLS")

    private fun table(rows: String): Map<String, Int> = rows.split(' ').associate { row ->
        val (tag, code) = row.split(':')
        tag to code.fold(0) { bits, c ->
            bits or when (c) {
                'S' -> SPECIAL
                'F' -> FORMATTING
                'C' -> SCOPE
                'L' -> SCOPE_LIST_ITEM
                'B' -> SCOPE_BUTTON
                'T' -> SCOPE_TABLE
                else -> error("no category $c")
            }
        }
    }

    /** Whether the tag [local] of namespace [ns] is of [category] (lexbor's `lxb_html_tag_is_category`). */
    fun isCategory(local: String, ns: Ns, category: Int): Boolean {
        val table = when (ns) {
            Ns.HTML -> HTML
            Ns.MATH -> MATH
            Ns.SVG -> SVG
        }
        return (table[local] ?: 0) and category != 0
    }

    fun isCategory(element: Element, category: Int) = isCategory(element.local, element.ns, category)

    /** An SVG element's name in its own case (lexbor's `lxb_html_tag_res_fixname_svg`). */
    val SVG_NAMES: Map<String, String> = listOf(
        "altGlyph", "altGlyphDef", "altGlyphItem", "animateColor", "animateMotion", "animateTransform", "clipPath",
        "feBlend", "feColorMatrix", "feComponentTransfer", "feComposite", "feConvolveMatrix", "feDiffuseLighting",
        "feDisplacementMap", "feDistantLight", "feDropShadow", "feFlood", "feFuncA", "feFuncB", "feFuncG", "feFuncR",
        "feGaussianBlur", "feImage", "feMerge", "feMergeNode", "feMorphology", "feOffset", "fePointLight",
        "feSpecularLighting", "feSpotLight", "feTile", "feTurbulence", "foreignObject", "glyphRef", "linearGradient",
        "radialGradient", "textPath",
    ).associateBy { lower(it) }

    /** An SVG attribute's name in its own case (lexbor's `lxb_html_tree_res_attr_adjust_svg_map`). */
    val SVG_ATTRIBUTES: Map<String, String> = listOf(
        "attributeName", "attributeType", "baseFrequency", "baseProfile", "calcMode", "clipPathUnits",
        "diffuseConstant", "edgeMode", "filterUnits", "glyphRef", "gradientTransform", "gradientUnits",
        "kernelMatrix", "kernelUnitLength", "keyPoints", "keySplines", "keyTimes", "lengthAdjust",
        "limitingConeAngle", "markerHeight", "markerUnits", "markerWidth", "maskContentUnits", "maskUnits",
        "numOctaves", "pathLength", "patternContentUnits", "patternTransform", "patternUnits", "pointsAtX",
        "pointsAtY", "pointsAtZ", "preserveAlpha", "preserveAspectRatio", "primitiveUnits", "refX", "refY",
        "repeatCount", "repeatDur", "requiredExtensions", "requiredFeatures", "specularConstant", "specularExponent",
        "spreadMethod", "startOffset", "stdDeviation", "stitchTiles", "surfaceScale", "systemLanguage",
        "tableValues", "targetX", "targetY", "textLength", "viewBox", "viewTarget", "xChannelSelector",
        "yChannelSelector", "zoomAndPan",
    ).associateBy { lower(it) }

    /** The foreign attributes whose name has a prefix, by their name, to their local part (lexbor's
     * `lxb_html_tree_res_attr_adjust_foreign_map`; `xmlns` keeps its name). */
    val FOREIGN_LOCAL: Map<String, String> = mapOf(
        "xlink:actuate" to "actuate", "xlink:arcrole" to "arcrole", "xlink:href" to "href", "xlink:role" to "role",
        "xlink:show" to "show", "xlink:title" to "title", "xlink:type" to "type", "xml:lang" to "lang",
        "xml:space" to "space", "xmlns:xlink" to "xlink",
    )

    private fun lower(s: String) = buildString(s.length) { for (c in s) append(if (c in 'A'..'Z') c + 32 else c) }
}
