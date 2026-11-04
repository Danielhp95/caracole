package io.github.danielhp95.caracole.core.html.internal.tree

/**
 * core.html's document tree, as lexbor keeps one (lexbor/dom/): nodes linked to their parent and siblings, so that
 * the tree builder moves them (the adoption agency, foster parenting) and selectolax's `replace_with` and
 * `insert_after` change them in place. A `<template>`'s contents are a fragment of their own, [Element.content],
 * which no walk of the tree reaches: selectolax shows a template with no children.
 */
internal abstract class Node {
    var parent: Node? = null
        private set
    var prev: Node? = null
        private set
    var next: Node? = null
        private set
    var firstChild: Node? = null
        private set
    var lastChild: Node? = null
        private set

    /** [child] as this node's last child, taken from wherever it was. */
    fun append(child: Node) {
        child.remove()
        child.parent = this
        child.prev = lastChild
        lastChild?.next = child
        lastChild = child
        if (firstChild == null) firstChild = child
    }

    /** [node] as this node's previous sibling, taken from wherever it was. */
    fun insertBefore(node: Node) {
        val parent = checkNotNull(parent) { "no parent to insert before" }
        node.remove()
        node.parent = parent
        node.next = this
        node.prev = prev
        if (prev == null) parent.firstChild = node else prev!!.next = node
        prev = node
    }

    /** [node] as this node's next sibling, taken from wherever it was. */
    fun insertAfter(node: Node) {
        val after = next
        if (after != null) after.insertBefore(node)
        else checkNotNull(parent) { "no parent to insert after" }.append(node)
    }

    /** This node out of its parent, its children with it. */
    fun remove() {
        val parent = parent ?: return
        if (prev == null) parent.firstChild = next else prev!!.next = next
        if (next == null) parent.lastChild = prev else next!!.prev = prev
        this.parent = null
        prev = null
        next = null
    }
}

/** The namespaces of the elements the tree builder makes. */
internal enum class Ns { HTML, MATH, SVG }

internal class Document : Node() {
    /** lexbor's compat mode: only quirks mode changes how `#id` and `.class` match. */
    var quirks = false
    var limitedQuirks = false
}

/** A `<template>`'s contents. */
internal class Fragment : Node()

/**
 * An element: [local], the tag name as the tokenizer gives it (ASCII-lowercased), which every rule of the tree
 * builder compares as lexbor compares tag ids; [name], the name selectolax shows (an SVG element's in its own case:
 * `clipPath`).
 */
internal class Element(val local: String, val ns: Ns, val name: String = local) : Node() {
    val attributes = ArrayList<Attr>()

    /** A `<template>`'s contents (HTML templates alone). */
    val content: Fragment? = if (local == "template" && ns == Ns.HTML) Fragment() else null

    /** The first attribute of that local name (lexbor's `lxb_dom_element_attr_by_id`). */
    fun attr(local: String): Attr? = attributes.firstOrNull { it.local == local }

    fun isHtml(tag: String) = ns == Ns.HTML && local == tag

    override fun toString() = "<$name>"
}

/**
 * An attribute: [local], its name as written (ASCII-lowercased) or the local part of an adjusted foreign one
 * (`xlink:href`'s `href`); [qualified], the adjusted name where the tree builder set one (`viewBox`, `xlink:href`,
 * `definitionURL`), else null; [value], null where none was written; [ns], the namespace lexbor gives it (its
 * element's, or `xlink`, `xml` or `xmlns` for an adjusted foreign one), which only the check for a duplicate reads.
 */
internal class Attr(val local: String, val qualified: String?, val value: String?, val ns: String) {
    /** The name selectolax shows. */
    val name: String get() = qualified ?: local

    override fun toString() = "$name=$value"
}

internal class Text(initial: String) : Node() {
    private val data = StringBuilder(initial)
    private var cached: String? = initial

    val text: String get() = cached ?: data.toString().also { cached = it }

    fun add(more: String) {
        data.append(more)
        cached = null
    }
}

internal class Comment(val data: String) : Node()

internal class ProcessingInstruction(val target: String, val data: String) : Node()

internal class DoctypeNode(val name: String?, val publicId: String?, val systemId: String?) : Node()
