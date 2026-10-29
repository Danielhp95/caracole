#!/usr/bin/env python3
"""Probe a candidate source politely and write what caracole needs to know about it, as Markdown.

    python3 probe_site.py https://example.com [--max-requests 10] [--out report.md]

Asks, in this order and only what robots.txt allows, with caracole's own user agent and at least 6 s apart (more if
the site's Crawl-delay says so): robots.txt, the home page, the sitemap (a content child of an index, and its first
child when it is an index too), one content page from it, the site's terms page, and its policy for AI agents
(`/ai.txt`, `/llms.txt`) if it has one. Stops at the first 403, 429 or challenge page and says so. About 8–11
requests.

It reports facts for the owner's go/no-go, never a verdict: the robots rules (caracole's group or `*`), the
Crawl-delay, other agents named (AI crawlers), the sitemaps and their size, URL shapes, what a content page carries
to anyone (JSON blocks, `<pre>` blocks, text), the server and any bot protection seen, the terms' sentences about
bots, scraping, copying, downloads, accounts and paid features, and the AI policy as written.
"""

from __future__ import annotations

import argparse
import collections
import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _polite import LOC, Blocked, Polite, gunzip_if_needed  # noqa: E402

TERMS_LINK = re.compile(r'href="([^"#]*(?:terms|tos|legal|conditions|copyright|dmca|disclaimer)[^"#]*)"', re.I)
TERMS_WORDS = re.compile(
    r"scrap|bot\b|bots\b|crawl|spider|robot|automat|harvest|mirror|reproduc|redistribut|copy|download|"
    r"commercial|permission|account|log ?in|personal use|copyright|dmca|license|subscription|paid|premium", re.I)
TERMS_URL = re.compile(r"terms|tos\b|legal|conditions|copyright|dmca", re.I)
STATIC_CHILD = re.compile(r"static|misc|pages?\b|main\b", re.I)
CONTENT_CHILD = re.compile(r"tab|song|chord|sheet|score|lyric|track|music", re.I)
AI_POLICIES = ("/ai.txt", "/llms.txt")
JSON_BLOCK = re.compile(r'<script\b([^>]*type="application/(?:ld\+)?json"[^>]*)>(.*?)</script>', re.S | re.I)
PROTECTION_HEADERS = ("cf-ray", "cf-cache-status", "x-sucuri-id", "x-akamai", "x-amz-cf-id", "x-datadome",
                      "x-px", "x-iinfo", "server-timing")


def shapes(urls: list[str], limit: int = 12) -> list[tuple[str, int]]:
    """URL paths with their varying parts as <…>, the commonest first: a site's URL scheme at a glance."""
    count: collections.Counter[str] = collections.Counter()
    for url in urls:
        parts = urllib.parse.urlsplit(url).path.strip("/").split("/")
        shape = "/".join("<n>" if p.isdigit() else ("<slug>" if i else p) for i, p in enumerate(parts))
        count["/" + shape] += 1
    return count.most_common(limit)


BOT_WORDS = re.compile(r"scrap|\bbots?\b|crawl|spider|robot|\bautomated\b|automation|harvest|mirror", re.I)


def ends_closed(body: bytes) -> str:
    """Whether a sitemap ends with its closing tag: one cut short is a server's error, never the whole list."""
    tail = body.rstrip()[-200:]
    return "yes" if b"</urlset>" in tail or b"</sitemapindex>" in tail else "no"


def carries(page: str) -> list[str]:
    """What a content page holds before any script runs: its JSON blocks (where a modern site keeps the data its
    player or app draws), its `<pre>` blocks (a text tab), and its visible text. A tab or sheet missing here is
    fetched later from an API, which robots.txt often closes: then the page alone can't give it."""
    found = []
    for attrs, body in JSON_BLOCK.findall(page):
        name = re.search(r'id="([^"]+)"', attrs)
        found.append(f"a JSON block{' `' + name.group(1) + '`' if name else ''} of {len(body):,} characters")
    pres = re.findall(r"<pre\b[^>]*>(.*?)</pre>", page, re.S | re.I)
    if pres:
        found.append(f"{len(pres)} `<pre>` block(s), {sum(len(p) for p in pres):,} characters")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>|<style.*?</style>", " ",
                                                                page, flags=re.S | re.I)))
    found.append(f"{len(text.strip()):,} characters of visible text")
    return found


def sentences(text: str) -> list[str]:
    """The terms' sentences that bear on caracole, those about bots first. A list item, a paragraph or a heading
    ends a sentence too (legal pages list their prohibitions without full stops), and a long one is cut to the
    words around its match."""
    plain = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
    plain = re.sub(r"</?(?:li|p|br|h\d|tr|div|dd|dt)\b[^>]*>", " ¶ ", plain, flags=re.I)
    plain = re.sub(r"<[^>]+>", " ", plain)
    plain = re.sub(r"&quot;", '"', re.sub(r"&amp;", "&", plain))
    plain = re.sub(r"\s+", " ", plain)
    found = []
    for s in re.split(r"(?<=[.!?])\s+|\s*¶\s*", plain):
        s = s.strip()
        match = TERMS_WORDS.search(s)
        if not match or len(s) < 20:
            continue
        if len(s) > 400:
            start = max(0, match.start() - 150)
            s = ("…" if start else "") + s[start:start + 400] + "…"
        found.append(s)
    found.sort(key=lambda s: not BOT_WORDS.search(s))  # the clauses about bots first
    return found[:40]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site")
    parser.add_argument("--max-requests", type=int, default=12)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    out: list[str] = []
    say = out.append
    site = Polite(args.site, max_requests=args.max_requests)
    r = site.robots
    say(f"# {site.host}: a probe for caracole\n")
    say(f"Asked with caracole's own user agent, {site.delay:g} s apart at least.\n")
    say("## robots.txt\n")
    say(f"- Answer: {site.robots_answer.status}"
        + (f", Last-Modified {site.robots_answer.headers.get('Last-Modified')}"
           if site.robots_answer.headers.get('Last-Modified') else ""))
    say(f"- Crawl-delay: {r.crawl_delay if r.crawl_delay is not None else 'none'}")
    say(f"- Allow ({len(r.allow)}): " + (", ".join(f"`{a}`" for a in r.allow[:20]) or "none"))
    say(f"- Disallow ({len(r.disallow)}): " + ", ".join(f"`{d}`" for d in r.disallow[:40]))
    say(f"- Sitemaps: " + (", ".join(r.sitemaps) or "none named"))
    shut = [a for a, d in r.named_agents.items() if "/" in d]
    if shut:
        say(f"- Agents shut out entirely: {', '.join(sorted(shut))}")
    say("")

    try:
        home = site.get("/")
        say("## Home page\n")
        say(f"- Answer: {home.status}, Server: {home.headers.get('Server', '?')}")
        seen = [h for h in PROTECTION_HEADERS if any(k.lower() == h for k in home.headers)]
        say(f"- Bot protection headers: {', '.join(seen) or 'none seen'}")
        terms_links = sorted({urllib.parse.urljoin(site.root + '/', m) for m in TERMS_LINK.findall(home.text)})
        say(f"- Terms/legal links on the home page: {', '.join(terms_links) or 'none'}\n")

        sitemap = r.sitemaps[0] if r.sitemaps else site.root + "/sitemap.xml"
        if site.robots.allowed(site.path_of(sitemap)):
            smap = site.get(sitemap)
            body = gunzip_if_needed(smap.body).decode("utf-8", "replace")
            locs = LOC.findall(body)
            say("## Sitemap\n")
            say(f"- {sitemap}: {smap.status}, {'an index of' if '<sitemapindex' in body else 'a list of'} {len(locs):,} entries"
                f"{', ETag ' + smap.headers['ETag'] if 'ETag' in smap.headers else ''}")
            if "<sitemapindex" in body and locs:
                say("- Children: " + ", ".join(locs[:10]) + (" …" if len(locs) > 10 else ""))
                # A content child for the URL shapes: one named for tabs or songs, else any that isn't a static or
                # misc page list; when it is an index too (songsterr.com's sitemap-tabs.xml, of 1,116), its first.
                content = ([u for u in locs if CONTENT_CHILD.search(u) and not STATIC_CHILD.search(u)]
                           or [u for u in locs if not STATIC_CHILD.search(u)] or locs)
                child_url = content[0]
                child = site.get(child_url)
                unzipped = gunzip_if_needed(child.body)
                child_locs = LOC.findall(unzipped.decode("utf-8", "replace"))
                if b"<sitemapindex" in unzipped[:2000] and child_locs:
                    say(f"- {child_url}: {child.status}, itself an index of {len(child_locs):,} sitemaps")
                    child_url = child_locs[0]
                    child = site.get(child_url)
                    unzipped = gunzip_if_needed(child.body)
                    child_locs = LOC.findall(unzipped.decode("utf-8", "replace"))
                say(f"- {child_url}: {child.status}, {len(child_locs):,} URLs, closed by its end tag: "
                    f"{ends_closed(unzipped)}")
                statics = [u for u in locs if STATIC_CHILD.search(u)]
                if not terms_links and statics:  # the legal pages are usually listed there
                    static = site.get(statics[0])
                    found = LOC.findall(gunzip_if_needed(static.body).decode("utf-8", "replace"))
                    terms_links = [u for u in found if TERMS_URL.search(u)]
                    say(f"- {statics[0]}: {static.status}, {len(found):,} URLs; legal pages: "
                        + (", ".join(terms_links) or "none"))
                locs = child_locs
            terms_links = terms_links or [u for u in locs if TERMS_URL.search(u)]
            say("- URL shapes (commonest first): " + "; ".join(f"`{s}` ×{n:,}" for s, n in shapes(locs)))
            say("- Samples: " + ", ".join(locs[:3] + locs[len(locs) // 2:len(locs) // 2 + 2]) + "\n")
            pages = [u for u in locs if not u.endswith((".xml", ".xml.gz")) and site.robots.allowed(site.path_of(u))]
            if pages:
                sample = site.get(pages[0])
                say(f"## A content page: {pages[0]}\n")
                say(f"- Answer: {sample.status}. What it carries to anyone, before any script runs:")
                for line in carries(sample.text):
                    say(f"  - {line}")
                say("- Read it yourself: is what caracole would keep (a tab, a sheet, its notes) in it, or does the "
                    "page's script fetch it later, from a route robots.txt may close?\n")

        terms_links = sorted(terms_links, key=lambda u: (not re.search(r"terms|tos", u, re.I), len(u)))
        for link in terms_links[:1]:
            if site.robots.allowed(site.path_of(link)):
                terms = site.get(link)
                say(f"## Terms: {link}\n")
                say(f"- Answer: {terms.status}. Sentences about bots, copying, downloads and accounts:\n")
                for s in sentences(terms.text):
                    say(f"  > {s}\n")

        say("## Policy for AI agents\n")  # a site's own word to automated agents, beside its terms (songsterr.com's)
        for policy in AI_POLICIES:
            if not site.robots.allowed(policy):
                say(f"- {policy}: closed by robots.txt, not asked")
                continue
            answer = site.get(policy)
            if answer.status == 200 and "text/html" not in answer.headers.get("Content-Type", ""):
                say(f"- {policy}: 200, {len(answer.body):,} bytes. As written:\n")
                say("```\n" + answer.text[:4000].strip() + ("\n…" if len(answer.text) > 4000 else "") + "\n```\n")
                break
            say(f"- {policy}: {answer.status}{', an HTML page' if answer.status == 200 else ''}")
    except Blocked as blocked:
        say(f"\n**Blocked:** {blocked}. caracole treats this as a block; nothing more was asked.")
    except PermissionError as closed:
        say(f"\n**Closed by robots.txt:** {closed}")
    except RuntimeError as spent:
        say(f"\n**Stopped:** {spent}")

    say(f"\n_{site.made} requests made._")
    report = "\n".join(out)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"Wrote {args.out}", file=sys.stderr)
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
