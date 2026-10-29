---
name: add-source
description: Add a new website as a source to caracole (a new provider of chord sheets, text tabs, Guitar Pro files, harmonica or game-music tabs, scores or lyrics), from research to an index on the owner's NixOS service. Use this whenever the owner asks to add, index, scrape, pull from, or "investigate adding" a site to caracole ("add gametabs.net as a source", "can caracole get tabs from songsterr", "index X too"), or when a conversation turns to building a new provider like harptabs.com or gametabs.net, even if the word "source" isn't used.
---

# Adding a source to caracole

caracole has gained two sources this way: harptabs.com (harmonica tabs) and gametabs.net (game music tabs). Both
went through the same five phases. This skill holds what they taught, and scripts for the parts that repeat.

The repo's AGENTS.md is the authority: its Invariants (Politeness, Errors are never misses, the synced library, the
schema) bind every source. Read it before building, and read the newest source's modules (`gametabs*.py`) as the
model. They show caracole's prose style and patterns better than any summary.

## Phase 1: research, then the owner's go/no-go

First look for an earlier decision on the site: `git grep -n -i <site> origin/main -- plan.md AGENTS.md docs/`.
plan.md had already made Songsterr "links only" and named its downloader among the paywall tools caracole never
uses, which settled half the question before any request.

Then probe the site. The script asks about 8–11 pages, with caracole's own user agent, at least 6 s apart, robots.txt
honoured, redirects followed one checked hop at a time:

    python3 .claude/skills/add-source/scripts/probe_site.py https://<site> --out <scratchpad>/<site>-probe.md

It reports robots.txt (rules, Crawl-delay, sitemaps, agents shut out), the server and any bot protection, the
sitemap's size and URL shapes, what one content page carries before any script runs (JSON blocks, `<pre>` blocks,
text), the terms' sentences about bots, copying, downloads, accounts and paid features, and the site's policy for AI
agents (`/ai.txt`, `/llms.txt`) as written. A 403, a 429 or a challenge stops it. That is a block, and a source
caracole can't read.

Any page more goes through `fetch_fixtures.py` into the scratchpad (same pace, user agent and checks), never curl
by hand or WebFetch: WebFetch sends another user agent, so point it at third parties' pages about the site, never at
the site. Keep pages that hold a song's lyrics or notes in the scratchpad, out of every report. When a third party
says something about the site (an API "open and keyless"), check it with one request or say it is unchecked:
songsterr.com's old search, said to be open, answered 404.

For a site worth a closer look, or when the owner asks for research, run the deep-research workflow on it (they have
used `/deep-research`). Fold the probe into the brief. Write the result to
`.superpowers/reports/<site> as a caracole source.md`, as was done for gametabs.net, and send it to the owner.

What the owner needs to decide, put plainly:
- **What it holds:** formats, instruments, size, activity, and what needs an account (caracole never logs in, so
  login-only files are out of reach).
- **Whether the thing caracole would keep is in the page itself.** Many sites send a shell and a JSON block, and the
  player fetches the notes from an API robots.txt closes (songsterr.com's tab pages: `part.current` null, the notes
  under `/api/`). Then the page alone can't give it, whatever the terms say.
- **Whether robots.txt allows** the pages caracole would read, and its Crawl-delay.
- **Its terms:** quote them. The owner's rule (AGENTS.md, since 2026-10-28) is that a site's terms against
  automated access don't stop caracole where the owner explicitly chose that site; harptabs.com and gametabs.net
  are the two so far. That is the owner's decision each time, never yours: report the terms, recommend, and wait.
  A clause against getting a paid feature's equivalent (a download, a print) is another line: caracole never works
  around a paywall (plan.md, "No paywalls"), whoever chose the site. Say which kind each clause is.
- **How a wanted.txt line ("Artist - Title") would match its pages:** game music is filed by game and composer,
  not by performer; an ASCII slug can drop a non-Latin name entirely.
- **What it adds for the owner's own songs:** read the service's wanted.txt (`/var/lib/caracole/library/`) and look
  for a few of them there (a web search limited to the site, or the sitemaps), above all songs UG and LaCuerda lack.

Everything else binds every site, chosen or not: robots.txt, the pace and budgets, caracole's own user agent, one
request at a time, no login, no closed API, and a block is a block. Never another user agent, cookies, proxies or a
captcha. The owner once asked to circumvent harptabs.com's search block; that was refused, and the index route was
built instead.

## Phase 2: a branch of its own, and fixtures

Work on a branch of its own from `origin/main`, in a worktree under the session's scratchpad. The owner's checkout
often has another session's uncommitted work: don't stash it or build in it.

    git -C /home/dani/Projects/caracole fetch -q origin
    git -C /home/dani/Projects/caracole worktree add -b <site> <scratchpad>/wt/<site> origin/main

Capture fixtures once, politely: robots.txt, the sitemap index and a trimmed child, one or two listing pages, two
content pages (one with a repeat suffix or an edge case):

    python3 .claude/skills/add-source/scripts/fetch_fixtures.py https://<site> tests/fixtures/<site>/ /sitemap.xml /a/page …

Then trim them to what the parser reads (a few cards, not fifty), and scramble the prose so no tab, lyric or note
is committed whole. Keep the lines the parser keys on:

    python3 .claude/skills/add-source/scripts/scramble_fixture.py tab.html -o tab.html --keep '^\s*<' --keep '<pattern of the lines to keep>'

Fixtures are the only live requests a source's build makes. The tests never make one; that is an invariant.

## Phase 3: build it, tests first

See every place the newest source plugs in, straight from the code:

    python3 .claude/skills/add-source/scripts/touchpoints.py gametabs          # add --tests for the tests too

Then read `references/checklist.md`. It says what each touch point is for, the decisions to make first (what file
is kept, how a line matches, where the index comes from, the budget), and how gametabs.net and harptabs.com answered
them.

Write a failing test before each piece (AGENTS.md: "Test first"). Use a fake site behind a real `PoliteClient`
(`tests/helpers/<site>_site.py`, `httpx.MockTransport`). Commit in conventional, scoped steps (`docs(agents): …`,
`feat(<site>): …`, `feat(search): …`), never with any AI attribution.

When the work is big, as both sources were (around 60 files), it can go to one subagent with this skill's path and
the decisions settled. A second lane that touches the library page's search parts collides with it, so keep it one
lane.

## Phase 4: land it

- **Before merging:** `git fetch origin && git merge origin/main`, so the final runs see what other sessions
  landed.
- **Run:** `nix develop -c pytest -q` (the whole suite; a browser test that fails under load is rerun alone before
  it's trusted), then `nix flake check`.
- **Push from the worktree:** `GH_TOKEN="$(gh auth token --user Danielhp95)" git push origin <site>:main`. That is
  a fast-forward. If it isn't one, merge `origin/main` again first, and never force.
- **If another session works in the checkout,** tell it (SendMessage) that `origin/main` moved and which files may
  conflict.

## Phase 5: deploy and index

caracole runs as a NixOS service on the owner's laptop (`~/nix_config/nixos/caracole.nix`, data in
`/var/lib/caracole`). Updating it needs sudo, so give the owner the commands, using `!` to run them in the session:

    ! cd ~/nix_config && nix flake update caracole
    ! sudo nixos-rebuild switch --flake ~/nix_config#lenovo
    ! sudo caracole-admin <site> --index --budget <N>

Estimate the index's length (pages × the delay's mean: 1,700 pages at 15 s is about 7 hours). It holds caracole's
lock, so start it well before the nightly run (`systemctl list-timers caracole.timer`), or run it in steps with the
default budget, each continuing where the last stopped. `sudo caracole-admin index stats` shows progress. Never run
a dev `caracole serve` on 8737, which is the service's; use 8738 or higher.

To confirm the deploy: `~/nix_config/flake.lock`'s caracole `rev` is the pushed commit, and `pgrep -af
'caracole.*<site>'` shows the index running.

## Report to the owner

After each phase, tell the owner in a few lines what happened and what they need to decide or run:
- Phase 1: the facts and the terms, with a recommendation.
- Phase 3: what was built, the counts, and any calls made.
- Phase 4: the commit on `main`, the suite line and the flake check.
- Phase 5: the commands, and how long the index takes.
